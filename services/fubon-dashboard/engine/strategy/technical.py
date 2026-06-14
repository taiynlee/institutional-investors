import pandas as pd
import pandas_ta as ta


class TechnicalStrategy:
    """雙時間框架 (1min + 5min) 技術指標評分。"""

    def score(self, df_1m: pd.DataFrame, df_5m: pd.DataFrame) -> int:
        points = 0
        if self._ma_ok(df_1m) and self._ma_ok(df_5m):
            points += 1
        if self._rsi_ok(df_1m):
            points += 1
        if self._kd_cross(df_1m):
            points += 1
        if self._macd_cross(df_1m):
            points += 1
        if self._bb_breakout(df_1m):
            points += 1
        return points

    def _ma_ok(self, df: pd.DataFrame) -> bool:
        if len(df) < 20:
            return False
        ma5 = df["close"].rolling(5).mean().iloc[-1]
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        return float(ma5) > float(ma20)

    def _rsi_ok(self, df: pd.DataFrame) -> bool:
        if len(df) < 15:
            return False
        rsi = ta.rsi(df["close"], length=14)
        if rsi is None or rsi.empty:
            return False
        val = rsi.iloc[-1]
        return float(val) < 70

    def _kd_cross(self, df: pd.DataFrame) -> bool:
        if len(df) < 14:
            return False
        stoch = ta.stoch(df["high"], df["low"], df["close"])
        if stoch is None or stoch.empty:
            return False
        k = stoch.iloc[:, 0]
        d = stoch.iloc[:, 1]
        if len(k) < 2:
            return False
        return float(k.iloc[-2]) <= float(d.iloc[-2]) and float(k.iloc[-1]) > float(d.iloc[-1])

    def _macd_cross(self, df: pd.DataFrame) -> bool:
        if len(df) < 26:
            return False
        macd = ta.macd(df["close"])
        if macd is None or macd.empty:
            return False
        hist = macd.iloc[:, 2]
        if len(hist) < 2:
            return False
        return float(hist.iloc[-2]) < 0 and float(hist.iloc[-1]) >= 0

    def _bb_breakout(self, df: pd.DataFrame) -> bool:
        if len(df) < 20:
            return False
        bb = ta.bbands(df["close"], length=20)
        if bb is None or bb.empty:
            return False
        upper = bb.iloc[:, 2]
        price = df["close"].iloc[-1]
        upper_val = float(upper.iloc[-1])
        return float(price) > upper_val * 0.999 and float(price) <= upper_val * 1.02
