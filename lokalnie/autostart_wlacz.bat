@echo off
REM Autostart bez uprawnien administratora: skrot w folderze Autostart uzytkownika.
set "S=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\pilka_tenis_lokalnie.bat"
> "%S%" echo @echo off
>> "%S%" echo start "Pilka+Tenis" /min "%~dp0uruchom_aplikacje.bat"
echo Gotowe: aplikacja wystartuje sama po zalogowaniu do Windows.
echo Plik autostartu: %S%
echo Wylaczenie: autostart_wylacz.bat
pause
