"""Project-wide configuration."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LEGACY_SQLITE_MARKET_DB_PATH = DATA_DIR / "market.db"
ENV_PATH = PROJECT_ROOT / ".env"
KRONOS_MODEL_VARIANT = "small"  # mini/small/base
KRONOS_DEVICE = "cpu"
KRONOS_PRED_LEN = 5
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
US_DATA_PROVIDER = os.getenv("OPENSTOCKAGENT_US_DATA_PROVIDER", "polygon")

DATA_DIR.mkdir(exist_ok=True)


def reload_local_env() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


reload_local_env()
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", POLYGON_API_KEY)
US_DATA_PROVIDER = os.getenv("OPENSTOCKAGENT_US_DATA_PROVIDER", US_DATA_PROVIDER)
