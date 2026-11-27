"""Hook PreToolUse: blokuje edycję plików prowadzonych przez drugą rozmowę.

Kod wyjścia 2 = Claude Code zatrzymuje edycję i pokazuje Claude'owi komunikat z stderr.
To bezpiecznik przed pomyłką, a nie zabezpieczenie – zasady są w NOTATKI-WSPOLNE.md.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obszary import NAZWY, PLIK_WATKU, biezacy_watek, katalog_projektu, wlasciciel  # noqa: E402


def main():
    try:
        dane = json.load(sys.stdin)
    except ValueError:
        return 0
    wejscie = dane.get("tool_input") or {}
    sciezka = wejscie.get("file_path") or wejscie.get("notebook_path")
    if not sciezka:
        return 0

    projekt = os.path.abspath(katalog_projektu())
    pelna = os.path.abspath(os.path.join(projekt, sciezka))
    if os.path.commonpath([projekt, pelna]) != projekt:
        return 0  # plik poza repo – nie nasza sprawa
    wzgledna = os.path.relpath(pelna, projekt)

    wlasc = wlasciciel(wzgledna)
    if wlasc is None:
        return 0

    watek = biezacy_watek()
    if watek is None:
        print(
            f"Strażnik obszarów: plik {wzgledna} prowadzi {NAZWY[wlasc]}, a ta sesja nie zapisała jeszcze, "
            f"którym wątkiem jest. Ustal to (z rozmowy lub skilla startowego) i zapisz jedno słowo "
            f"– pilka albo tenis – do pliku {PLIK_WATKU}, potem powtórz edycję.",
            file=sys.stderr,
        )
        return 2
    if watek == "oba" or watek == wlasc:
        return 0

    print(
        f"Strażnik obszarów: plik {wzgledna} prowadzi {NAZWY[wlasc]}, a ta sesja to {NAZWY[watek]}. "
        f"Zgodnie z NOTATKI-WSPOLNE.md zmieniaj go tylko na wyraźną prośbę właściciela. Jeśli właściciel "
        f"o to poprosił w tej rozmowie, zapisz słowo oba do {PLIK_WATKU} i opisz zmianę w dzienniku "
        f"NOTATKI-WSPOLNE.md. W przeciwnym razie zostaw plik i opisz potrzebną zmianę w dzienniku dla drugiego wątku.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
