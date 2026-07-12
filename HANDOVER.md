# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-13: 업종순위설정 ⑥ 행 종목 합계 표시 + P20 폴백 제거 (sector_max_targets=0)**
  - **종목 합계 표시 (P21 투명성)**: ⑥ "매수대상 업종수" 행 아래 보조 줄 추가 — "상위 N개 업종 종목 합계: X종목". 파란 배경 + 파란 굵은 숫자 강조. ⑤ appliedWeightsLabel 패턴과 일관 (P23). `updateMaxTargetsStatus(scores, maxTargets)`가 rank>0 업종을 rank 순 정렬 후 상위 N개의 total 합산
  - **P20 폴백 제거 (프론트 3곳)**: `Number(...) || DEFAULT_SECTOR_MAX_TARGETS` → `typeof raw === 'number' ? raw : DEFAULT_SECTOR_MAX_TARGETS`. 0을 0으로 동작, undefined일 때만 기본값. `sector-ranking-list.ts` 2곳, `sector-stock.ts` 1곳
  - **P20 clamp 제거**: `onNumChange`의 `sector_max_targets < 1 → 1` 강제 제거
  - **P20 폴백 제거 (백엔드)**: `engine_settings.py:137` `int(... or 3)` → `_v if _v is not None else 3` 패턴 (인접 라인 141 기존 패턴과 일관, P23)
  - **수정 파일**: `sector-settings.ts`, `sector-ranking-list.ts`, `sector-stock.ts` (프론트 3개) + `engine_settings.py` (백엔드 1개)
  - 검증: 백엔드 단위 `build_engine_settings_dict` 0→0/{}→3/5→5 정상, `npm run typecheck` 통과, `npm run build` 1.84s 성공, 런타임 기동은 백엔드 이미 실행 중(PID 19679)으로 잠금 충돌 생략
  - **사용자 UI 확인 대기**: ⑥ 입력란 0 설정 → "상위 0개 업종 종목 합계: 0종목" 표시, 1/3/5 변경 시 N과 합계 즉시 갱신
  - **추가 발견 (승인 대기)**: `engine_settings.py` 인접 라인 138(`sector_min_rise_ratio_pct` or 60.0), 139(`sector_min_trade_amt` or 0.0) 동일 P20 패턴 — 0을 정상 값으로 쓰면 같은 위험, 일괄 정리 권장

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, 테이블 컬럼 너비 동적 조정 등 — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 pytest 통과. 커버리지 Phase 1~3 완료
- **업종 분류**: 69→55 재분류 + 업종명 정비 + 순위 기반 점수 전환 + 종목 이동 버그 3건 근본 해결 + "업종명없음" 잔적 제거 — 완료, 사용자 UI 확인 대기
- **규칙/문서 정리**: AGENTS.md 4섹션 구조, 아키텍처 원칙 24개, .devin/workflows 제거 + skills 통합 — 완료 (2026-07-13)

## 진행 중 작업

### 아키텍처 전수 점검 — B-09 완료, 20개 미시작
- **완료**: B-01~B-09, F-01 (P0 전체 + B-06~B-09)
- **미시작**: B-10~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-10 (엔진 계좌/서비스) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 업종순위설정 ⑥ 종목 합계 표시 — 사용자 UI 확인 대기
- ⑥ 입력란 0/1/3/5 변경 시 보조 줄 "상위 N개 업종 종목 합계: X종목" 즉시 갱신 확인
- 0 설정 시 "상위 0개 업종 종목 합계: 0종목" 표시 확인 (백엔드 재기동 후)

### 2순위: engine_settings.py 인접 라인 P20 폴백 일괄 정리 (승인 대기)
- line 138: `sector_min_rise_ratio_pct` — `or 60.0`이 0%를 60%로 치환
- line 139: `sector_min_trade_amt` — `or 0.0`은 다행이지만 패턴 동일 위험
- 동일 패턴(`_v if _v is not None else 기본값`)으로 일괄 정리 권장

### 3순위: 아키텍처 전수 점검 P1 세션 (B-10)
- B-10: 엔진 계좌/서비스 (`engine_account.py`, `engine_account_rest.py`, `engine_account_notify.py`, `engine_service.py`)
- `docs/architecture_audit_plan.md` 체크리스트 사용, 발견 문제를 섹션 7에 등록
- 이후 B-11 (P1) → B-12~B-19 (P2) → B-20~B-23 (P3) → F-02~F-07 순서

### 보류: P23 테이블 컬럼 너비 일관성 개선 (사용자 승인 대기)
- stock-detail.ts 자체 `makeAmountColumn` 너비 설정 없음, 비표준 컬럼 너비 설정 없음 (buy-target.ts 6개, sell-position.ts 6개, profit-shared.ts 9개), 순번/종목코드 컬럼 팩토리 사용 통일

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
