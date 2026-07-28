# 태스크 파일: 매수 근거 통합 컬럼 구현

> **상태**: 태스크 분할 완료 (구현 미진행 — 규칙 0 준수, 승인 대기)
> **작성일**: 2026-07-28
> **설계서 경로**: `docs/buy-reason-column-design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ · 2세션(태스크 분할) ✅ · 3세션~(구현) 예정
> **관련 원칙**: P10(SSOT), P15(단일 주문 경로), P16(살아있는 경로), P18(테스트모드 동등성), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(용어 통일), P24(단순성), P25(격리된 실패)
> **관련 스킬**: `db-backup`(세션 2), `safe-trade`(세션 3·4), `backend-fix`(세션 1~4), `frontend-fix`(세션 5)

---

## 0. 사전조사 결과 요약

### 0.1 의존성 (수정 파일 + 변경점 + 기준 라인)

| 파일 | 변경점 | 기준 라인 |
|------|--------|-----------|
| `backend/app/domain/models.py` | `StockScore`에 개별 트리거 필드 4개 추가 (`boost_high_triggered` 등) | 10-27 |
| `backend/app/services/buy_filter.py` | `calculate_boost_score()` 내 각 조건 만족 시 트리거 필드 True 설정 | 8-64 (설계서 인용) |
| `backend/app/db/stock_tables.py` | `migrate_add_buy_reason_columns_to_trades()` 신규 추가 (ALTER TABLE 8개) | 260-277(기존 패턴) |
| `backend/app/web/app.py` | 신규 마이그레이션 함수 import + 기동 시 호출 | 48, 53 |
| `backend/app/services/trade_history.py` | `_TRADE_INSERT_SQL` 컬럼 8개 추가, `_trade_params()` 8개 필드 추출, `record_buy()` 시그니처 확장 + rec 8개 필드 | 78-96, 248-293 |
| `backend/app/services/trading.py` | `execute_buy()` 시그니처 확장(근거 데이터 전달), `_buy_reason = reason or "자동매수"` 폴백 제거, `record_buy()` 호출에 근거 전달 | 256-257, 517-524 |
| `backend/app/services/buy_order_executor.py` | `bt.stock`에서 근거 데이터 추출 전달, reason 문자열 생성 제거(빈 문자열 명시) | 229-232 |
| `frontend/src/pages/profit-columns.ts` | `parseBuyReasonSector`/`parseBuyReasonRank` 정규식 파싱 제거 → 구조화 컬럼 직접 표시 | 9-19, 37-39 |

### 0.2 영향 범위

- **백엔드 모델**: `StockScore` 필드 추가 → `StockScore` 인스턴스 생성·직렬화 경로 전체(WS 전송, 엔진 스코어링)에 필드 노출. 기본값 `False`이므로 기존 동작 영향 없음(P25 격리).
- **DB 스키마**: `trades` 테이블 컬럼 8개 추가. 기존 레코드는 NULL(매수 근거 미적용 — P20 폴백 아님). 매도 레코드도 NULL. `db-backup` 스킬 필수(안전 규칙 2).
- **거래 로직(기록 경로)**: `execute_buy()` → `record_buy()` 경로는 유지(P15). 근거 **데이터 전달만 추가**, 주문 발생·리스크 검사·가드 조건 변경 없음. `safe-trade` 스킬 필수(P15/P16/P18 점검).
- **프론트엔드**: 수익 상세 페이지 매수 테이블 "업종"·"매수순위" 컬럼 표시 방식 변경(reason 파싱 → 구조화 컬럼). 신규 가산점 컬럼(고가돌파·뉴스·잔량비율·프로그램) 표시 추가 여부는 사용자 결정(§2 항목 1).
- **테스트**: 백엔드(buy_filter, trade_history, buy_order_executor) + 프론트엔드(profit-columns) 기존 테스트 영향. 신규 테스트 케이스 추가(§3).

### 0.3 아키텍처 원칙 부합

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10(SSOT) | ✅ 개선 | reason 문자열 파싱 제거 → 구조화 컬럼 단일 진실 소스. 개별 트리거 상태 `StockScore`에 보존(옵션 1) |
| P15(단일 주문 경로) | ✅ 유지 | `execute_buy()` → `record_buy()` 경로 변경 없음, 근거 데이터 전달만 추가 |
| P16(살아있는 경로) | ✅ | 근거 데이터가 `buy_order_executor` → `execute_buy` → `record_buy` → DB까지 단일 배선. dead field(전달되나 미사용) 금지 |
| P18(테스트모드 동등성) | ✅ | 테스트/실전 모두 동일하게 구조화 근거 저장. 모드 분기 없음 |
| P20(폴백 금지) | ✅ 개선 | `reason or "자동매수"` 폴백 제거. 과거 레코드 NULL 명시적 처리(빈 값 그대로) |
| P21(사용자 투명성) | ✅ 개선 | 매수 근거(어떤 가산점이 기여했는지) 사용자 열람 가능 |
| P22(데이터 정합성) | ✅ | 컬럼 타입 보장, 매수 결정 시점 트리거 상태 보존(옵션 1) |
| P23(용어 통일) | ✅ | "업종"(not 섹터), "매수"(not Buy), "종목"(not 주식) — 컬럼명·표시 텍스트 준수 |
| P24(단순성) | ✅ | 별도 테이블(옵션 D) 대신 단일 테이블 컬럼 추가. 불리언(옵션 A) 채택 |
| P25(격리된 실패) | ✅ | 마이그레이션 실패 시 해당 컬럼 NULL, 기존 체결 이력 조회 영향 없음 |

### 0.4 기존 공통 자산 확인

- **마이그레이션 패턴**: `migrate_add_buy_date_to_trades()`(`stock_tables.py:260-277`) — `PRAGMA table_info` → `ALTER TABLE ADD COLUMN` → `commit`. 신규 마이그레이션도 동일 패턴 재사용(신규 함수 신규 생성 불가피 — 컬럼 8개 일괄 추가).
- **INSERT SQL 패턴**: `_TRADE_INSERT_SQL` + `_trade_params()` 기존 구조 재사용 — 컬럼 8개·placeholder 8개·필드 8개 추가만.
- **프론트 공통 자산**: `profit-columns.ts`의 `ColumnDef` 패턴, `components/common/ui-styles` 색상/포매터 재사용. 신규 컬럼 추가 시 동일 `ColumnDef` 구조 따름.

---

## 1. 단계 분할 (세션당 1단계 — 규칙 0-1)

> 각 세션은 독립적으로 완료·검증 가능한 크기. 검증 통과 시 커밋 + HANDOVER 갱신 + 사용자 보고 후 세션 종료.

### 세션 1: 백엔드 모델 + 가산점 트리거 보존

**목표**: `StockScore`에 개별 가산점 트리거 필드 4개 추가, `calculate_boost_score()`에서 트리거 시 필드 설정.

**수정 파일**:
- `backend/app/domain/models.py` — `StockScore`에 `boost_high_triggered`, `boost_news_triggered`, `boost_order_ratio_triggered`, `boost_program_triggered` (bool, 기본값 `False`) 추가
- `backend/app/services/buy_filter.py` — `calculate_boost_score()` 내 각 조건 만족 시 해당 트리거 필드 `True` 설정 (합산 로직은 유지, 필드 설정만 추가)

**검증 방법**:
- `py_compile` + `ruff` (구문/린트)
- `.venv/bin/python -m pytest backend/tests -q` (기존 buy_filter 테스트 통과 + 트리거 필드 설정 확인)
- `.venv/bin/python main.py` 런타임 기동 (StockScore 직렬화·WS 전송 정상)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증)

**적용 스킬**: `backend-fix` (모델 변경). safe-trade 해당 없음(매수 로직 아님, 스코어링 보존만).

**P원칙 점검**: P10(트리거 상태 보존), P22(매수 결정 시점 정합성), P25(기본값 False로 기존 동작 영향 없음)

---

### 세션 2: DB 마이그레이션 (db-backup 필수)

**목표**: `trades` 테이블에 매수 근거 컬럼 8개 추가 마이그레이션 함수 작성 + 기동 시 호출.

**수정 파일**:
- `backend/app/db/stock_tables.py` — `migrate_add_buy_reason_columns_to_trades()` 신규 추가: `PRAGMA table_info(trades)`로 8개 컬럼 존재 확인 후 `ALTER TABLE ADD COLUMN` 8개 (`sector TEXT`, `sector_rank INTEGER`, `buy_rank INTEGER`, `boost_score REAL`, `boost_high INTEGER`, `boost_news INTEGER`, `boost_order_ratio INTEGER`, `boost_program INTEGER`). 기존 `migrate_add_buy_date_to_trades()` 패턴 준수.
- `backend/app/web/app.py` — 48번 줄 import에 `migrate_add_buy_reason_columns_to_trades` 추가, 53번 줄 이후 호출 추가

**db-backup 절차 (스킬 적용 — 안전 규칙 2)**:
1. 백엔드 실행 중이면 안전 종료 (`lsof -ti:8000` 확인, 잔존 프로세스 0건)
2. 타임스탬프 백업: `stocks.db`, `stocks.db-shm`, `stocks.db-wal` 3개 파일
3. 백업 파일 크기 > 0 확인
4. 마이그레이션 적용 (런타임 기동 시 자동)
5. 런타임 기동 + 핵심 데이터 조회(체결 이력, 잔고) 정상 확인
6. 백업 파일 삭제는 **사용자 승인 후** (규칙 0 — 파일 삭제 = 코드 제거와 동일 취급)

**검증 방법**:
- `py_compile` + `ruff`
- `.venv/bin/python -m pytest backend/tests -q` (마이그레이션 관련 테스트)
- `.venv/bin/python main.py` 런타임 기동 → 마이그레이션 로그 확인 + `PRAGMA table_info(trades)`로 8개 컬럼 존재 확인
- 기존 체결 이력 조회 정상 확인 (과거 레코드 NULL)

**적용 스킬**: `db-backup`(필수), `backend-fix`. safe-trade 해당 없음(스키마만, 주문 경로 미관여).

**P원칙 점검**: P22(컬럼 타입 보장), P25(마이그레이션 실패 시 NULL, 기존 데이터 영향 없음), 안전 규칙 2(백업 필수)

---

### 세션 3: record_buy + INSERT SQL 확장 (safe-trade 필수)

**목표**: `_TRADE_INSERT_SQL`에 컬럼 8개 추가, `record_buy()` 시그니처에 근거 데이터 인자 추가, rec 딕셔너리 8개 필드 추가.

**수정 파일**:
- `backend/app/services/trade_history.py`:
  - `_TRADE_INSERT_SQL`(78-84): 컬럼 8개 추가 + VALUES placeholder 8개 추가 (기존 18 → 26개)
  - `_trade_params()`(87-96): rec에서 8개 필드 추가 추출 (`sector`, `sector_rank`, `buy_rank`, `boost_score`, `boost_high`, `boost_news`, `boost_order_ratio`, `boost_program`)
  - `record_buy()`(248-293): 키워드 인자 8개 추가 (기본값 `None`/`0` — 매도·수동 주문 시 미전달 허용), rec 딕셔너리에 8개 필드 추가

**safe-trade 점검 (스킬 적용)**:
- **P15(단일 주문 경로)**: `record_buy()` 호출 경로 유지. 신규 기록 경로 분기 금지.
- **P16(살아있는 경로)**: 전달된 근거 데이터가 INSERT SQL까지 도달. dead field(전달되나 SQL에 미포함) 금지 — `_trade_params()`와 `_TRADE_INSERT_SQL` 컬럼 순서 일치 필수.
- **P18(테스트모드 동등성)**: 테스트/실전 모두 동일하게 8개 필드 저장. 모드 분기 없음.
- **거래 모드**: `TRADE_MODE`/`is_test_mode` 확인 — 본 변경은 기록 로직만, 주문 발생 자체 변경 없음.
- **롤백 여부**: 기존 매수 기록 로직 변경 없음 — 필드 추가만이므로 롤백 해당 없음.

**검증 방법**:
- `py_compile` + `ruff`
- `.venv/bin/python -m pytest backend/tests -q` (trade_history 테스트 — INSERT SQL 컬럼 순서·placeholder 수 일치 확인)
- `.venv/bin/python main.py` 런타임 기동 (기존 record_buy 호출 정상)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증)

**적용 스킬**: `safe-trade`(필수), `backend-fix`

**P원칙 점검**: P15(단일 경로), P16(살아있는 경로 — SQL과 params 일치), P18(모드 동등성), P22(컬럼 타입)

---

### 세션 4: execute_buy + buy_order_executor 근거 전달 (safe-trade 필수)

**목표**: `execute_buy()` 시그니처에 근거 데이터 전달 인자 추가, `buy_order_executor`에서 `bt.stock` 데이터 추출 전달, reason 문자열 생성 제거.

**수정 파일**:
- `backend/app/services/trading.py`:
  - `execute_buy()`(256-257) + `_execute_buy_locked()`(268-269) 시그니처: `reason: str = ""` 외에 구조화 근거 인자 추가 (`sector`, `sector_rank`, `buy_rank`, `boost_score`, `boost_high`, `boost_news`, `boost_order_ratio`, `boost_program` — 키워드 인자, 기본값 `None`/`0`)
  - `_buy_reason = reason or "자동매수"`(518) 폴백 제거 — 자동매수 시 reason 빈 문자열 명시적 전달(P20)
  - `record_buy()` 호출(520-524): 근거 데이터 8개 전달
- `backend/app/services/buy_order_executor.py`:
  - 229-232: `bt.stock`(`s`)에서 `s.sector`, `bt.sector_rank`, `bt.rank`, `s.boost_score`, `s.boost_high_triggered`, `s.boost_news_triggered`, `s.boost_order_ratio_triggered`, `s.boost_program_triggered` 추출해 `execute_buy()`에 전달
  - `reason=f"업종자동매수 업종={s.sector} 순위={bt.rank}"` 제거 → `reason=""` (자동매수 명시)

**safe-trade 점검 (스킬 적용)**:
- **P15(단일 주문 경로)**: `execute_buy()` → `record_buy()` 경로 유지. 시그니처 확장이지 분기 아님.
- **P16(살아있는 경로)**: 근거 데이터가 `buy_order_executor` → `execute_buy` → `record_buy` → DB까지 단일 배선. 중간 단계에서 누락 시 즉시 발견(검증 필수).
- **P18(테스트모드 동등성)**: 테스트/실전 모두 동일하게 근거 전달. 모드 분기 없음.
- **거래 모드**: 주문 발생·리스크 검사·가드 조건 변경 없음 — 근거 전달만.
- **롤백 여부**: 기존 매수 조건·주문 경로·리스크 검사 변경 없음 — reason 문자열 생성 제거는 기록 포맷 변경이지 매수 로직 롤백 아님. 단, `reason or "자동매수"` 폴백 제거는 사용자 설계/승인 로직(규칙 0-5) — 설계서 §2.3에 명시된 대로 진행.

**검증 방법**:
- `py_compile` + `ruff`
- `.venv/bin/python -m pytest backend/tests -q` (trading, buy_order_executor 테스트 — 시그니처 변경 호환성)
- `.venv/bin/python main.py` 런타임 기동 (모의투자 매수 시도 → 근거 데이터 DB 저장 확인)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증)
- DB 조회: 매수 레코드 8개 컬럼 값 채워짐 확인 (NULL 아님)

**적용 스킬**: `safe-trade`(필수), `backend-fix`

**P원칙 점검**: P15(단일 경로), P16(살아있는 경로), P18(모드 동등성), P20(폴백 제거), P21(근거 투명성)

---

### 세션 5: 프론트엔드 구조화 컬럼 표시 (frontend-fix)

**목표**: `profit-columns.ts` 정규식 파싱 제거 → 구조화 컬럼 직접 표시. 신규 가산점 컬럼 표시 추가(사용자 결정 §2 항목 1에 따라).

**수정 파일**:
- `frontend/src/pages/profit-columns.ts`:
  - `parseBuyReasonSector`(12-15), `parseBuyReasonRank`(16-19) 정규식 파싱 함수 제거
  - `_BUY_REASON_SECTOR`, `_BUY_REASON_RANK` 정규식 상수 제거
  - "업종" 컬럼(37): `parseBuyReasonSector(r.reason)` → `String(r.sector ?? '')` (구조화 컬럼 직접 표시)
  - "매수순위" 컬럼(39): `parseBuyReasonRank(r.reason)` → `String(r.buy_rank ?? '')` (구조화 컬럼 직접 표시)
  - 신규 컬럼 추가(사용자 결정 §2 항목 1 승인 시): "업종순위"(`sector_rank`), "가산점"(`boost_score`), 가산점 트리거 4종(`boost_high`/`boost_news`/`boost_order_ratio`/`boost_program`) — 표시 여부·형식은 사용자 결정

**검증 방법**:
- `cd frontend && npm run typecheck` (`tsc --noEmit`)
- `cd frontend && npm run build` (`tsc -b && vite build`)
- `cd frontend && npm run test` (vitest — profit-columns 테스트)
- 브라우저 확인: 수익 상세 페이지 매수 테이블 "업종"·"매수순위" 컬럼 정상 표시 (과거 레코드는 빈 값 — P20)

**적용 스킬**: `frontend-fix`(필수)

**P원칙 점검**: P10(파싱 제거 → 구조화 컬럼), P20(과거 레코드 빈 값 그대로), P21(사용자 열람), P23(용어 통일 — "업종"/"매수순위")

---

### 세션 6: 문서 갱신 + 최종 통합 검증 + 계획서 삭제

**목표**: 설계 문서 상태 갱신, HANDOVER 갱신, 전체 통합 검증, 계획서 파일 삭제(규칙 10).

**수정 파일**:
- `docs/buy-reason-column-design.md` — 상태 "구현 완료" 갱신
- `HANDOVER.md` — 직전 완료 작업에 본 기능 추가, 다음 세션 진행 대기 항목 제거

**검증 방법** (전체 통합):
- `.venv/bin/python -m pytest backend/tests -q` (전체 백엔드 테스트)
- `.venv/bin/python main.py` 런타임 기동 (모의투자 매수 → 근거 데이터 DB 저장 → 프론트 표시 전체 흐름)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 전체 검증)
- `cd frontend && npm run typecheck && npm run build && npm run test` (프론트 전체)
- 브라우저 최종 확인: 수익 상세 페이지 매수 근거 컬럼 정상 표시

**계획서 삭제 (규칙 10)**:
- 삭제 대상: `docs/buy-reason-column-design.md`, `docs/buy-reason-column-tasks.md`
- 삭제 전 사용자 승인 필수 (규칙 0)
- 백업 파일 삭제(세션 2에서 보류한 것)도 함께 사용자 승인 후 진행

**P원칙 점검**: P10(SSOT — 계획서 삭제 후 git 커밋 메시지가 단일 진실 소스), 규칙 10(완료 시 계획서 삭제)

---

## 2. 사용자 결정 항목

> 설계서 §6 "미해결 결정 사항"에서 이관. 구현 세션 진입 전 확정 필요.

| # | 항목 | 옵션 | 추천 | 상태 |
|---|------|------|------|------|
| 1 | 개별 가산점 표현 | A. 불리언(0/1) / B. 점수 저장 | A(불리언) — P24 단순성 + P21 투명성 | **결정 대기** |
| 2 | `sector_rank` 출처 | A. `bt.sector_rank`(업종 내 종목 정렬 순위) / B. `sc.rank`(업종 강도 순위) | 사용자 요청 "순위"의 의미 확인 필요 — 매수순위(`bt.rank`)만인지 업종 순위 포함인지 | **결정 대기** |
| 3 | 과거 레코드 처리 | A. NULL 그대로 빈 값 표시(P20 준수) / B. reason 문자열 파싱 폴백 유지 | A(빈 값 표시) — P20 폴백 금지. 단, 프론트에서 과거 이력 열람 시 빈 값이 사용자에게 혼란인지 확인 필요 | **결정 대기** |
| 4 | 다단계 워크플로우 전환 | 본 태스크 파일대로 6세션 분할 진행 | 이미 다단계로 진행 중(사용자 명시) | ✅ 확정 |

> **구현 세션 진입 전**: 항목 1·2·3 사용자 결정 필수. 항목 1(불리언)은 세션 1·3에, 항목 2(sector_rank 출처)는 세션 1·4에, 항목 3(과거 레코드)는 세션 5에 영향.

---

## 3. 테스트 계획 (선택)

### 신규 테스트 케이스

| 세션 | 테스트 대상 | 케이스 |
|------|------------|--------|
| 1 | `buy_filter` `calculate_boost_score` | 각 가산점 조건 만족 시 트리거 필드 True 설정 확인 (4개 케이스) |
| 1 | `buy_filter` `calculate_boost_score` | 모든 조건 미충족 시 트리거 필드 False 확인 |
| 2 | `stock_tables` 마이그레이션 | 컬럼 8개 추가 후 `PRAGMA table_info` 확인 |
| 2 | `stock_tables` 마이그레이션 | 이미 컬럼 존재 시 스킵(멱등성) 확인 |
| 3 | `trade_history` `record_buy` | 근거 데이터 8개 전달 시 rec·INSERT SQL에 포함 확인 |
| 3 | `trade_history` `_trade_params` | 컬럼 순서·placeholder 수 일치 확인 (26개) |
| 4 | `trading` `execute_buy` | 근거 데이터 전달 시 `record_buy`까지 도달 확인 |
| 4 | `buy_order_executor` | `bt.stock`에서 근거 추출 후 `execute_buy` 전달 확인 |
| 4 | `trading` | reason 빈 문자열 전달 시 `"자동매수"` 폴백 미발생 확인 (P20) |
| 5 | `profit-columns` | 구조화 컬럼 직접 표시 확인 (reason 파싱 제거) |
| 5 | `profit-columns` | 과거 레코드(sector=NULL) 시 빈 값 표시 확인 (P20) |

### 기존 테스트 영향

- `buy_filter` 테스트: `StockScore` 필드 추가로 인한 fixture 갱신 필요 (기본값 False이므로 기존 단정문 영향 최소)
- `trade_history` 테스트: `record_buy` 시그니처 확장 — 기존 호출(근거 미전달) 시 기본값으로 동작 확인
- `trading`/`buy_order_executor` 테스트: `execute_buy` 시그니처 확장 — 기존 호출(reason만) 호환성 확인
- `profit-columns` 테스트: 파싱 함수 제거 — 기존 파싱 테스트 케이스 삭제/변경

---

## 4. 런타임 검증 방법 (선택)

### 백엔드 런타임 검증 (세션 1~4, 6)

- 기동: `.venv/bin/python main.py`
- await 누락: `.venv/bin/python -W error::RuntimeWarning main.py`
- 잔존 프로세스: `lsof -ti:8000` (0건 확인)
- 모의투자 매수 시도 → 로그 확인: `[매매] 매수 주문 전송` + `[정산] 매수 기록`
- DB 조회: `SELECT sector, sector_rank, buy_rank, boost_score, boost_high, boost_news, boost_order_ratio, boost_program FROM trades WHERE side='BUY' ORDER BY id DESC LIMIT 1` — 8개 컬럼 값 채워짐 확인

### DB 마이그레이션 검증 (세션 2)

- 기동 로그: `[데이터] 체결 이력 테이블에 매수 근거 컬럼 추가` (또는 "이미 존재 - 생략")
- 컬럼 확인: `PRAGMA table_info(trades)` — 8개 컬럼 존재
- 기존 데이터: 과거 매수 레코드 8개 컬럼 NULL 확인 (P20 — 폴백으로 덮지 않음)

### 프론트엔드 검증 (세션 5, 6)

- 타입체크: `cd frontend && npm run typecheck`
- 빌드: `cd frontend && npm run build`
- 테스트: `cd frontend && npm run test`
- 브라우저: 수익 상세 페이지 → 매수 테이블 "업종"·"매수순위" 컬럼 정상 표시, 과거 레코드 빈 값 표시
