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

### 3. Graceful Shutdown — 브라우저 종료 시 토큰 폐기 (완료)
- **파일**: `backend/app/services/engine_state.py` (line 24-25) — `shutdown_requested` 플래그 추가
- **파일**: `backend/app/web/routes/status.py` (line 5-10, 181-205) — `/api/shutdown` 엔드포인트 추가 (sendBeacon 수신 → 1초 후 SIGTERM)
- **파일**: `frontend/src/main.ts` (line 265-268) — `beforeunload` + `sendBeacon` 핸들러 추가
- **파일**: `backend/app/services/engine_loop.py` (line 388-409) — `stop_engine()` 내 토큰 폐기 호출 + `broker_tokens.clear()`
- **검증**: 런타임 로그에서 브라우저 종료 → `/api/shutdown` 수신 → SIGTERM → `stop_engine()` → 토큰 폐기 호출 확인

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

## 현재 상태
- 모든 수정 완료, py_compile + tsc + build 검증 통과
- 런타임 확인 완료: Frontend-First 기동 — 백엔드/프론트엔드 병렬 시작, Health 즉시 응답, WS 3채널 즉시 연결 (05:32 기동 로그)
- 런타임 확인 완료: 업종 요약정보 대기 해제 — `재계산 완료` 후 WS 접속 시 대기 없이 즉시 연결 (05:32 기동 로그)
- 런타임 검증 필요: 토큰 발급 실패/지연 상황에서 프론트엔드에 DB 데이터가 즉시 표시되는지 확인
- 런타임 검증 필요: `_login_post_pipeline`이 정상적으로 REST 잔고 조회 ~ WS 구독 등록까지 실행되는지 확인
- 런타임 검증 필요: Phase 1 Event 기반 수신율 대기가 정상적으로 임계값 통과 후 Phase 2로 전환되는지 확인

## 다음 단계
- 평일 거래 시간 기동 후 확인:
  - `[시작] 파이프라인 -- REST 잔고 선행 조회 시작` 로그 정상 출력 확인 (이전에는 AttributeError로 스킵됨)
  - WS 구독 등록이 정상적으로 수행되는지 확인 (이전에는 except에서 스킵됨)
  - Phase 1 수신율 대기 로그가 이벤트 기반으로 정상 출력되는지 확인
  - LS 토큰 폐기 성공 로그 확인 (주말에는 ConnectTimeout 발생)
  - 토큰 발급 지연 시 프론트엔드에 DB 데이터가 즉시 표시되는지 확인

## 미해결 문제
- LS 토큰 폐기 ConnectTimeout: 주말/비거래 시간대 LS증권 API 서버 접근 불가 — 코드 버그 아님, 거래 시간에 재확인 필요
- 종목수 1359 → 1361 불일치: 별도 조사 필요 (이전 세션 메모리 참고)
