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


def fetch_sma_data(tickers: list[str], sma_days: int = 200) -> dict[str, dict]:
    """Compute the SMA and current price for each ticker.

    Returns {ticker: {"current_price": float, "sma": float, "pct_from_sma": float}}
    """
    if not tickers:
        return {}
    # Need enough history for the SMA window + some buffer
    df = yf.download(
        tickers=" ".join(tickers),
        period="1y",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    # Normalize single-ticker to MultiIndex
    if not isinstance(df.columns, pd.MultiIndex) and len(tickers) == 1:
        ticker = tickers[0]
        df.columns = pd.MultiIndex.from_tuples(
            [(ticker, col) for col in df.columns], names=["ticker", "price"]
        )

    results: dict[str, dict] = {}
    for ticker in tickers:
        try:
            close = df[(ticker, "Close")].dropna()
            if len(close) < sma_days:
                continue
            sma = float(close.rolling(window=sma_days).mean().iloc[-1])
            current_price = float(close.iloc[-1])
            pct_from_sma = (current_price - sma) / sma * 100
            results[ticker] = {
                "current_price": current_price,
                "sma": sma,
                "pct_from_sma": pct_from_sma,
            }
        except (KeyError, TypeError, IndexError):
            continue
    return results


def _safe_float(val) -> float | None:
    """Convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def fetch_etf_info(tickers: list[str]) -> dict[str, dict]:
    """Fetch ETF-specific data: expense ratio, AUM, holdings, sector weights."""
    results: dict[str, dict] = {}

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        try:
            t = yf.Ticker(ticker)
            info = t.info if isinstance(t.info, dict) else {}
            return ticker, {
                "expense_ratio": _safe_float(info.get("annualReportExpenseRatio")),
                "total_assets": _safe_float(info.get("totalAssets")),
                "holdings": info.get("holdings", []),
                "sector_weightings": info.get("sectorWeightings", []),
                "trailing_dividend_yield": _safe_float(info.get("trailingAnnualDividendYield")),
                "fund_family": info.get("fundFamily"),
                "long_name": info.get("longName"),
            }
        except Exception:
            return ticker, {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, data = future.result()
            results[ticker] = data

    return results


def fetch_etf_performance(tickers: list[str]) -> dict[str, dict[str, float]]:
    """Compute price returns over multiple periods for ETFs."""
    periods = [("1m", "1mo"), ("3m", "3mo"), ("6m", "6mo"),
               ("1y", "1y"), ("3y", "3y"), ("5y", "5y")]
    results: dict[str, dict[str, float]] = {t: {} for t in tickers}

    for label, yf_period in periods:
        try:
            df = yf.download(
                tickers=" ".join(tickers),
                period=yf_period,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if not isinstance(df.columns, pd.MultiIndex) and len(tickers) == 1:
                ticker = tickers[0]
                df.columns = pd.MultiIndex.from_tuples(
                    [(ticker, col) for col in df.columns], names=["ticker", "price"]
                )
            for ticker in tickers:
                try:
                    series = df[(ticker, "Close")].dropna()
                    if len(series) >= 2:
                        ret = (float(series.iloc[-1]) / float(series.iloc[0]) - 1) * 100
                        results[ticker][label] = ret
                except (KeyError, TypeError, IndexError):
                    pass
        except Exception:
            pass

    return results


def compute_holdings_overlap(etf_holdings: dict[str, list[dict]]) -> dict[str, list[str]]:
    """Find stocks held by 2+ ETFs.

    Args:
        etf_holdings: {etf_ticker: [holding dicts with 'symbol' key]}

    Returns:
        {stock_symbol: [etf_tickers_that_hold_it]}  — only symbols in 2+ ETFs
    """
    stock_to_etfs: dict[str, list[str]] = {}
    for etf_ticker, holdings in etf_holdings.items():
        for h in holdings:
            symbol = h.get("symbol", "").upper()
            if symbol:
                stock_to_etfs.setdefault(symbol, []).append(etf_ticker)
    return {sym: etfs for sym, etfs in stock_to_etfs.items() if len(etfs) >= 2}


def fetch_portfolio_etf_holdings(
    etf_tickers: list[str],
) -> dict[str, list[dict]]:
    """Fetch top holdings for ETFs in the portfolio.

    Uses funds_data.top_holdings (DataFrame with Symbol index, 'Holding Percent' column).
    Returns {etf_ticker: [{"symbol": str, "holdingName": str, "holdingPercent": float}, ...]}
    """
    results: dict[str, list[dict]] = {}

    def _fetch_one(ticker: str) -> tuple[str, list[dict]]:
        try:
            t = yf.Ticker(ticker)
            fd = t.funds_data
            th = fd.top_holdings
            if th is None or th.empty:
                return ticker, []
            holdings = []
            for symbol, row in th.iterrows():
                holdings.append({
                    "symbol": str(symbol),
                    "holdingName": row.get("Name", ""),
                    "holdingPercent": float(row.get("Holding Percent", 0)),
                })
            return ticker, holdings
        except Exception:
            return ticker, []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in etf_tickers}
        for future in as_completed(futures):
            ticker, holdings = future.result()
            results[ticker] = holdings

    return results


def fetch_vix() -> dict:
    """Fetch the current VIX level and 1-day change.

    Returns {"current": float, "change_1d": float} or empty dict on failure.
    """
    from .config import VIX_TICKER

    try:
        df = yf.download(VIX_TICKER, period="5d", progress=False)
        if df.empty:
            return {}
        # yf.download may return MultiIndex columns; flatten to get Close
        if isinstance(df.columns, pd.MultiIndex):
            close = df[("Close", VIX_TICKER)].dropna()
        else:
            close = df["Close"].dropna()
        if len(close) < 1:
            return {}
        current = float(close.iloc[-1])
        change_1d = float(close.iloc[-1] - close.iloc[-2]) if len(close) >= 2 else 0.0
        return {"current": current, "change_1d": change_1d}
    except Exception:
        return {}


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
