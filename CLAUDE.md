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
│                   CashSecuredPutSnapshot + OwnerEarningsSnapshot + LeapsSnapshot dataclasses,
│                   build_snapshot(), build_valuation_snapshot(), build_value_check_snapshot(),
│                   build_owner_earnings_snapshot(), build_csp_snapshot(), build_leaps_snapshot(), score_ticker()
├── portfolio.py  — Position/Portfolio/PortfolioSnapshot dataclasses,
│                   load/save with auto-routing (Google Sheets → JSON fallback)
├── leaps.py      — LeapsPosition/LeapsBook dataclasses, load_leaps()/save_leaps()
│                   (local JSON only — no Sheets routing, unlike portfolio.py)
├── sheets.py     — Google Sheets CRUD: load_portfolio_from_sheet,
│                   save_portfolio_to_sheet, sync_position, remove_position_from_sheet
├── display.py    — Rich table/panel renderers + render_pie_chart() +
│                   render_etf_compare() + render_dip_alert() +
│                   render_portfolio_overlap() + render_value_check() +
│                   render_cash_secured_puts() + render_owner_earnings() +
│                   render_leaps_list() + render_leaps_detail() (zero business logic)
└── cli.py        — Typer app + subcommands; calls data → analysis/portfolio/leaps → display
```

**Dependency direction**: `config → data/analysis/portfolio/leaps/sheets → cli`; `display` only imported by `cli`; `html_report` only imported by `cli` (lazy, on --html flag).

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
- `ticker.quarterly_earnings` is deprecated and returns `None` in current yfinance — use `ticker.quarterly_income_stmt` / `ticker.income_stmt` (`"Total Revenue"`, `"Net Income"` rows) instead. `quarterly_income_stmt` only returns the trailing ~5 quarters (not a full 8-quarter YoY-by-quarter window).

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
stocktool leaps add
stocktool leaps list [--all] [--closed]
stocktool leaps show ID|TICKER
stocktool leaps update ID|TICKER
stocktool leaps remove ID|TICKER
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
Fetches: `.info` fundamentals + 3-year price history (also sliced for the 6-month avg PE) + analyst revenue estimates + balance sheet + 1-year price history for the 200-day SMA.

**Sections rendered (one panel per ticker):**

| # | Section | Key Metric | Source |
|---|---------|------------|--------|
| 1 | PE Ratio & Price Context | Trailing PE + 6-month and 3-year price/EPS proxies + price vs. 3-year mean + investor profile | `trailingPE`, price history |
| 2 | Cash & Debt Health | Cash, debt, net cash, debt/assets %, current ratio, quick ratio | `totalCash`, `totalDebt`, balance sheet, `currentRatio`, `quickRatio` |
| 3 | Revenue Estimate | Next-year analyst avg revenue | `ticker.revenue_estimate['+1y']` |
| 4 | Profit Margin | Trailing profit margin | `profitMargins` |
| 5 | Avg PE (6m) | Mean(close prices) / trailing EPS over 6 months | price history + `trailingEps` |
| 6 | Analyst Price Targets | Low / Mean / High price targets, upside %, analyst count, consensus, 200-day SMA & % vs price | `targetLowPrice`, `targetMeanPrice`, `targetHighPrice`, `recommendationKey`, `data.fetch_sma_data()` |
| — | Valuation Projection | Revenue × margin = earnings; earnings × avg PE = future market cap → possible return | computed |
| 8 | Earnings Growth Trend | Quarterly & annual Revenue/Net Income, net margin, QoQ/YoY growth, margin trend | `data.fetch_earnings_history()` — see dedicated section below |

**Three-Year Price Context:** `cli.py`'s `valuation` command fetches 3 years of price history in one call; the 6-month price/EPS proxy is sliced from that data. Both proxies divide mean prices by current trailing EPS, so neither represents historical P/E. The comparison of current P/E with the 3-year proxy reduces algebraically to current price versus the 3-year mean price; it is price context, not a cheap/expensive verdict. The report displays the last price-history date and identifies this limitation in terminal and HTML output.

**200-Day SMA in Analyst Price Targets:** reuses `data.fetch_sma_data(tickers, sma_days=200)` (same helper as `portfolio sma` / `strategy dip`) — one extra `yf.download(period="1y")` call per `valuation` invocation. Stored on `ValuationSnapshot` as `sma_200` (price) and `pct_from_sma_200` (`(current_price / sma_200 - 1) * 100`). Green when price ≥ SMA (long-term uptrend), red when below (potential value entry, same convention as `portfolio sma`'s BELOW SMA flag). Rendered in both the Rich panel (`display.py`) and the HTML report's Analyst Price Targets card (`html_report.py`); omitted entirely when yfinance doesn't return enough history (< 200 daily bars).

**Company Overview (Sector / Industry / Business Segments):** shown in the panel header, right below Price/Market Cap/Sector. Yahoo Finance's "Investment Themes" widget (per-theme 1-year performance, e.g. Google's "Publicidad +9.67%") was evaluated and rejected as a data source — it isn't exposed by yfinance's `.info`, any other `Ticker` method, or the underlying `quoteSummary` modules (`sectorTrend`/`industryTrend` return empty), and doesn't appear in Yahoo Finance's page HTML either, indicating it's a Yahoo Finance Plus (paid) feature with no free API path. Instead: `industry` comes straight from `info.get("industryDisp") or info.get("industry")`; `business_segments` is a **best-effort regex extraction** from `longBusinessSummary` (`analysis._extract_business_segments`) matching yfinance's two consistent vendor-text templates — `"operates through/in [N] segments: A, B, and C."` (MSFT, JNJ, JPM style) and `"operates through A, B, and C segments."` (GOOG, XOM style). Returns `[]` for single-segment/non-diversified companies (e.g. AAPL, V, KO) whose summary doesn't use either template — callers fall back to sector/industry alone in that case. Capped at 8 segments / 60 chars each as a guard against mis-captures. Rendered as a comma list in the Rich panel and as badge chips under the ticker name in the HTML hero card.

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

**CapEx as % of Revenue / Net Income:** two extra ratios shown alongside the Owner Earnings breakdown (Step 2), answering "how much of the top line / bottom line gets reinvested?" — a different denominator than `capex_intensity_pct` (Owner Earnings command), which divides by `NI + D&A` instead.

```
CapEx % of Revenue     = abs(capex_cf) / total_revenue_ttm × 100
CapEx % of Net Income  = abs(capex_cf) / net_income_ttm × 100     [None if net_income_ttm <= 0]
```

`total_revenue_ttm` and `net_income_ttm` come straight from `.info["totalRevenue"]` / `.info["netIncomeToCommon"]` (fallback: `total_revenue_ttm × profit_margin` if `netIncomeToCommon` is missing) — no new yfinance call, reusing the same `info` dict already fetched for the rest of `valuation`. Both are TTM actuals, same period convention as `capex_cf` (latest fiscal year from the cashflow statement).

Thresholds reuse the existing Capital Intensity bands via the shared `analysis.capex_intensity_color()` helper: green < 25%, yellow 25–50%, red ≥ 50% — same convention as `capex_intensity_pct`, not a new scale.

**New fields on `ValuationSnapshot`:** `shares_outstanding`, `revenue_growth`, `eps_growth`, `roe`, `roa`, `free_cashflow`, `depreciation`, `capex_cf`, `capex_pct_revenue`, `capex_pct_net_income`, `dcf_net_income`, `dcf_owner_earnings`, `dcf_owner_earnings_note`, `dcf_growth_rate`, `dcf_growth_note`, `dcf_discount_rate`, `dcf_terminal_growth`, `dcf_enterprise_value`, `dcf_equity_value`, `intrinsic_value_per_share`, `margin_of_safety_pct`, `iv_rating`, `iv_rating_color`.

## Earnings Growth Trend (Section 8 of `stocktool valuation`)

Appended automatically to every `valuation` panel, right after the DCF section. Answers a simple question in plain numbers: how much of each quarter's/year's revenue actually becomes profit, and is that improving?

**Data fetched:** `data.fetch_earnings_history()` pulls `Total Revenue` and `Net Income` from `ticker.quarterly_income_stmt` (last ~5 quarters) and `ticker.income_stmt` (last ~4-5 fiscal years, one call per ticker, parallelized like the other `data.py` fetchers). Periods missing either revenue or net income (e.g. yfinance's stale oldest annual column) are dropped rather than shown as N/A. `ticker.quarterly_earnings` is deprecated/empty in current yfinance and is not used.

**Computed in `analysis._build_earnings_periods` / `build_valuation_snapshot`:**

```
Margin (per period)  = Net Income / Revenue × 100
Growth (per period)  = (Revenue / Prior-Period Revenue - 1) × 100   [QoQ for quarters, YoY for years]
```

Growth is `None` for the oldest period in each list (no prior period available in the fetched window).

**Simple-English note** (`earnings_simple_note`): built from the latest fiscal year (falls back to the latest quarter if no annual data resolved), e.g. *"For every $10 in revenue, AAPL keeps $2.69 in profit — a 26.9% margin."* — directly answers the "if revenue is 10 and net income is 2" framing.

**Margin trend** (`earnings_margin_trend`, via `analysis._earnings_margin_trend`): direction of net margin across fiscal years, newest-first — mirrors the Owner Earnings trend heuristic (`build_owner_earnings_snapshot`):
- 3+ years → counts up/down moves between consecutive years; more ups → EXPANDING, more downs → COMPRESSING, tie → STABLE
- Exactly 2 years → ±2 percentage-point threshold on the single YoY margin delta
- < 2 years → `None` (not shown)

**Thresholds (reused from existing conventions, not new ones):**

- Margin color: green > 20%, yellow 5–20%, red < 5% — same bands as Section 4's Profit Margin
- Growth color: green > 15%, yellow 0–15%, red < 0% — same bands as `analysis._score_growth`

**New fields on `ValuationSnapshot`:** `earnings_quarters` / `earnings_years` (`list[EarningsPeriod]`, newest-first; `EarningsPeriod` = `period, revenue, net_income, margin_pct, growth_pct`), `earnings_margin_trend`, `earnings_simple_note`. Rendered as two tables (Quarterly QoQ, Annual YoY) in both the Rich panel (`display._render_one_valuation`) and the HTML report (`html_report._render_earnings_trend_card`).

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

## LEAPS Tracking (`stocktool leaps`)

Discipline-enforcing tracker for LEAPS (Long-term Equity AnticiPation Securities) positions — long-dated, deep-ITM options held as a stock substitute. `leaps add` is an interactive wizard that is a checklist, not just data entry: it blocks or warns on the same rules a disciplined LEAPS trader would self-impose before committing capital to a position that can go to zero.

**Scope of this implementation (MVP):** `add` (wizard), `list`, `show <id|ticker>`, `update <id|ticker>` (monitoring refresh), `remove <id|ticker>`. Core calculations include breakeven, days-to-expiry, position sizing, market-mark P&L when a valid Yahoo bid/ask midpoint is available (otherwise an explicitly labeled entry-delta estimate), signed delta-adjusted stock-equivalent exposure, an at-expiration scenario ladder, and a cross-check against the existing valuation engine. `add`, `show`, and `update` also display a Black–Scholes delta/gamma what-if curve; broker-entered delta remains the exposure input. **Deferred to future phases:** broker Greeks integration, true historical-IV rank/percentile (would need a historical-implied-volatility data source yfinance doesn't provide — see the CHEAP/FAIR/EXPENSIVE realized-vol proxy and the self-tracked IV Rank below for what's implemented instead), historical IV-crush statistics around earnings (same data-availability limitation), `leaps check` / `leaps alerts` / `leaps analyze`, email/SMTP notifications, and a Google Sheets backend for LEAPS.

**Data model (`leaps.py`):** `LeapsPosition` — `id` (8-char uuid), `ticker`, `option_type` (CALL/PUT), `strike`, `expiration`, `premium`, `contracts`, entry snapshot (`entry_date`, `entry_stock_price`, `entry_delta`/`entry_theta`/`entry_iv` — all optional), exit rules (`profit_target_multiplier`, `days_before_expiry_exit`), and close tracking (`status`, `closed_at`, `close_price`, `realized_pnl`). Dates are stored as ISO strings, not `date` objects, so the dataclass serializes with plain `dataclasses.asdict()` + `json.dump()` — no custom encoder needed.

**Persistence:** local JSON only at `~/.config/stocktool/leaps.json` (`load_leaps()`/`save_leaps()`). Unlike `portfolio.py`, there is **no Google Sheets routing** for LEAPS — a deliberate simplification for this MVP, not an oversight.

**`leaps remove` closes, it doesn't delete** — status flips to CLOSED (optionally recording a close price and realized P&L) so closed positions remain visible via `leaps list --closed` / `--all`. This preserves a track record of past LEAPS trades. Closing an already-closed position is a no-op, not an error.

**`leaps show` / `leaps remove` accept a ticker, not just the 8-char position id** (`cli._resolve_leaps_position()`): the raw argument is tried as an exact id first (backward compatible with ids already written to scripts/history), then as a case-insensitive ticker match against both active and closed positions. A single ticker match resolves silently; 2+ matches (e.g. two LEAPS tranches on the same name) render a numbered picker table (`display.render_leaps_candidates()`) and prompt for a choice via `_ask_int` — avoiding the need to copy/paste an opaque uuid for the common case of one position per ticker.

**Wizard rules (`leaps add`):**

| Rule | Threshold | Enforcement |
|------|-----------|-------------|
| Approved tickers | `LEAPS_APPROVED_TICKERS` config (default: GOOGL, AMZN, MSFT; override via `LEAPS_APPROVED_TICKERS` env, comma-separated) | Hard block, no override |
| Minimum days to expiry | 365 | Hard block, no override |
| Long expiry | > 730 days | Warn only |
| Moneyness | Strike at least 15% ITM | Warn only |
| Delta band | magnitude 0.70 – 0.90 | Warn only (manually entered — no Greeks engine yet; CALL positive, PUT negative) |
| Delta sweet spot | 0.75 – 0.85 ("Jorge's Rule") | Highlighted green — balanced leverage, the value-investor target band |
| Position size | > 3% of portfolio | Warn only |
| Position size | > 5% of portfolio | Warn + explicit y/N override |
| Earnings proximity | Next earnings within `LEAPS_EARNINGS_WARN_DAYS` (default 21) days | Warn only |

**Market context step (Step 4b, right after strike + expiration are entered):** `data.fetch_leaps_option_context(ticker, option_type, strike, expiration)` makes a best-effort, never-raising fetch of three pieces of market data for the exact contract the user is about to enter, since the wizard is meant to be run immediately before the real broker order is submitted:

- **Next earnings date** — from `ticker.calendar["Earnings Date"]`, falling back to `ticker.get_earnings_dates(limit=4)` filtered to future dates. Warned if within `LEAPS_EARNINGS_WARN_DAYS` (default 21) because earnings can bring a gap and volatility changes; this is a risk reminder, not a prediction of an IV crush.
- **Bid/ask → suggested limit price** — the exact contract's `bid`/`ask` from `ticker.option_chain(expiration)` (`.calls`/`.puts` filtered by `strike`); a valid two-sided midpoint, rounded to cents, becomes the suggested order limit. It is indicative and is not a guaranteed execution price. The quote retrieval time and spread are shown when available. A last trade is context only, never a substitute for a current mark.
- **IV vs. 1-year realized volatility → CHEAP/FAIR/EXPENSIVE verdict** — `analysis.leaps_iv_value_verdict(market_iv, realized_vol)` classifies the ratio `market_iv / realized_vol` against `config.LEAPS_IV_CHEAP_RATIO` (0.90) and `LEAPS_IV_EXPENSIVE_RATIO` (1.15): ≤0.90 → CHEAP (green), ≥1.15 → EXPENSIVE (red), otherwise FAIR (yellow); either input missing → no label (dim). This is a free-data proxy for IV rank, not a true historical-IV percentile — yfinance has no historical-implied-volatility series, so trailing realized (actual) price movement stands in for "average IV". Always printed with a one-line caveat saying so. Deliberately a plain colored word, not just a ratio — this tool is aimed at beginners who need a legible reminder/signal before committing capital, not a number they have to interpret themselves.

  Surfaced everywhere IV is shown, computed fresh each time (never cached): `leaps add` Step 4b (reusing `fetch_leaps_option_context`'s already-fetched realized vol), and `leaps show` / `leaps update` (which call the new standalone `data.fetch_realized_volatility(ticker)` — extracted from `fetch_leaps_option_context` so both paths share one implementation). `LeapsSnapshot` carries `realized_volatility`, `iv_value_ratio`, `iv_value_label`, `iv_value_color`, computed in `build_leaps_snapshot()` from `current_iv` (falling back to `entry_iv` if the position has never been through `leaps update`) — `None`/`"dim"` when not `ACTIVE`.

  In the IV History block (`display._leaps_iv_history_lines`), only the **latest** reading gets a label, and it is computed from that reading's own stored IV value (not from `LeapsSnapshot.iv_value_label`, which reflects `current_iv`/`entry_iv` and can briefly disagree with the latest history entry right after `leaps add`, when Yahoo's seeded market IV differs from a manually-typed entry IV) — so the label always matches the number it sits next to. Older readings stay untagged: recomputing realized volatility as of a past date isn't attempted, so tagging them would look like a backtest it isn't.

**Input validation (`cli._ask_float` / `cli._ask_int`):** every numeric wizard prompt (strike, premium, contracts, delta, theta, IV, portfolio value, profit target multiplier, time-stop days) goes through one of these two helpers instead of bare `FloatPrompt`/`IntPrompt`/manual `float()`. Each shows an inline example value (`[dim](e.g. 450.00)[/dim]`), strips thousands-separator commas before parsing, and on a malformed or out-of-range entry prints a red error message and **re-prompts** rather than raising an exception or calling `typer.Exit()` — a typo no longer aborts the whole wizard after several minutes of answered questions.

**Position sizing auto-sourced from the tracked portfolio:** the wizard reuses `portfolio.load_portfolio()` + `portfolio.build_portfolio_snapshot()`'s `total_market_value`. If any tracked holding lacks a current price, the total is treated as unavailable rather than using a partial sum; the interactive wizard asks for a manual total. `leaps list`/`leaps show` never prompt and show sizing as N/A if the total is unavailable. The denominator is tracked stock/ETF market value, not untracked cash or other assets.

**Formulas (`analysis.py`'s `build_leaps_snapshot()`):**

```
Breakeven              = strike + premium                         (CALL)
                        = strike - premium                         (PUT)
Days to Expiry          = expiration - today
Position %              = (contracts × premium × 100) / portfolio_value × 100
Intrinsic Value          = max(0, current_price - strike)                                    (CALL)
                         = max(0, strike - current_price)                                     (PUT)
Intrinsic Value %        = Intrinsic Value / current_price × 100
Current Option Value     = valid Yahoo bid/ask midpoint, when available
                         = max(intrinsic value, premium + (current_price - entry_stock_price) × signed Entry Delta), otherwise
Estimated P&L            = (Current Option Value - premium) × 100 × contracts
Profit %                 = P&L / (premium × 100 × contracts) × 100
Theta 30-day run-rate    = 30 × |latest position theta|; not cumulative theta paid
```

**Intrinsic Value** is pure math — no Greeks required, just current price vs. strike (e.g. a $250 stock on a $200 strike CALL has $50/share of intrinsic value, 20% of the stock price). It is `None` only when `current_price` is unavailable. Unlike `Theoretical Value` (a delta-based estimate of the option's actual market price, including time value), `Intrinsic Value` is the floor — what the contract would be worth if it expired today with zero time value remaining. Shown per-share (not multiplied by `100 × contracts`), same convention as `Theoretical Value`, in the `LeapsSnapshot`'s "Computed" section (`display.render_leaps_detail`).

The rough P&L fallback uses **entry delta**, not current delta, across the stock move since entry; it is a local linear estimate and can be materially inaccurate as gamma, IV, and time change. For PUTs, conventional delta is negative. The current manually refreshed delta is used for current stock-equivalent exposure and scenario sensitivity. If there is no quote and no entry delta, estimated P&L is unavailable. Closed-position P&L is shown as realized only when a close price was recorded.

**Theta units — position-level $/day, not a per-share Greek:** `entry_theta`/`current_theta` store the full position's dollar decay per day as displayed by a broker, including multiplier and contract count. The wizard and `leaps update` prompt for this directly. The displayed 30-day run-rate multiplies the latest known magnitude by 30; it is not a historical accumulation or a forecast.

**Color thresholds:** Days-to-expiry — red once inside the 90-day default time-stop window (`LEAPS_DEFAULT_TIME_STOP_DAYS`), else green. Profit % — green at/above the position's profit target (`(profit_target_multiplier - 1) × 100`), yellow while positive but below target, red when negative. Delta (`analysis.leaps_delta_color()`) — green in the 0.75–0.85 sweet spot, yellow in the 0.70–0.90 warn band outside that spot, red/dim otherwise.

**Monitoring: `stocktool leaps update <id|ticker>`** — this command records manually entered current delta/theta/IV, with PUT delta stored conventionally negative, and also fetches a best-effort Yahoo option mark/IV. A valid two-sided midpoint drives current P&L; if unavailable, the entry-delta fallback is used. Current delta does not extrapolate the full historical stock move. `leaps show` displays source/timestamps and entry vs. current Greeks. Theta is reported as a current 30-day run-rate, not an accumulated amount. No live option-Greeks feed exists in this tool.

**Gamma / delta curve:** `analysis.build_leaps_gamma_curve()` calculates European Black–Scholes delta and gamma from the current stock price, strike, time to expiry, option IV, risk-free rate, and dividend yield. The terminal chart plots theoretical signed delta over stock prices from 80% to 120% of spot, marks the current spot, and reports gamma in delta points per $1 underlying move. It explains local `Δdelta ≈ gamma × Δstock`; for long puts, gamma remains positive while delta is negative, so a rising stock moves put delta toward zero. This model view is separate: broker-entered current/entry delta continues to drive exposure and existing linear scenarios.

Model inputs are best-effort and recomputed per `leaps add`, `leaps show`, and `leaps update`: Yahoo option-chain IV (or clearly labeled manual current/entry IV), latest Yahoo `^TNX` close as a 10-year yield proxy (including its date), and Yahoo dividend yield. `dividendYield` is interpreted in the project's percentage-point convention; `yield` and `trailingAnnualDividendYield` are fractions converted to percent. A zero yield is accepted only when Yahoo explicitly reports zero `dividendYield` or `dividendRate=0`. Missing/invalid required inputs produce an unavailable explanation, never a guessed rate or yield. The chart holds IV, time, rates, and yield fixed across the scenario range; it is not a forecast or American-option pricing model. Gamma is local and changes along the curve.

**Stock-Equivalent Exposure (the "LEAPS behaves as stock" view):** added directly from the project's own LEAPS tutorial — a deep-ITM LEAPS is deliberately used as a stock substitute on highest-conviction names, so the tool should surface *actual* market exposure, not just cash-at-risk. New `LeapsSnapshot` fields, computed in `build_leaps_snapshot()`:

```
Effective Delta          = current_delta if set (via `leaps update`), else entry_delta
Effective Shares         = signed Effective Delta × 100 × contracts (PUTs are negative)
Effective Exposure       = Effective Shares × current_stock_price
Effective Position %     = |Effective Exposure| / portfolio_value × 100
Leverage Ratio           = |Effective Delta × current_stock_price| / current option value
```

`Effective Exposure` retains its sign to show direction; position-size percentage and leverage use absolute magnitude. Leverage uses the best available current option value, so it is unavailable when neither a quote nor a usable model value exists.

Color thresholds: `analysis.leaps_leverage_color()` — green ≤4x (solidly stock-like), yellow 4–7x (typical deep-ITM LEAPS), red >7x (drifted into speculative, low-delta territory — recheck with `leaps update`). `analysis.leaps_exposure_color()` reuses the wizard's own `LEAPS_WARN_POSITION_PCT`/`LEAPS_MAX_POSITION_PCT` bands (3%/5%) applied to `effective_position_pct` instead of cash. `leaps list`'s summary panel flags any active position whose delta has drifted red or whose leverage has crossed 7x, so multi-position monitoring doesn't require opening each one with `leaps show`.

**Vega + IV Impact:** `analysis._black_scholes_greeks()` extends the existing delta/gamma Black–Scholes helper to also return vega (textbook per-share vega for a 100-point vol move, divided by 100 for one percentage point, multiplied by 100 shares per contract — the two scalings cancel, so the raw `S × e^(-qT) × φ(d1) × √T` is already the right per-contract-per-point number). `LeapsGammaCurve.vega` carries this at the current spot alongside the existing `model_delta`/`gamma`. `analysis.LeapsVegaImpact` + `build_leaps_vega_impact(curve, position, current_iv)` turn that into dollar figures: `vega_total` (`vega × contracts`), the dollar impact of ±10/-20 IV points, and `vega_pnl_since_entry` (`vega_total × (current_iv − entry_iv)`, preferring this run's live option-chain IV, then saved current IV, then clearly flagged entry-IV fallback). Rendered by `display.render_leaps_vega_section()` right after the gamma/delta chart in `leaps show`/`leaps update`. It is a constant-vega approximation; vega changes with price, time, and IV. Not shown in `leaps add`'s wizard.

**IV Rank (self-tracked history):** `analysis.leaps_iv_rank(current_iv, iv_history)` measures today's IV position as a percentage of the span from the *minimum to maximum* of this position's accumulated `iv_history`; this is a range rank, not an empirical percentile or a true 52-week range. It uses only readings captured since tracking started and returns `None` below `LEAPS_IV_RANK_MIN_READINGS` (5) readings. A 4-tier ladder — `LEAPS_IV_RANK_CHEAP_MAX`/`NORMAL_MAX`/`ELEVATED_MAX` (30/60/80) — maps to CHEAP / NORMAL / ELEVATED / EXPENSIVE. It sits alongside the CHEAP/FAIR/EXPENSIVE realized-volatility verdict above; the two use different comparisons. `leaps show` appends one `IvReading` per calendar day, deduped so repeated same-day runs don't flood the history. In the IV History block, a difference over 5 points between the entry-day reading and manually entered entry IV produces an entry-day mismatch note.

**Earnings Move History:** `data.fetch_next_earnings_date(ticker)` is the earnings-date lookup used by `leaps show`/`leaps update`. `data.fetch_earnings_move_history(ticker, quarters=8)` compares the close on the last trading day before each report date to the first close strictly after it. This includes a possible after-hours reaction, but can include an extra session for before-market reports because Yahoo does not reliably identify release timing. The display labels this an earnings-window move rather than a precise post-report return. `analysis.leaps_earnings_move_stats()` summarizes absolute moves; `build_leaps_earnings_context()` combines them with effective delta for a **delta-only** scenario. It does not estimate IV crush. Rendered by `display.render_leaps_earnings_context()` after the Vega Analysis panel.

**Liquidity (spread, volume, open interest):** `fetch_leaps_option_quote()` and `fetch_leaps_option_context()` now also pull `volume`/`openInterest` from the same `option_chain()` row already read for bid/ask/IV — nearly free, no new yfinance call. `analysis.leaps_liquidity_rating(spread_pct, open_interest)` rates TIGHT (green, <1% spread & >500 OI) / MODERATE (yellow, <3% & >100) / WIDE (`orange3`, <5% & >50) / ILLIQUID (red) — same 4-tier palette as IV Rank — returning `("N/A", "dim")` whenever either input is missing rather than guessing. `display.render_leaps_liquidity()` shows bid/ask/mid/spread (in $ and % of mid), a round-trip spread-cost estimate (`(ask − bid) × 100 × contracts`, labeled as an estimate, not a guaranteed execution cost), volume, open interest, and the volume/OI ratio. Not stored on `LeapsSnapshot` — passed straight from the `option_quote` dict both callers already hold.

**Value-investor cross-check:** both `leaps add` (right after the ticker is approved) and `leaps show` call `cli._render_leaps_value_check()`, which reuses the *exact same engine* as `stocktool valuation` — `analysis.build_valuation_snapshot()` fed by `data.fetch_fundamentals`, `fetch_price_history` (180-day), `fetch_revenue_estimates`, `fetch_balance_sheets`, and `fetch_cashflow_basics`. It surfaces `possible_return_pct` (colored via the new `analysis.possible_return_verdict()`, mirroring the thresholds already used in `display.render_valuation`: ≥50% strong, 15–50% moderate, 0–15% limited, <0% downside) and the DCF `margin_of_safety_pct`/`iv_rating`/`iv_rating_color` fields. This is a pure cross-check, not a gate — it never blocks the wizard, it only informs. **`fetch_cashflow_basics` is required here**, not optional: without it, `build_valuation_snapshot`'s DCF step falls back to a raw `freeCashflow` proxy that can be wildly wrong (observed on AMZN: −2316% "Overvalued" instead of the correct +21.7% "Fair Value") — always fetch it alongside the other four calls for this cross-check.

**Scenario Analysis (at-expiration P&L ladder):** `analysis.build_leaps_scenario()` (used by both `leaps add`'s confirmation step and `leaps show`) computes a pure-math, no-Greeks-required table of intrinsic value / P&L / return at a spread of hypothetical expiration prices, plus:

```
Intrinsic (CALL) = max(0, price - strike) × 100 × contracts
Intrinsic (PUT)  = max(0, strike - price) × 100 × contracts
P&L              = Intrinsic - (premium × 100 × contracts)
Return %         = P&L / (premium × 100 × contracts) × 100
```

Price points are generated from a fixed set of multipliers on the current (or entry) stock price — `[0.7, 0.85, 0.95, 1.0, 1.1, 1.2, 1.3, 1.4, 1.6]` for CALLs, the mirrored descending set for PUTs — plus the strike and breakeven always inserted explicitly, deduped and sorted. "Key Levels" states the 100%-loss threshold, breakeven, and the % move (with direction — "rise" for CALL, "fall" for PUT) needed to break even within the remaining days-to-expiry (shown in months). Two named "+20% / +40% move" scenarios are included as a quick gut-check.

**Early-exit estimate:** starts from current stock price and the current option value (Yahoo midpoint, or a clearly labeled entry-delta estimate) and solves locally using signed current delta, falling back to entry delta. It is a rough guide that omits theta, IV, and gamma changes; PUT direction is handled by its negative delta. The accompanying "Warning Signs" panel points to `leaps show`/`leaps update` for the current self-tracked IV Rank (see above) and restates the time-stop date (`expiration − days_before_expiry_exit`).

**Loss-exit scenario (downside alert):** uses the same current-price/current-option-value anchor and local signed-delta approximation as the early-exit estimate, with fixed -30% and -50% option-value thresholds. It omits theta, IV, and gamma changes. Target stock levels are indicative scenarios, not price predictions.

**Theta Decay Acceleration Date:** answers "on what date does time decay start meaningfully working against this position?" — separate from the fixed `LEAPS_DEFAULT_TIME_STOP_DAYS` (90-day) exit rule, which uses the same flat day count for every contract regardless of how long the LEAPS runs. Grounded in the standard options-pricing heuristic that time value decays roughly proportional to `sqrt(days remaining)`, so daily theta roughly doubles once remaining life drops to 1/4 of its value — "last third of life" is the commonly-cited point where decay becomes materially faster.

```
Total Life            = expiration − entry_date
Decay Acceleration    = expiration − (Total Life × LEAPS_DECAY_ACCELERATION_FRACTION)   [default 1/3]
```

`analysis.compute_leaps_decay_date(entry_date, expiration)` is the single source of this formula — returns `(decay_acceleration_date, days_to_decay_acceleration)`, called from `build_leaps_snapshot()` (populates `LeapsSnapshot.decay_acceleration_date` / `days_to_decay_acceleration`) and directly from `leaps add`'s confirmation step (no snapshot exists yet at that point in the wizard). Falls back to treating today as the start of life if `entry_date` is missing, mirroring `days_held`'s own fallback.

**Color/surfacing:** `analysis.leaps_decay_color()` is binary — red once `days_to_decay_acceleration <= 0`, else green — same pattern as `leaps_dte_color()`. Rendered in three places: a line in `render_leaps_detail()`'s Computed section ("N days of slow decay left" / "passed N days ago — theta now eroding faster each week"), a summary flag in `render_leaps_list()` ("In accelerated decay zone: TICKER") alongside the existing time-stop/delta-drift/leverage flags, and a line in `leaps add`'s confirmation Summary printed right after the exit-rule line.

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
