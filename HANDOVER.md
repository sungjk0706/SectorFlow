# HANDOVER — SectorFlow

## 현재 진행 상태 (최신 — 다음 세션은 여기서 이어서 진행)

### 작업: 장운영정보(market_phase) 기반 개별 타이머 통합 — Step 1 + Step 2 완료

**진행 단계**: Step 1(`is_ws_subscribe_window()` market_phase 기반 변경) + Step 2(`_broadcast_market_phase()` 핸들러 추가 + 타이머 2개 제거) 완료. Step 3~5 대기.

**계획서**: `docs/plan_market_phase_integration.md` (5개 Step, 세션당 1단계)

**Step 2 완료 내용 (2026-07-14, 커밋 `076a66b`)**:
- `_broadcast_market_phase()`에 NXT "프리마켓" 진입 시 `_on_ws_subscribe_start()` 호출 추가, NXT "장마감" 진입 시 `_on_ws_subscribe_end()` 호출 추가
- `schedule_ws_subscribe_timers()`에서 `ws_subscribe_start`/`end` 타이머 예약 제거 — `confirmed_download_time` + market_phase 전환 타이머 11개만 유지
- `_fire_ws_subscribe_end()` dead code 제거 (P16) — call_later 콜백용 동기 래퍼였으나 타이머 제거로 호출처 사라짐, 테스트도 함께 제거
- 테스트: `test_triggers_nxt_premarket_on_phase_change`에 WS 구독 시작 검증 추가, `test_triggers_ws_subscribe_end_on_nxt_close` 신규 추가, `TestScheduleWsSubscribeTimers`에서 `ws_subscribe_start`/`end` 설정 제거
- 검증: py_compile OK, ruff All checks passed, pytest 133 passed (test_daily_time_scheduler) + 90 passed (test_web_ws_routes + test_engine_ws), 런타임 기동 209ms (`-W error::RuntimeWarning`), `장 상태 초기화: KRX=시간외 단일가, NXT=애프터마켓` 확인, 에러/Traceback/RuntimeWarning 없음, 잔존 프로세스 0건

**Step 1 완료 내용 (2026-07-14, 커밋 `076a66b`)**:
- `is_ws_subscribe_window()` 함수 본문을 `state.market_phase["nxt"]` 기반으로 변경 — `ws_subscribe_start`/`end` 시간 비교 로직 제거, `NXT_ACTIVE_PHASES` 포함 여부로 판단
- 주말/공휴일 판단 제거 — `calc_timebased_market_phase()`가 `nxt="휴장일"` 반환으로 자동 차단
- `ws_subscribe_on` 마스터 스위치 + 빈 settings RuntimeError 유지
- 빈 문자열 `nxt` 시 에러 로그 + False 반환 (P20 폴백 금지, 기존 `is_nxt_only_window` 패턴 동일)
- 테스트: `TestIsWsSubscribeWindow` 6개 + `TestIsEditWindowOpen` 2개를 `market_phase` 기반 mock로 변경
- 검증: py_compile OK, ruff All checks passed, pytest 133 passed + 90 passed, 런타임 기동 215ms, 잔존 프로세스 0건

**다음 단계**: Step 3 — `ws_subscribe_start`/`end` 설정 키 + UI 제거 + 마이그레이션. 사용자 승인 대기.

**이전 작업: NXT-only 구독 분리 — 그룹 A + 그룹 B 완료**

**방향 (반자동 방식)**:
- 07:55: NXT만 먼저 구독 (처음부터 NXT만 시작, 필터 추가)
- 09:00: KRX 추가 구독은 장운영정보 이벤트(`_on_krx_market_open()`)로 자동 처리 — 타이머 불필요
- 15:30: KRX 해지는 기존 로직(`_on_krx_after_hours_start()` → `remove_krx_only_stocks()`) 그대로 사용
- 20:00: NXT 해지는 기존 로직(`_on_ws_subscribe_end()` → `_trigger_unreg_all()`) 그대로 사용 — 15:30에 KRX `_subscribed` 제거되어 NXT만 남음

**그룹 B 완료 내용 (2026-07-14, 커밋 `145cf3c`)**:
- 세션 1에서 추가한 KRX 구독 시간 설정 키 2개(`ws_subscribe_start_krx`, `ws_subscribe_end_krx`) + UI 입력란 제거
- `settings_file.py`에 `_migrate_remove_krx_subscribe_keys()` 마이그레이션 함수 추가 — 기존 `_migrate_*` 패턴 준수, 다음 기동 시 DB에서 자동 DELETE
- `general-settings.ts`의 `scheduleTimeSave` 매개변수화(handle 파라미터)를 세션 1 이전 형태로 롤백 — 단일 호출처만 남으므로 불필요한 추상화 제거 (P24)
- 검증: ruff 기존 실패 1건 (수정 전 동일 실패, 규칙 4-1), py_compile OK, pytest 122 passed, tsc 통과, vite build 통과, vitest 101 passed, 런타임 기동 185ms (`-W error::RuntimeWarning`), `장 상태 초기화: KRX=종가 동시호가, NXT=조기 마감` 확인, 에러/Traceback/RuntimeWarning 없음, 잔존 프로세스 0건

**그룹 A 완료 내용 (2026-07-14, 커밋 `b04f98c`)**:
- `subscribe_sector_stocks_0b()`에 `nxt_only: bool = False` 키워드 파라미터 추가 — NXT-only 구간에 NXT 중복상장 종목만 구독
- `ws_subscribe_control.py`의 `start_quote()` + `run_conditional_reg_pipeline()`에서 `is_nxt_only_window()` 분기 추가
- 기존 로직 재사용: `_on_krx_market_open()`(09:00 KRX 추가), `_on_krx_after_hours_start()`(15:30 KRX 해지), `_on_ws_subscribe_end()`(20:00 NXT 해지) — 모두 수정 없음
- 검증: py_compile OK, ruff All checks passed, pytest 42 passed (test_engine_ws), 런타임 기동 285ms 정상, 잔존 프로세스 0건

**다음 단계**: NXT-only 구독 분리 작업 전체 완료. 다음 작업은 사용자 지시 대기.

**이전 작업: KRX 구독 시간 설정 키 2개 추가 — 세션 1 (커밋 `eff5e1e`, 그룹 B에서 롤백 완료)**:
- 설정 키 2개(`ws_subscribe_start_krx`, `ws_subscribe_end_krx`)의 기반 구축 — 7개 파일 수정
- 반자동 방식 재조정으로 인해 그룹 B(커밋 `145cf3c`)에서 제거 완료

**이전 작업: 가상스크롤 테이블 헤더/본문 컬럼 세로선 불일치 수정 — 완료 (커밋 `0aec178`)**:
- `applyGridTemplatePx()`가 `scrollContainer.querySelector('div')`로 sentinel를 찾으나 DOM 순서상 첫 div인 `headerDiv`를 반환하여, 리사이즈 시 데이터 행의 `gridTemplateColumns`가 갱신되지 않는 버그 수정.
- `virtual-scroller.ts`: sentinel div에 `data-vs-sentinel` 속성 추가.
- `data-table.ts`: `querySelector('div')` → `querySelector('[data-vs-sentinel]')`로 실제 데이터 행 컨테이너 정확히 식별.
- 검증: typecheck 통과, vite build 통과, vitest 101 passed (7 files), Playwright headless Chrome으로 리사이즈 시 헤더/본문 GTC 일치 확인, 잔존 프로세스 0건.

**이전 작업: 장운영정보(market_phase) 단일 소스 통합 — 수정 1~8 전부 완료**:
- 수정 8 (커밋 `aba9e92`): 재계산 타이머 3개 → `_broadcast_market_phase()` 내 페이즈 변경 감지 시 자동 트리거 통합.
- 수정 7 (커밋 `786e371`): `is_ws_subscribe_window()` docstring 기본값 불일치 수정.
- 수정 6 (커밋 `76abe89`): 프론트엔드 중복 상수 제거 + `is_nxt_only` SSOT 전송.
- 수정 5 (커밋 `2636bc1`): `build_sector_stocks_payload()`의 `krx_after_hours` dead data 제거.
- 수정 1,2,3,4 (커밋 `cc5f153`): 4개 시간 함수 → `state.market_phase` 기반 전환.

**주요 리스크**:
- JIF 누락 시 `market_phase` 부정확 (시계 타이머 백업으로 최대 1초 지연)
- 구독 구간 내 재기동 시 초기값 "장개시전" → 현재 페이즈 전환 감지로 재계산 트리거됨 (올바른 동작, 부트스트랩 재계산과 중복 가능하나 정합성 문제 없음)

**미해결 문제**:
- ruff 기존 실패 1건: `settings_store.py:14` `save_settings` unused import (수정 전 동일 실패, 규칙 4-1 기존 실패로 판정)

---

## 직전 완료 작업
- **2026-07-14: 장운영정보 기반 타이머 통합 — Step 2: _broadcast_market_phase() 핸들러 추가 + 타이머 2개 제거 (P10/P16/P24)**
  - **현상**: `ws_subscribe_start`/`end` 타이머가 `schedule_ws_subscribe_timers()`에서 예약되어 `_on_ws_subscribe_start`/`_end`를 호출했으나, Step 1에서 `is_ws_subscribe_window()`가 `market_phase` 기반으로 전환되어 타이머와 market_phase 이중 트리거 상태.
  - **근본 원인**: `daily_time_scheduler.py`의 `schedule_ws_subscribe_timers()`가 `ws_subscribe_start`/`end` 시각에 call_later 타이머를 예약하여 별도 트리거 경로를 유지. `_broadcast_market_phase()`의 페이즈 변경 감지로 통합 필요.
  - **수정 파일**: 백엔드 1파일 + 테스트 1파일 — `daily_time_scheduler.py`, `test_daily_time_scheduler.py`
  - **변경 내용**: (1) `daily_time_scheduler.py` — `_broadcast_market_phase()`에 NXT "프리마켓" 진입 시 `_on_ws_subscribe_start()` 호출 추가 (기존 `_on_nxt_premarket_start()` 이후), NXT "장마감" 진입 시 `_on_ws_subscribe_end()` 호출 추가. `schedule_ws_subscribe_timers()`에서 `ws_subscribe_start`/`end` 타이머 예약 로직 제거 (713-740행), `confirmed_download_time` + market_phase 전환 타이머 11개 유지. `_fire_ws_subscribe_end()` dead code 제거 (P16 — 타이머 제거로 호출처 사라짐). (2) `test_daily_time_scheduler.py` — `test_triggers_nxt_premarket_on_phase_change`에 WS 구독 시작 검증 추가, `test_triggers_ws_subscribe_end_on_nxt_close` 신규 추가, `TestScheduleWsSubscribeTimers`에서 `ws_subscribe_start`/`end` 설정 제거, `_fire_ws_subscribe_end` import + 테스트 제거.
  - **영향 범위**: 백엔드 1파일 + 테스트 1파일 (+33/-66, -33줄净감). `_on_ws_subscribe_start`/`_end` 함수 본문은 수정 없이 재사용. 재귀 호출 위험 없음 (페이즈 변경 감지 가드 `prev != fresh`로 차단). `_apply_auto_toggle_on_startup`은 여전히 `ws_subscribe_start`/`end` 설정 참조 (Step 3에서 설정 키 제거 시 함께 처리).
  - **검증**: py_compile 2개 파일 통과. ruff All checks passed. pytest 133 passed (test_daily_time_scheduler) in 0.75s + 90 passed (test_web_ws_routes + test_engine_ws) in 0.77s. 런타임 기동 `-W error::RuntimeWarning` 209ms, `장 상태 초기화: KRX=시간외 단일가, NXT=애프터마켓` 확인, 실시간 연결 완료, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `076a66b`

- **2026-07-14: 장운영정보 기반 타이머 통합 — Step 1: is_ws_subscribe_window() market_phase 기반 변경 (P10/P16/P20/P24)**
  - **현상**: `is_ws_subscribe_window()`가 사용자 설정 시간(`ws_subscribe_start`/`end`) 기반으로 구독 구간을 판단하나, 실제 구독 시작/종료는 `_broadcast_market_phase()`의 페이즈 변경 핸들러가 담당하여 시간 설정이 구독 동작에 반영되지 않는 P16(살아있는 경로) 위반 상태.
  - **근본 원인**: `daily_time_scheduler.py:283-324`의 `is_ws_subscribe_window()`가 주말/공휴일 판단 + `ws_subscribe_start`/`end` 시간 비교 로직으로 구독 구간을 판단. `market_phase`가 이미 시간 기반 + JIF 이벤트로 갱신되는 SSOT이므로 이중 기준 상태.
  - **수정 파일**: 백엔드 1파일 + 테스트 1파일 — `daily_time_scheduler.py`, `test_daily_time_scheduler.py`
  - **변경 내용**: (1) `daily_time_scheduler.py` — `is_ws_subscribe_window()` 본문을 `state.market_phase["nxt"]`가 `NXT_ACTIVE_PHASES`에 포함되는지로 판단하도록 변경. 주말/공휴일 판단 제거 (`calc_timebased_market_phase()`가 `nxt="휴장일"` 반환으로 자동 차단). `ws_subscribe_on` 마스터 스위치 + 빈 settings RuntimeError 유지. 빈 문자열 `nxt` 시 에러 로그 + False 반환 (P20 폴백 금지, 기존 `is_nxt_only_window` 패턴 동일). 호출처 8개 파일은 함수 본문만 변경으로 자동 적용, 수정 불필요 (P24 단순성). (2) `test_daily_time_scheduler.py` — `TestIsWsSubscribeWindow` 6개 테스트 + `TestIsEditWindowOpen` 2개 테스트를 `_kst_now`/`is_trading_day` 기반 mock → `state.market_phase` 기반 mock로 변경.
  - **영향 범위**: 백엔드 1파일 + 테스트 1파일 (+24/-42, -18줄净감). 호출처 8개 파일 (`engine_loop`, `engine_bootstrap`, `engine_cache`, `engine_service`, `ws_subscribe_control`, `stock_classification`, `ws_subscribe` 라우트, 내부 `is_heavy_operation_allowed`/`is_edit_window_open`/`_init_ws_subscribe_state`)은 자동 적용. 파생 함수 `is_edit_window_open()`, `is_heavy_operation_allowed()`도 자동 적용. `ws_subscribe_start`/`end` 설정 키는 Step 3에서 완전 제거 예정.
  - **검증**: py_compile 2개 파일 통과. ruff All checks passed. pytest 133 passed (test_daily_time_scheduler) in 0.65s + 90 passed (test_web_ws_routes + test_engine_ws) in 0.74s. 런타임 기동 `-W error::RuntimeWarning` 215ms, `장 상태 초기화: KRX=시간외 단일가, NXT=애프터마켓` 확인, 실시간 연결 완료, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `076a66b`

- **2026-07-14: KRX 구독 시간 설정 키 2개 제거 — 그룹 B (P10/P16/P24)**
  - **현상**: 세션 1에서 추가한 KRX 구독 시간 설정 키 2개(`ws_subscribe_start_krx`, `ws_subscribe_end_krx`)와 UI 입력란이 반자동 방식 재조정으로 인해 dead code로 잔존. 사용자가 설정 화면에서 "KRX 구독 시간" 입력란을 변경해도 실제 동작에 반영되지 않는 P16(살아있는 경로) 위반 상태.
  - **근본 원인**: 반자동 방식 전환으로 09:00 KRX 추가 구독/15:30 KRX 해지가 장운영정보 이벤트로 자동 처리되므로, 별도 KRX 구독 시간 설정이 불필요. 세션 1에서 추가한 설정 키 2개 + UI 입력란이 8개 파일에 걸쳐 잔존.
  - **수정 파일**: 백엔드 4파일 + 프론트엔드 2파일 + 테스트 2파일 — `settings_file.py`, `settings_defaults.py`, `settings_store.py`, `engine_settings.py`, `types/index.ts`, `general-settings.ts`, `test_settings_store.py`, `test_engine_settings.py`
  - **변경 내용**: (1) `settings_file.py` — `_migrate_remove_krx_subscribe_keys()` 마이그레이션 함수 추가 (기존 `_migrate_*` 패턴 준수, `del merged[key]`로 DB 자동 DELETE), 체인 등록. (2) 백엔드 3파일 — `settings_defaults.py`(기본값 2개 제거), `settings_store.py`(저장 페이로드 + `_TIME_FIELDS` 제거), `engine_settings.py`(엔진 설정 dict 제거). (3) 프론트엔드 2파일 — `types/index.ts`(IndexData 필드 2개 제거), `general-settings.ts`(KRX UI 입력란 블록 제거 + `scheduleTimeSave` handle 매개변수화를 세션 1 이전 형태로 롤백, `pendingTimeSave` 타입도 롤백, `wsKrxTimeHandle` 변수/cleanup 제거). (4) 테스트 2파일 — `test_settings_store.py`(3곳 dict에서 KRX 키 제거), `test_engine_settings.py`(5문자 검증 2줄 제거).
  - **영향 범위**: 8개 파일 (+21/-54). KRX 구독 시간 설정이 완전히 제거되고, 09:00 KRX 추가 구독/15:30 KRX 해지는 장운영정보 이벤트로 자동 처리 (그룹 A에서 이미 구현). DB에 잔존하는 KRX 키가 있을 경우 다음 기동 시 마이그레이션으로 자동 삭제. `scheduleTimeSave` 매개변수화 롤백으로 P24(단순성) 복귀 — 단일 호출처만 남으므로 불필요한 추상화 제거.
  - **검증**: ruff 기존 실패 1건 (`save_settings` unused import, 수정 전 동일 실패 확인 — 규칙 4-1 준수). py_compile 6개 파일 통과. pytest 122 passed (test_settings_store + test_engine_settings + test_settings_file_integration) in 0.40s. tsc --noEmit 통과. vite build 통과 (1.93s). vitest 101 passed (7 files). 런타임 기동 `-W error::RuntimeWarning` 185ms, `장 상태 초기화: KRX=종가 동시호가, NXT=조기 마감` 확인, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `145cf3c`

- **2026-07-14: NXT-only 구독 분리 — subscribe_sector_stocks_0b() nxt_only 파라미터 추가 (P10/P24)**
  - **현상**: 07:55 구독 시 KRX/NXT 구분 없이 전체 종목이 구독되어, KRX 장개시 전(09:00 이전)에 KRX 단독 종목의 실시간 데이터가 불필요하게 수신됨.
  - **근본 원인**: `subscribe_sector_stocks_0b()` (`engine_ws_reg.py:243`)가 KRX/NXT 구분 없이 보유종목 + 필터통과 종목을 모두 구독. `ws_subscribe_control.py`의 `start_quote()`와 `run_conditional_reg_pipeline()`이 이 함수를 호출할 때 NXT-only 구간 여부를 판단하지 않았음.
  - **수정 파일**: 백엔드 2개 파일 — `engine_ws_reg.py`, `ws_subscribe_control.py`
  - **변경 내용**: (1) `engine_ws_reg.py` — import에 `is_nxt_enabled` 추가, `subscribe_sector_stocks_0b()`에 `nxt_only: bool = False` 키워드 파라미터 추가, `nxt_only=True`일 때 보유종목/필터통과 종목 모두 `is_nxt_enabled(cd)`가 True인 종목만 필터링 (2줄 추가). 기본값 `False`로 기존 호출 경로 동작 변화 없음. (2) `ws_subscribe_control.py` — `start_quote()`와 `run_conditional_reg_pipeline()`에서 `is_nxt_only_window()` import 후 `subscribe_sector_stocks_0b(nxt_only=is_nxt_only_window())`로 호출.
  - **영향 범위**: 백엔드 2개 파일 (+12/-4줄). 기존 호출 경로(`_on_krx_market_open`, `_on_krx_after_hours_start`, `_on_ws_subscribe_end`)는 수정 없이 기본값 `nxt_only=False`로 기존 동작 유지. 09:00 KRX 추가 구독, 15:30 KRX 해지, 20:00 NXT 해지 — 모두 기존 로직 그대로 재사용.
  - **검증**: py_compile 2개 파일 통과. ruff All checks passed. pytest 42 passed (test_engine_ws) in 0.27s. 런타임 기동 `-W error::RuntimeWarning` 285ms, `장 상태 초기화: KRX=정규장, NXT=메인마켓` 확인, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `b04f98c`

- **2026-07-14: KRX 구독 시간 설정 키 2개 추가 — 세션 1 (P10/P21/P23/P24, 그룹 B에서 롤백 예정)**
  - **현상**: KRX 구독 시작/종료 시간을 NXT 구독 시간과 별도로 설정할 수 있는 기능이 없어, 세션 1에서 설정 키 2개(`ws_subscribe_start_krx`, `ws_subscribe_end_krx`)의 기반을 구축.
  - **근본 원인**: 기존 `ws_subscribe_start`/`ws_subscribe_end` 2개 키만 존재하여 KRX/NXT 구분 설정이 불가능. 설정 정의(`settings_defaults.py`), 저장(`settings_store.py`), 엔진 전달(`engine_settings.py`), UI 입력(`general-settings.ts`), 타입(`types/index.ts`), 테스트(2파일) 경로에 새 키가 없었음.
  - **수정 파일**: 백엔드 3파일 + 프론트엔드 2파일 + 테스트 2파일 — `settings_defaults.py`, `settings_store.py`, `engine_settings.py`, `types/index.ts`, `general-settings.ts`, `test_settings_store.py`, `test_engine_settings.py`
  - **변경 내용**: (1) `settings_defaults.py:21-22` — `DEFAULT_USER_SETTINGS`에 `ws_subscribe_start_krx="09:00"`, `ws_subscribe_end_krx="15:30"` 추가. (2) `settings_store.py:74-75` — `general_save_payload_from_flat()`에 새 키 2개 추가 + `_TIME_FIELDS`에 HH:MM 검증 대상 추가. (3) `engine_settings.py:89-90` — result dict에 새 키 2개 추가 (`str(merged[...])[:5]` 패턴). (4) `types/index.ts:139-140` — `IndexData` 인터페이스에 필드 2개 추가. (5) `general-settings.ts` — `scheduleTimeSave` handle 매개변수화 (기존 하드코딩 `wsTimeHandle` → 매개변수로 일반화), "KRX 구독 시간" TimePairInput 입력란 추가, `wsKrxTimeHandle` 변수/로드/cleanup/비활성화 처리. (6) 테스트 2파일 — 기존 dict에 새 키 2개 추가 + 5문자 검증 2줄.
  - **영향 범위**: 7개 파일 (+약 50줄). 세션 1 완료 후 세션 2 전까지: UI에 "KRX 구독 시간" 입력란이 표시되고 저장되지만, 실제 KRX 분리 구독 동작은 구현되지 않음. 사용자가 입력란을 변경해도 기존 통합 구독 동작 유지. 세션 2에서 타이머 구현 시 실제 동작 연결. `engine_service.py`의 `_WS_SCHEDULE_KEYS`는 세션 2에서 추가 (P16 준수 — 설정 키가 타이머 동작과 함께 연결).
  - **검증**: ruff 기존 실패 1건 (`save_settings` unused import, 수정 전 동일 실패 확인 — 규칙 4-1 준수). py_compile OK. pytest 107 passed (test_settings_store + test_engine_settings). tsc --noEmit 통과. vite build 통과 (1.98s). vitest 101 passed (7 files). 런타임 기동 164ms, `장 상태 초기화: KRX=정규장, NXT=메인마켓` 확인, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `eff5e1e`

- **2026-07-14: 가상스크롤 테이블 헤더/본문 컬럼 세로선 불일치 수정 — querySelector('div') → [data-vs-sentinel] (P16/P23)**
  - **현상**: 수익상세 페이지 매도내역/매수내역 테이블에서 컬럼 타이틀(헤더)의 세로셀선과 데이터 행의 세로셀선이 일치하지 않음.
  - **근본 원인**: `frontend/src/components/common/data-table.ts:695` — `applyGridTemplatePx()` 함수가 리사이즈 시 데이터 행 컨테이너(sentinel)를 찾기 위해 `scrollContainer.querySelector('div')`를 사용했으나, 이는 DOM 순서상 첫 번째 div인 `headerDiv`를 반환함. 결과로 헤더 `gridTemplateColumns`는 갱신되나 데이터 행 `gridTemplateColumns`는 갱신되지 않아 구값 유지. 컨테이너 너비가 변하는 시점(플렉스 레이아웃 안착, 탭 전환, 윈도우 리사이즈 등)부터 헤더와 본문의 컬럼 폭이 불일치.
  - **수정 파일**: 프론트엔드 2개 파일 — `virtual-scroller.ts`, `data-table.ts`
  - **변경 내용**: (1) `virtual-scroller.ts:185` — sentinel div에 `data-vs-sentinel` 속성 추가. (2) `data-table.ts:695` — `querySelector('div')` → `querySelector('[data-vs-sentinel]')`로 실제 데이터 행 컨테이너 정확히 식별.
  - **영향 범위**: 프론트엔드 2개 파일 (+6/-1). 가상 스크롤 모드를 사용하는 모든 DataTable이 리사이즈 시 헤더-본문 컬럼 정렬 유지. 초기 렌더링 동작은 동일 (이미 정렬 맞음), 리사이즈 시에만 수정 효과 적용. 기존 기능 영향 없음.
  - **검증**: typecheck (tsc --noEmit) 통과. vite build 통과. vitest 101 passed (7 files). Playwright headless Chrome 검증 — 초기 렌더링(800px) 헤더/데이터 GTC 일치, 리사이즈 후(600px) 헤더 GTC = 데이터 GTC = `39px 102px 77px 88px 69px 51px 88px 69px` 일치, 셀 경계 위치 완전 일치 확인. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `0aec178`

- **2026-07-14: 재계산 타이머 3개 _broadcast_market_phase() 통합 — 수정 8 (P10/P22/P24)**
  - **현상**: 08:00/09:00/15:30 재계산 타이머 3개가 `_broadcast_market_phase()`와 별도로 존재하여, JIF 경계 이벤트와 시계 타이머가 동시에 발생할 때 재계산이 중복 실행될 위험 존재.
  - **근본 원인**: `daily_time_scheduler.py:744-769`의 재계산 타이머 3개가 `market-phase` 타이머 배열(동일 시각 `_broadcast_market_phase()` 호출)과 독립적으로 예약되어, 동일 시각에 2개의 타이머가 각각 재계산과 페이즈 갱신을 따로 수행.
  - **수정 파일**: 백엔드 1개 파일 + 테스트 1개 파일 — `daily_time_scheduler.py`, `test_daily_time_scheduler.py`
  - **변경 내용**: (1) `_broadcast_market_phase()`에 prev/new 페이즈 비교 로직 추가 — NXT "프리마켓"/KRX "정규장"/KRX "체결 정산" 전환 시 `schedule_engine_task`로 `_on_nxt_premarket_start()`/`_on_krx_market_open()`/`_on_krx_after_hours_start()` 예약. (2) 타이머 3개 제거 (line 744-769, -28줄). (3) `_on_*` 함수 3개 docstring 갱신 — "_broadcast_market_phase()는 ...에서 동일 시각에 호출된다" → "내 페이즈 변경 감지 시 자동 트리거된다 (수정 8 통합)". (4) 테스트 기존 `test_broadcasts_phase` 수정 (prev=new로 설정) + 신규 4건 추가 (NXT 프리마켓/KRX 정규장/KRX 체결정산 트리거 + 변경 없을 시 미트리거).
  - **영향 범위**: 백엔드 1개 파일 + 테스트 1개 파일 (+47/-45). 구독 구간 내 재기동 시 초기값 "장개시전" → 현재 페이즈 전환 감지로 재계산 트리거됨 (올바른 동작). JIF 경계 이벤트와 시계 타이머 중복 호출 시 첫 번째 호출만 트리거 (P22 중복 방지).
  - **검증**: ruff All checks passed. py_compile OK. pytest 133 passed (test_daily_time_scheduler) in 0.76s. 런타임 기동 `-W error::RuntimeWarning` 103ms, `장 상태 초기화: KRX=정규장, NXT=메인마켓` 확인, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `aba9e92`

- **2026-07-14: 프론트엔드 KRX/NXT 중복 상수 제거 + is_nxt_only SSOT 전송 — 수정 6 (P10/P16/P22/P24)**
  - **현상**: 프론트엔드 `sector-stock.ts`가 백엔드와 동일한 `KRX_INACTIVE_PHASES`(12개)·`NXT_ACTIVE_PHASES`(6개) 상수와 `isKrxInactiveWindow()` 함수를 중복 정의하여 P10(SSOT) 위반. 백엔드가 이미 `is_nxt_only_window()`로 단일 진실 소스를 보유하고 있으나 프론트엔드에 전달되지 않아 독립 계산.
  - **근본 원인**: `get_market_phase()` (`daily_time_scheduler.py:230-247`)가 `market-phase` 이벤트 페이로드를 조립하면서 `is_nxt_only` 파생 값을 포함하지 않았음. 이 페이로드는 `initial-snapshot`·`market-phase`·`index-data` 3개 전송 경로가 모두 경유하는 SSOT 지점.
  - **수정 파일**: 백엔드 1개 파일 + 테스트 1개 파일 + 프론트엔드 4개 파일 — `daily_time_scheduler.py`, `test_daily_time_scheduler.py`, `sector-stock.ts`, `uiStore.ts`, `types/index.ts`, `binding.ts`
  - **변경 내용**: (1) 백엔드 `get_market_phase()` 반환 dict에 `phase["is_nxt_only"] = is_nxt_only_window()` 추가 (P22 파생). (2) 프론트엔드 `sector-stock.ts` 중복 상수 2개 + `isKrxInactiveWindow()` 제거 (-43줄), `computeRows` 파라미터 타입에 `is_nxt_only?: boolean` 추가, `krxInactive = marketPhase.is_nxt_only === true` 사용. (3) `uiStore.ts` marketPhase 인터페이스 + 초기값에 `is_nxt_only` 추가. (4) `types/index.ts` IndexData.market_phase 타입에 `is_nxt_only?: boolean` 추가. (5) `binding.ts` market-phase 이벤트 핸들러 타입에 `is_nxt_only` 추가. (6) 테스트 `TestGetMarketPhase` 기존 4건에 `is_nxt_only` 검증 추가 + 신규 1건 `test_is_nxt_only_true_when_krx_inactive_nxt_active` 추가.
  - **영향 범위**: 6개 파일 (+20/-36). `engine_account_notify.py` 수정 불필요 — 페이로드 조립 없이 `_broadcast()` 전달만 담당. 3개 전송 경로 모두 `get_market_phase()` 경유 → 자동 전송. 기존 `krxInactive` 행 스타일링 유지, UI 변화 없음.
  - **검증**: ruff All checks passed. py_compile OK. pytest 164 passed (test_daily_time_scheduler 129 + test_engine_snapshot 19 + test_sector_data_provider 16). 프론트엔드 typecheck (tsc --noEmit) 통과. 런타임 기동 `-W error::RuntimeWarning` 82ms, `장 상태 초기화: KRX=정규장, NXT=메인마켓` 확인, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `76abe89`

- **2026-07-14: 시간 함수 4개 market_phase 기반 전환 — 수정 1,2,3,4 (P10/P16/P20/P22/P23/P24)**
  - **현상**: `is_nxt_premarket_window()`, `is_nxt_aftermarket_window()`, `is_krx_after_hours()`, `get_nxt_trde_tp()` 4개 함수가 `state.market_phase`를 사용하지 않고 독립적으로 시간 계산 + 거래일 판별을 수행하여 SSOT(P10) 위반. 특히 `is_nxt_aftermarket_window()`는 거래일 체크 누락 버그 존재.
  - **근본 원인**: `calc_timebased_market_phase()`가 이미 거래일 판별 + 시간 구간 산정하여 `state.market_phase`에 저장하므로, 4개 함수가 이를 재사용해야 SSOT 준수. `daily_time_scheduler.py:46-60, 63-70, 192-205, 208-228`.
  - **수정 파일**: 백엔드 1개 파일 + 테스트 1개 파일 — `daily_time_scheduler.py`, `test_daily_time_scheduler.py`
  - **변경 내용**: (1) 수정 1 — `is_nxt_premarket_window()` → `state.market_phase["nxt"] == "프리마켓"`, 빈 문자열 감지 시 `logger.error` + `return False`. (2) 수정 2 — `is_nxt_aftermarket_window()` → `state.market_phase["nxt"] in ("애프터마켓", "애프터마켓 지속")`, 거래일 체크 누락 자동 해결. (3) 수정 3 — `is_krx_after_hours()` → `state.market_phase["krx"] in ("체결 정산", "장후 시간외", "시간외 단일가", "장 종료")`, `now` 파라미터 제거 (P24). (4) 수정 4 — `get_nxt_trde_tp()` docstring 갱신 (market_phase 기반 명시), 로직은 헬퍼 호출 유지 (P16). (5) 테스트 3개 클래스 재작성 — `_kst_now`/`is_trading_day` patch → `state.market_phase` mock 패턴. TestGetNxtTrdeTp 4건은 헬퍼 mock 방식 유지.
  - **영향 범위**: 백엔드 1개 파일 + 테스트 1개 파일 (+131/-90). 호출처 영향 없음 (`buy_order_executor.py:115`, `kiwoom_order.py:61` 인자 없이 호출). `test_buy_order_executor.py`/`test_kiwoom_order.py` — 함수를 `return_value`로 patch하므로 영향 없음.
  - **검증**: ruff All checks passed. py_compile OK. pytest 178 passed (test_daily_time_scheduler 128 + test_buy_order_executor + test_kiwoom_order 50). 런타임 기동 `-W error::RuntimeWarning` 94ms, `장 상태 초기화: KRX=정규장, NXT=메인마켓` 확인, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `cc5f153`

- **2026-07-14: 단계 완료 시 작업 여력 보고 규칙 추가 — AGENTS.md Context Mgmt 10번 + 스킬 5개 참조 링크 (P10/P23)**
  - **현상**: AGENTS.md와 5개 스킬 파일에 "단계 완료 시 작업 여력 보고 + 커밋/핸드오버 승인" 규칙이 없어, 에이전트가 매 단계 완료 시 사용자에게 작업 여력을 보고하고 승인받는 절차가 명시되어 있지 않았음.
  - **근본 원인**: `AGENTS.md` 섹션4 Context Management Rules에 "세션 종료 시 보고"(규칙 5)는 있었으나 "매 단계 완료 시 보고" 규칙이 없었음. 스킬 파일 5개에도 동일 규칙 누락.
  - **수정 파일**: 문서 6개 파일 — `AGENTS.md`, `.devin/skills/{problem-solve,backend-fix,frontend-fix,safe-trade,db-backup}/SKILL.md`
  - **변경 내용**: (1) `AGENTS.md:205-210` — Context Management Rules 신규 10번 "단계 완료 시 작업 여력 보고 (강제)" 추가. 일반 용어("작업 여력") 사용, 보고 예시 2종(충분/적음), 규칙 5(세션 종료 시)와 시점 구분 명시. (2) `AGENTS.md:190` — 기존 2번 끝에 "점검 결과는 규칙 10에 따라 사용자에게 보고" 연계 링크 추가. (3) 스킬 5개 — 각 파일의 보고 섹션에 "AGENTS.md 섹션4 Context Management Rules 10 준수" 참조 링크 1줄씩 추가 (P10 SSOT — 본문은 AGENTS.md, 스킬에는 참조만).
  - **영향 범위**: 6개 파일 (+16/-1). 코드 동작 영향 없음 (문서/규칙만 수정). 앞으로 모든 단계 완료 시 에이전트가 작업 여력을 보고하고 커밋/핸드오버 갱신 승인을 받도록 강제.
  - **검증**: grep "Context Management Rules 10" — 5개 스킬 파일에 1건씩 참조 확인. git diff --stat — 6개 파일 +16/-1. 잔존 프로세스: `main.py` PID 6199 1건 (이번 세션에서 띄우지 않은 기존 프로세스, 임의 종료하지 않음).
  - **커밋**: `bf8a06a`

- **2026-07-14: build_sector_stocks_payload krx_after_hours dead data 제거 — 필드 + import + 테스트 정리 (P16/P10)**
  - **현상**: `build_sector_stocks_payload()`가 `sector-stocks-refresh` 이벤트 페이로드에 `krx_after_hours` 필드를 포함하여 전송했으나, 프론트엔드 전체에서 참조 코드 없어 dead data로 전송됨 (P16 위반).
  - **근본 원인**: `engine_snapshot.py:97,109` — `is_krx_after_hours`를 import하여 반환값에 `krx_after_hours` 필드로 포함. 프론트엔드 `frontend/` 디렉토리 전체 검색 결과 참조 0건. `ws.py:94-95`에서 페이로드를 그대로 WS 전송하므로 불필요 데이터 매 전송마다 포함.
  - **수정 파일**: 백엔드 1개 파일 + 테스트 1개 파일 — `engine_snapshot.py`, `test_engine_snapshot.py`
  - **변경 내용**: (1) `engine_snapshot.py:97` — `is_krx_after_hours` import 제거. (2) `engine_snapshot.py:109` — 반환값 `{"_v": 1, "stocks": filtered, "krx_after_hours": is_krx_after_hours()}` → `{"_v": 1, "stocks": filtered}`. (3) `test_engine_snapshot.py:305,309,321,326` — `is_krx_after_hours` patch 2건 + assertion 2건 제거 + docstring 라인 번호 갱신 (L93-109 → L93-108). (4) `is_krx_after_hours` 함수 자체는 `daily_time_scheduler.py`에 유지 (수정 3 대상, `buy_order_executor.py` 사용 중).
  - **영향 범위**: 백엔드 1개 파일 + 테스트 1개 파일 (+3/-8). 프론트엔드 영향 없음 (참조 코드 없었음). WS 전송 `sector-stocks-refresh` 페이로드에서 `krx_after_hours` 필드 제거, UI 동작 영향 없음.
  - **검증**: ruff `test_engine_snapshot.py` All checks passed. `engine_snapshot.py` 기존 실패 1건 (`engine_state` unused import, 수정 전 동일 실패 확인 — 규칙 4-1). pytest `test_engine_snapshot.py` 19 passed in 1.03s. 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 171ms 기동, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수). `krx_after_hours` 잔존 — `engine_snapshot.py`/`test_engine_snapshot.py` 0건 확인.
  - **커밋**: `2636bc1`

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책, JIF 경계 이벤트 즉시 갱신 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, DataTable 컬럼 너비 안정화, applyIndexRefresh dead code 제거 + applyIndexData market_phase 갱신 — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 pytest 56 passed (test_engine_ws_dispatch.py). 커버리지 Phase 1~3 완료
- **규칙/문서 정리**: AGENTS.md 4섹션 구조, 아키텍처 원칙 24개, .devin/workflows 제거 + skills 통합 — 완료 (2026-07-13)

## 진행 중 작업

### 보유종목/수익현황 페이지 평가손익·수익률 실시간 불일치 해결 — 완료
- **상태**: 프론트엔드 3개 파일 수정 완료 (`8dd84a8`). 빌드 + 테스트 통과. 사용자 UI 확인 대기.
- **내용**: `computeHoldingsSummary` 공통 함수로 두 페이지(보유종목 요약 배지 + 수익현황 계좌현황)가 개별 종목 행과 동일한 데이터 소스(positions + sectorStocks)·공식으로 평가손익/수익률 계산. `real-data-tick` 이벤트에 반응하여 실시간 갱신.
- **대기**: 사용자 브라우저 UI 확인 — (1) 보유종목 페이지 개별 합산=요약 일치, (2) 수익현황 계좌현황=보유종목 요약 일치, (3) 실시간 가격 변동 시 두 페이지 갱신.

### 업종 점수 순위별 차등 점수제 전환 — 백엔드+프론트엔드 완료
- **상태**: 백엔드 전환(`b106a71`) + 프론트엔드 전환(`17b9300`) 완료. 사용자 UI 확인 완료. 본 전환 작업 완료.
- **배경**: 기존 3단계 누적 가산점(0~300, `rank_to_score`)은 인접 순위 간 격차가 1.67%로 미세하여 순위 구분이 애매했음. 사용자가 각 조건의 중요도를 조절할 수 없었음.
- **전환 내용**: `rank_to_score`(0~100) → `rank_to_tiered_score`(0~사용자 설정 만점). 1위=만점, 2위=만점-1, ..., 0점까지 1점씩 차감. 사용자 설정 만점 3개(1차=10, 2차=7, 3차=5 기본값). 컷오프(min_rise_ratio) 2패스 구조 유지.
- **백엔드 완료** (`b106a71`): `sector_score.py`(`rank_to_score` 제거, `rank_to_tiered_score` 도입), `settings_defaults.py`/`engine_settings.py`(신규 키 3개), `sector_calculator.py`/`engine_sector_confirm.py`/`sector_data_provider.py`(만점값 전달), `engine_service.py`(`_SECTOR_UI_KEYS` 추가 → 설정 변경 시 자동 재계산), ARCHITECTURE.md(참조 갱신), 테스트 5개 파일. pytest 2737 passed + ruff 0건 + 런타임 기동 통과.
- **프론트엔드 완료** (`17b9300`): `types/index.ts`(신규 키 3개), `sector-settings.ts`(④ 섹션 만점 입력란 3개), `sector-ranking-list.ts`+`data-table.ts`(점수 정수 표시). `npm run build` 1.54s + `npm test` 101 passed 통과. 사용자 UI 확인 완료.

### 업종 점수 누적 가산점제 전환 (구 작업 — 완료)
- **계획서**: `docs/plan_sector_bonus_points.md` (895줄 — 2026-07-13 갱신)
- **상태**: Phase 1~3-B + 잔존 정리 + ARCHITECTURE.md 갱신 + 전수 검증 완료. 이후 순위별 차등 점수제로 재전환 완료 (상단 참조).
- **추가 개선점**: 3차 가산점 median 대안(편향 모니터링 후 전환 검토) — 순위별 차등 점수제 전환 후에는 median 대안 불필요 (순위 기반이므로 절대값 왜곡 영향 없음)

### 아키텍처 전수 점검 — B-09 완료, 20개 미시작 (일시 보류)
- **완료**: B-01~B-09, F-01 (P0 전체 + B-06~B-09)
- **미시작**: B-10~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-10 (엔진 계좌/서비스) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 중복 로직 정리 — 2순위 (백엔드 설정 로드/마스킹 단일화)
- **상태**: 중복 로직 전수 조사 완료 (백엔드 8건 + 프론트엔드 9건 = 17건 식별). 1순위(JSON 직렬화 통일) 완료 (커밋 `5afe492`).
- **2순위**: 백엔드 설정 로드/마스킹/복호화 로직 단일화 — `engine_settings.py`로 통합
  - `settings_store.py:220-251`(`build_masked_settings_dict`)와 `engine_config.py:117-133`(`_mask_sensitive_settings`) 마스킹 중복
  - `engine_settings.py:28-39`(`_dec`)와 `settings_file.py:141-145` 복호화 유사 패턴
  - 영향 파일: 3개 (`engine_settings.py`, `settings_store.py`, `engine_config.py`)
- **3순위 이후**: 프론트엔드 숫자/소수점 포맷팅 통일 → 프론트엔드 설정 페이지 행 스타일 공통화 → 프론트엔드 날짜 포맷팅 공통화 → 백엔드 종목코드 정규화 → 백엔드 REG 페이로드 → 백엔드 KST 타임존 → 기타 LOW 항목
- **참고**: 각 항목은 세션당 1단계 원칙(규칙 0-1)에 따라 한 세션에 하나씩 진행

### 아키텍처 전수 점검 (일시 보류)
- B-10: 엔진 계좌/서비스 (`engine_account.py`, `engine_account_rest.py`, `engine_account_notify.py`, `engine_service.py`)
- `docs/architecture_audit_plan.md` 체크리스트 사용, 발견 문제를 섹션 7에 등록
- 이후 B-11 (P1) → B-12~B-19 (P2) → B-20~B-23 (P3) → F-02~F-07 순서

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결**
  - 상세 조사 기록: `docs/ghost_position_investigation.md` ([A]~[I] 미조사 항목)
  - 재발 방지 조치 (2026-07-10, 코드 확인 완료):
    - `test_positions` 테이블 제거 — `stock_tables.py:141`, DB 저장 로직 전체 제거
    - `trades` 기반 SSOT 전환 — `dry_run.py:38-68`, `trade_history.py:549`
    - `execute_sell()` 런타임 가드 — `trading.py:418-436` (유령 포지션 차단 + Telegram 알림)
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 수동 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성

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
