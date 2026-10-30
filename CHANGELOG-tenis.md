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
