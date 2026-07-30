# 설계서: 텔레그램 SSOT 4단계 — 프론트 거래일 기준 오늘 백엔드 참조 전환

> **상태**: 설계 완료 / 사용자 승인 대기
> **작성일**: 2026-07-31
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패)
> **관련 파일**: `backend/app/services/daily_time_scheduler.py` · `backend/app/services/engine_lifecycle.py` · `backend/app/services/engine_initial_data.py` · `backend/app/core/trading_calendar.py` · `frontend/src/utils/date.ts` · `frontend/src/stores/uiStore.ts` · `frontend/src/types/index.ts`
> **관련 API 스펙**: WS `engine-status` 이벤트 · WS `initial-snapshot` 이벤트
> **선행 작업**: 텔레그램 기간별 손익 SSOT 위반 수정 1~3단계 (커밋 `a89c7ad`) — 백엔드 텔레그램 명령어가 `get_chart_reference_trading_day()` 사용으로 전환 완료. 본 설계는 4단계(프론트 전환) 담당.

---

## 1. 배경 및 목표

### 1.1 현재 상태 — "거래일 기준 오늘" 두 개의 독립 구현

"거래일 기준 오늘" 개념이 **프론트엔드(phase 문자열 해석)와 백엔드(시간+캘린더)에 독립 구현**되어 있다.

| 계층 | 함수 | 기준 | 휴장일 처리 | 위치 |
|------|------|------|------------|------|
| 프론트 | `getTradingToday()` | `uiStore.marketPhase` 문자열 해석 ('장개시전'/'휴장일' → 전일) | `_prevWeekday()` — **주말만 스킵** | `frontend/src/utils/date.ts:43-49` |
| 백엔드 텔레그램 | `get_chart_reference_trading_day()` (1-3단계 전환 완료) | 08:00 시간 + 캘린더 | `get_previous_trading_day()` — **주말+평일 공휴일 스킵** | `trading_calendar.py:384-411` |
| 백엔드 dailySummary | `get_chart_reference_trading_day()` (동일) | 동일 | 동일 | `trade_history.py:626` |

**phase 자체는 이미 백엔드 SSOT**: `engine_state.market_phase` → `get_engine_status()` → WS `engine-status` → 프론트 `uiStore.marketPhase`. 즉 phase 판정은 문제 없음. **문제는 phase → 날짜 변환 단계**에서 프론트가 독자 로직(`_prevWeekday()`, 주말만 스킵)을 사용한다는 점.

### 1.2 불일치 시나리오

**시나리오 A — 평일 공휴일 (8월 15일 광복절, 금요일)**:
```
금 06:47 (08:00 프리마켓 개시 전, 8/15는 공휴일)
├─ 프론트 getTradingToday()     → 목 (8/14) ← _prevWeekday: 주말만 스킵, 금→목
├─ 백엔드 get_chart_reference_trading_day() → 수 (8/13) ← get_previous_trading_day: 금(공휴일)→목(주말)→수
└─ 텔레그램 (1-3단계 완료)       → 수 (8/13) ← 백엔드 SSOT
```
→ 프론트 수익현황(목요일 기준)과 텔레그램/dailySummary(수요일 기준)가 다른 결과 표시.

**시나리오 B — 월요일 06:47 (주말 직후)**:
```
월 06:47
├─ 프론트 getTradingToday()     → 금 ← _prevWeekday: 주말 스킵
├─ 백엔드 get_chart_reference_trading_day() → 금 ← get_previous_trading_day: 동일
└─ 텔레그램                     → 금 ← 동일
```
→ 주말만 걸치면 일치. **불일치는 평일 공휴일이 걸칠 때만 발생**.

### 1.3 목표

1. 프론트 `getTradingToday()`가 백엔드 `get_chart_reference_trading_day()` 값을 직접 사용 → 날짜 계산 단일 소스 수렴 (P10)
2. 프론트 `_prevWeekday()` 독자 로직 제거 → 휴장일 캘린더 의존성 제거 (P24)
3. 프론트 `isPreOpenPhase()`가 phase 문자열 해석 대신 백엔드 값 기반 판정으로 전환 → phase 문자열 집합(`PRE_OPEN_PHASES`) 하드코딩 제거 (P10)
4. 프론트↔텔레그램↔dailySummary 날짜 범위 완전 일치 (P22)

### 1.4 비목표

- **phase 판정 로직 변경 없음** — `calc_timebased_market_phase()`는 이미 백엔드 SSOT이며 프론트가 직접 판정하지 않음. 본 설계는 phase → 날짜 변환 경로만 다룸.
- **`get_chart_reference_trading_day()` 함수 수정 없음** — 백엔드 SSOT 함수는 1-3단계에서 이미 살아있는 경로에 배선됨. 본 설계는 노출 경로 추가만 수행.
- **`getTradingToday()` 사용처 로직 변경 없음** — `profit-shared.ts`/`profit-detail.ts` 등 호출부는 `getTradingToday()` 시그니처 유지하므로 수정 불필요. 함수 내부 구현만 교체.
- **거래 로직(매수/매도 게이트) 직접 수정 없음** — phase 판정은 매수 게이트가 참조하나, 본 수정은 phase 판정이 아닌 phase → 날짜 변환 경로. 매수 게이트는 여전히 `engine_state.market_phase` 문자열 기반 (무관).

---

## 2. 설계 방향

### 2.1 핵심 설계 결정

**결정 1: 백엔드 `get_market_phase()` 반환 dict에 `chart_reference_trading_day` 필드 추가**

`get_market_phase()` (`daily_time_scheduler.py:439`)는 phase SSOT 읽기 함수로, `get_engine_status()`와 `build_initial_snapshot()` 양쪽에서 호출된다. 따라서 이 함수에 필드를 추가하면:
- WS `engine-status` 이벤트 (`get_engine_status()` 경유)에 자동 포함
- WS `initial-snapshot` 이벤트 (`build_initial_snapshot()` 경유)에 자동 포함
- 양쪽 동일 패턴 (P23 일관성)

필드명: `chart_reference_trading_day` (ISO 날짜 문자열 `YYYY-MM-DD`)
값 출처: `get_chart_reference_trading_day().isoformat()` (`trading_calendar.py:384`)

**왜 `market_phase` dict 내부인가**: phase 관련 파생 데이터(`is_nxt_only`, `krx_countdown` 등)가 이미 `market_phase` dict 내부에 집중되어 있음. `chart_reference_trading_day`도 phase에서 파생되는 값이므로 동일 집합에 포함하는 것이 P23(일관성)·P24(단순성) 부합. 최상위 필드로 분리하면 phase 파생 데이터가 두 곳에 흩어짐.

**결정 2: 프론트 `getTradingToday()`가 백엔드 값 직접 반환**

```typescript
// 현재 (date.ts:43-49)
export function getTradingToday(): string {
  const calendarToday = getLocalToday()
  if (isPreOpenPhase()) {
    return _prevWeekday(calendarToday)
  }
  return calendarToday
}

// 목표
export function getTradingToday(): string {
  return uiStore.getState().marketPhase.chart_reference_trading_day ?? ''
}
```

- `uiStore.marketPhase.chart_reference_trading_day` 직접 반환
- `_prevWeekday()` 함수 제거 (P24 — 독자 로직 제거)
- `PRE_OPEN_PHASES` 상수 제거 (P10 — phase 문자열 집합 하드코딩 제거)

**결정 3: 프론트 `isPreOpenPhase()`가 백엔드 값 기반 판정으로 전환**

```typescript
// 현재 (date.ts:33-36)
export function isPreOpenPhase(): boolean {
  const phase = uiStore.getState().marketPhase
  return PRE_OPEN_PHASES.has(phase.krx) && PRE_OPEN_PHASES.has(phase.nxt)
}

// 목표
export function isPreOpenPhase(): boolean {
  const ref = uiStore.getState().marketPhase.chart_reference_trading_day
  return ref !== undefined && ref !== getLocalToday()
}
```

- `chart_reference_trading_day`가 로컬 오늘과 다르면 개장 전 (백엔드가 전일 반환했다는 의미)
- `PRE_OPEN_PHASES` 집합 하드코딩 제거 (P10)
- 백엔드가 08:00 경계에서 phase 전환 시 `chart_reference_trading_day`도 함께 갱신 → 자동 동기화

**결정 4: `uiStore` 초기값에 `chart_reference_trading_day` 기본값 추가**

엔진 기동 전 / WS 미연결 시 `marketPhase` 초기값에 빈 문자열 `''` 설정. `getTradingToday()`가 빈 문자열 반환 시 호출부에서 별도 처리 (빈 문자열이면 차트 미표시 등). P20(폴백 금지) — 빈 문자열을 폴백으로 덮지 않고 그대로 전달하여 호출부가 명시적으로 처리.

**결정 5: `getTradingMonthStart()`는 `getTradingToday()` 기반 유지**

```typescript
export function getTradingMonthStart(): string {
  return getTradingToday().slice(0, 7) + '-01'
}
```

변경 없음. `getTradingToday()`가 백엔드 값 반환하면 자동으로 백엔드 기준 월 시작일 산출. 월 경계일(예: 8/1 06:47)에 백엔드가 7/31 반환하면 `getTradingMonthStart()`도 7월 1일 반환 → 일관성 유지.

### 2.2 기각 방안

| 방안 | 기각 사유 |
|------|----------|
| **별도 REST API `/api/trading-day`** | phase는 이미 WS `engine-status`로 오고 있어 별도 API는 패턴 불일치 (P23 위반). 폴링 필요 시에만 API 유의미하나, 본 케이스는 WS push로 충분. |
| **프론트가 휴장일 캘린더 직접 보유** | P10(SSOT) 위반 심화 — 캘린더가 백엔드 단일 소스여야 하는데 프론트에 복제하면 동기화 부담. P24 위반 — 프론트에 캘린더 로직 추가는 복잡도 증가. |
| **`chart_reference_trading_day`를 `engine-status` 최상위 필드로 추가** | phase 파생 데이터가 `market_phase` dict 내부와 최상위에 분산 → P23(일관성) 위반. `get_market_phase()` 한 곳에서 추가하면 양쪽 노출 경로 자동 커버되므로 dict 내부가 단순 (P24). |
| **`isPreOpenPhase()` 제거 후 호출부가 `getTradingToday() !== getLocalToday()` 직접 판정** | `isPreOpenPhase()`는 `profit-shared.ts:199`에서 사용 중. 시그니처 유지가 호출부 수정 최소화 (P24 — 불필요한 호출부 변경 금지). 함수 내부만 교체. |
| **빈 문자열일 때 `getLocalToday()` 폴백** | P20(폴백 금지) — 정상 경로의 빈 문자열을 폴백으로 덮으면 엔진 기동 전에 잘못된 날짜(캘린더 오늘) 표시. 빈 문자열 그대로 전달하여 호출부가 명시 처리. |

---

## 3. 사용자 결정 항목

> problem-solve 섹션 1-1 의무 기록. 2세션 태스크 파일에서 활용.

| 질문 | 사용자 답변 | 비고 |
|------|------------|------|
| 이 작업을 다단계 워크플로우(설계안 → 태스크 파일 → 구현 3세션)로 진행할까요? | **다단계 진행** | 작업량 큼(프론트+백엔드 동시 수정), 디버깅 추적성 확보 |
| 백엔드가 '거래일 기준 오늘'을 프론트에 어떻게 노출할까요? | **engine-status 필드 추가** | 기존 WS 패턴 재사용, 별도 API 불필요 (P24) |

---

## 4. 아키텍처 원칙 부합 검토

| 원칙 | 부합 | 근거 |
|------|------|------|
| **P10 (SSOT)** | ✅ | "거래일 기준 오늘" 단일 소스 `get_chart_reference_trading_day()`로 수렴. 프론트 `_prevWeekday()`/`PRE_OPEN_PHASES` 독자 로직 제거. phase → 날짜 변환 경로 단일화. |
| **P16 (살아있는 경로)** | ✅ | `get_chart_reference_trading_day()`는 이미 `trade_history.py:626`·`telegram_bot.py:665`에서 살아있는 경로에 배선됨. `get_market_phase()`도 `get_engine_status()`/`build_initial_snapshot()` 양쪽 살아있는 경로. 신규 필드 추가도 동일 경로. |
| **P20 (폴백 금지)** | ✅ | 빈 문자열(엔진 기동 전)을 `getLocalToday()` 폴백으로 덮지 않음. 빈 문자열 그대로 전달 → 호출부 명시 처리. |
| **P21 (사용자 투명성)** | ✅ | 평일 공휴일에 프론트↔텔레그램 날짜 불일치 해결. 사용자가 "왜 화면과 텔레그램이 다르지?" 의문 제거. |
| **P22 (데이터 정합성)** | ✅ | 프론트↔텔레그램↔dailySummary가 동일 날짜 범위 사용 → 파생 데이터 일치. |
| **P23 (일관성)** | ✅ | `chart_reference_trading_day`를 `market_phase` dict 내부에 추가 → 기존 `is_nxt_only`/`krx_countdown` 파생 필드 패턴 일치. WS 이벤트 필드명 `snake_case` 유지. |
| **P24 (단순성)** | ✅ | 프론트 `_prevWeekday()`(8줄)·`PRE_OPEN_PHASES`(2줄) 제거. `getTradingToday()` 6줄 → 1줄. 백엔드 필드 추가 1줄. 전체 줄 수 감소. |
| **P25 (격리된 실패)** | ✅ | `get_market_phase()` 내 `get_chart_reference_trading_day()` 호출 실패 시 해당 필드만 빈 문자열, phase 문자열은 영향 없음. 프론트 `getTradingToday()` 빈 문자열 반환 시 호출부에서 차트 미표시 등 격리 처리. |

---

## 5. 위험도 산정

**위험도: 높음**

**근거**: 시간/날짜 의존 로직 변경. 프론트 `getTradingToday()`는 수익현황 페이지 날짜 범위 산정에 사용 → 표시 오류 시 사용자 의사결정 왜곡. 실전 모드에서 phase → 날짜 변환 오류는 매수 게이트 시간창 판정에 간접 영향 가능성 (단, 매수 게이트는 `engine_state.market_phase` 문자열 직접 참조하므로 본 수정과 무관 — phase 판정 자체는 변경 없음). "검증·관찰 계층 게이트" 표에서 "시간/날짜 의존 로직"은 명시적으로 "높음" 분류.

**비개발자용 3줄 요약**:
- **문제**: 평일 공휴일(예: 광복절) 새벽에 화면 수익현황과 텔레그램 손익이 다른 날짜 기준으로 표시됨 (화면은 주말만 건너뛰고, 텔레그램은 공휴일도 건너뜀).
- **해결**: 화면이 "오늘이 몇 일인지"를 백엔드에서 직접 받아 표시하도록 변경. 화면 내부의 독자적 날짜 계산 제거.
- **위험도**: 높음 — 날짜/시간 로직 변경이므로, 실전 적용 전 모의투자에서 평일 공휴일·월초·08:00 경계 등 특정 시간대 관찰 필요.

**게이트 적용** (위험도 높음 — 전 게이트 필수):
- **독립 검증**: 필수 — 별도 세션에서 커밋 + 태스크 파일 기반 충족도 검토
- **사전 롤백**: 필수 — 태스크 파일에 롤백 명령 + 증상 트리거 사전 정의
- **모의 관찰**: 필수 — 모의투자/dry-run 모드에서 2세션 관찰 (평일 공휴일·월초·08:00 경계 포함)
- **배포 후 모니터링**: 필수 — 실계좌 반영 후 3회 (장 시작/장 마감/특정 시간대) 화면↔텔레그램 숫자 비교

---

## 6. 영향 범위

### 6.1 백엔드 (수정 1파일, 참조 2파일)

| 파일 | 수정 내용 | 줄 수 |
|------|----------|-------|
| `backend/app/services/daily_time_scheduler.py` | `get_market_phase()` 반환 dict에 `chart_reference_trading_day` 필드 추가 | +2줄 |
| `backend/app/services/engine_lifecycle.py` | 수정 없음 (`get_engine_status()`가 `get_market_phase()` 호출 → 자동 포함) | — |
| `backend/app/services/engine_initial_data.py` | 수정 없음 (`build_initial_snapshot()`이 `get_market_phase()` 호출 → 자동 포함) | — |
| `backend/app/core/trading_calendar.py` | 수정 없음 (`get_chart_reference_trading_day()` 그대로 사용) | — |

### 6.2 프론트엔드 (수정 3파일)

| 파일 | 수정 내용 | 줄 수 |
|------|----------|-------|
| `frontend/src/utils/date.ts` | `getTradingToday()` 백엔드 값 직접 반환 · `isPreOpenPhase()` 백엔드 값 기반 전환 · `_prevWeekday()` 제거 · `PRE_OPEN_PHASES` 제거 | -10줄 +4줄 |
| `frontend/src/stores/uiStore.ts` | `UIState['marketPhase']` 타입에 `chart_reference_trading_day` 추가 · 초기값 `''` 설정 | +2줄 |
| `frontend/src/types/index.ts` | `EngineStatusPayload.market_phase` 타입에 `chart_reference_trading_day` 추가 | +1줄 |

### 6.3 테스트 (수정 2파일)

| 파일 | 수정 내용 |
|------|----------|
| `frontend/tests/utils/date.test.ts` | phase 문자열 mock → `chart_reference_trading_day` 값 mock 기반으로 전환. `_prevWeekday` 주말 스킵 테스트 제거, 백엔드 값 전달 테스트 추가. |
| `backend/tests/test_daily_time_scheduler.py` | `get_market_phase()` 반환에 `chart_reference_trading_day` 필드 존재 검증 추가. |

### 6.4 거래 로직 영향 — 없음

- 매수/매도 게이트는 `engine_state.market_phase` 문자열(`krx`/`nxt`) 직접 참조 → 본 수정(날짜 변환 경로)과 무관
- 주문 경로(`execute_buy()`/`execute_sell()`) 미접근 (P15)
- 손익금 계산 공식 미변경 — 날짜 범위 산정만 백엔드 값으로 일치

---

## 7. 리스크/롤백 기준

### 7.1 잠재 리스크

| 리스크 | 발생 조건 | 영향 | 완화 |
|--------|----------|------|------|
| 엔진 기동 전 빈 문자열 | WS 미연결 시 `chart_reference_trading_day=''` | 차트/수익현황 날짜 빈 → 표시 깨짐 가능 | 빈 문자열 시 호출부에서 차트 미표시 (P25 격리). initial-snapshot이 WS 연결 즉시 전송되므로 실제 발생 빈도 낮음. |
| 08:00 경계 지연 | phase 전환 시점과 `chart_reference_trading_day` 갱신 시점 차이 | 08:00~08:00:xx에 일시적 불일치 | `get_market_phase()`가 매 호출 시 `get_chart_reference_trading_day()` 실시간 산출 → 지연 없음 (캐시 아님). |
| 백엔드 캘린더 누락 | 휴장일 캘린더에 공휴일 미등록 | 백엔드도 잘못된 날짜 반환 | 기존 `get_chart_reference_trading_day()`의 이미 검증된 캘린더 사용 → 신규 리스크 아님. |

### 7.2 롤백 기준 (태스크 파일에 상세 정의 예정)

- **트리거**: 수익현황 페이지 날짜가 빈 문자열 표시 · 08:00 경계 이후에도 전일 기준 유지 · 텔레그램과 화면 날짜 불일치 지속
- **롤백 명령**: `git revert <구현 커밋 해시>` (태스크 파일에 해시 기재)
- **영향**: 프론트가 다시 독자 로직 사용 → 기존 상태(평일 공휴일 불일치)로 복귀. 거래 로직 무관.

---

## 8. 관련 파일

### 수정 대상
- `backend/app/services/daily_time_scheduler.py` — `get_market_phase()` (439-461줄)
- `frontend/src/utils/date.ts` — `getTradingToday()` · `isPreOpenPhase()` · `_prevWeekday()` · `PRE_OPEN_PHASES`
- `frontend/src/stores/uiStore.ts` — `UIState['marketPhase']` 타입 (36-43줄) · 초기값 (103줄)
- `frontend/src/types/index.ts` — `EngineStatusPayload.market_phase` (127-134줄)
- `frontend/tests/utils/date.test.ts` — 전면 갱신
- `backend/tests/test_daily_time_scheduler.py` — 필드 존재 검증 추가

### 참조 (수정 없음)
- `backend/app/core/trading_calendar.py` — `get_chart_reference_trading_day()` (384-411줄)
- `backend/app/services/engine_lifecycle.py` — `get_engine_status()` (173-211줄)
- `backend/app/services/engine_initial_data.py` — `build_initial_snapshot()` (22-93줄)
- `frontend/src/pages/profit-shared.ts` — `getTradingToday()`/`isPreOpenPhase()` 호출부 (시그니처 유지)
- `frontend/src/pages/profit-detail.ts` · `profit-detail-display.ts` · `profit-overview-mount.ts` · `profit-overview-date.ts` — `getTradingToday()` 호출부 (시그니처 유지)
