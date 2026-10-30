"""Aplikacja Flask (tenis). Działa samodzielnie albo zamontowana pod /tennis w aplikacji football (combo.py)."""
from __future__ import annotations

import json
import threading
import time

import numpy as np
import pandas as pd
from flask import Flask, abort, jsonify, redirect, render_template, request
from markupsafe import escape

from . import __version__, backtest, bets as bets_mod, betmarkets as bm, bootstrap, config, db, features as ft, gh_store, ledger, views as V
from .elo import SURFACES
from .odds import edge, kelly, valid

NAV = [("/", "Mecze"), ("/match", "Mecz"), ("/suggest", "Podpowiedzi"), ("/coupon", "Zestawienie"), ("/ranking", "Ranking Elo"),
       ("/recent", "Ostatnie"), ("/backtest", "Backtest"), ("/track", "Dziennik"), ("/bets", "Moje zakłady"), ("/data", "Dane")]


def _f(x):
    try:
        v = float(str(x).replace(",", "."))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _opts(values, current) -> str:
    return "".join(f'<option {"selected" if v == current else ""}>{v}</option>' for v in values)


def create_app(state: bootstrap.State | None = None, background: bool | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(config.PKG / "templates"))
    st = state or bootstrap.State()
    app.config["TN_STATE"] = st
    try:
        bootstrap.load_local(st)
    except Exception as e:  # noqa: BLE001
        st.step("historia z repo", False, str(e))
    if background if background is not None else config.AUTO_BOOTSTRAP:
        bootstrap.start_background(st)

    cache: dict = {}

    def cached(key, build, ttl=1800):
        k = (key, st.model_version, st.data_version)
        hit = cache.get(k)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        val = build()
        cache.clear() if len(cache) > 64 else None
        cache[k] = (time.time(), val)
        return val

    def render(tpl, title, **kw):
        return render_template(tpl, title=title, nav=NAV, R=request.script_root, version=__version__,
                               football=config.FOOTBALL_LINK, **kw)

    def page(title, *blocks, refresh=False):
        return render("page.html", title, blocks=blocks, refresh=refresh, fmt=lambda x: f"{x:.3f}")

    def model():
        return st.get_model()

    def hl():
        return _f(request.args.get("hl")) or config.HL_PP

    def upcoming_preds(tour: str | None = None):
        def build():
            m = model()
            up = db.load_upcoming(st.conn)
            out = []
            for r in up.to_dict("records"):
                if tour and r["tour"] != tour:
                    continue
                p = m.predict(r["tour"], r["surface"], r["best_of"], r["p1"], r["p2"], r.get("o1"), r.get("o2"))
                out.append((r, p))
            return out
        return cached(("up", tour), build, ttl=600)

    @app.errorhandler(404)
    def nf(e):
        return page("Nie znaleziono", ("p", str(e))), 404

    # ------------------------------------------------------------------ Mecze
    @app.get("/")
    def index():
        tour = (request.args.get("tour") or "").upper() or None
        m = model()
        items = upcoming_preds(tour)
        cards = []
        h = hl()
        last_day = None
        for r, p in items:
            day = str(r["date"])[:10]
            if day != last_day:
                cards.append(f"<h2>{escape(day)}</h2>")
                last_day = day
            line = _f(r.get("total_line"))
            q = {"tour": p["tour"], "surface": p["surface"], "bo": p["best_of"], "p1": p["p1"], "p2": p["p2"], "date": day,
                 "o1": r.get("o1") or "", "o2": r.get("o2") or ""}
            href = request.script_root + "/match?" + "&".join(f"{k}={escape(str(v))}" for k, v in q.items())
            o_txt = (f" · kursy {float(r['o1']):.2f} / {float(r['o2']):.2f}" if valid(r.get("o1"), r.get("o2")) else " · brak kursów")
            legs = []
            for k, who in (("w1", p["p1"]), ("w2", p["p2"])):
                pp = p["m"]["p1"] if k == "w1" else p["m"]["p2"]
                o = bm.book_odds(r, k)
                e = f" ({100 * edge(pp, o):+.0f}%)" if o else ""
                legs.append(V.add_btn(bm.leg_id(p["tour"], day, p["p1"], p["p2"], p["surface"], p["best_of"], k),
                                      f"＋ {V.short(who)} {V.fair(pp)}{e}"))
            src = "ręczny" if r.get("source") == "manual" else ("demo" if r.get("source") == "demo" else "")
            warn = "".join(f'<div class="warn m">⚠ {escape(w)}</div>' for w in p["warn"])
            cards.append(
                f'<div class="match"><div class="hd"><span class="pl">{escape(p["p1"])} <small>vs</small> {escape(p["p2"])}</span>'
                f'<span class="m">{escape(p["tour"])} · {escape(r.get("tournament") or "")} · {escape(p["surface"])} · do {p["best_of"] // 2 + 1} setów{o_txt}'
                f'{" · " + src if src else ""}</span></div>'
                f'<div class="bar2" title="{escape(p["p1"])} {V.pct(p["m"]["p1"])}"><i style="width:{100 * p["m"]["p1"]:.0f}%"></i></div>'
                f'{V.tiles_for(p, line, h)}{V.h2h_row(m.df, p)}'
                f'<div class="pgrow"><span class="lb">forma {escape(V.short(p["p1"]))}</span>{ft.form(m.df, p["tour"], p["p1"], 5)["html"]}</div>'
                f'<div class="pgrow"><span class="lb">forma {escape(V.short(p["p2"]))}</span>{ft.form(m.df, p["tour"], p["p2"], 5)["html"]}</div>'
                f'{warn}<div class="row" style="align-items:center">{"".join(legs)} <a href="{href}">szczegóły →</a>'
                f'{_del_form(r) if r.get("source") == "manual" else ""}</div></div>')
        tabs = [("Wszystkie", "/"), ("ATP", "/?tour=ATP"), ("WTA", "/?tour=WTA")]
        empty = "" if items else (
            '<div class="card"><p class="m">Brak nadchodzących meczów. ' +
            ("Kursy z The Odds API pobierają się co kilka godzin. " if config.ODDS_API_KEY else
             "Nie ustawiono ODDS_API_KEY - dodaj mecz ręcznie poniżej albo policz dowolną parę w zakładce Mecz. ") + "</p></div>")
        legend = ('<p class="small">Kafelki: wartość modelu, pod nią średnia dla touru i nawierzchni (ostatnie 3 lata) albo rynek, w nawiasie różnica w pp. '
                  f'Zielony/czerwony = odchylenie ≥ {h / 2:g} pp, ramka ≥ {h:g} pp (zmień: ?hl=6). H2H i forma: najnowsze z lewej, najedź, by zobaczyć mecz. '
                  '⚑ = faworyt rzadko wygrywa z tym rywalem (mała próba - traktuj jako sygnał do sprawdzenia, nie przewagę). '
                  'Przyciski ＋: uczciwy kurs z modelu, w nawiasie przewaga względem kursu bukmachera z bazy (ujemna = kurs za niski).</p>')
        return page("Mecze", ("tabs", tabs), ("html", "".join(cards) + empty + _manual_form(m) + legend),
                    refresh=st.refreshing and not items)

    def _del_form(r):
        return (f'<form method="post" action="{request.script_root}/upcoming/delete" style="display:inline;margin-left:auto">'
                f'<input type="hidden" name="id" value="{escape(r["id"])}"><button class="m">usuń</button></form>')

    def _manual_form(m):
        opts = "".join(f"<option value='{escape(n)}'>" for t in m.names for n in m.players(t))
        return (f'<details class="card"><summary>＋ Dodaj mecz ręcznie (np. z oferty bukmachera)</summary>'
                f'<form method="post" action="{request.script_root}/upcoming/add" class="form" style="margin-top:8px">'
                f'<div><label>Data</label><input type="date" name="date" required value="{pd.Timestamp.today():%Y-%m-%d}"></div>'
                f'<div><label>Tour</label><select name="tour"><option>ATP</option><option>WTA</option></select></div>'
                f'<div><label>Turniej</label><input name="tournament" placeholder="np. Paris Masters"></div>'
                f'<div><label>Nawierzchnia</label><select name="surface">{"".join(f"<option>{s}</option>" for s in SURFACES)}</select></div>'
                f'<div><label>Do ilu setów</label><select name="bo"><option value="3">2 wygranych (Bo3)</option><option value="5">3 wygranych (Bo5)</option></select></div>'
                f'<div><label>Zawodnik 1</label><input name="p1" list="pl" required placeholder="Sinner J."></div>'
                f'<div><label>Zawodnik 2</label><input name="p2" list="pl" required placeholder="Alcaraz C."></div>'
                f'<div><label>Kurs 1</label><input name="o1" inputmode="decimal"></div><div><label>Kurs 2</label><input name="o2" inputmode="decimal"></div>'
                f'<div><label>Linia gemów</label><input name="total_line" inputmode="decimal" placeholder="22.5"></div>'
                f'<div><label>Kurs over</label><input name="o_over" inputmode="decimal"></div><div><label>Kurs under</label><input name="o_under" inputmode="decimal"></div>'
                f'<div><button>Zapisz mecz</button></div></form><datalist id="pl">{opts}</datalist>'
                f'<p class="small">Wpisz nazwisko jak w bazie (podpowiedzi) albo pełne imię i nazwisko - aplikacja spróbuje dopasować. '
                f'Ręczne mecze zapisują się w GitHubie (jeśli ustawiono token), więc przetrwają restart.</p></details>')

    @app.post("/upcoming/add")
    def upcoming_add():
        f = request.form
        m = model()
        tour = (f.get("tour") or "ATP").upper()
        p1 = m.resolve(tour, f.get("p1", "").strip()) or f.get("p1", "").strip()
        p2 = m.resolve(tour, f.get("p2", "").strip()) or f.get("p2", "").strip()
        if not p1 or not p2 or p1 == p2:
            return page("Błąd", ("p", "Podaj dwóch różnych zawodników.")), 400
        row = {"source": "manual", "tour": tour, "tournament": f.get("tournament") or "", "surface": f.get("surface") or "Hard",
               "best_of": 5 if f.get("bo") == "5" else 3, "date": f.get("date") or f"{pd.Timestamp.today():%Y-%m-%d}",
               "p1": p1, "p2": p2, "o1": _f(f.get("o1")), "o2": _f(f.get("o2")), "total_line": _f(f.get("total_line")),
               "o_over": _f(f.get("o_over")), "o_under": _f(f.get("o_under"))}
        db.upsert_upcoming(st.conn, [row])
        cache.clear()
        bootstrap.log_predictions(st)
        bootstrap.sync_up_bg(st, ("manual", "predictions"))
        return redirect(request.script_root + "/")

    @app.post("/upcoming/delete")
    def upcoming_delete():
        db.delete_upcoming(st.conn, request.form.get("id", ""))
        cache.clear()
        bootstrap.sync_up_bg(st, ("manual",))
        return redirect(request.script_root + "/")

    # ------------------------------------------------------------------ Mecz
    @app.get("/match")
    def match():
        m = model()
        a = request.args
        tour = (a.get("tour") or "ATP").upper()
        surface = a.get("surface") or "Hard"
        bo = 5 if a.get("bo") == "5" else 3
        p1, p2 = (a.get("p1") or "").strip(), (a.get("p2") or "").strip()
        date = a.get("date") or f"{pd.Timestamp.today():%Y-%m-%d}"
        o1, o2 = _f(a.get("o1")), _f(a.get("o2"))
        opts = "".join(f"<option value='{escape(n)}'>" for n in m.players(tour))
        form = (f'<form class="card form" method="get">'
                f'<div><label>Tour</label><select name="tour">{_opts(("ATP", "WTA"), tour)}</select></div>'
                f'<div><label>Nawierzchnia</label><select name="surface">{_opts(SURFACES, surface)}</select></div>'
                f'<div><label>Sety</label><select name="bo"><option value="3">Bo3</option><option value="5" {"selected" if bo == 5 else ""}>Bo5</option></select></div>'
                f'<div><label>Zawodnik 1</label><input name="p1" list="pl" value="{escape(p1)}" required></div>'
                f'<div><label>Zawodnik 2</label><input name="p2" list="pl" value="{escape(p2)}" required></div>'
                f'<div><label>Kurs 1</label><input name="o1" value="{o1 or ""}" inputmode="decimal"></div>'
                f'<div><label>Kurs 2</label><input name="o2" value="{o2 or ""}" inputmode="decimal"></div>'
                f'<div><label>Data</label><input type="date" name="date" value="{escape(date)}"></div>'
                f'<div><button>Policz</button></div></form><datalist id="pl">{opts}</datalist>')
        if not p1 or not p2:
            return page("Mecz", ("html", form), ("p", "Wybierz dwóch zawodników (podpowiedzi z bazy), nawierzchnię i - jeśli masz - kursy. "
                                                     "Kursy nie są konieczne; z nimi prognoza jest mieszana z rynkiem."))
        p = m.predict(tour, surface, bo, p1, p2, o1, o2)
        up = db.load_upcoming(st.conn, include_past_days=3)
        row = {}
        if len(up):
            hit = up[(up.tour == tour) & (((up.p1 == p["p1"]) & (up.p2 == p["p2"])) | ((up.p1 == p["p2"]) & (up.p2 == p["p1"])))]
            if len(hit):
                row = hit.iloc[0].to_dict()
                if row["p1"] != p["p1"]:
                    row = {**row, "o1": row["o2"], "o2": row["o1"], "hcp_line": None}
        if o1 and o2:
            row.update(o1=o1, o2=o2)
        i1, i2 = p["info"]
        mk = f"rynek {V.pct(p['p_market'])} / Elo {V.pct(p['p_elo'])} / mieszanka (waga modelu {p['w']:.2f})" if p["p_market"] is not None else f"Elo {V.pct(p['p_elo'])} (bez kursów - sam model)"
        head = (f'<div class="match"><div class="hd"><span class="pl">{escape(p["p1"])} <small>vs</small> {escape(p["p2"])}</span>'
                f'<span class="m">{escape(tour)} · {escape(p["surface"])} · Bo{bo} · {escape(date)}</span></div>'
                f'<div class="bar2"><i style="width:{100 * p["m"]["p1"]:.0f}%"></i></div>'
                f'<div class="m">{escape(V.short(p["p1"]))} {V.pct(p["m"]["p1"])} ({V.fair(p["m"]["p1"])}) – {escape(V.short(p["p2"]))} {V.pct(p["m"]["p2"])} ({V.fair(p["m"]["p2"])}) · {mk}</div>'
                f'{V.tiles_for(p, _f(row.get("total_line")), hl())}{V.h2h_row(m.df, p)}'
                + "".join(f'<div class="warn m">⚠ {escape(w)}</div>' for w in p["warn"]) + "</div>")
        detail = (f'<div class="card">{V.games_chart(p, _f(row.get("total_line")))}'
                  f'<p class="m">Punkt przy serwisie (z modelu): {escape(V.short(p["p1"]))} {V.pct(p["serve"][0], 1)}, '
                  f'{escape(V.short(p["p2"]))} {V.pct(p["serve"][1], 1)} (średnia nawierzchni {V.pct(p["s0"], 1)}). '
                  f'Średni handicap gemów: {p["m"]["diff_mean"]:+.1f}. Średnia nawierzchni: {p["base"].get("games_mean", float("nan")):.1f} gemów, '
                  f'tie-break {V.pct(p["base"].get("p_tb"))}.</p></div>')
        players = '<div class="grid">' + V.player_block(m.df, p, 0) + V.player_block(m.df, p, 1) + "</div>"
        note = ('<p class="small">Gemy, sety i tie-breaki wynikają z jednej liczby - szansy wygrania punktu przy serwisie, dobranej tak, by zgadzała się '
                'z szansą zwycięstwa. Model nie zna jeszcze indywidualnego stylu (np. „wielki serwis” = więcej tie-breaków) - przy takich zawodnikach '
                'over/tie-break mogą być zaniżone. Zmęczenie i H2H są tylko informacyjne (nie zmieniają liczb).</p>')
        return page(f"{p['p1']} – {p['p2']}", ("html", form + head + detail + players), ("html", V.sections(p, date, row)), ("html", note))

    # ------------------------------------------------------------------ Podpowiedzi
    @app.get("/suggest")
    def suggest():
        a = request.args
        min_p = (_f(a.get("min_p")) or 0) / 100 or None
        min_e = _f(a.get("min_edge"))
        min_e = 0.03 if min_e is None else min_e / 100
        groups = a.getlist("g") or ["Zwycięzca", "Gemy", "Tie-break", "Sety"]
        tour = (a.get("tour") or "").upper() or None
        rows = []
        for r, p in upcoming_preds(tour):
            day = str(r["date"])[:10]
            cat = bm.catalogue(p)
            for k, v in cat.items():
                if v["group"] not in groups:
                    continue
                o = bm.book_odds(r, k)
                e = edge(v["p"], o) if o else None
                if o:
                    ok = e >= min_e and (min_p is None or v["p"] >= min_p)
                else:
                    ok = min_p is not None and v["p"] >= min_p
                if not ok:
                    continue
                rows.append({"day": day, "mecz": f"{p['p1']} – {p['p2']}", "tour": p["tour"], "typ": v["label"], "p": v["p"],
                             "fair": 1 / v["p"], "kurs": o, "edge": e, "kelly": kelly(v["p"], o) if o else None,
                             "leg": bm.leg_id(p["tour"], day, p["p1"], p["p2"], p["surface"], p["best_of"], k)})
        sort = a.get("sort") or "mecz"
        if sort == "edge":
            rows.sort(key=lambda x: -(x["edge"] if x["edge"] is not None else -9))
        elif sort == "p":
            rows.sort(key=lambda x: -x["p"])
        else:
            rows.sort(key=lambda x: (x["day"], x["mecz"], -x["p"]))
        gbox = "".join(f'<label style="margin-right:8px"><input type="checkbox" name="g" value="{g}" {"checked" if g in groups else ""}> {g}</label>' for g in bm.GROUPS)
        form = (f'<form class="card form" method="get"><div><label>Min. szansa % (puste = tylko typy z kursem)</label><input name="min_p" value="{a.get("min_p", "")}" inputmode="decimal"></div>'
                f'<div><label>Min. przewaga % (typy z kursem)</label><input name="min_edge" value="{a.get("min_edge", "3")}" inputmode="decimal"></div>'
                f'<div><label>Tour</label><select name="tour"><option value="">wszystkie</option><option {"selected" if tour == "ATP" else ""}>ATP</option><option {"selected" if tour == "WTA" else ""}>WTA</option></select></div>'
                f'<div><label>Sortuj</label><select name="sort"><option value="mecz">po meczu</option><option value="edge" {"selected" if sort == "edge" else ""}>po przewadze</option><option value="p" {"selected" if sort == "p" else ""}>po szansie</option></select></div>'
                f'<div style="grid-column:1/-1">{gbox}</div><div><button>Pokaż</button></div></form>')
        trs = []
        for x in rows[:300]:
            kurs = f"{x['kurs']:.2f}" if x["kurs"] else ""
            ed = f"{100 * x['edge']:+.0f}%" if x["edge"] is not None else ""
            ke = f"{100 * x['kelly']:.1f}%" if x["kelly"] is not None else ""
            pos = "pos" if (x["edge"] or 0) > 0 else ""
            trs.append(f'<tr><td class="l"><span class="dt">{x["day"][5:]}</span>{escape(x["mecz"])}</td><td class="l">{escape(x["typ"])}</td>'
                       f'<td>{V.pct(x["p"])}</td><td>{x["fair"]:.2f}</td><td>{kurs}</td><td class="{pos}">{ed}</td><td>{ke}</td>'
                       f'<td>{V.add_btn(x["leg"])}</td></tr>')
        body = "".join(trs)
        table = (f'<div class="card"><table><tr><th class="l">mecz</th><th class="l">typ</th><th>szansa</th><th>uczciwy</th><th>kurs</th><th>przewaga</th><th>Kelly ¼</th><th></th></tr>{body}</table></div>'
                 if rows else '<div class="card"><p class="m">Nic nie spełnia warunków. Bez kursów wpisz „Min. szansa” (np. 65), żeby zobaczyć najmocniejsze typy modelu.</p></div>')
        return page("Podpowiedzi", ("html", form + table),
                    ("p", "Kursy w bazie są zwykle tylko na zwycięzcę (i gemy, jeśli API je zwróci). Dla pozostałych rynków porównaj „uczciwy kurs” z ofertą "
                          "bukmachera: opłaca się tylko kurs wyraźnie wyższy. Przewaga zakłada, że model ma rację - na kursach zamknięcia rynek bywa lepszy."))

    # ------------------------------------------------------------------ Zestawienie + zakłady
    def compute_coupon(legs: list[str], odds_in: list[str]):
        m = model()
        up = db.load_upcoming(st.conn, include_past_days=3)
        out = []
        for i, leg in enumerate(legs):
            try:
                t, d, a, b, s, bo, key = bm.parse_leg(leg)
            except ValueError as e:
                out.append({"id": leg, "blad": str(e)})
                continue
            row = {}
            if len(up):
                hit = up[(up.tour == t) & (up.p1 == a) & (up.p2 == b)]
                if len(hit):
                    row = hit.iloc[0].to_dict()
            p = m.predict(t, s, bo, a, b, row.get("o1"), row.get("o2"))
            cat = bm.catalogue(p)
            if key not in cat:
                out.append({"id": leg, "mecz": f"{a} – {b}", "data": d, "blad": "nieznany rynek"})
                continue
            v = cat[key]
            mine = _f(odds_in[i]) if i < len(odds_in) else None
            book = bm.book_odds(row, key)
            used = mine if mine and mine > 1 else book
            out.append({"id": leg, "mecz": f"{a} – {b}", "data": d, "rynek": v["label"], "p": v["p"], "kurs_fair": 1 / v["p"],
                        "kurs_uzyty": used, "kurs_zrodlo": "Twój" if mine and mine > 1 else ("baza" if book else None),
                        "edge": edge(v["p"], used) if used else None, "ostrzezenia": p["warn"]})
        ok = [x for x in out if "blad" not in x]
        txt = ""
        if ok:
            pall = float(np.prod([x["p"] for x in ok]))
            txt = (f"{len(ok)} typ(y). Szansa wszystkich wg modelu (zakładając niezależność) {100 * pall:.1f}%, uczciwy kurs AKO {1 / pall:.2f}. "
                   "Typy z tego samego meczu nie są niezależne.")
        return {"legs": out, "podsumowanie": txt}

    @app.get("/coupon")
    def coupon():
        return render("coupon.html", "Zestawienie")

    @app.get("/api/coupon")
    def api_coupon():
        return jsonify(compute_coupon(request.args.getlist("leg"), request.args.getlist("odds")))

    @app.post("/api/bets")
    def api_bets_add():
        d = request.get_json(silent=True) or {}
        res = compute_coupon(d.get("legs") or [], d.get("odds") or [])
        legs = [x for x in res["legs"] if "blad" not in x]
        if not legs or any(not x.get("kurs_uzyty") for x in legs):
            return jsonify({"ok": False, "blad": "brakuje kursu przy którymś typie"}), 400
        odds = float(np.prod([x["kurs_uzyty"] for x in legs]))
        try:
            bets_mod.add_bet(st.conn, [{"id": x["id"], "mecz": x["mecz"], "rynek": x["rynek"], "p": x["p"], "kurs": x["kurs_uzyty"]} for x in legs],
                             odds, _f(d.get("stake")) or 0)
        except ValueError as e:
            return jsonify({"ok": False, "blad": str(e)}), 400
        bootstrap.sync_up_bg(st, ("bets",))
        return jsonify({"ok": True, "kurs": odds})

    @app.get("/bets")
    def bets_page():
        df = bets_mod.load(st.conn)
        bl = []
        for r in df.to_dict("records"):
            r["legs"] = json.loads(r["legs"])
            r["date"] = str(r["placed_at"])[:16].replace("T", " ")
            bl.append(r)
        return render("bets.html", "Moje zakłady", bets=bl, s=bets_mod.summary(df), spark=bets_mod.sparkline(bets_mod.cumulative(df)),
                      persisted=gh_store.enabled())

    @app.post("/bets/<int:bet_id>/<action>")
    def bets_action(bet_id, action):
        if action == "delete":
            bets_mod.delete(st.conn, bet_id)
        elif action in ("won", "lost", "void", "open"):
            bets_mod.set_status(st.conn, bet_id, action)
        else:
            abort(404)
        bootstrap.sync_up_bg(st, ("bets",))
        return redirect(request.script_root + "/bets")

    # ------------------------------------------------------------------ Ranking / zawodnik
    @app.get("/ranking")
    def ranking():
        m = model()
        tour = (request.args.get("tour") or "ATP").upper()
        surf = request.args.get("surface") or ""
        cut = m.df.date.max() - pd.Timedelta(days=180) if len(m.df) else None
        rows = []
        for k, r in m.elo.r.items():
            t, name = k.split("|", 1)
            if t != tour or (cut is not None and m.elo.last.get(k, cut) < cut):
                continue
            o, s, b = m.elo.rating(k, surf or "Hard")
            rows.append({"zawodnik": name, "Elo": round(o), **({f"Elo {surf}": round(s), "mieszane": round(b)} if surf else {}),
                         "mecze": m.elo.n.get(k, 0), "ranking": m.elo.rank.get(k)})
        df = pd.DataFrame(rows)
        if df.empty:
            return page("Ranking Elo", ("p", "Brak danych."))
        df = df.sort_values("mieszane" if surf else "Elo", ascending=False).head(100)
        df.insert(0, "#", range(1, len(df) + 1))
        df["ranking"] = df["ranking"].map(lambda x: "" if x != x or x is None else f"{int(x)}")
        tabs = [(f"{t} {s or 'ogólne'}", f"/ranking?tour={t}&surface={s}") for t in ("ATP", "WTA") for s in ("",) + SURFACES]
        df["zawodnik"] = [f'<a href="{request.script_root}/player?tour={tour}&name={escape(n)}">{escape(n)}</a>' for n in df.zawodnik]
        html = '<div class="card">' + df.to_html(index=False, border=0, escape=False, na_rep="–") + "</div>"
        return page(f"Ranking Elo {tour} {surf}", ("tabs", tabs), ("html", html),
                    ("p", "Aktywni w ostatnich 180 dniach. Elo liczone z meczów głównych turniejów (tennis-data.co.uk); „mieszane” = połowa ogólnego + połowa nawierzchni."))

    @app.get("/player")
    def player():
        m = model()
        tour = (request.args.get("tour") or "ATP").upper()
        name = m.resolve(tour, request.args.get("name", "")) or request.args.get("name", "")
        k = f"{tour}|{name}"
        if k not in m.elo.r:
            return page("Zawodnik", ("p", f"Nie znaleziono {name} w bazie {tour}.")), 404
        hist = m.elo.hist.get(k, [])[-120:]
        spark = bets_mod.sparkline([v for _, v in hist], h=80) if len(hist) > 2 else ""
        blocks = []
        for s in SURFACES:
            w, l = ft.surface_record(m.df, tour, name, s)
            o, rs, b = m.elo.rating(k, s)
            blocks.append(V.kpi(f"{rs:.0f}", f"Elo {s} · 12 mies. {w}–{l}"))
        d = ft.player_matches(m.df, tour, name).sort_values("date", ascending=False).head(25)
        rows = [{"data": f"{r['date']:%Y-%m-%d}", "turniej": r["tournament"], "naw.": r["surface"], "runda": r["round"],
                 "wynik": "W" if r["winner"] == name else "P", "rywal": r["loser"] if r["winner"] == name else r["winner"],
                 "sety": ft._score(r, r["winner"] != name)} for r in d.to_dict("records")]
        return page(name, ("html", f'<div class="kpis">{V.kpi(f"{m.elo.r[k]:.0f}", "Elo ogólne")}{"".join(blocks)}</div>'),
                    ("html", f'<div class="card"><div class="cap">Elo ogólne - ostatnie {len(hist)} meczów</div>{spark}</div>' if spark else ""),
                    ("t", pd.DataFrame(rows)))

    # ------------------------------------------------------------------ Ostatnie / backtest
    @app.get("/recent")
    def recent():
        days = int(_f(request.args.get("days")) or 7)
        tour = (request.args.get("tour") or "").upper() or None
        m = model()
        bt = cached(("recent", days, tour), lambda: backtest.rows(m, days=days, tour=tour))
        if bt.empty:
            return page("Ostatnie", ("p", "Brak meczów z ostatnich dni w bazie (tennis-data.co.uk aktualizuje się co kilka dni)."))
        c = bt[bt.completed]
        hit = ((c.p >= 0.5) == (c.y == 1))
        mk = c[c.p_market.notna()]
        mk_hit = ((mk.p_market >= 0.5) == (mk.y == 1)).mean() if len(mk) else None
        k = (f'<div class="kpis">{V.ring(float(hit.mean()), f"trafiony zwycięzca (model) · {len(c)} meczów")}'
             + (V.ring(float(mk_hit), "faworyt bukmachera") if mk_hit is not None else "")
             + V.kpi(f"{backtest._ll(c.p, c.y):.3f}", "log-loss model (mniej = lepiej)")
             + (V.kpi(f"{backtest._ll(mk.p_market, mk.y):.3f}", "log-loss rynek") if len(mk) else "") + "</div>")
        strip = "".join(f'<span class="fc {"yes" if h else "no"}" title="{escape(r.p1)} – {escape(r.p2)} {escape(r.score)}">{"✓" if h else "✗"}</span>'
                        for h, r in zip(hit[::-1], c[::-1].itertuples()))
        base = {}
        for (t, s, bo), g in c.groupby(["tour", "surface", "best_of"]):
            base[(t, s, bo)] = m.base_for(t, s, bo)
        b_over = float(np.mean([base[(r.tour, r.surface, r.best_of)].get("over", {}).get(f"{r.line}", np.nan) for r in c.itertuples()]))
        b_tb = float(np.mean([base[(r.tour, r.surface, r.best_of)].get("p_tb", np.nan) for r in c.itertuples()]))
        bars = V.market_bars([("Over linii", float((c.total_games > c.line).mean()), float(c.p_over.mean()), b_over if b_over == b_over else None),
                              ("Tie-break", float(c.tb.mean()), float(c.p_tb.mean()), b_tb if b_tb == b_tb else None),
                              ("Bez straty seta", float(c.straight.mean()), float(c.p_straight.mean()), None),
                              ("TB w 1. secie", float(c.set1_tb.mean()), float(c.p_set1_tb.mean()), None)])
        trs = []
        for r in c.sort_values("date", ascending=False).head(150).itertuples():
            fav1 = r.p >= 0.5
            ok = fav1 == (r.y == 1)
            over = r.total_games > r.line
            trs.append(f'<tr><td class="mt1"><span class="dt">{r.date:%m-%d}</span>{escape(r.p1)} – {escape(r.p2)}</td><td>{escape(r.score)}</td>'
                       f'<td class="mc {"yes" if ok else "no"}">{escape(V.short(r.p1 if fav1 else r.p2))} <small>{V.pct(max(r.p, 1 - r.p))}</small></td>'
                       f'<td class="mc {"yes" if over else "no"}">{int(r.total_games)} <small>{V.pct(r.p_over)}</small></td>'
                       f'<td class="mc {"yes" if r.tb else "no"}">{"TAK" if r.tb else "nie"} <small>{V.pct(r.p_tb)}</small></td></tr>')
        table = ('<div class="card rt"><table><tr><th>mecz</th><th>wynik</th><th>faworyt modelu</th><th>gemy (szansa over)</th><th>tie-break (szansa)</th></tr>'
                 + "".join(trs) + "</table></div>")
        tabs = [("7 dni", "/recent?days=7"), ("14 dni", "/recent?days=14"), ("30 dni", "/recent?days=30"), ("ATP", f"/recent?days={days}&tour=ATP"), ("WTA", f"/recent?days={days}&tour=WTA")]
        return page("Ostatnie", ("tabs", tabs), ("html", k),
                    ("html", f'<div class="card"><div class="cap">Forma modelu (najnowsze z lewej): ✓ = faworyt modelu wygrał</div><div class="fstrip">{strip}</div></div>'),
                    ("html", f'<div class="card"><div class="cap">Rynki: słupek = jak często zaszło, biała kreska = średnia szansa wg modelu, kropka = średnia nawierzchni</div>{bars}</div>'),
                    ("html", table),
                    ("p", "Prognozy sprzed meczu (Elo zna tylko wcześniejsze mecze). Mała próba = dużo szumu: tydzień dobrych lub złych wyników niewiele mówi."))

    @app.get("/backtest")
    def backtest_page():
        tour = (request.args.get("tour") or "").upper() or None
        days = int(_f(request.args.get("days")) or 365)
        m = model()
        bt = cached(("bt", tour, days), lambda: backtest.rows(m, days=days, tour=tour, limit=1500), ttl=6 * 3600)
        s = backtest.summary(bt)
        if not s:
            return page("Backtest", ("p", "Za mało danych."))
        rows = [("log-loss (zwycięzca)", s.get("ll_elo_mkt"), s.get("ll_market"), s.get("ll_blend")),
                ("Brier", s.get("brier_elo"), s.get("brier_market"), s.get("brier_blend")),
                ("trafność faworyta", s.get("acc_elo"), s.get("acc_market"), s.get("acc_blend"))]
        t1 = pd.DataFrame(rows, columns=["miara", "Elo", "rynek", "mieszanka"])
        t2 = pd.DataFrame([("średnia gemów", s.get("games_mean_pred"), s.get("games_mean_real")),
                           ("over 22.5 / 38.5", s.get("over_pred"), s.get("over_real")),
                           ("tie-break w meczu", s.get("tb_pred"), s.get("tb_real")),
                           ("bez straty seta", s.get("straight_pred"), s.get("straight_real"))], columns=["rynek", "model (średnio)", "faktycznie"])
        t3 = pd.DataFrame([("over (model)", s.get("over_brier")), ("over (sama średnia)", s.get("over_brier_base")),
                           ("tie-break (model)", s.get("tb_brier")), ("tie-break (sama średnia)", s.get("tb_brier_base"))], columns=["Brier", "wartość"])
        cal = pd.DataFrame(backtest.calibration(bt.p, bt.y))
        roi = backtest.roi_value(bt)
        roi_e = backtest.roi_value(bt, use="p_elo")
        r_txt = " · ".join(f"{lab}: {x['n']} zakładów, ROI {100 * x['roi']:+.1f}% (±{100 * (x['se'] or 0):.1f})" for lab, x in (("mieszanka", roi), ("samo Elo", roi_e)) if x.get("n"))
        tabs = [("ostatni rok", "/backtest"), ("2 lata", "/backtest?days=730"), ("ATP", f"/backtest?tour=ATP&days={days}"), ("WTA", f"/backtest?tour=WTA&days={days}")]
        return page("Backtest", ("tabs", tabs), ("p", f"{s['n']} meczów (z kursami: {s.get('n_mkt', 0)}). Rynek = Pinnacle bez marży. Mniej = lepiej dla log-loss i Briera; „Over linii” = 22.5 gema (Bo3) / 38.5 (Bo5)."),
                    ("t", t1), ("h", "Gemy i tie-breaki"), ("t", t2), ("t", t3), ("h", "Kalibracja (mieszanka)"), ("t", cal),
                    ("h", "Symulacja: 1 zł na zwycięzcę przy przewadze ≥ 3% (kursy Pinnacle)"), ("p", r_txt or "brak zakładów"),
                    ("p", "Uczciwie: parametry (serwis bazowy, waga rynku) są dobrane na całej historii, więc wynik jest lekko optymistyczny. "
                          "Kursy Pinnacle przy zamknięciu to najtrudniejszy rynek - jeśli rynek wygrywa z modelem, to normalne."))

    @app.get("/track")
    def track():
        pred = ledger.load(st.conn)
        ev = ledger.evaluate(pred, st.lookup)
        s = ledger.scores(ev)
        head = ""
        if s:
            head = ('<div class="kpis">' + V.kpi(str(s["n"]), "rozliczone prognozy") + V.kpi(V.pct(s["acc_model"]), "trafność faworyta")
                    + V.kpi(f"{s['ll_model']:.3f}", "log-loss model")
                    + (V.kpi(f"{s['ll_market']:.3f}", f"log-loss rynek (n={s['n_mkt']})", s["ll_market"] >= s["ll_model_same"]) if "ll_market" in s else "")
                    + (V.kpi(f"{s['games_bias']:+.1f}", "błąd średniej gemów (model − wynik)") if "games_bias" in s else "") + "</div>")
        show = pred.head(200).copy()
        if len(show):
            show = show[["date", "tour", "p1", "p2", "p_model", "p_market", "games_mean", "total_line", "p_over", "p_tb"]]
            show.columns = ["data", "tour", "zawodnik 1", "zawodnik 2", "szansa 1", "rynek 1", "gemy", "linia", "over", "TB"]
        return page("Dziennik prognoz", ("html", head),
                    ("p", "Prognoza zapisuje się przed meczem (nadchodzące mecze z listy) i zamraża w dniu meczu. "
                          + ("" if gh_store.enabled() else "UWAGA: bez GITHUB_TOKEN/GITHUB_REPO dziennik zniknie przy restarcie.")),
                    ("t", show) if len(show) else ("p", "Dziennik jest pusty - zapełni się, gdy pojawią się nadchodzące mecze."))

    # ------------------------------------------------------------------ Dane
    @app.get("/data")
    def data_page():
        m = model()
        df = m.df
        info = pd.DataFrame([{"tour": t, "mecze": int((df.tour == t).sum()), "od": f"{df[df.tour == t].date.min():%Y-%m-%d}",
                              "do": f"{df[df.tour == t].date.max():%Y-%m-%d}"} for t in df.tour.unique()]) if len(df) else pd.DataFrame()
        steps = "".join(f'<tr><td class="l">{escape(s["krok"])}</td><td class="{"ok" if s["ok"] else "bad"}">{"OK" if s["ok"] else "BŁĄD"}</td>'
                        f'<td class="l" style="white-space:normal">{escape(s["opis"])}</td><td>{escape(s["czas"][11:19])}</td></tr>' for s in st.diag["kroki"])
        params = pd.DataFrame([{"tour|nawierzchnia": k, "serwis bazowy s0": v} for k, v in sorted(m.s0.items())])
        refresh_btn = (f'<form method="post" action="{request.script_root}/refresh"><button>Odśwież teraz</button> '
                       f'<span class="m">{"trwa odświeżanie…" if st.refreshing else ""}</span></form>')
        return page("Dane", ("html", refresh_btn), ("t", info) if len(info) else ("p", "Baza pusta."),
                    ("html", f'<div class="card"><table><tr><th class="l">krok</th><th>stan</th><th class="l">opis</th><th>UTC</th></tr>{steps}</table></div>'),
                    ("h", "Parametry modelu"), ("t", params), ("p", f"Waga modelu w mieszance z rynkiem: {m.w}. Źródło: "
                                                                   f"{'tennis_params/model.json' if m.params.get('s0') else 'domyślne (python -m tnpred tune, by dobrać)'}."),
                    refresh=st.refreshing)

    @app.post("/refresh")
    def refresh():
        if not st.refreshing:
            threading.Thread(target=bootstrap.refresh, args=(st,), daemon=True).start()
            time.sleep(0.3)
        cache.clear()
        return redirect(request.script_root + "/data")

    # ------------------------------------------------------------------ API
    @app.get("/api/predict")
    def api_predict():
        a = request.args
        p = model().predict(a.get("tour", "ATP"), a.get("surface", "Hard"), a.get("bo", 3), a.get("p1", ""), a.get("p2", ""),
                            _f(a.get("o1")), _f(a.get("o2")))
        p["m"]["games_pmf"] = {str(k): v for k, v in p["m"]["games_pmf"].items()}
        for i in p["info"]:
            i["last"] = str(i["last"])[:10] if i["last"] is not None else None
        return jsonify(p)

    @app.get("/healthz")
    def health():
        try:
            n = st.conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        except Exception:  # noqa: BLE001
            n = None
        return jsonify({"ok": True, "app": "tnpred", "version": __version__, "matches": n, "refreshing": st.refreshing}), 200

    return app


_APP = None


def __getattr__(name):  # leniwe tworzenie: `gunicorn tnpred.web:app` (import modułu nie startuje aplikacji)
    global _APP
    if name == "app":
        if _APP is None:
            _APP = create_app()
        return _APP
    raise AttributeError(name)
