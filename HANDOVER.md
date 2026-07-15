# SectorFlow Handover

## 세션 개요
- 날짜: 2026-07-21
- 작업: 프론트엔드 데이터 테이블 컬럼 너비 공통 상수 적용 + 페이지별 override + 호가잔량비/프순매 컬럼 개선
- 상태: 구현 완료, 커밋/푸시 완료

## 직전 완료 작업

### 1. 컬럼 너비 공통 상수 도입 (이전 세션)
1. `frontend/src/components/common/table-config.ts` 신규 생성 — `ColumnType` 40개 및 `COLUMN_WIDTH` 표준 상수 정의.
2. `frontend/src/components/common/auto-width.ts` — `KOREAN_SCALE` 상수화, `1.8 → 1.4` 조정.
3. `frontend/src/components/common/data-table.ts` — `ColumnDef`에 `type?: ColumnType` 필드 추가, `createColumnWidthManager`에서 `minWidth`/`maxWidth` 미지정 시 `COLUMN_WIDTH[type]` 자동 적용.
4. `frontend/src/components/common/ui-styles.ts` — 10개 공통 컬럼 팩토리(`makeSeqColumn`, `makeCodeColumn`, `makePriceColumn`, `makeChangeColumn`, `makeRateColumn`, `makeStrengthColumn`, `makeAmountColumn`, `makeAvgAmountColumn`, `createStockNameColumn`, `createStockNameColumnWithSectorLookup`)에서 `COLUMN_WIDTH` 참조.
5. 8개 페이지(`buy-target`, `sell-position`, `profit-shared`, `stock-detail`, `sector-stock`, `stock-classification`, `general-settings`)의 `ColumnDef`에 `type` 지정.
6. `sector-ranking-list.ts`, `profit-overview.ts`의 flex 기반 이름/업종명 영역에 `min-width: 140px` 적용.
7. `npm run build` 및 `.venv/bin/python main.py` 테스트모드 기동 검증 완료.

### 2. 페이지별 컬럼 너비 override (이번 세션)
- **매수후보** (`buy-target.ts`):
  - 종목명 `maxWidth`: 140 → 168 (확대)
  - 거래대금(억) `maxWidth`: 140 → 126 (축소)
  - 호가잔량비 `maxWidth`: 140 → 114 → 110 (축소)
  - 5일고가 `maxWidth`: 100 → 96 (축소)
  - 프순매: 라벨 "프순매" → "프.순.매(백)", `minWidth`/`maxWidth` 85 → 106 (단위 표기 추가, P23 일관성)
- **업종별종목실시간시세** (`sector-stock.ts`):
  - 종목명 `maxWidth`: 140 → 166 (확대)
  - 거래대금(억) `maxWidth`: 140 → 126 (축소)
  - 5일평균(억) `maxWidth`: 120 → 108 (축소)

### 3. 호가잔량비 컬럼 render 개선 (이번 세션)
- 컬럼명: "호가잔량비" → "호가잔량비(%)" (P23: 단위 표기 패턴 통일)
- render: flex container로 [매수]/[매도]/보합(좌측) + 숫자(우측) 분리 정렬
- % 기호: 셀에서 삭제, 컬럼명으로 이동
- bid === ask 케이스: 좌측 "보합", 우측 "100.0" 표시 (3상태 일관성)

### 검증
- `npm run build` 성공 (exit 0)
- 공통 상수, 다른 페이지 영향 없음 (override는 해당 2개 페이지만)

## 현재 상태

### 1. 조사 범위
| 화면 | 파일 | 종류 |
|---|---|---|
| 매수 후보 | `frontend/src/pages/buy-target.ts` | DataTable |
| 보유 종목 | `frontend/src/pages/sell-position.ts` | DataTable |
| 수익 상세(매수/매도/드릴다운) | `frontend/src/pages/profit-detail.ts`, `frontend/src/pages/profit-shared.ts` | DataTable |
| 종목 상세 5일 데이터 | `frontend/src/pages/stock-detail.ts` | DataTable |
| 업종별 종목 시세 | `frontend/src/pages/sector-stock.ts` | DataTable |
| 업종 분류(검색/업종목록/종목목록) | `frontend/src/pages/stock-classification.ts` | DataTable |
| 일반 설정 명령어 안내 | `frontend/src/pages/general-settings.ts` | DataTable |
| 업종 순위 리스트 | `frontend/src/pages/sector-ranking-list.ts` | HTML div/flex |
| 수익 현황 업종별 종목 | `frontend/src/pages/profit-overview.ts` | HTML div/flex |

### 2. 핵심 공통 자산
- `frontend/src/components/common/table-config.ts` — `ColumnType`, `COLUMN_WIDTH`
- `frontend/src/components/common/data-table.ts` — `DataTable`, `ColumnDef`, `createColumnWidthManager`
- `frontend/src/components/common/auto-width.ts` — `estimateTextWidth`, `computeColWidths`, `widthsToPercentages`, `KOREAN_SCALE`
- `frontend/src/components/common/ui-styles.ts` — 셀 스타일, 공통 컬럼 팩토리

### 3. DB 데이터 특성
- `master_stocks_table.name`: 최대 14자, 평균 4.8자, 99% ≤ 9자
- `master_stocks_table.sector`: 최대 13자, 평균 6.8자
- `master_stocks_table.code`: 6자
- `stock_5d_bars.trade_amount`: 최대 33,936,947 (8자리)
- `stock_5d_bars.high_price`: 최대 3,015,000 (7자리)
- `trades.price`: 최대 1,858,500 (7자리)
- `trades.qty`: 최대 532 (3자리)
- `trades.total_amt`: 최대 5,128,949원
- `trades.fee`: 최대 771원
- `trades.tax`: 최대 10,280원
- `trades.realized_pnl`: 최대 157,700원
- `trades.pnl_rate`: 최대 5.47%

### 4. 해결된 문제
- `종목명` 컬럼이 전체 테이블에서 과도하게 넓게 표시되던 문제.
  - 원인: `auto-width.ts`의 `estimateTextWidth`가 한글 폭을 `fontSize * 0.75 * 1.8`로 과대 추정하고, `ColumnDef`의 `minWidth`/`maxWidth`가 페이지별로 제각각이며, `종목명`의 `maxWidth`가 200으로 큼.
  - 조치: `KOREAN_SCALE` 1.4 조정, `COLUMN_WIDTH` 표준 상수 적용, `종목명` `maxWidth` 140으로 축소.
- 숫자 컬럼(`현재가`, `거래대금(억)`, `대비`, `체결강도` 등)이 `maxWidth` 80~95에 묶여 있던 문제.
  - 조치: `ColumnType`별 표준 `minWidth`/`maxWidth` 적용, `type` 필드 추가로 `createColumnWidthManager`가 자동 적용.
- 매수후보/업종별종목실시간시세에서 숫자 컬럼이 과도하게 넓고 종목명이 좁은 문제.
  - 조치: 페이지 override로 숫자 컬럼 축소, 종목명 확대.
- 프순매 컬럼 단위 표기 누락 (P23 일관성 위반).
  - 조치: "프순매" → "프.순.매(백)" 라벨 변경, 너비 조정.
- 호가잔량비 글자와 숫자가 붙어 있어 행 간 비교 어려움 + % 단위 반복 표시.
  - 조치: flex container로 좌/우 분리 정렬, %는 컬럼명으로 이동, 보합 케이스 추가.

## 다음 단계
- 현재 보류 중인 미해결 문제 없음.
- 사용자 UI 확인 후 추가 컬럼 너비 조정이 필요하면 해당 페이지만 override로 진행.

## 미해결 문제
- 없음.

## 참고 사항
- `master_stocks_table`의 `cur_price`, `change`, `change_rate`, `trade_amount`는 현재 스냅샷에서 비어 있어, 수치 기준은 `stock_5d_bars`와 `trades`를 사용함.
- `auto-width.ts`의 `KOREAN_SCALE` 조정은 너비 추정 정확도에 큰 영향을 줌. 변경 없이는 `종목명` 9자만 되어도 150px 이상을 요구해 공간 낭비가 큼.
- `sector-ranking-list.ts`와 `profit-overview.ts`는 `DataTable`이 아니므로 별도 처리 필요.
- 컬럼 너비 공통 상수(`COLUMN_WIDTH`)는 min/max px 경계값이며, 실제 비율은 데이터 기반 px→% 정규화로 페이지별 컬럼 구성에 자동 적응함. per-page override는 `ColumnDef`의 `minWidth`/`maxWidth` 필드로 이미 지원.
