# Rozdział 1 – podsumowanie i plan na Rozdział 2

Zamknięcie: **10.11.2026**, wersja **0.9.5**. Dokument jest jednocześnie **przekazaniem projektu** do kolejnej rozmowy/etapu.

## 1. Co zostało zbudowane (stan na 0.9.5)

- **Model:** Dixon-Coles + regresje liczników; rynki: 1X2, O/U, BTTS, dokładne wyniki, remisy w połowach (HT, 2H, którakolwiek, HT lub FT), żółte kartki (z efektem sędziego), rożne, DC/DNB/handicapy; Monte Carlo tabeli.
- **Ligi:** E0, D1, F1, I1, N1, P1, SP1 aktywne w repo (`history/`, 2020–2026); CL i EL zaimplementowane, **nieaktywne** (brak plików `history/CL_*`, `EL_*`).
- **Ocena:** backtest walk-forward, `tune`, dziennik na żywo, „Ostatnie" (retrospektywa), testy hipotez (`fatigue-test`, `h2h-test`, `profile`).
- **Aplikacja:** Mecze (kafelki, średnie ligi, kolory, H2H, forma, godzina i status), Podpowiedzi, Zestawienie (żywe AKO, PDF), Ostatnie (wizualne), Dziennik, Moje zakłady, Dane, link do tenisa; eksport PDF (Ostatnie, Dziennik, Zestawienie – wszystkie ligi).
- **Infrastruktura:** Render Free + UptimeRobot, GitHub Actions (daily/weekly/tests), trwały dziennik i zakłady na gałęzi `ledger-data`, kopia lokalna na PC (Tailscale), wspólne repo z tenisem (`combo.py`).
- **Jakość:** ponad 240 testów; CHANGELOG i dokumentacja na bieżąco; dokumenty w `docs/`.

## 2. Historia wersji

| Wersja | Zakres |
|---|---|
| 0.1–0.2 | modele, backtest, kursy i miks z rynkiem, dziennik, aplikacja web, CSV i API-Football |
| 0.3 | historia w CSV jako źródło prawdy (`history/`), codzienna akcja GitHub |
| 0.4 / 0.4.1 | wiele lig, Liga Mistrzów, sędziowie/kartki/rożne; rynki remisowe |
| 0.5 – 0.5.4 | zmęczenie i krótka przerwa, trwały dziennik przez GitHub API, wyniki bez opóźnienia (football-data.org), historia lig i parametry w repo |
| 0.6 – 0.6.5 | Podpowiedzi i Zestawienie; naprawy (brak nadchodzących, workflow, testy); wyróżnienia na stronie Mecze (zielone ramki) |
| 0.7.0 – 0.7.4 | kontuzje/składy (API-Football, opcjonalnie), `avail-probe`, żywe AKO, Ostatnie: remis 2H i „HT lub 2H" |
| 0.8.0 – 0.8.1 | kafelki ze średnią ligi i kolorami, kartki/rożne w kafelkach, H2H i forma, flaga ⚑; wizualne „Ostatnie" |
| 0.9.0 | Moje zakłady (auto-rozliczanie, ROI, trwałość), `h2h-test` |
| 0.9.1 | link „🎾 Tenis", eksport PDF (Ostatnie, Dziennik, Zestawienie) |
| 0.9.2 | godzina startu i status meczu, PDF na górze Zestawienia |
| 0.9.3 – 0.9.5 | Liga Europy z TheSportsDB (kolejka po kolejce, filtr ligi, odporność na limit), `sportsdb-probe` |

(Dokładne wpisy: `CHANGELOG.md`.)

## 3. Najważniejsze ustalenia i lekcje

1. **Rynek ≥ model.** W dzienniku log-loss rynku jest zwykle niższy niż modelu; próby są jednak małe (20–25 meczów na ligę). Wniosek roboczy: model służy do selekcji i kalibracji, nie do „bicia rynku".
2. **Darmowe API mają haczyki:** API-Football free – bez bieżącego sezonu; football-data.org free – bez Ligi Europy; TheSportsDB free – lista sezonu ucięta do 15 zdarzeń (kolejki dają komplet), współdzielony klucz z limitem. **Zawsze weryfikuj źródło komendą-sondą zanim zaczniesz budować.**
3. **Render Free** wymaga: efemerycznego dysku (trwałość na GitHubie), keep-alive i jednego procesu.
4. **Testy muszą być izolowane** od stanu repo i bazy (`PARAMS_DIR`, `HISTORY_DIR`, `DB_PATH`).
5. **Format `history/*.csv` jest kontraktem** (nowe kolumny tylko w bazie, np. `kickoff`).
6. **Wizualna ocena** (kolory względem średniej ligi, zielone/czerwone) jest dla użytkownika cenniejsza niż dodatkowe tabele; interfejs musi działać na 390 px.
7. **Uczciwe ostrzeżenia** (małe próby, H2H słabe, przewaga >15% = błąd) są częścią produktu.

## 4. Otwarte sprawy na starcie Rozdziału 2

| # | Sprawa | Status / następny krok |
|---|---|---|
| 1 | **Liga Europy aktywna na Renderze** | `history-init --league EL --seasons 2025-2026` – sezon 2025 pobrany lokalnie (144 mecze), 2026 wymaga powtórki po limicie; potem commit `history/EL_*.csv` |
| 2 | **Trwałość dziennika/zakładów na Renderze** | potwierdzić `GITHUB_TOKEN` + `GITHUB_REPO` w Render → Environment; w *Dane* linia „Trwałość" ma pokazać wczytane prognozy |
| 3 | **Liga Mistrzów** nieaktywna (brak `history/CL_*`) | `history-init --league CL` (wymaga tokenu football-data.org) |
| 4 | Czyszczenie danych DEMO | `git rm history/DEMO_*.csv`, jeśli jeszcze są |
| 5 | Rozdzielenie gałęzi `ledger-data` (miała pełną kopię kodu) | do decyzji; dotyka tenisa |
| 6 | Wynik `h2h-test` na prawdziwej historii | uruchomić na PC i ocenić flagę ⚑ |
| 7 | Przyczyna rzadkich błędów testów o północy | niepotwierdzona |

## 5. Backlog Rozdziału 2 (propozycje, wg priorytetu)

1. **Kalibracja i widok kalibracji per rynek** (wykres przewidywane vs faktyczne, izotoniczna korekta) – najtańsza droga do realnej poprawy jakości.
2. **Backtest własnej reguły selekcji** na historii (np. „zielone kafelki + kurs ≥ X") – czy reguła użytkownika ma sens.
3. **CLV i porównanie z kursem zamknięcia** w Moich zakładach (wymaga archiwum kursów z `history/odds/`).
4. **Wiele lig w jednym modelu / siła lig** – żeby EL/CL korzystały z historii drużyn z lig krajowych.
5. **Kontuzje i składy** – tylko gdy pojawi się budżet (API-Football Pro 19 USD/mies.) lub inne darmowe źródło z bieżącym sezonem (sprawdzone sondą).
6. **Szybszy start aplikacji** (ładowanie historii w tle), jeśli wybudzanie Rendera nadal będzie problemem.
7. **Kafelki/aliasy dla nowych rynków** (DNB, handicapy) i dalsze usprawnienia Podpowiedzi.
8. **Pomoc w nauce użytkownika:** krótkie „jak czytać" przy kafelkach (rozwijalne), dokumentacja jako zakładka w aplikacji.

## 6. Umowa o pracy (dla kolejnych rozmów z asystentem)

- Język: polski; instrukcje krok po kroku (Windows, PowerShell, VS Code, GitHub Desktop); rzeczy „na telefon" – proste nazwy plików.
- Zacznij od przeczytania `NOTATKI-WSPOLNE.md` i `docs/`; po ważnej zmianie dopisz wpis w dzienniku.
- Pracuj bezpośrednio w repo `safe-n/flask-football-app`: `git pull --rebase` przed każdym pushem, commit na `master`.
- Nie ruszaj plików tenisowych i infrastruktury (`tnpred/`, `combo.py`, `requirements.txt`, `render.yaml`, `lokalnie/`); `openpyxl>=3.1` musi zostać w `requirements.txt`.
- Każda zmiana: testy, wpis w `CHANGELOG.md`, bump wersji, zielone testy przed pushem. Przypomnij użytkownikowi o „Aktualizuj i zrestartuj" na `/restart` po wysłaniu zmian.
- Uczciwość: nie obiecuj przewagi nad rynkiem; zaznaczaj ograniczenia danych i małe próby; sprawdzaj źródła danych sondą przed implementacją.
- Klucze nigdy w czacie/repo.
