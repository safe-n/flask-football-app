"""Parametry modelu per liga (zapisywane przez `tune`, wczytywane automatycznie)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config
from .predictor import MatchPredictor

DEFAULTS = {"ridge": 10.0, "xi": 0.0019, "blend_w": None}


def _file(league: str) -> Path:
    return config.DB_PATH.parent / f"params_{league}.json"


def load(league: str) -> dict:
    p = dict(DEFAULTS)
    f = _file(league)
    if f.exists():
        p.update(json.loads(f.read_text()))
    return p


def save(league: str, params: dict) -> Path:
    f = _file(league)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(params, indent=2))
    return f


def build_predictor(df: pd.DataFrame, league: str, **override) -> tuple[MatchPredictor, dict]:
    p = {**load(league), **{k: v for k, v in override.items() if v is not None}}
    return MatchPredictor(df, ridge=p["ridge"], xi=p["xi"]), p
