# SectorFlow Handover

## 세션 개요
- 날짜: 2026-07-18 (P-NEW-5 — 15개 모듈 state 참조 패턴 A → B 단계적 전환 8세션, engine_config.py + engine_bootstrap.py + engine_cache.py 3개 모듈 전환 — P-NEW-5 완료)
- 작업: HANDOVER.md P-NEW-5에 기록된 15개 모듈의 `state` 참조 패턴 A(모듈 레벨 `from backend.app.services.engine_state import state`) → 패턴 B(`from backend.app.services import engine_state` + `engine_state.state.X`) 단계적 전환 8세션(완료). 사용자 명시적 실행 지시어("P-NEW-5 진행해줘")로 진행 승인. 사전조사(규칙 0-2): 의존성 — 백엔드 3개 파일 + 테스트 2개 파일 수정 필요(test_engine_bootstrap.py patch 9곳 + test_engine_cache.py patch.object 19곳 + engine_state import 추가), test_engine_config.py는 존재하지 않아 테스트 수정 불필요, 프론트엔드 영향 없음. 원칙 부합 — P23(일관성) 7세션까지 전환한 13개 모듈과 동일 패턴 통일, P16(살아있는 경로) 모듈 로드 시점 고정 바인딩 제거, P10/P22/P24 부합. 기존 공통 자산 — daily_time_scheduler.py가 패턴 B 참조 모델. 백엔드 3개 파일 수정: (1) `engine_config.py` — line 11 모듈 레벨 import 패턴 B 전환 + `state.X` 12곳 → `engine_state.state.X` 치환(integrated_system_settings_cache/engine_user_id/running/on_filter_settings_changed). line 25 주석("# state.integrated_system_settings_cache는 app.py에서 이미 초기화됨") 및 line 48 docstring("state.integrated_system_settings_cache 를 갱신한다")은 규칙(주석 무단 수정 금지)에 따라 원본 유지. 함수 내 지역 import 없음. (2) `engine_bootstrap.py` — line 10 모듈 레벨 import 패턴 B 전환 + `state.X` 14곳 → `engine_state.state.X` 치환(ws_reg_pipeline_done/integrated_system_settings_cache/account_rest_bootstrapped/positions/master_stocks_cache/connector_manager/active_connector/sector_summary_cache). 함수 내 지역 import 없음. (3) `engine_cache.py` — line 10 모듈 레벨 import 패턴 B 전환 + `state.X` 14곳 → `engine_state.state.X` 치환(master_stocks_cache/integrated_system_settings_cache/preboot_cache_loaded/last_realtime_reset_date/bootstrap_event/data_ready_event/sector_summary_ready_event). 함수 내 지역 import 없음. 테스트 2개 파일 수정: `test_engine_bootstrap.py` — 9곳 `patch("...engine_bootstrap.state", mock_state)` → `patch("...engine_state.state", mock_state)` 치환. `test_engine_cache.py` — 19곳 `patch.object(engine_cache, "state", mock_state)` → `patch.object(engine_state, "state", mock_state)` 치환 + 파일 상단 `from backend.app.services import engine_state` import 추가. 정적 검증: py_compile OK + ruff check OK. pytest: test_engine_bootstrap.py + test_engine_cache.py 28 passed + 전체 회귀 **2928 passed, 0 failed**(이전 세션과 동일). 런타임 기동: `python -W error::RuntimeWarning main.py` 기동 성공 — RuntimeWarning 0건 + "앱 시작 완료" + "타임테이블 빌드 완료 — 11항목" + "업종 재계산 완료" + "LS증권 연결 완료 (테스트모드=True)" + "선행 캐시 로드 완료" (engine_cache.py 경로 정상 동작 확인) + 잔존 프로세스 0건. 사용자 체감 변화 없음(프로덕션 동작 100% 보존 — state 싱글톤 속성 참조 방식만 변경, 동일 객체 접근).
- 상태: P-NEW-5 **15개 모듈 전환 완료**(engine_service.py, engine_strategy_core.py, engine_ws_dispatch.py, engine_sector_confirm.py, sector_data_provider.py, engine_radar.py, market_close_pipeline.py, engine_snapshot.py, ws_subscribe_control.py, engine_ws_reg.py, engine_loop.py, engine_lifecycle.py, engine_ws.py, engine_config.py, engine_bootstrap.py, engine_cache.py). P-NEW-5 이슈 해결 완료 → "미해결 문제" P-NEW-5 섹션에 완료 상태 갱신.
- **참조 규칙**: AGENTS.md 섹션3 규칙 0(승인 전 수정 금지) + 규칙 0-1(세션당 1단계) + 규칙 0-2(수정 전 사전조사) + 규칙 9(발견 문제 기록) + backend-fix 스킬 + P10/P16/P23/P24

## 차순위 매수 시도 알고리즘 다단계 작업 — 완료 (2/2세션)

### 단계 진행 상황
- **설계 세션 (완료)**: 설계서 작성 — 사전조사 결과 + 사용자 결정 4항목 + 구현 방식 확정 반영.
  - **설계서**: `docs/architecture_multi_rank_buy_design.md` (821줄, 14개 섹션) — **2세션 완료 후 삭제 (규칙 11)**
  - **핵심 설계**: `execute_buy` 반환값 `bool` → `tuple[bool, str]` (성공여부, 사유코드). 사유코드 21개 상수 + `BUY_GLOBAL_REJECT_REASONS` frozenset(전체 차단 11개) + `_map_risk_reason_to_code()` 헬퍼(RiskManager 사유 문자열 → 사유코드 매핑). `buy_order_executor` 루프: 1순위 성공 후 잔액/한도 잔존 시 `continue`(차순위 시도), 1순위 종목별 차단 시 `continue`, 1순위 전체 차단 시 `break`, 잔액 0·최대 보유수·일일 한도 도달 시 `break`. `_refresh_buyable_prices()` 헬퍼 추가(매수 성공 후 잔액 갱신 시 _buyable_codes 재계산, P10 SSOT). `BUY_REJECT_QTY_ZERO`는 조건부 — 잔액 재조회로 전체/종목별 판별. 매수 사유 문자열에 순위 추가(`reason=f"업종자동매수 업종={s.sector} 순위={bt.rank}"`, P21). 간격 게이트: 같은 호출 내 연속 시도 허용, `mark_order_executed`는 매 성공 시마다 호출. 프론트엔드 변경 없음. UI 기준 변경(규칙 0-4): 사용자 체감 변화 "잔액이 남을 때 1순위만 사고 끝나지 않고 2순위·3순위로 잔액을 더 쓴다" only. 로그에 매수 시도 순위·사유 명시.
- **구현 1세션 (완료)**: trading.py 반환값 변경 + 사유코드 체계 + test_trading.py 갱신.
  - **수정 파일**: `backend/app/services/trading.py` + `backend/app/services/buy_order_executor.py`(임시 호환) + `backend/tests/test_trading.py`
  - **trading.py 변경**: 사유코드 상수 21개 + BUY_OK + BUY_GLOBAL_REJECT_REASONS frozenset(전체 차단 11개) + _map_risk_reason_to_code() 헬퍼 추가(모듈 상단). execute_buy/_execute_buy_locked 시그니처 `-> bool` → `-> tuple[bool, str]` + docstring 갱신. 21개 `return False` → `return False, BUY_REJECT_XXX` (4-2 매핑표 준수). 최종 `return True` → `return True, BUY_OK`. 등락률 가드는 _reject_code 변수로 상승(BUY_REJECT_RISE_GUARD)/하락(BUY_REJECT_FALL_GUARD) 구분. RiskManager 거부는 _map_risk_reason_to_code(_risk_reason)로 사유코드 분기.
  - **buy_order_executor.py 변경**: 임시 호환 코드 추가 — `_ordered_result = await ... execute_buy(...)` + `_ordered = _ordered_result[0] if isinstance(_ordered_result, tuple) else _ordered_result`. **2세션에서 제거 완료**.
  - **test_trading.py 변경**: 9곳 `result = await mgr.execute_buy(...)` → `result, _reason = await mgr.execute_buy(...)` (replace_all). 신규 TestExecuteBuyReasonCodes 클래스 12개 테스트(auto_buy_off/rebuy/open_order/signal_interval/max_holding/buy_amt_zero/price_zero/daily_state/realtime_latency/rise_guard/strength_guard/risk_circuit 사유코드 검증) + TestMapRiskReasonToCode 클래스 5개 테스트(circuit/loss/cash/single/unknown fallback). is_auto 체크 이후 가드 테스트는 `patch("backend.app.services.trading.auto_buy_effective", return_value=True)` 추가.
  - **검증**: py_compile OK + ruff check OK + pytest test_trading.py 48/48 통과(기존 31 + 신규 17) + pytest test_buy_order_executor.py 33/33 통과(임시 호환 코드 정상) + 런타임 `python -W error::RuntimeWarning main.py` 기동 성공 RuntimeWarning 0건 + 잔존 프로세스 0건.
- **구현 2세션 (완료)**: buy_order_executor 루프 제어 + _refresh_buyable_prices 헬퍼 + test_buy_order_executor.py 치환 + 차순위 시도 신규 테스트 10개 + 런타임 기동 검증 + HANDOVER.md 갱신 + 설계서 삭제(규칙 11).
  - **수정 파일**: `backend/app/services/buy_order_executor.py` + `backend/tests/test_buy_order_executor.py`
  - **buy_order_executor.py 변경**: 임시 호환 코드 제거 + `_refresh_buyable_prices()` 헬퍼 추가(모듈 레벨 — 기존 `_buyable_codes` 구축 로직과 통합, P10 SSOT) + 루프 제어 로직 변경(차순위 시도 알고리즘 — 1순위 성공 후 잔액/한도 잔존 시 continue, 1순위 종목별 차단 시 continue, 1순위 전체 차단 시 break, 잔액 0·최대 보유수·일일 한도 도달 시 break) + BUY_REJECT_QTY_ZERO 조건부 판별(잔액 재조회로 전체/종목별 분기) + 매수 사유 문자열에 순위 추가 + docstring 갱신 + import 추가(BUY_REJECT_QTY_ZERO, BUY_GLOBAL_REJECT_REASONS, get_risk_manager as _get_rm).
  - **test_buy_order_executor.py 변경**: 9곳 `return_value=True` → `(True, "")` 치환 + 3곳 `return_value=False` → `(False, BUY_REJECT_RISE_GUARD)` 치환 + `test_only_first_target_attempted` 제거(더 이상 유효하지 않은 "1순위만 시도" 검증 — 설계서 7-3 누락 발견) + `test_same_buyable_codes_different_order_skips` await_count 1→2 수정(2세션 차순위 시도로 종목별 차단 시 2회 호출) + 신규 TestMultiRankBuyAlgorithm 클래스 10개 테스트 추가.
  - **검증**: py_compile OK + ruff check OK + pytest test_buy_order_executor.py 42/42 통과(기존 32 + 신규 10) + pytest test_trading.py 48/48 통과(회귀 없음) + 전체 회귀 10 failed/2918 passed(10개 실패는 1세션 상태에서도 동일 — 본 2세션 수정 무관한 기존 실패, 규칙 4-1 추적 완료) + 런타임 `python -W error::RuntimeWarning main.py` 기동 성공 RuntimeWarning 0건 + 잔존 프로세스 0건.

---

## 이전 다단계 작업: 1일봉 다운로드 타임테이블 통합 — 완료 (5/5세션)

## 세션 개요 (이전)
- 날짜: 2026-07-18 (1일봉 다운로드 타임테이블 통합 다단계 작업 5세션 — 프론트엔드 + 최종 검증 + 계획서 삭제 완료 · **다단계 작업 전체 완료**)
- 작업: 1일봉차트 확정 다운로드 시간 DB 타임테이블 통합 다단계 작업 5세션(프론트엔드 + 최종 검증 + 계획서 삭제) 진행. 사용자 명시적 실행 지시어("5세션 진행해")로 진행 승인. 프론트엔드 2개 파일 수정: `frontend/src/types/index.ts`(라인 150 `confirmed_download_time: string` → `'timetable.confirmed_download': string` — P23 일관성), `frontend/src/pages/general-settings.ts`(`savingConfirmedDl` 변수 제거 + `scheduleConfirmedDlSave()` 함수 전체 제거 + `scheduleTimetableSave()` 시그니처 확장 — `key` 타입에 `'timetable.confirmed_download'` 추가 + 라인 312 `vals.confirmed_download_time` → `vals['timetable.confirmed_download']` + 라인 314-317 콜백 `scheduleConfirmedDlSave()` → `scheduleTimetableSave('timetable.confirmed_download', \`${h}:${m}\`)` 호출로 변경 + 라인 967 `r.confirmed_download_time` → `r['timetable.confirmed_download']` — P10 SSOT + P23 일관성 + P24 단순성). 문서 1개 파일 수정: `ARCHITECTURE.md`(라인 983 `confirmed_download_time` → `timetable.confirmed_download` 갱신 + 라인 1041 `ws_subscribe_timer_handles: list` 제거 — P14 단일 타이머. 단, `last_confirmed_download_date`는 다른 멱등성 가드 필드들이 ARCHITECTURE.md에 명시되어 있지 않으므로 일관성 유지를 위해 추가하지 않음 — 태스크 파일에서 약간 조정). 계획서 2개 삭제(규칙 11): `docs/architecture_download_timetable_integration_design.md` + `docs/plan_download_timetable_integration.md`. 정적 검증: `npm run typecheck` OK + `npm run build` OK (빌드 성공) + `npm run test` (vitest) 116/116 통과 (8개 테스트 파일). 런타임 기동 검증: `python -W error::RuntimeWarning main.py` 기동 성공 — RuntimeWarning 0건 + "타임테이블 빌드 완료 — 11항목" 로그 확인 + "단절 구간 기동 — 확정 다운로드 시각(20:40) 이전 — 타이머 대기" 로그 확인 + 잔존 프로세스 0건. 백엔드 회귀: pytest test_daily_time_scheduler+test_engine_settings+test_settings_store 357/357 통과. 잔존 참조 검색: `confirmed_download_time`/`ws_subscribe_timer_handles`/`schedule_ws_subscribe_timers`/`_fire_confirmed_download`/`scheduleConfirmedDlSave`/`savingConfirmedDl` — 코드 파일(backend/frontend) 0건 (역사적 조사 문서 `krx_receive_rate_missing_investigation.md`는 규칙 3에 따라 유지). 신규 함수/상수/컴포넌트 생성 없음 — 기존 공통 자산 재사용(P23/P24). 사용자 체감 변화 없음 (UI 입력칸, 다운로드 시간, 토글 동작 모두 기존과 동일).
- 상태: 5세션(프론트엔드 + 최종 검증 + 계획서 삭제) 완료. **1일봉 다운로드 타임테이블 통합 다단계 작업 5세션 전체 완료.** 커밋 진행 중.
- **참조 규칙**: AGENTS.md 섹션3 규칙 0(승인 전 수정 금지) + 규칙 0-1(세션당 1단계) + 규칙 0-2(수정 전 사전조사) + 규칙 4-1(테스트 실패 추적) + 섹션4 "다단계 작업 워크플로우" + 규칙 11(계획서 삭제) + P10/P14/P16/P20/P21/P22/P23/P24

## 1일봉 다운로드 타임테이블 통합 다단계 작업 — 완료 (5/5세션)

### 단계 진행 상황
- **1세션 (완료)**: 설계서 작성 — 이전 세션 검토(방식 A/B 비교) + 사용자 확정 7항목 반영.
  - **설계서**: `docs/architecture_download_timetable_integration_design.md` (398줄)
  - **핵심 설계**: 방식 A(아키텍처 원칙 완전 부합) 채택. `confirmed_download_time` → `timetable.confirmed_download` 키 이름 변경 + DB 마이그레이션(db-backup 선행). `build_timetable_from_cache()` 11번째 항목 추가 (토글 OFF 시 엔트리 스킵 — P16 dead path 제거). `schedule_ws_subscribe_timers()` 분기 제거 (함수 자체 제거 검토). 멱등성 가드 `state.last_confirmed_download_date` 추가 (P22, 기존 `last_realtime_reset_date` 패턴 재사용). 순서 검증 2그룹 분리 — 그룹1 사전 준비 3개 키(`rt <= ws <= krx < 09:00`), 그룹2 확정 다운로드(`confirmed_download > 20:00`). `engine_service.py` `_WS_SCHEDULE_KEYS` 제거 → `_TIMETABLE_KEYS`에 `timetable.confirmed_download` + `scheduler_market_close_on` 추가. 프론트엔드 `scheduleConfirmedDlSave()` → `scheduleTimetableSave()` 통합 (P23 일관성). 사용자 체감 변화 없음 (UI 입력칸, 다운로드 시간, 토글 동작 모두 기존과 동일).
  - **세션 분할 (5세션 확정)**: 1세션(설계서·완료) / 2세션(심층 사전조사 + 태스크 파일 작성) / 3세션(DB 마이그레이션 + 백엔드 키 변경) / 4세션(타임테이블 통합 + 멱등성 가드) / 5세션(프론트엔드 + 최종 검증 + 계획서 삭제)
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성 — 대상 파일 11개 의존성·영향 범위 식별, 태스크 파일에 단계별 검증 항목 명시.
  - **태스크 파일**: `docs/plan_download_timetable_integration.md` (473줄)
  - **심층 발견사항**: 대상 파일 11개(백엔드 6 + 프론트엔드 2 + 테스트 3) + DB + ARCHITECTURE.md. 수정 포인트 24개(A-X) 식별. `schedule_ws_subscribe_timers()` 호출자 3곳 식별(engine_service.py:135, _on_midnight:1410, start_daily_time_scheduler:1494). `is_ws_subscribe_window()` 테스트의 `confirmed_download_time` 참조 50곳은 cosmetic(함수 내부 미사용), `retry_pipeline_catchup_after_bootstrap()` 10곳은 실제 키 사용(line 687). 3세션 완료 후 런타임 기동 시 KeyError 가능성 식별 → 3세션은 정적 검증만, 런타임 기동은 4세션으로 이월. 자정 타임테이블 재빌드 보완 필요성 식별(4세션에서 처리). 타임테이블 direct 콜백 비동기 패턴 `_timetable_event_fired()` 검증 필요(4세션). 기존 공통 자산 10개 재사용 확인 — 신규 함수/상수/컴포넌트 생성 없음(P23/P24). 역사적 조사 문서(`krx_receive_rate_missing_investigation.md`)는 코드 제거 규칙 3에 따라 유지.
  - **세션 분할 (3세션 구현 확정)**: 3세션(DB 마이그레이션 + 백엔드 키 변경 — A,B,C,D,E,F,G,H,I,J) / 4세션(타임테이블 통합 + 멱등성 가드 — K,L,M,N,O,P,Q,R,S,T) / 5세션(프론트엔드 + 최종 검증 + 계획서 삭제 — U,V,W,X)
- **3세션 (완료)**: DB 마이그레이션 + 백엔드 키 변경 — db-backup 스킬 백업(20260718_034627) → DB 마이그레이션(`confirmed_download_time` → `timetable.confirmed_download` key UPDATE, 값 '20:40' 보존) → `settings_defaults.py`/`engine_settings.py`/`settings_store.py` 키 변경 + 순서 검증 2그룹 분리 → `test_settings_store.py`/`test_engine_settings.py` 테스트 수정.
  - **변경 파일 5개**: `backend/app/core/settings_defaults.py` (+2/-2), `backend/app/core/engine_settings.py` (+2/-2), `backend/app/core/settings_store.py` (+83/-55), `backend/tests/test_settings_store.py` (+97/-16), `backend/tests/test_engine_settings.py` (+5/-5)
  - **수정 포인트 10개 (A-J)**: (A) DB 마이그레이션 — `integrated_system_settings` 키 UPDATE, 값 보존 / (B) `settings_defaults.py` `confirmed_download_time` 제거 → `timetable.confirmed_download`를 `timetable.*` 네임스페이스에 추가 / (C) `engine_settings.py` `result["confirmed_download_time"]` → `result["timetable.confirmed_download"]` + 주석 갱신 / (D) `settings_store.py` `general_save_payload_from_flat()` 키 변경 / (E) `_TIME_FIELDS` 키 치환 / (F) `_TIMETABLE_ORDER_KEYS` 2그룹 분리 → `_TIMETABLE_PRE_OPEN_KEYS` + `_TIMETABLE_POST_CLOSE_KEYS` (하위 호환 `_TIMETABLE_ORDER_KEYS` 합집합 유지) / (G) `_validate_timetable_order()` 2단계 검증 분리 — 그룹1: rt ≤ ws ≤ krx < 09:00 / 그룹2: confirmed_download > 20:00 (NXT 종료 이후, 상한선 없음) / (H) `select_keys` 확장 — 그룹별 독립 확장 / (I) `test_settings_store.py` 키 치환 3곳 + 그룹2 검증 테스트 7개 추가 / (J) `test_engine_settings.py` 키 치환 2개 테스트
  - **검증**: py_compile OK + ruff check OK + pytest test_settings_store+test_engine_settings 136/136 통과 + test_daily_time_scheduler 217/217 통과 + 전체 회귀 2897 passed (기존 실패 1개 `test_trading.py::TestExecuteBuyGates::test_rebuy_block_disabled`은 원본 코드에서도 동일 실패 — 테스트 격리 문제, 본 수정과 무관, 규칙 4-1 준수)
  - **잔존 참조 (4세션/5세션 처리 예정)**: `daily_time_scheduler.py` 8곳(4세션 R/O), `engine_service.py` 1곳(4세션 S), `test_daily_time_scheduler.py` 27곳(4세션 T), `general-settings.ts` 4곳(5세션 U), `types/index.ts` 1곳(5세션 V), `ARCHITECTURE.md` 1곳(5세션 W). 태스크 파일 + 설계서는 5세션에서 삭제(규칙 11).
  - **런타임 기동 검증 이월**: 3세션 완료 후 `daily_time_scheduler.py` 2곳(line 687, 1157) 키 참조 미변경으로 런타임 기동 시 KeyError 가능 → 3세션은 정적 검증만 수행, 런타임 기동은 4세션 완료 후 수행.
- **4세션 (완료)**: 타임테이블 통합 + 멱등성 가드 — `engine_state.py` `ws_subscribe_timer_handles` 제거 + `last_confirmed_download_date` 추가 → `daily_time_scheduler.py` `build_timetable_from_cache()` 11번째 항목 추가(토글 OFF 시 스킵, P16) + `_on_confirmed_download()` 멱등성 가드(P22) + `_on_midnight()` 가드 리셋 + `schedule_ws_subscribe_timers()` + `_fire_confirmed_download()` 제거 + `start/stop_daily_time_scheduler()` 정리 + `retry_pipeline_catchup_after_bootstrap()` 키 참조 변경 → `engine_service.py` `_WS_SCHEDULE_KEYS` 제거 + `_TIMETABLE_KEYS` 확장(`timetable.confirmed_download` + `scheduler_market_close_on`) + 분기 재작성 → `test_daily_time_scheduler.py` + `test_engine_settings.py` 테스트 수정.
  - **변경 파일 5개**: `backend/app/services/engine_state.py` (+1/-1), `backend/app/services/daily_time_scheduler.py` (+51/-113), `backend/app/services/engine_service.py` (+23/-42), `backend/tests/test_daily_time_scheduler.py` (+137/-69), `backend/tests/test_engine_settings.py` (+68/-0)
  - **수정 포인트 10개 (K-T)**: (K) `engine_state.py` `ws_subscribe_timer_handles` 제거 + `last_confirmed_download_date` 추가 / (L) `build_timetable_from_cache()` 11번째 항목 추가 — `timetable.confirmed_download` direct 항목, 토글 OFF 시 스킵 (P16) / (M) `_on_confirmed_download()` 멱등성 가드 추가 — `last_confirmed_download_date == today_str` 시 스킵 (P22) / (N) `_on_midnight()` 가드 리셋 추가 + `schedule_ws_subscribe_timers()` 호출 제거 / (O) `schedule_ws_subscribe_timers()` 함수 + `_fire_confirmed_download()` 동기 래퍼 제거 / (P) `start_daily_time_scheduler()` `schedule_ws_subscribe_timers()` 호출 제거 / (Q) `stop_daily_time_scheduler()` `ws_subscribe_timer_handles` 블록 제거 / (R) `retry_pipeline_catchup_after_bootstrap()` 키 참조 변경 — `confirmed_download_time` → `timetable.confirmed_download` / (S) `engine_service.py` `_WS_SCHEDULE_KEYS` 제거 + `_TIMETABLE_KEYS`에 `timetable.confirmed_download` + `scheduler_market_close_on` 추가 + 분기 재작성 (단일 타임테이블 재빌드 경로) / (T) `test_daily_time_scheduler.py` + `test_engine_settings.py` 테스트 수정 — import 정리 + 키 치환 + 함수 제거 테스트 삭제 + 멱등성 가드 테스트 2개 + 토글 스킵 테스트 2개 + 재빌드 테스트 2개 추가
  - **검증**: py_compile OK + ruff check OK + pytest test_daily_time_scheduler 219/219 통과 + test_engine_settings+test_settings_store 138/138 통과 + 전체 회귀 2901 passed (기존 실패 1개 `test_trading.py::TestExecuteBuyGates::test_rebu_block_disabled`은 개별 실행 시 통과 — 테스트 격리 문제, 본 수정과 무관, 규칙 4-1 준수) + 런타임 기동 `python -W error::RuntimeWarning main.py` RuntimeWarning 0건 + "타임테이블 빌드 완료 — 11항목" 로그 확인 + 잔존 프로세스 0건
  - **잔존 참조 (5세션 처리 예정)**: `general-settings.ts` 4곳(5세션 U), `types/index.ts` 1곳(5세션 V), `ARCHITECTURE.md` 2줄(5세션 W). 태스크 파일 + 설계서는 5세션에서 삭제(규칙 11).
- **5세션 (완료)**: 프론트엔드 + 최종 검증 + 계획서 삭제 — `frontend/src/types/index.ts` `confirmed_download_time` → `'timetable.confirmed_download'` → `frontend/src/pages/general-settings.ts` `savingConfirmedDl` 변수 제거 + `scheduleConfirmedDlSave()` 함수 제거 + `scheduleTimetableSave()` 시그니처 확장(`'timetable.confirmed_download'` 추가) + 3곳 키 참조 변경(`vals.confirmed_download_time`/콜백/`r.confirmed_download_time`) → `ARCHITECTURE.md` 라인 983 갱신 + 라인 1041 `ws_subscribe_timer_handles` 제거 → 최종 검증 → 설계서 + 태스크 파일 삭제(규칙 11).
  - **변경 파일 3개 + 삭제 2개**: `frontend/src/types/index.ts` (+1/-1), `frontend/src/pages/general-settings.ts` (+6/-25), `ARCHITECTURE.md` (+2/-3). 삭제: `docs/architecture_download_timetable_integration_design.md` (398줄), `docs/plan_download_timetable_integration.md` (473줄)
  - **수정 포인트 4개 (U-W + X)**: (U) `general-settings.ts` `scheduleConfirmedDlSave()` 제거 → `scheduleTimetableSave()` 통합 — `savingConfirmedDl` 중복 상태 변수 제거 + 시그니처 확장 + 3곳 키 참조 변경 (P10 SSOT + P23 일관성 + P24 단순성) / (V) `types/index.ts` `confirmed_download_time: string` → `'timetable.confirmed_download': string` (P23) / (W) `ARCHITECTURE.md` 라인 983 `confirmed_download_time` → `timetable.confirmed_download` 갱신 + 라인 1041 `ws_subscribe_timer_handles: list` 제거 (P14). 단, `last_confirmed_download_date`는 다른 멱등성 가드 필드들이 ARCHITECTURE.md에 명시되어 있지 않으므로 일관성 유지를 위해 추가하지 않음 — 태스크 파일에서 약간 조정 / (X) 최종 검증 + 계획서 2개 삭제 (규칙 11)
  - **검증**: `npm run typecheck` OK + `npm run build` OK (빌드 성공 1.78s) + `npm run test` (vitest) 116/116 통과 (8개 테스트 파일) + 런타임 기동 `python -W error::RuntimeWarning main.py` RuntimeWarning 0건 + "타임테이블 빌드 완료 — 11항목" 로그 확인 + "단절 구간 기동 — 확정 다운로드 시각(20:40) 이전 — 타이머 대기" 로그 확인 + 잔존 프로세스 0건 + 백엔드 회귀 pytest 357/357 통과 + 잔존 참조 검색 코드 파일 0건
  - **다단계 작업 전체 완료**: 1세션(설계서) → 2세션(사전조사+태스크) → 3세션(DB 마이그레이션+백엔드 키) → 4세션(타임테이블 통합+멱등성 가드) → 5세션(프론트엔드+최종 검증+계획서 삭제). 단일 타임테이블 + 단일 타이머 + `timetable.*` 네임스페이스 SSOT 완성.

## 다음 세션 진행 대기: 없음 (1일봉 다운로드 타임테이블 통합 다단계 작업 전체 완료)

> 5세션(프론트엔드 + 최종 검증 + 계획서 삭제) 완료. 다단계 작업 5세션 전체 완료.
> 사용자 체감 변화 없음 (UI 입력칸, 다운로드 시간, 토글 동작 모두 기존과 동일). 브라우저 확인은 사용자가 직접 수행 권장 (시간 설정 탭 "1일봉차트 자동다운로드" 섹션 표시 + 시간 슬롯 + 토글 + 저장 동작 정상).

## 이전 다단계 작업: 일반설정 탭 재구성 — 전체 완료 (3~8세션, 총 6세션)

### 단계 진행 상황
- **1세션 (완료)**: 설계서 작성 — 검토 결과(이전 세션) + 사용자 확정 4항목 반영.
  - **설계서**: `docs/architecture_settings_tab_reorganization_design.md` (293줄)
  - **핵심 설계**: "시간 설정" 탭 신설(자동매수/매도 시간쌍 + 사전 준비 3슬롯 + 1일봉 다운로드 + 거래소 고정 시간 참고). 자동매매 탭 정리(매매 토글 4개 + 플래시 효과 이동). API 설정 탭 정리(증권사 + API 키만). 탭 순서: 자동매매 → 시간 설정 → 투자모드 → API 설정 → 텔레그램. "화면 설정" 탭 신설 기각(사용자 의견: 과잉). 자동매수/매도 토글 OFF 시 시간 입력 활성화 유지 + 안내 문구. 백엔드 변경 없음.
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성.
  - **태스크 파일**: `docs/plan_settings_tab_reorganization.md` (260줄)
  - **심층 발견사항**: 대상 파일 단일 `general-settings.ts` (약 1122줄). 백엔드 영향 없음. 기존 공통 컴포넌트 재사용 — 신규 컴포넌트 생성 없음. 핵심 내부 의존성 13항목 식별. `syncFromSettings()`가 모든 탭 동기화를 한 곳에서 처리 → 재구성 시 이 함수도 수정 필요. `unmount()`에서 모든 모듈 상태 변수 초기화 → 새 변수 추가 시 여기도 업데이트.
  - **세션 분할 (6세션 확정)**: 3세션(Step 1: 탭 골조 추가) / 4세션(Step 2: 자동매수/매도 시간쌍 이동) / 5세션(Step 3: 사전 준비 시간 + 거래소 고정 시간 이동) / 6세션(Step 4: 1일봉 다운로드 이동) / 7세션(Step 5: 플래시 효과 이동) / 8세션(Step 6: 최종 검증 + 정리 + 계획서 삭제)
- **3세션 (완료)**: Step 1 구현 — 탭 골조 추가.
  - **변경 파일 1개**: `frontend/src/pages/general-settings.ts` (+16줄 / -5줄)
  - **수정 포인트 4개 (A/B/C/D)**: (A) `TabId` 타입에 `'time-settings'` 추가 / (B) `renderTabBar()` tabs 배열 순서 변경 + 시간 설정 탭 추가 / (C) 신규 `renderTimeSettingsTab(container)` 골조 함수 추가 (sectionTitle만) / (D) `mount()`에 5번째 패널 추가 + 패널 순서 일치
  - **검증**: typecheck + 빌드 + 전체 테스트 116/116 통과
- **4세션 (완료)**: Step 2 구현 — 자동매수/매도 시간쌍 이동.
  - **변경 파일 1개**: `frontend/src/pages/general-settings.ts` (+64줄 / -54줄)
  - **수정 포인트 3개**: (1) `renderAutoTradeTab()` 자동매수/매도 행 단순화 — 시간쌍 입력 제거, 토글만 남김 + 안내 문구 "시간 설정은 시간 설정 탭에서" 추가 / (2) `renderTimeSettingsTab()`에 자동매수 시간쌍 + 자동매도 시간쌍 + 안내 문구 추가 ("자동매수/매도가 꺼져 있어도 시간을 미리 설정할 수 있습니다...") / (3) `syncFromSettings()`에서 `buyTimeHandle.setEnabled()`/`sellTimeHandle.setEnabled()` 호출 제거 (토글 OFF 시에도 시간 입력 활성화 유지 — 설계서 2-1)
  - **핵심 동작 변경 (사용자 확인 필요)**: 기존에는 자동매수/매도 토글을 끄면 시간 입력칸이 회색으로 비활성화되었음. 변경 후에는 토글이 꺼져 있어도 시간 입력칸이 항상 활성화되어 미리 시간을 설정할 수 있음. 안내 문구로 "자동매수/매도가 꺼져 있어도 시간을 미리 설정할 수 있습니다. 자동매매 탭에서 자동매수/매도를 켜면 이 시간에 맞춰 실행됩니다." 표시 (P21 사용자 투명성)
  - **검증**: typecheck 통과 + 빌드 통과 (1.89s) + 전체 테스트 116/116 통과. 브라우저 검증은 사용자 확인 필요 (시간 설정 탭에 자동매수/매도 시간쌍 표시 + 자동매매 탭에 토글만 표시 + 토글 OFF 시에도 시간 입력 활성화 + 저장 동작 정상)
- **5세션 (완료)**: Step 3 구현 — 사전 준비 시간 + 거래소 고정 시간 이동.
  - **변경 파일 1개**: `frontend/src/pages/general-settings.ts` (+95줄 / -95줄 — 코드 이동으로 증감 일치)
  - **수정 포인트 2개**: (1) `renderAutoTradeTab()`에서 "장 시작 전 사전 준비 시간" 섹션(sectionTitle + 설명 + 3개 슬롯) + "거래소 고정 시간 참고" 박스(7개 행) 제거 → 체결 불가 시간대 차단 토글 행 아래의 설명 문구로 함수 종료 / (2) `renderTimeSettingsTab()`에 자동매도 시간쌍 행 아래, 안내 문구 위에 사전 준비 시간 섹션 + 거래소 고정 시간 참고 박스 추가 (설계서 3-2 시간순 배치 준수). 함수 주석도 "Step 3 사전 준비 시간·거래소 고정 시간 이동" 반영으로 갱신.
  - **핵심 동작 변경 (사용자 확인 필요)**: 기존에는 "장 시작 전 사전 준비 시간" 3개 슬롯(실시간 항목 초기화 07:58 / 구독 사전 시작 07:59 / 정규장 사전 구독 08:59)과 "거래소 고정 시간 참고"(08:00~20:00, 7개)가 자동매매 탭 하단에 있었음. 변경 후 이들이 시간 설정 탭으로 이동. 자동매매 탭에는 마스터 토글, 자동매수/매도 토글, 체결 불가 시간대 차단 토글만 남음. 시간을 변경하거나 거래소 고정 시간을 확인하려면 시간 설정 탭으로 이동 (P21 사용자 투명성, P24 단순성)
  - **검증**: typecheck 통과 + 빌드 통과 (630ms) + 전체 테스트 2887 passed / 1 failed (`test_trading.py::TestExecuteBuyGates::test_rebuy_block_disabled` — 개별 실행 시 통과, 전체 실행 시 실패하는 테스트 격리 문제, 프론트엔드 수정과 무관 확인 완료 규칙 4-1). 브라우저 검증은 사용자 확인 필요 (시간 설정 탭에 사전 준비 시간 3개 슬롯 + 거래소 고정 시간 참고 표시 + 자동매매 탭에서 해당 섹션 제거 + 저장 동작 정상)
- **6세션 (완료)**: Step 4 구현 — 1일봉차트 자동다운로드 이동.
  - **변경 파일 1개**: `frontend/src/pages/general-settings.ts` (+43줄 / -43줄 — 코드 이동으로 증감 일치)
  - **수정 포인트 3개**: (1) `renderTimeSettingsTab()`에 정규장 사전 구독 슬롯 아래, 거래소 고정 시간 참고 박스 위에 "1일봉차트 자동다운로드" 섹션(sectionTitle + 토글 + 시간 슬롯 + 설명 문구) 추가 (설계서 3-2 시간순 배치 준수) / (2) `renderApiSettingsTab()`에서 1일봉 다운로드 행 + 설명 문구 제거 ("실시간 데이터 통신" 섹션 제목은 플래시 효과 Step 5 이동 대상이므로 유지) / (3) `renderTimeSettingsTab()` 함수 주석에 Step 4 반영 갱신
  - **핵심 동작 변경 (사용자 확인 필요)**: 기존에는 "1일봉차트 자동다운로드" 토글과 시간 슬롯이 API 설정 탭에 있었음. 변경 후 시간 설정 탭으로 이동. API 설정 탭에는 증권사 선택과 API 키만 남게 됨 (플래시 효과는 Step 5에서 자동매매 탭으로 이동 예정). 1일봉 다운로드 시간을 변경하거나 토글을 켜고 끄려면 시간 설정 탭으로 이동 (P21 사용자 투명성, P24 단순성)
  - **검증**: typecheck 통과 + 빌드 통과 (631ms) + 전체 테스트 2887 passed / 1 failed (`test_trading.py::TestExecuteBuyGates::test_rebuy_block_disabled` — 5세션과 동일한 테스트 격리 문제, 개별 실행 시 통과, 프론트엔드 수정과 무관 확인 완료 규칙 4-1). 브라우저 검증은 사용자 확인 필요 (시간 설정 탭에 1일봉 다운로드 토글 + 시간 슬롯 표시 + API 설정 탭에서 해당 행 제거 + 저장 동작 정상)
- **7세션 (완료)**: Step 5 구현 — 플래시 효과 이동.
  - **변경 파일 1개**: `frontend/src/pages/general-settings.ts` (+27줄 / -26줄 — 코드 이동으로 증감 거의 일치)
  - **수정 포인트 3개**: (1) `renderAutoTradeTab()` 하단(체결 불가 시간대 차단 토글 설명 문구 다음)에 "화면 표시" 섹션(sectionTitle) + 실시간 현재가 플래시 효과 토글 행 + 설명 문구 추가 (설계서 5-3 준수) / (2) `renderApiSettingsTab()`에서 "실시간 데이터 통신" 섹션 제목 + 플래시 효과 토글 행 + 설명 문구 제거 / (3) `renderAutoTradeTab()` 내에 Step 5 주석 추가 ("화면 표시 섹션 — 플래시 효과 (API 설정 탭에서 이동, Step 5, 설계서 5-3)")
  - **핵심 동작 변경 (사용자 확인 필요)**: 기존에는 "실시간 현재가 플래시 효과" 토글이 API 설정 탭에 있었음. 변경 후 자동매매 탭 하단의 "화면 표시" 섹션으로 이동. API 설정 탭에는 증권사 선택과 API 키만 남게 됨 (재구성 완료). 플래시 효과를 켜거나 끄려면 자동매매 탭 하단으로 이동 (P21 사용자 투명성, P24 단순성)
  - **검증**: typecheck 통과 + 빌드 통과 (1.92s, general-settings 청크 새 해시 PEcOWj2_.js) + 전체 테스트 116/116 통과. 브라우저 검증은 사용자 확인 필요 (자동매매 탭 하단에 "화면 표시" 섹션 + 플래시 효과 토글 표시 + 토글 변경 시 백엔드 저장 + API 설정 탭에서 해당 섹션 제거 확인)
- **8세션 (완료)**: Step 6 구현 — 최종 검증 + 정리 + 계획서 삭제.
  - **변경 파일 2개 (삭제)**: `docs/architecture_settings_tab_reorganization_design.md` + `docs/plan_settings_tab_reorganization.md` (규칙 11 — 다단계 작업 완료 시 계획서 삭제)
  - **검증 항목**: (1) typecheck 통과 + 빌드 통과 + 전체 테스트 116/116 통과 / (2) dead code 잔존 점검 — 모든 설정 키가 살아있는 경로에 연결, 잔존 없음 / (3) 5개 탭 구조 원칙 점검 P10/P16/P20/P21/P23/P24 모두 준수 / (4) 계획서 파일 2개 삭제 완료
  - **5개 탭 최종 구조**: 자동매매(마스터 토글, 자동매수 토글, 자동매도 토글, 체결 불가 시간대 차단, 화면 표시-플래시 효과) / 시간 설정(자동매수/매도 시간쌍, 사전 준비 3슬롯, 1일봉 다운로드, 거래소 고정 시간 참고) / 투자모드(기존 동일) / API 설정(증권사 선택 + API 키만) / 텔레그램(기존 동일)
  - **브라우저 최종 확인 필요 (사용자)**: 5개 탭 전환·표시·모든 설정 저장 동작 정상

## 다음 세션 진행 대기: 없음 (일반설정 탭 재구성 다단계 작업 전체 완료)

> 다단계 작업 전체 완료. 다음 작업은 사용자 신규 요청 시 진행.

## 이전 다단계 작업: DB 테이블 스케줄러 (다단계 작업) — 전체 완료

### 단계 진행 상황
- **1세션 (완료)**: 설계서 작성 — 사전조사 + 사용자 검토 요청 → 방식 B 채택 결정 + 설계서 작성.
  - **설계서**: `docs/architecture_db_timetable_design.md` (325줄, 완료 후 삭제 완료 — 규칙 11)
  - **핵심 설계**: 방식 B(key-value 평면 `timetable.*` 네임스페이스)로 3개 키(realtime_reset 07:58 / ws_prestart 07:59 / krx_pre_subscribe 08:59)를 `integrated_system_settings` 테이블에 저장. 거래소 고정 7개(08:00/09:00/15:20/15:30/15:40/18:00/20:00)는 코드 상수 유지. 시간 순서 검증(`realtime_reset ≤ ws_prestart ≤ krx_pre_subscribe < 09:00`) 필수. 저장 후 `_schedule_next_timetable_event()` 재호출로 타이머 재예약. `_TIMETABLE` 정적 리스트 → `build_timetable_from_cache()` 빌더 함수 방식 변경(규칙 0-5 사전 통지).
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성.
  - **태스크 파일**: `docs/plan_db_timetable.md` (631줄)
  - **심층 발견사항 6항목**: (2-1) `settings_defaults.py:117` 삽입 위치 확정 + `DEFAULT_SETTINGS` 병합 자동 전파 확인 / (2-2) `_validate_timetable_order()` 구현 세부 — `before` 인자로 나머지 2개 키 보충 + `select_keys` (라인 148) 확장 필요 + `routes/settings.py:84`가 `ValueError` → HTTP 422 자동 변환 (라우트 변경 불필요) / (2-3) `_TIMETABLE` 정적 리스트 제거 → 빈 리스트 + 빌더 함수 + `_schedule_next_timetable_event()` fallback(999-1003)도 `_TIMETABLE[0]["time"]` 참조로 변경 필요 (불일치 가능성 발견) / (2-4) 기동 빌드 배선 위치: `start_daily_time_scheduler()` 내 `_timetable_startup_scan()` 직전이 최적 (app.py 변경 불필요) / (2-5) `_TIMETABLE_KEYS` 분기는 `_WS_SCHEDULE_KEYS` 종료 직후 + 모듈 전역 재할당은 `_dts_mod._TIMETABLE = ...` 방식 (state 필드 아님, setter는 P24 위반) / (2-6) 프론트엔드 `createTimeSlot()` 재사용 — `confirmed_download_time` 행(590) 동일 패턴, 신규 컴포넌트 불필요, `renderAutoTradeTab()` 라인 288 다음 삽입
  - **다단계 분할 (6세션 확정)**: 1세션(설계서·완료) / 2세션(태스크 파일·완료) / 3세션(백엔드 Step 1·완료) / 4세션(백엔드 Step 2: 빌더 함수 + 기동 배선·완료) / 5세션(백엔드 Step 3: 저장 후 재예약 배선·완료) / 6세션(프론트엔드 Step 4: 입력칸 + 거래소 고정 표시·완료) / 7세션(프론트엔드 Step 5: 검증 에러 표시 + 저장 플로우 연결 + 테스트 갱신)
- **3세션 (완료)**: 백엔드 Step 1 구현 — 설정 키 3개 + 시간 순서 검증.
  - **변경 파일 3개**: `backend/app/core/settings_defaults.py` (3개 키 추가) + `backend/app/core/settings_store.py` (import + _TIME_FIELDS 확장 + _validate_timetable_order() + select_keys 확장 + 검증 배선) + `backend/tests/test_settings_store.py` (신규 11개 테스트)
  - **검증**: py_compile + ruff 통과 + test_settings_store.py 63개 통과 (신규 11 + 기존 52) + 전체 회귀 2876 passed / 1 failed (기존 실패, 본 수정 무관 — git stash로 검증) + 런타임 기동 RuntimeWarning 0건 + 잔존 프로세스 0건
- **4세션 (완료)**: 백엔드 Step 2 구현 — 빌더 함수 + 기동 배선.
  - **변경 파일 2개**: `backend/app/services/daily_time_scheduler.py` (_TIMETABLE 빈 리스트 + _parse_hm_tuple + build_timetable_from_cache + fallback 갱신 + start_daily_time_scheduler 빌드 배선) + `backend/tests/test_daily_time_scheduler.py` (import 추가 + TestTimetableBuilder 6개 + setup/teardown fixture)
  - **검증**: py_compile + ruff 통과 + test_daily_time_scheduler.py 217개 통과 (신규 6 + 기존 211) + 전체 회귀 2882 passed / 1 failed (기존 실패 test_rebuy_block_disabled, 본 수정 무관 — git stash로 검증) + 런타임 기동 RuntimeWarning 0건 + `[기동] 타임테이블 빌드 완료 — 10항목` 로그 정상 + 잔존 프로세스 0건
- **5세션 (완료)**: 백엔드 Step 3 구현 — `engine_service.py` `_TIMETABLE_KEYS` 분기 + 재빌드/재예약 배선.
  - **변경 파일 2개**: `backend/app/services/engine_service.py` (_TIMETABLE_KEYS 집합 + lazy import + _dts_mod._TIMETABLE 직접 재할당 + _schedule_next_timetable_event 재예약 + info/warning 로그) + `backend/tests/test_engine_settings.py` (TestApplySettingsChangeTimetableRebuild 5개 + setup/teardown _TIMETABLE 백업·복원)
  - **검증**: py_compile + ruff 통과 + test_engine_settings.py 63개 통과 (신규 5 + 기존 58) + 전체 회귀 2887 passed / 1 failed (기존 실패 test_rebuy_block_disabled, 본 수정 무관 — git stash + 단독 실행으로 검증, 4세션과 동일 테스트 격리 문제) + 런타임 기동 RuntimeWarning 0건 + `[기동] 타임테이블 빌드 완료 — 10항목` 로그 정상 + 잔존 프로세스 0건
- **6세션 (완료)**: 프론트엔드 Step 4 구현 — `general-settings.ts` "장 시작 전 사전 준비 시간" 카드 + 입력칸 3개 + 거래소 고정 시간 참고 표시.
  - **변경 파일 1개**: `frontend/src/pages/general-settings.ts` (모듈 상태 변수 9개 + scheduleTimetableSave 함수 + renderAutoTradeTab 카드 삽입 + syncFromSettings 동기화)
  - **검증**: typecheck 통과 + build 통과 (tsc -b + vite build, general-settings 청크 새 해시 C0gdq2_y.js) + 개발 서버 HTTP 200 응답 정상
  - **UI 변경 (규칙 0-4)**: 자동매매 탭 하단에 "장 시작 전 사전 준비 시간" 카드 추가 — 입력칸 3개(실시간 항목 초기화/구독 사전 시작/정규장 사전 구독, 기존 시간 입력칸과 동일 패턴) + 거래소 고정 시간 7개 참고 박스(읽기 전용)
- **7세션 (완료)**: 프론트엔드 Step 5 구현 — 422 검증 에러 메시지 정교화 + 테스트 갱신.
  - **변경 파일 3개**: `frontend/src/api/client.ts` (`request<T>` 에러 분기에서 422 응답 본문 `detail` 필드 추출 → Error 메시지에 포함, 모든 API 호출자 동일 혜택 P23) + `frontend/src/pages/general-settings.ts` (주석 1줄 갱신) + `frontend/tests/api/client.test.ts` 신규 (5개 테스트) + `frontend/tests/settings.test.ts` (saveSection 3개 테스트 추가)
  - **검증**: typecheck 통과 + build 통과 (general-settings 청크 새 해시 Db12K4gv.js) + vitest 116개 통과 (8개 파일, 신규 8개 포함)
  - **UI 변경 (규칙 0-4)**: 사용자가 시간 순서 위반 시(예: 정규장 사전 구독을 09:30으로 입력) 기존 "API error: 422" 대신 실제 검증 메시지("유효하지 않은 설정값: 타임테이블 시간 순서 오류: 실시간 초기화(07:58) ≤ 구독 시작(07:59) ≤ 정규장 사전 구독(09:30) < 09:00 이어야 합니다")가 토스트에 표시 → 어떤 값을 고쳐야 하는지 즉시 인지 (P21)

## 이전 다단계 작업: 타임테이블 기반 스케줄러 (다단계 작업) — 전체 완료

### 단계 진행 상황
- **1세션 (완료)**: 설계서 작성 — 사전조사(4개 서브에이전트 병렬) + 사용자 결정 6항목 확정 + 설계서 작성.
  - **설계서**: `docs/architecture_timetable_scheduler_design.md` (526줄, 완료 후 삭제 — 규칙 11)
  - **핵심 설계**: 10초 주기 `_market_phase_periodic_loop()` → 시간표 리스트 + 단일 `call_later` 타이머 교체. 시간표 10개 항목(07:58~20:00, direct 3개 + phase 7개). JIF 1순위 경로 유지(수신 시각 기록 1줄 추가만). 헬스체크 옵션 A(이벤트 시점 JIF 미수신 체크). 자정 타이머 별도 유지. DB 연동·call_later 3개 통합·예외 시간표는 2세션 예고.
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성.
  - **태스크 파일**: `docs/plan_timetable_scheduler.md` (484줄, 완료 후 삭제 — 규칙 11)
  - **심층 발견사항 6항목**: (2-1) engine_state.py datetime import 누락 → 3세션에서 추가 / (2-2) market_phase_periodic_task 필드 라인 89→112 정정 / (2-3) 15:30·18:00 부작용 트리거 직접 분기 없음 → 페이즈 변경 감지로 자동 처리, 문제 없음 / (2-4) _on_krx_pre_subscribe 위치 559 → _TIMETABLE 배치 871 이후 / (2-5) typing import 불필요 → list[dict] 단순화 / (2-6) _check_prestart_triggers 제거는 4세션 (3세션은 신규 추가만)
  - **세션 분할**: 3세션(Step 1~6: 신규 함수 5개 + state 필드, 기존 코드 변경 없음) / 4세션(Step 7+8: JIF 갱신 1줄 + 10초 루프 3함수 + _check_prestart_triggers 제거 + start/stop 갱신) / 5세션(Step 9+10: 단위 테스트 10개 케이스 + 기존 테스트 갱신/제거 + 런타임 기동 검증)
- **3세션 (완료)**: Step 1~6 구현 — 신규 함수 5개 + state 필드 2개 + datetime import.
  - **변경 파일**: `daily_time_scheduler.py` (신규 추가 5개 함수 + `_TIMETABLE` 상수 + `_JIF_STALE_WARN_SEC` 상수, 942~944 사이 배치) + `engine_state.py` (`from datetime import datetime` import 추가 + `timetable_timer_handle`/`last_jif_received_at` 필드 2개 추가)
  - **사전조사 결과 (규칙 0-2 4항목)**: 태스크 파일의 모든 라인 위치·의존성을 실제 코드에서 재검증 완료. 시간 상수 10개(21-49)·direct 콜백 3개(802/838/559)·phase 콜백(769)·_kst_now(450)·schedule_engine_task(import L14) 전부 일치. engine_state.py datetime import 누락(2-1) 확인 후 추가.
  - **영향범위**: 백엔드 2개 파일만 변경. 기존 코드 변경 없음 — 신규 추가만 (P16 주의: 4세션 배선 전까지 dead code, 다단계 워크플로우 허용).
  - **검증**: py_compile + ruff 통과 + 기존 테스트 216개 전체 통과(회귀 없음) + 런타임 기동(`-W error::RuntimeWarning`) RuntimeWarning 0건 + 에러 없음 + 잔존 프로세스 0건. 기동 로그에서 기존 `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 유지 출력 (4세션 제거 예정) + 타임테이블 로그 미출력 (배선 전이므로 정상).
- **4세션 (완료)**: Step 7+8 구현 — 10초 루프 제거 + 타임테이블 배선 완료.
  - **변경 파일**: `engine_ws_dispatch.py` (`_handle_jif()` 진입부 `state.last_jif_received_at = _kst_now()` 1줄 + `_kst_now` import 추가) + `daily_time_scheduler.py` (10초 루프 4함수 + 상수 + 섹션 주석 제거 -93줄, start/stop 갱신, 관련 주석 2곳 갱신) + `engine_state.py` (`market_phase_periodic_task` 필드 제거)
  - **사전조사 결과 (규칙 0-2 4항목)**: 3세션 신규 코드 추가로 라인 번호 변경 반영 — 제거 대상 4함수 실제 위치 재확인 (_check_prestart_triggers 1437 / _market_phase_periodic_loop 1469 / _start 1498 / _stop 1507). 3세션 신규 자산 5개 정상 존재 확인. 순환 import 위험 없음 (daily_time_scheduler.py가 engine_ws_dispatch.py를 import하지 않음).
  - **영향범위**: 백엔드 3개 파일만 변경. 프론트엔드 변경 없음. 테스트 파일은 5세션에서 갱신.
  - **UI 기준 변경 내용 (규칙 0-4)**: 화면 변화 없음. 백엔드 스케줄러 내부 구조 변경만. 사용자 체감 점: 장 상태 전환 시점이 약간 더 정확해짐 (10초 간격 체크 → 시각 도달 시 즉시 실행).
  - **검증**: py_compile + ruff 통과 + 런타임 기동(`-W error::RuntimeWarning`) RuntimeWarning 0건 + 에러 없음 + `[기동] 타임테이블 스케줄러 시작 — 다음 이벤트 예약 완료` 로그 출력 + 기존 `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 미출력 (10초 루프 제거 확인) + 잔존 프로세스 0건. test_daily_time_scheduler.py import error (예상됨 — 5세션에서 갱신, 태스크 파일 4-2 명시). test_trading.py 단독 실행 시 31개 전체 통과 (전체 실행 시 1개 실패는 테스트 순서 의존성, 내 수정과 무관).
- **5세션 (완료)**: Step 9+10 구현 — 단위 테스트 11개 케이스 + 기존 테스트 갱신/제거 + 런타임 기동 검증.
  - **변경 파일**: `test_daily_time_scheduler.py` (유일) — import 문 갱신(제거 5개 → 신규 6개) + TestCheckPrestartTriggers 제거(-117줄) + TestMarketPhasePeriodicLoop 제거(-137줄) + TestStopDailyTimeScheduler/TestStartDailyTimeScheduler 갱신 + TestTimetableScheduler 신규 11개 케이스 추가.
  - **사전조사 결과 (규칙 0-2 4항목)**: 4세션 완료 상태 재확인 — 신규 자산 5개 정상 존재 + 제거 4함수 잔존 0건 + engine_state.py 필드 2개 + start/stop 배선 확인. 영향범위: 테스트 파일 1개만. 원칙 부합: P16/P20/P22/P23/P24.
  - **영향범위**: 테스트 파일 1개만 변경. 백엔드/프론트엔드 코드 변경 없음.
  - **UI 기준 변경 내용 (규칙 0-4)**: 화면 변화 없음. 테스트 코드 정리만.
  - **검증**: py_compile + ruff 통과 + pytest 211개 전체 통과(기존 200 + 신규 11, 제거 17) + test_buy_order_executor 33개 + test_trading 31개 통과(회귀 없음) + 런타임 기동(`-W error::RuntimeWarning`) RuntimeWarning 0건 + 에러 없음 + `[기동] 타임테이블 스케줄러 시작 — 다음 이벤트 예약 완료` 로그 출력 + 기존 `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 미출력 + 잔존 프로세스 0건.
  - **테스트 케이스 11개 (TestTimetableScheduler)**: (1) test_jif_stale_warn_sec_is_120 — 임계값 120초 검증 / (2) test_schedule_next_event_at_0755_reserves_0758 — 07:55→07:58 delay=180s / (3) test_schedule_next_event_at_0930_reserves_1520 — 09:30→15:20 delay=21000s / (4) test_schedule_next_event_at_2030_reserves_next_day_0758 — 20:30→익일 07:58 delay=41280s / (5) test_direct_event_fires_action_and_reschedules — direct 항목 action 호출 + finally 재예약 / (6) test_phase_event_fires_broadcast_and_reschedules — phase 항목 _broadcast_market_phase 호출 + finally 재예약 / (7) test_direct_event_idempotency_guard_no_op — last_realtime_reset_date 가드로 no-op / (8) test_check_jif_health_recent_no_warning — 10초 전 warning 미출력 / (9) test_check_jif_health_none_logs_debug — None debug 출력 / (10) test_check_jif_health_stale_logs_warning — 150초 경과 warning 출력 / (11) test_startup_scan_at_075830_reserves_0759 — 07:58:30→07:59 delay=30s / (12) test_stop_cancels_timetable_timer — stop 시 cancel + None.

---

## 이전 다단계 작업: 시장가 주문 중단 시간대 게이트 (다단계 작업) — 완료

### 단계 진행 상황
- **1세션 (완료)**: 설계서 작성 — 사전조사 + 사용자 결정 5항목 확정 + 설계서 작성.
  - **설계서**: `docs/architecture_order_time_guard_design.md` (277줄)
  - **전신 문서**: `docs/plan_order_suspension_by_time.md` (사전조사 + 사용자 결정 완료 → 본 설계서로 통합, 2세션에서 삭제)
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성.
  - **태스크 파일**: `docs/plan_order_time_guard.md` (300줄)
- **3세션 (완료)**: Step 1 (차단 판별 함수 + ±5초 버퍼) + Step 4 (설정 키).
  - **변경 파일**: `daily_time_scheduler.py` (신규 함수 `is_order_blocked_by_time()` + `ORDER_TIME_BUFFER_SEC`/`_ORDER_TIME_BOUNDARIES_SEC` 상수) + `settings_defaults.py` (`order_time_guard_on: True`) + `test_daily_time_scheduler.py` (`TestIsOrderBlockedByTime` 20개 테스트)
  - **검증**: 단위 테스트 203개 통과 + test_buy_order_executor 33개 통과 + 런타임 기동 정상 (RuntimeWarning 0건)
- **4세션 (완료)**: Step 2 (execute_buy 게이트) + Step 3 (execute_sell 게이트) + Step 5 (헬퍼).
  - **변경 파일**: `trading.py` (신규 헬퍼 `_is_order_time_blocked(stk_cd, raw_settings)` + execute_buy 게이트 배선 L135-139 + execute_sell 게이트 배선 L468-471)
  - **사전조사 결과 (규칙 0-2 4항목)**:
    1. **의존성**: `is_order_blocked_by_time(stk_cd)`(daily_time_scheduler.py:331, 3세션 구현) + `order_time_guard_on`(settings_defaults.py:117, 3세션) + `raw_all`(trading.py:113) + `base_settings`(trading.py:457 인자) + `data_manager`(trading.py:11 import) + `logger`(trading.py:21). `_to_trade_settings`(L716)에 `order_time_guard_on` 키 없음 확인 → raw settings 전달(2-1 해결안).
    2. **영향범위**: 백엔드 1개 파일(trading.py) — 헬퍼 1개 + 게이트 2곳. 프론트엔드/테스트 변경 없음.
    3. **아키텍처 원칙 부합**: P15(단일 주문 경로 — execute_buy/sell 내부) + P16(살아있는 경로 — 주문 전송 전 호출) + P17(raw settings에서 토글 조회) + P20(빈 문자열 시 에러 로그) + P23(기존 게이트 패턴 동일) + P24(헬퍼 5줄) 전부 재확인 완료.
    4. **기존 공통 자산 확인**: `is_order_blocked_by_time()`(3세션 구현) 재사용. 새 자산 생성 없음.
  - **2-1 해결안 반영 (핵심)**: 헬퍼 `_is_order_time_blocked(stk_cd, raw_settings)`에 raw engine_settings 전달 — execute_buy는 `raw_all`(L113), execute_sell은 `base_settings`(L457 인자). `_to_trade_settings` 출력이 아님(`order_time_guard_on` 키 누락 → 토글 OFF 무효화 방지, P17).
  - **UI 기준 변경 내용 (규칙 0-4)**: 동시호가/장외 시간대에 자동매수 발생 시 주문 전송 중단(KRX 단독 종목만, NXT 종목은 NXT 거래 시간 허용). 동시호가 20분간 자동매도도 중단(종목 구분 없이 양쪽 차단). 토글 OFF 시 차단 없음(6세션에서 UI 토글 추가 예정). 이번 세션은 백엔드 only — 화면 변화 없음.
  - **검증**: py_compile + ruff 통과 + 단위 테스트 236개 통과(test_daily_time_scheduler 203 + test_buy_order_executor 33, 회귀 없음) + 런타임 기동(`-W error::RuntimeWarning`) 102ms 정상 기동 + RuntimeWarning 0건 + 잔존 프로세스 0건.
- **5세션 (완료)**: Step 7 (WS 이벤트 `order_time_blocked` 브로드캐스트) + Step 8 (바인딩 `binding.ts` + `uiStore.ts`).
  - **변경 파일**: `daily_time_scheduler.py` (신규 함수 `get_order_time_block_status() -> tuple[bool, str]` + `_apply_market_phase()` 내 브로드캐스트 배선) + `test_daily_time_scheduler.py` (`TestGetOrderTimeBlockStatus` 13개 테스트 + 기존 3개 테스트 기대값 1→2 갱신) + `uiStore.ts` (`orderTimeBlocked` 상태 + `applyOrderTimeBlocked`/`clearOrderTimeBlocked` 함수) + `binding.ts` (`order_time_blocked` 이벤트 바인딩)
  - **사전조사 결과 (규칙 0-2 4항목)**:
    1. **의존성**: `_apply_market_phase()`(daily_time_scheduler.py:673, SSOT 단일 경로) + `_broadcast()`(engine_account_notify.py:69) + `KRX_INACTIVE_PHASES`(L227) + `NXT_ACTIVE_PHASES`(L233) + `_ORDER_TIME_BOUNDARIES_SEC`(L322) + `ORDER_TIME_BUFFER_SEC` + `state.market_phase` + `_kst_now()` + `schedule_engine_task()`. 프론트엔드: `circuitBreakerOpen` 패턴(uiStore.ts:69/90/135/140/145/232) + `onEvent` 패턴(binding.ts:322-327). 기존 `is_order_blocked_by_time(stk_cd)`(L331, 3세션)은 변경하지 않음 — 20개 테스트 보호.
    2. **영향범위**: 백엔드 2개 파일(daily_time_scheduler.py, test_daily_time_scheduler.py) + 프론트엔드 2개 파일(uiStore.ts, binding.ts). 기존 코드 변경 최소화 — 신규 추가 + 기존 테스트 3개 기대값 갱신만.
    3. **아키텍처 원칙 부합**: P10(SSOT — `_apply_market_phase` 단일 경로에 탑승) + P15/P16(살아있는 경로 — JIF + 10초 주기 양쪽) + P20(빈 문자열 시 `blocked=False` + 에러 로그) + P21(헤더 칩 표시용 상태 전송) + P23(`circuit_breaker_open` 패턴 동일) + P24(신규 함수 ~20줄, 브로드캐스트 1줄) 전부 재확인 완료.
    4. **기존 공통 자산 확인**: `_broadcast()`·`schedule_engine_task()`·`KRX_INACTIVE_PHASES`·`NXT_ACTIVE_PHASES`·`_ORDER_TIME_BOUNDARIES_SEC`·`ORDER_TIME_BUFFER_SEC`·`circuitBreakerOpen` 패턴 전부 재사용. 새 자산 생성 없음.
  - **핵심 설계 결정**: `get_order_time_block_status()`를 페이즈 기반(종목 구분 없음) 신규 함수로 추가 — `is_order_blocked_by_time(stk_cd)`는 종목별 분기가 필요하므로 기존 로직 유지(규칙 0-3/0-5: 기존 승인된 로직 변경 최소화). 두 함수는 서로 다른 추상화 수준(페이즈 수준 vs 종목별)이므로 P10 위반 아님.
  - **브로드캐스트 탑승 위치**: `_apply_market_phase()` 내 `market-phase` 브로드캐스트 직후 — JIF 경로 + 10초 주기 양쪽에서 자동 전송(P10 SSOT 단일 경로). `blocked=False` 시 자동 해제(P24 — 별도 해제 로직 없음).
  - **테스트 실패 추적 (규칙 4-1)**: `_apply_market_phase`에 브로드캐스트 1줄 추가로 기존 3개 테스트(`test_broadcasts_phase`/`test_no_recompute_trigger_when_phase_unchanged`/`test_apply_market_phase_no_change_no_side_effects`)가 `schedule_engine_task.call_count == 1` 기대값 실패(2 == 1). 내 수정과 직접 연관 — 기대값 1→2 갱신 + 컨텍스트 검증 추가("market-phase" + "order_time_blocked" 포함 확인).
  - **UI 기준 변경 내용 (규칙 0-4)**: 이번 세션은 화면 변화 없음 — 백엔드가 "주문 일시중단 상태"를 10초마다 화면에 전송하고 프론트엔드가 저장만 하는 단계. 화면에 칩이 표시되는 것은 6세션(헤더 칩 구현)에서.
  - **검증**: py_compile + ruff 통과 + typecheck + build 1.77s 통과 + 단위 테스트 249개 통과(test_daily_time_scheduler 216 + test_buy_order_executor 33, 회귀 없음) + 런타임 기동(`-W error::RuntimeWarning`) 175ms 정상 기동 + RuntimeWarning 0건 + 잔존 프로세스 0건.
- **6세션 (완료)**: Step 6 (설정 토글 `general-settings.ts`) + Step 9 (헤더 칩 `header.ts`) + `types/index.ts` 설정 키 추가.
  - **변경 파일**: `types/index.ts` (`order_time_guard_on: boolean` AppSettings 키 추가, L213) + `general-settings.ts` (자동매도 행 아래 "체결 불가 시간대 주문 차단" 토글 행 추가 — `createToggleBtn()` 재사용, `orderTimeGuardToggle` 모듈 변수, `syncFromSettings`에서 `r.order_time_guard_on !== false` 동기화, 설명 문구 "동시호가·장외 시간대에 시장가 주문 자동 중단 (KRX 단독 종목만, NXT 종목은 NXT 거래 시간에 허용)") + `header.ts` (`orderTimeBlockedChip` 신규 칩 — `circuitBreakerChip` 패턴 동일, `clearOrderTimeBlocked()` 클릭 해제, `COLOR.warning`/`warningBg` 노란색, `onStateChange`에서 `orderTimeBlocked` 분해 + 표시 로직 `⏸ 주문 일시중단(${reason})`).
  - **사전조사 결과 (규칙 0-2 4항목)**:
    1. **의존성**: `createToggleBtn()`(setting-row.ts)·`uiFlashToggle`/`autoSellToggle` 패턴(general-settings.ts:55/52/221-262/602-613/807)·`createChipEl()`(header.ts:51)·`circuitBreakerChip` 패턴(header.ts:212-216/253-262)·`COLOR.warning`/`warningBg`(ui-styles.ts:53/72)·`clearOrderTimeBlocked()`(uiStore.ts:162, 5세션 구현)·`AppSettings` 타입(types/index.ts:211). 백엔드 변경 없음.
    2. **영향범위**: 프론트엔드 3개 파일(types/index.ts, general-settings.ts, header.ts). 백엔드/테스트 변경 없음.
    3. **아키텍처 원칙 부합**: P21(사용자 투명성 — 헤더 칩으로 차단 상태 표시 + 설정 토글로 사용자 제어) + P23(용어 통일 — "체결 불가 시간대 주문 차단"/"주문 일시중단(동시호가)") + P23(공통 자산 재사용 — `createToggleBtn()`/`createChipEl()`/`COLOR.warning`/`circuitBreakerChip` 패턴) + P23(UI 패턴 일관성 — 토글 행 = 기존 자동매도/uiFlash 패턴, 칩 = circuitBreakerChip 패턴) + P24(단순성 — 토글 행 ~15줄, 칩 표시 로직 ~10줄) 전부 재확인 완료.
    4. **기존 공통 자산 확인**: `createToggleBtn()`·`createChipEl()`·`COLOR.warning`/`warningBg`·`circuitBreakerChip` 패턴·`uiFlashToggle` 패턴·`clearOrderTimeBlocked()`(5세션 구현) 전부 재사용. 새 자산 생성 없음.
  - **역할 분리 설계**: 헤더 칩은 "현재 시간대 상태" 알림용(토글 OFF여도 표시), 설정 토글은 "차단 적용 여부" 제어용 — 두 역할 분리하여 사용자가 상태 인지 + 제어 독립 가능 (P21 사용자 투명성 + P24 단순성).
  - **UI 기준 변경 내용 (규칙 0-4)**: (1) 일반설정 → 자동매매 탭에 자동매도 행 아래 "체결 불가 시간대 주문 차단" 토글 새로 표시 — ON(기본) 시 동시호가/장외 시장가 주문 자동 중단, OFF 시 차단 없음. (2) 화면 상단 헤더에 동시호가/장외 진입 시 노란색 "주문 일시중단(동시호가)" 칩 표시 — 시간대 종료 시 자동 사라짐, 클릭 시 수동 숨김.
  - **검증**: typecheck 통과 + build 1.01s 통과 + 에러 0건.
  - **사전조사 결과 (규칙 0-2 4항목)**:
    1. **의존성**: `KRX_INACTIVE_PHASES`(daily_time_scheduler.py:227)·`NXT_ACTIVE_PHASES`(L233)·`is_nxt_enabled()`(engine_symbol_utils.py:11)·`_broadcast()`(engine_account_notify.py:69)·`createToggleBtn()`·`circuitBreakerOpen` 패턴 전부 재사용 확정. 외부 참조 없음.
    2. **영향범위**: 백엔드 4개 파일(daily_time_scheduler.py, settings_defaults.py, trading.py, engine_ws_dispatch.py) + 프론트엔드 4개 파일(general-settings.ts, header.ts, binding.ts, uiStore.ts) + 테스트 1개 파일(test_daily_time_scheduler.py). 기존 test_buy_order_executor.py는 변경 없음(기존 is_krx_after_hours 유지).
    3. **아키텍처 원칙 부합**: P10/P13/P15/P16/P17/P20/P21/P22/P23/P24 전부 재확인 완료.
    4. **기존 공통 자산 확인**: 위 1항과 동일 — 모두 재사용, 신규 자산 생성 없음.
  - **설계서 대비 핵심 발견사항 5건 (구현 세션 전 반드시 반영)**:
    1. **★ `_to_trade_settings` 설정 키 누락 (중요 — P17 위반 위험)**: `trading.py:694` `_to_trade_settings()` 반환 dict에 `order_time_guard_on` 키 없음. 설계서 의사코드대로 `settings.get("order_time_guard_on", True)` 쓰면 항상 True → 토글 OFF 무효화. **해결안**: 헬퍼 `_is_order_time_blocked(stk_cd, raw_settings)`에 raw engine_settings 전달 — execute_buy는 `raw_all`(L113), execute_sell은 `base_settings`(L457 인자). 4세션 구현 시 필수 반영.
    2. **±5초 버퍼 구현 방식 확정**: `calc_timebased_market_phase()` 분 단위 산정 → 버퍼는 `is_order_blocked_by_time()` 내부에서 초 단위 별도 계산. 차단 전환 경계(08:00, 09:00, 15:20, 15:40, 20:00) ±5초 내 무조건 차단(양방향 안전 측, P24 단순화). NXT 09:00:30은 calc_timebased_market_phase가 이미 초 단위 처리 → 버퍼 경계 집합에서 제외 검토(3세션 확정). 상수 `ORDER_TIME_BUFFER_SEC = 5`.
    3. **WS 이벤트 브로드캐스트 시점 확정**: `_broadcast_market_phase()`(10초 주기)에 탑승하여 별도 이벤트 `order_time_blocked` 브로드캐스트. 페이로드 `{"blocked": bool, "reason": str}`. 시간 기반이므로 별도 해제 로직 없음(P24).
    4. **execute_sell 삽입 위치 확인**: L461 `is_sell_auto` 체크 직후, L464 `order_type` 선언 전. `trade_settings`는 `_to_trade_settings` 출력 → `order_time_guard_on` 없음 → `base_settings` 사용(1번 해결안).
    5. **기존 `plan_order_suspension_by_time.md` 잔존 (규칙 11)**: 설계서에 "통합됨" 기록되었으나 파일 잔존 → 2세션에서 삭제 완료.
  - **세션 분할 확정 (3~6세션)**: 설계서 섹션 6과 동일. 3세션(Step 1+4) → 4세션(Step 2+3+5) → 5세션(Step 7+8) → 6세션(Step 6+9).
  - **코드 수정 없음**: 사전조사 + 태스크 파일 작성 only.
  - **사용자 확정 사항**:
    1. 08:00~08:50: KRX만 차단 / NXT 허용 (KRX 시장가 불가, NXT 프리마켓 체결 가능)
    2. 08:50~09:00: 양쪽 차단 (시가 동시호가, 양쪽 체결 없음)
    3. 09:00~15:20: 양쪽 허용 (정규장/메인마켓)
    4. 15:20~15:40: 양쪽 차단 (종가 동시호가·체결 정산, 양쪽 체결 없음/일괄)
    5. 15:40~20:00: KRX만 차단 / NXT 허용 (KRX 시장가 불가, NXT 애프터마켓 체결 가능)
    6. ±5초 버퍼: execute_buy/execute_sell 내부(주문 체크 시점)에만 적용, phase 산정은 건드리지 않음
    7. UI: 일반설정 > 자동매매 탭에 토글 추가 (기본 ON)
    8. 매수/매도 동일 적용
    9. KRX_INACTIVE_PHASES·NXT_ACTIVE_PHASES 재사용 (새 시간 상수 생성 없음)
    10. force_buy dead parameter: 본 작업에서 제거하지 않음 (별도 이슈로 기록)
  - **차단 판별 로직**: 신규 함수 `is_order_blocked_by_time(stk_cd)` — 기존 `is_nxt_only_window()` 패턴과 동일 구조. KRX 비활성 + NXT 활성 시 `is_nxt_enabled(stk_cd)`로 종목별 분기 (KRX 단독 종목만 차단, NXT 종목은 허용).
  - **백엔드 설계 (Step 1~5)**:
    - Step 1: `daily_time_scheduler.py` — `is_order_blocked_by_time()` 신규 함수 + ±5초 버퍼 (기존 `is_krx_after_hours()`는 유지, 영향 범위 최소화)
    - Step 2: `trading.py` `execute_buy()` 내부 — 자동매매 게이트 직후에 시간 게이트 배선 (P15 단일 경로, P16 살아있는 경로)
    - Step 3: `trading.py` `execute_sell()` 내부 — `is_sell_auto` 체크 직후에 시간 게이트 배선 (매도 동일 적용)
    - Step 4: `settings_defaults.py` — `order_time_guard_on: True` 설정 키 추가 (P13/P17)
    - Step 5: `engine_ws_dispatch.py` — `order_time_blocked` WS 이벤트 (기존 `circuit_breaker_open` 패턴 재사용, P23)
  - **프론트엔드 설계 (Step 6~8)**:
    - Step 6: `general-settings.ts` 자동매매 탭 — "체결 불가 시간대 주문 차단" 토글 (`createToggleBtn` 재사용, 기본 ON)
    - Step 7: `header.ts` — 노란색 "주문 일시중단(동시호가)" 칩 (서킷브레이커 칩 패턴 재사용, 시간대 종료 시 자동 해제)
    - Step 8: `binding.ts` + `uiStore.ts` — `order_time_blocked` 이벤트 바인딩 + `orderTimeBlocked` 상태 (기존 `circuitBreakerOpen` 패턴 재사용)
  - **세션 분할 (세션당 1단계 — 규칙 0-1)**:
    | 세션 | 단계 | 파일 | 검증 |
    |---|---|---|---|
    | 2세션 | 심층 사전조사 + 태스크 파일 작성 | (사전조사 후 확정) | — |
    | 3세션 | Step 1 (차단 판별 함수 + ±5초 버퍼) + Step 4 (설정 키) | daily_time_scheduler.py + settings_defaults.py | 단위 테스트 |
    | 4세션 | Step 2 (execute_buy 게이트) + Step 3 (execute_sell 게이트) + Step 5 (헬퍼) | trading.py | 런타임 기동 + 차단 로그 |
    | 5세션 | Step 7 (WS 이벤트) + Step 8 (바인딩) | engine_ws_dispatch.py + binding.ts + uiStore.ts | WS 이벤트 수신 |
    | 6세션 | Step 6 (설정 토글) + Step 9 (헤더 칩) | general-settings.ts + header.ts | 브라우저 확인 |
  - **별도 이슈 (force_buy dead parameter)**: `execute_buy(force_buy: bool = False)` 파라미터 존재하나 `force_buy=True` 호출부가 백엔드·프론트엔드·테스트 전체에 0건. P16(살아있는 경로)/P23(일관성 — docstring 불일치) 위반 소지. 본 작업에서 제거 안 함 → "미해결 문제" 섹션에 별도 기록 필요.
  - **코드 수정 없음**: 설계서 작성 only. 2세션 태스크 파일 작성은 사용자 "진행" 지시 시 시작.

### 참조 문서
- **설계서**: `docs/architecture_order_time_guard_design.md` (1세션)
- **태스크 파일**: `docs/plan_order_time_guard.md` (2세션 — 심층 사전조사 + 세션별 태스크 상세)
- **전신 문서**: `docs/plan_order_suspension_by_time.md` (2세션에서 삭제 — 설계서에 통합됨, 규칙 11)

### 승인 대기 항목
- **5세션 진행 (완료)**: Step 7 (`order_time_blocked` WS 이벤트 브로드캐스트 — `_apply_market_phase()` SSOT 단일 경로에 탑승, 페이로드 `{"blocked": bool, "reason": str}`, 기존 `circuit_breaker_open` 패턴 재사용) + Step 8 (`binding.ts` 이벤트 바인딩 + `uiStore.ts` `orderTimeBlocked` 상태 추가, 기존 `circuitBreakerOpen` 패턴 재사용) — `daily_time_scheduler.py` + `test_daily_time_scheduler.py` + `binding.ts` + `uiStore.ts` — 완료.
- **6세션 진행**: Step 6 (`general-settings.ts` 자동매매 탭에 "체결 불가 시간대 주문 차단" 토글 추가, `createToggleBtn()` 재사용, 설정 키 `order_time_guard_on`, 기본 ON) + Step 9 (`header.ts` 노란색 "주문 일시중단(동시호가)" 칩 추가, 기존 `circuitBreakerChip` 패턴 재사용, `COLOR.warning`/`COLOR.warningBg` 사용) — `general-settings.ts` + `header.ts` — 사용자 "진행" 지시 시 시작.

---

## 이전 다단계 작업: NXT 전용 시간대 KRX 종목 숨김 처리 (전체 완료)

### 단계 진행 상황
- **1세션 (완료)**: 설계 검토 + 디자인 파일 작성 — ARCHITECTURE.md 24개 원칙 검토 + 기존 공통 자산 조사(badge.ts, fade-in 패턴, filterBadge 패턴) + 사용자 결정 5항목 확정 + 시간 표기 구독 시점 기준 통일.
  - **설계서**: `docs/architecture_krx_hide_in_nxt_only_design.md` (565줄)
  - **사용자 확정 사항**:
    1. 빈 업종 그룹 행 → 그룹 행도 숨김
    2. 안내 배지 → 추가 (기존 filterBadge 패턴 재사용)
    3. 전환 애니메이션 → 배지 fade-in만 (150ms)
    4. "정규장 여부" 판단 방식 → **안 B: 프론트엔드 phase 문자열 매칭** (백엔드 변경 없음)
    5. "그 외 시간대" 안내 텍스트 → 추가 없음 (섹션 자체만 숨김)
  - **시간대 정의 (구독 신청/해지 시점 기준)**:
    | 시간대 | 구간 | KRX 종목 | NXT 종목 | 수신률 KRX 바 | 수신률 NXT 바 |
    |---|---|---|---|---|---|
    | NXT 전용 (오전) | 07:59 ~ 08:59 | 숨김 | 표시 | 숨김 | 표시 |
    | 정규장 | 08:59 ~ 15:20 | 표시 | 표시 | 표시 | 표시 |
    | NXT 전용 (오후) | 15:20 ~ 20:00 | 숨김 | 표시 | 숨김 | 표시 |
    | 그 외 | 20:00 ~ 07:59 | 숨김 | 숨김 | 숨김 | 숨김 |
  - **영향 범위 (안 B 확정 — 프론트엔드 only, 3개 파일)**:
    - `frontend/src/pages/sector-stock.ts` (중) — computeRows KRX 필터 + 빈 그룹 행 숨김 + krxInactive 제거 + 안내 배지 추가 + rowStyle 분기 제거
    - `frontend/src/pages/sector-settings.ts` (소) — _applyMarketPhaseActive 3상태 분기 + opacity→display 토글
    - `frontend/src/components/common/ui-styles.ts` (소) — inactiveRowBg 상수 제거
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성 — sector-stock.ts krxInactive 심볼 6곳 + inactiveRowBg 단일 사용처 + _applyMarketPhaseActive 호출부 2곳 + header.ts PHASE_STYLE 19개 phase 분석 → REGULAR_PHASES 4개 확정. 작업량 계산 → 단계 분할(3세션 + 4세션) + 태스크 파일 `docs/plan_krx_hide_in_nxt_only.md` (567줄) 작성.
  - **사전조사 결과 (규칙 0-2 4항목)**:
    1. **의존성**: krxInactive는 sector-stock.ts 내 6곳만 참조(외부 파일 참조 없음, 단일 파일 내 완결). inactiveRowBg는 sector-stock.ts:512 단일 사용처. _applyMarketPhaseActive 호출부 2곳(L231, L399) 모두 이미 marketPhase 전체 객체 전달 중 → 시그니처 확장해도 호출부 수정 불필요. krxRowEl/nxtRowEl은 모듈 변수로 mount에서 생성, unmount에서 null → display 토글로 전환해도 참조 유효.
    2. **영향범위**: 프론트엔드 3개 파일 (sector-stock.ts 중, sector-settings.ts 소, ui-styles.ts 소) — 백엔드 변경 없음(안 B 확정).
    3. **아키텍처 원칙 부합**: P10/P16/P20/P21/P22/P23/P24 전부 재확인 완료. 안 B P10/P23 부분 위험은 REGULAR_PHASES 동기화 주석으로 완화.
    4. **기존 공통 자산 확인**: filterBadge 패턴, COLOR.warningBg/warning, transition 속성, requestAnimationFrame 패턴 재사용 확정. badge.ts/toast.ts는 구조 부적합으로 기각.
  - **REGULAR_PHASES 확정** (header.ts PHASE_STYLE 분석 기반): `new Set(['정규장', '시가 동시호가', '종가 동시호가', '메인마켓'])` — 시간외/NXT 전용 phase 6개는 is_nxt_only 플래그로 우선 분리되므로 제외. 판정 순서: is_nxt_only 우선 → false일 때만 REGULAR_PHASES 참조.
  - **단계 분할 (세션당 1단계 — 규칙 0-1)**:
    | 세션 | 단계 | 파일 | 검증 |
    |---|---|---|---|
    | 3세션 | 종목 숨김 + 안내 배지 + 색상 상수 제거 | sector-stock.ts (4-1,4-2,4-3,4-4) + ui-styles.ts (4-5) | type-check + build + 브라우저 |
    | 4세션 | 수신률 섹션 3상태 숨김 | sector-settings.ts (4-7) | type-check + build + 브라우저 |
  - **sector-stock.ts 한 세션 전체 수정 이유**: krxInactive 필드 제거 시 computeRows/rowStyle/DataRowItem 인터페이스/updateUI가 모두 연관 → 부분 제거 시 타입 오류 또는 dead code 발생 위험.
- **3세션 (완료)**: 구현 Step 1 — sector-stock.ts (DataRowItem krxInactive 필드 제거 + computeRows KRX 단독 종목 continue 숨김 + 빈 업종 그룹 행 숨김 + stockSeq++ 위치 이동 순번 재정렬 + 안내 배지 DOM/갱신 + rowStyle 분기 제거 + disconnectedCallback 정리) + ui-styles.ts (inactiveRowBg 상수 제거). 검증: typecheck 통과 + build 성공(2.07s, 63 모듈) + 테스트 108/108 통과 + 브라우저 검증(개발 서버 5174).
  - **sector-stock.ts 수정 상세**:
    - `DataRowItem` 인터페이스: `krxInactive: boolean` 필드 제거.
    - `computeRows`: 그룹 행 push 이전에 `krxInactive && codes`일 때 활성 종목(NXT 지원) 0개면 `continue`로 그룹 행 숨김. 종목 루프에서 `if (krxInactive && !stock.nxt_enable) continue`로 KRX 단독 종목 행 숨김. `stockSeq++`를 두 continue 이후로 이동 → 활성 종목만 1, 2, 3... 자동 재정렬. `stockKrxInactive` 변수 제거. `rowOpacity`에서 `stockKrxInactive` 분기 제거. 캐시 체크 조건에서 `krxInactive` 항 제거. row 생성에서 `krxInactive` 필드 제거.
    - `nxtOnlyNoticeBadge` 필드 추가 + connectedCallback에서 filterBadge 이후 DOM 생성(filterBadge 패턴 재사용, COLOR.warningBg/warning, fade-in transition 150ms).
    - `updateUI`: filterBadge 갱신 이후 안내 배지 갱신 로직 추가 — `is_nxt_only === true`일 때 `hiddenCount` 계산 + 텍스트 `NXT 전용 시간대 — KRX 단독 종목 숨김 (N종목)` + fade-in(opacity 0→1 다음 프레임). 정규장/그 외 시 `display: none`.
    - `rowStyle`: `row.krxInactive ? COLOR.inactiveRowBg` 분기 제거.
    - `disconnectedCallback`: `this.nxtOnlyNoticeBadge = null` 추가.
  - **ui-styles.ts 수정 상세**: `inactiveRowBg: '#c8c8c8'` 상수 1줄 제거 (단일 사용처라 안전). `inactiveBg: '#e0e0e0'`는 별도 용도 유지.
  - **검증 결과**: typecheck 통과(타입 오류 없음) + build 성공(63 모듈 변환, 2.07s) + 테스트 108/108 통과(7개 테스트 파일) + 개발 서버 5174 기동 정상.
- **4세션 (대기)**: 구현 Step 2 — sector-settings.ts (REGULAR_PHASES 상수 추가 + _applyMarketPhaseActive 시그니처 확장 + 3상태 분기 + opacity→display 토글). 검증: type-check + build + 브라우저.

### 참조 문서
- (다단계 작업 전체 완료 — 설계서/태스크 파일은 규칙 11에 따라 삭제 예정)

### 승인 대기 항목
- (없음 — 다단계 작업 전체 완료)

## 직전 완료 작업
- **시장가 주문 중단 시간대 게이트 4세션 (다단계)**: trading.py 구현 Step 2+3+5 완료.
  - **trading.py 수정**: (1) `_is_order_time_blocked(stk_cd, raw_settings)` 헬퍼 메서드 추가 — 토글(`order_time_guard_on`) 조회 후 `is_order_blocked_by_time(stk_cd)` 호출, raw engine_settings 전달(2-1 해결안, P17). (2) `execute_buy()` 내부 자동매매 게이트(L134) 직후·재매수 차단 전에 시간 게이트 배선 — `raw_all` 전달, 차단 시 `return False`(P15/P16). (3) `execute_sell()` 내부 `is_sell_auto` 체크 직후·`order_type` 선언 전에 시간 게이트 배선 — `base_settings` 전달, 차단 시 `return`(매도 동일 적용).
  - **UI 기준 변경 내용** (규칙 0-4): 동시호가/장외 시간대에 자동매수 발생 시 주문 전송 중단(KRX 단독 종목만, NXT 종목은 NXT 거래 시간 허용). 동시호가 20분간 자동매도도 중단(종목 구분 없이 양쪽 차단). 토글 OFF 시 차단 없음(6세션에서 UI 토글 추가 예정). 이번 세션은 백엔드 only — 화면 변화 없음.
  - **2-1 해결안 반영 (핵심)**: 헬퍼에 raw engine_settings 전달(`raw_all`/`base_settings`) — `_to_trade_settings` 출력이 아님(`order_time_guard_on` 키 누락 → 토글 OFF 무효화 방지, P17).
  - **검증 결과**: py_compile + ruff 통과 + 단위 테스트 236개 통과(test_daily_time_scheduler 203 + test_buy_order_executor 33, 회귀 없음) + 런타임 기동(`-W error::RuntimeWarning`) 102ms 정상 기동 + RuntimeWarning 0건 + 잔존 프로세스 0건.
  - **원칙 15/16/18 준수 여부 (safe-trade 스킬)**: P15(단일 주문 경로 — execute_buy/execute_sell 내부에만 게이트 배선, 분기/우회 경로 없음) ✅ + P16(살아있는 경로 — 주문 전송 전 호출, dead code 아님) ✅ + P18(테스트모드 동등성 — 테스트모드/실전모드 동일하게 게이트 동작, 모드 분기 없음) ✅.
  - **커밋**: `feat: 시장가 주문 중단 시간대 게이트 4세션 — execute_buy/execute_sell 게이트 + 헬퍼 (Step 2+3+5)`.
  - **작업 여력**: 충분.
- **NXT 전용 시간대 KRX 수신률 섹션 3상태 숨김 (다단계 4세션)**: sector-settings.ts 구현 Step 2 완료.
  - **sector-settings.ts 수정**: REGULAR_PHASES 상수 추가(new Set(['정규장', '시가 동시호가', '종가 동시호가', '메인마켓']), header.ts PHASE_STYLE 동기화 주석 포함 — P10/P23) + _applyMarketPhaseActive 시그니처 확장({ is_nxt_only?, krx, nxt }) + 3상태 분기(NXT 전용/정규장/그 외) + opacity 0.3/1.0 토글 → display none/flex 토글 전환. 호출부 2곳(L231, L399)은 이미 marketPhase 전체 객체 전달 중이라 수정 불필요.
  - **UI 기준 변경 내용** (규칙 0-4):
    - NXT 전용 시간대(07:59~08:59, 15:20~20:00): 업종순위 설정 화면에서 KRX 수신률 바(배지 + 진행 바)가 흐릿하게 회색 표시되던 것 → 완전히 숨김. NXT 수신률 바만 표시. 임계치 입력란·상태 라벨은 유지.
    - 정규장(08:59~15:20): KRX/NXT 수신률 바 둘 다 정상 표시 (기존과 동일).
    - 그 외 시간대(20:00~07:59): KRX/NXT 수신률 바 둘 다 완전 숨김 (기존에는 둘 다 흐릿 표시).
  - **검증 결과**: typecheck 통과 + build 성공(637ms) + 테스트 108/108 통과 + 개발 서버 5174 기동 정상.
  - **커밋**: `feat: NXT 전용 시간대 KRX 수신률 섹션 3상태 숨김 (4세션)`.
  - **작업 여력**: 충분.
- **시장가 주문 중단 시간대 게이트 설계서 작성 (다단계 1세션)**: 사전조사 + 사용자 결정 5항목 확정 + 설계서 작성. 코드 수정 없음.
  - **설계서**: `docs/architecture_order_time_guard_design.md` (277줄) — 전신 `docs/plan_order_suspension_by_time.md` (사전조사 + 사용자 결정 완료 → 본 설계서로 통합)
  - **사전조사 결과**:
    - 매수 경로: `execute_buy()` 내부에 시간 체크 없음 — 외부 `buy_order_executor.py:110`만 `is_krx_after_hours()` 호출 (사전 필터). `force_buy=True` 경로는 존재하지 않음 (dead parameter, 별도 이슈).
    - 매도 경로: `execute_sell()`에 시간 체크 전혀 없음 — 동시호가 시간대 매도 주문 가능 (시장가이므로 체결 불가).
    - 기존 `is_krx_after_hours()` (daily_time_scheduler.py:298-312): 차단 O = 체결 정산·장후 시간외·시간외 단일가·장 종료. 차단 X(누락) = 시가 동시호가(08:50~09:00)·종가 동시호가(15:20~15:30)·동시호가 접수(08:40~08:50).
    - `KRX_INACTIVE_PHASES` frozenset (daily_time_scheduler.py:227-231): 이미 "시가 동시호가", "종가 동시호가" 포함 — 이 집합 재사용 시 누락 없이 차단 가능 (P10/P23).
    - `is_nxt_only_window()` 패턴 (KRX 비활성 + NXT 활성 판별)과 동일 구조로 KRX/NXT 분리 차단 가능.
  - **사용자 결정 5항목 확정** (규칙 0-4 UI 기준 설명 + 승인):
    1. 08:00~08:50: KRX만 차단 / NXT 허용 (KRX 시장가 불가, NXT 프리마켓 체결 가능)
    2. 08:50~09:00: 양쪽 차단 (시가 동시호가, 양쪽 체결 없음)
    3. 15:20~15:40: 양쪽 차단 (종가 동시호가·체결 정산)
    4. 15:40~20:00: KRX만 차단 / NXT 허용 (KRX 시장가 불가, NXT 애프터마켓 체결 가능)
    5. ±5초 버퍼: execute_buy/execute_sell 내부(주문 체크 시점)에만 적용, phase 산정은 건드리지 않음
    + 토글 UI(기본 ON) + 매수/매도 동일 적용 + KRX_INACTIVE_PHASES 재사용 + force_buy 본 작업에서 제거 안 함
  - **차단 판별 로직**: 신규 함수 `is_order_blocked_by_time(stk_cd)` — KRX 비활성 + NXT 활성 시 `is_nxt_enabled(stk_cd)`로 종목별 분기 (KRX 단독만 차단, NXT 종목 허용). 기존 `is_nxt_only_window()` 패턴과 동일.
  - **아키텍처 원칙 준수**: P10(SSOT — market_phase 단일 기준, 새 시간 상수 생성 금지) · P13(설정 메모리 상주) · P15(단일 주문 경로 — execute_buy/execute_sell 내부에만 게이트) · P16(살아있는 경로 — 내부 체크가 실제 주문 전송 전 호출) · P17(플래그 단일 소스) · P20(폴백 금지 — 빈 문자열 phase 시 logger.error + False) · P21(사용자 투명성 — 토글 + 헤더 칩) · P23(일관성 — 기존 패턴 재사용) · P24(단순성 — 시간 기반, 별도 재개 로직 불필요).
  - **세션 분할 (세션당 1단계 — 규칙 0-1)**: 2세션(태스크 파일) → 3세션(차단 판별 함수 + 설정 키) → 4세션(execute_buy/execute_sell 게이트) → 5세션(WS 이벤트 + 바인딩) → 6세션(설정 토글 + 헤더 칩).
  - **별도 이슈 (force_buy dead parameter)**: `execute_buy(force_buy: bool = False)` 파라미터 존재하나 `force_buy=True` 호출부가 백엔드·프론트엔드·테스트 전체에 0건. P16/P23 위반 소지. 본 작업에서 제거 안 함 → "미해결 문제" 섹션에 별도 기록 필요.
  - **코드 수정 없음**: 설계서 작성 only. 2세션 태스크 파일 작성은 사용자 "진행" 지시 시 시작.
  - **작업 여력**: 충분.
- **NXT 전용 시간대 KRX 종목 숨김 + 안내 배지 구현 (다단계 3세션)**: sector-stock.ts + ui-styles.ts 구현 Step 1 완료.
  - **sector-stock.ts 수정**: DataRowItem 인터페이스 krxInactive 필드 제거 + computeRows KRX 단독 종목 continue 숨김 + 빈 업종 그룹 행 숨김 + stockSeq++ 위치 이동(순번 자동 재정렬) + 안내 배지 DOM/갱신(filterBadge 패턴 재사용, COLOR.warningBg/warning, fade-in 150ms) + rowStyle 분기 제거 + disconnectedCallback 정리.
  - **ui-styles.ts 수정**: inactiveRowBg 상수 1줄 제거 (단일 사용처라 안전).
  - **UI 기준 변경 내용** (규칙 0-4):
    - NXT 전용 시간대: KRX 단독 종목이 회색 배경 흐릿 표시 → 행 자체 숨김 + 순번 1,2,3... 자동 재정렬. 업종 전체가 NXT 종목 0개면 그룹 행도 숨김.
    - 안내 배지: NXT 전용 시간대에 주황색 배지 표시 `NXT 전용 시간대 — KRX 단독 종목 숨김 (N종목)` (fade-in 150ms). 정규장 전환 시 자동 숨김.
    - 회색 배경(#c8c8c8) 제거: 행 자체를 숨기므로 불필요.
  - **검증 결과**: typecheck 통과 + build 성공(2.07s, 63 모듈) + 테스트 108/108 통과 + 개발 서버 5174 기동 정상.
  - **커밋**: `feat: NXT 전용 시간대 KRX 종목 숨김 + 안내 배지 추가 (3세션)`.
  - **작업 여력**: 충분.
- **NXT 전용 시간대 KRX 종목 숨김 처리 심층 사전조사 + 태스크 파일 작성 (다단계 2세션)**: 규칙 0-2 4항목 사전조사 + 단계 분할 + 태스크 파일 작성.
  - **산출물**: `docs/plan_krx_hide_in_nxt_only.md` (567줄) — 3세션/4세션 구현 태스크 상세.
  - **사전조사 (규칙 0-2 4항목)**:
    1. **의존성 조사**: krxInactive 심볼 sector-stock.ts 내 6곳만 참조(외부 파일 참조 없음). inactiveRowBg 단일 사용처(sector-stock.ts:512). _applyMarketPhaseActive 호출부 2곳(L231, L399) 모두 이미 marketPhase 전체 객체 전달 중 → 시그니처 확장해도 호출부 수정 불필요. krxRowEl/nxtRowEl 모듈 변수 참조 유효.
    2. **영향 범위**: 프론트엔드 3개 파일 (sector-stock.ts 중, sector-settings.ts 소, ui-styles.ts 소) — 백엔드 변경 없음(안 B 확정).
    3. **아키텍처 원칙 부합**: P10/P16/P20/P21/P22/P23/P24 전부 재확인. 안 B P10/P23 부분 위험은 REGULAR_PHASES 동기화 주석으로 완화.
    4. **기존 공통 자산 확인**: filterBadge 패턴, COLOR.warningBg/warning, transition 속성, requestAnimationFrame 패턴 재사용 확정. badge.ts/toast.ts 구조 부적합 기각.
  - **REGULAR_PHASES 확정** (header.ts PHASE_STYLE 19개 phase 분석): `new Set(['정규장', '시가 동시호가', '종가 동시호가', '메인마켓'])` — 시간외/NXT 전용 phase 6개('장전 시간외', '장후 시간외', '프리마켓', '애프터마켓', '애프터마켓 지속', '시간외 종가매매 종료 + 시간외 단일가매매 개시')는 is_nxt_only 플래그로 우선 분리되므로 제외. 판정 순서: is_nxt_only 우선 → false일 때만 REGULAR_PHASES 참조.
  - **단계 분할 (세션당 1단계 — 규칙 0-1)**: 3세션(sector-stock.ts + ui-styles.ts — krxInactive 필드 제거 시 computeRows/rowStyle/DataRowItem/updateUI 모두 연관되어 한 세션 전체 수정) + 4세션(sector-settings.ts — 별도 파일, 별도 검증).
  - **커밋 계획**: 3세션 `feat: NXT 전용 시간대 KRX 종목 숨김 + 안내 배지 + 순번 재정렬 (다단계 3세션)` / 4세션 `feat: 업종순위설정 수신률 섹션 3상태 숨김 (NXT 전용/정규장/그 외) (다단계 4세션)`.
  - **코드 수정 없음**: 사전조사 + 태스크 파일 작성 only. 3세션 구현은 사용자 "진행" 지시 시 시작.
  - **작업 여력**: 충분.
- **NXT 전용 시간대 KRX 종목 숨김 처리 설계서 작성 (다단계 1세션)**: 설계 검토 + 디자인 파일 작성.
  - **배경**: 기존 NXT 전용 시간대에 KRX 단독 종목을 회색 배경(#c8c8c8) + 투명도 0.85로 표시 → 사용자가 숨김 방식으로 개선 요청. 업종순위설정 패널 수신률 섹션도 함께 개선 요청.
  - **설계 내용**:
    - sector-stock.ts: computeRows에서 KRX 비활성 종목 continue 제외 + stockSeq++ 위치 이동(순번 자동 재정렬) + 빈 업종 그룹 행 숨김 + krxInactive 필드/분기/색상 상수 제거 + 안내 배지("NXT 전용 시간대 — KRX 단독 종목 숨김 (N종목)", filterBadge 패턴 재사용, fade-in 150ms) 추가.
    - sector-settings.ts: _applyMarketPhaseActive를 2상태(opacity 0.3/1.0) → 3상태(display none/flex) 분기로 확장. 안 B(프론트엔드 phase 문자열 매칭, REGULAR_PHASES 상수) 채택.
    - ui-styles.ts: inactiveRowBg 상수 제거 (단일 사용처라 안전).
    - 트리거 체인: 기존 market-phase WS 이벤트 → applyMarketPhase → uiStore.marketPhase → subscribe 감지 → refreshRows/_applyMarketPhaseActive. 신규 트리거 불필요.
  - **시간 표기 통일**: 모든 표시/숨김 전환 시점을 실제 구독 신청/해지 시간(07:59/08:59/15:20/20:00) 기준으로 통일. 기존 실제 장 시간(08:00/09:00/15:30/15:40) 표기에서 구독 시점 기준으로 변경.
  - **사용자 결정 5항목 확정**: 빈 그룹 행 숨김 / 안내 배지 추가 / fade-in만 / 안 B(프론트엔드 매칭) / 안내 텍스트 미추가.
  - **P원칙 검토**: P10(SSOT — is_nxt_only, nxt_enable 단일 소스) · P16(살아있는 경로 — dead code 위험 없음) · P20(폴백 금지) · P21(사용자 투명성 — 안내 배지 + market-count-row + 헤더 칩 3중 보완) · P22(데이터 정합성 — 파생 데이터 실시간 계산) · P23(일관성 — filterBadge 패턴 재사용, 용어 사전 준수) · P24(단순성 — 제거 분량 ≥ 추가 분량) 부합.
  - **안 B 채택 시 P10/P23 부분 위험**: phase 문자열 목록 변경 시 프론트엔드 추적 필요. 2세션 태스크 파일에서 REGULAR_PHASES와 header.ts PHASE_STYLE 동기화 주석 명시 예정.
  - **작업 여력**: 충분.
- **매도내역 매수일시 컬럼 추가 + 평균가 현행 유지**: 수익상세 페이지 매도내역 테이블에 "매수일시" 컬럼 신규 추가. 평균가 방식은 현행(FIFO 차감 + 잔여 lot 평균가) 유지 — 키움 HTS 0328 화면(매입가 = 총매수금액/보유수량)과 개념 일치.
  - **사전 검토** (코드 수정 전): 한국 주식시장 표준 처리 방식 웹 검색 — 세금 기준 원칙 FIFO(소득세법 시행령 제162조제5항), 예외 이동평균법(일부 증권사). 키움 HTS 0328 화면은 평균단가 표시, 매수일시는 미표시. 사용자 선호(평균가) = HTS 화면 표시 기준 부합. 매수일시 의미: 평균가 조정 시 단일 매수일시는 본질적 모순이나, "잔여 보유분의 최초 매수일"로 타협 (`get_earliest_buy_date`와 동일 출처 재사용, P23).
  - **DB 백업** (db-backup 스킬): `stocks.db.20260717_150244.backup` (1.0M) + `stocks.db-shm.20260717_150244.backup` (32K) + `stocks.db-wal.20260717_150244.backup` (0B).
  - **스키마 마이그레이션** (`backend/app/db/stock_tables.py` 2곳):
    - `init_cache_tables()` CREATE TABLE trades에 `buy_date TEXT` 컬럼 추가 (L46) — 신규 DB 생성 시 포함.
    - `migrate_add_buy_date_to_trades()` 신규 함수 (L268~) — 기존 DB 마이그레이션. `PRAGMA table_info(trades)`로 buy_date 존재 여부 확인 후 `ALTER TABLE trades ADD COLUMN buy_date TEXT`. 기존 `migrate_add_nxt_enable_column`/`migrate_add_hidden_to_custom_sectors` 패턴 준수 (P23).
    - `backend/app/web/app.py` (L48-53) — 기동 시 `migrate_add_buy_date_to_trades()` 호출 추가. `migrate_add_hidden_to_custom_sectors()` 직후.
  - **백엔드 수정** (`backend/app/services/trade_history.py` 4곳):
    - `_ensure_loaded()` SELECT (L45-53) — `t.buy_date` 컬럼 추가 조회.
    - `_TRADE_INSERT_SQL` (L72-78) — INSERT 컬럼/플레이스홀더에 buy_date 추가 (17→18 필드).
    - `_trade_params()` (L81-90) — 튜플 끝에 `rec.get("buy_date", "")` 추가.
    - `record_buy()` rec dict (L284) — `"buy_date": ""` 기본값 추가 (매수 레코드는 buy_date 무의미, 빈 값).
    - `record_sell()` 시그니처 (L309-319) — `buy_date: str = ""` 파라미터 추가. rec dict (L371) — `"buy_date": buy_date` 저장.
  - **백엔드 수정** (`backend/app/services/trading.py` 2곳):
    - `execute_sell()` 평균가 조회부 (L477-504) — `_buy_date` 변수 추가. test 모드: `_computed_pos.get("buy_date")` 추출 (`build_positions_from_trades` 결과). real 모드: `_p.get("buy_date")` 추출 (positions에서). P23 — `get_earliest_buy_date`와 동일 출처 재사용, 신규 함수 생성 없음.
    - `record_sell()` 호출부 (L559-565) — `buy_date=_buy_date` 전달.
  - **프론트엔드 수정** (`frontend/src/pages/profit-shared.ts` 1곳):
    - `SELL_COLS` (L365) — "매수일시" 컬럼 신규 추가 (매수가 컬럼 좌측). `key: 'buy_date'`, `label: '매수일시'`, MM/DD 형식 렌더. 12개 → 13개 컬럼.
  - **테스트 수정** (`backend/tests/test_trade_history.py` 1곳):
    - `TestTradeParams.test_params_order` (L444-460) — 17필드 → 18필드 튜플 순서 갱신. `rec.get("buy_date", "")` 추가.
  - **검증**: pytest test_trade_history 64 passed + test_stock_tables/test_web_app 49 passed (회귀 없음) + npm run build 성공 (1.02s) + 마이그레이션 직접 호출 검증 (buy_date 컬럼 정상 감지/추가) + 분할 매수 시뮬레이션 (7/1 10주@70000 + 7/5 10주@80000 → buy_date=2026-07-01, avg_price=75000 정확) + record_sell buy_date 저장 + _trade_params 18필드 순서 검증 통과.
  - **P원칙**: P10(SSOT — buy_date는 build_positions_from_trades에서 파생, trades가 단일 진실 원천) · P15(단일 주문 경로 — execute_sell 경로 내에서만 buy_date 추출, 분기/우회 없음) · P16(살아있는 경로 — record_sell → _insert_trade → DB INSERT 경로에 연결) · P18(테스트모드 동등성 — test/real 모드 모두 buy_date 추출 로직 포함) · P23(공통 자산 재사용 — get_earliest_buy_date와 동일 출처 재사용, 마이그레이션 함수 기존 패턴 준수) 준수.
  - **safe-trade 스킬 준수**: 주문 경로 분기 없음, RiskManager/CircuitBreaker 미변경, test 모드 유지, 하드코딩 API 키 없음.
  - **주의 사항**: 실전 모드 REST API positions에 buy_date가 없는 경우 빈 문자열로 저장될 수 있음 (engine_account.py에 trade_history SSOT 주입 로직이 있으나 execute_sell 시점 보장은 아님). 기존 매도 레코드(변경 전)는 buy_date 빈 값 — 신규 매도 건부터 매수일시 채워짐.
  - **작업 여력**: 충분.
- **구독/해지 타임라인 재설계 5세션 — 통합 런타임 검증 + 문서 갱신 + 계획서 삭제**: 5세션 전체 작업의 마지막 단계.
  - **`ARCHITECTURE.md`** (2곳):
    - 12.1 타이머 기반 트리거 갱신 (L976-984) — 타임라인 9개 이벤트로 재작성. 07:58 `_on_realtime_fields_reset()` (실시간 필드 초기화 + GC 비활성화 + 캐시 초기화) + 07:59 WS 구독 구간 진입 (상태 전환 + 엔진 루프 통지, 사전 구독) + 08:00 NXT 프리마켓 진입 (업종 재계산, 이미 구독됨) + 08:59 `_on_krx_pre_subscribe()` (KRX 단독 종목 사전 구독, 정규장 1분 전) + 09:00 KRX 정규장 진입 (업종 재계산, 구독은 멱등 스킵) + 15:20 `_on_krx_closing_auction_start()` (KRX 단독 종목 구독 해지, 종가 동시호가 진입) + 20:00 `_on_ws_subscribe_end()` (WS 구독 종료 + GC 정상화) + 20:40 `_fire_unified_confirmed_fetch()` (확정 시세 + 5일봉 다운로드, confirmed_download_time 설정 기본값) + 00:00 `_on_midnight()` (일일 리셋). 구 15:30/16:01/18:00 이벤트 제거 (15:20 종가 동시호가 해지로 통합).
    - 12.3 WS 구독 구간 판정 갱신 (L998-1004) — 사전 구간(07:59~08:00) 시간 기반 판정 `_is_pre_subscribe_window()` 추가 명시. `WS_SUBSCRIBE_PRESTART_TIME(07:59) <= t < NXT_PREMARKET_START(08:00)`, market_phase krx/nxt "휴장일" 시 False. 정규 구간은 기존 NXT_ACTIVE_PHASES 판정 유지.
  - **계획서/조사보고서 삭제 3건** (`git rm`):
    - `docs/architecture_subscribe_timeline_design.md` (설계서 — 1세션 산출물)
    - `docs/plan_subscribe_timeline.md` (태스크 파일 — 2세션 산출물)
    - `docs/subscribe_timeline_investigation.md` (조사보고서 — 2세션 산출물, 사용자 승인으로 추가 삭제 — 계획서에는 2개만 명시되었으나 이번 작업 사이클 산출물이므로 일관성 차원에서 함께 삭제)
  - **검증**: pytest 2838 passed (회귀 없음) + npm run build 성공 (2.09s) + 런타임 기동 `python -W error::RuntimeWarning main.py` RuntimeWarning 0건 + /api/settings 응답 정상 (200) + 잔존 프로세스 0건 + `backend/` 잔존 참조 0건 (Code Removal Rules 규칙 3 만족) + `docs/` 잔존 참조 0건 (session_state 계획서 3건은 2026-07-17 규칙 11 삭제됨).
  - **P원칙**: P10(SSOT — ARCHITECTURE.md 타임라인 단일 진실 소스 갱신) · P21(사용자 투명성 — 타임라인 문서 최신화) · P23(일관성 — 구현과 문서 일치, 구 함수명 참조 정리) 준수.
  - **작업 여력**: 충분.
- **구독/해지 타임라인 재설계 4세션 — 구현 Step 2: 08:59 KRX 사전 구독 + 15:20 KRX 해지 (Change 3, 4)**: 4개 변경안 중 Change 3, 4 구현.
  - **`backend/app/services/engine_state.py`** (1곳):
    - `last_krx_pre_subscribe_date: str = ""` 필드 추가 (L116) — KRX 사전 구독 실행 날짜 (YYYYMMDD). 멱등성 가드 그룹(L113-115)에 추가 — 기존 `last_realtime_reset_date`/`last_ws_subscribe_start_date` 패턴 준수 (P22).
  - **`backend/app/services/daily_time_scheduler.py`** (5곳):
    - `KRX_PRE_SUBSCRIBE_TIME = (8, 59)` 상수 추가 (L48) — 08:59 KRX 사전 구독 (정규장 1분 전). 기존 사전 트리거 상수 그룹에 추가 (P10 SSOT).
    - `_on_krx_pre_subscribe()` 신규 함수 (L463~) — 08:59 KRX 단독 종목 사전 구독 (재계산 없음). 정규장(09:00) 1분 전에 KRX 단독 종목 WS 구독을 미리 수행하여 09:00 시가 동시호가 체결 시점부터 실시간 시세 즉시 수신 (P16). 멱등성 가드 `last_krx_pre_subscribe_date == today_str` 시 스킵. 거래일 체크 후 가드 설정 (주말/공휴일 시 가드 미설정 → 다음 거래일 실행). `subscribe_sector_stocks_0b()` 내부 `_subscribed` 플래그로 09:00 중복 구독 방지 (P22).
    - `_check_prestart_triggers()` 확장 (L1189~) — 08:59 KRX 사전 구독 트리거 추가. `KRX_PRE_SUBSCRIBE_TIME <= t < KRX_REGULAR_START and last_krx_pre_subscribe_date != today_str` 조건. 08:00~09:00 구간에서 별도 트리거 (phase 변경 감지와 분리). docstring 갱신 — 07:58/07:59/08:59 사전 트리거 체크.
    - `_apply_market_phase()` 트리거 조건 변경 (L659) — `new_krx == "체결 정산"` → `new_krx == "종가 동시호가"`, context `"KRX 장외 전환"` → `"KRX 종가 동시호가 — 구독 해지"`. docstring 갱신 (L635) — "15:30 체결 정산" → "15:20 종가 동시호가".
    - `_on_krx_after_hours_start()` → `_on_krx_closing_auction_start()` 개명 (L490) — docstring "15:30 전환 콜백" → "15:20 종가 동시호가 전환 콜백", "KRX 종가 동시호가 종료(15:30) 시점" → "KRX 정규장 종료(15:20) 시점". 시장가 주문만 사용하므로 종가 동시호가 구간 체결 불가 → 구독 유지 불필요 명시. 동작 내용 동일 (재계산 + KRX 단독 종목 해지).
  - **`backend/tests/test_daily_time_scheduler.py`** (갱신 3 + 신규 8):
    - import 갱신: `_on_krx_pre_subscribe`, `_on_krx_closing_auction_start` 추가 (기존 `_on_krx_after_hours_start` 제거).
    - `TestOnKrxAfterHoursStart` → `TestOnKrxClosingAuctionStart` 개명 — 시각 `_make_kst(15, 30)` → `_make_kst(15, 20)` 3곳. 함수 호출 `_on_krx_after_hours_start()` → `_on_krx_closing_auction_start()` 3곳.
    - `test_triggers_krx_after_hours_on_phase_change` → `test_triggers_krx_closing_auction_on_phase_change` 갱신 — "체결 정산" 전환 → "종가 동시호가" 전환, context "KRX 장외 전환" → "KRX 종가 동시호가 — 구독 해지".
    - `TestCheckPrestartTriggers` 신규 3: `test_triggers_krx_pre_subscribe_at_0859` (08:59 트리거 1회), `test_skips_krx_pre_subscribe_if_already_run` (멱등성 가드), `test_skips_krx_pre_subscribe_after_0900` (09:00 이상 스킵).
    - `TestOnKrxPreSubscribe` 신규 클래스 5: `test_trading_day_subscribes` (거래일 구독 + 가드 설정), `test_weekend_skips` (주말 스킵 + 가드 미설정), `test_holiday_skips` (공휴일 스킵 + 가드 미설정), `test_skips_if_already_run_today` (멱등성 가드), `test_exception_does_not_raise` (예외 처리).
  - **검증**: pytest 2838 passed (기존 2830 + 신규 8, 회귀 없음) + 런타임 기동 `python -W error::RuntimeWarning main.py` RuntimeWarning 0건 + /api/settings 응답 정상 + 잔존 프로세스 0건 + `backend/` 잔존 참조 0건.
  - **P원칙**: P10(SSOT — 기존 시간 상수 재사용, 멱등성 가드 패턴 준수) · P16(살아있는 경로 — 08:59 시간 기반 트리거로 재시작 시 사전 구간 누락 없음) · P20(폴백 금지 — 정상 경로 확장) · P22(데이터 정합성 — `last_krx_pre_subscribe_date` 멱등성 가드, `subscribe_sector_stocks_0b()` 내부 `_subscribed` 플래그로 09:00 중복 구독 방지) · P23(일관성 — 함수 개명으로 명칭-동작 일치, 기존 패턴 준수) · P24(단순성 — 신규 함수 1개 + 상수 1개 + 필드 1개만 추가) 준수.
  - **작업 여력**: 충분.
- **문서 폴더 통합 — backend/docs/ → docs/ + 문서 경로 규칙 추가**: 분산된 문서를 docs/ 한 곳으로 통합 + 경로 규칙 문서화.
  - **파일 이동 2건** (`git mv` — 이력 보존):
    - `backend/docs/architecture_session_state_design.md` → `docs/architecture_session_state_design.md` (2026-07-17 규칙 11 삭제됨 — 안 D 완료)
    - `backend/docs/log_korean_migration_plan.md` → `docs/log_korean_migration_plan.md`
  - **`backend/docs/` 빈 폴더 삭제**.
  - **경로 참조 갱신 10곳**:
    - `AGENTS.md` 2곳 (line 201, 270 — 다단계 워크플로우 설계서 경로).
    - `docs/plan_session_state_*.md` 3곳 (line 5 — 관련 설계 문서 참조, 2026-07-17 규칙 11 삭제됨 — 안 D 완료).
    - `HANDOVER.md` 5곳 (역사적 참조 경로 일관성 유지 — 삭제된 파일 포함).
  - **`AGENTS.md` 신규 섹션 추가** — "문서 저장 경로 규칙 (P10 SSOT · P23 일관성)":
    - 설계서 `docs/architecture_*_design.md` / 태스크 `docs/plan_*.md` / 조사보고서 `docs/*_investigation.md` / API 스펙 `docs/api_specs/` / 감사계획 `docs/architecture_audit_plan.md` 경로 패턴 명시.
    - 금지: `backend/docs/`, `frontend/docs/` 등 코드 디렉터리 하위 문서 폴더 신규 생성.
    - 의무: 문서 이동 시 AGENTS.md·HANDOVER.md·태스크 파일 모든 참조 경로 동시 갱신 (P10 SSOT — 잔존 참조 방지).
  - **검증**: `grep "backend/docs/"` 잔존 2곳은 신규 규칙의 "금지 패턴 명시"로 의도적 (실제 파일 경로 참조 0건). 루트 폴더 임시/불필요 파일 없음. 코드 수정 없음(경로 참조만) — 빌드/테스트 영향 없음.
  - **P원칙**: P10(SSOT — 문서 단일 진실 소스) · P23(일관성 — 경로 패턴 표준화) 준수.
  - **작업 여력**: 충분.
- **매수/매도 설정 패널 UI 일관성 정리 + 주문 간격 라벨 2행/위치 정렬**: 매도설정 패널을 매수설정 기준으로 정리 + 주문 간격 섹션 UI 개선.
  - **`frontend/src/components/common/setting-row.ts`** (1곳 — `createToggleLabelControlsRow`):
    - `labelSubText?: string` 옵션 추가 (라벨 2행 처리). 보조 텍스트는 `FONT_SIZE.small`(11px) + `COLOR.tertiary`(회색)로 본문과 시각적 구분.
    - `labelWrap` 내부에 `labelBox`(flex column, line-height 1.2) 추가 — 본문 라벨 + 보조 라벨 2줄 구성.
    - 기존 호출처는 `labelSubText` 생략 시 기존 동작 유지 (선택적 옵션, 호환성 보장).
  - **`frontend/src/pages/sell-settings.ts`** (매수설정 기준 일관성 정리 — 169줄 → 173줄):
    - 익절/손절: 2줄 분리(토글 행 + 입력 행) → `createToggleLabelControlsRow` 1줄 통합. 인라인 토글 핸들러(`setOn`+`setDisabled`+`saveImmediate` 직접 작성) 제거 → `onToggle` 콜백만 작성 (매수 패턴).
    - 추적 매도 B-1 패턴: 토글+`ts_start_val` 한 줄(`createToggleLabelControlsRow` + `extraDisableTargets: [tsDropRow]`), `ts_drop_val` 별도 행. 토글 끄기 시 두 입력칸 함께 비활성화 (매수 잔량비율 dual slider 패턴과 동일).
    - syncFromSettings: `setDisabled(tpValRow!, !tpOn)` (non-null assertion) → `if (tpValControls) setDisabled(tpValControls, !tpOn)` (널 체크, 매수 패턴).
    - 모듈 상태 변수 주석: 역할별(`// 토글 참조`/`// 입력 참조`/`// 비활성 래퍼`) → 기능별(`// 익절/손절 UI 참조`/`// 추적 매도 UI 참조`/`// 매도 주문 간격 UI 참조`).
    - 라벨: `고점 추적 매도(Trailing Stop)` → `고점 추적 매도` (영문 제거, P23 용어 통일).
    - unmount: 기능별 그룹화 (매수 패턴).
    - 매도 주문 간격 라벨: `'매도 주문 간격 활성화 (초, 5초 단위)'` → `labelText: '매도 주문 간격 활성화'` + `labelSubText: '(초, 5초 단위, 손절 포함)'`.
  - **`frontend/src/pages/buy-settings.ts`** (주문 간격 섹션):
    - 라벨: `'매수 주문 간격 활성화 (초, 5초 단위)'` → `labelText: '매수 주문 간격 활성화'` + `labelSubText: '(초, 5초 단위)'`.
    - 섹션 위치: 중간(매수 금액 한도 → 매수 주문 간격 → 동일 종목 재매수 제어) → 가장 하단(매수 금액 한도 → 동일 종목 재매수 제어 → 매수 주문 간격). 매도(매도 유형 → 매도 주문 간격)와 동일 배치.
  - **유지 항목** (변경 금지 — 의도적 차이):
    - 매도 "매도 유형" 섹션 구조 (주문 유형 + 익절/손절/추적매도 묶음 — 매도 특성상 합리적).
    - 매도 주문 간격 안내 문구 "손절 포함 모든 매도에 간격이 적용됩니다" (P21 사용자 투명성).
  - **검증**: `npm run typecheck` 통과 + `npm run build` 성공(2.05s, `setting-row` 8.16 kB / `sell-settings` 2.86 kB / `buy-settings` 정상 생성, 에러 없음).
  - **P원칙**: P23(일관성 — 공통 컴포넌트 `createToggleLabelControlsRow` 재사용, 매수/매도 패턴 통일, 용어 통일) · P24(단순성 — 인라인 토글 핸들러 제거로 코드 감소) 준수.
  - **작업 여력**: 충분.
- **매수/매도 주문 간격 설정 개선 다단계 7세션 — 문서 + 런타임 검증 + 계획서 삭제 Step 5 (다단계 작업 전체 완료)**: 1~6세션 구현의 문서 갱신 + 통합 런타임 검증 + 작업 계획서 정리.
  - **`ARCHITECTURE.md:813-823`** (섹션 7.4 — 1곳):
    - 제목: "매수 주문 간격 및 쓰로틀" → "매수/매도 주문 간격 및 쓰로틀" (매도 간격 추가 반영).
    - 표 항목: `buy_interval_min | 0분 | 1순위 종목 매수 후 대기 간격 (분 단위)` 1줄 제거 → `buy_interval_sec | 30초 | 매수 주문 간격 (초 단위, 5~300, 5초 단위)` + `sell_interval_on | False | 매도 주문 간격 활성화 (토글)` + `sell_interval_sec | 30초 | 매도 주문 간격 (초 단위, 5~300, 5초 단위, 손절 포함)` 3줄 추가 (P10 SSOT — 문서와 코드 단일 진실 소스 일치, P21 사용자 투명성 — 손절 포함 명시).
  - **삭제 2개 파일** (사용자 승인 — 계획서 삭제 규칙):
    - `docs/plan_order_interval.md` (450줄 — 2세션 태스크 파일, 심층 사전조사 + 수정 범위 + 구현 Step + 테스트 계획).
    - `docs/architecture_order_interval_design.md` (433줄 — 1세션 설계서, 안 B 공통 모듈 추출 + 분리 설정 + 초 단위).
    - `git rm`로 삭제 — 다단계 작업 완료 후 계획서 정리 (AGENTS.md 섹션4 다단계 워크플로우 규칙).
  - **검증 (통합 런타임 검증)**:
    - pytest 전체 2822 passed (6세션과 동일 카운트, 회귀 없음).
    - npm run build 635ms 성공 (에러 없음).
    - 잔존 `buy_interval_min` 참조 6곳 — 모두 마이그레이션 로직/테스트 의도적 잔존 (`engine_settings.py` 3곳 + `test_engine_settings.py` 3곳). 프론트엔드/문서 잔존 0건.
    - 런타임 기동 `python3 -W error::RuntimeWarning main.py` — RuntimeWarning 0건, 기동 146ms, 에러/traceback 없음.
    - WS 설정 응답(`/api/settings`) 4개 필드 모두 존재: `buy_interval_on=True`, `buy_interval_sec=30`, `sell_interval_on=False`, `sell_interval_sec=30`.
    - 잔존 프로세스 0건.
  - **P원칙**: P10(SSOT — ARCHITECTURE.md와 코드 일치) · P21(사용자 투명성 — 손절 포함 명시) · P23(용어 통일 — "매수/매도 주문 간격") 준수.
  - **작업 여력**: 충분.
- **매수/매도 주문 간격 설정 개선 다단계 6세션 — 테스트 Step 4**: 3~5세션에서 구축·배선·UI 반영된 매수/매도 주문 간격 기능의 테스트 검증 (P16 살아있는 경로 — 게이트/타이머 배선 테스트로 확인). 마이그레이션 테스트 3개는 3세션에서 이미 완료(중복 제외).
  - **`test_buy_order_executor.py`** (신규 2개 — `TestBuyIntervalGate` 클래스 내):
    - `test_buy_interval_off_passes`: `buy_interval_on=False, buy_interval_sec=300` + `_last_global_buy_ts=now` → 토글 OFF 시 간격 내라도 통과 → `execute_buy` 호출. 기존 2개(차단/통과)와 함께 4개 케이스로 게이트 4가지 상태全覆盖.
    - `test_buy_interval_zero_sec_passes`: `buy_interval_on=True, buy_interval_sec=0` + `_last_global_buy_ts=now` → 0초=비활성 시 통과 → `execute_buy` 호출. `check_order_interval` 헬퍼의 `_sec <= 0` 분기 검증.
  - **`test_trading.py`** (신규 클래스 `TestSellIntervalGate` 5개 — `TestCheckSellConditions` 이후, `TestOnFillUpdate` 이전):
    - `test_sell_interval_blocks_within_period`: `sell_interval_on=True, sell_interval_sec=30` + `_last_global_sell_ts=now` + 손절 종목 → `execute_sell` 미호출 (간격 게이트가 for-loop 진입 차단).
    - `test_sell_interval_passes_after_period`: `_last_global_sell_ts=now-60` (간격 30초 초과) → `execute_sell` 호출.
    - `test_sell_interval_off_passes`: `sell_interval_on=False` + `_last_global_sell_ts=now` → 토글 OFF 시 통과 → `execute_sell` 호출.
    - `test_sell_interval_applies_to_loss_cut`: 손절 조건(pnl_rate=-6.0, loss_val=5%) + 간격 내 → `execute_sell` 미호출. **사용자 결정(손절 포함 모든 매도에 간격 적용) 검증** — plan_order_interval.md 1-3.
    - `test_mark_order_executed_updates_sell_ts`: `mark_order_executed("sell")` 헬퍼 직접 호출 → `state._last_global_sell_ts > 0` 갱신 확인. trading.py:535-536 배선 검증 (기존 test_trading.py 모든 테스트가 `mgr.execute_sell = AsyncMock()`로 실제 execute_sell 미호출 → 헬퍼 직접 단위테스트로 배선 검증).
  - **`test_web_routes.py:549`**: `mock_state._last_global_buy_ts = 0.0` 옆에 `mock_state._last_global_sell_ts = 0.0` 1줄 추가 — 일일 리셋 시 매도 타이머도 0으로 초기화됨을 테스트 설정에 반영 (settings.py:153-154 배선).
  - **검증**: py_compile 3개 파일 통과 + pytest 전체 2822 passed (이전 2815 + 신규 7 = 2822, 회귀 없음) + 잔존 프로세스 0건. ruff 미설치 환경으로 생략 (py_compile + pytest로 대체).
  - **P원칙**: P16(살아있는 경로 — 게이트/타이머 배선 테스트로 확인) · P22(데이터 정합성 — 성공 시만 타이머 갱신 검증) · P23(일관성 — 매수/매도 동일 패턴 테스트 구조) 준수.
  - **작업 여력**: 충분.

- **매수/매도 주문 간격 설정 개선 다단계 5세션 — 프론트엔드 Step 3**: UI에 매도 간격 섹션 추가 + 매수 간격 초 단위 변경 (P21 사용자 투명성). 3~4세션에서 구축·배선된 백엔드 `_sec` 키를 UI에 반영.
  - **`types/index.ts`** (2곳):
    - line 122-124: `buy_interval_min: number` → `buy_interval_sec: number` + 주석 "초 단위 5~300 5초 단위" (P10 SSOT).
    - line 138-143: 매도 설정 영역(`sell_offset` 이후)에 `sell_interval_on: boolean` + `sell_interval_sec: number` 추가 + 주석 "손절 포함 모든 매도에 적용".
  - **`buy-settings.ts`** (4곳):
    - line 6 import: `sectionTitle` → `sectionTitle, createDescText` (P23 공통 자산 재사용 — general-settings.ts/sector-settings.ts에서 안내 라벨로 이미 사용).
    - line 159 syncFromSettings: `r.buy_interval_min` → `r.buy_interval_sec`, `|| 0` → `|| 30` (기본값 30초).
    - line 338-351 mount: `createNumInput({ value: 0, step: 1, name: 'buy_interval_min' })` → `{ value: 30, step: 5, min: 5, max: 300, name: 'buy_interval_sec' }` + `vals.buy_interval_sec`. 라벨 `'매수 주문 간격 활성화 (분)'` → `'매수 주문 간격 활성화 (초, 5초 단위)'`.
    - 안내 라벨: `createDescText('5초 단위로 설정 가능합니다 (5~300초, 기본 30초)')` 추가 (P21 투명성).
  - **`sell-settings.ts`** (5곳):
    - line 5-6 import: `createToggleLabelControlsRow`(setting-row) + `createDescText`(settings-common) 추가.
    - line 36-38 변수: `sellIntervalToggle`/`sellIntervalInput`/`sellIntervalControls` 3개 추가 (buy-settings.ts 매수 간격 변수와 동일 패턴 — P23 일관성).
    - syncFromSettings: 매도 간격 동기화 블록 추가 (`sell_interval_on` 토글 + `sell_interval_sec` 값 + `setDisabled`).
    - mount line 136-149: "매도 주문 간격" 섹션 신규 (`sectionTitle` + `createNumInput`(step 5/min 5/max 300/value 30) + `createToggleLabelControlsRow` + `createDescText` 안내 "5초 단위로 설정 가능합니다 (5~300초, 기본 30초). 손절 포함 모든 매도에 간격이 적용됩니다."). 추적매도 `tsDropRow` 이후, `container.appendChild(root)` 이전.
    - unmount: `sellIntervalToggle/Input/Controls` 3개 null 처리 추가.
  - **검증**: `npm run typecheck` 통과 + `npm run build` 성공(772ms, 에러 없음) + 잔존 `buy_interval_min` 프론트엔드 0건(grep 확인). 백엔드 잔존은 마이그레이션 로직 3곳 + 테스트 3곳 + 설계서 22곳 = 모두 6/7세션에서 처리 예정 (계획된 잔존).
  - **P원칙**: P10(SSOT — `buy_interval_sec` 단일 키) · P21(사용자 투명성 — 매도 간격 UI + 안내 라벨) · P23(용어 통일 — "매도 주문 간격"/"종목") · P23(공통 자산 재사용 — `createDescText`/`createToggleLabelControlsRow`/`createNumInput`) · P23(UI 패턴 일관성 — 매수/매도 간격 섹션 동일 구조) 준수.
  - **작업 여력**: 충분.
- **매수/매도 주문 간격 설정 개선 다단계 4세션 — 백엔드 배선 Step 2**: 헬퍼를 실제 매수/매도 실행 경로에 배선 (P16 살아있는 경로). 3세션에서 구축한 헬퍼가 이제 실제 호출됨.
- **매수/매도 주문 간격 설정 개선 다단계 4세션 — 백엔드 배선 Step 2**: 헬퍼를 실제 매수/매도 실행 경로에 배선 (P16 살아있는 경로). 3세션에서 구축한 헬퍼가 이제 실제 호출됨.
  - **★ `order_interval.py` import 방식 수정 (3세션 코드 정제)**: 3세션에서 `from backend.app.services.engine_state import state`를 모듈 top-level에 배치했으나, 테스트가 `patch("backend.app.services.engine_state.state", fresh_state)`로 state를 mock할 때 top-level import는 원본 싱글톤을 바인딩하므로 패치가 적용되지 않는 문제 발견 → 함수 내부 import로 변경 (`buy_order_executor.py:42`, `trading.py:125/224/330/521/588`과 동일 패턴 — P23 일관성). 순환 import 위험 없음. 사용자 설계 로직 롤백 아님 (3세션 코드의 정제).
  - **`buy_order_executor.py`** (3곳):
    - line 36 docstring: "간격 대기" → "간격(초) 대기" (P23 + Code Removal Rules).
    - line 105-112 (7줄 → 3줄): `_buy_interval_on` 변수 + `buy_interval_min` 분 단위 게이트 → `check_order_interval(state.integrated_system_settings_cache, "buy")` 헬퍼 호출. `_buy_interval_on` 변수 제거 (헬퍼 내부로 이동).
    - line 185-186: `if _buy_interval_on: state._last_global_buy_ts = time.time()` → `mark_order_executed("buy")` 헬퍼 호출. 토글 OFF 시에도 타이머 갱신 (게이트가 통과시키므로 영향 없음, P24 단순화).
    - `import time` 제거 — 더 이상 사용하지 않음 (dead import 제거 — P16/P23).
  - **`trading.py`** (2곳):
    - line 610-613 (`check_sell_conditions` for-loop 직전): 매도 간격 게이트 `check_order_interval(base_settings, "sell")` 추가. RiskManager 체크 이후, for-loop 이전.
    - line 534-536 (`execute_sell` 성공 블록 진입 직후, 저널링 이전): `mark_order_executed("sell")` 타이머 갱신. 매수 로직과 대칭 (P22: 실제 실행만 기록, P23: 매수/매도 동일 패턴, P24: 실패 보호는 서킷브레이커 담당).
  - **`test_buy_order_executor.py:232-264`**: `TestBuyIntervalGate` 2개 케이스 `buy_interval_min` → `buy_interval_sec` 교체. 차단 테스트: `buy_interval_sec=300` + 최근 타임스탬프. 통과 테스트: `buy_interval_sec=60` + 120초 전 타임스탬프.
  - **검증**: py_compile 통과 + ruff check 통과 + pytest 전체 2815개 통과(3세션과 동일 카운트, 신규 실패 없음) + 런타임 기동 RuntimeWarning 0건(기동 124ms, 에러/traceback 없음) + 잔존 프로세스 0건 + lock 파일 정리 완료.
  - **P원칙**: P15(단일 주문 경로 — 게이트만 추가, 경로 분기 없음) · P16(살아있는 경로 — 헬퍼 실제 호출) · P22(데이터 정합성 — 성공 시만 타이머 갱신) · P23(일관성 — 매수/매도 동일 패턴 + 함수 내부 import 통일) · P24(단순성 — 7줄→3줄) 준수.
  - **거래 안전성 (safe-trade)**: 모의투자 모드 유지 · 주문 경로 단일성 유지 · RiskManager/CircuitBreaker 배선 변경 없음 · P15/P16/P18 준수.
  - **작업 여력**: 충분.
- **매수/매도 주문 간격 설정 개선 다단계 3세션 — 백엔드 기반 Step 1 (커밋 `9aecd5f`)**: 헬퍼 모듈 + 상태/설정/마이그레이션 기반 구축. 헬퍼는 아직 매수/매도 실행 경로에 배선하지 않음 (4세션에서 배선).
  - **신규 `order_interval.py`** (~30줄): `check_order_interval(settings, kind)` — 토글 OFF/0초/최초 시 True, 간격 내 False. `mark_order_executed(kind)` — 타이머 갱신. P23 공통 자산, P20 폴백 금지(`int(... or 0)` 패턴), P24 단순성.
  - **`engine_state.py:75-77`**: `_last_global_sell_ts: float = 0.0` 추가 + 주석 "주문 간격 타이머 (매수/매도 공통)".
  - **`settings_defaults.py:92-96`**: `buy_interval_min: 0` 제거 → `buy_interval_sec: 30` + `sell_interval_on: False` + `sell_interval_sec: 30`.
  - **`engine_settings.py:230-245`**: 분→초 마이그레이션 로직 + sell 3줄. **★ 설계서 버그 수정**: 설계서의 `merged.get("buy_interval_sec") if _v is None` 패턴은 DEFAULT_USER_SETTINGS에 `buy_interval_sec: 30` 추가 시 항상 30이 반환되어 마이그레이션이 동작하지 않음 → `flat`(DB 원본) 기반 키 존재 검사로 수정 (`if "buy_interval_sec" in flat: ... elif "buy_interval_min" in flat: ... else: 30`).
  - **`settings.py:152-154`**: 일일 리셋 시 `_last_global_sell_ts = 0.0` 추가.
  - **`test_engine_settings.py:353-373`**: `test_buy_interval_settings` _sec 교체 + `test_sell_interval_settings` 신규 + 마이그레이션 테스트 3개(`test_buy_interval_migration_min_to_sec` / `test_buy_interval_migration_zero` / `test_buy_interval_no_migration_when_sec_present`).
  - **`test_buy_order_executor.py:51-52`**: `_default_settings` 헬퍼 `buy_interval_min: 0` → `buy_interval_sec: 30` 교체. (TestBuyIntervalGate 본체 236/252행은 4세션에서 교체 — 배선 변경 직접 영향)
  - **검증**: py_compile 통과 + ruff check 통과 + pytest 전체 2815개 통과(신규 5개 포함) + 런타임 기동 RuntimeWarning 0건(기동 430ms, 에러/traceback 없음) + 잔존 프로세스 0건 + lock 파일 정리 완료.
  - **P원칙**: P10(SSOT — 헬퍼 1곳) · P20(폴백 금지) · P22(데이터 정합성) · P23(일관성) · P24(단순성 — ~30줄) 준수.
  - **작업 여력**: 충분.
  - **매도 타이머 갱신 시점 확정**: line 534 (주문 전송 성공 후) — 매수 로직(`buy_order_executor.py:182-186` `if _ordered:` 성공 시 갱신)과 대칭. P23 일관성 + P22 데이터 정합성(실패를 실행으로 기록 금지) + P24 단일 책임(실패 보호는 서킷브레이커 담당, 간격 게이트는 실행 간격만 담당).
  - **설계서 누락 4곳 발견**: `test_engine_settings.py:353-356` + `test_web_routes.py:549` + `buy-settings.ts:157-159`(syncFromSettings) + `buy_order_executor.py:36`(docstring) — 수정 범위 백엔드 7→8곳, 테스트 2→3곳로 보완.
  - **세션 분할 7세션 확정**: 심층조사 후에도 설계서 제안(7세션) 유지. 3세션에 테스트 2개 파일 포함(기반 변경 직접 영향 — 분리 시 pytest 전체 실패 상태 방치 위반).
  - **태스크 파일**: `docs/plan_order_interval.md` (450줄, 11섹션)
- **TOCTOU 경쟁 상태 수정 (A+B 조합, 커밋 `389505d`)**: check_buy_power 검증 시점과 실제 차감 시점 사이의 비동기 타이밍 갭(0.1초)으로 인한 경쟁 상태 해결. P-NEW-3 해결 완료.
  - A(사전 차감): `settlement_engine.reserve_buy_power`/`release_buy_power` 신규 + `dry_run._apply_buy` pre_reserved 플래그. B(글로벌 매수 락): `AutoTradeManager._buy_lock`(asyncio.Lock) 신규, execute_buy 래퍼 분리.
  - 검증: pytest 169개 통과 + 런타임 기동 RuntimeWarning 0건. P10/P15/P22/P23 준수.

## 다음 세션 진행 대기: 매수/매도 주문 간격 설정 개선 (다단계 작업)

### 단계 진행 상황
- **1세션 (완료, 커밋 `d49cbcc`)**: 설계 검토 + 디자인 파일 작성 — 매수 간격 로직 분석 + 매도 로직 분석 → 3가지 설계안 비교 → 사용자 4가지 결정 + 초 단위 범위 확정 → 설계서 작성.
  - **설계서**: `docs/architecture_order_interval_design.md` (433줄)
  - **선택안**: 안 B (공통 모듈 추출 + 분리 설정 + 초 단위)
  - **사용자 확정 사항**: 매도 간격 추가(손절 포함) / 초 단위(5~300초, 기본 30초, 5초 단위) / `_sec` 키 + 마이그레이션 / 각각 따로 / 공통 모듈 추출 / "5초 단위로 설정 가능" 안내
- **2세션 (완료, 커밋 `f1c5dde`)**: 심층 사전조사 + 태스크 파일 작성 — 매도 타이머 갱신 시점 확정(line 534) + 설계서 누락 4곳 발견 + 프론트엔드 구조 분석 → 태스크 파일 작성.
  - **태스크 파일**: `docs/plan_order_interval.md` (450줄)
  - **매도 타이머 갱신 시점**: line 534 (성공 후) — 매수 로직과 대칭 (P22/P23/P24 준수)
  - **설계서 누락 4곳**: test_engine_settings.py + test_web_routes.py + buy-settings.ts syncFromSettings + buy_order_executor.py docstring
  - **수정 범위 확정**: 백엔드 8곳 + 프론트엔드 3곳 + 테스트 3곳 + 문서 1곳 = 15곳
- **3세션 (완료, 커밋 `9aecd5f`)**: 구현 Step 1 — 백엔드 기반: `order_interval.py` 헬퍼 + `engine_state.py` + `settings_defaults.py` + `engine_settings.py`(마이그레이션) + `settings.py`(일일 리셋) + 테스트 기반 2개(test_engine_settings.py + test_buy_order_executor.py `_default_settings`). ★ 설계서 마이그레이션 버그 수정(merged→flat 기반). 검증: pytest 2815개 + 런타임 기동 RuntimeWarning 0건.
- **4세션 (완료)**: 구현 Step 2 — 백엔드 배선: `order_interval.py` import 방식 수정(함수 내부) + `buy_order_executor.py`(docstring + 게이트 헬퍼 + 타이머 헬퍼 + `import time` 제거) + `trading.py`(매도 게이트 + 타이머 갱신) + `test_buy_order_executor.py`(TestBuyIntervalGate 2개 `_sec` 교체). 검증: pytest 2815개 + 런타임 기동 RuntimeWarning 0건.
- **5세션 (완료)**: 구현 Step 3 — 프론트엔드: `types/index.ts`(`buy_interval_sec` + `sell_interval_on`/`sell_interval_sec`) + `buy-settings.ts`(syncFromSettings `_sec` + createNumInput step 5/min 5/max 300 + 라벨 "초" + `createDescText` 안내) + `sell-settings.ts`(import 2개 + 변수 3개 + syncFromSettings + mount "매도 주문 간격" 섹션 + unmount 정리). 검증: typecheck 통과 + build 772ms 성공 + 잔존 `buy_interval_min` 프론트엔드 0건.
- **6세션 (대기)**: 구현 Step 4 — 테스트: `TestSellIntervalGate` 5개 + 마이그레이션 3개 + `test_web_routes.py`
- **7세션 (대기)**: 구현 Step 5 — 문서(`ARCHITECTURE.md`) + 런타임 검증 + 계획서 2개 삭제

### 참조 문서
- **설계서**: `docs/architecture_order_interval_design.md` (1세션)
- **태스크 파일**: `docs/plan_order_interval.md` (2세션)

### 승인 대기 항목
- **6세션 진행**: 구현 Step 4 (테스트) — 사용자 "진행" 지시 시 시작

## 이전 세션 완료 작업 (커밋 완료)
- 3단계: 백엔드 수신률 KRX/NXT 분리 집계 + 임계값 게이트 옵션 C (8개 파일) — 구현 + 검증 + 커밋 완료.
- 분리 작업 자체는 구독 로직 미변경 확인 (git diff 확정). 본 문제와 무관.

## 완료된 다단계 작업: 카운트다운 SSOT 구현 (안 3 — 백엔드 카운트다운 SSOT) ✅

### 단계 진행 상황
- **1세션 (완료)**: 설계 검토 + 디자인 파일 작성 — 3안 비교(안 1 JIF 카운트다운 코드 처리 / 안 2 현상 유지 / 안 3 백엔드 카운트다운 SSOT) → 안 3 추천 → 사용자 안 3 확정. 디자인 파일: `docs/architecture_countdown_supplement_design.md` (삭제됨)
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성 — WS 메시지 흐름 파악 + 기존 시간표 상수 재사용 확인 + 구현 상세 + 세션 분할 + 테스트 계획. 태스크 파일: `docs/plan_countdown_supplement.md` (삭제됨)
- **3세션 (Step 1, 완료, 커밋 `9bd99ef`)**: 백엔드 구현 + 테스트 — `calc_countdown()` 신규 + 상수 3개 + `get_market_phase()` 필드 추가 + 테스트 9개. 검증 통과 (py_compile + ruff + pytest 167개 + 런타임 기동 RuntimeWarning 없음 + 잔존 프로세스 0건).
- **4세션 (Step 2, 완료, 커밋 `bf992fb`)**: 프론트엔드 구현 + 빌드 — 4개 파일 수정 (34 insertions, 44 deletions). `types/index.ts`/`uiStore.ts`/`binding.ts` 타입 정의에 countdown 필드 추가 + `header.ts`에서 `KRX_COUNTDOWN`/`NXT_COUNTDOWN`/`COUNTDOWN_THRESHOLD_MIN`/`computeCountdown()` 제거 + `formatCountdown()` 신규 + 호출부 2곳 수정 + 30초 setInterval 유지(수신값 재적용). 검증 통과 (`npm run build` 성공 + 잔존 참조 0건).
- **5세션 (Step 3, 완료, 커밋 대기)**: 통합 검증 + 계획서 삭제 — pytest 2789개 통과 + `npm run build` 성공 + 런타임 기동 RuntimeWarning 0건 + WS market-phase 메시지 `krx_countdown`/`nxt_countdown` 필드 존재 확인 + 잔존 프로세스 0건 + 계획서 파일 2개 삭제. 상세는 "직전 완료 작업" 섹션 참조.

### 참조 문서
- 디자인 파일·태스크 파일: 구현 완료 후 삭제됨 (규칙: 계획서 삭제). 설계/구현 상세는 git history(`9bd99ef`/`bf992fb`) 참조.

### 차기 권장 (별도 세션)
- **장 시간대 브라우저 카운트다운 칩 확인**: 카운트다운 대상 페이즈 진입 시점(08:50, 15:10, 19:50 등)에 백엔드+프론트엔드 기동 후 헤더 카운트다운 칩 실시간 표시 확인. 현재 시각(휴장일 새벽)은 확인 불가.

---

## 이전 세션 진행 대기: KRX 수신률 미표시 문제 추가 조사 (타이머 미실행 근본 원인)

### 문제 개요 (사용자 보고)
- **현상**: 앱을 NXT 프리마켓 08:00 이전에 기동한 후, 10:50경 확인하니 NXT 수신률만 표시되어 있고 KRX 수신률 표시가 없었음.
- **기대 동작**: 09:00 정규장 시작 후 KRX 수신률도 표시되어야 함.

### 3차 조사 핵심 발견 (이번 세션)
- **08:00 타이머도 미실행** (사실 11): 08:29:59에 실행된 "NXT 프리마켓 진입 (08:00)" 로그는 08:30 타이머가 대신 실행된 것. 08:00~08:30 28분 공백도 이로 설명됨.
- **08:30 타이머 정상 실행** (사실 11): 같은 이벤트 루프에서 08:30 타이머는 정상 실행됨.
- **자동매매 타이머 정상 실행** (사실 12): 08:01:59에 자동매매 시간 전환 타이머 정상 실행. 같은 루프에서 일부만 실패.
- **15분 로그 공백 = 자연스러운 현상** (사실 13): 08:50 이후 양 시장 비거래 구간이라 틱 없음. 이벤트 루프 블록 아님.
- **타이머 예약 로그 DEBUG 레벨** (사실 14): INFO 로그에 타이머 예약/실행 추적 정보가 전혀 남지 않음. 원인 특정의 주요 장애물.
- **07:50~09:00 설정 변경 없음** (사실 15): PATCH 0건, `schedule_ws_subscribe_timers()`는 기동 시 1회만 호출.
- **타이머 핸들 리스트 교체/손실 경로 없음** (사실 16): 코드상 `.clear()`, `.append()`만 사용, 리스트 객체 교체 경로 없음.

### 배제된 가능성 (3차 조사)
- 이벤트 루프 전체 블록 — 아님 (자동매매 타이머 정상 실행)
- 타이머 핸들 리스트 교체/손실 — 코드상 경로 없음
- 설정 변경에 의한 타이머 재예약 — 07:50~09:00 사이 설정 변경 없음
- 15분 로그 공백 = 이벤트 루프 블록 — 아님 (비거래 구간 정상)

### 여전히 남은 가능성 (3차 조사)
- `schedule_ws_subscribe_timers()` 재호출 (DEBUG 로그로 추적 불가) — 재호출 시 `delay_mp <= 0`인 타이머가 재예약되지 않아 08:00/09:00 미실행 가능. 하지만 재호출 트리거 코드 경로 미발견.
- asyncio `call_later` 타이머 관리 이슈 (macOS/Python 3.12) — 08:30 정상 실행이므로 단순 플랫폼 버그 단정 어려움.

### 다음 세션 조사 방향 (조사 보고서 기준 — 상세는 `docs/krx_receive_rate_missing_investigation.md` 참조)
1. **DEBUG → INFO 로그 승격 먼저 적용** (⭐⭐⭐ 최우선 전제 작업): 타이머 예약/실행/재호출 추적 가능하도록 로그 승격. 근본 원인 추적의 전제 조건.
2. **08:00, 09:00 타이머만 실패한 근본 원인 추적** (⭐⭐⭐ 최고 중요도, P10/P16 핵심): INFO 승격 후 재발 시 추적.
3. **`schedule_ws_subscribe_timers()` 재호출 경로 전수 추적** (⭐⭐⭐ 최고 중요도): 현재 코드상 재호출 트리거 미발견 — INFO 승격 후 런타임 추적 필요.
4. **타이머 통합(aba9e92) 이전/이후 비교** (⭐ 보통): 과거 09:00 전용 타이머 vs 현재 market_phase 타이머 의존 구조 신뢰성 비교, 회귀 여부 최종 확인.
5. **JIF 폴백 경로 활용 가능성** (⭐ 보통): JIF 이벤트를 market_phase 갱신 폴백으로 활용 가능성 검토 (수정 방안 수립 시).

### 이번 세션 조사로 확정된 사실 (상세는 조사 보고서 참조)
- 09:00 `_on_krx_market_open()` 미호출 확정 (로그 부재)
- `state.market_phase["krx"]` 미갱신 확정 (타이머 미실행)
- `is_nxt_only_window()` True 유지 확정 → KRX 수신률 0/0 고정
- 틱은 정상 수신 중 확정 (09:07 매매 발생)
- 분리 작업(1·2·3단계) 자체는 구독 로직 미변경 확정 (git diff)
- JIF 핸들러는 market_phase 갱신 안 함 확정 (폴백 경로 부재 = P16 위반)
- **08:00 타이머도 미실행 확정** (08:30 타이머가 대신 처리)
- **08:30 타이머 정상 실행 확정** (같은 루프에서 일부만 실패)
- **자동매매 타이머 정상 실행 확정** (같은 루프에서 다른 타이머 시스템은 정상)
- **15분 로그 공백 = 자연스러운 현상 확정** (비거래 구간, 이벤트 루프 블록 아님)
- **타이머 예약 로그 DEBUG 레벨 = 추적 불가 확정** (INFO 승격 필요)
- **07:50~09:00 설정 변경 없음 확정** (PATCH 0건)
- **타이머 핸들 리스트 교체/손실 경로 없음 확정** (코드상)

### 관련 파일
- `backend/app/pipelines/pipeline_compute.py` — `_handle_real_01_tick()` (dirty 세팅), `_sector_recompute_loop_impl()` Phase 2 (수신율 갱신 로그), `_calculate_receive_rate()` (분리 계산)
- `backend/app/services/sector_data_provider.py` — `get_sector_summary_inputs()` (krx_codes/nxt_codes 분리 반환, is_nxt_only_window 분기)
- `backend/app/services/daily_time_scheduler.py` — `is_nxt_only_window()` (market_phase 기반 판단)
- `backend/logs/trading_2026-07-16.log` — 08:30~10:52 구간 로그

### 사용자 승인 완료 항목 (이전 세션)
- **7-1 임계값 게이트 정책 (3단계)**: 옵션 C(시간대별 분기) 승인 — NXT-only 구간은 NXT 수신률만 기준, 정규장은 KRX/NXT 양쪽 모두 임계값 도달 시(AND).
- **7-2 진행 방식**: 분리 진행 (규칙 0-1 준수) 승인.
- **7-3 1단계 시작**: 승인 → 1단계 완료됨.

### 핵심 발견 (사전조사 결과 — 3단계 구현 시 참고)
1. **수신률 단일 집계**: `_received_codes: set[str]` 단일 세트로 KRX/NXT 구분 없이 종목코드만 저장 (pipeline_compute.py:34). 틱 수신 시 FID 9081(KRX='1'/NXT='2') 확인 없이 추가 (line 581). 정규장에서 KRX/NXT 개별 수신 상태를 알 수 없음 (P10/P21 위반).
2. **시간대 SSOT 이미 존재**: `is_nxt_only_window()`, `is_nxt_premarket_window()`, `is_nxt_aftermarket_window()`, `KRX_INACTIVE_PHASES`, `NXT_ACTIVE_PHASES` (daily_time_scheduler.py:46~193) — 새 시간 상수 불필요 (P10/P23).
3. **FID 9081 파서 존재**: `parse_fid9081_exchange()` (engine_ws_parsing.py:181) — '1'=KRX, '2'=NXT, ''=미수신. 단, `_AL` 통합 구독 시 빈 문자열 케이스 가능성 → 3단계 구현 전 실제 틱 로그 확인 권장.
4. **progress-bar.ts 2인스턴스 가능**: `createProgressBar()` 인터페이스로 독립 인스턴스 2개 생성 가능, 개별 `setValue`/`setThreshold` 호출 가능.
5. **임계값 게이트 핵심 로직**: `_sector_threshold_passed` (pipeline_compute.py:41) — 단일 수신률 기준. 분리 시 시간대별 분기 정책(옵션 C, 승인됨) 적용.

### 3단계 구현 계획 (계획서 섹션 3)
- **1단계 (프론트엔드 공통 컴포넌트 추출)**: ✅ 완료 — sector-stock.ts 인라인 카운트 → `createMarketCountRow` 공통 컴포넌트 추출.
- **2단계 (프론트엔드 수신률 분리 배지)**: ✅ 완료 — sector-settings.ts 수신률 표시 KRX/NXT 분리 배지 + 진행 바 2인스턴스. uiStore.receiveRate 타입 {krx, nxt} 분리. binding.ts 단일 수신률 양쪽 동일 매핑.
- **3단계 (백엔드 수신률 분리 집계 + 임계값 게이트)**: `_received_codes` KRX/NXT 2세트 분리, `_calculate_receive_rate()` 시간대별 분리 계산, `_send_receive_rate()` 전송 구조 변경, 임계값 게이트 시간대별 분기 정책(옵션 C, 승인됨). 테스트 전면 수정. **2단계에서 준비한 {krx, nxt} 구조에 분리 데이터 연동**.

### 승인 대기 상태
- 3단계 시작 승인 대기 — 사용자가 "진행해" 등 실행 지시어를 줄 때까지 코드 수정 금지 (AGENTS.md 섹션3 규칙 0).
- 3단계 임계값 게이트 정책은 이미 옵션 C로 승인됨 — 3단계 시작 시 재승인 불필요 (단, 3단계 시작 자체는 별도 승인 필요).
- 3단계는 백엔드 핵심 로직 변경(수신률 집계 + 임계값 게이트) — 백엔드 수정 시 safe-trade 스킬 + 테스트 + 런타임 기동 검증 필수.
- **3차 조사 후 승인 대기**: DEBUG → INFO 로그 승격 적용 (타이머 미실행 원인 추적의 전제 작업). 사용자가 "진행해" 등 실행 지시어를 줄 때까지 코드 수정 금지.

---

## 직전 완료 작업 (이번 세션)

### test_trading.py 테스트 격리 문제 근본 원인 해결 — daily_time_scheduler.py state 참조 패턴 P23 위반 수정

**배경**: 전체 회귀 시 test_trading.py 10개 테스트 실패(단독 실행 시 통과). 사용자 제시 보고 심층 검증 후 근본 원인 확인 — `daily_time_scheduler.py:13`의 모듈 레벨 `from backend.app.services.engine_state import state` 고정 바인딩이 `patch("engine_state.state")` 전파를 차단. 임포트 순서 의존성: `test_daily_time_scheduler.py`가 알파벳 순으로 먼저 수집되어 `daily_time_scheduler` 모듈 로드 → `state` = 실제 EngineState 인스턴스 고정 → 이후 `test_trading.py`의 `patch("engine_state.state")`가 `daily_time_scheduler.state`에 전파 안 됨 → `is_order_blocked_by_time`이 실제 `market_phase`(장개시전/장개시전)를 읽어 `True` 반환 → 시간 차단 사유가 의도한 사유코드보다 먼저 반환.

**근본 원인 판단**: 소스코드 P23(일관성) 위반. `state` 참조 패턴 3가지 혼재 — 패턴 A(모듈 레벨 `from ... import state` 16개 모듈) / 패턴 B(`import engine_state` + `engine_state.state.X` 2개) / 패턴 C(함수 내부 지연 임포트 11개). `trading.py`는 패턴 C로 올바르게 작성되어 있으나 `daily_time_scheduler.py`만 패턴 A를 써서 불일치 발생. 테스트코드는 2차적 책임 — 소스코드 불일치의 증상을 받은 것.

**해결 방식**: 패턴 B(모듈 통째 임포트)로 전환 — `patch("engine_state.state")`가 모든 `engine_state.state` 접근에 전파. P10(SSOT)/P16(살아있는 경로)/P23(일관성)/P24(단순성) 부합. Option C(프록시)는 P24 불필요 추상화 위반으로 기각.

**수정 파일**:
- `backend/app/services/daily_time_scheduler.py`: 라인 13 import 변경 `from backend.app.services.engine_state import state` → `from backend.app.services import engine_state` + `state.X` 참조 113곳 → `engine_state.state.X` 치환(replace_all) + 이중 치환 6곳 수정(`engine_engine_state.state.` → `engine_state.state.` — 주석 내 "engine_state.market_phase"의 "state."가 매칭된 것) + 주석/docstring 내 "state.market_phase" 설명도 P23 일관성 위해 함께 갱신.
- `backend/tests/test_daily_time_scheduler.py`: 150곳 `patch("backend.app.services.daily_time_scheduler.state", mock_state)` → `patch("backend.app.services.engine_state.state", mock_state)` — 패턴 B 전환으로 모듈 `state` 속성 사라져 AttributeError 해결. 같은 근본 원인 해결의 일부.

**검증**:
- 정적: py_compile OK + ruff check OK
- pytest 전체 회귀: **2928 passed, 0 failed**(이전 10 failed → 0)
- 런타임: `python -W error::RuntimeWarning main.py` 기동 성공 — RuntimeWarning 0건 + "타임테이블 빌드 완료 — 11항목" + "타임테이블 스케줄러 시작 — 다음 이벤트 예약 완료" + "장 상태 계산 완료 | KRX: 휴장일, NXT: 휴장일" + 잔존 프로세스 0건
- 프로덕션 동작 100% 보존 — state 싱글톤 속성 변경은 모든 패턴에서 동일 전파, 객체 교체는 테스트에서만 발생

**사용자 체감 변화**: 없음(프로덕션 동작 100% 보존).

**잔존 문제**: 15개 모듈이 여전히 패턴 A(모듈 레벨 `from ... import state`)를 사용 — P23 위반 잔존. 별도 세션에서 단계적 전환 필요 → "미해결 문제" 섹션에 기록.

---

## 직전 완료 작업 (이전 세션)

### 3차 조사: 09:00 타이머 미실행 근본 원인 심층 추적 (문서 업데이트 only — 코드 수정 없음)

**배경**: 2차 조사까지 09:00 타이머 미실행을 확인했으나 근본 원인 미확인. 3차 조사에서 타이머 미실행 패턴을 심층 추적.

**조사 내용**:
- 08:00 타이머도 미실행 확인 (08:29:59에 08:30 타이머가 대신 실행 → 누적 페이즈 변경 감지)
- 08:30 타이머 정상 실행 확인 (같은 이벤트 루프에서 일부만 실패)
- 자동매매 타이머 정상 실행 확인 (08:01:59, 별도 타이머 시스템)
- 15분 로그 공백(08:45~09:00) = 비거래 구간 정상 현상 확인 (이벤트 루프 블록 아님)
- 타이머 예약 로그 DEBUG 레벨 = 추적 불가 확인 (INFO 승격 필요)
- 07:50~09:00 설정 변경(PATCH) 0건 확인
- 타이머 핸들 리스트 교체/손실 경로 코드상 없음 확인
- `schedule_ws_subscribe_timers()` 재호출 트리거 코드 경로 미발견 (DEBUG 로그로 런타임 추적 불가)

**결과**: 근본 원인 여전히 미확인. 단, 08:00/09:00 타이머만 선택적 미실행 패턴 확정. DEBUG → INFO 로그 승격이 원인 특정의 전제 조건임을 확인.

**수정 내용**: 문서 업데이트 only (코드 수정 없음)
- `docs/krx_receive_rate_missing_investigation.md`: 확인된 사실 10건 → 16건 확장 (사실 11~16 추가), 타임라인 08:00 타이머 미실행/08:02 자동매매 타이머 정상 실행 추가, 미확인 항목 3차 조사 결과로 갱신, 다음 세션 조사 방향 INFO 승격 최우선 반영, 수정 방안 2단계 접근(추적 가능성 + 타이머 의존도 감소)으로 재구성
- `HANDOVER.md`: 세션 개요 3세션으로 갱신, 3차 조사 핵심 발견 + 배제된 가능성 + 남은 가능성 추가, 확정된 사실 7건 → 13건 확장

**다음 세션**: DEBUG → INFO 로그 승격 적용 후 재발 시 근본 원인 추적 (승인 대기).

---

## 직전 완료 작업 (이전 세션)

### 3단계: 백엔드 수신률 KRX/NXT 분리 집계 + 임계값 게이트 옵션 C (8개 파일)

**배경**: KRX/NXT 수신률 분리 집계 + 분리 배지 표시 3단계 구현의 최종 단계. 1·2단계에서 프론트엔드 분리 표시 준비 완료. 3단계에서 백엔드 수신률을 단일 집계에서 KRX/NXT 분리 집계로 변경. **FID 9081 틱 분석 방식 대신 `nxt_enable` 필드 기반 단순 방식 채택** (P10 SSOT, P24 단순성 — 틱 분석 불필요, sector-stock.ts 카운트와 동일 기준).

**수정 내용**:
- **`backend/app/pipelines/pipeline_compute.py`**: `_received_codes` 단일 세트 → `_received_codes_krx`/`_received_codes_nxt` 2세트 분리. 틱 수신 시 `is_nxt_enabled(nk_px)`로 분기 (FID 9081 불필요). `_current_receive_rate` → `{krx: {received, total, pct}, nxt: {received, total, pct}}` 분리 구조. `_calculate_receive_rate()` 시간대별 분리 계산 (NXT-only 구간 krx_codes 빈 리스트 → KRX 0/0, NXT만 산출). `_calc_market_receive_rate()` 헬퍼 추출 (단일 시장 수신률 계산, 함수 50줄 이하 유지). `_send_receive_rate()` 분리 구조 전송. `get_current_receive_rate()` 분리 구조 반환 (깊은 복사). Phase 1 임계값 게이트 옵션 C — `is_nxt_only_window()` 분기: NXT-only 구간 NXT 수신률만 기준, 정규장 KRX/NXT 양쪽 모두 도달 시(AND). Phase 2 로그 KRX/NXT 분리 출력.
- **`backend/app/services/sector_data_provider.py`**: `get_sector_summary_inputs()`에 `krx_codes`/`nxt_codes` 분리 반환 추가 (`nxt_enable` 필드 기반, P10 SSOT). `all_codes`는 기존 업종 점수 계산용 유지. `recompute_sector_summary_now()`에서 `compute_full_sector_summary()` 호출 시 `krx_codes`/`nxt_codes` 제외 (dict comprehension 필터).
- **`backend/app/services/engine_sector_confirm.py`**: `_full_recompute()`에서 `compute_full_sector_summary()` 호출 시 `krx_codes`/`nxt_codes` 제외.
- **`backend/app/services/telegram_bot.py`**: 업종 강도 요약 `compute_full_sector_summary()` 호출 시 `krx_codes`/`nxt_codes` 제외.
- **`frontend/src/binding.ts`**: `receive-rate` 이벤트 분리 구조 매핑 (`{krx, nxt}` → `uiStore.receiveRate`). `sector-scores` 이벤트 `receive_rate` 분리 구조 매핑.
- **`frontend/src/stores/uiStore.ts`**: `applyInitialSnapshotUI` 주석 3단계 상태로 갱신 (분리 구조 자동 처리는 2단계에서 이미 준비됨).
- **`backend/tests/test_pipeline_compute.py`**: `TestReceiveRate`/`TestCalculateReceiveRate`/`TestSectorRecomputeLoopImpl`/`TestSectorThresholdGate` 분리 구조로 전면 수정. NXT-only 구간 임계값 통과 테스트, 정규장 AND 정책 KRX만 통과 시 게이트 유지 테스트 추가.
- **`backend/tests/test_engine_snapshot.py`**: `get_current_receive_rate` mock 반환값 분리 구조로 변경.

**자동 연동 (추가 수정 불필요)**:
- `engine_account_notify.py`: `get_current_receive_rate()` 호출 → 분리 구조 자동 연동. `prev_receive_rate` 비교 Python `==` 중첩 dict 자동 처리. `status.receive_rate` 전송 자동 연동.
- `engine_snapshot.py`: `get_current_receive_rate()` 호출 → `receive_rate` 분리 구조 자동 연동.
- `ws.py`: `get_current_receive_rate()` 호출 → `receive_rate` 분리 구조 자동 연동.
- `market_close_pipeline.py`: `_calculate_receive_rate()`/`_send_receive_rate()`/`get_current_receive_rate()` 호출 → 분리 구조 자동 연동.

**유지 대상 (변경 안 함)**:
- 임계값 게이트 플래그 `_sector_threshold_passed` — 단일 플래그 유지 (시간대별 분기 로직만 추가).
- `is_nxt_tick()`/`parse_fid9081_exchange()` — FID 9081 기반 방식은 채택하지 않음 (`nxt_enable` 방식이 더 단순하고 일관됨).

**검증**: pytest 2746개 전체 통과 + 런타임 기동 (`python -W error::RuntimeWarning main.py`) RuntimeWarning 없음 + Traceback/TypeError 없음 + 수신률 분리 로그 정상 출력 ("KRX: 100.0%, NXT: 100.0%, 임계값: 95.0%"). 프론트엔드 빌드 성공 (63 modules, 1.81s). 잔존 프로세스 0건.

**위반 원칙 해결**: P10 (SSOT — `nxt_enable` 필드 단일 소스, FID 9081 중복 관리 없음), P21 (사용자 투명성 — KRX/NXT 개별 수신 상태 표시, 정규장 양쪽 대기 상태 명시), P22 (데이터 정합성 — `market_phase` 기반 파생), P23 (일관성 — sector-stock.ts 카운트와 동일 `nxt_enable` 기준, `is_nxt_only_window()` 재사용), P24 (단순성 — FID 9081 틱 분석 대신 `is_nxt_enabled()` 1회 조회, 함수 50줄 이하).

**수정 후 화면 변화**: 업종순위 설정 ② 영역 — 기존(2단계) KRX/NXT 진행 바 2개가 같은 수치 → KRX/NXT 진행 바 2개가 서로 다른 실제 수치. 정규장에서 "KRX는 80%인데 NXT는 40%"처럼 양쪽 진행도 개별 확인. 업종순위 계산 시작 시점 — 정규장에서 양쪽 모두 임계값 도달 시 시작, 한쪽 늦으면 "대기 중" 상태로 표시.

**영향 범위**: 백엔드 4개 파일 + 프론트엔드 2개 파일 + 테스트 2개 파일. DB 영향 없음.

---

## 직전 완료 작업 (이전 세션)

### 2단계: 프론트엔드 수신률 분리 배지 + 진행 바 2인스턴스 — sector-settings.ts (4개 파일)

**배경**: KRX/NXT 수신률 분리 집계 + 분리 배지 표시 3단계 구현의 2단계. 1단계에서 추출한 `createMarketCountRow` 공통 컴포넌트를 재사용하여 sector-settings.ts의 단일 수신률 표시를 KRX/NXT 분리 배지 + 진행 바 2인스턴스로 변경. 백엔드 분리(3단계) 전 과도기 — 단일 수신률을 양쪽에 동일 매핑.

**수정 내용**:
- **`frontend/src/stores/uiStore.ts`**: `ReceiveRateEntry` 인터페이스 추가. `receiveRate` 타입을 `{krx: ReceiveRateEntry | null; nxt: ReceiveRateEntry | null} | null`로 변경. `applySnapshot`에서 단일/분리 양쪽 호환 매핑 (백엔드가 단일 전송 시 양쪽 동일, 분리 전송 시 그대로 사용).
- **`frontend/src/binding.ts`**: `receive-rate`/`sector-scores` 이벤트에서 단일 수신률을 KRX/NXT 양쪽에 동일 매핑 (`{krx: single, nxt: single}`). 3단계에서 백엔드가 분리 데이터 전송 시 자동 연동.
- **`frontend/src/pages/sector-settings.ts`**: 단일 진행 바 → KRX/NXT 2행 분리 배지 + 진행 바 2인스턴스. `createMarketCountRow` 재사용 (showKrx/showNxt 옵션으로 각 시장 세그먼트만 표시). `marketPhase.is_nxt_only` 기반 활성/비활성 전환 (NXT-only 구간 KRX 회색 opacity 0.3). 상태 라벨 옵션 C 정책(AND) 적용 — 정규장 양쪽 임계값 도달 시 "진행 중", NXT-only 구간은 NXT만 기준. 기존 "수신 N종목 / 미수신 N종목" 단일 표시 제거 → KRX/NXT 각 행에 배지+카운트+진행바 통합.
- **`frontend/src/components/common/market-count-row.ts`**: `_appendNxtSegment`에 `isFirst` 파라미터 추가 — NXT 단독 행(sector-settings NXT 행) 시 좌측 여백(marginLeft 14px) 제거. sector-stock.ts에서는 NXT가 항상 KRX/합계 다음이므로 기존 동작 보존.

**유지 대상 (변경 안 함)**:
- 임계치 입력란(thresholdInput) — 1행 그대로 유지.
- 가산점 슬라이더/매수대상 설정 — ③④⑤ 영향 없음.
- 백엔드 수신률 집계 로직 — 3단계에서 수정.

**검증**: typecheck 통과 + build 성공 (63 modules transformed, exit 0, 2.09s). 브라우저 확인 — 사용자 승인 후 커밋.

**위반 원칙 해결**: P21 (사용자 투명성 — KRX/NXT 개별 수신 상태 표시, NXT-only 구간 KRX 비활성 명시), P23 (일관성 — 1단계 공통 컴포넌트 재사용, 진행 바 기존 컴포넌트 2인스턴스).

**수정 후 화면 변화**: 업종순위 설정 ② 영역 — 기존 단일 "수신 N종목 / 미수신 N종목" + 진행 바 1개 → KRX/NXT 2행 분리 배지(KRX: N종목 / NXT▲: N종목) + 진행 바 2개(각각 % 표시 + 임계치 마커). 정규장 양쪽 활성, NXT-only 구간 KRX 회색. 2단계에서는 양쪽 같은 수치 (3단계에서 개별 수치 연동).

**영향 범위**: 프론트엔드 4개 파일. 백엔드/DB 영향 없음.

---

## 직전 완료 작업 (이전 세션)

### 1단계: 프론트엔드 공통 컴포넌트 추출 — sector-stock.ts KRX/NXT/코스피/코스닥 카운트 (2개 파일)

### 보유종목 테이블 수수료·세금 컬럼 삭제 + 매수금액 라벨 병기 (2개 파일)

**배경**: 보유종목 테이블의 "세금" 컬럼이 모든 종목에서 0으로 표시됨. 조사 결과: (1) 세금은 매도 시에만 부과되므로 보유 중인 종목은 구조상 항상 0 (테스트 모드: `_position_from_lots()` 하드코딩 0, 실전 모드: 키움 kt00018 응답에 tax 필드 미존재). (2) "수수료" 컬럼은 매수금액(buy_amt = buy_amount + total_fee)에 이미 포함된 비용의 중복 표시. (3) "매수금액" 라벨만으로는 수수료 포함 여부를 사용자가 알 수 없어 P21(사용자 투명성) 위반 소지.

**근본 원인**: `frontend/src/pages/sell-position.ts:51-62` — COLUMNS 배열에 세금·수수료 컬럼 2개가 의미 없이/중복 표시되고, 매수금액 라벨이 수수료 포함 여부를 명시하지 않음.

**수정 내용**:
- **`frontend/src/pages/sell-position.ts`**: COLUMNS 배열에서 "수수료"(total_fee)·"세금"(tax) 컬럼 정의 2개 제거. "매수금액" 라벨 → "매수금액(수수료 포함)" 병기.
- **`frontend/src/types/index.ts`**: Position 인터페이스에서 `total_fee?`, `tax?` 옵션 필드 2개 제거 (sell-position.ts에서만 사용되었으므로).

**유지 대상 (변경 안 함)**:
- `table-config.ts`의 `tax`/`fee` ColumnType — `profit-shared.ts`(매도 이력 테이블)에서 사용 중.
- 백엔드 `engine_account_notify.py:542`의 `_MIN_POSITION_KEYS` 포함 `tax`/`total_fee` — 데이터 전송 구조 (프론트 미사용 필드는 무시됨, SSOT 위반 아님).
- `trades` 테이블 DB 스키마의 `fee`, `tax` 컬럼 — 매도 이력/수익 분석에 사용되므로 변경 금지.

**검증**: `npm run build` 성공 (62 modules transformed, exit 0). 잔존 참조 확인: `total_fee` 프론트엔드에서 완전 제거, `r.tax`/`d.tax` 잔존은 profit-shared.ts·canvas-profit-chart.ts의 매도 이력 기반 데이터로 정상 유지 대상.

**위반 원칙 해결**: P21 (사용자 투명성 — 매수금액에 수수료 포함 여부 명시, 의미 없는 0 표시 컬럼 제거로 오인 방지), P24 (단순성 — 중복·의미 없는 컬럼 제거).

**수정 후 화면 변화**: 보유종목 테이블에서 "수수료"·"세금" 컬럼 2개 사라짐. 컬럼 순서 `... 매수금액(수수료 포함) | 평가손익 ...`로 변경. 매수금액 값 자체는 기존과 동일(수수료 포함 총매입가).

**영향 범위**: 프론트엔드 2개 파일. 백엔드/DB 영향 없음.

---

## 해결 완료: P-NEW-1 직접 타이핑 시 슬라이더/저장값 범위 불일치 (2026-07-16)

**이슈 ID**: P-NEW-1 (신규 등록 2026-07-16, 해결 2026-07-16)
**상태**: 해결 완료 — `input` 이벤트 실시간 clamp 적용. 코드·빌드 검증 완료. 화면 검증 대기(사용자가 업종순위 설정 패널 ④ 가산점 입력창에 `150`·`-200` 타이핑 시 즉시 `+100`/`-100` 보정되는지 확인하면 완전 종결).

**문제**: `createNumInput` 공통 컴포넌트에서 사용자가 입력창에 직접 타이핑할 때 `min`/`max` 범위 clamp가 적용되지 않아, 짝이 되는 슬라이더(`-100~+100`)와 저장값이 불일치. 예: 가산점 입력창에 `150` 또는 `-200`을 직접 타이핑하면 그대로 `onChange`로 저장되지만 슬라이더는 `-100~+100` 범위.

**근본 원인**: `frontend/src/components/common/setting-row.ts:224-228` — `input` 이벤트 핸들러가 `Number(raw) || 0`로 변환만 하고 `min`/`max` clamp 없이 `onChange` 전달. 반면 ▲/▼ 버튼(235-236줄)은 `Math.min(maxVal, ...)` / `Math.max(minVal, ...)` clamp 적용. 두 경로(직접 타이핑 vs 버튼)의 허용 범위가 분리 관리됨.

**위반 원칙**: P10 (SSOT — 값 허용 범위가 슬라이더·버튼·직접 타이핑 3경로에서 단일 지정되지 않고 분리 관리).

**수정 이력 (롤백 포함 — AGENTS.md 섹션3 규칙 0-3 준수)**:
1. **1차 시도 (커밋 `0dee1e6`, 롤백됨)**: `blur` 시점 clamp 적용. "타이핑 중간값 잘림 방지"를 사유로 포커스 잃을 때 보정.
2. **롤백 사유**: 사용자 지적 — "바깥 클릭을 해야 되돌아가는 건 표준 아키텍처가 아닐 것 같다". 실제 문제 분석:
   - blur 전에 저장 버튼 누르면 범위 밖 값이 그대로 저장됨 (input 이벤트에서 clamp 없이 onChange 호출하므로).
   - 타이핑 중 입력창과 슬라이더가 불일치 상태로 방치됨.
   - "타이핑 중간값 잘림"은 실제로 미미함 — `-100` 입력 과정(`-`, `-1`, `-10`, `-100`)은 전부 범위 내, `150` 입력 시 `150` 순간 보정되는 것이 자연스러운 즉시 피드백.
   - 숫자 입력창 + 슬라이더 짝에서는 input 이벤트 실시간 clamp가 표준 패턴.
3. **2차 적용 (현재)**: `blur` 리스너 제거 → `input` 이벤트 핸들러에 실시간 clamp 추가. 범위 밖 값 입력 즉시 보정 + 슬라이더와 항상 일치 + 저장값 항상 유효.

**수정 내용** (2026-07-16 2차 적용):
- `frontend/src/components/common/setting-row.ts:224-238` — `input` 이벤트 핸들러에서 `Number(raw) || 0` 후 `Math.min(maxVal, Math.max(minVal, parsed))`로 clamp. `Math.round(... * 100) / 100`로 소수점 2자리 반올림 (▲/▼ 버튼과 동일 패턴, P23 일관성). 보정된 경우(`clamped !== parsed`)에만 `input.value` 갱신 — 범위 내 타이핑 시 커서 위치 보존.
- `blur` 리스너 제거 (1차 시도 코드 롤백).
- 기존 호출부 보존: `min`/`max` 미지정 시 기본값 `0`/`Infinity` → 기존 동작 보존. 가산점 3개 입력창만 `min:-100, max:100`으로 실제 clamp 적용.

**검증**: `npm run build` 성공 (62 modules transformed, exit 0, 1.97s). 화면 검증 대기 — 사용자가 업종순위 설정 패널 ④ 가산점 입력창에 `150` 또는 `-200` 타이핑 즉시 `+100`/`-100`으로 보정되는지, 슬라이더와 일치하는지, 범위 내 타이핑 시 커서 튐 현상 없는지 확인하면 완전 종결.

**수정 후 화면 변화**: 가산점 입력창에 범위 밖 값(`150`, `-200` 등)을 직접 타이핑하면 즉시 `+100`/`-100`으로 보정 (바깥 클릭 불필요). 슬라이더·▲/▼ 버튼·직접 타이핑 3경로 모두 `-100~+100` 단일 범위로 통일.

**영향 범위**: 프론트엔드 1개 파일(`setting-row.ts`). `createNumInput` 사용 모든 호출부(buy-settings 8곳, sell-settings 4곳, sector-settings 6곳)에 동일 적용 — 기본값 `min:0, max:Infinity`이므로 기존 동작 보존.

---

## 다음 세션 진행 대기: 실시간 체결 불가 시간대 주문 일시 중단

### 계획서 경로
- **`docs/plan_order_suspension_by_time.md`** — 구현 계획서 (사전조사 결과 + 구현 Step 1~10 + 세션 분할 + 사용자 결정 항목)

### 핵심 발견 (사전조사 결과)
1. **현재 차단 누락 구간**: `is_krx_after_hours()`가 "시가 동시호가"(08:50~09:00), "종가 동시호가"(15:20~15:30)를 차단하지 않음.
2. **매도 경로 시간 체크 전무**: `execute_sell()`에 시간 체크가 전혀 없어 동시호가 시간대에 손절/익절 매도 주문이 들어갈 수 있음.
3. **매수 경로 P16 위반 소지**: 시간 체크가 `buy_order_executor.py` 외부에만 있고 `execute_buy()` 내부에는 없어 수동 매수(force_buy) 시 우회 가능.
4. **기존 자산 재사용 가능**: `KRX_INACTIVE_PHASES` frozenset에 이미 "시가 동시호가", "종가 동시호가" 포함 — 새 시간 상수 불필요 (P10/P23).

### 사용자 결정 필요 항목 (계획서 섹션 3)
다음 세션 시작 전 사용자가 결정해야 할 5가지:
1. **3-1 NXT 종목 처리**: A) 전부 차단 / B) KRX·NXT 분리 차단 (15:40~16:00 NXT 애프터마켓 매매 허용 여부)
2. **3-2 시간외 거래 구간**: 장전/장후 시간외 시장가 주문 차단 포함 여부
3. **3-3 ±5초 여유 적용**: A) phase 산정 / B) 주문 체크 시점 (추천 B)
4. **3-4 수동 매수 차단**: 동시호가 시간대 수동 매수도 차단 여부
5. **3-5 매도 차단**: 동시호가 시간대 매도도 차단 여부 (권장: 차단)

### 구현 세션 분할 (계획서 섹션 6)
- 세션 1: Step 1 (시간대 차단 판별 함수) + Step 4 (설정 키 추가)
- 세션 2: Step 2 (execute_buy 내부 체크) + Step 3 (execute_sell 내부 체크)
- 세션 3: Step 5 (WS 이벤트) + Step 8 (바인딩)
- 세션 4: Step 6 (설정 토글) + Step 7 (헤더 칩)

### 승인 대기 상태
- 사용자가 5가지 결정 항목을 확정하고 "진행해" 등 실행 지시어를 줄 때까지 코드 수정 금지 (AGENTS.md 섹션3 규칙 0).
- 거래 로직 수정이므로 safe-trade 스킬 필수 (P15 단일 주문 경로, P16 살아있는 경로, P18 테스트모드 동등성).

---

## 직전 완료 작업 (이전 세션)

### 실시간 시세 0/- 혼용 근본 해결 — DB NULL→None 보존 통일 (3개 파일)

**문제**: NXT 장마감(20:00) 후 ~ 확정 다운로드(20:40) 전 구간에서 업종별 종목 시세 테이블과 보유종목 테이블의 실시간 필드가 0과 -로 혼용 표시됨.

**근본 원인**: `load_master_stocks_table()`에서 DB NULL을 로드할 때 필드마다 변환 방식이 불일치 — `cur_price`/`change`는 `int(... or 0)` 폴백으로 0 변환, `change_rate`/`trade_amount`는 None 보존. 이로 인해 같은 "데이터 없음" 상태가 0과 None 두 값으로 분리 관리됨 (P10 SSOT 위반, P20 폴백 금지 위반, P23 일관성 위반).

**수정 내용**:
1. `backend/app/db/stock_tables.py` 348-349줄: `cur_price`/`change`의 `int(... or 0)` 폴백 제거 → `int(...) if ... is not None else None` 패턴으로 `change_rate`/`trade_amount`와 통일
2. `backend/app/services/market_close_pipeline.py` 825-840줄: 신규 종목 초기값 `cur_price: 0, change: 0, change_rate: 0.0, trade_amount: 0` → `None` 4개 통일
3. `backend/tests/test_stock_tables.py`: NULL 보존 테스트 추가 (`test_load_null_realtime_fields_preserved`)

**검증**: 백엔드 테스트 264개 통과 + 런타임 기동 (RuntimeWarning 에러 없음, 1340종목 로드, 99ms 기동) + 잔존 프로세스 0건.

**위반 원칙**: P10 (SSOT — "데이터 없음" 단일 기준 None 통일), P20 (폴백 금지 — or 0 폴백 제거), P23 (일관성 — 4개 실시간 필드 동일 패턴).

**수정 후 화면 변화**: 20:00~20:40 구간에서 모든 실시간 필드가 동일하게 "-"로 표시 (현재가·대비의 "0"이 "-"로 통일). 20:40 이후 확정 데이터 채워지면 실제 값 표시.

---

## 직전 완료 작업 (이전 세션)

### 상단 요약 배지 위계 분리 + 색상/라벨 일관성 개선 (2개 파일)

**배경**: 사용자 보고 "보유주식 평가금액 숫자가 빨간색". 조사 결과 공통 배지 컴포넌트(`badge.ts`)의 `createBadge`에서 숫자 기본색이 `COLOR.up`(빨강)으로 고정되어, 색상을 따로 지정하지 않은 모든 배지(평가금액·주문가능금액·일일매수금액·동시보유한도) 숫자가 빨강으로 표시되던 문제. 추가로 라벨·숫자·단위가 같은 크기·같은 색으로 붙어 있어 시각적 위계가 없었고, 보유종목 3개 배지 라벨 길이가 제각각이라 숫자 위치가 정렬되지 않아 일관성 부족.

**수정 내용**:
- **`frontend/src/components/common/badge.ts`** (공통 배지 컴포넌트):
  - 숫자 기본색 `COLOR.up`(빨강) → `COLOR.neutral`(`#333`, 검정) 근본 해결 — 단순 수치가 빨강으로 표시되던 문제 해결.
  - 위계 분리: 숫자 13px 굵게(600, 중심), 라벨 13px 회색, 단위 11px 회색(보조), 상태 13px 회색.
  - 요소 간 gap 16px + `justifyContent: center` 중앙 정렬 + `alignItems: baseline` 하단 맞춤.
  - `updateBadge`에 `statusNumber`/`statusLabel` 옵션 추가 — "(N종목)"에서 N만 파란색(`COLOR.down`) 강조, 나머지 회색. 괄호 안 공백 추가 "( 4 종목 )".
- **`frontend/src/pages/sell-position.ts`** (보유종목 페이지):
  - 평가금액 배지: `statusText` → `statusNumber`/`statusLabel` 옵션으로 변경 (종목 수 파란색 강조).
  - 라벨 자세하게 통일: "보유주식 평가금액" → "보유주식 평가금액 합계", "평가손익" → "보유주식 평가손익 합계", "수익률" → "보유주식 평가수익률" (3개 라벨 길이 비슷 → 숫자 위치 정렬 → 일관성).

**검증 결과**:
- typecheck 통과, 빌드 성공 (642ms~2.09s).
- 브라우저 확인: 사용자가 "훨씬 좋아보인다" 확인.

**영향 범위**: 프론트엔드 2개 파일. 백엔드/DB 영향 없음.
- 보유종목 페이지 배지 3개 + 매수후보 페이지 배지 3개에 일괄 적용 (공통 컴포넌트 수정).
- 손익/수익률 배지 색상은 기존대로 유지 (이미 색상 따로 지정 → 영향 없음).

**아키텍처 원칙 부합**:
- P10 (SSOT): 잘못된 기본색(`COLOR.up`)을 단일 진실 소스에서 수정 — 모든 배지에 일관 적용.
- P20 (폴백 금지): 빨강을 폴백으로 덮지 않고 기본값 자체를 근본 수정.
- P21 (사용자 투명성): 단순 수치(평가금액 등)가 손익색(빨강)으로 오인되던 것을 해결.
- P23 (일관성): 공통 배지 컴포넌트 1곳 수정으로 2페이지 6배지 일관성 확보. 라벨 길이 통일로 숫자 위치 정렬.

## 직전 완료 작업 (이전 세션)

### 실시간 자동 연결 토글 라벨 + 설명 개선 (1개 파일)

**배경**: 기존 라벨 "실시간 연결"은 토글 역할(자동 연결 ON/OFF)이 직관적으로 드러나지 않았고, 설명 텍스트 "실시간 데이터 자동 연결 스위치 — OFF면 수동 연결만 가능"은 ON 시 언제 연결/해제되는지 안내가 없어 P21(사용자 투명성) 미흡. 사용자 제안으로 라벨 + 설명 모두 동작을 정확히 표기하도록 개선.

**수정 내용**:
- **`frontend/src/pages/general-settings.ts`**:
  - 라벨 "실시간 연결" → "실시간 자동 연결" (토글이 자동 연결 스위치임을 직관적으로 표시).
  - 설명 "실시간 데이터 자동 연결 스위치 — OFF면 수동 연결만 가능" → "ON: 거래일 오전 8시 자동 연결 → 오후 8시 자동 해제 (주말·공휴일 제외) / OFF: 자동 연결 안 함" (백엔드 NXT_ACTIVE_PHASES 08:00~20:00 기준 정확 표기).

**검증 결과**:
- typecheck 통과, 빌드 성공 (743ms).

**영향 범위**: 프론트엔드 1개 파일 2줄. 백엔드/DB 영향 없음.

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): 토글 ON 시 동작 시간을 사용자에게 명시 — 강화.
- P23 (일관성): 기존 설명 텍스트 패턴(createDescText) 유지.

### 기동 시 자동 다운로드 스킵 로직 무력화 근본 해결 — 기준일 SSOT 통일 (3개 파일)

**배경**: 사용자 보고 "앱 기동 시마다 오늘 이미 다운로드한 데이터가 있어도 무조건 다시 자동 다운로드 실행". 조사 결과, 토글 커밋(`b3d2611`)이 아닌 같은 날 새벽 머지된 `f50ce9f`가 원인. `f50ce9f`는 5일봉 미확정 당일 행 유입 차단을 위해 다운로드 파이프라인의 기준일을 `get_kst_today_str()`(달력 오늘)에서 `get_previous_trading_day_str(get_current_trading_day_str())`(가장 최근 확정된 거래일 = 직전 거래일)로 변경. 이에 따라 `master_stocks_table.date`에 직전 거래일이 저장되게 되었으나, 기동 스킵 로직(`retry_pipeline_catchup_after_bootstrap`)은 여전히 `get_current_trading_day_str()`(달력 오늘)과 비교하여 항상 불일치 → 무조건 다운로드 트리거. P10(SSOT) 위반 — 다운로드 파이프라인·수동 확인 API는 직전 거래일 기준으로 변경되었으나 기동 스킵 로직만 누락.

**수정 내용**:
- **`backend/app/services/daily_time_scheduler.py`** (`retry_pipeline_catchup_after_bootstrap`):
  - 비교 기준일을 `get_current_trading_day_str()`(달력 오늘)에서 `get_previous_trading_day_str(get_current_trading_day_str())`(가장 최근 확정된 거래일)로 변경 — 다운로드 파이프라인과 동일 기준(P10 SSOT).
  - 변수명 `_current_trading_day` → `_latest_confirmed_day`, `_cache_is_today` → `_cache_is_fresh`로 변경 (의미 반영, P23 용어 일관성).
  - 로그 메시지 "현재 거래일" → "최근 확정 거래일" 3곳 변경.
  - 기준일 변경 이유를 설명하는 주석 추가 (다운로드 파이프라인·수동 API와 동일 기준 P10 SSOT).
- **`backend/app/services/market_close_pipeline.py`** (`execute_unified_rolling_and_save` 주석):
  - `f50ce9f`에서 작성된 주석 "장 후 실행 시 date=오늘(07-15 확정)… 스킵 판단이 정확하게 동작함"이 코드 동작과 불일치(실제로는 항상 직전 거래일 저장)하던 것을 정정 (P21 사용자 투명성 + 주석/코드 일치).
- **`backend/tests/test_daily_time_scheduler.py`** (`TestRetryPipelineCatchup`):
  - `test_disconnected_cache_outdated_triggers_fetch`: 캐시 date `20250105` → `20250104`로 변경. (is_trading_day=True 모킹 시 current 20250106의 직전 거래일=20250105이므로, 캐시 20250105는 이제 fresh가 되어 트리거하지 않음. outdated 케이스를 만들려면 20250104 필요.)
  - `test_disconnected_cache_today_sets_done` → `test_disconnected_cache_fresh_sets_done`로 메서드명 변경 + 캐시 date `20250106` → `20250105`로 변경. (캐시 20250105 = 최근 확정 거래일 20250105 → 일치 → 스킵. "today"가 아닌 "fresh"로 의미 정정.)
  - 각 테스트에 캐시 date와 최근 확정 거래일의 관계를 설명하는 주석 추가.

**검증 결과**:
- pytest 전체 2742개 통과 (5.88s). test_daily_time_scheduler 4개 + test_market_close_pipeline 188개 포함.
- 런타임 기동 정상 (`-W error::RuntimeWarning` 모드, RuntimeWarning 0건, 서버 정상 기동 + Uvicorn 리스닝 확인).
- 런타임 로그로 스킵 동작 확인: `23:10:52 [스케줄] 단절 구간 기동 — 캐시(20260715) = 최근 확정 거래일(20260715) 확정 다운로드 시각 경과 (스킵)` — 23:10 기동 시 current_trading_day=20260716(20:00 이후라 다음 거래일), previous=20260715, 캐시=20260715 → 일치 → 스킵. 수정 전이라면 캐시(20260715) ≠ 현재거래일(20260716)로 무조건 다운로드 트리거했을 것.
- 잔존 프로세스 0건 + lock 파일 정리 완료.

**영향 범위**: 백엔드 2개 파일 + 테스트 1개 파일. 프론트엔드/DB 영향 없음(스키마 변경 없음, 백업 불필요). 매수/매도/업종 점수/수신률 로직에 영향 없음 — 기동 시 다운로드 스킵 여부 판단만 수정.

**아키텍처 원칙 부합**:
- P10 (SSOT): 다운로드 파이프라인·수동 확인 API·기동 스킵 로직 3곳 모두 동일 기준일(가장 최근 확정된 거래일) 사용으로 통일. 기존에는 기동 스킵 로직만 달력 오늘 기준이어서 SSOT 위반.
- P16 (살아있는 경로): 스킵 로직이 실제 기동 실행 경로에서 호출됨 확인 (`engine_cache._load_caches_preboot` → `retry_pipeline_catchup_after_bootstrap`).
- P20 (폴백 금지): 스킵이 안 된다고 다른 곳에서 억지로 막지 않음 — 기준일 비교 1곳만 수정하여 근본 해결.
- P21 (사용자 투명성): `f50ce9f`의 불일치 주석을 정정하여 주석/코드 일치 복원. 사용자 모르게 스킵 로직이 망가져 있던 것을 규명+해결.
- P23 (일관성): 변수명/로그 메시지를 실제 의미("최근 확정 거래일")에 맞게 정정.

## 직전 완료 작업 (이전 세션)

### Connector dead code 제거 — _realtime_enabled / _auto_trade_enabled 2계열 (6개 파일)

**배경**: 사전조사 중 `set_realtime_enabled()`/`is_realtime_enabled()`가 Connector에 플래그를 저장하기만 하고 프로덕션 코드에서 한 곳도 읽지 않는 dead code(P16 위반)임을 발견. 동일 패턴의 `_auto_trade_enabled` 계열도 dead code. 실제 의사결정은 `ws_subscribe_on`(WS 연결 게이트, engine_loop.py:304)과 `time_scheduler_on`(자동매매 타이머)이 담당하므로 Connector 플래그는 중복 저장이었음. 사용자 승인 하에 2계열 모두 제거.

**수정 내용**:
- **`backend/app/core/broker_connector.py`**: 기본 구현 스텁 `set_auto_trade_enabled`/`set_realtime_enabled` 2개 메서드 제거.
- **`backend/app/core/kiwoom_connector.py`**: `_realtime_enabled`/`_auto_trade_enabled` 필드 2개 + `is_realtime_enabled`/`set_realtime_enabled`/`is_auto_trade_enabled`/`set_auto_trade_enabled` 메서드 4개 제거.
- **`backend/app/core/ls_connector.py`**: 동일하게 필드 2개 + 메서드 4개 제거.
- **`backend/app/services/engine_service.py`**: `set_realtime_enabled()` 호출 1곳 + `set_auto_trade_enabled()` 호출 1곳 제거. 주석 번호 재정렬 (3)→(2), (4)→(3)).
- **`backend/tests/test_kiwoom_connector.py`**: `_realtime_enabled`/`_auto_trade_enabled` assertion 2개 + `test_realtime_get_set`/`test_auto_trade_get_set` 테스트 메서드 2개 제거.
- **`backend/tests/test_ls_connector.py`**: assertion 2개 + `TestLsConnectorSettings` 클래스 전체(테스트 4개) 제거.

**검증 결과**:
- 잔존 참조 0건 확인 (grep 전체 코드베이스).
- pytest 전체 2742개 통과 (0.70s).
- 런타임 기동 정상 (`-W error::RuntimeWarning` 모드, 에러/Traceback/RuntimeWarning 없음, 앱 시작 완료 + Uvicorn 리스닝 확인).
- 잔존 프로세스 0건 + lock 파일 정리 완료.

**영향 범위**: 백엔드 4개 파일 + 테스트 2개 파일. 프론트엔드/DB 영향 없음. 실시간 연결 토글(ws_subscribe_on) 및 자동매매 토글(time_scheduler_on) 동작 변경 없음 — 실제 게이트는 engine_loop.py의 `is_ws_subscribe_window()`와 daily_time_scheduler의 타이머가 담당하므로.

**아키텍처 원칙 부합**:
- P16 (살아있는 경로): 저장된 플래그를 아무도 읽지 않는 dead code 제거 → 강화.
- P24 (단순성): Connector에서 의미 없는 필드/메서드 2쌍씩 감소 → 강화.
- P10 (SSOT): 실제 의사결정은 ws_subscribe_on/time_scheduler_on 단일 소스가 담당, Connector 플래그는 중복 저장이었음 → 제거로 강화.

## 직전 완료 작업 (이전 세션)

### 1일봉차트 자동다운로드 토글 추가 + 라벨 개선 (2개 파일) — 커밋 `b3d2611`

**배경**: 일반설정 API 설정 탭의 "1일봉챠트 시세 다운로드" 행에 시간 입력란만 있고 ON/OFF 토글이 없어, 사용자가 자동 다운로드를 끄거나 켤 수 없었음. 백엔드에는 이미 `scheduler_market_close_on` 토글 설정값과 게이트 로직(`market_close_pipeline.py:1003`)이 구현되어 있었으나, 프론트엔드에 UI가 없어 P21(사용자 투명성) 위반 상태. 사용자 제안으로 토글 추가 + 라벨에 "자동다운로드" 명시.

**수정 내용**:
- **`frontend/src/pages/general-settings.ts`**:
  - 모듈 상태에 `confirmedDlToggle` 참조 추가.
  - `renderApiSettingsTab`의 confirmedDlRow 행 구조 변경: 라벨 왼쪽, 오른쪽에 [시간 슬롯 + 토글] 배치 (기존 "실시간 연결" 행 패턴과 동일 정렬).
  - 라벨 "1일봉챠트 시세 다운로드" → "1일봉차트 자동다운로드" (챠트→차트 오타 수정 + "자동다운로드" 추가).
  - 토글 ON/OFF 시 `scheduler_market_close_on` 즉시 저장 + 시간 슬롯 활성화/비활성화 (`setDisabled`).
  - 저장 실패 시 롤백 처리 (토글 + 시간 슬롯 상태 복원).
  - 설명 문구 "장마감 후 확정 시세 다운로드 시간" → "장마감 후 자동 다운로드 시간 (기본값 20:40) — OFF 시 수동 다운로드만 가능".
  - `syncFromSettings`에 토글 상태 동기화 + 시간 슬롯 활성화/비활성화 연동 추가.
  - `setDisabled` import 추가 (`ui-styles`).
- **`backend/app/services/engine_service.py`**:
  - `_WS_SCHEDULE_KEYS`에 `scheduler_market_close_on` 추가 — 토글 변경 시 타이머 즉시 재예약.

**검증 결과**:
- typecheck 통과, 빌드 성공.
- 백엔드 테스트 186개 전체 통과 (test_engine_settings + test_daily_time_scheduler).
- 백엔드 런타임 기동 정상 (포트 8000).

**영향 범위**: 프론트엔드 1개 파일 + 백엔드 1개 파일. 새 설정 키 추가 없이 기존 `scheduler_market_close_on` 재사용 (P10 SSOT 준수).

**아키텍처 원칙 부합**:
- P10 (SSOT): 새 키 만들지 않고 기존 `scheduler_market_close_on` 재사용.
- P16 (살아있는 경로): 이미 게이트가 동작 중, UI만 추가하여 호출 경로 연결.
- P21 (사용자 투명성): 백엔드 토글을 UI에 노출하여 사용자가 자동 다운로드 제어 가능.
- P23 (일관성): 기존 행 정렬 패턴(실시간 연결, 플래시 효과 행)과 동일 구조 유지.
- P24 (단순성): 백엔드 변경 1줄, 프론트엔드 UI만 추가.

## 직전 완료 작업 (이전 세션)

### 발견 문제 기록 의무에 '개선점' 추가 + 롤백 사유 기록 의무 신설 — AGENTS.md 규칙 9 + 5개 스킬 (6개 파일)

**배경**: AGENTS.md 규칙 9 "작업 중 발견 문제 기록 의무"는 위반/오류/버그/dead code/폴백 패턴 중심이며, problem-solve 스킬에는 이미 "개선점"이 언급되어 있어 양쪽 불일치 (P23 위반 소지). 사용자 제안으로 "아키텍처 원칙에 부합하는 더 나은 구조(개선점)"를 기록 대상에 추가.

**수정 내용**:
- **AGENTS.md 규칙 9 본문**: "아키텍처 위반(P원칙), 오류, 잠재적 버그, dead code, 폴백 패턴, 아키텍처 원칙에 부합하는 더 나은 구조(개선점) 등"으로 확장.
- **AGENTS.md 규칙 9 하위 항목 신설 "개선점 인정 기준 (P24 준수)"**: 주관적 취향이 아닌 객관적 근거 있는 것만 — (a) 특정 P원칙에 부합하여 정량적으로 더 단순/일관/정합 (b) 기존 공통 자산 재사용으로 중복 제거 (c) 명확한 중복·dead code·폴백 회피 가능. 근거 없는 "더 좋을 것 같음"은 기록 대상 아님.
- **AGENTS.md 규칙 9 기록 형식**: "위반 원칙 번호" → "위반/부합 원칙 번호(개선점의 경우)" 확장. 세션 종료 보고 문구 "N건의 신규 문제" → "N건의 신규 문제/개선점" 확장.
- **5개 스킬 파일** (problem-solve, backend-fix, frontend-fix, safe-trade, db-backup) "작업 중 발견 문제 기록 의무" 섹션: 동일 문구로 통일. problem-solve는 95행 기존 "개선점" 단어에 조건 명시 보완 (객관적 근거, P24 준수, AGENTS.md 상세 참조).

**검증 결과**: grep으로 6개 파일 동일 문구 확인 완료. 구 문구("폴백 패턴 등") 잔존 0건.

**영향 범위**: 문서 파일 6개만 변경. 코드 변경 없음.

**아키텍처 원칙 부합**:
- P10 (SSOT): AGENTS.md 규칙 9가 단일 진실 소스, 5개 스킬은 "상세 규칙은 AGENTS.md 섹션4 규칙 9 참조" 역참조.
- P23 (일관성): 6개 파일 동일 문구, problem-solve 기존 "개선점"과 AGENTS.md 본문 정합.
- P24 (단순성): 개선점 인정 기준으로 남발 방지, 규칙 비대화 회피.

### 롤백 사유 기록 의무 신설 + 롤백으로 증상 덮기 금지 — AGENTS.md 규칙 0-3 + problem-solve 스킬 (2개 파일)

**배경**: AGENTS.md 규칙 0-3 "사용자 승인 없는 롤백 절대 금지"는 승인 자체는 담당하나, 승인 후 **사유 기록** (git commit 메시지, HANDOVER.md)은 명시되어 있지 않았음. 나중에 git log나 HANDOVER.md만 보는 사람이 "왜 이전 상태로 되돌아갔지?" 오인하는 빈틈. 또한 problem-solve 스킬에 롤백과 근본 해결의 관계 미명시.

**수정 내용**:
- **AGENTS.md 규칙 0-3 하위 항목 신설 "롤백 사유 기록 의무 (강제)"**: 사용자 승인받아 롤백 진행한 경우, (1) git commit 메시지에 사유·되돌린 대상·영향 범위 상세 기록 ("revert" 한 단어로 끝내지 않음), (2) HANDOVER.md "직전 완료 작업" 섹션에 롤백 내용과 사유 명시.
- **problem-solve/SKILL.md 7항 "근본 원인 식별"**: "롤백으로 증상 덮기 금지" 추가 — 롤백 후에도 근본 원인이 남아있으면 재발. 롤백이 적절한 경우(잘못된 변경 되돌림, 승인받은 경우)와 부적절한 경우(증상 회피용) 구분 명시. AGENTS.md 규칙 0-3 역참조.

**검증 결과**: grep으로 4개 스킬(problem-solve/backend-fix/frontend-fix/safe-trade) "기존 로직 롤백 여부 확인" 항목이 "AGENTS.md 섹션3 규칙 0-3 준수" 역참조 확인 → 0-3에 하위 항목 추가하면 자동 전파 구조 정상.

**영향 범위**: 문서 파일 2개만 변경. 코드 변경 없음. 4개 스킬은 역참조 구조로 개별 수정 불필요 (P10 SSOT 유지).

**아키텍처 원칙 부합**:
- P10 (SSOT): AGENTS.md 규칙 0-3이 단일 진실 소스, 4개 스킬은 역참조로 자동 전파.
- P23 (일관성): problem-solve "롤백으로 증상 덮기 금지"가 AGENTS.md 0-3 역참조로 정합.
- P24 (단순성): 이미 존재하는 규칙 1·2(승인 없는 롤백 금지, 로직 변경 보고 의무)는 중복 추가하지 않고, 빈틈(기록 의무)만 보완.

## 직전 완료 작업 (이전 세션)

### 수익상세페이지 상단 카드 3→4 확장 + 기간별 색상 차별화 + 하단 통계 연동 (3개 파일) — 커밋 `09629b8`

**배경**: 수익상세페이지 상단 요약 카드가 당일/당월/누적 3개이며, 선택 시 모두 동일 파랑 색상이라 어떤 기간을 보고 있는지 시각적 구분이 안 됨. 수익현황(overview) 차트에는 이미 '직전' 버튼이 있어 두 페이지 간 빠른 범위 옵션이 불일치. 사용자 제안으로 '직전' 카드 추가 + 4카드 색상 차별화 + 하단 6개 통계 카드 색상 연동.

**수정 내용**:
- **`frontend/src/components/common/ui-styles.ts`**: 기간 구분 전용 색 3종 추가 (기존 의미 색 success/warning/up/kosdaq과 충돌 회피). `periodPrev`(#0097a7 청록)/`periodPrevBg`(#e0f7fa), `periodMonth`(#7b1fa2 보라)/`periodMonthBg`(#f3e5f5), `periodTotal`(#455a64 슬레이트)/`periodTotalBg`(#eceff1). 당일은 기존 `down`/`downBg` 재사용.
- **`frontend/src/pages/profit-shared.ts`**: `SummaryCardEls` 인터페이스에 `prevPnlEl`/`prevRateEl`/`prevCard` 추가. `SummaryCardCallbacks`에 `onPrevClick` 추가. `createSummaryCards` 3카드→4카드 확장 (CARD_TITLES = 당일/직전/당월/누적). `updateSummaryCards`에 직전 손익 계산 추가 — dailySummary에서 오늘보다 이전 날짜 중 가장 최근 항목 추출 (O(n) 단일 패스, 백엔드 추가 호출 없이 기존 데이터에서 파생).
- **`frontend/src/pages/profit-detail.ts`**:
  - `SelectedView` 타입에 `'prev'` 추가. `loadProfitDetailView` validViews 및 from/to 검증 조건에 'prev' 포함.
  - `applyCardStyle`을 카드별 보더/배경 색상 받도록 변경. `updateCardSelection`이 4카드 각각 해당 색상 적용.
  - 신규 `updateStatCardSelection()` — 하단 6개 통계 카드 색상을 상단 선택 기간과 동일 색으로 연동. `selectedView === null`(수동 날짜) 시 회색(borderLight/surfaceLight) 복귀.
  - `onPrevClick` 핸들러 — `api.getPrevTradingDay()` 비동기 조회 후 `filterByDate(prev.date)`. await 중 다른 카드 클릭 시 덮어쓰기 방지 가드(`if (selectedView !== 'prev') return`) 추가.
  - 하단 통계 카드 생성 시 `statCardEls` 배열에 push하여 색상 연동 대상 관리. unmount에서 초기화.
  - `api` import 추가 (`../api/client`).

**검증 결과**:
- typecheck 통과, 빌드 성공 (62 modules).
- 테스트 108개 전체 통과 (기존 실패 없음, profit 관련 테스트는 없으나 전체 회귀 확인).

**영향 범위**: 프론트엔드 3개 파일. 백엔드 변경 없음 (기존 `getPrevTradingDay` API 재사용). profit-overview는 `createSummaryCards` 미사용이라 영향 없음. 공유 함수 `createSummaryCards`의 실제 사용처는 profit-detail 1곳.

**아키텍처 원칙 부합**:
- P10 (SSOT): 공유 함수 1곳에서 4카드 관리, 직전 손익은 기존 dailySummary에서 파생 (중복 저장 금지).
- P21 (사용자 투명성): 하단 통계 색상 연동으로 "현재 보는 기간" 상단/하단 양쪽 시각화, 수동 날짜 시 회색 복귀로 상태 명확.
- P23 (일관성): overview 차트 '직전' 버튼과 detail '직전' 카드 일치, 기존 의미 색 충돌 회피한 신규 기간 구분 색 추가.
- P24 (단순성): 보더+옅은 배경으로 손익 텍스트 색(빨강/파랑)과 충돌 회피, 직전 손익 O(n) 단일 패스 추출.

## 다음 세션 작업
- **최우선: P-001 Step 2 진행 — 사용자 승인 후**
  - Step 1 완료. `engine_radar.py:73-77` 틱 수신 폴백 제거 완료.
  - Step 2 (세션 2): `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + `_has_any_realtime_data` 검증. 영향 범위 중간.
  - Step 3 (세션 3): `sector_calculator.py:69,78` 업종 점수 폴백 제거. 영향 범위 넓음.
  - 각 Step 시작 시 사용자 명시적 승인 필요.
- **다운로드 완료 시간 표시 (제안2)**: 1일봉/5일봉 다운로드 버튼 우측에 가장 최근 다운로드 완료 시간 표시. 백엔드 신규 기능 필요 — 현재 DB에 다운로드 완료 시간 저장소 없음 (`master_stocks_table.date`/`stock_5d_bars.dt`는 거래일이지 다운로드 시각 아님). 사전조사: 다운로드 파이프라인 완료 지점, 저장소 설계(system_state_cache 또는 신규 테이블), P10 SSOT/P22 정합성 점검 후 설계 제안.
- 실전모드 보관 기준(`RETENTION_TRADING_DAYS_REAL = 90`) 추후 논의 — 사용자가 "증권사 서버에 데이터가 다 있으니 추후 논의"라고 명시.
- 기존 발견 문제: `notify_raw_real_data` dead code (P16) 별도 검토 필요 시 사용자 지시.
- 사용자 UI 확인 후 추가 컬럼 너비 조정이 필요하면 해당 페이지만 override로 진행.

## 현재 상태

### 1. 조사 범위
| 화면 | 파일 | 종류 |
|---|---|---|
| 매수 후보 | `frontend/src/pages/buy-target.ts` | DataTable |
| 보유 종목 | `frontend/src/pages/sell-position.ts` | DataTable |
| 수익 상세(매수/매도/드릴다운) | `frontend/src/pages/profit-detail.ts`, `frontend/src/pages/profit-shared.ts` | DataTable |
| 종목 상세 5일 데이터 | `frontend/src/pages/stock-detail.ts` | DataTable |
| 업종별 종목 시세 | `frontend/src/pages/sector-stock.ts` | DataTable |
| 업종 분류(검색/업종목록/종목목록) | `frontend/src/pages/stock-classification.ts` | DataTable |
| 일반 설정 명령어 안내 | `frontend/src/pages/general-settings.ts` | DataTable |
| 업종 순위 리스트 | `frontend/src/pages/sector-ranking-list.ts` | HTML div/flex |
| 수익 현황 업종별 종목 | `frontend/src/pages/profit-overview.ts` | HTML div/flex |

### 2. 핵심 공통 자산
- `frontend/src/components/common/table-config.ts` — `ColumnType`, `COLUMN_WIDTH`
- `frontend/src/components/common/data-table.ts` — `DataTable`, `ColumnDef`, `createColumnWidthManager`
- `frontend/src/components/common/auto-width.ts` — `estimateTextWidth`, `computeColWidths`, `widthsToPercentages`, `KOREAN_SCALE`
- `frontend/src/components/common/ui-styles.ts` — 셀 스타일, 공통 컬럼 팩토리

### 3. DB 데이터 특성
- `master_stocks_table.name`: 최대 14자, 평균 4.8자, 99% ≤ 9자
- `master_stocks_table.sector`: 최대 13자, 평균 6.8자
- `master_stocks_table.code`: 6자
- `stock_5d_bars.trade_amount`: 최대 33,936,947 (8자리)
- `stock_5d_bars.high_price`: 최대 3,015,000 (7자리)
- `trades.price`: 최대 1,858,500 (7자리)
- `trades.qty`: 최대 532 (3자리)
- `trades.total_amt`: 최대 5,128,949원
- `trades.fee`: 최대 771원
- `trades.tax`: 최대 10,280원
- `trades.realized_pnl`: 최대 157,700원
- `trades.pnl_rate`: 최대 5.47%

### 4. 해결된 문제
- `종목명` 컬럼이 전체 테이블에서 과도하게 넓게 표시되던 문제.
  - 원인: `auto-width.ts`의 `estimateTextWidth`가 한글 폭을 `fontSize * 0.75 * 1.8`로 과대 추정하고, `ColumnDef`의 `minWidth`/`maxWidth`가 페이지별로 제각각이며, `종목명`의 `maxWidth`가 200으로 큼.
  - 조치: `KOREAN_SCALE` 1.4 조정, `COLUMN_WIDTH` 표준 상수 적용, `종목명` `maxWidth` 140으로 축소.
- 숫자 컬럼(`현재가`, `거래대금(억)`, `대비`, `체결강도` 등)이 `maxWidth` 80~95에 묶여 있던 문제.
  - 조치: `ColumnType`별 표준 `minWidth`/`maxWidth` 적용, `type` 필드 추가로 `createColumnWidthManager`가 자동 적용.
- 매수후보/업종별종목실시간시세에서 숫자 컬럼이 과도하게 넓고 종목명이 좁은 문제.
  - 조치: 페이지 override로 숫자 컬럼 축소, 종목명 확대.
- 프순매 컬럼 단위 표기 누락 (P23 일관성 위반).
  - 조치: "프순매" → "프.순.매(백)" 라벨 변경, 너비 조정.
- 호가잔량비 글자와 숫자가 붙어 있어 행 간 비교 어려움 + % 단위 반복 표시.
  - 조치: flex container로 좌/우 분리 정렬, %는 컬럼명으로 이동, 보합 케이스 추가.

## 문제 이력 (해결 완료 + 미해결)

> 각 이슈 헤더에 "해결 완료" 또는 미해결 상태가 명시되어 있습니다. 미해결은 P-001 1건만 잔존.

### 기존 테스트 실패: test_trading.py 테스트 격리 문제 (전체 회귀 시 10개 실패, 단독 실행 시 통과) → 해결 완료 (2026-07-18)

**발견일**: 2026-07-18 (DB 테이블 스케줄러 3세션 전체 회귀 테스트 실행 중 최초 발견 / 차순위 매수 시도 2세션 전체 회귀에서 9개 추가 발견)

**현상**: `backend/tests/test_trading.py`의 10개 테스트가 전체 회귀 실행 시에만 실패. 단독 실행 시 모두 통과. 순서 의존성/상태 공유 문제로 추정.
- `TestExecuteBuyGates::test_rebuy_block_disabled` (기존 실패 — DB 테이블 스케줄러 3세션에서 발견)
- `TestExecuteBuyReasonCodes::test_rebuy_block_today_returns_rebuy_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_open_order_returns_open_order_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_signal_interval_returns_signal_interval_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_max_holding_returns_max_holding_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_buy_amt_zero_returns_buy_amt_zero_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_price_zero_returns_price_zero_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_rise_guard_returns_rise_guard_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_strength_guard_returns_strength_guard_reason` (1세션 추가 테스트)
- `TestExecuteBuyReasonCodes::test_risk_circuit_returns_risk_circuit_reason` (1세션 추가 테스트)

**근본 원인 (해결 완료 2026-07-18)**: `daily_time_scheduler.py:13`의 모듈 레벨 `from backend.app.services.engine_state import state` 고정 바인딩이 `patch("engine_state.state")` 전파를 차단. 임포트 순서 의존성: `test_daily_time_scheduler.py`가 알파벳 순으로 먼저 수집되어 `daily_time_scheduler` 모듈 로드 → `state` = 실제 EngineState 인스턴스 고정 → 이후 `test_trading.py`의 `patch("engine_state.state")`가 `daily_time_scheduler.state`에 전파 안 됨 → `is_order_blocked_by_time`이 실제 `market_phase`(장개시전/장개시전)를 읽어 `True` 반환 → 시간 차단 사유가 의도한 사유코드보다 먼저 반환되어 10개 테스트 실패.

**해결 내역 (2026-07-18)**: `daily_time_scheduler.py` 패턴 A(모듈 레벨 `from ... import state`) → 패턴 B(`import engine_state` + `engine_state.state.X`) 전환. `test_daily_time_scheduler.py`의 patch 대상도 `engine_state.state`로 변경(150곳). 전체 회귀 2928 passed, 0 failed. 상세는 "직전 완료 작업 (이번 세션)" 섹션 참조.

**위반 원칙**: P23(일관성) — `state` 참조 패턴 3가지 혼재. 해결 완료.

---

### P-NEW-5: 15개 모듈 state 참조 패턴 A(모듈 레벨 고정 바인딩) 잔존 — P23 일관성 위반 (해결 완료 — 16/16 전환 완료 2026-07-18 8세션)

**이슈 ID**: P-NEW-5 (신규 등록 2026-07-18, test_trading.py 테스트 격리 문제 근본 원인 해결 중 발견 / 단계적 전환 진행 중 2026-07-18 / 해결 완료 2026-07-18 8세션)

**참고 (2026-07-18 6세션 정정)**: 이슈 제목 "15개 모듈"이나 실제 추적 목록은 16개 항목(1-16번). 이전 세션들에서 "잔존 N개" 기재 시 1개 단위 누락 발생 — 본 세션에서 정정 완료. 진행률은 목록 기준 11/16.

**현상**: `from backend.app.services.engine_state import state`를 모듈 레벨에서 사용하는 15개 모듈이 잔존. `daily_time_scheduler.py`는 본 세션에서 패턴 B로 전환 완료했으나, 나머지 15개 모듈은 여전히 패턴 A를 사용. 이들 모두 동일한 잠재적 테스트 격리 문제를 가짐. 현재 실패가 발생하지 않는 이유는 해당 모듈들을 간접 호출하는 테스트에서 `patch("engine_state.state")`가 아닌 다른 patch 방식을 사용하거나, 해당 경로가 테스트에서 호출되지 않기 때문. 향후 테스트 추가 시 동일한 문제 재발 가능.

**진행 상황 (2026-07-18 1세션)**: 15개 중 2개 전환 완료 — `engine_service.py`(state.X 7곳), `engine_strategy_core.py`(state.X 4곳). 정적 검증 OK + 전체 회귀 2928 passed + 런타임 기동 OK. 잔존 13개 모듈 + `engine_ws_dispatch.py` dead import 제거는 다음 세션에서 진행.

**진행 상황 (2026-07-18 2세션)**: 15개 중 3개 전환 완료 — `engine_ws_dispatch.py`(state.X 13줄 14개 발생 + dead import 제거). 이미 패턴 B 사용 중이던 8줄은 변경 불필요. 테스트 patch 경로 동반 수정: test_engine_ws_dispatch.py 12곳 + test_pipeline_compute.py 4곳. 테스트 patch 패턴 3가지 카테고리 수정(Category 1: `engine_state._notify_reg_ack` 개별 patch 4곳 / Category 2: `engine_state` 전체 patch 제거 2곳 / Category 3: `engine_state.state` patch + `mock_es.state.X` → `mock_state.X` 6곳). 정적 검증 OK + 전체 회귀 2928 passed + 런타임 기동 OK. 잔존 12개 모듈은 다음 세션에서 진행.

**진행 상황 (2026-07-18 3세션)**: 15개 중 5개 전환 완료 — `engine_sector_confirm.py`(state.X 29곳 + 함수 내 지역 import 1곳 제거) + `sector_data_provider.py`(state.X 22곳 + 함수 내 지역 import 2곳 제거). 주석 3곳(engine_sector_confirm.py:376, sector_data_provider.py:73/187)은 규칙(주석 무단 수정 금지)에 따라 원본 유지. 테스트 patch 경로 동반 수정: test_engine_sector_confirm.py 16곳 + test_sector_data_provider.py 7곳. 정적 검증 OK + 전체 회귀 2928 passed + 런타임 기동 OK("업종 재계산 완료" — engine_sector_confirm.py 경로 정상 동작 확인). 잔존 10개 모듈은 다음 세션에서 진행.

**진행 상황 (2026-07-18 4세션)**: 15개 중 7개 전환 완료 — `engine_radar.py`(state.X 5곳, 전부 master_stocks_cache) + `market_close_pipeline.py`(state.X 54곳 — master_stocks_cache/integrated_system_settings_cache/connector_manager/active_connector/broker_tokens/confirmed_refresh_running_confirmed/confirmed_refresh_running_5d/confirmed_refresh_message/latest_filter_summary_meta). line 807, 814 `system_state_cache`는 DB 테이블 이름이라 변경 대상 아님. 함수 내 지역 import 없음. 테스트 patch 경로 동반 수정: test_market_close_pipeline.py 45곳(`patch("...market_close_pipeline.state", mock_state)` → `patch("...engine_state.state", mock_state)`). test_engine_radar.py는 존재하지 않아 테스트 수정 불필요. 정적 검증 OK + test_market_close_pipeline.py 57 passed + 전체 회귀 2928 passed + 런타임 기동 OK("업종 재계산 완료" — engine_radar.py 경로 정상 동작 확인). 잔존 8개 모듈은 다음 세션에서 진행.

**진행 상황 (2026-07-18 5세션)**: 15개 중 9개 전환 완료 — `engine_snapshot.py`(state.X 11곳 — master_stocks_cache/integrated_system_settings_cache/bootstrap_event/preboot_cache_loaded/snapshot_history/positions/sector_summary_cache) + `ws_subscribe_control.py`(state.X 16곳 — quote_subscribed/ws_connection_status/integrated_system_settings_cache/ws_account_subscribed/master_stocks_cache/connector_manager/login_ok/active_connector + line 221 cleanup_stale_subscriptions 내 지역 import 1곳 제거, P24 단순성). line 24 주석("상태는 engine_state.py의 state에 통합 관리")은 원본 유지(주석 무단 수정 금지 규칙). 테스트 patch 경로 동반 수정: test_engine_snapshot.py 9곳(`patch("...engine_snapshot.state")` → `patch("...engine_state.state")` 단순 치환). test_ws_subscribe_control.py는 존재하지 않아 테스트 수정 불필요. 정적 검증 OK + test_engine_snapshot.py 19 passed + 전체 회귀 2928 passed + 런타임 기동 OK("업종 재계산 완료" — engine_snapshot.py / ws_subscribe_control.py 경로 정상 동작 확인). 잔존 7개 모듈(리스트 10-16번)은 다음 세션에서 진행.

**진행 상황 (2026-07-18 6세션)**: 11개 전환 완료 — `engine_ws_reg.py`(state.X 38곳 — master_stocks_cache/connector_manager/active_connector/login_ok/integrated_system_settings_cache/ws_account_subscribed) + `engine_loop.py`(state.X 60곳 — broker_tokens/integrated_system_settings_cache/login_ok/connector_manager/active_connector/token_ready_event/master_stocks_cache/running/engine_loop_ref/preboot_cache_loaded/preboot_ready_event/account_rest_lock/broker_spec/access_token/auto_trade/engine_stop_event/ws_window_changed_event/broker_rest_apis). `engine_loop.py` line 144 지역 import(`_notify_reg_ack`)는 `state`가 아닌 다른 심볼이므로 유지. line 46 docstring + line 160 주석은 규칙(주석 무단 수정 금지)에 따라 원본 유지. 테스트 patch 경로 동반 수정: test_engine_loop.py 26곳(`patch.object(engine_loop, "state", mock_state)` → `patch.object(engine_state, "state", mock_state)` + `from backend.app.services import engine_loop, engine_state` import 추가). test_engine_ws_reg.py는 순수 payload 빌더만 검증하여 테스트 수정 불필요. 정적 검증 OK + test_engine_loop.py + test_engine_ws_reg.py 56 passed + 전체 회귀 2928 passed + 런타임 기동 OK("업종 재계산 완료" + "LS증권 연결 완료 (테스트모드=True)" — engine_loop.py / engine_ws_reg.py 경로 정상 동작 확인). 잔존 5개 모듈(리스트 12-16번)은 다음 세션에서 진행.

**진행 상황 (2026-07-18 7세션)**: 13개 전환 완료 — `engine_lifecycle.py`(state.X 57곳 — engine_task/engine_user_id/running/integrated_system_settings_cache/engine_stop_event/ws_account_subscribed/quote_subscribed/ws_connection_status/account_rest_bootstrapped/login_ok/access_token/account_snapshot/broker_rest_totals/positions/snapshot_history/auto_trade/data_ready_event/bootstrap_event/sector_summary_ready_event/ws_reg_pipeline_done/master_stocks_cache/sector_summary_cache/connector_manager/active_connector/broker_tokens/engine_loop_ref) + `engine_ws.py`(state.X 50곳 — connector_manager/active_connector/reg_seq_lock/reg_ack_event/reg_ack_return_code/REG_POST_ACK_GAP_SEC/ws_reg_pipeline_done/master_stocks_cache/login_ok/integrated_system_settings_cache). `engine_lifecycle.py` line 173 주석("# broker별 실제 연결 상태 (state.broker_tokens 기반)")은 규칙(주석 무단 수정 금지)에 따라 원본 유지. `engine_ws.py` line 256, 268 함수 내 지역 import 2곳(subscribe_dynamic_data/unsubscribe_dynamic_data) 제거(P24 단순성 — 모듈 레벨 import로 충분). 테스트 patch 경로 동반 수정: test_engine_ws.py 28곳 단일 patch `patch("...engine_ws.state", ...)` → `patch("...engine_state.state", ...)` 치환 + 5곳 이중 patch(line 452/462/473/484/494) `engine_ws.state` patch 라인 제거 후 `engine_state.state` 단일 patch로 승격 + line 54 docstring "engine_ws.state 기본 mock" → "engine_state.state 기본 mock" 갱신(테스트 docstring은 코드와 일치해야 함 — Code Removal Rules). test_engine_lifecycle.py는 존재하지 않아 테스트 수정 불필요. 정적 검증 OK + test_engine_ws.py 42 passed + 전체 회귀 2928 passed + 런타임 기동 OK("업종 재계산 완료" + "LS증권 연결 완료 (테스트모드=True)" — engine_lifecycle.py / engine_ws.py 경로 정상 동작 확인). 잔존 3개 모듈(리스트 14-16번)은 다음 세션에서 진행.

**진행 상황 (2026-07-18 8세션 — 완료)**: 16개 전환 완료 — `engine_config.py`(state.X 12곳 — integrated_system_settings_cache/engine_user_id/running/on_filter_settings_changed) + `engine_bootstrap.py`(state.X 14곳 — ws_reg_pipeline_done/integrated_system_settings_cache/account_rest_bootstrapped/positions/master_stocks_cache/connector_manager/active_connector/sector_summary_cache) + `engine_cache.py`(state.X 14곳 — master_stocks_cache/integrated_system_settings_cache/preboot_cache_loaded/last_realtime_reset_date/bootstrap_event/data_ready_event/sector_summary_ready_event). `engine_config.py` line 25 주석 및 line 48 docstring의 "state.integrated_system_settings_cache" 표현은 규칙(주석 무단 수정 금지)에 따라 원본 유지. 함수 내 지역 import 3개 파일 모두 없음. 테스트 patch 경로 동반 수정: test_engine_bootstrap.py 9곳 `patch("...engine_bootstrap.state", mock_state)` → `patch("...engine_state.state", mock_state)` 치환 + test_engine_cache.py 19곳 `patch.object(engine_cache, "state", mock_state)` → `patch.object(engine_state, "state", mock_state)` 치환 + 파일 상단 `from backend.app.services import engine_state` import 추가. test_engine_config.py는 존재하지 않아 테스트 수정 불필요. 정적 검증 OK + test_engine_bootstrap.py + test_engine_cache.py 28 passed + 전체 회귀 2928 passed + 런타임 기동 OK("선행 캐시 로드 완료" — engine_cache.py 경로 정상 동작 확인 + "업종 재계산 완료" + "LS증권 연결 완료 (테스트모드=True)"). **P-NEW-5 이슈 해결 완료 — 16/16 모듈 전환 완료.**

**잔존 모듈 0개** (패턴 A — 모듈 레벨 `from backend.app.services.engine_state import state`):
1. ~~`engine_service.py:7`~~ ✅ 전환 완료 (2026-07-18 1세션)
2. ~~`engine_strategy_core.py:10`~~ ✅ 전환 완료 (2026-07-18 1세션)
3. ~~`engine_ws_dispatch.py:9`~~ ✅ 전환 완료 (2026-07-18 2세션 — dead import 제거 포함)
4. ~~`engine_sector_confirm.py:13`~~ ✅ 전환 완료 (2026-07-18 3세션)
5. ~~`sector_data_provider.py:8`~~ ✅ 전환 완료 (2026-07-18 3세션)
6. ~~`engine_radar.py:8`~~ ✅ 전환 완료 (2026-07-18 4세션)
7. ~~`market_close_pipeline.py:26`~~ ✅ 전환 완료 (2026-07-18 4세션)
8. ~~`engine_snapshot.py:12`~~ ✅ 전환 완료 (2026-07-18 5세션)
9. ~~`ws_subscribe_control.py:19`~~ ✅ 전환 완료 (2026-07-18 5세션 — line 221 지역 import 제거 포함)
10. ~~`engine_ws_reg.py:15`~~ ✅ 전환 완료 (2026-07-18 6세션)
11. ~~`engine_loop.py:18`~~ ✅ 전환 완료 (2026-07-18 6세션 — line 144 `_notify_reg_ack` 지역 import 유지)
12. ~~`engine_lifecycle.py:15`~~ ✅ 전환 완료 (2026-07-18 7세션 — line 173 주석 원본 유지)
13. ~~`engine_ws.py:10`~~ ✅ 전환 완료 (2026-07-18 7세션 — line 256/268 지역 import 제거 포함)
14. ~~`engine_config.py:11`~~ ✅ 전환 완료 (2026-07-18 8세션 — line 25 주석·line 48 docstring 원본 유지)
15. ~~`engine_bootstrap.py:10`~~ ✅ 전환 완료 (2026-07-18 8세션)
16. ~~`engine_cache.py:10`~~ ✅ 전환 완료 (2026-07-18 8세션)

**별도**: ~~`engine_ws_dispatch.py:9`~~ ✅ dead import 제거 완료 (2026-07-18 2세션)

**위반 원칙**: P23(일관성) — `state` 참조 패턴 3가지 혼재(패턴 A 8개 / 패턴 B 9개(daily_time_scheduler, engine_service, engine_strategy_core, engine_ws_dispatch, engine_sector_confirm, sector_data_provider, engine_radar, market_close_pipeline 포함) / 패턴 C 11개). P16(살아있는 경로) 정신 위반 — 모듈 로드 시점 고정 바인딩은 객체 교체 시 죽은 참조가 됨(프로덕션에서는 교체 안 일어나므로 미드러나나, 테스트 동작 입증 시 죽은 참조). **→ 해결 완료 (2026-07-18 8세션) — 16개 모듈 전부 패턴 B로 통일.**

**수정 방안 (제안)**: 각 모듈을 패턴 B(`from backend.app.services import engine_state` + `engine_state.state.X`)로 전환. 세션당 1단계 원칙(규칙 0-1)에 따라 세션당 1~2개 모듈씩 단계적 전환 권장. 각 전환 시 전체 회귀 + 런타임 기동 검증 필수. 테스트 patch 경로 동반 수정 필요 시 `patch("...engine_state.state")`로 통일 (P23 일관성). `engine_ws_dispatch.py` 2세션에서 발견: 테스트가 `patch("...engine_ws_dispatch.engine_state")`로 전체 모듈을 mock하는 패턴은 패턴 B 전환 시 깨짐 — `engine_state.state`가 MagicMock 속성이 되어 `mock_state`와 불일치. 해결: `engine_state._notify_reg_ack` 개별 patch 또는 `engine_state.state` patch로 대체. 3세션에서 확인: `engine_sector_confirm.py`/`sector_data_provider.py`는 단순 `patch("...module.state")` 패턴만 사용 → `patch("...engine_state.state")` 단순 치환으로 해결. 4세션에서 확인: `market_close_pipeline.py`도 동일 단순 패턴 → 45곳 단순 치환으로 해결. `engine_radar.py`는 테스트 patch 0건(test_engine_radar.py 없음). 함수 내 지역 import는 모듈 레벨 import로 충분하므로 제거. **→ 해결 완료 (2026-07-18 8세션).**

**조치**: 본 세션에서는 `engine_config.py` + `engine_bootstrap.py` + `engine_cache.py` 3개 전환 — P-NEW-5 완료.

### P-NEW-4: force_buy dead parameter — execute_buy 파라미터/분기/docstring 잔존 (P16 살아있는 경로, P23 일관성) → 해결 완료 (2026-07-17)

**이슈 ID**: P-NEW-4 (신규 등록 2026-07-17, 시장가 주문 중단 시간대 게이트 설계서 작성 중 발견 / 해결 2026-07-17)

**현상**: `trading.py execute_buy(force_buy: bool = False)` 파라미터가 존재하나, `force_buy=True`로 호출하는 코드가 백엔드·프론트엔드·테스트 전체에 0건. 유일한 실제 호출부는 `buy_order_executor.py:172`이며 `force_buy=False` 고정. "매수대기 수동 매수"라는 용어는 `trading.py` docstring/주석(98, 132행)에만 잔존하며, 프론트엔드에 수동 매수 UI 없음 (순수 자동매매 앱).

**근본 원인**: 과거에 수동 매수 기능이 존재했으나 제거되고, 파라미터와 관련 분기·docstring만 남은 것으로 추정. git history에서 `force_buy` 파라미터 자체는 Initial commit부터 존재.

**위반 원칙**:
- **P16 (살아있는 경로)**: 호출되지 않는 분기(`if not settings["is_auto"] and not force_buy`)가 잔존 — dead code 소지.
- **P23 (일관성)**: docstring이 실제 동작과 불일치 ("매수대기 수동 매수 전용"이라 했으나 해당 기능 없음).

**해결 내역 (2026-07-17)**:
- `trading.py`: `execute_buy()`·`_execute_buy_locked()` 시그니처에서 `force_buy` 파라미터 제거 + docstring "force_buy=True: 매수대기 수동 매수 전용" 제거 + 자동매매 게이트 분기 `if not settings["is_auto"] and not force_buy:` → `if not settings["is_auto"]:` 단순화 + 주석 "force_buy(매수대기 수동 매수) 시에만 우회" → "자동매매 비활성화 시 주문 생략" + 로그 `(강제매수=%s, 출처=자동신호)` → `(출처=자동신호)` (강제매수 필드 제거)
- `buy_order_executor.py:172`: `force_buy=False` 인자 제거
- `ARCHITECTURE.md:625`: "자동매매 게이트 (force_buy 시 우회)" → "자동매매 게이트 (자동매매 비활성화 시 차단)" 갱신
- `docs/architecture_order_time_guard_design.md` 섹션 8: "본 작업 범위 외" → "해결 완료 (2026-07-17 별도 세션)" 상태 갱신
- **동작 변화 없음**: 기존 `force_buy` 항상 False → `not force_buy` 항상 True → `if not settings["is_auto"]`와 동일. 자동매매 게이트 동작 100% 보존.
- **검증**: pytest 64개 전부 통과 (test_trading.py 31 + test_buy_order_executor.py 33) + 런타임 기동 정상 (테스트모드, RuntimeWarning 0건, execute_buy 임포트 OK)

**영향 범위**: `backend/app/services/trading.py` (시그니처 2곳 + 분기 1곳 + docstring/주석/로그 3곳) + `backend/app/services/buy_order_executor.py:172` (인자 제거) + `ARCHITECTURE.md:625` + `docs/architecture_order_time_guard_design.md` 섹션 8. 테스트 파일은 force_buy 인자 없이 호출하거나 AsyncMock 사용 → 영향 없음 확인.

**참조**: 시장가 주문 중단 시간대 게이트 설계서(`docs/architecture_order_time_guard_design.md`) 섹션 8에서 본 작업 범위 외로 명시적으로 분리했던 이슈.

---

### P-NEW-3: 주문가능금액 부족 상태에서 매수 실행 → max(0,...) 클램핑 인플레이션 (P22 데이터 정합성) → 해결 완료 (2026-07-17)

**이슈 ID**: P-NEW-3 (신규 등록 2026-07-16, 해결 2026-07-17)

**현상**: 테스트모드 계좌 현황에서 주문가능금액(28,372,133원)이 누적투자금(10,000,000원)의 2.8배로 표시됨. 손해 보는 중(미실현 평가손익 마이너스)인데 주문가능 금액이 늘어난 모순 관찰.

**근본 원인 (해결 완료)**: TOCTOU(Time-of-Check to Time-of-Use) 경쟁 상태. `trading.py execute_buy` line 284(check_buy_power 검증) ↔ `dry_run.py fake_fill_event` line 170(0.1초 지연 후 on_buy_fill 차감) 사이에 다른 매수의 fake_fill_event가 _orderable을 차감 → on_buy_fill 시점에 _orderable 부족 → `max(0, _orderable - cost)` 클램핑 9회 발생 → 약 156만원 인플레이션. 글로벌 매수 락 부재가 근본 원인 (종목별 락만 존재, 다른 종목 동시 매수 허용).

**수정 완료 (A+B 조합)**:
- A (사전 차감): `settlement_engine.reserve_buy_power` 신규 (check + 즉시 차감 원자적 수행) + `release_buy_power` (롤백). `dry_run._apply_buy`에 `pre_reserved` 플래그 추가 (True 시 중복 차감 생략).
- B (글로벌 매수 락): `AutoTradeManager._buy_lock` (asyncio.Lock) 신규. execute_buy를 래퍼로 분리, 동시 매수 순차 처리.

**검증**: pytest 169개 통과 + 런타임 기동 RuntimeWarning 0건 + 잔존 프로세스 0건.

**위반 원칙**: P22 (데이터 정합성) — 해결 완료.

---

### P-001: 실시간 데이터 미수신 시 0 폴백 → 수신률 100% 왜곡 + 업종 점수 왜곡

**현상**: HD현대 등 종목의 실시간 데이터 필드가 0 또는 "-"로 표시되는데, 업종순위 계산 임계치 수신률은 100%로 표시됨. 사용자 지적: "0을 데이터로 인식해서 왜곡".

**근본 원인 (2단계 연쇄, 코드 경로로 모두 확정)**

#### 원인 A — 미수신 데이터를 0으로 폴백 저장 (P20 폴백 금지 위반)
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/services/engine_ws_parsing.py:155-156` | `parse_change_rate_to_percent(None)` → `0.0` 반환. 빈 문자열·"0"도 모두 `0.0` 반환. |
| `backend/app/services/engine_account_rest.py:21-22` | `_parse_float_loose(None)` → `0.0` 반환. |
| `backend/app/services/engine_radar.py:75` | 틱 수신 시 FID 12(등락률) 값이 비어 있으면 `parse_change_rate_to_percent`를 거쳐 `entry["change_rate"] = 0.0` 저장. None이 아닌 0.0 저장. |
| `backend/app/services/engine_radar.py:77` | 틱 수신 시 FID 14(거래대금) 값이 비어 있으면 `_parse_float_loose`를 거쳐 `entry["trade_amount"] = 0` 저장. None이 아닌 0 저장. |

#### 원인 B — 수신률 계산이 0과 None을 구분하지 않음 (P22 데이터 정합성 위반)
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/pipelines/pipeline_compute.py:97` | `_has_any_realtime_data()`가 `entry.get(f) is not None`로만 판정. `0.0`/`0`은 None이 아니므로 "수신됨"으로 카운트. |
| `backend/app/pipelines/pipeline_compute.py:118-126` | `received_count`에 0으로 폴백된 종목이 포함됨. 결과: 실제 수신되지 않은 종목이 수신률 100%에 포함. |

**수신률 100%가 업종순위 계산 시작 조건과 연결되는 경로 (확정)**
1. `pipeline_compute.py:704` — Phase 1 루프에서 `_calculate_receive_rate()` 호출.
2. `pipeline_compute.py:706` — `_current_receive_rate["pct"]`를 `current_pct`로 읽음.
3. `pipeline_compute.py:716` — `if current_pct >= threshold_pct:` 수신률이 임계값 이상이면 통과.
4. `pipeline_compute.py:721` — `mark_sector_threshold_passed()` 호출 → 이후 sector-scores 전송 허용.
5. `pipeline_compute.py:722` — `request_sector_recompute(None)` 호출 → 콜드 스타트 1회 전체 재계산 트리거.
6. `engine_account_notify.py:273-276` — `is_sector_threshold_passed()`가 False면 sector-scores 전송 차단, True면 허용.

**확정된 사실**: 0으로 폴백된 종목이 수신률을 100%로 끌어올리고, 100%가 임계값 통과 조건이 되어 업종순위 계산이 시작됨. 실제로는 데이터가 부족해도 임계값이 통과됨.

**0이 섞인 데이터가 업종 점수 계산에 미치는 영향 (확정)**
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/domain/sector_calculator.py:69` | `change_rate = float(detail.get("change_rate", 0) or 0)` — 0이 유효 데이터로 StockScore에 저장. |
| `backend/app/domain/sector_calculator.py:78` | `ta = int(detail.get("trade_amount", 0) or 0)` — 0이 유효 데이터로 StockScore에 저장. |
| `backend/app/domain/sector_calculator.py:129` | `raw_rise_count = sum(1 for s in filtered_stocks if s.change_rate > 0)` — 0은 상승 종목에서 제외되어 `rise_ratio`(상승비율)를 낮춤. |
| `backend/app/domain/sector_calculator.py:132-133` | `raw_total_ta = sum(s.trade_amount ...)` → `avg_ta = raw_total_ta // raw_total` — 0이 거래대금 합산에 포함되어 `avg_trade_amount`를 낮춤. |
| `backend/app/domain/sector_calculator.py:134` | `avg_cr = sum(s.change_rate ...) / len(filtered_stocks)` — 0이 평균 등락률에 포함되어 `avg_change_rate`를 낮춤. |
| `backend/app/domain/sector_score.py:106-107` | `rise_values = [sc.rise_ratio ...]` → 1차 가산점(상승비율 순위) 계산에 0으로 왜곡된 `rise_ratio` 사용. |
| `backend/app/domain/sector_score.py:112-113` | `ta_values = [float(sc.avg_trade_amount) ...]` → 3차 가산점(거래대금 순위) 계산에 0으로 왜곡된 `avg_trade_amount` 사용. |
| `backend/app/domain/sector_score.py:142` | `all_entries.append((stock.change_rate, sc.sector))` → 2차 가산점(가중 순위 합)에 0인 `change_rate` 포함. |

**확정된 사실**: 0으로 폴백된 데이터가 1차·2차·3차 가산점 모두에 영향을 줌. 업종 점수 순위가 왜곡됨.

**현재가 0 표시 경로 (확정)**
- 틱 처리 `pipeline_compute.py:553` — `last_px <= 0`이면 틱 차단. 틱 경로로는 0이 들어가지 않음.
- 현재가 0은 초기 스냅샷/REST 로드 시점에 0으로 저장된 것이 화면에 남아있는 상태에서, 이후 해당 종목으로 틱이 아직 수신되지 않았을 때 발생.

**수정계획서**: `docs/plan_P001_fix.md` (2026-07-15 작성 완료)

**진행 상황**:
- **Step 1 완료 (2026-07-15)**: `engine_radar.py:73-77` 틱 수신 폴백 제거. 빈 FID 12/14 → None 유지. 검증 완료 (py_compile + 테스트 107개 통과 + 런타임 기동 정상).
- **Step 2 대기**: `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + 수신률 판정 검증.
- **Step 3 대기**: `sector_calculator.py:69,78` 업종 점수 폴백 제거.

**수정 방안 (수정계획서 기반)**
- **원인 A 해결 (Step 1, 2)**: `parse_change_rate_to_percent`·`_parse_float_loose` 자체는 변경하지 않음(REST 경로 호환성). 틱 수신 경로(`engine_radar.py:73-77`, `pipeline_compute.py:576`)에서 빈 문자열 체크 후 None 저장. (P20 폴백 금지 준수)
- **원인 B 해결 (Step 2)**: `_has_any_realtime_data`(`pipeline_compute.py:97`)는 `is not None` 체크 유지. 원인 A 수정 후 None이 저장되므로 `!= 0` 불필요. (정상 0% 등락률 오분류 방지)
- **업종 점수 왜곡 해결 (Step 3)**: `sector_calculator.py:69,78`에서 None을 0으로 폴백하지 않고 None 유지. 미수신 종목(change_rate 또는 trade_amount가 None)은 점수 계산에서 제외. (P22 데이터 정합성 준수)
- **연쇄 영향 조사 완료**: `parse_change_rate_to_percent` 호출처 2곳(둘 다 틱 경로), `_parse_float_loose` 호출처 6곳(1곳 틱, 5곳 REST), `sector_calculator.py` None 폴백, `trading.py` None 안전, 프론트엔드 null 안전, 보유종목 평가 안전. 상세는 수정계획서 섹션 2 참조.

**세션 분할 (수정계획서 기반)**
- Step 1 (세션 1): `engine_radar.py:73-77` 틱 수신 폴백 제거. 영향 범위 좁음.
- Step 2 (세션 2): `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + 수신률 판정 검증. 영향 범위 중간.
- Step 3 (세션 3): `sector_calculator.py:69,78` 업종 점수 폴백 제거. 영향 범위 넓음.
- **HANDOVER 원안 대비 변경**: 원안(1단계=원인 B, 2단계=원인 A)은 정상 0% 등락률 오분류 결함이 있어 순서 변경. 원안의 `!= 0` 판정식도 동일 이유로 제거.

**검증 방법 (수정 후)**
- 백엔드 런타임 기동 후, 틱이 일부만 수신된 상태에서 수신률이 100%가 아닌 실제 비율로 표시되는지 확인.
- 화면에서 0/- 로 표시되던 종목이 데이터 미수신 시 일관되게 "-"로 표시되는지 확인.
- 업종 점수 순위가 0 왜곡 없이 계산되는지 확인.

**관련 원칙**: P10(SSOT), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(일관성).
**조사 세션**: 2026-07-15.

## 참고 사항
- `master_stocks_table`의 `cur_price`, `change`, `change_rate`, `trade_amount`는 현재 스냅샷에서 비어 있어, 수치 기준은 `stock_5d_bars`와 `trades`를 사용함.
- `auto-width.ts`의 `KOREAN_SCALE` 조정은 너비 추정 정확도에 큰 영향을 줌. 변경 없이는 `종목명` 9자만 되어도 150px 이상을 요구해 공간 낭비가 큼.
- `sector-ranking-list.ts`와 `profit-overview.ts`는 `DataTable`이 아니므로 별도 처리 필요.
- 컬럼 너비 공통 상수(`COLUMN_WIDTH`)는 min/max px 경계값이며, 실제 비율은 데이터 기반 px→% 정규화로 페이지별 컬럼 구성에 자동 적응함. per-page override는 `ColumnDef`의 `minWidth`/`maxWidth` 필드로 이미 지원.
