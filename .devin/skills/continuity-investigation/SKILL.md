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

> **도구 사용 범위 (본 스킬은 조사 전용)**: `write`/`edit`은 상태 파일(`.devin/state/investigation_status.json` 및 `.bak`)·자동 이어하기 프롬프트(`.devin/state/continue.md`)·비상 정지 신호(`.devin/state/STOP`)·최종 보고서(`docs/조사보고서/*.md`)에만 사용. **코드 수정·설정 변경·스킬 파일 변경에 write/edit 사용 금지** — 발견된 문제의 수정은 problem-solve/backend-fix/frontend-fix 스킬로 위임. `exec`는 `glob`/`grep`/`ls`/`cp`(상태 파일 백업) 계열만 사용하며 `sudo`/`rm -rf`/`curl`/`wget`/`sqlite3`는 사용자 승인 없이 실행 금지(안전 규칙 5).

## 목적

한 세션에서 끝내지 못할 대규모 전수 조사(예: 전 파일 하드코딩 탐지, 전 API 경로 검증, Deprecated 사용 전수 조사)를
세션 단위로 분할하고, `.devin/state/investigation_status.json` 상태 파일로 진행 상황을 저장·복원하여
다음 세션에서 중단 지점부터 이어 진행한다. 모든 대상 조사가 완료되면 `FINAL_REPORT.md`를 자동 생성한다.

## 사용자 전제 (필수 — docs/절차규칙/절차규칙_조사_상세.md 규칙 0 준수)

> **공통 전제 (승인 전 수정 금지·사용자 소통·보고·오류 알림 의무·작업 시작 전 아키텍처 판정 필수·완료 보고 봉인)**: problem-solve 스킬 "사용자 전제" 섹션 (.devin/skills/problem-solve/SKILL.md) 참조. 단, 본 스킬은 조사 전용이므로 "승인 전 수정 금지"는 자동 충족(코드 수정 도구 사용 범위는 상단 "도구 사용 범위" 참조).

**본 스킬 특화 추가 항목**:
- **조사-수정 분리 (핵심)**: 본 스킬은 "조사(읽기/grep/glob)"가 주 목적. 조사 중 발견된 문제의 "수정"은 본 스킬 범위 밖 — 완료 후 `problem-solve`/`backend-fix`/`frontend-fix` 스킬로 위임.
- **완료 보고 봉인 (조사 특화)**: 전수 조사가 끝났거나 한 세션의 조사 단계가 끝난 뒤에는 다음 조사나 후속 작업을 제안·질문·승인 요청하지 않는다. 남은 조사는 상태 파일에만 기록하고 세션을 마친다.
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
| `docs/조사보고서/<주제>_<날짜>.md` | 최종 보고서 (완료 시 1회 생성, 전체 작업 완료 시 규칙 10에 따라 삭제) | 추적 |

## 상태 파일 구조 (investigation_status.json)

필드 규칙 (상세 JSON 구조는 하단 "참조" 섹션 참조):
- `completed` + `remaining` + `findings` 3개가 SSOT. 절대 중복·분산 관리 금지 (P10).
- `completed`에 들어간 파일은 `remaining`에서 반드시 제거 (교집합 0 유지).
- `findings`는 세션별로 덮어쓰지 말고 누적 (append).
- `session_count`는 매 세션 시작 시 +1. `max_sessions` 초과 시 자동 중단 (비용 폭주 방지).
- `status`가 `done`이면 재실행 금지.

## 절차

### 1. 세션 시작 — 상태 복원 또는 새 조사 초기화

#### 1-1. 기존 상태 복원 (우선)

- 상태 파일 존재 + `status == "in_progress"` → 파일 읽고 사용자에게 진행 상황 보고 후 "이어서 진행할까요?" 확인.
  - "이어서" 응답 → 2번(배치 조사)으로.
  - "새로 시작"/"취소" 응답 → 기존 상태 `.bak` 백업 후 1-2번으로.
  - **`session_count >= max_sessions` → 자동 중단**: "최대 세션 수 도달, 강제 중단" 보고 후 종료.
  - 상세 사용자 응답 처리는 하단 "참조" 섹션 참조.
- 파일 없거나 `status == "done"` → 1-2번(새 조사 초기화)으로.

#### 1-2. 새 조사 초기화

1. 사용자에게 조사 주제·범위·조사 기준 확인 (사전조사로 확정 불가한 항목만 질문 — problem-solve 섹션 1-1 기준):
   주제, 루트+glob 패턴, 체크리스트(자연어), 제외 경로(선택).
2. 대상 파일 전체 목록 생성 (`glob`), 제외 패턴 적용, `total_files` 기록.
3. `batch_size` 결정 (기본 8, 평균 길이별 4/8/12 조정 — 상세 기준은 하단 "참조" 섹션).
4. `investigation_status.json` 생성 (`completed: []`, `remaining: [전체 목록]`).
5. `.devin/state/STOP` 파일이 존재하면 삭제 (이전 STOP 신호 초기화).
6. 사용자에게 보고: "조사 대상 <N>개 파일, 배치 크기 <batch_size>. 첫 배치 시작합니다."

### 2. 배치 조사 루프 (한 세션 내)

각 배치마다:

#### 2-1. 배치 추출
- `remaining`에서 `batch_size`개를 `in_progress`로 이동. 상태 파일 즉시 갱신.

#### 2-2. 파일별 조사
각 파일에 대해: `read`로 읽기(큰 파일은 분할) → `grep`으로 패턴 사전 스캔 → 체크리스트 적용 → 발견 시 `findings` 누적 추가(file/line/severity/desc/evidence).
- 심각도 분류: `high`(보안·데이터 손실) / `mid`(아키텍처 원칙 위반·Deprecated) / `low`(스타일·네이밍). 상세 분류 기준과 발생 확률 부가 고려는 하단 "참조" 섹션 참조.

#### 2-3. 배치 완료 처리
1. 조사 완료 파일 `in_progress` → `completed` 이동, `remaining`에서 제거 (교집합 0 — P10).
2. `findings` 누적, `updated_at`·`next_action` 갱신, 상태 파일 저장.
3. **백업**: `investigation_status.json.bak`으로 복사 (손상 대비).

#### 2-4. 세션 양도 판단
매 배치 종료 후 다음 중 하나면 세션 종료 (상세 판단 조건은 하단 "참조" 섹션):
- `remaining` 길이 == 0 → 3번(완료 처리)으로.
- 이번 세션 배치 수 >= 3 → "다음 세션으로 양도" 보고 후 종료.
- 사용자 중단 지시 → `status: "aborted"` 저장 후 종료.
- AI 자가 판단: 컨텍스트 위험 → 상태 저장 후 종료.

### 3. 완료 처리 (remaining == 0)

#### 3-1. 완료 판정
- `remaining` 길이 == 0 && `status != "done"` → 완료. 조기 보고서 작성 금지 (반드시 0 확인 후).

#### 3-2. 최종 보고서 작성
경로: `docs/조사보고서/<주제>_<YYYYMMDD>.md`
구조: 제목/조사 일시/범위/세션 수/기준 → 요약(발견 건수·심각도별) → 심각도별 발견 목록(high/mid/low) → 권장 후속 작업(수정은 problem-solve/backend-fix/frontend-fix 위임) → 원본 데이터 경로.

#### 3-3. 상태 파일 종료 처리
- `status: "done"`으로 변경.
- `.devin/state/STOP` 파일 생성 (훅 루프 종료 신호 — `continuity-loop.sh`가 감지하여 재실행 중단).
- `updated_at` 갱신.
- 사용자에게 보고: "조사 완료. 보고서: `docs/조사보고서/<주제>_<날짜>.md`. 발견 <N>건."

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

---

## 참조 (상세 필요 시)

> 본 섹션은 본문 절차의 상세 기준을 보관한다. 핵심 흐름은 본문만으로 충분하며, 세부 판단이 필요할 때만 본 섹션을 참조한다.

### 상태 파일 JSON 전체 구조

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

### 1-1 상세 사용자 응답 처리

- 사용자가 "이어서 해줘" / "계속" / "진행해" 응답 → 2번(배치 조사)으로 이동.
- 사용자가 "새로 시작" / "취소" 응답 → 기존 상태 파일을 `.bak`으로 백업 후 새 조사 초기화(1-2번)로.

### batch_size 산정 세부 기준

- 기본 8개
- 대상 파일 평균 길이 500줄 초과 → 4개로 축소
- 대상 파일 평균 길이 100줄 미만 → 12개로 확장

### 심각도 분류 상세 기준 (영향도 1축 + 발생 확률 부가 고려)

- `high`: 보안 위험 (하드코딩 비밀키, SQL 인젝션), 데이터 손실 위험
- `mid`: 아키텍처 원칙 위반 (P10/P20/P22 위반), Deprecated API 사용
- `low`: 스타일/네이밍/경미한 일관성 위반
- **발생 확률 부가 고려 (같은 영향도 내 우선순위 조정용)**:
  - 보안 위험이나 실제 악용/발생 가능성 낮음 (예: 내부 전용 함수, 입력 검증 이미 존재) → 영향 high 유지하되 `findings`의 `desc`에 "발생 확률 낮음" 부기
  - 보안 위험이고 실제 악용 가능 (예: 외부 입력 직접 노출, 검증 없음) → `desc`에 "발생 확률 높음" 부기
  - 발생 확률은 보고서 정렬/후속 작업 우선순위 판단용 — 기존 high/mid/low 등급 자체는 유지 (P24 단순성 — 별도 점수 체계 도입 금지)

### 세션 양도 판단 세부 조건

매 배치 종료 후 다음 중 하나면 세션 종료:
- `remaining` 길이 == 0 → 3번(완료 처리)으로.
- 이번 세션에서 처리한 배치 수 >= 3 → 사용자에게 "이번 세션 배치 3회 완료, 다음 세션으로 양도" 보고 후 종료.
- 사용자가 중단 지시 → `status: "aborted"`로 저장 후 종료.
- AI 자가 판단: "이번 세션에서 추가 파일 읽으면 컨텍스트 위험" → 상태 저장 후 종료.
