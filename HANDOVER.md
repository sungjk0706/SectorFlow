# HANDOVER — SectorFlow

## 완료 단계

### 1. 토큰 폐기 로그 누락 버그 수정 (완료)
- **파일**: `backend/app/services/engine_loop.py` (line 53, 73)
- **원인**: `asyncio.to_thread(auth_provider.get_access_token)` — `async def` 함수를 `to_thread`로 호출하면 코루틴 객체만 반환되고 실제 실행 안 됨
- **수정**: `await auth_provider.get_access_token()` 직접 await 호출로 변경
- **docstring 정정**: "동기 토큰 발급" → "async def, httpx.AsyncClient 비동기 HTTP"
- **검증**: py_compile 성공, 런타임 로그에서 `[LS증권REST] 토큰 발급 성공` + `[LS증권REST] 토큰 폐기 예외` 확인 (폐기 호출 정상, ConnectTimeout은 주말/네트워크 문제)

### 2. 키움/LS 토큰 폐기 메서드 추가 (완료)
- **파일**: `backend/app/core/kiwoom_rest.py` (line 58-60, 284-313) — `REVOKE_URL` 상수 + `revoke_token()` 메서드
- **파일**: `backend/app/core/ls_rest.py` (line 47-49, 180-210) — `REVOKE_URL` 상수 + `revoke_token()` 메서드
- **폐기 API 스펙**: 키움 `https://api.kiwoom.com/oauth2/revoke` (JSON), LS `https://openapi.ls-sec.co.kr:8080/oauth2/revoke` (form-urlencoded)

### 3. Graceful Shutdown — WS 단절 기반 자동 종료 (완료)
- **파일**: `backend/app/services/engine_state.py` (line 24-25) — `shutdown_requested` 플래그 추가
- **파일**: `backend/app/web/ws_manager.py` (line 146-157, 462-474) — WS 전체 클라이언트 단절 시 타이머 예약 → 재연결 없으면 SIGTERM 전송
- **파일**: `backend/app/web/app.py` (line 124-128) — lifespan shutdown 첫 단계에 `ws_manager.close_all()` 배선 (EPIPE 방지)
- **파일**: `backend/app/web/ws_manager.py` (line 480-484) — `close_all()` 내 `_flush_task` 취소 로직 추가
- **파일**: `backend/app/services/engine_loop.py` (line 388-409) — `stop_engine()` 내 토큰 폐기 호출 + `broker_tokens.clear()`
- **제거**: `/api/shutdown` 엔드포인트 (dead code — 프론트엔드 호출 0건, 원칙 16 위반)
- **검증**: py_compile 성공, 런타임 로그에서 WS 단절 → SIGTERM → stop_engine() → 토큰 폐기 확인

### 4. 토큰 발급 지연이 프론트엔드 데이터 표시를 차단하는 버그 수정 (완료)
- **파일**: `backend/app/services/engine_loop.py` (line 201-212)
- **원인**: `_get_all_tokens_async(router)`와 `_cache_and_bootstrap(settings)`가 순차 실행 — LS 토큰 발급 실패 시 ~60s 블로킹이 `data_ready_event.set()`을 지연, 프론트엔드 초기 스냅샷 전송 차단
- **수정**: `asyncio.gather(_cache_and_bootstrap(settings), _get_all_tokens_async(router))` 병렬 실행 — 토큰 발급 지연과 무관하게 DB 기반 데이터 즉시 표시
- **`restore_state()` 순서**: `init()`이 `_cache_and_bootstrap` 내부에서 먼저 실행 → `restore_state()`가 DB 저장값으로 override (기존보다 더 올바른 순서)
- **검증**: py_compile 성공

### 5. 의존성 대기 로직 최적화 (완료)
- **파일**: `backend/app/services/engine_bootstrap.py` (line 150-158, 158-162)
  - **원인**: `_st._rest_api` 참조가 `EngineState`에 존재하지 않는 속성(`rest_api` 없음, `kiwoom_rest_api`/`ls_rest_api`만 존재) → `AttributeError` 발생 → `except Exception`에서 catch → 후속 로직(REST 잔고 조회, stale cleanup, WS 구독 등록) 전체 스킵
  - **수정**: 폴링 루프 2곳 제거. `_login_post_pipeline` 호출 시점에는 `state.kiwoom_rest_api`가 이미 설정됨 (`engine_loop.py:241`에서 gather 완료 후 설정)
- **파일**: `backend/app/services/engine_ws.py` (line 43, 56)
  - **수정**: 실패 경로(전송 실패, 타임아웃)의 `asyncio.sleep(REG_POST_ACK_GAP_SEC)` 제거. 성공 경로(line 58)는 Kiwoom WS rate-limit을 위해 유지
- **파일**: `backend/app/services/market_close_pipeline.py` (line 860)
  - **수정**: Step 2 완료 후 UI 진행률 표시용 `asyncio.sleep(1.5)` 제거
- **검증**: py_compile 3개 파일 통과, import 검증 통과, `_st._rest_api` 잔여 참조 0건 확인

### 6. 불필요한 의존성 및 폴링 대기 최적화 (완료)
- **파일**: `backend/app/services/engine_loop.py` (line 201-209)
  - **원인**: `_load_broker_spec_async`가 `asyncio.gather` 전에 순차 실행 — 캐시 로드, 토큰 발급과 독립적이지만 병렬 실행되지 않음
  - **수정**: `_load_broker_spec_async`를 gather에 포함하여 3개 파이프라인 병렬 실행
- **파일**: `backend/app/services/engine_bootstrap.py` (line 102-105)
  - **원인**: `notify_desktop_sector_stocks_refresh`와 `notify_buy_targets_update`가 순차 await — 독립적인 WS 브로드캐스트이므로 병렬 가능
  - **수정**: `asyncio.gather`로 병렬 실행
- **파일**: `backend/app/pipelines/pipeline_compute.py` (line 24, 100-101, 513-557)
  - **원인**: Phase 1 수신율 대기 루프가 `while + asyncio.sleep(0.1/1.0)` 폴링 패턴 — 아키텍처 원칙 "폴링 금지" 위반
  - **수정**: `_receive_rate_event: asyncio.Event` 추가. 틱 수신 시 `_receive_rate_event.set()`으로 깨움. `asyncio.wait_for(event.wait(), timeout=1.0)` 기반으로 전환. `asyncio.sleep` 5건 제거
- **검증**: py_compile 3개 파일 통과, engine_loop + engine_bootstrap import 통과 (pipeline_compute는 queue 초기화 순서로 기존과 동일)

### 7. Frontend-First 기동 시퀀스 개선 (완료)
- **파일**: `SectorFlow.command` (line 27-61)
  - **원인**: 백엔드 완전 기동 후 프론트엔드 시작 — 순차 대기로 ~1-2초 낭비
  - **수정**: 백엔드/프론트엔드 병렬 시작, 0.5초 간격 양쪽 동시 폴링
- **파일**: `frontend/src/main.ts` (line 212-245)
  - **원인**: Health Check 지수 백오프(500ms~16s) — localhost에 불필요한 긴 대기
  - **수정**: 300ms 고정 간격 폴링, `initializing` 상태도 서버 응답으로 간주하여 즉시 WS 연결
- **파일**: `backend/app/web/app.py` (line 85-116)
  - **원인**: lifespan이 `await start_engine()`에 블로킹 — 엔진 초기화 완료 전까지 Health endpoint 응답 불가
  - **수정**: `server_ready_event`를 yield 전 설정하여 Health endpoint 즉시 응답, `start_engine()` + coalescing + scheduler + telegram을 백그라운드 태스크로 이동. WS 핸들러가 `data_ready_event`/`bootstrap_event` 대기 후 스냅샷 전송하므로 엔진 초기화 전 프론트엔드 접속 안전
- **검증**: py_compile 성공, tsc --noEmit 성공, npm run build 성공, 런타임 로그 확인 (병렬 기동·Health 즉시 응답·WS 3채널 즉시 연결)

### 8. 업종 요약정보 생성 대기 해제 누락 수정 (완료)
- **파일**: `backend/app/services/sector_data_provider.py` (line 281, 284)
- **원인**: `recompute_sector_summary_now()`가 `_sector_summary_cache` 계산 후 `_sector_summary_ready_event.set()`을 호출하지 않음. 기존 `_deferred_sector_summary()`에서 의도적으로 제거(line 90 주석)하고 `engine_sector_confirm`로 위임했으나, `engine_sector_confirm.py:217`의 `set()`은 실시간 틱 수신 시에만 호출됨 — 비거래 시간 기동 시 영원히 대기
- **수정**: `recompute_sector_summary_now()` 정상 완료 후(line 281) 및 예외 시(line 284) `_es._sector_summary_ready_event.set()` 추가. 이 함수는 기동 시(`engine_cache.py:132`)와 설정 변경 시(`engine_service.py:426`)의 공통 경로이므로 단일 수정으로 모든 케이스 해결
- **검증**: py_compile 성공, 런타임 로그에서 WS 접속 시 `업종 요약정보 생성 대기 중` 미출력 (이벤트 이미 설정됨), 3개 WS 채널 즉시 연결 확인

### 9. 기동 시퀀스 추가 최적화 (완료)
- **파일**: `SectorFlow.command` (line 15-32, 42)
  - **원인**: `sleep 2` 고정 대기 — 이전 프로세스가 없어도 무조건 2초 대기
  - **수정**: 이전 프로세스 존재 시에만 `kill -0` 폴링으로 최대 2초 대기, 없으면 즉시 진행 (~2초 절감)
  - **원인**: `npx vite` — npx가 매번 vite 바이너리 탐색 (~100-200ms 오버헤드)
  - **수정**: `npm run dev`로 변경
- **파일**: `backend/app/services/engine_cache.py` (line 134-141)
  - **원인**: `retry_pipeline_catchup_after_bootstrap()`을 `await`로 블로킹 — 단절 구간 기동 시 확정 다운로드가 `_load_caches_preboot`를 블로킹
  - **수정**: `asyncio.create_task()`로 백그라운드화. `data_ready_event`/`bootstrap_event` 이미 `set()` 상태이므로 WS 핸들러 정상 동작
- **파일**: `backend/app/services/engine_loop.py` (line 155)
  - **원인**: `initialize_queues()`가 `app.py` lifespan과 `run_engine_loop`에서 중복 호출
  - **수정**: `run_engine_loop`에서 제거 (app.py에서 이미 초기화됨)
- **검증**: py_compile 성공, npm run build 성공

### 10. 잘못된 주석 수정 및 코드 묘비 주석 제거 (완료)
- **잘못된 주석 수정 (3건)**
  - `engine_bootstrap.py:55-59` — `asyncio.to_thread()`로 실행한다는 docstring → 실제는 직접 `await` 호출. `_sector_summary_ready_event.set()` 제거됨 반영
  - `sector_calculator.py:222` — `buy_widget 폴링에서 호출` → 존재하지 않는 `buy_widget` 참조 제거, 실제 호출자(engine_bootstrap, engine_sector_confirm, sector_data_provider, telegram_bot) 이벤트 기반 호출로 수정
  - `engine_snapshot.py:290-292` — `REAL 01 체결 캐시 기준 현재가` → 실제 항상 0 반환하는 스텁으로 수정
- **코드 묘비 주석 제거 (20개 파일, 65건+)**
  - 이미 삭제된 함수/변수를 참조하는 `제거:` 계열 주석 전부 제거
  - `_invalidate_sector_stocks_cache 제거`, `_pending_stock_details 제거`, `_sector_stock_layout 제거`, `get_buy_targets_snapshot 제거`, `_compute_filtered_codes 제거`, `eligible_stocks_cache 제거`, `_buy_targets_snapshot_cache 제거`, `_rest_radar_rest_once 제거`, `폴링 제거`, `실시간 틱 데이터 캐시 삭제` 등
- **백업 파일 제거**: `backend/app/services/.!56500!engine_loop.py` 삭제
- **검증**: py_compile 19개 파일 전부 통과, `제거:` 잔여 3건(정상—실제 동작 설명), `buy_widget` 잔여 0건
- **커밋**: `6116bf6` — 21 files changed, 9 insertions(+), 265 deletions(-)

### 11. Kiwoom-specific naming 제거 — 브로커 추상화 정합화 (완료)
- **함수명 일반화 (engine_ws_parsing.py)**
  - `_normalize_kiwoom_real_type` → `_normalize_real_type` (정의 + engine_ws_dispatch.py, pipeline_compute.py import)
  - `_parse_kiwoom_price_scalar` → `_parse_price_scalar` (정의 + 내부 호출처)
  - `_parse_ws_fid12_to_percent` 별칭 제거 → `parse_change_rate_to_percent` 직접 import (engine_ws_dispatch.py)
- **Facade 자기 재할당 제거 (engine_service.py)**
  - `X = X` 형태 self-reassignment 16건 제거, 이름이 다른 실제 별칭 6건만 남김
- **State 변수 일반화 (engine_state.py + 17개 파일)**
  - `state.kiwoom_connector` → `state.active_connector` (타입: `BrokerConnector | None`) — 17개 파일 호출처 전부 수정
  - `state.kiwoom_auth_provider` → `state.active_auth_provider`
  - `state.kiwoom_rest_api` / `state.ls_rest_api` → `state.broker_rest_apis: dict[str, object]` — engine_loop.py 초기화/정리 로직 dict 기반 통합, engine_account.py/kiwoom_providers.py 참조 수정
- **Docstring/comment 정리**
  - engine_service.py "KiwoomConnector" 4건 → "Connector"
  - engine_ws_parsing.py docstring "키움" 제거
  - backend_coalescing.py 주석 `kiwoom_connector` → `active_connector`
- **수정 파일 (19개)**: engine_ws_parsing.py, engine_ws_dispatch.py, pipeline_compute.py, engine_service.py, engine_state.py, engine_ws.py, engine_loop.py, engine_ws_reg.py, engine_lifecycle.py, daily_time_scheduler.py, engine_bootstrap.py, engine_sector_confirm.py, market_close_pipeline.py, ws_subscribe_control.py, engine_strategy_core.py, backend_coalescing.py, engine_account.py, kiwoom_providers.py, status.py
- **검증**: py_compile 19개 파일 전부 성공 (exit code 0), 잔여 검색 7개 항목 0건 확인

### 12. 이어받기 로직 완전 삭제 + 로그 통일 + 로거 아키텍처 수정 (완료)

#### 12-1. 이어받기 (resume download) 로직 완전 삭제
- **`kiwoom_stock_rest.py`** — `resume_codes` 파라미터, 이어받기 DB 조회 블록, `starting_count`, `downloaded_at_codes` 추적/DB 업데이트 제거
- **`market_close_pipeline.py`** — `load_progress_cache` import/호출, `resume_codes`/`starting_count` 변수, 이어받기 로그/WS 메시지 제거
- **`kiwoom_providers.py`** — `resume_codes` 파라미터 제거 (2개 함수)
- **`kiwoom_rest.py`** — `resume_codes` 파라미터 제거 (1개 함수)
- **`custom_sector.py`** — `resume_codes` 파라미터 제거 (2개 함수)
- **`stock_tables.py`** — `load_progress_cache()`, `clear_progress_cache()` 함수 삭제
- **검증**: `resume_codes`, `starting_count`, `이어받기`, `downloaded_at_codes`, `load_progress_cache`, `clear_progress_cache`, `downloaded_at` 잔여 0건 확인

#### 12-2. 백엔드 로그 통일 — 프론트엔드 UI 기준
- **태그 통일**: `[ka10081]` → `[1일봉챠트 시세 다운로드]` / `[5일봉챠트 거래대금,고가 다운로드]` (프론트엔드 버튼 텍스트와 일치)
- **진행률 로그**: 매 종목 `_log.info` 출력 (프론트엔드 헤더 인디케이터와 동일 단위)
- **WS 메시지**: 5일봉에 "거래대금,고가" 추가, ✅ 제거, 완료 메시지 포맷 1일봉과 통일
- **매 종목 INFO 로그 제거 후 복구**: 10% 단위 → 매 종목으로 변경 (개발 단계 일관성 우선)
- **수정 파일**: `kiwoom_stock_rest.py`, `market_close_pipeline.py`

#### 12-3. 로거 아키텍처 수정 — 주석/코드 불일치 해결 + trading_debug.log 제거
- **`logger.py`** — `trading.log` 싱크 레벨 `WARNING` → `INFO` (주석에 "INFO 이상"으로 명시되어 있었으나 코드만 WARNING)
- **`trading_debug.log` 싱크 제거** — `_debug_file_queue`, `_debug_file_sink`, 데몬 스레드 t2 삭제. 3채널 → 2채널(콘솔 + trading.log) 단순화
- **`trading.log` 싱크 레벨** — `level="INFO"` → `level=log_level` (설정 기반, `LOG_LEVEL=DEBUG` 시 DEBUG 로그도 trading.log에 기록)
- **보관일/로테이션 주석 정정** — trading.log 1일→2일, trading_debug.log 0일→1일, 50MB→10MB (실제 `_MAX_FILE_SIZE`와 일치)
- **검증**: py_compile 성공, `trading_debug_*` 파일 삭제

### 13. LS StockProvider 비동기 구현 1차 배선 (완료)
- **`ls_rest.py`** — 기존 `call_api()` 계약 유지, TR 전용 `call_tr()` 추가. `tr_cd`, `tr_cont`, `tr_cont_key` 헤더를 전송하고 응답 body/header/연속조회 키를 반환
- **`ls_stock_rest.py`** — 신규 파일. `t8436` 전체 종목, `t1404/t1405/t1410/t1411` 부적격 종목 집합, `t8451` 1일봉/5일봉 조회 함수 구현. LS 계정 단위 1 TPS 준수를 위해 per-stock 호출은 `max(interval_sec, 1.0)`로 순차 실행
- **`ls_providers.py`** — `LsStockProvider` 추가. `KiwoomStockProvider`와 동일한 5개 stock 메서드 제공, `_run_async()` 미사용
- **`broker_registry.py`** — LS 레지스트리에 `"stock": LsStockProvider` 등록
- **`stock_filter.py`** — `listCount` 빈 값은 통과, 명시적 비정상 값(`0` 등)은 제외 유지. `lastPrice` 빈 값 제외는 유지
- **검증**: `py_compile` 성공 (`ls_rest.py`, `ls_stock_rest.py`, `ls_providers.py`, `broker_registry.py`, `stock_filter.py`), 스모크 검증 성공 (`listCount=""` + `lastPrice="1000"` 통과, `listCount="0"` 제외, `_create_provider("stock", "ls", ...)`가 `LsStockProvider` 생성)

### 14. 확정시세 다운로드 증권사 분리 — 하이브리드 아키텍처 보정 (완료)
- **설정 분리**: `broker`는 실시간/계좌/주문용 주 사용 증권사로 유지, `confirmed_data_broker`는 장마감 전종목 목록·매매부적격 필터링·1일봉/5일봉 챠트 시세 다운로드 전용으로 추가
- **`settings_defaults.py`** — `confirmed_data_broker: "kiwoom"` 기본값 추가
- **`settings_store.py`** — `broker`, `confirmed_data_broker` 모두 레지스트리 기반 허용 증권사 검증
- **`engine_settings.py`** — `confirmed_data_broker`를 엔진 설정에 포함하고 `broker_config.stock`만 `confirmed_data_broker`를 사용하도록 분리. `websocket/order/account/sector/auth`는 기존 `broker` 유지
- **`engine_service.py`** — `confirmed_data_broker` 변경 시 엔진 재기동 없음. 설정 캐시 갱신 + UI 알림만 수행
- **`market_close_pipeline.py`** — 1일봉/5일봉 장마감 파이프라인의 stock/auth provider 선택을 `broker_config.stock → confirmed_data_broker → broker` 순으로 변경
- **`general-settings.ts`** — API 설정 탭의 `확정 시세 다운로드` 시간 설정 아래 `다운로드 증권사` 라디오 추가. 주 사용 증권사와 별도 저장/동기화
- **`types/index.ts`** — `AppSettings.confirmed_data_broker` 추가
- **검증**: Python `py_compile` 성공, frontend `npm run build` 성공, 스모크 검증 성공 (`broker=kiwoom`, `confirmed_data_broker=ls`일 때 `broker_config.websocket/order/account=kiwoom`, `broker_config.stock=ls`, stock provider=`LsStockProvider`)

### 15. JIF 기반 Market Phase 전환 — Fallback 제거 (완료)
- **배경**: 시간 기반 `is_nxt_only_window()` → JIF 기반 `state.market_phase` SSOT 읽기로 전환
- **`daily_time_scheduler.py`**:
  - `is_nxt_only_window()` (65-76행): `state.market_phase` (JIF 수신값) 직접 읽기. 빈 값 시 False 반환 — JIF 미수신 = WS 미연결 = 시세 없음 → 필터링 의미 없음
  - `get_market_phase()` (112-126행): 순수 읽기 함수. `state.market_phase` 복사본 반환, 쓰기 부작용 없음
  - `_calc_timebased_phase()` 제거: 시간 기반 장 상태 계산 함수 삭제
  - `_ensure_market_phase()` 제거: fallback 주입 함수 삭제
  - 타이머 콜백 5곳: `_ensure_market_phase()` 호출 제거 (09:00, 15:30, _broadcast_market_phase, _on_ws_subscribe_start, 구독 구간 내 시작)
- **`engine_snapshot.py`**: `_ensure_market_phase` import 및 호출 제거
- **아키텍처 원칙**: `state.market_phase`는 오직 `_handle_jif()` (JIF 수신)로만 채워짐 — SSOT 순수성 확보
- **검증**: py_compile 3개 파일 통과, tsc --noEmit 통과, `_ensure_market_phase`/`_calc_timebased_phase` 잔여 0건

### 16. LS 전종목 다운로드 — 키움 일관성 확보 (방안 B 근본 해결) (완료)
- **배경**: LS 다운로드가 t1404 완료 후 t1405~ 진행 중 "멈춤"으로 인식. 조사 결과 실제 멈춤이 아닌 42회 순차 API 호출 + asyncio.sleep(1.0) + 429 재시도로 인한 지연. 근본 원인은 LS만 Step 1에서 사전필터링 수행, 키움은 Step 2에 필터링 위임 — 아키텍처 불일치
- **`ls_stock_rest.py`**:
  - fetcher 반환형 `set[str]` → `dict[str, list[str]]` (code → state 라벨 목록)
  - `_T1404_LABELS`, `_T1405_LABELS` 상수 추가 (jongchk → 한국어 라벨 매핑)
  - t1404 jongchk에 "4"(투자환기) 추가 — 명세서에 있으나 누락되어 있었음
  - 각 fetcher gubun/jongchk 조합마다 진행 로그 추가 (`[LS부적격목록] t1404 gubun=0 jongchk=1(관리종목) — N종목`)
  - `fetch_ls_ineligible_codes` 반환형 `set[str]` → `dict[str, list[str]]`, 각 fetcher 시작/완료 로그 추가
  - `fetch_ls_all_stocks_unified` 사전필터링 제거 → 대신 t1404/t1405/t1410/t1411 결과를 `raw_item["state"]`에 `|` 구분자로 주입. 전종목을 그대로 반환하여 Step 2 `evaluate_stock_filter`가 필터링 수행
- **`stock_filter.py`**:
  - `_BLOCKED_STATE_KEYWORDS`에 7개 키워드 추가: `투자유의`, `투자주의`, `투자환기`, `위험예고`, `초저유동성`, `이상급등`, `상장주식수부족`
  - 키움에도 영향: ka10099 state에上述 키워드 포함 시 기존 통과 → 변경 후 차단
- **검증**: py_compile 2개 파일 성공, grep 잔여 검색 — `fetch_ls_ineligible_codes`/`fetch_ls_t14XX_codes` 참조가 `ls_stock_rest.py` 내부에만 존재, `fetch_ls_all_stocks_unified` 반환형 `list[UnifiedStockRecord]` 유지로 `ls_providers.py` 영향 없음
- **런타임 검증 필요**: LS 다운로드 시 Step 1 완료 → Step 2 `evaluate_stock_filter` 정상 동작, 키움 다운로드 시 추가 차단 종목 발생 여부

### 17. t1411 파라미터 수정 — 증거금 40%/100% 필터링 (완료)
- **파일**: `backend/app/core/ls_stock_rest.py` (line 245-263), `backend/app/core/stock_filter.py` (line 42-62)
- **수정**: `jkrate` "100"→"1"(100%), "5"(40%) 루프 추가, `jongchk` "0"→"1", `idx` "0"→0(integer), `_T1411_JKRATE_LABELS` 상수 추가, `_BLOCKED_STATE_KEYWORDS`에 "증거금40%" 추가
- **검증**: py_compile 성공

### 18. t8436 etfgubun → marketCode 매핑 — ETF/ETN 필터링 (완료)
- **파일**: `backend/app/core/ls_stock_rest.py` (line 96-107)
- **수정**: `_market_code()`에 `etfgubun` 체크 추가 — "1"→"8"(ETF), "2"→"60"(ETN), 일반은 기존 gubun 매핑 유지
- **검증**: py_compile 성공

### 19. _call_pages idx 타입 보존 — t1411 연속조회 integer 유지 (완료)
- **파일**: `backend/app/core/ls_stock_rest.py` (line 148-160)
- **수정**: `isinstance(cts_raw, str)`으로 타입 판별 — string은 `_s()` 변환, number는 원본 유지
- **검증**: py_compile 성공

### 20. t8436 spac_gubun 필드 기반 SPAC 필터링 (완료)
- **파일**: `backend/app/core/ls_stock_rest.py` (line 187-188)
- **수정**: `spac_gubun="Y"`이고 종목명에 "스팩" 없으면 종목명에 "스팩" 추가 → `stock_filter.py`에서 자동 차단
- **검증**: py_compile 성공

### 21. LS증권 API 매매 부적격 필터링 전면 조사 (완료 — 보고만)
- **조사 출처**: GitHub `xorrhks0216/LsApiHelper` specs + 로컬 명세서
- **매매 부적격 TR 5개**: t1404(관리/불성실/투자유의/투자환기), t1405(투자경고/매매정지/정리매매 등 9종), t1410(초저유동성), t1411(증거금40%/100%), t8436(etfgubun/spac_gubun/gubun)
- **미활용**: t8436 `bu12gubun`(증권그룹) — 값 매핑 문서 없어 추가 조사 필요
- **추가 발견**: t1403(신규상장종목조회) — LS 전환 시 regDay 대체 가능

### 22. LS증권 API TPS 테스트 및 다운로드 속도 개선 (완료)

#### 22-1. LS증권 API TPS 제한 테스트 (조사 → 테스트 → 검증)
- **배경**: LS 다운로드 속도 저하 원인 조사 중 "계정 단위 1 TPS" 가정 확인 필요 — 명세서에는 TR별로 TPS 명시
- **테스트 스크립트**: `backend/tests/test_ls_tps.py` (테스트 완료 후 삭제)
- **테스트 결과**:
  | 테스트 | 내용 | 결과 | 판정 |
  |--------|------|------|------|
  | Test 1 | t8451 무딜레이 2회 | 1차 성공, 2차 실패 (IGW00201) | TR별 1 TPS 확정 |
  | Test 2 | t8436 무딜레이 2회 | 모두 성공 | t8436은 2 TPS 확정 |
  | Test 3 | t8451 → t8436 교차 무딜레이 | 모두 성공 | TR별 독립 TPS 확정 |
  | Test 4 | t8451 + t8436 병렬 (gather) | 모두 성공 | 병렬 호출 가능 (이전 "HTTP 500"은 같은 TR 병렬이었음) |
  | Test 5 | t8451 0.5s 간격 3회 | 3번째 실패 | 1초에 2건까지만 허용 |
  | Test 6 | t8451 0.3s 간격 3회 | 2번째 실패 | 1초에 2건까지만 허용 |
- **핵심 결론**: LS증권 API TPS는 **TR별로 독립 적용** (계정 단위 아님)
  - t8451/t8410 = 1 TPS, t8436 = 2 TPS, 주문 = 10 TPS
  - 서로 다른 TR은 동시/교차 호출 가능
  - 같은 TR 1 TPS 위반 시 `IGW00201 "호출 거래건수를 초과하였습니다"` 반환

#### 22-2. Step 1: 부적격목록 4개 TR 동시 실행 (`ls_stock_rest.py:275-291`)
- **기존**: t1404 → t1405 → t1410 → t1411 순차 실행, 각 호출 후 `asyncio.sleep(1.0)`
- **변경**: `asyncio.gather`로 4개 TR 동시 실행 (`return_exceptions=True`)
- **효과**: ~44s → ~26s (가장 긴 t1405의 27회 호출 × 1.0s 기준)

#### 22-3. Step 5: t8451/t8410 교차 호출 (`ls_stock_rest.py:477-507`)
- **기존**: t8451만 사용, `gap = max(interval_sec, 1.0)` = 1.0s/종목
- **변경**: 홀수 idx → t8451, 짝수 idx → t8410 교차 호출, `gap = max(interval_sec, 0.5)` = 0.5s/종목
- **추가 함수**: `fetch_ls_daily_price_t8410` (t8410 기반 1일봉 조회)
- **효과**: ~21.7분 → ~10.8분 (약 1300종목 기준)

#### 22-4. 5일봉 조회 동일 적용 (`ls_stock_rest.py:510-540`)
- **기존**: t8451만 사용, `gap = max(interval_sec, 1.0)`
- **변경**: t8451/t8410 교차 호출, `gap = max(interval_sec, 0.5)`
- **추가 함수**: `fetch_ls_stock_5day_data_t8410` (t8410 기반 5일봉 조회)

#### 22-5. ETA 계산 수정 (`market_close_pipeline.py:1011`)
- `eta_sec` 계산을 `(total - cur) * 1.0`에서 `(total - cur) * 0.5`로 변경

#### 예상 소요 시간 비교 (약 1300종목 기준)
| 단계 | 기존 | 변경 후 |
|------|------|---------|
| Step 1 (부적격목록) | ~44s | ~26s |
| Step 5 (1일봉) | ~21.7분 | ~10.8분 |
| **총합** | **~22.5분** | **~11.5분** |

- **검증**: py_compile 3개 파일 통과 (`ls_stock_rest.py`, `market_close_pipeline.py`, `ls_providers.py`), import 검증 통과
- **테스트 스크립트 삭제**: `backend/tests/test_ls_tps.py` 테스트 완료 후 삭제

## 현재 상태
- **LS 다운로드 속도 개선 완료** — TR별 독립 TPS 기반 교차 호출 + 동시 실행으로 ~22.5분 → ~11.5분 단축
- **LS 매매 부적격 필터링 1차 완성** — t1404/t1405/t1410/t1411 4개 부적격 TR + t8436 etfgubun/spac_gubun 필드 매핑, py_compile 검증 통과
- t1411 파라미터 수정 완료 — jkrate "5"(40%)+"1"(100%) 루프, jongchk "1", idx integer, 연속조회 idx 타입 보존
- t8436 etfgubun → marketCode "8"(ETF)/"60"(ETN) 매핑 완료
- t8436 spac_gubun="Y" → 종목명 "스팩" 주입으로 필드 기반 SPAC 필터링 완료
- _call_pages idx 타입 보존 — string 필드는 _s() 변환, number 필드는 원본 유지
- stock_filter.py _BLOCKED_STATE_KEYWORDS에 "증거금40%" 추가
- LS 전종목 다운로드 키움 일관성 확보 (방안 B) 완료 — 사전필터링 제거, raw_item state 주입으로 Step 2 통일 필터링
- JIF 기반 Market Phase 전환 완료 — Fallback 제거로 SSOT 순수성 확보
- LS StockProvider 1차 비동기 배선 및 확정시세 다운로드 증권사 분리 완료
- 모든 이전 수정 완료, py_compile + tsc + build 검증 통과
- 런타임 확인 완료: Frontend-First 기동 — 백엔드/프론트엔드 병렬 시작, Health 즉시 응답, WS 3채널 즉시 연결 (05:32 기동 로그)
- 런타임 확인 완료: 업종 요약정보 대기 해제 — `재계산 완료` 후 WS 접속 시 대기 없이 즉시 연결 (05:32 기동 로그)
- 런타임 확인 완료: 1일봉 다운로드 매 종목 로그 정상 출력 — `trading_2026-06-28.log`에서 `[1일봉챠트 시세 다운로드] 진행 중: N/1281 (pct%)` 확인 (06:45)

## 다음 단계
- **LS 다운로드 속도 개선 런타임 검증 (최우선)**:
  - Step 1 부적격목록 4개 TR 동시 실행 정상 동작 확인
  - Step 5 t8451/t8410 교차 호출 시 두 TR 모두 정상 응답 확인
  - t8410 응답 필드가 t8451과 동일한지 확인 (명세서상 동일 구조)
  - t8410은 `exchgubun` 없어 NXT 종목 누락 가능 — 확정 파이프라인은 KRX 기준이므로 영향 최소
  - 0.5s 교차 호출 시 `IGW00201` 오류 발생 여부 확인
  - 실제 소요 시간 ~11.5분 근접 확인
  - 5일봉 교차 호출 정상 동작 확인
- **LS 필터링 런타임 검증**:
  - t1411 idx integer 정상 전송, jkrate="5"/"1" 각 gubun 조합 조회 확인
  - t8436 etfgubun="1"(ETF)→"8", "2"(ETN)→"60" 매핑 차단 확인
  - t8436 spac_gubun="Y" 종목명 "스팩" 주입 차단 확인
  - Step 2 `evaluate_stock_filter`가 `raw_item["state"]`로 정상 필터링 확인
  - 키움 다운로드 시 추가 차단 종목 발생 여부
- **월요일(2026-06-30) 거래일 테스트**:
  - ka10099 state 핑퐁 여부 확인
  - 20:40 자동 vs 수동 2차 state 비교 SQL: `SELECT a.code, a.state as s1, b.state as s2 FROM stock_filter_diagnostics a JOIN stock_filter_diagnostics b ON a.code=b.code WHERE a.run_id LIKE '20260630%' AND b.run_id LIKE '20260630%' AND a.run_id < b.run_id AND a.state != b.state`
- **거래일 JIF 런타임 확인**: market_phase 정상 설정, is_nxt_only_window() 반환값, 프론트엔드 장 상태 칩 표시
- LS 실제 API 런타임 확인: confirmed_data_broker=ls 설정, t8436/t8451/t8410 필드명 확인
- 평일 기동 후 확인: REST 잔고 조회, WS 구독, 수신율 대기, 토큰 폐기, 5일봉 로그

## 미해결 문제
- **LS 다운로드 속도 개선 런타임 검증 미완료**: py_compile만 통과, 실제 파이프라인 실행 시 t8451/t8410 교차 호출 및 4개 TR 동시 실행 정상 동작 확인 필요
  - t8410 응답이 t8451과 동일한 필드 구조인지 런타임 확인 필요 (명세서상 동일 `OutBlock1` 구조)
  - t8410은 `exchgubun` 필드 없어 NXT 종목 조회 불가 — 확정 파이프라인은 KRX 기준이므로 영향 최소 예상
  - 0.5s 교차 호출 시 실제 `IGW00201` 오류 발생 여부 확인 필요
- **LS 필터링 런타임 검증 미완료**: py_compile만 통과, 실제 LS API 호출 시 t1411 idx integer 전송, etfgubun/spac_gubun 매핑, state 주입 및 Step 2 필터링 동작 확인 필요
- **키움 `_BLOCKED_STATE_KEYWORDS` 추가 키워드 영향 검증 미완료**: ka10099 state에 "투자유의"/"투자주의"/"투자환기"/"위험예고"/"초저유동성"/"이상급등"/"상장주식수부족"/"증거금40%" 포함 종목이 기존 통과 → 변경 후 차단됨. 종목수 감소 가능성
- **t8436 `bu12gubun` 미활용**: 증권그룹 코드(예: "01") — 값 매핑이 공식 문서에 없어 추가 조사 필요. 리츠/펀드 등 추가 필터링 가능성
- **WS 재연결 후 JIF 재구독 실패 시 `state.market_phase` stale 데이터 문제**: `_on_socket_disconnect`에서 `state.market_phase`를 초기화하지 않음 — 재연결 후 JIF 재구독 실패 시 이전 JIF 값이 남아 있음. 별도 수정 필요 시 승인 요청
- LS StockProvider 실제 API 필드명 검증 필요: 현재 구현은 LsApiHelper 명세 기반이며, 실계정 API 응답에서 `t8436/t8451` 필드명이 다르면 매핑 보정 필요
- LS 토큰 폐기 ConnectTimeout: 주말/비거래 시간대 LS증권 API 서버 접근 불가 — 코드 버그 아님, 거래 시간에 재확인 필요
- 종목수 1359 → 1361 불일치: 별도 조사 필요 (이전 세션 메모리 참고 — `_apply_confirmed_to_memory`에서 새 엔트리 생성 의심)
- TODO 주석 7건 (개발 완료 후 토큰 검증 재활성화 시 처리): `deps.py:16`, `ws.py:159`, `ws_orders.py:23`, `ws_settings.py:23`, `client.ts:18,29,40,66`, `risk_manager.py:64`
- 개발 완료 단계 시 매 종목 진행률 로그 축소 검토 (현재 개발 단계: 매 종목 출력, 완성 단계: 필수 로그만)
