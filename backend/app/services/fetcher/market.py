import numpy as np
import yfinance as yf


def fetch_twii_bb_stats() -> tuple[float, float]:
    """
    計算大盤 ^TWII BB 位階資訊。
    回傳 (peak_bb_30d, current_bb)：
      peak_bb_30d — 近30日內 BB 位階最高值
      current_bb  — 當前 BB 位階
    RS 計算：market_bb_drop = peak_bb_30d - current_bb
    """
    df = yf.Ticker("^TWII").history(period="6mo", interval="1d")
    if df.empty or len(df) < 20:
        return 0.0, 0.0
    close = df["Close"].values
    ma20 = np.array([close[max(0, i - 19):i + 1].mean() for i in range(len(close))])
    std20 = np.array([
        max(close[max(0, i - 19):i + 1].std(ddof=0), 1e-8)
        for i in range(len(close))
    ])
    bb_pos = (close - ma20) / (2 * std20) * 10
    current_bb = float(bb_pos[-1])
    peak_bb_30d = float(bb_pos[-30:].max()) if len(bb_pos) >= 30 else float(bb_pos.max())
    return peak_bb_30d, current_bb
