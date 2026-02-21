from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analysis import FundamentalSnapshot, ValuationSnapshot, score_ticker, pe_category, cash_debt_rating
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


def render_portfolio_summary(snapshot: PortfolioSnapshot) -> None:
    table = Table(
        title="Portfolio Summary",
        show_lines=True,
        header_style="bold cyan",
        show_footer=True,
    )
    table.add_column("Ticker", style="bold")
    table.add_column("Shares", justify="right")
    table.add_column("Cost/Share", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Market Value", justify="right")
    table.add_column("Cost Value", justify="right")
    table.add_column("Unrealized P&L", justify="right")
    table.add_column("P&L %", justify="right")
    table.add_column("Weight", justify="right")

    for ps in snapshot.positions:
        pnl_color = "green" if ps.unrealized_pnl >= 0 else "red"
        pnl_sign = "+" if ps.unrealized_pnl >= 0 else ""
        pnl_pct_sign = "+" if ps.unrealized_pnl_pct >= 0 else ""
        table.add_row(
            ps.ticker,
            f"{ps.shares:.4f}",
            f"${ps.cost_basis:.2f}",
            f"${ps.current_price:.2f}",
            f"${ps.market_value:,.2f}",
            f"${ps.cost_value:,.2f}",
            Text(f"{pnl_sign}${ps.unrealized_pnl:,.2f}", style=pnl_color),
            Text(f"{pnl_pct_sign}{ps.unrealized_pnl_pct:.2f}%", style=pnl_color),
            f"{ps.current_weight:.1f}%",
        )

    total_pnl_color = "green" if snapshot.total_unrealized_pnl >= 0 else "red"
    total_sign = "+" if snapshot.total_unrealized_pnl >= 0 else ""
    total_pct_sign = "+" if snapshot.total_unrealized_pnl_pct >= 0 else ""

    table.columns[0].footer = Text("TOTAL", style="bold")
    table.columns[4].footer = Text(f"${snapshot.total_market_value:,.2f}", style="bold")
    table.columns[5].footer = Text(f"${snapshot.total_cost_value:,.2f}", style="bold")
    table.columns[6].footer = Text(
        f"{total_sign}${snapshot.total_unrealized_pnl:,.2f}", style=f"bold {total_pnl_color}"
    )
    table.columns[7].footer = Text(
        f"{total_pct_sign}{snapshot.total_unrealized_pnl_pct:.2f}%",
        style=f"bold {total_pnl_color}",
    )

    console.print(table)


def render_allocation(snapshot: PortfolioSnapshot) -> None:
    # Ticker allocation table
    alloc_table = Table(title="Allocation", show_lines=True, header_style="bold cyan")
    alloc_table.add_column("Ticker", style="bold")
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
    lines.append(Text(""))

    # ── 3. Revenue Estimate Next Year ────────────────────────────────────
    lines.append(Rule(" 3. Revenue Estimate — Next Year (Analyst Avg) ", style="cyan"))
    hint("Consistent revenue growth signals a durable business. The foundation of long-term compounding.")
    rev_str = _fmt_large(snap.next_year_revenue_est) if snap.next_year_revenue_est else "Not available"
    lines.append(Text(""))
    lines.append(Text.assemble(("  Analyst Avg Revenue: ", "bold"), (rev_str, "white")))
    lines.append(Text(""))

    # ── 4. Profit Margin ─────────────────────────────────────────────────
    lines.append(Rule(" 4. Profit Margin ", style="cyan"))
    hint("Of every $1 in sales, how much becomes profit. High margins = pricing power and competitive moat.")
    margin_str = f"{snap.profit_margin:.2%}" if snap.profit_margin else "N/A"
    margin_color = "green" if (snap.profit_margin or 0) > 0.20 else ("yellow" if (snap.profit_margin or 0) > 0.05 else "red")
    margin_label = "STRONG" if (snap.profit_margin or 0) > 0.20 else ("MODERATE" if (snap.profit_margin or 0) > 0.05 else "THIN")
    lines.append(Text(""))
    lines.append(Text.assemble(
        ("  Profit Margin: ", "bold"), (margin_str, margin_color),
        (f"   [{margin_label}]", margin_color),
    ))
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

    console.print(Panel(
        Group(*lines),
        title=f"[bold cyan]Valuación de Activos: {snap.ticker}[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))


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
