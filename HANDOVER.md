# SectorFlow Handover

## 세션 개요
- 날짜: 2026-07-15 (종목분류페이지 필터요약 라벨 우측 정렬 + 두 줄 표시)
- 작업: 종목분류페이지 상단 헤더에서 필터요약 라벨을 좌측 버튼 영역에서 우측 끝으로 이동하고, 한 줄 긴 텍스트를 두 줄(요약/주요 제외)로 분리 표시.
- 상태: 구현 + 검증 완료, 커밋 완료.

## 직전 완료 작업 (이번 세션)

### 1. 종목분류페이지 필터요약 라벨 우측 정렬 + 두 줄 표시 — `stock-classification.ts` (1개 파일)

**배경**: 필터요약 라벨("전체 4297종목 → 매매 가능 1341종목 (제외 2956종목, 69%) | 주요 제외: 증거금100%종목 1224개, ETF 1147개, ...")이 좌측 다운로드 버튼 2개와 같은 줄에 붙어있어, 화면이 좁으면 `nowrap + ellipsis`로 "주요 제외: ..." 부분이 잘려서 안 보이는 문제.

**수정 내용**:
- **모듈 변수 분리**: `indicatorLabel` (단일 span) → `indicatorLabelMain` + `indicatorLabelSub` (두 span).
- **`buildTripleHeader()`**: `indicatorLabel`을 좌측 버튼 컨테이너에서 제거. 우측 영역(`right`, flex:1)을 빈 공백에서 `flexDirection: column, alignItems: flex-end, textAlign: right` 컨테이너로 변경. 메인 줄(`FONT_SIZE.body`, `COLOR.neutral`) + 서브 줄(`FONT_SIZE.small`, `COLOR.tertiary`) 두 span 추가.
- **`updateIndicatorBar()`**: `filter_summary` 문자열을 ` | ` 기준으로 split — 첫 부분은 `indicatorLabelMain`, "주요 제외: ..."는 `indicatorLabelSub`에 표시. 분리 기준 없으면 메인에 전체 표시, 빈 값이면 두 줄 모두 클리어.
- **cleanup**: `indicatorLabel = null` → `indicatorLabelMain = null` + `indicatorLabelSub = null`.

**검증 결과**:
- typecheck 통과 (초기 `COLOR.secondary` 미존재 에러 → `COLOR.neutral`로 수정 후 통과)
- 빌드 성공 (stock-classification 번들 26.68 kB)
- 백엔드 런타임 이미 실행 중 (PID 22959), 정상 응답 확인

**영향 범위**: 프론트엔드 1개 파일만 변경. 백엔드/테스트 영향 없음. `filter_summary` 데이터 흐름 변화 없음 (문자열 표시만 분리).

**아키텍처 원칙 부합**: P21 (사용자 투명성 — 요약 정보가 잘리지 않고 전부 표시), P23 (용어 통일 — 텍스트 변경 없음), P24 (단순성 — DOM 요소 재배치만).

## 다음 세션 작업
- **다운로드 완료 시간 표시 (제안2)**: 1일봉/5일봉 다운로드 버튼 우측에 가장 최근 다운로드 완료 시간 표시. 백엔드 신규 기능 필요 — 현재 DB에 다운로드 완료 시간 저장소 없음 (`master_stocks_table.date`/`stock_5d_bars.dt`는 거래일이지 다운로드 시각 아님). 사전조사: 다운로드 파이프라인 완료 지점, 저장소 설계(system_state_cache 또는 신규 테이블), P10 SSOT/P22 정합성 점검 후 설계 제안.
- 실전모드 보관 기준(`RETENTION_TRADING_DAYS_REAL = 90`) 추후 논의 — 사용자가 "증권사 서버에 데이터가 다 있으니 추후 논의"라고 명시.
- 기존 발견 문제: `notify_raw_real_data` dead code (P16) 별도 검토 필요 시 사용자 지시.

## 직전 완료 작업 (이전 세션)

### 1. 안건 3 문서 보강 — AGENTS.md 규칙 0-3/0-4/0-5 + 스킬 4개 사전조사 항목 (5개 파일)

**배경**: 사용자가 설계한 `_received_codes`가 승인 없이 "dead code"로 제거되고, `ratio_5d`가 사용자 모르게 추가되는 문제 확인.

**수정 내용**:
- **AGENTS.md 섹션3 규칙 0에 하위 항목 3개 추가**:
  - **규칙 0-3 (승인 없는 롤백 절대 금지)**: 코드를 이전 상태로 되돌리는 모든 행위(코드 제거, 함수/변수 삭제, git revert/reset, 구조 회귀)는 사유·대상·영향 범위 보고 후 승인 필수. "dead code로 판단되어 제거" 단독 사유로 사용자 설계 로직 승인 없이 되돌리는 것 명시적 금지.
  - **규칙 0-4 (핵심 로직 변경 시 UI 기준 설명+승인)**: 수신률·업종 점수·매매 로직·매수 후보 선정·매도 조건 변경 시 변경 전/후 동작을 UI 기준 일반 용어로 설명 후 승인. 기술 식별자만 나열하고 UI 설명 생략 금지.
  - **규칙 0-5 (사용자 설계/승인 로직 더 엄격)**: 사용자가 직접 설계/승인한 로직 변경 시 사유·영향 범위·대안 상세 보고 후 승인 필수.
- **스킬 4개 사전조사 섹션에 "기존 로직 롤백 여부 확인" 항목 추가**:
  - `backend-fix/SKILL.md`: 수신률·업종 점수·매매 로직 예시
  - `frontend-fix/SKILL.md`: 매수 후보 목록·업종 점수 표시·보유 종목 등 핵심 화면 예시
  - `problem-solve/SKILL.md`: 핵심 기능 전체 예시
  - `safe-trade/SKILL.md`: 거래 로직 최우선 엄격 적용 명시 (돈이 직결되므로 규칙 0-4/0-5를 다른 스킬보다 더 엄격하게 적용)

**검증 결과**: git diff로 5개 파일 교차 참조 일관성 확인 완료. 규칙 번호 체계(0→0-1→0-2→0-3→0-4→0-5→1) 순서 정렬 확인.

**영향 범위**: 문서 파일 5개만 변경. 코드 변경 없음.

**커밋**: `ac3fbbf` — docs: 승인 없는 롤백 금지 + 핵심 로직 변경 UI 설명 의무 + 사용자 설계 로직 엄격 절차 규칙 추가

### 2. 정산 만료 기록 정리 로직 수정 — `trade_history.py` + `test_trade_history.py` (2개 파일)

**문제**: 로그 `[정산] 만료 기록 정리 완료 — 테스트모드 보관기간=2026-01-13, 실전모드 보관기간=2026-03-09`에서 보관기간이 과거 날짜로 표시되어 최근 거래 기록이 삭제되고 있는지 의심.

**조사 결과**:
- 최근 데이터 삭제 문제는 없었음 — `date < cutoff` 조건으로 cutoff 이전 데이터만 삭제, cutoff 이후~오늘 데이터 보존. 오늘(7/15) 데이터 103건/89건 DB에 안전 존재 확인.
- 실제 문제 2가지: (1) 테스트모드 보관 기준이 거래일 125일(≈1월 13일)로 달력 기준 6개월과 미세 불일치, (2) 로그가 매 실행마다 출력되며 "보관기간" 모호 용어로 오해 유발 (P21 위반).

**수정 내용**:
- **상수 변경**: `RETENTION_TRADING_DAYS_TEST = 125` → `RETENTION_MONTHS_TEST = 6` (달력 기준 6개월). 실전모드 `RETENTION_TRADING_DAYS_REAL = 90` 현행 유지 (추후 논의 대상).
- **cutoff 계산 변경**: `get_recent_trading_days(125)[0]` → `get_kst_today() - relativedelta(months=6)` (달력 6개월).
- **DB COUNT 사전 조회**: 삭제 대상 건수를 COUNT 쿼리로 조회 → 0건이면 DELETE 실행 안 함 + 로그 출력 안 함.
- **조건부 로그**: 삭제 발생 시에만 INFO 로그 출력 — "테스트모드 6개월 이전 매매 기록 N건 삭제 완료" / "실전모드 90거래일 이전 매매 기록 N건 삭제 완료".
- **except에 `exc_info=True` 추가** (스택 트레이스 기록).
- **테스트 3건 수정**: `test_test_mode_6_months_expired` (달력 6개월 기준), `test_real_mode_90_days_preserved` (DB COUNT=0 → DELETE 미호출 검증), `test_trim_exception_logged` (`get_kst_today` mock).

**검증 결과**:
- py_compile 2개 파일 통과
- pytest 64개 테스트 전체 통과 (0.39s)
- 런타임 기동 (`-W error::RuntimeWarning`) 정상, 에러/Traceback/RuntimeWarning 없음. "만료 기록 정리" 로그 출력 안 됨 (삭제 대상 0건 → 조건부 로그 정상 동작). 체결 이력 103건/89건 정상 로드. 금지 패턴 5개 없음.
- 잔존 프로세스 0건 확인

**영향 범위**: `trade_history.py` (상수 1개 + `_trim_expired()` 함수), `test_trade_history.py` (`TestTrimExpired` 3개 테스트). `_trim_expired`는 `_ensure_loaded()`에서만 호출 (앱 기동 시 1회). 프론트엔드 영향 없음.

## 다음 세션 작업
- 실전모드 보관 기준(`RETENTION_TRADING_DAYS_REAL = 90`) 추후 논의 — 사용자가 "증권사 서버에 데이터가 다 있으니 추후 논의"라고 명시.
- 기존 발견 문제: `notify_raw_real_data` dead code (P16) 별도 검토 필요 시 사용자 지시.

## 직전 완료 작업 (이전 세션)

### dead code 4건 제거 + FID 11 폴백 제거 (11개 파일) — 커밋 `f5047b6`

### 수신률 100% 왜곡 근본 해결 — _received_codes 복원 + 모든 경로 None→0 폴백 제거 (7개 파일) — 커밋 `eb1836b`

### P-001 Step 3: 업종 점수 계산 None 폴백 제거 + 미수신 종목 제외 — `sector_calculator.py`

**수정 내용**: `backend/app/domain/sector_calculator.py:68-87` — `change_rate`/`trade_amount`의 `or 0` 폴백 제거, None 유지. None인 종목은 `ratio_5d` 계산 전에 `continue`로 업종 점수 계산에서 제외.
- `change_rate` — None이면 None 유지, 값이 있으면 `float()` 변환 (라인 70-71)
- `trade_amount` — None이면 None 유지, 값이 있으면 `int()` 변환 (라인 81-82)
- None 제외 필터 `if change_rate is None or ta is None: continue` (라인 86-87)
- **계획서 결함 수정**: 계획서 4-3-2는 필터를 라인 101(StockScore 생성 전)에 배치하도록 명시했으나, 라인 95의 `ratio_5d` 계산(`ta > 0` 비교)이 먼저 실행되어 None 비교 TypeError 발생. 필터를 라인 78 직후(`ta` 할당 바로 다음, `ratio_5d` 계산 이전)로 조정.

**검증 결과**:
- py_compile 통과
- `test_sector_calculator.py` 34개 테스트(기존 28 + 신규 6) 전부 통과 (0.15s)
  - 신규 테스트 6개: `change_rate=None` 제외, `trade_amount=None` 제외, 전체 None → 빈 결과, `0.0` 제외 안 됨(정상 수신 0%), `0` 제외 안 됨(정상 수신 0원), None 종목 ratio_5d TypeError 미발생
- 런타임 기동 (`-W error::RuntimeWarning`) 정상, 에러/Traceback/RuntimeWarning 없음, 업종순위 재계산 2회 정상 완료, 금지 패턴 5개 로그 없음
- 잔존 프로세스 0건 확인

**영향 범위**: `sector_calculator.py` 1개 파일. `sector_score.py`(`sc.rise_ratio`, `sc.avg_trade_amount`, `stock.change_rate` 참조) — None 제거된 데이터만 들어오므로 수정 불필요. `models.py` `StockScore`(`change_rate: float`, `trade_amount: int`) — 제외 필터 후 None이 StockScore에 들어가지 않으므로 타입 변경 불필요. 프론트엔드 — 영향 없음 (이미 null 안전). 기존 테스트 28개 — `0.0`/`0` 정상 수신 케이스는 제외되지 않아 전부 통과.

## 직전 완료 작업 (이전 세션)

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
