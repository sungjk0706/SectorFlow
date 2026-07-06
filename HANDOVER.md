# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-06: WebSocket 예외 Traceback 중복 출력 제거 (SSOT 부합)**
  - 문제: `TimeoutError` 1개당 최대 12개 Traceback이 출력되는 로그 폭발 현상
  - 원인: `LsConnector.connect()`가 예외를 잡아 `exc_info=True` 로그 + `raise` 재전파를 동시에 수행 → `ConnectorManager`에서 2차 Traceback 출력. 재연결 루프도 매 시도마다 `exc_info=True`로 10개 Traceback 추가 생성. 최종 실패 지점은 오히려 `exc_info` 누락
  - 해결: `ls_connector.py` 3개 지점 + `kiwoom_connector.py` 3개 지점 수정
    - 초기 연결 실패: `exc_info=True` 제거 (ConnectorManager에서 Traceback 출력)
    - 재연결 루프 실패: `exc_info=True` 제거 (일시적 재시도는 WARNING 메시지만)
    - 최종 실패(10/10 초과): `exc_info=True` 추가 (디버깅 정보 필요)
  - 검증: `py_compile` 양 파일 성공, grep으로 6개 수정 지점 정상 적용 확인
  - 효과: 총 Traceback 수 최대 12개 → 2개 (83% 감소)

## 현재 상태
- **백엔드**: 989 passed (test_trading.py 제외, 사전 존재 hang). WebSocket Traceback 중복 출력 수정 커밋 완료
- **프론트엔드**: `npm run build` 성공 (tsc 0 errors, vite 53 modules)
- **Git**: `9300ab8` 커밋 푸시 완료 (fix: WebSocket 예외 Traceback 중복 출력 제거)
- **런타임**: 앱 기동 후 LS WebSocket 연결 성공 (최대 3회 시도), 업종순위 페이지 데이터 표시 확인됨. 단, **됐다 안됐다 하는 간헐적 현상 존재**

## 다음 단계
- **test_trading.py hang 해결**: `test_rebuy_block_disabled` — 사전 존재 이슈
- **테스트 커버리지 개선**: Priority 4 이상 진행

## 미해결 문제
- **LS증권 WebSocket 간헐적 연결/데이터 수신 불안정**: 기동 시마다 연결 타임아웃(10초) 1~2회 발생 후 성공하는 현상. `open_timeout=10`은 LS 서버 핸드셰이크에 충분한 시간 (키움증권도 동일값 사용). TimeoutError 자체는 일시적 서버/네트워크 문제. 데이터 수신이 됐다 안됐다 하는 현상 관찰됨 — 추후 면밀 조사 필요 (재연결 시 `_trigger_reg_pipeline()` 누락, 핸드셰이크 타이밍, 구독 등록 시점 등)
- **test_trading.py hang**: `TestExecuteBuyGates::test_rebuy_block_disabled` — `execute_buy` 내 `await` 호출 중 mock 누락 추정. 25개 테스트 파일 중 유일한 hang

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
- `test_risk_manager.py` ✅, `test_buy_order_executor.py` ✅, `test_trading.py` ⚠️ HANG (`test_rebuy_block_disabled` — 사전 존재 이슈, `pipeline_compute.py`와 무관)

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
- `telegram.py`, `telegram_bot.py`, `trade_history.py`, `dry_run.py`
- `journal.py`, `logger.py`, `encryption.py`, `sector_mapping.py`
