# LEAPS Tracker Feature — Prompt for Claude Code

## Context for Claude Code

I'm building a new feature for my existing `stocktool` CLI tracker. The tool is written in Go (based on my stack: Node.js, Golang, Python, AWS CDK), uses Yahoo Finance as the data source, and already tracks my stock positions. I want to add a comprehensive LEAPS (Long-term Equity AnticiPation Securities) tracking subsystem.

**My context as the user:**
- Senior backend engineer (6+ years), work remotely for TrueNorth
- Based in DR/Medellín, EST-aligned
- Portfolio value ~$95K, planning first real LEAPS at $120K
- Use Interactive Brokers for execution
- Non-resident alien (no US capital gains tax)
- Have proven swing trade discipline (NBIS +21.8%, NOW +39%)

## Feature Overview

Build a `leaps` subcommand that:
1. Starts an interactive wizard to add new LEAPS positions
2. Calculates key metrics (delta, theta, IV, breakeven, max loss)
3. Tracks time-based milestones (90 days before expiry, earnings dates)
4. Sends email notifications for exit conditions
5. Fetches IV data despite Yahoo Finance's limitations

## Command Structure

```bash
stocktool leaps add              # Interactive wizard
stocktool leaps list             # Show all active LEAPS
stocktool leaps show <id>        # Detail view with Greeks
stocktool leaps check            # Run exit condition checks
stocktool leaps alerts           # Show pending notifications
stocktool leaps remove <id>      # Close/remove position
stocktool leaps analyze <ticker> # Pre-trade analysis (before buying)
```

## Interactive Wizard — `stocktool leaps add`

Build a step-by-step prompt flow using survey/promptui library:

### Wizard Steps

**Step 1: Underlying ticker**
- Prompt: "Ticker symbol (GOOGL, AMZN, MSFT only — high conviction):"
- Validate: Must be in approved list (configurable in config file)
- Fetch current stock price from Yahoo Finance
- Show: "Current price: $XXX.XX"

**Step 2: Option type**
- Prompt: "CALL or PUT? [CALL]"
- Default: CALL
- Explain: "LEAPS are typically CALLS for bullish positions"

**Step 3: Strike price**
- Prompt: "Strike price: $"
- Validate: Must be numeric
- Calculate: Distance from current = (current - strike) / current * 100
- Warn if < 10% ITM: "⚠️ This is not deep ITM. LEAPS rules suggest 15%+ ITM"
- Show: "Strike is X% in-the-money"

**Step 4: Expiration date**
- Prompt: "Expiration date (YYYY-MM-DD):"
- Validate: Must be at least 365 days away
- Error if < 12 months: "❌ LEAPS rule: minimum 12 months to expiry"
- Warn if > 24 months: "⚠️ Very long expiry increases vega risk"
- Calculate: Days to expiration

**Step 5: Premium paid**
- Prompt: "Premium paid per share: $"
- Calculate: Total cost = premium × 100
- Calculate: Breakeven = strike + premium
- Show summary

**Step 6: Delta at purchase**
- Prompt: "Delta at purchase (0.00-1.00):"
- Validate: Range check
- Warn if < 0.70: "⚠️ Below 0.70 delta is not deep ITM — higher risk"
- Warn if > 0.90: "⚠️ Very deep ITM — expensive, lower leverage"

**Step 7: Theta at purchase**
- Prompt: "Theta per day: -$"
- Store as negative number
- Calculate: Monthly theta cost = theta × 30

**Step 8: IV at purchase (if available)**
- Prompt: "Implied Volatility at purchase (%):"
- Optional but recommended
- Flag for later IV crush detection

**Step 9: Portfolio percentage check**
- Prompt: "What is your current total portfolio value? $"
- Calculate: Position size as % of portfolio
- Error if > 5%: "🚨 EXCEEDS 5% LEAPS RULE — Position too large"
- Warn if > 3%: "⚠️ Approaching max LEAPS allocation"

**Step 10: Exit rules**
- Prompt: "Profit target multiplier? [1.5 for +50%]"
- Prompt: "Days before expiry to force exit? [90]"
- Store these as alert triggers

**Step 11: Notification preferences**
- Prompt: "Email for alerts [default from config]:"
- Prompt: "Enable earnings alerts? [Y]"
- Prompt: "Enable profit target alerts? [Y]"
- Prompt: "Enable time-stop alerts? [Y]"

**Step 12: Confirmation**
- Show full summary
- Confirm before saving

## Data Model

```go
type LEAPSPosition struct {
    ID              string    // UUID
    Ticker          string    // GOOGL, AMZN, MSFT, etc.
    OptionType      string    // CALL or PUT
    Strike          float64   // $280.00
    Expiration      time.Time // Jan 21, 2028
    Premium         float64   // $65.30
    Contracts       int       // Default 1
    TotalCost       float64   // premium * 100 * contracts

    // Entry snapshot
    EntryDate       time.Time
    EntryStockPrice float64
    EntryDelta      float64
    EntryTheta      float64
    EntryIV         float64   // optional

    // Current snapshot (updated by `check` command)
    LastCheckedAt    time.Time
    CurrentStockPrice float64
    CurrentDelta     float64
    CurrentTheta     float64
    CurrentIV        float64
    CurrentValue     float64  // last known contract price
    UnrealizedPnL    float64

    // Exit rules
    ProfitTargetMultiplier float64 // 1.5 = +50%
    DaysBeforeExpiryExit   int     // 90
    StopLossMultiplier     float64 // 0.5 = -50% (optional)

    // Earnings tracking
    NextEarningsDate time.Time
    EarningsAlertSent bool

    // Status
    Status      string    // ACTIVE, CLOSED, STOPPED
    ClosedAt    *time.Time
    ClosePrice  *float64
    RealizedPnL *float64

    // Notifications
    AlertEmail  string
    AlertsSent  []AlertRecord
}

type AlertRecord struct {
    Type      string    // PROFIT_TARGET, TIME_STOP, EARNINGS, IV_CRUSH
    SentAt    time.Time
    Message   string
    Resolved  bool
}
```

## Calculations to Implement

### 1. Breakeven Price
```
breakeven = strike + premium (for CALL)
breakeven = strike - premium (for PUT)
```

### 2. Days to Expiration
```go
daysToExpiry := int(position.Expiration.Sub(time.Now()).Hours() / 24)
```

### 3. Portfolio Percentage
```
positionPct = (contracts * premium * 100) / portfolioValue * 100
```

### 4. Theoretical P&L at Current Stock Price
Simple delta-based estimation when live option price isn't available:
```
estimatedCurrentValue = originalPremium + (currentStockPrice - entryStockPrice) * entryDelta
estimatedPnL = (estimatedCurrentValue - originalPremium) * 100
```

### 5. Time Decay Accumulated
```
daysHeld := int(time.Since(entryDate).Hours() / 24)
accumulatedTheta := daysHeld * abs(entryTheta) * 100
```

### 6. Profit Percentage
```
profitPct = ((currentValue - originalPremium) / originalPremium) * 100
```

## Yahoo Finance Integration

### Current Capabilities
Yahoo Finance DOES provide via unofficial API:
- Stock prices (historical and current)
- Earnings dates
- Option chains (limited data)
- Basic options data: strike, bid, ask, volume, open interest, implied volatility

### Yahoo Finance Option Chain Endpoint
```
https://query2.finance.yahoo.com/v7/finance/options/{TICKER}
```

Returns JSON with:
- `calls[]` and `puts[]` arrays
- Each contract has: `strike`, `lastPrice`, `bid`, `ask`, `volume`, `openInterest`, `impliedVolatility`
- **Implied Volatility IS available** per contract

### Fetching Specific LEAPS Contract

```go
func FetchOptionContract(ticker string, expiration time.Time, strike float64, optionType string) (*OptionData, error) {
    // Yahoo API: https://query2.finance.yahoo.com/v7/finance/options/AMZN?date=UNIX_TIMESTAMP
    // UNIX timestamp = expiration date at midnight UTC

    expirationUnix := expiration.Unix()
    url := fmt.Sprintf("https://query2.finance.yahoo.com/v7/finance/options/%s?date=%d",
        ticker, expirationUnix)

    // Parse JSON response
    // Filter calls or puts array by strike
    // Return OptionData with IV included
}

type OptionData struct {
    ContractSymbol    string
    Strike            float64
    LastPrice         float64
    Bid               float64
    Ask               float64
    Volume            int
    OpenInterest      int
    ImpliedVolatility float64  // ← This is what you need
    InTheMoney        bool
}
```

### Delta/Theta Calculation (Not Provided by Yahoo)

Yahoo doesn't provide delta/theta directly. Two options:

**Option A: Black-Scholes Approximation (recommended)**
Implement Black-Scholes formulas in Go:
```go
func CalculateGreeks(stockPrice, strike, iv float64, daysToExpiry int, riskFreeRate float64, isCall bool) (delta, gamma, theta, vega float64) {
    T := float64(daysToExpiry) / 365.0

    d1 := (math.Log(stockPrice/strike) + (riskFreeRate + 0.5*iv*iv)*T) / (iv * math.Sqrt(T))
    d2 := d1 - iv*math.Sqrt(T)

    if isCall {
        delta = normalCDF(d1)
    } else {
        delta = normalCDF(d1) - 1
    }

    gamma = normalPDF(d1) / (stockPrice * iv * math.Sqrt(T))
    theta = (-stockPrice*normalPDF(d1)*iv/(2*math.Sqrt(T))) / 365  // per day
    vega = stockPrice * normalPDF(d1) * math.Sqrt(T) / 100  // per 1% IV change

    return
}
```

**Option B: Use IB API as supplementary source** (future enhancement)
- IB provides full Greeks via their API
- Requires authentication and local gateway
- More complex but more accurate

### IV Rank Calculation

Yahoo provides current IV but NOT historical IV rank. Build it yourself:

```go
func CalculateIVRank(ticker string) (float64, error) {
    // Fetch historical IV for last 252 trading days (1 year)
    // Need to store daily IV snapshots in local SQLite DB

    // IV Rank = (Current IV - 52w Low IV) / (52w High IV - 52w Low IV) * 100

    // Store daily IV in database each time `check` runs
    // After 60+ days of data, IV Rank becomes meaningful
}
```

**Implementation detail:** Create a background daily job that stores IV snapshots in SQLite:
```sql
CREATE TABLE iv_history (
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    iv REAL NOT NULL,
    PRIMARY KEY (ticker, date)
);
```

## Email Notification System

### Setup
Use `net/smtp` or a library like `gomail`:
```go
import "gopkg.in/mail.v2"
```

### Notification Triggers

**1. Profit Target Hit (+50% or custom)**
```
Subject: 🎯 LEAPS PROFIT TARGET: {TICKER} +{PCT}%

Your {TICKER} {EXPIRY} ${STRIKE} CALL is up {PCT}%!
Current estimated value: ${VALUE}
Entry: ${ENTRY} ({DAYS_AGO} days ago)
Profit: +${PROFIT}

ACTION: Consider selling to lock in gains.
Rule: Take profit at +50% within 60 days.

[Dashboard link]
```

**2. Time Stop Approaching (90 days before expiry)**
```
Subject: ⏰ LEAPS TIME STOP: {TICKER} expires in {DAYS} days

Your {TICKER} LEAPS is entering the theta decay danger zone.
Expiration: {EXPIRY} ({DAYS} days remaining)
Current P&L: {+/-}${AMOUNT}

ACTION: Close position OR roll to longer expiry.
Theta is accelerating — holding gets expensive now.

[Dashboard link]
```

**3. Earnings Approaching (14 days before)**
```
Subject: 📊 EARNINGS ALERT: {TICKER} reports on {DATE}

{TICKER} earnings scheduled for {EARNINGS_DATE}
Days until earnings: {DAYS}
Your current P&L: {+/-}${AMOUNT}

CONSIDER:
- If profitable: Sell before earnings to avoid IV crush
- If losing: Hold through (can't make it worse)
- Earnings typically crash IV 10-20% afterward

[Dashboard link]
```

**4. IV Crush Detection**
When current IV < entry IV - 15% without stock moving significantly:
```
Subject: 💥 IV CRUSH WARNING: {TICKER} LEAPS

Implied Volatility dropped from {ENTRY_IV}% to {CURRENT_IV}% ({DROP}%)
Stock price change: {+/-}{STOCK_PCT}%

Your option may have lost value despite stock being stable.
Estimated vega impact: ${VEGA_LOSS}

[Dashboard link]
```

**5. Stop Loss Hit (optional, -50% default)**
```
Subject: 🚨 LEAPS STOP LOSS: {TICKER} down {PCT}%

Your position has hit the configured stop loss.
Current value: ${VALUE} (-{PCT}% from entry)

ACTION: Review thesis. If invalidated, close position.
```

### Alert Scheduling

Run alerts via cron or built-in scheduler:
```bash
# Cron suggestion
0 9 * * 1-5 /path/to/stocktool leaps check --notify
```

The `check` command should:
1. Fetch current data for all active LEAPS
2. Update position records
3. Evaluate alert conditions
4. Send emails for triggered alerts
5. Mark alerts as sent (prevent duplicate emails)

### Deduplication

Track `alerts_sent` to prevent spamming:
```go
func shouldSendAlert(position LEAPSPosition, alertType string) bool {
    for _, alert := range position.AlertsSent {
        if alert.Type == alertType {
            // Already sent — only resend if condition changes significantly
            if alertType == "PROFIT_TARGET" {
                return alert.ProfitLevel+10 < currentProfit // Resend if 10% more profit
            }
            return false
        }
    }
    return true
}
```

## Pre-Trade Analysis — `stocktool leaps analyze <ticker>`

Before executing a real LEAPS, run analysis:

```
$ stocktool leaps analyze AMZN

AMZN LEAPS Analysis — October 1, 2026
=============================================

Current Price: $251.39
52-week range: $180.25 - $278.56
Days from 52w high: -9.7%

NEXT EARNINGS: October 31, 2026 (30 days)
⚠️ WARNING: Within 2-week pre-earnings window
Recommendation: WAIT until Nov 1-3 (post-earnings)

Available LEAPS Expirations:
  Jan 2027 (113 days)    [too short — not a LEAPS]
  Jun 2027 (265 days)    [acceptable]
  Jan 2028 (477 days)    [✅ IDEAL]
  Jan 2029 (842 days)    [very long]

RECOMMENDED CONTRACT:
  AMZN Jan 2028 $220 CALL (Deep ITM)
  Current premium: ~$65.30
  Delta estimated: 0.75
  Breakeven: $285.30 (+13.4% needed)

PORTFOLIO FIT:
  Position cost: $6,530
  Your portfolio: $95,000
  Position size: 6.9% ⚠️ EXCEEDS 5% rule

CURRENT IV RANK:
  Current IV: 35.2%
  52-week range: 28% - 55%
  IV Rank: 37 (moderate — acceptable)

VERDICT: WAIT
Reasons:
  1. Earnings in 30 days — IV may crush post-report
  2. Portfolio under $120K threshold for sizing rule
  3. Better entry window: Nov 1-3 after earnings
```

## Configuration File

`~/.stocktool/config.yaml`:
```yaml
leaps:
  approved_tickers:
    - GOOGL
    - AMZN
    - MSFT
  max_position_pct: 5.0
  min_days_to_expiry: 365
  default_profit_target: 1.5
  default_time_stop_days: 90

notifications:
  email:
    enabled: true
    recipient: jcq012@gmail.com
    smtp_host: smtp.gmail.com
    smtp_port: 587
    smtp_user: ${EMAIL_USER}
    smtp_password: ${EMAIL_PASSWORD}

portfolio:
  current_value: 95000  # Updated manually or via API

data_source:
  provider: yahoo
  cache_ttl_minutes: 15
```

## Database Schema (SQLite)

```sql
-- Active and historical LEAPS positions
CREATE TABLE leaps_positions (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    expiration DATE NOT NULL,
    premium REAL NOT NULL,
    contracts INTEGER DEFAULT 1,
    entry_date TIMESTAMP NOT NULL,
    entry_stock_price REAL NOT NULL,
    entry_delta REAL,
    entry_theta REAL,
    entry_iv REAL,
    profit_target_multiplier REAL DEFAULT 1.5,
    days_before_expiry_exit INTEGER DEFAULT 90,
    status TEXT DEFAULT 'ACTIVE',
    closed_at TIMESTAMP,
    close_price REAL,
    realized_pnl REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Snapshot history for tracking
CREATE TABLE leaps_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT NOT NULL,
    snapshot_at TIMESTAMP NOT NULL,
    stock_price REAL,
    option_bid REAL,
    option_ask REAL,
    option_last REAL,
    delta REAL,
    theta REAL,
    iv REAL,
    estimated_pnl REAL,
    FOREIGN KEY (position_id) REFERENCES leaps_positions(id)
);

-- IV history for IV rank calculations
CREATE TABLE iv_history (
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    iv REAL NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- Alert tracking
CREATE TABLE leaps_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    triggered_at TIMESTAMP NOT NULL,
    sent_at TIMESTAMP,
    message TEXT,
    resolved BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (position_id) REFERENCES leaps_positions(id)
);

-- Earnings calendar cache
CREATE TABLE earnings_calendar (
    ticker TEXT NOT NULL,
    earnings_date DATE NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (ticker)
);
```

## File Structure (Suggested)

```
stocktool/
├── cmd/
│   └── leaps/
│       ├── add.go           # Wizard
│       ├── list.go
│       ├── show.go
│       ├── check.go         # Alert runner
│       ├── analyze.go
│       └── remove.go
├── internal/
│   ├── leaps/
│   │   ├── position.go      # Data model
│   │   ├── calculator.go    # Greeks, breakeven, P&L
│   │   ├── blackscholes.go  # Options math
│   │   ├── alerts.go        # Alert conditions
│   │   └── repository.go    # SQLite CRUD
│   ├── yahoo/
│   │   ├── client.go
│   │   ├── options.go       # Option chain fetching
│   │   └── earnings.go      # Earnings dates
│   ├── notifications/
│   │   ├── email.go         # SMTP sender
│   │   └── templates/       # Email templates
│   └── config/
│       └── config.go
└── main.go
```

## Testing Requirements

1. Unit tests for Black-Scholes calculations (verify against known Greeks)
2. Mock Yahoo Finance responses for repeatable tests
3. Test alert deduplication logic
4. Test wizard with various edge cases (short expiry, bad delta, etc.)
5. Integration test: full flow from `add` → `check` → `alert`

## Development Priority Order

1. **Phase 1 (MVP):** Wizard + database + basic calculations
   - `leaps add` wizard
   - SQLite storage
   - `leaps list` and `leaps show`
   - Breakeven, days-to-expiry calculations

2. **Phase 2 (Data):** Yahoo integration
   - Fetch current stock price
   - Fetch option chain for specific LEAPS
   - Store IV snapshots

3. **Phase 3 (Alerts):** Notification system
   - `leaps check` command
   - Email templates
   - All 5 alert types
   - Deduplication

4. **Phase 4 (Analysis):** Pre-trade tool
   - `leaps analyze <ticker>` command
   - IV rank calculation (after 60 days of data)
   - Earnings calendar check

5. **Phase 5 (Enhancements):**
   - Black-Scholes Greeks calculation
   - Roll analysis (close + reopen longer expiry)
   - Export to CSV
   - Historical performance reports

## Specific Yahoo Finance Quirks to Handle

1. **Rate limiting:** Yahoo may throttle requests. Implement exponential backoff
2. **Options chain availability:** Not all expirations always available via API
3. **IV precision:** Yahoo IV sometimes returns 0 for illiquid contracts — skip those
4. **Date formats:** Yahoo uses Unix timestamps for expiration dates
5. **Weekend/holiday handling:** Earnings dates may not include time, assume after-close
6. **Delisted/missing data:** Handle 404s gracefully

## My LEAPS Rules (Must Enforce)

Add these as validation in the wizard:

| Rule | Enforcement |
|------|-------------|
| Only approved tickers (GOOGL, AMZN, MSFT, etc.) | Hard block |
| Delta 0.70-0.85 for deep ITM | Warn, allow override |
| Minimum 12 months to expiry | Hard block if < 365 days |
| Max 5% of portfolio per position | Warn if 3-5%, block if >5% unless override |
| Must have exit rules set | Default to +50% and 90-day time stop |
| Can't buy within 14 days of earnings | Warn with clear explanation |

## Example Session Flow

```bash
$ stocktool leaps add

LEAPS Wizard — Add New Position
================================

Ticker (GOOGL/AMZN/MSFT): AMZN
✓ Current price: $251.39

Option type [CALL]: CALL

Strike price: $ 220
✓ 12.5% in-the-money (good for deep ITM strategy)

Expiration (YYYY-MM-DD): 2028-01-21
✓ 477 days to expiration (passes 365-day minimum)

Premium paid per share: $ 65.30
Total cost: $6,530.00
Breakeven: $285.30 (stock needs +13.4% to break even)

Delta at purchase: 0.75
✓ Deep ITM delta range

Theta per day: -5.20
Monthly theta cost: $156

IV at purchase (optional): 35.2

Portfolio total value: $ 95000
Position size: 6.87% of portfolio
🚨 EXCEEDS 5% rule — Override? [y/N]: n

Operation cancelled. Position size too large.
Recommended portfolio size for this trade: $130,600

$ stocktool leaps analyze AMZN
# ... shows pre-trade analysis ...
```

## Deliverables

Build the complete feature with:
1. All 7 subcommands (add, list, show, check, alerts, remove, analyze)
2. Full wizard flow with validation
3. SQLite persistence
4. Yahoo Finance integration (with IV)
5. Email notifications (all 5 alert types)
6. Configuration file support
7. Unit tests for calculations
8. README with usage examples

## Final Note

This feature should feel like a trading assistant that enforces discipline. The wizard isn't just data entry — it's a checklist that prevents stupid trades. The alerts aren't noise — they're carefully timed to make exit decisions easier when emotions might get in the way.

My proven discipline comes from pre-defined rules (NBIS +21.8%, NOW +39% swings). This tool should extend that discipline to LEAPS, where options can go to zero if I don't exit properly.

Keep the UI simple, text-based, with clear ASCII tables. No fancy TUI needed. Focus on correctness over flash.
