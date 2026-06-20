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
.ticker-section.active { display: block; }

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
"""


# ---------------------------------------------------------------------------
# SVG bar chart for owner earnings trend
# ---------------------------------------------------------------------------
def _owner_earnings_svg(years_data: list) -> str:
    """Generate a pure-SVG horizontal bar chart for owner earnings trend.

    years_data is a list of OwnerEarningsYear sorted newest-first.
    """
    if not years_data:
        return ""

    values = [y.owner_earnings for y in years_data]
    labels = [y.year for y in years_data]

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

        val_text = _fmt_large(val).replace('<span class="na">', "").replace("</span>", "")

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
    <div class="metric-row">
      <span class="metric-label">P/E Trailing</span>
      <span class="metric-value">{pe_badge}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">P/E Forward</span>
      <span class="metric-value">{fpe_badge}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Price / Book</span>
      <span class="metric-value">{pb_badge}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">EPS (Trailing)</span>
      <span class="metric-value">{_badge_score("eps", eps_disp)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Dividend Yield</span>
      <span class="metric-value">{_badge("div", "white") if snap.div_yield is None else div_disp}</span>
    </div>
  </div>

  <!-- Growth Metrics -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📈</span>Growth Metrics</div>
    <div class="metric-row">
      <span class="metric-label">EPS Growth</span>
      <span class="metric-value">{_badge(eps_growth_disp, scores.get("eps_growth","white"))}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Revenue Growth</span>
      <span class="metric-value">{_badge(rev_growth_disp, scores.get("revenue_growth","white"))}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Profit Margin</span>
      <span class="metric-value">{_badge(margin_disp, scores.get("profit_margin","white"))}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Return on Equity</span>
      <span class="metric-value">{_badge(roe_disp, scores.get("roe","white"))}</span>
    </div>
  </div>

  <!-- Financial Health -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🏦</span>Financial Health</div>
    <div class="metric-row">
      <span class="metric-label">Debt / Equity</span>
      <span class="metric-value">{_badge(debt_disp, scores.get("debt_to_equity","white"))}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">52-Week High</span>
      <span class="metric-value">{hi52}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">52-Week Low</span>
      <span class="metric-value">{lo52}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Horizon Return</span>
      <span class="metric-value">{hor_disp}</span>
    </div>
  </div>
</div>
"""


def _render_valuation_section(snap: ValuationSnapshot) -> str:
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

    return f"""
<div class="card-grid wide">
  <!-- PE & Profile -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📊</span>PE Ratio &amp; Investor Profile</div>
    <div class="metric-row">
      <span class="metric-label">Trailing P/E</span>
      <span class="metric-value" style="color:{pe_css}">
        {f"{snap.pe_ratio:.1f}x" if snap.pe_ratio is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <div class="metric-row">
      <span class="metric-label">6-Month Avg P/E</span>
      <span class="metric-value text-yellow">
        {f"{snap.avg_pe_6m:.1f}x" if snap.avg_pe_6m is not None else '<span class="na">N/A</span>'}
        <span class="text-muted" style="font-size:.72rem"> ← used for projection</span>
      </span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Investor Profile</span>
      <span class="metric-value" style="color:{pe_css}; font-size:.78rem; text-align:right; max-width:220px">
        {html.escape(pe_label)}
      </span>
    </div>
  </div>

  <!-- Cash & Debt -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🏦</span>Cash &amp; Debt Health</div>
    <div class="metric-row">
      <span class="metric-label">Total Cash</span>
      <span class="metric-value">{_fmt_large(snap.total_cash)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Total Debt</span>
      <span class="metric-value">{_fmt_large(snap.total_debt)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Net Cash</span>
      <span class="metric-value" style="color:{net_cash_color}">
        {_fmt_large(net_cash) if net_cash is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Debt / Assets</span>
      <span class="metric-value">
        {f'<span style="color:{da_css}">{da_pct:.1f}%</span> <span class="badge" style="color:{da_css}">{da_label}</span>' if da_pct is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Current Ratio</span>
      <span class="metric-value" style="color:{cr_css}">
        {f"{cr:.2f}x" if cr is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Quick Ratio</span>
      <span class="metric-value" style="color:{qr_css}">
        {f"{qr:.2f}x" if qr is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
  </div>

  <!-- Profitability -->
  <div class="card">
    <div class="card-title"><span class="card-icon">💰</span>Profitability</div>
    <div class="metric-row">
      <span class="metric-label">Profit Margin</span>
      <span class="metric-value">
        <span style="color:{margin_css}">{f"{snap.profit_margin:.2%}" if snap.profit_margin is not None else "N/A"}</span>
        &nbsp;<span class="badge" style="color:{margin_css}">{margin_label}</span>
      </span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Revenue Est. (next yr)</span>
      <span class="metric-value">{_fmt_large(snap.next_year_revenue_est)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Market Cap</span>
      <span class="metric-value">{_fmt_large(snap.market_cap)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">EPS (Trailing)</span>
      <span class="metric-value">{f"${snap.eps:.2f}" if snap.eps is not None else '<span class="na">N/A</span>'}</span>
    </div>
  </div>

  <!-- Analyst Targets -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🎯</span>Analyst Price Targets</div>
    <div class="metric-row">
      <span class="metric-label">Low Target</span>
      <span class="metric-value text-red">{f"${snap.analyst_target_low:.2f}" if snap.analyst_target_low is not None else '<span class="na">N/A</span>'}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Mean Target</span>
      <span class="metric-value">{f"${snap.analyst_target_mean:.2f}" if snap.analyst_target_mean is not None else '<span class="na">N/A</span>'}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">High Target</span>
      <span class="metric-value text-green">{f"${snap.analyst_target_high:.2f}" if snap.analyst_target_high is not None else '<span class="na">N/A</span>'}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Upside</span>
      <span class="metric-value" style="color:{upside_css}">
        {f"{'+' if (snap.analyst_upside_pct or 0) >= 0 else ''}{snap.analyst_upside_pct:.1f}%" if snap.analyst_upside_pct is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Consensus</span>
      <span class="metric-value" style="color:{rec_css}; font-weight:700">{html.escape(rec)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label"># Analysts</span>
      <span class="metric-value">{snap.num_analysts if snap.num_analysts is not None else '<span class="na">N/A</span>'}</span>
    </div>
  </div>
</div>

<!-- Valuation Projection -->
<div class="card" style="margin-bottom:24px">
  <div class="card-title"><span class="card-icon">🔮</span>Valuation Projection (5+ Year View)</div>
  <p style="font-size:.8rem; color:var(--clr-muted); margin-bottom:10px">
    Projected Earnings = Revenue Est. × Margin → Future Market Cap = Earnings × Avg P/E → Possible Return vs today
  </p>
  {proj_flow}
  <div style="margin-top:16px; text-align:center">
    <div style="font-size:.72rem; color:var(--clr-muted); text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">Possible Return</div>
    {ret_disp}
    <div style="font-size:.75rem; color:var(--clr-muted); margin-top:8px">
      Current Mkt Cap: {_fmt_large(snap.market_cap)}
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

    svg = _owner_earnings_svg(snap.years or [])

    return f"""
<div class="card-grid">
  <!-- Formula Breakdown -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🧮</span>Formula Breakdown</div>
    <div class="metric-row">
      <span class="metric-label">Net Income</span>
      <span class="metric-value">{_fmt_large(snap.net_income)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">+ Depreciation</span>
      <span class="metric-value">{_fmt_large(snap.depreciation)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">− CapEx</span>
      <span class="metric-value text-red">{_fmt_large(snap.capex)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">− Working Capital Δ</span>
      <span class="metric-value">{_fmt_large(snap.working_capital_change)}</span>
    </div>
    <div class="metric-row" style="border-top:2px solid var(--clr-border); margin-top:4px; padding-top:8px">
      <span class="metric-label" style="font-weight:700; color:var(--clr-fg)">Owner Earnings</span>
      <span class="metric-value text-green" style="font-size:1rem; font-weight:800">{_fmt_large(snap.owner_earnings)}</span>
    </div>
    <div class="metric-row">
      <span class="metric-label">Per Share</span>
      <span class="metric-value">{f"${snap.oe_per_share:.2f}" if snap.oe_per_share is not None else '<span class="na">N/A</span>'}</span>
    </div>
  </div>

  <!-- Reality Check & Yield -->
  <div class="card">
    <div class="card-title"><span class="card-icon">🔍</span>Reality Check &amp; Yield</div>
    <div class="metric-row">
      <span class="metric-label">OE vs Net Income</span>
      <span class="metric-value" style="color:{oe_vs_css}">
        {f"{'+' if (oe_vs_ni or 0) >= 0 else ''}{oe_vs_ni:.1f}%" if oe_vs_ni is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <p class="metric-hint">
      {"> +10%: earns more cash than it reports" if (oe_vs_ni or 0) > 10 else ("< -10%: reported profits are overstated" if (oe_vs_ni or -99) < -10 else "Profits match cash generation")}
    </p>
    <div class="metric-row" style="margin-top:10px">
      <span class="metric-label">OE Yield</span>
      <span class="metric-value" style="color:{yield_css}">
        {f"{oe_yield:.1f}%" if oe_yield is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <p class="metric-hint">{yield_label}</p>
    <div class="metric-row" style="margin-top:10px">
      <span class="metric-label">Capital Intensity</span>
      <span class="metric-value" style="color:{cap_css}">
        {f"{cap_int:.1f}%" if cap_int is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <p class="metric-hint">{cap_label}</p>
  </div>

  <!-- Trend -->
  <div class="card">
    <div class="card-title"><span class="card-icon">📅</span>Multi-Year Trend</div>
    <div class="big-metric" style="margin-bottom:12px">
      <div class="val" style="color:{trend_css}">{html.escape(trend)}</div>
      <div class="sub">
        {f"YoY: {'+' if (snap.oe_growth_pct or 0) >= 0 else ''}{snap.oe_growth_pct:.1f}%" if snap.oe_growth_pct is not None else ""}
        {f" &nbsp;|&nbsp; CAGR: {snap.oe_cagr_pct:.1f}%" if snap.oe_cagr_pct is not None else ""}
      </div>
    </div>
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
    <div class="metric-row">
      <span class="metric-label">P/E (Trailing)</span>
      <span class="metric-value" style="color:{pe_css}">
        {f"{snap.pe_ratio:.1f}x" if snap.pe_ratio is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <p class="metric-hint">Under 15 = bargain · 15-25 = fair · Over 25 = pricey</p>

    <div class="metric-row">
      <span class="metric-label">Price / Book</span>
      <span class="metric-value" style="color:{pb_css}">
        {f"{snap.pb_ratio:.1f}x" if snap.pb_ratio is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <p class="metric-hint">Under 1.5 = deep value · 1.5-3 = fair · Over 3 = expensive</p>

    <div class="metric-row">
      <span class="metric-label">Price / FCF</span>
      <span class="metric-value" style="color:{pfcf_css}">
        {f"{snap.pfcf_ratio:.1f}x" if snap.pfcf_ratio is not None else '<span class="na">N/A</span>'}
      </span>
    </div>
    <p class="metric-hint">Under 15 = strong value · 15-25 = fair · Over 25 = expensive</p>
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
