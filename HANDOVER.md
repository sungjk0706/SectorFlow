# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-09: Settlement Engine 리팩토링 — constants 추출, init→_load 통합**
  - `backend/app/core/constants.py` 신규 생성 (`_KST`, `BUY_COMMISSION`, `SELL_COMMISSION`, `SECURITIES_TAX`)
  - `settlement_engine.py`: `init()` 제거, `_load()`에 초기화 로직 통합, `restore_state(initial_deposit)` 연결
  - `engine_cache.py:113-117`: 기동 시 `restore_state(initial_deposit=settings["test_virtual_deposit"])` 호출 추가
  - `engine_loop.py:211`: 중복 `restore_state` 호출 제거 (engine_cache로 이관)
  - 테스트: `test_settlement_engine.py`, `test_dry_run_fill_event.py` — constants import, `init` 테스트→`_load` 테스트 교체
  - 검증: pytest 1020 passed, 런타임 기동 정상 (`[정산] 상태 복원 완료` 로그 확인)
  - 커밋: `3f783af` — `refactor: settlement_engine constants 추출 및 init→_load 통합`

## 현재 상태
- **백엔드**: Settlement Engine 리팩토링 완료, RiskManager 리팩토링 Phase 1 완료
- **프론트엔드**: 더미 데이터 삭제 완료, `npm run build` 통과
- **Git**: 커밋 `3f783af` push 완료 (관련 없는 변경사항 ARCHITECTURE.md, architecture_principles.md, risk_manager_refactor_megaplan.md는 미커밋)

## 다음 단계
- **1순위: 유령 포지션 재발 방지 (승인 후 진행)**:
  - 방안 A: `_load_positions()`에 trades 이력 교차 검증 추가 (`dry_run.py:46-55`)
  - shutdown 시퀀스 보완: `SectorFlow.command:19` SIGTERM 대기 2초→5초 연장
- **2순위: 브라우저 실제 화면 확인** — 장중에 매수후보 테이블에서 SK하이닉스(000660) 하이라이트 깜빡임 없는지 확인
- **3순위: exchange_calendars 교체 검토** — pandas(70MB)+numpy(33MB) 등 간접 의존성 약 112MB 절감 가능

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 3중 검증 완료, 일부 원인 미상**
  - 현상: 07-09 15:52 앱 재시작 시 삼성전자 10주 @70,100원이 갑자기 복원됨
  - 15:52:19 자동 익절 매도되어 실현손익 +2,087,886원 기록
  - 확인된 사실 (3중 검증 완료):
    - 코드 정상 경로로는 70,100원 포지션 생성 불가
    - "외부 요인에 의한 DB 직접 삽입" 결론은 타당
  - 미해결 사항 (다음 세션 조사 필요):
    1. 70,100원 값의 출처 (코드/로그/trades 어디에도 BUY 기록 없음)
    2. 14:32~15:52 80분 공백 시간 동안 DB를 조작한 주체
    3. shutdown 시퀀스가 `stop_db_writer()` 도달 전 중단된 원인 (`app.py:172` 이후 로그 미출력)
  - 수정해야 할 부분 (승인 후 진행):
    1. 방안 A: `_load_positions()`에 trades 이력 교차 검증 추가 (재발 방지)
    2. shutdown 시퀀스 보완: SIGTERM 대기 시간 2초→5초 연장
- **체결지연 50ms 초과 WARNING 7건** (2026-07-08 13:26~ 런타임 기동 중 발생)
  - `trading_2026-07-08.log:9597~9609` — 50~143ms 지연 7건 (200ms 초과 없음)
  - 조사 필요: `_handle_real_01_tick` await 체인 프로파일링, 지연 발생 위치 식별

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

## 개선 필요 영역 — 테스트 커버리지

### 현재 커버리지: 14% (13,833줄 중 1,981줄 커버)

### 고커버리지 영역 (유지)
- `sector_score.py` 100%, `models.py` 100%, `settings_defaults.py` 100%
- `sector_calculator.py` 97%, `sector_filter.py` 96%
- `test_dry_run_fill_event.py` 95%, `test_sector_calculator.py` 100%
- `database.py` 88%, `engine_state.py` 82%, `trade_mode.py` 79%
- `settings_file.py` 70%, `engine_utils.py` 68%

### 테스트 부족 영역 (우선순위별)

#### Priority 1 — 매매 핵심 로직 (완료)
- `test_buy_filter.py` ✅, `test_circuit_breaker.py` ✅, `test_settlement_engine.py` ✅
- `test_risk_manager.py` ✅, `test_buy_order_executor.py` ✅, `test_trading.py` ✅ (hang 해결 — 커밋 `a4fa031`)

#### Priority 2 — 엔진/WS 계층 (완료)
- `test_engine_ws.py` ✅, `test_engine_ws_dispatch.py` ✅, `test_engine_ws_parsing.py` ✅
- `test_engine_ws_reg.py` ✅, `test_engine_account.py` ✅, `test_engine_account_notify.py` ✅
- `test_engine_account_rest.py` ✅, `test_engine_symbol_utils.py` ✅

#### Priority 3 — 파이프라인/스케줄러 (완료)
- `market_close_pipeline.py` (712줄, 86%) ✅
- `pipeline_compute.py` (655줄, 92%) ✅ — 배치 드레인 + 코얼레싱 + 계좌 디바운스 추가 (2026-07-06)
- `pipeline_gateway.py` (86줄, 87%) ✅
- `daily_time_scheduler.py` (601줄, 90%) ✅
- `data_manager.py` (136줄, 96%) ✅

#### Priority 4 — 브로커 커넥터 (0% 커버, 장기)
- `kiwoom_connector.py`, `kiwoom_rest.py`, `kiwoom_order.py`, `kiwoom_providers.py`, `kiwoom_stock_rest.py`
- `ls_connector.py`, `ls_rest.py`, `ls_providers.py`
- `connector_manager.py`

#### Priority 5 — Web 라우트 (0% 커버, 장기)
- `app.py`, `ws.py`, `ws_manager.py`, `settings.py`, `stock_classification.py`, `status.py`

#### Priority 6 — 유틸/기타 (0% 커버, 장기)
- `telegram.py`, `telegram_bot.py`, `trade_history.py` (회귀 테스트 2건 추가), `dry_run.py`
- `journal.py`, `logger.py`, `encryption.py`, `sector_mapping.py`
