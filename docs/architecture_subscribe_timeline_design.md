# 구독/해지 타임라인 재설계 아키텍처 설계 (2026-07-17)

> **상태**: 설계 완료. 코드 수정 전 사용자 승인 대기.
> **관련 문서**: `docs/subscribe_timeline_investigation.md` (심층 조사 보고서 — 타임라인 전체 흐름, "웹소켓 연결" API 명세서 존재 여부, 수정 방향)
> **관련 원칙**: P10(SSOT), P16(살아있는 경로), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(일관성), P24(단순성)

---

## 1. 배경

SectorFlow의 실시간 구독/해지 타임라인은 현재 다음 흐름으로 동작:

| 시각 | 동작 | 트리거 |
|------|------|--------|
| 07:58 | 실시간 필드 초기화 | `_check_prestart_triggers()` |
| 07:59 | GC 비활성화 + 캐시 초기화 (사전 준비) | `_check_prestart_triggers()` |
| 08:00 | WS 연결 + NXT 구독 신청 | `_apply_market_phase()` (NXT "프리마켓" 진입) |
| 09:00 | KRX 단독 종목 추가 구독 | `_apply_market_phase()` (KRX "정규장" 진입) |
| 15:30 | KRX 단독 종목 구독 해지 | `_apply_market_phase()` (KRX "체결 정산" 진입) |
| 20:00 | 전체 구독 해지 + WS 연결 해제 | `_apply_market_phase()` (NXT "장마감" 진입) |

사용자 제안 4개 변경안을 심층 조사(`docs/subscribe_timeline_investigation.md`)를 통해 기술적 가능성을 확인했으며, 본 설계서는 구현 방안을 정의한다.

### 1.1 프로젝트 핵심 특성 (재설계 전제)

1. **시장가 체결만 사용** — 지정가 없음. 동시호가 구간(08:40~09:00, 15:20~15:30)은 시장가 체결 불가 → 구독 유지 불필요.
2. **종가 데이터** — 20:40 확정시세 다운로드로 수신. 실시간 종가 수신 불필요.
3. **"웹소켓 연결"** — 증권사 API가 아닌 표준 WebSocket 프로토콜(`websockets.connect()`). `connect()`/`disconnect()`는 API 명세상 필수 단계 캡슐화 → 단순화 대상 아님.

---

## 2. 확정된 4개 변경안

| # | 시각 | 제안 동작 | 현재 대비 변경 |
|---|------|-----------|-----------------|
| 1 | 07:58 | 필드 초기화 + GC 비활성화 + 캐시 초기화 | GC/캐시를 07:59에서 07:58로 이동 통합 |
| 2 | 07:59 | WS 연결 + LOGIN + NXT 구독 신청 | 신규: 08:00에서 07:59로 사전 구간 확장 |
| 3 | 08:59 | KRX 단독 종목 추가 구독 신청 | 신규: 09:00에서 08:59로 사전 트리거 추가 |
| 4 | 15:20 | KRX 단독 종목 구독 해지 | 변경: 15:30에서 15:20으로 이동 |

### 2.1 변경 후 타임라인

| 시각 | 동작 | 트리거 | 핵심 함수 |
|------|------|--------|-----------|
| 07:58 | 필드 초기화 + GC 비활성화 + 캐시 초기화 | `_check_prestart_triggers()` | `_on_realtime_fields_reset()` (확장) |
| 07:59 | WS 구독 구간 진입 (상태 전환 + 엔진 루프 통지) | `_check_prestart_triggers()` | `_on_ws_subscribe_start()` (축소) |
| 08:00 | NXT 프리마켓 진입 (이미 구독됨 — 재계산만) | `_apply_market_phase()` | `_on_nxt_premarket_start()` (변경 없음) |
| 08:59 | KRX 단독 종목 사전 구독 | `_check_prestart_triggers()` | `_on_krx_pre_subscribe()` (신규) |
| 09:00 | KRX 정규장 진입 (재계산 — 구독은 멱등 스킵) | `_apply_market_phase()` | `_on_krx_market_open()` (변경 없음) |
| 15:20 | KRX 단독 종목 구독 해지 + 재계산 | `_apply_market_phase()` | `_on_krx_closing_auction_start()` (이동·개명) |
| 15:30 | 체결 정산 진입 (부작용 없음) | `_apply_market_phase()` | (트리거 제거) |
| 20:00 | 전체 구독 해지 + WS 연결 해제 | `_apply_market_phase()` | `_on_ws_subscribe_end()` (변경 없음) |

---

## 3. 설계안 비교표

### 3.1 Change 2 — `is_ws_subscribe_window()` 사전 구간 추가

| 항목 | 안 A (시간 기반 판정) | **안 B (플래그 기반)** | 안 C (새 phase 추가) |
|---|---|---|---|
| **방식** | 07:59~08:00 시간 범위 체크 | `ws_subscribe_window_active` 플래그 OR 조건 | `calc_timebased_market_phase()`에 "사전 구독" phase 추가 |
| **재시작 대응** | **가능** (시간 기반이므로 플래그 무관) | 불가 (플래그는 메모리 → 재시작 시 False) | 가능 (phase가 영속적) |
| **P10 (SSOT)** | 부분 (시간 상수 재사용) | 준수 (플래그가 SSOT) | **준수** (phase가 SSOT) |
| **P24 (단순성)** | **단순** (조건 1개 추가) | 단순 (조건 1개 추가) | 복잡 (phase 계산 + 모든 소비자 영향) |
| **영향 범위** | `is_ws_subscribe_window()` 1곳 | `is_ws_subscribe_window()` 1곳 | `calc_timebased_market_phase()` + JIF 맵 + 카운트다운 + 프론트엔드 |
| **선택** | **선택** | 미선택 (재시작 시 사전 구간 누락) | 미선택 (과잉 영향) |

**안 A 선택 근거**: 재시작 시에도 사전 구간이 동작해야 함(P16 살아있는 경로). `ws_subscribe_window_active` 플래그는 메모리 상주 → 재시작 시 False → 안 B는 재시작 시 07:59 사전 구간 누락. 안 C는 모든 phase 소비자에게 영향을 주어 P24 위반. 안 A는 기존 시간 상수(`WS_SUBSCRIBE_PRESTART_TIME`, `NXT_PREMARKET_START`)를 재사용하여 단일 함수 내 조건 1개 추가로 해결.

### 3.2 Change 1 — 07:58 데이터 준비 통합

| 항목 | **안 A (기존 함수 확장)** | 안 B (신규 함수 분리) |
|---|---|---|
| **방식** | `_on_realtime_fields_reset()`에 GC + 캐시 초기화 추가 | 새 함수 `_on_prestart_data_prepare()` 생성 |
| **함수 수** | 변경 없음 (기존 1개 확장) | 증가 (신규 1개 + 기존 1개) |
| **P23 (일관성)** | 준수 (07:58 = 데이터 준비 단일 함수) | 준수 (역할 분리) |
| **P24 (단순성)** | **단순** (함수 수 증가 없음) | 함수 증가 |
| **보완 로직** | `_on_ws_subscribe_start()` 내 보완이 단일 호출로 해결 | 보완 시 2개 함수 호출 필요 |
| **선택** | **선택** | 미선택 (함수 증가, 보완 복잡) |

**안 A 선택 근거**: 07:58은 "데이터 준비" 단일 책임으로 통합하는 것이 P24(단순성)에 부합. `_on_realtime_fields_reset()`의 멱등성 가드(`last_realtime_reset_date`)가 GC + 캐시 초기화까지 함께 보호. `_on_ws_subscribe_start()`의 보완 로직도 `_on_realtime_fields_reset()` 1회 호출로 해결.

### 3.3 Change 4 — 15:20 KRX 해지 트리거 이동

| 항목 | **안 A (함수 개명 + 트리거 이동)** | 안 B (기존 함수 유지 + 조건만 변경) |
|---|---|---|
| **방식** | `_on_krx_after_hours_start()` → `_on_krx_closing_auction_start()` 개명 + 트리거 15:20 변경 | 함수명 유지 + 트리거 조건만 "체결 정산" → "종가 동시호가" 변경 |
| **P23 (일관성)** | **준수** (함수명이 동작 시점과 일치) | 위반 (함수명 "after_hours"이지만 15:20 동작) |
| **Code Removal Rules** | 참조 전체 갱신 필요 (docstring, 주석, 테스트) | 참조 갱신 불필요 |
| **선택** | **선택** | 미선택 (명칭-동작 불일치 P23 위반) |

**안 A 선택 근거**: 함수명이 동작 시점(15:20 종가 동시호가)과 일치해야 함(P23). 개명 시 Code Removal Rules에 따라 모든 참조(docstring, 주석, 테스트)를 갱신.

---

## 4. 선택안 동작 원리

### 4.1 Change 1 — 07:58 데이터 준비 통합

#### 현재 구조
- 07:58 `_on_realtime_fields_reset()`: 실시간 필드 초기화만 (`_reset_realtime_fields()`)
- 07:59 `_on_ws_subscribe_start()`: GC 비활성화 + 수신율 게이트 리셋 + 캐시 초기화 + 필드 초기화 보완 + WS 상태 전환 + 엔진 루프 통지

#### 변경 후 구조
- **07:58 `_on_realtime_fields_reset()` (확장)**: 실시간 필드 초기화 + GC 비활성화 + 수신율 게이트 리셋 + 캐시 초기화
  - 멱등성 가드: `last_realtime_reset_date == today_str` (기존 가드가 GC + 캐시까지 포함)
  - 거래일 체크 후 실행 (기존과 동일 — 주말/공휴일 시 GC 비활성화 생략 = 현재 동작 개선)
- **07:59 `_on_ws_subscribe_start()` (축소)**: WS 구독 상태 전환 + 엔진 루프 통지
  - `state.ws_subscribe_window_active = True`
  - `state.last_ws_subscribe_start_date = today_str`
  - `_broadcast_market_phase()`
  - `state.ws_window_changed_event.set()`
  - 보완: `last_realtime_reset_date != today_str` 시 `_on_realtime_fields_reset()` 1회 호출 (07:58 누락 시 전체 데이터 준비 보완)

#### 동작 개선: 주말 GC 비활성화 제거
현재 `_on_ws_subscribe_start()`는 거래일 체크 **이전**에 `gc.disable()`를 실행 → 주말에도 GC 비활성화. 변경 후 `_on_realtime_fields_reset()`는 거래일 체크 **이후**에 `gc.disable()` → 주말 GC 비활성화 생략. 주말에 `_on_ws_subscribe_end()`가 미실행될 수 있어 GC가 장기간 비활성화되는 잠재적 문제를 제거.

### 4.2 Change 2 — `is_ws_subscribe_window()` 사전 구간 추가

#### 공통 헬퍼 함수 (P23 공통 자산 재사용)
```python
def _is_pre_subscribe_window() -> bool:
    """07:59~08:00 사전 구독 구간 여부 (시간 기반 — 재시작 대응).

    WS_SUBSCRIBE_PRESTART_TIME(07:59) ~ NXT_PREMARKET_START(08:00) 사이.
    휴장일은 calc_timebased_market_phase()가 "휴장일"로 산정하므로 자동 차단.
    """
    now = _kst_now()
    t = now.hour * 60 + now.minute
    prestart_t = WS_SUBSCRIBE_PRESTART_TIME[0] * 60 + WS_SUBSCRIBE_PRESTART_TIME[1]
    market_t = NXT_PREMARKET_START[0] * 60 + NXT_PREMARKET_START[1]
    if not (prestart_t <= t < market_t):
        return False
    mp = state.market_phase
    if mp.get("nxt") == "휴장일" or mp.get("krx") == "휴장일":
        return False
    return True
```

#### `is_ws_subscribe_window()` 수정
```python
async def is_ws_subscribe_window(settings=None) -> bool:
    # ... settings 체크 (기존) ...
    mp = state.market_phase
    nxt = mp.get("nxt", "")
    if not nxt:
        return False
    if nxt in NXT_ACTIVE_PHASES:
        return True
    # 사전 구독 구간 (07:59~08:00) — 시간 기반 판정 (재시작 대응, P16)
    return _is_pre_subscribe_window()
```

#### `is_nxt_only_window()` 수정
```python
def is_nxt_only_window() -> bool:
    mp = state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        return False
    if krx in KRX_INACTIVE_PHASES and nxt in NXT_ACTIVE_PHASES:
        return True
    # 사전 구독 구간 (07:59~08:00) — NXT-only 구독 (KRX 단독 종목 제외)
    if _is_pre_subscribe_window() and krx in KRX_INACTIVE_PHASES:
        return True
    return False
```

07:59 시점: krx="장개시전"(KRX_INACTIVE), nxt="장개시전"(NXT_ACTIVE 아님) → 기존 조건 False. `_is_pre_subscribe_window()=True` + `krx in KRX_INACTIVE_PHASES=True` → True. NXT 구독 시 KRX 단독 종목 제외.

#### 재시작 시 동작
`_init_ws_subscribe_state()`가 `is_ws_subscribe_window()` 호출 → 07:59:30 재시작 시 시간 기반 판정으로 True 반환 → `ws_subscribe_window_active = True` 설정 + GC 비활성화 + 캐시 초기화 + 엔진 루프 통지. 사전 구간 내 재시작도 정상 동작 (P16 살아있는 경로).

### 4.3 Change 3 — 08:59 KRX 사전 구독

#### 신규 상수
```python
KRX_PRE_SUBSCRIBE_TIME = (8, 59)   # 08:59 KRX 사전 구독 (정규장 1분 전)
```

#### `_check_prestart_triggers()` 확장
현재 07:58/07:59 사전 트리거만 처리 → 08:59 KRX 사전 구독 트리거 추가:
```python
# 08:59 이상 ~ 09:00 미만 — KRX 사전 구독 트리거
krx_pre_t = KRX_PRE_SUBSCRIBE_TIME[0] * 60 + KRX_PRE_SUBSCRIBE_TIME[1]   # 539
krx_market_t = KRX_REGULAR_START[0] * 60 + KRX_REGULAR_START[1]           # 540
if krx_pre_t <= t < krx_market_t and state.last_krx_pre_subscribe_date != today_str:
    schedule_engine_task(_on_krx_pre_subscribe(), context="KRX 사전 구독 (08:59)")
```

#### 신규 함수 `_on_krx_pre_subscribe()`
- KRX 단독 종목 구독만 수행 (`subscribe_sector_stocks_0b()` — `_subscribed` 플래그 기반 멱등성)
- 재계산 미수행 (KRX 정규장 진입 전이므로 업종 점수에 KRX 단독 종목 포함 불필요)
- 멱등성 가드: `last_krx_pre_subscribe_date == today_str`
- 거래일 체크 포함

#### 09:00 `_on_krx_market_open()` 동작
- 재계산 수행 (기존 — KRX 단독 종목 포함 업종 점수 재계산)
- `subscribe_sector_stocks_0b()` 호출 유지 — 08:59 이미 구독된 종목은 `_subscribed` 플래그로 스킵 (멱등)
- 변경 불필요 (기존 로직이 멱등성 보장)

### 4.4 Change 4 — 15:20 KRX 구독 해지

#### `_apply_market_phase()` 트리거 조건 변경
```python
# 기존: KRX "체결 정산" 진입 시 (15:30)
if new_krx == "체결 정산" and prev_krx != "체결 정산":
    schedule_engine_task(_on_krx_after_hours_start(), context="KRX 장외 전환")

# 변경: KRX "종가 동시호가" 진입 시 (15:20)
if new_krx == "종가 동시호가" and prev_krx != "종가 동시호가":
    schedule_engine_task(_on_krx_closing_auction_start(), context="KRX 종가 동시호가 — 구독 해지")
```

#### 함수 개명: `_on_krx_after_hours_start()` → `_on_krx_closing_auction_start()`
- 동작 내용은 동일 (재계산 + KRX 단독 종목 해지)
- docstring 갱신: "15:30 체결 정산" → "15:20 종가 동시호가"
- Code Removal Rules 준수: 모든 참조(docstring, 주석, 테스트) 갱신

#### 15:30 트리거 제거
- 기존 15:30 "체결 정산" 진입 시 `_on_krx_after_hours_start()` 트리거 제거
- 15:30은 부작용 없이 phase 변경만 (로그만 출력)

#### P22 (데이터 정합성) 검증
- 종가는 20:40 확정시세 다운로드로 수신 → 15:20 KRX 해지 시 종가 데이터 손실 없음
- 시장가 체결만 사용 → 15:20~15:30 종가 동시호가 구간 체결 불가 → 구독 유지 불필요
- `KRX_INACTIVE_PHASES`에 "종가 동시호가" 포함 → 15:20 이후 `is_nxt_only_window()=True` (NXT-enabled 종목은 구독 유지)

---

## 5. P21 사용자 투명성 검토

### 5.1 사전 구독 UI 표시 (사용자 결정: 불필요)

07:59/08:59 사전 구독 시 UI에 "사전 구독 중" 상태를 표시하는 방안을 조사 단계에서 검토했으나, 사용자 결정으로 **불필요** 확정. 사전 구독은 내부 최적화(1분 일찍 구독 신청)이며 사용자가 알 필요가 없는 구현 세부.

### 5.2 15:20 KRX 해지 UI 표시

15:20 KRX 해지는 백엔드 내부 동작. 사용자는 이미 UI에서 장 상태("종가 동시호가")를 확인 가능. 추가 UI 표시 불필요 — 장 상태 표시로 충분 (P21 준수).

### 5.3 프론트엔드 변경 사항

**없음** — 4개 변경 전부 백엔드 내부 동작. 프론트엔드는 기존 `market-phase` 브로드캐스트로 장 상태를 이미 수신 중. 사전 구독 구간(07:59~08:00)의 `market_phase`는 "장개시전" 유지 → 프론트엔드 변화 없음.

---

## 6. 영향 파일 목록

### 6.1 핵심 변경 파일

| 파일 | 변경 내용 | 변경 규모 |
|------|-----------|-----------|
| `backend/app/services/daily_time_scheduler.py` | 상수 추가, 함수 확장/축소/개명/신규, 트리거 조건 변경 | 중 |
| `backend/tests/test_daily_time_scheduler.py` | 테스트 갱신 (07:58 통합, 07:59 사전 구간, 08:59 KRX 사전 구독, 15:20 해지) | 중 |

### 6.2 확인 필요 파일 (변경 가능성)

| 파일 | 확인 내용 | 변경 가능성 |
|------|-----------|-------------|
| `backend/app/services/engine_loop.py` | `_init_ws_subscribe_state()` 재시작 시 사전 구간 동작 확인 | 낮음 (변경 불필요 예상) |
| `backend/app/services/engine_state.py` | `last_krx_pre_subscribe_date` 상태 필드 추가 | 낮음 (1개 필드 추가) |

### 6.3 변경 없음 파일 (영향 없음 확인)

| 파일 | 확인 결과 |
|------|-----------|
| `backend/app/services/engine_ws_dispatch.py` | JIF 페이즈 맵 변경 없음 (사전 구간은 시간 기반) |
| `backend/app/services/engine_ws_reg.py` | `subscribe_sector_stocks_0b()` 멱등성으로 변경 불필요 |
| `backend/app/services/market_close_pipeline.py` | `remove_krx_only_stocks()` 변경 없음 (호출 시점만 이동) |
| `frontend/src/` | UI 변경 없음 (P21 5.1~5.3 참조) |

---

## 7. 다단계 작업 세션 분할 제안

> 규칙 0-1(세션당 1단계) 준수. 각 세션은 독립적으로 완료·검증 가능한 단위.

| 세션 | 단계 | 작업 내용 | 검증 |
|------|------|-----------|------|
| **1세션 (현재)** | 설계 | 설계서 작성 (`docs/architecture_subscribe_timeline_design.md`) | 사용자 승인 |
| **2세션** | 태스크 | 심층 사전조사(규칙 0-2 4항목) + 태스크 파일 작성 (`docs/plan_subscribe_timeline.md`) | 사용자 승인 |
| **3세션** | 구현 Step 1 | 사전 구간 판정 + 07:58 통합 (Change 1, 2) — `_is_pre_subscribe_window()`, `is_ws_subscribe_window()`, `is_nxt_only_window()`, `_on_realtime_fields_reset()` 확장, `_on_ws_subscribe_start()` 축소 | pytest + 런타임 기동 |
| **4세션** | 구현 Step 2 | 08:59 KRX 사전 구독 + 15:20 KRX 해지 (Change 3, 4) — `KRX_PRE_SUBSCRIBE_TIME`, `_on_krx_pre_subscribe()`, `_check_prestart_triggers()` 확장, `_apply_market_phase()` 트리거 변경, 함수 개명 | pytest + 런타임 기동 |
| **5세션** | 검증 + 정리 | 통합 런타임 검증 + 문서 갱신(`ARCHITECTURE.md` 타임라인) + 계획서 삭제 | pytest 전체 + 빌드 + 런타임 |

### 7.1 분할 근거

- **3세션/4세션 분할**: Change 1+2(사전 구간 판정 + 07:58 통합)은 `is_ws_subscribe_window()`/`is_nxt_only_window()`/`_on_realtime_fields_reset()`/`_on_ws_subscribe_start()`가 밀접하게 연관. Change 3+4(08:59 사전 구독 + 15:20 해지)는 `_check_prestart_triggers()`/`_apply_market_phase()` 트리거 영역. 두 그룹은 수정 파일이 동일하지만 수정 함수가 독립적.
- **5세션 분리**: 통합 검증 + 문서 갱신 + 계획서 삭제는 구현 완료 후 별도 세션에서 수행 (규칙 0-1 + 계획서 삭제 규칙).

---

## 8. 표준 검토 근거

### 8.1 P10 (SSOT)
- `is_ws_subscribe_window()`의 판정 기준이 `market_phase` + 시간 상수(기존 상수 재사용)로 단일화.
- `_is_pre_subscribe_window()` 헬퍼로 시간 기반 판정 로직을 1곳에 집중 (중복 금지).

### 8.2 P16 (살아있는 경로)
- 재시작 시 `_init_ws_subscribe_state()` → `is_ws_subscribe_window()` 시간 기반 판정 → 사전 구간 내 재시작도 정상 동작.
- 07:58 누락 시 07:59 `_on_ws_subscribe_start()` 보완 호출 → `_on_realtime_fields_reset()` 1회 호출로 전체 데이터 준비 복구.

### 8.3 P20 (폴백 금지)
- 시간 기반 판정은 정상 경로 확장 (폴백 아님). `ws_subscribe_window_active` 플래그 미의존 → 메모리 초기화 시 폴백 불필요.
- 보완 로직(`_on_realtime_fields_reset()` 호출)은 멱등성 가드 기반 정상 경로 (silent except: pass 금지).

### 8.4 P21 (사용자 투명성)
- 사전 구독 UI 표시: 사용자 결정으로 불필요 (내부 최적화).
- 15:20 KRX 해지: 기존 장 상태 UI 표시로 충분.

### 8.5 P22 (데이터 정합성)
- 15:20 KRX 해지 시 종가 데이터 손실 없음 (20:40 확정시세 다운로드로 수신).
- 시장가 체결만 사용 → 동시호가 구간 구독 유지 불필요.

### 8.6 P23 (일관성)
- `_is_pre_subscribe_window()` 공통 헬퍼 추출 (DRY).
- 함수 개명(`_on_krx_after_hours_start()` → `_on_krx_closing_auction_start()`)으로 명칭-동작 일치.
- 용어 통일: "구독"/"해지" (ARCHITECTURE.md 부록 L 준수).

### 8.7 P24 (단순성)
- 안 A(시간 기반) / 안 A(함수 확장) / 안 A(함수 개명) 선택 — 가장 단순한 대안.
- 신규 함수 2개(`_is_pre_subscribe_window()`, `_on_krx_pre_subscribe()`)만 추가 — 기존 구조 유지.
- 프론트엔드 변경 없음 — 백엔드 내부 최적화.

---

## 9. 검증 방법 (5세션 상세)

### 9.1 테스트
- `pytest backend/tests/test_daily_time_scheduler.py` — 07:58 통합, 07:59 사전 구간, 08:59 KRX 사전 구독, 15:20 해지 트리거
- `pytest backend/tests/test_engine_loop.py` — 재시작 시 사전 구간 동작
- pytest 전체 회귀 (기존 2822 passed 카운트 유지)

### 9.2 런타임 검증
- `python3 -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 0건
- 07:58/07:59/08:59/15:20/15:30/20:00 로그 확인 (거래일 장 시간대)
- `/api/settings` 응답 정상
- 잔존 프로세스 0건

### 9.3 빌드
- `npm run build` — 프론트엔드 변경 없으므로 기존 빌드 유지 (회귀 확인용)
