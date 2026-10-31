"""Eksport do PDF (reportlab, czcionka DejaVu z polskimi znakami): Ostatnie, Dziennik i Zestawienie - wszystkie ligi w jednym pliku.

Kolory jak w aplikacji: zielone = zaszło / trafione, czerwone = nie zaszło / pudło.
"""
from __future__ import annotations

import io
from datetime import datetime
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import __version__
from .recent_vis import _markets

FONTS = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("DV", str(FONTS / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", str(FONTS / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV", boldItalic="DV-B")

GREEN_BG, GREEN_FG = colors.HexColor("#cfeedd"), colors.HexColor("#0e6b37")
RED_BG, RED_FG = colors.HexColor("#f6d3d0"), colors.HexColor("#a32a20")
GREY, HEAD_BG = colors.HexColor("#5b6672"), colors.HexColor("#e8edf2")

H1 = ParagraphStyle("h1", fontName="DV-B", fontSize=16, leading=20, spaceAfter=4)
H2 = ParagraphStyle("h2", fontName="DV-B", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=3)
P = ParagraphStyle("p", fontName="DV", fontSize=8, leading=11, textColor=GREY, spaceAfter=3)
CELL = ParagraphStyle("c", fontName="DV", fontSize=7, leading=8.5)


def _doc(title: str, story: list) -> bytes:
    buf = io.BytesIO()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("DV", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(12 * mm, 7 * mm, f"{title} · wygenerowano {stamp} · football-predictor {__version__} · prognozy modelu, nie gwarancja")
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"str. {doc.page}")
        canvas.restoreState()

    d = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                          title=title, author="football-predictor")
    d.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _p(text: str, style=P) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _table(head: list[str], rows: list[list], styles: list, widths=None) -> Table:
    t = Table([head] + rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "DV", 7), ("FONT", (0, 0), (-1, 0), "DV-B", 7),
                           ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dbe1")),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)] + styles))
    return t


def _mark(styles: list, col: int, row: int, ok: bool) -> None:
    styles += [("BACKGROUND", (col, row), (col, row), GREEN_BG if ok else RED_BG),
               ("TEXTCOLOR", (col, row), (col, row), GREEN_FG if ok else RED_FG)]


def _pct(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{100 * x:.0f}%"


def _mark_txt(p, y) -> str:
    return _pct(p) if y is None or pd.isna(y) else f"{_pct(p)} {'✓' if int(y) else '✗'}"


def _match_table(res: pd.DataFrame, mk: list) -> Table:
    P3 = res[["p1", "px", "p2"]].to_numpy()
    pick = P3.argmax(axis=1)
    y = res["y"].to_numpy(int)
    head = ["data", "mecz", "wynik", "1X2 (model)"] + [m[0] for m in mk]
    rows, st = [], []
    for i, r in enumerate(res.itertuples(index=False), start=1):
        ok = pick[i - 1] == y[i - 1]
        row = [pd.to_datetime(r.date).strftime("%d.%m"), Paragraph(escape(f"{r.home} – {r.away}"), CELL), f"{int(r.hg)}–{int(r.ag)}",
               f"{'1X2'[pick[i - 1]]} {_pct(P3[i - 1].max())} {'✓' if ok else '✗'}"]
        _mark(st, 3, i, ok)
        for j, (_, yc, pc, _b) in enumerate(mk):
            pv, yv = getattr(r, pc, None), getattr(r, yc, None)
            row.append(_mark_txt(pv, yv))
            if pv is not None and not pd.isna(pv) and yv is not None and not pd.isna(yv):
                _mark(st, 4 + j, i, bool(int(yv)))
        rows.append(row)
    widths = [26, 140, 28, 52] + [50] * len(mk)
    return _table(head, rows, st, widths)


def recent_pdf(sections: list[tuple[str, str, pd.DataFrame]], days: int, skipped: list[str] | None = None) -> bytes:
    """sections: (nazwa ligi, podsumowanie tekstem, wyniki recent_predictions)."""
    story = [_p("Ostatnie mecze - retrospektywa modelu", H1),
             _p(f"Okno: ostatnie {days} dni. Model uczony wyłącznie na meczach sprzed danej kolejki (bez zaglądania w przyszłość). "
                "To nie jest dziennik na żywo. Zielone pole = zdarzenie zaszło ✓ (w 1X2: typ modelu trafiony), czerwone = nie zaszło ✗."),
             _p(f"Ligi w pliku: {len(sections)}" + (f". Pominięte (brak danych lub limit czasu): {', '.join(skipped)}." if skipped else "."))]
    for name, summary, res in sections:
        story.append(_p(name, H2))
        story.append(_p(summary))
        hit = float((res[["p1", "px", "p2"]].to_numpy().argmax(axis=1) == res["y"].to_numpy(int)).mean())
        story.append(_p(f"Trafione typy 1X2: {100 * hit:.0f}% ({len(res)} meczów)."))
        story.append(_match_table(res.sort_values("date", ascending=False), _markets(res)))
    if not sections:
        story.append(_p("Brak meczów do pokazania."))
    return _doc("Ostatnie mecze", story)


def journal_pdf(sections: list[tuple[str, dict, pd.DataFrame, pd.DataFrame]]) -> bytes:
    """sections: (liga, {w_bazie, rozliczone, oczekujace}, tabela podsumowania, rozliczone prognozy)."""
    story = [_p("Dziennik prognoz (na żywo)", H1),
             _p("Prognozy zapisane PRZED meczem i rozliczone po wyniku. Log-loss: im mniej, tym lepiej (model vs średnia ligi). "
                "Zielone pole = trafione, czerwone = pudło.")]
    for name, st, summ, s in sections:
        story.append(_p(f"{name} - w bazie {st['w_bazie']}, rozliczone {st['rozliczone']}, oczekujące {st['oczekujace']}", H2))
        if not summ.empty:
            cols = [c for c in summ.columns if c in ("rynek", "n", "model", "baseline", "rynek_ll", "model_na_tych_samych", "mix", "brier")]
            story.append(_table(cols, [[str(v) if not (isinstance(v, float) and np.isnan(v)) else "–" for v in row]
                                       for row in summ[cols].to_numpy()], [], None))
            story.append(Spacer(1, 4))
        if s.empty:
            story.append(_p("Brak rozliczonych prognoz."))
            continue
        s = s.sort_values("date", ascending=False).reset_index(drop=True)
        pick = s[["p1", "px", "p2"]].to_numpy().argmax(axis=1)
        rows, stl = [], []
        for i, r in enumerate(s.itertuples(index=False), start=1):
            k = pick[i - 1]
            ok = k == int(r.y)
            rows.append([str(r.date)[5:], Paragraph(escape(f"{r.home} – {r.away}"), CELL), f"{int(r.hg)}–{int(r.ag)}",
                         f"{_pct(r.p1)}/{_pct(r.px)}/{_pct(r.p2)}", f"{'1X2'[k]} {'✓' if ok else '✗'}",
                         _mark_txt(r.p_over25, int(r.hg + r.ag > 2.5)), _mark_txt(r.p_btts, int(r.hg > 0 and r.ag > 0))])
            _mark(stl, 4, i, ok)
            _mark(stl, 5, i, bool(r.hg + r.ag > 2.5))
            _mark(stl, 6, i, bool(r.hg > 0 and r.ag > 0))
        story.append(_table(["data", "mecz", "wynik", "1/X/2 (model)", "typ", "Over 2.5", "BTTS"], rows, stl, [30, 170, 32, 78, 40, 52, 52]))
    if not sections:
        story.append(_p("Dziennik jest pusty."))
    return _doc("Dziennik prognoz", story)


def coupon_pdf(data: dict, stake: float | None = None) -> bytes:
    """data: wynik compute_coupon (legs, laczne, ostrzezenia)."""
    legs = [l for l in data["legs"] if not l.get("blad")]
    story = [_p("Zestawienie typów", H1)]
    rows = [[l["data"], Paragraph(escape(l["mecz"]), CELL), Paragraph(escape(l["rynek"]), CELL), _pct(l["p"]), f"{l['kurs_fair']:.2f}",
             f"{l['kurs_uzyty']:.2f}" if l.get("kurs_uzyty") else "–"] for l in legs]
    story.append(_table(["data", "mecz", "rynek", "szansa (model)", "uczciwy kurs", "kurs"], rows, [], [48, 200, 170, 60, 60, 50]))
    n = len(legs)
    if n:
        pall = float(np.prod([l["p"] for l in legs]))
        same = len({l["data"] + l["mecz"] for l in legs}) < n
        odds = [l["kurs_uzyty"] for l in legs if l.get("kurs_uzyty")]
        info = [f"Liczba typów: {n}."]
        if not same:
            info.append(f"Szansa wszystkich typów wg modelu: {100 * pall:.1f}%, uczciwy kurs AKO: {1 / pall:.2f}.")
        else:
            info.append("Są typy z tego samego meczu - nie są niezależne, szansy łącznej nie liczę.")
        if len(odds) == n:
            tot = float(np.prod(odds))
            info.append(f"Kurs AKO (iloczyn kursów): {tot:.2f}.")
            if not same:
                info.append(f"Wartość oczekiwana wg modelu: {100 * (pall * tot - 1):+.0f}% stawki (optymistyczna - zakłada, że model ma rację).")
            if stake:
                info.append(f"Stawka {stake:.0f} zł → wygrana {stake * tot:.2f} zł (zysk {stake * tot - stake:.2f} zł).")
        else:
            info.append("Nie wszystkie typy mają kurs - AKO nie jest policzone.")
        story += [Spacer(1, 6), _p(" ".join(info))]
    for w in data.get("ostrzezenia") or []:
        story.append(_p("⚠ " + w))
    for l in legs:
        for w in l.get("ostrzezenia") or []:
            story.append(_p(f"⚠ {l['mecz']}: {w}"))
    if not legs:
        story.append(_p("Zestawienie jest puste."))
    return _doc("Zestawienie", story)
