"""Kontrola jakości danych - uruchom zanim zaczniesz ufać wynikom backtestu."""
from __future__ import annotations

import difflib
from itertools import combinations

import pandas as pd


def check(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Zwraca listę (poziom, komunikat). Poziomy: OK, UWAGA, BŁĄD."""
    out: list[tuple[str, str]] = []
    add = lambda lvl, msg: out.append((lvl, msg))  # noqa: E731
    n = len(df)
    add("OK", f"{n} meczów, {df['date'].min():%Y-%m-%d} → {df['date'].max():%Y-%m-%d}")

    dup = int(df.duplicated(["date", "home", "away"]).sum())
    add("BŁĄD" if dup else "OK", f"duplikaty (data+para): {dup}")

    big = int(((df.hg > 9) | (df.ag > 9)).sum())
    add("UWAGA" if big else "OK", f"wyniki z >9 golami jednej drużyny: {big}")

    if "hg_ht" in df:
        bad = int(((df.hg_ht > df.hg) | (df.ag_ht > df.ag)).sum())
        add("BŁĄD" if bad else "OK", f"wynik do przerwy większy niż końcowy: {bad}")

    for col, label in (("hg_ht", "wynik do przerwy"), ("h_yellow", "żółte kartki"), ("h_corners", "rożne"),
                       ("referee", "sędzia"), ("o_home", "kursy 1X2"), ("o_over25", "kursy O/U 2.5")):
        if col in df:
            pct = 100 * df[col].notna().mean()
            add("OK" if pct >= 90 else ("UWAGA" if pct >= 30 else "BŁĄD"), f"pokrycie: {label} {pct:.0f}%")
        else:
            add("UWAGA", f"brak kolumny: {label}")

    if {"o_home", "o_draw", "o_away"} <= set(df.columns):
        o = df.dropna(subset=["o_home", "o_draw", "o_away"])
        if len(o):
            ov = 1 / o.o_home + 1 / o.o_draw + 1 / o.o_away - 1
            weird = int(((ov < -0.01) | (ov > 0.25)).sum())
            add("UWAGA" if weird else "OK", f"kursy 1X2 z dziwną marżą (<-1% lub >25%): {weird}; mediana marży {100 * ov.median():.1f}%")

    cnt = pd.concat([df["home"], df["away"]]).value_counts()
    few = [t for t, c in cnt.items() if c < 10]
    if few:
        add("UWAGA", f"drużyny z <10 meczami (model użyje shrinkage): {', '.join(few[:8])}")

    names = sorted(cnt.index)
    sim = [(a, b) for a, b in combinations(names, 2)
           if difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.85]
    if sim:
        add("UWAGA", "podobne nazwy drużyn (może ta sama?): " + "; ".join(f"{a} ~ {b}" for a, b in sim[:6]))
    else:
        add("OK", "brak podejrzanie podobnych nazw drużyn")

    d = df.sort_values("date")
    gaps = d["date"].diff().dt.days
    long_gap = int((gaps > 75).sum())
    add("UWAGA" if long_gap else "OK", f"przerwy >75 dni w kalendarzu: {long_gap} (przerwa letnia jest normalna)")
    return out
