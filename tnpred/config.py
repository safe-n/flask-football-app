"""Konfiguracja ze zmiennych środowiskowych (.env). Żadnych kluczy w kodzie.

Nazwy zmiennych tenisowych mają przedrostek TN_, żeby aplikacja mogła działać w TEJ SAMEJ usłudze Render co football
(wspólne są tylko GITHUB_TOKEN i GITHUB_REPO - dziennik tenisa trafia do osobnego folderu `tennis/` w gałęzi ledger-data).
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv opcjonalny
    pass

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else ROOT / p


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on", "tak")


def auto_bootstrap_default(env=None) -> bool:
    """TN_AUTO_BOOTSTRAP: 1/0. Bez ustawienia: włączone na Render (RENDER=true)."""
    env = os.environ if env is None else env
    v = (env.get("TN_AUTO_BOOTSTRAP") or "").strip().lower()
    if v:
        return v in ("1", "true", "yes", "on", "tak")
    return env.get("RENDER") == "true"


DB_PATH = _path("TN_DB_PATH", "data/tennis.db")
HISTORY_DIR = _path("TN_HISTORY_DIR", "tennis_history")      # CSV w repo (1 plik = tour + rok), ładowane przy starcie
PARAMS_DIR = _path("TN_PARAMS_DIR", "tennis_params")         # parametry modelu (serwis bazowy, waga rynku) - śledzone w gicie
AUTO_BOOTSTRAP = auto_bootstrap_default()
TOURS = [t.strip().upper() for t in os.getenv("TN_TOURS", "ATP,WTA").split(",") if t.strip()]
YEARS = int(os.getenv("TN_YEARS", "5"))                       # ile ostatnich sezonów pobrać
REFRESH_HOURS = float(os.getenv("TN_REFRESH_HOURS", "12"))    # co ile godzin odświeżać wyniki (0 = wyłączone)
DEMO = _flag("TN_DEMO")                                        # dane syntetyczne (tylko do podglądu / testów)

# tennis-data.co.uk (darmowe XLSX z wynikami po setach i kursami). {year} zostanie podstawione.
# Strona dodała do ścieżki losowy człon (stan na 30.10.2026). Gdy znów go zmieni, aplikacja sama odczyta nowe linki
# ze strony TDATA_INDEX_URL; można też podać wzór ręcznie w TN_TDATA_ATP_URL / TN_TDATA_WTA_URL.
TDATA_ATP_URL = os.getenv("TN_TDATA_ATP_URL", "https://tennis-data.co.uk/hrjk-85HytOjkhth76j_ygh4jf7/{year}/{year}.xlsx")
TDATA_WTA_URL = os.getenv("TN_TDATA_WTA_URL", "https://tennis-data.co.uk/hrjk-85HytOjkhth76j_ygh4jf7/{year}w/{year}.xlsx")
TDATA_INDEX_URL = os.getenv("TN_TDATA_INDEX_URL", "https://tennis-data.co.uk/alldata.php")

# The Odds API (opcjonalnie; darmowy plan ~500 kredytów/mies.). Koszt jednego zapytania = liczba rynków × liczba regionów.
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_REGIONS = os.getenv("TN_ODDS_REGIONS", "eu")
ODDS_MARKETS = os.getenv("TN_ODDS_MARKETS", "h2h")             # np. "h2h,totals,spreads" (3× droższe, nie zawsze dostępne)
ODDS_REFRESH_HOURS = float(os.getenv("TN_ODDS_REFRESH_HOURS", "12"))
ODDS_MONTHLY_BUDGET = int(os.getenv("TN_ODDS_BUDGET", "450"))  # zostaw zapas z 500

# Model
ELO_SURFACE_WEIGHT = float(os.getenv("TN_ELO_SURFACE_WEIGHT", "0.5"))  # 0 = tylko ogólne Elo, 1 = tylko nawierzchnia
ELO_USE_RETIRED = _flag("TN_ELO_USE_RETIRED")                          # mecze skreczowane w Elo (domyślnie nie)
# Strojenie w aplikacji: kilka minut CPU na darmowym Renderze (0,1 CPU) blokowało stronę -> na Renderze domyślnie wyłączone.
AUTOTUNE = _flag("TN_AUTOTUNE", "0" if os.getenv("RENDER") == "true" else "1")
HL_PP = float(os.getenv("TN_HL_PP", "8"))                               # próg kolorowania kafelków (pp)
LOG_HORIZON_DAYS = int(os.getenv("TN_LOG_HORIZON_DAYS", "4"))

# Trwałość (jak w football): CSV w osobnej gałęzi repo przez GitHub REST API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
LEDGER_BRANCH = os.getenv("TN_LEDGER_BRANCH", os.getenv("LEDGER_BRANCH", "ledger-data"))
LEDGER_PREFIX = os.getenv("TN_LEDGER_PREFIX", "tennis/")      # folder w gałęzi - nie miesza się z plikami football

# Gdy tenis jest zamontowany w aplikacji football (combo.py) - link powrotny w menu
FOOTBALL_LINK = os.getenv("TN_FOOTBALL_LINK", "")
