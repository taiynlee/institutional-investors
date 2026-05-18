"""
yfinance 批次抓台股歷史 OHLCV
TWSE: code + ".TW"  (e.g. 2330.TW)
TPEx: code + ".TWO" (e.g. 3008.TWO)
"""
import pandas as pd
import yfinance as yf
from datetime import date, timedelta

_BATCH_SIZE = 100
_SUFFIX = {"TWSE": ".TW", "TPEx": ".TWO"}


async def fetch_prices_yf(
    stocks: list[tuple[str, str]],  # [(code, market), ...]
    days: int = 95,
) -> list[dict]:
    """Bulk-fetch OHLCV; stocks is list of (code, market) tuples."""
    if not stocks:
        return []

    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows: list[dict] = []

    for i in range(0, len(stocks), _BATCH_SIZE):
        batch = stocks[i : i + _BATCH_SIZE]
        tickers = [f"{c}{_SUFFIX.get(m, '.TW')}" for c, m in batch]
        try:
            df = yf.download(
                tickers,
                start=start,
                auto_adjust=True,
                progress=False,
            )
        except Exception as e:
            print(f"  yf batch {i // _BATCH_SIZE + 1} 失敗: {e}")
            continue

        if df.empty:
            continue

        multi = isinstance(df.columns, pd.MultiIndex)

        for (code, _), ticker in zip(batch, tickers):
            try:
                sub = df.xs(ticker, axis=1, level=1) if multi else df
                for ts, row in sub.iterrows():
                    close = row.get("Close")
                    if pd.isna(close):
                        continue
                    td = ts.date() if hasattr(ts, "date") else pd.Timestamp(ts).date()
                    rows.append({
                        "code": code,
                        "trade_date": td,
                        "open": float(row["Open"]) if not pd.isna(row.get("Open", float("nan"))) else float(close),
                        "high": float(row["High"]) if not pd.isna(row.get("High", float("nan"))) else float(close),
                        "low": float(row["Low"]) if not pd.isna(row.get("Low", float("nan"))) else float(close),
                        "close": float(close),
                        "volume": int(row["Volume"]) if not pd.isna(row.get("Volume", float("nan"))) else 0,
                    })
            except Exception:
                continue

    return rows
