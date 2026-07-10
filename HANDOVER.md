# HANDOVER — SectorFlow

## 추후 논의 필요 (미결정)
- 없음

## 진행 중 작업 (다음 세션에서 이어서 진행)
- **백엔드 로그 메시지 "복원" → "로드/구축" 수정: 2단계 (함수명 변경) 대기 중**
  - 1단계 완료 (이번 세션): 로그 메시지 + docstring/주석 16건 수정 — 아래 "직전 완료 작업" 참조
  - 2단계 (후속 세션): 함수명 변경 — `_restore_daily_buy_state()` → `_load_daily_buy_state()` (`trading.py:53`), `restore_state()` → `load_state()` (`settlement_engine.py:159`)
    - 주의: `restore_state()`는 기동 시(로드)와 모드 전환 시(복원) 모두 호출되는 dual-purpose 함수
    - 모드 전환 호출처: `engine_lifecycle.py:188` — 이쪽은 "복원"이 맞으므로 함수 분리 또는 호출처 주석으로 맥락 명시 필요
    - 호출처 추적 필수: `restore_state` 검색 후 모든 caller 확인

## 직전 완료 작업
- **2026-07-11: 백엔드 로그 메시지 "복원" → "로드/구축" 수정 (1단계: 로그+주석)**
  - 문제: 앱 기동 시 DB→메모리 로드 작업에 "복원(restore)"이라는 단어가 사용되어 실제 동작과 불일치
  - 수정 파일 7개 + 테스트 파일 1개:
    - `trade_history.py` — 로그 2건 + docstring 2건: "DB 복원" → "체결 이력 로드"
    - `settlement_engine.py` — 로그 1건 + docstring 3건: "상태 복원" → "상태 로드"
    - `engine_lifecycle.py` — 로그 1건 + docstring/주석 2건: "포지션 복원" → "포지션 구축"
    - `engine_cache.py` — 로그 1건 + 주석 1건: "상태 복원" → "상태 로드"
    - `trading.py` — 로그 2건 + docstring 1건: "매수 상태 복원" → "매수 상태 로드"
    - `engine_loop.py` — 주석 1건: "예수금 복원" → "예수금 로드"
    - `test_trade_history.py` — docstring 1건: "메모리 복원" → "메모리 로드"
  - 수정하지 않은 "복원" (적절한 사용): 재연결 후 구독 복원, 플래그 복원, 모드 전환 시 상태 복원, 재상장 종목 복원 등 39건
  - 검증: 런타임 기동 (`main.py` 15s) — 로그에서 "로드"/"구축" 출력 확인, 잔여 프로세스 없음
  - 커밋: `43699ac`

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체 (korean_lunar_calendar), boost_order_ratio_pct 422 수정, 보유종목 buy_date 파생, 유령 포지션 재발 방지 조치 — 모두 코드 확인 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 주문가능금액 배지, 매수일자 컬럼, stale state 수정, 색상 체계 통일 (COLOR 상수화), 검색 입력란 공통 컴포넌트, 가상 스크롤 플래시 억제, 일반설정 비거래일 배지 정렬 수정, 업종순위 요약 라벨 가독성 개선, 매수후보 배지 폰트 13px 확대, 매도설정 보유종목 요약 배지 추가 — 모두 코드 확인 완료, `npm run build` 통과
- **Git**: `9dfc6e2` (매도설정 보유종목 요약 배지 추가) — push 완료
- **테스트 커버리지**: Stage 1~9 완료 — 백엔드 2138 passed, 프론트엔드 112 passed (실행 시점 기준)
- **settlement.py await 누락**: 수정 완료 (`settlement.py:16`)

## 다음 단계
- **1순위: 백엔드 로그 메시지 "복원" → "로드/구축" 수정 2단계 (함수명 변경)**:
  - `_restore_daily_buy_state()` → `_load_daily_buy_state()` (`trading.py:53`)
  - `restore_state()` → `load_state()` (`settlement_engine.py:159`) — dual-purpose 함수이므로 모드 전환 호출처(`engine_lifecycle.py:188`) 맥락 처리 필요
  - 모든 caller 추적 후 일괄 변경, 테스트 통과 확인
- **2순위: 유령 포지션 근본 원인 심층 조사 (별도 세션)**:
  - 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
  - WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
  - `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조
- **2순위: 테스트 커버리지 다음 Stage 대상 선정 (사용자와 논의)**:
  - Stage 1~9 완료 — 전체 2138 passed (P1~P6 우선순위별 진행 완료)
  - 남은 미진행 파일: `telegram_bot.py` (P6)
  - 다음 Stage 대상 파일 선정 필요

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결**
  - 상세 조사 기록: `docs/ghost_position_investigation.md` ([A]~[I] 미조사 항목)
  - 재발 방지 조치 (2026-07-10, 코드 확인 완료):
    - `test_positions` 테이블 제거 — `stock_tables.py:141`, DB 저장 로직 전체 제거
    - `trades` 기반 SSOT 전환 — `dry_run.py:38-68`, `trade_history.py:549`
    - `execute_sell()` 런타임 가드 — `trading.py:418-436` (유령 포지션 차단 + Telegram 알림)
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 수동 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성

## 테스트 실행 원칙 (필수 준수)

### 1. 실행 명령어 (통일)
```
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- `timeout_method = signal` 필수 — `thread` 방식은 asyncio C-level wait를 interrupt하지 못해 hang 시 프로세스가 영구 블록됨
- `pytest.ini`에 전역 설정되어 있으므로 CLI에서 생략 가능

### 2. 자동 hang 체크 원칙 (에이전트 필수 강제 — 수동 개입 금지)
- **a. 10초마다 진행 상태 자동 체크**: 테스트 실행 후 `command_status`로 주기적 확인
- **b. 10초 이상 로그/출력 멈추면 즉시 hang 간주**: 대기 없이 강제 종료 결정
- **c. hang 감지 시 즉시 프로세스 강제 종료**: SIGTERM/Ctrl+C로 프로세스 종료
- **d. hang 원인 자동 분석**: 종료 후 로그/코드 분석하여 원인 보고
- **e. 위 모든 과정은 에이전트가 자동 수행**: 사용자 확인 대기 금지, 수동 개입 금지
- 정상 완료: "✅ N passed in N.Ns"
- hang 감지: "❌ 10초 이상 응답 없음 — 강제 종료 및 원인 분석 시작"

### 3. 테스트 hang 방지 코딩 원칙 (근본 원인별)

#### 원인 A: 실제 asyncio 동기화 프리미티브 (Lock/Event/wait_for)
- **금지**: 테스트에서 실제 `asyncio.Lock()`, `asyncio.Event()`, `asyncio.wait_for()` 사용
- **해결**: `MagicMock` + `AsyncMock`으로 교체
  - Lock: `lock.__aenter__ = AsyncMock(return_value=lock)`, `lock.__aexit__ = AsyncMock(return_value=None)`
  - Event: `ev.wait = AsyncMock()`, `ev.clear/set = MagicMock()`
  - wait_for: 즉시 반환 또는 즉시 `TimeoutError` 발생시키는 async 함수로 patch

#### 원인 B: asyncio.create_task 백그라운드 태스크
- **금지**: 테스트에서 `asyncio.create_task()`가 실제 실행되는 것을 허용
- **해결**: `patch("module.asyncio.create_task")`로 mock 교체, `add_done_callback` 속성 포함

#### 원인 C: NotificationWorker / 백그라운드 워커 싱글톤
- **금지**: `_fire_and_forget_telegram` 등이 실제 `NotificationWorker.get_instance()`를 호출하여 백그라운드 태스크 생성
- **해결**: autouse fixture에서 `patch("module._fire_and_forget_telegram")` 처리

#### 원인 D: 실제 DB I/O (aiosqlite)
- **금지**: 테스트에서 `get_db_connection()`이 실제 DB에 연결
- **해결**: autouse fixture에서 `patch("backend.app.db.database.get_db_connection")` 처리

#### 원인 E: pytest-asyncio 이벤트 루프 간섭
- **금지**: conftest.py에 async fixture 사용 (이벤트 루프 정리 중 hang 유발)
- **금지**: conftest.py에서 `asyncio.sleep` 전역 patch (pytest-asyncio 내부 동작 간섭)
- **해결**: conftest.py는 동기 fixture만 사용, 캐시 리셋 등 최소 기능만 유지

### 4. run_command 사용 시
- `Blocking: false` + `WaitMsBeforeAsync: 20000` — hang 감지 시 명령 취소 가능
- 또는 subprocess + `proc.wait(timeout=N)` + `proc.kill()` 패턴 사용
