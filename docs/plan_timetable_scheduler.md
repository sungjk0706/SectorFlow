# 태스크 파일: 타임테이블 기반 스케줄러 (Timetable Scheduler)

> **상태**: 2세션(심층 사전조사 + 태스크 파일 작성) 완료 · 구현 승인 대기
> **작성일**: 2026-07-17
> **설계서**: `docs/architecture_timetable_scheduler_design.md` (1세션 완료, 526줄)
> **관련 원칙**: P5(EventBus 금지) · P10(SSOT) · P11(폴링 금지) · P13(설정 메모리 상주) · P14(멀티스레드 금지) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 1. 사전조사 결과 (AGENTS.md 섹션3 규칙 0-2 4항목)

### 1-1. 의존성 (전체 코드베이스 검색)

| 자산 | 위치 | 역할 | 본 작업에서의 활용 |
|------|------|------|-------------------|
| `REALTIME_FIELDS_RESET_TIME` | `daily_time_scheduler.py:46` | `(7, 58)` 튜플 | **재사용** — `_TIMETABLE` 07:58 항목 |
| `WS_SUBSCRIBE_PRESTART_TIME` | `daily_time_scheduler.py:47` | `(7, 59)` 튜플 | **재사용** — `_TIMETABLE` 07:59 항목 |
| `NXT_PREMARKET_START` | `daily_time_scheduler.py:35` | `(8, 0)` 튜플 | **재사용** — `_TIMETABLE` 08:00 항목 |
| `KRX_PRE_SUBSCRIBE_TIME` | `daily_time_scheduler.py:48` | `(8, 59)` 튜플 | **재사용** — `_TIMETABLE` 08:59 항목 |
| `KRX_REGULAR_START` | `daily_time_scheduler.py:26` | `(9, 0)` 튜플 | **재사용** — `_TIMETABLE` 09:00 항목 |
| `KRX_REGULAR_END` | `daily_time_scheduler.py:27` | `(15, 20)` 튜플 | **재사용** — `_TIMETABLE` 15:20 항목 |
| `KRX_CLOSING_AUCTION_END` | `daily_time_scheduler.py:28` | `(15, 30)` 튜플 | **재사용** — `_TIMETABLE` 15:30 항목 |
| `NXT_SINGLE_PRICE_END` | `daily_time_scheduler.py:40` | `(15, 40)` 튜플 | **재사용** — `_TIMETABLE` 15:40 항목 |
| `NXT_AFTERMARKET_MID_END` | `daily_time_scheduler.py:42` | `(18, 0)` 튜플 | **재사용** — `_TIMETABLE` 18:00 항목 |
| `NXT_AFTERMARKET_END` | `daily_time_scheduler.py:43` | `(20, 0)` 튜플 | **재사용** — `_TIMETABLE` 20:00 항목 |
| `_on_realtime_fields_reset()` | `daily_time_scheduler.py:802-836` | 07:58 실시간 필드 초기화 (async, 멱등성 가드 `state.last_realtime_reset_date`) | **재사용** — `_TIMETABLE` direct 항목 콜백 |
| `_on_ws_subscribe_start()` | `daily_time_scheduler.py:838-871` | 07:59 WS 구독 사전 시작 (async, 멱등성 가드 `state.last_ws_subscribe_start_date`) | **재사용** — `_TIMETABLE` direct 항목 콜백 |
| `_on_krx_pre_subscribe()` | `daily_time_scheduler.py:559-583` | 08:59 KRX 사전 구독 (async, 멱등성 가드 `state.last_krx_pre_subscribe_date`) | **재사용** — `_TIMETABLE` direct 항목 콜백 |
| `_broadcast_market_phase()` | `daily_time_scheduler.py:769` | 페이즈 재산정 + `_apply_market_phase()` 호출 | **재사용** — `_TIMETABLE` phase 항목 콜백 |
| `_apply_market_phase()` | `daily_time_scheduler.py:721-766` | 페이즈 적용 + 부작용 트리거 (공통 종착점) | **재사용** — JIF/시간표 양 경로 공통 |
| `_kst_now()` | `daily_time_scheduler.py:450-451` | KST 기준 현재 시각 | **재사용** — 타이머 지연 계산 |
| `schedule_engine_task()` | `engine_lifecycle.py` (라인 14 import) | 백그라운드 태스크 안전 예약 | **재사용** — `call_later` 콜백 내 태스크 예약 |
| `logger` | `daily_time_scheduler.py:15` | `logging.getLogger(__name__)` | **재사용** — 로깅 |
| `_market_phase_periodic_loop()` | `daily_time_scheduler.py:1328-1355` | 10초 루프 (제거 대상) | **제거** |
| `_start_market_phase_periodic_task()` | `daily_time_scheduler.py:1357-1363` | 루프 태스크 시작 (제거 대상) | **제거** |
| `_stop_market_phase_periodic_task()` | `daily_time_scheduler.py:1366-1376` | 루프 태스크 정지 (제거 대상) | **제거** |
| `_check_prestart_triggers()` | `daily_time_scheduler.py:1296-1325` | 07:58/07:59/08:59 분기 로직 | **제거 후 시간표로 통합** (단, 4세션에서 제거 — 3세션은 신규 추가만) |
| `state.market_phase_periodic_task` | `engine_state.py:112` | 루프 태스크 핸들 (제거 대상) | **제거** + 신규 `timetable_timer_handle`/`last_jif_received_at` 추가 |
| `_handle_jif()` | `engine_ws_dispatch.py:257` | JIF 수신 핸들러 | **수정** — `last_jif_received_at` 갱신 1줄 추가 |
| `_init_ws_subscribe_state()` | `daily_time_scheduler.py:998-1046` | 기동 시 direct 동작 즉시 실행 | **유지** — 타임테이블 기동 스캔은 중복 실행 금지, 본 함수가 담당 |
| `start_daily_time_scheduler()` | `daily_time_scheduler.py:1382-1413` | 스케줄러 기동 | **수정** — `_start_market_phase_periodic_task()` 호출 → `_timetable_startup_scan()` 교체 (라인 1408) |
| `stop_daily_time_scheduler()` | `daily_time_scheduler.py:1415-1429` | 스케줄러 정지 | **수정** — `_stop_market_phase_periodic_task()` 호출 → 타임테이블 타이머 취소 교체 (라인 1428) |

### 1-2. 영향범위

| 계층 | 파일 | 변경 유형 | 세션 |
|------|------|----------|------|
| 백엔드 | `daily_time_scheduler.py` | 신규 추가: `_TIMETABLE`, `_schedule_next_timetable_event()`, `_timetable_event_fired()`, `_check_jif_health()`, `_timetable_startup_scan()` | 3세션 |
| 백엔드 | `daily_time_scheduler.py` | 제거: `_market_phase_periodic_loop()`, `_start_market_phase_periodic_task()`, `_stop_market_phase_periodic_task()`, `_check_prestart_triggers()` + 수정: `start/stop_daily_time_scheduler()` + 관련 주석 갱신 | 4세션 |
| 백엔드 | `engine_state.py` | 신규 필드: `timetable_timer_handle`, `last_jif_received_at` + 제거: `market_phase_periodic_task` + import 추가: `datetime` | 3세션 |
| 백엔드 | `engine_ws_dispatch.py` | 1줄 추가: `_handle_jif()` 내 `last_jif_received_at` 갱신 + import 추가: `_kst_now` | 4세션 |
| 테스트 | `test_daily_time_scheduler.py` | 신규 클래스: `TestTimetableScheduler` (10개 케이스) + 기존 `TestMarketPhasePeriodicLoop`/`TestCheckPrestartTriggers` 갱신 또는 제거 | 5세션 |

**순증 예상**: `daily_time_scheduler.py` 약 +40줄 (신규 +90, 제거 -50). P24 파일 500줄 기준 — 현재 1,429줄이나 본 파일은 이미 1,400줄 초과로 예외 적용 대상 (설계서 섹션 7 명시).

### 1-3. 아키텍처 원칙 부합 여부

| 원칙 | 부합 | 비고 |
|------|------|------|
| **P5 (EventBus 금지)** | ✅ | 시간표 → `schedule_engine_task()` 직접 호출, 옵서버 패턴 도입 없음 |
| **P10 (SSOT)** | ✅ | 시간표 단일 리스트, 기존 시간 상수 재사용, 신규 상수 생성 없음. `_apply_market_phase()` 공통 종착점 유지 |
| **P11 (폴링 금지)** | ✅ | `while + sleep` 제거 → `call_later` 이벤트 기반. **P11 예외 주석 제거** (라인 1336-1338) |
| **P13 (설정 메모리 상주)** | ✅ | 시간표는 코드 내 상수 (1세션), 틱 단계 DB 조회 없음 |
| **P14 (멀티스레드 금지)** | ✅ | `create_task` 1개(루프용) 제거 → `call_later` 1개(타이머용). 태스크 수 감소 |
| **P16 (살아있는 경로)** | ✅ | 기동 시 시간표 스캔 → 다음 이벤트 예약. JIF 미수신 시 시간표가 보완 경로 유지 |
| **P20 (폴백 금지)** | ✅ | 시간표 로드 실패 시 `logger.error` + 차단, silent `except: pass` 금지. `_timetable_event_fired()` 예외 시 `logger.warning(exc_info=True)` |
| **P21 (사용자 투명성)** | ✅ | 페이즈 브로드캐스트, `order_time_blocked` 브로드캐스트 유지 — UI 가시성 변화 없음 |
| **P22 (데이터 정합성)** | ✅ | 멱등성 가드(`state.last_*_date`) 유지 — 중복 실행 차단 |
| **P23 (일관성)** | ✅ | `schedule_engine_task()` 기존 패턴 재사용, `_broadcast_market_phase()` 기존 함수 재사용, `_kst_now()` 재사용 |
| **P24 (단순성)** | ✅ | 신규 함수 `_schedule_next_timetable_event()` 40줄 이내, `_timetable_event_fired()` 20줄 이내. 분기 로직 30줄(`_check_prestart_triggers`) → 시간표 조회 5줄로 축소 |

### 1-4. 기존 공통 자산 확인 (P23 사전 절차)

신규 자산 생성 없음. 모든 기능이 기존 공통 자산 재사용으로 구성:
- **시간 상수 10개**: `daily_time_scheduler.py:21-49` 기존 정의 재사용
- **direct 콜백 3개**: `_on_realtime_fields_reset()`(802), `_on_ws_subscribe_start()`(838), `_on_krx_pre_subscribe()`(559) 기존 함수 재사용
- **phase 콜백**: `_broadcast_market_phase()`(769) 기존 함수 재사용
- **시각 계산**: `_kst_now()`(450) 기존 함수 재사용
- **태스크 예약**: `schedule_engine_task()` 기존 패턴 재사용
- **로깅**: `logger`(15) 기존 인스턴스 재사용
- **state 필드 패턴**: `midnight_timer_handle`(engine_state.py:111) 기존 `asyncio.TimerHandle | None` 패턴 재사용

---

## 2. 설계서 대비 심층 발견사항

### 2-1. ★ `engine_state.py` `datetime` import 누락 (중요 — 신규 필드 타입 오류 위험)

**발견**: `engine_state.py` 라인 8에 `import asyncio`는 있으나 `from datetime import datetime`이 없음. 신규 필드 `last_jif_received_at: datetime | None = None`의 타입 힌트가 runtime에 `NameError` 유발 가능.

**영향**:
- `from __future__ import annotations`가 있으면 runtime 평가 지연으로 즉시 오류는 아니나, 정적 분석 및 일관성 차질.
- `daily_time_scheduler.py`의 `_check_jif_health()`에서 `state.last_jif_received_at`와 `_kst_now()` 반환값 비교 시 타입 불일치 위험.

**해결안 (확정)**: 3세션에서 `engine_state.py` 상단 import에 `from datetime import datetime` 추가. 기존 `asyncio` import(라인 8) 바로 아래 배치.

**기각안**: `last_jif_received_at`를 `Any` 타입으로 선언 — P23(일관성) 위반, 기존 `datetime` 필드 패턴과 불일치.

### 2-2. ★ `market_phase_periodic_task` 필드 위치 정정 (설계서 가정 라인 89 → 실제 라인 112)

**발견**: 설계서 섹션 4-6이 `market_phase_periodic_task`를 "라인 89 근처"로 가정했으나, 실제는 `engine_state.py:112`.

**영향**: 제거 대상 필드 위치 확인 필수. 4세션 제거 시 잘못된 라인 참조로 인한 삭제 누락 위험.

**해결안 (확정)**: 태스크 파일에서 실제 라인 112 기준으로 명시. 신규 필드 `timetable_timer_handle`/`last_jif_received_at`는 라인 111(`midnight_timer_handle`) 바로 아래에 추가 — 동일 `asyncio.TimerHandle | None` 패턴 그룹화.

### 2-3. ★ 15:30, 18:00 부작용 트리거 — 직접 분기 없음 (설계서 가정과 부분 불일치, 기능 문제 없음)

**발견**: 설계서 섹션 2-1이 15:30(`KRX_CLOSING_AUCTION_END`), 18:00(`NXT_AFTERMARKET_MID_END`)을 `_apply_market_phase()` 내 부작용 트리거로 나열했으나, 실제 `_apply_market_phase()`(721-766)에는 15:30/18:00에 대한 직접 분기 없음. 08:00/09:00/15:20/15:40(=20:00 공용) 분기만 존재.

**영향**: 없음. 15:30/18:00은 페이즈 변경 감지(`if prev_krx != new_krx or prev_nxt != new_nxt`, 라인 751)로 자동 처리됨. 시간표에서 phase 이벤트로 등록하면 `_broadcast_market_phase()` → `_apply_market_phase()` 호출 시 페이즈 변경 감지로 부작용 자동 트리거.

**해결안 (확정)**: 설계서대로 시간표에 15:30/18:00을 phase 항목으로 등록. 추가 분기 로직 불필요 (P24 단순성).

### 2-4. ★ `_on_krx_pre_subscribe()` 위치 — 다른 direct 콜백보다 앞에 정의 (라인 559)

**발견**: 설계서 섹션 4-1이 `_TIMETABLE` 배치를 "라인 905 이후 (direct 콜백 정의 이후)"로 가정. 실제 direct 콜백 위치: `_on_krx_pre_subscribe()`(559-583), `_on_realtime_fields_reset()`(802-836), `_on_ws_subscribe_start()`(838-871). 가장 마지막 direct 콜백은 `_on_ws_subscribe_start()`(871 종료).

**영향**: `_TIMETABLE`은 라인 871 이후에 배치해야 함 (함수 참조 순서). 설계서 가정 "905 이후"는 안전측이나, 실제로는 871 이후면 충분.

**해결안 (확정)**: `_TIMETABLE`을 `_on_ws_subscribe_start()` 종료(라인 871) 이후, `schedule_ws_subscribe_timers()` 시작(라인 944) 이전에 배치. 약 72줄 여유 공간 존재.

### 2-5. ★ `typing` import 불필요 — `list[dict]` 단순화 (P24)

**발견**: 설계서 섹션 4-1이 `from typing import Callable, Coroutine, Any`를 제안했으나, `daily_time_scheduler.py`에 `typing` import 없음. `from __future__ import annotations`(라인 8)로 타입 힌트가 문자열 평가되므로 runtime 오류는 아니나, 불필요한 import는 P24 위반.

**영향**: 없음.

**해결안 (확정)**: `_TIMETABLE` 타입을 `list[dict]`로 단순화 — `Callable` 등 import 불필요. dict 내 `action` 필드는 runtime에 함수 객체 직접 참조하므로 타입 힌트 없이도 동작. 설계서 섹션 4-1의 `list[dict]` 표기 채용.

### 2-6. ★ `_check_prestart_triggers()` 제거 시점 — 4세션 (3세션은 신규 추가만)

**발견**: 설계서 섹션 4-8이 10초 루프 제거(Step 8)를 1세션에 포함했으나, 규칙 0-1(세션당 1단계)에 따라 구현을 3세션으로 분할 시, 3세션은 신규 추가만 수행하고 기존 코드 제거는 4세션에서 수행.

**영향**: 3세션 완료 후 일시적으로 10초 루프 + 타임테이블 타이머가 동시 동작(중복 스케줄링). 단, 멱등성 가드로 부작용 중복 없음. 4세션에서 10초 루프 제거 시 해결.

**해결안 (확정)**: 3세션은 신규 함수 5개 + state 필드 추가만 (기존 코드 변경 없음). 4세션에서 10초 루프 + `_check_prestart_triggers()` 제거 + start/stop 갱신 + JIF 갱신. 5세션에서 테스트 + 런타임 검증.

**기각안**: 3세션에서 신규 추가 + 기존 제거 동시 수행 — 규칙 0-1 위반, 변경 범위 과대.

---

## 3. 세션 분할 확정 (설계서 섹션 8 + 본 조사 반영)

| 세션 | 작업 범위 | 파일 | 검증 |
|------|----------|------|------|
| **3세션** | Step 1~6: 신규 함수 5개(`_TIMETABLE`, `_schedule_next_timetable_event()`, `_timetable_event_fired()`, `_check_jif_health()`, `_timetable_startup_scan()`) + `engine_state.py` 필드 2개 추가 + `datetime` import | `daily_time_scheduler.py`, `engine_state.py` | py_compile + ruff + 기존 테스트 회귀 (신규 함수는 미호출 상태, dead code 아님 — 4세션에서 배선) |
| **4세션** | Step 7+8: `_handle_jif()` 내 `last_jif_received_at` 갱신 1줄 + 10초 루프 3함수 제거 + `_check_prestart_triggers()` 제거 + `start/stop_daily_time_scheduler()` 갱신 + 관련 주석 갱신 + `state.market_phase_periodic_task` 제거 | `daily_time_scheduler.py`, `engine_ws_dispatch.py`, `engine_state.py` | py_compile + ruff + 기존 테스트 회귀 (타임테이블 배선 완료) + 런타임 기동 (`-W error::RuntimeWarning`) |
| **5세션** | Step 9+10: 단위 테스트 `TestTimetableScheduler` 10개 케이스 + 기존 `TestMarketPhasePeriodicLoop`/`TestCheckPrestartTriggers` 갱신 또는 제거 + 런타임 기동 검증 | `test_daily_time_scheduler.py` | 단위 테스트 전체 통과 + 런타임 기동 + 로그 확인 |

> **규칙 0-1 준수**: 각 세션은 1단계만 진행. 3세션 완료 후 검증 → 커밋 → HANDOVER.md 갱신 → 4세션 진행 승인 대기.

---

## 4. 각 세션별 태스크 상세

### 4-1. 3세션: 신규 함수 5개 + state 필드 (Step 1~6)

**Step 1 — `daily_time_scheduler.py` `_TIMETABLE` 자료구조 (라인 871 이후 배치)**:

```python
# ── 타임테이블 스케줄러 (10초 루프 대체) ──────────────────────────────────────
# 시간표 항목: (시각 상수, 동작 종류, 콜백, 컨텍스트)
# - kind="direct": 시각 도달 시 callback 직접 실행 (사전 트리거)
# - kind="phase":  시각 도달 시 _broadcast_market_phase() 호출 (페이즈 재계산)
#
# P10 SSOT: 시간 상수는 기존 라인 21-49 재사용, 신규 상수 생성 없음.
# P24 단순성: 두 종류를 동일 리스트에서 kind 필드로 구분 (별도 리스트 분할 금지).
_TIMETABLE: list[dict] = [
    {"time": REALTIME_FIELDS_RESET_TIME, "kind": "direct", "action": _on_realtime_fields_reset, "ctx": "실시간 필드 초기화 (07:58)"},
    {"time": WS_SUBSCRIBE_PRESTART_TIME,  "kind": "direct", "action": _on_ws_subscribe_start,    "ctx": "WS 구독 사전 시작 (07:59)"},
    {"time": NXT_PREMARKET_START,         "kind": "phase",  "ctx": "NXT 프리마켓 진입 감지 (08:00)"},
    {"time": KRX_PRE_SUBSCRIBE_TIME,      "kind": "direct", "action": _on_krx_pre_subscribe,     "ctx": "KRX 사전 구독 (08:59)"},
    {"time": KRX_REGULAR_START,           "kind": "phase",  "ctx": "KRX 정규장 진입 감지 (09:00)"},
    {"time": KRX_REGULAR_END,             "kind": "phase",  "ctx": "KRX 종가 동시호가 진입 감지 (15:20)"},
    {"time": KRX_CLOSING_AUCTION_END,     "kind": "phase",  "ctx": "KRX 체결 정산 전환 감지 (15:30)"},
    {"time": NXT_SINGLE_PRICE_END,        "kind": "phase",  "ctx": "NXT 애프터마켓 진입 감지 (15:40)"},
    {"time": NXT_AFTERMARKET_MID_END,     "kind": "phase",  "ctx": "NXT 애프터마켓 지속 전환 감지 (18:00)"},
    {"time": NXT_AFTERMARKET_END,         "kind": "phase",  "ctx": "NXT 장마감 진입 감지 (20:00)"},
]
```

> **배치 위치**: `_on_ws_subscribe_start()` 종료(라인 871) 이후, `schedule_ws_subscribe_timers()` 시작(라인 944) 이전. direct 콜백 3개 모두 정의 이후이므로 함수 참조 순서 안전.

**Step 2 — `daily_time_scheduler.py` `_schedule_next_timetable_event()` (Step 1 이후 배치)**:

```python
def _schedule_next_timetable_event() -> None:
    """시간표에서 다음 미래 이벤트를 찾아 call_later 1개 예약.

    P11 (폴링 금지): while + sleep 대신 call_later 이벤트 기반.
    P14 (멀티스레드 금지): 타이머 1개만 유지 (기존 타이머 취소 후 재예약).
    P24 단순성: 시간표 선형 스캔, 복잡도 O(n) n=10.
    """
    # 기존 타이머 취소
    if state.timetable_timer_handle is not None:
        state.timetable_timer_handle.cancel()
        state.timetable_timer_handle = None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    now = _kst_now()
    now_sec = now.hour * 3600 + now.minute * 60 + now.second

    # 다음 미래 이벤트 탐색 (오늘 남은 이벤트)
    next_entry = None
    next_delay = None
    for entry in _TIMETABLE:
        h, m = entry["time"]
        event_sec = h * 3600 + m * 60
        delay = event_sec - now_sec
        if delay <= 0:
            continue  # 이미 지난 이벤트
        if next_delay is None or delay < next_delay:
            next_delay = delay
            next_entry = entry

    if next_entry is None or next_delay is None:
        # 오늘 남은 이벤트 없음 → 익일 첫 이벤트(07:58)까지 대기
        h, m = REALTIME_FIELDS_RESET_TIME
        target = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)
        next_delay = (target - now).total_seconds()
        next_entry = {"time": REALTIME_FIELDS_RESET_TIME, "kind": "phase", "ctx": "익일 첫 이벤트 (07:58 재스케줄)"}

    # 최소 1초 보장 (즉시 실행 방지)
    delay = max(next_delay, 1)
    state.timetable_timer_handle = loop.call_later(
        delay,
        lambda: schedule_engine_task(_timetable_event_fired(next_entry), context=f"타임테이블: {next_entry['ctx']}"),
    )
    logger.debug("[스케줄] 다음 타임테이블 이벤트 — %s (%.0f초 후)", next_entry["ctx"], delay)
```

**Step 3 — `daily_time_scheduler.py` `_timetable_event_fired()` (Step 2 이후 배치)**:

```python
async def _timetable_event_fired(entry: dict) -> None:
    """타임테이블 이벤트 발생 시 실행 — 동작 수행 + 다음 이벤트 예약.

    P16 (살아있는 경로): JIF 미수신 시 시간표가 보완 경로 유지.
    P22 (데이터 정합성): 멱등성 가드는 각 _on_* 콜백 내부에서 유지.
    P20 (폴백 금지): 예외 시 logger.warning(exc_info=True), silent pass 금지.
    """
    try:
        kind = entry["kind"]
        ctx = entry["ctx"]
        logger.info("[스케줄] 타임테이블 이벤트 실행 — %s", ctx)

        if kind == "direct":
            # 직접 동작: 사전 트리거 콜백 실행
            action = entry["action"]
            await action()
        elif kind == "phase":
            # 페이즈 재계산: _broadcast_market_phase() → _apply_market_phase() 내 부작용 트리거
            _broadcast_market_phase()

        # JIF 미수신 헬스체크 (옵션 A — 이벤트 실행 시점에 체크)
        _check_jif_health()

    except Exception as e:
        logger.warning("[스케줄] 타임테이블 이벤트 오류: %s", e, exc_info=True)
    finally:
        # 다음 이벤트 예약 (오류 발생 여부와 무관하게 스케줄러 지속)
        _schedule_next_timetable_event()
```

**Step 4 — `daily_time_scheduler.py` `_check_jif_health()` (Step 3 이후 배치)**:

```python
# JIF 헬스체크 임계값 — 마지막 JIF 수신 후 이 시간(초) 경과 시 경고
_JIF_STALE_WARN_SEC = 120  # 2분 (JIF는 페이즈 전환 시점에만 수신되므로 넉넉한 임계값)

def _check_jif_health() -> None:
    """마지막 JIF 수신 시각 경과 시간 체크 — 경고만 로깅, 자동 조치 없음 (P24).

    P21 (사용자 투명성): JIF 미수신 시 사용자가 인지할 수 있도록 로그.
    단, 자동 조치(강제 페이즈 전환 등)는 금지 — 시간표가 이미 보완 역할 수행 중.
    """
    last_jif = state.last_jif_received_at
    if last_jif is None:
        # 기동 후 JIF 미수신 — 시간표가 보완 중이므로 경고만
        logger.debug("[스케줄] JIF 미수신 상태 — 시간표 보완 동작 중")
        return
    elapsed = (_kst_now() - last_jif).total_seconds()
    if elapsed > _JIF_STALE_WARN_SEC:
        logger.warning("[스케줄] JIF 미수신 %.0f초 경과 — 시간표 보완 경로로 동작 중", elapsed)
```

**Step 5 — `daily_time_scheduler.py` `_timetable_startup_scan()` (Step 4 이후 배치)**:

```python
async def _timetable_startup_scan() -> None:
    """기동 시 시간표 스캔 — 다음 미래 이벤트 예약.

    P16 (살아있는 경로): 재기동 시 사전 트리거 구간(07:58~08:00) 누락 방지.
    P22 (데이터 정합성): 멱등성 가드(state.last_*_date)로 중복 실행 차단.
    P24 단순성: 본 함수는 "다음 예약"에만 집중 — 직접 동작 즉시 실행은
    기존 _init_ws_subscribe_state()(998-1046)가 담당, 중복 금지.

    기동 시나리오:
    - 07:55 재기동: 07:58/07:59 이벤트 예약만 (아직 도달 전)
    - 07:58:30 재기동: 07:58 direct 동작은 _init_ws_subscribe_state()가 담당 + 07:59 예약
    - 09:30 재기동: 07:58/07:59/08:59 direct 동작 스킵 (이미 지난, 멱등성 가드) + 15:20 예약
    """
    # 기동 시 현재 페이즈 즉시 산정은 기존 start_daily_time_scheduler()(1394-1397)가 담당
    # — 본 함수에서 중복 수행 금지

    # 다음 미래 이벤트 예약
    _schedule_next_timetable_event()
    logger.info("[기동] 타임테이블 스케줄러 시작 — 다음 이벤트 예약 완료")
```

> **설계서 대비 단순화**: 설계서 섹션 4-5의 과거 direct 이벤트 로깅 루프 제거 — 기존 `_init_ws_subscribe_state()`가 이미 담당하므로 중복 로깅 불필요 (P24). 본 함수는 `_schedule_next_timetable_event()` 호출 1줄 + 로깅 1줄로 단순화.

**Step 6 — `engine_state.py` 필드 추가 + import 추가**:

```python
# 라인 8 (기존 import asyncio) 아래에 추가:
from datetime import datetime

# 라인 111 (기존 midnight_timer_handle) 아래에 추가:
self.timetable_timer_handle: asyncio.TimerHandle | None = None  # 타임테이블 단일 타이머
self.last_jif_received_at: datetime | None = None               # JIF 헬스체크용
```

> **주의**: `market_phase_periodic_task`(라인 112) 제거는 4세션에서 수행. 3세션은 신규 필드 추가만.

**3세션 검증 항목**:
- py_compile: `daily_time_scheduler.py`, `engine_state.py` 컴파일 통과
- ruff: 린트 통과 (신규 함수 5개 + 필드 2개)
- 기존 테스트 회귀: `test_daily_time_scheduler.py` 전체 통과 (신규 함수는 미호출 상태이나, `_TIMETABLE` 정의 시점에 direct 콜백 참조로 인한 import 오류 없음 확인)
- **P16 주의**: 3세션 완료 후 신규 함수 5개는 미호출 상태. 4세션에서 배선 전까지 dead code 상태. 단, 규칙 0-1(세션당 1단계)에 따라 3세션은 추가만, 4세션에서 배선. 이는 다단계 작업 워크플로우에서 허용 (각 세션이 독립적으로 컴파일/테스트 통과해야 함).

---

### 4-2. 4세션: 10초 루프 제거 + 배선 (Step 7+8)

**Step 7 — `engine_ws_dispatch.py` `_handle_jif()` 내 JIF 수신 시각 갱신 (라인 270 근처)**:

```python
# engine_ws_dispatch.py 상단 import에 추가 (기존 import 그룹 내):
from backend.app.services.daily_time_scheduler import _kst_now

# _handle_jif() 진입부 (라인 270-271 jangubun/jstatus 추출 이후):
async def _handle_jif(data: dict) -> None:
    jangubun = str(data.get("jangubun", "")).strip()
    jstatus = str(data.get("jstatus", "")).strip()
    if not jangubun or not jstatus:
        return
    # ── JIF 수신 시각 기록 (타임테이블 헬스체크용) ──
    state.last_jif_received_at = _kst_now()
    # ... 기존 로직 유지 ...
```

> **P23 (일관성)**: `_kst_now()` 재사용. 신규 시각 계산 함수 생성 금지. 순환 import 위험 없음 (심층 조사 확인 — `daily_time_scheduler.py`가 `engine_ws_dispatch.py`를 import하지 않음).
> **import 위치**: 기존 `from backend.app.services.daily_time_scheduler import _apply_market_phase`(라인 253-254 근처)가 이미 존재하므로, 동일 import 그룹에 `_kst_now` 추가.

**Step 8 — `daily_time_scheduler.py` 10초 루프 제거 + start/stop 갱신**:

**제거 대상 4개 함수**:
1. `_market_phase_periodic_loop()` (라인 1328-1355) — 10초 루프 본체
2. `_start_market_phase_periodic_task()` (라인 1357-1363) — 루프 태스크 시작
3. `_stop_market_phase_periodic_task()` (라인 1366-1376) — 루프 태스크 정지
4. `_check_prestart_triggers()` (라인 1296-1325) — 07:58/07:59/08:59 분기 로직 (시간표로 통합)

**`start_daily_time_scheduler()` 갱신 (라인 1408)**:

```python
# 기존 (라인 1408):
#   _start_market_phase_periodic_task()
# 교체:
await _timetable_startup_scan()
```

**`stop_daily_time_scheduler()` 갱신 (라인 1428)**:

```python
# 기존 (라인 1428):
#   await _stop_market_phase_periodic_task()
# 교체:
# 타임테이블 타이머 취소
if state.timetable_timer_handle is not None:
    state.timetable_timer_handle.cancel()
    state.timetable_timer_handle = None
```

**`engine_state.py` 필드 제거 (라인 112)**:

```python
# 제거:
self.market_phase_periodic_task: asyncio.Task | None = None
```

> **코드 제거 규칙 준수**: 제거된 함수를 참조하는 모든 주석/docstring 함께 수정.
> - `daily_time_scheduler.py` 라인 993-995 근처 "주기 태스크 _market_phase_periodic_loop()가 10초 간격으로..." 주석 갱신 → "타임테이블 스케줄러가 시간표 기반으로 장 상태 보완"으로 수정.
> - 라인 1336-1338 P11 예외 주석 제거 (더 이상 예외 아님).
> - `_check_prestart_triggers()` 참조 주석 전체 검색 후 갱신.

**4세션 검증 항목**:
- py_compile + ruff: 제거된 함수 참조 잔존 없음 확인
- 기존 테스트 회귀: `TestMarketPhasePeriodicLoop`, `TestCheckPrestartTriggers` 테스트 실패 예상 → 5세션에서 갱신/제거. 4세션에서는 실패 확인 후 5세션에서 처리 (규칙 4-1: 테스트 실패 추적)
- 런타임 기동: `python -W error::RuntimeWarning main.py` — RuntimeWarning 0건 + `[기동] 타임테이블 스케줄러 시작` 로그 출력 + 기존 `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 미출력 확인

---

### 4-3. 5세션: 단위 테스트 + 런타임 검증 (Step 9+10)

**Step 9 — `test_daily_time_scheduler.py` 신규 클래스 `TestTimetableScheduler` (파일 끝 L2294 이후)**:

```python
# ── 타임테이블 스케줄러 ────────────────────────────────────────────

class TestTimetableScheduler:
    """타임테이블 스케줄러 단위 테스트 (10초 루프 대체)."""
```

**테스트 케이스 10개 (설계서 섹션 9-1)**:

1. **다음 이벤트 탐색 — 07:55 기동**: `_schedule_next_timetable_event()` 호출 시 07:58 이벤트 예약 (delay ≈ 180초). `state.timetable_timer_handle`에 `call_later` 핸들 설정 확인.
2. **다음 이벤트 탐색 — 09:30 기동**: 15:20 이벤트 예약 (가장 가까운 미래 phase). 07:58/07:59/08:59/09:00은 이미 지났으므로 스킵.
3. **다음 이벤트 탐색 — 20:30 기동**: 익일 07:58 예약 (24시간 + delay). `next_entry["ctx"]`에 "익일 첫 이벤트" 포함 확인.
4. **direct 이벤트 발생**: `_timetable_event_fired()`에 direct 항목 전달 시 `_on_realtime_fields_reset()` 호출 + `_schedule_next_timetable_event()` 호출 (finally 블록).
5. **phase 이벤트 발생**: `_timetable_event_fired()`에 phase 항목 전달 시 `_broadcast_market_phase()` 호출 + `_schedule_next_timetable_event()` 호출.
6. **멱등성 가드**: 같은 날 direct 이벤트 중복 실행 시 `_on_realtime_fields_reset()` 내 `state.last_realtime_reset_date` 가드로 no-op.
7. **JIF 헬스체크 — 정상**: `state.last_jif_received_at` 최근(10초 전) → 경고 로그 미출력.
8. **JIF 헬스체크 — 미수신**: `state.last_jif_received_at` None → debug 로그 출력. 120초 초과 → warning 로그 출력.
9. **기동 스캔 — 07:58:30 재기동**: `_timetable_startup_scan()` 호출 시 `_schedule_next_timetable_event()` 호출 → 07:59 예약 (07:58은 이미 지났으므로).
10. **타이머 취소**: `stop_daily_time_scheduler()` 시 `state.timetable_timer_handle.cancel()` 호출 + `None` 처리.

**기존 테스트 갱신/제거**:
- `TestMarketPhasePeriodicLoop` (라인 2076): 제거 대상 — `_market_phase_periodic_loop()` 제거됨. 클래스 전체 제거.
- `TestCheckPrestartTriggers` (라인 1385): 제거 대상 — `_check_prestart_triggers()` 제거됨. 클래스 전체 제거.
- `TestStartDailyTimeScheduler` (라인 2012): 갱신 — `_start_market_phase_periodic_task()` 호출 기대 → `_timetable_startup_scan()` 호출 기대로 변경.
- `TestStopDailyTimeScheduler` (라인 1978): 갱신 — `_stop_market_phase_periodic_task()` 호출 기대 → `timetable_timer_handle.cancel()` 기대로 변경.
- import 문 갱신: `_market_phase_periodic_loop`, `_start_market_phase_periodic_task`, `_stop_market_phase_periodic_task`, `_check_prestart_triggers` 제거. `_TIMETABLE`, `_schedule_next_timetable_event`, `_timetable_event_fired`, `_check_jif_health`, `_timetable_startup_scan`, `_JIF_STALE_WARN_SEC` 추가.

**Step 10 — 런타임 기동 검증 (규칙 5)**:

1. `python -W error::RuntimeWarning main.py` 기동 — async 경고 없음 확인
2. 기동 로그 확인: `[기동] 타임테이블 스케줄러 시작 — 다음 이벤트 예약 완료` 출력
3. 10초 루프 제거 확인: 기존 `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 미출력
4. `[스케줄] 다음 타임테이블 이벤트 — ...` 로그 출력 확인
5. JIF 수신 시 `last_jif_received_at` 갱신 확인 (WS 연결 후 JIF 수신 시점)
6. 페이즈 전환 정상 동작 확인 (JIF 1순위 + 시간표 보완)
7. 잔존 프로세스 0건 확인

**5세션 검증 항목**:
- 단위 테스트 전체 통과: `pytest backend/tests/test_daily_time_scheduler.py` (기존 + 신규 10개)
- 회귀 없음: `pytest backend/tests/test_buy_order_executor.py` 등 관련 테스트 통과
- 런타임 기동: RuntimeWarning 0건 + 타임테이블 로그 출력 + 10초 루프 로그 미출력

---

## 5. 위험 및 주의점 (설계서 섹션 10 + 본 조사 추가)

1. **3세션 dead code 일시적 허용** — 신규 함수 5개가 4세션 배선 전까지 미호출 상태. 규칙 0-1(세션당 1단계)에 따른 다단계 작업 워크플로우에서 허용되나, 4세션에서 반드시 배선 완료 (본 조사 2-6).
2. **3세션 완료 후 중복 스케줄링** — 10초 루프 + 타임테이블 타이머 동시 동작. 멱등성 가드로 부작용 중복 없으나, 4세션에서 10초 루프 제거 시 해결 (본 조사 2-6).
4. **기동 시 시간표 스캔 누락** — 기존 `_init_ws_subscribe_state()`(998-1046)가 direct 동작 담당 + 멱등성 가드 `state.last_*_date` 최후 방어 (설계서 섹션 10).
5. **JIF 미수신 시 보정 지연** — 최대 다음 이벤트까지. 헬스체크 옵션 A로 경고. 시간표가 정시에 `_broadcast_market_phase()` 수행하므로 페이즈 정확 유지 (설계서 섹션 10).
6. **call_later 콜백 내 예외 시 다음 이벤트 미예약** — `_timetable_event_fired()` finally 블록에서 무조건 `_schedule_next_timetable_event()` 호출 (설계서 섹션 10).
7. **자정 넘어간 후 타임테이블 타이머 미재예약** — `_schedule_next_timetable_event()`가 "익일 07:58" 예약. 자정 타이머는 별도 동작 (1세션, 설계서 섹션 6).
8. **`last_jif_received_at` 미갱신** — Step 7에서 `_handle_jif()` 진입부에 1줄 추가. 누락 시 코드 리뷰로 방어 (설계서 섹션 10).
9. **`engine_state.py` `datetime` import 누락** — 3세션에서 반드시 `from datetime import datetime` 추가 (본 조사 2-1).
10. **기존 테스트 제거 시 코드 제거 규칙** — `TestMarketPhasePeriodicLoop`/`TestCheckPrestartTriggers` 제거 시 관련 import 문 동시 갱신 (본 조사 2-6).

---

## 6. 승인 대기 항목

- **3세션 진행 승인**: 위 태스크 파일의 3세션 작업(Step 1~6: 신규 함수 5개 + state 필드) 구현 시작 대기.
- **설계서 대비 변경사항**: 심층 발견사항 2-1~2-6 (6항목) — 설계서 가정에서 정정된 부분. 큰 틀의 설계는 동일, 세부 라인 번호 및 import 정정만.

---

## 7. 참조

- **설계서**: `docs/architecture_timetable_scheduler_design.md` (1세션 완료, 526줄)
- **아키텍처 원칙**: `ARCHITECTURE.md` 제1부 "불변 원칙 24개" — P5/P10/P11/P13/P14/P16/P20/P21/P22/P23/P24
- **수행 규칙**: `AGENTS.md` 섹션3 규칙 0(승인 전 수정 금지) + 규칙 0-1(세션당 1단계) + 규칙 0-2(수정 전 사전조사) + 규칙 4-1(테스트 실패 추적) + 규칙 5(런타임 기동 검증)
- **코드 제거 규칙**: `AGENTS.md` 섹션2 "Code Removal Rules"
- **이전 태스크 파일 패턴**: `docs/plan_order_time_guard.md` (300줄, 동일 구조)
