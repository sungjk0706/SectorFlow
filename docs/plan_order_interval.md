# 구현 계획서: 매수/매도 주문 간격 설정 개선 (다단계 작업 태스크)

> **상태**: 심층 사전조사 완료 · 구현 계획 수립 완료 · **사용자 승인 대기**
> **작성일**: 2026-07-17
> **관련 설계 문서**: `backend/docs/architecture_order_interval_design.md` (안 B — 공통 모듈 추출 + 분리 설정 + 초 단위)
> **관련 원칙**: P10(SSOT) · P15(단일 주문 경로) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)
> **단계 위치**: 다단계 작업 7세션 중 **2세션** (1세션: 설계서 → **본 파일: 태스크** → 3~7세션: 구현)

---

## 1. 배경 및 목적

### 1-1. 문제 상황 (1세션 설계서 요약)

- **매수 주문 간격**: 구현됨. 분 단위(`buy_interval_min`). 게이트 위치 `buy_order_executor.py:105-112`.
- **매도 주문 간격**: 미구현. 매 틱마다 손절/익절/T/S 조건 평가 후 즉시 `execute_sell()` 호출. 시간 기반 전역 쿨다운 없음.
- **파세코 패턴 허용**: 매수만 간격이 있고 매도는 무제한 → 매수→즉시 매도→재매수 루프 가능.
- **분 단위 한계**: 1분(60초) 안에 여러 번 매매 가능 → 1초 간격 루프를 분 단위 설정으로는 차단 불가.

### 1-2. 목적 (안 B — 1세션 사용자 확정)

1. **공통 헬퍼 추출**: `order_interval.py` 신규 — `check_order_interval()` / `mark_order_executed()` (P23 동일 패턴 중복 제거)
2. **분 → 초 단위 변경**: `buy_interval_min` → `buy_interval_sec` (기동 시 마이그레이션 × 60)
3. **매도 간격 신규 추가**: `sell_interval_on` + `sell_interval_sec` (손절 포함 모든 매도에 적용)
4. **범위**: 5초 ~ 300초, 기본 30초, 5초 단위 입력
5. **UI 안내**: "5초 단위로 설정 가능합니다" + "손절 포함 모든 매도에 간격이 적용됩니다"

### 1-3. 사용자 확정 사항 (1세션)

| 항목 | 결정 |
|------|------|
| 매도 간격 추가 | 추가 (손절 포함 모든 매도에 동일 적용) |
| 단위 | 초 단위 (분 → 초 변경) |
| 범위 | 5초 ~ 300초, 기본 30초, 5초 단위 |
| 설정 키 | `_sec`로 변경 + 기동 시 마이그레이션 (기존 `buy_interval_min` × 60) |
| 통합/분리 | 각각 따로 (`buy_interval_sec` + `sell_interval_on`/`sell_interval_sec`) |
| 구현 방식 | 공통 모듈 추출 (`check_order_interval()` 헬퍼) |
| UI 안내 | "5초 단위로 설정 가능합니다" 라벨 표시 |

---

## 2. 심층 사전조사 결과 (2세션 신규)

### 2-1. ★ 매도 타이머 갱신 시점 결정 (설계서 미확정 항목 — 해결)

**설계서 섹션 4-3 대안 검토**: 주문 전송 전(line 473) vs 성공 후(line 534)

#### 비교 분석

| 항목 | line 473 (전송 전) | **line 534 (성공 후) — 선택** |
|------|------|------|
| 매수 로직과의 일관성 (P23) | **불일치** — 매수는 `if _ordered:` 성공 시만 갱신 | **일치** — 매수 `buy_order_executor.py:182-186`와 동일 패턴 |
| 타이머 의미 (P22) | 실패한 매도도 "실행"으로 기록 → 의미 왜곡 | **실제 실행된 매도만 카운트** — 의미 정확 |
| 실패 시 보호 | 간격으로 보호 (실패도 간격 소비) | **서킷브레이커가 보호** — `trading.py:517-531` `record_order_failure()` + OPEN 시 마스터 OFF |
| 단일 책임 (P24) | 간격 게이트가 실패 보호 겸함 → 책임 중복 | **간격 게이트 = 실행 간격만 담당**, 실패 보호는 서킷브레이커 담당 |

#### 결정: **line 534 (주문 전송 성공 후)**

**근거**:
1. **P23 일관성**: 매수 로직(`buy_order_executor.py:182-186`)은 `if _ordered:` (성공) 시에만 `state._last_global_buy_ts = time.time()` 갱신. 매도도 성공 시 갱신이 동일 패턴.
2. **P22 데이터 정합성**: 타이머 의미 = "마지막 실제 주문 실행 시각". 실패한 전송은 실행이 아님 → 실패를 실행으로 기록하면 정합성 위반.
3. **P24 단순성 + P15 단일 책임**: 매도 실패 시 이미 `RiskManager.record_order_failure()` + 서킷브레이커(`trading.py:517-531`) + `_recent_sells.discard()`(`trading.py:513`)가 보호. 간격 게이트가 실패 보호를 겸할 필요 없음.
4. **설계서의 "비대칭" 우려 해소**: 설계서 섹션 4-3에서 "매수 로직과 다소 비대칭"으로 지적한 line 473 안을 버리고, line 534 안으로 매수/매도 대칭 달성.

**정확한 삽입 위치**: `trading.py:execute_sell()` 내 `if not result.get("success"): ... return` 블록(line 512-532) 종료 **직후**, 저널링(`record_order_request`, line 534-543) **이전**.

```python
# line 532: return (실패 블록 종료)
# ↓↓↓ 신규 삽입 — 성공 경로 진입 시 타이머 갱신 ↓↓↓
from backend.app.services.order_interval import mark_order_executed
mark_order_executed("sell")
# ↑↑↑ 신규 삽입 ↑↑↑
# line 534: # ── 저널링: 주문 요청 기록 ──
```

### 2-2. ★ 설계서가 놓친 수정 지점 4곳 발견

설계서 섹션 8 "수정 범위 요약"에서 누락된 참조 (전체 코드베이스 grep으로 발견):

| # | 파일:라인 | 내용 | 수정 필요 |
|---|-----------|------|------------|
| 1 | `backend/tests/test_engine_settings.py:353-356` | `test_buy_interval_settings` — `buy_interval_min=30` 입력 → `result["buy_interval_min"] == 30` 검증 | `_sec` 키 + 마이그레이션 검증으로 교체 |
| 2 | `backend/tests/test_web_routes.py:549` | `mock_state._last_global_buy_ts = 0.0` (일일 리셋 테스트) | `_last_global_sell_ts = 0.0` 추가 |
| 3 | `frontend/src/pages/buy-settings.ts:157-159` | `syncFromSettings()` — `r.buy_interval_min` 참조 | `r.buy_interval_sec`로 교체 (설계서는 line 338-350만 언급) |
| 4 | `backend/app/services/buy_order_executor.py:36` | docstring "buy_interval_on 시 사용자 설정 간격 대기" | "초 단위" 반영 갱신 (P23 + Code Removal Rules) |

### 2-3. 프론트엔드 sell-settings.ts 구조 분석

- **`syncFromSettings()`** (line 38-63): tp/loss/ts 동기화 → 매도 간격 동기화 블록 신규 추가 필요
- **변수 선언** (line 20-35): tpToggle/lossToggle/tsToggle + 입력/래퍼 → `sellIntervalToggle`/`sellIntervalInput`/`sellIntervalControls` 3개 추가
- **`mount()`** (line 66-127): `sectionTitle('매도 유형')` 후 익절/손절/추적매도 → "매도 주문 간격" 섹션 신규 추가 (추적매도 `tsDropRow` 이후, `container.appendChild(root)` line 123 이전)
- **`unmount()`** (line 129-138): 변수 null 처리 → `sellInterval*` 3개 변수 null 처리 추가
- **import**: `createToggleLabelControlsRow`가 sell-settings.ts에 **없음** → import 추가 필요 (buy-settings.ts에는 있음, line 5). `createNumInput`은 이미 import됨(line 5).
- **안내 라벨**: "5초 단위로 설정 가능합니다. 손절 포함 모든 매도에 간격이 적용됩니다." — `createSettingRow` 또는 별도 라벨 요소로 추가

### 2-4. buy-settings.ts 수정 상세 (설계서 보완)

설계서 섹션 5-1은 line 338-350만 언급하나, 실제 3곳 수정 필요:

| 위치 | 현재 | 변경 후 |
|------|------|---------|
| line 67-69 | `buyIntervalToggle/Input/Controls` 변수 선언 | 유지 (변수명 변경 불필요) |
| line 157-159 | `r.buy_interval_min` 참조 + `setValue(Number(r.buy_interval_min) \|\| 0)` | `r.buy_interval_sec` 참조 + `setValue(Number(r.buy_interval_sec) \|\| 30)` |
| line 341 | `createNumInput({ value: 0, ... step: 1, name: 'buy_interval_min' })` + `vals.buy_interval_min` | `createNumInput({ value: 30, ... step: 5, min: 5, max: 300, name: 'buy_interval_sec' })` + `vals.buy_interval_sec` |
| line 343 | `labelText: '매수 주문 간격 활성화 (분)'` | `labelText: '매수 주문 간격 활성화 (초, 5초 단위)'` |
| line 341 이후 | (없음) | 안내 라벨 추가: "5초 단위로 설정 가능합니다" |

### 2-5. ARCHITECTURE.md line 817-818

```
| `buy_interval_on` | False | 매수 주문 간격 활성화 (토글) |
| `buy_interval_min` | 0분 | 1순위 종목 매수 후 대기 간격 (분 단위) |
```
→ 변경:
```
| `buy_interval_on` | False | 매수 주문 간격 활성화 (토글) |
| `buy_interval_sec` | 30초 | 매수 주문 간격 (초 단위, 5~300, 5초 단위) |
| `sell_interval_on` | False | 매도 주문 간격 활성화 (토글) |
| `sell_interval_sec` | 30초 | 매도 주문 간격 (초 단위, 5~300, 5초 단위, 손절 포함) |
```

### 2-6. 헬퍼 모듈 import 방식 (P23 일관성)

기존 코드베이스의 함수 내부 import 패턴 확인:
- `buy_order_executor.py:39-42`: 함수 내부 `from backend.app.services import dry_run` 등
- `trading.py:480, 495, 521-522`: 함수 내부 import 패턴 다수

→ `order_interval.py` import도 함수 내부 import로 통일 (순환 import 방지 + 기존 패턴 일관성). 단, `order_interval.py` 내부에서 `engine_state` import는 모듈 top-level (순환 위험 없음 — `engine_state`는 `order_interval`을 import하지 않음).

### 2-7. DB 스키마 변경 여부 (안전 규칙 확인)

- `integrated_system_settings` 테이블은 key-value 구조 → 새 키(`buy_interval_sec`, `sell_interval_on`, `sell_interval_sec`) 추가만.
- **스키마 변경 없음** → DB 백업 불필요 (AGENTS.md Safety Rule 2 — 스키마 변경 시에만 백업).
- 기존 `buy_interval_min` 키는 DB에 잔존 가능하나 마이그레이션 로직에서 읽고 `_sec`로 변환 후 사용 → 잔존 키는 무시 (삭제 불필요 — P20 폴백 금지, 레거시 데이터 존중).

---

## 3. 수정 범위 (전체 — 설계서 + 심층조사 누락 4곳 반영)

### 백엔드 (8곳 — 설계서 7곳 + test_engine_settings.py 1곳)

| # | 파일 | 수정 내용 | 세션 |
|---|------|-----------|------|
| 1 | `backend/app/services/order_interval.py` | **신규** — `check_order_interval()` + `mark_order_executed()` (~30줄) | 3 |
| 2 | `backend/app/services/engine_state.py:76` | `_last_global_sell_ts: float = 0.0` 추가 | 3 |
| 3 | `backend/app/core/settings_defaults.py:92-94` | `buy_interval_min: 0` → `buy_interval_sec: 30` + `sell_interval_on: False` + `sell_interval_sec: 30` | 3 |
| 4 | `backend/app/core/engine_settings.py:230-233` | `_sec` 필드 + 마이그레이션 로직 (buy) + sell 3줄 신규 | 3 |
| 5 | `backend/app/web/routes/settings.py:153` | 일일 초기화 시 `_last_global_sell_ts = 0.0` 리셋 추가 | 3 |
| 6 | `backend/app/services/buy_order_executor.py:36, 105-112, 185-186` | docstring 갱신 + 헬퍼 호출로 교체 (게이트 + 타이머) | 4 |
| 7 | `backend/app/services/trading.py:605 부근, 534 부근` | 매도 간격 게이트 (for-loop 전) + 타이머 갱신 (성공 후) | 4 |
| 8 | `backend/tests/test_engine_settings.py:353-356` | `test_buy_interval_settings` → `_sec` + 마이그레이션 검증 | 6 |

### 프론트엔드 (3곳)

| # | 파일 | 수정 내용 | 세션 |
|---|------|-----------|------|
| 1 | `frontend/src/pages/buy-settings.ts:157-159, 338-350` | `syncFromSettings` `_sec` 교체 + 입력(step 5, min 5, max 300) + 라벨 "초" + 안내 | 5 |
| 2 | `frontend/src/pages/sell-settings.ts:5, 20-35, 38-63, 66-127, 129-138` | import 추가 + 변수 3개 + syncFromSettings + mount 섹션 + unmount 정리 | 5 |
| 3 | `frontend/src/types/index.ts:122-124` | `buy_interval_min` → `buy_interval_sec` + `sell_interval_on` + `sell_interval_sec` | 5 |

### 테스트 (3곳 — 설계서 2곳 + test_web_routes.py 1곳)

| # | 파일 | 수정 내용 | 세션 |
|---|------|-----------|------|
| 1 | `backend/tests/test_buy_order_executor.py:52, 231-264` | `_default_settings` `_sec` 교체 + `TestBuyIntervalGate` `_sec` 키 + 신규 케이스 2개 | 6 |
| 2 | `backend/tests/test_trading.py` (또는 신규) | `TestSellIntervalGate` 5개 + 마이그레이션 테스트 3개 | 6 |
| 3 | `backend/tests/test_web_routes.py:549` | `mock_state._last_global_sell_ts = 0.0` 추가 | 6 |

### 문서 (1곳)

| # | 파일 | 수정 내용 | 세션 |
|---|------|-----------|------|
| 1 | `ARCHITECTURE.md:817-818` | `buy_interval_min` → `buy_interval_sec` + 매도 간격 2줄 추가 | 7 |

---

## 4. 구현 Step 상세 (세션별)

### 4-1. 3세션: 백엔드 기반 (Step 1)

**목표**: 헬퍼 모듈 + 상태/설정/마이그레이션 기반 구축 (아직 호출 경로에 배선하지 않음 — 4세션에서 배선)

**수정 파일 5개**:
1. **신규 `order_interval.py`** (~30줄):
   - `check_order_interval(settings: dict, kind: str) -> bool` — 토글 OFF/0초/최초 시 True, 간격 내 False
   - `mark_order_executed(kind: str) -> None` — `state._last_global_buy_ts`/`_last_global_sell_ts` 갱신
   - `int(... or 0)` 패턴 (P20 — 0도 유효값, `or` 폴백 아님)
2. **`engine_state.py:76`**: `self._last_global_sell_ts: float = 0.0` 추가 + 주석 갱신 ("매수/매도 주문 간격")
3. **`settings_defaults.py:92-94`**: `buy_interval_min: 0` 제거 → `buy_interval_sec: 30` + `sell_interval_on: False` + `sell_interval_sec: 30`
4. **`engine_settings.py:230-233`**: 마이그레이션 로직 + sell 3줄
   ```python
   result["buy_interval_on"] = bool(merged.get("buy_interval_on", False))
   _v = merged.get("buy_interval_sec")
   if _v is None:
       _legacy = merged.get("buy_interval_min")
       _v = int(_legacy) * 60 if _legacy is not None and str(_legacy).strip() != "" else 30
   result["buy_interval_sec"] = int(_v if _v is not None else 30)
   result["sell_interval_on"] = bool(merged.get("sell_interval_on", False))
   _v = merged.get("sell_interval_sec")
   result["sell_interval_sec"] = int(_v if _v is not None else 30)
   ```
5. **`settings.py:153`**: `state._last_global_sell_ts = 0.0` 추가

**검증**:
- `python -m py_compile` 전체 파일
- `ruff check` 신규 파일
- `pytest test_engine_settings.py` — 기존 `test_buy_interval_settings` 실패 예상 (4세션에서 수정? 아니면 3세션에서 함께? → **3세션에서 수정** — 마이그레이션 로직 변경 즉시 테스트도 교체하지 않으면 pytest 전체 실패. 단, test_buy_order_executor.py의 `_default_settings`도 `buy_interval_min` 사용 → 3세션에서 함께 교체 필요)
- **수정**: 3세션에 `test_engine_settings.py:353-356` + `test_buy_order_executor.py:52` (`_default_settings` 헬퍼) 포함 — 설정/기반 변경의 직접 영향이므로 3세션에서 처리
- 런타임 기동 `python -W error::RuntimeWarning main.py` — RuntimeWarning 0건

**P원칙**: P10(SSOT — 헬퍼 1곳) · P20(폴백 금지) · P24(단순성 — ~30줄)

### 4-2. 4세션: 백엔드 배선 (Step 2)

**목표**: 헬퍼를 실제 매수/매도 실행 경로에 배선 (P16 살아있는 경로)

**수정 파일 2개**:
1. **`buy_order_executor.py`**:
   - line 36 docstring: "buy_interval_on 시 사용자 설정 간격 대기" → "buy_interval_on 시 사용자 설정 간격(초) 대기"
   - line 105-112 (7줄 → 3줄):
     ```python
     from backend.app.services.order_interval import check_order_interval
     if not check_order_interval(state.integrated_system_settings_cache, "buy"):
         return
     ```
   - line 185-186:
     ```python
     from backend.app.services.order_interval import mark_order_executed
     mark_order_executed("buy")
     ```
     - `if _buy_interval_on:` 조건 제거 → 토글 OFF 시에도 타이머 갱신 (게이트가 통과시키므로 영향 없음, P24 단순화)
     - `_buy_interval_on` 변수(line 106) 제거 — 헬퍼 내부로 이동
2. **`trading.py`**:
   - `check_sell_conditions()` line 605 부근 (RiskManager 체크 line 596-604 이후, for-loop line 606 이전):
     ```python
     from backend.app.services.order_interval import check_order_interval
     if not check_order_interval(base_settings, "sell"):
         return
     ```
   - `execute_sell()` line 534 부근 (성공 블록 진입 직후, 저널링 이전 — **2-1 결정**):
     ```python
     from backend.app.services.order_interval import mark_order_executed
     mark_order_executed("sell")
     ```

**검증**:
- `python -m py_compile` + `ruff check`
- `pytest test_buy_order_executor.py` — `TestBuyIntervalGate` 2개 케이스 `_sec` 키로 교체 (3세션에서 `_default_settings`만 교체, 테스트 케이스 본체는 4세션에서 교체? → **4세션에서 교체** — 배선 변경의 직접 영향)
- 런타임 기동 — 매수/매도 간격 토글 ON 후 차단 로그 확인 (모의투자 모드)

**P원칙**: P15(단일 주문 경로 — 게이트만 추가) · P16(살아있는 경로 — 헬퍼 실제 호출) · P23(일관성 — 매수/매도 동일 패턴)

### 4-3. 5세션: 프론트엔드 (Step 3)

**목표**: UI에 매도 간격 섹션 추가 + 매수 간격 초 단위 변경

**수정 파일 3개**:
1. **`buy-settings.ts`** (3곳):
   - line 157-159: `r.buy_interval_min` → `r.buy_interval_sec`, `setValue(Number(r.buy_interval_sec) || 30)`
   - line 341: `createNumInput({ value: 30, step: 5, min: 5, max: 300, name: 'buy_interval_sec' })` + `vals.buy_interval_sec`
   - line 343: 라벨 `'매수 주문 간격 활성화 (초, 5초 단위)'`
   - 안내 라벨 추가: "5초 단위로 설정 가능합니다"
2. **`sell-settings.ts`** (5곳):
   - line 5 import: `createToggleLabelControlsRow` 추가
   - line 20-35 변수: `sellIntervalToggle`/`sellIntervalInput`/`sellIntervalControls` 3개
   - `syncFromSettings()`: 매도 간격 동기화 블록 추가
   - `mount()` line 121 이후: "매도 주문 간격" 섹션 (sectionTitle + createNumInput + createToggleLabelControlsRow + 안내 라벨)
   - `unmount()`: 3개 변수 null 처리
3. **`types/index.ts:122-124`**: `buy_interval_min` → `buy_interval_sec` + `sell_interval_on` + `sell_interval_sec`

**검증**:
- `npm run build` 성공
- 브라우저: 매수 설정 "매수 주문 간격 활성화 (초, 5초 단위)" 라벨 + 5초 step 확인
- 브라우저: 매도 설정 "매도 주문 간격" 섹션 신규 표시 + 안내 라벨 확인

**P원칙**: P21(사용자 투명성 — 매도 간격 UI + 안내) · P23(UI 패턴 일관성 — createToggleLabelControlsRow 재사용)

### 4-4. 6세션: 테스트 (Step 4)

**목표**: 기존 테스트 `_sec` 교체 + 매도 간격 게이트 테스트 + 마이그레이션 테스트

**수정 파일 3개**:
1. **`test_buy_order_executor.py`** (line 231-264):
   - `TestBuyIntervalGate.test_buy_interval_blocks_within_period`: `buy_interval_min=5` → `buy_interval_sec=300`, `_last_global_buy_ts = time.time()` → 차단
   - `TestBuyIntervalGate.test_buy_interval_passes_after_period`: `buy_interval_min=1` → `buy_interval_sec=60`, `_last_global_buy_ts = time.time() - 120` → 통과 (120 > 60)
   - 신규 `test_buy_interval_off_passes`: 토글 OFF 시 항상 통과
   - 신규 `test_buy_interval_zero_sec_passes`: 토글 ON + 0초 시 항상 통과
2. **`test_trading.py`** (또는 신규 `test_sell_order_executor.py`):
   - `TestSellIntervalGate.test_sell_interval_blocks_within_period`: `sell_interval_on=True, sell_interval_sec=30`, `_last_global_sell_ts = time.time()` → `check_sell_conditions()` for-loop 진입 안 함
   - `TestSellIntervalGate.test_sell_interval_passes_after_period`: `_last_global_sell_ts = time.time() - 60` → 통과
   - `TestSellIntervalGate.test_sell_interval_off_passes`: 토글 OFF 시 통과
   - `TestSellIntervalGate.test_sell_interval_applies_to_loss_cut`: 손절 조건 + 간격 내 → execute_sell 미호출
   - `TestSellIntervalGate.test_mark_order_executed_updates_sell_ts`: execute_sell 성공 시 `_last_global_sell_ts` 갱신 (line 534 — 성공 후)
   - 마이그레이션: `test_buy_interval_migration_min_to_sec` / `test_buy_interval_migration_zero` / `test_buy_interval_no_migration_when_sec_present`
3. **`test_web_routes.py:549`**: `mock_state._last_global_sell_ts = 0.0` 추가

**검증**:
- `pytest` 전체 통과
- 신규 테스트 10개 (매수 2 + 매도 5 + 마이그레이션 3) 통과

### 4-5. 7세션: 문서 + 런타임 검증 + 계획서 삭제 (Step 5)

**목표**: 문서 갱신 + 통합 런타임 검증 + 계획서 정리

**수정 파일 1개 + 삭제 2개**:
1. **`ARCHITECTURE.md:817-818`**: `buy_interval_min` → `buy_interval_sec` + 매도 간격 2줄 추가
2. **삭제**: `docs/plan_order_interval.md` (본 파일) + `backend/docs/architecture_order_interval_design.md` (설계서) — 규칙: 계획서 삭제

**검증**:
- `pytest` 전체 통과 (이전 세션 대비 회귀 없음)
- `npm run build` 성공
- 런타임 기동 `python -W error::RuntimeWarning main.py` — RuntimeWarning 0건
- WS 설정 응답에 `buy_interval_sec`/`sell_interval_on`/`sell_interval_sec` 필드 존재 확인
- 잔존 `buy_interval_min` 참조 0건 (grep — 단, 마이그레이션 로직 내 `merged.get("buy_interval_min")` 1곳은 의도적 잔존)
- 잔존 프로세스 0건

---

## 5. 세션 분할 확정

| 세션 | 단계 | 내용 | 파일 수 | 예상 줄 수 |
|------|------|------|---------|-----------|
| 1세션 (완료) | 설계 | 설계서 작성 | 1 (신규) | 433 |
| **2세션 (본 파일)** | **태스크** | **심층 사전조사 + 태스크 파일** | **1 (신규)** | **본 파일** |
| 3세션 | 구현 Step 1 | 백엔드 기반: 헬퍼 + 상태 + 설정 + 마이그레이션 + 일일 리셋 + 테스트 기반 | 5 + 테스트 2 | ~80 |
| 4세션 | 구현 Step 2 | 백엔드 배선: buy_order_executor + trading.py 매도 게이트 + 타이머 + 테스트 케이스 | 2 + 테스트 1 | ~40 |
| 5세션 | 구현 Step 3 | 프론트엔드: buy-settings + sell-settings + types | 3 | ~70 |
| 6세션 | 구현 Step 4 | 테스트: TestSellIntervalGate + 마이그레이션 + test_web_routes | 2~3 | ~120 |
| 7세션 | 구현 Step 5 | 문서(ARCHITECTURE.md) + 런타임 검증 + 계획서 2개 삭제 | 1 + 삭제 2 | ~10 |

- **총 7세션** (설계서 제안과 동일 — 심층조사 후에도 균형 양호)
- 각 구현 세션은 규칙 0-1(세션당 1단계) 준수
- 3세션에 테스트 2개 파일 포함: 설정/기반 변경의 직접 영향(`_default_settings` 헬퍼 + `test_buy_interval_settings`)이므로 기반 세션에서 처리 — 분리 시 pytest 전체 실패 상태 방치 위반

---

## 6. 테스트 계획 상세

### 6-1. 매수 간격 (`test_buy_order_executor.py:TestBuyIntervalGate`)

| 테스트 | 설정 | 타이머 | 기대 |
|--------|------|--------|------|
| `test_buy_interval_blocks_within_period` | `buy_interval_on=True, buy_interval_sec=300` | `_last_global_buy_ts = time.time()` | `execute_buy` 미호출 (차단) |
| `test_buy_interval_passes_after_period` | `buy_interval_on=True, buy_interval_sec=60` | `_last_global_buy_ts = time.time() - 120` | `execute_buy` 호출 (통과) |
| `test_buy_interval_off_passes` (신규) | `buy_interval_on=False` | `_last_global_buy_ts = time.time()` | `execute_buy` 호출 (토글 OFF 시 항상 통과) |
| `test_buy_interval_zero_sec_passes` (신규) | `buy_interval_on=True, buy_interval_sec=0` | `_last_global_buy_ts = time.time()` | `execute_buy` 호출 (0초 = 비활성) |

### 6-2. 매도 간격 (`test_trading.py:TestSellIntervalGate` — 신규)

| 테스트 | 설정 | 타이머 | 기대 |
|--------|------|--------|------|
| `test_sell_interval_blocks_within_period` | `sell_interval_on=True, sell_interval_sec=30` | `_last_global_sell_ts = time.time()` | `execute_sell` 미호출 (for-loop 진입 안 함) |
| `test_sell_interval_passes_after_period` | `sell_interval_on=True, sell_interval_sec=30` | `_last_global_sell_ts = time.time() - 60` | `execute_sell` 호출 (통과) |
| `test_sell_interval_off_passes` | `sell_interval_on=False` | `_last_global_sell_ts = time.time()` | `execute_sell` 호출 (토글 OFF) |
| `test_sell_interval_applies_to_loss_cut` | `sell_interval_on=True, sell_interval_sec=30` + 손절 조건 | `_last_global_sell_ts = time.time()` | `execute_sell` 미호출 (손절도 간격 적용 — 사용자 결정) |
| `test_mark_order_executed_updates_sell_ts` | `sell_interval_on=True` | `_last_global_sell_ts = 0.0` | execute_sell 성공 후 `_last_global_sell_ts > 0` (line 534 성공 후 갱신) |

### 6-3. 마이그레이션 (`test_engine_settings.py` 또는 `test_trading.py`)

| 테스트 | 입력 | 기대 |
|--------|------|------|
| `test_buy_interval_migration_min_to_sec` | `{buy_interval_min: 5}` (buy_interval_sec 없음) | `result["buy_interval_sec"] == 300` |
| `test_buy_interval_migration_zero` | `{buy_interval_min: 0}` | `result["buy_interval_sec"] == 0` (비활성화 유지) |
| `test_buy_interval_no_migration_when_sec_present` | `{buy_interval_sec: 120, buy_interval_min: 5}` | `result["buy_interval_sec"] == 120` (마이그레이션 미실행) |

### 6-4. 일일 리셋 (`test_web_routes.py:549`)

- 기존 `mock_state._last_global_buy_ts = 0.0` 옆에 `mock_state._last_global_sell_ts = 0.0` 추가 — 리셋 후 두 타이머 모두 0 확인

---

## 7. 런타임 검증 방법 (7세션)

### 7-1. 백엔드 기동 검증

```bash
cd backend && python -W error::RuntimeWarning main.py
```
- RuntimeWarning 0건 (async await 누락 검사)
- 기동 후 WS 설정 응답에 `buy_interval_sec`/`sell_interval_on`/`sell_interval_sec` 필드 존재 확인
- 잔존 프로세스 0건 (`ps aux | grep main.py`)

### 7-2. 간격 차단 로그 확인 (모의투자 모드)

- 매수 간격 토글 ON + `buy_interval_sec=5` 설정 → 매수 후 5초 내 재매수 시도 시 차단 (로그로 확인)
- 매도 간격 토글 ON + `sell_interval_sec=5` 설정 → 매도 후 5초 내 재매도 시도 시 차단
- 단, 장 시간대가 아니면 실제 주문 시도 불가 → 7세션 런타임 검증은 기동 + 필드 확인 + 로그 레벨까지만. 실제 차단 로그는 장 시간대 별도 진행.

### 7-3. 프론트엔드 빌드 + 브라우저

```bash
cd frontend && npm run build
```
- 빌드 성공
- 브라우저: 매수 설정 페이지 "매수 주문 간격 활성화 (초, 5초 단위)" + 5초 step 확인
- 브라우저: 매도 설정 페이지 "매도 주문 간격" 섹션 + 안내 라벨 "5초 단위로 설정 가능합니다. 손절 포함 모든 매도에 간격이 적용됩니다." 확인

### 7-4. 잔존 참조 확인

```bash
# buy_interval_min 잔존 — 마이그레이션 로직 1곳만 허용
grep -rn "buy_interval_min" backend/ frontend/ --include="*.py" --include="*.ts"
# 허용: engine_settings.py 내 merged.get("buy_interval_min") 1곳 (마이그레이션)
# 허용: architecture_order_interval_design.md (7세션에서 삭제)
```

---

## 8. 아키텍처 원칙 준수 검토 (2세션 추가)

| 원칙 | 준수 | 근거 (2세션 심층조사 추가) |
|------|------|------|
| P10 (SSOT) | 준수 | 간격 판단 `order_interval.py` 1곳. 타이머 `engine_state.py` 1곳. 단위 변환 `engine_settings.py` 1곳. |
| P15 (단일 주문 경로) | 준수 | `execute_buy()`/`execute_sell()` 경로 유지. 게이트만 추가. |
| P16 (살아있는 경로) | 준수 | 헬퍼가 실제 매수/매도 경로에서 호출. 4세션 배선으로 dead code 아님 보장. |
| P20 (폴백 금지) | 준수 | `int(... or 0)` 패턴. 마이그레이션 실패 시 silent fallback 없음. |
| P21 (사용자 투명성) | 준수 | UI 매도 간격 섹션 + "손절 포함" 안내. 차단 시 로그. |
| P22 (데이터 정합성) | **준수 (2세션 강화)** | 매도 타이머 갱신을 성공 후(line 534)로 확정 → 실패를 실행으로 기록하지 않음. |
| P23 (일관성) | **준수 (2세션 강화)** | 매수/매도 타이머 갱신 시점 대칭 (모두 성공 후). 헬퍼 공통 자산. UI 패턴 `createToggleLabelControlsRow` 재사용. |
| P24 (단순성) | 준수 | 헬퍼 ~30줄. 토글 체크 분기 제거. 간격 게이트 = 실행 간격만 담당 (실패 보호는 서킷브레이커 담당 — 단일 책임). |

---

## 9. safe-trade 스킬 준수 (거래 로직 수정)

- **거래 모드**: `trade_mode` 기본값 `"test"` (모의투자) 유지 — 실거래 변경 없음
- **단일 주문 경로 (P15)**: `execute_buy()`/`execute_sell()` 경로 유지, 게이트만 추가 — 분기/우회 없음
- **살아있는 경로 (P16)**: 헬퍼가 실제 주문 경로에서 호출 — 4세션 배선으로 보장
- **테스트모드 동등성 (P18)**: 간격 게이트는 테스트/실전 동일 동작 — 모드 분기 없음
- **롤백 여부**: 본 작업은 신규 기능 추가(매도 간격) + 단위 변경(분→초)이지 기존 로직 롤백 아님. 단, `buy_order_executor.py:105-112` 기존 7줄을 헬퍼 호출로 교체 — 이는 사용자가 1세션에서 명시적으로 안 B(공통 모듈 추출)를 승인한 변경이므로 규칙 0-5 준수.

---

## 10. 사용자 승인 대기 항목

본 태스크 파일의 다음 결정을 사용자가 승인해야 3세션(구현 Step 1) 진행 가능:

1. **매도 타이머 갱신 시점: line 534 (성공 후)** — 섹션 2-1 (2세션 심층조사에서 확정)
2. **설계서 누락 4곳 추가 수정** — 섹션 2-2 (test_engine_settings.py + test_web_routes.py + buy-settings.ts syncFromSettings + buy_order_executor.py docstring)
3. **3세션에 테스트 2개 파일 포함** — 섹션 4-1 (기반 변경의 직접 영향이므로 기반 세션에서 처리)
4. **세션 분할 7세션 유지** — 섹션 5 (심층조사 후에도 균형 양호)
5. **DB 백업 불필요** — 섹션 2-7 (스키마 변경 없음, key-value 새 키 추가만)

---

## 11. 참조

- **설계서**: `backend/docs/architecture_order_interval_design.md` (1세션, 433줄)
- **규칙**: AGENTS.md 섹션4 "다단계 작업 워크플로우" + safe-trade 스킬
- **이전 완료 다단계 작업 참조**: 카운트다운 SSOT (5세션 완료) — `docs/plan_session_state_periodic_task.md` 형식 참조
