# 설계서: 타임테이블 DB 저장 방식 (DB-backed Timetable)

> **상태**: 설계 완료 · 구현 승인 대기
> **작성일**: 2026-07-18
> **전신**: 타임테이블 스케줄러(`daily_time_scheduler.py:951-962`의 `_TIMETABLE` 파이썬 리스트) — 코드 내 고정에서 DB 기반 사용자 조정 가능으로 진화
> **관련 원칙**: P10(SSOT) · P13(설정 메모리 상주) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 1. 배경 및 목적

### 1-1. 현재 상태
- 타임테이블 스케줄러는 `daily_time_scheduler.py:951-962`의 `_TIMETABLE: list[dict]` 파이썬 리스트(10항목)로 구현
- 시간표 변경 시 코드 수정 + 앱 재시작 필요
- 사용자가 구독/해지 시간을 UI에서 조정 불가

### 1-2. 목적
- 타임테이블 중 **사용자 조정 가능 3개 시각**을 DB에 저장 → 설정 페이지에서 수정
- 앱 재시작 없이 시간표 변경 반영 (저장 즉시 타이머 재예약)
- 거래소 고정 시간(09:00, 15:20, 20:00 등 7개)은 코드 상수 유지 → 사용자가 임의 변경 차단
- 사용자가 "왜 이 시간에 구독이 시작되지?" 의문을 갖지 않도록 UI에 표시 (P21)

### 1-3. 범위 제한 (사용자 결정)
- **DB 저장 대상 (3개)**: `realtime_reset`(07:58), `ws_prestart`(07:59), `krx_pre_subscribe`(08:59)
- **코드 상수 유지 (7개)**: 08:00, 09:00, 15:20, 15:30, 15:40, 18:00, 20:00 (거래소 실제 스케줄)
- **저장 방식**: 방식 B (key-value 평면, `timetable.*` 네임스페이스) — 기존 `integrated_system_settings` 테이블 재사용, 신규 테이블 생성 안 함

---

## 2. 확정된 설계 결정 (사용자 승인)

### 2-1. 방식 B 채택 — key-value 평면

```
key                                value      value_type
─────────────────────────────────  ────────  ──────────
timetable.realtime_reset           07:58     string
timetable.ws_prestart              07:59     string
timetable.krx_pre_subscribe        08:59     string
```

- 기존 `integrated_system_settings` 테이블 스키마 그대로 사용 (마이그레이션 불필요 → Safety Rule 2 백업 부담 감소)
- 기존 `save_selected_settings` / `load_selected_settings` / `apply_settings_updates` / 저널링(`record_settings_change`) 그대로 재사용 (P23 일관성)
- 항목 단위 증분 저장·저널링 → "07:59 → 07:55" 변경 추적 가능 (감시성 향상)
- UI 폼 3개 입력칸이 3개 키와 1:1 매핑 → 프론트엔드 구조 단순 (P24)

### 2-2. SSOT 경계 분할 (P10)

| 데이터 | SSOT | 비고 |
|---|---|---|
| 시각(3개 사용자 조정) | DB (`integrated_system_settings`) | 사용자가 UI에서 변경 |
| 시각(7개 거래소 고정) | 코드 상수 (`daily_time_scheduler.py:21-49`) | 거래소 실제 스케줄, 변경 불가 |
| 동작 종류(`kind`)·콜백(`action`)·컨텍스트(`ctx`) | 코드 (`_TIMETABLE` 리스트) | 콜러블은 DB 직렬화 불가 → 코드가 SSOT |

→ 시각만 DB가 SSOT, 동작 정의는 코드가 SSOT. 경계 명확히 분리.

### 2-3. 시간 순서 검증 (P20/P22, 필수)

사용자가 잘못된 시간을 입력하는 경우(예: 09:30, 07:55→08:30 역순)를 즉시 차단:
- **검증 조건**: `realtime_reset ≤ ws_prestart ≤ krx_pre_subscribe < 09:00`
- **실패 시 처리**: 기본값 폴백 금지(P20) → 즉시 거부 + UI 에러 메시지 표시(P21)
- **형식 검증**: 기존 `_TIME_RE = re.compile(r"^\d{2}:\d{2}$")` 패턴 재사용 (P23)
- **범위 검증**: 시각은 `00:00`~`23:59`, 사용자 조정 3개는 모두 `08:59` 이전이어야 함 (정규장 09:00 시작 전 사전 준비 구간)

---

## 3. 아키텍처 원칙 준수

| 원칙 | 준수 내용 |
|---|---|
| **P10 (SSOT)** | 시각=DB SSOT, 동작 정의=코드 SSOT로 경계 분할. `DEFAULT_USER_SETTINGS`에 3개 키 기본값 추가 → 기본값 경로 단일화 |
| **P13 (설정 메모리 상주)** | 기동 시 `state.integrated_system_settings_cache`에 로드 후 스케줄러는 캐시 참조. 틱/스케줄 연산 단계에서 DB 조회 금지 |
| **P16 (살아있는 경로)** | 저장 후 `_schedule_next_timetable_event()` 재호출이 `apply_settings_change()` 실제 경로에 연결되어야 함 (WS 이벤트 핸들러까지 배선) |
| **P20 (폴백 금지)** | 시간 순서 위반·형식 오류 시 기본값 폴백 금지 → 즉시 거부 + UI 안내. silent `except: pass` 금지 |
| **P21 (사용자 투명성)** | 거래소 고정 7개 시간을 UI에 참고용 표시(수정 불가 칩). 변경 시 즉시 반영 여부 UI 표시 |
| **P22 (데이터 정합성)** | 시간 순서 위반 시 즉시 차단 — 잘못된 시각이 스케줄러에 반영되어 구독 누락 구간 발생하는 것을 방지 |
| **P23 (일관성)** | 기존 `apply_settings_updates`/`save_selected_settings`/`_TIME_RE`/`createToggleBtn` 패턴 재사용. 용어 사전 준수 ("구독" 등) |
| **P24 (단순성)** | 신규 테이블 생성 없이 기존 `integrated_system_settings` 재사용. 10항목 중 7개 상수는 코드 유지 → DB 부담 최소화 |

---

## 4. 백엔드 설계

### 4-1. 설정 키 추가 (Step 1)
**파일**: `backend/app/core/settings_defaults.py`

`DEFAULT_USER_SETTINGS`에 3개 키 추가:
```python
# 타임테이블 사용자 조정 시각 (장 시작 전 사전 준비 — P10 SSOT 기본값)
"timetable.realtime_reset": "07:58",      # 실시간 항목 초기화
"timetable.ws_prestart": "07:59",         # WS 구독 사전 시작
"timetable.krx_pre_subscribe": "08:59",   # KRX 정규장 사전 구독
```

- 기본값은 현재 코드 상수(`REALTIME_FIELDS_RESET_TIME` 등)와 동일 — 변경 없는 한 기존 동작 보존
- P13/P17: `integrated_system_settings_cache`에서만 관리

### 4-2. 시간 순서 검증 함수 (Step 2)
**파일**: `backend/app/core/settings_store.py`

`apply_settings_updates()` 내 기존 `_TIME_FIELDS` 검증 로직 확장:
- 기존 `_TIME_FIELDS` 집합에 3개 키 추가:
  ```python
  _TIME_FIELDS = frozenset({
      "confirmed_download_time",
      "buy_time_start", "buy_time_end",
      "sell_time_start", "sell_time_end",
      "timetable.realtime_reset",
      "timetable.ws_prestart",
      "timetable.krx_pre_subscribe",
  })
  ```
- 신규 검증 함수 `_validate_timetable_order(data: dict) -> None` 추가:
  - 3개 키 중 하나라도 `data`에 포함 시, DB에서 나머지 2개 키의 현재값을 로드(`load_selected_settings`)하여 3개 모두 검증
  - 검증 순서: `realtime_reset ≤ ws_prestart ≤ krx_pre_subscribe < "09:00"`
  - 위반 시 `ValueError` 발생 → `apply_settings_updates` 호출자가 HTTP 422로 변환 (기존 패턴)
  - 형식 오류(`_TIME_RE` 위반)는 기존 로직이 이미 무시+경고 → 신규 함수에서는 형식 통과한 값만 순서 검증

### 4-3. _TIMETABLE 빌더 함수 (Step 3)
**파일**: `backend/app/services/daily_time_scheduler.py`

현재 `_TIMETABLE` 모듈 전역 리스트를 **기동 시 캐시 기반으로 빌드**하는 구조로 변경:
- 기존 `_TIMETABLE: list[dict] = [...]` 제거 (사용자 설계 로직 변경 — 규칙 0-5 적용, 승인 후 진행)
- 신규 함수 `build_timetable_from_cache(settings: dict) -> list[dict]` 추가:
  - 인자: `state.integrated_system_settings_cache` 스냅샷
  - 반환: 기존과 동일한 dict 리스트 10항목 (kind/action/ctx 그대로, time 필드만 3개는 캐시값·7개는 코드 상수)
  - 캐시에 키가 없으면 `DEFAULT_USER_SETTINGS` 기본값 사용 (P10)
  - P24: 함수 50줄 이하, 복잡도 O(n) n=10
- 모듈 전역 `_TIMETABLE: list[dict]`는 빈 리스트로 초기화 후 기동 시 채움 (P16: 빈 리스트 상태로 스케줄러 동작 금지 → 기동 시 반드시 빌드 호출)
- `_schedule_next_timetable_event()`는 전역 `_TIMETABLE`를 그대로 참조 (기존 로직 변경 최소화)

### 4-4. 기동 시 타임테이블 빌드 배선 (Step 4)
**파일**: `backend/app/services/engine_bootstrap.py` (또는 `engine_config.py`의 캐시 로드 완료 지점)

엔진 기동 시 `state.integrated_system_settings_cache` 로드 완료 후:
```python
from backend.app.services.daily_time_scheduler import build_timetable_from_cache
state._TIMETABLE = build_timetable_from_cache(state.integrated_system_settings_cache)
```
- P16: 빌드 호출이 실제 기동 경로에 연결되어야 함 (dead code 금지)
- 기동 순서: 캐시 로드 → 타임테이블 빌드 → `_schedule_next_timetable_event()` 최초 호출

### 4-5. 저장 후 타이머 재예약 배선 (Step 5)
**파일**: `backend/app/services/engine_service.py`의 `apply_settings_change()`

기존 `_TIME_SCHEDULE_KEYS` / `_WS_SCHEDULE_KEYS` 분기 패턴 재사용 (P23):
```python
_TIMETABLE_KEYS = {
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
}
if changed_keys & _TIMETABLE_KEYS:
    try:
        from backend.app.services.daily_time_scheduler import (
            build_timetable_from_cache, _schedule_next_timetable_event,
        )
        state._TIMETABLE = build_timetable_from_cache(state.integrated_system_settings_cache)
        _schedule_next_timetable_event()  # 기존 타이머 취소 후 재예약 (P14 단일 타이머 유지)
        logger.info("[설정] 타임테이블 변경 감지 — 타이머 재예약 완료")
    except Exception:
        logger.warning("[설정] 타임테이블 재빌드/재예약 실패", exc_info=True)
```
- P14: `_schedule_next_timetable_event()` 내부에서 기존 `timetable_timer_handle.cancel()` 후 재예약 → 단일 타이머 유지
- P16: `apply_settings_change` 실제 경로에 연결 → 저장 후 즉시 반영
- 엔진 미실행 시: `save_pending_settings` 경로로 DB에만 저장, 다음 기동 시 빌드됨 (기존 패턴 준수)

### 4-6. WS 이벤트 (Step 6, 옵션)
**파일**: `backend/app/services/engine_ws_dispatch.py` 또는 `engine_account_notify.py`

타임테이블 변경 시 데스크톱에 알림 (기존 `notify_desktop_settings_toggled` 재사용):
- `apply_settings_change` 내 4) 일반 설정 변경 분기에서 `changed_dict`에 3개 키가 자동 포함됨 (별도 이벤트 불필요)
- 단, "다음 이벤트까지 남은 시간"을 UI에 표시하려면 별도 이벤트 추가 가능 — 본 설계에서는 최소 범위 유지 (P24)

---

## 5. 프론트엔드 설계

### 5-1. 설정 페이지 입력칸 (Step 7)
**파일**: `frontend/src/pages/general-settings.ts` (또는 스케줄 설정 섹션)

기존 `buy_time_start`/`buy_time_end` 입력칸 패턴 재사용 (P23):
- **위치**: "자동매매" 섹션의 시간 설정 행 아래, "장 시작 전 사전 준비 시간" 카드 신규 추가
- **입력칸 3개** (HH:MM time input):
  - "실시간 항목 초기화 시간" → `timetable.realtime_reset` (기본 07:58)
  - "구독 사전 시작 시간" → `timetable.ws_prestart` (기본 07:59)
  - "정규장 사전 구독 시간" → `timetable.krx_pre_subscribe` (기본 08:59)
- **설명 텍스트** (사용자 "코딩 1도 모름" 전제, 일반 용어):
  - 카드 상단: "장 시작 전 사전 준비 시간을 설정합니다. 너무 늦으면 실시간 데이터가 누락될 수 있습니다."
  - 각 입력칸 아래 한 줄 설명 (예: "장 시작 1분 전에 실시간 데이터 수신을 시작합니다")
- **저장 버튼**: 기존 "일반 설정 저장" 플로우 재사용 → `PATCH /api/settings/{field_name}` 3회 호출 또는 일괄 저장

### 5-2. 거래소 고정 시간 참고 표시 (Step 8)
**파일**: 동일 페이지 카드 하단

- "참고: 거래소 고정 시간 (변경 불가)" 접이식 영역
- 7개 시간을 칩 형태로 표시 (수정 불가 `disabled` 스타일):
  - 08:00 NXT 프리마켓 / 09:00 정규장 시작 / 15:20 정규장 종료 / 15:30 종가 동시호가 종료 / 15:40 NXT 애프터마켓 / 18:00 애프터마켓 지속 / 20:00 장마감
- P21: 사용자가 "이 시간들은 왜 수정 못 하지?" 의문 갖지 않도록 "거래소 실제 스케줄" 명시

### 5-3. 검증 에러 표시 (Step 9)
**파일**: 동일 페이지

- 저장 응답이 HTTP 422인 경우 기존 에러 토스트 패턴 재사용
- 에러 메시지 일반 용어화 (예: "시간 순서가 맞지 않습니다. 실시간 초기화 ≤ 구독 시작 ≤ 정규장 사전 구독 순서여야 합니다")
- P21: 사용자가 어떤 값을 고쳐야 하는지 명확히 안내

---

## 6. 데이터 흐름

### 6-1. 기동 시
```
엔진 기동
  → load_integrated_system_settings() (DB 로드)
  → state.integrated_system_settings_cache 갱신 (P13)
  → build_timetable_from_cache(cache) → state._TIMETABLE 채움
  → _schedule_next_timetable_event() (최초 타이머 예약)
```

### 6-2. 사용자 시간표 변경 시
```
UI 입력칸 수정 → PATCH /api/settings/timetable.ws_prestart
  → apply_settings_updates()
    → _validate_timetable_order(data) (P20/P22, 실패 시 422)
    → save_selected_settings() (DB 증분 저장)
    → record_settings_change() (저널링)
  → apply_settings_change(changed_keys)
    → refresh_engine_integrated_system_settings_cache() (캐시 갱신)
    → _TIMETABLE_KEYS 분기:
      → build_timetable_from_cache(cache) → state._TIMETABLE 재빌드
      → _schedule_next_timetable_event() (기존 타이머 취소 + 재예약, P14)
    → notify_desktop_settings_toggled(changed_dict) (UI 동기화)
```

### 6-3. 타임테이블 이벤트 발생 시 (기존과 동일)
```
loop.call_later 만료
  → _timetable_event_fired(entry)
    → kind="direct": action() 호출
    → kind="phase": _broadcast_market_phase()
    → _check_jif_health()
  → finally: _schedule_next_timetable_event() (다음 이벤트 예약)
```

---

## 7. 영향 범위

### 7-1. 백엔드
| 파일 | 변경 내용 |
|---|---|
| `backend/app/core/settings_defaults.py` | `DEFAULT_USER_SETTINGS`에 3개 키 추가 |
| `backend/app/core/settings_store.py` | `_TIME_FIELDS`에 3개 키 추가, `_validate_timetable_order()` 신규 함수 |
| `backend/app/services/daily_time_scheduler.py` | `_TIMETABLE` 전역 리스트 → 빌더 함수로 변경, `build_timetable_from_cache()` 신규 |
| `backend/app/services/engine_bootstrap.py` (또는 `engine_config.py`) | 기동 시 빌드 호출 배선 |
| `backend/app/services/engine_service.py` | `apply_settings_change()`에 `_TIMETABLE_KEYS` 분기 추가 |

### 7-2. 프론트엔드
| 파일 | 변경 내용 |
|---|---|
| `frontend/src/pages/general-settings.ts` | "장 시작 전 사전 준비 시간" 카드 + 입력칸 3개 + 거래소 고정 시간 참고 표시 |

### 7-3. 테스트
| 파일 | 변경 내용 |
|---|---|
| `backend/tests/test_daily_time_scheduler.py` | `build_timetable_from_cache()` 단위 테스트, 기존 `_TIMETABLE` 참조 테스트 갱신 |
| `backend/tests/test_settings_store.py` | `_validate_timetable_order()` 단위 테스트 (정상/순서 위반/형식 오류) |
| `backend/tests/test_engine_settings.py` | 기동 시 빌드 배선 통합 테스트 |

### 7-4. DB
- 스키마 변경 **없음** (기존 `integrated_system_settings` 테이블 재사용)
- Safety Rule 2 (백업) 불필요 — 스키마 마이그레이션 아님
- 최초 기동 시 `DEFAULT_USER_SETTINGS` 병합으로 3개 키 자동 저장

---

## 8. 다단계 작업 분할 (세션당 1단계, 규칙 0-1)

> 각 Step은 별도 세션에서 진행. 검증(테스트+런타임 기동) 후 커밋 + `HANDOVER.md` 갱신.

| Step | 세션 | 내용 | 검증 |
|---|---|---|---|
| 1 | 백엔드 1세션 | `settings_defaults.py` 3개 키 추가 + `settings_store.py` `_TIME_FIELDS` 확장 + `_validate_timetable_order()` | 단위 테스트 (정상/순서 위반/형식 오류) |
| 2 | 백엔드 2세션 | `daily_time_scheduler.py` 빌더 함수 + `_TIMETABLE` 전역 변경 + 기동 빌드 배선 | 단위 테스트 + 런타임 기동 확인 |
| 3 | 백엔드 3세션 | `engine_service.py` `_TIMETABLE_KEYS` 분기 + 저장 후 재예약 배선 | 통합 테스트 (저장→재빌드→재예약) |
| 4 | 프론트엔드 1세션 | 설정 페이지 입력칸 3개 + 거래소 고정 시간 참고 표시 | 빌드 + 브라우저 확인 |
| 5 | 프론트엔드 2세션 | 검증 에러 표시 + 저장 플로우 연결 | 빌드 + 브라우저 확인 (422 응답 시 에러 토스트) |
| 6 | 테스트 1세션 | 기존 테스트 갱신 + 신규 테스트 보강 | 전체 테스트 통과 |

---

## 9. 위험 및 완화

| 위험 | 완화 |
|---|---|
| 사용자가 09:30 등 장 후 시간 입력 → 구독 누락 구간 발생 | `_validate_timetable_order()`에서 `krx_pre_subscribe < "09:00"` 강제 (P22) |
| 빌더 함수 호출 누락 → 빈 `_TIMETABLE`로 스케줄러 무동작 | 기동 경로 배선 필수 (P16), 단위 테스트에서 빈 리스트 상태 검증 |
| 캐시와 DB 불일치 → 잘못된 시각으로 스케줄 | `refresh_engine_integrated_system_settings_cache()` 선행 후 빌드 (기존 패턴) |
| 기존 `_TIMETABLE` 직접 참조 테스트 깨짐 | Step 2에서 테스트 동시 갱신 (규칙 4-1) |
| 동시 저장 시 경쟁 | 기존 `get_db_lock()` + 트랜잭션으로 보호 (재사용) |

---

## 10. 승인 대기 항목

본 설계서는 **설계 완료·구현 승인 대기** 상태. 사용자의 명시적 실행 지시어("진행해", "구현해", "go" 등)가 있으면 Step 1부터 세션당 1단계로 진행.

### 10-1. 사용자 설계 로직 변경 사전 통지 (규칙 0-5)

본 설계는 기존 `_TIMETABLE` 파이썬 리스트(사용자가 이전에 설계·승인한 구조)를 **빌더 함수 기반으로 변경**하는 것을 포함합니다:
- **변경 사유**: DB 저장값을 반영하려면 기동 시·저장 시 동적으로 리스트를 빌드해야 함. 정적 리스트는 DB 값 반영 불가.
- **영향 범위**: `_TIMETABLE` 참조 코드(`_schedule_next_timetable_event`, `_timetable_event_fired`)는 변경 없음. 리스트 빌드 방식만 변경.
- **대안 검토**: (A) 빌더 함수 방식(본 설계 채택) (B) `_TIMETABLE`를 매번 DB 조회하여 빌드 — P13 위반(스케줄 연산 단계 DB 조회)으로 부적합.
- **승인 필요**: 본 설계서 전체 승인 시 `_TIMETABLE` 구조 변경도 함께 승인된 것으로 간주.

---

## 11. 참조

- 기존 타임테이블 구현: `backend/app/services/daily_time_scheduler.py:944-1041`
- 기존 설정 저장 API: `backend/app/core/settings_store.py:136-213`
- 기존 설정 변경 동기화: `backend/app/services/engine_service.py:30-160`
- 기존 설정 라우트: `backend/app/web/routes/settings.py:26-86`
- 유사 설계서: `docs/architecture_order_time_guard_design.md` (시간대 게이트 — 동일 패턴)
