"""Klocki HTML (kafelki, karta meczu, sekcje rynków, wizualizacje) - osobno od Flaska, żeby dało się testować."""
from __future__ import annotations

import math

from markupsafe import escape

from . import betmarkets as bm, features as ft
from .odds import edge, kelly, valid


DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]


def start_time(date_str):
    """Czas startu (UTC, z The Odds API albo z formularza). None, gdy znamy tylko dzień."""
    import pandas as pd
    s = str(date_str or "").strip()
    if len(s) < 16 or ":" not in s:
        return None
    try:
        return pd.Timestamp(s[:16].replace("T", " "), tz="UTC")
    except (ValueError, TypeError):
        return None


def when(date_str, now=None) -> dict:
    """Godzina startu w czasie lokalnym i status: przed / wkrótce / trwa / zakończony?"""
    import pandas as pd
    from . import config
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    t = start_time(date_str)
    if t is None:
        d = pd.Timestamp(str(date_str)[:10])
        today = now.tz_convert(config.TZ).normalize().tz_localize(None)
        st = "today" if d == today else ("past" if d < today else "future")
        return {"day": str(date_str)[:10], "label": f"{DNI[d.weekday()]} {d:%d.%m}, godz. nieznana", "time": "",
                "status": st, "badge": "dziś" if st == "today" else ("minął" if st == "past" else "")}
    loc = t.tz_convert(config.TZ)
    mins = (t - now).total_seconds() / 60
    if mins > 0:
        status = "soon" if mins <= 90 else "future"
        badge = (f"za {int(mins)} min" if mins < 60 else f"za {int(mins // 60)} h {int(mins % 60)} min") if mins <= 12 * 60 else ""
    elif -mins <= config.MATCH_HOURS * 60:
        status, badge = "live", "▶ rozpoczęty"
    else:
        status, badge = "done", "zakończony?"
    return {"day": f"{loc:%Y-%m-%d}", "label": f"{DNI[loc.weekday()]} {loc:%d.%m} {loc:%H:%M}", "time": f"{loc:%H:%M}",
            "status": status, "badge": badge}


def status_chip(w: dict) -> str:
    if not w["badge"]:
        return ""
    cls = {"live": "live", "soon": "soon", "done": "done", "today": "soon", "past": "done"}.get(w["status"], "")
    return f'<span class="chip {cls}">{escape(w["badge"])}</span>'


def pct(x, d=0) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{100 * x:.{d}f}%"


def cls_for(p, base, hl_pp: float) -> str:
    if p is None or base is None:
        return ""
    d = 100 * (p - base)
    if d >= hl_pp:
        return "up2"
    if d >= hl_pp / 2:
        return "up1"
    if d <= -hl_pp:
        return "dn2"
    if d <= -hl_pp / 2:
        return "dn1"
    return ""


def tile(label: str, p, base=None, base_label="śr.", hl_pp: float = 8, title: str = "") -> str:
    sub = ""
    if base is not None:
        d = round(100 * (p - base))
        sub = f"<small>{escape(base_label)} {pct(base)} ({'±0' if d == 0 else f'{d:+d}'})</small>"
    t = f' title="{escape(title)}"' if title else ""
    return f'<div class="b {cls_for(p, base, hl_pp)}"{t}>{escape(label)}<b>{pct(p)}</b>{sub}</div>'


def fair(p) -> str:
    return f"{1 / p:.2f}" if p and p > 0.005 else "–"


def short(name: str) -> str:
    """„De Vries L.” -> „De Vries”, „Kwon S.W.” -> „Kwon” (nazwisko bez inicjałów)."""
    toks = str(name or "").split()
    while len(toks) > 1 and toks[-1].endswith("."):
        toks.pop()
    return " ".join(toks)


def tiles_for(pred: dict, line: float | None, hl_pp: float) -> str:
    m, base = pred["m"], pred["base"] or {}
    a, b = short(pred["p1"]), short(pred["p2"])
    pm = pred.get("p_market")
    out = [tile(a, m["p1"], pm, "rynek", hl_pp, f"{pred['p1']} wygra: model (Elo zmieszane z rynkiem) vs kurs bez marży"),
           tile(b, m["p2"], None if pm is None else 1 - pm, "rynek", hl_pp, f"{pred['p2']} wygra")]
    ln = line if line else (22.5 if pred["best_of"] == 3 else 38.5)
    p_over = sum(v for k, v in m["games_pmf"].items() if k > float(ln))
    out.append(tile(f"Over {ln:g}", p_over, (base.get("over") or {}).get(f"{float(ln)}"), "śr.", hl_pp,
                    f"Średnia liczba gemów: model {m['games_mean']:.1f}, nawierzchnia {base.get('games_mean', float('nan')):.1f}"))
    out.append(tile("Tie-break", m["p_tb"], base.get("p_tb"), "śr.", hl_pp, "Co najmniej jeden tie-break w meczu"))
    need = pred["best_of"] // 2 + 1
    out.append(tile(f"{need}:0 / 0:{need}", m["straight"], base.get("straight"), "śr.", hl_pp, "Mecz bez straconego seta przez zwycięzcę"))
    return '<div class="row">' + "".join(out) + "</div>"


def add_btn(leg: str, label: str = "＋") -> str:
    return f'<button class="add" data-id="{escape(leg)}">{escape(label)}</button>'


def odds_cell(p, o) -> str:
    if not valid(o):
        return "<td>–</td><td>–</td>"
    e = edge(p, float(o))
    c = "pos" if e > 0 else "neg"
    return f'<td>{float(o):.2f}</td><td class="{c}">{100 * e:+.0f}%</td>'


def sections(pred: dict, date: str, row: dict | None = None) -> str:
    """Wszystkie rynki w grupach: szansa, uczciwy kurs, kurs z bazy (jeśli jest), przewaga, przycisk do zestawienia."""
    cat = bm.catalogue(pred)
    row = row or {}
    html = []
    for g in bm.GROUPS:
        items = [(k, v) for k, v in cat.items() if v["group"] == g]
        if not items:
            continue
        rows = []
        for k, v in items:
            leg = bm.leg_id(pred["tour"], date, pred["p1"], pred["p2"], pred["surface"], pred["best_of"], k)
            o = bm.book_odds(row, k)
            rows.append(f'<tr><td class="l">{escape(v["label"])}</td><td>{pct(v["p"])}</td><td>{fair(v["p"])}</td>'
                        f'{odds_cell(v["p"], o)}<td>{add_btn(leg)}</td></tr>')
        html.append(f'<div class="card"><b>{escape(g)}</b><table><tr><th class="l">typ</th><th>szansa</th><th>uczciwy kurs</th>'
                    f'<th>kurs</th><th>przewaga</th><th></th></tr>{"".join(rows)}</table></div>')
    return '<div class="grid">' + "".join(html) + "</div>"


def games_chart(pred: dict, line: float | None = None) -> str:
    pmf = pred["m"]["games_pmf"]
    if not pmf:
        return ""
    ks = list(range(min(pmf), max(pmf) + 1))
    mx = max(pmf.values())
    ln = line or (22.5 if pred["best_of"] == 3 else 38.5)
    bars = "".join(f'<i class="{"hi" if k > ln else ""}" style="height:{max(2, 100 * pmf.get(k, 0) / mx):.0f}%" '
                   f'title="{k} gemów: {pct(pmf.get(k, 0), 1)}"></i>' for k in ks)
    return (f'<div class="cap">Rozkład liczby gemów (zielone = over {ln:g}); średnio {pred["m"]["games_mean"]:.1f}</div>'
            f'<div class="gpmf">{bars}</div><div class="gax"><span>{ks[0]}</span><span>{ks[len(ks) // 2]}</span><span>{ks[-1]}</span></div>')


def player_block(df, pred: dict, i: int) -> str:
    name, tour, surf = pred["p1"] if i == 0 else pred["p2"], pred["tour"], pred["surface"]
    info = pred["info"][i]
    f = ft.form(df, tour, name, 8)
    fs = ft.form(df, tour, name, 6, surface=surf)
    w, l = ft.surface_record(df, tour, name, surf)
    fat = ft.fatigue(df, tour, name)
    rank = f"#{int(info['rank'])}" if info.get("rank") == info.get("rank") and info.get("rank") else "bez rankingu"
    fat_txt = (f"ostatnie 7 dni: {fat['m7']} mecz. / {fat['g7']} gemów; 14 dni: {fat['m14']} / {fat['g14']}"
               + (f"; od ostatniego meczu {fat['days_since']} dni" if fat["days_since"] is not None else ""))
    warn = " ⚠" if fat["g7"] >= 80 else ""
    return (f'<div class="card"><b>{escape(name)}</b> <span class="m">{rank} · Elo {info["elo"]:.0f} · {escape(surf)} {info["elo_surface"]:.0f} · '
            f'meczów w bazie {info["n"]}</span>'
            f'<div class="pgrow"><span class="lb">forma</span>{f["html"] or "<span class=m>brak</span>"} <span class="m">{f["w"]}/{f["n"]}</span></div>'
            f'<div class="pgrow"><span class="lb">{escape(surf)}</span>{fs["html"] or "<span class=m>brak</span>"} '
            f'<span class="m">12 mies.: {w}–{l}</span></div>'
            f'<div class="m">Zmęczenie: {fat_txt}{warn}</div></div>')


def h2h_row(df, pred: dict) -> str:
    h = ft.h2h(df, pred["tour"], pred["p1"], pred["p2"])
    if not h["n"]:
        return '<div class="pgrow"><span class="lb">H2H</span><span class="m">brak spotkań w bazie</span></div>'
    p = pred["m"]["p1"]
    flag = ft.underdog_flag(h, max(p, 1 - p), p >= 0.5)
    fl = ' <span class="flag" title="Faworyt rzadko wygrywa z tym rywalem (mała próba - słaba wartość predykcyjna)">⚑</span>' if flag else ""
    return (f'<div class="pgrow"><span class="lb">H2H {escape(short(pred["p1"]))}</span>{h["html"]}'
            f'<span class="m">{h["w1"]}–{h["w2"]}</span>{fl}</div>')


def market_bars(rows: list[tuple]) -> str:
    """(etykieta, faktycznie, model, średnia) -> słupki jak w fbpred: słupek = zaszło, biała kreska = model, kropka = średnia."""
    out = []
    for lab, real, model, base in rows:
        if real is None:
            continue
        dot = f'<span class="bd" style="left:{100 * base:.0f}%"></span>' if base is not None else ""
        out.append(f'<div class="mrow"><span class="ml">{escape(lab)}</span><span class="mt"><span class="mf" style="width:{100 * real:.0f}%"></span>'
                   f'<span class="mm" style="left:{100 * model:.0f}%"></span>{dot}</span>'
                   f'<span class="mv">{pct(real)} <small>model {pct(model)}{"" if base is None else " · śr. " + pct(base)}</small></span></div>')
    return "".join(out)


def ring(p: float, label: str) -> str:
    col = "var(--up)" if p >= 0.5 else "var(--dn)"
    return (f'<div class="kpi"><div class="ring" style="background:conic-gradient({col} {360 * p:.0f}deg, var(--bar) 0)">'
            f'<span>{pct(p)}</span></div><div class="ks">{escape(label)}</div></div>')


def kpi(v: str, label: str, good: bool | None = None) -> str:
    c = "" if good is None else ("g" if good else "r")
    return f'<div class="kpi"><div class="kv {c}">{escape(v)}</div><div class="ks">{escape(label)}</div></div>'


def kelly_txt(p, o) -> str:
    return f"{100 * kelly(p, float(o)):.1f}%" if valid(o) else "–"
