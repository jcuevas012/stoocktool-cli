from pathlib import Path

from dotenv import load_dotenv
import os

# Load .env from project root (two levels up from this file, or cwd)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # fallback: search cwd and parents

CONFIG_DIR = Path.home() / ".config" / "stocktool"
PORTFOLIO_FILE = CONFIG_DIR / "portfolio.json"

DEFAULT_HORIZON_DAYS = 90

VIX_TICKER = "^VIX"
MARGIN_RULES = [
    (40, 0.65, "EXTREME FEAR"),
    (35, 0.45, "HIGH FEAR"),
    (30, 0.25, "ELEVATED"),
]

# Google Sheets settings
CREDENTIALS_FILE = Path(
    os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE", str(CONFIG_DIR / "credentials.json"))
).expanduser()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
ENV_FILE = _env_path


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def sheets_configured() -> bool:
    """Return True if Google Sheets credentials exist on disk."""
    return CREDENTIALS_FILE.exists()
