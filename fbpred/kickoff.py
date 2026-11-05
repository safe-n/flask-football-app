"""Godzina startu i status meczu (przed / wkrótce / trwa / zakończony?) - jak w module tenisowym."""
from __future__ import annotations

import pandas as pd

from . import config

DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]


def start(kickoff) -> pd.Timestamp | None:
    s = str(kickoff or "").strip()
    if len(s) < 16 or ":" not in s or s.lower() in ("nan", "none", "nat"):
        return None
    try:
        return pd.Timestamp(s[:16].replace("T", " "), tz="UTC")
    except (ValueError, TypeError):
        return None


def when(kickoff, day, now=None) -> dict:
    """{day, label, time, status, badge}. Bez godziny: tylko dzień (status wg daty). Czas wyświetlany w config.TZ."""
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    t = start(kickoff)
    if t is None:
        d = pd.Timestamp(str(day)[:10])
        today = now.tz_convert(config.TZ).normalize().tz_localize(None)
        st = "today" if d == today else ("past" if d < today else "future")
        return {"day": f"{d:%Y-%m-%d}", "label": f"{DNI[d.weekday()]} {d:%d.%m}, godz. nieznana", "time": "", "status": st,
                "badge": "dziś" if st == "today" else ("minął" if st == "past" else ""), "sort": d.tz_localize("UTC") + pd.Timedelta(hours=23)}
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
            "status": status, "badge": badge, "sort": t}
