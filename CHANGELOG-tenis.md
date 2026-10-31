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
