Tu trafiają parametry modelu per liga (`params_E0.json` itd.) z komend `tune` i `fatigue-test --apply`.
Plik jest wersjonowany w gicie, więc po `git add params && git commit && git push` Render używa tych samych ustawień co Ty.
Bez tego serwis liczy na wartościach domyślnych (ridge=10, xi=0.0019, bez miksu z rynkiem i bez korekt).
