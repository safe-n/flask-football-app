# Notatki wspólne (piłka + tenis + infrastruktura)

Repo rozwijają **dwie osobne rozmowy z Claude**, które nie widzą się nawzajem. Ten plik jest ich wspólną pamięcią.
**Przeczytaj go na początku pracy, a po ważnej zmianie dopisz krótką notkę** w sekcji „Dziennik zmian”.

## Kto co prowadzi

| obszar | pliki | rozmowa |
|---|---|---|
| piłka | `fbpred/`, `templates/`, `history/`, `params/`, `ledger/`, `README.md`, `CHANGELOG.md` | **wątek piłki** |
| tenis | `tnpred/`, `tennis_history/`, `tennis_params/`, `README-tenis.md`, `CHANGELOG-tenis.md`, `tests/test_tn010.py` | **wątek „Tenis + infrastruktura”** |
| wspólne | `combo.py`, `requirements.txt`, `render.yaml`, `Dockerfile`, `lokalnie/`, `aktualizuj_tenis*.bat`, ten plik | **wątek „Tenis + infrastruktura”** |

Zmiany w obszarze drugiej rozmowy: tylko gdy właściciel poprosi, a jeśli to konieczne (np. nowa biblioteka w
`requirements.txt`), opisz ją w dzienniku poniżej.

## Zasady
- Użytkownik pisze po polsku, Windows + VS Code + PowerShell + GitHub Desktop (git w wierszu poleceń **nie** jest zainstalowany).
  Wszystko darmowe/hobbystyczne, instrukcje krok po kroku.
- Przed wysłaniem zmian zawsze pobierz najnowszy `master` (druga rozmowa mogła coś wypchnąć). Każdy push = nowe wdrożenie na Renderze.
- Klucze tylko w `.env` w folderze repo (jest w `.gitignore`); nigdy nie wypisuj ich w czacie ani w plikach.
- Ustawień Rendera nie zmieniaj bez pytania. Start Command: `gunicorn combo:app --workers 1 --threads 4 --timeout 120`.

## Jak to działa
- **Render** (darmowy plan, usługa `flask-football-app`): piłka pod `/`, tenis pod `/tennis/` (`combo.py`).
  UptimeRobot pinguje `/healthz`. Render zostaje jako zapas, gdy PC jest wyłączony.
- **Kopia lokalna na PC** (`C:\GitHub\flask-football-app`, nazwa komputera `desktop-8r4t2nq`):
  `lokalnie\uruchom_aplikacje.bat` → waitress na porcie 5000, autostart `lokalnie\autostart_wlacz.bat`.
  Telefon przez Tailscale: `http://desktop-8r4t2nq:5000/` (lub adres 100.x). Zapora: reguła na port 5000 tylko z 100.64.0.0/10.
- **Kopia lokalna ma osobne dane**, żeby nie nadpisywać Rendera (ustawiane w `uruchom_aplikacje.bat` – nie zmieniaj nazw tych zmiennych):
  `DB_PATH=data\football_local.db`, `TN_DB_PATH=data\tennis_local.db`, `LEDGER_BRANCH` / `TN_LEDGER_BRANCH=ledger-data-local`.
  Skutek: zakłady i dziennik zapisane lokalnie nie są widoczne na Renderze (i odwrotnie).
- **Gałąź `ledger-data`** (Render) i `ledger-data-local` (PC): dzienniki prognoz/zakładów w CSV przez GitHub API, bez redeployu.
- **Tenis – wyniki**: tennis-data.co.uk blokuje serwery (HTTP 403), wpuszcza PC. `python -m tnpred push-history`
  (Harmonogram co 4 h: `python -m tnpred install-task`) wysyła bieżący rok + parametry + styl zawodników do `ledger-data/tennis/history/`;
  Render sprawdza co 3 h. Strona aktualizuje pliki raz w tygodniu, po turniejach → dane bywają kilka dni w plecy.
- **Tenis – kursy**: The Odds API (`ODDS_API_KEY`, 500 kredytów/mies., budżet w aplikacji 450).

## Dziennik zmian (najnowsze na górze)
- **2026-11-05 · piłka 0.9.3** (wątek piłki): Liga Europy `EL` z TheSportsDB (`fbpred/sportsdb.py`, `extsource.py`), wersja próbna - aktywuje się dopiero po pojawieniu się `history/EL_*.csv` (komenda `history-init --league EL` na PC). Nowa opcjonalna zmienna `SPORTSDB_KEY`.
- **2026-11-05 · piłka 0.9.2** (wątek piłki): godzina startu i status meczu w Mecze/Zestawieniu/PDF (`fbpred/kickoff.py`, kolumna `kickoff` tylko w SQLite, zmienne `FB_TZ`, `FB_MATCH_HOURS`), link „Eksport PDF” na górze Zestawienia. Liga Europy: brak w darmowym football-data.org - czeka na decyzję o źródle.
- **2026-11-05 · tenis 0.3.10** (wątek tenisa): styl zawodnika w tie-breakach ATP (`tnpred/style.py`, `tennis_params/style.json`),
  kolory w „Ostatnich” względem średniej touru/nawierzchni, `PYTHONUTF8=1` w `aktualizuj_tenis_auto.bat`.
- **2026-11-05 · infrastruktura**: kopia lokalna na PC + Tailscale działa (`lokalnie/`). Piłka w tym czasie: 0.9.1 (bez zmian).
- Pomysł z wątku tenisa dla piłki: **Liga Europy** – brak w darmowym football-data.org i w CSV; wymagałaby siły drużyn między ligami.
  Decyzja należy do wątku piłki.
