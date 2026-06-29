"""
手動測試 _on_filled callback 邏輯
不需要 SDK、不需要引擎運行
執行：python services/fubon-dashboard/engine/test_fill_callback.py
"""
import logging
from datetime import datetime

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
logger = logging.getLogger("test")

# ── Mock deps ─────────────────────────────────────────────────────────────────

class MockBroker:
    def __init__(self):
        self.calls = []
    def buy(self, symbol, lots, price, order_type_override="stock", user_def=""):
        tag = f"BUY {symbol} {lots}張 @ {price} [{user_def}]"
        self.calls.append(tag)
        print(f"  [BROKER] {tag}")
    def sell(self, symbol, lots, price, reason="", user_def=""):
        tag = f"SELL {symbol} {lots}張 @ {price} reason={reason} [{user_def}]"
        self.calls.append(tag)
        print(f"  [BROKER] {tag}")

def now_tw():
    return datetime.now()

def sname(sym):
    return {"2330": "台積電", "2317": "鴻海", "2454": "聯發科"}.get(sym, sym)

# ── Replicate _on_filled (同 trading_engine.py 邏輯) ──────────────────────────

def make_on_filled(broker, pending_buys, pending_sells):
    def _on_filled(*args):
        try:
            data = args[-1] if args else None
            if data is None:
                return
            d = data if isinstance(data, dict) else vars(data)
            udef       = str(d.get('user_def', '') or '')
            filled_qty = int(d.get('filled_qty', 0) or 0)
            filled_px  = float(d.get('filled_price', 0) or d.get('filled_avg_price', 0) or 0)
            stock_no   = str(d.get('stock_no', '') or '')

            if not udef.startswith('auto_'):
                return

            sym = stock_no
            if not sym and '_' in udef:
                parts = udef.split('_', 2)
                sym = parts[2] if len(parts) >= 3 else ''

            actual_lots = filled_qty // 1000

            if udef.startswith('auto_buy_'):
                pending = pending_buys.pop(sym, None)
                if pending:
                    expected = pending['lots']
                    if actual_lots < expected:
                        remaining = expected - actual_lots
                        logger.warning("買進部分成交 %s %d/%d張，補送 %d張 @ %.2f",
                                       sym, actual_lots, expected, remaining, pending['price'])
                        try:
                            broker.buy(sym, remaining, pending['price'],
                                       order_type_override=pending.get('order_type', 'stock'),
                                       user_def=f"auto_buy_{sym}")
                            pending_buys[sym] = {**pending, 'lots': remaining,
                                                  'sent_at': now_tw().isoformat()}
                        except Exception as e:
                            logger.error("補買失敗 %s: %s", sym, e)
                    else:
                        logger.info("✅ 買進全數成交 %s %d張 @ %.2f", sym, actual_lots, filled_px)

            elif udef.startswith('auto_fe_'):
                pending = pending_sells.pop(sym, None)
                if pending:
                    expected = pending['lots']
                    if actual_lots < expected:
                        logger.warning("強制出場部分成交 %s %d/%d張（ROD備援處理剩餘）",
                                       sym, actual_lots, expected)
                    else:
                        logger.info("✅ 強制出場全數成交 %s %d張 @ %.2f", sym, actual_lots, filled_px)

            elif udef.startswith(('auto_sell_', 'auto_lsell_')):
                pending = pending_sells.pop(sym, None)
                if pending:
                    expected = pending['lots']
                    if actual_lots < expected:
                        remaining = expected - actual_lots
                        logger.warning("賣出部分成交 %s %d/%d張，補送 %d張",
                                       sym, actual_lots, expected, remaining)
                        try:
                            broker.sell(sym, remaining, filled_px,
                                        reason=pending.get('reason', 'partial_fill'),
                                        user_def=f"auto_sell_{sym}")
                            pending_sells[sym] = {**pending, 'lots': remaining,
                                                   'sent_at': now_tw().isoformat()}
                        except Exception as e:
                            logger.error("補賣失敗 %s: %s", sym, e)
                    else:
                        logger.info("✅ 出場全數成交 %s %d張 @ %.2f（%s）",
                                    sym, actual_lots, filled_px, pending.get('reason', '?'))
        except Exception as e:
            logger.debug("on_filled parse error: %s", e)
    return _on_filled


def run_test(name, fn):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print('='*60)
    broker = MockBroker()
    pending_buys: dict = {}
    pending_sells: dict = {}
    on_filled = make_on_filled(broker, pending_buys, pending_sells)
    fn(on_filled, broker, pending_buys, pending_sells)
    print(f"  pending_buys  after: {pending_buys}")
    print(f"  pending_sells after: {pending_sells}")
    print(f"  broker calls: {broker.calls}")
    return broker, pending_buys, pending_sells


# ── Test cases ────────────────────────────────────────────────────────────────

def test_buy_full(on_filled, broker, pb, ps):
    pb["2330"] = {"lots": 3, "price": 1000.0, "sent_at": "10:00", "order_type": "stock"}
    on_filled({"user_def": "auto_buy_2330", "filled_qty": 3000, "filled_price": 999.0, "stock_no": "2330"})
    assert not pb, "pending_buys should be empty after full fill"
    assert not broker.calls, "no re-order expected"
    print("  PASS ✓")

def test_buy_partial(on_filled, broker, pb, ps):
    pb["2317"] = {"lots": 5, "price": 200.0, "sent_at": "10:00", "order_type": "stock"}
    on_filled({"user_def": "auto_buy_2317", "filled_qty": 2000, "filled_price": 199.5, "stock_no": "2317"})
    assert "2317" in pb and pb["2317"]["lots"] == 3, f"should have 3 remaining, got {pb}"
    assert any("BUY 2317 3張" in c for c in broker.calls), f"re-order expected: {broker.calls}"
    print("  PASS ✓")

def test_sell_full(on_filled, broker, pb, ps):
    ps["2454"] = {"lots": 2, "price": 800.0, "sent_at": "11:00", "reason": "stop_loss"}
    on_filled({"user_def": "auto_sell_2454", "filled_qty": 2000, "filled_price": 795.0, "stock_no": "2454"})
    assert not ps, "pending_sells should be empty after full fill"
    assert not broker.calls, "no re-order expected"
    print("  PASS ✓")

def test_sell_partial(on_filled, broker, pb, ps):
    ps["2330"] = {"lots": 4, "price": 990.0, "sent_at": "13:00", "reason": "take_profit"}
    on_filled({"user_def": "auto_sell_2330", "filled_qty": 1000, "filled_price": 991.0, "stock_no": "2330"})
    assert "2330" in ps and ps["2330"]["lots"] == 3, f"should have 3 remaining, got {ps}"
    assert any("SELL 2330 3張" in c for c in broker.calls), f"re-order expected: {broker.calls}"
    print("  PASS ✓")

def test_force_exit_partial_no_reorder(on_filled, broker, pb, ps):
    # auto_fe_ 部分成交 → 不補單（有 ROD 備援）
    ps["2317"] = {"lots": 3, "price": 195.0, "sent_at": "13:25", "reason": "force_exit_loop"}
    on_filled({"user_def": "auto_fe_2317", "filled_qty": 1000, "filled_price": 194.0, "stock_no": "2317"})
    assert not ps, "pending_sells should be popped even on partial"
    assert not broker.calls, "NO re-order for force_exit (ROD backup handles it)"
    print("  PASS ✓")

def test_non_engine_order_ignored(on_filled, broker, pb, ps):
    on_filled({"user_def": "manual_sell_2330", "filled_qty": 1000, "filled_price": 999.0, "stock_no": "2330"})
    assert not broker.calls, "manual order should be ignored"
    print("  PASS ✓")

def test_stock_no_from_user_def(on_filled, broker, pb, ps):
    # stock_no 空時從 user_def 解析
    pb["2454"] = {"lots": 2, "price": 810.0, "sent_at": "09:30", "order_type": "stock"}
    on_filled({"user_def": "auto_buy_2454", "filled_qty": 2000, "filled_price": 810.0, "stock_no": ""})
    assert not pb, "should resolve sym from user_def"
    print("  PASS ✓")


if __name__ == "__main__":
    tests = [
        ("買進全數成交",               test_buy_full),
        ("買進部分成交→補單",           test_buy_partial),
        ("賣出全數成交",               test_sell_full),
        ("賣出部分成交→補單",           test_sell_partial),
        ("強制出場部分成交→不補單",      test_force_exit_partial_no_reorder),
        ("非引擎委託忽略",             test_non_engine_order_ignored),
        ("stock_no空時從user_def解析", test_stock_no_from_user_def),
    ]

    passed = failed = 0
    for name, fn in tests:
        try:
            run_test(name, fn)
            passed += 1
        except AssertionError as e:
            print(f"  FAIL ✗  {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR  {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"結果：{passed} 通過 / {failed} 失敗")
