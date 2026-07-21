# SectorFlow 아키텍처 전수 점검 계획서

> 작성일: 2026-07-11  
> 기준 문서: `ARCHITECTURE.md` (불변 원칙 24개)  
> 대상: 백엔드 Python 파일 107개 + 프론트엔드 TypeScript 파일 56개 = 총 163개

---

## 1. 개요

### 1.1 목적
SectorFlow 전체 코드베이스를 `ARCHITECTURE.md`에 정의된 22개 불변 원칙 기준으로 체계적으로 점검하여, 아키텍처 위반 사항을 발견하고 근본 원인 해결 계획을 수립.

### 1.2 범위
- **백엔드**: `backend/app/` 전체 (core, db, domain, services, pipelines, web)
- **프론트엔드**: `frontend/src/` 전체 (api, binding, components, layout, pages, stores, types, utils)
- **테스트**: `backend/tests/` 품질 및 커버리지
- **제외**: `stocks.db` 데이터 파일, `broker_specs/` JSON, `protobuf/` 정의

### 1.3 점검 방침
- 추측 금지 — 실제 코드 기반으로 판단
- 근본 원인 해결 — 증상 은폐용 폴백/임시방편 금지
- 파일 하나씩, 블록 단위로 점검
- 발견된 문제는 "발견된 문제 기록" 섹션에 즉시 기록

---

## 2. 불변 원칙 24개 평가 기준표

> 각 점검 항목에서 해당 원칙 번호(P1~P24)로 평가. 체크박스 ☐ = 미점검, ☑ = 준수, ☒ = 위반.

| 번호 | 원칙명 | 핵심 점검 포인트 |
|------|--------|-----------------|
| P1 | 단일 asyncio 이벤트 루프 | `asyncio.run()` 신규 루프 생성 금지, `uvloop` 단일 루프 |
| P2 | 모든 I/O는 async def | 동기 `requests`/`sqlite3`/`time.sleep`/`threading.Lock` 금지 |
| P3 | run_in_executor 우회 금지 | `loop.run_in_executor()` 호출 존재 여부 |
| P4 | 증권사 이름 공통 기능 침투 금지 | 공통 로직에 `kiwoom_`/`ls_` 접두사 존재 여부 |
| P5 | EventBus/발행구독 금지 | 콜백 리스트 옵서버, Redis/Pub-Sub, fire-and-forget `create_task` 금지 |
| P6 | SQLite 단일화 | PostgreSQL/MySQL/SQLAlchemy 사용 여부, Raw SQL 직통 확인 |
| P7 | 블로킹 = 지연 = 왜곡 | per-tick O(n) 연산, 매 틱 DB 조회/전체 순회 금지 |
| P8 | 실시간/배치 파이프라인 분리 | `tick_queue`/`Compute Loop` vs `market_close_pipeline` 물리적 분리 |
| P9 | 파이프라인 독립성 | 배치 연산 중 실시간 틱 차단 금지, `db_write_queue` 쓰기 직렬화 |
| P10 | 단일 소스 진리 (SSOT) | 같은 데이터가 여러 곳에서 독립 관리되는지, 캐시 직접 참조 여부 |
| P11 | 이벤트 기반 루프 | `while + sleep` 폴링 금지, `asyncio.Queue`/`call_later` 사용 |
| P12 | DB 연결 생명주기 공유 | 매 요청마다 `connect()` 금지, `_db_connection` 싱글톤 |
| P13 | 설정 메모리 상주 | 틱 연산 단계에서 DB 설정 조회 금지, O(1) 딕셔너리 조회 |
| P14 | 멀티스레드 남용 금지 | `threading.Thread()` 신규 생성, 무분별 `create_task` 금지 |
| P15 | 단일 주문 경로 | `trading.py` → `execute_buy()`/`execute_sell()` 단일 경로, 분기 금지 |
| P16 | 구현 = 살아있는 경로 배선 | 호출되지 않는 안전코드/dead code 존재 여부 |
| P17 | 플래그 단일 소스 | 한 플래그를 여러 곳에서 직접 수정하는지, 설정 함수 단일성 |
| P18 | 테스트모드 동등성 | 모드 분기가 돈 I/O 최소 지점에만 있는지, 안전장치 테스트 검증 가능 |
| P19 | 런타임 검증 게이트 | `RuntimeWarning(coroutine never awaited)` 검출, `await` 누락 |
| P20 | 폴백 금지 | 정상 경로의 빈 문자열/None/누락을 폴백으로 덮는지, silent `except: pass` |
| P21 | 사용자 투명성 | 사용자 모르는 중요 의사결정, 백엔드 상태의 UI 표시 의무 |
| P22 | 데이터 정합성 | 파생 데이터 모델, 기동 시 대조(reconciliation), 불일치 시 즉시 차단 |
| P23 | 일관된 통일성 | 용어 사전 준수("업종"/"종목"), 에러/비동기/네이밍/상수 패턴의 파일 간 일관, UI 패턴 공통 컴포넌트 추출 |
| P24 | 단순성 | 더 단순한 대체 가능성, 불필요한 추상화(1회용 래퍼/인터페이스), 함수 50줄·파일 500줄·복잡도 10 초과, 중복 로직 3회 추출 |

---

## 3. 세션 진행 가이드

### 3.1 파일 규모 분류

| 분류 | 줄 수 | 세션당 적정 수 | 예시 |
|------|-------|---------------|------|
| **소형** | < 50줄 | 3~5개 | `constants.py`, `trade_mode.py`, `broker_urls.py` |
| **중형** | 50~200줄 | 2~3개 | `risk_manager.py`, `engine_state.py`, `circuit_breaker.py` |
| **대형** | > 200줄 | 1개 | `market_close_pipeline.py`, `trading.py`, `daily_time_scheduler.py` |

### 3.2 세션 내 워크플로우

```
┌─────────────────────────────────────────────────────┐
│  1. 조사 단계 (40%)                                   │
│  ├── 파일 전체 읽기                                   │
│  ├── 22개 원칙 체크리스트 대조                        │
│  ├── 의존성/호출 관계 추적                            │
│  └── 위반 사항 식별 및 "발견된 문제 기록"에 등록       │
├─────────────────────────────────────────────────────┤
│  2. 수정 단계 (40%)                                   │
│  ├── 사용자 승인 후 수정 (AGENTS.md 규칙 준수)         │
│  ├── 파일 하나씩, 블록 단위 수정                       │
│  └── 금지: 임시방편, 폴백, !important, as any         │
├─────────────────────────────────────────────────────┤
│  3. 검증 단계 (20%)                                   │
│  ├── 백엔드: 런타임 기동 검증 (main.py 10~30s)        │
│  ├── 프론트엔드: npm run build                        │
│  ├── 테스트: pytest 해당 모듈                         │
│  └── 잔여 위반 패턴 검색 확인                         │
└─────────────────────────────────────────────────────┘
```

### 3.3 점검 완료 충족 기준

각 세션 종료 시 다음을 모두 충족해야 "완료"로 표시:

- [ ] 해당 세션의 모든 파일을 22개 원칙으로 점검 완료
- [ ] 발견된 위반 사항을 "발견된 문제 기록" 섹션에 등록
- [ ] 수정된 파일은 런타임 검증 또는 빌드 검증 통과
- [ ] 잔여 위반 패턴 검색(`grep`)으로 추가 인스턴스 없음 확인
- [ ] 세션 체크리스트에 완료 표시 (☑)

### 3.4 세션 순서 원칙

**의존성 하위 → 상위 + 중요도 P0 → P3 교차 적용**

1. **P0 최우선**: 자금 손실 직결 경로 (주문, 리스크, 실시간 파이프라인)
2. **P1 차선**: 시스템 가동 필수 (엔진 루프, WS, 상태 관리)
3. **P2 후순위**: 데이터 기반 계층 (도메인, DB, 설정, Broker 추상화)
4. **P3 최후**: 부가 기능 (UI, 알림, 테스트, 유틸)

> 예외: 의존성 하위 계층(DB, 설정)은 P0 점검 전에 선행 점검하여 기반 안정성 확보.

### 3.5 세션별 예상 소요 추정

> 주의: 아래 추정치는 파일 규모와 의존성 복잡도를 기반으로 한 상대적 지표. 실제 소요는 컨텍스트 사용량, 발견된 문제 수, 수정 범위에 따라 변동.

| 세션 유형 | 파일 규모 | 예상 소요 | 비고 |
|-----------|-----------|-----------|------|
| 대형 1개 | 200~500줄 | 중간~장시간 | 조사 깊이 필요, 의존성 추적 다수 |
| 대형 1개 (초대형) | 500~1400줄 | 장시간 | `market_close_pipeline`, `daily_time_scheduler` 등 |
| 중형 2~3개 | 50~200줄 | 중간 | 균형 잡힌 세션 |
| 소형 3~5개 | < 50줄 | 단시간 | 빠른 스캔, 위반 패턴 적음 |

---

## 4. 백엔드 점검 항목

### 우선순위 분류 기준

| 우선순위 | 기준 | 대상 |
|----------|------|------|
| **P0** | 자금 손실 직결, 실시간 매매 핵심 경로 | 주문 실행, 리스크, Dry Run, 정산 |
| **P1** | 시스템 가동 필수, 실시간 데이터 처리 | 엔진 루프, WS, 상태, 파이프라인 |
| **P2** | 데이터 기반, 도메인 로직, 인프라 | DB, 설정, Broker, Domain, 스케줄러 |
| **P3** | 부가 기능, 외부 인터페이스 | 알림, Web API, 유틸, 테스트 |

---

### 세션 B-01: P0 — 주문 실행 경로
> **우선순위**: P0 (자금 손실 직결)  
> **파일**: 대형 1개 + 중형 1개  
> **대상 원칙**: P1, P2, P5, P7, P14, P15, P16, P18, P20, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/trading.py` | 650 | 대형 | ☐ |
| `services/buy_order_executor.py` | 169 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P1: 단일 이벤트 루프 내에서 주문 실행
- [ ] P2: 모든 I/O가 async def
- [ ] P5: 직접 호출 체인, fire-and-forget create_task 없음
- [ ] P7: 주문 경로에 블로킹 연산 없음
- [ ] P14: 멀티스레드 사용 없음
- [ ] P15: `execute_buy()`/`execute_sell()` 단일 경로, 분기 없음
- [ ] P16: RiskManager/CircuitBreaker가 실제 호출 경로에 배선됨
- [ ] P18: 테스트모드 분기가 `dry_run.fake_send_order()`에만 존재
- [ ] P20: 폴백/silent except 없음
- [ ] P22: 주문 체결 → 정산/이력 간 데이터 정합성 보장
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-02: P0 — 리스크 관리 및 서킷 브레이커
> **우선순위**: P0 (자금 보호)  
> **파일**: 중형 2개  
> **대상 원칙**: P5, P7, P15, P16, P17, P18, P20, P21, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/risk_manager.py` | 130 | 중형 | ☐ |
| `services/circuit_breaker.py` | 113 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P5: 직접 호출 체인
- [ ] P7: 차단 로직에 블로킹 없음
- [ ] P15: 주문 경로 내에서만 리스크 체크 수행
- [ ] P16: RiskManager/CircuitBreaker가 살아있는 경로에 배선됨 (실제 호출 확인)
- [ ] P17: 차단 플래그가 SSOT에서 관리됨
- [ ] P18: 테스트모드에서도 리스크 체크 동작
- [ ] P20: 폴백 없음, 에러 시 명시적 로깅
- [ ] P21: 서킷 브레이커 OPEN 시 프론트엔드에 통지됨
- [ ] P22: 손실 한도 계산의 데이터 정합성
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-03: P0 — Dry Run (테스트 모드 가상 주문)
> **우선순위**: P0 (테스트모드 동등성 핵심)  
> **파일**: 대형 1개  
> **대상 원칙**: P1, P2, P5, P14, P15, P16, P18, P20, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/dry_run.py` | 354 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P1: 단일 이벤트 루프
- [ ] P2: 모든 I/O async def
- [ ] P5: fire-and-forget create_task 없음 (done_callback 확인)
- [ ] P14: 멀티스레드 없음
- [ ] P15: `fake_send_order()`가 단일 주문 경로의 테스트 분기
- [ ] P16: dead code/no-op 함수 없음
- [ ] P18: 실전모드와 동일한 과정 (돈 I/O만 다름)
- [ ] P20: 폴백/silent except 없음
- [ ] P22: `test_positions`와 `trade_history` 간 정합성 (유령 포지션 방지)
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-04: P0 — 정산 엔진 및 거래 이력
> **우선순위**: P0 (자금 계산 정확성)  
> **파일**: 대형 1개 + 중형 1개  
> **대상 원칙**: P2, P6, P8, P9, P10, P12, P13, P20, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/settlement_engine.py` | 248 | 대형 | ☑ |
| `services/trade_history.py` | 656 | 대형 | ☑ |

**원칙 체크리스트**:
- [x] P2: DB I/O async def
- [x] P6: SQLite 단일화, Raw SQL
- [x] P8: 배치 파이프라인과 분리
- [x] P9: `db_write_queue`로 쓰기 직렬화
- [x] P10: 정산 상태 SSOT (`settlement_state` 단일 행)
- [x] P12: DB 연결 싱글톤
- [x] P13: 정산 상태 메모리 상주
- [x] P20: 폴백 없음 (B04-01/02/03 — silent except 및 폴백 3건 제거)
- [x] P22: 정산 상태와 거래 이력 간 정합성, 기동 시 대조 (B04-02 — DB 에러 시 기본값 덮어쓰기 폴백 제거, B04-05 reconciliation 보류)
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-05: P0 — 자동매매 유효성 및 코어 큐
> **우선순위**: P0 (매매 게이트)  
> **파일**: 소형 2개  
> **대상 원칙**: P5, P10, P11, P13, P17, P18, P21, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/auto_trading_effective.py` | 80 | 중형 | ☑ |
| `services/core_queues.py` | 127 | 중형 | ☑ |

**원칙 체크리스트**:
- [x] P5: asyncio.Queue 파이프라인 일원화
- [x] P10: 설정 캐시 직접 참조 (B05-04 docstring 불일치 수정, B05-06 tick_queue size 불일치 수정)
- [x] P11: 폴링 없음, 이벤트 기반
- [x] P13: 설정 O(1) 메모리 조회
- [x] P17: `auto_buy_on`/`auto_sell_on` 플래그 SSOT
- [x] P18: 테스트모드에서도 동일한 게이트 로직
- [x] P21: 매매 차단 시 사용자에게 표시 (B05-01 silent except → warning 로그 추가)
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-06: P1 — 엔진 루프 및 생명주기
> **우선순위**: P1 (시스템 가동 필수)  
> **파일**: 대형 2개 + 중형 1개  
> **대상 원칙**: P1, P2, P5, P7, P8, P9, P11, P14, P16, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/engine_loop.py` | 384 | 대형 | ☑ |
| `services/engine_lifecycle.py` | 378 | 대형 | ☑ |
| `services/engine_state.py` | 141 | 중형 | ☑ |

**원칙 체크리스트**:
- [x] P1: 단일 이벤트 루프
- [x] P2: 모든 I/O async def
- [x] P5: 직접 호출 체인, fire-and-forget 없음
- [x] P7: 루프 내 블로킹 연산 없음, `asyncio.sleep(0)` 양보
- [x] P8: 실시간 루프와 배치 분리
- [x] P9: 파이프라인 간 간섭 없음
- [x] P11: 이벤트 기반 (`ws_window_changed_event` 대기)
- [x] P14: 멀티스레드 없음
- [x] P16: dead code/no-op 없음 (B06-01, B06-02, B06-03 해결)
- [x] P19: `await` 누락 없음
- [x] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-07: P1 — WS 시세 처리 (파싱/디스패치/등록)
> **우선순위**: P1 (실시간 데이터 처리)  
> **파일**: 대형 1개 + 중형 2개 + 소형 1개  
> **대상 원칙**: P1, P2, P3, P4, P5, P7, P8, P11, P14, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/engine_ws_reg.py` | 484 | 대형 | ☐ |
| `services/engine_ws_dispatch.py` | 335 | 대형 | ☐ |
| `services/engine_ws.py` | 311 | 대형 | ☐ |
| `services/engine_ws_parsing.py` | 218 | 대형 | ☐ |
| `services/engine_ws_fill_followup.py` | 29 | 소형 | ☐ |

**원칙 체크리스트**:
- [ ] P1: 단일 이벤트 루프
- [ ] P2: 모든 I/O async def
- [ ] P3: `run_in_executor` 없음
- [ ] P4: 증권사 이름이 공통 파싱 로직에 침투하지 않음
- [ ] P5: 직접 호출 체인
- [ ] P7: per-tick O(n) 연산 없음, 매 틱 DB 조회 없음
- [ ] P8: 실시간 파이프라인 내 처리
- [ ] P11: 이벤트 기반 (Queue 대기)
- [ ] P14: 멀티스레드 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-08: P1 — 엔진 부트스트랩/캐시/스냅샷/구성/유틸
> **우선순위**: P1 (초기화 및 캐시)  
> **파일**: 중형 3개 + 소형 2개  
> **대상 원칙**: P5, P10, P12, P13, P14, P16, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/engine_bootstrap.py` | 206 | 대형 | ☑ |
| `services/engine_snapshot.py` | 242 | 대형 | ☑ |
| `services/engine_cache.py` | 152 | 중형 | ☑ |
| `services/engine_config.py` | 155 | 중형 | ☑ |
| `services/engine_utils.py` | 68 | 중형 | ☑ |

**원칙 체크리스트**:
- [x] P5: fire-and-forget create_task 없음 (done_callback 확인)
- [x] P10: 캐시 SSOT (`master_stocks_cache`, `integrated_system_settings_cache`)
- [x] P12: DB 연결 싱글톤
- [x] P13: 설정 메모리 상주
- [x] P14: 멀티스레드 없음
- [x] P16: dead code 없음
- [x] P19: `await` 누락 없음
- [x] P20: 폴백/silent except 없음
- [x] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [x] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-09: P1 — 엔진 섹터 확인/전략/레이더/심볼
> **우선순위**: P1 (업종 재계산 및 매수 전략)  
> **파일**: 대형 1개 + 중형 2개 + 소형 1개  
> **대상 원칙**: P5, P7, P10, P11, P13, P16, P18, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/engine_sector_confirm.py` | 426→413 | 대형 | ☑ |
| `services/engine_radar.py` | 208→79 | 대형 | ☑ |
| `services/engine_strategy_core.py` | 78→42 | 중형 | ☑ |
| `services/engine_symbol_utils.py` | 157→143 | 중형 | ☑ |
| `services/engine_radar_ops.py` | 70→제거 | 중형 | ☑ |

**원칙 체크리스트**:
- [x] P5: 직접 호출 체인
- [x] P7: 증분 재계산에서 블로킹 없음
- [x] P10: 업종 점수 캐시 SSOT
- [x] P11: 이벤트 기반 (dirty 섹터 감지)
- [x] P13: 설정 O(1) 조회
- [x] P16: dead code 없음
- [x] P18: 테스트모드에서 동일한 계산 로직
- [x] P20: 폴백/silent except 없음
- [x] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [x] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-10: P1 — 엔진 계좌/서비스
> **우선순위**: P1 (계좌 관리 및 엔진 서비스)  
> **파일**: 대형 2개 + 중형 2개  
> **대상 원칙**: P2, P4, P5, P10, P13, P16, P19, P20, P21, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/engine_account_notify.py` | 657 | 대형 | ☐ |
| `services/engine_account.py` | 502 | 대형 | ☐ |
| `services/engine_account_rest.py` | 390 | 대형 | ☐ |
| `services/engine_service.py` | 220 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P2: 모든 I/O async def
- [ ] P4: 증권사 이름 침투 없음
- [ ] P5: 직접 호출 체인
- [ ] P10: 계좌 상태 SSOT
- [ ] P13: 설정 메모리 조회
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P21: 계좌 상태 변화가 UI에 표시됨
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-11: P1 — 파이프라인 (Compute / Gateway)
> **우선순위**: P1 (실시간 데이터 파이프라인)  
> **파일**: 대형 1개 + 중형 1개  
> **대상 원칙**: P1, P2, P5, P7, P8, P9, P11, P14, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `pipelines/pipeline_compute.py` | 739 | 대형 | ☐ |
| `pipelines/pipeline_gateway.py` | 181 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P1: 단일 이벤트 루프
- [ ] P2: 모든 I/O async def
- [ ] P5: asyncio.Queue 파이프라인, 직접 호출
- [ ] P7: 블로킹 연산 없음
- [ ] P8: 실시간 파이프라인으로서 배치와 분리
- [ ] P9: 파이프라인 독립성
- [ ] P11: 이벤트 기반 (Queue 대기)
- [ ] P14: 멀티스레드 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-12: P2 — DB 계층
> **우선순위**: P2 (데이터 기반, 하위 계층 선행)  
> **파일**: 대형 1개 + 중형 2개 + 소형 1개  
> **대상 원칙**: P2, P6, P8, P9, P10, P12, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `db/stock_tables.py` | 371 | 대형 | ☐ |
| `db/db_writer.py` | 183 | 중형 | ☐ |
| `db/database.py` | — | 중형 | ☐ |
| `db/json_utils.py` | — | 소형 | ☐ |

**원칙 체크리스트**:
- [ ] P2: aiosqlite 사용, 동기 sqlite3 없음
- [ ] P6: SQLite 단일화, ORM 없음, Raw SQL
- [ ] P8: 실시간/배치 쓰기 분리
- [ ] P9: `db_write_queue` 쓰기 직렬화
- [ ] P10: 데이터 SSOT
- [ ] P12: `_db_connection` 싱글톤, 매 요청 connect() 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-13: P2 — 설정 관리
> **우선순위**: P2 (설정 기반, 하위 계층 선행)  
> **파일**: 대형 1개 + 중형 2개 + 소형 1개  
> **대상 원칙**: P2, P6, P10, P12, P13, P17, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `core/settings_file.py` | 430 | 대형 | ☐ |
| `core/settings_store.py` | 251 | 대형 | ☐ |
| `core/engine_settings.py` | 214 | 대형 | ☐ |
| `core/settings_defaults.py` | 148 | 중형 | ☐ |
| `core/trade_mode.py` | 39 | 소형 | ☐ |

**원칙 체크리스트**:
- [ ] P2: DB I/O async def
- [ ] P6: SQLite, Raw SQL
- [ ] P10: `integrated_system_settings_cache` SSOT
- [ ] P12: DB 연결 싱글톤
- [ ] P13: 설정 메모리 상주, 틱 연산에서 DB 조회 없음
- [ ] P17: 플래그 단일 소스 (`auto_buy_on` 등)
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-14: P2 — Broker 추상화 (공통)
> **우선순위**: P2 (증권사 추상화 계층)  
> **파일**: 대형 1개 + 중형 2개 + 소형 2개  
> **대상 원칙**: P2, P3, P4, P5, P10, P14, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `core/broker_router.py` | 285 | 대형 | ☐ |
| `core/connector_manager.py` | 281 | 대형 | ☐ |
| `core/broker_registry.py` | 184 | 중형 | ☐ |
| `core/broker_providers.py` | 120 | 중형 | ☐ |
| `core/broker_factory.py` | 57 | 중형 | ☐ |
| `core/broker_connector.py` | 115 | 중형 | ☐ |
| `core/broker_urls.py` | 82 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P2: 모든 I/O async def
- [ ] P3: `run_in_executor` 없음
- [ ] P4: 공통 로직에 `kiwoom_`/`ls_` 접두사 없음
- [ ] P5: 직접 호출 체인
- [ ] P10: 인증 토큰 캐시 SSOT
- [ ] P14: 멀티스레드 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-15: P2 — 증권사 구현: 키움증권
> **우선순위**: P2 (증권사별 구현)  
> **파일**: 대형 2개 + 중형 3개  
> **대상 원칙**: P1, P2, P3, P4, P5, P7, P14, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `core/kiwoom_connector.py` | 563 | 대형 | ☐ |
| `core/kiwoom_rest.py` | 653 | 대형 | ☐ |
| `core/kiwoom_stock_rest.py` | 430 | 대형 | ☐ |
| `core/kiwoom_providers.py` | 337 | 대형 | ☐ |
| `core/kiwoom_order.py` | 93 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P1: `asyncio.run()` 신규 루프 생성 없음
- [ ] P2: `httpx.AsyncClient` 사용, 동기 `requests` 없음
- [ ] P3: `run_in_executor` 없음
- [ ] P4: 키움 특화 로직이 공통 로직에 침투하지 않음 (별도 파일 격리 확인)
- [ ] P5: 직접 호출 체인
- [ ] P7: WS 수신 핸들러에 블로킹 없음
- [ ] P14: 멀티스레드 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-16: P2 — 증권사 구현: LS증권
> **우선순위**: P2 (증권사별 구현)  
> **파일**: 대형 2개 + 중형 1개  
> **대상 원칙**: P1, P2, P3, P4, P5, P7, P14, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `core/ls_connector.py` | 875 | 대형 | ☐ |
| `core/ls_rest.py` | 635 | 대형 | ☐ |
| `core/ls_providers.py` | 195 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P1: `asyncio.run()` 신규 루프 생성 없음 (과거 위반 사례 `_run_async()` 재발 확인)
- [ ] P2: `httpx.AsyncClient` 사용
- [ ] P3: `run_in_executor` 없음
- [ ] P4: LS 특화 로직이 공통 로직에 침투하지 않음
- [ ] P5: 직접 호출 체인
- [ ] P7: WS 수신 핸들러에 블로킹 없음
- [ ] P14: 멀티스레드 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-17: P2 — Domain 계층 (모델/업종계산/필터)
> **우선순위**: P2 (도메인 로직)  
> **파일**: 대형 1개 + 중형 3개 + 소형 1개  
> **대상 원칙**: P7, P10, P13, P16, P18, P20, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `domain/sector_calculator.py` | 252 | 대형 | ☐ |
| `domain/buy_filter.py` | 314 | 대형 | ☐ |
| `domain/sector_score.py` | 111 | 중형 | ☐ |
| `domain/sector_filter.py` | — | 중형 | ☐ |
| `domain/models.py` | 124 | 중형 | ☐ |
| `core/stock_filter.py` | 261 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P7: 계산 로직에 블로킹/DB 조회 없음 (순수 계산)
- [ ] P10: 데이터 모델 SSOT
- [ ] P13: 설정값 메모리 조회
- [ ] P16: dead code 없음
- [ ] P18: 테스트모드와 동일한 계산
- [ ] P20: 폴백/silent except 없음
- [ ] P22: 파생 데이터 모델 선호, 단계 간 일관성
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-18: P2 — 스케줄러 및 장마감 파이프라인
> **우선순위**: P2 (배치 파이프라인)  
> **파일**: 초대형 2개 + 중형 1개  
> **대상 원칙**: P1, P2, P5, P7, P8, P9, P11, P14, P16, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/market_close_pipeline.py` | 1370 | 초대형 | ☐ |
| `services/daily_time_scheduler.py` | 1050 | 초대형 | ☐ |
| `services/data_manager.py` | 237 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P1: 단일 이벤트 루프
- [ ] P2: 모든 I/O async def
- [ ] P5: 직접 호출 체인
- [ ] P7: 배치 연산 중 실시간 틱 차단 금지
- [ ] P8: 배치 파이프라인으로서 실시간과 분리
- [ ] P9: 파이프라인 독립성
- [ ] P11: `asyncio.call_later()` 기반, 폴링 없음
- [ ] P14: 멀티스레드 없음
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-19: P2 — WS 구독 제어 및 업종 데이터 제공자
> **우선순위**: P2 (WS 구독 관리)  
> **파일**: 대형 1개 + 중형 1개  
> **대상 원칙**: P4, P5, P7, P10, P11, P13, P16, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/ws_subscribe_control.py` | 261 | 대형 | ☐ |
| `services/sector_data_provider.py` | 300 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P4: 증권사 이름 침투 없음
- [ ] P5: 직접 호출 체인
- [ ] P7: 구독 제어에 블로킹 없음
- [ ] P10: 업종 데이터 SSOT
- [ ] P11: 이벤트 기반
- [ ] P13: 설정 메모리 조회
- [ ] P16: dead code 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-20: P3 — 알림 (Telegram / Notification)
> **우선순위**: P3 (부가 기능)  
> **파일**: 대형 1개 + 소형 1개  
> **대상 원칙**: P2, P5, P14, P16, P19, P20, P21, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `services/telegram_bot.py` | 525 | 대형 | ☐ |
| `services/telegram.py` | — | 중형 | ☐ |
| `services/notification_worker.py` | 98 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P2: HTTP I/O async def (`httpx.AsyncClient`)
- [ ] P5: 직접 호출 체인
- [ ] P14: 멀티스레드 없음
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P21: 중요 상태 변화가 알림으로 전달됨
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-21: P3 — 기타 Core 유틸
> **우선순위**: P3 (인프라 유틸)  
> **파일**: 대형 1개 + 중형 3개 + 소형 4개  
> **대상 원칙**: P2, P5, P10, P14, P16, P19, P20, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `core/journal.py` | 324 | 대형 | ☐ |
| `core/logger.py` | 314 | 대형 | ☐ |
| `core/trading_calendar.py` | 406 | 대형 | ☐ |
| `core/stock_classification_data.py` | 240 | 대형 | ☐ |
| `core/sector_mapping.py` | 99 | 중형 | ☐ |
| `core/sector_stock_cache.py` | 138 | 중형 | ☐ |
| `core/lock_manager.py` | 146 | 중형 | ☐ |
| `core/encryption.py` | 87 | 중형 | ☐ |
| `core/memory_monitor.py` | 52 | 중형 | ☐ |
| `core/constants.py` | 14 | 소형 | ☐ |
| `core/logging_config.py` | 19 | 소형 | ☐ |

**원칙 체크리스트**:
- [ ] P2: `asyncio.Lock` 사용, `threading.Lock` 없음
- [ ] P5: 직접 호출 체인
- [ ] P10: 종목 매핑/분류 캐시 SSOT
- [ ] P14: 멀티스레드 없음
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-22: P3 — Web API 계층
> **우선순위**: P3 (외부 인터페이스)  
> **파일**: 대형 1개 + 중형 2개 + 소형 6개  
> **대상 원칙**: P2, P5, P10, P12, P13, P16, P19, P20, P21, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `web/app.py` | 323 | 대형 | ☐ |
| `web/ws_manager.py` | 351 | 대형 | ☐ |
| `web/routes/stock_classification.py` | 330 | 대형 | ☐ |
| `web/routes/settings.py` | 169 | 중형 | ☐ |
| `web/routes/status.py` | 144 | 중형 | ☐ |
| `web/routes/ws.py` | 207 | 대형 | ☐ |
| `web/routes/ws_subscribe.py` | 71 | 중형 | ☐ |
| `web/auth.py` | 45 | 소형 | ☐ |
| `web/deps.py` | 26 | 소형 | ☐ |
| `web/routes/account.py` | 5 | 소형 | ☐ |
| `web/routes/auth.py` | 28 | 소형 | ☐ |
| `web/routes/market.py` | 17 | 소형 | ☐ |
| `web/routes/settlement.py` | 17 | 소형 | ☐ |
| `app/config.py` | 79 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P2: 모든 엔드포인트 async def
- [ ] P5: 직접 호출 체인
- [ ] P10: 설정/상태 SSOT 참조
- [ ] P12: DB 연결 싱글톤
- [ ] P13: 설정 DB 직접 조회 없음 (캐시 참조)
- [ ] P16: dead code 없음
- [ ] P19: `await` 누락 없음
- [ ] P20: 폴백/silent except 없음
- [ ] P21: 백엔드 상태가 API/WebSocket으로 프론트엔드에 전달됨
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 B-23: P3 — 테스트 품질 점검
> **우선순위**: P3 (테스트 품질)  
> **파일**: 테스트 파일 66개  
> **대상 원칙**: P16, P18, P19, P22, P23, P24

| 점검 항목 | 점검 완료 |
|-----------|----------|
| 테스트 커버리지 현황 파악 (모듈별) | ☐ |
| P16: 테스트가 살아있는 경로를 검증하는지 (dead code 테스트 아님) | ☐ |
| P18: 테스트모드 동등성 검증 존재 여부 | ☐ |
| P19: `RuntimeWarning(coroutine never awaited)` 감지 테스트 | ☐ |
| P22: 데이터 정합성 대조(reconciliation) 테스트 | ☐ |
| P23: 용어/에러/비동기/네이밍/상수 일관성 점검 | ☐ |
| P24: 단순성 점검 (불필요한 추상화, 복잡도) | ☐ |
| 미커버 모듈 식별 (테스트 파일 없는 소스 파일) | ☐ |
| 통합 테스트 vs 단위 테스트 비율 | ☐ |

---

## 5. 프론트엔드 점검 항목

### 우선순위 분류 기준

| 우선순위 | 기준 | 대상 |
|----------|------|------|
| **P0** | 실시간 데이터 표시, 상태 동기화 | 통신 계층, Stores, Binding |
| **P1** | 페이지 진입, 라우팅, 레이아웃 | 진입점, 라우터, 레이아웃 |
| **P2** | 핵심 매매 페이지 | 업종순위, 매수후보, 보유종목, 설정 |
| **P3** | 부가 UI, 컴포넌트, 유틸 | 수익 페이지, 컴포넌트, 타입 |

---

### 세션 F-01: P0 — 통신 계층 및 상태 관리
> **우선순위**: P0 (실시간 데이터 표시 핵심)  
> **파일**: 대형 1개 + 중형 3개 + 소형 2개  
> **대상 원칙**: P5, P10, P11, P19, P21, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `stores/hotStore.ts` | 676 | 대형 | ☑ |
| `stores/uiStore.ts` | 243 | 대형 | ☑ |
| `api/ws.ts` | 267 | 대형 | ☑ |
| `api/client.ts` | 188 | 중형 | ☑ |
| `binding.ts` | 315 | 대형 | ☑ |
| `stores/store.ts` | 50 | 소형 | ☑ |
| `stores/stockClassificationStore.ts` | 57 | 소형 | ☑ |
| `stores/index.ts` | 5 | 소형 | ☑ |

**원칙 체크리스트**:
- [x] P5: WebSocket 이벤트 → Store 갱신이 직접 호출 체인 (옵서버 패턴 아님) — window.dispatchEvent는 DOM 렌더링 최적화용 의도적 예외
- [x] P10: 상태가 단일 Store에서 관리됨 (중복 상태 없음) — uiStore.positionCount 중복 제거
- [x] P11: 폴링 없음, 이벤트 기반 (WS 메시지 구동) — ping interval은 keepalive용이며 폴링 아님
- [x] P19: 비동기 처리 누락 없음 (Promise await/catch) — client.ts 401 dead code 제거, ws.onerror 로깅 추가
- [x] P21: 백엔드 상태(매수 차단, 리스크 등)가 UI에 표시됨 — circuit_breaker_open 배선 + ws-connection-status 배선 + WS 연결/재연결 칩 추가
- [x] P22: WS 이벤트와 Store 상태 간 정합성 — in-place mutation은 의도적 성능 최적화 예외
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 F-02: P1 — 진입점, 라우팅, 레이아웃
> **우선순위**: P1 (앱 진입 및 구조)  
> **파일**: 대형 1개 + 중형 3개 + 소형 1개  
> **대상 원칙**: P5, P10, P16, P19, P21, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `main.ts` | 329 | 대형 | ☐ |
| `layout/header.ts` | 420 | 대형 | ☐ |
| `router.ts` | 273 | 대형 | ☐ |
| `layout/shell.ts` | 169 | 중형 | ☐ |
| `layout/sidebar.ts` | 99 | 중형 | ☐ |
| `settings.ts` | 146 | 중형 | ☐ |

**원칙 체크리스트**:
- [ ] P5: 직접 호출 체인 (이벤트 버스 없음)
- [ ] P10: 전역 상태 SSOT 참조
- [ ] P16: dead code/미사용 라우트 없음
- [ ] P19: 비동기 초기화 누락 없음
- [ ] P21: 엔진 상태/연결 상태가 헤더에 표시됨
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 F-03: P2 — 핵심 매매 페이지 (업종순위/매수후보/보유종목)
> **우선순위**: P2 (핵심 매매 UI)  
> **파일**: 대형 3개 + 소형 1개  
> **대상 원칙**: P5, P10, P16, P19, P21, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `pages/sector-stock.ts` | 724 | 대형 | ☐ |
| `pages/buy-target.ts` | 514 | 대형 | ☐ |
| `pages/sell-position.ts` | 307 | 대형 | ☐ |
| `pages/sector-ranking-list.ts` | 244 | 대형 | ☐ |
| `pages/sector-ranking-page.ts` | 82 | 소형 | ☐ |
| `pages/stock-detail.ts` | 271 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P5: 직접 호출 체인
- [ ] P10: 페이지 상태가 Store에서 관리됨 (로컬 중복 없음)
- [ ] P16: dead code/미사용 함수 없음
- [ ] P19: 비동기 데이터 로딩 누락 없음
- [ ] P21: 매수 차단/가드 실패 이유가 UI에 표시됨
- [ ] P22: 실시간 시세와 표시 데이터 간 정합성
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 F-04: P2 — 설정 페이지 (매수/매도/일반/업종/종목분류)
> **우선순위**: P2 (설정 UI)  
> **파일**: 대형 3개 + 중형 2개  
> **대상 원칙**: P10, P13, P16, P17, P19, P21, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `pages/stock-classification.ts` | 1555 | 초대형 | ☐ |
| `pages/general-settings.ts` | 999 | 대형 | ☐ |
| `pages/buy-settings.ts` | 344 | 대형 | ☐ |
| `pages/sell-settings.ts` | 139 | 중형 | ☐ |
| `pages/sector-settings.ts` | 307 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P10: 설정값이 Store를 통해 백엔드 SSOT와 동기화됨
- [ ] P13: 설정 변경 시 백엔드 캐시 갱신 경로 확인
- [ ] P16: dead code/미사용 설정 항목 없음
- [ ] P17: 플래그 토글이 단일 경로로 백엔드에 전달됨
- [ ] P19: 설정 저장 비동기 처리 누락 없음
- [ ] P21: 설정 변경 결과가 UI에 즉시 반영됨
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 F-05: P3 — 수익 페이지
> **우선순위**: P3 (수익 분석 UI)  
> **파일**: 대형 3개  
> **대상 원칙**: P5, P10, P16, P19, P22, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `pages/profit-overview.ts` | 646 | 대형 | ☐ |
| `pages/profit-detail.ts` | 620 | 대형 | ☐ |
| `pages/profit-shared.ts` | 515 | 대형 | ☐ |

**원칙 체크리스트**:
- [ ] P5: 직접 호출 체인
- [ ] P10: 수익 데이터가 Store에서 관리됨
- [ ] P16: dead code 없음
- [ ] P19: 비동기 데이터 로딩 누락 없음
- [ ] P22: 수익 데이터와 백엔드 정산 데이터 간 정합성
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 F-06: P3 — 공통 컴포넌트
> **우선순위**: P3 (UI 컴포넌트)  
> **파일**: 대형 2개 + 중형 6개 + 소형 11개  
> **대상 원칙**: P5, P10, P16, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `components/common/data-table.ts` | 943 | 대형 | ☐ |
| `components/common/setting-row.ts` | 597 | 대형 | ☐ |
| `components/common/ui-styles.ts` | 575 | 대형 | ☐ |
| `components/virtual-scroller.ts` | 528 | 대형 | ☐ |
| `components/canvas-profit-chart.ts` | 508 | 대형 | ☐ |
| `components/common/button.ts` | 321 | 대형 | ☐ |
| `components/canvas-sector-donut.ts` | 347 | 대형 | ☐ |
| `components/common/dialog.ts` | 261 | 대형 | ☐ |
| `components/common/context-popup.ts` | 260 | 대형 | ☐ |
| `components/common/settings-common.ts` | 221 | 대형 | ☐ |
| `components/common/toast.ts` | 189 | 중형 | ☐ |
| `components/common/create-slider.ts` | 173 | 중형 | ☐ |
| `components/common/search-input.ts` | 153 | 중형 | ☐ |
| `components/common/auto-width.ts` | 133 | 중형 | ☐ |
| `components/common/date-range-input.ts` | 96 | 중형 | ☐ |
| `components/common/time-pair-input.ts` | 64 | 소형 | ☐ |
| `components/common/sector-row.ts` | 62 | 소형 | ☐ |
| `components/common/card-header.ts` | 42 | 소형 | ☐ |
| `components/common/broker-badge.ts` | 42 | 소형 | ☐ |
| `components/common/account-labels.ts` | 32 | 소형 | ☐ |
| `components/common/card-title.ts` | 21 | 소형 | ☐ |

**원칙 체크리스트**:
- [ ] P5: 컴포넌트 간 직접 호출 (이벤트 버스 없음)
- [ ] P10: 컴포넌트 상태가 Store에서 관리됨 (로컬 상태 최소화)
- [ ] P16: dead code/미사용 컴포넌트 없음
- [ ] P23: UI 패턴(목록/카드/태그/버튼/모달) 2회 이상 반복 시 공통 컴포넌트 추출, 직접 중복 구현 없음. 용어 사전 준수
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

### 세션 F-07: P3 — 타입 및 유틸
> **우선순위**: P3 (타입 정의 및 유틸)  
> **파일**: 대형 1개 + 중형 1개 + 소형 3개  
> **대상 원칙**: P10, P16, P23, P24

| 파일 | 줄 수 | 규모 | 점검 완료 |
|------|-------|------|----------|
| `types/index.ts` | 321 | 대형 | ☐ |
| `types/event.ts` | 165 | 중형 | ☐ |
| `utils/settings-save.ts` | 78 | 중형 | ☐ |
| `utils/settings-page.ts` | 54 | 소형 | ☐ |
| `utils/sliderConvert.ts` | 9 | 소형 | ☐ |

**원칙 체크리스트**:
- [ ] P10: 타입 정의가 백엔드 모델과 일치함 (SSOT 관점)
- [ ] P16: 미사용 타입/유틸 함수 없음
- [ ] P23: 용어 사전 준수, 에러/비동기/네이밍/상수 패턴 파일 간 일관
- [ ] P24: 더 단순한 대체 가능성, 불필요한 추상화, 함수/파일 길이·복잡도 기준

---

## 6. 추천 세션 순서

> 의존성 하위 → 상위 + 중요도 P0 → P3 교차 적용

| 순서 | 세션 ID | 우선순위 | 내용 | 파일 수 | 예상 소요 |
|------|---------|----------|------|---------|-----------|
| 1 | B-01 | P0 | 주문 실행 경로 | 2 | 중간~장시간 |
| 2 | B-02 | P0 | 리스크 관리 및 서킷 브레이커 | 2 | 중간 |
| 3 | B-03 | P0 | Dry Run (테스트 모드 가상 주문) | 1 | 중간 |
| 4 | B-04 | P0 | 정산 엔진 및 거래 이력 | 2 | 중간~장시간 |
| 5 | B-05 | P0 | 자동매매 유효성 및 코어 큐 | 2 | 단시간 |
| 6 | B-06 | P1 | 엔진 루프 및 생명주기 | 3 | 중간~장시간 |
| 7 | B-07 | P1 | WS 시세 처리 | 5 | 장시간 |
| 8 | B-08 | P1 | 엔진 부트스트랩/캐시/스냅샷 | 5 | 중간 |
| 9 | B-09 | P1 | 엔진 섹터 확인/전략/레이더 | 5 | 중간 |
| 10 | B-10 | P1 | 엔진 계좌/서비스 | 4 | 중간~장시간 |
| 11 | B-11 | P1 | 파이프라인 (Compute/Gateway) | 2 | 중간~장시간 |
| 12 | B-12 | P2 | DB 계층 | 4 | 중간 |
| 13 | B-13 | P2 | 설정 관리 | 5 | 중간 |
| 14 | B-14 | P2 | Broker 추상화 (공통) | 7 | 중간 |
| 15 | B-15 | P2 | 증권사 구현: 키움 | 5 | 장시간 |
| 16 | B-16 | P2 | 증권사 구현: LS | 3 | 장시간 |
| 17 | B-17 | P2 | Domain 계층 | 6 | 중간 |
| 18 | B-18 | P2 | 스케줄러 및 장마감 파이프라인 | 3 | 장시간 |
| 19 | B-19 | P2 | WS 구독 제어 및 업종 데이터 | 2 | 중간 |
| 20 | B-20 | P3 | 알림 (Telegram) | 3 | 중간 |
| 21 | B-21 | P3 | 기타 Core 유틸 | 11 | 중간 |
| 22 | B-22 | P3 | Web API 계층 | 14 | 중간~장시간 |
| 23 | B-23 | P3 | 테스트 품질 점검 | 66 | 중간 |
| 24 | F-01 | P0 | 통신 계층 및 상태 관리 | 8 | 중간~장시간 |
| 25 | F-02 | P1 | 진입점, 라우팅, 레이아웃 | 6 | 중간 |
| 26 | F-03 | P2 | 핵심 매매 페이지 | 6 | 중간~장시간 |
| 27 | F-04 | P2 | 설정 페이지 | 5 | 중간~장시간 |
| 28 | F-05 | P3 | 수익 페이지 | 3 | 중간 |
| 29 | F-06 | P3 | 공통 컴포넌트 | 21 | 장시간 |
| 30 | F-07 | P3 | 타입 및 유틸 | 5 | 단시간 |

> **총 30세션** | 백엔드 23세션 + 프론트엔드 7세션

### 세션 분할 가이드

- **컨텍스트 한계 대비**: 대형/초대형 파일이 많은 세션(B-07, B-15, B-16, B-18)은 필요시 2개 서브세션으로 분할 가능
- **분할 기준**: 1세션당 총 줄 수 1000줄 이상 시 분할 권장
- **분할 시**: 세션 ID에 `-a`, `-b` 접미사 (예: B-18-a, B-18-b)
- **HANDOVER.md 연동**: 세션 종료 시 진행 상태를 `HANDOVER.md`에 기록하여 다음 세션에서 이어서 작업

---

## 7. 발견된 문제 기록

> 점검 진행 중 발견된 아키텍처 위반 사항을 아래 표에 기록.  
> 각 문제는 고유 ID를 부여하고, 수정 시 상태를 갱신.

### 문제 기록 템플릿

| ID | 세션 | 파일:줄 | 위반 원칙 | 심각도 | 설명 | 상태 |
|----|------|---------|-----------|--------|------|------|
| — | — | — | — | — | (점검 전) | — |

### 심각도 분류

| 심각도 | 기준 |
|--------|------|
| **CRITICAL** | 자금 손실 위험, 데이터 정합성 위반, 실시간 파이프라인 중단 |
| **HIGH** | 아키텍처 원칙 위반 (P1~P3, P15, P16), 안전장치 미배선 |
| **MEDIUM** | 코드 품질 위반 (P5, P14, P19, P20), dead code |
| **LOW** | 스타일/가독성, 경미한 원칙 편차 |

### 상태 분류

| 상태 | 의미 |
|------|------|
| `발견` | 문제 식별됨, 미수정 |
| `수정중` | 수정 작업 진행 중 |
| `해결` | 근본 원인 해결 완료, 검증 통과 |
| `보류` | 사용자 승인 대기 또는 의존성 문제로 대기 |

---

### 발견된 문제 목록

| ID | 세션 | 파일:줄 | 위반 원칙 | 심각도 | 설명 | 상태 |
|----|------|---------|-----------|--------|------|------|
| B03-01 | B-03 | `dry_run.py:45-68` | P20/P22 | HIGH | `_refresh_positions_if_dirty`에서 dirty 플래그를 try 이전에 `False`로 설정 + silent except → 재구축 실패 시 stale 캐시 영속, 데이터 정합성 위반 | 해결 |
| B03-02 | B-03 | `dry_run.py:320-353` | P16 | MEDIUM | dead code 4개 함수 (`get_virtual_balance`, `get_virtual_deposit_setting`, `reset_virtual_balance`, `charge_virtual_balance`) — web routes가 settlement_engine 직접 호출하도록 변경되어 잔존 | 해결 |
| B03-03 | B-03 | `dry_run.py:312-317, 130, 171` | P16/P20 | MEDIUM | `_estimate_market_price` 도달 불가 (호출자가 항상 price > 0 보장) + price=0 폴백이 가짜 체결가 0을 조용히 허용 | 해결 |
| B04-01 | B-04 | `trade_history.py:34-66` | P20 | HIGH | `_ensure_loaded`에서 `_loaded = True`를 try 블록 이전에 설정 → DB 로드 실패 시 후속 호출이 재시도하지 않음, empty history로 세션 전체 진행 → 체결 이력 누락 | 해결 |
| B04-02 | B-04 | `stock_tables.py:123-138`, `settlement_engine.py:176-231` | P20/P22 | CRITICAL | `load_settlement_state`가 "행 없음"과 "DB 에러"를 구분하지 않고 모두 None 반환 (silent except) + `_load`가 None을 신규 설치로 간주하고 기본값으로 초기화 후 영속화 → 일시적 DB 에러 시 실제 정산 상태가 기본값으로 덮어씌워짐 → 자금 손실 | 해결 |
| B04-03 | B-04 | `trade_history.py:388-401` | P20 | MEDIUM | `_lookup_sector`가 DB 에러 시 "미분류" 폴백 반환 → "행 없음"과 "DB 에러"를 구분하지 않음, 정상 데이터를 폴백으로 덮음 | 해결 |
| B04-04 | B-04 | `trade_history.py:69-71, 156-177, 249-256, 654-656` | P16 | MEDIUM | dead code 5개 함수 (`_migrate_from_json`, `_patch_sell_history`, `start/stop_consumer_task`, `close_db_connection`) — no-op이거나 앱 코드에서 호출되지 않음 | 해결 |
| B04-05 | B-04 | `settlement_engine.py`, `trade_history.py` | P22 | HIGH | 기동 시 정산 상태(`_orderable`)와 거래 이력으로 역산한 값 간 대조(reconciliation) 없음 → B04-02 폴백 문제와 결합 시 자금 손실 위험. B06-02 해결로 `_reconciliation_on_startup` 미구현 함수 제거됨 — 실전투자 모드는 증권사 서버가 SSOT이므로 별도 대조 불필요 (사용자 결정) | 해결 |
| B05-01 | B-05 | `auto_trading_effective.py:38-43` | P20/P21 | MEDIUM | `_in_time_range`에서 `except Exception: return False` — 설정 키 누락/오류 시 매수·매도 조용히 차단, 사용자가 차단 원인 인지 불가 | 해결 |
| B05-02 | B-05 | `auto_trading_effective.py:46-52` | P16 | MEDIUM | `schedule_allows_auto_trading` dead code — 함수 정의만 있고 호출처 전무 (grep 확인) | 해결 |
| B05-03 | B-05 | `auto_trading_effective.py:4` | P10 | LOW | docstring이 제거된 필드 `auto_trade_on`을 참조 — migration 코드는 `settings_file.py`에 별도 존재, 혼란 유발 | 해결 |
| B05-04 | B-05 | `core_queues.py:7`, `ARCHITECTURE.md:53,265` | P16/P10 | MEDIUM | docstring이 "5개 코어 큐"라고 기술하고 `order_queue`를 나열하나 실제 4개 큐만 존재 — `order_queue` 변수/함수/상수 전무, ARCHITECTURE.md도 같은 불일치 | 해결 |
| B05-05 | B-05 | `core_queues.py:108-128`, `engine_lifecycle.py:83` | P16/P22 | MEDIUM | `clear_all_queues` dead code — `stop_engine()`에서 호출되지 않아 엔진 재기동 시 stale 큐 데이터 잔존 가능 | 해결 |
| B05-06 | B-05 | `core_queues.py:22`, `ARCHITECTURE.md:444,475` | P10 | LOW | `tick_queue` size 불일치 — 코드는 20000, ARCHITECTURE.md는 5000으로 기술 | 해결 |
| F01-01 | F-01 | `uiStore.ts:85-87,22,65` | P16 | MEDIUM | `setConnected()` 함수 + `connected` 상태 dead code. 로컬 앱에서 WS 연결 상태 칩 불필요 (사용자 결정) — 함수 및 상태 제거 | 해결 |
| F01-02 | F-01 | `uiStore.ts:93-95` | P16 | MEDIUM | `setEngineReady()` 함수 정의만 있고 호출처 전무. `engineReady`는 `applyInitialSnapshotUI`에서만 갱신 | 해결 |
| F01-03 | F-01 | `uiStore.ts:190-194`, `binding.ts` | P16/P21 | HIGH | `applyWsConnectionStatus()` 정의되었으나 배선되지 않음. 로컬 앱에서 WS 연결 상태 칩 불필요 (사용자 결정) — 함수 제거. 증권사 WS 상태는 `broker_statuses` 기반 헤더 칩으로 표시 중 | 해결 |
| F01-04 | F-01 | `uiStore.ts:19,64` | P16/P10 | MEDIUM | `uiStore.positionCount`가 한 번도 갱신되지 않음. `hotStore.positionCount`가 실제 SSOT. 중복 상태 | 해결 |
| F01-05 | F-01 | `uiStore.ts:25,68,90` | P16/P21 | MEDIUM | `backfilling` 상태가 `ws.ts`에서 갱신되나 어떤 화면 컴포넌트도 읽지 않음. 로컬 앱에서 재연결 중 칩 불필요 (사용자 결정) — 상태, 함수, `_hasConnectedOnce` 전부 제거 | 해결 |
| F01-06 | F-01 | `uiStore.ts:175-181` | P16 | LOW | `applyTestDataResetCompleted`에 `console.log` 디버그 로그 3개 잔존 | 해결 |
| F01-07 | F-01 | `client.ts:17-44,68-73` | P16/P20 | MEDIUM | `getTokenExp`(주석), `isAuthenticated`(항상 true), `forceLogout`(no-op), `setToken`/`clearToken`(호출처 전무), 401 처리(console.warn만) — 인증 dead code 일괄 제거 | 해결 |
| F01-08 | F-01 | `binding.ts` (V-02 보류) | P21 | HIGH | `circuit_breaker_open` 이벤트 미배선 — 백엔드 `trading.py:293,484`에서 서킷브레이커 OPEN 시 브로드캐스트하나 프론트엔드 수신 핸들러 없음 → 사용자가 리스크 차단을 UI에서 인지 불가 | 해결 |
| F01-09 | F-01 | `ws.ts:122` | P20/P21 | MEDIUM | `ws.onerror = () => {}` — WebSocket 에러를 조용히 무시. `console.error` 로깅 추가 | 해결 |
| F01-10 | F-01 | `binding.ts:71-73,192-194` | P21 | LOW | WS `onDisconnected` 콜백이 빈 함수. 로컬 앱에서 연결 해제 칩 불필요 (사용자 결정) — 빈 콜백 유지, 별도 화면 표시 없음 | 해결 |
| B06-01 | B-06 | `engine_lifecycle.py:378-380`, `engine_ws_dispatch.py:152-158` | P16 | MEDIUM | `_delayed_resubscribe_stock_after_rate_limit` no-op 함수 (`pass`만 존재) + 호출부에서 태스크 생성·done_callback·try/except 전부 dead code. 시장가 운용으로 재구독 불필요 → 함수 + 호출부 + 미사용 import 제거 | 해결 |
| B06-02 | B-06 | `engine_lifecycle.py:237-302` | P16/P21 | HIGH | `_reconciliation_on_startup` 미구현 — 서버 체결 내역 조회 후 실제 대조 없이 "원장 대조 완료" 로그 + `{"status":"success"}` UI 브로드캐스트 (프론트엔드 수신부 없음). 실전투자 모드는 증권사 서버가 SSOT이므로 별도 대조 불필요 → 함수 제거, 테스트모드 포지션 구축 로직만 `start_engine`에 인라인 유지 | 해결 |
| B06-03 | B-06 | `engine_state.py:131-133` | P16 | LOW | `_on_filter_settings_changed` module-level 래퍼 — `state.on_filter_settings_changed()` 메서드와 기능 중복, 프로덕션에서 호출처 전무 (테스트는 `sector_data_provider` 직접 import) → 래퍼 제거 | 해결 |
| B06-04 | B-06 | `engine_lifecycle.py:325-328` | P10 | LOW | `get_current_kst_time`가 `datetime.now()` (로컬 시간) 사용 — 함수명/주석은 KST이나 실제로 KST 아님. `constants.py`의 `_KST` 상수 import하여 `datetime.now(_KST)`로 수정 | 해결 |
| B08-01 | B-08 | `engine_bootstrap.py:15` | P16 | MEDIUM | `_subscribe_semaphore` — 정의만 있고 사용처 전무, 구독 루프 제거 후 잔존 | 해결 |
| B08-02 | B-08 | `engine_bootstrap.py:18-45` | P16 | MEDIUM | `BOOTSTRAP_STAGES` + `_broadcast_bootstrap_stage` — 프로덕션 호출처 전무, 테스트에서만 호출 | 해결 |
| B08-03 | B-08 | `engine_bootstrap.py:51-112` | P16 | MEDIUM | `_deferred_sector_summary` — 프로덕션 호출처 전무, 테스트에서만 호출 | 해결 |
| B08-04 | B-08 | `engine_bootstrap.py:115-129` | P16 | MEDIUM | `_notify_close_data_ui` — 프로덕션 호출처 전무, 테스트에서만 호출 | 해결 |
| B08-05 | B-08 | `engine_bootstrap.py:48` | P23 | LOW | 삭제된 함수 `_bootstrap_sector_stocks_async` 참조 주석 잔존 | 해결 |
| B08-06 | B-08 | `engine_bootstrap.py:200-203` | P16/P24 | MEDIUM | `_run_sector_reg_pipeline` 래퍼 — 프로덕션에서 engine_ws 직접 import, 래퍼는 테스트만 사용 | 해결 |
| B08-07 | B-08 | `engine_snapshot.py:214-242` | P16 | MEDIUM | `get_position_pnl_pct_for_code` — 프로덕션 호출처 전무, 테스트에서만 호출 | 해결 |
| B08-08 | B-08 | `engine_cache.py:14` | P16 | MEDIUM | `_subscribe_semaphore` — 정의만 있고 사용처 전무 | 해결 |
| B08-09 | B-08 | `engine_cache.py:87-93` | P16/P20 | MEDIUM | `_cached_avg is not None` — 항상 dict이므로 None 불가, else 분기 dead code | 해결 |
| B08-10 | B-08 | `engine_cache.py:111` | P23 | LOW | 삭제된 함수 `_bootstrap_sector_stocks_async` 참조 주석 잔존 | 해결 |
| B08-11 | B-08 | `engine_config.py:26-29` | P20/P24 | MEDIUM | `get_settings_snapshot` if/else 양 분기가 동일 코드 (`dict(state.integrated_system_settings_cache)`) | 해결 |
| B08-12 | B-08 | `engine_config.py:141-149` | P16 | MEDIUM | `get_connection_level_keys` — 정의만 있고 호출처 전무 | 해결 |
| B08-13 | B-08 | `daily_time_scheduler.py:867` | P4 | HIGH | `cm.get_connector("kiwoom")` 하드코딩 → broker 확인 + `state.connector_manager or state.active_connector` | 해결 |
| B08-14 | B-08 | `market_close_pipeline.py:126` | P4 | HIGH | `cm.get_connector("kiwoom")` 하드코딩 → `state.connector_manager or state.active_connector` | 해결 |
| B09-01 | B-09 | `engine_radar.py:19-29` | P16 | MEDIUM | `get_subscribed_stocks` — 프로덕션 호출처 전무 | 해결 |
| B09-02 | B-09 | `engine_radar.py:32-34` | P16 | MEDIUM | `get_sector_layout` — 프로덕션 호출처 전무 | 해결 |
| B09-03 | B-09 | `engine_radar.py:37-40` | P16 | MEDIUM | `get_avg_trade_amount_5d_map` — 프로덕션 호출처 전무 | 해결 |
| B09-04 | B-09 | `engine_radar.py:77-94` | P16 | MEDIUM | `merge_live_price_to_radar_row` — 프로덕션 호출처 전무 | 해결 |
| B09-05 | B-09 | `engine_radar.py:135-155` | P16 | MEDIUM | `_mark_radar_exited` — 프로덕션 호출처 전무 | 해결 |
| B09-06 | B-09 | `engine_radar.py:158-160` | P16 | LOW | `clear_exited_from_radar` — 항상 0 반환, 호출처 전무 | 해결 |
| B09-07 | B-09 | `engine_radar.py:163-165` | P16 | LOW | `_drop_rest_radar_quote_for_nk` — pass만 존재, 호출처 전무 | 해결 |
| B09-08 | B-09 | `engine_radar.py:168-174` | P16 | LOW | `_clear_radar_rest_bootstrap_for_stk_cd` — pass만 존재, _mark_radar_exited에서만 호출 (동시 제거) | 해결 |
| B09-09 | B-09 | `engine_radar.py:177-185` | P16 | MEDIUM | `_clear_radar_and_ready_memory` — 프로덕션 호출처 전무 | 해결 |
| B09-10 | B-09 | `engine_radar.py:188-208` | P16 | MEDIUM | `_tracked_ui_stock_codes` — 프로덕션 호출처 전무 | 해결 |
| B09-11 | B-09 | `engine_strategy_core.py:15-21` | P16 | LOW | `_is_placeholder_stock_name` — resolve_radar_display_name에서만 호출 (동시 제거) | 해결 |
| B09-12 | B-09 | `engine_strategy_core.py:24-44` | P16 | MEDIUM | `resolve_radar_display_name` — 프로덕션 호출처 전무 | 해결 |
| B09-13 | B-09 | `engine_symbol_utils.py:65-70` | P16 | LOW | `_to_al_stk_cd` — 테스트에서만 호출 | 해결 |
| B09-14 | B-09 | `engine_symbol_utils.py:73-75` | P16 | LOW | `is_nxt_code` — 테스트에서만 호출 | 해결 |
| B09-15 | B-09 | `engine_radar_ops.py:9-49` | P16 | MEDIUM | `overlay_radar_row_with_live_price` — merge_live_price_to_radar_row에서만 호출 (동시 제거) | 해결 |
| B09-16 | B-09 | `engine_radar_ops.py:52-70` | P16 | MEDIUM | `apply_real01_volume_amount_to_radar_rows` — 테스트에서만 호출 | 해결 |
| B09-17 | B-09 | `engine_sector_confirm.py:26-28` | P16 | LOW | `is_engine_running_internal` — 테스트에서만 호출 | 해결 |
| B09-18 | B-09 | `engine_sector_confirm.py:403-405` | P16 | LOW | `flush_pending_recompute` — 호환용 래퍼, 테스트에서만 호출 | 해결 |
| B09-19 | B-09 | `engine_radar.py:70-71` | P20 | MEDIUM | `get_orderbook_cache` silent except → 로깅 추가 (데이터 정합성 가시화) | 해결 |
| B09-20 | B-09 | `engine_radar.py:45,51,57,63` | P23 | LOW | 함수 내 중복 `from ... import state` 4건 (상단 import 사용) | 해결 |
| B09-21 | B-09 | `engine_strategy_core.py:64` | P23 | LOW | 삭제된 `register_pending_stock` 참조 주석 잔존 | 해결 |
| B10-01 | B-10 | `engine_account_rest.py:111-232, 312-400` | P4 | HIGH | 키움 전용 파싱 함수 5개(`parse_kt00001_deposit`, `parse_kt00018_balance`, `real04_official_account_delta`, `real04_official_apply_position_line`, `_real04_is_stock_item`)가 공통 services 파일에 위치. docstring에 "키움 공식" 명시. LS는 `ls_providers.py`에 별도 Provider 존재하므로 키움 파싱도 `kiwoom_providers.py`로 이동 필요 | 해결 (B-10-b: `kiwoom_account_parsing.py`로 이동, 호출처 import 변경) |
| B10-02 | B-10 | `engine_account_rest.py:26-400` vs `kiwoom_providers.py:96-214` | P10 | MEDIUM | 키움 계좌 파싱 로직이 두 곳에 중복 구현(`_fetch_account_data` 경로 vs `KiwoomAccountProvider.get_account_balance`). 단일 진실 소스 위반 (kiwoom_providers.py 구현은 B-14 범위에서 별도 dead code 조사 필요) | 이월 (B-14) |
| B10-03 | B-10 | `engine_account_notify.py:51-59` | P16 | MEDIUM | 8개 레거시 데스크톱 콜백 변수(`_desktop_*_notifier`) — 정의만 있고 대입/참조 전무 | 해결 (B-10-a) |
| B10-04 | B-10 | `engine_account_notify.py:112-171` | P16 | MEDIUM | 11개 no-op 함수(7개 `register_desktop_*` + 4개 `register/unregister_*_ws_queue`) — 호출처 전무 | 해결 (B-10-a) |
| B10-05 | B-10 | `engine_account_notify.py:401-405` | P16 | MEDIUM | `notify_desktop_buy_radar_only()` no-op(`pass`) — app/ 내 호출처 전무 (ARCHITECTURE.md:276에 이미 지적) | 해결 (B-10-a) |
| B10-06 | B-10 | `engine_account_notify.py:447-452` | P16 | MEDIUM | `notify_desktop_account_tabs_refresh()` — app/ 및 tests 전체에서 호출처 전무 | 해결 (B-10-a) |
| B10-07 | B-10 | `engine_account_notify.py:365-392` | P16 | MEDIUM | `notify_raw_real_data()` — 프로덕션 호출처 전무(테스트만). real-data는 `pipeline_compute.py:608`에서 `broadcast_queue` 경로로 전송 | 해결 (B-10-a) |
| B10-08 | B-10 | `engine_account_notify.py:623-626` | P16/P10 | MEDIUM | `notify_ws_subscribe_status()` — 프로덕션 호출처 전무(테스트만). docstring은 "ws_subscribe_control._set_status()에서 사용"이라고 기술하나 실제는 `_broadcast` 직접 호출 → 주석/코드 불일치 | 해결 (B-10-a) |
| B10-09 | B-10 | `engine_account.py:257-261, 390-393` | P16 | MEDIUM | `if state.refresh_account_snapshot_meta:` / `if state.update_account_memory:` 분기 — `engine_state.py:40-41`에서 `None` 초기화 후 다른 곳에서 대입 전무 → 항상 False인 dead 분기 | 해결 (B-10-a) |
| B10-10 | B-10 | `engine_account.py:401-402` | P20/P21 | HIGH | `_apply_balance_realtime`에서 `except Exception: pass` — 잔고 업데이트 후 매수 재평가(`evaluate_buy_candidates`) 실패 시 조용히 무시. 사용자가 "왜 잔고 회복 후에도 매수가 안 되지?" 인지 불가 | 해결 (B-10-a) |
| B10-11 | B-10 | `engine_service.py:215-216` | P20/P21 | HIGH | `apply_settings_change` 끝 `except Exception: pass` — 설정 변경 후 매수 스냅샷 무효화(`invalidate_buy_snapshot`) 실패 시 조용히 무시. 설정 변경 후 매수 재평가 안 됨을 사용자가 인지 불가 | 해결 (B-10-a) |
| B10-12 | B-10 | `engine_account_notify.py` 전체 | P24 | MEDIUM | 파일 632줄 — 500줄 초과 | 해결 (B-10-b: 412줄 + `engine_account_broadcast.py` 124줄로 분할) |
| B10-13 | B-10 | `engine_service.py:30-216` | P24 | MEDIUM | `apply_settings_change` 함수 186줄 — 50줄 초과(설정 키 그룹별 분리 필요) | 해결 (B-10-b: 49줄 + 10개 그룹 헬퍼로 분리) |
| B10-14 | B-10 | `engine_account.py:113-195` | P24 | MEDIUM | `_fetch_account_data` 함수 82줄 — 50줄 초과 | 해결 (B-10-b: 46줄 + 3개 헬퍼로 분리) |
| B10-15 | B-10 | `engine_account_notify.py:268-342` | P24 | MEDIUM | `notify_desktop_sector_score` 함수 74줄 — 50줄 초과 | 해결 (B-10-b: 32줄 + 4개 페이로드 헬퍼로 분리) |
| B10-16 | B-10 | `engine_account_notify.py:455-519` | P24 | MEDIUM | `broadcast_account_update` 함수 64줄 — 50줄 초과 | 해결 (B-10-b: 15줄 + 3개 헬퍼, `engine_account_broadcast.py`로 이동) |
| B10-17 | B-10 | `engine_account.py:215-275` | P24 | MEDIUM | `_update_account_memory_inner` 함수 60줄 — 50줄 초과 | 해결 (B-10-b: 15줄 + 2개 헬퍼로 분리) |
| B11-01 | B-11 | `pipeline_compute.py` 전체 863줄 | P24 | MEDIUM | 파일 500줄 기준 초과 → 틱 핸들러/코얼레싱을 `pipeline_compute_tick_handlers.py`(320줄)로 분리. 본 파일 672줄(수신율 로직은 테스트가 모듈 전역을 직접 참조하여 추가 분할 시 테스트 대폭 수정 필요 — 잔여 172줄 초과분은 B-11-b에서 별도 검토) | 해결 (B-11-a) |
| B11-02 | B-11 | `pipeline_compute.py:556-663` `_handle_real_01_tick` 108줄 | P24 | MEDIUM | 함수 50줄 초과 — 5단계(전송/레이더/보유종목/매도/지연) 중 3단계를 헬퍼로 분리(`_apply_01_radar_and_receive_rate`, `_apply_01_price_to_positions`, `_check_01_auto_sell`) | 해결 (B-11-a: ~50줄 + 3개 헬퍼) |
| B11-03 | B-11 | `pipeline_compute.py:740-862` `_sector_recompute_loop_impl` 123줄 | P24 | MEDIUM | 함수 50줄 초과 — Phase 1/Phase 2 분리 + 임계값 판정 헬퍼 추출(`_phase1_wait_threshold`, `_evaluate_threshold`, `_phase2_batch_recompute_loop`) | 해결 (B-11-a: 본체 8줄 + 3개 헬퍼) |
| B11-04 | B-11 | `pipeline_compute.py:278-346` `_compute_loop_impl` 69줄 | P24 | MEDIUM | 함수 50줄 초과 — control 드레인/배치 처리 헬퍼 분리(`_drain_control_queue`, `_process_tick_batch`) | 해결 (B-11-a: ~40줄 + 2개 헬퍼) |
| B11-05 | B-11 | `pipeline_compute.py:349-408` `_process_control_signal` 60줄 | P24 | MEDIUM | 함수 50줄 초과 — DYNAMIC_REG/DYNAMIC_UNREG 헬퍼 분리(`_handle_dynamic_reg`, `_handle_dynamic_unreg`) | 해결 (B-11-a: ~35줄 + 2개 헬퍼) |
| B11-06 | B-11 | `pipeline_compute.py:473-538` `_handle_real_tick` 66줄 | P24 | MEDIUM | 함수 50줄 초과 — 아이템 추출/디스패치 헬퍼 분리(`_extract_real_items`, `_dispatch_real_item`) | 해결 (B-11-a: ~18줄 + 2개 헬퍼) |
| B11-07 | B-11 | `pipeline_compute.py:223-275` `_coalesce_batch` 53줄 | P24 | LOW | 함수 50줄 초과 (경미) — 내부 아이템 코얼레싱 헬퍼 분리(`_coalesce_real_items`) | 해결 (B-11-a: ~30줄 + 1개 헬퍼) |
| B11-08 | B-11 | `pipeline_compute_tick_handlers.py:275-278` (이관) | P20 | MEDIUM | `except ValueError: tval = 0` — 잘못된 PGM 데이터를 0으로 조용히 대체. 사용자가 프로그램 순매수 0을 실데이터로 오인 | 해결 (B-11-b: `tval` 누락/오류 시 로깅+스킵, 0 대체 제거) |
| B11-09 | B-11 | `pipeline_compute_tick_handlers.py:247` (이관) | P20 | MEDIUM | `state.master_stocks_cache.get(nk, {})` 빈 dict 폴백 — "캐시 미스(비정상)"와 "미구독 종목(정상)" 구분 불가 | 해결 (B-11-b: `nk in cache` 명시적 분기, 캐시 미스 시 로깅+스킵) |
| B11-10 | B-11 | `pipeline_compute_tick_handlers.py:281` (이관) | P20 | MEDIUM | 동일 `get(nk, {})` 폴백 (PGM 핸들러) | 해결 (B-11-b: B11-09와 동일 패턴 적용) |
| B11-11 | B-11 | `pipeline_compute.py:548-610` Phase 1 루프 | P11 | HIGH | `while + asyncio.sleep(1.0)` 폴링으로 수신율 임계값 대기 — `asyncio.Event` 기반 전환 가능 (사용자 설계 로직, 규칙 0-5 적용) | 해결 (B-11-b: 사용자 승인 대안1 — `LazyEvent.wait()` + 200ms 디바운스 전환, `reset_sector_threshold`에서 이벤트 클리어) |
| B11-12 | B-11 | `pipeline_compute.py:195-196` `start_compute_loop` | P16/P21 | HIGH | `create_task()` 후 `add_done_callback` 미설정 — compute/sector_recompute 태스크 조용히 사망 시 사용자 인지 불가. gateway 루프(`app.py:63`)는 설정되어 있어 비일관 (P23) | 해결 (B-11-a: `add_done_callback` 추가, gateway 루프와 일관) |

---

## 8. 점검 진행 현황 요약

### 세션별 진행 상태

| 세션 ID | 우선순위 | 내용 | 상태 |
|---------|----------|------|------|
| B-01 | P0 | 주문 실행 경로 | ☑ 완료 (8건 수정) |
| B-02 | P0 | 리스크 관리 및 서킷 브레이커 | ☑ 완료 (3건 수정) |
| B-03 | P0 | Dry Run | ☑ 완료 (3건 수정) |
| B-04 | P0 | 정산 엔진 및 거래 이력 | ☑ 완료 (4건 수정) |
| B-05 | P0 | 자동매매 유효성 및 코어 큐 | ☑ 완료 (6건 수정, 378 tests passed) |
| B-06 | P1 | 엔진 루프 및 생명주기 | ☑ 완료 (4건 수정, 271 tests passed) |
| B-07 | P1 | WS 시세 처리 | ☑ 완료 (7건 수정, 140 tests passed) |
| B-08 | P1 | 엔진 부트스트랩/캐시/스냅샷 | ☑ 완료 (14건 수정, 261 tests passed) |
| B-09 | P1 | 엔진 섹터 확인/전략/레이더 | ☑ 완료 (24건 수정, 2714 tests passed) |
| B-10 | P1 | 엔진 계좌/서비스 | ◐ B-10-a 완료 (11건 수정), B-10-b 대기 (6건) |
| B-11 | P1 | 파이프라인 (Compute/Gateway) | ☑ 완료 (B-11-a 8건 + B-11-b 4건 = 12건 수정, 2964 tests passed) |
| B-12 | P2 | DB 계층 | ☐ 미시작 |
| B-13 | P2 | 설정 관리 | ☐ 미시작 |
| B-14 | P2 | Broker 추상화 (공통) | ☐ 미시작 |
| B-15 | P2 | 증권사 구현: 키움 | ◐ B-15-a 완료 (7건 수정), B-15-b 대기 (3파일) |
| B-16 | P2 | 증권사 구현: LS | ☐ 미시작 |
| B-17 | P2 | Domain 계층 | ☑ 완료 (3건 P16/P24) |
| B-18 | P2 | 스케줄러 및 장마감 파이프라인 | ☐ 미시작 |
| B-19 | P2 | WS 구독 제어 및 업종 데이터 | ☐ 미시작 |
| B-20 | P3 | 알림 (Telegram) | ☐ 미시작 |
| B-21 | P3 | 기타 Core 유틸 | ☐ 미시작 |
| B-22 | P3 | Web API 계층 | ☐ 미시작 |
| B-23 | P3 | 테스트 품질 점검 | ☐ 미시작 |
| F-01 | P0 | 통신 계층 및 상태 관리 | ☑ 완료 (10건 수정, V-02 해결, 112 tests passed) |
| F-02 | P1 | 진입점, 라우팅, 레이아웃 | ☐ 미시작 |
| F-03 | P2 | 핵심 매매 페이지 | ☐ 미시작 |
| F-04 | P2 | 설정 페이지 | ☐ 미시작 |
| F-05 | P3 | 수익 페이지 | ☐ 미시작 |
| F-06 | P3 | 공통 컴포넌트 | ☐ 미시작 |
| F-07 | P3 | 타입 및 유틸 | ☐ 미시작 |

### 진행률

| 항목 | 카운트 |
|------|--------|
| 전체 세션 | 30 |
| 완료 | 14 (B-01~B-14, F-01) |
| 진행 중 | 2 (B-10-a 완료/B-10-b 대기, B-15-a 완료/B-15-b 대기) |
| 미시작 | 14 |
| 발견된 문제 | 78 |
| 해결된 문제 | 70 |
| 보류된 문제 | 0 |

---

## 9. 점검 완료 정의

본 계획서의 모든 점검이 "완료"로 간주되려면:

1. **30개 세션 모두 완료 표시** (☑)
2. **발견된 모든 CRITICAL/HIGH 문제가 `해결` 상태**
3. **22개 불변 원칙에 대해 전체 코드베이스 위반 사항 0건 확인**
4. **백엔드 런타임 기동 검증 통과** (`main.py` 정상 구동)
5. **프론트엔드 빌드 검증 통과** (`npm run build` 성공)
6. **테스트 스위트 통과** (`pytest` 전체 성공)
