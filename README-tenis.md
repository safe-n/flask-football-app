# Tenis (tnpred) – instrukcja

Aplikacja tenisowa działa w tej samej usłudze Render co piłka, pod adresem `/tennis/` (plik `combo.py`).
Model ≈ rynek: to narzędzie do selekcji i oceny, nie „pewniaki”.

## Codzienna aktualizacja wyników (raz skonfigurować)

tennis-data.co.uk nie wpuszcza serwerów (Render, GitHub), więc wyniki pobiera Twój komputer i wysyła je do GitHuba.
Aplikacja sprawdza je co ok. 3 h. Bez Commit/Push i bez przebudowy Rendera.
Przy nowych wynikach komputer liczy też **styl zawodników** (tie-breaki ponad siłę i nawierzchnię, na razie ATP) i wysyła
`style.json`; ręcznie: `python -m tnpred style` (podgląd: `python -m tnpred style --show`).

1. **Token GitHub** (jednorazowo): github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens →
   Generate new token. Repository access: *Only select repositories* → `flask-football-app`.
   Permissions → Repository permissions → **Contents: Read and write**. Generate i skopiuj token.
2. **Plik `.env`** w folderze `C:\GitHub\flask-football-app` (Notatnik → Zapisz jako → nazwa `.env`, typ „Wszystkie pliki”).
   Jeśli plik już jest (piłka), dopisz na końcu:
   ```
   GITHUB_TOKEN=tu_wklej_token
   GITHUB_REPO=safe-n/flask-football-app
   ```
   Plik `.env` nie trafia do repo (jest w .gitignore) – token zostaje tylko na Twoim komputerze.
3. **Test**: dwuklik `aktualizuj_tenis.bat`. Powinno pokazać „wysłano … meczów” albo „bez zmian”.
4. **Automat**: w PowerShell (VS Code), w folderze repo:
   ```
   python -m tnpred install-task
   ```
   Od teraz Windows uruchamia aktualizację co 4 h, gdy komputer jest włączony. Dziennik: `tennis_update.log`.
   Usunięcie: `python -m tnpred install-task --remove`.

Uwaga: sama strona tennis-data nie zawsze aktualizuje pliki codziennie – zadanie wyśle nowe wyniki, gdy tylko się pojawią.

Od 0.3.11 lukę wypełnia darmowy feed ESPN (bez klucza): wyniki z ostatnich dni trafiają do modelu od razu i są zastępowane danymi tennis-data po ich publikacji, a mecze turniejów, których nie zna The Odds API (np. ATP 250, Finals), pojawiają się w zakładce Mecze bez kursów („terminarz ESPN”). Feed jest nieoficjalny – gdy przestanie działać, aplikacja wraca do samych tennis-data i The Odds API (błąd widać w Dane). Wyłączenie: `TN_ESPN=0`.

## Pozostałe

- Godziny i status meczów, eksport PDF (Mecze → 📄 Eksport PDF), zakłady, dziennik, backtest – opis w `CHANGELOG-tenis.md`.
- Pamięć Render: zalecana zmienna `MALLOC_ARENA_MAX=2` (Render → Environment).
- Nadchodzące mecze z kursami: zmienna `ODDS_API_KEY` (darmowy klucz z the-odds-api.com) albo ręcznie w zakładce Mecze.


## Moje typy i kupony (od 0.3.12)
Kliknij kafelek z procentem w zakładce Mecze - typ trafi do szkicu kuponu w zakładce „Moje typy”. „Zatwierdź kupon” zapisuje go na stałe
(kursy opcjonalne; gdy są przy każdym typie - AKO). Po meczu typy rozliczają się same (zielony = wszedł, czerwony = nie wszedł), a zestawienie
porównuje Twoją skuteczność z procentami modelu (wg rodzaju typu i przedziału szansy). Wydruk / PDF: przycisk w zakładce. Opis wzorca: `docs/WZORZEC-MOJE-TYPY.md`.
