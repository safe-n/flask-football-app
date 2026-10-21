# football-predictor

Prawdopodobieństwa dla meczów ligowych: **1X2, over/under goli, BTTS, dokładne wyniki, remis do przerwy / w 2. połowie
(w którejkolwiek / w obu), połowa-mecz (HT/FT), żółte kartki (z efektem sędziego), rzuty rożne** + backtest i porównanie z kursami.

## Szybki start (5 minut, bez żadnych kluczy)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # Windows: copy .env.example .env

python -m fbpred fetch-csv --league E0 --seasons 2020-2024   # darmowe dane: wyniki, połowy, kartki, rożne, sędziowie, kursy
python -m fbpred backtest --league E0 --min-train 380        # uczciwa ocena modelu
python -m fbpred predict --league E0 --home Arsenal --away Chelsea --referee "M Oliver"
python -m fbpred serve                                       # aplikacja web na http://127.0.0.1:5000
```

Bez internetu: `python -m fbpred demo` generuje **sztuczną** ligę (`DEMO`) do testów.

## Codzienna praca (zalecany workflow)

```bash
python -m fbpred check --league E0          # 1. czy dane są czyste?
python -m fbpred tune --league E0           # 2. dobierz ridge/xi i wagę miksu z rynkiem (raz na jakiś czas)
python -m fbpred backtest --league E0       # 3. uczciwa ocena + "czy to szum?" (przedziały ufności)
python -m fbpred daily --league E0          # 4. każdego dnia: dane → zapis prognoz → rozliczenie
python -m fbpred track --league E0          # 5. raport z dziennika (jedyny test na żywo)
python -m fbpred simulate --league E0       # tabela: szanse na mistrza, puchary, spadek
python -m fbpred strengths --league E0      # siła drużyn, mnożniki sędziów
python -m fbpred predict --league E0 --home Arsenal --away Chelsea --odds 1.9 3.6 4.2
```
`daily` ma tryb API: `python -m fbpred daily --league 39 --source api`. Do automatyzacji użyj crona / GitHub Actions / Render cron.

## Źródła danych

| Źródło | Komenda | Zalety |
|---|---|---|
| football-data.co.uk (CSV) | `fetch-csv` / `import-csv` | wiele sezonów za darmo, kartki, rożne, sędziowie, kursy zamknięcia |
| API-Football (RapidAPI) | `fetch-api`, `upcoming` | nadchodzące mecze, wiele lig, kursy przedmeczowe |

Uwagi:
- **Nie mieszaj źródeł w jednej lidze** (inne nazwy drużyn). CSV używa kodów lig (`E0`), API numerów (`39`).
- API ma dzienne limity i ograniczenia sezonów zależne od planu. Odpowiedzi są cache'owane w `data/cache`, a pobieranie
  statystyk jest wznawialne - uruchamiaj codziennie, aż uzupełni całość.
- Kursy w API-Football dla starych meczów bywają niedostępne. Zbieraj je na bieżąco (`upcoming`), budując własną historię.

## Jak to działa

- **Bramki:** Dixon-Coles (Poisson z atakiem/obroną drużyn, przewagą domu, korektą niskich wyników `rho`),
  wagi czasowe (nowsze mecze ważą więcej), ridge (shrinkage ogranicza nadmierną pewność).
- **Kartki, rożne, gole w połowach:** regresja Poissona / ujemna dwumianowa (`models/counts.py`), efekt drużyny, rywala i
  (dla kartek) sędziego. Połowy modelowane osobno, stąd remis do przerwy / w 2. poł. i HT/FT.
- **Backtest walk-forward:** model uczy się tylko na przeszłości. Miary: log-loss, Brier, RPS, kalibracja,
  porównanie do średniej ligowej i do bukmachera (log-loss mniejszy = lepiej).
- **Miks z rynkiem:** kursy po usunięciu marży (metoda potęgowa) łączone z modelem wagą dobraną w backteście.
  Zwykle najlepszy wynik daje przewaga rynku (np. 20% model + 80% rynek) - to normalne.
- **Nowe rynki:** podwójna szansa, DNB, handicapy azjatyckie, sumy drużyn, czyste konto, wygrana do zera.
- **Symulacja sezonu:** Monte Carlo z tych samych macierzy wyników (remisy rozstrzygane różnicą bramek).
- Strojenie ręczne: `python -m fbpred backtest --league E0 --ridge 15 --xi 0.001`, automatyczne: `tune`.

## Co musisz wiedzieć (uczciwie)

- Kursy zamknięcia są bardzo dobrym predyktorem. Jeśli w backtestcie model nie bije kolumny `bukmacher`, to nie ma
  przewagi - to normalne i typowe. Zacznij od pytania „czy jestem dobrze skalibrowany?", nie „czy zarabiam?".
- Przewaga >15% nad kursem to prawie zawsze **błąd modelu**, nie okazja (CLI i web ostrzegają).
- Wyniki w `DEMO` pochodzą z generatora, nie mówią nic o prawdziwym futbolu.
- Rynki kartek/rożnych nie mają w danych bukmachera do porównania, oceniasz je tylko względem średniej ligowej.

## Bezpieczeństwo - po starym repo

Stare repo miało klucze wpisane w kodzie (RapidAPI, OpenAI, hasło do bazy Postgres). Zrób:
1. **Odwołaj** klucze: RapidAPI (nowy klucz), OpenAI (platform.openai.com → API keys → Revoke), zresetuj hasło bazy na Renderze.
2. Załóż **nowe repo** i wrzuć ten projekt (nie kopiuj historii ze starego). Stare repo ustaw jako *private* albo usuń.
3. Klucze trzymaj tylko w `.env` lokalnie i w *Environment* na Renderze. `.env` jest w `.gitignore`.

## Struktura

```
fbpred/
  config.py      konfiguracja z .env
  db.py          SQLite (jedna tabela matches)
  csvdata.py     import football-data.co.uk
  fetch.py       klient API-Football (cache, limity, wznawianie)
  models/        goals.py (Dixon-Coles), counts.py (kartki/rożne/połowy), markets.py
  predictor.py   składa modele w prognozę meczu
  backtest.py    walk-forward + metryki + kalibracja
  odds.py        usuwanie marży, miks z rynkiem, edge, Kelly
  ledger.py      dziennik prognoz (log/rozliczanie/raport)
  simulate.py    Monte Carlo tabeli
  quality.py     kontrola jakości danych
  params.py      zapisane parametry per liga
  web.py, cli.py, synthetic.py
tests/           python -m unittest
```

## Pomysły na dalej
Kilka lig w jednym modelu (siła lig, puchary europejskie), składy/absencje, xG, kalibracja izotoniczna,
model na żywo (in-play), alerty (Telegram/e-mail) z `daily`.
