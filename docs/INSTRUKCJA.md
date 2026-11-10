# Instrukcja użytkownika – football-predictor

Aplikacja: `https://flask-football-app.onrender.com` (Render) lub kopia lokalna `http://localhost:5000` / przez Tailscale z telefonu.
Menu u góry: **Mecze · Mecz · Podpowiedzi · Zestawienie · Remisy · Statystyki · Tabela · Siła · Ostatnie · Dziennik · Moje zakłady · Dane · 🎾 Tenis**.
Wybór ligi – lista lig pod menu. Po uśpieniu serwera (Render Free) pierwsze wejście trwa ok. minuty („Ładowanie danych").

## 1. Mecze (strona główna)

Dla każdego nadchodzącego meczu – karta z:
- **Godziną i statusem:** „pt 06.11 20:45", plakietka „za 45 min" / „▶ rozpoczęty" / „zakończony?"; mecze pogrupowane po dniach.
- **Paskiem 1X2** (zielony – gospodarz, szary – remis, czerwony – gość) i **kafelkami**: O2.5, BTTS, remis HT, remis 2H, „HT lub 2H",
  „HT lub FT", remis FT, żółte (O3.5 i średnia), rożne (O9.5 i średnia).
- Każdy kafelek pokazuje **wartość modelu**, pod nią **średnią ligi** i różnicę w nawiasie, np. `liga 49% (+3)`.
  **Kolor tekstu:** zielony = powyżej średniej ligi, czerwony = poniżej; **ramka** = wyraźne odchylenie (próg domyślnie 8 pp, zmienisz `?hl=…`).
- **H2H:** do 5 ostatnich spotkań (najnowsze z lewej, wynik z perspektywy gospodarza, tooltip z prawdziwym meczem) + bilans „xW yR zP".
  **Forma:** kółka W/R/P gospodarza (ogółem i u siebie) oraz gościa (ogółem i na wyjeździe).
- **⚑ H2H:** ostrzeżenie, gdy faworyt (≥45%) wygrał ≤20% z ≥3 ostatnich spotkań z tym rywalem. To sygnał do oceny, nie przewaga – model się nie zmienia.
- **Przyciski „+ typ (kurs, przewaga)"** dodają typ do Zestawienia (ponowne kliknięcie odznacza).

Liczby w kafelkach to **prognozy modelu**, nie pewniaki. Przewaga > 15% nad kursem to zwykle błąd modelu, nie okazja.

## 2. Podpowiedzi

Automatyczne wybieranie typów z całej listy meczów:
- wybierasz rynek(ki), przedział prawdopodobieństwa, liczbę dni; pola „Ile wyników" i „Typów z meczu" puste = auto;
- przy wielu rynkach naraz pojawiają się **wszystkie sensowne mecze** (sortowanie „po meczu");
- „Typów w auto-kuponie" = ile typów z różnych meczów ma mieć kupon; wynik zawiera „Najsłabszy typ na kuponie";
- każdy typ można dodać do Zestawienia (i odznaczyć).

## 3. Zestawienie (kupon)

- Twoje typy z kursami, które wpisujesz ręcznie; **AKO liczy się na żywo**: liczba typów, szansa wszystkich wg modelu (iloczyn), uczciwy kurs, kurs AKO, wartość oczekiwana (EV), stawka → wygrana.
  Typy z tego samego meczu nie są niezależne – wtedy szansy łącznej nie liczymy.
- **📄 Eksport PDF** (link na górze) – typy z kursami, godzinami i podsumowaniem AKO.
- **Zapisz w dzienniku zakładów** – zapisuje zakład (pojedynczy lub AKO) w „Moich zakładach".
- Opcjonalnie **analiza AI** (wymaga klucza i kodu dostępu; płatna za użycie, z dziennym limitem).
- Koszyk pamięta przeglądarka (`localStorage`) – na telefonie i komputerze osobno.

## 4. Ostatnie (retrospektywa)

Pokazuje, jak model poradziłby sobie z meczami z ostatnich 7/14/30 dni, **ucząc się tylko na meczach sprzed każdej kolejki**.
To podgląd, nie dziennik na żywo. Elementy: pierścień trafności 1X2, pasek formy modelu (✓/✗), **wykres trafności rynków**
(słupek = jak często zaszło, biała kreska = model, kropka = średnia ligi), tabela mecz po meczu w polach **zielonych (zaszło ✓) i czerwonych (nie ✗)**
z paskiem proporcji tak/nie nad kolumnami. **📄 PDF (wszystkie ligi)** – jeden plik ze wszystkimi ligami.
Przy 20 meczach różnice 5–10 pp to szum – patrz okno 30 dni.

## 5. Dziennik

Jedyny test „na żywo": prognozy zapisane przed meczem i rozliczone po wyniku (log-loss modelu vs średnia ligi vs rynek, Brier, kalibracja,
symulacja typów z przewagą ≥ 3%). **📄 PDF dziennika (wszystkie ligi)**. Zapis trwały wymaga `GITHUB_TOKEN` i `GITHUB_REPO` na Renderze.

## 6. Moje zakłady

Notatnik własnych zakładów: pojedyncze i AKO, kurs, stawka, szansa wg modelu. **Rozliczają się same** po wynikach (obsługuje 1X2, podwójną szansę,
gole, BTTS, remisy w połowach, kartki, rożne; AKO przegrywa od razu, gdy jeden typ nie wejdzie). Ręcznie: Wygrany / Przegrany / Zwrot / W grze / Usuń.
Statystyki: zysk, ROI, trafność, średni kurs, wykres skumulowanego zysku oraz **„Czy model miał rację?"** (średnia szansa wg modelu vs faktyczna trafność, zysk
oczekiwany vs rzeczywisty, kurs „na zero"). Przy kilkudziesięciu zakładach to głównie szum – sensowny obraz po kilkuset.

## 7. Pozostałe zakładki

- **Mecz** – szczegóły jednego meczu (rynki, dokładne wyniki, sędzia, ew. kontuzje).
- **Remisy** – ranking meczów pod rynki remisowe (HT, 2H, HT lub FT…).
- **Statystyki / Siła / Tabela** – sędziowie i drużyny (kartki, rożne), siła drużyn, symulacja tabeli (Monte Carlo).
- **Dane** – diagnostyka: źródła, liczba meczów, integralność bazy, trwałość dziennika, wynik ostatniego odświeżania.
- **🎾 Tenis** – link do aplikacji tenisowej (`/tennis/`).

## 8. Typowy dzień pracy

1. Otwórz **Mecze** – przejrzyj kafelki/H2H, odfiltruj mecze godne uwagi (zielone ramki, ⚑).
2. **Podpowiedzi** → dodaj kilka typów do **Zestawienia**, wpisz kursy bukmachera; sprawdź AKO, EV i najsłabszy typ.
3. Jeśli stawiasz – **Zapisz w dzienniku zakładów**.
4. Po meczach: **Moje zakłady** rozliczają się same; zerknij na **Ostatnie** i **Dziennik** (kalibracja, rynek vs model).
5. Raz w tygodniu: PDF dziennika/ostatnich do archiwum.

## 9. Jak czytać wyniki (uczciwie)

- Kursy zamknięcia to bardzo dobry predyktor – model ≈ rynek to normalne. Pytanie nr 1: *czy jestem skalibrowany?*, dopiero potem *czy zarabiam?*.
- Małe próby (20–50 meczów/zakładów) nie dowodzą niczego. Decyzje o „przewadze" dopiero przy setkach rozliczeń.
- Rynki remisów w połowach, kartek i rożnych nie mają historycznych kursów – oceniasz je względem średniej ligi i własnej skuteczności.
- H2H i forma to pomoc wzrokowa; `python -m fbpred h2h-test` pokazuje, czy H2H wnosi coś ponad kursy.
