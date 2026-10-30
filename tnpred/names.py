"""Nazwy zawodników. tennis-data.co.uk: „Sinner J.”, „De Minaur A.”, „Kwon S.W.”; The Odds API: „Jannik Sinner”, „Alex de Minaur”.

Klucz dopasowania = (nazwisko bez akcentów/myślników, pierwsza litera imienia).
"""
from __future__ import annotations

import re
import unicodedata


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[-.'’`]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def split_td(name: str) -> tuple[str, str]:
    """„Auger-Aliassime F.” -> („auger aliassime”, „f”). Bez inicjałów: całość to nazwisko."""
    toks = str(name or "").strip().split()
    k = len(toks)
    while k > 1 and toks[k - 1].endswith("."):
        k -= 1
    surname = norm(" ".join(toks[:k]))
    init = norm(toks[k])[:1] if k < len(toks) else ""
    return surname, init


class NameIndex:
    """Mapuje dowolny zapis na nazwę w formacie tennis-data (tej, której używa baza)."""

    def __init__(self, names):
        self.exact: dict[str, str] = {}
        self.by_key: dict[tuple[str, str], list[str]] = {}
        self.by_surname: dict[str, list[str]] = {}
        for n in sorted(set(x for x in names if x)):
            self.exact[norm(n)] = n
            sur, ini = split_td(n)
            self.by_key.setdefault((sur, ini), []).append(n)
            self.by_surname.setdefault(sur, []).append(n)

    def resolve(self, name: str | None) -> str | None:
        if not name:
            return None
        n = norm(name)
        if n in self.exact:
            return self.exact[n]
        sur, ini = split_td(name)
        if ini and len(self.by_key.get((sur, ini), [])) == 1:
            return self.by_key[(sur, ini)][0]
        toks = n.split()
        # pełne imię i nazwisko: „alex de minaur” -> próbuj nazwisk od najdłuższego
        for i in range(1, len(toks)):
            cand = self.by_key.get((" ".join(toks[i:]), toks[0][:1]), [])
            if len(cand) == 1:
                return cand[0]
        # zapis odwrotny „Sinner Jannik”
        for i in range(len(toks) - 1, 0, -1):
            cand = self.by_key.get((" ".join(toks[:i]), toks[i][:1]), [])
            if len(cand) == 1:
                return cand[0]
        return None


def to_td(full: str) -> str:
    """Nieznany zawodnik z pełnym imieniem -> „Nazwisko I.” (żeby nowy gracz miał spójny zapis)."""
    toks = str(full or "").strip().split()
    if len(toks) < 2:
        return str(full or "").strip()
    return f"{' '.join(toks[1:])} {toks[0][0].upper()}."
