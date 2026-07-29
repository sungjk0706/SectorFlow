# 설계: 개장 전 거래일 판정 로직 수정 (테스트모드 한정)

> **다단계 워크플로우 1세션(설계)** — 본 파일은 설계 산출물. 다음 세션에서 태스크 파일(`architecture_trading_day_premarket_tasks.md`)로 분해 예정.
> **작성일**: 2026-07-30
> **범위**: 테스트모드 한정 (실전모드는 증권사 서버 SSOT → 수정 제외)
> **관련 문서**: `docs/architecture_base_asset_denominator_design.md`, `docs/krx_nxt_market_hours.md`

---

## 0. 사용자 결정 사항 (1세션)

| # | 결정 사항 | 확정값 | 출처 |
|---|---|---|---|
| 1 | 수정 대상 모드 | 테스트모드 한정 (실전모드 제외) | 사용자 지시 |
| 2 | 개장 기준 시각 | 08:00 (NXT 프리마켓 개장) | 사용자 명세서 |
| 3 | 작업 단계 | 설계까지만 수행, 태스크 파일은 다음 세션 | 사용자 지시 |

### 결정 상세

- **실전모드 제외 근거**: 실전모드는 증권사 서버가 SSOT이므로 앱은 데이터 수신만 담당. 데이터 보관·계산 안 함 → 프론트엔드 날짜 로직 수정이 실전모드에 미치는 영향은 데이터 표시 범위뿐이나, 사용자가 명시적으로 제외 지시.
- **08:00 기준 근거**: NXT 프리마켓 개장 시각(`NXT_PREMARKET_START = (8, 0)` — `daily_time_scheduler.py:34`). 이 시각부터 오늘(N일)이 거래일로 활성화되어 실시간 시세 반영 시작.

---

## 1. 코드 조사 결과

### 1.1 현재 `getLocalToday()` 구현

**파일**: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/utils/date.ts" />

```typescript
export function getLocalToday(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
```

- `new Date()` = 브라우저 로컬 시간 (사용자 PC KST 전제)
- **시간 미고려**: 오전 00:00~23:59 모두 N일 반환
- **문제**: 오전 07:00에 호출 시 N일 반환 → 당일 카드가 N일 기준 동작 (N일 매도 없음 → 0/0% 표시)

### 1.2 `getLocalToday()` 사용처 9곳

| # | 파일:라인 | 용도 | 개장 전 영향 |
|---|---|---|---|
| 1 | `profit-shared.ts:176` | `updateSummaryCards` 당일 카드 `dateFrom/dateTo` | **높음** — N일 기준 당일 카드 |
| 2 | `profit-shared.ts:604` | `renderAccountVals` 당일 집계 (`computeTodayAggregates`) | **높음** — N일 매수/매도 집계 |
| 3 | `profit-detail-display.ts:111` | 당월 드릴다운 `yearMonth` 추출 | 중간 — 월 경계일 00:00~08:00에 전월로 표시되어야 하나 현재 N일 월로 표시 |
| 4 | `profit-overview-mount.ts:278` | 빠른 날짜 범위 기본값 | 중간 — `to: today`가 N일로 설정 |
| 5 | `profit-overview-date.ts:56` | `defaultDateRange()` `to` 값 | 중간 — 동일 |
| 6 | `profit-detail.ts:132` | 당월 범위 `monthStart/monthEnd` | 중간 — 월 경계일 영향 |
| 7 | `canvas-profit-chart.ts:154` | 차트 헤더 오늘 표시 | 낮음 — 표시 전용 |
| 8 | `sell-position.ts:92` | 당일 매수 포지션 색상 강조 | 낮음 — 시각 강조만 |
| 9 | `utils/date.ts:6` | 함수 정의 자체 | — |

### 1.3 백엔드 장 시간대 판정 SSOT (재사용 후보)

**파일**: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" />

#### 1.3.1 시간표 상수 (20-40줄)
```python
NXT_PREMARKET_START = (8, 0)    # 08:00 프리마켓 시작
NXT_AFTERMARKET_END = (20, 0)   # 20:00 애프터마켓 종료 → 장마감
```

#### 1.3.2 `calc_timebased_market_phase()` (112-200줄)
- KST 시각 기반 KRX/NXT 장 상태 산정
- 반환: `{"krx": str, "nxt": str}` (예: `{"krx": "장개시전", "nxt": "장개시전"}`)
- 00:00~08:00 → `"장개시전"` (양쪽 모두)
- 08:00~08:50 → `{"krx": "장전 대기", "nxt": "프리마켓"}`
- 20:00~24:00 → `"장마감"` (양쪽)

#### 1.3.3 `_kst_now()` (466-467줄) + `_KST` (`constants.py:9`)
```python
_KST = timezone(timedelta(hours=9))
def _kst_now() -> datetime:
    return datetime.now(_KST)
```

### 1.4 프론트엔드 `market_phase` 수신 경로 (이미 구축됨)

**핵심 발견**: 프론트엔드는 이미 백엔드 `market_phase`를 WS로 수신하여 `uiStore.marketPhase`에 보관.

| 단계 | 위치 | 내용 |
|------|------|------|
| 백엔드 산정 | `daily_time_scheduler.py:calc_timebased_market_phase()` | KST 시각 기반 phase 산정 |
| 백엔드 push | `ws.py:142` `engine-status` 이벤트 | `market_phase` 필드 포함 |
| 프론트 수신 | `binding.ts:201` `pricesClient.onEvent('market-phase', ...)` | `applyMarketPhase()` 호출 |
| 프론트 저장 | `uiStore.ts:263` `applyMarketPhase()` | `uiStore.marketPhase` 갱신 |
| 프론트 타입 | `types/index.ts:126` | `market_phase?: { krx: string; nxt: string; ... }` |
| 초기값 | `uiStore.ts:103` | `{ krx: '장마감', nxt: '장마감', ... }` |
| 기존 사용처 | `sector-settings.ts:119` `REGULAR_PHASES` | 정규장 판정에 이미 phase 문자열 사용 |

**기존 phase 기반 분기 패턴** (`sector-settings.ts:127-135`):
```typescript
const REGULAR_PHASES = new Set(['정규장', '시가 동시호가', '종가 동시호가', '메인마켓'])
function _applyMarketPhaseActive(marketPhase: {...}): void {
  const isNxtOnly = marketPhase.is_nxt_only === true
  const isRegular = REGULAR_PHASES.has(marketPhase.krx) || REGULAR_PHASES.has(marketPhase.nxt)
  // ...
}
```

→ **이미 phase 문자열 집합 기반 분기 패턴이 존재**. 당일 거래일 판정에 동일 패턴 재사용 가능 (P23 일관성).

### 1.5 백엔드 `get_current_trading_day()` (참고 — 수정 대상 아님)

**파일**: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/core/trading_calendar.py" /> 344-370줄

```python
def get_current_trading_day() -> date:
    now = datetime.now(_KST)
    today = now.date()
    if now.hour >= _NXT_CLOSE_HOUR:  # 20:00 이후 → 다음 거래일
        return _next_trading_day(today)
    if is_trading_day(today):
        return today  # ← 08:00 전이어도 N일 반환
    return _next_trading_day(today)
```

- 20:00 기준은 반영되어 있으나 **08:00 기준 미반영** — 오전 07:00에 N일 반환
- **본 설계 범위 아님**: 백엔드는 스냅샷 저장(`_save_daily_snapshot`)에만 사용하며, 이는 장마감 후(20:00 이후)에만 호출되므로 08:00 기준 누락이 실제 문제를 일으키지 않음
- 프론트엔드 문제가 아니므로 본 세션에서 수정 제외 (P24 단순성 — 불필요한 수정 금지)

---

## 2. 근본 원인 분석

### 2.1 근본 원인

`getLocalToday()`가 **시간을 전혀 고려하지 않고 캘린더 날짜만 반환**. 거래일 판정은 "장 개장 여부"라는 시간 의존 개념인데, 날짜 유틸이 시간 차원을 누락.

### 2.2 파생 영향

- 당일 카드: 오전 7시에 N일 매도 집계 → 0건 → pnl=0, rate=0 (실제로는 전일 N-1 마감 기준이어야)
- 5거래일 카드: `getRecent5TradingDays(dailySummary)`가 dailySummary에서 추출하므로 N일 매도 없으면 자연히 N-1~N-5 → 우연히 맞으나 명시적 로직 아님
- 당월 카드: 월 경계일 00:00~08:00에 신월로 표시 (예: 7/1 07:00 → 7월 당월 카드, 실제로는 6월 마감 기준이어야)
- 당일 집계(`computeTodayAggregates`): N일 매수/매도 0건으로 집계

### 2.3 우연히 정상 동작하는 부분 (수정 불필요)

- `get_base_asset_for_period()` (`stock_tables.py:223`): `WHERE date < date_from` → 항상 전일 스냅샷만 조회 → 분모 자체는 개장 전에도 N-1 기준 정상 추출 ✓
- `get_previous_trading_day()` (`trading_calendar.py:293`): 시간 무관, 항상 N-1 반환 → `/api/trade-history/prev-trading-day` 정상 ✓

---

## 3. 근본 수정안 설계

### 3.1 설계 원칙: 백엔드 SSOT 재사용 (P10)

**핵심 결정**: 거래일 판정의 SSOT는 백엔드 `market_phase` (이미 WS로 프론트에 전달됨). 프론트엔드가 시간을 독립 계산하지 않고 **`uiStore.marketPhase`를 소비**하여 당일 거래일 활성화 여부 판정.

**근거**:
- P10 (SSOT): 시간 기반 장 상태 판정은 백엔드 `calc_timebased_market_phase()`가 단일 소스. 프론트가 `new Date().getHours() >= 8`로 독립 판정하면 두 번째 소스 발생 → 드리프트 위험 (예: 브라우저 시간 오차, 서버-클라이언트 시차)
- P23 (일관성): `sector-settings.ts`가 이미 `marketPhase` 기반 분기 패턴 사용. 동일 패턴으로 당일 거래일 판정 구현
- P24 (단순성): 프론트 시간 계산 로직 신규 도입 대신 기존 WS 인프라 재사용 → 코드 증가 최소

### 3.2 phase 문자열 기반 당일 거래일 활성화 판정

**개장 전(당일 미활성) phase 집합** (08:00 이전 + 휴장일):
- `"장개시전"` (00:00~08:00, 양쪽 모두)
- `"휴장일"` (주말/공휴일)

**개장 후(당일 활성) phase 집합** (08:00~20:00):
- `"프리마켓"`, `"장전 대기"`, `"장전 시간외"`, `"동시호가 접수"`, `"시가 동시호가"`
- `"정규장"`, `"종가 동시호가"`, `"체결 정산"`, `"장후 시간외"`
- `"시간외 종가매매 종료 + 시간외 단일가매매 개시"`, `"장 종료"`
- `"정규장 준비"`, `"메인마켓"`, `"조기 마감"`, `"단일가 매매"`, `"애프터마켓"`

**장마감 후(다음 거래일로 전환) phase**:
- `"장마감"` (20:00~24:00) — 이미 `get_current_trading_day()`가 20:00 기준으로 다음 거래일 전환하므로 프론트도 동일하게 처리

### 3.3 신규 함수 설계: `getTradingToday()`

**파일**: `frontend/src/utils/date.ts` (기존 파일 확장)

```typescript
import { uiStore } from '../stores/uiStore'

/** 개장 전(08:00 NXT 프리마켓 전) phase 집합 — 당일 거래일 미활성.
 *  P23 일관성 — sector-settings.ts REGULAR_PHASES 패턴 재사용.
 *  P10 SSOT — phase 판정은 백엔드 calc_timebased_market_phase()가 단일 소스. */
const PRE_OPEN_PHASES = new Set(['장개시전', '휴장일'])

/** 장마감 후(20:00 이후) phase — 다음 거래일로 전환.
 *  백엔드 get_current_trading_day()의 _NXT_CLOSE_HOUR=20 기준과 일치 (P10). */
const POST_CLOSE_PHASE = '장마감'

/** 거래일 기준 오늘 날짜 (YYYY-MM-DD).
 *  - 08:00 이전(장개시전/휴장일): 전일 반환 (개장 전에는 오늘이 거래일에 미포함)
 *  - 08:00~20:00(장중): 오늘 반환
 *  - 20:00 이후(장마감): 다음 거래일 반환 (백엔드 get_current_trading_day()와 일치)
 *  P10 SSOT — uiStore.marketPhase 기반 판정, 프론트 독립 시간 계산 금지. */
export function getTradingToday(): string {
  const phase = uiStore.getState().marketPhase
  const calendarToday = getLocalToday()  // 캘린더 날짜 (시간 무관)

  // 장마감 후(20:00~) → 다음 거래일 (백엔드와 일치)
  if (phase.krx === POST_CLOSE_PHASE && phase.nxt === POST_CLOSE_PHASE) {
    return _nextCalendarDay(calendarToday)
  }
  // 개장 전(08:00 전 또는 휴장일) → 전일
  if (PRE_OPEN_PHASES.has(phase.krx) && PRE_OPEN_PHASES.has(phase.nxt)) {
    return _prevCalendarDay(calendarToday)
  }
  // 장중(08:00~20:00) → 오늘
  return calendarToday
}
```

**보조 함수** (동일 파일):
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

### 3.4 `getLocalToday()` 유지 여부

**유지 (별도 함수)**: `getLocalToday()`는 "캘린더 오늘" (시간 무관) 의미로 유지. 용도별 분리:
- `getLocalToday()`: 캘린더 날짜 (표시 전용, 당일 색상 강조 등 시간 무관 용도) — 사용처 7, 8번 유지
- `getTradingToday()`: 거래일 기준 오늘 (당일 카드, 당일 집계, 당월 범위 등 시간 의존 용도) — 사용처 1~6번 전환

**P24 단순성**: 두 함수로 용도 분리. 단일 함수에 시간 인자 추가보다 명확 (호출부에서 의도 드러남).

### 3.5 사용처 전환 매핑

| # | 파일:라인 | 현재 | 전환 | 비고 |
|---|---|---|---|---|
| 1 | `profit-shared.ts:176` | `getLocalToday()` | `getTradingToday()` | 당일 카드 dateFrom/dateTo |
| 2 | `profit-shared.ts:604` | `getLocalToday()` | `getTradingToday()` | 당일 집계 |
| 3 | `profit-detail-display.ts:111` | `getLocalToday().slice(0,7)` | `getTradingToday().slice(0,7)` | 당월 드릴다운 yearMonth |
| 4 | `profit-overview-mount.ts:278` | `getLocalToday()` | `getTradingToday()` | 빠른 범위 기본값 |
| 5 | `profit-overview-date.ts:56` | `getLocalToday()` | `getTradingToday()` | defaultDateRange to |
| 6 | `profit-detail.ts:132` | `getLocalToday()` | `getTradingToday()` | 당월 범위 |
| 7 | `canvas-profit-chart.ts:154` | `getLocalToday()` | **유지** | 표시 전용 (오늘 표시) |
| 8 | `sell-position.ts:92` | `getLocalToday()` | **유지** | 당일 색상 강조 (표시 전용) |

> 7, 8번은 "캘린더 오늘" 표시가 사용자 기대에 부합 (오전 7시에도 "오늘 7/30" 표시는 자연스러움). 거래일 기준이 필요 없으므로 유지.

### 3.6 `getLocalMonthStart()` 연쇄 수정 검토

`getLocalMonthStart()` (`date.ts:12`)도 동일 이슈: 월 경계일 00:00~08:00에 신월 반환.

**결정**: `getTradingMonthStart()` 신규 추가 (3.3 패턴 동일). 사용처: `profit-overview-date.ts:56` (`defaultDateRange` from), `canvas-profit-chart.ts:155`.

```typescript
export function getTradingMonthStart(): string {
  const tradingToday = getTradingToday()
  return tradingToday.slice(0, 7) + '-01'
}
```

---

## 4. 아키텍처 원칙 부합 검토

### 4.1 P10 (SSOT) — 부합 ✓

- **거래일 판정 SSOT**: 백엔드 `calc_timebased_market_phase()` → WS `market-phase` → `uiStore.marketPhase` → `getTradingToday()`. 프론트가 시간을 독립 계산하지 않음.
- **위반 시나리오 배제**: 만약 프론트가 `new Date().getHours() >= 8`로 판정했다면 브라우저 시간 오차/서버-클라이언트 시차 시 백엔드-프론트 드리프트 발생. 본 설계는 이를 원천 차단.
- **phase 문자열 SSOT**: `PRE_OPEN_PHASES` 집합은 백엔드 `calc_timebased_market_phase()` 반환 문자열에 의존. 백엔드 phase 명칭 변경 시 프론트도 갱신 필요 → `sector-settings.ts:REGULAR_PHASES`와 동일한 동기화 의존성 (기존 패턴 준수, P23).

### 4.2 P24 (단순성) — 부합 ✓

- **중복 제거**: 시간 계산 로직을 프론트에 신규 도입하지 않고 기존 WS 인프라 재사용. 신규 코드 = `getTradingToday()` 1함수 + 보조 2함수 (~25줄).
- **불필요한 추상화 금지**: `getLocalToday()`/`getTradingToday()` 용도 분리는 실제 의미 차이(캘린더 날짜 vs 거래일 기준 날짜) 반영. 단일 함수에 `boolean includeTime` 인자 추가보다 명확.
- **더 단순한 대체 검토**: 
  - 대안 A: `getLocalToday()` 자체를 시간 고려하도록 수정 → 사용처 7, 8번(표시 전용)이 의도치 않게 전일 표시로 변경 → 부작용. **기각**.
  - 대안 B: 각 사용처에서 `if (phase === '장개시전') prevDay else today` 인라인 분기 → 9곳 중 6곳 분기 중복 → P24 위반. **기각**.
  - 본 설계(신규 함수 + 사용처 전환)가 가장 단순.

### 4.3 P23 (일관성) — 부합 ✓

- **네이밍**: `getTradingToday()` — `getLocalToday()`와 동일 어조, `Trading` 접두사로 거래일 기준 명시. `camelCase` 준수 (TS 규칙).
- **패턴 재사용**: `PRE_OPEN_PHASES` 집합 기반 분기 = `sector-settings.ts:REGULAR_PHASES` 패턴. 동일 파일 내 상수 집합 정의 패턴.
- **용어 통일**: "거래일" (ARCHITECTURE.md 부록 B 표준 용어). "개장 전"/"장마감 후" (기존 phase 명칭 사용).

### 4.4 P20 (폴백 금지) — 부합 ✓

- `uiStore.marketPhase` 초기값 `{ krx: '장마감', nxt: '장마감' }` → WS 수신 전에는 장마감으로 간주 → 다음 거래일 반환. 이는 합리적 기본값이지 폴백 아님 (앱 초기 로딩 시에는 거래일 카드가 어차피 빈 데이터).
- `PRE_OPEN_PHASES`에 없는 phase → 장중으로 간주 → 오늘 반환. 이는 명시적 기본값 정의 (폴백이 아님).

### 4.5 P16 (살아있는 경로) — 부합 ✓

- `getTradingToday()`는 6곳 사용처에서 실제 호출되는 살아있는 경로.
- `uiStore.marketPhase`는 WS `market-phase` 이벤트 + 30초 카운트다운 타이머(`header.ts:603`)로 주기적 갱신 → dead code 아님.

### 4.6 P22 (데이터 정합성) — 부합 ✓

- 당일 카드 dateFrom/dateTo와 백엔드 스냅샷 저장 날짜(`get_current_trading_day()`)가 08:00/20:00 기준으로 정합.
- 단, 백엔드 `get_current_trading_day()`는 08:00 기준 미반영이나 스냅샷 저장은 20:00 이후에만 호출되므로 실제 정합성 문제 없음 (1.5절 참고).

### 4.7 P25 (격리된 실패) — 부합 ✓

- `uiStore.getState().marketPhase` 읽기 실패 시 (store 미초기화) 초기값 반환 → 앱 중단 없음.
- phase 문자열이 예상치 못한 값이면 장중으로 간주 → 오늘 반환 (안전 측).

---

## 5. 5종 테이블 표준 형식 보고

### 5.1 수정 범위 테이블

| 구분 | 대상 | 수정 내용 | 파일 | 라인 |
|------|------|-----------|------|------|
| 신규 | `getTradingToday()` | 거래일 기준 오늘 (phase 기반) | `frontend/src/utils/date.ts` | 신규 추가 |
| 신규 | `getTradingMonthStart()` | 거래일 기준 당월 시작 | `frontend/src/utils/date.ts` | 신규 추가 |
| 신규 | `PRE_OPEN_PHASES` | 개장 전 phase 집합 상수 | `frontend/src/utils/date.ts` | 신규 추가 |
| 신규 | `_prevCalendarDay/_nextCalendarDay` | 날짜 산술 보조 | `frontend/src/utils/date.ts` | 신규 추가 |
| 수정 | `updateSummaryCards` 당일 카드 | `getLocalToday`→`getTradingToday` | `profit-shared.ts` | 176 |
| 수정 | `renderAccountVals` 당일 집계 | 동일 | `profit-shared.ts` | 604 |
| 수정 | 당월 드릴다운 yearMonth | 동일 | `profit-detail-display.ts` | 111 |
| 수정 | 빠른 범위 기본값 | 동일 | `profit-overview-mount.ts` | 278 |
| 수정 | `defaultDateRange` to | 동일 | `profit-overview-date.ts` | 56 |
| 수정 | 당월 범위 | 동일 | `profit-detail.ts` | 132 |
| 수정 | `defaultDateRange` from | `getLocalMonthStart`→`getTradingMonthStart` | `profit-overview-date.ts` | 56 |
| 수정 | 차트 헤더 monthFirst | 동일 | `canvas-profit-chart.ts` | 155 |
| 유지 | 차트 헤더 todayStr | `getLocalToday` 유지 (표시 전용) | `canvas-profit-chart.ts` | 154 |
| 유지 | 당일 색상 강조 | `getLocalToday` 유지 (표시 전용) | `sell-position.ts` | 92 |
| 제외 | 백엔드 `get_current_trading_day()` | 08:00 기준 미반영이나 실제 문제 없음 | `trading_calendar.py` | 344 |
| 제외 | 실전모드 전체 | 증권사 서버 SSOT → 수정 제외 | — | — |

### 5.2 검증 게이트 테이블

| 대상 | 명령어 | 비고 |
|------|--------|------|
| 프론트엔드 타입체크 | `cd frontend && npm run typecheck` | `tsc --noEmit` |
| 프론트엔드 빌드 | `cd frontend && npm run build` | `tsc -b && vite build` |
| 프론트엔드 테스트 | `cd frontend && npm run test` | vitest, 116 tests — `getTradingToday` 신규 테스트 추가 필요 |
| 백엔드 테스트 | 해당 없음 | 백엔드 수정 없음 |

### 5.3 위험 및 예외 테이블

| 위험 | 확률 | 영향 | 완화 |
|------|------|------|------|
| `uiStore.marketPhase` WS 수신 전 초기값 '장마감'으로 당일 카드가 다음 거래일 기준 동작 | 중 | 앱 첫 로딩 1~2초간 당일 카드 빈 표시 | 초기 로딩 시 어차피 데이터 없음 → 무영향 |
| 백엔드 phase 명칭 변경 시 `PRE_OPEN_PHASES` 미갱신 | 낮 | 개장 전에 오늘 기준 동작 | `sector-settings.ts:REGULAR_PHASES`와 동일한 기존 동기화 의존성 (P23) |
| 브라우저 시간이 KST가 아닌 경우 | 낮 | `getLocalToday()` 캘린더 날짜 오차 | 기존 이슈 (본 수정 범위 아님) — `getTradingToday`의 phase 판정은 백엔드 KST 기반이므로 영향 없음 |
| 08:00 정각 경계 (phase 전환 직전/직후) | 낮 | 1초 오차 가능 | 백엔드 phase 전환이 08:00 정각 발생 → 무시 가능 수준 |

### 5.4 의존성 테이블

| 의존 | 방향 | 내용 |
|------|------|------|
| `utils/date.ts` → `stores/uiStore.ts` | 신규 | `getTradingToday()`가 `uiStore.getState().marketPhase` 읽기 |
| `uiStore.marketPhase` → `binding.ts` `market-phase` WS | 기존 | phase 갱신 경로 (수정 없음) |
| `calc_timebased_market_phase()` → WS `market-phase` | 기존 | 백엔드 SSOT (수정 없음) |
| `PRE_OPEN_PHASES` ↔ `calc_timebased_market_phase()` 반환 문자열 | 신규 동기화 | 백엔드 phase 명칭 변경 시 프론트 상수 갱신 필요 (REGULAR_PHASES와 동일 패턴) |

### 5.5 태스크 분할 예정 (다음 세션)

| 태스크 | 내용 | 예상 커밋 |
|--------|------|-----------|
| F-1 | `date.ts` 신규 함수 + 상수 추가 | `feat: getTradingToday 거래일 기준 오늘 추가 (phase 기반)` |
| F-2 | 사용처 6곳 전환 + `getLocalMonthStart`→`getTradingMonthStart` | `refactor: 기간 카드 날짜를 거래일 기준으로 전환` |
| F-3 | `getTradingToday` 단위 테스트 (개장 전/장중/장마감 후 3케이스) | `test: getTradingToday phase 기반 분기 테스트` |
| F-4 | 검증 게이트 통과 (typecheck/build/test) | — |

---

## 6. 다음 세션 인계

- 본 설계 파일 기반으로 `docs/architecture_trading_day_premarket_tasks.md` 태스크 파일 작성 예정
- 태스크 분할: F-1(신규 함수) → F-2(사용처 전환) → F-3(테스트) → F-4(검증)
- 각 태스크 독립 커밋, 완료 시마다 검증 게이트 통과 필수
- 실전모드 관련 코드는 태스크 대상에서 제외 (사용자 결정 1)
