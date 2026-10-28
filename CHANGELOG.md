
## 0.7.3 - AKO w Zestawieniu liczy się na żywo

- Zestawienie: panel AKO - kursy, które wpisujesz, mnożą się na bieżąco (także gdy baza nie ma kursów, np. remisy w połowach);
  pokazuje też szansę wszystkich typów wg modelu, uczciwy kurs AKO z prognoz, wartość oczekiwaną oraz wygraną dla stawki
  (stawka zapamiętywana w przeglądarce). Przy typach z tego samego meczu szansa łączna nie jest liczona (brak niezależności).
- Podpowiedzi: „nóg” = jeden typ na kuponie; opis w podpowiedzi pola.

## 0.7.2 - avail-probe nie przerywa się przy błędzie API

- Na stronie Mecz błąd „Free plans do not have access to this season” jest wyjaśniony po polsku (darmowy plan nie obejmuje bieżącego sezonu).
- Każdy krok diagnostyki jest osobno: błąd (np. ograniczenie darmowego planu do części sezonów) jest wypisany w całości
  („BŁĄD w kroku …: …”), a raport idzie dalej. Mecze na najbliższe 7 dni pobierane zakresem dat zamiast parametru `next`.

## 0.7.1 - avail-probe: poprawka błędu i kursy na rynki połówkowe

- `avail-probe` wywracał się na wpisie rynku bez nazwy (`null` z API). Naprawione.
- Probe wypisuje teraz kursy na kluczowe rynki: First Half Winner (id 13, zawiera remis do przerwy), Second Half Winner (id 3),
  HT/FT Double (id 7), Double Chance 1H, BTTS 1H, DNB 1H - żeby sprawdzić, co zwraca konto, zanim zaczniemy zbierać historię kursów.

## 0.7.0 - Kontuzje, zawieszenia i składy (API-Football, opcjonalnie)

- Nowy moduł `fbpred/avail.py` + blok „Dostępność zawodników” na stronie Mecz (gdy podana data i ustawiony `API_KEY`).
  Informacyjnie: NIE zmienia prognozy, wspiera ręczną korektę xG.
- Oszczędność limitu: kontuzje = 1 zapytanie na ligę i dzień (cache 3 h, wspólne dla meczów), dopasowanie meczu = 1 zapytanie
  na ligę i dzień, składy = 1 zapytanie na mecz i tylko na kliknięcie. Dzienny limit własny `AVAIL_DAILY_CAP` (domyślnie 40).
- `python -m fbpred avail-probe --league I1`: sprawdza klucz i wypisuje, jakie rynki kursów (m.in. połówkowe) oraz kontuzje
  zwraca konto - do dalszej rozbudowy (zbieranie kursów na remisy w połowach).
- `ApiClient.cached()`; testy: `tests/test_v66.py` (na podstawionych odpowiedziach - API nie było testowane na żywo).

## 0.6.5 - Wyróżnienia na stronie Mecze

- Zielona ramka także przy BTTS i remisach (HT, 2H, HT lub 2H, HT lub FT, FT), gdy wartość jest co najmniej 8 pp powyżej
  ŚREDNIEJ LIGI (ostatnie 3 sezony) dla danego rynku - próg względem bazy, bo np. „HT lub 2H” zdarza się w ok. 64% meczów.
  Zmiana progu: `?hl=6`. Najechanie na pole pokazuje średnią ligi; pod listą jest legenda.

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
