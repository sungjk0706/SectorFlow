# 구현 계획서: 장 상태 시간 정밀 조정 + 런타임 통합 검증 (4단계)

> **상태**: 사전조사 완료 · 구현 계획 수립 완료 · **사용자 승인 대기**
> **작성일**: 2026-07-16
> **관련 설계 문서**: `backend/docs/architecture_session_state_design.md` (안 D — 하이브리드: JIF 1순위 + 시간 기반 보완)
> **관련 원칙**: P10(SSOT) · P11(폴링 금지) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)
> **단계 위치**: 안 D 구현 4단계 중 **4단계** (1단계: JIF jstatus 코드 맵핑 사전 검증 → 2단계: JIF 핸들러 확장 → 3단계: 주기 태스크 전환 → **4단계: 본 파일**)

---

## 1. 배경 및 목적

### 1-1. 문제 상황

3단계 완료 후 장 상태 관리는 JIF 1순위 + 10초 간격 주기 태스크 보완 구조로 동작. 하지만 3단계에서 "별도 검토"로 미뤄던 3가지 시간 정밀 이슈가 잔존:

1. **WS 구독 시작 시점 (08:00)**: `_on_ws_subscribe_start()`가 NXT "프리마켓" 페이즈 진입(08:00) 감지 시 트리거. WS 연결 + 실시간 필드 초기화가 08:00에 시작되므로, 08:00 NXT 프리마켓 체결 데이터 수신 시작 시점에 WS가 아직 연결되지 않았을 수 있음 → 초기 틱 누락 위험.
2. **실시간 필드 초기화 시점 (08:00)**: `_on_ws_subscribe_start()` 안에서 `_reset_realtime_fields()` 호출. WS 구독 시작과 같은 시점에 전일 확정 데이터 제거 → 08:00 이전에 잔존하는 전일 데이터가 섞일 수 있음.
3. **NXT 메인마켓 전환 시각 (09:00:00 vs 09:00:30)**: `calc_timebased_market_phase()`가 분 단위 판별(`t = hour*60+minute`)을 사용. `NXT_PREP_NONE_END = (9, 0)` → 09:00:00부터 "메인마켓" 산정. 실제 NXT 메인마켓은 09:00:30 시작 (사용자 보고). 09:00:00~09:00:30 사이 30초간 "메인마켓"으로 잘못 산정. JIF "21:장시작"이 1순위이므로 보완되나, 시간 기반 보완 경로의 정확도 개선 필요.

### 1-2. 목적 (4단계 범위)

1. **WS 구독 시작 시각 조정: 08:00 → 07:59**: phase 계산은 실제 스케줄(08:00) 유지, WS 구독 시작 부작용만 07:59에 사전 트리거. 08:00 NXT 프리마켓 체결 시작 전 WS 연결 완료.
2. **실시간 필드 초기화 시각 조정: 08:00 → 07:58**: WS 구독 시작(07:59)과 분리하여 07:58에 단독 트리거. 전일 확정 데이터를 WS 구독 시작 1분 전에 제거.
3. **NXT 메인마켓 전환 시각 정밀화: 09:00:00 → 09:00:30**: `calc_timebased_market_phase()` NXT 부분만 초 단위 예외 처리. KRX 정규장(09:00:00)은 분 단위 유지.
4. **jstatus 52 표시 문구 수정**: **본 4단계에서 제외** (사용자 결정 — 별도 세션에서 진행).
5. **런타임 통합 검증**: 장 시간대 JIF push + 주기 태스크 + 사전 트리거 실제 동작 확인 (별도 진행 — 장 시간대).

### 1-3. 3단계 완료 상태 (전제)

- 11개 market-phase 전환 타이머 제거 완료 (`schedule_ws_subscribe_timers()` 내 루프).
- 10초 간격 주기 태스크 `_market_phase_periodic_loop()` 기동/종료 연결 완료.
- `_apply_market_phase()`에 부작용 트리거 로직 집중 (페이즈 변경 감지 시 멱등성 보장).
- `_apply_market_phase()` 부작용 트리거:
  - `new_nxt == "프리마켓"` → `_on_nxt_premarket_start()` + `_on_ws_subscribe_start()` (08:00)
  - `new_krx == "정규장"` → `_on_krx_market_open()` (09:00)
  - `new_krx == "체결 정산"` → `_on_krx_after_hours_start()` (15:30)
  - `new_nxt == "장마감"` → `_on_ws_subscribe_end()` (20:00)

---

## 2. 사전조사 결과 (심화)

### 2-1. 사용자 결정 사항 (설계 방향 확정)

| 항목 | 사용자 결정 | 설계 방향 |
|------|-------------|-----------|
| WS 구독 07:59 | phase는 08:00 유지, WS만 07:59 | phase 계산과 부작용 트리거 분리 — 주기 태스크에서 시각 기반 사전 트리거 |
| 필드 초기화 07:58 | 분리 — 07:58 단독 트리거 | `_on_ws_subscribe_start()`에서 `_reset_realtime_fields()` 분리 → 별도 함수 |
| NXT 09:00:30 | NXT만 초 단위 예외 | `calc_timebased_market_phase()` NXT 메인마켓 전환만 초 단위 판별 추가 |
| jstatus 52 문구 | 4단계에서 제외 | 별도 세션에서 진행 |

### 2-2. 현재 `_on_ws_subscribe_start()` 구조 (daily_time_scheduler.py:586-621)

```python
async def _on_ws_subscribe_start() -> None:
    # 1. 장중 GC 비활성화
    gc.disable()
    # 2. 거래일/설정 체크
    # 3. state.ws_subscribe_window_active = True
    # 4. 수신율 임계값 게이트 리셋
    # 5. 실시간 필드 초기화 (← 본 4단계에서 분리 대상)
    await _reset_realtime_fields()
    # 6. delta 비교 캐시 초기화
    # 7. _broadcast_market_phase()
    # 8. state.ws_window_changed_event.set()
```

**분리 대상**: 5번 `_reset_realtime_fields()` 호출 → 별도 `_on_realtime_fields_reset()` 함수로 추출.

### 2-3. 부작용 트리거 경로 (3곳 — 중복 실행 위험)

| 경로 | 트리거 시점 | 4단계 변경 |
|------|-------------|-------------|
| `_apply_market_phase()` — `new_nxt == "프리마켓"` | 08:00 (phase 변경 감지) | **유지** — JIF 1순위 + 시간 기반 08:00 보완. 멱등성 가드로 07:59 사전 실행 후 중복 방지 |
| 주기 태스크 사전 트리거 (신규) | 07:59 (시각 기반) | **신규 추가** — WS 구독 시작만 07:59에 사전 실행 |
| 주기 태스크 사전 트리거 (신규) | 07:58 (시각 기반) | **신규 추가** — 실시간 필드 초기화만 07:58에 사전 실행 |

**중복 실행 시나리오**:
- 07:58: 주기 태스크가 `_on_realtime_fields_reset()` 트리거 (필드 초기화)
- 07:59: 주기 태스크가 `_on_ws_subscribe_start()` 트리거 (WS 구독 시작 — 필드 초기화 제외)
- 08:00: phase "프리마켓" 진입 → `_apply_market_phase()`가 `_on_ws_subscribe_start()` 재트리거 → **멱등성 가드로 스킵**

→ 멱등성 가드 필수: `_on_ws_subscribe_start()`와 `_on_realtime_fields_reset()` 모두 "이미 실행됐으면 스킵" 가드 추가.

### 2-4. 멱등성 가드 방식 검토

| 방식 | 구현 | 장단점 |
|------|------|--------|
| A. `ws_subscribe_window_active` 플래그 | 이미 True면 스킵 | 단순. 하지만 필드 초기화는 별도 가드 필요 |
| B. 날짜 기반 플래그 | `state.last_realtime_reset_date`, `state.last_ws_subscribe_start_date` | 정확 — 날짜 변경 시 자동 리셋. 자정 콜백에서 플래그 초기화 불필요 (날짜 비교로 자동 해결) |
| C. 단순 bool 플래그 | `state.realtime_fields_initialized`, `state.ws_subscribe_started` | 단순. 하지만 자정에 리셋 필요 — 리셋 누락 시 다음 날 실행 안 됨 |

**추천: B (날짜 기반 플래그)** — 자정 리셋 불필요, P22(데이터 정합성) 준수. 기존 `state.last_reset_date` 패턴 참조 (P23 일관성).

### 2-5. NXT 메인마켓 09:00:30 초 단위 예외 처리

**현재** (daily_time_scheduler.py:151-154):
```python
elif t < _m(NXT_PREP_NONE_END):    # t < 540 (09:00)
    nxt = "정규장 준비"
elif t < _m(NXT_MAINMARKET_END):   # t < 920 (15:20)
    nxt = "메인마켓"
```

**변경 후** (NXT 메인마켓 전환만 초 단위 예외):
```python
elif t < _m(NXT_PREP_NONE_END):
    nxt = "정규장 준비"
elif t == _m(NXT_PREP_NONE_END) and now.second < 30:
    nxt = "정규장 준비"           # 09:00:00~09:00:29 — 정규장 준비 유지
elif t < _m(NXT_MAINMARKET_END):
    nxt = "메인마켓"              # 09:00:30~ — 메인마켓
```

**영향 범위**: `calc_timebased_market_phase()` 내 NXT 분기만 수정. KRX 분기는 분 단위 유지 (KRX 정규장 09:00:00 시작 — 초 단위 무관).
- `now.second` 접근 필요 → 기존 `t = now.hour * 60 + now.minute` 유지, `now` 변수 추가 활용.
- 주기 태스크 10초 간격 → 09:00:30~09:00:40 사이에 "메인마켓" 전환 (최대 10초 지연). JIF "21:장시작"이 1순위이므로 보완.

### 2-6. 사전 트리거 시각 상수 (신규)

```python
# ── 사전 트리거 시각 (장 시작 전 사전 준비) ──
REALTIME_FIELDS_RESET_TIME = (7, 58)   # 07:58 실시간 필드 초기화 (WS 구독 1분 전)
WS_SUBSCRIBE_PRESTART_TIME = (7, 59)   # 07:59 WS 구독 사전 시작 (NXT 프리마켓 1분 전)
NXT_MAINMARKET_START_SECOND = 30       # 09:00:30 NXT 메인마켓 시작 (초 단위)
```

### 2-7. 주기 태스크 내 사전 트리거 로직 위치

**현재** `_market_phase_periodic_loop()` (3단계 구현):
```python
async def _market_phase_periodic_loop() -> None:
    while not engine_stop_event.is_set():
        _broadcast_market_phase()
        await asyncio.wait_for(engine_stop_event.wait(), timeout=10)
```

**변경 후** — 사전 트리거 체크 추가:
```python
async def _market_phase_periodic_loop() -> None:
    while not engine_stop_event.is_set():
        _check_prestart_triggers()       # 신규 — 07:58/07:59 사전 트리거
        _broadcast_market_phase()
        await asyncio.wait_for(engine_stop_event.wait(), timeout=10)
```

`_check_prestart_triggers()` 신규 함수:
- 현재 KST 시각이 07:58 이상이고 거래일이면 `_on_realtime_fields_reset()` 트리거 (날짜 플래그로 중복 방지)
- 현재 KST 시각이 07:59 이상이고 거래일이면 `_on_ws_subscribe_start()` 트리거 (날짜 플래그로 중복 방지)
- 08:00 이상이면 사전 트리거 체크 스킵 (phase 변경 감지가 담당)

### 2-8. 연쇄 영향 파일

| 파일 | 함수/변수 | 영향 | 수정 여부 |
|------|-----------|------|-----------|
| `backend/app/services/daily_time_scheduler.py` | `calc_timebased_market_phase()` (NXT 초 단위 예외), `_on_ws_subscribe_start()` (필드 초기화 분리 + 멱등성 가드), 신규 `_on_realtime_fields_reset()`, 신규 `_check_prestart_triggers()`, `_market_phase_periodic_loop()` (사전 트리거 호출), 신규 상수 3개 | 핵심 수정 대상 | **수정** |
| `backend/app/services/engine_state.py` | 신규 `last_realtime_reset_date: str`, `last_ws_subscribe_start_date: str` 필드 | 날짜 기반 멱등성 플래그 | **수정** |
| `backend/tests/test_daily_time_scheduler.py` | `calc_timebased_market_phase()` NXT 09:00:30 테스트, `_on_realtime_fields_reset()` 테스트, `_check_prestart_triggers()` 테스트, `_on_ws_subscribe_start()` 멱등성 테스트 | 신규 테스트 + 기존 테스트 수정 | **수정** |
| `backend/app/services/engine_ws_dispatch.py` | — | 변경 없음 (JIF 맵 그대로) | 미수정 |
| `backend/app/services/engine_snapshot.py` | `_reset_realtime_fields()` | 변경 없음 (호출 경로만 분리) | 미수정 |
| `backend/app/services/engine_cache.py` | `_load_caches_preboot()` 내 `_reset_realtime_fields()` 호출 | 재기동 시 필드 초기화 경로 — `last_realtime_reset_date` 플래그 동기화 필요 | **수정 (플래그 동기화만)** |
| `frontend/` | — | 변경 없음 (WS "market-phase" 이벤트 구조 동일, 페이즈명 동일) | 미수정 |

---

## 3. 구현 계획

### 3-1. 신규 state 필드 (engine_state.py)

```python
# ── 스케줄러 상태 ── 섹션에 추가 (기존 market_phase_periodic_task 근처)
self.last_realtime_reset_date: str = ""        # 실시간 필드 초기화 실행 날짜 (YYYYMMDD) — 멱등성 가드
self.last_ws_subscribe_start_date: str = ""    # WS 구독 시작 실행 날짜 (YYYYMMDD) — 멱등성 가드
```

### 3-2. 신규 상수 (daily_time_scheduler.py — 상단 상수 섹션)

```python
# ── 사전 트리거 시각 (장 시작 전 사전 준비 — 안 D 4단계) ──
REALTIME_FIELDS_RESET_TIME = (7, 58)   # 07:58 실시간 필드 초기화 (WS 구독 1분 전)
WS_SUBSCRIBE_PRESTART_TIME = (7, 59)   # 07:59 WS 구독 사전 시작 (NXT 프리마켓 1분 전)
NXT_MAINMARKET_START_SECOND = 30       # 09:00:30 NXT 메인마켓 시작 (초 단위 예외)
```

### 3-3. `calc_timebased_market_phase()` NXT 초 단위 예외 (daily_time_scheduler.py:146-164)

```python
# ── NXT ──
if t < _m(NXT_PREMARKET_START):
    nxt = "장개시전"
elif t < _m(NXT_PREMARKET_END):
    nxt = "프리마켓"
elif t < _m(NXT_PREP_NONE_END):
    nxt = "정규장 준비"
elif t == _m(NXT_PREP_NONE_END) and now.second < NXT_MAINMARKET_START_SECOND:
    nxt = "정규장 준비"           # 09:00:00~09:00:29 — 정규장 준비 유지 (초 단위 예외)
elif t < _m(NXT_MAINMARKET_END):
    nxt = "메인마켓"              # 09:00:30~ — 메인마켓
# ... 이하 동일 ...
```

**주의**: `now` 변수는 이미 line 110 `now = _kst_now()`에서 정의됨. `now.second` 접근 가능.

### 3-4. `_on_realtime_fields_reset()` 신규 함수 (daily_time_scheduler.py)

`_on_ws_subscribe_start()`에서 분리한 실시간 필드 초기화 전용 함수:

```python
async def _on_realtime_fields_reset() -> None:
    """07:58 사전 트리거 — 실시간 필드 초기화 (전일 확정 데이터 제거).

    WS 구독 시작(07:59)과 분리하여 1분 먼저 실행 — WS 연결 전에 전일 데이터 제거.
    날짜 기반 멱등성 가드: 같은 날 중복 실행 방지 (P22 데이터 정합성).
    """
    try:
        today = _kst_now()
        today_str = today.strftime("%Y%m%d")
        if state.last_realtime_reset_date == today_str:
            return  # 이미 오늘 실행됨 — 중복 방지
        from backend.app.core.trading_calendar import is_trading_day
        if today.weekday() >= 5 or not is_trading_day(today.date()):
            return
        settings = state.integrated_system_settings_cache
        if not bool(settings.get("ws_subscribe_on", False)):
            logger.info("[작업실행] 실시간 필드 초기화 생략 (수동 모드)")
            return
        logger.info("[작업실행] 실시간 필드 초기화 (사전 — 07:58)")
        from backend.app.services.engine_snapshot import _reset_realtime_fields
        await _reset_realtime_fields()
        state.last_realtime_reset_date = today_str
        logger.info("[작업실행] 실시간 필드 초기화 완료 (사전)")
    except Exception as e:
        logger.warning("[작업실행] 실시간 필드 초기화 오류: %s", e, exc_info=True)
```

### 3-5. `_on_ws_subscribe_start()` 수정 (daily_time_scheduler.py:586-621)

1. **실시간 필드 초기화 호출 제거** (line 607-610) — `_on_realtime_fields_reset()`으로 이관.
2. **멱등성 가드 추가** — 날짜 기반 중복 실행 방지.

```python
async def _on_ws_subscribe_start() -> None:
    """WS 구독 시작 — WS 연결 + 실시간 데이터 수신 시작.

    07:59 사전 트리거 (주기 태스크) 또는 08:00 phase 변경 감지 (_apply_market_phase)로 호출.
    날짜 기반 멱등성 가드: 같은 날 중복 실행 방지.
    실시간 필드 초기화는 _on_realtime_fields_reset()에서 07:58에 사전 실행 (분리).
    """
    try:
        today = _kst_now()
        today_str = today.strftime("%Y%m%d")
        if state.last_ws_subscribe_start_date == today_str:
            logger.debug("[작업실행] WS 구독 시작 스킵 (이미 실행됨 — %s)", today_str)
            return
        # 장중 GC 비활성화 (HFT 지연 방지)
        gc.disable()
        logger.info("[스케줄] 장중 메모리 정리 비활성화 (실시간 처리 지연 방지)")
        if today.weekday() >= 5:
            return
        settings = state.integrated_system_settings_cache
        if not is_trading_day(today.date()):
            return
        if not bool(settings.get("ws_subscribe_on", False)):
            logger.info("[작업실행] WS 구독 시작 생략 (수동 모드)")
            return
        logger.info("[작업실행] WS 구독 시작")
        state.ws_subscribe_window_active = True
        state.last_ws_subscribe_start_date = today_str
        # ── 수신율 임계값 게이트 리셋 ──
        from backend.app.pipelines.pipeline_compute import reset_sector_threshold
        reset_sector_threshold()
        # ── 실시간 필드 초기화는 07:58 사전 실행됨 (_on_realtime_fields_reset) ──
        #    사전 실행 누락 시 여기서 보완 (멱등성 — last_realtime_reset_date 체크)
        if state.last_realtime_reset_date != today_str:
            logger.info("[스케줄] 실시간 필드 초기화 (사전 실행 누락 — 보완)")
            from backend.app.services.engine_snapshot import _reset_realtime_fields
            await _reset_realtime_fields()
            state.last_realtime_reset_date = today_str
        # delta 비교 캐시 초기화
        from backend.app.services.engine_account_notify import notify_cache
        notify_cache.prev_scores = []
        state.sector_summary_cache = None
        _broadcast_market_phase()
        state.ws_window_changed_event.set()
        logger.info("[작업실행] WS 구독 시작 완료 — 엔진 루프에 연결 통지")
    except Exception as e:
        logger.warning("[작업실행] WS 구독 시작 콜백 오류: %s", e, exc_info=True)
```

**보완 경로**: 07:58 사전 실행이 누락된 경우(예: 07:58에 엔진 꺼져 있음 → 07:59 이후 기동) WS 구독 시작 안에서 필드 초기화 보완. `last_realtime_reset_date != today_str`이면 보완 실행. P16(살아있는 경로) 준수.

### 3-6. `_check_prestart_triggers()` 신규 함수 (daily_time_scheduler.py)

```python
def _check_prestart_triggers() -> None:
    """주기 태스크 내 사전 트리거 체크 — 07:58/07:59 시각 도달 시 사전 실행.

    phase 계산(08:00)과 분리하여 부작용만 사전 실행 (P10 SSOT — phase는 실제 스케줄 유지).
    날짜 기반 멱등성 가드로 중복 실행 방지 (P22).
    """
    try:
        now = _kst_now()
        today_str = now.strftime("%Y%m%d")
        t = now.hour * 60 + now.minute
        reset_t = _m(REALTIME_FIELDS_RESET_TIME)    # 478 (07:58)
        prestart_t = _m(WS_SUBSCRIBE_PRESTART_TIME) # 479 (07:59)
        market_t = _m(NXT_PREMARKET_START)           # 480 (08:00)
        # 08:00 이상이면 사전 트리거 구간 아님 — phase 변경 감지가 담당
        if t >= market_t:
            return
        # 07:58 이상 — 실시간 필드 초기화 사전 트리거
        if t >= reset_t and state.last_realtime_reset_date != today_str:
            schedule_engine_task(_on_realtime_fields_reset(), context="실시간 필드 초기화 (사전 07:58)")
        # 07:59 이상 — WS 구독 시작 사전 트리거
        if t >= prestart_t and state.last_ws_subscribe_start_date != today_str:
            schedule_engine_task(_on_ws_subscribe_start(), context="WS 구독 시작 (사전 07:59)")
    except Exception as e:
        logger.warning("[스케줄] 사전 트리거 체크 오류: %s", e, exc_info=True)
```

### 3-7. `_market_phase_periodic_loop()` 수정

```python
async def _market_phase_periodic_loop() -> None:
    while not engine_stop_event.is_set():
        try:
            _check_prestart_triggers()       # 신규 — 07:58/07:59 사전 트리거
            _broadcast_market_phase()
        except Exception as e:
            logger.warning("[스케줄] 주기 태스크 오류: %s", e, exc_info=True)
        await asyncio.wait_for(engine_stop_event.wait(), timeout=10)
```

### 3-8. `_init_ws_subscribe_state()` 수정 (daily_time_scheduler.py:748-794)

재기동 시 구독 구간 내 기동 — `last_realtime_reset_date` / `last_ws_subscribe_start_date` 플래그 동기화:
- 구독 구간 내 기동 시 이미 WS 구독이 활성 → `last_ws_subscribe_start_date`를 오늘 날짜로 설정 (중복 실행 방지).
- 실시간 필드 초기화는 `preboot_cache_loaded` 체크 후 실행 — 실행 시 `last_realtime_reset_date`를 오늘 날짜로 설정.

```python
# 기존 line 766-790 영역 수정
if in_window:
    # ... 기존 GC 비활성화 ...
    today_str = _kst_now().strftime("%Y%m%d")
    state.last_ws_subscribe_start_date = today_str  # 신규 — 중복 실행 방지
    if state.preboot_cache_loaded:
        logger.info("[스케줄] 구독 구간 내 시작 — 실시간 필드 초기화")
        from backend.app.services.engine_snapshot import _reset_realtime_fields
        await _reset_realtime_fields()
        state.last_realtime_reset_date = today_str  # 신규 — 중복 실행 방지
    # ... 이하 동일 ...
```

### 3-9. `engine_cache.py` `_load_caches_preboot()` 수정 (line 96-103)

DB 로드 후 실시간 필드 초기화 시 `last_realtime_reset_date` 동기화:

```python
# 기존 line 101-103 영역
from backend.app.services.engine_snapshot import _reset_realtime_fields
await _reset_realtime_fields()
state.last_realtime_reset_date = _kst_now().strftime("%Y%m%d")  # 신규 — 플래그 동기화
logger.info("[데이터] 실시간 통신 구독 구간 — 실시간 필드 초기화 완료 (DB 로드 후)")
```

**주의**: `engine_cache.py`에서 `_kst_now()` import 필요 — `from backend.app.services.daily_time_scheduler import _kst_now` 또는 직접 `datetime.now(KST)`. P23 일관성 — 기존 `_kst_now()` 재사용 추천.

---

## 4. 테스트 계획

### 4-1. 기존 테스트 수정

#### `TestCalcTimebasedMarketPhase` (test_daily_time_scheduler.py)
- NXT 09:00:00 케이스: `now.second = 0` → "정규장 준비" 유지 검증 (기존: "메인마켓" → 수정: "정규장 준비").
- NXT 09:00:29 케이스: `now.second = 29` → "정규장 준비" 유지 검증 (신규).
- NXT 09:00:30 케이스: `now.second = 30` → "메인마켓" 전환 검증 (신규).
- KRX 09:00:00 케이스: "정규장" 유지 (초 단위 예외 없음 — KRX는 분 단위 유지).

#### `TestOnWsSubscribeStart` (기존 테스트 있는 경우)
- 실시간 필드 초기화 호출 제거 검증 — `_reset_realtime_fields` 직접 호출 대신 `_on_realtime_fields_reset()` 사전 실행 가정.
- 멱등성 가드: `last_ws_subscribe_start_date == today` 시 스킵 검증 (신규).

### 4-2. 신규 테스트: `TestOnRealtimeFieldsReset`

```python
class TestOnRealtimeFieldsReset:
    """_on_realtime_fields_reset() — 07:58 사전 트리거 실시간 필드 초기화 테스트."""

    async def test_resets_fields_and_sets_flag(self):
        # 실행 시 _reset_realtime_fields() 호출 + last_realtime_reset_date 설정

    async def test_skips_if_already_run_today(self):
        # last_realtime_reset_date == today 시 스킵 (멱등성)

    async def test_skips_on_weekend(self):
        # 주말 시 실행 안 함

    async def test_skips_on_non_trading_day(self):
        # 휴장일 시 실행 안 함

    async def test_skips_on_manual_mode(self):
        # ws_subscribe_on=False 시 스킵
```

### 4-3. 신규 테스트: `TestCheckPrestartTriggers`

```python
class TestCheckPrestartTriggers:
    """_check_prestart_triggers() — 07:58/07:59 사전 트리거 체크 테스트."""

    def test_triggers_fields_reset_at_0758(self):
        # 07:58 시각 + 미실행 → _on_realtime_fields_reset 트리거

    def test_triggers_ws_subscribe_at_0759(self):
        # 07:59 시각 + 미실행 → _on_ws_subscribe_start 트리거

    def test_skips_after_0800(self):
        # 08:00 이상 시 사전 트리거 없음 (phase 변경 감지가 담당)

    def test_skips_if_already_run(self):
        # 날짜 플래그 설정 시 중복 트리거 없음

    def test_skips_on_weekend(self):
        # 주말 시 트리거 없음
```

### 4-4. 신규 테스트: `TestOnWsSubscribeStartIdempotency`

```python
class TestOnWsSubscribeStartIdempotency:
    """_on_ws_subscribe_start() 멱등성 + 보완 경로 테스트."""

    async def test_skips_if_already_started_today(self):
        # last_ws_subscribe_start_date == today 시 스킵

    async def test_compensates_missing_fields_reset(self):
        # last_realtime_reset_date != today 시 필드 초기화 보완 실행

    async def test_skips_fields_reset_if_already_done(self):
        # last_realtime_reset_date == today 시 필드 초기화 보완 스킵
```

### 4-5. 검증 항목

| 항목 | 방법 |
|------|------|
| py_compile | `python -m py_compile daily_time_scheduler.py engine_state.py engine_cache.py` |
| ruff | `ruff check daily_time_scheduler.py engine_state.py engine_cache.py test_daily_time_scheduler.py` |
| pytest | `pytest test_daily_time_scheduler.py -v` (기존 테스트 수정 + 신규 테스트) |
| 런타임 기동 | `python -W error::RuntimeWarning main.py` — RuntimeWarning 0건, 사전 트리거 로그 확인 (07:58/07:59 시간대) |

---

## 5. 런타임 검증 방법

### 5-1. 기동 검증

```bash
cd backend && python -W error::RuntimeWarning main.py
```

확인 항목:
1. `[기동] 장 상태 계산 완료 | KRX: {상태}, NXT: {상태}` 로그 (기존)
2. `[기동] 장 상태 주기 태스크 시작 (10초 간격)` 로그 (3단계)
3. RuntimeWarning / Traceback 0건
4. 잔존 프로세스 0건

### 5-2. 사전 트리거 동작 확인 (장 시간대 — 07:58/07:59)

**07:58 도달 시**:
- `[작업실행] 실시간 필드 초기화 (사전 — 07:58)` 로그
- `[작업실행] 실시간 필드 초기화 완료 (사전)` 로그

**07:59 도달 시**:
- `[작업실행] WS 구독 시작` 로그
- `[작업실행] WS 구독 시작 완료 — 엔진 루프에 연결 통지` 로그

**08:00 도달 시** (phase 변경 감지):
- `[장상태] KRX: 장전 대기 → 장전 대기 | NXT: 장개시전 → 프리마켓` 로그
- WS 구독 시작 재트리거 → 멱등성 가드로 스킵 (`[작업실행] WS 구독 시작 스킵 (이미 실행됨)` DEBUG 로그)

### 5-3. NXT 메인마켓 09:00:30 전환 확인 (장 시간대)

- 09:00:00~09:00:29: NXT "정규장 준비" 유지 (10초 주기 태스크 로그)
- 09:00:30~09:00:40: NXT "메인마켓" 전환 — `[장상태] NXT: 정규장 준비 → 메인마켓` 로그
- JIF "21:장시작" 수신 시 즉시 전환 (1순위) — `[연결] JIF 수신: jangubun=6, jstatus=21` 로그 후 전환

### 5-4. JIF 런타임 검증 (별도 진행 — 장 시간대)

2단계 임시 INFO 로그 `[연결] JIF 수신: jangubun=%s, jstatus=%s`로 장 시작 시점 실제 push 코드 확인.
- **현재 장 마감 시간이라 런타임 JIF 검증 불가 — 다음 장 시간대에 별도 진행**.
- 맵핑 테이블과 불일치 시 별도 수정.

---

## 6. 승인 대기 항목

1. **4단계 구현 승인** (사용자 실행 지시어 대기 — 규칙 0).
2. **jstatus 52 표시 문구 수정**: 본 4단계에서 제외 (사용자 결정). 별도 세션에서 진행 — P23(용어 통일) 검토 포함.
3. **사전 트리거 시각 (07:58/07:59)**: 사용자 지정. 변경 필요 시 사용자 결정.
4. **NXT 메인마켓 시작 초 (30초)**: 사용자 보고 기반. 실제 NXT 스케줄 변경 시 상수 수정 필요.
5. **멱등성 가드 방식 (날짝 기반 플래그)**: 추천 방식. 다른 방식 원할 경우 사용자 결정.
6. **`_on_ws_subscribe_start()` 보완 경로**: 07:58 사전 실행 누락 시 WS 구독 시작 안에서 필드 초기화 보완 (P16 살아있는 경로). 보완 경로 제거 원할 경우 사용자 결정.

---

## 7. UI 기준 변경 설명 (규칙 0-4)

### 변경 전 (현재 화면)
- 08:00에 NXT "프리마켓" 진입 시 WS 구독 시작 + 실시간 필드 초기화 동시 실행.
- 08:00 NXT 프리마켓 체결 시작 시점에 WS가 아직 연결되지 않았을 수 있음 → 초기 틱 누락.
- NXT "메인마켓"이 09:00:00부터 표시 (실제 09:00:30 시작과 30초 불일치).

### 변경 후 (화면 변화)
- **07:58**: 전일 확정 데이터 제거 (화면 변화 없음 — 내부 데이터 초기화).
- **07:59**: WS 연결 시작 (화면 변화 없음 — 연결 준비). 08:00 NXT 프리마켓 체결 시작 시점에 WS 이미 연결 완료 → 초기 틱 누락 방지.
- **08:00**: NXT "프리마켓" 표시 시작 (기존과 동일 — phase는 실제 스케줄 유지).
- **09:00:30**: NXT "메인마켓" 표시 시작 (이전: 09:00:00 → 정확도 개선). 화면 장 상태 칩이 실제 NXT 스케줄과 일치.

### 사용자가 확인할 수 있는 영향
- 08:00 NXT 프리마켓 시작 시 체결 데이터 누락 감소 (WS 사전 연결).
- NXT 장 상태 표시가 실제 거래소 스케줄과 일치 (09:00:30 메인마켓 전환).
- 화면 장 상태 칩 변화 시점이 더 정확 (JIF 1순위 + 시간 기반 정밀 보완).
