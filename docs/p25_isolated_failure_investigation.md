# SectorFlow P25 (격리된 실패) 전수 조사 보고서

> 작성일: 2026-07-23
> 기준 문서: `ARCHITECTURE.md` 제1부 P25 (불변 원칙 25개 중 25번째)
> 성격: 조사 보고서 (AGENTS.md 문서 저장 경로 규칙 — `docs/*_investigation.md`, 역사적 기록 유지, 규칙 11 삭제 제외)
> 진행 방식: 조사만 수행 (수정은 별도 승인 세션에서 진행)

---

## 1. 조사 개요

### 1.1 목적

P25 (격리된 실패) 원칙 관점에서 전체 코드베이스 전수 조사.
- 한 구성요소의 실패가 전체 시스템 기동/운영을 블로킹할 수 있는 취약점 식별
- 실패가 해당 구성요소에서 차단+로깅되는지, 다른 구성요소가 정상 작동 유지되는지 점검
- 관련 원칙(P7/P9/P16/P20/P23)과의 교차 점검

### 1.2 P25 핵심 내용 (ARCHITECTURE.md 발췌)

- 한 구성요소 실패가 전체 시스템 기동/운영 블로킹 금지
- 실패는 해당 구성요소에서 차단+로깅, 다른 구성요소 정상 작동 유지
- 격리 ≠ silent 무시 — 반드시 에러 로깅 (P20/P23 일관)
- P24 균형: 최소 전파 차단에 국한, 과도한 격리 추상화 금지

### 1.3 조사 범위

#### A. 프론트엔드 (3개 영역)
- **A1. WS 이벤트 디스패치**: `frontend/src/api/ws.ts`, `frontend/src/binding.ts`
- **A2. Store listener 전파**: `frontend/src/stores/store.ts`, `hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts`
- **A3. UI 컴포넌트 렌더링·DOM 리스너**: 36개 파일 (pages, components/common, layout)

#### B. 백엔드 (5개 영역)
- **B1. 엔진 코어 루프·태스크 스케줄러**: `engine_lifecycle.py`, `engine_loop.py`, `engine_ws*.py` 6개
- **B2. 파이프라인 연산 루프**: `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `pipeline_gateway.py`
- **B3. 대형 스케줄러·파이프라인**: `daily_time_scheduler.py`, `market_close_pipeline.py`
- **B4. 워커·IO·재시도 루프**: `notification_worker.py`, `db_writer.py`, `telegram_bot.py`, `kiwoom_rest.py`, `kiwoom_stock_rest.py`, `engine_cache.py`, `app.py`, `ws.py`/`ws_settings.py`/`ws_orders.py`
- **B5. 매매·테스트모드 태스크**: `trading.py`, `buy_order_executor.py`, `dry_run.py`

#### C. 교차 원칙 점검 (모든 세션에 통합)
- **P7** (블로킹 금지): 틱 핸들러 경로의 예외 전파가 루프 중단 유발 여부
- **P9** (파이프라인 독립): 예외 전파 경로 점검
- **P16** (살아있는 경로): add_done_callback 로깅 실제 발화 여부, dead code 격리 아닌지
- **P20** (폴백 금지): 모든 `except Exception`이 silent pass 아닌지, `exc_info=True` 로깅 여부
- **P23** (일관성): 격리 패턴이 파일 간 동일한지 (`schedule_engine_task` vs 직접 `create_task` 혼용 여부)

### 1.4 조사 방식 (모든 세션 공통)

- 각 파일의 `try/except`, `create_task`, `asyncio.gather`, `while` 루프, `add_done_callback` 패턴 분석
- 위반 후보 식별 시: 파일:줄번호 + 증상 + 영향 범위 기록 → 본 보고서 섹션 2 매트릭스에 누적
- 발견 즉시 `HANDOVER.md` "미해결 문제" 섹션에 병행 기록 (AGENTS.md 섹션4 규칙9)
- 수정은 별도 승인 세션에서 진행 (본 조사는 보고까지만)

### 1.5 9세션 분할

AGENTS.md 섹션3 규칙 0-1 (세션당 1단계 원칙) 준수.

| 세션 | 영역 | 우선순위 | 조사 파일 | 산출물 |
|------|------|----------|-----------|--------|
| 1 | A1 WS 디스패치 | 1 | `api/ws.ts`, `binding.ts` | 핸들러별 격리 여부 매트릭스 |
| 2 | B1 엔진 코어 루프 | 2 | `engine_lifecycle.py`, `engine_loop.py`, `engine_ws*.py` 6개 | 루프·태스크 격리 매트릭스 |
| 3 | B2 파이프라인 연산 | 3 | `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `pipeline_gateway.py` | compute 루프·sector 재계산 루프 격리 점검 |
| 4 | A2 Store listener | 4 | `store.ts`, `hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts` | listener 전파 차단 검증 + 추가 setState 경로 |
| 5 | B3 대형 스케줄러·파이프라인 | 5 | `daily_time_scheduler.py`, `market_close_pipeline.py` | schedule_engine_task 호출별 격리 + except 블록 P20 점검 |
| 6 | B4 워커·IO·재시도 | 6 | `notification_worker.py`, `db_writer.py`, `telegram_bot.py`, `kiwoom_rest.py`, `kiwoom_stock_rest.py`, `engine_cache.py`, `app.py`, `ws.py`/`ws_settings.py`/`ws_orders.py` | 워커·재시도 루프 격리 점검 |
| 7 | A3 UI 컴포넌트 렌더링 | 7 | 36개 파일 (pages, components/common, layout) | 컴포넌트·DOM 리스너 격리 매트릭스 |
| 8 | B5 매매·테스트모드 | 8 | `trading.py`, `buy_order_executor.py`, `dry_run.py` | dry_run 태스크·매매 경로 격리 점검 |
| 9 | C 교차 점검·총합 보고 | 9 | 전 세션 결과 취합 | P25 위반 전체 목록 + P7/P9/P16/P20/P23 교차 매트릭스 + 우선수정 추천 |

### 1.6 우선순위 기준 (영향도 큰 것부터)

| 순위 | 영역 | 사유 |
|------|------|------|
| 1 | A1 WS 디스패치 | 매 이벤트 통과. 한 핸들러 throw 시 전 채널 이벤트 수신 중단 → 화면 전체 멈춤 |
| 2 | B1 엔진 코어 루프 | 매 틱·매 이벤트 통과. 한 번 중단 시 자동매매 전체 정지 |
| 3 | B2 파이프라인 연산 루프 | 업종 점수·매수 후보 산출 경로. 중단 시 매수 후보 미갱신 |
| 4 | A2 Store listener | 화면 갱신 최종 경로 |
| 5 | B3 대형 스케줄러·파이프라인 | 장 마감 후 파이프라인·타임테이블 |
| 6 | B4 워커·IO·재시도 루프 | 알림·DB·재시도. 실패 시 일부 기능 손실 |
| 7 | A3 UI 컴포넌트 렌더링 | 개별 화면 단위 격리. 영향도 국소적 |
| 8 | B5 매매·테스트모드 태스크 | dry_run 태스크. 테스트모드 한정 |
| 9 | C 교차 점검·총합 보고 | 모든 세션 결과 취합 |

### 1.7 사전 확인된 주요 위반 후보 (조사 전 단계, 확정은 각 세션에서)

- `frontend/src/api/ws.ts:193` — `_dispatchMessage`의 `list.forEach(h => h(data))` 핸들러별 try/catch 누락 (P25 위반 후보)
- `backend/app/pipelines/pipeline_compute.py:209,214` — `create_task` 직접 호출 (schedule_engine_task 미사용, P23 일관성 위반 후보)
- `backend/app/services/trading.py:477,666` — dry_run 태스크 `create_task` 직접 호출 (P23 위반 후보)

---

## 2. P25 위반 매트릭스 (빈 템플릿 — 세션별 누적 갱신)

> 각 세션 조사 완료 후 위반 식별 시 본 매트릭스에 행 추가.
> ID 형식: `{영역}-{세션번호}-{순번}` (예: `A1-01-01`).

| ID | 영역 | 파일:줄 | 위반 내용 | 영향 범위 | 등급 | 관련 원칙 | 조사 세션 | 수정 승인 |
|----|------|---------|-----------|-----------|------|-----------|-----------|-----------|
| A1-01-01 | A1 WS 디스패치 | `frontend/src/api/ws.ts:193` | `_dispatchMessage`의 `list.forEach(h => h(data))`가 핸들러별 try/catch 없음. 한 핸들러 throw 시 forEach 즉시 중단 → 같은 event type의 후속 핸들러 미실행 + 예외가 `_handleBinaryFrame`/`_handleTextFrame` catch로 전파 | 같은 이벤트의 다른 핸들러 미실행 + (binary) 같은 프레임 후속 이벤트 손실. 화면 갱신 경로 전체가 WS 디스패치 단계에서 차단될 수 있음 | CRITICAL | P25, P21 | 세션 1 | 미승인 |
| A1-01-02 | A1 WS 디스패치 | `frontend/src/api/ws.ts:164-174` | `_handleBinaryFrame`의 `for (const event of events)` 루프가 try 블록 내부. 한 이벤트 핸들러 throw 시 catch(171)가 잡지만 루프 중단 → 같은 바이너리 프레임의 나머지 이벤트 모두 손실 | real-data는 고빈도 바이너리 프레임. 한 종목 핸들러 오류가 같은 프레임의 다른 종목 시세 갱신을 막음 → 화면 일부 종목 시세 정지 | CRITICAL | P25, P7 | 세션 1 | 미승인 |
| A1-01-03 | A1 WS 디스패치 | `frontend/src/api/ws.ts:172,181` | `_handleBinaryFrame`/`_handleTextFrame` catch 블록이 "디코딩 실패"/"파싱 실패"로 로깅. 실제로는 핸들러 예외일 수도 있어 로그 메시지가 원인을 잘못 표시 | 잘못된 로그로 디버깅 방해. P21(사용자 투명성) — 개발자가 원인 파악 불가. P23(일관성) — 에러 분류 불일치 | MEDIUM | P21, P23 | 세션 1 | 미승인 |
| A1-01-04 | A1 WS 디스패치 | `frontend/src/binding.ts` (33개 핸들러 전체) | 33개 onEvent 핸들러 중 어느 것도 내부 try/catch 없음. store.ts setState listener 루프는 F-02 fix로 보호되나, (a) 핸들러 본문 로직(destructuring, recalcTradeAmountRank, rebuildBuyTargetIndex, 중첩 property access), (b) setState의 updater 함수(`partial(state)` — store.ts:19), (c) applyXxx 함수 본문은 보호되지 않음. throw 시 A1-01-01/02로 전파 | 고위험 핸들러: `buy-targets-delta`(114-161, 복잡 로직), `sector-scores`(287-310, 중첩 접근), `sector-stocks-delta`(95-112), `circuit_breaker_open`(318-322, showToast). 이들 throw 시 WS 디스패치 단계에서 다른 이벤트까지 손실 | HIGH | P25, P16 | 세션 1 | 미승인 |
| A1-01-05 | A1 WS 디스패치 | `frontend/src/api/ws.ts:132-136` | `_scheduleReconnect`의 setTimeout 콜백이 `_connect()` 호출 시 try/catch 없음. `_connect` 동기 throw 시 재연결 루프 영구 중단 | `_connect`는 단순 WebSocket 생성으로 동기 throw 확률 낮음. 단, `disconnect()` 내부 오류 시 throw 가능. 발생 시 WS 영구 단절 | LOW | P25 | 세션 1 | 미승인 |
| B1-02-01 | B1 엔진 코어 루프 | `backend/app/services/engine_loop.py:304` | `run_engine_loop` while 루프 본문 내 `is_ws_subscribe_window(_settings)` 호출이 try/except 없음. throw 시 외부 try(159)에서 catch → 엔진 루프 전체 종료 | 한 번의 `is_ws_subscribe_window` 오류가 엔진 루프를 영구 종료 → 자동매매 전체 정지. WS 구간 감지 루프가 단일 예외로 사망 | HIGH | P25, P7 | 세션 2 | 미승인 |
| B1-02-02 | B1 엔진 코어 루프 | `backend/app/services/engine_loop.py:374,377` | `run_engine_loop` finally 블록 내 `disconnect_all()`/`disconnect()` 호출에 try/except 없음. throw 시 후속 정리(connector_manager=None, broker_rest_apis.clear(), running=False, broadcast_engine_status()) 스킵 | 엔진 정지 시 커넥터 정리 실패 → 엔진 상태 불일치(running=True 잔존, REST API 미정리). 다음 기동 시 잔존 상태 간섭 | MEDIUM | P25, P22 | 세션 2 | 미승인 |
| B1-02-03 | B1 엔진 코어 루프 | `backend/app/services/engine_loop.py:387,389` | `run_engine_loop` finally 블록 REST API 정리 루프에서 `_reset_client()`/`aclose()` 호출에 try/except 없음. `revoke_token()`은 try/except(382-385) 있으나 그 다음 호출들이 무보호 | 한 증권사 클라이언트 정리 실패 시 나머지 증권사 정리 스킵 → 일부 REST 클라이언트 미정리(리소스 누수) | MEDIUM | P25 | 세션 2 | 미승인 |
| B1-02-04 | B1 엔진 코어 루프 | `backend/app/services/engine_loop.py:31` | `_cache_and_bootstrap`에서 `_load_caches_preboot(settings)` 호출에 try/except 없음. throw 시 `run_engine_loop` try(159)에서 catch → 엔진 루프 종료 | 캐시 로드 실패(DB 오류, 파일 오류 등)가 엔진 기동 전체 차단. 엔진 기동 실패 시 자동매매 불가 | HIGH | P25, P16 | 세션 2 | 미승인 |
| B1-02-05 | B1 엔진 코어 루프 | `backend/app/services/engine_ws_dispatch.py:149-153` | `_handle_real_00` 내 `auto_trade.on_fill_update()`와 `engine_account._on_fill_after_ws()` 호출에 try/except 없음. throw 시 호출자(pipeline_compute.py:487)로 전파 | 주문체결 처리 중 예외 시 호출자로 전파. 호출자(pipeline_compute)의 격리 여부는 세션 3에서 확인. 세션 2 범위에서는 "호출자 의존" | LOW | P25 | 세션 2 | 미승인 |
| B1-02-06 | B1 엔진 코어 루프 | `backend/app/services/engine_ws_dispatch.py:162` | `_handle_real_balance` 내 `engine_account._apply_balance_realtime()` 호출에 try/except 없음. throw 시 호출자(pipeline_compute.py:492)로 전파 | 잔고 처리 중 예외 시 호출자로 전파. 호출자 격리 여부는 세션 3에서 확인 | LOW | P25 | 세션 2 | 미승인 |
| B1-02-07 | B1 엔진 코어 루프 | `backend/app/services/engine_lifecycle.py:38` | `start_engine` 내 `dry_run._refresh_positions_if_dirty()` 호출에 try/except 없음. throw 시 start_engine throw | 주 호출자(app.py:123 `_engine_init_background`)는 try/except(122-144)로 격리 → P25 준수. 단, engine_service.py:93 경유 호출 시 해당 함수의 try/except 여부는 세션 6에서 확인 | LOW | P25 | 세션 2 | 미승인 |
| B2-03-01 | B2 파이프라인 연산 | `backend/app/pipelines/pipeline_compute.py:646-670` | `_phase2_batch_recompute_loop` while 루프 본문에 try/except 없음. `notify_desktop_sector_scores`(667)/`_flush_sector_recompute_impl`(670) 등 무보호 호출이 throw 시 전파 → 태스크 영구 종료. 동일 구조의 `_compute_loop_impl`(316)은 `except Exception: log+continue` 있는데 비대칭 | 한 번의 업종 점수 전송/재계산 실패가 Phase 2 루프 사망 → 업종 점수 갱신 영구 중단 → 매수 후보 선정 영향 | HIGH | P25, P7, P23 | 세션 3 | 미승인 |
| B2-03-02 | B2 파이프라인 연산 | `backend/app/pipelines/pipeline_compute.py:673-686` | `_sector_recompute_loop_impl`이 `except CancelledError`(684)만 있고 `except Exception` 없음. B2-03-01의 상위 원인 — 비-CancelledError 예외 시 태스크 종료 | Phase 1/Phase 2 전체 사망. `_compute_loop_impl`은 `except Exception` 있는데 본 함수는 없어 P23 일관성 위반 | MEDIUM | P25, P23 | 세션 3 | 미승인 |
| B2-03-03 | B2 파이프라인 연산 | `backend/app/pipelines/pipeline_compute.py:521-526` | `_handle_real_tick` for item 루프에 per-item try/except 없음. 한 item(00 체결 등) 실패 시 같은 REAL 틱의 나머지 item(01/0D/0J 등) 스킵. 루프 전체 try/except(519-528)는 compute 루프 전파는 차단하나 형제 item 손실은 막지 못함 | 한 종목 체결 처리 오류가 같은 프레임의 다른 종목 시세/호가/업종지수 갱신 누락. B1-02-05/06 형제 손실과 동일 경로 | LOW | P25, P7 | 세션 3 | 미승인 |
| B2-03-04 | B2 파이프라인 연산 | `backend/app/pipelines/pipeline_compute_tick_handlers.py:92-104` | `_handle_real_0j_tick`에 try/except 없음. 다른 leaf 핸들러(`_handle_real_01_tick`/`_handle_real_0d_tick`/`_handle_real_pgm_tick`)는 try/except 있는데 0J만 없음 → P23 일관성 위반. `notify_index_data` 실패 시 상위 `_handle_real_tick`에 의존 | 업종지수 전송 실패 시 같은 REAL 틱의 나머지 item 스킵(B2-03-03 경로 합류). 영향도 국소적 | LOW | P25, P23 | 세션 3 | 미승인 |
| B2-03-05 | B2 파이프라인 연산 | `backend/app/pipelines/pipeline_gateway.py:32` | `start_gateway_loop`가 `_gateway_task`에 done_callback 없음. compute 서브태스크(`pipeline_compute.py:210-218`)는 done_callback 있는데 게이트웨이는 없음 → P23 일관성 위반 | 루프 자체는 `_broadcast_loop` try/except로 격리되어 영향도 낮음. 단 태스크 예외 시 로깅 누락(P21) | LOW | P25, P21, P23 | 세션 3 | 미승인 |
| A2-04-01 | A2 Store listener | `frontend/src/stores/store.ts:19` | `setState`의 updater 함수 `partial(state)`가 try/catch 밖. updater 본문 throw 시 listener 루프(40-46) 보호 우회, setState 호출자에게 즉시 전파 → binding.ts 핸들러(A1-01-04) → WS 디스패치(A1-01-01)로 전파 → 같은 이벤트 후속 핸들러 미실행 + 같은 바이너리 프레임 후속 이벤트 손실 | 고빈도 이벤트(real-data, buy-targets-delta, account-update)의 updater throw 시 화면 갱신 전체 중단 위험. throw 확률은 낮으나 구조적 보호 부재 | MEDIUM | P25, P16 | 세션 4 | 미승인 |
| A2-04-02 | A2 Store listener | `frontend/src/stores/hotStore.ts:367-370,390,412,431` | `window.dispatchEvent(new CustomEvent(...))`가 try/catch 밖. CustomEvent 핸들러(real-data-tick/orderbook-tick/program-tick) throw 시 apply* 함수 호출자로 전파 → binding.ts 핸들러 → WS 디스패치로 전파. real-data-tick은 매 틱 발생 | 한 UI 컴포넌트 핸들러 오류가 같은 틱의 다른 종목 시세 갱신 중단. 핸들러 등록부는 A3(세션 7)에서 조사 예정 | MEDIUM | P25, P7 | 세션 4 | 미승인 |
| B3-05-01 | B3 스케줄러·파이프라인 | `backend/app/services/market_close_pipeline.py:645-650` | `_save_confirmed_cache` inner except에서 rollback+warning 후 fall-through → 650 `return True` → 전종목 마스터 테이블 DB 저장 실패해도 함수 True 반환. 후속 6단계 메모리 교체 로직이 잘못된 성공 전제로 진행 | DB 저장 실패를 성공으로 보고 → 6단계 메모리 교체가 잘못된 전제로 실행 → 메모리/DB 불일치 상태 지속. P22 데이터 정합성 위반 + P21 사용자 투명성 위반 | HIGH | P22, P21 | 세션 5 | 미승인 |
| B3-05-02 | B3 스케줄러·파이프라인 | `backend/app/services/market_close_pipeline.py:897` | `_step5_download_daily_confirmed`에서 `confirmed = {}` 빈 폴백. if confirmed 가드로 메모리/DB는 보호되나, 빈 eligible_codes로 `_run_post_confirmed_pipeline` 실행 → 빈 캐시 저장 시도 | 전종목 다운로드 실패 시 빈 데이터로 후속 파이프라인 진행. P20 폴백 금지 위반. 단 if confirmed 가드로 메모리/DB 파손은 차단 | MEDIUM | P20 | 세션 5 | 미승인 |
| B3-05-03 | B3 스케줄러·파이프라인 | `backend/app/services/market_close_pipeline.py:492` | `except (ValueError, TypeError): pass` silent pass. float 변환 실패 시 strength_str 갱신 스킵만 하고 종목 루프 계속 (로깅 없음) | strength 필드 갱신 누락이 로그에 남지 않아 디버깅 불가. P20 위반. 영향도 국소적 (단일 종목 strength 필드) | LOW | P20 | 세션 5 | 미승인 |
| B3-05-04 | B3 스케줄러·파이프라인 | 11곳 (`market_close_pipeline.py` 424, 858, 934, 1103, 1254 + `daily_time_scheduler.py` 1273, 1287, 1327, 1354, 1446, 1507) | exc_info 누락. logger.warning은 하나 exc_info=True 누락. 단 934는 "(무시)" 표시로 의도적 일부 드러남 | 스택트레이스 누락으로 디버깅困难. P23 일관성 위반 (다른 경로는 exc_info=True). 즉시 중단 유발 아님 | LOW | P23 | 세션 5 | 미승인 |

### 등급 정의
- **CRITICAL**: 한 구성요소 실패가 시스템 전체 중단 유발 (자동매매 정지, 화면 전체 멈춤)
- **HIGH**: 한 구성요소 실패가 주요 기능(매수 후보 산출, 업종 점수 등) 중단 유발
- **MEDIUM**: 한 구성요소 실패가 일부 기능 손실 (알림 누락 등), 시스템은 동작
- **LOW**: 일관성 위반 (혼용 패턴 등), 즉시 중단 유발 아님

### 관련 원칙 표기
- P25 (격리된 실패) — 본 조사 주 원칙
- P7 (블로킹 금지), P9 (파이프라인 독립), P16 (살아있는 경로), P20 (폴백 금지), P23 (일관성) — 교차 점검 대상

---

## 3. 세션 1: A1 WS 디스패치 조사

> 상태: 완료 (2026-07-23)
> 조사 파일: `frontend/src/api/ws.ts` (261줄), `frontend/src/binding.ts` (338줄), `frontend/src/stores/store.ts` (57줄 — 보호 범위 확인용)
> 조사 범위:
> - `_dispatchMessage` (ws.ts:185-194) 핸들러별 try/catch 여부
> - `_handleBinaryFrame` / `_handleTextFrame` (ws.ts:164-183) 디코딩 실패 시 핸들러 호출 차단 여부
> - `binding.ts` 33개 onEvent 핸들러 각각의 내부 예외 처리 여부
> - WS 재연결 루프 (`_scheduleReconnect`) 실패 시 전파 경로
> - store.ts setState try/catch (F-02 fix)의 보호 범위 한계 확인

### 3.1 조사 결과

#### 3.1.1 WS 디스패치 호출 경로 (정상 시)

```
ws.onmessage (ws.ts:104)
  → _handleBinaryFrame(buffer)  /  _handleTextFrame(text)
    → try { decodeProtobufEvents(buffer) / JSON.parse(text) }
      → for (const event of events)  /  단일 msg
        → _dispatchMessage(msg)
          → list.forEach(h => h(data))   ← 핸들러 호출
            → binding.ts 33개 핸들러 중 해당 type
              → applyXxx(...) / hotStore.setState((state) => {...})
                → store.ts setState → listener 루프 (F-02 try/catch 보호)
```

#### 3.1.2 보호 계층 분석 (어디까지 막아주는가)

| 계층 | 위치 | try/catch | 보호 대상 | 비고 |
|------|------|-----------|-----------|------|
| Protobuf 디코딩 | `decodeProtobufEvents` ws.ts:36-53 | O (per-event) | 단일 이벤트 디코딩 실패 | 다른 이벤트는 계속 디코딩. 양호 |
| 바이너리 프레임 루프 | `_handleBinaryFrame` ws.ts:164-174 | O (루프 전체) | 디코딩 + 핸들러 예외 전부 | **문제**: 루프가 try 내부 → 한 핸들러 throw 시 나머지 이벤트 손실 (A1-01-02) |
| 텍스트 프레임 | `_handleTextFrame` ws.ts:176-183 | O (단일) | 파싱 + 핸들러 예외 전부 | catch 로그가 "파싱 실패"로 핸들러 예외와 혼동 (A1-01-03) |
| 핸들러 디스패치 | `_dispatchMessage` ws.ts:193 | X | 핸들러별 격리 | **핵심 위반**: `forEach` 내 핸들러별 try/catch 없음 (A1-01-01) |
| binding.ts 핸들러 본문 | binding.ts 33개 | X | 핸들러 로직 | 33개 전부 try/catch 없음 (A1-01-04) |
| setState updater 함수 | store.ts:19 `partial(state)` | X | updater 함수 본문 | F-02 fix는 listener 루프(40-46)만 보호. updater throw는 보호 안됨 |
| setState listener 루프 | store.ts:40-46 | O (per-listener) | UI 렌더링 listener | F-02 fix. 양호. 단, binding.ts 핸들러 오류는 여기 도달 전 전파 |

**핵심 한계**: F-02 fix(store.ts listener 루프 try/catch)는 UI 렌더링 listener만 보호. binding.ts 핸들러 본문 로직 + setState updater 함수는 보호되지 않아, 이들 throw 시 예외가 store.ts를 넘어 ws.ts 디스패치 단계로 역전파 → A1-01-01/02 위반 경로로 합류.

#### 3.1.3 binding.ts 33개 핸들러 분류

| 채널 | 핸들러 수 | 위험도 | 고위험 핸들러 (복잡 로직) |
|------|-----------|--------|---------------------------|
| prices | 25 | HIGH | `buy-targets-delta`(114-161), `sector-scores`(287-310), `sector-stocks-delta`(95-112), `sell-history-append`(234-242), `circuit_breaker_open`(318-322, showToast) |
| settings | 6 | MEDIUM | `avg-amt-progress`(209-211, 다중 optional 필드), `bootstrap-stage`(205-207) |
| orders | 2 | LOW | `order-filled`(220-222), `test-data-reset-completed`(225-227) — 단순 applyXxx 호출 |

전 33개 핸들러가 내부 try/catch 없음. 단순 핸들러(orders 채널 등)는 applyXxx 내부 오류 가능성만 남고, 복잡 핸들러(prices 채널)는 핸들러 본문 자체 오류 가능성이 높음.

#### 3.1.4 재연결 루프 분석

- `_scheduleReconnect` (ws.ts:132-136): setTimeout 콜백 → `_connect()`. try/catch 없음.
- `_connect` (ws.ts:89-130): `disconnect()` → `new WebSocket(url)` → 핸들러 설정. 동기 throw 가능성 낮으나 `disconnect()` 내부 오류 시 throw 가능.
- ping 타이머 (ws.ts:141-154): `ws.send` try/catch 있음. 2회 실패 시 close + reconnect. 양호.
- `onclose` (ws.ts:118-129): 1008(인증거부) 시 재연결 안함(의도적). 나머지 `_scheduleReconnect`. 양호.

#### 3.1.5 사전 위반 후보(1.7절) 확정 결과

- `ws.ts:193` `_dispatchMessage` forEach — **확정 CRITICAL** (A1-01-01)
- (백엔드 후보 2건은 세션 3/8에서 조사 예정)

### 3.2 위반 목록

| ID | 등급 | 파일:줄 | 위반 요약 | 수정 방향 (참고용, 승인 시 별도 세션) |
|----|------|---------|-----------|---------------------------------------|
| A1-01-01 | CRITICAL | ws.ts:193 | `_dispatchMessage` 핸들러별 try/catch 없음 | `forEach`를 try/catch 감싼 루프로 변경, 핸들러 throw 시 `console.error('[WS] handler error', type, e)` + 다른 핸들러 계속 실행 |
| A1-01-02 | CRITICAL | ws.ts:164-174 | `_handleBinaryFrame` 루프가 try 내부 → 후속 이벤트 손실 | 디코딩 try와 핸들러 디스패치 try 분리. 디코딩은 프레임 단위, 핸들러는 per-event try (A1-01-01 수정으로 자연 해결) |
| A1-01-03 | MEDIUM | ws.ts:172,181 | catch 로그가 "파싱 실패"로 핸들러 예외와 혼동 | 디코딩/파싱 catch와 핸들러 catch 분리 후 각각 목적에 맞는 로그 메시지 |
| A1-01-04 | HIGH | binding.ts 33개 핸들러 | 내부 try/catch 없음 | (a) A1-01-01 수정으로 디스패치 단계 격리 확보 시 핸들러 개별 try/catch는 선택적. (b) 단, 고위험 핸들러(buy-targets-delta 등)는 본문 try/catch 권장 — 디스패치 격리와 본문 격리는 상호 보완. 최종 방침은 수정 세션에서 결정 |
| A1-01-05 | LOW | ws.ts:132-136 | `_scheduleReconnect` setTimeout 콜백 try/catch 없음 | `_connect()` 호출을 try/catch 감싸고 실패 시 `_scheduleReconnect` 재호출(백오프 유지) |

### 3.3 교차 원칙 점검 (세션 1 범위)

| 원칙 | 해당 여부 | 비고 |
|------|-----------|------|
| P7 (블로킹 금지) | 해당 | A1-01-02: 바이너리 프레임 루프 중단 = 시세 갱신 블로킹. 틱 핸들러 경로는 아니지만 고빈도 real-data 경로 |
| P9 (파이프라인 독립) | 해당 아님 | WS 디스패치는 파이프라인 아님 |
| P16 (살아있는 경로) | 해당 | A1-01-04: 핸들러 본문 보호 없음 = 예외 시 경로 사망. F-02 fix는 listener 경로만 살림 |
| P20 (폴백 금지) | 해당 아님 | 본 세션에서 silent `except: pass` 없음. 모든 catch는 console.error 로깅 |
| P23 (일관성) | 해당 | A1-01-03: 에러 로그 메시지 불일치(파싱 vs 핸들러). P25 격리 패턴이 ws.ts 내에서도 불일치(디코딩은 per-event, 핸들러는 per-batch) |

---

## 4. 세션 2: B1 엔진 코어 루프 조사

> 상태: 완료 (2026-07-23)
> 조사 파일: `engine_lifecycle.py` (328줄), `engine_loop.py` (395줄), `engine_ws_dispatch.py` (401줄), `engine_ws.py` (271줄), `engine_ws_fill_followup.py` (29줄), `engine_ws_parsing.py` (218줄), `engine_ws_reg.py` (490줄)
> 보조 조사 파일: `kiwoom_connector.py` (_recv_loop), `ls_connector.py` (_recv_loop), `app.py` (start_engine 호출자), `engine_service.py` (on_trade_mode_switched 호출자)
> 조사 범위:
> - `schedule_engine_task` (engine_lifecycle.py:279-309) 중앙 격리 메커니즘 검증
> - `engine_loop.py:302` 메인 루프 while 내부 try/except 전파 차단
> - `engine_loop.py:343-344` create_task 직접 호출 (stop_wait/change_wait) 격리
> - engine_ws_* 6개 파일의 이벤트 핸들러 예외 전파 경로
> - 커넥터 recv 루프에서 핸들러 호출 시 예외 격리 (P23 일관성 점검)

### 4.1 조사 결과

#### 4.1.1 엔진 코어 호출 경로 (정상 시)

```
app.py lifespan → _engine_init_background (app.py:121, try/except 보호)
  → start_engine (engine_lifecycle.py:22)
    → asyncio.create_task(_engine_loop()) (line 30, 엔진 메인 태스크)
      → _engine_loop (engine_lifecycle.py:48, try/except 보호)
        → run_engine_loop (engine_loop.py:133)
          → try (159) {
              _init_ws_subscribe_state, _cache_and_bootstrap, _get_all_tokens_async, _load_spec
              → asyncio.gather (208, 3개 병렬)
              → start_compute_loop (296)
              → while not engine_stop_event.is_set() (302, 메인 루프)
                → is_ws_subscribe_window (304) ← 무보호
                → WS 연결/해제 (308-341, 개별 try/except 보호)
                → stop_wait/change_wait create_task (343-344, asyncio.wait + cancel)
            } except CancelledError (353) / except Exception (355)
          → finally (359) { stop_compute_loop (try/except), disconnect_all (무보호), REST 정리 루프 (부분 보호) }

커넥터 recv 루프:
_KiwoomSocket._recv_loop (kiwoom_connector.py:95, try/except 전체 루프)
  → REAL → tick_queue (138, QueueFull try/except)
  → LOGIN/REG/UNREG/REMOVE → _on_message (133,151)
    → _on_ws_message (kiwoom_connector.py:376)
      → _broker_message_handler (engine_ws.py:93)
        → _handle_ws_data (engine_ws.py:106)
          → engine_ws_dispatch.handle_ws_data (165, try/except 보호)
            → _handle_login / _handle_reg / _handle_jif

REAL 틱 처리 (세션 3 범위, 참고):
tick_queue → pipeline_compute → _handle_real_00 / _handle_real_balance (engine_ws_dispatch.py)
```

#### 4.1.2 보호 계층 분석 (어디까지 막아주는가)

| 계층 | 위치 | try/except | 보호 대상 | 비고 |
|------|------|-----------|-----------|------|
| 엔진 메인 태스크 | `_engine_loop` engine_lifecycle.py:48-56 | O | run_engine_loop 전체 | 양호. 루프 예외 시 로깅 후 종료 |
| 엔진 루프 진입 | `run_engine_loop` engine_loop.py:159-358 | O (전체) | 루프 본문 전체 | **문제**: while 내 개별 호출이 무보호면 루프 전체 종료 (B1-02-01) |
| WS 구간 감지 루프 | `while` engine_loop.py:302-351 | X (루프 본문) | is_ws_subscribe_window 호출 | **핵심 위반**: 304줄 throw 시 루프 종료 (B1-02-01) |
| WS 연결 초기화 | engine_loop.py:308-330 | O (개별) | ConnectorManager 생성/연결 | 양호. 실패 시 connector_manager=None |
| WS 연결 해제 | engine_loop.py:333-341 | O (개별) | disconnect_all | 양호 |
| stop_wait/change_wait | engine_loop.py:343-350 | O (asyncio.wait + cancel) | 로컬 대기 태스크 | 양호. pending cancel로 정리 |
| finally 정리 - compute | engine_loop.py:365-368 | O | stop_compute_loop | 양호 |
| finally 정리 - 커넥터 | engine_loop.py:374,377 | X | disconnect_all/disconnect | **위반**: throw 시 후속 정리 스킵 (B1-02-02) |
| finally 정리 - REST 루프 | engine_loop.py:381-389 | 부분 | revoke_token(O) / _reset_client,aclose(X) | **위반**: 한 증권사 실패 시 나머지 스킵 (B1-02-03) |
| 캐시+부트스트랩 | `_cache_and_bootstrap` engine_loop.py:22-39 | 부분 | broadcast(O) / _load_caches_preboot(X) | **위반**: 캐시 로드 실패 시 엔진 종료 (B1-02-04) |
| 토큰 발급 | `_get_all_tokens_async` engine_loop.py:42-103 | O (per-broker + gather) | 개별 증권사 토큰 발급 | 양호. gather return_exceptions=True |
| 브로커 스펙 로드 | `_load_broker_spec_async` engine_loop.py:106-130 | O (전체) | 스펙 로드 | 양호. 실패 시 빈 리스트 |
| schedule_engine_task | engine_lifecycle.py:279-309 | O (전체) | 코루틴 스케줄 + done_callback | 양호. 중앙 격리 메커니즘 |
| WS 디스패치 | `handle_ws_data` engine_ws_dispatch.py:165-177 | O (전체) | LOGIN/REG/UNREG/REMOVE/JIF 핸들러 | 양호. 핸들러 예외 시 로깅 |
| _handle_login | engine_ws_dispatch.py:55-64 | O (REG 트리거) | REG 파이프라인 트리거 | 양호 |
| _handle_reg | engine_ws_dispatch.py:91-121 | O (try/finally) | REG 응답 처리 | 양호. finally에서 _notify_reg_ack 보장 |
| _handle_real_00 | engine_ws_dispatch.py:139-155 | 부분 | 902 파싱(O) / on_fill_update, _on_fill_after_ws(X) | **위반**: 자동매매 콜백 무보호 (B1-02-05). 호출자 의존 |
| _handle_real_balance | engine_ws_dispatch.py:158-162 | X | _apply_balance_realtime | **위반**: 잔고 처리 무보호 (B1-02-06). 호출자 의존 |
| _notify_krx_cb_telegram | engine_ws_dispatch.py:390-400 | O | 텔레그램 알림 | 양호 |
| 커넥터 recv 루프 | kiwoom_connector.py:95-172, ls_connector.py:95-164 | O (전체 루프) | recv + 핸들러 호출 | 양호. 비-연결오류 시 로깅+계속. P23 일관성 |
| _ensure_ws_subscriptions | engine_ws.py:202-215 | O (try/except/finally) | 구독 전송 | 양호 |
| _run_sector_reg_pipeline | engine_ws.py:218-235 | O (try/except/finally) | REG 파이프라인 | 양호. finally에서 event set 보장 |
| subscribe_index_realtime | engine_ws_reg.py:333-354 | O | 업종지수 구독 | 양호 |
| subscribe_account_realtime | engine_ws_reg.py:357-389 | O | 계좌 구독 | 양호 |
| subscribe_positions_stocks | engine_ws_reg.py:392-432 | 부분 | subscribe_stocks 실패 시 롤백 | 양호. 실패 시 _subscribed 플래그 롤백 |
| restore_subscriptions | engine_ws_reg.py:439-490 | O (0J/00/04 각각) | 재연결 후 구독 복원 | 양호. 각 단계별 try/except |
| _unreg_grp | engine_ws_reg.py:201-241 | O (청크별) | REMOVE 전송 | 양호. 청크별 try/except (233-236) |
| engine_ws_parsing.py | 전체 (218줄) | O (각 파서) | 파싱 함수 | 양호. 순수 함수, try/except 내장 |
| engine_ws_fill_followup.py | 전체 (29줄) | 해당 없음 | 동기 콜백 래퍼 | 양호. 단순 호출 |

#### 4.1.3 schedule_engine_task 중앙 격리 메커니즘 검증

`schedule_engine_task` (engine_lifecycle.py:279-309)는 엔진 이벤트 루프에 코루틴을 안전하게 스케줄하는 중앙 메커니즘.

**검증 결과 — P25 준수**:
1. `loop.call_soon_threadsafe(_create_with_callback)` — UI 스레드에서 호출 시 안전 스케줄
2. `task.add_done_callback(lambda t: logger.warning(...) if t.exception() else None)` — 태스크 실패 시 로깅 (silent 아님, P20 준수)
3. 스케줄 실패 시 `coro.close()` 정리 — 코루틴 리소스 누수 방지
4. `coro.close()` 자체도 try/except (296-297, 307-308) — 정리 실패 시에도 로깅
5. `asyncio.get_running_loop().create_task(coro)` 폴백 경로(299-302)도 동일한 done_callback 적용

**P23 일관성**: `add_done_callback` 패턴이 app.py:142, engine_lifecycle.py:289/301에서 동일 적용. 일관됨.

#### 4.1.4 engine_loop.py:343-344 create_task 직접 호출 분석

사전 위반 후보(1.7절)가 아님. 조사 결과 **위반 아님**:
- `stop_wait = asyncio.create_task(engine_stop_event.wait())` (343)
- `change_wait = asyncio.create_task(ws_window_changed_event.wait())` (344)
- `asyncio.wait([stop_wait, change_wait], return_when=FIRST_COMPLETED)` (345-348)
- `for p in pending: p.cancel()` (349-350) — pending 태스크 정리

이들은 `schedule_engine_task` 대상이 아님 — 로컬 이벤트 대기 태스크이며 asyncio.wait + cancel로 정상 정리. P25 위반 아님, P23 일관성 위반 아님.

#### 4.1.5 커넥터 recv 루프 P23 일관성 점검

| 커넥터 | _recv_loop | try/except | 비-연결오류 시 | P25 | P23 |
|--------|-----------|-----------|---------------|-----|-----|
| Kiwoom | kiwoom_connector.py:95-172 | O (전체 루프) | 로깅+계속 (169-170) | 준수 | — |
| LS | ls_connector.py:95-164 | O (전체 루프) | 로깅+계속 (160-162) | 준수 | 일관 |

두 커넥터의 recv 루프 패턴 동일 — try/except 전체 루프, 연결 끊김 시 break, 비-연결오류 시 `logger.warning(..., exc_info=True)` + `asyncio.sleep(0.1)` + 계속. P25 준수, P23 일관.

#### 4.1.6 사전 위반 후보(1.7절) 확정 결과

- `engine_loop.py:343-344` create_task 직접 호출 — **위반 아님** (4.1.4 참조)
- (프론트엔드 후보 1건은 세션 1에서 확정, 백엔드 후보 `pipeline_compute.py:209,214`/`trading.py:477,666`는 세션 3/8에서 조사 예정)

### 4.2 위반 목록

| ID | 등급 | 파일:줄 | 위반 요약 | 수정 방향 (참고용, 승인 시 별도 세션) |
|----|------|---------|-----------|---------------------------------------|
| B1-02-01 | HIGH | engine_loop.py:304 | while 루프 본문 내 `is_ws_subscribe_window` 호출이 무보호. throw 시 엔진 루프 전체 종료 | while 루프 본문을 try/except로 감싸고, 예외 시 `logger.warning(..., exc_info=True)` + `await asyncio.sleep(1)` 후 계속. 루프 종료는 engine_stop_event에서만 유도 |
| B1-02-02 | MEDIUM | engine_loop.py:374,377 | finally 블록 `disconnect_all()`/`disconnect()` 무보호. throw 시 후속 정리 스킵 | `disconnect_all()`/`disconnect()`를 try/except로 감싸고, 실패 시 `logger.warning(..., exc_info=True)`. 후속 정리(connector_manager=None 등)는 항상 실행 |
| B1-02-03 | MEDIUM | engine_loop.py:387,389 | finally 블록 REST 정리 루프에서 `_reset_client()`/`aclose()` 무보호. 한 증권사 실패 시 나머지 스킵 | `_reset_client()`/`aclose()`를 기존 `revoke_token()` try/except 블록 내로 통합. 한 증권사 정리 실패 시 로깅 후 다음 증권사 계속 |
| B1-02-04 | HIGH | engine_loop.py:31 | `_cache_and_bootstrap`에서 `_load_caches_preboot` 무보호. throw 시 엔진 루프 종료 | `_load_caches_preboot`를 try/except로 감싸고, 실패 시 `logger.error(..., exc_info=True)` + 빈 캐시로 기동 허용 또는 안전한 종료. 기동 실패 시 프론트엔드에 상태 전송(P21) |
| B1-02-05 | LOW | engine_ws_dispatch.py:149-153 | `_handle_real_00` 내 `on_fill_update`/`_on_fill_after_ws` 무보호. 호출자(pipeline_compute) 의존 | 세션 3에서 pipeline_compute 호출부 격리 확인 후 결정. 호출자 격리 있으면 본문 try/catch 선택적, 없으면 본문 try/catch 필수 |
| B1-02-06 | LOW | engine_ws_dispatch.py:162 | `_handle_real_balance` 내 `_apply_balance_realtime` 무보호. 호출자 의존 | B1-02-05와 동일. 세션 3에서 확인 후 결정 |
| B1-02-07 | LOW | engine_lifecycle.py:38 | `start_engine` 내 `_refresh_positions_if_dirty` 무보호. 주 호출자(app.py)는 격리 있으나 engine_service.py:93 경유 시 미확인 | 세션 6에서 engine_service.py:90-93 경로 확인 후 결정. 필요 시 `_refresh_positions_if_dirty`를 try/except로 감싸고 실패 시 경고 로그 + 계속 |

### 4.3 교차 원칙 점검 (세션 2 범위)

| 원칙 | 해당 여부 | 비고 |
|------|-----------|------|
| P7 (블로킹 금지) | 해당 | B1-02-01: is_ws_subscribe_window throw 시 엔진 루프 중단 = 자동매매 블로킹. 매 루프 반복 호출 경로 |
| P9 (파이프라인 독립) | 해당 아님 | 엔진 코어 루프는 파이프라인 아님. start_compute_loop 호출은 파이프라인 시작점이나 루프 자체는 코어 |
| P16 (살아있는 경로) | 해당 | B1-02-04: 캐시 로드 실패 시 엔진 루프 사망 — 경로가 살아있지 않음. schedule_engine_task의 done_callback은 살아있는 경로 유지 |
| P20 (폴백 금지) | 해당 아님 | 본 세션에서 silent `except: pass` 없음. 모든 catch는 logger.warning/error + exc_info=True. 무보호 호출(B1-02-01~04)은 catch 자체가 없어 P20 대상 아님 |
| P23 (일관성) | 해당 | schedule_engine_task vs 직접 create_task 혼용 — engine_loop.py:30(엔진 메인), 343-344(로컬 대기)는 schedule_engine_task 불필요. 일관성 유지. 커넥터 recv 루프 패턴 Kiwoom/LS 동일 |

### 4.4 양호 항목 (P25 준수 확인)

- `schedule_engine_task` (engine_lifecycle.py:279-309): 중앙 격리 메커니즘. done_callback 로깅 + coro.close() 정리. **P25 준수**
- `_engine_loop` (engine_lifecycle.py:48-56): try/except로 run_engine_loop 감쌈. **P25 준수**
- `handle_ws_data` (engine_ws_dispatch.py:165-177): try/except로 LOGIN/REG/UNREG/REMOVE/JIF 핸들러 격리. **P25 준수**
- `_handle_login` (engine_ws_dispatch.py:55-64): REG 파이프라인 트리거 try/except. **P25 준수**
- `_handle_reg` (engine_ws_dispatch.py:91-121): try/finally로 REG 처리 격리. **P25 준수**
- `_notify_krx_cb_telegram` (engine_ws_dispatch.py:390-400): try/except로 알림 격리. **P25 준수**
- `_recv_loop` (kiwoom_connector.py:95-172, ls_connector.py:95-164): 전체 루프 try/except, 비-연결오류 시 로깅+계속. **P25 준수, P23 일관**
- `_broker_message_handler` (engine_ws.py:93-103): handle_ws_data의 try/except가 격리. **P25 준수**
- `_ensure_ws_subscriptions_for_positions` (engine_ws.py:202-215): try/except/finally. **P25 준수**
- `_run_sector_reg_pipeline` (engine_ws.py:218-235): try/except/finally. **P25 준수**
- `subscribe_index_realtime` (engine_ws_reg.py:333-354): try/except. **P25 준수**
- `subscribe_account_realtime` (engine_ws_reg.py:357-389): try/except. **P25 준수**
- `restore_subscriptions_after_reconnect` (engine_ws_reg.py:439-490): 0J/00/04 복원 각각 try/except. **P25 준수**
- `_unreg_grp` (engine_ws_reg.py:201-241): 청크별 try/except (233-236). **P25 준수**
- `engine_ws_parsing.py` (전체): 순수 파싱 함수, try/except 내장. **P25 준수**
- `engine_ws_fill_followup.py` (전체): 동기 콜백 래퍼, 단순. **P25 준수**
- `engine_loop.py:343-344` create_task 직접 호출: 로컬 대기 태스크, asyncio.wait + cancel로 정리. **위반 아님**

---

## 5. 세션 3: B2 파이프라인 연산 루프 조사

> 상태: 완료 (2026-07-23)
> 조사 파일: `pipeline_compute.py` (686줄), `pipeline_compute_tick_handlers.py` (333줄), `pipeline_gateway.py` (120줄)
> 보조 조사 파일: `engine_lifecycle.py` (schedule_engine_task 비교), `app.py` (게이트웨이 호출부), `engine_ws_dispatch.py` (B1-02-05/06 원본), `engine_sector_confirm.py`/`engine_account_notify.py` (Phase 2 호출 함수들)
> 조사 범위:
> - `pipeline_compute.py:209,214` create_task 직접 호출 (schedule_engine_task 미사용 — P23 위반 후보)
> - `_compute_loop_impl` / `_sector_recompute_loop_impl` / `_phase2_batch_recompute_loop` 루프 실패 시 전파 경로
> - `_handle_real_tick` for item 루프 per-item 격리 (B1-02-05/06 호출부 격리 확인)
> - tick_handlers의 틱 핸들러 예외 처리 (P7 교차)
> - `pipeline_gateway.py` 게이트웨이 루프 격리 + done_callback 일관성

### 5.1 조사 결과

#### 5.1.1 파이프라인 연산 호출 경로 (정상 시)

```
엔진 루프 (engine_loop.py:296)
  → await start_compute_loop (pipeline_compute.py:199)
    → asyncio.create_task(_compute_loop_impl()) (209, done_callback 있음)
    → asyncio.create_task(_sector_recompute_loop_impl()) (214, done_callback 있음)

_compute_loop_impl (278):
  while _compute_running (286)
    try { tick_queue.get(timeout=0.5) → _drain_control_queue → _process_tick_batch → sleep(0) }
    except CancelledError: break
    except Exception: log+continue  ← P25 준수

_process_tick_batch (256):
  for event in coalesced:
    try { _process_tick_data(event) } except Exception: log  ← per-event P25 준수

_process_tick_data → _handle_real_tick (509):
  try { for item in items: _dispatch_real_item(item) } except Exception: log  ← 루프 전파 차단 O, per-item X
    → _dispatch_real_item (467): 01/00/04/80/0d/0j/PGM 분기
      → _handle_real_00 (engine_ws_dispatch.py:139) ← B1-02-05 원본
      → _handle_real_balance (engine_ws_dispatch.py:158) ← B1-02-06 원본
      → _handle_real_01_tick / _handle_real_0d_tick / _handle_real_pgm_tick (try/except 있음)
      → _handle_real_0j_tick (try/except 없음 — B2-03-04)

_sector_recompute_loop_impl (673):
  try { _phase1_wait_threshold → _phase2_batch_recompute_loop }
  except CancelledError: log  ← except Exception 없음 (B2-03-02)

_phase1_wait_threshold (569):
  while _compute_running and not phase1_completed (588)
    try { _receive_rate_event.wait → _calculate_receive_rate → _evaluate_threshold }
    except Exception: log+continue  ← P25 준수

_phase2_batch_recompute_loop (638):
  while _compute_running (646)
    await asyncio.sleep(0.2)
    if _receive_rate_dirty: _calculate_receive_rate + _send_receive_rate
    await notify_desktop_sector_scores(force=False)  ← 무보호 (B2-03-01)
    if has_dirty_sectors(): await _flush_sector_recompute_impl()  ← 무보호 (B2-03-01)

app.py lifespan (62):
  _gateway_task = asyncio.create_task(start_gateway_loop())  ← done_callback 있음 (63)
    → _gateway_loop_impl (51) → _broadcast_loop (62)
      while _gateway_running (68)
        try { broadcast_queue.get → _process_broadcast → task_done }
        except CancelledError: break
        except Exception: log+continue  ← P25 준수
```

#### 5.1.2 보호 계층 분석 (어디까지 막아주는가)

| 계층 | 위치 | try/except | 보호 대상 | 비고 |
|------|------|-----------|-----------|------|
| compute 루프 | `_compute_loop_impl` pipeline_compute.py:285-318 | O (루프 본문) | tick_queue 처리 전체 | 양호. `except Exception: log+continue` |
| 배치 처리 | `_process_tick_batch` pipeline_compute.py:261-267 | O (per-event) | 개별 이벤트 처리 | 양호. 한 이벤트 실패 시 다음 이벤트 계속 |
| REAL 틱 처리 | `_handle_real_tick` pipeline_compute.py:519-528 | O (루프 전체) | for item 루프 전체 | **위반**: per-item try/except 없음 → 한 item 실패 시 나머지 item 스킵 (B2-03-03) |
| 01 leaf 핸들러 | `_handle_real_01_tick` tick_handlers.py:208-255 | O (전체) | 01 체결 처리 | 양호. try/except + log |
| 0d leaf 핸들러 | `_handle_real_0d_tick` tick_handlers.py:265-293 | O (전체) | 0D 호가 처리 | 양호 |
| PGM leaf 핸들러 | `_handle_real_pgm_tick` tick_handlers.py:302-333 | O (전체) | PGM 순매수 처리 | 양호 |
| 0J leaf 핸들러 | `_handle_real_0j_tick` tick_handlers.py:92-104 | X | 0J 업종지수 처리 | **위반**: 다른 leaf는 try/except 있는데 0J만 없음 (B2-03-04). P23 일관성 위반 |
| 제어 신호 | `_process_control_signal` pipeline_compute.py:369-393 | O (전체) | 제어 신호 처리 | 양호 |
| 업종 재계산 신호 | `_handle_sector_recompute` pipeline_compute.py:425-433 | O (전체) | 재계산 처리 | 양호 |
| 수신율 계산 | `_calculate_receive_rate` pipeline_compute.py:149-161 | O (전체) | 수신율 계산 | 양호 |
| Phase 1 루프 | `_phase1_wait_threshold` pipeline_compute.py:588-635 | O (루프 본문) | 임계값 대기 | 양호. `except Exception: log+continue` |
| Phase 2 루프 | `_phase2_batch_recompute_loop` pipeline_compute.py:646-670 | X (루프 본문) | 업종 점수 전송/재계산 | **핵심 위반**: while 본문 무보호 (B2-03-01) |
| 업종 재계산 루프 | `_sector_recompute_loop_impl` pipeline_compute.py:681-686 | 부분 | Phase 1+2 전체 | **위반**: `except CancelledError`만 있고 `except Exception` 없음 (B2-03-02) |
| _flush_sector_recompute_impl | engine_sector_confirm.py:79-201 | O (전체) | 증분 재계산 | 양호. 내부 try/except |
| notify_desktop_sector_scores | engine_account_notify.py:191-220 | 부분 | 업종 점수 전송 | 임계값 게이트 try/except(195-201) 있으나 본문 무보호. _safe_broadcast는 try/except(67-70) |
| 게이트웨이 루프 | `_broadcast_loop` pipeline_gateway.py:67-80 | O (루프 본문) | broadcast_queue 처리 | 양호. `except Exception: log+continue` |
| 게이트웨이 전송 | `_process_broadcast`/`_send_to_websocket` pipeline_gateway.py:92-120 | O (각각) | 전송 처리 | 양호 |
| 게이트웨이 태스크 | `start_gateway_loop` pipeline_gateway.py:32 | X (done_callback) | 태스크 실패 로깅 | **위반**: compute 서브태스크는 done_callback 있는데 게이트웨이는 없음 (B2-03-05). 단 app.py:63에서 외부 done_callback 추가됨 — 본 파일 내 일관성 위반 |

#### 5.1.3 사전 위반 후보(1.7절) 확정 결과

- `pipeline_compute.py:209,214` create_task 직접 호출 — **위반 아님**
  - `start_compute_loop`는 `engine_loop.py:296`에서 `await start_compute_loop()`로 호출 — 이미 엔진 이벤트 루프 안에서 실행
  - `schedule_engine_task`는 UI 스레드(이벤트 루프 없음)에서 크로스 스레드 스케줄링용 (`call_soon_threadsafe`). 이미 루프 안에서는 폴백 경로(engine_lifecycle.py:299-302)와 동일한 `create_task + add_done_callback` 패턴 사용
  - 209-213, 215-218: done_callback 로깅 있음 → P25 격리 확보, P23 일관성 유지

#### 5.1.4 B1-02-05/06 호출부 격리 확인 (세션 2에서 이월)

- **B1-02-05** (`_handle_real_00` 내 `on_fill_update`/`_on_fill_after_ws` 무보호):
  - 호출부: `_dispatch_real_item` (pipeline_compute.py:487) → `_handle_real_tick` (519-528) try/except
  - ✅ 루프 전파 차단: compute 루프로 전파 안 됨
  - ❌ 형제 item 손실: per-item try/except 없음 → 같은 REAL 틱의 나머지 item 스킵 (B2-03-03)
  - **결론**: 등급 LOW 유지. 본문 try/catch는 선택적(루프 전파는 호출부가 차단). 형제 item 손실 방지 위해 per-item try/except 권장

- **B1-02-06** (`_handle_real_balance` 내 `_apply_balance_realtime` 무보호):
  - 호출부: `_dispatch_real_item` (pipeline_compute.py:492) → 동일 경로
  - **결론**: B1-02-05와 동일. 등급 LOW 유지

#### 5.1.5 _phase2_batch_recompute_loop vs _compute_loop_impl 비대칭 (P23 위반)

| 루프 | while 본문 try/except | except Exception | 비고 |
|------|----------------------|------------------|------|
| `_compute_loop_impl` (286-313) | O (287-317) | O (316-317) log+continue | P25 준수 |
| `_phase1_wait_threshold` (588-634) | O (589-635) | O (634-635) log+continue | P25 준수 |
| `_phase2_batch_recompute_loop` (646-670) | X | X | **위반** (B2-03-01) |
| `_sector_recompute_loop_impl` (681-686) | — | X (CancelledError만) | **위반** (B2-03-02) |

동일한 while 루프 패턴이 4곳에서 사용되는데 2곳만 보호되고 2곳은 미보호. P23 일관성 위반 + P25 위반.

### 5.2 위반 목록

| ID | 등급 | 파일:줄 | 위반 요약 | 수정 방향 (참고용, 승인 시 별도 세션) |
|----|------|---------|-----------|---------------------------------------|
| B2-03-01 | HIGH | pipeline_compute.py:646-670 | `_phase2_batch_recompute_loop` while 루프 본문에 try/except 없음. `notify_desktop_sector_scores`/`_flush_sector_recompute_impl` 무보호 호출이 throw 시 태스크 영구 종료 | while 루프 본문을 try/except로 감싸고, `except asyncio.CancelledError: break` + `except Exception: logger.error(..., exc_info=True)` + continue. `_compute_loop_impl`(314-317) 패턴과 일치시켜 P23 준수 |
| B2-03-02 | MEDIUM | pipeline_compute.py:673-686 | `_sector_recompute_loop_impl`이 `except CancelledError`만 있고 `except Exception` 없음. B2-03-01 상위 원인 | `except asyncio.CancelledError` 후 `except Exception: logger.error(..., exc_info=True)` 추가. 단 B2-03-01 수정 시 본 함수는 Phase 1/2 진입만 감싸므로 자연 해결 가능 |
| B2-03-03 | LOW | pipeline_compute.py:521-526 | `_handle_real_tick` for item 루프에 per-item try/except 없음. 한 item 실패 시 같은 REAL 틱의 나머지 item 스킵 | for 루프 본문을 per-item try/except로 감싸고, `except Exception: logger.error("[연산] 아이템 처리 오류 (계속): %s", e, exc_info=True)`. `_process_tick_batch`(262-267) 패턴과 일치 |
| B2-03-04 | LOW | pipeline_compute_tick_handlers.py:92-104 | `_handle_real_0j_tick`에 try/except 없음. 다른 leaf 핸들러(01/0d/PGM)는 try/except 있는데 0J만 없음 → P23 일관성 위반 | `_handle_real_0j_tick` 본문을 try/except로 감싸고, `except Exception: logger.error("[연산] 업종지수 틱(0J) 처리 오류: %s", e, exc_info=True)`. 다른 leaf 핸들러 패턴과 일치 |
| B2-03-05 | LOW | pipeline_gateway.py:32 | `start_gateway_loop`가 `_gateway_task`에 done_callback 없음. compute 서브태스크는 done_callback 있는데 게이트웨이는 없음 → P23 일관성 위반 | `_gateway_task.add_done_callback(lambda t: logger.warning("[연결] 게이트웨이 루프 작업 실패: %s", t.exception()) if t.exception() else None)` 추가. 단 app.py:63에서 외부 done_callback 있으나 본 파일 내 일관성은 본문에서 유지 |

### 5.3 교차 원칙 점검 (세션 3 범위)

| 원칙 | 해당 여부 | 비고 |
|------|-----------|------|
| P7 (블로킹 금지) | 해당 | B2-03-01: Phase 2 루프 사망 = 업종 점수 갱신 블로킹. B2-03-03: 한 item 실패 시 같은 프레임 나머지 item 시세 갱신 블로킹 |
| P9 (파이프라인 독립) | 해당 | B2-03-01: compute 루프와 sector 재계산 루프는 독립 태스크이나 Phase 2 사망 시 업종 점수 파이프라인 전체 중단. 게이트웨이 루프는 독립 유지 |
| P16 (살아있는 경로) | 해당 | B2-03-01/02: Phase 2 루프 사망 시 경로가 살아있지 않음. done_callback은 로깅만 하고 재시작 안 함 |
| P20 (폴백 금지) | 해당 아님 | 본 세션에서 silent `except: pass` 없음. 모든 catch는 logger.error/warning + exc_info=True. 무보호 호출(B2-03-01~04)은 catch 자체가 없어 P20 대상 아님 |
| P23 (일관성) | 해당 | B2-03-02: `_compute_loop_impl`은 `except Exception` 있는데 `_sector_recompute_loop_impl`은 없음 — 비대칭. B2-03-04: leaf 핸들러 4개 중 0J만 try/except 없음. B2-03-05: compute는 done_callback 있는데 gateway는 없음. 사전 위반 후보 create_task 직접 호출은 위반 아님(5.1.3) |

### 5.4 양호 항목 (P25 준수 확인)

- `_compute_loop_impl` (pipeline_compute.py:278-319): while 루프 try/except, `except Exception: log+continue`. **P25 준수**
- `_process_tick_batch` (pipeline_compute.py:256-276): per-event try/except (262-267). **P25 준수**
- `_process_control_signal` (pipeline_compute.py:358-393): try/except 전체. **P25 준수**
- `_handle_sector_recompute` (pipeline_compute.py:416-433): try/except 전체. **P25 준수**
- `_calculate_receive_rate` (pipeline_compute.py:135-161): try/except 전체. **P25 준수**
- `_phase1_wait_threshold` (pipeline_compute.py:569-635): while 루프 try/except, `except Exception: log+continue`. **P25 준수**
- `_handle_real_01_tick` (tick_handlers.py:196-256): try/except 전체. **P25 준수**
- `_handle_real_0d_tick` (tick_handlers.py:259-293): try/except 전체. **P25 준수**
- `_handle_real_pgm_tick` (tick_handlers.py:296-333): try/except 전체. **P25 준수**
- `_flush_sector_recompute_impl` (engine_sector_confirm.py:66-201): try/except 전체 (200-201). **P25 준수**
- `_safe_broadcast` (engine_account_notify.py:64-70): try/except. **P25 준수**
- `_broadcast_loop` (pipeline_gateway.py:62-80): while 루프 try/except, `except Exception: log+continue`. **P25 준수**
- `_process_broadcast`/`_send_to_websocket` (pipeline_gateway.py:83-120): 각각 try/except. **P25 준수**
- `pipeline_compute.py:209,214` create_task 직접 호출: 엔진 루프 안에서 호출, done_callback 있음. schedule_engine_task 불필요. **위반 아님**
- app.py:62-63 게이트웨이 태스크: 외부 done_callback 추가. **P25 준수** (단 pipeline_gateway.py 내부 일관성은 B2-03-05)

---

## 6. 세션 4: A2 Store listener 조사

> 상태: 완료 (2026-07-23)
> 조사 파일: `frontend/src/stores/store.ts` (57줄), `hotStore.ts` (607줄), `uiStore.ts` (256줄), `stockClassificationStore.ts` (54줄)
> 보조 파일: `frontend/src/stores/index.ts` (5줄), `frontend/src/binding.ts` (338줄) — setState 호출부·updater 함수 본문 확인용
> 조사 범위:
> - `store.ts:40-46` listener 루프 try/catch 검증 (F-02 해결 시 추가됨)
> - `store.ts:19` updater 함수 `partial(state)` try/catch 외부 여부
> - `hotStore.ts` apply* 함수 13개의 setState 경로 — listener throw 유발 가능성
> - `uiStore.ts` apply* 함수 16개의 setState 경로
> - `stockClassificationStore.ts` setState 경로
> - `binding.ts` 직접 setState 호출 6곳 (sector-stocks-delta, buy-targets-delta, buy-history-append, sell-history-append, receive-rate, sector-scores) — updater 함수 본문 throw 가능성
> - `hotStore.ts` CustomEvent dispatchEvent 4곳 — 핸들러 throw 시 전파 경로

### 6.1 조사 결과

**핵심 구조**: `createStore`(`store.ts:10-56`)는 단일 진실 소스 패턴. `setState`(18-47)는 (1) updater 함수 실행(19) → (2) shallow merge + Object.is 변경 감지(22-33) → (3) state 교체(35) → (4) listener 루프 통지(40-46) 순서. listener 루프(40-46)는 try/catch + `console.error('[Store] listener error', e)`로 보호 — **F-02 fix로 P25 준수**. silent pass 아님 (P20 준수).

**위반 2건 식별**:

- **A2-04-01 (MEDIUM)**: `store.ts:19` updater 함수 `partial(state)`가 try/catch **밖**. updater 함수 본문이 throw하면 listener 루프(40-46)에 도달하지 않고 setState 호출자에게 즉시 전파. setState 호출자는 `binding.ts` onEvent 핸들러(A1-01-04 — try/catch 없음) → WS 디스패치 `_dispatchMessage` `forEach(h => h(data))`(A1-01-01)로 전파 → 같은 이벤트의 후속 핸들러 미실행 + 같은 바이너리 프레임 후속 이벤트 손실. listener 루프 보호가 updater 단계에서 무력화되는 구조적 취약점.
  - throw 유발 가능 updater 함수 (복잡도 높은 순):
    - `binding.ts:116-160` buy-targets-delta — `normalizeStockCode`, `findIndex`, `recalcTradeAmountRank`, `rebuildBuyTargetIndex`, 중첩 property access. added/removed/changed 가드는 있으나 `state.sectorStocks[normalizeStockCode(item.code)]` 접근 중 `item.code` undefined 시 `normalizeStockCode` 내부 `code.includes('_')` throw
    - `binding.ts:97-111` sector-stocks-delta — `stocksToMap(added)`, `normalizeStockCode(code)` 루프
    - `hotStore.ts:134-166` applyAccountUpdate delta 경로 — `normalizeStockCode`, `splice`, `findIndex`, `rebuildPositionIndex`
    - `hotStore.ts:453-482` applyRealtimeReset — `nullifyFields`, `Object.entries`, `rebuildPositionIndex`
    - `uiStore.ts:206-221` applyIndexData — `data.upcode`/`data.broker_statuses`/`data.market_phase` 접근
  - 실제 throw 확률은 낮으나(대부분 가드 존재), 구조적 보호 부재는 P25 위반. 한 updater throw가 전체 WS 디스패치 체인을 중단시킬 수 있음.

- **A2-04-02 (MEDIUM)**: `hotStore.ts:367-370,390,412,431` `window.dispatchEvent(new CustomEvent(...))`가 try/catch **밖**. CustomEvent 핸들러(`real-data-tick`, `orderbook-tick`, `program-tick`)가 throw하면 `applyRealData`/`applyOrderbookUpdate`/`applyProgramUpdate` 호출자로 전파 → `binding.ts` 핸들러(170-180, try/catch 없음) → WS 디스패치로 전파. `real-data-tick`은 고빈도(매 틱마다 발생), 핸들러는 UI 컴포넌트에서 `addEventListener`로 등록하므로 한 컴포넌트 핸들러 오류가 같은 틱의 다른 종목 시세 갱신을 막을 수 있음.
  - 발생 위치: `applyRealData`(390 — 매 틱, 367-370 — rank-0 변경 시), `applyOrderbookUpdate`(412), `applyProgramUpdate`(431)
  - 단 이 위반의 핸들러 등록부는 A3(UI 컴포넌트 렌더링, 세션 7) 영역에서 본격 조사 예정. 본 세션에서는 dispatchEvent 호출부 전파 경로만 식별.

**양호 항목**:
- `store.ts:40-46` listener 루프 try/catch + `console.error('[Store] listener error', e)` — **P25 준수** (F-02 fix). silent pass 아님 (P20 준수).
- `store.ts:22-33` shallow merge + Object.is 변경 감지 — 변경된 키가 있을 때만 state 교체 + listener 통지. 불필요한 리렌더 방지. **P24 단순성 준수**.
- `store.ts:49-54` subscribe/unsubscribe — Set 기반, 반환된 unsubscribe 함수로 정리. **P25 준수** (listener 누적 방지).
- `hotStore.ts` apply* 함수 13개(`applyAccountUpdate`, `applyRealData`, `applyOrderbookUpdate`, `applyProgramUpdate`, `applyRealtimeReset`, `applyBuyTargetsUpdate`, `applySectorScores`, `applySectorStocksRefresh`, `applyOrderFilled`, `applySellHistoryUpdate`, `applyBuyHistoryUpdate`, `applyDailySummaryUpdate`, `applyInitialSnapshotHot`) — 모두 `hotStore.setState()` 경유. setState 내부 listener 루프 보호됨. **P25 준수** (updater 본문 제외 — A2-04-01).
- `uiStore.ts` apply* 함수 16개(`applyAvgAmtProgress`, `applyBootstrapStage`, `applySettingsChanged`, `applyEngineReloadComplete`, `applyCircuitBreakerOpen`, `clearCircuitBreakerOpen`, `applyOrderTimeBlocked`, `clearOrderTimeBlocked`, `applyRiskBlockStatus`, `clearRiskBlockStatus`, `applyBuyLimitStatus`, `applyTestDataResetCompleted`, `applyWsSubscribeStatus`, `applyMarketPhase`, `applyIndexData`, `setSelectedSector`, `applyInitialSnapshotUI`) — 모두 `uiStore.setState()` 경유. **P25 준수** (updater 본문 제외 — A2-04-01).
- `stockClassificationStore.ts:34-45` `applyStockClassificationChanged` — `stockClassificationStore.setState()` 경유. **P25 준수**.
- `hotStore.ts:98-109` `recalcTradeAmountRank` — `targets.filter().sort()` 후 rank 할당. 순수 함수, throw 가능성 낮음. 다만 `binding.ts:157` buy-targets-delta updater 내부에서 호출되므로 A2-04-01 경로에 포함.
- `hotStore.ts:71-95` `rebuildBuyTargetIndex`/`rebuildPositionIndex` — Map 구축. 순수 함수. `binding.ts:158`에서 updater 내부 호출 — A2-04-01 경로 포함.
- `hotStore.ts:15-23` `normalizeStockCode` — `code.includes('_')`에서 code undefined 시 throw. 다수 apply* 함수에서 호출. A2-04-01 경로의 주요 throw 소스 후보.

**교차 원칙 점검**:
- **P25**: listener 루프 자체는 준수. updater 함수(19)와 dispatchEvent(367-431)가 보호 우회 경로.
- **P20**: `console.error` 로깅으로 silent pass 아님. 양호.
- **P23**: 3개 store(hot/ui/stockClassification) 모두 동일 `createStore` 패턴 사용 — 일관성 준수. 단 updater 보호 부재가 3개 store에 공통 적용되어 일관된 취약점.
- **P16**: listener 루프 보호는 살아있는 경로. updater 보호 부재는 실제 throw 시에만 발현.
- **P21**: listener 오류 시 `console.error`로 개발자 알림. 사용자 직접 투명성은 A3(세션 7)에서 UI 표시 여부 점검 예정.

**수정 방향 (참고용, 승인 시 별도 세션)**:
- A2-04-01: `setState` 본문을 try/catch로 감싸거나, updater 함수 호출(19)을 try/catch로 감싸고 실패 시 로깅 후 early return. `store.ts` 단일 파일 수정으로 3개 store 모두 보호. P24 단순성 — `createStore` 한 곳에서 보호하므로 중복 추상화 아님.
- A2-04-02: `applyRealData`/`applyOrderbookUpdate`/`applyProgramUpdate` 내 `window.dispatchEvent`를 try/catch로 감싸거나, CustomEvent 핸들러 등록부(A3 영역)에서 try/catch 추가. dispatchEvent 호출부 보호가 더 근본적. 단 A3(세션 7)에서 핸들러 등록 패턴 조사 후 결정 권장.

### 6.2 위반 목록

| ID | 영역 | 파일:줄 | 위반 내용 | 영향 범위 | 등급 | 관련 원칙 | 조사 세션 | 수정 승인 |
|----|------|---------|-----------|-----------|------|-----------|-----------|-----------|
| A2-04-01 | A2 Store listener | `frontend/src/stores/store.ts:19` | `setState`의 updater 함수 `partial(state)`가 try/catch 밖. updater 본문 throw 시 listener 루프(40-46) 보호 우회, setState 호출자에게 즉시 전파 → binding.ts 핸들러(A1-01-04) → WS 디스패치(A1-01-01)로 전파 → 같은 이벤트 후속 핸들러 미실행 + 같은 바이너리 프레임 후속 이벤트 손실 | 고빈도 이벤트(real-data, buy-targets-delta, account-update)의 updater throw 시 화면 갱신 전체 중단 위험. throw 확률은 낮으나 구조적 보호 부재 | MEDIUM | P25, P16 | 세션 4 | 미승인 |
| A2-04-02 | A2 Store listener | `frontend/src/stores/hotStore.ts:367-370,390,412,431` | `window.dispatchEvent(new CustomEvent(...))`가 try/catch 밖. CustomEvent 핸들러(real-data-tick/orderbook-tick/program-tick) throw 시 apply* 함수 호출자로 전파 → binding.ts 핸들러 → WS 디스패치로 전파. real-data-tick은 매 틱 발생 | 한 UI 컴포넌트 핸들러 오류가 같은 틱의 다른 종목 시세 갱신 중단. 핸들러 등록부는 A3(세션 7)에서 조사 예정 | MEDIUM | P25, P7 | 세션 4 | 미승인 |

---

## 7. 세션 5: B3 대형 스케줄러·파이프라인 조사

> 상태: 완료 (2026-07-23)
> 조사 파일: `daily_time_scheduler.py` (1524줄), `market_close_pipeline.py` (1407줄), `engine_lifecycle.py` (328줄, schedule_engine_task 정의 확인용)
> 조사 범위:
> - `daily_time_scheduler.py` schedule_engine_task 15회 호출별 context 명시·격리 여부
> - `market_close_pipeline.py` except 블록 19개 — silent pass 여부 (P20 교차), exc_info 로깅 여부
> - 파이프라인 단계 간 실패 전파 경로 (P9 교차)
> - `call_later` / `call_soon_threadsafe` 콜백 실패 시 루프 영향

### 7.1 조사 결과

**1. schedule_engine_task 15회 호출 격리 (daily_time_scheduler.py)** — 양호
- 14회 실제 호출 + 1회 import. 모두 `schedule_engine_task(coro, context="...")` 일관 패턴 (P23 OK)
- `engine_lifecycle.py:279-309` 정의: `loop.call_soon_threadsafe(_create_with_callback)` + `task.add_done_callback(lambda t: logger.warning(...) if t.exception() else None)` → 태스크 실패 시 경고 로깅, 루프 중단 없음 → **P25 격리 준수**
- call_soon_threadsafe 자체 실패 시 `coro.close()` 정리 → OK
- 15회 모두 동일 패턴, 격리 일관적

**2. except 블록 silent pass 여부 (P20)**
- **market_close_pipeline.py 19개**: silent pass 1건(492 float 변환 `pass`), 빈 폴백 1건(897 `confirmed={}`), exc_info 누락 5건(424, 858, 934, 1103, 1254), raise 전파 1건(385 의도적), 나머지 11건 logger.warning+exc_info OK
- **daily_time_scheduler.py 26개**: silent pass 0건, exc_info 누락 6건(1273, 1287, 1327, 1354, 1446, 1507), RuntimeError→return 3건(1085, 1372, 1458 의도적 루프 없음 시 스킵), 나머지 17건 OK

**3. 파이프라인 단계 간 실패 전파 (P9)**
- `_run_confirmed_pipeline` (976-1064): 1~4단계 None 반환 시 즉시 `return {"fetched":0,"failed":0,"cached":False}` → 전파 명시적. 단 실패 상태 알림 필드 없어 fetched=0이 정상 0건인지 실패인지 구분 안 됨 → **P21 부분 위반**
- 5단계 `confirmed={}` 폴백(897) → `if confirmed` 가드로 메모리/DB 보호되나, `_run_post_confirmed_pipeline(eligible_codes=confirmed_codes)`는 여전히 실행 → 빈 eligible로 캐시 저장 시도
- 7단계 `_step7_recompute_and_broadcast` except(972) → logger.warning+exc_info → 격리 OK
- finally 플래그 복원 → OK

**4. call_later/call_soon_threadsafe 콜백 실패 시 루프 영향** — 양호
- daily_time_scheduler.py call_later 3곳(1116, 1401, 1465): 모두 `lambda: schedule_engine_task(coro, context=...)` → schedule_engine_task 내부 try/except로 보호되어 lambda 예외 거의 불가능. lambda 자체 예외 시 asyncio "Exception in callback" 경고, 루프 중단 없음 → **P25 OK**
- market_close_pipeline.py call_soon_threadsafe 1곳(68): `lambda: q.put_nowait(data) if not q.full() else None` + 외부 try/except(44-73) → 실패 시 logger.warning → OK. 단일 루프 스레드이므로 full()/put_nowait 레이스 없음

### 7.2 위반 목록

| ID | 등급 | 파일:줄 | 위반 | 관련 원칙 |
|----|------|---------|------|-----------|
| B3-05-01 | HIGH | `market_close_pipeline.py:645-650` | `_save_confirmed_cache` inner except에서 rollback+warning 후 fall-through → 650 `return True` → 전종목 마스터 테이블 DB 저장 실패해도 함수 True 반환. 후속 6단계 메모리 교체 로직이 잘못된 성공 전제로 진행 | P22, P21 |
| B3-05-02 | MEDIUM | `market_close_pipeline.py:897` | `_step5_download_daily_confirmed`에서 `confirmed = {}` 빈 폴백. if confirmed 가드로 메모리/DB는 보호되나, 빈 eligible_codes로 `_run_post_confirmed_pipeline` 실행 → 빈 캐시 저장 시도 | P20 |
| B3-05-03 | LOW | `market_close_pipeline.py:492` | `except (ValueError, TypeError): pass` silent pass. float 변환 실패 시 strength_str 갱신 스킵만 하고 종목 루프 계속 (로깅 없음) | P20 |
| B3-05-04 | LOW | 11곳 | exc_info 누락: `market_close_pipeline.py` 424, 858, 934, 1103, 1254 + `daily_time_scheduler.py` 1273, 1287, 1327, 1354, 1446, 1507. logger.warning은 하나 exc_info=True 누락. 단 934는 "(무시)" 표시로 의도적 일부 드러남 | P23 |

### 7.3 양호 항목
- schedule_engine_task 15회 호출 모두 P25 격리 준수 (add_done_callback)
- call_later 3곳 + call_soon_threadsafe 1곳 모두 보호 (schedule_engine_task 경유 또는 외부 try/except)
- 45개 except 중 28개 logger.warning+exc_info=True로 P25 준수
- RuntimeError→return 3건(1085, 1372, 1458) 의도적 스킵 (루프 없음 시)
- _run_confirmed_pipeline 1~4단계 None 반환 패턴 명시적
- _step7_recompute_and_broadcast·finally 플래그 복원 격리 OK

---

## 8. 세션 6: B4 워커·IO·재시도 루프 조사

> 상태: 완료 (2026-07-23)
> 조사 파일: `notification_worker.py`, `db_writer.py`, `telegram_bot.py`, `kiwoom_rest.py`, `kiwoom_stock_rest.py`, `engine_cache.py`, `app.py`, `ws.py`, `ws_settings.py`, `ws_orders.py`
> 조사 범위:
> - `notification_worker.py:55` `_consume_loop` while 루프 예외 격리
> - `kiwoom_rest.py:377,383` / `kiwoom_stock_rest.py:156,321` while 재시도 루프 실패 시 전파
> - `ws.py:171` WS 서버 while 루프 — 클라이언트별 격리
> - `ws_settings.py:29`, `ws_orders.py:29` WS 루프
> - `app.py:62,141,146` 시작 태스크 실패 시 기동 블로킹 여부 (P25 핵심 — 기동 블로킹 금지)

### 8.1 조사 결과

**전반적 평가**: 대부분의 while 루프와 재시도 루프는 P25(격리된 실패)와 P1-P3(async 일관성)를 잘 준수. IO는 전부 async(httpx.AsyncClient, aiosqlite)이고 동기 블로킹 I/O는 발견되지 않음. 백그라운드 태스크들은 `add_done_callback`로 조용히 사망 시 로깅 처리.

**파일별 상세**:

1. **notification_worker.py** — 양호
   - `_consume_loop` (53-65): while 루프, `await _handle(msg)` 예외 시 `logger.warning` 후 계속, `finally: task_done()`. CancelledError는 break.
   - `enqueue` (41-51): `put_nowait` + QueueFull 로깅. 논블로킹 OK.
   - `shutdown` (78-93): `asyncio.wait_for(queue.join(), timeout=10.0)` graceful. OK.

2. **db_writer.py** — 잠재 이슈 1건
   - `_db_writer_loop` (53-88): `asyncio.wait`로 shutdown_event + queue get 동시 대기. 예외 시 `logger.error(..., exc_info=True)` 후 계속.
   - **이슈**: `_process_operation`이 실패해 `raise`하면 line 79의 `task_done()`이 스킵됨 → 큐 미완료 카운트 누적. graceful shutdown 경로에서 `queue.join()`이 무한 대기할 가능성. 단, `stop_db_writer`는 cancel + 큐 비우기로 회피하므로 실제 발현은 제한적.
   - IO: aiosqlite async + `get_db_lock()`. OK.

3. **telegram_bot.py** — 양호
   - `_poll_loop` (88-111): while 루프, 예외 시 `had_error=True` + 로깅 + 2초 sleep 후 재시도. CancelledError break. 활성 설정 없으면 자동 종료.
   - `_poll_one` (144-197): httpx async, 예외 시 로깅 후 return(다음 폴링에서 재시도). atexit 예외 시 루프 중단. OK.
   - `asyncio.gather(*tasks, return_exceptions=True)`로 개별 폴링 예외 격리. OK.

4. **kiwoom_rest.py** — 잠재 이슈 1건
   - `_call_api` (125-197): 재시도 루프, 429 adaptive backoff, 예외 시 `_reset_client` 후 재시도. 모두 실패 시 `(None, hit_429)`. 양호.
   - `_issue_token` (199-266): 3회 재시도, 429 sleep. 양호.
   - **이슈**: `_request` (317-357)는 예외 시 재시도 없이 즉시 `return None` (line 353-356). `_call_api`는 예외 시 재시도하는데 일관성 부족(P23). 의도적일 수 있으나 확인 필요.
   - `_paginated_request` (359-422): 페이지네이션 while + 429 내부 재시도 3회. 예외 시 부분 결과 반환. 양호.
   - IO: 전부 httpx async. OK.

5. **kiwoom_stock_rest.py** — 양호
   - `fetch_ka10081_daily_5d_data` (138-218): while True 페이지네이션, resp 없음/예외 시 break. OK.
   - `_fetch_all_stocks_ka10081` (221-): for 루프, 예외 시 `failed_codes` 추가 후 계속. 양호.
   - IO: 전부 async. OK.

6. **engine_cache.py** — 잠재 이슈 1건
   - `_load_caches_preboot` (14-149): 단일 try-except.
   - **이슈**: line 148-149에서 치명적 오류(`RuntimeError("master_stocks_table 테이블에 데이터가 없습니다")` line 28 포함)를 "무시, 기존 흐름으로 진행"으로 처리. **P20(폴백 금지) 위반 소지** — master_stocks_table 없음이 치명적인데 폴백으로 덮음.
   - 백그라운드 태스크(line 134-136, 143-144)는 `add_done_callback`로 실패 로깅. P25 준수.

7. **app.py** — 양호
   - lifespan (32-195): startup/shutdown. 백그라운드 태스크 전부 `add_done_callback`로 실패 로깅. P25 준수.
   - `global_exception_handler` (245-271): 예외 로깅 + 텔레그램 알림(5분 쿨다운). OK.
   - IO: 전부 async. OK.

8. **ws.py / ws_settings.py / ws_orders.py** — 양호 (동일 패턴)
   - 세 파일 모두 while True 수신 루프, `WebSocketDisconnect` pass, 기타 예외 `logger.warning`, finally `unregister`.
   - `_send_initial_snapshot_delayed`는 이벤트 대기 기반(폴링 없음), 예외 시 로깅. OK.
   - IO: 전부 async. OK.

**IO 블로킹 여부**: 발견 없음. 모든 I/O는 async(httpx.AsyncClient, aiosqlite, asyncio.Queue/Event) 기반. 동기 `requests`, `sqlite3`, `time.sleep`, `threading` 사용 없음.

### 8.2 위반 목록

| ID | 심각도 | 파일:줄 | 내용 | 관련 원칙 |
|----|--------|---------|------|-----------|
| B4-06-01 | MEDIUM | `db_writer.py:79` | `_process_operation` 실패 시 `task_done()` 스킵 → 큐 미완료 카운트 누적, graceful shutdown 시 `queue.join()` 무한 대기 위험 | P25 부분 |
| B4-06-02 | LOW | `kiwoom_rest.py:353-356` | `_request` 예외 시 재시도 없이 즉시 `return None` — `_call_api`와 일관성 부족 | P23(일관성) |
| B4-06-03 | MEDIUM | `engine_cache.py:148-149` | 치명적 오류(RuntimeError 포함)를 "무시하고 진행" — master_stocks_table 없음이 치명적인데 폴백 처리 | P20(폴백 금지) |

### 8.3 양호 항목 (P25 준수 확인)

- `notification_worker._consume_loop`: 예외 격리 + finally task_done + CancelledError break — P25 OK
- `telegram_bot._poll_loop`: had_error 플래그 + 2초 sleep 재시도 + gather return_exceptions — P25 OK
- `kiwoom_rest._call_api`: 429 adaptive backoff + 예외 시 재시도 + _reset_client — P25 OK
- `kiwoom_rest._paginated_request`: 부분 결과 반환 + 429 내부 재시도 — P25 OK
- `kiwoom_stock_rest._fetch_all_stocks_ka10081`: failed_codes 추적 후 루프 계속 — P25 OK
- `app.py` 백그라운드 태스크 3곳(62, 141, 146): add_done_callback 실패 로깅 — P25 OK
- `ws.py/ws_settings.py/ws_orders.py` 수신 루프: WebSocketDisconnect pass + 기타 예외 로깅 + finally unregister — P25 OK
- IO 전부 async: P1-P3 준수

---

## 9. 세션 7: A3 UI 컴포넌트 렌더링 조사

> 상태: 미시작
> 조사 파일: 36개 파일 (pages/*, components/common/*, layout/*)
> 조사 범위:
> - `subscribe()` 리스너 내부 렌더링 실패 시 전파
> - `addEventListener` 콜백 실패 시 전파
> - 컴포넌트 팩토리 내부 DOM 조작 예외 처리
> - 개별 칩/컴포넌트 렌더링 실패가 전체 화면 중단 유발 여부 (F-02 사례와 동일 패턴)

### 9.1 조사 결과
_작성 예정_

### 9.2 위반 목록
_작성 예정_

---

## 10. 세션 8: B5 매매·테스트모드 태스크 조사

> 상태: 미시작
> 조사 파일: `trading.py`, `buy_order_executor.py`, `dry_run.py`
> 조사 범위:
> - `trading.py:477,666` dry_run fake_fill create_task 직접 호출 (P23 위반 후보)
> - `add_done_callback` 로깅 실제 발화 여부 (P16 교차)
> - 매매 경로 예외 전파 — 매수/매도 실패 시 엔진 루프 영향
> - safe-trade 스킬 연계 (거래 로직 수정 시 별도 스킬 필수)

### 10.1 조사 결과
_작성 예정_

### 10.2 위반 목록
_작성 예정_

---

## 11. 세션 9: 교차 점검·총합 보고

> 상태: 미시작
> 조사 범위: 세션 1~8 결과 취합 + 교차 원칙 매트릭스 작성 + 우선수정 추천

### 11.1 P25 위반 전체 목록 (취합)
_세션 1~8 완료 후 본 섹션 2 매트릭스와 연동_

### 11.2 교차 원칙 매트릭스 (빈 템플릿)

| 위반 ID | P25 | P7 | P9 | P16 | P20 | P23 | 비고 |
|---------|-----|----|----|-----|-----|-----|------|
| _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ |

### 11.3 우선수정 추천 (영향도 순)
_세션 1~8 완료 후 작성_

### 11.4 조사 완료 정의
- 본 보고서 섹션 2 매트릭스에 모든 위반 누적 완료
- 교차 원칙 매트릭스 (11.2) 작성 완료
- 우선수정 추천 (11.3) 작성 완료
- 각 위반에 대해 별도 수정 세션 승인 대기 상태로 이관

---

## 12. 변경 이력

| 날짜 | 세션 | 변경 내용 |
|------|------|-----------|
| 2026-07-23 | (준비) | 본 보고서 생성 (조사 개요, 매트릭스 빈 템플릿, 세션 1~9 기본 구조) |
| 2026-07-23 | 세션 1 | A1 WS 디스패치 조사 완료. 위반 5건 식별 (A1-01-01~05). 섹션 2 매트릭스 + 섹션 3 결과 작성. CRITICAL 2건, HIGH 1건, MEDIUM 1건, LOW 1건 |
| 2026-07-23 | 세션 2 | B1 엔진 코어 루프 조사 완료. 위반 7건 식별 (B1-02-01~07). 섹션 2 매트릭스 + 섹션 4 결과 작성. HIGH 2건, MEDIUM 2건, LOW 3건. 사전 위반 후보 engine_loop.py:343-344는 위반 아님으로 확정. schedule_engine_task 중앙 격리 메커니즘 P25 준수 확인. 커넥터 recv 루프 P23 일관성 확인 |
| 2026-07-23 | 세션 3 | B2 파이프라인 연산 루프 조사 완료. 위반 5건 식별 (B2-03-01~05). 섹션 2 매트릭스 + 섹션 5 결과 작성. HIGH 1건, MEDIUM 1건, LOW 3건. 사전 위반 후보 pipeline_compute.py:209,214 create_task 직접 호출은 위반 아님으로 확정 (엔진 루프 안 await 호출). B1-02-05/06 호출부 격리 확인 완료 (LOW 유지). while 루프 4곳 중 2곳만 보호되어 P23 비대칭 |
| 2026-07-23 | 세션 4 | A2 Store listener 조사 완료. 위반 2건 식별 (A2-04-01~02). 섹션 2 매트릭스 + 섹션 6 결과 작성. MEDIUM 2건. store.ts:40-46 listener 루프는 F-02 fix로 P25 준수 확인. 단 updater 함수(19)와 dispatchEvent(367-431)가 listener 루프 보호 우회 경로. 3개 store 동일 createStore 패턴 P23 일관성 준수 |
| 2026-07-23 | 세션 5 | B3 대형 스케줄러·파이프라인 조사 완료. 위반 4건 식별 (B3-05-01~04). 섹션 2 매트릭스 + 섹션 7 결과 작성. HIGH 1건, MEDIUM 1건, LOW 2건. schedule_engine_task 15회 호출 모두 P25 격리 준수 (add_done_callback). call_later 3곳+call_soon_threadsafe 1곳 모두 보호. 45개 except 중 28개 logger.warning+exc_info=True 준수. B3-05-01 (HIGH) DB 저장 실패를 True 반환하는 P22/P21 위반이 가장 심각 |
