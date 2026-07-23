@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Build PKD Segmentation QC

echo ============================================
echo   Building PKD Segmentation QC  (.exe)
echo ============================================
echo.

REM --- find a compatible Python ---
set "PYEXE="
py -3.12 -c "" 2>nul && set "PYEXE=py -3.12"
if not defined PYEXE ( py -3.13 -c "" 2>nul && set "PYEXE=py -3.13" )
if not defined PYEXE ( py -3.11 -c "" 2>nul && set "PYEXE=py -3.11" )
if not defined PYEXE ( py -3.14 -c "" 2>nul && set "PYEXE=py -3.14" )
if not defined PYEXE (
  echo Could not find a usable Python. Install Python 3.12 from:
  echo    https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)
echo Using interpreter: %PYEXE%

REM --- reuse the same venv as run.bat if present ---
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYEXE% -m venv .venv
  if errorlevel 1 ( echo Failed to create venv. & pause & exit /b 1 )
)
call ".venv\Scripts\activate.bat"

echo Installing dependencies + PyInstaller...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo.
  echo Install failed - see messages above.
  echo If you are on Python 3.14, install Python 3.12 and re-run.
  echo.
  pause
  exit /b 1
)

echo.
echo Running PyInstaller ^(this can take several minutes^)...
pyinstaller --noconfirm pkdqc.spec
if errorlevel 1 (
  echo.
  echo Build failed - see messages above.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   DONE.
echo   Your app:   dist\PKD_QC\PKD_QC.exe
echo.
echo   To use it now:   open the dist\PKD_QC folder and run PKD_QC.exe
echo   To share it:     zip the whole  dist\PKD_QC  folder
echo ============================================
echo.
pause
endlocal
