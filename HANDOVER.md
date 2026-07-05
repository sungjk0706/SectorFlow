# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-06: WS 구독 분산 최적화 — sender 파라미터 라우팅 수정**
  - `engine_ws.py`: `_ws_send_reg_unreg_and_wait_ack`, `_ws_send_remove_fire_and_forget`에 `sender` 파라미터 추가
  - `kiwoom_connector.py`: 5개 메서드에서 `sender=self` 전달
  - `connector_manager.py`: `subscribe_stocks` 나머지 유실 수정, `supports_ack` 추가
  - `engine_ws_reg.py`: `_unreg_grp`, `subscribe_account_realtime`에서 kiwoom 커넥터 직접 조회
  - `market_close_pipeline.py`: `remove_krx_only_stocks`에서 kiwoom 커넥터 직접 조회 후 sender 전달
  - `daily_time_scheduler.py`: `_do_unreg_all`에서 `ws.broker_id` 체크 대신 kiwoom 커넥터 직접 조회
  - 테스트: `test_market_close_pipeline.py`, `test_daily_time_scheduler.py` mock 패턴 업데이트
- **2026-07-06: 테스트 hang 자동 감지 원칙 수립**
  - HANDOVER.md 섹션 2 강화: 10초마다 자동 체크, hang 시 즉시 강제 종료, 원인 자동 분석
  - 메모리 "SectorFlow 문제해결 참고서" 동기화

## 현재 상태
- **백엔드**: `pytest backend/tests/` 1016 passed, 13 warnings in 8.32s
- **프론트엔드**: vitest 109 passed, tsc 0 errors, eslint 0 errors (직전 세션 기준)
- **Git**: 미커밋 — WS 구독 분산 수정분 + 테스트 수정분 + HANDOVER.md 업데이트

## 다음 단계
- **Git 커밋**: WS 구독 분산 수정분 + 테스트 수정분 + HANDOVER.md
- **브라우저 런타임 검증 (대기)**: 테스트모드 매수/매도 시 체결가 로그에서 슬리피지 적용 확인
- **테스트 커버리지 개선**: Priority 4 이상 진행

## 미해결 문제
- **백엔드 테스트 워닝 15개 (기능 영향 없음, 테스트 코드 원인)**
  - 모두 `RuntimeWarning: coroutine '...' was never awaited` 계열 — 테스트에서 async 함수 호출 후 coroutine이 await되지 않고 GC됨
  - **A. `AsyncMockMixin._execute_mock_call` (7개)**: `test_pipeline_compute` 1, `test_pipeline_gateway` 4, `test_risk_manager` 1, `test_trading` 1 — AsyncMock 호출 결과 coroutine이 await되지 않음 (mock 설정 이슈)
  - **B. `test_daily_time_scheduler` 특정 코루틴 (6개)**: `_do_unified_confirmed_fetch`, `_broadcast`, `_on_ws_subscribe_end`, `_on_confirmed_download`, `_ws_disconnect_only`, `_login_post_pipeline` — fire-and-forget 패턴의 async 함수가 테스트 종료 시 미처리 상태로 GC
  - **C. `test_pipeline_compute` 루프 코루틴 (2개)**: `_compute_loop_impl`, `_sector_recompute_loop_impl` — 백그라운드 루프 코루틴이 테스트 종료 시 미처리
  - **영향도**: 프로덕션 코드에 영향 없음. 테스트 mock/이벤트 루프 정리 시점 문제. 필요 시 각 테스트에서 coroutine 정리(cleanup) 추가로 해결 가능

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
- `test_risk_manager.py` ✅, `test_buy_order_executor.py` ✅, `test_trading.py` ✅

#### Priority 2 — 엔진/WS 계층 (완료)
- `test_engine_ws.py` ✅, `test_engine_ws_dispatch.py` ✅, `test_engine_ws_parsing.py` ✅
- `test_engine_ws_reg.py` ✅, `test_engine_account.py` ✅, `test_engine_account_notify.py` ✅
- `test_engine_account_rest.py` ✅, `test_engine_symbol_utils.py` ✅

#### Priority 3 — 파이프라인/스케줄러 (완료)
- `market_close_pipeline.py` (712줄, 86%) ✅
- `pipeline_compute.py` (344줄, 92%) ✅
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
- `telegram.py`, `telegram_bot.py`, `trade_history.py`, `dry_run.py`
- `journal.py`, `logger.py`, `encryption.py`, `sector_mapping.py`
