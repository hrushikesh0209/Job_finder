@echo off
setlocal
echo ============================================================
echo   Job Finder AI - Setup and Launch
echo ============================================================
echo.

cd /d "%~dp0"

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [0/3] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )
)

set "PYTHON=venv\Scripts\python.exe"

echo [1/3] Installing required packages...
"%PYTHON%" -m pip install -r requirements.txt --prefer-binary -q
if errorlevel 1 (
    echo WARNING: Some packages failed to install. The app may not work fully.
)

echo.
echo [2/3] Optional extras
set /p INSTALL_PW="Install Playwright? Required for Indeed and Naukri boards (y/N): "
if /i "%INSTALL_PW%"=="y" (
    "%PYTHON%" -m pip install playwright -q
    "%PYTHON%" -m playwright install chromium
    echo Playwright + Chromium installed.
)
set /p INSTALL_ST="Install sentence-transformers for semantic CV matching? Downloads 22MB model on first use (y/N): "
if /i "%INSTALL_ST%"=="y" (
    "%PYTHON%" -m pip install sentence-transformers -q
    echo sentence-transformers installed.
)

echo.
echo [3/3] Launching web UI...
echo.
echo ============================================================
echo   Open your browser at: http://localhost:8501
echo   Press Ctrl+C in this window to stop the server.
echo ============================================================
echo.
"%PYTHON%" -m streamlit run app.py --server.port 8501

pause
