from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Optional

from .config import PORTFOLIO_FILE, ensure_config_dir


@dataclass
class Position:
    ticker: str
    shares: float
    cost_basis: float          # cost per share
    target_weight: Optional[float] = None  # percentage 0-100


@dataclass
class Portfolio:
    positions: list[Position] = field(default_factory=list)

    # --- mutation ---

    def add_position(self, ticker: str, shares: float, price: float) -> None:
        ticker = ticker.upper()
        existing = self._find(ticker)
        if existing is None:
            self.positions.append(Position(ticker=ticker, shares=shares, cost_basis=price))
        else:
            total_shares = existing.shares + shares
            existing.cost_basis = (
                existing.shares * existing.cost_basis + shares * price
            ) / total_shares
            existing.shares = total_shares

    def remove_position(self, ticker: str) -> bool:
        ticker = ticker.upper()
        before = len(self.positions)
        self.positions = [p for p in self.positions if p.ticker != ticker]
        return len(self.positions) < before

    def set_target_weight(self, ticker: str, weight: float) -> bool:
        ticker = ticker.upper()
        pos = self._find(ticker)
        if pos is None:
            return False
        pos.target_weight = weight
        return True

    def tickers(self) -> list[str]:
        return [p.ticker for p in self.positions]

    def _find(self, ticker: str) -> Optional[Position]:
        for p in self.positions:
            if p.ticker == ticker:
                return p
        return None


@dataclass
class PositionSnapshot:
    ticker: str
    shares: float
    cost_basis: float
    current_price: float
    market_value: float
    cost_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    current_weight: float        # percentage of total portfolio
    target_weight: Optional[float]
    sector: Optional[str]


@dataclass
class PortfolioSnapshot:
    positions: list[PositionSnapshot]
    total_market_value: float
    total_cost_value: float
    total_unrealized_pnl: float
    total_unrealized_pnl_pct: float
    sector_allocation: dict[str, float]   # sector -> % of portfolio
    rebalancing_signals: list[dict]       # list of signal dicts


def build_portfolio_snapshot(
    portfolio: Portfolio,
    current_prices: dict[str, float],
    sector_map: dict[str, Optional[str]],
) -> PortfolioSnapshot:
    position_snapshots: list[PositionSnapshot] = []
    total_market_value = 0.0
    total_cost_value = 0.0

    # First pass: compute market values
    for pos in portfolio.positions:
        price = current_prices.get(pos.ticker, 0.0)
        market_value = pos.shares * price
        cost_value = pos.shares * pos.cost_basis
        total_market_value += market_value
        total_cost_value += cost_value

    # Second pass: build snapshots with weights
    for pos in portfolio.positions:
        price = current_prices.get(pos.ticker, 0.0)
        market_value = pos.shares * price
        cost_value = pos.shares * pos.cost_basis
        unrealized_pnl = market_value - cost_value
        unrealized_pnl_pct = (unrealized_pnl / cost_value * 100) if cost_value else 0.0
        current_weight = (market_value / total_market_value * 100) if total_market_value else 0.0

        position_snapshots.append(
            PositionSnapshot(
                ticker=pos.ticker,
                shares=pos.shares,
                cost_basis=pos.cost_basis,
                current_price=price,
                market_value=market_value,
                cost_value=cost_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                current_weight=current_weight,
                target_weight=pos.target_weight,
                sector=sector_map.get(pos.ticker),
            )
        )

    total_unrealized_pnl = total_market_value - total_cost_value
    total_unrealized_pnl_pct = (
        total_unrealized_pnl / total_cost_value * 100 if total_cost_value else 0.0
    )

    # Sector allocation
    sector_allocation: dict[str, float] = {}
    for ps in position_snapshots:
        sector = ps.sector or "Unknown"
        sector_allocation[sector] = sector_allocation.get(sector, 0.0) + ps.current_weight

    # Rebalancing signals
    rebalancing_signals = _compute_rebalancing_signals(position_snapshots, total_market_value)

    return PortfolioSnapshot(
        positions=position_snapshots,
        total_market_value=total_market_value,
        total_cost_value=total_cost_value,
        total_unrealized_pnl=total_unrealized_pnl,
        total_unrealized_pnl_pct=total_unrealized_pnl_pct,
        sector_allocation=sector_allocation,
        rebalancing_signals=rebalancing_signals,
    )


def _compute_rebalancing_signals(
    positions: list[PositionSnapshot],
    total_market_value: float,
) -> list[dict]:
    signals = []
    for ps in positions:
        if ps.target_weight is None:
            continue
        diff = ps.current_weight - ps.target_weight
        if diff > 2:
            signal = "OVERWEIGHT"
            color = "red"
        elif diff < -2:
            signal = "UNDERWEIGHT"
            color = "yellow"
        else:
            signal = "ON_TARGET"
            color = "green"

        # Compute dollar amount to buy/sell
        target_value = total_market_value * ps.target_weight / 100
        dollar_diff = ps.market_value - target_value
        shares_diff = dollar_diff / ps.current_price if ps.current_price else 0.0

        signals.append(
            {
                "ticker": ps.ticker,
                "current_weight": ps.current_weight,
                "target_weight": ps.target_weight,
                "diff": diff,
                "signal": signal,
                "color": color,
                "dollar_diff": dollar_diff,
                "shares_diff": shares_diff,
            }
        )
    return signals


# --- persistence ---

def load_portfolio() -> Portfolio:
    if not PORTFOLIO_FILE.exists():
        return Portfolio()
    try:
        with PORTFOLIO_FILE.open() as f:
            data = json.load(f)
        positions = [
            Position(
                ticker=p["ticker"],
                shares=p["shares"],
                cost_basis=p["cost_basis"],
                target_weight=p.get("target_weight"),
            )
            for p in data.get("positions", [])
        ]
        return Portfolio(positions=positions)
    except (json.JSONDecodeError, KeyError):
        return Portfolio()


def save_portfolio(portfolio: Portfolio) -> None:
    ensure_config_dir()
    data = dataclasses.asdict(portfolio)
    with PORTFOLIO_FILE.open("w") as f:
        json.dump(data, f, indent=2)
