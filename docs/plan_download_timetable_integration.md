# 태스크 파일: 1일봉차트 확정 다운로드 시간 DB 타임테이블 통합 구현 계획

> **상태**: 태스크 파일 작성 완료 · 구현 승인 대기
> **작성일**: 2026-07-18
> **전세션 산출물**: `docs/architecture_download_timetable_integration_design.md` (설계서)
> **다단계 워크플로우**: 1세션(설계서 ✓) → 2세션(본 태스크 파일 ✓) → 3세션~(단계별 구현)
> **관련 원칙**: P10(SSOT) · P14(단일 타이머) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 1. 심층 사전조사 결과 (규칙 0-2 4항목)

### 1-1. 의존성 조사

#### 백엔드 대상 파일

**① `backend/app/services/daily_time_scheduler.py`** (약 1527줄 — 핵심 수정 대상)

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `retry_pipeline_catchup_after_bootstrap()` | 653-716 | 라인 687 `_settings["confirmed_download_time"]` → `_settings["timetable.confirmed_download"]` 키 참조 변경. 부트스트랩 catch-up 로직은 멱등성 가드로 단순화 (설계서 4-5) |
| `_fire_unified_confirmed_fetch()` | 620-633 | 변경 없음 — `confirmed_done` 플래그 가드 유지 (이미 존재하는 1차 가드) |
| `_on_confirmed_download()` | 913-919 | 멱등성 가드 `last_confirmed_download_date` 진입부 추가 (설계서 4-2). 현재 가드 없음 → 신규 추가 |
| `_fire_confirmed_download()` | 908-910 | 제거 대상 — 타임테이블이 직접 `_on_confirmed_download()` 호출하므로 동기 래퍼 불필요 (P24). 단, 타임테이블 `kind="direct"` 콜백은 비동기 함수를 `schedule_engine_task()`로 래핑하는 기존 패턴 확인 필요 |
| `build_timetable_from_cache()` | 962-996 | 11번째 항목 추가 — `timetable.confirmed_download` + 토글 OFF 시 스킵 (설계서 4-1). 현재 10항목 → 11항목 |
| `_cache_time()` (내부 함수) | 975-979 | 변경 없음 — 기존 패턴 그대로 재사용 (P23) |
| `schedule_ws_subscribe_timers()` | 1122-1173 | 제거 대상 — 사실상 `confirmed_download_time` 타이머만 담당 (나머지는 이전 다단계 작업에서 제거됨). 전체 검색 결과 호출자 3곳 존재 → 제거 시 호출자도 함께 정리 |
| `state.ws_subscribe_timer_handles` 참조 | 1131-1133, 1162, 1517-1519 | 제거 대상 — `schedule_ws_subscribe_timers()` 제거 시 함께 정리 |
| `_on_midnight()` | 1382-1414 | 라인 1390 `state.confirmed_done = False` 옆에 `state.last_confirmed_download_date = ""` 리셋 추가 (자정 리셋, 설계서 4-2). 라인 1410 `schedule_ws_subscribe_timers(settings)` 호출 제거 |
| `start_daily_time_scheduler()` | 1486-1508 | 라인 1494 `schedule_ws_subscribe_timers(settings)` 호출 제거. 타임테이블 빌드(1500)는 11항목으로 자동 확장 |
| `stop_daily_time_scheduler()` | 1511-1527 | 라인 1517-1519 `ws_subscribe_timer_handles` 취소 블록 제거 |

**`schedule_ws_subscribe_timers()` 호출자 전체 검색 결과 (P16 — 제거 전 확인)**:
| 호출자 | 파일·줄 | 처리 |
|---|---|---|
| `engine_service.py` 설정 변경 감지 | engine_service.py:135 | `_WS_SCHEDULE_KEYS` 분기 재작성 — `_TIMETABLE_KEYS`로 통합 (설계서 4-4) |
| `_on_midnight()` 자정 리셋 | daily_time_scheduler.py:1410 | 호출 제거 (타임테이블 타이머는 자정에 자동 재예약되지 않으므로 별도 처리 검토 — 아래 "주의사항" 참조) |
| `start_daily_time_scheduler()` 기동 | daily_time_scheduler.py:1494 | 호출 제거 (타임테이블 빌드+스캔이 이미 담당) |

> **주의사항 (자정 타이머 재예약)**: `schedule_ws_subscribe_timers()` 제거 시 자정에 `confirmed_download_time` 타이머가 재예약되지 않음. 단, 타임테이블 타이머(`_schedule_next_timetable_event()`)가 다음 미래 이벤트를 자동 예약하므로 20:40 이벤트도 타임테이블에 포함되어 자동 예약됨. 자정 리셋 후 타임테이블 재빌드가 필요한지 확인 — `_on_midnight()`에서 `_TIMETABLE` 재빌드 + `_schedule_next_timetable_event()` 호출 추가 검토 (설계서에 명시 없음 → 4세션에서 보완).

**② `backend/app/services/engine_state.py`** (약 128줄)

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `ws_subscribe_timer_handles` | 109 | 제거 — `schedule_ws_subscribe_timers()` 제거와 함께 |
| `last_realtime_reset_date` | 116 | 참조용 — 신규 `last_confirmed_download_date` 패턴의 모델 (P23 일관성) |
| `last_ws_subscribe_start_date` | 117 | 참조용 — 동일 패턴 |
| `last_krx_pre_subscribe_date` | 118 | 참조용 — 동일 패턴 |
| 신규 필드 | 118 아래 | `last_confirmed_download_date: str = ""` 추가 (확정 다운로드 멱등성 가드, P22) |

**③ `backend/app/services/engine_service.py`** (설정 변경 감지)

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `_WS_SCHEDULE_KEYS` | 127 | 제거 — `confirmed_download_time` 키 자체 제거 |
| `_WS_SCHEDULE_KEYS` 분기 | 128-147 | 재작성 — `scheduler_market_close_on` 토글 변경 시 타임테이블 재빌드 필요. "활성→구간밖 즉시 구독 해제" / "비활성→구간안 즉시 구독 시작" 로직은 `scheduler_market_close_on`만 남으므로 별도 분기 유지 또는 `_TIMETABLE_KEYS` 분기 내부로 통합 (설계서 4-4) |
| `_TIMETABLE_KEYS` | 150-154 | `timetable.confirmed_download` + `scheduler_market_close_on` 추가 |

**④ `backend/app/core/settings_store.py`** (설정 저장 + 순서 검증)

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `general_save_payload_from_flat()` | 74 | `"confirmed_download_time"` → `"timetable.confirmed_download"` 키 이름 변경 |
| `_TIME_FIELDS` | 199-206 | `confirmed_download_time` → `timetable.confirmed_download` 치환 |
| `_TIMETABLE_ORDER_KEYS` | 138-142 | 2그룹 분리 — `_TIMETABLE_PRE_OPEN_KEYS`(기존 3개) + `_TIMETABLE_POST_CLOSE_KEYS`(신규 1개) (설계서 4-6) |
| `_validate_timetable_order()` | 145-191 | 2단계 검증 분리 — 그룹1: rt ≤ ws ≤ krx < 09:00 / 그룹2: confirmed_download > 20:00 |
| `select_keys` 확장 | 211-213 | `timetable.confirmed_download`가 data에 있으면 그룹2 검증용으로 추가 |

**⑤ `backend/app/core/settings_defaults.py`** (기본값)

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `"confirmed_download_time": "20:40"` | 20 | 제거 → `"timetable.confirmed_download": "20:40"`를 라인 123 아래에 추가 (네임스페이스 일관성, P23) |

**⑥ `backend/app/core/engine_settings.py`** (설정 스냅샷 빌드)

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `result["confirmed_download_time"]` | 279 | `result["timetable.confirmed_download"]`로 변경. 주석(278)도 함께 갱신 |

#### 프론트엔드 대상 파일

**⑦ `frontend/src/pages/general-settings.ts`** (약 1122줄)

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `scheduleConfirmedDlSave()` | 113-129 | 제거 → `scheduleTimetableSave()` 호출로 통합 (P23 일관성). `savingConfirmedDl` 변수(62)도 함께 제거 |
| `scheduleTimetableSave()` | 134-149 | 시그니처 확장 — `key` 매개변수 타입에 `'timetable.confirmed_download'` 추가. 기존 422 검증 에러 토스트 자동 적용 |
| `vals['confirmed_download_time']` | 118 | `vals['timetable.confirmed_download']`로 변경 |
| `{ confirmed_download_time: newVal }` | 121 | `{ 'timetable.confirmed_download': newVal }`로 변경 + `scheduleTimetableSave('timetable.confirmed_download', newVal)` 호출로 교체 |
| `vals.confirmed_download_time` | 312 | `vals['timetable.confirmed_download']`로 변경 |
| `r.confirmed_download_time` | 967 | `r['timetable.confirmed_download']`로 변경 |
| `confirmedDlSlot` 콜백 | 314-317 | `scheduleConfirmedDlSave()` → `scheduleTimetableSave('timetable.confirmed_download', ...)` 호출로 변경 |
| 모듈 상태 변수 | 59, 61, 62 | `confirmedDlSlot`, `confirmedDlH`, `confirmedDlM` 유지 (UI 요소는 그대로). `savingConfirmedDl`(62) 제거 |

**⑧ `frontend/src/types/index.ts`**

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `confirmed_download_time: string` | 150 | 제거 → `'timetable.confirmed_download': string` 추가 (기존 `timetable.*` 키 옆, P23) |

#### 테스트 대상 파일

**⑨ `backend/tests/test_daily_time_scheduler.py`** (약 2307줄 — 60곳 매치)

| 테스트 클래스 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| import 블록 | 60-61, 76 | `_fire_confirmed_download`, `schedule_ws_subscribe_timers` import 제거 (함수 제거 시) |
| `TestIsWsSubscribeWindow` | 935-995 | mock settings `{"confirmed_download_time": "20:40"}` → `{"timetable.confirmed_download": "20:40"}` (cosmetic — 함수 내부에서 키 미사용, P23 일관성) |
| `TestIsEditWindowOpen` | 1000-1015 | 동일 — mock settings 키 이름 치환 |
| `TestOnRealtimeFieldsReset` | 1327-1386 | 동일 — mock settings 키 이름 치환 (4곳) |
| `TestOnWsSubscribeStartIdempotency` | 1455-1506 | 동일 — mock settings 키 이름 치환 (3곳) |
| `TestInitWsSubscribeState` | 1576-1629 | 동일 — mock settings 키 이름 치환 (3곳) |
| `TestFireWrappers.test_fire_confirmed_download_schedules` | 1533-1536 | 제거 — `_fire_confirmed_download()` 함수 제거 시 |
| `TestOnConfirmedDownload` | 1546-1556 | 멱등성 가드 테스트 추가 — 같은 날 2회 호출 시 2회째 스킵 (신규 2개 테스트) |
| `TestScheduleWsSubscribeTimers` | 1943-1969 | 제거 또는 전환 — `schedule_ws_subscribe_timers()` 제거 시. 타임테이블 기반 테스트로 전환 검토 |
| `TestStartDailyTimeScheduler` | 1910-1938 | `schedule_ws_subscribe_timers` 모킹(1921) 제거 |
| `TestStopDailyTimeScheduler` | 1874-1905 | `ws_subscribe_timer_handles` 모킹(1883, 1901) 제거 |
| `TestRetryPipelineCatchup` | 2010-2062 | mock settings `{"confirmed_download_time": "20:40"}` → `{"timetable.confirmed_download": "20:40"}` (4곳, 실제 키 사용 — line 687) |
| `TestTimetableBuilder` | 2067-2134 | 11항목 빌드 테스트로 갱신 — `len(tt) == 11`, 11번째 direct 항목 검증 추가. 토글 OFF 시 스킵 테스트 추가 (신규) |
| `TestTimetableScheduler` | 2137-2234 | mock settings 키 이름 치환 (2234). direct 이벤트 멱등성 가드 테스트에 `last_confirmed_download_date` 추가 |
| `test_stop_cancels_timetable_timer` | 2295-2307 | `ws_subscribe_timer_handles` 모킹(2301) 제거 |
| `_on_midnight` 테스트 | 1777 | `schedule_ws_subscribe_timers` 모킹 제거 |

**⑩ `backend/tests/test_engine_settings.py`**

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `test_confirmed_download_time_default` | 327-329 | `test_timetable_confirmed_download_default`로 변경 — 키 이름 치환 |
| `test_confirmed_download_time_override` | 331-333 | 동일 — 키 이름 치환 |
| `TestApplySettingsChangeTimetableRebuild` | 404- | `_TIMETABLE_KEYS` 변경 반영 — `timetable.confirmed_download` + `scheduler_market_close_on` 추가 시 재빌드 검증 테스트 추가 |

**⑩ `backend/tests/test_settings_store.py`**

| 항목 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `_full_input()` | 83 | `"confirmed_download_time"` → `"timetable.confirmed_download"` |
| `test_no_changes` before | 205 | 동일 — 키 이름 치환 |
| `test_changed_value` before | 225 | 동일 — 키 이름 치환 |
| `TestValidateTimetableOrder` | 245-326 | 그룹2 검증 테스트 추가 — `timetable.confirmed_download` > 20:00 통과 / ≤ 20:00 시 ValueError (신규 2-3개 테스트) |
| `test_timetable_order_violation_raises` | 442-452 | 그룹1 검증 유지 + 그룹2 검증 추가 |
| `test_timetable_order_valid_saves` | 457-469 | 그룹2 통과 케이스 추가 |
| `test_timetable_select_keys_includes_all_three` | 472-487 | `timetable.confirmed_download` 포함 시 select_keys 확장 검증 추가 |

#### 문서 대상 파일

| 파일 | 위치 (줄) | 통합 시 영향 |
|---|---|---|
| `ARCHITECTURE.md` | 983, 1041 | 라인 983 `confirmed_download_time` → `timetable.confirmed_download` 갱신. 라인 1041 `ws_subscribe_timer_handles` 제거 + `last_confirmed_download_date` 추가 |
| `docs/krx_receive_rate_missing_investigation.md` | 87-250 (16곳) | **변경 없음** — 역사적 조사 기록 (AGENTS.md 코드 제거 규칙 3: "문제 기록의 역사적 로그는 유지") |

### 1-2. 영향 범위

- **백엔드**: 6개 파일 수정 (`daily_time_scheduler.py`, `engine_state.py`, `engine_service.py`, `settings_store.py`, `settings_defaults.py`, `engine_settings.py`)
- **프론트엔드**: 2개 파일 수정 (`general-settings.ts`, `types/index.ts`)
- **테스트**: 3개 파일 수정 (`test_daily_time_scheduler.py`, `test_engine_settings.py`, `test_settings_store.py`)
- **DB**: `stocks.db` 마이그레이션 — `integrated_system_settings` 테이블에서 key 1행 UPDATE (db-backup 스킬 선행)
- **문서**: `ARCHITECTURE.md` 2줄 갱신. 역사적 조사 문서는 유지
- **사용자 체감 변화**: 없음 (UI 입력칸, 다운로드 실행 시간, 토글 동작 모두 기존과 동일 — 설계서 섹션 10)

### 1-3. 아키텍처 원칙 부합 확인

| 원칙 | 부합 여부 | 비고 |
|---|---|---|
| P10 (SSOT) | ✓ | 모든 시간 키 `timetable.*` 네임스페이스 단일화. 단일 타임테이블 + 단일 타이머. `ws_subscribe_timer_handles` 제거로 타이머 SSOT 단일화 |
| P14 (단일 타이머) | ✓ | `state.timetable_timer_handle` 1개만 유지. `ws_subscribe_timer_handles` 리스트 제거 |
| P16 (살아있는 경로) | ✓ | 토글 OFF 시 타임테이블 엔트리 빌드 단계에서 스킵 — dead path(콜백 호출 후 아무 동작 없음) 제거. 부트스트랩 catch-up 유지 (기동 시 누락 방지 보완 경로). `schedule_ws_subscribe_timers()` 제거 전 호출자 3곳 확인 완료 → 모두 정리 |
| P20 (폴백 금지) | ✓ | 기존 `_cache_time()` 패턴 그대로 사용 — 캐시에 키 없으면 `DEFAULT_USER_SETTINGS` 기본값, 그것도 없으면 `ValueError`. silent `except: pass` 금지 (기존 `logger.warning(..., exc_info=True)` 패턴 유지) |
| P21 (사용자 투명성) | ✓ | UI에 이미 표시됨 (시간 설정 탭). 순서 검증 에러 시 422 응답 → 토스트 메시지 (기존 패턴 유지). 사용자 체감 변화 없음 |
| P22 (데이터 정합성) | ✓ | `state.last_confirmed_download_date` 멱등성 가드 추가 — 같은 날 중복 다운로드 차단. 기존 `last_realtime_reset_date`/`last_ws_subscribe_start_date`/`last_krx_pre_subscribe_date` 패턴과 동일. 자정 리셋 (`_on_midnight()`에서 `""`로 리셋). 기존 `confirmed_done` 플래그는 1차 가드로 유지 (이중 안전장치) |
| P23 (일관성) | ✓ | 시간 키 모두 `timetable.*` 패턴. 타임테이블 엔트리 모두 동일 dict 구조(`time`/`kind`/`action`/`ctx`). 저장 함수 `scheduleTimetableSave()`로 통합. `_on_confirmed_download()` 콜백 재사용 — 신규 함수 작성 금지. 멱등성 가드 패턴 기존 3개와 동일 |
| P24 (단순성) | ✓ | `schedule_ws_subscribe_timers()` 제거 (사실상 confirmed_download_time만 담당). `_fire_confirmed_download()` 동기 래퍼 제거. 단일 타임테이블 + 단일 타이머. `build_timetable_from_cache()` 10항목 → 11항목 (함수 50줄 이하 유지) |

### 1-4. 기존 공통 자산 확인 (P23 사전 절차)

통합에 필요한 모든 요소는 기존 공통 자산으로 충분:

| 자산 | 출처 | 용도 | 신규 생성 여부 |
|---|---|---|---|
| `_cache_time()` 내부 함수 | daily_time_scheduler.py:975-979 | 캐시→기본값→ValueError 3단계 조회 | 아니요 (재사용) |
| `_parse_hm_tuple()` | daily_time_scheduler.py:956-959 | HH:MM → (h, m) 파싱 | 아니요 (재사용) |
| `_on_confirmed_download()` 콜백 | daily_time_scheduler.py:913-919 | 확정 다운로드 트리거 | 아니요 (재사용, 가드만 추가) |
| `_fire_unified_confirmed_fetch()` | daily_time_scheduler.py:620-633 | 실제 다운로드 실행 | 아니요 (재사용) |
| `last_realtime_reset_date` 패턴 | engine_state.py:116 | 날짜 기반 멱등성 가드 모델 | 아니요 (동일 패턴 적용) |
| `scheduleTimetableSave()` | general-settings.ts:134-149 | 타임테이블 키 저장 + 422 토스트 | 아니요 (시그니처 확장만) |
| `schedule_engine_task()` | engine_lifecycle | 비동기 태스크 스케줄링 | 아니요 (재사용) |
| 타임테이블 dict 구조 (`time`/`kind`/`action`/`ctx`) | daily_time_scheduler.py:985-995 | 엔트리 표준 구조 | 아니요 (동일 구조) |
| `createTimeSlot`, `updateTimeSlotDisplay`, `parseHM` | components/common/settings-common | 시간 슬롯 UI | 아니요 (재사용) |
| `toastResult` | components/common/toast | 저장 결과 토스트 | 아니요 (재사용) |

→ **신규 함수/상수/컴포넌트 생성 없음**. 모든 기능은 기존 공통 자산의 재사용 또는 시그니처 확장으로 구현 (P23 일관성, P24 단순성).

---

## 2. 작업량 계산 및 단계 분할

### 2-1. 수정 포인트 목록

| # | 수정 포인트 | 파일 | 작업량 |
|---|---|---|---|
| A | DB 마이그레이션 — `confirmed_download_time` → `timetable.confirmed_download` key UPDATE | stocks.db | 중 (백업 선행) |
| B | `settings_defaults.py` 키 변경 + 이동 | settings_defaults.py:20, 123 | 소 |
| C | `engine_settings.py` 키 참조 변경 + 주석 갱신 | engine_settings.py:278-279 | 소 |
| D | `settings_store.py` `general_save_payload_from_flat()` 키 변경 | settings_store.py:74 | 소 |
| E | `settings_store.py` `_TIME_FIELDS` 키 치환 | settings_store.py:199-206 | 소 |
| F | `settings_store.py` `_TIMETABLE_ORDER_KEYS` 2그룹 분리 | settings_store.py:138-142 | 중 |
| G | `settings_store.py` `_validate_timetable_order()` 2단계 검증 분리 | settings_store.py:145-191 | 중 |
| H | `settings_store.py` `select_keys` 확장 | settings_store.py:211-213 | 소 |
| I | `test_settings_store.py` 키 치환 + 그룹2 검증 테스트 추가 | test_settings_store.py | 중 |
| J | `test_engine_settings.py` 키 치환 + 재빌드 테스트 갱신 | test_engine_settings.py | 소 |
| K | `engine_state.py` `ws_subscribe_timer_handles` 제거 + `last_confirmed_download_date` 추가 | engine_state.py:109, 118 | 소 |
| L | `daily_time_scheduler.py` `build_timetable_from_cache()` 11번째 항목 추가 + 토글 스킵 | daily_time_scheduler.py:962-996 | 중 |
| M | `daily_time_scheduler.py` `_on_confirmed_download()` 멱등성 가드 추가 | daily_time_scheduler.py:913-919 | 소 |
| N | `daily_time_scheduler.py` `_on_midnight()` 가드 리셋 + `schedule_ws_subscribe_timers` 호출 제거 | daily_time_scheduler.py:1390, 1410 | 소 |
| O | `daily_time_scheduler.py` `schedule_ws_subscribe_timers()` + `_fire_confirmed_download()` 제거 | daily_time_scheduler.py:908-910, 1122-1173 | 중 |
| P | `daily_time_scheduler.py` `start_daily_time_scheduler()` 호출 제거 | daily_time_scheduler.py:1494 | 소 |
| Q | `daily_time_scheduler.py` `stop_daily_time_scheduler()` `ws_subscribe_timer_handles` 블록 제거 | daily_time_scheduler.py:1517-1519 | 소 |
| R | `daily_time_scheduler.py` `retry_pipeline_catchup_after_bootstrap()` 키 참조 변경 | daily_time_scheduler.py:687 | 소 |
| S | `engine_service.py` `_WS_SCHEDULE_KEYS` 제거 + `_TIMETABLE_KEYS` 확장 + 분기 재작성 | engine_service.py:127-167 | 중 |
| T | `test_daily_time_scheduler.py` 키 치환 + 함수 제거 테스트 삭제 + 멱등성/토글 스킵 테스트 추가 | test_daily_time_scheduler.py | 대 (60곳) |
| U | `general-settings.ts` 키 참조 변경 (4곳) + `scheduleConfirmedDlSave()` 통합 | general-settings.ts | 중 |
| V | `types/index.ts` 키 변경 | types/index.ts:150 | 소 |
| W | `ARCHITECTURE.md` 2줄 갱신 | ARCHITECTURE.md:983, 1041 | 소 |
| X | 최종 검증 (런타임 기동 + 전체 회귀 + 브라우저) | — | 중 |

### 2-2. 단계 분할 (3세션 × 1단계 — 설계서 섹션 7 준거)

> 규칙 0-1(세션당 1단계) 준수. 3세션(구현) 분할 — 설계서(1세션) + 본 태스크 파일(2세션) 완료 후 3세션부터 구현.

#### 3세션: DB 마이그레이션 + 백엔드 키 변경 (A, B, C, D, E, F, G, H, I, J)

**목표**: DB 스키마(키 이름) 마이그레이션 + 백엔드 설정 키 참조 전환 + 순서 검증 2그룹 분리. 타임테이블 엔트리 추가/타이머 통합은 4세션에서 수행 (본 세션에서는 타임테이블 로직 미수정).

**세션 내 순서** (한 세션에서 완료하되 순서 엄수):
1. **db-backup 스킬 호출** → `stocks.db`, `stocks.db-shm`, `stocks.db-wal` 타임스탬프 백업 (Safety Rules 2)
2. **DB 마이그레이션 스크립트 실행** — `integrated_system_settings` 테이블에서 `key='confirmed_download_time'` → `key='timetable.confirmed_download'` UPDATE. 값은 그대로 유지. 마이그레이션 전후 행 수 검증 (1행 → 1행). 실패 시 백업에서 즉시 복원 (사용자 승인 후)
3. **settings_defaults.py** (B) — `confirmed_download_time` 제거, `timetable.confirmed_download` 추가 (라인 123 아래)
4. **engine_settings.py** (C) — 키 참조 + 주석 갱신
5. **settings_store.py** (D, E, F, G, H) — `general_save_payload_from_flat()` 키 변경 + `_TIME_FIELDS` 치환 + `_TIMETABLE_ORDER_KEYS` 2그룹 분리 + `_validate_timetable_order()` 2단계 검증 + `select_keys` 확장
6. **test_settings_store.py** (I) — 키 치환 + 그룹2 검증 테스트 추가 (통과/실패 케이스)
7. **test_engine_settings.py** (J) — 키 치환 + 재빌드 테스트 갱신

**주의**: 본 세션에서는 `daily_time_scheduler.py`의 `confirmed_download_time` 참조(line 687, 1157)를 그대로 유지 — 4세션에서 타임테이블 통합 시 함께 변경. 단, 이로 인해 3세션 완료 후 런타임 기동 시 `retry_pipeline_catchup_after_bootstrap()`과 `schedule_ws_subscribe_timers()`가 `KeyError` 발생 가능 → **3세션에서는 런타임 기동 검증 생략**하고 정적 검증(py_compile + ruff + 단위 테스트)만 수행. 런타임 기동은 4세션 완료 후 수행.

> **대안 검토**: 3세션에서 `daily_time_scheduler.py`의 키 참조 2곳(line 687, 1157)만 임시로 신규 키로 변경하면 런타임 기동 가능. 단, 이 경우 4세션에서 타임테이블 통합 시 다시 수정해야 하므로 중복 수정 발생. **설계서 의도(3세션=키 변경, 4세션=타임테이블 통합) 준수하여 런타임 기동은 4세션으로 이월**.

**검증 항목**:
- [ ] db-backup 스킬로 백업 완료 (3개 파일 타임스탬프 백업)
- [ ] DB 마이그레이션 전후 행 수 검증 (1행 → 1행)
- [ ] 마이그레이션 후 `timetable.confirmed_download` 키로 값 조회 성공 (기존 값 보존)
- [ ] `py_compile` 전체 통과
- [ ] `ruff check` 통과
- [ ] `pytest test_settings_store.py` 전체 통과 (그룹2 검증 테스트 포함)
- [ ] `pytest test_engine_settings.py` 전체 통과
- [ ] `confirmed_download_time` 잔존 참조 없음 (백엔드 설정 계층에서 — `daily_time_scheduler.py` 2곳은 4세션에서 처리하므로 예외)

#### 4세션: 타임테이블 통합 + 멱등성 가드 (K, L, M, N, O, P, Q, R, S, T)

**목표**: 타임테이블 11번째 항목 추가 + 멱등성 가드 + `schedule_ws_subscribe_timers()` 제거 + 부트스트랩 catch-up 키 참조 변경 + 설정 변경 감지 분기 재작성. 단일 타임테이블 + 단일 타이머 완성.

**세션 내 순서**:
1. **engine_state.py** (K) — `ws_subscribe_timer_handles` 제거 + `last_confirmed_download_date: str = ""` 추가
2. **daily_time_scheduler.py** (L) — `build_timetable_from_cache()` 11번째 항목 추가 (토글 OFF 시 스킵, `_on_confirmed_download` 콜백, `kind="direct"`)
3. **daily_time_scheduler.py** (M) — `_on_confirmed_download()` 멱등성 가드 추가 (`last_confirmed_download_date == today_str` 시 스킵)
4. **daily_time_scheduler.py** (N) — `_on_midnight()` 가드 리셋 추가 + `schedule_ws_subscribe_timers(settings)` 호출 제거. 자정 타임테이블 재빌드 검토 (주의사항 1-1 참조)
5. **daily_time_scheduler.py** (O) — `schedule_ws_subscribe_timers()` 함수 + `_fire_confirmed_download()` 동기 래퍼 제거. 타임테이블 direct 콜백이 비동기 `_on_confirmed_download()`를 `schedule_engine_task()`로 래핑하는 패턴 확인 (기존 `_on_realtime_fields_reset` 등 direct 항목 패턴과 일치)
6. **daily_time_scheduler.py** (P, Q) — `start_daily_time_scheduler()` 호출 제거 + `stop_daily_time_scheduler()` 블록 제거
7. **daily_time_scheduler.py** (R) — `retry_pipeline_catchup_after_bootstrap()` 키 참조 변경 (line 687)
8. **engine_service.py** (S) — `_WS_SCHEDULE_KEYS` 제거 + `_TIMETABLE_KEYS`에 `timetable.confirmed_download` + `scheduler_market_close_on` 추가 + 분기 재작성 (토글 변경 시 타임테이블 재빌드 + 구간 재판정)
9. **test_daily_time_scheduler.py** (T) — import 정리 + mock settings 키 치환(60곳 중 cosmetic 50곳 + 실제 10곳) + `TestScheduleWsSubscribeTimers` 제거/전환 + `TestFireWrappers.test_fire_confirmed_download_schedules` 제거 + `TestOnConfirmedDownload` 멱등성 가드 테스트 2개 추가 + `TestTimetableBuilder` 11항목/토글 스킵 테스트 추가 + `TestStopDailyTimeScheduler`/`TestStartDailyTimeScheduler` 모킹 정리

**검증 항목**:
- [ ] `py_compile` 전체 통과
- [ ] `ruff check` 통과
- [ ] `pytest test_daily_time_scheduler.py` 전체 통과 (멱등성 가드 + 토글 스킵 + 11항목 빌드 테스트 포함)
- [ ] `pytest` 전체 회귀 (test_settings_store + test_engine_settings + 기타) 통과
- [ ] 런타임 기동 — `python -W error::RuntimeWarning main.py` RuntimeWarning 0건
- [ ] 런타임 기동 후 잔존 프로세스 0건 (기동 종료 시 정상 정리)
- [ ] 기동 로그에 "타임테이블 빌드 완료 — 11항목" 표시
- [ ] `schedule_ws_subscribe_timers` 잔존 참조 없음 (코드 + 테스트)
- [ ] `_fire_confirmed_download` 잔존 참조 없음 (코드 + 테스트)
- [ ] `ws_subscribe_timer_handles` 잔존 참조 없음 (코드 + 테스트 + ARCHITECTURE.md 제외 — 5세션에서 갱신)
- [ ] `confirmed_download_time` 잔존 참조 없음 (코드 + 테스트 — 프론트엔드는 5세션)

#### 5세션: 프론트엔드 + 최종 검증 + 계획서 삭제 (U, V, W, X)

**목표**: 프론트엔드 키 참조 변경 + 저장 함수 통합 + ARCHITECTURE.md 갱신 + 최종 검증 + 설계서/태스크 파일 삭제 (규칙 11).

**세션 내 순서**:
1. **types/index.ts** (V) — `confirmed_download_time` 제거 + `'timetable.confirmed_download': string` 추가
2. **general-settings.ts** (U) — `scheduleConfirmedDlSave()` 제거 → `scheduleTimetableSave()` 시그니처 확장 + 4곳 키 참조 변경 + `savingConfirmedDl` 변수 제거
3. **ARCHITECTURE.md** (W) — 라인 983 `confirmed_download_time` → `timetable.confirmed_download` 갱신 + 라인 1041 `ws_subscribe_timer_handles` 제거 + `last_confirmed_download_date` 추가
4. **최종 검증** (X) — typecheck + build + vitest + 런타임 기동 + 브라우저 확인 (사용자)
5. **계획서 삭제** (규칙 11) — `docs/architecture_download_timetable_integration_design.md` + `docs/plan_download_timetable_integration.md` 삭제

**검증 항목**:
- [ ] `npm run typecheck` (또는 프로젝트 타입체크 명령) 통과
- [ ] `npm run build` 통과
- [ ] `npm run test` (vitest) 전체 통과
- [ ] 런타임 기동 — `python -W error::RuntimeWarning main.py` RuntimeWarning 0건 + 잔존 프로세스 0건
- [ ] 브라우저 확인 (사용자) — 시간 설정 탭 "1일봉차트 자동다운로드" 섹션 표시 + 시간 슬롯 + 토글 + 저장 동작 정상
- [ ] 브라우저 확인 (사용자) — 순서 검증 에러 시 토스트 메시지 표시 (20:40 → 20:00 이하로 변경 시 422)
- [ ] `confirmed_download_time` 잔존 참조 없음 (전체 코드베이스 — 역사적 조사 문서 제외)
- [ ] 계획서 2개 삭제 완료 (규칙 11)

---

## 3. 단계별 상세 구현 계획

### 3-1. 3세션 상세 — DB 마이그레이션 + 백엔드 키 변경

#### DB 마이그레이션 스크립트 (일회성, 세션 내 실행 후 삭제 검토)

```sql
-- 마이그레이션 전 검증
SELECT COUNT(*) FROM integrated_system_settings WHERE key = 'confirmed_download_time';
-- 예상: 1

-- 마이그레이션
UPDATE integrated_system_settings
SET key = 'timetable.confirmed_download'
WHERE key = 'confirmed_download_time';

-- 마이그레이션 후 검증
SELECT COUNT(*) FROM integrated_system_settings WHERE key = 'timetable.confirmed_download';
-- 예상: 1
SELECT COUNT(*) FROM integrated_system_settings WHERE key = 'confirmed_download_time';
-- 예상: 0
```

- 값은 그대로 유지 (사용자 설정값 보존)
- 실패 시 백업에서 즉시 복원 (사용자 승인 후 — 규칙 0-3)

#### settings_store.py 순서 검증 2그룹 분리 (F, G, H)

```python
# 그룹 1: 장 전 사전 준비 (기존 3개 키)
_TIMETABLE_PRE_OPEN_KEYS = (
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
)
# 검증: rt <= ws <= krx < 09:00

# 그룹 2: 장 후 확정 다운로드 (신규 1개 키)
_TIMETABLE_POST_CLOSE_KEYS = (
    "timetable.confirmed_download",
)
# 검증: confirmed_download > 20:00 (NXT 장마감 이후만 허용)
```

- `_validate_timetable_order()`를 2개 검증 단계로 분리
- 그룹2는 상한선 없음 (사용자가 23:50까지 설정 가능 — 증권사 확정 데이터 준비 지연 대비)
- `select_keys` 확장: `timetable.confirmed_download`가 data에 있으면 그룹2 검증용으로 추가

### 3-2. 4세션 상세 — 타임테이블 통합 + 멱등성 가드

#### build_timetable_from_cache() 11번째 항목 (L)

```python
# 11번째 항목 — 확정 데이터 다운로드 (timetable.confirmed_download)
# 토글 OFF 시 엔트리 스킵 (P16 살아있는 경로 — dead path 제거)
scheduler_close_on = bool(settings.get("scheduler_market_close_on", True))
if scheduler_close_on:
    cd = _cache_time("timetable.confirmed_download")
    entries.append({
        "time": cd,
        "kind": "direct",
        "action": _on_confirmed_download,
        "ctx": f"확정 데이터 다운로드 ({cd[0]:02d}:{cd[1]:02d})",
    })
```

- `kind="direct"` — 사전 트리거 3개와 동일 패턴 (P23)
- 토글 OFF 시 엔트리 자체 스킵 → 콜백 내부 게이트 불필요 (P16)
- direct 콜백이 비동기 `_on_confirmed_download()`인 경우의 실행 패턴 — 기존 `_on_realtime_fields_reset` 등 direct 항목이 `schedule_engine_task()`로 래핑되는지 `_timetable_event_fired()` 확인 필요 (4세션에서 검증)

#### _on_confirmed_download() 멱등성 가드 (M)

```python
async def _on_confirmed_download() -> None:
    try:
        today_str = _kst_now().strftime("%Y%m%d")
        if state.last_confirmed_download_date == today_str:
            logger.debug("[스케줄] 확정 다운로드 오늘 이미 실행 — 스킵 (P22)")
            return
        logger.info("[스케줄] 확정 시세 다운로드 시각 도달 → 확정 데이터 다운로드 트리거")
        _fire_unified_confirmed_fetch()
        state.last_confirmed_download_date = today_str
    except Exception as e:
        logger.warning("[스케줄] 확정 데이터 다운로드 콜백 오류: %s", e, exc_info=True)
```

- 기존 `last_realtime_reset_date` 패턴과 동일 (P23)
- 기존 `confirmed_done` 플래그는 `_fire_unified_confirmed_fetch()` 내 1차 가드로 유지 (이중 안전장치)

#### schedule_ws_subscribe_timers() 제거 시 주의 (O)

- 타임테이블 direct 콜백이 비동기 함수를 직접 호출하는 패턴 확인 — `_timetable_event_fired()`에서 `kind="direct"`일 때 `action()` 호출 방식 확인
- 기존 `_fire_confirmed_download()`는 `schedule_engine_task(_on_confirmed_download(), ...)`로 래핑 — 타임테이블이 동일 래핑을 제공하는지 확인, 미제공 시 `_fire_confirmed_download()` 유지 또는 타임테이블 콜백을 동기 래퍼로 지정

#### engine_service.py 분기 재작성 (S)

```python
# _WS_SCHEDULE_KEYS 제거 (confirmed_download_time 키 자체 제거)
# _TIMETABLE_KEYS에 timetable.confirmed_download + scheduler_market_close_on 추가
_TIMETABLE_KEYS = {
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
    "timetable.confirmed_download",      # 신규 — 시간 키
    "scheduler_market_close_on",         # 신규 — 토글 변경 시 타임테이블 재빌드 필요
}
if changed_keys & _TIMETABLE_KEYS:
    # 기존 재빌드 + 재예약 로직 (변경 없음)
    _dts_mod._TIMETABLE = build_timetable_from_cache(state.integrated_system_settings_cache)
    _schedule_next_timetable_event()
```

- `scheduler_market_close_on` 토글 변경 시에도 타임테이블 재빌드 필요 (엔트리 스킵/추가)
- 기존 `_WS_SCHEDULE_KEYS` 분기의 "활성→구간밖 즉시 구독 해제" / "비활성→구간안 즉시 구독 시작" 로직은 `scheduler_market_close_on`만 남으므로 별도 분기 유지 검토 (또는 `_TIMETABLE_KEYS` 분기 내부로 통합)

### 3-3. 5세션 상세 — 프론트엔드 + 최종 검증 + 계획서 삭제

#### scheduleConfirmedDlSave() 통합 (U)

```typescript
// 기존 scheduleConfirmedDlSave() 제거 → scheduleTimetableSave() 호출로 통일
confirmedDlSlot = createTimeSlot(confirmedDlH, confirmedDlM, (h, m) => {
  confirmedDlH = h; confirmedDlM = m; updateTimeSlotDisplay(confirmedDlSlot!, h, m)
  scheduleTimetableSave('timetable.confirmed_download', `${h}:${m}`)
})
```

- `scheduleTimetableSave()` 시그니처의 `key` 매개변수 타입에 `'timetable.confirmed_download'` 추가
- 422 검증 에러 토스트 자동 적용 (기존 `scheduleTimetableSave`가 이미 `toastResult` 호출)
- `savingConfirmedDl` 변수 제거 (중복 상태 변수 — `savingTimetable`으로 통합)

---

## 4. 위험 요소 및 완화

| 위험 | 완화 |
|------|------|
| DB 마이그레이션 실패 | db-backup 스킬로 백업 후 진행, 실패 시 즉시 복원 (사용자 승인 후 — 규칙 0-3). 마이그레이션 전후 행 수 검증 (1행 → 1행) |
| 기존 사용자 설정값 손실 | UPDATE 시 값은 그대로 유지, key만 변경. 마이그레이션 전후 값 비교 검증 |
| 3세션 완료 후 런타임 기동 시 KeyError | 3세션에서는 런타임 기동 검증 생략, 정적 검증만 수행. 런타임 기동은 4세션 완료 후 수행 (설계서 의도 준수) |
| 멱등성 가드 자정 리셋 누락 | 기존 `last_realtime_reset_date` 리셋 위치(`_on_midnight()` line 1390)와 동일하게 처리. 리셋 누락 시 다음 날 다운로드 안 됨 → 런타임 기동 시 가드 리셋 보완 |
| 부트스트랩 catch-up과 타임테이블 타이머 중복 | 멱등성 가드가 2차 차단 (이중 안전장치). 부트스트랩이 먼저 실행되더라도 가드가 타임테이블 타이머의 중복 호출 차단 |
| `schedule_ws_subscribe_timers()` 제거 시 자정 타이머 재예약 누락 | 타임테이블 타이머가 다음 미래 이벤트를 자동 예약하므로 20:40도 포함. 단, 자정 리셋 후 타임테이블 재빌드 필요 — `_on_midnight()`에서 `_TIMETABLE` 재빌드 + `_schedule_next_timetable_event()` 호출 추가 검토 (4세션에서 보완) |
| `_fire_confirmed_download()` 제거 시 타임테이블 direct 콜백 패턴 불일치 | 타임테이블이 비동기 `_on_confirmed_download()`를 직접 호출 시 `schedule_engine_task()` 래핑 필요. 기존 `_on_realtime_fields_reset` 등 direct 항목의 실행 패턴 확인 후 결정 — 4세션에서 `_timetable_event_fired()` 검증 |
| 토글 OFF 시 부트스트랩 catch-up 동작 | 부트스트랩 catch-up은 `scheduler_market_close_on` 토글 확인 후 실행 (토글 OFF 시 스킵). 타임테이블 엔트리 스킵과 일관성 유지 — 4세션에서 `retry_pipeline_catchup_after_bootstrap()`에 토글 확인 추가 검토 |
| 테스트 60곳 키 치환 누락 | 4세션에서 `confirmed_download_time` 전체 검색으로 잔존 참조 확인. cosmetic 50곳(is_ws_subscribe_window mock) + 실제 10곳(retry_pipeline_catchup) 구분 처리 |

---

## 5. 참조 규칙

- AGENTS.md 섹션3 규칙 0 (승인 전 수정 금지)
- AGENTS.md 섹션3 규칙 0-1 (세션당 1단계)
- AGENTS.md 섹션3 규칙 0-2 (수정 전 사전조사) — 본 태스크 파일이 2세션 사전조사 산출물
- AGENTS.md 섹션3 규칙 0-3 (사용자 승인 없는 롤백 금지) — DB 마이그레이션 실패 시 복원은 사용자 승인 후 진행
- AGENTS.md 섹션4 "다단계 작업 워크플로우" (설계→태스크→구현 3세션)
- AGENTS.md 섹션4 규칙 11 (계획서 삭제) — 5세션에서 설계서 + 본 태스크 파일 삭제
- Safety Rules 2 (DB 스키마 변경 전 백업) — db-backup 스킬 선행 (3세션)
- P10/P14/P16/P20/P21/P22/P23/P24 (아키텍처 불변 원칙)

---

## 6. 다음 세션 진행 대기

> 본 태스크 파일(2세션) 완료. 3세션(DB 마이그레이션 + 백엔드 키 변경) 진행은 사용자 명시적 실행 지시어 대기.
