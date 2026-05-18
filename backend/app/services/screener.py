import numpy as np
from datetime import date


def calc_bb_position(closes: list[float]) -> float:
    """
    布林位階 = (Close - MA20) / (2 × STD20) × 10
    可超出 ±10（超出布林帶時延伸計算，不截斷）
    """
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


def check_breakout_candle(
    open_: float, high: float, low: float, close: float,
    volume: int, ma20_vol: float,
) -> bool:
    """
    驗證創高當日 K 棒形態：
    1. 紅K（收 > 開）
    2. 出量（成交量 > 20日均量 × 2，漲停除外）
    3. 上影線 < (高 - 低) × 0.2
    """
    if close <= open_:
        return False
    is_limit_up = (high == close)
    if not is_limit_up and volume < ma20_vol * 2:
        return False
    candle_range = high - low
    upper_shadow = high - close
    if candle_range > 0 and upper_shadow / candle_range > 0.2:
        return False
    return True


def find_50d_high_event(
    closes: list[float],
    volumes: list[int],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    lookback_event: int = 20,
) -> tuple[float, int] | None:
    """
    在最近 lookback_event 日內找符合條件的50日新高突破事件。
    條件：
      - 今日收盤 > 50日最高收盤 且 昨日收盤 < 50日最高收盤（突破當天）
      - 創高當日 check_breakout_candle 通過
      - 創高當日 BB 位階 > 8
    回傳 (bb_peak, days_ago) 或 None
    """
    n = len(closes)
    if n < 52:
        return None

    for days_ago in range(lookback_event):
        idx = n - 1 - days_ago
        if idx < 51:
            break

        today_close = closes[idx]
        yesterday_close = closes[idx - 1]
        high_50d = max(closes[idx - 50:idx])

        if today_close < high_50d or yesterday_close >= high_50d:
            continue

        if opens and highs and lows:
            ma20_vol = float(np.mean(volumes[max(0, idx - 20):idx])) if idx >= 20 else 0
            if not check_breakout_candle(
                opens[idx], highs[idx], lows[idx], closes[idx],
                volumes[idx], ma20_vol,
            ):
                continue

        bb_peak = calc_bb_position(closes[:idx + 1])
        if bb_peak <= 8:
            continue

        return bb_peak, days_ago

    return None


def check_entry_criteria(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[int],
) -> dict:
    """
    篩選條件:
    1. 近20日內有50日新高突破事件（出量+紅K+無長上影+BB位階>8）
    2. 當前 BB 位階 -3 ~ 5（拉回到月線附近）
    3. 趨勢保護：MA20 > MA60, MA60 斜率>0, 收盤>MA60
    """
    bb_now = calc_bb_position(closes)
    event = find_50d_high_event(closes, volumes, opens, highs, lows, lookback_event=20)
    squeeze = is_squeeze(closes)

    arr = np.array(closes, dtype=float)
    trend_ok = False
    if len(arr) >= 60:
        ma20 = arr[-20:].mean()
        ma60 = arr[-60:].mean()
        ma60_prev = arr[-61:-1].mean() if len(arr) >= 61 else ma60
        trend_ok = bool(ma20 > ma60 and ma60 > ma60_prev and arr[-1] > ma60)

    passes = (
        event is not None
        and -3 <= bb_now <= 5
        and trend_ok
    )

    bb_peak, peak_days_ago = event if event else (0.0, 0)
    return {
        "bb_position": round(bb_now, 2),
        "bb_peak": round(bb_peak, 2),
        "peak_days_ago": peak_days_ago,
        "is_squeeze": squeeze,
        "trend_ok": trend_ok,
        "passes": passes,
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
            "chip_ratio_6d": 0.0, "chip_ratio_12d": 0.0,
            "foreign_6d_net": 0.0, "trust_6d_net": 0.0,
        }

    rows_6 = inst_rows[-6:]
    rows_12 = inst_rows[-12:]
    f6 = sum(r.foreign_net for r in rows_6)
    t6 = sum(r.trust_net for r in rows_6)
    f12 = sum(r.foreign_net for r in rows_12)
    t12 = sum(r.trust_net for r in rows_12)

    # capital_lots=0（未取得股本）→ 無法計算比率，但仍回傳淨買超張數供顯示
    if capital_lots <= 0:
        return {
            "foreign_6d_net": f6,
            "trust_6d_net": t6,
            "chip_ratio_6d": 0.0,
            "chip_ratio_12d": 0.0,
        }

    return {
        "foreign_6d_net": f6,
        "trust_6d_net": t6,
        "chip_ratio_6d": round((f6 + t6) / capital_lots * 100, 3),
        "chip_ratio_12d": round((f12 + t12) / capital_lots * 100, 3),
    }


def calc_score(result: dict, chip: dict, market_bb_drop: float) -> float:
    """
    綜合評分 (0~100)
    - BB 位階越靠近 0~2 分越高（25%）
    - 法人買超/股本（6日+12日各滿1%加分）（25%）
    - 量縮（融資5日增減<5%扣分豁免）（-10 deduction）
    - RS 優於大盤（15%）
    - 盤整突破加分（15%）
    """
    score = 50.0
    bb = result["bb_position"]

    score += max(0, (5 - abs(bb - 1.5)) / 5 * 25)

    if chip.get("chip_ratio_6d", 0) >= 1.0:
        score += 12.5
    if chip.get("chip_ratio_12d", 0) >= 1.0:
        score += 12.5

    if chip.get("margin_5d_chg", 0) > 0.05:
        score -= 10

    if chip.get("holders_1000_chg", 0) > 0:
        score += 5

    if result.get("is_squeeze"):
        score += 15

    stock_bb_drop = result["bb_peak"] - result["bb_position"]
    if market_bb_drop > 0 and stock_bb_drop < market_bb_drop * 1.2:
        score += 15

    return round(min(100, max(0, score)), 1)
