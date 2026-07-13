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


def _consecutive_days_above_ma5(closes: list[float]) -> int:
    """計算收盤站上5日均線的連續天數（從今日往回數）"""
    n = len(closes)
    count = 0
    for i in range(n - 1, 3, -1):
        ma5 = float(np.mean(closes[i - 4:i + 1]))
        if closes[i] > ma5:
            count += 1
        else:
            break
    return count


def is_early_breakout(closes: list[float]) -> bool:
    """
    策略 A 條件2：啟動初期確認（四項全須通過）
      - 0.5% < 月線(MA20)斜率 ≤ 1.5%
      - 布林上軌斜率 > 2%
      - 布林帶寬 < 35%
      - 站上MA5連續天數 ≤ 5
    """
    arr = np.array(closes, dtype=float)
    if len(arr) < 22:
        return False

    ma20_today = arr[-20:].mean()
    ma20_prev  = arr[-21:-1].mean()
    if ma20_prev <= 0:
        return False
    ma20_slope = (ma20_today / ma20_prev - 1) * 100
    if not (0.3 < ma20_slope <= 2.0):
        return False

    std20_today = arr[-20:].std(ddof=0)
    std20_prev  = arr[-21:-1].std(ddof=0)
    upper_today = ma20_today + 2 * std20_today
    lower_today = ma20_today - 2 * std20_today
    upper_prev  = ma20_prev  + 2 * std20_prev

    if upper_prev <= 0 or lower_today <= 0:
        return False

    upper_slope = (upper_today / upper_prev - 1) * 100
    if upper_slope <= 2:
        return False

    bandwidth = (upper_today / lower_today - 1) * 100
    if bandwidth >= 35:
        return False

    if _consecutive_days_above_ma5(closes) > 5:
        return False

    return True


def _find_30d_high_breakout(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[int],
    lookback: int = 50,
    require_volume: bool = False,
    vol_multiplier: float = 1.5,
    start_days_ago: int = 0,
    require_first_day: bool = True,
) -> tuple[float, int] | None:
    n = len(closes)
    for days_ago in range(start_days_ago, lookback):
        idx = n - 1 - days_ago
        if idx < 31:
            break
        high_30d = max(closes[idx - 30:idx])
        if closes[idx] <= high_30d:
            continue
        if require_first_day and closes[idx - 1] >= high_30d:
            continue
        h, l = highs[idx], lows[idx]
        if h > l and (closes[idx] - l) / (h - l) < 0.7:
            continue
        if require_volume:
            ma20_vol = float(np.mean(volumes[max(0, idx - 20):idx])) if idx >= 20 else 0.0
            if volumes[idx] < ma20_vol * vol_multiplier:
                continue
        bb_at_event = calc_bb_position(closes[:idx + 1])
        if bb_at_event <= 5:
            continue
        return bb_at_event, days_ago
    return None


def check_cond3_breakout(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[int],
) -> bool:
    if len(closes) < 32:
        return False
    high_30d = max(closes[-31:-1])
    if closes[-1] <= high_30d:
        return False
    rng = highs[-1] - lows[-1]
    if rng > 0 and (closes[-1] - lows[-1]) / rng < 0.7:
        return False
    vols = np.array(volumes, dtype=float)
    ma20_vol = vols[-21:-1].mean() if len(vols) >= 21 else vols[:-1].mean()
    if volumes[-1] < ma20_vol * 1.5:
        return False
    if calc_bb_position(closes) <= 8:
        return False
    return True


def check_entry_criteria(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[int],
) -> dict:
    """
    入場條件 = A or B

    A: 啟動初期(is_early_breakout) + 今日創30日新高 + 今日出量 + 趨勢保護
    B: 近50個交易日內曾創30日新高 + 今日BB位階≤5 + 趨勢保護
    """
    bb_now = calc_bb_position(closes)
    squeeze = is_squeeze(closes)
    early_breakout = is_early_breakout(closes)

    arr = np.array(closes, dtype=float)
    trend_ok = False
    if len(arr) >= 61:
        ma20 = arr[-20:].mean()
        ma20_prev = arr[-21:-1].mean()
        ma60 = arr[-60:].mean()
        ma60_prev = arr[-61:-1].mean()
        trend_ok = bool(
            ma20 > ma60 and
            ma20 > ma20_prev and
            ma60 > ma60_prev and
            arr[-1] > ma60
        )

    passes_A = False
    bb_peak_A = 0.0
    if early_breakout and trend_ok:
        result = _find_30d_high_breakout(
            closes, highs, lows, volumes, lookback=1, require_volume=True,
            vol_multiplier=1.5, start_days_ago=0, require_first_day=True,
        )
        if result:
            bb_peak_A, _ = result
            passes_A = True

    passes_B_price = False
    bb_peak_B = 0.0
    days_ago_B = 0
    if trend_ok and bb_now <= 5:
        result = _find_30d_high_breakout(
            closes, highs, lows, volumes, lookback=50, require_volume=False,
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
        "is_squeeze": early_breakout,
        "trend_ok": trend_ok,
        "passes_A": passes_A,
        "passes_B_price": passes_B_price,
        "passes": passes_A or passes_B_price,
    }


def calc_dip_buy_bonus(
    closes: list[float],
    price_dates: list,
    inst_map: dict,
    max_down_days: int = 5,
    points_per_day: float = 1.0,
) -> float:
    bonus = 0.0
    found = 0
    for i in range(len(closes) - 1, 0, -1):
        if found >= max_down_days:
            break
        if closes[i] < closes[i - 1]:
            found += 1
            if inst_map.get(price_dates[i], 0) > 0:
                bonus += points_per_day
    return bonus


def calc_vol_ratio(volumes: list[int]) -> float:
    """近5日均量 / 前5日均量"""
    if len(volumes) < 10:
        return 1.0
    recent = np.mean(volumes[-5:])
    prev = np.mean(volumes[-10:-5])
    return float(recent / prev) if prev > 0 else 1.0


def calc_chip_ratios(inst_rows: list, capital_lots: float) -> dict:
    if not inst_rows:
        return {
            "foreign_6d_net": 0.0, "trust_6d_net": 0.0,
            "chip_ratio_1d": 0.0, "chip_ratio_6d": 0.0,
            "chip_ratio_12d": 0.0, "chip_ratio_20d": 0.0,
        }

    rows_1  = inst_rows[-1:]
    rows_6  = inst_rows[-6:]
    rows_12 = inst_rows[-12:]
    rows_20 = inst_rows[-20:]
    f1  = sum(r.foreign_net for r in rows_1)
    t1  = sum(r.trust_net for r in rows_1)
    f6  = sum(r.foreign_net for r in rows_6)
    t6  = sum(r.trust_net for r in rows_6)
    f12 = sum(r.foreign_net for r in rows_12)
    t12 = sum(r.trust_net for r in rows_12)
    f20 = sum(r.foreign_net for r in rows_20)
    t20 = sum(r.trust_net for r in rows_20)

    if capital_lots <= 0:
        return {
            "foreign_6d_net": f6, "trust_6d_net": t6,
            "chip_ratio_1d": 0.0, "chip_ratio_6d": 0.0,
            "chip_ratio_12d": 0.0, "chip_ratio_20d": 0.0,
        }

    return {
        "foreign_6d_net":  f6,
        "trust_6d_net":    t6,
        "chip_ratio_1d":   round((f1  + t1)  / capital_lots * 100, 3),
        "chip_ratio_6d":   round((f6  + t6)  / capital_lots * 100, 3),
        "chip_ratio_12d":  round((f12 + t12) / capital_lots * 100, 3),
        "chip_ratio_20d":  round((f20 + t20) / capital_lots * 100, 3),
    }


def calc_score(result: dict, chip: dict, market_bb_drop: float, vol_ratio: float = 1.0) -> float:
    """
    策略 B 綜合評分 (0~100):
    - BB 位階 (20%)
    - chip_6d  (20%)
    - chip_12d (15%)
    - chip_20d (15%)
    - 千張大戶 w1+w2+w3 各10分 (30%)
    """
    score = 0.0
    bb = result["bb_position"]

    if bb <= -1:     score += 10
    elif bb <= 0.5:  score += 20
    elif bb <= 1.5:  score += 18
    elif bb <= 2.5:  score += 16
    elif bb <= 3.5:  score += 14
    elif bb <= 4.5:  score += 12
    elif bb <= 5:    score += 10

    def _chip_score_6d(v: float) -> float:
        if v > 5:  return 20
        if v > 4:  return 16
        if v > 3:  return 12
        if v > 2:  return 9
        if v >= 1: return 5
        return 0

    def _chip_score_12d(v: float) -> float:
        if v > 5:  return 15
        if v > 4:  return 12
        if v > 3:  return 10
        if v > 2:  return 8
        if v >= 1: return 5
        return 0

    def _chip_score_20d(v: float) -> float:
        if v > 10: return 15
        if v > 5:  return 12
        if v > 4:  return 9
        if v > 3:  return 8
        if v > 2:  return 6
        if v >= 1: return 4
        return 0

    score += _chip_score_6d(chip.get("chip_ratio_6d", 0))
    score += _chip_score_12d(chip.get("chip_ratio_12d", 0))
    score += _chip_score_20d(chip.get("chip_ratio_20d", 0))

    def _lot_score(diff: float) -> float:
        if diff > 3: return 10
        if diff > 2: return 5
        if diff > 1: return 3
        if diff > 0: return 2
        return 0

    score += _lot_score(chip.get("holders_w1", chip.get("holders_1000_chg", 0)))
    score += _lot_score(chip.get("holders_w2", 0))
    score += _lot_score(chip.get("holders_w3", 0))

    return round(min(100, max(0, score)), 1)


def calc_upper_slope(closes: list[float]) -> float:
    """布林上軌斜率 = ((今日上軌 / 昨日上軌) - 1) × 100"""
    arr = np.array(closes, dtype=float)
    if len(arr) < 21:
        return 0.0
    ma_t = arr[-20:].mean(); std_t = arr[-20:].std(ddof=0); upper_t = ma_t + 2 * std_t
    ma_p = arr[-21:-1].mean(); std_p = arr[-21:-1].std(ddof=0); upper_p = ma_p + 2 * std_p
    if upper_p <= 0:
        return 0.0
    return float((upper_t / upper_p - 1) * 100)


def calc_ma20_slope(closes: list[float]) -> float:
    """月線（MA20）斜率 = ((今日MA20 / 昨日MA20) - 1) × 100"""
    arr = np.array(closes, dtype=float)
    if len(arr) < 21:
        return 0.0
    ma_t = arr[-20:].mean()
    ma_p = arr[-21:-1].mean()
    if ma_p <= 0:
        return 0.0
    return float((ma_t / ma_p - 1) * 100)


def calc_close_position(close: float, high: float, low: float) -> float:
    """收盤在高低區間位置 = (收盤 - 最低) / (最高 - 最低) × 100"""
    if high <= low:
        return 100.0
    return float((close - low) / (high - low) * 100)


def calc_score_a(
    bb_position: float,
    close_position: float,
    change_pct: float,
    upper_slope: float,
    ma20_slope: float,
    chip1d: float,
    chip12d: float,
    shareholder_change: float,
    vol_ratio: float = 0.0,
    sh_chg_stale: bool = False,
) -> float:
    """
    策略A專用評分（100分）

    A. 籌碼強度（30分）— chip1d + chip12d；雙負時扣 8 分
    B. 突破品質（35分）— BB位階、收盤位置、漲幅、量比
    C. 動能品質（15分）— 布林上軌斜率（越陡=越成熟=越低分）、MA20斜率
    D. 千張大戶積累（20分）— TDCC週報；sh_chg_stale=True 時僅給中性 2 分

    upper_slope 反向計分為設計：策略A定義「啟動初期」，斜率 2-3% 為最佳
    進場點，≥8% 代表趨勢已延伸，追高風險高。
    """
    score = 0.0

    # A. 籌碼強度（30分）
    if chip1d > 3:      score += 15
    elif chip1d > 2:    score += 12
    elif chip1d > 1:    score += 9
    elif chip1d > 0.5:  score += 6
    elif chip1d > 0:    score += 3

    if chip12d > 6:     score += 15
    elif chip12d > 4:   score += 12
    elif chip12d > 2:   score += 9
    elif chip12d > 1:   score += 5
    elif chip12d > 0:   score += 2

    # 今日 + 12日均為賣超 → 雙確認籌碼惡化，扣 8 分
    if chip1d <= 0 and chip12d < 0:
        score -= 8

    # B. 突破品質（35分）
    if bb_position >= 11:  score += 8
    elif bb_position >= 8: score += 5

    if close_position >= 90:    score += 8
    elif close_position >= 80:  score += 5
    elif close_position >= 70:  score += 2

    if change_pct > 9:   score += 8
    elif change_pct > 7: score += 6
    elif change_pct > 5: score += 3

    if vol_ratio > 5:    score += 11
    elif vol_ratio > 3:  score += 9
    elif vol_ratio >= 2: score += 7
    elif vol_ratio >= 1.5: score += 5

    # C. 動能品質（15分）
    if 2 <= upper_slope < 3:    score += 10
    elif 3 <= upper_slope < 5:  score += 8
    elif 5 <= upper_slope < 8:  score += 5
    elif upper_slope >= 8:      score += 2

    if 0.8 <= ma20_slope <= 1.2:                            score += 5
    elif 0.5 <= ma20_slope < 0.8 or 1.2 < ma20_slope <= 1.5: score += 3

    # D. 千張大戶積累（20分）
    # TDCC 資料超過 10 天未更新時 sh_chg_stale=True，只給中性基準分避免過度獎勵陳舊數據
    if shareholder_change is not None:
        if sh_chg_stale:
            score += 2
        elif shareholder_change >= 5:    score += 20
        elif shareholder_change >= 3:    score += 16
        elif shareholder_change >= 2:    score += 10
        elif shareholder_change >= 1:    score += 6
        elif shareholder_change >= 0:    score += 2

    return round(min(100, max(0, score)), 1)
