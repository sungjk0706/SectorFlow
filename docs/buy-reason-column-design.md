# 매수 근거 통합 컬럼 설계

> **상태**: 설계 (구현 미진행 — 규칙 0 준수, 승인 대기)
> **작성일**: 2026-07-28
> **관련 규칙**: P10(SSOT), P15(단일 주문 경로), P16(살아있는 경로), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(용어 통일), P24(단순성), P25(격리된 실패)
> **관련 스킬**: `db-backup`(스키마 변경 전 백업 필수), `safe-trade`(`record_buy` 호출 경로 수정 시 적용)
> **다단계 워크플로우**: 설계(본 파일) → 태스크 분할 → 구현 (세션당 1단계)

---

## 1. 현재 상태 조사

### 1.1 trades 테이블 스키마

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/db/stock_tables.py" lines="22-42" />

```sql
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    side TEXT NOT NULL,           -- "BUY" | "SELL"
    stk_cd TEXT NOT NULL,
    stk_nm TEXT,
    price INTEGER,
    qty INTEGER,
    total_amt INTEGER,
    fee INTEGER,
    tax INTEGER,
    avg_buy_price INTEGER,
    buy_total_amt INTEGER,
    realized_pnl INTEGER,
    pnl_rate REAL,
    reason TEXT,                  -- ← 매수 근거가 문자열로 저장되는 유일한 컬럼
    trade_mode TEXT NOT NULL,
    buy_date TEXT                 -- 마이그레이션 추가 컬럼(migrate_add_buy_date_to_trades)
)
```

- 업종·순위·가산점을 저장하는 구조화 컬럼 없음. `reason TEXT` 단일 컬럼에 문자열로 통합 저장.
- 기존 마이그레이션 패턴: `migrate_add_buy_date_to_trades()`(<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/db/stock_tables.py" lines="260-277" />) — `PRAGMA table_info`로 컬럼 존재 확인 후 `ALTER TABLE ADD COLUMN`, 앱 기동 시 1회 실행(`app.py:53`).

### 1.2 reason 컬럼 사용 현황 (데이터 흐름)

**매수 reason 생성 단일 경로**:

1. `buy_order_executor.py:231` — 매수 시도 시 reason 문자열 생성
   <ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/buy_order_executor.py" lines="229-232" />
   ```python
   _ordered, _reason = await state.auto_trade.execute_buy(
       s.code, float(_price), state.access_token or "",
       reason=f"업종자동매수 업종={s.sector} 순위={bt.rank}",
   )
   ```
   - `s.sector`: `StockScore.sector` (예: "반도체") — `custom_sectors` 테이블 기반 업종명
   - `bt.rank`: `BuyTarget.rank` — 매수 후보 전체 우선순위(정렬 후 1, 2, 3...)
   - `bt.sector_rank`: `BuyTarget.sector_rank` — 업종 내 순위(별도 필드지만 reason에 미포함)

2. `trading.py:518` — `execute_buy()` 내부에서 `record_buy()`로 전달
   <ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trading.py" lines="517-524" />
   ```python
   _buy_reason = reason or "자동매수"   # ← 빈 reason 폴백 (P20 위반 소지 — 명시적 값 아님)
   await trade_history.record_buy(
       stk_cd=stk_cd, stk_nm=stk_nm,
       price=fill_price, qty=buy_qty,
       reason=_buy_reason, trade_mode=_mode,
   )
   ```

3. `trade_history.py:248-285` — `record_buy()`가 rec 딕셔너리에 `reason` 필드 저장
   <ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trade_history.py" lines="78-96" />
   - `_TRADE_INSERT_SQL`은 18개 컬럼에 INSERT. `sector` 컬럼 없음.

**매도 reason**: `record_sell()`(<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trade_history.py" lines="296-365" />) — 매도 사유(예: "익절", "손절")가 `reason`으로 저장. 매도 rec에는 `sector` 필드를 `_lookup_sector()`로 조회해 추가(line 316, 354)하나, **DB INSERT SQL에 sector 컬럼이 없어 영속화되지 않음** (메모리 + WS 전송 전용 — 프론트 도넛 차트 집계용).

### 1.3 프론트엔드 reason 파싱 (P10 위반)

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/pages/profit-columns.ts" lines="9-39" />

```typescript
const _BUY_REASON_SECTOR = /업종=([^ ]+)/
const _BUY_REASON_RANK = /순위=(\d+)/
function parseBuyReasonSector(reason: unknown): string {
  const m = _BUY_REASON_SECTOR.exec(String(reason ?? ''))
  return m ? m[1] : ''    // ← 매칭 실패 시 빈 문자열 (P20 폴백과 동일 위험)
}
```

- 수익 상세 페이지 매수 테이블의 "업종"·"매수순위" 컬럼이 reason 문자열 정규식 파싱으로 표시.
- **P10(SSOT) 위반**: 구조화 데이터를 문자열에서 역추출. reason 포맷 변경 시 파서가 조용히 빈 값 표시.
- 매수 후보 테이블의 "원인" 컬럼(<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/pages/buy-target-columns.ts" lines="148-161" />)은 `bt.reason`(차단 사유: "보유중"/"금일매수"/상승률 차단 등)을 표시 — 체결 이력 reason과는 다른 용도.

### 1.4 매수 시점 접근 가능 데이터 (BuyTarget + StockScore)

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/domain/models.py" lines="9-55" />

| 필드 | 출처 | 현재 reason 포함 여부 | 비고 |
|------|------|----------------------|------|
| `s.sector` | StockScore | ✓ (`업종={s.sector}`) | 업종명 (예: "반도체") — 별도 "업종명" 없음, sector 자체가 명칭 |
| `bt.rank` | BuyTarget | ✓ (`순위={bt.rank}`) | 매수 후보 전체 우선순위 |
| `bt.sector_rank` | BuyTarget | ✗ | 업종 내 순위 — reason에 미포함 |
| `s.boost_score` | StockScore | ✗ | 가산점 **합계** (>= 0.0) |
| 개별 가산점 트리거 | `calculate_boost_score()` 내 지역 변수 | ✗ | **미보존** — 합산 후 개별 여부 소실 (P10 위반, HANDOVER 기록) |
| `s.change_rate` | StockScore | ✗ | 등락률 — 매수 시점 값 |
| `s.cur_price` | StockScore | ✗ | 현재가 — 체결가와 다를 수 있음 |
| `s.avg_amt_5d` | StockScore | ✗ | 5거래일 평균 거래대금 |

**개별 가산점 4종** (`buy_filter.py:8-64` `calculate_boost_score()`):

| 가산점 | 조건 | 점수 파라미터 | 트리거 판정 |
|--------|------|--------------|-------------|
| 고가돌파 | `boost_high_on` + `cur_price > high_5d` | `boost_high_score` | `high_5d_cache`에서 조회 |
| 잔량비율 | `boost_order_ratio_on` + `ratio >= 1 + abs(pct)/100` | `boost_order_ratio_score` | `orderbook_cache`에서 조회 |
| 프로그램순매수 | `boost_program_net_buy_on` + `net_buy > 0` | `boost_program_net_buy_score` | `program_net_buy_cache`에서 조회 |
| 뉴스 호재 | `boost_news_on` + `news_score > 0` | `boost_news_score` | `news_boost_cache`에서 조회 (5분 TTL) |

> **주의**: 개별 트리거 여부는 `calculate_boost_score()` 내에서만 판정되고 합산 점수만 `StockScore.boost_score`에 저장됨. 매수 체결 시점(`buy_order_executor.py`)에는 `bt.stock.boost_score`(합계)만 접근 가능. 개별 구성요소를 보존하려면 `StockScore`에 개별 트리거 필드 추가(모델 변경) 또는 매수 시점에 캐시에서 재조회 필요.

### 1.5 업종 점수 3단계 가산점 (SectorScore — 업종 단위)

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/domain/models.py" lines="31-46" />

- `bonus_rise_ratio`(1차): 업종 간 상승비율 순위 → tiered 점수
- `bonus_relative_strength`(2차): 통과 업종 종목들 가중 순위 합 → tiered 점수
- `bonus_trade_amount`(3차): 업종 간 거래대금 순위 → tiered 점수
- `final_score` = 1차 + 2차 + 3차

> 이들은 **업종 단위** 점수로, 매수 종목 개별 근거가 아님. 사용자 요청 "가산점(고가돌파, 뉴스, 잔량비율, 프로그램)"은 **종목 단위** 4개 가산점(§1.4)을 가리킴. 업종 단위 3단계 가산점은 매수 근거 컬럼에 포함하지 않는 것을 권장(혼란 방지 — P23 용어 명확성). 단, 업종 순위(`sc.rank`) 자체는 매수 근거에 포함 가능.

### 1.6 "업종명" 별도 존재 여부

코드베이스에서 `s.sector`가 곧 업종명(예: "반도체", "자동차"). 별도의 업종 코드 vs 업종명 구분 없음. `custom_sectors` 테이블이 `name` 컬럼에 업종명 저장. 따라서 **"업종"과 "업종명"은 동일 데이터** — 사용자 요청의 "업종, 업종명"은 단일 컬럼으로 통합 가능.

---

## 2. 포함할 조건 목록 + 표시 형식

### 2.1 매수 근거 컬럼 후보

| # | 컬럼명(제안) | 데이터 | 현재 상태 | 표시 형식 제안 |
|---|-------------|--------|-----------|---------------|
| 1 | `sector` | 업종명 (`s.sector`) | reason 문자열에 포함 | 텍스트 (예: "반도체") |
| 2 | `sector_rank` | 업종 순위 (`bt.sector_rank` 또는 `sc.rank`) | reason에 미포함 | 정수 (1, 2, 3...) |
| 3 | `buy_rank` | 매수 후보 전체 순위 (`bt.rank`) | reason 문자열에 포함 | 정수 (1, 2, 3...) |
| 4 | `boost_score` | 종목 가산점 합계 (`s.boost_score`) | 미포함 | 소수점 1자리 (예: 3.0) |
| 5 | `boost_high` | 고가돌파 트리거 여부 | 미보존 | 불리언 (0/1) 또는 점수 |
| 6 | `boost_news` | 뉴스 호재 트리거 여부 | 미보존 | 불리언 (0/1) 또는 점수 |
| 7 | `boost_order_ratio` | 잔량비율 트리거 여부 | 미보존 | 불리언 (0/1) 또는 점수 |
| 8 | `boost_program` | 프로그램순매수 트리거 여부 | 미보존 | 불리언 (0/1) 또는 점수 |

### 2.2 표시 형식 옵션

**옵션 A — 개별 트리거 불리언(0/1)**:
- 각 가산점이 매수 결정에 기여했는지 여부만 저장 (점수 합계는 `boost_score`로 별도 저장)
- 장점: 단순(P24), 사용자가 "어떤 근거로 들어갔는지" 직관적 파악(P21)
- 단점: 점수 가중치 변경 이력은 알 수 없음(설정값 자체는 별도 이력 미관리)

**옵션 B — 개별 점수 저장**:
- 각 가산점의 부여 점수(예: 1.0)를 저장
- 장점: 점수 합계 검증 가능(P22 정합성)
- 단점: 점수 합 = `boost_score`이므로 중복(P10/P24), 설정값 변경 시점에 따라 의미 달라짐

**추천: 옵션 A (불리언 0/1)** — P24 단순성 + P21 사용자 투명성. 점수 합계는 `boost_score` 단일 컬럼으로 충분.

### 2.3 reason 문자열 처리

- 기존 reason 문자열 `"업종자동매수 업종={sector} 순위={rank}"`는 **구조화 컬럼 도입 후 제거** (P10 SSOT — 문자열 파싱 제거).
- `reason` 컬럼은 자동매수가 아닌 수동 주문·기타 사유용으로 유지(빈 문자열 허용 = 자동매수).
- 프론트 `parseBuyReasonSector`/`parseBuyReasonRank` 정규식 파싱 제거 → 구조화 컬럼 직접 표시.
- `trading.py:518` `_buy_reason = reason or "자동매수"` 폴백 제거 — 자동매수 시 reason 빈 문자열 명시적 전달(P20).

---

## 3. DB 마이그레이션 범위 (스키마 변경 vs 기존 컬럼 활용)

### 3.1 옵션 비교

| 옵션 | 방식 | P10 부합 | P22 부합 | 쿼리 용이성 | 마이그레이션 부담 |
|------|------|----------|----------|------------|------------------|
| **A. reason 문자열 확장** | 기존 `reason TEXT`에 더 많은 키=값 추가 | ✗ (파싱 의존 심화) | ✗ | ✗ (LIKE/정규식만) | 없음 |
| **B. JSON 문자열** | `reason`에 JSON 저장 | ✗ (여전 파싱) | △ | ✗ (SQLite JSON 함수 필요) | 없음 |
| **C. 구조화 컬럼 추가** | `sector`, `sector_rank`, `buy_rank`, `boost_score`, `boost_high`, `boost_news`, `boost_order_ratio`, `boost_program` 컬럼 신규 추가 | ✓ | ✓ | ✓ | ALTER TABLE 8개 |
| **D. 별도 테이블** | `trade_buy_reasons` 테이블(trades.id FK) | ✓ | ✓ | ✓ (JOIN) | 테이블 신규 + 조인 부담 |

### 3.2 추천: 옵션 C (구조화 컬럼 추가)

**근거**:
- **P10(SSOT)**: 업종·순위·가산점이 단일 컬럼에 구조화 저장 → 문자열 파싱 제거
- **P22(데이터 정합성)**: 컬럼 단위 타입 보장, NULL/빈 값 명시적 처리
- **P24(단순성)**: 옵션 D(JOIN) 대비 단일 테이블 조회. 매수 1건당 근거 1행(1:1)이므로 별도 테이블 분리는 과잉 추상화
- **기존 패턴 일치**: `migrate_add_buy_date_to_trades()`와 동일하게 `ALTER TABLE ADD COLUMN` + 기동 시 1회 마이그레이션

**마이그레이션 스키마 (제안)**:

```sql
ALTER TABLE trades ADD COLUMN sector TEXT;              -- 업종명
ALTER TABLE trades ADD COLUMN sector_rank INTEGER;      -- 업종 순위
ALTER TABLE trades ADD COLUMN buy_rank INTEGER;         -- 매수 후보 전체 순위
ALTER TABLE trades ADD COLUMN boost_score REAL;         -- 종목 가산점 합계
ALTER TABLE trades ADD COLUMN boost_high INTEGER;       -- 고가돌파 트리거 (0/1)
ALTER TABLE trades ADD COLUMN boost_news INTEGER;       -- 뉴스 호재 트리거 (0/1)
ALTER TABLE trades ADD COLUMN boost_order_ratio INTEGER;-- 잔량비율 트리거 (0/1)
ALTER TABLE trades ADD COLUMN boost_program INTEGER;    -- 프로그램순매수 트리거 (0/1)
```

- 매수(BUY) 레코드에만 값 존재. 매도(SELL) 레코드는 NULL(명시적 미적용 — P20 폴백 아님).
- 기존 레코드(마이그레이션 전 매수)는 NULL — reason 문자열에서 역추출하지 않음(P20: 폴백으로 덮지 않음). 과거 이력은 기존 reason 문자열 그대로 두되 프론트는 구조화 컬럼 우선 표시, NULL 시 reason 파싱 폴백(선택).

### 3.3 INSERT SQL 및 record_buy 변경 범위

- `_TRADE_INSERT_SQL`(`trade_history.py:78-84`): 컬럼 8개 추가 → VALUES placeholder 8개 추가
- `_trade_params()`(`trade_history.py:87-96`): rec에서 8개 필드 추가 추출
- `record_buy()`(`trade_history.py:248-285`): rec 딕셔너리에 8개 필드 추가
- `execute_buy()` 시그니처(`trading.py:257`): `reason: str` 외에 구조화 근거 데이터 전달 필요 (또는 `record_buy` 직접 호출 시점에 `buy_order_executor`에서 전달)
- `buy_order_executor.py:229-232`: `bt.stock`에서 boost_score, 개별 트리거, sector, sector_rank, rank 추출해 전달

### 3.4 개별 가산점 트리거 보존 방안 (핵심 설계 결정)

**문제**: `calculate_boost_score()`가 합계만 반환, 개별 트리거 여부 소실.

**옵션 1 — StockScore 모델에 개별 트리거 필드 추가**:
- `StockScore`에 `boost_high_triggered`, `boost_news_triggered`, `boost_order_ratio_triggered`, `boost_program_triggered` (bool) 필드 추가
- `calculate_boost_score()` 내에서 각 조건 만족 시 해당 필드 True 설정
- 매수 시점에 `bt.stock`에서 직접 접근
- 장점: 매수 결정 시점의 정확한 트리거 상태 보존 (P10 SSOT)
- 단점: 모델 변경 + `calculate_boost_score()` 수정 + 테스트 영향

**옵션 2 — 매수 시점에 캐시에서 재조회**:
- `buy_order_executor.py`에서 `get_high_price_5d_cache()`, `get_orderbook_cache()`, `get_program_net_buy_cache()`, `get_news_boost_cache()`로 재조회
- 장점: 모델 변경 없음
- 단점: 매수 시도 시점과 `calculate_boost_score()` 실행 시점 사이 캐시 갱신 가능 → **P10 위반**(매수 결정에 사용된 값과 다를 수 있음). 매수 틱 핸들러에 캐시 조회 추가 = P7(틱 핸들러 연산) 부담

**추천: 옵션 1** — 매수 결정에 실제 사용된 트리거 상태를 보존해야 P10/P22 부합. 옵션 2는 재조회 시점 차이로 정합성 위험.

---

## 4. safe-trade + db-backup 필요성

### 4.1 db-backup (필수)

- **스키마 변경(ALTER TABLE 8개)** 수반 → 안전 규칙 2 + `db-backup` 스킬 적용 필수
- 절차: 앱 종료 → `stocks.db`, `stocks.db-shm`, `stocks.db-wal` 타임스탬프 백업 → 마이그레이션 → 런타임 검증 → 백업 파일 삭제(사용자 승인 후)
- 백업 파일 삭제 전 런타임 기동 + 핵심 데이터 조회(체결 이력, 잔고) 정상 확인

### 4.2 safe-trade (필수)

- `record_buy()` 호출 경로 수정 + `execute_buy()` 시그니처 변경 → `safe-trade` 스킬 적용 필수
- 점검 항목:
  - **P15(단일 주문 경로)**: `execute_buy()` → `record_buy()` 경로 유지. 신규 매수 기록 경로 분기 금지.
  - **P16(살아있는 경로)**: 구조화 근거 데이터가 `buy_order_executor` → `execute_buy` → `record_buy` → DB까지 단일 경로 배선. dead code(전달되나 저장 안 되는 필드) 금지.
  - **P18(테스트모드 동등성)**: 테스트/실전 모두 동일하게 구조화 근거 저장. 모드 분기 없음.
  - **거래 모드**: `TRADE_MODE`/`is_test_mode` 확인 — 본 변경은 기록 로직만 해당하므로 모의투자/실전 모두 안전. 주문 발생 자체는 변경 없음.
  - **롤백 여부**: 기존 매수 로직(조건·주문 경로·리스크 검사) 변경 없음 — 근거 **기록**만 추가하므로 롤백 해당 없음.

### 4.3 다단계 워크플로우 전환 검토 (규칙 0-2-5)

작업 범위 분석:
- 백엔드: 모델(StockScore 필드 4개) + buy_filter + trade_history + trading + buy_order_executor + stock_tables 마이그레이션
- 프론트엔드: profit-columns.ts 파싱 제거 + 구조화 컬럼 표시 + 테스트
- DB: 마이그레이션 8개 컬럼 + 백업/검증
- 테스트: 백엔드(trade_history, buy_filter, buy_order_executor) + 프론트엔드(profit-columns)

→ **다단계 워크플로우 전환 권장** (설계 → 태스크 → 구현 세션 분할). 거래 로직은 돈 직결이므로 영향 범위 상세 설명 후 사용자 승인 필요.

---

## 5. 추천 구현 순서 (참고용 — 구현은 별도 세션)

> 본 섹션은 구현 시 참고용. 승인 전 코드 수정 금지(규칙 0).

1. **백엔드 모델 + 가산점 보존**: `StockScore`에 개별 트리거 필드 4개 추가 → `calculate_boost_score()`에서 트리거 시 필드 설정 → 테스트
2. **DB 마이그레이션**: `migrate_add_buy_reason_columns_to_trades()` 추가 → `app.py` 기동 시 호출 → db-backup 절차
3. **record_buy + INSERT SQL**: `_TRADE_INSERT_SQL` 컬럼 8개 추가 → `record_buy()` 시그니처 확장 → `_trade_params()` 수정
4. **execute_buy + buy_order_executor**: 근거 데이터 전달 경로 배선 → reason 문자열 생성 제거(빈 문자열 명시)
5. **프론트엔드**: `profit-columns.ts` 정규식 파싱 제거 → 구조화 컬럼 표시 → 테스트
6. **문서 갱신**: 본 설계 문서 상태 갱신 + HANDOVER

---

## 6. 미해결 결정 사항 (사용자 확인 필요)

> 구현 진행 전 아래 항목 확정 필요.

1. **개별 가산점 표현**: 불리언(0/1) vs 점수 저장 — 추천 불리언(§2.2)
2. **sector_rank 출처**: `bt.sector_rank`(업종 내 종목 정렬 순위) vs `sc.rank`(업종 강도 순위) — 사용자 요청 "순위"가 매수순위(`bt.rank`)만 의미하는지, 업종 순위도 포함인지 확인
3. **과거 레코드 처리**: 마이그레이션 전 매수 레코드의 구조화 컬럼 NULL → 프론트 표시 시 reason 문자열 파싱 폴백 유지 여부 (P20: 폴백 금지 원칙과 충돌 — 과거 데이터는 빈 값 표시 권장)
4. **다단계 워크플로우 전환**: 본 작업을 설계→태스크→구현 3세션 이상으로 분할 진행할지 (규칙 0-2-5 — 작업량 큼, 거래 로직 돈 직결)

---

## 7. P원칙 부합 점검

| 원칙 | 부합 여부 | 비고 |
|------|----------|------|
| P10(SSOT) | ✓ 개선 | reason 문자열 파싱 제거 → 구조화 컬럼 단일 진실 소스 |
| P15(단일 주문 경로) | ✓ 유지 | `execute_buy()` → `record_buy()` 경로 변경 없음, 근거 데이터 전달만 추가 |
| P16(살아있는 경로) | ✓ | 근거 데이터가 기록 경로까지 단일 배선. dead field(전달되나 미사용) 금지 |
| P20(폴백 금지) | ✓ 개선 | `reason or "자동매수"` 폴백 제거, 과거 레코드 NULL 명시적 처리 |
| P21(사용자 투명성) | ✓ 개선 | 매수 근거(어떤 가산점이 기여했는지) 사용자 열람 가능 |
| P22(데이터 정합성) | ✓ | 컬럼 타입 보장, 매수 결정 시점 트리거 상태 보존(옵션 1) |
| P23(용어 통일) | ✓ | "업종"(not 섹터), "매수"(not Buy), "종목"(not 주식) — 컬럼명·표시 텍스트 준수 |
| P24(단순성) | ✓ | 별도 테이블(옵션 D) 대신 단일 테이블 컬럼 추가. 불리언(옵션 A) 채택 |
| P25(격리된 실패) | ✓ | 마이그레이션 실패 시 해당 컬럼 NULL, 기존 체결 이력 조회 영향 없음 |
