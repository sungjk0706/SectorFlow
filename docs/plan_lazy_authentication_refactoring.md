# 태스크 파일: Lazy Authentication 리팩토링 구현

> **상태**: 태스크 분할 완료 / 구현 승인 대기
> **작성일**: 2026-07-30
> **설계서 경로**: `docs/lazy-authentication-refactoring-design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ / 2세션(태스크 분할) ✅ / 3세션(구현) 대기
> **관련 원칙**: P4 · P10 · P13 · P16 · P17 · P18 · P19 · P20 · P24 · P25

---

## 0. 사전조사 결과 요약

> 설계서(섹션 1·2·6·7·8·11)에서 이미 확정한 사실은 P10(SSOT)에 따라 본 섹션에서 요약만 기재. 상세 근거는 설계서 참조.

### 0.1 의존성

| 파일 | 변경점 | 기준 라인 |
|------|--------|-----------|
| `backend/app/services/engine_loop.py` | `_get_all_tokens_async` 발급 대상 수집 로직 축소: `broker_config` 전수 순회 + `confirmed_data_broker` 추가 수집 → `settings["broker"]` 단일 항목 | 47–108 (변경 집중: 55–79) |
| `backend/app/services/engine_loop.py` | startup 소비 지점·강등 경로·`gather` 호출·`token_ready_event.set()` — **변경 없음, 동작 유지 확인만** | 213 · 236 · 239–242 · 219 |
| `backend/app/services/market_close_pipeline.py` | 배치 자체 Lazy Auth (`_create_provider` → `get_access_token` → 조건부 저장 → `finally` 조건부 `pop`) — **변경 없음, 기존 유지** | 1092–1102 · 1144–1147 · 1276–1277 · 1474 |
| `backend/tests/test_engine_loop.py` | `TestGetAllTokensAsync` 내 기존 테스트 업데이트 + 신규 시나리오 추가 | 196–333 (변경 집중: 278–297 + 신규 추가) |
| `backend/tests/_mock_helpers.py` | `swallow_gather_side_effect` 등 기존 헬퍼 — **재사용, 변경 없음** | 임포트만 |
| `backend/tests/test_broker_change.py` | `confirmed_data_broker` 변경 시 재기동 검증 — **후보 검증 대상(수정 아님)**, 1단계 검증에서 회귀 없음 먼저 확인 | 전체 |
| `backend/tests/test_market_close_pipeline.py` | 배치 자체 발급·재사용·`pop` 정리 테스트 — **변경 없음, 기존 유지** (설계서 시나리오 6·7) | 전체 |

### 0.2 영향 범위

- **백엔드**: `engine_loop.py` 단일 함수 내부 로직만. 외부 인터페이스(함수 시그니처·반환값) 변경 없음.
- **프론트엔드 / DB / 설정 스키마 / UI**: 변경 없음 (설계서 섹션 7 "미수정" 명시).
- **배치 경로**: 변경 없음. 단, startup에서 `confirmed_data_broker` 토큰을 미리 발급하지 않게 되므로, 배치 시작 시 `if _broker_name not in broker_tokens` 분기(`market_close_pipeline.py:1098`)가 자체 발급을 담당. 기능적 회귀 없음 — 설계서 섹션 8·12로 검증 완료.
- **시나리오 9(추가A) 사전조사 결과 (2026-07-30 확정)**: `test_market_close_pipeline.py:899` `test_broker_token_registered_and_cleaned`는 **`_broker_token_registered=True` 경로**(빈 `broker_tokens`에서 시작 → 배치 자체 발급 → `finally`에서 `pop`)만 검증. 시나리오 9(`_broker_token_registered=False`, startup 토큰 재사용 → `pop` 안 함)는 **기존 테스트로 커버되지 않음** 확정. 단, `test_market_close_pipeline.py` 추가는 설계서 섹션 6·7 "변경 파일 목록·`market_close_pipeline.py` 미수정"과 충돌 → **이번 작업에서 제외, 별도 이관** (사용자 결정 H 참조).
- **`stop → reset_broker_session_state → reset_router → start_engine` 재기동 흐름**: 변경 없음 (설계서 섹션 7).

### 0.3 아키텍처 원칙 부합

> 상세 근거는 설계서 섹션 11. 본 태스크는 실행 단계별 부합 항목만 표기.

| 원칙 | 부합 | 실행 단계에서의 확인점 |
|------|------|----------------------|
| P4 | ✅ | 발급 대상 축소만, 증권사별 코드 침투 없음 |
| P10 | ✅ | `broker_tokens` SSOT 단일, 중복 토큰 저장소 생성 없음 |
| P13 | ✅ | startup 초기화만, 틱 단계 DB 조회 무관 |
| P16 | ✅ | `_get_all_tokens_async`는 `engine_loop.py:213`에서 실제 호출되는 살아있는 경로 |
| P17 | ✅ | 토큰 상태 단일 소스(`broker_tokens`) 유지, 플래그 분산 없음 |
| P18 | ✅ | 테스트/실전 공통 경로 훼손 없음, 발급 대상만 축소 |
| P19 | ✅ | 검증 게이트에 실제 pytest + RuntimeWarning + 핵심 테스트의 `get_access_token()` 호출 대상 검증 포함 (섹션 3) |
| P20 | ✅ | silent fallback 추가 없음, 기존 명시적 강등 경로(`engine_loop.py:239-242`) 유지 |
| P24 | ✅ | 배치 기존 Lazy Auth 재사용, 새 추상화/전역 `LazyAuthManager` 도입 없음, 단일 구현 세션 분할 |
| P25 | ✅ | 기존 토큰 실패 강등 경로 유지, 인증 실패가 전체 프로세스 즉시 중단시키지 않음 |

### 0.4 기존 공통 자산 확인

- **재사용 (신규 생성 없음)**:
  - `backend.app.core.broker_registry._create_provider` — `_fetch_one` 내 기존 호출 그대로 유지 (`engine_loop.py:85-89`)
  - `BROKER_DISPLAY_NAMES` — 경고 로그 메시지에 기존 매핑 그대로 사용 (`engine_loop.py:94`)
  - `engine_state.state.integrated_system_settings_cache` — 설정 SSOT, 기존 참조 그대로
  - `asyncio.gather` 병렬 구조 — 발급 대상만 축소, 병렬 구조 자체 유지
  - 테스트 헬퍼: `_mock_state`(`test_engine_loop.py:42`), `swallow_gather_side_effect`(`_mock_helpers.py`)
- **신규 생성**: 없음 (임의 파일/함수/전역 매니저 추가 금지 — 설계서 섹션 6)

---

## 1. 단계 분할

> 정량 기준(컨텍스트 관리 규칙 1 · 규칙 0-2-5): 수정 파일 3개 초과 또는 수정 라인 50줄 초과 시 다단계 분할 필수.
> 본 작업: 구현 로직 변경 약 15줄(`engine_loop.py`), 테스트 업데이트+추가(`test_engine_loop.py`). 구현 로직은 기준 미달이며, 테스트는 동일 파일·동일 클래스(`TestGetAllTokensAsync`) 내 추가로 컨텍스트가 동일 → **단일 구현 세션(3세션)으로 분할** (P24 단순성 — 과잉 분할 회피).

### 3세션: 구현 + 테스트 (단일 세션)

**목표**: `_get_all_tokens_async` 발급 대상을 `{broker}` 단일 항목으로 축소하고, 테스트 시나리오 1·2·3·4·5·8을 `test_engine_loop.py`에 반영하며, 검증 게이트 3단계를 통과한다.

**수정 파일 목록**:
1. `backend/app/services/engine_loop.py` — 구현
2. `backend/tests/test_engine_loop.py` — 테스트 업데이트 + 신규 추가

**파일별 변경점**:

#### `backend/app/services/engine_loop.py` (구현)

`_get_all_tokens_async` 내부 55–79번 줄(발급 대상 수집 + API 키 필터 + early return)을 다음으로 축소:

- `broker_config` 전수 순회 + `confirmed_data_broker` 추가 수집(`55–68번`) → `settings["broker"]` 단일 항목 조회로 대체
- API 키 필터링(`70–76번`) — 활성 broker 1개에 대해서만 수행
- early return 조건(`78–79번`) — 활성 broker 미설정 또는 API 키 미설정 시 기존대로 early return
- 변경 후 발급 대상 = `[broker_id]` 1개 항목 (리스트 형태 유지 → `asyncio.gather` 호출부 `97–100번` 변경 없음)

**유지 (변경 금지 — 설계서 섹션 7)**:
- `auth_cache = getattr(router, "_auth_cache", {})` (53번)
- `_fetch_one` 내 `_create_provider` 재사용 로직 (81–95번)
- `asyncio.gather(..., return_exceptions=True)` 병렬 구조 (97–100번)
- `engine_state.state.broker_tokens.clear()` (102번)
- 결과 저장 루프 (104–108번)
- 실패 시 `logger.warning(..., exc_info=True)` (94번) — silent `except: pass` 아님
- 외부 인터페이스(함수 시그니처·반환값·docstring)는 변경 없으나, docstring 내 "모든 증권사" 표현이 새 동작과 불일치하면 P10/P23 위반이므로 함께 수정 (49–52번 docstring)

#### `backend/tests/test_engine_loop.py` (테스트)

- **기존 테스트 업데이트**: `test_confirmed_data_broker_collected`(`278–297`) — 기존 의도("confirmed_data_broker도 발급 대상 포함")를 반전하여 "confirmed_data_broker는 startup 발급 대상에서 제외"로 변경.
  - 구현 진입 시 해당 테스트의 원래 의도를 커밋 히스토리와 함께 확인 후 **최소 변경** (설계서 섹션 14-3 승인 조건).
  - **삭제 결정 시 최소 조건 (판단 기준)**: 커밋 히스토리상 이 테스트가 다중 broker 발급 의도 외의 별도 버그를 잡은 이력이 없을 때만 의도 반전 업데이트(삭제 아님)로 처리. 의도 반전이 불가능한 구조적 이유가 있을 때만 삭제 — 그 경우에도 동일 검증(활성 broker만 발급)을 신규 시나리오 3/4로 보존하므로 검증 공백 없음.
  - 기대: `broker=kiwoom, confirmed_data_broker=ls` → `broker_tokens`에 `kiwoom`만 존재, `ls` 부재.
- **신규 테스트 추가** (`TestGetAllTokensAsync` 클래스 내): 설계서 섹션 9 시나리오 1·2·3·4·5 반영. **핵심 원칙(설계서 섹션 9)**: 단순히 `broker_tokens` 결과만 보지 말고, 실제로 어느 증권사의 `get_access_token()`이 호출됐는지까지 검증 (`auth_provider.get_access_token.assert_called_once()` / `.assert_not_called()`).
  - 시나리오 1: `broker=ls, confirmed_data_broker=""` → ls `get_access_token()` 호출 O, ls 토큰 저장
  - 시나리오 2: `broker=kiwoom, confirmed_data_broker=""` → kiwoom `get_access_token()` 호출 O, kiwoom 토큰 저장 (기존 `test_token_success_stored_in_state`와 중복 시 통합 또는 호출 검증 강화)
  - 시나리오 3: `broker=ls, confirmed_data_broker=kiwoom` → **ls `get_access_token()` 호출 O, kiwoom `get_access_token()` 호출 X**, `broker_tokens`에 ls만 존재
  - 시나리오 4: `broker=kiwoom, confirmed_data_broker=ls` → **kiwoom `get_access_token()` 호출 O, ls `get_access_token()` 호출 X**, `broker_tokens`에 kiwoom만 존재
  - 시나리오 5: 시나리오 3/4에서 미사용 broker 토큰이 `broker_tokens`에 없음 검증 (3/4에 통합)
- **기존 테스트 유지 (변경 없음)**:
  - `test_no_valid_brokers_returns_early` — 활성 broker API 키 없으면 early return (변경 후에도 동일)
  - `test_token_failure_returns_none` — 토큰 발급 실패 시 저장 안함 (시나리오 8 관련, `get_access_token` 호출 검증 보강 가능)
  - `test_auth_cache_miss_creates_provider` — 캐시 미스 시 provider 생성
  - `test_broker_tokens_cleared_before_set` — clear 후 저장
  - `test_empty_broker_name_in_config_skipped` — 정규화로 `broker_config`가 단일 `{broker}`로 수렴하므로, 빈 문자열 스킵 시나리오는 새 로직에서 자연 제거. **구현 진입 시 이 테스트의 유효성 재확인** — 새 발급 대상 계산이 `broker_config`를 순회하지 않으므로 해당 테스트가 더 이상 유효하지 않으면 의도를 보존하는 방향으로 업데이트 또는 삭제 (커밋 히스토리 확인 후 최소 변경). **삭제 결정 시 최소 조건 (판단 기준)**: 커밋 히스토리상 이 테스트가 빈 broker 스킵 의도 외의 별도 버그를 잡은 이력이 없을 때만 삭제 가능. 삭제 시에도 새 로직(`settings["broker"]` 단일 조회)이 빈 broker를 자연 스킵하는지를 시나리오 1/2의 `broker=""` 변형 또는 `test_no_valid_brokers_returns_early`로 보존 — 검증 공백 없음.
- **`run_engine_loop` 관련 테스트**(`416–790`): `_get_all_tokens_async`를 `AsyncMock`으로 mock 하는 기존 패턴 유지 — 함수 시그니처 변경 없으므로 영향 없음.

**검증 방법** (3단계 게이트 — 설계서 섹션 10):

```bash
# 1단계: 관련 테스트만 먼저
.venv/bin/python -m pytest backend/tests/test_engine_loop.py -q
.venv/bin/python -m pytest backend/tests/test_broker_change.py -q
.venv/bin/python -m pytest backend/tests/test_market_close_pipeline.py -q

# 2단계: 전체 (2697 tests, asyncio_mode=auto)
.venv/bin/python -m pytest backend/tests -q

# 3단계: RuntimeWarning (await 누락 검증 — 금지 패턴 4번째)
.venv/bin/python -W error::RuntimeWarning main.py
```

프론트엔드 변경 없으므로 `npm run typecheck`/`build` 생략 가능.

**핵심 검증 (전체 pytest 통과만으로는 부족 — 설계서 섹션 10)**:
1. startup에서 활성 broker만 인증하는가 — 시나리오 3/4의 `get_access_token()` 호출 대상 검증
2. `confirmed_data_broker`는 startup에서 인증하지 않는가 — 시나리오 3/4
3. 배치는 필요 시 자체 인증하는가 — `test_market_close_pipeline.py` 기존 테스트 유지(시나리오 6/7)
4. 기존 시세 전용 강등이 유지되는가 — 시나리오 8

새로 추가/업데이트된 핵심 테스트가 위 4가지를 직접 검증하는지 확인.

---

## 2. 사용자 결정 항목

> 설계서 섹션 4·5·14·15에서 확정된 사항 이관. 구현 중 추가 결정 시 누적 기록.

| # | 결정 사항 | 확정 내용 | 근거 (설계서) |
|---|----------|-----------|--------------|
| A | Startup 인증 대상 | `{broker}` 1개만 발급 | 섹션 4 — `broker_nm = settings["broker"]` 단일 startup 소비자 |
| B | `confirmed_data_broker` 처리 | startup에서 완전히 제외, `market_close_pipeline.py` 자체 Lazy Auth에 위임 | 섹션 5 — 비배치 startup 소비자 코드 검색 결과 부재 |
| C | `market_close_pipeline.py:1094` 하드코딩 (`_broker_name = "kiwoom"`) | **이번 범위 밖**, 수정하지 않고 별도 이슈로 기록 | 섹션 13 — 단일 과제 원칙(P24), 별도 태스크에서 조사 |
| D | 테스트 10(추가B) `confirmed_data_broker != broker` 시 배치 동작 검증 | **이번 작업 제외** — 섹션 13 하드코딩 이슈 해결 후 별도 태스크에서 검증 | 섹션 9 참고 · 섹션 15 |
| E | 기존 테스트 업데이트 범위 | 다중 broker 발급 검증 테스트를 단일 발급로 변경 시, 기존 의도를 커밋 히스토리와 함께 확인 후 **최소 변경** | 섹션 14-3 |
| F | `test_broker_change.py` 영향 | 1단계 검증에서 먼저 실행하여 회귀 없음 확인 (수정 아님, 검증만) | 섹션 14-4 |
| G | 단일 구현 세션 분할 | 구현 로직 약 15줄 + 테스트 동일 파일/클래스 내 추가 → 단일 세션(3세션) 진행. 과잉 분할 회피 (P24) | 본 태스크 0.4 · 1 |
| H | 시나리오 9(추가A) 처리 | **이번 작업 제외, 별도 이관** — 사전조사(2026-07-30)로 `test_market_close_pipeline.py:899`가 `_broker_token_registered=True` 경로만 검증하여 시나리오 9 커버 안 됨 확정. `test_market_close_pipeline.py` 추가는 설계서 섹션 6·7(변경 파일 목록·`market_close_pipeline.py` 미수정)과 충돌 → P24 단일 과제 준수 위해 제외. 별도 태스크에서 `broker == confirmed_data_broker` 시 배치 재사용·`pop` 안 함 검증 추가 (섹션 13 하드코딩 조사와 함께 또는 별도). | 본 태스크 0.2 · 3 |

---

## 3. 테스트 계획

> 설계서 섹션 9의 9개 시나리오 중 이번 세션(3세션)에 반영하는 항목 매핑. 상세 기대값은 설계서 섹션 9 표 참조.

| # | 시나리오 | 반영 위치 | 비고 |
|---|---------|-----------|------|
| 1 | broker=ls, confirmed_data_broker="" | `test_engine_loop.py` 신규 | ls 인증 호출 O, ls 토큰 저장 |
| 2 | broker=kiwoom, confirmed_data_broker="" | `test_engine_loop.py` (기존 강화 또는 신규) | kiwoom 인증 호출 O, kiwoom 토큰 저장 |
| 3 | broker=ls, confirmed_data_broker=kiwoom | `test_engine_loop.py` 신규 | **ls 호출 O, kiwoom 호출 X**, ls만 저장 |
| 4 | broker=kiwoom, confirmed_data_broker=ls | `test_engine_loop.py` 신규 | **kiwoom 호출 O, ls 호출 X**, kiwoom만 저장 |
| 5 | 시나리오 3/4에서 미사용 broker 토큰 부재 검증 | 시나리오 3/4에 통합 | 불필요 발급 제거 확인 |
| 6 | 배치 자체 발급·재사용·pop 정리 동작 유지 | `test_market_close_pipeline.py` 기존 (변경 없음) | 자체 Lazy Auth 유지 |
| 7 | startup 토큰 존재 시 배치 재사용 경로 유지 | `test_market_close_pipeline.py` 기존 (변경 없음) | `if _broker_name not in broker_tokens` 분기 |
| 8 | 활성 broker 토큰 발급 실패 시 시세 전용 모드 강등 | `test_engine_loop.py` `test_token_failure_returns_none` + `run_engine_loop` 강등 테스트 유지 | `engine_loop.py:239-242` 경로 유지 |
| 9 (추가A) | broker=kiwoom, confirmed_data_broker=kiwoom (동일) → 배치 재사용 후 pop 안 함 | **이번 작업 제외 (사용자 결정 H)** — 사전조사로 `test_market_close_pipeline.py:899`가 `_broker_token_registered=True` 경로만 검증하여 커버 안 됨 확정. `test_market_close_pipeline.py` 추가는 설계서 범위 충돌 → 별도 태스크로 이관. | `_broker_token_registered=False`로 pop 안 함 |
| 10 (추가B) | `confirmed_data_broker != broker` 시 배치 동작 | **이번 작업 제외** (사용자 결정 D) | 섹션 13 별도 이슈 해결 후 별도 태스크 |

**기존 테스트 업데이트** (설계서 섹션 9 "기존 테스트 업데이트"):
- `test_confirmed_data_broker_collected` → 의도 반전 (다중 발급 검증 → 단일 발급 + confirmed 제외 검증)
- `test_empty_broker_name_in_config_skipped` → 새 로직에서 `broker_config` 순회 제거로 유효성 재확인 후 최소 업데이트 또는 삭제 (커밋 히스토리 확인)

---

## 4. 런타임 검증 방법

> 백엔드 변경이므로 기동 검증 포함 (선택 섹션 — 설계서 섹션 10 3단계와 중복이나, 런타임 기동 체크포인트 보강).

**기동 명령**:
```bash
.venv/bin/python main.py                              # 정상 기동
.venv/bin/python -W error::RuntimeWarning main.py     # await 누락 검증 (금지 패턴 4번째)
```

**체크 포인트** (0-1-3 명령어로 잔존 프로세스 0건 확인 후 기동):
1. 기동 로그에 활성 broker 토큰 발급 1건만 표시되는지 확인 (다중 broker 발급 로그 부재)
2. `confirmed_data_broker`가 활성 broker와 달라도 해당 broker의 토큰 발급 로그가 startup에 나타나지 않는지 확인
3. 활성 broker 토큰 발급 실패 시 "시세 전용 모드로 기동" 로그가 기존과 동일하게 출력되는지 확인 (강등 경로 유지)
4. 장마감 배치 수동 트리거 시 `if _broker_name not in broker_tokens` 분기로 자체 발급이 정상 동작하는지 확인 (가능한 경우)

---

## 5. 바로잡음 로그

> 구현 중 태스크 기재 오류 발견 시 원인+수정 기록. (초기 작성 시 공란)

- **2026-07-30 (태스크 작성 세션 내 보완)**: 외부 검토(다른 AI) 의견 반영 2건.
  1. 기존 테스트 2개(`test_confirmed_data_broker_collected`, `test_empty_broker_name_in_config_skipped`)의 "구현 시 판단" 항목에 **판단 기준(삭제 결정 시 최소 조건)** 한 줄씩 추가 — "구현하기 편한 쪽(테스트 약화/삭제)으로 기울 위험" 방어 (규칙 0-2-6·P21).
  2. 시나리오 9(추가A) "구현 시 확인" 유예 → **사전조사 완료**. `test_market_close_pipeline.py:899`가 `_broker_token_registered=True` 경로만 검증하여 시나리오 9 커버 안 됨 확정. 설계서 섹션 6·7 범위 충돌로 **이번 작업 제외·별도 이관** 확정 (사용자 결정 H 신설, 0.2·3절 동기화).
  - 외부 의견 3건(2697개 실행 시간 언급)은 AGENTS.md SSOT(표준 검증 명령어)와 충돌로 미반영 (P10).
