"""Interfejs wiersza poleceń:  python -m fbpred <komenda> --help"""
from __future__ import annotations

import argparse
import difflib
import sys
from datetime import date

import numpy as np
import pandas as pd

from . import config, csvdata, db, fatigue as fat, profile as prof_mod, history, ledger, notify, params as prm, quality, recent as recent_mod, rest, report, stats as stats_mod
from .backtest import (DRAW_CALIB, best_blend, betting_sim, bias_shift, bias_table, calibration, compare_report,
                       summarize, walk_forward)
from . import draws as draws_mod
from .odds import apply_blend, value_picks
from .predictor import format_prediction
from .simulate import simulate_table

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)


def _years(s: str) -> list[int]:
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


def _season_now() -> int:
    t = date.today()
    return t.year if t.month >= 7 else t.year - 1


def _resolve(name: str, teams: list[str]) -> str:
    if name in teams:
        return name
    m = difflib.get_close_matches(name, teams, n=3, cutoff=0.5)
    if len(m) == 1 or (m and m[0].lower().startswith(name.lower())):
        print(f"(dopasowano '{name}' -> '{m[0]}')")
        return m[0]
    sys.exit(f"Nie znam drużyny '{name}'. Podobne: {m or 'brak'}. Lista: python -m fbpred teams --league ...")


def _load(a) -> pd.DataFrame:
    conn = db.connect(config.DB_PATH)
    df = db.load_matches(conn, a.league)
    if df.empty:
        sys.exit(f"Brak meczów dla ligi '{a.league}'. Najpierw: fetch-csv / fetch-api / demo.")
    return df


def _predictor(a, df):
    P, p = prm.build_predictor(df, a.league, ridge=getattr(a, "ridge", None), xi=getattr(a, "xi", None))
    return P, p


# ------------------------------------------------------------------ dane
def cmd_fetch_csv(a):
    conn = db.connect(config.DB_PATH)
    for y in _years(a.seasons):
        try:
            rows = history.apply_aliases(csvdata.parse_csv(csvdata.download(a.league, y), a.league, y))
        except Exception as e:  # noqa: BLE001
            print(f"  {a.league} {y}: błąd ({e})")
            continue
        db.upsert_matches(conn, rows)
        print(f"  {a.league} {y}/{y + 1}: {len(rows)} meczów")


def cmd_import_csv(a):
    conn = db.connect(config.DB_PATH)
    text = open(a.file, encoding="utf-8-sig", errors="replace").read()
    rows = history.apply_aliases(csvdata.parse_csv(text, a.league, a.season))
    db.upsert_matches(conn, rows)
    print(f"Zaimportowano {len(rows)} meczów ({a.league} {a.season}).")


def cmd_fetch_fixtures(a):
    conn = db.connect(config.DB_PATH)
    rows = history.apply_aliases(csvdata.parse_csv(csvdata.download_fixtures(), a.league, None, only_div=True))
    db.upsert_matches(conn, rows)
    if config.ARCHIVE_ODDS:
        print(f"  archiwum kursów: +{history.archive_odds(rows, config.HISTORY_DIR)}")
    print(f"  nadchodzące mecze ({a.league}): {len(rows)} (z kursami, jeśli udostępnione)")


def cmd_fetch_api(a):
    from .fetch import ApiClient, fetch_missing_stats, fetch_season
    conn = db.connect(config.DB_PATH)
    c = ApiClient()
    for y in _years(a.seasons):
        print(f"  sezon {y}: {fetch_season(c, conn, a.league, y)} meczów")
    n = fetch_missing_stats(c, conn, a.league, a.stats_limit)
    print(f"  statystyki pobrane dla {n} meczów; użyto zapytań: {c.used}, zostało: {c.remaining}")
    print("  (uruchom ponownie jutro, aby dociągnąć kolejne - pobieranie jest wznawialne)")


def cmd_upcoming(a):
    from .fetch import ApiClient, fetch_upcoming
    conn = db.connect(config.DB_PATH)
    c = ApiClient()
    print(f"  zapisano {fetch_upcoming(c, conn, a.league, a.days)} meczów; zapytań: {c.used}")


def cmd_check(a):
    df = _load(a)
    icon = {"OK": "✔", "UWAGA": "!", "BŁĄD": "✖"}
    for lvl, msg in quality.check(df):
        print(f" {icon[lvl]} [{lvl}] {msg}")


# ------------------------------------------------------------------ analiza
def cmd_teams(a):
    P, _ = _predictor(a, _load(a))
    print("\n".join(P.teams))


def cmd_strengths(a):
    df = _load(a)
    P, p = _predictor(a, df)
    print(f"Siła drużyn (atak wyżej = lepiej, obrona niżej = lepiej)  | ridge={p['ridge']}, xi={p['xi']}\n")
    act = set(stats_mod.active_teams(df))
    print(P.goals.strengths().loc[lambda t: t.index.isin(act)].to_string())
    print(f"\nPrzewaga domowa: {np.exp(P.goals.ha):.2f}x goli, rho (korekta niskich wyników): {P.goals.rho:+.3f}")
    if P.yellow and P.yellow.r:
        n = df["referee"].value_counts()
        t = pd.DataFrame({"mnoznik_kartek": {r: float(np.exp(v)) for r, v in P.yellow.r.items()}})
        t["mecze"] = t.index.map(lambda r: int(n.get(r, 0)))
        t = t[t["mecze"] >= 8].sort_values("mnoznik_kartek", ascending=False).round(3)
        print("\nSędziowie (mnożnik oczekiwanych żółtych kartek, min. 8 meczów):")
        print(pd.concat([t.head(8), t.tail(8)]).drop_duplicates().to_string())


def cmd_stats(a):
    df = _load(a)
    P, _ = _predictor(a, df)
    t = stats_mod.referee_table(df, P, a.seasons, a.min_matches) if a.view == "referees" else \
        stats_mod.team_table(df, P, a.seasons)
    print(t.to_string(index=False) if not t.empty else "Brak statystyk kartek/rożnych w danych tej ligi.")


def cmd_fatigue(a):
    """Czy krótka przerwa / LM zmienia wyniki? Test na prognozach walk-forward (jedna lub wiele lig łącznie)."""
    conn = db.connect(config.DB_PATH)
    sides, parts = [], []
    leagues = history.resolve_leagues(a.leagues)
    for lg in leagues:
        df = db.load_matches(conn, lg)
        if len(df) < a.min_train + 100:
            print(f"  {lg}: za mało meczów ({len(df)}), pomijam")
            continue
        p = prm.load(lg)
        res = walk_forward(df, a.min_train, a.step, progress=False, ridge=p["ridge"], xi=p["xi"], shot_weight=p["shot_weight"])
        cal = rest.build_calendar(df, conn)
        feats = cal.features(res)
        sides.append(fat.side_frame(res, feats, lg))
        parts.append((lg, res, feats))
        print(f"  {lg}: {len(res)} prognoz, mecze po krótkiej przerwie: {int((feats.short_h | feats.short_a).sum())}"
              + (", z kalendarzem Ligi Mistrzów" if cal.has_cl else ", BEZ danych o Lidze Mistrzów"))
    if not sides:
        sys.exit("Brak lig z wystarczającą liczbą meczów.")
    table = fat.mean_shift_test(pd.concat(sides, ignore_index=True))
    print("\n1) Efekt na liczbę goli względem prognozy modelu (próg istotności |z| >= %.1f):\n" % fat.Z_MIN)
    print(table.drop(columns=["klucz", "wspolczynnik"]).to_string(index=False) if not table.empty else "brak wariancji w danych")
    res_all = pd.concat([r for _, r, _ in parts], ignore_index=True)
    feats_all = pd.concat([f for _, _, f in parts], ignore_index=True)
    u = fat.uncertainty_test(res_all, feats_all)
    print("\n2) Przewidywalność wyników po krótkiej przerwie (1X2, umiejętność modelu vs średnia ligi):")
    print(f"   mecze po krótkiej przerwie: {u['n_krotka']}, zwykłe: {u['n_zwykle']}")
    if "roznica" in u:
        print(f"   umiejętność: krótka {u['umiejetnosc_krotka']:+.4f} | zwykłe {u['umiejetnosc_zwykle']:+.4f} | "
              f"różnica {u['roznica']:+.4f} [95%: {u['przedzial_95'][0]:+.4f}, {u['przedzial_95'][1]:+.4f}]")
    print(f"   → {u['wniosek']}")
    side_all = pd.concat(sides, ignore_index=True)
    ho = fat.holdout_gain(side_all)
    print(f"\n3) Test na danych kontrolnych (ostatnie 40% meczów, {ho['n_test']} obserwacji): przyrost log-wiarygodności "
          f"{ho['gain_per_100']:+.3f} na 100 obserwacji ({'poprawa' if ho['gain_per_100'] > 0 else 'brak poprawy'})")
    coefs = fat.significant_coefs(table, ho)
    print(f"\nWspółczynniki, które przeszły oba testy: {coefs or 'żaden - model zostaje bez czynnika zmęczenia'}")
    if a.apply:
        for lg, _, _ in parts:
            cur = prm.load(lg)
            cur["fatigue"] = coefs
            prm.save(lg, cur)
        print("Zapisano do parametrów lig" + (": " + ", ".join(lg for lg, _, _ in parts)) + ". "
              "Aby Render ich używał: git add params && git commit && git push")
    else:
        print("(użyj --apply, aby zapisać istotne współczynniki do modelu)")


def cmd_recent(a):
    df = _load(a)
    p = prm.load(a.league)
    res = recent_mod.recent_predictions(df, a.days, ridge=p["ridge"], xi=p["xi"], shot_weight=p["shot_weight"],
                                        calib=p.get("draw_shift") or None)
    if res.empty:
        sys.exit("Brak meczów w wybranym oknie.")
    print(recent_mod.show_table(res).to_string(index=False))
    print("\n" + recent_mod.summary(res))


def cmd_profile(a):
    """Czy metoda 'wyrównane kursy + lekka przewaga gości => remis w 1. lub 2. połowie' działa na historii?"""
    conn = db.connect(config.DB_PATH)
    if a.leagues == "auto":
        lgs = [r[0] for r in conn.execute("SELECT DISTINCT league FROM matches ORDER BY 1") if r[0] not in ("DEMO", "CL")]
    else:
        lgs = [x.strip() for x in a.leagues.split(",")]
    df = pd.concat([db.load_matches(conn, lg) for lg in lgs], ignore_index=True) if lgs else pd.DataFrame()
    res = prof_mod.odds_profile(df, a.balance / 100) if not df.empty else {"n": 0}
    if not res["n"]:
        sys.exit("Brak meczów z kursami i wynikiem do przerwy.")
    print(f"Ligi: {', '.join(lgs)} | mecze z kursami: {res['n']} | 'wyrównane' = różnica szans gość-gospodarz <= {a.balance:.0f} pp\n")
    print(res["tabela"].to_string(index=False))
    if not res["podzial_goli"].empty:
        print("\nTen sam profil z podziałem na oczekiwaną liczbę goli (rynek O/U 2.5):\n")
        print(res["podzial_goli"].to_string(index=False))
    print("\n" + res["werdykt"])


def cmd_draws(a):
    conn = db.connect(config.DB_PATH)
    df = db.load_matches(conn, a.league)
    up = db.load_upcoming(conn, a.league, since=None if a.include_past else db.today())
    if df.empty or up.empty:
        sys.exit("Brak danych lub nadchodzących meczów (zajrzyj na stronę /data albo uruchom fetch-fixtures).")
    P, p = _predictor(a, df)
    t = draws_mod.draw_table(P, df, up, a.market, a.days, a.top)
    title, _ = draws_mod.MARKETS[a.market]
    if t.empty:
        sys.exit(f"Brak meczów w horyzoncie {a.days} dni.")
    base = draws_mod.base_rates(df).get(a.market)
    print(f"{title} - mecze w ciągu {a.days} dni (średnia ligi: {100 * base:.1f}%)\n" if base else f"{title}\n")
    print(t.to_string(index=False))
    print("\nkurs_fair = 1/prawdopodobieństwo (bez marży). Opłaca się, gdy kurs bukmachera jest WYRAŹNIE wyższy.")
    if p.get("draw_shift") and any(p["draw_shift"].values()):
        print(f"(zastosowano kalibrację z tune: {p['draw_shift']})")


def cmd_predict(a):
    df = _load(a)
    P, p = _predictor(a, df)
    home, away = _resolve(a.home, P.teams), _resolve(a.away, P.teams)
    row = {"o_home": a.odds[0], "o_draw": a.odds[1], "o_away": a.odds[2]} if a.odds else {}
    pred = apply_blend(P.predict(home, away, a.referee), row, p["blend_w"])
    print(format_prediction(pred))


def cmd_upcoming_predict(a):
    conn = db.connect(config.DB_PATH)
    df = db.load_matches(conn, a.league)
    up = db.load_upcoming(conn, a.league, since=None if a.include_past else db.today())
    if up.empty:
        sys.exit("Brak nadchodzących meczów w bazie (komendy: fetch-fixtures, upcoming, demo; --include-past dla danych demo).")
    P, p = _predictor(a, df)
    for r in up.head(a.limit).to_dict("records"):
        pred = apply_blend(P.predict(r["home"], r["away"], r.get("referee"), date=r["date"]), r, p["blend_w"])
        print(format_prediction(pred))
        picks = value_picks(pred, r, a.min_edge)
        if picks:
            print("\n  TYPY Z PRZEWAGĄ nad kursem (to nie jest gwarancja!):")
            for k in picks:
                warn = "  <- PODEJRZANE: tak duża przewaga to zwykle błąd modelu" if k["edge"] > 0.15 else ""
                print(f"   {k['rynek']:10} p={k['p_model']:.3f} kurs={k['kurs']} edge={k['edge']:+.1%} "
                      f"kelly1/4={k['kelly_1/4']:.2%}{warn}")
        print("-" * 60)


def cmd_simulate(a):
    conn = db.connect(config.DB_PATH)
    df = db.load_matches(conn, a.league)
    if df.empty:
        sys.exit("Brak danych.")
    up = db.load_upcoming(conn, a.league)
    P, _ = _predictor(a, df)
    tab, info = simulate_table(df, P, up, n=a.n, n_european=a.top, n_relegated=a.relegated)
    print(f"Sezon {info['sezon']}: zostało {info['pozostalo_meczow']} meczów ({info['metoda']}), "
          f"{info['symulacji']} symulacji\n")
    print(tab.to_string(index=False))


# ------------------------------------------------------------------ ocena i strojenie
def cmd_backtest(a):
    df = _load(a)
    p = {**prm.load(a.league), **{k: v for k, v in (("ridge", a.ridge), ("xi", a.xi), ("shot_weight", a.shot_weight))
                                  if v is not None}}
    print(f"Backtest: {len(df)} meczów, trening min. {a.min_train}, krok {a.step} dni, ridge={p['ridge']}, "
          f"xi={p['xi']}, shot_weight={p['shot_weight']}")
    res = walk_forward(df, a.min_train, a.step, ridge=p["ridge"], xi=p["xi"], shot_weight=p["shot_weight"])
    print("\nLog-loss (mniej = lepiej). 'vs_baseline_%' > 0: model lepszy od średniej ligowej.\n")
    print(summarize(res).to_string(index=False))
    bt = bias_table(res)
    if not bt.empty:
        print("\nCzy model zawyża/zaniża? (średnia prognoza vs faktyczna częstość; 'tune' koryguje istotne obciążenie remisów)\n")
        print(bt.to_string(index=False))
    print()
    for line in compare_report(res):
        print(" •", line)
    sim = betting_sim(res)
    if sim:
        print(f"\nSymulacja zakładów (1X2, edge>=5%): {sim}")
    print("\nKalibracja 1X2 (gospodarz wygrywa):")
    print(calibration(res["p1"].to_numpy(), (res["y"] == 0).to_numpy(float)).to_string(index=False))
    if a.out:
        res.to_csv(a.out, index=False)
        print(f"\nZapisano wyniki do {a.out}")


def cmd_tune(a):
    df = _load(a)
    grid = [(r, x) for r in a.ridges for x in a.xis]
    print(f"Strojenie: {len(grid)} kombinacji, krok {a.step} dni (może potrwać)")
    rows, best = [], None
    for r, x in grid:
        res = walk_forward(df, a.min_train, a.step, progress=False, ridge=r, xi=x)
        s = summarize(res).set_index("rynek")
        ll = float(s.loc["1X2", "model"])
        bl = best_blend(res)
        rows.append({"ridge": r, "xi": x, "logloss_1X2": ll,
                     "logloss_O2.5": float(s.loc["Over 2.5", "model"]) if "Over 2.5" in s.index else np.nan,
                     "waga_modelu_w_miksie": bl["w"] if bl else np.nan})
        print(f"  ridge={r:<5} xi={x:<7} 1X2={ll:.4f}")
        if best is None or ll < best[0]:
            best = (ll, r, x, bl["w"] if bl else None)
    print("\n" + pd.DataFrame(rows).round(4).sort_values("logloss_1X2").to_string(index=False))
    ll0, r, x, w = best
    sw = 0.0
    if df[["h_sot", "a_sot"]].notna().all(axis=1).sum() >= 200:
        print("\nEtap 2: waga celnych strzałów (stabilniejszy sygnał niż same gole)")
        best_sw = (ll0, 0.0, w)
        for cand in a.shot_weights:
            res = walk_forward(df, a.min_train, a.step, progress=False, ridge=r, xi=x, shot_weight=cand)
            ll = float(summarize(res).set_index("rynek").loc["1X2", "model"])
            bl = best_blend(res)
            print(f"  shot_weight={cand:<4} 1X2={ll:.4f}")
            if ll < best_sw[0] - 1e-6:
                best_sw = (ll, cand, bl["w"] if bl else w)
        _, sw, w = best_sw
    print("\nEtap 3: kalibracja rynków remisowych")
    res_f = walk_forward(df, a.min_train, a.step, progress=False, ridge=r, xi=x, shot_weight=sw)
    bl = best_blend(res_f)
    w = bl["w"] if bl else w
    shifts = {k: bias_shift(res_f, yc, pc) for k, (yc, pc) in DRAW_CALIB.items()}
    bt = bias_table(res_f)
    if not bt.empty:
        print(bt.to_string(index=False))
    print(f"  przesunięcia logitów (0 = brak istotnego obciążenia): {shifts}")
    f = prm.save(a.league, {"ridge": r, "xi": x, "blend_w": w, "shot_weight": sw, "draw_shift": shifts})
    print(f"\nNajlepsze: ridge={r}, xi={x}, shot_weight={sw}, waga modelu w miksie z rynkiem={w}  → zapisano {f}")
    print("Uwaga: strojenie na tych samych danych co ocena zawyża wynik - traktuj jako wskazówkę.")
    print(f"Aby Render używał tych parametrów: git add params && git commit -m 'parametry {a.league}' && git push")


# ------------------------------------------------------------------ dziennik
def cmd_log(a):
    conn = db.connect(config.DB_PATH)
    df = db.load_matches(conn, a.league)
    up = db.load_upcoming(conn, a.league, since=None if a.include_past else db.today())
    if up.empty:
        sys.exit("Brak nadchodzących meczów do zapisania (mecze z wcześniejszych dni są pomijane; --include-past tylko do testów).")
    P, p = _predictor(a, df)
    n = ledger.log_predictions(conn, P, up, a.league, blend_w=p["blend_w"])
    print(f"Zapisano {n} prognoz do dziennika (tabela predictions).")


def cmd_track(a):
    conn = db.connect(config.DB_PATH)
    s = ledger.settled(conn, a.league)
    print(f"Rozliczone: {len(s)} | oczekują na mecz: {ledger.pending(conn, a.league)}")
    if s.empty:
        print("Jeszcze nic do rozliczenia - poczekaj na wyniki zapisanych meczów.")
        return
    hist = db.load_matches(conn, a.league)
    hist = hist[~hist["fixture_id"].isin(s["fixture_id"])]  # historia bez rozliczanych meczów
    tab, sim = ledger.track_summary(s, a.min_edge, base=ledger.league_base_rates(hist))
    print("\nLog-loss na żywo (mniej = lepiej):\n")
    print(tab.to_string(index=False))
    print(f"\nSymulacja typów (edge>={a.min_edge:.0%}): {sim}")


def cmd_daily(a):
    """Codzienna rutyna: odśwież dane -> zapisz prognozy -> rozlicz."""
    conn = db.connect(config.DB_PATH)
    if a.source == "csv":
        y = _season_now()
        for yy in (y,):
            try:
                db.upsert_matches(conn, csvdata.parse_csv(csvdata.download(a.league, yy), a.league, yy))
            except Exception as e:  # noqa: BLE001
                print(f"  CSV {a.league} {yy}: błąd ({e})")
        try:
            db.upsert_matches(conn, csvdata.parse_csv(csvdata.download_fixtures(), a.league, None, only_div=True))
        except Exception as e:  # noqa: BLE001
            print(f"  fixtures.csv: błąd ({e})")
    else:
        from .fetch import ApiClient, fetch_missing_stats, fetch_season, fetch_upcoming
        c = ApiClient()
        fetch_season(c, conn, a.league, _season_now())
        fetch_missing_stats(c, conn, a.league, a.stats_limit)
        fetch_upcoming(c, conn, a.league, 7)
        print(f"  API: zapytań {c.used}, zostało {c.remaining}")
    print(f"  usunięto przeterminowanych meczów: {db.purge_stale_upcoming(conn)}")
    cmd_log(a)
    cmd_track(a)


def cmd_demo(a):
    from .synthetic import generate
    conn = db.connect(config.DB_PATH)
    df = generate(n_seasons=3)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    cols = [c for c in db.COLUMNS if c in df.columns]
    rows = df[cols].astype(object).where(df[cols].notna(), None).to_dict("records")
    db.upsert_matches(conn, rows)
    print(f"Wygenerowano {len(rows)} SZTUCZNYCH meczów (liga DEMO) w {config.DB_PATH}")
    print("Spróbuj:\n  python -m fbpred check --league DEMO\n  python -m fbpred backtest --league DEMO --min-train 380"
          "\n  python -m fbpred simulate --league DEMO\n  python -m fbpred log --league DEMO")


def cmd_history_init(a):
    res = history.update_from_source(history.resolve_leagues(a.league), _years(a.seasons))
    print(f"Gotowe: {len(res)} plików w {config.HISTORY_DIR}. Zacommituj katalog history/.")


def cmd_history_update(a):
    seasons = _years(a.seasons) if a.seasons else None
    res = history.update_from_source(history.resolve_leagues(a.leagues), seasons)
    print(f"Zaktualizowano {len(res)} plików; nowych meczów: {sum(r['dodane'] for r in res)}, "
          f"poprawionych: {sum(r['zmienione'] for r in res)}.")


def cmd_history_export(a):
    conn = db.connect(config.DB_PATH)
    res = history.export_from_db(conn, config.HISTORY_DIR, a.leagues.split(",") if a.leagues else None, a.include_demo)
    for name, st in res["files"].items():
        print(f"  {name}: +{st['dodane']} (razem {st['razem']})")
    print(f"Odrzucono: {len(res['rejected'])}, naprawiono usterek: {res['sanitized']}. Zacommituj katalog history/.")


def cmd_history_status(a):
    t = history.status(config.HISTORY_DIR)
    print(t.to_string(index=False) if not t.empty else f"Brak plików historii w {config.HISTORY_DIR}.")


def cmd_report(a):
    conn = db.connect(config.DB_PATH)
    txt = "# Raport dziennika prognoz\n\n" + "\n".join(
        report.ledger_report(conn, lg, a.min_edge) for lg in history.resolve_leagues(a.leagues))
    if a.out:
        from pathlib import Path
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(txt, encoding="utf-8")
        print(f"Zapisano {a.out}")
    else:
        print(txt)


def cmd_notify(a):
    conn = db.connect(config.DB_PATH)
    horizon = pd.Timestamp.today().normalize() + pd.Timedelta(days=a.days)
    blocks = []
    for lg in history.resolve_leagues(a.leagues):
        df, up = db.load_matches(conn, lg), db.load_upcoming(conn, lg, since=db.today())
        up = up[up["date"] <= horizon]
        if df.empty or up.empty:
            continue
        P, p = prm.build_predictor(df, lg)
        blocks.append(f"⚽ Prognozy {lg} (model statystyczny, nie gwarancja)")
        for r in up.head(a.limit).to_dict("records"):
            pred = apply_blend(P.predict(r["home"], r["away"], r.get("referee"), date=r["date"]), r, p["blend_w"])
            picks = [k for k in value_picks(pred, r, a.min_edge)]
            blocks.append(notify.format_match(pred, r, picks))
    if len(blocks) <= 1:
        print("Brak meczów w zadanym horyzoncie - nic nie wysyłam.")
        return
    text = "\n\n".join(blocks)
    if a.dry_run:
        print(text)
        return
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        print("Brak TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID - pomijam wysyłkę (użyj --dry-run, aby zobaczyć treść).")
        return
    print(f"Wysłano {notify.send_telegram(text)} wiadomość(i) na Telegram.")


def cmd_bootstrap(a):
    from . import bootstrap
    bootstrap.run_once(history.resolve_leagues(a.leagues), a.years, export_ledger=a.export_ledger)
    print(bootstrap.STATUS["message"])


def cmd_serve(a):
    from .web import create_app
    create_app().run(host=a.host, port=a.port, debug=False)


def main(argv=None):
    p = argparse.ArgumentParser(prog="fbpred", description="Prognozy prawdopodobieństw meczów piłkarskich")
    sp = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_, league=True):
        s = sp.add_parser(name, help=help_)
        if league:
            s.add_argument("--league", default=config.DEFAULT_LEAGUE, help="np. E0 (CSV) albo 39 (API)")
        s.set_defaults(fn=fn)
        return s

    s = add("fetch-csv", cmd_fetch_csv, "pobierz sezony z football-data.co.uk")
    s.add_argument("--seasons", default="2021-2024", help="np. 2021-2024 albo 2023,2024")
    s = add("import-csv", cmd_import_csv, "zaimportuj ręcznie pobrany plik CSV")
    s.add_argument("file")
    s.add_argument("--season", type=int, required=True)
    add("fetch-fixtures", cmd_fetch_fixtures, "nadchodzące mecze + kursy (football-data fixtures.csv)")
    s = add("fetch-api", cmd_fetch_api, "pobierz mecze+statystyki z API-Football")
    s.add_argument("--seasons", default="2023")
    s.add_argument("--stats-limit", type=int, default=80)
    s = add("upcoming", cmd_upcoming, "pobierz nadchodzące mecze i kursy (API)")
    s.add_argument("--days", type=int, default=7)
    add("check", cmd_check, "kontrola jakości danych")
    add("teams", cmd_teams, "lista drużyn w modelu")
    add("strengths", cmd_strengths, "ranking siły drużyn i sędziów")

    s = add("stats", cmd_stats, "statystyki sędziów / drużyn (kartki, rożne)")
    s.add_argument("--view", choices=["referees", "teams"], default="referees")
    s.add_argument("--seasons", type=int, default=2)
    s.add_argument("--min-matches", type=int, default=8)
    s = add("fatigue-test", cmd_fatigue, "zmęczenie / krótka przerwa: czy to realny efekt? (test na prognozach)", league=False)
    s.add_argument("--leagues", default="auto", help="auto = wszystkie ligi z bazy/history; wiele lig = większa moc testu")
    s.add_argument("--min-train", type=int, default=300)
    s.add_argument("--step", type=int, default=28)
    s.add_argument("--apply", action="store_true", help="zapisz istotne współczynniki do params_<liga>.json")
    s = add("recent", cmd_recent, "retrospektywa: co model przewidziałby przed ostatnimi meczami")
    s.add_argument("--days", type=int, default=10)
    s = add("profile", cmd_profile, "test metody: wyrównane kursy + przewaga gości => remis w 1. lub 2. połowie", league=False)
    s.add_argument("--leagues", default="auto", help="auto = wszystkie ligi w bazie (bez DEMO i LM) albo np. E0,D1")
    s.add_argument("--balance", type=float, default=10, help="próg 'wyrównane' w punktach procentowych")
    s = add("draws", cmd_draws, "ranking meczów pod rynki remisowe (HT, 2H, HT lub FT...)")
    s.add_argument("--include-past", action="store_true", help="także mecze z wcześniejszych dni (tylko demo/testy)")
    s.add_argument("--market", choices=list(draws_mod.MARKETS), default="ht_or_ft")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--top", type=int, default=15)
    s = add("predict", cmd_predict, "prognoza jednego meczu")
    s.add_argument("--home", required=True)
    s.add_argument("--away", required=True)
    s.add_argument("--referee")
    s.add_argument("--odds", type=float, nargs=3, metavar=("1", "X", "2"), help="kursy 1X2 do miksu z rynkiem")
    s.add_argument("--ridge", type=float)
    s.add_argument("--xi", type=float)
    s = add("upcoming-predict", cmd_upcoming_predict, "prognozy dla nadchodzących meczów z bazy")
    s.add_argument("--include-past", action="store_true", help="także mecze z wcześniejszych dni (tylko demo/testy)")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--min-edge", type=float, default=0.03)
    s = add("simulate", cmd_simulate, "symulacja tabeli do końca sezonu (Monte Carlo)")
    s.add_argument("--n", type=int, default=5000)
    s.add_argument("--top", type=int, default=4, help="ile miejsc to puchary")
    s.add_argument("--relegated", type=int, default=3)

    s = add("backtest", cmd_backtest, "backtest walk-forward z przedziałami ufności")
    s.add_argument("--min-train", type=int, default=300)
    s.add_argument("--step", type=int, default=14)
    s.add_argument("--out", help="zapisz predykcje do CSV")
    s.add_argument("--ridge", type=float)
    s.add_argument("--xi", type=float)
    s.add_argument("--shot-weight", type=float, help="waga celnych strzałów w bramkach (0-1)")
    s = add("tune", cmd_tune, "dobierz ridge/xi/miks z rynkiem i zapisz")
    s.add_argument("--min-train", type=int, default=300)
    s.add_argument("--step", type=int, default=28)
    s.add_argument("--ridges", type=float, nargs="+", default=[5, 10, 20])
    s.add_argument("--xis", type=float, nargs="+", default=[0.0007, 0.0019, 0.004])
    s.add_argument("--shot-weights", type=float, nargs="+", default=[0.25, 0.5])

    s = add("log", cmd_log, "zapisz prognozy nadchodzących meczów do dziennika")
    s.add_argument("--include-past", action="store_true", help="także mecze z wcześniejszych dni (tylko demo/testy)")
    s.add_argument("--ridge", type=float)
    s.add_argument("--xi", type=float)
    s = add("track", cmd_track, "raport z dziennika (rozliczone prognozy)")
    s.add_argument("--min-edge", type=float, default=0.03)
    s = add("daily", cmd_daily, "rutyna dnia: dane -> dziennik -> raport")
    s.add_argument("--source", choices=["csv", "api"], default="csv")
    s.add_argument("--stats-limit", type=int, default=60)
    s.add_argument("--min-edge", type=float, default=0.03)
    s.add_argument("--ridge", type=float)
    s.add_argument("--xi", type=float)
    s = add("history-init", cmd_history_init, "pobierz wiele sezonów do history/*.csv (jednorazowo)", league=False)
    s.add_argument("--league", default=config.DEFAULT_LEAGUE, help="np. E0 lub E0,D1,SP1,I1,F1,N1,P1,CL (CL wymaga tokenu)")
    s.add_argument("--seasons", default="2020-2025")
    s = add("history-update", cmd_history_update, "dopisz nowe mecze do history/*.csv (np. raz w tygodniu)", league=False)
    s.add_argument("--leagues", default="auto", help="auto = wszystkie ligi z history/, albo np. E0,D1,CL")
    s.add_argument("--seasons", help="domyślnie bieżący i poprzedni sezon")
    s = add("history-export", cmd_history_export, "zapisz mecze z lokalnej bazy SQLite do history/*.csv", league=False)
    s.add_argument("--leagues", help="np. E0 (domyślnie wszystkie oprócz DEMO)")
    s.add_argument("--include-demo", action="store_true", help="uwzględnij sztuczną ligę DEMO (nie zalecane)")
    add("history-status", cmd_history_status, "pokrycie danych w history/", league=False)
    s = add("report", cmd_report, "raport dziennika w markdown (CI)", league=False)
    s.add_argument("--leagues", default="auto", help="auto = wszystkie ligi z history/, albo np. E0,D1,CL")
    s.add_argument("--min-edge", type=float, default=0.03)
    s.add_argument("--out")
    s = add("notify", cmd_notify, "wyślij zestawienie prognoz na Telegram", league=False)
    s.add_argument("--leagues", default="auto", help="auto = wszystkie ligi z history/, albo np. E0,D1,CL")
    s.add_argument("--days", type=int, default=3)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--min-edge", type=float, default=0.05)
    s.add_argument("--dry-run", action="store_true")
    s = sp.add_parser("bootstrap", help="pierwsze zasilenie bazy (CSV) + prognozy do dziennika")
    s.add_argument("--leagues", default="auto", help="auto = wszystkie ligi z history/, albo np. E0,D1,CL")
    s.add_argument("--years", type=int, default=4)
    s.add_argument("--export-ledger", action="store_true", help="zapisz dziennik do ledger/predictions.csv (dla CI)")
    s.set_defaults(fn=cmd_bootstrap)
    add("demo", cmd_demo, "wygeneruj sztuczną ligę (bez internetu)", league=False)
    s = add("serve", cmd_serve, "uruchom aplikację webową", league=False)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
