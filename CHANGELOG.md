
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
