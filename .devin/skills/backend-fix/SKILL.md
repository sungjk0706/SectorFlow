---
name: backend-fix
description: 백엔드 코드 수정 및 런타임 검증 절차
allowed-tools:
  - read
  - grep
  - glob
  - exec
  - edit
  - write
---

## 사용자 전제 (필수)
- **사용자는 코딩 지식이 전혀 없음.** UI 기준 일반 용어로만 소통. 기술 명령어 안내 금지. 에이전트가 직접 실행.
- **승인 전 코드 수정 절대 금지 (AGENTS.md 섹션3 규칙0 준수).** 이 스킬이 호출되었다고 해서 자동으로 수정에 들어가는 것이 아님. 사용자가 "진행해/수정해/구현해/적용해/go" 등 명시적 실행 지시어를 준 경우에만 수정. 분석/조사/계획/추천까지만 수행하고 대기.

## 백엔드 수정 절차

### 1. 사전 조사 (필수 — AGENTS.md 섹션3 규칙 0-2 준수)
> **다단계 작업 안내**: 신규 기능/구조 변경/다단계 작업인 경우 AGENTS.md 섹션4 "다단계 작업 워크플로우" 적용 (설계→태스크→구현 3세션). 본 스킬은 구현 단계(3세션~)의 백엔드 수정 절차 담당.
- 대상 파일의 전체 구조와 의존성 확인
- 영향 받는 모든 파일/함수/변수 식별
- 아키텍처 원칙 준수 여부 확인 — AGENTS.md 섹션2 "코드 수정 시 점검 체크리스트" 사용
- **기존 공통 자산 확인 (AGENTS.md 섹션3 규칙 0-2.4)**: 신규 함수/상수/패턴 구현 전, 기존 공통 자산(`core/constants.py`, 공통 유틸, 기존 함수 등)을 먼저 검색. 동일 또는 유사한 공통 자산이 있으면 반드시 그것을 활용하고 같은 기능을 새로 만들지 않음.
- **기존 로직 롤백 여부 확인 (AGENTS.md 섹션3 규칙 0-3/0-4/0-5 준수)**: 이 수정이 기존 코드를 이전 상태로 되돌리는 행위(롤백)인지 확인. 롤백에 해당하면 사유·대상·영향 범위를 사용자에게 보고 후 승인받아야 함 (승인 없는 롤백 절대 금지). 특히 수신률·업종 점수·매매 로직 등 핵심 기능 변경 시 UI 기준 일반 용어로 변경 내용 설명 + 승인 필수(규칙 0-4). 사용자가 직접 설계/승인한 로직(예: 누적 수신 세트, 업종 점수 계산식)은 사유·영향·대안 상세 보고 후 승인 필수(규칙 0-5).
- 조사 결과(의존성/영향범위/원칙 부합)를 수정 계획에 포함하여 사용자에게 제시. 승인 후 수정 시작.

### 2. 코드 수정
- 작은 단위로 수정 (파일 하나씩, 블록 단위)
- 아키텍처 원칙 준수:
  - 모든 I/O는 async def (P2)
  - 동기 함수 금지 (httpx.AsyncClient/aiosqlite 사용)
  - run_in_executor 우회 금지 (P3)
  - 단일 asyncio 이벤트 루프 유지 (P1)
  - 폴백 금지 (P20)
- **ARCHITECTURE.md 금지 패턴 5개 준수** (수정 후 반드시 확인):
  - `asyncio.run()` 금지 → `async def` + `await` 직접 호출
  - `create_task` 무분별 분리 금지 → `schedule_engine_task()` 사용 (add_done_callback 포함)
  - `except Exception: pass` 금지 → `logger.warning(..., exc_info=True)`
  - async 함수 `await` 누락 금지 → 4-2 RuntimeWarning 검증으로 확인
  - dead code 방치 금지 → 호출되지 않는 함수 삭제 또는 명시적 `# DEPRECATED` 표시
- **실시간 데이터 처리 금지 목록 (Python 백엔드)**:
  - `time.sleep()` → `asyncio.sleep()`
  - `threading.Lock/RLock/Event` → `asyncio.Lock/Event`
  - `input()` → 절대 사용 금지
  - `requests`/`urllib` → `httpx.AsyncClient`
  - 전체 `json.dumps()` 재직렬화 → delta만 직렬화
  - 전체 리스트 순회 후 교체 → 인덱스/키 직접 접근
  - 매 틱마다 전체 데이터 재조회 → 변경분만 처리
  - `threading.Thread()` 신규 생성 → 기존 이벤트 루프 활용
  - `asyncio.create_task()` 무분별한 분리 → 호출 체인 유지
  - Queue에 무한 쌓기 → 처리 속도 > 수신 속도 보장
  - 공통: 실시간 수신 데이터는 delta만 처리, 50ms 초과 시 경고 로그, 200ms 초과 시 처리 중단 및 원인 보고

### 3. 정적 검증
- py_compile 통과 확인
- 타입 체크 (mypy)
- 린트 (ruff)

### 4. 런타임 기동 검증 (필수 - 원칙 19)
py_compile 통과와 pytest 통과는 런타임 동작을 보장하지 않음. 반드시 다음 절차 수행:

#### 4-1. 앱 기동
```bash
.venv/bin/python main.py
```
- **async/await 누락 검증 (금지 패턴 4)**: `.venv/bin/python -W error::RuntimeWarning main.py`로 기동 시 RuntimeWarning을 에러로 승격. `RuntimeWarning: coroutine was never awaited` 발생 시 await 누락이므로 즉시 수정.

#### 4-2. 기동 확인 (10~30초 대기)
- 콘솔 로그 확인: 에러/Traceback/RuntimeWarning 없음
- 파일 로그 확인 (`backend/logs/trading_*.log`): 정상 기록 여부
- 지연/hang/예외 발생 여부 확인
- **금지 패턴 5개 재확인**: 기동 로그에서 `asyncio.run`, `create_task` 예외 사라짐, `except Exception: pass` 로그 없음, dead code 경고 없음

#### 4-3. 프로세스 종료
```bash
kill <PID>
```
- 잔존 프로세스 확인 및 완전 종료는 AGENTS.md 섹션3 규칙 5-1 준수 (세션 종료 전 0건 확인까지 필수)

### 5. 테스트 실행 (필요한 경우)
```bash
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- `timeout_method = signal` 필수 — `thread` 방식은 asyncio C-level wait를 interrupt하지 못해 hang 시 프로세스가 영구 블록됨
- `pytest.ini`에 전역 설정되어 있으므로 CLI에서 생략 가능
- hang 감지 시 즉시 강제 종료
- 잔존 프로세스 정리는 AGENTS.md 섹션3 규칙 5-1 준수

#### 5-1. 자동 hang 체크 원칙 (에이전트 필수 — 수동 개입 금지)
- 10초마다 `command_status`로 진행 상태 자동 체크
- 10초 이상 로그/출력 멈추면 즉시 hang 간주 → 강제 종료
- hang 감지 시 즉시 SIGTERM/Ctrl+C로 프로세스 종료 후 원인 분석
- 위 모든 과정은 에이전트가 자동 수행 — 사용자 확인 대기 금지, 수동 개입 금지

#### 5-2. 테스트 hang 방지 코딩 원칙 (근본 원인별)

**원인 A: 실제 asyncio 동기화 프리미티브 (Lock/Event/wait_for)**
- 금지: 테스트에서 실제 `asyncio.Lock()`, `asyncio.Event()`, `asyncio.wait_for()` 사용
- 해결: `MagicMock` + `AsyncMock`으로 교체
  - Lock: `lock.__aenter__ = AsyncMock(return_value=lock)`, `lock.__aexit__ = AsyncMock(return_value=None)`
  - Event: `ev.wait = AsyncMock()`, `ev.clear/set = MagicMock()`
  - wait_for: 즉시 반환 또는 즉시 `TimeoutError` 발생시키는 async 함수로 patch

**원인 B: asyncio.create_task 백그라운드 태스크**
- 금지: 테스트에서 `asyncio.create_task()`가 실제 실행되는 것을 허용
- 해결: `patch("module.asyncio.create_task")`로 mock 교체, `add_done_callback` 속성 포함

**원인 C: NotificationWorker / 백그라운드 워커 싱글톤**
- 금지: `_fire_and_forget_telegram` 등이 실제 `NotificationWorker.get_instance()`를 호출하여 백그라운드 태스크 생성
- 해결: autouse fixture에서 `patch("module._fire_and_forget_telegram")` 처리

**원인 D: 실제 DB I/O (aiosqlite)**
- 금지: 테스트에서 `get_db_connection()`이 실제 DB에 연결
- 해결: autouse fixture에서 `patch("backend.app.db.database.get_db_connection")` 처리

**원인 E: pytest-asyncio 이벤트 루프 간섭**
- 금지: conftest.py에 async fixture 사용 (이벤트 루프 정리 중 hang 유발)
- 금지: conftest.py에서 `asyncio.sleep` 전역 patch (pytest-asyncio 내부 동작 간섭)
- 해결: conftest.py는 동기 fixture만 사용, 캐시 리셋 등 최소 기능만 유지

#### 5-3. 동적 타임아웃 설정 (무한 대기 방지)
- `@pytest.mark.timeout(N)` 또는 `--timeout=N` CLI 옵션
- 비동기 테스트는 `asyncio.wait_for(coro, timeout=N)`로 개별 타임아웃 적용
- 기본값: 단위 테스트 30초, 통합 테스트 60초, E2E 120초
- 타임아웃 초과 시 실패로 처리하고 원인 분석

#### 5-4. run_command 사용 시
- `Blocking: false` + `WaitMsBeforeAsync: 20000` — hang 감지 시 명령 취소 가능
- 또는 subprocess + `proc.wait(timeout=N)` + `proc.kill()` 패턴 사용

### 6. 보고
- 수정한 파일
- 해결한 근본 원인
- 검증한 항목 (정적 검증 + 런타임 기동)
- 사용자가 직접 확인할 방법
- **용어 사전 준수 (P23)**: 사용자 보고, 로그 메시지, 문서 작성 시 `ARCHITECTURE.md` 부록 L 표준 용어 사전 준수 — "업종" not "섹터", "종목" not "주식", "매수 후보" not "바이 리스트"
- **단계 완료 시 작업 여력 보고 (AGENTS.md 섹션4 Context Management Rules 10 준수)**: 각 단계 완료 시 사용자에게 현재 작업 여력을 일반 용어로 보고 ("작업 여력 충분/적음"). 보고 후 커밋 + HANDOVER.md 갱신 진행 여부를 사용자 승인받아 진행.

## 주의사항
- 아키텍처 원칙 관련 수정은 런타임 기동 검증 생략 금지
- asyncio, 이벤트 루프, 비동기 큐, WebSocket 관련 수정은 특히 주의
- 잔존 프로세스 0건 확인까지가 완료 기준 (AGENTS.md 섹션3 규칙 5-1)

## 작업 중 발견 문제 기록 의무
- 메인 작업 도중 발견한 아키텍처 위반(P원칙), 오류, 잠재적 버그, dead code, 폴백 패턴, 아키텍처 원칙에 부합하는 더 나은 구조(개선점) 등은 즉시 `HANDOVER.md` "미해결 문제" 섹션에 기록 (파일:줄, 위반/부합 원칙 번호, 증상/개선내용). 사용자 승인 불필요 — 발견 즉시 기록. 상세 규칙은 AGENTS.md 섹션4 규칙 9 참조.
