---
description: 백엔드 코드 수정 및 런타임 검증 절차
---

## 백엔드 수정 절차

### 1. 사전 조사
- 대상 파일의 전체 구조와 의존성 확인
- 영향 받는 모든 파일/함수/변수 식별
- 아키텍처 원칙 준수 여부 확인 (async/asyncio, SSOT, 폴백 금지)

### 2. 코드 수정
- 작은 단위로 수정 (파일 하나씩, 블록 단위)
- 아키텍처 원칙 준수:
  - 모든 I/O는 async def
  - 동기 함수 금지 (httpx.AsyncClient/aiosqlite 사용)
  - run_in_executor 우회 금지
  - 단일 asyncio 이벤트 루프 유지
  - 폴백 금지 (원칙 20)

### 3. 정적 검증
- py_compile 통과 확인
- 타입 체크 (mypy)
- 린트 (ruff)

### 4. 런타임 기동 검증 (필수 - 원칙 19)
py_compile 통과와 pytest 통과는 런타임 동작을 보장하지 않음. 반드시 다음 절차 수행:

#### 4-1. 앱 기동
```bash
.venv/bin/python main.py
```

#### 4-2. 기동 확인 (10~30초 대기)
- 콘솔 로그 확인: 에러/Traceback/RuntimeWarning 없음
- 파일 로그 확인 (`backend/logs/trading_*.log`): 정상 기록 여부
- 지연/hang/예외 발생 여부 확인

#### 4-3. 프로세스 종료
```bash
kill <PID>
```

#### 4-4. 잔존 프로세스 확인
```bash
ps aux | grep -E "python|main.py" | grep -v grep
```
- 잔존 프로세스 0개인지 확인

### 5. 테스트 실행 (필요한 경우)
```bash
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- hang 감지 시 즉시 강제 종료
- 잔존 프로세스 정리 필수

### 6. 보고
- 수정한 파일
- 해결한 근본 원인
- 검증한 항목 (정적 검증 + 런타임 기동)
- 사용자가 직접 확인할 방법

## 주의사항
- 아키텍처 원칙 관련 수정은 런타임 기동 검증 생략 금지
- asyncio, 이벤트 루프, 비동기 큐, WebSocket 관련 수정은 특히 주의
- 잔존 프로세스 0개 확인까지가 완료 기준
