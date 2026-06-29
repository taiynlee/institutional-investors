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
    """向上捨入到最近有效 tick（停損觸價單：更早觸發）"""
    tick = tw_tick_size(price)
    return round(math.ceil(round(price / tick, 8)) * tick, 8)


def round_down_tick(price: float) -> float:
    """向下捨入到最近有效 tick（停利觸價單：不多加 tick）"""
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

    def _extract_order_no(self, result) -> Optional[str]:
        if result is None:
            return None
        for attr in ("order_no", "ordno", "seq_no", "order_id"):
            v = getattr(result, attr, None)
            if v:
                return str(v)
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            for k in ("order_no", "ordno", "seq_no", "id"):
                if data.get(k):
                    return str(data[k])
        return None

    def cancel_order(self, order_no: str):
        """取消未成交委託（市場單/限價單）。"""
        if not order_no:
            return
        if self.dry_run:
            logger.info("[DRY RUN] CANCEL ORDER %s", order_no)
            return
        if self._sdk is None or self._account is None:
            return
        try:
            self._sdk.stock.cancel_order(account=self._account, order_no=order_no)
            logger.info("取消委託 order_no=%s", order_no)
        except Exception as e:
            logger.warning("取消委託失敗 order_no=%s: %s", order_no, e)

    def buy(self, symbol: str, lots: int, price: float, order_type_override: str = "stock", user_def: str = "") -> Optional[str]:
        """買進限價單。返回 order_no（dry_run 時返回 None）。"""
        price = round_down_tick(price)
        _udef = user_def or f"auto_buy_{symbol}"
        if self.dry_run:
            logger.info("[DRY RUN] BUY %s x%d張 @ %.2f user_def=%s", symbol, lots, price, _udef)
            return None
        if self._sdk is None:
            raise RuntimeError("SDK not initialized")
        from fubon_neo.sdk import Order
        from fubon_neo.constant import BSAction, MarketType, PriceType, TimeInForce, OrderType
        _ot_map = {"stock": OrderType.Stock, "margin": OrderType.Margin,
                   "daytrade": OrderType.DayTrade}
        ot = _ot_map.get(order_type_override, OrderType.Stock)
        try:
            o = Order(
                buy_sell=BSAction.Buy,
                symbol=symbol,
                quantity=lots * 1000,
                market_type=MarketType.Common,
                price_type=PriceType.Limit,
                time_in_force=TimeInForce.ROD,
                order_type=ot,
                price=str(price),
                user_def=_udef,
            )
            result = self._sdk.stock.place_order(self._account, o)
            order_no = self._extract_order_no(result)
            logger.info("BUY %s (%s) order_no=%s result: %s", symbol, order_type_override, order_no, result)
            return order_no
        except Exception as e:
            raise RuntimeError(f"下單失敗: {e}") from e

    def sell(self, symbol: str, lots: int, price: float, reason: str = "", user_def: str = "") -> Optional[str]:
        """賣出。price>0 → 限價ROD（可追價）；price<=0 → 市價IOC（強制出場）。返回 order_no。"""
        _udef = user_def or f"auto_sell_{symbol}"
        _market = (price <= 0)
        if not _market:
            price = round_up_tick(price)
        if self.dry_run:
            _mode = "市價IOC" if _market else f"限價ROD@{price:.2f}"
            logger.info("[DRY RUN] SELL %s x%d張 %s | 原因:%s user_def=%s", symbol, lots, _mode, reason, _udef)
            return None
        if self._sdk is None:
            raise RuntimeError("SDK not initialized")
        from fubon_neo.sdk import Order
        from fubon_neo.constant import BSAction, MarketType, PriceType, TimeInForce, OrderType
        if _market:
            order = Order(
                buy_sell=BSAction.Sell,
                symbol=symbol,
                quantity=lots * 1000,
                market_type=MarketType.Common,
                price_type=PriceType.Market,
                time_in_force=TimeInForce.IOC,
                order_type=OrderType.Stock,
                user_def=_udef,
            )
        else:
            order = Order(
                buy_sell=BSAction.Sell,
                symbol=symbol,
                quantity=lots * 1000,
                market_type=MarketType.Common,
                price_type=PriceType.Limit,
                time_in_force=TimeInForce.ROD,
                order_type=OrderType.Stock,
                price=str(price),
                user_def=_udef,
            )
        result = self._sdk.stock.place_order(self._account, order)
        order_no = self._extract_order_no(result)
        logger.info("SELL %s reason=%s order_no=%s result: %s", symbol, reason, order_no, result)
        return order_no

    def limit_sell(self, symbol: str, lots: int, price: float, user_def: str = ""):
        """限價現賣 ROD。"""
        price = round_up_tick(price)
        _udef = user_def or f"auto_lsell_{symbol}"
        if self.dry_run:
            logger.info("[DRY RUN] LIMIT SELL %s x%d張 @ %.2f user_def=%s", symbol, lots, price, _udef)
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
            price_type=PriceType.Limit,
            time_in_force=TimeInForce.ROD,
            order_type=OrderType.Stock,
            price=str(price),
            user_def=_udef,
        )
        try:
            result = self._sdk.stock.place_order(self._account, order)
            logger.info("LIMIT SELL %s result: %s", symbol, result)
        except Exception as e:
            raise RuntimeError(f"下單失敗: {e}") from e

    def place_conditional_stop(
        self,
        symbol: str,
        lots: int,
        stop_price: float,
        trade_date: str,
    ) -> Optional[str]:
        """停損觸價賣單：成交價 <= stop_price 時市價賣出。"""
        stop_price = round_up_tick(stop_price)  # 向上捨入 = 更早觸發，保護性更強
        if self.dry_run:
            logger.info("[DRY RUN] COND STOP %s x%d張 stop=%.2f", symbol, lots, stop_price)
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
                order_type=ConditionOrderType.Stock,  # 現賣
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
                logger.info("停損觸價單成功 %s stop=%.2f guid=%s", symbol, stop_price, guid)
                return str(guid)
            else:
                logger.error("停損觸價單失敗 %s: %s", symbol, result)
                return None
        except Exception as e:
            logger.error("停損觸價單例外 %s: %s", symbol, e)
            return None

    def place_conditional_take_profit(
        self,
        symbol: str,
        lots: int,
        trigger_price: float,
        trade_date: str,
    ) -> Optional[str]:
        """停利觸價賣單：成交價 >= trigger_price 時市價賣出。不多加 tick。"""
        trigger_price = round_down_tick(trigger_price)
        if self.dry_run:
            logger.info("[DRY RUN] COND TP %s x%d張 trigger=%.2f", symbol, lots, trigger_price)
            return None
        if self._sdk is None or self._account is None:
            logger.error("停利觸價單：SDK 或 account 未初始化")
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
                trigger_value=trigger_price,
                comparison=Operator.GreaterThanOrEqual,
            )
            order = ConditionOrder(
                buy_sell=BSAction.Sell,
                symbol=symbol,
                market_type=ConditionMarketType.Common,
                price_type=ConditionPriceType.Market,
                time_in_force=TimeInForce.ROD,
                order_type=ConditionOrderType.Stock,  # 現賣
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
                logger.info("停利觸價單成功 %s tp=%.2f guid=%s", symbol, trigger_price, guid)
                return str(guid)
            else:
                logger.error("停利觸價單失敗 %s: %s", symbol, result)
                return None
        except Exception as e:
            logger.error("停利觸價單例外 %s: %s", symbol, e)
            return None

    def cancel_conditional_order(self, guid: str):
        """取消觸價單（停損或停利）。"""
        if self.dry_run or not guid:
            return
        if self._sdk is None or self._account is None:
            return
        try:
            self._sdk.stock.cancel_condition_orders(account=self._account, guid=guid)
            logger.info("觸價單取消 guid=%s", guid)
        except Exception as e:
            logger.error("取消觸價單失敗 guid=%s: %s", guid, e)

    # 向後相容別名
    def cancel_conditional_stop(self, guid: str):
        self.cancel_conditional_order(guid)
