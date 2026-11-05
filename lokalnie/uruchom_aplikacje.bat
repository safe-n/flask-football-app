@echo off
title Pilka + Tenis - lokalnie (nie zamykaj tego okna)
cd /d "%~dp0.."
echo Sprawdzam serwer waitress...
python -m pip install --quiet --disable-pip-version-check waitress
REM odswiezanie danych w tle wlaczone (na komputerze tennis-data.co.uk dziala bezposrednio)
set AUTO_BOOTSTRAP=1
set TN_AUTO_BOOTSTRAP=1
set TN_REFRESH_HOURS=3
REM osobna baza i osobna galaz zapisu, zeby kopia lokalna nie nadpisywala zakladow i dziennika z Rendera
set TN_DB_PATH=data\tennis_local.db
set DB_PATH=data\football_local.db
set LEDGER_BRANCH=ledger-data-local
set TN_LEDGER_BRANCH=ledger-data-local
REM wycisza tylko niegrozne ostrzezenie pandas o wydajnosci (kod pilki); inne ostrzezenia i bledy nadal widac
set PYTHONWARNINGS=ignore:DataFrame is highly fragmented
echo.
echo Aplikacja startuje. Na tym komputerze:  http://localhost:5000   (tenis: http://localhost:5000/tennis/)
echo Z telefonu przez Tailscale:            http://%COMPUTERNAME%:5000   (tenis: /tennis/)
echo Zamkniecie tego okna = wylaczenie aplikacji.
echo.
python -m waitress --host=0.0.0.0 --port=5000 --threads=6 combo:app
pause
