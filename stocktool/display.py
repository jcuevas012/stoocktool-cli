from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analysis import (
    FundamentalSnapshot, ValuationSnapshot, ValueCheckSnapshot,
    CashSecuredPutSnapshot, OwnerEarningsSnapshot, ETFValuationSnapshot,
    score_ticker, pe_category, cash_debt_rating,
)
from .portfolio import PortfolioSnapshot

console = Console()


def render_fundamental_table(
    snapshots: list[FundamentalSnapshot],
    show_scores: bool = False,
    horizon_days: int = 90,
) -> None:
    title = f"Fundamental Analysis  ({horizon_days}-day horizon)"
    table = Table(title=title, show_lines=True, header_style="bold cyan")

    table.add_column("Metric", style="bold", min_width=20)
    for snap in snapshots:
        table.add_column(snap.ticker, justify="right", min_width=12)

    scores_by_ticker: dict[str, dict[str, str]] = {}
    if show_scores:
        for snap in snapshots:
            scores_by_ticker[snap.ticker] = score_ticker(snap)

    def _cell(value, fmt: str, key: str, ticker: str, suffix: str = "") -> Text:
        color = scores_by_ticker.get(ticker, {}).get(key, "white") if show_scores else "white"
        if value is None:
            return Text("N/A", style="dim")
        return Text(f"{value:{fmt}}{suffix}", style=color)

    rows: list[tuple[str, str, str, str]] = [
        ("Sector", "sector", "", ""),
        ("Current Price", "current_price", ".2f", "$"),
        ("P/E (Trailing)", "pe_ratio", ".1f", "x"),
        ("P/E (Forward)", "forward_pe", ".1f", "x"),
        ("EPS (Trailing)", "eps", "", "$"),
        ("EPS Growth", "eps_growth", ".1%", ""),
        ("Revenue Growth", "revenue_growth", ".1%", ""),
        ("Profit Margin", "profit_margin", ".1%", ""),
        ("Debt / Equity", "debt_to_equity", ".1f", ""),
        ("ROE", "roe", ".1%", ""),
        ("Price / Book", "price_to_book", ".2f", "x"),
        ("Dividend Yield", "div_yield", ".2%", ""),
        ("52-Week High", "week_52_high", ".2f", "$"),
        ("52-Week Low", "week_52_low", ".2f", "$"),
        (f"{horizon_days}d Return", "horizon_return_pct", ".2f", "%"),
    ]

    for label, attr, fmt, prefix in rows:
        cells = [Text(label, style="bold")]
        for snap in snapshots:
            val = getattr(snap, attr)
            if attr == "sector":
                cells.append(Text(val or "N/A", style="dim" if val is None else ""))
            elif attr in ("current_price", "week_52_high", "week_52_low"):
                if val is None:
                    cells.append(Text("N/A", style="dim"))
                else:
                    cells.append(Text(f"${val:.2f}"))
            elif attr in ("eps_growth", "revenue_growth", "profit_margin", "roe"):
                if val is None:
                    cells.append(Text("N/A", style="dim"))
                else:
                    color = scores_by_ticker.get(snap.ticker, {}).get(attr, "white") if show_scores else "white"
                    cells.append(Text(f"{val:.1%}", style=color))
            elif attr == "div_yield":
                if val is None:
                    cells.append(Text("N/A", style="dim"))
                else:
                    color = scores_by_ticker.get(snap.ticker, {}).get(attr, "white") if show_scores else "white"
                    # yfinance returns dividendYield already as a percentage decimal (0.39 = 0.39%)
                    cells.append(Text(f"{val:.2f}%", style=color))
            elif attr == "horizon_return_pct":
                if val is None:
                    cells.append(Text("N/A", style="dim"))
                else:
                    color = scores_by_ticker.get(snap.ticker, {}).get(attr, "white") if show_scores else "white"
                    sign = "+" if val >= 0 else ""
                    cells.append(Text(f"{sign}{val:.2f}%", style=color))
            else:
                if val is None:
                    cells.append(Text("N/A", style="dim"))
                else:
                    color = scores_by_ticker.get(snap.ticker, {}).get(attr, "white") if show_scores else "white"
                    if attr == "eps":
                        cells.append(Text(f"${val:.2f}", style=color))
                    else:
                        cells.append(Text(f"{val:{fmt}}{prefix}", style=color))
        table.add_row(*cells)

    console.print(table)


def render_value_check(snapshots: list[ValueCheckSnapshot]) -> None:
    """Render a quick value-check table with P/E, P/B, P/FCF and color-coded hints."""
    # Thresholds: (green_max, yellow_max)
    THRESHOLDS = {
        "P/E":   (15, 25, "< 15 = bargain, 15–25 = fair, > 25 = pricey"),
        "P/B":   (1.5, 3, "< 1.5 = deep value, 1.5–3 = fair, > 3 = expensive"),
        "P/FCF": (15, 25, "< 15 = strong value, 15–25 = fair, > 25 = expensive"),
    }

    def _color(value: float | None, green_max: float, yellow_max: float) -> str:
        if value is None or value < 0:
            return "red"
        if value < green_max:
            return "green"
        if value <= yellow_max:
            return "yellow"
        return "red"

    def _fmt(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.1f}x"

    table = Table(title="Quick Value Check", show_lines=True, header_style="bold cyan")
    table.add_column("Metric", style="bold", min_width=24)
    for snap in snapshots:
        label = snap.ticker
        if snap.sector:
            label += f"\n[dim]{snap.sector}[/dim]"
        if snap.current_price is not None:
            label += f"\n[dim]${snap.current_price:.2f}[/dim]"
        table.add_column(label, justify="right", min_width=12)
    table.add_column("Hint", style="dim italic", min_width=30)

    rows = [
        ("Price to Earnings (P/E)", "pe_ratio", "P/E"),
        ("Price to Book (P/B)", "pb_ratio", "P/B"),
        ("Price to Free Cash Flow (P/FCF)", "pfcf_ratio", "P/FCF"),
    ]

    for label, attr, key in rows:
        green_max, yellow_max, hint = THRESHOLDS[key]
        cells: list = [label]
        for snap in snapshots:
            val = getattr(snap, attr)
            color = _color(val, green_max, yellow_max)
            cells.append(Text(_fmt(val), style=color))
        cells.append(hint)
        table.add_row(*cells)

    console.print(table)


def render_portfolio_summary(snapshot: PortfolioSnapshot) -> None:
    table = Table(
        title="Portfolio Summary",
        show_lines=True,
        header_style="bold cyan",
        show_footer=True,
    )
    table.add_column("Ticker", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Shares", justify="right")
    table.add_column("Cost/Share", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Market Value", justify="right")
    table.add_column("Cost Value", justify="right")
    table.add_column("Unrealized P&L", justify="right")
    table.add_column("P&L %", justify="right")
    table.add_column("Weight", justify="right")

    stock_positions = [ps for ps in snapshot.positions if not ps.is_etf]
    etf_positions = [ps for ps in snapshot.positions if ps.is_etf]

    def _add_group(positions, group_label):
        for ps in positions:
            pnl_color = "green" if ps.unrealized_pnl >= 0 else "red"
            pnl_sign = "+" if ps.unrealized_pnl >= 0 else ""
            pnl_pct_sign = "+" if ps.unrealized_pnl_pct >= 0 else ""
            table.add_row(
                ps.ticker,
                "ETF" if ps.is_etf else "Stock",
                f"{ps.shares:.4f}",
                f"${ps.cost_basis:.2f}",
                f"${ps.current_price:.2f}",
                f"${ps.market_value:,.2f}",
                f"${ps.cost_value:,.2f}",
                Text(f"{pnl_sign}${ps.unrealized_pnl:,.2f}", style=pnl_color),
                Text(f"{pnl_pct_sign}{ps.unrealized_pnl_pct:.2f}%", style=pnl_color),
                f"{ps.current_weight:.1f}%",
            )
        # Sub-total row if both types exist
        if positions and (stock_positions and etf_positions):
            grp_mv = sum(p.market_value for p in positions)
            grp_cv = sum(p.cost_value for p in positions)
            grp_pnl = grp_mv - grp_cv
            grp_pnl_pct = (grp_pnl / grp_cv * 100) if grp_cv else 0.0
            grp_weight = sum(p.current_weight for p in positions)
            pc = "green" if grp_pnl >= 0 else "red"
            table.add_row(
                Text(f"  {group_label} Subtotal", style="bold dim"),
                "", "", "", "",
                Text(f"${grp_mv:,.2f}", style="bold"),
                Text(f"${grp_cv:,.2f}", style="bold"),
                Text(f"{'+'if grp_pnl>=0 else ''}${grp_pnl:,.2f}", style=f"bold {pc}"),
                Text(f"{'+'if grp_pnl_pct>=0 else ''}{grp_pnl_pct:.2f}%", style=f"bold {pc}"),
                Text(f"{grp_weight:.1f}%", style="bold"),
            )

    _add_group(stock_positions, "Stocks")
    _add_group(etf_positions, "ETFs")

    total_pnl_color = "green" if snapshot.total_unrealized_pnl >= 0 else "red"
    total_sign = "+" if snapshot.total_unrealized_pnl >= 0 else ""
    total_pct_sign = "+" if snapshot.total_unrealized_pnl_pct >= 0 else ""

    table.columns[0].footer = Text("TOTAL", style="bold")
    table.columns[5].footer = Text(f"${snapshot.total_market_value:,.2f}", style="bold")
    table.columns[6].footer = Text(f"${snapshot.total_cost_value:,.2f}", style="bold")
    table.columns[7].footer = Text(
        f"{total_sign}${snapshot.total_unrealized_pnl:,.2f}", style=f"bold {total_pnl_color}"
    )
    table.columns[8].footer = Text(
        f"{total_pct_sign}{snapshot.total_unrealized_pnl_pct:.2f}%",
        style=f"bold {total_pnl_color}",
    )

    console.print(table)


def render_allocation(snapshot: PortfolioSnapshot) -> None:
    # Ticker allocation table
    alloc_table = Table(title="Allocation", show_lines=True, header_style="bold cyan")
    alloc_table.add_column("Ticker", style="bold")
    alloc_table.add_column("Type", style="dim")
    alloc_table.add_column("Sector")
    alloc_table.add_column("Current Weight", justify="right")
    alloc_table.add_column("Target Weight", justify="right")
    alloc_table.add_column("Difference", justify="right")

    for ps in snapshot.positions:
        if ps.target_weight is not None:
            diff = ps.current_weight - ps.target_weight
            diff_color = "red" if diff > 2 else ("yellow" if diff < -2 else "green")
            diff_sign = "+" if diff >= 0 else ""
            diff_text = Text(f"{diff_sign}{diff:.1f}%", style=diff_color)
            target_text = f"{ps.target_weight:.1f}%"
        else:
            diff_text = Text("—", style="dim")
            target_text = "—"

        alloc_table.add_row(
            ps.ticker,
            "ETF" if ps.is_etf else "Stock",
            ps.sector or "Unknown",
            f"{ps.current_weight:.1f}%",
            target_text,
            diff_text,
        )

    console.print(alloc_table)

    # Sector breakdown
    if snapshot.sector_allocation:
        sector_table = Table(title="Sector Breakdown", show_lines=True, header_style="bold cyan")
        sector_table.add_column("Sector", style="bold")
        sector_table.add_column("Weight", justify="right")

        for sector, weight in sorted(snapshot.sector_allocation.items(), key=lambda x: -x[1]):
            sector_table.add_row(sector, f"{weight:.1f}%")

        console.print(sector_table)

    # Type breakdown (ETF vs Stock)
    if snapshot.type_allocation and len(snapshot.type_allocation) > 1:
        type_table = Table(title="Type Breakdown", show_lines=True, header_style="bold cyan")
        type_table.add_column("Type", style="bold")
        type_table.add_column("Weight", justify="right")

        for type_name, weight in sorted(snapshot.type_allocation.items()):
            type_table.add_row(type_name, f"{weight:.1f}%")

        console.print(type_table)


def render_rebalancing_signals(snapshot: PortfolioSnapshot) -> None:
    if not snapshot.rebalancing_signals:
        console.print(Panel("No target weights set. Use `stocktool portfolio target TICKER WEIGHT` to set targets.", title="Rebalancing"))
        return

    table = Table(title="Rebalancing Signals", show_lines=True, header_style="bold cyan")
    table.add_column("Ticker", style="bold")
    table.add_column("Signal", justify="center")
    table.add_column("Current", justify="right")
    table.add_column("Target", justify="right")
    table.add_column("Diff", justify="right")
    table.add_column("Action (shares)", justify="right")
    table.add_column("Action ($)", justify="right")

    for sig in snapshot.rebalancing_signals:
        diff_sign = "+" if sig["diff"] >= 0 else ""
        shares_diff = sig["shares_diff"]
        dollar_diff = sig["dollar_diff"]

        if sig["signal"] == "OVERWEIGHT":
            action_shares = f"Sell {abs(shares_diff):.2f}"
            action_dollar = f"Sell ${abs(dollar_diff):,.2f}"
        elif sig["signal"] == "UNDERWEIGHT":
            action_shares = f"Buy {abs(shares_diff):.2f}"
            action_dollar = f"Buy ${abs(dollar_diff):,.2f}"
        else:
            action_shares = "—"
            action_dollar = "—"

        table.add_row(
            sig["ticker"],
            Text(sig["signal"], style=f"bold {sig['color']}"),
            f"{sig['current_weight']:.1f}%",
            f"{sig['target_weight']:.1f}%",
            Text(f"{diff_sign}{sig['diff']:.1f}%", style=sig["color"]),
            action_shares,
            action_dollar,
        )

    console.print(table)


def render_compare_table(
    snapshots: list[FundamentalSnapshot],
    horizon_days: int = 90,
) -> None:
    render_fundamental_table(snapshots, show_scores=True, horizon_days=horizon_days)


def render_valuation(snapshots: list[ValuationSnapshot]) -> None:
    """Render the valuation template for each ticker as a rich Panel."""
    for snap in snapshots:
        _render_one_valuation(snap)


def _render_one_valuation(snap: ValuationSnapshot) -> None:
    from rich.console import Group
    from rich.rule import Rule

    lines: list = []

    def hint(text: str) -> None:
        lines.append(Text(f"  ↳ {text}", style="dim italic"))

    # ── Header ───────────────────────────────────────────────────────────
    price_str = f"${snap.current_price:.2f}" if snap.current_price else "N/A"
    mktcap_str = _fmt_large(snap.market_cap)
    sector_str = snap.sector or "Unknown"
    lines.append(Text.assemble(
        ("  Price: ", "bold"), (price_str, "cyan"),
        ("   Market Cap: ", "bold"), (mktcap_str, "cyan"),
        ("   Sector: ", "bold"), (sector_str, ""),
    ))
    lines.append(Text(""))

    # ── 1. PE Ratio ──────────────────────────────────────────────────────
    lines.append(Rule(" 1. PE Ratio (Price / Earnings) ", style="cyan"))
    hint("How much you pay for $1 of company profit. Lower = cheaper entry for long-term investors.")
    pe_label, pe_color = pe_category(snap.pe_ratio)
    pe_str = f"{snap.pe_ratio:.1f}x" if snap.pe_ratio else "N/A"
    avg_pe_str = f"{snap.avg_pe_6m:.1f}x" if snap.avg_pe_6m else "N/A"
    lines.append(Text(""))
    lines.append(Text.assemble(("  Trailing PE:      ", "bold"), (pe_str, pe_color)))
    lines.append(Text.assemble(("  Investor Profile: ", "bold"), (pe_label, pe_color)))
    lines.append(Text.assemble(
        ("  6-Month Avg PE:   ", "bold"), (avg_pe_str, "yellow"),
        ("   ← used for projection below", "dim"),
    ))
    lines.append(Text(""))

    # ── 2. Cash & Debt Health ────────────────────────────────────────────
    lines.append(Rule(" 2. Cash & Debt Health ", style="cyan"))
    hint("A strong balance sheet survives recessions and funds growth without raising new debt.")
    lines.append(Text(""))

    cash_str = _fmt_large(snap.total_cash) if snap.total_cash else "N/A"
    debt_str = _fmt_large(snap.total_debt) if snap.total_debt else "N/A"
    cash_rating, cash_color = cash_debt_rating(snap.total_cash, snap.total_debt)
    debt_rating = "EXCELLENT" if (snap.total_debt or 0) < (snap.total_cash or 0) else "REVIEW"
    debt_color = "green" if debt_rating == "EXCELLENT" else "yellow"

    net_cash = None
    if snap.total_cash is not None and snap.total_debt is not None:
        net_cash = snap.total_cash - snap.total_debt
    net_str = _fmt_large(abs(net_cash)) if net_cash is not None else "N/A"
    net_sign = "+" if (net_cash or 0) >= 0 else "-"
    net_color = "green" if (net_cash or 0) >= 0 else "red"

    lines.append(Text.assemble(
        ("  Cash:         ", "bold"), (cash_str, "white"),
        ("   [", "dim"), (cash_rating, cash_color), ("]", "dim"),
    ))
    lines.append(Text.assemble(
        ("  Total Debt:   ", "bold"), (debt_str, "white"),
        ("   [", "dim"), (debt_rating, debt_color), ("]", "dim"),
    ))
    lines.append(Text.assemble(
        ("  Net Cash:     ", "bold"), (f"{net_sign}{net_str}", net_color),
        ("   (cash minus debt)", "dim"),
    ))
    lines.append(Text(""))

    # Debt as % of total assets
    if snap.debt_to_assets_pct is not None:
        assets_str = _fmt_large(snap.total_assets)
        da_pct = snap.debt_to_assets_pct
        da_color = "green" if da_pct < 40 else ("yellow" if da_pct < 65 else "red")
        da_label = "LOW LEVERAGE" if da_pct < 40 else ("MODERATE" if da_pct < 65 else "HIGH LEVERAGE")
        lines.append(Text.assemble(
            ("  Total Assets:  ", "bold"), (assets_str, "white"),
        ))
        lines.append(Text.assemble(
            ("  Debt/Assets:   ", "bold"), (f"{da_pct:.1f}%", da_color),
            (f"   [{da_label}]", da_color),
            ("   — what % of all assets is financed by debt", "dim"),
        ))
    else:
        lines.append(Text("  Debt/Assets: N/A", style="dim"))

    # Liquidity ratios
    cr_str = f"{snap.current_ratio:.2f}x" if snap.current_ratio else "N/A"
    qr_str = f"{snap.quick_ratio:.2f}x" if snap.quick_ratio else "N/A"
    cr_color = "green" if (snap.current_ratio or 0) >= 1.5 else ("yellow" if (snap.current_ratio or 0) >= 1 else "red")
    qr_color = "green" if (snap.quick_ratio or 0) >= 1 else ("yellow" if (snap.quick_ratio or 0) >= 0.7 else "red")
    lines.append(Text(""))
    lines.append(Text("  Liquidity (ability to pay short-term obligations):", style="bold"))
    lines.append(Text.assemble(
        ("  Current Ratio:  ", "bold"), (cr_str, cr_color),
        ("   — current assets / current liabilities. >1.5 = healthy", "dim"),
    ))
    lines.append(Text.assemble(
        ("  Quick Ratio:    ", "bold"), (qr_str, qr_color),
        ("   — like current ratio but excludes inventory. >1.0 = solid", "dim"),
    ))

    # Free Cash Flow (used in DCF fallback)
    if snap.free_cashflow is not None:
        fcf_s = _fmt_large(snap.free_cashflow)
        fcf_color = "green" if snap.free_cashflow > 0 else "red"
        lines.append(Text(""))
        lines.append(Text.assemble(
            ("  Free Cash Flow: ", "bold"), (fcf_s, fcf_color),
            ("   — operating cash minus capex. Used as DCF fallback if D&A unavailable.", "dim"),
        ))
    lines.append(Text(""))

    # ── 3. Revenue Estimate Next Year ────────────────────────────────────
    lines.append(Rule(" 3. Revenue Estimate — Next Year (Analyst Avg) ", style="cyan"))
    hint("Consistent revenue growth signals a durable business. The foundation of long-term compounding.")
    rev_str = _fmt_large(snap.next_year_revenue_est) if snap.next_year_revenue_est else "Not available"
    lines.append(Text(""))
    lines.append(Text.assemble(("  Analyst Avg Revenue: ", "bold"), (rev_str, "white")))
    lines.append(Text(""))

    # ── 4. Profitability & Growth ─────────────────────────────────────────
    lines.append(Rule(" 4. Profitability & Growth ", style="cyan"))
    hint("Core earnings quality metrics. Margin = pricing power. EPS/Revenue growth = compounding engine. ROE = capital efficiency.")
    margin_str = f"{snap.profit_margin:.2%}" if snap.profit_margin else "N/A"
    margin_color = "green" if (snap.profit_margin or 0) > 0.20 else ("yellow" if (snap.profit_margin or 0) > 0.05 else "red")
    margin_label = "STRONG" if (snap.profit_margin or 0) > 0.20 else ("MODERATE" if (snap.profit_margin or 0) > 0.05 else "THIN")
    lines.append(Text(""))
    lines.append(Text.assemble(
        ("  Profit Margin:    ", "bold"), (margin_str, margin_color),
        (f"   [{margin_label}]", margin_color),
        ("   — net income / revenue", "dim"),
    ))

    # EPS
    eps_str = f"${snap.eps:.2f}" if snap.eps is not None else "N/A"
    eps_color = "green" if (snap.eps or 0) > 0 else "red"
    lines.append(Text.assemble(
        ("  EPS (Trailing):   ", "bold"), (eps_str, eps_color),
        ("   — per-share profit over last 12 months", "dim"),
    ))

    # ROE
    if snap.roe is not None:
        roe_color = "green" if snap.roe > 0.20 else ("yellow" if snap.roe > 0.10 else "red")
        roe_label = "EXCELLENT" if snap.roe > 0.20 else ("DECENT" if snap.roe > 0.10 else "POOR")
        lines.append(Text.assemble(
            ("  Return on Equity: ", "bold"), (f"{snap.roe:.1%}", roe_color),
            (f"   [{roe_label}]", roe_color),
            ("   — net income / shareholders' equity", "dim"),
        ))
    else:
        lines.append(Text("  Return on Equity: N/A", style="dim"))

    # Revenue & EPS growth (trailing, used in DCF)
    lines.append(Text(""))
    lines.append(Text("  Growth Rates (trailing, used in DCF growth-rate selection):", style="bold"))
    if snap.revenue_growth is not None:
        rg_color = "green" if snap.revenue_growth > 0.15 else ("yellow" if snap.revenue_growth > 0 else "red")
        lines.append(Text.assemble(
            ("  Revenue Growth:   ", "bold"), (f"{snap.revenue_growth:+.1%}", rg_color),
        ))
    else:
        lines.append(Text("  Revenue Growth:   N/A", style="dim"))

    if snap.eps_growth is not None:
        eg_color = "green" if snap.eps_growth > 0.15 else ("yellow" if snap.eps_growth > 0 else "red")
        lines.append(Text.assemble(
            ("  EPS Growth:       ", "bold"), (f"{snap.eps_growth:+.1%}", eg_color),
        ))
    else:
        lines.append(Text("  EPS Growth:       N/A", style="dim"))

    lines.append(Text(""))

    # ── 5. Avg PE (6 months) ─────────────────────────────────────────────
    lines.append(Rule(" 5. Average PE — Last 6 Months ", style="cyan"))
    hint("Historical average of what the market was paying. Used to estimate a realistic future valuation.")
    lines.append(Text(""))
    lines.append(Text.assemble(("  Avg PE (6m): ", "bold"), (avg_pe_str, "yellow")))
    lines.append(Text(""))

    # ── 6. Analyst Price Targets ─────────────────────────────────────────
    lines.append(Rule(" 6. Analyst Price Targets ", style="cyan"))
    hint("Wall Street's 12-month consensus. A reference point — not a guarantee. For 5+ year holds, fundamentals matter more.")
    lines.append(Text(""))

    if snap.analyst_target_mean and snap.current_price:
        upside_str = (
            f"{snap.analyst_upside_pct:+.1f}%" if snap.analyst_upside_pct is not None else "N/A"
        )
        upside_color = "green" if (snap.analyst_upside_pct or 0) > 0 else "red"
        low_str = f"${snap.analyst_target_low:.2f}" if snap.analyst_target_low else "N/A"
        mean_str = f"${snap.analyst_target_mean:.2f}"
        high_str = f"${snap.analyst_target_high:.2f}" if snap.analyst_target_high else "N/A"
        analysts_str = f"{snap.num_analysts}" if snap.num_analysts else "N/A"

        rec = (snap.recommendation_key or "N/A").replace("_", " ").title()
        rec_color = (
            "green" if "buy" in (snap.recommendation_key or "").lower()
            else "red" if "sell" in (snap.recommendation_key or "").lower()
            else "yellow"
        )

        lines.append(Text.assemble(
            ("  Current Price:   ", "bold"), (f"${snap.current_price:.2f}", "cyan"),
        ))
        lines.append(Text.assemble(
            ("  Low  Target:     ", "bold"), (low_str, "red"),
        ))
        lines.append(Text.assemble(
            ("  Mean Target:     ", "bold"), (mean_str, "white"),
            ("   → Upside: ", "dim"), (upside_str, upside_color),
        ))
        lines.append(Text.assemble(
            ("  High Target:     ", "bold"), (high_str, "green"),
        ))
        lines.append(Text.assemble(
            ("  # Analysts:      ", "bold"), (analysts_str, "white"),
            ("   Consensus: ", "dim"), (rec, f"bold {rec_color}"),
        ))
    else:
        lines.append(Text("  No analyst price targets available.", style="dim"))
    lines.append(Text(""))

    # ── Valuation Projection ─────────────────────────────────────────────
    lines.append(Rule(" Valuation Projection (5+ Year Value Investing View) ", style="bold magenta"))
    hint("Conservative estimate of future value. For long-term holds, look for 50%+ upside potential.")
    lines.append(Text(""))

    if snap.projected_earnings and snap.next_year_revenue_est and snap.profit_margin:
        rev_s = _fmt_large(snap.next_year_revenue_est)
        margin_s = f"{snap.profit_margin:.2%}"
        earn_s = _fmt_large(snap.projected_earnings)
        lines.append(Text.assemble(
            ("  Projected Earnings  = ", "bold"),
            (rev_s, "white"), (" × ", "dim"), (margin_s, "white"),
            (" = ", "dim"), (earn_s, "green"),
        ))
    else:
        lines.append(Text("  Projected Earnings: N/A — analyst revenue estimate unavailable", style="dim"))

    if snap.future_market_cap and snap.avg_pe_6m and snap.projected_earnings:
        earn_s = _fmt_large(snap.projected_earnings)
        fmc_s = _fmt_large(snap.future_market_cap)
        lines.append(Text.assemble(
            ("  Future Market Cap   = ", "bold"),
            (earn_s, "white"), (" × ", "dim"), (f"{snap.avg_pe_6m:.1f}x", "white"),
            (" = ", "dim"), (fmc_s, "green"),
        ))
    else:
        lines.append(Text("  Future Market Cap: N/A", style="dim"))

    mktcap_s = _fmt_large(snap.market_cap) if snap.market_cap else "N/A"
    lines.append(Text.assemble(("  Current Market Cap  = ", "bold"), (mktcap_s, "white")))
    lines.append(Text(""))

    if snap.possible_return_pct is not None:
        ret_color = "bold green" if snap.possible_return_pct >= 15 else ("bold yellow" if snap.possible_return_pct >= 0 else "bold red")
        sign = "+" if snap.possible_return_pct >= 0 else ""
        verdict = (
            "Strong opportunity for long-term investor" if snap.possible_return_pct >= 50
            else "Moderate upside — monitor fundamentals" if snap.possible_return_pct >= 15
            else "Limited upside at current price" if snap.possible_return_pct >= 0
            else "Projected downside — re-evaluate"
        )
        lines.append(Text.assemble(
            ("  Possible Return: ", "bold"),
            (f"{sign}{snap.possible_return_pct:.1f}%", ret_color),
            (f"   — {verdict}", "dim"),
        ))
    else:
        lines.append(Text("  Possible Return: N/A — need revenue estimate to project", style="dim"))

    # ── Intrinsic Value (DCF) ─────────────────────────────────────────────
    lines.append(Text(""))
    lines.append(Rule(" 7. Intrinsic Value — DCF (Buffett Owner Earnings Method) ", style="bold magenta"))
    hint("10-year discounted cash flow using Owner Earnings. Estimates fair value per share independent of market price.")
    lines.append(Text(""))

    if snap.dcf_owner_earnings is not None:
        ni_s = _fmt_large(snap.dcf_net_income) if snap.dcf_net_income else "N/A"
        oe_s = _fmt_large(snap.dcf_owner_earnings)
        lines.append(Text.assemble(("  Step 1  Normalized Net Income: ", "bold"), (ni_s, "white")))

        lines.append(Text.assemble(
            ("  Step 2  Owner Earnings:        ", "bold"), (oe_s, "cyan"),
            ("   (NI + D&A − CapEx)", "dim"),
        ))
        if snap.depreciation is not None:
            dep_s = _fmt_large(snap.depreciation)
            lines.append(Text(f"            D&A (add back):  {dep_s}", style="dim"))
        if snap.capex_cf is not None:
            capex_s = _fmt_large(abs(snap.capex_cf))
            lines.append(Text(f"            CapEx (subtract): {capex_s}", style="dim"))
        if snap.dcf_owner_earnings_note:
            lines.append(Text(f"          ↳ {snap.dcf_owner_earnings_note}", style="dim italic"))
        lines.append(Text(""))

        growth_s = f"{snap.dcf_growth_rate:.1%}" if snap.dcf_growth_rate is not None else "N/A"
        lines.append(Text.assemble(
            ("  Step 3  Growth Rate:           ", "bold"), (growth_s, "yellow"),
        ))
        if snap.dcf_growth_note:
            lines.append(Text(f"          ↳ {snap.dcf_growth_note}", style="dim italic"))
        lines.append(Text.assemble(
            ("  Step 4  Discount Rate:         ", "bold"),
            (f"{snap.dcf_discount_rate:.0%}", "white"),
            ("   (required annual return)", "dim"),
        ))
        lines.append(Text.assemble(
            ("  Step 5  Terminal Growth:       ", "bold"),
            (f"{snap.dcf_terminal_growth:.1%}", "white"),
            ("   (perpetual growth after year 10)", "dim"),
        ))
        lines.append(Text(""))

        ev_s = _fmt_large(snap.dcf_enterprise_value) if snap.dcf_enterprise_value else "N/A"
        eq_s = _fmt_large(snap.dcf_equity_value) if snap.dcf_equity_value else "N/A"
        lines.append(Text.assemble(("  Step 6  Enterprise Value:      ", "bold"), (ev_s, "white")))
        lines.append(Text.assemble(
            ("  Step 7  Equity Value:          ", "bold"), (eq_s, "white"),
            ("   (+ cash − debt)", "dim"),
        ))

        if snap.intrinsic_value_per_share is not None:
            iv_s = f"${snap.intrinsic_value_per_share:.2f}"
            price_s = f"${snap.current_price:.2f}" if snap.current_price else "N/A"
            lines.append(Text(""))
            lines.append(Text.assemble(
                ("  Step 8  Intrinsic Value/Share: ", "bold"), (iv_s, "bold cyan"),
                ("   vs Current ", "dim"), (price_s, "white"),
            ))

        if snap.margin_of_safety_pct is not None:
            mos = snap.margin_of_safety_pct
            mos_color = "bold green" if mos > 25 else ("bold yellow" if mos > 5 else "bold red")
            sign = "+" if mos >= 0 else ""
            rating_color = snap.iv_rating_color or "white"
            lines.append(Text.assemble(
                ("  Step 9  Margin of Safety:     ", "bold"),
                (f"{sign}{mos:.1f}%", mos_color),
            ))
            lines.append(Text(""))
            lines.append(Text.assemble(
                ("  Step 10 Rating:               ", "bold"),
                (snap.iv_rating or "N/A", f"bold {rating_color}"),
            ))
        else:
            lines.append(Text("  Steps 8-10: N/A — need shares outstanding for per-share value", style="dim"))
    else:
        lines.append(Text("  DCF not available — insufficient data (need revenue estimate + profit margin or FCF > 0)", style="dim"))

    console.print(Panel(
        Group(*lines),
        title=f"[bold cyan]Valuación de Activos: {snap.ticker}[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))


def render_etf_valuation(snapshots: list[ETFValuationSnapshot]) -> None:
    """Render the ETF valuation template for each ticker as a rich Panel."""
    for snap in snapshots:
        _render_one_etf_valuation(snap)
    if len(snapshots) >= 2:
        _render_etf_valuation_comparison(snapshots)


def _render_one_etf_valuation(snap: ETFValuationSnapshot) -> None:
    from rich.console import Group
    from rich.rule import Rule

    lines: list = []

    def hint(text: str) -> None:
        lines.append(Text(f"  ↳ {text}", style="dim italic"))

    # ── Header ───────────────────────────────────────────────────────────
    price_str = f"${snap.current_price:.2f}" if snap.current_price else "N/A"
    aum_str = _fmt_large(snap.total_assets) if snap.total_assets else "N/A"
    er_str = f"{snap.expense_ratio:.2%}" if snap.expense_ratio is not None else "N/A"
    lines.append(Text.assemble(
        ("  Price: ", "bold"), (price_str, "cyan"),
        ("   AUM: ", "bold"), (aum_str, "cyan"),
        ("   Expense Ratio: ", "bold"), (er_str, ""),
        ("   Category: ", "bold"), (snap.category or "Unknown", ""),
    ))
    lines.append(Text(""))

    # ── 1. Basket Concentration & Top Holdings ──────────────────────────
    lines.append(Rule(" 1. Basket Concentration & Top Holdings ", style="cyan"))
    hint("A fund concentrated in a handful of names behaves more like those stocks than a diversified basket.")
    lines.append(Text(""))

    if snap.holdings:
        h_table = Table(show_lines=False, header_style="bold cyan", box=None, padding=(0, 1))
        h_table.add_column("Symbol", style="bold")
        h_table.add_column("Name")
        h_table.add_column("Weight", justify="right")
        h_table.add_column("Trailing PE", justify="right")
        for h in snap.holdings:
            pe_str = f"{h.trailing_pe:.1f}x" if h.trailing_pe else "N/A"
            h_table.add_row(h.symbol, h.name or "N/A", f"{h.weight_pct:.2f}%", pe_str)
        lines.append(h_table)
        lines.append(Text(""))

    if snap.concentration_pct is not None:
        conc = snap.concentration_pct
        conc_color = "green" if conc < 40 else ("yellow" if conc < 60 else "red")
        conc_label = "DIVERSIFIED" if conc < 40 else ("MODERATE" if conc < 60 else "CONCENTRATED")
        lines.append(Text.assemble(
            ("  Top 10 Weight: ", "bold"), (f"{conc:.1f}%", conc_color),
            (f"   [{conc_label}]", conc_color),
        ))
    else:
        lines.append(Text("  Top 10 Weight: N/A", style="dim"))
    lines.append(Text(""))

    # ── 2. Valuation Multiples & PEGY ────────────────────────────────────
    lines.append(Rule(" 2. Valuation Multiples & PEGY ", style="cyan"))
    hint("PEGY adjusts P/E for growth AND yield — a fund can look expensive on P/E alone but cheap once growth and dividends are priced in.")
    lines.append(Text(""))

    pe_str = f"{snap.trailing_pe:.1f}x" if snap.trailing_pe else "N/A"
    source_note = "(basket .info)" if snap.trailing_pe_source == "etf_info" else "(weighted top-10 holdings)"
    lines.append(Text.assemble(
        ("  Trailing PE:        ", "bold"), (pe_str, "white"),
        (f"   {source_note}", "dim"),
    ))
    if snap.holdings_pe_coverage_note:
        hint(snap.holdings_pe_coverage_note)

    growth_str = f"{snap.forward_eps_growth_pct:+.1f}%" if snap.forward_eps_growth_pct is not None else "N/A"
    growth_color = "green" if (snap.forward_eps_growth_pct or 0) > 10 else ("yellow" if (snap.forward_eps_growth_pct or 0) > 0 else "red")
    lines.append(Text.assemble(
        ("  Forward EPS Growth: ", "bold"), (growth_str, growth_color),
        ("   — weighted across top-10 holdings", "dim"),
    ))

    yield_str = f"{snap.distribution_yield_pct:.2f}%" if snap.distribution_yield_pct is not None else "N/A"
    lines.append(Text.assemble(
        ("  Distribution Yield: ", "bold"), (yield_str, "white"),
    ))

    pegy_str = f"{snap.pegy_ratio:.2f}x" if snap.pegy_ratio is not None else "N/A"
    lines.append(Text.assemble(
        ("  PEGY Ratio:         ", "bold"), (pegy_str, snap.pegy_color or "dim"),
        (f"   [{snap.pegy_label or 'N/A'}]", snap.pegy_color or "dim"),
    ))
    lines.append(Text(""))

    # ── 3. Historical Valuation Bands & NAV ──────────────────────────────
    lines.append(Rule(" 3. Historical Valuation Bands & NAV ", style="cyan"))
    hint("Fair value assumes the fund's P/E reverts to its historical average — a reference point, not a guarantee.")
    lines.append(Text(""))

    hist_pe_str = f"{snap.hist_5y_avg_pe:.1f}x" if snap.hist_5y_avg_pe else "N/A"
    lines.append(Text.assemble(("  5Y Avg PE:    ", "bold"), (hist_pe_str, "yellow")))
    if snap.hist_pe_note:
        hint(snap.hist_pe_note)

    fv_str = f"${snap.fair_value:.2f}" if snap.fair_value else "N/A"
    lines.append(Text.assemble(("  Fair Value:   ", "bold"), (fv_str, "cyan")))

    if snap.tier1_entry is not None and snap.tier2_entry is not None:
        lo, hi = sorted([snap.tier1_entry, snap.tier2_entry])
        entry_str = f"${lo:.2f} – ${hi:.2f}"
    elif snap.tier1_entry is not None:
        entry_str = f"${snap.tier1_entry:.2f} (Tier 2 unavailable)"
    elif snap.tier2_entry is not None:
        entry_str = f"${snap.tier2_entry:.2f} (Tier 1 unavailable)"
    else:
        entry_str = "N/A"
    lines.append(Text.assemble(("  Entry Zone:   ", "bold"), (entry_str, "green")))
    lines.append(Text(""))

    # ── 4. Valuation Projection (5-Year Growth View) ─────────────────────
    lines.append(Rule(" 4. Valuation Projection (5-Year Growth View) ", style="bold magenta"))
    hint("Conservative estimate of future value. For long-term holds, look for 50%+ upside potential.")
    lines.append(Text(""))

    growth_used_str = f"{snap.growth_rate_used:.1%}" if snap.growth_rate_used is not None else "N/A"
    lines.append(Text.assemble(("  Growth Rate Used:    ", "bold"), (growth_used_str, "yellow")))

    proj_price_str = f"${snap.projected_price_5y:.2f}" if snap.projected_price_5y else "N/A"
    lines.append(Text.assemble(("  Projected Price (5Y): ", "bold"), (proj_price_str, "white")))

    if snap.total_return_pct is not None:
        ret_color = "bold green" if snap.total_return_pct >= 50 else ("bold yellow" if snap.total_return_pct >= 15 else ("green" if snap.total_return_pct >= 0 else "bold red"))
        cagr_str = f"{snap.cagr_pct:+.1f}%" if snap.cagr_pct is not None else "N/A"
        lines.append(Text.assemble(
            ("  5-Year Possible Return: ", "bold"),
            (f"{snap.total_return_pct:+.1f}%", ret_color),
            (f" ({cagr_str} CAGR)", "dim"),
        ))
    else:
        lines.append(Text("  5-Year Possible Return: N/A", style="dim"))
    lines.append(Text(""))

    # ── 5. Entry Strategy & Margin of Safety ─────────────────────────────
    lines.append(Rule(" 5. Entry Strategy & Margin of Safety ", style="bold magenta"))
    hint("Margin of safety cushions against being wrong. Entry tiers give a disciplined way to average in.")
    lines.append(Text(""))

    if snap.margin_of_safety_pct is not None:
        mos = snap.margin_of_safety_pct
        mos_color = "bold green" if mos > 25 else ("bold yellow" if mos > 5 else "bold red")
        sign = "+" if mos >= 0 else ""
        lines.append(Text.assemble(
            ("  Margin of Safety:       ", "bold"), (f"{sign}{mos:.1f}%", mos_color),
        ))
    else:
        lines.append(Text("  Margin of Safety: N/A", style="dim"))

    t1_str = f"${snap.tier1_entry:.2f}" if snap.tier1_entry is not None else "N/A"
    t2_str = f"${snap.tier2_entry:.2f}" if snap.tier2_entry is not None else "N/A"
    lines.append(Text.assemble(
        ("  Tier 1 (DCA Pullback):        ", "bold"), (t1_str, "green"),
        ("   — min(50d EMA, price × 0.95)", "dim"),
    ))
    lines.append(Text.assemble(
        ("  Tier 2 (Valuation Reversion): ", "bold"), (t2_str, "green"),
        ("   — min(fair value, 200d SMA)", "dim"),
    ))
    lines.append(Text(""))

    lines.append(Text.assemble(
        ("  Rating: ", "bold"),
        (snap.rating or "N/A", f"bold {snap.rating_color or 'white'}"),
    ))

    console.print(Panel(
        Group(*lines),
        title=f"[bold cyan]Valuación de Activos: {snap.ticker}[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))


def _render_etf_valuation_comparison(snapshots: list[ETFValuationSnapshot]) -> None:
    """Render a side-by-side comparison table for multiple ETF tickers."""
    table = Table(
        title="ETF Valuation — Side by Side",
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Metric", style="bold", min_width=20)
    for snap in snapshots:
        table.add_column(snap.ticker, justify="right", min_width=12)
    table.add_column("What it means", style="dim italic", min_width=30)

    cells: list = ["PEGY Ratio"]
    for snap in snapshots:
        if snap.pegy_ratio is not None:
            cells.append(Text(f"{snap.pegy_ratio:.2f}x", style=snap.pegy_color or "dim"))
        else:
            cells.append(Text("N/A", style="dim"))
    cells.append("Lower = cheaper relative to growth + yield")
    table.add_row(*cells)

    cells = ["Margin of Safety"]
    for snap in snapshots:
        if snap.margin_of_safety_pct is not None:
            mos = snap.margin_of_safety_pct
            color = "green" if mos > 25 else ("yellow" if mos > 5 else "red")
            cells.append(Text(f"{mos:+.1f}%", style=color))
        else:
            cells.append(Text("N/A", style="dim"))
    cells.append("Cushion between fair value and current price")
    table.add_row(*cells)

    cells = ["Concentration (Top 10)"]
    for snap in snapshots:
        if snap.concentration_pct is not None:
            conc = snap.concentration_pct
            color = "green" if conc < 40 else ("yellow" if conc < 60 else "red")
            cells.append(Text(f"{conc:.1f}%", style=color))
        else:
            cells.append(Text("N/A", style="dim"))
    cells.append("Higher = more concentrated in fewer names")
    table.add_row(*cells)

    cells = ["Rating"]
    for snap in snapshots:
        cells.append(Text(snap.rating or "N/A", style=f"bold {snap.rating_color or 'white'}"))
    cells.append("Combined PEGY + margin of safety verdict")
    table.add_row(*cells)

    console.print(table)


def render_sma_screen(sma_data: dict[str, dict], sma_days: int = 200) -> None:
    """Show portfolio positions vs their SMA, highlighting those trading below."""
    if not sma_data:
        console.print("[yellow]No SMA data available (need at least 200 trading days of history).[/yellow]")
        return

    below: list[tuple[str, dict]] = []
    above: list[tuple[str, dict]] = []
    for ticker, d in sorted(sma_data.items()):
        if d["pct_from_sma"] < 0:
            below.append((ticker, d))
        else:
            above.append((ticker, d))

    table = Table(
        title=f"Portfolio — {sma_days}-Day SMA Screen",
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Ticker", style="bold")
    table.add_column("Price", justify="right")
    table.add_column(f"{sma_days}d SMA", justify="right")
    table.add_column("vs SMA", justify="right")
    table.add_column("Signal", justify="center")

    # Below SMA first (the opportunities)
    for ticker, d in below:
        pct = d["pct_from_sma"]
        table.add_row(
            ticker,
            f"${d['current_price']:.2f}",
            f"${d['sma']:.2f}",
            Text(f"{pct:+.2f}%", style="red"),
            Text("BELOW SMA", style="bold yellow"),
        )
    for ticker, d in above:
        pct = d["pct_from_sma"]
        table.add_row(
            ticker,
            f"${d['current_price']:.2f}",
            f"${d['sma']:.2f}",
            Text(f"{pct:+.2f}%", style="green"),
            Text("ABOVE SMA", style="dim"),
        )

    console.print(table)

    if below:
        tickers_str = ", ".join(t for t, _ in below)
        console.print(Panel(
            f"[bold yellow]{len(below)} position(s) trading below {sma_days}d SMA:[/bold yellow] {tickers_str}\n"
            f"[dim]↳ Price is below the long-term average — may signal a buying opportunity for value investors.\n"
            f"  Check fundamentals before adding. Use: stocktool valuation {below[0][0]}[/dim]",
            title=f"[bold yellow]Below {sma_days}-Day SMA[/bold yellow]",
            border_style="yellow",
        ))
    else:
        console.print(Panel(
            f"[green]All positions are trading above their {sma_days}-day SMA.[/green]\n"
            f"[dim]↳ No positions are currently in a long-term downtrend.[/dim]",
            border_style="green",
        ))


def render_pie_chart(
    snapshot: PortfolioSnapshot,
    save_path: Optional[str] = None,
) -> None:
    """Render portfolio allocation as a terminal bar chart and save a PNG pie chart."""
    from .config import CONFIG_DIR, ensure_config_dir

    # ── Terminal: horizontal bar chart ──────────────────────────────────
    BAR_WIDTH = 30
    colors = ["cyan", "green", "yellow", "magenta", "blue", "red", "white"]

    # Ticker allocation bar chart
    table = Table(
        title="Portfolio Allocation",
        show_lines=False,
        header_style="bold cyan",
        box=None,
        padding=(0, 1),
    )
    table.add_column("Ticker", style="bold", min_width=8)
    table.add_column("Weight", justify="right", min_width=8)
    table.add_column("", min_width=BAR_WIDTH + 2)

    sorted_positions = sorted(snapshot.positions, key=lambda p: -p.current_weight)
    for i, ps in enumerate(sorted_positions):
        color = colors[i % len(colors)]
        bar_len = int(ps.current_weight / 100 * BAR_WIDTH)
        bar = Text("█" * bar_len, style=color)
        table.add_row(ps.ticker, f"{ps.current_weight:.1f}%", bar)

    console.print(table)
    console.print()

    # Sector allocation bar chart
    if snapshot.sector_allocation:
        sec_table = Table(
            title="Sector Allocation",
            show_lines=False,
            header_style="bold cyan",
            box=None,
            padding=(0, 1),
        )
        sec_table.add_column("Sector", style="bold", min_width=20)
        sec_table.add_column("Weight", justify="right", min_width=8)
        sec_table.add_column("", min_width=BAR_WIDTH + 2)

        sorted_sectors = sorted(snapshot.sector_allocation.items(), key=lambda x: -x[1])
        for i, (sector, weight) in enumerate(sorted_sectors):
            color = colors[i % len(colors)]
            bar_len = int(weight / 100 * BAR_WIDTH)
            bar = Text("█" * bar_len, style=color)
            sec_table.add_row(sector, f"{weight:.1f}%", bar)

        console.print(sec_table)
        console.print()

    # Type allocation bar chart (ETF vs Stock)
    has_type = snapshot.type_allocation and len(snapshot.type_allocation) > 1
    if has_type:
        type_table = Table(
            title="ETF vs Stock",
            show_lines=False,
            header_style="bold cyan",
            box=None,
            padding=(0, 1),
        )
        type_table.add_column("Type", style="bold", min_width=8)
        type_table.add_column("Weight", justify="right", min_width=8)
        type_table.add_column("", min_width=BAR_WIDTH + 2)

        type_colors = {"Stock": "green", "ETF": "blue"}
        for type_name, weight in sorted(snapshot.type_allocation.items()):
            color = type_colors.get(type_name, "white")
            bar_len = int(weight / 100 * BAR_WIDTH)
            bar = Text("█" * bar_len, style=color)
            type_table.add_row(type_name, f"{weight:.1f}%", bar)

        console.print(type_table)
        console.print()

    # ── PNG: matplotlib pie charts ──────────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        num_charts = 1
        if snapshot.sector_allocation:
            num_charts += 1
        if has_type:
            num_charts += 1

        fig, axes = plt.subplots(1, num_charts, figsize=(7 * num_charts, 7))
        if num_charts == 1:
            axes = [axes]

        ax_idx = 0

        # Ticker pie
        labels = [ps.ticker for ps in sorted_positions]
        sizes = [ps.current_weight for ps in sorted_positions]
        axes[ax_idx].pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140)
        axes[ax_idx].set_title("Ticker Allocation")
        ax_idx += 1

        # Sector pie
        if snapshot.sector_allocation:
            sec_labels = [s for s, _ in sorted_sectors]
            sec_sizes = [w for _, w in sorted_sectors]
            axes[ax_idx].pie(sec_sizes, labels=sec_labels, autopct="%1.1f%%", startangle=140)
            axes[ax_idx].set_title("Sector Allocation")
            ax_idx += 1

        # Type pie (ETF vs Stock)
        if has_type:
            type_labels = list(snapshot.type_allocation.keys())
            type_sizes = list(snapshot.type_allocation.values())
            axes[ax_idx].pie(type_sizes, labels=type_labels, autopct="%1.1f%%",
                             startangle=140, colors=["#4CAF50", "#2196F3"])
            axes[ax_idx].set_title("ETF vs Stock")

        plt.tight_layout()

        ensure_config_dir()
        out_path = save_path or str(CONFIG_DIR / "portfolio_allocation.png")
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        console.print(f"[dim]Pie chart saved to {out_path}[/dim]")
    except ImportError:
        console.print("[dim]Install matplotlib for PNG pie chart export.[/dim]")


def render_etf_compare(
    etf_info: dict[str, dict],
    performance: dict[str, dict[str, float]],
    overlap: dict[str, list[str]],
) -> None:
    """Render ETF comparison: overview, holdings, overlap, sectors, performance."""
    tickers = list(etf_info.keys())

    # ── Overview Table ──
    overview = Table(title="ETF Comparison", show_lines=True, header_style="bold cyan")
    overview.add_column("Metric", style="bold", min_width=20)
    for t in tickers:
        overview.add_column(t, justify="right", min_width=14)

    overview.add_row("Name", *[etf_info[t].get("long_name", "N/A") or "N/A" for t in tickers])
    overview.add_row("Expense Ratio", *[_fmt_pct(etf_info[t].get("expense_ratio")) for t in tickers])
    overview.add_row("AUM", *[_fmt_large(etf_info[t].get("total_assets")) for t in tickers])
    overview.add_row("Div Yield (trailing)", *[_fmt_pct(etf_info[t].get("trailing_dividend_yield")) for t in tickers])
    overview.add_row("Fund Family", *[etf_info[t].get("fund_family", "N/A") or "N/A" for t in tickers])
    console.print(overview)

    # ── Performance Table ──
    perf_table = Table(title="Price Performance", show_lines=True, header_style="bold cyan")
    perf_table.add_column("Period", style="bold")
    for t in tickers:
        perf_table.add_column(t, justify="right")

    for period in ["1m", "3m", "6m", "1y", "3y", "5y"]:
        cells: list = [period.upper()]
        for t in tickers:
            val = performance.get(t, {}).get(period)
            if val is not None:
                color = "green" if val >= 0 else "red"
                cells.append(Text(f"{val:+.2f}%", style=color))
            else:
                cells.append(Text("N/A", style="dim"))
        perf_table.add_row(*cells)
    console.print(perf_table)

    # ── Top 10 Holdings per ETF ──
    for t in tickers:
        holdings = etf_info[t].get("holdings", [])[:10]
        if not holdings:
            continue
        h_table = Table(title=f"Top Holdings: {t}", show_lines=True, header_style="bold cyan")
        h_table.add_column("#", style="dim", width=3)
        h_table.add_column("Symbol", style="bold")
        h_table.add_column("Name")
        h_table.add_column("Weight", justify="right")
        for i, h in enumerate(holdings, 1):
            pct = h.get("holdingPercent")
            pct_str = f"{pct * 100:.2f}%" if pct else "N/A"
            h_table.add_row(
                str(i),
                h.get("symbol", "N/A"),
                h.get("holdingName", "N/A"),
                pct_str,
            )
        console.print(h_table)

    # ── Holdings Overlap ──
    if overlap:
        o_table = Table(title="Holdings Overlap", show_lines=True, header_style="bold yellow")
        o_table.add_column("Stock", style="bold")
        o_table.add_column("Found In", min_width=20)
        o_table.add_column("# ETFs", justify="right")

        sorted_overlap = sorted(overlap.items(), key=lambda x: -len(x[1]))
        for symbol, etf_list in sorted_overlap:
            o_table.add_row(symbol, ", ".join(etf_list), str(len(etf_list)))

        total_unique = set()
        for t in tickers:
            for h in etf_info[t].get("holdings", []):
                s = h.get("symbol", "").upper()
                if s:
                    total_unique.add(s)
        overlap_pct = len(overlap) / len(total_unique) * 100 if total_unique else 0

        console.print(o_table)
        console.print(
            f"[dim]Overlap: {len(overlap)} of {len(total_unique)} unique holdings "
            f"({overlap_pct:.1f}%) appear in 2+ ETFs[/dim]"
        )
        console.print("[dim]Note: Based on top holdings reported by yfinance (not full fund composition)[/dim]")
    else:
        console.print("[dim]No holdings overlap found between these ETFs.[/dim]")

    # ── Sector Weights per ETF ──
    all_sectors: set[str] = set()
    etf_sectors: dict[str, dict[str, float]] = {}
    for t in tickers:
        etf_sectors[t] = {}
        for sw in etf_info[t].get("sector_weightings", []):
            if isinstance(sw, dict):
                for sector, weight in sw.items():
                    all_sectors.add(sector)
                    etf_sectors[t][sector] = float(weight) * 100

    if all_sectors:
        s_table = Table(title="Sector Breakdown", show_lines=True, header_style="bold cyan")
        s_table.add_column("Sector", style="bold", min_width=20)
        for t in tickers:
            s_table.add_column(t, justify="right")
        for sector in sorted(all_sectors):
            s_table.add_row(
                sector,
                *[f"{etf_sectors[t].get(sector, 0):.1f}%" for t in tickers],
            )
        console.print(s_table)


def render_dip_alert(
    vix_data: dict,
    margin_rule: tuple[float, str] | None,
    sma_data: dict[str, dict],
    sma_days: int = 200,
    total_market_value: float = 0.0,
    max_margin_pool: float = 0.0,
    used_margin: float = 0.0,
) -> None:
    """Render the market dip alert: VIX gauge, margin signal, and SMA dip candidates."""
    from rich.console import Group
    from rich.rule import Rule

    # ── Panel 1: VIX Fear Gauge ──
    vix = vix_data.get("current")
    change = vix_data.get("change_1d", 0.0)

    if vix is not None:
        if vix < 20:
            vix_color, vix_label = "green", "LOW VOLATILITY"
        elif vix < 30:
            vix_color, vix_label = "yellow", "MODERATE VOLATILITY"
        else:
            vix_color, vix_label = "red", "HIGH VOLATILITY"

        change_sign = "+" if change >= 0 else ""
        change_color = "red" if change > 0 else "green"

        console.print(Panel(
            Text.assemble(
                ("  VIX:      ", "bold"), (f"{vix:.2f}", f"bold {vix_color}"),
                (f"   [{vix_label}]", vix_color), ("\n", ""),
                ("  1d Change: ", "bold"), (f"{change_sign}{change:.2f}", change_color),
            ),
            title="[bold cyan]VIX Fear Gauge[/bold cyan]",
            border_style=vix_color,
        ))
    else:
        console.print(Panel(
            "[yellow]Could not fetch VIX data.[/yellow]",
            title="[bold cyan]VIX Fear Gauge[/bold cyan]",
            border_style="yellow",
        ))

    # ── Panel 2: Margin Deployment Signal ──
    if margin_rule is not None:
        deploy_pct, label = margin_rule
        if deploy_pct >= 0.65:
            signal_color = "red"
        elif deploy_pct >= 0.45:
            signal_color = "yellow"
        else:
            signal_color = "cyan"

        parts: list[tuple[str, str]] = [
            ("  Signal:     ", "bold"), (label, f"bold {signal_color}"), ("\n", ""),
            ("  VIX rule:   ", "bold"), (f"deploy {deploy_pct:.0%} of margin pool", signal_color), ("\n", ""),
        ]
        if max_margin_pool > 0:
            from .config import MAX_MARGIN_PCT
            deploy_now = max_margin_pool * deploy_pct
            remaining_capacity = max(max_margin_pool - used_margin, 0.0)
            can_deploy = min(deploy_now, remaining_capacity)
            used_pct = (used_margin / max_margin_pool * 100) if max_margin_pool > 0 else 0.0
            used_color = "red" if used_pct > 80 else "yellow" if used_pct > 40 else "green"

            parts += [
                ("  Margin pool:   ", "bold"), (f"${max_margin_pool:,.0f}", "white"),
                (f"  ({MAX_MARGIN_PCT:.0%} of ${total_market_value:,.0f} portfolio — hard cap)\n", "dim"),
                ("  Used margin:   ", "bold"), (f"${used_margin:,.0f}", used_color),
                (f"  ({used_pct:.1f}% of pool deployed)\n", "dim"),
                ("  Remaining:     ", "bold"), (f"${remaining_capacity:,.0f}", "white"),
                ("  available\n", "dim"),
                ("  Target deploy: ", "bold"), (f"${deploy_now:,.0f}", f"bold {signal_color}"),
                (f"  ({deploy_pct:.0%} of pool per VIX rule)\n", "dim"),
                ("  Can deploy:    ", "bold"), (f"${can_deploy:,.0f}", f"bold {signal_color}"),
                ("  (remaining capacity, capped at target)", "dim"),
            ]

        console.print(Panel(
            Text.assemble(*parts),
            title="[bold cyan]Margin Deployment Signal[/bold cyan]",
            border_style=signal_color,
        ))
    else:
        console.print(Panel(
            Text.assemble(
                ("  Signal:  ", "bold"), ("LOW FEAR", "bold green"), ("\n", ""),
                ("  Deploy:  ", "bold"), ("0% — no margin deployment", "green"),
            ),
            title="[bold cyan]Margin Deployment Signal[/bold cyan]",
            border_style="green",
        ))

    # ── Panel 3: SMA Dip Candidates ──
    below = [(t, d) for t, d in sorted(sma_data.items()) if d["pct_from_sma"] < 0]

    if below:
        table = Table(
            title=f"Dip Candidates — Below {sma_days}-Day SMA",
            show_lines=True,
            header_style="bold cyan",
        )
        table.add_column("Ticker", style="bold")
        table.add_column("Price", justify="right")
        table.add_column(f"{sma_days}d SMA", justify="right")
        table.add_column("vs SMA", justify="right")

        for ticker, d in below:
            pct = d["pct_from_sma"]
            table.add_row(
                ticker,
                f"${d['current_price']:.2f}",
                f"${d['sma']:.2f}",
                Text(f"{pct:+.2f}%", style="red"),
            )
        console.print(table)
    else:
        console.print(f"[dim]No portfolio positions are below their {sma_days}-day SMA.[/dim]")

    # ── Summary ──
    vix_str = f"{vix:.1f}" if vix is not None else "N/A"
    deploy_pct_val = margin_rule[0] if margin_rule else 0.0
    deploy_str = f"{deploy_pct_val:.0%}" if margin_rule else "0%"
    label_str = margin_rule[1] if margin_rule else "LOW FEAR"
    below_count = len(below)
    below_tickers = ", ".join(t for t, _ in below) if below else "none"

    margin_summary = ""
    if max_margin_pool > 0:
        if margin_rule:
            deploy_now = max_margin_pool * deploy_pct_val
            remaining_capacity = max(max_margin_pool - used_margin, 0.0)
            can_deploy = min(deploy_now, remaining_capacity)
            margin_summary = (
                f" → pool [bold]${max_margin_pool:,.0f}[/bold]"
                f" | used [bold]${used_margin:,.0f}[/bold]"
                f" | can deploy [bold]${can_deploy:,.0f}[/bold]"
            )
        else:
            remaining_capacity = max(max_margin_pool - used_margin, 0.0)
            margin_summary = (
                f" → pool [bold]${max_margin_pool:,.0f}[/bold]"
                f" | used [bold]${used_margin:,.0f}[/bold]"
                f" | remaining [bold]${remaining_capacity:,.0f}[/bold]"
            )

    console.print(Panel(
        f"[bold]VIX at {vix_str}[/bold] → [bold]{label_str}[/bold] → "
        f"[bold]{deploy_str}[/bold] of margin pool"
        f"{margin_summary} → "
        f"[bold]{below_count}[/bold] position(s) below {sma_days}d SMA: {below_tickers}",
        title="[bold magenta]Strategy Summary[/bold magenta]",
        border_style="magenta",
    ))


def render_portfolio_overlap(
    stock_tickers: list[str],
    etf_holdings: dict[str, list[dict]],
    portfolio_weights: dict[str, float],
) -> None:
    """Show overlap between individual stock holdings and ETF holdings."""
    from rich.console import Group
    from rich.rule import Rule

    if not etf_holdings:
        console.print("[yellow]No ETF holdings data available.[/yellow]")
        return

    stock_set = {t.upper() for t in stock_tickers}

    # Build overlap: {stock: {etf: weight_in_etf}}
    overlap: dict[str, dict[str, float]] = {}
    for etf_ticker, holdings in etf_holdings.items():
        for h in holdings:
            symbol = h.get("symbol", "").upper()
            pct = h.get("holdingPercent")
            if symbol in stock_set and pct is not None:
                overlap.setdefault(symbol, {})[etf_ticker] = pct

    etf_tickers = sorted(etf_holdings.keys())

    # ── Overlap Detail Table ──
    if overlap:
        table = Table(
            title="Portfolio Overlap — Stocks You Hold Individually AND via ETFs",
            show_lines=True,
            header_style="bold cyan",
        )
        table.add_column("Stock", style="bold")
        table.add_column("Direct Weight", justify="right")
        for etf in etf_tickers:
            table.add_column(f"In {etf}", justify="right")
        table.add_column("Effective Exposure", justify="right")

        sorted_overlap = sorted(overlap.items(), key=lambda x: -len(x[1]))
        for stock, etf_map in sorted_overlap:
            direct_wt = portfolio_weights.get(stock, 0.0)
            # Effective = direct weight + sum(etf_portfolio_weight * stock_weight_in_etf)
            indirect = 0.0
            cells: list = [stock, f"{direct_wt:.1f}%"]
            for etf in etf_tickers:
                if etf in etf_map:
                    wt_in_etf = etf_map[etf] * 100  # holdingPercent is decimal
                    etf_portfolio_wt = portfolio_weights.get(etf, 0.0)
                    contribution = etf_portfolio_wt * etf_map[etf]  # % of portfolio via this ETF
                    indirect += contribution
                    cells.append(Text(f"{wt_in_etf:.1f}%", style="yellow"))
                else:
                    cells.append(Text("—", style="dim"))

            effective = direct_wt + indirect
            cells.append(Text(f"{effective:.1f}%", style="bold green"))
            table.add_row(*cells)

        console.print(table)

        # ── Summary Panel ──
        total_direct = sum(portfolio_weights.get(s, 0.0) for s in overlap)
        total_effective = 0.0
        for stock, etf_map in overlap.items():
            direct = portfolio_weights.get(stock, 0.0)
            indirect = sum(
                portfolio_weights.get(etf, 0.0) * pct
                for etf, pct in etf_map.items()
            )
            total_effective += direct + indirect

        redundancy = total_effective - total_direct
        console.print(Panel(
            f"[bold]{len(overlap)}[/bold] of your [bold]{len(stock_set)}[/bold] individual stocks "
            f"also appear in your ETF holdings.\n"
            f"[bold]Direct exposure:[/bold] {total_direct:.1f}%   "
            f"[bold]Effective (with ETF):[/bold] {total_effective:.1f}%   "
            f"[bold yellow]Redundant overlap:[/bold yellow] +{redundancy:.1f}%\n"
            f"[dim]↳ Effective exposure includes your direct weight plus the indirect weight "
            f"through ETFs (ETF portfolio weight × stock's weight in that ETF).[/dim]",
            title="[bold yellow]Overlap Summary[/bold yellow]",
            border_style="yellow",
        ))
    else:
        console.print(Panel(
            "[green]No overlap found between your individual stocks and ETF holdings.[/green]\n"
            "[dim]Note: Based on top holdings reported by yfinance (not full fund composition).[/dim]",
            border_style="green",
        ))

    # ── ETFs with no holdings data ──
    no_data = [etf for etf in etf_tickers if not etf_holdings.get(etf)]
    if no_data:
        console.print(
            f"[dim]No holdings data available for: {', '.join(no_data)} "
            f"(yfinance may not report holdings for all ETFs)[/dim]"
        )


def render_owner_earnings(snapshots: list[OwnerEarningsSnapshot]) -> None:
    """Render Owner Earnings analysis — one panel per ticker with plain English hints."""
    if not snapshots:
        console.print("[yellow]No owner earnings data available for the given tickers.[/yellow]")
        return

    for snap in snapshots:
        _render_one_owner_earnings(snap)

    # ── Comparison table if multiple tickers ──
    if len(snapshots) > 1:
        _render_owner_earnings_comparison(snapshots)


def _render_one_owner_earnings(snap: OwnerEarningsSnapshot) -> None:
    from rich.console import Group
    from rich.rule import Rule

    lines: list = []

    def hint(text: str) -> None:
        lines.append(Text(f"  {text}", style="dim italic"))

    # ── Header ──
    price_str = f"${snap.current_price:.2f}" if snap.current_price else "N/A"
    mktcap_str = _fmt_large(snap.market_cap)
    sector_str = snap.sector or "Unknown"
    lines.append(Text.assemble(
        ("  Price: ", "bold"), (price_str, "cyan"),
        ("   Market Cap: ", "bold"), (mktcap_str, "cyan"),
        ("   Sector: ", "bold"), (sector_str, ""),
    ))
    lines.append(Text(""))

    # ── 1. The Formula Breakdown ──
    lines.append(Rule(" 1. What does this business really earn? ", style="cyan"))
    hint("Reported profit can be misleading. Owner Earnings shows the actual")
    hint("cash the business generates for its owners after keeping the lights on.")
    lines.append(Text(""))

    ni_str = _fmt_large(snap.net_income)
    dep_str = _fmt_large(snap.depreciation)
    capex_str = _fmt_large(abs(snap.capex)) if snap.capex else "N/A"
    wc_str = _fmt_large(abs(snap.working_capital_change)) if snap.working_capital_change is not None else "N/A"
    wc_sign = "+" if (snap.working_capital_change or 0) <= 0 else "-"
    oe_str = _fmt_large(snap.owner_earnings)

    lines.append(Text("  The formula:", style="bold"))
    lines.append(Text.assemble(
        ("    Reported profit (net income):     ", ""), (ni_str, "white"),
    ))
    lines.append(Text.assemble(
        ("  + Depreciation (non-cash expense):  ", ""), (f"+{dep_str}", "green"),
    ))
    hint("    Money the company 'expensed' on paper but didn't actually spend this year.")
    lines.append(Text.assemble(
        ("  - Capital spending (to keep running): ", ""), (f"-{capex_str}", "red"),
    ))
    hint("    What the company must spend on equipment, buildings, etc. to stay competitive.")
    wc_color = "green" if (snap.working_capital_change or 0) <= 0 else "red"
    lines.append(Text.assemble(
        ("  ", ""), (f"{wc_sign} Working capital changes:         ", ""),
        (f"{wc_sign}{wc_str}", wc_color),
    ))
    hint("    Cash tied up (or freed) in day-to-day operations like inventory and receivables.")
    lines.append(Text("    " + "─" * 40))

    oe_color = "green" if snap.owner_earnings and snap.owner_earnings > 0 else "red"
    lines.append(Text.assemble(
        ("  = Owner Earnings:                   ", "bold"), (oe_str, f"bold {oe_color}"),
    ))
    if snap.oe_per_share is not None:
        lines.append(Text.assemble(
            ("    Per share: ", ""), (f"${snap.oe_per_share:.2f}", "cyan"),
        ))
    lines.append(Text(""))

    # ── 2. Reality Check: OE vs Reported Profit ──
    lines.append(Rule(" 2. Are the reported profits real? ", style="cyan"))
    lines.append(Text(""))

    if snap.oe_vs_net_income_pct is not None:
        diff = snap.oe_vs_net_income_pct
        if diff > 10:
            rc_color = "green"
            rc_verdict = "YES — This company earns MORE cash than it reports as profit."
            rc_detail = "The real cash coming in exceeds the accounting numbers. Solid."
        elif diff >= -10:
            rc_color = "yellow"
            rc_verdict = "MOSTLY — Cash earnings roughly match reported profits."
            rc_detail = "What you see is what you get. Straightforward business."
        else:
            rc_color = "red"
            rc_verdict = "CAUTION — Reported profits overstate the real cash earned."
            rc_detail = (
                f"The company reports {ni_str} in profit but only generates {oe_str} in cash. "
                "The gap means heavy spending or accounting adjustments eat into real returns."
            )

        lines.append(Text.assemble(("  ", ""), (rc_verdict, f"bold {rc_color}")))
        hint(rc_detail)
        lines.append(Text(""))
        lines.append(Text.assemble(
            ("  Owner Earnings vs Net Income: ", "bold"),
            (f"{diff:+.1f}%", rc_color),
            ("  (positive = OE exceeds reported profit)", "dim"),
        ))
    else:
        lines.append(Text("  Cannot compare — net income is zero or negative.", style="dim"))
    lines.append(Text(""))

    # ── 3. Owner Earnings Yield ──
    lines.append(Rule(" 3. What return are you getting for your money? ", style="cyan"))
    hint("Owner Earnings Yield = Owner Earnings / Market Cap.")
    hint("Think of it as: for every $100 you invest, how much real cash does the business produce?")
    lines.append(Text(""))

    if snap.oe_yield_pct is not None:
        yld = snap.oe_yield_pct
        if yld >= 8:
            y_color = "green"
            y_verdict = f"EXCELLENT — You get ${yld:.2f} of real cash for every $100 invested."
            y_detail = "This is a high-yield business at today's price. Great value territory."
        elif yld >= 4:
            y_color = "yellow"
            y_verdict = f"DECENT — You get ${yld:.2f} of real cash for every $100 invested."
            y_detail = "A fair return. Could be better, but the business may be growing."
        else:
            y_color = "red"
            y_verdict = f"LOW — You get only ${yld:.2f} of real cash for every $100 invested."
            y_detail = "You're paying a premium. Only worth it if the business is growing fast."

        lines.append(Text.assemble(("  ", ""), (y_verdict, f"bold {y_color}")))
        hint(y_detail)
        lines.append(Text(""))
        lines.append(Text.assemble(
            ("  Owner Earnings Yield: ", "bold"), (f"{yld:.2f}%", y_color),
        ))
    else:
        lines.append(Text("  Cannot calculate — owner earnings are zero or negative.", style="dim"))
    lines.append(Text(""))

    # ── 4. Capital Intensity ──
    lines.append(Rule(" 4. How much does it cost to keep this business running? ", style="cyan"))
    hint("Some businesses (like software) need very little reinvestment.")
    hint("Others (like airlines) must spend heavily just to maintain what they have.")
    lines.append(Text(""))

    if snap.capex_intensity_pct is not None:
        ci = snap.capex_intensity_pct
        if ci < 25:
            ci_color = "green"
            ci_label = "LIGHT"
            ci_verdict = "This business keeps most of what it earns. Very little goes to maintenance."
            ci_detail = "Like a toll bridge — once built, the cash just flows in."
        elif ci < 50:
            ci_color = "yellow"
            ci_label = "MODERATE"
            ci_verdict = "Reasonable reinvestment needs. The business keeps more than half its cash."
            ci_detail = "Manageable spending level. Watch that it doesn't creep up over time."
        else:
            ci_color = "red"
            ci_label = "HEAVY"
            ci_verdict = "This business eats most of its own cash just to stay competitive."
            ci_detail = "Like a factory that must constantly buy new machines. Less cash for you."

        lines.append(Text.assemble(
            ("  Capital Intensity: ", "bold"), (f"{ci:.0f}%", ci_color),
            (f"   [{ci_label}]", ci_color),
        ))
        hint(ci_verdict)
        hint(ci_detail)
    else:
        lines.append(Text("  Cannot calculate capital intensity.", style="dim"))
    lines.append(Text(""))

    # ── 5. Multi-Year Trend ──
    lines.append(Rule(" 5. Is the cash machine getting stronger or weaker? ", style="cyan"))
    hint("A great business generates more cash each year. Consistency is key.")
    lines.append(Text(""))

    if snap.years and len(snap.years) >= 2:
        # Trend mini-table
        trend_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False, padding=(0, 2))
        trend_table.add_column("Year", style="bold")
        trend_table.add_column("Net Income", justify="right")
        trend_table.add_column("Owner Earnings", justify="right")
        trend_table.add_column("OE vs NI", justify="right")

        # Show years in chronological order (oldest first)
        for y in reversed(snap.years):
            oe_val = y.owner_earnings
            ni_val = y.net_income
            oe_color_y = "green" if oe_val > 0 else "red"
            diff_y = ((oe_val / ni_val - 1) * 100) if ni_val and ni_val > 0 else None
            diff_str = f"{diff_y:+.0f}%" if diff_y is not None else "N/A"
            diff_color_y = "green" if diff_y is not None and diff_y > 0 else ("red" if diff_y is not None and diff_y < -10 else "yellow")

            trend_table.add_row(
                y.year[:4],
                _fmt_large(ni_val),
                Text(_fmt_large(oe_val), style=oe_color_y),
                Text(diff_str, style=diff_color_y),
            )

        lines.append(trend_table)
        lines.append(Text(""))

        # Trend verdict
        if snap.trend_direction:
            t_color = {"GROWING": "green", "STABLE": "yellow", "DECLINING": "red"}.get(snap.trend_direction, "white")
            trend_hints = {
                "GROWING": "The business is producing more cash each year. This is what you want to see.",
                "STABLE": "Cash generation is steady but not growing. Reliable, but watch for stagnation.",
                "DECLINING": "The business is generating less cash over time. Find out why before investing more.",
            }
            lines.append(Text.assemble(
                ("  Trend: ", "bold"), (snap.trend_direction, f"bold {t_color}"),
            ))
            hint(trend_hints.get(snap.trend_direction, ""))

        if snap.oe_growth_pct is not None:
            g_color = "green" if snap.oe_growth_pct > 0 else "red"
            lines.append(Text.assemble(
                ("  Last year growth: ", "bold"), (f"{snap.oe_growth_pct:+.1f}%", g_color),
            ))
        if snap.oe_cagr_pct is not None:
            c_color = "green" if snap.oe_cagr_pct > 0 else "red"
            n = len(snap.years) - 1
            lines.append(Text.assemble(
                (f"  {n}-year CAGR: ", "bold"), (f"{snap.oe_cagr_pct:+.1f}%", c_color),
                ("  (compound annual growth rate)", "dim"),
            ))
    else:
        lines.append(Text("  Not enough historical data for trend analysis.", style="dim"))

    lines.append(Text(""))

    # ── Bottom Line ──
    lines.append(Rule(" Bottom Line ", style="bold magenta"))
    lines.append(Text(""))

    verdicts = []
    if snap.oe_yield_pct is not None:
        if snap.oe_yield_pct >= 8:
            verdicts.append(("High cash yield at this price", "green"))
        elif snap.oe_yield_pct >= 4:
            verdicts.append(("Fair cash yield", "yellow"))
        else:
            verdicts.append(("Low cash yield — paying a premium", "red"))

    if snap.oe_vs_net_income_pct is not None:
        if snap.oe_vs_net_income_pct > 10:
            verdicts.append(("Profits are real and backed by cash", "green"))
        elif snap.oe_vs_net_income_pct >= -10:
            verdicts.append(("Cash roughly matches reported profits", "yellow"))
        else:
            verdicts.append(("Reported profits may be overstated", "red"))

    if snap.trend_direction == "GROWING":
        verdicts.append(("Cash generation is growing", "green"))
    elif snap.trend_direction == "DECLINING":
        verdicts.append(("Cash generation is declining", "red"))

    if snap.capex_intensity_pct is not None:
        if snap.capex_intensity_pct < 25:
            verdicts.append(("Light capital needs — cash cow", "green"))
        elif snap.capex_intensity_pct >= 50:
            verdicts.append(("Heavy reinvestment needed to compete", "red"))

    for verdict_text, color in verdicts:
        bullet = "+" if color == "green" else ("-" if color == "red" else "~")
        lines.append(Text.assemble(("  ", ""), (f" {bullet} ", f"bold {color}"), (verdict_text, color)))

    lines.append(Text(""))

    console.print(Panel(
        Group(*lines),
        title=f"[bold cyan]Owner Earnings: {snap.ticker}[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))


def _render_owner_earnings_comparison(snapshots: list[OwnerEarningsSnapshot]) -> None:
    """Render a side-by-side comparison table for multiple tickers."""
    table = Table(
        title="Owner Earnings — Side by Side",
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Metric", style="bold", min_width=28)
    for snap in snapshots:
        table.add_column(snap.ticker, justify="right", min_width=12)
    table.add_column("What it means", style="dim italic", min_width=30)

    # Row: Owner Earnings
    cells: list = ["Owner Earnings"]
    for snap in snapshots:
        color = "green" if snap.owner_earnings and snap.owner_earnings > 0 else "red"
        cells.append(Text(_fmt_large(snap.owner_earnings), style=color))
    cells.append("Real cash the business produces for owners")
    table.add_row(*cells)

    # Row: OE per Share
    cells = ["Per Share"]
    for snap in snapshots:
        cells.append(f"${snap.oe_per_share:.2f}" if snap.oe_per_share else "N/A")
    cells.append("Your share of the cash as a stockholder")
    table.add_row(*cells)

    # Row: OE Yield
    cells = ["Owner Earnings Yield"]
    for snap in snapshots:
        if snap.oe_yield_pct is not None:
            color = "green" if snap.oe_yield_pct >= 8 else ("yellow" if snap.oe_yield_pct >= 4 else "red")
            cells.append(Text(f"{snap.oe_yield_pct:.2f}%", style=color))
        else:
            cells.append(Text("N/A", style="dim"))
    cells.append("Cash return per $100 invested (higher = cheaper)")
    table.add_row(*cells)

    # Row: OE vs Net Income
    cells = ["OE vs Reported Profit"]
    for snap in snapshots:
        if snap.oe_vs_net_income_pct is not None:
            color = "green" if snap.oe_vs_net_income_pct > 10 else ("red" if snap.oe_vs_net_income_pct < -10 else "yellow")
            cells.append(Text(f"{snap.oe_vs_net_income_pct:+.0f}%", style=color))
        else:
            cells.append(Text("N/A", style="dim"))
    cells.append("Positive = profits are real, negative = inflated")
    table.add_row(*cells)

    # Row: Capital Intensity
    cells = ["Capital Intensity"]
    for snap in snapshots:
        if snap.capex_intensity_pct is not None:
            color = "green" if snap.capex_intensity_pct < 25 else ("red" if snap.capex_intensity_pct >= 50 else "yellow")
            cells.append(Text(f"{snap.capex_intensity_pct:.0f}%", style=color))
        else:
            cells.append(Text("N/A", style="dim"))
    cells.append("Low = cash cow, high = needs constant spending")
    table.add_row(*cells)

    # Row: Trend
    cells = ["Trend"]
    for snap in snapshots:
        t = snap.trend_direction or "N/A"
        color = {"GROWING": "green", "STABLE": "yellow", "DECLINING": "red"}.get(t, "dim")
        cells.append(Text(t, style=color))
    cells.append("Is the cash machine improving over time?")
    table.add_row(*cells)

    console.print(table)


def render_cash_secured_puts(snapshots: list[CashSecuredPutSnapshot]) -> None:
    """Render cash-secured put opportunities ranked by valuation attractiveness."""

    if not snapshots:
        console.print("[yellow]No put-selling opportunities found for portfolio stocks.[/yellow]")
        return

    # Sort by valuation attractiveness (best possible return first)
    ranked = sorted(
        snapshots,
        key=lambda s: s.possible_return_pct if s.possible_return_pct is not None else -999,
        reverse=True,
    )

    # ── Main Table ──
    table = Table(
        title="Cash-Secured Put Screener — Buffett Style",
        show_lines=True,
        header_style="bold cyan",
        caption="Sell puts on stocks you'd happily own for 5–10 years. If assigned, you buy at a discount.",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Ticker", style="bold")
    table.add_column("Beta", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Strike", justify="right")
    table.add_column("Exp (DTE)", justify="right")
    table.add_column("Premium", justify="right")
    table.add_column("Cash Req", justify="right")
    table.add_column("Return", justify="right")
    table.add_column("Annual.", justify="right")
    table.add_column("Eff. Buy", justify="right")
    table.add_column("Discount", justify="right")
    table.add_column("OI", justify="right")
    table.add_column("Valuation", justify="center")

    for i, snap in enumerate(ranked, 1):
        # Beta color: < 1 = green (less volatile), > 1.5 = red
        beta_str = f"{snap.beta:.2f}" if snap.beta is not None else "N/A"
        beta_color = "white"
        if snap.beta is not None:
            beta_color = "green" if snap.beta < 1 else ("yellow" if snap.beta < 1.5 else "red")

        # Return color: > 2% = green, 1-2% = yellow, < 1% = dim
        ret_color = "dim"
        if snap.return_pct is not None:
            ret_color = "green" if snap.return_pct >= 2 else ("yellow" if snap.return_pct >= 1 else "dim")

        # Annualized return color
        ann_color = "dim"
        if snap.annualized_return_pct is not None:
            ann_color = "green" if snap.annualized_return_pct >= 12 else (
                "yellow" if snap.annualized_return_pct >= 6 else "dim"
            )

        # Valuation verdict color
        verdict = snap.valuation_verdict or "N/A"
        verdict_color = "dim"
        if verdict == "STRONG BUY":
            verdict_color = "bold green"
        elif verdict == "GOOD VALUE":
            verdict_color = "green"
        elif verdict == "FAIR":
            verdict_color = "yellow"
        elif verdict == "OVERVALUED":
            verdict_color = "red"

        table.add_row(
            str(i),
            snap.ticker,
            Text(beta_str, style=beta_color),
            f"${snap.current_price:.2f}" if snap.current_price else "N/A",
            f"${snap.strike:.2f}" if snap.strike else "N/A",
            f"{snap.expiration} ({snap.dte}d)" if snap.expiration and snap.dte else "N/A",
            f"${snap.premium:.2f}" if snap.premium else "N/A",
            f"${snap.cash_required:,.0f}" if snap.cash_required else "N/A",
            Text(f"{snap.return_pct:.2f}%", style=ret_color) if snap.return_pct is not None else Text("N/A", style="dim"),
            Text(f"{snap.annualized_return_pct:.1f}%", style=ann_color) if snap.annualized_return_pct is not None else Text("N/A", style="dim"),
            f"${snap.effective_buy_price:.2f}" if snap.effective_buy_price else "N/A",
            Text(f"{snap.discount_pct:.1f}%", style="green") if snap.discount_pct is not None else Text("N/A", style="dim"),
            f"{snap.open_interest:,}" if snap.open_interest else "N/A",
            Text(verdict, style=verdict_color),
        )

    console.print(table)

    # ── Strategy Summary Panel ──
    strong = [s for s in ranked if s.valuation_verdict in ("STRONG BUY", "GOOD VALUE")]
    best_returns = sorted(
        [s for s in ranked if s.annualized_return_pct is not None],
        key=lambda s: s.annualized_return_pct,  # type: ignore[arg-type]
        reverse=True,
    )

    lines = []
    if strong:
        tickers_str = ", ".join(s.ticker for s in strong)
        lines.append(f"[bold green]Top value picks for puts:[/bold green] {tickers_str}")
    if best_returns:
        top = best_returns[0]
        lines.append(
            f"[bold]Best annualized return:[/bold] {top.ticker} at "
            f"{top.annualized_return_pct:.1f}% "
            f"(${top.premium:.2f} premium on ${top.strike:.2f} strike)"
        )
    total_cash = sum(s.cash_required for s in ranked if s.cash_required)
    lines.append(f"[bold]Total cash needed (all puts):[/bold] ${total_cash:,.0f}")
    lines.append(
        "[dim]Targets: ~5% OTM strikes, 30-45 DTE. "
        "If assigned, you own a great company at a discount.[/dim]"
    )

    console.print(Panel(
        "\n".join(lines),
        title="[bold magenta]Put-Selling Strategy Summary[/bold magenta]",
        border_style="magenta",
    ))


def _fmt_pct(value: float | None) -> str:
    """Format a decimal as percentage (0.0039 → '0.39%')."""
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _fmt_large(value: float | None) -> str:
    """Format large numbers as $X.XXB / $X.XXT / $X.XXM."""
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:.2f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:.2f}M"
    return f"{sign}${abs_val:,.0f}"
