"""Aplikacja Flask: prognozy nadchodzących meczów, symulacja tabeli, dziennik, siła drużyn + JSON API."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from flask import Flask, abort, jsonify, render_template, request

from . import bootstrap, config, db, history, ledger, params as prm
from .odds import apply_blend, value_picks
from .simulate import simulate_table

TTL = 3600


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(config.ROOT / "templates"))
    try:
        bootstrap.load_local()        # historia z CSV -> SQLite od razu (offline), niezależnie od AUTO_BOOTSTRAP
    except Exception as e:  # noqa: BLE001 - błąd odczytu historii nie może zablokować startu serwera
        print(f"[bootstrap] load_local nie powiodło się: {e}", flush=True)
    if config.AUTO_BOOTSTRAP:
        bootstrap.start_background()
    else:
        print("[bootstrap] AUTO_BOOTSTRAP wyłączony - brak odświeżania z internetu (dane z history/ wczytane)", flush=True)
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
                if config.AUTO_BOOTSTRAP and bootstrap.STATUS["state"] in ("idle", "loading"):
                    abort(503, bootstrap.STATUS["message"])
                abort(404, f"Brak danych dla ligi {league}. Uruchom: python -m fbpred fetch-csv --league {league}")
            P, p = prm.build_predictor(df, league)
            return P, p, df
        return cached(("model", league), build)

    def leagues() -> list[str]:
        conn = db.connect(config.DB_PATH)
        return [r[0] for r in conn.execute("SELECT DISTINCT league FROM matches ORDER BY 1")]

    def page(title, league, *blocks, refresh=False):
        return render_template("page.html", title=title, league=league, leagues=leagues(), blocks=blocks,
                               refresh=refresh)

    @app.errorhandler(503)
    @app.errorhandler(404)
    def friendly(e):
        return page("Dane niedostępne" if e.code == 404 else "Ładowanie danych", league_arg(),
                    ("p", getattr(e, "description", str(e))), refresh=e.code == 503), e.code

    @app.get("/")
    def index():
        league = league_arg()
        conn = db.connect(config.DB_PATH)
        if config.AUTO_BOOTSTRAP and bootstrap.count_finished(conn, league) == 0:
            st = bootstrap.STATUS["state"]
            if st in ("idle", "loading"):
                return page("Ładowanie danych", league, ("p", bootstrap.STATUS["message"]), refresh=True), 503
            if st == "error":
                return page("Brak danych", league, ("p", bootstrap.STATUS["message"] + " Ponowię próbę za kilka minut.")), 503
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

    @app.get("/data")
    def data_page():
        league = league_arg()
        conn = db.connect(config.DB_PATH)
        q = pd.read_sql_query(
            "SELECT league AS liga, season AS sezon, COUNT(*) AS mecze, "
            "SUM(hg IS NOT NULL) AS rozegrane, MIN(date) AS od, MAX(date) AS do, "
            "ROUND(100.0*SUM(hg_ht IS NOT NULL)/COUNT(*)) AS 'HT_%', "
            "ROUND(100.0*SUM(h_yellow IS NOT NULL)/COUNT(*)) AS 'kartki_%', "
            "ROUND(100.0*SUM(h_sot IS NOT NULL)/COUNT(*)) AS 'sot_%', "
            "ROUND(100.0*SUM(o_home IS NOT NULL)/COUNT(*)) AS 'kursy_%' "
            "FROM matches GROUP BY league, season ORDER BY league, season", conn)
        hist = history.status(config.HISTORY_DIR)
        blocks = [("p", f"Stan zasilania: {bootstrap.STATUS['state']} - {bootstrap.STATUS['message']}"),
                  ("p", "Konfiguracja: " + ", ".join(f"{k}={v}" for k, v in bootstrap.describe().items())),
                  ("p", "Baza w pamięci serwisu (SQLite):"), ("t", q)]
        if not config.AUTO_BOOTSTRAP:
            blocks.insert(2, ("p", "Odświeżanie z internetu jest WYŁĄCZONE. Ustaw AUTO_BOOTSTRAP=1 w Render → Environment "
                                   "(render.yaml działa tylko dla usług utworzonych z Blueprintu). Dane z history/ i tak działają."))
        if not hist.empty:
            blocks += [("p", f"Historia w repo ({config.HISTORY_DIR}):"), ("t", hist)]
        return page("Dane", league, *blocks)

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
        return {"ok": True, "dane": bootstrap.STATUS}

    return app


app = create_app()  # dla gunicorn: gunicorn fbpred.web:app
