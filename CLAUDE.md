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
│                   compute_holdings_overlap, fetch_portfolio_etf_holdings,
│                   fetch_owner_earnings, fetch_put_candidates
├── html_report.py — Self-contained HTML report generator: generate_html_report(snapshots, output_path)
│                   No external deps (stdlib only + existing packages). Inline CSS dark theme,
│                   card grid layout, color-coded badges, SVG bar charts, tab-based multi-ticker nav.
├── analysis.py   — FundamentalSnapshot + ValuationSnapshot + ValueCheckSnapshot +
│                   CashSecuredPutSnapshot + OwnerEarningsSnapshot dataclasses,
│                   build_snapshot(), build_valuation_snapshot(), build_value_check_snapshot(),
│                   build_owner_earnings_snapshot(), build_csp_snapshot(), score_ticker()
├── portfolio.py  — Position/Portfolio/PortfolioSnapshot dataclasses,
│                   load/save with auto-routing (Google Sheets → JSON fallback)
├── sheets.py     — Google Sheets CRUD: load_portfolio_from_sheet,
│                   save_portfolio_to_sheet, sync_position, remove_position_from_sheet
├── display.py    — Rich table/panel renderers + render_pie_chart() +
│                   render_etf_compare() + render_dip_alert() +
│                   render_portfolio_overlap() + render_value_check() +
│                   render_cash_secured_puts() + render_owner_earnings() (zero business logic)
└── cli.py        — Typer app + subcommands; calls data → analysis/portfolio → display
```

**Dependency direction**: `config → data/analysis/portfolio/sheets → cli`; `display` only imported by `cli`; `html_report` only imported by `cli` (lazy, on --html flag).

## HTML Report Export (`--html`)

Commands `analyze`, `valuation`, and `owner-earnings` accept an optional `--html [PATH]` flag.

```bash
stocktool analyze AAPL MSFT --html
stocktool valuation AAPL MSFT GOOGL --html
stocktool owner-earnings AAPL MSFT --html
stocktool analyze AAPL --html /path/to/report.html  # custom path
```

**Behavior:**
- When `--html` is provided without a path, the report is saved to `~/.config/stocktool/report_<TICKERS>_<DATE>.html`
- The file is opened automatically in the default browser after generation
- Terminal Rich output is still rendered normally alongside the HTML export

**html_report.py design principles:**
- No new Python dependencies — only stdlib (`html`, `pathlib`, `datetime`, `webbrowser`) plus packages already installed
- Self-contained HTML: all CSS inline in a `<style>` block, no external fonts/CDN/scripts
- Dark theme, card-based grid layout, responsive at 1280px
- Color-coded badges use the same thresholds as `analysis.py` (green/yellow/red scale functions imported directly — never duplicated)
- Multi-ticker reports include tab pills (JS only for tab switching) + a side-by-side comparison table
- Owner Earnings section includes a pure SVG horizontal bar chart for the multi-year trend
- `generate_html_report(snapshots, output_path=None, open_browser=True) -> str` is the single public function

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

### FMP Setup (optional)

Only needed for `stocktool etf valuation`'s true 5-year historical average P/E — the command works fully without it.

```bash
# 1. Get a free key at financialmodelingprep.com (250 requests/day free tier)
# 2. Add it to .env:
echo 'FMP_API_KEY=' >> .env
# 3. Omit entirely to use the yfinance-only proxy instead — no setup required.
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
- `funds_data.top_holdings`'s `"Holding Percent"` column is a true fraction (0.08 = 8%), not a decimal-percentage — unlike `dividendYield` above.
- `annualReportExpenseRatio` and `trailingAnnualDividendYield` are no longer populated for most ETFs. Use `netExpenseRatio` and `dividendYield` instead — both are "decimal percentage" fields (0.03 = 0.03%, 1.07 = 1.07%) like `dividendYield` above, so divide by 100 to store as a true fraction if that's your field's convention.
- ETFs often lack `currentPrice` in `.info` (populated as `regularMarketPrice`/`previousClose` instead, or not at all). `stocktool etf valuation` sidesteps this by sourcing current price from price-history close throughout, rather than from `.info`.
- Per-stock `earningsGrowth` is a noisy trailing YoY figure that can spike to 1000%+ off a near-zero prior-year base (e.g. a cyclical semiconductor coming out of a down year) — clip/cap it before using in any weighted or aggregate calculation.

## Commands

```bash
stocktool analyze AAPL MSFT [--horizon 90] [--scores]
stocktool compare AAPL MSFT GOOGL [--horizon 60]
stocktool valuation AAPL MSFT GOOGL
stocktool value AAPL MSFT GOOGL
stocktool owner-earnings AAPL MSFT GOOGL
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
stocktool etf valuation VOO QQQM [--html]
stocktool strategy dip [--sma-days 200]
stocktool strategy puts [--min-dte 30] [--max-dte 45] [--otm 5.0]
stocktool strategy margin [AMOUNT] [--reset]
stocktool docs
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

## ETF Valuation (`stocktool etf valuation`)

Value-investing template for ETFs: PEGY ratio, P/E-reversion fair value, margin of safety, a 5-year growth projection, and two disciplined entry price tiers. Mirrors the visual style of `stocktool valuation` (same Rich Panel conventions, same `Valuación de Activos: {TICKER}` title).

**Data fetched:** ETF `.info` (via `fetch_etf_info`, extended with `trailing_pe`/`forward_pe`/`category`) + top-10 holdings via `funds_data.top_holdings` (`fetch_portfolio_etf_holdings`) + per-holding `.info` for PE/growth (`fetch_holding_fundamentals`) + 5-year price history for EMA-50/SMA-200/52w-hi-lo/proxy average price (`fetch_etf_technicals`) + optional Financial Modeling Prep call for true 5-year average P/E (`fmp.fetch_historical_pe`).

**Sections rendered (one panel per ticker):**

| # | Section | Key Metric | Source |
|---|---------|------------|--------|
| 1 | Basket Concentration & Top Holdings | Top-10 weight sum, holdings table | `funds_data.top_holdings` |
| 2 | Valuation Multiples & PEGY | Trailing P/E, forward EPS growth, distribution yield, PEGY | ETF `.info` or weighted top-10 holdings |
| 3 | Historical Valuation Bands & NAV | 5Y avg P/E, fair value, entry zone | FMP or yfinance price-proxy |
| 4 | Valuation Projection (5-Year Growth View) | Projected price, total return, CAGR | computed |
| 5 | Entry Strategy & Margin of Safety | Margin of safety, Tier 1/Tier 2 entries, rating | computed |

**Formulas (`analysis.py`):**

```
Concentration       = sum(top-10 holding weights)
PEGY                = Trailing P/E / (Forward EPS Growth % + Distribution Yield %)   [None if growth <= 0]
Fair Value          = Current Price × (5Y Avg P/E / Trailing P/E)
Margin of Safety    = (Fair Value − Current Price) / Current Price × 100
Projected EPS (5Y)  = Current EPS-equivalent × (1 + growth_rate)^5      [EPS-equivalent = Price / Trailing P/E]
Projected Price (5Y)= Projected EPS × Terminal P/E (= 5Y Avg P/E)
Tier 1 (DCA Pullback)        = min(50-day EMA, Current Price × 0.95)
Tier 2 (Valuation Reversion) = min(Fair Value, 200-day SMA)
```

**Basket-level trailing P/E and forward growth:** the ETF's own `.info["trailingPE"]` is used if populated; otherwise a weighted **harmonic** mean of the top-10 holdings' trailing P/E (`sum(weights) / sum(weight/pe)`), covering only holdings with a valid positive P/E — the coverage (e.g. "8/10 holdings, 71% of top-10 weight") is shown alongside. Forward EPS growth is a weighted arithmetic mean of the top-10 holdings' `earningsGrowth`, each **clipped to [-30%, +50%]** before weighting (see the yfinance note above on noisy per-stock growth figures) — this is intentionally tighter than a literal "no clipping" reading of the SRS, mirroring how `_select_dcf_growth_rate` already caps even high-ROIC stock-level growth at 15%.

**Growth rate used for the 5-year projection:** `min(forward_eps_growth / 100, 0.15)` if positive, else a `0.06` default — capped to prevent a single outlier holding from compounding into an unrealistic 5-year figure, floored higher than the stock-side DCF's 4% default since a diversified basket of large caps rarely has zero growth.

**Rating ladder (`determine_etf_rating`):**

| Condition | Rating |
|-----------|--------|
| PEGY < 1.5 and MoS > 10% | ★★★★★ Strong Buy (green) |
| PEGY < 2.0 and MoS > 0% | ★★★★☆ Buy/Accumulate (green) |
| 2.0 ≤ PEGY ≤ 2.8 | ★★★☆☆ Hold/DCA on Pullbacks (yellow) |
| PEGY > 2.8 or MoS < -20% | ★★☆☆☆ Overvalued/Trim (red) |
| PEGY and MoS both present, none of the above | ★★☆☆☆ Hold/Neutral (yellow) |
| PEGY or MoS missing | ☆☆☆☆☆ Insufficient Data (dim) |

The "Hold/Neutral" rule isn't in the original spec — it fills a real gap in the literal ladder (e.g. PEGY=1.7, MoS=-5% matches none of the first four rules) so only genuinely missing data falls into "Insufficient Data".

**Concentration thresholds:** green < 40% (diversified), yellow 40–60% (moderate), red > 60% (concentrated) — mirrors the existing `debt_to_assets_pct` 40/65 split style.

### Financial Modeling Prep (FMP) integration — optional

yfinance has no field for a true multi-year historical average P/E, which the Fair Value / Margin of Safety / 5-Year Projection formulas above all depend on. `stocktool etf valuation` optionally calls **Financial Modeling Prep** for this one field:

- Set `FMP_API_KEY=...` in `.env` (get a free key at financialmodelingprep.com) to enable it. Omit it entirely — the command works fully without it.
- Endpoint: `GET https://financialmodelingprep.com/stable/ratios?symbol={TICKER}&period=annual&limit=5&apikey={KEY}`, called **at most once per ETF ticker** (not per holding), to stay well within the free tier's 250 requests/day.
- The exact P/E field name in FMP's response could not be verified against live documentation (the docs site blocks automated fetching) — `fmp.py` tries several candidate field names defensively (`priceToEarningsRatio`, `peRatio`, `priceEarningsRatio`) and falls back to the proxy below if none resolve. Re-verify with a real API key if FMP changes its schema.
- **Fallback proxy** (used automatically with no key, on any API failure, or on a rate limit): `5Y Avg P/E ≈ mean(5-year price) × (current Trailing P/E / current Price)` — assumes the basket's aggregate earnings are roughly stable over the window. The `hist_pe_note` field on `ETFValuationSnapshot` always states which source was used.

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

## DCF Intrinsic Value (Section 7 of `stocktool valuation`)

Appended automatically to every `valuation` panel. Implements a 10-step Buffett Owner Earnings DCF.

**Additional data fetched:** `fetch_cashflow_basics()` in `data.py` pulls depreciation + capex from the annual cashflow statement (same session as the other valuation fetches).

**10-step methodology:**

| Step | Description |
|------|-------------|
| 1 | Normalized Net Income = Revenue Est. × Profit Margin (fallback: FCF) |
| 2 | Owner Earnings = NI + Depreciation + CapEx (yfinance capex is negative) |
| 3 | Growth Rate — conservative: avg(revenue_growth, eps_growth) capped by ROE tier |
| 4 | Discount Rate = 10% |
| 5 | Terminal Growth = 2.5% |
| 6 | Enterprise Value = PV(10yr OE) + PV(Terminal Value) |
| 7 | Equity Value = EV + Cash − Debt |
| 8 | Intrinsic Value Per Share = Equity Value / Shares Outstanding |
| 9 | Margin of Safety = (IV − Price) / IV × 100 |
| 10 | Rating based on margin of safety |

**Growth rate selection (in `analysis._select_dcf_growth_rate`):**
- High-ROIC (ROE > 25%) + avg growth ≥ 10% → cap at 15%
- Solid allocator (ROE > 15% or avg growth ≥ 8%) → cap at 12%
- Mature/average → cap at 8%
- No positive growth signals → default 4%

**Rating thresholds:**

| Margin of Safety | Rating |
|-----------------|--------|
| > 40% | ★★★★★ Strong Buy |
| 25–40% | ★★★★ Buy |
| 15–25% | ★★★ Fair Value |
| 5–15% | ★★ Hold |
| < 5% | ★ Overvalued |

**Fallback logic for Owner Earnings:**
1. If D&A + CapEx from cashflow available → full formula
2. Else if FCF > 0 → FCF used as proxy
3. Else if NI > 0 → NI used as fallback
4. If none positive → DCF section shows "insufficient data"

**New fields on `ValuationSnapshot`:** `shares_outstanding`, `revenue_growth`, `eps_growth`, `roe`, `roa`, `free_cashflow`, `depreciation`, `capex_cf`, `dcf_net_income`, `dcf_owner_earnings`, `dcf_owner_earnings_note`, `dcf_growth_rate`, `dcf_growth_note`, `dcf_discount_rate`, `dcf_terminal_growth`, `dcf_enterprise_value`, `dcf_equity_value`, `intrinsic_value_per_share`, `margin_of_safety_pct`, `iv_rating`, `iv_rating_color`.

## Quick Value Check (`stocktool value`)

Quick-reference command for value investors. Shows P/E, P/B, and P/FCF ratios with color-coded thresholds and hint text.

**Thresholds:**

| Metric | Green (Good) | Yellow (Fair) | Red (Expensive) |
|--------|-------------|---------------|-----------------|
| P/E | < 15 | 15–25 | > 25 or negative |
| P/B | < 1.5 | 1.5–3 | > 3 or negative |
| P/FCF | < 15 | 15–25 | > 25 or negative |

P/FCF is computed as `marketCap / freeCashflow` from `.info` fields.

## Owner Earnings (`stocktool owner-earnings`)

Buffett's preferred measure of true profitability. Unlike reported net income, Owner Earnings
shows the actual cash a business generates for its owners after maintaining operations.

**Formula:** `Net Income + Depreciation - Capital Spending - Working Capital Changes`

**Data source:** `ticker.cashflow` DataFrame. Index keys:
- `Net Income From Continuing Operations` (fallback: `Net Income`)
- `Depreciation Amortization Depletion` (fallback: `Depreciation And Amortization`)
- `Capital Expenditure` (already negative in yfinance — add directly)
- `Change In Working Capital` (negative = cash consumed)

**Sections rendered (one panel per ticker):**

| # | Section | What it answers |
|---|---------|-----------------|
| 1 | Formula Breakdown | What does this business really earn in cash? |
| 2 | Reality Check | Are the reported profits real? (OE vs Net Income) |
| 3 | Owner Earnings Yield | What return are you getting for your money? |
| 4 | Capital Intensity | How much does it cost to keep this business running? |
| 5 | Multi-Year Trend | Is the cash machine getting stronger or weaker? |
| - | Bottom Line | Combined verdict bullets |

**Key metrics and thresholds:**

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| OE vs Net Income | > +10% (earns more than reports) | -10% to +10% (matches) | < -10% (overstated) |
| Owner Earnings Yield | >= 8% (excellent value) | 4-8% (decent) | < 4% (paying premium) |
| Capital Intensity | < 25% (cash cow) | 25-50% (moderate) | >= 50% (heavy spender) |
| Trend | GROWING | STABLE | DECLINING |

**Multi-ticker comparison:** When 2+ tickers are provided, a side-by-side summary table
is rendered after the individual panels with a "What it means" column in plain English.

**Plain English design:** Every metric includes a verdict in simple language (e.g., "Like a toll
bridge — once built, the cash just flows in" for low capital intensity). No financial jargon
without an explanation.

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
| < 28      | 0%              | LOW FEAR — no margin deployment |
| ~28       | 15%             | EARLY WARNING — deploy 15% margin |
| ~30       | 25%             | ELEVATED — deploy 25% margin |
| ~35       | 45%             | HIGH FEAR — deploy 45% margin |
| ≥ 40      | 65%             | EXTREME FEAR — deploy 65% margin |

**Output panels:**

1. **VIX Fear Gauge** — Current VIX value, color-coded, 1-day change
2. **Margin Deployment Signal** — Which rule triggered, margin % to deploy
3. **Dip Candidates** — Portfolio positions trading below SMA
4. **Strategy Summary** — Combined signal in one line

## Cash-Secured Put Screener (`stocktool strategy puts`)

Buffett-style put-selling screener for portfolio stocks. Sells puts on stocks you'd happily own for 5-10 years. If assigned, you buy a great company at a discount while collecting premium.

- Only screens individual stocks (not ETFs) from the portfolio
- Finds put options expiring in 30-45 DTE (configurable via `--min-dte` / `--max-dte`)
- Selects strikes ~5% below current price (configurable via `--otm`)
- Ranks stocks by valuation attractiveness (using the valuation engine's projected return)
- Uses bid price as premium (what you'd actually receive)

**Data fetched per ticker:**

- Options chain (puts) via `ticker.option_chain(date)` for nearest 30-45 DTE expiration
- Beta from `.info` (volatility measure)
- Full valuation data (fundamentals, 6-month history, revenue estimates, balance sheet) for ranking

**Columns displayed:**

| Column | Description |
|--------|-------------|
| Beta | Stock volatility vs market (< 1 = less volatile) |
| Price | Current stock price |
| Strike | Selected put strike (~5% OTM) |
| Exp (DTE) | Expiration date and days to expiration |
| Premium | Bid price per share (what you collect) |
| Cash Req | Cash needed to secure the put (strike x 100) |
| Return | Premium / strike as percentage |
| Annual. | Return annualized to 365 days |
| Eff. Buy | Effective purchase price if assigned (strike - premium) |
| Discount | Discount from current price to effective buy price |
| OI | Open interest (liquidity indicator) |
| Valuation | Verdict from valuation engine (STRONG BUY / GOOD VALUE / FAIR / OVERVALUED) |

**Valuation verdict thresholds (from projected return):**
>
- >= 50% projected return → STRONG BUY
- 15-50% → GOOD VALUE
- 0-15% → FAIR
- < 0% → OVERVALUED

**Color coding:**

- Beta: green < 1, yellow 1-1.5, red > 1.5
- Return: green >= 2%, yellow 1-2%, dim < 1%
- Annualized: green >= 12%, yellow 6-12%, dim < 6%

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

***Consideration***
When new feature is added please update the CLAUDE.md documentation with the principles to consider as help for future feature
