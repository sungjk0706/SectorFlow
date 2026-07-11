# SectorFlow Agent Rules

## Project Overview

SectorFlow is a local real-time stock auto-trading web app for one person.

- Backend: FastAPI + Python + aiosqlite (SQLite `backend/data/stocks.db`)
- Frontend: TypeScript (Vanilla)
- Pipeline: After market close → download 5-day bars → filter by trading amount → group by custom sector → sector screening → sector ranking → top N sectors → buy candidates → buy (market order) → hold list → sell
- Key frontend state: `frontend/src/stores/store.ts`

## Safety Rules (Always Apply)

1. Never delete or overwrite `backend/data/stocks.db` or any `*.db` files directly.
2. Before any DB schema change or migration, create a timestamped backup of `stocks.db`, `stocks.db-shm`, and `stocks.db-wal`.
3. Trading code must stay in simulation/test mode unless the user explicitly confirms real money and you warn them.
4. Do not hardcode broker API keys, tokens, or credentials.
5. Do not run `sudo`, `rm -rf`, `curl`, `wget`, or `sqlite3` without user approval.
6. Do not edit `~/.bashrc`, `~/.zshrc`, or system paths.

## Investigation & Problem Solving Rules

0. **Approval before editing.** Before modifying any code for debugging, new implementation, or improvements, always present a clear plan and get explicit user approval first. Do not make any file edits until the user explicitly says "진행해", "수정해", "구현해", "go", or similar. If the user only asks for analysis or reporting, do not edit.
1. No guessing. Base all conclusions on actual code, search results, logs, and browser reproducible behavior.
2. Solve the root cause, not the symptom. No temporary fixes, fallbacks, `!important`, `as any`, or "let's do this for now" workarounds.
3. One small step at a time. Modify one file or block at a time, then verify.
4. After any change, run at least one of: type check, lint, build, test, or runtime start.
5. For backend changes, runtime startup check is mandatory: start `.venv/bin/python main.py`, check logs, wait 10–30s, then terminate and confirm no leftover processes.
6. Report using: problem symptom, root cause (file:line), fix, impact, verification.
7. Do not commit or update `HANDOVER.md` without user approval.

## Code Removal Rules

함수, 변수, 클래스, 모듈 등 코드를 제거할 때 다음을 반드시 함께 수행:

1. **참조 주석 정리**: 제거된 코드를 참조하는 모든 주석, docstring, 파일 헤더 설명을 함께 수정 또는 제거.
2. **불일치 금지**: 주석과 코드의 불일치는 원칙10(SSOT) 및 원칙21(사용자 투명성) 위반. 제거된 함수가 docstring에 남아 있으면 신규 코드에서 해당 함수를 찾는 오류 발생.
3. **검색 범위**: 제거된 코드의 이름으로 전체 코드베이스(backend + frontend + tests + docs)를 검색하여 잔존 참조 확인. 단, 문제 기록(`architecture_audit_plan.md` 섹션 7)의 역사적 로그는 유지.
4. **테스트 파일 포함**: 테스트 파일의 docstring, 헤더 주석도 코드와 일치해야 함.

## Forbidden Words

"아마도", "아마", "대부분", "일반적으로", "일단", "우선", "임시로", "추후 개선", "나중에 리팩토링", "제 생각에는"

## Allowed Words

"파일 A의 n번째 줄에서 확인됨", "검색 결과 해당 클래스가 남아 있음", "빌드 로그에서 타입 오류가 확인됨", "이 부분은 아직 확인 필요"

## Skill Auto-Invocation

The user is a beginner and does not know which skill to use. Automatically invoke the appropriate skill based on the user's request. Do not wait for the user to ask for a specific skill.

- **Bug, debugging, problem analysis, root cause**: invoke `/problem-solve`
- **Backend code change or API error**: invoke `/backend-fix`
- **Frontend UI, page, or build error**: invoke `/frontend-fix`
- **DB schema change, migration, or table modification**: invoke `/db-backup` first, then proceed
- **Trading logic, broker API, order code**: invoke `/safe-trade` first
- **New logic implementation**: invoke `/problem-solve` for planning, then `/backend-fix` or `/frontend-fix` for implementation

When in doubt, invoke `/problem-solve` first. Always follow the rules in this file even when a skill is not explicitly invoked.

## Context Management Rules

1. **사전 종료 권한**: 에이전트는 작업 중 컨텍스트 사용량이 많아져 오류 가능성이 있다고 판단되면, 현재 진행 상태를 `HANDOVER.md`에 기록하고 사용자에게 보고한 후 세션을 종료할 수 있음.
2. **HANDOVER.md 기록 의무**: 세션 종료 전 반드시 다음을 기록:
   - 완료된 작업 요약 (파일명, 테스트 수, 검증 결과)
   - 진행 중인 작업의 현재 단계 (어디까지 했고, 어디서부터 이어하면 되는지)
   - 다음 세션에서 수행해야 할 구체적 항목
3. **사용자 보고**: 세션 종료 시 사용자에게 진행 상태와 다음 단계를 명확히 전달.
4. **다음 세션 연속성**: 다음 세션에서는 `HANDOVER.md`를 먼저 확인하여 이어서 작업 진행.
5. **완료 작업 정리**: 새 세션 시작 시 `HANDOVER.md`의 "직전 완료 작업" 섹션에서 최근 1~2건만 유지하고 나머지 과거 완료 작업은 삭제. git history에 이미 기록되어 있으므로 중복 누적 방지. "현재 상태"와 "다음 단계" 섹션도 최신 상태로 업데이트.
