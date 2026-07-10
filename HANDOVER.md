# HANDOVER — SectorFlow

## 추후 논의 필요 (미결정)
- 없음

## 진행 중 작업 (다음 세션에서 이어서 진행)
- **백엔드 로그 아키텍처 점검 후속 — 세션별 단위 작업 (로그+코드 정밀 검증)**
  - 점검 완료: 런타임 기동 로그 + 코드베이스 886건 logger 호출 분석 (3개 병렬 에이전트)
  - 2단계 완료: 함수명 변경 (`_restore_daily_buy_state` → `_load_daily_buy_state`, `restore_state` → `load_state`)
  - C-1단계 완료: 구두점 "->" → "—" 통일 7건
  - E단계 완료: `engine_config.py` 로그 메시지 vs 실제 동작 불일치 수정 (백엔드 3건 + 프론트엔드 6건)
  - **C단계 완료: C-2 `--` → "—" 통일** — C-2-1(26건) + C-2-2(50건) + C-2-3(56건) = 총 132건
    - C-2-1 완료: settlement_engine(7), engine_lifecycle(6), engine_cache(5), dry_run(8) = 26건
    - C-2-2 완료: daily_time_scheduler(23), market_close_pipeline(4), engine_ws(14), engine_ws_reg(9) = 50건
    - C-2-3 완료: ws(7), engine_account(18), stock_tables(1), app(1), settings_file(2), notification_worker(3), engine_ws_fill_followup(2), engine_bootstrap(3), stock_classification_data(2), kiwoom_stock_rest(12), trading(5) = 56건
    - 제외: SQL 주석 7건(stock_tables), 장식용 구분선 6건(app.py) — 문법/의도적
    - engine_service.py는 `--` 매치 0건으로 제외됨
  - **B단계**: 부적절한 로그 레벨 1건
    - `engine_cache.py:152` — `logger.info` → `logger.warning` ("저장데이터 로드 실패"를 INFO로 로깅)
  - **A단계**: silent 예외 처리 5건 (`except Exception: pass` → `logger.warning` 추가)
    - `settlement_engine.py:110-111` — State Gate 회복 실패 silent pass
    - `settlement_engine.py:228-229` — test_virtual_deposit 로드 실패 silent pass
    - `trade_history.py:109-110` — dry_run 포지션 캐시 무효화 실패 silent pass
    - `trade_history.py:228-229` — 동일 (이력 초기화 후)
    - `trade_history.py:530-531` — 동일 (테스트모드 데이터 삭제 후)
  - **검토 권장 (D단계, 별도)**: 영구 저장소 실패를 `logger.warning` → `logger.error` 검토
    - `settlement_engine.py:176` — "상태 저장 실패"
    - `settlement_engine.py:219` — "상태 파일 로드 실패 (기본값 사용)"

## 직전 완료 작업
- **2026-07-11: C-2-3 — `--` → "—" 통일 (3차, 56건)**
  - 대상: ws(7), engine_account(18), stock_tables(1), app(1), settings_file(2), notification_worker(3), engine_ws_fill_followup(2), engine_bootstrap(3), stock_classification_data(2), kiwoom_stock_rest(12), trading(5)
  - 제외: SQL 주석 7건(stock_tables `-- 백만원 단위`), 장식용 구분선 6건(app.py `# --- startup ---` 등)
  - 로그 vs 동작 불일치: 없음 (정밀 검증 완료)
  - 검증: py_compile 11개 통과, 런타임 기동 정상 (`—` 로그 출력 확인), 잔존 프로세스 0건
  - **커밋**: `9b5d60d`

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체 (korean_lunar_calendar), boost_order_ratio_pct 422 수정, 보유종목 buy_date 파생, 유령 포지션 재발 방지 조치 — 모두 코드 확인 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 주문가능금액 배지, 매수일자 컬럼, stale state 수정, 색상 체계 통일 (COLOR 상수화), 검색 입력란 공통 컴포넌트, 가상 스크롤 플래시 억제, 일반설정 비거래일 배지 정렬 수정, 업종순위 요약 라벨 가독성 개선, 매수후보 배지 폰트 13px 확대, 매도설정 보유종목 요약 배지 추가 — 모두 코드 확인 완료, `npm run build` 통과
- **Git**: `5d175d9` (C-2-1, 26건) + `82032e1` (C-2-2, 50건) + `9b5d60d` (C-2-3, 56건) — push 미수행
- **테스트 커버리지**: Stage 1~9 완료 — 백엔드 2138 passed, 프론트엔드 112 passed (실행 시점 기준)
- **settlement.py await 누락**: 수정 완료 (`settlement.py:16`)

## 다음 단계
- **1순위: B단계 — 부적절한 로그 레벨 (1세션)**:
  - `engine_cache.py:152` — `logger.info` → `logger.warning` ("저장데이터 로드 실패"를 INFO로 로깅)
  - 검증: py_compile + 런타임 기동
- **2순위: A단계 — silent 예외 처리 5건 (1세션)**:
  - `settlement_engine.py:110-111, 228-229`, `trade_history.py:109-110, 228-229, 530-531`
  - `except Exception: pass` → `logger.warning("...", exc_info=True)` 추가
  - 각 예외 블록의 의도(silent 허용 vs 버그)를 코드 맥락에서 판단 후 수정
  - 검증: py_compile + 런타임 기동 + 관련 테스트 파일 실행
- **3순위: D단계 — 영구 저장소 실패 로그 레벨 검토 (1세션)**:
  - `settlement_engine.py:176, 219` — `logger.warning` → `logger.error` 검토
  - 검증: py_compile + 런타임 기동
- **4순위: 유령 포지션 근본 원인 심층 조사 (별도 세션)**:
  - 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
  - WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
  - `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조
- **5순위: 테스트 커버리지 다음 Stage 대상 선정 (사용자와 논의)**:
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
