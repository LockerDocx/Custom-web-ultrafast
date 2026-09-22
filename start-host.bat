@echo off
setlocal
cd /d "%~dp0"
title Jev Ultrafast - Firefox bridge host

rem Double-clickable starter: prepares a private Python environment and runs
rem the Firefox bridge host. First run also creates the .env settings file.

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 or newer is required.
  echo Install it from https://www.python.org/downloads/ and double-click this file again.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Preparing the host for the first run. This can take a minute...
  python -m venv .venv
  ".venv\Scripts\python" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python" -m pip install --quiet -e .
  if errorlevel 1 (
    echo Installation failed. Check your internet connection and run this file again.
    pause
    exit /b 1
  )
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo A settings file .env was just created.
  echo Add your API keys ^(GROQ_API_KEY, NVIDIA_API_KEY, ...^) and double-click this file again.
  echo See docs\providers.md for every option.
  start notepad ".env"
  pause
  exit /b 0
)

echo.
echo Host starting. Keep this window open while you use the sidebar.
echo Firefox: about:debugging -^> This Firefox -^> Load Temporary Add-on -^> extension\manifest.json
echo.
".venv\Scripts\jev-firefox"
echo.
echo The host stopped.
pause
