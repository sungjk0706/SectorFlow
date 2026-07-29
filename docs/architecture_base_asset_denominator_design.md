# 설계: 기초자산 분모 방식 수익률 계산 (증권사 표준 A 방식)

> **다단계 워크플로우 1세션(설계)** — 본 파일은 설계만 포함. 2세션(태스크 파일)은 다음 세션에서 작성.
> **작성일**: 2026-07-30
> **관련 커밋**: 43644cd (A 방식 분모 통일 1차), 본 설계는 2차(기초자산 스냅샷)

---

## 1. 문제 정의

### 1.1 현상
100만원 투자원금으로 68건 회전(매수원가 합 931만원) 시:
- 당월 카드: -101,828 / 9,319,479 = **-1.09%** (B 방식, 회전율 희석)
- 누적 카드: -101,828 / 1,000,275 = **-10.18%** (A 방식)
→ 손익 금액이 같은데 수익률이 10배 차이, 실제 위험 인지 불가 (P21 위반)

### 1.2 근본 원인
현재 `computeCumulativePnl` 분모 로직:
- 테스트모드: `accumulated_investment`(100만원 고정) — 모든 카드 동일 분모
- 실전모드: `buy_total_amt`(매수원가 합) — 회전율 희석 발생

**문제**: 테스트모드는 "투자원금 고정"으로 복리 자산 변화 미반영, 실전은 "매수원가 합"으로 회전율 희석.
**해결**: 증권사 표준 A 방식 — "기초자산(기간 시작 시점 총자산)" 분모.

### 1.3 사용자 요구 규칙 (확정)

| 카드 | 분모 | 의미 |
|---|---|---|
| 당일 | 전일 장마감 총자산 + 당일 순입출금액 | "오늘 시작 재산 대비 오늘 손익" |
| 전일 | 전전일 장마감 총자산 + 전일 순입출금액 | "전일 시작 재산 대비 전일 손익" |
| 5거래일 | 5거래일 전 장마감 총자산 + 5일 순입출금액 | "5일 전 재산 대비 5일 손익" |
| 당월 | 당월 1일 장마감 총자산 + 당월 순입출금액 | "월초 재산 대비 당월 손익" |
| 누적 | 초기 투자원금 (`accumulated_investment`) | "시작 원금 대비 전체 손익" (현행 유지) |

**금융 데이터 대원칙**: "오늘 아침 자산 = 전일 장마감 자산" (장외 입출금 없는 한).

---

## 2. 사용자 결정 항목

| # | 결정 사항 | 사용자 선택 | 사유 |
|---|---|---|---|
| 1 | 스냅샷 저장 시점 | **장마감 후** (`_run_post_confirmed_pipeline`) | DB 데이터 정합성·배치 안정성. 기동 여부에 따른 누락 위험 제거. Truth 소스 단일화. |
| 2 | 당일 카드 분모 | **전일 장마감 총자산 + 당일 순입출금액** | "오늘 아침 = 전일 종가" 금융 대원칙. 장외 입출금은 순입출금액으로 보정. |
| 3 | 누적 카드 분모 | **초기 투자원금 유지** (`accumulated_investment`) | "처음 넣은 원금 대비 전체 손익". 첫 스냅샷 이전 거래 분모 0 문제 회피. |

---

## 3. 현재 구조 조사 결과

### 3.1 백엔드 현황

#### account_snapshot 구조 (`engine_account_rest.py:100-143`)
- `deposit`(예수금), `orderable`(주문가능금액), `accumulated_investment`(누적투자금), `initial_deposit`(초기투자금)
- `total_eval`(총평가금액), `total_pnl`(총손익), `total_buy`(총매입금액), `total_rate`(총수익률)
- `total_eval_amount`(= total_eval, 프론트 호환 키), `total_pnl_rate`(= total_rate)
- `position_count`, `snapshot_at`, `price_source`, `broker`, `trade_mode`

#### 계좌 총자산 산출
- **테스트모드**: `orderable`(주문가능금액) + `total_eval`(평가금액) = 총자산 (`engine_account.py:285-307`)
- **실전모드**: `deposit`(예수금) + `total_eval`(평가금액) = 총자산 (REST kt00018 기반)

#### settlement_engine (`settlement_engine.py`)
- `_accumulated_investment`: 초기투자금 + 충전금액, 매수/매도 시 **불변**
- `_orderable`: 매수 시 차감, 매도/충전 시 증가
- `charge(amount)`: 누적투자금 + 주문가능금액 동시 증가 (입금)
- 출금 기능: 현재 명시적 출금 API 없음 (설계 시 고려)

#### get_daily_summary (`trade_history.py:599-674`)
- 반환 필드: `date, buy_count, sell_count, realized_pnl, buy_total_amt, pnl_rate, buy_fee, sell_fee, tax`
- **계좌 잔고 필드 없음** — 거래 기반 실현손익만

#### DB 스키마 (`stock_tables.py`)
- `settlement_state`(단일 행 id=1), `trades`, `trading_days_cache`, `custom_sectors`, `integrated_system_settings`, `sectors`, `master_stocks_table`, `stock_5d_bars`
- **일별 계좌 스냅샷 테이블 없음**

#### 장마감 파이프라인 (`market_close_pipeline.py:510-520`)
- `_run_post_confirmed_pipeline()`: 장마감 후 확정 데이터 처리 종료점
- 현재 `_save_confirmed_cache()`만 호출 (전종목 마스터 DB 저장)
- **일별 계좌 스냅샷 저장 추가 적소**

### 3.2 프론트엔드 현황

#### computeCumulativePnl (`profit-shared.ts:372-378`)
```ts
const denominator = isTestMode
  ? (account?.accumulated_investment ?? account?.initial_deposit ?? 0)
  : buyTotal
```
- 시그니처: `(sellHistory, account, isTestMode, dateFrom?, dateTo?)` → `{ pnl, rate }`
- `aggregatePnl(sellHistory, dateFrom, dateTo)` → `{ pnl, buyTotal, rate }`

#### 분모 사용처 5곳
| # | 함수 | 파일:라인 | 호출 방식 |
|---|---|---|---|
| 1 | `computeCumulativePnl` | profit-shared.ts:372 | 핵심 분모 로직 |
| 2 | `updateSummaryCards` | profit-shared.ts:191,193,196,198,199 | 5개 카드 (당일/전일/5거래일/당월/누적) |
| 3 | `updateStatistics` | profit-detail-display.ts:157 | 하단 통계 (필터 적용) |
| 4 | `buildDonutCenter` | profit-overview-mount.ts:74 | 도넛 차트 중앙 |
| 5 | `renderAccountVals` | profit-shared.ts:565 | 계좌 현황 누적 수익률 |

#### AccountSnapshot 타입 (`types/index.ts:3-15`)
- `accumulated_investment?`, `initial_deposit?`, `deposit`, `orderable?`, `total_eval_amount` 등
- **기초자산 필드 없음** — 추가 필요

#### hotStore (`hotStore.ts:36-48`)
- `account: AccountSnapshot | null`, `dailySummary`, `sellHistory`, `buyHistory`

---

## 4. 설계

### 4.1 백엔드: 일별 계좌 스냅샷 저장

#### 4.1.1 신규 DB 테이블 (`stock_tables.py:_create_runtime_tables`)
```sql
CREATE TABLE IF NOT EXISTS account_daily_snapshot (
    date TEXT NOT NULL,                  -- 거래일 (YYYY-MM-DD)
    trade_mode TEXT NOT NULL,            -- "test" 또는 "real"
    total_asset INTEGER NOT NULL,        -- 기초자산 (예수금/주문가능금액 + 총평가금액)
    deposit INTEGER,                     -- 예수금 (참조용)
    orderable INTEGER,                   -- 주문가능금액 (참조용)
    total_eval_amount INTEGER,           -- 총평가금액 (참조용)
    accumulated_investment INTEGER,      -- 누적투자금 (참조용, 테스트모드)
    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, trade_mode)
)
```
- `total_asset` = 기초자산 (분모 후보). 테스트모드=`orderable + total_eval`, 실전=`deposit + total_eval`
- 참조 필드는 감사·디버깅용 (P22 데이터 정합성)

#### 4.1.2 저장 함수 (`stock_tables.py` 또는 신규 `account_snapshot_history.py`)
```python
async def save_daily_account_snapshot(trade_mode: str) -> None:
    """장마감 후 당일 계좌 총자산 스냅샷 저장 (INSERT OR REPLACE)."""
    # state.account_snapshot에서 total_asset 산출
    # 테스트모드: orderable + total_eval
    # 실전모드: deposit + total_eval
```

#### 4.1.3 조회 함수
```python
async def get_account_snapshot_by_date(date: str, trade_mode: str) -> dict | None:
    """특정 날짜의 기초자산 스냅샷 조회. 없으면 None."""

async def get_base_asset_for_period(date_from: str, trade_mode: str) -> int | None:
    """기간 시작 시점 기초자산 조회.
    date_from의 전일 장마감 스냅샷 반환 (당일 분모 = 전일 종가).
    date_from이 당일이면 전일, 5거래일이면 5일 전, 당월이면 월초.
    """
```

#### 4.1.4 저장 시점 (`market_close_pipeline.py:_run_post_confirmed_pipeline`)
```python
async def _run_post_confirmed_pipeline(eligible_codes=None) -> None:
    try:
        await _save_confirmed_cache(eligible_codes=eligible_codes)
        # 신규: 장마감 후 당일 계좌 스냅샷 저장 (P25 격리 — 실패 시 파이프라인 중단 안 함)
        try:
            from backend.app.services.engine_account import get_trade_mode
            await save_daily_account_snapshot(get_trade_mode())
        except Exception as e:
            logger.warning("[스케줄] 일별 계좌 스냅샷 저장 실패 (기동 유지): %s", e, exc_info=True)
        logger.info("[스케줄] 확정 후 파이프라인 종료 (롤링 로직 생략)")
    except Exception as exc:
        logger.warning("[스케줄] 확정 후 파이프라인 오류: %s", exc, exc_info=True)
```

### 4.2 백엔드: 순입출금액 추적

#### 문제
당일 카드 분모 = 전일 장마감 총자산 + 당일 순입출금액.
순입출금액 = 당일 입금 - 당일 출금.

#### 현재 상황
- `settlement_engine.charge(amount)`: 입금 시 `accumulated_investment` + `orderable` 증가
- **출금 API 없음** — 현재 구조에서 출금 미지원
- 입금 이력: `accumulated_investment` 변동으로 추적 가능하나, **일별 입금 이력 저장 안 됨**

#### 설계 (최소 구현)
- `settlement_engine`에 당일 입금액 추적 변수 추가: `_daily_deposit_total: int = 0`
- `charge()` 호출 시 `_daily_deposit_total += amount`
- 장마감 스냅샷 저장 시 `_daily_deposit_total`을 스냅샷에 포함, 저장 후 리셋
- 출금 미지원: 당일 순입출금액 = 당일 입금액 (출금 0 가정)
- **후순위**: 출금 기능 추가 시 `_daily_withdrawal_total` 추가

#### 스냅샷 테이블 확장 (선택)
```sql
-- account_daily_snapshot에 추가
daily_deposit INTEGER DEFAULT 0,       -- 당일 입금액
daily_withdrawal INTEGER DEFAULT 0,    -- 당일 출금액 (현재 0)
```
- 분모 = `total_asset`(전일) + `daily_deposit` - `daily_withdrawal`
- but 당일 카드는 "전일 스냅샷 + 당일 입출금"이므로, 당일 입출금은 **당일 스냅샷이 아닌 실시간 값** 필요
- **대안**: 프론트에 당일 입금액을 account snapshot에 실시간 포함하여 전송

### 4.3 백엔드: API/Ws 확장

#### 4.3.1 기초자산 조회 API (신규)
```
GET /api/trade-history/base-asset?date=YYYY-MM-DD&trade_mode=test
→ { "date": "2026-07-28", "total_asset": 1000000, "found": true }
```
- 프론트에서 각 카드의 dateFrom에 대해 전일 기초자산 조회
- 없으면 `found: false` → 프론트에서 폴백 처리 (누적 카드는 accumulated_investment, 기간 카드는 buy_total_amt 임시)

#### 4.3.2 dailySummary 확장 (대안)
`get_daily_summary` 반환 필드에 `base_asset` 추가:
```python
daily_map[d] = {
    ...기존 필드...,
    "base_asset": 전일 장마감 스냅샷 total_asset,  # 신규
}
```
- 프론트 dailySummary에 기초자산 포함 → API 추가 호출 불필요 (P10 SSOT — dailySummary가 일별 데이터 단일 소스)
- **권장**: API 추가보다 dailySummary 확장이 단순성(P24)·일관성(P23) 유리

### 4.4 프론트엔드: computeCumulativePnl 분모 로직 교체

#### 4.4.1 시그니처 확장
```ts
export interface CumulativePnlParams {
  sellHistory: Record<string, unknown>[]
  account: AccountSnapshot | null
  isTestMode: boolean
  dateFrom?: string
  dateTo?: string
  baseAsset?: number  // 신규: 기간 시작 시점 기초자산 (없으면 폴백)
}

export function computeCumulativePnl(params: CumulativePnlParams): { pnl: number; rate: number } {
  const { sellHistory, account, isTestMode, dateFrom, dateTo, baseAsset } = params
  const { pnl, buyTotal } = aggregatePnl(sellHistory, dateFrom, dateTo)
  const isCumulative = !dateFrom && !dateTo
  let denominator: number
  if (isCumulative) {
    // 누적 카드: 초기 투자원금 (사용자 결정 — 현행 유지)
    denominator = isTestMode
      ? (account?.accumulated_investment ?? account?.initial_deposit ?? 0)
      : buyTotal
  } else {
    // 기간 한정 카드: 기초자산 (전일 장마감 총자산 + 당일 순입출금)
    // baseAsset 없으면 폴백 (buy_total_amt — 기존 B 방식, 데이터 미축적 기간)
    denominator = baseAsset ?? buyTotal
  }
  return { pnl, rate: computeWeightedRate(pnl, denominator) }
}
```

#### 4.4.2 updateSummaryCards 호출부
```ts
// dailySummary에서 각 카드의 기초자산 추출 (dailySummary 확장 시)
const dayBaseAsset = findBaseAssetForDate(dailySummary, today)       // 전일 스냅샷
const prevBaseAsset = findBaseAssetForDate(dailySummary, prevDay)    // 전전일 스냅샷
const fiveBaseAsset = findBaseAssetForDate(dailySummary, fivedayFrom)
const monthBaseAsset = findBaseAssetForDate(dailySummary, monthStart)

const dayS = computeCumulativePnl({ sellHistory, account, isTestMode, dateFrom: today, dateTo: today, baseAsset: dayBaseAsset })
// ... 나머지 카드 동일 패턴
const allS = computeCumulativePnl({ sellHistory, account, isTestMode })  // 누적은 baseAsset 없음
```

#### 4.4.3 헬퍼 함수 (신규)
```ts
/** dailySummary에서 특정 날짜의 기초자산(전일 장마감 스냅샷) 추출.
 *  date의 전일 행의 base_asset 필드 반환. 없으면 undefined (폴백). */
function findBaseAssetForDate(dailySummary: Record<string, unknown>[], date: string): number | undefined {
  // date 이전 날짜 중 가장 최근 행의 base_asset
}
```

### 4.5 AccountSnapshot 타입 확정
- `accumulated_investment` 유지 (누적 카드 분모)
- 기초자산은 dailySummary 행별로 오므로 AccountSnapshot에 추가 불필요
- 단, 당일 순입출금액은 account snapshot에 실시간 포함 검토:
  ```ts
  daily_deposit?: number   // 당일 입금액 (실시간)
  ```
  - 당일 카드 분모 = 전일 baseAsset + account.daily_deposit

---

## 5. 아키텍처 원칙 점검

| 원칙 | 부합 여부 | 비고 |
|---|---|---|
| P10 (SSOT) | ✅ | dailySummary가 일별 데이터(기초자산 포함) 단일 소스. account snapshot은 현재 상태 SSOT. |
| P16 (살아있는 경로) | ✅ | 스냅샷 저장이 `_run_post_confirmed_pipeline` 실제 실행 경로에 연결. |
| P20 (폴백 금지) | ⚠️ | baseAsset 없을 때 buyTotal 폴백은 **예외적 허용** (데이터 미축적 기간). 단, 정상 경로의 빈 값을 폴백으로 덮는 것이 아니라 "데이터 없음" 상태 명시 필요. 설계 시 폴백 대신 "데이터 미축적" 표시 검토. |
| P21 (사용자 투명성) | ✅ | 회전율 희석 착시 제거, 복리 자산 변화 반영 → 실제 위험 정확 표시. |
| P22 (데이터 정합성) | ✅ | 기초자산 = 원본(account snapshot)에서 파생. 스냅샷 저장 시점 확정. |
| P23 (일관성) | ✅ | computeCumulativePnl SSOT 유지, 5개 사용처 동일 분모 규칙. |
| P24 (단순성) | ✅ | dailySummary 확장이 API 추가보다 단순. 출금 미지원은 당면 범위 최소화. |
| P25 (격리된 실패) | ✅ | 스냅샷 저장 실패 시 파이프라인 중단 안 함 (warning 로깅). |

### P20 폴백 이슈 상세
- baseAsset이 없는 경우(첫 거래일, 스냅샷 미축적 기간) 분모를 buyTotal로 폴밭하면 B 방식 회전율 희석 재발
- **대안**: baseAsset 없을 때 rate를 `null`로 반환 → UI에 "-" 표시 (P21 투명성)
- but 누적 카드는 accumulated_investment로 정상 동작 (데이터 없음 이슈 없음)
- **결정 필요**: 기간 카드 baseAsset 없을 때 (A) buyTotal 폴백 (B) null 표시 — 태스크 파일에서 사용자 결정 권장

---

## 6. 구현 범위 (태스크 파일 2세션에서 분해 예정)

### 6.1 백엔드 (신규 기능)
1. `account_daily_snapshot` 테이블 생성 (`stock_tables.py`)
2. `save_daily_account_snapshot()` 저장 함수
3. `get_account_snapshot_by_date()` / `get_base_asset_for_period()` 조회 함수
4. `_run_post_confirmed_pipeline`에 저장 호출 추가 (P25 격리)
5. `get_daily_summary` 반환 필드에 `base_asset` 추가 (각 일별 행의 전일 스냅샷)
6. `settlement_engine` 당일 입금액 추적 (`_daily_deposit_total`) + account snapshot에 `daily_deposit` 포함
7. DB 마이그레이션: stocks.db 백업 (db-backup 스킬 필수) → 테이블 생성

### 6.2 프론트엔드 (로직 교체)
1. `computeCumulativePnl` 시그니처 확장 (`baseAsset?` 추가) + 분모 로직 교체
2. `findBaseAssetForDate` 헬퍼 함수 추가
3. `updateSummaryCards` 5개 카드 호출부에 baseAsset 전달
4. `updateStatistics` baseAsset 전달
5. `buildDonutCenter` baseAsset 전달
6. `renderAccountVals` 누적 카드는 baseAsset 없음 (현행 유지)
7. 회귀 테스트: 기초자산 있음/없음 케이스 추가

### 6.3 검증
- 백엔드: pytest (일별 스냅샷 저장/조회 회귀)
- 프론트: typecheck + test + build
- 런타임: `python -W error::RuntimeWarning main.py` (await 누락)
- DB: stocks.db 백업 후 마이그레이션 (db-backup 스킬)

---

## 7. 후순위 (본 설계 범위 외)

- **실전모드 출금 기능**: 현재 출금 API 없음. 출금 지원 시 `_daily_withdrawal_total` 추가.
- **실전모드 A 방식 완전 적용**: 실전도 기초자산 분모 적용 (본 설계에 포함되나, 실전 데이터 검증 별도 필요).
- **기초자산 없는 기간 폴백 정책**: 태스크 파일에서 사용자 결정 권장 (buyTotal 폴백 vs null 표시).

---

## 8. 다음 세션 (태스크 파일) 인계 사항

1. 본 설계의 6.1~6.3 구현 범위를 태스크 단위로 분해
2. P20 폴백 이슈(7번) 사용자 결정 필요 — 태스크 파일에 질문 항목으로 기재
3. DB 마이그레이션 전 db-backup 스킬 실행 필수 (안전 규칙 2)
4. `settlement_engine` 출금 미지원 전제 — 당일 순입출금 = 당일 입금액만
5. dailySummary 확장 방식 채택 (API 추가 방식 배제 — P24 단순성)
