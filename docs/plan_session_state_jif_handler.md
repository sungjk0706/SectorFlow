# 구현 계획서: JIF 핸들러 확장 — 장 상태 전환 처리 (2단계)

> **상태**: 사전조사 완료 · 구현 계획 수립 완료 · **사용자 승인 대기**
> **작성일**: 2026-07-16
> **관련 설계 문서**: `backend/docs/architecture_session_state_design.md` (안 D — 하이브리드: JIF 1순위 + 시간 기반 보완)
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P23(일관성) · P24(단순성)
> **단계 위치**: 안 D 구현 4단계 중 **2단계** (1단계: JIF jstatus 코드 맵핑 사전 검증 → **2단계: 본 파일** → 3단계: 주기 태스크 + 타이머 제거 → 4단계: 런타임 통합 검증)

---

## 1. 배경 및 목적

### 1-1. 문제 상황

현재 `_handle_jif()` (engine_ws_dispatch.py:204~246)는 KRX 서킷브레이커/사이드카(jstatus 61~71)만 처리하며, **장 상태 전환 jstatus 코드(11, 21, 31, 41, 51, 52, 54, 55, 56, 57, 58 등)를 silent return** (line 226~227 `__no_change__` 분기).

이로 인해:
- 거래소가 push하는 장운영정보(ground truth)가 장 상태 관리에 활용되지 않음
- 장 상태 전환은 로컬 타이머 11개에만 의존 → 타이머 미실행 시 KRX 수신률 미표시 문제 발생 (HANDOVER.md 참조)
- 안 D 설계에서 JIF를 1순위 장 상태 소스로 사용하려면 `_handle_jif()` 확장 필수

### 1-2. 목적 (2단계 범위)

- `_handle_jif()`에 **장 상태 전환 처리 분기 추가** (서킷브레이커 처리와 분리)
- JIF jstatus 코드 → KRX/NXT 페이즈명 맵핑 테이블 구성
- JIF 수신 시 `state.market_phase` 갱신 + 부작용 트리거 (WS 구독, 업종 재계산 등)
- **타이머는 3단계에서 제거** — 2단계에서는 JIF 경로 추가만, 기존 타이머 유지

### 1-3. 1단계 사전 검증 결과 (문서 조회)

> **1단계 원칙**: "코드 수정 없음, 조사 only" — 본 2단계 계획서에 1단계 결과를 통합.

**JIF API 스펙 출처**: `docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt`

#### jangubun (장구분) 값
| 코드 | 의미 | 본 프로젝트 관련 |
|------|------|------------------|
| 1 | 코스피 | KRX — 현재 서킷브레이커 처리 중 |
| 2 | 코스닥 | KRX — 현재 서킷브레이커 처리 중 |
| 5 | 선물/옵션 | 미사용 |
| 6 | NXT전용 | **NXT — 현재 미처리, 2단계에서 추가** |
| 8 | KRX야간파생 | 미사용 |
| 9~F | 해외주식 | 미사용 |

#### jstatus 공통 코드 (모든 jangubun 공통)
| 코드 | 의미 | 시간대 (추정) |
|------|------|---------------|
| 11 | 장전동시호가개시 | 08:40 (KRX 동시호가 접수 시작) |
| 21 | 장시작 | 09:00 (정규장/메인마켓 시작) |
| 22 | 장개시 10초전 | 08:59:50 (카운트다운, 페이즈 전환 아님) |
| 23 | 장개시 1분전 | 08:59 (카운트다운) |
| 24 | 장개시 5분전 | 08:55 (카운트다운) |
| 25 | 장개시 10분전 | 08:50 (카운트다운) |
| 31 | 장후동시호가개시 | 15:20 (종가 동시호가 / 조기 마감 시작) |
| 41 | 장마감 | 15:30 (정규장 종료) |
| 42 | 장마감 10초전 | 15:29:50 (카운트다운) |
| 43 | 장마감 1분전 | 15:29 (카운트다운) |
| 44 | 장마감 5분전 | 15:15 (카운트다운) |
| 51 | 시간외종가매매개시 | 15:40 (장후 시간외 / 애프터마켓 시작) |
| 52 | 시간외종가매매종료, 시간외단일가매매개시 | 16:00 (시간외 단일가 시작) |
| 53 | 사용안함 | — |
| 54 | 시간외단일가매매종료 | 18:00 (장 종료 / 애프터마켓 지속 전환) |
| 55 | 프리마켓 개시 | 08:00 (NXT 프리마켓 시작) |
| A2~A5 | 프리마켓 장개시 N전 | 카운트다운 (08:59:50~08:50) |
| 56 | 에프터마켓 개시 | 15:40 (NXT 애프터마켓 시작) |
| B2~B5 | 에프터마켓 장개시 N전 | 카운트다운 |
| 57 | 프리마켓 마감 | 08:50 (NXT 프리마켓 종료) |
| C2~C4 | 프리마켓 장마감 N전 | 카운트다운 |
| 58 | 에프터마켓 마감 | 20:00 (NXT 장마감) |
| D2~D4 | 에프터마켓 장마감 N전 | 카운트다운 |

#### KOSPI/KOSDAQ 전용 (jangubun 1, 2) — 서킷브레이커/사이드카
| 코드 | 의미 | 현재 처리 |
|------|------|-----------|
| 61~71 | 서킷브레이커/사이드카 | **이미 구현됨** (변경 없음) |

#### 런타임 검증 상태
- **JIF 구독**: 로그인 직후 `subscribe_jif()` 호출 (ls_connector.py:400) — 구독 자체는 정상
- **런타임 로그**: JIF 수신 로그 없음 — 현재 코드가 비-CB jstatus를 로깅하지 않기 때문 (silent return)
- **미확인 사항**: 실제 런타임에서 어떤 jstatus 코드가 어떤 시점에 push되는지 미검증
  - 카운트다운 코드(22~25, 42~44, A2~A5, B2~B5, C2~C4, D2~D4)가 실제로 push되는지 미확인
  - jangubun 6(NXT)에 대해 공통 코드(55~58)가 push되는지 미확인
  - **2단계 구현 시 임시 DEBUG 로그 추가 후 런타임 검증 권장** (아래 섹션 5 참조)

---

## 2. 사전조사 결과 (심화)

### 2-1. 현재 _handle_jif() 구조 (engine_ws_dispatch.py:204~246)

```
_handle_jif(data)
  → jangubun/jstatus 파싱 (빈 값 시 return)
  → jangubun 1/2 (KRX):
      → _JSTATUS_KRX_ALERT 맵 조회 (61~71만 등록)
      → 미등록 코드("__no_change__") → silent return  ← 장 상태 전환 코드가 여기서 drop
      → 등록 코드: krx_alert 갱신 + 서킷브레이커 활성/해제 처리
  → jangubun 6 (NXT): 처리 없음 (함수 종료)
```

**문제**: jstatus 11/21/31/41/51/52/54/55/56/57/58 등 장 상태 전환 코드가 `_JSTATUS_KRX_ALERT` 맵에 없어 `__no_change__` 분기로 silent return 됨.

### 2-2. 현재 _broadcast_market_phase() 구조 (daily_time_scheduler.py:509~547)

```
_broadcast_market_phase()
  → prev_krx/prev_nxt = state.market_phase  # 이전 상태 저장
  → fresh = calc_timebased_market_phase()    # 시간 기반 재계산
  → state.market_phase = fresh               # 덮어쓰기  ← JIF 갱신이 무효화됨
  → _broadcast("market-phase", phase)        # WS 전송
  → 페이즈 변경 감지 시 부작용 트리거:
      - NXT "프리마켓" 진입 → _on_nxt_premarket_start() + _on_ws_subscribe_start()
      - KRX "정규장" 진입 → _on_krx_market_open()
      - KRX "체결 정산" 진입 → _on_krx_after_hours_start()
      - NXT "장마감" 진입 → _on_ws_subscribe_end()
```

**구조적 문제 (P10 위반 위험)**: `_broadcast_market_phase()`가 항상 `calc_timebased_market_phase()`로 state를 덮어쓰므로, JIF가 `state.market_phase`를 갱신해도 다음 타이머 호출 시 시간 기반 값으로 덮어씌워짐. JIF를 1순위로 만들려면 이 구조를 해결해야 함.

### 2-3. 해결 방안: _broadcast_market_phase() 분리

`_broadcast_market_phase()`를 **"계산" 단계와 "적용+전송+부작용" 단계로 분리**:

```
[신규] _apply_market_phase(phase: dict) -> None
  → prev_krx/prev_nxt = state.market_phase
  → state.market_phase = phase              # 전달받은 phase로 갱신 (JIF 또는 시간 기반)
  → _broadcast("market-phase", phase)
  → 페이즈 변경 감지 시 부작용 트리거 (기존 로직 이동)

[수정] _broadcast_market_phase() -> None
  → fresh = calc_timebased_market_phase()
  → _apply_market_phase(fresh)              # 분리된 함수 호출
```

- **JIF 경로**: `_handle_jif()` → `_apply_market_phase(jif_phase)` (JIF 맵 기반)
- **타이머 경로** (2단계에서 유지): 타이머 → `_broadcast_market_phase()` → `calc_timebased_market_phase()` → `_apply_market_phase()`
- **3단계 주기 태스크 경로**: 주기 태스크 → `_broadcast_market_phase()` (동일)

이렇게 분리하면:
- 부작용 트리거 로직이 `_apply_market_phase()` 한 곳에 집중 (P10 SSOT, P24 단순성)
- JIF가 1순위로 동작: JIF 수신 시 JIF 맵 기반 phase 적용, 타이머는 시간 기반 보완
- 타이머가 시간 기반으로 덮어쓰는 문제: 3단계에서 타이머 제거 시 해결. 2단계에서는 JIF와 타이머가 동시에 존재하므로, JIF 수신 직후 타이머가 덮어쓸 수 있으나 **페이즈 변경 감지 로직이 멱등성을 가지므로** (같은 페이즈면 부작용 미발생) 실질적 충돌 없음

### 2-4. JIF → 페이즈명 맵핑 설계

#### KRX (jangubun 1/2) jstatus → krx 페이즈명
| jstatus | 의미 | → krx 페이즈명 | 비고 |
|---------|------|----------------|------|
| 11 | 장전동시호가개시 | 동시호가 접수 | 08:40 |
| 21 | 장시작 | 정규장 | 09:00 — 부작용 트리거 대상 |
| 22~25 | 장개시 N전 | (무시) | 카운트다운, 페이즈 전환 아님 |
| 31 | 장후동시호가개시 | 종가 동시호가 | 15:20 |
| 41 | 장마감 | 체결 정산 | 15:30 — 부작용 트리거 대상 |
| 42~44 | 장마감 N전 | (무시) | 카운트다운 |
| 51 | 시간외종가매매개시 | 장후 시간외 | 15:40 |
| 52 | 시간외종가매매종료, 시간외단일가매매개시 | 시간외 단일가 | 16:00 |
| 54 | 시간외단일가매매종료 | 장 종료 | 18:00 |
| 61~71 | 서킷브레이커/사이드카 | (기존 처리 유지) | krx_alert만 갱신, 페이즈 변경 아님 |

#### NXT (jangubun 6) jstatus → nxt 페이즈명
| jstatus | 의미 | → nxt 페이즈명 | 비고 |
|---------|------|----------------|------|
| 55 | 프리마켓 개시 | 프리마켓 | 08:00 — 부작용 트리거 대상 |
| A2~A5 | 프리마켓 장개시 N전 | (무시) | 카운트다운 |
| 57 | 프리마켓 마감 | 정규장 준비 | 08:50 |
| 21 | 장시작 | 메인마켓 | 09:00 |
| 31 | 장후동시호가개시 | 조기 마감 | 15:20 |
| 41 | 장마감 | 단일가 매매 | 15:30 |
| 56 | 에프터마켓 개시 | 애프터마켓 | 15:40 |
| 58 | 에프터마켓 마감 | 장마감 | 20:00 — 부작용 트리거 대상 |
| B2~B5, C2~C4, D2~D4 | 카운트다운 | (무시) | 페이즈 전환 아님 |

#### 맵핑 주의사항
- **jstatus 21/31/41은 jangubun에 따라 다른 페이즈명**: jangubun 1/2면 KRX 페이즈, jangubun 6이면 NXT 페이즈
- **카운트다운 코드(22~25, 42~44, A2~A5, B2~B5, C2~C4, D2~D4)는 무시**: 페이즈 전환 이벤트가 아니므로 state 갱신 불필요 (P24 단순성)
- **jstatus 52는 복합 이벤트**: "시간외종가매매종료 + 시간외단일가매매개시" — KRX "시간외 단일가"로 맵핑
- **런타임 검증 필요**: 위 맵핑은 API 문서 기반이나, 실제 push 시점/코드값은 런타임 로그로 확인 필요 (규칙 1 — 추측 금지)

### 2-5. 연쇄 영향 파일

| 파일 | 함수/변수 | 영향 | 수정 여부 |
|------|-----------|------|-----------|
| `backend/app/services/engine_ws_dispatch.py` | `_handle_jif()`, 신규 `_JIF_PHASE_MAP_KRX`, `_JIF_PHASE_MAP_NXT`, `_JIF_IGNORE_CODES` | 핵심 수정 대상 — 장 상태 전환 분기 추가 | **수정** |
| `backend/app/services/daily_time_scheduler.py` | `_broadcast_market_phase()` 분리 → 신규 `_apply_market_phase()` | 부작용 트리거 로직 분리 | **수정** |
| `backend/tests/test_engine_ws_dispatch.py` | `TestHandleJif` 클래스 | JIF 장 상태 전환 테스트 추가 | **수정** |
| `backend/tests/test_daily_time_scheduler.py` | `_broadcast_market_phase` 관련 테스트 | `_apply_market_phase` 분리에 따른 테스트 | **수정** |
| `backend/app/services/engine_account_notify.py` | `_broadcast()` 호출 | 변경 없음 — 기존 함수 재사용 | 미수정 |
| `frontend/` | — | 변경 없음 — WS "market-phase" 이벤트 구조 동일 | 미수정 |

---

## 3. 구현 계획

### 3-1. 신규 상수: JIF 페이즈 맵 (engine_ws_dispatch.py)

```python
# ── JIF 장 상태 전환 맵 (jangubun 1/2 = KRX) ──
# 서킷브레이커(61~71)는 기존 _JSTATUS_KRX_ALERT에서 처리, 여기서는 장 상태 전환만.
_JIF_PHASE_MAP_KRX: dict[str, str] = {
    "11": "동시호가 접수",      # 장전동시호가개시 (08:40)
    "21": "정규장",             # 장시작 (09:00)
    "31": "종가 동시호가",      # 장후동시호가개시 (15:20)
    "41": "체결 정산",          # 장마감 (15:30)
    "51": "장후 시간외",        # 시간외종가매매개시 (15:40)
    "52": "시간외 단일가",      # 시간외종가매매종료+단일가개시 (16:00)
    "54": "장 종료",            # 시간외단일가매매종료 (18:00)
}

# ── JIF 장 상태 전환 맵 (jangubun 6 = NXT) ──
_JIF_PHASE_MAP_NXT: dict[str, str] = {
    "55": "프리마켓",           # 프리마켓 개시 (08:00)
    "57": "정규장 준비",        # 프리마켓 마감 (08:50)
    "21": "메인마켓",           # 장시작 (09:00)
    "31": "조기 마감",          # 장후동시호가개시 (15:20)
    "41": "단일가 매매",        # 장마감 (15:30)
    "56": "애프터마켓",         # 에프터마켓 개시 (15:40)
    "58": "장마감",             # 에프터마켓 마감 (20:00)
}

# ── JIF 카운트다운 코드 (무시 — 페이즈 전환 아님) ──
_JIF_IGNORE_CODES: frozenset[str] = frozenset({
    "22", "23", "24", "25",           # KRX 장개시 N전
    "42", "43", "44",                 # KRX 장마감 N전
    "A2", "A3", "A4", "A5",           # NXT 프리마켓 장개시 N전
    "B2", "B3", "B4", "B5",           # NXT 에프터마켓 장개시 N전
    "C2", "C3", "C4",                 # NXT 프리마켓 장마감 N전
    "D2", "D3", "D4",                 # NXT 에프터마켓 장마감 N전
    "53",                             # 사용안함
})
```

### 3-2. _handle_jif() 확장 (engine_ws_dispatch.py)

현재 구조(jangubun 1/2 → 서킷브레이커만)에 **장 상태 전환 분기 추가**:

```
_handle_jif(data)
  → jangubun/jstatus 파싱 (빈 값 시 return)
  → jstatus in _JIF_IGNORE_CODES → return (카운트다운 무시)

  → jangubun 1/2 (KRX):
      1) 장 상태 전환: _JIF_PHASE_MAP_KRX 조회 → phase 갱신 + _apply_market_phase()
      2) 서킷브레이커: _JSTATUS_KRX_ALERT 조회 → krx_alert 갱신 (기존 로직 유지)
      ※ 두 처리는 독립 — 장 상태 전환 코드(11/21/31/41/51/52/54)는 _JSTATUS_KRX_ALERT에 없고,
         서킷브레이커 코드(61~71)는 _JIF_PHASE_MAP_KRX에 없으므로 분리 가능

  → jangubun 6 (NXT):
      → _JIF_PHASE_MAP_NXT 조회 → phase 갱신 + _apply_market_phase()
```

**핵심 분기 로직** (의사 코드):
```python
async def _handle_jif(data: dict) -> None:
    jangubun = str(data.get("jangubun", "")).strip()
    jstatus = str(data.get("jstatus", "")).strip()
    if not jangubun or not jstatus:
        return

    # 카운트다운 코드 무시
    if jstatus in _JIF_IGNORE_CODES:
        return

    # ── 장 상태 전환 처리 (신규) ──
    if jangubun in ("1", "2"):
        new_krx = _JIF_PHASE_MAP_KRX.get(jstatus)
        if new_krx:
            await _apply_jif_phase(krx=new_krx)
            # 서킷브레이커는 별도 처리 (기존 로직 유지)
    elif jangubun == "6":
        new_nxt = _JIF_PHASE_MAP_NXT.get(jstatus)
        if new_nxt:
            await _apply_jif_phase(nxt=new_nxt)

    # ── 서킷브레이커/사이드카 처리 (기존 로직 유지) ──
    if jangubun in ("1", "2"):
        # ... 기존 _JSTATUS_KRX_ALERT 처리 로직 ...
```

### 3-3. _apply_jif_phase() 신규 함수 (engine_ws_dispatch.py)

JIF 수신 시 장 상태를 갱신하고 부작용을 트리거하는 함수.

```
_apply_jif_phase(krx: str | None = None, nxt: str | None = None)
  → 현재 state.market_phase에서 변경되지 않은 쪽은 시간 기반 값 유지
  → krx/nxt 중 수신된 쪽만 갱신
  → _apply_market_phase({krx, nxt}) 호출 — daily_time_scheduler에서 import
```

**주의**: JIF는 KRX(jangubun 1/2) 또는 NXT(jangubun 6) 개별적으로 push하므로, 한 번에 한쪽만 갱신. 다른 쪽은 기존 `state.market_phase` 값 유지.

### 3-4. _broadcast_market_phase() 분리 (daily_time_scheduler.py)

```
[신규] _apply_market_phase(phase: dict) -> None
  - prev_krx/prev_nxt 저장
  - state.market_phase 갱신
  - _broadcast("market-phase", phase)
  - 페이즈 변경 감지 → 부작용 트리거 (기존 line 532~545 로직 이동)
  - [장상태] 로그 출력 (기존 line 533~536 로직 이동)

[수정] _broadcast_market_phase() -> None
  - fresh = calc_timebased_market_phase()
  - _apply_market_phase(fresh)
```

### 3-5. 순환 참조 주의

- `engine_ws_dispatch.py`에서 `daily_time_scheduler.py`의 `_apply_market_phase()`를 import → **순환 참조 가능**
- 현재 `engine_ws_dispatch.py`는 이미 `engine_account_notify._broadcast`를 지연 import (line 219) → 동일 패턴으로 `daily_time_scheduler._apply_market_phase`도 함수 내 지연 import
- `daily_time_scheduler.py`는 `engine_ws_dispatch.py`를 import하지 않으므로 순환 참조 아님

---

## 4. 테스트 계획

### 4-1. test_engine_ws_dispatch.py — TestHandleJif 확장

| 테스트명 | 검증 내용 |
|----------|-----------|
| `test_jif_krx_phase_transition` | jangubun=1, jstatus=21 → krx "정규장" 갱신 + _apply_market_phase 호출 |
| `test_jif_nxt_phase_transition` | jangubun=6, jstatus=55 → nxt "프리마켓" 갱신 + _apply_market_phase 호출 |
| `test_jif_countdown_ignored` | jstatus=22 (장개시 10초전) → _apply_market_phase 호출 없음 |
| `test_jif_krx_circuit_breaker_unchanged` | jstatus=61 → 장 상태 전환 없음, 서킷브레이커 처리만 (기존 테스트 유지) |
| `test_jif_nxt_aftermarket_close` | jangubun=6, jstatus=58 → nxt "장마감" 갱신 |
| `test_jif_unknown_jstatus_no_change` | jstatus=99 → state 변경 없음 |
| `test_jif_phase_map_completeness` | _JIF_PHASE_MAP_KRX/NXT 키가 _JIF_IGNORE_CODES와 중복 없음 |

### 4-2. test_daily_time_scheduler.py — _apply_market_phase 테스트

| 테스트명 | 검증 내용 |
|----------|-----------|
| `test_apply_market_phase_change` | krx 변경 시 부작용 트리거 (_on_krx_market_open 호출) |
| `test_apply_market_phase_no_change` | 동일 페이즈 시 부작용 미발생 |
| `test_broadcast_market_phase_uses_calc` | _broadcast_market_phase()가 calc_timebased_market_phase() 결과를 _apply_market_phase에 전달 |

### 4-3. 검증 절차 (수정 후)

1. **py_compile**: `python -m py_compile backend/app/services/engine_ws_dispatch.py backend/app/services/daily_time_scheduler.py`
2. **ruff**: `ruff check backend/app/services/engine_ws_dispatch.py backend/app/services/daily_time_scheduler.py`
3. **테스트**: `pytest backend/tests/test_engine_ws_dispatch.py backend/tests/test_daily_time_scheduler.py -v`
4. **RuntimeWarning**: `python -W error::RuntimeWarning main.py` 기동 — async await 누락 확인
5. **런타임 기동**: 정상 기동 후 로그 확인 — JIF 수신 시 `[연결] JIF 장 상태 전환` 로그 출력 확인

---

## 5. 런타임 JIF 수신 검증 (1단계 보완 — 2단계 구현에 포함)

### 5-1. 임시 DEBUG 로그 추가

`_handle_jif()` 진입 시 모든 jangubun/jstatus 값을 DEBUG 로그로 출력:

```python
logger.debug("[연결] JIF 수신: jangubun=%s, jstatus=%s", jangubun, jstatus)
```

- 런타임 기동 후 장 시작 시점(08:00~09:00, 15:20~15:40, 20:00)에 JIF 수신 로그 확인
- 실제 push되는 jstatus 코드값과 맵핑 테이블 비교
- 누락된 코드 발견 시 맵 추가 (폴백 아닌 실제 데이터 기반 보완 — P20)

### 5-2. 검증 항목

1. **KRX jangubun 1/2**: 11, 21, 31, 41, 51, 52, 54 코드가 실제 push되는지
2. **NXT jangubun 6**: 55, 57, 21, 31, 41, 56, 58 코드가 실제 push되는지
3. **카운트다운 코드**: 22~25, 42~44, A2~A5 등이 push되는지 (push되어도 무시)
4. **push 시점**: API 문서의 시간대 추정이 실제와 일치하는지
5. **미push 전환**: JIF가 커버하지 않는 전환(예: KRX "장전 대기" 08:00, "장전 시간외" 08:30) 식별 → 3단계 주기 태스크가 보완

### 5-3. 검증 결과 처리

- 맵핑 테이블과 실제 코드가 불일치 시: **3단계 진행 전** 맵 수정 (별도 세션)
- JIF가 일부 전환만 커버 시: 3단계 주기 태스크가 보완하므로 설계대로 진행
- JIF가 전혀 push되지 않을 시: WS 구독 문제 별도 조사 (본 2단계 범위 외)

---

## 6. 아키텍처 원칙 점검 체크리스트

- [ ] **P10 (SSOT)**: 부작용 트리거 로직이 `_apply_market_phase()` 한 곳에 집중. JIF 맵과 시간 기반 함수가 각각 독립된 진실 소스이나, 적용 경로는 단일.
- [ ] **P16 (살아있는 경로)**: JIF 수신 시 JIF 경로가 동작. JIF 미수신 시 기존 타이머가 동작 (2단계). 3단계에서 주기 태스크가 보완.
- [ ] **P20 (폴백 금지)**: JIF 맵에 없는 코드는 silent return이 아닌, 카운트다운으로 명시적 분류(`_JIF_IGNORE_CODES`). 맵에 없는 비-카운트다운 코드는 DEBUG 로그 출력 후 추적 (폴백 아님).
- [ ] **P21 (사용자 투명성)**: JIF 장 상태 전환 시 `[장상태]` 로그 출력 (기존 `_apply_market_phase` 로직). 사용자가 JIF 기반 전환을 로그로 확인 가능.
- [ ] **P23 (일관성)**: 페이즈명이 `calc_timebased_market_phase()`의 페이즈명과 동일 (용어 사전 준수). 서킷브레이커 처리는 기존 패턴 유지.
- [ ] **P24 (단순성)**: `_handle_jif()` 함수 50줄 이하 유지 (분기 추가 후 초과 시 `_apply_jif_phase()`로 분리). `_apply_market_phase()`는 기존 `_broadcast_market_phase()`에서 로직 이동만 (신규 로직 아님).

---

## 7. 예상 수정 파일 및 분량

| 파일 | 수정 유형 | 예상 분량 |
|------|-----------|-----------|
| `backend/app/services/engine_ws_dispatch.py` | 신규 상수 3개 + `_handle_jif()` 확장 + `_apply_jif_phase()` 신규 | +60줄 |
| `backend/app/services/daily_time_scheduler.py` | `_apply_market_phase()` 추출 + `_broadcast_market_phase()` 단순화 | +20줄 / -10줄 |
| `backend/tests/test_engine_ws_dispatch.py` | TestHandleJif 테스트 7개 추가 | +80줄 |
| `backend/tests/test_daily_time_scheduler.py` | _apply_market_phase 테스트 3개 추가 | +40줄 |

---

## 8. 승인 대기 항목

- **2단계 구현 승인** (사용자 실행 지시어 대기 — 규칙 0)
- **JIF 페이즈 맵 검증 방식**: 임시 DEBUG 로그 추가 후 런타임 검증 (5절) — 본 2단계에 포함할지, 별도 세션으로 분리할지
- **jstatus 52 복합 이벤트 처리**: "시간외종가매매종료 + 시간외단일가매매개시"를 단일 페이즈 "시간외 단일가"로 맵핑할지 (현재 계획)
- **NXT 09:00:30 문제**: 설계 문서 7-1 항목 3 — 본 2단계에 포함하지 않음 (JIF "21:장시작"이 09:00:00에 push되면 09:00:00 갱신, 30초 차이는 무시). 3단계에서 별도 검토.
