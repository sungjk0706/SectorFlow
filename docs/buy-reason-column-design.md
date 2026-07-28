# 매수 근거 통합 컬럼 설계 (A 방식)

> **상태**: 설계 (구현 미진행 — 규칙 0 준수, 승인 대기)
> **작성일**: 2026-07-28 (재설계 — B 방식 검토 후 A 방식 채택)
> **관련 규칙**: P10(SSOT), P15(단일 주문 경로), P16(살아있는 경로), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(용어 통일), P24(단순성), P25(격리된 실패)
> **관련 스킬**: `db-backup`(스키마 변경 전 백업 필수), `safe-trade`(`record_buy` 호출 경로 수정 시 적용)
> **다단계 워크플로우**: 설계(본 파일) → 태스크 분할 → 구현 (세션당 1단계)

---

## 0. 설계 방식 결정 (A vs B)

### 0.1 사용자 원래 의도
- 매수 체결 시점에 trades 테이블에 매수 근거를 통합 저장
- 포함: 업종명, 매수순위, 고가돌파/뉴스/잔량비율/프로그램순매수 **발생한 것만**
- 예: `"업종: 반도체 · 매수순위: 1위 · 📈고가돌파 · 📰뉴스"`

### 0.2 두 방식 검토

| 방식 | 프론트 컬럼 구성 | 컬럼 수 | DB 컬럼 추가 |
|------|-----------------|---------|-------------|
| **A (채택)** | 기존 "업종"·"매수순위" 컬럼 유지(구조화로 개선) + 가산점 통합 컬럼 1개 신규 | 10 + 1 = 11 | sector, buy_rank 2개 |
| **B (사용자 제안)** | 기존 "업종"·"매수순위" 제거 + 모든 근거 1개 통합 컬럼 | 10 − 2 + 1 = 9 | sector, buy_rank, 가산점 통합 3개 또는 통합 1개 |

### 0.3 A 방식 채택 근거

1. **말줄임 시 핵심 정보 보존 (P21)**: B 통합 컬럼은 가산점 4개 발생 시 약 550–650px 추정. maxWidth 제한 시 가산점(매수 근거 핵심)이 잘림. A는 업종·매수순위가 별도 컬럼이므로 항상 표시 보장.
2. **정렬 기능 유지**: A는 매수순위(숫자)·업종(텍스트) 컬럼별 정렬 가능. B는 혼합 문자열이라 정렬 불가.
3. **컬럼 너비 안정성**: A의 가산점 통합 컬럼은 발생한 가산점만 표시하므로 150px 수준으로 안정.
4. **구현 복잡도 동일**: 백엔드 작업량 A/B 동일. 프론트는 컬럼 정의 방향만 차이.
5. **사용자 승인**: "너의 추천대로 진행해" (2026-07-28)

> **참고**: 사용자가 B 방식 선호 시 차후 전환 가능. A→B는 프론트 컬럼 정의 병합만으로 단순 전환 가능(역방향은 어려움). A가 확장 유연성 확보.

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

3. `trade_history.py:78-96` — `_TRADE_INSERT_SQL`은 18개 컬럼에 INSERT. `sector` 컬럼 없음.
   <ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trade_history.py" lines="78-96" />

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

### 1.4 매수 시점 접근 가능 데이터 (BuyTarget + StockScore)

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/domain/models.py" lines="9-27" />

| 필드 | 출처 | 현재 reason 포함 여부 | 비고 |
|------|------|----------------------|------|
| `s.sector` | StockScore | ✓ (`업종={s.sector}`) | 업종명 (예: "반도체") — 별도 "업종명" 없음, sector 자체가 명칭 |
| `bt.rank` | BuyTarget | ✓ (`순위={bt.rank}`) | 매수 후보 전체 우선순위 |
| `bt.sector_rank` | BuyTarget | ✗ | 업종 내 순위 — reason에 미포함 |
| `s.boost_score` | StockScore | ✗ | 가산점 **합계** (>= 0.0) |
| 개별 가산점 트리거 | `calculate_boost_score()` 내 지역 변수 | ✗ | **미보존** — 합산 후 개별 여부 소실 (P10 위반) |

**개별 가산점 4종** (`backend/app/domain/buy_filter.py:8-64` `calculate_boost_score()`):

| 가산점 | 조건 | 점수 파라미터 | 트리거 판정 |
|--------|------|--------------|-------------|
| 고가돌파 | `boost_high_on` + `cur_price > high_5d` | `boost_high_score` | `high_5d_cache`에서 조회 |
| 잔량비율 | `boost_order_ratio_on` + `ratio >= 1 + abs(pct)/100` | `boost_order_ratio_score` | `orderbook_cache`에서 조회 |
| 프로그램순매수 | `boost_program_net_buy_on` + `net_buy > 0` | `boost_program_net_buy_score` | `program_net_buy_cache`에서 조회 |
| 뉴스 호재 | `boost_news_on` + `news_score > 0` | `boost_news_score` | `news_boost_cache`에서 조회 (5분 TTL) |

> **주의**: 개별 트리거 여부는 `calculate_boost_score()` 내에서만 판정되고 합산 점수만 `StockScore.boost_score`에 저장됨. 매수 체결 시점(`buy_order_executor.py`)에는 `bt.stock.boost_score`(합계)만 접근 가능. 개별 구성요소를 보존하려면 `StockScore`에 개별 트리거 필드 추가(모델 변경) 필요.

### 1.5 매수후보 테이블 컬럼 vs StockScore 필드 (조사 결과)

사용자 질문: "매수후보 테이블의 호가잔량비/프순매/뉴스/5거래일 고가 컬럼 점수를 매수내역 저장 시 활용 가능 여부"

**매수후보 테이블 컬럼** (`frontend/src/pages/buy-target-columns.ts`):
- `order_ratio` (호가잔량비): `t.order_ratio: [bid, ask]` — 프론트 SectorStock 필드
- `program_net_buy` (프순매): `t.program_net_buy` (원 단위) — 프론트 SectorStock 필드
- `news_boost` (📰뉴스): `t.news_boost` (점수) — 프론트 SectorStock 필드
- `high_5d` (5거래일 고가): `t.high_5d` — 프론트 SectorStock 필드

**핵심 발견**: `StockScore`(백엔드)에는 `order_ratio`/`program_net_buy`/`news_boost`/`high_5d` 필드 **없음**. 매수 시점(`buy_order_executor.py:212`)에는 `s = bt.stock`(`StockScore`)만 접근. 프론트 매수후보 테이블의 값들은 백엔드가 WS로 별도 전송한 SectorStock 확장 필드.

**결론**: 매수 시점에 매수후보 테이블 값을 재사용하려면, 백엔드 `StockScore`에 개별 가산점 트리거 필드를 추가하고 `calculate_boost_score()` 시점에 저장해야 함. 매수 시점 캐시 재조회는 P10 위험(캐시 갱신 시점 차이).

### 1.6 "업종명" 별도 존재 여부

코드베이스에서 `s.sector`가 곧 업종명(예: "반도체", "자동차"). 별도의 업종 코드 vs 업종명 구분 없음. `custom_sectors` 테이블이 `name` 컬럼에 업종명 저장. 따라서 **"업종"과 "업종명"은 동일 데이터** — 단일 컬럼으로 통합.

---

## 2. A 방식 설계 — 컬럼 구성 + 표시 형식

### 2.1 프론트엔드 매수내역 테이블 컬럼 (A 방식)

| # | 컬럼명 | 데이터 소스 | 표시 형식 | 기존 대비 변경 |
|---|--------|------------|-----------|---------------|
| 1 | 순번 | 인덱스 | 숫자 | 유지 |
| 2 | 일시 | `r.date` + `r.time` | MM/DD HH:MM | 유지 |
| 3 | 종목코드 | `r.stk_cd` | 코드 | 유지 |
| 4 | 종목명 | `r.stk_nm` + hotStore | 이름 | 유지 |
| 5 | **업종** | `r.sector` (신규 구조화 컬럼) | 텍스트 (예: "반도체") | **변경**: reason 파싱 → 구조화 컬럼 직접 |
| 6 | **매수순위** | `r.buy_rank` (신규 구조화 컬럼) | 숫자 (1, 2, 3...) | **변경**: reason 파싱 → 구조화 컬럼 직접 |
| 7 | 매수가 | `r.price` | 숫자 | 유지 |
| 8 | 수량 | `r.qty` | 숫자 | 유지 |
| 9 | 매수 지출(수수료 포함) | `r.total_amt` | 원 | 유지 |
| 10 | 수수료 | `r.fee` | 원 | 유지 |
| 11 | **매수 근거** (신규) | `r.reason` (가산점 통합 문자열) | "📈고가돌파 · 📰뉴스" | **신규 추가** |

- 기존 "업종"·"매수순위" 컬럼은 유지, 데이터 소스만 reason 파싱 → 구조화 컬럼로 변경 (P10 개선).
- 신규 "매수 근거" 컬럼 1개 추가. 발생한 가산점만 이모지+이름으로 표시.
- 컬럼 수: 10 → 11 (신규 1개 추가).

### 2.2 가산점 통합 문자열 포맷 (reason 컬럼 재사용)

**매수 시 reason 컬럼값** (가산점 통합 문자열):
- 발생한 가산점만 ` · ` 구분자로 연결
- 각 가산점: 이모지 + 한글 이름
- 예: `"📈고가돌파 · 📰뉴스"` (고가돌파·뉴스 발생, 잔량비율·프로그램 미발생)
- 예: `"📈고가돌파 · 📊잔량비율 · 📰뉴스 · 💹프로그램순매수"` (4개 모두 발생)
- 가산점 미발생 시: 빈 문자열 `""` (P20 — 명시적 빈 값, 폴백 금지)

**가산점 이모지+이름 매핑**:

| 가산점 | 트리거 필드 (StockScore) | 표시 문자열 |
|--------|-------------------------|-------------|
| 고가돌파 | `boost_high_triggered` | `📈고가돌파` |
| 잔량비율 | `boost_order_ratio_triggered` | `📊잔량비율` |
| 뉴스 호재 | `boost_news_triggered` | `📰뉴스` |
| 프로그램순매수 | `boost_program_triggered` | `💹프로그램순매수` |

**표시 순서**: 고가돌파 → 잔량비율 → 뉴스 → 프로그램순매수 (고정 순서 — P23 일관성).

### 2.3 매도 reason 처리

- 매도 레코드: 기존 reason 컬럼에 매도 사유("익절"/"손절" 등) 그대로 유지.
- reason 컬럼은 side에 따라 용도 분리:
  - `side="BUY"`: 가산점 통합 문자열 (매수 근거)
  - `side="SELL"`: 매도 사유
- 매도 레코드의 sector/buy_rank는 NULL (매수 근거 아니므로 — P20 폴백 아님).

### 2.4 reason 폴백 제거 (P20)

- `trading.py:518` `_buy_reason = reason or "자동매수"` 폴백 제거.
- 자동매수 시 reason은 `buy_order_executor`에서 생성한 가산점 통합 문자열 명시적 전달.
- 가산점 미발생 시 빈 문자열 `""` 전달 (P20 — 명시적 빈 값).

---

## 3. DB 마이그레이션 범위

### 3.1 컬럼 추가 (구조화 — 파싱 제거)

```sql
ALTER TABLE trades ADD COLUMN sector TEXT;        -- 업종명 (매수에만 값, 매도는 NULL)
ALTER TABLE trades ADD COLUMN buy_rank INTEGER;   -- 매수 후보 전체 순위 (매수에만 값, 매도는 NULL)
```

- 기존 8컬럼 분리 방식 대비 대폭 축소 (8 → 2). 가산점은 기존 reason 컬럼 재사용.
- 마이그레이션 패턴: `migrate_add_buy_date_to_trades()`와 동일 (`PRAGMA table_info` → `ALTER TABLE ADD COLUMN`).
- 매수(BUY) 레코드에만 값 존재. 매도(SELL) 레코드는 NULL.
- 기존 레코드(마이그레이션 전 매수)는 NULL — reason 문자열에서 역추출하지 않음 (P20: 폴백으로 덮지 않음).

### 3.2 reason 컬럼 재사용 (포맷만 변경)

- 기존 reason: `"업종자동매수 업종=X 순위=N"`
- 신규 reason(매수): 가산점 통합 문자열 `"📈고가돌파 · 📰뉴스"`
- 신규 reason(매도): 기존 매도 사유 유지
- 스키마 변경 없음 (기존 TEXT 컬럼). 마이그레이션 불필요.

### 3.3 INSERT SQL 및 record_buy 변경 범위

- `_TRADE_INSERT_SQL`(`trade_history.py:78-84`): 컬럼 2개 추가(sector, buy_rank) → VALUES placeholder 2개 추가
- `_trade_params()`(`trade_history.py:87-96`): rec에서 sector, buy_rank 2개 필드 추가 추출
- `record_buy()`(`trade_history.py:248-285`): rec 딕셔너리에 sector, buy_rank 필드 추가, 시그니처에 sector/buy_rank 인자 추가
- `execute_buy()` 시그니처(`trading.py:257`): sector, buy_rank 인자 추가 (또는 buy_order_executor에서 record_buy 직접 호출 시점에 전달)
- `buy_order_executor.py:229-232`: `bt.stock`에서 sector 추출, `bt.rank`에서 buy_rank 추출, 트리거 필드로 가산점 통합 문자열 생성해 reason 전달

### 3.4 개별 가산점 트리거 보존 (핵심 설계 결정)

**문제**: `calculate_boost_score()`가 합계만 반환, 개별 트리거 여부 소실.

**해결: StockScore 모델에 개별 트리거 필드 4개 추가**:
- `boost_high_triggered`, `boost_news_triggered`, `boost_order_ratio_triggered`, `boost_program_triggered` (bool, 기본값 `False`)
- `calculate_boost_score()` 내에서 각 조건 만족 시 해당 필드 `True` 설정 (합산 로직 유지, 필드 설정만 추가)
- 매수 시점에 `bt.stock`에서 직접 접근해 가산점 통합 문자열 생성

**근거**:
- P10(SSOT): 매수 결정 시점의 정확한 트리거 상태 보존
- P22(데이터 정합성): 매수 결정에 사용된 값과 동일 값 보존
- 매수 시점 캐시 재조회 대안은 P10 위험(캐시 갱신 시점 차이)으로 배제

---

## 4. safe-trade + db-backup 필요성

### 4.1 db-backup (필수)
- **스키마 변경(ALTER TABLE 2개)** 수반 → 안전 규칙 2 + `db-backup` 스킬 적용 필수
- 절차: 앱 종료 → `stocks.db`, `stocks.db-shm`, `stocks.db-wal` 타임스탬프 백업 → 마이그레이션 → 런타임 검증 → 백업 파일 삭제(사용자 승인 후)

### 4.2 safe-trade (필수)
- `record_buy()` 호출 경로 수정 + `execute_buy()` 시그니처 변경 → `safe-trade` 스킬 적용 필수
- 점검 항목:
  - **P15(단일 주문 경로)**: `execute_buy()` → `record_buy()` 경로 유지. 신규 매수 기록 경로 분기 금지.
  - **P16(살아있는 경로)**: 근거 데이터가 `buy_order_executor` → `execute_buy` → `record_buy` → DB까지 단일 경로 배선. dead code(전달되나 저장 안 되는 필드) 금지.
  - **P18(테스트모드 동등성)**: 테스트/실전 모두 동일하게 구조화 근거 저장. 모드 분기 없음.
  - **거래 모드**: 본 변경은 기록 로직만 해당. 주문 발생·리스크 검사·가드 조건 변경 없음.
  - **롤백 여부**: 기존 매수 로직 변경 없음 — 근거 **기록**만 추가하므로 롤백 해당 없음.

### 4.3 다단계 워크플로우 (규칙 0-2-5)

작업 범위:
- 백엔드: 모델(StockScore 필드 4개) + buy_filter + trade_history + trading + buy_order_executor + stock_tables 마이그레이션
- 프론트엔드: profit-columns.ts 파싱 제거 + 구조화 컬럼 직접 표시 + 신규 가산점 컬럼 + 테스트
- DB: 마이그레이션 2개 컬럼 + 백업/검증
- 테스트: 백엔드(buy_filter, trade_history, buy_order_executor) + 프론트엔드(profit-columns)

→ **다단계 워크플로우 전환** (설계 → 태스크 분할 → 구현 세션당 1단계, 총 6세션).

---

## 5. 아키텍처 원칙 부합

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10(SSOT) | ✅ 개선 | reason 문자열 파싱 제거 → 구조화 컬럼(sector, buy_rank) 단일 진실 소스. 개별 트리거 상태 StockScore에 보존 |
| P15(단일 주문 경로) | ✅ 유지 | `execute_buy()` → `record_buy()` 경로 변경 없음, 근거 데이터 전달만 추가 |
| P16(살아있는 경로) | ✅ | 근거 데이터가 `buy_order_executor` → `execute_buy` → `record_buy` → DB까지 단일 배선 |
| P18(테스트모드 동등성) | ✅ | 테스트/실전 모두 동일하게 구조화 근거 저장. 모드 분기 없음 |
| P20(폴백 금지) | ✅ 개선 | `reason or "자동매수"` 폴백 제거. 과거 레코드 NULL 명시적 처리 |
| P21(사용자 투명성) | ✅ 개선 | 매수 근거(어떤 가산점이 기여했는지) 사용자 열람 가능. 핵심 정보(업종·순위) 말줄임 시에도 보존 |
| P22(데이터 정합성) | ✅ | 컬럼 타입 보장, 매수 결정 시점 트리거 상태 보존 |
| P23(용어 통일) | ✅ | "업종"(not 섹터), "매수"(not Buy), "종목"(not 주목) — 컬럼명·표시 텍스트 준수 |
| P24(단순성) | ✅ | 8컬럼 분리 대신 2컬럼 구조화 + reason 재사용. A 방식 채택 (B 대비 말줄임 안정성) |
| P25(격리된 실패) | ✅ | 마이그레이션 실패 시 해당 컬럼 NULL, 기존 체결 이력 조회 영향 없음 |
