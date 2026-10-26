"""Katalog rynków (typów) liczonych z prognozy meczu + identyfikatory nóg kuponu."""
from __future__ import annotations

GROUPS = ["1X2", "Podwójna szansa", "Gole", "Remisy", "Kartki", "Rożne"]
SEP = "~"


def catalogue(pred: dict) -> dict[str, dict]:
    """key -> {label, group, p}. 1X2 bierze wersję zmieszaną z rynkiem, jeśli jest dostępna."""
    out: dict[str, dict] = {}

    def add(key, label, group, p):
        if p is not None:
            out[key] = {"label": label, "group": group, "p": float(p)}

    x = pred.get("1x2_blend") or pred["1x2"]
    add("1", "1 – gospodarz wygra", "1X2", x["1"])
    add("X", "X – remis", "1X2", x["X"])
    add("2", "2 – gość wygra", "1X2", x["2"])
    add("1X", "1X – gospodarz nie przegra", "Podwójna szansa", x["1"] + x["X"])
    add("X2", "X2 – gość nie przegra", "Podwójna szansa", x["X"] + x["2"])
    add("12", "12 – bez remisu", "Podwójna szansa", x["1"] + x["2"])
    g = pred["goals"]
    for line in ("1.5", "2.5", "3.5"):
        add(f"o{line}", f"Over {line} goli", "Gole", g.get(f"over_{line}"))
        add(f"u{line}", f"Under {line} goli", "Gole", g.get(f"under_{line}"))
    add("btts", "Obie strzelą (BTTS tak)", "Gole", g.get("btts_yes"))
    add("nobtts", "BTTS nie", "Gole", g.get("btts_no"))
    h = pred.get("halves")
    if h:
        add("d_ht", "Remis do przerwy", "Remisy", h["draw_ht"])
        add("d_2h", "Remis w 2. połowie", "Remisy", h["draw_2h"])
        add("d_either", "Remis w 1. LUB 2. połowie", "Remisy", h["draw_either_half"])
        add("d_htft", "Remis do przerwy LUB na koniec", "Remisy", h["draw_ht_or_ft"])
        add("d_ft", "Remis na koniec meczu", "Remisy", h["draw_ft"])
    for k, label in (("yellow", "Żółte kartki"),):
        if k in pred:
            for line, p in pred[k]["over"].items():
                add(f"y{line}", f"{label} over {line}", "Kartki", p)
    if "corners" in pred:
        for line, p in pred["corners"]["over"].items():
            add(f"c{line}", f"Rożne over {line}", "Rożne", p)
    return out


_ODDS_COL = {"1": "o_home", "X": "o_draw", "2": "o_away", "o2.5": "o_over25", "u2.5": "o_under25",
             "btts": "o_btts_yes", "nobtts": "o_btts_no"}


def book_odds(row: dict, key: str) -> float | None:
    """Kurs bukmachera z bazy (tylko dla rynków, które źródło danych udostępnia)."""
    col = _ODDS_COL.get(key)
    v = row.get(col) if col else None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v == v and v > 1.0 else None


def leg_id(league: str, date: str, home: str, away: str, key: str) -> str:
    return SEP.join([league, str(date)[:10], home, away, key])


def parse_leg(leg: str) -> tuple[str, str, str, str, str]:
    parts = leg.split(SEP)
    if len(parts) != 5:
        raise ValueError(f"nieprawidłowy identyfikator typu: {leg!r}")
    return tuple(parts)  # type: ignore[return-value]
