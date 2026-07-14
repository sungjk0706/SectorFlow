# SectorFlow Agent Rules

> **규칙 우선순위**: 섹션1(프로젝트 개요) > 섹션2(아키텍처 원칙) > 섹션3(수행 규칙) > 섹션4(작업 프로세스).
> 상위 섹션 규칙이 하위 섹션 규칙보다 우선. 충돌 시 상위 섹션 기준으로 판단.

---

## 섹션1. 프로젝트 개요 (최상위)

SectorFlow is a local real-time stock auto-trading web app for one person.

- Backend: FastAPI + Python + aiosqlite (SQLite `backend/data/stocks.db`)
- Frontend: TypeScript (Vanilla)
- Pipeline: After market close → download 5-day bars → filter by trading amount → group by custom sector → sector screening → sector ranking → top N sectors → buy candidates → buy (market order) → hold list → sell
- Key frontend state: `frontend/src/stores/store.ts`

### 사용자 프로필 (필수 전제)

- **사용자는 코딩 지식이 전혀 없음 ("코딩 1도 모름").** 이 전제를 모든 안내, 보고, 질문에 항상 유지.
- 사용자는 UI로만 조작하고 확인함. 터미널 명령어, 코드, API 호출을 직접 다루지 않음.
- 에이전트가 기술 작업을 전담하고, 사용자에게는 UI 기준 일반 용어로만 소통.

---

## 섹션2. 아키텍처 원칙 (불변 원칙)

> 본 섹션은 `ARCHITECTURE.md`에 정의된 24개 불변 원칙(P1~P24)과 안전 규칙을 포함. 코드 변경 시 반드시 준수.

### Safety Rules (Always Apply)

1. Never delete or overwrite `backend/data/stocks.db` or any `*.db` files directly.
2. Before any DB schema change or migration, create a timestamped backup of `stocks.db`, `stocks.db-shm`, and `stocks.db-wal`.
3. Trading code must stay in simulation/test mode unless the user explicitly confirms real money and you warn them.
4. Do not hardcode broker API keys, tokens, or credentials.
5. Do not run `sudo`, `rm -rf`, `curl`, `wget`, or `sqlite3` without user approval.
6. Do not edit `~/.bashrc`, `~/.zshrc`, or system paths.

### Architecture Principles Reference

- 코드 변경 시 `ARCHITECTURE.md`의 24개 불변 원칙(P1~P24)을 준수. 주요 원칙:
  - **P10 (SSOT)**: 같은 데이터가 여러 곳에서 독립 관리되지 않도록 단일 진실 소스 유지.
  - **P16 (구현 = 살아있는 경로 배선)**: 호출되지 않는 안전코드/dead code 금지.
  - **P20 (폴백 금지)**: 정상 경로의 빈 문자열/None/누락을 폴백으로 덮지 않음, silent `except: pass` 금지.
  - **P21 (사용자 투명성)**: 사용자 모르는 중요 의사결정 금지, 백엔드 상태의 UI 표시 의무.
  - **P22 (데이터 정합성)**: 파생 데이터 모델, 기동 시 대조(reconciliation), 불일치 시 즉시 차단.
  - **P23 (일관된 통일성)**: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관, UI 패턴 공통 컴포넌트 추출.
  - **P24 (단순성)**: 더 단순한 대체 가능성, 불필요한 추상화 금지, 함수/파일 길이·복잡도 기준.
- 전체 원칙 목록은 `ARCHITECTURE.md` 제1부 "불변 원칙 24개" 참조.

### 코드 수정 시 점검 체크리스트 (수정 전/중/후 필수)

> 아래 체크리스트는 24개 원칙 중 스킬 파일에 개별 명시되지 않은 원칙들을 실행 가능한 점검 항목으로 구체화. 모든 코드 수정 시 수정 전 조사(규칙 0-2) 단계에서 확인.

#### 백엔드 수정 시 필수 점검
- [ ] **P1-P3 (async 일관성)**: 모든 I/O는 `async def`, 동기 함수(`requests`, `sqlite3`, `time.sleep`, `threading.Lock`) 금지, `run_in_executor()` 우회 금지
- [ ] **P4 (증권사명 침투 금지)**: 공통 로직에 `kiwoom_`/`ls_` 접두사가 없는가? 증권사별 코드는 `broker_factory.py` 레지스트리에 분리되었는가?
- [ ] **P5 (EventBus 금지)**: Redis/Pub-Sub/콜백 리스트 옵서버 패턴을 도입하지 않았는가? 직접 호출 체인을 유지했는가?
- [ ] **P7 (블로킹 금지)**: 틱 핸들러에 per-tick O(n) 연산, 매 틱 DB 조회, 매 틱 전체 리스트 순회가 없는가?
- [ ] **P11 (폴링 금지)**: `while + sleep` 폴링을 도입하지 않았는가? `asyncio.Queue` + `asyncio.wait()` 이벤트 기반인가?
- [ ] **P12 (DB 연결)**: 매 요청마다 `connect()`를 호출하지 않았는가? 싱글톤 연결을 유지했는가?
- [ ] **P13 (설정 메모리 상주)**: 틱 연산 단계에서 DB 설정 조회를 하지 않았는가? 메모리 캐시를 참조했는가?
- [ ] **P14 (멀티스레드 금지)**: `threading.Thread()` 신규 생성이 없는가? `asyncio.create_task()` 무분별 분리가 없는가?
- [ ] **P15 (단일 주문 경로)**: 주문 로직이 `execute_buy()`/`execute_sell()` 단일 경로인가? 분기/우회 경로가 없는가? (거래 로직 수정 시 safe-trade 스킬 필수)
- [ ] **P16 (살아있는 경로)**: 작성한 안전장치가 실제 실행 경로에 연결되었는가? 호출되지 않는 dead code가 아닌가?
- [ ] **P17 (플래그 단일 소스)**: 플래그(`auto_buy_on` 등)를 여러 곳에서 직접 수정하지 않았는가? `integrated_system_settings_cache`에서만 관리되는가?
- [ ] **P20 (폴백 금지)**: 정상 경로의 빈 문자열/None/누락을 폴백으로 덮지 않았는가? silent `except: pass`가 없는가?
- [ ] **P22 (데이터 정합성)**: 파생 데이터를 중복 저장하지 않았는가? 원본에서 파생하는 모델인가? 불일치 시 즉시 차단하는가?
- [ ] **P23 (용어 통일)**: 로그/문서에 "섹터" 대신 "업종", "주식" 대신 "종목"을 사용했는가? (`ARCHITECTURE.md` 부록 L 참조)
- [ ] **P24 (단순성)**: 함수 50줄 이하, 파일 500줄 이하, 순환 복잡도 10 이하? 불필요한 추상화/1회용 래퍼가 없는가?

#### 프론트엔드 수정 시 필수 점검
- [ ] **P21 (사용자 투명성)**: 백엔드 상태 변화(매수 차단, 리스크 초과 등)를 UI에 표시했는가? 사용자가 "왜 이 종목이 매수되지 않았지?"라고 의문을 갖지 않도록 했는가?
- [ ] **P23 (용어 통일)**: UI 텍스트에 "섹터" 대신 "업종", "주식" 대신 "종목", "바이 리스트" 대신 "매수 후보"를 사용했는가? (`ARCHITECTURE.md` 부록 L 참조)
- [ ] **P23 (UI 패턴 일관성)**: 동일한 UI 패턴이 2회 이상 반복 시 공통 컴포넌트로 추출했는가?

#### ARCHITECTURE.md 금지 패턴 5개 (수정 후 필수 확인)
- [ ] `asyncio.run()` 사용 금지 → `async def` + `await` 직접 호출
- [ ] `create_task` 무분별 분리 금지 → `schedule_engine_task()` 사용 (add_done_callback 포함)
- [ ] `except Exception: pass` 금지 → `logger.warning(..., exc_info=True)`
- [ ] async 함수 `await` 누락 금지 → `python -W error::RuntimeWarning main.py`로 검증
- [ ] dead code 방치 금지 → 호출되지 않는 함수 삭제 또는 명시적 `# DEPRECATED` 표시

### Code Removal Rules

함수, 변수, 클래스, 모듈 등 코드를 제거할 때 다음을 반드시 함께 수행:

1. **참조 주석 정리**: 제거된 코드를 참조하는 모든 주석, docstring, 파일 헤더 설명을 함께 수정 또는 제거.
2. **불일치 금지**: 주석과 코드의 불일치는 원칙10(SSOT) 및 원칙21(사용자 투명성) 위반. 제거된 함수가 docstring에 남아 있으면 신규 코드에서 해당 함수를 찾는 오류 발생.
3. **검색 범위**: 제거된 코드의 이름으로 전체 코드베이스(backend + frontend + tests + docs)를 검색하여 잔존 참조 확인. 단, 문제 기록(`architecture_audit_plan.md` 섹션 7)의 역사적 로그는 유지.
4. **테스트 파일 포함**: 테스트 파일의 docstring, 헤더 주석도 코드와 일치해야 함.

---

## 섹션3. 수행 규칙 (모든 작업 시 준수)

### Investigation & Problem Solving Rules

0. **승인 전 코드 수정 절대 금지 (최우선 규칙).** 어떤 작업이든 — 디버깅, 새 구현, 개선, 리팩토링, 1줄 변경 포함 — 사용자의 명시적 승인 없이는 절대 코드를 수정하지 않는다. 분석, 조사, 계획 제안, 추천까지만 수행하고 승인 전까지 수정 금지.
   - **승인 트리거**: 사용자가 "진행해", "수정해", "구현해", "go", "해줘", "적용해" 등 명시적 실행 지시어를 사용한 경우만 승인으로 간주.
   - **미승인 상황 (수정 금지)**: 사용자가 "분석해", "조사해", "확인해", "검토해", "의견 줘", "추천해", "어떻게 생각해", "계획 보여줘" 등을 요청한 경우. 이 경우 분석/조사/제안까지만 하고 응답 종료. 사용자가 추가로 실행 지시어를 줄 때까지 대기.
   - **추천 요청 시 주의**: 사용자가 "추천해줘", "너의 추천은?" 등을 물을 때, 추천을 제시한 후 사용자의 명시적 승인 없이 자동으로 수정에 들어가는 것은 절대 금지. 추천 제시 → 사용자 승인 → 수정 순서 엄수.
   - **Plan 모드가 아닐 때도 동일**: Normal 모드라도 승인 전 수정 금지. 모드와 무관하게 항상 적용.
0-1. **세션당 1단계 원칙 (강제).** 각 세션은 1단계(Step)만 진행. 한 세션에서 여러 단계를 연속 진행 금지.
   - 단계 완료 후 반드시 검증 수행: 백엔드 수정 시 테스트 + 런타임 기동(규칙 5), 프론트엔드 수정 시 빌드 + 브라우저 확인.
   - 검증 이상 없으면 커밋 + `HANDOVER.md` 갱신 + 사용자 보고 후 세션 종료. 검증 실패 시 다음 세션으로 넘기지 않고 해당 세션에서 원인 해결.
   - 다음 단계는 다음 세션에서 `HANDOVER.md` 기반으로 이어서 진행 (섹션4 규칙 6 참조).
   - 작업량이 많은 경우 사전 분할 후 사용자에게 분할 계획 보고 (섹션4 규칙 1과 연계).
   - 규칙 3(파일/블록 단위 수정)은 본 규칙의 세부 수행 방식. 본 규칙은 세션 단위 경계를 정의.
0-2. **수정 전 사전조사 의무 (강제).** 코드 수정 착수 전 반드시 다음 3항목 조사:
   1) **의존성**: 이 수정이 다른 어떤 코드(함수/변수/모듈/타입/설정 키)에 영향을 주는지 전체 코드베이스 검색으로 식별.
   2) **영향범위**: 백엔드/프론트엔드/테스트 중 어디까지 바뀌는지 명시.
   3) **아키텍처 원칙 부합 여부**: P10(SSOT)/P16(살아있는 경로)/P20(폴백 금지)/P21(사용자 투명성)/P22(데이터 정합성)/P23(일관성)/P24(단순성) 중 해당 원칙 확인.
   - 조사 결과를 수정 계획에 포함하여 사용자에게 제시.
   - 사용자 승인(실행 지시어, 규칙 0) 후에만 수정 시작.
   - 스킬(problem-solve/backend-fix/frontend-fix)의 사전조사 절차와 동일 기준 적용. 스킬 미호출 시에도 본 규칙 적용.
1. No guessing. Base all conclusions on actual code, search results, logs, and browser reproducible behavior.
2. Solve the root cause, not the symptom. No temporary fixes, fallbacks, `!important`, `as any`, or "let's do this for now" workarounds.
3. One small step at a time. Modify one file or block at a time, then verify.
4. After any change, run at least one of: type check, lint, build, test, or runtime start.
4-1. **테스트 실패 추적 의무 (강제).** 테스트 실행 시 실패가 발생하면 "내 수정과 무관한 기존 실패"라고 단정하지 말고, 반드시 아래 절차를 수행:
   1) **연관성 조사**: 실패한 테스트가 수정한 코드/함수/모듈/설정 키를 직접 또는 간접적으로 참조하는지 확인.
   2) **수정 전 상태 비교**: `git stash`로 수정을 임시 되돌린 후 동일 테스트를 실행하여 수정 전에도 실패하는지 확인. 수정 전에도 실패하면 기존 실패로 판정, 수정 후에만 실패하면 내 수정이 원인.
   3) **기존 실패로 판정된 경우**: 사용자 보고에 "기존 실패 N건 (수정 전 동일 실패 확인)"으로 명시하고, `HANDOVER.md` "미해결 문제" 섹션에 기록.
   4) **내 수정이 원인인 경우**: 즉시 원인 추적 및 수정. "기존 실패"로 치부하고 넘어가는 것은 절대 금지.
   - 테스트 실패는 무언가 잘못됐다는 신호. 무시하지 말고 반드시 추적하는 것이 원칙.
5. For backend changes, runtime startup check is mandatory: start `.venv/bin/python main.py`, check logs, wait 10–30s, then terminate. 잔존 프로세스 정리는 규칙 5-1 준수.
5-1. **세션 종료 전 잔존 프로세스 완전 종료 (강제).** 모든 작업 완료 후 세션 종료 전 반드시 다음 절차 수행:
   1) **잔존 프로세스 확인**: `ps aux | grep -E "python|main.py|pytest" | grep -v grep`로 백엔드/테스트 프로세스 잔존 여부 확인.
   2) **잔존 시 즉시 종료**: 1개라도 잔존하면 `kill <PID>`로 종료. 응답 없으면 `kill -9 <PID>`.
   3) **재확인으로 0건 확인**: 종료 후 재확인하여 잔존 0건까지가 세션 종료 조건.
   - **적용 범위**: 백엔드 런타임 기동(규칙 5), pytest 실행, db-backup 앱 종료 등 프로세스를 띄운 모든 작업. 프론트엔드 전용 작업이라도 백엔드 기동을 동반한 경우 포함.
   - **세션 종료 조건**: 잔존 프로세스 0건 확인 전에는 세션 종료 불가. HANDOVER.md 갱신 + 사용자 보고 전에 반드시 수행.
6. Do not commit or update `HANDOVER.md` without user approval.

### 사용자 의사소통 규칙 (필수)

사용자는 코딩 지식이 전혀 없음(섹션1 참조). 모든 소통은 아래 원칙 준수:

1. **기술 명령어 안내 금지**: `curl`, `npm`, `cd`, `httpx`, `pytest`, `python`, `git`, `node` 등 기술 명령어를 사용자에게 직접 안내하지 않음. 에이전트가 직접 실행.
2. **UI 기준 검증 안내**: 사용자에게 확인/검증을 요청할 때는 항상 UI 조작으로 안내. 예: "설정 페이지에서 X를 확인해 주세요", "브라우저에서 Y 화면을 봐 주세요". 터미널/콘솔 확인 요청 금지.
3. **API 직접 호출 안내 금지**: 사용자에게 API 직접 호출(curl, httpx, Postman 등)로 검증을 요청하지 않음. 에이전트가 내부적으로 API 호출 후 결과를 UI 화면 또는 일반 용어로 보고.
4. **일반 용어 사용**: 코드 식별자, 파일 경로, 스택 트레이스를 사용자 보고에 그대로 노출하지 않음. "화면의 매수 후보 목록", "설정의 증권사 항목" 등 UI 요소 기준으로 설명. 단, 사용자가 명시적으로 기술 세부사항을 요구한 경우는 예외.

### 보고서 형식 (5항목 준수)

모든 문제 해결 보고서는 다음 5개 항목을 준수:

1. **현상** (problem symptom): 사용자가 관찰한 문제 증상.
2. **근본 원인** (root cause, file:line): 실제 코드 기반 근본 원인. 파일명:줄번호 명시.
3. **수정 방안** (fix): 근본 원인을 해결한 구체적 수정 내용.
4. **영향 범위** (impact): 수정이 다른 기능/모듈에 미치는 영향.
5. **검증 방법** (verification): 수정 후 실행한 검증 단위 테스트, 빌드, 런타임 기동 등의 결과.

### Forbidden Words

"아마도", "아마", "대부분", "일반적으로", "일단", "우선", "임시로", "추후 개선", "나중에 리팩토링", "제 생각에는"

### Allowed Words

"파일 A의 n번째 줄에서 확인됨", "검색 결과 해당 클래스가 남아 있음", "빌드 로그에서 타입 오류가 확인됨", "이 부분은 아직 확인 필요"

---

## 섹션4. 작업 프로세스 (워크플로우)

### 세션 시작 절차 (필수 — 모든 세션 첫 응답 전 수행)

1. **HANDOVER.md 자동 확인 (강제)**: 세션 첫 응답 전 반드시 `HANDOVER.md`를 읽고 현재 상태 파악. 사용자가 "핸드오버 확인해줘"라고 별도 요청하지 않아도 자동 수행.
   - 확인 항목: 직전 완료 작업, 현재 상태, 진행 중 작업, 다음 단계, 미해결 문제.
2. **현재 상태 간략 보고**: 확인 후 사용자에게 현재 진행 상태를 간략히 요약 보고 (직전 완료 작업, 진행 중 작업, 다음 단계 우선순위).
3. **사용자 지시 대기**: 보고 후 사용자의 다음 작업 지시 대기. 사용자가 명확히 다른 작업을 즉시 지시한 경우(예: "X 수정해줘") 핸드오버 요약은 생략하고 지시된 작업에 집중 가능.
4. **완료 작업 정리 (규칙 7 연계)**: 새 세션 시작 시 `HANDOVER.md`의 "직전 완료 작업" 섹션에서 최근 1~2건만 유지하고 과거 완료 작업은 삭제 (규칙 7 준수).

### Skill Auto-Invocation

The user is a beginner and does not know which skill to use. Automatically invoke the appropriate skill based on the user's request. Do not wait for the user to ask for a specific skill.

- **Bug, debugging, problem analysis, root cause**: invoke `/problem-solve`
- **Backend code change or API error**: invoke `/backend-fix`
- **Frontend UI, page, or build error**: invoke `/frontend-fix`
- **DB schema change, migration, or table modification**: invoke `/db-backup` first, then proceed
- **Trading logic, broker API, order code**: invoke `/safe-trade` first
- **New logic implementation**: invoke `/problem-solve` for planning, then `/backend-fix` or `/frontend-fix` for implementation

When in doubt, invoke `/problem-solve` first. Always follow the rules in this file even when a skill is not explicitly invoked.

### Context Management Rules

1. **작업량 기반 사전 분할**: 작업량이 많은 경우, 에이전트가 자체 판단하여 작업을 작은 단위로 분할. 각 단위는 독립적으로 완료·검증 가능한 크기로 설정. 분할 시 사용자에게 분할 계획을 보고 후 진행.
2. **단계 완료 시 컨텍스트 점검**: 각 작은 단계 완료 시 현재 컨텍스트 사용량을 점검. 사용량이 높아 다음 단계에서 오류 가능성이 있다고 판단되면, 다음 단계 진행 전 `HANDOVER.md`에 현재 진행 상태를 갱신하여 만일의 중단에 대비. 점검 결과는 규칙 10에 따라 사용자에게 보고.
3. **사전 종료 권한**: 에이전트는 작업 중 컨텍스트 사용량이 많아져 오류 가능성이 있다고 판단되면, 현재 진행 상태를 `HANDOVER.md`에 기록하고 사용자에게 보고한 후 세션을 종료할 수 있음.
4. **HANDOVER.md 기록 의무**: 세션 종료 전 반드시 다음을 기록:
   - 완료된 작업 요약 (파일명, 테스트 수, 검증 결과)
   - 진행 중인 작업의 현재 단계 (어디까지 했고, 어디서부터 이어하면 되는지)
   - 다음 세션에서 수행해야 할 구체적 항목
5. **사용자 보고**: 세션 종료 시 사용자에게 진행 상태와 다음 단계를 명확히 전달.
6. **다음 세션 연속성**: 다음 세션 시작 시 "세션 시작 절차"의 HANDOVER.md 자동 확인(강제)에 따라 이어서 작업 진행.
7. **완료 작업 정리**: 새 세션 시작 시 `HANDOVER.md`의 "직전 완료 작업" 섹션에서 최근 1~2건만 유지하고 나머지 과거 완료 작업은 삭제. git history에 이미 기록되어 있으므로 중복 누적 방지. "현재 상태"와 "다음 단계" 섹션도 최신 상태로 업데이트.
8. **HANDOVER.md 수정 원칙 (read-before-write)**: `HANDOVER.md` 수정 시 반드시 read 먼저 수행. 기존 내용을 보존한 후 병합. write 도구로 덮어쓰기 금지 — 기존 섹션 내용을 읽어 확인한 후에만 수정/추가. 실수로 기존 내용을 삭제하는 사고 방지.
9. **작업 중 발견 문제 기록 의무 (강제)**: 메인 작업 도중 우연히 발견한 아키텍처 위반(P원칙), 오류, 잠재적 버그, dead code, 폴백 패턴 등은 현재 세션에서 즉시 해결하지 못하더라도 **반드시** `HANDOVER.md`의 "미해결 문제" 섹션에 기록. 사용자는 코딩 지식이 없어 직접 해결할 수 없으므로, 에이전트가 발견 즉시 기록하지 않으면 영영 누락됨.
   - **기록 형식**: 파일명:줄번호, 위반 원칙 번호(P10/P16/P20 등), 증상 1문장, (가능시) 수정 방향.
   - **중복 회피**: 이미 "미해결 문제"에 등록된 항목은 중복 기록하지 않고, 새 정보가 있으면 기존 항목에 갱신.
   - **세션 종료 보고**: 세션 종료 시 "미해결 문제"에 신규 추가된 항목이 있으면 사용자에게 명시적으로 보고 ("이번 세션에서 N건의 신규 문제를 발견하여 미해결 문제에 등록했습니다").
   - **다음 세션 우선순위**: 다음 세션 시작 시 `HANDOVER.md`의 "미해결 문제" 섹션을 확인하고, 사용자와 함께 해결 우선순위를 정함.
10. **단계 완료 시 작업 여력 보고 (강제)**: 각 단계(규칙 0-1의 1단계) 완료 시, 사용자에게 현재 작업 여력을 일반 용어로 보고. 기술 용어("컨텍스트", "토큰") 대신 "작업 여력" 등 일반 용어 사용 (사용자 의사소통 규칙 4 준수). 규칙 2의 내부 점검 결과를 사용자에게 전달하는 단계.
    - **보고 예시**:
      - 여력 충분: "이번 단계 완료. 작업 여력 충분 — 커밋 + 핸드오버 갱신 진행해도 됩니다."
      - 여력 적음: "이번 단계 완료. 작업 여력 적음 — 커밋 + 핸드오버 갱신 후 세션 종료 권장합니다."
    - **보고 후 진행**: 커밋 + `HANDOVER.md` 갱신 진행 여부를 사용자 승인(규칙 6)받아 진행. 승인 전 커밋/핸드오버 갱신 금지.
    - **세션 종료 시 보고와 구분**: 규칙 5(세션 종료 시 진행 상태 + 다음 단계 전달)은 세션 종료 시점 보고. 본 규칙 10은 매 단계 완료 시점 보고. 두 규칙은 시점이 다르며 모두 준수.
