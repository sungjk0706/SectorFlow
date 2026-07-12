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
- 전체 원칙 목록은 `docs/architecture_audit_plan.md` 섹션 2의 평가 기준표 참조.

### Code Removal Rules

함수, 변수, 클래스, 모듈 등 코드를 제거할 때 다음을 반드시 함께 수행:

1. **참조 주석 정리**: 제거된 코드를 참조하는 모든 주석, docstring, 파일 헤더 설명을 함께 수정 또는 제거.
2. **불일치 금지**: 주석과 코드의 불일치는 원칙10(SSOT) 및 원칙21(사용자 투명성) 위반. 제거된 함수가 docstring에 남아 있으면 신규 코드에서 해당 함수를 찾는 오류 발생.
3. **검색 범위**: 제거된 코드의 이름으로 전체 코드베이스(backend + frontend + tests + docs)를 검색하여 잔존 참조 확인. 단, 문제 기록(`architecture_audit_plan.md` 섹션 7)의 역사적 로그는 유지.
4. **테스트 파일 포함**: 테스트 파일의 docstring, 헤더 주석도 코드와 일치해야 함.

---

## 섹션3. 수행 규칙 (모든 작업 시 준수)

### Investigation & Problem Solving Rules

0. **Approval before editing.** Before modifying any code for debugging, new implementation, or improvements, always present a clear plan and get explicit user approval first. Do not make any file edits until the user explicitly says "진행해", "수정해", "구현해", "go", or similar. If the user only asks for analysis or reporting, do not edit.
1. No guessing. Base all conclusions on actual code, search results, logs, and browser reproducible behavior.
2. Solve the root cause, not the symptom. No temporary fixes, fallbacks, `!important`, `as any`, or "let's do this for now" workarounds.
3. One small step at a time. Modify one file or block at a time, then verify.
4. After any change, run at least one of: type check, lint, build, test, or runtime start.
5. For backend changes, runtime startup check is mandatory: start `.venv/bin/python main.py`, check logs, wait 10–30s, then terminate and confirm no leftover processes.
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
2. **단계 완료 시 컨텍스트 점검**: 각 작은 단계 완료 시 현재 컨텍스트 사용량을 점검. 사용량이 높아 다음 단계에서 오류 가능성이 있다고 판단되면, 다음 단계 진행 전 `HANDOVER.md`에 현재 진행 상태를 갱신하여 만일의 중단에 대비.
3. **사전 종료 권한**: 에이전트는 작업 중 컨텍스트 사용량이 많아져 오류 가능성이 있다고 판단되면, 현재 진행 상태를 `HANDOVER.md`에 기록하고 사용자에게 보고한 후 세션을 종료할 수 있음.
4. **HANDOVER.md 기록 의무**: 세션 종료 전 반드시 다음을 기록:
   - 완료된 작업 요약 (파일명, 테스트 수, 검증 결과)
   - 진행 중인 작업의 현재 단계 (어디까지 했고, 어디서부터 이어하면 되는지)
   - 다음 세션에서 수행해야 할 구체적 항목
5. **사용자 보고**: 세션 종료 시 사용자에게 진행 상태와 다음 단계를 명확히 전달.
6. **다음 세션 연속성**: 다음 세션에서는 `HANDOVER.md`를 먼저 확인하여 이어서 작업 진행.
7. **완료 작업 정리**: 새 세션 시작 시 `HANDOVER.md`의 "직전 완료 작업" 섹션에서 최근 1~2건만 유지하고 나머지 과거 완료 작업은 삭제. git history에 이미 기록되어 있으므로 중복 누적 방지. "현재 상태"와 "다음 단계" 섹션도 최신 상태로 업데이트.
8. **HANDOVER.md 수정 원칙 (read-before-write)**: `HANDOVER.md` 수정 시 반드시 read 먼저 수행. 기존 내용을 보존한 후 병합. write 도구로 덮어쓰기 금지 — 기존 섹션 내용을 읽어 확인한 후에만 수정/추가. 실수로 기존 내용을 삭제하는 사고 방지.
