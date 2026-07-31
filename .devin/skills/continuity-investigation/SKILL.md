---
name: continuity-investigation
description: 대규모 전수 조사를 세션 단위로 분할하고 상태 파일로 이어가는 연속성 루프 스킬
allowed-tools:
  - read
  - grep
  - glob
  - write
  - edit
  - exec
---

## 목적

한 세션에서 끝내지 못할 대규모 전수 조사(예: 전 파일 하드코딩 탐지, 전 API 경로 검증, Deprecated 사용 전수 조사)를
세션 단위로 분할하고, `.devin/state/investigation_status.json` 상태 파일로 진행 상황을 저장·복원하여
다음 세션에서 중단 지점부터 이어 진행한다. 모든 대상 조사가 완료되면 `FINAL_REPORT.md`를 자동 생성한다.

## 사용자 전제 (필수 — AGENTS.md 섹션3 규칙0 준수)

- **승인 전 코드 수정 절대 금지.** 본 스킬은 "조사(읽기/grep/glob)"가 주 목적이다. 조사 중 발견된 문제의 "수정"은
  본 스킬 범위 밖 — 완료 후 `problem-solve`/`backend-fix`/`frontend-fix` 스킬로 위임.
- 사용자 소통·보고 의무: AGENTS.md 섹션3 "사용자 의사소통 규칙"(1~5항), 규칙 0-8(보고 의무), 규칙 0-9(오류 알림) 준수.
- **P24 단순성**: 복잡한 자동화 프레임워크 사용 금지. 파일 기반 단순 상태 관리(JSON 1개)만 사용.
- **안전 규칙 준수**: `*.db` 파일 삭제/덮어쓰기 금지, `sudo`/`rm -rf`/`curl`/`wget`/`sqlite3` 사용자 승인 없이 실행 금지.

## 핵심 파일 (P10 SSOT)

| 파일 | 역할 | git 추적 |
|------|------|----------|
| `.devin/state/investigation_status.json` | 조사 진행 상황 단일 진실 소스 | 제외 |
| `.devin/state/continue.md` | 다음 세션 자동 실행용 프롬프트 (훅 스크립트가 생성) | 제외 |
| `.devin/state/STOP` | 비상 정지 신호 파일 (존재 시 루프 즉시 종료) | 제외 |
| `.devin/scripts/continuity-loop.sh` | SessionEnd 훅이 호출하는 자동 재실행 스크립트 | 추적 |
| `.devin/hooks.v1.json` | SessionEnd 훅 설정 | 추적 |
| `docs/investigation_report_<slug>_<date>.md` | 최종 보고서 (완료 시 1회 생성) | 추적 |

## 상태 파일 구조 (investigation_status.json)

```json
{
  "topic": "조사 주제 (사용자 지정)",
  "topic_slug": "파일명용 슬러그 (영문 소문자+하이픈)",
  "started_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "status": "in_progress | done | aborted",
  "scope": {
    "root": "조사 루트 디렉터리 (절대경로)",
    "glob": "파일 패턴 (예: **/*.py)",
    "total_files": 0,
    "exclude": ["제외할 경로 패턴 선택"]
  },
  "checklist": "각 파일에 적용할 조사 기준 (자연스러운 문장)",
  "batch_size": 8,
  "completed": [],
  "remaining": [],
  "in_progress": null,
  "findings": [
    {
      "file": "절대경로",
      "line": 0,
      "severity": "high | mid | low",
      "desc": "발견 내용 설명",
      "evidence": "증거 스니펫 (코드 일부)"
    }
  ],
  "session_count": 0,
  "max_sessions": 30,
  "next_action": "다음 세션에서 할 작업 설명"
}
```

필드 규칙:
- `completed` + `remaining` + `findings` 3개가 SSOT. 절대 중복·분산 관리 금지 (P10).
- `completed`에 들어간 파일은 `remaining`에서 반드시 제거 (교집합 0 유지).
- `findings`는 세션별로 덮어쓰지 말고 누적 (append).
- `session_count`는 매 세션 시작 시 +1. `max_sessions` 초과 시 자동 중단 (비용 폭주 방지).
- `status`가 `done`이면 재실행 금지.

## 절차

### 1. 세션 시작 — 상태 복원 또는 새 조사 초기화

#### 1-1. 기존 상태 복원 (우선)

1. `.devin/state/investigation_status.json` 존재 + `status == "in_progress"`:
   - 파일 읽기 → 사용자에게 보고:
     > "이전 조사가 진행 중입니다. 주제: <topic>. 완료 <completed 길이>/<total_files>, 남은 <remaining 길이>개,
     > 세션 <session_count>회차. 이어서 진행할까요?"
   - 사용자가 "이어서 해줘" / "계속" / "진행해" 응답 → 2번(배치 조사)으로 이동.
   - 사용자가 "새로 시작" / "취소" 응답 → 기존 상태 파일을 `.bak`으로 백업 후 새 조사 초기화(1-2번)로.
   - **`session_count >= max_sessions`인 경우 자동 중단**: 사용자에게 "최대 세션 수 도달, 강제 중단" 보고 후 종료.
2. 파일 없거나 `status == "done"`: 1-2번(새 조사 초기화)으로.

#### 1-2. 새 조사 초기화

1. 사용자에게 조사 주제·범위·조사 기준 확인 (사전조사로 확정 불가한 항목만 질문 — problem-solve 섹션 1-1 기준):
   - 조사 주제 (예: "하드코딩된 API 키 전수 조사")
   - 조사 범위: 루트 디렉터리 + glob 패턴 (기본값 제안: `backend/app` + `**/*.py`)
   - 조사 기준(체크리스트): 각 파일에서 무엇을 찾을지 자연어로 (예: "API 키, 토큰, 비밀번호가 코드에 직접 적혀 있는지")
   - 제외 경로 (선택): `__pycache__`, `.venv`, `node_modules` 등은 기본 제외
2. 대상 파일 전체 목록 생성 (`glob` 도구 사용):
   - 제외 패턴 적용 후 최종 목록 산출
   - `total_files` 기록
3. `batch_size` 결정:
   - 기본 8개
   - 대상 파일 평균 길이 500줄 초과 → 4개로 축소
   - 대상 파일 평균 길이 100줄 미만 → 12개로 확장
4. `investigation_status.json` 생성 (위 구조 사용, `completed: []`, `remaining: [전체 목록]`).
5. `.devin/state/STOP` 파일이 존재하면 삭제 (새 조사 시작 시 이전 STOP 신호 초기화).
6. 사용자에게 보고: "조사 대상 <N>개 파일, 배치 크기 <batch_size>. 첫 배치 시작합니다."

### 2. 배치 조사 루프 (한 세션 내)

각 배치마다 다음을 수행:

#### 2-1. 배치 추출
- `remaining`에서 `batch_size`개를 꺼내 `in_progress` 배열로 이동 (또는 파일별 순차 처리).
- 상태 파일 즉시 갱신 (`in_progress` 필드).

#### 2-2. 파일별 조사
각 파일에 대해:
1. `read` 도구로 파일 읽기 (파일이 너무 크면 `offset`/`limit`로 분할 읽기).
2. `grep` 도구로 패턴 사전 스캔 (조사 기준에 해당하는 패턴).
3. 조사 기준(체크리스트) 적용:
   - 각 항목별로 파일 내 해당 여부 확인
   - 발견 시 `findings`에 누적 추가 (file/line/severity/desc/evidence)
4. 심각도 분류 기준:
   - `high`: 보안 위험 (하드코딩 비밀키, SQL 인젝션), 데이터 손실 위험
   - `mid`: 아키텍처 원칙 위반 (P10/P20/P22 위반), Deprecated API 사용
   - `low`: 스타일/네이밍/경미한 일관성 위반

#### 2-3. 배치 완료 처리
1. 조사 완료한 파일들을 `in_progress`에서 `completed`로 이동.
2. `remaining`에서 제거 (교집합 0 유지 — P10).
3. `findings`에 새 발견 사항 누적.
4. `updated_at` 갱신.
5. `next_action` 갱신 (예: "다음 배치: <남은 첫 파일>부터 <batch_size>개").
6. 상태 파일 저장 (`write` 도구).
7. **백업**: `investigation_status.json.bak`으로 복사 (손상 대비).

#### 2-4. 세션 양도 판단
매 배치 종료 후 다음 중 하나면 세션 종료:
- `remaining` 길이 == 0 → 3번(완료 처리)으로.
- 이번 세션에서 처리한 배치 수 >= 3 → 사용자에게 "이번 세션 배치 3회 완료, 다음 세션으로 양도" 보고 후 종료.
- 사용자가 중단 지시 → `status: "aborted"`로 저장 후 종료.
- AI 자가 판단: "이번 세션에서 추가 파일 읽으면 컨텍스트 위험" → 상태 저장 후 종료.

### 3. 완료 처리 (remaining == 0)

#### 3-1. 완료 판정
- `remaining` 길이 == 0 && `status != "done"` → 완료.
- 조기 보고서 작성 금지 (반드시 0 확인 후).

#### 3-2. 최종 보고서 작성
경로: `docs/investigation_report_<topic_slug>_<YYYYMMDD>.md`

구조:
```markdown
# 전수 조사 보고서: <topic>

- 조사 일시: <started_at> ~ <updated_at>
- 조사 범위: <root> / <glob> / 총 <total_files>파일
- 세션 수: <session_count> / 최대 <max_sessions>
- 조사 기준: <checklist>

## 요약
- 발견 문제: <N>건 (high <a> / mid <b> / low <c>)
- 조사 완료 파일: <completed 길이> / <total_files>

## 심각도별 발견 목록

### High (<a>건)
- **<file>:<line>** — <desc>
  ```
  <evidence>
  ```

### Mid (<b>건)
...

### Low (<c>건)
...

## 권장 후속 작업
1. <high 심각도 문제 우선 수정 — problem-solve/backend-fix/frontend-fix 스킬로 위임>
2. ...

## 원본 데이터
- 상세 조사 기록: `.devin/state/investigation_status.json`
- 백업: `.devin/state/investigation_status.json.bak`
```

#### 3-3. 상태 파일 종료 처리
- `status: "done"`으로 변경.
- `.devin/state/STOP` 파일 생성 (훅 루프 종료 신호 — `continuity-loop.sh`가 감지하여 재실행 중단).
- `updated_at` 갱신.
- 사용자에게 보고: "조사 완료. 보고서: `docs/investigation_report_<slug>_<date>.md`. 발견 <N>건."

### 4. 세션 종료 시 자동 이어하기 (훅 연동)

본 스킬은 세션 종료 시 다음을 수행한다 (훅 스크립트 `.devin/scripts/continuity-loop.sh`와 연동):

1. 세션 종료 전 마지막 상태 저장 (2-3번에서 이미 수행).
2. `remaining > 0` && `status == "in_progress"`인 경우:
   - `.devin/state/continue.md` 자동 생성 (다음 세션용 프롬프트):
     ```markdown
     investigation_status.json을 읽고 중단된 지점부터 다음 배치를 조사해줘.
     continuity-investigation 스킬 절차를 따라. 주제: <topic>.
     ```
3. 세션 종료 → `SessionEnd` 훅이 `continuity-loop.sh` 실행 → 자동으로 `devin -p --prompt-file continue.md` 호출.
4. 사용자 개입 없이 다음 세션 시작 → 1-1번(상태 복원)으로 자동 진입.

**비상 정지**: 사용자가 `touch .devin/state/STOP` 실행하거나 "그만해"라고 하면:
- 즉시 `status: "aborted"` 저장.
- `STOP` 파일 생성.
- 훅 스크립트가 `STOP` 감지 시 재실행 중단.

## 안전장치 정리

| 위험 | 대응 |
|------|------|
| 무한 루프 | `STOP` 파일 1개 생성으로 즉시 중단 |
| 상태 파일 손상 | 매 배치마다 `.bak` 백업 |
| 세션 크래시 | 다음 세션 시작 시 `.bak`에서 복구 시도 |
| 비용 폭주 | `max_sessions` (기본 30) 초과 시 자동 중단 |
| 중복 조사 | `completed`/`remaining` 교집합 0 유지 (P10) |
| 조기 보고서 | `remaining == 0` 확인 후에만 작성 |
| 권한 남용 | 본 스킬은 조사(읽기) 전용. 수정은 별도 스킬 위임 |

## 기존 워크플로우와 충돌 회피

| 기존 | 본 스킬 | 구분 |
|------|---------|------|
| `problem-solve` | 단일 세션 근본 해결 | 본 스킬은 "대규모 전수 조사" 전용 |
| `backend-fix`/`frontend-fix` | 수정 절차 | 본 스킬은 조사만, 수정은 기존 스킬에 위임 |
| 다단계 워크플로우 (설계→태스크→구현) | 신규 기능 구현 | 본 스킬은 조사 특화 |
| `HANDOVER.md` | 세션 종료 보고용 | 본 스킬 상태는 `.devin/state/` 별도 보관 |

## 사용 예시

**최초 시작 (사용자 1줄):**
```
backend/app 전체에서 하드코딩된 API 키·토큰 전수 조사해줘. 연속성 루프로.
```

**이어하기 (자동 — 훅이 처리, 사용자 개입 0):**
- 세션 종료 → 훅 → 다음 세션 자동 실행 → 반복

**수동 이어하기 (훅 미사용 시):**
```
이어서 해줘
```

**비상 정지:**
```
touch .devin/state/STOP
```
또는
```
그만해
```

**완료 (자동):**
- `FINAL_REPORT.md` 생성 후 안내
