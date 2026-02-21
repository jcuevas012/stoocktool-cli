from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "stocktool"
PORTFOLIO_FILE = CONFIG_DIR / "portfolio.json"

DEFAULT_HORIZON_DAYS = 90


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
