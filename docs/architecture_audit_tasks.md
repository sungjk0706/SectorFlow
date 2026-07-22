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
| B-10 | P1 | 엔진 계좌/서비스 | 4 | ☑ | 완료 (B-10-a 11건 + B-10-b 7건 = 18건, B10-02는 B-14 이월) |
| B-11 | P1 | 파이프라인 (Compute/Gateway) | 2 | ☑ | 완료 (B-11-a 8건 + B-11-b 4건 = 12건) |
| B-12 | P2 | DB 계층 | 4 | ☑ | 9건 수정 |
| B-13 | P2 | 설정 관리 | 5 | ☑ | 부분 완료 (3건 해결 B13-01/02/05, 잔여 5건 보류 LOW/INFO) |
| B-14 | P2 | Broker 추상화 (공통) | 7 | ☑ | 완료 (B-14-a 6건 + B-14-b 2건 = 8건) |
| B-15 | P2 | 증권사 구현: 키움 | 5 | ☑ | 완료 (B-15-a 7건 + B-15-b 7건 = 14건) |
| B-16 | P2 | 증권사 구현: LS | 3 | ☑ | 분할 권장 (완료) |
| B-17 | P2 | Domain 계층 | 6 | ☑ | 완료 (3건 P16/P24) |
| B-18 | P2 | 스케줄러 및 장마감 파이프라인 | 3 | ☑ | 완료 (6건 P16/P20, P24 분할 이월) |
| B-19 | P2 | WS 구독 제어 및 업종 데이터 | 2 | ☑ | 완료 (4건 P16/P20/P24) |
| B-20 | P3 | 알림 (Telegram) | 3 | ☑ | 완료 (3건 P16/P21) |
| B-21 | P3 | 기타 Core 유틸 | 11 | ☑ | 완료 (B-21-a journal.py 12건, B-21-b logger+encryption 4건, B-21-c classification+mapping+cache 3건 P16) |
| B-22 | P3 | Web API 계층 | 14 | ☑ | 완료 (B-22-a ws_manager dead code 3건 + B-22-b 주석 dead code 4건 + B-22-c silent except 1건/dead 변수·필드 4건/reset_test_data 분할 = 13건 P16/P20/P21/P24) |
| B-23 | P3 | 테스트 품질 점검 | 67 | ☑ | 완료 (B-23-a 메타 점검, B-23-b 대형 9개, B-23-c 중형 20개, B-23-d 소형 36개 점검 완료) |
| F-01 | P0 | 통신 계층 및 상태 관리 | 8 | ☑ | 10건 수정 |
| **F-02** | **P1** | **진입점, 라우팅, 레이아웃** | 6 | ☑ | 완료 (7건 P16/P23/P24) |
| F-03 | P2 | 핵심 매매 페이지 | 6 | ✅ | 6건 해결 (P16/P19/P23/P24), 4건 보류 |
| F-04 | P2 | 설정 페이지 | 5 | ☐ | 분할 권장 (F-04-a 5건 + F-04-b 4건 + F-04-c 4건 해결, 잔여 F-04-d/e) |
| F-05 | P3 | 수익 페이지 | 3 | ☐ | |
| F-06 | P3 | 공통 컴포넌트 | 25 | ☐ | 분할 권장 |
| F-07 | P3 | 타입 및 유틸 | 5 | ☐ | |

**진행률**: 28/30 세션 완료 (93%). B-10 완료 (B-10-a 11건 + B-10-b 7건, B10-02는 B-14 이월). B-11 완료 (B-11-a 8건 + B-11-b 4건). B-13 부분 완료 (3건 해결 B13-01/02/05, 잔여 5건 보류 LOW/INFO). B-14 완료 (B-14-a 6건 + B-14-b 2건). B-15 완료 (B-15-a 7건 + B-15-b 7건). B-23 완료 (테스트 품질 점검). F-02 완료 (7건 P16/P23/P24). F-03 완료 (6건 P16/P19/P23/P24, 4건 보류). F-04 부분 완료 (F-04-a 5건 + F-04-b 4건 + F-04-c 4건 해결, 잔여 F-04-d/e). 잔여 3세션 (F-04-d/e, F-05, F-06, F-07) + B-13 보류.

---

## 3. 세션별 실행 태스크 (잔여 6세션)

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

> **부분 완료 (2026-07-22)**: 3건 해결 (B13-01/02/05) — MEDIUM 2건 + LOW 1건 (P4). 잔여 5건 보류 (B13-03/04/06/07/08 — LOW/INFO 등급). 별도 세션에서 추가 수정 가능.

**대상 파일** (5개, 총 1387줄)
- [x] `backend/app/core/settings_file.py` (440줄→428줄, B13-01 update_settings 삭제)
- [x] `backend/app/core/settings_store.py` (382줄→362줄, B13-02 dead code 삭제)
- [x] `backend/app/core/engine_settings.py` (346줄→341줄, B13-05 키움 분기 제거)
- [ ] `backend/app/core/settings_defaults.py` (180줄, 중형) — 위반 없음
- [ ] `backend/app/core/trade_mode.py` (39줄, 소형) — 위반 없음

**대상 원칙**: P2, P6, P10, P12, P13, P17, P20, P23, P24

**조사 체크리스트** (2026-07-22 조사 완료)
- [x] P2: DB I/O `async def` — 준수
- [x] P6: SQLite, Raw SQL — 준수
- [x] P10: `integrated_system_settings_cache` SSOT (다중 캐시 금지) — 준수 (잔여: B13-03 engine_settings 기본값 61곳 중복, LOW)
- [x] P12: DB 연결 싱글톤 — 준수
- [x] P13: 설정 메모리 상주, 틱 연산에서 DB 조회 없음 — 준수
- [x] P17: 플래그 단일 소스 (`auto_buy_on`/`auto_sell_on` 등 다중 수정 금지) — 준수
- [x] P20: 폴백/silent except 없음 — 준수
- [x] P23: 용어 사전 준수, 패턴 일관 — 준수
- [x] P24: 단순성 기준 — 잔여: B13-07 함수 길이 50줄 초과 2곳 (LOW, 보류)

**검증**
- [x] `pytest backend/tests -k "settings"` 통과 (301 passed)
- [x] `python -W error::RuntimeWarning main.py` 기동 검증 (344ms, RuntimeWarning 0건)
- [x] 잔여 플래그 다중 수정 패턴 grep (`auto_buy_on\s*=`) 추가 인스턴스 없음
- [x] 잔존 참조 grep (`update_settings`, `_schedule_settings_task`) 0건 확인

**해결 내역**
- **B13-01 (MEDIUM, P22)**: `update_settings` 저널링/검증 우회 경로 제거 — 함수 삭제 + 호출자 2곳(telegram_bot, dry_run)을 `apply_settings_updates`로 전환. 모든 설정 변경이 단일 경로 통해 저널 기록.
- **B13-02 (MEDIUM, P16)**: `_schedule_settings_task` dead code 삭제 — 호출처 0건 + 미사용 `asyncio` import 제거.
- **B13-05 (LOW, P4)**: `_pick_broker_credentials` 키움 특수 분기 제거 — 현재 선택 증권사 + `_app_key` 접미 키 기반 동적 loop로 모든 증권사 균일 처리.

**잔여 위반 (보류 — 별도 세션 가능)**
- B13-03 (LOW, P10/P16): engine_settings.py 기본값 61곳 중복 — `merged = {**DEFAULT_USER_SETTINGS, **flat}` 후에도 `merged.get(key, default)`로 기본값 하드코딩. `settings_defaults.py`와 중복.
- B13-04 (LOW, P4/P10): `"kiwoom"` 기본값 공통 로직 침투 2곳 — B13-03 해결 시 함께 처리 가능.
- B13-06 (LOW, P3): `asyncio.to_thread` 파일 I/O — async 대체재 없음, 1회 실행, 보류 권장.
- B13-07 (LOW, P24): 함수 길이 50줄 초과 2곳 — 그룹별 헬퍼 분리 필요.
- B13-08 (INFO, P10/P23): "mock" 매핑 3곳 분산 — 각각 다른 계층/목적, 보류 권장.

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
- [x] `backend/app/core/ls_connector.py` (895줄→839줄, B-16-a 완료)
- [x] `backend/app/core/ls_rest.py` (639줄→452줄, B-16-b 완료)
- [x] `backend/app/core/ls_providers.py` (198줄→190줄, B-16-b 완료)

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

**B-16-a 완료 (2026-07-21)**: 5건 해결 (B16-01~05). B16-01 _make_queue_callback() 헬퍼 추출로 connect()/_reconnect_loop() 중복 _queue_put_with_drop 중첩함수 통합 (P23/P24, kiwoom B15-02 동일 패턴), B16-02 except Exception 4곳에 exc_info=True 추가 (P23, kiwoom B15-03/B15-04 동일 패턴), B16-03 _recv_loop queue_callback None 폴백 dead code 제거 (P20/P16, kiwoom은 폴백 없이 직접 호출), B16-04 connect() 초기 연결 실패 로그 logger.warning→logger.error로 kiwoom과 일치 (P23), B16-05 subscribe_stocks/unsubscribe_stocks를 subscribe_stocks_tr/unsubscribe_stocks_tr US3 고정 래퍼로 통합 (P23/P24). test_fallback_on_message_when_no_queue 테스트 제거 (폴백 경로 제거로 무효). 검증: py_compile OK + ruff OK + pytest 263 passed(test_ls*) + 2960 passed(전체, 회귀 없음) + 런타임 기동 183ms 정상 (RuntimeWarning 없음, LS 토큰 발급·연결 정상).

**B-16-b 완료 (2026-07-22)**: 7건 해결 (B16-06~12). B16-06 except Exception as e: 7곳(line 85/174/206/267/350/457/562)에 exc_info=True 추가 (P23, kiwoom connector 12/12·kiwoom stock_rest 6/6·kiwoom order 1/1·ls connector B16-02 4/4와 일관성 — LS rest 파일은 0/7이었음), B16-07 call_tr 메서드 dead code 제거 (P16, production 호출처 0건/테스트 8건만, B15-05 get_spec 제거와 동일 패턴 — call_api가 production 사용 중이므로 중복 미사용), B16-08 get_daily_history 메서드 dead code 제거 (P16, production 0건/테스트 1건), B16-09 get_themes 메서드 dead code 제거 (P16, production 0건/테스트 1건), B16-10 buy_order/sell_order 중복 → _place_order 헬퍼 추출 (P23/P24, 104줄×2 중 차이 2곳만 → 헬퍼 1개 + 얇은 래퍼 2개, B15-10/B15-11 동일 패턴, 약 80줄 감소), B16-11 get_deposit_detail/get_balance_detail dead 분기 제거 (P16/P24, 양분기 모두 return res — 조건식 dead code, kiwoom은 조건 없이 직접 위임), B16-12 LsOrderProvider.send_order dead 변수/분기 제거 (P16/P24, ls_order_type = 1 if order_type == 'buy' else 2 → 항상 1 또는 2 → else 분기 도달 불가 → order_type 직접 분기로 단순화, 잘못된 입력 처리 버그 수정: 기존 조용히 매도 처리 → 에러 반환, 정상 입력 변화 없음). TestLsRestCallTr 8건 + test_get_daily_history_delegates 1건 + test_get_themes_delegates 1건 제거, 파일 헤더 주석 정리. 검증: py_compile 4파일 OK + ruff OK + pytest 253 passed(test_ls*, B-16-a 263 - 10건 = 253, 회귀 없음) + 2950 passed(전체, B-16-a 2960 - 10건 = 2950, 회귀 없음) + 런타임 기동 161ms 정상 (RuntimeWarning 없음, LS 토큰 발급·연결 정상, 잔존 프로세스 0건). **B-16 완료**: LS증권 구현 3개 파일 12건(B-16-a 5건 + B-16-b 7건) 전부 해결.

---

### 세션 B-17: P2 — Domain 계층 (모델/업종계산/필터)

**대상 파일** (6개, 총 1209줄)
- [x] `backend/app/domain/sector_calculator.py` (213줄→195줄)
- [x] `backend/app/domain/buy_filter.py` (336줄, 변경 없음 — 조사 결과 P원칙 위반 없음)
- [x] `backend/app/domain/sector_score.py` (200줄, 변경 없음 — 조사 결과 P원칙 위반 없음)
- [x] `backend/app/domain/sector_filter.py` (57줄, 변경 없음 — 조사 결과 P원칙 위반 없음)
- [x] `backend/app/domain/models.py` (81줄→65줄)
- [x] `backend/app/core/stock_filter.py` (322줄→269줄)

**대상 원칙**: P7, P10, P13, P16, P18, P20, P22, P23, P24

**조사 체크리스트**
- [x] P7: 계산 로직에 블로킹/DB 조회 없음 (순수 계산)
- [x] P10: 데이터 모델 SSOT
- [x] P13: 설정값 메모리 조회
- [x] P16: dead code 없음 — 3건 제거 (B17-01 미사용 파라미터 16개, B17-02 is_excluded_with_ka10100, B17-03 SortKey/_SORT_LABEL/DEFAULT_SORT_KEYS)
- [x] P18: 테스트모드와 동일한 계산
- [x] P20: 폴백/silent except 없음
- [x] P22: 파생 데이터 모델 선호, 단계 간 일관성
- [x] P23: 용어 사전 준수, 패턴 일관
- [x] P24: 단순성 기준 — compute_full_sector_summary 시그니처 30→14 파라미터 감소 (B17-01)

**검증**
- [x] `pytest backend/tests -k "sector or buy_filter or stock_filter or domain"` 통과 (376 passed)
- [x] 잔여 DB 직접 조회 / 동기 I/O grep 추가 인스턴스 없음

**B-17 완료 (2026-07-22)**: 3건 해결 (B17-01~03). B17-01 compute_full_sector_summary 미사용 파라미터 16개 제거 (P16/P24, 과거 매수 타겟 생성까지 수행했던 시절의 잔재 — 현재는 build_buy_targets_from_settings가 별도 수행, 시그니처 30→14 파라미터로 감소, Literal import 제거, sector_data_provider.py get_sector_summary_inputs에서 latest_index 키 제거 연동), B17-02 is_excluded_with_ka10100 함수 제거 (P16, production 호출처 0건/테스트 11건만, is_excluded가 production 사용 중, B15-05/B16-07과 동일 패턴, TestIsExcludedWithKa10100 9건 제거), B17-03 SortKey/_SORT_LABEL/DEFAULT_SORT_KEYS 상수 제거 (P16, 외부 import 0건/파일 내 참조도 없음, Literal import 제거). subagent 조사에서 간접 호출 헬퍼(create_buy_targets/calculate_boost_score/check_stock_guards/rank_to_tiered_score 등)를 dead code로 잘못 분류한 것을 바로잡음 — P16은 "실제 실행 경로에 연결되어 있는가"가 기준이므로 build_buy_targets_from_settings → create_buy_targets → 헬퍼 호출 체인은 살아있는 경로. 검증: py_compile 12파일 OK + ruff OK + pytest 376 passed(sector/buy_filter/stock_filter/domain) + 2941 passed(전체, B-16-b 2950 - is_excluded_with_ka10100 9건 = 2941, 회귀 없음) + 런타임 기동 123ms 정상 (RuntimeWarning 없음, 1356종목 로드·업종순위 재계산·LS/키움 토큰 발급 정상, 잔존 프로세스 0건). **B-17 완료**: Domain 계층 6개 파일 3건 전부 해결.

---

### 세션 B-18: P2 — 스케줄러 및 장마감 파이프라인

> **분할 강력 권장**: 총 3150줄 (초대형 2개). B-18-a (market_close_pipeline 1407줄) / B-18-b (daily_time_scheduler 1506줄 + data_manager 237줄) 분할.

**대상 파일** (3개, 총 3150줄)
- [x] `backend/app/services/market_close_pipeline.py` (1407줄, 초대형) — dead code 없음, 18개 함수 모두 살아있는 경로
- [x] `backend/app/services/daily_time_scheduler.py` (1506줄→1443줄, 초대형) — 4건 dead code 제거
- [x] `backend/app/services/data_manager.py` (237줄→45줄, 대형) — 3건 dead code 제거

**대상 원칙**: P1, P2, P5, P7, P8, P9, P11, P14, P16, P19, P20, P23, P24

**조사 체크리스트**
- [x] P1: 단일 이벤트 루프 — 위반 없음
- [x] P2: 모든 I/O `async def` — 위반 없음
- [x] P5: 직접 호출 체인 — 위반 없음
- [x] P7: 배치 연산 중 실시간 틱 차단 금지 — 위반 없음
- [x] P8: 배치 파이프라인으로서 실시간과 분리 — 위반 없음
- [x] P9: 파이프라인 독립성 — 위반 없음
- [x] P11: `asyncio.call_later()` 기반, 폴링 없음 — 위반 없음
- [x] P14: 멀티스레드 없음 — 위반 없음
- [x] P16: dead code 없음 — 6건 제거 (B18-01~05 + B18-06 연동)
- [x] P19: `await` 누락 없음 — 런타임 기동 검증 OK
- [x] P20: 폴백/silent except 없음 — 1건 제거 (B18-06, _load_broker_settings 제거로 해결)
- [x] P23: 용어 사전 준수, 패턴 일관 — 위반 없음
- [ ] P24: 단순성 기준 (1407줄/1443줄 → 분할 필수) — **이월**: 파일 분할은 대형 작업이므로 별도 세션

**검증**
- [x] `pytest backend/tests -k "market_close or scheduler or data_manager"` 통과 (285 passed)
- [x] `python -W error::RuntimeWarning main.py` 기동 검증 (95ms 정상, RuntimeWarning 없음)
- [x] 잔여 폴링 / `threading.Thread` / dead code grep 추가 인스턴스 없음

**B-18 완료 (2026-07-22)**: 6건 해결 (B18-01~06). B18-01 `get_account_profit_rate` 제거 (P16, 계좌 수익률 조회 kt00018, production 0건/테스트 7건). B18-02 `get_main_account_info` 제거 (P16, 계좌 메인 정보 조회 kt00001, production 0건/테스트 7건). B18-03 `_freeze_krx_amt29_baseline` 제거 (P16, body가 pass만 있는 stub, production 0건/테스트 1건). B18-04 `_apply_detail_to_entry` 제거 (P16, ka10086 응답 처리 헬퍼, production 0건/테스트 6건). B18-05 `_fire_ws_disconnect_only` + `_ws_disconnect_only` 제거 (P16, WS 구독 해제 전용, _fire_ws_disconnect_only production 0건/테스트 1건, _ws_disconnect_only도 _fire에서만 호출되어 함께 제거/테스트 1건 — subagent가 _ws_disconnect_only를 잘못 "살아있는 경로"로 판정한 것을 직접 grep으로 바로잡음). B18-06 `_load_broker_settings` 제거 (P16/P20, get_main_account_info에서만 호출되어 함께 제거, silent `except Exception: return None`도 함께 해결). data_manager.py 237줄→45줄, daily_time_scheduler.py 1506줄→1443줄. subagent 병렬 조사로 3개 파일 75개 함수 전체 추적, market_close_pipeline.py 18개 함수는 dead code 없음(_step6 의도적 누락 — 5단계→7단계 직접 진행). 검증: py_compile 5파일 OK + ruff OK + pytest 285 passed(market_close/scheduler/data_manager) + 2913 passed(전체, B-17 2941 - 제거 테스트 28건 = 2913, 회귀 없음) + 런타임 기동 95ms 정상 (RuntimeWarning 없음, 168ms 연산 준비·LS/키움 토큰 발급·LS 연결 정상, 잔존 프로세스 0건). **P24 파일 길이 초과 이월**: market_close_pipeline.py(1407줄)/daily_time_scheduler.py(1443줄) 분할은 대형 작업이므로 별도 세션. **B-18 완료**: 스케줄러 및 장마감 파이프라인 3개 파일 6건 전부 해결.

---

### 세션 B-19: P2 — WS 구독 제어 및 업종 데이터 제공자

**대상 파일** (2개, 총 572줄)
- [x] `backend/app/services/ws_subscribe_control.py` (262줄→230줄)
- [x] `backend/app/services/sector_data_provider.py` (309줄→282줄)

**대상 원칙**: P4, P5, P7, P10, P11, P13, P16, P20, P23, P24

**조사 체크리스트**
- [x] P4: 증권사 이름 침투 없음
- [x] P5: 직접 호출 체인
- [x] P7: 구독 제어에 블로킹 없음
- [x] P10: 업종 데이터 SSOT
- [x] P11: 이벤트 기반
- [x] P13: 설정 메모리 조회
- [x] P16: dead code 없음 — B19-01 `stop_industry` 스텁 제거, B19-02 `on_setting_changed` no-op 제거
- [x] P20: 폴백/silent except 없음 — B19-04 try/except 중복 제거
- [x] P23: 용어 사전 준수, 패턴 일관
- [x] P24: 단순성 기준 — B19-03 루프 중복 제거, B19-04 try/except 중복 제거

**검증**
- [x] `pytest backend/tests -k "ws_subscribe or sector_data"` 통과 (62 passed)
- [x] `python -W error::RuntimeWarning main.py` 기동 검증 (152ms 정상, RuntimeWarning 없음)
- [x] 잔여 증권사 접두사 / 폴링 grep 추가 인스턴스 없음

**B-19 완료 (2026-07-22)**: 4건 해결 (B19-01~04). B19-01 `stop_industry` 제거 (P16, 하위 호환용 스텁, body가 return만, production 2건/테스트 5건 → ws_subscribe.py 호출처 `get_subscribe_status()` 직접 반환으로 수정, 실패 케이스 테스트 2건 제거). B19-02 `on_setting_changed` 제거 (P16, `quote_auto_subscribe` 브랜치가 pass만, no-op, production 1건/테스트 0건 → engine_service.py의 `_apply_ws_subscribe_control_change`도 no-op이므로 함께 제거, 68행 호출처도 제거). B19-03 `get_buy_targets_sector_stocks` 루프 중복 제거 (P24, buy_targets/blocked_targets 루프 19개 필드 동일 반복 → `_build_target_entry` 헬퍼 추출). B19-04 `_on_filter_settings_changed` try/except 중복 제거 (P20/P24, `recompute_sector_summary_now`가 내부에서 이미 예외 처리 → 외부 try/except 제거, `test_exception_logged` 테스트 1건 제거). ws_subscribe_control.py 262줄→230줄, sector_data_provider.py 309줄→282줄. subagent 병렬 조사로 2개 파일 19개 함수 전체 추적. 검증: py_compile 5파일 OK + ruff OK + pytest 62 passed(ws_subscribe/sector_data/web_ws_routes/engine_service) + 2910 passed(전체, B-18 2913 - 제거 테스트 3건 = 2910, 회귀 없음) + 런타임 기동 152ms 정상 (RuntimeWarning 없음, 1356종목 로드·업종순위 재계산 완료·LS/키움 토큰 발급·LS 연결 정상, 잔존 프로세스 0건). **B-19 완료**: WS 구독 제어 및 업종 데이터 제공자 2개 파일 4건 전부 해결.

---

### 세션 B-20: P3 — 알림 (Telegram / Notification)

**대상 파일** (3개, 총 668줄)
- [x] `backend/app/services/telegram_bot.py` (527줄→505줄)
- [x] `backend/app/services/telegram.py` (43줄, 변경 없음)
- [x] `backend/app/services/notification_worker.py` (98줄, 변경 없음 — app.py에서 호출 추가)

**대상 원칙**: P2, P5, P14, P16, P19, P20, P21, P23, P24

**조사 체크리스트**
- [x] P2: HTTP I/O `async def` (`httpx.AsyncClient`) — 모든 HTTP 요청 비동기, 동기 `requests` 없음
- [x] P5: 직접 호출 체인 — EventBus/옵서버 패턴 없음
- [x] P14: 멀티스레드 없음 — `asyncio.create_task` 2건(telegram_bot:71, notification_worker:38)은 장기 실행 백그라운드 폴링/워커로 schedule_engine_task 전환 부적합, 보류
- [x] P16: dead code 없음 — B20-01 `stop` 제거, B20-02 `get_poll_ok_age_sec` 제거
- [x] P19: `await` 누락 없음 — create_task의 await 누락은 의도적(fire-and-forget)
- [x] P20: 폴백/silent except 없음 — `or ""` 패턴은 외부 입력 None 정규화로 P20 위반 아님
- [x] P21: 중요 상태 변화가 알림으로 전달됨 — B20-03 app.py shutdown에 NotificationWorker.shutdown() 호출 추가
- [x] P23: 용어 사전 준수, 패턴 일관 — "업종"/"종목"/"매수 후보" 용어 사용
- [x] P24: 단순성 기준 — 함수 50줄 이하, 불필요한 추상화 없음

**검증**
- [x] `pytest backend/tests -k "telegram or notification"` 통과 (146 passed)
- [x] `python -W error::RuntimeWarning main.py` 기동 검증 (440ms 정상, RuntimeWarning 없음)
- [x] 잔여 동기 `requests` / dead code grep 추가 인스턴스 없음

**B-20 완료 (2026-07-22)**: 3건 해결 (B20-01~03). B20-01 `stop` 제거 (P16, 동기 취소 전용 메서드, production 호출처 0건/테스트 4건 → stop_async가 유일 종료 경로, TestStop 4건 제거). B20-02 `get_poll_ok_age_sec` 제거 (P16, 폴링 성공 경과 초 반환, production 호출처 0건/테스트 2건 → `_last_poll_ok_mon` 필드도 함께 제거, TestGetPollOkAgeSec 2건 + test_stop_async_clears_poll_ok_mon 1건 + assertion 2건 제거, import time 제거). B20-03 app.py shutdown에 `NotificationWorker.get_instance().shutdown()` 호출 추가 (P21, stop_engine() 이후 큐 잔량 알림 처리, 종료 시 알림 누락 방지). telegram_bot.py 527줄→505줄. subagent 병렬 조사로 3개 파일 28개 함수 전체 추적. 검증: py_compile 5파일 OK + ruff OK + pytest 146 passed(telegram_bot/telegram/notification_worker) + 2903 passed(전체, B-19 2910 - 제거 테스트 7건 = 2903, 회귀 없음) + 런타임 기동 440ms 정상 (RuntimeWarning 없음, 1356종목 로드·업종순위 재계산 완료·LS/키움 토큰 발급·LS 연결 정상, 잔존 프로세스 0건). **B-20 완료**: 알림 Telegram/Notification 3개 파일 3건 전부 해결.

---

### 세션 B-21: P3 — 기타 Core 유틸

**대상 파일** (11개, 총 1951줄) — 3서브세션 분할 (B-21-a/b/c)
- [x] `backend/app/core/journal.py` (324줄→123줄, B-21-a 완료)
- [x] `backend/app/core/logger.py` (426줄→415줄, B-21-b 완료 — get_logger deprecated 제거)
- [x] `backend/app/core/trading_calendar.py` (406줄, B-21-c — DEAD CODE 없음, P20/P24/P10 위반은 별도 세션 대상)
- [x] `backend/app/core/stock_classification_data.py` (238줄→233줄, B-21-c 완료 — load_custom_data_readonly 제거)
- [x] `backend/app/core/sector_mapping.py` (99줄→70줄, B-21-c 완료 — get_merged_sector 제거)
- [x] `backend/app/core/sector_stock_cache.py` (140줄→125줄, B-21-c 완료 — save_filter_summary_meta_cache 제거, load는 살아있는 경로 유지)
- [x] `backend/app/core/lock_manager.py` (146줄, B-21-b — 살아있는 경로 확인, 수정 없음)
- [x] `backend/app/core/encryption.py` (87줄→59줄, B-21-b 완료 — SENSITIVE_KEYS/encrypt_sensitive/decrypt_sensitive 제거)
- [ ] `backend/app/core/memory_monitor.py` (52줄, 중형, 위반 없음)
- [ ] `backend/app/core/constants.py` (14줄, 소형, 위반 없음)
- [ ] `backend/app/core/logging_config.py` (19줄, 소형, 위반 없음)

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

**B-21-a 완료 (2026-07-22)**: journal.py dead code 12개 함수 제거 (P16). production 호출처 0건인 함수 12개 제거: `_get_conn`/`_ensure_loaded`/`_migrate_from_json` (no-op 잔재), `close_db_connection` (no-op, database.py 중복), `_read_all_entries` (삭제 함수에서만 호출), `_perform_compaction` (내부 호출 없음), `record_fill_event` (production 호출 0건), `oms_get_pending_orders`/`oms_update_order_status`/`oms_get_next_seq`(+`_next_seq`) (OMS API, production 호출 0건), `replay_journal`/`clear_journal`/`get_journal_stats` (production 호출 0건). 유지: start/stop_consumer_task(app.py 호출), record_settings_change(settings_store.py 호출), record_order_request(trading.py 호출), _append_entry(내부 호출), JournalEventType/JournalEntry. journal.py 324줄→123줄, test_journal.py 502줄→169줄 (삭제 테스트 26건). 검증: py_compile + ruff OK + pytest 2877 passed(전체, 회귀 없음) + 런타임 기동 192ms 정상 (RuntimeWarning 없음) + 잔존 프로세스 0건. **B-21-a 완료**: journal.py dead code 전부 해결. B-21-b(logger+encryption+lock_manager), B-21-c(trading_calendar+classification+mapping+cache) 잔여.

**B-21-b 완료 (2026-07-22)**: logger.py + encryption.py dead code 제거 (P16). logger.py: `get_logger` 함수 제거 (deprecated, production 호출처 0건, test_logger.py만 참조). `except: pass` 5건 유지 — 로그 싱크 I/O 실패 시 앱 크래시 방지용 정당한 처리 (P20 위반 아님, `logger.warning`으로 바꾸면 무한 재귀). `_async_file_writer_loop` 78줄 유지 — 단일 응집 asyncio 태스크 루프, 분할 시 상태 공유 복잡도 증가 (P24). encryption.py: `SENSITIVE_KEYS`/`encrypt_sensitive`/`decrypt_sensitive` 제거 (production 호출처 0건, test_encryption.py만 참조). 유지: `_get_fernet`/`encrypt_value`/`decrypt_value` (engine_settings·telegram_bot·settings_file 호출). "Fernet 없으면 평문 반환" 패턴 유지 — 보안 설계 결정, 규칙 0-4(핵심 로직 변경 시 UI 기준 설명 + 승인) 해당 → B21-01로 보류 등록 (사용자 승인 대기). lock_manager.py: **태스크 노트 "전체 파일 dead code" 주장은 오류** — main.py가 5개 심볼 활발히 사용 (`acquire_lock`/`read_lock_pid`/`format_duplicate_message`/`register_cleanup`/`LOCK_FILE_PATH`), `release_lock`도 `register_cleanup` 내부 cleanup 핸들러에서 호출 → 살아있는 경로, dead code 없음, 수정 없음. logger.py 426줄→415줄, test_logger.py 423줄→401줄 (삭제 2건), encryption.py 87줄→59줄, test_encryption.py 270줄→145줄 (삭제 15건). 검증: py_compile + ruff OK + pytest 57 passed(logger+encryption) + 2860 passed(전체, 이전 2877 - 17건 = 2860, 회귀 없음) + 런타임 기동 126ms 정상 (RuntimeWarning 없음, 1356종목 로드·업종순위 재계산 완료·LS/키움 토큰 발급·LS 연결 정상·종료 시 잠금 파일 삭제 정상) + 잔존 프로세스 0건. **B-21-b 완료**: logger.py + encryption.py dead code 전부 해결. lock_manager.py는 살아있는 경로 확인 (태스크 노트 오류 정정). B-21-c(trading_calendar+classification+mapping+cache) 잔여.

**B-21-c 완료 (2026-07-22)**: stock_classification_data.py + sector_mapping.py + sector_stock_cache.py dead code 제거 (P16). **DEAD 3건 제거**: (1) `stock_classification_data.py` — `load_custom_data_readonly` 제거 (하위 호환성용 빈 데이터 로드, production 호출 0건, 테스트만 참조). (2) `sector_mapping.py` — `get_merged_sector` 제거 (단일 종목 업종 조회, production 호출 0건, `get_merged_sectors_batch` 배치 버전으로 대체됨, 테스트만 9회 참조) + `get_merged_sectors_batch` docstring에서 `get_merged_sector` 역사적 언급 제거. (3) `sector_stock_cache.py` — `save_filter_summary_meta_cache` 제거 (filter_summary 메타 저장, production 호출 0건). **유지**: `load_filter_summary_meta_cache` (app.py:74에서 await 호출 — 살아있는 경로), `StockClassificationData` (load_custom_data가 반환, stock_classification.py:194·ws.py:72에서 .sectors/.stock_moves 속성 사용 — 살아있는 경로). **trading_calendar.py**: DEAD CODE 없음 (모든 심볼이 ALIVE 또는 ALIVE 체인의 INTERNAL) → B-21-c 대상 아님. P20 위반 2건(줄 311 폴백, 줄 211 silent except) + P24 위반 1건(_compute_holidays 104줄) + P10 위반 1건(_KST 중복 정의)은 별도 세션 대상. **사전조사 중 subagent 분류 오류 2건 정정**: (1) StockClassificationData — DEAD로 분류했으나 load_custom_data가 반환하는 살아있는 경로 → 유지. (2) load_filter_summary_meta_cache — DEAD로 분류했으나 app.py:74에서 await 호출 → 유지 (제거 후 복구). stock_classification_data.py 238줄→233줄, sector_mapping.py 99줄→70줄, sector_stock_cache.py 140줄→125줄, test_stock_classification_data.py 298줄→292줄 (삭제 1건), test_sector_mapping.py 304줄→185줄 (삭제 9건 + docstring "3함수"→"2함수" 정리). 검증: py_compile + ruff OK + pytest 59 passed(관련 3파일) + 2850 passed(전체, 이전 2860 - 10건 = 2850, 회귀 없음) + 런타임 기동 123ms 정상 (RuntimeWarning 0건, 1356종목 로드·업종순위 재계산 완료·필터 요약 메타 캐시 로드 완료·LS/키움 토큰 발급·LS 연결 정상) + 잔존 프로세스 0건. **B-21-c 완료**: classification+mapping+cache dead code 전부 해결. **B-21 전체 완료**: B-21-a(journal 12건) + B-21-b(logger 1건+encryption 3건) + B-21-c(classification 1건+mapping 1건+cache 1건) = 총 19건 dead code 제거.

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

### 세션 B-23: P3 — 테스트 품질 점검 (분할: B-23-a/b/c/d)

> **분할 사유**: 테스트 파일 65개 / 35,673줄 / 테스트 함수 약 2844개로 단일 세션 전수 점검 불가 (규칙 0-1). 메타 점검(B-23-a) + 파일 규모별 세부 점검 3분할(B-23-b/c/d).

**대상 파일** (65개, `backend/tests/` 전체 — 계획 문서의 67개는 추정치, 실측 65개)

**대상 원칙**: P16, P18, P19, P22, P23, P24

**조사 체크리스트**
- [x] 테스트 커버리지 현황 파악 (모듈별) — B-23-a 완료
- [ ] P16: 테스트가 살아있는 경로를 검증하는지 (dead code 테스트 아님) — B-23-b/c/d 이월
- [~] P18: 테스트모드 동등성 검증 존재 여부 — B-23-a 키워드 스캔(7개 파일), 심층은 B-23-b/c/d
- [x] P19: `RuntimeWarning(coroutine never awaited)` 감지 테스트 — B-23-a 완료 (감지 테스트 부재, 4개 파일에서 "방지" 주석만)
- [~] P22: 데이터 정합성 대조(reconciliation) 테스트 — B-23-a 키워드 스캔(5개 파일), 심층은 B-23-b/c/d
- [ ] P23: 용어/에러/비동기/네이밍/상수 일관성 점검 — B-23-b/c/d 이월
- [ ] P24: 단순성 점검 (불필요한 추상화, 복잡도) — B-23-b/c/d 이월
- [x] 미커버 모듈 식별 (테스트 파일 없는 소스 파일) — B-23-a 완료 (17개 모듈 전용+간접 0건)
- [x] 통합 테스트 vs 단위 테스트 비율 — B-23-a 완료 (integration 2개, 단위 63개; async 1482 / sync 1362)

#### B-23-a 메타 점검 결과 (완료)

**규모**: 테스트 파일 65개 / 소스 파일 103개 / 테스트 코드 35,673줄 / 테스트 함수 약 2844개 (async 1482, sync 1362)

**P19 RuntimeWarning 감지 테스트**: 부재. 4개 파일(`test_web_app`, `test_pipeline_compute`, `test_trading`, `test_daily_time_scheduler`)에서 mock 코루틴 close를 통한 RuntimeWarning "방지" 주석만 존재. 감지 자체를 검증하는 테스트 없음 → B-23-b/c/d에서 보완 권장.

**P18 테스트모드 동등성**: 7개 파일에서 키워드 스캔(`test_telegram`, `test_engine_ws`, `test_pipeline_compute`, `test_buy_order_executor`, `test_engine_bootstrap`, `test_risk_manager`, `test_trading`). 심층 검증 내용은 B-23-b/c/d에서 확인.

**P22 reconciliation**: 5개 파일에서 키워드 스캔(`test_engine_sector_confirm`, `test_settlement_engine`, `test_engine_settings`, `test_daily_time_scheduler`, `test_settlement_verification`). 심층은 B-23-b/c/d.

**미커버 모듈** (전용 테스트 + 간접 import 모두 0건, 17개):
`engine_config`, `engine_strategy_core`, `engine_utils`, `engine_radar`, `auto_trading_effective`, `ws_subscribe_control`, `broker_factory`, `broker_registry`, `broker_connector`, `trade_mode`, `settings_defaults`, `memory_monitor`, `logging_config`, `sector_stock_cache`, `sector_filter`, `pipeline_compute_tick_handlers`, `json_utils`

**간접 import만 있는 모듈** (전용 테스트 없으나 다른 테스트에서 import):
`engine_state`(9), `core_queues`(6), `database`(4), `engine_service`(3), `constants`(3), `broker_urls`(2), `broker_providers`(2), `engine_lifecycle`(1), `order_interval`(1), `kiwoom_account_parsing`(1), `engine_account_broadcast`(1), `db_writer`(1)

**웹 라우트 커버리지**: 전용 테스트 없는 라우트 — `stock_detail`, `trade`, `deps`. 나머지 라우트(account/auth/market/settlement/status/ws_orders/ws_settings/ws_subscribe)는 `test_web_routes`에서 통합 커버 추정(각 1개 파일).

**통합 vs 단위 비율**: integration 명시 2개(`test_sector_calculator_integration`, `test_settings_file_integration`), 단위 63개.

#### B-23-b 세부 점검 — 대형 파일 (1000줄+, 9개) — 완료
- [x] P16/P23/P24/P18/P22 점검
- 대상: `test_daily_time_scheduler`(2285), `test_pipeline_compute`(1540), `test_telegram_bot`(1244), `test_market_close_pipeline`(1228), `test_trade_history`(1119), `test_ls_connector`(1090), `test_engine_sector_confirm`(1068), `test_engine_loop`(1059), `test_buy_order_executor`(1001)

##### B-23-b 점검 결과

**P16 (살아있는 경로) — 위반 1건**
- `test_trade_history.py:609-642` (`TestCalcAvgBuyPrice`): `_calc_avg_buy_price` 함수(`trade_history.py:295`)가 소스에 정의만 있고 백엔드 전체에서 호출 경로 없음 (dead code). 이 dead code를 테스트하고 있음 → P16 위반. 수정 필요: `_calc_avg_buy_price` 함수 제거 + 테스트 제거 (별도 세션 승인 필요).
- 나머지 8개 파일: 위반 없음. 모든 테스트가 실제 소스의 살아있는 함수/클래스를 참조. 제거된 기능(`sector_confirmed` 확정, `get_merged_sector`) 테스트 없음.
  - 주의: `test_engine_sector_confirm.py` 파일명의 "sector_confirm"은 업종 재계산 기능을 의미하며, 제거된 "sector_confirmed 확정" 개념과 무관함 (오해 주의).

**P23 (일관성) — 위반 0건**
- 모든 9개 파일에서 용어 사전 준수 ("섹터"/"주식"/"바이 리스트" 사용 없음, "업종"/"종목"/"매수 후보" 올바르게 사용).
- 코드 식별자(`sector`, `stock`, `buy`)는 ARCHITECTURE.md 부록 L/M 예외 조항에 따라 허용.
- 네이밍/에러/비동기/상수 패턴 파일 내 일관적.

**P24 (단순성) — 위반 7건**
- 파일 길이 초과 (500줄 기준): 9개 파일 전부 초과 (1001~2285줄). 단, 테스트 파일은 기능별 그룹화된 클래스 단위이므로 예외적 허용 범위 검토 필요.
- 함수 길이 초과 (50줄 기준) — 4건:
  - `test_pipeline_compute.py:1391-1449` `test_phase1_marks_threshold_passed` (59줄)
  - `test_market_close_pipeline.py:1026-1079` `test_5d_safety_net_blocks_current_trading_day_bar` (54줄)
  - `test_market_close_pipeline.py:1082-1136` `test_5d_deletes_future_bars` (55줄)
  - `test_buy_order_executor.py:535-585` `test_same_buyable_codes_different_order_skips` (51줄)
- 중복 테스트 로직 (fixture/파라미터화 가능) — 3건:
  - `test_daily_time_scheduler.py:511-820` `TestIsOrderBlockedByTime` vs `TestGetOrderTimeBlockStatus` 버퍼 테스트 중복 (약 17개 메서드)
  - `test_engine_loop.py:411-1054` 19개 테스트에서 동일한 16개 patch 블록 반복
  - `test_market_close_pipeline.py:973-1228` 5일봉 파이프라인 테스트 6개에서 13-19개 patch 문 중복
  - 기타: `test_telegram_bot.py:596-787` TestHandleCommand 21개 테스트 명령어 라우팅 중복, `test_engine_sector_confirm.py` 9개 테스트 설정 캐시 중복, `test_ls_connector.py` 구독/해제 테스트 그룹 중복, `test_buy_order_executor.py` 40개+ 테스트 patch 설정 중복

**P18 (테스트모드 동등성) — 부분**
- 모드별 차이 검증 있음: `test_trade_history.py` (수수료/세금/보관기한 test vs real 6개 테스트), `test_pipeline_compute.py` (test_mode/real_mode 개별 테스트 3개).
- "동등성" 명시적 검증 부재: "로직은 동일하고 돈 I/O만 다르다"를 검증하는 테스트 없음.
- `test_buy_order_executor.py`/`test_engine_loop.py`: 모든 테스트가 test_mode=True로만 실행, 실전모드 경로 검증 부족.
- 나머지 5개 파일: 해당 없음 (테스트모드 구분 없는 영역).

**P22 (데이터 정합성) — 부분**
- `test_daily_time_scheduler.py`: 4건 reconciliation 테스트 존재 (멱등성 가드 3건 + 캐시 날짜 불일치 검증 1건) — 양호.
- `test_engine_sector_confirm.py:1032`: 주석에 "(P22 정합성)" 언급만 있고 실제 대조 검증 로직 없음.
- 나머지 7개 파일: reconciliation(대조) 검증 테스트 전무.

**B-23-b 발견 위반 요약**
| 원칙 | 위반 건수 | 주요 내용 |
|------|----------|----------|
| P16 | 1건 | `_calc_avg_buy_price` dead code 테스트 (test_trade_history) |
| P23 | 0건 | 전부 준수 |
| P24 | 7건 | 함수 길이 초과 4건 + 중복 로직 3건 (파일 길이 초과는 테스트 파일 예외 검토) |
| P18 | 부분 | 모드별 차이 검증은 있으나 동등성 명시적 검증 부재 |
| P22 | 부분 | 1개 파일만 양호, 나머지 reconciliation 테스트 부재 |

**수정 권장 순위** (별도 세션 승인 필요):
1. (P16) `_calc_avg_buy_price` dead code 제거 + 테스트 제거 — `trade_history.py:295` + `test_trade_history.py:609-642`
2. (P24) 함수 길이 초과 4건 — 헬퍼 추출 또는 단순화
3. (P24) 중복 로직 — fixture 추출 (test_engine_loop 19개 patch, test_market_close_pipeline 5일봉 6개, test_daily_time_scheduler 버퍼 17개)
4. (P18/P22) 동등성/reconciliation 테스트 보완 — 신규 테스트 추가

#### B-23-c 세부 점검 — 중형 파일 (400-1000줄, 20개)
- [x] P16/P23/P24/P18/P22 점검 (2026-07-22 완료, 코드 수정 없음 — 점검/조사 작업)
- 대상: `test_kiwoom_connector`(985), `test_kiwoom_rest`(878), `test_kiwoom_providers`(827), `test_settings_store`(807), `test_trading`(769), `test_kiwoom_stock_rest`(755), `test_web_ws_manager`(723), `test_web_ws_routes`(700), `test_buy_filter`(680), `test_engine_settings`(657), `test_broker_router`(624), `test_web_routes`(581), `test_web_stock_classification`(580), `test_connector_manager`(561), `test_ls_rest`(560), `test_ls_providers`(560), `test_engine_ws`(555), `test_engine_cache`(513), `test_risk_manager`(512), `test_sector_calculator`(488)

**B-23-c 점검 결과 상세** (20개 파일, 총 13,315줄)

| 파일 | 줄 수 | P16 | P23 | P24 | P18 | P22 |
|------|-------|-----|-----|-----|-----|-----|
| test_kiwoom_connector | 985 | 0건 | 0건 | 2건 (파일 길이, 중복 patch) | 해당 없음 | 해당 없음 |
| test_kiwoom_rest | 878 | 0건 | 0건 | 2건 (파일 길이, 중복 patch) | 해당 없음 | 해당 없음 |
| test_kiwoom_providers | 827 | 0건 | 0건 | 2건 (파일 길이, 중복 patch) | 해당 없음 | 해당 없음 |
| test_settings_store | 807 | 0건 | 0건 | 2건 (파일 길이, 중복 dict) | 해당 없음 | 부분 (_payload_values_equal) |
| test_trading | 769 | 0건 | 0건 | 3건 (파일 길이, 중복 patch 10회+, 가독성) | 부분 (단순 test_mode=True만) | 해당 없음 |
| test_kiwoom_stock_rest | 755 | 0건 | 0건 | 0건 (파일 길이 기록만) | 해당 없음 | 해당 없음 |
| test_web_ws_manager | 723 | 0건 | 0건 | 0건 (파일 길이 기록만) | 해당 없음 | 해당 없음 |
| test_web_ws_routes | 700 | 0건 | 0건 | 0건 (파일 길이 기록만) | 해당 없음 | 해당 없음 |
| test_buy_filter | 680 | 0건 | 0건 | 0건 (파일 길이 기록만) | 해당 없음 | 해당 없음 |
| test_engine_settings | 657 | 0건 | 0건 | 0건 (파일 길이 기록만) | 해당 없음 | 해당 (전역 상태 백업/복원) |
| test_broker_router | 624 | 0건 | 0건 | 1건 (파일 길이, patch 24회) | 해당 없음 | 해당 없음 |
| test_web_routes | 581 | 0건 | 0건 | 1건 (파일 길이, patch 14회) | 해당 없음 | 해당 없음 |
| test_web_stock_classification | 580 | 0건 | 0건 | 1건 (파일 길이, patch 6회) | 해당 없음 | 해당 없음 |
| test_connector_manager | 561 | 0건 | 0건 | 1건 (파일 길이) | 해당 없음 | 해당 없음 |
| test_ls_rest | 560 | 0건 | 0건 | 1건 (파일 길이) | 해당 없음 | 해당 없음 |
| test_ls_providers | 560 | 0건 | 0건 | 1건 (파일 길이) | 해당 없음 | 해당 없음 |
| test_engine_ws | 555 | 0건 | 0건 | 1건 (파일 길이) | 부분 (각 모드 동작만) | 해당 없음 |
| test_engine_cache | 513 | 0건 | 0건 | 1건 (파일 길이) | 부분 (각 모드 동작만) | 해당 없음 |
| test_risk_manager | 512 | 0건 | 0건 | 1건 (파일 길이) | 부분 (각 모드 동작만, 31개) | 해당 없음 |
| test_sector_calculator | 488 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |

**B-23-c 발견 위반 요약**
| 원칙 | 위반 건수 | 주요 내용 |
|------|----------|----------|
| P16 | 0건 | 전부 양호 (제거된 함수 테스트 없음, dead code 없음) |
| P23 | 0건 | 전부 준수 (금지 용어 "섹터"/"주식"/"바이 리스트"/"홀딩" 사용 없음) |
| P24 | 19건 | 파일 길이 500줄 초과 19개 (테스트 파일 예외 검토) + 중복 patch 패턴 8개 파일 (test_trading 10회+, test_broker_router 24회, test_web_routes 14회, test_web_stock_classification 6회, test_kiwoom_connector/rest/providers, test_settings_store) |
| P18 | 부분 4건 | test_trading(단순 test_mode=True만), test_engine_ws/engine_cache/risk_manager(각 모드 동작만 검증, 동등성 명시 검증 부재) |
| P22 | 부분 2건 | test_settings_store(_payload_values_equal 유틸 테스트), test_engine_settings(전역 상태 백업/복원). 시스템 레벨 reconciliation(메모리 vs DB, 캐시 vs 원본) 테스트 부재 |

**수정 권장 순위** (별도 세션 승인 필요):
1. (P24) 중복 patch 패턴 conftest.py fixture 추출 — test_trading(10회+), test_broker_router(24회), test_web_routes(14회) 우선
2. (P18) test_mode=True/False 동등성 명시 검증 테스트 추가 — test_trading, test_engine_ws, test_engine_cache, test_risk_manager
3. (P22) 시스템 레벨 reconciliation 테스트 보완 — 메모리 vs DB, 캐시 vs 원본 비교
4. (P24) 파일 길이 500줄 초과 19개 — 테스트 파일 예외 검토 후 분할 여부 결정

#### B-23-d 세부 점검 — 소형 파일 (400줄-, 36개) — 완료
- [x] P16/P23/P24/P18/P22 점검 (2026-07-22 완료, 코드 수정 없음 — 점검/조사 작업)
- 대상 (36개, 총 10,724줄): `test_engine_ws_fill_followup`(77), `test_data_manager`(110), `test_encryption`(144), `test_engine_ws_reg`(146), `test_journal`(169), `test_sector_mapping`(185), `test_lock_manager`(219), `test_engine_bootstrap`(223), `test_circuit_breaker`(231), `test_sector_calculator_integration`(243), `test_settings_boost_order_ratio`(244), `test_telegram`(250), `test_engine_symbol_utils`(252), `test_engine_account`(253), `test_pipeline_gateway`(259), `test_notification_worker`(274), `test_trading_calendar`(276), `test_stock_classification_data`(292), `test_settings_file_integration`(294), `test_kiwoom_order`(295), `test_engine_account_notify`(307), `test_sector_data_provider`(318), `test_broker_change`(331), `test_dry_run`(333), `test_stock_tables`(356), `test_dry_run_fill_event`(380), `test_stock_filter`(388), `test_web_app`(401), `test_logger`(407), `test_settlement_verification`(410), `test_engine_ws_parsing`(411), `test_sector_score`(413), `test_engine_account_rest`(441), `test_engine_ws_dispatch`(450), `test_engine_snapshot`(470), `test_settlement_engine`(472)

**B-23-d 점검 결과 상세** (36개 파일, 총 10,724줄)

| 파일 | 줄 수 | P16 | P23 | P24 | P18 | P22 |
|------|-------|-----|-----|-----|-----|-----|
| test_engine_ws_fill_followup | 77 | 0건 | 0건 | 부분 (refresh/sell mock 7회 반복) | 해당 없음 | 해당 없음 |
| test_data_manager | 110 | 0건 | 0건 | 부분 (mock_state patch 5회 반복) | 해당 없음 | 해당 없음 |
| test_encryption | 144 | 0건 | 0건 | 부분 (get_settings patch 6회 반복) | 해당 없음 | 해당 없음 |
| test_engine_ws_reg | 146 | 0건 | 0건 | 부분 (empty/invalid 패턴 반복) | 해당 없음 | 해당 없음 |
| test_journal | 169 | 0건 | 0건 | 부분 (_fake_lock_ctx patch 4회 반복) | 해당 없음 | 해당 없음 |
| test_sector_mapping | 185 | 0건 | 0건 | 부분 (mock_state/conn/cursor 8회 반복) | 해당 없음 | 해당 없음 |
| test_lock_manager | 219 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_engine_bootstrap | 223 | 0건 | 0건 | 0건 | 부분 (test_mode skip REST만, 동등성 명시 검증 부재) | 해당 없음 |
| test_circuit_breaker | 231 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_sector_calculator_integration | 243 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_settings_boost_order_ratio | 244 | 0건 | 0건 | 1건 (5개 patch 블록 5회 중복) | 해당 없음 | 해당 없음 |
| test_telegram | 250 | 0건 | 0건 | 1건 (settings dict + mock 11회 중복) | 부분 (test/real 토큰 각각 테스트, 동등성 명시 검증 부재) | 해당 없음 |
| test_engine_symbol_utils | 252 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_engine_account | 253 | 0건 | 0건 | 0건 | 부분 (test/real 모드 13쌍, 동등성 명시 검증 부재) | 해당 없음 |
| test_pipeline_gateway | 259 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_notification_worker | 274 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_trading_calendar | 276 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_stock_classification_data | 292 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_settings_file_integration | 294 | 0건 | 0건 | 0건 | 부분 (trade_mode 저장/로드만, 동등성 명시 검증 부재) | 1건 (roundtrip save→load 정합성) |
| test_kiwoom_order | 295 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_engine_account_notify | 307 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_sector_data_provider | 318 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_broker_change | 331 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_dry_run | 333 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_stock_tables | 356 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_dry_run_fill_event | 380 | 0건 | 0건 | 1건 (_setup_test_env fixture 44줄, test_settlement_verification과 중복) | 부분 (헤더에 P18 명시하나 test_mode만 실행) | 해당 없음 |
| test_stock_filter | 388 | 0건 | 2건 ("상장주식수비정상" 261/388줄 — "주식" 금지 용어) | 0건 | 해당 없음 | 해당 없음 |
| test_web_app | 401 | 0건 | 0건 | 1건 (_lifespan_patches 52줄, 28개 patch 리스트) | 해당 없음 | 해당 없음 |
| test_logger | 407 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_settlement_verification | 410 | 0건 | 0건 | 1건 (_setup_settlement_env fixture 44줄, test_dry_run_fill_event과 중복) | 부분 (sync vs async 동등성은 있으나 test/real 모드 동등성 아님) | 해당 없음 |
| test_engine_ws_parsing | 411 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_sector_score | 413 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_engine_account_rest | 441 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_engine_ws_dispatch | 450 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_engine_snapshot | 470 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |
| test_settlement_engine | 472 | 0건 | 0건 | 0건 | 해당 없음 | 해당 없음 |

**B-23-d 발견 위반 요약**
| 원칙 | 위반 건수 | 주요 내용 |
|------|----------|----------|
| P16 | 0건 | 36개 전부 양호 (제거된 함수 테스트 없음, dead code 없음) |
| P23 | 2건 | test_stock_filter "상장주식수비정상" 문자열 2회 (261/388줄) — "주식" 금지 용어, "상장종목수비정상"으로 수정 권장 |
| P24 | 13건 | 중복 mock/patch 패턴 12개 파일 (그룹 1의 6개 + test_settings_boost_order_ratio + test_telegram + test_dry_run_fill_event + test_web_app + test_settlement_verification) + 함수 길이 50줄 초과 1건 (test_web_app _lifespan_patches 52줄) |
| P18 | 부분 6건 | test_engine_bootstrap/test_telegram/test_engine_account/test_settings_file_integration (각 모드 동작만, 동등성 명시 검증 부재), test_dry_run_fill_event (헤더에 P18 명시하나 test_mode만), test_settlement_verification (sync vs async는 있으나 test/real 아님) |
| P22 | 1건 | test_settings_file_integration (roundtrip save→load 정합성) — 시스템 레벨 reconciliation(메모리 vs DB, 캐시 vs 원본) 테스트 부재 |

**수정 권장 순위** (별도 세션 승인 필요):
1. (P23) test_stock_filter "상장주식수비정상" → "상장종목수비정상" 수정 (261/388줄) — 가장 단순, 1파일 2곳
2. (P24) test_web_app `_lifespan_patches` 함수 52줄 → 분할 또는 별도 모듈 이동
3. (P24) 중복 fixture 패턴 conftest.py 추출 — test_dry_run_fill_event + test_settlement_verification 공통 fixture 우선 (중복이 가장 명확)
4. (P24) 중복 mock/patch 패턴 fixture 추출 — test_settings_boost_order_ratio (5 patch 5회), test_telegram (settings dict 11회) 우선
5. (P18) test/real 모드 동등성 명시 검증 테스트 추가 — test_engine_account (13쌍) 우선, test_engine_bootstrap/test_telegram/test_settings_file_integration 보완
6. (P22) 시스템 레벨 reconciliation 테스트 보완 — test_settings_file_integration의 roundtrip 외 캐시 vs 원본 대조 추가

**검증**: 코드 수정 없음 → pytest/런타임 검증 대상 아님. **B-23-d 완료**: 소형 36개 점검 완료. B-23 (테스트 품질 점검) 전체 완료.

---

### 세션 F-02: P1 — 진입점, 라우팅, 레이아웃

**대상 파일** (6개, 총 1530줄)
- [x] `frontend/src/main.ts` (322줄, 대형)
- [x] `frontend/src/layout/header.ts` (500줄, 대형 → 분할 완료)
- [x] `frontend/src/router.ts` (237줄, 대형)
- [x] `frontend/src/layout/shell.ts` (168줄, 중형)
- [x] `frontend/src/layout/sidebar.ts` (99줄, 중형)
- [x] `frontend/src/settings.ts` (98줄, 중형)

**대상 원칙**: P5, P10, P16, P19, P21, P23, P24

**조사 체크리스트**
- [x] P5: 직접 호출 체인 (이벤트 버스 없음) — 준수
- [x] P10: 전역 상태 SSOT 참조 — 준수 (uiStore 단일 소스)
- [x] P16: dead code/미사용 라우트 없음 — **해결 F02-01~F02-05** (WebComponentPage 분기, createGlobalWsBadge, settingsModuleCache 주석, router tail 주석, shell contentArea export)
- [x] P19: 비동기 초기화 누락 없음 — 준수
- [x] P21: 엔진 상태/연결 상태가 헤더에 표시됨 — 준수 (header.ts 모든 상태 칩 배선 유지)
- [x] P23: 용어 사전 준수, 패턴 일관 — **해결 F02-06** (settings.ts "Python GC" 잘못된 주석, main.ts 중복 번호)
- [x] P24: 단순성 기준 (header.ts 519줄 → 분할 검토) — **해결 F02-07** (header.ts 519→500줄, onStateChange 분할, renderAvgAmtChip/resolveAvgAmtMsg/resolveAvgAmtStyle 3함수 추출)

**검증**
- [x] `npm run build` 성공 (tsc 타입체크 + vite 빌드)
- [x] `npm run typecheck` 성공 (tsc --noEmit)
- [ ] 브라우저 확인 (모든 라우트 진입, 헤더 상태 표시) — 백엔드 미기동으로 WS 데이터 미확인, 구조는 정상
- [x] 잔여 dead code / 미사용 라우트 grep 추가 인스턴스 없음

---

### 세션 F-03: P2 — 핵심 매매 페이지 (업종순위/매수후보/보유종목) ✅

**대상 파일** (6개, 총 2135줄)
- [x] `frontend/src/pages/sector-stock.ts` (671→653줄) — dead code 2건 + 중복 1건 제거
- [x] `frontend/src/pages/buy-target.ts` (469→462줄) — 헤더 공통 컴포넌트 교체
- [x] `frontend/src/pages/sell-position.ts` (258줄) — 위반 없음 (F03-07 보류: 사용자 설계 로직)
- [x] `frontend/src/pages/sector-ranking-list.ts` (351줄) — 위반 없음
- [x] `frontend/src/pages/sector-ranking-page.ts` (82줄) — 위반 없음
- [x] `frontend/src/pages/stock-detail.ts` (304→247줄) — 합계 바 공통 컴포넌트 교체 + _mounted 가드 추가

**대상 원칙**: P5, P10, P16, P19, P21, P22, P23, P24

**조사 체크리스트**
- [x] P5: 직접 호출 체인 — 준수
- [x] P10: 페이지 상태가 Store에서 관리됨 — 준수
- [x] P16: dead code/미사용 함수 없음 — 2건 해결 (filterStocksBySector, default export)
- [x] P19: 비동기 데이터 로딩 누락 없음 — 1건 해결 (stock-detail _mounted 가드)
- [x] P21: 매수 차단/가드 실패 이유가 UI에 표시됨 — 준수
- [x] P22: 실시간 시세와 표시 데이터 간 정합성 — 1건 보류 (F03-07, 사용자 설계 로직)
- [x] P23: 용어 사전 준수, 패턴 일관 — 2건 해결 (헤더, 합계 바 공통 컴포넌트 교체)
- [x] P24: 단순성 기준 — 1건 해결 (rowCache.clear 중복), 3건 보류 (파일/함수 길이, 구조 개선)

**검증**
- [x] `npm run typecheck` 성공
- [x] `npm run build` 성공
- [x] 잔여 dead code grep 추가 인스턴스 없음

**보류 항목 (B그룹 4건)**: F03-07 (P20/P22 폴백), F03-08/F03-09 (P24 파일/함수 길이), F03-10 (P23 유틸 위치)

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
