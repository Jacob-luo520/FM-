@echo off
cd /d "%~dp0"
set "PY="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3 not found. Install from https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% "%~dp0build_exe.py"
pause
