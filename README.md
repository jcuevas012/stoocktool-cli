# stocktool

CLI tool for mid-term stock fundamental analysis and portfolio tracking. Built for investors who want quick terminal access to valuations, rebalancing signals, SMA screens, and market dip alerts.

Uses **yfinance** (no API key required), **Typer** for CLI, and **Rich** for terminal output.

## Installation

```bash
# Clone and install
git clone git@github.com:jcuevas012/stoocktool-cli.git
cd stoocktool-cli
pip install -e .

# Or run directly without installing
python -m stocktool.cli
```

Requires Python 3.10+.

## Quick Start

```bash
# Analyze a stock
stocktool analyze AAPL MSFT --scores

# Build a portfolio
stocktool portfolio add AAPL 10 182.50
stocktool portfolio add MSFT 5 420.00
stocktool portfolio add VOO 20 450.00 --etf

# Set target allocations
stocktool portfolio target AAPL 15
stocktool portfolio target VOO 30

# View your portfolio
stocktool portfolio show
```

## Commands

### Analysis

| Command | Description |
|---------|-------------|
| `stocktool analyze AAPL MSFT [--horizon 90] [--scores]` | Fundamental analysis table with optional color-coded scores |
| `stocktool compare AAPL MSFT GOOGL [--horizon 60]` | Side-by-side comparison with scores |
| `stocktool valuation AAPL MSFT GOOGL` | Full valuation template (PE, cash/debt, revenue projections, possible return) |

### Portfolio Management

| Command | Description |
|---------|-------------|
| `stocktool portfolio show [--no-chart]` | P&L summary, allocation, sector breakdown, pie charts |
| `stocktool portfolio add TICKER SHARES COST [--etf]` | Add shares (weighted-average cost basis if ticker exists) |
| `stocktool portfolio sell TICKER SHARES` | Reduce shares from a position |
| `stocktool portfolio remove TICKER` | Remove a position entirely |
| `stocktool portfolio target TICKER WEIGHT_PCT` | Set target allocation weight (e.g. `30` for 30%) |
| `stocktool portfolio analyze [--horizon 90] [--scores]` | Run fundamental analysis on all portfolio tickers |
| `stocktool portfolio rebalance` | Show buy/sell signals based on target weights |
| `stocktool portfolio sma [--days 200]` | Screen positions against their Simple Moving Average |
| `stocktool portfolio overlap` | Show overlap between individual stocks and ETF holdings |
| `stocktool portfolio migrate` | Migrate local JSON portfolio to Google Sheets |

### ETF Tools

| Command | Description |
|---------|-------------|
| `stocktool etf compare VOO QQQM SPY` | Compare ETFs: expense ratios, performance, holdings overlap, sectors |

### Strategy

| Command | Description |
|---------|-------------|
| `stocktool strategy dip [--sma-days 200]` | Market dip alert: VIX fear gauge + margin deployment rules + SMA dip candidates |

## Features

### Valuation Template

Full value-investing analysis designed for 5+ year positions:

```
Projected Earnings = Next-Year Revenue Estimate x Profit Margin
Future Market Cap  = Projected Earnings x 6-Month Avg PE
Possible Return    = (Future Market Cap / Current Market Cap) - 1
```

Includes PE categorization, cash/debt health (with leverage ratings), analyst price targets, and a projected return verdict.

### Portfolio Tracking

- **P&L summary** with unrealized gains, cost basis, and current weights
- **Allocation tables** by ticker, sector, and type (ETF vs Stock)
- **Pie charts** rendered in terminal (bar charts) and saved as PNG (matplotlib)
- **Rebalancing signals** — OVERWEIGHT / UNDERWEIGHT / ON_TARGET with exact share counts

### SMA Screen

Screens all portfolio positions against their Simple Moving Average (default 200-day). Highlights positions trading **below** the SMA as potential buying opportunities.

### Portfolio Overlap

Identifies stocks you hold both directly and indirectly through ETFs. Calculates **effective exposure** (direct weight + indirect weight through each ETF) and shows total redundant overlap.

### ETF Support

- Mark positions as ETFs with `--etf` flag
- Type grouping in `portfolio show` (Stocks Subtotal / ETFs Subtotal)
- ETF comparison: expense ratios, AUM, performance (1M-5Y), top holdings, holdings overlap, sector breakdown

### Market Dip Alert

Combines the CBOE VIX (fear index) with SMA screening:

| VIX Level | Margin to Deploy | Signal |
|-----------|-----------------|--------|
| < 30 | 0% | LOW FEAR |
| ~30 | 25% | ELEVATED |
| ~35 | 45% | HIGH FEAR |
| >= 40 | 65% | EXTREME FEAR |

### Scoring Thresholds

Color-coded quality scores when using `--scores`:

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| P/E | < 15 | 15-30 | > 30 or < 0 |
| EPS/Rev Growth | > 15% | 0-15% | < 0 |
| Profit Margin | > 20% | 5-20% | < 5% |
| Debt/Equity | < 50 | 50-150 | > 150 |
| ROE | > 20% | 10-20% | < 10% |
| P/B | < 3x | 3-6x | > 6x or < 0 |

## Portfolio Persistence

Two backends, auto-selected:

1. **Google Sheets** (primary) — if a service account is configured
2. **Local JSON** (fallback) — `~/.config/stocktool/portfolio.json`

### Google Sheets Setup

```bash
# 1. Create a Google Cloud service account and download the JSON key
# 2. Place the key file:
cp ~/Downloads/your-key.json ~/.config/stocktool/credentials.json

# 3. Create .env in project root:
echo 'GOOGLE_SHEETS_CREDENTIALS_FILE=~/.config/stocktool/credentials.json' > .env
echo 'GOOGLE_SHEET_ID=' >> .env

# 4. First portfolio write auto-creates the sheet and saves the ID to .env
stocktool portfolio add AAPL 10 182.50

# 5. (Optional) Migrate existing JSON portfolio:
stocktool portfolio migrate
```

## Architecture

```
stocktool/
├── config.py     — Path constants, environment config, Google Sheets settings
├── data.py       — All yfinance I/O (fundamentals, prices, SMA, VIX, ETF data)
├── analysis.py   — Snapshot dataclasses, scoring, valuation logic
├── portfolio.py  — Position/Portfolio models, persistence (Sheets + JSON)
├── sheets.py     — Google Sheets CRUD operations
├── display.py    — Rich table/panel renderers (zero business logic)
└── cli.py        — Typer CLI app and subcommands
```

## License

MIT
