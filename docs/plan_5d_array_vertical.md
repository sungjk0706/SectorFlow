# 5일봉 배열 테이블 구조 개선 수정 계획서 — 가로 배열 → 세로 행

> **작성일**: 2026-07-14
> **상태**: 계획 완료, 단계별 진행 대기
> **승인 상태**: 사용자 승인 대기 (각 Step 시작 시 별도 승인 필요)
> **관련 원칙**: P10 (SSOT), P16 (살아있는 경로), P20 (폴백 금지), P22 (데이터 정합성), P23 (일관성), P24 (단순성)

---

## 1. 배경 및 목표

### 1-1. 현재 상태

- `stock_5d_array` 테이블이 가로 배열 구조: `code, date, day1_amount, day2_amount, ..., day5_amount, day1_high, ..., day5_high`
- 각 day별 **실제 날짜가 저장되지 않음** — `date` 컬럼은 API 조회일 1개만 저장
- UI 컬럼명이 "당일", "직전1일", "직전2일" 등 추상적 위치로 고정
- 2026-07-14 버그 수정(rolling 가드, 커밋 대기)로 당일/직전1일 중복 문제는 해결했으나, 근본 구조는 그대로

### 1-2. 목표

가로 배열(`day1~day5`) 구조를 **세로 행**(종목코드 + 날짜 + 거래대금 + 고가) 구조로 변경:

- 각 일봉이 **실제 날짜**와 함께 1행으로 저장
- UI 컬럼명을 "당일/직전1일" → **실제 날짜**(예: "2026-07-14")로 표시
- rolling 로직 제거 — 단순히 해당 날짜 행을 INSERT OR REPLACE
- 5일이 아닌 N일로 확장 시 컬럼 변경 없이 행 추가만으로 가능

### 1-3. 핵심 설계 원칙

- **P10 (SSOT)**: 5일봉 데이터가 세로 행으로 단일 관리, 날짜가 명시적으로 저장되어 의미론 중복 제거
- **P22 (데이터 정합성)**: 각 행이 (종목코드, 날짜) 복합키로 식별, 같은 날 재실행 시 자동 덮어쓰기
- **P24 (단순성)**: rolling 로직("기존 day1을 day2로 밀어내기") 제거, INSERT OR REPLACE만으로 처리

---

## 2. 현재 구조 및 영향 범위

### 2-1. 현재 `stock_5d_array` 테이블 구조

```sql
CREATE TABLE stock_5d_array (
    code TEXT PRIMARY KEY,
    date TEXT,
    day1_amount INTEGER,  -- 백만원 단위
    day2_amount INTEGER,
    day3_amount INTEGER,
    day4_amount INTEGER,
    day5_amount INTEGER,
    day1_high INTEGER,
    day2_high INTEGER,
    day3_high INTEGER,
    day4_high INTEGER,
    day5_high INTEGER
)
```

- 기본키: `code` (종목당 1행)
- 문제: 각 day의 실제 날짜를 알 수 없음

### 2-2. 변경 후 테이블 구조

```sql
CREATE TABLE stock_5d_bars (
    code TEXT NOT NULL,
    dt TEXT NOT NULL,           -- 실제 거래일 (YYYYMMDD)
    trade_amount INTEGER,       -- 백만원 단위
    high_price INTEGER,         -- 원 단위
    PRIMARY KEY (code, dt)
)
```

- 기본키: `(code, dt)` 복합키 (종목×날짜당 1행)
- 테이블명 변경: `stock_5d_array` → `stock_5d_bars` (의미 명확화)
- 5일 제한 없음 — N일치 저장 가능

### 2-3. 영향 받는 파일 (9개)

| 계층 | 파일 | 현재 수정 내용 |
|------|------|------|
| DB 스키마 | `backend/app/db/stock_tables.py` | 테이블 생성 함수 + 마이그레이션 함수 |
| 백엔드 쓰기 | `backend/app/services/market_close_pipeline.py` | `execute_unified_rolling_and_save()`, `fetch_5d_data_only()` |
| 백엔드 읽기 | `backend/app/web/routes/stock_detail.py` | 5d-array API 응답 구조 |
| 프론트엔드 타입 | `frontend/src/api/client.ts` | 응답 타입 |
| 프론트엔드 UI | `frontend/src/pages/stock-detail.ts` | 컬럼 정의 (고정 → 동적 날짜) |
| 테스트 | `backend/tests/test_market_close_pipeline.py` | 기존 테스트 수정 + 신규 테스트 |
| 테스트 | `backend/tests/test_stock_tables.py` | 테이블 생성 테스트 |
| 문서 | `ARCHITECTURE.md` | 스키마 설명 갱신 |
| 핸드오버 | `HANDOVER.md` | 진행 상태 갱신 |

### 2-4. `master_stocks_table` 관계

- `master_stocks_table`의 `avg_5d_trade_amount`, `high_5d_price` 컬럼은 **유지** (파생 데이터)
- 파생 방식 변경: 기존 `day1~5` 배열에서 계산 → `stock_5d_bars`에서 최근 5행으로 계산
- `master_stocks_table.date`는 기존대로 유지 (소속 거래일)

---

## 3. 단계별 수정 계획

### Step 1: DB 스키마 변경 + 마이그레이션 + 백엔드 쓰기 로직

**사전조사**:
- `stock_tables.py` 270-290줄 `create_stock_5d_array_table()` 구조 확인
- `market_close_pipeline.py` `execute_unified_rolling_and_save()` 206-350줄 쓰기 로직 확인
- `market_close_pipeline.py` `fetch_5d_data_only()` 1125-1310줄 쓰기 로직 확인
- 기존 `stock_5d_array` 데이터 존재 여부 확인 (DB 백업 필요 — db-backup 스킬 사용)
- `kiwoom_stock_rest.py` `fetch_ka10081_daily_5d_data()` 응답에 `dt` 필드 포함 확인 (API 명세서 125-129줄)

**수정 내용**:

1. **`stock_tables.py`**:
   - `create_stock_5d_bars_table()` 함수 추가 (기존 `create_stock_5d_array_table()` 대체)
   - `migrate_5d_array_to_bars()` 마이그레이션 함수 추가:
     - 기존 `stock_5d_array`의 `day1~5` 데이터를 세로 행으로 변환
     - 단, 각 day의 실제 날짜를 알 수 없으므로 `date` 컬럼(조회일) 기준으로 추정 불가
     - **마이그레이션 생략**: 기존 데이터는 무효(날짜 모름)이므로 DROP + CREATE로 신규 시작
     - 사용자에게 기존 5일봉 데이터 삭제 안내 (수동 다운로드로 재구성 필요)
   - 기존 `create_stock_5d_array_table()` 함수 제거 (P16 dead code)

2. **`market_close_pipeline.py`**:
   - `execute_unified_rolling_and_save()`:
     - rolling 로직 제거 ("기존 day1을 day2로 밀어내기")
     - `qry_dt` 기반으로 해당 날짜 행을 INSERT OR REPLACE
     - `avg_5d_trade_amount`, `high_5d_price` 계산: `stock_5d_bars`에서 해당 종목의 최근 5행으로 계산
   - `fetch_5d_data_only()`:
     - API 응답의 `amts_5d_array`, `highs_5d_array`와 함께 **각 행의 `dt` 필드**도 수집
     - `kiwoom_stock_rest.py` `fetch_ka10081_daily_5d_data()` 응답에 `dts_5d_array` 추가 필요
     - 세로 행으로 INSERT OR REPLACE
   - `_step5_download_daily_confirmed()`:
     - `qry_dt` 기반으로 해당 날짜 행만 INSERT OR REPLACE

3. **`kiwoom_stock_rest.py`**:
   - `fetch_ka10081_daily_5d_data()` 응답에 `dts_5d_array` 추가 (각 행의 `dt` 필드)

**검증**:
- py_compile, ruff
- pytest (test_market_close_pipeline.py, test_stock_tables.py, test_kiwoom_stock_rest.py)
- 런타임 기동 (`-W error::RuntimeWarning`)
- 잔존 프로세스 0건 확인

**영향 범위**: 3개 백엔드 파일 + 3개 테스트 파일

---

### Step 2: 백엔드 읽기 API + 캐시 계산 로직

**사전조사**:
- `web/routes/stock_detail.py` 16-67줄 `get_stock_detail_5d_array()` 응답 구조 확인
- `market_close_pipeline.py` `_save_confirmed_cache()` 494-614줄 확인
- `sector_data_provider.py` `avg_5d_trade_amount`, `high_5d_price` 사용처 확인

**수정 내용**:

1. **`web/routes/stock_detail.py`**:
   - API 응답 구조 변경:
     ```json
     {
       "date": "20260714",
       "items": [
         {
           "code": "005930",
           "name": "삼성전자",
           "market_type": "0",
           "nxt_enable": false,
           "bars": [
             { "dt": "20260714", "trade_amount": 19467830, "high_price": 270000 },
             { "dt": "20260711", "trade_amount": 15313000, "high_price": 292500 },
             ...
           ]
         }
       ]
     }
     ```
   - `stock_5d_bars`에서 각 종목의 최근 5행을 날짜 내림차순으로 조회
   - 라우트 경로 유지: `/api/stock-detail/5d-array` (하위 호환)

2. **`market_close_pipeline.py`**:
   - `_save_confirmed_cache()`에서 `avg_5d_trade_amount`, `high_5d_price` 계산 로직:
     - 기존: 메모리 캐시의 `avg_5d_trade_amount`/`high_5d_price` 직접 사용
     - 변경: `stock_5d_bars`에서 최근 5행으로 재계산 (P10 SSOT — 파생 데이터는 원본에서 계산)
   - 단, 메모리 캐시의 `avg_5d_trade_amount`/`high_5d_price` 필드는 유지 (성능 — 매 틱마다 DB 조회 방지)
   - 계산 시점: 5일봉/1일봉 다운로드 완료 후 1회만 계산

**검증**:
- py_compile, ruff
- pytest (test_market_close_pipeline.py, test_web_stock_detail.py)
- 런타임 기동 + API 응답 확인 (에이전트가 내부적으로 API 호출 후 결과 보고)
- 잔존 프로세스 0건 확인

**영향 범위**: 2개 백엔드 파일 + 2개 테스트 파일

---

### Step 3: 프론트엔드 타입 + UI (동적 날짜 컬럼)

**사전조사**:
- `frontend/src/api/client.ts` 124-143줄 `getStockDetail5d` 타입 확인
- `frontend/src/pages/stock-detail.ts` 전체 구조 확인 (273줄)
- `frontend/src/components/common/data-table.ts` 동적 컬럼 지원 여부 확인

**수정 내용**:

1. **`frontend/src/api/client.ts`**:
   - `getStockDetail5d` 응답 타입 변경:
     ```typescript
     getStockDetail5d: () =>
       request<{
         date: string;
         items: Array<{
           code: string;
           name: string;
           market_type: string;
           nxt_enable: boolean;
           bars: Array<{
             dt: string;          // YYYYMMDD
             trade_amount: number | null;  // 백만원 단위
             high_price: number | null;    // 원 단위
           }>;
         }>;
       }>('/api/stock-detail/5d-array'),
     ```

2. **`frontend/src/pages/stock-detail.ts`**:
   - `StockDetail5dItem` 인터페이스 변경: `day1_amount~day5_amount, day1_high~day5_high` → `bars: Array<{dt, trade_amount, high_price}>`
   - 컬럼 정의를 **동적 생성**으로 변경:
     - 데이터 로드 후 `bars`의 `dt` 필드에서 날짜 추출
     - 각 날짜별로 거래대금 컬럼 + 고가 컬럼 생성
     - 컬럼명: `2026-07-14 거래대금(억)`, `2026-07-14 고가` 형식
     - 날짜 포맷: `YYYYMMDD` → `YYYY-MM-DD` 변환
   - `fmtAmount`, `fmtHigh` 함수는 그대로 유지
   - `makeAmountColumn`, `makeHighColumn` → 동적 키 지원으로 수정
   - 검색 필터: `bars` 배열 내부 검색이 아닌 종목명/코드 기준 유지

3. **날짜 포맷팅**:
   - `YYYYMMDD` → `MM-DD` (컬럼명용, 연도는 기준일에 표시)
   - 또는 `YYYY-MM-DD` 전체 표시 (사용자 선택 가능)

**검증**:
- `tsc --noEmit` 통과
- `vite build` 통과
- 브라우저 확인 (종목상세 화면에서 날짜 컬럼명 표시, 거래대금/고가 값 표시)
- 잔존 프로세스 0건 확인

**영향 범위**: 2개 프론트엔드 파일

---

### Step 4: 테스트 전면 수정 + 문서 갱신

**사전조사**:
- `test_market_close_pipeline.py` 기존 테스트 중 `day1_amount` 등 참조하는 모든 테스트 확인
- `test_stock_tables.py` `create_stock_5d_array_table` 테스트 확인
- `test_kiwoom_stock_rest.py` `fetch_ka10081_daily_5d_data` 테스트 확인
- `ARCHITECTURE.md` 5일봉 배열 관련 설명 확인

**수정 내용**:

1. **`test_market_close_pipeline.py`**:
   - `TestExecuteUnifiedRollingAndSave` 클래스:
     - 기존 `day1_amount~day5_amount` 참조 테스트 → `stock_5d_bars` 세로 행 검증으로 변경
     - `test_rolling_guard_same_day_skips_rolling` → `test_same_day_upsert_no_duplicate` (같은 날 재실행 시 덮어쓰기 검증)
     - `test_rolling_normal_new_day` → `test_new_day_insert_new_row` (새 날짜 행 추가 검증)
   - `TestFetch5dDataOnly` 클래스:
     - mock 응답에 `dts_5d_array` 추가
     - 세로 행 INSERT 검증

2. **`test_stock_tables.py`**:
   - `TestCreateStock5dArrayTable` → `TestCreateStock5dBarsTable`로 변경
   - 테이블 구조 검증 (복합키, 컬럼명)

3. **`test_kiwoom_stock_rest.py`**:
   - `TestFetchKa10081Daily5dData` 클래스:
     - 응답에 `dts_5d_array` 포함 검증 추가

4. **`ARCHITECTURE.md`**:
   - `stock_5d_array` → `stock_5d_bars` 스키마 설명 갱신
   - 5일봉 배열 데이터 모델 설명 갱신 (가로 → 세로)

5. **`HANDOVER.md`**:
   - 진행 상태 갱신 (Step 1~4 완료)

**검증**:
- py_compile, ruff
- pytest 전체 (test_market_close_pipeline + test_stock_tables + test_kiwoom_stock_rest)
- `tsc --noEmit`, `vite build`
- 런타임 기동 (`-W error::RuntimeWarning`)
- 잔존 프로세스 0건 확인

**영향 범위**: 3개 테스트 파일 + 2개 문서 파일

---

## 4. 마이그레이션 주의사항

### 4-1. 기존 `stock_5d_array` 데이터 처리

- 기존 가로 배열 데이터는 각 day의 **실제 날짜를 알 수 없음** (날짜 모호성이 버그의 근본 원인)
- 따라서 마이그레이션(데이터 변환)은 **수행하지 않음** — 기존 데이터는 무효
- Step 1에서 `DROP TABLE stock_5d_array` + `CREATE TABLE stock_5d_bars`로 신규 시작
- 사용자 안내: "기존 5일봉 데이터가 삭제됩니다. 앱 기동 후 5일봉 다운로드를 다시 실행해 주세요."

### 4-2. DB 백업 (필수)

- Step 1 시작 전 **반드시** db-backup 스킬로 `stocks.db` 백업
- 스키마 변경(테이블 DROP/CREATE)이 포함되므로 백업은 필수

### 4-3. `master_stocks_table` 파생 데이터

- `avg_5d_trade_amount`, `high_5d_price`는 Step 1에서 0으로 초기화
- Step 2에서 `stock_5d_bars` 기반으로 재계산
- Step 1 완료 후 사용자가 5일봉 다운로드를 실행하면 정상 값으로 갱신됨

---

## 5. 세션 진행 순서

| 세션 | Step | 작업 | 검증 |
|------|------|------|------|
| 1 | Step 1 | DB 스키마 + 백엔드 쓰기 | pytest + 런타임 기동 |
| 2 | Step 2 | 백엔드 읽기 API + 캐시 | pytest + 런타임 + API 확인 |
| 3 | Step 3 | 프론트엔드 타입 + UI | tsc + vite build + 브라우저 |
| 4 | Step 4 | 테스트 + 문서 | pytest + tsc + 런타임 기동 |

각 세션은 HANDOVER.md 기반으로 이어서 진행 (세션당 1단계 원칙 준수).

---

## 6. 완료 기준

- [ ] `stock_5d_bars` 테이블이 세로 행 구조로 생성됨
- [ ] 5일봉/1일봉 다운로드 시 세로 행으로 저장됨
- [ ] 종목상세 화면에서 컬럼명이 실제 날짜로 표시됨
- [ ] 같은 날 재실행 시 중복 없이 덮어쓰기됨
- [ ] `avg_5d_trade_amount`, `high_5d_price`가 `stock_5d_bars` 기반으로 계산됨
- [ ] 모든 테스트 통과
- [ ] 런타임 기동 정상
- [ ] ARCHITECTURE.md 갱신 완료
