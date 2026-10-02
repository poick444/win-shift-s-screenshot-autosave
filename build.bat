@echo off
setlocal
py -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1
py assets\make_icon.py
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm --clean --onefile --windowed --name Kadr --icon assets\kadr.ico --add-data "assets\kadr.ico;assets" main.py
if errorlevel 1 exit /b 1
echo Done: dist\Kadr.exe
