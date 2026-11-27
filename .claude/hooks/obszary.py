"""Wspólne dane strażnika: kto prowadzi które pliki (z NOTATKI-WSPOLNE.md, sekcja „Kto co prowadzi”).

Jeśli zmieni się podział obszarów, popraw go tutaj i w NOTATKI-WSPOLNE.md jednocześnie.
"""
import os

# Wątki: "pilka" = wątek piłki, "tenis" = wątek „Tenis + infrastruktura” (prowadzi też pliki wspólne).
OBSZARY = {
    "pilka": [
        "fbpred/", "templates/", "history/", "params/", "ledger/", "docs/",
        "README.md", "CHANGELOG.md",
    ],
    "tenis": [
        "tnpred/", "tennis_history/", "tennis_params/",
        "README-tenis.md", "CHANGELOG-tenis.md", "tests/test_tn010.py",
        # pliki wspólne – też wątek „Tenis + infrastruktura”
        "combo.py", "requirements.txt", "render.yaml", "Dockerfile", "lokalnie/",
        "aktualizuj_tenis",  # aktualizuj_tenis*.bat
    ],
}

# Każdy wątek może dopisywać do dziennika zmian.
WOLNE = ["NOTATKI-WSPOLNE.md"]

NAZWY = {"pilka": "wątek piłki", "tenis": "wątek „Tenis + infrastruktura”"}
PLIK_WATKU = os.path.join(".claude", "watek.local")
DOZWOLONE_WARTOSCI = ("pilka", "tenis", "oba")


def katalog_projektu():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def wlasciciel(sciezka_wzgledna):
    """Zwraca 'pilka', 'tenis' albo None (plik niczyj lub wolny)."""
    p = sciezka_wzgledna.replace("\\", "/").lstrip("./")
    if p in WOLNE:
        return None
    for watek, wzorce in OBSZARY.items():
        for w in wzorce:
            if w.endswith("/"):
                if p.startswith(w):
                    return watek
            elif p == w or (w == "aktualizuj_tenis" and p.startswith(w)):
                return watek
    return None


def biezacy_watek():
    try:
        with open(os.path.join(katalog_projektu(), PLIK_WATKU), encoding="utf-8") as f:
            w = f.read().strip().lower()
        return w if w in DOZWOLONE_WARTOSCI else None
    except OSError:
        return None
