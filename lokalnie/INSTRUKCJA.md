# Piłka + tenis na Twoim komputerze (kopia lokalna)

Szybsza kopia aplikacji na laptopie. Render zostaje bez zmian jako zapas, gdy laptop jest wyłączony.
Kopia lokalna ma **osobną bazę i osobny zapis** (gałąź `ledger-data-local`), więc nie nadpisze zakładów ani dziennika z Rendera.

## 1. Uruchomienie (pierwszy raz)
1. GitHub Desktop → **Fetch origin** → **Pull origin** (żeby mieć folder `lokalnie`).
2. W pliku `.env` w folderze repo powinny być klucze (ten sam plik, którego używa `aktualizuj_tenis.bat`):
   `ODDS_API_KEY=…` (tenis – mecze z kursami) oraz klucze piłki, jeśli ich używasz (`FOOTBALL_DATA_ORG_TOKEN`, `API_KEY`…).
   Wartości skopiujesz z Render → Environment (kliknij wartość, żeby ją odkryć).
3. Dwuklik **`lokalnie\uruchom_aplikacje.bat`**. Otworzy się czarne okno – **nie zamykaj go** (zamknięcie = wyłączenie aplikacji).
   Jeśli Windows zapyta o zaporę dla Pythona – zaznacz **sieci prywatne** i kliknij Zezwól.
4. W przeglądarce: **http://localhost:5000** (piłka) i **http://localhost:5000/tennis/** (tenis).
   Pierwszy start trwa ok. minuty (pobieranie danych, liczenie modelu).

## 2. Autostart
Dwuklik **`lokalnie\autostart_wlacz.bat`** – aplikacja sama wystartuje (zminimalizowana) po zalogowaniu do Windows.
Wyłączenie: `autostart_wylacz.bat`.
W Claude Desktop możesz też włączyć „Keep computer awake”; zamknięcie klapy laptopa i tak go usypia
(Panel sterowania → Opcje zasilania → „Wybierz działanie po zamknięciu pokrywy” → „Nic nie rób” przy zasilaniu z sieci).

## 2a. Aktualizacja kodu i restart – jednym przyciskiem
Przy każdym starcie `uruchom_aplikacje.bat` sam pobiera najnowszy kod z GitHuba (git wbudowany w GitHub Desktop) i doinstalowuje
biblioteki. Po zmianach wysłanych przez Claude nie trzeba więc klikać Pull ani zamykać okna:
otwórz **`http://localhost:5000/restart`** (z telefonu: `http://NAZWA-KOMPUTERA:5000/restart`, link jest też w tenis → Dane)
i kliknij **„🔄 Aktualizuj i zrestartuj”**. Po ok. minucie strona wróci sama. Na Renderze ten przycisk jest wyłączony
(Render aktualizuje się sam). Jeśli w oknie pojawi się „Nie udało się pobrać zmian”, w folderze są zmienione pliki –
sprawdź zakładkę Changes w GitHub Desktop.

## 3. Dostęp z telefonu (Tailscale, bezpłatnie)
1. Laptop: zainstaluj Tailscale z **tailscale.com/download**, zaloguj się (np. kontem Google).
2. Telefon: aplikacja **Tailscale** ze sklepu, zaloguj się **tym samym kontem**, włącz połączenie.
3. W aplikacji Tailscale na telefonie zobaczysz nazwę laptopa (np. `laptop-pnisz`). Otwórz w przeglądarce telefonu:
   **http://NAZWA-LAPTOPA:5000/tennis/** (albo adres 100.x.x.x widoczny w Tailscale).
Aplikacja nie jest wystawiona do internetu – widzą ją tylko Twoje urządzenia w Tailscale (i domowe Wi-Fi).

## Gdy coś nie działa
- Okno pokazało błąd i się zamknęło → zrób zdjęcie, wyślij.
- Telefon nie łączy się, a na laptopie działa → zapora Windows: Ustawienia → Zapora → Zezwalaj aplikacji → Python → zaznacz „Prywatne”.
