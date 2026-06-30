# HANDOVER — SectorFlow

## 완료 단계
- 2026-06-30: 아키텍처 최적화 (커밋 `2abb184`) — ARCHITECTURE.md 섹션 27에 기록 완료
- 2026-06-30: 초저지연 아키텍처 수정안 A~D 적용 완료
- 2026-06-30: 앱 기동 시간 증가 근본 원인 분석 및 수정안 1~4 적용 완료
- 2026-06-30: 실시간 데이터 비동기화 근본 원인 분석 및 수정 완료
- 2026-06-30: 코알레싱 정리 — pipeline_gateway.py 데드 코드 제거, backend_coalescing.py import 제거(좀비 코드), ws_manager.py _state_queue/_event_queue/_flush_loop 전면 제거
- 2026-06-30: backend_coalescing.py 파일 삭제 + __pycache__ .pyc 삭제, ARCHITECTURE.md 참조 정리 (line 1119 파일트리, line 333 시작순서 제거)
- 2026-06-30: 업종지수 실시간 데이터 처리 및 헤더 표시 구현 (커밋 `af7622f`)

## 현재 상태

### 업종지수 실시간 데이터 처리 및 헤더 표시 (2026-06-30, 커밋 `af7622f`)
- **배경**: LS증권 IJ_ 데이터가 수신되어도 버려지고, 키움 0J REAL 데이터가 dispatch에서 처리되지 않으며, 프론트엔드에 지수 표시 기능이 없었음
- **수정 내역**:
  - **`broker_connector.py`**: `subscribe_index()` 추상 메서드 추가 (기본 구현: 미지원, `return False`)
  - **`ls_connector.py`**: `_convert_ls_to_internal`의 IJ_ 분기에서 `jisu`, `change`, `drate`, `sign`, `upcode`를 추출하여 0J 내부 형식으로 변환. `subscribe_index()` 메서드 추가 (KOSPI "001", KOSDAQ "101" 각각 IJ_ 구독). `connect()` 및 `_reconnect_loop()`에서 `subscribe_index()` 호출 추가
  - **`kiwoom_connector.py`**: `subscribe_index()` 메서드 추가 (기존 `build_index_reg_payload` + `_ws_send_reg_unreg_and_wait_ack` 방식)
  - **`engine_ws_reg.py`**: `subscribe_index_realtime()`에서 `broker_id != "kiwoom"` 하드코딩 제거 (원칙4 위반 수정). 커넥터의 `subscribe_index()` 공통 인터페이스 호출로 통일
  - **`engine_ws_dispatch.py`**: `_handle_real_0j()` 핸들러 추가 (저장 없이 즉시 `notify_index_data()` 호출). `_REAL_DISPATCH` 테이블에 `"0j"` 등록. `_handle_real` if-elif에 `0j` 분기 추가
  - **`engine_account_notify.py`**: `notify_index_data()` 함수 추가 (`index-data` 이벤트로 pass-through 브로드캐스트)
  - **`types/index.ts`**: `IndexData` 인터페이스 추가 (`upcode`, `jisu`, `change`, `drate`, `sign`)
  - **`uiStore.ts`**: `indexData` 필드 + `applyIndexData` 액션 추가
  - **`binding.ts`**: `settingsClient.onEvent('index-data', ...)` → `applyIndexData` 바인딩 추가
  - **`header.ts`**: 헤더 최우측에 코스피/코스닥 지수 칩 추가. 표시 형식: `코스피 +5% 8400` / `코스닥 -2% 970` (상승 빨강, 하락 파랑, 보합 회색)
- **검증**: TypeScript 타입 체크 통과, Vite 빌드 통과, Python 6개 모듈 임포트 통과
- **아키텍처 원칙 준수**: 원칙4 (증권사 이름 공통 기능 침투 금지) — `subscribe_index()` 공통 인터페이스로 추상화. 원칙5 (델타 전송) — 수신 시 즉시 pass-through, 저장 없음. 원칙11 (이벤트 기반 루프) — 폴링 없이 수신 시 즉시 브로드캐스트
- **남은 확인 사항**: 장중 실시간 데이터 수신 시 헤더 표시 확인 필요. LS IJ_ `upcode` 필드값이 "001"/"101"인지 실제 수신 시 확인 필요

### 코알레싱 정리 작업 (2026-06-30)
- **배경**: ws_manager.py의 _state_queue coalescing이 1인 로컬 초저지연 아키텍처에 불필요한 버퍼링 계층으로 확인됨
- **검증 결과**:
  - `trade-price` 이벤트: 코드베이스에서 발생 자체가 없는 데드 이벤트 (notify_desktop_trade_price 호출부 없음)
  - `orderbook-update` 이벤트: 매수후보 guard_pass 종목(~10종목 이하)만 0D 구독, 해지 30초 지연 → 빈도 매우 낮음
  - `broadcast_to_pages`: 큐 적재 + 즉시 전송 동시 수행 → 이중 전송 버그
- **수정 내역**:
  - **`pipeline_gateway.py`**: `_COALESCE_MS`, `_coalesce_cache`, `_should_coalesce` 함수 및 coalescing 체크 블록 제거 (데드 코드)
  - **`app.py`**: `BackendCoalescing` import 및 startup 코드 제거 (좀비 코드 — websocket_connections 항상 empty)
  - **`engine_ws_dispatch.py`**: `BackendCoalescing.add_raw_data(item)` else 블록 제거
  - **`ws_manager.py`**: `_FLUSH_INTERVAL`, `_STATE_EVENTS`, `_state_queue`, `_event_queue`, `_flush_task`, `_flush_event`, `_ensure_flush_task()`, `_flush_loop()`, `_flush()` 전면 제거. `broadcast()`를 `_send_broadcast` create_task 즉시 전송으로 통일. `broadcast_to_pages()` 큐 적재 제거 및 이중 전송 버그 수정. `close_all()`에서 `_flush_task` cancel 제거.
  - **`pipeline_gateway.py` docstring**: `_state_queue` 코알레싱 언급 제거
- **정적 검증**: py_compile 2개 파일 통과, import 검증 통과, 잔여 코드 검색 0건
- **호출부 호환성**: broadcast() 13곳, broadcast_to_pages() 2곳, close_all() 1곳 — 시그니처 변경 없음

### 실시간 데이터 비동기화 수정 (2026-06-30)
- **원인**: 업종순위 테이블과 매수후보 테이블이 같은 종목의 시세를 동시에 같은 값으로 표시하지 않는 문제
- **근본 원인 3가지**:
  1. `ws_manager.py` per-client 페이지 필터링 (`_is_code_relevant_for_page`): 활성 페이지 기준으로 `real-data` 전송을 필터링하여 두 테이블이 다른 데이터를 수신
  2. `engine_account_notify.py` `_is_relevant_code`: `positions_code_set`과 `layout_code_set`만 체크하고 buy target codes를 누락하여 매수후보-only 종목이 Path A에서 차단
  3. `pipeline_gateway.py` 코알레싱 버그: `real-data`가 100ms 내 후속 tick을 drop하지만 캐시에서 재전송하지 않아 데이터 유실
- **수정 내역**:
  - **`ws_manager.py` `broadcast` 메서드** (line 411-420): `real-data` 이벤트의 per-client 페이지 사전 필터링 제거. 모든 클라이언트가 `real-data` 수신.
  - **`ws_manager.py` `_send_realdata_encoded` 메서드** (line 321-336): per-client `active_page` 필터링 제거. FID 구독 그룹화는 유지.
  - **`engine_account_notify.py` `NotificationCache`** (line 33, 46): `buy_targets_code_set` 필드 추가 및 `clear_all`에서 초기화.
  - **`engine_account_notify.py` `_is_relevant_code`** (line 355-356): `buy_targets_code_set` 체크 추가.
  - **`engine_account_notify.py` `notify_buy_targets_update`** (line 575-577): `buy_targets_code_set` 갱신 로직 추가.
  - **`pipeline_gateway.py` `_process_broadcast`** (line 169): 코알레싱 대상에서 `real-data` 제거. 100ms 내 후속 tick drop 유실 버그 해결.
- **정적 검증**: py_compile 3개 파일 통과, npm run build 통과.
- **아키텍처 원칙 준수**: SSOT (원칙 10) — 프론트엔드 `hotStore`가 단일 소스, 백엔드는 모든 관련 데이터 전송. delta 전송 (원칙 5 워크룰) — 페이지 필터링 제거하되 FID 구독 필터링 유지.

### 이전 수정 (2026-06-30)
- **수정안 1 (tracemalloc 배치 이동)**: `app.py`에서 `start_memory_monitor()`/`stop_memory_monitor()` 제거. `daily_time_scheduler.py:562-565` `_on_ws_subscribe_end()` 내에서 start → snapshot → stop 수행. 기동 중 tracemalloc 오버헤드 제거.
- **수정안 2 (recompute 백그라운드화)**: `engine_cache.py:142-144` — `await recompute_sector_summary_now()`를 `asyncio.create_task()`로 변경. `sector_summary_ready_event`로 완료 통지 유지. 기동 경로 CPU 블로킹 제거.
- **수정안 3 (이중 순회 제거)**: `sector_data_provider.py:257-280` — `get_sector_summary_inputs()` 결과 `_inputs["all_codes"]`를 `_filtered` 마킹에 재사용. `state.master_stocks_cache.copy()` 및 재순회 제거.
- **수정안 4 (측정 범위 확대)**: `app.py:21` lifespan 시작 시 `_t_lifespan_start` 추가. `app.py:112` `engine_ready_event.set()` 시 총 기동시간 로그 추가.

## 다음 단계 (우선순위 높음)
1. **코알레싱 정리 런타임 검증 (필수)**: `SectorFlow.command`로 앱 기동 후以下 확인:
   - 앱 정상 시작 여부 (ws_manager import 에러 없는지)
   - WS 클라이언트 연결 후 이벤트 수신 정상 (sector-scores, account-update, orderbook-update 등)
   - `broadcast_to_pages` 이중 전송 버그 해결 확인 (account-update 이벤트가 1회만 수신되는지)
   - `real-data` 즉시 전송 정상 (기존과 동일하게 작동하는지)
   - 원칙 19 (런타임 검증 게이트) 준수
2. **이전 런타임 검증 (필수)**: `SectorFlow.command`로 앱 기동 후以下 확인:
   - 앱 정상 시작 여부 (lifespan 에러 없는지)
   - `[웹서버] [앱시작] lifespan 총 기동시간 -- XXXms` 로그 확인
   - `[앱시작] 준비완료 -- XXXms` 시작 시간 단축 확인 (이전 1875ms)
   - 업종 재계산 백그라운드 실행 로그 확인 (`[데이터준비] 업종순위 계산 백그라운드 실행`)
   - `sector_summary_ready_event` 대기 후 WS 정상 전송 확인
   - 원칙 19 (런타임 검증 게이트) 준수: py_compile 통과는 검증의 시작점이며 실제 실행 경로 흘려보기 필요
3. **실시간 데이터 비동기화 런타임 검증 (필수)**: 앱 기동 후以下 확인:
   - 업종순위 페이지와 매수설정 페이지를 각각 띄움 (dual layout)
   - 같은 종목의 시세가 두 테이블에서 동시에 같은 값으로 표시되는지 확인
   - `real-data` 이벤트가 모든 클라이언트에게 전송되는지 확인 (브라우저 콘솔)
   - 매수후보-only 종목 (레이아웃에 없는)의 `real-data` 수신 확인
4. 런타임 에러 발생 시 해당 파일+줄번호 보고 후 수정

## 미해결 문제
- **TODO 주석 7건**: `deps.py:16`, `ws.py:159`, `ws_orders.py:23`, `ws_settings.py:23`, `client.ts:18,29,40,66`, `risk_manager.py:64`
- **종목수 불일치**: `_apply_confirmed_to_memory`에서 새 엔트리 생성 의심 (이전 세션 조사, 우선순위 낮음)
- **`notifyPageActive`/`notifyPageInactive` 프론트엔드 호출**: `account-update` 페이지별 라우팅에 사용 중 (engine_account_notify.py:463, ws_manager.py:354). NOT dead code — 제거 금지.

## 개선 필요 영역 (ARCHITECTURE.md 기반)

### 1. 단일 종목 비중 한도 미구현
- **현상**: `risk_manager.py:64`에 TODO 주석 존재, `max_single_stock_exposure` 로직 미구현
- **위치**: `backend/app/services/risk_manager.py` — `RiskManager.check_buy_order_allowed()`
- **영향**: 단일 종목에 과도한 자금 집중 가능
- **관련 파일**: `risk_manager.py`, `account_manager.py`, `engine_state.py`

### 2. 리스크 임계치 하드코딩
- **현상**: `max_daily_loss_limit = -500000`, `max_total_exposure_ratio = 0.95` 등이 하드코딩
- **위치**: `backend/app/services/risk_manager.py` — `RiskManager.__init__()`
- **영향**: 사용자가 리스크 한도를 설정 UI에서 변경 불가
- **관련 파일**: `risk_manager.py`, `settings_defaults.py`, `settings_store.py`, `engine_settings.py`

### 3. 다중 증권사 WS 동시 구독 로드밸런싱
- **현상**: `ConnectorManager`로 다중 증권사 WS 연결은 지원되나, 구독 분산 최적화 미구현
- **위치**: `backend/app/core/connector_manager.py`, `backend/app/services/engine_ws_reg.py`
- **영향**: 종목 구독이 단일 증권사에 집중 시 WS 세션 한도 도달 가능
- **관련 파일**: `connector_manager.py`, `engine_ws_reg.py`, `kiwoom_connector.py`, `ls_connector.py`

### 4. 프론트엔드 프레임워크 검토
- **현상**: Vanilla TypeScript로 구현, 컴포넌트 재사용성 및 상태관리 한계
- **위치**: `frontend/src/` 전체
- **영향**: 페이지 간 공통 로직 중복, 상태 동기화 복잡도 증가
- **관련 파일**: `frontend/src/binding.ts`, `frontend/src/stores/`, `frontend/src/pages/`

### 5. 백업/복구 자동화
- **현상**: `stocks.db` 수동 백업만 가능, 자동 백업 스크립트 없음
- **위치**: `backend/data/stocks.db` (단일 파일)
- **영향**: DB 손상 시 복구 불가
- **관련 파일**: `SectorFlow.command`, `backend/app/db/database.py`

### 6. 테스트 자동화 부재
- **현상**: 수동 테스트만 수행, pytest 기반 단위/통합 테스트 없음
- **위치**: `backend/` 전체 (테스트 디렉토리 없음)
- **영향**: 코드 변경 시 회귀 위험, 안전장치 검증 불가
- **관련 파일**: `backend/app/domain/`, `backend/app/services/risk_manager.py`, `backend/app/services/settlement_engine.py`
