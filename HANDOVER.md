# HANDOVER — SectorFlow

## 추후 논의 필요 (미결정)
- 없음

## 진행 중 작업 (다음 세션에서 이어서 진행)
- 없음

## 직전 완료 작업
- **2026-07-11: 수익상세 페이지 뷰 상태 재기동 후 유지 — localStorage 영속화**
  - 근본 원인: `profit-detail.ts`에 localStorage 저장/복원 로직 전무, `selectedView` + `drilldownActive` + `dateRangeInput`이 mount 시마다 하드코딩(`today` 고정)
  - 수정: `profit-detail.ts` — `PROFIT_DETAIL_VIEW_KEY` 상수 + `loadProfitDetailView()`/`saveProfitDetailView()`/`persistViewState()` 헬퍼 추가
  - 수정: mount 초기화 — `loadProfitDetailView()`로 복원, saved 있으면 selectedView/drilldownActive/dateRangeInput 복원, 없으면 기존 'today' 기본값
  - 수정: 7곳 상호작용 핸들러에 `persistViewState()` 추가 (Today/Month/Total 카드, 드릴다운 토글 ON/OFF, dateRangeInput onChange, 드릴다운 행 클릭)
  - 검증: `npm run typecheck` + `npm run build` 통과 (59 modules transformed) + `npm test` 112 passed
  - 수정 파일: `profit-detail.ts`

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체 (korean_lunar_calendar), boost_order_ratio_pct 422 수정, 보유종목 buy_date 파생, 유령 포지션 재발 방지 조치, 테스트모드 6개월 보관 정책(125거래일, 메모리+DB 동시 정리) — 모두 코드 확인 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 주문가능금액 배지, 매수일자 컬럼, stale state 수정, 색상 체계 통일 (COLOR 상수화), 검색 입력란 공통 컴포넌트, 가상 스크롤 플래시 억제, 일반설정 비거래일 배지 정렬 수정, 업종순위 요약 라벨 가독성 개선, 매수후보 배지 폰트 13px 확대, 매도설정 보유종목 요약 배지 추가, 업종순위 페이지 불투명도 3단계 통일, maxTargets fallback SSOT 통일(DEFAULT_SECTOR_MAX_TARGETS 상수), 수익현황/수익상세 기간 전환 버튼(당일/5일/당월/전체 4버튼 + 파랑 테두리), 일별수익률 안내 라벨 삭제, Enter 키 포커스 이동 개선(28개 입력창), Vite 프록시 크래시 방어, Vite http proxy error 로그 근본 해결(백엔드 ready 대기 후 브라우저 오픈), 수익현황 업종 섹션 연동(도넛 범례 클릭→스크롤+하이라이트), 전체보기/전체접기 토글 버튼, 차트 onMove undefined 크래시 근본 해결(render early return 시 barRects 동기화), 수익현황 기간 선택 상태 재기동 후 유지(localStorage quickLabel 영속화 + 초기 활성 버튼 복원), 수익상세 페이지 뷰 상태 재기동 후 유지(localStorage selectedView+drilldownActive+dateRange 영속화, 7곳 핸들러 persistViewState) — 모두 코드 확인 완료, `npm run build` 통과
- **Git**: 수익상세 페이지 뷰 상태 유지 — `main` 50750a9, `origin/main` push 완료
- **테스트 커버리지**: Stage 1~9 + P6(telegram_bot.py) + 0% 모듈 7개 + 10%대 모듈 9개 + 30~50%대 Phase 1,2,3 전부 완료 — 백엔드 2761 passed, 0 failed
  - 0% 모듈 7개 해결: engine_ws_fill_followup(100%), engine_radar_ops(100%), notification_worker(85.19%), lock_manager(68.09%), engine_cache, broker_router, engine_loop
  - 10%대 모듈 9개 해결: engine_settings(100%), stock_tables(100%), stock_filter(99.44%), stock_classification_data(95.14%), settings_store(93.13%), sector_data_provider(92.94%), engine_bootstrap(49.62%), engine_snapshot(39.22%), engine_sector_confirm(33.45%)
  - 30~50%대 Phase 1,2,3 전부 완료 (실측): engine_snapshot(39.22%→97.39%, 12 테스트), engine_sector_confirm(33.45%→91.20%, 19 테스트), engine_bootstrap(49.62%→99.25%, 12 테스트)
  - 커버리지 실행 명령어: `python -m pytest backend/tests --cov=backend --cov-report=term-missing --cov-report=html --timeout=15 --timeout-method=signal`
- **settlement.py await 누락**: 수정 완료 (`settlement.py:16`)

## 다음 단계
- **1순위: engine_sector_confirm 커버리지 추가 개선 (91.20% → 95%+ 목표)**
  - 현재 91.20%로 30~50%대 Phase 3 완료 기준 충족했으나, 남은 8.8% 분석 후 추가 테스트 작성 여부 검토
- **2순위: 유령 포지션 005930 근본 원인 조사 (후순위)**
  - 여러 차례 시도했으나 원인 식별이 어려워 후순위로 변경
  - 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
  - WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
  - `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조

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
