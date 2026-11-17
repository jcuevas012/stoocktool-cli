"""SQLite history of `vstock calc leaps --save` evaluations (stdlib sqlite3, append-only)."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from .config import LEAPS_EVAL_DB, ensure_config_dir
from .leaps_calc import LeapsEvaluation, SEVERITY_BLOCKING, SEVERITY_WARNING

_SCHEMA = """
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
    verdict TEXT NOT NULL,
    blocking_failures_json TEXT,
    warnings_json TEXT,
    raw_computation_json TEXT
)
"""


def _connect(db_path: Optional[Path]) -> sqlite3.Connection:
    if db_path is None:
        ensure_config_dir()
        db_path = LEAPS_EVAL_DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def evaluation_to_dict(ev: LeapsEvaluation) -> dict:
    data = dataclasses.asdict(ev)
    data["contract"] = ev.contract_label
    return data


def save_evaluation(ev: LeapsEvaluation, db_path: Optional[Path] = None) -> int:
    inputs, metrics = ev.inputs, ev.metrics
    blocking = [dataclasses.asdict(r) for r in ev.rules if r.severity == SEVERITY_BLOCKING]
    warnings = [dataclasses.asdict(r) for r in ev.rules if r.severity == SEVERITY_WARNING]
    with closing(_connect(db_path)) as conn, conn:
        cursor = conn.execute(
            """INSERT INTO leaps_evaluations (
                ticker, expiration_date, strike, premium, underlying_price, delta, gamma, theta,
                vega, iv, iv_percentile, days_to_expiry, nav_at_eval, position_size_pct,
                breakeven_price, exit_trigger_price, stop_loss_price, verdict,
                blocking_failures_json, warnings_json, raw_computation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                inputs.ticker.upper(), inputs.expiration, inputs.strike, inputs.premium or 0.0,
                inputs.spot, inputs.delta, inputs.gamma, inputs.theta, inputs.vega,
                inputs.iv_pct, inputs.iv_percentile, metrics.days_to_expiry, inputs.nav,
                metrics.position_pct, metrics.breakeven, metrics.exit_price, metrics.stop_price,
                ev.verdict, json.dumps(blocking), json.dumps(warnings),
                json.dumps(evaluation_to_dict(ev), default=str),
            ),
        )
        return int(cursor.lastrowid)


def list_evaluations(
    ticker: Optional[str] = None, limit: int = 20, db_path: Optional[Path] = None
) -> list[dict]:
    query = "SELECT * FROM leaps_evaluations"
    params: list = []
    if ticker:
        query += " WHERE ticker = ?"
        params.append(ticker.upper())
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with closing(_connect(db_path)) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
