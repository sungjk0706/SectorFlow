# SectorFlow 아키텍처

> 1인 로컬 주식 자동매매 웹앱 — Python 백엔드 + TypeScript 프론트엔드  
> 단일 asyncio 이벤트 루프 기반 실시간 파이프라인 아키텍처

---

# 제1부: 철학과 원칙 (정신)

## 핵심 가치

- **초저지연**: 50ms 미만 틱 처리, 200ms 초과 시 자동매매 중단
- **단순성**: 단일 이벤트 루프, 단일 SQLite, 직접 SQL, 직접 호출 체인
- **신뢰성**: 근본 원인 해결, 런타임 검증, 테스트모드 동등성

---

## 불변 원칙 24개

### 원칙 1: 단일 asyncio 이벤트 루프
**내용**: 모든 비동기 작업은 단일 이벤트 루프 내에서 처리  
**구현 가이드**:
- `main.py`에서 `uvicorn.run(..., loop="uvloop")` 사용
- 모든 코루틴은 단일 루프에서 실행
- 멀티스레드 금지 (원칙 14)

### 원칙 2: 모든 I/O는 async def
**내용**: 동기 함수 금지, 모든 I/O는 비동기로 처리  
**구현 가이드**:
- HTTP: `httpx.AsyncClient` 사용 (동기 `requests` 금지)
- DB: `aiosqlite` 사용 (동기 `sqlite3` 금지)
- 대기: `asyncio.sleep()` 사용 (동기 `time.sleep()` 금지)
- 락: `asyncio.Lock` 사용 (동기 `threading.Lock` 금지)

### 원칙 3: run_in_executor 우회 금지
**내용**: 동기 코드를 비동기로 위장하는 행위 금지  
**구현 가이드**:
- `loop.run_in_executor()` 사용 금지
- 진짜 async 라이브러리로 교체

### 원칙 4: 증권사 이름 공통 기능 침투 금지
**내용**: 특정 증권사 이름이 공통 로직에 침투하는 것 금지  
**구현 가이드**:
- `BrokerRouter` + `ConnectorManager` 추상화 사용
- 공통 로직에 `kiwoom_`, `ls_` 접두사 금지
- 증권사별 구현은 `broker_factory.py` 레지스트리에서 분리

### 원칙 5: EventBus/발행구독 패턴 사용 금지
**내용**: 직접 호출 체인 유지, asyncio.Queue 파이프라인으로 일원화  
**구현 가이드**:
- Redis/Pub-Sub 금지
- 콜백 리스트 옵서버 패턴 금지
- `tick_queue` → `Compute Loop` → 직접 호출(`execute_buy`/`execute_sell`) → `OMS` 명시적 파이프라인

### 원칙 6: SQLite 단일화
**내용**: 데이터베이스는 SQLite 하나로 통일, ORM·무거운 추상화 금지  
**구현 가이드**:
- PostgreSQL/MySQL 금지
- SQLAlchemy 등 ORM 금지
- Raw SQL 직통 사용
- 단일 커넥션 (원칙 12)

### 원칙 7: 블로킹 = 지연 = 왜곡 = 망함
**내용**: 블로킹은 지연을 유발하고 데이터를 왜곡시키며 시스템을 망침  
**구현 가이드**:
- `_handle_real_01_tick`에 per-tick O(n) 연산 금지
- 매 틱마다 DB 조회 금지
- 매 틱마다 전체 리스트 순회 금지
- `asyncio.sleep(0)`로 협력적 양보

### 원칙 8: 실시간 파이프라인과 배치 파이프라인 분리
**내용**: 두 파이프라인은 명확히 분리  
**구현 가이드**:
- 실시간: `tick_queue`, `Compute Loop`, `Gateway Loop`
- 배치: `market_close_pipeline.py` (20:40 확정 시세, 5일봉)
- 물리적 루프와 데이터 배관 완전 분리

### 원칙 9: 각 파이프라인 독립, 상호 간섭 금지
**내용**: 파이프라인 간 상호 의존/간섭 금지  
**구현 가이드**:
- 배치 연산 중 실시간 틱 수집 차단 금지
- 실시간 루프에서 대량 디스크 쓰기 금지
- `db_write_queue`로 쓰기 직렬화

### 원칙 10: 단일 소스 진리 (SSOT)
**내용**: 같은 데이터는 한 곳에서만 관리  
**구현 가이드**:
- 설정: `integrated_system_settings_cache` (메모리) → SQLite (영속)
- 종목 정보: `master_stocks_cache` (메모리) → `master_stocks_table` (영속)
- 모든 모듈이 캐시를 직접 참조

### 원칙 11: 이벤트 기반 루프
**내용**: 폴링 금지, 이벤트 기반으로만 처리  
**구현 가이드**:
- `while + sleep` 폴링 금지
- `asyncio.Queue` + `asyncio.wait()` 사용
- `daily_time_scheduler.py`에서 `asyncio.call_later()` 사용

### 원칙 12: DB 연결 매번 생성/파기 금지
**내용**: DB 연결은 앱과 생명주기 공유  
**구현 가이드**:
- `database.py`에서 `_db_connection` 싱글톤
- 앱 시작 시 1회 생성, 앱 종료 시까지 유지
- 매 요청마다 `connect()` 금지

### 원칙 13: 설정 매번 DB 쿼리 금지
**내용**: 설정은 메모리 상주  
**구현 가이드**:
- 앱 로드 시 `load_integrated_system_settings()`로 캐시
- 설정 변경 시: DB 저장 → 캐시 갱신 → `apply_settings_change()`
- 틱 연산 단계에서는 O(1) 메모리 딕셔너리 조회

### 원칙 14: 멀티스레드 남용 금지
**내용**: 단일 루프 사용  
**구현 가이드**:
- `threading.Thread()` 신규 생성 금지
- `asyncio.create_task()` 무분별한 분리 금지
- 기존 이벤트 루프 활용

### 원칙 15: 단일 주문 경로
**내용**: 주문 경로는 하나만. 병렬/죽은 주문 경로 금지.  
**구현 가이드**:
- `trading.py` → `execute_buy()` / `execute_sell()` 단일 경로
- 테스트모드: `dry_run.fake_send_order()`
- 실전: `router.order.send_order()`
- 주문 로직 분기 금지

### 원칙 16: "구현 = 살아있는 경로에 배선됨"
**내용**: 안전/제어 장치는 실제 실행 경로에 연결되어 동작 입증돼야 함  
**구현 가이드**:
- `RiskManager`는 `execute_buy()`/`execute_sell()` 내부에서 호출
- `CircuitBreaker`는 주문 전후에 호출
- 호출 안 되는 안전코드는 위험한 착시

### 원칙 17: 플래그 단일 소스
**내용**: 한 플래그는 정의·설정·읽기가 같은 변수를 가리켜야 함.  
**구현 가이드**:
- `auto_buy_on`은 `integrated_system_settings_cache`에서만 관리
- 플래그 설정 함수는 하나만
- 여러 곳에서 플래그 직접 수정 금지

### 원칙 18: 테스트모드 동등성
**내용**: 테스트모드와 실전모드는 돈 I/O만 다르고, 그 외 모든 과정은 동일  
**구현 가이드**:
- 모드 분기는 돈 I/O 최소 지점에만 (`dry_run.fake_send_order()`)
- 모든 안전장치는 테스트모드에서 검증 가능
- 업종 점수 계산, 필터링, 타이밍 로직은 동일

### 원칙 19: 런타임 검증 게이트
**내용**: py_compile/import 성공은 검증이 아님  
**구현 가이드**:
- 변경은 실제 실행경로를 흘려보는 런타임 점검
- `RuntimeWarning(coroutine never awaited)`을 error로 승격
- 테스트로 실제 동작 검증

### 원칙 20: 폴백 금지 — 근본 원인 해결 방해
**내용**: 폴백(fallback) 코드는 정상 경로의 불안정성을 은폐하고 근본 원인 해결을 방해함  
**구현 가이드**:
- 정상 경로에서 절대 발생하지 않아야 할 상태(빈 문자열, None, 누락)를 폴백으로 덮지 말 것
- 폴백 분기가 필요하다는 것 자체가 상위 초기화나 데이터 흐름에 결함이 있다는 신호
- 결함이 발견되면 폴백으로 덮지 말고 **원인을 제거**할 것 (초기값 수정, 데이터 흐름 수정)
- 부득이하게 예외 상황을 처리해야 한다면 silent fallback이 아니라 **에러 로그**를 출력하여 즉시 인지 가능하게 할 것
- SSOT 원칙(원칙 10)과 충돌: 폴백은 사실상 제2의 데이터 소스를 만드는 것

### 원칙 21: 사용자 투명성 (User Transparency)

#### 21-1. 사용자 모르는 로직 금지
사용자가 인지하지 못하는 상태에서 중요한 의사결정(매수/매도, 리스크 차단 등)이 이루어져서는 안 된다.
중요한 로직은 반드시 사용자와 사전에 상의하거나, 설정으로 제어할 수 있어야 한다.

#### 21-2. 백엔드 동작의 UI 표시 의무
백엔드에서 발생하는 중요한 상태 변화(매수 차단, 리스크 초과, 가드 조건 충족 등)는
프론트엔드 UI에서 사용자가 확인할 수 있도록 표시되어야 한다.
사용자가 "왜 이 종목이 매수되지 않았지?" 또는 "왜 이렇게 되었지?"라고 의문을 가지지 않도록 해야 한다.

### 원칙 22: 데이터 정합성 (Data Consistency)

**내용**: SSOT(원칙 10)는 데이터 출처를 하나로 통일하지만, 파이프라인의 여러 단계를 거치는 데이터 조작 시 단계 간 일관성은 별도로 보장해야 함

**배경**: 유령 포지션 사례 (`docs/ghost_position_investigation.md`)에서 `_test_positions`와 `trade_history`가 독립적으로 영속화되어, 중단/예외 시 두 시스템 간 불일치로 유령 포지션이 발생함. SSOT 원칙만으로는 파이프라인 단계 간 일관성을 보장할 수 없음

**구현 가이드**:
- **파생 데이터 모델 선호**: 두 번째 데이터 저장소를 운영하는 대신, 하나의 원본에서 다른 데이터를 파생(예: `trades` 테이블 → `build_positions_from_trades()`로 포지션 산출). 중복 저장 금지
- **원자성 보장**: 다중 단계 데이터 조작이 불가피할 경우, 단일 트랜잭션으로 묶거나 순차 실행 보장. 중단/예외 시 부분 영속화 방지
- **기동 시 대조(reconciliation)**: 메모리 상태와 영속화된 상태 간 불일치 탐지 및 정정. 테스트모드에서도 대조 스킵 금지 (원칙 18 준수)
- **불일치 발견 시 즉시 차단**: silent 무시 금지 — `logger.critical` 경고 + 관련 파이프라인 중단. 유령 데이터가 후속 파이프라인(매도 등)에 전파되는 것을 원천 차단
- **SSOT와의 관계**: 원칙 10이 "출처를 하나로"라면, 원칙 22는 "출처가 하나여도 파이프라인 단계 간 일관성을 별도로 검증하라"

### 원칙 23: 일관된 통일성 (Consistent Unity)

**내용**: 같은 의미/기능을 가리키는 대상은 코드/화면/로그/문서 전 영역에서 하나의 방식으로 통일. 파일 간 불일치 금지.

**배경**: 1인 로컬 시스템에서는 다수 개발자 간 합의 비용이 없으나, 파일 간 에러 처리·비동기 패턴·네이밍·상수 관리·UI 패턴·용어가 불일치하면 동일한 기능을 중복 구현하거나, 한 파일의 변경이 다른 파일에 전파되지 않아 정합성이 깨짐. SSOT(원칙 10)가 데이터 출처 단일화를 다루면, P23은 표현·구현 방식의 단일화를 다룸.

**구현 가이드**:
- **용어 통일**: 표준 용어 사전(부록 L 참조) 준수
  - "업종" 사용, "섹터" 금지
  - "종목" 사용, "주식" 금지
  - 증권사 표시명은 사전에 정한 표시명 사용 (예: "LS증권" — 기존 로그 한글화 작업과 일관)
- **백엔드 에러 처리 일관성**: 모든 모듈이 동일한 에러 처리 패턴 사용
  - `except Exception as e: logger.warning(..., exc_info=True)` 패턴
  - silent `except: pass` 금지 (원칙 20과 중복 강화)
  - 에러 로그 메시지 형식 통일 (한국어 + 대상 명시)
- **백엔드 비동기 패턴 일관성**: 동일한 상황에서 동일한 async 패턴 사용
  - 타임아웃 처리 방식 통일 (`asyncio.wait_for` vs 수동 `asyncio.sleep` 체크 중 하나 일관)
  - 병렬 처리가 필요한 경우 `asyncio.gather` 사용, 순차 처리가 필요한 경우 순차 `await` — 혼용 금지
  - 백그라운드 태스크는 `schedule_engine_task()`로 통일
- **백엔드 네이밍 일관성**: 파일/함수/변수 명명 규칙 통일
  - Python: `snake_case` (PEP 8 준수)
  - 증권사별 코드는 `kiwoom_`/`ls_` 접두사 (원칙 4와 일관)
  - 공통 로직은 증권사 접두사 없이 (원칙 4)
- **백엔드 상수 관리 일관성**: 매직 넘버는 `core/constants.py`에 집중 관리
  - 파일 간 분산된 상수 정의 금지
  - 동일한 의미의 상수가 여러 파일에 중복 정의 금지 (SSOT 원칙 10과 중복 강화)
- **프론트엔드 UI 패턴 일관성**: 동일한 UI 패턴(목록/카드/태그/버튼/모달 등)이 2회 이상 반복 시 `components/common/` 하위 공통 컴포넌트로 추출, 직접 중복 구현 금지
- **신규 구현 전 기존 공통 자산 검색 (사전 절차)**: 새 함수/컴포넌트/상수/표준 색상/패턴을 만들기 전에 동일 또는 유사 기능의 기존 공통 자산을 먼저 검색하고 활용. 같은 기능을 새로 만들지 않음. (백엔드: `core/constants.py`·공통 유틸·기존 함수 / 프론트엔드: `components/common/`·공통 함수·표준 색상. 절차 상세는 AGENTS.md 섹션3 규칙 0-2.4)

**SSOT(원칙 10)와의 관계**: P10은 데이터 출처 단일화, P23은 표현/구현 방식 단일화

### 원칙 24: 단순성 (Simplicity)

**내용**: 같은 기능을 더 단순한 방법으로 구현할 수 있다면 단순한 쪽을 선택. 불필요한 추상화, 과도한 간접 계층, 복잡한 구현을 금지.

**배경**: 핵심 가치(단일 이벤트 루프, 단일 SQLite, 직접 SQL, 직접 호출 체인)가 아키텍처 구조 단순성을 규정하나, 코드 구현 단계의 단순성은 별도로 점검 필요. 1인 로컬 시스템에서 과도한 추상화는 유지보수 비용만 증가시키고 디버깅을 어렵게 함. 기존 부록 H(리팩토링 기준)·부록 I(YAGNI/DRY)에 산재한 단순성 기준을 불변 원칙으로 승격.

**구현 가이드**:
- **더 단순한 대체 가능성**: 같은 결과를 내는 더 단순한 방법이 존재하면 복잡한 구현 금지
- **불필요한 추상화 금지**:
  - 단일 호출처를 위한 인터페이스/추상 클래스 금지 (YAGNI)
  - 1회 사용 래퍼 함수, 1회 사용 제네릭 헬퍼 금지
  - 언어/표준 라이브러리가 제공하는 기능을 직접 재구현 금지
- **복잡도 기준** (기존 부록 H 기준 승격):
  - 함수 50줄 이하, 파일 500줄 이하
  - 순환 복잡도 10 이하
- **중복 로직 추출** (기존 부록 I DRY 기준 승격):
  - 같은 로직 3회 이상 반복 시 함수/클래스 추출
  - 단, 과도한 추상화로 가독성 저하 금지 (P24 자체와 균형)

**P16(구현=살아있는 경로)과의 관계**: P16은 dead code 금지, P24는 살아있는 코드라도 더 단순해질 수 있는지 점검

---

## 금지 패턴 (확정)

> 본 항목은 실제 코드에서 발견·수정된 아키텍처 위반 사례를 명시적으로 기록하여,
> 동일한 문제가 재발하지 않도록 방지하는 것을 목적으로 한다.

### 1. asyncio.run() 사용 금지
- **위반 사례**: `ls_providers.py`에서 `_run_async()`로 새 이벤트 루프 생성
- **관련 원칙**: 원칙 1 (단일 asyncio 이벤트 루프), 원칙 2 (모든 I/O는 async def)
- **이유**: 단일 이벤트 루프 원칙 위반 — 새 이벤트 루프 생성은 기존 루프와 충돌, 예외 추적 불가
- **대체**: `async def`로 선언하고 `await` 직접 호출

### 2. create_task 무분별한 분리 금지
- **위반 사례**: `engine_cache.py`, `dry_run.py`에서 `done_callback` 없는 fire-and-forget `create_task`
- **관련 원칙**: 원칙 5 (직접 호출 체인 유지), 원칙 14 (멀티스레드 남용 금지)
- **이유**: 예외 추적 불가, 호출 체인 단절 — 태스크 실패 시 조용히 사라짐
- **대체**: `schedule_engine_task()` 사용 (내부적으로 `add_done_callback`으로 예외 로깅) 또는 `add_done_callback()` 직접 추가

### 3. except Exception: pass 금지
- **위반 사례**: 9개 파일에서 예외를 조용히 삼킴 (`except Exception: pass`)
- **관련 원칙**: 원칙 20 (폴백 금지 — 근본 원인 해결 방해)
- **이유**: 오류 은폐, 디버깅 불가 — 예외가 발생했는지조차 알 수 없음
- **대체**: `logger.warning()`으로 예외 로깅 — `except Exception as e: logger.warning("...", e, exc_info=True)`

### 4. async 함수 호출 시 await 누락 금지
- **위반 사례**: `_broadcast()`가 `async def`로 선언되었으나 호출부에 `await` 누락 (10개 파일, 12개 호출소)
- **관련 원칙**: 원칙 2 (모든 I/O는 async def), 원칙 5 (직접 호출 체인 유지), 원칙 19 (런타임 검증 게이트)
- **이유**: `RuntimeWarning: coroutine was never awaited` 발생, 코루틴이 GC되어 실제 전송 실패
- **대체**: 
  - `async def` 함수 내에서는 `await _broadcast(...)` 
  - 동기 함수 내에서는 `schedule_engine_task(_broadcast(...), context="...")`로 래핑
- **검증 방법**: `python -W error::RuntimeWarning main.py`로 기동 시 RuntimeWarning을 에러로 승격하여 검증

### 5. no-op/dead code 방치 금지
- **위반 사례**: `notify_snapshot_history_update`, `notify_desktop_buy_radar_only` 등 호출되지 않는 함수 방치
- **관련 원칙**: 원칙 16 ("구현 = 살아있는 경로에 배선됨")
- **이유**: 아키텍처 문서와 실제 코드 불일치 — 호출 안 되는 함수는 존재하지 않는 것과 같음
- **대체**: 사용하지 않는 함수는 삭제하거나, 명시적으로 `# DEPRECATED: ...` 주석으로 표시

---

## 아키텍처 타당성 검증

### 1인 로컬 자동매매 시스템 최적성 분석

#### 단일 asyncio 이벤트 루프 및 멀티스레드 남용 금지
**타당성 (최적)**
- 파이썬 GIL로 인해 멀티스레드는 CPU 연산 병렬 처리 불가
- 초당 수천 틱 처리 시 스레드 간 락 경쟁은 레이턴시 병목 유발
- 단일 asyncio 이벤트 루프는 협동적 멀티태스킹으로 I/O 대기 시간 효율화

#### 모든 I/O는 async def 및 run_in_executor 우회 금지
**타당성 (최적)**
- 단 하나의 동기 I/O 작업이 이벤트 루프 전체 멈춤
- run_in_executor는 스레드 풀 생성/컨텍스트 스위칭 비용 누적으로 레이턴시 스파이크 유발
- 모든 I/O를 aiosqlite, httpx 등 async/await 계열 라이브러리로 일관 규정이 50ms 미만 지연 보장

#### SQLite 단일화 및 ORM·무거운 추상화 금지
**타당성 (최적)**
- PostgreSQL/MySQL은 TCP/IP 루프백 네트워크 홉, 쿼리 파싱, 세션 관리 오버헤드 발생
- SQLite는 프로세스 내 메모리/파일 직접 접근, 네트워크 오버헤드 zero
- SQLAlchemy 등 ORM은 쿼리 결과 파이썬 객체 매핑(Hydration) 과정에서 대량 CPU 소모
- Raw SQL 직통 조작과 aiosqlite.Row 딕셔너리 처리가 레이턴시 단축에 절대적 유리

#### DB 연결 매번 생성/파기 금지 및 설정 메모리 상주
**타당성 (최적)**
- SQLite 커넥션 오픈은 디스크 I/O 잠금 동반, 수십 ms 소요되는 무거운 작업
- 매 요청마다 커넥션 생성은 실시간 파이프라인 파괴
- 설정값 조회를 시세 처리 루프 안에서 DB 조회는 자살 행위
- 설정은 앱 로드 시 및 설정 수정 이벤트 시에만 메모리 동기화, 틱 연산 단계에서는 O(1) 메모리 딕셔너리 조회

#### EventBus/발행구독 패턴 사용 금지 (직접 호출 체인 유지)
**타당성 (최적)**
- EventBus는 호출 흐름 불투명화, 콜백 호출 리스트 루프 오버헤드 유발
- 비동기 예외 발생 시 스택 트레이스 손실로 1인 개발 시 디버깅 극도로 어려움
- tick_queue -> Compute Engine -> 직접 호출(execute_buy/execute_sell) -> OMS Pipeline 명시적 asyncio.Queue 파이프라인 구조는 투명성 확보, 디버깅 속도 압도적 향상

#### 실시간 파이프라인과 배치 파이프라인 명확 분리
**타당성 (최적)**
- 장마감 데이터 백업/정산 작업은 대량 Row 집계 연산 및 디스크 쓰기 동반
- 두 작업이 동일 데이터 큐나 CPU 스레드 공유 시 배치 연산 중 실시간 틱 수집/매매 타점 연산 밀려 데이터 유실/지연 체결(슬리피지) 발생
- 물리적 루프와 데이터 배관 완전 분리 필요

#### 증권사 이름 공통 기능 침투 금지 (Broker Abstraction)
**타당성 (최적)**
- 증권사마다 종목 코드 체계, 호가 단위, 실시간 시세 포맷이 완전히 상이
- 핵심 매매 엔진이 특정 증권사 API 포맷 종속 시 다른 증권사 전환/다중 증권사 결합 시 전체 로직 재작성 필요
- BrokerRouter와 공통 Connector 인터페이스로 비즈니스 엔진과 통신 레이어 격리는 유지보수/확장성 측면 적합

---

## 엔터프라이즈 아키텍처와의 비교 분석

### 비교 매트릭스

| 비교 항목 | 대기업 핀테크 증권사 (토스, 카카오 등) | SectorFlow (1인 로컬 자동매매 시스템) |
|---------|-------------------------------------|-------------------------------------|
| 주요 인프라 | 클라우드 분산 환경 (AWS, 다중 IDC) | 단일 로컬 컴퓨터 (Local PC) |
| 동시성 처리 | 분산 스레드 아키텍처 / 액티브-액티브 클러스터링 | 단일 asyncio 이벤트 루프 (단일 스레드) |
| 메시징/이벤트 | Apache Kafka, RabbitMQ 등 분산 브로커 | asyncio.Queue (In-Memory Queue) |
| 캐시 시스템 | 분산 Redis 클러스터, Memcached | 로컬 메모리 캐시 (Python dict) |
| 데이터베이스 | PostgreSQL, TimescaleDB, Oracle RAC 등 고신뢰성 분산 DB | SQLite 단일화 (WAL 모드 활용) |
| 아키텍처 패턴 | MSA (마이크로서비스 아키텍처), CQRS 패턴 | 단일 모놀리식 프로세스 (Monolithic) |
| 개발/운영 비용 | 매우 높음 (대규모 인프라 엔지니어링 팀 필요) | 극도로 낮음 (추가 인프라 비용 $0, 자가 완비형) |
| 네트워크 지연 | 서버 간 네트워크 홉 발생 (ms 단위 발생) | Zero Network Hop (메모리 버스 및 IPC) |

### 기술적 논거: 왜 엔터프라이즈 아키텍처를 로컬 앱에 도입하면 안 되는가?

#### 지연 시간(Latency)의 역설
- 대형 증권사는 Kafka와 Redis 사용으로 서버 간 네트워크 호출(TCP/IP) 수반, 1~5ms 이상 대기 시간 추가
- SectorFlow는 동일 프로세스 내 asyncio.Queue와 Python 메모리 참조 사용, 틱 전달 시간 마이크로초(µs) 단위 수렴
- 로컬 내 처리 지연이 대형 서버 아키텍처보다 훨씬 낮음

#### 관리 및 복잡성 오버헤드
- 1인 개발자가 로컬에서 Kafka, Redis, PostgreSQL 서버 운영 시 개발 시간 절반 이상을 인프라 설치/유실 방지/커넥션 풀 에러 대응에 소모
- 핵심 매매 알고리즘 개발 방해

#### 리소스 격리 한계
- 개인 PC 한정 자원(RAM 16-32GB, 8-16코어 CPU)에서 무거운 백그라운드 인프라 서버 동시 구동은 자원 고갈 초래
- 매매 엔진 연산에 지연(Garbage Collection, OS 스케줄링 밀림) 발생

**결론**: SectorFlow의 "단순함, 가벼움, 로컬 완비형" 원칙은 1인 자동매매 환경에서 타협이 아니라 성능과 생존을 위한 극도의 최적 설계

---

# 제2부: 시스템 설계 (몸)

## 1. 시스템 개요

SectorFlow는 한국 주식시장(KRX/NXT)의 실시간 시세를 WebSocket으로 수신하여 업종별 강도를 분석하고, 자동 매수/매도를 실행하는 1인 로컬 자동매매 시스템이다.

**핵심 특징:**
- 단일 Python 프로세스, 단일 asyncio 이벤트 루프
- FastAPI 웹서버와 트레이딩 엔진이 동일 루프에서 실행
- 순수 asyncio.Queue 기반 인프로세스 파이프라인 (Redis 등 외부 브로커 없음)
- SQLite 단일 커넥션 + WAL 모드 (ORM 없이 직접 SQL)
- 테스트 모드(가상계좌) / 실전 모드 전환 지원
- 다중 증권사 지원 (키움, LS etc.) — Broker Router + ConnectorManager

---

## 2. 기술 스택

### 백엔드 (Python)
- **언어**: Python 3.12+
- **웹 프레임워크**: FastAPI + Uvicorn (ASGI)
- **비동기 DB**: aiosqlite (SQLite WAL mode)
- **WebSocket**: FastAPI WebSocket (Starlette)
- **HTTP 클라이언트**: httpx (async)
- **증권사 연결**: 커스텀 WebSocket Connector (키움, LS)
- **로깅**: Python logging + 커스텀 configure_app_logging
- **암호화**: cryptography (API 키 암호화 저장)

### 프론트엔드 (TypeScript)
- **언어**: TypeScript
- **빌드**: Vite
- **상태관리**: Custom Store (Event-driven)
- **실시간 통신**: Native WebSocket
- **차트**: Canvas 기반 커스텀 렌더링
- **가상 스크롤**: 커스텀 virtual-scroller 구현

### 인프라
- **DB**: SQLite (단일 파일 `backend/data/stocks.db`)
- **외부 서비스**: Telegram Bot API (알림), korean_lunar_calendar (음력→양력 변환, KRX 거래일 계산)
- **배포**: 로컬 실행 (SectorFlow.command 스크립트)

---

## 3. 프로세스 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    단일 asyncio 이벤트 루프                      │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  FastAPI     │  │  Trading     │  │  Time Scheduler      │   │
│  │  Web Server  │  │  Engine      │  │  (daily_time_sched)  │   │
│  │  (Uvicorn)   │  │  (engine_*)  │  │  asyncio.call_later  │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│  ┌──────┴───────┐  ┌──────┴──────────────────────┴───────────┐   │
│  │  WS Manager  │  │          Pipeline Loops                  │   │
│  │  (ws_manager)│  │  Compute Loop / Gateway Loop             │   │
│  └──────────────┘  └──────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  DB Writer   │  │  Trade Hist  │  │  Journal Consumer    │   │
│  │  (직렬화 큐)  │  │  Consumer    │  │  (주문 저널링)        │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 기동 순서 (lifespan)

```
1. configure_app_logging()
2. start_db_writer()           — DB 쓰기 큐 시작
3. init_cache_tables()         — CREATE TABLE IF NOT EXISTS
4. initialize_trading_calendar_cache()  — 거래일 캐시 로드
5. initialize_queues()         — 4개 코어 큐 생성
6. start_gateway_loop()        — Gateway 파이프라인 시작 (엔진과 독립)
7. load_filter_summary_meta_cache()
8. load_integrated_system_settings()  — SQLite → settings_cache (SSOT)
9. journal.start_consumer_task()
10. server_ready_event.set()   — Health endpoint 즉시 응답 가능
11. _engine_init_background()  — 백그라운드 엔진 초기화
    ├── start_engine()
    │   ├── 테스트모드: dry_run._refresh_positions_if_dirty()  — trades 기반 포지션 구축
    │   └── run_engine_loop()
    │       ├── _cache_and_bootstrap()    — 캐시 선행 로드
    │       ├── _get_all_tokens_async()   — 다중 증권사 토큰 병렬 발급
    │       ├── _load_broker_spec_async() — TR 스펙 로드
    │       ├── settlement_engine.load_state()  — 가상잔고 로드
    │       ├── start_compute_loop()      — Compute 파이프라인 시작
    │       └── WS 구간 감지 루프         — ConnectorManager 연결/해제
    ├── engine_ready_event.set()
    └── start_daily_time_scheduler()  — 타이머 스케줄링
```

### 종료 순서 (shutdown)

```
1. ws_manager.close_all()           — WS 클라이언트 정상 종료
2. journal.stop_consumer_task()
3. telegram_bot.stop_async()
4. stop_engine()                    — 엔진 루프 + 백그라운드 태스크 취소
5. stop_daily_time_scheduler()
6. stop_db_writer()
7. close_db_connection()
```

---

## 4. 파이프라인 아키텍처

### 4.1 코어 큐 (4개)

```
                    ┌────────────────────────────────────────────────┐
                    │              Broker WebSocket                   │
                    │    (키움/LS 실시간 시세 수신)                     │
                    └────────────────┬───────────────────────────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │   engine_ws_dispatch.py         │
                    │   (시세 파싱 + 라우팅)            │
                    └──┬──────────┬────────────────────┘
                       │          │
                       ▼          ▼
              ┌────────────┐ ┌──────────────────┐
              │ tick_queue │ │ broadcast_queue  │
              │ (20000)    │ │ (2000)           │
              │ 드롭 정책   │ │ 상태/이벤트 큐    │
              └─────┬──────┘ └────────┬─────────┘
                    │                 │
                    ▼                 ▼
              ┌─────────────────┐   ┌────────────────────┐
              │ Compute Loop    │   │ Gateway Loop       │
              │ (pipeline_      │   │ (pipeline_gateway) │
              │  compute.py)    │   │ broadcast 루프     │
              │                 │   └────────┬───────────┘
              │ tick + control  │            │
              │ 동시 대기        │            ▼
              └────┬────────────┘   ┌────────────────────┐
                   │                │  WS Manager        │
                   ▼                │  (프론트엔드 전송)   │
              ┌────────────┐       └────────────────────┘
              │control_queue│
              │ (500)       │
              │ PriorityQueue│
              └─────────────┘
```

| 큐 | 크기 | 타입 | 정책 |
|----|------|------|------|
| `tick_queue` | 20000 | asyncio.Queue | 드롭 정책 (가득 시 가장 오래된 데이터 버림) |
| `broadcast_queue` | 2000 | asyncio.Queue | 상태형/이벤트형 구분 |
| `control_queue` | 500 | asyncio.PriorityQueue | 최우선순위 (설정 변경 등) |

### 4.2 Compute Loop (`pipeline_compute.py`)

```python
# 핵심 구조: tick_queue + control_queue 동시 대기
while _compute_running:
    tick_task = asyncio.ensure_future(tick_queue.get())
    control_task = asyncio.ensure_future(control_queue.get())
    done, pending = await asyncio.wait({tick_task, control_task}, FIRST_COMPLETED)
    
    # control 신호 처리 (UPDATE_CONFIG, RECOMPUTE_SECTOR, DYNAMIC_REG/UNREG)
    # tick 데이터 처리 → _process_tick_data()
    await asyncio.sleep(0)  # 협력적 양보 (이벤트 루프 고갈 방지)
```

**별도 루프:** `_sector_recompute_loop` — 10초 주기 디바운스 타이머 기반 업종 재계산

### 4.3 Gateway Loop (`pipeline_gateway.py`)

단일 소비 루프 실행:
- `_broadcast_loop`: `broadcast_queue` 소비 → WebSocket 전송

---

## 5. 데이터 흐름

### 5.1 실시간 시세 흐름

**WS 구독 대상 (1차 필터 게이트):**
- 1차 필터(5일평균거래대금 `sector_min_trade_amt`억원 이상) 통과 종목 + 보유종목만 WS 구독
- `subscribe_sector_stocks_0b()`가 `_filtered` 플래그 기반으로 구독 대상 선정 (200개 한도, 보유종목 우선)
- 필터 미통과 종목: WS 구독 안됨 → 01 틱 수신 없음 → 업종 순위 계산 대상 아님 → 아무 처리도 하지 않음

```
[WS 구독] 1차 필터 통과 종목 + 보유종목만 구독 (subscribe_sector_stocks_0b)
    │
    ▼
증권사 WS ──► connector ──► tick_queue
                                │
                                ▼
                            Compute Loop (_handle_real_01_tick)
                                ├── 1. broadcast_queue.put_nowait(real-data)  — 화면 전송 (최우선)
                                │      └──► pipeline_gateway ──► WS Manager ──► 프론트엔드
                                ├── 2. master_stocks_cache 갱신 (cur_price, change_rate, strength, trade_amount)
                                ├── 3. request_sector_recompute(nk_px)  — dirty 마킹 (O(1), 별도 배치 루프에서 계산)
                                ├── 4. 보유종목 현재가 반영 (state.positions) + 자동매도 조건 체크
                                └── 5. _check_realtime_latency()  — 200ms 초과 시 자동매매 중단
```

**전송 경로 일관성 (P23):**
- 01/0B 틱 (현재가/등락률/체결강도/거래대금): `broadcast_queue` 경로 (전 종목 동일)
- 0D 틱 (호가잔량비): `ws_manager.broadcast` 직접 경로 (매수 후보만, `_subscribed_dynamic` 플래그)
- PGM 틱 (프로그램 순매수): `ws_manager.broadcast` 직접 경로 (매수 후보만, `_subscribed_dynamic` 플래그)

### 5.2 업종 점수 계산 흐름

**별도 백그라운드 루프 — 실시간 시세 전송과 분리:**
- Compute Loop 내 `_handle_real_01_tick`에서 `request_sector_recompute(code)`로 dirty 마킹만 수행 (O(1) set add)
- 실제 업종 점수 계산은 별도 백그라운드 루프 `_sector_recompute_loop_impl()`에서 수행
- Phase 1 (1회): 실시간데이터 수신율 임계값(`sector_start_threshold_pct`) 대기 → 통과 후 Phase 2 전환
- Phase 2: 0.2초 배치 루프 — dirty 종목의 업종만 증분 재계산

```
tick 이벤트 (01/0B 틱)
    │
    ▼
request_sector_recompute(code)  — dirty 코드 등록 (O(1) set add, 계산 아님)
    │
    ▼ (별도 백그라운드 루프, 0.2초 배치)
_flush_sector_recompute_impl()
    │
    ├── 캐시 없음 → _full_recompute()     — 전체 재계산 (콜드 스타트)
    └── 일반 캐시 → 증분 재계산             — dirty 섹터만 교체
         │
         ▼
    compute_sector_scores()
         │
         ▼
    calculate_bonus_scores()  — 3단계 누적 가산점 (순위별 차등, 0~만점 합) + 컷오프 내부 적용
         │  (옵션 C 2패스: 1차/3차 계산 → 컷오프 → 2차 모집단 구성 → 종합)
         ▼
    build_buy_targets_from_settings()  — 매수 타겟 큐 생성
         │
         ▼
    _sector_summary_cache 갱신 (참조 교체)
         │
         ├──► notify_desktop_sector_scores()  — delta 전송
         ├──► notify_buy_targets_update()
         └──► evaluate_buy_candidates()  — 매수 시도
```

### 5.3 매수 주문 흐름

```
evaluate_buy_candidates()
    │
    ├── auto_buy_effective() 게이트 (마스터스위치 + 시간범위 + auto_buy_on)
    ├── 최대 보유 종목 수 체크
    ├── 일일 매수 한도 체크
    │
    ▼ (종목별 루프)
execute_buy()
    │
    ├── 실시간 지연 게이트 (200ms 초과 시 차단)
    ├── 자동매매 게이트 (force_buy 시 우회)
    ├── 재매수 차단 (rebuy_block_on=True 시 오늘 매수 종목 차단)
    ├── 쓰로틀 (30초 내 재신호 차단)
    ├── 최대 보유 종목 수 체크
    ├── RiskManager 게이트
    │   ├── 테스트모드: CircuitBreaker만 체크
    │   └── 실전: CircuitBreaker + 일일손실한도 + 예수금
    │
    ├── 테스트모드: settlement_engine.check_test_buy_power()
    │
    ▼ (주문 전송)
    테스트모드: dry_run.fake_send_order()
    실전: router.order.send_order()
         │
         ├── 성공 → RiskManager.record_success() → 체결이력 기록
         └── 실패 → RiskManager.record_failure() → CircuitBreaker OPEN 시 마스터 OFF
```

### 5.4 매도 주문 흐름

```
check_sell_conditions()  — 스냅샷 루프에서 주기적 호출
    │
    ├── 실시간 지연 게이트
    ├── RiskManager CircuitBreaker 체크
    │
    ▼ (종목별)
    ├── 손절: pnl_rate <= -loss_val
    ├── 익절: pnl_rate >= tp_val
    └── T/S: 최고점 대비 하락률 >= ts_drop_val
         │
         ▼
    execute_sell()
         │
         ├── 테스트모드: dry_run.fake_send_order()
         ├── 실전: router.order.send_order()
         │
         ├── 성공 → 체결이력 기록 → RiskManager.record_success()
         └── 실패 → RiskManager.record_failure()
```

---

## 6. 업종 점수 계산 엔진

### 6.1 데이터 모델

```
StockScore (종목 단위)
├── code, name, sector
├── change_rate, change, cur_price
├── trade_amount, avg_amt_5d, ratio_5d_pct
├── strength (체결강도)
├── market_type, nxt_enable
├── guard_pass, guard_reason
└── boost_score (가산점)

SectorScore (업종 단위)
├── sector, total, rise_count, rise_ratio
├── avg_change_rate, avg_trade_amount, avg_ratio_5d_pct
├── final_score (종합 가산점 = 1차+2차+3차, 0~만점 합, 정수)
├── bonus_rise_ratio (1차 가산점: 상승 종목 비율 순위, tiered 점수 0~만점)
├── bonus_relative_strength (2차 가산점: 통과 업종 종목 백분위 평균 순위, tiered 점수 0~만점)
├── bonus_trade_amount (3차 가산점: 거래대금 순위, tiered 점수 0~만점)
├── rank (1=최강, 0=순위 없음/컷오프 미달)
└── stocks: list[StockScore]

SectorSummary (전체 결과)
├── sectors: list[SectorScore]  — 강도 순위 정렬
├── buy_targets: list[BuyTarget]
├── blocked_targets: list[BuyTarget]
└── version
```

### 6.2 3단계 누적 가산점 시스템

**설계 원칙**: 기존 가중치 슬라이더(주관 개입)와 트리밍(인위적 잘라내기)을 제거하고,
순위/백분위 기반의 3단계 누적 가산점으로 업종 강도 평가. 매수 설정 `boost_score` 누적
합산 패턴과 동일 구조 (P23 일관성).

**3개 단계 (각 0~사용자 설정 만점, 종합 0~만점 합):**

| 단계 | 의미 | 데이터 | 점수 변환 | 함수 |
|------|------|--------|-----------|------|
| 1차 | 상승 폭 (참여 폭) | `rise_ratio` (상승 종목 비율) | 업종 간 순위 → tiered 점수 (0~만점) | `rank_to_tiered_score` |
| 2차 | 상승 강도 (상승 폭) | 통과 업종 종목 `change_rate` | 종목 백분위 → 업종별 평균 → 업종 간 순위 → tiered 점수 (0~만점) | `percentile_to_score` + `rank_to_tiered_score` |
| 3차 | 거래대금 (유동성) | `avg_trade_amount` (평균 거래대금) | 업종 간 순위 → tiered 점수 (0~만점) | `rank_to_tiered_score` |

**사용자 설정 만점 (기본값):**
- `sector_bonus_rise_ratio_max` = 10 (1차 만점)
- `sector_bonus_relative_strength_max` = 7 (2차 만점)
- `sector_bonus_trade_amount_max` = 5 (3차 만점)

**점수 변환 함수:**
- `rank_to_tiered_score`: 순위별 차등 점수 = max(0, max_score - rank + 1) — 1위=만점, 2위=만점-1, ..., 만점 순위=1, 그 아래=0. 업종 간 순위 비교용 (1차/3차, 2차 최종 변환).
- `percentile_to_score`: 백분위 점수 = (N - rank) / (N - 1) × 100 — 최대값=100점, 최소값=0점 (완전 0~100 스케일). 종목 간 상대 비교용 (2차 중간 단계). N=1이면 100점.
- 동점 처리: 같은 값 = 같은 점수, 다음 순위 건너뜀 (표준 순위 방식).

**계산 과정 (옵션 C — 2패스, `calculate_bonus_scores`):**
1. **1패스**: 1차(상승비율 순위 → tiered) + 3차(거래대금 순위 → tiered) 계산 → 임시 합산 기반 정렬
2. **컷오프**: `min_rise_ratio` 미만 업종 `rank=0` (매수 대상 제외) — `calculate_bonus_scores` 내부에서 수행 (진실 소스 1곳, P10/P22)
3. **2패스**: 통과 업종(rank>0) 종목들만 모집단 → `percentile_to_score` 백분위 → 업종별 평균 → 업종 간 순위 → `rank_to_tiered_score` tiered 점수 = 2차 가산점
4. **종합**: `final_score = 1차 + 2차 + 3차` (0~만점 합, 정수)
5. **재정렬**: `final_score` 내림차순 → `bonus_relative_strength` 내림차순 → `bonus_rise_ratio` 내림차순 → 업종명 오름차순 (결정적 정렬)
6. **rank 부여**: 1-based, 컷오프 미달 업종은 `rank=0` 유지

> **2차 가산점 모집단 (P22 데이터 정합성)**: 컷오프 적용 후 통과 업종이 확정된 상태에서
> 모집단 구성. 옵션 C 2패스 채택으로 진실 소스 1곳 유지. 미통과 업종은 2차 가산점=0점.
> 통과 업종 0개 시 모든 업종 2차 가산점=0점 (1차/3차만으로 순위 결정).

### 6.3 필터링

- **1차 필터**: 5일평균거래대금 (`min_avg_amt_eok`) — 업종 그룹핑 전 적용
  - `get_sector_stocks()`에서 필터 통과 종목만 `all_codes`에 포함 → 업종 순위 계산 대상
  - 필터 통과 종목에 `_filtered` 플래그 설정 → `subscribe_sector_stocks_0b()`에서 WS 구독 대상 선정 (보유종목 포함, 200개 한도)
  - **필터 미통과 종목**: WS 구독 안됨 → 실시간 시세 수신 없음 → 업종 순위 계산 대상 아님 → 아무 처리도 하지 않음
- **업종 컷오프**: `min_rise_ratio` 미만 업종은 `rank=0` (매수 대상 제외)
- **개별 종목 가드**: 상승률 과열(`block_rise_pct`), 하락률 과열(`block_fall_pct`), 체결강도 최소값

### 6.4 증분 연산 모드

| 모드 | 조건 | 동작 |
|------|------|------|
| 전체 재계산 | 캐시 없음 (콜드 스타트) | `compute_full_sector_summary()` |
| 증분 재계산 | 캐시 있음, dirty 섹터만 | dirty 섹터만 재계산 → 병합 → 전체 순위 점수 재계산 |

### 6.5 가산점 (Boost Score)

| 가산점 | 조건 | 설정 키 |
|--------|------|---------|
| 고가 돌파 | 5일 고가 돌파 시 | `boost_high_breakout_on/score` |
| 호가 잔량비 | 매수호가/매도호가 비율 | `boost_order_ratio_on/pct/score` |
| 프로그램 매수 | 프로그램 순매수 | `boost_program_net_buy_on/score` |

---

## 7. 주문 실행 계층

### 7.1 주문 경로 이원화

```
                    ┌─────────────────────┐
                    │  AutoTradeManager   │
                    │  (trading.py)       │
                    └──────┬──────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
     테스트모드                      실전모드
              │                         │
     dry_run.fake_send_order()    router.order.send_order()
     (가상 체결, 지연 시뮬레이션)    (증권사 REST API 주문)
              │                         │
     settlement_engine              증권사 서버
     .on_buy_fill() / .on_sell_fill()
     (가상 잔고 갱신)
```

### 7.2 RiskManager (주문 전 관문)

```
RiskManager
├── CircuitBreaker
│   ├── CLOSED → OPEN: 주문 실패 5회 연속
│   ├── OPEN → HALF_OPEN: 60초 경과
│   ├── HALF_OPEN → CLOSED: 테스트 주문 성공
│   └── HALF_OPEN → OPEN: 테스트 주문 실패
├── 일일 손실 한도 (-500,000원)
├── 예수금 잔액 검사
└── 단일 종목 비중 한도 (TODO)
```

**CircuitBreaker OPEN 시:** 마스터 스위치 강제 OFF + 프론트엔드 브로드캐스트

### 7.3 자동매매 게이트

```
auto_buy_effective():
  ├── _master_on(): time_scheduler_on + 공휴일 가드
  ├── auto_buy_on == True
  └── _in_time_range(buy_time_start, buy_time_end)

auto_sell_effective():
  ├── _master_on(): time_scheduler_on + 공휴일 가드
  ├── auto_sell_on == True
  └── _in_time_range(sell_time_start, sell_time_end)
```

### 7.4 매수 주문 간격 및 쓰로틀

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `buy_interval_on` | False | 매수 주문 간격 활성화 (토글) |
| `buy_interval_min` | 0분 | 1순위 종목 매수 후 대기 간격 (분 단위) |
| `MIN_INTERVAL` | 30초 | 동일 종목 연속 신호 차단 |
| `_bought_today` | set | 오늘 매수한 종목 재매수 차단 |
| `max_stock_cnt` | 설정값 | 최대 보유 종목 수 |
| `max_daily_total_buy_amt` | 설정값 | 일일 최대 매수 금액 |

---

## 8. 정산 엔진 (Settlement Engine)

테스트 모드의 가상 예수금/투자금 관리.

### 8.1 상태

```
_accumulated_investment  — 누적 투자금 (가상 예수금)
_orderable               — 주문 가능 금액
_initial_deposit         — 초기 입금액 (기본 10,000,000원)
```

### 8.2 주요 함수

| 함수 | 설명 |
|------|------|
| `init(deposit)` | 초기 입금, `_accumulated_investment = _orderable = deposit` |
| `on_buy_fill(price, qty, fee)` | 매수 체결: `_orderable -= (price*qty + fee)` |
| `on_sell_fill(price, qty, fee, tax)` | 매도 체결: `_orderable += (price*qty - fee - tax)` |
| `charge(amount)` | 입금: `_accumulated_investment += amount, _orderable += amount` |
| `get_available_cash()` | 주문 가능 금액 조회 |
| `reset(deposit)` | 전체 리셋 (사용자 수동) |
| `save_state()` / `load_state()` | SQLite 영속화 / 로드 |

### 8.3 영속화

- `settlement_state` 테이블 (id=1 단일 행)
- `db_writer` 큐 경유 비동기 저장
- 하위 호환: `deposit` / `available_cash` 구버전 키 처리

---

## 9. Dry Run (테스트 모드 가상 주문)

```
dry_run.fake_send_order()
├── 매수: 가상 포지션 생성 (qty, avg_price)
│   ├── settlement_engine.on_buy_fill()
│   └── test_positions 테이블 저장
├── 매도: 가상 포지션 감소/제거
│   ├── settlement_engine.on_sell_fill()
│   └── test_positions 테이블 갱신
└── 0B 틱: cur_price 갱신 → 평가손익 재계산
```

- 가상 포지션은 메모리 + SQLite `test_positions` 테이블에 영속화
- 체결 지연 시뮬레이션 (실제 체결 타이밍 모방)
- 수수료/세금 계산 포함

---

## 10. 데이터베이스 계층

### 10.1 연결 관리

```python
# database.py
_db_connection: aiosqlite.Connection  — 단일 커넥션
_db_lock: asyncio.Lock                — 쓰기 직렬화

# Pragmas
PRAGMA journal_mode = WAL
PRAGMA synchronous = NORMAL
PRAGMA cache_size = -64000  (64MB)
PRAGMA temp_store = MEMORY
PRAGMA mmap_size = 268435456  (256MB)
```

### 10.2 DB Writer (쓰기 직렬화 큐)

```
비즈니스 로직 ──► execute_db_write(DBWriteOperation) ──► _db_write_queue (100)
                                                              │
                                                              ▼
                                                        _db_writer_loop()
                                                              │
                                                        _process_operation()
                                                              │
                                                        async with get_db_lock()
                                                              │
                                                        conn.execute() + commit()
```

### 10.3 테이블 스키마

| 테이블 | 용도 |
|--------|------|
| `master_stocks_table` | 전체 종목 마스터 (코드, 이름, 업종, 시장, NXT) |
| `stock_5d_array` | 5일봉 데이터 (거래대금, 고가 등) |
| `settlement_state` | 정산 엔진 상태 (단일 행) |
| `test_positions` | 테스트 모드 가상 포지션 |
| `trades` | 체결 이력 (매수/매도) |
| `trading_days_cache` | 거래일 캐시 (연 1회 갱신) |
| `sectors` | 업종 정의 (커스텀 업종명) |
| `integrated_system_settings` | 통합 설정 (단일 행 SSOT) |
| `broker_specs` | 증권사 TR 스펙 (role_mappings) |
| `journal` | 주문 저널 (요청/체결/취소 추적) |

---

## 11. WebSocket 통신 계층

### 11.1 WSManager (프론트엔드 ↔ 백엔드)

```
WSManager (싱글톤)
├── _clients: set[WebSocket]           — 연결된 클라이언트
├── _client_active_page: dict          — per-client 활성 페이지
├── _client_subscribed_fids: dict      — per-client 구독 FID
├── _state_queue: dict                 — 상태형 (최신값만 유지)
├── _event_queue: list                 — 이벤트형 (순서 보장)
└── _flush_task                         — 0.1초 주기 배치 전송
```

**전송 방식:**
| 타입 | 방식 | 특징 |
|------|------|------|
| `real-data` | 즉시 전송 | FID 필터 + zlib 압축, per-client 페이지 필터링 |
| 상태형 이벤트 | 최신값 유지 | `(event_type, code)` 키로 최신값 덮어쓰기 |
| 이벤트형 | 순서 보장 | `_event_queue`에 순차 누적 |
| 페이지별 | 타겟 전송 | 활성 페이지 클라이언트에게만 전송 |

**Graceful Shutdown:** 전체 WS 끊김 후 1초 대기 → 재연결 없으면 SIGTERM

### 11.2 주요 이벤트

| 이벤트 | 타입 | 설명 |
|--------|------|------|
| `real-data` | 즉시 | 실시간 시세 (FID 압축) |
| `sector-scores` | 상태형 | 업종 점수 (delta 전송) |
| `buy-targets-update` | 이벤트형 | 매수 타겟 변경 |
| `account-update` | 상태형 | 계좌 정보 |
| `engine-status` | 상태형 | 엔진 상태 |
| `market-phase` | 이벤트형 | 장 단계 (개장/장중/장마감 etc.) |
| `circuit_breaker_open` | 이벤트형 | 서킷 브레이커 알림 |
| `engine-ready` | 이벤트형 | 엔진 준비 완료 |
| `buy-history-append` | 이벤트형 | 매수 체결 단건 |
| `sell-history-append` | 이벤트형 | 매도 체결 단건 + 일자 요약 |

---

## 12. 시간 스케줄러 (`daily_time_scheduler.py`)

### 12.1 타이머 기반 트리거

```
asyncio.call_later() 기반 — 매일 재스케줄링

08:00  _on_ws_subscribe_start()     — WS 구독 시작 + GC 비활성화 (NXT 프리마켓 진입 시 자동 트리거)
09:00  KRX 개장 감지
20:00  _on_ws_subscribe_end()       — WS 구독 종료 + GC 정상화 (NXT 장마감 진입 시 자동 트리거)
15:30  KRX after hours / NXT aftermarket 시작
16:01  KRX unsubscribe              — KRX 종목 구독 해제
18:00  NXT aftermarket 종료
20:40  _fire_unified_confirmed_fetch() — 확정 시세 + 5일봉 다운로드
00:00  _on_midnight()               — 일일 리셋 (거래일 판단, 타이머 재예약)
```

### 12.2 자동매매 타이머

```
buy_time_start  — auto_buy_effective() 활성화
buy_time_end    — auto_buy_effective() 비활성화
sell_time_start — auto_sell_effective() 활성화
sell_time_end   — auto_sell_effective() 비활성화
```

### 12.3 WS 구독 구간 판정

```python
is_ws_subscribe_window(settings):
  1. ws_subscribe_on 마스터 스위치 체크
  2. state.market_phase["nxt"]가 NXT_ACTIVE_PHASES에 포함 여부
     (주말/공휴일은 calc_timebased_market_phase()가 nxt="휴장일"로 자동 차단)
```

### 12.4 엔진 루프의 WS 구간 감지

`engine_loop.py`의 메인 루프는 `ws_window_changed_event`를 대기하며:
- 구간 진입: `ConnectorManager` 생성 + WS 연결 + 종목 구독
- 구간 종료: WS 연결 해제 + ConnectorManager 정리

---

## 13. 상태 관리 (SSOT)

### 13.1 EngineState (메모리 상주)

```python
# engine_state.py — 싱글톤
class EngineState:
    # 엔진 상태
    running, login_ok, access_token
    connector_manager, active_connector
    broker_tokens: dict[str, str]
    
    # 데이터 캐시
    master_stocks_cache: dict[str, dict]     — 전체 종목 정보 (단일 소스)
    integrated_system_settings_cache: dict   — 통합 설정 (SSOT)
    positions: list                          — 보유 종목
    sector_score_index: dict                 — 업종별 점수 인덱스
    
    # 이벤트/락
    engine_stop_event, ws_window_changed_event
    data_ready_event, token_ready_event
    bootstrap_event, sector_summary_ready_event
    engine_ready_event, server_ready_event
    
    # 스케줄러 상태
    ws_subscribe_window_active: bool | None
    ws_subscribe_timer_handles: list
    auto_trade_timer_handles: list
    midnight_timer_handle
    
    # 실시간 상태
    realtime_latency_exceeded: bool          — 200ms 초과 시 자동매매 중단
    market_phase: dict                       — KRX/NXT 장 단계
```

### 13.2 설정 계층

```
SQLite (integrated_system_settings 테이블)
    │
    ▼ load_integrated_system_settings()
state.integrated_system_settings_cache (메모리 SSOT)
    │
    ├── 모든 모듈이 이 캐시를 직접 참조
    ├── 설정 변경 시: settings.py → DB 저장 → 캐시 갱신 → apply_settings_change()
    └── apply_settings_change() → 타이머 재예약 / 섹터 재계산 / WS 구간 재판정
```

---

## 14. 증권사 연결 계층

### 14.1 Broker Router 패턴

```
broker_factory.py
    │
    ├── get_router() → BrokerRouter (싱글톤)
    │   ├── .auth → AuthProvider (토큰 발급)
    │   ├── .order → OrderProvider (주문 전송)
    │   ├── .stock → StockProvider (종목/시세 조회)
    │   └── .real → RealDataProvider (실시간 데이터)
    │
    └── broker_registry.py
        ├── _create_provider(type, broker_id, settings, auth_cache)
        └── BROKER_DISPLAY_NAMES
```

### 14.2 ConnectorManager (다중 증권사 WS)

```
ConnectorManager
├── _connectors: dict[str, BrokerConnector]
│   ├── kiwoom_connector.py  — 키움증권 WS
│   └── ls_connector.py      — LS증권 WS
├── connect_all()             — 모든 증권사 WS 연결
├── disconnect_all()          — 모든 WS 해제
├── is_connected()            — 연결 상태 확인
├── set_message_callback()    — 시세 수신 콜백
└── get_connector(broker_id)  — 특정 증권사 커넥터
```

### 14.3 지원 증권사

| 증권사 | WS 시세 | REST 주문 | REST 계좌 | TR 스펙 |
|--------|---------|-----------|-----------|---------|
| 키움증권 | kiwoom_connector | kiwoom_order | kiwoom_rest | broker_specs DB |
| LS증권 | ls_connector | ls_rest | ls_rest | broker_specs DB |

---

## 15. 안전장치 요약

| 계층 | 장치 | 임계치 | 동작 |
|------|------|--------|------|
| 실시간 지연 | `_check_realtime_latency()` | 200ms | 자동매매 중단 플래그 |
| 실시간 지연 | 경고 | 50ms | 로그 경고 |
| 주문 실패 | CircuitBreaker | 5회 연속 | OPEN → 주문 거부 |
| 주문 복구 | CircuitBreaker | 60초 | HALF_OPEN → 테스트 주문 |
| 일일 손실 | RiskManager | -500,000원 | 매수 차단 |
| 예수금 | RiskManager | 주문액 > 잔액 | 매수 차단 |
| 틱 폭주 | tick_queue 드롭 | 5000개 | 가장 오래된 데이터 버림 |
| 이벤트 루프 | `asyncio.sleep(0)` | 매 틱 | 협력적 양보 |
| GC 지연 | `gc.disable()` | WS 구간 중 | HFT 지연 방지 |
| WS 끊김 | shutdown timer | 1초 | 재연결 없으면 SIGTERM |

---

## 16. 장마감 파이프라인

```
20:00 _on_ws_subscribe_end() (NXT 장마감 진입 시 자동 트리거)
  ├── GC 정상화 (gc.enable() + gc.collect())
  ├── 실시간 구독 전체 해제 (_trigger_unreg_all)
  ├── time_scheduler_on = False, ws_subscribe_on = False
  └── WS 연결 해제 (engine_loop에서)

20:40 _fire_unified_confirmed_fetch()
  ├── 확정 시세 다운로드 (당일 종가)
  │   ├── 전체 종목 확정 가격/거래대금 DB 저장
  │   └── master_stocks_cache 확정 데이터 갱신
  ├── 5일봉 다운로드
  │   ├── 최근 5거래일 일봉 데이터
  │   ├── 5일평균거래대금 계산
  │   ├── high_price (5일 고가) 갱신
  │   └── stock_5d_array 테이블 저장
  └── 업종 요약 전체 재계산 (확정 데이터 기반)

00:00 _on_midnight()
  ├── 일일 리셋 (last_reset_date 갱신)
  ├── 거래일 판단 → 타이머 재예약
  └── 체결 이력 만료 레코드 정리
```

---

## 17. 프론트엔드 아키텍처

### 17.1 페이지 구조

| 페이지 | 파일 | 설명 |
|--------|------|------|
| 업종순위 | `sector-ranking.ts` | 업종별 점수/순위 테이블 |
| 업종별종목 | `sector-stock.ts` | 선택 업종 내 종목 시세 |
| 매수후보 | `buy-target.ts` | 매수 타겟 + 차단 종목 |
| 보유종목 | `sell-position.ts` | 보유 종목 + 손익 |
| 수익현황 | `profit-overview.ts` | 일별 수익 그래프 + 요약 |
| 매수설정 | `buy-settings.ts` | 매수 관련 설정 |
| 매도설정 | `sell-settings.ts` | 매도 관련 설정 |
| 일반설정 | `general-settings.ts` | 증권사/계좌/시간 설정 |
| 종목분류 | `stock-classification.ts` | 업종 매핑 관리 |

### 17.2 상태 관리

```
stores/
├── store.ts               — 글로벌 스토어 (계좌, 엔진상태)
├── hotStore.ts            — 실시간 시세 핫 스토어 (빈번한 갱신)
├── uiStore.ts             — UI 상태 (페이지, 모달, 로딩)
├── stockClassificationStore.ts — 종목 분류 상태
└── index.ts               — 스토어 집합
```

### 17.3 통신 계층

```
api/           — REST API 클라이언트
binding.ts     — WebSocket 이벤트 바인딩 (이벤트 → 스토어 갱신)
main.ts        — 앱 진입점, WS 연결 관리
router.ts      — 해시 기반 라우터
settings.ts    — 프론트엔드 설정
```

### 17.4 컴포넌트

```
components/
├── canvas-profit-chart.ts  — Canvas 기반 수익 차트
├── virtual-scroller.ts     — 대량 데이터 가상 스크롤
└── common/ (19개)          — 공통 UI 컴포넌트
```

---

## 18. 디렉토리 구조

```
SectorFlow/
├── main.py                          — 앱 진입점 (Uvicorn 실행)
├── ARCHITECTURE.md                  — 본 문서
├── SectorFlow.command               — macOS 실행 스크립트
│
├── backend/
│   ├── init_db.py                   — DB 스키마 초기화 스크립트
│   ├── requirements.txt             — Python 의존성
│   ├── data/
│   │   ├── stocks.db                — SQLite DB 파일
│   │   └── broker_specs/            — 증권사 TR 스펙 JSON
│   ├── protobuf/                    — Protobuf 이벤트 정의
│   └── app/
│       ├── config.py                — 앱 설정
│       ├── core/                    — 핵심 모듈
│       │   ├── broker_*.py          — 증권사 추상화 (Router, Factory, Registry)
│       │   ├── kiwoom_*.py          — 키움증권 구현 (Connector, REST, Order)
│       │   ├── ls_*.py              — LS증권 구현 (Connector, REST)
│       │   ├── connector_manager.py — 다중 증권사 WS 관리
│       │   ├── settings_*.py        — 설정 관리 (파일, 스토어, 기본값)
│       │   ├── sector_mapping.py    — 종목 → 업종 매핑
│       │   ├── trading_calendar.py  — 거래일 캘린더
│       │   ├── stock_filter.py      — 종목 필터링
│       │   ├── journal.py           — 주문 저널링
│       │   └── encryption.py        — API 키 암호화
│       ├── domain/                  — 도메인 로직 (순수 계산)
│       │   ├── models.py            — 데이터 모델 (StockScore, SectorScore etc.)
│       │   ├── sector_calculator.py — 업종 점수 계산
│       │   ├── sector_score.py      — 순위 기반 점수 + 가중치 계산
│       │   ├── sector_filter.py     — 업종 필터링/그룹핑
│       │   ├── buy_filter.py        — 매수 타겟 생성 + 가드
│       │   └── stock_filter.py      — 종목 필터 로직
│       ├── services/                — 비즈니스 서비스 계층
│       │   ├── engine_state.py      — 전역 상태 (싱글톤)
│       │   ├── engine_loop.py       — 엔진 메인 루프
│       │   ├── engine_lifecycle.py  — 엔진 시작/중지/정산
│       │   ├── engine_service.py    — 엔진 서비스 (설정 적용, 스냅샷)
│       │   ├── engine_bootstrap.py  — 부트스트랩 (초기 데이터 로드)
│       │   ├── engine_cache.py      — 캐시 선행 로드
│       │   ├── engine_ws.py         — WS 구독 관리
│       │   ├── engine_ws_dispatch.py— WS 시세 파싱/라우팅
│       │   ├── engine_ws_reg.py     — WS 종목 구독 등록/해제
│       │   ├── engine_ws_parsing.py — WS 데이터 파싱
│       │   ├── engine_sector_confirm.py — 업종 재계산 (증분)
│       │   ├── engine_snapshot.py   — 스냅샷 생성
│       │   ├── engine_account*.py   — 계좌 관리/조회/알림
│       │   ├── engine_radar*.py     — 레이더 종목 관리
│       │   ├── engine_strategy_core.py — 매수 전략 코어
│       │   ├── trading.py           — AutoTradeManager (매수/매도 실행)
│       │   ├── buy_order_executor.py— 매수 후보 평가/실행
│       │   ├── dry_run.py           — 테스트 모드 가상 주문
│       │   ├── settlement_engine.py — 정산 엔진 (가상 잔고)
│       │   ├── trade_history.py     — 체결 이력 (메모리 + DB)
│       │   ├── risk_manager.py      — 리스크 관리자
│       │   ├── circuit_breaker.py   — 서킷 브레이커
│       │   ├── account_manager.py   — 계좌 관리자
│       │   ├── daily_time_scheduler.py — 시간 스케줄러
│       │   ├── market_close_pipeline.py — 장마감 파이프라인
│       │   ├── sector_data_provider.py — 업종 데이터 제공자
│       │   ├── core_queues.py       — 전역 큐 정의 (core_queues.py)
│       │   ├── core_queues.py       — 전역 큐 (4개)
│       │   ├── auto_trading_effective.py — 자동매매 유효성 판정
│       │   ├── ws_subscribe_control.py — WS 구독 제어
│       │   ├── telegram_bot.py      — 텔레그램 봇
│       │   ├── data_manager.py      — 데이터 매니저 (종목명 etc.)
│       │   ├── state_manager.py     — 상태 관리자
│       │   └── notification_worker.py — 알림 워커
│       ├── pipelines/               — 파이프라인 루프
│       │   ├── pipeline_compute.py  — Compute 루프 (tick + control)
│       │   └── pipeline_gateway.py  — Gateway 루프 (broadcast + price)
│       ├── db/                      — 데이터베이스 계층
│       │   ├── database.py          — 연결 관리 (단일 커넥션)
│       │   ├── db_writer.py         — 쓰기 직렬화 큐
│       │   └── stock_tables.py      — 테이블 정의 + 마이그레이션
│       └── web/                     — 웹 서버 계층
│           ├── app.py               — FastAPI 앱 (lifespan)
│           ├── ws_manager.py        — WebSocket 관리자
│           ├── auth.py              — 인증
│           ├── deps.py              — 의존성 주입
│           ├── middleware.py        — 미들웨어
│           └── routes/              — REST API + WS 라우트
│               ├── ws.py            — WebSocket 엔드포인트
│               ├── ws_orders.py     — 주문 WS
│               ├── ws_settings.py   — 설정 WS
│               ├── ws_subscribe.py  — 구독 제어 WS
│               ├── settings.py      — 설정 REST API
│               ├── status.py        — 상태 REST API
│               ├── account.py       — 계좌 REST API
│               ├── trade.py         — 주문 REST API
│               ├── settlement.py    — 정산 REST API
│               ├── market.py        — 시장 정보 REST API
│               ├── stock_classification.py — 종목 분류 REST API
│               └── auth.py          — 인증 REST API
│
└── frontend/
    ├── index.html
    ├── package.json
    ├── tsconfig.json
    └── src/
        ├── main.ts                  — 앱 진입점
        ├── router.ts                — 해시 라우터
        ├── binding.ts               — WS 이벤트 바인딩
        ├── settings.ts              — 프론트엔드 설정
        ├── api/                     — REST API 클라이언트
        ├── stores/                  — 상태 관리
        ├── pages/                   — 페이지 컴포넌트 (9개)
        ├── components/              — 공통 컴포넌트
        │   ├── common/ (19개)
        │   ├── canvas-profit-chart.ts
        │   └── virtual-scroller.ts
        ├── layout/                  — 레이아웃 컴포넌트
        ├── types/                   — TypeScript 타입 정의
        └── utils/                   — 유틸리티
```

---

## 19. REST API 엔드포인트

| 라우트 | 파일 | 주요 기능 |
|--------|------|-----------|
| `/api/status` | status.py | 엔진 상태, 계좌 정보, 시장 단계 |
| `/api/settings` | settings.py | 설정 조회/수정 |
| `/api/account` | account.py | 계좌 잔고 조회 |
| `/api/trade` | trade.py | 수동 주문 (매수/매도) |
| `/api/settlement` | settlement.py | 정산 엔진 상태/리셋/입금 |
| `/api/market` | market.py | 시장 정보 (업종 목록, 종목 분류) |
| `/api/stock-classification` | stock_classification.py | 종목 분류 관리 |
| `/ws` | ws.py | 메인 WebSocket (상태/이벤트) |
| `/ws/orders` | ws_orders.py | 주문 관련 WS |
| `/ws/settings` | ws_settings.py | 설정 변경 WS |
| `/ws/subscribe` | ws_subscribe.py | 구독 제어 WS |

---

# 제3부: 운영 가이드 (실천)

## 1. 앱 시작/종료

### 1.1 시작

```bash
# macOS
./SectorFlow.command

# 수동 시작
cd /Users/sungjk0706/Desktop/SectorFlow
source .venv/bin/activate
python main.py
```

**SectorFlow.command 수행 과정:**
1. 가상환경 활성화
2. 이전 프로세스 안전 종료 (SIGTERM → SIGKILL)
3. 백엔드 실행 (`python main.py`)
4. 백엔드 준비 대기 (포트 8000 체크)
5. 프론트엔드 실행 (`npx vite`)
6. 프론트엔드 준비 대기 (포트 5173 체크)
7. 브라우저 자동 열기 (Chrome http://localhost:5173)
8. 종료 시 안전 정리 (trap cleanup)

### 1.2 종료

- **정상 종료**: 터미널에서 Ctrl+C
- **강제 종료**: `pkill -f "python main.py"` (최후 수단)

**종료 순서:**
1. WS 클라이언트 정상 종료
2. trade_history/journal consumer 중지
3. Telegram 봇 중지
4. 엔진 루프 중지
5. 시간 스케줄러 중지
6. DB writer 중지
7. DB 연결 종료

---

## 2. 세션 시작 시 필수 점검 항목

### 2.1 HANDOVER.md 확인

파일 위치: `/HANDOVER.md`

확인 내용:
- 완료 단계
- 현재 작업 중인 기능
- 다음 단계
- 미해결 문제

없으면: "이전 작업 내역이 없습니다. 새로 시작할까요?" 대기

### 2.2 아키텍처 불변 원칙 준수 확인

- 단일 asyncio 이벤트 루프 유지
- 모든 I/O는 async def
- run_in_executor 우회 금지
- 증권사 이름 공통 기능 침투 금지
- EventBus/발행구독 패턴 사용 금지
- SQLite 단일화 (ORM·무거운 추상화 금지)
- 블로킹 = 지연 = 왜곡 = 망함
- 실시간 파이프라인과 배치 파이프라인 분리
- 각 파이프라인 독립, 상호 간섭 금지
- 단일 소스 진리
- 이벤트 기반 루프 (폴링 금지)
- DB 연결 매번 생성/파기 금지
- 설정 매번 DB 쿼리 금지 (메모리 상주)
- 멀티스레드 남용 금지

### 2.3 파이썬 버전 확인

**가상환경 Python 3.12 사용 (필수)**
- Python 3.12 문법 지원: `Container | None` (PEP 604)
- `di/container.py`에서 사용 중
- 다른 버전 사용 시 타입 힌트 오류 발생 가능

### 2.4 시장 정보 확인

- KRX 마감: 15:30
- NXT(넥스트레이드) 마감: 20:00
- 공휴일: 매매 없음
- 두 시장을 항상 구분하여 처리

### 2.5 실시간 데이터 처리 금지 목록 확인

#### Python 백엔드 금지
- `time.sleep()` → `asyncio.sleep()` 사용
- `threading.Event().wait()` → `asyncio.Event().wait()` 사용
- `threading.Lock()`, `threading.RLock()` → `asyncio.Lock()` 사용
- `input()` → 절대 사용 금지
- `requests.get()`, `requests.post()` 등 → `httpx.AsyncClient` 사용
- `urllib.request` → `httpx.AsyncClient` 사용
- 대용량 dict/list 전체 `json.dumps()` 재직렬화 → delta만 직렬화
- 전체 리스트 순회 후 교체 → 인덱스/키 직접 접근으로 교체
- 매 틱마다 전체 데이터 재조회 → 변경분만 처리
- `threading.Thread()` 신규 생성 → 기존 이벤트 루프 활용
- `asyncio.create_task()` 무분별한 분리 → `schedule_engine_task()` 사용 또는 `add_done_callback()` 추가
- `asyncio.run()` → 절대 사용 금지 (단일 이벤트 루프 원칙 위반)
- `except Exception: pass` → `logger.warning()`으로 예외 로깅
- async 함수 호출 시 `await` 누락 → 반드시 `await` 사용 또는 `schedule_engine_task()`로 래핑
- no-op/dead code 방치 → 사용하지 않는 함수는 삭제 또는 명시적 DEPRECATED 표시
- Queue에 무한 쌓기 → 처리 속도 > 수신 속도 보장 필수

#### TypeScript 프론트엔드 금지
- `innerHTML` 전체 교체 → 변경된 요소만 업데이트
- `.map()` 전체 재생성 → 변경된 항목만 교체
- 전체 store 초기화 후 재설정 → 해당 key만 업데이트
- `setInterval()` 반복 전체 조회 → WS 이벤트 수신으로 대체
- `setTimeout()` 중첩 재귀 → 단일 이벤트 리스너로 대체
- `alert()`, `confirm()`, `prompt()` → 절대 사용 금지
- 대용량 `JSON.stringify()` 전체 직렬화 → delta만 직렬화

#### 공통 원칙
- 실시간 수신 데이터는 반드시 delta(변경분)만 처리
- 50ms 초과 감지 시 즉시 경고 로그
- 200ms 초과 시 해당 처리 중단 및 원인 보고
- 금지 항목 발견 시 수정 전 반드시 승인 요청

### 2.6 주요 파일 역할 확인

- `engine_account_notify.py`: WS 브로드캐스트 (delta)
- `engine_sector_confirm.py`: 업종 점수 증분 재계산
- `engine_ws_dispatch.py`: WS 메시지 분기 + 0J REAL 감지
- `daily_time_scheduler.py`: 시간 기반 타이머
- `trading.py`: 자동매매 실행
- `binding.ts`: WS 이벤트 → Store 액션 바인딩
- `stores/appStore.ts`: Zustand 전역 상태 (Record 기반)

### 2.7 작업 프로세스 준수

1. 파일 구조 파악
2. 호출처 추적
3. 영향 파일 확인
4. 불확실하면 질문
5. 승인
6. 실행
7. 테스트
8. 보고

### 2.8 롤백 기준 확인

- 단계 시작 전 반드시 git commit 또는 백업
- 심각한 오류 시 해당 단계 전체 롤백

### 2.9 응답 형식 준수

**금지 표현:** "~일 것입니다", "~로 보입니다", "~인 것 같습니다", "아마도 ~", "~때문일 수 있습니다", "~가능성이 있습니다", "일반적으로 ~", "보통 이런 경우에는 ~"

**허용 응답 형식:**
- [확인한 사실] (파일명+줄번호/함수명)
- [확인 필요 — 파일 읽겠습니다]
- [승인 요청] 변경내용/영향범위

---

## 3. 테스트모드와 실전투자의 차이점

테스트모드와 실전투자의 다른 점: 가상 매수/매도주문, 체결, 잔액, 계좌 등 돈에 관련된 것만 제외

나머지는 실전투자와 똑같음

즉 실제로 돈에 관련된 것만 가상으로 처리할 뿐 나머지는 실전투자와 똑같음

---

## 4. 성능 최적화 이력

### 4.1 SQLite WAL 및 Pragmas 적용

**문제**: 쓰기 작업 시 전체 DB 파일 락으로 읽기 작업 대기

**해결**:
```python
PRAGMA journal_mode = WAL
PRAGMA synchronous = NORMAL
PRAGMA cache_size = -64000
PRAGMA temp_store = MEMORY
PRAGMA mmap_size = 268435456
```

**효과**: 비동기 쓰기 수행 중에도 실시간 틱 계산에 필요한 읽기 작업 절대 블로킹되지 않음

### 4.2 DB 쓰기 직렬화 큐

**문제**: 동시 쓰기 작업 시 `database is locked` 오류

**해결**: `db_write_queue` + 전용 Background DB Writer 태스크

**효과**: 디스크 I/O 횟수 획기적 감소 (초당 100번 쓰기 → 1초에 1번 일괄 커밋)

### 4.3 GC 런타임 회피 전략

**문제**: 실시간 틱 폭주로 GC Stop-the-World 상태 → 50ms 이상 지연

**해결**:
- WS 구간 중 `gc.disable()`
- 장중 유휴 시간 및 장 마감 후 `gc.collect()`

**효과**: HFT 파이썬 엔진 지연 방지

---

# 부록

## A. 증권사 특이사항

### 키움증권

- 종목 코드: 6자리 (예: 005930)
- 호가 단위: 종목 가격대별 상이
- 실시간 시세: WebSocket (키움 OpenAPI+)
- 주문: REST API (HTS 인증 필요)

### LS증권

- 종목 코드: 6자리
- 호가 단위: 종목 가격대별 상이
- 실시간 시세: WebSocket (LS Xing)
- 주문: REST API

---

## B. SQLite Pragmas

```python
PRAGMA journal_mode = WAL          — Write-Ahead Logging 모드
PRAGMA synchronous = NORMAL        — 디스크 쓰기 속도 가속화
PRAGMA cache_size = -64000         — 64MB 캐시
PRAGMA temp_store = MEMORY        — 임시 테이블 메모리 보관
PRAGMA mmap_size = 268435456      — 256MB 메모리 매핑
```

---

## C. 메모리 모니터링

```python
import tracemalloc

tracemalloc.start()
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
```

배치 파이프라인에서 주기적 점검 설계

---

## D. TR 참조

증권사 TR(Transaction Request) 스펙은 `backend/data/broker_specs/` 디렉토리에 JSON 형식으로 저장

- `role_mappings`: TR ID ↔ 역할 매핑
- 증권사별 TR 포맷 정의

---

## E. 로깅 레벨

- **DEBUG**: 개발 중 상세 정보
- **INFO**: 일반적인 작동 정보
- **WARNING**: 예상치 못한 문제 (시스템 계속 작동)
- **ERROR**: 심각한 문제 (일부 기능 중단)
- **CRITICAL**: 치명적 문제 (시스템 중단)

---

## F. 커밋 메시지 규칙 (Conventional Commits)

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type**:
- `feat`: 새 기능
- `fix`: 버그 수정
- `refactor`: 리팩토링
- `docs`: 문서화
- `test`: 테스트
- `chore`: 기타

**예시**:
```
feat(stock): 실시간 시세 수신 기능 추가

WebSocket을 통한 실시간 시세 수신 기능 구현.
업종 점수 계산 로직과 연동.

Closes #123
```

---

## G. TDD 프로세스

1. **Red**: 실패하는 테스트 작성
2. **Green**: 테스트를 통과하는 최소한의 코드 작성
3. **Refactor**: 코드 리팩토링 (테스트 통과 유지)

### 테스트 작성 원칙

- **AAA 패턴**: Arrange (준비) → Act (실행) → Assert (검증)
- **단일 책임**: 하나의 테스트는 하나의 것만 검증
- **명확한 이름**: 테스트 이름으로 무엇을 검증하는지 명확히
- **독립성**: 테스트 간 의존성 없이 순서 상관없이 실행 가능

### 테스트 커버리지 기준

- **최소 커버리지**: 80%
- **핵심 로직**: 95% 이상
- **도구**: pytest-cov (Python), Vitest coverage (TypeScript)

---

## H. 코드 품질 관리

### 리팩토링 기준

- **복잡도**: 함수 복잡도 10 이하, 파일 복잡도 50 이하
- **길이**: 함수 50줄 이하, 파일 500줄 이하
- **중복**: 같은 로직 3회 이상 반복 시 함수 추출
- **이름**: 의도를 명확히 전달하는 이름 사용

### 정적 분석 도구

```bash
# Python
mypy backend/  # 타입 검사
ruff check backend/  # 린팅
pylint backend/  # 코드 품질

# TypeScript
npm run type-check  # 타입 검사
npm run lint  # 린팅
```

### 코드 품질 점검 리스트

- [ ] 타입 힌트 포함 (Python)
- [ ] 함수/클래스에 docstring 포함
- [ ] 매직 넘버 제거 (상수로 대체)
- [ ] 불필요한 주석 제거 (코드가 스스로 설명하도록)
- [ ] 예외 처리 적절히 수행
- [ ] 로깅 적절히 추가

---

## I. 개발 프로세스

### 구현 계획 수립

1. **요구사항 명확화**: 사용자 요구사항을 문서화
2. **파일 구조 분석**: 관련 파일 및 의존성 파악
3. **단계별 계획 작성**: 각 단계의 목표, 파일, 검증 방법 명시
4. **사용자 승인**: 계획 승인 후 실행

### 계획서 형식 (plan.md)

```markdown
# [기능명] 구현 계획

## 요구사항
- [기능 설명]

## 관련 파일
- backend/app/domain/xxx.py
- frontend/src/components/xxx.tsx

## 단계별 계획
### 단계 1: 데이터 모델 수정
- 파일: backend/app/domain/xxx.py
- 변경 내용: [상세]
- 검증: 테스트 작성 및 실행

### 단계 2: API 엔드포인트 추가
- 파일: backend/app/api/xxx.py
- 변경 내용: [상세]
- 검증: API 테스트

### 단계 3: 프론트엔드 UI 구현
- 파일: frontend/src/components/xxx.tsx
- 변경 내용: [상세]
- 검증: 브라우저 테스트
```

### YAGNI (You Aren't Gonna Need It)

- **원칙**: 당장 필요하지 않은 기능은 구현하지 않음
- **적용**: 미래의 확장성을 위해 과도한 추상화 금지
- **예외**: 아키텍처 원칙에 명시된 경우 제외

### DRY (Don't Repeat Yourself)

- **원칙**: 중복 코드 제거
- **적용**: 같은 로직 3회 이상 반복 시 함수/클래스 추출
- **주의**: 과도한 추상화로 가독성 저하 금지

---

## J. CI/CD 전략 (로컬 환경)

1. **사전 커밋 검사**: 타입 검사, 린팅, 테스트
2. **커밋 후 검증**: 빌드, 통합 테스트
3. **배포 전 검증**: 전체 테스트, 수동 테스트

---

## K. CHANGELOG 관리

```markdown
# Changelog

## [Unreleased]
### Added
- 실시간 시세 수신 기능
- 업종 점수 계산

### Changed
- DB 연결 최적화

### Fixed
- 메모리 누수 수정

## [1.0.0] - 2026-01-01
```

---

## L. API 문서화

- **FastAPI**: 자동 생성되는 Swagger UI 활용 (`http://localhost:8000/docs`)
- **TypeScript**: JSDoc으로 함수/클래스 문서화
- **README.md**: 프로젝트 개요, 설치, 실행 방법

---

## M. 표준 용어 사전 (원칙 23 준수)

> 같은 의미를 가리키는 단어가 코드/화면/로그/문서에서 혼용되는 것을 금지.
> 아래 표준 용어만 사용. 금지 용어는 신규 코드/로그/문서에 사용 금지.
> 기존 코드의 금지 용어는 점검 세션에서 순차적 표준 용어로 교체.

| 표준 용어 | 금지 용어 | 적용 범위 | 비고 |
|-----------|-----------|-----------|------|
| 업종 | 섹터 | 코드/화면/로그/문서 전 영역 | 도메인 용어 통일. 단, 파일명/클래스명의 `sector`는 코드 식별자로 허용 (예: `sector_calculator.py`) |
| 종목 | 주식 | 코드/화면/로그/문서 전 영역 | 도메인 용어 통일. 단, 파일명/클래스명의 `stock`은 코드 식별자로 허용 (예: `stock_filter.py`) |
| 매수 | Buy, 구매 | 화면/로그/문서 | 거래 용어 통일. 단, 코드 식별자의 `buy`/`execute_buy`는 허용 |
| 매도 | Sell, 판매 | 화면/로그/문서 | 거래 용어 통일. 단, 코드 식별자의 `sell`/`execute_sell`은 허용 |
| 매수 후보 | 바이 리스트, 매수 타겟 | 화면/로그/문서 | UI 표시명 통일 |
| 보유 종목 | 홀딩, 포지션 | 화면/로그 | UI 표시명 통일. 단, 코드 식별자의 `position`/`holdings`는 허용 |
| 증권사 표시명 | 코드 식별자 (화면/로그 한정) | 화면/로그 | "LS증권", "키움증권" 등 사전 정한 표시명 사용. 단, 코드 내부 식별자(`ls_`, `kiwoom_`)는 원칙 4에 따라 유지 |

> **코드 식별자 예외**: 파일명, 클래스명, 함수명, 변수명에 포함된 영어 식별자(`sector`, `stock`, `buy`, `sell`, `position`)는 코드 가독성과 관행상 허용. 원칙 23의 용어 통일은 **사용자에게 보이는 화면 텍스트, 로그 메시지, 문서 설명**에 적용.
> **확장**: 신규 용어 혼용 발견 시 이 사전에 추가하여 합의 후 적용.

---

# 최종 권고

SectorFlow 아키텍처 불변 원칙은 "1인 로컬 실시간 주식 자동매매 웹 어플리케이션" 목적에 한해 100점 만점에 98점짜리 최적의 설계.

### 핵심 요약

- 단순한 비동기 단일 루프 + 메모리 캐시 구조는 분산 큐(Kafka)나 무거운 백엔드 프레임워크보다 로컬 환경에서 더 낮은 지연(1ms 미만)과 높은 데이터 정합성 제공
- SQLite 단일화 및 ORM 배제 원칙은 로컬 환경 효율 극대화 탁월 선택
- 실시간성과 디스크 I/O 병목 상충 관계 완벽 해결 위해 Pragmas WAL 모드 활성화와 DB 쓰기 전용 백그라운드 큐 직렬화 조치를 아키텍처 규칙에 명문화 적용 권고
- 제시된 원칙들이 프로젝트 내 철저히 유지 시 군더더기 없고 디버깅 쉬우며 실시간 성능 극대화 최고 수준 자동매매 솔루션 완성 가능

