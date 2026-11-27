"""Hook SessionStart: przypomina zasady wspólnego repo i pokazuje najnowsze wpisy z dziennika.

Wszystko, co ten skrypt wypisze, Claude dostaje na początku sesji jako kontekst.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obszary import NAZWY, PLIK_WATKU, biezacy_watek, katalog_projektu  # noqa: E402

ILE_WPISOW = 5


def najnowsze_wpisy(tekst, ile):
    _, _, dziennik = tekst.partition("## Dziennik zmian")
    wpisy, biezacy = [], []
    for linia in dziennik.splitlines()[1:]:
        if linia.startswith("- "):
            if biezacy:
                wpisy.append("\n".join(biezacy))
            biezacy = [linia]
        elif biezacy and linia.startswith("  "):
            biezacy.append(linia)
    if biezacy:
        wpisy.append("\n".join(biezacy))
    return wpisy[:ile]


def main():
    watek = biezacy_watek()
    print("REPO WSPÓLNE DWÓCH ROZMÓW (piłka i tenis) – zasady z NOTATKI-WSPOLNE.md:")
    print("1. Przeczytaj NOTATKI-WSPOLNE.md, zanim zaczniesz zmiany.")
    print("2. Przed pushem pobierz najnowszy master – druga rozmowa mogła coś wypchnąć. Każdy push = wdrożenie na Renderze.")
    print("3. Po ważnej zmianie dopisz notkę na górze sekcji „Dziennik zmian”.")
    if watek:
        opis = "oba wątki (zgoda właściciela)" if watek == "oba" else NAZWY[watek]
        print(f"4. Ta sesja jest zapisana jako: {opis} ({PLIK_WATKU}).")
    else:
        print(f"4. Strażnik obszarów blokuje edycję plików wątków, dopóki nie zapiszesz w {PLIK_WATKU} "
              "słowa pilka albo tenis (ustal z rozmowy lub ze skilla startowego).")

    try:
        with open(os.path.join(katalog_projektu(), "NOTATKI-WSPOLNE.md"), encoding="utf-8") as f:
            wpisy = najnowsze_wpisy(f.read(), ILE_WPISOW)
    except OSError:
        wpisy = []
    if wpisy:
        print(f"\nNajnowsze wpisy z dziennika ({len(wpisy)}):")
        print("\n".join(wpisy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
