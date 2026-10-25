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
# "auto" (domyślnie) = wszystkie ligi, które mają pliki w history/ (bez DEMO); albo jawna lista "E0,D1,SP1"
BOOTSTRAP_LEAGUES = [x.strip() for x in os.getenv("BOOTSTRAP_LEAGUES", "auto").split(",")
                     if x.strip() and x.strip().lower() != "auto"]
BOOTSTRAP_YEARS = int(os.getenv("BOOTSTRAP_YEARS", "4"))   # ile ostatnich sezonów pobrać
REFRESH_HOURS = float(os.getenv("REFRESH_HOURS", "24"))     # co ile godzin odświeżać (0 = wyłączone)
LEDGER_CSV = _path("LEDGER_CSV", "ledger/predictions.csv")   # dziennik trzymany w repo (trwały, za darmo)

HISTORY_DIR = _path("HISTORY_DIR", "history")                # źródło prawdy: CSV w repo (1 plik = liga+sezon)
ARCHIVE_ODDS = os.getenv("ARCHIVE_ODDS", "0") == "1"          # archiwizuj kursy przedmeczowe (włącza CI)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

FDORG_TOKEN = os.getenv("FOOTBALL_DATA_ORG_TOKEN", "")        # darmowy token z football-data.org (Liga Mistrzów + fallback terminarza)
FDORG_PAUSE = float(os.getenv("FDORG_PAUSE", "6.5"))          # plan darmowy: 10 zapytań/min
LOG_HORIZON_DAYS = int(os.getenv("LOG_HORIZON_DAYS", "10"))   # prognozy do dziennika tylko na najbliższe N dni

# --- trwałość dziennika bez GitHub Actions: aplikacja zapisuje CSV w osobnej gałęzi repo przez GitHub REST API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")                 # token z uprawnieniem Contents: write (tylko dla tego repo!)
GITHUB_REPO = os.getenv("GITHUB_REPO", "")                   # "uzytkownik/nazwa-repo"
LEDGER_BRANCH = os.getenv("LEDGER_BRANCH", "ledger-data")    # osobna gałąź - nie wywołuje redeployu na Renderze
LEDGER_REMOTE_PATH = os.getenv("LEDGER_REMOTE_PATH", "ledger/predictions.csv")

# parametry modelu z `tune` / `fatigue-test --apply`: katalog ŚLEDZONY w gicie (data/ jest ignorowane, więc Render ich nie widział)
PARAMS_DIR = _path("PARAMS_DIR", "params")
