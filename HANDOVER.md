# SectorFlow Handover

## 세션 개요
- 날짜: 2026-07-15 (에이전트 규칙/스킷 업데이트 — 발견 문제 기록 의무에 '개선점' 추가 + 롤백 사유 기록 의무 신설)
- 작업: 1) AGENTS.md 규칙 9 "작업 중 발견 문제 기록 의무"에 "개선점(아키텍처 원칙에 부합하는 더 나은 구조)" 추가 + 객관적 근거 인정 기준 명시. 5개 스킬 파일 동일 문구로 통일. 2) AGENTS.md 규칙 0-3에 "롤백 사유 기록 의무" 하위 항목 신설 (git commit 메시지 + HANDOVER.md). problem-solve 스킬에 "롤백으로 증상 덮기 금지" 추가.
- 상태: 구현 + 검증 완료, 커밋 완료.

## 직전 완료 작업 (이번 세션)

### 1. 발견 문제 기록 의무에 '개선점' 추가 — AGENTS.md 규칙 9 + 5개 스킬 (6개 파일)

**배경**: AGENTS.md 규칙 9 "작업 중 발견 문제 기록 의무"는 위반/오류/버그/dead code/폴백 패턴 중심이며, problem-solve 스킬에는 이미 "개선점"이 언급되어 있어 양쪽 불일치 (P23 위반 소지). 사용자 제안으로 "아키텍처 원칙에 부합하는 더 나은 구조(개선점)"를 기록 대상에 추가.

**수정 내용**:
- **AGENTS.md 규칙 9 본문**: "아키텍처 위반(P원칙), 오류, 잠재적 버그, dead code, 폴백 패턴, 아키텍처 원칙에 부합하는 더 나은 구조(개선점) 등"으로 확장.
- **AGENTS.md 규칙 9 하위 항목 신설 "개선점 인정 기준 (P24 준수)"**: 주관적 취향이 아닌 객관적 근거 있는 것만 — (a) 특정 P원칙에 부합하여 정량적으로 더 단순/일관/정합 (b) 기존 공통 자산 재사용으로 중복 제거 (c) 명확한 중복·dead code·폴백 회피 가능. 근거 없는 "더 좋을 것 같음"은 기록 대상 아님.
- **AGENTS.md 규칙 9 기록 형식**: "위반 원칙 번호" → "위반/부합 원칙 번호(개선점의 경우)" 확장. 세션 종료 보고 문구 "N건의 신규 문제" → "N건의 신규 문제/개선점" 확장.
- **5개 스킬 파일** (problem-solve, backend-fix, frontend-fix, safe-trade, db-backup) "작업 중 발견 문제 기록 의무" 섹션: 동일 문구로 통일. problem-solve는 95행 기존 "개선점" 단어에 조건 명시 보완 (객관적 근거, P24 준수, AGENTS.md 상세 참조).

**검증 결과**: grep으로 6개 파일 동일 문구 확인 완료. 구 문구("폴백 패턴 등") 잔존 0건.

**영향 범위**: 문서 파일 6개만 변경. 코드 변경 없음.

**아키텍처 원칙 부합**:
- P10 (SSOT): AGENTS.md 규칙 9가 단일 진실 소스, 5개 스킬은 "상세 규칙은 AGENTS.md 섹션4 규칙 9 참조" 역참조.
- P23 (일관성): 6개 파일 동일 문구, problem-solve 기존 "개선점"과 AGENTS.md 본문 정합.
- P24 (단순성): 개선점 인정 기준으로 남발 방지, 규칙 비대화 회피.

### 2. 롤백 사유 기록 의무 신설 + 롤백으로 증상 덮기 금지 — AGENTS.md 규칙 0-3 + problem-solve 스킬 (2개 파일)

**배경**: AGENTS.md 규칙 0-3 "사용자 승인 없는 롤백 절대 금지"는 승인 자체는 담당하나, 승인 후 **사유 기록** (git commit 메시지, HANDOVER.md)은 명시되어 있지 않았음. 나중에 git log나 HANDOVER.md만 보는 사람이 "왜 이전 상태로 되돌아갔지?" 오인하는 빈틈. 또한 problem-solve 스킬에 롤백과 근본 해결의 관계 미명시.

**수정 내용**:
- **AGENTS.md 규칙 0-3 하위 항목 신설 "롤백 사유 기록 의무 (강제)"**: 사용자 승인받아 롤백 진행한 경우, (1) git commit 메시지에 사유·되돌린 대상·영향 범위 상세 기록 ("revert" 한 단어로 끝내지 않음), (2) HANDOVER.md "직전 완료 작업" 섹션에 롤백 내용과 사유 명시.
- **problem-solve/SKILL.md 7항 "근본 원인 식별"**: "롤백으로 증상 덮기 금지" 추가 — 롤백 후에도 근본 원인이 남아있으면 재발. 롤백이 적절한 경우(잘못된 변경 되돌림, 승인받은 경우)와 부적절한 경우(증상 회피용) 구분 명시. AGENTS.md 규칙 0-3 역참조.

**검증 결과**: grep으로 4개 스킬(problem-solve/backend-fix/frontend-fix/safe-trade) "기존 로직 롤백 여부 확인" 항목이 "AGENTS.md 섹션3 규칙 0-3 준수" 역참조 확인 → 0-3에 하위 항목 추가하면 자동 전파 구조 정상.

**영향 범위**: 문서 파일 2개만 변경. 코드 변경 없음. 4개 스킬은 역참조 구조로 개별 수정 불필요 (P10 SSOT 유지).

**아키텍처 원칙 부합**:
- P10 (SSOT): AGENTS.md 규칙 0-3이 단일 진실 소스, 4개 스킬은 역참조로 자동 전파.
- P23 (일관성): problem-solve "롤백으로 증상 덮기 금지"가 AGENTS.md 0-3 역참조로 정합.
- P24 (단순성): 이미 존재하는 규칙 1·2(승인 없는 롤백 금지, 로직 변경 보고 의무)는 중복 추가하지 않고, 빈틈(기록 의무)만 보완.

## 직전 완료 작업 (이전 세션)

### 수익상세페이지 상단 카드 3→4 확장 + 기간별 색상 차별화 + 하단 통계 연동 (3개 파일) — 커밋 `09629b8`

**배경**: 수익상세페이지 상단 요약 카드가 당일/당월/누적 3개이며, 선택 시 모두 동일 파랑 색상이라 어떤 기간을 보고 있는지 시각적 구분이 안 됨. 수익현황(overview) 차트에는 이미 '직전' 버튼이 있어 두 페이지 간 빠른 범위 옵션이 불일치. 사용자 제안으로 '직전' 카드 추가 + 4카드 색상 차별화 + 하단 6개 통계 카드 색상 연동.

**수정 내용**:
- **`frontend/src/components/common/ui-styles.ts`**: 기간 구분 전용 색 3종 추가 (기존 의미 색 success/warning/up/kosdaq과 충돌 회피). `periodPrev`(#0097a7 청록)/`periodPrevBg`(#e0f7fa), `periodMonth`(#7b1fa2 보라)/`periodMonthBg`(#f3e5f5), `periodTotal`(#455a64 슬레이트)/`periodTotalBg`(#eceff1). 당일은 기존 `down`/`downBg` 재사용.
- **`frontend/src/pages/profit-shared.ts`**: `SummaryCardEls` 인터페이스에 `prevPnlEl`/`prevRateEl`/`prevCard` 추가. `SummaryCardCallbacks`에 `onPrevClick` 추가. `createSummaryCards` 3카드→4카드 확장 (CARD_TITLES = 당일/직전/당월/누적). `updateSummaryCards`에 직전 손익 계산 추가 — dailySummary에서 오늘보다 이전 날짜 중 가장 최근 항목 추출 (O(n) 단일 패스, 백엔드 추가 호출 없이 기존 데이터에서 파생).
- **`frontend/src/pages/profit-detail.ts`**:
  - `SelectedView` 타입에 `'prev'` 추가. `loadProfitDetailView` validViews 및 from/to 검증 조건에 'prev' 포함.
  - `applyCardStyle`을 카드별 보더/배경 색상 받도록 변경. `updateCardSelection`이 4카드 각각 해당 색상 적용.
  - 신규 `updateStatCardSelection()` — 하단 6개 통계 카드 색상을 상단 선택 기간과 동일 색으로 연동. `selectedView === null`(수동 날짜) 시 회색(borderLight/surfaceLight) 복귀.
  - `onPrevClick` 핸들러 — `api.getPrevTradingDay()` 비동기 조회 후 `filterByDate(prev.date)`. await 중 다른 카드 클릭 시 덮어쓰기 방지 가드(`if (selectedView !== 'prev') return`) 추가.
  - 하단 통계 카드 생성 시 `statCardEls` 배열에 push하여 색상 연동 대상 관리. unmount에서 초기화.
  - `api` import 추가 (`../api/client`).

**검증 결과**:
- typecheck 통과, 빌드 성공 (62 modules).
- 테스트 108개 전체 통과 (기존 실패 없음, profit 관련 테스트는 없으나 전체 회귀 확인).

**영향 범위**: 프론트엔드 3개 파일. 백엔드 변경 없음 (기존 `getPrevTradingDay` API 재사용). profit-overview는 `createSummaryCards` 미사용이라 영향 없음. 공유 함수 `createSummaryCards`의 실제 사용처는 profit-detail 1곳.

**아키텍처 원칙 부합**:
- P10 (SSOT): 공유 함수 1곳에서 4카드 관리, 직전 손익은 기존 dailySummary에서 파생 (중복 저장 금지).
- P21 (사용자 투명성): 하단 통계 색상 연동으로 "현재 보는 기간" 상단/하단 양쪽 시각화, 수동 날짜 시 회색 복귀로 상태 명확.
- P23 (일관성): overview 차트 '직전' 버튼과 detail '직전' 카드 일치, 기존 의미 색 충돌 회피한 신규 기간 구분 색 추가.
- P24 (단순성): 보더+옅은 배경으로 손익 텍스트 색(빨강/파랑)과 충돌 회피, 직전 손익 O(n) 단일 패스 추출.

## 다음 세션 작업
- **최우선: P-001 Step 2 진행 — 사용자 승인 후**
  - Step 1 완료. `engine_radar.py:73-77` 틱 수신 폴백 제거 완료.
  - Step 2 (세션 2): `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + `_has_any_realtime_data` 검증. 영향 범위 중간.
  - Step 3 (세션 3): `sector_calculator.py:69,78` 업종 점수 폴백 제거. 영향 범위 넓음.
  - 각 Step 시작 시 사용자 명시적 승인 필요.
- **다운로드 완료 시간 표시 (제안2)**: 1일봉/5일봉 다운로드 버튼 우측에 가장 최근 다운로드 완료 시간 표시. 백엔드 신규 기능 필요 — 현재 DB에 다운로드 완료 시간 저장소 없음 (`master_stocks_table.date`/`stock_5d_bars.dt`는 거래일이지 다운로드 시각 아님). 사전조사: 다운로드 파이프라인 완료 지점, 저장소 설계(system_state_cache 또는 신규 테이블), P10 SSOT/P22 정합성 점검 후 설계 제안.
- 실전모드 보관 기준(`RETENTION_TRADING_DAYS_REAL = 90`) 추후 논의 — 사용자가 "증권사 서버에 데이터가 다 있으니 추후 논의"라고 명시.
- 기존 발견 문제: `notify_raw_real_data` dead code (P16) 별도 검토 필요 시 사용자 지시.
- 사용자 UI 확인 후 추가 컬럼 너비 조정이 필요하면 해당 페이지만 override로 진행.

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

## 미해결 문제

### P-001: 실시간 데이터 미수신 시 0 폴백 → 수신률 100% 왜곡 + 업종 점수 왜곡

**현상**: HD현대 등 종목의 실시간 데이터 필드가 0 또는 "-"로 표시되는데, 업종순위 계산 임계치 수신률은 100%로 표시됨. 사용자 지적: "0을 데이터로 인식해서 왜곡".

**근본 원인 (2단계 연쇄, 코드 경로로 모두 확정)**

#### 원인 A — 미수신 데이터를 0으로 폴백 저장 (P20 폴백 금지 위반)
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/services/engine_ws_parsing.py:155-156` | `parse_change_rate_to_percent(None)` → `0.0` 반환. 빈 문자열·"0"도 모두 `0.0` 반환. |
| `backend/app/services/engine_account_rest.py:21-22` | `_parse_float_loose(None)` → `0.0` 반환. |
| `backend/app/services/engine_radar.py:75` | 틱 수신 시 FID 12(등락률) 값이 비어 있으면 `parse_change_rate_to_percent`를 거쳐 `entry["change_rate"] = 0.0` 저장. None이 아닌 0.0 저장. |
| `backend/app/services/engine_radar.py:77` | 틱 수신 시 FID 14(거래대금) 값이 비어 있으면 `_parse_float_loose`를 거쳐 `entry["trade_amount"] = 0` 저장. None이 아닌 0 저장. |

#### 원인 B — 수신률 계산이 0과 None을 구분하지 않음 (P22 데이터 정합성 위반)
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/pipelines/pipeline_compute.py:97` | `_has_any_realtime_data()`가 `entry.get(f) is not None`로만 판정. `0.0`/`0`은 None이 아니므로 "수신됨"으로 카운트. |
| `backend/app/pipelines/pipeline_compute.py:118-126` | `received_count`에 0으로 폴백된 종목이 포함됨. 결과: 실제 수신되지 않은 종목이 수신률 100%에 포함. |

**수신률 100%가 업종순위 계산 시작 조건과 연결되는 경로 (확정)**
1. `pipeline_compute.py:704` — Phase 1 루프에서 `_calculate_receive_rate()` 호출.
2. `pipeline_compute.py:706` — `_current_receive_rate["pct"]`를 `current_pct`로 읽음.
3. `pipeline_compute.py:716` — `if current_pct >= threshold_pct:` 수신률이 임계값 이상이면 통과.
4. `pipeline_compute.py:721` — `mark_sector_threshold_passed()` 호출 → 이후 sector-scores 전송 허용.
5. `pipeline_compute.py:722` — `request_sector_recompute(None)` 호출 → 콜드 스타트 1회 전체 재계산 트리거.
6. `engine_account_notify.py:273-276` — `is_sector_threshold_passed()`가 False면 sector-scores 전송 차단, True면 허용.

**확정된 사실**: 0으로 폴백된 종목이 수신률을 100%로 끌어올리고, 100%가 임계값 통과 조건이 되어 업종순위 계산이 시작됨. 실제로는 데이터가 부족해도 임계값이 통과됨.

**0이 섞인 데이터가 업종 점수 계산에 미치는 영향 (확정)**
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/domain/sector_calculator.py:69` | `change_rate = float(detail.get("change_rate", 0) or 0)` — 0이 유효 데이터로 StockScore에 저장. |
| `backend/app/domain/sector_calculator.py:78` | `ta = int(detail.get("trade_amount", 0) or 0)` — 0이 유효 데이터로 StockScore에 저장. |
| `backend/app/domain/sector_calculator.py:129` | `raw_rise_count = sum(1 for s in filtered_stocks if s.change_rate > 0)` — 0은 상승 종목에서 제외되어 `rise_ratio`(상승비율)를 낮춤. |
| `backend/app/domain/sector_calculator.py:132-133` | `raw_total_ta = sum(s.trade_amount ...)` → `avg_ta = raw_total_ta // raw_total` — 0이 거래대금 합산에 포함되어 `avg_trade_amount`를 낮춤. |
| `backend/app/domain/sector_calculator.py:134` | `avg_cr = sum(s.change_rate ...) / len(filtered_stocks)` — 0이 평균 등락률에 포함되어 `avg_change_rate`를 낮춤. |
| `backend/app/domain/sector_score.py:106-107` | `rise_values = [sc.rise_ratio ...]` → 1차 가산점(상승비율 순위) 계산에 0으로 왜곡된 `rise_ratio` 사용. |
| `backend/app/domain/sector_score.py:112-113` | `ta_values = [float(sc.avg_trade_amount) ...]` → 3차 가산점(거래대금 순위) 계산에 0으로 왜곡된 `avg_trade_amount` 사용. |
| `backend/app/domain/sector_score.py:142` | `all_entries.append((stock.change_rate, sc.sector))` → 2차 가산점(가중 순위 합)에 0인 `change_rate` 포함. |

**확정된 사실**: 0으로 폴백된 데이터가 1차·2차·3차 가산점 모두에 영향을 줌. 업종 점수 순위가 왜곡됨.

**현재가 0 표시 경로 (확정)**
- 틱 처리 `pipeline_compute.py:553` — `last_px <= 0`이면 틱 차단. 틱 경로로는 0이 들어가지 않음.
- 현재가 0은 초기 스냅샷/REST 로드 시점에 0으로 저장된 것이 화면에 남아있는 상태에서, 이후 해당 종목으로 틱이 아직 수신되지 않았을 때 발생.

**수정계획서**: `docs/plan_P001_fix.md` (2026-07-15 작성 완료)

**진행 상황**:
- **Step 1 완료 (2026-07-15)**: `engine_radar.py:73-77` 틱 수신 폴백 제거. 빈 FID 12/14 → None 유지. 검증 완료 (py_compile + 테스트 107개 통과 + 런타임 기동 정상).
- **Step 2 대기**: `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + 수신률 판정 검증.
- **Step 3 대기**: `sector_calculator.py:69,78` 업종 점수 폴백 제거.

**수정 방안 (수정계획서 기반)**
- **원인 A 해결 (Step 1, 2)**: `parse_change_rate_to_percent`·`_parse_float_loose` 자체는 변경하지 않음(REST 경로 호환성). 틱 수신 경로(`engine_radar.py:73-77`, `pipeline_compute.py:576`)에서 빈 문자열 체크 후 None 저장. (P20 폴백 금지 준수)
- **원인 B 해결 (Step 2)**: `_has_any_realtime_data`(`pipeline_compute.py:97`)는 `is not None` 체크 유지. 원인 A 수정 후 None이 저장되므로 `!= 0` 불필요. (정상 0% 등락률 오분류 방지)
- **업종 점수 왜곡 해결 (Step 3)**: `sector_calculator.py:69,78`에서 None을 0으로 폴백하지 않고 None 유지. 미수신 종목(change_rate 또는 trade_amount가 None)은 점수 계산에서 제외. (P22 데이터 정합성 준수)
- **연쇄 영향 조사 완료**: `parse_change_rate_to_percent` 호출처 2곳(둘 다 틱 경로), `_parse_float_loose` 호출처 6곳(1곳 틱, 5곳 REST), `sector_calculator.py` None 폴백, `trading.py` None 안전, 프론트엔드 null 안전, 보유종목 평가 안전. 상세는 수정계획서 섹션 2 참조.

**세션 분할 (수정계획서 기반)**
- Step 1 (세션 1): `engine_radar.py:73-77` 틱 수신 폴백 제거. 영향 범위 좁음.
- Step 2 (세션 2): `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + 수신률 판정 검증. 영향 범위 중간.
- Step 3 (세션 3): `sector_calculator.py:69,78` 업종 점수 폴백 제거. 영향 범위 넓음.
- **HANDOVER 원안 대비 변경**: 원안(1단계=원인 B, 2단계=원인 A)은 정상 0% 등락률 오분류 결함이 있어 순서 변경. 원안의 `!= 0` 판정식도 동일 이유로 제거.

**검증 방법 (수정 후)**
- 백엔드 런타임 기동 후, 틱이 일부만 수신된 상태에서 수신률이 100%가 아닌 실제 비율로 표시되는지 확인.
- 화면에서 0/- 로 표시되던 종목이 데이터 미수신 시 일관되게 "-"로 표시되는지 확인.
- 업종 점수 순위가 0 왜곡 없이 계산되는지 확인.

**관련 원칙**: P10(SSOT), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(일관성).
**조사 세션**: 2026-07-15.

## 참고 사항
- `master_stocks_table`의 `cur_price`, `change`, `change_rate`, `trade_amount`는 현재 스냅샷에서 비어 있어, 수치 기준은 `stock_5d_bars`와 `trades`를 사용함.
- `auto-width.ts`의 `KOREAN_SCALE` 조정은 너비 추정 정확도에 큰 영향을 줌. 변경 없이는 `종목명` 9자만 되어도 150px 이상을 요구해 공간 낭비가 큼.
- `sector-ranking-list.ts`와 `profit-overview.ts`는 `DataTable`이 아니므로 별도 처리 필요.
- 컬럼 너비 공통 상수(`COLUMN_WIDTH`)는 min/max px 경계값이며, 실제 비율은 데이터 기반 px→% 정규화로 페이지별 컬럼 구성에 자동 적응함. per-page override는 `ColumnDef`의 `minWidth`/`maxWidth` 필드로 이미 지원.
