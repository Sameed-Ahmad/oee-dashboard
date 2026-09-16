"""Paths and settings shared across the backend."""
from pathlib import Path

# backend/app/config.py -> backend/app -> backend -> project root
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

DATA_DIR = BACKEND_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

FRONTEND_DIR = PROJECT_ROOT / "frontend"

PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)


def processed_cache_path(slug: str) -> Path:
    return PROCESSED_DATA_DIR / f"{slug}.json"
