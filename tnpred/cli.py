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
            try:
                df = tdata.download(tour, y)
                tdata.save_history(df, tour, y)
                print(f"{tour} {y}: {len(df)} meczów -> {f}")
            except Exception as e:  # noqa: BLE001
                bad += 1
                print(f"{tour} {y}: BŁĄD {e}")
    total = len(years) * len(a.tours.split(","))
    print(f"\nPodsumowanie: pobrano {total - bad} z {total} plików.")
    if bad and bad == total:
        print("NIC nie udało się pobrać. Najczęstsze przyczyny: brak 'openpyxl' w requirements.txt albo strona tennis-data.co.uk "
              "nie odpowiada / blokuje serwer. Aplikacja na Renderze i tak spróbuje pobrać dane sama (zakładka Dane).")
        raise SystemExit(1)


def cmd_tune(a):
    from .model import save_params
    m = _model()
    p = {"s0": m.fit_s0(verbose=True), "blend_w": m.fit_blend(verbose=True), "fitted_at": pd.Timestamp.utcnow().isoformat(),
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
    f.set_defaults(fn=cmd_fetch_history)
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
