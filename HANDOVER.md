# HANDOVER — SectorFlow

## 추후 논의 필요 (미결정)
- 없음

## 직전 완료 작업
- **2026-07-12: 백엔드 로그 한글화 3차 작업 — 5단계 (services B 내부 디버그 로그) 완료**
  - **수정 파일**: `services/engine_ws_reg.py`, `engine_ws.py`, `engine_sector_confirm.py`, `data_manager.py` (4개 파일)
  - **내용**: 약 33건 로그 메시지 + 주석/docstring 한글화 — 브로커→증권사(3건), BrokerConnector→증권사 커넥터(3건), BrokerRouter→증권사 라우터(1건), 태스크→작업(2건), 타임아웃→시간 초과(3건), trnm=→메시지유형=(1건), WS→실시간 통신(3건), 이미구독→이미 구독(1건), 브로드캐스트→전송(1건), 스킵→생략(3건), 스윕→일괄 정리(2건), best-effort→최선 노력(1건), pending→대기(1건), no-op→작업 없음(1건), delta→증분(4건), ready set→준비 대기실(1건), 클리어→비우기(2건), 계좌등록→계좌 등록(1건), 계좌설정→계좌 설정(1건), Grp 10→그룹 10(1건), base_url→기본 주소(2건), broker 기반→증권사 기반(1건), kt00018→계좌평가잔고내역(kt00018)(1건), kt00001→예수금 상세현황(kt00001)(1건), 예수금상세현황→예수금 상세현황(1건), 예외→오류(2건), 메인계좌정보→메인 계좌정보(1건), 실패함→실패(1건). WebSocket(프로토콜 고유명사), REG/UNREG/REMOVE(프로토콜 메시지 타입), dirty(코드 변수명)는 유지
  - **검증**: py_compile 4개 파일 통과, 잔존 영어 grep 0건 (브로커/BrokerConnector/BrokerRouter/WS /타임아웃/best-effort/no-op/trnm=/스킵/이미구독/브로드캐스트/스윕/pending에/delta/ready set/클리어/계좌등록/계좌설정/Grp 10/base_url/예외/kt00018 /kt00001 /예수금상세현황/메인계좌정보/실패함 전부 0건 — 코드 내 프로토콜 필드값 trnm="REG"/trnm="REMOVE" 및 속성 접근 auth.rest_api.base_url는 정상 유지), 런타임 기동 확인 (총 기동시간 193ms, 에러/Traceback 없음, "전종목 마스터 테이블 초기화 완료" 한국어 출력 확인), 잔존 프로세스 0개
- **2026-07-12: 백엔드 로그 한글화 3차 작업 — 4단계 (market_close_pipeline) 완료**
  - **수정 파일**: `services/market_close_pipeline.py` (1개 파일, 1370줄)
  - **내용**: 81건 logger 호출 + 약 40건 주석/docstring 한글화 — Step 1~7→1~7단계, stock_5d_array→5일봉 배열 테이블, master_stocks_table→전종목 마스터 테이블, 브로드캐스트→전송, 파싱→해석, 예외→오류, broker→증권사, WS 브로드캐스트→실시간 통신 전송, fire-and-forget→즉시 전송, Rate limiting→요청 간격 조절 등 (상세는 git history 참조)
  - **검증**: py_compile 1개 파일 통과, 잔존 영어 grep 0건, 런타임 기동 확인 (총 기동시간 320ms, 에러/Traceback 없음), 잔존 프로세스 0개

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체 (korean_lunar_calendar), boost_order_ratio_pct 422 수정, 보유종목 buy_date 파생, 유령 포지션 재발 방지 조치, 테스트모드 6개월 보관 정책(125거래일, 메모리+DB 동시 정리) — 모두 코드 확인 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 주문가능금액 배지, 매수일자 컬럼, stale state 수정, 색상 체계 통일 (COLOR 상수화), 검색 입력란 공통 컴포넌트, 가상 스크롤 플래시 억제, 일반설정 비거래일 배지 정렬 수정, 업종순위 요약 라벨 가독성 개선, 매수후보 배지 폰트 13px 확대, 매도설정 보유종목 요약 배지 추가, 업종순위 페이지 불투명도 3단계 통일, maxTargets fallback SSOT 통일(DEFAULT_SECTOR_MAX_TARGETS 상수), 수익현황/수익상세 기간 전환 버튼(당일/5일/당월/전체 4버튼 + 파랑 테두리), 일별수익률 안내 라벨 삭제, Enter 키 포커스 이동 개선(28개 입력창), Vite 프록시 크래시 방어, Vite http proxy error 로그 근본 해결(백엔드 ready 대기 후 브라우저 오픈), 수익현황 업종 섹션 연동(도넛 범례 클릭→스크롤+하이라이트), 전체보기/전체접기 토글 버튼, 차트 onMove undefined 크래시 근본 해결(render early return 시 barRects 동기화), 수익현황 기간 선택 상태 재기동 후 유지(localStorage quickLabel 영속화 + 초기 활성 버튼 복원), 수익상세 페이지 뷰 상태 재기동 후 유지(localStorage selectedView+drilldownActive+dateRange 영속화, 7곳 핸들러 persistViewState), 스핀버튼 초기 비활성 버그 근본 해결(store subscriber settings 변경 시에만 notify + createSpinButtons mousedown 포커스 유지 + registerEditing 데드 코드 제거), 증권사 변경 확인 팝업 추가(showConfirmDialog 재사용 + 변경 전/후 증권사명 + 4개 작업 요약 + 취소 시 라디오 복원 + BROKER_NAMES SSOT 상수), brokerSaving disabled 잔존 버그 수정(then 콜백 실행 순서 교정) — 모두 코드 확인 완료, `npm run build` 통과
- **Git**: 증권사 변경 시 토큰 폐기 로그 불일치 수정 (P15/P21) — 커밋 완료 (10dbafe), 런타임 검증 완료
- **AGENTS.md**: 4섹션 우선순위 구조 재구성 완료 (섹션1 개요 > 섹션2 아키텍처 원칙 > 섹션3 수행 규칙 > 섹션4 작업 프로세스). 신규 규칙 7건 추가 — 사용자 프로필 "코딩 1도 모름", 아키텍처 원칙 참조, 사용자 의사소통 규칙(기술 명령어 안내 금지·UI 기준 검증·API 직접 호출 안내 금지), 보고서 5항목 명시화, HANDOVER.md read-before-write 의무, 작업량 기반 사전 분할, 단계 완료 시 컨텍스트 점검. 기존 규칙 15개 누락 없음 대조 완료
- **테스트 커버리지**: Stage 1~9 + P6(telegram_bot.py) + 0% 모듈 7개 + 10%대 모듈 9개 + 30~50%대 Phase 1,2,3 전부 완료 — 백엔드 2763 passed, 0 failed
  - 0% 모듈 7개 해결: engine_ws_fill_followup(100%), engine_radar_ops(100%), notification_worker(85.19%), lock_manager(68.09%), engine_cache, broker_router, engine_loop
  - 10%대 모듈 9개 해결: engine_settings(100%), stock_tables(100%), stock_filter(99.44%), stock_classification_data(95.14%), settings_store(93.13%), sector_data_provider(92.94%), engine_bootstrap(49.62%), engine_snapshot(39.22%), engine_sector_confirm(33.45%)
  - 30~50%대 Phase 1,2,3 전부 완료 (실측): engine_snapshot(39.22%→97.39%, 12 테스트), engine_sector_confirm(33.45%→100%, 51 테스트), engine_bootstrap(49.62%→99.25%, 12 테스트)
  - 커버리지 실행 명령어: `python -m pytest backend/tests --cov=backend --cov-report=term-missing --cov-report=html --timeout=15 --timeout-method=signal`
- **settlement.py await 누락**: 수정 완료 (`settlement.py:16`)
- **루트 폴더 정리**: 완료된 1회성 계획서 3건 + 로컬 산출물 4건 제거 (2026-07-12). `docs/architecture_audit_plan.md`, `docs/ghost_position_investigation.md`, `docs/api_specs/` 유지

## 진행 중 작업

### 백엔드 로그 한글화 3차 작업 (내부 디버그 로그) — 5/8단계 완료

> **계획서**: `backend/docs/log_korean_migration_plan.md`의 "2차 작업 (내부 디버그 로그) — 향후 진행" 섹션
> **이력**: 1차 작업(2026-07-09) 약 30개 파일 1차 한글화. 2차 작업(사용자 노출 로그) 5단계 전부 완료. 3차 작업(내부 디버그 로그) 8단계 중 5단계 완료.

| 단계 | 내용 | 파일 수 | 상태 |
|------|------|---------|------|
| 1단계 | pipelines 내부 디버그 로그 | 2 | ☑ 완료 (2026-07-12) |
| 2단계 | db (stock_tables, db_writer, json_utils) | 3 | ☑ 완료 (2026-07-12) |
| 3단계 | services A (engine_cache, engine_snapshot, engine_config) | 3 | ☑ 완료 (2026-07-12) |
| 4단계 | market_close_pipeline (단독, 81건) | 1 | ☑ 완료 (2026-07-12) |
| 5단계 | services B (engine_ws_reg, engine_ws, engine_sector_confirm, data_manager) | 4 | ☑ 완료 (2026-07-12) |
| 6단계 | services C (sector_data_provider, ws_subscribe_control, engine_strategy_core, engine_ws_fill_followup, core_queues) | 5 | ☐ 미시작 |
| 7단계 | core A (stock_classification_data, sector_mapping, sector_stock_cache, settings_file, settings_store) | 5 | ☐ 미시작 |
| 8단계 | core B (trading_calendar, lock_manager, journal, memory_monitor) | 4 | ☐ 미시작 |

### 백엔드 로그 한글화 2차 작업 — 1~5단계 전부 완료

> **계획서**: `backend/docs/log_korean_migration_plan.md`
> **이력**: 1차 작업(2026-07-09) 약 30개 파일 1차 한글화. 2차 작업 1단계(Uvicorn 자체 로그) + 2단계(웹서버/실시간 통신) + 3단계(매매/계좌/정산) + 4단계(알림/서킷브레이커) + 5단계(증권사 연결/주문/잔고) 완료. 2차 작업 5단계 전부 완료.

| 단계 | 내용 | 파일 수 | 상태 |
|------|------|---------|------|
| 1단계 | Uvicorn 자체 로그 한국어화 | 1 | ☑ 완료 (2026-07-12) |
| 2단계 | 웹서버/실시간 통신 로그 | 7 | ☑ 완료 (2026-07-12) |
| 3단계 | 매매/계좌/정산 로그 | 12 | ☑ 완료 (2026-07-12) |
| 4단계 | 알림/서킷브레이커 로그 | 5 | ☑ 완료 (2026-07-12) |
| 5단계 | 증권사 연결/주문/잔고 로그 | 11 | ☑ 완료 (2026-07-12) |

**2차 작업(사용자 노출 로그) 전부 완료.**

### 아키텍처 전수 점검 — 7/30 세션 완료

| 세션 ID | 우선순위 | 내용 | 상태 |
|---------|----------|------|------|
| B-01 | P0 | 주문 실행 경로 | ☑ 완료 (8건 수정, 50 tests passed) |
| B-02 | P0 | 리스크 관리 및 서킷 브레이커 | ☑ 완료 (3건 수정, 2774 tests passed) |
| B-03 | P0 | Dry Run (테스트 모드 가상 주문) | ☑ 완료 (3건 수정, 2768 tests passed) |
| B-04 | P0 | 정산 엔진 및 거래 이력 | ☑ 완료 (4건 수정, 2763 tests passed) |
| B-05 | P0 | 자동매매 유효성 및 코어 큐 | ☑ 완료 (6건 수정, 378 tests passed) |
| F-01 | P0 | 통신 계층 및 상태 관리 | ☑ 완료 (10건 수정, V-02 해결, 112 tests passed) |
| B-06 | P1 | 엔진 루프 및 생명주기 | ☑ 완료 (4건 수정, 271 tests passed) |
| B-07~B-11 | P1 | WS/부트스트랩/섹터/계좌/파이프라인 | ☐ 미시작 |
| B-12~B-19 | P2 | DB/설정/Broker/증권사/Domain/스케줄러 | ☐ 미시작 |
| B-20~B-23 | P3 | 알림/유틸/Web API/테스트 | ☐ 미시작 |
| F-02~F-07 | P1~P3 | 진입점/핵심페이지/설정/수익/컴포넌트/타입 | ☐ 미시작 |

## 다음 단계

### 1순위: 백엔드 로그 한글화 3차 작업 (내부 디버그 로그) — 진행 중

3차 작업 8단계 중 5단계 완료. **다음 세션은 6단계(services C)부터 시작** — `services/sector_data_provider.py`, `ws_subscribe_control.py`, `engine_strategy_core.py`, `engine_ws_fill_followup.py`, `core_queues.py` 5개 파일. 진행 방법은 5단계와 동일 (파일별 logger 호출 + 주석/docstring 한글화 → py_compile → 잔존 영어 grep → 런타임 기동 검증).

- **1단계** ☑ 완료 (2026-07-12): `pipelines/pipeline_compute.py`, `pipeline_gateway.py` — 28건 로그 메시지 + 8건 주석/docstring 동기화
- **2단계** ☑ 완료 (2026-07-12): `db/stock_tables.py`, `db/db_writer.py`, `db/json_utils.py` — 12건 로그 메시지 한글화
- **3단계** ☑ 완료 (2026-07-12): `services/engine_cache.py`, `engine_snapshot.py`, `engine_config.py` — 15건 로그 메시지 한글화
- **4단계** ☑ 완료 (2026-07-12): `services/market_close_pipeline.py` — 81건 logger 호출 + 약 40건 주석/docstring 한글화
- **5단계** ☑ 완료 (2026-07-12): `services/engine_ws_reg.py`, `engine_ws.py`, `engine_sector_confirm.py`, `data_manager.py` — 약 33건 로그 메시지 + 주석/docstring 한글화
- **6단계** ☐ 미시작: `services/sector_data_provider.py`, `ws_subscribe_control.py`, `engine_strategy_core.py`, `engine_ws_fill_followup.py`, `core_queues.py`
- **7단계** ☐ 미시작: `core/stock_classification_data.py`, `sector_mapping.py`, `sector_stock_cache.py`, `settings_file.py`, `settings_store.py`
- **8단계** ☐ 미시작: `core/trading_calendar.py`, `lock_manager.py`, `journal.py`, `memory_monitor.py`

3차 작업 대상 파일 목록은 `backend/docs/log_korean_migration_plan.md`의 "2차 작업 (내부 디버그 로그) — 향후 진행" 섹션 참조.

### 2순위: 아키텍처 전수 점검 P1 세션 (B-07)

B-06 완료. P0 세션(6/6) + B-06 완료 — 총 7/30 세션. 로그 한글화 작업 완료 후 `docs/architecture_audit_plan.md`의 추천 세션 순서에 따라 P1 진행:

1. **B-07**: WS 시세 처리 (파싱/디스패치/등록) (`engine_ws_reg.py`, `engine_ws_dispatch.py`, `engine_ws.py`, `engine_ws_parsing.py`, `engine_ws_fill_followup.py`)

**보류 (B04-05)**: B-04에서 발견된 기동 시 정산 상태-거래 이력 대조(reconciliation) 부재 (P22) — B06-02 해결로 `_reconciliation_on_startup` 미구현 함수 제거됨. 실전투자 모드는 증권사 서버가 SSOT이므로 별도 대조 불필요 (사용자 결정). B04-05 상태를 "해결"로 변경.

각 세션 진행 시:
- `docs/architecture_audit_plan.md`의 해당 세션 체크리스트 사용
- 발견된 문제를 계획서 섹션 7 "발견된 문제 기록"에 등록
- 세션 완료 시 계획서 섹션 8 "점검 진행 현황 요약" 갱신
- 세션 종료 시 본 `HANDOVER.md` 진행 상태 갱신

### 3순위: 유령 포지션 005930 근본 원인 조사
- 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
- WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
- `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조

### 4순위: P1 세션 (B-08~B-11, F-02)
B-06, B-07 완료 후 진행.

### 5순위: P2 세션 (B-12~B-19, F-03~F-04)
P1 세션 완료 후 진행.

### 6순위: P3 세션 (B-20~B-23, F-05~F-07)
P2 세션 완료 후 진행.

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결**
  - 상세 조사 기록: `docs/ghost_position_investigation.md` ([A]~[I] 미조사 항목)
  - 재발 방지 조치 (2026-07-10, 코드 확인 완료):
    - `test_positions` 테이블 제거 — `stock_tables.py:141`, DB 저장 로직 전체 제거
    - `trades` 기반 SSOT 전환 — `dry_run.py:38-68`, `trade_history.py:549`
    - `execute_sell()` 런타임 가드 — `trading.py:418-436` (유령 포지션 차단 + Telegram 알림)
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 수동 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성

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
