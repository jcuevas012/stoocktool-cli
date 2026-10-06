from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

from .config import MARGIN_STATE_FILE, LEAPS_EARNINGS_HISTORY_QUARTERS, ensure_config_dir


def get_used_margin() -> float:
    """Return the currently recorded used margin amount (default 0)."""
    if MARGIN_STATE_FILE.exists():
        try:
            return float(json.loads(MARGIN_STATE_FILE.read_text()).get("used_margin", 0.0))
        except Exception:
            pass
    return 0.0


def set_used_margin(amount: float) -> None:
    """Persist the used margin amount to disk."""
    ensure_config_dir()
    MARGIN_STATE_FILE.write_text(json.dumps({"used_margin": amount}))


def fetch_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch .info for each ticker in parallel (max 5 workers)."""
    results: dict[str, dict] = {}

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        try:
            info = yf.Ticker(ticker).info
            return ticker, info if isinstance(info, dict) else {}
        except Exception as exc:
            return ticker, {"_data_fetch_error": type(exc).__name__}

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


def fetch_cashflow_basics(tickers: list[str]) -> dict[str, dict]:
    """Fetch latest-year depreciation and capex from cashflow statement for DCF valuation."""
    results: dict[str, dict] = {}

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        out: dict = {}
        try:
            t = yf.Ticker(ticker)
            cf = t.cashflow
            if cf is None or cf.empty:
                return ticker, out
            col = cf.columns[0]  # most recent year

            def _get(*keys):
                for key in keys:
                    if key in cf.index and pd.notna(cf.loc[key, col]):
                        return float(cf.loc[key, col])
                return None

            dep = _get("Depreciation Amortization Depletion", "Depreciation And Amortization")
            capex = _get("Capital Expenditure")
            if dep is not None:
                out["depreciation"] = dep
            if capex is not None:
                out["capex"] = capex  # negative in yfinance
        except Exception:
            pass
        return ticker, out

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, out = future.result()
            results[ticker] = out

    return results


def fetch_earnings_history(tickers: list[str]) -> dict[str, dict]:
    """Fetch quarterly and annual Revenue/Net Income for earnings-trend analysis.

    Returns {ticker: {"quarters": [{"period": str, "revenue": float, "net_income": float}, ...],
                       "years": [{"period": str, "revenue": float, "net_income": float}, ...]}}
    Both lists are newest-first, matching yfinance's column order. Columns with a
    missing revenue or net income (e.g. yfinance's stale oldest annual column) are dropped.
    """
    results: dict[str, dict] = {}

    def _get(frame, col, *keys):
        for key in keys:
            if key in frame.index and pd.notna(frame.loc[key, col]):
                return float(frame.loc[key, col])
        return None

    def _extract(frame) -> list[dict]:
        periods: list[dict] = []
        if frame is None or frame.empty:
            return periods
        for col in frame.columns:
            revenue = _get(frame, col, "Total Revenue", "Operating Revenue")
            net_income = _get(frame, col, "Net Income", "Net Income Common Stockholders",
                               "Net Income From Continuing Operations")
            if revenue is None or net_income is None:
                continue
            label = str(col.date()) if hasattr(col, "date") else str(col)
            periods.append({"period": label, "revenue": revenue, "net_income": net_income})
        return periods

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        try:
            t = yf.Ticker(ticker)
            return ticker, {
                "quarters": _extract(t.quarterly_income_stmt),
                "years": _extract(t.income_stmt),
            }
        except Exception:
            return ticker, {}

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

            # annualReportExpenseRatio is no longer populated by yfinance for most
            # ETFs; netExpenseRatio is the current field but returned as a
            # "decimal percentage" (0.03 = 0.03%) rather than a fraction — normalize
            # to a true fraction so this stays consistent with the old field's unit.
            net_er = _safe_float(info.get("netExpenseRatio"))
            expense_ratio = net_er / 100 if net_er is not None else _safe_float(info.get("annualReportExpenseRatio"))

            # trailingAnnualDividendYield is similarly stale; dividendYield (also a
            # "decimal percentage") and yield (a true fraction) are the working
            # fallbacks — normalize both to a true fraction.
            div_yield = _safe_float(info.get("dividendYield"))
            if div_yield is not None:
                trailing_dividend_yield = div_yield / 100
            else:
                trailing_dividend_yield = _safe_float(info.get("yield"))
                if trailing_dividend_yield is None:
                    trailing_dividend_yield = _safe_float(info.get("trailingAnnualDividendYield"))

            return ticker, {
                "expense_ratio": expense_ratio,
                "total_assets": _safe_float(info.get("totalAssets")),
                "holdings": info.get("holdings", []),
                "sector_weightings": info.get("sectorWeightings", []),
                "trailing_dividend_yield": trailing_dividend_yield,
                "fund_family": info.get("fundFamily"),
                "long_name": info.get("longName"),
                "trailing_pe": _safe_float(info.get("trailingPE")),
                "forward_pe": _safe_float(info.get("forwardPE")),
                "category": info.get("category"),
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


def fetch_holding_fundamentals(symbols: list[str]) -> dict[str, dict]:
    """Fetch trailing/forward PE and earnings growth for ETF top-holding stocks.

    Used to build a weighted basket PE/growth for ETF valuation when the ETF's
    own .info doesn't populate trailingPE/forwardPE directly.
    Returns {symbol: {"trailing_pe": float|None, "forward_pe": float|None,
                       "earnings_growth": float|None}}
    """
    results: dict[str, dict] = {}
    if not symbols:
        return results

    def _fetch_one(symbol: str) -> tuple[str, dict]:
        try:
            info = yf.Ticker(symbol).info
            info = info if isinstance(info, dict) else {}
            return symbol, {
                "trailing_pe": _safe_float(info.get("trailingPE")),
                "forward_pe": _safe_float(info.get("forwardPE")),
                "earnings_growth": _safe_float(info.get("earningsGrowth")),
            }
        except Exception:
            return symbol, {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, s): s for s in symbols}
        for future in as_completed(futures):
            symbol, info = future.result()
            results[symbol] = info

    return results


def fetch_etf_technicals(tickers: list[str]) -> dict[str, dict]:
    """Compute EMA-50, SMA-200, 52-week high/low, and 5-year average price.

    Single yf.download(period="5y") call per batch, reused both for the
    technicals (tail of the series) and for the 5y-average-price proxy used
    as a fallback for historical average P/E when FMP is unavailable.

    Returns {ticker: {"current_price": float|None, "ema_50": float|None,
                       "sma_200": float|None, "week_52_high": float|None,
                       "week_52_low": float|None, "avg_price_5y": float|None}}
    """
    results: dict[str, dict] = {}
    if not tickers:
        return results

    df = yf.download(
        tickers=" ".join(tickers),
        period="5y",
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
            close = df[(ticker, "Close")].dropna()
            if close.empty:
                continue
            current_price = float(close.iloc[-1])
            ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1]) if len(close) >= 50 else None
            sma_200 = float(close.rolling(window=200).mean().iloc[-1]) if len(close) >= 200 else None
            recent = close.tail(252)
            results[ticker] = {
                "current_price": current_price,
                "ema_50": ema_50,
                "sma_200": sma_200,
                "week_52_high": float(recent.max()),
                "week_52_low": float(recent.min()),
                "avg_price_5y": float(close.mean()),
            }
        except (KeyError, TypeError, IndexError):
            continue

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


def fetch_owner_earnings(tickers: list[str]) -> dict[str, dict]:
    """Fetch cash flow statement data needed for Owner Earnings calculation.

    Returns {ticker: {
        "net_income": float, "depreciation": float, "capex": float (negative),
        "working_capital_change": float,
        "market_cap": float, "current_price": float,
        "years": [{same fields per year}, ...],  # multi-year for trend
    }}
    """
    results: dict[str, dict] = {}

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        try:
            t = yf.Ticker(ticker)
            info = t.info if isinstance(t.info, dict) else {}
            cf = t.cashflow

            if cf is None or cf.empty:
                return ticker, {}

            # Helper to find a value by trying multiple index keys
            def _get_cf(frame, *keys):
                for key in keys:
                    if key in frame.index:
                        val = frame.loc[key]
                        if pd.notna(val.iloc[0]) if not isinstance(val.iloc[0], str) else False:
                            return val
                return None

            # Build per-year data (columns are fiscal year dates, newest first)
            years = []
            for col in cf.columns:
                year_label = str(col.year) if hasattr(col, "year") else str(col)
                ni_row = _get_cf(cf, "Net Income From Continuing Operations", "Net Income")
                dep_row = _get_cf(cf, "Depreciation Amortization Depletion", "Depreciation And Amortization")
                capex_row = _get_cf(cf, "Capital Expenditure")
                wc_row = _get_cf(cf, "Change In Working Capital")

                ni = float(ni_row[col]) if ni_row is not None and pd.notna(ni_row[col]) else None
                dep = float(dep_row[col]) if dep_row is not None and pd.notna(dep_row[col]) else None
                capex = float(capex_row[col]) if capex_row is not None and pd.notna(capex_row[col]) else None
                wc = float(wc_row[col]) if wc_row is not None and pd.notna(wc_row[col]) else None

                if ni is not None and dep is not None and capex is not None:
                    # capex is already negative in yfinance
                    # wc change: negative = cash consumed, positive = cash released
                    wc_val = wc if wc is not None else 0
                    owner_earnings = ni + dep + capex - wc_val
                    years.append({
                        "year": year_label,
                        "net_income": ni,
                        "depreciation": dep,
                        "capex": capex,
                        "working_capital_change": wc_val,
                        "owner_earnings": owner_earnings,
                    })

            if not years:
                return ticker, {}

            latest = years[0]
            return ticker, {
                **latest,
                "market_cap": _safe_float(info.get("marketCap")),
                "current_price": _safe_float(info.get("currentPrice")),
                "shares_outstanding": _safe_float(info.get("sharesOutstanding")),
                "sector": info.get("sector"),
                "years": years,
            }
        except Exception:
            return ticker, {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, data = future.result()
            results[ticker] = data

    return results


def fetch_put_candidates(
    tickers: list[str], min_dte: int = 30, max_dte: int = 45
) -> dict[str, dict]:
    """Fetch OTM put options in the target DTE range for each ticker.

    Returns {ticker: {"current_price", "beta", "expiration", "dte", "puts": [...]}}
    Each put entry: {"strike", "bid", "ask", "volume", "open_interest", "implied_volatility"}
    """
    from datetime import datetime, date

    results: dict[str, dict] = {}

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        try:
            t = yf.Ticker(ticker)
            info = t.info if isinstance(t.info, dict) else {}
            current_price = _safe_float(info.get("currentPrice")) or _safe_float(
                info.get("regularMarketPrice")
            )
            beta = _safe_float(info.get("beta"))

            expirations = t.options  # tuple of date strings
            if not expirations:
                return ticker, {}

            today = date.today()

            # Find expiration closest to target DTE range
            best_exp: str | None = None
            best_dte: int | None = None
            # First pass: look within range
            for exp_str in expirations:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - today).days
                if min_dte <= dte <= max_dte:
                    if best_dte is None or dte < best_dte:
                        best_exp = exp_str
                        best_dte = dte
            # Fallback: nearest expiration beyond min_dte
            if best_exp is None:
                for exp_str in expirations:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                    dte = (exp_date - today).days
                    if dte >= min_dte:
                        if best_dte is None or dte < best_dte:
                            best_exp = exp_str
                            best_dte = dte

            if best_exp is None or current_price is None:
                return ticker, {"current_price": current_price, "beta": beta}

            chain = t.option_chain(best_exp)
            puts_df = chain.puts

            # Filter OTM puts (strike < current_price)
            otm = puts_df[puts_df["strike"] < current_price].copy()

            candidates = []
            for _, row in otm.iterrows():
                bid = float(row.get("bid", 0)) if pd.notna(row.get("bid")) else 0
                if bid <= 0:
                    continue  # skip puts with no bid
                candidates.append({
                    "strike": float(row["strike"]),
                    "bid": bid,
                    "ask": float(row.get("ask", 0)) if pd.notna(row.get("ask")) else 0,
                    "volume": int(row["volume"]) if pd.notna(row.get("volume")) else 0,
                    "open_interest": int(row["openInterest"]) if pd.notna(row.get("openInterest")) else 0,
                    "implied_volatility": float(row["impliedVolatility"]) if pd.notna(row.get("impliedVolatility")) else 0,
                })

            return ticker, {
                "current_price": current_price,
                "beta": beta,
                "expiration": best_exp,
                "dte": best_dte,
                "puts": candidates,
            }
        except Exception:
            return ticker, {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, data = future.result()
            results[ticker] = data

    return results


def fetch_current_iv(ticker: str, option_type: str, strike: float, expiration: str) -> Optional[float]:
    """Best-effort fetch of the current market-quoted IV (%) for an already-open LEAPS contract,
    reusing the same `option_chain` lookup as `fetch_leaps_option_context`'s Step 4b contract
    check. Unlike delta/theta, IV is a field yfinance's option chain actually exposes per
    contract, so `leaps update` can refresh it from Yahoo instead of relying on manual entry
    alone. Returns None on any failure (missing contract, network error, etc.) — never raises.
    """
    try:
        t = yf.Ticker(ticker)
        chain = t.option_chain(expiration)
        contracts_df = chain.calls if option_type == "CALL" else chain.puts
        row = contracts_df[contracts_df["strike"] == strike]
        if row.empty:
            return None
        iv = _safe_float(row.iloc[0].get("impliedVolatility"))
        return iv * 100 if iv is not None else None  # fraction -> percent
    except Exception:
        return None


def fetch_leaps_option_quote(ticker: str, option_type: str, strike: float, expiration: str) -> dict:
    """Fetch one LEAPS contract's two-sided quote, IV, and last-trade timestamp.

    A midpoint is returned as the indicative mark only for a positive, non-crossed
    bid/ask. It is not an executable fill price. Missing/stale last-trade data is
    exposed separately and never substituted for a current two-sided mark.
    """
    from datetime import datetime

    result = {"retrieved_at": datetime.now().astimezone().isoformat(timespec="minutes")}
    try:
        ticker_obj = yf.Ticker(ticker)
        chain = ticker_obj.option_chain(expiration)
        contracts = chain.calls if option_type == "CALL" else chain.puts
        match = contracts[contracts["strike"] == strike]
        if match.empty:
            return result
        row = match.iloc[0]
        bid = _safe_float(row.get("bid"))
        ask = _safe_float(row.get("ask"))
        iv = _safe_float(row.get("impliedVolatility"))
        last_trade = row.get("lastTradeDate")
        if bid is not None:
            result["bid"] = bid
        if ask is not None:
            result["ask"] = ask
        if bid is not None and ask is not None and 0 < bid <= ask:
            result["mid"] = round((bid + ask) / 2, 4)
            result["spread_pct"] = ((ask - bid) / ((ask + bid) / 2) * 100) if ask + bid else None
        if iv is not None:
            result["implied_volatility"] = iv * 100
        if last_trade is not None and hasattr(last_trade, "isoformat"):
            result["last_trade_at"] = last_trade.isoformat()
    except Exception:
        pass
    return result


def fetch_leaps_gamma_inputs(ticker: str) -> dict:
    """Fetch disclosed Black–Scholes rate and dividend-yield inputs for LEAPS gamma.

    Yahoo's ^TNX close is used as a 10-year Treasury yield proxy. Yahoo's dividendYield
    uses this project's documented percentage-point convention (0.39 means 0.39%);
    the alternate `yield` and trailingAnnualDividendYield fields are fractions.
    Missing inputs remain missing so callers can explain why the model is unavailable.
    """
    from datetime import datetime

    result: dict = {"retrieved_at": datetime.now().astimezone().isoformat(timespec="minutes")}
    try:
        ticker_obj = yf.Ticker(ticker)
    except Exception:
        ticker_obj = None
    try:
        history = ticker_obj.history(period="5d") if ticker_obj is not None else None
        if history is not None and not history.empty and "Close" in history:
            closes = history["Close"].dropna()
            if not closes.empty:
                spot = _safe_float(closes.iloc[-1])
                if spot is not None and spot > 0:
                    result["stock_price"] = spot
                    result["stock_price_as_of"] = closes.index[-1].date().isoformat()
    except Exception:
        pass

    try:
        info = ticker_obj.info if ticker_obj is not None else None
        if isinstance(info, dict):
            dividend_yield = _safe_float(info.get("dividendYield"))
            if dividend_yield is not None and 0 <= dividend_yield <= 100:
                result["dividend_yield_pct"] = dividend_yield
                result["dividend_source"] = "Yahoo dividendYield"
            else:
                for key in ("yield", "trailingAnnualDividendYield"):
                    fraction = _safe_float(info.get(key))
                    if fraction is not None and 0 <= fraction <= 1:
                        result["dividend_yield_pct"] = fraction * 100
                        result["dividend_source"] = f"Yahoo {key} (fraction converted to percent)"
                        break
                if "dividend_yield_pct" not in result and _safe_float(info.get("dividendRate")) == 0:
                    result["dividend_yield_pct"] = 0.0
                    result["dividend_source"] = "Yahoo dividendRate confirms no dividend"
    except Exception:
        pass

    try:
        history = yf.Ticker("^TNX").history(period="5d")
        if history is not None and not history.empty and "Close" in history:
            closes = history["Close"].dropna()
            if not closes.empty:
                rate = _safe_float(closes.iloc[-1])
                if rate is not None and -5 <= rate <= 25:
                    result["risk_free_rate_pct"] = rate
                    result["risk_free_source"] = "Yahoo ^TNX 10-year Treasury yield"
                    result["risk_free_as_of"] = closes.index[-1].date().isoformat()
    except Exception:
        pass
    return result


def fetch_realized_volatility(ticker: str, period: str = "1y") -> Optional[float]:
    """Best-effort annualized realized (historical) volatility (%) from daily log returns.

    Used as a free-data proxy for "average IV" — yfinance has no historical-implied-volatility
    series, so actual realized price movement stands in for it when judging whether a LEAPS
    contract's current market IV looks cheap or expensive. Returns None on any failure.
    """
    try:
        import numpy as np

        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty or len(hist) <= 5:
            return None
        log_returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
        return float(log_returns.std() * (252 ** 0.5)) * 100  # fraction -> percent
    except Exception:
        return None


def fetch_next_earnings_date(ticker: str) -> dict:
    """Best-effort next earnings date lookup — standalone so `leaps show`/`leaps update` can
    use it too, not just `leaps add`'s fetch_leaps_option_context`. Never raises.

    Returns a dict with "earnings_date" (ISO) and "days_to_earnings" (int) when found, {}
    otherwise.
    """
    from datetime import date, datetime

    result: dict = {}
    try:
        t = yf.Ticker(ticker)
        earnings_date = None
        cal = t.calendar
        if isinstance(cal, dict) and cal.get("Earnings Date"):
            earnings_date = cal["Earnings Date"][0]
        if earnings_date is None:
            edf = t.get_earnings_dates(limit=4)
            if edf is not None and not edf.empty:
                future = edf[edf.index.date >= date.today()]
                if not future.empty:
                    earnings_date = future.index[-1].date()
        if earnings_date is not None:
            if isinstance(earnings_date, datetime):
                earnings_date = earnings_date.date()
            result["earnings_date"] = earnings_date.isoformat()
            result["days_to_earnings"] = (earnings_date - date.today()).days
    except Exception:
        pass
    return result


def fetch_earnings_move_history(ticker: str, quarters: int = LEAPS_EARNINGS_HISTORY_QUARTERS) -> list[dict]:
    """Best-effort historical price move bracketing each of the last `quarters` earnings
    reports: the close on the last trading day strictly before the earnings date, versus the
    close on the first trading day on/after it (this is the closest honest bracket available —
    yfinance's earnings-date timestamps don't reliably say before-market vs. after-market).

    Returns a list of {"date": iso, "pct_move": signed %, "abs_pct_move": %}, newest last.
    Never raises — returns [] on any failure (missing data, network error, too-short history).
    """
    from datetime import date

    try:
        t = yf.Ticker(ticker)
        edf = t.get_earnings_dates(limit=quarters + 4)
        if edf is None or edf.empty:
            return []
        past_dates = sorted(d.date() for d in edf.index if d.date() < date.today())
        past_dates = past_dates[-quarters:]
        if not past_dates:
            return []

        hist = t.history(period="3y")
        if hist.empty or "Close" not in hist:
            return []
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return []
        trading_days = [ts.date() for ts in closes.index]

        results = []
        for earnings_date in past_dates:
            prior_idx = None
            for i, d in enumerate(trading_days):
                if d < earnings_date:
                    prior_idx = i
                else:
                    break
            if prior_idx is None or prior_idx + 1 >= len(trading_days):
                continue
            prior_close = float(closes.iloc[prior_idx])
            next_close = float(closes.iloc[prior_idx + 1])
            if prior_close <= 0:
                continue
            pct_move = (next_close - prior_close) / prior_close * 100
            results.append({
                "date": earnings_date.isoformat(),
                "pct_move": pct_move,
                "abs_pct_move": abs(pct_move),
            })
        return results
    except Exception:
        return []


def fetch_leaps_option_context(
    ticker: str, option_type: str, strike: float, expiration: str
) -> dict:
    """Best-effort market context for the `leaps add` wizard: the chosen contract's
    bid/ask/IV, the next earnings date, and 1-year realized volatility.

    Returns a dict with any subset of {"bid", "ask", "mid", "implied_volatility",
    "earnings_date", "days_to_earnings", "realized_volatility"} — missing keys mean
    that piece could not be fetched. Never raises; this is supplementary context for
    a manual-entry wizard, not a hard data requirement.
    """
    from datetime import datetime

    result: dict = {}
    t = yf.Ticker(ticker)
    result["quote_retrieved_at"] = datetime.now().astimezone().isoformat(timespec="minutes")

    # Contract bid/ask/IV for the exact strike + expiration the user already chose.
    try:
        chain = t.option_chain(expiration)
        contracts_df = chain.calls if option_type == "CALL" else chain.puts
        row = contracts_df[contracts_df["strike"] == strike]
        if not row.empty:
            row = row.iloc[0]
            bid = _safe_float(row.get("bid"))
            ask = _safe_float(row.get("ask"))
            if bid is not None:
                result["bid"] = bid
            if ask is not None:
                result["ask"] = ask
            if bid is not None and ask is not None and 0 < bid <= ask:
                result["mid"] = round((bid + ask) / 2, 2)
                midpoint = (bid + ask) / 2
                result["spread_pct"] = (ask - bid) / midpoint * 100 if midpoint else None
            iv = _safe_float(row.get("impliedVolatility"))
            if iv is not None:
                result["implied_volatility"] = iv * 100  # fraction -> percent
    except Exception:
        pass

    # Next earnings date.
    result.update(fetch_next_earnings_date(ticker))

    # 1-year realized (historical) volatility — proxy for "average IV".
    realized_vol = fetch_realized_volatility(ticker, period="1y")
    if realized_vol is not None:
        result["realized_volatility"] = realized_vol

    return result


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
    if days <= 365 * 3:
        return "3y"
    return "5y"
