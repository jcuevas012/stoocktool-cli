"""Financial Modeling Prep (FMP) client.

Used narrowly for one field yfinance cannot provide: true multi-year historical
average P/E for ETF valuation. Field names below are best-effort guesses from
FMP's `ratios` endpoint (the official docs site blocks automated fetching, so
exact field names could not be verified ahead of time) — the defensive
multi-key lookup exists specifically to degrade gracefully if a guess is wrong.
Re-verify against a live API key if FMP changes its schema.
"""

from __future__ import annotations

from typing import Optional

import requests

from .config import FMP_API_KEY, FMP_BASE_URL, fmp_configured

_PE_FIELD_CANDIDATES = ("priceToEarningsRatio", "peRatio", "priceEarningsRatio")


def _first_float(d: dict, *keys: str) -> Optional[float]:
    for key in keys:
        val = d.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def fetch_historical_pe(
    ticker: str, years: int = 5, timeout: float = 5.0
) -> tuple[Optional[float], Optional[str]]:
    """Fetch the trailing N-year average P/E for a symbol from FMP.

    Returns (avg_pe, error_reason). error_reason is one of:
    None (success), "no_key", "http_error", "rate_limited",
    "empty_response", "no_pe_field" — intended for a note field, not shown
    raw to the end user. Never raises; issues at most one HTTP request.
    """
    if not fmp_configured():
        return None, "no_key"

    try:
        resp = requests.get(
            f"{FMP_BASE_URL}/ratios",
            params={"symbol": ticker, "period": "annual", "limit": years, "apikey": FMP_API_KEY},
            timeout=timeout,
        )
        if resp.status_code == 429:
            return None, "rate_limited"
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None, "http_error"

    if isinstance(data, dict) and "Error Message" in data:
        return None, "rate_limited"
    if not isinstance(data, list) or not data:
        return None, "empty_response"

    values = [pe for row in data if isinstance(row, dict) and (pe := _first_float(row, *_PE_FIELD_CANDIDATES)) is not None]
    if not values:
        return None, "no_pe_field"

    return sum(values) / len(values), None
