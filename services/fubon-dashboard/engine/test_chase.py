"""
測試追價邏輯（買入/賣出）和 Option A（確認後才記持倉）
執行：python3 services/fubon-dashboard/engine/test_chase.py
"""
import logging
import math
from datetime import datetime, time as dtime
from typing import Optional

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
logger = logging.getLogger("test")

# ── 從 broker.py 複製 tick size 工具 ─────────────────────────────────────────

def tw_tick_size(price: float) -> float:
    if price < 10:   return 0.01
    if price < 50:   return 0.05
    if price < 100:  return 0.1
    if price < 500:  return 0.5
    if price < 1000: return 1.0
    return 5.0

def round_up_tick(price: float) -> float:
    tick = tw_tick_size(price)
    return round(math.ceil(round(price / tick, 8)) * tick, 8)

def round_down_tick(price: float) -> float:
    tick = tw_tick_size(price)
    return round(math.floor(round(price / tick, 8)) * tick, 8)

# ── Mock deps ─────────────────────────────────────────────────────────────────

class MockBroker:
    def __init__(self):
        self.calls = []
        self._order_counter = 0
        self.dry_run = False

    def _next_no(self):
        self._order_counter += 1
        return f"ORD{self._order_counter:04d}"

    def buy(self, symbol, lots, price, order_type_override="stock", user_def=""):
        no = self._next_no()
        tag = f"BUY {symbol} {lots}張 @{price:.2f} [{user_def}] → {no}"
        self.calls.append(tag); print(f"  [BROKER] {tag}")
        return no

    def sell(self, symbol, lots, price, reason="", user_def=""):
        no = self._next_no()
        mode = f"市價IOC" if price <= 0 else f"限價ROD@{price:.2f}"
        tag = f"SELL {symbol} {lots}張 {mode} reason={reason} [{user_def}] → {no}"
        self.calls.append(tag); print(f"  [BROKER] {tag}")
        return no

    def cancel_order(self, order_no):
        tag = f"CANCEL {order_no}"
        self.calls.append(tag); print(f"  [BROKER] {tag}")

    def place_conditional_stop(self, symbol, lots, stop_price, trade_date):
        no = self._next_no()
        print(f"  [BROKER] COND_STOP {symbol} {lots}張 stop={stop_price:.2f} → {no}")
        return no

    def place_conditional_take_profit(self, symbol, lots, trigger_price, trade_date):
        no = self._next_no()
        print(f"  [BROKER] COND_TP {symbol} {lots}張 tp={trigger_price:.2f} → {no}")
        return no

class MockPosition:
    def __init__(self, symbol, entry_price, lots, stop_loss, take_profit):
        self.symbol = symbol
        self.entry_price = entry_price
        self.lots = lots
        self.stop_loss = stop_loss
        self.take_profit = take_profit

def now_tw():
    return datetime.now()

def sname(sym):
    return {"2330": "台積電", "2317": "鴻海"}.get(sym, sym)

# ── 模擬引擎狀態 ──────────────────────────────────────────────────────────────

def make_engine_state():
    return dict(
        positions={},       # om.positions
        condition_ids={},
        _chase_buys={},
        _chase_sells={},
        _pending_buys={},
        _pending_sells={},
    )

# ── 追價 on_tick 邏輯（複製自 trading_engine.py）────────────────────────────

def simulate_on_tick(sym, price, broker, s):
    tick_sz = tw_tick_size(price)

    # 追價買
    if sym in s["_chase_buys"] and sym not in s["positions"]:
        cb = s["_chase_buys"][sym]
        if price - cb["order_price"] >= 2 * tick_sz:
            if not cb.get("chased"):
                chase_px = round_up_tick(price + tick_sz)
                logger.warning("追價買進 %s: 原%.2f 現%.2f → 追%.2f（最後機會）",
                               sym, cb["order_price"], price, chase_px)
                if cb.get("order_no"):
                    broker.cancel_order(cb["order_no"])
                new_no = broker.buy(sym, cb["lots"], chase_px,
                                    user_def=f"auto_buy_{sym}")
                cb["order_price"] = chase_px
                cb["order_no"] = new_no
                cb["chased"] = True
            else:
                logger.warning("追價買進 %s 再次未成，放棄", sym)
                if cb.get("order_no"):
                    broker.cancel_order(cb["order_no"])
                s["_chase_buys"].pop(sym, None)
                s["_pending_buys"].pop(sym, None)

    # 追價賣
    if sym in s["_chase_sells"]:
        cs = s["_chase_sells"][sym]
        if cs["order_price"] - price >= 2 * tick_sz:
            chase_px = round_down_tick(price - tick_sz)
            cs["chase_count"] = cs.get("chase_count", 0) + 1
            logger.warning("追價賣出 %s: 原%.2f 現%.2f → 追%.2f（第%d次）",
                           sym, cs["order_price"], price, chase_px, cs["chase_count"])
            if cs.get("order_no"):
                broker.cancel_order(cs["order_no"])
            new_no = broker.sell(sym, cs["lots"], chase_px,
                                  reason=cs.get("reason", "chase_sell"),
                                  user_def=f"auto_sell_{sym}")
            cs["order_price"] = chase_px
            cs["order_no"] = new_no
            s["_pending_sells"][sym] = {
                "lots": cs["lots"], "price": chase_px,
                "sent_at": now_tw().isoformat(), "reason": cs.get("reason"),
            }

# ── on_filled 邏輯（複製自 trading_engine.py）────────────────────────────────

def simulate_on_filled(data, broker, s, today_str="2026/06/29"):
    udef       = str(data.get("user_def", "") or "")
    filled_qty = int(data.get("filled_qty", 0) or 0)
    filled_px  = float(data.get("filled_price", 0) or 0)
    stock_no   = str(data.get("stock_no", "") or "")

    if not udef.startswith("auto_"):
        return

    sym = stock_no or (udef.split("_", 2)[2] if "_" in udef else "")
    actual_lots = filled_qty // 1000

    if udef.startswith("auto_buy_"):
        chase = s["_chase_buys"].get(sym)
        if sym not in s["positions"] and chase:
            s["_chase_buys"].pop(sym, None)
            s["_pending_buys"].pop(sym, None)
            ep = filled_px if filled_px > 0 else chase["order_price"]
            ref = chase.get("ref_price", ep)
            stop_loss   = round_up_tick(ep - 3 * tw_tick_size(ep))
            take_profit = round_down_tick(ep * 1.02)
            pos = MockPosition(sym, ep, actual_lots, stop_loss, take_profit)
            s["positions"][sym] = pos
            sl_g = broker.place_conditional_stop(sym, actual_lots, stop_loss, today_str)
            tp_g = broker.place_conditional_take_profit(sym, actual_lots, take_profit, today_str)
            s["condition_ids"][sym] = {"sl": sl_g, "tp": tp_g}
            logger.info("✅ 買進成交 %s %d張 @ %.2f → 持倉已建立", sym, actual_lots, ep)
            expected = chase.get("lots", actual_lots)
            if actual_lots < expected:
                remaining = expected - actual_lots
                logger.warning("部分成交 %s 補送 %d張", sym, remaining)
                new_no = broker.buy(sym, remaining, ep, user_def=f"auto_buy_{sym}")
                s["_pending_buys"][sym] = {"lots": remaining, "price": ep,
                                            "order_no": new_no,
                                            "sent_at": now_tw().isoformat()}
        else:
            s["_pending_buys"].pop(sym, None)
            if sym in s["positions"]:
                s["positions"][sym].lots += actual_lots
                logger.info("✅ 買進補足 %s +%d張 合計%d張", sym, actual_lots, s["positions"][sym].lots)

    elif udef.startswith("auto_fe_"):
        s["_pending_sells"].pop(sym, None)
        s["_chase_sells"].pop(sym, None)
        logger.info("✅ 強制出場成交 %s %d張 @ %.2f", sym, actual_lots, filled_px)

    elif udef.startswith(("auto_sell_", "auto_lsell_")):
        pending = s["_pending_sells"].pop(sym, None)
        if pending:
            expected = pending["lots"]
            if actual_lots < expected:
                remaining = expected - actual_lots
                cs = s["_chase_sells"].get(sym)
                logger.warning("賣出部分成交 %s %d/%d張，補送 %d張", sym, actual_lots, expected, remaining)
                new_no = broker.sell(sym, remaining, filled_px,
                                      reason=pending.get("reason", "partial"),
                                      user_def=f"auto_sell_{sym}")
                s["_pending_sells"][sym] = {**pending, "lots": remaining}
                if cs:
                    cs["lots"] = remaining
                    cs["order_price"] = filled_px
                    cs["order_no"] = new_no
            else:
                s["_chase_sells"].pop(sym, None)
                logger.info("✅ 出場全數成交 %s %d張 @ %.2f（%s）",
                            sym, actual_lots, filled_px, pending.get("reason"))

# ── Test helpers ──────────────────────────────────────────────────────────────

def run_test(name, fn):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print("="*60)
    broker = MockBroker()
    s = make_engine_state()
    try:
        fn(broker, s)
        print("  PASS ✓")
    except AssertionError as e:
        print(f"  FAIL ✗  {e}")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  ERROR  {e}")

# ── Tests ─────────────────────────────────────────────────────────────────────

def test_buy_no_drift(broker, s):
    """無漂移 → 不追價"""
    no = broker.buy("2330", 2, 510.0, user_def="auto_buy_2330")
    s["_chase_buys"]["2330"] = {"lots": 2, "order_price": 510.0, "ref_price": 500.0,
                                 "order_no": no, "chased": False}
    simulate_on_tick("2330", 511.0, broker, s)  # 1 tick，不追
    assert "2330" in s["_chase_buys"], "chase_buys 應還存在"
    assert not any("CANCEL" in c for c in broker.calls), "不應取消"
    assert broker.calls.count(f"CANCEL {no}") == 0

def test_buy_chase_once(broker, s):
    """漂移 2 tick → 追一次"""
    no = broker.buy("2330", 2, 510.0, user_def="auto_buy_2330")
    s["_chase_buys"]["2330"] = {"lots": 2, "order_price": 510.0, "ref_price": 500.0,
                                 "order_no": no, "chased": False}
    simulate_on_tick("2330", 512.0, broker, s)  # 2 tick → 追到 513
    cb = s["_chase_buys"].get("2330")
    assert cb and cb["chased"], "chased 應為 True"
    assert cb["order_price"] == 513.0, f"追價應到 513, got {cb['order_price']}"
    assert any("CANCEL" in c and "ORD0001" in c for c in broker.calls)
    assert any("BUY 2330 2張 @513.00" in c for c in broker.calls)

def test_buy_chase_abandon(broker, s):
    """已追過一次，再次漂移 → 放棄"""
    no1 = broker.buy("2330", 2, 510.0, user_def="auto_buy_2330")
    s["_chase_buys"]["2330"] = {"lots": 2, "order_price": 513.0, "ref_price": 500.0,
                                 "order_no": no1, "chased": True}
    simulate_on_tick("2330", 516.0, broker, s)  # 再次 2 tick → 放棄
    assert "2330" not in s["_chase_buys"], "chase_buys 應清空"
    assert "2330" not in s["positions"], "持倉不應建立"

def test_buy_confirmed_builds_position(broker, s):
    """on_filled → 建倉 + 掛條件單"""
    no = broker.buy("2330", 2, 510.0, user_def="auto_buy_2330")
    s["_chase_buys"]["2330"] = {"lots": 2, "order_price": 510.0, "ref_price": 500.0,
                                 "order_no": no, "chased": False}
    assert "2330" not in s["positions"], "成交前不應有持倉"
    simulate_on_filled({"user_def": "auto_buy_2330", "filled_qty": 2000,
                         "filled_price": 510.0, "stock_no": "2330"}, broker, s)
    assert "2330" in s["positions"], "成交後應有持倉"
    assert s["positions"]["2330"].lots == 2
    cids = s["condition_ids"].get("2330", {})
    assert cids.get("sl"), "應有停損條件單 guid"
    assert cids.get("tp"), "應有停利條件單 guid"

def test_buy_no_position_before_filled(broker, s):
    """委託送出後到 on_filled 前，持倉不應存在"""
    no = broker.buy("2330", 3, 500.0, user_def="auto_buy_2330")
    s["_chase_buys"]["2330"] = {"lots": 3, "order_price": 500.0, "ref_price": 490.0,
                                 "order_no": no, "chased": False}
    simulate_on_tick("2330", 501.0, broker, s)  # 1 tick，無追
    assert "2330" not in s["positions"], "成交確認前不應建倉"

def test_buy_partial_fill(broker, s):
    """部分成交 → 建倉（實際張數）+ 補送剩餘"""
    no = broker.buy("2330", 3, 510.0, user_def="auto_buy_2330")
    s["_chase_buys"]["2330"] = {"lots": 3, "order_price": 510.0, "ref_price": 500.0,
                                 "order_no": no, "chased": False}
    simulate_on_filled({"user_def": "auto_buy_2330", "filled_qty": 2000,
                         "filled_price": 510.0, "stock_no": "2330"}, broker, s)
    assert s["positions"]["2330"].lots == 2, "先建 2 張持倉"
    assert "2330" in s["_pending_buys"], "應有補買委託"
    assert s["_pending_buys"]["2330"]["lots"] == 1

def test_sell_chase(broker, s):
    """賣出後價格跌 2 tick → 追下去（tick=0.5, 2 tick=1.0）"""
    no = broker.sell("2330", 2, 299.0, reason="stop_loss", user_def="auto_sell_2330")
    s["_chase_sells"]["2330"] = {"lots": 2, "order_price": 299.0,
                                  "order_no": no, "chase_count": 0, "reason": "stop_loss"}
    s["_pending_sells"]["2330"] = {"lots": 2, "price": 299.0,
                                    "sent_at": "", "reason": "stop_loss"}
    # 299→298.5 = 1 tick → 不追
    simulate_on_tick("2330", 298.5, broker, s)
    assert s["_chase_sells"]["2330"]["chase_count"] == 0, "1 tick 不應追價"
    # 298.5→298.0 累計 2 tick（order_price=299.0, drift=1.0=2tick） → 觸發追
    simulate_on_tick("2330", 298.0, broker, s)
    assert s["_chase_sells"]["2330"]["chase_count"] == 1, "2 tick 應追一次"
    assert s["_chase_sells"]["2330"]["order_price"] == 297.5, \
        f"追價應到 297.5（298-0.5），got {s['_chase_sells']['2330']['order_price']}"

def test_sell_chase_unlimited(broker, s):
    """賣出一直追，不放棄"""
    no = broker.sell("2330", 2, 299.0, reason="take_profit", user_def="auto_sell_2330")
    s["_chase_sells"]["2330"] = {"lots": 2, "order_price": 299.0,
                                  "order_no": no, "chase_count": 0, "reason": "take_profit"}
    s["_pending_sells"]["2330"] = {"lots": 2, "price": 299.0, "sent_at": "", "reason": "take_profit"}
    prices = [297.0, 295.0, 293.0]  # 每次跌 2 tick
    for p in prices:
        simulate_on_tick("2330", p, broker, s)
    assert s["_chase_sells"]["2330"]["chase_count"] == 3, \
        f"應追 3 次, got {s['_chase_sells']['2330']['chase_count']}"
    assert "2330" in s["_chase_sells"], "賣出不放棄，chase_sells 還在"

def test_sell_full_fill_clears_chase(broker, s):
    """全數成交 → 清除 chase_sells"""
    no = broker.sell("2330", 2, 299.0, reason="stop_loss", user_def="auto_sell_2330")
    s["_chase_sells"]["2330"] = {"lots": 2, "order_price": 299.0,
                                  "order_no": no, "chase_count": 0, "reason": "stop_loss"}
    s["_pending_sells"]["2330"] = {"lots": 2, "price": 299.0, "sent_at": "", "reason": "stop_loss"}
    simulate_on_filled({"user_def": "auto_sell_2330", "filled_qty": 2000,
                         "filled_price": 298.5, "stock_no": "2330"}, broker, s)
    assert "2330" not in s["_chase_sells"], "chase_sells 應清空"
    assert "2330" not in s["_pending_sells"]

def test_sell_partial_fill_updates_chase(broker, s):
    """部分成交 → _chase_sells 更新剩餘張數"""
    no = broker.sell("2330", 3, 299.0, reason="stop_loss", user_def="auto_sell_2330")
    s["_chase_sells"]["2330"] = {"lots": 3, "order_price": 299.0,
                                  "order_no": no, "chase_count": 0, "reason": "stop_loss"}
    s["_pending_sells"]["2330"] = {"lots": 3, "price": 299.0, "sent_at": "", "reason": "stop_loss"}
    simulate_on_filled({"user_def": "auto_sell_2330", "filled_qty": 1000,
                         "filled_price": 299.0, "stock_no": "2330"}, broker, s)
    assert "2330" in s["_chase_sells"], "chase_sells 應保留（還有剩餘）"
    assert s["_chase_sells"]["2330"]["lots"] == 2


if __name__ == "__main__":
    tests = [
        ("買進無漂移→不追",              test_buy_no_drift),
        ("買進漂移2tick→追一次",          test_buy_chase_once),
        ("買進已追過→再漂移→放棄",        test_buy_chase_abandon),
        ("買進on_filled→建倉+條件單",     test_buy_confirmed_builds_position),
        ("Option A：成交前不建倉",        test_buy_no_position_before_filled),
        ("買進部分成交→補送剩餘",          test_buy_partial_fill),
        ("賣出漂移2tick→追下去",          test_sell_chase),
        ("賣出不斷追→不放棄",             test_sell_chase_unlimited),
        ("賣出全數成交→清chase_sells",    test_sell_full_fill_clears_chase),
        ("賣出部分成交→更新chase_sells",  test_sell_partial_fill_updates_chase),
    ]

    passed = failed = 0
    for name, fn in tests:
        broker = MockBroker()
        s = make_engine_state()
        print(f"\n{'='*60}\nTEST: {name}\n{'='*60}")
        try:
            fn(broker, s)
            print("  PASS ✓")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL ✗  {e}")
            failed += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ERROR  {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"結果：{passed} 通過 / {failed} 失敗")
