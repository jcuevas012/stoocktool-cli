# LEAPS Priority 1 Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add vega/IV-impact, IV Rank, earnings move history, and liquidity display to `stocktool leaps show` / `leaps update`, exactly as scoped in the approved design spec.

**Architecture:** Four independent features, each following the existing `analysis.py` (compute) → `cli.py` (fetch + wire) → `display.py` (render) layering already used by `LeapsGammaCurve`/`LeapsScenario`. No new persistent store — everything is either computed fresh each run or appended to the existing per-position `iv_history` list in the local JSON file.

**Tech Stack:** Python, Typer CLI, `rich` terminal output, `yfinance` for market data, `unittest` (stdlib) for tests — no pytest, no database.

**Spec:** `docs/superpowers/specs/2026-10-05-leaps-priority1-enhancements-design.md`

## Global Constraints

- No new persistent store beyond appending to the existing per-position `iv_history` list (spec Non-goals).
- No historical IV-crush statistic anywhere — there is no data source for it; never fabricate one (spec Non-goals).
- No true 52-week IV range — only label what this tool has actually recorded since tracking started (spec Non-goals).
- No changes to `leaps add`'s wizard flow — the four new sections appear only in `leaps show` / `leaps update` (spec Non-goals).
- Every new `data.py` fetch function must never raise — return `[]` / `{}` / `None` on any failure, matching the existing `fetch_leaps_*` convention.
- The IV Rank and Liquidity ladders are 4-tier (green/yellow/`orange3`/red) — a deliberate, user-confirmed exception to this tool's otherwise 3-color LEAPS palette (delta/leverage/exposure/profit colors stay 3-tier, unchanged).
- CLAUDE.md must be updated to document every new feature (this project's standing instruction).
- Display functions in `display.py` contain zero business logic — they only format values already computed by `analysis.py` / `data.py`, matching the existing dependency direction documented in CLAUDE.md.

## Review Focus

1. Vega "P&L contribution since entry" must show a real `$0.00` when IV hasn't changed since entry — `None` is reserved for *missing* entry/current IV, never reused to mean "zero change" (classic falsy-zero bug). Owned by Task 2.
2. IV Rank must switch from "not enough history" to a computed percentage at exactly the configured minimum reading count, not one reading above or below it (off-by-one). Owned by Task 3.
3. The new daily auto-capture (`leaps show` now writes, not just reads) must not fire for CLOSED positions, and must not fire when no market IV was fetched this run. Owned by Task 4.
4. Liquidity rating must degrade to `("N/A", "dim")` rather than raising or mis-rating when open interest or the bid/ask spread is missing (new or illiquid contract, or an empty quote). Owned by Task 7.
5. The earnings-move fetch must return `[]` (never raise) on a yfinance exception, an empty earnings-dates response, or a too-short price-history window. Owned by Task 5.

---

### Task 1: Vega model — extend the Black–Scholes helper

**Files:**
- Modify: `stocktool/analysis.py:1370-1397` (`_black_scholes_delta_gamma`), `stocktool/analysis.py:1348-1363` (`LeapsGammaCurve`), `stocktool/analysis.py:1400-1460` (`build_leaps_gamma_curve`)
- Modify: `tests/test_leaps_gamma.py:54-58` (direct calls to the renamed function)

**Interfaces:**
- Produces: `analysis._black_scholes_greeks(option_type, stock_price, strike, years_to_expiry, volatility, risk_free_rate, dividend_yield) -> tuple[float, float, float]` (delta, gamma, vega). `LeapsGammaCurve.vega: float` (new field, dollars per contract per 1 IV-percentage-point move, computed once at the current spot).

- [ ] **Step 1: Write the failing test for vega** — append to `tests/test_leaps_gamma.py`:

```python
    def test_vega_matches_hand_computed_value(self):
        # S=100, K=100, T=1y, sigma=0.30, r=0.04, q=0.01 — same inputs as the gamma test above.
        # d1 = (ln(100/100) + (0.04 - 0.01 + 0.5*0.3^2)*1) / (0.3*1) = 0.0650 / 0.3 = 0.21667
        # phi(d1) = exp(-0.5*0.21667^2) / sqrt(2*pi) = 0.38910
        # vega = 100 * exp(-0.01*1) * 0.38910 * sqrt(1) = 38.5252 (within rounding)
        from stocktool.analysis import _black_scholes_greeks

        _, _, vega = _black_scholes_greeks("CALL", 100.0, 100.0, 1.0, 0.30, 0.04, 0.01)

        self.assertAlmostEqual(vega, 38.525, places=2)

    def test_vega_is_identical_for_call_and_put_same_strike(self):
        from stocktool.analysis import _black_scholes_greeks

        _, _, call_vega = _black_scholes_greeks("CALL", 100.0, 100.0, 1.0, 0.30, 0.04, 0.01)
        _, _, put_vega = _black_scholes_greeks("PUT", 100.0, 100.0, 1.0, 0.30, 0.04, 0.01)

        self.assertAlmostEqual(call_vega, put_vega, places=6)

    def test_curve_exposes_vega_at_current_spot(self):
        curve = self.build("CALL")

        self.assertIsNotNone(curve)
        self.assertGreater(curve.vega, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_leaps_gamma -v`
Expected: the three new tests `FAIL` with `AttributeError`/`ImportError` (`_black_scholes_greeks` doesn't exist yet, `LeapsGammaCurve` has no `vega` field).

- [ ] **Step 3: Rename and extend `_black_scholes_delta_gamma`**

In `stocktool/analysis.py`, replace the existing function (lines 1370-1397) with:

```python
def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value ** 2) / math.sqrt(2.0 * math.pi)


def _black_scholes_greeks(
    option_type: str,
    stock_price: float,
    strike: float,
    years_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> tuple[float, float, float]:
    """Return European Black–Scholes delta, gamma, and vega using continuous rates/yield.

    Vega is scaled to dollars per contract per 1 percentage-point change in IV: the textbook
    per-share vega (dollars per 1.00 = 100-point change in vol) divided by 100 for one
    percentage point, multiplied by 100 shares per contract — the two scalings cancel, so the
    raw S × e^(-qT) × φ(d1) × √T already is the right number.
    """
    if min(stock_price, strike, years_to_expiry, volatility) <= 0:
        raise ValueError("stock price, strike, time, and volatility must be positive")
    root_t = math.sqrt(years_to_expiry)
    d1 = (
        math.log(stock_price / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility**2) * years_to_expiry
    ) / (volatility * root_t)
    discounted_dividend = math.exp(-dividend_yield * years_to_expiry)
    if option_type.upper() == "CALL":
        delta = discounted_dividend * _normal_cdf(d1)
    elif option_type.upper() == "PUT":
        delta = discounted_dividend * (_normal_cdf(d1) - 1.0)
    else:
        raise ValueError("option_type must be CALL or PUT")
    pdf_d1 = _normal_pdf(d1)
    gamma = discounted_dividend * pdf_d1 / (stock_price * volatility * root_t)
    vega = stock_price * discounted_dividend * pdf_d1 * root_t
    return delta, gamma, vega
```

This keeps the gamma formula numerically identical (`pdf_d1` is exactly the `exp(-0.5*d1**2)/sqrt(2*pi)` the old code computed inline) — only the vega addition and the name/arity are new.

- [ ] **Step 4: Update `LeapsGammaCurve` and `build_leaps_gamma_curve`**

In the `LeapsGammaCurve` dataclass (around line 1348), add the field right after `gamma`:

```python
    gamma: float  # change in delta per $1 underlying move
    vega: float   # dollars per contract per 1 IV-percentage-point move, at the current spot
```

In `build_leaps_gamma_curve`, update both call sites:

```python
    model_delta, gamma, vega = _black_scholes_greeks(
        position.option_type, stock_price, position.strike, years, volatility, risk_free, dividend_yield
    )

    points: list[LeapsGammaPoint] = []
    for index in range(point_count):
        offset_pct = -price_range_pct + 2 * price_range_pct * index / (point_count - 1)
        scenario_price = stock_price * (1 + offset_pct / 100.0)
        scenario_delta, _, _ = _black_scholes_greeks(
            position.option_type, scenario_price, position.strike, years, volatility, risk_free, dividend_yield
        )
        points.append(LeapsGammaPoint(stock_price=scenario_price, delta=scenario_delta))

    return LeapsGammaCurve(
        ticker=position.ticker,
        option_type=position.option_type,
        spot=stock_price,
        model_delta=model_delta,
        gamma=gamma,
        vega=vega,
        implied_volatility_pct=implied_volatility_pct,
        risk_free_rate_pct=risk_free_rate_pct,
        dividend_yield_pct=dividend_yield_pct,
        days_to_expiry=days_to_expiry,
        iv_source=iv_source,
        risk_free_source=risk_free_source,
        dividend_source=dividend_source,
        spot_as_of=spot_as_of,
        points=points,
    )
```

- [ ] **Step 5: Update the two existing direct-call tests in `tests/test_leaps_gamma.py`**

Replace lines 51-58 (`test_gamma_matches_local_delta_change_per_dollar`):

```python
    def test_gamma_matches_local_delta_change_per_dollar(self):
        years = 1.0
        args = ("CALL", 100.0, 100.0, years, 0.30, 0.04, 0.01)
        _, gamma, _ = _black_scholes_greeks(*args)
        delta_up, _, _ = _black_scholes_greeks("CALL", 101.0, *args[2:])
        delta_down, _, _ = _black_scholes_greeks("CALL", 99.0, *args[2:])

        self.assertAlmostEqual(gamma, (delta_up - delta_down) / 2.0, delta=0.00001)
```

And update the import at the top of the file:

```python
from stocktool.analysis import _black_scholes_greeks, build_leaps_gamma_curve, build_leaps_snapshot
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m unittest tests.test_leaps_gamma -v`
Expected: all tests `PASS` (9 existing + 3 new = 12 total).

- [ ] **Step 7: Commit**

```bash
git add stocktool/analysis.py tests/test_leaps_gamma.py
git commit -m "feat: add Black-Scholes vega to the LEAPS gamma curve model"
```

---

### Task 2: Vega dollar-impact + display

**Files:**
- Modify: `stocktool/analysis.py` (new dataclass + function, after `LeapsGammaCurve`/`build_leaps_gamma_curve`, e.g. around line 1461)
- Modify: `stocktool/display.py` (new render function; import list)
- Modify: `stocktool/cli.py:1339-1342` (`leaps_show`), `stocktool/cli.py` (`leaps_update`'s equivalent gamma-chart call site)
- Create: `tests/test_leaps_vega_impact.py`

**Interfaces:**
- Consumes: `analysis.LeapsGammaCurve` (Task 1), `LeapsPosition` (`stocktool/leaps.py`).
- Produces: `analysis.LeapsVegaImpact` dataclass, `analysis.build_leaps_vega_impact(curve: Optional[LeapsGammaCurve], position: LeapsPosition) -> Optional[LeapsVegaImpact]`. `display.render_leaps_vega_section(curve, impact, unavailable_reason) -> None`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_leaps_vega_impact.py`:

```python
import unittest
from datetime import date, timedelta

from stocktool.analysis import build_leaps_gamma_curve, build_leaps_vega_impact
from stocktool.leaps import LeapsPosition


def make_position(entry_iv=None, current_iv=None) -> LeapsPosition:
    return LeapsPosition(
        id="vega001",
        ticker="TEST",
        option_type="CALL",
        strike=100.0,
        expiration=(date.today() + timedelta(days=365)).isoformat(),
        premium=10.0,
        contracts=2,
        entry_stock_price=100.0,
        entry_iv=entry_iv,
        current_iv=current_iv,
    )


def make_curve(position):
    return build_leaps_gamma_curve(
        position, stock_price=100.0, implied_volatility_pct=30.0,
        risk_free_rate_pct=4.0, dividend_yield_pct=1.0,
    )


class VegaImpactTests(unittest.TestCase):
    def test_none_curve_returns_none(self):
        self.assertIsNone(build_leaps_vega_impact(None, make_position()))

    def test_total_vega_scales_by_contracts(self):
        position = make_position(entry_iv=30.0, current_iv=30.0)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertAlmostEqual(impact.vega_total, impact.vega_per_contract * 2)
        self.assertAlmostEqual(impact.impact_plus_10, impact.vega_total * 10)
        self.assertAlmostEqual(impact.impact_minus_20, impact.vega_total * -20)

    def test_zero_iv_change_gives_real_zero_not_none(self):
        # Review Focus #1: entry == current must show a real $0.00, not "N/A".
        position = make_position(entry_iv=30.0, current_iv=30.0)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertEqual(impact.iv_change_pts, 0.0)
        self.assertEqual(impact.vega_pnl_since_entry, 0.0)
        self.assertIsNotNone(impact.vega_pnl_since_entry)

    def test_missing_both_entry_and_current_iv_gives_none_change(self):
        position = make_position(entry_iv=None, current_iv=None)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertIsNotNone(impact)  # vega itself is still computable
        self.assertIsNone(impact.iv_change_pts)
        self.assertIsNone(impact.vega_pnl_since_entry)

    def test_current_iv_falls_back_to_entry_iv_when_unset(self):
        position = make_position(entry_iv=30.0, current_iv=None)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertEqual(impact.current_iv, 30.0)
        self.assertEqual(impact.iv_change_pts, 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_leaps_vega_impact -v`
Expected: `FAIL`/`ImportError` — `build_leaps_vega_impact` doesn't exist yet.

- [ ] **Step 3: Implement `LeapsVegaImpact` + `build_leaps_vega_impact`** — add to `stocktool/analysis.py` right after `build_leaps_gamma_curve`:

```python
@dataclass
class LeapsVegaImpact:
    """Dollar impact of IV moves, derived from a LeapsGammaCurve's current-spot vega."""
    vega_per_contract: float  # $ per contract per 1 IV percentage point
    vega_total: float         # vega_per_contract * contracts
    impact_plus_10: float
    impact_minus_10: float
    impact_minus_20: float
    entry_iv: Optional[float]
    current_iv: Optional[float]
    iv_change_pts: Optional[float]
    vega_pnl_since_entry: Optional[float]


def build_leaps_vega_impact(
    curve: Optional["LeapsGammaCurve"], position: LeapsPosition
) -> Optional[LeapsVegaImpact]:
    """Dollar impact of IV moves, using today's model vega as a constant approximation across
    the whole move since entry (vega itself drifts with price, time, and IV level).

    Returns None only when the gamma curve itself is unavailable — vega_total is still
    computable even with no IV history at all; only the "since entry" fields become None then.
    """
    if curve is None:
        return None
    vega_total = curve.vega * position.contracts
    entry_iv = position.entry_iv
    current_iv = position.current_iv if position.current_iv is not None else entry_iv
    iv_change_pts = None
    vega_pnl_since_entry = None
    if entry_iv is not None and current_iv is not None:
        iv_change_pts = current_iv - entry_iv
        vega_pnl_since_entry = vega_total * iv_change_pts
    return LeapsVegaImpact(
        vega_per_contract=curve.vega,
        vega_total=vega_total,
        impact_plus_10=vega_total * 10,
        impact_minus_10=vega_total * -10,
        impact_minus_20=vega_total * -20,
        entry_iv=entry_iv,
        current_iv=current_iv,
        iv_change_pts=iv_change_pts,
        vega_pnl_since_entry=vega_pnl_since_entry,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_leaps_vega_impact -v`
Expected: all 5 tests `PASS`.

- [ ] **Step 5: Add the display function** — in `stocktool/display.py`, add `LeapsVegaImpact` to the `from .analysis import (...)` block, then add:

```python
def render_leaps_vega_section(
    curve: Optional[LeapsGammaCurve],
    impact: Optional[LeapsVegaImpact],
    unavailable_reason: Optional[str],
) -> None:
    """Vega and its dollar impact — reuses the same model inputs as the gamma/delta chart."""
    if curve is None or impact is None:
        console.print(Panel(
            unavailable_reason or "Vega unavailable; missing model inputs.",
            title="[bold magenta]Vega Analysis[/bold magenta]",
            border_style="magenta",
        ))
        return
    lines = [
        f"Current vega: ${impact.vega_per_contract:,.2f} per contract per 1pt IV move "
        f"(${impact.vega_total:,.2f} total for this position)",
        f"  Impact of +10 IV points: [green]+${impact.impact_plus_10:,.2f}[/green]",
        f"  Impact of -10 IV points: [red]{impact.impact_minus_10:,.2f}[/red]  (pre-earnings-crush scenario)",
        f"  Impact of -20 IV points: [red]{impact.impact_minus_20:,.2f}[/red]  (panic-crush scenario)",
        "",
    ]
    if impact.entry_iv is not None:
        lines.append(f"Entry IV: {impact.entry_iv:.1f}%")
    if impact.current_iv is not None:
        lines.append(f"Current IV: {impact.current_iv:.1f}%")
    if impact.iv_change_pts is not None:
        arrow = "↑" if impact.iv_change_pts > 0 else ("↓" if impact.iv_change_pts < 0 else "→")
        pnl_color = "green" if impact.vega_pnl_since_entry >= 0 else "red"
        lines.append(f"IV change since entry: {arrow} {impact.iv_change_pts:+.1f}pts")
        lines.append(
            f"Vega P&L contribution since entry: [{pnl_color}]~${impact.vega_pnl_since_entry:+,.2f}[/{pnl_color}]"
        )
    else:
        lines.append("IV change since entry: N/A — needs both an entry IV and a current/fallback IV")
    lines.append(
        "[dim]Uses today's vega as a constant approximation across the whole move since entry — "
        "vega itself drifts with price, time, and IV level.[/dim]"
    )
    console.print(Panel(
        "\n".join(lines),
        title="[bold magenta]Vega Analysis[/bold magenta]",
        border_style="magenta",
    ))
```

- [ ] **Step 6: Wire into `leaps_show` and `leaps_update`** — in `stocktool/cli.py`, right after each existing call to `display.render_leaps_gamma_chart(gamma_curve, broker_delta, broker_delta_label, gamma_unavailable)` (one in `leaps_show` around line 1342, one in `leaps_update` near its own gamma-chart call), add:

```python
    vega_impact = analysis.build_leaps_vega_impact(gamma_curve, position)
    display.render_leaps_vega_section(gamma_curve, vega_impact, gamma_unavailable)
```

- [ ] **Step 7: Manual sanity check**

Run: `python -m stocktool.cli leaps show AMZN` (or whichever ticker has an active LEAPS position in the local `leaps.json`)
Expected: a new "Vega Analysis" panel appears right after the gamma/delta chart, with no traceback.

- [ ] **Step 8: Commit**

```bash
git add stocktool/analysis.py stocktool/display.py stocktool/cli.py tests/test_leaps_vega_impact.py
git commit -m "feat: show vega and its dollar IV-impact on LEAPS positions"
```

---

### Task 3: IV Rank computation

**Files:**
- Modify: `stocktool/config.py` (new constants, after `LEAPS_DECAY_ACCELERATION_FRACTION`)
- Modify: `stocktool/analysis.py` (new dataclass + function near `leaps_iv_value_verdict`, around line 1607; new `LeapsSnapshot` fields around line 1507; wire into `build_leaps_snapshot` around line 1733)
- Create: `tests/test_leaps_iv_rank.py`

**Interfaces:**
- Consumes: `IvReading` (`stocktool/leaps.py`, has `.iv: float`, `.date: str`).
- Produces: `analysis.LeapsIvRank` dataclass, `analysis.leaps_iv_rank(current_iv: Optional[float], iv_history: list[IvReading]) -> Optional[LeapsIvRank]`. New `LeapsSnapshot` fields: `iv_rank_pct`, `iv_rank_label`, `iv_rank_color`, `iv_range_low`, `iv_range_high`, `iv_rank_reading_count`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_leaps_iv_rank.py`:

```python
import unittest

from stocktool.analysis import leaps_iv_rank
from stocktool.leaps import IvReading


def readings(*values: float) -> list[IvReading]:
    return [IvReading(date=f"2026-01-{i+1:02d}", iv=v, source="yahoo") for i, v in enumerate(values)]


class LeapsIvRankTests(unittest.TestCase):
    def test_below_minimum_readings_returns_none(self):
        # Review Focus #2: 4 readings must be None, 5 must compute — exact boundary.
        self.assertIsNone(leaps_iv_rank(40.0, readings(30, 32, 34, 36)))

    def test_exactly_minimum_readings_computes_a_rank(self):
        result = leaps_iv_rank(40.0, readings(20, 25, 30, 35, 40))

        self.assertIsNotNone(result)
        self.assertEqual(result.reading_count, 5)
        self.assertEqual(result.range_low, 20.0)
        self.assertEqual(result.range_high, 40.0)
        self.assertAlmostEqual(result.rank_pct, 100.0)

    def test_flat_history_ranks_at_fifty(self):
        result = leaps_iv_rank(30.0, readings(30, 30, 30, 30, 30))

        self.assertAlmostEqual(result.rank_pct, 50.0)

    def test_label_and_color_boundaries(self):
        cases = [
            (29.9, "CHEAP", "green"),
            (30.0, "CHEAP", "green"),
            (30.1, "NORMAL", "yellow"),
            (60.0, "NORMAL", "yellow"),
            (60.1, "ELEVATED", "orange3"),
            (80.0, "ELEVATED", "orange3"),
            (80.1, "EXPENSIVE", "red"),
        ]
        history = readings(0, 100, 50, 10, 90)  # range 0-100 so current_iv == rank_pct directly
        for current_iv, expected_label, expected_color in cases:
            with self.subTest(current_iv=current_iv):
                result = leaps_iv_rank(current_iv, history)
                self.assertEqual(result.label, expected_label)
                self.assertEqual(result.color, expected_color)

    def test_none_current_iv_returns_none(self):
        self.assertIsNone(leaps_iv_rank(None, readings(20, 25, 30, 35, 40)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_leaps_iv_rank -v`
Expected: `FAIL`/`ImportError` — `leaps_iv_rank` doesn't exist yet.

- [ ] **Step 3: Add config constants** — in `stocktool/config.py`, right after `LEAPS_IV_EXPENSIVE_RATIO = 1.15`:

```python
# IV Rank: percentile of current IV against this position's own tracked iv_history (not a
# true 52-week range — yfinance has no historical-IV series, so this is only what the tool
# has actually recorded since the user started tracking this position).
LEAPS_IV_RANK_MIN_READINGS = 5
LEAPS_IV_RANK_CHEAP_MAX = 30
LEAPS_IV_RANK_NORMAL_MAX = 60
LEAPS_IV_RANK_ELEVATED_MAX = 80
```

- [ ] **Step 4: Implement `LeapsIvRank` + `leaps_iv_rank`** — in `stocktool/analysis.py`, add right after `leaps_iv_value_verdict`:

```python
@dataclass
class LeapsIvRank:
    rank_pct: float
    label: str
    color: str
    range_low: float
    range_high: float
    reading_count: int


def leaps_iv_rank(current_iv: Optional[float], iv_history: list) -> Optional[LeapsIvRank]:
    """IV percentile against this position's own accumulated history. Boundaries are
    inclusive on the lower bucket (exactly 30.0 is CHEAP, exactly 60.0 is NORMAL, etc.)."""
    from .config import (
        LEAPS_IV_RANK_MIN_READINGS, LEAPS_IV_RANK_CHEAP_MAX,
        LEAPS_IV_RANK_NORMAL_MAX, LEAPS_IV_RANK_ELEVATED_MAX,
    )
    if current_iv is None or len(iv_history) < LEAPS_IV_RANK_MIN_READINGS:
        return None
    values = [r.iv for r in iv_history]
    low, high = min(values), max(values)
    rank_pct = 50.0 if high == low else max(0.0, min(100.0, (current_iv - low) / (high - low) * 100))
    if rank_pct <= LEAPS_IV_RANK_CHEAP_MAX:
        label, color = "CHEAP", "green"
    elif rank_pct <= LEAPS_IV_RANK_NORMAL_MAX:
        label, color = "NORMAL", "yellow"
    elif rank_pct <= LEAPS_IV_RANK_ELEVATED_MAX:
        label, color = "ELEVATED", "orange3"
    else:
        label, color = "EXPENSIVE", "red"
    return LeapsIvRank(
        rank_pct=rank_pct, label=label, color=color,
        range_low=low, range_high=high, reading_count=len(iv_history),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest tests.test_leaps_iv_rank -v`
Expected: all 5 tests `PASS`.

- [ ] **Step 6: Add fields to `LeapsSnapshot` and wire into `build_leaps_snapshot`**

In `LeapsSnapshot` (around line 1507), right after the existing `iv_value_color: str = "dim"` field:

```python
    iv_rank_pct: Optional[float] = None
    iv_rank_label: Optional[str] = None
    iv_rank_color: str = "dim"
    iv_range_low: Optional[float] = None
    iv_range_high: Optional[float] = None
    iv_rank_reading_count: int = 0
```

In `build_leaps_snapshot` (around line 1733), where `iv_value_label, iv_value_color, iv_value_ratio = leaps_iv_value_verdict(latest_iv, realized_vol)` already sits inside `if is_active:`, add directly below it:

```python
        iv_rank = leaps_iv_rank(latest_iv, position.iv_history)
```

And in the final `return LeapsSnapshot(...)` call, add after the existing `iv_value_color=iv_value_color,` line:

```python
        iv_rank_pct=iv_rank.rank_pct if iv_rank else None,
        iv_rank_label=iv_rank.label if iv_rank else None,
        iv_rank_color=iv_rank.color if iv_rank else "dim",
        iv_range_low=iv_rank.range_low if iv_rank else None,
        iv_range_high=iv_rank.range_high if iv_rank else None,
        iv_rank_reading_count=len(position.iv_history),
```

(`iv_rank` is `None` outside the `if is_active:` block too, since it's only assigned there — add `iv_rank = None` as the initializer alongside the existing `iv_value_label, iv_value_color, iv_value_ratio = None, "dim", None` line above that `if is_active:` block, matching the existing pattern.)

- [ ] **Step 7: Run the full existing LEAPS test suite to check for regressions**

Run: `python -m unittest tests.test_leaps_gamma tests.test_leaps_vega_impact tests.test_leaps_iv_rank -v`
Expected: all tests `PASS`.

- [ ] **Step 8: Commit**

```bash
git add stocktool/config.py stocktool/analysis.py tests/test_leaps_iv_rank.py
git commit -m "feat: compute IV Rank from a LEAPS position's own tracked IV history"
```

---

### Task 4: Daily auto-capture + IV Rank display + entry-day mismatch flag

**Files:**
- Modify: `stocktool/leaps.py` (new method on `LeapsPosition`, after the dataclass definition around line 52)
- Modify: `stocktool/cli.py:1303-1342` (`leaps_show`), `stocktool/cli.py:1439-1446` (`leaps_update`)
- Modify: `stocktool/display.py` (`_leaps_current_iv_line`/`render_leaps_detail`, `_leaps_iv_history_lines`)
- Create: `tests/test_leaps_model.py`

**Interfaces:**
- Produces: `LeapsPosition.record_iv_reading(iv: float, today: date, source: str) -> bool` (returns `True` if a new reading was appended, `False` if today's date was already recorded — dedup, and testable without mocking the clock since `today` is a parameter). `cli._should_capture_iv_reading(position_status: str, market_iv: Optional[float]) -> bool` (the guard deciding whether `leaps show` attempts a capture at all).

- [ ] **Step 1: Write the failing test** — create `tests/test_leaps_model.py`:

```python
import unittest
from datetime import date

from stocktool.leaps import LeapsPosition


def make_position() -> LeapsPosition:
    return LeapsPosition(
        id="model001", ticker="TEST", option_type="CALL", strike=100.0,
        expiration="2028-01-01", premium=10.0,
    )


class RecordIvReadingTests(unittest.TestCase):
    def test_first_reading_appends_and_returns_true(self):
        position = make_position()
        appended = position.record_iv_reading(30.0, date(2026, 1, 1), "yahoo")

        self.assertTrue(appended)
        self.assertEqual(len(position.iv_history), 1)
        self.assertEqual(position.iv_history[0].iv, 30.0)
        self.assertEqual(position.iv_history[0].date, "2026-01-01")

    def test_same_day_second_call_is_deduped(self):
        # Review Focus #3 support: repeated same-day calls must not flood the history.
        position = make_position()
        position.record_iv_reading(30.0, date(2026, 1, 1), "yahoo")
        appended_again = position.record_iv_reading(31.0, date(2026, 1, 1), "yahoo")

        self.assertFalse(appended_again)
        self.assertEqual(len(position.iv_history), 1)
        self.assertEqual(position.iv_history[0].iv, 30.0)  # first reading wins, not overwritten

    def test_next_day_appends_a_second_reading(self):
        position = make_position()
        position.record_iv_reading(30.0, date(2026, 1, 1), "yahoo")
        appended = position.record_iv_reading(31.0, date(2026, 1, 2), "manual")

        self.assertTrue(appended)
        self.assertEqual(len(position.iv_history), 2)
        self.assertEqual(position.iv_history[1].source, "manual")


class ShouldCaptureIvReadingTests(unittest.TestCase):
    """Review Focus #3: the leaps_show capture guard must not fire for CLOSED positions or
    when no market IV was fetched this run."""

    def test_active_with_market_iv_captures(self):
        from stocktool.cli import _should_capture_iv_reading

        self.assertTrue(_should_capture_iv_reading("ACTIVE", 30.0))

    def test_closed_position_never_captures(self):
        from stocktool.cli import _should_capture_iv_reading

        self.assertFalse(_should_capture_iv_reading("CLOSED", 30.0))

    def test_no_market_iv_never_captures(self):
        from stocktool.cli import _should_capture_iv_reading

        self.assertFalse(_should_capture_iv_reading("ACTIVE", None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_leaps_model -v`
Expected: `FAIL`/`AttributeError` — `record_iv_reading` doesn't exist yet.

- [ ] **Step 3: Implement `record_iv_reading`** — in `stocktool/leaps.py`, add to the `LeapsPosition` dataclass body (as a method, after the field declarations, before the class ends):

```python
    def record_iv_reading(self, iv: float, today: date, source: str) -> bool:
        """Append one IV reading for `today`, deduped by calendar day — returns False (no-op)
        if today's reading is already recorded, so repeated `leaps show` runs in one day don't
        flood the history. `today` is a parameter (not `date.today()` internally) so this is
        testable without faking the clock.
        """
        today_iso = today.isoformat()
        if self.iv_history and self.iv_history[-1].date == today_iso:
            return False
        self.iv_history.append(IvReading(date=today_iso, iv=iv, source=source))
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_leaps_model -v`
Expected: all 3 tests `PASS`.

- [ ] **Step 4b: Add the capture guard to `cli.py` and run its tests**

In `stocktool/cli.py`, add a small module-level helper near `_get_leaps_option_quote` (around line 948):

```python
def _should_capture_iv_reading(position_status: str, market_iv: Optional[float]) -> bool:
    """Guard for leaps_show's new auto-capture: only for ACTIVE positions, and only when a
    market IV reading actually came back this run."""
    return position_status == "ACTIVE" and market_iv is not None
```

(`Optional` is already imported in `cli.py` — if not, add `from typing import Optional` near the top of the file.)

Run: `python -m unittest tests.test_leaps_model -v`
Expected: all 6 tests `PASS` (3 from Step 4 + 3 new guard tests).

- [ ] **Step 5: Use `record_iv_reading` in `leaps_update`** — in `stocktool/cli.py`, replace the existing block (around line 1443-1445):

```python
    if current_iv is not None:
        source = "yahoo" if market_iv is not None and abs(current_iv - market_iv) < 0.05 else "manual"
        position.iv_history.append(IvReading(date=position.last_updated, iv=current_iv, source=source))
```

with:

```python
    if current_iv is not None:
        source = "yahoo" if market_iv is not None and abs(current_iv - market_iv) < 0.05 else "manual"
        position.record_iv_reading(current_iv, date.today(), source)
```

(The `IvReading` import in this function becomes unused — remove it from the `from .leaps import load_leaps, save_leaps, IvReading` line, leaving `from .leaps import load_leaps, save_leaps`.)

- [ ] **Step 6: Add the same capture to `leaps_show`, reordered so IV Rank reflects today's reading**

Replace the body of `leaps_show` (`stocktool/cli.py:1303-1326`, from `def leaps_show` through the `market_iv = option_context.get("implied_volatility")`-equivalent line) with:

```python
def leaps_show(
    identifier: str = typer.Argument(..., help="LEAPS position id or ticker symbol."),
) -> None:
    """Detail view for a single LEAPS position."""
    from datetime import date

    from . import data, analysis, display
    from .leaps import load_leaps, save_leaps

    book = load_leaps()
    position = _resolve_leaps_position(book, identifier)
    if position is None:
        console.print(f"[red]No LEAPS position found for id or ticker '{identifier}'.[/red]")
        raise typer.Exit(1)

    current_price = data.get_current_prices([position.ticker]).get(position.ticker) if position.status == "ACTIVE" else None
    portfolio_value = _leaps_portfolio_value()
    option_quote = _get_leaps_option_quote(position)
    realized_vol = data.fetch_realized_volatility(position.ticker) if position.status == "ACTIVE" else None

    market_iv = option_quote.get("implied_volatility")
    if _should_capture_iv_reading(position.status, market_iv):
        if position.record_iv_reading(market_iv, date.today(), "yahoo"):
            save_leaps(book)

    snapshot = analysis.build_leaps_snapshot(position, current_price, portfolio_value, option_quote, realized_vol)
    display.render_leaps_detail(position, snapshot)

    if position.status == "CLOSED":
        return

    if market_iv is not None:
        gamma_iv = market_iv
        gamma_iv_source = f"Yahoo option chain IV (retrieved {option_quote.get('retrieved_at', 'time unavailable')})"
    elif position.current_iv is not None:
        gamma_iv = position.current_iv
        if position.iv_history:
            last_iv = position.iv_history[-1]
            gamma_iv_source = f"saved {last_iv.source} IV from {last_iv.date}"
        else:
            gamma_iv_source = "saved current IV"
    else:
        gamma_iv, gamma_iv_source = None, "unavailable"
```

Everything from `gamma_curve, broker_delta, broker_delta_label, gamma_unavailable = _leaps_gamma_view(...)`
through the end of the function is **unchanged — do not delete or retype it**, including the
`display.render_leaps_gamma_chart(...)` call and (once Task 2 has run) the vega-section lines right
after it. This step only replaces the *opening* portion of `leaps_show` shown above: it moves the
`market_iv` lookup and the new capture call earlier in the function, and removes the one now-redundant
duplicate line `market_iv = option_quote.get("implied_volatility")` that used to appear again after the
`CLOSED` check — everything after that point in the original function stays exactly as it is.

- [ ] **Step 7: Add the IV Rank line to the detail panel** — in `stocktool/display.py`, add a helper right after `_leaps_current_iv_line`:

```python
def _leaps_iv_rank_line(snapshot: LeapsSnapshot) -> str:
    """IV Rank against this position's own tracked history (not a true 52-week range)."""
    if snapshot.iv_rank_label is None:
        return (
            f"  IV Rank: not enough history yet ({snapshot.iv_rank_reading_count} reading(s) so far) "
            "— keep running `leaps show`/`leaps update` to build this up"
        )
    return (
        f"  IV Rank: [{snapshot.iv_rank_color}]{snapshot.iv_rank_pct:.0f}th percentile — "
        f"{snapshot.iv_rank_label}[/{snapshot.iv_rank_color}] "
        f"(range {snapshot.iv_range_low:.1f}%-{snapshot.iv_range_high:.1f}% over "
        f"{snapshot.iv_rank_reading_count} tracked readings)"
    )
```

In `render_leaps_detail`'s `lines` list, right after the existing `_leaps_current_iv_line(position, snapshot),` entry, add:

```python
        _leaps_iv_rank_line(snapshot),
```

- [ ] **Step 8: Add the entry-day mismatch flag** — in `stocktool/display.py`'s `_leaps_iv_history_lines`, right before the existing `if len(position.iv_history) >= 2:` trend block, add:

```python
    entry_day_reading = next((r for r in position.iv_history if r.date == position.entry_date), None)
    if (
        entry_day_reading is not None
        and position.entry_iv is not None
        and abs(position.entry_iv - entry_day_reading.iv) > 5
    ):
        lines.append(
            f"  [yellow]⚠ Entry-day IV mismatch: manually entered {position.entry_iv:.1f}% vs. "
            f"Yahoo chain {entry_day_reading.iv:.1f}% that day.[/yellow]"
        )
```

- [ ] **Step 9: Manual sanity check**

Run: `python -m stocktool.cli leaps show AMZN` twice in a row.
Expected: no traceback either time; `iv_history` in `~/.config/stocktool/leaps.json` gains at most one new entry across both runs (same calendar day — dedup working); an "IV Rank" line appears under "Current IV" (likely "not enough history yet" unless 5+ readings already exist).

- [ ] **Step 10: Commit**

```bash
git add stocktool/leaps.py stocktool/cli.py stocktool/display.py tests/test_leaps_model.py
git commit -m "feat: auto-capture daily IV readings in leaps show, surface IV Rank and entry-day mismatch flag"
```

---

### Task 5: Earnings move history — data fetch

**Files:**
- Modify: `stocktool/data.py:888-906` (extract `fetch_next_earnings_date` out of `fetch_leaps_option_context`), add new `fetch_earnings_move_history`
- Modify: `stocktool/config.py` (new constant)
- Create: `tests/test_leaps_earnings.py`

**Interfaces:**
- Produces: `data.fetch_next_earnings_date(ticker: str) -> dict` (keys: `"earnings_date"`, `"days_to_earnings"`, or `{}`). `data.fetch_earnings_move_history(ticker: str, quarters: int = 8) -> list[dict]` (each dict: `"date"`, `"pct_move"`, `"abs_pct_move"`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_leaps_earnings.py`:

```python
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

import pandas as pd

from stocktool.data import fetch_earnings_move_history, fetch_next_earnings_date


class FetchEarningsMoveHistoryTests(unittest.TestCase):
    def test_computes_pct_move_around_each_earnings_date(self):
        today = date.today()
        earnings_date = today - timedelta(days=100)
        earnings_df = pd.DataFrame(
            {"EPS Estimate": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp(earnings_date)])
        )
        trading_days = pd.bdate_range(end=pd.Timestamp(today), periods=400)
        closes = pd.Series(100.0, index=trading_days)
        before_idx = trading_days.searchsorted(pd.Timestamp(earnings_date)) - 1
        closes.iloc[before_idx] = 100.0
        closes.iloc[before_idx + 1] = 110.0
        hist_df = pd.DataFrame({"Close": closes})

        ticker = Mock()
        ticker.get_earnings_dates.return_value = earnings_df
        ticker.history.return_value = hist_df

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            moves = fetch_earnings_move_history("TEST", quarters=8)

        self.assertEqual(len(moves), 1)
        self.assertAlmostEqual(moves[0]["pct_move"], 10.0, places=4)
        self.assertAlmostEqual(moves[0]["abs_pct_move"], 10.0, places=4)

    def test_never_raises_on_fetch_failure(self):
        # Review Focus #5.
        with patch("stocktool.data.yf.Ticker", side_effect=RuntimeError("network down")):
            moves = fetch_earnings_move_history("TEST")

        self.assertEqual(moves, [])

    def test_empty_earnings_dates_returns_empty_list(self):
        # Review Focus #5.
        ticker = Mock()
        ticker.get_earnings_dates.return_value = pd.DataFrame()
        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            moves = fetch_earnings_move_history("TEST")

        self.assertEqual(moves, [])

    def test_too_short_price_history_returns_empty_list(self):
        # Review Focus #5.
        today = date.today()
        earnings_df = pd.DataFrame(
            {"EPS Estimate": [1.0]},
            index=pd.DatetimeIndex([pd.Timestamp(today - timedelta(days=5))]),
        )
        ticker = Mock()
        ticker.get_earnings_dates.return_value = earnings_df
        ticker.history.return_value = pd.DataFrame({"Close": []})
        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            moves = fetch_earnings_move_history("TEST")

        self.assertEqual(moves, [])


class FetchNextEarningsDateTests(unittest.TestCase):
    def test_future_earnings_date_from_get_earnings_dates(self):
        future_date = date.today() + timedelta(days=15)
        edf = pd.DataFrame({"EPS Estimate": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp(future_date)]))
        ticker = Mock()
        ticker.calendar = {}
        ticker.get_earnings_dates.return_value = edf

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            result = fetch_next_earnings_date("TEST")

        self.assertEqual(result["earnings_date"], future_date.isoformat())
        self.assertEqual(result["days_to_earnings"], 15)

    def test_never_raises_on_fetch_failure(self):
        with patch("stocktool.data.yf.Ticker", side_effect=RuntimeError("network down")):
            result = fetch_next_earnings_date("TEST")

        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_leaps_earnings -v`
Expected: `FAIL`/`ImportError` — neither function exists yet.

- [ ] **Step 3: Add `LEAPS_EARNINGS_HISTORY_QUARTERS` constant** — in `stocktool/config.py`, after the IV Rank constants from Task 3:

```python
LEAPS_EARNINGS_HISTORY_QUARTERS = 8
```

Also add this constant to `stocktool/data.py`'s existing module-level config import (line 9): change
`from .config import MARGIN_STATE_FILE, ensure_config_dir` to
`from .config import MARGIN_STATE_FILE, LEAPS_EARNINGS_HISTORY_QUARTERS, ensure_config_dir`
— so `fetch_earnings_move_history`'s default below has exactly one source of truth instead of a
second hardcoded `8`.

- [ ] **Step 4: Extract `fetch_next_earnings_date`** — in `stocktool/data.py`, replace the inline "Next earnings date." block inside `fetch_leaps_option_context` (lines 888-906) with a call to a new standalone function. First add the new function right before `fetch_leaps_option_context`:

```python
def fetch_next_earnings_date(ticker: str) -> dict:
    """Best-effort next earnings date lookup — standalone so `leaps show`/`leaps update` can
    use it too, not just `leaps add`'s fetch_leaps_option_context`. Never raises.

    Returns a dict with "earnings_date" (ISO) and "days_to_earnings" (int) when found, {}
    otherwise.
    """
    from datetime import date, datetime

    result: dict = {}
    try:
        t = yf.Ticker(ticker)
        earnings_date = None
        cal = t.calendar
        if isinstance(cal, dict) and cal.get("Earnings Date"):
            earnings_date = cal["Earnings Date"][0]
        if earnings_date is None:
            edf = t.get_earnings_dates(limit=4)
            if edf is not None and not edf.empty:
                future = edf[edf.index.date >= date.today()]
                if not future.empty:
                    earnings_date = future.index[-1].date()
        if earnings_date is not None:
            if isinstance(earnings_date, datetime):
                earnings_date = earnings_date.date()
            result["earnings_date"] = earnings_date.isoformat()
            result["days_to_earnings"] = (earnings_date - date.today()).days
    except Exception:
        pass
    return result
```

Then replace the old inline block inside `fetch_leaps_option_context` with:

```python
    # Next earnings date.
    result.update(fetch_next_earnings_date(ticker))
```

- [ ] **Step 5: Implement `fetch_earnings_move_history`** — add right after `fetch_next_earnings_date`:

```python
def fetch_earnings_move_history(ticker: str, quarters: int = LEAPS_EARNINGS_HISTORY_QUARTERS) -> list[dict]:
    """Best-effort historical price move bracketing each of the last `quarters` earnings
    reports: the close on the last trading day strictly before the earnings date, versus the
    close on the first trading day on/after it (this is the closest honest bracket available —
    yfinance's earnings-date timestamps don't reliably say before-market vs. after-market).

    Returns a list of {"date": iso, "pct_move": signed %, "abs_pct_move": %}, newest last.
    Never raises — returns [] on any failure (missing data, network error, too-short history).
    """
    try:
        t = yf.Ticker(ticker)
        edf = t.get_earnings_dates(limit=quarters + 4)
        if edf is None or edf.empty:
            return []
        past_dates = sorted(d.date() for d in edf.index if d.date() < date.today())
        past_dates = past_dates[-quarters:]
        if not past_dates:
            return []

        hist = t.history(period="3y")
        if hist.empty or "Close" not in hist:
            return []
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return []
        trading_days = [ts.date() for ts in closes.index]

        results = []
        for earnings_date in past_dates:
            prior_idx = None
            for i, d in enumerate(trading_days):
                if d < earnings_date:
                    prior_idx = i
                else:
                    break
            if prior_idx is None or prior_idx + 1 >= len(trading_days):
                continue
            prior_close = float(closes.iloc[prior_idx])
            next_close = float(closes.iloc[prior_idx + 1])
            if prior_close <= 0:
                continue
            pct_move = (next_close - prior_close) / prior_close * 100
            results.append({
                "date": earnings_date.isoformat(),
                "pct_move": pct_move,
                "abs_pct_move": abs(pct_move),
            })
        return results
    except Exception:
        return []
```

Add `from datetime import date` to this function's imports if not already module-level in `data.py` (check the top of the file — if `date` isn't imported at module scope, add `from datetime import date` as a local import inside this function, matching the style already used by `fetch_leaps_option_context`, which does `from datetime import date, datetime` locally).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m unittest tests.test_leaps_earnings -v`
Expected: all 6 tests `PASS`.

- [ ] **Step 7: Run the existing gamma test suite to confirm the `fetch_leaps_option_context` refactor didn't break it**

Run: `python -m unittest tests.test_leaps_gamma -v`
Expected: all tests still `PASS` (this suite doesn't call `fetch_leaps_option_context` directly, but confirms no import-time breakage in `data.py`).

- [ ] **Step 8: Commit**

```bash
git add stocktool/data.py stocktool/config.py tests/test_leaps_earnings.py
git commit -m "feat: fetch historical earnings-move data for LEAPS positions"
```

---

### Task 6: Earnings move stats + projection + display

**Files:**
- Modify: `stocktool/analysis.py` (new dataclasses + functions, near the other LEAPS helpers)
- Modify: `stocktool/display.py` (new render function)
- Modify: `stocktool/cli.py` (`leaps_show`, `leaps_update`)
- Modify: `tests/test_leaps_earnings.py` (add stats tests)

**Interfaces:**
- Consumes: `data.fetch_earnings_move_history` output (Task 5), `LeapsSnapshot.current_delta`/`entry_delta` (existing).
- Produces: `analysis.LeapsEarningsStats`, `analysis.leaps_earnings_move_stats(moves: list[dict]) -> Optional[LeapsEarningsStats]`. `analysis.LeapsEarningsContext`, `analysis.build_leaps_earnings_context(position, current_price, effective_delta, next_earnings_date, days_to_earnings, moves) -> Optional[LeapsEarningsContext]`. `display.render_leaps_earnings_context(context) -> None`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_leaps_earnings.py`:

```python
from stocktool.analysis import build_leaps_earnings_context, leaps_earnings_move_stats
from stocktool.leaps import LeapsPosition


class LeapsEarningsMoveStatsTests(unittest.TestCase):
    def test_computes_avg_and_max_abs_move(self):
        moves = [
            {"date": "2026-01-01", "pct_move": 5.0, "abs_pct_move": 5.0},
            {"date": "2026-04-01", "pct_move": -9.0, "abs_pct_move": 9.0},
        ]
        stats = leaps_earnings_move_stats(moves)

        self.assertAlmostEqual(stats.avg_abs_move_pct, 7.0)
        self.assertAlmostEqual(stats.max_abs_move_pct, 9.0)
        self.assertEqual(stats.quarters_used, 2)

    def test_empty_moves_returns_none(self):
        self.assertIsNone(leaps_earnings_move_stats([]))


class BuildLeapsEarningsContextTests(unittest.TestCase):
    def make_position(self) -> LeapsPosition:
        return LeapsPosition(
            id="earn001", ticker="TEST", option_type="CALL", strike=100.0,
            expiration="2028-01-01", premium=10.0, contracts=2,
        )

    def test_none_when_no_date_and_no_moves(self):
        context = build_leaps_earnings_context(self.make_position(), 100.0, 0.8, None, None, [])

        self.assertIsNone(context)

    def test_computes_delta_only_impact_with_moves_and_delta(self):
        moves = [{"date": "2026-01-01", "pct_move": 10.0, "abs_pct_move": 10.0}]
        context = build_leaps_earnings_context(
            self.make_position(), current_price=100.0, effective_delta=0.8,
            next_earnings_date="2026-12-01", days_to_earnings=20, moves=moves,
        )

        self.assertEqual(context.avg_abs_move_pct, 10.0)
        # delta_impact = 0.8 * 100 * 2 contracts * (100 * 10 / 100) = 1600.0
        self.assertAlmostEqual(context.delta_impact_avg, 1600.0)

    def test_date_only_with_no_moves_still_returns_context(self):
        context = build_leaps_earnings_context(self.make_position(), 100.0, 0.8, "2026-12-01", 20, [])

        self.assertIsNotNone(context)
        self.assertIsNone(context.avg_abs_move_pct)
        self.assertEqual(context.quarters_used, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_leaps_earnings -v`
Expected: the 5 new tests `FAIL`/`ImportError`.

- [ ] **Step 3: Implement the stats and context functions** — add to `stocktool/analysis.py`:

```python
@dataclass
class LeapsEarningsStats:
    avg_abs_move_pct: float
    max_abs_move_pct: float
    quarters_used: int


def leaps_earnings_move_stats(moves: list[dict]) -> Optional[LeapsEarningsStats]:
    """Summary stats over fetch_earnings_move_history()'s per-quarter moves. None if empty."""
    if not moves:
        return None
    abs_moves = [m["abs_pct_move"] for m in moves]
    return LeapsEarningsStats(
        avg_abs_move_pct=sum(abs_moves) / len(abs_moves),
        max_abs_move_pct=max(abs_moves),
        quarters_used=len(moves),
    )


@dataclass
class LeapsEarningsContext:
    ticker: str
    next_earnings_date: Optional[str]
    days_to_earnings: Optional[int]
    avg_abs_move_pct: Optional[float]
    max_abs_move_pct: Optional[float]
    quarters_used: int
    delta_impact_avg: Optional[float]  # dollar impact if the stock moves UP by avg_abs_move_pct;
    delta_impact_max: Optional[float]  # negate for the down-move scenario (delta-only, symmetric)


def build_leaps_earnings_context(
    position: LeapsPosition,
    current_price: Optional[float],
    effective_delta: Optional[float],
    next_earnings_date: Optional[str],
    days_to_earnings: Optional[int],
    moves: list[dict],
) -> Optional[LeapsEarningsContext]:
    """Combines historical earnings-move stats with this position's effective delta for a
    delta-only projection (no IV-crush estimate — see spec Non-goals). None only when there's
    neither an earnings date nor any move history to show.
    """
    stats = leaps_earnings_move_stats(moves)
    if next_earnings_date is None and stats is None:
        return None
    delta_impact_avg = None
    delta_impact_max = None
    if stats is not None and effective_delta is not None and current_price is not None:
        delta_impact_avg = effective_delta * 100 * position.contracts * (current_price * stats.avg_abs_move_pct / 100)
        delta_impact_max = effective_delta * 100 * position.contracts * (current_price * stats.max_abs_move_pct / 100)
    return LeapsEarningsContext(
        ticker=position.ticker,
        next_earnings_date=next_earnings_date,
        days_to_earnings=days_to_earnings,
        avg_abs_move_pct=stats.avg_abs_move_pct if stats else None,
        max_abs_move_pct=stats.max_abs_move_pct if stats else None,
        quarters_used=stats.quarters_used if stats else 0,
        delta_impact_avg=delta_impact_avg,
        delta_impact_max=delta_impact_max,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_leaps_earnings -v`
Expected: all 11 tests in this file `PASS` (6 from Task 5 + 5 new).

- [ ] **Step 5: Add the display function** — in `stocktool/display.py`, add `LeapsEarningsContext` to the analysis import block, then add:

```python
def render_leaps_earnings_context(context: Optional[LeapsEarningsContext]) -> None:
    if context is None:
        console.print(Panel(
            "No earnings date or move history available for this ticker.",
            title="[bold magenta]Earnings Context[/bold magenta]",
            border_style="magenta",
        ))
        return
    lines = []
    if context.next_earnings_date is not None:
        lines.append(f"Next earnings: {context.next_earnings_date} ({context.days_to_earnings} days away)")
    else:
        lines.append("Next earnings: unavailable")
    if context.avg_abs_move_pct is not None:
        lines.append(
            f"Historical post-earnings move: avg ±{context.avg_abs_move_pct:.1f}% over last "
            f"{context.quarters_used} quarters · max ±{context.max_abs_move_pct:.1f}%"
        )
        if context.delta_impact_avg is not None:
            lines.append(
                f"Delta-only projection — avg move: up → {context.delta_impact_avg:+,.0f}, "
                f"down → {-context.delta_impact_avg:+,.0f}"
            )
        if context.delta_impact_max is not None:
            lines.append(
                f"Delta-only projection — max historical move: up → {context.delta_impact_max:+,.0f}, "
                f"down → {-context.delta_impact_max:+,.0f}"
            )
        lines.append(
            "[dim]Delta-only estimate — earnings often also moves IV sharply (usually down after "
            "the report), and this tool has no reliable estimate of that IV change.[/dim]"
        )
    else:
        lines.append(f"[dim]No earnings-move history available ({context.quarters_used} quarters found).[/dim]")
    console.print(Panel(
        "\n".join(lines),
        title="[bold magenta]Earnings Context[/bold magenta]",
        border_style="magenta",
    ))
```

- [ ] **Step 6: Wire into `leaps_show` and `leaps_update`** — in `stocktool/cli.py`, right after the vega-section call added in Task 2 (in both commands), add:

```python
    earnings_info = data.fetch_next_earnings_date(position.ticker) if position.status == "ACTIVE" else {}
    earnings_moves = data.fetch_earnings_move_history(position.ticker) if position.status == "ACTIVE" else []
    effective_delta = snapshot.current_delta if snapshot.current_delta is not None else snapshot.entry_delta
    earnings_context = analysis.build_leaps_earnings_context(
        position, current_price, effective_delta,
        earnings_info.get("earnings_date"), earnings_info.get("days_to_earnings"),
        earnings_moves,
    )
    display.render_leaps_earnings_context(earnings_context)
```

(`snapshot` is already in scope in both `leaps_show` and `leaps_update` by this point in the function.)

- [ ] **Step 7: Manual sanity check**

Run: `python -m stocktool.cli leaps show AMZN`
Expected: an "Earnings Context" panel appears, no traceback, showing either real earnings-date/move data or an honest "unavailable"/"no history" message.

- [ ] **Step 8: Commit**

```bash
git add stocktool/analysis.py stocktool/display.py stocktool/cli.py tests/test_leaps_earnings.py
git commit -m "feat: add earnings move history and delta-only impact projection to LEAPS detail view"
```

---

### Task 7: Liquidity (spread, volume, open interest)

**Files:**
- Modify: `stocktool/data.py:729-764` (`fetch_leaps_option_quote`), `stocktool/data.py:865-885` (`fetch_leaps_option_context`'s contract block)
- Modify: `stocktool/config.py` (new constants)
- Modify: `stocktool/analysis.py` (new function)
- Modify: `stocktool/display.py` (new render function; import)
- Modify: `stocktool/cli.py` (`leaps_show`, `leaps_update`)
- Create: `tests/test_leaps_liquidity.py`

**Interfaces:**
- Produces: `analysis.leaps_liquidity_rating(spread_pct: Optional[float], open_interest: Optional[float]) -> tuple[str, str]`. `display.render_leaps_liquidity(option_quote: dict, contracts: int) -> None`. `fetch_leaps_option_quote`/`fetch_leaps_option_context` result dicts gain optional `"volume"`/`"open_interest"` keys.

- [ ] **Step 1: Write the failing tests** — create `tests/test_leaps_liquidity.py`:

```python
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from stocktool.analysis import leaps_liquidity_rating
from stocktool.data import fetch_leaps_option_quote


class LeapsLiquidityRatingTests(unittest.TestCase):
    def test_tight_when_narrow_spread_and_high_oi(self):
        self.assertEqual(leaps_liquidity_rating(0.5, 600), ("TIGHT", "green"))

    def test_moderate_boundary(self):
        self.assertEqual(leaps_liquidity_rating(2.0, 200), ("MODERATE", "yellow"))

    def test_wide_boundary(self):
        self.assertEqual(leaps_liquidity_rating(4.0, 60), ("WIDE", "orange3"))

    def test_illiquid_when_spread_too_wide(self):
        self.assertEqual(leaps_liquidity_rating(8.0, 1000), ("ILLIQUID", "red"))

    def test_illiquid_when_open_interest_too_low(self):
        self.assertEqual(leaps_liquidity_rating(0.5, 10), ("ILLIQUID", "red"))

    def test_missing_spread_returns_na(self):
        # Review Focus #4.
        self.assertEqual(leaps_liquidity_rating(None, 600), ("N/A", "dim"))

    def test_missing_open_interest_returns_na(self):
        # Review Focus #4.
        self.assertEqual(leaps_liquidity_rating(0.5, None), ("N/A", "dim"))


class FetchLeapsOptionQuoteLiquidityTests(unittest.TestCase):
    def test_extracts_volume_and_open_interest(self):
        row = pd.DataFrame([{
            "strike": 100.0, "bid": 9.5, "ask": 10.0,
            "impliedVolatility": 0.30, "lastTradeDate": pd.Timestamp("2026-01-01"),
            "volume": 89, "openInterest": 1245,
        }])
        chain = Mock()
        chain.calls, chain.puts = row, row
        ticker = Mock()
        ticker.option_chain.return_value = chain

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            result = fetch_leaps_option_quote("TEST", "CALL", 100.0, "2028-01-01")

        self.assertEqual(result["volume"], 89)
        self.assertEqual(result["open_interest"], 1245)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_leaps_liquidity -v`
Expected: `FAIL`/`ImportError`/`KeyError` — `leaps_liquidity_rating` doesn't exist, and the quote dict has no `"volume"`/`"open_interest"` keys yet.

- [ ] **Step 3: Add config constants** — in `stocktool/config.py`, after the earnings constant from Task 5:

```python
# Liquidity rating: spread-of-mid and open interest thresholds. Same 4-tier palette as IV Rank.
LEAPS_LIQUIDITY_TIGHT_SPREAD_PCT = 1.0
LEAPS_LIQUIDITY_MODERATE_SPREAD_PCT = 3.0
LEAPS_LIQUIDITY_WIDE_SPREAD_PCT = 5.0
LEAPS_LIQUIDITY_TIGHT_OI = 500
LEAPS_LIQUIDITY_MODERATE_OI = 100
LEAPS_LIQUIDITY_WIDE_OI = 50
```

- [ ] **Step 4: Extend `fetch_leaps_option_quote` and `fetch_leaps_option_context` with volume/open interest** — in `stocktool/data.py`, inside `fetch_leaps_option_quote`'s try block, right after the existing `iv = _safe_float(row.get("impliedVolatility"))` line, add:

```python
        volume = _safe_float(row.get("volume"))
        open_interest = _safe_float(row.get("openInterest"))
```

and right after the existing `if iv is not None: result["implied_volatility"] = iv * 100` block, add:

```python
        if volume is not None:
            result["volume"] = volume
        if open_interest is not None:
            result["open_interest"] = open_interest
```

Make the identical addition inside `fetch_leaps_option_context`'s contract block (same two insertion points, same variable names, right after its own `iv = _safe_float(row.get("impliedVolatility"))` and its `if iv is not None: result["implied_volatility"] = iv * 100` lines).

- [ ] **Step 5: Implement `leaps_liquidity_rating`** — add to `stocktool/analysis.py`:

```python
def leaps_liquidity_rating(spread_pct: Optional[float], open_interest: Optional[float]) -> tuple[str, str]:
    """Liquidity rating from spread-of-mid and open interest. ('N/A', 'dim') when either input
    is missing — never guesses at liquidity from partial data."""
    from .config import (
        LEAPS_LIQUIDITY_TIGHT_SPREAD_PCT, LEAPS_LIQUIDITY_MODERATE_SPREAD_PCT,
        LEAPS_LIQUIDITY_WIDE_SPREAD_PCT, LEAPS_LIQUIDITY_TIGHT_OI,
        LEAPS_LIQUIDITY_MODERATE_OI, LEAPS_LIQUIDITY_WIDE_OI,
    )
    if spread_pct is None or open_interest is None:
        return "N/A", "dim"
    if spread_pct < LEAPS_LIQUIDITY_TIGHT_SPREAD_PCT and open_interest > LEAPS_LIQUIDITY_TIGHT_OI:
        return "TIGHT", "green"
    if spread_pct < LEAPS_LIQUIDITY_MODERATE_SPREAD_PCT and open_interest > LEAPS_LIQUIDITY_MODERATE_OI:
        return "MODERATE", "yellow"
    if spread_pct < LEAPS_LIQUIDITY_WIDE_SPREAD_PCT and open_interest > LEAPS_LIQUIDITY_WIDE_OI:
        return "WIDE", "orange3"
    return "ILLIQUID", "red"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m unittest tests.test_leaps_liquidity -v`
Expected: all 8 tests `PASS`.

- [ ] **Step 7: Add the display function** — in `stocktool/display.py`, add `leaps_liquidity_rating` to the analysis import block, then add:

```python
def render_leaps_liquidity(option_quote: dict, contracts: int) -> None:
    """Bid/ask/volume/open-interest context — passed straight from the already-fetched quote
    dict rather than stored on LeapsSnapshot, since both callers already hold it in scope."""
    bid, ask, mid = option_quote.get("bid"), option_quote.get("ask"), option_quote.get("mid")
    spread_pct = option_quote.get("spread_pct")
    volume, open_interest = option_quote.get("volume"), option_quote.get("open_interest")
    rating_label, rating_color = leaps_liquidity_rating(spread_pct, open_interest)
    lines = []
    if bid is not None and ask is not None:
        mid_str = f"  Mid: ${mid:.2f}" if mid is not None else ""
        lines.append(f"Bid/Ask: ${bid:.2f} / ${ask:.2f}{mid_str}")
        if spread_pct is not None:
            spread_cost = (ask - bid) * 100 * contracts
            lines.append(
                f"Spread: ${ask - bid:.2f} ({spread_pct:.1f}% of mid) · round-trip cost estimate: "
                f"~${spread_cost:,.2f} [dim](estimate, not a guaranteed execution cost)[/dim]"
            )
    else:
        lines.append("Bid/Ask: unavailable")
    if open_interest is not None:
        lines.append(f"Open interest: {open_interest:,.0f} contracts")
    if volume is not None:
        lines.append(f"Volume (latest session): {volume:,.0f} contracts")
    if volume is not None and open_interest:
        lines.append(f"Volume/OI ratio: {volume / open_interest:.2f}")
    lines.append(f"Liquidity rating: [{rating_color}]{rating_label}[/{rating_color}]")
    console.print(Panel(
        "\n".join(lines),
        title="[bold magenta]Market Liquidity[/bold magenta]",
        border_style="magenta",
    ))
```

- [ ] **Step 8: Wire into `leaps_show` and `leaps_update`** — in `stocktool/cli.py`, right after the earnings-context call added in Task 6 (in both commands), add:

```python
    display.render_leaps_liquidity(option_quote, position.contracts)
```

- [ ] **Step 9: Manual sanity check**

Run: `python -m stocktool.cli leaps show AMZN`
Expected: a "Market Liquidity" panel appears with bid/ask/spread/volume/OI and a liquidity rating, no traceback.

- [ ] **Step 10: Commit**

```bash
git add stocktool/data.py stocktool/config.py stocktool/analysis.py stocktool/display.py stocktool/cli.py tests/test_leaps_liquidity.py
git commit -m "feat: surface bid/ask spread, volume, and open interest for LEAPS positions"
```

---

### Task 8: CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md` (LEAPS section)

**Interfaces:**
- None — documentation only, no code interface.

- [ ] **Step 1: Document all four features and the bug-fix polish**

In `CLAUDE.md`'s LEAPS section, add new subsections (after the existing "Stock-Equivalent Exposure" subsection, before "Value-investor cross-check" — or wherever reads most naturally alongside the existing level of detail) covering, at the same depth as the existing IV-verdict documentation added earlier:

- **Vega + IV Impact**: the `_black_scholes_greeks` extension, `LeapsGammaCurve.vega`, `LeapsVegaImpact`/`build_leaps_vega_impact`, the "today's vega as constant approximation" caveat, and where it renders.
- **IV Rank**: the `leaps_iv_rank` formula, the 4-tier palette exception (and why), the `leaps show` capture-cadence change (now a light write), and the entry-day mismatch flag.
- **Earnings Move History**: `fetch_next_earnings_date`/`fetch_earnings_move_history`, the bracketing-close methodology, `leaps_earnings_move_stats`/`build_leaps_earnings_context`, and the explicit no-IV-crush-number decision.
- **Liquidity**: the new `volume`/`open_interest` fields, `leaps_liquidity_rating`'s thresholds, and the spread-cost-estimate caveat.

Update the "Scope of this implementation (MVP)" paragraph's "Deferred to future phases" line to remove anything now implemented (IV Rank is no longer purely deferred — a self-tracked-history version now exists; a *true* historical-IV-based rank remains deferred since that still needs a data source this tool doesn't have).

- [ ] **Step 2: Verify no other CLAUDE.md section references stale behavior**

Run: `grep -n "Deferred to future phases\|IV rank" CLAUDE.md`
Expected: the deferred-items line accurately reflects what Tasks 1-7 actually built (self-tracked IV Rank implemented; true historical-IV-based percentile still deferred).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document LEAPS vega, IV rank, earnings history, and liquidity features"
```

---

### Task 9: Full verification

**Files:**
- None (verification only; fixes if anything is found get their own commit referencing the task that owns the broken code).

**Interfaces:**
- None.

- [ ] **Step 1: Run the entire test suite**

Run: `python -m unittest discover -s tests -v`
Expected: every test across `test_leaps_gamma.py`, `test_leaps_vega_impact.py`, `test_leaps_iv_rank.py`, `test_leaps_model.py`, `test_leaps_earnings.py`, `test_leaps_liquidity.py` passes — no regressions from Tasks 1-7.

- [ ] **Step 2: Manual end-to-end run against the real AMZN LEAPS position**

Run: `python -m stocktool.cli leaps show AMZN`
Expected: Vega Analysis, Earnings Context, and Market Liquidity panels all appear (alongside the existing gamma/delta chart), an IV Rank line appears under Current IV, no traceback.

- [ ] **Step 3: Confirm the daily dedup behavior end-to-end**

Run: `python -m stocktool.cli leaps show AMZN` a second time immediately after Step 2.
Expected: output is stable (same IV Rank reading count as Step 2 — no duplicate entry appended for the same day). Confirm by inspecting `~/.config/stocktool/leaps.json`'s `iv_history` for the AMZN position: the last entry's `date` should still be today's date exactly once.

- [ ] **Step 4: Run `leaps update` once end-to-end**

Run: `python -m stocktool.cli leaps update AMZN` (answer prompts with any valid values, or accept the shown defaults).
Expected: all four new sections also appear after `leaps update`'s own gamma/delta chart, consistent with `leaps show`.

- [ ] **Step 5: If any issue surfaced in Steps 1-4, fix it in the owning task's files and commit**

```bash
git add <files touched by the fix>
git commit -m "fix: <describe the specific issue found during end-to-end verification>"
```

(If nothing surfaced, no commit is needed for this task — Tasks 1-8 already committed everything.)
