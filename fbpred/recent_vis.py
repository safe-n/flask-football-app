"""Wizualna wersja zakładki „Ostatnie”: kafelki, pierścień trafności, pasek formy modelu, tabela w kolorach i wykres rynków.

Zielony = zaszło / trafione, czerwony = nie zaszło / pudło. Wszystko to czysty HTML+CSS (bez bibliotek), generowany tutaj,
z jednym wyjątkiem: teksty z danych (nazwy drużyn) są escapowane.
"""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd

from .backtest import CORNER_LINE, YELLOW_LINE, logloss_multi

MARKETS = [("Over 2.5", "y_over25", "p_over25", "b_over25"), ("BTTS", "y_btts", "p_btts", "b_btts"),
           ("Remis HT", "y_draw_ht", "p_draw_ht", "b_draw_ht"), ("Remis 2H", "y_draw_2h", "p_draw_2h", "b_draw_2h"),
           ("HT lub 2H", "y_draw_either", "p_draw_either", "b_draw_either"), ("HT lub FT", "y_draw_htft", "p_draw_htft", "b_draw_htft"),
           (f"Żółte >{YELLOW_LINE}", "y_yel", "p_yel", "b_yel"), (f"Rożne >{CORNER_LINE}", "y_cor", "p_cor", "b_cor")]


def _markets(res: pd.DataFrame):
    out = []
    for label, y, p, b in MARKETS:
        if y in res and p in res and res[y].notna().any() and res[p].notna().any():
            out.append((label, y, p, b))
    return out


def _pct(x) -> str:
    return f"{100 * x:.0f}%"


def stats_rows(res: pd.DataFrame) -> list[dict]:
    """Dla każdego rynku: ile razy zaszło, z ilu, średnie prawdopodobieństwo modelu i średnia ligi."""
    rows = []
    for label, y, p, b in _markets(res):
        ok = res[res[y].notna() & res[p].notna()]
        if ok.empty:
            continue
        base = float(ok[b].mean()) if b in ok and ok[b].notna().any() else None
        rows.append({"label": label, "k": int(ok[y].sum()), "n": len(ok), "freq": float(ok[y].mean()),
                     "model": float(ok[p].mean()), "base": base})
    return rows


def _ring(pct: float, text: str, sub: str) -> str:
    deg = 360 * max(0.0, min(pct, 1.0))
    return (f'<div class="kpi"><div class="ring" style="background:conic-gradient(var(--w) {deg:.0f}deg,var(--p) 0)">'
            f'<span>{escape(text)}</span></div><div class="ks">{escape(sub)}</div></div>')


def _tile(big: str, label: str, cls: str = "") -> str:
    return f'<div class="kpi"><div class="kv {cls}">{escape(big)}</div><div class="ks">{escape(label)}</div></div>'


def _cell(p, y) -> str:
    if pd.isna(p):
        return '<td class="mc">–</td>'
    if pd.isna(y):
        return f'<td class="mc">{_pct(p)}</td>'
    ok = int(y) == 1
    return f'<td class="mc {"yes" if ok else "no"}" title="{"zaszło" if ok else "nie zaszło"}">{_pct(p)}<i>{"✓" if ok else "✗"}</i></td>'


def dashboard(res: pd.DataFrame) -> str:
    if res.empty:
        return ""
    res = res.sort_values("date", ascending=False).reset_index(drop=True)
    y = res["y"].to_numpy(int)
    P = res[["p1", "px", "p2"]].to_numpy()
    pick = P.argmax(axis=1)
    hit = pick == y
    n = len(res)
    conf = float(P.max(axis=1).mean())
    ll = logloss_multi(P, y)
    lb = logloss_multi(res[["b1", "bx", "b2"]].to_numpy(), y)
    sr = stats_rows(res)

    kp = [_ring(hit.mean(), _pct(hit.mean()), f"typy 1X2 trafione {int(hit.sum())}/{n}"),
          _tile(_pct(conf), "średnia pewność modelu", ""),
          _tile(f"{ll:.2f}", f"log-loss (średnia ligi {lb:.2f})", "g" if ll < lb else "r")]
    if "k1" in res and res["k1"].notna().all():
        lm = logloss_multi(res[["k1", "kx", "k2"]].to_numpy(), y)
        kp.append(_tile(f"{lm:.2f}", "log-loss rynku (im mniej, tym lepiej)", "g" if lm < ll else "r"))
    html = ['<div class="rv"><div class="kpis">' + "".join(kp) + "</div>"]

    # pasek formy: ostatnie mecze od najstarszego (lewa) do najnowszego (prawa)
    chron = list(zip(res["home"][::-1], res["away"][::-1], res["hg"][::-1], res["ag"][::-1], hit[::-1]))
    chips = "".join(f'<span class="fc {"yes" if h else "no"}" title="{escape(str(a))} – {escape(str(b))} {int(c)}–{int(d)}">{"✓" if h else "✗"}</span>'
                    for a, b, c, d, h in chron)
    html.append(f'<p class="cap">Forma modelu (typ 1X2, od najstarszego do najnowszego):</p><div class="fstrip">{chips}</div>')

    # wykres rynków: słupek = jak często zaszło, znacznik = średnia modelu, kropka = średnia ligi
    if sr:
        html.append('<h2>Trafność rynków</h2><p class="cap">Zielony słupek = jak często zdarzenie zaszło w tych meczach. '
                    'Biała kreska = średnie prawdopodobieństwo modelu, kropka = średnia ligi. Gdy słupek kończy się blisko kreski, model „mówił prawdę”.</p>')
        for r in sr:
            base = f'<i class="bd" style="left:{100 * r["base"]:.0f}%" title="średnia ligi {_pct(r["base"])}"></i>' if r["base"] is not None else ""
            diff = 100 * (r["freq"] - r["model"])
            cls = "g" if diff >= 5 else "r" if diff <= -5 else ""
            html.append(f'<div class="mrow"><span class="ml">{escape(r["label"])}</span>'
                        f'<span class="mt"><span class="mf" style="width:{100 * r["freq"]:.0f}%"></span>'
                        f'<i class="mm" style="left:{100 * r["model"]:.0f}%" title="model {_pct(r["model"])}"></i>{base}</span>'
                        f'<span class="mv">{r["k"]}/{r["n"]} · {_pct(r["freq"])}<small class="{cls}"> (model {_pct(r["model"])}, {diff:+.0f} pp)</small></span></div>')

    # tabela w kolorach, z proporcją TAK/NIE nad każdą kolumną
    mk = _markets(res)
    head = ['<th>mecz</th><th>wynik</th><th>1X2 (model)</th>']
    prop = ['<td></td><td></td><td>' + _bar(int(hit.sum()), n) + "</td>"]
    for label, yc, pc, bc in mk:
        ok = res[yc].dropna()
        head.append(f"<th>{escape(label)}</th>")
        prop.append("<td>" + _bar(int(ok.sum()), len(ok)) + "</td>")
    body = []
    for i, r in res.iterrows():
        res_l = "1X2"[y[i]]
        cells = [f'<td class="mt1"><span class="dt">{pd.to_datetime(r["date"]).strftime("%d.%m")}</span> {escape(str(r["home"]))} – {escape(str(r["away"]))}</td>',
                 f'<td class="sc">{int(r["hg"])}–{int(r["ag"])}</td>',
                 f'<td class="mc {"yes" if hit[i] else "no"}" title="wynik: {res_l}">{"1X2"[pick[i]]} <small>{_pct(P[i].max())}</small><i>{"✓" if hit[i] else "✗"}</i></td>']
        for label, yc, pc, bc in mk:
            cells.append(_cell(r.get(pc), r.get(yc)))
        body.append("<tr>" + "".join(cells) + "</tr>")
    html.append('<h2>Mecz po meczu</h2><p class="cap">Procent to prognoza modelu przed meczem. Zielone pole: zdarzenie zaszło ✓, czerwone: nie zaszło ✗. '
                'W 1X2 zielone = typ modelu (najwyższe %) trafiony. Pod nagłówkiem pasek: proporcja zielone/czerwone w danej kolumnie.</p>'
                '<div class="card rt"><table><thead><tr>' + "".join(head) + "</tr><tr class=\"pr\">" + "".join(prop)
                + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div></div>")
    return "".join(html)


def _bar(k: int, n: int) -> str:
    if n <= 0:
        return ""
    g = 100 * k / n
    return (f'<div class="pbar" title="zaszło {k} z {n}"><span class="pg1" style="width:{g:.0f}%"></span></div>'
            f'<small class="pn">{k}/{n} ({g:.0f}%)</small>')
