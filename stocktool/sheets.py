"""Google Sheets backend for portfolio persistence."""
from __future__ import annotations

from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from .config import CREDENTIALS_FILE, GOOGLE_SHEET_ID, ENV_FILE
from .portfolio import Portfolio, Position

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER_ROW = ["ticker", "shares", "cost_basis", "target_weight", "is_etf"]
OLD_HEADER_ROW = ["ticker", "shares", "cost_basis", "target_weight"]


def get_sheets_client() -> gspread.Client:
    """Authenticate with Google using service account credentials."""
    creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=SCOPES)
    return gspread.authorize(creds)


def _write_sheet_id_to_env(sheet_id: str) -> None:
    """Write the Google Sheet ID back to .env so it persists."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"GOOGLE_SHEETS_CREDENTIALS_FILE={CREDENTIALS_FILE}\nGOOGLE_SHEET_ID={sheet_id}\n")
        return

    lines = ENV_FILE.read_text().splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith("GOOGLE_SHEET_ID"):
            new_lines.append(f"GOOGLE_SHEET_ID={sheet_id}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"GOOGLE_SHEET_ID={sheet_id}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n")


def ensure_sheet(client: gspread.Client) -> gspread.Worksheet:
    """Open existing sheet or create a new one. Returns the first worksheet."""
    if GOOGLE_SHEET_ID:
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        worksheet = spreadsheet.sheet1
        # Ensure header row exists, migrate if needed
        first_row = worksheet.row_values(1)
        if first_row == OLD_HEADER_ROW:
            # Migration: add is_etf column
            worksheet.update("E1", [["is_etf"]])
            num_rows = len(worksheet.get_all_values()) - 1
            if num_rows > 0:
                worksheet.update(f"E2:E{num_rows + 1}", [["FALSE"]] * num_rows)
        elif first_row != HEADER_ROW:
            worksheet.update("A1:E1", [HEADER_ROW])
        return worksheet

    # Create new spreadsheet
    spreadsheet = client.create("Stocktool Portfolio")
    worksheet = spreadsheet.sheet1
    worksheet.update("A1:E1", [HEADER_ROW])
    sheet_id = spreadsheet.id
    _write_sheet_id_to_env(sheet_id)

    # Update the module-level constant so subsequent calls in the same session work
    import stocktool.config as cfg
    cfg.GOOGLE_SHEET_ID = sheet_id

    from rich.console import Console
    Console().print(
        f"[green]Created Google Sheet:[/green] https://docs.google.com/spreadsheets/d/{sheet_id}"
    )
    return worksheet


def load_portfolio_from_sheet() -> Portfolio:
    """Read all rows from the Google Sheet and return a Portfolio."""
    client = get_sheets_client()
    worksheet = ensure_sheet(client)
    records = worksheet.get_all_records()

    positions = []
    for row in records:
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        shares = float(row.get("shares", 0))
        cost_basis = float(row.get("cost_basis", 0))
        tw = row.get("target_weight", "")
        target_weight: Optional[float] = None
        if tw != "" and tw is not None:
            try:
                target_weight = float(tw)
            except (ValueError, TypeError):
                pass
        is_etf_raw = row.get("is_etf", "")
        is_etf = str(is_etf_raw).upper() in ("TRUE", "1", "YES")

        positions.append(Position(
            ticker=ticker,
            shares=shares,
            cost_basis=cost_basis,
            target_weight=target_weight,
            is_etf=is_etf,
        ))
    return Portfolio(positions=positions)


def save_portfolio_to_sheet(portfolio: Portfolio) -> None:
    """Clear and rewrite all positions to the Google Sheet."""
    client = get_sheets_client()
    worksheet = ensure_sheet(client)

    # Clear data rows (keep header)
    worksheet.batch_clear(["A2:E1000"])

    if not portfolio.positions:
        return

    rows = []
    for pos in portfolio.positions:
        rows.append([
            pos.ticker,
            pos.shares,
            pos.cost_basis,
            pos.target_weight if pos.target_weight is not None else "",
            pos.is_etf,
        ])
    end_col = "E"
    end_row = len(rows) + 1
    worksheet.update(f"A2:{end_col}{end_row}", rows)


def sync_position(ticker: str, shares: float, cost_basis: float,
                  target_weight: Optional[float] = None,
                  is_etf: bool = False) -> None:
    """Upsert a single row by ticker."""
    client = get_sheets_client()
    worksheet = ensure_sheet(client)
    ticker = ticker.upper()

    # Find existing row
    try:
        cell = worksheet.find(ticker, in_column=1)
    except gspread.exceptions.CellNotFound:
        cell = None

    row_data = [ticker, shares, cost_basis,
                target_weight if target_weight is not None else "", is_etf]
    if cell:
        row_num = cell.row
        worksheet.update(f"A{row_num}:E{row_num}", [row_data])
    else:
        worksheet.append_row(row_data)


def remove_position_from_sheet(ticker: str) -> bool:
    """Delete a row by ticker. Returns True if found and removed."""
    client = get_sheets_client()
    worksheet = ensure_sheet(client)
    ticker = ticker.upper()

    try:
        cell = worksheet.find(ticker, in_column=1)
    except gspread.exceptions.CellNotFound:
        return False

    worksheet.delete_rows(cell.row)
    return True
