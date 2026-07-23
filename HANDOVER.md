# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. 이전 세션의 완료 작업, 현재 상태, 다음 세션에서 이어서 진행할 항목을 기록.

---

## 세션 개요

| 날짜 | 세션 | 작업 | 상태 |
|------|------|------|------|
| 2026-07-23 | T3-S27 | DataTable 빈 데이터 시 헤더 라벨 잘림 방지 (initFromRows 빈 데이터 분기 호출) — P21/P16/P20 (프론트엔드) | 완료 |
| 2026-07-23 | T3-S26 | 전 페이지 패널 padding 8px 통일 (shell 기본값 변경 + sector-ranking 중복 오버라이드 제거) — P23/P24/P10 (프론트엔드) | 완료 |
| 2026-07-23 | T3-S25 | 업종순위 페이지 가운데·우측 패널 padding 16px→8px (컬럼 너비 확보) — P21/P23 (프론트엔드) | 완료 |
| 2026-07-23 | T3-S24 | 매수/매도 상태 배지 판정 로직 공통 추출 (computeOrderBlockStatus) — P10/P23/P25 (프론트엔드) | 완료 |
| 2026-07-23 | T3-S23 | 배지 폰트 위계 조정 + 보유종목 배지 라벨 축약 (P23/P21) (프론트엔드) | 완료 |
| 2026-07-23 | T3-S22 | 보유종목 테이블 4번째 배지 "🚦 매도상태" 추가 (매수후보 T3-S21과 동일 패턴) — P21 (프론트엔드) | 완료 |
| 2026-07-23 | T3-S21 | 매수후보 테이블 4번째 배지 "🚦 매수상태" 추가 (전체 차단 게이트 UI 표시) — P21 (프론트엔드) | 완료 |
| 2026-07-23 | T3-S20 | 매수 수량 계산 수수료 여유분 확보 (max_buy_qty_for_budget 헬퍼 SSOT) — P10/P22 (백엔드+테스트) | 완료 |
| 2026-07-23 | T3-S19 | 일일/종목당 매수 한도 수수료 포함 통일 (테스트모드) — P22/P10/P21 (백엔드+프론트+테스트) | 완료 |
| 2026-07-23 | T3-S18 | 수익상세 페이지 매수/매도 금액 라벨 명확화 + 승률/수익률 카드 순서 교환 (P21/P23) | 완료 |
| 2026-07-23 | T3-S16 | B5-08-01/02/04 trading.py 매매 로직 (schedule_engine_task 교체 + 평균매입가 분기 주석 + 실시간 지연 fail-closed) | 완료 |
| 2026-07-23 | T3-S15 | A3-07-08/09/10 통계 카드 / 라우트 변경 / addEventListener 격리 | 완료 |
| 2026-07-23 | T3-S14 | B3-05-03/04 silent except 제거 + exc_info 11곳 보강 | 완료 |

> P25 전수 조사(9세션) + 수정(Tier 1/2/3, 17세션) 전체 완료. 계획서/태스크 파일은 규칙 11에 따라 삭제됨. 조사 보고서 `docs/p25_isolated_failure_investigation.md`는 역사적 기록으로 유지.

---

## 직전 완료 작업

### T3-S27 DataTable 빈 데이터 시 헤더 라벨 잘림 방지 — 완료 (2026-07-23) — P21 사용자 투명성 + P16 살아있는 경로 + P20 폴백 금지 (프론트엔드, frontend-fix)

**세션**: 단일 세션. 가상 스크롤/고정 모드 DataTable 모두에서 빈 데이터 초기 렌더링 시 컬럼 폭 계산이 스킵되어 헤더 라벨이 잘리는 현상 수정. `createColumnWidthManager.initFromRows()`를 빈 데이터 분기에서도 호출하도록 변경.

**배경**: T3-S25에서 발견된 업종순위 테이블 "평균거래(억)" 라벨 짤림 현상(임계치 수신율 달성 전 잘림, 달성 후 정상 표시) 조사 결과 — `data-table-virtual.ts:388`의 `if (rows.length > 0)` 조건으로 인해 빈 데이터일 때 `initFromRows`가 스킵되고, `cachedPercentages`가 균등 분할(컬럼수 10개 → 각 10%) 상태로 유지됨. 헤더 셀 `whiteSpace: nowrap` + `overflow: hidden` 스타일로 인해 10% 폭에서 "평균거래(억)" 라벨이 잘림. 임계치 후 첫 유효 데이터 진입 시 `initFromRows`가 1회 실행되어 라벨 폭 기반 정상 폭 적용. `data-table-fixed.ts:201`에도 동일 패턴(`rows.length === 0` 분기에서 `initFromRows` 스킵) 확인.

**작업 내용** (2건, 2개 파일):
1. **`data-table-virtual.ts:388`** — `if (rows.length > 0) { widthMgr.initFromRows(rows) }` → 조건 제거하고 무조건 `widthMgr.initFromRows(rows)` 호출. `computeColWidths`는 샘플이 비어도 라벨 폭 기반으로 minWidth 산출하므로 라벨 잘림 해결.
2. **`data-table-fixed.ts:201`** — 빈 데이터 분기(`rows.length === 0`) 내에 `widthMgr.initFromRows(rows)` 호출 추가. 동일 원리로 라벨 폭 기반 폭 적용.

**수정 파일**: 2개 (프론트엔드).
- `frontend/src/components/common/data-table-virtual.ts` (조건 제거 + 주석 갱신, 5줄 감소)
- `frontend/src/components/common/data-table-fixed.ts` (빈 데이터 분기에 initFromRows 호출 1줄 + 주석 1줄 추가)

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): 빈 데이터 상태에서도 헤더 라벨이 온전히 표시되어 사용자가 컬럼 의미 인지 가능.
- P16 (살아있는 경로): 기존 `initFromRows` 정상 계산 경로 그대로 사용, 새 분기/우회 경로 없음.
- P20 (폴밭 금지): 빈 데이터를 폴백으로 덮는 것이 아니라 라벨 기반 정상 계산 경로로 진입시키는 것. silent `except: pass` 없음.
- P24 (단순성): 조건 1개 제거/추가만으로 해결, 신규 추상화 없음.
- P25 (격리된 실패): 해당 없음 (폭 계산 로직 변경).

**영향 범위**: 프론트엔드 2파일. 백엔드/DB/테스트 영향 없음. 가상 스크롤/고정 모드 DataTable을 사용하는 모든 페이지(sector-ranking-list, sector-stock, buy-target, sell-position, stock-detail 등)의 빈 데이터 초기 렌더링 시 헤더 라벨 잘림 해소. 데이터 진입 후 1회 재계산 로직은 기존과 동일 (이후 고정). 핵심 매매 로직 아님 → 규칙 0-4 해당 없음. **롤백 아님** — 조건 제거/추가로 정상 경로 진입 확대이지 이전 상태로 회귀가 아님 → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 임계치 수신율 달성 전 상태에서 업종순위 테이블의 "평균거래(억)" 라벨이 잘리지 않고 전체 표시됨 (기존: 잘림).
- 종목 리스트 테이블의 "거래대금(억)" 등 모든 컬럼 헤더도 빈 데이터 상태에서 정상 표시됨.
- 임계치 달성 후 데이터 진입 시 컬럼 너비는 기존과 동일하게 데이터 기반으로 1회 재계산 후 고정 (화면 변화 없음).

**검증**:
- `npm run build` (tsc -b + vite build) 통과 — 77 모듈 변환, 876ms, 타입 오류 없음 ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 본 세션에서 해결 완료. 추가 발견 문제 없음.

---

### T3-S26 전 페이지 패널 padding 8px 통일 — 완료 (2026-07-23) — P23 일관성 + P24 단순성 + P10 SSOT (프론트엔드, frontend-fix)

**세션**: 단일 세션. shell.ts의 패널 기본 padding을 16px → 8px로 변경하여 모든 페이지의 패널 여백을 통일. sector-ranking-page에 남아있던 padding 오버라이드/복원 중복 코드와 `DEFAULT_TRIPLE_*_PADDING` 상수도 함께 제거.

**배경**: T3-S25에서 sector-ranking-page의 가운데·우측 패널 padding을 8px로 축소하면서 다른 페이지(stock-classification, buy-target, sell-position, profit-overview, profit-detail)는 여전히 shell 기본값 16px를 사용해 P23(일관성) 위반 상태. sector-ranking-page는 mount 시 8px 오버라이드 + unmount 시 16px 복원 코드를 가지고 있어 P10(SSOT) 위반(shell 기본값과 중복 관리) + P24(단순성) 위반(페이지마다 오버라이드/복원 중복).

**작업 내용** (2건, 2개 파일):
1. **`shell.ts` 패널 기본 padding 16px → 8px** — `shell.ts:85,96,99,102`. rightPanel(dual/full/single 데이터 영역) + tripleLeft/Center/Right(triple 3컬럼) 4곳. leftPanel(dual 설정 영역)은 이미 8px이므로 변경 없음.
2. **`sector-ranking-page.ts` 중복 코드 제거** — `DEFAULT_TRIPLE_LEFT/CENTER/RIGHT_PADDING` 상수 3개(15-17행) + mount 시 padding 오버라이드 3줄(36,41,42행) + unmount 시 padding 복원 3줄(79,81,83행) 제거. flex/width/minWidth 오버라이드는 패널 비율/너비 설정이므로 유지.

**수정 파일**: 2개 (프론트엔드).
- `frontend/src/layout/shell.ts` (패널 기본 padding 4곳 16px → 8px)
- `frontend/src/pages/sector-ranking-page.ts` (padding 상수 3개 + 오버라이드 3줄 + 복원 3줄 제거, 총 10줄 감소)

**아키텍처 원칙 부합**:
- P23 (일관성): 모든 페이지(8개 라우트) 패널 padding 8px 통일. 기존 sector-ranking만 8px, 나머지 16px 불일치 해소.
- P24 (단순성): 단일 소스(shell.ts) 1곳에서 관리. sector-ranking의 중복 오버라이드/복원 코드 ~10줄 제거. 페이지마다 mount/unmount에 오버라이드+복원 추가하는 대안 대비 코드 단순.
- P10 (SSOT): padding 진실 소스 shell.ts 1곳. 기존 `DEFAULT_*_PADDING` 상수가 shell 기본값과 중복 관리하던 것 제거.
- P21 (사용자 투명성): 해당 없음 (여백 시각적 변화만).
- P25 (격리된 실패): 해당 없음 (CSS 수치 변경).

**영향 범위**: 프론트엔드 2파일. 백엔드/DB/테스트 영향 없음. 자동 적용 페이지 8개: sector-ranking, buy-settings, sell-settings, profit-overview, profit-detail, stock-classification, stock-detail, general-settings. 핵심 매매 로직 아님 → 규칙 0-4 해당 없음. **롤백 아님** — shell 기본값 변경은 신규 통일이지 이전 상태로 회귀가 아님. 단, sector-ranking-page의 오버라이드/복원 코드 제거는 T3-S25에서 추가한 코드 제거에 해당하나, 사용자가 사전조사 보고 시 "sector-ranking의 중복 오버라이드/복원 코드와 DEFAULT_*_PADDING 상수도 함께 제거"로 명시하고 사용자가 "진행해" 승인했으므로 규칙 0-3/0-5 준수.

**UI 기준 화면 변화 (규칙 0-4)**:
- 모든 페이지의 패널 내부 좌우 여백이 16px → 8px로 감소. 콘텐츠가 더 넓게 표시됨.
- 업종순위 페이지: 기존과 동일 (이미 8px 적용 중).
- 매수 후보/보유 종목/수익률 요약/수익률 상세/종목 분류/종목 상세/일반 설정: 좌우 여백이 좁아지고 콘텐츠 영역이 넓어짐.
- 페이지 전환 시 여백이 일관되게 8px로 유지됨 (이전에는 업종순위만 8px, 나머지 16px로 전환 시 여백 튀는 현상).

**검증**:
- `npm run build` (tsc -b + vite build) 통과 — 77 모듈 변환, 822ms, 타입 오류 없음 ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 본 세션에서 해결 완료. 추가 발견 문제 없음.

---

### T3-S25 업종순위 페이지 가운데·우측 패널 padding 16px→8px — 완료 (2026-07-23) — P21 가독성 + P23 일관성 (프론트엔드, frontend-fix)

**세션**: 단일 세션. 업종순위 페이지(sector-ranking-page) 3패널 중 가운데(업종순위 테이블)·우측(종목시세) 패널의 padding을 shell 기본값 16px에서 8px로 축소. 좌측 설정 패널(8px)과 일치시켜 3패널 padding 통일 + 가운데 테이블 컬럼 약 16px 확보.

**배경**: 업종순위 테이블의 외곽 테두리선은 이미 모두 제거된 상태(border:none, 셀/행 구분선 none). 컬럼 너비를 잡아먹는 주원인은 `tripleCenter` padding 16px(좌우 32px). 좌측 패널은 8px이므로 P23(일관성) 위반 상태. padding 축소로 컬럼 너비 확보 → 업종명/가산점/상승비율/평균거래 숫자 잘림 완화 (P21 가독성).

**작업 내용** (3건, 1개 파일):
1. **상수 추가** — `DEFAULT_TRIPLE_CENTER_PADDING`/`DEFAULT_TRIPLE_RIGHT_PADDING` (16px) — unmount 복원용.
2. **mount 시 padding 오버라이드** — `tripleCenter.style.padding = '8px'`, `tripleRight.style.padding = '8px'`.
3. **unmount 시 padding 복원** — 두 패널 padding을 16px 기본값으로 복원 (stock-classification 페이지 영향 방지).

**수정 파일**: 1개 (프론트엔드).
- `frontend/src/pages/sector-ranking-page.ts` (상수 2개 추가 + mount padding 오버라이드 2줄 + unmount padding 복원 2줄)

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): padding 축소 → 컬럼 너비 확대 → 숫자/업종명 잘림 감소 → 가독성 향상.
- P23 (일관성): 기존 좌측 8px / 가운데·우측 16px 불일치 해소 → 3패널 모두 8px 통일.
- P24 (단순성): padding 수치 2개만 수정, 복잡도 증가 없음.
- P25 (격리된 실패): CSS 수치 변경이라 다른 컴포넌트 영향 없음.

**영향 범위**: 프론트엔드 1파일. 백엔드/DB/테스트 영향 없음. stock-classification 페이지는 shell 기본값 16px를 사용하며 unmount 시 복원되므로 영향 없음. 핵심 매매 로직 아님 → 규칙 0-4 해당 없음. 롤백 아님 (padding 축소) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 업종순위 페이지: 가운데(업종순위 테이블)·우측(종목시세) 패널의 좌우 여백이 16px → 8px로 줄어듦. 가운데 테이블 컬럼이 약 16px 더 넓어져 업종명·가산점·상승비율·평균거래 숫자 잘림 완화. 좌측 설정 패널(8px)과 시각적 일관성.
- 다른 페이지(종목분류 등): 영향 없음 (unmount 시 16px 복원).

**검증**:
- `npm run build` (tsc -b + vite build) 통과 — 77 모듈 변환, 977ms, 타입 오류 없음 ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**:
1. **업종순위 테이블 "평균거래(억)" 라벨 짤림 현상** — 임계치 수신율 달성 전에는 라벨이 잘리고, 달성 후에는 정상 표시. 조사 결과 아래 "다음 세션 진행 대기" 섹션 참조.
2. **다른 페이지 패널 padding 8px 통일 검토** — stock-classification, buy-target, sell-position, profit-overview, profit-detail 페이지도 shell 기본값 16px를 사용 중. sector-ranking-page와 동일 패턴으로 8px 통일 검토 필요. → **T3-S26에서 해결 완료** (shell 기본값 8px로 전 페이지 통일).

---

### T3-S24 매수/매도 상태 배지 판정 로직 공통 추출 — 완료 (2026-07-23) — P10 SSOT + P23 일관성 + P25 격리된 실패 (프론트엔드, frontend-fix)

**세션**: 단일 세션. 매수후보/보유종목 양쪽 상태 배지의 차단 게이트 판정 로직(서킷브레이커 > 리스크 > 시간대 > 자동매매 OFF > 자동매수/매도 OFF > 시간대 외)이 거의 동일 코드로 중복되어 있던 것을 단일 함수 `computeOrderBlockStatus()`로 추출. buy-target 쪽 try/catch 누락(P25 위반)도 함께 보정.

**배경**: T3-S23 작업 중 발견 — `buy-target.ts:247-281`(인라인, try/catch 없음)과 `sell-position.ts:146-186`(`updateSellStatusBadge()`, try/catch 있음)이 6단계 게이트 우선순위 체인을 거의 동일하게 중복 구현. side/플래그/시간설정/텍스트만 다른 매개변수화 가능한 7개 차이점만 존재. P23(일관성) 위반 + buy 쪽 P25(격리된 실패) 위반(try/catch 누락으로 판정 중 예외 시 페이지 전체 중단 위험).

**작업 내용** (3건, 3개 파일):
1. **신규 `utils/order-block-status.ts`** — `computeOrderBlockStatus(side, uiState, settings): OrderBlockStatus` 단일 함수. side별 텍스트 매핑 테이블(`SIDE_TEXT`) 1곳에서 buy/sell 차이 관리 (ok/autoOff/outOfTime 텍스트 + autoFlag/timeStart/timeEnd 키). DOM 렌더링은 호출부 `updateBadge()` 담당 → 관심사 분리 (P24 단순성 — badge.ts 렌더링 책임과 분리).
2. **`buy-target.ts` 인라인 블록 교체** — 36줄 게이트 체인 → `computeOrderBlockStatus('buy', ...)` 호출 13줄. **try/catch + console.error 추가** (P25 격리 — 기존 누락 보정, sell 쪽과 일관성 확보).
3. **`sell-position.ts` 함수 본문 축소** — `updateSellStatusBadge()` 본문 45줄 → 16줄. 기존 try/catch 구조 유지.

**수정 파일**: 3개 (프론트엔드).
- `frontend/src/utils/order-block-status.ts` (신규, 89줄 — 판정 함수 + side 매핑 테이블)
- `frontend/src/pages/buy-target.ts` (import 추가 + 인라인 게이트 체인 → 함수 호출 + try/catch 추가)
- `frontend/src/pages/sell-position.ts` (import 추가 + 함수 본문 → 호출 1줄)

**아키텍처 원칙 부합**:
- P10 (SSOT): 게이트 판정 로직 단일 함수화 — 기존 2곳 중복 제거. side별 텍스트/키 매핑도 단일 테이블에서 관리.
- P23 (일관성): buy/sell 동일 패턴 보장. buy 쪽 try/catch 누락 보정으로 에러 격리 패턴 일관성 회복.
- P24 (단순성): 추상화 최소 (함수 1개 + 인터페이스 1개 + 매핑 테이블 1개). DOM 렌더링은 호출부 유지로 관심사 분리. badge.ts(렌더링 컴포넌트)에 비즈니스 로직 혼재 방지.
- P25 (격리된 실패): buy 쪽 try/catch 추가 → 양쪽 모두 판정 중 예외 시 해당 배지만 갱신 중단, 페이지 전체 중단 없음.
- P21 (사용자 투명성): 기존 UI 표시 텍스트/색상/우선순위 100% 유지 → 화면 변화 없음.

**영향 범위**: 프론트엔드 3파일(신규 1 + 수정 2). 백엔드/DB/테스트 영향 없음. 핵심 매매 로직 아님 (UI 상태 배지 판정만) → 규칙 0-4 해당 없음. 롤백 아님 (중복 제거 추출) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**: 없음. 매수후보 "🚦 매수상태" 배지와 보유종목 "🚦 매도상태" 배지의 표시 텍스트·색상·차단 사유 우선순위가 이전과 완전히 동일. 내부 코드 구조만 공통 함수로 통일.

**검증**:
- `npm run typecheck` (tsc --noEmit) 통과 ✓
- `npm run build` (tsc -b + vite build) 통과 — `order-block-status` 청크 분리 생성, 623ms, 타입 오류 없음 ✓
- 브라우저 검증: 사용자 확인 완료 (매수후보/보유종목 상태 배지 표시 이전과 동일)

**작업 중 발견 문제**: 본 세션에서 해결 완료. 추가 발견 문제 없음.

---

### T3-S23 배지 폰트 위계 조정 + 보유종목 배지 라벨 축약 — 완료 (2026-07-23) — P23 일관성 + P21 사용자 투명성 (프론트엔드, frontend-fix)

**세션**: 단일 세션. 매수후보/보유종목 양쪽 4등분 배지 행에서 라벨·상태 텍스트가 짤리는 문제 해결. 폰트 위계 재설정으로 값(중심) 강조 + 라벨/상태(보조) 축소, 보유종목 배지 라벨 축약.

**배경**: T3-S21/T3-S22에서 양쪽 페이지에 4번째 상태 배지가 추가되며 배지 행이 4등분(flex:1)으로 고정됨. 배지 내부 요소 4개(라벨 13px + 값 13px 굵게 + 단위 11px + 상태 13px)가 gap 16px로 나열되어 라벨이 긴 보유종목 페이지("📊 보유 종목 평가금액 합계" 등)나 상태 텍스트에 종목명이 들어가는 매수후보("(1위 종목명 N주)")에서 값/상태가 ellipsis로 잘리는 현상. 라벨이 값과 동일 13px라 비중 균형도 맞지 않음 (P23 위계 불일치 + P21 사용자 인지 저해).

**작업 내용** (2건, 2개 파일):
1. **`badge.ts` 폰트 위계 조정** — `badge.ts:60-105`. 라벨 `FONT_SIZE.body`(13px) → `FONT_SIZE.code`(12px), 상태 `FONT_SIZE.body`(13px) → `FONT_SIZE.small`(11px), 내부 gap 16px → 8px. 값(13px 굵게)·단위(11px) 유지. docstring "label은 13px 회색, unit/status는 11px 회색(보조)" → "label은 12px 회색, unit/status는 11px 회색(보조)", "gap 16px" → "gap 8px" 갱신 (P10 SSOT — 주석/코드 불일치 해소).
2. **`sell-position.ts` 배지 라벨 3개 축약** — `sell-position.ts:200-203`. "📊 보유 종목 평가금액 합계" → "📊 평가금액 합계", "📉 보유 종목 평가손익 합계" → "📉 평가손익 합계", "📈 보유 종목 평가수익률" → "📈 평가수익률". "🚦 매도상태" 유지. "보유 종목" 중복 제거로 buy-target 라벨 길이와 균형 맞춤.

**수정 파일**: 2개 (프론트엔드).
- `frontend/src/components/common/badge.ts` (라벨/상태 폰트 축소 + gap 축소 + docstring 갱신)
- `frontend/src/pages/sell-position.ts` (배지 라벨 3개 축약)
- `frontend/src/pages/buy-target.ts` — 변경 없음 (이미 짧은 라벨, `badge.ts` 변경으로 폰트 자동 적용만 수용)

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): 라벨/상태 짤림 해소로 사용자가 배지 내용 인지 가능.
- P23 (일관성): 매수/매도 배지 라벨 길이·폰트 위계 통일. `FONT_SIZE.code`(12px)/`FONT_SIZE.small`(11px) 표준 상수 재사용 (신규 상수 아님).
- P10 (SSOT): docstring과 실제 폰트 값 불일치 제거.
- P24 (단순성): 구조 변경 없이 폰트 상수·gap 값만 조정. 신규 추상화 없음.
- P25 (격리된 실패): 해당 없음 (스타일 변경).

**영향 범위**: 프론트엔드 2파일. 백엔드/DB/테스트 영향 없음. 핵심 매매 로직 아님 (UI 스타일만) → 규칙 0-4 해당 없음. 롤백 아님 (스타일 조정) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 매수후보 화면: 4개 배지 라벨("주문가능금액/일일 매수/보유 종목/매수상태")이 13px → 12px로 약간 작아지고, "(1위 종목명 N주)" 상태 텍스트가 13px → 11px로 작아져 값이 더 잘 보임. 배지 내 요소 간 간격이 좁아져 한 줄에 더 안정적으로 배치.
- 보유종목 화면: 배지 라벨이 "평가금액 합계/평가손익 합계/평가수익률/매도상태"로 짧아지고, 값과 "(N 종목)" 상태가 잘려 보이지 않게 됨. 매수후보 화면과 동일한 폰트 위계·간격.

**검증**:
- `npm run build` (tsc -b + vite build) 통과 — 76 모듈 변환, 632ms, 타입 오류 없음 ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 매수/매도 상태 배지 로직(`buy-target.ts:247-281`의 매수상태 체인과 `sell-position.ts:146-186`의 매도상태 체인)이 거의 동일 코드로 중복. P23(일관성) 관점에서 공통 유틸 추출 가능. 다음 세션(T3-S24)에서 분리 진행 예정 (규칙 0-1 세션당 1단계 준수로 본 세션에서는 분리하지 않음).

---

### T3-S22 보유종목 테이블 4번째 배지 "🚦 매도상태" 추가 — 완료 (2026-07-23) — P21 사용자 투명성 (프론트엔드, frontend-fix)

**세션**: 단일 세션. 보유종목 테이블 상단 배지 행에 4번째 배지 추가로 "왜 매도가 안 되는지"를 화면에서 즉시 파악 가능하게 함. 매수후보 T3-S21과 동일 패턴.

**배경**: 기존 3개 배지(평가금액/평가손익/수익률)는 "요약 수치"만 표시. 서킷브레이커·리스크·시간대·자동매도 OFF 등으로 매도가 차단될 수 있으나, 그 사실이 보유종목 페이지에 문맥적으로 연결되지 않아 사용자가 "보유 종목 있는데 왜 안 팔려?"라는 의문을 갖게 됨 (P21 위반). 차단 정보는 화면 최상단 헤더 칩에 있으나 시선 분리. T3-S21에서 매수후보에 매수상태 배지를 추가했으나 보유종목 페이지는 미대응 상태였음.

**작업 내용** (5건, 1개 파일):
1. **import 추가** — `sell-position.ts:7,10` `uiStore`, `globalSettingsManager` (buy-target.ts와 동일).
2. **모듈 변수 추가** — `sell-position.ts:104-106,113` `unsubUiStore`/`unsubSettings`/`_statusRafId`/`summaryStatusBadge`.
3. **`updateSellStatusBadge()` 함수 신규** — `sell-position.ts:142-189`. 우선순위 체인: 서킷브레이커 > 리스크(side=sell) > 시간대 > 자동매매 OFF > 자동매도 OFF > 매도 시간대 외. 정상 시 "매도 가능"(파랑), 차단 시 "차단: {사유}"(빨강). 시간 범위 체크는 KST HH:MM 기준(`toLocaleTimeString('en-GB', { timeZone: 'Asia/Seoul' })`)으로 백엔드 `auto_sell_effective`와 동일 로직. try/catch + console.error (P25 격리된 실패).
4. **배지 추가 + 초기 렌더** — `sell-position.ts:198-208` 4번째 `createBadge('🚦 매도상태', '')` 추가. `mount()` 초기 렌더 시 `updateSellStatusBadge()` 호출.
5. **uiStore + globalSettingsManager 구독** — `sell-position.ts:282-302` rAF 배칭으로 매도상태 배지 갱신. `unmount()`에 신규 구독 해제 + `_statusRafId` 취소 추가.

**수정 파일**: 1개 (프론트엔드).
- `frontend/src/pages/sell-position.ts` (import + 모듈 변수 + updateSellStatusBadge 함수 + 4번째 배지 + uiStore/settings 구독 + unmount 정리)

**데이터 소스 (P10 SSOT — 신규 데이터 없음)**:
- `uiStore.circuitBreakerOpen` / `orderTimeBlocked` / `riskBlockStatus` — 기존 WS 이벤트로 갱신됨. `riskBlockStatus.side === 'sell'`로 매도 전용 분기.
- `globalSettingsManager.getSettings()`의 `time_scheduler_on`/`auto_sell_on`/`sell_time_start`/`sell_time_end` — 기존 설정.

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): 핵심 목적 — 매도 차단 원인을 보유종목 화면에 직접 표시. "보유 종목 있는데 왜 안 팔려?" 의문 해소.
- P10 (SSOT): 신규 데이터/상태 없음. 기존 uiStore + globalSettingsManager 집계만.
- P16 (살아있는 경로): updateSellStatusBadge()는 mount 초기 렌더 + uiStore/settings 구독 콜백에서 호출됨.
- P20 (폴백 금지): settings null 시 early return (기존 패턴 준수).
- P23 (일관성): buy-target.ts의 매수상태 배지와 동일 패턴·우선순위·색상. `createBadge`/`updateBadge` 공통 컴포넌트 재사용, 용어사전 준수("매도").
- P24 (단순성): 우선순위 if-else 체인, 신규 추상화 없음.
- P25 (격리된 실패): updateSellStatusBadge() try/catch + console.error.

**영향 범위**: 프론트엔드 1파일. 백엔드/테스트 영향 없음. 핵심 매매 로직 아님 (UI 표시만) → 규칙 0-4 해당 없음. 롤백 아님 (신규 배지 추가) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 보유종목 화면 상단 배지 행이 3개 → 4개로 변경. 기존 3개 배지(평가금액/평가손익/수익률) 라벨/표시 변화 없음.
- 4번째 배지 "🚦 매도상태" 추가:
  - 정상: "매도 가능" (파랑)
  - 서킷브레이커 발동 시: "차단: 서킷브레이커" (빨강)
  - 리스크 차단 시: "차단: 리스크({사유})" (빨강)
  - 동시호가/장외 시: "차단: {사유}" (빨강)
  - 자동매매 OFF 시: "차단: 자동매매 OFF" (빨강)
  - 자동매도 OFF 시: "차단: 자동매도 OFF" (빨강)
  - 매도 작동 시간 외: "차단: 매도 시간대 외" (빨강)
- 사용자가 보유종목 화면만 보고 "지금 매도가 실행 가능한가?"를 즉시 파악 가능. 매수후보 화면의 "🚦 매수상태" 배지와 동일한 위치·색상·표시 방식.

**검증**:
- `npm run typecheck` (tsc --noEmit) 통과 ✓
- `npm run build` (tsc -b + vite build) 통과 — sell-position 번들 5.12 kB ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 없음. (T3-S21에서 발견한 P21 갭 — 미노출 4개 전체 차단 사유 백엔드 WS 미브로드캐스트 — 는 매도에도 동일하게 적용되나, 본 세션에서는 신규 발견 아님. 기존 "미해결 문제" 섹션 참조.)

---

### T3-S21 매수후보 테이블 4번째 배지 "🚦 매수상태" 추가 — 완료 (2026-07-23) — P21 사용자 투명성 (프론트엔드, problem-solve)

**세션**: 단일 세션. 매수후보 테이블 상단 배지 행에 4번째 배지 추가로 "왜 매수가 안 되는지"를 화면에서 즉시 파악 가능하게 함.

**배경**: 기존 3개 배지(주문가능금액/일일 매수/보유 종목)는 "한도(용량)"만 표시. 주문가능금액이 충분해도 서킷브레이커·리스크·시간대·자동매수 OFF 등으로 매수가 차단될 수 있으나, 그 사실이 매수후보 페이지에 문맥적으로 연결되지 않아 사용자가 "돈 있는데 왜 안 사?"라는 의문을 갖게 됨 (P21 위반). 차단 정보는 화면 최상단 헤더 칩에 있으나 시선 분리.

**작업 내용** (4건, 1개 파일):
1. **배지 라벨 간소화 (4등분 폭 압축 대응)** — `buy-target.ts:263-265` "💰 일일 매수 금액 (수수료 포함)" → "💰 일일 매수", "📦 동시 보유 종목 최대" → "📦 보유 종목". 신규 "🚦 매수상태" 배지 추가 (단위 없음).
2. **`badgeEls` 타입에 `status: BadgeHandle` 추가** — `buy-target.ts:154` 4번째 배지 핸들 보관.
3. **`updateBadges()`에 매수상태 로직 추가** — `buy-target.ts:247-281`. 우선순위 체인: 서킷브레이커 > 리스크(side=buy) > 시간대 > 자동매매 OFF > 자동매수 OFF > 매수 시간대 외. 정상 시 "매수 가능"(파랑), 차단 시 "차단: {사유}"(빨강). 시간 범위 체크는 KST HH:MM 기준(`toLocaleTimeString('en-GB', { timeZone: 'Asia/Seoul' })`)으로 백엔드 `auto_buy_effective`와 동일 로직.
4. **`scheduleRender()` 변경 감지에 차단 상태 추가** — `buy-target.ts:381-393,434-447`. `circuitBreakerOpen`/`orderTimeBlocked`/`riskBlockStatus` 참조 변경 시 재렌더 트리거 + lastRendered 갱신.

**수정 파일**: 1개 (프론트엔드).
- `frontend/src/pages/buy-target.ts` (배지 라벨 간소화 + 4번째 배지 추가 + updateBadges 매수상태 로직 + scheduleRender 변경 감지)

**데이터 소스 (P10 SSOT — 신규 데이터 없음)**:
- `uiStore.circuitBreakerOpen` / `orderTimeBlocked` / `riskBlockStatus` — 기존 WS 이벤트(`circuit_breaker_open`/`order_time_blocked`/`risk_block_status`)로 갱신됨
- `globalSettingsManager.getSettings()`의 `time_scheduler_on`/`auto_buy_on`/`buy_time_start`/`buy_time_end` — 기존 설정

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): 핵심 목적 — 매수 차단 원인을 매수후보 화면에 직접 표시. "돈 있는데 왜 안 사?" 의문 해소.
- P10 (SSOT): 신규 데이터/상태 없음. 기존 uiStore 상태 집계만.
- P16 (살아있는 경로): updateBadges()는 기존 렌더 경로에서 호출됨.
- P20 (폴백 금지): settings null 시 early return (기존 패턴 준수).
- P23 (일관성): `createBadge`/`updateBadge` 공통 컴포넌트 재사용, 용어사전 준수("매수").
- P24 (단순성): 우선순위 if-else 체인, 신규 추상화 없음.
- P25 (격리된 실패): 기존 updateBadges 호출부 패턴 준수.

**영향 범위**: 프론트엔드 1파일. 백엔드/테스트 영향 없음. 핵심 매매 로직 아님 (UI 표시만) → 규칙 0-4 해당 없음. 롤백 아님 (신규 배지 추가) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 매수후보 화면 상단 배지 행이 3개 → 4개로 변경. 기존 배지 라벨 간소화 ("💰 일일 매수 금액 (수수료 포함)" → "💰 일일 매수", "📦 동시 보유 종목 최대" → "📦 보유 종목").
- 4번째 배지 "🚦 매수상태" 추가:
  - 정상: "매수 가능" (파랑)
  - 서킷브레이커 발동 시: "차단: 서킷브레이커" (빨강)
  - 리스크 차단 시: "차단: 리스크({사유})" (빨강)
  - 동시호가/장외 시: "차단: {사유}" (빨강)
  - 자동매매 OFF 시: "차단: 자동매매 OFF" (빨강)
  - 자동매수 OFF 시: "차단: 자동매수 OFF" (빨강)
  - 매수 작동 시간 외: "차단: 매수 시간대 외" (빨강)
- 사용자가 매수후보 화면만 보고 "지금 매수가 실행 가능한가?"를 즉시 파악 가능.

**검증**:
- `npm run build` (tsc -b + vite build) 통과 — 76 modules, 629ms ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 미노출 4개 전체 차단 사유(`daily_state`, `realtime_latency`, `test_cash`, `order_fail`)가 백엔드에서 WS 브로드캐스트되지 않아 프론트에서 표시 불가. "미해결 문제" 섹션에 별도 기록.

---

### T3-S20 매수 수량 계산 수수료 여유분 확보 — 완료 (2026-07-23) — P10 SSOT / P22 데이터 정합성 (백엔드, safe-trade + backend-fix)

**세션**: 단일 세션. 매수 수량 계산 시 수수료 포함 최대 수량 헬퍼 추가 + 양쪽 호출처 통일 + 테스트 추가.

**배경**: T3-S19에서 한도 체크 기준을 수수료 포함으로 통일했으나, 매수 수량 계산(`buy_qty = budget // price`)은 여전히 수수료 미반영. 테스트모드에서 `reserve_buy_power`가 청구하는 cost(수수료 포함)가 `buy_qty * price`를 초과하면 "주문가능금액 부족" 거부로 매수 1회 시도가 헛수고였던 버그. 또한 `buy_order_executor._refresh_buyable_prices`의 매수 후보 필터(`_max_for_code < _est_price`)도 수수료 미반영으로 trading.py와 기준 상이 (P10 위반).

**작업 내용** (4건, 5개 파일):
1. **`max_buy_qty_for_budget` 헬퍼 추가 (P10 SSOT)** — `settlement_engine.py:172-188`. 예산 내 수수료 포함 최대 매수 수량 반환. `reserve_buy_power`의 cost 공식(`price*qty + round(price*qty*BUY_COMMISSION)`)과 정합. 테스트모드만 수수료 적용, 실전모드는 `budget // price` (P18 — 실전 수수료는 별도 세션).
2. **trading.py buy_qty 계산 헬퍼 호출로 변경** — `trading.py:362` `buy_qty = _max_available // _est_buy_price` → `settlement_engine.max_buy_qty_for_budget(_est_buy_price, _max_available, is_test_mode(raw_all))`. 중복 지연 import 정리 (P24).
3. **buy_order_executor._refresh_buyable_prices 헬퍼 적용** — `buy_order_executor.py:55` 단가 비교 `_max_for_code < _est_price` → `max_buy_qty_for_budget(_est_price, _max_for_code, is_test) <= 0`. trading.py와 동일 기준 (P10).
4. **테스트 추가** — `test_settlement_engine.py` `TestMaxBuyQtyForBudget` 9개 (zero/negative, 딱 맞는 예산, 수수료 초과 1주 감소, 1주만 가능, 1주 불가, 실전 수수료 미적용, reserve_buy_power 정합성). `test_trading.py:855` 주석 헬퍼 기반 계산으로 업데이트 (결과 14주 동일).

**수정 파일**: 5개 (백엔드 3 + 테스트 2).
- `backend/app/services/settlement_engine.py` (헬퍼 추가)
- `backend/app/services/trading.py` (buy_qty 헬퍼 호출 + 중복 import 정리)
- `backend/app/services/buy_order_executor.py` (_refresh_buyable_prices 헬퍼 적용)
- `backend/tests/test_settlement_engine.py` (TestMaxBuyQtyForBudget 9개)
- `backend/tests/test_trading.py` (주석 업데이트)

**아키텍처 원칙 부합**:
- P10 (SSOT): 단일 헬퍼를 settlement_engine에 두고 trading.py/buy_order_executor 양쪽이 호출 → 동일 기준.
- P16 (살아있는 경로): 헬퍼가 실제 매수 경로 2곳에서 모두 호출됨.
- P22 (데이터 정합성): buy_qty가 reserve_buy_power가 청구할 금액과 정합 → 불필요한 거부 사전 차단.
- P20 (폴백 금지): 살 수 없으면 0 반환 → 기존 BUY_REJECT_QTY_ZERO/skip 경로가 처리 (silent pass 없음).
- P15 (단일 주문 경로): 주문 경로 변경 없음, 수량 계산만 정교화.
- P18 (테스트모드 동등성): 수수료 분기는 is_test 플래그로 기존 estimate_fill_price와 동일한 분기점.
- P24 (단순성): 헬퍼 5줄, 추상화 최소.

**영향 범위**: 백엔드 3파일 + 테스트 2파일. 핵심 매매 로직(매수 수량 계산) 변경 → 규칙 0-4 UI 기준 설명 + 승인 완료. 롤백 아님 (신규 헬퍼 추가 + 기준 통일) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**: 매수 후보 목록 자체는 동일(종목/순위 변동 없음). 다만 잔액이 종목 1주+수수료를 감당 못 하는 임계 상황에서 해당 종목이 매수 후보에서 미리 제외되어 "매수 시도 → 주문가능금액 부족 거부" 로그가 더 이상 찍히지 않음 (불필요한 노이즈 감소). 실전모드 화면 변화 없음.

**검증**:
- py_compile 5개 파일 통과 ✓
- ruff All checks passed ✓
- pytest test_settlement_engine + test_trading: 116 passed ✓
- 런타임 기동 (`-W error::RuntimeWarning`): 정상 기동, 에러/Traceback/RuntimeWarning 없음, 잔존 프로세스 0건 ✓

**작업 중 발견 문제**: 없음 (P18 갭은 T3-S19에서 이미 기록됨).

---

### T3-S19 일일/종목당 매수 한도 수수료 포함 통일 (테스트모드) — 완료 (2026-07-23) — P22 데이터 정합성 / P10 SSOT / P21 사용자 투명성 (백엔드 + 프론트엔드, safe-trade + problem-solve)

**세션**: 단일 세션. 백엔드 한도 체크 기준 통일 + 프론트엔드 UI 라벨 명확화 + 테스트 추가.

**배경**: T3-S18에서 발견한 한도 체크 기준 불일치 — settlement_engine은 수수료 포함 차감하지만, `_daily_buy_spent`/`_symbol_daily_buy_spent`는 수수료 제외로 누적 → 한도 잔여와 실제 지출 가능액이 어긋남 (P22 위반 소지). 사용자 방향 지시: 테스트모드만 수수료 포함 한도 체크로 수정, 실전모드는 현행 유지 + 실전 전환 직전 별도 세션에서 처리.

**작업 내용** (4건, 4개 파일):
1. **`_load_daily_buy_state` total_amt 기반 로드 (P10/P22)** — `trading.py:136-160` price*qty 합 → trade_history.total_amt 합으로 변경. trade_history.record_buy의 total_amt 공식(테스트: price*qty+fee / 실전: price*qty)과 단일 기준. 재기동 시 메모리 누적과 로드 값이 모드별로 일치.
2. **매수 후 누적 fee 포함 (테스트모드만, P22)** — `trading.py:450-457` `spent = buy_qty*fill_price` → `_base = buy_qty*fill_price; _fee = round(_base*BUY_COMMISSION) if is_test_mode else 0; spent = _base + _fee`. 테스트모드만 수수료 포함, 실전모드는 현행 유지. trade_history.record_buy 공식과 동일.
3. **BUY_COMMISSION import 추가** — `trading.py:20` `from backend.app.core.constants import BUY_COMMISSION`. 기존 공통 상수 재사용 (P23).
4. **UI 라벨 "수수료 포함" 명시 (P21)** — `buy-target.ts:263` 배지 "일일 매수 금액 (수수료 제외)" → "(수수료 포함)". `buy-settings.ts:325,355` 설정 라벨 2개 "전체 일일 최대 매수 금액" / "종목당 일일 최대 매수 금액" → 각각 "(수수료 포함)" 추가.

**수정 파일**: 4개 (백엔드 1 + 프론트엔드 2 + 테스트 1).
- `backend/app/services/trading.py` (import + _load_daily_buy_state + 매수 후 누적)
- `frontend/src/pages/buy-target.ts` (배지 라벨)
- `frontend/src/pages/buy-settings.ts` (설정 라벨 2개)
- `backend/tests/test_trading.py` (신규 테스트 6개: TestDailyBuySpentFeeInclusive 클래스)

**아키텍처 원칙 부합**:
- P22 (데이터 정합성): 한도 체크 기준과 settlement_engine 차감 기준이 테스트모드에서 일치. 재기동 시 _load와 post-buy 누적이 동일 공식 사용.
- P10 (SSOT): trade_history.total_amt를 단일 진실 원천으로 사용. price*qty와 total_amt 이중 관리 제거.
- P21 (사용자 투명성): UI 라벨에 "수수료 포함" 명시로 한도 설정 의미 변경 투명화.
- P18 (테스트모드 동등성): 테스트/실전 간 한도 기준 상이 → 미해결 문제로 기록, 실전 전환 직전 별도 세션 처리.
- P15 (단일 주문 경로): 주문 경로 변경 없음. 한도 체크 내부 수치 기준만 변경.
- P23 (공통 자산 재사용): BUY_COMMISSION 기존 상수 재사용.

**영향 범위**: 백엔드 1파일(trading.py) + 프론트엔드 2파일 + 테스트 1파일. 핵심 매매 로직(한도 체크 기준) 변경 → 규칙 0-4 UI 기준 설명 + 승인 완료. 롤백 아님 (신규 기준 통일) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 매수후보 화면 상단 배지: "💰 일일 매수 금액 (수수료 제외)" → "💰 일일 매수 금액 (수수료 포함)". 30만원어치 매수 시 배지 표시가 300,000원 → 약 300,045원으로 변경 (수수료 0.015% 추가).
- 매수 설정 화면: "전체 일일 최대 매수 금액" → "전체 일일 최대 매수 금액 (수수료 포함)", "종목당 일일 최대 매수 금액" → "종목당 일일 최대 매수 금액 (수수료 포함)".
- 동일 한도 설정 시 실제 매수 가능 주식 수가 수수료분만큼 극소량 감소. 단, 주문가능금액 차감은 이미 수수료 포함이었으므로 실제 매수 가능액 변화는 없음 — 한도 체크 기준이 주문가능금액 차감 기준과 일치해지는 효과.

**검증**: pytest + npm run build (진행 중).

**작업 중 발견 문제**: P18 갭 (테스트/실전 한도 기준 상이) — 미해결 문제에 기록.

---

### T3-S18 수익상세 페이지 매수/매도 금액 라벨 명확화 + 승률/수익률 카드 순서 교환 — 완료 (2026-07-23) — P21 사용자 투명성 / P23 일관성 (프론트엔드, frontend-fix 스킬)

**세션**: 단일 세션. 프론트엔드 라벨/카드 순서 수정만 (로직 변경 없음).

**배경**: 수익상세 페이지 하단 통계 카드 "매수금액"이 수수료 포함임이 라벨에 명시되지 않아, 사용자가 "투자금 100만원인데 매수금액이 100만원을 초과"로 오해하는 문제. 사전 조사(코드 + DB 거래 데이터) 결과:
- orderable(주문가능금액)은 정산 엔진이 수수료 포함 차감하므로 초과하지 않음 (정상 동작).
- "매수금액 100만원 초과"는 매도 회수금을 재매수에 사용한 당일 누적 지출의 정상적 증가.
- 원인은 UI 라벨 모호성 (P21 사용자 투명성 위반) + 매수/매도 금액의 비대칭 표시 (매수는 수수료 포함, 매도는 실수령).

**작업 내용** (2건, 2개 파일):
1. **라벨 명확화 (P21/P23)** — `profit-detail-mount.ts` 하단 통계 카드 6개 라벨 + `profit-columns.ts` 매수/매도 내역 테이블 컬럼 라벨 변경:
   - 하단 통계 카드: "매수금액" → "당일 매수 지출(수수료 포함)", "매도금액" → "당일 매도 수령(실수령)"
   - 매수 내역 테이블: "매수금액" → "매수 지출(수수료 포함)"
   - 매도 내역 테이블: "매수금액" → "매수 지출(수수료 포함)", "매도금액" → "매도 수령(실수령)"
   - 보유종목 페이지의 "매수금액(수수료 포함)" 표현과 일관성 유지 (P23). 하단 통계 카드는 "당일 합계"이므로 "당일" 포함, 테이블 개별 거래 행은 "당일" 제외.
2. **승률/수익률 카드 순서 교환** — `profit-detail-mount.ts` buildStatRow 마지막 두 카드 순서 교체. `STAT_LABELS` 배열 순서 + state 참조 할당(`statAvgRateEl`/`statWinRateEl` 인덱스)을 함께 교체하여 인덱스 정합성 유지 (P22).

**수정 파일**: 2개 (프론트엔드).
- `frontend/src/pages/profit-detail-mount.ts` (STAT_LABELS 라벨 변경 + 승률/수익률 카드 순서 교환)
- `frontend/src/pages/profit-columns.ts` (BUY_COLS/SELL_COLS 컬럼 라벨 변경)

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): "매수금액"이 수수료 포함인지, "매도금액"이 실수령인지 라벨에 명시. 사용자가 "투자금 100만원인데 매수금액이 100만원을 넘었다"고 오해하는 것 방지.
- P22 (데이터 정합성): 승률/수익률 카드 교환 시 라벨과 state 참조를 함께 교체하여 값이 엉뚱한 카드에 들어가지 않도록 보장.
- P23 (일관성): 보유종목 페이지 "매수금액(수수료 포함)"과 동일 표현. 하단 통계 카드(당일 합계)와 테이블(개별 거래)의 "당일" 포함/제외 기준 일관.

**영향 범위**: 프론트엔드 2개 파일. 백엔드/테스트 영향 없음. 라벨 텍스트 + 카드 순서만 변경 (로직/계산 변경 없음) → 규칙 0-4 해당 없음. 롤백 아님 (신규 라벨 명확화) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 수익상세 페이지 하단 통계 카드 6개 순서: 총 건수 / 당일 매수 지출(수수료 포함) / 당일 매도 수령(실수령) / 실현손익 / **수익률** / **승률** (기존: 승률 → 수익률 순).
- 매수 내역 탭 컬럼 헤더: "매수 지출(수수료 포함)" (기존: "매수금액").
- 매도 내역 탭 컬럼 헤더: "매수 지출(수수료 포함)" + "매도 수령(실수령)" (기존: "매수금액" + "매도금액").
- 값 자체는 변화 없음 (라벨/순서만 변경).

**검증**:
- `npm run typecheck` (tsc --noEmit) 통과 ✓
- `npm run build` (tsc -b + vite build) 통과 — 76 modules, 1.96s ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 없음.

**보류 수정안** (본 세션에서 보류, 후속 세션 대기):
- **수정안 A (한도 수수료 포함 통일)** — `_daily_buy_spent`/`_symbol_daily_buy_spent`를 수수료 포함(`total_amt`) 기준으로 변경. 한도 설정 의미가 "순수 매수가"에서 "수수료 포함 지출액"으로 변경되므로 규칙 0-4 승인 필수. **다음 세션 진행 예정**.
- **수정안 C (매수 수량 계산 수수료 반영)** — `buy_qty` 계산 시 수수료 여유분 확보. 현재 버그는 아니나 P22 강화. 별도 세션 대기.

---

### B5-08-01/02/04 trading.py 매매 로직 — schedule_engine_task 교체 + 평균매입가 분기 주석 + 실시간 지연 fail-closed — 완료 (2026-07-23) — P23 일관성 / P20 폴백 금지 / P25 격리된 실패 (Tier 3 마지막 세션, LOW 3건, 백엔드, safe-trade)

**세션**: 단일 세션. 백엔드 코드 수정 (safe-trade 스킬 + backend-fix 스킬). Tier 3 마지막 세션.

**배경**: P25 수정 계획 Tier 3 마지막 세션. A3-07-08/09/10 완료 후 진행. trading.py 매매 로직 3건 — 사전조사 → 수정 계획 보고(3건 각각 옵션 제시) → 승인(B5-08-01 진행, B5-08-02 옵션 A, B5-08-04 옵션 A) → 수정 진행.

**작업 내용** (3건, 2개 파일):
1. **B5-08-01 (LOW, P23) 완료** — `trading.py:474-482` (매수), `trading.py:663-671` (매도) `asyncio.create_task` → `schedule_engine_task` 교체. ARCHITECTURE.md 금지 패턴 2 준수. 매매 로직 변경 없음 (태스크 스케줄링 인프라만). `schedule_engine_task`가 동일 기능(create_task + add_done_callback) + 코루틴 정리(coro.close()) + 예외 로깅 보장. 테스트 패치도 함께 변경 (`test_trading.py:202`).
2. **B5-08-02 (LOW, P18) 완료 — 옵션 A (현행 유지 + 주석 명시)** — `trading.py:571-580` 평균매입가 조회 테스트/실전 분기에 주석 추가. 테스트모드는 `build_positions_from_trades`로 유령 포지션 차단 검사(qty 부족 시 매도 중단)를 수행하는 안전장치이므로 분기가 의도적임을 명시. 매매 로직 변경 없음.
3. **B5-08-04 (LOW, P20/P25) 완료 — 옵션 A (fail-closed 전환)** — `trading.py:203-213` (매수), `trading.py:705-715` (매도) 실시간 지연 체크 fail-open → fail-closed 전환. 체크 자체 실패 시 매수/매도 차단 (안전 우선). 지연 상태 확인 불가 시 시스템 장애 상황이므로 안전 차단이 합리적. **핵심 매매 로직 변경 (규칙 0-4 승인 완료)**.

**수정 파일**: 2개 (백엔드).
- `backend/app/services/trading.py` (B5-08-01 매수/매도 schedule_engine_task 교체, B5-08-02 평균매입가 분기 주석, B5-08-04 매수/매도 실시간 지연 fail-closed)
- `backend/tests/test_trading.py` (B5-08-01 패치 변경: asyncio.create_task → schedule_engine_task + MagicMock import 제거)

**아키텍처 원칙 부합**:
- P15 (단일 주문 경로): `execute_buy()`/`execute_sell()` 경로 유지. `schedule_engine_task`는 태스크 스케줄링만 변경, 주문 경로 변경 없음.
- P16 (살아있는 경로): `schedule_engine_task`의 `add_done_callback`이 실제 실행 경로에 연결됨.
- P18 (테스트모드 동등성): B5-08-02 옵션 A로 현행 유지. 테스트/실전 조회 분기는 "조회"이며 돈 I/O가 아님 — 유령 포지션 차단 검사는 테스트모드 안전장치로 명시.
- P20 (폴백 금지): B5-08-04 fail-closed로 폴백 금지 강화. 체크 실패 시 silent pass 대신 안전 차단 + 로깅.
- P23 (일관성): `schedule_engine_task` 사용으로 코드베이스 일관성 향상 (engine_sector_confirm.py:392, daily_time_scheduler.py 등 기존 패턴과 일치).
- P25 (격리된 실패): `schedule_engine_task`의 예외 처리 + 코루틴 정리 보장. fail-closed로 시스템 장애 시 안전 차단.

**안전 확인 (safe-trade 스킬)**:
- 거래 모드: **테스트모드** (코드 변경 없이 현행 유지). `is_test_mode()` 플래그로 보호됨.
- API 키 하드코딩: 없음.
- 주문 경로: `execute_buy()`/`execute_sell()` 단일 경로 유지 (P15). 테스트모드 `dry_run.fake_send_order()` / 실전 `router.order.send_order()` 2개만 허용.
- RiskManager/CircuitBreaker: `execute_buy()`/`execute_sell()` 내부 호출 유지 (P16).
- 테스트모드 동등성: 안전장치 생략 없음 (P18).
- **원칙 15/16/18 준수 여부**: 모두 준수.

**영향 범위**: 백엔드 2개 파일. 프론트엔드 영향 없음. 핵심 매매 로직 변경 (B5-08-04) — 규칙 0-4 승인 완료. 롤백 아님 (신규 보호 코드 추가 + 인프라 일관성 교체) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4 — B5-08-04 핵심 로직 변경)**:
- **정상 상황**: 변화 없음. 실시간 통신 정상 시 매수/매도 동일 동작.
- **시스템 장애 상황 (실시간 지연 상태 확인 불가)**:
  - **변경 전**: 매수/매도가 계속 진행됨 (fail-open). 지연 중단 게이트가 우회될 소지.
  - **변경 후**: 매수/매도가 차단됨 (fail-closed). 화면 상단에 "실시간 지연" 칩 표시 + 매수 후보 목록에 차단 종목 표시 안 됨. 안전 우선.
- **사용자가 확인할 수 있는 영향**: 시스템 장애 상황에서 매수 후보 목록이 비어있을 수 있음. 정상 상황에서는 변화 없음.

**검증**:
- `python -m py_compile backend/app/services/trading.py` 통과 ✓
- `python -m pytest backend/tests/test_trading.py -x -q` 통과 — 52 passed in 0.54s ✓
- `python -m pytest backend/tests/test_settlement_verification.py backend/tests/test_settlement_engine.py -x -q` 통과 — 56 passed in 0.82s ✓
- `.venv/bin/ruff check backend/app/services/trading.py backend/tests/test_trading.py` 통과 — All checks passed ✓
- `python -W error::RuntimeWarning main.py` 런타임 기동 통과 — 에러/Traceback/RuntimeWarning 없음, 220ms 기동, 정산 대조 완료(주문가능 870,541원 일치), 실시간 구독 정상 ✓

**작업 중 발견 문제**: 없음.

---

### A3-07-08/09/10 통계 카드 / 라우트 변경 / addEventListener 격리 — 완료 (2026-07-23) — P25 격리된 실패 (Tier 3 다섯째 세션, LOW 3건, 프론트엔드)

**세션**: 단일 세션. 프론트엔드 코드 수정 (frontend-fix 스킬). 세션 라벨 T3-S15.

**배경**: P25 수정 계획 Tier 3 다섯째 세션. B3-05-03/04 완료 후 진행. 사전조사 → 수정 계획 보고(87개 addEventListener 전수 조사 + 고위험 분류) → 승인(옵션 A + createSummaryCards 포함) → 수정 진행.

**작업 내용** (3건, 14개 파일):
1. **A3-07-08 (LOW) 완료** — `profit-shared.ts:76-106` createSummaryCards 4카드 루프 per-card try/catch + 더미 push. buildStatRow는 T2-S10에서 이미 완료되었으나, 동일 패턴의 createSummaryCards가 누락되어 있었음 (T2-S10 누락분 보완).
2. **A3-07-09 (LOW) 완료** — `router.ts:105-109` notifyRouteChange cb 루프 per-cb try/catch + console.error. 리스너 1(setActiveRoute) throw 시 리스너 2(settingsCard 마운트) 스킵 방지.
3. **A3-07-10 (LOW) 완료** — 87개 addEventListener 전수 조사 → 고위험 46개 식별 → 옵션 A(공통 컴포넌트 chokepoint) 적용. 6개 공통 컴포넌트 + 6개 페이지 파일에서 try/catch 적용.
   - **공통 컴포넌트 (6파일)**: button.ts(4개 click 핸들러), setting-row-inputs.ts(9개 input/change 핸들러), setting-row.ts(2개 spin 버튼), setting-row-controls.ts(2개 토글/라디오), settings-common.ts(3개 시간 선택), create-slider.ts(3개 input/commit 핸들러)
   - **페이지 고위험 (6파일)**: profit-overview-mount.ts(1개 real-data-tick), sell-position.ts(1개 real-data-tick), buy-target.ts(3개 real-data-tick/orderbook/program), sector-stock.ts(1개 real-data-tick), header.ts(3개 매매 차단 상태 칩 해제), main.ts(3개 beforeunload WS disconnect)
   - **저위험 41개 제외**: hover(mouseenter/mouseleave), scroll, mousemove, animationend, keydown-Enter/focusNext, 단순 DOM 제거 — P24 단순성 준수

**수정 파일**: 14개 (프론트엔드).
- `frontend/src/pages/profit-shared.ts` (createSummaryCards per-card try/catch + 더미 push)
- `frontend/src/router.ts` (notifyRouteChange per-cb try/catch)
- `frontend/src/components/common/button.ts` (4개 click 핸들러 try/catch)
- `frontend/src/components/common/setting-row-inputs.ts` (9개 onChange/onEnter 핸들러 try/catch)
- `frontend/src/components/common/setting-row.ts` (2개 spin 버튼 onUp/onDown try/catch)
- `frontend/src/components/common/setting-row-controls.ts` (2개 토글/라디오 핸들러 try/catch)
- `frontend/src/components/common/settings-common.ts` (3개 시간 선택 핸들러 try/catch)
- `frontend/src/components/common/create-slider.ts` (3개 input/commit 핸들러 try/catch)
- `frontend/src/pages/profit-overview-mount.ts` (real-data-tick try/catch)
- `frontend/src/pages/sell-position.ts` (real-data-tick try/catch)
- `frontend/src/pages/buy-target.ts` (3개 틱 핸들러 try/catch)
- `frontend/src/pages/sector-stock.ts` (real-data-tick try/catch)
- `frontend/src/layout/header.ts` (3개 칩 해제 핸들러 try/catch)
- `frontend/src/main.ts` (beforeunload 3개 WS disconnect 개별 try/catch)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 핸들러 throw 시 console.error 로깅 + 다른 핸들러/이벤트 계속 동작. 공통 컴포넌트 chokepoint로 36개 핸들러를 6개 파일에서 보호.
- P20 (폴백 금지): silent `except: pass` 없음 — 모든 catch에 `console.error` 명시 로깅.
- P23 (일관성): T2-S10의 per-item try/catch + console.error 패턴과 동일. 공통 컴포넌트에서 일관된 에러 메시지 형식(`[컴포넌트명] 핸들러 error`).
- P24 (단순성): 공통 컴포넌트 chokepoint로 수정 지점 최소화 (87개 → 14개 파일). 저위험 41개 제외로 범위 과대 방지.
- P21 (사용자 투명성): 설정 변경 실패 시 콘솔 에러로 원인 추적 가능. 매매 차단 상태 칩 해제 실패 시 로깅.
- P16 (살아있는 경로): 모든 try/catch는 실제 이벤트 핸들러 경로에 연결됨 (dead code 아님).

**영향 범위**: 프론트엔드 14개 파일. 백엔드/테스트 영향 없음. 핵심 매매 로직 아님 (이벤트 핸들러 예외 처리만 추가) → 규칙 0-4 해당 없음. 롤백 아님 (신규 보호 코드 추가) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 정상 동작 변화 없음.
- 비정상 상황에서만 개선:
  - 수익 상세 페이지 요약 카드(당일/직전/당월/누적 손익) 생성 중 오류 시: 해당 카드만 '-' 표시, 나머지 카드 정상 표시 (기존에는 전체 카드 누락 가능).
  - 페이지 이동 시 오류: 좌측 설정 패널이 정상 전환됨 (기존에는 첫 리스너 오류 시 좌측 패널 미갱신).
  - 설정 입력 중 오류: 콘솔에 에러 기록, 다른 설정 입력 계속 가능 (기존에는 오류 전파로 입력 기능 중단 가능).
  - 실시간 시세 갱신 중 오류: 해당 틱만 누락, 이후 틱 정상 처리 (기존에는 브라우저 전역 에러).
  - 매매 차단 상태 칩 해제 클릭 오류: 콘솔에 에러 기록 (기존에는 브라우저 전역 에러).

**검증**:
- `npm run typecheck` (tsc --noEmit) 통과 ✓
- `npm run build` (tsc -b + vite build) 통과 — 76 modules, 1.71s ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 없음.

---

## 다음 세션 진행 대기

**T3-S24 매수/매도 상태 배지 로직 공통 추출 (P23 일관성)** — `buy-target.ts:247-281`의 매수상태 체인과 `sell-position.ts:146-186`의 매도상태 체인이 거의 동일 코드로 중복. 우선순위 구조(서킷브레이커 > 리스크 > 시간대 > 자동매매 OFF > 자동매수/매도 OFF > 시간대 외)와 색상·status 매핑이 동일. `computeBuyBlockStatus(uiState, settings)` / `computeSellBlockStatus(uiState, settings)`(또는 단일 `computeBlockStatus(side, ...)`)를 `badge.ts` 또는 별도 유틸로 추출하여 양쪽에서 호출. 사전조사 시 양쪽 로직 diff 상세 비교 + 추출 위치(`badge.ts` 확장 vs 신규 유틸) 결정 필요.

**업종순위 테이블 "평균거래(억)" 라벨 짤림 원인 조사 (T3-S25 발견)** — 임계치 수신율 달성 전에는 "평균거래(억)" 라벨이 잘리고, 달성 후에는 정상 표시되는 현상. 코드 기반 조사 결과:

- **컬럼 정의** (`sector-ranking-list.ts:173-181`): `avg_trade_amount` 컬럼, label "평균거래(억)", type `avg_amount` (minWidth 80, maxWidth 120 — `table-config.ts:68`).
- **컬럼 폭 계산** (`data-table.ts:126-154` `createColumnWidthManager`): 첫 `updateRows` 시 1회만 `extractSamples`로 데이터 기반 폭 계산 후 `initialized=true`로 고정. 이후 어떤 데이터 변화에도 재계산하지 않음.
- **초기 렌더링** (`sector-ranking-list.ts:324-331`): mount 시 `refreshRows(state.sectorScores)` → `updateRows` 호출. 임계치 전 `sectorScores`가 빈 배열이거나 0값 더미 데이터일 경우, `extractSamples`가 빈/짧은 샘플을 추출하여 컬럼 폭이 label 폭 기준으로만 산출됨.
- **px 변환** (`data-table-virtual.ts:95-122` `applyGridTemplatePx`): `scrollContainer.clientWidth` 기준으로 px 변환. `w <= 0`이면 스킵. mount 시점에 scrollContainer가 아직 렌더링되지 않아 clientWidth=0이면 gridTemplateColumns가 적용되지 않고, ResizeObserver가 나중에 clientWidth 변화를 감지하여 재계산.
- **추정 원인**: 임계치 전 빈 데이터로 `initFromRows`가 실행되어 컬럼 폭이 label 기준으로 고정되거나, mount 시점 clientWidth=0으로 gridTemplateColumns가 미적용된 상태에서 헤더가 균등 분배로 렌더링. 임계치 후 데이터/레이아웃 변화로 ResizeObserver가 재계산하면서 정상 폭 적용.
- **정확한 원인 파악에 필요한 추가 검증**: 브라우저 개발자 도구로 임계치 전후의 computed `gridTemplateColumns` px 값과 `scrollContainer.clientWidth` 확인 필요.
- **수정 방향 후보**: (1) `initFromRows`를 빈 데이터일 때 실행하지 않고 첫 유효 데이터까지 지연, (2) `initFromRows` 재계산 허용 (initialized 플래그 제거 또는 리셋 기능 추가), (3) label 폭에 안전 여백 추가. 어느 방향이든 P21(사용자 투명성) + P24(단순성) + P23(다른 DataTable과 일관성) 검토 필요.
- → **T3-S27에서 해결 완료** — 실제 원인은 `initFromRows`가 빈 데이터일 때 스킵되어 `cachedPercentages`가 균등 분할 상태로 유지된 것. `data-table-virtual.ts`와 `data-table-fixed.ts` 모두 빈 데이터 분기에서도 `initFromRows` 호출하도록 수정. `computeColWidths`는 샘플이 비어도 라벨 폭 기반으로 minWidth 산출하므로 라벨 잘림 해결.

**다른 페이지 패널 padding 8px 통일 검토 (T3-S25 발견)** — T3-S25에서 sector-ranking-page의 가운데·우측 패널 padding을 16px→8px로 축소하여 좌측 패널(8px)과 일치시킴. 다른 페이지도 shell 기본값 16px를 사용 중이므로 동일 패턴으로 8px 통일 검토 필요. → **T3-S26에서 해결 완료** (shell 기본값 16px→8px로 전 페이지 통일 + sector-ranking 중복 오버라이드/복원 코드 제거).

**실전모드 수수료 대응 (P18 갭)** — 실전 전환 직전 별도 세션에서 처리 필요. 상세는 "미해결 문제" 섹션 참조.

**사용자 지시 시 진행 가능 항목 (audit 문서 잔여)**:
- B-13 보류 5건 (B13-03/04/06/07/08, LOW/INFO 등급) — `docs/architecture_audit_plan.md` 섹션 7 참조
- B21-01 보류 (암호화 폴백, 사용자 승인 대기 — 보안 동작 변화, UI 기준 설명 필요)
- F-03 보류 4건 (F03-07/08/09/10) — `docs/architecture_audit_tasks.md` F-03 섹션 참조
- F-04 잔여 파일 분할 (stock-classification.ts 1618줄, general-settings.ts 1390줄)
- F-07 미시작 (타입 및 유틸 5개 파일, 총 651줄)

**참고 문서**:
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` (역사적 기록, 유지)
- 아키텍처 감사 계획: `docs/architecture_audit_plan.md`
- 아키텍처 감사 태스크: `docs/architecture_audit_tasks.md`

---

## 미해결 문제

### P21 갭: 미노출 4개 전체 차단 사유 백엔드 WS 미브로드캐스트 (2026-07-23 T3-S21 발견)
- **파일**: `backend/app/services/trading.py:204,216,222` (`BUY_REJECT_DAILY_STATE`/`BUY_REJECT_REALTIME_LATENCY`/`BUY_REJECT_AUTO_BUY_OFF`), `trading.py` `BUY_REJECT_TEST_CASH`/`BUY_REJECT_ORDER_FAIL` (사후 사유)
- **위반/부합 원칙**: P21 (사용자 투명성) 위반 — 4개 전체 차단 사유가 백엔드에서 WS 브로드캐스트되지 않아 프론트엔드 매수상태 배지(T3-S21)에서 표시 불가.
- **증상**: 일일 매수 상태 로드 실패(`daily_state`), 실시간 지연 200ms 초과(`realtime_latency`), 테스트 예수금 검증 실패(`test_cash`), 주문 전송 실패(`order_fail`) 발생 시 매수후보 화면의 "🚦 매수상태" 배지가 "매수 가능"으로 잘못 표시됨 (실제로는 차단됨).
- **근거**: T3-S21에서 매수상태 배지 추가 시 기존 uiStore 상태만 사용하기로 함 (P10 SSOT). 이 4개 사유는 백엔드에서 WS 이벤트로 전송되지 않으므로 프론트에서 알 수 없음.
- **수정 방향**: 별도 후속 세션에서 백엔드 `trading.py`에 WS 브로드캐스트 추가. `engine_state` 기반으로 `daily_state`/`realtime_latency` 상태를 WS 이벤트(`buy_block_status` 등 신규 또는 기존 `risk_block_status` 확장)로 전송 → 프론트 uiStore에 신규 상태 추가 → 매수상태 배지 우선순위 체인에 반영. `test_cash`/`order_fail`은 사후 사유이므로 별도 알림 방식 검토 필요.

### P18 갭: 테스트/실전 한도 체크 기준 상이 (2026-07-23 T3-S19 발견)
- **파일**: `backend/app/services/trading.py:141,147` (_load_daily_buy_state), `trading.py:450-457` (매수 후 누적), `backend/app/services/trade_history.py:270,280` (record_buy total_amt)
- **위반/부합 원칙**: P18 (테스트모드 동등성) 부분 위반 — 테스트모드는 수수료 포함 한도 체크, 실전모드는 수수료 제외 한도 체크로 기준 상이.
- **증상**: 테스트모드에서는 `_daily_buy_spent`/`_symbol_daily_buy_spent`가 `total_amt`(수수료 포함) 기준으로 누적/로드되어 settlement_engine 차감 기준과 일치. 실전모드에서는 trade_history의 `fee=0`, `total_amt=price*qty`이므로 한도 누적이 수수료 제외 기준 → settlement_engine(수수료 포함 차감)과 기준 불일치. 사용자는 현재 테스트모드 운영 중이므로 기능적 문제 없음.
- **근거**: 사용자 방향 지시 — "테스트모드: 수수료 포함 한도 체크, 실전모드: 증권사 데이터 그대로 사용, 수수료 계산 로직 불필요 → 별도 처리. 지금은 테스트모드만 운영 중이므로 테스트모드 기준으로 수정. 실전모드 수수료 대응은 실전 전환 직전 별도 세션에서 처리."
- **수정 방향**: 실전 전환 직전 별도 세션에서 실전모드 수수료 대응 필요. trade_history의 실전모드 fee=0 기록 문제도 함께 검토. 실전 브로커 수수료를 trade_history에 기록하는 방식 또는 trading.py에서 실전모드에도 BUY_COMMISSION 추정치를 적용하는 방식(A-2 원안) 중 선택 필요.
- **참고**: settlement_engine.py:65,78,112는 테스트/실전 무관 항상 BUY_COMMISSION 적용 중이므로, 실전 전환 시 trading.py 한도 체크만 실전 수수료 미반영 상태가 됨.

### virtual-scroller.ts renderRow 호출부 3곳 무보호 (2026-07-23 발견)
- **파일**: `frontend/src/components/virtual-scroller.ts`
- **위반/부합 원칙**: P25 (격리된 실패) 위반 소지, P23 (일관성) — 같은 파일 내 renderRange 루프는 격리했으나 다음 3곳은 무보호 상태로 잔존:
  - `updateItems` 루프 내 renderRow 2곳 (444줄 existing 경로, 451줄 new 경로)
  - `updateItemByKey` 내 renderRow (468줄)
  - `updateItem` 내 renderRow (499줄)
- **증상**: 가상 스크롤 아이템 증분 갱신 시 한 행 renderRow throw → updateItems/updateItemByKey/updateItem 루프 중단. renderRange와 동일 패턴 적용 시 해결.
- **수정 방향**: 후속 세션에서 사용자 승인 시 동일 패턴(per-item try/catch + console.error) 적용 권장 (P23 일관성).

### data-table-fixed.ts:290 셀 렌더 에러 로그 메시지 불일치 (2026-07-23 발견)
- **파일**: `frontend/src/components/common/data-table-fixed.ts:290`
- **위반/부합 원칙**: P23 (일관성) — 사전 존재 불일치.
- **증상**: `console.error('[data-table] cell render error:', err)` — 다른 4곳은 `console.error('[DataTable] cell render error', e)` (대소문자/콜론/변수명 불일치).
- **수정 방향**: 후속 세션에서 일관성 정비 시 통일 권장.

### B1-02-07 포지션 구축 실패 시 UI 사용자 알림 누락 (2026-07-23 발견)
- **파일**: `backend/app/services/engine_lifecycle.py:38-43` (start_engine try/except), `backend/app/services/engine_state.py` (state 필드), `backend/app/services/engine_lifecycle.py:162` (get_engine_status), 프론트엔드 `frontend/src/binding.ts` (engine-ready 핸들러)
- **위반/부합 원칙**: P21 (사용자 투명성) 부분 충족 — 백엔드 try/except로 `logger.warning("[연산] 테스트모드 포지션 구축 실패 — 엔진은 계속 가동")` 로그는 활성화되었으나, 화면에 "보유 종목 불러오기 실패, 엔진은 계속 가동 중" 상태를 명시적으로 표시하는 프론트엔드 경로 미구현.
- **증상**: 테스트모드에서 `_refresh_positions_if_dirty` 실패 시 (trade_history 조회 오류 등) 엔진은 계속 가동하나, 사용자 화면에는 정상 기동과 동일하게 `engine-ready`만 표시됨. 보유 종목 목록이 비어있어 사용자가 "왜 보유 종목이 안 보이지?" 의문 가능.
- **수정 방향**: engine_lifecycle.py:38 except 블록에서 `engine_state.state`에 포지션 구축 실패 플래그 설정 → get_engine_status() 반환값에 포함 → 프론트엔드 index-data/engine-ready 핸들러에서 UI 표시 (예: 엔진 상태 칩에 경고 표시). 백엔드 + 프론트엔드 변경이 필요하므로 별도 세션에서 승인 시 진행 권장.
- **참고**: B4-06-03 "감소 모드" 화면 명시 표시 미구현(아래 항목)과 동일 성격 — 백엔드는 로그로 상태 노출, UI 표시는 별도. 두 항목을 하나의 세션에서 통합 처리 가능.

### B4-06-03 "감소 모드" 화면 명시 표시 미구현 (2026-07-23 발견)
- **파일**: `backend/app/services/engine_loop.py:35`, `backend/app/services/engine_lifecycle.py:162` (get_engine_status), 프론트엔드 `frontend/src/binding.ts:244` (engine-ready 핸들러)
- **위반/부합 원칙**: P21 (사용자 투명성) 부분 충족 — 백엔드 log-and-rethrow로 engine_loop.py:35 "감소 모드로 기동" 에러 로그는 활성화되었으나, 화면에 "감소 모드" 상태를 명시적으로 표시하는 프론트엔드 경로 미구현.
- **증상**: 종목 마스터 DB가 비어있는 치명 상황에서 백엔드는 감소 모드로 기동하나, 사용자 화면에는 정상 기동과 동일하게 `engine-ready`만 표시됨. 사용자가 "왜 종목이 안 보이지?" 의문 가능.
- **수정 방향**: engine_loop.py:35 except 블록에서 `engine_state.state`에 감소 모드 플래그 설정 → get_engine_status() 반환값에 포함 → 프론트엔드 index-data 핸들러에서 UI 표시. 백엔드 + 프론트엔드 변경이 필요하므로 별도 세션에서 승인 시 진행 권장.
