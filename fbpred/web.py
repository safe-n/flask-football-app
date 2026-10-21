"""Aplikacja Flask: prognozy nadchodzących meczów, symulacja tabeli, dziennik, siła drużyn + JSON API."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from flask import Flask, abort, jsonify, render_template, request

from . import config, db, ledger, params as prm
from .odds import apply_blend, value_picks
from .simulate import simulate_table

TTL = 3600


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(config.ROOT / "templates"))
    cache: dict[tuple, tuple[float, object]] = {}

    def cached(key: tuple, build):
        hit = cache.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
        val = build()
        cache[key] = (time.time(), val)
        return val

    def league_arg() -> str:
        return request.args.get("league", config.DEFAULT_LEAGUE)

    def model(league: str):
        def build():
            conn = db.connect(config.DB_PATH)
            df = db.load_matches(conn, league)
            if df.empty:
                abort(404, f"Brak danych dla ligi {league}")
            P, p = prm.build_predictor(df, league)
            return P, p, df
        return cached(("model", league), build)

    def leagues() -> list[str]:
        conn = db.connect(config.DB_PATH)
        return [r[0] for r in conn.execute("SELECT DISTINCT league FROM matches ORDER BY 1")]

    def page(title, league, *blocks):
        return render_template("page.html", title=title, league=league, leagues=leagues(), blocks=blocks)

    @app.get("/")
    def index():
        league = league_arg()
        conn = db.connect(config.DB_PATH)
        up = db.load_upcoming(conn, league)
        items = []
        if not up.empty:
            P, p, _ = model(league)
            for r in up.head(40).to_dict("records"):
                pred = apply_blend(P.predict(r["home"], r["away"], r.get("referee")), r, p["blend_w"])
                items.append({"row": r, "p": pred, "picks": value_picks(pred, r)})
        return render_template("index.html", items=items, league=league, leagues=leagues())

    @app.get("/table")
    def table():
        league = league_arg()
        P, _, df = model(league)
        up = db.load_upcoming(db.connect(config.DB_PATH), league)
        tab, info = cached(("sim", league), lambda: simulate_table(df, P, up, n=4000))
        return page("Symulacja tabeli", league,
                    ("p", f"Sezon {info['sezon']}: zostało {info['pozostalo_meczow']} meczów ({info['metoda']}), "
                          f"{info['symulacji']} symulacji Monte Carlo."),
                    ("t", tab))

    @app.get("/strengths")
    def strengths():
        league = league_arg()
        P, p, _ = model(league)
        s = P.goals.strengths().reset_index().rename(columns={"index": "druzyna"})
        return page("Siła drużyn", league,
                    ("p", f"Przewaga domowa: {np.exp(P.goals.ha):.2f}x goli. ridge={p['ridge']}, xi={p['xi']}."),
                    ("t", s))

    @app.get("/track")
    def track():
        league = league_arg()
        conn = db.connect(config.DB_PATH)
        s = ledger.settled(conn, league)
        if s.empty:
            return page("Dziennik prognoz", league,
                        ("p", f"Brak rozliczonych prognoz. Oczekujące: {ledger.pending(conn, league)}. "
                              "Zapisuj prognozy komendą `python -m fbpred log` (albo `daily`)."))
        hist = db.load_matches(conn, league)
        hist = hist[~hist["fixture_id"].isin(s["fixture_id"])]
        tab, sim = ledger.track_summary(s, base=ledger.league_base_rates(hist))
        return page("Dziennik prognoz", league,
                    ("p", f"Rozliczone: {len(s)}, oczekujące: {ledger.pending(conn, league)}. Log-loss: mniej = lepiej."),
                    ("t", tab), ("p", f"Symulacja typów: {sim}"))

    @app.get("/api/predict")
    def api_predict():
        league = league_arg()
        home, away = request.args.get("home"), request.args.get("away")
        if not home or not away:
            abort(400, "Podaj ?home=...&away=...")
        P, _, _ = model(league)
        return jsonify(P.predict(home, away, request.args.get("referee")))

    @app.get("/healthz")
    def health():
        return {"ok": True}

    return app


app = create_app()  # dla gunicorn: gunicorn fbpred.web:app
