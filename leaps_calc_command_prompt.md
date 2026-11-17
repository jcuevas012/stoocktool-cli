# Build `stocktool calc leaps` — LEAPS Decision Analyzer Command

**Target audience:** Claude Code building a new command in my existing `stocktool` CLI.

---

## 1. Mission

Build a new subcommand `calc leaps` that evaluates a LEAPS options contract against my personal, locked investment framework. The output must tell me in **under 5 seconds**:

1. Does this contract comply with ALL my rules? (green/red checklist)
2. What are the realistic return scenarios (short-term + at expiration)?
3. Where are my +50% exit and -50% stop trigger prices?
4. Should I buy it, wait, or reject it?

The command replaces my current habit of manually computing scenarios in a spreadsheet. It must encode every rule below so I never forget or override one in a moment of FOMO.

---

## 2. My Locked Framework (encode these as rules)

### 2.1 LEAPS entry rules (5 non-negotiable)

1. **Approved names only:** GOOGL, AMZN, MSFT, META, NVDA, TSM, AVGO — reject anything else
2. **Deep ITM delta:** 0.75 to 0.85 (reject outside this range, flag yellow if 0.70-0.75 or 0.85-0.90)
3. **Minimum 12-18 months to expiry** (reject if DTE < 365)
4. **Max 5% of portfolio NAV per LEAPS** (hard rule — reject if contract cost > 5% of NAV)
5. **Exit trigger:** sell at +50% premium gain OR 90 days before expiry (whichever comes first)

### 2.2 IV entry rules

- Reject if **IV 52-week percentile > 70% AND earnings <30 days away** (IV crush trap)
- Position sizing calibrated to IV:
  - **IV 25-40%:** position can be 3-4% of portfolio
  - **IV 40-60%:** position can be 2-3% of portfolio
  - **IV >60%:** position should be 1% or avoid entirely

### 2.3 Diversification rules

- Minimum 3 sectors when running 3+ LEAPS
- No two LEAPS with correlation > 0.70 (GOOGL + AMZN together = NOT diversified, both MAG7)
- Correlation matrix I use:
  - GOOGL-AMZN: 0.78
  - GOOGL-MSFT: 0.75
  - GOOGL-META: 0.72
  - MSFT-META: 0.80
  - NVDA-AVGO: 0.82
  - NVDA-TSM: 0.74
  - AMZN-MSFT: 0.70
  - AVGO-TSM: 0.76
  - (anything else: assume 0.65 unless specified)

### 2.4 Stop loss

- **-50% of premium paid** = hard stop
- Stop loss price (stock) ≈ Entry stock - (0.5 × Entry premium ÷ delta)

### 2.5 Exit price formula (+50% target)

```
Exit stock price = Entry stock + (0.5 × Entry premium ÷ average delta)
```

### 2.6 Phased deployment plan (match contract to portfolio phase)

| Phase | NAV trigger | What's allowed |
|---|---|---|
| Phase 1 | Current | Paper only — AMZN + GOOGL |
| Phase 2 | $100K-120K | Add NVDA + TSM paper practice |
| Phase 3 | $120K+ | 1st real LEAPS: GOOGL Jun 2028 $260C (~$8K) + AMZN Jan 2028 $220C (~$7K) |
| Phase 4 | $150K+ | Add TSM LEAPS (~$5K) for sector mix |
| Phase 5 | $200K+ | Add PLTR LEAPS (~$5K) orchestration + small thematic |
| Phase 6 | $300K+ | Add TSLA LEAPS (2-3% due to high IV) |

- Reject real-money buys below the phase threshold for that name
- Allow "paper" mode via `--paper` flag with no NAV check

### 2.7 Fill discipline

- Always flag if the user is about to pay the **ask**
- Target fill = bid/ask midpoint
- Warn if bid-ask spread > 5% of midpoint (liquidity risk)

### 2.8 Safe margin rules (for cash availability check)

- Current account margin must be < 10% of NAV before allowing new LEAPS
- If margin is above hard cap: reject with reason "margin must be below 10% of NAV before deploying new positions"

---

## 3. Command Signature

```bash
stocktool calc leaps <TICKER> --strike <PRICE> --expiration <YYYY-MM-DD> [OPTIONS]

Required:
  <TICKER>              Ticker symbol (e.g. GOOGL)
  --strike <PRICE>      Option strike price
  --expiration <DATE>   Expiration YYYY-MM-DD (resolves to nearest actual expiry if not exact)

Optional:
  --premium <PRICE>     Override auto-pulled premium (defaults to IBKR mid-point)
  --nav <AMOUNT>        Portfolio NAV for sizing check (defaults to IBKR account summary)
  --paper               Treat as paper trade (skip NAV/margin phase checks)
  --compare <STRIKE>    Compare this contract to another strike side-by-side
  --output <FORMAT>     table | json | compact (default: table)
  --save                Save evaluation to history (SQLite)
  --chart               Render ASCII payoff diagram inline
  --scenarios <STOCK_PRICES>  Comma-separated list of prices to evaluate (e.g. 260,280,300,340,380)
```

Examples:
```bash
# Full analysis of GOOGL Jun 2028 $260 Call
stocktool calc leaps GOOGL --strike 260 --expiration 2028-06-16 --chart

# Compare two strikes
stocktool calc leaps GOOGL --strike 260 --expiration 2028-06-16 --compare 270

# Paper mode (skips phase check)
stocktool calc leaps NVDA --strike 170 --expiration 2028-01-21 --paper

# Pull from IBKR with custom NAV
stocktool calc leaps AMZN --strike 220 --expiration 2028-01-21 --nav 95000
```

---

## 4. Required Computations

### 4.1 Pull data from IBKR connector

Use these existing patterns (we already have IBKR API integration in `stocktool`):

```python
# Resolve underlying contract_id from ticker
underlying = ibkr.search_contracts(query=ticker)

# Get current underlying price + IV
snapshot = ibkr.get_price_snapshot(
    contract_id=underlying.contract_id,
    market_data_names=["last", "bid_ask", "implied_vol_underlying",
                       "misc_statistics", "historical_vol",
                       "implied_volatility_percentile"]
)

# Resolve expiration_id (nearest to requested date)
params = ibkr.get_option_parameters(underlying_contract_id=underlying.contract_id)
expiration_id = find_nearest_expiration(params.expirations, requested_date)

# Get option chain for strike range (strike ± $20)
chain = ibkr.get_option_data(
    expiration_id=expiration_id,
    min_strike=strike - 20,
    max_strike=strike + 20
)

# Resolve call contract_id for requested strike
option_contract_id = chain.find_by_strike(strike).call_contract_id

# Get option Greeks and pricing
option_data = ibkr.get_price_snapshot(
    contract_id=option_contract_id,
    market_data_names=["bid_ask", "last", "option_greeks",
                       "option_midpoint_iv", "option_volume",
                       "option_open_interest"]
)

# Account info for sizing/margin check
account = ibkr.get_account_summary()
```

### 4.2 Core metrics to compute

```python
# Basic
days_to_expiry = (expiration_date - today).days
contract_cost = premium * 100  # options are 100 shares per contract
breakeven_stock_price = strike + premium

# Position size
position_size_pct = contract_cost / nav
max_position_cost = nav * 0.05  # 5% rule

# IV-based max sizing
iv_pct = underlying_iv * 100
if iv_pct < 40:
    iv_max_pct = 0.04
elif iv_pct < 60:
    iv_max_pct = 0.03
else:
    iv_max_pct = 0.01
iv_max_cost = nav * iv_max_pct

# Exit triggers
exit_price_50_pct = entry_stock + (0.5 * premium / delta)
stop_loss_50_pct = entry_stock - (0.5 * premium / delta)
critical_exit_date = expiration_date - timedelta(days=90)

# Required moves
breakeven_move_pct = (breakeven_stock_price - current_price) / current_price * 100
exit_move_pct = (exit_price_50_pct - current_price) / current_price * 100
stop_move_pct = (stop_loss_50_pct - current_price) / current_price * 100

# Theta decay projections (in $ per contract)
theta_30d = theta * 30 * 100
theta_90d = theta * 90 * 100
theta_180d = theta * 180 * 100
theta_365d = theta * 365 * 100
```

### 4.3 Scenario matrix

Generate P&L at a grid of stock prices × time horizons.

**Default stock price grid** (if `--scenarios` not provided):
- Current price × [0.75, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.35, 1.50]

**Time horizon grid:**
- Today (delta-based estimate)
- +30 days (delta-based + theta decay)
- +90 days (delta-based + theta decay)
- +180 days (delta-based + theta decay)
- At expiration (pure intrinsic value, no time value)

**Price calculation methods:**
```python
# Short-term (any date before expiration):
# Uses delta for price-move impact + theta for time decay
# This is a simplification — assumes delta stays constant (fine for ±20% moves)
def project_premium_short_term(current_premium, delta, theta,
                                stock_move_dollars, days_forward):
    delta_pnl = delta * stock_move_dollars
    theta_pnl = -theta * days_forward  # theta is negative, so this subtracts
    return current_premium + delta_pnl - (theta * days_forward)

# At expiration (intrinsic value only):
def premium_at_expiration(strike, stock_price_at_expiry):
    return max(0, stock_price_at_expiry - strike)
```

### 4.4 Rule compliance checks

Return a dict/list of each rule with status:

```python
rules_checks = [
    {
        "rule": "Approved ticker",
        "required": "GOOGL, AMZN, MSFT, META, NVDA, TSM, AVGO",
        "actual": ticker,
        "pass": ticker in APPROVED_NAMES,
        "severity": "blocking" if not pass else "ok"
    },
    {
        "rule": "Delta range",
        "required": "0.75 to 0.85",
        "actual": f"{delta:.2f}",
        "pass": 0.75 <= delta <= 0.85,
        "severity": "warning" if 0.70 <= delta < 0.75 else "blocking"
    },
    {
        "rule": "Days to expiry",
        "required": ">= 365 days",
        "actual": f"{days_to_expiry} days",
        "pass": days_to_expiry >= 365,
    },
    {
        "rule": "Position size",
        "required": f"<= ${max_position_cost:,.0f} (5% of ${nav:,.0f})",
        "actual": f"${contract_cost:,.0f} ({position_size_pct*100:.1f}%)",
        "pass": contract_cost <= max_position_cost,
        "severity": "blocking"
    },
    {
        "rule": "IV level",
        "required": "IV < 40% for 3-4% sizing, < 60% for 2-3%",
        "actual": f"{iv_pct:.1f}%",
        "pass": iv_pct < 60,
    },
    {
        "rule": "IV 52w percentile",
        "required": "< 70% if earnings <30 days",
        "actual": f"{iv_percentile*100:.0f}%",
        "pass": not (iv_percentile > 0.70 and days_to_earnings < 30)
    },
    {
        "rule": "Portfolio phase",
        "required": f"Phase for this name requires NAV >= ${phase_threshold:,.0f}",
        "actual": f"NAV ${nav:,.0f}",
        "pass": nav >= phase_threshold
    },
    {
        "rule": "Margin status",
        "required": "Margin < 10% of NAV",
        "actual": f"{margin_pct:.1f}%",
        "pass": margin_pct < 10
    },
    {
        "rule": "Bid-ask spread",
        "required": "< 5% of mid-point",
        "actual": f"{spread_pct:.1f}%",
        "pass": spread_pct < 5,
        "severity": "warning"
    },
    {
        "rule": "Correlation with existing LEAPS",
        "required": "No existing LEAPS with correlation > 0.70",
        "actual": f"Max correlation: {max_corr:.2f} with {corr_name}",
        "pass": max_corr <= 0.70
    }
]
```

Count: blocking failures, warnings, passes. Derive final **VERDICT**:
- 0 blocking failures → **BUY APPROVED** (green)
- 1+ blocking failures → **DO NOT BUY** (red)
- All pass but warnings → **BUY WITH CAUTION** (yellow)

---

## 5. Output Format

### 5.1 Default (table format)

```
╔══════════════════════════════════════════════════════════════════╗
║  LEAPS DECISION ANALYZER                              stocktool  ║
║  GOOGL Jun 16, 2028 $260 Call                                    ║
╠══════════════════════════════════════════════════════════════════╣
║  Underlying $294.73  |  Premium $81.13  |  Cost $8,113           ║
║  DTE 581 days        |  IV 36.8%        |  Delta 0.77            ║
╚══════════════════════════════════════════════════════════════════╝

RULE COMPLIANCE
──────────────────────────────────────────────────────────────────
  ✅ Approved ticker (GOOGL)
  ✅ Delta 0.77 in range (0.75-0.85)
  ✅ DTE 581 days (min 365)
  ✅ IV 36.8% (below 40% threshold)
  ✅ Earnings 75 days away
  ❌ POSITION SIZE: $8,113 = 10.0% of NAV (max 5% = $4,075)
  ❌ MARGIN: Account -$8,308 (12.3% of NAV, must be <10%)
  ❌ PHASE: NAV $81,500 < $120,000 Phase 3 trigger for GOOGL real LEAPS
  ⚠️  Correlation: 0.78 with existing AMZN paper LEAPS

VERDICT: ❌ DO NOT BUY — 3 blocking rules failed

KEY METRICS
──────────────────────────────────────────────────────────────────
  Breakeven at expiry        $341.13  (+15.7% move required)
  +50% exit trigger          $349.55  (+18.6% move required)
  -50% stop loss             $239.91  (-18.6% drawdown)
  Critical exit date         2028-03-18  (90 days before expiry)
  Max loss (if stock ≤ $260) -$8,113   (100% of premium)

THETA DECAY (if stock stays at $294.73)
──────────────────────────────────────────────────────────────────
   30 days:  -$174    (-2.1% of premium)
   90 days:  -$522    (-6.4% of premium)
  180 days:  -$1,044  (-12.9% of premium)
  365 days:  -$2,117  (-26.1% of premium)

SCENARIO MATRIX (P&L per contract)
──────────────────────────────────────────────────────────────────
                    │  Today    +30d     +90d     +180d    @Expiry
  $450  (+52.7%)    │  +$11,963 +$11,789 +$11,441 +$10,919 +$10,887
  $420  (+42.5%)    │  +$9,653  +$9,479  +$9,131  +$8,609  +$7,887
  $400  (+35.7%)    │  +$8,113  +$7,939  +$7,591  +$7,069  +$5,887
  $380  (+28.9%)    │  +$6,573  +$6,399  +$6,051  +$5,529  +$3,887
  $360  (+22.1%)    │  +$5,033  +$4,859  +$4,511  +$3,989  +$1,887
  $349  (+18.6%) 🎯 │  +$4,187  +$4,013  +$3,665  +$3,143  +$878
  $341  (+15.7%) BE │  +$3,571  +$3,397  +$3,049  +$2,527  $0
  $320  (+8.6%)     │  +$1,953  +$1,779  +$1,431  +$909    -$2,113
  $300  (+1.8%)     │  +$413    +$239    -$109    -$631    -$4,113
  $294  (0%)        │  $0       -$174    -$522    -$1,044  -$5,131
  $280  (-5.0%)     │  -$1,127  -$1,301  -$1,649  -$2,171  -$6,113
  $260  (-11.8%)    │  -$2,667  -$2,841  -$3,189  -$3,711  -$8,113
  $240  (-18.6%) 🛑 │  -$4,207  -$4,381  -$4,729  -$5,251  -$8,113

🎯 = +50% exit trigger   BE = Breakeven   🛑 = -50% stop loss

PORTFOLIO CONTEXT
──────────────────────────────────────────────────────────────────
  Current LEAPS:
    • GOOGL Jan 2028 $290C @ $83  (paper)
    • AMZN Jan 2028 $220C @ $67.50 (paper)
  This LEAPS correlation profile:
    • GOOGL-AMZN: 0.78 ⚠️
    • GOOGL-MSFT: 0.75 ⚠️
  Diversification check: would be 3rd GOOGL exposure (stock + paper LEAPS + real)

ACTION RECOMMENDATION
──────────────────────────────────────────────────────────────────
  Not yet — three blocking rules fail. Resolve first:
    1. Clear margin debt (target Dec 30, 2026 per locked plan)
    2. Grow portfolio to $120K (Phase 3 trigger — ~8-11 months out)
    3. Consider reducing GOOGL stock exposure first (currently 13.75%)

  When all three resolved, this is a strong candidate:
    • Low IV entry (36.8% vs 40% max)
    • Deep ITM delta 0.77
    • 19 months runway
    • Only 15.7% move needed to break even

  Set alert: when NAV >= $120,000, re-run this command.
```

### 5.2 Compact format (`--output compact`)

One-line summary for use in loops / dashboards:

```
GOOGL 2028-06-16 $260C | $81.13 | Δ0.77 IV36.8% | BE $341 (+15.7%) | Exit $350 | Stop $240 | VERDICT: ❌ BLOCKING (3 rules)
```

### 5.3 JSON format (`--output json`)

Full structured output for programmatic use. Include all computed values, all rule checks, all scenarios.

### 5.4 ASCII chart (`--chart` flag)

Render a terminal payoff diagram using `plotext` or similar:

```
Payoff Diagram: GOOGL Jun 2028 $260C
Y-axis: P&L per contract ($)
X-axis: GOOGL stock price at expiration

$15k ┤                                           ⡀⠒⠒
     │                                     ⡀⠒⠒⠁
$10k ┤                               ⡀⠒⠒⠁
     │                         ⡀⠒⠒⠁
$5k  ┤                   ⡀⠒⠒⠁ 🎯
     │             ⡀⠒⠒⠁
$0   ┼────────⡀⠒⠒⠁ BE─────────────────────
     │  ⡀⠒⠒⠁
-$5k ┤⠒⠁ 🛑
     │
-$10k┤________________________________________
     $200 $240 $260 $280 $300 $320 $340 $360 $380 $400 $420 $450
```

---

## 6. Data Storage (SQLite)

Add a new table `leaps_evaluations` to track every analysis:

```sql
CREATE TABLE IF NOT EXISTS leaps_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ticker TEXT NOT NULL,
    expiration_date DATE NOT NULL,
    strike REAL NOT NULL,
    premium REAL NOT NULL,
    underlying_price REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    iv REAL,
    iv_percentile REAL,
    days_to_expiry INTEGER,
    nav_at_eval REAL,
    position_size_pct REAL,
    breakeven_price REAL,
    exit_trigger_price REAL,
    stop_loss_price REAL,
    verdict TEXT NOT NULL,  -- APPROVED | CAUTION | BLOCKED
    blocking_failures_json TEXT,
    warnings_json TEXT,
    raw_computation_json TEXT
);
```

Save every evaluation when `--save` flag is used. Add a `stocktool calc history leaps` command to view past evaluations.

---

## 7. Edge Cases to Handle

1. **Strike doesn't exist** at that expiration → suggest 2 nearest strikes (above + below), explain increment
2. **Expiration doesn't exist** → use nearest actual expiration date (3rd Friday of month typically)
3. **Greeks return empty** from IBKR (common for illiquid contracts) → estimate delta using Black-Scholes approximation or warn user
4. **IV data missing** → warn and skip IV-related checks
5. **No existing LEAPS in portfolio** → skip correlation check, don't flag
6. **NAV flag not provided + IBKR call fails** → error out with clear message, don't guess
7. **Negative cash in account** → compute margin as |cash|/NAV × 100, flag if >10%
8. **Contract already exists in portfolio** → warn user (potential duplication)
9. **Paper mode (`--paper`)** → skip NAV check, phase check, margin check; still run IV, delta, DTE, correlation checks

---

## 8. Testing Scenarios

Include test cases:

```python
# Test 1: Current state — GOOGL Jun 2028 $260C should FAIL
# Expected: 3 blocking failures (position size, margin, phase)

# Test 2: Same contract at Phase 3 ($120K NAV, no margin)
# Expected: PASS all rules, VERDICT: APPROVED

# Test 3: NVDA $220 Jan 2028 Call with --paper flag
# Expected: Skip NAV/phase/margin, still check IV/delta/DTE

# Test 4: AMD Jun 2028 $200 Call
# Expected: FAIL immediately (approved names rule — AMD removed)

# Test 5: GOOGL Jan 2027 $290 Call (DTE < 365)
# Expected: FAIL (DTE rule)

# Test 6: GOOGL Jun 2028 $320 Call (deep OTM, low delta)
# Expected: FAIL (delta < 0.75)

# Test 7: TSLA Jun 2028 $400 Call (high IV ~60%, approved? No - not in list)
# Expected: FAIL (not approved — only becomes available at Phase 6)

# Test 8: --compare flag for GOOGL $260 vs $270
# Expected: Side-by-side output showing breakeven/exit/sizing differences
```

---

## 9. Technical Specifications

- **Language:** Python 3.11+
- **CLI framework:** Click or Typer (match existing `stocktool` pattern)
- **Pretty output:** Rich library
- **ASCII charts:** plotext
- **Data validation:** Pydantic
- **IBKR integration:** reuse existing `stocktool.ibkr` module
- **Date handling:** use `dateutil` for expiration parsing (nearest-Friday logic)
- **Formulas module:** put all option math in `stocktool/options/math.py` for reusability
- **Rules module:** `stocktool/options/rules.py` — one class per rule, each returning `RuleCheckResult`

Structure:

```
stocktool/
├── cli/
│   └── calc/
│       ├── __init__.py
│       ├── leaps.py          # the command
│       ├── output.py         # table, compact, json, chart formatters
│       └── history.py        # stocktool calc history leaps
├── options/
│   ├── math.py              # breakeven, exit, stop, scenarios, theta projections
│   ├── rules.py             # all rule check classes
│   ├── constants.py         # APPROVED_NAMES, CORRELATION_MATRIX, PHASE_THRESHOLDS
│   └── models.py            # Pydantic models for Contract, Evaluation, RuleCheckResult
└── ibkr/
    └── options.py           # pulls option chain, Greeks, snapshots
```

---

## 10. Nice-to-haves (Priority 2, can be deferred)

- `stocktool calc leaps --watch <TICKER>` → monitors price daily and sends alert when verdict changes
- Integration with real portfolio history to compute cumulative correlation (not just the static matrix)
- IV rank chart over 12 months when --chart passed
- `--vs-stock` flag to compare buying LEAPS vs buying equivalent dollar amount of stock
- Export to CSV: `--export analysis.csv`
- Breakeven probability using log-normal distribution (academic but useful)

---

## 11. Acceptance Criteria

The command is done when:

1. ✅ `stocktool calc leaps GOOGL --strike 260 --expiration 2028-06-16` returns full analysis matching Section 5.1 format
2. ✅ All 8 test scenarios in Section 8 pass
3. ✅ ASCII chart renders correctly in terminal
4. ✅ SQLite history saves evaluations
5. ✅ `--paper` flag bypasses NAV/margin/phase checks but preserves others
6. ✅ `--compare` flag produces side-by-side analysis
7. ✅ JSON output is valid and complete
8. ✅ No blocking failures are ever silently dismissed — they must appear in VERDICT
9. ✅ Error messages are human-readable (not raw tracebacks)
10. ✅ Runs in under 5 seconds for cached contract data

---

## 12. Final Notes

- **Do NOT allow a `--force` or `--override` flag** for blocking rules. The entire point is that the framework protects me from myself. If I want to override, I should edit the rules file explicitly.
- **Rule thresholds live in `constants.py`** — one place to change if I update my framework
- **Output should be scannable** — I'll run this on my phone sometimes. Use emoji sparingly but effectively (✅ ❌ ⚠️ 🎯 🛑)
- **Default to conservative interpretations** — if IV data is missing, assume high IV. If correlation unknown, assume 0.65. If earnings date unknown, assume <30 days.

The command should feel like a disciplined mentor that answers one question: **"Should I buy this LEAPS right now?"**

If the answer is "no," it should tell me *exactly which rules fail* so I know what to change — in the market, in my portfolio, or in my patience.

---

**Please implement this as a complete, production-ready command. Ask me only if a technical choice would significantly change the design (e.g. SQLite vs JSON for history, Click vs Typer). Otherwise, make sensible defaults and ship it.**
