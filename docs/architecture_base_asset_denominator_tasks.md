# 태스크 분할: 기초자산 분모 방식 수익률 계산 구현

> **다단계 워크플로우 2세션(태스크 분할)** — 본 파일은 1세션 설계(`architecture_base_asset_denominator_design.md`)를 태스크 단위로 분해.
> **작성일**: 2026-07-30
> **관련 커밋**: 9ba3de7 (1세션 설계 파일)
> **설계 파일**: `docs/architecture_base_asset_denominator_design.md`

---

## 0. 사용자 결정 사항 (1세션 + 2세션 확정)

| # | 결정 사항 | 확정값 | 출처 |
|---|---|---|---|
| 1 | 스냅샷 저장 시점 | 장마감 후 `_run_post_confirmed_pipeline` | 1세션 결정 |
| 2 | 당일 카드 분모 | 전일 장마감 총자산 + 당일 순입출금액 | 1세션 결정 |
| 3 | 누적 카드 분모 | 초기 투자원금 (`accumulated_investment`) 유지 | 1세션 결정 |
| 4 | dailySummary 확장 방식 채택 | API 추가 방식 배제 (P24 단순성) | 1세션 결정 |
| 5 | 출금 미지원 전제 | 당일 순입출금 = 당일 입금액만 | 1세션 전제 |
| 6 | **기간 카드 baseAsset 없을 때 분모** | **"첫 거래일의 기초자산 = 초기 투자원금" 금융 로직 정의** (폴밭 아님) | 2세션 결정 |

### 결정 6 상세 (사용자 2세션 결정)

- **원칙**: "스냅샷 레코드가 없다" ≠ "기초 투자 자산이 없다"
- **첫 거래일**: 어제 스냅샷 없음 → 기초자산 = 최초 투자원금 (`accumulated_investment`)
- **2일차부터**: 정상적으로 기초자산 = 전일 장마감 스냅샷
- **배제**: A(null/-) 방식은 UX 최악, B(buyTotal) 방식은 회전율 착시 재발
- **구현**: `baseAsset ?? accumulated_investment` (테스트/실전 모두). 폴백이 아닌 "초기값 정의"로 명명.

---

## 1. 코드 조사 결과 (2세션 — 설계 대비 정정 포함)

### 1.1 백엔드 조사 정정

| 설계 문서 기재 | 실제 위치 | 비고 |
|---|---|---|
| `backend/app/services/stock_tables.py` | **`backend/app/db/stock_tables.py`** | `services/`가 아닌 `db/` 폴더 |
| `_create_runtime_tables` 7-57줄 | 정확 | `settlement_state`, `trades`, `trading_days_cache` 3개 테이블 |
| `_run_post_confirmed_pipeline` 510-520줄 | 정확 | `_save_confirmed_cache` 호출 후 `logger.info` 1줄 |
| `get_daily_summary` 599-674줄 | 정확 | `daily_map[d]` 딕셔너리 구성, 9개 필드 |
| `settlement_engine.charge()` 136-146줄 | 정확 | 모듈 레벨 상태 (`_accumulated_investment`, `_orderable`, `_loaded`, `_initial_deposit`) |
| `get_trade_mode()` 42-44줄 | 정확 | `is_test_mode(state.integrated_system_settings_cache)` 기반 |
| `build_account_snapshot_meta` 100-143줄 | 정확 | `engine_account_rest.py`, 17개 필드 반환 |

### 1.2 프론트엔드 조사 정정 (중요)

| 설계 문서 기재 | 실제 | 비고 |
|---|---|---|
| 분모 사용처 5곳 | **8곳** | 사용처 재집계 필요 |
| `profit-shared.ts` 경로 | **`frontend/src/pages/profit-shared.ts`** | `utils/`가 아닌 `pages/` 폴더 |
| `computeCumulativePnl` 372-378줄 | 정확 | 현재 분모: 테스트=`accumulated_investment`, 실전=`buyTotal` |
| `computeWeightedRate` 위치 | `profit-shared.ts`가 아닌 **`ui-styles.ts` 142-144줄** | 공식: `pnl / buyTotal × 100` |
| `AccountSnapshot` 타입 3-15줄 | 정확 | `accumulated_investment?` 선택 필드 |

### 1.3 computeCumulativePnl 사용처 8곳 (정정)

| # | 함수 | 파일:라인 | 호출 인자 | 분모 동작 |
|---|---|---|---|---|
| 1 | updateSummaryCards (당일) | profit-shared.ts:191 | `{ sellHistory, account, isTestMode, dateFrom: today, dateTo: today }` | 테스트: accumulated_investment, 실전: 당일 buyTotal |
| 2 | updateSummaryCards (전일) | profit-shared.ts:193 | `{ ..., dateFrom: prevDay, dateTo: prevDay }` | 동일 패턴 |
| 3 | updateSummaryCards (5거래일) | profit-shared.ts:196 | `{ ..., dateFrom: fivedayFrom, dateTo: fivedayTo }` | 동일 패턴 |
| 4 | updateSummaryCards (당월) | profit-shared.ts:198 | `{ ..., dateFrom: monthStart, dateTo: monthEnd }` | 동일 패턴 |
| 5 | updateSummaryCards (누적) | profit-shared.ts:199 | `{ sellHistory, account, isTestMode }` (dateFrom/dateTo 없음) | 누적 모드 |
| 6 | renderAccountVals | profit-shared.ts:565-567 | `{ sellHistory, account: a, isTestMode }` (누적 모드) | 계좌 현황 누적 |
| 7 | buildDonutCenter | profit-overview-mount.ts:74-80 | `{ sellHistory: filteredSellHistory, account, isTestMode, dateFrom: localDateFrom, dateTo: localDateTo }` | 도넛 중앙 |
| 8 | updateStatistics | profit-detail-display.ts:157-163 | `{ sellHistory: filteredSells, account, isTestMode, dateFrom, dateTo }` | 하단 통계 |

> **P10/P23 일관성**: 8곳 모두 `computeCumulativePnl` SSOT 호출. 분모 로직은 함수 내부에서 통일되므로 함수 1곳 수정 + baseAsset 전달 8곳 추가.

### 1.4 dailySummary 전달 경로

- WS 이벤트 `daily-summary-update` → `applyDailySummaryUpdate` → `hotStore.dailySummary`
- WS 이벤트 `sell-history-append` → `hotStore.dailySummary` 동시 갱신
- 타입: `Record<string, unknown>[]`, 주요 필드: `date`, `sell_count`, `buy_count`, `realized_pnl`, `pnl_rate`

### 1.5 기존 테스트 현황

- `frontend/tests/pages/profit-shared.test.ts`: `computeHoldingsSummary`, `computePositionValuation` 테스트 존재
- **`computeCumulativePnl` 테스트 없음** → 신규 추가 필요 (태스크 F-7)

---

## 2. 태스크 분할

> **원칙**: 백엔드 태스크(B-*) → 프론트엔드 태스크(F-*) 순서. 백엔드가 base_asset 데이터를 제공해야 프론트가 소비 가능.
> 각 태스크는 독립 커밋 단위. 태스크 완료 시마다 검증 게이트 통과 필수.

### 2.1 백엔드 태스크 (B-1 ~ B-7)

#### B-1: DB 백업 (안전 규칙 2 필수)

- **스킬**: `db-backup` 스킬 실행 (스키마 변경 전 필수)
- **대상**: `backend/data/stocks.db`, `stocks.db-shm`, `stocks.db-wal` 타임스탬프 백업
- **완료 기준**: 백업 파일 생성 확인
- **커밋**: 백업 파일은 `.gitignore` 대상이므로 커밋 제외 (백업 자체가 완료 기준)

#### B-2: account_daily_snapshot 테이블 생성

- **파일**: `backend/app/db/stock_tables.py` `_create_runtime_tables` (57줄 이후)
- **스키마** (설계 4.1.1 + 순입출금 필드 확장):
```sql
CREATE TABLE IF NOT EXISTS account_daily_snapshot (
    date TEXT NOT NULL,                  -- 거래일 (YYYY-MM-DD)
    trade_mode TEXT NOT NULL,            -- "test" 또는 "real"
    total_asset INTEGER NOT NULL,        -- 기초자산 (예수금/주문가능금액 + 총평가금액)
    deposit INTEGER,                     -- 예수금 (참조용)
    orderable INTEGER,                   -- 주문가능금액 (참조용)
    total_eval_amount INTEGER,           -- 총평가금액 (참조용)
    accumulated_investment INTEGER,      -- 누적투자금 (참조용, 테스트모드)
    daily_deposit INTEGER DEFAULT 0,     -- 당일 입금액
    daily_withdrawal INTEGER DEFAULT 0,  -- 당일 출금액 (현재 0, 후순위)
    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, trade_mode)
)
```
- **인덱스**: `CREATE INDEX IF NOT EXISTS idx_account_daily_snapshot_date ON account_daily_snapshot (date)`
- **패턴**: 기존 `settlement_state`, `trades` 테이블 CREATE 패턴 준수
- **검증**: `.venv/bin/python -m pytest backend/tests -q` (기동 시 테이블 생성 회귀)
- **커밋**: `feat: account_daily_snapshot 테이블 추가 (기초자산 분모 방식)`

#### B-3: 일별 계좌 스냅샷 저장 함수

- **파일**: `backend/app/db/stock_tables.py` (신규 함수, `load_settlement_state` 함수 다음)
- **함수 시그니처**:
```python
async def save_daily_account_snapshot(
    conn,
    *,
    date: str,
    trade_mode: str,
    total_asset: int,
    deposit: int = 0,
    orderable: int = 0,
    total_eval_amount: int = 0,
    accumulated_investment: int = 0,
    daily_deposit: int = 0,
    daily_withdrawal: int = 0,
) -> None:
    """장마감 후 당일 계좌 총자산 스냅샷 저장 (INSERT OR REPLACE)."""
```
- **패턴**: `save_settlement_state` 패턴 준수 (`INSERT OR REPLACE`)
- **P22 데이터 정합성**: `total_asset`은 호출부에서 산출 (원본 account_snapshot에서 파생)
- **검증**: pytest (신규 테스트: 저장 후 조회 일치)
- **커밋**: `feat: save_daily_account_snapshot 저장 함수 추가`

#### B-4: 일별 계좌 스냅샷 조회 함수

- **파일**: `backend/app/db/stock_tables.py` (B-3 함수 다음)
- **함수 2개**:
```python
async def get_account_snapshot_by_date(conn, *, date: str, trade_mode: str) -> dict | None:
    """특정 날짜의 기초자산 스냅샷 조회. 없으면 None."""

async def get_base_asset_for_period(conn, *, date_from: str, trade_mode: str) -> int | None:
    """기간 시작 시점 기초자산 조회.
    date_from의 전일 장마감 스냅샷 total_asset 반환 (당일 분모 = 전일 종가).
    date_from이 당일이면 전일, 5거래일이면 5일 전, 당월이면 월초.
    없으면 None (프론트에서 초기 투자원금으로 처리 — 결정 6)."""
```
- **검증**: pytest (신규 테스트: 날짜 범위 조회, 없는 날짜 None 반환)
- **커밋**: `feat: get_account_snapshot_by_date / get_base_asset_for_period 조회 함수 추가`

#### B-5: settlement_engine 당일 입금액 추적

- **파일**: `backend/app/services/settlement_engine.py`
- **변경**:
  - 모듈 레벨 변수 추가 (30-33줄 부근): `_daily_deposit_total: int = 0`
  - `charge()` 함수 (136-146줄) 내부: `_daily_deposit_total += amount` 추가
  - 신규 함수 `get_daily_deposit_total() -> int` / `reset_daily_deposit_total() -> None`
- **P10 SSOT**: `_daily_deposit_total`은 settlement_engine 단일 소스
- **검증**: pytest (charge 후 get_daily_deposit_total 일치, reset 후 0)
- **커밋**: `feat: settlement_engine 당일 입금액 추적 (_daily_deposit_total)`

#### B-6: _run_post_confirmed_pipeline 스냅샷 저장 호출 추가

- **파일**: `backend/app/services/market_close_pipeline.py` `_run_post_confirmed_pipeline` (516-520줄)
- **변경**:
```python
try:
    await _save_confirmed_cache(eligible_codes=eligible_codes)
    # 신규: 장마감 후 당일 계좌 스냅샷 저장 (P25 격리 — 실패 시 파이프라인 중단 안 함)
    try:
        from backend.app.services.engine_account import get_trade_mode
        from backend.app.db.stock_tables import save_daily_account_snapshot
        # account_snapshot에서 total_asset 산출 + _daily_deposit_total 포함
        await _save_daily_snapshot(get_trade_mode())
    except Exception as e:
        logger.warning("[스케줄] 일별 계좌 스냅샷 저장 실패 (기동 유지): %s", e, exc_info=True)
    logger.info("[스케줄] 확정 후 파이프라인 종료 (롤링 로직 생략)")
except Exception as exc:
    logger.warning("[스케줄] 확정 후 파이프라인 오류: %s", exc, exc_info=True)
```
- **신규 헬퍼**: `_save_daily_snapshot(trade_mode)` — account_snapshot에서 total_asset 산출 (테스트: `orderable + total_eval`, 실전: `deposit + total_eval`) + `settlement_engine.get_daily_deposit_total()` 포함 + 저장 후 `reset_daily_deposit_total()`
- **P25 격리된 실패**: 스냅샷 저장 실패 시 warning 로깅 후 파이프라인 계속
- **P16 살아있는 경로**: `_run_post_confirmed_pipeline` 실제 실행 경로에 연결
- **검증**: pytest + `python -W error::RuntimeWarning main.py` (await 누락)
- **커밋**: `feat: 장마감 후 일별 계좌 스냅샷 저장 호출 추가 (P25 격리)`

#### B-7: get_daily_summary base_asset 필드 확장

- **파일**: `backend/app/services/trade_history.py` `get_daily_summary` (640-674줄)
- **변경**: `daily_map[d]` 구성 시 `base_asset` 필드 추가
```python
daily_map[d] = {
    "date": d,
    ...기존 9개 필드...,
    "base_asset": await get_base_asset_for_period(conn, date_from=d, trade_mode=trade_mode),  # 신규
}
```
- **의미**: 각 일별 행의 `base_asset` = 전일 장마감 스냅샷 `total_asset` (당일 분모 = 전일 종가)
- **P10 SSOT**: dailySummary가 일별 데이터(기초자산 포함) 단일 소스
- **P24 단순성**: API 추가 방식 배제, dailySummary 확장 채택
- **검증**: pytest (daily_summary에 base_asset 필드 존재, 전일 스냅샷 연동)
- **커밋**: `feat: get_daily_summary base_asset 필드 추가 (dailySummary 확장)`

---

### 2.2 프론트엔드 태스크 (F-1 ~ F-7)

#### F-1: AccountSnapshot 타입 확장

- **파일**: `frontend/src/types/index.ts` AccountSnapshot (3-15줄)
- **변경**: `daily_deposit?: number` 필드 추가 (당일 입금액, 실시간)
- **비고**: 기초자산은 dailySummary 행별로 오므로 AccountSnapshot에 추가 불필요. 단, 당일 순입출금액은 account snapshot에 실시간 포함 (당일 카드 분모 = 전일 baseAsset + account.daily_deposit)
- **검증**: `cd frontend && npm run typecheck`
- **커밋**: `feat: AccountSnapshot 타입 daily_deposit 필드 추가`

#### F-2: computeCumulativePnl 시그니처 확장 + 분모 로직 교체

- **파일**: `frontend/src/pages/profit-shared.ts` computeCumulativePnl (372-378줄)
- **변경**:
```typescript
export interface CumulativePnlParams {
  sellHistory: Record<string, unknown>[]
  account: AccountSnapshot | null
  isTestMode: boolean
  dateFrom?: string
  dateTo?: string
  baseAsset?: number  // 신규: 기간 시작 시점 기초자산 (전일 장마감 총자산 + 당일 순입출금)
}

export function computeCumulativePnl(params: CumulativePnlParams): { pnl: number; rate: number } {
  const { sellHistory, account, isTestMode, dateFrom, dateTo, baseAsset } = params
  const { pnl, buyTotal } = aggregatePnl(sellHistory, dateFrom, dateTo)
  const isCumulative = !dateFrom && !dateTo
  let denominator: number
  if (isCumulative) {
    // 누적 카드: 초기 투자원금 (사용자 결정 3 — 현행 유지)
    denominator = isTestMode
      ? (account?.accumulated_investment ?? account?.initial_deposit ?? 0)
      : buyTotal
  } else {
    // 기간 한정 카드: 기초자산 (전일 장마감 총자산 + 당일 순입출금)
    // 결정 6: baseAsset 없으면 초기 투자원금 (첫 거래일 기초자산 = 초기 투자원금, 폴백 아닌 초기값 정의)
    const fallback = isTestMode
      ? (account?.accumulated_investment ?? account?.initial_deposit ?? 0)
      : buyTotal
    denominator = baseAsset ?? fallback
  }
  return { pnl, rate: computeWeightedRate(pnl, denominator) }
}
```
- **P20 폴백 금지 준수**: "폴백"이 아닌 "첫 거래일 기초자산 = 초기 투자원금" 금융 로직 정의 (결정 6)
- **주석 업데이트**: 기존 분모 규칙 주석을 새 규칙으로 교체 (P23 용어 일관성)
- **검증**: typecheck + test
- **커밋**: `feat: computeCumulativePnl baseAsset 파라미터 + 기초자산 분모 로직`

#### F-3: findBaseAssetForDate 헬퍼 함수 추가

- **파일**: `frontend/src/pages/profit-shared.ts` (computeCumulativePnl 다음)
- **함수**:
```typescript
/** dailySummary에서 특정 날짜의 기초자산(전일 장마감 스냅샷) 추출.
 *  date 이전 날짜 중 가장 최근 행의 base_asset 필드 반환.
 *  없으면 undefined (computeCumulativePnl에서 초기 투자원금으로 처리 — 결정 6). */
export function findBaseAssetForDate(
  dailySummary: Record<string, unknown>[],
  date: string,
): number | undefined {
  let prevBaseAsset: number | undefined
  let prevDate = ''
  for (const r of dailySummary) {
    const d = String(r.date ?? '')
    const baseAsset = Number(r.base_asset ?? 0)
    if (d < date && d > prevDate && baseAsset > 0) {
      prevDate = d
      prevBaseAsset = baseAsset
    }
  }
  return prevBaseAsset
}
```
- **검증**: typecheck + test (신규 테스트: 날짜 범위, 없는 날짜 undefined)
- **커밋**: `feat: findBaseAssetForDate 헬퍼 함수 추가`

#### F-4: updateSummaryCards 5개 카드 baseAsset 전달

- **파일**: `frontend/src/pages/profit-shared.ts` updateSummaryCards (166-221줄)
- **변경**: 5개 카드 호출부에 baseAsset 추가 (누적 카드는 제외)
```typescript
const dayBaseAsset = findBaseAssetForDate(dailySummary, today)
const prevBaseAsset = prevDay ? findBaseAssetForDate(dailySummary, prevDay) : undefined
const fiveBaseAsset = (fivedayFrom && fivedayTo) ? findBaseAssetForDate(dailySummary, fivedayFrom) : undefined
const monthBaseAsset = findBaseAssetForDate(dailySummary, monthStart)

const dayS = computeCumulativePnl({ sellHistory, account, isTestMode, dateFrom: today, dateTo: today, baseAsset: dayBaseAsset })
const prevS = prevDay
  ? computeCumulativePnl({ sellHistory, account, isTestMode, dateFrom: prevDay, dateTo: prevDay, baseAsset: prevBaseAsset })
  : { pnl: 0, rate: 0 }
const fiveS = (fivedayFrom && fivedayTo)
  ? computeCumulativePnl({ sellHistory, account, isTestMode, dateFrom: fivedayFrom, dateTo: fivedayTo, baseAsset: fiveBaseAsset })
  : { pnl: 0, rate: 0 }
const monS = computeCumulativePnl({ sellHistory, account, isTestMode, dateFrom: monthStart, dateTo: monthEnd, baseAsset: monthBaseAsset })
const allS = computeCumulativePnl({ sellHistory, account, isTestMode })  // 누적은 baseAsset 없음
```
- **당일 카드 정정**: 당일 분모 = 전일 baseAsset + account.daily_deposit (설계 4.5). `dayBaseAsset`에 daily_deposit 보정 필요:
  - `const dayBaseAssetWithDeposit = (dayBaseAsset ?? 0) + (account?.daily_deposit ?? 0)` (dayBaseAsset 있을 때만)
  - 단, dayBaseAsset이 undefined면 결정 6에 따라 초기 투자원금으로 처리 (daily_deposit 보정 제외)
- **검증**: typecheck + test + build
- **커밋**: `feat: updateSummaryCards 5개 카드 baseAsset 전달`

#### F-5: buildDonutCenter baseAsset 전달

- **파일**: `frontend/src/pages/profit-overview-mount.ts` buildDonutCenter (70-82줄)
- **변경**: `state.filteredSellHistory`에 더해 `dailySummary`에서 baseAsset 추출
```typescript
function buildDonutCenter(state: ProfitOverviewState): SectorDonutCenter {
  const hotState = hotStore.getState()
  const settings = globalSettingsManager.getSettings()
  const isTestMode = settings?.trade_mode === 'test'
  const baseAsset = state.localDateFrom
    ? findBaseAssetForDate(hotState.dailySummary, state.localDateFrom)
    : undefined
  const { pnl, rate } = computeCumulativePnl({
    sellHistory: state.filteredSellHistory,
    account: hotState.account,
    isTestMode,
    dateFrom: state.localDateFrom,
    dateTo: state.localDateTo,
    baseAsset,  // 신규
  })
  return { pnl, rate, title: makeCenterTitle(state.localQuickLabel) }
}
```
- **import 추가**: `findBaseAssetForDate` from `./profit-shared`
- **검증**: typecheck + build
- **커밋**: `feat: buildDonutCenter baseAsset 전달`

#### F-6: updateStatistics baseAsset 전달

- **파일**: `frontend/src/pages/profit-detail-display.ts` updateStatistics (140-171줄)
- **변경**: dateRange.from 있을 때 baseAsset 추출
```typescript
const isTestMode = globalSettingsManager.getSettings()?.trade_mode === 'test'
const baseAsset = dateRange.from
  ? findBaseAssetForDate(hotStore.getState().dailySummary, dateRange.from)
  : undefined
const { rate: avgRate } = computeCumulativePnl({
  sellHistory: filteredSells,
  account: hotStore.getState().account,
  isTestMode,
  dateFrom: dateRange.from || undefined,
  dateTo: dateRange.to || undefined,
  baseAsset,  // 신규
})
```
- **import 추가**: `findBaseAssetForDate` from `./profit-shared`
- **검증**: typecheck + build
- **커밋**: `feat: updateStatistics baseAsset 전달`

#### F-7: 회귀 테스트 추가

- **파일**: `frontend/tests/pages/profit-shared.test.ts` (신규 테스트 블록)
- **테스트 케이스**:
  1. `computeCumulativePnl` 누적 모드 (dateFrom/dateTo 없음): 테스트=accumulated_investment 분모, 실전=buyTotal 분모
  2. `computeCumulativePnl` 기간 모드 + baseAsset 있음: baseAsset 분모
  3. `computeCumulativePnl` 기간 모드 + baseAsset 없음: 초기 투자원금 분모 (결정 6)
  4. `findBaseAssetForDate`: 날짜 범위 내 최근 행 추출
  5. `findBaseAssetForDate`: 없는 날짜 undefined 반환
- **검증**: `cd frontend && npm run test`
- **커밋**: `test: computeCumulativePnl / findBaseAssetForDate 회귀 테스트 추가`

---

### 2.3 검증 태스크 (V-1)

#### V-1: 전체 검증 게이트

- **백엔드**:
  - `.venv/bin/python -m pytest backend/tests -q` (2697 tests)
  - `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락, 금지 패턴 4번째)
  - 0-1-3 명령어로 잔존 프로세스 0건 확인
- **프론트엔드**:
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm run test` (vitest, 116 tests + F-7 신규)
  - `cd frontend && npm run build`
- **DB**: stocks.db 백업 파일 존재 확인 (B-1)
- **커밋**: 검증 태스크는 커밋 없음 (각 태스크 커밋 시 검증 포함)

---

## 3. 태스크 의존성 그래프

```
B-1 (DB 백업) → B-2 (테이블 생성) → B-3 (저장 함수) → B-4 (조회 함수)
                                                       ↓
B-5 (입금액 추적) → B-6 (파이프라인 저장 호출) → B-7 (dailySummary 확장)
                                                       ↓
F-1 (타입 확장) → F-2 (computeCumulativePnl) → F-3 (findBaseAssetForDate)
                                                       ↓
                              F-4 (updateSummaryCards) → F-5 (buildDonutCenter)
                                                       ↓
                              F-6 (updateStatistics) → F-7 (회귀 테스트)
                                                       ↓
                                                   V-1 (전체 검증)
```

- **직렬 필수**: B-1 → B-2 → B-3 → B-4 (DB 스키마 → 저장 → 조회 순서)
- **병렬 가능**: B-5는 B-2~B-4와 병렬 (독립 모듈), 단 B-6는 B-5 + B-3 의존
- **프론트는 백엔드 B-7 완료 후 착수**: dailySummary에 base_asset 필드가 있어야 프론트가 소비 가능

---

## 4. 구현 순서 권장 (단일 세션或多세션)

### 4.1 단일 세션 완료 시 (권장)
B-1 → B-2 → B-3 → B-4 → B-5 → B-6 → B-7 → F-1 → F-2 → F-3 → F-4 → F-5 → F-6 → F-7 → V-1

### 4.2 2세션 분할 시
- **3세션 (백엔드)**: B-1 ~ B-7 + 백엔드 pytest
- **4세션 (프론트엔드)**: F-1 ~ F-7 + 프론트엔드 typecheck/test/build + V-1

---

## 5. 아키텍처 원칙 점검 (구현 완료 후 필수)

| 원칙 | 태스크 | 점검 항목 |
|---|---|---|
| P10 (SSOT) | B-7, F-2 | dailySummary가 일별 데이터 단일 소스. account snapshot은 현재 상태 SSOT. |
| P16 (살아있는 경로) | B-6 | 스냅샷 저장이 `_run_post_confirmed_pipeline` 실제 실행 경로에 연결 |
| P20 (폴백 금지) | F-2 | baseAsset 없음 = "첫 거래일 기초자산 = 초기 투자원금" 금융 로직 정의 (폴백 아님) |
| P21 (사용자 투명성) | F-2~F-6 | 회전율 희석 착시 제거, 복리 자산 변화 반영 |
| P22 (데이터 정합성) | B-3, B-6 | 기초자산 = 원본(account snapshot)에서 파생. 스냅샷 저장 시점 확정 |
| P23 (일관성) | F-2 | computeCumulativePnl SSOT 유지, 8개 사용처 동일 분모 규칙 |
| P24 (단순성) | B-7 | dailySummary 확장이 API 추가보다 단순 |
| P25 (격리된 실패) | B-6 | 스냅샷 저장 실패 시 파이프라인 중단 안 함 (warning 로깅) |

---

## 6. 후순위 (본 태스크 범위 외)

- **실전모드 출금 기능**: 현재 출금 API 없음. 출금 지원 시 `_daily_withdrawal_total` 추가 + 스냅샷 테이블 daily_withdrawal 필드 활성화.
- **실전모드 A 방식 완전 검증**: 실전 데이터로 기초자산 분모 적용 검증 (별도 세션).
- **과거 데이터 소급 적용**: 기존 거래일의 base_asset 소급 계산 (현재는 첫 스냅샷 이후부터 적용).

---

## 7. 다음 세션 인계 사항

1. 본 태스크 파일의 B-1 ~ B-7, F-1 ~ F-7, V-1 순서대로 구현
2. B-1 (DB 백업)은 `db-backup` 스킬 실행 필수 (안전 규칙 2)
3. 결정 6 (baseAsset 없을 때 초기 투자원금)은 F-2에서 구현 — "폴백" 주석 금지, "첫 거래일 기초자산 정의" 명명
4. 백엔드 `stock_tables.py` 경로 정정: `services/`가 아닌 `db/` 폴더 (1절 1.1)
5. 프론트 `computeCumulativePnl` 사용처 5개 → 8개 정정 (1절 1.3)
6. 프론트 `profit-shared.ts` 경로 정정: `utils/`가 아닌 `pages/` 폴더
7. `computeWeightedRate` 위치: `profit-shared.ts`가 아닌 `ui-styles.ts` 142-144줄
8. 각 태스크 완료 시 검증 게이트 통과 후 커밋 (코드만, HANDOVER.md 제외)
9. 전체 완료 후 HANDOVER.md 갱신 + 세션 완료 보고 (규칙 0-6-2/0-7)
