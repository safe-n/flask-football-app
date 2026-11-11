# Notatki wspólne (piłka + tenis + infrastruktura)

Repo rozwijają **dwie osobne rozmowy z Claude**, które nie widzą się nawzajem. Ten plik jest ich wspólną pamięcią.
**Przeczytaj go na początku pracy, a po ważnej zmianie dopisz krótką notkę** w sekcji „Dziennik zmian”.

## Kto co prowadzi

| obszar | pliki | rozmowa |
|---|---|---|
| piłka | `fbpred/`, `templates/`, `history/`, `params/`, `ledger/`, `docs/`, `README.md`, `CHANGELOG.md` | **wątek piłki** |
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
  `lokalnie\uruchom_aplikacje.bat` → `lokalnie\serwer.py` (git pull + pip + waitress na porcie 5000, pętla restartu),
  autostart `lokalnie\autostart_wlacz.bat`. **Nowy kod na PC: strona `/restart` → „Aktualizuj i zrestartuj”**
  (działa tylko lokalnie, `LOCAL_RESTART=1`). Nie wgrywaj plików bezpośrednio na PC – tylko przez GitHub, wtedy pull jest czysty.
  Telefon przez Tailscale: `http://desktop-8r4t2nq:5000/` (lub adres 100.x). Zapora: reguła na port 5000 tylko z 100.64.0.0/10.
- **Kopia lokalna ma osobne dane**, żeby nie nadpisywać Rendera (ustawiane w `uruchom_aplikacje.bat` – nie zmieniaj nazw tych zmiennych):
  `DB_PATH=data\football_local.db`, `TN_DB_PATH=data\tennis_local.db`, `LEDGER_BRANCH` / `TN_LEDGER_BRANCH=ledger-data-local`.
  Skutek: zakłady i dziennik zapisane lokalnie nie są widoczne na Renderze (i odwrotnie).
- **Gałąź `ledger-data`** (Render) i `ledger-data-local` (PC): dzienniki prognoz/zakładów w CSV przez GitHub API, bez redeployu.
- **Tenis – wyniki**: tennis-data.co.uk blokuje serwery (HTTP 403), wpuszcza PC. `python -m tnpred push-history`
  (Harmonogram co 4 h: `python -m tnpred install-task`) wysyła bieżący rok + parametry + styl zawodników do `ledger-data/tennis/history/`;
  Render sprawdza co 3 h. Strona aktualizuje pliki raz w tygodniu, po turniejach → dane bywają kilka dni w plecy.
- **Tenis – kursy**: The Odds API (`ODDS_API_KEY`, 500 kredytów/mies., budżet w aplikacji 450) - tylko duże turnieje.
- **Tenis – łatka ESPN**: wyniki z ostatnich dni + terminarz bez kursów (feed nieoficjalny, może zniknąć; `TN_ESPN=0` wyłącza).

## Dziennik zmian (najnowsze na górze)
- **2026-11-11 · tenis 0.3.14** (wątek tenisa): poprawka utraty danych na Renderze - tnpred zapisywał do GitHuba PRZED odczytem
  po restarcie (pusta baza nadpisywała typy, kupony, zakłady i dziennik). Dane odtworzone z historii `ledger-data`.
  **Dla piłki:** fbpred czyta przed zapisem (bootstrap.py ~334 vs ~361), więc problemu nie ma - ale przy każdej nowej synchronizacji
  zasada: najpierw sync_down, zapis dopiero po udanym odczycie.
- **2026-11-11 · piłka 0.10.0** (wątek piłki, start Rozdziału 2): „Moje typy” w piłce wg `docs/WZORZEC-MOJE-TYPY.md` - klikalne kafelki
  na stronie Mecze, szkic → kupon na stałe, zestawienie skuteczności z wydrukiem (`fbpred/picks.py`, `templates/picks.html`, `/picks`, `/api/picks`).
  Pliki piłki w gałęzi dziennika: `ledger/picks.csv`, `ledger/pick_coupons.csv` (tenis ma swoje w `tennis/` - nie kolidują). Plików tenisa nie ruszano.
  Przy okazji naprawione auto-rozliczanie „Moich zakładów” w piłce (zła kolejność argumentów lookupu).
- **2026-11-10 · tenis 0.3.13** (wątek tenisa): kupony w „Moich typach” (szkic → zatwierdzony na stałe, AKO gdy są kursy).
  **Dla wątku piłki:** użytkownik chce tej samej funkcji w piłce (aktywne kafelki → Moje typy → kupony, zestawienie z wydrukiem).
  Pełny opis i lista kontrolna: `docs/WZORZEC-MOJE-TYPY.md` (kod wzorcowy w `tnpred/picks.py`, `templates/picks.html`).
- **2026-11-10 · tenis 0.3.12** (wątek tenisa): „Moje typy” - klikalne kafelki, rozliczanie wszedł/nie wszedł, zestawienie
  skuteczności z wydrukiem (`tnpred/picks.py`, plik `picks.csv` w gałęzi dziennika).
- **2026-11-10 · infrastruktura**: lokalny commit na PC („update history”: `history/EL_2025.csv`, styl TB) blokował `git pull --ff-only`
  w `lokalnie/serwer.py` od 7.11 - przeniesiony na master (aba870b). Gdy wersja na PC nie rośnie po restarcie: GitHub Desktop, „↑” przy Pull.
- **2026-11-10 · tenis 0.3.11** (wątek tenisa): `tnpred/espn.py` - łatka świeżych wyników i terminarz z feedu ESPN
  (bez klucza) dla turniejów, których nie ma w The Odds API (ATP 250, Finals). Nowe opcjonalne zmienne `TN_ESPN`, `TN_ESPN_DAYS`.
- **2026-11-10 · piłka 0.9.5 + dokumentacja** (wątek piłki): zamknięty Rozdział 1 - katalog `docs/` (koncepcja, architektura, instrukcja, operacje, podsumowanie i plan Rozdziału 2). Od 0.9.3 doszły: 0.9.4 (EL kolejka po kolejce) i 0.9.5 (odporność na limit TheSportsDB). Liga Europy nadal nieaktywna na Renderze - brak `history/EL_*.csv` (do dokończenia `history-init --league EL --seasons 2026-2026` na PC).
- **2026-11-05 · infrastruktura**: przycisk `/restart` (w `combo.py`) + `lokalnie/serwer.py`: kopia na PC sama pobiera
  kod z GitHuba przy starcie i po kliknięciu restartu; harmonogram „Tenis - aktualizacja wynikow” co 4 h ustawiony na PC.
- **2026-11-05 · piłka 0.9.3** (wątek piłki): Liga Europy `EL` z TheSportsDB (`fbpred/sportsdb.py`, `extsource.py`), wersja próbna - aktywuje się dopiero po pojawieniu się `history/EL_*.csv` (komenda `history-init --league EL` na PC). Nowa opcjonalna zmienna `SPORTSDB_KEY`.
- **2026-11-05 · piłka 0.9.2** (wątek piłki): godzina startu i status meczu w Mecze/Zestawieniu/PDF (`fbpred/kickoff.py`, kolumna `kickoff` tylko w SQLite, zmienne `FB_TZ`, `FB_MATCH_HOURS`), link „Eksport PDF” na górze Zestawienia. Liga Europy: brak w darmowym football-data.org - czeka na decyzję o źródle.
- **2026-11-05 · tenis 0.3.10** (wątek tenisa): styl zawodnika w tie-breakach ATP (`tnpred/style.py`, `tennis_params/style.json`),
  kolory w „Ostatnich” względem średniej touru/nawierzchni, `PYTHONUTF8=1` w `aktualizuj_tenis_auto.bat`.
- **2026-11-05 · infrastruktura**: kopia lokalna na PC + Tailscale działa (`lokalnie/`). Piłka w tym czasie: 0.9.1 (bez zmian).
- Pomysł z wątku tenisa dla piłki: **Liga Europy** – brak w darmowym football-data.org i w CSV; wymagałaby siły drużyn między ligami.
  Decyzja należy do wątku piłki.
