#!/usr/bin/env python3
"""
盤後深度分析腳本 — dry run 逐筆進出場審計 + 參數評估 + 外資投信融資券
自動於交易日 21:30 由 systemd timer 觸發（收盤後等法人資料公布）
"""
import csv
import io
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

DB       = Path(os.environ.get("FUBON_DATA_DIR", "/home/tommy0322/fubon-data")) / "ticks.db"
LOG_DIR  = Path(os.environ.get("FUBON_LOG_DIR", "/home/tommy0322/fubon-logs"))
REPORT_DIR = Path(os.environ.get("FUBON_DATA_DIR", "/home/tommy0322/fubon-data")) / "analysis"
REPORT_DIR.mkdir(exist_ok=True)

# ── tick 面值 ──────────────────────────────────────────────────────────────────
def tick_size(price: float) -> float:
    if price < 10:    return 0.01
    if price < 50:    return 0.05
    if price < 100:   return 0.1
    if price < 500:   return 0.5
    if price < 1000:  return 1.0
    return 5.0

def ticks_between(p1: float, p2: float) -> float:
    ts = tick_size(min(p1, p2))
    return round((p2 - p1) / ts, 1) if ts else 0.0

# ── 外部 API ───────────────────────────────────────────────────────────────────
def _api(path: str, port: int = 8090) -> dict | list:
    try:
        return json.loads(urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=5).read())
    except Exception:
        return {}

_name_cache: dict[str, str] = {}

def _stock_name(symbol: str, pool: list) -> str:
    if symbol in _name_cache:
        return _name_cache[symbol]
    name = next((s.get("name", "") for s in pool if s.get("code") == symbol), "")
    if not name:
        try:
            snap = _api(f"/api/stock-snapshot/{symbol}", port=8000)
            name = snap.get("name", symbol) if isinstance(snap, dict) else symbol
        except Exception:
            name = symbol
    _name_cache[symbol] = name or symbol
    return _name_cache[symbol]

# ── PostgreSQL via Docker exec ─────────────────────────────────────────────────
PG_CONTAINER = os.environ.get("PG_CONTAINER", "institutional-investors-db-1")
PG_USER = "stock"
PG_DB   = "stock_force"

def _query_pg(sql: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["docker", "exec", PG_CONTAINER,
             "psql", "-U", PG_USER, "-d", PG_DB,
             "--no-align", "--csv",   # with header
             "-c", sql],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        reader = csv.DictReader(io.StringIO(result.stdout))
        return [dict(r) for r in reader]
    except Exception as e:
        print(f"PostgreSQL 查詢失敗: {e}")
        return []

def fetch_institutional_margin(symbols: list[str], trade_date: str) -> dict[str, dict]:
    """Return {symbol: {foreign_net, trust_net, three_major_net, margin_balance, margin_change, short_balance_lots}}"""
    if not symbols:
        return {}
    syms_sql = "ARRAY[" + ",".join(f"'{s}'" for s in symbols) + "]"

    inst_rows = _query_pg(f"""
        SELECT code, foreign_net, trust_net, three_major_net
        FROM institutional
        WHERE code = ANY({syms_sql}) AND trade_date = '{trade_date}'
    """)
    margin_rows = _query_pg(f"""
        SELECT code, margin_balance, margin_change, short_balance
        FROM margin_trading
        WHERE code = ANY({syms_sql}) AND trade_date = '{trade_date}'
    """)

    result: dict[str, dict] = {s: {} for s in symbols}
    for r in inst_rows:
        code = r.get("code", "").strip()
        if code in result:
            result[code].update({
                "foreign_net": _flt(r.get("foreign_net")),
                "trust_net":   _flt(r.get("trust_net")),
                "three_major_net": _flt(r.get("three_major_net")),
            })
    for r in margin_rows:
        code = r.get("code", "").strip()
        if code in result:
            mb = _int(r.get("margin_balance"))
            mc = _int(r.get("margin_change"))
            sb = _int(r.get("short_balance"))
            result[code].update({
                "margin_balance_lots": mb // 1000 if mb else 0,
                "margin_change_lots":  mc // 1000 if mc else 0,
                "short_balance_lots":  sb // 1000 if sb else 0,
            })
    return result

def _flt(v) -> float | None:
    try: return float(v)
    except: return None

def _int(v) -> int | None:
    try: return int(float(v))
    except: return None

def _inst_verdict(data: dict, symbol: str) -> list[str]:
    verdicts = []
    fn  = data.get("foreign_net")
    tn  = data.get("trust_net")
    tmn = data.get("three_major_net")
    mb  = data.get("margin_balance_lots")
    mc  = data.get("margin_change_lots")
    sb  = data.get("short_balance_lots")

    if fn is not None:
        label = f"外資{'買超' if fn > 0 else '賣超'} {abs(fn):.0f}張"
        if tn is not None:
            label += f"，投信{'買超' if tn > 0 else '賣超'} {abs(tn):.0f}張"
        if tmn is not None:
            if tmn > 0:
                label += f" → 三大法人買超 {tmn:.0f}張，方向偏多"
            else:
                label += f" → 三大法人賣超 {abs(tmn):.0f}張，主力撤退"
        verdicts.append(label)

    if mc is not None and mc < -100:
        verdicts.append(f"融資減少 {abs(mc)}張（散戶降槓桿，市場偏謹慎）")
    elif mc is not None and mc > 100:
        verdicts.append(f"融資增加 {mc}張（散戶加碼，留意洗盤壓力）")

    if sb is not None and sb > 0:
        verdicts.append(f"融券餘額 {sb}張" + (f"，融資 {mb}張" if mb else ""))

    return verdicts

# ── jsonl log 解析 ─────────────────────────────────────────────────────────────
def load_jsonl(date_str: str) -> list[dict]:
    path = LOG_DIR / f"dry_run_{date_str}.jsonl"
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events

# ── tick 資料 ──────────────────────────────────────────────────────────────────
def load_ticks(conn: sqlite3.Connection, symbol: str, date_str: str) -> list[tuple[str, float, int]]:
    """Return [(ts, price, volume), ...] sorted by ts"""
    rows = conn.execute(
        "SELECT ts, price, volume FROM ticks WHERE symbol=? AND ts LIKE ? ORDER BY ts",
        (symbol, date_str + "%"),
    ).fetchall()
    return rows

def price_at(ticks: list, ts_str: str) -> float | None:
    """Last price at or before ts_str"""
    price = None
    for ts, p, _ in ticks:
        if ts <= ts_str:
            price = p
        else:
            break
    return price

def range_stats(ticks: list, t_from: str, t_to: str) -> dict:
    """High/low/first/last price within [t_from, t_to]"""
    subset = [(ts, p, v) for ts, p, v in ticks if t_from <= ts <= t_to]
    if not subset:
        return {}
    prices = [p for _, p, _ in subset]
    return {
        "high":  max(prices),
        "low":   min(prices),
        "first": subset[0][1],
        "last":  subset[-1][1],
        "first_ts": subset[0][0][:19],
        "last_ts":  subset[-1][0][:19],
    }

def find_peak_after(ticks: list, entry_ts: str, horizon_min: int = 120) -> dict:
    """Peak and trough after entry within horizon_min minutes"""
    end = (datetime.fromisoformat(entry_ts) + timedelta(minutes=horizon_min)).strftime("%Y-%m-%d %H:%M:%S")
    subset = [(ts, p) for ts, p, _ in ticks if ts > entry_ts and ts <= end]
    if not subset:
        return {}
    peaks = [(ts, p) for ts, p in subset if p == max(t[1] for t in subset)]
    troughs = [(ts, p) for ts, p in subset if p == min(t[1] for t in subset)]
    return {
        "peak_price": peaks[0][1],
        "peak_ts":    peaks[0][0][:19],
        "trough_price": troughs[0][1],
        "trough_ts":    troughs[0][0][:19],
    }

def post_exit_path(ticks: list, exit_ts: str, minutes: int = 30) -> dict:
    """Price stats in the Nmin window after exit"""
    end = (datetime.fromisoformat(exit_ts) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    return range_stats(ticks, exit_ts, end)

# ── 參數評估 ───────────────────────────────────────────────────────────────────
def _entry_time_verdict(entry_ts: str, entry_start_time: str) -> str:
    entry_t = datetime.fromisoformat(entry_ts).strftime("%H:%M")
    h, m = entry_start_time.split(":")
    if datetime.fromisoformat(entry_ts).time() < datetime.strptime(entry_start_time, "%H:%M").time():
        return f"進場 {entry_t} < entry_start_time {entry_start_time}，此單在當前設定下會被 gate 擋掉"
    return f"進場 {entry_t} 在 entry_start_time {entry_start_time} 之後，gate 正常"

def _stop_verdict(entry: float, stop: float, exit_price: float, post_low: float | None) -> str:
    ts = tick_size(entry)
    stop_ticks = round((entry - stop) / ts)
    triggered = exit_price <= stop
    saved = ""
    if post_low is not None:
        saved_ticks = round((stop - post_low) / ts)
        if saved_ticks > 0:
            saved = f"停損後價格繼續跌至 {post_low}（省了 {saved_ticks} tick = {saved_ticks * ts * 1000:.0f}元/張）"
        else:
            saved = f"停損後價格回升至 {post_low}（可能出場太早）"
    verdict = f"停損 {stop}（{stop_ticks} tick 下）{'觸發' if triggered else '未觸發'}。{saved}"
    return verdict

def _tp_verdict(entry: float, take_profit: float, day_high: float) -> str:
    ts = tick_size(entry)
    tp_ticks = round((take_profit - entry) / ts)
    gap_ticks = round((take_profit - day_high) / ts)
    if day_high >= take_profit:
        return f"停利 {take_profit} 達到（日高 {day_high} > 目標）✓"
    else:
        return f"停利 {take_profit}（{tp_ticks} tick 上），日高只有 {day_high}，差 {gap_ticks} tick 未觸及"

def _tick_rise_verdict(tick_rise: float, threshold: float, entry_ts: str) -> str:
    entry_min = datetime.fromisoformat(entry_ts).hour * 60 + datetime.fromisoformat(entry_ts).minute
    zone = "開盤 9 分鐘" if entry_min < 9 * 60 + 10 else ("開盤 30 分鐘" if entry_min < 9 * 60 + 30 else "盤中")
    ratio = round(tick_rise / threshold, 1)
    risk = "高（開盤假突破常見）" if entry_min < 9 * 60 + 30 else "中"
    return (
        f"tick_rise={tick_rise:.0f} tick（門檻={threshold:.0f}）{ratio}x 倍觸發，"
        f"進場在{zone}，假突破風險={risk}"
    )

# ── 主分析 ─────────────────────────────────────────────────────────────────────
def analyze(target_date: str | None = None) -> dict:
    today = target_date or date.today().isoformat()
    events = load_jsonl(today)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 當前參數快照
    params = _api("/trading-params") or {}
    pool_api = _api("/api/pool", port=8000)
    pool = pool_api if isinstance(pool_api, list) else []

    # ── 從 jsonl 取進出場 ───────────────────────────────────────────────────────
    buys: dict[str, dict] = {}   # symbol → order_buy event
    sells: dict[str, dict] = {}  # symbol → order_sell event
    evals: dict[str, list] = {}  # symbol → [signal_eval events]

    for e in events:
        t = e.get("type")
        sym = e.get("symbol", "")
        if t == "order_buy":
            buys[sym] = e
        elif t == "order_sell":
            sells[sym] = e
        elif t == "signal_eval":
            evals.setdefault(sym, []).append(e)

    if not buys:
        # jsonl log 不存在或今天沒交易，fallback 到 intraday_trades
        trades_db = conn.execute(
            "SELECT * FROM intraday_trades WHERE trade_date=? AND dry_run=1 ORDER BY trade_time",
            (today,),
        ).fetchall()
        conn.close()
        report = {
            "date": today,
            "source": "intraday_trades_only",
            "summary": {"total_trades": 0, "note": "jsonl log 無進場紀錄"},
            "trades": [],
            "params_snapshot": params,
        }
        if trades_db:
            report["summary"]["total_trades"] = len(trades_db)
            report["summary"]["note"] = "有 intraday_trades 但缺少 jsonl log，無法深入分析"
        out = REPORT_DIR / f"{today}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"報告儲存至 {out}")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return report

    # ── 預載法人 + 融資券資料 ───────────────────────────────────────────────────
    all_symbols = list(buys.keys())
    inst_margin = fetch_institutional_margin(all_symbols, today)

    # ── 逐筆深度分析 ────────────────────────────────────────────────────────────
    trade_reports = []
    pnl_total = 0.0
    win_count = 0
    reason_counter: dict[str, int] = {}
    all_hold_secs: list[int] = []
    early_entries = 0  # 在 entry_start_time 前進場的筆數

    entry_start_time = str(params.get("entry_start_time", "09:15"))

    for sym, buy in sorted(buys.items(), key=lambda kv: kv[1]["ts"]):
        sell = sells.get(sym, {})
        name = _stock_name(sym, pool)

        entry_ts    = buy["ts"]
        entry_price = buy["price"]
        stop_loss   = buy.get("stop_loss")
        take_profit = buy.get("take_profit")
        lots        = buy.get("lots", 1)

        exit_ts     = sell.get("ts")
        exit_price  = sell.get("exit_price")
        exit_reason = sell.get("reason", "unknown")
        pnl         = sell.get("pnl", 0.0)

        # 持倉時間
        hold_sec = None
        if exit_ts:
            try:
                hold_sec = int((datetime.fromisoformat(exit_ts) - datetime.fromisoformat(entry_ts)).total_seconds())
                all_hold_secs.append(hold_sec)
            except Exception:
                pass

        if pnl > 0:
            win_count += 1
        reason_counter[exit_reason] = reason_counter.get(exit_reason, 0) + 1
        pnl_total += pnl

        # ── tick 分析 ──────────────────────────────────────────────────────────
        ticks = load_ticks(conn, sym, today)
        day_open9  = range_stats(ticks, today + " 09:00", today + " 09:01")
        orb        = range_stats(ticks, today + " 09:00", today + " 09:30")
        day_all    = range_stats(ticks, today + " 08:30", today + " 13:31")

        entry_ts_dt = datetime.fromisoformat(entry_ts)
        entry_ts_str = entry_ts_dt.strftime("%Y-%m-%d %H:%M:%S")

        mfe_info = find_peak_after(ticks, entry_ts_str, horizon_min=60)
        post_exit = post_exit_path(ticks, exit_ts[:19] if exit_ts else entry_ts_str, minutes=30) if exit_ts else {}

        day_high  = day_all.get("high")
        day_low   = day_all.get("low")
        orb_high  = orb.get("high")
        orb_low   = orb.get("low")
        open9     = day_open9.get("first")
        mfe_price = mfe_info.get("peak_price")
        mfe_ts    = mfe_info.get("peak_ts")
        trough    = mfe_info.get("trough_price")
        post_low  = post_exit.get("low")
        post_high = post_exit.get("high")

        mfe_ticks = ticks_between(entry_price, mfe_price) if mfe_price else None
        mae_ticks = ticks_between(entry_price, trough) if trough else None

        ts = tick_size(entry_price)
        # 最佳進場點（日低至出場時間段的最低點）
        range_to_exit = range_stats(ticks, today + " 09:00", exit_ts[:19] if exit_ts else entry_ts_str)
        optimal_entry = range_to_exit.get("low")
        optimal_save_ticks = ticks_between(optimal_entry, entry_price) if optimal_entry else 0

        # ── 進場條件（最近 signal_eval 在進場前 30s）─────────────────────────
        entry_eval = {}
        sym_evals = evals.get(sym, [])
        for ev in sym_evals:
            if ev["ts"] <= entry_ts and ev.get("actual_enter") is True:
                entry_eval = ev
        # fallback: closest signal_eval before entry
        if not entry_eval:
            pre_evals = [ev for ev in sym_evals if ev["ts"] <= entry_ts]
            if pre_evals:
                entry_eval = pre_evals[-1]

        tick_rise_at_entry = entry_eval.get("tick_rise_60s")
        change_pct_at_entry = entry_eval.get("change_pct")
        tick_rise_threshold = float(params.get("tick_rise_threshold", 4))

        # ── 早於 entry_start_time 檢查 ─────────────────────────────────────
        est_parts = entry_start_time.split(":")
        entry_ts_naive = entry_ts_dt.replace(tzinfo=None)
        est_time = datetime(entry_ts_naive.year, entry_ts_naive.month, entry_ts_naive.day,
                            int(est_parts[0]), int(est_parts[1]))
        is_early = entry_ts_naive < est_time
        if is_early:
            early_entries += 1

        # ── 進場情境分類 ────────────────────────────────────────────────────
        entry_min = entry_ts_dt.hour * 60 + entry_ts_dt.minute
        if entry_min < 9 * 60 + 10:
            entry_zone = "extreme_open"   # 開盤 10min 內
        elif entry_min < 9 * 60 + 30:
            entry_zone = "opening"        # 開盤 30min 內
        elif entry_min < 11 * 60:
            entry_zone = "morning"
        elif entry_min < 12 * 60:
            entry_zone = "midday"
        else:
            entry_zone = "afternoon"

        # ── 逐參數評估 ─────────────────────────────────────────────────────
        param_verdicts = {}

        # entry_start_time
        param_verdicts["entry_start_time"] = {
            "current": entry_start_time,
            "entry_actual": entry_ts_dt.strftime("%H:%M"),
            "blocked_by_current": is_early,
            "verdict": _entry_time_verdict(entry_ts, entry_start_time),
        }

        # tick_rise_threshold
        if tick_rise_at_entry is not None:
            param_verdicts["tick_rise_threshold"] = {
                "value_at_entry": tick_rise_at_entry,
                "current_threshold": tick_rise_threshold,
                "x_over_threshold": round(tick_rise_at_entry / tick_rise_threshold, 1) if tick_rise_threshold else None,
                "entry_zone": entry_zone,
                "verdict": _tick_rise_verdict(tick_rise_at_entry, tick_rise_threshold, entry_ts),
            }

        # stop_loss
        if stop_loss is not None and exit_price is not None:
            param_verdicts["stop_loss_ticks"] = {
                "stop_price": stop_loss,
                "ticks_from_entry": round((entry_price - stop_loss) / ts),
                "current_setting": params.get("stop_loss_ticks"),
                "triggered": exit_reason in ("tick_stop", "stop_loss"),
                "post_exit_low": post_low,
                "verdict": _stop_verdict(entry_price, stop_loss, exit_price, post_low),
            }

        # take_profit
        if take_profit is not None and day_high is not None:
            tp_reached = day_high >= take_profit
            param_verdicts["take_profit_add_pct"] = {
                "target_price": take_profit,
                "ticks_above_entry": round((take_profit - entry_price) / ts),
                "current_setting": params.get("take_profit_add_pct"),
                "day_high": day_high,
                "reached": tp_reached,
                "verdict": _tp_verdict(entry_price, take_profit, day_high),
            }

        # amplitude_min_pct
        if day_high and day_low and open9:
            amplitude = round((day_high - day_low) / open9 * 100, 2) if open9 else 0
            amp_threshold = float(params.get("amplitude_min_pct", 3.0))
            param_verdicts["amplitude_min_pct"] = {
                "actual_amplitude": amplitude,
                "threshold": amp_threshold,
                "verdict": (f"日振幅 {amplitude}%（門檻 {amp_threshold}%）"
                           + ("，條件達標" if amplitude >= amp_threshold else "，條件未達")),
            }

        # ── 法人/融資評語 ──────────────────────────────────────────────────
        im_data = inst_margin.get(sym, {})
        inst_verdicts = _inst_verdict(im_data, sym)

        # ── 整體進出場評語 ──────────────────────────────────────────────────
        verdicts = []

        # 進場時間評語
        if entry_zone == "extreme_open":
            verdicts.append(f"⚠️ 進場 {entry_ts_dt.strftime('%H:%M:%S')}（開盤後 {entry_min-9*60} 分鐘）= 開盤極高波動期，假突破最常見")
        elif entry_zone == "opening":
            verdicts.append(f"進場 {entry_ts_dt.strftime('%H:%M:%S')} 在開盤 30min 內，波動仍高")

        if is_early:
            verdicts.append(f"⚠️ 此單在當前 entry_start_time={entry_start_time} 下不會發生")

        # tick_rise 評語
        if tick_rise_at_entry is not None:
            ratio = tick_rise_at_entry / tick_rise_threshold if tick_rise_threshold else 0
            if ratio >= 5 and entry_zone in ("extreme_open", "opening"):
                verdicts.append(f"tick_rise={tick_rise_at_entry:.0f} 是 {ratio:.0f}x 閾值，可能是開盤噪音放大")
            elif ratio < 2:
                verdicts.append(f"tick_rise={tick_rise_at_entry:.0f} 僅勉強達標（{ratio:.1f}x），動能偏弱")

        # 停損評語
        if exit_reason in ("tick_stop", "stop_loss"):
            if post_low and post_low < stop_loss:
                saved = round((stop_loss - post_low) / ts * ts * 1000 * lots)
                verdicts.append(f"✓ 停損 {stop_loss} 正確：出場後跌至 {post_low}，省了 {saved:,} 元")
            elif post_low and post_low > entry_price:
                verdicts.append(f"△ 停損後價格回到 {post_low}（高於進場 {entry_price}），可能是假突破被洗出")
            else:
                verdicts.append(f"停損 {stop_loss} 觸發，出場後 {post_low or '?'}")

        # 停利評語
        if take_profit and day_high and day_high < take_profit:
            gap_pct = round((take_profit - day_high) / entry_price * 100, 1)
            verdicts.append(f"停利 {take_profit} 距日高 {day_high} 還差 {gap_pct}%，目標偏高")

        # MFE/MAE 比較
        if mfe_ticks is not None and mae_ticks is not None:
            mfe_ticks_abs = abs(mfe_ticks)
            mae_ticks_abs = abs(mae_ticks)
            if mfe_ticks_abs <= 1:
                verdicts.append(f"進場後最高只漲 {mfe_ticks_abs} tick 就反轉，入場時機差（假突破）")
            else:
                verdicts.append(f"MFE +{mfe_ticks_abs} tick @ {mfe_ts}，MAE -{mae_ticks_abs} tick")

        # 最佳進場比較
        if optimal_entry and optimal_save_ticks > 2:
            verdicts.append(
                f"最佳進場（{range_to_exit.get('first_ts','?')}–出場前低點 {optimal_entry}）"
                f"比實際早 {optimal_save_ticks:.0f} tick"
            )

        trade_reports.append({
            "symbol": sym,
            "name": name,
            "entry": {
                "time": entry_ts_dt.strftime("%H:%M:%S"),
                "price": entry_price,
                "lots": lots,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "zone": entry_zone,
                "before_start_gate": is_early,
                "tick_rise_60s": tick_rise_at_entry,
                "change_pct": change_pct_at_entry,
            },
            "exit": {
                "time": datetime.fromisoformat(exit_ts).strftime("%H:%M:%S") if exit_ts else None,
                "price": exit_price,
                "reason": exit_reason,
                "hold_sec": hold_sec,
                "pnl": pnl,
            },
            "day_context": {
                "open_price": open9,
                "day_high": day_high,
                "day_low": day_low,
                "orb_high": orb_high,
                "orb_low": orb_low,
                "day_range_pct": round((day_high - day_low) / open9 * 100, 2) if day_high and day_low and open9 else None,
            },
            "trade_path": {
                "mfe_price": mfe_price,
                "mfe_ticks": mfe_ticks,
                "mfe_time": mfe_ts,
                "mae_ticks": mae_ticks,
                "post_exit_high": post_high,
                "post_exit_low": post_low,
                "optimal_entry_price": optimal_entry,
                "optimal_entry_saved_ticks": optimal_save_ticks if optimal_save_ticks > 0 else 0,
            },
            "verdicts": verdicts,
            "param_verdicts": param_verdicts,
            "institutional_context": {
                "data": im_data,
                "verdicts": inst_verdicts,
            },
        })

    conn.close()

    trade_count = len(trade_reports)
    avg_hold = int(sum(all_hold_secs) / len(all_hold_secs)) if all_hold_secs else None

    # ── 聚合參數評估 ─────────────────────────────────────────────────────────
    aggregate_verdicts = []

    # entry_start_time
    if early_entries == trade_count and trade_count > 0:
        aggregate_verdicts.append(
            f"entry_start_time={entry_start_time}：今日 {trade_count} 筆全在 gate 前進場，"
            f"若當前 gate 有效，今日所有虧損可完全避免"
        )
    elif early_entries > 0:
        aggregate_verdicts.append(
            f"entry_start_time={entry_start_time}：{early_entries}/{trade_count} 筆在 gate 前進場"
        )

    # stop_loss 有效性
    sl_trades = [t for t in trade_reports if t["exit"]["reason"] in ("tick_stop", "stop_loss")]
    sl_count = len(sl_trades)
    if sl_count == trade_count and trade_count > 0:
        saved_all = all(
            t["trade_path"].get("post_exit_low") is not None and
            t["trade_path"]["post_exit_low"] < (t["entry"]["stop_loss"] or 0)
            for t in sl_trades if t["entry"].get("stop_loss")
        )
        if saved_all:
            aggregate_verdicts.append(
                f"stop_loss_ticks：{sl_count}/{trade_count} 筆觸停損，停損後全部繼續下跌，停損機制有效"
            )
        else:
            aggregate_verdicts.append(
                f"stop_loss_ticks：{sl_count}/{trade_count} 筆觸停損（部分停損後反彈，可能洗出）"
            )

    # take_profit 有效性
    tp_hit = [t for t in trade_reports if t["param_verdicts"].get("take_profit_add_pct", {}).get("reached")]
    aggregate_verdicts.append(
        f"take_profit_add_pct={params.get('take_profit_add_pct')}%：{len(tp_hit)}/{trade_count} 筆觸及停利"
        + ("" if len(tp_hit) > 0 else "，考慮降低目標或改用移動停利")
    )

    # opening zone 集中度
    open_trades = [t for t in trade_reports if t["entry"]["zone"] in ("extreme_open", "opening")]
    if open_trades:
        aggregate_verdicts.append(
            f"開盤 30min 進場：{len(open_trades)}/{trade_count} 筆，"
            f"建議 entry_start_time 改為 09:30 觀察效果"
        )

    # ── 組報告 ────────────────────────────────────────────────────────────────
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    wd = datetime.strptime(today, "%Y-%m-%d").weekday()

    report = {
        "date": today,
        "weekday": weekday_names[wd],
        "source": "jsonl_deep_analysis",
        "summary": {
            "total_trades":    trade_count,
            "total_pnl":       pnl_total,
            "win_count":       win_count,
            "loss_count":      trade_count - win_count,
            "win_rate":        round(win_count / trade_count, 2) if trade_count else 0,
            "exit_reasons":    reason_counter,
            "avg_hold_sec":    avg_hold,
            "early_entries":   early_entries,
            "entry_start_time": entry_start_time,
        },
        "params_snapshot": {k: params.get(k) for k in [
            "tick_rise_threshold", "stop_loss_ticks", "take_profit_add_pct",
            "amplitude_min_pct", "bid_pct_threshold", "bid_1m_pct_threshold",
            "latest_dynamic_add_time", "force_exit_time", "entry_start_time",
        ]},
        "trades": trade_reports,
        "aggregate_verdicts": aggregate_verdicts,
    }

    out = REPORT_DIR / f"{today}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"報告儲存至 {out}")

    # ── 終端摘要 ─────────────────────────────────────────────────────────────
    print(f"\n📊 盤後分析 {today} (週{weekday_names[wd]})")
    print(f"{'─'*40}")
    print(f"交易 {trade_count} 筆 | 損益 {pnl_total:+,.0f} 元 | 勝率 {report['summary']['win_rate']:.0%}")
    print(f"出場原因: {reason_counter}")
    if avg_hold:
        print(f"平均持倉 {avg_hold//60}分{avg_hold%60}秒")
    print()
    for t in trade_reports:
        e = t["entry"]
        x = t["exit"]
        print(f"  {t['symbol']} {t['name']}")
        print(f"    進 {e['time']} @ {e['price']} ({e['zone']}) tick_rise={e['tick_rise_60s']}")
        print(f"    出 {x['time']} @ {x['price']} ({x['reason']}) {x['pnl']:+,}元")
        for v in t["verdicts"][:3]:
            print(f"    → {v}")
        for v in t["institutional_context"]["verdicts"]:
            print(f"    📊 {v}")
    print()
    print("【聚合評估】")
    for v in aggregate_verdicts:
        print(f"  • {v}")

    return report


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    analyze(d)
