"""Raporty tekstowe/markdown (do GitHuba, CI i powiadomień) - bez dodatkowych zależności."""
from __future__ import annotations

import pandas as pd

from . import db, ledger


def to_markdown(df: pd.DataFrame, floatfmt: str = "{:.4f}") -> str:
    if df.empty:
        return "_brak danych_"

    def fmt(v):
        if isinstance(v, float):
            return "–" if pd.isna(v) else floatfmt.format(v)
        return "–" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v)

    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


def ledger_report(conn, league: str, min_edge: float = 0.03) -> str:
    s = ledger.settled(conn, league)
    head = f"## {league}\n\nRozliczone prognozy: **{len(s)}**, oczekujące: **{ledger.pending(conn, league)}**\n"
    if s.empty:
        return head + "\n_Jeszcze nic do rozliczenia._\n"
    hist = db.load_matches(conn, league)
    hist = hist[~hist["fixture_id"].isin(s["fixture_id"])]
    tab, sim = ledger.track_summary(s, min_edge, base=ledger.league_base_rates(hist))
    return (head + "\nLog-loss na żywo (mniej = lepiej):\n\n" + to_markdown(tab) +
            f"\n\nSymulacja typów (edge ≥ {min_edge:.0%}): zakłady {sim['zaklady']}, ROI {sim['ROI_%']}% "
            f"_(mała próba = głównie szum)_\n")
