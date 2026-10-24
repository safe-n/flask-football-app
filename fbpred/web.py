"""Aplikacja Flask: mecze, podgląd meczu, statystyki sędziów/drużyn, tabela, siła drużyn, dziennik, dane + JSON API."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from flask import Flask, abort, jsonify, render_template, request

from . import bootstrap, config, db, draws, gh_store, history, ledger, leagues as lg_cat, params as prm, recent as recent_mod, stats
from .odds import apply_blend, value_picks
from .simulate import simulate_table

TTL = 3600


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def match_sections(p: dict) -> tuple[dict, list[tuple[str, list]], list[str]]:
    """Przygotowuje podgląd meczu (nagłówek + sekcje tabelek) z prognozy - osobno od szablonu, żeby dało się testować."""
    e, g = p["extra"], p["goals"]
    head = {"title": f"{p['home']} – {p['away']}",
            "sub": f"oczekiwane gole {p['xg']['home']}–{p['xg']['away']}" + (f" · sędzia {p['referee']}" if p.get("referee") else "")
                   + (f" · brak historii: {', '.join(p['unknown_teams'])}" if p["unknown_teams"] else ""),
            "x12": [(k, _pct(p["1x2"][k])) for k in "1X2"]}
    S: list[tuple[str, list]] = [
        ("Gole", [("Over 1.5", _pct(g["over_1.5"])), ("Over 2.5", _pct(g["over_2.5"])), ("Over 3.5", _pct(g["over_3.5"])),
                  ("BTTS tak", _pct(g["btts_yes"]))] + [(f"wynik {s}", _pct(q)) for s, q in g["top_scores"][:3]]),
        ("Podwójna szansa / DNB", [(k, _pct(v)) for k, v in e["double_chance"].items()] +
         [("DNB gospodarz", _pct(e["dnb"]["home"])), ("DNB gość", _pct(e["dnb"]["away"]))]),
        ("Czyste konto / do zera", [("Gospodarz czyste konto", _pct(e["clean_sheets"]["home_cs"])),
                                    ("Gość czyste konto", _pct(e["clean_sheets"]["away_cs"])),
                                    ("Gospodarz wygra do zera", _pct(e["clean_sheets"]["home_win_to_nil"])),
                                    ("Gość wygra do zera", _pct(e["clean_sheets"]["away_win_to_nil"]))]),
        ("Handicap gospodarzy (wygrana)", [(k, _pct(e["asian"][k]["win"])) for k in ("-1.5", "-0.5", "0.5", "1.5")]),
    ]
    if "halves" in p:
        h = p["halves"]
        best = sorted(h["htft"].items(), key=lambda kv: -kv[1])[:4]
        S.append(("Połowy", [("Remis do przerwy", _pct(h["draw_ht"])), ("Remis w 2. połowie", _pct(h["draw_2h"])),
                             ("Remis w którejkolwiek", _pct(h["draw_either_half"])), ("Remis w obu", _pct(h["draw_both_halves"])),
                             ("Gol w 1. połowie", _pct(h["over_0.5_ht"]))]))
        S.append(("Remisy: HT / FT", [("Remis do przerwy LUB na koniec", _pct(h["draw_ht_or_ft"])),
                                      ("Remis w 1. LUB 2. połowie", _pct(h["draw_either_half"])),
                                      ("Remis na koniec meczu", _pct(h["draw_ft"])), ("Remis do przerwy i na koniec", _pct(h["htft"]["X/X"]))]))
        S.append(("Połowa/mecz (najczęstsze)", [(k, _pct(v)) for k, v in best]))
    for key, title in (("yellow", "Żółte kartki"), ("corners", "Rzuty rożne")):
        if key in p:
            c = p[key]
            S.append((f"{title} (śr. {c['total_mean']} = {c['home_mean']} + {c['away_mean']})",
                      [(f"Over {k}", _pct(v)) for k, v in c["over"].items()] +
                      [("Gospodarz więcej", _pct(c["more_than_opponent"]["home"])), ("Gość więcej", _pct(c["more_than_opponent"]["away"]))]))
    if "rest" in p or "manual_adj" in p:
        rows = []
        if "rest" in p:
            rs = p["rest"]
            for side, lab in (("home", "Gospodarz"), ("away", "Gość")):
                days = rs[f"{side}_days"]
                tag = " (Liga Mistrzów)" if rs[f"{side}_tag"] == "CL" else ""
                rows.append((f"{lab}: dni od ostatniego meczu", "brak danych" if days is None else f"{days}{tag}" + ("  ⚠" if rs[f"{side}_short"] else "")))
            if rs["factors"] != (1.0, 1.0):
                rows.append(("Korekta zmęczenia xG (test)", f"×{rs['factors'][0]} / ×{rs['factors'][1]}"))
        if "manual_adj" in p:
            rows.append(("Ręczna korekta xG", f"×{p['manual_adj'][0]} / ×{p['manual_adj'][1]}"))
        S.insert(0, ("Odpoczynek i korekty", rows))
    notes = [] if "yellow" in p else ["Brak statystyk kartek/rożnych w danych tej ligi (np. Liga Mistrzów z darmowego źródła ich nie zawiera)."]
    return head, S, notes


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

    def league_options() -> list[tuple[str, str]]:
        conn = db.connect(config.DB_PATH)
        codes = [r[0] for r in conn.execute("SELECT DISTINCT league FROM matches ORDER BY 1")]
        return [(c, lg_cat.label(c)) for c in codes]

    def page(title, league, *blocks, refresh=False):
        return render_template("page.html", title=title, league=league, leagues=league_options(), blocks=blocks,
                               refresh=refresh, fmt=lambda x: f"{x:.2f}".rstrip("0").rstrip(".") if abs(x) < 1e6 else str(x))

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
                pred = apply_blend(P.predict(r["home"], r["away"], r.get("referee"), date=r["date"]), r, p["blend_w"])
                items.append({"row": r, "p": pred, "picks": value_picks(pred, r)})
        return render_template("index.html", items=items, league=league, leagues=league_options(),
                               title=f"Mecze · {lg_cat.name(league)}")

    @app.get("/match")
    def match():
        league = league_arg()
        P, _, df = model(league)
        teams = [t for t in stats.active_teams(df) if t in P.teams]
        home = request.args.get("home") or (teams[0] if teams else "")
        away = request.args.get("away") or (teams[1] if len(teams) > 1 else "")
        referee = request.args.get("referee") or None
        date = request.args.get("date") or None
        try:
            adj_h, adj_a = float(request.args.get("adj_h", 1.0)), float(request.args.get("adj_a", 1.0))
        except ValueError:
            adj_h = adj_a = 1.0
        recent = stats.season_slice(df, 2)
        refs = sorted(recent["referee"].dropna().unique()) if "referee" in recent else []
        ctx = dict(title=f"Podgląd meczu · {lg_cat.name(league)}", league=league, leagues=league_options(), teams=teams,
                   referees=refs, home=home, away=away, referee=referee, head=None, sections=[], notes=[],
                   date=date or "", adj_h=adj_h, adj_a=adj_a, adj_opts=[0.7, 0.8, 0.9, 1.0, 1.1, 1.2])
        if request.args.get("home") and request.args.get("away") and home != away:
            if home not in P.teams or away not in P.teams:
                abort(404, f"Nieznana drużyna: {home if home not in P.teams else away}")
            head, sections, notes = match_sections(P.predict(home, away, referee, date=date, adj=(adj_h, adj_a)))
            ctx.update(head=head, sections=sections, notes=notes)
        return render_template("match.html", **ctx)

    @app.get("/draws")
    def draws_page():
        league = league_arg()
        market = request.args.get("market", "ht_or_ft")
        days = max(1, min(int(request.args.get("days", 7)), 30))
        if market not in draws.MARKETS:
            abort(400, f"Nieznany rynek. Dostępne: {', '.join(draws.MARKETS)}")
        P, p, df = model(league)
        up = db.load_upcoming(db.connect(config.DB_PATH), league)
        title = draws.MARKETS[market][0]
        tabs = ("tabs", [(lab.split(" ", 1)[1] if False else lab, f"/draws?league={league}&market={k}&days={days}")
                         for k, (lab, _) in draws.MARKETS.items()])
        base = draws.base_rates(df).get(market)
        note = ("p", f"{title}. Średnia ligi z historii: {100 * base:.1f}%. " if base else f"{title}. ")
        note = ("p", note[1] + "kurs_fair = 1/prawdopodobieństwo (bez marży bukmachera) - stawiaj tylko, gdy kurs u bukmachera jest "
                "wyraźnie wyższy. 'vs_liga_pp' = o ile punktów proc. powyżej średniej ligi.")
        if any((p.get("draw_shift") or {}).values()):
            note = ("p", note[1] + f" Zastosowano kalibrację z tune: {p['draw_shift']}.")
        t = draws.draw_table(P, df, up, market, days)
        if t.empty:
            return page("Remisy", league, tabs, ("p", f"Brak nadchodzących meczów w ciągu {days} dni (zajrzyj na stronę Dane)."))
        return page(f"Remisy · {lg_cat.name(league)}", league, tabs, note, ("t", t))

    @app.get("/stats")
    def stats_page():
        league = league_arg()
        view = request.args.get("view", "referees")
        seasons = max(1, min(int(request.args.get("seasons", 2 if view == "referees" else 1)), 6))
        P, _, df = model(league)
        base = f"/stats?league={league}"
        tabs = ("tabs", [("Sędziowie", f"{base}&view=referees&seasons=2"), ("Drużyny: kartki i rożne", f"{base}&view=teams&seasons=1"),
                         ("(więcej sezonów)", f"{base}&view={view}&seasons=3")])
        if view == "teams":
            t = stats.team_table(df, P, seasons)
            note = ("p", f"Średnie na mecz z ostatnich {seasons} sezonów. kartki_x / rozne_x to mnożniki z modelu (1.0 = średnia ligi, "
                         "skorygowane o rywali; większe = więcej kartek/rożnych).")
        else:
            t = stats.referee_table(df, P, seasons)
            note = ("p", f"Sędziowie z min. 8 meczami w ostatnich {seasons} sezonach. mnoznik_model uwzględnia małą próbę "
                         "(shrinkage), więc jest ostrożniejszy niż surowa średnia.")
        if t.empty:
            return page("Statystyki", league, tabs, ("p", "Brak statystyk kartek/rożnych/sędziów w danych tej ligi."))
        return page(f"Statystyki · {lg_cat.name(league)}", league, tabs, note, ("t", t))

    @app.get("/table")
    def table():
        league = league_arg()
        P, _, df = model(league)
        up = db.load_upcoming(db.connect(config.DB_PATH), league)
        tab, info = cached(("sim", league), lambda: simulate_table(df, P, up, n=4000))
        return page(f"Symulacja tabeli · {lg_cat.name(league)}", league,
                    ("p", f"Sezon {lg_cat.season_label(info['sezon'])}: zostało {info['pozostalo_meczow']} meczów "
                          f"({info['metoda']}), {info['symulacji']} symulacji Monte Carlo."), ("t", tab))

    @app.get("/strengths")
    def strengths():
        league = league_arg()
        P, p, df = model(league)
        s = P.goals.strengths().reset_index().rename(columns={"index": "druzyna"})
        active = set(stats.active_teams(df))
        s = s[s["druzyna"].isin(active)]
        return page(f"Siła drużyn · {lg_cat.name(league)}", league,
                    ("p", f"Tylko drużyny z bieżącego sezonu. Przewaga domowa: {np.exp(P.goals.ha):.2f}x goli. "
                          f"ridge={p['ridge']}, xi={p['xi']}, shot_weight={p.get('shot_weight', 0)}."), ("t", s))

    @app.get("/recent")
    def recent_page():
        league = league_arg()
        days = max(3, min(int(request.args.get("days", 10)), 30))
        P, p, df = model(league)

        def build():
            return recent_mod.recent_predictions(df, days, ridge=p["ridge"], xi=p["xi"], shot_weight=p.get("shot_weight", 0.0),
                                                 calib=p.get("draw_shift") or None)
        res = cached(("recent", league, days), build)
        if res.empty:
            return page("Ostatnie mecze", league, ("p", f"Brak rozegranych meczów z ostatnich {days} dni w bazie."))
        tabs = ("tabs", [(f"{d} dni", f"/recent?league={league}&days={d}") for d in (7, 14, 30)])
        return page(f"Ostatnie mecze · {lg_cat.name(league)}", league, tabs,
                    ("p", "Retrospektywa: model uczony wyłącznie na meczach sprzed danej kolejki (bez zaglądania w przyszłość). "
                          "To nie jest dziennik na żywo, tylko podgląd, jak model poradziłby sobie z ostatnimi meczami."),
                    ("p", recent_mod.summary(res)), ("t", recent_mod.show_table(res).iloc[::-1].reset_index(drop=True)))

    @app.get("/track")
    def track():
        league = league_arg()
        conn = db.connect(config.DB_PATH)
        st = ledger.stats(conn, league)
        d = bootstrap.DIAG.get("dziennik", {})
        diag = ("p", f"W bazie: {st['w_bazie']} prognoz (rozliczone {st['rozliczone']}, oczekujące {st['oczekujace']}). "
                     f"Trwałość: {d.get('trwalosc', 'brak informacji (odświeżanie jeszcze się nie wykonało)')}. "
                     f"Ostatni zapis do GitHuba: {d.get('zapis', '-')}.")
        s = ledger.settled(conn, league)
        if s.empty:
            why = ("Dziennik zapisuje prognozę PRZED meczem i rozlicza ją, gdy pojawi się wynik. Mecze, które odbyły się, zanim "
                   "prognozy zaczęły być zapisywane (albo zanim dziennik stał się trwały), nie trafią tu wstecznie - zobacz "
                   "zakładkę Ostatnie mecze, która pokazuje retrospektywę. " +
                   ("" if gh_store.enabled() else "UWAGA: trwałość dziennika jest wyłączona (brak GITHUB_TOKEN/GITHUB_REPO), "
                                                  "więc dziennik znika przy każdym restarcie serwisu."))
            return page("Dziennik prognoz", league, diag, ("p", why),
                        ("tabs", [("Zobacz ostatnie mecze (retrospektywa)", f"/recent?league={league}")]))
        hist = db.load_matches(conn, league)
        hist = hist[~hist["fixture_id"].isin(s["fixture_id"])]
        tab, sim = ledger.track_summary(s, base=ledger.league_base_rates(hist))
        return page("Dziennik prognoz", league, diag,
                    ("p", f"Rozliczone: {len(s)}, oczekujące: {ledger.pending(conn, league)}. Log-loss: mniej = lepiej."),
                    ("t", tab), ("p", f"Symulacja typów: {sim}"))

    @app.get("/data")
    def data_page():
        league = league_arg()
        conn = db.connect(config.DB_PATH)
        q = pd.read_sql_query(
            "SELECT league AS liga, season AS sezon, COUNT(*) AS mecze, SUM(hg IS NOT NULL) AS rozegrane, "
            "SUM(hg IS NULL) AS nadchodzace, MIN(date) AS od, MAX(date) AS do, "
            "ROUND(100.0*SUM(hg_ht IS NOT NULL)/COUNT(*)) AS 'HT_%', ROUND(100.0*SUM(h_yellow IS NOT NULL)/COUNT(*)) AS 'kartki_%', "
            "ROUND(100.0*SUM(h_sot IS NOT NULL)/COUNT(*)) AS 'sot_%', ROUND(100.0*SUM(o_home IS NOT NULL)/COUNT(*)) AS 'kursy_%' "
            "FROM matches GROUP BY league, season ORDER BY league, season", conn)
        diag = pd.DataFrame([{"liga": lg, "krok": k, "wynik": v} for lg, d in bootstrap.DIAG.items() for k, v in d.items()])
        hist = history.status(config.HISTORY_DIR)
        blocks = [("p", f"Stan zasilania: {bootstrap.STATUS['state']} - {bootstrap.STATUS['message']}"),
                  ("p", "Konfiguracja: " + ", ".join(f"{k}={v}" for k, v in bootstrap.describe().items()))]
        if not config.AUTO_BOOTSTRAP:
            blocks.append(("p", "Odświeżanie z internetu jest WYŁĄCZONE. Ustaw AUTO_BOOTSTRAP=1 w Render → Environment "
                                "(render.yaml działa tylko dla usług utworzonych z Blueprintu). Dane z history/ i tak działają."))
        if not diag.empty:
            blocks += [("h", "Diagnostyka ostatniego odświeżenia (skąd bierze się terminarz)"), ("t", diag)]
        blocks += [("h", "Baza w pamięci serwisu (SQLite)"), ("t", q)]
        if not hist.empty:
            blocks += [("h", f"Historia w repo ({config.HISTORY_DIR})"), ("t", hist)]
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
