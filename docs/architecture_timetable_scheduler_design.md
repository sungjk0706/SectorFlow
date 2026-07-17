# 설계서: 타임테이블 기반 스케줄러 (Timetable Scheduler)

> **상태**: 설계 완료 · 구현 승인 대기
> **작성일**: 2026-07-17
> **전신**: 사전조사(4개 서브에이전트 병렬 조사) + 사용자 결정 완료 → 본 설계서
> **관련 원칙**: P5(EventBus 금지) · P10(SSOT) · P11(폴링 금지) · P13(설정 메모리 상주) · P14(멀티스레드 금지) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 1. 배경 및 목적

### 1-1. 문제 상황

현재 장 상태 보완은 `_market_phase_periodic_loop()`가 10초 간격으로 `while + asyncio.wait_for(timeout=10)` 루프를 돌며 담당 (<ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" /> 라인 1328-1355).

- **깨어남 과다**: 하루 8,640회 루프 진입 (대부분 아무 동작 없이 시간 비교만 수행)
- **P11 회색지대**: `while + sleep` 폴링이나, "하우스키핑 타이머" 예외를 주석으로 방어 중 (라인 1338-1341). P11이 명시하는 `asyncio.Queue + asyncio.wait()` 이벤트 기반에 정면 부합하지 않음
- **트리거 지연**: 07:58 사전 트리거가 07:58:00~07:58:09 사이 무작위 실행 (최대 10초 지연)
- **시간표 분산**: 07:58/07:59/08:59 사전 트리거는 `_check_prestart_triggers()` 내 분기 로직 (라인 1296-1325), 08:00/09:00/15:20/20:00 페이즈 트리거는 `_apply_market_phase()` 내 분기 로직 (라인 751-764). 같은 시간표가 두 곳에 분산

### 1-2. 목적

- 10초 주기 폴링 루프를 **시간표 + 단일 타이머** 패턴으로 교체 → 하루 깨어남 8,640회 → **7~8회** (1,080배 감소)
- P11(폴링 금지) **명확 부합** — 예외 주석 제거, `call_later` 이벤트 기반
- 사전 트리거 **초 단위 정밀 실행** (07:58:00 정확)
- 분산된 시간표를 **단일 시간표 SSOT**로 통합 (P10)

### 1-3. 설계 범위 (1세션)

| 항목 | 포함 | 제외 (2세션 이후) |
|------|------|-------------------|
| 10초 루프 → 타임테이블 교체 | ✅ | — |
| JIF 1순위 경로 유지 | ✅ (변경 없음) | — |
| JIF 미수신 헬스체크 (옵션 A) | ✅ | — |
| 자정 타이머 별도 유지 | ✅ (변경 없음) | — |
| DB 연동 | ❌ | 2세션 (integrated_system_settings 재사용) |
| call_later 3개 통합 | ❌ | 2세션 (자정/확정다운로드/자동매매전환) |
| 예외 시간표 (임시공휴일) | ❌ | 2세션 |

---

## 2. 확정된 시간표 (사용자 결정)

> 기준: `daily_time_scheduler.py` 라인 21-49 시간 상수 + 라인 751-764 페이즈 트리거 + 라인 1296-1325 사전 트리거. **기존 상수 재사용, 신규 시간 상수 생성 없음 (P10 SSOT)**.

### 2-1. 일일 시간표 (거래일 기준)

| 시각 | 상수 | 동작 콜백 | 컨텍스트 | 현재 구현 위치 |
|------|------|----------|----------|---------------|
| 07:58 | `REALTIME_FIELDS_RESET_TIME` | `_on_realtime_fields_reset()` | 실시간 필드 초기화 | `_check_prestart_triggers()` 분기 |
| 07:59 | `WS_SUBSCRIBE_PRESTART_TIME` | `_on_ws_subscribe_start()` | WS 구독 사전 시작 | `_check_prestart_triggers()` 분기 |
| 08:00 | `NXT_PREMARKET_START` | `_broadcast_market_phase()` | NXT 프리마켓 진입 감지 | `_apply_market_phase()` 페이즈 변경 |
| 08:59 | `KRX_PRE_SUBSCRIBE_TIME` | `_on_krx_pre_subscribe()` | KRX 사전 구독 | `_check_prestart_triggers()` 분기 |
| 09:00 | `KRX_REGULAR_START` | `_broadcast_market_phase()` | KRX 정규장 진입 감지 | `_apply_market_phase()` 페이즈 변경 |
| 15:20 | `KRX_REGULAR_END` | `_broadcast_market_phase()` | KRX 종가 동시호가 진입 감지 | `_apply_market_phase()` 페이즈 변경 |
| 15:30 | `KRX_CLOSING_AUCTION_END` | `_broadcast_market_phase()` | KRX 체결 정산 전환 감지 | `_apply_market_phase()` 페이즈 변경 |
| 15:40 | `NXT_SINGLE_PRICE_END` | `_broadcast_market_phase()` | NXT 애프터마켓 진입 감지 | `_apply_market_phase()` 페이즈 변경 |
| 18:00 | `NXT_AFTERMARKET_MID_END` | `_broadcast_market_phase()` | NXT 애프터마켓 지속 전환 감지 | `_apply_market_phase()` 페이즈 변경 |
| 20:00 | `NXT_AFTERMARKET_END` | `_broadcast_market_phase()` | NXT 장마감 진입 감지 → `_on_ws_subscribe_end()` 트리거 | `_apply_market_phase()` 페이즈 변경 |

### 2-2. 시간표 항목 분류

두 종류의 동작이 시간표에 혼재:

1. **직접 동작 (direct action)**: 시각 도달 시 콜백 직접 실행
   - 07:58 `_on_realtime_fields_reset()`
   - 07:59 `_on_ws_subscribe_start()`
   - 08:59 `_on_krx_pre_subscribe()`

2. **페이즈 재계산 (phase recompute)**: 시각 도달 시 `_broadcast_market_phase()` 호출 → `calc_timebased_market_phase()` 재산정 → `_apply_market_phase()` 내 페이즈 변경 감지 → 부작용 트리거
   - 08:00, 09:00, 15:20, 15:30, 15:40, 18:00, 20:00

> **설계 결정**: 두 종류를 동일 시간표에 항목별 `kind` 필드로 구분. 단일 타이머가 순차 처리.

### 2-3. 비거래일 처리

- 비거래일(주말/공휴일)에는 시간표 이벤트가 발생해도 **대부분 멱등성 가드로 no-op** (이미 `state.last_*_date == today_str`)
- 단, `_broadcast_market_phase()`는 비거래일에도 "휴장일" 페이즈 산정 → 브로드캐스트 (기존 10초 루프와 동일 동작)
- **별도 비거래일 필터링 불필요** (P24 단순성) — 멱등성 가드가 자연 차단

---

## 3. 아키텍처 원칙 준수

| 원칙 | 준수 내용 |
|------|----------|
| **P5 (EventBus 금지)** | 시간표 → `schedule_engine_task()` 직접 호출, 옵서버 패턴 도입 없음 |
| **P10 (SSOT)** | 시간표는 `daily_time_scheduler.py` 내 단일 리스트, 기존 시간 상수 재사용, 신규 상수 생성 금지 |
| **P11 (폴링 금지)** | `while + sleep` 제거 → `call_later` 단일 타이머 이벤트 기반. **예외 주석 제거** |
| **P13 (설정 메모리 상주)** | 시간표는 코드 내 상수 (1세션), 틱 단계 DB 조회 없음. 2세션 DB 연동 시에도 기동/설정 변경 시에만 로드 |
| **P14 (멀티스레드 금지)** | `create_task` 1개(루프용) 제거 → `call_later` 1개(타이머용). 태스크 수 감소 |
| **P16 (살아있는 경로)** | 기동 시 시간표 스캔 → 현재 시간에 맞는 동작 즉시 실행. JIF 미수신 시 시간표가 보완 경로 유지 |
| **P20 (폴백 금지)** | 시간표 로드 실패 시 `logger.error` + 차단, silent `except: pass` 금지 |
| **P21 (사용자 투명성)** | 페이즈 브로드캐스트, `order_time_blocked` 브로드캐스트 유지 — UI 가시성 변화 없음 |
| **P22 (데이터 정합성)** | 멱등성 가드(`state.last_*_date`) 유지 — 중복 실행 차단. 기동 스캔 시에도 동일 가드 적용 |
| **P23 (일관성)** | `schedule_engine_task()` 기존 패턴 재사용, `_broadcast_market_phase()` 기존 함수 재사용 |
| **P24 (단순성)** | 신규 함수 `_timetable_scheduler_step()` 40줄 이내 예상. 분기 로직 30줄(`_check_prestart_triggers`) → 시간표 조회 5줄로 축소. 순환 복잡도 5 이내 예상 |

---

## 4. 백엔드 설계

### 4-1. 시간표 자료구조 (Step 1)

`daily_time_scheduler.py` 내 신규 추가. 기존 시간 상수 재사용.

```python
from typing import Callable, Coroutine, Any

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

**주의**: `_TIMETABLE`은 `_on_*` 콜백 함수 정의 이후에 위치해야 함 (함수 참조 순서). 기존 `_on_realtime_fields_reset` 등은 라인 802~905에 정의되어 있으므로, `_TIMETABLE`은 라인 905 이후에 배치.

### 4-2. 단일 타이머 스케줄 함수 (Step 2)

10초 루프를 대체하는 핵심 함수. 다음 이벤트까지 `call_later` 1개 예약.

```python
def _schedule_next_timetable_event() -> None:
    """시간표에서 다음 미래 이벤트를 찾아 call_later 1개 예약.

    P11 (폴링 금지): while + sleep 대신 call_later 이벤트 기반.
    P14 (멀티스레드 금지): 타이머 1개만 유지 (기존 타이머 취소 후 재예약).
    P24 (단순성): 시간표 선형 스캔, 복잡도 O(n) n=10.
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
        # 오늘 남은 이벤트 없음 → 자정 이후 첫 이벤트(07:58)까지 대기
        # 자정 타이머가 별도 존재하므로, 여기서는 다음 07:58까지 예약
        h, m = REALTIME_FIELDS_RESET_TIME
        target = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)
        next_delay = (target - now).total_seconds()
        # 07:58 가짜 엔트리 생성 (자정 넘어간 후 실제 스케줄러가 재개)
        next_entry = {"time": REALTIME_FIELDS_RESET_TIME, "kind": "phase", "ctx": "익일 첫 이벤트 (07:58 재스케줄)"}

    # 최소 1초 보장 (즉시 실행 방지)
    delay = max(next_delay, 1)
    state.timetable_timer_handle = loop.call_later(
        delay,
        lambda: schedule_engine_task(_timetable_event_fired(next_entry), context=f"타임테이블: {next_entry['ctx']}"),
    )
    logger.debug("[스케줄] 다음 타임테이블 이벤트 — %s (%.0f초 후)", next_entry["ctx"], delay)
```

### 4-3. 이벤트 발생 핸들러 (Step 3)

타이머 만료 시 실행. 동작 수행 + 다음 이벤트 예약.

```python
async def _timetable_event_fired(entry: dict) -> None:
    """타임테이블 이벤트 발생 시 실행 — 동작 수행 + 다음 이벤트 예약.

    P16 (살아있는 경로): JIF 미수신 시 시간표가 보완 경로 유지.
    P22 (데이터 정합성): 멱등성 가드는 각 _on_* 콜백 내부에서 유지.
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

### 4-4. JIF 미수신 헬스체크 (Step 4)

10초 루프 제거로 JIF 미수신 감지가 사라지는 것을 보완. **옵션 A: 이벤트 실행 시점에 체크**.

```python
# JIF 헬스체크 임계값 — 마지막 JIF 수신 후 이 시간(초) 경과 시 경고
_JIF_STALE_WARN_SEC = 120  # 2분 (JIF는 페이즈 전환 시점에만 수신되므로 넉넉한 임계값)

def _check_jif_health() -> None:
    """마지막 JIF 수신 시각 경과 시간 체크 — 경고만 로깅, 자동 조치 없음 (P24).

    P21 (사용자 투명성): JIF 미수신 시 사용자가 인지할 수 있도록 로그 + UI 알림.
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

### 4-5. 기동 시 시간표 스캔 (Step 5)

엔진 기동/재기동 시 현재 시간에 맞는 동작 즉시 실행 (P16 살아있는 경로). 기존 `_init_ws_subscribe_state()`와 유사 패턴.

```python
async def _timetable_startup_scan() -> None:
    """기동 시 시간표 스캔 — 현재 시간 기준 이미 지난 이벤트 중 누락된 동작 즉시 실행.

    P16 (살아있는 경로): 재기동 시 사전 트리거 구간(07:58~08:00) 누락 방지.
    P22 (데이터 정합성): 멱등성 가드(state.last_*_date)로 중복 실행 차단.

    기동 시나리오:
    - 07:55 재기동: 07:58/07:59 이벤트 예약만 (아직 도달 전)
    - 07:58:30 재기동: 07:58 직접 동작 즉시 실행 (last_realtime_reset_date 가드) + 07:59 예약
    - 09:30 재기동: 07:58/07:59/08:59 직접 동작 스킵 (이미 지난, 멱등성 가드) + 15:20 예약
    """
    now = _kst_now()
    now_sec = now.hour * 3600 + now.minute * 60 + now.second
    today_str = now.strftime("%Y%m%d")

    # 기동 시 현재 페이즈 즉시 산정 (기존 start_daily_time_scheduler() 라인 1394-1397 유지)
    # — 이 부분은 기존 코드 그대로 유지, 본 함수에서 중복 수행 금지

    # 이미 지난 direct 이벤트: 멱등성 가드 통과 시에만 즉시 실행
    for entry in _TIMETABLE:
        if entry["kind"] != "direct":
            continue
        h, m = entry["time"]
        event_sec = h * 3600 + m * 60
        if event_sec > now_sec:
            continue  # 아직 미래 — 예약 단계에서 처리
        # 이미 지난 direct 이벤트 — 멱등성 가드는 각 콜백 내부에서 수행
        # 단, 기동 시 중복 실행 방지를 위해 가드 상태 로깅만 (실제 실행은 _init_ws_subscribe_state 등 기존 기동 로직이 담당)
        logger.debug("[기동] 타임테이블 과거 direct 이벤트 — %s (기존 기동 로직이 이미 처리했는지 확인)", entry["ctx"])

    # 다음 미래 이벤트 예약
    _schedule_next_timetable_event()
```

> **주의**: 기동 시 직접 동작(`_on_realtime_fields_reset` 등)의 즉시 실행은 기존 `_init_ws_subscribe_state()` (라인 998-1053)가 이미 담당하고 있음. 본 스케줄러는 **중복 실행 금지** — 멱등성 가드(`state.last_*_date`)가 최후 방어선. 본 함수는 "다음 이벤트 예약"에만 집중 (P24 단순성).

### 4-6. state 신규 필드 (Step 6)

`engine_state.py`에 타이머 핸들 + JIF 수신 시각 추가.

```python
# engine_state.py 내 EngineState 클래스에 추가
self.timetable_timer_handle: asyncio.TimerHandle | None = None  # 타임테이블 단일 타이머
self.last_jif_received_at: datetime | None = None               # JIF 헬스체크용
```

> 기존 `market_phase_periodic_task` (라인 89 근처)는 제거 대상 — `_stop_market_phase_periodic_task()` 호출 후 `None` 처리.

### 4-7. JIF 수신 시각 갱신 (Step 7)

`engine_ws_dispatch.py` `_handle_jif()` 내에 1줄 추가.

```python
# engine_ws_dispatch.py _handle_jif() 진입부 (라인 257 근처)
async def _handle_jif(data: dict) -> None:
    jangubun = str(data.get("jangubun", "")).strip()
    jstatus = str(data.get("jstatus", "")).strip()
    if not jangubun or not jstatus:
        return
    # ── JIF 수신 시각 기록 (타임테이블 헬스체크용) ──
    from backend.app.services.daily_time_scheduler import _kst_now
    engine_state.state.last_jif_received_at = _kst_now()
    # ... 기존 로직 유지 ...
```

> P23 (일관성): `_kst_now()` 재사용. 신규 시각 계산 함수 생성 금지.

### 4-8. 기존 10초 루프 제거 (Step 8)

제거 대상:
- `_market_phase_periodic_loop()` (라인 1328-1355)
- `_start_market_phase_periodic_task()` (라인 1357-1363)
- `_stop_market_phase_periodic_task()` (라인 1366-1376)
- `state.market_phase_periodic_task` 필드

`start_daily_time_scheduler()` (라인 1382-1413) 내 `_start_market_phase_periodic_task()` 호출을 `_timetable_startup_scan()` 호출로 교체:

```python
# 기존 (라인 1407-1408):
#   _start_market_phase_periodic_task()
# 교체:
await _timetable_startup_scan()
```

`stop_daily_time_scheduler()` 내 `_stop_market_phase_periodic_task()` 호출을 타임테이블 타이머 취소로 교체:

```python
# 타임테이블 타이머 취소
if state.timetable_timer_handle is not None:
    state.timetable_timer_handle.cancel()
    state.timetable_timer_handle = None
```

> **코드 제거 규칙 준수**: 제거된 함수를 참조하는 모든 주석/docstring 함께 수정. `daily_time_scheduler.py` 라인 993-995의 "주기 태스크 _market_phase_periodic_loop()가 10초 간격으로..." 주석도 함께 갱신.

---

## 5. JIF 1순위 경로 유지 (변경 없음)

### 5-1. JIF 경로 (변경 없음)

```
WebSocket JIF 수신
  → engine_service._handle_ws_data()
  → handle_ws_data() (engine_ws_dispatch.py 라인 166)
  → _handle_jif() (라인 257)
      ├─ state.last_jif_received_at 갱신 (신규 1줄)
      └─ _apply_jif_phase() → _apply_market_phase() (기존 그대로)
```

### 5-2. 시간표 경로 (신규)

```
타임테이블 타이머 만료
  → _timetable_event_fired(entry)
      ├─ direct: _on_realtime_fields_reset() / _on_ws_subscribe_start() / _on_krx_pre_subscribe()
      ├─ phase:  _broadcast_market_phase() → _apply_market_phase()
      └─ _check_jif_health() + _schedule_next_timetable_event()
```

### 5-3. 양 경로 공통 종착점

`_apply_market_phase()` (라인 721-766) — JIF 경로와 시간표 경로 모두 이 함수에서 페이즈 적용 + 부작용 트리거. **P10 SSOT (적용 경로 단일)** 유지.

### 5-4. JIF vs 시간표 경쟁 조건

JIF 수신과 시간표 이벤트가 동시 발생 시:
- `_apply_market_phase()` 내 멱등성 보장 (같은 페이즈면 부작용 미발생, 라인 751 `if prev_krx != new_krx or prev_nxt != new_nxt`)
- `state.last_*_date` 가드로 direct 동작 중복 실행 차단
- **별도 락 불필요** (P24 단순성, P14 멀티스레드 금지 — 단일 이벤트 루프 내 순차 실행)

---

## 6. 기존 call_later 3개와의 관계 (1세션: 변경 없음)

| 타이머 | 위치 | 1세션 처리 | 사유 |
|--------|------|-----------|------|
| 확정 다운로드 (`schedule_ws_subscribe_timers`) | 라인 983 | **유지** | 사용자 설정 `confirmed_download_time` 기반, 시간표(고정 시각)와 성격 상이 |
| 자동매매 전환 (`schedule_auto_trade_timers`) | 라인 1193 | **유지** | 사용자 설정 `buy_time_start/end`, `sell_time_start/end` 기반, 동적 시각 |
| 자정 날짜 변경 (`schedule_midnight_timer`) | 라인 1254 | **유지** | 시간표 재로드 트리거 — 자정에 날짜 변경 + 타임테이블 타이머 재예약 필요 |

> **2세션 검토**: 자정 타이머 콜백 `_on_midnight()` (라인 1204) 내 `_schedule_next_timetable_event()` 호출 추가 여부는 1세션 구현 후 안정성 검증 후 결정. 1세션에서는 자정 타이머와 타임테이블 타이머가 독립 동작 — 자정 넘어가면 타임테이블의 "익일 첫 이벤트(07:58)" 예약이 자연 처리.

---

## 7. 변경 범위 및 파일 목록

| 파일 | 변경 유형 | 내용 | 예상 줄 수 |
|------|----------|------|-----------|
| `daily_time_scheduler.py` | 신규 추가 | `_TIMETABLE`, `_schedule_next_timetable_event()`, `_timetable_event_fired()`, `_check_jif_health()`, `_timetable_startup_scan()` | +90줄 |
| `daily_time_scheduler.py` | 제거 | `_market_phase_periodic_loop()`, `_start_market_phase_periodic_task()`, `_stop_market_phase_periodic_task()` | -50줄 |
| `daily_time_scheduler.py` | 수정 | `start_daily_time_scheduler()` 내 호출 교체, `stop_daily_time_scheduler()` 내 타이머 취소, 관련 주석 갱신 | ±10줄 |
| `engine_state.py` | 신규 필드 | `timetable_timer_handle`, `last_jif_received_at` + 기존 `market_phase_periodic_task` 제거 | ±3줄 |
| `engine_ws_dispatch.py` | 1줄 추가 | `_handle_jif()` 내 `last_jif_received_at` 갱신 | +1줄 |
| 테스트 파일 (신규) | 신규 | 타임테이블 스케줄러 단위 테스트 | +100줄 (별도) |

**순증**: `daily_time_scheduler.py` 약 +40줄 (신규 +90, 제거 -50). P24 파일 500줄 기준 내.

---

## 8. 구현 단계 (세션 내 순서)

> 규칙 0-1 (세션당 1단계) 준수: 본 설계서 전체가 1세션 1단계. 세션 내 세부 순서는 아래와 같으나, 한 세션에서 모두 완료 후 검증.

| 세부 Step | 내용 | 의존성 |
|-----------|------|--------|
| Step 1 | `_TIMETABLE` 자료구조 정의 (기존 상수 재사용) | 없음 |
| Step 2 | `_schedule_next_timetable_event()` 구현 | Step 1 |
| Step 3 | `_timetable_event_fired()` 구현 | Step 2 |
| Step 4 | `_check_jif_health()` 구현 | 없음 |
| Step 5 | `_timetable_startup_scan()` 구현 | Step 2 |
| Step 6 | `engine_state.py` 필드 추가/제거 | 없음 |
| Step 7 | `engine_ws_dispatch.py` JIF 수신 시각 갱신 | Step 6 |
| Step 8 | 기존 10초 루프 제거 + `start/stop_daily_time_scheduler()` 갱신 | Step 1-7 |
| Step 9 | 단위 테스트 작성 | Step 1-8 |
| Step 10 | 런타임 기동 검증 (규칙 5) | Step 9 |

---

## 9. 검증 계획

### 9-1. 단위 테스트 (Step 9)

| 테스트 케이스 | 검증 내용 |
|---------------|----------|
| 다음 이벤트 탐색 — 07:55 기동 | 07:58 이벤트 예약 (delay ≈ 180초) |
| 다음 이벤트 탐색 — 09:30 기동 | 15:20 이벤트 예약 (가장 가까운 미래 phase) |
| 다음 이벤트 탐색 — 20:30 기동 | 익일 07:58 예약 (24시간 + delay) |
| direct 이벤트 발생 | `_on_realtime_fields_reset()` 호출 + 다음 이벤트 예약 |
| phase 이벤트 발생 | `_broadcast_market_phase()` 호출 + 다음 이벤트 예약 |
| 멱등성 가드 | 같은 날 direct 이벤트 중복 실행 시 no-op |
| JIF 헬스체크 — 정상 | `last_jif_received_at` 최근 → 경고 없음 |
| JIF 헬스체크 — 미수신 | `last_jif_received_at` None 또는 120초 초과 → 경고 로그 |
| 기동 스캔 — 07:58:30 재기동 | 07:58 direct 이벤트 가드 확인 + 07:59 예약 |
| 타이머 취소 | `stop_daily_time_scheduler()` 시 `timetable_timer_handle.cancel()` |

### 9-2. 런타임 기동 검증 (Step 10, 규칙 5)

1. `python -W error::RuntimeWarning main.py` 기동 — async 경고 없음 확인
2. 기동 로그 확인: `[스케줄] 다음 타임테이블 이벤트 — ...` 출력
3. 10초 루프 제거 확인: 기존 `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 미출력
4. JIF 수신 시 `last_jif_received_at` 갱신 확인 (WS 연결 후 JIF 수신 시점)
5. 페이즈 전환 정상 동작 확인 (JIF 1순위 + 시간표 보완)

### 9-3. 회귀 체크

- [ ] 07:58 실시간 필드 초기화 정상 실행 (direct)
- [ ] 07:59 WS 구독 사전 시작 정상 실행 (direct)
- [ ] 08:00 NXT 프리마켓 진입 감지 (phase → `_apply_market_phase()` → `_on_nxt_premarket_start()`)
- [ ] 08:59 KRX 사전 구독 정상 실행 (direct)
- [ ] 09:00 KRX 정규장 진입 감지 (phase → `_on_krx_market_open()`)
- [ ] 15:20 KRX 종가 동시호가 진입 감지 (phase → `_on_krx_closing_auction_start()`)
- [ ] 20:00 NXT 장마감 진입 감지 (phase → `_on_ws_subscribe_end()`)
- [ ] `order_time_blocked` 브로드캐스트 정상 (P21 사용자 투명성)
- [ ] 자정 타이머 정상 동작 (기존 로직 유지)
- [ ] 확정 다운로드 타이머 정상 동작 (기존 로직 유지)
- [ ] 자동매매 전환 타이머 정상 동작 (기존 로직 유지)

---

## 10. 리스크 분석

| 리스크 | 확률 | 영향 | 대응 |
|--------|------|------|------|
| 기동 시 시간표 스캔 누락 (이미 지난 direct 동작 미실행) | 중 | 높음 | 기존 `_init_ws_subscribe_state()`가 이미 담당 + 멱등성 가드 `state.last_*_date` 최후 방어 |
| JIF 미수신 시 보정 지연 (최대 다음 이벤트까지) | 중 | 중 | 헬스체크 옵션 A로 경고. 시간표가 정시에 `_broadcast_market_phase()` 수행하므로 페이즈는 정확 유지 |
| call_later 콜백 내 예외 시 다음 이벤트 미예약 | 저 | 높음 | `_timetable_event_fired()` finally 블록에서 무조건 `_schedule_next_timetable_event()` 호출 |
| 시간표 편집 실수 (시간 중복/누락) | 저 | 중 | 1세션은 코드 내 고정 시간표이므로 리뷰로 방어. 2세션 DB 연동 시 정합성 검증 로직 추가 |
| 자정 넘어간 후 타임테이블 타이머 미재예약 | 저 | 높음 | `_schedule_next_timetable_event()`가 "익일 07:58" 예약. 자정 타이머는 별도 동작 (1세션) |
| `last_jif_received_at` 미갱신 (JIF 경로 누락) | 저 | 중 | Step 7에서 `_handle_jif()` 진입부에 1줄 추가 — 누락 시 코드 리뷰로 방어 |

---

## 11. 2세션 예고 (본 설계 범위 외)

1세션 안정화 후 검토 항목:

1. **DB 연동**: `integrated_system_settings` 재사용, 시간표를 JSON 값으로 저장. 설정 변경 시 캐시 갱신 + 타임테이블 재로드
2. **call_later 3개 통합**: 확정 다운로드/자동매매 전환 타이머를 시간표에 편입 (동적 시각 처리 로직 필요)
3. **예외 시간표**: 임시공휴일 등 요일별/날짜별 예외 스케줄 (JSON 리스트)
4. **자정 타이머와 시간표 통합**: 자정 콜백 내 `_schedule_next_timetable_event()` 호출로 익일 예약 명시화

---

## 12. 사용자 UI 영향 (P21 사용자 투명성)

### 12-1. 화면 변화: **없음**

- 페이즈 브로드캐스트: 기존과 동일 (`_apply_market_phase()` 내 `_broadcast("market-phase", ...)`)
- `order_time_blocked` 브로드캐스트: 기존과 동일
- 카운트다운 표시: 프론트엔드가 페이즈명 + 현재 시각으로 자체 계산 (기존과 동일, P24)

### 12-2. 사용자 인지 변화

- **정밀 트리거**: 07:58 실시간 필드 초기화가 07:58:00에 정확 실행 (기존 07:58:00~07:58:09 무작위 → 07:58:00 정확). 사용자는 체감 어려우나 로그로 확인 가능
- **JIF 미수신 경고**: 로그에 `[스케줄] JIF 미수신 120초 경과` 경고 추가. UI 알림은 2세션 검토

---

## 13. 핵심 설계 결정 요약

| 결정 | 사유 | 관련 원칙 |
|------|------|----------|
| 시간표를 코드 내 리스트로 정의 (DB 연동 2세션) | 1세션 패턴 검증 우선, 리스크 최소 | 규칙 0-1, P24 |
| direct/phase 두 종류를 동일 시간표에서 `kind` 필드로 구분 | 별도 리스트 분할 시 중복 스캔, 복잡도 증가 | P24 |
| JIF 경로는 1줄 추가만 (수신 시각 갱신) | JIF 1순위 구조 유지, 과도한 변경 금지 | P10, P16 |
| 헬스체크 옵션 A (이벤트 시점 체크) | 별도 타이머 추가 시 깨어름 증가, P24 위반 | P24 |
| 자정 타이머 별도 유지 | 시간표 재로드 트리거, 독립 역할 | P14 |
| 기동 스캔은 "다음 예약"에만 집중 | 직접 동작 즉시 실행은 기존 `_init_ws_subscribe_state()` 담당, 중복 금지 | P16, P22 |
| `_apply_market_phase()` 공통 종착점 유지 | JIF/시간표 양 경로 단일 적용, 멱등성 보장 | P10, P22 |

---

> **승인 대기**: 본 설계서의 구현 진행은 사용자 명시적 승인(규칙 0) 후 시작.
