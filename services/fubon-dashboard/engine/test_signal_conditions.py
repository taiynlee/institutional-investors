"""
模擬測試：進場條件全路徑驗證
餵假 tick 資料給 SymbolSession + SignalCombiner，確認六關卡邏輯正確。
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
from engine.data.session_state import SymbolSession
from engine.strategy.signal_combiner import SignalCombiner

TZ = ZoneInfo("Asia/Taipei")

PASS = 0
FAIL = 0

def check(label: str, result, expect_enter: bool, expect_reason_contains: str = ""):
    global PASS, FAIL
    ok = result.should_enter == expect_enter
    if expect_reason_contains and not result.should_enter:
        ok = ok and expect_reason_contains in result.reason
    status = "✅ PASS" if ok else "❌ FAIL"
    if not ok:
        FAIL += 1
        print(f"{status} {label}")
        print(f"       期望 enter={expect_enter} reason~'{expect_reason_contains}'")
        print(f"       實際 enter={result.should_enter} reason='{result.reason}'")
    else:
        PASS += 1
        print(f"{status} {label}  reason='{result.reason}'")


def make_session(ref_price=100.0) -> SymbolSession:
    return SymbolSession("TEST", ref_price, ref_price * 1.1)


def make_combiner(max_change_pct=5.0) -> SignalCombiner:
    return SignalCombiner(max_change_pct=max_change_pct)


# 模擬時間固定在 10:00（在窗口內）
TRADE_TIME = dtime(10, 0, 0)
NOW_TW_DT  = datetime(2026, 7, 14, 10, 0, 0, tzinfo=TZ)


def feed_ticks(sess: SymbolSession, price: float, count: int = 5, size: int = 1000):
    """模擬餵 tick：固定時間點，不更動 _min_vol_hist（用於快速建 quote_history）"""
    with patch("engine.data.session_state.now_tw", return_value=NOW_TW_DT):
        for _ in range(count):
            sess.on_tick(price, size, 0, tick_window_seconds=60)
            sess.on_bid_ask_tick(size, 0, window_seconds=60)  # 全外盤


def feed_minutes(sess: SymbolSession, price: float, minutes: int = 6,
                 size_per_min: int = 300000):
    """模擬跨越 N 個分鐘邊界，讓 _min_vol_hist 累積足夠資料"""
    base = datetime(2026, 7, 14, 9, 0, 0, tzinfo=TZ)
    for m in range(minutes + 1):
        dt = base + timedelta(minutes=m)
        with patch("engine.data.session_state.now_tw", return_value=dt):
            sess.on_tick(price, size_per_min, 0, tick_window_seconds=60)
            sess.on_bid_ask_tick(size_per_min, 0, window_seconds=60)


def evaluate(sess, combiner, price, past_avg, vol_1m_lots=None,
             tick_rise=5.0, bid_pct=90.0,
             tick_rise_threshold=4, bid_1m_pct_threshold=85.0, vol_1m_coef=0.8,
             positions_count=0, max_positions=5, not_in_pos=True,
             trade_time=TRADE_TIME):
    """呼叫 evaluate，繞開 curr_price 直接給參數"""
    sess.curr_price = price
    vol_lots = vol_1m_lots if vol_1m_lots is not None else sess.vol_1m_lots
    return combiner.evaluate(
        symbol="TEST",
        time_ok=True,
        not_in_position=not_in_pos,
        positions_count=positions_count,
        max_positions=max_positions,
        change_pct=sess.change_pct,
        check_not_in_position=True,
        vol_ratio=100.0,
        vol_ratio_min_pct=0.0,
        tick_rise=tick_rise,
        tick_rise_threshold=tick_rise_threshold,
        bid_1m_pct=bid_pct,
        bid_1m_pct_threshold=bid_1m_pct_threshold,
        vol_1m_lots=vol_lots,
        past_5min_avg_vol=past_avg,
        vol_1m_coef=vol_1m_coef,
    )


print("=" * 60)
print("A. 時間/持倉/次數/漲跌幅 基本關卡")
print("=" * 60)

sess = make_session(100.0)
feed_minutes(sess, 100.0)
c = make_combiner()

# A1 時間不在窗口 → time_not_ok
r = c.evaluate("TEST", time_ok=False, not_in_position=True,
               positions_count=0, max_positions=5, change_pct=1.0,
               past_5min_avg_vol=500, vol_1m_coef=0.8, vol_1m_lots=600,
               tick_rise=5, tick_rise_threshold=4, bid_1m_pct=90, bid_1m_pct_threshold=85)
check("A1 時間不在窗口", r, False, "time_not_ok")

# A2 已持倉 → already_in_position
r = c.evaluate("TEST", time_ok=True, not_in_position=False,
               positions_count=0, max_positions=5, change_pct=1.0,
               past_5min_avg_vol=500, vol_1m_coef=0.8, vol_1m_lots=600,
               tick_rise=5, tick_rise_threshold=4, bid_1m_pct=90, bid_1m_pct_threshold=85)
check("A2 已持倉", r, False, "already_in_position")

# A3 今日次數達上限
r = c.evaluate("TEST", time_ok=True, not_in_position=True,
               positions_count=5, max_positions=5, change_pct=1.0,
               past_5min_avg_vol=500, vol_1m_coef=0.8, vol_1m_lots=600,
               tick_rise=5, tick_rise_threshold=4, bid_1m_pct=90, bid_1m_pct_threshold=85)
check("A3 今日次數達上限", r, False, "max_daily_trades_reached")

# A4 漲幅超過 +5% → 拒絕
r = c.evaluate("TEST", time_ok=True, not_in_position=True,
               positions_count=0, max_positions=5, change_pct=5.1,
               past_5min_avg_vol=500, vol_1m_coef=0.8, vol_1m_lots=600,
               tick_rise=5, tick_rise_threshold=4, bid_1m_pct=90, bid_1m_pct_threshold=85)
check("A4 漲幅 +5.1% 超限", r, False, "change_pct_exceeded")

# A5 跌幅超過 -5%（雙向過濾）
r = c.evaluate("TEST", time_ok=True, not_in_position=True,
               positions_count=0, max_positions=5, change_pct=-5.5,
               past_5min_avg_vol=500, vol_1m_coef=0.8, vol_1m_lots=600,
               tick_rise=5, tick_rise_threshold=4, bid_1m_pct=90, bid_1m_pct_threshold=85)
check("A5 跌幅 -5.5% 雙向過濾", r, False, "change_pct_exceeded")

print()
print("=" * 60)
print("B. ⑤a tick 上漲條件")
print("=" * 60)

# B1 tick_rise 不足
r = evaluate(make_session(), c, 100.0, past_avg=500, vol_1m_lots=600, tick_rise=3)
check("B1 tick↑=3 不足門檻4", r, False, "tick_rise_low")

# B2 tick_rise 剛好等於門檻
r = evaluate(make_session(), c, 100.0, past_avg=500, vol_1m_lots=600, tick_rise=4)
check("B2 tick↑=4 剛好達門檻", r, True)

# B3 tick_rise_threshold=0 → 關閉條件
r = evaluate(make_session(), c, 100.0, past_avg=500, vol_1m_lots=600,
             tick_rise=0, tick_rise_threshold=0)
check("B3 tick門檻=0（關閉），tick↑=0仍通過", r, True)

print()
print("=" * 60)
print("C. ⑤b 外盤佔比條件")
print("=" * 60)

# C1 外盤% 不足
r = evaluate(make_session(), c, 100.0, past_avg=500, vol_1m_lots=600, bid_pct=84.9)
check("C1 外盤%=84.9% 不足門檻85%", r, False, "bid1m_low")

# C2 外盤% 剛好
r = evaluate(make_session(), c, 100.0, past_avg=500, vol_1m_lots=600, bid_pct=85.0)
check("C2 外盤%=85.0% 剛好達門檻", r, True)

print()
print("=" * 60)
print("D. ⑤c 外盤量條件（含修正後 bypass 邏輯）")
print("=" * 60)

# D1 修正前 bug：avg=0 應拒絕（不是 bypass）
r = evaluate(make_session(), c, 100.0, past_avg=0.0, vol_1m_lots=0.0)
check("D1 avg=0 → vol_avg_not_ready（修正後）", r, False, "vol_avg_not_ready")

# D2 vol_1m_coef=0 → 關閉⑤c，avg=0也應通過
r = evaluate(make_session(), c, 100.0, past_avg=0.0, vol_1m_lots=0.0, vol_1m_coef=0.0)
check("D2 vol_1m_coef=0（關閉），avg=0仍通過", r, True)

# D3 外盤量不足
r = evaluate(make_session(), c, 100.0, past_avg=1000.0, vol_1m_lots=799.9)
check("D3 外盤量=799.9 < 1000×0.8=800 → 拒絕", r, False, "vol_1m_low")

# D4 外盤量剛好達門檻
r = evaluate(make_session(), c, 100.0, past_avg=1000.0, vol_1m_lots=800.0)
check("D4 外盤量=800.0 = 1000×0.8 → 通過", r, True)

# D5 外盤量超過門檻
r = evaluate(make_session(), c, 100.0, past_avg=1000.0, vol_1m_lots=1200.0)
check("D5 外盤量=1200 > 門檻 → 通過", r, True)

print()
print("=" * 60)
print("E. 完整路徑：SymbolSession 餵真實假 tick")
print("=" * 60)

# E1 模擬重啟後 2 分鐘內（_min_vol_hist 空）→ 拒絕
sess_fresh = make_session(100.0)
with patch("engine.data.session_state.now_tw", return_value=NOW_TW_DT):
    # 只餵 1 分鐘的 tick，不跨分鐘邊界 → hist 仍空
    for _ in range(10):
        sess_fresh.on_tick(102.0, 1000, 0)
        sess_fresh.on_bid_ask_tick(1000, 0)
avg_fresh = sess_fresh.past_5min_avg_vol_lots
r = evaluate(sess_fresh, c, 102.0, past_avg=avg_fresh,
             vol_1m_lots=sess_fresh.vol_1m_lots, tick_rise=5)
check(f"E1 重啟後 hist 空（avg={avg_fresh}）→ vol_avg_not_ready", r, False, "vol_avg_not_ready")

# E2 模擬正常運行：跨6個分鐘邊界後
sess_mature = make_session(100.0)
feed_minutes(sess_mature, 100.0, minutes=6, size_per_min=300000)
# 最後在 10:00 餵外盤 tick
with patch("engine.data.session_state.now_tw", return_value=NOW_TW_DT):
    for _ in range(20):
        sess_mature.on_bid_ask_tick(50000, 0)
avg_mature = sess_mature.past_5min_avg_vol_lots
vol_mature = sess_mature.vol_1m_lots
sess_mature.curr_price = 102.0  # 漲了 2%
r = evaluate(sess_mature, c, 102.0, past_avg=avg_mature,
             vol_1m_lots=vol_mature, tick_rise=5)
check(f"E2 正常運行 avg={avg_mature:.0f}張 vol={vol_mature:.1f}張 → ok", r, True)

# E3 正常運行但外盤量不足
sess_lowvol = make_session(100.0)
feed_minutes(sess_lowvol, 100.0, minutes=6, size_per_min=300000)
avg_lv = sess_lowvol.past_5min_avg_vol_lots
r = evaluate(sess_lowvol, c, 102.0, past_avg=avg_lv,
             vol_1m_lots=1.0, tick_rise=5)  # vol_1m=1張 << 需要240張
check(f"E3 外盤量不足（avg={avg_lv:.0f}，需{avg_lv*0.8:.0f}，實際1張）", r, False, "vol_1m_low")

print()
print("=" * 60)
print(f"結果：{PASS} 通過 / {FAIL} 失敗")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
