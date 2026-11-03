## 0.3.5 - szybkie ładowanie strony Mecze
- „Forma dnia” (0.3.0) spowolniła liczenie meczu ok. 10×: przy kilkudziesięciu meczach z kursami strona Mecze na Renderze
  liczyła się ponad minutę i nie ładowała się. Teraz: tablica szansa→serwis liczona raz na tour+nawierzchnię (interpolacja
  zamiast szukania dla każdego meczu), H2H i forma z indeksu zawodników zamiast przeszukiwania 25 tys. meczów.
- Pomiar (120 meczów, Twoje dane): strona Mecze 0,08 s (wcześniej kilka s lokalnie ≈ minuta na Renderze); pierwsze wejście
  po restarcie przygotowywane w tle.

## 0.3.4 - odporność na błędną wartość GITHUB_REPO
- Render: GITHUB_REPO zawierał enter i dopisek („safe-n/flask-football-app⏎2”) - GitHub odpowiadał 404, przez co dziennik,
  zakłady i wyniki z GitHuba nigdy się nie zapisywały/wczytywały. Tenis bierze teraz tylko pierwsze słowo zmiennej
  i ostrzega w Dane, że wartość warto poprawić (piłka korzysta z tej samej zmiennej).

## 0.3.3 - mecze z kursami nie czekają na GitHuba; wątek tła widoczny w Dane
- Na Renderze wątek w tle nie zapisywał żadnego kroku (od początku): stał albo kończył się błędem bez śladu - a kursy
  The Odds API pobierały się dopiero na końcu, więc znikały mecze. Teraz kursy idą PIERWSZE, każdy błąd wątku trafia
  do tabeli w Dane („wątek tła: …”), a gdy brak postępu - Dane pokazują, w którym miejscu kodu wątek stoi.

## 0.3.2 - wersja na górze strony + sprawdzanie tokenu GitHub
- Na górze każdej strony: „tenis vX.Y.Z · commit abc1234 · start dd.mm hh:mm” - widać, która wersja jest wgrana i kiedy serwer wystartował.
- Zakładka Dane: krok „GitHub: token” mówi wprost, czy token widzi repo i może do niego pisać (bez tego dziennik, zakłady
  i codzienne wyniki nie działają).

## 0.3.1 - codzienna aktualizacja wyników bez Commit/Push
- `python -m tnpred push-history` (albo dwuklik `aktualizuj_tenis.bat`): pobiera bieżący rok z tennis-data.co.uk na Twoim
  komputerze i wysyła go prosto do GitHuba (gałąź ledger-data, folder tennis/history) razem z parametrami modelu.
  Nie zmienia plików w folderze repo i nie przebudowuje Rendera. Wysyła tylko to, co się zmieniło.
- `python -m tnpred install-task`: zadanie w Harmonogramie zadań Windows - aktualizacja co 4 h, gdy komputer jest włączony
  (`--every 6` zmienia odstęp, `--remove` usuwa). Dziennik: tennis_update.log.
- Aplikacja sprawdza nowe wyniki w GitHubie co 3 h (TN_REFRESH_HOURS) i od razu po „Odśwież teraz”; pobiera tylko zmienione pliki.
- Zakładka Dane: ostrzeżenie, gdy dane mają ponad 3 dni.

## 0.3.0 - model gemów skalibrowany na prawdziwych danych („forma dnia”)
- BŁĄD wykryty backtestem na historii 2022-26: model przewidywał 25,6 gema na mecz (realnie 24,3), over 22.5 w 52% meczów
  (realnie 43%) i 53% meczów bez straty seta (realnie 62%). Kafelki „Over” i „Tie-break” były więc prawie zawsze zielone,
  a „2:0” czerwone - to był błąd modelu, nie sygnał.
- Przyczyna: założenie, że każdy punkt jest „taki sam”. Dodana forma dnia (losowa przewaga zawodnika w danym meczu,
  sigma dobierana na historii) - mecze stają się bardziej jednostronne tak jak w rzeczywistości.
- Strojenie dobiera teraz razem serwis bazowy i formę dnia (tour + nawierzchnia) pod 4 wskaźniki: tie-break i gemy w 1. secie,
  mecze bez straty seta, średnia gemów. Parametry znowu realistyczne (ATP 0,64-0,66, WTA 0,56-0,60; wcześniej WTA 0,45-0,51).
- Backtest (ostatni rok, 4900 meczów): średnia gemów 24,2 vs 24,3; over 22.5: 42,5% vs 43,2%; tie-break 34% vs 33%;
  bez straty seta 63% vs 62%. Over i tie-break lepsze od samej średniej (Brier 0,241 vs 0,245 oraz 0,210 vs 0,222).
  Uwaga: parametry strojone na ostatnich 3 latach, które obejmują ten rok - wynik lekko optymistyczny.
- Zwycięzca: samo Elo jest wyraźnie słabsze od kursów Pinnacle (log-loss 0,628 vs 0,587), więc waga modelu = 0 i przy zwycięzcy
  aplikacja w praktyce pokazuje rynek. Uczciwy wynik, nie błąd.
- Strojenie trwa ok. 1 min (u Ciebie w aktualizuj_tenis.bat). Backtest w aplikacji: ostatnie 400 meczów.

## 0.2.2 - poprawne parametry WTA + odświeżanie, które nie wisi
- BŁĄD: dobieranie serwisu bazowego (s0) potrafiło zjechać poniżej 0,5 (WTA mączka 0,45, hard 0,51) - zawyżało to przełamania
  i psuło gemy/tie-breaki WTA. Teraz siatka 0,50-0,72 dopasowuje jednocześnie częstość tie-breaka i średnią liczbę gemów
  w 1. secie; wynik na brzegu siatki = wartość domyślna. Na danych testowych odtwarza prawdziwe wartości (±0,02), 2× szybciej.
- Odświeżanie na Renderze: krótsze limity czasu połączeń, po „403” od tennis-data.co.uk przerywa i nie próbuje przez 24 h
  (strona blokuje serwery - nowe wyniki tylko z Twojego komputera). Postęp każdego kroku widać w zakładce Dane.
- Dane: data ostatniego meczu w bazie + przypomnienie o aktualizacji, gdy dane mają ponad tydzień; przy długim odświeżaniu
  pokazuje, w którym miejscu stoi (diagnostyka).
- `aktualizuj_tenis.bat`: dwuklik = pobranie bieżącego roku + strojenie modelu (potem Commit + Push).

## 0.2.1 - godziny rozpoczęcia i status meczu
- Mecze: godzina startu w czasie polskim (TN_TZ), sortowanie po godzinie, dni po polsku („sob 31.10.2026”).
- Status: „za X min” / „▶ rozpoczęty” / „zakończony?” (wg planu; TN_MATCH_HOURS = 4 h) + ostrzeżenie, że kursy są sprzed meczu.
- Ręczne dodawanie meczu: pole „Godzina” (czas polski, opcjonalne).
- The Odds API: po starcie meczu nie nadpisujemy kursów przedmeczowych kursami na żywo (te psułyby przewagę i dziennik).
- Eksport PDF: godzina i status przy każdym meczu.
- Lista meczów odświeża się od razu po nowych kursach/meczach (wcześniej do 10 min opóźnienia).

## 0.2.0 - eksport PDF + mniej pamięci
- Mecze -> „📄 Eksport PDF”: zwięzła wersja do druku (A4) - zwycięzca z uczciwym kursem, kursem i przewagą, gemy (over, średnia),
  tie-break, najczęstszy wynik w setach, H2H i forma W/P, ostrzeżenia. PDF zapisuje przeglądarka („Zapisz jako PDF”) - zero
  obciążenia serwera. Filtr touru i dnia (`?day=RRRR-MM-DD`).
- Pamięć (mail z Rendera „exceeded its memory limit”): dane modelu jako kategorie/float32, indeks wyników bez kopii wierszy,
  historia Elo ograniczona do 120 ostatnich ocen, mniejsze bufory modelu punktowego, czyszczenie bufora stron po zmianie danych,
  oddawanie pamięci systemowi po przebudowie. Dodatek tenisa w szczycie: ok. 130 MB -> ok. 55 MB (pomiar na 18 tys. meczów).
- Krótkie nazwiska wielowyrazowe („De Vries”, nie „De”).

## 0.1.4 - stabilność na darmowym Renderze (HTTP 503)
- Przyczyna 503: przy pierwszym starcie aplikacja stroiła model na serwerze (minuty CPU przy 0,1 CPU) i trzymała w pamięci
  ogromny cache rozkładów meczów - razem z piłką przekraczało to limity Rendera (512 MB), proces był restartowany.
- Cache rozkładów zmniejszony (ok. 190 MB -> ok. 15 MB przy strojeniu/backteście).
- Backtest w aplikacji liczy ostatnie 600 meczów (pełny: python -m tnpred backtest u siebie).
- Strojenie na Renderze domyślnie wyłączone (TN_AUTOTUNE=1 włącza). `python -m tnpred fetch-history` u Ciebie pobiera dane
  i od razu stroi model -> tennis_params/model.json trafia do repo razem z historią.

## 0.1.3 - nowe adresy plików tennis-data.co.uk
- Strona zmieniła adresy plików (https, bez www, dodatkowy człon w ścieżce) - stąd „HTTP 404”. Nowy wzór domyślny,
  a gdy strona znów go zmieni, aplikacja sama odczyta aktualne linki ze strony alldata.php.
- Usunięte zapasowe źródło Sackmann (autor skasował repozytoria we wrześniu 2026).
- `fetch-history` wyjaśnia różnicę: 403 = blokada serwera (uruchom w domu), 404 = zmieniony adres.

## 0.1.2 - historia ręcznie + zapasowe źródło
- tennis-data.co.uk odpowiada serwerom GitHuba „403” (blokada, nie błąd kodu). Aplikacja czyta teraz pliki XLSX pobrane ręcznie
  w przeglądarce: `tennis_history/ATP/*.xlsx` i `tennis_history/WTA/*.xlsx` (nazwy plików dowolne).
- Zapasowe źródło wyników: GitHub JeffSackmann (bez kursów), używane tylko dla lat bez danych.
- Workflow tennis-weekly nie kończy się błędem, gdy historia jest w repo; stroi model na tym, co ma.
- Zakładka Dane: które pliki wczytano i skąd pochodzi każdy rok; brak nowszych danych przy istniejącej historii = ostrzeżenie, nie błąd.

## 0.1.1 - workflow tennis-weekly odporniejszy
- Workflow instaluje openpyxl jawnie (bez niego pobieranie XLSX z tennis-data.co.uk kończyło się błędem) i ma nowsze akcje (bez ostrzeżenia o Node 20).
- `fetch-history`: czytelne podsumowanie i podpowiedź przyczyny; brak openpyxl zgłaszany wprost (też w zakładce Dane).
- Pobieranie z przeglądarkowym nagłówkiem User-Agent (część serwerów odrzuca „boty”).
- Brak bieżącego roku lub backtestu nie przerywa już całego workflow.

## 0.1.0 - pierwsza wersja tenisowa
- Model: Elo ogólne + nawierzchnia (walk-forward), mieszanka z rynkiem (waga z historii), łańcuch punkt → gem → set → mecz
  (dokładny, z Bo5 i tie-breakiem do 10 w decydującym secie Szlema). Rynki: zwycięzca, wynik w setach, over/under i handicap gemów,
  tie-break, 1. set, „co najmniej set”.
- Dane: tennis-data.co.uk (ATP+WTA, wyniki i kursy), The Odds API (opcjonalnie, nadchodzące mecze), ręczne dodawanie meczów.
  Dopasowanie nazw „Jannik Sinner” ↔ „Sinner J.”.
- Zakładki jak w fbpred: Mecze (kafelki ze średnią nawierzchni / rynkiem, H2H i forma W/P, flaga ⚑), Mecz (wszystkie rynki,
  rozkład gemów, forma na nawierzchni, zmęczenie), Podpowiedzi, Zestawienie (AKO), Ranking Elo, Zawodnik, Ostatnie (wersja wizualna),
  Backtest, Dziennik, Moje zakłady, Dane.
- Zapis trwały w gałęzi ledger-data, folder `tennis/` (prognozy, zakłady, ręczne mecze).
- `combo.py`: tenis pod `/tennis` w tej samej usłudze Render co football (jeden limit godzin, jeden UptimeRobot).
- Workflow `tennis-weekly` (historia + strojenie), testy `tests/test_tn010.py`.
