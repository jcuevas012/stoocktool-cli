from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class FundamentalSnapshot:
    ticker: str
    sector: Optional[str] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    eps: Optional[float] = None
    eps_growth: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    roe: Optional[float] = None
    price_to_book: Optional[float] = None
    div_yield: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    current_price: Optional[float] = None
    horizon_return_pct: Optional[float] = None


def build_snapshot(
    ticker: str,
    info: dict,
    history: pd.DataFrame,
    horizon_days: int,
) -> FundamentalSnapshot:
    """Build a FundamentalSnapshot from raw yfinance data."""
    horizon_return = _compute_horizon_return(ticker, history)

    return FundamentalSnapshot(
        ticker=ticker,
        sector=info.get("sector"),
        pe_ratio=_safe_float(info.get("trailingPE")),
        forward_pe=_safe_float(info.get("forwardPE")),
        eps=_safe_float(info.get("trailingEps")),
        eps_growth=_safe_float(info.get("earningsGrowth")),
        revenue_growth=_safe_float(info.get("revenueGrowth")),
        profit_margin=_safe_float(info.get("profitMargins")),
        debt_to_equity=_safe_float(info.get("debtToEquity")),
        roe=_safe_float(info.get("returnOnEquity")),
        price_to_book=_safe_float(info.get("priceToBook")),
        div_yield=_safe_float(info.get("dividendYield")),
        week_52_high=_safe_float(info.get("fiftyTwoWeekHigh")),
        week_52_low=_safe_float(info.get("fiftyTwoWeekLow")),
        current_price=_safe_float(info.get("currentPrice")),
        horizon_return_pct=horizon_return,
    )


@dataclass
class ValuationSnapshot:
    ticker: str
    sector: Optional[str] = None
    current_price: Optional[float] = None
    market_cap: Optional[float] = None
    # PE
    pe_ratio: Optional[float] = None       # trailing PE
    avg_pe_6m: Optional[float] = None      # avg price / trailing EPS over 6 months
    eps: Optional[float] = None
    # Profitability
    profit_margin: Optional[float] = None  # fraction (0.27 = 27%)
    # Cash & Debt
    total_cash: Optional[float] = None
    total_debt: Optional[float] = None
    total_assets: Optional[float] = None
    debt_to_assets_pct: Optional[float] = None   # totalDebt / totalAssets * 100
    current_ratio: Optional[float] = None        # current assets / current liabilities
    quick_ratio: Optional[float] = None          # (current assets - inventory) / current liabilities
    # Analyst targets
    analyst_target_mean: Optional[float] = None
    analyst_target_low: Optional[float] = None
    analyst_target_high: Optional[float] = None
    analyst_upside_pct: Optional[float] = None   # (mean_target / current_price - 1) * 100
    num_analysts: Optional[int] = None
    recommendation_key: Optional[str] = None     # 'buy', 'hold', 'sell', 'strongBuy', etc.
    # Projections
    next_year_revenue_est: Optional[float] = None
    projected_earnings: Optional[float] = None   # next_year_rev * profit_margin
    future_market_cap: Optional[float] = None    # projected_earnings * avg_pe_6m
    possible_return_pct: Optional[float] = None  # (future_mktcap / mktcap - 1) * 100


def pe_category(pe: Optional[float]) -> tuple[str, str]:
    """Return (label, color) for PE ratio bucket per the valuation template."""
    if pe is None:
        return "N/A", "dim"
    if pe < 20:
        return "Conservative (<20x) — expects 12-15% growth", "green"
    if pe < 40:
        return "Medium Growth (20-39x) — expects 22-35% growth", "yellow"
    return "High Growth / High Risk (40+x) — expects ~100% growth", "red"


def cash_debt_rating(cash: Optional[float], debt: Optional[float]) -> tuple[str, str]:
    """Return (label, color) based on net cash position."""
    if cash is None or debt is None:
        return "N/A", "dim"
    net = cash - debt
    if net > 0:
        return "EXCELLENT", "green"
    if net > -cash * 0.5:
        return "GOOD", "yellow"
    return "CAUTION", "red"


def build_valuation_snapshot(
    ticker: str,
    info: dict,
    history_6m: pd.DataFrame,
    next_year_revenue: Optional[float],
    bs_data: Optional[dict] = None,
) -> "ValuationSnapshot":
    """Build a ValuationSnapshot with projected future market cap and return."""
    bs_data = bs_data or {}
    eps = _safe_float(info.get("trailingEps"))
    current_price = _safe_float(info.get("currentPrice"))
    market_cap = _safe_float(info.get("marketCap"))
    profit_margin = _safe_float(info.get("profitMargins"))
    pe_ratio = _safe_float(info.get("trailingPE"))
    total_cash = _safe_float(info.get("totalCash"))
    total_debt = _safe_float(info.get("totalDebt"))

    # Debt health from balance sheet
    total_assets = _safe_float(bs_data.get("totalAssets"))
    debt_to_assets_pct: Optional[float] = None
    if total_assets and total_assets > 0 and total_debt is not None:
        debt_to_assets_pct = total_debt / total_assets * 100
    current_ratio = _safe_float(info.get("currentRatio"))
    quick_ratio = _safe_float(info.get("quickRatio"))

    # Analyst price targets (all available in .info)
    analyst_target_mean = _safe_float(info.get("targetMeanPrice"))
    analyst_target_low = _safe_float(info.get("targetLowPrice"))
    analyst_target_high = _safe_float(info.get("targetHighPrice"))
    analyst_upside_pct: Optional[float] = None
    if analyst_target_mean and current_price and current_price > 0:
        analyst_upside_pct = (analyst_target_mean / current_price - 1) * 100
    num_analysts_raw = info.get("numberOfAnalystOpinions")
    num_analysts = int(num_analysts_raw) if num_analysts_raw else None
    recommendation_key = info.get("recommendationKey")

    # 6-month average PE = mean(close prices) / trailing EPS
    avg_pe_6m: Optional[float] = None
    if eps and eps > 0:
        try:
            close_col = (ticker, "Close")
            series = history_6m[close_col].dropna()
            if not series.empty:
                avg_pe_6m = float(series.mean()) / eps
        except (KeyError, TypeError):
            pass
    if avg_pe_6m is None:
        avg_pe_6m = pe_ratio  # fallback to current PE

    # Projections
    projected_earnings: Optional[float] = None
    future_market_cap: Optional[float] = None
    possible_return_pct: Optional[float] = None

    if next_year_revenue and profit_margin:
        projected_earnings = next_year_revenue * profit_margin
    if projected_earnings and avg_pe_6m:
        future_market_cap = projected_earnings * avg_pe_6m
    if future_market_cap and market_cap and market_cap > 0:
        possible_return_pct = (future_market_cap / market_cap - 1) * 100

    return ValuationSnapshot(
        ticker=ticker,
        sector=info.get("sector"),
        current_price=current_price,
        market_cap=market_cap,
        pe_ratio=pe_ratio,
        avg_pe_6m=avg_pe_6m,
        eps=eps,
        profit_margin=profit_margin,
        total_cash=total_cash,
        total_debt=total_debt,
        total_assets=total_assets,
        debt_to_assets_pct=debt_to_assets_pct,
        current_ratio=current_ratio,
        quick_ratio=quick_ratio,
        analyst_target_mean=analyst_target_mean,
        analyst_target_low=analyst_target_low,
        analyst_target_high=analyst_target_high,
        analyst_upside_pct=analyst_upside_pct,
        num_analysts=num_analysts,
        recommendation_key=recommendation_key,
        next_year_revenue_est=next_year_revenue,
        projected_earnings=projected_earnings,
        future_market_cap=future_market_cap,
        possible_return_pct=possible_return_pct,
    )


def score_ticker(snapshot: FundamentalSnapshot) -> dict[str, str]:
    """Return a color signal for each metric using simple threshold rules.

    Colors: 'green' = good, 'yellow' = neutral, 'red' = caution, 'white' = N/A
    """
    scores: dict[str, str] = {}

    scores["pe_ratio"] = _score_pe(snapshot.pe_ratio)
    scores["forward_pe"] = _score_pe(snapshot.forward_pe)
    scores["eps"] = "green" if (snapshot.eps or 0) > 0 else "red"
    scores["eps_growth"] = _score_growth(snapshot.eps_growth)
    scores["revenue_growth"] = _score_growth(snapshot.revenue_growth)
    scores["profit_margin"] = _score_margin(snapshot.profit_margin)
    scores["debt_to_equity"] = _score_debt(snapshot.debt_to_equity)
    scores["roe"] = _score_roe(snapshot.roe)
    scores["price_to_book"] = _score_pb(snapshot.price_to_book)
    scores["div_yield"] = "green" if (snapshot.div_yield or 0) > 0 else "white"
    scores["horizon_return_pct"] = _score_return(snapshot.horizon_return_pct)

    return scores


# --- helpers ---

def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        return None if (f != f) else f  # filter NaN
    except (TypeError, ValueError):
        return None


def _compute_horizon_return(ticker: str, history: pd.DataFrame) -> Optional[float]:
    try:
        close_col = (ticker, "Close")
        series = history[close_col].dropna()
        if len(series) < 2:
            return None
        first = float(series.iloc[0])
        last = float(series.iloc[-1])
        if first == 0:
            return None
        return (last - first) / first * 100
    except (KeyError, TypeError, IndexError):
        return None


def _score_pe(pe: Optional[float]) -> str:
    if pe is None:
        return "white"
    if pe < 0:
        return "red"
    if pe < 15:
        return "green"
    if pe < 30:
        return "yellow"
    return "red"


def _score_growth(g: Optional[float]) -> str:
    if g is None:
        return "white"
    if g > 0.15:
        return "green"
    if g > 0:
        return "yellow"
    return "red"


def _score_margin(m: Optional[float]) -> str:
    if m is None:
        return "white"
    if m > 0.20:
        return "green"
    if m > 0.05:
        return "yellow"
    return "red"


def _score_debt(d: Optional[float]) -> str:
    if d is None:
        return "white"
    if d < 50:
        return "green"
    if d < 150:
        return "yellow"
    return "red"


def _score_roe(r: Optional[float]) -> str:
    if r is None:
        return "white"
    if r > 0.20:
        return "green"
    if r > 0.10:
        return "yellow"
    return "red"


def _score_pb(pb: Optional[float]) -> str:
    if pb is None:
        return "white"
    if pb < 0:
        return "red"
    if pb < 3:
        return "green"
    if pb < 6:
        return "yellow"
    return "red"


def _score_return(r: Optional[float]) -> str:
    if r is None:
        return "white"
    if r > 5:
        return "green"
    if r >= 0:
        return "yellow"
    return "red"
