"""Powiadomienia Telegram (darmowe): zestawienie prognoz i typów z przewagą. Token tylko ze zmiennych środowiskowych."""
from __future__ import annotations

import pandas as pd
import requests

from . import config

LIMIT = 3800  # limit Telegrama to 4096 znaków na wiadomość


def _pct(x: float) -> str:
    return f"{100 * x:.0f}"


def format_match(pred: dict, row: dict, picks: list[dict]) -> str:
    x = pred.get("1x2_blend") or pred["1x2"]
    d = pd.Timestamp(row["date"]).strftime("%d.%m")
    lines = [f"{pred['home']} – {pred['away']} ({d})",
             f" 1X2: {_pct(x['1'])}/{_pct(x['X'])}/{_pct(x['2'])}%"
             + (f"  (rynek {_pct(pred['market_1x2']['1'])}/{_pct(pred['market_1x2']['X'])}/{_pct(pred['market_1x2']['2'])})"
                if "market_1x2" in pred else ""),
             f" O2.5 {_pct(pred['goals']['over_2.5'])}% · BTTS {_pct(pred['goals']['btts_yes'])}%"
             + (f" · remis HT {_pct(pred['halves']['draw_ht'])}% · HT lub FT {_pct(pred['halves']['draw_ht_or_ft'])}%"
                if "halves" in pred else "")]
    if "yellow" in pred:
        lines.append(f" żółte śr. {pred['yellow']['total_mean']} · rożne śr. {pred.get('corners', {}).get('total_mean', '–')}")
    for k in picks[:2]:
        flag = " ⚠ podejrzanie duża" if k["edge"] > 0.15 else ""
        lines.append(f" ⚑ {k['rynek']} @{k['kurs']} przewaga {100 * k['edge']:+.0f}%{flag}")
    return "\n".join(lines)


def chunk(text: str, limit: int = LIMIT) -> list[str]:
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        parts.append(cur)
    return parts


def send_telegram(text: str, token: str | None = None, chat_id: str | None = None, timeout: int = 20) -> int:
    token, chat_id = token or config.TELEGRAM_BOT_TOKEN, chat_id or config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        raise RuntimeError("Brak TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    n = 0
    for part in chunk(text):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": part, "disable_web_page_preview": True}, timeout=timeout)
        r.raise_for_status()
        n += 1
    return n
