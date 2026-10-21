# Zmiany

## 0.2.0
- **Dziennik prognoz** (`log`, `track`, `daily`): zapis przed meczem, rozliczanie po meczu, log-loss na żywo vs rynek.
- **Miks model + rynek** (kursy bez marży metodą potęgową), optymalna waga z backtestu, zapisywana przez `tune`.
- **`tune`**: automatyczny dobór ridge/xi per liga (zapis `data/params_<liga>.json`).
- **Backtest**: przedziały ufności (bootstrap) i werdykt "istotne / szum"; symulacja zakładów po prawdziwych kursach z marżą.
- **Nowe rynki**: podwójna szansa, DNB, handicapy azjatyckie, sumy drużyn, czyste konto, wygrana do zera, dokładna suma goli.
- **`simulate`**: Monte Carlo reszty sezonu (mistrz, puchary, spadek, oczekiwane punkty i miejsce).
- **`check`**: kontrola jakości danych (duplikaty, HT>FT, podobne nazwy drużyn, pokrycie kolumn, marża kursów).
- **`strengths`**: ranking drużyn i mnożniki kartkowe sędziów. **`fetch-fixtures`**: nadchodzące mecze z kursami (CSV).
- Web: podstrony Tabela / Siła drużyn / Dziennik. CI (GitHub Actions) i Dockerfile.

## 0.1.0
- Dixon-Coles, modele zliczeń (kartki, rożne, połowy), backtest walk-forward, import CSV i API-Football, web i CLI.
