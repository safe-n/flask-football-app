Źródło prawdy: zakończone mecze, jeden plik = liga + sezon (np. `E0_2025.csv`).

- Aktualizacja raz w tygodniu (workflow `weekly-history`) lub ręcznie: `python -m fbpred history-update --leagues E0`.
- Jednorazowy start: `python -m fbpred history-init --league E0 --seasons 2018-2025` albo
  `python -m fbpred history-export` (przenosi to, co masz już w lokalnej bazie SQLite).
- `odds/` - archiwum kursów przedmeczowych (dopisywane codziennie). `UPDATES.log` - dziennik aktualizacji.
- `aliases.json` (opcjonalnie): `{"Nott'm Forest": "Nottm Forest"}` - ujednolicenie nazw drużyn.
