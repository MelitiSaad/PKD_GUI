@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PKD Segmentation QC

echo ============================================
echo   PKD Segmentation QC  -  launcher
echo ============================================
echo.

REM --- find a compatible Python (Qt/VTK wheels may not exist for 3.14 yet) ---
set "PYEXE="
py -3.12 -c "" 2>nul && set "PYEXE=py -3.12"
if not defined PYEXE ( py -3.13 -c "" 2>nul && set "PYEXE=py -3.13" )
if not defined PYEXE ( py -3.11 -c "" 2>nul && set "PYEXE=py -3.11" )
if not defined PYEXE ( py -3.14 -c "" 2>nul && set "PYEXE=py -3.14" & set "RISKY=1" )

if not defined PYEXE (
  echo Could not find a usable Python.
  echo Please install Python 3.12 from:
  echo    https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

echo Using interpreter: %PYEXE%
if defined RISKY (
  echo.
  echo NOTE: only Python 3.14 was found. Qt/VTK may not have 3.14 wheels yet,
  echo so install could fail. If it does, install Python 3.12 and re-run this.
  echo.
)

REM --- create the virtual environment on first run ---
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment ^(first run only^)...
  %PYEXE% -m venv .venv
  if errorlevel 1 ( echo Failed to create venv. & pause & exit /b 1 )
)

call ".venv\Scripts\activate.bat"

REM --- install dependencies (idempotent; fast after first run) ---
echo Checking dependencies...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed - see the messages above.
  echo Most common cause: Python 3.14 without Qt/VTK wheels. Install Python 3.12.
  echo.
  pause
  exit /b 1
)

echo.
echo Launching PKD Segmentation QC...

REM Verify the app imports cleanly first (errors show here), then launch
REM WITHOUT a console window so no terminal lingers while the app runs.
python -c "import pkdqc" 2>import_check.txt
if errorlevel 1 (
  echo.
  echo The app failed to start. Details:
  type import_check.txt
  del import_check.txt >nul 2>&1
  echo.
  echo A copy of run-time logs is in your user logs folder.
  pause
  exit /b 1
)
del import_check.txt >nul 2>&1
start "" ".venv\Scripts\pythonw.exe" -m pkdqc
endlocal
exit /b 0
