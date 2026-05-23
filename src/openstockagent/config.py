"""Project-wide configuration."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "market.db"
KRONOS_MODEL_VARIANT = "small"  # mini/small/base
KRONOS_DEVICE = "cpu"
KRONOS_PRED_LEN = 5

DATA_DIR.mkdir(exist_ok=True)
