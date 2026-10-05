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

leaps_app = typer.Typer(help="LEAPS options tracking commands.", no_args_is_help=True)
app.add_typer(leaps_app, name="leaps")

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
        price_history = data.fetch_price_history(tickers, horizon_days=365 * 3)
        revenue_estimates = data.fetch_revenue_estimates(tickers)
        balance_sheets = data.fetch_balance_sheets(tickers)
        cashflow_basics = data.fetch_cashflow_basics(tickers)
        sma_data = data.fetch_sma_data(tickers, sma_days=200)
        earnings_history = data.fetch_earnings_history(tickers)

    snapshots = [
        analysis.build_valuation_snapshot(
            t,
            fundamentals.get(t, {}),
            price_history,
            revenue_estimates.get(t),
            balance_sheets.get(t, {}),
            cashflow_basics.get(t, {}),
            sma_data.get(t, {}).get("sma"),
            earnings_history.get(t, {}),
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
# stocktool etf valuation
# ---------------------------------------------------------------------------

@etf_app.command("valuation")
def etf_valuation(
    tickers: list[str] = typer.Argument(..., help="One or more ETF ticker symbols."),
    html: bool = typer.Option(False, "--html", is_flag=True, help="Export a self-contained HTML report to the default path."),
    html_path: Optional[str] = typer.Option(None, "--html-path", help="Custom path for the HTML report (implies --html)."),
) -> None:
    """ETF valuation: concentration, PEGY, historical valuation bands, 5Y projection, entry strategy."""
    from . import data, analysis, display, fmp

    tickers = [t.upper() for t in tickers]
    with console.status(f"Fetching ETF valuation data for {', '.join(tickers)}..."):
        etf_info = data.fetch_etf_info(tickers)
        top_holdings = data.fetch_portfolio_etf_holdings(tickers)
        all_symbols = sorted({h["symbol"] for t in tickers for h in top_holdings.get(t, [])})
        holding_fundamentals = data.fetch_holding_fundamentals(all_symbols)
        technicals = data.fetch_etf_technicals(tickers)
        hist_pe_results = {t: fmp.fetch_historical_pe(t) for t in tickers}

    snapshots = [
        analysis.build_etf_valuation_snapshot(
            t, etf_info.get(t, {}), top_holdings.get(t, []),
            holding_fundamentals, technicals.get(t, {}),
            hist_pe_results[t][0], hist_pe_results[t][1],
        )
        for t in tickers
    ]
    display.render_etf_valuation(snapshots)

    if html or html_path:
        from .html_report import generate_html_report
        out = generate_html_report(snapshots, output_path=html_path or None)
        console.print(f"[green]HTML report saved:[/green] {out}")


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
# stocktool leaps add
# ---------------------------------------------------------------------------

def _leaps_portfolio_value() -> Optional[float]:
    """Best-effort total portfolio market value, reusing the tracked portfolio."""
    from . import data
    from .portfolio import load_portfolio, build_portfolio_snapshot

    portfolio = load_portfolio()
    if not portfolio.positions:
        return None
    tickers = portfolio.tickers()
    prices = data.get_current_prices(tickers)
    sector_map = {t: None for t in tickers}
    snapshot = build_portfolio_snapshot(portfolio, prices, sector_map)
    return snapshot.total_market_value or None


def _leaps_quick_valuation(ticker: str):
    """Best-effort cross-check against the value-investing engine (`stocktool valuation`'s logic).

    Returns None on any fetch/build failure rather than raising — this is a supplementary
    check inside the LEAPS wizard, not a hard requirement to proceed.
    """
    from . import data, analysis

    try:
        fundamentals = data.fetch_fundamentals([ticker])
        history_6m = data.fetch_price_history([ticker], horizon_days=180)
        revenue_estimates = data.fetch_revenue_estimates([ticker])
        balance_sheets = data.fetch_balance_sheets([ticker])
        # cashflow_basics (D&A + CapEx) is required for the DCF step — without it,
        # build_valuation_snapshot falls back to a raw `freeCashflow` proxy that can be
        # wildly wrong (observed: AMZN -2316% "Overvalued" vs the correct +21.6% "Fair Value").
        cashflow_basics = data.fetch_cashflow_basics([ticker])
        return analysis.build_valuation_snapshot(
            ticker, fundamentals.get(ticker, {}), history_6m,
            revenue_estimates.get(ticker), balance_sheets.get(ticker, {}),
            cashflow_basics.get(ticker, {}),
        )
    except Exception:
        return None


def _render_leaps_value_check(ticker: str) -> None:
    from . import analysis

    with console.status(f"Cross-checking {ticker} against the value-investing screen..."):
        valuation = _leaps_quick_valuation(ticker)
    if valuation is None:
        console.print("[dim]Could not fetch valuation data for cross-check.[/dim]")
        return
    pr_color, pr_label = analysis.possible_return_verdict(valuation.possible_return_pct)
    pr_str = f"{valuation.possible_return_pct:+.1f}%" if valuation.possible_return_pct is not None else "N/A"
    console.print(f"[bold]Value check:[/bold] possible return [{pr_color}]{pr_str}[/{pr_color}] ({pr_label})")
    if valuation.margin_of_safety_pct is not None:
        mos_color = valuation.iv_rating_color or "dim"
        console.print(
            f"  DCF margin of safety: [{mos_color}]{valuation.margin_of_safety_pct:+.1f}%[/{mos_color}]"
            f" — {valuation.iv_rating}"
        )
    console.print(f"[dim]Full detail: stocktool valuation {ticker}[/dim]")


def _prompt_expiration() -> "date":
    from datetime import date
    from rich.prompt import Prompt

    while True:
        raw = Prompt.ask("Expiration date (YYYY-MM-DD) [dim](e.g. 2027-06-18)[/dim]")
        try:
            return date.fromisoformat(raw)
        except ValueError:
            console.print("[red]Invalid date — use YYYY-MM-DD format, e.g. 2027-06-18.[/red]")


def _ask_float(
    label: str,
    example: str,
    default: Optional[float] = None,
    optional: bool = False,
    min_value: Optional[float] = None,
) -> Optional[float]:
    """Prompt for a float with an inline example, a comma-tolerant parser, and a
    retry-on-invalid loop instead of crashing the wizard on bad input."""
    from rich.prompt import Prompt

    suffix = " (optional)" if optional else ""
    prompt_text = f"{label}{suffix} [dim](e.g. {example})[/dim]"
    while True:
        raw = Prompt.ask(prompt_text, default="" if default is None else str(default))
        if optional and not raw.strip():
            return None
        cleaned = raw.strip().replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            console.print(f"[red]Invalid number — enter digits only, e.g. {example}[/red]")
            continue
        if min_value is not None and value < min_value:
            console.print(f"[red]Value must be at least {min_value}.[/red]")
            continue
        return value


def _ask_int(
    label: str,
    example: str,
    default: Optional[int] = None,
    min_value: Optional[int] = None,
) -> int:
    """Prompt for an int with an inline example, a comma-tolerant parser, and a
    retry-on-invalid loop instead of crashing the wizard on bad input."""
    from rich.prompt import Prompt

    prompt_text = f"{label} [dim](e.g. {example})[/dim]"
    while True:
        raw = Prompt.ask(prompt_text, default=None if default is None else str(default))
        cleaned = raw.strip().replace(",", "")
        try:
            value = int(cleaned)
        except ValueError:
            console.print(f"[red]Invalid whole number — enter digits only, e.g. {example}[/red]")
            continue
        if min_value is not None and value < min_value:
            console.print(f"[red]Value must be at least {min_value}.[/red]")
            continue
        return value


def _resolve_leaps_position(book, identifier: str):
    """Resolve a user-supplied `leaps show`/`leaps remove` argument to a position.

    Tries an exact position-id match first (backward compatible with existing ids),
    then falls back to a case-insensitive ticker match. Prompts for a choice when a
    ticker matches more than one position, since ids are hard to remember/type.
    """
    from . import display

    position = book.find(identifier)
    if position is not None:
        return position

    matches = [p for p in book.positions if p.ticker.upper() == identifier.upper()]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    display.render_leaps_candidates(matches)
    choice = _ask_int(f"Which {identifier.upper()} position", "1", default=1, min_value=1)
    while choice > len(matches):
        console.print(f"[red]Enter a number between 1 and {len(matches)}.[/red]")
        choice = _ask_int(f"Which {identifier.upper()} position", "1", default=1, min_value=1)
    return matches[choice - 1]


@leaps_app.command("add")
def leaps_add() -> None:
    """Interactive wizard to add a new LEAPS position, enforcing position-discipline rules."""
    from datetime import date
    from rich.prompt import Prompt, Confirm

    from . import data, analysis, display
    from .config import (
        LEAPS_APPROVED_TICKERS, LEAPS_MIN_DAYS_TO_EXPIRY, LEAPS_LONG_EXPIRY_WARN_DAYS,
        LEAPS_DELTA_WARN_LOW, LEAPS_DELTA_WARN_HIGH, LEAPS_MAX_POSITION_PCT,
        LEAPS_WARN_POSITION_PCT, LEAPS_DEFAULT_PROFIT_TARGET, LEAPS_DEFAULT_TIME_STOP_DAYS,
        LEAPS_EARNINGS_WARN_DAYS,
    )
    from .leaps import LeapsPosition, IvReading, load_leaps, save_leaps, new_position_id

    console.print("\n[bold]LEAPS Wizard — Add New Position[/bold]")
    console.print("=" * 32)

    # Step 1: ticker
    ticker = Prompt.ask(f"Ticker symbol ({', '.join(LEAPS_APPROVED_TICKERS)} only — high conviction)").strip().upper()
    if ticker not in LEAPS_APPROVED_TICKERS:
        console.print(f"[red]❌ {ticker} is not in the approved LEAPS ticker list ({', '.join(LEAPS_APPROVED_TICKERS)}).[/red]")
        raise typer.Exit(1)

    with console.status(f"Fetching current price for {ticker}..."):
        current_price = data.get_current_prices([ticker]).get(ticker)
    if not current_price:
        console.print(f"[red]Could not fetch a current price for {ticker}.[/red]")
        raise typer.Exit(1)
    console.print(f"✓ Current price: [bold]${current_price:.2f}[/bold]")
    _render_leaps_value_check(ticker)

    # Step 2: option type
    option_type = Prompt.ask("CALL or PUT?", choices=["CALL", "PUT"], default="CALL")
    if option_type == "CALL":
        console.print("[dim]LEAPS are typically CALLS for bullish positions.[/dim]")

    # Step 3: strike price
    strike = _ask_float("Strike price ($)", example="450.00", min_value=0.01)
    itm_pct = (
        (current_price - strike) / current_price * 100
        if option_type == "CALL"
        else (strike - current_price) / current_price * 100
    )
    if itm_pct < 10:
        console.print(f"[yellow]⚠️ Strike is {itm_pct:.1f}% in-the-money — not deep ITM. LEAPS rules suggest 15%+ ITM.[/yellow]")
    else:
        console.print(f"✓ Strike is {itm_pct:.1f}% in-the-money")

    # Step 4: expiration date
    expiration = _prompt_expiration()
    days_to_expiry = (expiration - date.today()).days
    if days_to_expiry < LEAPS_MIN_DAYS_TO_EXPIRY:
        console.print(f"[red]❌ LEAPS rule: minimum {LEAPS_MIN_DAYS_TO_EXPIRY} days to expiry (got {days_to_expiry}).[/red]")
        raise typer.Exit(1)
    if days_to_expiry > LEAPS_LONG_EXPIRY_WARN_DAYS:
        console.print(f"[yellow]⚠️ Very long expiry ({days_to_expiry} days) increases vega risk.[/yellow]")
    console.print(f"✓ {days_to_expiry} days to expiration (passes {LEAPS_MIN_DAYS_TO_EXPIRY}-day minimum)")

    # Step 4b: market context — next earnings date, bid/ask, IV vs 1Y realized volatility.
    # Best-effort only: this wizard is meant to be run right before you submit the real
    # order, so these are advisory checks, not blockers.
    with console.status(f"Fetching option market context for {ticker}..."):
        option_context = data.fetch_leaps_option_context(
            ticker, option_type, strike, expiration.isoformat()
        )

    days_to_earnings = option_context.get("days_to_earnings")
    if days_to_earnings is not None:
        earnings_str = f"{option_context['earnings_date']} ({days_to_earnings} days away)"
        if 0 <= days_to_earnings <= LEAPS_EARNINGS_WARN_DAYS:
            console.print(
                f"[yellow]⚠️ Next earnings: {earnings_str} — within the {LEAPS_EARNINGS_WARN_DAYS}-day "
                f"warn window. Expect an IV crush and a possible gap move right after you enter.[/yellow]"
            )
        else:
            console.print(f"[green]✓ Next earnings: {earnings_str}[/green]")
    else:
        console.print("[dim]Next earnings date not available.[/dim]")

    suggested_premium = option_context.get("mid")
    bid, ask = option_context.get("bid"), option_context.get("ask")
    if bid is not None and ask is not None:
        if suggested_premium is not None:
            console.print(
                f"Market bid/ask: ${bid:.2f} / ${ask:.2f} → suggested limit (mid): ${suggested_premium:.2f}"
            )
        else:
            console.print(f"Market bid/ask: ${bid:.2f} / ${ask:.2f}")
    else:
        console.print("[dim]No matching contract found for this strike/expiration — enter premium manually.[/dim]")

    market_iv = option_context.get("implied_volatility")
    realized_vol = option_context.get("realized_volatility")
    if market_iv is not None and realized_vol:
        iv_ratio = market_iv / realized_vol
        if iv_ratio > 1.3:
            iv_color, iv_note = "red", "running rich vs. realized vol — options are relatively expensive right now"
        elif iv_ratio < 0.9:
            iv_color, iv_note = "green", "near or below realized vol — reasonably priced"
        else:
            iv_color, iv_note = "yellow", "modestly elevated vs. realized vol — typical for LEAPS"
        console.print(
            f"[{iv_color}]Market IV: {market_iv:.1f}% vs 1Y realized volatility {realized_vol:.1f}% "
            f"({iv_ratio - 1:+.0%}) — {iv_note}[/{iv_color}]"
        )
    elif market_iv is not None:
        console.print(f"Market IV: {market_iv:.1f}% [dim](realized volatility unavailable for comparison)[/dim]")

    # Step 5: premium + contracts
    premium_example = f"{suggested_premium:.2f}" if suggested_premium is not None else "12.70"
    premium = _ask_float(
        "Premium paid per share ($)", example=premium_example, default=suggested_premium, min_value=0.01
    )
    contracts = _ask_int("Contracts", example="2", default=1, min_value=1)
    total_cost = premium * 100 * contracts
    breakeven = strike + premium if option_type == "CALL" else strike - premium
    console.print(f"Total cost: ${total_cost:,.2f}")
    console.print(f"Breakeven: ${breakeven:.2f}")

    # Step 6: delta at purchase (optional) — read off your broker's chain, not computed here
    entry_delta = _ask_float(
        "Delta at purchase (0.00-1.00, read from your broker's option chain)",
        example="0.80", optional=True,
    )
    if entry_delta is not None:
        color = analysis.leaps_delta_color(entry_delta)
        if entry_delta < LEAPS_DELTA_WARN_LOW:
            console.print(f"[yellow]⚠️ Below {LEAPS_DELTA_WARN_LOW} delta is not deep ITM — higher risk.[/yellow]")
        elif entry_delta > LEAPS_DELTA_WARN_HIGH:
            console.print(f"[yellow]⚠️ Above {LEAPS_DELTA_WARN_HIGH} delta is very deep ITM — expensive, lower leverage.[/yellow]")
        elif color == "green":
            console.print(f"[green]✓ Delta {entry_delta:.2f} — Jorge's Rule sweet spot (0.75-0.85): balanced leverage for value investors.[/green]")
        else:
            console.print(f"[yellow]Delta {entry_delta:.2f} is deep ITM but outside the 0.75-0.85 sweet spot.[/yellow]")

    # Step 7: theta at purchase (optional)
    theta_magnitude = _ask_float("Theta per day (magnitude $)", example="0.03", optional=True)
    entry_theta: Optional[float] = -abs(theta_magnitude) if theta_magnitude is not None else None
    if entry_theta is not None:
        console.print(f"Monthly theta cost: ${abs(entry_theta) * 30:,.2f}")

    # Step 8: IV at purchase (optional) — market IV fetched in Step 4b is shown again here
    # as a reference so you're not typing against nothing.
    if market_iv is not None:
        console.print(f"[dim]Market IV for this contract: {market_iv:.1f}% — enter that, or your own reading.[/dim]")
    entry_iv = _ask_float("Implied Volatility at purchase (%)", example="35.0", optional=True)

    # Step 9: portfolio percentage check
    portfolio_value = _leaps_portfolio_value()
    if portfolio_value is None:
        console.print("[dim]No tracked portfolio found — enter your total portfolio value manually.[/dim]")
        portfolio_value = _ask_float("Current total portfolio value ($)", example="250000", min_value=0.01)
    position_pct = total_cost / portfolio_value * 100 if portfolio_value else 0.0
    console.print(f"Position size: {position_pct:.2f}% of portfolio")
    if position_pct > LEAPS_MAX_POSITION_PCT:
        console.print(f"[red]🚨 EXCEEDS {LEAPS_MAX_POSITION_PCT:.0f}% LEAPS RULE — Position too large.[/red]")
        if not Confirm.ask("Override?", default=False):
            console.print("[yellow]Operation cancelled. Position size too large.[/yellow]")
            raise typer.Exit()
    elif position_pct > LEAPS_WARN_POSITION_PCT:
        console.print(f"[yellow]⚠️ Approaching max LEAPS allocation ({LEAPS_WARN_POSITION_PCT:.0f}%).[/yellow]")

    # Step 10: exit rules
    profit_target_multiplier = _ask_float(
        "Profit target multiplier", example="1.5", default=LEAPS_DEFAULT_PROFIT_TARGET, min_value=0.01
    )
    days_before_expiry_exit = _ask_int(
        "Days before expiry to force exit", example="90", default=LEAPS_DEFAULT_TIME_STOP_DAYS, min_value=0
    )

    # Step 11/12: scenario analysis, confirmation + save
    position = LeapsPosition(
        id=new_position_id(),
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiration=expiration.isoformat(),
        premium=premium,
        contracts=contracts,
        entry_date=date.today().isoformat(),
        entry_stock_price=current_price,
        entry_delta=entry_delta,
        entry_theta=entry_theta,
        entry_iv=entry_iv,
        profit_target_multiplier=profit_target_multiplier,
        days_before_expiry_exit=days_before_expiry_exit,
    )

    # Seed IV history going forward from today — yfinance has no historical-IV endpoint, so
    # this can't backfill the past, only start accumulating real readings from here on.
    # Prefer the Yahoo-quoted market IV for this exact contract (Step 4b) over the manually
    # typed entry IV, since it's an actual market reading rather than a hand-entered one.
    if market_iv is not None:
        position.iv_history.append(IvReading(date=position.entry_date, iv=round(market_iv, 2), source="yahoo"))
    elif entry_iv is not None:
        position.iv_history.append(IvReading(date=position.entry_date, iv=entry_iv, source="manual"))

    console.print("\n[bold cyan]Summary[/bold cyan]")
    console.print(f"  {ticker} {option_type} ${strike:.2f} exp {expiration.isoformat()}")
    console.print(f"  Premium ${premium:.2f} x {contracts} contract(s) = ${total_cost:,.2f}")
    console.print(f"  Breakeven: ${breakeven:.2f}  ·  Position size: {position_pct:.2f}%")
    console.print(f"  Exit: {profit_target_multiplier}x profit target, {days_before_expiry_exit}-day time stop")
    decay_date, decay_days = analysis.compute_leaps_decay_date(position.entry_date, position.expiration)
    if decay_date is not None:
        decay_desc = (
            f"{decay_days} days of slow decay before theta accelerates"
            if decay_days is not None and decay_days > 0
            else "already past the 1/3-life mark — decay is accelerating now"
        )
        console.print(f"  Decay acceleration date: {decay_date} ({decay_desc})")
    console.print()

    scenario = analysis.build_leaps_scenario(position, current_price)
    display.render_leaps_scenario(scenario)

    if not Confirm.ask("Save this LEAPS position?", default=True):
        console.print("[yellow]Operation cancelled.[/yellow]")
        raise typer.Exit()

    book = load_leaps()
    book.add_position(position)
    save_leaps(book)
    console.print(f"[green]Saved LEAPS position {ticker} (id={position.id}).[/green]")


# ---------------------------------------------------------------------------
# stocktool leaps list
# ---------------------------------------------------------------------------

@leaps_app.command("list")
def leaps_list(
    all_: bool = typer.Option(False, "--all", help="Show both active and closed positions."),
    closed: bool = typer.Option(False, "--closed", help="Show only closed positions."),
) -> None:
    """List tracked LEAPS positions (active by default)."""
    from . import data, analysis, display
    from .leaps import load_leaps

    book = load_leaps()
    if all_:
        positions = book.positions
    elif closed:
        positions = book.closed_positions()
    else:
        positions = book.active_positions()

    if not positions:
        display.render_leaps_list([])
        return

    tickers = sorted({p.ticker for p in positions})
    prices = data.get_current_prices(tickers)
    portfolio_value = _leaps_portfolio_value()

    snapshots = [
        analysis.build_leaps_snapshot(p, prices.get(p.ticker), portfolio_value)
        for p in positions
    ]
    display.render_leaps_list(snapshots)


# ---------------------------------------------------------------------------
# stocktool leaps show
# ---------------------------------------------------------------------------

@leaps_app.command("show")
def leaps_show(
    identifier: str = typer.Argument(..., help="LEAPS position id or ticker symbol."),
) -> None:
    """Detail view for a single LEAPS position."""
    from . import data, analysis, display
    from .leaps import load_leaps

    book = load_leaps()
    position = _resolve_leaps_position(book, identifier)
    if position is None:
        console.print(f"[red]No LEAPS position found for id or ticker '{identifier}'.[/red]")
        raise typer.Exit(1)

    current_price = data.get_current_prices([position.ticker]).get(position.ticker)
    portfolio_value = _leaps_portfolio_value()
    snapshot = analysis.build_leaps_snapshot(position, current_price, portfolio_value)
    display.render_leaps_detail(position, snapshot)

    console.print()
    _render_leaps_value_check(position.ticker)
    console.print()
    scenario = analysis.build_leaps_scenario(position, current_price)
    display.render_leaps_scenario(scenario)


# ---------------------------------------------------------------------------
# stocktool leaps update
# ---------------------------------------------------------------------------

@leaps_app.command("update")
def leaps_update(
    identifier: str = typer.Argument(..., help="LEAPS position id or ticker symbol to refresh."),
) -> None:
    """Refresh current delta/theta/IV during monitoring — read fresh values off your broker's
    option chain. Entry values are left untouched (the P&L estimate stays anchored to entry);
    this only updates the 'as of today' snapshot used for exit-strategy and exposure tracking."""
    from datetime import date

    from . import data, analysis, display
    from .leaps import load_leaps, save_leaps, IvReading

    book = load_leaps()
    position = _resolve_leaps_position(book, identifier)
    if position is None:
        console.print(f"[red]No LEAPS position found for id or ticker '{identifier}'.[/red]")
        raise typer.Exit(1)
    if position.status == "CLOSED":
        console.print(f"[yellow]Position {position.id} is closed — nothing to monitor.[/yellow]")
        return

    console.print(f"\n[bold]Updating {position.ticker} {position.option_type} ${position.strike:.2f} exp {position.expiration}[/bold]")
    if position.last_updated:
        console.print(f"[dim]Last updated: {position.last_updated}[/dim]")

    current_delta = _ask_float(
        "Current delta (0.00-1.00, from your broker's option chain)",
        example="0.78",
        default=position.current_delta if position.current_delta is not None else position.entry_delta,
        optional=True,
    )
    if current_delta is not None:
        color = analysis.leaps_delta_color(current_delta)
        if color == "green":
            console.print(f"[green]✓ Delta {current_delta:.2f} — still in the 0.75-0.85 sweet spot.[/green]")
        elif color == "yellow":
            console.print(f"[yellow]Delta {current_delta:.2f} is deep ITM but outside the 0.75-0.85 sweet spot.[/yellow]")
        else:
            console.print(f"[red]⚠️ Delta {current_delta:.2f} has drifted out of LEAPS range — this position is behaving less like stock. Review your exit plan.[/red]")

    theta_magnitude = _ask_float(
        "Current theta per day (magnitude $)",
        example="0.04",
        default=abs(position.current_theta) if position.current_theta is not None else (abs(position.entry_theta) if position.entry_theta is not None else None),
        optional=True,
    )
    current_theta = -abs(theta_magnitude) if theta_magnitude is not None else None

    with console.status(f"Fetching current market IV for {position.ticker} from Yahoo..."):
        market_iv = data.fetch_current_iv(position.ticker, position.option_type, position.strike, position.expiration)
    if market_iv is not None:
        console.print(f"[dim]Market IV for this contract (from Yahoo): {market_iv:.1f}%[/dim]")
    else:
        console.print("[dim]No matching contract found on Yahoo for this strike/expiration — enter IV manually.[/dim]")

    current_iv = _ask_float(
        "Current Implied Volatility (%)",
        example="32.0",
        default=market_iv if market_iv is not None else (
            position.current_iv if position.current_iv is not None else position.entry_iv
        ),
        optional=True,
    )

    position.current_delta = current_delta
    position.current_theta = current_theta
    position.current_iv = current_iv
    position.last_updated = date.today().isoformat()
    if current_iv is not None:
        source = "yahoo" if market_iv is not None and abs(current_iv - market_iv) < 0.05 else "manual"
        position.iv_history.append(IvReading(date=position.last_updated, iv=current_iv, source=source))
    save_leaps(book)
    console.print(f"[green]Updated {position.ticker} (id={position.id}) as of {position.last_updated}.[/green]\n")

    current_price = data.get_current_prices([position.ticker]).get(position.ticker)
    portfolio_value = _leaps_portfolio_value()
    snapshot = analysis.build_leaps_snapshot(position, current_price, portfolio_value)
    display.render_leaps_detail(position, snapshot)


# ---------------------------------------------------------------------------
# stocktool leaps remove
# ---------------------------------------------------------------------------

@leaps_app.command("remove")
def leaps_remove(
    identifier: str = typer.Argument(..., help="LEAPS position id or ticker symbol to close."),
) -> None:
    """Close a LEAPS position (kept for history, not deleted)."""
    from rich.prompt import Confirm, FloatPrompt

    from .leaps import load_leaps, save_leaps

    book = load_leaps()
    position = _resolve_leaps_position(book, identifier)
    if position is None:
        console.print(f"[red]No LEAPS position found for id or ticker '{identifier}'.[/red]")
        raise typer.Exit(1)
    if position.status == "CLOSED":
        console.print(f"[yellow]Position {position.id} is already closed (closed_at={position.closed_at}).[/yellow]")
        return

    close_price = None
    if Confirm.ask("Record a close price for this position?", default=True):
        close_price = FloatPrompt.ask("Close price per share ($)")

    ok, msg = book.close_position(position.id, close_price)
    if ok:
        save_leaps(book)
        console.print(f"[green]{msg}[/green]")
    else:
        console.print(f"[yellow]{msg}[/yellow]")


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
        ("etf valuation VOO QQQM",        "PEGY, valuation bands, 5Y projection, entry tiers", "--html"),
        ("strategy dip",                  "VIX fear gauge + margin deployment signal",        "--sma-days 200"),
        ("strategy puts",                 "Cash-secured put screener (Buffett style)",        "--min-dte 30  --max-dte 45  --otm 5.0"),
        ("strategy margin [AMOUNT]",      "Track / update margin in use",                     "--reset"),
        ("leaps add",                     "Interactive LEAPS wizard (sizing/expiry/delta checks)", ""),
        ("leaps list",                    "Table of tracked LEAPS positions",                 "--all  --closed"),
        ("leaps show ID|TICKER",          "Detail panel for one LEAPS position",              ""),
        ("leaps remove ID|TICKER",        "Close (not delete) a LEAPS position",              ""),
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

    # ── LEAPS rules ───────────────────────────────────────────────────────────
    from .config import (
        LEAPS_APPROVED_TICKERS, LEAPS_MIN_DAYS_TO_EXPIRY, LEAPS_DELTA_WARN_LOW,
        LEAPS_DELTA_WARN_HIGH, LEAPS_WARN_POSITION_PCT, LEAPS_MAX_POSITION_PCT,
    )
    leaps_table = Table(title="LEAPS Rules  (leaps add)", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    leaps_table.add_column("Rule", style="bold")
    leaps_table.add_column("Threshold")
    leaps_table.add_column("Enforcement")
    for row in [
        ("Approved tickers",    ", ".join(LEAPS_APPROVED_TICKERS), "Hard block"),
        ("Min days to expiry",  str(LEAPS_MIN_DAYS_TO_EXPIRY), "Hard block"),
        ("Delta warn band",     f"{LEAPS_DELTA_WARN_LOW:.2f} – {LEAPS_DELTA_WARN_HIGH:.2f}", "Warn only"),
        ("Delta sweet spot",    "0.75 – 0.85 (Jorge's Rule)", "Highlighted green"),
        ("Position size warn",  f"> {LEAPS_WARN_POSITION_PCT:.0f}% of portfolio", "Warn only"),
        ("Position size max",   f"> {LEAPS_MAX_POSITION_PCT:.0f}% of portfolio", "Warn + y/N override"),
    ]:
        leaps_table.add_row(*row)
    console.print(leaps_table)

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
