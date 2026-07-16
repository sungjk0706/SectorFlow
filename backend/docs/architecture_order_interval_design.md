# 매수/매도 주문 간격 설정 아키텍처 설계 검토 (2026-07-17)

> **상태**: 설계 검토 완료. 안 B(공통 모듈 추출 + 분리 설정 + 초 단위) 선택. 코드 수정 전 사용자 승인 대기.
> **관련 원칙**: P10(SSOT), P15(단일 주문 경로), P16(살아있는 경로), P20(폴백 금지), P21(사용자 투명성), P23(일관성), P24(단순성)

---

## 1. 배경

### 1-1. 현재 상태
- **매수 주문 간격**: 구현됨. `buy_interval_on` 토글 + `buy_interval_min`(분 단위) 값.
  - 게이트 위치: `buy_order_executor.py:105-112` — `evaluate_buy_candidates()` 진입 시 사전 체크
  - 타이머 상태: `engine_state.py:76` `_last_global_buy_ts`
  - 매수 성공 시 갱신: `buy_order_executor.py:185-186`
  - 일일 초기화 시 리셋: `settings.py:152-153`
- **매도 주문 간격**: 미구현. `check_sell_conditions()`가 매 틱마다 손절/익절/T/S 조건 평가 후 즉시 `execute_sell()` 호출. 유일한 차단은 `_recent_sells`(종목별, 체결 확인 전까지 재주문 차단) — 시간 기반 전역 쿨다운 없음.

### 1-2. 문제의식
1. **파세코 패턴 허용**: 매수만 간격이 있고 매도는 무제한 → 매수→즉시 매도→재매수 루프 가능. 특히 모의투자(수수료 0원)에서 비용 없이 1초 단위 루프 발생.
2. **분 단위 한계**: 1분(60초) 안에 여러 번 매매 가능 → 1초 간격 루프를 분 단위 설정으로는 차단 불가.
3. **연속 매도 수수료 낭비**: T/S가 여러 종목에서 동시 발동 시 한 번에 다수 매도 → 수수료 누적.
4. **P23 위반 우려**: 매수 간격 로직(7줄 패턴)을 매도에도 동일하게 적용 시 동일 패턴 2곳 중복.

### 1-3. 사용자 확정 사항
| 항목 | 결정 |
|------|------|
| 매도 간격 추가 | **추가** (손절 포함 모든 매도에 동일 적용) |
| 단위 | **초 단위** (분 → 초 변경) |
| 범위 | **5초 ~ 300초**, 기본값 **30초**, **5초 단위** 입력 |
| 설정 키 | **`_sec`로 변경** + 기동 시 마이그레이션 (기존 `buy_interval_min` × 60) |
| 통합/분리 | **각각 따로** (`buy_interval_sec` + `sell_interval_on`/`sell_interval_sec`) |
| 구현 방식 | **공통 모듈 추출** (`check_order_interval()` 헬퍼) |
| UI 안내 | "5초 단위로 설정 가능합니다" 라벨 표시 |

---

## 2. 3가지 설계안 비교표

| 항목 | 안 A (로직 복사) | **안 B (공통 모듈 추출 — 선택)** | 안 C (통합 단일 간격) |
|---|---|---|---|
| **매수/매도 설정 키** | `buy_interval_sec` + `sell_interval_sec` (분리) | `buy_interval_sec` + `sell_interval_on`/`sell_interval_sec` (분리) | `order_interval_sec` (통합) |
| **게이트 로직 위치** | `buy_order_executor.py` + `trading.py` 각각 복사 | **`order_interval.py` 헬퍼** — 양쪽에서 호출 | `order_interval.py` 헬퍼 — 단일 키 |
| **타이머 상태** | `_last_global_buy_ts` + `_last_global_sell_ts` | `_last_global_buy_ts` + `_last_global_sell_ts` | `_last_order_ts` (단일) |
| **P10 (SSOT)** | 위험 (간격 판단 로직 2곳) | **준수** (헬퍼 1곳, 단위 변환 1곳) | 준수 (단일 키) |
| **P15 (단일 주문 경로)** | 준수 (execute_buy/sell 경로 유지) | **준수** (게이트만 추가, 경로 분기 없음) | 준수 |
| **P16 (살아있는 경로)** | 준수 (양쪽에 게이트 배선) | **준수** (헬퍼가 양쪽 실제 경로에서 호출) | 준수 |
| **P20 (폴백 금지)** | 준수 | **준수** (0도 유효값 — `or` 폴백 금지 패턴 유지) | 준수 |
| **P21 (사용자 투명성)** | 준수 | **준수** (UI에 매도 간격 섹션 추가, 차단 시 로그) | 부분 (매도 후 매수도 차단되어 사용자 혼란) |
| **P23 (일관성)** | **위반** (동일 패턴 2곳 중복) | **준수** (공통 자산 추출) | 준수 |
| **P24 (단순성)** | 가장 단순 (추상화 0) | 중간 (헬퍼 1개 추가, ~30줄) | 가장 단순 (키 1개) |
| **실전 유연성** | 양호 (분리 조정) | **양호** (분리 조정) | **부족** (매도 후 매수까지 차단 → 순환 매매 저해) |
| **단위 변경 영향** | 2곳 수정 | **1곳 수정** (헬퍼 내부) | 1곳 수정 |
| **마이그레이션** | buy만 (기존 1개 키) | buy만 (기존 1개 키) | buy만 (기존 1개 키) |

---

## 3. 최종 선택: 안 B (공통 모듈 추출 + 분리 설정 + 초 단위)

### 선택 근거

1. **P23 준수**: 동일한 간격 판단 패턴이 매수/매도 양쪽에서 필요 → 공통 헬퍼로 추출하여 중복 제거. "동일 패턴 2회 이상 반복 시 공통 컴포넌트 추출" 규칙 준수.
2. **실전 유연성**: 매수/매도는 서로 다른 의사결정(매수=자금 집중, 매도=수수료+손실 확정). 분리 설정으로 독립 조정 가능. 통합 시 "매도 후 매수"까지 막혀 순환 전략 불가.
3. **파세코 패턴 차단**: 양쪽 모두 쿨다운 → 어느 한쪽만 차단해도 루프가 끊김. 5초 최소값으로 1초 루프를 5번째 시도부터 차단.
4. **마이그레이션 단순**: 기존 `buy_interval_min` 1개 키만 변환. 기본값이 0(비활성화)이므로 사용자가 명시 설정한 경우에만 영향.
5. **단위 변경 집중**: 분→초 변환 로직이 헬퍼 1곳에 집중 → 향후 단위 변경 시 1곳만 수정.

### 안 A/C 미선택 사유
- **안 A**: P23 위반 (동일 패턴 2곳 중복). 향후 단위 변경 시 2곳 수정 필요.
- **안 C**: 통합 시 "매도 후 매수"까지 차단되어 정상 순환 매매 저해. 매수/매도 리스크 프로파일이 다름.

---

## 4. 안 B 동작 원리

### 4-1. 공통 헬퍼 모듈 (신규)

**파일**: `backend/app/services/order_interval.py` (~30줄)

```python
# -*- coding: utf-8 -*-
"""
주문 간격 게이트 공통 헬퍼 — 매수/매도 양쪽에서 호출 (P23 공통 자산).

매수: buy_order_executor.evaluate_buy_candidates() 진입 시 사전 체크
매도: trading.check_sell_conditions() for-loop 진입 전 사전 체크
"""
import time
from backend.app.services.engine_state import state


def check_order_interval(settings: dict, kind: str) -> bool:
    """
    주문 간격 게이트 — 간격 내면 False 반환 (호출측에서 return).
    kind: "buy" | "sell"
    반환: True=통과(주문 시도 가능), False=차단(간격 내)
    """
    _on = bool(settings.get(f"{kind}_interval_on", False))
    if not _on:
        return True
    _sec = int(settings.get(f"{kind}_interval_sec", 0) or 0)
    if _sec <= 0:
        return True
    _last_ts = state._last_global_buy_ts if kind == "buy" else state._last_global_sell_ts
    if _last_ts <= 0:
        return True  # 최초 주문 — 타이머 미설정
    return (time.time() - _last_ts) >= _sec


def mark_order_executed(kind: str) -> None:
    """
    주문 전송 성공 시 타이머 갱신.
    kind: "buy" | "sell"
    """
    _now = time.time()
    if kind == "buy":
        state._last_global_buy_ts = _now
    else:
        state._last_global_sell_ts = _now
```

**설계 포인트**:
- `check_order_interval()`은 순수 판정 함수 — 상태 변경 없음 (P24 단순성).
- `mark_order_executed()`는 주문 성공 경로에서만 호출 (P16 살아있는 경로).
- 0도 유효값이므로 `or 0` 폴백이 아닌 `int(... or 0)` 패턴 — 기존 `buy_order_executor.py:108`과 동일 (P20 준수).
- `state._last_global_*_ts <= 0` 체크로 최초 주문 허용 (기존 `_last_global_buy_ts=0.0` 초기값과 호환).

### 4-2. 매수 경로 수정

**`buy_order_executor.py:105-112`** (기존 7줄 → 헬퍼 호출 3줄):
```python
# 기존:
_buy_interval_on = bool(state.integrated_system_settings_cache.get("buy_interval_on", False))
if _buy_interval_on:
    _buy_interval_min = int(state.integrated_system_settings_cache.get("buy_interval_min", 0) or 0)
    if _buy_interval_min > 0:
        _now_check = time.time()
        if _now_check - state._last_global_buy_ts < _buy_interval_min * 60:
            return

# 변경 후:
from backend.app.services.order_interval import check_order_interval
if not check_order_interval(state.integrated_system_settings_cache, "buy"):
    return
```

**`buy_order_executor.py:185-186`** (타이머 갱신):
```python
# 기존:
if _buy_interval_on:
    state._last_global_buy_ts = time.time()

# 변경 후:
from backend.app.services.order_interval import mark_order_executed
mark_order_executed("buy")
```

- `mark_order_executed("buy")`는 토글 ON/OFF와 무관하게 항상 호출 → 토글 OFF 시에도 타이머는 갱신되지만 게이트가 통과시키므로 영향 없음 (P24 단순성 — 토글 체크 분기 제거).

### 4-3. 매도 경로 수정

**`trading.py:check_sell_conditions()` line 605 부근** (RiskManager 체크 후, for-loop 전):
```python
# 신규 추가 — 매도 간격 게이트 (for-loop 진입 전)
from backend.app.services.order_interval import check_order_interval
if not check_order_interval(base_settings, "sell"):
    return
```

- 위치: RiskManager 서킷브레이커 체크(line 596-604) **이후**, for-loop(line 606) **이전**.
- 이유: 리스크 차단된 매도가 타이머를 갱신하면 안 됨 (매수 로직과 동일 패턴 — 사전 체크 후 게이트).

**`trading.py:execute_sell()` line 473 부근** (주문 전송 성공 시):
```python
# 기존 line 473:
self._recent_sells.add(stk_cd)

# 변경 후:
self._recent_sells.add(stk_cd)
from backend.app.services.order_interval import mark_order_executed
mark_order_executed("sell")
```

- 위치: `_recent_sells.add(stk_cd)` 직후, 주문 전송(`send_order`) **이전**.
- 이유: 주문 전송을 시도한 시점이 곧 "매도 시도" 시점. 전송 실패 시 `_recent_sells.discard(stk_cd)`(line 513)가 호출되지만 타이머는 갱신 유지 → 실패한 매도도 간격으로 카운트 (매수 로직과 다소 비대칭이나, 실패 반복 방지에 유리).
- **대안 (검토)**: 주문 전송 **성공 후**(line 534 이후)에 타이머 갱신. 매수 로직(`buy_order_executor.py:185`)은 `_ordered` True 시 갱신하므로 매도도 성공 후 갱신이 일관적. → **2세션 심층 사전조사에서 확정**.

### 4-4. 손절 적용 (사용자 결정: 손절에도 간격 적용)

- `check_sell_conditions()` for-loop 전 게이트 → 손절/익절/T/S 모두 간격 내 차단.
- **주의**: 손절이 간격 내에서 발생하면 최대 30초(기본값) 지연 → 손실 확대 가능.
- 사용자가 명시적으로 "손절에도 적용"을 선택했으므로 이 결정을 존중.
- UI에 "손절 포함 모든 매도에 간격 적용됨" 안내 추가 권장 (P21 사용자 투명성).

### 4-5. 설정 키 마이그레이션 (분 → 초)

**`engine_settings.py` line 230-233** (기존):
```python
result["buy_interval_on"]              = bool(merged.get("buy_interval_on", False))
_v = merged.get("buy_interval_min")
result["buy_interval_min"]             = int(_v if _v is not None else 0)
```

**변경 후**:
```python
# 매수 주문 간격 (초 단위, 5~300, 기본 30)
result["buy_interval_on"]              = bool(merged.get("buy_interval_on", False))
_v = merged.get("buy_interval_sec")
if _v is None:
    # 마이그레이션: 기존 buy_interval_min(분) × 60 → 초. 0(비활성화)은 그대로 0.
    _legacy = merged.get("buy_interval_min")
    _v = int(_legacy) * 60 if _legacy is not None and str(_legacy).strip() != "" else 30
result["buy_interval_sec"]             = int(_v if _v is not None else 30)

# 매도 주문 간격 (초 단위, 5~300, 기본 30) — 신규
result["sell_interval_on"]             = bool(merged.get("sell_interval_on", False))
_v = merged.get("sell_interval_sec")
result["sell_interval_sec"]            = int(_v if _v is not None else 30)
```

**마이그레이션 규칙**:
- `buy_interval_sec` 키가 DB에 없고 `buy_interval_min`이 있으면 × 60 변환.
- `buy_interval_min=0`(비활성화 기본값) → `buy_interval_sec=0` 유지 (토글 OFF이므로 값은 무의미).
- `buy_interval_min=5`(5분) → `buy_interval_sec=300`(5분).
- `sell_interval_*`은 신규 → 마이그레이션 불필요, 기본값 30초.
- **DB 스키마 변경 없음**: `integrated_system_settings` 테이블은 key-value 구조 → 새 키 추가만. 백업 불필요 (AGENTS.md Safety Rule 2 — 스키마 변경 시에만 백업).

### 4-6. 기본값 (settings_defaults.py)

```python
# 기존:
"buy_interval_on": False,
"buy_interval_min": 0,

# 변경 후:
"buy_interval_on": False,
"buy_interval_sec": 30,  # 토글 OFF 시 무의미, ON 시 기본 30초
"sell_interval_on": False,
"sell_interval_sec": 30,
```

### 4-7. 엔진 상태 (engine_state.py line 76)

```python
# 기존:
self._last_global_buy_ts: float = 0.0

# 변경 후:
self._last_global_buy_ts: float = 0.0
self._last_global_sell_ts: float = 0.0
```

### 4-8. 일일 초기화 (settings.py line 153)

```python
# 기존:
state._last_global_buy_ts = 0.0

# 변경 후:
state._last_global_buy_ts = 0.0
state._last_global_sell_ts = 0.0
```

---

## 5. 프론트엔드 수정

### 5-1. 매수 설정 (buy-settings.ts line 338-350)

```typescript
// 기존 라벨: '매수 주문 간격 활성화 (분)'
// 변경 후: '매수 주문 간격 활성화 (초)'

buyIntervalInput = createNumInput({
  value: 30,  // 기본값 0 → 30
  onChange: v => { vals.buy_interval_sec = v; saveHelper!.autoSave('buy_interval_sec', v) },
  step: 5,    // 5초 단위
  min: 5,     // 최소 5초
  max: 300,   // 최대 300초
  name: 'buy_interval_sec',
})
const r = createToggleLabelControlsRow({
  labelText: '매수 주문 간격 활성화 (초, 5초 단위)',
  toggleOn: false,
  onToggle: next => { vals.buy_interval_on = next; saveHelper!.saveImmediate({ buy_interval_on: next }) },
  controlsChild: buyIntervalInput.el,
})
```

- "5초 단위로 설정 가능합니다" 안내 라벨 추가 (사용자 확정 사항).

### 5-2. 매도 설정 (sell-settings.ts line 77 부근)

신규 섹션 추가:
```typescript
// ── 매도 주문 간격 섹션 ──
root.appendChild(sectionTitle('매도 주문 간격'))

sellIntervalInput = createNumInput({
  value: 30,
  onChange: v => { vals.sell_interval_sec = v; saveHelper!.autoSave('sell_interval_sec', v) },
  step: 5,
  min: 5,
  max: 300,
  name: 'sell_interval_sec',
})
const r = createToggleLabelControlsRow({
  labelText: '매도 주문 간격 활성화 (초, 5초 단위)',
  toggleOn: false,
  onToggle: next => { vals.sell_interval_on = next; saveHelper!.saveImmediate({ sell_interval_on: next }) },
  controlsChild: sellIntervalInput.el,
})
sellIntervalToggle = r.toggle; sellIntervalControls = r.controls
root.appendChild(r.el)

// 안내 라벨: "5초 단위로 설정 가능합니다. 손절 포함 모든 매도에 간격이 적용됩니다."
```

### 5-3. 타입 (types/index.ts line 122-124)

```typescript
// 기존:
buy_interval_on: boolean
buy_interval_min: number

// 변경 후:
buy_interval_on: boolean
buy_interval_sec: number
sell_interval_on: boolean
sell_interval_sec: number
```

---

## 6. 테스트 계획

### 6-1. 매수 간격 테스트 (기존 test_buy_order_executor.py 수정)

**`TestBuyIntervalGate`** (line 231-259):
- `test_buy_interval_blocks_within_period`: `buy_interval_min=5` → `buy_interval_sec=300`, `_last_global_buy_ts = time.time()` → 차단 확인
- `test_buy_interval_passes_after_period`: `buy_interval_min=1` → `buy_interval_sec=60`, `_last_global_buy_ts = time.time() - 120` → 통과 확인 (120초 > 60초)
- 신규: `test_buy_interval_off_passes` — 토글 OFF 시 항상 통과
- 신규: `test_buy_interval_zero_sec_passes` — 토글 ON + 0초 시 항상 통과

### 6-2. 매도 간격 테스트 (신규 test_trading.py 또는 test_sell_order_executor.py)

**`TestSellIntervalGate`**:
- `test_sell_interval_blocks_within_period`: `sell_interval_on=True, sell_interval_sec=30`, `_last_global_sell_ts = time.time()` → `check_sell_conditions()` 호출 시 for-loop 진입 안 함 (execute_sell 미호출)
- `test_sell_interval_passes_after_period`: `_last_global_sell_ts = time.time() - 60` → 통과 (60초 > 30초)
- `test_sell_interval_off_passes`: 토글 OFF 시 항상 통과
- `test_sell_interval_applies_to_loss_cut`: 손절 조건 + 간격 내 → execute_sell 미호출 (사용자 결정: 손절에도 적용)
- `test_mark_order_executed_updates_sell_ts`: execute_sell 성공 시 `_last_global_sell_ts` 갱신 확인

### 6-3. 마이그레이션 테스트 (신규)

- `test_buy_interval_migration_min_to_sec`: `buy_interval_min=5`만 있고 `buy_interval_sec` 없음 → `build_engine_settings_dict()` 결과 `buy_interval_sec=300`
- `test_buy_interval_migration_zero`: `buy_interval_min=0` → `buy_interval_sec=0` (비활성화 유지)
- `test_buy_interval_no_migration_when_sec_present`: `buy_interval_sec=120` 있음 → 120 유지 (마이그레이션 미실행)

### 6-4. 런타임 검증 (구현 세션)

- 백엔드 기동 후 `python -W error::RuntimeWarning main.py` — async await 누락 검사
- 매수/매도 간격 토글 ON 후 실제 간격 차단 로그 확인
- 프론트엔드 빌드 + 브라우저에서 매도 설정 섹션 표시 확인

---

## 7. 아키텍처 원칙 준수 검토

| 원칙 | 준수 여부 | 근거 |
|------|----------|------|
| **P10 (SSOT)** | 준수 | 간격 판단 로직 `order_interval.py` 1곳. 타이머 상태 `engine_state.py` 1곳. 단위 변환 `engine_settings.py` 1곳. |
| **P15 (단일 주문 경로)** | 준수 | `execute_buy()`/`execute_sell()` 경로 유지. 게이트만 추가, 분기/우회 없음. |
| **P16 (살아있는 경로)** | 준수 | 헬퍼가 실제 매수/매도 실행 경로에서 호출됨. dead code 아님. |
| **P20 (폴백 금지)** | 준수 | 0도 유효값 — `int(... or 0)` 패턴 유지 (기존 코드와 일치). 마이그레이션 실패 시 silent fallback 없음. |
| **P21 (사용자 투명성)** | 준수 | UI에 매도 간격 섹션 추가. "손절 포함 적용" 안내. 차단 시 로그 출력. |
| **P22 (데이터 정합성)** | 준수 | 파생 데이터 없음. 타이머는 메모리 상태 (휘발성, 일일 리셋). |
| **P23 (일관성)** | 준수 | 공통 헬퍼 추출로 동일 패턴 중복 제거. 용어 사전 준수 ("매수"/"매도"). |
| **P24 (단순성)** | 준수 | 헬퍼 ~30줄, 함수 50줄 이하. 불필요한 추상화 없음. 토글 체크 분기 제거로 단순화. |

---

## 8. 수정 범위 요약

### 백엔드 (7곳)
1. `backend/app/core/settings_defaults.py` — 기본값 (`buy_interval_sec=30`, `sell_interval_on=False`, `sell_interval_sec=30`), `buy_interval_min` 제거
2. `backend/app/core/engine_settings.py` line 230-233 — `_sec` 필드 + 마이그레이션 로직
3. `backend/app/services/engine_state.py` line 76 — `_last_global_sell_ts` 추가
4. **신규** `backend/app/services/order_interval.py` — 공통 헬퍼 (`check_order_interval`, `mark_order_executed`)
5. `backend/app/services/buy_order_executor.py` line 105-112, 185-186 — 헬퍼 호출로 교체
6. `backend/app/services/trading.py` `check_sell_conditions()` line 605 부근 + `execute_sell()` line 473 부근 — 헬퍼 게이트 + 타이머 갱신
7. `backend/app/web/routes/settings.py` line 153 부근 — 일일 초기화 시 `_last_global_sell_ts` 리셋

### 프론트엔드 (3곳)
1. `frontend/src/pages/buy-settings.ts` line 338-350 — 라벨 "분"→"초", step 5, min 5, max 300, 키 `_sec`, 안내 라벨
2. `frontend/src/pages/sell-settings.ts` line 77 부근 — "매도 주문 간격" 섹션 신규 추가
3. `frontend/src/types/index.ts` line 122-124 — 타입 필드 교체/추가

### 테스트 (2곳)
1. `backend/tests/test_buy_order_executor.py` line 231-259 — `_sec` 키로 교체, 신규 케이스 추가
2. `backend/tests/test_trading.py` (또는 신규) — `TestSellIntervalGate` + 마이그레이션 테스트

### 문서 (1곳)
1. `ARCHITECTURE.md` line 818 — `buy_interval_min` → `buy_interval_sec`, 매도 간격 항목 추가

---

## 9. 다단계 작업 세션 분할 제안

| 세션 | 단계 | 내용 |
|------|------|------|
| 1세션 (완료) | 설계 | 본 설계서 작성 |
| 2세션 | 태스크 | 심층 사전조사 + `docs/plan_order_interval.md` 태스크 파일 작성 (구현 Step + 세션 분할 + 테스트 계획 상세) |
| 3세션 | 구현 Step 1 | 백엔드: `order_interval.py` 헬퍼 + `engine_state.py` + `settings_defaults.py` + `engine_settings.py` (마이그레이션) + `settings.py` 일일 리셋 |
| 4세션 | 구현 Step 2 | 백엔드: `buy_order_executor.py` 헬퍼 적용 + `trading.py` 매도 게이트 + 타이머 갱신 |
| 5세션 | 구현 Step 3 | 프론트엔드: `buy-settings.ts` + `sell-settings.ts` + `types/index.ts` |
| 6세션 | 구현 Step 4 | 테스트: `test_buy_order_executor.py` 수정 + `TestSellIntervalGate` + 마이그레이션 테스트 |
| 7세션 | 구현 Step 5 | 문서 갱신(`ARCHITECTURE.md`) + 런타임 검증 + 계획서 파일 삭제 |

- 각 구현 세션은 규칙 0-1(세션당 1단계) 준수.
- 2세션에서 작업량 계산 후 세션 분할 확정.

---

## 10. 사용자 승인 대기 항목

본 설계서의 다음 결정을 사용자가 승인해야 2세션(태스크 파일 작성) 진행 가능:

1. **안 B 선택** (공통 모듈 추출 + 분리 설정 + 초 단위) — 섹션 3
2. **헬퍼 인터페이스** (`check_order_interval`/`mark_order_executed`) — 섹션 4-1
3. **매도 타이머 갱신 시점** — 주문 전송 전(line 473) vs 성공 후(line 534) — 섹션 4-3 (2세션에서 확정)
4. **마이그레이션 규칙** (`buy_interval_min × 60 → buy_interval_sec`, 0은 유지) — 섹션 4-5
5. **손절에도 간격 적용** (사용자 이미 확정, 설계서에 명시) — 섹션 4-4
6. **세션 분할 제안** (7세션) — 섹션 9
