# SectorFlow 아키텍처

> 1인 로컬 주식 자동매매 웹앱 — Python 백엔드 + TypeScript 프론트엔드
> 단일 asyncio 이벤트 루프 기반 실시간 파이프라인 아키텍처
>
> **본 문서는 모든 코드 수정의 유일한 기준이다.** 코드는 본 문서를 따라야 하며, 본 문서가 코드를 따라가서는 안 된다.
> 본 문서와 코드가 불일치할 때는 코드가 살아있는 실행 경로라면 코드를 기준으로 본 문서를 갱신한다(근거: W6 살아있는 안전장치).
> 작업자(AI)의 세션 절차·응답 형식·금지 패턴 체크리스트는 `AGENTS.md`를 따른다. 본 문서는 "시스템이 어떻게 동작해야 하는가"만을 다룬다.

---

## 문서 구조

본 문서는 3개 층으로 구성된다.

| 층 | 내용 | 표현 | 변경 조건 |
|----|------|------|-----------|
| **L1 불변 원칙** | 돈·안전 관련 절대 규칙 (W1~W12) + 안전 규칙 | "~해야 한다", "~금지" | 근거 명시 후에만 변경 |
| **L2 설계 결정과 근거** | 구조 선택 + "왜 이렇게 했는가" | 서술 | 구조를 바꾸려면 본 문서부터 수정 |
| **L3 수치 참조표** | 구현 세부 수치의 코드 상수 위치 | `파일명:상수명` | 값은 코드가 주인, 본 문서는 위치만 참조 |

**수치 소유권 분리 기준 (W3 SSOT):**
- 전략·안전 수치(지연 임계치, 서킷브레이커 임계치, 구독 한도, 일일 손실 한도 기본값): **본 문서가 주인** — 값 + 근거 명시 (L1 또는 L2)
- 구현 세부 수치(큐 크기, 배치 주기, 쓰로틀 간격): **코드 상수가 주인** — 본 문서는 L3 참조표에 위치만 기재

왜: 수치가 문서와 코드 양쪽에 존재하면 어느 쪽을 고쳐도 다른 쪽이 낡는다(드리프트의 구조적 원인). 수치의 주인을 한 곳으로 몰면 문서는 영구적으로 참조만 하므로 드리프트가 차단된다.

---

# L1. 불변 원칙

> 돈·안전과 직접 관련된 절대 규칙. 구조가 변경되더라도 동일한 안전성을 보장해야 하는 원칙.
> 표현은 "~해야 한다" / "~금지"만 사용한다. 모호한 표현 금지.
> 기존 25개 원칙(P1~P25)을 교차 중복 제거하여 12개(W1~W12)로 통합. 매핑표는 부록 A 참조.

## W1. 단일 루프·논블로킹

**모든 비동기 작업은 단일 asyncio 이벤트 루프 내에서 처리해야 한다.** 멀티스레드·멀티프로세스 분산 금지.
**모든 I/O는 `async def`여야 한다.** 동기 함수 금지.
**블로킹은 금지한다.** 블로킹 = 지연 = 데이터 왜곡 = 시스템 붕괴.

구현 요건:
- `main.py`에서 `uvicorn.run(..., loop="uvloop")` 사용. 모든 코루틴은 단일 루프에서 실행.
- HTTP: `httpx.AsyncClient` 사용. 동기 `requests`/`urllib.request` 금지.
- DB: `aiosqlite` 사용. 동기 `sqlite3` 금지.
- 대기: `asyncio.sleep()` 사용. 동기 `time.sleep()`/`threading.Event().wait()` 금지.
- 락: `asyncio.Lock` 사용. 동기 `threading.Lock`/`threading.RLock` 금지.
- `loop.run_in_executor()`로 동기 코드를 비동기로 위장하는 행위 금지. 진짜 async 라이브러리로 교체.
- `threading.Thread()` 신규 생성 금지.
- `asyncio.create_task()` 무분별 분리 금지 → `schedule_engine_task()` 사용 또는 `add_done_callback()` 추가.
- `asyncio.run()` 절대 사용 금지 (단일 루프 원칙 위반).
- 틱 핸들러에 per-tick O(n) 연산 금지. 매 틱마다 DB 조회 금지. 매 틱마다 전체 리스트 순회 금지.
- 매 틱마다 `asyncio.sleep(0)`로 협력적 양보하여 이벤트 루프 고갈을 방지해야 한다.
- Queue에 무한 쌓기 금지 — 처리 속도 > 수신 속도 보장 필수.

> 통합 근거: P1(단일 루프), P2(모든 I/O async), P3(run_in_executor 금지), P7(블로킹 금지), P14(멀티스레드 남용 금지) + 금지 패턴 1·2·4는 같은 맥락의 세부 요건.

## W2. 파이프라인 분리

**실시간 파이프라인과 배치 파이프라인은 명확히 분리해야 한다.** 각 파이프라인은 독립적이며 상호 간섭 금지.

구현 요건:
- 실시간: `tick_queue` → Compute Loop → Gateway Loop.
- 배치: `market_close_pipeline.py` (20:40 확정 시세 + 5거래일 일봉 다운로드).
- 배치 연산 중 실시간 틱 수집을 차단해서는 안 된다.
- 실시간 루프에서 대량 디스크 쓰기 금지 → `db_write_queue`로 쓰기 직렬화.
- 물리적 루프와 데이터 배관은 완전 분리.

> 통합 근거: P8(파이프라인 분리), P9(상호 간섭 금지).

## W3. 단일 소스 진리 (SSOT)

**같은 데이터는 한 곳에서만 관리해야 한다.** 두 번째 데이터 소스 생성 금지.

구현 요건:
- 설정: `integrated_system_settings_cache`(메모리) → SQLite `integrated_system_settings` 테이블(영속). 모든 모듈이 캐시를 직접 참조.
- 종목 정보: `master_stocks_cache`(메모리) → `master_stocks_table`(영속).
- DB 연결은 앱과 생명주기를 공유. `database.py`의 `_db_connection` 싱글톤. 매 요청마다 `connect()` 금지.
- 설정은 메모리 상주. 틱 연산 단계에서 DB 설정 조회 금지 → O(1) 메모리 딕셔너리 조회. 설정 변경 시: DB 저장 → 캐시 갱신 → `apply_settings_change()`.
- 플래그(`auto_buy_on` 등)는 `integrated_system_settings_cache`에서만 관리. 한 플래그의 정의·설정·읽기가 같은 변수를 가리켜야 한다. 여러 곳에서 플래그 직접 수정 금지.

> 통합 근거: P10(SSOT), P12(DB 연결 싱글톤), P13(설정 메모리 상주), P17(플래그 단일 소스).

## W4. 단계 간 정합성

**SSOT(W3)는 데이터 출처를 하나로 통일하지만, 파이프라인 여러 단계를 거치는 데이터 조작 시 단계 간 일관성은 별도로 보장해야 한다.**

구현 요건:
- **파생 데이터 모델 선호**: 두 번째 데이터 저장소를 운영하는 대신 하나의 원본에서 파생(예: `trades` 테이블 → `build_positions_from_trades()`로 포지션 산출). 중복 저장 금지.
- **원자성 보장**: 다중 단계 데이터 조작이 불가피할 경우 단일 트랜잭션으로 묶거나 순차 실행 보장. 중단/예외 시 부분 영속화 방지.
- **기동 시 대조(reconciliation)**: 메모리 상태와 영속화된 상태(또는 실전 모드의 경우 증권사 서버 상태) 간 불일치 탐지 및 정정. **테스트모드와 실전모드 모두 스킵 금지** — 테스트모드는 `settlement_engine.reconcile_with_trades()`(구현됨), 실전모드는 증권사 조회값 vs 내부 기록 대조(D14, 현재 미구현).
- **런타임 주기적 대조**: 실전 모드에서는 WS 체결 통보 누락·네트워크 장애 등으로 내부 기록과 실제 계좌가 조용히 어긋날 수 있으므로, 런타임 중 주기적 증권사 재조회 대조가 필요(D17, 현재 미구현).
- **불일치 발견 시 즉시 차단**: silent 무시 금지 → `logger.critical` 경고 + 관련 파이프라인 중단. 유령 데이터가 후속 파이프라인(매도 등)에 전파되는 것을 원천 차단.

> 통합 근거: P22(데이터 정합성). 배경: 유령 포지션 사례(`docs/ghost_position_investigation.md`). 실전 모드 재기동 잔고 동기화 기준은 D14, 런타임 주기적 대조는 D17 참조.

## W5. 단일 주문 경로

**주문 경로는 하나만 둬야 한다.** 병렬 주문 경로·죽은 주문 경로·주문 로직 분기 금지.

구현 요건:
- `trading.py`의 `execute_buy()` / `execute_sell()` 단일 경로.
- 테스트모드: `dry_run.fake_send_order()`.
- 실전: `router.order.send_order()`.
- 모드 분기는 돈 I/O 최소 지점(`dry_run.fake_send_order()`)에만 존재. 그 외 로직 분기 금지.

> 통합 근거: P15(단일 주문 경로). 주문 멱등성 기준은 D12 참조.

## W6. 살아있는 안전장치

**안전/제어 장치는 실제 실행 경로에 연결되어 동작이 입증돼야 한다.** 호출되지 않는 안전코드(dead code)는 위험한 착시이므로 금지.

구현 요건:
- `RiskManager`는 `execute_buy()`/`execute_sell()` 내부에서 호출.
- `CircuitBreaker`는 주문 전후에 호출.
- 작성한 안전장치가 실제 실행 경로에 연결됐는지 확인. 호출되지 않는 함수는 삭제 또는 명시적 `# DEPRECATED` 표시.
- "기준인 척하는 dead rule" 금지 — 문서에만 존재하고 코드에서 실행되지 않는 규칙은 제거.

> 통합 근거: P16(살아있는 경로 배선) + 금지 패턴 5(dead code 방치).

## W7. 테스트모드 동등성

**전략 판단·리스크 게이트·주문 상태 전이는 테스트모드와 실전모드가 동일하게 유지돼야 한다.** 계좌·잔고·체결·정산의 외부 원장만 테스트용 원장으로 대체한다.

구현 요건:
- 모드 분기는 돈 I/O 최소 지점(`dry_run.fake_send_order()`)에만.
- 모든 안전장치는 테스트모드에서 검증 가능해야 한다.
- 업종 점수 계산, 필터링, 타이밍 로직은 동일.
- 수수료/세금 계산은 테스트모드에서만 수행. 실전모드는 증권사 서버가 수수료/세금의 SSOT이므로 SectorFlow가 자체 계산하지 않는다(외부 원장의 일부로 취급).
- 기동 시 대조(reconciliation)는 테스트모드에서도 스킵 금지.
- **시뮬레이터 응답 형태 = 증권사 응답 형태**: 가상 체결·잔고·주문 응답을 만들 때, 실전에서 증권사가 주는 응답 구조(체결가·체결시간·수량·주문번호·상태 등 필드)와 최대한 동일한 형태로 만들어야, 손익 계산·체결 판정 함수가 "이게 실전 데이터인지 가상 데이터인지 모른 채" 동일하게 동작할 수 있다. 이게 테스트가 실전을 제대로 대변하는 핵심 조건이다.

> 통합 근거: P18(테스트모드 동등성).
> **현재 상태(W6 투명성)**: 키움 응답 구조는 시뮬레이터가 모방(`data.output.ord_no` 등). 단 LS 증권 응답 구조(`order_no`/`raw_res`)와 시뮬레이터 불일치 — 공통 데이터 모델 부재로 증권사별 분기 처리 필요. 후속 과제: `docs/설계서/실전모드_불일치_조정.md` 섹션 5 참조.

## W8. 폴백 금지

**정상 경로의 데이터 누락·초기화 실패를 기본값으로 덮어 숨기지 않는다.** 폴백은 사실상 제2의 데이터 소스를 만드는 것이므로 W3(SSOT)와 충돌.

구현 요건:
- 정상 경로에서 절대 발생하지 않아야 할 상태(빈 문자열, None, 누락)를 폴백으로 덮지 말 것.
- 폴백 분기가 필요하다는 것 자체가 상위 초기화나 데이터 흐름에 결함이 있다는 신호. 결함이 발견되면 폴백으로 덮지 말고 **원인을 제거**할 것.
- 부득이하게 예외 상황을 처리해야 한다면 silent fallback이 아니라 **에러 로그**를 출력하여 즉시 인지 가능하게 할 것.
- `except Exception: pass` 금지 → `logger.warning(..., exc_info=True)`로 예외 로깅.

> 통합 근거: P20(폴백 금지) + 금지 패턴 3(silent except pass).

## W9. 격리된 실패

**한 구성요소의 실패가 전체 시스템 기동/운영을 블로킹해서는 안 된다.** 실패는 해당 구성요소에서 차단 + 로깅, 다른 구성요소는 정상 작동 유지.

구현 요건:
- 백엔드: 태스크/코루틴 실패가 루프 전체를 중단하지 않도록 `schedule_engine_task()` 사용. 격리 시 에러 로깅(silent pass 금지).
- 프론트엔드: 개별 칩/컴포넌트 렌더링 실패가 전체 화면을 중단하지 않도록 store listener 루프에 전파 차단(try/catch + 로깅). 격리 시 에러 로깅(silent pass 금지).

> 통합 근거: P25(격리된 실패).

## W10. 사용자 투명성

**사용자가 인지하지 못하는 상태에서 중요한 의사결정(매수/매도, 리스크 차단 등)이 이루어져서는 안 된다.** 중요한 로직은 반드시 사용자와 사전 상의하거나 설정으로 제어할 수 있어야 한다.
**백엔드에서 발생하는 중요한 상태 변화는 프론트엔드 UI에서 사용자가 확인할 수 있도록 표시해야 한다.**

구현 요건:
- 매매 차단 원인(리스크 초과, 가드 조건 미충족, 자동매수 OFF 등)은 화면 상단 헤더 칩뿐 아니라 해당 페이지(매수 후보/보유 종목)의 각 항목 배지에서도 즉시 확인할 수 있어야 한다.
- 사용자가 "왜 이 종목이 매수되지 않았지?"라고 의문을 갖지 않도록 할 것.
- 사용자가 헤더까지 올라가지 않고도 해당 종목 옆에서 차단 사유를 바로 볼 수 있도록 할 것.

> 통합 근거: P21(사용자 투명성).

## W11. 표현 통일

**같은 의미/기능을 가리키는 대상은 코드/화면/로그/문서 전 영역에서 하나의 방식으로 통일해야 한다.** 파일 간 불일치 금지.

구현 요건:
- **용어 통일**: 표준 용어 사전(부록 B) 준수. "업종"(섹터 금지), "종목"(주식 금지), "매수 후보"(바이 리스트·매수 타겟 금지), "보유 종목"(홀딩·포지션 금지, 단 코드 식별자 `position`/`holdings`는 허용).
- **네이밍 일관성**: Python `snake_case` / TS `camelCase`·`PascalCase` / 파일명 `kebab-case.ts` / WS 이벤트 `kebab-case`. `_`/`-` 혼용 금지.
- **공통 자산 재사용**: 신규 함수/상수/컴포넌트/패턴 구현 전, 기존 공통 자산(`core/constants.py`, `frontend/src/components/common/`, 기존 함수 등)을 먼저 검색. 같은 기능을 새로 만들지 말 것.
- **로그/용어 생성 시 기존 표현 확인**: 신규 로그·상태명·UI 텍스트·주석 생성 시 동일 동작의 기존 표현을 코드베이스에서 먼저 검색하여 일치시킬 것. 동일 동작에 서로 다른 표현 공존 금지.
- **UI 패턴 일관성**: 동일한 UI 패턴이 2회 이상 반복 시 공통 컴포넌트로 추출.
- **후안 B 부호 규칙**: 하락/손실은 음수, 상승/이익은 양수(부록 B.2 참조).

> 통합 근거: P23(일관된 통일성).

## W12. 중복·과잉 추상화 금지

**중복 제거를 줄 수 단축보다 우선한다.** 더 단순한 대체 가능성을 먼저 검토한다. 불필요한 추상화·1회용 래퍼 금지.

구현 요건:
- 동일 로직 중복이 없는가? (W3·W11과 교차 강화)
- 함수/파일 길이가 50/500줄을 초과하면 책임 분리를 검토할 것. (50/500줄은 분할 검토 참고 기준, 자동 위반 아님.)
- 순환 복잡도 10 이하 권장.
- 불필요한 추상화·1회용 래퍼 금지.
- 당장 필요하지 않은 기능은 구현하지 않는다(YAGNI). 단, 본 문서에 명시된 원칙은 예외.

> 통합 근거: P24(단순성).

---

## 안전 규칙 (항상 적용)

> 돈·DB·시스템에 직결되는 절대 규칙. W1~W12와 동등한 강제력.

1. `backend/data/stocks.db`를 포함한 모든 `*.db` 파일을 직접 삭제하거나 덮어쓰지 않는다.
2. DB 스키마 변경·마이그레이션 전, `stocks.db`, `stocks.db-shm`, `stocks.db-wal`의 타임스탬프 백업을 생성한다.
3. 사용자가 실제 돈을 사용하겠다고 명시적으로 확인하고 경고를 받기 전까지 매매 코드는 테스트 모드로 유지한다.
4. 증권사 API 키, 토큰, 자격 증명을 하드코딩하지 않는다.
5. 사용자 승인 없이 `sudo`, `rm -rf`, `curl`, `wget`, `sqlite3`를 실행하지 않는다.
6. `~/.bashrc`, `~/.zshrc`, 시스템 경로를 수정하지 않는다.

---

# L2. 설계 결정과 근거

> 현재 1인 로컬·단일 프로세스 환경에 적합하여 선택한 구현 방식. 향후 규모·요구사항·측정 결과가 바뀌면 재검토 가능.
> 구조를 바꾸려면 본 문서부터 수정한 뒤 코드를 따라야 한다.

## D1. 단일 프로세스에서는 EventBus 미사용

현재는 직접 호출 체인과 `asyncio.Queue` 파이프라인을 사용한다. 별도의 EventBus·Redis Pub/Sub·분산 메시지 브로커·콜백 리스트 옵서버 패턴을 도입하지 않는다.

**근거**: 1인 로컬 단일 프로세스에서는 직접 호출 체인이 호출 추적성·예외 전파·재처리·종료 처리를 가장 단순하게 만든다. 프로세스 분리나 다중 소비자가 필요해질 경우 재검토 대상.

> 기존 P5.

## D2. SQLite 단일화

1인 로컬 앱의 데이터 규모와 운영 방식을 고려하여 SQLite를 단일 영속 저장소로 사용한다.

- SQLite WAL 모드 + Pragmas(부록 C).
- Raw SQL 직통 사용. ORM 미사용.
- 단일 커넥션 생명주기 관리(W3).
- DB 쓰기 직렬화 큐(`db_write_queue` + 전용 Background DB Writer)로 동시 쓰기 `database is locked` 오류 방지. 디스크 I/O 획기적 감소(초당 100번 쓰기 → 1초에 1번 일괄 커밋).

**근거**: 1인 로컬 데이터 규모에서 SQLite가 충분하며, 단일 영속 저장소가 W3(SSOT)를 가장 단순하게 보장한다.

> 기존 P6.

## D3. 증권사 이름 공통 기능 침투 금지

특정 증권사 이름이 공통 로직에 침투하는 것을 금지한다.

- `BrokerRouter` + `ConnectorManager` 추상화 사용.
- 공통 로직에 `kiwoom_`, `ls_` 접두사 금지.
- 증권사별 구현은 `core/kiwoom_*.py`·`core/ls_*.py`에 분리(`broker_factory.py`/`broker_registry.py` 레지스트리 경유).
- 증권사 표시명은 사전 정한 표시명("키움증권", "LS증권") 사용. 단, 코드 내부 식별자는 유지.

**근거**: 다중 증권사 지원 시 공통 로직이 증권사별 코드에 오염되면 유지보수 비용이 급증한다.

> 기존 P4.

## D4. 이벤트 기반 루프 (폴링 금지)

내부 상태 확인을 위한 `while + sleep` 폴링 금지. `asyncio.Queue` + `asyncio.wait()`/`asyncio.wait_for()` 이벤트 기반으로 처리.

- `daily_time_scheduler.py`에서 `asyncio.call_later()` 사용.
- **외부 서비스 long polling 예외**: 외부 서비스가 WebSocket이나 webhook 등 push 방식을 제공하지 않는 경우 해당 서비스의 long polling은 예외적으로 허용. 단, 긴 대기시간·취소 가능한 비동기 요청·종료 시 태스크 취소·오류 재시도·빠른 반복 요청 방지·엔진 루프와의 실패 격리를 갖춰야 한다.

**근거**: 폴링은 불필요한 CPU 점유와 지연을 유발한다. 이벤트 기반이 W1(논블로킹)과 일치한다.

> 기존 P11.

## D5. 런타임 검증 게이트

`py_compile`/import 성공은 검증이 아니다. 변경은 실제 실행 경로를 흘려보는 런타임 점검이 필요.

- `RuntimeWarning(coroutine never awaited)`을 error로 승격: `.venv/bin/python -W error::RuntimeWarning main.py`.
- 테스트로 실제 동작 검증.
- `mypy`는 사전 에러 존재로 표준 검증 게이트 아님(사용 시 기존 실패 추적 비용 발생).

**근거**: 정적 성공이 런타임 안전을 보장하지 않는다. await 누락은 실전에서 치명적이다.

> 기존 P19.

## D6. 브라우저 종료와 백엔드 분리

브라우저(WS 클라이언트)가 모두 닫혀도 백엔드는 계속 실행된다. 브라우저를 닫아도 자동매매는 중단되지 않으며, 다시 접속하면 이어서 확인 가능. 앱 종료는 실행 스크립트 종료(Ctrl+C, 터미널 닫기) 시에만 발생.

**근거**: 자동매매는 사용자가 화면을 보지 않아도 동작해야 한다. 시작 스크립트는 백엔드·프론트엔드까지만 기동하고 브라우저는 사용자가 직접 연다(접속 안내 출력만 존재, 브라우저 자동 열기 없음, WS 끊김 시 자동 종료 로직 없음).

> 1단계 사용자 결정 Q2 반영.

## D7. OMS 서킷브레이커 (재검토 예정)

> 본 절은 **OMS 서킷브레이커**(`backend/app/services/circuit_breaker.py`)에 한정. **KRX 서킷브레이커/사이드카**(`engine_state.krx_circuit_breaker_active`)는 증권사 수신 데이터로 동작하므로 본 절 대상 아님.

> **재검토 예정 (2026-07-29 사용자 결정)**: OMS 서킷브레이커 자체가 1인 로컬 자동매매 앱에서 정말 필요한 안전장치인지 추후 심도 있는 논의가 필요. 본 절은 현재 구현 상태를 사실 그대로 명시하되, 기준 확정은 보류. 아래 내용은 현행 구현의 관찰 기술(기준 아님).

서킷브레이커 상태 전이 (현재 구현):
- CLOSED(정상) → OPEN(차단): 주문 실패 5회 연속 누적.
- OPEN → HALF_OPEN(복구 시도): 60초 경과 후 다음 주문 1건 허용.
- HALF_OPEN → CLOSED: 복구 판정 주문 성공.
- HALF_OPEN → OPEN: 복구 판정 주문 실패.

**복구 판정 주문의 실체 (현재 구현)**:
- 테스트모드: 가상 체결(`dry_run.fake_send_order()`). 돈이 나가지 않는다.
- 실전모드: 별도의 가상 점검 주문(probe)은 존재하지 않는다. **다음 실제 주문 1건(실제 돈)이 복구 판정을 겸한다.**

용어: "테스트 주문"이라는 표현 대신 **"복구 판정 주문"**으로 용어 정확화.

**실주문 관련 우려**: 실전 모드에서 복구 판정 주문이 사용자의 매매 의사와 무관하게 실제 돈을 노출시키는 문제는, OMS 서킷브레이커 재검토와 별개로 **D16 "실전 모드 사용자 모르는 주문 금지" 원칙**으로 보편적 기준을 별도 명시.

> 1단계 사용자 결정 Q1 반영. 코드 확인 사실 그대로 명시. 2026-07-29 재검토 예정 표시 추가.

## D8. 구독 한도 200 = 키움증권 세션 한도 기준

WS 구독 종목 수 기본 한도 200은 키움증권 세션 한도 기준의 보수적 상한이다. LS증권은 더 많은 세션 한도(약 300개 이상)를 제공하므로 여유가 있다.

**근거**: 보수적 상한으로 설정하면 다중 증권사 환경에서 안전하게 운영 가능. LS증권 단독 운영 시 한도 상향 검토 대상.

> 1단계 사용자 결정 Q3 반영.

## D9. 실시간 데이터 처리 금지 목록

### Python 백엔드 금지
- `time.sleep()` → `asyncio.sleep()`
- `threading.Event().wait()` → `asyncio.Event().wait()`
- `threading.Lock()`/`threading.RLock()` → `asyncio.Lock()`
- `input()` → 절대 사용 금지
- `requests.get()`/`requests.post()`/`urllib.request` → `httpx.AsyncClient`
- 대용량 dict/list 전체 `json.dumps()` 재직렬화 → delta만 직렬화
- 전체 리스트 순회 후 교체 → 인덱스/키 직접 접근으로 교체
- 매 틱마다 전체 데이터 재조회 → 변경분만 처리
- `threading.Thread()` 신규 생성 → 기존 이벤트 루프 활용
- `asyncio.create_task()` 무분별 분리 → `schedule_engine_task()` 또는 `add_done_callback()`
- `asyncio.run()` → 절대 사용 금지
- `except Exception: pass` → `logger.warning(..., exc_info=True)`
- async 함수 호출 시 `await` 누락 → 반드시 `await` 또는 `schedule_engine_task()`로 래핑
- no-op/dead code 방치 → 사용하지 않는 함수 삭제 또는 명시적 `# DEPRECATED`
- Queue에 무한 쌓기 → 처리 속도 > 수신 속도 보장

### TypeScript 프론트엔드 금지
- `innerHTML` 전체 교체 → 변경된 요소만 업데이트
- `.map()` 전체 재생성 → 변경된 항목만 교체
- 전체 store 초기화 후 재설정 → 해당 key만 업데이트
- `setInterval()` 반복 전체 조회 → WS 이벤트 수신으로 대체
- `setTimeout()` 중첩 재귀 → 단일 이벤트 리스너로 대체
- `alert()`/`confirm()`/`prompt()` → 절대 사용 금지
- 대용량 `JSON.stringify()` 전체 직렬화 → delta만 직렬화

### 공통
- 실시간 수신 데이터는 반드시 delta(변경분)만 처리.
- 50ms 초과 감지 시 즉시 경고 로그.
- 200ms 초과 시 해당 처리 중단 및 원인 보고.

## D10. 시장 정보

- KRX 마감: 15:30
- NXT(넥스트레이드) 마감: 20:00
- 공휴일: 매매 없음.
- 두 시장을 항상 구분하여 처리.

## D11. Python 버전

가상환경 Python 3.12 사용(필수). `Container | None`(PEP 604) 문법 사용 중(`di/container.py`). 다른 버전 사용 시 타입 힌트 오류 발생 가능.

## D12. 주문 멱등성

**기준**: 주문은 식별 가능해야 하며, 동일 종목에 미체결 주문이 존재할 때 새 주문을 전송해서는 안 된다.

구현 요건:
- 모든 주문은 `order_id`를 발급받아야 한다. 증권사 응답에 `order_id`가 있으면 사용, 없으면 타임스탬프 기반으로 생성(`trading.py` `execute_buy()`/`execute_sell()`).
- 종목별 `has_open_buy` 플래그로 미체결 주문 존재 시 차단(`BUY_REJECT_OPEN_ORDER`). 체결 완료 시 플래그 해제.
- 주문 요청은 저널에 기록(`journal.record_order_request()`, status="pending").

**현재 상태(W6 투명성)**: 위 기준은 구현되어 작동 중. 단, 네트워크 타임아웃·재기동 등 재전송 시나리오에서 동일 요청이 새 주문으로 발생하는 것을 막는 진정한 멱등성 키(client_order_id/UUID 기반, 재전송 시 기존 주문 ID 반환)는 미구현.

**후속 과제(별도 승인 필요)**: 증권사 API의 `client_order_id` 지원 여부 조사 후 진정한 멱등성 키 도입. 재기동 시 중복 주문 위험은 D13(미체결 주문 복구)에서 다룸.

## D13. 기동 시 미체결 주문 복구 (실전 모드)

**기준**: 실전 모드 기동 시 이전 세션의 잔여 미체결 주문이 존재해서는 안 되며, 존재할 경우 반드시 사용자에게 표시 후 처리(취소 또는 유지)해야 한다(W10 사용자 투명성).

구현 요건:
- 실전 모드 기동 시 증권사 미체결 주문 조회 API 호출 → 잔여 미체결 주문 목록 확보.
- 미체결 주문 존재 시 UI에 명시적 표시 + 사용자 결정(취소/유지) 대기. 자동 처리 금지(W10).
- 테스트모드는 `fake_send_order()`가 동기식 즉시 체결 응답을 반환하므로 미체결 상태가 발생하지 않음 → 복구 절차 제외(W7 동등성 위반 아님: 발생 자체가 없는 상태).

**현재 상태(W6 투명성)**: 미구현. 기동 시 저널 기반 미체결 복구도, 증권사 미체결 주문 조회 API 호출도 없음. 키움·LS 모두 미체결조회 API 자체가 미구현 상태. 자동매매 루프 내에서는 `has_open_buy` 플래그로 실시간 중복 주문을 차단하지만, 이는 기동 시 잔여 주문 복구와는 별개 문제.

**후속 과제(별도 승인 필요)**: 실전 모드 기동 시 미체결 주문 조회·동기화 로직 구현. 상세 설계: `docs/설계서/실전모드_불일치_조정.md` 섹션 4.

## D14. 실전 모드 재기동 잔고 동기화

**기준**: 실전 모드 기동 시 증권사 계좌 잔고·보유 종목을 증권사 서버에서 조회하여 메모리 상태를 로드해야 한다. 증권사 서버가 잔고·보유 종목의 SSOT이므로 로컬 재계산이 아닌 조회 로드가 기준이다.

구현 요건:
- 실전 모드 기동 시 증권사 계좌 잔고 조회 API + 보유 종목 조회 API 호출 → `engine_state.positions`·`settlement_engine` 상태 로드.
- 테스트모드는 `build_positions_from_trades("test")`로 trades 기반 포지션 구축 + `settlement_engine.reconcile_with_trades()`로 주문가능금액 대조·복구(S1 참조). 이는 가상 원장이므로 로컬 계산이 SSOT.
- 모드 분기는 돈 I/O 최소 지점에서만(W5/W7). 실전은 조회 로드, 테스트는 trades 기반 계산 — SSOT의 주인이 다를 뿐 동등한 복구 경로.

**현재 상태(W6 투명성)**: 테스트모드 복구 경로만 구현됨(`settlement_engine.reconcile_with_trades()`, `engine_lifecycle.py` 테스트모드 분기). 실전 모드는 `engine_bootstrap.py`에서 `_update_account_memory()`로 증권사 REST 조회(kt00001/kt00018) 후 메모리 반영은 구현되어 있으나, **내부 기록과의 불일치 대조·차단 로직은 없음** (조회 후 그대로 반영만). `engine_lifecycle.py:38` 주석 "증권사 서버가 SSOT이므로 별도 대조 불필요"는 현재 코드 상태를 정확히 반영하지만, P22 "불일치 시 즉시 차단" 요건은 미충족. 조회 실패 시 기존 스냅샷 유지(silent fallback) — W8(P20 폴백 금지) 위반 가능.

**후속 과제(별도 승인 필요)**: 실전 모드 기동 시 증권사 잔고·보유 종목 조회 후 내부 기록과 대조·불일치 차단 로직 구현. 상세 설계: `docs/설계서/실전모드_불일치_조정.md` 섹션 3.

## D15. 단계별 지연 측정 의무화

**기준**: 실시간 데이터 처리의 end-to-end 지연 기준(50ms 경고/200ms 중단)을 유지하며, 병목 구간 식별을 위해 각 처리 단계별 지연 측정을 의무화한다.

구현 요건:
- end-to-end 기준 유지: 틱 수신 시점부터 처리 완료까지 50ms 초과 시 경고, 200ms 초과 시 자동매매 중단(`engine_ws_dispatch._check_realtime_latency()`, S9 참조).
- 단계별 측정 의무화: 아래 4단계 각각의 지연을 측정·로깅하여 병목 구간을 식별 가능하게 할 것.
  1. 틱 수신 → 파싱/라우팅 (`engine_ws_dispatch.py`)
  2. 파싱 → Compute Loop 진입 (`pipeline_compute.py`)
  3. Compute Loop → broadcast_queue 적재
  4. broadcast_queue → WS 전송 완료 (`pipeline_gateway.py`/`ws_manager.py`)
- 단계별 예산 수치는 측정 데이터 축적 후 별도 과제에서 정의(현 시점에서는 측정 의무화만 기준).

**현재 상태(W6 투명성)**: end-to-end 측정만 구현됨(50ms 경고/200ms 중단, `realtime_latency_exceeded` 플래그). 4단계별 개별 측정·로깅은 미구현. Compute Loop·Gateway Loop·WSManager flush에 단계별 지연 측정 로직 없음.

**후속 과제(별도 승인 필요)**: 4단계별 지연 측정 구현 → 측정 데이터 축적 후 단계별 예산 수치 정의.

## D16. 실전 모드 사용자 모르는 주문 금지

**기준**: 실전 모드에서 사용자의 매매 의사와 무관하게 시스템이 자의적으로 실제 주문(실제 돈이 나가는 주문)을 전송하는 것을 금지한다.

적용 범위:
- 매매 전략에 의한 정상 주문(execute_buy/execute_sell 단일 경로, 사용자가 설정한 조건 기반)은 본 기준 대상 아님.
- 본 기준이 금지하는 대상: **안전장치·검증·복구 확인 등 부가 목적의 주문**으로서 사용자 매매 의사와 무관하게 전송되는 실제 주문.
- 테스트모드는 가상 체결(`dry_run.fake_send_order()`)이므로 본 기준 대상 아님.

**근거**: 1인 로컬 자동매매 앱에서 실전 모드의 모든 실주문은 사용자가 설정한 전략·조건의 결과여야 한다. 안전장치 검증·연결 생존 확인 등 부가 목적으로 사용자 모르게 실제 돈을 노출시키는 것은 P21(사용자 투명성) 위반이자 계좌 보호 원칙에 반한다. 부가 목적의 확인은 가상 확인(잔고 조회 등 무비용 요청) 또는 테스트모드 경로로 수행할 것.

**현재 구현 상태(W6 투명성)**:
- D7 OMS 서킷브레이커 HALF_OPEN 복구 판정 주문이 본 기준에 해당하는 잠재 위반 후보. 단, D7은 재검토 예정이므로 본 기준 위반 확정은 D7 재검토 완료 후 판정.
- 그 외 매매 전략 경로(execute_buy/execute_sell)는 사용자 설정 조건 기반이므로 본 기준 준수.

> 2026-07-29 사용자 결정 반영. D7 재검토와 별개로 보편적 원칙으로 명시.

## D17. 런타임 주기적 Reconciliation (실전 모드)

**기준**: 실전 모드 런타임 중, WS 체결 통보 누락·네트워크 장애·재연결 등으로 인해 앱 내부 기록(잔고·보유·체결내역)과 증권사 서버 실제 계좌가 어긋날 수 있으므로, 주기적으로 증권사에 재조회하여 내부 기록과 대조·보정해야 한다. 이게 없으면 불일치가 조용히 영구화되어 매도 누락·잔고 오산·리스크 게이트 오작동으로 이어진다.

구현 요건:
- 실전 모드 런타임 중 일정 간격(예: 장중 1회 또는 이벤트 트리거)으로 증권사 잔고·보유·미체결 재조회 → 내부 `state.positions`·`account_snapshot`과 대조.
- 폴링 금지(P11) — `asyncio` 기반 스케줄링(`daily_time_scheduler` 확장 또는 이벤트 트리거).
- 불일치 시 W4 "불일치 발견 시 즉시 차단" 준수 — `logger.critical` + 관련 파이프라인 중단 + UI 알림(P21).
- 테스트모드는 가상 원장이 SSOT이므로 자기 자신과 대조하는 의미가 없음 → 스킵(W7 동등성 위반 아님: 외부 원장 부재).
- 재연결 후 구독 복원(`engine_ws_reg.restore_subscriptions_after_reconnect`)은 기존 구현됨 — 단, 체결 누락 감지·복구는 본 항목의 범위.

**현재 상태(W6 투명성)**: 미구현. 런타임 중 주기적 증권사 재조회 로직 전혀 없음. 재연결 시 구독 복원만 구현됨(`engine_ws_reg.py`). 체결 통보 누락 감지·주문 타임아웃·누락 복구 로직 없음. `daily_time_scheduler`에 잔고 재조회 스케줄 없음.

**후속 과제(별도 승인 필요)**: 실전 모드 런타임 주기적 reconciliation 스케줄링 + 체결 누락 감지·복구 로직 구현. 상세 설계: `docs/설계서/실전모드_불일치_조정.md` 섹션 2.

---

# L2. 시스템 구조

## S1. 기동·종료 순서

### 기동 순서 (startup)
```
1. configure_app_logging()
2. start_db_writer()           — DB 쓰기 큐 시작
3. init_cache_tables()         — CREATE TABLE IF NOT EXISTS
4. initialize_trading_calendar_cache()  — 거래일 캐시 로드
5. initialize_queues()         — 3개 코어 큐 생성 (tick/broadcast/control)
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

> **기동 시 누락 단계(W10 투명성)**: 위 기동 순서에는 아래 두 단계가 포함되어야 하나 현재 미구현(D13/D14 참조).
> - **실전 모드 미체결 주문 복구(D13)**: 실전 기동 시 증권사 미체결 주문 조회 → 잔여 주문 사용자 표시·처리. 후속 과제.
> - **실전 모드 잔고·보유 종목 로드(D14)**: 실전 기동 시 증권사 계좌 조회 API로 메모리 상태 로드. 후속 과제.
> - 테스트모드는 위 두 단계가 의미 없음(가상 체결·가상 원장). 테스트모드 포지션 구축은 `dry_run._refresh_positions_if_dirty()`로 이미 기동 순서에 포함.

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

## S2. 파이프라인 아키텍처

### 코어 큐 (3개)

```
                    ┌────────────────────────────────────────┐
                    │              Broker WebSocket           │
                    │    (키움/LS 실시간 시세 수신)            │
                    └────────────────┬───────────────────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │   engine_ws_dispatch.py         │
                    │   (시세 파싱 + 라우팅)           │
                    └──┬──────────┬───────────────────┘
                       │          │
                       ▼          ▼
              ┌────────────┐ ┌──────────────────┐
              │ tick_queue │ │ broadcast_queue  │
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
                   ▼                │  (프론트엔드 전송)  │
              ┌────────────┐       └────────────────────┘
              │control_queue│
              │ PriorityQueue│
              └─────────────┘
```

> 큐 크기·드롭 정책 등 구현 세부 수치는 L3 참조표 참조.
> `db_write_queue`는 별도의 DB 쓰기 직렬화 큐(D2). 코어 파이프라인 큐가 아니다.

### Compute Loop (`pipeline_compute.py`)
```python
# 핵심 구조: tick_queue 대기 + control_queue 신호 동시 처리
while _compute_running:
    try:
        # 0.5초 timeout — 틱 없는 시간에도 control 신호 처리
        data = await asyncio.wait_for(tick_queue.get(), timeout=0.5)
    except asyncio.TimeoutError:
        data = None
    # control 신호 처리 (UPDATE_CONFIG, RECOMPUTE_SECTOR, DYNAMIC_REG/UNREG)
    # tick 데이터 처리 → _process_tick_data()
    await asyncio.sleep(0)  # 협력적 양보 (이벤트 루프 고갈 방지)
```

**별도 루프**: `_sector_recompute_loop` — 0.2초 주기 배치 루프, dirty 종목의 업종만 증분 재계산.

### Gateway Loop (`pipeline_gateway.py`)
단일 소비 루프: `_broadcast_loop`가 `broadcast_queue`를 소비 → WebSocket 전송.

## S3. 데이터 흐름

### 실시간 시세 흐름
**WS 구독 대상 (1차 필터 게이트)**:
- 1차 필터(5거래일 평균 거래대금 `sector_min_trade_amt`억원 이상) 통과 종목 + 보유종목만 WS 구독.
- `subscribe_sector_stocks_0b()`가 `_filtered` 플래그 기반으로 구독 대상 선정. 설정 한도 `subscribe.max_0b_count`(기본 200, 보유종목 우선, D8 참조).
- 필터 미통과 종목: WS 구독 안됨 → 01 틱 수신 없음 → 업종 순위 계산 대상 아님 → 아무 처리도 하지 않음.

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

**전송 경로 일관성 (W11)**:
- 01/0B 틱(현재가/등락률/체결강도/거래대금): `broadcast_queue` 경로(전 종목 동일).
- 0D 틱(호가잔량비): `ws_manager.broadcast` 직접 경로(매수 후보만, `_subscribed_dynamic` 플래그).
- PGM 틱(프로그램 순매수): `ws_manager.broadcast` 직접 경로(매수 후보만, `_subscribed_dynamic` 플래그).

### 업종 점수 계산 흐름
별도 백그라운드 루프 — 실시간 시세 전송과 분리:
- Compute Loop 내 `_handle_real_01_tick`에서 `request_sector_recompute(code)`로 dirty 마킹만 수행(O(1) set add).
- 실제 업종 점수 계산은 별도 백그라운드 루프 `_sector_recompute_loop_impl()`에서 수행.
- Phase 1(1회): 실시간데이터 수신율 임계값(`sector_start_threshold_pct`, 기본 70%) 대기 → 통과 후 Phase 2 전환.
- Phase 2: 0.2초 배치 루프 — dirty 종목의 업종만 증분 재계산.

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
    └── 일반 캐시 → 증분 재계산             — dirty 업종만 교체
         │
         ▼
    compute_sector_scores()
         │
         ▼
    calculate_bonus_scores()  — 3단계 누적 가산점
         │
         ▼
    broadcast_queue.put(sector-scores)  — delta 전송
```

### 매수 흐름
```
[장중] auto_buy_effective() 활성화 타이머 (buy_time_start ~ buy_time_end)
    │
    ▼
매수 후보 선정 (업종 순위 + 1차 필터 + 2차 필터)
    │
    ▼
execute_buy() (단일 경로, W5)
    ├── RiskManager 사전 체크 (잔액, 일일 손실, 단일 종목 비중, 서킷브레이커)
    ├── CircuitBreaker.allow_request() 사전 체크
    ├── 주문 전송 (테스트: dry_run.fake_send_order / 실전: router.order.send_order)
    ├── CircuitBreaker.record_success()/record_failure() 사후 기록
    └── 체결 시: positions 갱신 + trade_history 기록 + broadcast
```

### 매도 흐름
```
[장중] auto_sell_effective() 활성화 타이머 (sell_time_start ~ sell_time_end)
    │
    ▼
보유 종목 자동매도 조건 체크 (매 틱마다)
    ├── 익절: pnl_rate >= tp_val
    ├── 손절: pnl_rate <= loss_val (둘 다 음수, 부록 B.2)
    ├── T/S(Trailing Stop): 추적 고점 대비 하락률 <= ts_drop_val
    └── 실시간 지연 200ms 초과 시 매도 조건 전체 차단
    │
    ▼
execute_sell() (단일 경로, W5)
    ├── RiskManager 사전 체크
    ├── CircuitBreaker.allow_request() 사전 체크
    ├── 주문 전송
    ├── CircuitBreaker.record_success()/record_failure() 사후 기록
    └── 체결 시: positions 갱신 + trade_history 기록 + broadcast
```

## S4. 장마감 파이프라인

```
20:00 _on_ws_subscribe_end() (NXT 장마감 진입 시 자동 트리거)
  ├── 실시간 구독 전체 해제
  └── WS 연결 해제
20:40 _fire_unified_confirmed_fetch() (timetable.confirmed_download 설정, 기본값)
  ├── 확정 시세 다운로드 (전 종목)
  ├── 5거래일 일봉 다운로드 (전 종목)
  ├── 1차 필터 갱신 (5거래일 평균 거래대금 기준)
  └── 업종 재계산 트리거
```

## S5. 시간 스케줄러 (`daily_time_scheduler.py`)

`asyncio.call_later()` 기반 — 매일 재스케줄링.

```
07:58  _on_realtime_fields_reset()  — 실시간 필드 초기화 + 캐시 초기화
07:59  WS 구독 구간 진입             — 상태 전환 + 엔진 루프 통지 (사전 구독, NXT 프리마켓 1분 전)
08:00  NXT 프리마켓 진입             — 업종 재계산 (이미 구독됨)
08:59  _on_krx_pre_subscribe()      — KRX 단독 종목 사전 구독 (정규장 1분 전)
09:00  KRX 정규장 진입              — 업종 재계산 (구독은 08:59 사전 구독에서 담당)
15:20  _on_krx_closing_auction_start() — KRX 단독 종목 구독 해지 (종가 동시호가 진입)
20:00  _on_ws_subscribe_end()       — WS 구독 종료 (NXT 장마감 진입 시 자동 트리거)
20:40  _fire_unified_confirmed_fetch() — 확정 시세 + 5거래일 일봉 다운로드
00:00  _on_midnight()               — 일일 리셋 (거래일 판단, 타이머 재예약)
```

자동매매 타이머:
```
buy_time_start  — auto_buy_effective() 활성화
buy_time_end    — auto_buy_effective() 비활성화
sell_time_start — auto_sell_effective() 활성화
sell_time_end   — auto_sell_effective() 비활성화
```

WS 연결 제어 (자의적 판정 제거 — 2026-08-06):
- 엔진 기동 시 `access_token` 있으면 즉시 `ConnectorManager` 생성 + WS 연결.
- 엔진 루프는 `engine_stop_event` 대기만 수행 (중간 재판정 루프 제거).
- 장마감(20:00) `_on_ws_subscribe_end()`가 `connector_manager.disconnect_all()` 직접 수행.
- 시간대로 연결을 차단하는 자의적 판정은 제거됨. 증권사 서버가 24시간 연결을 허용하므로 앱이 시계로 판단하지 않음.
- `is_nxt_only_window()`는 "KRX 단독 종목 제외" 용도(업종 점수 계산)로만 유지.

## S6. 상태 관리 (SSOT)

### EngineState (메모리 상주, `engine_state.py` — 싱글톤)
```python
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
    engine_stop_event
    data_ready_event, token_ready_event
    bootstrap_event, sector_summary_ready_event
    engine_ready_event, server_ready_event

    # 스케줄러 상태
    ws_subscribe_window_active: bool | None
    auto_trade_timer_handles: list
    midnight_timer_handle

    # 실시간 상태
    realtime_latency_exceeded: bool          — 200ms 초과 시 자동매매 중단
    market_phase: dict                       — KRX/NXT 장 단계
    krx_circuit_breaker_active: bool         — KRX 서킷브레이커/사이드카
```

### 설정 계층
```
SQLite (integrated_system_settings 테이블)
    │
    ▼ load_integrated_system_settings()
state.integrated_system_settings_cache (메모리 SSOT)
    │
    ├── 모든 모듈이 이 캐시를 직접 참조
    ├── 설정 변경 시: settings.py → DB 저장 → 캐시 갱신 → apply_settings_change()
    └── apply_settings_change() → 타이머 재예약 / 업종 재계산 / WS 구간 재판정
```

## S7. 증권사 연결 계층

### Broker Router 패턴
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

### ConnectorManager (다중 증권사 WS)
```
ConnectorManager
├── _connectors: dict[str, BrokerConnector]
│   ├── kiwoom_connector.py  — 키움증권 WS
│   └── ls_connector.py      — LS증권 WS
├── connect_all()             — 모든 증권사 WS 연결
├── disconnect_all()          — 모든 WS 해제
├── is_connected()            — 연결 상태 확인
├── set_message_callback()    — 시세 수신 콜밭
└── get_connector(broker_id)  — 특정 증권사 커넥터
```

### 지원 증권사
| 증권사 | WS 시세 | REST 주문 | REST 계좌 | TR 스펙 |
|--------|---------|-----------|-----------|---------|
| 키움증권 | kiwoom_connector | kiwoom_order | kiwoom_rest | broker_specs DB |
| LS증권 | ls_connector | ls_rest | ls_rest | broker_specs DB |

## S8. WebSocket 통신 계층

### WSManager (프론트엔드 ↔ 백엔드, 싱글톤)
```
WSManager
├── _clients: set[WebSocket]           — 연결된 클라이언트
├── _client_active_page: dict          — per-client 활성 페이지
├── _client_subscribed_fids: dict      — per-client 구독 FID
├── _state_queue: dict                 — 상태형 (최신값만 유지)
├── _event_queue: list                 — 이벤트형 (순서 보장)
└── _flush_task                         — 0.1초 주기 배치 전송
```

**전송 방식**:
| 타입 | 방식 | 특징 |
|------|------|------|
| `real-data` | 즉시 전송 | FID 필터 + zlib 압축, per-client 페이지 필터링 |
| 상태형 이벤트 | 최신값 유지 | `(event_type, code)` 키로 최신값 덮어쓰기 |
| 이벤트형 | 순서 보장 | `_event_queue`에 순차 누적 |
| 페이지별 | 타겟 전송 | 활성 페이지 클라이언트에게만 전송 |

**Graceful Shutdown (D6)**: WS 클라이언트(브라우저)가 모두 닫혀도 백엔드는 계속 실행.

### 주요 이벤트
| 이벤트 | 타입 | 설명 |
|--------|------|------|
| `real-data` | 즉시 | 실시간 시세 (FID 압축) |
| `sector-scores` | 상태형 | 업종 점수 (delta 전송) |
| `buy-targets-update` | 이벤트형 | 매수 타겟 변경 |
| `account-update` | 상태형 | 계좌 정보 |
| `engine-status` | 상태형 | 엔진 상태 |
| `market-phase` | 이벤트형 | 장 단계 (개장/장중/장마감 etc.) |
| `circuit-breaker-open` | 이벤트형 | 서킷 브레이커 알림 |
| `krx-circuit-breaker` | 이벤트형 | KRX 서킷브레이커/사이드카 알림 |
| `risk-block-status` | 이벤트형 | 리스크 매니저 매수/매도 차단 알림 (헤더 빨간 칩) |
| `engine-ready` | 이벤트형 | 엔진 준비 완료 |
| `buy-history-append` | 이벤트형 | 매수 체결 단건 |
| `sell-history-append` | 이벤트형 | 매도 체결 단건 + 일자 요약 |

## S9. 안전장치 요약

| 계층 | 장치 | 임계치 | 동작 | 근거 |
|------|------|--------|------|------|
| 실시간 지연 | `_check_realtime_latency()` | 200ms 초과 | 자동매매 중단 플래그 | 200ms 초과 시 데이터 왜곡 위험 |
| 실시간 지연 | 경고 | 50ms 초과 | 로그 경고 | 50ms 초과 시 지연 징후 |
| 주문 실패 | CircuitBreaker | 5회 연속 | OPEN → 주문 거부 | 계좌 보호 |
| 주문 복구 | CircuitBreaker | 60초 경과 | HALF_OPEN → 복구 판정 주문 1건 허용 (D7, 재검토 예정) | 무한 차단 방지 |
| 일일 손실 | RiskManager | `daily_loss_limit`(음수, 기본 -500,000원) | 매수 차단 | 손실 확대 방지 |
| 일일 손실률 | RiskManager | `daily_loss_rate_limit`(음수) | 매수 차단 | 손실 확대 방지 |
| 예수금 | RiskManager | 주문액 > 잔액 | 매수 차단 | 잔고 부족 주문 방지 |
| 단일 종목 비중 | RiskManager | `single_stock_limit_pct` | 매수 차단 | 분산 효과 유지 |
| 종목 하락률 | RiskManager | `buy_block_fall_pct`(음수) | 매수 차단 | 급락종목 매수 방지 |
| 종목 상승률 | RiskManager | `buy_block_rise_pct`(양수) | 매수 차단 | 급등종목 추격 매수 방지 |
| 틱 폭주 | tick_queue 드롭 | 큐 가득 시 | 가장 오래된 데이터 버림 | W1 (처리 속도 > 수신 속도) |
| 이벤트 루프 | `asyncio.sleep(0)` | 매 틱 | 협력적 양보 | 이벤트 루프 고갈 방지 |
| KRX 서킷브레이커 | `krx_circuit_breaker_active` | KRX 서킷브레이커/사이드카 발동 | 자동매매 차단 | 시장 전체 정지 대응 |

> 단일 종목 비중 한도는 구현 완료 상태이며 매수 차단 경로에서 작동 중(`risk_manager.py`).
> 틱 드롭 수치(큐 크기)는 L3 참조표 참조.
> 실시간 지연 측정은 현재 end-to-end만 구현됨. 단계별 측정 의무화 기준은 D15 참조.

## S10. DB 스키마 주요 테이블

| 테이블 | 용도 |
|--------|------|
| `master_stocks_table` | 전 종목 기본 정보 (단일 소스) |
| `trades` | 체결 이력 (매수/매도) |
| `trading_days_cache` | 거래일 캐시 (연 1회 갱신) |
| `sectors` | 업종 정의 (커스텀 업종명) |
| `integrated_system_settings` | 통합 설정 (단일 행 SSOT) |
| `broker_specs` | 증권사 TR 스펙 (role_mappings) |
| `journal` | 주문 저널 (요청/체결/취소 추적) |

## S11. 프론트엔드 구조

- `frontend/src/stores/store.ts` — 전역 상태(Record 기반, 메인 SSOT).
- `frontend/src/stores/uiStore.ts` — UI 상태.
- `frontend/src/binding.ts` — WS 이벤트 → Store 액션 바인딩.
- `frontend/src/router.ts` — 프론트엔드 라우터.
- `frontend/src/components/common/` — 공통 컴포넌트(W11 재사용 1순위).
- `frontend/src/pages/` — 페이지 진입점.

---

# L3. 수치 참조표

> 구현 세부 수치의 주인은 코드 상수다. 본 표는 위치만 참조한다.
> 값이 변경되어도 본 표는 갱신하지 않는다(위치가 바뀔 때만 갱신).
> 전략·안전 수치(값 + 근거 명시 필요)는 L1·L2에 직접 기재한다.

## 큐·배치

| 항목 | 코드 위치 |
|------|----------|
| tick_queue 크기 | `backend/app/services/core_queue.py:TICK_QUEUE_MAXSIZE` |
| broadcast_queue 크기 | `backend/app/services/core_queue.py:BROADCAST_QUEUE_MAXSIZE` |
| control_queue 크기 | `backend/app/services/core_queue.py:CONTROL_QUEUE_MAXSIZE` |
| db_write_queue 크기 | `backend/app/db/db_writer.py:_DB_WRITE_QUEUE_MAXSIZE` |
| notification queue 크기 | `backend/app/services/notification_worker.py:_QUEUE_MAXSIZE` |
| file log queue 크기 | `backend/app/core/logger.py` (`_file_queue = asyncio.Queue(maxsize=50_000)`) |
| Compute Loop tick 대기 timeout | `backend/app/pipelines/pipeline_compute.py` (`asyncio.wait_for(tick_queue.get(), timeout=0.5)`) |
| 업종 재계산 배치 주기 | `backend/app/pipelines/pipeline_compute.py` (`asyncio.sleep(0.2)`) |
| WSManager flush 주기 | `backend/app/web/...` (`_flush_task` 0.1초 주기) |
| 수신율 갱신 디바운스 | `backend/app/pipelines/pipeline_compute.py` (`asyncio.sleep(0.2)`) |
| fake_fill 지연 | `backend/app/services/dry_run.py:FAKE_FILL_DELAY` |
| 알림 쿨다운 | `backend/app/web/app.py:ALERT_COOLDOWN_SECONDS` |

## 안전장치

| 항목 | 코드 위치 | 비고 |
|------|----------|------|
| CircuitBreaker 실패 임계치 | `backend/app/services/circuit_breaker.py:CircuitBreaker.__init__(failure_threshold=5)` | 기본값 5 |
| CircuitBreaker 복구 timeout | `backend/app/services/circuit_breaker.py:CircuitBreaker.__init__(recovery_timeout=60)` | 기본값 60초 |
| 실시간 지연 경고/중단 임계치 | `backend/app/services/engine_ws_dispatch.py:_check_realtime_latency()` | 50ms 경고 / 200ms 중단 (L2 S9에 근거 명시) |
| 일일 손실 한도 기본값 | `backend/app/core/settings_defaults.py:DEFAULT_USER_SETTINGS` | `daily_loss_limit`(음수) |
| 일일 손실률 한도 기본값 | `backend/app/core/settings_defaults.py:DEFAULT_USER_SETTINGS` | `daily_loss_rate_limit`(음수) |
| 단일 종목 비중 한도 | `backend/app/core/settings_defaults.py:DEFAULT_USER_SETTINGS` | `single_stock_limit_pct` |
| 종목 하락률 매수차단 | `backend/app/core/settings_defaults.py:DEFAULT_USER_SETTINGS` | `buy_block_fall_pct`(음수) |
| 종목 상승률 매수차단 | `backend/app/core/settings_defaults.py:DEFAULT_USER_SETTINGS` | `buy_block_rise_pct`(양수) |
| 수신율 임계값 | `backend/app/core/settings_defaults.py:DEFAULT_USER_SETTINGS` | `sector_start_threshold_pct`(기본 70.0) |

## 구독·필터

| 항목 | 코드 위치 | 비고 |
|------|----------|------|
| WS 구독 종목 한도 기본값 | `backend/app/core/settings_defaults.py` (`subscribe.max_0b_count`, 기본 200) | D8: 키움증권 세션 한도 기준 |
| 1차 필터 키 (SSOT) | `backend/app/core/settings_defaults.py:DEFAULT_USER_SETTINGS` (`sector_min_trade_amt`) | 함수 인자명 `min_avg_amt_eok`는 별개 |

## 시간 스케줄

| 항목 | 코드 위치 |
|------|----------|
| WS 사전 구독 시작 시각 | `backend/app/services/daily_time_scheduler.py:WS_SUBSCRIBE_PRESTART_TIME` (07:59) |
| NXT 프리마켓 시작 시각 | `backend/app/services/daily_time_scheduler.py:NXT_PREMARKET_START` (08:00) |
| 확정 시세 다운로드 시각 | `settings.timetable.confirmed_download` (기본 20:40) |
| 자동매수/매도 타이머 | `settings.buy_time_start/end`, `settings.sell_time_start/end` |

---

# 부록

## A. 원칙 매핑표 (기존 25개 → W1~W12)

> 통합 근거: P10/P22/P23/P24가 "중복 제거"를 서로 교차 강화하며 같은 말을 반복 → 에이전트 규칙 충돌 판단 비용과 문서 유지비용의 근본 원인. 내용 손실 없이 교차 중복 제거.

| 새 원칙 | 통합된 기존 원칙 | 핵심 주제 |
|---------|----------------|-----------|
| W1 단일 루프·논블로킹 | P1, P2, P3, P7, P14 + 금지 패턴 1·2·4 | 단일 루프, async I/O, 블로킹 금지 |
| W2 파이프라인 분리 | P8, P9 | 실시간/배치 분리, 상호 간섭 금지 |
| W3 SSOT | P10, P12, P13, P17 | 단일 소스, DB 싱글톤, 설정 메모리 상주, 플래그 단일 소스 |
| W4 단계 간 정합성 | P22 | 파이프라인 단계 간 일관성 |
| W5 단일 주문 경로 | P15 | 주문 경로 단일화 |
| W6 살아있는 안전장치 | P16 + 금지 패턴 5 | 살아있는 경로 배선, dead code 금지 |
| W7 테스트모드 동등성 | P18 | 모드 동등성, 외부 원장만 대체 |
| W8 폴백 금지 | P20 + 금지 패턴 3 | 폴백 금지, silent except 금지 |
| W9 격리된 실패 | P25 | 구성요소 실패 격리 |
| W10 사용자 투명성 | P21 | 사용자 모르는 의사결정 금지, UI 표시 의무 |
| W11 표현 통일 | P23 | 용어·네이밍·패턴 통일 |
| W12 중복·과잉 추상화 금지 | P24 | 중복 제거, 단순성 |

**L2로 이동된 구조 선택 원칙** (불변 원칙에서 제외, 설계 결정으로 재분류):

| 기존 원칙 | L2 위치 | 주제 |
|----------|---------|------|
| P4 | D3 | 증권사 이름 공통 기능 침투 금지 |
| P5 | D1 | EventBus 미사용 |
| P6 | D2 | SQLite 단일화 |
| P11 | D4 | 이벤트 기반 루프 (폴링 금지) |
| P19 | D5 | 런타임 검증 게이트 |

## B. 표준 용어 사전 (W11 준수)

> 같은 의미를 가리키는 단어가 코드/화면/로그/문서에서 혼용되는 것을 금지.
> 아래 표준 용어만 사용. 금지 용어는 신규 코드/로그/문서에 사용 금지.
> 기존 코드의 금지 용어는 점검 세션에서 순차적 표준 용어로 교체.

| 표준 용어 | 금지 용어 | 적용 범위 | 비고 |
|-----------|-----------|-----------|------|
| 업종 | 섹터 | 코드/화면/로그/문서 전 영역 | 도메인 용어 통일. 단, 파일명/클래스명의 `sector`는 코드 식별자로 허용 (예: `sector_calculator.py`) |
| 종목 | 주식 | 코드/화면/로그/문서 전 영역 | 도메인 용어 통일. 단, 파일명/클래스명의 `stock`은 코드 식별자로 허용 (예: `stock_filter.py`) |
| 매수 | Buy, 구매 | 화면/로그/문서 | 거래 용어 통일. 단, 코드 식별자의 `buy`/`execute_buy`는 허용 |
| 매도 | Sell, 판매 | 화면/로그/문서 | 거래 용어 통일. 단, 코드 식별자의 `sell`/`execute_sell`은 허용 |
| 매수체결 | 매수인지 매도인지 구분이 필요한 자리에서의 단독 "체결" | 화면/로그/문서 | 매수 한 건을 가리킬 때는 "매수체결"로 정확히 표기. 단, 매수+매도 통칭("체결 이력")·시장 지표("체결강도")·공통 차단("체결 불가 시간대")은 단독 "체결" 허용 |
| 매도체결 | 매도인지 매수인지 구분이 필요한 자리에서의 단독 "체결" | 화면/로그/문서 | 매도 한 건을 가리킬 때는 "매도체결"로 정확히 표기. 단, 통칭·시장 지표·공통 차단은 단독 "체결" 허용 (매수체결 행 참조) |
| 매수 후보 | 바이 리스트, 매수 타겟 | 화면/로그/문서 | UI 표시명 통일 |
| 보유 종목 | 홀딩, 포지션 | 화면/로그 | UI 표시명 통일. 단, 코드 식별자의 `position`/`holdings`는 허용 |
| 증권사 표시명 | 코드 식별자 (화면/로그 한정) | 화면/로그 | "LS증권", "키움증권" 등 사전 정한 표시명 사용. 단, 코드 내부 식별자(`ls_`, `kiwoom_`)는 D3에 따라 유지 |
| 일봉 | 1일봉, 1일봉차트, 1일봉챠트 | 화면/로그/문서 | "일봉" 자체가 하루 단위 봉을 뜻하므로 "1" 중복. "챠트"는 외래어 표기법 위반(국립국어원: chart → 차트). 단, 코드 식별자(`daily_confirmed`, `fetch_all_stocks_daily_confirmed`)는 허용 |
| 5거래일 일봉 | 5일봉, 5일봉차트, 5일봉챠트 | 화면/로그/문서 | "5일봉"은 "5일선"(이동평균선)과 혼동 위험. "최근 5거래일치 일봉 데이터"가 정확한 의미. 단, 코드 식별자(`fetch_stock_5day_data`, `stock_5d_bars`)는 허용 |
| 5거래일 평균 거래대금 | 5일 평균 거래대금, 5일평균거래대금, 5일평균 | 화면/로그/문서 | 주말·공휴일 제외 5영업일 명시. 단, 코드 식별자(`avg_amt_5d`, `avg_5d_trade_amount`)는 허용 |
| 5거래일 고가 | 5일 고가, 5일고가, 5일 전고가, 5일 전고점 | 화면/로그/문서 | "5일선의 고가" 오해 방지. 단, 코드 식별자(`high_5d`, `high_5d_price`, `get_high_price_5d_cache`)는 허용 |
| 5거래일 손익 | 5일 손익 | 화면/로그/문서 | 수익 상세 요약 카드 표시명 통일. 단, 코드 식별자(`fivedayPnlEl`, `fivedayCard`)는 허용 |
| 차트 | 챠트 | 화면/로그/문서 | 국립국어원 외래어 표기법: chart → 차트 (ㅊ 다음 이중모음 ㅑ 금지) |

> **코드 식별자 예외**: 파일명, 클래스명, 함수명, 변수명에 포함된 영어 식별자(`sector`, `stock`, `buy`, `sell`, `position`, `5d`, `fiveday`)는 코드 가독성과 관행상 허용. W11의 용어 통일은 **사용자에게 보이는 화면 텍스트, 로그 메시지, 문서 설명**에 적용.
> **확장**: 신규 용어 혼용 발견 시 이 사전에 추가하여 합의 후 적용.

### B.2 후안 B 부호 규칙 (의미 기반 부호 규약)

> 하락/손실은 **음수**, 상승/이익은 **양수**로 통일 (W11 일관성).
> 부호가 의미를 직관적으로 표현하도록 절댓값 양수 표기 대신 의미 기반 부호 사용.
> 검증은 `_RISK_FLOAT_KEYS`(`backend/app/core/settings_store.py`)가 저장 시 부호 위반을 차단 (W8/W4).

| 설정 키 | 부호 | 범위 | 의미 | 비교 로직 |
|---------|------|------|------|-----------|
| `daily_loss_rate_limit` | 음수 | -100~0 | 일일 손실률 한도 | pnl_rate <= daily_loss_rate_limit 시 매수 차단 |
| `daily_loss_limit` | 음수 | -10억~0 | 일일 손실액 한도 | daily_pnl <= daily_loss_limit 시 매수 차단 |
| `loss_val` | 음수 | -100~0 | 손절 하락률 | pnl_rate <= loss_val 시 손절 매도 (둘 다 음수) |
| `ts_drop_val` | 음수 | -100~0 | 추적 고점대비 하락률 | drop_rate <= ts_drop_val 시 T/S 매도 (둘 다 음수) |
| `buy_block_fall_pct` | 음수 | -100~0 | 종목 하락률 매수차단 | change_rate <= buy_block_fall_pct 시 매수 차단 |
| `tp_val` | 양수 | 0~100 | 익절 상승률 | pnl_rate >= tp_val 시 익절 매도 |
| `ts_start_val` | 양수 | 0~100 | 추적 시작 상승률 | pnl_rate >= ts_start_val 시 T/S 추적 시작 |
| `buy_block_rise_pct` | 양수 | 0~100 | 종목 상승률 매수차단 | change_rate >= buy_block_rise_pct 시 매수 차단 |

> **마이그레이션**: 기존 양수(절댓값) 표기에서 음수 표기로 전환 시 `settings_file.py`의 idempotent 마이그레이션 함수가 런타임 기동 시 자동 변환 (`_migrate_loss_val_to_negative`, `_migrate_ts_drop_val_to_negative` 등).
> **확장**: 신규 하락/손실 관련 설정 키 추가 시 음수 규약 적용 후 이 표에 추가.

## C. SQLite Pragmas (D2)

```python
PRAGMA journal_mode = WAL          — Write-Ahead Logging 모드
PRAGMA synchronous = NORMAL        — 디스크 쓰기 속도 가속화
PRAGMA cache_size = -64000         — 64MB 캐시
PRAGMA temp_store = MEMORY         — 임시 테이블 메모리 보관
PRAGMA mmap_size = 268435456       — 256MB 메모리 매핑
```

**효과**: 읽기와 쓰기의 병행성을 개선하여 일반적인 쓰기 작업이 실시간 읽기를 불필요하게 막는 상황을 줄임. 단일 쓰기 제약, checkpoint, 디스크 지연, 잠금 경합에 따른 지연 가능성은 남아 있음.

## D. 증권사 특이사항

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

## E. 로깅 레벨

- **DEBUG**: 개발 중 상세 정보
- **INFO**: 일반적인 작동 정보
- **WARNING**: 예상치 못한 문제 (시스템 계속 작동)
- **ERROR**: 심각한 문제 (일부 기능 중단)
- **CRITICAL**: 치명적 문제 (시스템 중단)

## F. TR 참조

증권사 TR(Transaction Request) 스펙은 `backend/data/broker_specs/` 디렉토리에 JSON 형식으로 저장.

- `role_mappings`: TR ID ↔ 역할 매핑.
- 증권사별 TR 포맷 정의.

---

# 최종 권고

SectorFlow 아키텍처는 1인 로컬 실시간 자동매매 앱의 사용자 수와 운영 범위에 맞춰 구성 복잡성을 낮추고 주문·정산 안전성을 우선한 구조다.

이 문서는 영구적인 최적성을 주장하지 않으며, 실제 사용량·장애 기록·측정 결과에 따라 구조를 재검토한다. 구조를 바꾸려면 본 문서부터 수정한 뒤 코드를 따른다.

### 핵심 요약

- 단일 asyncio 루프와 메모리 캐시는 현재 로컬 환경에서 호출 흐름과 상태를 직접 추적하기 쉽다.
- SQLite와 Raw SQL은 현재 데이터 규모와 운영 방식에 적합하다.
- 모든 안전장치는 살아있는 실행 경로에 배선된다(W6).
- 테스트모드와 실전모드는 동일한 전략·리스크·주문 상태 전이를 공유한다(W7).
- 사용자에게 보이는 모든 중요 상태는 UI에 투명하게 표시된다(W10).
