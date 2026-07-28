"""
html_report.py — Self-contained HTML report generator for stocktool analysis snapshots.

Generates a single HTML file (inline CSS, pure SVG charts, no external dependencies)
from any combination of FundamentalSnapshot, ValuationSnapshot, OwnerEarningsSnapshot,
and ValueCheckSnapshot dataclasses.

Public API:
    generate_html_report(snapshots, output_path) -> str
"""
from __future__ import annotations

import html
import pathlib
import webbrowser
from datetime import datetime
from typing import Optional, Union

from .analysis import (
    FundamentalSnapshot,
    ValuationSnapshot,
    ValueCheckSnapshot,
    OwnerEarningsSnapshot,
    ETFValuationSnapshot,
    score_ticker,
    pe_category,
    cash_debt_rating,
    _score_pe,
    _score_growth,
    _score_margin,
    _score_debt,
    _score_roe,
    _score_pb,
    _score_return,
)

AnySnapshot = Union[
    FundamentalSnapshot,
    ValuationSnapshot,
    ValueCheckSnapshot,
    OwnerEarningsSnapshot,
    ETFValuationSnapshot,
]

# ---------------------------------------------------------------------------
# Color mapping: analysis.py color names → CSS variables
# ---------------------------------------------------------------------------
_COLOR_MAP = {
    "green":  "var(--clr-green)",
    "yellow": "var(--clr-yellow)",
    "red":    "var(--clr-red)",
    "white":  "var(--clr-fg)",
    "dim":    "var(--clr-muted)",
}

_BADGE_CLASS = {
    "green":  "badge badge-green",
    "yellow": "badge badge-yellow",
    "red":    "badge badge-red",
    "white":  "badge badge-neutral",
    "dim":    "badge badge-neutral",
}


def _css_color(score_key: str) -> str:
    return _COLOR_MAP.get(score_key, "var(--clr-fg)")


def _badge(text: str, color: str) -> str:
    cls = _BADGE_CLASS.get(color, "badge badge-neutral")
    return f'<span class="{cls}">{html.escape(str(text))}</span>'


def _val(v, fmt: str = "", suffix: str = "", prefix: str = "", na: str = "N/A") -> str:
    if v is None:
        return f'<span class="na">{na}</span>'
    try:
        if fmt:
            return f"{prefix}{v:{fmt}}{suffix}"
        return f"{prefix}{v}{suffix}"
    except (ValueError, TypeError):
        return f'<span class="na">{na}</span>'


def _fmt_large(v: Optional[float]) -> str:
    """Format large numbers as $1.23T / $456.7B / $12.3M etc."""
    if v is None:
        return '<span class="na">N/A</span>'
    abs_v = abs(v)
    sign = "-" if v < 0 else ""
    if abs_v >= 1e12:
        return f"{sign}${abs_v / 1e12:.2f}T"
    if abs_v >= 1e9:
        return f"{sign}${abs_v / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{sign}${abs_v / 1e6:.2f}M"
    return f"{sign}${abs_v:,.0f}"


def _tr(label: str, value_html: str, tip: str, row_style: str = "") -> str:
    """Metric row with hover tooltip. tip supports \\n for line breaks."""
    safe_tip = html.escape(tip)
    style_attr = f' style="{row_style}"' if row_style else ""
    return (
        f'<div class="metric-row has-tip" data-tip="{safe_tip}"{style_attr}>'
        f'<span class="metric-label">{html.escape(label)}</span>'
        f'<span class="metric-value">{value_html}</span>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Tooltip copy — what each metric means + good value ranges
# ---------------------------------------------------------------------------
_TIPS = {
    # ── Fundamentals ────────────────────────────────────────────────────────
    "pe_trailing":      "Trailing P/E — Price ÷ last-12-month EPS.\nHow much you pay for $1 of annual profit.\n\n✅ < 15x — cheap, value territory\n🟡 15–25x — fair price\n🔴 > 25x — expensive premium\n🔴 Negative — company reporting a loss",
    "pe_forward":       "Forward P/E — Price ÷ next-12-month EPS estimate.\nUses analyst forecasts, so more forward-looking than trailing PE.\n\n✅ < 15x — good entry\n🟡 15–25x — fair\n🔴 > 25x — growth priced in",
    "price_book":       "Price / Book Value.\nCompares market price to net asset value (assets − liabilities).\n\n✅ < 1.5x — deep value, paying close to assets\n🟡 1.5–3x — fair premium for quality\n🔴 > 3x — paying heavily for intangibles/goodwill",
    "eps":              "Earnings Per Share (trailing 12 months).\nThe per-share profit foundation for all PE ratios.\n\n✅ Positive & growing — healthy\n🔴 Negative — company losing money\n📌 Strong EPS growth is the engine of long-term returns",
    "div_yield":        "Annual dividend ÷ share price.\nIncome you receive for holding the stock.\n\n✅ > 2% — meaningful income\n🟡 1–2% — modest yield\n⚪ 0% — growth-focused, reinvests profits\n📌 Very high yields (>6%) may signal distress",
    "eps_growth":       "Year-over-year growth in Earnings Per Share.\nMeasures how fast per-share profits are expanding.\n\n✅ > 15% — strong growth\n🟡 0–15% — modest improvement\n🔴 Negative — earnings contracting",
    "rev_growth":       "Year-over-year top-line revenue growth.\nGrowing revenue without earnings can mean heavy investment or margin pressure.\n\n✅ > 15% — high growth\n🟡 5–15% — steady growth\n🔴 < 0% — shrinking business",
    "profit_margin":    "Net Income ÷ Revenue.\nOf every $1 in sales, how much becomes profit.\n\n✅ > 20% — strong moat & pricing power\n🟡 5–20% — competitive but manageable\n🔴 < 5% — thin margins, vulnerable to shocks",
    "roe":              "Return on Equity — Net Income ÷ Shareholders' Equity.\nMeasures how efficiently management uses your invested capital.\n\n✅ > 20% — excellent capital allocator\n🟡 10–20% — decent returns\n🔴 < 10% — poor use of capital",
    "debt_equity":      "Total Debt ÷ Shareholders' Equity.\nHow leveraged the company is relative to its own equity base.\n\n✅ < 50 — conservatively financed\n🟡 50–150 — moderate leverage\n🔴 > 150 — highly leveraged, higher risk",
    "hi52":             "The highest closing price over the past 52 weeks.\nCurrent price near the 52-week high may indicate momentum but less margin of safety.",
    "lo52":             "The lowest closing price over the past 52 weeks.\nCurrent price near the 52-week low can signal opportunity or a deteriorating business — dig deeper.",
    "horizon_return":   "Price return over the selected analysis horizon (default 90 days).\nMeasures recent momentum, not fundamental value.\n\n✅ > 5% — positive trend\n🟡 0–5% — flat\n🔴 Negative — recent price weakness",
    # ── Valuation section ───────────────────────────────────────────────────
    "avg_pe_6m":        "Average P/E ratio over the past 6 months.\nSmooths out daily noise to show what investors have recently paid on average.\nUsed in the valuation projection to estimate future market cap.",
    "inv_profile":      "Investment style implied by the current P/E multiple.\n\n< 20x — Value / Conservative (expects 12–15% growth)\n20–40x — Medium Growth (expects 22–35% growth)\n> 40x — High Growth / Speculative (expects ~100% growth)",
    "total_cash":       "Cash, equivalents, and short-term investments on the balance sheet.\n\n✅ Exceeds total debt — fortress balance sheet\n🟡 Below total debt but manageable\n🔴 Tiny vs. obligations — limited safety net",
    "total_debt":       "Total long-term financial debt.\nSustainable when well below annual Free Cash Flow × 5.\n\n✅ Well below cash & FCF\n🟡 Manageable, serviceable from earnings\n🔴 Exceeds cash + multi-year FCF",
    "net_cash":         "Total Cash − Total Debt.\nPositive = net creditor (fortress). Negative = net debtor.\n\n✅ Positive — financial strength\n🟡 Slightly negative — watch debt maturity\n🔴 Deeply negative — leverage risk",
    "debt_assets":      "Total Debt ÷ Total Assets.\nWhat % of the company's resources are debt-financed.\n\n✅ < 40% — low leverage\n🟡 40–65% — moderate\n🔴 > 65% — high leverage, elevated risk",
    "current_ratio":    "Current Assets ÷ Current Liabilities.\nCan the company pay all bills due within 12 months?\n\n✅ ≥ 1.5x — healthy liquidity\n🟡 1.0–1.5x — adequate but monitor\n🔴 < 1.0x — may struggle to meet short-term obligations",
    "quick_ratio":      "Like Current Ratio but excludes inventory (hardest to liquidate quickly).\nMore conservative liquidity test.\n\n✅ ≥ 1.0x — solid\n🟡 0.7–1.0x — acceptable\n🔴 < 0.7x — tight",
    "rev_est":          "Wall Street analyst consensus for next year's revenue.\nGrowing estimates signal confidence; declining estimates signal concern.\n📌 Used directly in the valuation projection formula.",
    "market_cap":       "Total market value of all outstanding shares.\nUseful for sizing: <$2B small-cap, $2–10B mid-cap, >$10B large-cap.\nUsed as the denominator in many valuation ratios.",
    "eps_val":          "Earnings Per Share (trailing 12 months).\nFoundation for the P/E ratio. Must be positive for most value metrics to apply.",
    "analyst_low":      "Most pessimistic analyst 12-month price target.\nRepresents the bear case floor. A current price below the low target is unusual.",
    "analyst_mean":     "Average of all analyst 12-month price targets — the street consensus.\n\n✅ > 20% upside — analysts see real opportunity\n🟡 5–20% — modest implied upside\n🔴 < 5% or negative — market already pricing in growth",
    "analyst_high":     "Most optimistic analyst 12-month price target.\nRepresents the bull case with aggressive assumptions. Treat as ceiling, not expectation.",
    "analyst_upside":   "% gap from current price to analyst mean target.\n\n✅ > 20% — meaningful consensus upside\n🟡 5–20% — modest\n🔴 Negative — priced above analyst targets",
    "consensus":        "Aggregated analyst recommendation across all covering analysts.\n\nStrong Buy / Buy — bullish majority\nHold — neutral, neither buy nor sell\nSell / Strong Sell — bearish, proceed with caution",
    "num_analysts":     "Number of analysts publishing price targets for this stock.\nMore analysts = more reliable consensus signal.\n\n✅ > 15 — good coverage\n🟡 5–15 — moderate\n🔴 < 5 — thin coverage, treat targets cautiously",
    "possible_return":  "Projected return if the company reaches its estimated future market cap.\nFormula: (Revenue Est × Margin × Avg PE) ÷ Current Market Cap − 1\n\n✅ > 50% — strong long-term value opportunity\n🟡 15–50% — moderate upside\n⚪ 0–15% — limited upside at current price\n🔴 Negative — projected downside",
    # ── DCF card ────────────────────────────────────────────────────────────
    "dcf_ni":           "Normalized Net Income = Next-Year Revenue Estimate × Profit Margin.\nThe starting annual profit used to seed the DCF model.\nMore forward-looking than reported trailing net income.",
    "dcf_oe":           "Owner Earnings (Buffett's definition):\nNet Income + Depreciation − Capital Expenditures\n\nCaptures the true cash generated for owners after maintaining and replacing assets.\nHigher than net income = business generates more cash than it reports (good).\nLower = heavy capex drag on reported earnings.",
    "dcf_growth":       "Annual Owner Earnings growth rate applied for 10 years.\nDerived conservatively from trailing revenue & EPS growth, capped by ROE quality tier:\n\n✅ High-ROIC (ROE>25%): capped at 15%\n🟡 Solid allocator (ROE>15%): capped at 12%\n⚪ Average business: capped at 8%\n\nVery high trailing growth is capped to avoid unrealistic projections.",
    "dcf_discount":     "Required annual return (discount rate) = 10%.\nAll future cash flows are divided by (1.10)^year to get today's equivalent value.\nBuffett benchmarks against 10% as the long-run US equity average.\nA higher rate would produce a lower (more conservative) intrinsic value.",
    "dcf_terminal":     "Perpetual growth rate assumed for all cash flows beyond year 10 = 2.5%.\nApproximates long-run nominal GDP growth. No business can outgrow the economy forever.\n\n⚠ Even a 0.5% change here meaningfully shifts terminal value — treat with skepticism.",
    "dcf_ev":           "Enterprise Value = PV of 10 projected Owner Earnings years + PV of Terminal Value.\nThis is the estimated standalone business value, before accounting for cash and debt on the balance sheet.",
    "dcf_equity":       "Equity Value = Enterprise Value + Cash − Debt.\nAdjusts the business value for what shareholders actually own after paying off debt.\nPositive net cash boosts equity value; net debt reduces it.",
    "dcf_iv":           "Intrinsic Value Per Share = Equity Value ÷ Total Shares Outstanding.\nEstimated fair price based on fundamentals, not market sentiment.\n\n📌 Use as a reference range ± 20%, not a precise target.\n📌 Most accurate for stable, profitable businesses with predictable cash flows.",
    "dcf_mos":          "Margin of Safety = (Intrinsic Value − Current Price) ÷ Intrinsic Value\n\nThe discount you get vs. estimated fair value. Higher = more cushion for error.\n\n✅ > 40% — strong margin, wide buffer\n✅ 25–40% — solid buying opportunity\n🟡 15–25% — fair value zone, slim buffer\n🟡 5–15% — priced close to fair value\n🔴 < 5% or negative — no margin of safety",
    # ── Owner Earnings section ───────────────────────────────────────────────
    "oe_net_income":    "Reported net income from the income statement (latest fiscal year).\nStarting point for Buffett's Owner Earnings formula.\nCan differ from true cash earnings due to non-cash items.",
    "oe_depreciation":  "Depreciation & Amortization — a non-cash accounting expense added back.\nRepresents the paper cost of aging assets, not an actual cash outflow.\nHigh D&A vs. CapEx suggests capital-light model.",
    "oe_capex":         "Capital Expenditures — cash spent on property, plant, and equipment.\nSubtracted from Owner Earnings because this cash is genuinely consumed to maintain the business.\n\n✅ Low vs. operating cash flow — capital-light (good)\n🔴 High vs. operating cash flow — capital-intensive (tough business)",
    "oe_wc":            "Change in Working Capital — cash tied up (or released) by operations.\nNegative = cash consumed by inventory/receivables growth.\nPositive = cash released as payables extend.\nIgnored if unavailable; approximated as zero.",
    "oe_total":         "Owner Earnings = Net Income + D&A + CapEx − Working Capital Change.\nBuffett's preferred measure of true business profitability.\nMore reliable than GAAP net income for assessing real cash generation.",
    "oe_per_share":     "Owner Earnings ÷ Shares Outstanding.\nThe per-share cash the business truly earns for you as an owner.\nCompare to stock price: Price ÷ OE/Share = effective P/OE multiple.",
    "oe_vs_ni":         "How Owner Earnings compare to reported Net Income.\n\n✅ > +10% — earns more cash than it reports (conservative accounting)\n🟡 -10% to +10% — profits match cash generation\n🔴 < -10% — reported profits overstate real cash earnings",
    "oe_yield":         "Owner Earnings ÷ Market Cap.\nThe cash return you earn as an owner at the current price — like a real earnings yield.\n\n✅ ≥ 8% — excellent value at current price\n🟡 4–8% — decent return\n🔴 < 4% — paying a premium, thin yield",
    "cap_intensity":    "CapEx as % of (Net Income + D&A) — how much of gross cash flow goes to maintaining assets.\n\n✅ < 25% — capital-light cash machine (toll bridge model)\n🟡 25–50% — moderate reinvestment needed\n🔴 ≥ 50% — heavy capex, capital-intensive business",
    "oe_trend":         "Direction of Owner Earnings over multiple years.\n\n✅ GROWING — cash generation accelerating\n🟡 STABLE — consistent but not expanding\n🔴 DECLINING — deteriorating cash production",
    "oe_yoy":           "Year-over-year change in Owner Earnings (latest vs prior year).\nShort-term signal — one bad year can be noise; two in a row is a pattern.",
    "oe_cagr":          "Compound Annual Growth Rate of Owner Earnings across all available years.\nMore reliable than single-year YoY. Aim for CAGR above your discount rate (10%) for a compounding business.",
    # ── Value Check ─────────────────────────────────────────────────────────
    "vc_pe":            "Trailing P/E (Price ÷ EPS).\nCore value-investing metric.\n\n✅ < 15x — bargain territory\n🟡 15–25x — fair value\n🔴 > 25x or negative — expensive or loss-making",
    "vc_pb":            "Price / Book Value per share.\nCompares what you pay to the company's net asset value.\n\n✅ < 1.5x — deep value (buying near or below assets)\n🟡 1.5–3x — fair premium for quality\n🔴 > 3x — paying heavily for brand / intangibles",
    "vc_pfcf":          "Price / Free Cash Flow.\nLike P/E but uses actual cash generated instead of accounting earnings.\nOften more reliable than P/E for capital-intensive companies.\n\n✅ < 15x — strong value\n🟡 15–25x — fair\n🔴 > 25x — expensive",
    # ── ETF Valuation ────────────────────────────────────────────────────────
    "etf_concentration": "Sum of the top-10 holdings' portfolio weight.\nHigher concentration means the fund behaves more like those individual stocks.\n\n✅ < 40% — diversified\n🟡 40–60% — moderate concentration\n🔴 > 60% — concentrated, few names drive returns",
    "etf_trailing_pe":  "Basket-level trailing P/E — from the ETF's own .info if populated, otherwise a weighted harmonic mean of the top-10 holdings' trailing P/E.",
    "etf_growth":       "Weighted average forward EPS growth across the top-10 holdings (each clipped to [-30%, +50%] to limit the effect of noisy single-stock YoY figures before weighting).",
    "etf_yield":        "Trailing 12-month distribution yield for the fund.",
    "etf_pegy":         "PEGY = Trailing P/E ÷ (Forward EPS Growth % + Distribution Yield %).\nAdjusts P/E for both growth and income, not just growth (PEG) alone.\n\n✅ < 1.0x — undervalued\n🟡 1.0–2.0x — fairly valued\n🔴 > 2.0x — overvalued",
    "etf_hist_pe":      "5-year historical average P/E, from Financial Modeling Prep when an API key is configured — otherwise a proxy: mean(5-year price) × (current PE ÷ current price), which assumes basket EPS is roughly stable over the window.",
    "etf_fair_value":   "Fair Value = Current Price × (5Y Avg P/E ÷ Trailing P/E).\nEstimates what the price would be if the fund's P/E reverted to its historical average.",
    "etf_entry_zone":   "Tier 1 (DCA Pullback) = min(50-day EMA, Price × 0.95).\nTier 2 (Valuation Reversion) = min(Fair Value, 200-day SMA).\nTwo disciplined price levels for phased entries.",
    "etf_projection":   "5-Year Projection: Projected EPS = Current EPS-equivalent × (1 + growth)^5; Projected Price = Projected EPS × Terminal P/E (5Y avg).\nCurrent EPS-equivalent = Current Price ÷ Trailing P/E — a basket-level approximation, not a literal reported EPS.",
    "etf_mos":          "Margin of Safety = (Fair Value − Current Price) ÷ Current Price.\nThe cushion between the estimated fair value and what you'd pay today.\n\n✅ > 25% — solid buying opportunity\n🟡 5–25% — fair value zone\n🔴 < 5% or negative — little to no margin",
}


# ---------------------------------------------------------------------------
# Inline CSS — dark theme, card grid, badges, sparkline
# ---------------------------------------------------------------------------
_CSS = """
/* ── Reset & base ─────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --clr-bg:       #0f1117;
  --clr-surface:  #1a1d27;
  --clr-border:   #2a2d3e;
  --clr-fg:       #e2e8f0;
  --clr-muted:    #64748b;
  --clr-accent:   #6366f1;
  --clr-green:    #22c55e;
  --clr-yellow:   #eab308;
  --clr-red:      #ef4444;
  --clr-blue:     #3b82f6;
  --radius:       10px;
  --shadow:       0 4px 24px rgba(0,0,0,.4);
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background: var(--clr-bg);
  color: var(--clr-fg);
  line-height: 1.6;
  font-size: 14px;
  padding: 0 0 60px;
}

a { color: var(--clr-accent); text-decoration: none; }

/* ── Top header bar ────────────────────────────────────────────── */
.report-header {
  background: var(--clr-surface);
  border-bottom: 1px solid var(--clr-border);
  padding: 24px 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: var(--shadow);
}
.report-header h1 {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--clr-fg);
  letter-spacing: -0.02em;
}
.report-header h1 span { color: var(--clr-accent); }
.report-meta { font-size: 0.78rem; color: var(--clr-muted); }

/* ── Layout ────────────────────────────────────────────────────── */
.container { max-width: 1280px; margin: 0 auto; padding: 32px 24px 0; }
.section-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--clr-fg);
  margin: 40px 0 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--clr-border);
  letter-spacing: -0.01em;
}

/* ── Ticker nav tabs ───────────────────────────────────────────── */
.ticker-nav {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 24px 0 0;
  padding-bottom: 32px;
  border-bottom: 1px solid var(--clr-border);
}
.ticker-pill {
  background: var(--clr-surface);
  border: 1px solid var(--clr-border);
  border-radius: 40px;
  padding: 6px 20px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--clr-muted);
  cursor: pointer;
  transition: all .15s;
}
.ticker-pill:hover,
.ticker-pill.active {
  background: var(--clr-accent);
  border-color: var(--clr-accent);
  color: #fff;
}

/* ── Ticker section ────────────────────────────────────────────── */
.ticker-section { display: none; }
.ticker-section.active { display: block; margin-top: 36px; }

/* ── Hero card ─────────────────────────────────────────────────── */
.hero-card {
  background: linear-gradient(135deg, var(--clr-surface) 0%, #1e2235 100%);
  border: 1px solid var(--clr-border);
  border-radius: var(--radius);
  padding: 28px 32px;
  margin-bottom: 24px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 20px;
  box-shadow: var(--shadow);
}
.hero-left h2 {
  font-size: 2.2rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--clr-fg);
}
.hero-left .ticker-sub {
  font-size: 0.85rem;
  color: var(--clr-muted);
  margin-top: 4px;
}
.hero-right { text-align: right; }
.hero-price {
  font-size: 2rem;
  font-weight: 700;
  color: var(--clr-accent);
  letter-spacing: -0.02em;
}
.hero-price-sub { font-size: 0.8rem; color: var(--clr-muted); margin-top: 2px; }

/* ── Card grid ─────────────────────────────────────────────────── */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.card-grid.wide {
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
}

/* ── Card ──────────────────────────────────────────────────────── */
.card {
  background: var(--clr-surface);
  border: 1px solid var(--clr-border);
  border-radius: var(--radius);
  padding: 20px 22px;
  box-shadow: var(--shadow);
  transition: border-color .15s;
}
.card:hover { border-color: var(--clr-accent); }
.card-title {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--clr-muted);
  margin-bottom: 14px;
}
.card-title .card-icon { margin-right: 6px; opacity: .7; }

/* ── Metric rows inside cards ──────────────────────────────────── */
.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 5px 0;
  border-bottom: 1px solid var(--clr-border);
  gap: 12px;
}
.metric-row:last-child { border-bottom: none; }
.metric-label {
  font-size: 0.82rem;
  color: var(--clr-muted);
  flex: 1;
  white-space: nowrap;
}
.metric-value {
  font-size: 0.88rem;
  font-weight: 600;
  text-align: right;
}
.metric-hint {
  font-size: 0.72rem;
  color: var(--clr-muted);
  margin-top: 2px;
  text-align: right;
  font-style: italic;
}

/* ── Color utilities ───────────────────────────────────────────── */
.text-green  { color: var(--clr-green); }
.text-yellow { color: var(--clr-yellow); }
.text-red    { color: var(--clr-red); }
.text-blue   { color: var(--clr-blue); }
.text-muted  { color: var(--clr-muted); }
.text-accent { color: var(--clr-accent); }
.na          { color: var(--clr-muted); font-style: italic; }

/* ── Badges ────────────────────────────────────────────────────── */
.badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 20px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.badge-green   { background: rgba(34,197,94,.15);  color: var(--clr-green); border: 1px solid rgba(34,197,94,.3); }
.badge-yellow  { background: rgba(234,179,8,.15);  color: var(--clr-yellow); border: 1px solid rgba(234,179,8,.3); }
.badge-red     { background: rgba(239,68,68,.15);  color: var(--clr-red); border: 1px solid rgba(239,68,68,.3); }
.badge-neutral { background: rgba(100,116,139,.1); color: var(--clr-muted); border: 1px solid rgba(100,116,139,.2); }
.badge-accent  { background: rgba(99,102,241,.15); color: var(--clr-accent); border: 1px solid rgba(99,102,241,.3); }

/* ── Big metric highlight ──────────────────────────────────────── */
.big-metric {
  text-align: center;
  padding: 8px 0 12px;
}
.big-metric .val {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}
.big-metric .sub {
  font-size: 0.76rem;
  color: var(--clr-muted);
  margin-top: 4px;
}

/* ── SVG sparkline / bar chart ─────────────────────────────────── */
.chart-wrap {
  margin-top: 12px;
  overflow-x: auto;
}
.sparkline-bar {
  transition: opacity .15s;
}
.sparkline-bar:hover { opacity: .8; }
.chart-label {
  font-size: 11px;
  fill: var(--clr-muted);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.chart-value-label {
  font-size: 10px;
  font-weight: 700;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

/* ── Projection flow ───────────────────────────────────────────── */
.projection-flow {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
  font-size: 0.84rem;
}
.proj-step {
  background: rgba(99,102,241,.08);
  border: 1px solid rgba(99,102,241,.2);
  border-radius: 6px;
  padding: 6px 12px;
  text-align: center;
}
.proj-step .step-label { font-size: 0.68rem; color: var(--clr-muted); text-transform: uppercase; letter-spacing: .05em; }
.proj-step .step-val   { font-weight: 700; color: var(--clr-fg); margin-top: 2px; }
.proj-arrow { color: var(--clr-muted); font-size: 1.1rem; flex-shrink: 0; }

/* ── Hover tooltips ────────────────────────────────────────────── */
.metric-row.has-tip { cursor: help; }
.metric-row.has-tip .metric-label {
  text-decoration: underline dotted rgba(100,116,139,.5);
  text-underline-offset: 3px;
}
#_tt {
  display: none;
  position: fixed;
  z-index: 9999;
  background: #1a1d27;
  border: 1px solid #3a3d52;
  border-radius: 10px;
  padding: 12px 16px;
  font-size: .78rem;
  line-height: 1.65;
  color: #e2e8f0;
  max-width: 300px;
  box-shadow: 0 8px 32px rgba(0,0,0,.7);
  pointer-events: none;
  white-space: pre-line;
}

/* ── Comparison table ──────────────────────────────────────────── */
.compare-wrap { overflow-x: auto; margin-top: 8px; }
.compare-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}
.compare-table th {
  background: rgba(99,102,241,.1);
  color: var(--clr-accent);
  padding: 10px 14px;
  text-align: left;
  font-weight: 700;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: .05em;
  border-bottom: 2px solid var(--clr-border);
  white-space: nowrap;
}
.compare-table th:not(:first-child) { text-align: right; }
.compare-table td {
  padding: 9px 14px;
  border-bottom: 1px solid var(--clr-border);
  color: var(--clr-fg);
}
.compare-table td:not(:first-child) { text-align: right; }
.compare-table tr:last-child td { border-bottom: none; }
.compare-table tr:hover td { background: rgba(99,102,241,.04); }
.compare-table .row-label { font-weight: 600; color: var(--clr-muted); font-size: 0.8rem; }

/* ── Footer ────────────────────────────────────────────────────── */
.report-footer {
  margin-top: 60px;
  padding: 20px 40px;
  border-top: 1px solid var(--clr-border);
  font-size: 0.75rem;
  color: var(--clr-muted);
  text-align: center;
}

/* ── Responsive ────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .report-header { padding: 16px 20px; }
  .container { padding: 20px 16px 0; }
  .hero-card { padding: 20px; }
  .card-grid, .card-grid.wide { grid-template-columns: 1fr; }
  .hero-left h2 { font-size: 1.6rem; }
  .hero-price { font-size: 1.4rem; }
}
"""

# ---------------------------------------------------------------------------
# Minimal JS: tab switching only
# ---------------------------------------------------------------------------
_JS = """
function showTicker(id) {
  document.querySelectorAll('.ticker-section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.ticker-pill').forEach(p => p.classList.remove('active'));
  const sec = document.getElementById('sec-' + id);
  const pill = document.getElementById('pill-' + id);
  if (sec) sec.classList.add('active');
  if (pill) pill.classList.add('active');
}
document.addEventListener('DOMContentLoaded', function() {
  const first = document.querySelector('.ticker-pill');
  if (first) first.click();
});

// ── Tooltip system ──────────────────────────────────────────────────────────
(function() {
  const tt = document.getElementById('_tt');
  let cur = null;
  document.addEventListener('mouseover', function(e) {
    const el = e.target.closest('[data-tip]');
    if (!el) return;
    cur = el;
    tt.textContent = el.dataset.tip;
    tt.style.display = 'block';
    _positionTip(e);
  });
  document.addEventListener('mousemove', function(e) {
    if (!cur) return;
    _positionTip(e);
  });
  document.addEventListener('mouseout', function(e) {
    const el = e.target.closest('[data-tip]');
    if (!el) return;
    if (!e.relatedTarget || !e.relatedTarget.closest('[data-tip]')) {
      tt.style.display = 'none';
      cur = null;
    }
  });
  function _positionTip(e) {
    const pad = 14, vpw = window.innerWidth, vph = window.innerHeight;
    const tw = tt.offsetWidth, th = tt.offsetHeight;
    let x = e.clientX + pad;
    let y = e.clientY - th - pad;
    if (x + tw > vpw - 8) x = e.clientX - tw - pad;
    if (y < 8) y = e.clientY + pad;
    tt.style.left = x + 'px';
    tt.style.top  = y + 'px';
  }
})();
"""


# ---------------------------------------------------------------------------
# SVG bar chart (shared: owner earnings trend + ETF holdings weight)
# ---------------------------------------------------------------------------
def _bar_chart_svg(labels: list, values: list[float], value_fmt=None) -> str:
    """Generate a pure-SVG horizontal bar chart.

    value_fmt formats each value for the trailing label; defaults to the
    existing large-number ($1.23B) formatting. Bars are green for values >= 0
    and red for negative values — for all-positive series (e.g. holding
    weights) this naturally renders every bar green with no special-casing.
    """
    if not labels or not values:
        return ""
    if value_fmt is None:
        value_fmt = lambda v: _fmt_large(v).replace('<span class="na">', "").replace("</span>", "")

    max_abs = max(abs(v) for v in values) if values else 1
    if max_abs == 0:
        max_abs = 1

    # Chart dimensions
    bar_height = 28
    gap = 10
    label_w = 50
    val_label_w = 80
    chart_w = 380
    bar_area_w = chart_w - label_w - val_label_w
    n = len(values)
    svg_h = n * (bar_height + gap) + 20

    bars = []
    for i, (val, lbl) in enumerate(zip(values, labels)):
        y_pos = i * (bar_height + gap) + 10
        ratio = val / max_abs  # -1..1
        bar_w = abs(ratio) * bar_area_w * 0.88
        bar_x = label_w
        color = "#22c55e" if val >= 0 else "#ef4444"

        val_text = value_fmt(val)

        bars.append(
            f'<text x="{label_w - 6}" y="{y_pos + bar_height / 2 + 4}" '
            f'class="chart-label" text-anchor="end">{html.escape(str(lbl))}</text>'
        )
        bars.append(
            f'<rect class="sparkline-bar" x="{bar_x}" y="{y_pos}" '
            f'width="{bar_w:.1f}" height="{bar_height}" rx="4" fill="{color}" opacity="0.85"/>'
        )
        bars.append(
            f'<text x="{bar_x + bar_w + 6}" y="{y_pos + bar_height / 2 + 4}" '
            f'class="chart-value-label" fill="{color}">{html.escape(val_text)}</text>'
        )

    return (
        f'<svg width="{chart_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(bars)
        + "</svg>"
    )


# ---------------------------------------------------------------------------
# Section builders — one function per snapshot type
# ---------------------------------------------------------------------------

def _render_fundamental_section(snap: FundamentalSnapshot) -> str:
    scores = score_ticker(snap)

    def _mv(attr: str, fmt: str, prefix: str = "", suffix: str = "") -> str:
        val = getattr(snap, attr, None)
        color_key = scores.get(attr, "white")
        css = _css_color(color_key)
        if val is None:
            return '<span class="na">N/A</span>'
        try:
            formatted = f"{prefix}{val:{fmt}}{suffix}" if fmt else f"{prefix}{val}{suffix}"
            return f'<span style="color:{css}">{html.escape(formatted)}</span>'
        except (ValueError, TypeError):
            return '<span class="na">N/A</span>'

    def _badge_score(attr: str, text: str) -> str:
        color = scores.get(attr, "white")
        return _badge(text, color)

    # ── Valuation Ratios card ──────────────────────────────────────────────
    pe_badge = _badge_score("pe_ratio", f"{snap.pe_ratio:.1f}x" if snap.pe_ratio is not None else "N/A")
    fpe_badge = _badge_score("forward_pe", f"{snap.forward_pe:.1f}x" if snap.forward_pe is not None else "N/A")
    pb_badge = _badge_score("price_to_book", f"{snap.price_to_book:.2f}x" if snap.price_to_book is not None else "N/A")

    # ── Growth Metrics card ────────────────────────────────────────────────
    eps_growth_disp = f"{snap.eps_growth:.1%}" if snap.eps_growth is not None else "N/A"
    rev_growth_disp = f"{snap.revenue_growth:.1%}" if snap.revenue_growth is not None else "N/A"
    margin_disp = f"{snap.profit_margin:.1%}" if snap.profit_margin is not None else "N/A"

    # ── Financial Health card ──────────────────────────────────────────────
    roe_disp = f"{snap.roe:.1%}" if snap.roe is not None else "N/A"
    debt_disp = f"{snap.debt_to_equity:.1f}" if snap.debt_to_equity is not None else "N/A"

    # ── Price Range card ───────────────────────────────────────────────────
    div_disp = f"{snap.div_yield:.2f}%" if snap.div_yield is not None else "N/A"
    hi52 = f"${snap.week_52_high:.2f}" if snap.week_52_high is not None else "N/A"
    lo52 = f"${snap.week_52_low:.2f}" if snap.week_52_low is not None else "N/A"
    eps_disp = f"${snap.eps:.2f}" if snap.eps is not None else "N/A"

    # horizon return
    hor_color = _css_color(scores.get("horizon_return_pct", "white"))
    hor_sign = "+" if (snap.horizon_return_pct or 0) >= 0 else ""
    hor_disp = (
        f'<span style="color:{hor_color}">{hor_sign}{snap.horizon_return_pct:.2f}%</span>'
        if snap.horizon_return_pct is not None
        else '<span class="na">N/A</span>'
    )

    return f"""
<div class="card-grid">
  <!-- Valuation Ratios -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📊</span>Valuation Ratios</div>
    {_tr("P/E Trailing",    pe_badge,                                    _TIPS["pe_trailing"])}
    {_tr("P/E Forward",     fpe_badge,                                   _TIPS["pe_forward"])}
    {_tr("Price / Book",    pb_badge,                                    _TIPS["price_book"])}
    {_tr("EPS (Trailing)",  _badge_score("eps", eps_disp),               _TIPS["eps"])}
    {_tr("Dividend Yield",  _badge("div","white") if snap.div_yield is None else div_disp, _TIPS["div_yield"])}
  </div>

  <!-- Growth Metrics -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📈</span>Growth Metrics</div>
    {_tr("EPS Growth",      _badge(eps_growth_disp, scores.get("eps_growth","white")),   _TIPS["eps_growth"])}
    {_tr("Revenue Growth",  _badge(rev_growth_disp, scores.get("revenue_growth","white")), _TIPS["rev_growth"])}
    {_tr("Profit Margin",   _badge(margin_disp, scores.get("profit_margin","white")),    _TIPS["profit_margin"])}
    {_tr("Return on Equity",_badge(roe_disp, scores.get("roe","white")),                 _TIPS["roe"])}
  </div>

  <!-- Financial Health -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🏦</span>Financial Health</div>
    {_tr("Debt / Equity",   _badge(debt_disp, scores.get("debt_to_equity","white")),     _TIPS["debt_equity"])}
    {_tr("52-Week High",    hi52,                                                         _TIPS["hi52"])}
    {_tr("52-Week Low",     lo52,                                                         _TIPS["lo52"])}
    {_tr("Horizon Return",  hor_disp,                                                     _TIPS["horizon_return"])}
  </div>
</div>
"""


def _render_dcf_card(snap: "ValuationSnapshot") -> str:
    """Render the DCF Intrinsic Value card for the HTML report."""
    if snap.dcf_owner_earnings is None:
        return """
<div class="card" style="margin-bottom:24px">
  <div class="card-title"><span class="card-icon">🧮</span>Intrinsic Value — DCF (Buffett Owner Earnings)</div>
  <p style="color:var(--clr-muted); font-size:.85rem">
    Insufficient data for DCF calculation (need revenue estimate + profit margin, or positive FCF).
  </p>
</div>"""

    color_map = {"green": "var(--clr-green)", "yellow": "var(--clr-yellow)", "red": "var(--clr-red)"}
    mos = snap.margin_of_safety_pct
    mos_css = color_map.get(snap.iv_rating_color or "", "var(--clr-muted)")
    mos_str = f"{'+' if (mos or 0) >= 0 else ''}{mos:.1f}%" if mos is not None else "N/A"
    rating_str = html.escape(snap.iv_rating or "N/A")
    iv_str = f"${snap.intrinsic_value_per_share:.2f}" if snap.intrinsic_value_per_share else "N/A"
    price_str = f"${snap.current_price:.2f}" if snap.current_price else "N/A"
    growth_str = f"{snap.dcf_growth_rate:.1%}" if snap.dcf_growth_rate is not None else "N/A"
    growth_note = html.escape(snap.dcf_growth_note or "")
    oe_note = html.escape(snap.dcf_owner_earnings_note or "")

    return f"""
<div class="card" style="margin-bottom:24px">
  <div class="card-title"><span class="card-icon">🧮</span>Intrinsic Value — DCF (Buffett Owner Earnings Method)</div>
  <p style="font-size:.8rem; color:var(--clr-muted); margin-bottom:14px">
    10-year discounted Owner Earnings model. Discount rate: {snap.dcf_discount_rate:.0%} · Terminal growth: {snap.dcf_terminal_growth:.1%}
  </p>
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:0 24px">
    <div>
      {_tr("Normalized Net Income", _fmt_large(snap.dcf_net_income), _TIPS["dcf_ni"])}
      {_tr("Owner Earnings", f'<span class="text-accent">{_fmt_large(snap.dcf_owner_earnings)}</span>', _TIPS["dcf_oe"])}
      <div style="font-size:.72rem; color:var(--clr-muted); margin-bottom:10px; padding-left:2px">↳ {oe_note}</div>
      {_tr("Growth Rate (10yr)", f'<span class="text-yellow">{growth_str}</span>', _TIPS["dcf_growth"])}
      <div style="font-size:.72rem; color:var(--clr-muted); margin-bottom:10px; padding-left:2px">↳ {growth_note}</div>
      {_tr("Discount Rate", f'{snap.dcf_discount_rate:.0%}', _TIPS["dcf_discount"])}
      {_tr("Terminal Growth", f'{snap.dcf_terminal_growth:.1%}', _TIPS["dcf_terminal"])}
      {_tr("Enterprise Value", _fmt_large(snap.dcf_enterprise_value), _TIPS["dcf_ev"])}
      {_tr("Equity Value (+ cash − debt)", _fmt_large(snap.dcf_equity_value), _TIPS["dcf_equity"])}
    </div>
    <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; border-left:1px solid var(--clr-border); padding-left:24px">
      <div class="has-tip" data-tip="{html.escape(_TIPS["dcf_iv"])}" style="cursor:help">
        <div style="font-size:.72rem; color:var(--clr-muted); text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">Intrinsic Value / Share</div>
        <div style="font-size:2rem; font-weight:800; color:var(--clr-accent)">{iv_str}</div>
        <div style="font-size:.8rem; color:var(--clr-muted); margin:4px 0">vs Current Price {price_str}</div>
      </div>
      <div class="has-tip" data-tip="{html.escape(_TIPS["dcf_mos"])}" style="margin-top:16px; cursor:help">
        <div style="font-size:.72rem; color:var(--clr-muted); text-transform:uppercase; letter-spacing:.07em">Margin of Safety</div>
        <div style="font-size:1.6rem; font-weight:800; color:{mos_css}">{mos_str}</div>
        <div style="margin-top:12px; font-size:1rem; font-weight:700; color:{mos_css}">{rating_str}</div>
      </div>
    </div>
  </div>
</div>"""


def _render_valuation_section(snap: "ValuationSnapshot") -> str:
    # PE category
    pe_label, pe_color_name = pe_category(snap.pe_ratio)
    pe_color_map = {"green": "var(--clr-green)", "yellow": "var(--clr-yellow)", "red": "var(--clr-red)"}
    pe_css = pe_color_map.get(pe_color_name, "var(--clr-fg)")

    # Cash/Debt
    cash_rating, cash_rating_color = cash_debt_rating(snap.total_cash, snap.total_debt)
    net_cash = None
    if snap.total_cash is not None and snap.total_debt is not None:
        net_cash = snap.total_cash - snap.total_debt
    net_cash_color = "var(--clr-green)" if (net_cash or 0) >= 0 else "var(--clr-red)"

    # Debt/Assets
    da_pct = snap.debt_to_assets_pct
    da_label = "N/A"
    da_css = "var(--clr-muted)"
    if da_pct is not None:
        if da_pct < 40:
            da_label, da_css = "LOW LEVERAGE", "var(--clr-green)"
        elif da_pct < 65:
            da_label, da_css = "MODERATE", "var(--clr-yellow)"
        else:
            da_label, da_css = "HIGH LEVERAGE", "var(--clr-red)"

    # Liquidity
    cr = snap.current_ratio
    cr_css = "var(--clr-green)" if (cr or 0) >= 1.5 else ("var(--clr-yellow)" if (cr or 0) >= 1 else "var(--clr-red)")
    qr = snap.quick_ratio
    qr_css = "var(--clr-green)" if (qr or 0) >= 1 else ("var(--clr-yellow)" if (qr or 0) >= 0.7 else "var(--clr-red)")

    # Analyst targets
    rec = (snap.recommendation_key or "N/A").replace("_", " ").title()
    rec_key = snap.recommendation_key or ""
    rec_css = (
        "var(--clr-green)" if "buy" in rec_key.lower()
        else "var(--clr-red)" if "sell" in rec_key.lower()
        else "var(--clr-yellow)"
    )
    upside_css = "var(--clr-green)" if (snap.analyst_upside_pct or 0) > 0 else "var(--clr-red)"

    # Projection verdict
    ret = snap.possible_return_pct
    ret_verdict = "N/A"
    ret_css = "var(--clr-muted)"
    if ret is not None:
        if ret >= 50:
            ret_verdict, ret_css = "Strong opportunity", "var(--clr-green)"
        elif ret >= 15:
            ret_verdict, ret_css = "Moderate upside", "var(--clr-yellow)"
        elif ret >= 0:
            ret_verdict, ret_css = "Limited upside", "var(--clr-muted)"
        else:
            ret_verdict, ret_css = "Projected downside", "var(--clr-red)"

    margin_css = "var(--clr-green)" if (snap.profit_margin or 0) > 0.20 else ("var(--clr-yellow)" if (snap.profit_margin or 0) > 0.05 else "var(--clr-red)")
    margin_label = "STRONG" if (snap.profit_margin or 0) > 0.20 else ("MODERATE" if (snap.profit_margin or 0) > 0.05 else "THIN")

    # Projection flow
    proj_flow = ""
    if snap.next_year_revenue_est and snap.profit_margin and snap.projected_earnings and snap.future_market_cap:
        proj_flow = f"""
<div class="projection-flow">
  <div class="proj-step">
    <div class="step-label">Revenue Est.</div>
    <div class="step-val">{_fmt_large(snap.next_year_revenue_est)}</div>
  </div>
  <span class="proj-arrow">×</span>
  <div class="proj-step">
    <div class="step-label">Profit Margin</div>
    <div class="step-val">{snap.profit_margin:.1%}</div>
  </div>
  <span class="proj-arrow">=</span>
  <div class="proj-step">
    <div class="step-label">Proj. Earnings</div>
    <div class="step-val" style="color:var(--clr-green)">{_fmt_large(snap.projected_earnings)}</div>
  </div>
  <span class="proj-arrow">×</span>
  <div class="proj-step">
    <div class="step-label">Avg PE (6m)</div>
    <div class="step-val">{snap.avg_pe_6m:.1f}x</div>
  </div>
  <span class="proj-arrow">=</span>
  <div class="proj-step">
    <div class="step-label">Future Mkt Cap</div>
    <div class="step-val" style="color:var(--clr-accent)">{_fmt_large(snap.future_market_cap)}</div>
  </div>
</div>
"""

    ret_disp = (
        f'<span style="color:{ret_css}; font-size:1.6rem; font-weight:800">'
        + (f"{'+' if (ret or 0) >= 0 else ''}{ret:.1f}%" if ret is not None else "N/A")
        + f'</span><div style="color:{ret_css}; font-size:0.8rem; margin-top:4px">{ret_verdict}</div>'
    )

    pe_val_html = f'<span style="color:{pe_css}">{snap.pe_ratio:.1f}x</span>' if snap.pe_ratio is not None else '<span class="na">N/A</span>'
    avg_pe_html = (f'<span class="text-yellow">{snap.avg_pe_6m:.1f}x</span><span class="text-muted" style="font-size:.72rem"> ← projection</span>' if snap.avg_pe_6m is not None else '<span class="na">N/A</span>')
    inv_profile_html = f'<span style="color:{pe_css}; font-size:.78rem">{html.escape(pe_label)}</span>'
    net_cash_html = f'<span style="color:{net_cash_color}">{_fmt_large(net_cash)}</span>' if net_cash is not None else '<span class="na">N/A</span>'
    da_html = f'<span style="color:{da_css}">{da_pct:.1f}%</span> <span class="badge" style="color:{da_css}">{da_label}</span>' if da_pct is not None else '<span class="na">N/A</span>'
    margin_html = f'<span style="color:{margin_css}">{snap.profit_margin:.2%}</span>&nbsp;<span class="badge" style="color:{margin_css}">{margin_label}</span>' if snap.profit_margin is not None else '<span class="na">N/A</span>'
    upside_html = f'<span style="color:{upside_css}">{("+" if (snap.analyst_upside_pct or 0) >= 0 else "")}{snap.analyst_upside_pct:.1f}%</span>' if snap.analyst_upside_pct is not None else '<span class="na">N/A</span>'

    return f"""
<div class="card-grid wide">
  <!-- PE & Profile -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📊</span>PE Ratio &amp; Investor Profile</div>
    {_tr("Trailing P/E",      pe_val_html,   _TIPS["pe_trailing"])}
    {_tr("6-Month Avg P/E",   avg_pe_html,   _TIPS["avg_pe_6m"])}
    {_tr("Investor Profile",  inv_profile_html, _TIPS["inv_profile"])}
  </div>

  <!-- Cash & Debt -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🏦</span>Cash &amp; Debt Health</div>
    {_tr("Total Cash",    _fmt_large(snap.total_cash),                  _TIPS["total_cash"])}
    {_tr("Total Debt",    _fmt_large(snap.total_debt),                  _TIPS["total_debt"])}
    {_tr("Net Cash",      net_cash_html,                                _TIPS["net_cash"])}
    {_tr("Debt / Assets", da_html,                                      _TIPS["debt_assets"])}
    {_tr("Current Ratio", f'<span style="color:{cr_css}">{cr:.2f}x</span>' if cr is not None else '<span class="na">N/A</span>', _TIPS["current_ratio"])}
    {_tr("Quick Ratio",   f'<span style="color:{qr_css}">{qr:.2f}x</span>' if qr is not None else '<span class="na">N/A</span>', _TIPS["quick_ratio"])}
  </div>

  <!-- Profitability -->
  <div class="card">
    <div class="card-title"><span class="card-icon">💰</span>Profitability</div>
    {_tr("Profit Margin",        margin_html,                       _TIPS["profit_margin"])}
    {_tr("Revenue Est. (next yr)",_fmt_large(snap.next_year_revenue_est), _TIPS["rev_est"])}
    {_tr("Market Cap",           _fmt_large(snap.market_cap),       _TIPS["market_cap"])}
    {_tr("EPS (Trailing)",       f"${snap.eps:.2f}" if snap.eps is not None else '<span class="na">N/A</span>', _TIPS["eps_val"])}
  </div>

  <!-- Analyst Targets -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🎯</span>Analyst Price Targets</div>
    {_tr("Low Target",   f'<span class="text-red">${snap.analyst_target_low:.2f}</span>' if snap.analyst_target_low is not None else '<span class="na">N/A</span>',   _TIPS["analyst_low"])}
    {_tr("Mean Target",  f'${snap.analyst_target_mean:.2f}' if snap.analyst_target_mean is not None else '<span class="na">N/A</span>',                                _TIPS["analyst_mean"])}
    {_tr("High Target",  f'<span class="text-green">${snap.analyst_target_high:.2f}</span>' if snap.analyst_target_high is not None else '<span class="na">N/A</span>', _TIPS["analyst_high"])}
    {_tr("Upside",       upside_html,                                                                                                                                    _TIPS["analyst_upside"])}
    {_tr("Consensus",    f'<span style="color:{rec_css}; font-weight:700">{html.escape(rec)}</span>',                                                                   _TIPS["consensus"])}
    {_tr("# Analysts",   str(snap.num_analysts) if snap.num_analysts is not None else '<span class="na">N/A</span>',                                                    _TIPS["num_analysts"])}
  </div>
</div>

<!-- Valuation Projection -->
<div class="card" style="margin-bottom:24px">
  <div class="card-title"><span class="card-icon">🔮</span>Valuation Projection (5+ Year View)</div>
  <p style="font-size:.8rem; color:var(--clr-muted); margin-bottom:10px">
    Projected Earnings = Revenue Est. × Margin → Future Market Cap = Earnings × Avg P/E → Possible Return vs today
  </p>
  {proj_flow}
  <div style="margin-top:16px; text-align:center" data-tip="{html.escape(_TIPS["possible_return"])}" class="has-tip" style="cursor:help">
    <div style="font-size:.72rem; color:var(--clr-muted); text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">Possible Return</div>
    {ret_disp}
    <div style="font-size:.75rem; color:var(--clr-muted); margin-top:8px">
      Current Mkt Cap: {_fmt_large(snap.market_cap)}
    </div>
  </div>
</div>

{_render_dcf_card(snap)}
"""


def _render_etf_valuation_section(snap: ETFValuationSnapshot) -> str:
    pegy_css = _css_color(snap.pegy_color or "")
    rating_css = _css_color(snap.rating_color or "")
    conc_css = _css_color(
        "green" if (snap.concentration_pct or 0) < 40
        else "yellow" if (snap.concentration_pct or 0) < 60
        else "red"
    ) if snap.concentration_pct is not None else "var(--clr-muted)"

    labels = [h.symbol for h in (snap.holdings or [])]
    values = [h.weight_pct for h in (snap.holdings or [])]
    holdings_svg = _bar_chart_svg(labels, values, value_fmt=lambda v: f"{v:.1f}%")

    holdings_rows = "".join(
        f'<tr><td>{html.escape(h.symbol)}</td><td>{html.escape(h.name or "N/A")}</td>'
        f'<td style="text-align:right">{h.weight_pct:.2f}%</td>'
        f'<td style="text-align:right">{f"{h.trailing_pe:.1f}x" if h.trailing_pe else "N/A"}</td></tr>'
        for h in (snap.holdings or [])
    )

    pegy_html = f'<span style="color:{pegy_css}">{snap.pegy_ratio:.2f}x</span> <span class="badge" style="color:{pegy_css}">{html.escape(snap.pegy_label or "N/A")}</span>' if snap.pegy_ratio is not None else '<span class="na">N/A</span>'
    conc_html = f'<span style="color:{conc_css}">{snap.concentration_pct:.1f}%</span>' if snap.concentration_pct is not None else '<span class="na">N/A</span>'
    growth_html = f'{snap.forward_eps_growth_pct:+.1f}%' if snap.forward_eps_growth_pct is not None else '<span class="na">N/A</span>'
    trailing_pe_html = f'{snap.trailing_pe:.1f}x <span class="text-muted" style="font-size:.72rem">({"basket" if snap.trailing_pe_source == "etf_info" else "weighted holdings"})</span>' if snap.trailing_pe is not None else '<span class="na">N/A</span>'

    fair_value_html = f'${snap.fair_value:.2f}' if snap.fair_value is not None else '<span class="na">N/A</span>'
    hist_pe_html = f'{snap.hist_5y_avg_pe:.1f}x' if snap.hist_5y_avg_pe is not None else '<span class="na">N/A</span>'

    if snap.tier1_entry is not None and snap.tier2_entry is not None:
        lo, hi = sorted([snap.tier1_entry, snap.tier2_entry])
        entry_html = f'${lo:.2f} &ndash; ${hi:.2f}'
    elif snap.tier1_entry is not None:
        entry_html = f'${snap.tier1_entry:.2f} <span class="text-muted" style="font-size:.72rem">(tier 2 unavailable)</span>'
    elif snap.tier2_entry is not None:
        entry_html = f'${snap.tier2_entry:.2f} <span class="text-muted" style="font-size:.72rem">(tier 1 unavailable)</span>'
    else:
        entry_html = '<span class="na">N/A</span>'

    mos = snap.margin_of_safety_pct
    mos_css = "var(--clr-green)" if (mos or -99) > 25 else ("var(--clr-yellow)" if (mos or -99) > 5 else "var(--clr-red)")
    mos_str = f"{'+' if (mos or 0) >= 0 else ''}{mos:.1f}%" if mos is not None else "N/A"

    ret = snap.total_return_pct
    ret_css = "var(--clr-green)" if (ret or -99) >= 50 else ("var(--clr-yellow)" if (ret or -99) >= 15 else ("var(--clr-fg)" if (ret or -99) >= 0 else "var(--clr-red)"))
    ret_str = f"{'+' if (ret or 0) >= 0 else ''}{ret:.1f}%" if ret is not None else "N/A"
    cagr_str = f"{snap.cagr_pct:+.1f}%" if snap.cagr_pct is not None else "N/A"

    return f"""
<div class="card-grid wide">
  <!-- Concentration & Top Holdings -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🧺</span>Basket Concentration &amp; Top Holdings</div>
    {_tr("Top 10 Weight", conc_html, _TIPS["etf_concentration"])}
    <table style="width:100%; font-size:.78rem; margin-top:10px; border-collapse:collapse">
      <thead><tr style="color:var(--clr-muted); text-align:left">
        <th>Symbol</th><th>Name</th><th style="text-align:right">Weight</th><th style="text-align:right">P/E</th>
      </tr></thead>
      <tbody>{holdings_rows}</tbody>
    </table>
    <div class="chart-wrap">{holdings_svg}</div>
  </div>

  <!-- Valuation Multiples & PEGY -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📊</span>Valuation Multiples &amp; PEGY</div>
    {_tr("Trailing P/E", trailing_pe_html, _TIPS["etf_trailing_pe"])}
    {_tr("Forward EPS Growth", growth_html, _TIPS["etf_growth"])}
    {_tr("Distribution Yield", f"{snap.distribution_yield_pct:.2f}%" if snap.distribution_yield_pct is not None else '<span class="na">N/A</span>', _TIPS["etf_yield"])}
    {_tr("PEGY Ratio", pegy_html, _TIPS["etf_pegy"])}
    <p style="font-size:.72rem; color:var(--clr-muted); margin-top:6px">↳ {html.escape(snap.holdings_pe_coverage_note or "")}</p>
  </div>

  <!-- Historical Valuation Bands & NAV -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📈</span>Historical Valuation Bands &amp; NAV</div>
    {_tr("5Y Avg P/E", hist_pe_html, _TIPS["etf_hist_pe"])}
    <p style="font-size:.72rem; color:var(--clr-muted); margin-bottom:6px">↳ {html.escape(snap.hist_pe_note or "")}</p>
    {_tr("Fair Value", fair_value_html, _TIPS["etf_fair_value"])}
    {_tr("Entry Zone", entry_html, _TIPS["etf_entry_zone"])}
  </div>
</div>

<!-- Valuation Projection -->
<div class="card" style="margin-bottom:24px">
  <div class="card-title"><span class="card-icon">🔮</span>Valuation Projection (5-Year Growth View)</div>
  <p style="font-size:.8rem; color:var(--clr-muted); margin-bottom:10px">
    Projected EPS = Current EPS-equivalent × (1 + growth)^5 &nbsp;&middot;&nbsp; Projected Price = Projected EPS × Terminal P/E (5Y avg)
  </p>
  <div style="text-align:center" data-tip="{html.escape(_TIPS["etf_projection"])}" class="has-tip" style="cursor:help">
    <div style="font-size:.72rem; color:var(--clr-muted); text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">5-Year Possible Return</div>
    <span style="color:{ret_css}; font-size:1.6rem; font-weight:800">{ret_str}</span>
    <div style="color:{ret_css}; font-size:0.8rem; margin-top:4px">{cagr_str} CAGR</div>
  </div>
</div>

<!-- Entry Strategy & Margin of Safety -->
<div class="card" style="margin-bottom:24px">
  <div class="card-title"><span class="card-icon">🎯</span>Entry Strategy &amp; Margin of Safety</div>
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:0 24px">
    <div>
      {_tr("Margin of Safety", f'<span style="color:{mos_css}">{mos_str}</span>', _TIPS["etf_mos"])}
      {_tr("Tier 1 (DCA Pullback)", f"${snap.tier1_entry:.2f}" if snap.tier1_entry is not None else '<span class="na">N/A</span>', "min(50-day EMA, price × 0.95)")}
      {_tr("Tier 2 (Valuation Reversion)", f"${snap.tier2_entry:.2f}" if snap.tier2_entry is not None else '<span class="na">N/A</span>', "min(fair value, 200-day SMA)")}
    </div>
    <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; border-left:1px solid var(--clr-border); padding-left:24px">
      <div style="font-size:.72rem; color:var(--clr-muted); text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">Rating</div>
      <div style="font-size:1.3rem; font-weight:800; color:{rating_css}">{html.escape(snap.rating or "N/A")}</div>
    </div>
  </div>
</div>
"""


def _render_owner_earnings_section(snap: OwnerEarningsSnapshot) -> str:
    # OE vs Net Income
    oe_vs_ni = snap.oe_vs_net_income_pct
    oe_vs_css = (
        "var(--clr-green)" if (oe_vs_ni or 0) > 10
        else "var(--clr-yellow)" if (oe_vs_ni or -99) >= -10
        else "var(--clr-red)"
    )

    # OE Yield
    oe_yield = snap.oe_yield_pct
    yield_css = (
        "var(--clr-green)" if (oe_yield or 0) >= 8
        else "var(--clr-yellow)" if (oe_yield or 0) >= 4
        else "var(--clr-red)"
    )
    yield_label = (
        "Excellent value" if (oe_yield or 0) >= 8
        else "Decent return" if (oe_yield or 0) >= 4
        else "Paying premium"
    )

    # Capital intensity
    cap_int = snap.capex_intensity_pct
    cap_css = (
        "var(--clr-green)" if (cap_int or 100) < 25
        else "var(--clr-yellow)" if (cap_int or 100) < 50
        else "var(--clr-red)"
    )
    cap_label = (
        "Cash cow" if (cap_int or 100) < 25
        else "Moderate spender" if (cap_int or 100) < 50
        else "Heavy spender"
    )

    # Trend
    trend = snap.trend_direction or "N/A"
    trend_css = {
        "GROWING": "var(--clr-green)",
        "STABLE": "var(--clr-yellow)",
        "DECLINING": "var(--clr-red)",
    }.get(trend, "var(--clr-muted)")

    _years = snap.years or []
    svg = _bar_chart_svg([y.year for y in _years], [y.owner_earnings for y in _years])

    oe_vs_html   = f'<span style="color:{oe_vs_css}">{("+" if (oe_vs_ni or 0) >= 0 else "")}{oe_vs_ni:.1f}%</span>' if oe_vs_ni is not None else '<span class="na">N/A</span>'
    yield_html   = f'<span style="color:{yield_css}">{oe_yield:.1f}%</span>' if oe_yield is not None else '<span class="na">N/A</span>'
    cap_int_html = f'<span style="color:{cap_css}">{cap_int:.1f}%</span>' if cap_int is not None else '<span class="na">N/A</span>'
    yoy_html     = f'<span>{("+" if (snap.oe_growth_pct or 0) >= 0 else "")}{snap.oe_growth_pct:.1f}%</span>' if snap.oe_growth_pct is not None else '<span class="na">N/A</span>'
    cagr_html    = f'<span>{snap.oe_cagr_pct:.1f}%</span>' if snap.oe_cagr_pct is not None else '<span class="na">N/A</span>'

    return f"""
<div class="card-grid">
  <!-- Formula Breakdown -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🧮</span>Formula Breakdown</div>
    {_tr("Net Income",          _fmt_large(snap.net_income),                         _TIPS["oe_net_income"])}
    {_tr("+ Depreciation",      _fmt_large(snap.depreciation),                       _TIPS["oe_depreciation"])}
    {_tr("− CapEx",             f'<span class="text-red">{_fmt_large(snap.capex)}</span>', _TIPS["oe_capex"])}
    {_tr("− Working Capital Δ", _fmt_large(snap.working_capital_change),              _TIPS["oe_wc"])}
    {_tr("Owner Earnings",      f'<span class="text-green" style="font-size:1rem;font-weight:800">{_fmt_large(snap.owner_earnings)}</span>', _TIPS["oe_total"], "border-top:2px solid var(--clr-border);margin-top:4px;padding-top:8px")}
    {_tr("Per Share",           f'${snap.oe_per_share:.2f}' if snap.oe_per_share is not None else '<span class="na">N/A</span>', _TIPS["oe_per_share"])}
  </div>

  <!-- Reality Check & Yield -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🔍</span>Reality Check &amp; Yield</div>
    {_tr("OE vs Net Income", oe_vs_html,   _TIPS["oe_vs_ni"])}
    <p class="metric-hint">
      {"> +10%: earns more cash than it reports" if (oe_vs_ni or 0) > 10 else ("< -10%: reported profits are overstated" if (oe_vs_ni or -99) < -10 else "Profits match cash generation")}
    </p>
    {_tr("OE Yield",         yield_html,   _TIPS["oe_yield"],    "margin-top:10px")}
    <p class="metric-hint">{yield_label}</p>
    {_tr("Capital Intensity",cap_int_html, _TIPS["cap_intensity"],"margin-top:10px")}
    <p class="metric-hint">{cap_label}</p>
  </div>

  <!-- Trend -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📅</span>Multi-Year Trend</div>
    <div class="big-metric has-tip" data-tip="{html.escape(_TIPS["oe_trend"])}" style="margin-bottom:12px;cursor:help">
      <div class="val" style="color:{trend_css}">{html.escape(trend)}</div>
    </div>
    {_tr("YoY Growth", yoy_html,  _TIPS["oe_yoy"])}
    {_tr("CAGR",       cagr_html, _TIPS["oe_cagr"])}
    <div class="chart-wrap">
      {svg}
    </div>
  </div>
</div>
"""


def _render_value_check_section(snap: ValueCheckSnapshot) -> str:
    def _vc_color(val: Optional[float], g: float, y: float) -> str:
        if val is None or val < 0:
            return "var(--clr-red)"
        if val < g:
            return "var(--clr-green)"
        if val <= y:
            return "var(--clr-yellow)"
        return "var(--clr-red)"

    pe_css = _vc_color(snap.pe_ratio, 15, 25)
    pb_css = _vc_color(snap.pb_ratio, 1.5, 3)
    pfcf_css = _vc_color(snap.pfcf_ratio, 15, 25)

    return f"""
<div class="card-grid">
  <div class="card">
    <div class="card-title"><span class="card-icon">💡</span>Quick Value Check</div>
    {_tr("P/E (Trailing)", f'<span style="color:{pe_css}">{snap.pe_ratio:.1f}x</span>' if snap.pe_ratio is not None else '<span class="na">N/A</span>', _TIPS["vc_pe"])}
    {_tr("Price / Book",   f'<span style="color:{pb_css}">{snap.pb_ratio:.1f}x</span>' if snap.pb_ratio is not None else '<span class="na">N/A</span>', _TIPS["vc_pb"])}
    {_tr("Price / FCF",    f'<span style="color:{pfcf_css}">{snap.pfcf_ratio:.1f}x</span>' if snap.pfcf_ratio is not None else '<span class="na">N/A</span>', _TIPS["vc_pfcf"])}
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Comparison table (multi-ticker, one type)
# ---------------------------------------------------------------------------

def _render_comparison_table(snapshots: list[AnySnapshot]) -> str:
    """Render a side-by-side comparison table for multiple tickers."""
    if len(snapshots) < 2:
        return ""

    tickers = [s.ticker for s in snapshots]
    header_cells = "".join(f"<th>{html.escape(t)}</th>" for t in tickers)

    # Determine what type of snapshots we have
    first = snapshots[0]

    if isinstance(first, FundamentalSnapshot):
        rows = [
            ("Sector", lambda s: getattr(s, "sector", None) or "N/A", None),
            ("Current Price", lambda s: f"${s.current_price:.2f}" if s.current_price else "N/A", None),
            ("P/E (Trailing)", lambda s: f"{s.pe_ratio:.1f}x" if s.pe_ratio is not None else "N/A",
             lambda s: _score_pe(s.pe_ratio)),
            ("P/E (Forward)", lambda s: f"{s.forward_pe:.1f}x" if s.forward_pe is not None else "N/A",
             lambda s: _score_pe(s.forward_pe)),
            ("EPS Growth", lambda s: f"{s.eps_growth:.1%}" if s.eps_growth is not None else "N/A",
             lambda s: _score_growth(s.eps_growth)),
            ("Revenue Growth", lambda s: f"{s.revenue_growth:.1%}" if s.revenue_growth is not None else "N/A",
             lambda s: _score_growth(s.revenue_growth)),
            ("Profit Margin", lambda s: f"{s.profit_margin:.1%}" if s.profit_margin is not None else "N/A",
             lambda s: _score_margin(s.profit_margin)),
            ("Debt / Equity", lambda s: f"{s.debt_to_equity:.1f}" if s.debt_to_equity is not None else "N/A",
             lambda s: _score_debt(s.debt_to_equity)),
            ("ROE", lambda s: f"{s.roe:.1%}" if s.roe is not None else "N/A",
             lambda s: _score_roe(s.roe)),
            ("Price / Book", lambda s: f"{s.price_to_book:.2f}x" if s.price_to_book is not None else "N/A",
             lambda s: _score_pb(s.price_to_book)),
            ("Horizon Return", lambda s: f"{'+' if (s.horizon_return_pct or 0) >= 0 else ''}{s.horizon_return_pct:.2f}%" if s.horizon_return_pct is not None else "N/A",
             lambda s: _score_return(s.horizon_return_pct)),
        ]

    elif isinstance(first, ValuationSnapshot):
        rows = [
            ("Current Price", lambda s: f"${s.current_price:.2f}" if s.current_price else "N/A", None),
            ("Market Cap", lambda s: _fmt_large(s.market_cap).replace('<span class="na">N/A</span>', "N/A"), None),
            ("P/E Trailing", lambda s: f"{s.pe_ratio:.1f}x" if s.pe_ratio is not None else "N/A",
             lambda s: _score_pe(s.pe_ratio)),
            ("6m Avg P/E", lambda s: f"{s.avg_pe_6m:.1f}x" if s.avg_pe_6m is not None else "N/A", None),
            ("Profit Margin", lambda s: f"{s.profit_margin:.2%}" if s.profit_margin is not None else "N/A",
             lambda s: _score_margin(s.profit_margin)),
            ("Net Cash", lambda s: _fmt_large((s.total_cash or 0) - (s.total_debt or 0)).replace('<span class="na">N/A</span>', "N/A") if s.total_cash is not None and s.total_debt is not None else "N/A", None),
            ("Debt/Assets", lambda s: f"{s.debt_to_assets_pct:.1f}%" if s.debt_to_assets_pct is not None else "N/A", None),
            ("Analyst Mean", lambda s: f"${s.analyst_target_mean:.2f}" if s.analyst_target_mean is not None else "N/A", None),
            ("Analyst Upside", lambda s: f"{'+' if (s.analyst_upside_pct or 0) >= 0 else ''}{s.analyst_upside_pct:.1f}%" if s.analyst_upside_pct is not None else "N/A", None),
            ("Possible Return", lambda s: f"{'+' if (s.possible_return_pct or 0) >= 0 else ''}{s.possible_return_pct:.1f}%" if s.possible_return_pct is not None else "N/A", None),
            ("Consensus", lambda s: (s.recommendation_key or "N/A").replace("_", " ").title(), None),
        ]

    elif isinstance(first, OwnerEarningsSnapshot):
        rows = [
            ("Owner Earnings", lambda s: _fmt_large(s.owner_earnings).replace('<span class="na">N/A</span>', "N/A"), None),
            ("OE per Share", lambda s: f"${s.oe_per_share:.2f}" if s.oe_per_share is not None else "N/A", None),
            ("OE Yield", lambda s: f"{s.oe_yield_pct:.1f}%" if s.oe_yield_pct is not None else "N/A", None),
            ("OE vs Net Inc.", lambda s: f"{'+' if (s.oe_vs_net_income_pct or 0) >= 0 else ''}{s.oe_vs_net_income_pct:.1f}%" if s.oe_vs_net_income_pct is not None else "N/A", None),
            ("CapEx Intensity", lambda s: f"{s.capex_intensity_pct:.1f}%" if s.capex_intensity_pct is not None else "N/A", None),
            ("YoY Growth", lambda s: f"{'+' if (s.oe_growth_pct or 0) >= 0 else ''}{s.oe_growth_pct:.1f}%" if s.oe_growth_pct is not None else "N/A", None),
            ("CAGR", lambda s: f"{s.oe_cagr_pct:.1f}%" if s.oe_cagr_pct is not None else "N/A", None),
            ("Trend", lambda s: s.trend_direction or "N/A", None),
        ]

    elif isinstance(first, ValueCheckSnapshot):
        rows = [
            ("Current Price", lambda s: f"${s.current_price:.2f}" if s.current_price else "N/A", None),
            ("P/E", lambda s: f"{s.pe_ratio:.1f}x" if s.pe_ratio is not None else "N/A",
             lambda s: _score_pe(s.pe_ratio)),
            ("P/B", lambda s: f"{s.pb_ratio:.1f}x" if s.pb_ratio is not None else "N/A",
             lambda s: _score_pb(s.pb_ratio)),
            ("P/FCF", lambda s: f"{s.pfcf_ratio:.1f}x" if s.pfcf_ratio is not None else "N/A", None),
        ]
    else:
        return ""

    row_html_parts = []
    for label, val_fn, color_fn in rows:
        cells = [f'<td class="row-label">{html.escape(label)}</td>']
        for snap in snapshots:
            raw = val_fn(snap)
            # Strip any residual html from _fmt_large
            clean = raw.replace('<span class="na">N/A</span>', "N/A")
            if color_fn:
                color = color_fn(snap)
                css = _css_color(color)
                cell = f'<td style="color:{css}">{html.escape(clean)}</td>'
            else:
                cell = f"<td>{html.escape(clean)}</td>"
            cells.append(cell)
        row_html_parts.append("<tr>" + "".join(cells) + "</tr>")

    rows_html = "\n".join(row_html_parts)
    return f"""
<h2 class="section-title">Side-by-Side Comparison</h2>
<div class="compare-wrap">
  <table class="compare-table">
    <thead><tr><th>Metric</th>{header_cells}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""


# ---------------------------------------------------------------------------
# Per-ticker HTML block
# ---------------------------------------------------------------------------

def _render_ticker_block(snap: AnySnapshot) -> str:
    ticker = snap.ticker
    sector = getattr(snap, "sector", None) or "Unknown"
    price = getattr(snap, "current_price", None)
    price_disp = f"${price:.2f}" if price is not None else "N/A"

    if isinstance(snap, FundamentalSnapshot):
        report_type = "Fundamental Analysis"
        content = _render_fundamental_section(snap)
    elif isinstance(snap, ValuationSnapshot):
        report_type = "Valuation Analysis"
        content = _render_valuation_section(snap)
    elif isinstance(snap, OwnerEarningsSnapshot):
        report_type = "Owner Earnings"
        content = _render_owner_earnings_section(snap)
    elif isinstance(snap, ValueCheckSnapshot):
        report_type = "Value Check"
        content = _render_value_check_section(snap)
    elif isinstance(snap, ETFValuationSnapshot):
        report_type = "ETF Valuation"
        content = _render_etf_valuation_section(snap)
    else:
        report_type = "Analysis"
        content = "<p>No data available.</p>"

    return f"""
<div class="hero-card">
  <div class="hero-left">
    <h2>{html.escape(ticker)}</h2>
    <div class="ticker-sub">{html.escape(sector)} &nbsp;·&nbsp; {html.escape(report_type)}</div>
  </div>
  <div class="hero-right">
    <div class="hero-price">{html.escape(price_disp)}</div>
    <div class="hero-price-sub">Current Price</div>
  </div>
</div>
{content}
"""


# ---------------------------------------------------------------------------
# Full document assembly
# ---------------------------------------------------------------------------

def _build_html(snapshots: list[AnySnapshot], generated_at: str) -> str:
    # Group snapshots by ticker to handle mixed types for the same ticker
    by_ticker: dict[str, list[AnySnapshot]] = {}
    for snap in snapshots:
        by_ticker.setdefault(snap.ticker, []).append(snap)

    tickers = list(by_ticker.keys())
    multi = len(tickers) > 1

    # Infer report title from snapshot types
    types_seen = {type(s).__name__ for s in snapshots}
    if "FundamentalSnapshot" in types_seen:
        title = "Fundamental Analysis"
    elif "ValuationSnapshot" in types_seen:
        title = "Valuation Analysis"
    elif "OwnerEarningsSnapshot" in types_seen:
        title = "Owner Earnings Report"
    elif "ValueCheckSnapshot" in types_seen:
        title = "Value Check"
    elif "ETFValuationSnapshot" in types_seen:
        title = "ETF Valuation Analysis"
    else:
        title = "Stock Analysis"

    ticker_summary = ", ".join(tickers)

    # Build tab pills
    pills_html = ""
    sections_html = ""

    if multi:
        pills_html = '<div class="ticker-nav">' + "".join(
            f'<span class="ticker-pill" id="pill-{html.escape(t)}" '
            f'onclick="showTicker(\'{html.escape(t)}\')">{html.escape(t)}</span>'
            for t in tickers
        ) + "</div>"

    for t in tickers:
        snaps = by_ticker[t]
        blocks = "".join(_render_ticker_block(s) for s in snaps)

        # Add comparison section only when viewing the first ticker and multiple tickers exist
        # (comparison is shown in a separate "compare" section below the ticker sections)
        section_class = "ticker-section" + (" active" if t == tickers[0] else "")
        sections_html += (
            f'<div class="{section_class}" id="sec-{html.escape(t)}">{blocks}</div>\n'
        )

    # Build comparison section (same type across tickers)
    comparison_html = ""
    if multi and len(set(type(s).__name__ for s in snapshots)) == 1:
        comparison_html = _render_comparison_table(snapshots)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)} — {html.escape(ticker_summary)}</title>
  <style>{_CSS}</style>
</head>
<body>

<header class="report-header">
  <h1>stock<span>tool</span> &mdash; {html.escape(title)}</h1>
  <div class="report-meta">
    Tickers: <strong>{html.escape(ticker_summary)}</strong>
    &nbsp;·&nbsp; Generated: {html.escape(generated_at)}
    &nbsp;·&nbsp; Powered by yfinance
  </div>
</header>

<div class="container">
  {pills_html}
  {sections_html}
  {comparison_html}
</div>

<footer class="report-footer">
  Generated by stocktool &nbsp;·&nbsp; Data from yfinance &nbsp;·&nbsp;
  Not financial advice. Do your own research.
</footer>

<div id="_tt"></div>
<script>{_JS}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_html_report(
    snapshots: list[AnySnapshot],
    output_path: Optional[str] = None,
    open_browser: bool = True,
) -> str:
    """Generate a self-contained HTML report from one or more analysis snapshots.

    Parameters
    ----------
    snapshots:
        List of any combination of FundamentalSnapshot, ValuationSnapshot,
        OwnerEarningsSnapshot, ValueCheckSnapshot.
    output_path:
        Where to write the HTML file. Defaults to
        ~/.config/stocktool/report_<TICKERS>_<DATE>.html
    open_browser:
        If True, open the file in the default web browser after writing.

    Returns
    -------
    str
        Absolute path to the generated HTML file.
    """
    if not snapshots:
        raise ValueError("generate_html_report: snapshots list is empty")

    from .config import ensure_config_dir, CONFIG_DIR

    ensure_config_dir()

    if output_path is None:
        tickers_slug = "_".join(s.ticker for s in snapshots[:4])
        date_slug = datetime.now().strftime("%Y%m%d")
        output_path = str(pathlib.Path(CONFIG_DIR) / f"report_{tickers_slug}_{date_slug}.html")

    generated_at = datetime.now().strftime("%B %d, %Y at %H:%M")
    html_content = _build_html(snapshots, generated_at)

    path = pathlib.Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_content, encoding="utf-8")

    if open_browser:
        webbrowser.open(path.as_uri())

    return str(path)
