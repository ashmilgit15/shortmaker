@echo off
echo ============================================
echo   ShortMaker Cookie Sync
echo   Uploads YouTube cookies from Firefox
echo   to your ShortMaker server
echo ============================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python first.
    pause
    exit /b 1
REM Check if httpx is installed
python -c "import httpx" >nul 2>&1
if errorlevel 1 (
    echo Installing httpx...
    pip install httpx
)

echo.
echo Choose an option:
echo   1. Upload cookies to server (auto-sync every 60 min)
echo   2. Print base64 value for Render env var
echo   3. Upload once and exit
echo.
set /p choice="Enter choice (1-3): "

if "%choice%"=="1" (
    python scripts\cookie_auto_sync.py --base-url https://shortmaker-2.onrender.com
) else if "%choice%"=="2" (
    python scripts\cookie_auto_sync.py --print-base64
    echo.
    echo Copy the base64 value above and paste it into
    echo SHORTMAKER_YTDLP_COOKIES_BASE64 in your Render dashboard.
    pause
) else if "%choice%"=="3" (
    python scripts\cookie_auto_sync.py --once --base-url https://shortmaker-2.onrender.com
    pause
) else (
    echo Invalid choice.
    pause
)
