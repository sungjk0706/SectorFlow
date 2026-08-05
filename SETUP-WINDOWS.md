# SectorFlow Windows 설치 가이드

> Windows 사용자를 위한 설치·실행 가이드입니다.

---

## 1. 사전 준비 (필수)

### 1-1. Python 3.11+

1. https://www.python.org/downloads/ 에서 Python 3.11 이상 설치
2. 설치 시 **"Add Python to PATH"** 체크 확인

확인:
```powershell
python --version
```

### 1-2. Node.js 18+

1. https://nodejs.org/ 에서 LTS 버전 설치

확인:
```powershell
node --version
npm --version
```

---

## 2. 설정 파일 준비

### 2-1. .env 파일 생성

`.env.example` 을 복사하여 `.env` 를 만듭니다:

```powershell
copy .env.example .env
```

### 2-2. 암호화 키 설정 (중요)

**stocks.db 를 공유받은 경우:**
- 원본 제공자의 `ENCRYPTION_KEY` 값을 그대로 입력해야 기존 설정이 복호화됩니다.

**새로 설치하는 경우:**
- 아래 명령으로 새 키를 생성하여 `.env` 의 `ENCRYPTION_KEY=` 뒤에 입력:
```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2-3. 증권사 API 키 입력

사용할 증권사의 API 키를 `.env` 에 입력:

- **LS증권**: `LS_APP_KEY`, `LS_APP_SECRET` (https://openapi.ls-sec.co.kr 발급)
- **키움증권**: `KIWOOM_APP_KEY`, `KIWOOM_APP_SECRET` (https://api.kiwoom.com 발급)

> API 키는 앱 실행 후 UI 설정 화면에서도 입력 가능합니다.

---

## 3. 실행

### 방법 A: 바로가기 (권장)

1. `Create-Shortcut-Win.ps1` 우클릭 → **PowerShell로 실행**
2. 생성된 `SectorFlow-Win.lnk` 더블클릭

### 방법 B: 직접 실행

```powershell
.\SectorFlow-Win.bat
```

### 최초 실행 시 자동 수행

- Python 가상환경 생성 (`.venv\`)
- Python 의존성 설치 (`pip install -r requirements.txt`)
- 프론트엔드 의존성 설치 (`npm install`)

> 최초 실행은 몇 분 소요될 수 있습니다.

---

## 4. 접속

실행 완료 후 브라우저가 자동으로 열립니다:

```
http://localhost:5173
```

수동 접속 시 위 주소로 이동하세요.

---

## 5. 종료

- 런처 창에서 **Ctrl+C** 또는 창 닫기
- 백엔드·프론트엔드 프로세스가 자동으로 안전 종료됩니다.

---

## 6. 투자 모드 설정

앱 실행 후 UI 설정 화면에서:

| 모드 | 설명 |
|------|------|
| **테스트 모드** | 가상 데이터로 업종 순위·매수후보 로직 검증 (API 키 불필요) |
| **실전/모의투자** | 증권사 서버로 실제 주문 전송 (API 키 필수) |

> 백테스트 피드백 목적이라면 먼저 **테스트 모드**로 로직을 확인한 후,
> 증권사 모의투자 계좌로 전환하는 것을 권장합니다.

---

## 7. 문제 해결

### 포트가 이미 사용 중

```powershell
netstat -ano | findstr :8000
netstat -ano | findstr :5173
```
해당 PID 종료:
```powershell
taskkill /PID <PID번호> /F
```

### 백엔드가 시작되지 않음

1. `.env` 파일의 `ENCRYPTION_KEY` 가 올바른지 확인
2. `backend\data\server.lock` 파일이 있으면 삭제
3. 런처 창(SectorFlow-Backend)의 에러 메시지 확인

### 의존성 재설치

```powershell
rmdir /s /q .venv
del /f /q .venv\.deps_installed 2>nul
rmdir /s /q frontend\node_modules
```
이후 `SectorFlow-Win.bat` 재실행 → 자동 재설치.

---

## 8. DB (stocks.db) 공유 관련

stocks.db 를 공유받은 경우:

1. `backend\data\` 폴더에 `stocks.db` 배치
2. `.env` 의 `ENCRYPTION_KEY` 를 원본 제공자와 **동일**하게 설정
3. 기존 증권사 API 키는 암호화되어 DB에 저장되어 있으나,
   본인 계좌로 사용하려면 UI 설정에서 **본인의 API 키로 교체** 필요
