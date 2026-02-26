# Portfolio Strategy — Growth Sleeve

> **Last updated:** 2026-02-26
> **Target annual return:** 15–30%

## Investment Context

This is the **aggressive growth sleeve** of a two-portfolio strategy:

| Sleeve | Size | Purpose | Holdings |
|--------|------|---------|----------|
| **401k (Yale Model)** | ~$20K | Diversification & defense | VXUS (international), VNQ (real estate), bonds |
| **This Portfolio** | ~$53K | US tech/innovation alpha | 12 stocks + 4 ETFs |

The 401k handles international, real estate, and fixed income exposure.
This portfolio intentionally overweights US tech/growth — the tech concentration is a **feature, not a bug**.

## Target Allocation (Total = 100%)

### Tier 1: Growth Engines (42%)
Core positions driving 15-30% returns. Largest allocations.

| Ticker | Target | Sector | Thesis |
|--------|--------|--------|--------|
| GOOGL | 12% | AI / Search / Cloud | Most diversified big tech (search, ads, cloud, YouTube, TPUs). Can pivot across business lines. ~33% margins, fortress balance sheet. **Preferred over NVDA for stability** |
| MSFT | 10% | Cloud / AI | ~39% margins, Azure + Copilot, enterprise AI distribution advantage |
| AMZN | 10% | Cloud / E-commerce | AWS + advertising flywheel, margin expansion runway |
| NVDA | 10% | Semiconductors / AI | 50%+ margins, AI infrastructure leader, datacenter GPU monopoly. Higher beta than GOOGL |

### Tier 2: High-Conviction Growth (15%)
Strong compounders with clear moats.

| Ticker | Target | Sector | Thesis |
|--------|--------|--------|--------|
| AVGO | 8% | Semiconductors / Networking | AI networking monopoly, VMware integration, ~36% margins |
| META | 7% | Social / AI | ~30% margins, AI-driven ad targeting, massive user base moat |

### Tier 3: Stable Compounders (14%)
Lower volatility, steady returns. Portfolio ballast within the growth sleeve.

| Ticker | Target | Sector | Thesis |
|--------|--------|--------|--------|
| V | 5% | Payments | 50% margins, payments duopoly, recession-resilient |
| AAPL | 5% | Consumer Tech | Ecosystem lock-in, services growth. Overlap with QQQM |
| UNH | 4% | Healthcare | Only non-tech sector bet. Defensive growth, DOJ overhang = opportunity |

### Tier 4: Speculative / High-Beta (4%)
Small positions with asymmetric upside. Keep sized small.

| Ticker | Target | Sector | Thesis |
|--------|--------|--------|--------|
| TSLA | 2% | EVs / Energy / Robotaxi | Narrative/optionality bet on robotaxi, energy storage, AI. Thin margins today |
| PLTR | 2% | AI / Defense | ~36% margins, government + enterprise AI platform. High PE but real moat |

### Tier 5: Value Anchor (5%)
Downside protection and crash-buying power.

| Ticker | Target | Sector | Thesis |
|--------|--------|--------|--------|
| BRK-B | 5% | Conglomerate / Financial | Massive cash reserves, low PE. Ballast + crash-buying power. Kept small to not drag growth |

### ETFs (28%)
Broad exposure + thematic bets. Watch for overlap with individual holdings.

| Ticker | Target | Category | Thesis |
|--------|--------|----------|--------|
| QQQM | 12% | Nasdaq 100 | Tech growth baseline. Reduced from 18% due to overlap with individual stocks |
| VOO | 8% | S&P 500 | Broad market floor. 401k also covers this |
| SMH | 5% | Semiconductors | Adds ASML, TSM, KLAC beyond NVDA/AVGO |
| CIBR | 3% | Cybersecurity | Secular theme, set-and-forget |

## Accumulation Strategy (Never Sell to Rebalance)

This portfolio follows a **buy-only DCA strategy**. We rebalance by directing new monthly contributions
toward underweight positions — never by selling overweight ones. Positions naturally converge to targets over time.

### Position Tier Rules

| Tier | Target Range | Buy Priority |
|------|-------------|-------------|
| Growth Engines | 10-12% each | HIGH — always acceptable to add, especially below 200d SMA |
| High-Conviction | 7-8% each | HIGH — add when underweight or below SMA |
| Stable Compounders | 4-5% each | MEDIUM — add slowly on dips |
| Speculative | 1-2% each | LOW — only on major dips, never let exceed 3% |
| Value Anchor | 5% | LOW — only during market crashes |

### Monthly Buy Decision Process

1. Run `stocktool portfolio rebalance` to see which positions are underweight
2. Run `stocktool portfolio sma` to see which positions are below 200d SMA
3. Run `stocktool strategy dip` to check VIX fear level
4. **Prioritize buys** using this matrix:

| Underweight? | Below SMA? | VIX > 30? | Action |
|:---:|:---:|:---:|--------|
| Yes | Yes | Yes | **TOP PRIORITY** — strongest buy signal, consider extra cash |
| Yes | Yes | No | **HIGH PRIORITY** — dip + underweight, add aggressively |
| Yes | No | — | **NORMAL** — standard DCA contribution |
| No | Yes | — | **OPPORTUNISTIC** — small add if conviction is high |
| No | No | — | **SKIP** — direct cash elsewhere |

### Extra Cash Deployment (e.g. $5K–$10K lump sum)

When adding extra cash beyond monthly DCA:

1. Run all three commands above to get the current picture
2. Rank positions by: **most underweight + below SMA + highest tier = buy first**
3. Spread across 2-4 positions max (don't spray across everything)
4. Tier 1 Growth Engines always get the largest share of extra cash
5. Never put extra cash into positions already overweight — let them naturally come back to target

## How to Analyze (Live Data Commands)

Use these commands to get **current** valuations and opportunities — don't rely on stale snapshots:

```bash
# Monthly check: where to direct new money
stocktool portfolio rebalance       # underweight positions = buy candidates
stocktool portfolio sma             # below SMA = dip opportunities
stocktool strategy dip              # VIX + combined dip signal

# Quarterly deep dive: valuation health check
stocktool valuation GOOGL MSFT AMZN NVDA AVGO META
stocktool valuation AAPL BRK-B V UNH TSLA PLTR

# Periodic: check ETF redundancy
stocktool portfolio overlap
```

## Valuation Guardrails

When running `stocktool valuation`, use these thresholds to decide action:

| Projected Return | Action |
|:---:|--------|
| > 50% | Strong buy if below SMA and underweight |
| 15–50% | Good DCA candidate, add on dips |
| 0–15% | Hold position, direct new cash elsewhere |
| < 0% | Re-evaluate thesis. Stop adding. Only position where selling is considered |

**Margin health check:** Debt/Assets > 40% = caution. Profit margin declining 2+ quarters = thesis risk.

## Key Risks to Monitor

1. **Tech concentration (~60-65% effective)** — intentional, but a sector rotation would hit hard. The 401k (VXUS, VNQ) provides the hedge
2. **TSLA + PLTR valuation** — combined 4% at extreme PEs. Don't let these grow beyond 5% total
3. **QQQM overlap** — even at 12%, QQQM duplicates your individual tech holdings. Run `stocktool portfolio overlap` periodically
4. **Interest rate sensitivity** — rising rates compress growth multiples. BRK-B + V + UNH provide some buffer
5. **Single-country risk** — 100% US in this sleeve. Acceptable because 401k holds VXUS

## Decision Rules

- **Monthly DCA:** Always buy the most underweight + below SMA position first
- **Extra cash ($5K+):** Spread across top 2-4 underweight positions, heaviest into Tier 1
- **When VIX > 30:** Use `stocktool strategy dip` — consider deploying margin on Tier 1 dips
- **Quarterly review:** Run `stocktool valuation` on all holdings
- **Thesis broken?** If margin trend reverses 2+ quarters, stop adding. Selling is last resort
- **New position criteria:** PE < 40x (or hyper-growth with >40% margins), strong buy consensus, below SMA preferred
- **Only sell if:** Thesis is fundamentally broken (not just a dip), or projected return is negative for 2+ quarters
