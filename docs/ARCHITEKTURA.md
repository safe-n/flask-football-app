# Architektura – football-predictor (Rozdział 1, wersja 0.9.5)

## 1. Widok całości

```
 ŹRÓDŁA DANYCH                        APLIKACJA (Flask, pakiet fbpred)                 WYJŚCIA
 ─────────────                        ────────────────────────────────                 ───────
 football-data.co.uk  CSV ─┐
 football-data.org   API ──┤  bootstrap.py ──► db.py (SQLite: matches)  ──► predictor.py ──► web.py ──► przeglądarka / telefon
 TheSportsDB (EL)    API ──┤   (odświeżanie,        ▲                         │ (Dixon-Coles,          (zakładki, PDF)
 history/*.csv (repo) ─────┘    blokada, diag)      │                         │  regresje liczników)
                                                    │                         ▼
                              history.py ◄──────────┘               ledger.py (dziennik prognoz)
                              (CSV = prawda)                        bets.py   (moje zakłady)
                                                                          │
                                         gh_store.py ◄────────────────────┘  (zapis CSV na gałąź ledger-data przez GitHub API)

 GitHub Actions: daily (dane → prognozy → rozliczenie → raport) · weekly (history-update, tune) · tests · init-history
 Render Free: gunicorn combo:app  (piłka pod „/", tenis pod „/tennis/")   ·   Kopia lokalna na PC: waitress :5000 (osobna baza i gałąź ledger)
```

## 2. Struktura repozytorium

| Ścieżka | Zawartość | Właściciel |
|---|---|---|
| `fbpred/` | pakiet piłki (poniżej) | wątek piłki |
| `templates/` | szablony Jinja: `base.html` (CSS + skrypt koszyka i kafelków w `<head>`), `picks.html` (Moje typy), `page.html` (bloki p/h/tabs/html/t), `index.html` (Mecze), `match.html`, `suggest.html`, `coupon.html`, `bets.html` | piłka |
| `history/` | `LIGA_ROK.csv` – zakończone mecze (prawda), `odds/` – archiwum kursów przedmeczowych, `UPDATES.log` | piłka |
| `params/` | `params_LIGA.json` – strojone parametry (ridge, xi, blend_w, shot_weight) | piłka |
| `ledger/` | `predictions.csv`, `REPORT.md` – zapis codziennej akcji | piłka |
| `tests/` | `unittest`, jeden plik na wersję (`test_v61.py` … `test_v93.py`), `__init__.py` izoluje `PARAMS_DIR`/`HISTORY_DIR` | piłka |
| `docs/` | ta dokumentacja | piłka |
| `.github/workflows/` | `daily`, `weekly`, `init-history`, `tests`, `tennis-weekly` | wspólne (`tennis-weekly` – tenis) |
| `tnpred/`, `tennis_*`, `combo.py`, `requirements.txt`, `render.yaml`, `Dockerfile`, `lokalnie/` | tenis i infrastruktura | wątek „Tenis + infrastruktura" – **nie ruszać** bez uzgodnienia |

## 3. Moduły pakietu `fbpred/`

| Obszar | Moduły | Rola |
|---|---|---|
| Konfiguracja | `config.py`, `leagues.py`, `names.py` | zmienne środowiskowe; katalog lig (`E0`…`CL`, `EL`; `NO_CSV`); normalizacja nazw drużyn |
| Dane | `csvdata.py`, `fdorg.py`, `sportsdb.py`, `extsource.py`, `fetch.py`, `history.py`, `db.py`, `bootstrap.py`, `quality.py` | pobieranie, parsowanie, zapis `history/`, SQLite, odświeżanie w tle (blokada `refresh.lock`, diagnostyka `diag.json`) |
| Modele | `models/` (goals, counts, markets), `predictor.py`, `params.py`, `fatigue.py`, `rest.py`, `profile.py` | Dixon-Coles + regresje, skład prognozy, parametry per liga, testy hipotez (zmęczenie, profil remisów) |
| Rynek | `odds.py`, `betmarkets.py`, `draws.py`, `simulate.py` | de-vig, miks z rynkiem, edge, Kelly; katalog rynków i identyfikatory typów `liga~data~dom~gość~klucz`; ranking remisów; Monte Carlo tabeli |
| Ocena | `backtest.py`, `recent.py`, `recent_vis.py`, `stats.py`, `h2h.py`, `ledger.py`, `report.py` | walk-forward, retrospektywa, bazowe częstości (średnie ligi), kafelki/kolory, H2H i forma, dziennik |
| Użytkownik | `web.py`, `suggest.py`, `bets.py`, `picks.py`, `pdfexport.py`, `kickoff.py`, `ai.py`, `notify.py`, `gh_store.py`, `cli.py` | strony i API, Podpowiedzi, Moje zakłady, Moje typy (0.10.0), PDF, godzina/status meczu, analiza AI (opcjonalnie), Telegram, trwałość na GitHubie, CLI |
| Opcjonalne | `avail.py` | kontuzje/składy z API-Football (wymaga planu z bieżącym sezonem) |

## 4. Dane i baza

- **Źródło prawdy:** `history/LIGA_ROK.csv`. Kolumny (`db.COLUMNS`): `fixture_id, league, season, date, home, away, referee, status, hg, ag, hg_ht, ag_ht,
  h_shots, a_shots, h_sot, a_sot, h_corners, a_corners, h_yellow, a_yellow, h_red, a_red, stats_done, o_home, o_draw, o_away, o_over25, o_under25, o_btts_yes, o_btts_no`.
- **SQLite** (`data/football.db`, w `.gitignore`): tabela `matches` (`DB_COLUMNS` = `COLUMNS` + `kickoff` UTC), tabela `predictions` (dziennik), `bets` (moje zakłady).
  Starsze bazy migrują się same (`ALTER TABLE` przy `db.connect`).
- **`fixture_id`:** stabilny skrót crc32 z `liga|data|gospodarz|gość` – ten sam mecz z różnych źródeł nie dubluje się.
- **Upsert** nie nadpisuje wartości `NULL` (COALESCE) – nowe źródło uzupełnia, nie kasuje.
- **Godzina startu (`kickoff`):** `utcDate` z football-data.org lub kolumna `Time` z CSV (czas brytyjski → UTC); wyświetlana w `FB_TZ` (domyślnie Europe/Warsaw).

### Cykl danych w aplikacji (`bootstrap.py`)
1. Start: wczytaj `history/` do SQLite (liga wchodzi do aplikacji, gdy ma pliki w `history/`; `BOOTSTRAP_LEAGUES=auto`).
2. Tło: odśwież bieżący sezon (CSV), uzupełnij nadchodzące mecze i godziny z football-data.org (`fill_upcoming`), dla `CL`/`EL` – przez `extsource`.
3. Zapisz prognozy najbliższych dni do dziennika (`LOG_HORIZON_DAYS`), rozlicz zakończone.
4. Dziennik/zakłady → CSV na gałąź `ledger-data` (`gh_store`), przy starcie pobranie (`INSERT OR IGNORE`).
5. Co `REFRESH_HOURS` (domyślnie 24) – powtórz.

## 5. Trwałość

| Dane | Gdzie żyją | Jak przeżywają restart Rendera |
|---|---|---|
| Wyniki meczów | `history/*.csv` w repo (aktualizuje je akcja `weekly`/`daily`) | tak – start ładuje z repo |
| Dziennik prognoz | tabela `predictions` + `ledger/predictions.csv` (Actions) + gałąź `ledger-data` (aplikacja) | tak, **jeśli** na Renderze są `GITHUB_TOKEN` i `GITHUB_REPO` |
| Moje zakłady | tabela `bets` + `ledger/bets.csv` na `ledger-data` | jak wyżej |
| Moje typy i ich kupony (0.10.0) | tabele `picks`, `pick_coupons` + `ledger/picks.csv`, `ledger/pick_coupons.csv` na `ledger-data` | jak wyżej |
| Parametry modeli | `params/*.json` w repo | tak |
| Koszyk (Zestawienie), stawka | `localStorage` przeglądarki (`fb_coupon`, `fb_stake`) | per przeglądarka |

Kopia lokalna na PC używa `DB_PATH=data\football_local.db` i `LEDGER_BRANCH=ledger-data-local` – nie miesza się z Renderem.

## 6. Strony i API (`web.py`)

Strony: `/` Mecze · `/match` · `/suggest` Podpowiedzi · `/coupon` Zestawienie · `/draws` · `/stats` · `/table` · `/strengths` ·
`/recent` Ostatnie · `/track` Dziennik · `/bets` Moje zakłady · `/picks` Moje typy · `/data` Dane (diagnostyka) · `/profile`.
API/eksport: `/api/coupon`, `/api/predict`, `/api/bets` (POST), `/bets/<id>/<akcja>` (POST), `/api/picks` (POST, przełącznik kafelka; 409 dla zatwierdzonych), `/picks/confirm`, `/picks/<id>/<hit|miss|void|open|kurs|delete>` (POST), `/api/ai/coupon` (POST, kod dostępu),
`/export/recent.pdf`, `/export/journal.pdf`, `/export/coupon.pdf`, `/healthz` (zawsze 200 JSON, gdy proces żyje).

Wzorce interfejsu: kafelki z średnią ligi i kolorami, chipy H2H/formy (W/R/P), pasek formy modelu (✓/✗), wykres trafności rynków (CSS),
koszyk w `localStorage` z żywym AKO, PDF (reportlab + DejaVu w `fbpred/fonts/`, polskie znaki), tryb jasny/ciemny, układ na 390 px.

## 7. CLI (`python -m fbpred …`)

Dane: `fetch-csv`, `import-csv`, `fetch-fixtures`, `fetch-api`, `upcoming`, `history-init`, `history-update`, `history-export`, `history-status`, `bootstrap`, `check`, `teams`.
Modele i ocena: `backtest`, `tune`, `predict`, `upcoming-predict`, `simulate`, `strengths`, `stats`, `recent`, `draws`, `profile`, `fatigue-test`, `h2h-test`.
Dziennik i raporty: `log`, `track`, `daily`, `report`, `notify`.
Diagnostyka: `avail-probe` (API-Football), `sportsdb-probe` (Liga Europy). Inne: `demo` (sztuczna liga), `serve`.

## 8. Wdrożenie

- **Render Free:** `gunicorn combo:app --workers 1 --threads 4 --timeout 120`, health check `/healthz`; `combo.py` montuje piłkę pod `/` i tenis pod `/tennis/`.
- **UptimeRobot:** HTTP co 5 min na `/healthz` (utrzymuje serwis rozbudzony; „Down" przy usypianiu nie jest błędem kodu).
- **GitHub Actions:** `daily` 06:17 UTC (dane → prognozy → raport → opcjonalnie Telegram → commit z `git pull --rebase --autostash && git push` w pętli 3 prób),
  `weekly` (aktualizacja historii i strojenie), `tests`, `init-history` (ręczny start).
- **PC:** `lokalnie\uruchom_aplikacje.bat` → `lokalnie\serwer.py` (git pull + pip + waitress :5000, `/restart` = „Aktualizuj i zrestartuj"), dostęp z telefonu przez Tailscale.

## 9. Testy i jakość

- `python -m unittest discover -s tests -t .` (ponad 240 testów; wszystkie mają przechodzić przed pushem).
- Testy izolują `PARAMS_DIR`, `HISTORY_DIR` i `DB_PATH` (tymczasowe katalogi) – w przeciwnym razie CI widzi stan repo/bazy i daje fałszywe błędy.
- Strony testowane Flask test clientem; wygląd – zrzutami Playwright (Chromium) w trybie jasnym i ciemnym na 390 px.
- Dane syntetyczne (`synthetic.py`) do testów bez internetu; zbyt dobre wyniki na DEMO nic nie znaczą.

## 10. Współpraca z wątkiem tenisowym

Jedno repo, dwa niezależne wątki. Zasady (pełne w `NOTATKI-WSPOLNE.md`): przed pushem `git pull --rebase`; piłka rusza tylko swoje
katalogi; zmiany w `requirements.txt`, `combo.py`, `render.yaml`, `lokalnie/` tylko za zgodą drugiego wątku (linia `openpyxl>=3.1` musi zostać);
ważne zmiany → wpis w dzienniku `NOTATKI-WSPOLNE.md`.
