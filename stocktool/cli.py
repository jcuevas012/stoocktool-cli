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


# ---------------------------------------------------------------------------
# stocktool valuation
# ---------------------------------------------------------------------------

@app.command()
def valuation(
    tickers: list[str] = typer.Argument(..., help="One or more ticker symbols."),
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
    from .config import MARGIN_RULES
    from .portfolio import load_portfolio

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

    display.render_dip_alert(vix_data, margin_rule, sma_data, sma_days)


# ---------------------------------------------------------------------------
# Entry point for `python -m stocktool.cli`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
