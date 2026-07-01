@echo off
setlocal

cd /d "%~dp0"

set "PYEXE=python"
%PYEXE% --version >nul 2>nul
if errorlevel 1 (
  set "PYEXE=py -3"
  %PYEXE% --version >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ first.
    pause
    exit /b 1
  )
)

echo [1/5] Python OK

if not exist ".venv\Scripts\python.exe" (
  echo [2/5] Creating virtual environment...
  %PYEXE% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
  )
) else (
  echo [2/5] Virtual environment already exists.
)

echo [3/5] Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] Failed to activate virtual environment.
  pause
  exit /b 1
)

echo [4/5] Installing dependencies...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] Failed to upgrade pip.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Failed to install requirements.
  pause
  exit /b 1
)

echo [5/5] Starting service...
echo URL: http://127.0.0.1:8000
echo HEALTH: http://127.0.0.1:8000/health
echo DOCS: http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop.
echo.
python -m uvicorn app:app --host 0.0.0.0 --port 8000

echo.
echo Service stopped.
pause
endlocal
