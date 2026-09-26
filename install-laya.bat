@echo off
rem Manual installer for the local decision engine (Laya).
rem
rem The agent installs it by itself on the first normal start; this is the hand-run path
rem for when that could not happen (offline start, failed download, or a reinstall).
rem Both run the same code, so the CPU-torch choice and the messages are identical.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run the main starter ^(start-host.bat^) once, then try again.
  pause
  exit /b 1
)
".venv\Scripts\python" -m jev_ultrafast.laya_install
pause
