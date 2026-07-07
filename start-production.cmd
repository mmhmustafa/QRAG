@echo off
rem Launch the Customer Questionnaire Assistant in production mode (local single-user).
rem Builds the frontend once, then starts backend (no reload) and frontend in separate windows.
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Python environment not found. Follow the Quick start in README.md first.
  exit /b 1
)
if not exist frontend\node_modules (
  echo Frontend dependencies not installed. Run: npm install --prefix frontend
  exit /b 1
)
echo Building frontend...
call npm run build --prefix frontend
if errorlevel 1 exit /b 1
start "QRAG backend (port 8000)" cmd /k .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --app-dir backend
start "QRAG frontend (port 3000)" cmd /k npm run start --prefix frontend
echo.
echo Backend:  http://localhost:8000  (API docs at /docs)
echo Frontend: http://localhost:3000
echo A database backup snapshot is written to .\backups\ on every backend start.
