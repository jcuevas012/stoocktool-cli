from pathlib import Path

from dotenv import load_dotenv
import os

# Load .env from project root (two levels up from this file, or cwd)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # fallback: search cwd and parents

CONFIG_DIR = Path.home() / ".config" / "vstock"
PORTFOLIO_FILE = CONFIG_DIR / "portfolio.json"
MARGIN_STATE_FILE = CONFIG_DIR / "margin_state.json"

DEFAULT_HORIZON_DAYS = 90

VIX_TICKER = "^VIX"

# Personal margin safety rule: never exceed this fraction of portfolio value as total margin
MAX_MARGIN_PCT = 0.25

MARGIN_RULES = [
    (40, 0.65, "EXTREME FEAR"),
    (35, 0.45, "HIGH FEAR"),
    (30, 0.25, "ELEVATED"),
    (28, 0.15, "EARLY WARNING"),
]

# LEAPS tracking (vstock leaps)
LEAPS_FILE = CONFIG_DIR / "leaps.json"
LEAPS_APPROVED_TICKERS = [
    t.strip().upper()
    for t in os.environ.get("LEAPS_APPROVED_TICKERS", "GOOGL,AMZN,MSFT").split(",")
    if t.strip()
]
LEAPS_MIN_DAYS_TO_EXPIRY = 365
LEAPS_LONG_EXPIRY_WARN_DAYS = 730
LEAPS_MIN_ITM_PCT = 15.0
LEAPS_DELTA_WARN_LOW = 0.70
LEAPS_DELTA_WARN_HIGH = 0.90
LEAPS_MAX_POSITION_PCT = 5.0
LEAPS_WARN_POSITION_PCT = 3.0
LEAPS_DEFAULT_PROFIT_TARGET = 1.5
LEAPS_DEFAULT_TIME_STOP_DAYS = 90
# Warn in the `leaps add` wizard if the next earnings date falls within this many days of today
LEAPS_EARNINGS_WARN_DAYS = int(os.environ.get("LEAPS_EARNINGS_WARN_DAYS", "21"))
# Fraction of a position's total life (entry date -> expiration) remaining at which theta decay
# is considered to start accelerating. Grounded in the standard options-pricing heuristic that
# time value decays roughly proportional to sqrt(days remaining) — theta roughly doubles once
# remaining life drops to 1/4 of its value, and "last third of life" is the commonly-cited point
# where daily decay becomes materially faster. Scales to each position's own duration instead of
# reusing the flat LEAPS_DEFAULT_TIME_STOP_DAYS day count for every contract length.
LEAPS_DECAY_ACCELERATION_FRACTION = 1 / 3
# IV-vs-realized-volatility "cheap/fair/expensive" ratio bands (market IV / trailing 1Y
# realized volatility). This is a free-data proxy for IV rank — yfinance has no historical-IV
# series, so realized (actual) volatility stands in for "average IV". Below LEAPS_IV_CHEAP_RATIO,
# options are priced below how much the stock has actually moved; above LEAPS_IV_EXPENSIVE_RATIO,
# you're paying a volatility premium above realized movement.
LEAPS_IV_CHEAP_RATIO = 0.90
LEAPS_IV_EXPENSIVE_RATIO = 1.15
# IV Rank: current IV's position within this position's tracked min/max IV range (not an
# empirical percentile or true 52-week range — yfinance has no historical-IV series).
LEAPS_IV_RANK_MIN_READINGS = 5
LEAPS_IV_RANK_CHEAP_MAX = 30
LEAPS_IV_RANK_NORMAL_MAX = 60
LEAPS_IV_RANK_ELEVATED_MAX = 80
LEAPS_EARNINGS_HISTORY_QUARTERS = 8
# Liquidity rating: spread-of-mid and open interest thresholds. Same 4-tier palette as IV Rank.
LEAPS_LIQUIDITY_TIGHT_SPREAD_PCT = 1.0
LEAPS_LIQUIDITY_MODERATE_SPREAD_PCT = 3.0
LEAPS_LIQUIDITY_WIDE_SPREAD_PCT = 5.0
LEAPS_LIQUIDITY_TIGHT_OI = 500
LEAPS_LIQUIDITY_MODERATE_OI = 100
LEAPS_LIQUIDITY_WIDE_OI = 50

# ---------------------------------------------------------------------------
# LEAPS Decision Analyzer framework (vstock calc leaps)
# This block IS the locked framework: change a rule here, never via a CLI override flag.
# Intentionally separate from the `leaps add` wizard settings above.
# ---------------------------------------------------------------------------
CALC_APPROVED_TICKERS = ["GOOGL", "AMZN", "MSFT", "META", "NVDA", "TSM", "AVGO"]
# Names outside the base list that unlock for real money once NAV reaches their phase.
# Paper mode skips NAV checks, so these never unlock in --paper.
CALC_PHASE_UNLOCK_TICKERS = {"PLTR": 200_000, "TSLA": 300_000}
CALC_DELTA_MIN = 0.75
CALC_DELTA_MAX = 0.85
CALC_DELTA_WARN_MIN = 0.70
CALC_DELTA_WARN_MAX = 0.90
CALC_MIN_DTE = 365
CALC_MAX_POSITION_PCT = 5.0
CALC_EXIT_DAYS_BEFORE_EXPIRY = 90
CALC_PROFIT_TARGET_PCT = 50.0
CALC_STOP_LOSS_PCT = 50.0
# (IV % upper bound, max position % of NAV) — first matching tier wins.
CALC_IV_SIZING = [(40.0, 4.0), (60.0, 3.0), (float("inf"), 1.0)]
CALC_IV_HIGH_PCT = 60.0
CALC_IV_PERCENTILE_MAX = 70.0
CALC_EARNINGS_TRAP_DAYS = 30
# Real-money NAV required per name (phase plan). Names not listed use the Phase 3 default.
CALC_PHASE_THRESHOLDS = {
    "GOOGL": 120_000,
    "AMZN": 120_000,
    "TSM": 150_000,
    "PLTR": 200_000,
    "TSLA": 300_000,
}
CALC_DEFAULT_PHASE_THRESHOLD = 120_000
CALC_MARGIN_MAX_PCT = 10.0
CALC_SPREAD_WARN_PCT = 5.0
CALC_CORRELATION = {
    ("GOOGL", "AMZN"): 0.78,
    ("GOOGL", "MSFT"): 0.75,
    ("GOOGL", "META"): 0.72,
    ("MSFT", "META"): 0.80,
    ("NVDA", "AVGO"): 0.82,
    ("NVDA", "TSM"): 0.74,
    ("AMZN", "MSFT"): 0.70,
    ("AVGO", "TSM"): 0.76,
}
CALC_DEFAULT_CORRELATION = 0.65
CALC_CORRELATION_MAX = 0.70
CALC_SECTORS = {
    "GOOGL": "Communication Services",
    "META": "Communication Services",
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "MSFT": "Software",
    "PLTR": "Software",
    "NVDA": "Semiconductors",
    "AVGO": "Semiconductors",
    "TSM": "Semiconductors",
}
CALC_MIN_SECTORS = 3
CALC_DEFAULT_PRICE_GRID = [0.75, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.35, 1.50]
CALC_HORIZONS = [0, 30, 90, 180]
LEAPS_EVAL_DB = CONFIG_DIR / "leaps_evaluations.db"

# Google Sheets settings
CREDENTIALS_FILE = Path(
    os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE", str(CONFIG_DIR / "credentials.json"))
).expanduser()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
ENV_FILE = _env_path

# Financial Modeling Prep (optional) — supplies true 5-year historical average P/E
# for ETF valuation; the feature falls back to a yfinance-only proxy without a key.
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
FMP_BASE_URL = "https://financialmodelingprep.com/stable"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def sheets_configured() -> bool:
    """Return True if Google Sheets credentials exist on disk."""
    return CREDENTIALS_FILE.exists()


def fmp_configured() -> bool:
    """Return True if an FMP API key is set."""
    return bool(FMP_API_KEY)
