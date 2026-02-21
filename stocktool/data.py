from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf


def fetch_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch .info for each ticker in parallel (max 5 workers)."""
    results: dict[str, dict] = {}

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        try:
            info = yf.Ticker(ticker).info
            return ticker, info if isinstance(info, dict) else {}
        except Exception:
            return ticker, {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, info = future.result()
            results[ticker] = info

    return results


def fetch_price_history(tickers: list[str], horizon_days: int) -> pd.DataFrame:
    """Batch-fetch OHLCV history for all tickers in one HTTP call.

    Always uses group_by='ticker' to produce a consistent MultiIndex DataFrame
    regardless of whether one or many tickers are requested.
    """
    period = _days_to_period(horizon_days)
    df = yf.download(
        tickers=" ".join(tickers),
        period=period,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    # When a single ticker is downloaded with group_by='ticker', yfinance may
    # return a flat DataFrame instead of a MultiIndex. Normalize it.
    if isinstance(df.columns, pd.MultiIndex):
        return df
    # Single ticker — wrap in MultiIndex
    if len(tickers) == 1:
        ticker = tickers[0]
        df.columns = pd.MultiIndex.from_tuples(
            [(ticker, col) for col in df.columns], names=["ticker", "price"]
        )
    return df


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """Return the most recent closing price for each ticker."""
    if not tickers:
        return {}
    df = fetch_price_history(tickers, horizon_days=5)
    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            close_col = (ticker, "Close")
            series = df[close_col].dropna()
            if not series.empty:
                prices[ticker] = float(series.iloc[-1])
        except (KeyError, TypeError):
            pass
    return prices


def fetch_balance_sheets(tickers: list[str]) -> dict[str, dict]:
    """Fetch total assets from annual balance sheet for each ticker in parallel."""
    results: dict[str, dict] = {}

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        out: dict = {}
        try:
            t = yf.Ticker(ticker)
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                for key in ("Total Assets", "TotalAssets", "totalAssets"):
                    if key in bs.index:
                        val = bs.loc[key].iloc[0]
                        if pd.notna(val):
                            out["totalAssets"] = float(val)
                        break
        except Exception:
            pass
        return ticker, out

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, out = future.result()
            results[ticker] = out

    return results


def fetch_revenue_estimates(tickers: list[str]) -> dict[str, float | None]:
    """Fetch next-year analyst revenue estimates for each ticker in parallel."""
    results: dict[str, float | None] = {}

    def _fetch_one(ticker: str) -> tuple[str, float | None]:
        try:
            t = yf.Ticker(ticker)
            rev_est = t.revenue_estimate
            if rev_est is not None and not rev_est.empty and "+1y" in rev_est.index:
                val = rev_est.loc["+1y", "avg"]
                if pd.notna(val):
                    return ticker, float(val)
        except Exception:
            pass
        return ticker, None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, val = future.result()
            results[ticker] = val

    return results


def _days_to_period(days: int) -> str:
    if days <= 5:
        return "5d"
    if days <= 30:
        return "1mo"
    if days <= 60:
        return "3mo"
    if days <= 90:
        return "3mo"
    if days <= 180:
        return "6mo"
    if days <= 365:
        return "1y"
    return "2y"
