"""LEAPS Decision Analyzer (`vstock calc leaps`) — pure math and rule checks, no I/O.

Every threshold lives in config.py's "LEAPS Decision Analyzer framework" block. There is
deliberately no override path: a blocking rule can only be changed by editing that block.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .analysis import _black_scholes_greeks, black_scholes_price_theta
from .config import (
    CALC_APPROVED_TICKERS, CALC_PHASE_UNLOCK_TICKERS, CALC_DELTA_MIN, CALC_DELTA_MAX,
    CALC_DELTA_WARN_MIN, CALC_DELTA_WARN_MAX, CALC_MIN_DTE, CALC_MAX_POSITION_PCT,
    CALC_EXIT_DAYS_BEFORE_EXPIRY, CALC_PROFIT_TARGET_PCT, CALC_STOP_LOSS_PCT, CALC_IV_SIZING,
    CALC_IV_HIGH_PCT, CALC_IV_PERCENTILE_MAX, CALC_EARNINGS_TRAP_DAYS, CALC_PHASE_THRESHOLDS,
    CALC_DEFAULT_PHASE_THRESHOLD, CALC_MARGIN_MAX_PCT, CALC_SPREAD_WARN_PCT, CALC_CORRELATION,
    CALC_DEFAULT_CORRELATION, CALC_CORRELATION_MAX, CALC_SECTORS, CALC_MIN_SECTORS,
    CALC_DEFAULT_PRICE_GRID, CALC_HORIZONS,
)

SEVERITY_OK = "ok"
SEVERITY_WARNING = "warning"
SEVERITY_BLOCKING = "blocking"
SEVERITY_SKIPPED = "skipped"

VERDICT_APPROVED = "APPROVED"
VERDICT_CAUTION = "CAUTION"
VERDICT_BLOCKED = "BLOCKED"


@dataclass
class ExistingLeaps:
    """An already-held LEAPS, reduced to what the correlation/duplicate/sector rules need."""
    ticker: str
    strike: float
    expiration: str
    premium: float
    option_type: str = "CALL"


@dataclass
class CalcInputs:
    ticker: str
    strike: float
    expiration: str                      # resolved, actual expiration (ISO)
    spot: Optional[float]
    premium: Optional[float]
    option_type: str = "CALL"
    requested_expiration: Optional[str] = None
    premium_source: str = "Yahoo bid/ask midpoint"
    premium_overridden: bool = False
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    spread_pct: Optional[float] = None
    open_interest: Optional[float] = None
    volume: Optional[float] = None
    iv_pct: Optional[float] = None
    iv_source: Optional[str] = None
    iv_percentile: Optional[float] = None   # 0-100; yfinance can't supply it, --iv-percentile can
    delta: Optional[float] = None
    delta_source: Optional[str] = None
    theta: Optional[float] = None           # $ per share per calendar day (negative)
    gamma: Optional[float] = None
    vega: Optional[float] = None
    earnings_date: Optional[str] = None
    days_to_earnings: Optional[int] = None
    earnings_estimated: bool = False        # projected from the last report + one quarter
    nav: Optional[float] = None
    used_margin: float = 0.0
    paper: bool = False
    existing_leaps: list[ExistingLeaps] = field(default_factory=list)
    today: Optional[str] = None             # ISO; None means date.today() (parameter for tests)


@dataclass
class RuleCheck:
    rule: str
    required: str
    actual: str
    passed: bool
    severity: str  # ok | warning | blocking | skipped
    why: str = ""  # plain-English reason the rule exists, shown under non-passing rules


@dataclass
class ScenarioRow:
    price: float
    move_pct: float
    markers: list[str]
    pnl_by_horizon: dict[int, Optional[float]]  # days forward -> P&L per contract
    pnl_at_expiry: float


@dataclass
class CalcMetrics:
    days_to_expiry: int
    contract_cost: Optional[float]
    breakeven: Optional[float]
    exit_price: Optional[float]
    stop_price: Optional[float]
    critical_exit_date: str
    breakeven_move_pct: Optional[float]
    exit_move_pct: Optional[float]
    stop_move_pct: Optional[float]
    max_loss: Optional[float]
    position_pct: Optional[float]
    max_position_cost: Optional[float]
    iv_max_position_pct: Optional[float]
    iv_max_cost: Optional[float]
    margin_pct: Optional[float]
    theta_projection: dict[int, float] = field(default_factory=dict)       # days -> $ per contract
    theta_projection_pct: dict[int, float] = field(default_factory=dict)   # days -> % of premium


@dataclass
class LeapsEvaluation:
    inputs: CalcInputs
    metrics: CalcMetrics
    rules: list[RuleCheck]
    scenarios: list[ScenarioRow]
    verdict: str
    blocking_count: int
    warning_count: int
    pass_count: int
    correlations: list[tuple[str, float]]
    recommendations: list[str]
    strengths: list[str]

    @property
    def contract_label(self) -> str:
        return f"{self.inputs.ticker} {self.inputs.expiration} ${self.inputs.strike:g}{self.inputs.option_type[0]}"


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------

def _today(inputs: CalcInputs) -> date:
    return date.fromisoformat(inputs.today) if inputs.today else date.today()


def model_greeks(
    option_type: str,
    spot: float,
    strike: float,
    days_to_expiry: int,
    iv_pct: float,
    risk_free_pct: float,
    dividend_pct: float,
) -> Optional[dict]:
    """Black–Scholes delta/gamma/vega/theta/price, or None when inputs can't support the model."""
    if None in (spot, strike, iv_pct, risk_free_pct, dividend_pct):
        return None
    if days_to_expiry <= 0 or spot <= 0 or strike <= 0 or iv_pct <= 0:
        return None
    years = days_to_expiry / 365.0
    args = (option_type, spot, strike, years, iv_pct / 100, risk_free_pct / 100, dividend_pct / 100)
    delta, gamma, vega = _black_scholes_greeks(*args)
    price, theta = black_scholes_price_theta(*args)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "price": price}


def intrinsic_value(option_type: str, strike: float, stock_price: float) -> float:
    if option_type == "PUT":
        return max(0.0, strike - stock_price)
    return max(0.0, stock_price - strike)


def breakeven_price(option_type: str, strike: float, premium: float) -> float:
    return strike - premium if option_type == "PUT" else strike + premium


def exit_trigger_price(spot: float, premium: float, delta: float) -> float:
    """Stock price at which a +50% premium gain is expected (linear delta approximation)."""
    return spot + (CALC_PROFIT_TARGET_PCT / 100) * premium / delta


def stop_loss_price(spot: float, premium: float, delta: float) -> float:
    """Stock price at which a -50% premium loss is expected (linear delta approximation)."""
    return spot - (CALC_STOP_LOSS_PCT / 100) * premium / delta


def project_premium(
    option_type: str,
    strike: float,
    premium: float,
    delta: float,
    theta: float,
    spot: float,
    stock_price: float,
    days_forward: int,
) -> float:
    """Short-term option value: premium + delta·Δstock + theta·days (theta is negative).

    Assumes delta stays constant (reasonable for roughly ±20% moves). Floored at intrinsic
    value, since an option can't trade below what it would pay out if exercised.
    """
    value = premium + delta * (stock_price - spot) + theta * days_forward
    return max(value, intrinsic_value(option_type, strike, stock_price))


def iv_max_position_pct(iv_pct: Optional[float]) -> float:
    """Max position % of NAV allowed for this IV level; unknown IV is treated as high IV."""
    if iv_pct is None:
        return CALC_IV_SIZING[-1][1]
    for upper, max_pct in CALC_IV_SIZING:
        if iv_pct < upper:
            return max_pct
    return CALC_IV_SIZING[-1][1]


def _iv_tier_labels() -> list[tuple[str, float]]:
    """('<40%', 4.0), ('40–60%', 3.0), ('≥60%', 1.0) — built from CALC_IV_SIZING so text never drifts from config."""
    labels: list[tuple[str, float]] = []
    lower = None
    for upper, max_pct in CALC_IV_SIZING:
        if lower is None:
            label = f"<{upper:g}%"
        elif upper == float("inf"):
            label = f"≥{lower:g}%"
        else:
            label = f"{lower:g}–{upper:g}%"
        labels.append((label, max_pct))
        lower = upper
    return labels


def iv_tier_label(iv_pct: float) -> str:
    for (label, _), (upper, _) in zip(_iv_tier_labels(), CALC_IV_SIZING):
        if iv_pct < upper:
            return label
    return _iv_tier_labels()[-1][0]


def pair_correlation(a: str, b: str) -> float:
    a, b = a.upper(), b.upper()
    if a == b:
        return 1.0
    return CALC_CORRELATION.get((a, b), CALC_CORRELATION.get((b, a), CALC_DEFAULT_CORRELATION))


def phase_threshold(ticker: str) -> float:
    return CALC_PHASE_THRESHOLDS.get(ticker.upper(), CALC_DEFAULT_PHASE_THRESHOLD)


def build_metrics(inputs: CalcInputs) -> CalcMetrics:
    expiration = date.fromisoformat(inputs.expiration)
    dte = (expiration - _today(inputs)).days
    premium, spot, delta = inputs.premium, inputs.spot, inputs.delta
    contract_cost = premium * 100 if premium is not None else None
    breakeven = breakeven_price(inputs.option_type, inputs.strike, premium) if premium is not None else None
    usable_delta = delta is not None and abs(delta) > 0 and spot is not None and premium is not None
    exit_price = exit_trigger_price(spot, premium, delta) if usable_delta else None
    stop_price = stop_loss_price(spot, premium, delta) if usable_delta else None

    def move(target: Optional[float]) -> Optional[float]:
        if target is None or not spot:
            return None
        return (target - spot) / spot * 100

    nav = inputs.nav if inputs.nav and inputs.nav > 0 else None
    iv_pct_cap = iv_max_position_pct(inputs.iv_pct)
    theta_projection: dict[int, float] = {}
    theta_projection_pct: dict[int, float] = {}
    if inputs.theta is not None:
        for days in (30, 90, 180, 365):
            dollars = inputs.theta * days * 100
            theta_projection[days] = dollars
            if contract_cost:
                theta_projection_pct[days] = dollars / contract_cost * 100

    return CalcMetrics(
        days_to_expiry=dte,
        contract_cost=contract_cost,
        breakeven=breakeven,
        exit_price=exit_price,
        stop_price=stop_price,
        critical_exit_date=(expiration - timedelta(days=CALC_EXIT_DAYS_BEFORE_EXPIRY)).isoformat(),
        breakeven_move_pct=move(breakeven),
        exit_move_pct=move(exit_price),
        stop_move_pct=move(stop_price),
        max_loss=-contract_cost if contract_cost is not None else None,
        position_pct=(contract_cost / nav * 100) if (nav and contract_cost is not None) else None,
        max_position_cost=nav * CALC_MAX_POSITION_PCT / 100 if nav else None,
        iv_max_position_pct=iv_pct_cap,
        iv_max_cost=nav * iv_pct_cap / 100 if nav else None,
        margin_pct=(inputs.used_margin / nav * 100) if nav else None,
        theta_projection=theta_projection,
        theta_projection_pct=theta_projection_pct,
    )


def build_scenarios(
    inputs: CalcInputs,
    metrics: CalcMetrics,
    prices: Optional[list[float]] = None,
) -> list[ScenarioRow]:
    """P&L per contract over a price grid × time horizons, newest-highest price first."""
    spot, premium = inputs.spot, inputs.premium
    if spot is None or premium is None:
        return []
    marked: dict[float, list[str]] = {}
    grid = prices if prices else [spot * m for m in CALC_DEFAULT_PRICE_GRID]
    for p in grid:
        marked.setdefault(round(p, 2), [])
    for value, marker in (
        (metrics.exit_price, "🎯"),
        (metrics.breakeven, "BE"),
        (inputs.strike, "K"),
        (metrics.stop_price, "🛑"),
        (spot, "NOW"),
    ):
        if value is not None and value > 0:
            marked.setdefault(round(value, 2), []).append(marker)

    rows: list[ScenarioRow] = []
    for price in sorted(marked, reverse=True):
        by_horizon: dict[int, Optional[float]] = {}
        for days in CALC_HORIZONS:
            if inputs.delta is None or days >= metrics.days_to_expiry:
                by_horizon[days] = None
                continue
            if days > 0 and inputs.theta is None:
                by_horizon[days] = None
                continue
            value = project_premium(
                inputs.option_type, inputs.strike, premium, inputs.delta,
                inputs.theta or 0.0, spot, price, days,
            )
            by_horizon[days] = (value - premium) * 100
        at_expiry = (intrinsic_value(inputs.option_type, inputs.strike, price) - premium) * 100
        rows.append(ScenarioRow(
            price=price,
            move_pct=(price - spot) / spot * 100,
            markers=marked[price],
            pnl_by_horizon=by_horizon,
            pnl_at_expiry=at_expiry,
        ))
    return rows


# ---------------------------------------------------------------------------
# Rules — one function per rule, each returning a RuleCheck
# ---------------------------------------------------------------------------

def _skipped(rule: str, required: str, reason: str) -> RuleCheck:
    return RuleCheck(rule, required, reason, True, SEVERITY_SKIPPED)


def check_approved_ticker(inputs: CalcInputs) -> RuleCheck:
    ticker = inputs.ticker.upper()
    required = ", ".join(CALC_APPROVED_TICKERS)
    if ticker in CALC_APPROVED_TICKERS:
        return RuleCheck("Approved ticker", required, ticker, True, SEVERITY_OK)
    unlock = CALC_PHASE_UNLOCK_TICKERS.get(ticker)
    if unlock is not None:
        required = f"{required} (+{ticker} at NAV ≥ ${unlock:,.0f})"
        if inputs.paper:
            return RuleCheck(
                "Approved ticker", required,
                f"{ticker} — phase-locked, can't unlock in paper mode", False, SEVERITY_BLOCKING,
            )
        if inputs.nav is not None and inputs.nav >= unlock:
            return RuleCheck("Approved ticker", required, f"{ticker} (phase unlocked)", True, SEVERITY_OK)
        return RuleCheck(
            "Approved ticker", required,
            f"{ticker} — locked until NAV ≥ ${unlock:,.0f}", False, SEVERITY_BLOCKING,
        )
    return RuleCheck("Approved ticker", required, f"{ticker} — not on approved list", False, SEVERITY_BLOCKING)


def check_delta(inputs: CalcInputs) -> RuleCheck:
    required = f"{CALC_DELTA_MIN:.2f} to {CALC_DELTA_MAX:.2f}"
    if inputs.delta is None:
        return RuleCheck("Delta range", required, "unknown (no IV to model it)", False, SEVERITY_BLOCKING)
    delta = abs(inputs.delta)
    actual = f"{delta:.2f}"
    if CALC_DELTA_MIN <= delta <= CALC_DELTA_MAX:
        return RuleCheck("Delta range", required, actual, True, SEVERITY_OK)
    if CALC_DELTA_WARN_MIN <= delta <= CALC_DELTA_WARN_MAX:
        return RuleCheck("Delta range", required, actual, False, SEVERITY_WARNING)
    return RuleCheck("Delta range", required, actual, False, SEVERITY_BLOCKING)


def check_dte(inputs: CalcInputs, metrics: CalcMetrics) -> RuleCheck:
    passed = metrics.days_to_expiry >= CALC_MIN_DTE
    return RuleCheck(
        "Days to expiry", f">= {CALC_MIN_DTE} days", f"{metrics.days_to_expiry} days",
        passed, SEVERITY_OK if passed else SEVERITY_BLOCKING,
    )


def check_position_size(inputs: CalcInputs, metrics: CalcMetrics) -> RuleCheck:
    rule = "Position size"
    if inputs.paper:
        return _skipped(rule, f"<= {CALC_MAX_POSITION_PCT:g}% of NAV", "paper mode")
    if metrics.max_position_cost is None or metrics.contract_cost is None:
        return RuleCheck(rule, f"<= {CALC_MAX_POSITION_PCT:g}% of NAV", "NAV unknown", False, SEVERITY_BLOCKING)
    passed = metrics.contract_cost <= metrics.max_position_cost
    return RuleCheck(
        rule,
        f"<= ${metrics.max_position_cost:,.0f} ({CALC_MAX_POSITION_PCT:g}% of ${inputs.nav:,.0f})",
        f"${metrics.contract_cost:,.0f} ({metrics.position_pct:.1f}%)",
        passed, SEVERITY_OK if passed else SEVERITY_BLOCKING,
    )


def check_iv_sizing(inputs: CalcInputs, metrics: CalcMetrics) -> RuleCheck:
    rule = "IV level / sizing"
    tiers = [f"IV {label} → max {cap:g}% of NAV" for label, cap in _iv_tier_labels()]
    tiers[-1] += " (or avoid)"
    required = " · ".join(tiers)
    why = (
        "Higher implied volatility (IV) means a pricier premium and bigger price swings, "
        "so each dollar carries more risk — the higher the IV, the smaller the position."
    )
    if inputs.iv_pct is None:
        return RuleCheck(
            rule, required, "IV unknown — treated as high, so max 1% of NAV", False, SEVERITY_WARNING, why,
        )
    cap = metrics.iv_max_position_pct
    cap_cost = f" (${metrics.iv_max_cost:,.0f})" if metrics.iv_max_cost is not None else ""
    actual = f"IV {inputs.iv_pct:.1f}% is in the {iv_tier_label(inputs.iv_pct)} tier → max {cap:g}% of NAV{cap_cost}"
    if inputs.iv_pct >= CALC_IV_HIGH_PCT:
        return RuleCheck(rule, required, f"{actual} — high IV, consider avoiding", False, SEVERITY_WARNING, why)
    if not inputs.paper and metrics.position_pct is not None and metrics.position_pct > cap:
        cost = f" (${metrics.contract_cost:,.0f})" if metrics.contract_cost is not None else ""
        return RuleCheck(
            rule, required,
            f"{actual}, but this contract is {metrics.position_pct:.1f}% of NAV{cost} — "
            f"{metrics.position_pct / cap:.1f}× over the cap",
            False, SEVERITY_WARNING, why,
        )
    return RuleCheck(rule, required, actual, True, SEVERITY_OK, why)


def check_iv_crush(inputs: CalcInputs) -> RuleCheck:
    """IV-crush trap. Conservative defaults: unknown percentile = high, unknown earnings = soon."""
    required = f"not (IV percentile > {CALC_IV_PERCENTILE_MAX:g}% and earnings < {CALC_EARNINGS_TRAP_DAYS}d)"
    pct_high = inputs.iv_percentile is None or inputs.iv_percentile > CALC_IV_PERCENTILE_MAX
    earnings_soon = inputs.days_to_earnings is None or inputs.days_to_earnings < CALC_EARNINGS_TRAP_DAYS
    pct_text = "unknown (assumed high)" if inputs.iv_percentile is None else f"{inputs.iv_percentile:.0f}%"
    earn_text = (
        "unknown (assumed <30d)" if inputs.days_to_earnings is None
        else f"{inputs.days_to_earnings}d" + (" (est.)" if inputs.earnings_estimated else "")
    )
    actual = f"IV pctile {pct_text}, earnings in {earn_text}"
    passed = not (pct_high and earnings_soon)
    return RuleCheck("IV crush trap", required, actual, passed, SEVERITY_OK if passed else SEVERITY_BLOCKING)


def check_phase(inputs: CalcInputs) -> RuleCheck:
    threshold = phase_threshold(inputs.ticker)
    required = f"NAV ≥ ${threshold:,.0f} for real {inputs.ticker.upper()} LEAPS"
    if inputs.paper:
        return _skipped("Portfolio phase", required, "paper mode")
    if inputs.nav is None:
        return RuleCheck("Portfolio phase", required, "NAV unknown", False, SEVERITY_BLOCKING)
    passed = inputs.nav >= threshold
    return RuleCheck(
        "Portfolio phase", required, f"NAV ${inputs.nav:,.0f}", passed,
        SEVERITY_OK if passed else SEVERITY_BLOCKING,
    )


def check_margin(inputs: CalcInputs, metrics: CalcMetrics) -> RuleCheck:
    required = f"Margin < {CALC_MARGIN_MAX_PCT:g}% of NAV"
    if inputs.paper:
        return _skipped("Margin status", required, "paper mode")
    if metrics.margin_pct is None:
        return RuleCheck("Margin status", required, "NAV unknown", False, SEVERITY_BLOCKING)
    passed = metrics.margin_pct < CALC_MARGIN_MAX_PCT
    return RuleCheck(
        "Margin status", required, f"${inputs.used_margin:,.0f} ({metrics.margin_pct:.1f}% of NAV)",
        passed, SEVERITY_OK if passed else SEVERITY_BLOCKING,
    )


def check_spread(inputs: CalcInputs) -> RuleCheck:
    required = f"< {CALC_SPREAD_WARN_PCT:g}% of midpoint"
    if inputs.spread_pct is None:
        return RuleCheck("Bid-ask spread", required, "no two-sided quote", False, SEVERITY_WARNING)
    passed = inputs.spread_pct < CALC_SPREAD_WARN_PCT
    return RuleCheck(
        "Bid-ask spread", required, f"{inputs.spread_pct:.1f}%", passed,
        SEVERITY_OK if passed else SEVERITY_WARNING,
    )


def check_fill_price(inputs: CalcInputs) -> RuleCheck:
    required = "limit at midpoint, never pay the ask"
    if inputs.premium is None:
        return RuleCheck("Fill price", required, "no premium", False, SEVERITY_WARNING)
    if inputs.ask is not None and inputs.ask > 0 and inputs.premium >= inputs.ask:
        return RuleCheck(
            "Fill price", required, f"${inputs.premium:.2f} ≥ ask ${inputs.ask:.2f} — paying the ask",
            False, SEVERITY_WARNING,
        )
    target = f" (mid ${inputs.mid:.2f})" if inputs.mid is not None else ""
    return RuleCheck("Fill price", required, f"${inputs.premium:.2f}{target}", True, SEVERITY_OK)


def correlations_with_existing(inputs: CalcInputs) -> list[tuple[str, float]]:
    seen: dict[str, float] = {}
    for pos in inputs.existing_leaps:
        seen[pos.ticker.upper()] = pair_correlation(inputs.ticker, pos.ticker)
    return sorted(seen.items(), key=lambda kv: kv[1], reverse=True)


def check_correlation(inputs: CalcInputs, correlations: list[tuple[str, float]]) -> RuleCheck:
    required = f"No existing LEAPS with correlation > {CALC_CORRELATION_MAX:.2f}"
    if not correlations:
        return _skipped("Correlation", required, "no existing LEAPS")
    name, corr = correlations[0]
    passed = corr <= CALC_CORRELATION_MAX
    return RuleCheck(
        "Correlation", required, f"max {corr:.2f} with {name}", passed,
        SEVERITY_OK if passed else SEVERITY_WARNING,
    )


def check_duplicate(inputs: CalcInputs) -> RuleCheck:
    required = "contract not already held"
    for pos in inputs.existing_leaps:
        if (
            pos.ticker.upper() == inputs.ticker.upper()
            and math.isclose(pos.strike, inputs.strike)
            and pos.expiration == inputs.expiration
        ):
            return RuleCheck("Duplicate contract", required, "already held — duplication", False, SEVERITY_WARNING)
    if not inputs.existing_leaps:
        return _skipped("Duplicate contract", required, "no existing LEAPS")
    return RuleCheck("Duplicate contract", required, "new contract", True, SEVERITY_OK)


def check_sectors(inputs: CalcInputs) -> RuleCheck:
    required = f"≥ {CALC_MIN_SECTORS} sectors once running {CALC_MIN_SECTORS}+ LEAPS"
    tickers = {p.ticker.upper() for p in inputs.existing_leaps} | {inputs.ticker.upper()}
    count = len(inputs.existing_leaps) + 1
    if count < CALC_MIN_SECTORS:
        return _skipped("Sector diversification", required, f"{count} LEAPS after this buy")
    sectors = {CALC_SECTORS.get(t, t) for t in tickers}
    passed = len(sectors) >= CALC_MIN_SECTORS
    return RuleCheck(
        "Sector diversification", required, f"{len(sectors)} sectors across {count} LEAPS",
        passed, SEVERITY_OK if passed else SEVERITY_WARNING,
    )


def run_rule_checks(
    inputs: CalcInputs, metrics: CalcMetrics, correlations: list[tuple[str, float]]
) -> list[RuleCheck]:
    return [
        check_approved_ticker(inputs),
        check_delta(inputs),
        check_dte(inputs, metrics),
        check_iv_sizing(inputs, metrics),
        check_iv_crush(inputs),
        check_position_size(inputs, metrics),
        check_margin(inputs, metrics),
        check_phase(inputs),
        check_spread(inputs),
        check_fill_price(inputs),
        check_correlation(inputs, correlations),
        check_duplicate(inputs),
        check_sectors(inputs),
    ]


def derive_verdict(rules: list[RuleCheck]) -> tuple[str, int, int, int]:
    blocking = sum(1 for r in rules if r.severity == SEVERITY_BLOCKING)
    warnings = sum(1 for r in rules if r.severity == SEVERITY_WARNING)
    passes = sum(1 for r in rules if r.severity == SEVERITY_OK)
    if blocking:
        verdict = VERDICT_BLOCKED
    elif warnings:
        verdict = VERDICT_CAUTION
    else:
        verdict = VERDICT_APPROVED
    return verdict, blocking, warnings, passes


def _recommendations(inputs: CalcInputs, metrics: CalcMetrics, rules: list[RuleCheck]) -> list[str]:
    lines: list[str] = []
    for r in rules:
        if r.severity not in (SEVERITY_BLOCKING, SEVERITY_WARNING):
            continue
        if r.rule == "Approved ticker":
            lines.append(f"{inputs.ticker.upper()} isn't approved — pick from {', '.join(CALC_APPROVED_TICKERS)}.")
        elif r.rule == "Delta range":
            lines.append(
                f"Choose a strike with delta {CALC_DELTA_MIN:.2f}-{CALC_DELTA_MAX:.2f} "
                "(lower strike → higher delta)."
            )
        elif r.rule == "Days to expiry":
            lines.append(f"Pick an expiration at least {CALC_MIN_DTE} days out.")
        elif r.rule == "Position size" and metrics.contract_cost is not None and inputs.nav:
            needed = metrics.contract_cost / (CALC_MAX_POSITION_PCT / 100)
            lines.append(f"Grow NAV to ${needed:,.0f} for this contract to fit the {CALC_MAX_POSITION_PCT:g}% cap.")
        elif r.rule == "Margin status" and inputs.nav:
            target = inputs.nav * CALC_MARGIN_MAX_PCT / 100
            lines.append(f"Pay margin down below ${target:,.0f} (currently ${inputs.used_margin:,.0f}).")
        elif r.rule == "Portfolio phase":
            lines.append(f"Grow portfolio to ${phase_threshold(inputs.ticker):,.0f} (phase trigger for this name).")
        elif r.rule == "IV crush trap":
            lines.append("Wait until after earnings, or pass --iv-percentile if you know IV is not elevated.")
        elif r.rule == "IV level / sizing":
            cap_cost = f" (${metrics.iv_max_cost:,.0f})" if metrics.iv_max_cost is not None else ""
            lines.append(
                f"Size down to ≤{metrics.iv_max_position_pct:g}% of NAV{cap_cost} for this IV level, "
                "or wait for IV to drop into a lower tier."
            )
        elif r.rule == "Bid-ask spread":
            lines.append("Liquidity risk — work a limit at the midpoint and be patient.")
        elif r.rule == "Fill price":
            lines.append("Don't pay the ask — set a limit at the midpoint.")
        elif r.rule == "Correlation":
            lines.append("Highly correlated with an existing LEAPS — this adds concentration, not diversification.")
        elif r.rule == "Duplicate contract":
            lines.append("You already hold this exact contract.")
        elif r.rule == "Sector diversification":
            lines.append(f"Add a LEAPS outside your current sectors to reach {CALC_MIN_SECTORS}.")
    return lines


def _strengths(inputs: CalcInputs, metrics: CalcMetrics) -> list[str]:
    lines: list[str] = []
    if inputs.iv_pct is not None and inputs.iv_pct < CALC_IV_SIZING[0][0]:
        lines.append(f"Low IV entry ({inputs.iv_pct:.1f}% vs {CALC_IV_SIZING[0][0]:g}% tier)")
    if inputs.delta is not None and CALC_DELTA_MIN <= abs(inputs.delta) <= CALC_DELTA_MAX:
        lines.append(f"Deep ITM delta {abs(inputs.delta):.2f}")
    if metrics.days_to_expiry >= CALC_MIN_DTE:
        lines.append(f"{metrics.days_to_expiry / 30.44:.0f} months runway")
    if metrics.breakeven_move_pct is not None:
        lines.append(f"{metrics.breakeven_move_pct:+.1f}% move to break even at expiry")
    return lines


def evaluate_leaps(inputs: CalcInputs, scenario_prices: Optional[list[float]] = None) -> LeapsEvaluation:
    metrics = build_metrics(inputs)
    correlations = correlations_with_existing(inputs)
    rules = run_rule_checks(inputs, metrics, correlations)
    verdict, blocking, warnings, passes = derive_verdict(rules)
    return LeapsEvaluation(
        inputs=inputs,
        metrics=metrics,
        rules=rules,
        scenarios=build_scenarios(inputs, metrics, scenario_prices),
        verdict=verdict,
        blocking_count=blocking,
        warning_count=warnings,
        pass_count=passes,
        correlations=correlations,
        recommendations=_recommendations(inputs, metrics, rules),
        strengths=_strengths(inputs, metrics),
    )
