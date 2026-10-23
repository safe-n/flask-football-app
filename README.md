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


## Deploy na Render - skąd aplikacja bierze dane

`.gitignore` celowo wyklucza `data/` i `*.db`, więc baza NIE jedzie na GitHuba. Zamiast tego aplikacja
**sama zasila bazę** (`AUTO_BOOTSTRAP=1`): przy starcie pobiera ostatnie sezony z football-data.co.uk
(w tle, strona pokazuje "Ładowanie danych" i sama się odświeża), a potem co `REFRESH_HOURS` dociąga bieżący
sezon, nadchodzące mecze z kursami i zapisuje prognozy do dziennika.

| Plan Rendera | Co się dzieje z bazą | Dziennik prognoz |
|---|---|---|
| **Darmowy** | znika przy każdym restarcie i uśpieniu (po 15 min bez ruchu); przy wybudzeniu ładuje się od nowa (kilka sekund) | nie przetrwa - do testów |
| **Płatny + Persistent Disk** | trwała (`/var/data`), odświeżanie w tle co 24 h | trwały - tu ma sens `track` |

Ważne ograniczenia Rendera (z dokumentacji): dysk działa tylko na płatnych serwisach, jest dostępny wyłącznie dla
jednego serwisu (nie dla Cron Joba ani jednorazowych zadań), a Cron Job nie może mieć dysku. Dlatego odświeżanie działa
**wewnątrz** serwisu WWW, a nie jako osobny Cron. Używaj jednego workera (`--workers 1`, jak w `render.yaml`).

Ręcznie: `python -m fbpred bootstrap --leagues E0,D1 --years 4`. Zmienne: `AUTO_BOOTSTRAP`, `BOOTSTRAP_LEAGUES`,
`BOOTSTRAP_YEARS`, `REFRESH_HOURS` (patrz `.env.example`).


## Wersja w 100% darmowa z trwałym dziennikiem (Render Free + GitHub Actions)

Render Free gubi pliki, ale dziennik prognoz może mieszkać w repo:

1. **GitHub Actions** (`.github/workflows/daily.yml`) codziennie o 06:17 UTC: pobiera dane, zapisuje prognozy
   nadchodzących meczów, rozlicza zakończone i zapisuje `ledger/predictions.csv` + `ledger/REPORT.txt` do repo.
2. Commit uruchamia redeploy na Renderze, a aplikacja przy starcie wczytuje `ledger/predictions.csv`, więc strona
   **Dziennik** (`/track`) ma pełną historię mimo tymczasowego dysku.
3. Prognozy są **zamrażane w dniu meczu** (nie da się ich nadpisać po fakcie) - to uczciwy test.

Uruchomienie: wrzuć projekt na GitHuba → zakładka *Actions* → workflow `daily` → *Run workflow* (pierwszy raz ręcznie).
Jeśli push z workflow się nie uda: *Settings → Actions → General → Workflow permissions → Read and write*.

Dobrze wiedzieć (z dokumentacji GitHub): Actions są darmowe dla publicznych repo (prywatne mają miesięczny limit minut),
a harmonogram w publicznym repo wyłącza się po 60 dniach bez aktywności - wtedy włącz go ręcznie w zakładce Actions.
Dziennik jest w publicznym repo widoczny dla wszystkich (nie ma tam kluczy, tylko prawdopodobieństwa i kursy).
Każdy codzienny commit = redeploy na Renderze (zużywa darmowe minuty buildów, ale to rząd 1-2 min dziennie).


## Architektura danych (od 0.3): historia w CSV jako źródło prawdy

```
history/E0_2024.csv, E0_2025.csv ...   zakończone mecze (1 plik = liga + sezon, małe diffy w gicie)
history/odds/E0.csv                    archiwum kursów PRZEDMECZOWYCH (dopisywane codziennie)
history/aliases.json                   opcjonalne ujednolicenie nazw drużyn
history/UPDATES.log                    kto/kiedy/ile dopisał
ledger/predictions.csv, REPORT.md      dziennik prognoz i raport (codziennie)
```
Aplikacja przy starcie wczytuje `history/` **offline** (sekundy, zero zależności od źródła), a dopiero potem odświeża
bieżący sezon. SQLite jest tylko tymczasowym cache'em.

**Jednorazowy start** (wybierz jedno):
```bash
python -m fbpred history-export                              # masz już lokalną bazę? przenieś ją do history/
python -m fbpred history-init --league E0 --seasons 2018-2025   # albo pobierz sezony od zera
git add history && git commit -m "historia" && git push
```
**Potem automatycznie:** workflow `weekly-history` (poniedziałek) dopisuje nowe mecze (upsert po `fixture_id`: nowe
dochodzą, poprawione wyniki się aktualizują, **nic nie jest kasowane**, błędne wiersze są odrzucane i raportowane).
Workflow `daily` zapisuje prognozy, kursy do archiwum i dziennik. Oba piszą do repo pojedynczo (wspólna kolejka).

Komendy: `history-status` (pokrycie danych), `history-update`, `history-export`, `history-init`.

## Powiadomienia Telegram (darmowe)

1. W Telegramie napisz do **@BotFather** → `/newbot` → skopiuj token. Napisz cokolwiek do swojego bota.
2. Chat id: otwórz `https://api.telegram.org/bot<TOKEN>/getUpdates` i odczytaj `chat.id`.
3. W repo: *Settings → Secrets and variables → Actions* → dodaj `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`.

Codzienny workflow wyśle zestawienie prognoz (1X2 z miksem z rynkiem, O2.5, BTTS, remis do przerwy, typy z przewagą).
Bez sekretów krok po prostu się pomija. Podgląd bez wysyłki: `python -m fbpred notify --dry-run`. Token trzymaj
wyłącznie w sekretach/zmiennych środowiskowych.

## Wiele lig

W workflowach zmień `LEAGUES: "E0"` na np. `"E0,D1,SP1"` (kody football-data.co.uk) i raz uruchom
`history-init --league E0,D1,SP1`. Każda liga ma własny model i własne parametry (`tune --league D1`).

## Celne strzały w modelu bramek

`tune` ma etap 2: sprawdza, czy mieszanie prognozy bramek z modelem celnych strzałów (stabilniejszy sygnał, bo zdarzeń
jest ~3x więcej) poprawia log-loss, i zapisuje `shot_weight`. Ręcznie: `backtest --shot-weight 0.5`.
Uwaga: na danych syntetycznych to działa z konstrukcji generatora - wiarygodna jest dopiero ocena na prawdziwych meczach.


## Rozwiązywanie problemów: Render pokazuje "idle" / pustą bazę

Od 0.3.1 historia z `history/` jest wczytywana do SQLite **przy każdym starcie, offline** (bez wątku i bez sieci),
więc strona działa od razu. `AUTO_BOOTSTRAP` włącza tylko odświeżanie z internetu (bieżący sezon, kursy, dziennik) i na
Renderze jest domyślnie włączone (wykrywane przez `RENDER=true`). Zmienną możesz zapisać jako `1`, `true`, `yes` lub `on`.

Jeśli mimo to coś nie działa, sprawdź w logach Rendera linię `[bootstrap] start: {...}` (pokazuje wartości konfiguracji
i liczbę meczów w bazie) oraz stronę `/data`, która pisze wprost, co jest wyłączone i dlaczego.
Pamiętaj: `render.yaml` stosuje się tylko do usług utworzonych z Blueprintu. Jeśli usługę tworzyłeś ręcznie w panelu,
zmienne ustawiaj w *Render → usługa → Environment*.
Nie wrzucaj do `history/` sztucznej ligi DEMO (`history-export` pomija ją domyślnie); usuń ją: `git rm history/DEMO_*.csv`.


## Wiele lig i Liga Mistrzów (od 0.4)

**Ligi krajowe** (football-data.co.uk, bez klucza): `E0` Premier League, `E1` Championship, `D1` Bundesliga, `SP1` La Liga,
`I1` Serie A, `F1` Ligue 1, `N1` Eredivisie, `P1` Primeira Liga, `B1`, `T1`, `G1`, `SC0` i inne z katalogu `fbpred/leagues.py`.
1. GitHub → *Actions* → **init-history** → *Run workflow* (domyślnie `E0,D1,SP1,I1,F1,N1,P1,CL` i sezony `2020-2025`).
2. Render → *Environment* → ustaw `BOOTSTRAP_LEAGUES=auto` (wszystkie ligi z `history/`; nic więcej nie trzeba wpisywać).
Workflowy `daily` i `weekly-history` też działają w trybie `auto`, więc nowa liga dołącza się sama.

**Liga Mistrzów** nie występuje w football-data.co.uk, więc dane idą z football-data.org (darmowy token, 10 zapytań/min):
1. Zarejestruj się na football-data.org/client/register i skopiuj token.
2. GitHub → *Settings → Secrets and variables → Actions* → sekret `FOOTBALL_DATA_ORG_TOKEN`; Render → *Environment* → ta sama zmienna.
3. Uruchom `init-history` z `CL` na liście lig.

Ograniczenia LM (uczciwie): darmowy plan nie daje kursów ani statystyk, więc dla LM są 1X2, gole, BTTS i remis do przerwy,
**bez kartek i rożnych**; ok. 190 meczów na sezon i drużyny z różnych lig powodują, że model jest dużo mniej pewny niż dla
ligi krajowej (bardziej "w stronę średniej"). Dodatkowo plan darmowy może nie udostępniać starszych sezonów (zobaczysz to w logu).

## Statystyki sędziów, kartek i rożnych

Strona **Statystyki** (`/stats`): sędziowie (średnie żółtych/czerwonych/rożnych, odchylenie od ligi, mnożnik z modelu, który
uwzględnia małą próbę) oraz drużyny (kartki i rożne zdobyte/stracone, mnożniki `kartki_x` i `rozne_x`). Strona **Mecz** (`/match`):
wybierasz gospodarza, gościa i sędziego, a dostajesz komplet rynków (1X2, gole, połowy, kartki, rożne, handicapy, czyste konto).
W konsoli: `python -m fbpred stats --league E0 --view referees` / `--view teams`.

## Dlaczego "Brak nadchodzących meczów"?

Terminarz pochodzi z `fixtures.csv` (football-data.co.uk), a gdy tam nie ma meczów danej ligi - z football-data.org (jeśli ustawiono
token). Strona **Dane** pokazuje teraz krok po kroku, co się udało, a co nie (np. "plik pobrany, ale bez nadchodzących meczów tej ligi"
albo "zapas wyłączony: brak tokenu"). Bez tokenu i z pustym `fixtures.csv` terminarza po prostu nie ma skąd wziąć.


## Rynki remisowe (0.4.1)

Model zna pięć rynków remisowych i liczy je z oczekiwanych goli osobno dla 1. i 2. połowy (Poisson / ujemna dwumianowa):
**remis do przerwy**, **remis w 2. połowie**, **remis w 1. LUB 2. połowie** (`draw_either_half`),
**remis do przerwy LUB na koniec meczu** (`draw_ht_or_ft` = P(HT) + P(FT) − P(HT i FT)) oraz remis na koniec meczu.
Jak xG wpływa na remis: im więcej goli oczekiwanych w połowie, tym rzadszy remis (suma xG 0,6 → ~60%, 1,2 → ~42%, 2,0 → ~31%),
a mecze wyrównane remisują częściej niż jednostronne. Dokładny rachunek robi aplikacja, więc nie trzeba go liczyć ręcznie.

* Strona **Remisy** (`/draws`) i komenda `python -m fbpred draws --market ht_or_ft` rankingują nadchodzące mecze,
  pokazują uczciwy kurs (1/p) i różnicę względem średniej ligi. Stawiaj tylko, gdy kurs bukmachera jest wyraźnie wyższy.
* `backtest` wypisuje **tabelę obciążenia** (średnia prognoza vs faktyczna częstość) i werdykt „zawyża / zaniża / ok”.
* `tune` (etap 3) koryguje obciążenie tych rynków przesunięciem logitów, ale tylko gdy różnica przekracza 3 błędy
  standardowe (inaczej model goniłby za szumem). Dziennik prognoz zapisuje oba nowe rynki, więc `track` pokaże ich skuteczność na żywo.
* Uwaga: football-data.co.uk nie ma kursów na remis do przerwy ani na „HT lub FT”, więc nie da się policzyć zysku z historii;
  można sprawdzić tylko, czy prawdopodobieństwa są wiarygodne. Opłacalność zweryfikujesz porównując `kurs_fair` z kursem u bukmachera.
