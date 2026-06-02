# SectorFlow 최적화 아키텍처 제안서

## 1. 목적

이 문서는 SectorFlow를 1인 로컬 실시간 데이터 처리 기반 주식 자동매매 웹앱으로 유지하면서, 현재 코드 구조를 최신 검증된 자동매매 시스템 아키텍처 원칙과 비교해 최적화 방향을 제안한다.

검토 기준은 다음과 같다.

- 단일 사용자 로컬 실행
- 실시간 시세 수신과 주문 처리의 지연 최소화
- 이벤트 기반 처리
- 주문/체결 무결성 보장
- SQLite 단일 저장소 유지
- 불필요한 분산 시스템, 외부 브로커, 과도한 DI 제거
- 설정과 마스터 데이터의 단일 소스 진리 유지
- 앱 기동 시 필요한 캐시만 단일 런타임 상태로 적재

## 2. 외부 아키텍처 기준 요약

웹 검색으로 확인한 실시간 자동매매/알고리즘 트레이딩 아키텍처 자료들은 공통적으로 다음 구성을 제시한다.

- Market Data Ingestion: 시세 수신 계층
- Event Queue: 이벤트 전달/순서 제어 계층
- Strategy/Compute Engine: 전략 판단 및 점수 계산 계층
- Risk Manager: 주문 전 위험 통제 계층
- OMS/Execution: 주문 관리 및 실행 계층
- Persistence/Audit: 주문, 체결, 설정, 상태 저장 계층
- UI/Monitoring Gateway: 화면 전송 및 상태 관찰 계층

대규모 시스템에서는 Kafka, Redis, TimescaleDB, 마이크로서비스가 사용된다. 하지만 1인 로컬 앱에서는 이 구성이 과하다. SectorFlow에는 프로세스 내부 `asyncio.Queue`, 단일 FastAPI 프로세스, SQLite WAL, 단일 DB 커넥션, 메모리 런타임 캐시가 더 적합하다.

## 3. 현재 SectorFlow 아키텍처 조사 결과

### 3.1 앱 기동 흐름

확인 파일: `backend/app/web/app.py`

- `app.py:18-20`: FastAPI lifespan에서 앱 시작/종료를 관리한다.
- `app.py:28-29`: DB Writer를 시작한다.
- `app.py:31-33`: 전역 큐를 초기화한다.
- `app.py:35-45`: SQLite 캐시 테이블과 마이그레이션을 실행한다.
- `app.py:55-65`: `integrated_system_settings`를 1회 로드한 뒤 `_integrated_system_settings_cache`에 반영한다.
- `app.py:67-69`: 기본 `ThreadPoolExecutor(max_workers=8)`를 설정한다.
- `app.py:85-95`: 체결 이력 Consumer와 Journal Consumer를 시작한다.
- `app.py:97-100`: `start_engine()`을 호출한다.
- `app.py:107-116`: `backend_coalescing`, `ws_manager`를 DI Container에 등록한다.
- `app.py:127-136`: 스케줄러와 텔레그램 후순위 태스크를 시작한다.

판단:

- 기동 순서 자체는 실시간 앱에 맞다.
- `settings`는 `_integrated_system_settings_cache`에 이미 반영되므로 DI Container 등록과 중복된다.
- `ThreadPoolExecutor(max_workers=8)`는 1인 로컬 앱 기준으로 과하다.

### 3.2 이벤트 큐 구조

확인 파일: `backend/app/services/core_queues.py`

- `core_queues.py:5-13`: 4개 코어 큐를 명시한다.
- `core_queues.py:23-27`: 큐 크기를 분리한다.
- `core_queues.py:37-54`: 앱 기동 시 전역 큐를 초기화한다.
- `core_queues.py:85-109`: `tick_queue`에 드롭 정책을 적용한다.

현재 큐 구성:

- `tick_queue`: 시세 수신 전용, 최신성 우선
- `order_queue`: 주문/체결 전용, 드롭 금지
- `broadcast_queue`: UI 전송 전용
- `control_queue`: 사용자 제어 전용, 우선순위 큐

판단:

- 1인 로컬 HTS형 자동매매 앱에 적합하다.
- 외부 메시지 브로커 없이 `asyncio.Queue`를 사용하는 방향이 현재 규모에 적합하다.
- 단, 코드 주석의 “이벤트 버스” 표현은 프로젝트 원칙의 “EventBus/발행구독 패턴 금지”와 혼동된다. 실제 구현은 외부 브로커나 느슨한 pub/sub가 아니라 명시적 큐 배관이다. 명칭은 “Core Queues” 또는 “Pipeline Queues”가 더 정확하다.

### 3.3 Compute/OMS/Gateway 파이프라인

확인 파일:

- `backend/app/services/pipeline_compute.py`
- `backend/app/services/pipeline_oms.py`
- `backend/app/services/pipeline_gateway.py`
- `backend/app/services/engine_loop.py`

확인 내용:

- `pipeline_compute.py:5-12`: `tick_queue`에서 시세를 받아 전략/점수/주문 후보를 계산한다.
- `pipeline_compute.py:119-157`: tick 이벤트를 순차 처리하고 `await asyncio.sleep(0)`으로 협력적 양보를 수행한다.
- `pipeline_oms.py:5-14`: 주문/체결 데이터 드롭 금지와 순서 보존을 명시한다.
- `pipeline_oms.py:101-138`: Pending 주문이 없으면 서버 원장 조회를 생략한다.
- `pipeline_gateway.py:5-15`: UI 전송은 `broadcast_queue`를 통해 수행하고 100ms Coalescing을 적용한다.
- `engine_loop.py:352-367`: Compute, OMS, Gateway 루프를 백그라운드 태스크로 시작한다.

판단:

- 데이터 수신, 계산, 주문, 화면 전송이 분리되어 있어 표준 자동매매 구조에 부합한다.
- 주문 큐와 시세 큐를 분리한 점은 적합하다.
- Gateway의 Coalescing은 UI 폭주 방지에 적합하다.
- 주의점은 `asyncio.create_task`가 여러 곳에서 사용된다는 점이다. 중앙 코디네이터에서 관리되는 장기 루프는 허용하고, 도메인 내부 임의 분산 태스크는 줄이는 기준이 필요하다.

### 3.4 DB 구조

확인 파일:

- `backend/app/db/database.py`
- `backend/app/db/db_writer.py`

확인 내용:

- `database.py:9-31`: SQLite 단일 커넥션을 공유한다.
- `database.py:25-29`: WAL, synchronous NORMAL, cache_size, temp_store MEMORY를 설정한다.
- `database.py:43-45`: DB 쓰기 Lock을 제공한다.
- `db_writer.py:4-15`: DB Writer는 단일 쓰기 직렬화 역할을 가진다.
- `db_writer.py:78-109`: 단일 DB 쓰기 작업을 Lock 안에서 처리하고 commit/rollback을 수행한다.

판단:

- SQLite 단일화와 WAL 구성은 1인 로컬 시스템에 적합하다.
- DB Writer는 주문/체결/상태 저장의 순서 보장에 유리하다.
- 단, 모든 DB 쓰기가 실제로 DB Writer를 통과하는지 별도 점검이 필요하다. 직접 `conn.commit()`이 여러 도메인에 남아 있으면 단일 쓰기 직렬화 원칙이 약해진다.

### 3.5 DI Container

확인 파일:

- `backend/app/di/container.py`
- `backend/app/web/app.py`
- `backend/app/core/settings_store.py`

확인 내용:

- `container.py:13-18`: `_services`, `_singletons`를 가진 단일 Container를 구현한다.
- `container.py:25-34`: 이름 기반 싱글톤 등록/조회 기능이 있다.
- `app.py:60`: `settings`를 등록한다.
- `app.py:110`: `backend_coalescing`을 등록한다.
- `app.py:115`: `ws_manager`를 등록한다.
- `settings_store.py:242-247`: `settings` 싱글톤을 조회해 변경 키를 반영한다.

판단:

- 현재 실제 사용이 확인된 것은 `settings` 조회다.
- `backend_coalescing`, `ws_manager`는 등록 로그는 있지만 조회 사용 근거가 확인되지 않았다.
- 1인 로컬 앱에는 현재 형태의 DI Container가 과하다.
- `engine_state._integrated_system_settings_cache`가 이미 런타임 설정 단일 캐시 역할을 수행하므로 DI Container의 `settings`는 중복 경로다.

제안:

- DI Container는 제거하거나 테스트 전용으로 축소한다.
- 런타임 설정 접근은 `_integrated_system_settings_cache` 단일 경로로 통일한다.
- `backend_coalescing`, `ws_manager`는 각 모듈의 명시적 싱글톤 또는 직접 import로 유지한다.

### 3.6 ThreadPoolExecutor

확인 파일:

- `backend/app/web/app.py`
- `backend/app/services/market_close_pipeline.py`
- `backend/app/services/engine_loop.py`

확인 내용:

- `app.py:67-69`: `loop.set_default_executor(ThreadPoolExecutor(max_workers=8))`를 설정한다.
- `market_close_pipeline.py:12, 26`: `_CONFIRMED_FETCH_EXECUTOR = ThreadPoolExecutor(max_workers=1)`가 선언되어 있다.
- 검색 결과 `_CONFIRMED_FETCH_EXECUTOR.submit(...)` 호출은 확인되지 않았다.
- 검색 결과 `run_in_executor` 호출은 확인되지 않았다.
- `engine_loop.py:90, 109`: `asyncio.to_thread()`가 토큰 발급 래핑에 사용된다.

판단:

- `set_default_executor(max_workers=8)`는 `asyncio.to_thread()`의 기본 실행 풀에 영향을 준다.
- 1인 로컬 앱에서 8개 워커는 과하다.
- 토큰 발급처럼 짧고 낮은 빈도의 동기 래핑은 전용 async 구현 또는 제한된 executor로 충분하다.
- `_CONFIRMED_FETCH_EXECUTOR`는 현재 미사용 데드 코드로 판단된다.

제안:

- `_CONFIRMED_FETCH_EXECUTOR`는 삭제한다.
- 기본 executor는 제거하거나 `max_workers=2`로 제한한다.
- 장기적으로 Kiwoom/LS REST 호출을 async HTTP 클라이언트로 통일해 `to_thread()` 의존을 줄인다.

## 4. 캐시 구조와 단일 캐시 필요성

### 4.1 현재 확인된 핵심 런타임 캐시

확인 파일: `backend/app/services/engine_state.py`

주요 캐시/상태:

- `_integrated_system_settings_cache`: 런타임 설정 캐시
- `_master_stocks_cache`: 종목 마스터/확정 데이터 메모리 캐시
- `_broker_tokens`: 증권사별 토큰 캐시
- `_access_token`: 현재 기준 증권사 접근 토큰
- `_rest_api`: 기준 증권사 REST 인스턴스
- `_account_snapshot`: 계좌 스냅샷
- `_positions`: 보유 종목
- `_snapshot_history`: 계좌 스냅샷 이력
- `_sector_score_index`: 업종 점수 인덱스
- `_buy_targets_cache_ref`: 매수 후보 참조 캐시

확인 파일: `backend/app/services/pipeline_gateway.py`

- `_coalesce_cache`: UI 전송 Coalescing용 짧은 수명 캐시

확인 파일: `backend/app/core/broker_factory.py`

- `_router_cache`: BrokerRouter 싱글톤 캐시

### 4.2 이미 제거되었거나 통합된 캐시 흔적

`engine_state.py:56-72`, `engine_cache.py:69-126`에서 여러 캐시가 제거 또는 통합된 사실이 확인된다.

제거/통합 흔적:

- `_sector_stock_layout` 제거 → `_integrated_system_settings_cache["sector_stock_layout"]`로 통합
- `_avg_amt_5d` 제거 → `_master_stocks_cache`에서 직접 사용
- `_amts_5d_arrays`, `_highs_5d_arrays` 제거 → `stock_5d_array` 테이블에서 직접 읽도록 대체
- 실시간 틱 데이터 캐시 제거
- `_sector_stocks_cache` 제거 → `_master_stocks_cache` 기반 필터링
- `_buy_targets_snapshot_cache` 제거 → `sector_summary_cache.buy_targets`와 중복 제거
- `_sector_summary_cache`는 `engine_service` 단일 소스로 통합한다는 주석 존재

판단:

- 캐시 단일화 방향은 이미 진행되어 있다.
- 하지만 `engine_state.py`, `engine_service.py`, `engine_cache.py`, `engine_bootstrap.py` 사이에 캐시 소유권이 분산되어 있어 유지보수 비용이 남아 있다.
- 특히 `_integrated_system_settings_cache`와 DI Container `settings`는 중복 경로다.
- `_broker_tokens`, `_access_token`, `_rest_api`, `BrokerRouter._router_cache`, `KiwoomRestAPI._token_info`는 인증/브로커 상태의 다중 캐시처럼 동작한다. 토큰 재발급 이슈는 이 중복 소유권에서 발생했다.

### 4.3 앱 기동 시 단일 캐시가 필요한 이유

1인 로컬 실시간 자동매매 앱에서 앱 기동 시 단일 런타임 캐시는 필요하다.

이유:

- 설정을 매번 DB에서 읽으면 실시간 처리 중 DB I/O가 증가한다.
- 종목 마스터 데이터를 매번 DB에서 읽으면 필터링과 업종 계산이 지연된다.
- 주문/체결 처리 중 설정 기준이 흔들리면 같은 이벤트에 다른 기준이 적용된다.
- 토큰/REST 인스턴스가 여러 개면 같은 증권사에 중복 인증 요청이 발생한다.
- UI 초기 스냅샷과 실시간 delta가 서로 다른 기준 데이터를 사용할 수 있다.

따라서 단일 캐시는 필요하다. 다만 “여러 목적의 단일 캐시”가 아니라 “도메인별 소유자가 명확한 최소 캐시”가 필요하다.

## 5. 최종 권장 아키텍처

SectorFlow에 최적화된 구조는 다음과 같다.

```text
FastAPI Lifespan
  ├─ SQLite 단일 커넥션 초기화 (WAL)
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

### 5.1 유지할 것

- FastAPI 단일 프로세스
- 단일 asyncio 이벤트 루프
- SQLite + WAL + aiosqlite 단일 커넥션
- DB Writer 단일 쓰기 직렬화
- `asyncio.Queue` 기반 명시적 파이프라인
- `tick_queue`, `order_queue`, `broadcast_queue`, `control_queue` 분리
- `order_queue` 드롭 금지
- `tick_queue` 최신성 우선 드롭 정책
- Gateway Coalescing
- BrokerRouter 싱글톤
- 앱 기동 시 설정/마스터 데이터 메모리 적재

### 5.2 줄일 것

- DI Container
- 미사용 ThreadPoolExecutor
- 기본 executor 과다 워커
- 중복 설정 캐시
- 토큰/REST 인스턴스의 다중 소유권
- 도메인 내부 임의 `create_task`
- 개발자용 INFO 로그

### 5.3 새로 명확히 할 것

#### RuntimeState 단일 진입점

현재 `engine_state.py`는 전역 상태 저장소 역할을 한다. 이를 명시적 책임으로 정리한다.

권장 분리:

- `RuntimeSettings`: 설정 캐시
- `MarketDataStore`: 종목 마스터/실시간 상태
- `BrokerSession`: 토큰, REST 인스턴스, WebSocket Connector
- `AccountState`: 계좌/포지션/스냅샷
- `PipelineState`: 큐와 루프 상태

단, 파일을 무리하게 대규모 리팩토링하지 않고 현재 구조에서는 `engine_state.py` 안의 소유권 주석과 접근 함수를 먼저 정리한다.

#### BrokerSession 단일화

토큰 재발급 방지를 위해 다음 원칙이 필요하다.

- 증권사별 AuthProvider는 `BrokerRouter`가 1회 생성한다.
- REST 인스턴스는 AuthProvider 내부의 1개를 공유한다.
- 토큰 캐시는 `KiwoomRestAPI._token_info`를 원천으로 둔다.
- `_broker_tokens`와 `_access_token`은 UI 상태 반영용 파생값으로 제한한다.
- 다운로드/배치 파이프라인도 반드시 `get_router()`를 사용한다.

#### Cache Ownership Table

| 데이터 | 원천 저장소 | 런타임 캐시 | 소유자 | 비고 |
|---|---|---|---|---|
| 통합 설정 | integrated_system_settings | `_integrated_system_settings_cache` | engine_state | DI settings 제거 권장 |
| 종목 마스터 | master_stocks_table | `_master_stocks_cache` | engine_state | 필터/업종 계산 기준 |
| 5일봉 배열 | stock_5d_array | 필요 시 조회 | DB | 메모리 중복 캐시 금지 |
| 토큰 | Kiwoom REST 응답 | `KiwoomRestAPI._token_info` | BrokerSession | `_access_token`은 파생값 |
| 계좌 | 증권사 REST/WS | `_account_snapshot`, `_positions` | AccountState | 테스트모드도 같은 흐름 |
| 업종 점수 | `_master_stocks_cache` + 실시간 입력 | `_sector_score_index` | SectorCompute | 전체 중복 캐시 금지 |
| UI 전송 병합 | 실시간 이벤트 | `_coalesce_cache` | Gateway | 짧은 수명 캐시만 허용 |

## 6. 우선순위별 개선 제안

### P0: 안정성/중복 제거

1. DI Container 제거 또는 축소
   - `settings`는 `_integrated_system_settings_cache`만 사용한다.
   - `backend_coalescing`, `ws_manager` 등록은 제거한다.
   - 테스트용 reset이 필요하면 테스트 헬퍼로만 남긴다.

2. BrokerSession 단일화 문서화 및 강제
   - `BrokerRouter()` 직접 생성 금지
   - `get_router()`만 사용
   - 토큰 원천은 `KiwoomRestAPI._token_info`로 고정

3. 미사용 `_CONFIRMED_FETCH_EXECUTOR` 삭제
   - `market_close_pipeline.py:26` 선언은 submit 사용처가 확인되지 않았다.

4. 기본 ThreadPoolExecutor 축소
   - `max_workers=8`을 제거하거나 `max_workers=2`로 제한한다.
   - 장기적으로 REST 동기 호출을 async HTTP로 전환한다.

### P1: 캐시 소유권 명확화

1. `engine_state.py`의 상태를 도메인별 구역으로 재정렬한다.
2. `_integrated_system_settings_cache` 접근 함수를 표준화한다.
3. `_master_stocks_cache` 갱신 경로를 `load`, `batch refresh`, `realtime update`로 구분한다.
4. `_sector_summary_cache` 위치를 하나로 확정한다.
5. 모든 캐시에 “원천/파생/수명/갱신자”를 명시한다.

### P2: 관측성과 로그 정리

1. 사용자 로그와 개발자 로그를 분리한다.
2. 앱 기동 로그는 사용자에게 필요한 단계만 INFO로 둔다.
3. 내부 구현 로그는 DEBUG로 전환하거나 제거한다.
4. 실시간 지연 50ms/200ms 기준 로그는 유지한다.

### P3: 장기 개선

1. 동기 REST 래핑 제거
   - `asyncio.to_thread()` 사용 지점을 async HTTP로 교체한다.
2. 중앙 태스크 코디네이터 도입
   - 장기 루프 태스크만 중앙에서 생성/종료한다.
3. DB Writer 사용률 점검
   - 직접 commit 경로를 조사해 단일 쓰기 직렬화 원칙을 강화한다.

## 7. 최종 의견

현재 SectorFlow는 1인 로컬 실시간 자동매매 앱에 필요한 핵심 구조를 이미 갖고 있다.

적합한 부분:

- 단일 FastAPI 프로세스
- 단일 asyncio 이벤트 루프
- 명시적 파이프라인 큐
- 시세/주문/UI/제어 큐 분리
- SQLite WAL
- DB Writer 단일 쓰기
- 마스터 데이터 메모리 적재
- Gateway Coalescing

과하거나 위험한 부분:

- DI Container는 현재 범위에서 과하다.
- `ThreadPoolExecutor(max_workers=8)`는 1인 로컬 환경에 과하다.
- 미사용 `_CONFIRMED_FETCH_EXECUTOR`는 삭제 대상이다.
- 설정 캐시와 DI settings는 중복 경로다.
- 토큰/REST 인스턴스 소유권이 분산되면 중복 인증이 재발한다.

최적화 방향:

- 외부 브로커/Kafka/Redis를 추가하지 않는다.
- 마이크로서비스로 나누지 않는다.
- DI Container를 제거하거나 최소화한다.
- 단일 RuntimeState와 BrokerSession을 명확히 한다.
- 앱 기동 시 설정/마스터/브로커 세션 캐시는 1회만 만들고, 이후에는 해당 캐시를 단일 기준으로 사용한다.

## 8. 실행 순서 제안

1. 문서 기준 확정
2. DI Container 제거 범위 확정
3. ThreadPoolExecutor 축소/삭제
4. BrokerSession 단일화 규칙 검색 검증
5. 캐시 소유권 표를 코드 주석 또는 별도 문서로 반영
6. py_compile 검증
7. 앱 재기동 로그 확인
8. 5일봉 다운로드 시 토큰 재발급 미발생 확인
