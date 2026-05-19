import numpy as np
from datetime import date


def calc_bb_position(closes: list[float]) -> float:
    """布林位階 = (Close - MA20) / (2 × STD20) × 10"""
    arr = np.array(closes, dtype=float)
    if len(arr) < 20:
        return 0.0
    ma20 = arr[-20:].mean()
    std20 = arr[-20:].std(ddof=0)
    if std20 < 1e-8:
        return 0.0
    return float((arr[-1] - ma20) / (2 * std20) * 10)


def calc_bb_bandwidth(closes: list[float]) -> float:
    """帶寬率 = (上軌 - 下軌) / MA20"""
    arr = np.array(closes[-20:], dtype=float)
    if len(arr) < 20:
        return 0.0
    ma20 = arr.mean()
    std20 = arr.std(ddof=0)
    return float(4 * std20 / ma20) if ma20 > 0 else 0.0


def is_squeeze(closes: list[float]) -> bool:
    """盤整確認: 最近5日中 ≥3日帶寬 < 帶寬_MA20 × 0.85"""
    if len(closes) < 40:
        return False
    bws = []
    for i in range(len(closes) - 25, len(closes)):
        bws.append(calc_bb_bandwidth(closes[:i + 1]))
    if len(bws) < 25:
        return False
    bw_ma20 = np.mean(bws[:20])
    recent_5 = bws[-5:]
    return sum(1 for bw in recent_5 if bw < bw_ma20 * 0.85) >= 3


def _find_30d_high_breakout(
    closes: list[float],
    volumes: list[int],
    lookback: int = 50,
    require_volume: bool = False,
    vol_multiplier: float = 1.5,
    start_days_ago: int = 0,
) -> tuple[float, int] | None:
    """
    在近 lookback 個交易日內找30日新高突破事件。
    條件：
      - closes[idx] > 前30日最高 且 closes[idx-1] < 前30日最高（突破當天）
      - BB 位階 > 8（確認突破布林上軌附近）
      - require_volume=True 時，額外要求成交量 >= MA20 × vol_multiplier
    回傳 (bb_peak_at_event, days_ago) 或 None
    """
    n = len(closes)
    for days_ago in range(start_days_ago, lookback):
        idx = n - 1 - days_ago
        if idx < 31:
            break
        high_30d = max(closes[idx - 30:idx])
        if closes[idx] <= high_30d or closes[idx - 1] >= high_30d:
            continue
        if require_volume:
            ma20_vol = float(np.mean(volumes[max(0, idx - 20):idx])) if idx >= 20 else 0.0
            if volumes[idx] < ma20_vol * vol_multiplier:
                continue
        bb_at_event = calc_bb_position(closes[:idx + 1])
        if bb_at_event <= 8:
            continue
        return bb_at_event, days_ago
    return None


def check_entry_criteria(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[int],
) -> dict:
    """
    入場條件 = A or B

    A: BB壓縮(squeeze) + 今日創30日新高 + 今日出量(≥MA20×1.5) + 趨勢保護
    B: 近50個交易日內曾創30日新高 + 今日BB位階≤5 + 趨勢保護
       （籌碼條件 chip_ratio_6d≥1% AND chip_ratio_12d≥1% 由外部檢查）

    趨勢保護: MA20 > MA60 AND MA60斜率>0 AND 收盤>MA60
    """
    bb_now = calc_bb_position(closes)
    squeeze = is_squeeze(closes)

    arr = np.array(closes, dtype=float)
    trend_ok = False
    if len(arr) >= 61:
        ma20 = arr[-20:].mean()
        ma60 = arr[-60:].mean()
        ma60_prev = arr[-61:-1].mean()
        trend_ok = bool(ma20 > ma60 and ma60 > ma60_prev and arr[-1] > ma60)

    # Strategy A: 今日突破 + 事前壓縮 + 出量
    passes_A = False
    bb_peak_A = 0.0
    if squeeze and trend_ok:
        result = _find_30d_high_breakout(
            closes, volumes, lookback=1, require_volume=True,
            vol_multiplier=1.5, start_days_ago=0,
        )
        if result:
            bb_peak_A, _ = result
            passes_A = True

    # Strategy B: 歷史突破 + 目前拉回位階≤5
    passes_B_price = False
    bb_peak_B = 0.0
    days_ago_B = 0
    if trend_ok and bb_now <= 5:
        result = _find_30d_high_breakout(
            closes, volumes, lookback=50, require_volume=False,
            start_days_ago=1,
        )
        if result:
            bb_peak_B, days_ago_B = result
            passes_B_price = True

    if passes_A:
        bb_peak, peak_days_ago = bb_peak_A, 0
    elif passes_B_price:
        bb_peak, peak_days_ago = bb_peak_B, days_ago_B
    else:
        bb_peak, peak_days_ago = 0.0, 0

    return {
        "bb_position": round(bb_now, 2),
        "bb_peak": round(bb_peak, 2),
        "peak_days_ago": peak_days_ago,
        "is_squeeze": squeeze,
        "trend_ok": trend_ok,
        "passes_A": passes_A,
        "passes_B_price": passes_B_price,
        "passes": passes_A or passes_B_price,
    }


def calc_vol_ratio(volumes: list[int]) -> float:
    """近5日均量 / 前5日均量"""
    if len(volumes) < 10:
        return 1.0
    recent = np.mean(volumes[-5:])
    prev = np.mean(volumes[-10:-5])
    return float(recent / prev) if prev > 0 else 1.0


def calc_chip_ratios(inst_rows: list, capital_lots: float) -> dict:
    """
    計算法人買超/股本比率（6日 + 12日）
    inst_rows: 從 DB 取出的 Institutional 記錄（按日期升序），foreign_net 單位：張
    capital_lots: 股本（張），來自 StockList.capital
    """
    if not inst_rows:
        return {
            "foreign_6d_net": 0.0, "trust_6d_net": 0.0,
            "chip_ratio_1d": 0.0, "chip_ratio_6d": 0.0, "chip_ratio_12d": 0.0,
        }

    rows_1 = inst_rows[-1:]
    rows_6 = inst_rows[-6:]
    rows_12 = inst_rows[-12:]
    f1 = sum(r.foreign_net for r in rows_1)
    t1 = sum(r.trust_net for r in rows_1)
    f6 = sum(r.foreign_net for r in rows_6)
    t6 = sum(r.trust_net for r in rows_6)
    f12 = sum(r.foreign_net for r in rows_12)
    t12 = sum(r.trust_net for r in rows_12)

    if capital_lots <= 0:
        return {
            "foreign_6d_net": f6,
            "trust_6d_net": t6,
            "chip_ratio_1d": 0.0,
            "chip_ratio_6d": 0.0,
            "chip_ratio_12d": 0.0,
        }

    return {
        "foreign_6d_net": f6,
        "trust_6d_net": t6,
        "chip_ratio_1d": round((f1 + t1) / capital_lots * 100, 3),
        "chip_ratio_6d": round((f6 + t6) / capital_lots * 100, 3),
        "chip_ratio_12d": round((f12 + t12) / capital_lots * 100, 3),
    }


def calc_score(result: dict, chip: dict, market_bb_drop: float) -> float:
    """
    綜合評分 (0~100):
    - BB 位階接近 0~2 加分 (25%)
    - 法人買超/股本 (6日+12日各滿1%加分) (25%)
    - BB壓縮突破加分 (15%)
    - RS 優於大盤加分 (15%)
    """
    score = 50.0
    bb = result["bb_position"]

    score += max(0, (5 - abs(bb - 1.5)) / 5 * 25)

    if chip.get("chip_ratio_6d", 0) >= 1.0:
        score += 12.5
    if chip.get("chip_ratio_12d", 0) >= 1.0:
        score += 12.5

    if chip.get("holders_1000_chg", 0) > 0:
        score += 5

    if result.get("is_squeeze"):
        score += 15

    stock_bb_drop = result["bb_peak"] - result["bb_position"]
    if market_bb_drop > 0 and stock_bb_drop < market_bb_drop * 1.2:
        score += 15

    return round(min(100, max(0, score)), 1)
