@echo off
REM Uruchamiane automatycznie przez Harmonogram zadan (python -m tnpred install-task).
REM Pobiera biezacy rok z tennis-data.co.uk i wysyla do GitHuba. Dziennik: tennis_update.log
cd /d "%~dp0"
python -m tnpred push-history >> tennis_update.log 2>&1
