
## 0.6.4 - Zestawienie, odznaczanie typów, pełna lista przy wielu rynkach

- **Zestawienie wisiało na „Ładowanie…”:** funkcje koszyka (`fbLoad`…) były w `base.html` pod treścią strony, więc skrypt Zestawienia
  kończył się błędem `ReferenceError`. Skrypt jest teraz w `<head>`. Test: `tests/test_v64.py`, sprawdzone w przeglądarce (Playwright).
- **Odznaczanie:** przycisk „＋” przełącza się na „✓” i kliknięcie usuwa typ z zestawienia; „Dodaj wszystkie” też działa w obie strony.
  Stan przycisków synchronizuje się po powrocie na stronę.
- **Podpowiedzi przy wielu rynkach** (np. Remisy + Gole + Kartki + Rożne): puste pola „Ile wyników” i „Typów z meczu” = tryb auto
  (wiele rynków: do 300 wyników i do 12 typów z meczu, przy jednym rynku jak dotąd 20 i 1). Nowe sortowanie „po meczu”.

## 0.6.3 - Testy niezależne od historii w repo

- `test_empty_db_then_loaded` padał na GitHubie (`200 != 503`): `create_app()` wczytuje `history/` od razu, a w repo są już prawdziwe
  dane, więc baza nie była pusta. Testy mają teraz własny, pusty katalog historii (`tests/__init__.py`). Zmiana tylko w testach.

## 0.6.2 - Naprawa workflow GitHub Actions (zapis do repo)

- `daily`, `weekly`, `init-history`: krok „Zapisz zmiany w repo” padał z `cannot pull with rebase: You have unstaged changes`
  (np. `ledger/REPORT.md` poza `git add`). Teraz: commit, potem `git pull --rebase --autostash` i `git push` z 3 próbami.
  (Poprawkę znalazł użytkownik: skutek - dziennik zaczął się zapisywać do repo.)

## 0.6.1 - Brak nadchodzących meczów mimo świeżego terminarza

- **Przyczyna:** `fixtures.csv` (football-data.co.uk) bywa nieaktualny - zawierał mecze tylko do 25.10. Zapasowe źródło
  (football-data.org) uruchamiało się wyłącznie przy *pustym* pliku, więc przy pliku „starym, ale niepustym" terminarz się nie uzupełniał.
- **Poprawka:** przy ustawionym `FOOTBALL_DATA_ORG_TOKEN` terminarz jest ZAWSZE uzupełniany o przyszłe mecze, których brakuje w bazie
  (bez duplikatów, mecze z fixtures.csv z kursami zostają nietknięte; nowe są bez kursów). Dane -> strona *Dane*: kroki `fixtures_csv`
  ("N meczów, w tym K od dziś - plik jest nieaktualny") i `football-data.org` ("dodano N nadchodzących...").
- **Ostatnie:** wyniki z CSV pojawiają się z opóźnieniem źródła; szybkie wyniki (`wyniki_szybkie`) działają tylko z tokenem.
- **Wiele procesów:** diagnostyka zapisywana do pliku (`diag.json`), odświeżanie pod blokadą plikową (jeden proces naraz).
- **Lista lig:** deduplikacja i czyszczenie kodów lig; strona *Dane* pokazuje kontrolę integralności bazy.
- Testy: `tests/test_v61.py`.
