# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
CLI tool for mid-term stock fundamental analysis and portfolio tracking.
Uses **yfinance** (no API key required), **typer** for CLI, and **rich** for terminal output.

## Installation
```bash
pip install -e .          # installs `stocktool` entry point
# OR
python -m stocktool.cli   # run directly without installing
```

## Architecture
```
stocktool/
├── config.py     — Path constants, DEFAULT_HORIZON_DAYS=90, VIX_TICKER, MARGIN_RULES,
│                   ensure_config_dir(), dotenv loading, Google Sheets constants, sheets_configured()
├── data.py       — All yfinance I/O: fetch_fundamentals, fetch_price_history,
│                   get_current_prices, fetch_revenue_estimates, fetch_balance_sheets,
│                   fetch_sma_data, fetch_vix, fetch_etf_info, fetch_etf_performance,
│                   compute_holdings_overlap, fetch_portfolio_etf_holdings
├── analysis.py   — FundamentalSnapshot + ValuationSnapshot + ValueCheckSnapshot dataclasses,
│                   build_snapshot(), build_valuation_snapshot(), build_value_check_snapshot(), score_ticker()
├── portfolio.py  — Position/Portfolio/PortfolioSnapshot dataclasses,
│                   load/save with auto-routing (Google Sheets → JSON fallback)
├── sheets.py     — Google Sheets CRUD: load_portfolio_from_sheet,
│                   save_portfolio_to_sheet, sync_position, remove_position_from_sheet
├── display.py    — Rich table/panel renderers + render_pie_chart() +
│                   render_etf_compare() + render_dip_alert() +
│                   render_portfolio_overlap() + render_value_check() (zero business logic)
└── cli.py        — Typer app + subcommands; calls data → analysis/portfolio → display
```

**Dependency direction**: `config → data/analysis/portfolio/sheets → cli`; `display` only imported by `cli`.

## Portfolio Persistence
Two backends, auto-selected:

1. **Google Sheets** (primary, if configured) — positions stored in a shared spreadsheet.
   - Requires a Google Cloud service account JSON at `~/.config/stocktool/credentials.json`
   - Sheet ID stored in `.env` at project root (`GOOGLE_SHEET_ID`)
   - On first write, a new spreadsheet is created and the ID is saved to `.env`
   - Sheet layout: `ticker | shares | cost_basis | target_weight | is_etf` (header row 1, data from row 2)
   - Use `stocktool portfolio migrate` to copy local JSON → Google Sheets

2. **Local JSON** (fallback) — `~/.config/stocktool/portfolio.json`
   - Used automatically if credentials file doesn't exist

Never store computed/live data — only: ticker, shares, cost_basis, target_weight, is_etf.

### Google Sheets Setup
```bash
# 1. Create a Google Cloud service account and download the JSON key
# 2. Place the key file:
cp ~/Downloads/your-key.json ~/.config/stocktool/credentials.json
# 3. Create .env in project root (or use the template):
echo 'GOOGLE_SHEETS_CREDENTIALS_FILE=~/.config/stocktool/credentials.json' > .env
echo 'GOOGLE_SHEET_ID=' >> .env
# 4. First portfolio write auto-creates the sheet and saves the ID to .env
stocktool portfolio add AAPL 10 182.50
# 5. (Optional) Migrate existing JSON portfolio:
stocktool portfolio migrate
```

## Key yfinance Notes
- Always use `group_by="ticker"` with `yf.download()` to ensure consistent MultiIndex
- Single-ticker downloads are normalized to MultiIndex manually in `data.py`
- `.info` keys are unreliable — always use `.get()` with `Optional[float]` fields
- Max 5 `ThreadPoolExecutor` workers for parallel fetches
- `dividendYield` from `.info` is returned as a decimal percentage (e.g. 0.39 = 0.39%) — display with `:.2f}%` not `:.2%`
- `recommendationKey` uses underscores: `"strong_buy"`, `"buy"`, `"hold"`, `"sell"`, `"strong_sell"`
- `ticker.revenue_estimate` returns a DataFrame indexed by period (`'0q'`, `'+1q'`, `'0y'`, `'+1y'`)
- `ticker.balance_sheet` index key for total assets: try `"Total Assets"` then `"TotalAssets"`
- ETF top holdings: use `ticker.funds_data.top_holdings` (returns DataFrame with Symbol index, `"Name"` and `"Holding Percent"` columns). The `.info["holdings"]` key is no longer populated by yfinance.

## Commands
```bash
stocktool analyze AAPL MSFT [--horizon 90] [--scores]
stocktool compare AAPL MSFT GOOGL [--horizon 60]
stocktool valuation AAPL MSFT GOOGL
stocktool value AAPL MSFT GOOGL
stocktool portfolio show [--horizon 90] [--no-chart]
stocktool portfolio add TICKER SHARES COST_PER_SHARE [--etf]
stocktool portfolio sell TICKER SHARES
stocktool portfolio remove TICKER
stocktool portfolio target TICKER WEIGHT_PCT
stocktool portfolio analyze [--horizon 90] [--scores]
stocktool portfolio rebalance
stocktool portfolio sma [--days 200]
stocktool portfolio overlap
stocktool portfolio migrate
stocktool etf compare VOO QQQM SPY
stocktool strategy dip [--sma-days 200]
```

## ETF Support

### `--etf` flag
Use `stocktool portfolio add TICKER SHARES COST --etf` to mark a position as an ETF.
The `is_etf` flag is stored in the Google Sheet and local JSON.

### Type grouping in `portfolio show`
When the portfolio has both ETFs and individual stocks:
- **Portfolio Summary** groups positions by type with sub-total rows (Stocks Subtotal, ETFs Subtotal)
- **Allocation** table includes a Type column
- **Type Breakdown** table shows ETF vs Stock total weights
- **Pie chart** includes a third chart: ETF vs Stock split

### `stocktool etf compare` command
Compares 2+ ETFs side-by-side:
- **Overview:** Name, expense ratio, AUM, dividend yield, fund family
- **Performance:** Price returns over 1M, 3M, 6M, 1Y, 3Y, 5Y
- **Top Holdings:** Top 10 holdings per ETF (when available from yfinance)
- **Holdings Overlap:** Stocks appearing in 2+ ETFs with overlap percentage
- **Sector Breakdown:** Sector weights per ETF side-by-side

**Note:** yfinance ETF data varies — expense ratio, holdings, and sector weights may show N/A for some ETFs. Holdings overlap is based on top reported holdings only (not full fund composition).

## Pie Chart (`stocktool portfolio show`)
`portfolio show` now renders allocation charts after the summary tables:
- **Terminal:** Horizontal bar charts (ticker allocation + sector allocation) using rich
- **PNG:** Matplotlib pie charts saved to `~/.config/stocktool/portfolio_allocation.png`
- Use `--no-chart` to skip chart rendering

## Valuation Command (`stocktool valuation`)
Full value-investing analysis template. Designed for 5+ year positions.
Fetches: `.info` fundamentals + 6-month price history + analyst revenue estimates + balance sheet.

**Sections rendered (one panel per ticker):**

| # | Section | Key Metric | Source |
|---|---------|------------|--------|
| 1 | PE Ratio | Trailing PE + 6-month avg PE + investor profile | `trailingPE`, price history |
| 2 | Cash & Debt Health | Cash, debt, net cash, debt/assets %, current ratio, quick ratio | `totalCash`, `totalDebt`, balance sheet, `currentRatio`, `quickRatio` |
| 3 | Revenue Estimate | Next-year analyst avg revenue | `ticker.revenue_estimate['+1y']` |
| 4 | Profit Margin | Trailing profit margin | `profitMargins` |
| 5 | Avg PE (6m) | Mean(close prices) / trailing EPS over 6 months | price history + `trailingEps` |
| 6 | Analyst Price Targets | Low / Mean / High price targets, upside %, analyst count, consensus | `targetLowPrice`, `targetMeanPrice`, `targetHighPrice`, `recommendationKey` |
| — | Valuation Projection | Revenue × margin = earnings; earnings × avg PE = future market cap → possible return | computed |

**Projection formula:**
```
Projected Earnings = Next-Year Revenue Estimate × Profit Margin
Future Market Cap  = Projected Earnings × 6-Month Avg PE
Possible Return    = (Future Market Cap / Current Market Cap) - 1
```

**Debt/Assets thresholds:**
- < 40% → LOW LEVERAGE (green)
- 40–65% → MODERATE (yellow)
- > 65% → HIGH LEVERAGE (red)

**Possible Return verdict:**
- ≥ 50% → Strong opportunity for long-term investor
- 15–50% → Moderate upside — monitor fundamentals
- 0–15% → Limited upside at current price
- < 0% → Projected downside — re-evaluate

## Quick Value Check (`stocktool value`)
Quick-reference command for value investors. Shows P/E, P/B, and P/FCF ratios with color-coded thresholds and hint text.

**Thresholds:**

| Metric | Green (Good) | Yellow (Fair) | Red (Expensive) |
|--------|-------------|---------------|-----------------|
| P/E | < 15 | 15–25 | > 25 or negative |
| P/B | < 1.5 | 1.5–3 | > 3 or negative |
| P/FCF | < 15 | 15–25 | > 25 or negative |

P/FCF is computed as `marketCap / freeCashflow` from `.info` fields.

## SMA Screen (`stocktool portfolio sma`)
Screens all portfolio positions against their Simple Moving Average (default 200-day).
Highlights positions trading **below** the SMA — potential buying opportunities for value investors.

- Fetches 1 year of price history via `yf.download()`, computes rolling mean
- Sorts results: BELOW SMA first (opportunities), then ABOVE SMA
- `--days` flag overrides the SMA window (e.g. `--days 50` for 50-day SMA)
- Summary panel lists flagged tickers and suggests `stocktool valuation` for deeper analysis

## Portfolio Overlap (`stocktool portfolio overlap`)
Shows overlap between individual stocks and ETF holdings in the portfolio.
Identifies stocks held both directly and indirectly through ETFs.

- Fetches ETF top holdings via `ticker.funds_data.top_holdings` (DataFrame with Symbol index)
- Calculates **effective exposure** per stock: direct weight + sum(ETF portfolio weight × stock's weight in that ETF)
- Summary panel shows total direct vs effective exposure and redundant overlap percentage

**Output:**
- **Overlap Table** — Each overlapping stock with direct weight, weight in each ETF, and effective exposure
- **Overlap Summary** — Count of overlapping stocks, direct vs effective totals, redundant overlap %

**Note:** Based on top holdings reported by yfinance (not full fund composition). ETFs without holdings data are listed separately.

## Market Dip Alert (`stocktool strategy dip`)
Combines the CBOE VIX (fear index) with SMA screening to help decide when and how much margin to deploy during market dips.

- Fetches `^VIX` via `yf.download()` for current fear level and 1-day change
- Screens all portfolio positions against their SMA (default 200-day)
- `--sma-days` flag overrides the SMA window (e.g. `--sma-days 50`)

**VIX color thresholds:** green < 20, yellow 20–30, red > 30

**Margin deployment rules:**

| VIX Level | Margin to Deploy | Label |
|-----------|-----------------|-------|
| < 30      | 0%              | LOW FEAR — no margin deployment |
| ~30       | 25%             | ELEVATED — deploy 25% margin |
| ~35       | 45%             | HIGH FEAR — deploy 45% margin |
| ≥ 40      | 65%             | EXTREME FEAR — deploy 65% margin |

**Output panels:**
1. **VIX Fear Gauge** — Current VIX value, color-coded, 1-day change
2. **Margin Deployment Signal** — Which rule triggered, margin % to deploy
3. **Dip Candidates** — Portfolio positions trading below SMA
4. **Strategy Summary** — Combined signal in one line

## Rebalancing Logic
- OVERWEIGHT: current_weight > target_weight + 2%  → red
- UNDERWEIGHT: current_weight < target_weight - 2%  → yellow
- ON_TARGET: within ±2%                             → green

## Scoring Thresholds (analysis.py)
| Metric        | Green         | Yellow       | Red           |
|---------------|---------------|--------------|---------------|
| P/E           | < 15          | 15–30        | > 30 or < 0   |
| EPS/Rev Growth| > 15%         | 0–15%        | < 0           |
| Profit Margin | > 20%         | 5–20%        | < 5%          |
| Debt/Equity   | < 50          | 50–150       | > 150         |
| ROE           | > 20%         | 10–20%       | < 10%         |
| P/B           | < 3x          | 3–6x         | > 6x or < 0   |
| Horizon Return| > 5%          | 0–5%         | < 0           |
