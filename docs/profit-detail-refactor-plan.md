# SectorFlow 수익현황 페이지 개선 - 단계별 진행 계획

- **프로젝트:** SectorFlow
- **작업명:** 수익현황 페이지 요약/상세 분리 (profit-overview → profit-overview + profit-detail)
- **작성일:** 2026-07-07 (rev. 2026-07-07 — 페이지 역할 분리 구조 반영)
- **총 7단계 (세션당 1단계 진행)

---

## 페이지 역할 정의

### profit-overview (요약/대시보드) — "지금 어떤 상태인가?"
- 차트 (작게, 클릭 시 detail 페이지로 이동)
- 요약카드 3개 (당일/당월/누적 손익)
- 계좌현황
- "상세 분석 보기" 버튼
- **제외:** 거래내역 테이블, 드릴다운

### profit-detail (상세/분석) — "무슨 일이 있었나?"
- 차트 (크게, 300px, 막대 클릭 → 날짜 필터)
- 드릴다운 (당월 일별 요약, 날짜 클릭 → 같은 페이지 거래내역 필터)
- 날짜/종목 필터
- 전체 거래내역 (가상스크롤, 매도/매수 탭)
- 통계 정보 (필터링된 데이터 기반: 총 건수, 매수/매도금액, 실현손익, 승률, 평균 수익률)
- **제외:** 요약카드, 계좌현황

---

## 진행 상태 요약

| 단계 | 내용 | 상태 | 세션 |
|------|------|------|------|
| Step 1 | 공통 모듈 분리 (profit-shared.ts) | 완료 | 세션 1 |
| Step 2 | API 클라이언트 확장 (client.ts + trade.py) | 완료 | 세션 2 |
| Step 3 | 기존 profit-overview.ts 리팩터링 (import 교체) | 완료 | 세션 1 |
| Step 4 | profit-detail.ts 신규 생성 (초안) | 완료 | 세션 2 |
| Step 4-a | profit-detail.ts 구조 수정 (요약카드/계좌 제거, 드릴다운/종목필터/통계 추가) | 완료 | 세션 3 |
| Step 4-b | profit-overview.ts 구조 수정 (거래내역/드릴다운 제거, 상세보기 버튼 추가) | 완료 | 세션 3 |
| Step 5 | 라우팅 추가 (main.ts) | 완료 | 세션 4 |
| Step 6 | 사이드바 메뉴 추가 (sidebar.ts) | 완료 | 세션 4 |
| Step 7 | 요약 페이지 이동 버튼 + 차트 클릭 시 detail 이동 | 완료 | 세션 4 |

---

## Step 1: 공통 모듈 분리 (profit-shared.ts)

- **목표:** `profit-overview.ts`의 공통 로직을 `profit-shared.ts`로 추출
- **대상 파일:** `frontend/src/pages/profit-shared.ts` (신규 생성)
- **추출 내용:**
  - `BUY_COLS`, `SELL_COLS`, `DRILLDOWN_COLS` (컬럼 정의)
  - `aggregatePnl` (손익 집계 순수 함수)
  - `buildMonthlyDrilldown` (당월 일별 요약)
  - `buildChartFromDailySummary` (차트 데이터 변환)
  - `getLocalToday` (로컬 날짜)
  - `PnlSummary`, `DailyDrilldownRow` (타입 정의)
  - `DUMMY_BUY`, `DUMMY_SELL` (더미 데이터)
  - `renderAccountVals` (계좌 현황 렌더 → 매개변수 구조 변경)
- **주의사항:** `renderAccountVals`는 모듈 변수 의존성 제거 후 순수 함수화
- **검증:** `npm run type-check` + `npm run build`
- **의존성:** 없음 (최우선 단계)

---

## Step 2: API 클라이언트 확장 (client.ts)

- **목표:** `client.ts`의 `getBuyHistory`/`getSellHistory`에 날짜 필터 파라미터 추가
- **대상 파일:** `frontend/src/api/client.ts`
- **변경 내용:**
  - `getBuyHistory(tradeMode?, dateFrom?, dateTo?)` → 선택적 파라미터
  - `getSellHistory(tradeMode?, dateFrom?, dateTo?)` → 선택적 파라미터
  - `URLSearchParams` 사용으로 기존 호출 호환성 유지
- **백엔드:** `trade.py` 라우트에 `date_from`, `date_to` Query 파라미터 추가 (서비스 계층 `trade_history.py`는 이미 지원했으나 라우트에 누락되어 있었음)
- **검증:** `npm run typecheck` + `npm run build` + `pytest test_trade_history.py`
- **의존성:** 없음 (Step 1과 독립)

---

## Step 3: 기존 profit-overview.ts 리팩터링 (완료)

- **목표:** 공통 모듈 import로 교체
- **대상 파일:** `frontend/src/pages/profit-overview.ts`
- **변경 내용:** `profit-shared.ts`에서 import로 교체, 기존 렌더링 로직 유지
- **검증:** `npm run typecheck` + `npm run build` 통과
- **의존성:** Step 1 완료 필수

---

## Step 4: profit-detail.ts 신규 생성 (완료 — 초안)

- **목표:** 상세 수익현황 페이지 초안 생성
- **대상 파일:** `frontend/src/pages/profit-detail.ts` (신규 생성)
- **구성 (초안):** 차트(300px) + 요약카드 3개 + 계좌현황 + 거래내역(가상스크롤 + 날짜 필터)
- **검증:** `npm run typecheck` + `npm run build` 통과
- **비고:** Step 4-a에서 역할 분리 구조로 수정

---

## Step 4-a: profit-detail.ts 구조 수정

- **목표:** 상세/분석 페이지 역할에 맞게 구성 요소 재배치
- **대상 파일:** `frontend/src/pages/profit-detail.ts`
- **제거:**
  - 요약카드 3개 (당일/당월/누적 손익) — overview 전용
  - 계좌현황 (`renderAccountVals`, 관련 모듈 변수, DOM 생성) — overview 전용
  - `updateSummaryCards()` 함수 및 rAF 핸들러 내 갱신 로직
- **추가:**
  - 드릴다운 뷰 (당월 일별 요약, `buildMonthlyDrilldown` + `createDrilldownCols` 재사용)
  - 드릴다운 날짜 클릭 → 같은 페이지 거래내역 날짜 필터 (cross-page 이동 없음)
  - 종목 필터 input (종목명/코드 검색 → `filterRows`에 종목 조건 추가)
  - 통계 정보 행 (필터링된 거래내역 기반: 총 건수, 매수/매도금액, 실현손익, 승률, 평균 수익률)
- **유지:** 차트(300px, 막대 클릭 → 날짜 필터), 거래내역(가상스크롤, 매도/매수 탭), 날짜 필터
- **검증:** `npm run typecheck` + `npm run build`
- **의존성:** Step 4 완료 필수

---

## Step 4-b: profit-overview.ts 구조 수정

- **목표:** 요약/대시보드 페이지 역할에 맞게 구성 요소 재배치
- **대상 파일:** `frontend/src/pages/profit-overview.ts`
- **제거:**
  - 거래내역 테이블 (`showTable()`, `activeTab`, `sellTable`, `buyTable`, `sellTabBtn`, `buyTabBtn`, `tableContainer`, `tableViewContainer`, `dummyMsg`)
  - 드릴다운 (`showDrilldown()`, `drilldownTable`, `drilldownViewContainer`, `drilldownActive`, `dateFilter`, `filterByDate()`)
  - 카드 클릭 핸들러 중 `showTable()` 호출 제거
  - rAF 핸들러에서 `showTable()`/`showDrilldown()` 호출 제거
  - 미사용 import 제거 (`BUY_COLS`, `SELL_COLS`, `DUMMY_BUY`, `DUMMY_SELL`, `buildMonthlyDrilldown`, `createDrilldownCols`, `DailyDrilldownRow`)
- **유지:** 차트(작게), 요약카드 3개, 계좌현황
- **추가:**
  - 차트 클릭 시 `location.hash = '#/profit-detail'` 이동
  - 요약카드 클릭 시 `location.hash = '#/profit-detail'` 이동 (당일/당월/누적 각각)
- **검증:** `npm run typecheck` + `npm run build` + 브라우저 `#/profit-overview` 확인
- **의존성:** Step 4-a 완료 필수 (동시 진행 권장)

---

## Step 5: 라우팅 추가 (main.ts)

- **목표:** `#/profit-detail` 라우트 등록
- **대상 파일:** `frontend/src/main.ts`
- **변경 내용:**
  ```typescript
  {
    path: '#/profit-detail',
    layout: 'full',
    load: () => import('./pages/profit-detail').then(m => m.default),
  },
  ```
- **검증:** `#/profit-detail` 접근 시 페이지 렌더링 확인
- **의존성:** Step 4-a, 4-b 완료 필수

---

## Step 6: 사이드바 메뉴 추가 (sidebar.ts)

- **목표:** 수익상세 메뉴 추가
- **대상 파일:** `frontend/src/layout/sidebar.ts`
- **변경 내용:**
  - `{ path: '#/profit-detail', label: '수익상세', icon: '📋' }` 추가
- **검증:** 사이드바에 수익상세 메뉴 표시 확인
- **의존성:** Step 5 완료 필수

---

## Step 7: 요약→상세 이동 연결

- **목표:** 요약 페이지에서 상세 페이지로 자연스러운 이동 경로 제공
- **대상 파일:** `frontend/src/pages/profit-overview.ts` (Step 4-b에서 이미 구현될 수 있음)
- **변경 내용:**
  - 차트 막대 클릭 → `location.hash = '#/profit-detail'`
  - 요약카드 클릭 → `location.hash = '#/profit-detail'`
  - (선택) `createCardTitle` 영역에 "상세 분석 보기" 버튼 추가
- **검증:** 각 진입점 클릭 시 상세 페이지 이동 확인
- **의존성:** Step 5 완료 필수
- **비고:** Step 4-b에서 미리 구현된 경우 이 단계는 생략

---

## 세션별 진행 일정

| 세션 | 단계 | 작업 | 검증 | 승인 |
|------|------|------|------|------|
| 세션 1 | Step 1 + 3 | 공통 모듈 분리 + import 교체 | typecheck + build | 완료 |
| 세션 2 | Step 2 + 4 | API 확장 + detail 초안 생성 | typecheck + build | 완료 |
| 세션 3 | Step 4-a + 4-b | 페이지 역할 분리 수정 | typecheck + build + 브라우저 | 완료 |
| 세션 4 | Step 5 + 6 + 7 | 라우팅 + 사이드바 + 이동 연결 | 브라우저 확인 | 완료 |

---

## 유의사항

1. 각 단계 완료 후 사용자 승인 필요
2. Step 4-a/4-b는 동시 진행 권장 (한 세션에서 두 파일 수정)
3. Step 7은 Step 4-b에서 미리 구현 가능 — 중복 시 생략
4. 각 단계 완료 시 `HANDOVER.md` 업데이트 + Git 커밋 (사용자 승인 후)

---

## 아키텍처 원칙 부합 확인

| 원칙 | 부합 내용 |
|------|-----------|
| 원칙 10 (SSOT) | 공통 로직이 `profit-shared.ts` 단일 모듈에서 관리, `hotStore` 단일 데이터 소스 재사용 |
| 원칙 11 (이벤트 기반) | 기존 WS 이벤트 구독 유지, 폴링 없음 |
| 원칙 16 (살아있는 경로) | 서비스 계층의 기존 기능을 라우트에 배선하여 실제 실행 경로에 연결 |
| 원칙 20 (폴백 금지) | 새로운 폴백 분기 없이 기존 데이터 구조 그대로 활용 |

---

## 영향 범위 요약

| 파일 | 변경 유형 | 영향 |
|------|-----------|------|
| `profit-shared.ts` | 변경 없음 | 기존 공통 함수 그대로 재사용 |
| `profit-detail.ts` | 수정 (Step 4-a) | 요약카드/계좌 제거, 드릴다운/종목필터/통계 추가 |
| `profit-overview.ts` | 수정 (Step 4-b) | 거래내역/드릴다운 제거, 상세보기 이동 추가, 파일 크기 감소 |
| `api/client.ts` | 변경 없음 (Step 2 완료) | 기존 호출 호환 |
| `main.ts` | 수정 (Step 5) | 기존 라우트 영향 없음 |
| `sidebar.ts` | 수정 (Step 6) | 기존 메뉴 영향 없음 |
| `router.ts` | 변경 없음 | 자동 지원 |
| `binding.ts` | 변경 없음 | WS 이벤트 기존 유지 |
| `hotStore.ts` | 변경 없음 | 데이터 소스 유지 |
| `backend/app/web/routes/trade.py` | 변경 없음 (Step 2 완료) | 기존 파라미터 유지 |
