import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)


def tw_tick_size(price: float) -> float:
    """台股最小跳動單位（依股價）"""
    if price < 10:
        return 0.01
    if price < 50:
        return 0.05
    if price < 100:
        return 0.1
    if price < 500:
        return 0.5
    if price < 1000:
        return 1.0
    return 5.0


def round_up_tick(price: float) -> float:
    """向上捨入到最近有效 tick（觸價單用：確保在停損前觸發）"""
    tick = tw_tick_size(price)
    # math.ceil 以 tick 為單位，避免浮點誤差
    return round(math.ceil(round(price / tick, 8)) * tick, 8)


def round_down_tick(price: float) -> float:
    """向下捨入到最近有效 tick（限價買單用）"""
    tick = tw_tick_size(price)
    return round(math.floor(round(price / tick, 8)) * tick, 8)


class FubonBroker:
    """fubon-neo SDK 封裝。dry_run=True 時只 log，不實際下單。"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._sdk = None
        self._account = None

    def initialize(self, sdk, account=None):
        self._sdk = sdk
        self._account = account

    def buy(self, symbol: str, lots: int, price: float):
        price = round_down_tick(price)
        if self.dry_run:
            logger.info("[DRY RUN] BUY %s x%d張 @ %.2f", symbol, lots, price)
            return
        if self._sdk is None:
            raise RuntimeError("SDK not initialized")
        from fubon_neo.sdk import Order
        from fubon_neo.constant import BSAction, MarketType, PriceType, TimeInForce, OrderType
        order = Order(
            buy_sell=BSAction.Buy,
            symbol=symbol,
            quantity=lots * 1000,
            market_type=MarketType.Common,
            price_type=PriceType.Limit,
            time_in_force=TimeInForce.ROD,
            order_type=OrderType.DayTrade,
            price=str(price),
        )
        result = self._sdk.stock.place_order(self._account, order)
        logger.info("BUY %s result: %s", symbol, result)

    def sell(self, symbol: str, lots: int, price: float, reason: str = ""):
        if self.dry_run:
            logger.info("[DRY RUN] SELL %s x%d張 @ %.2f | 原因:%s", symbol, lots, price, reason)
            return
        if self._sdk is None:
            raise RuntimeError("SDK not initialized")
        from fubon_neo.sdk import Order
        from fubon_neo.constant import BSAction, MarketType, PriceType, TimeInForce, OrderType
        order = Order(
            buy_sell=BSAction.Sell,
            symbol=symbol,
            quantity=lots * 1000,
            market_type=MarketType.Common,
            price_type=PriceType.Market,
            time_in_force=TimeInForce.IOC,
            order_type=OrderType.DayTrade,
        )
        result = self._sdk.stock.place_order(self._account, order)
        logger.info("SELL %s reason=%s result: %s", symbol, reason, result)

    def place_conditional_stop(
        self,
        symbol: str,
        lots: int,
        stop_price: float,
        trade_date: str,
    ) -> Optional[str]:
        """掛觸價賣單（停損）。當成交價 <= stop_price 時市價賣出。

        dry_run=True 時只 log，回傳 None。
        實際下單成功回傳 condition guid，失敗回傳 None。
        """
        # 捨入到有效 tick（向上 = 更早觸發，保護性更強）
        raw = stop_price
        stop_price = round_up_tick(stop_price)
        if stop_price != raw:
            logger.info("觸價單 stop_price %.2f → %.2f (tick adjust)", raw, stop_price)
        if self.dry_run:
            logger.info("[DRY RUN] COND STOP %s x%d張 stop_price=%.2f", symbol, lots, stop_price)
            return None
        if self._sdk is None or self._account is None:
            logger.error("觸價單：SDK 或 account 未初始化")
            return None
        try:
            from fubon_neo.sdk import Condition, ConditionOrder
            from fubon_neo.constant import (
                TriggerContent, Operator, ConditionPriceType,
                ConditionMarketType, BSAction, ConditionOrderType,
                StopSign, TimeInForce,
            )
            condition = Condition(
                market_type=ConditionMarketType.Common,
                symbol=symbol,
                trigger=TriggerContent.MatchedPrice,
                trigger_value=stop_price,
                comparison=Operator.LessThanOrEqual,
            )
            order = ConditionOrder(
                buy_sell=BSAction.Sell,
                symbol=symbol,
                market_type=ConditionMarketType.Common,
                price_type=ConditionPriceType.Market,
                time_in_force=TimeInForce.ROD,
                order_type=ConditionOrderType.DayTrade,
                quantity=lots * 1000,
            )
            result = self._sdk.stock.single_condition(
                account=self._account,
                start_date=trade_date,
                end_date=trade_date,
                stop_sign=StopSign.Full,
                condition=condition,
                order=order,
            )
            if result and getattr(result, "is_success", False):
                data = getattr(result, "data", {}) or {}
                guid = data.get("id") or data.get("guid") or str(result)
                logger.info("觸價賣單成功 %s stop=%.2f guid=%s", symbol, stop_price, guid)
                return str(guid)
            else:
                logger.error("觸價賣單失敗 %s: %s", symbol, result)
                return None
        except Exception as e:
            logger.error("觸價賣單例外 %s: %s", symbol, e)
            return None

    def cancel_conditional_stop(self, guid: str):
        """取消觸價賣單。"""
        if self.dry_run or not guid:
            return
        if self._sdk is None or self._account is None:
            return
        try:
            self._sdk.stock.cancel_condition_orders(account=self._account, guid=guid)
            logger.info("觸價單取消 guid=%s", guid)
        except Exception as e:
            logger.error("取消觸價單失敗 guid=%s: %s", guid, e)
