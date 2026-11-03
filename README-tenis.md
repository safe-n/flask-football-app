# Tenis (tnpred) – instrukcja

Aplikacja tenisowa działa w tej samej usłudze Render co piłka, pod adresem `/tennis/` (plik `combo.py`).
Model ≈ rynek: to narzędzie do selekcji i oceny, nie „pewniaki”.

## Codzienna aktualizacja wyników (raz skonfigurować)

tennis-data.co.uk nie wpuszcza serwerów (Render, GitHub), więc wyniki pobiera Twój komputer i wysyła je do GitHuba.
Aplikacja sprawdza je co ok. 3 h. Bez Commit/Push i bez przebudowy Rendera.

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

## Pozostałe

- Godziny i status meczów, eksport PDF (Mecze → 📄 Eksport PDF), zakłady, dziennik, backtest – opis w `CHANGELOG-tenis.md`.
- Pamięć Render: zalecana zmienna `MALLOC_ARENA_MAX=2` (Render → Environment).
- Nadchodzące mecze z kursami: zmienna `ODDS_API_KEY` (darmowy klucz z the-odds-api.com) albo ręcznie w zakładce Mecze.
