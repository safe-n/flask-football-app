@echo off
title Pilka + Tenis - lokalnie (nie zamykaj tego okna)
cd /d "%~dp0.."
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
set PYTHONUTF8=1
REM Petla "pobierz kod z GitHuba -> uruchom -> po przycisku /restart od nowa" jest w lokalnie\serwer.py.
REM Wszystko w JEDNEJ linii: cmd wczytuje ja w calosci, wiec podmiana tego pliku przez git pull nic nie psuje.
python lokalnie\serwer.py & pause & exit /b
