# SectorFlow 아키텍처 리팩터링 실행지시서

## 0. 문서 목적

이 문서는 하위 AI 코딩에이전트가 `ARCHITECTURE_PROPOSAL.md`의 방향을 실제 코드 수정 작업으로 안전하게 나누어 실행하기 위한 작업 지시서다.

이 문서는 최종 설계 방향을 반복 설명하는 문서가 아니다. 실제 코드 수정 전 반드시 확인해야 할 절차, 수정 범위, 금지 범위, 검증 기준, 완료 기준을 정의한다.

## 1. 절대 작업 원칙

### 1.1 문서만 보고 수정 금지

하위 AI 코딩에이전트는 이 문서만 근거로 코드를 수정하면 안 된다.

각 단계 시작 전 반드시 다음을 수행한다.

1. 현재 파일 내용을 다시 읽는다.
2. 호출처를 검색한다.
3. 영향 범위를 확인한다.
4. 변경 계획을 사용자에게 보고한다.
5. 사용자 승인을 받은 뒤 수정한다.
6. 수정 후 검증한다.
7. 검증 결과를 보고한다.

### 1.2 단계별 승인 필수

한 번에 여러 단계를 진행하지 않는다.

각 단계는 다음 형식으로 승인받는다.

```text
[승인 요청]
단계: P0-1 DI Container 제거 준비
수정 대상 파일:
- backend/app/web/app.py
- backend/app/core/settings_store.py
- backend/app/di/container.py

변경 내용:
- settings DI 등록 제거
- _integrated_system_settings_cache 단일 경로 사용

검증 방법:
- python -m py_compile ...
- 앱 재기동

진행해도 될까요?
```

### 1.3 코드 기반 보고 필수

보고는 반드시 파일명과 줄번호를 포함한다.

금지 표현:

- 아마도
- 보입니다
- 같습니다
- 가능성이 있습니다
- 일단

허용 표현:

- `파일명:라인`에서 확인됨
- 검색 결과 호출처가 확인됨
- py_compile 성공
- 앱 로그에서 확인됨

### 1.4 수정 단위 제한

한 단계에서 큰 리팩터링을 하지 않는다.

권장 단위:

- 파일 1~3개
- 기능 1개
- 검증 1회

금지:

- 여러 파일을 큰 정규식으로 일괄 치환
- 실시간 파이프라인과 DB 저장 경로를 동시에 수정
- 주문/체결 로직과 UI 로그 정리를 동시에 수정

## 2. 사전 필수 확인

작업 시작 전 반드시 아래 파일을 읽는다.

1. `ARCHITECTURE_PROPOSAL.md`
2. `HANDOVER.md`
3. `backend/app/web/app.py`
4. `backend/app/services/engine_state.py`
5. `backend/app/services/engine_loop.py`
6. `backend/app/services/core_queues.py`
7. `backend/app/db/database.py`
8. `backend/app/db/db_writer.py`
9. `backend/app/core/broker_factory.py`
10. `backend/app/core/broker_router.py`

## 3. 수정 금지 영역

다음 영역은 명시적 요청 없이는 수정하지 않는다.

### 3.1 주문/체결 무결성 영역

- `backend/app/services/pipeline_oms.py`
- `backend/app/services/trading.py`
- `backend/app/core/journal.py`
- 주문 Pending/Completed 처리
- Reconciliation 처리

수정 금지 이유:

- 주문/체결은 드롭 금지와 순서 보장이 핵심이다.
- 리팩터링 중 무결성 손상 위험이 크다.

### 3.2 실시간 시세 처리 핵심 영역

- `backend/app/services/pipeline_compute.py`
- `backend/app/services/engine_ws_dispatch.py`
- `backend/app/services/engine_ws_reg.py`
- WebSocket 실시간 수신/구독/해제 흐름

수정 금지 이유:

- 틱 처리 지연과 누락이 자동매매 판단을 왜곡한다.

### 3.3 DB 저장 무결성 영역

- `backend/app/db/database.py`
- `backend/app/db/db_writer.py`

단, 별도 단계에서 DB Writer 사용 경로 점검은 가능하다. 직접 수정은 사용자 승인 후 진행한다.

### 3.4 테스트모드/실전투자 분기

- 테스트모드는 돈 관련 주문/체결/잔고만 가상이다.
- 나머지 데이터 흐름은 실전투자와 동일해야 한다.
- 테스트모드라는 이유로 증권사/실시간/데이터 흐름을 임의로 우회하지 않는다.

## 4. 목표 아키텍처 요약

SectorFlow의 최종 목표 아키텍처는 다음과 같다.

```text
FastAPI Lifespan
  ├─ SQLite 단일 커넥션 초기화
  ├─ DB Writer 시작
  ├─ RuntimeState 초기화
  │   ├─ SettingsCache 1회 로드
  │   ├─ MasterStocksCache 1회 로드
  │   └─ BrokerSession 1회 생성
  ├─ Pipeline Queues 초기화
  │   ├─ tick_queue
  │   ├─ order_queue
  │   ├─ broadcast_queue
  │   └─ control_queue
  ├─ Engine 시작
  │   ├─ MarketData Ingestion
  │   ├─ Compute Engine
  │   ├─ Risk Manager
  │   ├─ OMS
  │   └─ Gateway
  └─ Scheduler 시작
```

유지할 것:

- 단일 FastAPI 프로세스
- 단일 asyncio 이벤트 루프
- SQLite + WAL + aiosqlite 단일 커넥션
- DB Writer 단일 쓰기 직렬화
- `asyncio.Queue` 기반 명시적 파이프라인
- `tick_queue`, `order_queue`, `broadcast_queue`, `control_queue` 분리
- `BrokerRouter` 싱글톤
- 앱 기동 시 설정/마스터 데이터 메모리 적재

줄일 것:

- DI Container
- 미사용 ThreadPoolExecutor
- 기본 executor 과다 워커
- 중복 설정 캐시
- 토큰/REST 인스턴스 다중 소유권
- 개발자용 INFO 로그

## 5. 실행 단계

## P0-1. DI Container 사용 범위 축소 또는 제거

### 목적

현재 DI Container는 1인 로컬 앱 기준으로 과한 추상화다. 실제 설정 캐시는 `_integrated_system_settings_cache`가 담당하므로 `settings` DI 등록 경로를 제거하거나 축소한다.

### 조사 대상

- `backend/app/di/container.py`
- `backend/app/web/app.py`
- `backend/app/core/settings_store.py`

### 사전 검색

다음 검색을 수행한다.

```text
get_container
register_singleton
get_singleton
register_service
get_service
```

### 예상 수정 방향

1. `app.py`에서 `container = get_container()` 필요 여부 확인
2. `settings` 등록 제거 가능 여부 확인
3. `settings_store.py`가 `_integrated_system_settings_cache`를 직접 갱신하도록 변경
4. `backend_coalescing`, `ws_manager` DI 등록 제거 가능 여부 확인
5. `container.py` 삭제는 마지막 단계로 미룬다. 먼저 미사용 상태를 만든다.

### 금지

- `_integrated_system_settings_cache` 구조를 동시에 바꾸지 않는다.
- 설정 저장 DB 로직을 동시에 수정하지 않는다.
- `settings_store.py`의 저장/브로드캐스트 로직을 임의 변경하지 않는다.

### 검증

```bash
python -m py_compile backend/app/web/app.py backend/app/core/settings_store.py backend/app/di/container.py
```

앱 재기동 후 확인:

- 설정 로드 성공
- 설정 변경 저장 성공
- 상단 상태/설정 화면 정상 표시

### 완료 기준

- `settings` 조회가 DI Container 없이 동작한다.
- 앱 기동 로그에서 DI Container 등록 로그가 사라진다.
- 설정 변경 후 런타임 캐시가 갱신된다.

## P0-2. ThreadPoolExecutor 정리

### 목적

1인 로컬 실시간 앱에서 과한 스레드풀과 미사용 executor를 제거한다.

### 조사 대상

- `backend/app/web/app.py`
- `backend/app/services/market_close_pipeline.py`
- `backend/app/services/engine_loop.py`
- `backend/app/core/kiwoom_rest.py`

### 사전 검색

```text
ThreadPoolExecutor
set_default_executor
to_thread
run_in_executor
_CONFIRMED_FETCH_EXECUTOR
submit(
```

### 예상 수정 방향

1. `market_close_pipeline.py`의 `_CONFIRMED_FETCH_EXECUTOR`가 미사용이면 삭제
2. `app.py`의 `ThreadPoolExecutor(max_workers=8)`은 제거하거나 `max_workers=2`로 축소
3. `asyncio.to_thread()` 호출은 즉시 제거하지 않는다. 호출 대상이 동기 API인지 먼저 확인한다.
4. 장기적으로 REST 호출은 async HTTP로 전환한다.

### 금지

- 토큰 발급 흐름을 동시에 async로 대규모 변경하지 않는다.
- 증권사 REST 모듈 전체를 리팩터링하지 않는다.
- 실시간 WebSocket 처리와 함께 수정하지 않는다.

### 검증

```bash
python -m py_compile backend/app/web/app.py backend/app/services/market_close_pipeline.py backend/app/services/engine_loop.py
```

앱 재기동 후 확인:

- 앱 정상 기동
- 키움증권 토큰 발급 성공
- 5일봉 다운로드 시작 가능

### 완료 기준

- 미사용 executor가 제거된다.
- 기본 executor 과다 설정이 제거 또는 축소된다.
- 토큰 발급과 앱 기동이 유지된다.

## P0-3. BrokerSession 단일화 규칙 적용

### 목적

토큰 재발급과 REST 인스턴스 중복 생성을 방지한다.

### 조사 대상

- `backend/app/core/broker_factory.py`
- `backend/app/core/broker_router.py`
- `backend/app/core/kiwoom_providers.py`
- `backend/app/core/kiwoom_rest.py`
- `backend/app/services/engine_loop.py`
- `backend/app/services/market_close_pipeline.py`

### 사전 검색

```text
BrokerRouter(
get_router(
KiwoomAuthProvider(
KiwoomRestAPI(
_access_token
_broker_tokens
_token_info
```

### 예상 수정 방향

1. 모든 일반 실행 경로에서 `BrokerRouter()` 직접 생성 금지
2. `get_router()` 단일 경로 사용
3. `KiwoomRestAPI._token_info`를 토큰 원천으로 확정
4. `_broker_tokens`, `_access_token`은 UI/상태 표시용 파생값으로 제한
5. 다운로드/배치 파이프라인도 `get_router()` 사용 유지

### 금지

- 증권사별 Provider 인터페이스를 동시에 변경하지 않는다.
- Kiwoom/LS 브로커 추상화를 깨지 않는다.
- 키움증권 이름을 공통 브로커 코드에 침투시키지 않는다.

### 검증

```bash
python -m py_compile backend/app/core/broker_factory.py backend/app/core/broker_router.py backend/app/core/kiwoom_providers.py backend/app/core/kiwoom_rest.py backend/app/services/engine_loop.py backend/app/services/market_close_pipeline.py
```

앱 재기동 후 확인:

- 앱 기동 시 토큰 1회 발급
- 5일봉 다운로드 클릭 시 불필요한 재발급 로그 없음
- 기존 토큰 캐시 사용

### 완료 기준

- `BrokerRouter()` 직접 생성 경로가 제거된다.
- 5일봉 다운로드 시 토큰 재발급이 발생하지 않는다.

## P1-1. 캐시 소유권 정리

### 목적

여러 캐시가 중복 원천처럼 동작하지 않도록 원천/파생/수명/갱신자를 명확히 한다.

### 조사 대상

- `backend/app/services/engine_state.py`
- `backend/app/services/engine_cache.py`
- `backend/app/services/engine_bootstrap.py`
- `backend/app/services/engine_config.py`
- `backend/app/services/engine_sector.py`
- `backend/app/services/engine_sector_confirm.py`
- `backend/app/services/engine_snapshot.py`

### 캐시 소유권 기준

| 데이터 | 원천 저장소 | 런타임 캐시 | 소유자 |
|---|---|---|---|
| 통합 설정 | integrated_system_settings | `_integrated_system_settings_cache` | engine_state |
| 종목 마스터 | master_stocks_table | `_master_stocks_cache` | engine_state |
| 5일봉 배열 | stock_5d_array | 필요 시 조회 | DB |
| 토큰 | Kiwoom REST 응답 | `KiwoomRestAPI._token_info` | BrokerSession |
| 계좌 | 증권사 REST/WS | `_account_snapshot`, `_positions` | AccountState |
| 업종 점수 | master cache + 실시간 입력 | `_sector_score_index` | SectorCompute |
| UI 병합 | 실시간 이벤트 | `_coalesce_cache` | Gateway |

### 예상 수정 방향

1. `engine_state.py`에 캐시 소유권 표를 코드 구조로 반영
2. 중복 캐시 주석과 실제 사용이 다른 곳을 정리
3. `_integrated_system_settings_cache` 접근 경로 표준화
4. `_master_stocks_cache` 갱신 경로 표준화

### 금지

- 캐시 저장 구조를 한 번에 대규모 변경하지 않는다.
- 업종 계산 결과와 UI 스냅샷을 동시에 바꾸지 않는다.
- DB 테이블 구조를 동시에 변경하지 않는다.

### 검증

```bash
python -m py_compile backend/app/services/engine_state.py backend/app/services/engine_cache.py backend/app/services/engine_bootstrap.py backend/app/services/engine_config.py backend/app/services/engine_sector.py backend/app/services/engine_sector_confirm.py backend/app/services/engine_snapshot.py
```

앱 재기동 후 확인:

- 전체 종목 로드 수 정상
- 5일평균 로드 수 정상
- 업종순위 표시 정상
- 설정 변경 후 필터 반영 정상

### 완료 기준

- 캐시별 원천/파생/갱신자가 문서와 코드에서 일치한다.
- 설정 캐시 중복 경로가 제거된다.
- 마스터 종목 캐시가 단일 기준으로 유지된다.

## P1-2. 로그 레벨과 사용자 로그 정리

### 목적

사용자에게 필요한 로그와 개발자용 로그를 분리한다.

### INFO 유지 대상

- 앱 기동 완료
- 증권사 연결/토큰 발급 완료
- 데이터 준비 완료
- 실시간 연결 시작/중지
- 주문/체결 관련 핵심 상태
- 오류/경고

### DEBUG 또는 삭제 대상

- DI Container 내부 등록 로그
- ThreadPoolExecutor 설정 직전/완료 로그
- 내부 함수 진입 로그
- 이미 완료된 마이그레이션 스킵 로그
- DEBUG-FILTER 로그
- 캐시 내부 로드 상세 로그

### 금지

- 오류 로그를 삭제하지 않는다.
- 주문/체결/리스크 관련 로그를 임의 삭제하지 않는다.
- 보안 정보가 포함된 로그는 삭제 또는 마스킹한다.

### 검증

앱 재기동 후 확인:

- 사용자 로그가 간결해진다.
- 오류 발생 시 원인 추적 가능한 로그는 유지된다.

## P2-1. DB Writer 사용 경로 점검

### 목적

SQLite 단일 쓰기 직렬화 원칙이 실제 코드 전체에서 유지되는지 확인한다.

### 사전 검색

```text
conn.commit
.execute(
.executemany(
get_db_connection
execute_db_write
enqueue_db_write
```

### 작업 방식

이 단계는 먼저 조사만 수행한다. 사용자 승인 없이 수정하지 않는다.

### 보고 항목

- 직접 commit 파일 목록
- DB Writer 사용 파일 목록
- 직접 commit이 허용되는 초기화/마이그레이션 파일 목록
- DB Writer로 이동해야 할 런타임 쓰기 파일 목록

## P2-2. 중앙 태스크 코디네이터 검토

### 목적

장기 실행 태스크와 임시 태스크를 구분한다.

### 사전 검색

```text
asyncio.create_task
get_running_loop().create_task
```

### 판단 기준

허용:

- 앱 기동 시 시작하는 장기 루프
- Compute/OMS/Gateway
- Scheduler
- Journal Consumer
- Trade History Consumer

주의:

- 도메인 내부에서 임의 생성되는 태스크
- 실패 추적이 어려운 fire-and-forget 태스크
- 취소/종료 경로가 없는 태스크

### 작업 방식

이 단계는 먼저 조사만 수행한다. 사용자 승인 없이 수정하지 않는다.

## 6. 공통 검증 명령

Python 문법 검증:

```bash
python -m py_compile <수정한 파일들>
```

프론트엔드 수정이 있을 때:

```bash
npm run build
```

앱 기동 검증:

```bash
/Users/sungjk0706/Desktop/SectorFlow/SectorFlow.command
```

앱 기동 후 확인:

- 백엔드 준비 완료
- 프론트엔드 준비 완료
- 브라우저 접속 가능
- 키움증권 인증/토큰 로그 정상
- 마이그레이션 스킵 로그 미출력
- 5일봉 다운로드 시 토큰 재발급 없음

## 7. 롤백 기준

다음 증상이 발생하면 해당 단계 수정을 중단한다.

- 앱 기동 실패
- 토큰 발급 실패
- 설정 로드 실패
- 업종순위 0종목 표시
- WebSocket 연결 실패
- 주문/체결 관련 예외 발생
- DB locked 또는 DB commit 실패
- 테스트모드와 실전투자 분기 이상

롤백 방식:

1. 수정 파일 목록 확인
2. 해당 단계에서 수정한 파일만 되돌림
3. 되돌린 뒤 py_compile 수행
4. 앱 재기동 확인
5. 원인 보고 후 대기

## 8. 하위 AI 에이전트 보고 형식

각 단계 완료 후 다음 형식으로 보고한다.

```markdown
## 단계 완료 보고

### 단계
- P0-1 DI Container 사용 범위 축소

### 수정한 파일
- 파일A:라인
- 파일B:라인

### 해결한 원인
- 중복 설정 캐시 경로 제거

### 검증한 항목
- py_compile 성공
- 앱 재기동 성공
- 설정 변경 반영 확인

### 남은 확인 사항
- 사용자가 직접 5일봉 다운로드 후 토큰 재발급 로그 확인 필요

### 다음 단계 제안
- P0-2 ThreadPoolExecutor 정리
```

## 9. 사용자에게 전달할 작업 지시 문구

사용자는 하위 AI 코딩에이전트에게 다음처럼 지시하면 된다.

```text
ARCHITECTURE_PROPOSAL.md와 ARCHITECTURE_REFACTOR_PLAN.md를 모두 읽어라.
ARCHITECTURE_PROPOSAL.md는 최종 설계 방향서이고,
ARCHITECTURE_REFACTOR_PLAN.md는 실행 지시서다.

단, 문서만 보고 바로 수정하지 말고,
각 단계 시작 전 현재 코드를 다시 읽고 호출처와 영향 범위를 확인한 뒤
수정 계획을 보고하고 내 승인을 받은 후 진행해라.

한 번에 한 단계씩 진행하고,
수정 후 py_compile과 앱 기동 검증 결과를 보고해라.
```

## 10. 최종 결론

하위 AI 코딩에이전트는 이 실행지시서만 단독으로 사용하면 안 된다.

반드시 다음 3개를 함께 사용한다.

1. `ARCHITECTURE_PROPOSAL.md` - 최종 방향서
2. `ARCHITECTURE_REFACTOR_PLAN.md` - 실행 지시서
3. 현재 코드 재조사 결과 - 실제 수정 근거

이 세 가지가 일치할 때만 수정한다.
