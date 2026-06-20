from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from . import __version__
from .config import DEFAULT_HORIZON_DAYS

app = typer.Typer(
    name="stocktool",
    help="Stock market mid-term analysis and portfolio tracker.",
    no_args_is_help=True,
)
portfolio_app = typer.Typer(help="Portfolio management commands.", no_args_is_help=True)
app.add_typer(portfolio_app, name="portfolio")

etf_app = typer.Typer(help="ETF analysis commands.", no_args_is_help=True)
app.add_typer(etf_app, name="etf")

strategy_app = typer.Typer(help="Investment strategy commands.", no_args_is_help=True)
app.add_typer(strategy_app, name="strategy")

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"stocktool v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=_version_callback, is_eager=True
    ),
) -> None:
    pass


# ---------------------------------------------------------------------------
# stocktool analyze
# ---------------------------------------------------------------------------

@app.command()
def analyze(
    tickers: list[str] = typer.Argument(..., help="One or more ticker symbols."),
    horizon: int = typer.Option(DEFAULT_HORIZON_DAYS, "--horizon", "-h", help="Lookback window in days."),
    scores: bool = typer.Option(False, "--scores", "-s", help="Color-code values by quality scores."),
    html: bool = typer.Option(False, "--html", is_flag=True, help="Export a self-contained HTML report to the default path."),
    html_path: Optional[str] = typer.Option(None, "--html-path", help="Custom path for the HTML report (implies --html)."),
) -> None:
    """Fetch fundamental data and display an analysis table."""
    from . import data, analysis, display

    tickers = [t.upper() for t in tickers]
    with console.status(f"Fetching data for {', '.join(tickers)}..."):
        fundamentals = data.fetch_fundamentals(tickers)
        history = data.fetch_price_history(tickers, horizon)

    snapshots = [
        analysis.build_snapshot(t, fundamentals.get(t, {}), history, horizon)
        for t in tickers
    ]
    display.render_fundamental_table(snapshots, show_scores=scores, horizon_days=horizon)

    if html or html_path:
        from .html_report import generate_html_report
        out = generate_html_report(snapshots, output_path=html_path or None)
        console.print(f"[green]HTML report saved:[/green] {out}")


# ---------------------------------------------------------------------------
# stocktool valuation
# ---------------------------------------------------------------------------

@app.command()
def valuation(
    tickers: list[str] = typer.Argument(..., help="One or more ticker symbols."),
    html: bool = typer.Option(False, "--html", is_flag=True, help="Export a self-contained HTML report to the default path."),
    html_path: Optional[str] = typer.Option(None, "--html-path", help="Custom path for the HTML report (implies --html)."),
) -> None:
    """Valuation template: PE category, cash/debt health, future market cap & possible return.

    Applies your valuation formula:
      Projected Earnings  = Next-Year Revenue Estimate × Profit Margin
      Future Market Cap   = Projected Earnings × 6-Month Avg PE
      Possible Return     = Future Market Cap / Current Market Cap - 1
    """
    from . import data, analysis, display

    tickers = [t.upper() for t in tickers]
    with console.status(f"Fetching valuation data for {', '.join(tickers)}..."):
        fundamentals = data.fetch_fundamentals(tickers)
        history_6m = data.fetch_price_history(tickers, horizon_days=180)
        revenue_estimates = data.fetch_revenue_estimates(tickers)
        balance_sheets = data.fetch_balance_sheets(tickers)

    snapshots = [
        analysis.build_valuation_snapshot(
            t,
            fundamentals.get(t, {}),
            history_6m,
            revenue_estimates.get(t),
            balance_sheets.get(t, {}),
        )
        for t in tickers
    ]
    display.render_valuation(snapshots)

    if html or html_path:
        from .html_report import generate_html_report
        out = generate_html_report(snapshots, output_path=html_path or None)
        console.print(f"[green]HTML report saved:[/green] {out}")


# ---------------------------------------------------------------------------
# stocktool value
# ---------------------------------------------------------------------------

@app.command()
def value(
    tickers: list[str] = typer.Argument(..., help="One or more ticker symbols."),
) -> None:
    """Quick value check: P/E, P/B, P/FCF with color-coded value-investor hints."""
    from . import data, analysis, display

    tickers = [t.upper() for t in tickers]
    with console.status(f"Fetching data for {', '.join(tickers)}..."):
        fundamentals = data.fetch_fundamentals(tickers)

    snapshots = [
        analysis.build_value_check_snapshot(t, fundamentals.get(t, {}))
        for t in tickers
    ]
    display.render_value_check(snapshots)


# ---------------------------------------------------------------------------
# stocktool compare
# ---------------------------------------------------------------------------

@app.command()
def compare(
    tickers: list[str] = typer.Argument(..., help="Two or more ticker symbols to compare."),
    horizon: int = typer.Option(DEFAULT_HORIZON_DAYS, "--horizon", "-h", help="Lookback window in days."),
) -> None:
    """Compare multiple tickers side-by-side with color-coded scores."""
    from . import data, analysis, display

    if len(tickers) < 2:
        console.print("[red]Provide at least 2 tickers to compare.[/red]")
        raise typer.Exit(1)

    tickers = [t.upper() for t in tickers]
    with console.status(f"Fetching data for {', '.join(tickers)}..."):
        fundamentals = data.fetch_fundamentals(tickers)
        history = data.fetch_price_history(tickers, horizon)

    snapshots = [
        analysis.build_snapshot(t, fundamentals.get(t, {}), history, horizon)
        for t in tickers
    ]
    display.render_compare_table(snapshots, horizon_days=horizon)


# ---------------------------------------------------------------------------
# stocktool portfolio show
# ---------------------------------------------------------------------------

@portfolio_app.command("show")
def portfolio_show(
    horizon: int = typer.Option(DEFAULT_HORIZON_DAYS, "--horizon", "-h", help="Lookback window in days."),
    no_chart: bool = typer.Option(False, "--no-chart", help="Skip the allocation pie chart."),
) -> None:
    """Display portfolio P&L summary and allocation."""
    from . import data, display
    from .portfolio import load_portfolio, build_portfolio_snapshot

    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print("[yellow]Portfolio is empty. Add positions with `stocktool portfolio add`.[/yellow]")
        raise typer.Exit()

    tickers = portfolio.tickers()
    with console.status("Fetching current prices..."):
        prices = data.get_current_prices(tickers)
        fundamentals = data.fetch_fundamentals(tickers)

    sector_map = {t: fundamentals.get(t, {}).get("sector") for t in tickers}
    snapshot = build_portfolio_snapshot(portfolio, prices, sector_map)

    display.render_portfolio_summary(snapshot)
    display.render_allocation(snapshot)

    if not no_chart:
        display.render_pie_chart(snapshot)


# ---------------------------------------------------------------------------
# stocktool portfolio add
# ---------------------------------------------------------------------------

@portfolio_app.command("add")
def portfolio_add(
    ticker: str = typer.Argument(..., help="Ticker symbol."),
    shares: float = typer.Argument(..., help="Number of shares."),
    cost_per_share: float = typer.Argument(..., help="Cost per share (purchase price)."),
    etf: bool = typer.Option(False, "--etf", help="Mark this position as an ETF."),
) -> None:
    """Add shares to the portfolio (weighted-average cost basis if ticker exists)."""
    from .portfolio import load_portfolio, save_portfolio

    if shares <= 0 or cost_per_share <= 0:
        console.print("[red]Shares and cost-per-share must be positive.[/red]")
        raise typer.Exit(1)

    portfolio = load_portfolio()
    portfolio.add_position(ticker.upper(), shares, cost_per_share, is_etf=etf)
    save_portfolio(portfolio)
    label = " (ETF)" if etf else ""
    console.print(f"[green]Added {shares} shares of {ticker.upper()}{label} at ${cost_per_share:.2f}.[/green]")


# ---------------------------------------------------------------------------
# stocktool portfolio sell
# ---------------------------------------------------------------------------

@portfolio_app.command("sell")
def portfolio_sell(
    ticker: str = typer.Argument(..., help="Ticker symbol."),
    shares: float = typer.Argument(..., help="Number of shares to sell."),
) -> None:
    """Sell (reduce) shares from an existing position. Cost basis stays unchanged."""
    from .portfolio import load_portfolio, save_portfolio

    if shares <= 0:
        console.print("[red]Shares must be positive.[/red]")
        raise typer.Exit(1)

    portfolio = load_portfolio()
    ok, msg = portfolio.sell_shares(ticker.upper(), shares)
    if ok:
        save_portfolio(portfolio)
        console.print(f"[green]{msg}[/green]")
    else:
        console.print(f"[yellow]{msg}[/yellow]")


# ---------------------------------------------------------------------------
# stocktool portfolio remove
# ---------------------------------------------------------------------------

@portfolio_app.command("remove")
def portfolio_remove(
    ticker: str = typer.Argument(..., help="Ticker symbol to remove."),
) -> None:
    """Remove a position entirely from the portfolio."""
    from .portfolio import load_portfolio, save_portfolio

    portfolio = load_portfolio()
    removed = portfolio.remove_position(ticker.upper())
    if removed:
        save_portfolio(portfolio)
        console.print(f"[green]Removed {ticker.upper()} from portfolio.[/green]")
    else:
        console.print(f"[yellow]{ticker.upper()} not found in portfolio.[/yellow]")


# ---------------------------------------------------------------------------
# stocktool portfolio target
# ---------------------------------------------------------------------------

@portfolio_app.command("target")
def portfolio_target(
    ticker: str = typer.Argument(..., help="Ticker symbol."),
    weight: float = typer.Argument(..., help="Target weight as a percentage (e.g. 30 for 30%)."),
) -> None:
    """Set a target allocation weight for a ticker."""
    from .portfolio import load_portfolio, save_portfolio

    if not (0 <= weight <= 100):
        console.print("[red]Weight must be between 0 and 100.[/red]")
        raise typer.Exit(1)

    portfolio = load_portfolio()
    ok = portfolio.set_target_weight(ticker.upper(), weight)
    if ok:
        save_portfolio(portfolio)
        console.print(f"[green]Set target weight for {ticker.upper()} to {weight:.1f}%.[/green]")
    else:
        console.print(f"[yellow]{ticker.upper()} not found in portfolio. Add it first.[/yellow]")


# ---------------------------------------------------------------------------
# stocktool portfolio rebalance
# ---------------------------------------------------------------------------

@portfolio_app.command("rebalance")
def portfolio_rebalance() -> None:
    """Show rebalancing signals based on target weights."""
    from . import data, display
    from .portfolio import load_portfolio, build_portfolio_snapshot

    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print("[yellow]Portfolio is empty.[/yellow]")
        raise typer.Exit()

    tickers = portfolio.tickers()
    with console.status("Fetching current prices..."):
        prices = data.get_current_prices(tickers)
        fundamentals = data.fetch_fundamentals(tickers)

    sector_map = {t: fundamentals.get(t, {}).get("sector") for t in tickers}
    snapshot = build_portfolio_snapshot(portfolio, prices, sector_map)
    display.render_rebalancing_signals(snapshot)


# ---------------------------------------------------------------------------
# stocktool portfolio sma
# ---------------------------------------------------------------------------

@portfolio_app.command("sma")
def portfolio_sma(
    days: int = typer.Option(200, "--days", "-d", help="SMA window in trading days."),
) -> None:
    """Screen portfolio positions against the 200-day SMA.

    Lists all positions and highlights those trading BELOW their moving average
    — potential buy opportunities for long-term value investors.
    """
    from . import data, display
    from .portfolio import load_portfolio

    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print("[yellow]Portfolio is empty. Add positions with `stocktool portfolio add`.[/yellow]")
        raise typer.Exit()

    tickers = portfolio.tickers()
    with console.status(f"Fetching {days}-day SMA for {', '.join(tickers)}..."):
        sma_data = data.fetch_sma_data(tickers, sma_days=days)

    display.render_sma_screen(sma_data, sma_days=days)


# ---------------------------------------------------------------------------
# stocktool portfolio overlap
# ---------------------------------------------------------------------------

@portfolio_app.command("overlap")
def portfolio_overlap() -> None:
    """Show overlap between individual stocks and ETF holdings in the portfolio.

    Identifies stocks you hold directly AND indirectly through ETFs,
    calculates effective exposure, and highlights redundant overlap.
    """
    from . import data, display
    from .portfolio import load_portfolio, build_portfolio_snapshot

    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print("[yellow]Portfolio is empty.[/yellow]")
        raise typer.Exit()

    etf_positions = [p for p in portfolio.positions if p.is_etf]
    stock_positions = [p for p in portfolio.positions if not p.is_etf]

    if not etf_positions:
        console.print("[yellow]No ETFs in portfolio. Nothing to check overlap against.[/yellow]")
        raise typer.Exit()
    if not stock_positions:
        console.print("[yellow]No individual stocks in portfolio. Nothing to check overlap for.[/yellow]")
        raise typer.Exit()

    tickers = portfolio.tickers()
    with console.status("Fetching ETF holdings and current prices..."):
        prices = data.get_current_prices(tickers)
        fundamentals = data.fetch_fundamentals(tickers)
        etf_holdings = data.fetch_portfolio_etf_holdings([p.ticker for p in etf_positions])

    sector_map = {t: fundamentals.get(t, {}).get("sector") for t in tickers}
    snapshot = build_portfolio_snapshot(portfolio, prices, sector_map)
    portfolio_weights = {ps.ticker: ps.current_weight for ps in snapshot.positions}

    display.render_portfolio_overlap(
        stock_tickers=[p.ticker for p in stock_positions],
        etf_holdings=etf_holdings,
        portfolio_weights=portfolio_weights,
    )


# ---------------------------------------------------------------------------
# stocktool portfolio analyze
# ---------------------------------------------------------------------------

@portfolio_app.command("analyze")
def portfolio_analyze(
    horizon: int = typer.Option(DEFAULT_HORIZON_DAYS, "--horizon", "-h", help="Lookback window in days."),
    scores: bool = typer.Option(False, "--scores", "-s", help="Color-code values by quality scores."),
) -> None:
    """Run fundamental analysis on all portfolio tickers."""
    from . import data, analysis, display
    from .portfolio import load_portfolio

    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print("[yellow]Portfolio is empty.[/yellow]")
        raise typer.Exit()

    tickers = portfolio.tickers()
    with console.status(f"Fetching data for portfolio ({', '.join(tickers)})..."):
        fundamentals = data.fetch_fundamentals(tickers)
        history = data.fetch_price_history(tickers, horizon)

    snapshots = [
        analysis.build_snapshot(t, fundamentals.get(t, {}), history, horizon)
        for t in tickers
    ]
    display.render_fundamental_table(snapshots, show_scores=scores, horizon_days=horizon)


# ---------------------------------------------------------------------------
# stocktool portfolio migrate
# ---------------------------------------------------------------------------

@portfolio_app.command("migrate")
def portfolio_migrate() -> None:
    """Migrate portfolio from local JSON to Google Sheets."""
    from .config import sheets_configured
    from .portfolio import load_portfolio_json
    from .sheets import save_portfolio_to_sheet

    if not sheets_configured():
        console.print(
            "[red]Google Sheets not configured.[/red]\n"
            "Place your service account credentials at ~/.config/stocktool/credentials.json\n"
            "and set GOOGLE_SHEETS_CREDENTIALS_FILE in .env"
        )
        raise typer.Exit(1)

    portfolio = load_portfolio_json()
    if not portfolio.positions:
        console.print("[yellow]Local JSON portfolio is empty. Nothing to migrate.[/yellow]")
        raise typer.Exit()

    with console.status("Migrating portfolio to Google Sheets..."):
        save_portfolio_to_sheet(portfolio)

    console.print(
        f"[green]Migrated {len(portfolio.positions)} position(s) to Google Sheets.[/green]"
    )


# ---------------------------------------------------------------------------
# stocktool etf compare
# ---------------------------------------------------------------------------

@etf_app.command("compare")
def etf_compare(
    tickers: list[str] = typer.Argument(..., help="Two or more ETF ticker symbols to compare."),
) -> None:
    """Compare ETFs: expense ratios, holdings overlap, sector breakdown, and performance."""
    from . import data, display

    if len(tickers) < 2:
        console.print("[red]Provide at least 2 ETF tickers to compare.[/red]")
        raise typer.Exit(1)

    tickers = [t.upper() for t in tickers]
    with console.status(f"Fetching ETF data for {', '.join(tickers)}..."):
        etf_info = data.fetch_etf_info(tickers)
        performance = data.fetch_etf_performance(tickers)

    holdings_map = {t: etf_info.get(t, {}).get("holdings", []) for t in tickers}
    overlap = data.compute_holdings_overlap(holdings_map)

    display.render_etf_compare(etf_info, performance, overlap)


# ---------------------------------------------------------------------------
# stocktool strategy dip
# ---------------------------------------------------------------------------

@strategy_app.command("dip")
def strategy_dip(
    sma_days: int = typer.Option(200, "--sma-days", "-d", help="SMA window in trading days."),
) -> None:
    """Market dip alert: VIX fear gauge + margin deployment rules + SMA dip candidates.

    Combines the CBOE VIX (fear index) with SMA screening to decide
    when and how much margin to deploy during market dips.
    """
    from . import data, display
    from .config import MARGIN_RULES, MAX_MARGIN_PCT
    from .portfolio import load_portfolio
    used_margin = data.get_used_margin()

    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print("[yellow]Portfolio is empty. Add positions with `stocktool portfolio add`.[/yellow]")
        raise typer.Exit()

    tickers = portfolio.tickers()
    with console.status("Fetching VIX and SMA data..."):
        vix_data = data.fetch_vix()
        sma_data = data.fetch_sma_data(tickers, sma_days=sma_days)

    # Determine which margin rule applies (highest threshold first)
    margin_rule: tuple[float, str] | None = None
    vix = vix_data.get("current")
    if vix is not None:
        for threshold, deploy_pct, label in MARGIN_RULES:
            if vix >= threshold:
                margin_rule = (deploy_pct, label)
                break

    # Compute total portfolio market value from sma_data prices + portfolio shares
    total_market_value = 0.0
    for pos in portfolio.positions:
        price = sma_data.get(pos.ticker, {}).get("current_price")
        if price:
            total_market_value += pos.shares * price

    max_margin_pool = total_market_value * MAX_MARGIN_PCT

    display.render_dip_alert(vix_data, margin_rule, sma_data, sma_days, total_market_value, max_margin_pool, used_margin)


# ---------------------------------------------------------------------------
# stocktool strategy margin
# ---------------------------------------------------------------------------

@strategy_app.command("margin")
def strategy_margin(
    amount: Optional[float] = typer.Argument(None, help="Set used margin amount in dollars (omit to show current status)."),
    reset: bool = typer.Option(False, "--reset", "-r", help="Reset used margin to $0."),
) -> None:
    """Track margin in use.

    Run with no arguments to show current margin status.
    Pass an amount to record how much margin you currently have deployed.

    Examples:
        stocktool strategy margin          # show current status
        stocktool strategy margin 3500     # record $3,500 used
        stocktool strategy margin --reset  # clear back to $0
    """
    from . import data
    from .config import MAX_MARGIN_PCT
    from .portfolio import load_portfolio

    if reset:
        data.set_used_margin(0.0)
        console.print("[green]Margin usage reset to $0.[/green]")
        return

    if amount is not None:
        if amount < 0:
            console.print("[red]Amount must be >= 0.[/red]")
            raise typer.Exit(1)
        data.set_used_margin(amount)
        console.print(f"[green]Used margin updated to [bold]${amount:,.0f}[/bold].[/green]")

    # Always show current status
    used = data.get_used_margin()
    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print(f"[bold]Used margin:[/bold] ${used:,.0f}  (no portfolio loaded for pool calculation)")
        return

    from . import data as _data
    tickers = portfolio.tickers()
    with console.status("Fetching prices..."):
        prices = _data.get_current_prices(tickers)

    total_value = sum(pos.shares * prices.get(pos.ticker, 0.0) for pos in portfolio.positions)
    pool = total_value * MAX_MARGIN_PCT
    remaining = max(pool - used, 0.0)
    used_pct = (used / pool * 100) if pool > 0 else 0.0

    from rich.table import Table
    table = Table(title="Margin Status", header_style="bold cyan", show_lines=True)
    table.add_column("Metric", style="bold")
    table.add_column("Amount", justify="right")
    table.add_column("Notes", style="dim")

    table.add_row("Portfolio Value", f"${total_value:,.0f}", "current market value")
    table.add_row(
        "Max Margin Pool",
        f"${pool:,.0f}",
        f"{MAX_MARGIN_PCT:.0%} of portfolio — your hard cap",
    )
    used_style = "red" if used_pct > 80 else "yellow" if used_pct > 40 else "green"
    table.add_row(
        "Used Margin",
        f"[{used_style}]${used:,.0f}[/{used_style}]",
        f"{used_pct:.1f}% of pool deployed",
    )
    table.add_row(
        "Remaining Capacity",
        f"[bold]${remaining:,.0f}[/bold]",
        "available to deploy",
    )
    console.print(table)
    console.print(
        f"\n[dim]Update with:[/dim] [bold]stocktool strategy margin <amount>[/bold]  "
        f"[dim]or[/dim] [bold]stocktool strategy margin --reset[/bold]"
    )


# ---------------------------------------------------------------------------
# stocktool owner-earnings
# ---------------------------------------------------------------------------

@app.command("owner-earnings")
def owner_earnings(
    tickers: list[str] = typer.Argument(..., help="One or more ticker symbols."),
    html: bool = typer.Option(False, "--html", is_flag=True, help="Export a self-contained HTML report to the default path."),
    html_path: Optional[str] = typer.Option(None, "--html-path", help="Custom path for the HTML report (implies --html)."),
) -> None:
    """Owner Earnings: what the business really earns in cash.

    Warren Buffett's preferred measure of true profitability.
    Unlike reported profit, Owner Earnings shows the actual cash
    a business generates for its owners after maintaining operations.

    Formula: Net Income + Depreciation - Capital Spending - Working Capital Changes

    Shows plain-English verdicts, multi-year trends, and a side-by-side
    comparison when analyzing multiple tickers.
    """
    from . import data, analysis, display

    tickers = [t.upper() for t in tickers]
    with console.status(f"Fetching cash flow data for {', '.join(tickers)}..."):
        oe_data = data.fetch_owner_earnings(tickers)

    snapshots: list[analysis.OwnerEarningsSnapshot] = []
    no_data: list[str] = []
    for t in tickers:
        snap = analysis.build_owner_earnings_snapshot(t, oe_data.get(t, {}))
        if snap:
            snapshots.append(snap)
        else:
            no_data.append(t)

    display.render_owner_earnings(snapshots)

    if no_data:
        console.print(f"[dim]No cash flow data available for: {', '.join(no_data)}[/dim]")

    if (html or html_path) and snapshots:
        from .html_report import generate_html_report
        out = generate_html_report(snapshots, output_path=html_path or None)
        console.print(f"[green]HTML report saved:[/green] {out}")


# ---------------------------------------------------------------------------
# stocktool strategy puts
# ---------------------------------------------------------------------------

@strategy_app.command("puts")
def strategy_puts(
    min_dte: int = typer.Option(30, "--min-dte", help="Minimum days to expiration."),
    max_dte: int = typer.Option(45, "--max-dte", help="Maximum days to expiration."),
    otm_pct: float = typer.Option(5.0, "--otm", help="Target OTM percentage below current price."),
) -> None:
    """Cash-secured put screener for portfolio stocks.

    Finds put-selling opportunities on stocks you'd happily own for 5-10 years.
    Ranks by valuation attractiveness (projected return from the valuation engine)
    so you sell puts on the best value stocks first.

    Shows: beta, strike, premium, cash required, return, annualized return,
    effective buy price (if assigned), and valuation verdict.
    """
    from . import data, analysis, display
    from .portfolio import load_portfolio

    portfolio = load_portfolio()
    if not portfolio.positions:
        console.print("[yellow]Portfolio is empty. Add positions with `stocktool portfolio add`.[/yellow]")
        raise typer.Exit()

    # Only screen individual stocks (not ETFs)
    stock_tickers = [p.ticker for p in portfolio.positions if not p.is_etf]
    if not stock_tickers:
        console.print("[yellow]No individual stocks in portfolio. Puts are for stocks you'd hold 5-10 years.[/yellow]")
        raise typer.Exit()

    with console.status(f"Fetching options & valuation data for {', '.join(stock_tickers)}..."):
        # Fetch put options
        put_data = data.fetch_put_candidates(stock_tickers, min_dte=min_dte, max_dte=max_dte)

        # Fetch valuation data for ranking
        fundamentals = data.fetch_fundamentals(stock_tickers)
        history_6m = data.fetch_price_history(stock_tickers, horizon_days=180)
        revenue_estimates = data.fetch_revenue_estimates(stock_tickers)
        balance_sheets = data.fetch_balance_sheets(stock_tickers)

    # Build valuation snapshots for ranking
    valuations = {
        t: analysis.build_valuation_snapshot(
            t, fundamentals.get(t, {}), history_6m,
            revenue_estimates.get(t), balance_sheets.get(t, {}),
        )
        for t in stock_tickers
    }

    # Build put snapshots
    snapshots: list[analysis.CashSecuredPutSnapshot] = []
    no_options: list[str] = []
    for t in stock_tickers:
        pd_entry = put_data.get(t, {})
        snap = analysis.build_csp_snapshot(t, pd_entry, valuations.get(t), target_otm_pct=otm_pct)
        if snap:
            snapshots.append(snap)
        else:
            no_options.append(t)

    display.render_cash_secured_puts(snapshots)

    if no_options:
        console.print(f"[dim]No options data available for: {', '.join(no_options)}[/dim]")


# ---------------------------------------------------------------------------
# stocktool docs  — quick-reference guide
# ---------------------------------------------------------------------------

@app.command("docs")
def docs() -> None:
    """Show a quick-reference guide for all commands, flags, and thresholds."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich import box

    console.print()
    console.print(Panel(
        "[bold cyan]stocktool[/bold cyan] — Mid-term stock fundamental analysis & portfolio tracker\n"
        "[dim]No API key required · powered by yfinance[/dim]",
        title="[bold]Quick Reference Guide[/bold]",
        border_style="cyan",
    ))

    # ── Commands ──────────────────────────────────────────────────────────────
    cmd_table = Table(title="Commands", box=box.SIMPLE_HEAVY, header_style="bold cyan", show_lines=False)
    cmd_table.add_column("Command", style="bold green", no_wrap=True)
    cmd_table.add_column("Description")
    cmd_table.add_column("Key Flags", style="dim")

    rows = [
        ("analyze AAPL MSFT",            "Fundamental data table",                          "--horizon 90  --scores"),
        ("compare AAPL MSFT GOOGL",       "Side-by-side comparison (color-scored)",          "--horizon 60"),
        ("valuation AAPL MSFT",           "Full value-investing template + projected return", ""),
        ("value AAPL MSFT",               "Quick P/E · P/B · P/FCF check",                   ""),
        ("owner-earnings AAPL MSFT",      "Buffett owner-earnings + multi-year trend",        ""),
        ("portfolio show",                "P&L summary + allocation chart",                   "--horizon 90  --no-chart"),
        ("portfolio add TICKER SH COST",  "Add / accumulate shares (weighted avg cost)",      "--etf"),
        ("portfolio sell TICKER SH",      "Reduce shares (cost basis unchanged)",             ""),
        ("portfolio remove TICKER",       "Remove position entirely",                         ""),
        ("portfolio target TICKER PCT",   "Set target allocation weight",                     ""),
        ("portfolio analyze",             "Run fundamental analysis on all holdings",         "--horizon 90  --scores"),
        ("portfolio rebalance",           "Show over/under-weight signals",                   ""),
        ("portfolio sma",                 "Screen holdings vs moving average",                "--days 200"),
        ("portfolio overlap",             "Direct + ETF indirect exposure overlap",           ""),
        ("portfolio migrate",             "Copy local JSON → Google Sheets",                  ""),
        ("etf compare VOO QQQM SPY",      "Side-by-side ETF overview + holdings + sectors",  ""),
        ("strategy dip",                  "VIX fear gauge + margin deployment signal",        "--sma-days 200"),
        ("strategy puts",                 "Cash-secured put screener (Buffett style)",        "--min-dte 30  --max-dte 45  --otm 5.0"),
        ("strategy margin [AMOUNT]",      "Track / update margin in use",                     "--reset"),
    ]
    for cmd, desc, flags in rows:
        cmd_table.add_row(f"stocktool {cmd}", desc, flags)
    console.print(cmd_table)

    # ── Scoring thresholds ────────────────────────────────────────────────────
    score_table = Table(title="Scoring Thresholds  (analyze / compare)", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    score_table.add_column("Metric", style="bold")
    score_table.add_column("Green (Good)", style="green")
    score_table.add_column("Yellow (Fair)", style="yellow")
    score_table.add_column("Red (Concern)", style="red")
    for row in [
        ("P/E",           "< 15",   "15–30",   "> 30 or < 0"),
        ("EPS/Rev Growth","  > 15%", "0–15%",   "< 0%"),
        ("Profit Margin", "> 20%",  "5–20%",   "< 5%"),
        ("Debt/Equity",   "< 50",   "50–150",  "> 150"),
        ("ROE",           "> 20%",  "10–20%",  "< 10%"),
        ("P/B",           "< 3×",   "3–6×",    "> 6× or < 0"),
        ("Horizon Return","> 5%",   "0–5%",    "< 0%"),
    ]:
        score_table.add_row(*row)

    # ── Value check thresholds ────────────────────────────────────────────────
    value_table = Table(title="Value Check  (value cmd)", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    value_table.add_column("Metric", style="bold")
    value_table.add_column("Green", style="green")
    value_table.add_column("Yellow", style="yellow")
    value_table.add_column("Red", style="red")
    for row in [
        ("P/E",   "< 15",  "15–25", "> 25 or neg"),
        ("P/B",   "< 1.5", "1.5–3", "> 3 or neg"),
        ("P/FCF", "< 15",  "15–25", "> 25 or neg"),
    ]:
        value_table.add_row(*row)

    console.print(Columns([score_table, value_table], equal=False, expand=False))

    # ── Owner Earnings thresholds ─────────────────────────────────────────────
    oe_table = Table(title="Owner Earnings Thresholds", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    oe_table.add_column("Metric", style="bold")
    oe_table.add_column("Green", style="green")
    oe_table.add_column("Yellow", style="yellow")
    oe_table.add_column("Red", style="red")
    for row in [
        ("OE vs Net Income",    "> +10%",  "−10% to +10%", "< −10%"),
        ("OE Yield",            ">= 8%",   "4–8%",          "< 4%"),
        ("Capital Intensity",   "< 25%",   "25–50%",        ">= 50%"),
    ]:
        oe_table.add_row(*row)
    console.print(oe_table)

    # ── VIX / Margin rules ────────────────────────────────────────────────────
    vix_table = Table(title="VIX Margin Rules  (strategy dip)", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    vix_table.add_column("VIX Level", style="bold")
    vix_table.add_column("Deploy %", justify="right")
    vix_table.add_column("Signal")
    for row in [
        ("< 28",  "0%",  "LOW FEAR — no margin deployment"),
        ("~28",  "15%", "EARLY WARNING"),
        ("~30",  "25%", "ELEVATED"),
        ("~35",  "45%", "HIGH FEAR"),
        (">= 40","65%", "EXTREME FEAR"),
    ]:
        vix_table.add_row(*row)

    # ── Rebalancing rules ─────────────────────────────────────────────────────
    reb_table = Table(title="Rebalancing Signals", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    reb_table.add_column("State", style="bold")
    reb_table.add_column("Condition")
    reb_table.add_row("[red]OVERWEIGHT[/red]",   "current > target + 2%")
    reb_table.add_row("[yellow]UNDERWEIGHT[/yellow]", "current < target − 2%")
    reb_table.add_row("[green]ON TARGET[/green]",    "within ±2%")

    console.print(Columns([vix_table, reb_table], equal=False, expand=False))

    # ── Valuation projection ──────────────────────────────────────────────────
    console.print(Panel(
        "[bold]Valuation projection formula:[/bold]\n"
        "  Projected Earnings  = Next-Year Revenue Estimate × Profit Margin\n"
        "  Future Market Cap   = Projected Earnings × 6-Month Avg P/E\n"
        "  Possible Return     = Future Market Cap / Current Market Cap − 1\n\n"
        "[bold]Possible Return verdicts:[/bold]\n"
        "  [green]>= 50%[/green]  Strong opportunity\n"
        "  [yellow]15–50%[/yellow]  Moderate upside — monitor fundamentals\n"
        "  [dim] 0–15%[/dim]  Limited upside at current price\n"
        "  [red]  < 0%[/red]  Projected downside — re-evaluate",
        title="Valuation Command",
        border_style="dim",
    ))

    console.print(
        "[dim]Run any command with [bold]--help[/bold] for full option details.  "
        "e.g. [bold]stocktool valuation --help[/bold][/dim]\n"
    )


# ---------------------------------------------------------------------------
# Entry point for `python -m stocktool.cli`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
