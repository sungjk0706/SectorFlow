# 구현 계획서: 주기 태스크 추가 + 11개 타이머 제거 (3단계)

> **상태**: 사전조사 완료 · 구현 계획 수립 완료 · **사용자 승인 대기**
> **작성일**: 2026-07-16
> **관련 설계 문서**: `docs/architecture_session_state_design.md` (안 D — 하이브리드: JIF 1순위 + 시간 기반 보완)
> **관련 원칙**: P10(SSOT) · P11(폴링 금지) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P23(일관성) · P24(단순성)
> **단계 위치**: 안 D 구현 4단계 중 **3단계** (1단계: JIF jstatus 코드 맵핑 사전 검증 → 2단계: JIF 핸들러 확장 → **3단계: 본 파일** → 4단계: 런타임 통합 검증)

---

## 1. 배경 및 목적

### 1-1. 문제 상황

현재 장 상태 전환은 **로컬 타이머 11개**에 의존 (`daily_time_scheduler.py:749-759`):
- 08:00, 08:30, 08:40, 08:50, 09:00, 15:20, 15:30, 15:40, 16:00, 18:00, 20:00 시점에 `call_later` 예약 → `_broadcast_market_phase()` 호출

이 타이머들의 신뢰성 문제가 HANDOVER.md에 문서화됨:
- 08:00/09:00 타이머가 선택적으로 미실행 → `state.market_phase["krx"]` 미갱신 → KRX 수신률 0/0 고정
- macOS/Python 3.12 환경에서 `call_later` 타이머 관리 이슈 추정

2단계에서 JIF 핸들러 확장(`_handle_jif()` → `_apply_jif_phase()` → `_apply_market_phase()`)이 완료되어 JIF가 1순위 장 상태 소스로 동작. 하지만 **타이머 11개가 여전히 존재**하여:
- 타이머가 시간 기반 `calc_timebased_market_phase()`로 state를 덮어쓰는 구조가 잔존
- 타이머 미실행 시 부작용 누락 위험이 해결되지 않음
- 안 D 설계의 "타이머 0개" 목표 미달성

### 1-2. 목적 (3단계 범위)

1. **11개 market-phase 전환 타이머 제거**: `schedule_ws_subscribe_timers()` 내 타이머 루프 제거
2. **주기 태스크 추가**: 10초 간격으로 `calc_timebased_market_phase()` → `_apply_market_phase()` 호출하는 하우스키핑 주기 태스크
3. **주기 태스크 기동/종료 연결**: `start_daily_time_scheduler()`에서 시작, `stop_daily_time_scheduler()`에서 종료
4. **테스트**: 타이머 제거에 따른 기존 테스트 수정 + 주기 태스크 테스트 추가

### 1-3. 2단계 완료 상태 (전제)

- `_handle_jif()` → `_apply_jif_phase()` → `_apply_market_phase()` 경로 구축 완료 (JIF 1순위)
- `_broadcast_market_phase()` → `calc_timebased_market_phase()` → `_apply_market_phase()` 경로 유지 (시간 기반 보완)
- `_apply_market_phase()`에 부작용 트리거 로직 집중 (P10 SSOT — 페이즈 변경 감지 시 멱등성 보장)
- 임시 INFO 로그 `[연결] JIF 수신: jangubun=%s, jstatus=%s` 추가됨 (런타임 JIF 검증 대기 — 장 시간대 별도 진행)

---

## 2. 사전조사 결과 (심화)

### 2-1. 제거 대상: 11개 market-phase 전환 타이머

**위치**: `daily_time_scheduler.py:743-759` (`schedule_ws_subscribe_timers()` 내)

```python
# ★ market-phase 전환 시점 타이머
for hm_h, hm_m, label in (
    (8, 0, "08:00"), (8, 30, "08:30"), (8, 40, "08:40"), (8, 50, "08:50"),
    (9, 0, "09:00"),
    (15, 20, "15:20"), (15, 30, "15:30"), (15, 40, "15:40"), (16, 0, "16:00"),
    (18, 0, "18:00"), (20, 0, "20:00"),
):
    delay_mp = _seconds_until_hm(hm_h, hm_m)
    if delay_mp > 0 and loop:
        h = loop.call_later(max(delay_mp, 1), _broadcast_market_phase)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[스케줄] 장 상태 전환 (%s) — %.0f초 후 예약", label, delay_mp)
```

**제거 후**: `schedule_ws_subscribe_timers()`는 `confirmed_download_time` 타이머만 담당 (별도 기능, 유지).

### 2-2. `schedule_ws_subscribe_timers()` 호출 경로 (3곳)

| 호출 위치 | 파일:라인 | 호출 시점 | 타이머 제거 후 영향 |
|-----------|-----------|-----------|---------------------|
| `start_daily_time_scheduler()` | `daily_time_scheduler.py:1071` | 엔진 기동 시 | `confirmed_download_time` 타이머만 예약 — 정상 |
| `_on_midnight()` | `daily_time_scheduler.py:987` | 자정 콜백 (일일 재예약) | `confirmed_download_time` 타이머만 재예약 — 정상 |
| `engine_service.py:135` | 설정 변경 (PATCH) | 사용자 설정 변경 시 | `confirmed_download_time` 타이머만 재예약 — 정상 |

**결론**: 3곳 모두 `confirmed_download_time` 타이머 예약 목적이 주이므로 타이머 제거 후에도 함수 호출 유지. 함수명 `schedule_ws_subscribe_timers` 유지 (P23 — 기존 호출 경로 변경 최소화).

### 2-3. 주기 태스크 구현 패턴 (기존 자산 참조 — P23)

**참조 패턴**: `pipeline_compute.py:834` `_sector_recompute_loop_impl()`

```python
# Phase 2: 0.2초 배치 재계산 루프
while _compute_running:
    await asyncio.sleep(0.2)
    # ... 처리 로직 ...
```

**참조 패턴**: `pipeline_compute.py:185-217` `start_compute_loop()` / `stop_compute_loop()`

```python
async def start_compute_loop() -> None:
    global _compute_task, _compute_running
    if _compute_running:
        return
    _compute_running = True
    _compute_task = asyncio.get_running_loop().create_task(_compute_loop_impl())

async def stop_compute_loop() -> None:
    global _compute_running, _compute_task
    _compute_running = False
    if _compute_task:
        _compute_task.cancel()
        try:
            await _compute_task
        except asyncio.CancelledError:
            pass
        _compute_task = None
```

**적용**: 동일 패턴으로 `_market_phase_periodic_loop()` + `start`/`stop` 함수 구성.

### 2-4. P11 (폴링 금지) 검토

**P11 원칙**: `while + sleep` 폴링 도입 금지, `asyncio.Queue` + `asyncio.wait()` 이벤트 기반.

**안 D 설계의 주기 태스크는 P11 위반인가?** — **아님** (설계 문서 섹션 6-1 근거):
- NexusFi Academy "Trading Automation Fundamentals": "하우스키핑 타이머(세션 종료, 조정, 헬스 체크)는 이벤트 루프 내에서 허용."
- JIF가 1순위 이벤트 소스 (P11 준수 — 이벤트 기반).
- 주기 태스크는 **하우스키핑 보완** (WS 끊김, JIF 미수신, 네트워크 지연 시 살아있는 경로 — P16).
- `calc_timebased_market_phase()`는 순수 함수 (거래일 캐시 조회만, DB I/O 없음) → 10초 주기 CPU 부하 무시 가능.
- **기존 코드베이스에 동일 패턴 존재**: `_sector_recompute_loop_impl()` (0.2초), `_compute_loop_impl()` (0.5초 timeout) — P23 일관성.

### 2-5. `calc_timebased_market_phase()` 초 단위 무시 이슈 (NXT 09:00:30)

**현재**: `t = now.hour * 60 + now.minute` (line 112) — 초 단위 무시.
- `NXT_PREP_NONE_END = (9, 0)` → 09:00:00부터 "메인마켓" 산정.
- 실제 NXT 메인마켓은 09:00:30 시작 (사용자 보고).
- 09:00:00~09:00:30 사이 30초간 "메인마켓"으로 산정되나, JIF "21:장시작"이 09:00:00에 push되면 JIF가 우선 (1순위).

**3단계 처리 방침**: **본 3단계에 포함하지 않음** (별도 검토).
- JIF가 1순위이므로 30초 오차는 JIF push가 보완.
- 시간 기반 보완 경로에서 30초 오차는 무시 가능 수준 (10초 주기 태스크 + JIF 우선).
- 초 단위 판별은 `calc_timebased_market_phase()` 구조 변경이 필요하므로 별도 세션에서 검토.

### 2-6. 연쇄 영향 파일

| 파일 | 함수/변수 | 영향 | 수정 여부 |
|------|-----------|------|-----------|
| `backend/app/services/daily_time_scheduler.py` | `schedule_ws_subscribe_timers()` (타이머 루프 제거), 신규 `_market_phase_periodic_loop()` + `start`/`stop`, `start_daily_time_scheduler()` (주기 태스크 시작), `stop_daily_time_scheduler()` (주기 태스크 종료) | 핵심 수정 대상 | **수정** |
| `backend/app/services/engine_state.py` | 신규 `market_phase_periodic_task: asyncio.Task \| None` 필드 | 주기 태스크 핸들 저장 | **수정** |
| `backend/tests/test_daily_time_scheduler.py` | `TestScheduleWsSubscribeTimers` (타이머 제거 반영), 신규 `TestMarketPhasePeriodicLoop` 클래스 | 타이머 테스트 수정 + 주기 태스크 테스트 추가 | **수정** |
| `backend/app/services/engine_ws_dispatch.py` | — | 변경 없음 (2단계 완료) | 미수정 |
| `backend/app/services/engine_loop.py` | — | 변경 없음 (`start_daily_time_scheduler()`에서 주기 태스크 시작) | 미수정 |
| `frontend/` | — | 변경 없음 (WS "market-phase" 이벤트 구조 동일) | 미수정 |

---

## 3. 구현 계획

### 3-1. 신규 state 필드 (engine_state.py)

```python
# ── 스케줄러 상태 ── 섹션에 추가
self.market_phase_periodic_task: asyncio.Task | None = None
```

주기 태스크 핸들 저장 — `stop_daily_time_scheduler()`에서 취소.

### 3-2. 11개 타이머 제거 (daily_time_scheduler.py:743-759)

**제거 대상 코드**:
```python
# ★ market-phase 전환 시점 타이머
# KRX: 08:00 장전대기, ... 20:00 장마감
# NXT: 08:00 프리마켓, ... 20:00 장마감
for hm_h, hm_m, label in (
    (8, 0, "08:00"), (8, 30, "08:30"), (8, 40, "08:40"), (8, 50, "08:50"),
    (9, 0, "09:00"),
    (15, 20, "15:20"), (15, 30, "15:30"), (15, 40, "15:40"), (16, 0, "16:00"),
    (18, 0, "18:00"), (20, 0, "20:00"),
):
    delay_mp = _seconds_until_hm(hm_h, hm_m)
    if delay_mp > 0 and loop:
        h = loop.call_later(max(delay_mp, 1), _broadcast_market_phase)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[스케줄] 장 상태 전환 (%s) — %.0f초 후 예약", label, delay_mp)
```

**제거 후**: `schedule_ws_subscribe_timers()`는 `confirmed_download_time` 타이머만 담당.
- 주석 갱신: "market-phase 전환 타이머 제거됨 (3단계) — 주기 태스크 `_market_phase_periodic_loop()`가 시간 기반 보완 담당 (안 D, P10/P16/P24)."

### 3-3. 신규 주기 태스크 (daily_time_scheduler.py)

```python
_MARKET_PHASE_PERIODIC_INTERVAL = 10.0  # 10초 간격 (안 D 설계)


async def _market_phase_periodic_loop() -> None:
    """장 상태 시간 기반 보완 주기 태스크 (안 D — 하우스키핑 타이머).

    JIF가 1순위 장 상태 소스이나, WS 끊김/JIF 미수신/네트워크 지연 시
    시간 기반 계산이 살아있는 경로로 동작 (P16 살아있는 경로).
    10초 간격으로 calc_timebased_market_phase() → _apply_market_phase() 호출.
    페이즈 변경 감지는 _apply_market_phase() 내 멱등성 보장 (같은 페이즈면 부작용 미발생).

    P11 (폴링 금지) 준수: 하우스키핑 타이머는 이벤트 루프 내에서 허용
    (NexusFi Academy "Trading Automation Fundamentals" — 세션 종료/조정/헬스체크 타이머 허용).
    JIF가 1순위 이벤트 소스이므로 본 주기 태스크는 보완 역할.
    """
    logger.info("[기동] 장 상태 주기 태스크 시작 (10초 간격)")
    try:
        while not state.engine_stop_event.is_set():
            try:
                _broadcast_market_phase()
            except Exception as e:
                logger.warning("[스케줄] 장 상태 주기 계산 오류: %s", e, exc_info=True)
            try:
                await asyncio.wait_for(state.engine_stop_event.wait(), timeout=_MARKET_PHASE_PERIODIC_INTERVAL)
            except asyncio.TimeoutError:
                pass  # 10초 경과 → 다음 주기 실행
    except asyncio.CancelledError:
        logger.info("[스케줄] 장 상태 주기 태스크 취소됨")
        raise


def _start_market_phase_periodic_task() -> None:
    """주기 태스크 기동 — start_daily_time_scheduler()에서 호출."""
    if state.market_phase_periodic_task is not None:
        return
    state.market_phase_periodic_task = asyncio.get_running_loop().create_task(
        _market_phase_periodic_loop()
    )


async def _stop_market_phase_periodic_task() -> None:
    """주기 태스크 종료 — stop_daily_time_scheduler()에서 호출."""
    task = state.market_phase_periodic_task
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    state.market_phase_periodic_task = None
```

**설계 포인트**:
- `asyncio.wait_for(state.engine_stop_event.wait(), timeout=10.0)` — 10초 대기 또는 엔진 종료 시 즉시 종료 (P11 — 이벤트 기반 대기, `while + sleep` 폴링 아님).
- `_broadcast_market_phase()` 호출 → `calc_timebased_market_phase()` → `_apply_market_phase()` (기존 경로 재사용 — P10 SSOT).
- 페이즈 변경 감지 멱등성: `_apply_market_phase()` 내 `prev_krx != new_krx or prev_nxt != new_nxt` 검사로 같은 페이즈면 부작용 미발생.

### 3-4. `start_daily_time_scheduler()` 수정 (daily_time_scheduler.py:1048-1076)

기존 타이머 예약 후 주기 태스크 기동 추가:

```python
async def start_daily_time_scheduler() -> None:
    # ... 기존 로직 ...
    await schedule_auto_trade_timers(settings)
    await schedule_ws_subscribe_timers(settings)
    schedule_midnight_timer()
    # ── 장 상태 주기 태스크 기동 (안 D 3단계 — 시간 기반 보완) ──
    _start_market_phase_periodic_task()
    # ...
```

### 3-5. `stop_daily_time_scheduler()` 수정 (daily_time_scheduler.py:1079-1091)

기존 타이머 취소 후 주기 태스크 종료 추가:

```python
async def stop_daily_time_scheduler() -> None:
    # ... 기존 타이머 취소 ...
    # ── 장 상태 주기 태스크 종료 (안 D 3단계) ──
    await _stop_market_phase_periodic_task()
    logger.info("[스케줄] 중지")
```

### 3-6. `_on_midnight()` 영향 검토 (daily_time_scheduler.py:987)

자정 콜백에서 `schedule_ws_subscribe_timers(settings)` 호출 — 타이머 제거 후 `confirmed_download_time` 타이머만 재예약.
**주기 태스크는 자정에 재기동 불필요** — `engine_stop_event`가 set되지 않는 한 계속 실행 (날짜 변경 시 `calc_timebased_market_phase()`가 자동으로 거래일/휴장일 판별).

---

## 4. 테스트 계획

### 4-1. 기존 테스트 수정

#### `TestScheduleWsSubscribeTimers` (test_daily_time_scheduler.py:1243)
- `test_cancels_existing_and_schedules`: 11개 타이머 제거 후 `confirmed_download_time` 타이머만 예약되는지 검증으로 수정.
  - 기존: `assert len(mock_state.ws_subscribe_timer_handles) > 0`
  - 수정 후: `assert len(mock_state.ws_subscribe_timer_handles) == 1` (confirmed_download_time 타이머 1개만)
- `test_no_loop_skips`: 변경 없음 (loop 없을 시 스킵 — 동일).

#### `TestStopDailyTimeScheduler` (test_daily_time_scheduler.py:1182)
- `test_cancels_all_timers`: 주기 태스크 취소 검증 추가.
  - `mock_state.market_phase_periodic_task` 추가 설정.
- `test_no_timers_no_error`: 주기 태스크 None 케이스 추가.

#### `TestStartDailyTimeScheduler` (test_daily_time_scheduler.py:1213)
- `test_initializes_and_schedules`: 주기 태스크 기동 검증 추가.
  - `_start_market_phase_periodic_task` mock 추가.

### 4-2. 신규 테스트: `TestMarketPhasePeriodicLoop`

```python
class TestMarketPhasePeriodicLoop:
    """주기 태스크 기동/종료 + 10초 간격 실행 + 엔진 종료 시 즉시 종료 테스트."""

    def test_start_creates_task(self):
        # _start_market_phase_periodic_task() 호출 시 state.market_phase_periodic_task 설정

    def test_start_no_duplicate(self):
        # 이미 task가 있으면 재생성하지 않음

    async def test_stop_cancels_task(self):
        # _stop_market_phase_periodic_task() 호출 시 task 취소 + None 설정

    async def test_stop_no_task_no_error(self):
        # task가 None이어도 에러 없음

    async def test_loop_calls_broadcast_market_phase(self):
        # _market_phase_periodic_loop()가 _broadcast_market_phase()를 호출하는지

    async def test_loop_stops_on_engine_stop(self):
        # engine_stop_event.set() 시 루프 즉시 종료

    async def test_loop_continues_on_exception(self):
        # _broadcast_market_phase() 예외 시 루프 계속 실행 (다음 주기 재시도)
```

### 4-3. 검증 항목

| 항목 | 방법 |
|------|------|
| py_compile | `python -m py_compile daily_time_scheduler.py engine_state.py` |
| ruff | `ruff check daily_time_scheduler.py engine_state.py test_daily_time_scheduler.py` |
| pytest | `pytest test_daily_time_scheduler.py -v` (기존 테스트 + 신규 테스트) |
| 런타임 기동 | `python -W error::RuntimeWarning main.py` — RuntimeWarning 0건, `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 확인 |
| 타이머 제거 확인 | 런타임 로그에서 `[스케줄] 장 상태 전환` DEBUG 로그 미출력 확인 |
| 주기 태스크 동작 | 런타임 로그에서 10초 간격 `_broadcast_market_phase()` 호출 확인 (페이즈 변경 시 `[장상태]` 로그) |

---

## 5. 런타임 검증 방법

### 5-1. 기동 검증

```bash
cd backend && python -W error::RuntimeWarning main.py
```

확인 항목:
1. `[기동] 장 상태 계산 완료 | KRX: {상태}, NXT: {상태}` 로그 (기존)
2. `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 (신규)
3. RuntimeWarning / Traceback 0건
4. 잔존 프로세스 0건 (기동 후 종료)

### 5-2. 타이머 제거 확인

기동 후 로그에서:
- `[스케줄] 장 상태 전환 (08:00)` 등 DEBUG 로그 미출력 (11개 타이머 제거됨)
- `[스케줄] 확정 시세 다운로드 (20:40)` DEBUG 로그만 출력 (confirmed_download_time 타이머 유지)

### 5-3. 주기 태스크 동작 확인

- 10초 간격으로 `_broadcast_market_phase()` 호출 (페이즈 변경 시에만 `[장상태]` 로그 출력 — 멱등성)
- 페이즈 변경 없을 시 로그 미출력 (멱등성 검증)

### 5-4. JIF 런타임 검증 (별도 진행 — 장 시간대)

2단계에서 추가된 임시 INFO 로그 `[연결] JIF 수신: jangubun=%s, jstatus=%s`로 장 시작 시점 실제 push 코드 확인.
- **현재 장 마감 시간이라 런타임 JIF 검증 불가 — 다음 장 시간대에 별도 진행**.
- 맵핑 테이블과 불일치 시 4단계 진행 전 맵 수정.

---

## 6. 승인 대기 항목

1. **3단계 구현 승인** (사용자 실행 지시어 대기 — 규칙 0).
2. **NXT 09:00:30 문제**: 본 3단계에 포함하지 않음 (별도 검토). JIF가 1순위이므로 30초 오차는 JIF push가 보완. 초 단위 판별은 `calc_timebased_market_phase()` 구조 변경이 필요하므로 별도 세션에서 검토.
3. **WS 07:55/07:59 조정**: 본 3단계에 포함하지 않음. 현재 코드에 07:55/07:59 시각 없음. WS 연결을 08:00보다 일찍 시작하려면 별도 트리거 필요 — 별도 세션에서 검토.
4. **주기 태스크 간격 (10초)**: 안 D 설계 기준. 변경 필요 시 사용자 결정.
5. **`schedule_ws_subscribe_timers()` 함수명 유지**: 타이머 제거 후에도 함수명 유지 (P23 — 기존 호출 경로 3곳 변경 최소화). 함수명 변경 원할 경우 사용자 결정.

---

## 7. UI 기준 변경 설명 (규칙 0-4)

### 변경 전 (현재 화면)
- 앱 기동 후 11개 타이머가 각 시점(08:00, 09:00, 15:30 등)에 장 상태를 갱신.
- 타이머가 미실행 시 화면에서 KRX 수신률이 표시되지 않는 문제 발생.

### 변경 후 (화면 변화)
- 11개 타이머 대신 **10초 간격 주기 태스크**가 장 상태를 갱신.
- JIF(거래소 push)가 1순위 → 장 상태 전환 시 즉시 화면 반영.
- JIF 미수신 시 10초 내 시간 기반 계산이 보완 → 화면에 장 상태 누락 없음.
- 타이머 미실행 문제 근본 해결 → KRX 수신률 미표시 문제 재발 방지.

### 사용자가 확인할 수 있는 영향
- 화면의 장 상태(KRX/NXT) 표시가 10초 내 갱신 (이전: 타이머 시점에만 갱신).
- 장 시작/종료 시점에 화면 장 상태가 누락 없이 전환.
- KRX 수신률 미표시 문제 재발 방지 (타이머 의존성 제거).
