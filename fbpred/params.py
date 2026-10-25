"""Parametry modelu per liga (zapisywane przez `tune`, wczytywane automatycznie)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config
from .predictor import MatchPredictor

DEFAULTS = {"ridge": 10.0, "xi": 0.0019, "blend_w": None, "shot_weight": 0.0, "draw_shift": {}, "fatigue": {}}


def _file(league: str) -> Path:
    """Plik do ZAPISU: params/ w repo (commitujesz go, żeby Render używał tych samych ustawień)."""
    return Path(config.PARAMS_DIR) / f"params_{league}.json"


def _sources(league: str) -> list[Path]:
    """Pliki do odczytu: najpierw stara lokalizacja (data/), potem params/ (ma pierwszeństwo)."""
    return [config.DB_PATH.parent / f"params_{league}.json", _file(league)]


def load(league: str) -> dict:
    p = dict(DEFAULTS)
    for f in _sources(league):
        if f.exists():
            p.update(json.loads(f.read_text()))
    return p


def describe(league: str) -> dict:
    """Skąd pochodzą parametry (do strony Dane: czy Render używa dostrojonych, czy domyślnych)."""
    p = load(league)
    used = [str(f) for f in _sources(league) if f.exists()]
    return {"liga": league, "ridge": p["ridge"], "xi": p["xi"], "shot_weight": p.get("shot_weight", 0.0),
            "waga_modelu_vs_rynek": p.get("blend_w"), "korekta_remisow": "tak" if any((p.get("draw_shift") or {}).values()) else "nie",
            "zmeczenie": "tak" if p.get("fatigue") else "nie", "zrodlo": "dostrojone (params/)" if used else "DOMYŚLNE (nie uruchomiono tune lub plik nie jest w repo)"}


def save(league: str, params: dict) -> Path:
    f = _file(league)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(params, indent=2))
    return f


def build_predictor(df: pd.DataFrame, league: str, **override) -> tuple[MatchPredictor, dict]:
    p = {**load(league), **{k: v for k, v in override.items() if v is not None}}
    cal = None
    try:                                           # kalendarz odpoczynku (liga + ewentualnie LM z bazy)
        from . import db, rest
        cal = rest.build_calendar(df, db.connect(config.DB_PATH))
    except Exception:  # noqa: BLE001 - brak kalendarza nie może blokować prognoz
        cal = None
    return MatchPredictor(df, ridge=p["ridge"], xi=p["xi"], shot_weight=p.get("shot_weight", 0.0),
                          calib=p.get("draw_shift") or None, calendar=cal, fatigue=p.get("fatigue") or None), p
