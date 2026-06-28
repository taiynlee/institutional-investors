#!/usr/bin/env python3
"""
盤後分析腳本 — dry run 參數調整建議
自動於交易日 14:00 由 systemd timer 觸發
"""
import json
import os
import re
import sqlite3
import urllib.request
from datetime import date, datetime
from pathlib import Path
DB = Path(os.environ.get("FUBON_DATA_DIR", "/home/tommy0322/fubon-data")) / "ticks.db"
REPORT_DIR = Path(os.environ.get("FUBON_DATA_DIR", "/home/tommy0322/fubon-data")) / "analysis"
REPORT_DIR.mkdir(exist_ok=True)


def _api(path: str) -> dict | list:
    try:
        return json.loads(urllib.request.urlopen(f"http://localhost:8090{path}", timeout=5).read())
    except Exception:
        return {}



def _parse_exit_reason(content: str) -> str:
    m = re.search(r"原因=(\S+)", content)
    if not m:
        return "unknown"
    r = m.group(1)
    if "force" in r:
        return "force_exit"
    if "take_profit" in r:
        return "take_profit"
    return "stop_loss"


def analyze(target_date: str | None = None) -> dict:
    today = target_date or date.today().isoformat()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # ── 1. 當日交易紀錄 ──────────────────────────────────────────────
    trades = conn.execute(
        "SELECT * FROM intraday_trades WHERE trade_date=? AND dry_run=1 ORDER BY trade_time",
        (today,),
    ).fetchall()

    # ── 2. 持倉紀錄（取進場時間、停損停利）────────────────────────────
    positions = conn.execute(
        "SELECT * FROM intraday_positions WHERE trade_date=?",
        (today,),
    ).fetchall()
    pos_map = {p["symbol"]: dict(p) for p in positions}

    # ── 3. LINE 通知（解析出場原因）────────────────────────────────────
    notifs = conn.execute(
        """SELECT msg_type, content, sent_at FROM line_notifications
           WHERE msg_type IN ('dry_entry','dry_exit','force_exit','warning')
           AND date(sent_at,'localtime')=?
           ORDER BY sent_at""",
        (today,),
    ).fetchall()
    conn.close()

    # ── 4. 當前參數 ────────────────────────────────────────────────
    params = _api("/trading-params")
    daytrade = _api("/daytrade/list")
    candidate_count = daytrade.get("count", 0) if isinstance(daytrade, dict) else 0

    # ── 5. 計算指標 ────────────────────────────────────────────────
    trade_count = len(trades)
    total_pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    # 出場原因（優先從 LINE log 解析）
    exit_reasons: dict[str, int] = {"stop_loss": 0, "take_profit": 0, "force_exit": 0, "unknown": 0}
    for n in notifs:
        if n["msg_type"] in ("dry_exit", "force_exit"):
            r = _parse_exit_reason(n["content"])
            exit_reasons[r] = exit_reasons.get(r, 0) + 1

    # 進場時間分析
    entry_times = []
    for n in notifs:
        if n["msg_type"] == "dry_entry":
            try:
                t = datetime.fromisoformat(n["sent_at"])
                entry_times.append(t.hour * 60 + t.minute)
            except Exception:
                pass

    avg_entry_min = int(sum(entry_times) / len(entry_times)) if entry_times else None
    avg_entry_str = f"{avg_entry_min//60:02d}:{avg_entry_min%60:02d}" if avg_entry_min else "N/A"

    # 持倉時間分析（分鐘）
    holding_times = []
    for t in trades:
        p = pos_map.get(t["symbol"])
        if p and p.get("entry_time"):
            try:
                entry = datetime.fromisoformat(p["entry_time"])
                exit_t = datetime.strptime(f"{today} {t['trade_time']}", "%Y-%m-%d %H:%M:%S")
                holding_times.append((exit_t - entry).seconds // 60)
            except Exception:
                pass
    avg_hold = int(sum(holding_times) / len(holding_times)) if holding_times else None

    # ── 6. 建議邏輯 ────────────────────────────────────────────────
    suggestions: list[str] = []
    curr = params or {}

    stop_rate = exit_reasons["stop_loss"] / trade_count if trade_count else 0
    tp_rate   = exit_reasons["take_profit"] / trade_count if trade_count else 0
    fe_rate   = exit_reasons["force_exit"] / trade_count if trade_count else 0

    if trade_count == 0:
        suggestions.append(f"今日無交易，候選股 {candidate_count} 檔但無符合進場條件")
        suggestions.append(f"考慮放寬：tick_rise_threshold {curr.get('tick_rise_threshold',4)}→{max(2,curr.get('tick_rise_threshold',4)-1)}")
        suggestions.append(f"或放寬：amplitude_min_pct {curr.get('amplitude_min_pct',3)}%→{max(1,curr.get('amplitude_min_pct',3)-0.5)}%")
    else:
        if stop_rate >= 0.6:
            trt = curr.get("tick_rise_threshold", 4)
            sl  = curr.get("stop_loss_ticks", 4)
            suggestions.append(f"停損率 {stop_rate:.0%} 偏高 → 進場訊號太早")
            suggestions.append(f"  選擇①：tick_rise_threshold {trt}→{trt+1}（更強動能才進場）")
            suggestions.append(f"  選擇②：stop_loss_ticks {sl}→{sl+1}（停損放寬）")

        if tp_rate == 0 and trade_count >= 2:
            tpa = curr.get("take_profit_add_pct", 4)
            suggestions.append(f"停利從未觸發 → take_profit_add_pct {tpa}%→{max(1.5,tpa-1)}% 降低目標")

        if fe_rate >= 0.4:
            lat = curr.get("latest_dynamic_add_time", "12:30")
            suggestions.append(f"強制出場率 {fe_rate:.0%} 偏高 → 進場時間太晚")
            suggestions.append(f"  latest_dynamic_add_time {lat}→縮短 30 分鐘，拒絕過晚進場")

        if total_pnl > 0 and tp_rate > 0.5:
            tpa = curr.get("take_profit_add_pct", 4)
            suggestions.append(f"停利率佳({tp_rate:.0%})且盈利 → 可試 take_profit_add_pct {tpa}%→{tpa+0.5}%")

        if avg_entry_min and avg_entry_min > 11 * 60 + 30:
            suggestions.append(f"平均進場時間 {avg_entry_str}，偏向尾盤 → 注意 force_exit 壓力")

        if total_pnl < 0 and stop_rate < 0.3 and fe_rate >= 0.5:
            fe = curr.get("force_exit_time", "13:14")
            suggestions.append(f"主要虧損來自強制出場，非停損 → force_exit_time {fe} 設定偏早，或考慮提前認賠")

    if not suggestions:
        suggestions.append("今日表現正常，參數無需調整")

    # ── 7. 組報告 ─────────────────────────────────────────────────
    report = {
        "date": today,
        "trade_count": trade_count,
        "total_pnl": total_pnl,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / trade_count, 2) if trade_count else 0,
        "exit_reasons": exit_reasons,
        "avg_entry_time": avg_entry_str,
        "avg_hold_min": avg_hold,
        "candidate_count": candidate_count,
        "params_snapshot": {
            k: curr.get(k) for k in [
                "tick_rise_threshold", "stop_loss_ticks", "take_profit_add_pct",
                "amplitude_min_pct", "bid_pct_threshold", "bid_1m_pct_threshold",
                "latest_dynamic_add_time", "force_exit_time", "entry_start_time",
            ]
        },
        "suggestions": suggestions,
    }

    # ── 8. 存檔 ────────────────────────────────────────────────────
    out = REPORT_DIR / f"{today}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"報告儲存至 {out}")

    # ── 9. 送 LINE ─────────────────────────────────────────────────
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    wd = datetime.strptime(today, "%Y-%m-%d").weekday()
    header = f"📊 盤後分析 {today[5:]} (週{weekday_names[wd]})"

    if trade_count == 0:
        body = "今日無 dry run 交易記錄"
    else:
        sl_n  = exit_reasons["stop_loss"]
        tp_n  = exit_reasons["take_profit"]
        fe_n  = exit_reasons["force_exit"]
        body  = (
            f"交易 {trade_count} 筆 | 損益 {total_pnl:+,.0f} 元\n"
            f"停損 {sl_n} | 停利 {tp_n} | 強制 {fe_n}\n"
            f"勝率 {report['win_rate']:.0%} | 平均持倉 {avg_hold or '?'} 分鐘\n"
        )

    suggestion_text = "\n".join(f"• {s}" for s in suggestions)
    msg = f"{header}\n{'─'*18}\n{body}\n\n⚠️ 建議：\n{suggestion_text}"

    print(msg)
    return report


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    analyze(d)
