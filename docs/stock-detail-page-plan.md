# 종목상세 페이지 구현 계획서

## 목적

일반 사용자가 DB를 직접 열지 않고, 웹 UI에서 매매적격종목별 5일봉 거래대금 배열 및 5일봉 고가를 테이블로 확인할 수 있도록 신규 페이지를 추가.

## UI 기준 설명

- **한 문장 요약**: 각 종목의 최근 5일간 거래대금과 고가를 한 눈에 보여주는 페이지.
- **비유**: 마트에서 과일을 살 때, 과일마다 최근 5일간 가격 변동과 최고가를 표시한 표를 보고 적정가를 판단하는 것과 같음.
- **실제 화면**: 사이드바 "종목상세" 메뉴 클릭 → 페이지 상단에 기준일 + 검색 입력란 (종목명 또는 종목코드) 표시 → 전체 종목 테이블 표시 (종목코드 / 종목명 / 직전4일 거래대금 / 직전3일 / 직전2일 / 직전1일 / 당일 / 직전4일 고가 / 직전3일 / 직전2일 / 직전1일 / 당일). 검색어 입력 시 매칭된 행이 하이라이트(노란색 배경)로 표시되고 매칭되지 않은 행은 흐리게(dim) 표시됨.
- **마무리**: 매매 필터링 기준값(5일봉 거래대금, 5일 고가)을 사용자가 직관적으로 확인 가능.

---

## 구현 단계 (세션별 분할)

### Step 1: Backend API 엔드포인트 추가

**파일**: `backend/app/web/routes/stock_detail.py` (신규)

**내용**:
- `APIRouter(prefix="/api", tags=["stock-detail"])`
- GET `/api/stock-detail/5d-array` 엔드포인트
- `stock_5d_array` 테이블과 `master_stocks_table`을 LEFT JOIN하여 종목명 포함
- 응답 형식:
  ```json
  {
    "date": "20260707",
    "items": [
      {
        "code": "005930",
        "name": "삼성전자",
        "day1_amount": 1200000,
        "day2_amount": 1100000,
        "day3_amount": null,
        "day4_amount": null,
        "day5_amount": null,
        "day1_high": 78000,
        "day2_high": 77000,
        "day3_high": null,
        "day4_high": null,
        "day5_high": null
      }
    ]
  }
  ```
- 단위: 거래대금은 백만원 (DB 저장 단위 그대로), 고가는 원 (DB 저장 단위 그대로)
- 정렬: 종목코드 오름차순

**SQL 쿼리**:
```sql
SELECT
    a.code, a.date,
    a.day1_amount, a.day2_amount, a.day3_amount, a.day4_amount, a.day5_amount,
    a.day1_high, a.day2_high, a.day3_high, a.day4_high, a.day5_high,
    m.name
FROM stock_5d_array a
LEFT JOIN master_stocks_table m ON a.code = m.code
ORDER BY a.code
```

**등록**: `backend/app/web/app.py`에 import + `app.include_router(stock_detail_router)` 추가

**아키텍처 원칙 부합**:
- 원칙 2 (async def): `async def` 엔드포인트
- 원칙 6 (Raw SQL): ORM 없이 Raw SQL 직통
- 원칙 10 (SSOT): `stock_5d_array` DB 테이블에서 읽기만 함 (데이터 복제 없음)
- 원칙 12 (DB 연결 공유): `get_db_connection()` 사용

**검증**: `py_compile` + 수동 curl 테스트

---

### Step 2: Frontend API 클라이언트 함수 추가

**파일**: `frontend/src/api/client.ts` (수정)

**내용**: `api` 객체에 `getStockDetail5d` 함수 추가
```typescript
getStockDetail5d: () =>
  request<{
    date: string;
    items: Array<{
      code: string;
      name: string;
      day1_amount: number | null;
      day2_amount: number | null;
      day3_amount: number | null;
      day4_amount: number | null;
      day5_amount: number | null;
      day1_high: number | null;
      day2_high: number | null;
      day3_high: number | null;
      day4_high: number | null;
      day5_high: number | null;
    }>;
  }>('/api/stock-detail/5d-array'),
```

**검증**: `npm run build` (TypeScript 타입 체크)

---

### Step 3: Frontend 페이지 컴포넌트 추가

**파일**: `frontend/src/pages/stock-detail.ts` (신규)

**내용**:
- `PageModule` 인터페이스 구현 (`mount`, `unmount`)
- `full` 레이아웃 사용 (컬럼이 많으므로 전체 너비 필요)
- 기존 `createDataTable<T>()` 팩토리 사용 (`@/frontend/src/components/common/data-table.ts`)
- 컬럼 구성 (총 12컬럼):

| 컬럼 | key | align | 설명 |
|------|-----|-------|------|
| 종목코드 | code | center | 6자리 |
| 종목명 | name | left | |
| 당일 거래대금 | day1_amount | right | 억원 단위 변환 (백만원 / 100) |
| 직전1일 거래대금 | day2_amount | right | 억원 단위 |
| 직전2일 거래대금 | day3_amount | right | 억원 단위 |
| 직전3일 거래대금 | day4_amount | right | 억원 단위 |
| 직전4일 거래대금 | day5_amount | right | 억원 단위 |
| 당일 고가 | day1_high | right | 원 단위, 천 단위 콤마 |
| 직전1일 고가 | day2_high | right | |
| 직전2일 고가 | day3_high | right | |
| 직전3일 고가 | day4_high | right | |
| 직전4일 고가 | day5_high | right | |

- `null` 값은 `-` 표시 (신규 상장 종목 등)
- 페이지 상단에 데이터 기준일(`date`) 표시
- **검색 입력란**: `createSearchInput()` 공통 컴포넌트 재사용 (`@/frontend/src/components/common/search-input.ts`)
  - placeholder: `'종목명 또는 코드 검색'`
  - 종목코드(`code`) 또는 종목명(`name`) 기준 포괄 검색 (case-insensitive `includes`)
  - 클라이언트 사이드 필터링 — 이미 로드된 데이터에서 필터 (추가 API 호출 없음)
  - 검색어 비어 있으면 전체 행 표시
- **하이라이트**: `rowStyle` 콜백 활용 (`stock-classification.ts:1016-1017` 패턴 참고)
  - 매칭된 행: `background: COLOR.warningBg` (노란색 배경)
  - 매칭되지 않은 행: `opacity: '0.4'` (dim 처리)
  - 검색어 비어 있으면 모든 행 기본 스타일
- `mount` 시 `api.getStockDetail5d()` 1회 호출 → 테이블 렌더링
- `unmount` 시 `DataTableApi.destroy()` + `searchInput.clear()` 호출
- WS 구독 불필요 (정적 배치 데이터)
- `notifyPageActive` / `notifyPageInactive` 호출 불필요 (실시간 데이터 없음)

**참고 패턴**:
- `@/frontend/src/pages/profit-overview.ts` (PageModule 패턴, API 호출, `full` 레이아웃)
- `@/frontend/src/pages/stock-classification.ts:558` (`createSearchInput` 사용 패턴)
- `@/frontend/src/pages/stock-classification.ts:1016-1017` (`rowStyle` 하이라이트 패턴)
- `@/frontend/src/pages/sector-stock.ts:58-71` (`filterStocksBySearch` 필터링 로직)

**단위 변환**:
- 거래대금: DB 백만원 → UI 억원 (÷100), 소수점 1자리
- 고가: DB 원 → UI 원 (그대로), 천 단위 콤마 (`fmtComma`)

**스타일**: `ui-styles.ts` 상수 사용 (COLOR, FONT_SIZE, FONT_WEIGHT)

**검증**: `npm run build`

---

### Step 4: 라우트 + 사이드바 등록

**파일 1**: `frontend/src/main.ts` (수정)
- `routes` 배열에 신규 항목 추가:
  ```typescript
  {
    path: '#/stock-detail',
    layout: 'full',
    load: () => import('./pages/stock-detail').then(m => m.default),
  },
  ```
- 위치: `#/stock-classification` 뒤, `#/general-settings` 앞

**파일 2**: `frontend/src/layout/sidebar.ts` (수정)
- `MENU` 배열에 신규 항목 추가:
  ```typescript
  { path: '#/stock-detail', label: '종목상세', icon: '🔍', separator: true },
  ```
- 위치: `#/stock-classification` 뒤 (separator로 구분), `#/general-settings` 앞

**검증**: `npm run build` + 브라우저에서 사이드바 메뉴 표시 확인

---

## 영향 범위

### 신규 파일
- `backend/app/web/routes/stock_detail.py`
- `frontend/src/pages/stock-detail.ts`

### 수정 파일
- `backend/app/web/app.py` (import + include_router, 2줄)
- `frontend/src/api/client.ts` (API 함수 1개 추가)
- `frontend/src/main.ts` (routes 배열 1항목 추가)
- `frontend/src/layout/sidebar.ts` (MENU 배열 1항목 추가)

### 영향 받지 않는 모듈
- 실시간 파이프라인 (WS, engine_*) — 영향 없음
- 배치 파이프라인 (market_close_pipeline, fetch_5d_data_only) — 영향 없음
- 기존 페이지 — 영향 없음
- 매매 로직 (trading.py) — 영향 없음

---

## 주의 사항

1. **데이터 신선도**: `stock_5d_array`는 장마감 후 또는 수동 다운로드 시에만 갱신됨. 페이지 상단에 기준일(`date` 컬럼) 표시 필수
2. **단위 표시**: 거래대금은 DB에 백만원 단위로 저장됨 (`stock_tables.py:410-414`). UI에서는 억원 단위로 변환 표시
3. **null 처리**: 신규 상장 종목은 5일치 데이터가 없을 수 있음. `null`은 `-`로 표시
4. **컬럼 너비**: 12컬럼이므로 `full` 레이아웃 필수. `createDataTable`의 `minWidth` 옵션 활용

---

## 검증 체크리스트

- [ ] `py_compile` backend route 통과
- [ ] `npm run build` 통과
- [ ] 사이드바 "종목상세" 메뉴 표시
- [ ] 페이지 진입 시 테이블 렌더링
- [ ] 거래대금 억원 단위 표시
- [ ] 고가 원 단위 천 단위 콤마 표시
- [ ] null 값 `-` 표시
- [ ] 기준일 표시
- [ ] 검색 입력란 표시 및 동작 (종목명/코드 검색)
- [ ] 검색 매칭 행 하이라이트 (노란색 배경)
- [ ] 검색 비매칭 행 dim 처리 (opacity 0.4)
- [ ] 검색어 삭제 시 전체 행 복원
- [ ] 기존 페이지 정상 동작 (회귀 없음)
