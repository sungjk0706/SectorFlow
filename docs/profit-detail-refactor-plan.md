# SectorFlow 수익현황 페이지 개선 - 단계별 진행 계획

- **프로젝트:** SectorFlow
- **작업명:** 수익현황 페이지 요약/상세 분리 (profit-overview → profit-overview + profit-detail)
- **작성일:** 2026-07-07
- **총 7단계 (세션당 1단계 진행)**

---

## 진행 상태 요약

| 단계 | 내용 | 상태 | 세션 |
|------|------|------|------|
| Step 1 | 공통 모듈 분리 (profit-shared.ts) | 완료 | 세션 1 |
| Step 2 | API 클라이언트 확장 (client.ts + trade.py) | 완료 | 세션 2 |
| Step 3 | 기존 profit-overview.ts 리팩터링 | 대기 | 세션 3 |
| Step 4 | 새 profit-detail.ts 생성 | 대기 | 세션 4 |
| Step 5 | 라우팅 추가 (main.ts) | 대기 | 세션 5 |
| Step 6 | 사이드바 메뉴 추가 (sidebar.ts) | 대기 | 세션 5 |
| Step 7 | 요약 페이지 이동 버튼 추가 (선택) | 대기 | 세션 6 |

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

## Step 3: 기존 profit-overview.ts 리팩터링

- **목표:** 공통 모듈 import로 교체
- **대상 파일:** `frontend/src/pages/profit-overview.ts`
- **변경 내용:**
  - `profit-shared.ts`에서 import로 교체
  - 기존 렌더링 로직, rAF 배칭, store 구독은 그대로 유지
  - 파일 크기 935줄 → 약 500줄 감소
- **검증:** `npm run type-check` + `npm run build` + 브라우저 `#/profit-overview` 정상 확인
- **의존성:** Step 1 완료 필수

---

## Step 4: 새 profit-detail.ts 생성

- **목표:** 상세 수익현황 페이지 생성
- **대상 파일:** `frontend/src/pages/profit-detail.ts` (신규 생성)
- **구성:**
  - 상단: 전체 너비 차트 (`createProfitChart` 재사용, 높이 300px)
  - 중단: 요약 카드 3개 (`aggregatePnl` 재사용)
  - 하단: 계좌현황 (`renderAccountVals` 재사용)
  - 하단: 전체 거래내역 (매도/매수 탭 + 가상 스크롤 + 날짜 필터)
  - `hotStore` 구독으로 실시간 갱신
- **검증:** `npm run type-check` + `npm run build`
- **의존성:** Step 1, 2, 3 완료 필수

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
- **의존성:** Step 4 완료 필수

---

## Step 6: 사이드바 메뉴 추가 (sidebar.ts)

- **목표:** 수익상세 메뉴 추가
- **대상 파일:** `frontend/src/layout/sidebar.ts`
- **변경 내용:**
  - `{ path: '#/profit-detail', label: '수익상세', icon: '📋' }` 추가
- **검증:** 사이드바에 수익상세 메뉴 표시 확인
- **의존성:** Step 5 완료 필수

---

## Step 7: 이동 버튼 추가 (선택)

- **목표:** 요약 페이지에서 상세 페이지 이동 버튼
- **대상 파일:** `frontend/src/pages/profit-overview.ts`
- **변경 내용:**
  - `createCardTitle` 영역에 "상세 보기" 버튼 추가
  - click → `location.hash = '#/profit-detail'`
- **검증:** 버튼 클릭 시 상세 페이지 이동 확인
- **의존성:** Step 5 완료 필수
- **비고:** 선택사항이므로 생략 가능

---

## 세션별 진행 일정

| 세션 | 단계 | 작업 | 검증 | 승인 |
|------|------|------|------|------|
| 세션 1 | Step 1 | 공통 모듈 분리 | type-check + build | 사용자 승인 |
| 세션 2 | Step 2 | API 확장 | type-check + build | 사용자 승인 |
| 세션 3 | Step 3 | 기존 페이지 리팩터 | type-check + build + 브라우저 | 사용자 승인 |
| 세션 4 | Step 4 | 새 페이지 생성 | type-check + build | 사용자 승인 |
| 세션 5 | Step 5 + 6 | 라우팅 + 사이드바 | 브라우저 확인 | 사용자 승인 |
| 세션 6 | Step 7 | 이동 버튼 (선택) | 브라우저 확인 | 사용자 승인 |

---

## 유의사항

1. 각 단계 완료 후 사용자 승인 필요
2. Step 1 완료 후 반드시 빌드 검증 (이후 단계는 Step 1에 의존)
3. Step 4는 Step 1~3에 의존하므로 순서 변경 불가
4. Step 7은 선택사항이므로 생략 가능
5. 각 단계 완료 시 `HANDOVER.md` 업데이트 + Git 커밋 (사용자 승인 후)

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
| `profit-shared.ts` (신규) | 생성 | 공통 로직 단일 소스 |
| `profit-detail.ts` (신규) | 생성 | 상세 페이지 |
| `profit-overview.ts` | 수정 (import 교체) | 기존 기능 유지, 파일 크기 감소 |
| `api/client.ts` | 수정 (파라미터 확장) | 기존 호출 호환 (선택적 파라미터) |
| `main.ts` | 수정 (라우트 추가) | 기존 라우트 영향 없음 |
| `sidebar.ts` | 수정 (메뉴 추가) | 기존 메뉴 영향 없음 |
| `router.ts` | 변경 없음 | 자동 지원 |
| `binding.ts` | 변경 없음 | WS 이벤트 기존 유지 |
| `hotStore.ts` | 변경 없음 | 데이터 소스 유지 |
| `backend/app/web/routes/trade.py` | 수정 (파라미터 추가) | `/buy`, `/sell` 라우트에 `date_from`, `date_to` 추가, 기존 호출 호환 |
