# 태스크 분할: 개장 전 거래일 판정 로직 수정 (테스트모드 한정)

> **다단계 워크플로우 2세션(태스크 분할)** — 본 파일은 1세션 설계(`architecture_trading_day_premarket_design.md`)를 태스크 단위로 분해.
> **작성일**: 2026-07-30
> **관련 커밋**: e085ef7 (1세션 설계 파일)
> **설계 파일**: `docs/architecture_trading_day_premarket_design.md`
> **범위**: 테스트모드 한정 (실전모드는 증권사 서버 SSOT → 수정 제외)

---

## 0. 사용자 결정 사항 (1세션 확정)

| # | 결정 사항 | 확정값 | 출처 |
|---|---|---|---|
| 1 | 수정 대상 모드 | 테스트모드 한정 (실전모드 제외) | 사용자 지시 |
| 2 | 개장 기준 시각 | 08:00 (NXT 프리마켓 개장) | 사용자 명세서 |
| 3 | 작업 단계 | 1세션 설계 → 2세션 태스크 분할 → 3세션 구현 | 사용자 지시 |
| 4 | 거래일 판정 SSOT | 백엔드 `market_phase` (WS로 프론트에 전달됨) — 프론트 독립 시간 계산 금지 | 1세션 설계 (P10) |
| 5 | `getLocalToday()` 유지 여부 | 유지 (표시 전용 2곳) + `getTradingToday()` 신규 분리 | 1세션 설계 (P24) |
| 6 | 백엔드 `get_current_trading_day()` 수정 | 제외 — 스냅샷 저장은 20:00 이후만 호출되므로 08:00 기준 누락이 실제 문제 없음 | 1세션 설계 (P24) |

### 결정 4 상세 (P10 SSOT)

- 거래일 판정은 시간 의존 개념. 백엔드 `calc_timebased_market_phase()`가 KST 시각 기반 단일 소스.
- 프론트가 `new Date().getHours() >= 8`로 독립 판정 시 브라우저 시간 오차·서버-클라이언트 시차로 드리프트 발생 위험.
- 프론트는 이미 WS `market-phase` 이벤트로 `uiStore.marketPhase`를 보관 중 → 이를 소비하여 판정.

### 결정 5 상세 (P24 단순성)

- `getLocalToday()`: 캘린더 날짜 (시간 무관) — 사용처 7, 8번(표시 전용) 유지.
- `getTradingToday()`: 거래일 기준 날짜 (phase 기반) — 사용처 1~6번 전환.
- 단일 함수에 `boolean includeTime` 인자 추가보다 용도 분리가 명확 (호출부에서 의도 드러남).

---

## 1. 코드 조사 결과 (2세션 — 설계 대비 검증)

### 1.1 설계 대비 코드 위치 검증 (전부 일치)

| 설계 기재 | 실제 위치 | 비고 |
|---|---|---|
| `frontend/src/utils/date.ts` `getLocalToday()` 6줄 | 정확 | 5-9줄, 시간 미고려 캘린더 날짜 |
| `frontend/src/utils/date.ts` `getLocalMonthStart()` 12줄 | 정확 | 11-15줄, 동일 이슈 (월 경계일) |
| `profit-shared.ts:176` `getLocalToday()` | 정확 | `updateSummaryCards` 당일 카드 |
| `profit-shared.ts:604` `getLocalToday()` | 정확 | `renderAccountVals` 당일 집계 |
| `profit-detail-display.ts:111` `getLocalToday().slice(0,7)` | 정확 | 당월 드릴다운 yearMonth |
| `profit-overview-mount.ts:278` `getLocalToday()` | 정확 | 빠른 범위 기본값 |
| `profit-overview-date.ts:56` `getLocalToday()` + `getLocalMonthStart()` | 정확 | `defaultDateRange` from/to 동일 라인 |
| `profit-detail.ts:132` `getLocalToday()` | 정확 | 당월 범위 monthStart/monthEnd |
| `canvas-profit-chart.ts:154` `getLocalToday()` | 정확 | 차트 헤더 오늘 표시 (유지) |
| `canvas-profit-chart.ts:155` `getLocalMonthStart()` | 정확 | 차트 헤더 월시작 (전환) |
| `sell-position.ts:92` `getLocalToday()` | 정확 | 당일 색상 강조 (유지) |

### 1.2 `getLocalToday()` / `getLocalMonthStart()` 사용처 전체 (grep 검증)

| # | 파일:라인 | 함수 | 용도 | 전환 여부 |
|---|---|---|---|---|
| 1 | `profit-shared.ts:176` | `updateSummaryCards` | 당일 카드 dateFrom/dateTo | **전환** |
| 2 | `profit-shared.ts:604` | `renderAccountVals` | 당일 집계 computeTodayAggregates | **전환** |
| 3 | `profit-detail-display.ts:111` | 당월 드릴다운 | yearMonth 추출 | **전환** |
| 4 | `profit-overview-mount.ts:278` | 빠른 범위 기본값 | `to: today` | **전환** |
| 5 | `profit-overview-date.ts:56` | `defaultDateRange` | from/to 동일 라인 | **전환** (from은 `getTradingMonthStart`, to는 `getTradingToday`) |
| 6 | `profit-detail.ts:132` | 당월 범위 | monthStart/monthEnd | **전환** |
| 7 | `canvas-profit-chart.ts:154` | 차트 헤더 | 오늘 표시 | **유지** (표시 전용) |
| 8 | `canvas-profit-chart.ts:155` | 차트 헤더 | 월시작 표시 | **전환** (`getTradingMonthStart`) |
| 9 | `sell-position.ts:92` | 당일 색상 강조 | 시각 강조만 | **유지** (표시 전용) |

> **정정**: 설계 1.2절은 9곳으로 기재했으나, `getLocalMonthStart()` 사용처 2곳(`profit-overview-date.ts:56`, `canvas-profit-chart.ts:155`)이 별도 집계에 포함되지 않았음. 본 태스크 파일에서 명시적으로 포함 (P10 SSOT — 누락 방지).
> **최종 전환 대상**: `getLocalToday()` 6곳 + `getLocalMonthStart()` 2곳 = **총 8곳 전환**.

### 1.3 `uiStore.marketPhase` 상태 검증

- **초기값** (`uiStore.ts:103`): `{ krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false }`
- **갱신 경로**: `binding.ts:201` `market-phase` WS 이벤트 → `applyMarketPhase()` (`uiStore.ts:263`)
- **접근 패턴**: `uiStore.getState().marketPhase` (기존 `sector-settings.ts:161-162, 236, 258, 375` 등 다수 사용)
- **타입**: `types/index.ts:126` `market_phase?: { krx: string; nxt: string; ... }`

### 1.4 기존 phase 기반 분기 패턴 (재사용 대상)

**파일**: `frontend/src/pages/sector-settings.ts:119`

```typescript
const REGULAR_PHASES = new Set(['정규장', '시가 동시호가', '종가 동시호가', '메인마켓'])
// 133줄: const isRegular = REGULAR_PHASES.has(marketPhase.krx) || REGULAR_PHASES.has(marketPhase.nxt)
```

→ `PRE_OPEN_PHASES` 신규 상수가 동일 패턴 준수 (P23 일관성).

### 1.5 기존 테스트 현황

- `frontend/tests/utils/order-block-status.test.ts`: `makeCleanUiState()` 헬퍼 패턴 존재 (UIState 기본값 구성)
- **`getTradingToday` / `getTradingMonthStart` 테스트 없음** → 신규 추가 필요 (태스크 F-3)
- 테스트 파일 위치: `frontend/tests/utils/date.test.ts` (신규 생성)

---

## 2. 태스크 분할

> **원칙**: 프론트엔드 전용 (백엔드 수정 없음). 신규 함수(F-1) → 사용처 전환(F-2) → 테스트(F-3) → 검증(F-4) 순서.
> 각 태스크는 독립 커밋 단위. 태스크 완료 시마다 검증 게이트 통과 필수.

### 2.1 프론트엔드 태스크 (F-1 ~ F-4)

#### F-1: `date.ts` 신규 함수 + 상수 추가

- **파일**: `frontend/src/utils/date.ts` (기존 파일 확장)
- **변경**:
  - import 추가: `import { uiStore } from '../stores/uiStore'`
  - 상수 추가:
    ```typescript
    /** 개장 전(08:00 NXT 프리마켓 전) phase 집합 — 당일 거래일 미활성.
     *  P23 일관성 — sector-settings.ts REGULAR_PHASES 패턴 재사용.
     *  P10 SSOT — phase 판정은 백엔드 calc_timebased_market_phase()가 단일 소스. */
    const PRE_OPEN_PHASES = new Set(['장개시전', '휴장일'])

    /** 장마감 후(20:00 이후) phase — 다음 거래일로 전환.
     *  백엔드 get_current_trading_day()의 _NXT_CLOSE_HOUR=20 기준과 일치 (P10). */
    const POST_CLOSE_PHASE = '장마감'
    ```
  - 보조 함수 추가 (모듈 프라이빗):
    ```typescript
    function _prevCalendarDay(yyyyMmDd: string): string {
      const d = new Date(yyyyMmDd + 'T00:00:00')
      d.setDate(d.getDate() - 1)
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    }

    function _nextCalendarDay(yyyyMmDd: string): string {
      const d = new Date(yyyyMmDd + 'T00:00:00')
      d.setDate(d.getDate() + 1)
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    }
    ```
  - 신규 함수 2개 추가:
    ```typescript
    /** 거래일 기준 오늘 날짜 (YYYY-MM-DD).
     *  - 08:00 이전(장개시전/휴장일): 전일 반환 (개장 전에는 오늘이 거래일에 미포함)
     *  - 08:00~20:00(장중): 오늘 반환
     *  - 20:00 이후(장마감): 다음 거래일 반환 (백엔드 get_current_trading_day()와 일치)
     *  P10 SSOT — uiStore.marketPhase 기반 판정, 프론트 독립 시간 계산 금지. */
    export function getTradingToday(): string {
      const phase = uiStore.getState().marketPhase
      const calendarToday = getLocalToday()
      if (phase.krx === POST_CLOSE_PHASE && phase.nxt === POST_CLOSE_PHASE) {
        return _nextCalendarDay(calendarToday)
      }
      if (PRE_OPEN_PHASES.has(phase.krx) && PRE_OPEN_PHASES.has(phase.nxt)) {
        return _prevCalendarDay(calendarToday)
      }
      return calendarToday
    }

    /** 거래일 기준 이번 달 시작일 (YYYY-MM-01).
     *  getTradingToday() 기준 월의 1일 — 월 경계일 00:00~08:00에 전월 1일 반환. */
    export function getTradingMonthStart(): string {
      return getTradingToday().slice(0, 7) + '-01'
    }
    ```
- **파일 헤더 주석 업데이트**: 3줄 "profit-shared/sell-position/..." 공유 문구에 신규 함수 추가 언급 (P23 — 주석-코드 불일치 금지)
- **P10 SSOT**: phase 판정은 `uiStore.marketPhase` 단일 소스
- **P23 일관성**: `REGULAR_PHASES` 패턴 재사용, `camelCase` 네이밍, "거래일" 표준 용어
- **P20 폴백 금지**: 초기값 '장마감'은 합리적 기본값 (폴백 아님), `PRE_OPEN_PHASES` 외 phase → 장중으로 간주는 명시적 기본값 정의
- **P25 격리된 실패**: `uiStore.getState()` 읽기 실패 시 초기값 반환 → 앱 중단 없음
- **검증**: `cd frontend && npm run typecheck`
- **커밋**: `feat: getTradingToday/getTradingMonthStart 거래일 기준 날짜 추가 (phase 기반)`

#### F-2: 사용처 8곳 전환

- **대상**: `getLocalToday()` 6곳 + `getLocalMonthStart()` 2곳
- **변경 내역**:

| # | 파일:라인 | 변경 | import 추가 |
|---|---|---|---|
| 1 | `profit-shared.ts:176` | `getLocalToday()` → `getTradingToday()` | `getTradingToday` 추가 |
| 2 | `profit-shared.ts:604` | `getLocalToday()` → `getTradingToday()` | (1에서 이미 추가) |
| 3 | `profit-detail-display.ts:111` | `getLocalToday().slice(0,7)` → `getTradingToday().slice(0,7)` | `getTradingToday` 추가 |
| 4 | `profit-overview-mount.ts:278` | `getLocalToday()` → `getTradingToday()` | `getTradingToday` 추가 (기존 `getLocalToday` import 제거 또는 유지 — 사용처 확인) |
| 5 | `profit-overview-date.ts:56` | `getLocalMonthStart()` → `getTradingMonthStart()`, `getLocalToday()` → `getTradingToday()` | `getTradingMonthStart`, `getTradingToday` 추가 |
| 6 | `profit-detail.ts:132` | `getLocalToday()` → `getTradingToday()` | `getTradingToday` 추가 |
| 7 | `canvas-profit-chart.ts:154` | **유지** (`getLocalToday()`) | 변경 없음 |
| 8 | `canvas-profit-chart.ts:155` | `getLocalMonthStart()` → `getTradingMonthStart()` | `getTradingMonthStart` 추가 (기존 `getLocalMonthStart` import는 154줄에서 여전히 사용하므로 유지) |

- **import 정리 원칙** (P23 일관성 + P24 단순성):
  - 각 파일에서 `getLocalToday`/`getLocalMonthStart`가 더 이상 사용되지 않으면 import에서 제거
  - 여전히 사용되면(예: `canvas-profit-chart.ts` 154줄) 유지
  - 사용처 7, 8번(`sell-position.ts:92`, `canvas-profit-chart.ts:154`)은 표시 전용이므로 `getLocalToday()` 유지
- **P21 사용자 투명성**: 개장 전에 당일 카드가 전일 마감 기준으로 표시되어 사용자가 "왜 0/0%인지" 혼란 제거
- **P22 데이터 정합성**: 프론트 dateFrom/dateTo와 백엔드 스냅샷 저장 날짜(20:00 기준)가 정합
- **검증**: `cd frontend && npm run typecheck` + `cd frontend && npm run build`
- **커밋**: `refactor: 기간 카드 날짜를 거래일 기준으로 전환 (8곳)`

#### F-3: `getTradingToday` / `getTradingMonthStart` 단위 테스트

- **파일**: `frontend/tests/utils/date.test.ts` (신규 생성)
- **테스트 케이스**:
  1. **개장 전 (08:00 이전)**: `marketPhase = { krx: '장개시전', nxt: '장개시전' }` → `getTradingToday()`가 전일 반환
  2. **휴장일**: `marketPhase = { krx: '휴장일', nxt: '휴장일' }` → `getTradingToday()`가 전일 반환
  3. **장중 (정규장)**: `marketPhase = { krx: '정규장', nxt: '정규장' }` → `getTradingToday()`가 오늘 반환
  4. **장마감 후 (20:00 이후)**: `marketPhase = { krx: '장마감', nxt: '장마감' }` → `getTradingToday()`가 다음 거래일(다음 캘린더 일) 반환
  5. **프리마켓 (08:00~08:50)**: `marketPhase = { krx: '장전 대기', nxt: '프리마켓' }` → `getTradingToday()`가 오늘 반환 (PRE_OPEN_PHASES 외)
  6. **초기값 (WS 수신 전)**: `marketPhase = { krx: '장마감', nxt: '장마감' }` (초기값) → 다음 거래일 반환 (합리적 기본값)
  7. **`getTradingMonthStart()` 월 경계일**: 개장 전 phase + 캘린더 날짜가 월 1일 → 전월 1일 반환
  8. **`getTradingMonthStart()` 장중**: 장중 phase + 캘린더 날짜가 월 15일 → 당월 1일 반환
- **테스트 패턴** (기존 `order-block-status.test.ts`의 `makeCleanUiState()` 패턴 참고):
  ```typescript
  import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
  import { getTradingToday, getTradingMonthStart, getLocalToday } from '../../src/utils/date'
  import { uiStore } from '../../src/stores/uiStore'
  import type { UIState } from '../../src/stores/uiStore'

  function setMarketPhase(krx: string, nxt: string): void {
    const cur = uiStore.getState()
    uiStore.setState({ ...cur, marketPhase: { ...cur.marketPhase, krx, nxt } })
  }

  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })
  ```
- **가짜 시간 설정**: `vi.setSystemTime(new Date('2026-07-30T07:00:00+09:00'))` (개장 전), `new Date('2026-07-30T10:00:00+09:00')` (장중), `new Date('2026-07-30T21:00:00+09:00')` (장마감 후)
- **P16 살아있는 경로**: 테스트가 실제 `getTradingToday()` 호출 경로 검증
- **검증**: `cd frontend && npm run test` (기존 116 tests + 신규 8 tests = 124 tests)
- **커밋**: `test: getTradingToday/getTradingMonthStart phase 기반 분기 테스트 추가`

#### F-4: 전체 검증 게이트

- **프론트엔드**:
  - `cd frontend && npm run typecheck` (`tsc --noEmit`)
  - `cd frontend && npm run test` (vitest, 116 + F-3 신규 tests)
  - `cd frontend && npm run build` (`tsc -b && vite build`)
- **백엔드**: 해당 없음 (백엔드 수정 없음)
- **DB**: 해당 없음 (스키마 변경 없음)
- **커밋**: 검증 태스크는 커밋 없음 (각 태스크 커밋 시 검증 포함)

---

## 3. 태스크 의존성 그래프

```
F-1 (date.ts 신규 함수 + 상수) → F-2 (사용처 8곳 전환)
                                     ↓
                                F-3 (단위 테스트)
                                     ↓
                                F-4 (전체 검증)
```

- **직렬 필수**: F-1 → F-2 (신규 함수가 있어야 사용처 전환 가능)
- **F-3은 F-1 직후 가능**: 테스트는 함수 자체 검증이므로 F-2와 독립. 단, F-2에서 발생할 수 있는 회귀를 포함하려면 F-2 이후 권장.
- **F-4는 모든 태스크 완료 후**: 최종 회귀 검증

---

## 4. 구현 순서 권장 (단일 세션)

### 4.1 단일 세션 완료 시 (권장 — 규모 작음)

```
F-1 → F-2 → F-3 → F-4
```

> 본 태스크는 프론트엔드 신규 함수 2개 + 사용처 8곳 전환 + 테스트 8케이스로 규모가 작음. 단일 세션 완료 권장.
> 이전 다단계 워크플로우(기초자산 분모 — 백엔드 7 + 프론트 7 = 14 태스크)와 비교 시 약 1/3 규모.

### 4.2 분할 필요 시 (사용자 결정)

- **3세션 (구현)**: F-1 + F-2 + F-3 + F-4 (단일 세션 권장이나, 사용자가 분할 원할 시 F-1/F-2를 3세션, F-3/F-4를 4세션으로 분할 가능)

---

## 5. 아키텍처 원칙 점검 (구현 완료 후 필수)

| 원칙 | 태스크 | 점검 항목 |
|---|---|---|
| P10 (SSOT) | F-1 | 거래일 판정 SSOT = `uiStore.marketPhase` (백엔드 `calc_timebased_market_phase()`). 프론트 독립 시간 계산 금지. |
| P16 (살아있는 경로) | F-1, F-2 | `getTradingToday()`가 6곳 사용처에서 실제 호출. `uiStore.marketPhase`는 WS + 30초 타이머로 갱신 → dead code 아님. |
| P20 (폴백 금지) | F-1 | 초기값 '장마감'은 합리적 기본값 (폴백 아님). `PRE_OPEN_PHASES` 외 phase → 장중 간주는 명시적 기본값 정의. |
| P21 (사용자 투명성) | F-2 | 개장 전 당일 카드가 전일 마감 기준 표시 → "왜 0/0%인지" 혼란 제거. |
| P22 (데이터 정합성) | F-2 | 프론트 dateFrom/dateTo와 백엔드 스냅샷 저장 날짜(20:00 기준) 정합. 08:00/20:00 경계 일치. |
| P23 (일관성) | F-1, F-2 | `PRE_OPEN_PHASES` = `REGULAR_PHASES` 패턴 재사용. `camelCase` 네이밍. "거래일" 표준 용어. 파일 헤더 주석 일치. |
| P24 (단순성) | F-1 | 신규 코드 ~25줄 (함수 2 + 보조 2 + 상수 2). 기존 WS 인프라 재사용. 대안 A/B 기각 (설계 4.2 참고). |
| P25 (격리된 실패) | F-1 | `uiStore.getState()` 읽기 실패 시 초기값 반환 → 앱 중단 없음. 예상치 못한 phase → 장중 간주 (안전 측). |

### 코드 제거 규칙 점검 (F-2)

- `getLocalToday`/`getLocalMonthStart` import 제거 시 해당 파일에서 더 이상 사용되지 않는지 확인 (grep 재검증)
- 제거된 import를 참조하는 주석 없는지 확인 (P23 주석-코드 불일치 금지)
- `getLocalToday()`/`getLocalMonthStart()` 함수 자체는 유지 (사용처 7, 8번 및 `getTradingToday()` 내부에서 사용) — 함수 제거 아님

---

## 6. 후순위 (본 태스크 범위 외)

- **백엔드 `get_current_trading_day()` 08:00 기준 반영**: 현재 20:00 기준만 반영. 스냅샷 저장은 20:00 이후만 호출되므로 실제 문제 없으나, 향후 백엔드에서 당일 거래일 판정이 필요한 다른 용도 추가 시 검토 (설계 1.5절).
- **실전모드 거래일 판정**: 실전모드는 증권사 서버 SSOT이므로 앱이 데이터 수신만 담당. 프론트엔드 날짜 로직 수정이 실전모드에 미치는 영향은 데이터 표시 범위뿐이나, 사용자 결정 1에 따라 제외.
- **브라우저 시간이 KST가 아닌 경우**: `getLocalToday()` 캘린더 날짜 오차 (기존 이슈). 본 수정 범위 아님 — `getTradingToday()`의 phase 판정은 백엔드 KST 기반이므로 영향 없음.

---

## 7. 다음 세션 인계 사항

1. 본 태스크 파일의 F-1 ~ F-4 순서대로 구현 (단일 세션 권장)
2. F-1에서 `import { uiStore } from '../stores/uiStore'` 추가 — `date.ts`에 첫 uiStore 의존성 (순환 참조 위험 없음 — `uiStore`는 `date.ts`를 import하지 않음)
3. F-2에서 사용처 8곳 전환 후 각 파일의 import 정리 (사용되지 않는 `getLocalToday`/`getLocalMonthStart` import 제거)
4. F-3에서 `vi.setSystemTime()`으로 가짜 시간 설정 — `getLocalToday()` 내부 `new Date()`와 `uiStore.marketPhase` 양쪽 검증
5. 각 태스크 완료 시 검증 게이트 통과 후 커밋 (코드만, HANDOVER.md 제외)
6. 전체 완료 후 HANDOVER.md 갱신 + 세션 완료 보고 (규칙 0-6-2/0-7)
7. **정정 사항 반영**: 설계 1.2절 9곳 → 본 파일 1.2절 9곳(명시적 8곳 전환 + 1곳 함수 정의) + `getLocalMonthStart()` 2곳 별도 집계 (1.2절 표 참고)
