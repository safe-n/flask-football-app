@echo off
REM Aktualizacja historii tenisa: pobiera biezacy rok z tennis-data.co.uk i stroi model.
REM Potem otworz GitHub Desktop: Commit to master, Push origin.
cd /d "%~dp0"
python -m tnpred fetch-history
echo.
echo Teraz w GitHub Desktop: Commit to master, potem Push origin.
pause
