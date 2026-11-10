# Operacje i wdrożenie – football-predictor

Praktyczny podręcznik: zmienne środowiskowe, aktualizacje, dodawanie lig, rozwiązywanie problemów.
Użytkownik pracuje na Windows (VS Code, PowerShell, GitHub Desktop – git w wierszu poleceń nie jest zainstalowany), repo: `C:\GitHub\flask-football-app`.

## 1. Zmienne środowiskowe

Klucze **tylko** w `.env` (lokalnie, w `.gitignore`) i w *Render → Environment*. Nigdy w czacie, kodzie ani commitach. Wyciekły klucz – natychmiast unieważnij.

| Zmienna | Domyślnie | Do czego |
|---|---|---|
| `AUTO_BOOTSTRAP` | `1` (render.yaml) | aplikacja sama zasila bazę przy starcie |
| `BOOTSTRAP_LEAGUES` | `auto` | `auto` = ligi, które mają pliki w `history/`; albo lista `E0,D1,…` |
| `BOOTSTRAP_YEARS` | `4` | ile ostatnich sezonów |
| `REFRESH_HOURS` | `24` | co ile godzin odświeżać (0 = wyłączone) |
| `FOOTBALL_DATA_ORG_TOKEN` | – | darmowy token football-data.org: szybkie wyniki, terminarz, godziny, Liga Mistrzów (limit 10 zapytań/min, `FDORG_PAUSE`) |
| `GITHUB_TOKEN` | – | token **Contents: Read and write** wyłącznie dla tego repo – trwały dziennik i zakłady |
| `GITHUB_REPO` | – | dokładnie `safe-n/flask-football-app` (bez spacji/entera) |
| `LEDGER_BRANCH` | `ledger-data` | gałąź danych (PC: `ledger-data-local` – **nie zmieniać nazw zmiennych**) |
| `DB_PATH` | `data/football.db` | baza SQLite (PC: `data\football_local.db`) |
| `LOG_HORIZON_DAYS` | `10` | prognozy do dziennika tylko na najbliższe N dni |
| `FB_TZ`, `FB_MATCH_HOURS` | `Europe/Warsaw`, `2.5` | strefa wyświetlania godzin; po ilu godzinach od startu mecz = „zakończony?" |
| `SPORTSDB_KEY` | `123` | TheSportsDB (Liga Europy), darmowy klucz publiczny |
| `API_KEY`, `API_PROVIDER`, `API_HOST` | – / `rapidapi` | API-Football (opcjonalnie; darmowy plan bez bieżącego sezonu) |
| `AVAIL_ENABLED`, `AVAIL_DAILY_CAP` | `1`, `40` | kontuzje/składy (działają tylko z planem obejmującym bieżący sezon) |
| `ANTHROPIC_API_KEY`, `AI_ACCESS_CODE`, `AI_MODEL`, `AI_DAILY_LIMIT` | – | analiza AI zestawienia (płatna za użycie; kod dostępu chroni budżet) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | – | powiadomienia z akcji `daily` (sekrety GitHuba) |
| `ARCHIVE_ODDS` | `0` (CI: `1`) | archiwizacja kursów przedmeczowych do `history/odds/` |

## 2. Aktualizacja aplikacji

1. Zmiany ląduje się w repo (`master`). **Przed wysłaniem pobierz najnowszy `master`** (drugi wątek – tenis – pcha równolegle).
2. Każdy push = nowe wdrożenie na Renderze (rozruch ~1–2 min). Gałąź `ledger-data` nie wywołuje redeployu.
3. Kopia lokalna na PC: `http://localhost:5000/restart` → **„Aktualizuj i zrestartuj"** (git pull + pip + restart). Nie wgrywaj plików na PC ręcznie – tylko przez GitHub.
4. Po zmianie kodu: `python -m unittest discover -s tests -t .` – wszystkie testy mają przechodzić.

## 3. Codzienne i cotygodniowe automaty (GitHub Actions)

- **daily** (06:17 UTC): `bootstrap --leagues auto --years 4 --export-ledger` → `report` → opcjonalnie Telegram → commit (`git pull --rebase --autostash && git push`, 3 próby).
- **weekly:** `history-update` (nowe mecze do `history/*.csv`), strojenie parametrów (`tune`).
- **tests:** testy na każdy push. **init-history:** ręczny jednorazowy start historii dla wskazanych lig.
- Sekrety (Settings → Secrets → Actions): `FOOTBALL_DATA_ORG_TOKEN`, opcjonalnie `TELEGRAM_*`.

## 4. Render Free – co warto wiedzieć

- Dysk jest efemeryczny; serwis usypia po 15 min bez ruchu HTTP; limit 750 h/mies. na workspace (druga darmowa usługa je zjada).
- UptimeRobot: monitor HTTP(s) co **5 min** na `https://flask-football-app.onrender.com/healthz`. „Down" przy uśpieniu to nie błąd kodu; po wybudzeniu wraca „Up".
- `/healthz` zwraca zawsze 200 JSON, gdy proces żyje (rozbudza usługę). `/robots.txt` nie rozbudza.
- Start Command (wspólny z tenisem): `gunicorn combo:app --workers 1 --threads 4 --timeout 120`. Ustawień Rendera nie zmieniaj bez pytania właściciela infrastruktury.

## 5. Dodawanie i aktywacja ligi

Liga jest aktywna, gdy ma pliki `history/LIGA_ROK.csv` (przy `BOOTSTRAP_LEAGUES=auto`).

- **Ligi z CSV (football-data.co.uk):** `python -m fbpred history-init --league SP1 --seasons 2020-2026` → commit i push `history/`.
- **Liga Mistrzów (`CL`):** wymaga `FOOTBALL_DATA_ORG_TOKEN`; `history-init --league CL --seasons 2024-2026`.
- **Liga Europy (`EL`, TheSportsDB):**
  1. `python -m fbpred sportsdb-probe` – weryfikacja źródła (nazwa ligi, kolejki, statusy, liczba meczów).
  2. `python -m fbpred history-init --league EL --seasons 2025-2026`. Klucz publiczny jest współdzielony i bywa limitowany – gdy zobaczysz
     „CZĘŚCIOWO"/„limit zapytań", odczekaj 2–3 minuty i powtórz (np. `--seasons 2026-2026`). Komenda dopisuje, nie nadpisuje.
  3. Commit i push `history/EL_*.csv`; po wdrożeniu Render wciągnie EL sam. **Stan na 10.11.2026: kroki 2–3 nie zostały jeszcze wykonane w repo.**
  Ograniczenia EL: tylko gole (brak połówek/kartek/rożnych), model tylko z meczów EL, brak kursów w bazie; fazy po dogrywce/karnych pomijane.

## 6. Kopia lokalna na PC (skrót)

`lokalnie\uruchom_aplikacje.bat` → `lokalnie\serwer.py` (git pull + pip + waitress :5000 + pętla restartu), autostart `lokalnie\autostart_wlacz.bat`,
telefon przez Tailscale `http://desktop-8r4t2nq:5000/`. Osobne dane (`football_local.db`, `ledger-data-local`) – zakłady i dziennik lokalne nie są widoczne na Renderze (i odwrotnie).
Pełny opis: `NOTATKI-WSPOLNE.md`.

## 7. Rozwiązywanie problemów (z historii projektu)

| Objaw | Przyczyna | Rozwiązanie |
|---|---|---|
| „Brak nadchodzących meczów" mimo świeżych danych | stary `fixtures.csv` / filtr wczorajszych meczów | football-data.org dopisuje przyszłe mecze (`fill_upcoming`); 0.6.1 |
| Zestawienie „Ładowanie…" w nieskończoność | skrypt koszyka ładowany po elemencie, który go używa | skrypt w `<head>` (0.6.4) |
| CI: `200 != 503` w testach | testy widziały historię z repo/bazę | izolacja `HISTORY_DIR`, `PARAMS_DIR`, `DB_PATH` w testach |
| Akcja `daily` nie zapisuje do repo | wyścig pushów | `git pull --rebase --autostash && git push` w pętli 3 prób |
| UptimeRobot „Down" | serwis uśpiony | `/healthz` co 5 min; po wybudzeniu OK |
| Dziennik/zakłady znikają po restarcie Rendera | brak `GITHUB_TOKEN`/`GITHUB_REPO` lub zły zapis | uzupełnij zmienne; w zakładce **Dane** linia „Trwałość" powinna pokazać „GitHub, gałąź ledger-data: wczytano N prognoz" |
| `avail-probe`: „Free plans do not have access to this season" | API-Football bez bieżącego sezonu na darmowym planie | plan Pro (19 USD/mies.) albo bez kontuzji |
| `sportsdb-probe`: „limit zapytań" | współdzielony klucz publiczny | odczekać kilka minut; pobieranie zwraca wynik częściowy |
| Pobranie paczki zip z telefonu znika | przeglądarka mobilna | prosta nazwa pliku (np. `fbpred-0-9-5.zip`) albo pobranie z komputera |
| Test losowo pada o północy | przejście dnia w testach opartych o „dziś" | powtórz; (przyczyna niepotwierdzona) |

## 8. Bezpieczeństwo

- Klucze (RapidAPI, football-data.org, GitHub, Anthropic, Telegram, The Odds API) – wyłącznie `.env` / Render Environment / sekrety GitHuba.
- Stare repo miało klucze w kodzie – zostały unieważnione; nowe repo bez tej historii.
- Token GitHuba: minimalny zakres (Contents: Read and write, tylko to repo).
- Analiza AI jest za kodem dostępu i dziennym limitem; nie udostępniaj kodu osobom trzecim.
