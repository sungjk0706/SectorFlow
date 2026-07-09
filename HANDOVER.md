# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-09: 프론트엔드 더미 데이터 삭제 — DUMMY_BUY/DUMMY_SELL 제거**
  - `profit-shared.ts:411-419` — `DUMMY_BUY`, `DUMMY_SELL` 상수 삭제
  - `profit-detail.ts` — import 제거, `isDummy`/`dummyMsg` 관련 로직 제거
  - `npm run build` 통과 (tsc + vite build 성공)
  - 잔여 참조 0건 확인 (grep 검색 완료)

## 현재 상태
- **백엔드**: RiskManager 리팩토링 Phase 1 완료
- **프론트엔드**: 더미 데이터 삭제 완료, `npm run build` 통과
- **Git**: 더미 데이터 삭제 커밋 대기

## 다음 단계
- **유령 포지션 근본 원인 조사 (최우선)**:
  - 07-09 15:52에 `test_positions` 테이블에 005930(10주, avg_price=70,100)이 삽입된 경로 추적 필요
  - 더미 데이터(avg_buy_price=70,000)와 유령 포지션(avg_price=70,100)의 값 차이 확인 필요
  - `save_test_positions()` 호출 경로 전체 재추적 필요
  - 14:32 앱 종료~15:52 앱 시작 사이 DB에 직접 INSERT된 경로 식별
- **2순위: 브라우저 실제 화면 확인** — 장중에 매수후보 테이블에서 SK하이닉스(000660) 하이라이트 깜빡임 없는지 확인
- **3순위: exchange_calendars 교체 검토** — pandas(70MB)+numpy(33MB) 등 간접 의존성 약 112MB 절감 가능

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) 원인 미상**
  - 07-09 08:03 BUY 6주 → 10:53 SELL 6주(전량 매도) → 15:52 SELL 10주(유령 포지션)
  - 12:08~14:02 모든 SQLite 복원 0종목 (DB 비어 있었음)
  - 14:32 종료~15:52 시작 사이 외부에서 DB에 INSERT된 것으로 추정
  - `trades` 테이블 id=144: 15:52 SELL 10주 avg_buy=70,100 기록됨
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
