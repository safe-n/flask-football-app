"""Komendy: python -m tnpred <komenda>. Pomoc: python -m tnpred -h"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from . import __version__, backtest, config, tdata


def _model():
    from .model import TennisModel
    df = tdata.load_history_dir()
    if df.empty and config.DEMO:
        from . import synthetic
        df = synthetic.generate()
    if df.empty:
        raise SystemExit("Brak historii w folderze tennis_history/ - uruchom najpierw: python -m tnpred fetch-history")
    return TennisModel(df)


def cmd_fetch_history(a):
    now = pd.Timestamp.today()
    years = range(now.year - a.years + 1, now.year + 1)
    bad = 0
    for tour in a.tours.split(","):
        for y in years:
            f = tdata.history_file(tour, y)
            if f.exists() and y < now.year and not a.force:
                print(f"{tour} {y}: jest już {f.name} - pomijam (--force, by pobrać ponownie)")
                continue
            manual = config.HISTORY_DIR / tour / f"{y}.xlsx"
            if manual.exists() and not a.force:
                print(f"{tour} {y}: jest plik pobrany ręcznie ({tour}/{manual.name}) - pomijam")
                continue
            try:
                df, src = tdata.download_any(tour, y)
                tdata.save_history(df, tour, y)
                print(f"{tour} {y}: {len(df)} meczów ({src}) -> {f}")
            except Exception as e:  # noqa: BLE001
                bad += 1
                print(f"{tour} {y}: BŁĄD {e}")
    total = len(years) * len(a.tours.split(","))
    print(f"\nPodsumowanie: pobrano {total - bad} z {total} plików.")
    if bad:
        print("Część plików niedostępna. HTTP 403 = strona blokuje ten komputer/serwer (GitHub, Render) - uruchom komendę u siebie w domu. "
              "HTTP 404 = zmienił się adres plików - skopiuj link z https://tennis-data.co.uk/alldata.php i wpisz wzór do .env "
              "(TN_TDATA_ATP_URL / TN_TDATA_WTA_URL). Pliki można też wrzucić ręcznie do tennis_history/ATP/ i tennis_history/WTA/.")
    if tdata.load_history_dir().empty:
        print("Brak jakiejkolwiek historii - przerywam.")
        raise SystemExit(1)
    if not a.no_tune:
        print("\nStrojenie modelu (ok. pół minuty)...")
        cmd_tune(a)
        print("Gotowe. Teraz Commit + Push (GitHub Desktop), żeby Render dostał nową historię i parametry.")


def cmd_push_history(a):
    """Pobiera bieżący rok z tennis-data.co.uk NA TWOIM KOMPUTERZE i wysyła go do gałęzi ledger-data (folder tennis/history).
    Nie zmienia plików w folderze repo (GitHub Desktop nic nie pokaże) i nie wywołuje przebudowy Rendera -
    aplikacja sama sprawdza tę gałąź co kilka godzin."""
    import json
    from datetime import datetime
    from . import gh_store
    from .model import TennisModel
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"=== {stamp} tnpred {__version__}: aktualizacja wyników ===")
    if not gh_store.enabled():
        raise SystemExit("Brak GITHUB_TOKEN / GITHUB_REPO w pliku .env w folderze repo (README: „Codzienna aktualizacja”).")
    now = pd.Timestamp.today()
    years = [now.year] + ([now.year - 1] if now.month == 1 else [])
    remote = gh_store.list_dir(gh_store.history_path())
    fresh, sent = [], 0
    for tour in a.tours.split(","):
        for y in years:
            name = f"{tour}_{y}.csv"
            try:
                df, src = tdata.download_any(tour, y)
            except Exception as e:  # noqa: BLE001
                print(f"{tour} {y}: BŁĄD {e}")
                continue
            fresh.append(df)
            text = tdata.history_text(df)
            last = pd.to_datetime(df["date"]).max()
            if remote.get(name) == gh_store.git_sha(text):
                print(f"{tour} {y}: bez zmian ({len(df)} meczów, ostatni {last:%Y-%m-%d})")
                continue
            gh_store.push(text, gh_store.history_path(name), message=f"tennis history: {name} ({len(df)} meczów, do {last:%Y-%m-%d})")
            sent += 1
            print(f"{tour} {y}: wysłano {len(df)} meczów (ostatni {last:%Y-%m-%d})")
    if not fresh:
        raise SystemExit("Nic nie pobrano - sprawdź internet albo adresy plików (README).")
    if sent and not a.no_tune:
        base = tdata.load_history_dir()
        allm = pd.concat([base] + fresh, ignore_index=True).drop_duplicates(
            subset=["tour", "date", "winner", "loser", "tournament"], keep="last")
        m = TennisModel(allm)
        s0 = m.fit_s0()
        params = {"s0": s0, "sigma": m.fitted_sigma, "blend_w": m.fit_blend(), "fitted_at": pd.Timestamp.utcnow().isoformat(),
                  "matches": int(len(m.df))}
        text = json.dumps(params, indent=2, ensure_ascii=False)
        gh_store.push(text, gh_store.history_path("model.json"), message="tennis: parametry modelu")
        print("wysłano parametry modelu:", ", ".join(f"{k} {v}" for k, v in sorted(s0.items())))
        _push_style(m)
    print(f"Gotowe: {sent} plik(ów) wysłanych. Aplikacja wczyta je przy najbliższym sprawdzeniu (co ok. 3 h) "
          f"albo od razu po kliknięciu „Odśwież teraz” w zakładce Dane.")


def _push_style(m) -> dict:
    """Liczy styl TB zawodników (kilkadziesiąt s), zapisuje lokalnie i wysyła do gałęzi z historią (Render wczyta)."""
    from . import gh_store, style
    st = style.compute(m)
    style.save(st)
    if gh_store.enabled():
        gh_store.push(style.to_text(st), gh_store.history_path("style.json"), message="tennis: styl zawodników (TB)")
    n = sum(len(v) for v in st["players"].values())
    print(f"styl zawodników: {n} zawodników ({', '.join(st['tours'])})" + (" - wysłano" if gh_store.enabled() else ""))
    return st


def cmd_style(a):
    """Policz (i wyślij) styl TB zawodników bez pobierania wyników; pokaż skrajnych."""
    from . import style
    m = _model()
    st = _push_style(m) if not a.show else style.load()
    for t in st.get("tours", []):
        print(f"\n{t}: najwięcej / najmniej tie-breaków ponad model (styl po ściągnięciu, liczba meczów)")
        for p, v, n in style.top(st, t, a.n):
            print(f"  {p:24s} {100 * v:+5.1f} pp  ({n})")


def cmd_install_task(a):
    """Windows: zadanie w Harmonogramie zadań uruchamiające aktualizuj_tenis_auto.bat co N godzin (gdy komputer jest włączony)."""
    import os
    import subprocess
    bat = config.ROOT / "aktualizuj_tenis_auto.bat"
    name = "Tenis - aktualizacja wynikow"
    if os.name != "nt":
        raise SystemExit("To polecenie działa na Windows.")
    if a.remove:
        r = subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True, text=True)
        print(r.stdout or r.stderr)
        return
    if not bat.exists():
        raise SystemExit(f"Brak pliku {bat}")
    r = subprocess.run(["schtasks", "/Create", "/SC", "HOURLY", "/MO", str(a.every), "/TN", name, "/TR", f'"{bat}"', "/F"],
                       capture_output=True, text=True)
    print(r.stdout or r.stderr)
    if r.returncode == 0:
        print(f"Zadanie „{name}” uruchamia się co {a.every} h, gdy komputer jest włączony. Dziennik: {config.ROOT / 'tennis_update.log'}")


def cmd_tune(a):
    from .model import save_params
    m = _model()
    s0 = m.fit_s0(verbose=True)
    p = {"s0": s0, "sigma": m.fitted_sigma, "blend_w": m.fit_blend(verbose=True), "fitted_at": pd.Timestamp.utcnow().isoformat(),
         "matches": int(len(m.df))}
    save_params(p)
    print(f"zapisano {config.PARAMS_DIR / 'model.json'}")


def cmd_backtest(a):
    m = _model()
    bt = backtest.rows(m, days=a.days, tour=a.tour, limit=a.limit)
    s = backtest.summary(bt)
    print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in s.items()}, indent=1, ensure_ascii=False))
    print("ROI mieszanka:", backtest.roi_value(bt), "| samo Elo:", backtest.roi_value(bt, use="p_elo"))
    for c in backtest.calibration(bt.p, bt.y):
        print(f"  {c['przedzial']:>8}  n={c['n']:5d}  model {100 * c['model']:.0f}%  faktycznie {100 * c['faktycznie']:.0f}%")


def cmd_predict(a):
    m = _model()
    p = m.predict(a.tour, a.surface, a.bo, a.p1, a.p2, a.o1, a.o2)
    s = p["m"]
    print(f"{p['p1']} – {p['p2']} ({p['tour']}, {p['surface']}, Bo{p['best_of']})")
    print(f"  zwycięzca: {100 * s['p1']:.1f}% / {100 * s['p2']:.1f}%  (Elo {100 * p['p_elo']:.1f}%"
          + (f", rynek {100 * p['p_market']:.1f}%)" if p["p_market"] is not None else ")"))
    print(f"  sety: " + ", ".join(f"{k} {100 * v:.0f}%" for k, v in s["sets"].items()))
    print(f"  gemy średnio {s['games_mean']:.1f}; " + ", ".join(f"O{k} {100 * v:.0f}%" for k, v in s["over"].items()))
    print(f"  tie-break w meczu {100 * s['p_tb']:.0f}%, 1. set dla {p['p1']} {100 * s['set1_p1']:.0f}%")
    for w in p["warn"]:
        print("  ⚠", w)


def cmd_serve(a):
    from .web import create_app
    create_app(background=a.refresh).run(host="0.0.0.0", port=a.port, debug=False)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tnpred", description=f"Prognozy tenisowe {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch-history", help="pobierz CSV z tennis-data.co.uk do tennis_history/")
    f.add_argument("--years", type=int, default=config.YEARS)
    f.add_argument("--tours", default=",".join(config.TOURS))
    f.add_argument("--force", action="store_true")
    f.add_argument("--no-tune", action="store_true", help="nie stroj modelu po pobraniu")
    f.set_defaults(fn=cmd_fetch_history)
    ph = sub.add_parser("push-history", help="pobierz bieżący rok i wyślij do GitHuba (gałąź ledger-data) - codzienna aktualizacja")
    ph.add_argument("--tours", default=",".join(config.TOURS))
    ph.add_argument("--no-tune", action="store_true")
    ph.set_defaults(fn=cmd_push_history)
    it = sub.add_parser("install-task", help="Windows: zaplanuj push-history co kilka godzin")
    it.add_argument("--every", type=int, default=4, help="co ile godzin (domyślnie 4)")
    it.add_argument("--remove", action="store_true", help="usuń zaplanowane zadanie")
    it.set_defaults(fn=cmd_install_task)
    sy = sub.add_parser("style", help="policz styl TB zawodników -> tennis_params/style.json (+ wyślij do GitHuba)")
    sy.add_argument("--show", action="store_true", help="tylko pokaż zapisany")
    sy.add_argument("-n", type=int, default=10)
    sy.set_defaults(fn=cmd_style)
    t = sub.add_parser("tune", help="dobierz s0 (serwis) i wagę rynku -> tennis_params/model.json")
    t.set_defaults(fn=cmd_tune)
    b = sub.add_parser("backtest", help="walk-forward: model vs rynek, gemy, tie-breaki, kalibracja")
    b.add_argument("--days", type=int, default=365)
    b.add_argument("--tour")
    b.add_argument("--limit", type=int)
    b.set_defaults(fn=cmd_backtest)
    p = sub.add_parser("predict", help="prognoza jednego meczu")
    p.add_argument("p1")
    p.add_argument("p2")
    p.add_argument("--tour", default="ATP")
    p.add_argument("--surface", default="Hard")
    p.add_argument("--bo", type=int, default=3)
    p.add_argument("--o1", type=float)
    p.add_argument("--o2", type=float)
    p.set_defaults(fn=cmd_predict)
    s = sub.add_parser("serve", help="lokalny serwer (http://localhost:5001)")
    s.add_argument("--port", type=int, default=5001)
    s.add_argument("--refresh", action="store_true", help="pobierz dane z internetu przy starcie")
    s.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    a.fn(a)
