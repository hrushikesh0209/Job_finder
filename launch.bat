@echo off
REM One command to set up (first run) and launch Job Finder in your browser.
REM Usage: double-click, or run "launch.bat" / "launch.bat --port 8502"
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" launch.py %*
    goto done
)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 launch.py %*
    goto done
)
where python >nul 2>&1
if not errorlevel 1 (
    python launch.py %*
    goto done
)
echo Python 3.10+ not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup.
pause
exit /b 1

:done
if errorlevel 1 pause
