# SectorFlow Handover

## 세션 개요
- 날짜: 2026-07-15 (P-001 Step 2 수정 세션)
- 작업: P-001 Step 2 — `pipeline_compute.py:576` 보유종목 틱 rate 폴백 제거
- 상태: Step 2 구현 + 검증 완료, 커밋 완료

## 직전 완료 작업 (이번 세션)

### P-001 Step 2: 보유종목 틱 rate 폴백 제거 — `pipeline_compute.py`

**수정 내용**: `backend/app/pipelines/pipeline_compute.py:575-576` — FID 12(등락률) 값이 빈 문자열이거나 키가 없으면 None 저장, 값이 있으면 기존 파서 호출.
- FID 12 키 없음 → `_raw12 = None` → `rate = None` (미수신)
- 빈 문자열 → `"".strip()` falsy → `rate = None` (미수신)
- `"0"` → `parse_change_rate_to_percent("0")` → `0.0` 저장 (정상 수신 0%)
- `"1.5"` → `1.5` 저장 (정상 수신)
- 계획서 원안 대비 P24 개선: `_ws_fid_raw` 1회 호출로 간소화 (원안은 2회 호출 + `_ws_fid_key_present` 중복)

`_has_any_realtime_data` (`pipeline_compute.py:91-97`)는 **변경 없음**. Step 1 완료로 `master_stocks_cache` 빈 값이 None으로 저장되므로 기존 `is not None` 체크가 정상 동작 (None=미수신, 0.0=정상 수신 0% 구분).

**검증 결과**:
- py_compile 통과
- `test_pipeline_compute.py` 87개 테스트 전부 통과 (0.20s)
- 런타임 기동 (`-W error::RuntimeWarning`) 정상, 에러/Traceback/RuntimeWarning 없음, 금지 패턴 5개 로그 없음
- 잔존 프로세스 0건 확인

**영향 범위**: 보유종목 틱 처리 경로 `rate` 지역 변수 + `_dr_pos["change_rate"]` 저장 1곳. `_recalc_pnl`은 change_rate 미사용 → 안전. 보유종목 새로고침 `if old.get(f) is not None` 보존 로직 → None이면 보존 안 함, 안전. 보유종목 UI는 `sectorStock?.cur_price` 기준 자체 계산 → 안전. 수신률/업종점수/REST 잔고 경로 영향 없음.

**작업 중 발견 문제 (P-001 범위 외)**:
- `pipeline_compute.py:575` FID 11(대비) 빈 값 → 0 폴백 (P20). 수신률/업종점수 미사용이라 P-001 범위 외. 별도 검토.
- `engine_account_notify.py:350` `notify_desktop_trade_price` dead code (P16). 프로덕션 호출처 없음. 별도 검토.

## 다음 세션 작업 (P-001 Step 3)
- `sector_calculator.py:69,78` 업종 점수 폴백 제거 (None을 0으로 폴백하지 않고 미수신 종목 제외).
- 사전조사는 `docs/plan_P001_fix.md` Step 3 섹션 참조.

## 직전 완료 작업 (이전 세션)

### P-001 Step 1: 틱 수신 경로 폴백 제거 — `engine_radar.py`

**수정 내용**: `backend/app/services/engine_radar.py:73-83` — FID 12(등락률)/14(거래대금) 값이 빈 문자열이면 None 유지 (할당 생략), 값이 있으면 기존 파서 호출.
- 빈 문자열 → None 유지 (미수신, P20 폴백 금지 준수)
- `"0"` → `parse_change_rate_to_percent("0")` → `0.0` 저장 (정상 수신)
- `"1.5"` → `1.5` 저장 (정상 수신)

**검증 결과**:
- py_compile 통과
- `test_engine_ws_parsing.py` 107개 테스트 전부 통과 (파서 자체 미변경)
- 런타임 기동 (`-W error::RuntimeWarning`) 정상, 에러/Traceback/RuntimeWarning 없음, 금지 패턴 5개 로그 없음
- 잔존 프로세스 0건 확인

**영향 범위**: 틱 수신 경로만. REST 잔고 경로 영향 없음. 소비자 전수 조사 결과 회귀 없음 (`trading.py` None 안전, `sector_calculator.py`/`get_trade_amount_cache` None→0 폴백으로 기존 동작 동일, 프론트엔드 null 안전).

### P-001 수정계획서 작성 (이전 세션, 사전조사 완료)
1. `docs/plan_P001_fix.md` 신규 작성 — P-001 근본 원인 해결을 위한 3단계 수정계획서.
2. 사전조사 범위:
   - `parse_change_rate_to_percent` 호출처 2곳 추적 (둘 다 틱 수신 경로).
   - `_parse_float_loose` 호출처 6곳 추적 (1곳 틱, 5곳 REST 잔고).
   - `_parse_int_loose` 호출처 추적 (REST 잔고 전용, P-001 무관).
   - 확정 데이터 경로 2곳 패턴 분석 (`daily_time_scheduler.py` "0값은 덮지 않음" vs `market_close_pipeline.py` 무조건 덮기 — P23 불일치).
   - `sector_calculator.py:69,78` None 폴백 확인 (2차 왜곡 원인, HANDOVER 원안에 미포함 → Step 3로 추가).
   - `trading.py:218-219` None 안전 확인 (이미 `is not None` 체크).
   - 프론트엔드 `!= null` 체크 확인 (이미 null 안전, 수정 불필요).
   - 보유종목 평가 경로 확인 (`_recalc_pnl`은 change_rate 미사용, 안전).
   - `notify_desktop_trade_price` / `notify_raw_real_data` dead code 확인 (별도 P16 이슈).
3. HANDOVER 원안 대비 주요 변경:
   - **세션 분할 순서 변경**: 원안(1단계=원인 B, 2단계=원인 A) → 본 계획서(1단계=원인 A, 2단계=원인 B 검증, 3단계=점수). 원인 B 먼저 시 정상 0% 등락률 오분류 발생.
   - **원인 B 판정식 변경**: 원안(`is not None and != 0`) → 본 계획서(`is not None` 유지). 원인 A 수정 후 None이 저장되므로 `!= 0` 불필요.
   - **파서 자체 미변경**: `parse_change_rate_to_percent`/`_parse_float_loose` 자체는 변경하지 않고 호출부에서 빈 값 체크. REST 경로 호환성 유지.
   - **`sector_calculator.py` 수정 추가**: 원안에 미포함된 2차 왜곡 원인. Step 3로 추가.
   - **단계 수 변경**: 2단계 → 3단계.

## 직전 완료 작업 (이전 세션)
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
- **최우선: P-001 Step 2 진행 — 사용자 승인 후**
  - Step 1 완료 (본 세션). `engine_radar.py:73-77` 틱 수신 폴백 제거 완료.
  - Step 2 (세션 2): `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + `_has_any_realtime_data` 검증. 영향 범위 중간.
  - Step 3 (세션 3): `sector_calculator.py:69,78` 업종 점수 폴백 제거. 영향 범위 넓음.
  - 각 Step 시작 시 사용자 명시적 승인 필요.
- 사용자 UI 확인 후 추가 컬럼 너비 조정이 필요하면 해당 페이지만 override로 진행.

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
