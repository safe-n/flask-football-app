"""Konfiguracja ze zmiennych środowiskowych (.env). Żadnych kluczy w kodzie."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv opcjonalny
    pass

ROOT = Path(__file__).resolve().parent.parent


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else ROOT / p


API_KEY = os.getenv("API_KEY", "")
API_HOST = os.getenv("API_HOST", "api-football-v1.p.rapidapi.com")
API_PROVIDER = os.getenv("API_PROVIDER", "rapidapi")
ODDS_BOOKMAKER_ID = int(os.getenv("ODDS_BOOKMAKER_ID", "8"))
REQUEST_RESERVE = int(os.getenv("REQUEST_RESERVE", "5"))
DB_PATH = _path("DB_PATH", "data/football.db")
CACHE_DIR = _path("CACHE_DIR", "data/cache")
DEFAULT_LEAGUE = os.getenv("DEFAULT_LEAGUE", "E0")
