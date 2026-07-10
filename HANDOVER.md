# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-10: 검색 입력란 전수조사 및 공통 컴포넌트 통일 — 5페이지 7개 인스턴스 일원화 + label/compact 옵션 + 포커스 언더라인 + placeholder 색상**
  - 목적: 각 페이지가 검색 입력란의 라벨/색상/스타일을 자체 구현하여 7개 검색란 스타일 분산 → 공통 컴포넌트 `search-input.ts`에 기능 내장 후 전 페이지 통일
  - `search-input.ts`: `label`/`labelColor`/`compact` 옵션 추가, `width` 기본값 `100%`→`180px`, input에 `sf-search-input` 클래스 추가, 텍스트 색상 `COLOR.code` 명시, 포커스 언더라인 강조 (`boxShadow: inset 0 -2px 0 borderColor`, HTS 스타일), compact 모드(아이콘/클리어버튼 off, padding 2px 4px, fontSize 12px), 라벨 폰트 `FONT_SIZE.section`(14px) 통일
  - `index.html`: `.sf-search-input::placeholder { color: #9e9e9e; }` CSS 추가 (COLOR.disabled 통일 — JS inline style로는 ::placeholder 설정 불가)
  - `sector-stock.ts`: 자체 라벨 span 2개(stockSearchWrapper/sectorSearchWrapper) 제거, 컴포넌트 `label` 옵션 사용 (종목명/코드 파랑, 업종명 주황), width 180px 기본값 적용
  - `stock-classification.ts`: 종목 검색(파랑 라벨+border, width 100%), 대상업종 검색(주황 라벨+border, width 100%) 추가
  - `stock-detail.ts`: 라벨 "종목명 / 코드" + 파랑 border + width 180px 통일 (검색란은 line 150에 이미 존재, 스타일 통일 작업)
  - `buy-target.ts`: 자체 라벨 span 제거, 컴포넌트 `label` 옵션 사용
  - `profit-detail.ts`: stockFilterInput을 `createSearchInput` compact 모드로 교체, `.value.trim()`→`.getValue()` (3곳), 자체 "종목:" 라벨 제거, width 180px 통일
  - 색상 구분 (검색 대상별): 종목명/코드=🔵COLOR.down(파랑), 업종/섹터=🟠COLOR.warning(주황)
  - 검증: tsc 타입체크 0 에러, vite build 통과 (57 모듈), vitest 109/109 통과
  - 커밋: (이번 커밋)
- **2026-07-10: 프론트엔드 색상 체계 통일 — 하드코딩 색상 ~190곳 COLOR 상수로 일원화 + secondary→tertiary 통합**
  - 목적: 28개 파일에 분산된 하드코딩 색상(~190곳)을 `ui-styles.ts` COLOR 상수로 통일, `secondary`(#888)를 `tertiary`(#666)로 통합하여 라벨/설명문 색상 일원화
  - `ui-styles.ts`: COLOR 상수 16개 추가 — `white`, `groupHeader`, `border`/`borderDark`/`borderLight`/`borderGrid`/`borderRow`, `zebra`/`surfaceLight`/`hoverBg`/`surface`/`highlight`/`inactiveBg`/`toggleOff`; `secondary` 제거; `CELL_BORDER`·cellStyle·disabled option 하드코딩 교체
  - `secondary`→`tertiary` 일괄 교체: 12개 파일 33곳 (sed 일괄 처리)
  - 하드코딩 색상 교체: 28개 파일 ~190곳 — 텍스트(`#aaa`→disabled, `#999`→disabled, `#111`→neutral, `#222`→neutral, `#666`→tertiary, `#1a1a1a`→neutral, `#333`→neutral, `#616161`→tertiary, `#1a237e`→groupHeader, `#fff`→white), 보더(`#ccc`→border, `#ddd`→borderDark, `#eee`→borderLight, `#d0d0d0`→borderGrid, `#e5e7eb`→borderRow, `#f5f5f5`→neutralBg, `#f0f0f0`→hoverBg, `#e0e0e0`→inactiveBg, `#d0d5dd`→borderGrid), 배경(`#f9f9f9`→zebra, `#fafafa`→surfaceLight, `#f8f9fa`/`#f8f8f8`/`#f7f8fa`→surface, `#fff9c4`→highlight, `#6c757d`→toggleOff, `#dee2e6`→inactiveBg)
  - cssText/template literal 문자열 내 `#xxx`도 `${COLOR.xxx}` 형식으로 교체 (sidebar, shell, header, router, canvas-sector-donut, canvas-profit-chart, profit-overview, profit-detail, profit-shared, sector-ranking-list, settings-common)
  - 제외 (도메인 특화): 차트 팔레트 20색, 점수 색상 3종(#e67e22/#2c3e50/#7f8c8d), 브로커 브랜드(#FF8C00/#DC143C), 슬라이더(#0d6efd/#e9ecef), 다크테마(DARK_FIELD_STYLE #1e1e1e/#555/#ddd), 부트스트랩 칩(#f3e5f5/#6a1b9a), success hover(#157347)
  - 아키텍처: 원칙 10 (SSOT — 색상 단일 소스 진리), 원칙 22 (파생 데이터 모델 — 보더/배경 계층화)
  - 검증: tsc 타입체크 0 에러, vite build 통과 (57 모듈 1.97s), vitest 109/109 통과, grep 재검색 — `COLOR.secondary` 0건, 비제외 하드코딩 색상 0건
  - 커밋: (이번 커밋)
- **2026-07-10: 수익상세/매도설정 페이지 데이터 정합성 근본 수정 + 매수일자 최초 매수일 표시 + 매수일자 색상 변경**
  - 문제 1: 수익상세 페이지(매수 8건/매도 6건)와 매도설정 페이지(보유종목 5종목) 간 데이터 불일치
  - 원인 1: `trade_history._buy_history/_sell_history`(수익상세 원천)와 `dry_run._test_positions`(보유종목 원천)가 이중 상태로 관리, `record_buy/record_sell`(동기)과 `_apply_buy/_apply_sell`(비동기 0.1초 후)이 원자적으로 결합되지 않아 diverge
  - 수정 1 (SSOT 일원화): `dry_run._test_positions`를 파생 캐시로 격하 — `_positions_dirty` 플래그 추가, `_load_positions()` → `_refresh_positions_if_dirty()`로 변경 (dirty 시 `build_positions_from_trades()`로 재구축, cur_price/stk_nm 등 비파생 필드 보존)
  - 수정 1: `_apply_buy/_apply_sell`에서 `_test_positions` 직접 수정 제거, `settlement_engine`만 갱신
  - 수정 1: `trade_history._insert_trade()`/`clear_test_history()`/`_reset_global_state()`에서 `dry_run._positions_dirty = True` 설정 (캐시 무효화)
  - 수정 1: `engine_lifecycle.py` `_load_positions()` → `_refresh_positions_if_dirty()` 교체
  - 문제 2: 보유종목 매수일자가 모두 오늘로 표시됨 (최초 매수일이 아님)
  - 원인 2: `build_positions_from_trades()`가 `_buy_history`(DESC 정렬)를 순회하며 첫 발견 매수의 date를 buy_date로 설정 — DESC이므로 첫 발견 = 최근 매수일. 이후 더 오래된 매수를 만나도 buy_date 갱신 안 함. `get_earliest_buy_date()`도 같은 버그
  - 수정 2: `build_positions_from_trades()` `if pos:` 분기에 `buy_date` 최초 매수일 추적 로직 추가 (문자열 비교 `rec_date < pos["buy_date"]`)
  - 수정 2: `get_earliest_buy_date()`를 전체 순회하며 최소 date 추적하도록 수정
  - 문제 3: 매수일자 컬럼 색상 — 당일 빨강(강조), 과거 회색
  - 수정 3: `sell-position.ts` 매수일자 컬럼 색상 변경 — 당일=`COLOR.neutral`(#333, 기본 텍스트), 과거=`COLOR.disabled`(#9e9e9e, 연한 회색)
  - 데이터 검증: 5종목(161390/000990/066570/000270/035420) 모두 2026-07-10 매수, 매도 기록 없음 → buy_date=오늘이 정확함. 전체 44건 매수/39건 매도, 잔여 5종목 정합
  - 검증: 런타임 시작 정상 (에러 없음), 백엔드 테스트 1025 passed, 프론트엔드 build 성공
  - 커밋: (이번 커밋)
- **2026-07-10: 수익현황 페이지 빈 데이터 차트/도넛 stale state 근본 수정 — 더미 데이터 생성 로직 완전 제거 + currentSegments 초기화**
  - 문제: 날짜 범위에 매도 데이터가 없어도 일별 수익률 차트에 더미 막대/라인이 표시되고, 업종별 수익 분포 도넛 우측 범례에 이전 데이터가 잔류
  - 원인: `canvas-profit-chart.ts`의 `generateDummyData()` 폴백 (원칙 20 위반), `canvas-sector-donut.ts`의 `render()`에서 `currentSegments` 미초기화 (원칙 22 위반)
  - `canvas-profit-chart.ts`: `generateDummyData()` 29줄 삭제, `refreshInternal()` 더미 분기 제거 + `hasVisibleBar` 판정을 `pnl !== null && pnl !== 0`에서 `pnl === null`로 수정 (손익 0원 정상 매도 폴백 버그 제거), overlay 텍스트 "(샘플 데이터)" 제거
  - `canvas-sector-donut.ts`: `render()`의 `!hasData` 분기와 `totalAbs === 0` 분기에 `currentSegments = []`, `segmentRects = []` 초기화 추가
  - `profit-overview.ts`: `initState`/`filteredSellHistory` 할당을 `createSectorDonut` 전으로 이동, 도넛 초기 data를 `filteredSellHistory`로 변경 (초기 전체 데이터 렌더링 → 덮어쓰기 깜빡임 방지)
  - 아키텍처: 원칙 10 (SSOT — 더미 제2 소스 제거), 원칙 20 (폴백 금지), 원칙 21 (사용자 투명성 — "샘플 데이터" 표시 제거), 원칙 22 (데이터 정합성 — 파이프라인 단계 간 currentSegments 일관성)
  - 검증: tsc 타입체크 통과, vite build 통과 (57 모듈), vitest 109/109 통과
  - 커밋: (이번 커밋)
- **2026-07-10: 보유종목 테이블 매수일자 컬럼 추가 — trade_history SSOT → WS → hotStore → UI 전체 파이프라인**
  - 목적: 매도설정 페이지 보유종목 테이블에 매수일자 표시 — 당일 매수 빨강, 과거 회색 조건부 스타일링
  - 백엔드: `trade_history.py` `build_positions_from_trades()` buy_date 파생 + `get_earliest_buy_date()` 헬퍼 추가 (실전모드 REST 보완용)
  - 백엔드: `dry_run.py` `_apply_buy()` 신규 position에 buy_date 추가, `engine_account.py` `_broadcast_account()` 실전모드 buy_date 주입
  - 백엔드: `engine_account_notify.py` `_POSITION_CMP_KEYS`, `_MIN_POSITION_KEYS`에 buy_date 추가
  - 프론트엔드: `types/index.ts` Position에 `buy_date?: string` 추가, `sell-position.ts` 매수일자 컬럼 추가 + 컬럼 순서 조정
  - 컬럼 순서: 순번→종목코드→종목명→현재가→매수가→매수금액→평가손익→수익률→수량→매수일자
  - 아키텍처: 원칙 10 (SSOT — trade_history date 필드에서 파생), 원칙 18 (테스트모드 동등성), 원칙 20 (폴백 금지), 원칙 22 (파생 데이터 모델)
  - 검증: py_compile 4파일 성공, tsc --noEmit 성공, vite build 성공, 런타임 기동 정상 (966ms, 에러 없음), test_dry_run_fill_event 29 passed
  - 커밋: `77d1d3c` push 완료
- **2026-07-10: 매수후보 페이지 검색 입력란 위치 재조정 — 좌측 상단, 주문가능금액 배지 하단**
  - 변경 파일: `frontend/src/pages/buy-target.ts` 1개
  - 검증: `npm run typecheck` 통과, `npm run test` 109 passed
  - 커밋: `d4b3d40` push 완료

## 현재 상태
- **백엔드**: 유령 매도 기록(id=144) 삭제 완료, 유령 포지션 재발 방지 예방 조치 구현 완료 (근본 원인은 미해결), boost_order_ratio_pct 422 오류 수정 완료, Settlement Engine 리팩토링 완료, RiskManager 리팩토링 Phase 1 완료, 보유종목 buy_date 파생·브로드캐스트 구현 완료
- **프론트엔드**: 더미 데이터 삭제 완료, 차트 툴팁 잘림 수정 완료, 매수후보 페이지 주문가능금액 배지·검색 입력란 추가 완료, 보유종목 테이블 매수일자 컬럼 추가 완료, 수익현황 페이지 빈 데이터 차트/도넛 stale state 근본 수정 완료, 프론트엔드 색상 체계 통일 완료 (하드코딩 ~190곳 COLOR 상수화 + secondary→tertiary 통합), 검색 입력란 공통 컴포넌트 통일 완료 (5페이지 7개 인스턴스 + label/compact 옵션 + 포커스 언더라인 + placeholder 색상), `npm run build` 통과
- **Git**: 커밋 `a2ea0cf` push 완료 (검색 입력란 통일 작업은 미커밋)

## 다음 단계
- **1순위: 유령 포지션 근본 원인 심층 조사 (별도 세션)**:
  - 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
  - WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
  - `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조
- **2순위: 브라우저 실제 화면 확인** — 장중에 매수후보 테이블에서 SK하이닉스(000660) 하이라이트 깜빡임 없는지 확인 + 매수/매도호가잔량비율 슬라이더 422 미발생 확인
- **3순위: exchange_calendars 교체 검토** — pandas(70MB)+numpy(33MB) 등 간접 의존성 약 112MB 절감 가능

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결, 재발 방지 조치 + 유령 매도 기록 삭제 완료**
  - 상세 조사 기록: `docs/ghost_position_investigation.md`
  - 재발 방지 조치 (2026-07-10 구현): `test_positions` 테이블 제거, `trades` 기반 SSOT 전환, `execute_sell()` 런타임 가드
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성
- **체결지연 50ms 초과 WARNING 7건** (2026-07-08 13:26~ 런타임 기동 중 발생)
  - `trading_2026-07-08.log:9597~9609` — 50~143ms 지연 7건 (200ms 초과 없음)
  - 조사 필요: `_handle_real_01_tick` await 체인 프로파일링, 지연 발생 위치 식별

## 테스트 실행 원칙 (필수 준수)

### 1. 실행 명령어 (통일)
```
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- `timeout_method = signal` 필수 — `thread` 방식은 asyncio C-level wait를 interrupt하지 못해 hang 시 프로세스가 영구 블록됨
- `pytest.ini`에 전역 설정되어 있으므로 CLI에서 생략 가능

### 2. 자동 hang 체크 원칙 (에이전트 필수 강제 — 수동 개입 금지)
- **a. 10초마다 진행 상태 자동 체크**: 테스트 실행 후 `command_status`로 주기적 확인
- **b. 10초 이상 로그/출력 멈추면 즉시 hang 간주**: 대기 없이 강제 종료 결정
- **c. hang 감지 시 즉시 프로세스 강제 종료**: SIGTERM/Ctrl+C로 프로세스 종료
- **d. hang 원인 자동 분석**: 종료 후 로그/코드 분석하여 원인 보고
- **e. 위 모든 과정은 에이전트가 자동 수행**: 사용자 확인 대기 금지, 수동 개입 금지
- 정상 완료: "✅ N passed in N.Ns"
- hang 감지: "❌ 10초 이상 응답 없음 — 강제 종료 및 원인 분석 시작"

### 3. 테스트 hang 방지 코딩 원칙 (근본 원인별)

#### 원인 A: 실제 asyncio 동기화 프리미티브 (Lock/Event/wait_for)
- **금지**: 테스트에서 실제 `asyncio.Lock()`, `asyncio.Event()`, `asyncio.wait_for()` 사용
- **해결**: `MagicMock` + `AsyncMock`으로 교체
  - Lock: `lock.__aenter__ = AsyncMock(return_value=lock)`, `lock.__aexit__ = AsyncMock(return_value=None)`
  - Event: `ev.wait = AsyncMock()`, `ev.clear/set = MagicMock()`
  - wait_for: 즉시 반환 또는 즉시 `TimeoutError` 발생시키는 async 함수로 patch

#### 원인 B: asyncio.create_task 백그라운드 태스크
- **금지**: 테스트에서 `asyncio.create_task()`가 실제 실행되는 것을 허용
- **해결**: `patch("module.asyncio.create_task")`로 mock 교체, `add_done_callback` 속성 포함

#### 원인 C: NotificationWorker / 백그라운드 워커 싱글톤
- **금지**: `_fire_and_forget_telegram` 등이 실제 `NotificationWorker.get_instance()`를 호출하여 백그라운드 태스크 생성
- **해결**: autouse fixture에서 `patch("module._fire_and_forget_telegram")` 처리

#### 원인 D: 실제 DB I/O (aiosqlite)
- **금지**: 테스트에서 `get_db_connection()`이 실제 DB에 연결
- **해결**: autouse fixture에서 `patch("backend.app.db.database.get_db_connection")` 처리

#### 원인 E: pytest-asyncio 이벤트 루프 간섭
- **금지**: conftest.py에 async fixture 사용 (이벤트 루프 정리 중 hang 유발)
- **금지**: conftest.py에서 `asyncio.sleep` 전역 patch (pytest-asyncio 내부 동작 간섭)
- **해결**: conftest.py는 동기 fixture만 사용, 캐시 리셋 등 최소 기능만 유지

### 4. run_command 사용 시
- `Blocking: false` + `WaitMsBeforeAsync: 20000` — hang 감지 시 명령 취소 가능
- 또는 subprocess + `proc.wait(timeout=N)` + `proc.kill()` 패턴 사용

## 개선 필요 영역 — 테스트 커버리지

### 현재 커버리지: 14% (13,833줄 중 1,981줄 커버)

### 고커버리지 영역 (유지)
- `sector_score.py` 100%, `models.py` 100%, `settings_defaults.py` 100%
- `sector_calculator.py` 97%, `sector_filter.py` 96%
- `test_dry_run_fill_event.py` 95%, `test_sector_calculator.py` 100%
- `database.py` 88%, `engine_state.py` 82%, `trade_mode.py` 79%
- `settings_file.py` 70%, `engine_utils.py` 68%

### 테스트 부족 영역 (우선순위별)

#### Priority 1 — 매매 핵심 로직 (완료)
- `test_buy_filter.py` ✅, `test_circuit_breaker.py` ✅, `test_settlement_engine.py` ✅
- `test_risk_manager.py` ✅, `test_buy_order_executor.py` ✅, `test_trading.py` ✅ (hang 해결 — 커밋 `a4fa031`)

#### Priority 2 — 엔진/WS 계층 (완료)
- `test_engine_ws.py` ✅, `test_engine_ws_dispatch.py` ✅, `test_engine_ws_parsing.py` ✅
- `test_engine_ws_reg.py` ✅, `test_engine_account.py` ✅, `test_engine_account_notify.py` ✅
- `test_engine_account_rest.py` ✅, `test_engine_symbol_utils.py` ✅

#### Priority 3 — 파이프라인/스케줄러 (완료)
- `market_close_pipeline.py` (712줄, 86%) ✅
- `pipeline_compute.py` (655줄, 92%) ✅ — 배치 드레인 + 코얼레싱 + 계좌 디바운스 추가 (2026-07-06)
- `pipeline_gateway.py` (86줄, 87%) ✅
- `daily_time_scheduler.py` (601줄, 90%) ✅
- `data_manager.py` (136줄, 96%) ✅

#### Priority 4 — 브로커 커넥터 (0% 커버, 장기)
- `kiwoom_connector.py`, `kiwoom_rest.py`, `kiwoom_order.py`, `kiwoom_providers.py`, `kiwoom_stock_rest.py`
- `ls_connector.py`, `ls_rest.py`, `ls_providers.py`
- `connector_manager.py`

#### Priority 5 — Web 라우트 (0% 커버, 장기)
- `app.py`, `ws.py`, `ws_manager.py`, `settings.py`, `stock_classification.py`, `status.py`

#### Priority 6 — 유틸/기타 (0% 커버, 장기)
- `telegram.py`, `telegram_bot.py`, `trade_history.py` (회귀 테스트 2건 추가), `dry_run.py`
- `journal.py`, `logger.py`, `encryption.py`, `sector_mapping.py`
