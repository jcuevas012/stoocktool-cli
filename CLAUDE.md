# stocktool — Claude Code Guide

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
├── config.py     — Path constants, DEFAULT_HORIZON_DAYS=90, ensure_config_dir()
├── data.py       — All yfinance I/O: fetch_fundamentals, fetch_price_history,
│                   get_current_prices, fetch_revenue_estimates, fetch_balance_sheets
├── analysis.py   — FundamentalSnapshot + ValuationSnapshot dataclasses,
│                   build_snapshot(), build_valuation_snapshot(), score_ticker()
├── portfolio.py  — Position/Portfolio/PortfolioSnapshot dataclasses, load/save JSON
├── display.py    — Rich table/panel renderers (zero business logic)
└── cli.py        — Typer app + subcommands; calls data → analysis/portfolio → display
```

**Dependency direction**: `config → data/analysis/portfolio → cli`; `display` only imported by `cli`.

## Portfolio Persistence
Stored at `~/.config/stocktool/portfolio.json`.
Never store computed/live data — only: ticker, shares, cost_basis, target_weight.

## Key yfinance Notes
- Always use `group_by="ticker"` with `yf.download()` to ensure consistent MultiIndex
- Single-ticker downloads are normalized to MultiIndex manually in `data.py`
- `.info` keys are unreliable — always use `.get()` with `Optional[float]` fields
- Max 5 `ThreadPoolExecutor` workers for parallel fetches
- `dividendYield` from `.info` is returned as a decimal percentage (e.g. 0.39 = 0.39%) — display with `:.2f}%` not `:.2%`
- `recommendationKey` uses underscores: `"strong_buy"`, `"buy"`, `"hold"`, `"sell"`, `"strong_sell"`
- `ticker.revenue_estimate` returns a DataFrame indexed by period (`'0q'`, `'+1q'`, `'0y'`, `'+1y'`)
- `ticker.balance_sheet` index key for total assets: try `"Total Assets"` then `"TotalAssets"`

## Commands
```bash
stocktool analyze AAPL MSFT [--horizon 90] [--scores]
stocktool compare AAPL MSFT GOOGL [--horizon 60]
stocktool valuation AAPL MSFT GOOGL
stocktool portfolio show [--horizon 90]
stocktool portfolio add TICKER SHARES COST_PER_SHARE
stocktool portfolio remove TICKER
stocktool portfolio target TICKER WEIGHT_PCT
stocktool portfolio analyze [--horizon 90] [--scores]
stocktool portfolio rebalance
```

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
