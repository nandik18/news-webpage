@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Commodity News Desk - EXE Builder
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found.
  echo Install Python 3.11+ from python.org and try again.
  pause
  exit /b 1
)

echo Installing/updating required packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: Package installation failed.
  pause
  exit /b 1
)

echo.
echo Building Windows EXE...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist CommodityNewsDesk.spec del /q CommodityNewsDesk.spec

python -m PyInstaller --noconfirm --clean --onefile --windowed --name CommodityNewsDesk --add-data "templates;templates" --add-data "static;static" app.py
if errorlevel 1 (
  echo.
  echo ERROR: EXE build failed.
  pause
  exit /b 1
)

echo.
echo ==========================================
echo   BUILD COMPLETE
echo ==========================================
echo.
echo Your EXE is here:
echo   dist\CommodityNewsDesk.exe
echo.
echo Double-click it to launch the dashboard.
echo.
pause
