from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from .leaps import LeapsPosition


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
class EarningsPeriod:
    """One quarter or fiscal year of Revenue/Net Income, for the earnings-trend section."""
    period: str
    revenue: float
    net_income: float
    margin_pct: float                    # net_income / revenue * 100
    growth_pct: Optional[float] = None    # vs prior period of the same cadence (QoQ or YoY)


@dataclass
class ValuationSnapshot:
    ticker: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    business_segments: list[str] = field(default_factory=list)
    current_price: Optional[float] = None
    price_data_through: Optional[str] = None
    data_warnings: list[str] = field(default_factory=list)
    market_cap: Optional[float] = None
    # PE
    pe_ratio: Optional[float] = None       # trailing PE
    avg_pe_6m: Optional[float] = None      # mean 6m price / current trailing EPS
    avg_pe_3y: Optional[float] = None      # price / current trailing EPS proxy over 3 years
    pe_vs_history_pct: Optional[float] = None  # approximate current-price vs 3y mean-price change
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
    capex_pct_revenue: Optional[float] = None    # abs(capex_cf) / total_revenue * 100
    capex_pct_net_income: Optional[float] = None # abs(capex_cf) / net_income * 100 (None if net_income <= 0)
    # DCF intrinsic value (10-step methodology)
    dcf_net_income: Optional[float] = None       # step 1 normalized NI
    dcf_owner_earnings: Optional[float] = None   # step 2
    dcf_owner_earnings_note: Optional[str] = None
    dcf_data_note: Optional[str] = None
    dcf_growth_rate: Optional[float] = None      # step 3
    dcf_growth_note: Optional[str] = None
    dcf_discount_rate: float = 0.10              # step 4
    dcf_terminal_growth: float = 0.025           # step 5
    dcf_enterprise_value: Optional[float] = None # step 6
    dcf_equity_value: Optional[float] = None     # step 7
    intrinsic_value_per_share: Optional[float] = None  # step 8
    intrinsic_value_low: Optional[float] = None
    intrinsic_value_high: Optional[float] = None
    margin_of_safety_pct: Optional[float] = None       # step 9 (%)
    iv_rating: Optional[str] = None             # step 10 label
    iv_rating_color: Optional[str] = None       # "green" / "yellow" / "red"
    # Earnings Growth Trend (Section 8)
    earnings_quarters: list[EarningsPeriod] = field(default_factory=list)  # newest first
    earnings_years: list[EarningsPeriod] = field(default_factory=list)     # newest first
    earnings_margin_trend: Optional[str] = None   # "EXPANDING" / "STABLE" / "COMPRESSING"
    earnings_simple_note: Optional[str] = None    # e.g. "For every $10 in revenue, keeps $2.70 (27%)"


def pe_category(pe: Optional[float]) -> tuple[str, str]:
    """Return (label, color) for PE ratio bucket per the valuation template."""
    if pe is None:
        return "N/A", "dim"
    if pe < 20:
        return "Conservative (<20x) — expects 12-15% growth", "green"
    if pe < 40:
        return "Medium Growth (20-39x) — expects 22-35% growth", "yellow"
    return "High Growth / High Risk (40+x) — expects ~100% growth", "red"


def pe_vs_history_label(pct: Optional[float]) -> tuple[str, str]:
    """Describe current price versus its 3-year mean-price proxy, without value claims."""
    if pct is None:
        return "N/A", "dim"
    if pct <= -10:
        return "Below 3-year mean price", "cyan"
    if pct <= 10:
        return "Near 3-year mean price", "yellow"
    return "Above 3-year mean price", "cyan"


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


def capex_intensity_color(pct: Optional[float]) -> str:
    """Color band for a CapEx-relative-to-profitability ratio: green<25%, yellow 25-50%, red>=50%."""
    if pct is None:
        return "dim"
    if pct < 25:
        return "green"
    if pct < 50:
        return "yellow"
    return "red"


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


def _extract_business_segments(long_summary: str) -> list[str]:
    """Best-effort extraction of reportable segment names from yfinance's longBusinessSummary.

    yfinance's vendor-supplied descriptions follow one of two consistent templates for
    multi-segment companies: "operates through/in [N] segments: A, B, and C." or
    "operates through A, B, and C segments." Single-segment / non-diversified companies
    won't match either — callers should fall back to sector/industry alone in that case.
    """
    if not long_summary:
        return []

    match = re.search(
        r"operates (?:through|in)\s+(?:an?|one|two|three|four|five|six|seven|eight|nine|ten)?\s*"
        r"(?:reportable\s+)?segments?[:,]\s*([^.]+)\.",
        long_summary,
    )
    if not match:
        match = re.search(
            r"operates (?:through|in)\s+([^.]+?)\s+(?:reportable\s+)?segments?\b",
            long_summary,
        )
    if not match:
        return []

    segment_list = match.group(1)
    if "," in segment_list:
        parts = [p.strip() for p in segment_list.split(",") if p.strip()]
        if parts:
            parts[-1] = re.sub(r"^and\s+", "", parts[-1], flags=re.IGNORECASE)
    else:
        parts = [p.strip() for p in re.split(r"\s+and\s+", segment_list, maxsplit=1)]

    segments = [p for p in parts if p and len(p) <= 60]
    return segments if 1 < len(segments) <= 8 else []


def _build_earnings_periods(raw_periods: list[dict]) -> list[EarningsPeriod]:
    """Convert newest-first raw {period, revenue, net_income} dicts into EarningsPeriod,
    with margin and growth (vs the next-older period in the list) computed."""
    periods: list[EarningsPeriod] = []
    for i, p in enumerate(raw_periods):
        revenue = p["revenue"]
        net_income = p["net_income"]
        margin_pct = (net_income / revenue * 100) if revenue else 0.0

        growth_pct: Optional[float] = None
        if i + 1 < len(raw_periods):
            prior_revenue = raw_periods[i + 1]["revenue"]
            if prior_revenue:
                growth_pct = (revenue / prior_revenue - 1) * 100

        periods.append(EarningsPeriod(
            period=p["period"], revenue=revenue, net_income=net_income,
            margin_pct=margin_pct, growth_pct=growth_pct,
        ))
    return periods


def _earnings_margin_trend(years: list[EarningsPeriod]) -> Optional[str]:
    """Direction of the net-margin trend across fiscal years (newest first).

    Mirrors the owner-earnings trend heuristic: 3+ years counts up/down moves;
    exactly 2 years falls back to a +/-2 percentage-point threshold on the single delta.
    """
    if len(years) >= 3:
        margins = [y.margin_pct for y in years]
        ups = sum(1 for i in range(len(margins) - 1) if margins[i] > margins[i + 1])
        downs = sum(1 for i in range(len(margins) - 1) if margins[i] < margins[i + 1])
        if ups > downs:
            return "EXPANDING"
        if downs > ups:
            return "COMPRESSING"
        return "STABLE"
    if len(years) == 2:
        delta = years[0].margin_pct - years[1].margin_pct
        if delta > 2:
            return "EXPANDING"
        if delta < -2:
            return "COMPRESSING"
        return "STABLE"
    return None


def _earnings_simple_note(ticker: str, latest: Optional[EarningsPeriod]) -> Optional[str]:
    """Plain-English translation of the net margin, e.g. '$10 revenue -> $2.70 profit (27%)'."""
    if latest is None or not latest.revenue:
        return None
    per_ten = latest.net_income / latest.revenue * 10
    return (
        f"For every $10 in revenue, {ticker} keeps ${per_ten:.2f} in profit "
        f"— a {latest.margin_pct:.1f}% margin."
    )


def build_valuation_snapshot(
    ticker: str,
    info: dict,
    price_history: pd.DataFrame,
    next_year_revenue: Optional[float],
    bs_data: Optional[dict] = None,
    cf_data: Optional[dict] = None,
    sma_200: Optional[float] = None,
    earnings_data: Optional[dict] = None,
) -> "ValuationSnapshot":
    """Build a ValuationSnapshot with projected future market cap, return, and DCF intrinsic value."""
    bs_data = bs_data or {}
    eps = _safe_float(info.get("trailingEps"))
    current_price = _safe_float(info.get("currentPrice"))
    current_price_from_history = False
    price_data_through: Optional[str] = None
    history_close = pd.Series(dtype=float)
    try:
        history_close = price_history[(ticker, "Close")].dropna()
        if not history_close.empty:
            price_data_through = str(history_close.index.max().date())
            if current_price is None:
                current_price = float(history_close.iloc[-1])
                current_price_from_history = True
    except (KeyError, TypeError):
        pass
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

    # These are price/current-EPS proxies, not historical P/E: past EPS is unavailable.
    # price_history spans ~3 years; the 6-month window is sliced from it.
    avg_pe_6m: Optional[float] = None
    avg_pe_3y: Optional[float] = None
    avg_pe_6m_fallback = False
    if eps and eps > 0:
        try:
            close_col = (ticker, "Close")
            series = price_history[close_col].dropna()
            if not series.empty:
                cutoff_6m = series.index.max() - pd.Timedelta(days=182)
                series_6m = series[series.index >= cutoff_6m]
                if not series_6m.empty:
                    avg_pe_6m = float(series_6m.mean()) / eps
                avg_pe_3y = float(series.mean()) / eps
        except (KeyError, TypeError):
            pass
    if avg_pe_6m is None:
        avg_pe_6m = pe_ratio  # fallback to current PE
        avg_pe_6m_fallback = True

    pe_vs_history_pct: Optional[float] = None
    if pe_ratio and avg_pe_3y and avg_pe_3y > 0:
        pe_vs_history_pct = (pe_ratio / avg_pe_3y - 1) * 100

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

    # CapEx as % of Revenue / Net Income (TTM actuals, same convention as capex_intensity_pct)
    total_revenue_ttm = _safe_float(info.get("totalRevenue"))
    net_income_ttm = _safe_float(info.get("netIncomeToCommon"))
    if net_income_ttm is None and total_revenue_ttm and profit_margin:
        net_income_ttm = total_revenue_ttm * profit_margin

    capex_pct_revenue: Optional[float] = None
    capex_pct_net_income: Optional[float] = None
    if capex_cf is not None:
        abs_capex = abs(capex_cf)
        if total_revenue_ttm and total_revenue_ttm > 0:
            capex_pct_revenue = abs_capex / total_revenue_ttm * 100
        if net_income_ttm and net_income_ttm > 0:
            capex_pct_net_income = abs_capex / net_income_ttm * 100

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
    dcf_data_note: Optional[str] = None
    if dcf_net_income is not None and depreciation is not None and capex_cf is not None:
        dcf_owner_earnings = dcf_net_income + depreciation + capex_cf  # capex_cf already negative
        dcf_owner_earnings_note = "NI + D&A + CapEx (latest year; CapEx is total, not maintenance-only)"
        dcf_data_note = "Working-capital changes are not included; latest reported D&A/CapEx are paired with forecast net income."
    elif dcf_net_income is not None and free_cashflow is not None and free_cashflow > 0:
        # FCF ≈ NI + D&A - CapEx, so use it as proxy when D&A/CapEx unavailable
        dcf_owner_earnings = free_cashflow
        dcf_owner_earnings_note = "Free Cash Flow proxy used (D&A/CapEx unavailable)"
        dcf_data_note = "FCF is a proxy for owner earnings; working-capital treatment may differ from the full formula."
    elif dcf_net_income is not None and dcf_net_income > 0:
        dcf_owner_earnings = dcf_net_income
        dcf_owner_earnings_note = "Net Income proxy used (no FCF/D&A data)"
        dcf_data_note = "Net income omits reinvestment and working-capital needs, so this can overstate owner earnings."

    # Steps 3-10
    dcf_growth_rate: Optional[float] = None
    dcf_growth_note: Optional[str] = None
    dcf_enterprise_value: Optional[float] = None
    dcf_equity_value: Optional[float] = None
    intrinsic_value_per_share: Optional[float] = None
    intrinsic_value_low: Optional[float] = None
    intrinsic_value_high: Optional[float] = None
    margin_of_safety_pct: Optional[float] = None
    iv_rating: Optional[str] = None
    iv_rating_color: Optional[str] = None

    if dcf_owner_earnings is not None and dcf_owner_earnings > 0:
        dcf_growth_rate, dcf_growth_note = _select_dcf_growth_rate(revenue_growth, eps_growth, roe, roa)
        pv_oe, pv_tv = _run_dcf(dcf_owner_earnings, dcf_growth_rate, discount_rate, terminal_growth)
        dcf_enterprise_value = pv_oe + pv_tv
        # Owner Earnings starts from net income, an equity cash-flow basis. Do not
        # add cash or subtract debt, which would mix equity and enterprise methods.
        dcf_equity_value = dcf_enterprise_value
        # Step 8: per-share
        if shares_outstanding and shares_outstanding > 0:
            intrinsic_value_per_share = dcf_equity_value / shares_outstanding
            # Sensitivity envelope: lower growth/higher discount vs. higher growth/lower
            # discount. It is a model range, not a confidence interval.
            low_growth = max(0.0, dcf_growth_rate - 0.02)
            high_growth = min(0.20, dcf_growth_rate + 0.02)
            low_pv = sum(dcf_owner_earnings * (1 + low_growth) ** year / 1.12 ** year for year in range(1, 11))
            low_terminal = dcf_owner_earnings * (1 + low_growth) ** 10 * (1 + terminal_growth) / (0.12 - terminal_growth) / 1.12 ** 10
            high_pv = sum(dcf_owner_earnings * (1 + high_growth) ** year / 1.08 ** year for year in range(1, 11))
            high_terminal = dcf_owner_earnings * (1 + high_growth) ** 10 * (1 + terminal_growth) / (0.08 - terminal_growth) / 1.08 ** 10
            intrinsic_value_low = (low_pv + low_terminal) / shares_outstanding
            intrinsic_value_high = (high_pv + high_terminal) / shares_outstanding
        # Step 9 & 10
        if intrinsic_value_per_share and current_price and intrinsic_value_per_share > 0:
            margin_of_safety_pct = (intrinsic_value_per_share - current_price) / intrinsic_value_per_share * 100
            iv_rating, iv_rating_color = _iv_rating(margin_of_safety_pct / 100)

    industry = info.get("industryDisp") or info.get("industry")
    business_segments = _extract_business_segments(info.get("longBusinessSummary") or "")
    data_warnings: list[str] = []
    fetch_error = info.get("_data_fetch_error")
    if fetch_error:
        data_warnings.append(f"Fundamentals request failed ({fetch_error}); verify ticker and data connection.")
    elif not info:
        data_warnings.append("Fundamental data unavailable; verify ticker and data connection.")
    if current_price is None:
        data_warnings.append("Current price unavailable from the fundamentals response.")
    elif current_price_from_history:
        data_warnings.append("Current price uses the latest available daily close because no current quote was returned.")
    if price_data_through is None:
        data_warnings.append("Price history unavailable; price-based comparisons are omitted.")
    if next_year_revenue is None:
        data_warnings.append("Next-year analyst revenue estimate unavailable; revenue-based projections are omitted.")
    if avg_pe_6m_fallback and pe_ratio is not None:
        reason = "price history unavailable" if price_data_through is None else "trailing EPS is not positive"
        data_warnings.append(f"Projection multiple fell back to current trailing P/E because {reason}.")

    # ── Earnings Growth Trend (Section 8) ──────────────────────────────────
    earnings_data = earnings_data or {}
    earnings_quarters = _build_earnings_periods(earnings_data.get("quarters", []))
    earnings_years = _build_earnings_periods(earnings_data.get("years", []))
    earnings_margin_trend = _earnings_margin_trend(earnings_years)
    earnings_simple_note = _earnings_simple_note(
        ticker, earnings_years[0] if earnings_years else (earnings_quarters[0] if earnings_quarters else None)
    )

    return ValuationSnapshot(
        ticker=ticker,
        sector=info.get("sector"),
        industry=industry,
        business_segments=business_segments,
        current_price=current_price,
        price_data_through=price_data_through,
        data_warnings=data_warnings,
        market_cap=market_cap,
        pe_ratio=pe_ratio,
        avg_pe_6m=avg_pe_6m,
        avg_pe_3y=avg_pe_3y,
        pe_vs_history_pct=pe_vs_history_pct,
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
        capex_pct_revenue=capex_pct_revenue,
        capex_pct_net_income=capex_pct_net_income,
        dcf_net_income=dcf_net_income,
        dcf_owner_earnings=dcf_owner_earnings,
        dcf_owner_earnings_note=dcf_owner_earnings_note,
        dcf_data_note=dcf_data_note,
        dcf_growth_rate=dcf_growth_rate,
        dcf_growth_note=dcf_growth_note,
        dcf_discount_rate=discount_rate,
        dcf_terminal_growth=terminal_growth,
        dcf_enterprise_value=dcf_enterprise_value,
        dcf_equity_value=dcf_equity_value,
        intrinsic_value_per_share=intrinsic_value_per_share,
        intrinsic_value_low=intrinsic_value_low,
        intrinsic_value_high=intrinsic_value_high,
        margin_of_safety_pct=margin_of_safety_pct,
        iv_rating=iv_rating,
        iv_rating_color=iv_rating_color,
        earnings_quarters=earnings_quarters,
        earnings_years=earnings_years,
        earnings_margin_trend=earnings_margin_trend,
        earnings_simple_note=earnings_simple_note,
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
    ask: Optional[float] = None
    bid_ask_spread_pct: Optional[float] = None
    breakeven_price: Optional[float] = None
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
    ask = best.get("ask")
    midpoint = (premium + ask) / 2 if ask and ask > 0 else None
    spread_pct = ((ask - premium) / midpoint * 100) if midpoint and ask >= premium else None
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
        ask=ask,
        bid_ask_spread_pct=spread_pct,
        breakeven_price=strike - premium,
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


# --- LEAPS tracking ---


@dataclass
class LeapsGammaPoint:
    stock_price: float
    delta: float


@dataclass
class LeapsGammaCurve:
    """Black–Scholes delta curve for a LEAPS contract at fixed model inputs."""
    ticker: str
    option_type: str
    spot: float
    model_delta: float
    gamma: float  # change in delta per $1 underlying move
    vega: float   # dollars per contract per 1 IV-percentage-point move, at the current spot
    implied_volatility_pct: float
    risk_free_rate_pct: float
    dividend_yield_pct: float
    days_to_expiry: int
    iv_source: str
    risk_free_source: str
    dividend_source: str
    spot_as_of: Optional[str] = None
    points: list[LeapsGammaPoint] = field(default_factory=list)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value ** 2) / math.sqrt(2.0 * math.pi)


def _black_scholes_greeks(
    option_type: str,
    stock_price: float,
    strike: float,
    years_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> tuple[float, float, float]:
    """Return European Black–Scholes delta, gamma, and vega using continuous rates/yield.

    Vega is scaled to dollars per contract per 1 percentage-point change in IV: the textbook
    per-share vega (dollars per 1.00 = 100-point change in vol) divided by 100 for one
    percentage point, multiplied by 100 shares per contract — the two scalings cancel, so the
    raw S × e^(-qT) × φ(d1) × √T already is the right number.
    """
    if min(stock_price, strike, years_to_expiry, volatility) <= 0:
        raise ValueError("stock price, strike, time, and volatility must be positive")
    root_t = math.sqrt(years_to_expiry)
    d1 = (
        math.log(stock_price / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility**2) * years_to_expiry
    ) / (volatility * root_t)
    discounted_dividend = math.exp(-dividend_yield * years_to_expiry)
    if option_type.upper() == "CALL":
        delta = discounted_dividend * _normal_cdf(d1)
    elif option_type.upper() == "PUT":
        delta = discounted_dividend * (_normal_cdf(d1) - 1.0)
    else:
        raise ValueError("option_type must be CALL or PUT")
    pdf_d1 = _normal_pdf(d1)
    gamma = discounted_dividend * pdf_d1 / (stock_price * volatility * root_t)
    vega = stock_price * discounted_dividend * pdf_d1 * root_t
    return delta, gamma, vega


def build_leaps_gamma_curve(
    position: LeapsPosition,
    stock_price: Optional[float],
    implied_volatility_pct: Optional[float],
    risk_free_rate_pct: Optional[float],
    dividend_yield_pct: Optional[float],
    *,
    iv_source: str = "Yahoo option chain",
    risk_free_source: str = "Yahoo ^TNX 10-year Treasury yield",
    dividend_source: str = "Yahoo ticker dividend yield",
    spot_as_of: Optional[str] = None,
    price_range_pct: float = 20.0,
    point_count: int = 9,
) -> Optional[LeapsGammaCurve]:
    """Build a delta-versus-stock-price curve. Returns None when model inputs are unavailable.

    The curve holds IV, rates, dividend yield, and time to expiry fixed at their current
    readings. Gamma is local curvature: approximately how much delta changes per $1 stock move.
    """
    inputs = (stock_price, implied_volatility_pct, risk_free_rate_pct, dividend_yield_pct)
    if any(value is None or not math.isfinite(float(value)) for value in inputs):
        return None
    if point_count < 3 or point_count % 2 == 0 or price_range_pct <= 0:
        raise ValueError("point_count must be odd and at least 3; price_range_pct must be positive")

    days_to_expiry = (date.fromisoformat(position.expiration) - date.today()).days
    if days_to_expiry <= 0 or stock_price <= 0 or position.strike <= 0 or implied_volatility_pct <= 0:
        return None
    years = days_to_expiry / 365.0
    volatility = implied_volatility_pct / 100.0
    risk_free = risk_free_rate_pct / 100.0
    dividend_yield = dividend_yield_pct / 100.0
    model_delta, gamma, vega = _black_scholes_greeks(
        position.option_type, stock_price, position.strike, years, volatility, risk_free, dividend_yield
    )

    points: list[LeapsGammaPoint] = []
    for index in range(point_count):
        offset_pct = -price_range_pct + 2 * price_range_pct * index / (point_count - 1)
        scenario_price = stock_price * (1 + offset_pct / 100.0)
        scenario_delta, _, _ = _black_scholes_greeks(
            position.option_type, scenario_price, position.strike, years, volatility, risk_free, dividend_yield
        )
        points.append(LeapsGammaPoint(stock_price=scenario_price, delta=scenario_delta))

    return LeapsGammaCurve(
        ticker=position.ticker,
        option_type=position.option_type,
        spot=stock_price,
        model_delta=model_delta,
        gamma=gamma,
        vega=vega,
        implied_volatility_pct=implied_volatility_pct,
        risk_free_rate_pct=risk_free_rate_pct,
        dividend_yield_pct=dividend_yield_pct,
        days_to_expiry=days_to_expiry,
        iv_source=iv_source,
        risk_free_source=risk_free_source,
        dividend_source=dividend_source,
        spot_as_of=spot_as_of,
        points=points,
    )

@dataclass
class LeapsVegaImpact:
    """Dollar impact of IV moves, derived from a LeapsGammaCurve's current-spot vega."""
    vega_per_contract: float  # $ per contract per 1 IV percentage point
    vega_total: float         # vega_per_contract * contracts
    impact_plus_10: float
    impact_minus_10: float
    impact_minus_20: float
    entry_iv: Optional[float]
    current_iv: Optional[float]
    iv_change_pts: Optional[float]
    vega_pnl_since_entry: Optional[float]


def build_leaps_vega_impact(
    curve: Optional["LeapsGammaCurve"], position: LeapsPosition
) -> Optional[LeapsVegaImpact]:
    """Dollar impact of IV moves, using today's model vega as a constant approximation across
    the whole move since entry (vega itself drifts with price, time, and IV level).

    Returns None only when the gamma curve itself is unavailable — vega_total is still
    computable even with no IV history at all; only the "since entry" fields become None then.
    """
    if curve is None:
        return None
    vega_total = curve.vega * position.contracts
    entry_iv = position.entry_iv
    current_iv = position.current_iv if position.current_iv is not None else entry_iv
    iv_change_pts = None
    vega_pnl_since_entry = None
    if entry_iv is not None and current_iv is not None:
        iv_change_pts = current_iv - entry_iv
        vega_pnl_since_entry = vega_total * iv_change_pts
    return LeapsVegaImpact(
        vega_per_contract=curve.vega,
        vega_total=vega_total,
        impact_plus_10=vega_total * 10,
        impact_minus_10=vega_total * -10,
        impact_minus_20=vega_total * -20,
        entry_iv=entry_iv,
        current_iv=current_iv,
        iv_change_pts=iv_change_pts,
        vega_pnl_since_entry=vega_pnl_since_entry,
    )


@dataclass
class LeapsSnapshot:
    """Computed view of one LeapsPosition: entry data plus derived calculations."""
    id: str
    ticker: str
    option_type: str
    strike: float
    expiration: str
    premium: float
    contracts: int
    entry_stock_price: float
    entry_delta: Optional[float]
    entry_theta: Optional[float]
    entry_iv: Optional[float]
    status: str
    current_stock_price: Optional[float] = None
    current_option_mark: Optional[float] = None
    mark_source: Optional[str] = None
    quote_retrieved_at: Optional[str] = None
    last_trade_at: Optional[str] = None
    valuation_method: Optional[str] = None
    current_delta: Optional[float] = None
    current_theta: Optional[float] = None
    current_iv: Optional[float] = None
    last_updated: Optional[str] = None
    # --- computed ---
    breakeven: Optional[float] = None
    days_to_expiry: Optional[int] = None
    days_held: Optional[int] = None
    decay_acceleration_date: Optional[str] = None
    days_to_decay_acceleration: Optional[int] = None
    position_pct: Optional[float] = None
    intrinsic_value: Optional[float] = None
    intrinsic_value_pct: Optional[float] = None
    theoretical_current_value: Optional[float] = None
    theoretical_pnl: Optional[float] = None
    theta_30d_run_rate: Optional[float] = None
    profit_pct: Optional[float] = None
    # --- stock-equivalent exposure (value-investor "LEAPS as stock substitute" view) ---
    effective_shares: Optional[float] = None
    effective_exposure: Optional[float] = None
    effective_position_pct: Optional[float] = None
    leverage_ratio: Optional[float] = None
    realized_pnl: Optional[float] = None
    # --- IV value signal (cheap/fair/expensive vs. realized volatility proxy) ---
    realized_volatility: Optional[float] = None
    iv_value_ratio: Optional[float] = None
    iv_value_label: Optional[str] = None
    iv_value_color: str = "dim"


def leaps_dte_color(days_to_expiry: Optional[int]) -> str:
    """Red once inside the default 90-day time-stop window, else green."""
    if days_to_expiry is None:
        return "dim"
    from .config import LEAPS_DEFAULT_TIME_STOP_DAYS
    return "red" if days_to_expiry < LEAPS_DEFAULT_TIME_STOP_DAYS else "green"


def compute_leaps_decay_date(
    entry_date_iso: Optional[str], expiration_iso: str
) -> tuple[Optional[str], Optional[int]]:
    """Date at which theta decay is expected to start accelerating for this specific contract.

    Scales LEAPS_DECAY_ACCELERATION_FRACTION (default last third of life) to the position's own
    entry-to-expiration span, rather than using a flat day count for every contract length — see
    the constant's docstring in config.py for the sqrt(time)-decay rationale. Falls back to
    treating today as the start of life if entry_date is missing (mirrors build_leaps_snapshot's
    own days_held fallback).
    """
    from .config import LEAPS_DECAY_ACCELERATION_FRACTION

    expiration_date = date.fromisoformat(expiration_iso)
    entry_date = date.fromisoformat(entry_date_iso) if entry_date_iso else date.today()
    total_days = (expiration_date - entry_date).days
    if total_days <= 0:
        return None, None
    decay_date = expiration_date - timedelta(days=round(total_days * LEAPS_DECAY_ACCELERATION_FRACTION))
    days_to_decay_date = (decay_date - date.today()).days
    return decay_date.isoformat(), days_to_decay_date


def leaps_decay_color(days_to_decay_acceleration: Optional[int]) -> str:
    """Red once past the decay acceleration date, else green — same binary pattern as leaps_dte_color."""
    if days_to_decay_acceleration is None:
        return "dim"
    return "red" if days_to_decay_acceleration <= 0 else "green"


def leaps_profit_color(profit_pct: Optional[float], profit_target_multiplier: float = 1.5) -> str:
    """Green at/above the profit target, yellow while positive but below target, red when negative."""
    if profit_pct is None:
        return "dim"
    target_pct = (profit_target_multiplier - 1) * 100
    if profit_pct >= target_pct:
        return "green"
    if profit_pct >= 0:
        return "yellow"
    return "red"


def leaps_delta_color(delta: Optional[float]) -> str:
    """Color by delta magnitude; callers retain the sign for directional exposure math."""
    if delta is None:
        return "dim"
    delta = abs(delta)
    if 0.75 <= delta <= 0.85:
        return "green"
    if 0.70 <= delta < 0.75 or 0.85 < delta <= 0.90:
        return "yellow"
    return "red"


def _signed_leaps_delta(option_type: str, delta: Optional[float]) -> Optional[float]:
    """Normalize stored deltas to standard option signs, including legacy positive PUT inputs."""
    if delta is None:
        return None
    magnitude = abs(delta)
    return -magnitude if option_type.upper() == "PUT" else magnitude


def leaps_leverage_color(leverage_ratio: Optional[float]) -> str:
    """Option leverage/elasticity color: green <=4x (solidly stock-like), yellow 4-7x
    (typical deep-ITM LEAPS), red >7x (drifted into speculative, low-delta territory)."""
    if leverage_ratio is None:
        return "dim"
    if leverage_ratio <= 4:
        return "green"
    if leverage_ratio <= 7:
        return "yellow"
    return "red"


def leaps_exposure_color(effective_position_pct: Optional[float]) -> str:
    """Delta-adjusted market-exposure color, mirroring the wizard's own 3%/5% cash-sizing bands."""
    if effective_position_pct is None:
        return "dim"
    from .config import LEAPS_MAX_POSITION_PCT, LEAPS_WARN_POSITION_PCT
    if effective_position_pct > LEAPS_MAX_POSITION_PCT:
        return "red"
    if effective_position_pct > LEAPS_WARN_POSITION_PCT:
        return "yellow"
    return "green"


def leaps_iv_value_verdict(
    market_iv: Optional[float], realized_vol: Optional[float]
) -> tuple[Optional[str], str, Optional[float]]:
    """Classify a LEAPS contract's market IV as CHEAP/FAIR/EXPENSIVE against trailing realized
    volatility — the free-data proxy for "average IV" used throughout this tool, since yfinance
    has no historical-implied-volatility series. A beginner-facing signal, not a precise IV rank.

    Returns (label, color, ratio) — label and ratio are None when either input is missing.
    """
    if market_iv is None or not realized_vol:
        return None, "dim", None
    from .config import LEAPS_IV_CHEAP_RATIO, LEAPS_IV_EXPENSIVE_RATIO
    ratio = market_iv / realized_vol
    if ratio <= LEAPS_IV_CHEAP_RATIO:
        return "CHEAP", "green", ratio
    if ratio >= LEAPS_IV_EXPENSIVE_RATIO:
        return "EXPENSIVE", "red", ratio
    return "FAIR", "yellow", ratio


def possible_return_verdict(pct: Optional[float]) -> tuple[str, str]:
    """Color + label for a valuation engine's possible_return_pct, mirroring build_valuation_snapshot's own convention."""
    if pct is None:
        return "dim", "N/A"
    if pct >= 50:
        return "bold green", "Strong opportunity"
    if pct >= 15:
        return "bold yellow", "Moderate upside"
    if pct >= 0:
        return "dim", "Limited upside"
    return "bold red", "Projected downside"


def build_leaps_snapshot(
    position: LeapsPosition,
    current_price: Optional[float],
    portfolio_value: Optional[float] = None,
    option_quote: Optional[dict] = None,
    realized_vol: Optional[float] = None,
) -> LeapsSnapshot:
    option_quote = option_quote or {}
    is_active = position.status == "ACTIVE"
    if not is_active:
        current_price = None
    strike, premium = position.strike, position.premium
    breakeven = strike + premium if position.option_type == "CALL" else strike - premium

    expiration_date = date.fromisoformat(position.expiration)
    days_to_expiry = (expiration_date - date.today()).days

    entry_date = date.fromisoformat(position.entry_date) if position.entry_date else date.today()
    days_held = (date.today() - entry_date).days

    decay_acceleration_date, days_to_decay_acceleration = compute_leaps_decay_date(
        position.entry_date, position.expiration
    )

    position_pct = None
    if portfolio_value and is_active:
        position_pct = (position.contracts * premium * 100) / portfolio_value * 100

    intrinsic_value = None
    intrinsic_value_pct = None
    if current_price is not None:
        intrinsic_value = (
            max(0.0, current_price - strike) if position.option_type == "CALL" else max(0.0, strike - current_price)
        )
        if current_price:
            intrinsic_value_pct = intrinsic_value / current_price * 100

    # Current delta is appropriate for today's exposure, but not for repricing the full
    # move since entry. Without a current option mark, use entry delta only as a rough
    # first-order estimate of value since purchase.
    entry_delta = _signed_leaps_delta(position.option_type, position.entry_delta)
    current_delta = _signed_leaps_delta(position.option_type, position.current_delta)
    effective_delta = current_delta if current_delta is not None else entry_delta
    effective_theta = position.current_theta if position.current_theta is not None else position.entry_theta

    theoretical_current_value = None
    theoretical_pnl = None
    profit_pct = None
    option_mark = option_quote.get("mid") if is_active else None
    valuation_method = None
    if option_mark is not None:
        theoretical_current_value = max(0.0, float(option_mark))
        valuation_method = "Yahoo bid/ask midpoint"
    elif entry_delta is not None and current_price is not None and is_active:
        estimate = premium + (current_price - position.entry_stock_price) * entry_delta
        intrinsic_now = (
            max(0.0, current_price - strike) if position.option_type == "CALL"
            else max(0.0, strike - current_price)
        )
        theoretical_current_value = max(0.0, intrinsic_now, estimate)
        valuation_method = "rough entry-delta estimate; time value and changing Greeks omitted"
    if theoretical_current_value is not None:
        theoretical_pnl = (theoretical_current_value - premium) * 100 * position.contracts
        if premium:
            profit_pct = (theoretical_current_value - premium) / premium * 100
    elif not is_active and position.realized_pnl is not None:
        theoretical_pnl = position.realized_pnl
        profit_pct = (position.realized_pnl / (premium * 100 * position.contracts) * 100
                      if premium and position.contracts else None)

    # effective_theta is the full POSITION's $/day decay (broker's Position Theta / P.Theta
    # reading, already including the 100-share multiplier and contract count) — not a per-share
    # Greek — so no further multiplication by 100 or contracts here.
    theta_30d_run_rate = abs(effective_theta) * 30 if effective_theta is not None and is_active else None

    # Stock-equivalent exposure also uses effective_delta (computed above) since it reflects
    # *today's* real market exposure, not the exposure at entry.
    effective_shares = None
    effective_exposure = None
    effective_position_pct = None
    leverage_ratio = None
    if effective_delta is not None and is_active:
        effective_shares = effective_delta * 100 * position.contracts
        if current_price is not None:
            effective_exposure = effective_shares * current_price
            if portfolio_value:
                effective_position_pct = abs(effective_exposure) / portfolio_value * 100
            if theoretical_current_value and theoretical_current_value > 0:
                leverage_ratio = abs(effective_delta * current_price) / theoretical_current_value

    iv_value_label, iv_value_color, iv_value_ratio = None, "dim", None
    if is_active:
        latest_iv = position.current_iv if position.current_iv is not None else position.entry_iv
        iv_value_label, iv_value_color, iv_value_ratio = leaps_iv_value_verdict(latest_iv, realized_vol)

    return LeapsSnapshot(
        id=position.id,
        ticker=position.ticker,
        option_type=position.option_type,
        strike=strike,
        expiration=position.expiration,
        premium=premium,
        contracts=position.contracts,
        entry_stock_price=position.entry_stock_price,
        entry_delta=entry_delta,
        entry_theta=position.entry_theta,
        entry_iv=position.entry_iv,
        status=position.status,
        current_stock_price=current_price,
        current_option_mark=option_mark,
        mark_source="Yahoo bid/ask midpoint" if option_mark is not None else None,
        quote_retrieved_at=option_quote.get("retrieved_at") if is_active else None,
        last_trade_at=option_quote.get("last_trade_at") if is_active else None,
        valuation_method=valuation_method,
        current_delta=current_delta,
        current_theta=position.current_theta,
        current_iv=position.current_iv,
        last_updated=position.last_updated,
        breakeven=breakeven,
        days_to_expiry=days_to_expiry,
        days_held=days_held,
        decay_acceleration_date=decay_acceleration_date,
        days_to_decay_acceleration=days_to_decay_acceleration,
        position_pct=position_pct,
        intrinsic_value=intrinsic_value,
        intrinsic_value_pct=intrinsic_value_pct,
        theoretical_current_value=theoretical_current_value,
        theoretical_pnl=theoretical_pnl,
        theta_30d_run_rate=theta_30d_run_rate,
        profit_pct=profit_pct,
        effective_shares=effective_shares,
        effective_exposure=effective_exposure,
        effective_position_pct=effective_position_pct,
        leverage_ratio=leverage_ratio,
        realized_pnl=position.realized_pnl if not is_active else None,
        realized_volatility=realized_vol if is_active else None,
        iv_value_ratio=iv_value_ratio,
        iv_value_label=iv_value_label,
        iv_value_color=iv_value_color,
    )


@dataclass
class LeapsScenarioRow:
    price: float
    intrinsic: float
    pnl: float
    return_pct: float


@dataclass
class LeapsLossExitLevel:
    loss_pct: float  # 30.0 or 50.0
    target_value: float  # contract value (per-share) at this loss level
    target_price: Optional[float]  # approx. required stock price, via linear delta estimate
    severity: str  # "yellow" or "red"


# (loss_pct, severity) — 30% is an early warning to reassess, 50% is a hard exit signal
LOSS_EXIT_THRESHOLDS: tuple[tuple[float, str], ...] = ((30.0, "yellow"), (50.0, "red"))


@dataclass
class LeapsScenario:
    """At-expiration P&L ladder plus breakeven/early-exit/loss-exit context for one LeapsPosition.

    Pure math — intrinsic value at expiration needs no Greeks. The early-exit and loss-exit price
    estimates reuse the same linear delta approximation as LeapsSnapshot's theoretical
    P&L (no time-decay/theta modeling), so they are explicitly flagged as a rough guide.
    """
    ticker: str
    option_type: str
    strike: float
    premium: float
    contracts: int
    total_cost: float
    breakeven: float
    days_to_expiry: Optional[int]
    base_price: float
    current_option_value: Optional[float]
    current_value_source: str
    rows: list[LeapsScenarioRow]
    pct_move_to_breakeven: Optional[float]
    move_direction: str  # "rise" or "fall"
    upside_scenarios: list[tuple[float, LeapsScenarioRow]]
    early_exit_target_value: Optional[float]
    early_exit_target_price: Optional[float]
    loss_exit_levels: list[LeapsLossExitLevel]
    time_stop_date: Optional[str]
    warnings: list[str] = field(default_factory=list)


def build_leaps_scenario(
    position: LeapsPosition,
    current_price: Optional[float] = None,
    current_option_mark: Optional[float] = None,
) -> LeapsScenario:
    is_call = position.option_type == "CALL"
    strike, premium, contracts = position.strike, position.premium, position.contracts
    total_cost = premium * 100 * contracts
    breakeven = strike + premium if is_call else strike - premium
    base_price = current_price if current_price is not None else position.entry_stock_price

    def _row(price: float) -> LeapsScenarioRow:
        intrinsic = (
            max(0.0, price - strike) * 100 * contracts
            if is_call
            else max(0.0, strike - price) * 100 * contracts
        )
        pnl = intrinsic - total_cost
        return_pct = pnl / total_cost * 100 if total_cost else 0.0
        return LeapsScenarioRow(price=price, intrinsic=intrinsic, pnl=pnl, return_pct=return_pct)

    multipliers = (
        [0.7, 0.85, 0.95, 1.0, 1.1, 1.2, 1.3, 1.4, 1.6]
        if is_call
        else [1.3, 1.15, 1.05, 1.0, 0.9, 0.8, 0.7, 0.6, 0.4]
    )
    price_points = {round(base_price * m) for m in multipliers} if base_price else set()
    price_points.add(round(strike))
    price_points.add(round(breakeven))
    rows = [_row(float(p)) for p in sorted(price_points)]

    pct_move_to_breakeven = None
    if base_price:
        pct_move_to_breakeven = (
            (breakeven - base_price) / base_price * 100
            if is_call
            else (base_price - breakeven) / base_price * 100
        )
    move_direction = "rise" if is_call else "fall"

    upside_scenarios: list[tuple[float, LeapsScenarioRow]] = []
    if base_price:
        for pct in (20.0, 40.0):
            target_price = base_price * (1 + pct / 100) if is_call else base_price * (1 - pct / 100)
            upside_scenarios.append((pct, _row(target_price)))

    days_to_expiry = None
    time_stop_date = None
    try:
        exp_date = date.fromisoformat(position.expiration)
        days_to_expiry = (exp_date - date.today()).days
        time_stop_date = (exp_date - timedelta(days=position.days_before_expiry_exit)).isoformat()
    except ValueError:
        pass

    early_exit_target_value = premium * position.profit_target_multiplier
    early_exit_target_price = None
    entry_delta = _signed_leaps_delta(position.option_type, position.entry_delta)
    current_delta = _signed_leaps_delta(position.option_type, position.current_delta)
    effective_delta = current_delta if current_delta is not None else entry_delta
    current_option_value = current_option_mark
    if current_option_value is None and current_price is not None and entry_delta is not None:
        rough_value = premium + (current_price - position.entry_stock_price) * entry_delta
        intrinsic_now = max(0.0, current_price - strike) if is_call else max(0.0, strike - current_price)
        current_option_value = max(0.0, intrinsic_now, rough_value)
        current_value_source = "entry-delta estimate"
    else:
        current_value_source = "Yahoo bid/ask midpoint" if current_option_mark is not None else "unavailable"
    if effective_delta and base_price is not None and current_option_value is not None:
        early_exit_target_price = base_price + (early_exit_target_value - current_option_value) / effective_delta

    loss_exit_levels: list[LeapsLossExitLevel] = []
    for loss_pct, severity in LOSS_EXIT_THRESHOLDS:
        target_value = premium * (1 - loss_pct / 100)
        target_price = None
        if effective_delta and base_price is not None and current_option_value is not None:
            target_price = base_price + (target_value - current_option_value) / effective_delta
        loss_exit_levels.append(
            LeapsLossExitLevel(
                loss_pct=loss_pct, target_value=target_value, target_price=target_price, severity=severity
            )
        )

    warnings: list[str] = []
    if position.entry_iv is not None:
        warnings.append(
            f"IV at entry: {position.entry_iv:.1f}% — recheck current IV rank with your broker; "
            "this tool doesn't track IV history."
        )
    warnings.append(
        "Confirm the next earnings date before entering or exiting — earnings can cause a gap and a change in implied volatility; direction and size are uncertain."
    )
    if time_stop_date:
        warnings.append(
            f"Time-stop: plan to close or roll by {time_stop_date} "
            f"({position.days_before_expiry_exit} days before expiry) — theta accelerates sharply inside that window."
        )

    return LeapsScenario(
        ticker=position.ticker,
        option_type=position.option_type,
        strike=strike,
        premium=premium,
        contracts=contracts,
        total_cost=total_cost,
        breakeven=breakeven,
        days_to_expiry=days_to_expiry,
        base_price=base_price,
        current_option_value=current_option_value,
        current_value_source=current_value_source,
        rows=rows,
        pct_move_to_breakeven=pct_move_to_breakeven,
        move_direction=move_direction,
        upside_scenarios=upside_scenarios,
        early_exit_target_value=early_exit_target_value,
        early_exit_target_price=early_exit_target_price,
        loss_exit_levels=loss_exit_levels,
        time_stop_date=time_stop_date,
        warnings=warnings,
    )
