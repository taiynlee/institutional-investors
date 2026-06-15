import pandas as pd
from datetime import datetime
from typing import Optional

from engine.utils.tz import now_tw
from engine.strategy.bar_builder import Bar, BarBuilder
from engine.strategy.volume_price import VolumePriceStrategy
from engine.strategy.technical import TechnicalStrategy
from engine.strategy.signal_combiner import SignalCombiner, SignalResult


class SymbolSession:
    def __init__(
        self,
        symbol: str,
        reference_price: float,
        limitup_price: float,
        atr: float,
        orb_window_minutes: int = 15,  # 保留參數避免舊呼叫報錯，已不使用
    ):
        self.symbol = symbol
        self.reference_price = reference_price
        self.limitup_price = limitup_price
        self.atr = atr

        self.bar_builder = BarBuilder()

        self._df_1min: list[dict] = []
        self._df_5min: list[dict] = []

        self.bar_builder.on_1min_close = self._on_1min_close
        self.bar_builder.on_5min_close = self._on_5min_close

        self.last_bids: list[dict] = []
        self.last_asks: list[dict] = []
        self.prev_1min_volume: int = 0
        self.prev_1min_close: float = reference_price
        self.curr_price: float = reference_price

    def on_tick(self, price: float, size: int, ts_ns: int):
        self.curr_price = price
        dt = now_tw()
        self.bar_builder.on_tick({"price": price, "volume": size, "time": dt})

    def on_quote(self, bids: list[dict], asks: list[dict]):
        self.last_bids = bids
        self.last_asks = asks

    def _on_1min_close(self, bar: Bar):
        self._df_1min.append({
            "open": bar.open, "high": bar.high,
            "low": bar.low, "close": bar.close, "volume": bar.volume,
        })
        self.prev_1min_volume = bar.volume
        self.prev_1min_close = bar.close

    def _on_5min_close(self, bar: Bar):
        self._df_5min.append({
            "open": bar.open, "high": bar.high,
            "low": bar.low, "close": bar.close, "volume": bar.volume,
        })

    @property
    def change_pct(self) -> float:
        return (self.curr_price - self.reference_price) / self.reference_price * 100

    @property
    def limit_up_pct_away(self) -> float:
        if self.curr_price <= 0:
            return 10.0
        return (self.limitup_price - self.curr_price) / self.curr_price * 100

    @property
    def bid_ratio(self) -> float:
        bid_total = sum(
            b.get("size", 0) if isinstance(b, dict) else (b[1] if len(b) > 1 else 1)
            for b in self.last_bids
        )
        ask_total = sum(
            a.get("size", 0) if isinstance(a, dict) else (a[1] if len(a) > 1 else 1)
            for a in self.last_asks
        )
        total = bid_total + ask_total
        return bid_total / total if total > 0 else 0.0

    def _avg_1min_volume(self, lookback: int = 10) -> float:
        recent = self._df_1min[-lookback:] if self._df_1min else []
        if recent:
            return sum(b["volume"] for b in recent) / len(recent)
        return float(self.prev_1min_volume or 1)

    def volume_price_score(self, vp: VolumePriceStrategy) -> int:
        bid_total = sum(b.get("size", 0) if isinstance(b, dict) else (b[1] if len(b) > 1 else 1) for b in self.last_bids)
        ask_total = sum(a.get("size", 0) if isinstance(a, dict) else (a[1] if len(a) > 1 else 1) for a in self.last_asks)
        curr_vol = self.bar_builder.current_1min.volume if self.bar_builder.current_1min else 0
        return vp.score(
            bid_total=bid_total,
            ask_total=ask_total,
            curr_volume=curr_vol,
            avg_volume=self._avg_1min_volume(),
            curr_close=self.curr_price,
            prev_close=self.prev_1min_close,
        )

    def technical_score(self, tech: TechnicalStrategy) -> int:
        df1 = pd.DataFrame(self._df_1min)
        df5 = pd.DataFrame(self._df_5min)
        if df1.empty or len(df1) < 5:
            return 0
        return tech.score(df1, df5 if not df5.empty else df1)

    def evaluate_theoretical(
        self,
        combiner: SignalCombiner,
        vp: VolumePriceStrategy,
        tech: TechnicalStrategy,
        current_time,
        futures_signal=None,
        entry_cutoff_mins: int = 13 * 60 + 10,
        market_ok: bool = True,
        orb_volume_multiplier: float = 1.5,  # 保留參數相容性，已不使用
    ) -> SignalResult:
        current_mins = current_time.hour * 60 + current_time.minute
        time_ok = (
            current_mins >= 9 * 60 + 15 and
            current_mins < entry_cutoff_mins
        )
        return combiner.evaluate(
            symbol=self.symbol,
            current_price=self.curr_price,
            time_ok=time_ok,
            market_ok=market_ok,
            not_in_position=True,
            no_order_lock=True,
            positions_count=0,
            max_positions=999,
            limit_up_pct_away=self.limit_up_pct_away,
            volume_price_score=self.volume_price_score(vp),
            technical_score=self.technical_score(tech),
            chips_score=0,
            change_pct=self.change_pct,
            futures_signal=futures_signal,
        )

    def evaluate(
        self,
        combiner: SignalCombiner,
        vp: VolumePriceStrategy,
        tech: TechnicalStrategy,
        current_time,
        positions_count: int,
        max_positions: int,
        not_in_position: bool,
        futures_signal=None,
        entry_cutoff_mins: int = 13 * 60 + 10,
        market_ok: bool = True,
        orb_volume_multiplier: float = 1.5,  # 保留參數相容性，已不使用
    ) -> SignalResult:
        current_mins = current_time.hour * 60 + current_time.minute
        time_ok = (
            current_mins >= 9 * 60 + 15 and
            current_mins < entry_cutoff_mins
        )
        return combiner.evaluate(
            symbol=self.symbol,
            current_price=self.curr_price,
            time_ok=time_ok,
            market_ok=market_ok,
            not_in_position=not_in_position,
            no_order_lock=True,
            positions_count=positions_count,
            max_positions=max_positions,
            limit_up_pct_away=self.limit_up_pct_away,
            volume_price_score=self.volume_price_score(vp),
            technical_score=self.technical_score(tech),
            chips_score=0,
            change_pct=self.change_pct,
            futures_signal=futures_signal,
        )
