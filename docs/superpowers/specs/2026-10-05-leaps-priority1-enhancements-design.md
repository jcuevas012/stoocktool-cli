# LEAPS `show`/`update` Enhancements — Priority 1 (Vega, IV Rank, Earnings History, Liquidity)

## Context

A larger enhancement wishlist was proposed for `stocktool leaps` (12 features across three
priority tiers). That wishlist assumed a different implementation than this project actually
has (it described a database-backed system); this spec re-derives the first, highest-priority
slice of it — the four features the original request asked to build first — against how this
codebase actually works: positions persist as local JSON (`stocktool/leaps.py`), and every
other LEAPS view is computed fresh on each run (`analysis.build_leaps_snapshot`,
`build_leaps_gamma_curve`, `build_leaps_scenario`) rather than read from a database.

Later tiers of the original wishlist (portfolio-level summary, capital-efficiency comparison,
journal notes, Fibonacci zones, etc.) are explicitly out of scope here and will get their own
spec once this slice ships.

## Goals

1. Show **vega** and its dollar impact, so IV-driven P&L swings are visible alongside the
   existing delta/gamma view — LEAPS are long-dated and vega-sensitive, and today's tool has
   no vega at all.
2. Turn today's single CHEAP/FAIR/EXPENSIVE label (shipped earlier this session) into a real
   **IV Rank** percentile once enough of this tool's own tracked history exists, rather than
   leaving the user to guess what "expensive" means numerically.
3. Surface **historical earnings-move context** (how much the stock has actually moved after
   its last several reports) next to the existing earnings-date warning.
4. Surface **liquidity** (bid/ask spread, volume, open interest) — data already being fetched
   but currently discarded before it reaches the screen.

## Non-goals

- No new persistent store beyond appending to the existing per-position `iv_history` list.
- No historical IV-crush statistic — there is no historical implied-volatility data source
  available to this tool (free or otherwise), so this will not be fabricated. The earnings
  feature covers *price* moves only.
- No true 52-week IV range — only what this tool has actually recorded since the user started
  tracking a given position. Labeled honestly as such.
- No changes to `leaps add`'s wizard flow beyond what it already shows (earnings date, bid/ask,
  the CHEAP/FAIR/EXPENSIVE line). The new richer sections (vega, IV rank, earnings history,
  liquidity) appear in `leaps show` / `leaps update`'s detail view, not mid-wizard — keeps the
  add flow from growing longer than it already is.

## Feature 1: Vega + IV Impact

**Model.** `analysis._black_scholes_delta_gamma` is extended to also return vega (renamed
`_black_scholes_greeks`, returning `(delta, gamma, vega)`); all existing call sites are updated.
Vega is the standard Black–Scholes `S × e^(−qT) × φ(d1) × √T`, which — due to the percentage/
shares-per-contract scaling cancelling out — equals the dollar change in one contract's value
per 1 percentage-point move in IV. `LeapsGammaCurve` gains a `vega: float` field (computed once,
at the current spot, alongside the existing `model_delta`/`gamma`); the curve's price-sweep
points remain delta-only as today.

**Derived values** (new function `analysis.build_leaps_vega_impact(curve, position)` →
`LeapsVegaImpact` dataclass: `vega_per_contract`, `vega_total` (`× position.contracts`),
`impact_plus_10`, `impact_minus_10`, `impact_minus_20` (`vega_total × points`), `entry_iv`,
`current_iv`, `iv_change_pts` (`current_iv − entry_iv`, using `entry_iv` as fallback when
`current_iv` is unset), `vega_pnl_since_entry` (`vega_total × iv_change_pts`). Returns `None`
when the gamma curve itself is unavailable or `iv_change_pts` can't be computed (needs both an
entry and a current/fallback IV).

**Display** (`display.render_leaps_vega_section`): new panel after the existing gamma/delta
chart, since it reuses the same model inputs line. Caveat line: *"Uses today's vega as a
constant approximation across the whole move since entry — vega itself drifts with price, time,
and IV level."* Mirrors the existing gamma chart's own "holds inputs fixed" caveat style.

## Feature 2: IV Rank (from this tool's own tracked history)

**Formula** (new `analysis.leaps_iv_rank(current_iv, iv_history) -> LeapsIvRank | None`):
given the position's accumulated `iv_history` (today's reading included, see capture-cadence
change below), with `low = min(readings)`, `high = max(readings)`:

```
rank_pct = clamp((current_iv - low) / (high - low) * 100, 0, 100)   # 50 if high == low
```

Returns `None` (displayed as "not enough history yet — N/5 readings") when fewer than
`LEAPS_IV_RANK_MIN_READINGS` (5) readings exist. New config constants — a 4-tier ladder with
its own 4th color (`orange3`, between yellow and red), a deliberate first exception to this
tool's existing green/yellow/red-only LEAPS palette (delta, leverage, exposure, profit all stay
3-color) because this ladder specifically needs to distinguish "watch it" from "avoid it":

| Rank | Label | Color |
|---|---|---|
| 0–30 | CHEAP | green |
| 30–60 | NORMAL | yellow |
| 60–80 | ELEVATED | orange3 |
| 80–100 | EXPENSIVE | red |

(`LEAPS_IV_RANK_CHEAP_MAX=30`, `LEAPS_IV_RANK_NORMAL_MAX=60`, `LEAPS_IV_RANK_ELEVATED_MAX=80`.)
This sits *alongside*, not instead of, the already-shipped IV-vs-realized-volatility verdict —
the two answer different questions ("rich vs. this stock's own actual movement" vs. "rich vs.
what IV has actually done on this contract since you've tracked it") and are both useful.

**Capture-cadence change:** `leaps show` currently only *displays* IV; it will now also append
one `IvReading` per calendar day (deduped — if today's date is already the last entry, skip),
same as `leaps update` already does, so this history accumulates on every run rather than only
on explicit updates. This makes `leaps show` a (very small, append-only) write for the first
time — called out explicitly since `show` commands are usually read-only.

**Fields added to `LeapsSnapshot`:** `iv_rank_pct`, `iv_rank_label`, `iv_rank_color`,
`iv_range_low`, `iv_range_high`, `iv_rank_reading_count` — fits naturally alongside the existing
`iv_value_label`/`iv_value_color`/`iv_value_ratio` fields from the realized-vol verdict.

## Feature 3: Earnings Move History

**Data** (new `data.fetch_earnings_move_history(ticker, quarters=8) -> list[dict]`): fetches
`ticker.get_earnings_dates(limit=quarters + 4)` filtered to past dates (most recent `quarters`),
and one `ticker.history(period="3y")` call for daily closes. For each earnings date, finds the
closest prior and next trading-day closes and returns
`{"date": iso, "pct_move": signed %, "abs_pct_move": %}`. Skips any date where a bracketing
close can't be found (e.g. too close to the 3-year window edge). Never raises — returns `[]` on
any failure, same convention as the other `fetch_leaps_*` functions.

**Stats** (new `analysis.leaps_earnings_move_stats(moves) -> LeapsEarningsStats | None`):
`avg_abs_move_pct`, `max_abs_move_pct`, `quarters_used` (`len(moves)`). `None` if `moves` is
empty.

**Projection:** combines the stats with the position's existing effective delta —
`delta_impact = effective_delta × 100 × contracts × (current_price × avg_abs_move_pct / 100)`
— shown for both the average move and the max move, directionally signed for CALL/PUT. Labeled
plainly: *"Delta-only estimate — earnings often also moves IV sharply (usually down after the
report), and this tool has no reliable estimate of that IV change."* This intentionally does
**not** attempt the IV-crush dollar figure the original wishlist asked for (see Non-goals).

**New dataclass** `LeapsEarningsContext` (ticker, next_earnings_date, days_to_earnings,
avg_abs_move_pct, max_abs_move_pct, quarters_used, delta_impact_avg, delta_impact_max) built by
`analysis.build_leaps_earnings_context(...)`, rendered by a new
`display.render_leaps_earnings_context(...)` panel placed after "Computed" in `leaps show` /
`leaps update`'s output. Kept as a standalone dataclass (like `LeapsGammaCurve`/`LeapsScenario`
already are) rather than folded into `LeapsSnapshot`, since it's conceptually a separate concern
with its own data fetch.

## Feature 4: Liquidity (spread, volume, open interest)

**Data:** `data.fetch_leaps_option_quote` and `fetch_leaps_option_context` are extended to also
pull `volume` and `openInterest` from the same `option_chain()` row already being read (bid/ask/
IV are already pulled from this row today — this is almost free).

**Rating** (new `analysis.leaps_liquidity_rating(spread_pct, open_interest) -> (label, color)`),
same 4-tier palette as IV Rank above:

| Spread (of mid) | OI | Rating | Color |
|---|---|---|---|
| < 1% | > 500 | TIGHT | green |
| 1–3% | > 100 | MODERATE | yellow |
| 3–5% | > 50 | WIDE | orange3 |
| > 5% or missing OI/spread | ≤ 50 | ILLIQUID / N/A | red / dim |

**Display:** new `display.render_leaps_liquidity(option_quote, rating_label, rating_color,
spread_cost_estimate)` panel in `leaps show` / `leaps update`, showing bid/ask/mid/spread (both
$ and % of mid), a round-trip spread-cost estimate (`(ask − bid) × 100 × contracts`, labeled
"estimate, not a guaranteed execution cost"), volume, open interest, and the volume/OI ratio.
Not stored on `LeapsSnapshot` — passed straight from the already-fetched `option_quote` dict,
since `leaps show`/`leaps update` already hold it in scope.

## Small bug-fix polish: IV source-mismatch flag

If `position.entry_iv` is set and the `iv_history` entry dated on `entry_date` differs from it
by more than 5 points, show one inline note under the IV History block: *"⚠ Entry-day IV
mismatch: manually entered {entry_iv}% vs. Yahoo chain {history_iv}% that day."* Purely
defensive display logic — no change to which value the tool actually uses for computations
(`current_iv` falling back to `entry_iv`, unchanged).

## Files touched

- `stocktool/config.py` — new constants (`LEAPS_IV_RANK_MIN_READINGS`,
  `LEAPS_IV_RANK_CHEAP_MAX/NORMAL_MAX/ELEVATED_MAX`, liquidity spread/OI thresholds,
  `LEAPS_EARNINGS_HISTORY_QUARTERS`).
- `stocktool/data.py` — `fetch_earnings_move_history`; extend `fetch_leaps_option_quote` /
  `fetch_leaps_option_context` with `volume`/`open_interest`.
- `stocktool/analysis.py` — `_black_scholes_greeks` (rename + vega), `LeapsVegaImpact` +
  `build_leaps_vega_impact`, `leaps_iv_rank` + `LeapsIvRank`, new `LeapsSnapshot` IV-rank fields,
  `leaps_earnings_move_stats` + `LeapsEarningsStats`, `build_leaps_earnings_context` +
  `LeapsEarningsContext`, `leaps_liquidity_rating`.
- `stocktool/leaps.py` — no schema change; `iv_history` already supports this.
- `stocktool/cli.py` — `leaps_show`/`leaps_update` gain the new fetch calls, the daily
  auto-capture append (also applies to `leaps_show`), and wire the new sections into the render
  call; small IV-mismatch check.
- `stocktool/display.py` — `render_leaps_vega_section`, `render_leaps_earnings_context`,
  `render_leaps_liquidity`; mismatch note added to the existing IV History block.
- `CLAUDE.md` — new subsections documenting all of the above, following the existing LEAPS
  section's level of detail.

## Testing

- Vega: compare `_black_scholes_greeks`'s vega against a hand-computed value for a known
  (S, K, T, σ, r, q) tuple.
- IV rank: unit-test `leaps_iv_rank` with synthetic `iv_history` lists — below-minimum,
  exact-boundary (30/60/80), and flat-history (`high == low`) cases.
- Liquidity: unit-test `leaps_liquidity_rating` across its boundary values and the missing-data
  case.
- Earnings move stats: unit-test `leaps_earnings_move_stats` with a synthetic `moves` list
  (empty list → `None`; known values → exact avg/max).
- Manual: run `leaps show` / `leaps update` against a real active position (e.g. the existing
  AMZN position) and confirm all four new sections render without crashing when data is
  partially missing (no quote, no earnings date, <5 IV readings).
