# Wzorzec: aktywne kafelki → Moje typy → kupony

Opis funkcji wdrożonej w tenisie (tnpred 0.3.12–0.3.13), spisany tak, żeby wątek piłki mógł zrobić analogiczną zmianę w `fbpred/`.
Kod wzorcowy: `tnpred/picks.py`, `tnpred/templates/picks.html`, `tnpred/views.py` (`tile`, `tile_specs`, `tiles_for`),
`tnpred/web.py` (`/api/picks`, `/picks`, `/picks/confirm`, `/picks/<id>/<akcja>`), JS i CSS w `tnpred/templates/base.html`,
testy `PicksTests` i `CouponTests` w `tests/test_tn010.py`.

## 1. Po co (słowami użytkownika)
Użytkownik chce kliknąć kafelek z procentem przy meczu i mieć ten typ zapisany. Po meczu typ ma się sam rozliczyć: zielony = wszedł,
czerwony = nie wszedł. Ze swoich typów składa kupon i zatwierdza go „na sztywno”, nawet bez kursów. Gdy kursy są wpisane, kupon jest AKO.
Na tej podstawie sprawdza własną skuteczność: typuje głównie wysokie procenty, czasem underdogi z przeczucia.
Zestawienie ma się dać wydrukować.

To NIE zastępuje „Moich zakładów” (stawki, zysk w zł). „Moje typy” to dziennik trafności bez pieniędzy, z opcjonalnym kursem.

## 2. Przepływ dla użytkownika
1. **Mecze**: każdy kafelek z procentem (w tenisie: zwycięzca ×2, Over linii, Tie-break, bez straty seta) jest klikalny.
   - Pierwsze kliknięcie zapisuje typ: kafelek dostaje niebieską ramkę i ✓ w rogu.
   - Drugie kliknięcie usuwa typ, ale tylko dopóki nie jest zatwierdzony.
   - Zaznaczenie przetrwa odświeżenie strony, bo serwer zna zapisane typy.
2. **Moje typy → Szkic kuponu**:
   - Szkic to typy kliknięte od ostatniego zatwierdzenia. Przy każdym typie widać szansę modelu, odniesienie (rynek albo średnią) i pole kursu.
   - Pod spodem: szansa wszystkich typów naraz (iloczyn), uczciwy kurs i kurs AKO, gdy każdy typ ma kurs.
   - Przycisk „✅ Zatwierdź kupon” (z opcjonalną notatką) zamyka szkic. Kolejne kliknięcia tworzą nowy szkic.
3. **Kupony** (zatwierdzone, najnowsze pierwsze):
   - Każdy kupon ma numer, datę, typ (AKO / Pojedynczy / „bez kursów”), status, zysk przy stawce 1 j. (gdy jest kurs) i listę typów z kolorem wyniku.
   - Zatwierdzonego typu nie można usunąć ani zmienić mu kursu (HTTP 409 / komunikat). Można tylko ręcznie poprawić wynik (⋯), gdy źródło danych się pomyli.
4. **Zestawienie skuteczności** (patrz pkt 5) oraz filtry 30/90 dni i ATP/WTA. „🖨 Drukuj / PDF” wywołuje `window.print()`; style `@media print` dają białe tło i ukrywają nawigację, przyciski i formularze.

## 3. Dane
- **Tabela `picks`**: `id, created_at, leg (UNIQUE), tour, date, p1, p2, key, label, grp, p, ref, kurs, status, settled_at, coupon`.
  - `leg` to ten sam identyfikator co w kuponie zakładów (`tour~data~zawodnik1~zawodnik2~nawierzchnia~sety~klucz`), dzięki czemu działa istniejące rozliczanie `betmarkets.leg_won`.
  - `p` i `ref` to szansa modelu i punkt odniesienia z CHWILI kliknięcia, liczone po stronie serwera, a nie przysłane z przeglądarki.
  - `kurs` jest brany z bazy (`book_odds`), jeśli jest; w szkicu można go wpisać lub poprawić.
  - `status`: `open` / `hit` / `miss` / `void`.
  - `coupon` = NULL oznacza typ w szkicu.
- **Tabela `coupons`**: `id, created_at, note`. Status, kurs AKO, szansę i zysk kuponu liczymy z typów (nic się nie rozjeżdża):
  - dowolny `miss` → kupon „nie wszedł”,
  - dowolny `open` → „w grze”,
  - wszystkie `void` → „zwrot”,
  - w pozostałych przypadkach → „wszedł”.
  - Typy `void` wypadają z kursu AKO i z iloczynu szans.
- **Migracja**: `ensure()` dodaje kolumnę `coupon` przez `ALTER TABLE`, gdy jej brak. Stare typy lądują w szkicu; import starego CSV bez kolumny działa.
- **Zapis trwały**: `picks.csv` i `coupons.csv` w gałęzi dziennika (`gh_store.FILES`, `bootstrap.sync_up/sync_down`, `INSERT OR IGNORE`), dokładnie jak `bets.csv`.
  - Zapis idzie w tle (`sync_up_bg`) po każdej zmianie.
  - PC (`ledger-data-local`) i Render (`ledger-data`) mają osobne dzienniki; to celowe i takie samo jak przy zakładach.

## 4. Rozliczanie
`picks.settle_open(conn, st.lookup)` jest wołane w `bootstrap.refresh` obok `bets.settle_open`. Dla każdego otwartego typu:
`leg_won(key, oriented(wynik, zawodnik1))` → True = `hit`, False = `miss`, `"void"` (krecz/walkower) = `void`, None = czekamy.
W tenisie wynik zwykle jest tego samego dnia dzięki łatce ESPN; w piłce wystarczy źródło, z którego już rozlicza się „Moje zakłady”.

## 5. Jak oceniamy skuteczność (najważniejsza decyzja)
Sam kolor wszedł/nie wszedł myli: typ 80% powinien wchodzić często, a underdog 30% rzadko. Dlatego zestawienie pokazuje:
- **trafione vs oczekiwane**: oczekiwane = średnia z klikniętych procentów. Różnica w pp to „Ty vs procenty modelu”;
- osobno **wg rodzaju typu**: faworyt (p ≥ 50%) / underdog / over / under / TB / bez straty seta;
- osobno **wg przedziału szansy**: <35, 35–50, 50–65, 65–80, ≥80%, czyli kalibracja własnej selekcji;
- **zysk przy stawce 1 j.** tylko dla typów i kuponów z kursem; u underdogów liczy się bardziej niż skuteczność;
- **Brier** (średni kwadrat błędu szansy; 0.25 = rzut monetą przy 50%);
- **pasek ✓/✗** z ostatnich 60 rozliczonych typów;
- kupony osobno: wygrane / rozliczone, oczekiwane (średni iloczyn szans), zysk 1 j.

Zawsze dopisany komentarz o małej próbie: do ok. 100 typów ±10 pp to zwykle przypadek, a AKO wchodzi rzadko.

## 6. Szczegóły techniczne warte skopiowania
- Kafelek: `<div class="b … pk [on]" data-pick="{leg}" role="button" tabindex="0">`.
  - JS (`pkToggle`) robi `POST /api/picks {leg}` i przełącza klasę `on`; obsługuje też Enter i spację.
  - Błąd 409 (zatwierdzony typ) pokazuje `alert` z komunikatem.
  - Na czas zapytania kafelek dostaje klasę `busy`, żeby podwójne kliknięcie nie dodało i od razu nie usunęło typu.
- Serwer sam liczy `p`, `ref` i etykietę z tej samej funkcji, która rysuje kafelki (`tile_specs`), więc procent zapisany = procent widziany.
- Linia over jest w kluczu (`o22.5`), żeby typ rozliczał się względem linii widzianej przy kliknięciu.
- Widok na telefonie: tabela z 4 kolumnami (mecz·typ / szansa / kurs / wynik), akcje schowane pod `<details>⋯</details>`; brak poziomego przewijania przy 400 px.
- Nowy rynek w tenisie: `str` (zwycięzca bez straty seta). W piłce odpowiedniki kafelków to np. 1/X/2, Over 2.5, BTTS; trzeba się upewnić, że `leg_won` fbpred zna każdy klucz kafelka.

## 7. Lista kontrolna dla wątku piłki
1. `fbpred/picks.py`: skopiować moduł i podmienić `kind()` na rodzaje piłkarskie (np. faworyt/underdog 1X2, remis, over/under, BTTS).
2. W `views`/`web` piłki wydzielić `tile_specs(pred)` (klucz, etykieta, p, ref) i użyć go do rysowania kafelków oraz w `/api/picks`.
3. Trasy: `/api/picks` (toggle; 409 dla zatwierdzonych), `/picks`, `/picks/confirm`, `/picks/<id>/<hit|miss|void|open|kurs|delete>`; pozycja „Moje typy” w nawigacji.
4. Szablon `picks.html` i style `.pk`, `.pt`, `.cp`, `@media print` z `tnpred/templates/base.html`.
5. `settle_open` w odświeżaniu, `picks`/`coupons` w `gh_store.FILES` oraz w sync up/down.
6. Testy: przełączanie kafelka, rozliczenie każdego klucza, kupon AKO i bez kursów, blokada po zatwierdzeniu, migracja, eksport/import.
7. Nie mieszać plików z tenisem: piłka ma własne `picks.csv`/`coupons.csv` w swoim folderze dziennika (prefiks gałęzi).
