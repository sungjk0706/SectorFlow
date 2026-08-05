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
> **공통 전제 (승인 전 수정 금지·사용자 소통·보고·오류 알림 의무·작업 시작 전 아키텍처 판정 필수·완료 보고 봉인)**: problem-solve 스킬 "사용자 전제" 섹션 (.devin/skills/problem-solve/SKILL.md) 참조.
- **설계서·태스크 파일 작성 시 (다단계 1·2세션)**: 작성 전 반드시 docs/절차규칙_문서포맷_상세.md(특히 0절 "문서 역할 원칙" 5항목)을 재독. 기존 `docs/태스크/*.md`는 포맷 SSOT가 아니라 과거 산출물 — 베끼지 말 것.

## 백엔드 수정 절차

### 1. 사전 조사 (필수 — docs/절차규칙_조사_상세.md 규칙 0-2 준수)
> **다단계 작업 안내**: 신규 기능/구조 변경/다단계 작업인 경우 docs/절차규칙_세션절차_상세.md "다단계 작업 워크플로우" 적용 (설계→태스크→구현 3세션). 본 스킬은 구현 단계(3세션~)의 백엔드 수정 절차 담당.
> **사전조사 후 워크플로우 전환 (docs/절차규칙_조사_상세.md 규칙 0-2-5)**: 사전조사 완료 후 작업량이 크다고 판명된 경우, 사용자에게 다단계 워크플로우 전환을 제안하고 승인받아야 함 (승인 없이 임의 전환/임의 단일 세션 진행 금지).
> **사전조사 기본 흐름 (의존성 확인·영향 범위 3단계 분류·회귀 예상 지점 명시적 나열·근본 원인 분석·아키텍처 원칙 점검 P1~P25·기존 공통 자산 확인·네이밍 일관성 확인·롤백 여부 확인·사용자 의도 파악 질문·수정안 제시 원칙·코드 수정 전 의도 파악 3항목)**: problem-solve 스킬 "기본 틀" 섹션 (.devin/skills/problem-solve/SKILL.md) 참조. 본 스킬에는 백엔드 특화만 기재.

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
- 잔존 프로세스 확인 및 완전 종료는 docs/절차규칙_조사_상세.md 0-1-3 준수 (세션 종료 전 0건 확인까지 필수)

### 5. 테스트 실행 (필요한 경우)
```bash
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- `timeout_method = signal` 필수 — `thread` 방식은 asyncio C-level wait를 interrupt하지 못해 hang 시 프로세스가 영구 블록됨
- `pytest.ini`에 전역 설정되어 있으므로 CLI에서 생략 가능
- hang 감지 시 즉시 강제 종료
- 잔존 프로세스 정리는 docs/절차규칙_조사_상세.md 0-1-3 준수

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

#### 5-5. 검증 자동화 루프(하네스) — docs/절차규칙_조사_상세.md 0-1-2 검증 자동화 루프 준수
정적 검증(섹션 3) + 런타임 기동(섹션 4) + 테스트(섹션 5) 중 실패 시 통과까지 자동 반복. 상세 절차·중단 조건·0-1 관계는 docs/절차규칙_조사_상세.md 0-1-2 검증 자동화 루프 본문 참조. 종료 조건: py_compile + pytest + 런타임 기동(`-W error::RuntimeWarning`) 전부 pass + 잔존 프로세스 0건(0-1-3). 섹션 7 보고에 루프 결과 명시.

### 6. 완료 기준 (Definition of Done)
> 검증 명령 통과만으로 "완료"가 아님. 아래 기준 전부 충족 시 완료 (P20 — 암묵적 생략 금지).
> **3계층 검증 (하네스 강화 — docs/절차규칙_세션절차_상세.md "작업 완료 시 점검 체크리스트" 1단계 준수)**: 기계적 검증 + 요청 의도 사후 확인 + 독립 검증자(거래·핵심 로직 시). 상세는 docs/절차규칙_세션절차_상세.md 본문.

- [ ] **기계적 검증**: 정적 검증(py_compile / ruff) + 런타임 기동(`-W error::RuntimeWarning` 포함, 금지 패턴 5개 재확인) + 테스트(회귀 예상 지점 포함) + 잔존 프로세스 0건(0-1-3)
- [ ] **완료 보고 전 기계적 검증 스크립트 (강제)**: `bash scripts/pre-complete-check.sh backend` 실행 — 실패 시 완료 보고 금지, 통과까지 재시도(0-1-2 루프)
- [ ] **요청 의도 사후 확인 (Intent layer — 강제)**: "사용자 원래 요청" vs "실제 구현된 변경" 나란히 비교 → 일치하는지 확인. 불일치 시 완료 보고 금지.
- [ ] **독립 검증자 검토 (거래·핵심 로직 시 필수)**: `run_subagent`(profile `subagent_explore`)에게 커밋 해시 + 변경 요약 + "요청대로 구현되었는지 + 원칙 위반 없는지" 질문. 단순 버그 수정은 생략 가능(사전조사 시 "회귀 위험 없음" 명시한 경우만). **단, 거래·매매·주문·리스크 로직(safe-trade 스킬 대상) 및 핵심 로직은 safe-trade 5-2·independent-verify 위험도 '높음' 기준에 따라 생략 불가 — 항상 필수.**
- [ ] 회귀 예상 지점별 검증 완료 (섹션 1에서 나열한 지점) — 기존 테스트 없는 지점은 신규 회귀 테스트 작성
- [ ] **사용자 화면 확인 권유**: 에이전트가 할 수 없는 화면 확인 항목을 완료 보고에 권유 형태로 포함 (강제 아님 — 권유, 단 생략 금지)
- [ ] 사용자 보고 완료 (규칙 0-8)

### 7. 보고
> **사용자 보고 의무**: docs/절차규칙_조사_상세.md 규칙 0-8 준수 (UI 기준 일반 용어 + P1~P25 부합 여부 + 보고서 형식은 docs/절차규칙_보고_상세.md '작업 완료 보고서 표준 형식' 참조). 오류·위험 발견 시 규칙 0-9(오류·위험 알림 의무) 준수.

- **검증 결과 표**에 백엔드 필수 행:
  - `py_compile` / `ruff` / `mypy` (해당 시)
  - `pytest` (전체 또는 대상 파일)
  - `RuntimeWarning` 기동 검증 (`.venv/bin/python -W error::RuntimeWarning main.py`)
  - 잔존 프로세스 0건
- **변경 내용 표**에 추가:
  - 수정한 파일 목록, 해결한 근본 원인, 사용자가 직접 확인할 방법
  - `근본 원인 분석 (5 Whys)`: 버그 수정 시 problem-solve 섹션 1-2의 결과 (표면 증상 → 근본 원인 → 해결안). 신규 구현 시 "해당 없음"
  - `회귀 예상 지점`: 섹션 1에서 나열한 회귀 위험 지점 + 각 지점별 테스트 존재 여부 + 신규 회귀 테스트 작성 여부
- **아키텍처 원칙 판별 표**에는 AGENTS.md 작업 시작 전 아키텍처 적합성 판정 게이트의 P1~P25 전체 결과를 포함하고, 백엔드 핵심 항목과 금지 패턴 5개(실시간 데이터 처리 금지 목록)를 구체적으로 적는다.
- **검증·관찰 계층 게이트 (위험도 기반 — docs/절차규칙_세션절차_상세.md "검증·관찰 계층 게이트" 준수)**: 백엔드 변경은 위험도에 따라 계층 적용. 파이프라인·인증·설정 스키마·DB 마이그레이션(중간)은 사전 롤백 필수 + 독립 검증·관찰 권장. 거래 로직·시간 의존 로직(높음)은 전 게이트 필수 — safe-trade 스킬 6-1절 참조. 단순 1파일 수정(낮음)은 게이트 생략 가능(P24).

## 주의사항
- 아키텍처 원칙 관련 수정은 런타임 기동 검증 생략 금지
- asyncio, 이벤트 루프, 비동기 큐, WebSocket 관련 수정은 특히 주의
- 잔존 프로세스 0건 확인까지가 완료 기준 (docs/절차규칙_조사_상세.md 0-1-3)

## 작업 중 발견 문제 기록 의무
docs/절차규칙_컨텍스트관리_상세.md 규칙 9 준수 — 발견 즉시 `HANDOVER.md` "미해결 문제"에 기록, 사용자 승인 불필요.
