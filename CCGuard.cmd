@echo off
setlocal
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
  start "" pythonw.exe "%~dp0CCGuard.pyw"
  exit /b 0
)
where pyw.exe >nul 2>nul
if not errorlevel 1 (
  start "" pyw.exe -3 "%~dp0CCGuard.pyw"
  exit /b 0
)
where python.exe >nul 2>nul
if not errorlevel 1 (
  python "%~dp0CCGuard.pyw"
  if errorlevel 1 pause
  exit /b 0
)
where py.exe >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0CCGuard.pyw"
  if errorlevel 1 pause
  exit /b 0
)
echo Python 3.10+ was not found. Install it from https://www.python.org/downloads/ and enable "Add python.exe to PATH".
pause
exit /b 1
