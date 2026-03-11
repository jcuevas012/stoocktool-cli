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


@dataclass
class ValueCheckSnapshot:
    ticker: str
    sector: Optional[str] = None
    current_price: Optional[float] = None
    pe_ratio: Optional[float] = None        # trailingPE
    pb_ratio: Optional[float] = None        # priceToBook
    pfcf_ratio: Optional[float] = None      # marketCap / freeCashflow


def build_value_check_snapshot(ticker: str, info: dict) -> ValueCheckSnapshot:
    """Build a ValueCheckSnapshot from raw yfinance .info dict."""
    market_cap = _safe_float(info.get("marketCap"))
    free_cashflow = _safe_float(info.get("freeCashflow"))
    pfcf: Optional[float] = None
    if market_cap and free_cashflow and free_cashflow > 0:
        pfcf = market_cap / free_cashflow

    return ValueCheckSnapshot(
        ticker=ticker,
        sector=info.get("sector"),
        current_price=_safe_float(info.get("currentPrice")),
        pe_ratio=_safe_float(info.get("trailingPE")),
        pb_ratio=_safe_float(info.get("priceToBook")),
        pfcf_ratio=pfcf,
    )


@dataclass
class OwnerEarningsYear:
    """One year of owner earnings data."""
    year: str
    net_income: float
    depreciation: float
    capex: float                     # negative value
    working_capital_change: float
    owner_earnings: float


@dataclass
class OwnerEarningsSnapshot:
    """Owner Earnings analysis for a single ticker."""
    ticker: str
    sector: Optional[str] = None
    current_price: Optional[float] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    # Latest year
    owner_earnings: Optional[float] = None
    net_income: Optional[float] = None
    depreciation: Optional[float] = None
    capex: Optional[float] = None
    working_capital_change: Optional[float] = None
    # Computed
    oe_per_share: Optional[float] = None
    oe_yield_pct: Optional[float] = None          # owner_earnings / market_cap * 100
    oe_vs_net_income_pct: Optional[float] = None   # (OE / net_income - 1) * 100
    capex_intensity_pct: Optional[float] = None    # abs(capex) / (net_income + depreciation) * 100
    # Multi-year trend
    years: list[OwnerEarningsYear] = None  # type: ignore[assignment]
    oe_growth_pct: Optional[float] = None  # YoY growth of latest vs prior year
    oe_cagr_pct: Optional[float] = None    # CAGR across all available years
    trend_direction: Optional[str] = None  # "GROWING", "STABLE", "DECLINING"


def build_owner_earnings_snapshot(ticker: str, data: dict) -> Optional[OwnerEarningsSnapshot]:
    """Build an OwnerEarningsSnapshot from raw cashflow data."""
    if not data or "owner_earnings" not in data:
        return None

    oe = data["owner_earnings"]
    ni = data["net_income"]
    dep = data["depreciation"]
    capex = data["capex"]
    wc = data["working_capital_change"]
    mktcap = data.get("market_cap")
    shares = data.get("shares_outstanding")

    # Owner earnings per share
    oe_per_share = oe / shares if shares and shares > 0 else None

    # Owner earnings yield
    oe_yield = (oe / mktcap * 100) if mktcap and mktcap > 0 and oe > 0 else None

    # OE vs Net Income comparison
    oe_vs_ni = ((oe / ni - 1) * 100) if ni and ni > 0 else None

    # CapEx intensity: how much of gross cash flow goes to maintaining the business
    gross_cash = ni + dep if dep else ni
    capex_intensity = (abs(capex) / gross_cash * 100) if gross_cash and gross_cash > 0 else None

    # Multi-year data
    year_snapshots = []
    for y in data.get("years", []):
        year_snapshots.append(OwnerEarningsYear(
            year=y["year"],
            net_income=y["net_income"],
            depreciation=y["depreciation"],
            capex=y["capex"],
            working_capital_change=y["working_capital_change"],
            owner_earnings=y["owner_earnings"],
        ))

    # Growth calculations
    oe_growth = None
    oe_cagr = None
    trend = None
    if len(year_snapshots) >= 2:
        latest_oe = year_snapshots[0].owner_earnings
        prior_oe = year_snapshots[1].owner_earnings
        if prior_oe and prior_oe > 0:
            oe_growth = (latest_oe / prior_oe - 1) * 100

    if len(year_snapshots) >= 3:
        oldest_oe = year_snapshots[-1].owner_earnings
        newest_oe = year_snapshots[0].owner_earnings
        n_years = len(year_snapshots) - 1
        if oldest_oe and oldest_oe > 0 and newest_oe and newest_oe > 0:
            oe_cagr = ((newest_oe / oldest_oe) ** (1 / n_years) - 1) * 100

    # Trend direction based on multi-year pattern
    if len(year_snapshots) >= 3:
        oe_values = [y.owner_earnings for y in year_snapshots]
        # Count how many years show growth vs decline (newest first, so reverse)
        ups = sum(1 for i in range(len(oe_values) - 1) if oe_values[i] > oe_values[i + 1])
        downs = sum(1 for i in range(len(oe_values) - 1) if oe_values[i] < oe_values[i + 1])
        if ups > downs:
            trend = "GROWING"
        elif downs > ups:
            trend = "DECLINING"
        else:
            trend = "STABLE"
    elif oe_growth is not None:
        trend = "GROWING" if oe_growth > 5 else ("DECLINING" if oe_growth < -5 else "STABLE")

    return OwnerEarningsSnapshot(
        ticker=ticker,
        sector=data.get("sector"),
        current_price=data.get("current_price"),
        market_cap=mktcap,
        shares_outstanding=shares,
        owner_earnings=oe,
        net_income=ni,
        depreciation=dep,
        capex=capex,
        working_capital_change=wc,
        oe_per_share=oe_per_share,
        oe_yield_pct=oe_yield,
        oe_vs_net_income_pct=oe_vs_ni,
        capex_intensity_pct=capex_intensity,
        years=year_snapshots,
        oe_growth_pct=oe_growth,
        oe_cagr_pct=oe_cagr,
        trend_direction=trend,
    )


@dataclass
class CashSecuredPutSnapshot:
    """One put-selling opportunity for a portfolio stock."""
    ticker: str
    current_price: Optional[float] = None
    beta: Optional[float] = None
    expiration: Optional[str] = None
    dte: Optional[int] = None
    # Selected put contract
    strike: Optional[float] = None
    premium: Optional[float] = None          # bid price per share
    # Computed
    cash_required: Optional[float] = None    # strike * 100
    return_pct: Optional[float] = None       # premium / strike * 100
    annualized_return_pct: Optional[float] = None
    effective_buy_price: Optional[float] = None  # strike - premium
    discount_pct: Optional[float] = None     # discount from current price
    open_interest: Optional[int] = None
    implied_volatility: Optional[float] = None
    # Valuation context (from valuation engine)
    possible_return_pct: Optional[float] = None
    valuation_verdict: Optional[str] = None


def _valuation_verdict(possible_return: Optional[float]) -> str:
    """Map possible return % to a Buffett-style verdict."""
    if possible_return is None:
        return "N/A"
    if possible_return >= 50:
        return "STRONG BUY"
    if possible_return >= 15:
        return "GOOD VALUE"
    if possible_return >= 0:
        return "FAIR"
    return "OVERVALUED"


def build_csp_snapshot(
    ticker: str,
    put_data: dict,
    valuation: Optional["ValuationSnapshot"] = None,
    target_otm_pct: float = 5.0,
) -> Optional[CashSecuredPutSnapshot]:
    """Build a CashSecuredPutSnapshot by selecting the best put near target_otm_pct below price.

    Returns None if no suitable put is found.
    """
    current_price = put_data.get("current_price")
    puts = put_data.get("puts", [])
    if not current_price or not puts:
        return None

    # Target strike: ~target_otm_pct% below current price
    target_strike = current_price * (1 - target_otm_pct / 100)

    # Find the put closest to target strike
    best = min(puts, key=lambda p: abs(p["strike"] - target_strike))

    strike = best["strike"]
    premium = best["bid"]
    dte = put_data.get("dte")

    cash_required = strike * 100
    return_pct = (premium / strike * 100) if strike > 0 else None
    annualized = (return_pct * 365 / dte) if return_pct and dte and dte > 0 else None
    effective_buy = strike - premium
    discount = ((current_price - effective_buy) / current_price * 100) if current_price > 0 else None

    possible_return = valuation.possible_return_pct if valuation else None
    verdict = _valuation_verdict(possible_return)

    return CashSecuredPutSnapshot(
        ticker=ticker,
        current_price=current_price,
        beta=put_data.get("beta"),
        expiration=put_data.get("expiration"),
        dte=dte,
        strike=strike,
        premium=premium,
        cash_required=cash_required,
        return_pct=return_pct,
        annualized_return_pct=annualized,
        effective_buy_price=effective_buy,
        discount_pct=discount,
        open_interest=best.get("open_interest"),
        implied_volatility=best.get("implied_volatility"),
        possible_return_pct=possible_return,
        valuation_verdict=verdict,
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
