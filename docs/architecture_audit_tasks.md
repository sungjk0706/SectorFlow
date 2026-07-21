# SectorFlow 아키텍처 위반 전수 조사 태스크 파일

> 작성일: 2026-07-18
> 기준 문서: `ARCHITECTURE.md` (불변 원칙 24개) + `docs/architecture_audit_plan.md` (세션 분할 계획)
> 목적: `architecture_audit_plan.md`의 30세션 계획을 실행 가능한 체크리스트 태스크로 전개. 각 세션별 조사·수정·검증 단계를 추적 가능한 단위로 분해.
> 대상: 백엔드 Python 107파일 + 프론트엔드 TypeScript 57파일 + 테스트 67파일 = 총 231파일

---

## 0. 사용 방법

- 본 파일은 `architecture_audit_plan.md`의 실행 추적용 보조 파일. 원칙 정의·세션 분할 논리·과거 해결 이력은 plan 본문을 참조.
- 각 세션은 **조사 → (사용자 승인 후) 수정 → 검증** 3단계로 진행 (AGENTS.md 규칙 0, 0-1, 0-2 준수).
- 세션당 1단계 원칙 (AGENTS.md 규칙 0-1): 한 세션에서 여러 세션을 연속 진행 금지.
- 발견된 위반 사항은 `architecture_audit_plan.md` 섹션 7 "발견된 문제 기록"에 ID 부여 후 기록 (예: `B10-01`).
- 세션 완료 시 `architecture_audit_plan.md` 섹션 8 "점검 진행 현황 요약"과 본 파일의 상태 표를 함께 갱신.
- 줄 수는 2026-07-18 기준 실측값 (plan의 추정치와 다를 수 있음).

---

## 1. 24개 불변 원칙 빠른 참조

> 각 세션 체크리스트에서 P1~P24 번호로 참조. 상세 정의는 `ARCHITECTURE.md` 제1부 및 `architecture_audit_plan.md` 섹션 2.

| 번호 | 원칙명 | 1줄 점검 포인트 |
|------|--------|-----------------|
| P1 | 단일 asyncio 루프 | `asyncio.run()` 신규 루프 금지 |
| P2 | 모든 I/O async | 동기 `requests`/`sqlite3`/`time.sleep`/`threading.Lock` 금지 |
| P3 | run_in_executor 우회 금지 | `loop.run_in_executor()` 존재 여부 |
| P4 | 증권사명 공통 침투 금지 | 공통 로직에 `kiwoom_`/`ls_` 접두사 금지 |
| P5 | EventBus/발행구독 금지 | 콜백 리스트 옵서버, fire-and-forget `create_task` 금지 |
| P6 | SQLite 단일화 | ORM/PostgreSQL 금지, Raw SQL |
| P7 | 블로킹 금지 | per-tick O(n), 매 틱 DB 조회/전체 순회 금지 |
| P8 | 실시간/배치 분리 | `tick_queue` vs `market_close_pipeline` 물리 분리 |
| P9 | 파이프라인 독립성 | 배치 중 실시간 틱 차단 금지, `db_write_queue` 직렬화 |
| P10 | SSOT | 같은 데이터 다중 관리 금지, 캐시 직접 참조 |
| P11 | 이벤트 기반 | `while + sleep` 폴링 금지, `asyncio.Queue`/`call_later` |
| P12 | DB 연결 싱글톤 | 매 요청 `connect()` 금지, `_db_connection` 공유 |
| P13 | 설정 메모리 상주 | 틱 연산 단계 DB 설정 조회 금지 |
| P14 | 멀티스레드 금지 | `threading.Thread()` 신규 생성, 무분별 `create_task` 금지 |
| P15 | 단일 주문 경로 | `execute_buy()`/`execute_sell()` 단일 경로 |
| P16 | 살아있는 경로 | 호출되지 않는 안전코드/dead code 금지 |
| P17 | 플래그 단일 소스 | `auto_buy_on` 등 다중 수정 금지 |
| P18 | 테스트모드 동등성 | 모드 분기는 돈 I/O 최소 지점만 |
| P19 | 런타임 검증 | `RuntimeWarning(coroutine never awaited)` 검출 |
| P20 | 폴백 금지 | 빈 문자열/None 폴백, silent `except: pass` 금지 |
| P21 | 사용자 투명성 | 백엔드 상태 UI 표시 의무 |
| P22 | 데이터 정합성 | 파생 데이터 모델, 기동 시 대조, 불일치 시 차단 |
| P23 | 일관성 | 용어("업종"/"종목"), 에러/비동기/네이밍/상수 일관, 공통 컴포넌트 추출 |
| P24 | 단순성 | 함수 50줄·파일 500줄·복잡도 10, 불필요한 추상화 금지 |

---

## 2. 전체 세션 진행 현황

> 상태: ☑ 완료 / ☐ 미시작 / ◐ 진행중

| 세션 | 우선순위 | 내용 | 파일 수 | 상태 | 비고 |
|------|----------|------|---------|------|------|
| B-01 | P0 | 주문 실행 경로 | 2 | ☑ | 8건 수정 |
| B-02 | P0 | 리스크 관리 및 서킷 브레이커 | 2 | ☑ | 3건 수정 |
| B-03 | P0 | Dry Run | 1 | ☑ | 3건 수정 |
| B-04 | P0 | 정산 엔진 및 거래 이력 | 2 | ☑ | 4건 수정 |
| B-05 | P0 | 자동매매 유효성 및 코어 큐 | 2 | ☑ | 6건 수정 |
| B-06 | P1 | 엔진 루프 및 생명주기 | 3 | ☑ | 4건 수정 |
| B-07 | P1 | WS 시세 처리 | 5 | ☑ | 7건 수정 |
| B-08 | P1 | 엔진 부트스트랩/캐시/스냅샷 | 5 | ☑ | 14건 수정 |
| B-09 | P1 | 엔진 섹터 확인/전략/레이더 | 5 | ☑ | 24건 수정 |
| **B-10** | **P1** | **엔진 계좌/서비스** | 4 | ◐ | **B-10-a 완료 (11건 수정), B-10-b 대기 (6건)** |
| **B-11** | **P1** | **파이프라인 (Compute/Gateway)** | 2 | ◐ | **B-11-a 완료 (8건 수정), B-11-b 대기 (4건)** |
| B-12 | P2 | DB 계층 | 4 | ☑ | 9건 수정 |
| B-13 | P2 | 설정 관리 | 5 | ☐ | |
| B-14 | P2 | Broker 추상화 (공통) | 7 | ◐ | B-14-a 완료 (6건 수정), B-14-b 대기 (2건 P20/P21 폴백) |
| B-15 | P2 | 증권사 구현: 키움 | 5 | ☐ | 분할 권장 |
| B-16 | P2 | 증권사 구현: LS | 3 | ☐ | 분할 권장 |
| B-17 | P2 | Domain 계층 | 6 | ☐ | |
| B-18 | P2 | 스케줄러 및 장마감 파이프라인 | 3 | ☐ | 분할 권장 (초대형 2개) |
| B-19 | P2 | WS 구독 제어 및 업종 데이터 | 2 | ☐ | |
| B-20 | P3 | 알림 (Telegram) | 3 | ☐ | |
| B-21 | P3 | 기타 Core 유틸 | 11 | ☐ | |
| B-22 | P3 | Web API 계층 | 14 | ☐ | |
| B-23 | P3 | 테스트 품질 점검 | 67 | ☐ | |
| F-01 | P0 | 통신 계층 및 상태 관리 | 8 | ☑ | 10건 수정 |
| **F-02** | **P1** | **진입점, 라우팅, 레이아웃** | 6 | ☐ | |
| F-03 | P2 | 핵심 매매 페이지 | 6 | ☐ | |
| F-04 | P2 | 설정 페이지 | 5 | ☐ | 분할 권장 |
| F-05 | P3 | 수익 페이지 | 3 | ☐ | |
| F-06 | P3 | 공통 컴포넌트 | 25 | ☐ | 분할 권장 |
| F-07 | P3 | 타입 및 유틸 | 5 | ☐ | |

**진행률**: 10/30 세션 완료 (33%). B-10-a 완료 (11건 수정), B-10-b 대기 (6건). B-11-a 완료 (8건 수정), B-11-b 대기 (4건). 잔여 19세션.

---

## 3. 세션별 실행 태스크 (잔여 20세션)

> 각 세션은 아래 4블록으로 구성:
> 1. **대상 파일** (실측 줄 수)
> 2. **대상 원칙**
> 3. **조사 체크리스트** (세션 착수 시 순차 점검)
> 4. **검증 단계** (수정 후 수행)

---

### 세션 B-10: P1 — 엔진 계좌/서비스

**대상 파일** (4개, 총 1733줄)
- [x] `backend/app/services/engine_account_notify.py` (412줄, B-10-b 분할 완료)
- [x] `backend/app/services/engine_account.py` (473줄, B-10-b 분할 완료)
- [x] `backend/app/services/engine_account_rest.py` (176줄, B-10-b 파싱 함수 이동 완료)
- [x] `backend/app/services/engine_service.py` (249줄, B-10-b 분할 완료)
- [x] `backend/app/core/kiwoom_account_parsing.py` (244줄, B-10-b 신규 — 키움 파싱 단일 진실 소스)
- [x] `backend/app/services/engine_account_broadcast.py` (124줄, B-10-b 신규 — account-update 브로드캐스트 분리)

**대상 원칙**: P2, P4, P5, P10, P13, P16, P19, P20, P21, P23, P24

**조사 체크리스트** (2026-07-21 조사 완료)
- [x] P2: 모든 I/O `async def` (동기 `requests`/`sqlite3`/`time.sleep`/`threading.Lock` 없음) — 준수
- [x] P4: 증권사명 (`kiwoom_`/`ls_`)이 공통 계좌 로직에 침투하지 않음 — **해결 B10-01** (키움 파싱 5함수 `kiwoom_account_parsing.py`로 이동)
- [x] P5: 직접 호출 체인 (콜백 리스트 옵서버, fire-and-forget `create_task` 없음) — 준수
- [ ] P10: 계좌 상태 SSOT (한 플래그/상태를 다중 소스에서 관리하지 않음) — **B10-02 이월 (B-14)** (kiwoom_providers.py 중복 구현 dead code 조사 필요)
- [x] P13: 설정값 O(1) 메모리 조회 (틱/통지 단계에서 DB 설정 조회 없음) — 준수
- [x] P16: dead code/no-op 함수 없음 (전체 grep으로 호출처 확인) — **해결 B10-03 ~ B10-09** (B-10-a 완료)
- [x] P19: `await` 누락 없음 (`python -W error::RuntimeWarning main.py` 검증) — 준수
- [x] P20: 폴백/silent `except: pass` 없음 ("행 없음" vs "DB 에러" 구분) — **해결 B10-10, B10-11** (B-10-a 완료)
- [x] P21: 계좌 상태 변화(잔고/평가금/서킷브레이커)가 WS 브로드캐스트로 UI에 전달됨 — 준수
- [x] P23: 용어 사전 준수 ("업종"/"종목"), 에러/비동기/네이밍/상수 패턴 파일 간 일관 — 준수
- [x] P24: 함수 50줄·파일 500줄·복잡도 10 기준, 불필요한 추상화/1회용 래퍼 없음 — **해결 B10-12 ~ B10-17** (B-10-b 완료)

**검증** (B-10-b 세션에서 수행 완료)
- [x] `pytest backend/tests` 2961 passed (test_engine_account_notify + test_engine_account_rest + 전체)
- [x] `python -W error::RuntimeWarning main.py` 10s 기동 검증 (RuntimeWarning 없음)
- [x] 잔여 위반 패턴 grep (`kiwoom_`/`ls_` 접두사, `except.*pass`, dead code) 추가 인스턴스 없음

**조사 결과 요약** (2026-07-21)
- 위반 17건 발견: B10-01 ~ B10-17 (HIGH 3건, MEDIUM 14건)
- 해결 16건 (B-10-a: B10-03~11 9건, B-10-b: B10-01, B10-12~17 7건)
- 이월 1건: B10-02 (B-14에서 kiwoom_providers.py dead code 조사)
- 위반 원칙: P4(1), P10(1), P16(7), P20(2), P24(6)
- 준수 원칙: P2, P5, P13, P19, P21, P23
- 상세 기록: `architecture_audit_plan.md` 섹션 7 "발견된 문제 기록" 참조

---

### 세션 B-11: P1 — 파이프라인 (Compute / Gateway)

**대상 파일** (3개, 총 1112줄)
- [x] `backend/app/pipelines/pipeline_compute.py` (672줄, B-11-a 분할 완료 — 863줄→672줄)
- [x] `backend/app/pipelines/pipeline_compute_tick_handlers.py` (320줄, B-11-a 신규 — 틱 핸들러/코얼레싱 분리)
- [ ] `backend/app/pipelines/pipeline_gateway.py` (120줄, 중형 — B-11-b에서 점검)

**대상 원칙**: P1, P2, P5, P7, P8, P9, P11, P14, P19, P20, P23, P24

**조사 체크리스트** (2026-07-21 조사 완료)
- [x] P1: 단일 이벤트 루프 (`asyncio.run()` 신규 루프 없음) — 준수
- [x] P2: 모든 I/O `async def` — 준수
- [x] P5: `asyncio.Queue` 파이프라인, 직접 호출 (옵서버 패턴 금지) — 준수
- [x] P7: 파이프라인 단계에 블로킹 연산 없음 — 준수 (배치 처리)
- [x] P8: 실시간 파이프라인으로서 배치(`market_close_pipeline`)와 분리 — 준수
- [x] P9: 파이프라인 독립성 (gateway는 app.py에서 독립 시작) — 준수
- [x] P11: 이벤트 기반 (`Queue.get()` 대기, `while + sleep` 폴링 금지) — **해결 B11-11** (B-11-b: Phase 1 `while + asyncio.sleep(1.0)` 폴링 → `LazyEvent.wait()` + 200ms 디바운스 전환, 사용자 승인 대안1)
- [x] P14: 멀티스레드 없음 (`threading.Thread()` 신규 생성 금지) — 준수
- [x] P19: `await` 누락 없음 — 준수 (런타임 기동 검증)
- [x] P20: 폴백/silent except 없음 — **해결 B11-08~10** (B-11-b: PGM `except ValueError: tval=0` → 로깅+스킵, `get(nk, {})` 폴백 2건 → `nk in cache` 명시적 분기+로깅)
- [x] P23: 용어 사전 준수, 패턴 일관 — 준수 ("업종"/"종목" 사용)
- [x] P24: 단순성 기준 — **해결 B11-01~07** (B-11-a: 모든 함수 50줄 이하, 파일 863줄→672줄+320줄 분할). 잔여 172줄 초과분은 수신율 로직(테스트 모듈 전역 직접 참조)으로 B-11-b에서 별도 검토
- [x] P16/P21: `add_done_callback` 배선 — **해결 B11-12** (B-11-a: compute/sector_recompute 태스크 실패 시 로깅, gateway 루프와 일관)

**검증** (B-11-a + B-11-b 세션에서 수행 완료)
- [x] `pytest backend/tests/test_pipeline_compute.py backend/tests/test_pipeline_gateway.py` 106 passed (B-11-a)
- [x] `pytest backend/tests` 2964 passed (전체, B-11-b)
- [x] `python -W error::RuntimeWarning main.py` 기동 검증 (B-11-b: RuntimeWarning/Traceback 없음, 잔존 프로세스 0건)
- [x] 잔존 프로세스 0건 확인

**조사 결과 요약** (2026-07-21)
- 위반 12건 발견: B11-01 ~ B11-12 (HIGH 2건, MEDIUM 9건, LOW 1건)
- 해결 12건 전부 완료: B-11-a (B11-01~07 P24 분할 + B11-12 add_done_callback) + B-11-b (B11-08~10 P20 폴백 + B11-11 P11 폴링→이벤트)
- 위반 원칙: P11(1), P16/P21(1), P20(3), P24(7) — 전부 해결
- 준수 원칙: P1, P2, P5, P7, P8, P9, P14, P19, P23
- 상세 기록: `architecture_audit_plan.md` 섹션 7 "발견된 문제 기록" 참조

---

### 세션 B-12: P2 — DB 계층 ☑ 완료 (9건 수정)

**대상 파일** (4개, 총 698줄)
- [x] `backend/app/db/stock_tables.py` (387줄, 대형)
- [x] `backend/app/db/db_writer.py` (183줄, 중형)
- [x] `backend/app/db/database.py` (43줄, 소형) — 위반 없음
- [x] `backend/app/db/json_utils.py` (85줄, 소형) — 위반 없음

**대상 원칙**: P2, P6, P8, P9, P10, P12, P19, P20, P23, P24

**조사 체크리스트**
- [ ] P2: `aiosqlite` 사용, 동기 `sqlite3` 없음
- [ ] P6: SQLite 단일화, ORM/SQLAlchemy 없음, Raw SQL
- [ ] P8: 실시간/배치 쓰기 분리
- [ ] P9: `db_write_queue` 쓰기 직렬화
- [ ] P10: 데이터 SSOT (같은 데이터 다중 테이블 관리 금지)
- [ ] P12: `_db_connection` 싱글톤, 매 요청 `connect()` 금지
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음 ("행 없음" vs "DB 에러" 구분 — B04-02 교훈)
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `pytest backend/tests -k "db or stock_tables or db_writer"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증
- [ ] 잔여 동기 `sqlite3` / `connect()` 직접 호출 grep 추가 인스턴스 없음

---

### 세션 B-13: P2 — 설정 관리

**대상 파일** (5개, 총 1387줄)
- [ ] `backend/app/core/settings_file.py` (440줄, 대형)
- [ ] `backend/app/core/settings_store.py` (382줄, 대형)
- [ ] `backend/app/core/engine_settings.py` (346줄, 대형)
- [ ] `backend/app/core/settings_defaults.py` (180줄, 중형)
- [ ] `backend/app/core/trade_mode.py` (39줄, 소형)

**대상 원칙**: P2, P6, P10, P12, P13, P17, P20, P23, P24

**조사 체크리스트**
- [ ] P2: DB I/O `async def`
- [ ] P6: SQLite, Raw SQL
- [ ] P10: `integrated_system_settings_cache` SSOT (다중 캐시 금지)
- [ ] P12: DB 연결 싱글톤
- [ ] P13: 설정 메모리 상주, 틱 연산에서 DB 조회 없음
- [ ] P17: 플래그 단일 소스 (`auto_buy_on`/`auto_sell_on` 등 다중 수정 금지)
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `pytest backend/tests -k "settings"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증
- [ ] 잔여 플래그 다중 수정 패턴 grep (`auto_buy_on\s*=`) 추가 인스턴스 없음

---

### 세션 B-14: P2 — Broker 추상화 (공통)

> **분할 진행**: B-14-a (기계적 6건 완료) / B-14-b (핵심 동작 2건 완료 — B14-05/B14-06 P20/P21 폴백) — **B-14 완료**

**대상 파일** (7개, 총 1133줄)
- [x] `backend/app/core/broker_router.py` (290줄→281줄, 대형) — B14-07 dead 분기 제거
- [ ] `backend/app/core/connector_manager.py` (292줄, 대형) — B14-08 완료, B14-b 대상 아님
- [x] `backend/app/core/broker_registry.py` (184줄→179줄, 중형) — B14-04 중복 통합
- [ ] `backend/app/core/broker_providers.py` (120줄, 중형) — B14-09 재검토: P4 위반 아님
- [x] `backend/app/core/broker_factory.py` (58줄→36줄, 중형) — B14-01/02 dead code 제거
- [ ] `backend/app/core/broker_connector.py` (107줄, 중형) — 위반 없음
- [x] `backend/app/core/broker_urls.py` (82줄→80줄, 중형) — B14-03 dead 상수 제거

**대상 원칙**: P2, P3, P4, P5, P10, P14, P19, P20, P23, P24

**조사 체크리스트**
- [x] P2: 모든 I/O `async def`
- [x] P3: `run_in_executor` 없음
- [x] P4: 공통 로직에 `kiwoom_`/`ls_` 접두사 없음 (B14-01 해결 — broker_factory kiwoom 분기 제거)
- [x] P5: 직접 호출 체인
- [x] P10: 인증 토큰 캐시 SSOT
- [x] P14: 멀티스레드 없음
- [x] P19: `await` 누락 없음
- [x] P20: 폴백/silent except 없음 (B14-05/B14-06 해결 — broker_router._build·get_provider 폴백 제거, ValueError 전파)
- [x] P23: 용어 사전 준수, 패턴 일관 (B14-04/B14-08 해결)
- [x] P24: 단순성 기준 (B14-04 중복 통합)

**검증**
- [x] `pytest backend/tests -k "broker or connector"` 통과 (342 passed)
- [x] `python -W error::RuntimeWarning main.py` 기동 검증 (359ms 정상 기동)
- [x] 잔여 `kiwoom_`/`ls_` 접두사가 공통 파일에 침투하지 않았는지 grep 확인

**B-14-a 완료 (2026-07-21)**: 기계적 6건 해결 (B14-01/02/03/04/07/08). B14-09는 재검토 결과 P4 위반 아님 (UnifiedStockRecord는 범용 공통 데이터 클래스).
**B-14-b 완료 (2026-07-21)**: B14-05 (broker_router._build 증권사 비어있음 → 기본 증권사 조용히 대체, P20/P21) — dead code 제거 + ValueError 전파. B14-06 (get_provider 페이지 오버라이드 실패 시 전역 Provider 폴백, P20) — try/except 제거 + ValueError 전파. 규칙 0-4 적용, UI 기준 설명 + 승인 완료.
**B-14 완료**: Broker 추상화 공통 7개 파일 9건 전부 해결.

---

### 세션 B-15: P2 — 증권사 구현: 키움증권

> **분할 권장**: 총 2060줄. B-15-a (connector + rest, 1209줄) / B-15-b (stock_rest + providers + order, 851줄) 분할 권장.

**대상 파일** (5개, 총 2060줄)
- [x] `backend/app/core/kiwoom_connector.py` (554줄→520줄, B-15-a 완료)
- [x] `backend/app/core/kiwoom_rest.py` (655줄→636줄, B-15-a 완료)
- [x] `backend/app/core/kiwoom_stock_rest.py` (436줄→407줄, B-15-b 완료)
- [x] `backend/app/core/kiwoom_providers.py` (342줄, B-15-b 조사 결과 위반 없음)
- [x] `backend/app/core/kiwoom_order.py` (73줄→76줄, B-15-b 완료)

**대상 원칙**: P1, P2, P3, P4, P5, P7, P14, P19, P20, P23, P24

**조사 체크리스트**
- [x] P1: `asyncio.run()` 신규 루프 생성 없음 (B-15-a)
- [x] P2: `httpx.AsyncClient` 사용, 동기 `requests` 없음 (B-15-a)
- [x] P3: `run_in_executor` 없음 (B-15-a)
- [x] P4: 키움 특화 로직이 공통 로직에 침투하지 않음 (별도 파일 격리 확인) (B-15-a)
- [x] P5: 직접 호출 체인 (B-15-a)
- [x] P7: WS 수신 핸들러에 블로킹 없음 (B-15-a)
- [x] P14: 멀티스레드 없음 (B-15-a)
- [x] P19: `await` 누락 없음 (B-15-a)
- [x] P20: 폴백/silent except 없음 (B-15-a)
- [x] P23: 용어 사전 준수, 패턴 일관 (B-15-a)
- [x] P24: 단순성 기준 (B-15-a: 중복 함수 추출로 connector 34줄 감소)
- [x] P1~P24 잔여: B-15-b (stock_rest + providers + order) — 7건 해결

**검증**
- [x] `pytest backend/tests -k "kiwoom"` 통과 (336 passed, B-15-a / 330 passed, B-15-b)
- [x] `python -W error::RuntimeWarning main.py` 기동 검증 (95ms 정상 기동, B-15-a / 94ms 정상 기동, B-15-b)
- [x] 잔여 동기 `requests` / `asyncio.run` / `run_in_executor` grep 추가 인스턴스 없음 (B-15-a)
- [x] B-15-b 검증 (stock_rest + providers + order) — 330 passed(test_kiwoom) + 2961 passed(전체) + 94ms 기동

**B-15-a 완료 (2026-07-21)**: 7건 해결 (B15-01~07). B15-01 set_queue_callback dead code 제거 (P16), B15-02 _make_queue_callback 헬퍼 추출로 connect()/_reconnect_loop() 중복 중첩함수 통합 (P23/P24), B15-03/B15-04 except Exception logger에 exc_info=True 추가 (P23), B15-05 get_spec dead wrapper 제거 (P16), B15-06 __enter__/__exit__ 동기 컨텍스트 매니저 dead code 제거 (P16), B15-07 fetch_ka20001_index JSON 파싱 실패 로그를 info→warning으로 변경 (P23).

**B-15-b 완료 (2026-07-21)**: 7건 해결 (B15-08~14). B15-08 except Exception 6곳에 exc_info=True 추가 (P23), B15-09 _pct dead code 제거 (P16), B15-10 _build_ka10081_request/_ensure_descending_by_dt 헬퍼 추출로 fetch_ka10081_daily_price/5d_data 중복 로직 통합 (P23/P24), B15-11 _fetch_all_stocks_ka10081 공통 루프 헬퍼 추출로 fetch_ka10081_all_stocks_daily_confirmed/5day 통합 (P23/P24), B15-14 hit_429 미사용 변수 _로 대체 (P24), B15-12 kiwoom_order.py logger 모듈 레벨로 이동 (P23/P24), B15-13 kiwoom_order.py except Exception에 exc_info=True 추가 (P23). kiwoom_providers.py는 조사 결과 위반 없음. 미해결 문제 2건 HANDOVER.md 기록: kiwoom_rest.py exc_info 8곳 누락, kiwoom_providers.py:75 계좌번호 real/legacy 불일치.

**B-15 완료**: 키움증권 구현 5개 파일 14건(B-15-a 7건 + B-15-b 7건) 전부 해결.

---

### 세션 B-16: P2 — 증권사 구현: LS증권

> **분할 권장**: 총 1732줄. B-16-a (ls_connector 895줄) / B-16-b (ls_rest + ls_providers 837줄) 분할 권장.

**대상 파일** (3개, 총 1732줄)
- [ ] `backend/app/core/ls_connector.py` (895줄, 초대형)
- [ ] `backend/app/core/ls_rest.py` (639줄, 대형)
- [ ] `backend/app/core/ls_providers.py` (198줄, 중형)

**대상 원칙**: P1, P2, P3, P4, P5, P7, P14, P19, P20, P23, P24

**조사 체크리스트**
- [ ] P1: `asyncio.run()` 신규 루프 생성 없음 (과거 위반 사례 `_run_async()` 재발 확인)
- [ ] P2: `httpx.AsyncClient` 사용
- [ ] P3: `run_in_executor` 없음
- [ ] P4: LS 특화 로직이 공통 로직에 침투하지 않음
- [ ] P5: 직접 호출 체인
- [ ] P7: WS 수신 핸들러에 블로킹 없음
- [ ] P14: 멀티스레드 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준 (ls_connector.py 895줄 → 분할 강력 권장)

**검증**
- [ ] `pytest backend/tests -k "ls_"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증 (LS 모의투자 모드)
- [ ] 잔여 `_run_async` / `asyncio.run` / 동기 `requests` grep 추가 인스턴스 없음

---

### 세션 B-17: P2 — Domain 계층 (모델/업종계산/필터)

**대상 파일** (6개, 총 1209줄)
- [ ] `backend/app/domain/sector_calculator.py` (213줄, 대형)
- [ ] `backend/app/domain/buy_filter.py` (336줄, 대형)
- [ ] `backend/app/domain/sector_score.py` (200줄, 대형)
- [ ] `backend/app/domain/sector_filter.py` (57줄, 소형)
- [ ] `backend/app/domain/models.py` (81줄, 중형)
- [ ] `backend/app/core/stock_filter.py` (322줄, 대형)

**대상 원칙**: P7, P10, P13, P16, P18, P20, P22, P23, P24

**조사 체크리스트**
- [ ] P7: 계산 로직에 블로킹/DB 조회 없음 (순수 계산)
- [ ] P10: 데이터 모델 SSOT
- [ ] P13: 설정값 메모리 조회
- [ ] P16: dead code 없음
- [ ] P18: 테스트모드와 동일한 계산
- [ ] P20: 폴백/silent except 없음
- [ ] P22: 파생 데이터 모델 선호, 단계 간 일관성
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `pytest backend/tests -k "sector or buy_filter or stock_filter or domain"` 통과
- [ ] 잔여 DB 직접 조회 / 동기 I/O grep 추가 인스턴스 없음

---

### 세션 B-18: P2 — 스케줄러 및 장마감 파이프라인

> **분할 강력 권장**: 총 3150줄 (초대형 2개). B-18-a (market_close_pipeline 1407줄) / B-18-b (daily_time_scheduler 1506줄 + data_manager 237줄) 분할.

**대상 파일** (3개, 총 3150줄)
- [ ] `backend/app/services/market_close_pipeline.py` (1407줄, 초대형)
- [ ] `backend/app/services/daily_time_scheduler.py` (1506줄, 초대형)
- [ ] `backend/app/services/data_manager.py` (237줄, 대형)

**대상 원칙**: P1, P2, P5, P7, P8, P9, P11, P14, P16, P19, P20, P23, P24

**조사 체크리스트**
- [ ] P1: 단일 이벤트 루프
- [ ] P2: 모든 I/O `async def`
- [ ] P5: 직접 호출 체인
- [ ] P7: 배치 연산 중 실시간 틱 차단 금지
- [ ] P8: 배치 파이프라인으로서 실시간과 분리
- [ ] P9: 파이프라인 독립성
- [ ] P11: `asyncio.call_later()` 기반, 폴링 없음
- [ ] P14: 멀티스레드 없음
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준 (1407줄/1506줄 → 분할 필수)

**검증**
- [ ] `pytest backend/tests -k "market_close or scheduler or data_manager"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증 (장마감 시뮬레이션)
- [ ] 잔여 폴링 / `threading.Thread` / dead code grep 추가 인스턴스 없음

---

### 세션 B-19: P2 — WS 구독 제어 및 업종 데이터 제공자

**대상 파일** (2개, 총 572줄)
- [ ] `backend/app/services/ws_subscribe_control.py` (262줄, 대형)
- [ ] `backend/app/services/sector_data_provider.py` (310줄, 대형)

**대상 원칙**: P4, P5, P7, P10, P11, P13, P16, P20, P23, P24

**조사 체크리스트**
- [ ] P4: 증권사 이름 침투 없음
- [ ] P5: 직접 호출 체인
- [ ] P7: 구독 제어에 블로킹 없음
- [ ] P10: 업종 데이터 SSOT
- [ ] P11: 이벤트 기반
- [ ] P13: 설정 메모리 조회
- [ ] P16: dead code 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `pytest backend/tests -k "ws_subscribe or sector_data"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증
- [ ] 잔여 증권사 접두사 / 폴링 grep 추가 인스턴스 없음

---

### 세션 B-20: P3 — 알림 (Telegram / Notification)

**대상 파일** (3개, 총 668줄)
- [ ] `backend/app/services/telegram_bot.py` (527줄, 대형)
- [ ] `backend/app/services/telegram.py` (43줄, 소형)
- [ ] `backend/app/services/notification_worker.py` (98줄, 중형)

**대상 원칙**: P2, P5, P14, P16, P19, P20, P21, P23, P24

**조사 체크리스트**
- [ ] P2: HTTP I/O `async def` (`httpx.AsyncClient`)
- [ ] P5: 직접 호출 체인
- [ ] P14: 멀티스레드 없음
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P21: 중요 상태 변화(서킷브레이커, 매수 차단 등)가 알림으로 전달됨
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `pytest backend/tests -k "telegram or notification"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증
- [ ] 잔여 동기 `requests` / dead code grep 추가 인스턴스 없음

---

### 세션 B-21: P3 — 기타 Core 유틸

**대상 파일** (11개, 총 1951줄)
- [ ] `backend/app/core/journal.py` (324줄, 대형)
- [ ] `backend/app/core/logger.py` (426줄, 대형)
- [ ] `backend/app/core/trading_calendar.py` (406줄, 대형)
- [ ] `backend/app/core/stock_classification_data.py` (238줄, 대형)
- [ ] `backend/app/core/sector_mapping.py` (99줄, 중형)
- [ ] `backend/app/core/sector_stock_cache.py` (140줄, 중형)
- [ ] `backend/app/core/lock_manager.py` (146줄, 중형)
- [ ] `backend/app/core/encryption.py` (87줄, 중형)
- [ ] `backend/app/core/memory_monitor.py` (52줄, 중형)
- [ ] `backend/app/core/constants.py` (14줄, 소형)
- [ ] `backend/app/core/logging_config.py` (19줄, 소형)

**대상 원칙**: P2, P5, P10, P14, P16, P19, P20, P23, P24

**조사 체크리스트**
- [ ] P2: `asyncio.Lock` 사용, `threading.Lock` 없음
- [ ] P5: 직접 호출 체인
- [ ] P10: 종목 매핑/분류 캐시 SSOT
- [ ] P14: 멀티스레드 없음
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `pytest backend/tests -k "journal or logger or calendar or classification or lock or encryption"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증
- [ ] 잔여 `threading.Lock` / `threading.Thread` grep 추가 인스턴스 없음

---

### 세션 B-22: P3 — Web API 계층

**대상 파일** (14개, 총 1918줄)
- [ ] `backend/app/web/app.py` (323줄, 대형)
- [ ] `backend/app/web/ws_manager.py` (351줄, 대형)
- [ ] `backend/app/web/routes/stock_classification.py` (372줄, 대형)
- [ ] `backend/app/web/routes/settings.py` (166줄, 중형)
- [ ] `backend/app/web/routes/status.py` (144줄, 중형)
- [ ] `backend/app/web/routes/ws.py` (206줄, 대형)
- [ ] `backend/app/web/routes/ws_subscribe.py` (71줄, 중형)
- [ ] `backend/app/web/auth.py` (45줄, 소형)
- [ ] `backend/app/web/deps.py` (26줄, 소형)
- [ ] `backend/app/web/routes/account.py` (5줄, 소형)
- [ ] `backend/app/web/routes/auth.py` (28줄, 소형)
- [ ] `backend/app/web/routes/market.py` (17줄, 소형)
- [ ] `backend/app/web/routes/settlement.py` (17줄, 소형)
- [ ] `backend/app/app/config.py` (79줄, 중형)

**대상 원칙**: P2, P5, P10, P12, P13, P16, P19, P20, P21, P23, P24

**조사 체크리스트**
- [ ] P2: 모든 엔드포인트 `async def`
- [ ] P5: 직접 호출 체인
- [ ] P10: 설정/상태 SSOT 참조
- [ ] P12: DB 연결 싱글톤
- [ ] P13: 설정 DB 직접 조회 없음 (캐시 참조)
- [ ] P16: dead code 없음 (F01-07 인증 dead code 교훈 — 잔존 확인)
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P21: 백엔드 상태가 API/WebSocket으로 프론트엔드에 전달됨
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `pytest backend/tests -k "web or routes or ws_manager"` 통과
- [ ] `python -W error::RuntimeWarning main.py` 기동 검증
- [ ] 잔여 동기 엔드포인트 / DB 직접 조회 grep 추가 인스턴스 없음

---

### 세션 B-23: P3 — 테스트 품질 점검

**대상 파일** (67개, `backend/tests/` 전체)

**대상 원칙**: P16, P18, P19, P22, P23, P24

**조사 체크리스트**
- [ ] 테스트 커버리지 현황 파악 (모듈별)
- [ ] P16: 테스트가 살아있는 경로를 검증하는지 (dead code 테스트 아님)
- [ ] P18: 테스트모드 동등성 검증 존재 여부
- [ ] P19: `RuntimeWarning(coroutine never awaited)` 감지 테스트
- [ ] P22: 데이터 정합성 대조(reconciliation) 테스트
- [ ] P23: 용어/에러/비동기/네이밍/상수 일관성 점검
- [ ] P24: 단순성 점검 (불필요한 추상화, 복잡도)
- [ ] 미커버 모듈 식별 (테스트 파일 없는 소스 파일)
- [ ] 통합 테스트 vs 단위 테스트 비율

**검증**
- [ ] `pytest backend/tests` 전체 통과
- [ ] 커버리지 리포트 (`pytest --cov`) 확인
- [ ] 미커버 모듈 목록화

---

### 세션 F-02: P1 — 진입점, 라우팅, 레이아웃

**대상 파일** (6개, 총 1530줄)
- [ ] `frontend/src/main.ts` (329줄, 대형)
- [ ] `frontend/src/layout/header.ts` (519줄, 대형)
- [ ] `frontend/src/router.ts` (273줄, 대형)
- [ ] `frontend/src/layout/shell.ts` (169줄, 중형)
- [ ] `frontend/src/layout/sidebar.ts` (99줄, 중형)
- [ ] `frontend/src/settings.ts` (141줄, 중형)

**대상 원칙**: P5, P10, P16, P19, P21, P23, P24

**조사 체크리스트**
- [ ] P5: 직접 호출 체인 (이벤트 버스 없음)
- [ ] P10: 전역 상태 SSOT 참조
- [ ] P16: dead code/미사용 라우트 없음
- [ ] P19: 비동기 초기화 누락 없음
- [ ] P21: 엔진 상태/연결 상태가 헤더에 표시됨
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준 (header.ts 519줄 → 분할 검토)

**검증**
- [ ] `npm run build` 성공 (tsc 타입체크 + vite 빌드)
- [ ] 브라우저 확인 (모든 라우트 진입, 헤더 상태 표시)
- [ ] 잔여 dead code / 미사용 라우트 grep 추가 인스턴스 없음

---

### 세션 F-03: P2 — 핵심 매매 페이지 (업종순위/매수후보/보유종목)

**대상 파일** (6개, 총 2135줄)
- [ ] `frontend/src/pages/sector-stock.ts` (671줄, 대형)
- [ ] `frontend/src/pages/buy-target.ts` (469줄, 대형)
- [ ] `frontend/src/pages/sell-position.ts` (258줄, 대형)
- [ ] `frontend/src/pages/sector-ranking-list.ts` (351줄, 대형)
- [ ] `frontend/src/pages/sector-ranking-page.ts` (82줄, 소형)
- [ ] `frontend/src/pages/stock-detail.ts` (304줄, 대형)

**대상 원칙**: P5, P10, P16, P19, P21, P22, P23, P24

**조사 체크리스트**
- [ ] P5: 직접 호출 체인
- [ ] P10: 페이지 상태가 Store에서 관리됨 (로컬 중복 없음)
- [ ] P16: dead code/미사용 함수 없음
- [ ] P19: 비동기 데이터 로딩 누락 없음
- [ ] P21: 매수 차단/가드 실패 이유가 UI에 표시됨
- [ ] P22: 실시간 시세와 표시 데이터 간 정합성
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준 (sector-stock.ts 671줄 → 분할 검토)

**검증**
- [ ] `npm run build` 성공
- [ ] 브라우저 확인 (업종순위/매수후보/보유종목 페이지 렌더링)
- [ ] 잔여 로컬 상태 중복 / dead code grep 추가 인스턴스 없음

---

### 세션 F-04: P2 — 설정 페이지 (매수/매도/일반/업종/종목분류)

> **분할 권장**: 총 3145줄. F-04-a (stock-classification 1617줄) / F-04-b (general-settings 1421줄 + buy-settings 424 + sell-settings 174 + sector-settings 509) 분할 권장.

**대상 파일** (5개, 총 3145줄)
- [ ] `frontend/src/pages/stock-classification.ts` (1617줄, 초대형)
- [ ] `frontend/src/pages/general-settings.ts` (1421줄, 대형)
- [ ] `frontend/src/pages/buy-settings.ts` (424줄, 대형)
- [ ] `frontend/src/pages/sell-settings.ts` (174줄, 중형)
- [ ] `frontend/src/pages/sector-settings.ts` (509줄, 대형)

**대상 원칙**: P10, P13, P16, P17, P19, P21, P23, P24

**조사 체크리스트**
- [ ] P10: 설정값이 Store를 통해 백엔드 SSOT와 동기화됨
- [ ] P13: 설정 변경 시 백엔드 캐시 갱신 경로 확인
- [ ] P16: dead code/미사용 설정 항목 없음
- [ ] P17: 플래그 토글이 단일 경로로 백엔드에 전달됨
- [ ] P19: 설정 저장 비동기 처리 누락 없음
- [ ] P21: 설정 변경 결과가 UI에 즉시 반영됨
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준 (1617줄/1421줄 → 분할 필수)

**검증**
- [ ] `npm run build` 성공
- [ ] 브라우저 확인 (모든 설정 탭 저장/로드)
- [ ] 잔여 플래그 다중 경로 / dead code grep 추가 인스턴스 없음

---

### 세션 F-05: P3 — 수익 페이지

**대상 파일** (3개, 총 1954줄)
- [ ] `frontend/src/pages/profit-overview.ts` (718줄, 대형)
- [ ] `frontend/src/pages/profit-detail.ts` (667줄, 대형)
- [ ] `frontend/src/pages/profit-shared.ts` (569줄, 대형)

**대상 원칙**: P5, P10, P16, P19, P22, P23, P24

**조사 체크리스트**
- [ ] P5: 직접 호출 체인
- [ ] P10: 수익 데이터가 Store에서 관리됨
- [ ] P16: dead code 없음
- [ ] P19: 비동기 데이터 로딩 누락 없음
- [ ] P22: 수익 데이터와 백엔드 정산 데이터 간 정합성
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준 (718/667/569줄 → 분할 검토)

**검증**
- [ ] `npm run build` 성공
- [ ] 브라우저 확인 (수익 페이지 렌더링)
- [ ] 잔여 dead code / 정합성 위반 grep 추가 인스턴스 없음

---

### 세션 F-06: P3 — 공통 컴포넌트

> **분할 권장**: 총 25파일 6803줄. F-06-a (data-table 1053 + setting-row 626 + ui-styles 598 + virtual-scroller 531 + canvas-profit-chart 512) / F-06-b (button 336 + canvas-sector-donut 347 + dialog 261 + context-popup 260 + settings-common 243 + 나머지 소형 15개) 분할 권장.

**대상 파일** (25개, 총 6803줄)
- [ ] `frontend/src/components/common/data-table.ts` (1053줄, 대형)
- [ ] `frontend/src/components/common/setting-row.ts` (626줄, 대형)
- [ ] `frontend/src/components/common/ui-styles.ts` (598줄, 대형)
- [ ] `frontend/src/components/virtual-scroller.ts` (531줄, 대형)
- [ ] `frontend/src/components/canvas-profit-chart.ts` (512줄, 대형)
- [ ] `frontend/src/components/common/button.ts` (336줄, 대형)
- [ ] `frontend/src/components/canvas-sector-donut.ts` (347줄, 대형)
- [ ] `frontend/src/components/common/dialog.ts` (261줄, 대형)
- [ ] `frontend/src/components/common/context-popup.ts` (260줄, 대형)
- [ ] `frontend/src/components/common/settings-common.ts` (243줄, 대형)
- [ ] `frontend/src/components/common/progress-bar.ts` (182줄, 중형)
- [ ] `frontend/src/components/common/create-slider.ts` (201줄, 대형)
- [ ] `frontend/src/components/common/search-input.ts` (153줄, 중형)
- [ ] `frontend/src/components/common/badge.ts` (147줄, 중형)
- [ ] `frontend/src/components/common/auto-width.ts` (128줄, 중형)
- [ ] `frontend/src/components/common/market-count-row.ts` (113줄, 중형)
- [ ] `frontend/src/components/common/table-config.ts` (97줄, 중형)
- [ ] `frontend/src/components/common/date-range-input.ts` (96줄, 중형)
- [ ] `frontend/src/components/common/toast.ts` (189줄, 중형)
- [ ] `frontend/src/components/common/time-pair-input.ts` (64줄, 소형)
- [ ] `frontend/src/components/common/sector-row.ts` (62줄, 소형)
- [ ] `frontend/src/components/common/card-header.ts` (42줄, 소형)
- [ ] `frontend/src/components/common/broker-badge.ts` (42줄, 소형)
- [ ] `frontend/src/components/common/account-labels.ts` (32줄, 소형)
- [ ] `frontend/src/components/common/card-title.ts` (21줄, 소형)

**대상 원칙**: P5, P10, P16, P23, P24

**조사 체크리스트**
- [ ] P5: 컴포넌트 간 직접 호출 (이벤트 버스 없음)
- [ ] P10: 컴포넌트 상태가 Store에서 관리됨 (로컬 상태 최소화)
- [ ] P16: dead code/미사용 컴포넌트 없음
- [ ] P23: UI 패턴(목록/카드/태그/버튼/모달) 2회 이상 반복 시 공통 컴포넌트 추출, 직접 중복 구현 없음. 용어 사전 준수
- [ ] P24: 단순성 기준 (data-table 1053줄, setting-row 626줄, ui-styles 598줄 → 분할 검토)

**검증**
- [ ] `npm run build` 성공
- [ ] 브라우저 확인 (모든 페이지에서 공통 컴포넌트 렌더링)
- [ ] 잔여 중복 UI 패턴 / dead code grep 추가 인스턴스 없음

---

### 세션 F-07: P3 — 타입 및 유틸

**대상 파일** (5개, 총 651줄)
- [ ] `frontend/src/types/index.ts` (350줄, 대형)
- [ ] `frontend/src/types/event.ts` (165줄, 중형)
- [ ] `frontend/src/utils/settings-save.ts` (78줄, 중형)
- [ ] `frontend/src/utils/settings-page.ts` (54줄, 소형)
- [ ] `frontend/src/utils/sliderConvert.ts` (9줄, 소형)

**대상 원칙**: P10, P16, P23, P24

**조사 체크리스트**
- [ ] P10: 타입 정의가 백엔드 모델과 일치함 (SSOT 관점)
- [ ] P16: 미사용 타입/유틸 함수 없음
- [ ] P23: 용어 사전 준수, 패턴 일관
- [ ] P24: 단순성 기준

**검증**
- [ ] `npm run build` 성공 (tsc 타입체크)
- [ ] 잔여 미사용 타입 / 유틸 grep 추가 인스턴스 없음

---

## 4. 세션 공통 워크플로우 (AGENTS.md 규칙 0-1 준수)

```
┌─────────────────────────────────────────────────────────────┐
│  1. 사전조사 (규칙 0-2 의무)                                  │
│  ├── 각 파일 전체 읽기                                        │
│  ├── 24개 원칙 체크리스트 대조                                │
│  ├── 의존성/호출 관계 추적 (grep)                             │
│  ├── 기존 공통 자산 확인 (P23 사전 절차)                      │
│  └── 위반 사항 식별 → plan 섹션 7에 ID 부여 기록              │
├─────────────────────────────────────────────────────────────┤
│  2. 사용자 승인 대기 (규칙 0)                                 │
│  ├── 위반 사항 + 수정 계획 + 영향 범위 보고                   │
│  ├── 핵심 로직 변경 시 UI 기준 설명 (규칙 0-4)                │
│  └── 사용자 명시적 승인("진행해"/"수정해" 등) 대기            │
├─────────────────────────────────────────────────────────────┤
│  3. 수정 (승인 후)                                            │
│  ├── 파일 하나씩, 블록 단위 수정 (규칙 3)                     │
│  ├── 금지: 임시방편, 폴백, !important, as any                │
│  └── 사용자 설계 로직 변경 시 더 엄격한 절차 (규칙 0-5)       │
├─────────────────────────────────────────────────────────────┤
│  4. 검증 (규칙 4)                                             │
│  ├── 백엔드: pytest + python -W error::RuntimeWarning main.py│
│  ├── 프론트엔드: npm run build + 브라우저 확인                │
│  └── 잔여 위반 패턴 grep 확인                                 │
├─────────────────────────────────────────────────────────────┤
│  5. 세션 종료                                                 │
│  ├── 커밋 (규칙 0-3 롤백 사유 기록 의무 준수)                 │
│  ├── HANDOVER.md 갱신                                         │
│  ├── plan 섹션 7/8 갱신                                       │
│  ├── 본 파일 섹션 2 상태 표 갱신                              │
│  └── 사용자 보고 후 세션 종료 (다음 세션은 다음 기회)         │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 위반 사항 기록 템플릿

> 각 세션에서 위반 사항 발견 시 `architecture_audit_plan.md` 섹션 7에 아래 포맷으로 기록.

```
| ID | 세션 | 파일:줄 | 위반 원칙 | 심각도 | 설명 | 상태 |
|----|------|---------|-----------|--------|------|------|
| B10-01 | B-10 | engine_account.py:123-145 | P16 | MEDIUM | (함수명) dead code — 프로덕션 호출처 전무 (grep 확인) | 발견 |
```

**심각도 분류**
- **CRITICAL**: 자금 손실 위험, 데이터 정합성 위반, 실시간 파이프라인 중단
- **HIGH**: 아키텍처 원칙 위반 (P1~P3, P15, P16), 안전장치 미배선
- **MEDIUM**: 코드 품질 위반 (P5, P14, P19, P20), dead code
- **LOW**: 스타일/가독성, 경미한 원칙 편차

**상태 분류**
- `발견` → `수정중` → `해결` / `보류`

---

## 6. 완료 정의 (plan 섹션 9와 동일)

본 태스크 파일의 모든 세션이 "완료"로 간주되려면:

1. [ ] 30개 세션 모두 완료 표시 (본 파일 섹션 2 + plan 섹션 8)
2. [ ] 발견된 모든 CRITICAL/HIGH 문제가 `해결` 상태
3. [ ] 24개 불변 원칙에 대해 전체 코드베이스 위반 사항 0건 확인
4. [ ] 백엔드 런타임 기동 검증 통과 (`python -W error::RuntimeWarning main.py`)
5. [ ] 프론트엔드 빌드 검증 통과 (`npm run build`)
6. [ ] 테스트 스위트 통과 (`pytest backend/tests` 전체 성공)

---

## 7. 추천 다음 세션 순서

> 의존성 하위 → 상위 + 중요도 P0 → P3 교차 적용 (plan 섹션 6 기준)

1. **B-10** (P1, 엔진 계좌/서비스) — 다음 세션 추천
2. **B-11** (P1, 파이프라인)
3. **B-12** (P2, DB 계층) — 하위 계층 선행
4. **B-13** (P2, 설정 관리) — 하위 계층 선행
5. **B-14** (P2, Broker 추상화)
6. **B-15-a/b** (P2, 키움 — 분할)
7. **B-16-a/b** (P2, LS — 분할)
8. **B-17** (P2, Domain)
9. **B-18-a/b** (P2, 스케줄러/장마감 — 분할)
10. **B-19** (P2, WS 구독/업종 데이터)
11. **B-20** (P3, 알림)
12. **B-21** (P3, Core 유틸)
13. **B-22** (P3, Web API)
14. **B-23** (P3, 테스트 품질)
15. **F-02** (P1, 진입점/라우팅/레이아웃)
16. **F-03** (P2, 핵심 매매 페이지)
17. **F-04-a/b** (P2, 설정 페이지 — 분할)
18. **F-05** (P3, 수익 페이지)
19. **F-06-a/b** (P3, 공통 컴포넌트 — 분할)
20. **F-07** (P3, 타입/유틸)

---

## 8. 참고 문서

- `ARCHITECTURE.md` — 24개 불변 원칙 정의 + 금지 패턴 5개 + 부록 L 용어 사전
- `docs/architecture_audit_plan.md` — 원본 전수 점검 계획서 (세션 분할 논리, 과거 해결 이력 42건)
- `AGENTS.md` — 수행 규칙 (규칙 0, 0-1, 0-2, 0-3, 0-4, 0-5)
- `HANDOVER.md` — 세션별 진행 이력
