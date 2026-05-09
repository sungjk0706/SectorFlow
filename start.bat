@echo off
chcp 65001 >nul
title SectorFlow

:: ── 중복 실행 체크: 포트 8000이 이미 사용 중이면 실행 차단 ──
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo  ============================================
    echo    이미 실행 중입니다!
    echo    SectorFlow 서버가 이미 켜져 있습니다.
    echo    중복 실행을 차단합니다.
    echo  ============================================
    echo.
    timeout /t 3 >nul
    exit
)

echo ============================================
echo   SectorFlow Server Starting...
echo ============================================
echo.

call %~dp0.venv\Scripts\activate.bat

echo [1/2] Starting server...
echo   - Press Ctrl+C or close this window to stop
echo.
cd /d %~dp0
python main.py
