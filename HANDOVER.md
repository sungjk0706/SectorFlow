# HANDOVER — SectorFlow

## 현재 진행 상태 (최신 — 다음 세션은 여기서 이어서 진행)

### 작업: 장운영정보(market_phase) 단일 소스 통합 — 수정 7,5,1,2,3,4 완료, 수정 6,8 대기

**진행 단계**: 수정 7,5,1,2,3,4 완료. 다음 단계: 수정 6 (프론트엔드 상수 제거 + is_nxt_only 전송) 또는 수정 8 (선택, 타이머 통합).

**완료된 수정**:
- **수정 7 완료** (커밋 `786e371`): `is_ws_subscribe_window()` docstring 기본값 불일치 수정.
- **수정 5 완료** (커밋 `2636bc1`): `build_sector_stocks_payload()`의 `krx_after_hours` dead data 제거.
- **수정 1,2,3,4 완료** (이번 세션): 4개 시간 함수 → `state.market_phase` 기반 전환.
  - 수정 1: `is_nxt_premarket_window()` → `state.market_phase["nxt"] == "프리마켓"`, 빈 문자열 감지 포함.
  - 수정 2: `is_nxt_aftermarket_window()` → `state.market_phase["nxt"] in ("애프터마켓", "애프터마켓 지속")`, 거래일 체크 누락 자동 해결.
  - 수정 3: `is_krx_after_hours()` → `state.market_phase["krx"] in ("체결 정산", "장후 시간외", "시간외 단일가", "장 종료")`, `now` 파라미터 제거 (P24).
  - 수정 4: `get_nxt_trde_tp()` docstring 갱신 (market_phase 기반 명시), 로직은 헬퍼 호출 유지 (P16).
  - 테스트 3개 클래스 재작성 (TestIsNxtPremarketWindow 5건, TestIsNxtAftermarketWindow 5건, TestIsKrxAfterHours 8건) — `_kst_now`/`is_trading_day` patch → `state.market_phase` mock 패턴. TestGetNxtTrdeTp 4건은 헬퍼 mock 방식 유지.
  - 검증: ruff + py_compile 통과, pytest 178 passed (test_daily_time_scheduler 128 + test_buy_order_executor + test_kiwoom_order 50), 런타임 기동 `-W error::RuntimeWarning` 94ms 에러/Traceback/RuntimeWarning 없음, 잔존 프로세스 0건.

**남은 수정안 (승인 대기)**:
- **수정 6**: 프론트엔드 `KRX_INACTIVE_PHASES`/`NXT_ACTIVE_PHASES` 제거 + 백엔드 `market-phase` 이벤트에 `is_nxt_only: boolean` 추가 (`sector-stock.ts:127-154`, `uiStore.ts`, `types/index.ts`, `binding.ts`, `engine_account_notify.py`)
- **수정 8 (선택)**: 08:00/09:00/15:30 재계산 타이머 → `_broadcast_market_phase()` 내 페이즈 변경 감지 시 자동 트리거 통합 (`daily_time_scheduler.py:741-766`). 복잡도 증가 가능성 있어 신중 평가 필요.

**다음 단계 제안 (세션당 1단계, 규칙 0-1 준수)**:
1. 수정 6 (프론트엔드 상수 제거 + is_nxt_only 전송) — 백엔드-프론트엔드 동시 수정
2. 수정 8 (선택, 타이머 통합) — 별도 검증 필요

**남은 수정 파일 목록**:
- 백엔드: `engine_account_notify.py`
- 프론트엔드: `sector-stock.ts`, `uiStore.ts`, `types/index.ts`, `binding.ts`

**주요 리스크**:
- JIF 누락 시 `market_phase` 부정확 (시계 타이머 백업으로 최대 1초 지연)
- 프론트엔드-백엔드 `is_nxt_only` 동기화 (수정 6)

**추가 검토 결론: `ws_subscribe_start/end` 자동화 대체 권장하지 않음**:
- 거래소 장시간과 사용자가 원하는 데이터 수신 시간은 다를 수 있음 (P21 위반)
- 테스트모드 유연성 제약 (P18 위반)
- 현재 3계층 구조(ws_subscribe_on 토글 + 시간 설정 + market_phase 타이머)가 합리적
- 다만 기본값 09:00~15:00을 NXT 거래시간 고려해 08:50~15:30 조정은 별도 세션에서 검토 가능

**다음 세션 지시어 예시**:
- "수정 6 진행해" → 프론트엔드 상수 제거 + is_nxt_only 전송
- "수정 8 진행해" → 타이머 통합 (선택)

---

## 직전 완료 작업
- **2026-07-14: 시간 함수 4개 market_phase 기반 전환 — 수정 1,2,3,4 (P10/P16/P20/P22/P23/P24)**
  - **현상**: `is_nxt_premarket_window()`, `is_nxt_aftermarket_window()`, `is_krx_after_hours()`, `get_nxt_trde_tp()` 4개 함수가 `state.market_phase`를 사용하지 않고 독립적으로 시간 계산 + 거래일 판별을 수행하여 SSOT(P10) 위반. 특히 `is_nxt_aftermarket_window()`는 거래일 체크 누락 버그 존재.
  - **근본 원인**: `calc_timebased_market_phase()`가 이미 거래일 판별 + 시간 구간 산정하여 `state.market_phase`에 저장하므로, 4개 함수가 이를 재사용해야 SSOT 준수. `daily_time_scheduler.py:46-60, 63-70, 192-205, 208-228`.
  - **수정 파일**: 백엔드 1개 파일 + 테스트 1개 파일 — `daily_time_scheduler.py`, `test_daily_time_scheduler.py`
  - **변경 내용**: (1) 수정 1 — `is_nxt_premarket_window()` → `state.market_phase["nxt"] == "프리마켓"`, 빈 문자열 감지 시 `logger.error` + `return False`. (2) 수정 2 — `is_nxt_aftermarket_window()` → `state.market_phase["nxt"] in ("애프터마켓", "애프터마켓 지속")`, 거래일 체크 누락 자동 해결. (3) 수정 3 — `is_krx_after_hours()` → `state.market_phase["krx"] in ("체결 정산", "장후 시간외", "시간외 단일가", "장 종료")`, `now` 파라미터 제거 (P24). (4) 수정 4 — `get_nxt_trde_tp()` docstring 갱신 (market_phase 기반 명시), 로직은 헬퍼 호출 유지 (P16). (5) 테스트 3개 클래스 재작성 — `_kst_now`/`is_trading_day` patch → `state.market_phase` mock 패턴. TestGetNxtTrdeTp 4건은 헬퍼 mock 방식 유지.
  - **영향 범위**: 백엔드 1개 파일 + 테스트 1개 파일 (+131/-90). 호출처 영향 없음 (`buy_order_executor.py:115`, `kiwoom_order.py:61` 인자 없이 호출). `test_buy_order_executor.py`/`test_kiwoom_order.py` — 함수를 `return_value`로 patch하므로 영향 없음.
  - **검증**: ruff All checks passed. py_compile OK. pytest 178 passed (test_daily_time_scheduler 128 + test_buy_order_executor + test_kiwoom_order 50). 런타임 기동 `-W error::RuntimeWarning` 94ms, `장 상태 초기화: KRX=정규장, NXT=메인마켓` 확인, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: (이번 세션에서 커밋 예정)

- **2026-07-14: 단계 완료 시 작업 여력 보고 규칙 추가 — AGENTS.md Context Mgmt 10번 + 스킬 5개 참조 링크 (P10/P23)**
- **2026-07-14: 단계 완료 시 작업 여력 보고 규칙 추가 — AGENTS.md Context Mgmt 10번 + 스킬 5개 참조 링크 (P10/P23)**
  - **현상**: AGENTS.md와 5개 스킬 파일에 "단계 완료 시 작업 여력 보고 + 커밋/핸드오버 승인" 규칙이 없어, 에이전트가 매 단계 완료 시 사용자에게 작업 여력을 보고하고 승인받는 절차가 명시되어 있지 않았음.
  - **근본 원인**: `AGENTS.md` 섹션4 Context Management Rules에 "세션 종료 시 보고"(규칙 5)는 있었으나 "매 단계 완료 시 보고" 규칙이 없었음. 스킬 파일 5개에도 동일 규칙 누락.
  - **수정 파일**: 문서 6개 파일 — `AGENTS.md`, `.devin/skills/{problem-solve,backend-fix,frontend-fix,safe-trade,db-backup}/SKILL.md`
  - **변경 내용**: (1) `AGENTS.md:205-210` — Context Management Rules 신규 10번 "단계 완료 시 작업 여력 보고 (강제)" 추가. 일반 용어("작업 여력") 사용, 보고 예시 2종(충분/적음), 규칙 5(세션 종료 시)와 시점 구분 명시. (2) `AGENTS.md:190` — 기존 2번 끝에 "점검 결과는 규칙 10에 따라 사용자에게 보고" 연계 링크 추가. (3) 스킬 5개 — 각 파일의 보고 섹션에 "AGENTS.md 섹션4 Context Management Rules 10 준수" 참조 링크 1줄씩 추가 (P10 SSOT — 본문은 AGENTS.md, 스킬에는 참조만).
  - **영향 범위**: 6개 파일 (+16/-1). 코드 동작 영향 없음 (문서/규칙만 수정). 앞으로 모든 단계 완료 시 에이전트가 작업 여력을 보고하고 커밋/핸드오버 갱신 승인을 받도록 강제.
  - **검증**: grep "Context Management Rules 10" — 5개 스킬 파일에 1건씩 참조 확인. git diff --stat — 6개 파일 +16/-1. 잔존 프로세스: `main.py` PID 6199 1건 (이번 세션에서 띄우지 않은 기존 프로세스, 임의 종료하지 않음).
  - **커밋**: `bf8a06a`

- **2026-07-14: build_sector_stocks_payload krx_after_hours dead data 제거 — 필드 + import + 테스트 정리 (P16/P10)**
  - **현상**: `build_sector_stocks_payload()`가 `sector-stocks-refresh` 이벤트 페이로드에 `krx_after_hours` 필드를 포함하여 전송했으나, 프론트엔드 전체에서 참조 코드 없어 dead data로 전송됨 (P16 위반).
  - **근본 원인**: `engine_snapshot.py:97,109` — `is_krx_after_hours`를 import하여 반환값에 `krx_after_hours` 필드로 포함. 프론트엔드 `frontend/` 디렉토리 전체 검색 결과 참조 0건. `ws.py:94-95`에서 페이로드를 그대로 WS 전송하므로 불필요 데이터 매 전송마다 포함.
  - **수정 파일**: 백엔드 1개 파일 + 테스트 1개 파일 — `engine_snapshot.py`, `test_engine_snapshot.py`
  - **변경 내용**: (1) `engine_snapshot.py:97` — `is_krx_after_hours` import 제거. (2) `engine_snapshot.py:109` — 반환값 `{"_v": 1, "stocks": filtered, "krx_after_hours": is_krx_after_hours()}` → `{"_v": 1, "stocks": filtered}`. (3) `test_engine_snapshot.py:305,309,321,326` — `is_krx_after_hours` patch 2건 + assertion 2건 제거 + docstring 라인 번호 갱신 (L93-109 → L93-108). (4) `is_krx_after_hours` 함수 자체는 `daily_time_scheduler.py`에 유지 (수정 3 대상, `buy_order_executor.py` 사용 중).
  - **영향 범위**: 백엔드 1개 파일 + 테스트 1개 파일 (+3/-8). 프론트엔드 영향 없음 (참조 코드 없었음). WS 전송 `sector-stocks-refresh` 페이로드에서 `krx_after_hours` 필드 제거, UI 동작 영향 없음.
  - **검증**: ruff `test_engine_snapshot.py` All checks passed. `engine_snapshot.py` 기존 실패 1건 (`engine_state` unused import, 수정 전 동일 실패 확인 — 규칙 4-1). pytest `test_engine_snapshot.py` 19 passed in 1.03s. 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 171ms 기동, 에러/Traceback/RuntimeWarning 없음. 잔존 프로세스 0건 (규칙 5-1 준수). `krx_after_hours` 잔존 — `engine_snapshot.py`/`test_engine_snapshot.py` 0건 확인.
  - **커밋**: `2636bc1`

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책, JIF 경계 이벤트 즉시 갱신 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, DataTable 컬럼 너비 안정화, applyIndexRefresh dead code 제거 + applyIndexData market_phase 갱신 — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 pytest 56 passed (test_engine_ws_dispatch.py). 커버리지 Phase 1~3 완료
- **규칙/문서 정리**: AGENTS.md 4섹션 구조, 아키텍처 원칙 24개, .devin/workflows 제거 + skills 통합 — 완료 (2026-07-13)

## 진행 중 작업

### 보유종목/수익현황 페이지 평가손익·수익률 실시간 불일치 해결 — 완료
- **상태**: 프론트엔드 3개 파일 수정 완료 (`8dd84a8`). 빌드 + 테스트 통과. 사용자 UI 확인 대기.
- **내용**: `computeHoldingsSummary` 공통 함수로 두 페이지(보유종목 요약 배지 + 수익현황 계좌현황)가 개별 종목 행과 동일한 데이터 소스(positions + sectorStocks)·공식으로 평가손익/수익률 계산. `real-data-tick` 이벤트에 반응하여 실시간 갱신.
- **대기**: 사용자 브라우저 UI 확인 — (1) 보유종목 페이지 개별 합산=요약 일치, (2) 수익현황 계좌현황=보유종목 요약 일치, (3) 실시간 가격 변동 시 두 페이지 갱신.

### 업종 점수 순위별 차등 점수제 전환 — 백엔드+프론트엔드 완료
- **상태**: 백엔드 전환(`b106a71`) + 프론트엔드 전환(`17b9300`) 완료. 사용자 UI 확인 완료. 본 전환 작업 완료.
- **배경**: 기존 3단계 누적 가산점(0~300, `rank_to_score`)은 인접 순위 간 격차가 1.67%로 미세하여 순위 구분이 애매했음. 사용자가 각 조건의 중요도를 조절할 수 없었음.
- **전환 내용**: `rank_to_score`(0~100) → `rank_to_tiered_score`(0~사용자 설정 만점). 1위=만점, 2위=만점-1, ..., 0점까지 1점씩 차감. 사용자 설정 만점 3개(1차=10, 2차=7, 3차=5 기본값). 컷오프(min_rise_ratio) 2패스 구조 유지.
- **백엔드 완료** (`b106a71`): `sector_score.py`(`rank_to_score` 제거, `rank_to_tiered_score` 도입), `settings_defaults.py`/`engine_settings.py`(신규 키 3개), `sector_calculator.py`/`engine_sector_confirm.py`/`sector_data_provider.py`(만점값 전달), `engine_service.py`(`_SECTOR_UI_KEYS` 추가 → 설정 변경 시 자동 재계산), ARCHITECTURE.md(참조 갱신), 테스트 5개 파일. pytest 2737 passed + ruff 0건 + 런타임 기동 통과.
- **프론트엔드 완료** (`17b9300`): `types/index.ts`(신규 키 3개), `sector-settings.ts`(④ 섹션 만점 입력란 3개), `sector-ranking-list.ts`+`data-table.ts`(점수 정수 표시). `npm run build` 1.54s + `npm test` 101 passed 통과. 사용자 UI 확인 완료.

### 업종 점수 누적 가산점제 전환 (구 작업 — 완료)
- **계획서**: `docs/plan_sector_bonus_points.md` (895줄 — 2026-07-13 갱신)
- **상태**: Phase 1~3-B + 잔존 정리 + ARCHITECTURE.md 갱신 + 전수 검증 완료. 이후 순위별 차등 점수제로 재전환 완료 (상단 참조).
- **추가 개선점**: 3차 가산점 median 대안(편향 모니터링 후 전환 검토) — 순위별 차등 점수제 전환 후에는 median 대안 불필요 (순위 기반이므로 절대값 왜곡 영향 없음)

### 아키텍처 전수 점검 — B-09 완료, 20개 미시작 (일시 보류)
- **완료**: B-01~B-09, F-01 (P0 전체 + B-06~B-09)
- **미시작**: B-10~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-10 (엔진 계좌/서비스) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 중복 로직 정리 — 2순위 (백엔드 설정 로드/마스킹 단일화)
- **상태**: 중복 로직 전수 조사 완료 (백엔드 8건 + 프론트엔드 9건 = 17건 식별). 1순위(JSON 직렬화 통일) 완료 (커밋 `5afe492`).
- **2순위**: 백엔드 설정 로드/마스킹/복호화 로직 단일화 — `engine_settings.py`로 통합
  - `settings_store.py:220-251`(`build_masked_settings_dict`)와 `engine_config.py:117-133`(`_mask_sensitive_settings`) 마스킹 중복
  - `engine_settings.py:28-39`(`_dec`)와 `settings_file.py:141-145` 복호화 유사 패턴
  - 영향 파일: 3개 (`engine_settings.py`, `settings_store.py`, `engine_config.py`)
- **3순위 이후**: 프론트엔드 숫자/소수점 포맷팅 통일 → 프론트엔드 설정 페이지 행 스타일 공통화 → 프론트엔드 날짜 포맷팅 공통화 → 백엔드 종목코드 정규화 → 백엔드 REG 페이로드 → 백엔드 KST 타임존 → 기타 LOW 항목
- **참고**: 각 항목은 세션당 1단계 원칙(규칙 0-1)에 따라 한 세션에 하나씩 진행

### 아키텍처 전수 점검 (일시 보류)
- B-10: 엔진 계좌/서비스 (`engine_account.py`, `engine_account_rest.py`, `engine_account_notify.py`, `engine_service.py`)
- `docs/architecture_audit_plan.md` 체크리스트 사용, 발견 문제를 섹션 7에 등록
- 이후 B-11 (P1) → B-12~B-19 (P2) → B-20~B-23 (P3) → F-02~F-07 순서

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
