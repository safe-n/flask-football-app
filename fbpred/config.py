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

# --- automatyczne zasilanie bazy przy starcie aplikacji (Render itp.)
def auto_bootstrap_default(env=None) -> bool:
    """AUTO_BOOTSTRAP: akceptuje 1/true/yes/on (i 0/false/no/off). Bez ustawienia: włączone na Render (RENDER=true)."""
    env = os.environ if env is None else env
    v = (env.get("AUTO_BOOTSTRAP") or "").strip().lower()
    if v:
        return v in ("1", "true", "yes", "on", "tak")
    return env.get("RENDER") == "true"


AUTO_BOOTSTRAP = auto_bootstrap_default()
BOOTSTRAP_LEAGUES = [x.strip() for x in os.getenv("BOOTSTRAP_LEAGUES", DEFAULT_LEAGUE).split(",") if x.strip()]
BOOTSTRAP_YEARS = int(os.getenv("BOOTSTRAP_YEARS", "4"))   # ile ostatnich sezonów pobrać
REFRESH_HOURS = float(os.getenv("REFRESH_HOURS", "24"))     # co ile godzin odświeżać (0 = wyłączone)
LEDGER_CSV = _path("LEDGER_CSV", "ledger/predictions.csv")   # dziennik trzymany w repo (trwały, za darmo)

HISTORY_DIR = _path("HISTORY_DIR", "history")                # źródło prawdy: CSV w repo (1 plik = liga+sezon)
ARCHIVE_ODDS = os.getenv("ARCHIVE_ODDS", "0") == "1"          # archiwizuj kursy przedmeczowe (włącza CI)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
