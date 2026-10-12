@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please follow the first-time setup in README.md first.
  pause
  exit /b 1
)
echo Open http://localhost:8000 in your browser after the server starts.
".venv\Scripts\python.exe" app.py
pause
