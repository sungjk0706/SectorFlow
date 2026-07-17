# 태스크 파일: 타임테이블 DB 저장 방식 구현 (DB-backed Timetable)

> **상태**: 2세션(심층 사전조사 + 태스크 파일 작성) 완료 · 3세션(백엔드 Step 1) 승인 대기
> **작성일**: 2026-07-18
> **설계서**: `docs/architecture_db_timetable_design.md` (325줄)
> **관련 원칙**: P10(SSOT) · P13(설정 메모리 상주) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 0. 심층 사전조사 결과 (규칙 0-2 4항목 + 규칙 0-5)

> 설계서의 추상적 설계를 실제 코드의 라인 번호·의존성·삽입 지점으로 구체화.
> 모든 라인 번호는 본 세션 기준 (코드 수정 전).

### 0-1. settings_defaults.py — `DEFAULT_USER_SETTINGS` 삽입 위치

**파일**: `backend/app/core/settings_defaults.py`
**삽입 위치**: 라인 117 (`"order_time_guard_on": True,`) 다음, 닫는 `}` (라인 118) 이전.

```python
     # 체결 불가 시간대 주문 차단 (동시호가·장외 시간가 주문 자동 중단, 기본 ON)
     "order_time_guard_on": True,

     # 타임테이블 사용자 조정 시각 (장 시작 전 사전 준비 — P10 SSOT 기본값)
     # 거래소 고정 7개 시간(08:00~20:00)은 코드 상수로 daily_time_scheduler.py:21-49에 유지.
     "timetable.realtime_reset": "07:58",      # 실시간 항목 초기화
     "timetable.ws_prestart": "07:59",         # WS 구독 사전 시작
     "timetable.krx_pre_subscribe": "08:59",   # KRX 정규장 사전 구독
 }
```

**의존성**:
- `DEFAULT_SETTINGS` (라인 151-155)가 `**DEFAULT_USER_SETTINGS` 병합 → 자동 포함.
- `build_engine_settings_dict()` (engine_settings.py)가 `DEFAULT_SETTINGS` 기반 정규화 → 자동 전파.
- `app.py:82-95`의 `load_integrated_system_settings()` + `build_engine_settings_dict()` → 캐시 주입 시 자동 포함.

**영향 범위**: 백엔드 1개 파일. 기존 키 순서·값 변경 없음. 신규 3개 키 추가만.

### 0-2. settings_store.py — `_TIME_FIELDS` 확장 + `_validate_timetable_order()` 구현 세부

**파일**: `backend/app/core/settings_store.py`

#### (a) `_TIME_FIELDS` 확장 (라인 141-145)

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

기존 로직(라인 172-176)이 `_TIME_RE.match()` 실패 시 무시+경고 → 3개 키에도 동일 적용 (P23 일관성).

#### (b) `_validate_timetable_order()` 신규 함수

**위치**: `apply_settings_updates()` 함수(라인 136) **직전**에 모듀 레벨 함수로 추가. (또는 파일 끝 부분 helper 영역 — P24 단순성: 호출 근처 배치 선호)

**구현 세부**:
```python
_TIMETABLE_ORDER_KEYS = (
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
)

async def _validate_timetable_order(data: dict, before: dict) -> None:
    """3개 타임테이블 키의 시간 순서 검증 (P20/P22).

    검증 조건: realtime_reset ≤ ws_prestart ≤ krx_pre_subscribe < "09:00"
    - data: 이번 요청에서 변경하려는 키/값
    - before: load_selected_settings()로 로드한 기존 DB 값 (나머지 2개 키 보충용)

    실패 시 ValueError 발생 → apply_settings_updates 호출자가 HTTP 422로 변환 (기존 패턴).
    형식 오류(_TIME_RE 위반)는 이미 apply_settings_updates 상단에서 무시+경고 처리되므로
    본 함수에서는 형식 통과한 값만 순서 검증.
    """
    # 이번 요청에 3개 키 중 하나라도 포함 시에만 검증
    if not (set(data.keys()) & set(_TIMETABLE_ORDER_KEYS)):
        return

    # 3개 키의 최종값 산정: data 우선, 없으면 before, 없으면 DEFAULT_USER_SETTINGS
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS
    values: dict[str, str] = {}
    for k in _TIMETABLE_ORDER_KEYS:
        if k in data and data[k]:
            values[k] = str(data[k]).strip()
        elif k in before and before[k]:
            values[k] = str(before[k]).strip()
        else:
            values[k] = str(DEFAULT_USER_SETTINGS.get(k, "")).strip()

    # 3개 모두 값이 있어야 검증 (빈 값이면 기본값 폴백이 아니라 P20 위반 → ValueError)
    missing = [k for k in _TIMETABLE_ORDER_KEYS if not values.get(k)]
    if missing:
        raise ValueError(f"타임테이블 시각 누락: {missing} — 기본값 폴백 금지 (P20)")

    # 시간 순서 검증: realtime_reset ≤ ws_prestart ≤ krx_pre_subscribe < 09:00
    def _to_min(v: str) -> int:
        h, m = v.split(":")
        return int(h) * 60 + int(m)

    rt = _to_min(values["timetable.realtime_reset"])
    ws = _to_min(values["timetable.ws_prestart"])
    krx = _to_min(values["timetable.krx_pre_subscribe"])
    open_min = 9 * 60  # 09:00

    if not (rt <= ws <= krx < open_min):
        raise ValueError(
            f"타임테이블 시간 순서 오류: "
            f"실시간 초기화({values['timetable.realtime_reset']}) ≤ "
            f"구독 시작({values['timetable.ws_prestart']}) ≤ "
            f"정규장 사전 구독({values['timetable.krx_pre_subscribe']}) < 09:00 이어야 합니다"
        )
```

#### (c) `apply_settings_updates()` 내 호출 지점

**위치**: 라인 188 (`to_save[k] = v` / `after[k] = v` 완료 후), 라인 198 (`save_selected_settings(to_save)`) 호출 **직전**.

```python
    # ... 기존 루프 (155-187) 종료 후 ...

    # 타임테이블 시간 순서 검증 (P20/P22) — 저장 전 차단
    await _validate_timetable_order(data, before)

    # 증분 저장 (전체 설정 덮어쓰기 없이 변경된 필드만 저장)
    await save_selected_settings(to_save)
```

**이유**:
- `to_save`가 확정된 후 저장 직전에 검증 → 잘못된 값이 DB에 들어가는 것을 원천 차단 (P22).
- `before` (라인 149의 `load_selected_settings(select_keys)` 결과)를 인자로 전달 → DB에서 나머지 2개 키 보충.
- 단, `select_keys` (라인 148)에 3개 키가 포함되도록 확장 필요:
  ```python
  # 기존: select_keys = set(data.keys()) | {"broker"}
  # 변경: 타임테이블 키 중 하나라도 data에 있으면 3개 모두 select_keys에 추가
  if set(data.keys()) & set(_TIMETABLE_ORDER_KEYS):
      select_keys = set(data.keys()) | {"broker"} | set(_TIMETABLE_ORDER_KEYS)
  else:
      select_keys = set(data.keys()) | {"broker"}
  ```

**의존성**:
- `re` 모듈: 라인 139에서 이미 `import re` (함수 내 local import) → 재사용.
- `load_selected_settings`: 라인 10-15에서 이미 import → 재사용.
- `DEFAULT_USER_SETTINGS`: 신규 import 추가 (`from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS`) — 파일 상단(라인 9-16) import 영역에 추가.
- `routes/settings.py:84`가 `ValueError`를 HTTP 422로 변환 → 라우트 변경 불필요.

**영향 범위**: 백엔드 1개 파일. 라우트/엔진 변경 없음.

### 0-3. daily_time_scheduler.py — `_TIMETABLE` 제거 범위 + 빌더 함수 구현

**파일**: `backend/app/services/daily_time_scheduler.py`

#### (a) 제거 범위: 라인 951-962 (`_TIMETABLE: list[dict] = [...]`)

기존 10항목 정적 리스트를 제거. 항목 구성:
- 3개 direct (07:58/07:59/08:59) — 시각을 캐시에서 읽어 동적 생성
- 7개 phase (08:00/09:00/15:20/15:30/15:40/18:00/20:00) — 시각을 코드 상수에서 읽어 생성

#### (b) 빈 리스트 초기화 + 빌더 함수 추가

**위치**: 기존 라인 951 위치에 빈 리스트 + 빌더 함수 추가.

```python
# ── 타임테이블 스케줄러 (10초 루프 대체) ──────────────────────────────────────
# 시간표 항목: (시각 상수, 동작 종류, 콜백, 컨텍스트)
# - kind="direct": 시각 도달 시 callback 직접 실행 (사전 트리거)
# - kind="phase":  시각 도달 시 _broadcast_market_phase() 호출 (페이즈 재계산)
#
# P10 SSOT: 시간 상수는 기존 라인 21-49 재사용, 신규 상수 생성 없음.
# P24 단순성: 두 종류를 동일 리스트에서 kind 필드로 구분 (별도 리스트 분할 금지).
# P16 (살아있는 경로): _TIMETABLE은 기동 시 build_timetable_from_cache()로 채워짐.
#   빈 리스트 상태로 스케줄러 동작 금지 → start_daily_time_scheduler()에서 반드시 빌드 호출.
_TIMETABLE: list[dict] = []


def _parse_hm_tuple(v: str) -> tuple[int, int]:
    """HH:MM 문자열 → (h, m) 튜플. 형식 오류 시 ValueError (P20 폴백 금지)."""
    h, m = str(v).strip().split(":")
    return int(h), int(m)


def build_timetable_from_cache(settings: dict) -> list[dict]:
    """설정 캐시 기반으로 타임테이블 리스트 빌드 (P10 SSOT · P13 메모리 상주).

    인자: state.integrated_system_settings_cache 스냅샷
    반환: 기존 _TIMETABLE과 동일한 dict 리스트 10항목
          - 3개 direct: 시각을 캐시에서 읽음 (없으면 DEFAULT_USER_SETTINGS 기본값)
          - 7개 phase:  시각을 코드 상수(21-49)에서 읽음 (거래소 고정)

    P24 단순성: 함수 50줄 이하, 복잡도 O(n) n=10.
    P20 폴백 금지: 캐시에 키가 없으면 DEFAULT_USER_SETTINGS 기본값 (이것도 없으면 ValueError).
    """
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS

    def _cache_time(key: str, default_key: str) -> tuple[int, int]:
        v = settings.get(key) or DEFAULT_USER_SETTINGS.get(default_key)
        if not v:
            raise ValueError(f"타임테이블 시각 누락: {key} — 기본값 폴백 금지 (P20)")
        return _parse_hm_tuple(v)

    rt = _cache_time("timetable.realtime_reset", "timetable.realtime_reset")
    ws = _cache_time("timetable.ws_prestart", "timetable.ws_prestart")
    krx = _cache_time("timetable.krx_pre_subscribe", "timetable.krx_pre_subscribe")

    return [
        {"time": rt,   "kind": "direct", "action": _on_realtime_fields_reset, "ctx": f"실시간 필드 초기화 ({rt[0]:02d}:{rt[1]:02d})"},
        {"time": ws,   "kind": "direct", "action": _on_ws_subscribe_start,    "ctx": f"WS 구독 사전 시작 ({ws[0]:02d}:{ws[1]:02d})"},
        {"time": NXT_PREMARKET_START,         "kind": "phase",  "ctx": "NXT 프리마켓 진입 감지 (08:00)"},
        {"time": krx,  "kind": "direct", "action": _on_krx_pre_subscribe,     "ctx": f"KRX 사전 구독 ({krx[0]:02d}:{krx[1]:02d})"},
        {"time": KRX_REGULAR_START,           "kind": "phase",  "ctx": "KRX 정규장 진입 감지 (09:00)"},
        {"time": KRX_REGULAR_END,             "kind": "phase",  "ctx": "KRX 종가 동시호가 진입 감지 (15:20)"},
        {"time": KRX_CLOSING_AUCTION_END,     "kind": "phase",  "ctx": "KRX 체결 정산 전환 감지 (15:30)"},
        {"time": NXT_SINGLE_PRICE_END,        "kind": "phase",  "ctx": "NXT 애프터마켓 진입 감지 (15:40)"},
        {"time": NXT_AFTERMARKET_MID_END,     "kind": "phase",  "ctx": "NXT 애프터마켓 지속 전환 감지 (18:00)"},
        {"time": NXT_AFTERMARKET_END,         "kind": "phase",  "ctx": "NXT 장마감 진입 감지 (20:00)"},
    ]
```

#### (c) `_schedule_next_timetable_event()` (965-1011) 변경 여부

**변경 없음**. 전역 `_TIMETABLE`를 그대로 참조 (라인 988 `for entry in _TIMETABLE:`).
기동 시 빌드 후에는 전역 리스트가 채워져 있으므로 정상 동작.

#### (d) 익일 첫 이벤트 fallback (라인 999-1003)

```python
if next_entry is None or next_delay is None:
    # 오늘 남은 이벤트 없음 → 익일 첫 이벤트(07:58)까지 대기
    h, m = REALTIME_FIELDS_RESET_TIME  # ← 코드 상수 유지 (거래소 고정이 아닌 사용자 조정이지만 fallback은 상수 사용)
```

**검토**: 이 fallback은 "오늘 남은 이벤트 없음" 상황에서만 동작. 사용자가 07:58을 07:55로 변경해도, 빌드된 _TIMETABLE의 첫 항목 time은 07:55가 됨. 그러나 이 fallback 코드는 _TIMETABLE을 참조하지 않고 `REALTIME_FIELDS_RESET_TIME` 상수(07:58)를 직접 사용 → **불일치 가능성**.

**수정 필요**: fallback도 _TIMETABLE[0]["time"]을 참조하도록 변경:
```python
if next_entry is None or next_delay is None:
    # 오늘 남은 이벤트 없음 → 익일 첫 이벤트까지 대기
    first_time = _TIMETABLE[0]["time"] if _TIMETABLE else REALTIME_FIELDS_RESET_TIME
    h, m = first_time
    target = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)
    next_delay = (target - now).total_seconds()
    next_entry = {"time": first_time, "kind": "phase", "ctx": f"익일 첫 이벤트 ({h:02d}:{m:02d} 재스케줄)"}
```

**P16 주의**: `_TIMETABLE`이 빈 리스트일 때 `REALTIME_FIELDS_RESET_TIME` 상수로 fallback → 빈 리스트 상태는 기동 시 빌드 전에만 존재하므로 실제 동작하지 않음 (안전장치).

#### (e) 빌드 호출 배선 위치 — `start_daily_time_scheduler()` 내부

**파일**: 동일 `daily_time_scheduler.py`
**위치**: `start_daily_time_scheduler()` (라인 1434-1464) 내, 라인 1460 `await _timetable_startup_scan()` 호출 **직전**.

```python
async def start_daily_time_scheduler() -> None:
    """타임스케줄러를 시작하는 함수 — 이벤트 타이머 초기 예약."""
    try:
        # ── 기동 시 자동 ON/OFF 판별: 거래일+시간구간이면 ON, 아니면 OFF ──
        settings = state.integrated_system_settings_cache
        if not settings:
            raise RuntimeError("settings cache not initialized")
        await _apply_auto_toggle_on_startup(settings)

        # ── market_phase 시간 기반 초기화 (SSOT) ──
        phase = calc_timebased_market_phase()
        state.market_phase["krx"] = phase["krx"]
        state.market_phase["nxt"] = phase["nxt"]
        logger.info("[기동] 장 상태 계산 완료 | KRX: %s, NXT: %s", phase["krx"], phase["nxt"])

        # 기동 시 현재 장 상태 즉시 브로드캐스트 (WS 구독 창과 무관)
        _broadcast_market_phase()

        state.last_reset_date = _kst_now().strftime("%Y%m%d")

        await schedule_auto_trade_timers(settings)
        await schedule_ws_subscribe_timers(settings)
        schedule_midnight_timer()

        # ── 타임테이블 빌드 (DB 저장 시각 반영 — P10/P13/P16) ──
        # 기동 시 캐시 기반으로 _TIMETABLE 채움. 빈 리스트 상태로 스케줄러 동작 금지.
        global _TIMETABLE
        _TIMETABLE = build_timetable_from_cache(settings)
        logger.info("[기동] 타임테이블 빌드 완료 — %d항목", len(_TIMETABLE))

        # ── 타임테이블 스케줄러 기동 (10초 루프 대체 — 시간표 기반 보완) ──
        await _timetable_startup_scan()
        # ... (이하 기존 주석 유지)
    except Exception as e:
        logger.warning("[스케줄] 타이머 초기 예약 실패: %s", e)
```

**이유**:
- `engine_bootstrap.py`는 LOGIN 후 파이프라인만 담당 (부적합).
- `engine_config.py`의 `refresh_engine_integrated_system_settings_cache()`는 캐시 갱신만 담당 (타임테이블 빌드는 스케줄러 책임).
- `start_daily_time_scheduler()`가 `state.integrated_system_settings_cache` 접근 보장 (라인 1440) + 단일 기동 진입점 → 가장 깔끔.
- `app.py:131`에서 `await start_daily_time_scheduler()` 호출 → 자동 전파. app.py 변경 불필요.

**P16 확인**: 빌드 호출이 `start_daily_time_scheduler()` 실제 실행 경로에 연결. `app.py:131`에서 반드시 호출됨.

**의존성**:
- `_on_realtime_fields_reset` (라인 802), `_on_ws_subscribe_start` (라인 838), `_on_krx_pre_subscribe` (라인 559) — 기존 함수 재사용, 변경 없음.
- `NXT_PREMARKET_START` 등 7개 상수 (라인 21-49) — 기존 재사용.
- `DEFAULT_USER_SETTINGS` — 신규 import (함수 내 local import로 순환 import 방지).

**영향 범위**: 백엔드 1개 파일. 기존 함수/상수 변경 없음. _TIMETABLE 구조만 변경 (정적 리스트 → 빌더 함수).

### 0-4. engine_service.py — `_TIMETABLE_KEYS` 분기 삽입 위치

**파일**: `backend/app/services/engine_service.py`

#### (a) `_TIMETABLE_KEYS` 집합 정의 + 분기 삽입

**위치**: `_WS_SCHEDULE_KEYS` 분기(라인 126-147) 종료 직후, `_SECTOR_UI_KEYS` 정의(라인 149-168) 이전.

```python
    # WS 구독 시간/스케줄 변경 시 → 즉시 구간 재판정 + 타이머 재예약
    _WS_SCHEDULE_KEYS = {"confirmed_download_time", "scheduler_market_close_on"}
    if changed_keys & _WS_SCHEDULE_KEYS:
        # ... 기존 126-147 유지 ...
        except Exception:
            logger.warning("[설정] 실시간 구독 타이머 재예약 실패", exc_info=True)

    # 타임테이블 시각 변경 시 → _TIMETABLE 재빌드 + 타이머 재예약 (P14 단일 타이머 유지)
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
            import backend.app.services.daily_time_scheduler as _dts_mod
            _dts_mod._TIMETABLE = build_timetable_from_cache(state.integrated_system_settings_cache)
            _schedule_next_timetable_event()  # 기존 타이머 취소 후 재예약 (P14)
            logger.info("[설정] 타임테이블 변경 감지 — 재빌드 + 타이머 재예약 완료")
        except Exception:
            logger.warning("[설정] 타임테이블 재빌드/재예약 실패", exc_info=True)

    # 업종 정렬/필터 관련 설정 변경 시 업종 점수만 재계산 (종목 시세는 WS delta로만 전송)
    _SECTOR_UI_KEYS = {
        # ... 기존 150-168 유지 ...
```

#### (b) 모듈 전역 `_TIMETABLE` 재할당 방식

**검토**: 설계서는 `state._TIMETABLE = ...` 로 기술했으나, 실제 `_TIMETABLE`은 `daily_time_scheduler.py`의 **모듈 전역 변수** (state 필드 아님). 따라서:
- `import backend.app.services.daily_time_scheduler as _dts_mod` 후 `_dts_mod._TIMETABLE = ...` 로 재할당.
- 또는 `daily_time_scheduler.py`에 `set_timetable(new_list: list[dict]) -> None` setter 함수 추가 (P24 단순성: 1회용 래퍼 금지 → 직접 재할당 선호).

**채택**: 직접 재할당 방식 (`_dts_mod._TIMETABLE = ...`). 이유:
- `_schedule_next_timetable_event()`가 모듈 전역 `_TIMETABLE`을 참조하므로, 모듈 전역을 갱신해야 반영됨.
- setter 함수는 1회용 래퍼 (P24 위반).

#### (c) 엔진 미실행 시 처리

`routes/settings.py:44-49`가 엔진 미실행 시 `apply_settings_change()` 호출을 생략 → `_TIMETABLE_KEYS` 분기 미실행.
DB에만 저장 → 다음 기동 시 `start_daily_time_scheduler()`의 빌드 호출로 반영 (기존 패턴 준수).

#### (d) 검증 순서 보장

`apply_settings_updates()` 내 `_validate_timetable_order()`가 저장 전에 검증 → 잘못된 시각이 DB에 들어가지 않음.
따라서 `apply_settings_change()`의 재빌드 분기는 검증 통과한 값으로만 동작 (P22).

**의존성**:
- `state.integrated_system_settings_cache` — 라인 48의 `refresh_engine_integrated_system_settings_cache()` 호출로 갱신됨 → 최신값 보장.
- `build_timetable_from_cache`, `_schedule_next_timetable_event` — lazy import (순환 import 방지, 기존 패턴 준수).

**영향 범위**: 백엔드 1개 파일. 기존 분기 패턴 재사용.

### 0-5. 프론트엔드 general-settings.ts — 입력칸 패턴 재사용 지점

**파일**: `frontend/src/pages/general-settings.ts`

#### (a) 재사용 가능 공통 자산 (P23)

- `createTimeSlot(hour, minute, onChange)` — `frontend/src/components/common/settings-common.ts:70`
  - 단일 시간 입력칸 (드롭다운 선택 UI)
  - `confirmed_download_time` 행 (general-settings.ts:590)이 동일 패턴 사용
- `parseHM(v)` — `settings-common.ts:14`
- `updateTimeSlotDisplay(slot, h, m)` — `settings-common.ts:112`
- `createToggleBtn`, `createDescText`, `sectionTitle`, `setDisabled` — 기존 general-settings.ts 내 함수
- `settingsMgr.saveSection(dirty)` + `toastResult(res)` — 기존 저장 플로우

→ **신규 컴포넌트 생성 불필요**. `createTimeSlot` 3개 인스턴스 생성으로 충족 (P24).

#### (b) 카드 삽입 위치

**위치**: `renderAutoTradeTab()` 함수(라인 158-289) 내, 라인 288 (`createDescText('동시호가·장외 시간대...')`) 다음, 닫는 `}` (라인 289) 이전.

**이유**:
- "자동매매" 탭의 시간 설정 행(buy_time/sell_time/order_time_guard) 아래 → 시간 설정 관련 자연스러운 그룹핑.
- "1일봉차트 자동다운로드" 행(580-616)은 별도 탭/섹션 → 분리 대상 아님.

#### (c) 카드 구조 (UI 기준 설명 — 규칙 0-4)

```
[자동매매 탭]
  ├─ 자동매매 (마스터 토글)
  ├─ 자동매수 (시간 쌍 + 토글)
  ├─ 자동매도 (시간 쌍 + 토글)
  ├─ 체결 불가 시간대 주문 차단 (토글)
  └─ [신규] 장 시작 전 사전 준비 시간
      설명: "장 시작 전 사전 준비 시간을 설정합니다. 너무 늦으면 실시간 데이터가 누락될 수 있습니다."
      ├─ 실시간 항목 초기화 시간: [07:58 ▼]  (기본 07:58)
      │   설명: "장 시작 1분 전에 실시간 데이터 수신을 시작합니다"
      ├─ 구독 사전 시작 시간:      [07:59 ▼]  (기본 07:59)
      │   설명: "실시간 항목 초기화 직후 WS 구독을 사전 시작합니다"
      ├─ 정규장 사전 구독 시간:    [08:59 ▼]  (기본 08:59)
      │   설명: "정규장 시작 1분 전에 KRX 종목을 사전 구독합니다"
      └─ [참고: 거래소 고정 시간 (변경 불가)] 접이식 영역
          • 08:00 NXT 프리마켓 시작
          • 09:00 정규장 시작
          • 15:20 정규장 종료
          • 15:30 종가 동시호가 종료
          • 15:40 NXT 애프터마켓 시작
          • 18:00 애프터마켓 지속 전환
          • 20:00 장마감
```

#### (d) 저장 플로우

각 입력칸 변경 시 `settingsMgr.saveSection({ "timetable.realtime_reset": "07:55" })` 호출 → 기존 `confirmed_download_time` 저장 패턴(102-118) 재사용.
422 응답 시 `toastResult(res)`가 기존 에러 토스트 표시 (P21).

#### (e) 상태 동기화

`syncFromSettings()` (기존 함수)에 3개 키 값 반영 → `vals["timetable.realtime_reset"]` 등.
`settingsMgr.getSettings()`가 백엔드 PATCH 응답 후 갱신 → 자동 반영.

**의존성**:
- `createTimeSlot` import — 기존 (general-settings.ts 상단 import 영역).
- `vals` 객체 — 기존 모듈 전역.
- `settingsMgr` — 기존 모듈 전역.

**영향 범위**: 프론트엔드 1개 파일. 신규 컴포넌트 생성 없음.

### 0-6. 테스트 파일 갱신 지점

#### (a) `backend/tests/test_daily_time_scheduler.py`

**import 갱신** (라인 29-83):
- 라인 77: `_TIMETABLE,` → `build_timetable_from_cache,` + `_TIMETABLE,` 유지 (빈 리스트 초기화이므로 테스트용 빌더 호출 필요)
- 신규 import: `build_timetable_from_cache`

**테스트 케이스 갱신**:
- 라인 2146: `entry = next(e for e in _TIMETABLE if e["ctx"].startswith("실시간 필드 초기화"))` → 빌더 호출로 변경:
  ```python
  _tt = build_timetable_from_cache({
      "timetable.realtime_reset": "07:58",
      "timetable.ws_prestart": "07:59",
      "timetable.krx_pre_subscribe": "08:59",
  })
  entry = next(e for e in _tt if e["ctx"].startswith("실시간 필드 초기화"))
  ```
- 기타 _TIMETABLE 직접 참조 테스트: 동일 패턴으로 빌더 호출로 변경.

**신규 테스트 케이스** (TestBuildTimetableFromCache 클래스):
- `test_default_values`: 기본 캐시 → 10항목, 3개 direct 시각 07:58/07:59/08:59
- `test_custom_values`: 사용자 조정 시각 → 3개 direct 시각 반영
- `test_missing_key_uses_default`: 캐시에 일부 키 누락 → DEFAULT_USER_SETTINGS 기본값
- `test_all_missing_raises`: 캐시+기본값 모두 누락 → ValueError (P20)
- `test_invalid_format_raises`: "07:99" 등 → ValueError
- `test_phase_entries_use_code_constants`: 7개 phase 항목 시각 = 코드 상수
- `test_order_preserved`: 반환 리스트 순서 = 기존 _TIMETABLE 순서

#### (b) `backend/tests/test_settings_store.py`

**신규 테스트 클래스** (TestValidateTimetableOrder):
- `test_valid_order`: 07:58 ≤ 07:59 ≤ 08:59 < 09:00 → 통과
- `test_equal_values`: 07:58 = 07:58 = 07:58 → 통과 (≤ 조건)
- `test_reverse_order`: 08:59, 07:59, 07:58 → ValueError
- `test_krx_at_open`: 08:59 = 09:00 → ValueError (< 09:00 엄격)
- `test_krx_after_open`: 09:30 → ValueError
- `test_missing_in_data_uses_before`: data에 1개만, before에 나머지 2개 → 통과
- `test_missing_everywhere_raises`: data/before/DEFAULT 모두 누락 → ValueError
- `test_no_timetable_keys_skipped`: data에 일반 키만 → 검증 생략 (통과)

**TestApplySettingsUpdates 갱신**:
- `test_timetable_order_violation_raises`: `apply_settings_updates({"timetable.ws_prestart": "09:30"})` → ValueError
- `test_timetable_order_valid_saves`: 정상 시각 → 저장 호출 확인

#### (c) `backend/tests/test_engine_settings.py` (또는 test_engine_service.py)

**신규 통합 테스트**:
- `test_apply_settings_change_timetable_rebuild`: 3개 키 변경 시 `_TIMETABLE` 재빌드 + `_schedule_next_timetable_event()` 호출 확인 (mock 기반)

---

## 1. 다단계 작업 분할 (세션당 1단계, 규칙 0-1)

> 설계서 8절의 6세션 분할을 본 태스크 파일에서 확정. 각 Step은 별도 세션에서 진행.

| Step | 세션 | 내용 | 파일 | 검증 |
|---|---|---|---|---|
| 1 | 백엔드 3세션 | `settings_defaults.py` 3개 키 추가 + `settings_store.py` `_TIME_FIELDS` 확장 + `_validate_timetable_order()` + `apply_settings_updates()` 배선 | 2개 파일 | 단위 테스트 (정상/순서 위반/형식 오류) + 기존 테스트 회귀 |
| 2 | 백엔드 4세션 | `daily_time_scheduler.py` 빌더 함수 + `_TIMETABLE` 빈 리스트 + `_schedule_next_timetable_event()` fallback 갱신 + `start_daily_time_scheduler()` 빌드 배선 | 1개 파일 | 단위 테스트 (빌더) + 런타임 기동 확인 + 기존 테스트 갱신 |
| 3 | 백엔드 5세션 | `engine_service.py` `_TIMETABLE_KEYS` 분기 + 재빌드/재예약 배선 | 1개 파일 | 통합 테스트 (저장→재빌드→재예약) + 런타임 확인 |
| 4 | 프론트엔드 6세션 | `general-settings.ts` "장 시작 전 사전 준비 시간" 카드 + 입력칸 3개 + 거래소 고정 시간 참고 표시 | 1개 파일 | 빌드 + 브라우저 확인 |
| 5 | 프론트엔드 7세션 | 검증 에러 표시 + 저장 플로우 연결 (422 응답 시 에러 토스트) | 동일 파일 | 빌드 + 브라우저 확인 (422 시 에러 토스트) |
| 6 | 테스트 8세션 | 기존 테스트 갱신 + 신규 테스트 보강 (빌더/검증/통합) | 3개 테스트 파일 | 전체 테스트 통과 + 런타임 기동 |

**총 6세션** (설계서 8절과 일치). 각 세션 종료 시 커밋 + `HANDOVER.md` 갱신.

---

## 2. Step 1 상세 (백엔드 3세션 — 다음 세션)

> 본 세션(2세션)은 태스크 파일 작성까지. Step 1 구현은 3세션에서 승인 후 진행.

### 2-1. 수정 파일 (2개)

1. `backend/app/core/settings_defaults.py`
   - 라인 117 다음에 3개 키 + 섹션 주석 추가 (0-1절 참조)

2. `backend/app/core/settings_store.py`
   - 상단 import 영역에 `from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS` 추가
   - `_TIME_FIELDS` (라인 141-145)에 3개 키 추가
   - `_TIMETABLE_ORDER_KEYS` 상수 + `_validate_timetable_order()` 함수 추가 (0-2절 참조)
   - `apply_settings_updates()` 내:
     - 라인 148 `select_keys` 확장 (타임테이블 키 중 하나라도 있으면 3개 모두 추가)
     - 라인 198 `save_selected_settings(to_save)` 직전에 `await _validate_timetable_order(data, before)` 호출

### 2-2. 사전조사 결과 (규칙 0-2 4항목)

1. **의존성**:
   - `DEFAULT_USER_SETTINGS` → `DEFAULT_SETTINGS` (settings_defaults.py:151) → `build_engine_settings_dict()` → `app.py:93` 캐시 주입. 자동 전파.
   - `_TIME_FIELDS` → `apply_settings_updates()` 라인 172에서만 참조. 다른 참조 없음.
   - `_validate_timetable_order()` → 신규 함수, `apply_settings_updates()`에서만 호출.
   - `load_selected_settings` → 이미 import (라인 10-15).
   - `routes/settings.py:84`가 `ValueError` → HTTP 422 변환. 라우트 변경 불필요.

2. **영향 범위**: 백엔드 2개 파일. 프론트엔드/테스트/DB 스키마 변경 없음.

3. **아키텍처 원칙 부합**:
   - P10 (SSOT): 기본값이 `DEFAULT_USER_SETTINGS`에 단일화.
   - P13 (설정 메모리 상주): 검증은 `before` (DB 로드값) + `data` (요청값) + `DEFAULT_USER_SETTINGS` 만으로 수행. 틱 연산 단계 DB 조회 없음.
   - P16 (살아있는 경로): `_validate_timetable_order()`가 `apply_settings_updates()` 실제 경로에 연결.
   - P20 (폴백 금지): 누락 시 ValueError (빈 문자열/None 폴백 금지).
   - P22 (데이터 정합성): 순서 위반 시 즉시 차단.
   - P23 (일관성): 기존 `_TIME_FIELDS`/`_TIME_RE`/`ValueError` 패턴 재사용.
   - P24 (단순성): 함수 30줄 이하, 복잡도 O(1).

4. **기존 공통 자산 확인**:
   - `_TIME_FIELDS`, `_TIME_RE`, `load_selected_settings`, `ValueError` → HTTP 422 패턴 모두 기존 재사용.
   - 신규 자산 생성 없음.

### 2-3. 검증 계획

1. `python -m py_compile backend/app/core/settings_defaults.py backend/app/core/settings_store.py`
2. `ruff check backend/app/core/settings_defaults.py backend/app/core/settings_store.py`
3. `pytest backend/tests/test_settings_store.py -v` (신규 테스트 케이스 + 기존 회귀)
4. `pytest backend/tests/ -x` (전체 회귀 — Step 1은 기존 기능 변경 없으므로 전체 통과 예상)
5. 런타임 기동: `python -W error::RuntimeWarning main.py` → RuntimeWarning 0건 + 에러 없음 + `[기동]` 로그 정상

### 2-4. 커밋 메시지

```
feat: 타임테이블 DB 저장 3세션 — 설정 키 3개 + 시간 순서 검증 (Step 1)

- settings_defaults.py: DEFAULT_USER_SETTINGS에 timetable.* 3개 키 추가
  (realtime_reset 07:58 / ws_prestart 07:59 / krx_pre_subscribe 08:59)
- settings_store.py: _TIME_FIELDS에 3개 키 확장 + _validate_timetable_order() 신규
  검증 조건: realtime_reset ≤ ws_prestart ≤ krx_pre_subscribe < 09:00
  위반 시 ValueError → routes/settings.py에서 HTTP 422 변환 (기존 패턴)
- apply_settings_updates()에 검증 배선 (save_selected_settings 직전)

P10/P13/P16/P20/P22/P23/P24 부합. 거래소 고정 7개 시간은 코드 상수 유지.

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

---

## 3. 위험 및 완화 (설계서 9절 + 본 조사 구체화)

| 위험 | 완화 | 조사 결과 |
|---|---|---|
| 사용자가 09:30 등 장 후 시간 입력 → 구독 누락 구간 | `_validate_timetable_order()`에서 `krx_pre_subscribe < "09:00"` 강제 (P22) | routes/settings.py:84가 자동 422 변환 |
| 빌더 함수 호출 누락 → 빈 `_TIMETABLE`로 스케줄러 무동작 | `start_daily_time_scheduler()` 내 빌드 호출 배선 (P16) | app.py:131에서 반드시 호출됨 |
| 캐시와 DB 불일치 → 잘못된 시각으로 스케줄 | `refresh_engine_integrated_system_settings_cache()` 선행 후 빌드 (기존 패턴) | engine_service.py:48에서 이미 갱신 |
| 기존 `_TIMETABLE` 직접 참조 테스트 깨짐 | Step 2에서 테스트 동시 갱신 (규칙 4-1) | test_daily_time_scheduler.py:77, 2146 갱신 필요 |
| 동시 저장 시 경쟁 | 기존 `get_db_lock()` + 트랜잭션으로 보호 | settings_file.py 기존 패턴 |
| `_schedule_next_timetable_event()` fallback 불일치 | Step 2에서 fallback도 `_TIMETABLE[0]["time"]` 참조로 변경 | 0-3절 (d) 항목 |
| 모듈 전역 `_TIMETABLE` 재할당 경쟁 | `_TIMETABLE_KEYS` 분기는 단일 await 경로 (apply_settings_change) | engine_service.py:30 단일 진입점 |

---

## 4. 규칙 0-5 사전 통지 (사용자 설계 로직 변경)

본 태스크는 기존 `_TIMETABLE` 파이썬 리스트(사용자가 이전에 설계·승인한 구조)를 **빌더 함수 기반으로 변경**하는 것을 포함:

- **변경 사유**: DB 저장값을 반영하려면 기동 시·저장 시 동적으로 리스트를 빌드해야 함. 정적 리스트는 DB 값 반영 불가.
- **영향 범위**:
  - `_TIMETABLE` 참조 코드: `_schedule_next_timetable_event()` (988), 테스트 (2146) — 변경 최소화.
  - 리스트 빌드 방식만 변경. 항목 구조(dict 키: time/kind/action/ctx)는 동일.
  - `_schedule_next_timetable_event()` fallback (999-1003)도 `_TIMETABLE[0]["time"]` 참조로 변경.
- **대안 검토**:
  - (A) 빌더 함수 방식 (본 설계 채택) — P13 준수 (메모리 캐시 기반).
  - (B) `_TIMETABLE`를 매번 DB 조회하여 빌드 — P13 위반 (스케줄 연산 단계 DB 조회).
  - (C) `_TIMETABLE`를 state 필드로 이동 — state 필드 증가, P24 위반 (불필요한 추상화).
- **승인 필요**: 본 태스크 파일 전체 승인 시 `_TIMETABLE` 구조 변경도 함께 승인된 것으로 간주.

---

## 5. 승인 대기 항목

본 태스크 파일은 **2세션(심층 사전조사 + 태스크 파일 작성) 완료·3세션(Step 1 구현) 승인 대기** 상태.

사용자의 명시적 실행 지시어("진행해", "구현해", "go" 등)가 있으면 Step 1부터 세션당 1단계로 진행.

---

## 6. 참조

- 설계서: `docs/architecture_db_timetable_design.md` (325줄)
- 기존 타임테이블 구현: `backend/app/services/daily_time_scheduler.py:944-1041`
- 기존 설정 저장 API: `backend/app/core/settings_store.py:136-213`
- 기존 설정 변경 동기화: `backend/app/services/engine_service.py:30-217`
- 기존 설정 라우트: `backend/app/web/routes/settings.py:26-86`
- 기존 설정 기본값: `backend/app/core/settings_defaults.py:10-118`
- 기존 시간 입력 컴포넌트: `frontend/src/components/common/settings-common.ts:70` (`createTimeSlot`)
- 기존 단일 시간 입력 사용 예: `frontend/src/pages/general-settings.ts:590` (`confirmed_download_time`)
- 유사 설계서: `docs/architecture_order_time_guard_design.md` (시간대 게이트 — 동일 패턴)
