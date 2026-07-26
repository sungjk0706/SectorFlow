# `engine_state` 상태 소유권 매트릭스

> 작성일: 2026-07-26
> 세션: COUPLING-S1 (C-01)
> 기준 파일: `backend/app/services/engine_state.py`
> 원칙: P10 SSOT, P16 살아있는 경로, P20 폴백 금지, P22 데이터 정합성, P23 일관성, P24 단순성, P25 격리된 실패
> 상태: 조사 전수 완료 (운영 코드 수정 없음, 매트릭스 문서만 작성)

---

## 1. 목적과 범위

`EngineState` 싱글톤(`engine_state.state`)이 보유한 69개 속성의 소유권을 실제 코드 참조로 확정한다. 각 속성별 `owner / readers / writers / 생명주기`를 기록하여:

- 단일 writer(단일 소유권) 속성과 다중 writer(산재) 속성을 구분한다.
- 다중 writer 중 "자연스러운 산재"(init/오류/성공 라이프사이클 협업)와 "단일화 후보"(변경 허브)를 구분한다.
- 헬퍼 경유 단일화 패턴(`_mark_realtime_reset_done()` 등)과 거래 관련 산재(변경 금지)를 명시한다.
- dead code 후보를 식별한다.

본 세션은 매트릭스 작성까지만 수행하며, 속성별 읽기·쓰기 경계 좁히기는 후속 세션에서 가장 위험도가 높은 1개 속성만 별도 승인 후 진행한다.

### 조사 방법

- `engine_state`를 import하는 38개 파일을 `from ... import state` / `from ... import engine_state` 두 패턴으로 전수 검색
- 각 속성별로 `state.<prop>` / `engine_state.state.<prop>` 참조를 grep 후 read로 read/write 구분
- helper 함수(`_get_account_rest_lock`, `_notify_reg_ack`, `_get_rest_api_thread_sem`, `_mark_realtime_reset_done`, `_set_latest_filter_summary_meta`, `_reset_confirmed_refresh_running`, `broadcast_ws_connection_status`, `_set_status`) 경유 간접 write 추적
- docstring(세션 10/11/12)에 기록된 기존 소유권 계약과 실제 코드 대조
- `backend/tests/` 모킹은 "writers (테스트)" 란에 요약 표기(모킹은 실제 소유권과 무관, 참고용)

### read vs write 분류 기준

- **read**: 속성을 참조만 (조건문, 인자, 반환, 비교, 메서드 호출의 수신자). `await state.X.wait()`, `state.X.get(k)`, `state.X.method()` 포함.
- **write**: 속성에 할당/수정. `state.X = v`(재할당), `state.X[k] = v`(dict 항목 쓰기), `state.X.append(v)`/`.clear()`/`.update()`(mutable 호출), `state.X.set()`/`.clear()`(LazyEvent 상태 변경) 포함.
- **helper 경유 write**: helper 함수 본체가 속성을 write하면 helper 정의 파일이 writer, 호출부는 "간접 writer (helper 경유)"로 별도 표기.

---

## 2. 전체 요약 (66개 속성)

### 2.1 소유권 패턴별 분류

| 패턴 | 속성 수 | 속성 목록 |
|------|--------|-----------|
| **단일 writer (소유권 명확)** | 36 | connector_manager, broker_spec, engine_user_id, ws_connection_status, quote_subscribed, account_rest_lock, account_snapshot, index_data_cache, market_phase, krx_circuit_breaker_active, news_boost_cache, news_keywords_cache, news_boost_score, news_boost_ttl_sec, last_reset_date, krx_remove_done, confirmed_done, auto_trade_timer_handles, midnight_timer_handle, timetable_timer_handle, last_ws_subscribe_start_date, last_krx_pre_subscribe_date, last_confirmed_download_date, last_jif_received_at, krx_countdown_override, nxt_countdown_override, engine_task, engine_loop_ref, realtime_latency_exceeded, data_ready_event, token_ready_event, bootstrap_event, engine_ready_event, server_ready_event, preboot_ready_event, confirmed_refresh_running_5d |
| **helper 경유 단일화 완료** | 5 | last_realtime_reset_date, confirmed_refresh_running_confirmed, latest_filter_summary_meta, reg_ack_event, sector_summary_cache(COUPLING-S1 후속) |
| **헬퍼 단일 writer (lazy init)** | 3 | rest_api_thread_sem, reg_seq_lock, account_rest_lock(단일 writer에도 포함) |
| **자연스러운 산재 (라이프사이클/이벤트 협업)** | 12 | running, degraded_mode, preboot_cache_loaded, position_build_failed, ws_reg_pipeline_done, sector_summary_ready_event, engine_stop_event, ws_window_changed_event, reg_ack_return_code, ws_account_subscribed, account_rest_bootstrapped, auto_trade |
| **다중 writer (단일화 후보)** | 8 | login_ok, access_token, broker_tokens, broker_rest_totals, broker_rest_apis, positions, master_stocks_cache(전체 재할당은 단일, 항목 쓰기 다중), sector_summary_ready_event(자연스러운 산재로 재분류됨) |
| **거래 관련 산재 (변경 금지)** | 3 | integrated_system_settings_cache, _last_global_buy_ts, _last_global_sell_ts |
| **상수 (쓰기 없음)** | 1 | REG_POST_ACK_GAP_SEC |
| **Dead code (DC-S2 제거 완료)** | 0 | shutdown_requested, confirmed_refresh_running, MIN_CACHE_LIFETIME_SEC — 모두 제거됨 |

> 합산 중복: 일부 속성은 여러 패턴에 걼. helper 경유 단일화 4개는 단일 writer로도 집계 가능. 최종 유효 단일 writer 수는 약 40개.

### 2.2 단일화 우선순위 (변경 허브 순)

| 순위 | 속성 | writer 수 | 비고 |
|------|------|-----------|------|
| 1 | `integrated_system_settings_cache` | 10+ | 거래 관련 산재 (세션 11 범위 외, 변경 금지 — 별도 승인 필요) |
| 2 | `sector_summary_cache` | 7 → 1 | ☑ 단일화 완료 (COUPLING-S1 후속) — `_set_sector_summary` 헬퍼 경유 |
| 3 | `master_stocks_cache` (항목 쓰기) | 다중 | 전체 재할당은 engine_cache 단일, 항목 쓰기(_subscribed 등)는 구독 로직 산재 |
| 4 | `login_ok` | 5 | 브로커별 로그인 이벤트 + 엔진 초기화 (자연스러운 산재 후보) |
| 5 | `confirmed_done` | 5 (단일 파일 내) | daily_time_scheduler 단일 파일 내 5곳 — 단일화 대상 아님 |
| 6 | `positions` | 3 | 세션 10 "갱신 분산 주의" |
| 7 | `broker_rest_totals` | 3 | 세션 10 "갱신 분산 주의" |
| 8 | `access_token` | 3 | broker_tokens에서 파생 — 파생 참조 단일화 검토 |
| 9 | `broker_tokens` | 2 (engine_loop + market_close_pipeline 임시) | 임시 토큰 등록/제거 패턴 |
| 10 | `_last_global_buy_ts` / `_last_global_sell_ts` | 2 | 거래 관련 산재 (변경 금지) |

### 2.3 Dead code (DC-S2 제거 완료)

| 속성 | 상태 | 비고 |
|------|------|------|
| `shutdown_requested` | ☑ 제거됨 | DC-S2: 선언만, 읽기/쓰기 0건. test mock 정리 |
| `confirmed_refresh_running` | ☑ 제거됨 | DC-S2: 쓰기 0건, 읽기 2건 → `confirmed_refresh_running_confirmed`/`_5d`로 전환 후 제거 |
| `MIN_CACHE_LIFETIME_SEC` | ☑ 제거됨 | DC-S2: 읽기/쓰기 0건 (상수). 메타 테스트 정리 |

---

## 3. 그룹별 매트릭스 상세

> 각 속성의 readers/writers는 운영 코드를 기준으로 하며, 테스트 모킹은 "writers (테스트)" / "readers (테스트)" 란에 파일 단위로 요약. 줄번호가 많은 경우 범위로 표기.

### 3.1 A 그룹 — 브로커 연결 (5개)

#### A1. `connector_manager` (ConnectorManager | None)
- **초기값**: `None` (line 112)
- **owner**: `engine_loop` (단일 writer)
- **writers (운영)**: `engine_loop.py:141, 323, 332, 338, 385` — None 초기화 / ConnectorManager 생성 / 연결 실패·해제·종료 시 None
- **writers (테스트)**: 28건 모킹 (`test_daily_time_scheduler`, `test_engine_bootstrap`, `test_market_close_pipeline`, `test_engine_sector_confirm`, `test_engine_loop`, `test_engine_ws`, `test_web_routes`, `test_web_app`, `test_broker_change`)
- **readers (운영)**: 26곳 — `daily_time_scheduler:1253,1269,1281`, `web/routes/status.py:81`, `ws_subscribe_control:225`, `engine_bootstrap:54`, `market_close_pipeline:130`, `engine_sector_confirm:276`, `engine_lifecycle:179,186,187,226`, `engine_ws_reg:213,254,338,368,394,452`, `engine_ws:17,40,76,135,153,172,188,199`, `engine_loop:311,334,336,380,381`
- **생명주기**: 기동 시 / 세션 시작 / 종료 시 (연결/해제 루프)
- **비고**: docstring(세션 12) "단일 연결 소유자" 계약과 완전 일치. 불변조건 "connector_manager is None ⟺ WS 연결 없음" 준수. 22곳 fallback 패턴 제거 완료.

#### A2. `broker_tokens` (dict[str, str])
- **초기값**: `{}` (line 113)
- **owner**: 다중 writer (2곳: engine_loop 주, market_close_pipeline 임시)
- **writers (운영)**: `engine_loop.py:102, 108, 142, 401` (.clear / [bid]=token / 초기화·종료), `market_close_pipeline.py:1036, 1082, 1211, 1422` (임시 토큰 등록/제거 — 확정 데이터 다운로드용, finally에서 정리)
- **writers (테스트)**: `test_engine_loop.py:560, 864, 902` (모킹)
- **readers (운영)**: `engine_lifecycle:184` (for 순회), `engine_loop:236` (.get)
- **readers (테스트)**: `test_market_close_pipeline:52, 913`, `test_engine_loop` 다수
- **생명주기**: 기동 시 / 세션 시작 / 장마감 파이프라인 (임시 등록/제거)
- **비고**: docstring "갱신 분산 주의 속성" 일치. market_close_pipeline의 임시 토큰 패턴은 finally 블록에서 정리되므로 누수 위험 없음. 단일화 시 임시 패턴 별도 처리 필요.

#### A3. `access_token` (str | None)
- **초기값**: `None` (line 116)
- **owner**: 다중 writer (2곳: engine_loop, engine_lifecycle)
- **writers (운영)**: `engine_loop.py:238` (token 할당, 발급 성공), `engine_loop.py:242` (None, 발급 실패), `engine_lifecycle.py:133` (None, 증권사 변경 시 초기화)
- **writers (테스트)**: `test_web_routes`, `test_engine_loop`, `test_dry_run_fill_event`, `test_buy_order_executor`, `test_pipeline_compute`, `test_engine_ws_dispatch_isolation`, `test_settlement_verification`, `test_broker_change` 다수
- **readers (운영)**: `web/routes/status.py:41`, `engine_lifecycle:200`, `engine_loop:276, 308`, `engine_ws_dispatch:141`, `engine_account:390`, `dry_run:195`, `buy_order_executor:205`, `pipeline_compute_tick_handlers:187, 192, 196`
- **생명주기**: 기동 시 / 세션 시작 / 증권사 변경 시
- **비고**: docstring "갱신 분산 주의 속성 (3곳: engine_lifecycle, engine_loop ×2)"과 일치. `broker_tokens`에서 파생된 단일 대표값 — `broker_tokens[active_broker]`가 SSOT. 파생 참조 단일화 검토 대상(active_connector 제거 패턴과 유사).

#### A4. `login_ok` (bool)
- **초기값**: `False` (line 117)
- **owner**: 다중 writer (5곳: ls_connector ×2, kiwoom_connector, engine_lifecycle, engine_loop, engine_ws_dispatch)
- **writers (운영)**: `ls_connector.py:382` (True, 로그인 성공), `ls_connector.py:651` (False, 연결 해제), `ls_connector.py:700` (True, 재연결 로그인), `kiwoom_connector.py:390` (False, 로그아웃), `engine_lifecycle.py:132` (False, 증권사 변경 시 초기화), `engine_loop.py:140` (False, 기동 시 초기화), `engine_ws_dispatch.py:21` (True, LOGIN 응답)
- **writers (테스트)**: `test_web_routes`, `test_daily_time_scheduler`, `test_market_close_pipeline`, `test_engine_sector_confirm`, `test_engine_loop`, `test_engine_ws`, `test_engine_ws_dispatch`, `test_broker_change` 다수
- **readers (운영)**: `daily_time_scheduler:1254, 1270`, `web/routes/status.py:84`, `ws_subscribe_control:225`, `engine_sector_confirm:277`, `engine_lifecycle:198, 199`, `engine_ws_reg:255, 398, 449`, `engine_ws:136, 154, 189, 190, 200`
- **생명주기**: 기동 시 / 로그인·로그아웃·재연결 이벤트
- **비고**: docstring "갱신 분산 주의 속성 (5곳)" 일치. 브로커 커넥터의 로그인 이벤트 동기화 + 엔진 초기화가 섞인 패턴. "자연스러운 산재" 후보(이벤트 기반 상태 동기화)이나, 단일 헬퍼 `set_login_state(ok: bool, source: str)`로 수렴 가능성 존재.

#### A5. `broker_spec` (list)
- **초기값**: `[]` (line 185)
- **owner**: `engine_loop` (단일 writer)
- **writers (운영)**: `engine_loop.py:209` (`await _load_broker_spec_async(...)` 할당, 기동 시 1회 로드)
- **writers (테스트)**: `test_engine_loop.py:67, 852` (모킹)
- **readers (운영)**: `engine_loop:230, 233, 251` (타입 확인 / 길이 확인 / TR ID 설정 루프)
- **readers (테스트)**: `test_engine_loop:67, 857`
- **생명주기**: 기동 시 (1회성 로드, 이후 읽기 전용)
- **비고**: A 그룹 중 유일하게 단일 writer. `integrated_system_settings_cache["_broker_specs"]`에서 파생. 소유권 계약 명확.

---

### 3.2 B 그룹 — 계좌 (11개)

#### B1. `engine_user_id` (str)
- **초기값**: `""` (line 118)
- **owner**: `engine_lifecycle` (단일 writer)
- **writers (운영)**: `engine_lifecycle.py:32` (start_engine에서 설정)
- **writers (테스트)**: `test_engine_ws_dispatch_isolation.py:143, 170, 196` (모킹)
- **readers (운영)**: `engine_config.py:71` (user_id 기반 설정 조회), `engine_account.py:237` (설정 재로드 시 전달)
- **생명주기**: 기동 시
- **비고**: 단일 writer 패턴, 깔끔함.

#### B2. `ws_account_subscribed` (bool)
- **초기값**: `False` (line 176)
- **owner**: 다중 writer (2곳: engine_ws_reg True, engine_lifecycle False 리셋) — 자연스러운 산재 (init/성공 패턴)
- **writers (운영)**: `engine_ws_reg.py:381` (True, 구독 성공), `engine_lifecycle.py:128` (False, reset_broker_session_state)
- **writers (테스트)**: `test_broker_change.py:106, 118` (모킹/assert)
- **readers (운영)**: `ws_subscribe_control.py:95` (중복 구독 방지)
- **생명주기**: 이벤트 기반 (구독 성공 시 True, 브로커 변경 시 False)
- **비고**: 세션 10 "자연스러운 산재"로 분류됨. 단일화 대상 아님.

#### B3. `ws_connection_status` (bool)
- **초기값**: `False` (line 177)
- **owner**: `ws_subscribe_control.broadcast_ws_connection_status` (helper 경유 단일 writer)
- **writers (운영)**: `ws_subscribe_control.py:72` (broadcast_ws_connection_status 내부), `engine_lifecycle.py:130` (False, reset_broker_session_state — helper 외 직접 쓰기)
- **writers (테스트)**: `test_broker_change.py:108, 120` (모킹/assert)
- **readers (운영)**: `ws_subscribe_control.py:70` (상태 변경 체크)
- **생명주기**: 이벤트 기반 (연결/해제 시 broadcast)
- **비고**: connector가 helper 호출하는 패턴. engine_lifecycle의 False 리셋은 예외 경로.

#### B4. `quote_subscribed` (bool)
- **초기값**: `False` (line 178)
- **owner**: `ws_subscribe_control._set_status` (helper 경유 단일 writer)
- **writers (운영)**: `ws_subscribe_control.py:57` (_set_status 내부), `engine_lifecycle.py:129` (False, reset — helper 외 직접 쓰기)
- **writers (테스트)**: `test_broker_change.py:107, 119` (모킹/assert)
- **readers (운영)**: `ws_subscribe_control.py:43, 56, 118, 149` (get_subscribe_status / 상태 변경 체크 / start_quote / stop_quote)
- **생명주기**: 이벤트 기반 (구독 시작/중지)
- **비고**: helper 경유 단일 writer 패턴.

#### B5. `account_rest_bootstrapped` (bool)
- **초기값**: `False` (line 179)
- **owner**: 다중 writer (2곳: engine_account True, engine_lifecycle False) — 자연스러운 산재 (init/성공 패턴)
- **writers (운영)**: `engine_account.py:258` (True, _update_account_memory_inner), `engine_lifecycle.py:131` (False, reset)
- **readers (운영)**: `engine_bootstrap.py:30, 38` (미부트스트랩 체크), `engine_account.py:207` (중복 호출 스킵)
- **readers (테스트)**: `test_engine_bootstrap.py:30, 60, 77, 94, 142, 171, 195`, `test_engine_state_groups.py:42`
- **생명주기**: 세션 시작 (REST bootstrap 완료 시)
- **비고**: 세션 10 "자연스러운 산재"로 분류됨. 단일화 대상 아님.

#### B6. `broker_rest_totals` (dict)
- **초기값**: `{"total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_rate": 0.0}` (line 180-182)
- **owner**: 다중 writer (3곳: engine_account, pipeline_compute_tick_handlers, engine_lifecycle) — 단일화 후보
- **writers (운영)**: `engine_lifecycle.py:137` (초기값 리셋), `engine_account.py:287` (전체 재할당, _apply_broker_totals_from_summary), `engine_account.py:361-365` (개별 필드 갱신, _on_real_04), `pipeline_compute_tick_handlers.py:170-172` (positions 합산 재계산 후 재할당)
- **readers (운영)**: `engine_account.py:62, 71, 328`, `engine_account_rest.py:95`, `pipeline_compute_tick_handlers.py:170-172`
- **readers (테스트)**: `test_engine_account.py:98, 117, 173`, `test_pipeline_compute.py:904`, `test_engine_state_groups.py:43`
- **생명주기**: 틱 단위 (REAL 04 이벤트) + 세션 시작 (bootstrap)
- **비고**: docstring(세션 10) "갱신 분산 주의 속성 - 3곳" 일치. 단일화 후보. `engine_account`가 주 소유자, `pipeline_compute_tick_handlers`는 positions 기반 재계산, `engine_lifecycle`은 리셋. 헬퍼 `_apply_broker_totals(totals)`로 수렴 가능성.

#### B7. `auto_trade` (AutoTradeManager | None)
- **초기값**: `None` (line 183)
- **owner**: 다중 writer (2곳: engine_loop 생성, engine_lifecycle 리셋) — 자연스러운 산재 (라이프사이클 협업)
- **writers (운영)**: `engine_loop.py:279` (AutoTradeManager 생성), `engine_lifecycle.py:139` (None 리셋)
- **writers (테스트)**: `test_dry_run_fill_event.py:120, 267, 279`, `test_settlement_verification.py:104`, `test_buy_order_executor.py:108`
- **readers (운영)**: `engine_sector_confirm.py:169, 233`, `sector_data_provider.py:274`, `engine_ws_dispatch.py:140`, `engine_account.py:77-79, 390`, `dry_run.py:194`, `buy_order_executor.py:47, 86, 117, 204`, `pipeline_compute_tick_handlers.py:187, 192, 196`, `web/routes/settings.py:154-158`
- **생명주기**: 기동 시 (생성) + 세션 종료 (리셋)
- **비고**: 자연스러운 산재. 라이프사이클 협업 패턴.

#### B8. `broker_rest_apis` (dict[str, Any])
- **초기값**: `{}` (line 186)
- **owner**: 다중 writer (2곳: engine_loop 주, providers fallback init) — 자연스러운 산재
- **writers (운영)**: `engine_loop.py:259` (RestApi 인스턴스 할당), `engine_loop.py:400` (.clear, 종료 시), `kiwoom_providers.py:39` (None일 때 fallback 할당), `ls_providers.py:26` (None일 때 fallback 할당)
- **readers (운영)**: `kiwoom_connector.py:506`, `ls_connector.py:790`, `kiwoom_providers.py:34`, `ls_providers.py:21`
- **readers (테스트)**: `test_ls_connector`, `test_kiwoom_connector`, `test_ls_providers`, `test_kiwoom_providers`, `test_engine_state_groups.py:45`
- **생명주기**: 기동 시 (생성) + 종료 시 (clear)
- **비고**: engine_loop가 주 소유자, providers의 fallback init은 None 방어용. 자연스러운 산재.

#### B9. `account_rest_lock` (asyncio.Lock | None)
- **초기값**: `None` (line 143)
- **owner**: `engine_state._get_account_rest_lock` (helper 경유 단일 writer) + `engine_loop` None 리셋
- **writers (운영)**: `engine_state.py:230` (_get_account_rest_lock helper에서 None일 때 생성), `engine_loop.py:158` (None 리셋)
- **readers (운영)**: `engine_account.py:202` (_update_account_memory에서 _get_account_rest_lock 호출)
- **readers (테스트)**: `test_engine_loop.py:84, 450`, `test_engine_state_groups.py:46`
- **생명주기**: 기동 시 (None 초기화) + 지연 생성 (first use)
- **비고**: helper 경유 lazy init 패턴.

#### B10. `account_snapshot` (dict)
- **초기값**: `{}` (line 187)
- **owner**: `engine_account` (단일 writer)
- **writers (운영)**: `engine_lifecycle.py:136` ({} 리셋), `engine_account.py:259-261` (broker, deposit, orderable 설정), `engine_account.py:312-314` (accumulated_investment, orderable, initial_deposit 설정), `engine_account.py:359` (deposit 갱신, _on_real_04)
- **readers (운영)**: `engine_account.py:221, 263, 270, 271`, `engine_account_rest.py:113-115, 124, 129`, `risk_manager.py:164`, `web/routes/status.py:48`
- **readers (테스트)**: `test_web_routes`, `test_risk_manager`, `test_engine_account`, `test_broker_change`, `test_engine_state_groups.py:47`
- **생명주기**: 세션 시작 (bootstrap) + 틱 단위 (REAL 04 이벤트)
- **비고**: engine_account가 주 writer, engine_lifecycle은 리셋만. 단일 writer 패턴.

#### B11. `positions` (list)
- **초기값**: `[]` (line 188)
- **owner**: 다중 writer (3곳: engine_account, web/routes/settings, kiwoom_account_parsing) — 단일화 후보
- **writers (운영)**: `engine_lifecycle.py:138` ([] 리셋), `engine_account.py:255` (REST merged 재할당, _apply_account_yield_to_state), `kiwoom_account_parsing.py:126` (positions.append, real04_official_apply_position_line — 신규 포지션 추가), `web/routes/settings.py:132` ([] 리셋, _reset_positions_and_account)
- **readers (운영)**: `engine_bootstrap.py:34, 36, 38`, `engine_account.py:53, 301, 350-353, 389, 402`, `engine_snapshot.py:163`, `buy_order_executor.py:103`, `pipeline_compute_tick_handlers.py:168, 194`
- **readers (테스트)**: `test_broker_change`, `test_risk_manager`, `test_engine_snapshot`, `test_pipeline_compute`, `test_engine_account`, `test_engine_state_groups.py:48`
- **생명주기**: 세션 시작 (bootstrap) + 틱 단위 (REAL 04) + 사용자 요청 (settings reset)
- **비고**: docstring(세션 10) "갱신 분산 주의 속성 - 3곳" 일치. `kiwoom_account_parsing`의 append는 REAL 04 이벤트 핸들러 경로. `web/routes/settings`의 리셋은 사용자 요청. 단일화 시 append 경로와 리셋 경로를 별도 헬퍼로 분리 검토.

---

### 3.3 C 그룹 — 업종 분석 (9개)

#### C1. `sector_summary_cache` (SectorSummary | None)
- **초기값**: `None` (line 147)
- **owner**: `engine_snapshot._set_sector_summary()` 헬퍼 단일 경로 — **☑ 단일화 완료 (COUPLING-S1 후속)**
- **writers (운영)**: 헬퍼 내부 1곳 — `engine_snapshot.py:254` (`engine_state.state.sector_summary_cache = summary`). 기존 7곳 직접 쓰기는 헬퍼 호출로 전환 완료.
- **헬퍼 호출부 (7곳)**: `engine_lifecycle.py:161` (reset_for_restart), `daily_time_scheduler.py:849, 1237` (pre_ws_subscribe_reset / ws_subscribe_in_session_reset), `engine_sector_confirm.py:180, 245` (incremental_recompute / full_recompute), `sector_data_provider.py:283` (recompute_sector_summary), `engine_snapshot.py:180` (reset_realtime_fields)
- **readers (운영)**: `web/routes/settings.py:163`, `web/routes/ws.py:126`, `buy_order_executor.py:89`, `engine_bootstrap.py:63`, `engine_sector_confirm.py:88, 215`, `sector_data_provider.py:107, 120, 219`
- **readers (테스트)**: `test_engine_sector_confirm`, `test_buy_order_executor`, `test_web_routes.py:577` 다수
- **생명주기**: 세션 시작 / 이벤트 기반 (설정 변경, 재계산, 장마감)
- **비고**: docstring(세션 10) "sector_summary_cache: 7곳 — 가장 분산도 높음" → COUPLING-S1 후속 세션에서 `_set_sector_summary(summary, source)` 헬퍼로 단일화 완료. `source` 인자로 갱신 출처 로깅 (P21 사용자 투명성). 회귀 테스트 `test_sector_summary_cache_single_owner`가 단일 소유자 계약 검증.

#### C2. `master_stocks_cache` (dict[str, dict])
- **초기값**: `{}` (line 152)
- **owner**: 전체 재할당은 `engine_cache` 단일, dict 항목 쓰기는 다중 (구독 관리 로직 산재)
- **writers (운영)**: 전체 재할당 — `engine_cache.py:31, 77`. 항목 쓰기(_subscribed, _filtered 등) — `market_close_pipeline.py:179, 294, 345, 459, 821, 838, 955`, `engine_ws_reg.py:239, 302, 310, 321, 329, 423, 431, 462, 467, 475`, `daily_time_scheduler.py:1306`, `engine_sector_confirm.py:382`, `engine_bootstrap.py:47`, `engine_lifecycle.py:149`, `engine_loop.py:145`, `ws_subscribe_control.py:213`, `web/routes/settings.py:134`, `engine_snapshot.py:159`
- **readers (운영)**: 27곳 — `trading.py:344`, `web/routes/status.py:59, 66, 86`, `engine_ws_reg.py:298, 315, 417`, `sector_data_provider.py:83, 155`, `engine_radar.py:65`, `sector_calculator.py:61`, `engine_symbol_utils.py:17, 44`, `data_manager.py:27`, `pipeline_compute.py:177`, `sector_mapping.py:25`, `stock_classification_data.py:38`, `market_close_pipeline.py:1131`, `daily_time_scheduler.py:686`, `web/routes/settings.py:125, 133`, `ws_subscribe_control.py:213`, `engine_lifecycle.py:149`, `engine_loop.py:145`, `engine_cache.py:90`, `engine_snapshot.py:159`, `engine_bootstrap.py:47`
- **생명주기**: 기동 시 (engine_cache 초기화) / 틱 단위 (구독 상태 갱신)
- **비고**: 전체 dict 재할당은 engine_cache 단일 경로(P10 SSOT 준수). 항목 쓰기는 구독 관리 로직의 자연스러운 분산 — 단일화 대상 아님. 다만 항목 쓰기 패턴이 _subscribed/_filtered 등 예약 필드에 한정되므로, 헬퍼 `mark_subscribed(code)` / `mark_filtered(code)`로 수렴 가능성은 존재(후속 검토).

#### C3. `index_data_cache` (dict[str, dict[str, str]])
- **초기값**: `{}` (line 156)
- **owner**: `engine_account_notify` (단일 writer)
- **writers (운영)**: `engine_account_notify.py:209` (notify_index_data, 틱 수신 시)
- **readers (운영)**: `web/routes/ws.py:153` (WS 재연결 시 재전송)
- **readers (테스트)**: `test_engine_account_notify.py:281, 286, 302, 308`
- **생명주기**: 틱 단위 (업종지수 실시간 수신)
- **비고**: docstring "notify_index_data()가 틱 수신 시 갱신" 일치. 단일 writer 패턴 유지 잘됨.

#### C4. `market_phase` (dict)
- **초기값**: `{"krx": "장개시전", "nxt": "장개시전"}` (line 157-159)
- **owner**: `daily_time_scheduler` (단일 writer)
- **writers (운영)**: `daily_time_scheduler.py:758, 759, 1471, 1472`
- **readers (운영)**: `daily_time_scheduler.py:88, 104, 309, 322, 367, 401, 427, 492`, `engine_ws_dispatch.py:280, 364`
- **readers (테스트)**: `test_daily_time_scheduler` 다수 (72 locations)
- **생명주기**: 기동 시 / 이벤트 기반 (JIF 수신, 시간 기반 스케줄러)
- **비고**: docstring "시간 기반 스케줄러 + JIF 경계 이벤트가 갱신" 일치. 단일 소유권 유지 잘됨.

#### C5. `krx_circuit_breaker_active` (bool)
- **초기값**: `False` (line 160)
- **owner**: `engine_ws_dispatch` (단일 writer)
- **writers (운영)**: `engine_ws_dispatch.py:377, 383` (JIF 서킷브레이커 코드 수신 시)
- **readers (운영)**: `auto_trading_effective.py:30`
- **readers (테스트)**: `test_trading.py:54`, `test_engine_ws_dispatch.py:269, 282, 293, 377, 381`
- **생명주기**: 이벤트 기반 (JIF 서킷브레이커 코드 수신 시)
- **비고**: JIF 핸들러에서만 쓰기, auto_trading_effective에서만 읽기. 단일 소유권 유지 잘됨.

#### C6. `news_boost_cache` (dict[str, tuple[float, float]])
- **초기값**: `{}` (line 166)
- **owner**: `pipeline_compute_tick_handlers` (단일 writer)
- **writers (운영)**: `pipeline_compute_tick_handlers.py:382` (NWS 수신 시)
- **readers (운영)**: `engine_radar.py:35`
- **readers (테스트)**: `test_pipeline_compute_nws_handler.py:31, 38, 43, 48, 54, 59, 65`
- **생명주기**: 틱 단위 (뉴스 NWS 수신 시)
- **비고**: docstring "5분 TTL (P10 SSOT)" 일치. 만료 항목 제거는 get_news_boost_cache()에서 수행.

#### C7. `news_keywords_cache` (list[str])
- **초기값**: `[]` (line 167)
- **owner**: `engine_config` (단일 writer)
- **writers (운영)**: `engine_config.py:53` (설정 로더)
- **readers (운영)**: `pipeline_compute_tick_handlers.py:368`
- **생명주기**: 기동 시 / 설정 변경 시
- **비고**: docstring "설정 로더에서 갱신 (P13)" 일치. 메모리 상주로 틱 단계 DB 조회 금지 준수.

#### C8. `news_boost_score` (float)
- **초기값**: `1.0` (line 168)
- **owner**: `engine_config` (단일 writer)
- **writers (운영)**: `engine_config.py:56`
- **readers (운영)**: `pipeline_compute_tick_handlers.py:377`
- **생명주기**: 기동 시 / 설정 변경 시
- **비고**: docstring 일치.

#### C9. `news_boost_ttl_sec` (int)
- **초기값**: `300` (line 169)
- **owner**: `engine_config` (단일 writer)
- **writers (운영)**: `engine_config.py:57`
- **readers (운영)**: `engine_radar.py:34`
- **생명주기**: 기동 시 / 설정 변경 시
- **비고**: docstring 일치. get_news_boost_cache()에서 TTL 기준 만료 항목 제거.

---

### 3.4 D 그룹 — 스케줄러 (13개)

#### D1. `last_reset_date` (str)
- **초기값**: `""` (line 194)
- **owner**: `daily_time_scheduler` (단일 writer, 단일 파일 내 2곳)
- **writers (운영)**: `daily_time_scheduler.py:1404, 1478`
- **readers (운영)**: `daily_time_scheduler.py:1403`
- **생명주기**: 자정 / 기동 시
- **비고**: 단일 모듈 내 산재, 단일화 대상 아님.

#### D2. `krx_remove_done` (bool)
- **초기값**: `False` (line 195)
- **owner**: `daily_time_scheduler` (단일 writer, 단일 파일 내 4곳)
- **writers (운영)**: `daily_time_scheduler.py:623, 627, 632, 1405`
- **readers (운영)**: `daily_time_scheduler.py:622`
- **생명주기**: 장마감 15:20 / 자정
- **비고**: docstring(세션 10)에 "갱신 분산 주의 속성"으로 기록되었으나, 실제로는 단일 파일 내 4곳. 외부 모듈 쓰기 없음. 단일화 대상 아님.

#### D3. `confirmed_done` (bool)
- **초기값**: `False` (line 196)
- **owner**: `daily_time_scheduler` (단일 writer, 단일 파일 내 6곳)
- **writers (운영)**: `daily_time_scheduler.py:646, 657, 660, 727, 907, 1406`
- **readers (운영)**: `daily_time_scheduler.py:644, 715`
- **생명주기**: 장마감 / 부트스트랩 catch-up / 오후 8시 구독 종료 / 자정
- **비고**: docstring(세션 10) "confirmed_done: 5곳 (daily_time_scheduler 단일 파일 내 5곳)" 일치 (실제 6곳). 단일 파일 내 산재이므로 단일화 대상 아님.

#### D4. `auto_trade_timer_handles` (list)
- **초기값**: `[]` (line 197)
- **owner**: `daily_time_scheduler` (단일 writer, 단일 파일 내 3곳)
- **writers (운영)**: `daily_time_scheduler.py:1354, 1388, 1502` (clear/append)
- **readers (운영)**: `daily_time_scheduler.py:1352, 1354, 1388, 1500, 1502`
- **생명주기**: 기동 시 / 설정 변경 시 / 중지 시
- **비고**: 단일 모듈 내 쓰기. 단일화 대상 아님.

#### D5. `midnight_timer_handle` (asyncio.TimerHandle | None)
- **초기값**: `None` (line 198)
- **owner**: `daily_time_scheduler` (단일 writer)
- **writers (운영)**: `daily_time_scheduler.py:1440, 1451, 1504, 1505`
- **readers (운영)**: `daily_time_scheduler.py:1438, 1503, 1504`
- **생명주기**: 기동 시 / 자정 콜백 / 중지 시
- **비고**: 단일 모듈 내 쓰기.

#### D6. `timetable_timer_handle` (asyncio.TimerHandle | None)
- **초기값**: `None` (line 199)
- **owner**: `daily_time_scheduler` (단일 writer)
- **writers (운영)**: `daily_time_scheduler.py:1067, 1102, 1508, 1509`
- **readers (운영)**: `daily_time_scheduler.py:1065, 1507, 1508`
- **생명주기**: 기동 시 / 타임테이블 이벤트 / 중지 시
- **비고**: 단일 모듈 내 쓰기. 타임테이블 단일 타이머.

#### D7. `last_jif_received_at` (datetime | None)
- **초기값**: `None` (line 200)
- **owner**: `engine_ws_dispatch` (단일 writer)
- **writers (운영)**: `engine_ws_dispatch.py:312` (JIF 수신 시)
- **readers (운영)**: `daily_time_scheduler.py:1161` (JIF 헬스체크)
- **생명주기**: 틱 단위 (JIF 수신 시)
- **비고**: 단일 모듈 쓰기, JIF 헬스체크용.

#### D8. `krx_countdown_override` (dict | None)
- **초기값**: `None` (line 204)
- **owner**: `engine_ws_dispatch` (단일 writer)
- **writers (운영)**: `engine_ws_dispatch.py:338, 352`
- **readers (운영)**: `daily_time_scheduler.py:268`
- **생명주기**: JIF 카운트다운 수신 시 / 페이즈 전환 시
- **비고**: docstring "JIF 1순위, 시간표 보조" 일치. 단일 모듈 쓰기.

#### D9. `nxt_countdown_override` (dict | None)
- **초기값**: `None` (line 205)
- **owner**: `engine_ws_dispatch` (단일 writer)
- **writers (운영)**: `engine_ws_dispatch.py:340, 357`
- **readers (운영)**: `daily_time_scheduler.py:269`
- **생명주기**: JIF 카운트다운 수신 시 / 페이즈 전환 시
- **비고**: D8과 동일 패턴.

#### D10. `last_realtime_reset_date` (str)
- **초기값**: `""` (line 207)
- **owner**: `engine_snapshot` (helper 경유 단일 writer) — **세션 11 단일화 완료**
- **writers (운영)**: `engine_snapshot.py:231` (_mark_realtime_reset_done helper 본체)
- **간접 writers (helper 호출부)**: `engine_cache.py:105`, `daily_time_scheduler.py:850, 1228`
- **readers (운영)**: `daily_time_scheduler.py:830, 879`
- **생명주기**: 사전 트리거 07:58 / WS 구독 구간 기동 시
- **비고**: docstring(세션 11) "last_realtime_reset_date → engine_snapshot._mark_realtime_reset_done()" 일치. 외부 직접 쓰기 없음, helper 경유만 존재. 단일화 완료 모범 사례.

#### D11. `last_ws_subscribe_start_date` (str)
- **초기값**: `""` (line 208)
- **owner**: `daily_time_scheduler` (단일 writer)
- **writers (운영)**: `daily_time_scheduler.py:876, 1220`
- **readers (운영)**: `daily_time_scheduler.py:867`
- **생명주기**: 사전 트리거 07:59 / 구독 구간 기동 시
- **비고**: 단일 모듈 내 쓰기. 멱등성 가드.

#### D12. `last_krx_pre_subscribe_date` (str)
- **초기값**: `""` (line 209)
- **owner**: `daily_time_scheduler` (단일 writer)
- **writers (운영)**: `daily_time_scheduler.py:589`
- **readers (운영)**: `daily_time_scheduler.py:574`
- **생명주기**: 사전 트리거 08:59
- **비고**: 단일 모듈 내 쓰기. 멱등성 가드.

#### D13. `last_confirmed_download_date` (str)
- **초기값**: `""` (line 210)
- **owner**: `daily_time_scheduler` (단일 writer)
- **writers (운영)**: `daily_time_scheduler.py:937, 1407`
- **readers (운영)**: `daily_time_scheduler.py:932`
- **생명주기**: 확정 다운로드 20:40 / 자정
- **비고**: docstring(세션 11) "P22 날짜 기반 멱등성 가드 — 같은 날 2회 호출 시 2회째 스킵" 일치. 단일 모듈 내 쓰기.

---

### 3.5 E 그룹 — 이벤트/락/상수 (17개)

#### E1. `data_ready_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 128)
- **owner**: `engine_cache` (단일 writer)
- **writers (운영)**: `engine_cache.py:124` (set)
- **readers (운영)**: `web/routes/ws.py:28` (is_set), `web/routes/ws.py:30` (wait)
- **생명주기**: 기동 시 (캐시 로드 완료 시 set)
- **비고**: 단일 writer 패턴. 계약 일치.

#### E2. `token_ready_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 129)
- **owner**: `engine_loop` (단일 writer)
- **writers (운영)**: `engine_loop.py:219` (set), `engine_loop.py:143` (clear)
- **readers (운영)**: 없음 (테스트에서만 mock)
- **생명주기**: 기동 시 (토큰 발급 완료 시 set)
- **비고**: 단일 writer. 운영 reader 0건 — 후속 검토 대상(사용처 확인 필요).

#### E3. `ws_reg_pipeline_done` (LazyEvent)
- **초기값**: `LazyEvent()` (line 130)
- **owner**: 다중 writer (2곳: engine_bootstrap, engine_ws) — 자연스러운 산재 (준비 이벤트)
- **writers (운영)**: `engine_bootstrap.py:71` (set), `engine_ws.py:163` (set), `engine_bootstrap.py:17` (clear), `engine_lifecycle.py:145` (clear)
- **readers (운영)**: `web/routes/status.py:89` (is_set)
- **생명주기**: 이벤트 기반 (로그인 후 파이프라인 완료 시)
- **비고**: docstring(세션 11) "engine_ws(set) + engine_bootstrap(set) — 준비 이벤트" 일치. 자연스러운 산재, 단일화 대상 아님.

#### E4. `bootstrap_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 131)
- **owner**: `engine_cache` (단일 writer)
- **writers (운영)**: `engine_cache.py:122` (set), `engine_lifecycle.py:143` (clear)
- **readers (운영)**: `web/routes/ws.py:35, 37, 41`, `web/routes/status.py:19, 90`, `engine_snapshot.py:75`
- **생명주기**: 기동 시 (캐시 로드 완료 시 set)
- **비고**: 단일 writer(set), clear는 lifecycle. 계약 일치.

#### E5. `sector_summary_ready_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 132)
- **owner**: 다중 writer (3곳: engine_cache, engine_sector_confirm, sector_data_provider) — 자연스러운 산재 (준비 이벤트)
- **writers (운영)**: `engine_cache.py:132` (set), `engine_sector_confirm.py:196, 259` (set), `sector_data_provider.py:298, 301` (set, 예외 경로 포함), `engine_lifecycle.py:144` (clear)
- **readers (운영)**: `web/routes/ws.py:98, 100`
- **생명주기**: 이벤트 기반 (업종 요약정보 생성 완료 시)
- **비고**: docstring(세션 11) "sector_data_provider + engine_sector_confirm — 준비 이벤트" 일치. engine_cache의 set은 preboot 캐시 적중 경로. 자연스러운 산재.

#### E6. `engine_ready_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 133)
- **owner**: `web/app.py` (단일 writer)
- **writers (운영)**: `web/app.py:141` (set), `web/app.py:206` (clear)
- **readers (운영)**: `web/routes/status.py:18`
- **생명주기**: 기동 시 (엔진 초기화 완료 시 set)
- **비고**: 단일 writer 패턴.

#### E7. `server_ready_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 134)
- **owner**: `web/app.py` (단일 writer)
- **writers (운영)**: `web/app.py:128` (set), `web/app.py:207` (clear)
- **readers (운영)**: `web/routes/status.py:17`
- **생명주기**: 기동 시 (서버 리스닝 시작 시 set)
- **비고**: 단일 writer 패턴.

#### E8. `preboot_ready_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 136)
- **owner**: `engine_loop` (단일 writer)
- **writers (운영)**: `engine_loop.py:175` (set), `engine_loop.py:156` (clear)
- **readers (운영)**: 없음 (테스트 mock만)
- **생명주기**: 기동 시 (엔진 내부 준비 완료 시 set)
- **비고**: 단일 writer. 운영 reader 0건 — 후속 검토 대상.

#### E9. `engine_stop_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 137)
- **owner**: 다중 writer (2곳: engine_lifecycle set, engine_loop clear) — 자연스러운 산재 (라이프사이클 협업)
- **writers (운영)**: `engine_lifecycle.py:80` (set), `engine_loop.py:302` (clear)
- **readers (운영)**: `engine_loop.py:305` (is_set), `engine_loop.py:349` (wait)
- **생명주기**: 기동/종료 (엔진 루프 제어용)
- **비고**: 라이프사이클 협업 패턴. 자연스러운 산재.

#### E10. `ws_window_changed_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 138)
- **owner**: 다중 writer (2곳: daily_time_scheduler set, engine_loop clear) — 자연스러운 산재 (스케줄러/루프 협업)
- **writers (운영)**: `daily_time_scheduler.py:885, 915, 1242` (set), `engine_loop.py:357` (clear)
- **readers (운영)**: `engine_loop.py:350` (wait)
- **생명주기**: 이벤트 기반 (WS 구간 변화 시)
- **비고**: 스케줄러에서 set, 엔진 루프에서 clear/wait. 자연스러운 산재.

#### E11. `reg_seq_lock` (asyncio.Lock | None)
- **초기값**: `None` (line 139)
- **owner**: `engine_ws` (단일 writer, lazy init)
- **writers (운영)**: `engine_ws.py:33` (None일 때 asyncio.Lock() 생성)
- **readers (운영)**: `engine_ws.py:32` (None check), `engine_ws.py:35` (async with)
- **생명주기**: 지연 초기화 (최초 사용 시 생성)
- **비고**: Lazy initialization 패턴. 단일 writer.

#### E12. `reg_ack_event` (LazyEvent)
- **초기값**: `LazyEvent()` (line 140)
- **owner**: `engine_state._notify_reg_ack` (helper 경유 단일 writer)
- **writers (운영)**: `engine_state.py:237` (set, helper 본체)
- **간접 writers (helper 호출부)**: `ls_connector.py:384`, `engine_loop.py:148`, `engine_ws_dispatch.py:22, 85`
- **writers (clear)**: `engine_ws.py:37, 54`
- **readers (운영)**: `engine_ws.py:36, 50, 51, 53, 54`
- **생명주기**: 이벤트 기반 (REG/UNREG ACK 수신 시)
- **비고**: helper 경유 단일 writer 패턴. docstring line 233-237에 helper 명시.

#### E13. `reg_ack_return_code` (str)
- **초기값**: `""` (line 141)
- **owner**: 다중 writer (2곳: engine_ws 직접, engine_state._notify_reg_ack 간접)
- **writers (운영)**: `engine_ws.py:38` ("" 초기화), `engine_state.py:235` (helper 본체, _notify_reg_ack)
- **readers (운영)**: `engine_ws.py:58`
- **생명주기**: 이벤트 기반 (REG/UNREG ACK 응답 코드 저장)
- **비고**: engine_ws에서 초기화(""), _notify_reg_ack에서 갱신. helper 경유 패턴.

#### E14. `rest_api_thread_sem` (asyncio.Semaphore | None)
- **초기값**: `None` (line 142)
- **owner**: `engine_state._get_rest_api_thread_sem` (helper 경유 단일 writer, lazy init)
- **writers (운영)**: `engine_state.py:225` (None일 때 asyncio.Semaphore(1) 생성, helper 본체)
- **간접 writers (helper 호출부)**: `engine_account.py:103`
- **readers (운영)**: `engine_account.py:103` (None check 후 helper 호출)
- **생명주기**: 지연 초기화 (최초 사용 시 생성)
- **비고**: helper 경유 lazy init 패턴. docstring line 223-226 명시.

#### E15. `_last_global_buy_ts` (float)
- **초기값**: `0.0` (line 172)
- **owner**: 다중 writer (2곳: order_interval, web/routes/settings) — 거래 관련 산재 (변경 금지)
- **writers (운영)**: `order_interval.py:38` (time.time(), 매수 실행 후), `web/routes/settings.py:160` (0.0, 설정 변경 시 리셋)
- **readers (운영)**: `order_interval.py:24`
- **생명주기**: 주문 간격 (매수 타이머)
- **비고**: docstring(세션 11) "order_interval + web/routes/settings" 일치. 거래 관련 산재, 본 세션 범위 외.

#### E16. `_last_global_sell_ts` (float)
- **초기값**: `0.0` (line 173)
- **owner**: 다중 writer (2곳: order_interval, web/routes/settings) — 거래 관련 산재 (변경 금지)
- **writers (운영)**: `order_interval.py:40` (time.time()), `web/routes/settings.py:161` (0.0)
- **readers (운영)**: `order_interval.py:24`
- **생명주기**: 주문 간격 (매도 타이머)
- **비고**: E15와 동일 패턴. 거래 관련 산재, 변경 금지.

#### E17. `MIN_CACHE_LIFETIME_SEC` (float) — **DC-S2 제거됨**
- **상태**: 제거 완료 (세션 DC-S2)
- **비고**: 상수 선언만, 읽기/쓰기 0건. 메타 테스트 정리.

#### E18. `REG_POST_ACK_GAP_SEC` (float) — 상수
- **초기값**: `0.35` (line 191)
- **owner**: 상수 (쓰기 없음)
- **writers (운영)**: 없음
- **readers (운영)**: `engine_ws.py:59`
- **생명주기**: 상수
- **비고**: docstring(세션 11) "읽기만 존재 (engine_ws)" 일치. 단일 reader.

---

### 3.6 F 그룹 — 안전/기동 플래그 (11개)

#### F1. `running` (bool)
- **초기값**: `False` (line 110)
- **owner**: 다중 writer (2곳: engine_lifecycle, engine_loop) — 자연스러운 산재 (라이프사이클 협업)
- **writers (운영)**: `engine_lifecycle.py:33` (True, start_engine), `engine_lifecycle.py:77` (False, stop_engine), `engine_loop.py:152` (False, 루프 시작 시 초기화), `engine_loop.py:402` (False, 루프 종료 시)
- **readers (운영)**: `telegram_bot.py:354`, `web/routes/status.py:20, 85`, `engine_lifecycle.py:169, 195`, `engine_config.py:104`, `buy_order_executor.py:83`
- **생명주기**: 기동 시 / 종료 시
- **비고**: docstring(세션 11) "자연스러운 산재 — 라이프사이클 협업" 일치. engine_lifecycle(start/stop) + engine_loop(run/exit).

#### F2. `shutdown_requested` (bool) — **DC-S2 제거됨**
- **상태**: 제거 완료 (세션 DC-S2)
- **비고**: 선언만 존재, 운영 읽기/쓰기 0건. test mock 1건 정리.

#### F3. `engine_task` (asyncio.Task | None)
- **초기값**: `None` (line 114)
- **owner**: `engine_lifecycle` (단일 writer)
- **writers (운영)**: `engine_lifecycle.py:34` (create_task), `engine_lifecycle.py:95` (None, 취소 후)
- **readers (운영)**: `engine_lifecycle.py:25, 89, 92, 169, 203`
- **생명주기**: 기동 시 / 종료 시
- **비고**: engine_lifecycle에서만 생성·취소·None 할당. is_engine_running()에서 상태 확인.

#### F4. `engine_loop_ref` (asyncio.AbstractEventLoop | None)
- **초기값**: `None` (line 115)
- **owner**: `engine_loop` (단일 writer)
- **writers (운영)**: `engine_loop.py:153` (asyncio.get_running_loop())
- **readers (운영)**: `engine_lifecycle.py:294` (call_soon_threadsafe용)
- **생명주기**: 기동 시
- **비고**: engine_loop.run_engine_loop() 시작 시 설정. engine_lifecycle.schedule_engine_task()에서 사용.

#### F5. `realtime_latency_exceeded` (bool)
- **초기값**: `False` (line 119)
- **owner**: `engine_ws_dispatch` (단일 writer)
- **writers (운영)**: `engine_ws_dispatch.py:98, 104` (200ms 초과 시 True, 회복 시 False)
- **readers (운영)**: `trading.py:233, 727` (매수/매도 차단)
- **생명주기**: 틱 단위 (이벤트 기반)
- **비고**: P17(플래그 단일 소스) 준수. trading.py에서 매수/매도 차단에 사용.

#### F6. `position_build_failed` (bool)
- **초기값**: `False` (line 124)
- **owner**: 다중 writer (2곳: engine_lifecycle init, engine_lifecycle 오류 시) — 자연스러운 산재 (init/오류 패턴)
- **writers (운영)**: `engine_lifecycle.py:29` (False, start_engine 초기화), `engine_lifecycle.py:47` (True, 테스트모드 포지션 구축 실패)
- **readers (운영)**: `engine_lifecycle.py:208` (get_engine_status에서 프론트 전달)
- **생명주기**: 기동 시 / 오류 시
- **비고**: docstring(세션 11) "자연스러운 산재" 일치. P21 사용자 투명성 — 엔진 재기동 시에만 해제.

#### F7. `degraded_mode` (bool)
- **초기값**: `False` (line 125)
- **owner**: 다중 writer (2곳: engine_lifecycle init, engine_loop 오류 시) — 자연스러운 산재 (init/오류 패턴)
- **writers (운영)**: `engine_lifecycle.py:30` (False, start_engine 초기화), `engine_loop.py:35` (True, _load_caches_preboot 실패)
- **readers (운영)**: `engine_lifecycle.py:209` (get_engine_status에서 프론트 전달)
- **생명주기**: 기동 시 / 오류 시
- **비고**: docstring(세션 11) "자연스러운 산재" 일치. P21. 엔진 재기동 시에만 해제.

#### F8. `preboot_cache_loaded` (bool)
- **초기값**: `False` (line 135)
- **owner**: 다중 writer (2곳: engine_loop init, engine_cache 성공 시) — 자연스러운 산재 (init/성공 패턴)
- **writers (운영)**: `engine_loop.py:155` (False, 루프 시작 시 초기화), `engine_cache.py:94` (True, _load_caches_preboot 성공)
- **readers (운영)**: `daily_time_scheduler.py:1223`, `engine_snapshot.py:75`
- **생명주기**: 기동 시 / 캐시 로드 성공 시
- **비고**: docstring(세션 11) "자연스러운 산재" 일치. 실시간 필드 초기화 타이밍 조절에 사용.

#### F9. `confirmed_refresh_running` (bool) — **DC-S2 제거됨**
- **상태**: 제거 완료 (세션 DC-S2)
- **비고**: 쓰기 0건, 읽기 2건을 `confirmed_refresh_running_confirmed`/`_5d` 실제 플래그로 전환 후 제거. P21 사용자 투명성 복원 (다운로드 중 상태 표시), P16 중복 다운로드 차단 복원.

#### F10. `confirmed_refresh_running_confirmed` (bool)
- **초기값**: `False` (line 149)
- **owner**: `market_close_pipeline` (helper 경유 단일 writer) — **세션 11 단일화 완료**
- **writers (운영)**: `market_close_pipeline.py:987` (helper _reset_confirmed_refresh_running 본체), `market_close_pipeline.py:1013` (True 시작), `market_close_pipeline.py:1085` (False finally)
- **간접 writers (helper 호출부)**: `daily_time_scheduler` → _reset_confirmed_refresh_running() 헬퍼 경유
- **readers (운영)**: `market_close_pipeline.py:1010`
- **생명주기**: 이벤트 기반 (장마감 파이프라인)
- **비고**: docstring(세션 11) 단일화 완료. 소유 모듈 내 3곳 + 외부 예외 경로 helper. 확정시세 다운로드 전용.

#### F11. `confirmed_refresh_running_5d` (bool)
- **초기값**: `False` (line 150)
- **owner**: `market_close_pipeline` (단일 writer)
- **writers (운영)**: `market_close_pipeline.py:1199, 1226, 1425`
- **readers (운영)**: `market_close_pipeline.py:1196`, `web/routes/stock_classification.py:313`
- **생명주기**: 이벤트 기반 (5거래일 일봉 다운로드)
- **비고**: market_close_pipeline.fetch_5d_data_only()에서만 쓰기. 중복 실행 방지용.

#### F12. `latest_filter_summary_meta` (str)
- **초기값**: `""` (line 151)
- **owner**: `market_close_pipeline` (helper 경유 단일 writer) — **세션 11 단일화 완료**
- **writers (운영)**: `market_close_pipeline.py:996` (helper _set_latest_filter_summary_meta 본체)
- **간접 writers (helper 호출부)**: `market_close_pipeline.py:845` (4단계), `web/app.py:83` (기동 시 DB 캐시 로드)
- **readers (운영)**: `web/routes/stock_classification.py:75, 184`, `web/routes/ws.py:60`
- **생명주기**: 기동 시 / 파이프라인 완료 시
- **비고**: docstring(세션 11) 단일화 완료. helper 단일 경로. 호출부: market_close_pipeline(4단계), web/app.py(기동 시).

#### F13. `integrated_system_settings_cache` (dict)
- **초기값**: `{}` (line 184)
- **owner**: 다중 writer (10+ 곳: web/app, engine_config, trading, market_close_pipeline, engine_loop, engine_cache) — **거래 관련 산재 (변경 금지)**
- **writers (운영)**: `web/app.py:103-104` (clear+update, 기동 시 DB 로드), `engine_config.py:94-96` (clear+update, 전체 갱신), `trading.py:437, 646` (항목 쓰기, 매수/매도 후 auto_buy_on 등), `market_close_pipeline.py:1019, 1025, 1148, 1161` (항목 쓰기, 파이프라인 단계별), `engine_loop.py:149` (항목 쓰기), `engine_cache.py:54` (항목 쓰기)
- **readers (운영)**: 20+ 곳 — `ls_connector:827-828`, `kiwoom_connector:536-537`, `broker_router:65-67, 77, 97, 103`, `engine_settings:110`, `telegram_bot:122, 293`, `web/routes/settings:59, 71, 129, 140, 175`, `trade_history:190, 213`, `engine_account_notify:320`, `settlement_engine:251, 338`, `daily_time_scheduler:488, 681, 976, 1202, 1294`, `engine_lifecycle:324, 326`, `engine_loop:58, 164`, `engine_cache:43, 110, 112`, `engine_snapshot:63`, `engine_sector_confirm:117, 153, 157-159, 224-228`
- **생명주기**: 기동 시 / 설정 변경 / 파이프라인 실행 / 주문 후
- **비고**: docstring(세션 11) "거래 관련 산재 (변경 금지 — 본 세션 범위 외). engine_config 전체 갱신 + 각 모듈 항목 수정. 10+ 파일" 일치. P13 메모리 상주 준수. 가장 분산도 높은 속성이나, 거래 안전성 때문에 본 세션 및 후속 COUPLING 세션 범위 외. 별도 승인 필요.

---

## 4. 단일화 우선순위 후속 세션 후보

후속 세션에서는 아래 1개 속성만 별도 승인 후 최소 범위로 읽기·쓰기 경계를 좁힌다.

### 4.1 1순위 후보: `sector_summary_cache` (7곳 writer) — ☑ 단일화 완료 (COUPLING-S1 후속)

- **이유**: docstring이 "가장 분산도 높음"으로 명시. 거래 관련이 아니므로 safe-trade 제약 없음. 7곳 writer 중 6곳이 engine_* 모듈이므로 헬퍼 수렴 가능성 높음.
- **단일화 방향**: `engine_snapshot._set_sector_summary(summary, source: str)` helper 신설. 기존 7곳 직접 쓰기를 helper 호출로 전환. `source` 인자로 갱신 출처 로깅(P21 사용자 투명성).
- **위험도**: 중간. 7곳 writer 중 일부는 예외 경로(setup 중 오류 시 None 복원)이므로 helper가 예외 경로도 커버해야 함.
- **검증**: `test_engine_sector_confirm`, `test_buy_order_executor`, `test_web_routes` + 백엔드 전체 테스트 + RuntimeWarning 기동.
- **완료 결과**: 헬퍼 신설 + 7곳 호출 전환 + 회귀 테스트 `test_sector_summary_cache_single_owner` 전환. 백엔드 2760 passed (회귀 0건), RuntimeWarning 기동 정상 (168ms, Traceback 0건), 잔존 프로세스 0건.

### 4.2 2순위 후보 (참고용, 본 후속 세션에서는 다루지 않음)

- `positions` (3곳): kiwoom_account_parsing의 append 경로와 web/routes/settings의 리셋 경로를 별도 헬퍼로 분리 검토.
- `broker_rest_totals` (3곳): `engine_account._apply_broker_totals(totals)` helper로 수렴 검토.
- `access_token` (3곳): `broker_tokens`에서 파생된 단일 대표값 — active_connector 제거 패턴과 유사하게 파생 참조 단일화 검토.

### 4.3 거래 관련 산재 (변경 금지 — 별도 승인 필요)

- `integrated_system_settings_cache` (10+ 곳)
- `_last_global_buy_ts` / `_last_global_sell_ts` (2곳)

이 속성들은 거래 안전성과 직결되므로 COUPLING 세션 범위 외. 별도 승인 시 safe-trade 절차 적용.

### 4.4 Dead code (DC-S2 제거 완료)

- `shutdown_requested`: ☑ 제거 — 선언만, 참조 0건.
- `confirmed_refresh_running`: ☑ 제거 — 쓰기 0건, 읽기 2건 → 실제 플래그로 전환 후 제거.
- `MIN_CACHE_LIFETIME_SEC`: ☑ 제거 — 상수, 읽기 0건.

---

## 5. docstring과의 대조 결과

| 항목 | docstring 기록 | 실제 조사 결과 | 일치 여부 |
|------|----------------|----------------|-----------|
| `login_ok` 5곳 | kiwoom_connector, ls_connector ×2, engine_lifecycle, engine_loop, engine_ws_dispatch | 동일 (5곳: ls_connector ×2, kiwoom_connector, engine_lifecycle, engine_loop, engine_ws_dispatch — 총 7 write 라인이나 모듈은 5곳) | 일치 |
| `sector_summary_cache` 7곳 | engine_lifecycle, daily_time_scheduler ×2, engine_sector_confirm ×2, sector_data_provider, engine_snapshot | 단일화 완료 — `_set_sector_summary` 헬퍼 1곳(세션 COUPLING-S1 후속) | 일치(과거 기준) → 단일화 완료 |
| `confirmed_done` 5곳 | daily_time_scheduler 단일 파일 내 5곳 | 실제 6곳 (646, 657, 660, 727, 907, 1406) | 대체 일치 (1곳 추가) |
| `positions` 3곳 | engine_account, engine_lifecycle, web/routes/settings | 실제 4곳 (engine_lifecycle, engine_account, kiwoom_account_parsing, web/routes/settings) | 불일치 — `kiwoom_account_parsing.py:126`이 빠져 있음. docstring 업데이트 권장. |
| `broker_rest_totals` 3곳 | pipeline_compute_tick_handlers, engine_account, engine_lifecycle | 동일 | 일치 |
| `access_token` 3곳 | engine_lifecycle, engine_loop ×2 | 동일 (engine_loop:238, 242 / engine_lifecycle:133) | 일치 |
| `last_realtime_reset_date` helper 경유 | engine_snapshot._mark_realtime_reset_done(), 호출부 engine_cache, daily_time_scheduler ×2 | 동일 | 일치 |
| `confirmed_refresh_running_confirmed` 단일화 | market_close_pipeline (소유 모듈 직접 쓰기) + daily_time_scheduler helper 경유 | 동일 | 일치 |
| `latest_filter_summary_meta` 단일화 | market_close_pipeline._set_latest_filter_summary_meta(), 호출부 4단계 + web/app.py | 동일 | 일치 |
| `connector_manager` 단일 소유자 | engine_loop에서만 생성·해제·None | 동일 | 일치 |
| `integrated_system_settings_cache` 10+ 파일 | 거래 관련 산재, 변경 금지 | 동일 (20+ readers, 6 writer 모듈) | 일치 |
| `_last_global_buy_ts` / `_last_global_sell_ts` | order_interval + web/routes/settings | 동일 | 일치 |
| `MIN_CACHE_LIFETIME_SEC` 읽기 0건 | DC-S2 제거됨 | 제거 완료 | 일치 |
| `REG_POST_ACK_GAP_SEC` 읽기만 | engine_ws | 동일 | 일치 |
| `shutdown_requested` 참조 0건 | DC-S2 제거됨 | 제거 완료 | 일치 |
| `confirmed_refresh_running` 쓰기 0건, 읽기만 2건 | DC-S2 제거됨 | 제거 완료 | 일치 |

### 불일치 1건

- **`positions`**: docstring이 `kiwoom_account_parsing.py:126`의 append를 누락. 세션 10 조사 시 누락된 것으로 보임. docstring 업데이트 권장(별도 승인 시).

---

## 6. 결론

- 66개 속성 중 약 40개가 단일 writer(또는 helper 경유 단일화)로 소유권이 명확.
- 12개는 "자연스러운 산재"(init/오류/성공 라이프사이클 협업)로 단일화 대상 아님.
- 9개는 다중 writer(단일화 후보). 그중 `sector_summary_cache`(7곳)는 COUPLING-S1 후속 세션에서 `_set_sector_summary` 헬퍼로 단일화 완료. 남은 후보 8개.
- 3개는 거래 관련 산재로 본 세션 범위 외(별도 승인 필요).
- 3개 dead code는 DC-S2에서 제거 완료.
- docstring과의 대조에서 1건 불일치(`positions`의 `kiwoom_account_parsing` 누락).
- `sector_summary_cache` 단일화 완료. 후속은 2순위 후보(`positions` 3곳, `broker_rest_totals` 3곳, `access_token` 3곳) 별도 승인 시 진행 권장.
