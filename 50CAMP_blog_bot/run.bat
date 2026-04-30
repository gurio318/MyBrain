@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install from https://www.python.org/
    pause
    exit /b 1
)
pip install anthropic -q >nul 2>&1
echo Starting blog post generation...
python generate_and_post.py
pause
