"""Interfejs wiersza poleceń:  python -m fbpred <komenda> --help"""
from __future__ import annotations

import argparse
import difflib
import sys
from datetime import date

import numpy as np
import pandas as pd

from . import config, csvdata, db, ledger, params as prm, quality
from .backtest import (best_blend, betting_sim, calibration, compare_report, summarize, walk_forward)
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
            rows = csvdata.parse_csv(csvdata.download(a.league, y), a.league, y)
        except Exception as e:  # noqa: BLE001
            print(f"  {a.league} {y}: błąd ({e})")
            continue
        db.upsert_matches(conn, rows)
        print(f"  {a.league} {y}/{y + 1}: {len(rows)} meczów")


def cmd_import_csv(a):
    conn = db.connect(config.DB_PATH)
    text = open(a.file, encoding="utf-8-sig", errors="replace").read()
    rows = csvdata.parse_csv(text, a.league, a.season)
    db.upsert_matches(conn, rows)
    print(f"Zaimportowano {len(rows)} meczów ({a.league} {a.season}).")


def cmd_fetch_fixtures(a):
    conn = db.connect(config.DB_PATH)
    rows = csvdata.parse_csv(csvdata.download_fixtures(), a.league, None, only_div=True)
    db.upsert_matches(conn, rows)
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
    print(P.goals.strengths().to_string())
    print(f"\nPrzewaga domowa: {np.exp(P.goals.ha):.2f}x goli, rho (korekta niskich wyników): {P.goals.rho:+.3f}")
    if P.yellow and P.yellow.r:
        n = df["referee"].value_counts()
        t = pd.DataFrame({"mnoznik_kartek": {r: float(np.exp(v)) for r, v in P.yellow.r.items()}})
        t["mecze"] = t.index.map(lambda r: int(n.get(r, 0)))
        t = t[t["mecze"] >= 8].sort_values("mnoznik_kartek", ascending=False).round(3)
        print("\nSędziowie (mnożnik oczekiwanych żółtych kartek, min. 8 meczów):")
        print(pd.concat([t.head(8), t.tail(8)]).drop_duplicates().to_string())


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
    up = db.load_upcoming(conn, a.league)
    if up.empty:
        sys.exit("Brak nadchodzących meczów w bazie (komendy: fetch-fixtures, upcoming, demo).")
    P, p = _predictor(a, df)
    for r in up.head(a.limit).to_dict("records"):
        pred = apply_blend(P.predict(r["home"], r["away"], r.get("referee")), r, p["blend_w"])
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
    p = {**prm.load(a.league), **{k: v for k, v in (("ridge", a.ridge), ("xi", a.xi)) if v is not None}}
    print(f"Backtest: {len(df)} meczów, trening min. {a.min_train}, krok {a.step} dni, ridge={p['ridge']}, xi={p['xi']}")
    res = walk_forward(df, a.min_train, a.step, ridge=p["ridge"], xi=p["xi"])
    print("\nLog-loss (mniej = lepiej). 'vs_baseline_%' > 0: model lepszy od średniej ligowej.\n")
    print(summarize(res).to_string(index=False))
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
    _, r, x, w = best
    f = prm.save(a.league, {"ridge": r, "xi": x, "blend_w": w})
    print(f"\nNajlepsze: ridge={r}, xi={x}, waga modelu w miksie z rynkiem={w}  → zapisano {f}")
    print("Uwaga: strojenie na tych samych danych co ocena zawyża wynik - traktuj jako wskazówkę.")


# ------------------------------------------------------------------ dziennik
def cmd_log(a):
    conn = db.connect(config.DB_PATH)
    df = db.load_matches(conn, a.league)
    up = db.load_upcoming(conn, a.league)
    if up.empty:
        sys.exit("Brak nadchodzących meczów do zapisania.")
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

    s = add("predict", cmd_predict, "prognoza jednego meczu")
    s.add_argument("--home", required=True)
    s.add_argument("--away", required=True)
    s.add_argument("--referee")
    s.add_argument("--odds", type=float, nargs=3, metavar=("1", "X", "2"), help="kursy 1X2 do miksu z rynkiem")
    s.add_argument("--ridge", type=float)
    s.add_argument("--xi", type=float)
    s = add("upcoming-predict", cmd_upcoming_predict, "prognozy dla nadchodzących meczów z bazy")
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
    s = add("tune", cmd_tune, "dobierz ridge/xi/miks z rynkiem i zapisz")
    s.add_argument("--min-train", type=int, default=300)
    s.add_argument("--step", type=int, default=28)
    s.add_argument("--ridges", type=float, nargs="+", default=[5, 10, 20])
    s.add_argument("--xis", type=float, nargs="+", default=[0.0007, 0.0019, 0.004])

    s = add("log", cmd_log, "zapisz prognozy nadchodzących meczów do dziennika")
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
    add("demo", cmd_demo, "wygeneruj sztuczną ligę (bez internetu)", league=False)
    s = add("serve", cmd_serve, "uruchom aplikację webową", league=False)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
