@echo off
REM linkedin-autopilot launcher — install + run
REM Usage: run.bat           (first install)
REM        run.bat --shell    (open a cmd in the venv)

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Installing virtual environment...
    python -m venv venv
    echo Installing dependencies...
    venv\Scripts\pip install --upgrade pip
    venv\Scripts\pip install -r requirements.txt
    echo Installing engines' dependencies...
    venv\Scripts\pip install selenium webdriver-manager python-dotenv PyYAML keyring openai
    echo Done.
)

if "%1"=="--shell" (
    cmd /k "venv\Scripts\activate.bat"
) else (
    venv\Scripts\python -m app.main
)
