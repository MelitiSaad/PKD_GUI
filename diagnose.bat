@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag your scan file ^(or the DICOM folder^) onto this file,
  echo or run:  diagnose.bat "C:\path\to\scan"
  echo.
  set /p SCAN="Or paste the path here and press Enter: "
) else (
  set "SCAN=%~1"
)
if not exist ".venv\Scripts\python.exe" (
  echo Please run run.bat once first to set up the environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" diagnose.py "%SCAN%"
echo.
pause
endlocal
