# Lazy Authentication 리팩토링 설계안

> **상태**: 설계 완료 / 구현 승인 대기
> **작성일**: 2026-07-30
> **범위**: `_get_all_tokens_async()` eager 토큰 발급 → 활성 broker 1개만 인증하는 Lazy Authentication 구조로 축소
> **범위 외**: Hot-Swap Broker Runtime Manager, 기능별 라우팅 개편, `MUST_SAME_BROKER_PAIRS` 정책 변경, UI/DB/설정 스키마 변경

---

## 1. 현재 코드 기반 사실 확인

코드 직접 추적으로 확정한 현재 아키텍처 사실.

| 항목 | 코드 위치 | 확인 내용 |
|------|----------|-----------|
| 사용자 설정 | `frontend/src/pages/general-settings-api-settings-tab.ts:231` | `saveSection({ broker: val })` — 단일 `broker` 키만 저장 |
| 백엔드 정규화 | `backend/app/core/engine_settings.py:312-320` | `_normalize_broker_config`가 websocket/order/sector/auth 모두 `broker`로 수렴 |
| Eager 발급 | `backend/app/services/engine_loop.py:47-109` | `_get_all_tokens_async`가 `broker_config` + `confirmed_data_broker`에서 API 키 있는 모든 증권사 병렬 발급 |
| Startup 소비 | `backend/app/services/engine_loop.py:236` | `broker_tokens.get(broker_nm)`, `broker_nm = settings["broker"]` — 활성 broker만 조회 |
| 상태 조회 | `backend/app/services/engine_lifecycle.py:185` | `items()` 순회, 존재하는 토큰만 — "모든 broker 필수" 전제 없음 |
| 배치 자체 Lazy Auth | `backend/app/services/market_close_pipeline.py:1092-1102, 1144-1147` | 자체 AuthProvider 생성 → 필요 시 발급 → 재사용 → `pop` 정리 |
| 배치 두 번째 경로 | `backend/app/services/market_close_pipeline.py:1276-1277, 1474` | 동일 패턴 (20:30 통합 조회) |
| 강등 경로 | `backend/app/services/engine_loop.py:239-242` | 토큰 부재 시 "시세 전용 모드로 기동", 크래시 아님 |

### 핵심 검증: `confirmed_data_broker` 토큰의 startup 외 소비자

`broker_tokens`의 모든 비테스트 소비 지점 추적 결과:

- `engine_loop.py:236` — `broker_tokens.get(broker_nm)`, `broker_nm = settings["broker"]` (활성 broker만)
- `engine_lifecycle.py:185` — `items()` 순회 (존재하는 것만)
- `market_close_pipeline.py:1099/1145/1277/1474` — 배치 자체 발급·정리

**결론: `confirmed_data_broker` 토큰을 `broker_tokens`에서 읽는 비배치 startup 소비자는 존재하지 않는다.**

---

## 2. 이번 변경의 근본 원인

`_get_all_tokens_async`의 발급 대상 계산이 "실제 사용 여부"가 아니라 "API 키 존재 여부" 기준이다 (`engine_loop.py:70-76`).

정규화로 인해 `broker_config`는 사실상 `{broker}`로 수렴하지만, `confirmed_data_broker`가 별도 증권사일 경우 startup에서 불필요한 토큰을 발급한다. 런타임은 "모든 broker 토큰 존재"를 전제하지 않으므로(검증 완료), 이 eager 발급은 근본적으로 불필요하다.

**해결 방향**: 발급 대상을 "API 키가 있는 모든 증권사"에서 "startup에서 실제 사용하는 활성 broker 1개"로 축소. 임시 조건(`if broker_name != confirmed_data_broker`)이 아닌 근본 원인 해결 (P20 부합).

---

## 3. 최종 권장 아키텍처

```
앱 시작
  ↓
설정 로드
  ↓
broker 확인
  ↓
{broker} 토큰 1개만 발급
  ↓
실시간/주문 엔진 시작

장마감 배치
  ↓
자체 Lazy Auth 유지 (기존 broker_tokens 재사용 우선)
  ↓
5일봉/확정 시세 다운로드
  ↓
배치 토큰/세션 정리 (pop)

> **참고**: 배치가 실제로 어느 broker를 사용하는지(`confirmed_data_broker` 설정 vs `_broker_name = "kiwoom"` 하드코딩)는 섹션 13의 별도 이슈 조사 대상. 이번 작업에서는 배치 자체 Lazy Auth 구조를 유지하는 것만 확정.
```

두 인증 생명주기(startup 인증 / 배치 인증)를 억지로 합치지 않고 각자 책임 영역에서 관리 (P24). 새로운 전역 `LazyAuthManager` 도입 없음.

증권사 변경 시 `stop_engine → reset_broker_session_state → reset_router → start_engine` 유지 (이번 범위 밖).

---

## 4. Startup 인증 대상 확정 (질문 A)

**Startup 인증 대상 = `{broker}` 1개.**

근거: startup 비배치 소비자는 `engine_loop.py:236`의 `broker_tokens.get(broker_nm)` 단일 지점이며, `broker_nm = str(settings["broker"]).lower().strip()` (`engine_loop.py:178`). 반례 없음.

---

## 5. `confirmed_data_broker` 처리 방식 확정 (질문 B)

**`confirmed_data_broker`는 startup에서 완전히 제외하고 `market_close_pipeline.py` 자체 Lazy Auth에 위임.**

근거:
- `confirmed_data_broker` 토큰을 `broker_tokens`에서 읽는 비배치 startup 소비자가 코드 검색 결과 존재하지 않음
- 배치 경로는 이미 `if _broker_name not in broker_tokens` 조건으로 자체 발급을 처리 (`market_close_pipeline.py:1098-1099`)
- startup에서 미리 발급하지 않아도 배치 시작 시 자체 발급됨

---

## 6. 변경 파일 목록

| 파일 | 변경 유형 | 범위 |
|------|----------|------|
| `backend/app/services/engine_loop.py` | 수정 | `_get_all_tokens_async` 발급 대상 축소 (`broker_config` + `confirmed_data_broker` 순회 → `{broker}` 단일 항목) |
| `backend/tests/test_engine_loop.py` | 수정 | 토큰 발급 대상 축소 반영 + 신규 시나리오 추가 (호출 대상 검증 포함) |

**후보 추가 파일 (구현 시 확인 후 결정):**
- `backend/tests/test_broker_change.py` — `confirmed_data_broker` 변경 시 재기동 검증이 토큰 발급 축소와 충돌하지 않는지 확인. 재기동 흐름을 검증하므로 직접 충돌 가능성 낮음.

임의 파일/함수 추가 없음. 위 2개(또는 3개) 파일만.

---

## 7. 코드 변경 책임 범위

### 수정
- `_get_all_tokens_async` 내부: 발급 대상 수집 로직을 `broker_config` + `confirmed_data_broker` 순회에서 `{broker}` 단일 항목으로 축소
- `auth_cache` 재사용 로직, `broker_tokens.clear()` 후 저장 패턴, 실패 시 `logger.warning(..., exc_info=True)` 유지

### 미수정 (명시적 유지)
- 외부 인터페이스(함수 시그니처, 반환값) 변경 없음
- `reset_router`, `BrokerRouter`, `ConnectorManager`, `market_close_pipeline.py` 수정 없음
- UI, 설정 스키마, DB 마이그레이션 없음
- `stop_engine → reset_broker_session_state → reset_router → start_engine` 재기동 흐름 유지

---

## 8. 토큰 상태 생명주기

### Startup token 발급
1. `_get_all_tokens_async` 호출 (`engine_loop.py:213`, `asyncio.gather` 내 병렬)
2. 발급 대상 = `{broker}` 1개
3. `broker_tokens.clear()` 후 활성 broker 토큰만 저장
4. `token_ready_event.set()` 신호 전송 (`engine_loop.py:219`)

### 기존 token 재사용
- `auth_cache`에 이미 해당 broker의 AuthProvider가 있으면 재사용 (`broker_registry.py:161-164`)
- 배치 경로: `if _broker_name not in broker_tokens` 조건으로 startup 토큰이 있으면 재사용 (`market_close_pipeline.py:1098`)

### 배치 token 발급
- 배치 시작 시 자체 AuthProvider 생성 (`market_close_pipeline.py:1092-1096`)
- `broker_tokens`에 없으면 발급 후 저장 + `_broker_token_registered = True` 플래그 설정 (`market_close_pipeline.py:1098-1100`)
- `broker_tokens`에 이미 있으면 재사용, `_broker_token_registered`는 False 유지 → **pop하지 않음**
- 배치 종료 후 `if _broker_token_registered:` 조건부 `pop` — **배치가 새로 추가한 토큰만 제거** (`market_close_pipeline.py:1144-1145, 1474`)

> **안전성 (코드 검증 완료)**: `broker == confirmed_data_broker`인 경우 배치는 기존 startup 토큰을 재사용하고 `_broker_token_registered`가 False이므로 `pop`하지 않음. 즉 활성 broker 토큰의 수명주기를 건드리지 않음.

### `broker_tokens` 상태 일관성
- startup 후: `{broker: token}` 1개 항목만
- 배치 실행 중: `{broker: token, confirmed_broker: batch_token}` (일시적)
- 배치 종료 후: `{broker: token}` 로 복귀
- `engine_lifecycle.py:185`는 `items()` 순회이므로 항목 수 변화에 안전

### Token 발급 실패 시 기존 강등 경로 유지
- `engine_loop.py:239-242`: 활성 broker 토큰 발급 실패 → `access_token = None` + "시세 전용 모드로 기동" 로그
- 크래시 없음, P25 부합

---

## 9. 테스트 계획

기존 `test_engine_loop.py` 구조(`_mock_state` + `patch.object`)를 따르되, **`_get_all_tokens_async` 자체를 mock 하지 않고 실제 실행 + AuthProvider mock + `get_access_token()` 호출 대상 검증** 형태를 최소 1개 포함 (P19 실제 살아있는 경로 검증).

> **핵심 원칙**: 단순히 `broker_tokens` 결과만 보지 말고, 실제로 어느 증권사의 `get_access_token()`이 호출됐는지까지 검증. 불필요한 provider 생성 후 토큰만 저장하지 않는 것과, 처음부터 provider 생성/인증 자체를 하지 않는 것을 구분.

| # | 시나리오 | 기대 |
|---|---------|------|
| 1 | broker=ls, confirmed_data_broker="" | ls `get_access_token()` 호출 O, ls 토큰 저장 |
| 2 | broker=kiwoom, confirmed_data_broker="" | kiwoom `get_access_token()` 호출 O, kiwoom 토큰 저장 |
| 3 | broker=ls, confirmed_data_broker=kiwoom | **ls `get_access_token()` 호출 O, kiwoom `get_access_token()` 호출 X**, `broker_tokens`에 ls만 존재 |
| 4 | broker=kiwoom, confirmed_data_broker=ls | **kiwoom `get_access_token()` 호출 O, ls `get_access_token()` 호출 X**, `broker_tokens`에 kiwoom만 존재 |
| 5 | 시나리오 3/4에서 미사용 broker 토큰이 `broker_tokens`에 없음 검증 | 불필요 발급 제거 확인 |
| 6 | 배치 경로 `test_market_close_pipeline.py` 기존 테스트 유지 | 자체 발급·재사용·pop 정리 동작 유지 |
| 7 | startup 토큰 존재 시 배치 재사용 경로 유지 | `if _broker_name not in broker_tokens` 분기 정상 |
| 8 | 활성 broker 토큰 발급 실패 시 시세 전용 모드 강등 | `engine_loop.py:239-242` 경로 유지 |
| 9 (추가A) | broker=kiwoom, confirmed_data_broker=kiwoom (동일) | startup kiwoom 토큰 존재 → 배치 새 인증 호출 없음 → 기존 토큰 재사용 → **배치 종료 후 kiwoom 토큰 유지** (`_broker_token_registered=False`로 pop 안 함) |

> **참고 — 테스트 10(추가B)은 이번 작업에서 제외**: `confirmed_data_broker != broker`일 때 "배치가 confirmed_data_broker를 인증한다"는 검증은 현재 코드에서 성립하지 않음. `market_close_pipeline.py:1094, 1272`가 `_broker_name = "kiwoom"` 하드코딩으로 `confirmed_data_broker` 설정을 읽지 않기 때문. 이 시나리오는 섹션 13의 별도 이슈(하드코딩 조사) 해결 후 별도 태스크에서 검증.

### 기존 테스트 업데이트
- 다중 broker 발급을 검증하던 기존 테스트(`test_get_all_tokens_collects_multiple_brokers`류)를 단일 broker 발급으로 업데이트
- 구현 진입 시 해당 테스트의 원래 의도를 커밋 히스토리와 함께 확인 후 최소 변경

---

## 10. 검증 게이트

```bash
# 1단계: 관련 테스트만 먼저
.venv/bin/python -m pytest backend/tests/test_engine_loop.py -q
.venv/bin/python -m pytest backend/tests/test_broker_change.py -q
.venv/bin/python -m pytest backend/tests/test_market_close_pipeline.py -q

# 2단계: 전체
.venv/bin/python -m pytest backend/tests -q

# 3단계: RuntimeWarning (await 누락 검증)
.venv/bin/python -W error::RuntimeWarning main.py
```

프론트엔드 변경 없으므로 `npm run typecheck`/`build` 생략 가능.

### 핵심 검증 (전체 pytest 통과만으로는 부족)
1. startup에서 broker만 인증하는가 — 테스트 3/4
2. confirmed_data_broker는 startup에서 인증하지 않는가 — 테스트 3/4
3. 배치는 필요 시 자체 인증하는가 — 테스트 6/7
4. 기존 시세 전용 강등이 유지되는가 — 테스트 8

새로 추가된 핵심 테스트가 위 4가지를 직접 검증하는지 확인.

---

## 11. 아키텍처 원칙 부합 여부

| 원칙 | 부합 | 근거 |
|------|------|------|
| P4 | ✓ | 증권사별 코드 침투 없음, 발급 대상만 축소 |
| P10 | ✓ | `broker_tokens` SSOT 단일, 중복 토큰 저장소 생성 없음 |
| P13 | ✓ | 틱 단계 DB 조회 무관, startup 초기화만 변경 |
| P16 | ✓ | `_get_all_tokens_async`는 실제 `engine_loop.py:213`에서 호출되는 살아있는 경로 |
| P17 | ✓ | 토큰 상태 단일 소스(`broker_tokens`) 유지, 플래그 분산 없음 |
| P18 | ✓ | 테스트/실전 공통 경로 훼손 없음, 발급 대상만 축소 |
| P19 | ✓ | 검증 게이트에 실제 pytest + RuntimeWarning + 핵심 테스트의 `get_access_token()` 호출 대상 검증 포함 |
| P20 | ✓ | silent fallback 추가 없음, 기존 명시적 강등 경로 유지 |
| P24 | ✓ | 배치 기존 Lazy Auth 재사용, 새 추상화/중복 경로 없음 |
| P25 | ✓ | 기존 토큰 실패 강등 경로 유지하여 해당 인증 실패가 전체 프로세스를 즉시 중단시키지 않도록 함. P25 관련 실패 격리 구조(`schedule_engine_task()` 및 해당 런타임 경로)는 기존 유지·검증 |

---

## 12. 회귀 위험 및 대응

| 위험 | 영향 | 대응 |
|------|------|------|
| `confirmed_data_broker` 토큰 startup 제거 | 배치 시작 시 자체 발급으로 약간 지연 | 배치 `if not in broker_tokens` 분기가 이미 자체 발급 처리하므로 기능적 회귀 없음; 테스트 6/7로 검증 |
| `engine_lifecycle.py:185` 상태 조회 | startup 후 `broker_tokens`에 활성 broker만 존재 | `items()` 순회이므로 존재하지 않는 broker는 표시 안 됨 — 기존 동작과 일치, 회귀 없음 |
| 시세 전용 모드 강등 | 활성 broker 토큰 발급 실패 시 | `engine_loop.py:239-242` 경로 변경 없음, 테스트 8로 검증 |
| 엔진 초기화 순서 | `_get_all_tokens_async`가 `asyncio.gather` 내 병렬 | 발급 대상만 축소, 병렬 구조·순서 변경 없음 |
| `broker_tokens.clear()` 호출 시점 | `engine_loop.py:102, 142, 401` | 변경 없음, clear 후 활성 broker만 저장 |
| 기존 다중 broker 발급 검증 테스트 | 단일 broker 발급으로 기대치 변경 필요 | 테스트 5로 대체, 기존 테스트 명 확인 후 최소 업데이트 |
| `broker_tokens.clear()`와 배치 실행의 lifecycle 충돌 | 배치 실행 중 `confirmed_data_broker` 토큰 추가와 동시에 startup/재기동 `clear()` 발생 시 상태 충돌 가능성 | 현재 `stop → reset → start` 구조상 동시 실행 가능성 낮으나 구현 시 `broker_tokens.clear()` 호출 시점(`engine_loop.py:102, 142, 401`)이 startup/재기동 시점 외에 실행될 가능성 없는지 확인 |

---

## 13. 별도 이슈로 기록 (이번 범위 밖)

### 이슈: `market_close_pipeline.py:1094` 하드코딩 `_broker_name = "kiwoom"`

**심각도**: 잠재 결함 (이번 Lazy Auth 작업과 별개)

**문제**:
- `market_close_pipeline.py:1094`에 `_broker_name = "kiwoom"` 하드코딩 존재
- 사용자가 `confirmed_data_broker = LS`로 설정해도 실제 배치 다운로드는 키움으로 진행될 가능성
- P10 (SSOT), P21 (사용자 투명성), P23 (용어/설정 일관성) 위반 가능성

**이번 작업에서의 처리**: 수정하지 않음 (단일 과제 원칙, P24). 단, 별도 이슈로 명시적으로 기록.

**별도 태스크 권장 내용**:
- `confirmed_data_broker` 설정이 실제 배치 경로(`market_close_pipeline.py:1094` 및 1276 부근)에서 사용되는지 조사
- 하드코딩을 `confirmed_data_broker or broker` 기반 동적 선택으로 변경할지, 아니면 현재 하드코딩이 의도된 동작인지(키움만 5일봉 다운로드 지원 등) 확인
- 이 결정은 Lazy Auth 리팩토링 완료 후 별도 세션에서 진행

---

## 14. 구현 전 마지막 승인 필요 사항

1. **발급 대상 축소 확정**: `{broker}`만 발급, `confirmed_data_broker`는 startup에서 제외 — 코드 검증 완료, 승인 대기
2. **`market_close_pipeline.py:1094` 하드코딩 처리**: 이번 범위 백 유지, 별도 이슈로 기록 (섹션 13)
3. **기존 테스트 업데이트 범위**: `test_engine_loop.py`의 다중 broker 발급 검증 테스트를 단일 발급으로 바꾸는 것이 기존 의도와 충돌하지 않는지 — 구현 진입 시 해당 테스트의 원래 의도를 커밋 히스토리와 함께 확인 후 최소 변경
4. **`test_broker_change.py` 영향**: `confirmed_data_broker` 변경 시 재기동 검증이 토큰 발급 축소와 독립적인지 — 1단계 검증에서 먼저 실행하여 회귀 없음 확인

---

## 15. 승인 조건 요약

| 항목 | 승인 |
|------|------|
| `_get_all_tokens_async` → startup 인증 대상 `{broker}`로 축소 | ✓ |
| `confirmed_data_broker` → startup 인증 제외 | ✓ |
| `market_close_pipeline` → 기존 자체 Lazy Auth 유지 | ✓ |
| `stop → reset → start` → 변경 없음 | ✓ |
| Broker Registry / Provider / Connector → 변경 없음 | ✓ |
| UI / DB / 설정 스키마 → 변경 없음 | ✓ |
| 테스트: `broker=LS, confirmed_data_broker=KIWOOM` → LS 인증 호출 O, KIWOOM 인증 호출 X 검증 | ✓ |
| 테스트(추가A): `broker == confirmed_data_broker` 시 기존 토큰 재사용 후 활성 broker 토큰 유지 (pop 안 함) | ✓ |
| 테스트(추가B): **이번 작업 제외** — `confirmed_data_broker` 상이 시 배치 동작은 섹션 13 별도 이슈 해결 후 별도 태스크에서 검증 | ✓ (제외) |
| `market_close_pipeline.py:1094` 하드코딩 → 별도 이슈 기록 | ✓ |
