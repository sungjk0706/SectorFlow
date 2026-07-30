@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

setlocal enabledelayedexpansion

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

echo ============================================
echo   SectorFlow 실행 중...
echo ============================================
echo.

REM ── 사전 확인: Python, Node ──────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo   Python 3.11+ 을 설치해 주세요: https://www.python.org/downloads/
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [오류] Node.js/npm이 설치되어 있지 않습니다.
    echo   Node.js 18+ 을 설치해 주세요: https://nodejs.org/
    pause
    exit /b 1
)

REM ── .env 파일 확인 ──────────────────────────────────
if not exist ".env" (
    echo [오류] .env 파일이 없습니다.
    echo   .env.example 을 복사하여 .env 를 만들고 설정값을 입력해 주세요:
    echo     copy .env.example .env
    echo   자세한 내용은 SETUP-WINDOWS.md 참고.
    pause
    exit /b 1
)

REM ── 가상환경 생성 (최초 1회) ──────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo 가상환경 생성 중...
    python -m venv .venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패.
        pause
        exit /b 1
    )
    echo 가상환경 생성 완료.
    echo.
)

REM ── Python 의존성 설치 (최초 1회) ────────────────────
if not exist ".venv\.deps_installed" (
    echo Python 의존성 설치 중...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [오류] Python 의존성 설치 실패.
        pause
        exit /b 1
    )
    echo done > ".venv\.deps_installed"
    echo Python 의존성 설치 완료.
    echo.
)

REM ── 프론트엔드 의존성 설치 (최초 1회) ────────────────
if not exist "frontend\node_modules" (
    echo 프론트엔드 의존성 설치 중...
    cd frontend
    call npm install
    if errorlevel 1 (
        echo [오류] npm install 실패.
        pause
        exit /b 1
    )
    cd ..
    echo 프론트엔드 의존성 설치 완료.
    echo.
)

REM ── 이전 프로세스 정리 (포트 충돌 방지) ──────────────
echo 이전 프로세스 정리 중...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

if exist "backend\data\server.lock" del /f /q "backend\data\server.lock" 2>nul

REM ── 백엔드 + 프론트엔드 실행 ──────────────────────────
echo 백엔드 및 프론트엔드 동시 준비 중...

start "SectorFlow-Backend" /min ".venv\Scripts\python.exe" main.py
set "BACKEND_TITLE=SectorFlow-Backend"

start "SectorFlow-Frontend" /min cmd /c "cd frontend && npm run dev"
set "FRONTEND_TITLE=SectorFlow-Frontend"

REM ── 백엔드 준비 대기 (최대 30초) ─────────────────────
echo 백엔드 시작 대기 중...
set /a WAIT_COUNT=0
:wait_backend
set /a WAIT_COUNT+=1
if %WAIT_COUNT% gtr 150 (
    echo [경고] 백엔드가 30초 내에 시작되지 않았습니다.
    echo   백엔드 창(SectorFlow-Backend)을 확인해 주세요.
    goto start_browser
)

powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:%BACKEND_PORT%/api/health' -TimeoutSec 1 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul 2>&1
    goto wait_backend
)
echo 백엔드 준비 완료.

REM ── 브라우저 열기 ────────────────────────────────────
:start_browser
echo.
echo ============================================
echo   SectorFlow 실행 완료
echo ============================================
echo.
echo   브라우저에서 접속하세요:
echo      http://localhost:%FRONTEND_PORT%
echo.
echo   종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo ============================================

start "" "http://localhost:%FRONTEND_PORT%"

REM ── 종료 대기 (CtrlC 또는 창 닫기) ────────────────────
echo.
echo 종료 대기 중... (Ctrl+C 로 종료)

:wait_exit
tasklist /fi "WINDOWTITLE eq SectorFlow-Backend*" 2>nul | find "cmd.exe" >nul 2>&1
if errorlevel 1 (
    echo 백엔드가 종료되었습니다. 프론트엔드 정리 중...
    taskkill /fi "WINDOWTITLE eq SectorFlow-Frontend*" /F >nul 2>&1
    goto cleanup
)
timeout /t 2 /nobreak >nul 2>&1
goto wait_exit

:cleanup
if exist "backend\data\server.lock" del /f /q "backend\data\server.lock" 2>nul
echo 모든 프로세스가 안전하게 종료되었습니다.
pause
exit /b 0
