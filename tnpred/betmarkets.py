"""Katalog rynków tenisowych liczonych z prognozy + identyfikatory typów + rozliczanie.

Identyfikator typu: tour~data~zawodnik1~zawodnik2~nawierzchnia~sety~klucz (np. ATP~2026-11-02~Sinner J.~Alcaraz C.~Hard~3~o22.5).
Klucze: w1/w2 (zwycięzca), o22.5/u22.5 (gemy), h1-3.5 / h2+2.5 (handicap gemów), s2-0 / s1-2 (wynik w setach, z perspektywy 1),
tb/notb (tie-break w meczu), fs1/fs2 (1. set), ws1/ws2 (wygra co najmniej seta), f1o9.5/f1u9.5 (gemy w 1. secie).
Krecz / walkower: typ = zwrot (zasady bukmacherów się różnią - sprawdź u swojego).
"""
from __future__ import annotations

GROUPS = ["Zwycięzca", "Gemy", "Handicap", "Sety", "Tie-break", "1. set"]
SEP = "~"


def catalogue(pred: dict) -> dict[str, dict]:
    m = pred["m"]
    a, b = pred["p1"], pred["p2"]
    out: dict[str, dict] = {}

    def add(key, label, group, p):
        if p is not None:
            out[key] = {"label": label, "group": group, "p": float(min(max(p, 0.0), 1.0))}

    add("w1", f"{a} wygra", "Zwycięzca", m["p1"])
    add("w2", f"{b} wygra", "Zwycięzca", m["p2"])
    for line, p in m["over"].items():
        add(f"o{line}", f"Over {line} gemów", "Gemy", p)
        add(f"u{line}", f"Under {line} gemów", "Gemy", 1 - p)
    for h, p in m["hcp"].items():
        add(f"h1{h}", f"{a} {h} gemów", "Handicap", p)
        inv = ("+" if h.startswith("-") else "-") + h[1:]
        add(f"h2{inv}", f"{b} {inv} gemów", "Handicap", 1 - p)
    for sc, p in m["sets"].items():
        add(f"s{sc}", f"Wynik w setach {sc} ({a.split()[0]}–{b.split()[0]})", "Sety", p)
    add("ws1", f"{a} wygra co najmniej seta", "Sety", m["win_a_set"]["1"])
    add("ws2", f"{b} wygra co najmniej seta", "Sety", m["win_a_set"]["2"])
    add("tb", "Tie-break w meczu – tak", "Tie-break", m["p_tb"])
    add("notb", "Tie-break w meczu – nie", "Tie-break", 1 - m["p_tb"])
    add("fs1", f"{a} wygra 1. seta", "1. set", m["set1_p1"])
    add("fs2", f"{b} wygra 1. seta", "1. set", 1 - m["set1_p1"])
    add("f1o9.5", "1. set: over 9.5 gema", "1. set", m["set1_over9.5"])
    add("f1u9.5", "1. set: under 9.5 gema", "1. set", 1 - m["set1_over9.5"])
    return out


def book_odds(row: dict, key: str) -> float | None:
    """Kurs z bazy (tylko rynki, które daje źródło: zwycięzca; gemy/handicap jeśli API je zwróciło)."""
    def f(c):
        try:
            v = float(row.get(c))
        except (TypeError, ValueError):
            return None
        return v if v == v and v > 1.0 else None
    if key == "w1":
        return f("o1")
    if key == "w2":
        return f("o2")
    if key[:1] in "ou" and key[1:].replace(".", "", 1).isdigit() and row.get("total_line") not in (None, ""):
        try:
            if abs(float(key[1:]) - float(row["total_line"])) < 1e-9:
                return f("o_over") if key[0] == "o" else f("o_under")
        except (TypeError, ValueError):
            return None
    if key[:2] in ("h1", "h2") and row.get("hcp_line") not in (None, ""):
        try:
            h = float(key[2:])
            hl = float(row["hcp_line"])   # handicap zawodnika 1
        except (TypeError, ValueError):
            return None
        if key[:2] == "h1" and abs(h - hl) < 1e-9:
            return f("o_h1")
        if key[:2] == "h2" and abs(h + hl) < 1e-9:
            return f("o_h2")
    return None


def leg_id(tour, date, p1, p2, surface, best_of, key) -> str:
    return SEP.join([str(tour), str(date)[:10], str(p1), str(p2), str(surface), str(int(best_of)), key])


def parse_leg(leg: str) -> tuple:
    parts = leg.split(SEP)
    if len(parts) != 7:
        raise ValueError(f"nieprawidłowy identyfikator typu: {leg!r}")
    t, d, a, b, s, bo, k = parts
    return t, d, a, b, s, int(bo), k


def oriented(r: dict, p1: str) -> dict | None:
    """Wynik meczu z perspektywy zawodnika 1: lista setów [(g1, g2)], kto wygrał, czy krecz/walkower."""
    if r is None:
        return None
    p1_won = r["winner"] == p1
    sets = []
    for i in range(1, 6):
        a, b = r.get(f"w{i}"), r.get(f"l{i}")
        if a is None or b is None or a != a or b != b:
            break
        sets.append((int(a), int(b)) if p1_won else (int(b), int(a)))
    c = str(r.get("comment") or "Completed").lower()
    return {"p1_won": p1_won, "sets": sets, "completed": c.startswith("compl")}


def leg_won(key: str, res: dict | None) -> bool | None:
    """True/False = rozliczony; None = brak danych; 'void' = zwrot (krecz/walkower)."""
    if res is None:
        return None
    if not res["completed"]:
        return "void"  # type: ignore[return-value]
    sets = res["sets"]
    if not sets:
        return None
    g1, g2 = sum(a for a, _ in sets), sum(b for _, b in sets)
    s1, s2 = sum(a > b for a, b in sets), sum(b > a for a, b in sets)
    tb = any(a + b == 13 for a, b in sets)
    if key == "w1":
        return res["p1_won"]
    if key == "w2":
        return not res["p1_won"]
    if key[:1] in ("o", "u") and key[1:].replace(".", "", 1).isdigit():
        line = float(key[1:])
        return (g1 + g2 > line) if key[0] == "o" else (g1 + g2 < line)
    if key[:2] in ("h1", "h2"):
        h = float(key[2:])
        return (g1 - g2 + h > 0) if key[:2] == "h1" else (g2 - g1 + h > 0)
    if key.startswith("s") and "-" in key:
        x, y = key[1:].split("-")
        return (s1, s2) == (int(x), int(y))
    if key == "ws1":
        return s1 >= 1
    if key == "ws2":
        return s2 >= 1
    if key == "tb":
        return tb
    if key == "notb":
        return not tb
    if key in ("fs1", "fs2"):
        a, b = sets[0]
        return (a > b) if key == "fs1" else (b > a)
    if key.startswith("f1") and key[2] in "ou":
        a, b = sets[0]
        line = float(key[3:])
        return (a + b > line) if key[2] == "o" else (a + b < line)
    return None
