import pytest
import numpy as np
from app.services.screener import (
    calc_bb_position, is_squeeze, check_entry_criteria,
    find_50d_high_event, check_breakout_candle,
)


def make_ohlcv(n=80):
    """
    Pattern: slow rise → sideways plateau → breakout day (idx=60) → pullback
    Breakout at idx=60 is 19 days before the end, within lookback_event=20.
    """
    up = list(np.linspace(100, 119, 50))      # idx 0-49: slow rise to 119
    side = [118.0] * 10                         # idx 50-59: sideways just below peak
    breakout = [130.0]                           # idx 60: big breakout
    down = list(np.linspace(128, 112, 19))      # idx 61-79: pullback
    closes = up + side + breakout + down

    opens = [c * 0.997 for c in closes]
    highs = [c * 1.001 for c in closes]         # small upper shadow to pass candle check
    lows = [c * 0.990 for c in closes]
    vols = [1000] * n
    vols[60] = 3000                              # volume spike at breakout
    return opens, highs, lows, closes, vols


def make_squeeze_closes(n=60):
    """High-volatility oscillation → flat plateau → bandwidth contraction"""
    oscillating = [100 + 15 * np.sin(i * 0.8) for i in range(45)]
    flat = [100.0] * (n - 45)
    return oscillating + flat


def test_calc_bb_position_at_ma20():
    closes = [100.0] * 60
    assert abs(calc_bb_position(closes)) < 0.5


def test_calc_bb_position_beyond_upper():
    closes = [100.0] * 59 + [115.0]
    pos = calc_bb_position(closes)
    assert pos > 10.0


def test_is_squeeze_detects_contraction():
    closes = make_squeeze_closes(60)
    assert is_squeeze(closes) is True


def test_find_50d_high_event_detects_breakout():
    _, _, _, closes, vols = make_ohlcv()
    # Breakout at idx=60, 19 days ago → within lookback_event=25
    event = find_50d_high_event(closes, vols, lookback_event=25)
    assert event is not None
    bb_peak, days_ago = event
    assert bb_peak > 8
    assert days_ago <= 25


def test_find_50d_high_event_no_breakout():
    closes = list(np.linspace(130, 100, 80))
    vols = [1000] * 80
    assert find_50d_high_event(closes, vols) is None


def test_check_breakout_candle_pass():
    assert check_breakout_candle(
        open_=100, high=105, low=99, close=104,
        volume=3000, ma20_vol=1000,
    ) is True


def test_check_breakout_candle_fail_long_shadow():
    assert check_breakout_candle(
        open_=100, high=110, low=99, close=101,
        volume=3000, ma20_vol=1000,
    ) is False


def test_check_entry_criteria_pass():
    opens, highs, lows, closes, vols = make_ohlcv()
    result = check_entry_criteria(opens, highs, lows, closes, vols)
    # Breakout detected, bb_peak > 8
    assert result["bb_peak"] > 8


def test_check_entry_criteria_fail_too_low():
    # Big drop after breakout → bb_position << -3 → passes=False
    opens = [100.0] * 80
    closes = list(np.concatenate([np.linspace(100, 130, 50), np.linspace(130, 70, 30)]))
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.99 for c in closes]
    vols = [1000] * 80
    vols[49] = 3000
    result = check_entry_criteria(opens, highs, lows, closes, vols)
    assert result["passes"] is False
