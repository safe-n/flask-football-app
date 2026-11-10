# Koncepcja i założenia – football-predictor (Rozdział 1)

Dokument opisuje **po co** aplikacja powstała, **jakimi zasadami** się kieruje i **dlaczego** podjęto kluczowe decyzje.
Stan na zamknięcie Rozdziału 1: wersja **0.9.5** (10.11.2026). Kontekst techniczny: `ARCHITEKTURA.md`, obsługa: `INSTRUKCJA.md`.

## 1. Cel

Prywatne, darmowe narzędzie, które dla meczów ligowych szacuje **prawdopodobieństwa zdarzeń** (1X2, gole, BTTS, remisy
w połowach, żółte kartki, rożne) i pomaga **świadomie wybierać i oceniać typy** – zamiast obstawiać „na czuja".

Aplikacja ma odpowiadać na trzy pytania:
1. *Ile procent daje model temu zdarzeniu* i czy to dużo na tle średniej ligi? (kafelki, kolory)
2. *Czy kurs bukmachera jest wyższy niż uczciwy kurs z modelu?* (przewaga/edge, AKO, EV)
3. *Czy model w ogóle ma rację?* (dziennik prognoz, retrospektywa „Ostatnie", moje zakłady)

Użytkownik: jedna osoba (hobbysta), po polsku, Windows + telefon, bez budżetu na infrastrukturę.

## 2. Założenia nadrzędne

| # | Założenie | Konsekwencja w projekcie |
|---|---|---|
| 1 | **Wszystko za darmo / hobbystycznie** | Render Free, GitHub Actions, football-data.co.uk, football-data.org (darmowy token), TheSportsDB (klucz publiczny); płatne API tylko jako opcja „gdy będzie budżet" |
| 2 | **Uczciwość statystyczna ponad efekt „wow"** | Wszędzie ostrzeżenia o małej próbie; model porównywany z rynkiem; wynik „model nie bije rynku" jest akceptowany i raportowany |
| 3 | **Narzędzie do selekcji, nie wyrocznia** | Brak obietnic zysku; flagi (⚑ H2H, „przewaga >15% to zwykle błąd modelu") są sygnałami do oceny wzrokowej |
| 4 | **Przejrzystość** | Każda liczba da się wyjaśnić (tooltip, legenda, dokumentacja); testy tam, gdzie można pomylić się cicho |
| 5 | **Dane jako źródło prawdy w repo** | Pliki `history/*.csv` są prawdą; baza SQLite jest wtórna i może zniknąć |
| 6 | **Odporność na efemeryczny hosting** | Render Free kasuje dysk – dziennik i zakłady zapisują się na GitHubie |
| 7 | **Prostota operacyjna** | Jeden proces (gunicorn 1 worker), brak zewnętrznej bazy, brak kolejek, zero stałych kosztów |
| 8 | **Bezpieczeństwo kluczy** | Tylko `.env` (poza repo) i panel Rendera; nigdy w czacie ani w kodzie |

## 3. Czego aplikacja świadomie NIE robi

- Nie obiecuje przewagi nad rynkiem. Kursy zamknięcia są bardzo dobrym predyktorem; model ≈ rynek to normalny wynik.
- Nie stawia zakładów i nie łączy się z bukmacherami. „Moje zakłady" to wyłącznie notatnik/rozliczalnik.
- Nie obsługuje zakładów na żywo (in-play) ani rynków graczy.
- Nie zgaduje rynków bez danych: remisy w połowach nie mają historycznych kursów, kartki/rożne – tylko porównanie do średniej ligi.
- Nie miesza źródeł danych w jednej lidze (różne pisownie drużyn).
- Nie jest wieloużytkownikowa (brak logowania; AI chronione kodem dostępu).

## 4. Koncepcja modelowania

**Bramki – Dixon-Coles.** Poisson z atakiem/obroną drużyn, przewagą domu, korektą niskich wyników (`rho`), wagami czasowymi
(`xi` – nowsze mecze ważą więcej) i regularyzacją ridge (ogranicza nadmierną pewność). Opcjonalna waga celnych strzałów
(`shot_weight`) zasila siłę drużyn dodatkową informacją niż same gole.

**Liczniki – regresje.** Kartki, rożne i gole w połowach: Poisson / ujemna dwumianowa z efektem drużyny, rywala i
(dla kartek) sędziego. Połowy modelowane osobno jako niezależne → z nich wynikają remis do przerwy / w 2. połowie /
„HT lub 2H" / „HT lub FT".

**Rynek jako kotwica.** Kursy bez marży (metoda potęgowa) można mieszać z modelem wagą dobraną w backteście (`tune`).
W zapisanych parametrach lig `blend_w` wynosi obecnie 0.0 – wybór wagi należy do procedury `tune`, nie do ręcznych poprawek.

**Ocena.** Walk-forward backtest (model uczy się tylko na przeszłości): log-loss, Brier, RPS, kalibracja, porównanie do
średniej ligi i do bukmachera. Jedynym prawdziwym testem „na żywo" jest **dziennik prognoz** (prognoza zapisana PRZED meczem,
rozliczana po wyniku).

**Wyróżnianie wartości (kafelki).** Zamiast progu bezwzględnego używamy odchylenia od **średniej ligi z ostatnich 3 sezonów**:
dla procentów ±8 pp (duże), z mniejszym progiem min(3 pp, margines/2) dla słabszego wyróżnienia; dla średnich liczników ±12% / ±5%.
Zielony = powyżej średniej, czerwony = poniżej – to szybka ocena wzrokowa, nie rekomendacja zakładu.

**H2H.** Pokazywany, bo użytkownik używa go do wychwytywania underdogów. Jego wartość predykcyjna jest słaba i zależy od
małej próby, dlatego flaga ⚑ nie zmienia prawdopodobieństw modelu, a komenda `h2h-test` pozwala sprawdzić na historii, czy H2H
wnosi cokolwiek **ponad kursy** (kubełki wg bilansu faworyta + test nachylenia).

## 5. Kluczowe decyzje architektoniczne i uzasadnienia

| Decyzja | Uzasadnienie | Konsekwencja |
|---|---|---|
| CSV w `history/` jako źródło prawdy, SQLite wtórna | Render Free kasuje dysk; CSV w repo jest trwałe, przeglądalne, diffowalne | Start aplikacji ładuje historię z repo, potem dociąga świeże wyniki |
| Dziennik i zakłady na osobnej gałęzi `ledger-data` (GitHub API) | Zapis z aplikacji nie może wywoływać redeployu | Gałąź danych oddzielona od kodu; kopia lokalna ma własną `ledger-data-local` |
| Model per liga (nie jeden globalny) | Prosto, szybko, dane z jednego źródła spójne w nazwach drużyn | Brak siły między ligami (stąd ograniczenia Ligi Mistrzów/Europy) |
| Jeden worker gunicorn + wątki | SQLite + blokada odświeżania (`refresh.lock`) | Prostota; modele liczą się w tle, strona pokazuje „Ładowanie…" |
| Źródła wymienne za routerem (`extsource.py`) | CL → football-data.org, EL → TheSportsDB | Nowe źródło = nowy moduł + wpis w routerze |
| Kolumna `kickoff` tylko w bazie, nie w `COLUMNS` | Pliki `history/*.csv` nie mogą zmieniać formatu (hałas w commitach, scalanie z Actions) | Godzina odtwarza się przy każdym odświeżeniu z fixtures/API |
| Wersje `0.x.y` + `CHANGELOG.md` + jeden plik testów na wersję | Śledzenie zmian przy pracy z asystentem w kolejnych rozmowach | Każda zmiana ma wpis i testy |
| Wspólne repo z tenisem (`combo.py`) | Jedna usługa Render Free (750 h/mies.) mieści obie aplikacje | Podział odpowiedzialności w `NOTATKI-WSPOLNE.md` |

## 6. Znane ograniczenia (stan na 0.9.5)

- **Model ≈ rynek, nie lepszy.** W dzienniku log-loss rynku bywa niższy niż modelu (np. D1: rynek 0.832 vs model 0.856;
  E0: 1.025 vs 1.037, próby po 20–25 meczów). Małe próby – wnioski dopiero przy setkach rozliczeń.
- **Rynki połówkowe, kartki, rożne:** brak historycznych kursów → ocena tylko względem średniej ligi.
- **Brak kontuzji i składów** w produkcji: API-Football na darmowym planie nie obejmuje bieżącego sezonu (moduł `avail.py` gotowy, wymaga planu Pro).
- **Liga Mistrzów i Liga Europy** – model tylko z meczów danych rozgrywek, bez siły drużyn z lig krajowych; EL bez połówek/kartek/rożnych (TheSportsDB).
- **Liga Europy nie jest jeszcze aktywna na Renderze** – wymaga wgrania `history/EL_*.csv` (patrz `OPERACJE.md`).
- **Render Free:** usypianie po 15 min bez ruchu (UptimeRobot na `/healthz` to łagodzi), efemeryczny dysk, ~1 min rozruchu.
- **Opóźnienia danych:** CSV football-data.co.uk bywa dni w plecy; szybkie wyniki dla 7 lig z football-data.org (token).
- **H2H:** próbki 3–5 spotkań, tylko historia z kilku sezonów w bazie.

## 7. Kryteria sukcesu (jak ocenić, że to działa)

1. **Kalibracja:** na dużej próbie rozliczeń przewidywane % ≈ częstość zdarzeń (wykres „Trafność rynków" w *Ostatnich*).
2. **Dziennik ≥ kilkaset rozliczeń na rynek** zanim zapadnie jakakolwiek decyzja o „przewadze".
3. **Moje zakłady:** zysk/ROI vs to, co obiecywał model (zysk oczekiwany wg modelu vs faktyczny) – przy kilkuset zakładach.
4. **Operacyjnie:** codzienny workflow zielony, brak ręcznych poprawek danych, strona odpowiada po uśpieniu w ~1 min.
5. **Zaufanie:** zero niespodzianek w liczbach – testy zielone, ostrzeżenia widoczne.
