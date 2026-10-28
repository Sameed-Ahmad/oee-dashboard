"""Paths and settings shared across the backend."""
from pathlib import Path

# backend/app/config.py -> backend/app -> backend -> project root
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

DATA_DIR = BACKEND_DIR / "data"
PROCESSED_DATA_DIR = DATA_DIR / "processed"  # shared cache dir for every unit's products, not unit-specific source data

FRONTEND_DIR = PROJECT_ROOT / "frontend"

PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)


def processed_cache_path(slug: str) -> Path:
    return PROCESSED_DATA_DIR / f"{slug}.json"
