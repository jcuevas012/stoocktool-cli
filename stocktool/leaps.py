from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .config import LEAPS_FILE, ensure_config_dir


@dataclass
class IvReading:
    """One point in a LeapsPosition's accumulated IV history.

    yfinance has no historical-IV endpoint (see CLAUDE.md) — there is no way to fetch IV
    readings from the past. This instead builds a real history forward in time: one point
    seeded at `leaps add` (market IV from Yahoo's option chain for the exact contract, or the
    manually-entered entry IV if Yahoo had no quote), then one more point each time
    `leaps update` runs.
    """
    date: str   # ISO date
    iv: float   # percent
    source: str  # "yahoo" (fetched from Yahoo's live option chain) or "manual" (typed by hand)


@dataclass
class LeapsPosition:
    id: str
    ticker: str
    option_type: str           # "CALL" or "PUT"
    strike: float
    expiration: str            # ISO date string "YYYY-MM-DD"
    premium: float
    contracts: int = 1
    entry_date: str = ""       # ISO date string
    entry_stock_price: float = 0.0
    entry_delta: Optional[float] = None
    entry_theta: Optional[float] = None
    entry_iv: Optional[float] = None
    current_delta: Optional[float] = None
    current_theta: Optional[float] = None
    current_iv: Optional[float] = None
    last_updated: Optional[str] = None  # ISO date of the last `leaps update`
    iv_history: list[IvReading] = field(default_factory=list)
    profit_target_multiplier: float = 1.5
    days_before_expiry_exit: int = 90
    status: str = "ACTIVE"     # "ACTIVE" or "CLOSED"
    closed_at: Optional[str] = None
    close_price: Optional[float] = None
    realized_pnl: Optional[float] = None

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


@dataclass
class LeapsBook:
    positions: list[LeapsPosition] = field(default_factory=list)

    def add_position(self, position: LeapsPosition) -> None:
        self.positions.append(position)

    def find(self, position_id: str) -> Optional[LeapsPosition]:
        return self._find(position_id)

    def _find(self, position_id: str) -> Optional[LeapsPosition]:
        for p in self.positions:
            if p.id == position_id:
                return p
        return None

    def close_position(self, position_id: str, close_price: Optional[float] = None) -> tuple[bool, str]:
        pos = self._find(position_id)
        if pos is None:
            return False, f"No LEAPS position found with id {position_id}."
        if pos.status == "CLOSED":
            return False, f"Position {position_id} is already closed (closed_at={pos.closed_at})."
        pos.status = "CLOSED"
        pos.closed_at = date.today().isoformat()
        if close_price is not None:
            pos.close_price = close_price
            pos.realized_pnl = (close_price - pos.premium) * 100 * pos.contracts
        return True, f"Closed {pos.ticker} {pos.option_type} ${pos.strike} exp {pos.expiration} (id={position_id})."

    def active_positions(self) -> list[LeapsPosition]:
        return [p for p in self.positions if p.status == "ACTIVE"]

    def closed_positions(self) -> list[LeapsPosition]:
        return [p for p in self.positions if p.status == "CLOSED"]


def new_position_id() -> str:
    return uuid.uuid4().hex[:8]


def load_leaps() -> LeapsBook:
    """Load LEAPS positions from local JSON. No Google Sheets routing — JSON-only."""
    if not LEAPS_FILE.exists():
        return LeapsBook()
    try:
        with LEAPS_FILE.open() as f:
            data = json.load(f)
        positions = [
            LeapsPosition(
                id=p["id"],
                ticker=p["ticker"],
                option_type=p["option_type"],
                strike=p["strike"],
                expiration=p["expiration"],
                premium=p["premium"],
                contracts=p.get("contracts", 1),
                entry_date=p.get("entry_date", ""),
                entry_stock_price=p.get("entry_stock_price", 0.0),
                entry_delta=p.get("entry_delta"),
                entry_theta=p.get("entry_theta"),
                entry_iv=p.get("entry_iv"),
                current_delta=p.get("current_delta"),
                current_theta=p.get("current_theta"),
                current_iv=p.get("current_iv"),
                last_updated=p.get("last_updated"),
                iv_history=[IvReading(**r) for r in p.get("iv_history", [])],
                profit_target_multiplier=p.get("profit_target_multiplier", 1.5),
                days_before_expiry_exit=p.get("days_before_expiry_exit", 90),
                status=p.get("status", "ACTIVE"),
                closed_at=p.get("closed_at"),
                close_price=p.get("close_price"),
                realized_pnl=p.get("realized_pnl"),
            )
            for p in data.get("positions", [])
        ]
        return LeapsBook(positions=positions)
    except (json.JSONDecodeError, KeyError):
        return LeapsBook()


def save_leaps(book: LeapsBook) -> None:
    ensure_config_dir()
    data = dataclasses.asdict(book)
    with LEAPS_FILE.open("w") as f:
        json.dump(data, f, indent=2)
