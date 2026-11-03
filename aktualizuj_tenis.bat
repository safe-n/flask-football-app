@echo off
REM Recznie (dwuklik): pobiera biezacy rok z tennis-data.co.uk i wysyla do GitHuba - bez Commit/Push.
cd /d "%~dp0"
python -m tnpred push-history
echo.
pause
