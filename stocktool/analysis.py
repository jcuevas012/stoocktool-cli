from __future__ import annotations

from dataclasses import dataclass, field
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
    sma_200: Optional[float] = None              # 200-day simple moving average price
    pct_from_sma_200: Optional[float] = None     # (current_price / sma_200 - 1) * 100
    # Projections (existing PE-based)
    next_year_revenue_est: Optional[float] = None
    projected_earnings: Optional[float] = None   # next_year_rev * profit_margin
    future_market_cap: Optional[float] = None    # projected_earnings * avg_pe_6m
    possible_return_pct: Optional[float] = None  # (future_mktcap / mktcap - 1) * 100
    # Extra fundamentals for DCF
    shares_outstanding: Optional[float] = None
    revenue_growth: Optional[float] = None       # decimal (0.10 = 10%)
    eps_growth: Optional[float] = None           # decimal
    roe: Optional[float] = None                  # decimal
    roa: Optional[float] = None                  # decimal
    free_cashflow: Optional[float] = None
    # Cashflow statement data
    depreciation: Optional[float] = None
    capex_cf: Optional[float] = None             # negative value from yfinance
    # DCF intrinsic value (10-step methodology)
    dcf_net_income: Optional[float] = None       # step 1 normalized NI
    dcf_owner_earnings: Optional[float] = None   # step 2
    dcf_owner_earnings_note: Optional[str] = None
    dcf_growth_rate: Optional[float] = None      # step 3
    dcf_growth_note: Optional[str] = None
    dcf_discount_rate: float = 0.10              # step 4
    dcf_terminal_growth: float = 0.025           # step 5
    dcf_enterprise_value: Optional[float] = None # step 6
    dcf_equity_value: Optional[float] = None     # step 7
    intrinsic_value_per_share: Optional[float] = None  # step 8
    margin_of_safety_pct: Optional[float] = None       # step 9 (%)
    iv_rating: Optional[str] = None             # step 10 label
    iv_rating_color: Optional[str] = None       # "green" / "yellow" / "red"


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


def _select_dcf_growth_rate(
    revenue_growth: Optional[float],
    eps_growth: Optional[float],
    roe: Optional[float],
    roa: Optional[float],
) -> tuple[float, str]:
    """Choose a conservative DCF growth rate. Returns (rate, explanation)."""
    candidates = []
    parts = []
    if revenue_growth is not None and revenue_growth > 0:
        candidates.append(revenue_growth)
        parts.append(f"rev +{revenue_growth:.1%}")
    if eps_growth is not None and eps_growth > 0:
        candidates.append(eps_growth)
        parts.append(f"EPS +{eps_growth:.1%}")

    quality = roe or roa or 0.0

    if not candidates:
        return 0.04, "No positive growth signals found; conservative 4% default assumed"

    avg = sum(candidates) / len(candidates)

    # Cap based on capital-allocation quality (ROE/ROA as proxy for ROIC)
    if quality > 0.25 and avg >= 0.10:
        cap, tier = 0.15, "high-ROIC compounder (>25% ROE)"
    elif quality > 0.15 or avg >= 0.08:
        cap, tier = 0.12, "solid capital allocator"
    else:
        cap, tier = 0.08, "mature/average business"

    rate = min(avg, cap)
    note = f"Avg of {', '.join(parts)}, capped at {cap:.0%} for {tier}"
    return rate, note


def _run_dcf(
    owner_earnings: float,
    growth_rate: float,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.025,
    n_years: int = 10,
) -> tuple[float, float]:
    """Return (pv_of_projected_earnings, pv_of_terminal_value)."""
    pv_oe = sum(
        owner_earnings * (1 + growth_rate) ** t / (1 + discount_rate) ** t
        for t in range(1, n_years + 1)
    )
    oe_year_n = owner_earnings * (1 + growth_rate) ** n_years
    terminal_value = oe_year_n * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_tv = terminal_value / (1 + discount_rate) ** n_years
    return pv_oe, pv_tv


def _iv_rating(margin_of_safety: float) -> tuple[str, str]:
    """Return (label, color) for a margin-of-safety fraction."""
    if margin_of_safety > 0.40:
        return "★★★★★ Strong Buy", "green"
    if margin_of_safety > 0.25:
        return "★★★★ Buy", "green"
    if margin_of_safety > 0.15:
        return "★★★ Fair Value", "yellow"
    if margin_of_safety > 0.05:
        return "★★ Hold", "yellow"
    return "★ Overvalued", "red"


def build_valuation_snapshot(
    ticker: str,
    info: dict,
    history_6m: pd.DataFrame,
    next_year_revenue: Optional[float],
    bs_data: Optional[dict] = None,
    cf_data: Optional[dict] = None,
    sma_200: Optional[float] = None,
) -> "ValuationSnapshot":
    """Build a ValuationSnapshot with projected future market cap, return, and DCF intrinsic value."""
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

    pct_from_sma_200: Optional[float] = None
    if sma_200 and current_price and sma_200 > 0:
        pct_from_sma_200 = (current_price / sma_200 - 1) * 100

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

    # Projections (PE-based)
    projected_earnings: Optional[float] = None
    future_market_cap: Optional[float] = None
    possible_return_pct: Optional[float] = None

    if next_year_revenue and profit_margin:
        projected_earnings = next_year_revenue * profit_margin
    if projected_earnings and avg_pe_6m:
        future_market_cap = projected_earnings * avg_pe_6m
    if future_market_cap and market_cap and market_cap > 0:
        possible_return_pct = (future_market_cap / market_cap - 1) * 100

    # Extra fundamentals from .info
    # Use market_cap / price as authoritative share count — sharesOutstanding from yfinance
    # can omit share classes (e.g. GOOGL only returns Class A, missing Class B and C).
    shares_outstanding: Optional[float] = None
    if market_cap and current_price and current_price > 0:
        shares_outstanding = market_cap / current_price
    if shares_outstanding is None:
        shares_outstanding = _safe_float(info.get("sharesOutstanding"))
    revenue_growth = _safe_float(info.get("revenueGrowth"))
    eps_growth = _safe_float(info.get("earningsGrowth"))
    roe = _safe_float(info.get("returnOnEquity"))
    roa = _safe_float(info.get("returnOnAssets"))
    free_cashflow = _safe_float(info.get("freeCashflow"))

    # Cashflow data (depreciation / capex for Owner Earnings)
    cf_data = cf_data or {}
    depreciation = _safe_float(cf_data.get("depreciation"))
    capex_cf = _safe_float(cf_data.get("capex"))  # negative value in yfinance

    # ── DCF Intrinsic Value (10-step Buffett methodology) ─────────────────
    discount_rate = 0.10
    terminal_growth = 0.025

    # Step 1: Normalized Net Income
    dcf_net_income: Optional[float] = None
    if next_year_revenue and profit_margin:
        dcf_net_income = next_year_revenue * profit_margin

    # Step 2: Owner Earnings = NI + Dep - Maintenance CapEx
    dcf_owner_earnings: Optional[float] = None
    dcf_owner_earnings_note: Optional[str] = None
    if dcf_net_income is not None and depreciation is not None and capex_cf is not None:
        dcf_owner_earnings = dcf_net_income + depreciation + capex_cf  # capex_cf already negative
        dcf_owner_earnings_note = "NI + D&A + CapEx (full formula)"
    elif dcf_net_income is not None and free_cashflow is not None and free_cashflow > 0:
        # FCF ≈ NI + D&A - CapEx, so use it as proxy when D&A/CapEx unavailable
        dcf_owner_earnings = free_cashflow
        dcf_owner_earnings_note = "Free Cash Flow used (D&A/CapEx unavailable)"
    elif dcf_net_income is not None and dcf_net_income > 0:
        dcf_owner_earnings = dcf_net_income
        dcf_owner_earnings_note = "Net Income used as fallback (no FCF/D&A data)"

    # Steps 3-10
    dcf_growth_rate: Optional[float] = None
    dcf_growth_note: Optional[str] = None
    dcf_enterprise_value: Optional[float] = None
    dcf_equity_value: Optional[float] = None
    intrinsic_value_per_share: Optional[float] = None
    margin_of_safety_pct: Optional[float] = None
    iv_rating: Optional[str] = None
    iv_rating_color: Optional[str] = None

    if dcf_owner_earnings is not None and dcf_owner_earnings > 0:
        dcf_growth_rate, dcf_growth_note = _select_dcf_growth_rate(revenue_growth, eps_growth, roe, roa)
        pv_oe, pv_tv = _run_dcf(dcf_owner_earnings, dcf_growth_rate, discount_rate, terminal_growth)
        dcf_enterprise_value = pv_oe + pv_tv
        # Step 7: add cash, subtract debt
        dcf_equity_value = dcf_enterprise_value + (total_cash or 0) - (total_debt or 0)
        # Step 8: per-share
        if shares_outstanding and shares_outstanding > 0:
            intrinsic_value_per_share = dcf_equity_value / shares_outstanding
        # Step 9 & 10
        if intrinsic_value_per_share and current_price and intrinsic_value_per_share > 0:
            margin_of_safety_pct = (intrinsic_value_per_share - current_price) / intrinsic_value_per_share * 100
            iv_rating, iv_rating_color = _iv_rating(margin_of_safety_pct / 100)

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
        sma_200=sma_200,
        pct_from_sma_200=pct_from_sma_200,
        next_year_revenue_est=next_year_revenue,
        projected_earnings=projected_earnings,
        future_market_cap=future_market_cap,
        possible_return_pct=possible_return_pct,
        shares_outstanding=shares_outstanding,
        revenue_growth=revenue_growth,
        eps_growth=eps_growth,
        roe=roe,
        roa=roa,
        free_cashflow=free_cashflow,
        depreciation=depreciation,
        capex_cf=capex_cf,
        dcf_net_income=dcf_net_income,
        dcf_owner_earnings=dcf_owner_earnings,
        dcf_owner_earnings_note=dcf_owner_earnings_note,
        dcf_growth_rate=dcf_growth_rate,
        dcf_growth_note=dcf_growth_note,
        dcf_discount_rate=discount_rate,
        dcf_terminal_growth=terminal_growth,
        dcf_enterprise_value=dcf_enterprise_value,
        dcf_equity_value=dcf_equity_value,
        intrinsic_value_per_share=intrinsic_value_per_share,
        margin_of_safety_pct=margin_of_safety_pct,
        iv_rating=iv_rating,
        iv_rating_color=iv_rating_color,
    )


@dataclass
class ETFHolding:
    symbol: str
    name: str
    weight_pct: float                            # 0-100 scale
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    earnings_growth: Optional[float] = None       # decimal (0.10 = 10%)


@dataclass
class ETFValuationSnapshot:
    ticker: str
    long_name: Optional[str] = None
    fund_family: Optional[str] = None
    category: Optional[str] = None
    current_price: Optional[float] = None
    total_assets: Optional[float] = None            # AUM
    expense_ratio: Optional[float] = None
    distribution_yield_pct: Optional[float] = None  # already a %, per yfinance convention

    # Section 1 — Basket Concentration & Top Holdings
    holdings: list = field(default_factory=list)     # list[ETFHolding]
    concentration_pct: Optional[float] = None        # sum of top-10 weights
    holdings_pe_coverage_note: Optional[str] = None

    # Section 2 — Valuation Multiples & PEGY
    trailing_pe: Optional[float] = None
    trailing_pe_source: Optional[str] = None          # "etf_info" | "weighted_holdings"
    forward_eps_growth_pct: Optional[float] = None
    pegy_ratio: Optional[float] = None
    pegy_label: Optional[str] = None
    pegy_color: Optional[str] = None

    # Section 3 — Historical Valuation Bands & NAV
    hist_5y_avg_pe: Optional[float] = None
    hist_pe_note: Optional[str] = None
    fair_value: Optional[float] = None
    ema_50: Optional[float] = None
    sma_200: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    tier1_entry: Optional[float] = None               # DCA pullback
    tier2_entry: Optional[float] = None               # valuation reversion

    # Section 4 — 5-Year Projection
    growth_rate_used: Optional[float] = None          # decimal
    projected_eps_5y: Optional[float] = None
    projected_price_5y: Optional[float] = None
    total_return_pct: Optional[float] = None
    cagr_pct: Optional[float] = None

    # Section 5 — Entry Strategy & Rating
    margin_of_safety_pct: Optional[float] = None
    rating: Optional[str] = None
    rating_color: Optional[str] = None


def calculate_pegy(
    trailing_pe: Optional[float],
    forward_eps_growth_pct: Optional[float],
    distribution_yield_pct: Optional[float],
) -> Optional[float]:
    """PEGY = trailing_pe / (growth_pct + yield_pct). None if any input missing or growth <= 0."""
    if trailing_pe is None or forward_eps_growth_pct is None or distribution_yield_pct is None:
        return None
    if forward_eps_growth_pct <= 0:
        return None
    denom = forward_eps_growth_pct + distribution_yield_pct
    if denom <= 0:
        return None
    return trailing_pe / denom


def pegy_status(pegy: Optional[float]) -> tuple[str, str]:
    """Return (label, color) bucket for a PEGY ratio."""
    if pegy is None:
        return "N/A", "dim"
    if pegy < 1.0:
        return "Undervalued", "green"
    if pegy <= 2.0:
        return "Fairly Valued", "yellow"
    return "Overvalued", "red"


def calculate_fair_value(
    current_price: Optional[float],
    hist_5y_avg_pe: Optional[float],
    trailing_pe: Optional[float],
) -> Optional[float]:
    """Fair value via P/E reversion: current_price * (hist_5y_avg_pe / trailing_pe)."""
    if current_price is None or hist_5y_avg_pe is None or not trailing_pe:
        return None
    return current_price * (hist_5y_avg_pe / trailing_pe)


def calculate_margin_of_safety(
    fair_value: Optional[float], current_price: Optional[float]
) -> Optional[float]:
    """(fair_value - current_price) / current_price * 100 — returns a percent."""
    if fair_value is None or not current_price:
        return None
    return (fair_value - current_price) / current_price * 100


def calculate_5y_projection(
    current_eps: Optional[float],
    growth_rate: Optional[float],
    terminal_pe: Optional[float],
    current_price: Optional[float],
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Return (projected_eps_5y, projected_price_5y, total_return_pct, cagr_pct)."""
    if current_eps is None or growth_rate is None or terminal_pe is None or not current_price:
        return None, None, None, None

    projected_eps_5y = current_eps * (1 + growth_rate) ** 5
    projected_price_5y = projected_eps_5y * terminal_pe
    if projected_price_5y < 0:
        return projected_eps_5y, projected_price_5y, None, None

    total_return_pct = (projected_price_5y / current_price - 1) * 100
    cagr_pct = ((projected_price_5y / current_price) ** (1 / 5) - 1) * 100
    return projected_eps_5y, projected_price_5y, total_return_pct, cagr_pct


def determine_etf_rating(
    pegy: Optional[float], margin_of_safety_pct: Optional[float]
) -> tuple[str, str]:
    """Explicit top-to-bottom ladder, first match wins.

    Rule 4b ("Hold/Neutral") is not in the source SRS — it fills a real gap in the
    literal ladder (e.g. pegy=1.7, mos=-5 matches none of rules 1-4) so that only
    genuinely missing data falls into the "Insufficient Data" catch-all.
    """
    mos = margin_of_safety_pct
    if pegy is not None and mos is not None:
        if pegy < 1.5 and mos > 10:
            return "★★★★★ Strong Buy", "green"
        if pegy < 2.0 and mos > 0:
            return "★★★★☆ Buy/Accumulate", "green"
        if 2.0 <= pegy <= 2.8:
            return "★★★☆☆ Hold/DCA on Pullbacks", "yellow"
        if pegy > 2.8 or mos < -20:
            return "★★☆☆☆ Overvalued/Trim", "red"
        return "★★☆☆☆ Hold/Neutral", "yellow"
    if pegy is not None and pegy > 2.8:
        return "★★☆☆☆ Overvalued/Trim", "red"
    if mos is not None and mos < -20:
        return "★★☆☆☆ Overvalued/Trim", "red"
    return "☆☆☆☆☆ Insufficient Data", "dim"


def _weighted_harmonic_pe(holdings: list[ETFHolding]) -> tuple[Optional[float], str]:
    """Weighted harmonic-mean PE over holdings with a valid positive trailing PE."""
    covered = [h for h in holdings if h.trailing_pe and h.trailing_pe > 0]
    if not covered:
        return None, f"0/{len(holdings)} holdings, 0% of top-10 weight"
    weight_sum = sum(h.weight_pct for h in covered)
    if weight_sum <= 0:
        return None, f"0/{len(holdings)} holdings, 0% of top-10 weight"
    weighted_pe = weight_sum / sum(h.weight_pct / h.trailing_pe for h in covered)
    note = f"{len(covered)}/{len(holdings)} holdings, {weight_sum:.0f}% of top-10 weight"
    return weighted_pe, note


def _weighted_forward_growth(holdings: list[ETFHolding]) -> Optional[float]:
    """Weighted arithmetic-mean forward EPS growth (decimal) over holdings with valid growth.

    yfinance's per-stock earningsGrowth is a raw trailing YoY figure that can spike
    to 1000%+ off a near-zero prior-year base (e.g. a cyclical semiconductor coming
    out of a down year) — it is noisy, not a sustainable forward growth signal.
    Clip each holding to [-30%, +50%] before weighting, mirroring how
    _select_dcf_growth_rate already caps even high-ROIC compounders at 15% rather
    than trusting raw growth figures — a wide-but-sane band prevents one outlier
    name (or yfinance's noise) from producing an absurd basket-level growth rate.
    """
    covered = [h for h in holdings if h.earnings_growth is not None]
    weight_sum = sum(h.weight_pct for h in covered)
    if not covered or weight_sum <= 0:
        return None
    clipped = [max(-0.3, min(0.5, h.earnings_growth)) for h in covered]
    return sum(h.weight_pct * g for h, g in zip(covered, clipped)) / weight_sum


def build_etf_valuation_snapshot(
    ticker: str,
    etf_info: dict,
    top_holdings: list[dict],
    holding_fundamentals: dict[str, dict],
    technicals: dict,
    hist_pe: Optional[float],
    hist_pe_error: Optional[str],
) -> ETFValuationSnapshot:
    """Build an ETFValuationSnapshot: concentration, PEGY, fair value, 5Y projection, entry tiers.

    Never raises — every field defaults to None on missing inputs.
    """
    technicals = technicals or {}
    etf_info = etf_info or {}
    current_price = technicals.get("current_price")

    # ── Section 1: Top holdings + concentration ──
    holdings: list[ETFHolding] = []
    for h in (top_holdings or [])[:10]:
        symbol = str(h.get("symbol", "")).upper()
        fundamentals = holding_fundamentals.get(symbol, {}) if holding_fundamentals else {}
        holdings.append(
            ETFHolding(
                symbol=symbol,
                name=h.get("holdingName", ""),
                weight_pct=float(h.get("holdingPercent", 0) or 0) * 100,  # yfinance returns a decimal fraction
                trailing_pe=fundamentals.get("trailing_pe"),
                forward_pe=fundamentals.get("forward_pe"),
                earnings_growth=fundamentals.get("earnings_growth"),
            )
        )
    concentration_pct = sum(h.weight_pct for h in holdings) if holdings else None

    # ── Section 2: Basket PE + forward growth + PEGY ──
    weighted_pe, coverage_note = _weighted_harmonic_pe(holdings)
    trailing_pe = etf_info.get("trailing_pe") or weighted_pe
    trailing_pe_source = "etf_info" if etf_info.get("trailing_pe") else "weighted_holdings"

    weighted_growth = _weighted_forward_growth(holdings)
    forward_eps_growth_pct = weighted_growth * 100 if weighted_growth is not None else None

    trailing_dividend_yield = etf_info.get("trailing_dividend_yield")  # true fraction, per data.fetch_etf_info
    distribution_yield_pct = trailing_dividend_yield * 100 if trailing_dividend_yield is not None else None

    pegy_ratio = calculate_pegy(trailing_pe, forward_eps_growth_pct, distribution_yield_pct)
    pegy_label, pegy_color = pegy_status(pegy_ratio)

    # ── Section 3: Historical avg PE (FMP or proxy) + fair value + entry tiers ──
    if hist_pe is not None:
        hist_5y_avg_pe = hist_pe
        hist_pe_note = "FMP 5-year average"
    else:
        avg_price_5y = technicals.get("avg_price_5y")
        if avg_price_5y is not None and trailing_pe and current_price:
            hist_5y_avg_pe = avg_price_5y * (trailing_pe / current_price)
            hist_pe_note = f"Proxy: mean(5y price) × (current PE / current price) — FMP unavailable ({hist_pe_error})"
        else:
            hist_5y_avg_pe = None
            hist_pe_note = f"Unavailable — FMP unavailable ({hist_pe_error}) and insufficient price/PE data for proxy"

    fair_value = calculate_fair_value(current_price, hist_5y_avg_pe, trailing_pe)
    margin_of_safety_pct = calculate_margin_of_safety(fair_value, current_price)

    ema_50 = technicals.get("ema_50")
    sma_200 = technicals.get("sma_200")

    if ema_50 is not None and current_price is not None:
        tier1_entry = min(ema_50, current_price * 0.95)
    elif current_price is not None:
        tier1_entry = current_price * 0.95
    else:
        tier1_entry = None

    if fair_value is not None and sma_200 is not None:
        tier2_entry = min(fair_value, sma_200)
    elif fair_value is not None:
        tier2_entry = fair_value
    elif sma_200 is not None:
        tier2_entry = sma_200
    else:
        tier2_entry = None

    # ── Section 4: 5-year projection ──
    if forward_eps_growth_pct is not None and forward_eps_growth_pct > 0:
        growth_rate_used = min(forward_eps_growth_pct / 100, 0.15)
    else:
        growth_rate_used = 0.06

    current_eps = current_price / trailing_pe if current_price and trailing_pe else None
    projected_eps_5y, projected_price_5y, total_return_pct, cagr_pct = calculate_5y_projection(
        current_eps, growth_rate_used, hist_5y_avg_pe, current_price
    )

    # ── Section 5: Rating ──
    rating, rating_color = determine_etf_rating(pegy_ratio, margin_of_safety_pct)

    return ETFValuationSnapshot(
        ticker=ticker,
        long_name=etf_info.get("long_name"),
        fund_family=etf_info.get("fund_family"),
        category=etf_info.get("category"),
        current_price=current_price,
        total_assets=etf_info.get("total_assets"),
        expense_ratio=etf_info.get("expense_ratio"),
        distribution_yield_pct=distribution_yield_pct,
        holdings=holdings,
        concentration_pct=concentration_pct,
        holdings_pe_coverage_note=coverage_note,
        trailing_pe=trailing_pe,
        trailing_pe_source=trailing_pe_source,
        forward_eps_growth_pct=forward_eps_growth_pct,
        pegy_ratio=pegy_ratio,
        pegy_label=pegy_label,
        pegy_color=pegy_color,
        hist_5y_avg_pe=hist_5y_avg_pe,
        hist_pe_note=hist_pe_note,
        fair_value=fair_value,
        ema_50=ema_50,
        sma_200=sma_200,
        week_52_high=technicals.get("week_52_high"),
        week_52_low=technicals.get("week_52_low"),
        tier1_entry=tier1_entry,
        tier2_entry=tier2_entry,
        growth_rate_used=growth_rate_used,
        projected_eps_5y=projected_eps_5y,
        projected_price_5y=projected_price_5y,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        margin_of_safety_pct=margin_of_safety_pct,
        rating=rating,
        rating_color=rating_color,
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
