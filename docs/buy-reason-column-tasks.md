# 태스크 파일: 매수 근거 통합 컬럼 구현 (A 방식)

> **상태**: 태스크 분할 완료 (구현 미진행 — 규칙 0 준수, 승인 대기)
> **작성일**: 2026-07-28 (재설계 — A 방식 채택 후 재작성)
> **설계서 경로**: `docs/buy-reason-column-design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ · 2세션(태스크 분할) ✅ · 3세션~(구현) 예정
> **관련 원칙**: P10(SSOT), P15(단일 주문 경로), P16(살아있는 경로), P18(테스트모드 동등성), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(용어 통일), P24(단순성), P25(격리된 실패)
> **관련 스킬**: `db-backup`(세션 2), `safe-trade`(세션 3·4), `backend-fix`(세션 1~4), `frontend-fix`(세션 5)

---

## 0. 사전조사 결과 요약

### 0.1 의존성 (수정 파일 + 변경점 + 기준 라인)

| 파일 | 변경점 | 기준 라인 |
|------|--------|-----------|
| `backend/app/domain/models.py` | `StockScore`에 개별 트리거 필드 4개 추가 (`boost_high_triggered` 등) | 9-27 |
| `backend/app/domain/buy_filter.py` | `calculate_boost_score()` 내 각 조건 만족 시 트리거 필드 True 설정 | 8-64 |
| `backend/app/db/stock_tables.py` | `migrate_add_buy_reason_columns_to_trades()` 신규 추가 (ALTER TABLE 2개: sector, buy_rank) | 260-277(기존 패턴) |
| `backend/app/web/app.py` | 신규 마이그레이션 함수 import + 기동 시 호출 | 48, 53 |
| `backend/app/services/trade_history.py` | `_TRADE_INSERT_SQL` 컬럼 2개 추가(sector, buy_rank), `_trade_params()` 2개 필드 추출, `record_buy()` 시그니처 확장 + rec 2개 필드 | 78-96, 248-293 |
| `backend/app/services/trading.py` | `execute_buy()` 시그니처 확장(sector, buy_rank 전달), `_buy_reason = reason or "자동매수"` 폴백 제거, `record_buy()` 호출에 sector/buy_rank 전달 | 256-257, 517-524 |
| `backend/app/services/buy_order_executor.py` | `bt.stock`에서 sector·buy_rank·트리거 필드 추출, 가산점 통합 문자열(reason) 생성, reason 문자열 생성 제거 | 229-232 |
| `frontend/src/pages/profit-columns.ts` | `parseBuyReasonSector`/`parseBuyReasonRank` 정규식 파싱 제거 → r.sector/r.buy_rank 직접 표시, 신규 "매수 근거" 컬럼 추가(r.reason 표시) | 9-19, 37-39 |

### 0.2 영향 범위

- **백엔드 모델**: `StockScore` 필드 추가 → `StockScore` 인스턴스 생성·직렬화 경로 전체(WS 전송, 엔진 스코어링)에 필드 노출. 기본값 `False`이므로 기존 동작 영향 없음(P25 격리).
- **DB 스키마**: `trades` 테이블 컬럼 2개 추가(sector, buy_rank). 기존 레코드는 NULL(매수 근거 미적용 — P20 폴백 아님). 매도 레코드도 NULL. `db-backup` 스킬 필수(안전 규칙 2).
- **거래 로직(기록 경로)**: `execute_buy()` → `record_buy()` 경로는 유지(P15). 근거 **데이터 전달만 추가**, 주문 발생·리스크 검사·가드 조건 변경 없음. `safe-trade` 스킬 필수.
- **프론트엔드**: 수익 상세 페이지 매수 테이블 "업종"·"매수순위" 컬럼 데이터 소스 변경(reason 파싱 → 구조화 컬럼). 신규 "매수 근거" 컬럼 1개 추가(가산점 통합 문자열 표시).
- **테스트**: 백엔드(buy_filter, trade_history, buy_order_executor) + 프론트엔드(profit-columns) 기존 테스트 영향. 신규 테스트 케이스 추가(§3).

### 0.3 아키텍처 원칙 부합

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10(SSOT) | ✅ 개선 | reason 문자열 파싱 제거 → 구조화 컬럼(sector, buy_rank) 단일 진실 소스. 개별 트리거 상태 StockScore에 보존 |
| P15(단일 주문 경로) | ✅ 유지 | `execute_buy()` → `record_buy()` 경로 변경 없음, 근거 데이터 전달만 추가 |
| P16(살아있는 경로) | ✅ | 근거 데이터가 `buy_order_executor` → `execute_buy` → `record_buy` → DB까지 단일 배선. dead field 금지 |
| P18(테스트모드 동등성) | ✅ | 테스트/실전 모두 동일하게 구조화 근거 저장. 모드 분기 없음 |
| P20(폴백 금지) | ✅ 개선 | `reason or "자동매수"` 폴백 제거. 과거 레코드 NULL 명시적 처리(빈 값 그대로) |
| P21(사용자 투명성) | ✅ 개선 | 매수 근거(어떤 가산점이 기여했는지) 사용자 열람 가능. 핵심 정보(업종·순위) 말줄임 시에도 보존 |
| P22(데이터 정합성) | ✅ | 컬럼 타입 보장, 매수 결정 시점 트리거 상태 보존 |
| P23(용어 통일) | ✅ | "업종"(not 섹터), "매수"(not Buy), "종목"(not 주목) — 컬럼명·표시 텍스트 준수 |
| P24(단순성) | ✅ | 8컬럼 분리 대신 2컬럼 구조화 + reason 재사용. A 방식 채택 (B 대비 말줄임 안정성) |
| P25(격리된 실패) | ✅ | 마이그레이션 실패 시 해당 컬럼 NULL, 기존 체결 이력 조회 영향 없음 |

### 0.4 기존 공통 자산 확인

- **마이그레이션 패턴**: `migrate_add_buy_date_to_trades()`(`stock_tables.py:260-277`) — `PRAGMA table_info` → `ALTER TABLE ADD COLUMN` → `commit`. 신규 마이그레이션도 동일 패턴 재사용(컬럼 2개 일괄 추가).
- **INSERT SQL 패턴**: `_TRADE_INSERT_SQL` + `_trade_params()` 기존 구조 재사용 — 컬럼 2개·placeholder 2개·필드 2개 추가만.
- **프론트 공통 자산**: `profit-columns.ts`의 `ColumnDef` 패턴, `components/common/ui-styles` 색상/포매터 재사용. 신규 컬럼 추가 시 동일 `ColumnDef` 구조 따름.

### 0.5 가산점 통합 문자열 포맷 (설계서 §2.2)

| 가산점 | 트리거 필드 (StockScore) | 표시 문자열 |
|--------|-------------------------|-------------|
| 고가돌파 | `boost_high_triggered` | `📈고가돌파` |
| 잔량비율 | `boost_order_ratio_triggered` | `📊잔량비율` |
| 뉴스 호재 | `boost_news_triggered` | `📰뉴스` |
| 프로그램순매수 | `boost_program_triggered` | `💹프로그램순매수` |

- 표시 순서: 고가돌파 → 잔량비율 → 뉴스 → 프로그램순매수 (고정 순서 — P23 일관성).
- 구분자: ` · ` (전각 공백 + 중점 + 전각 공백).
- 발생한 가산점만 연결. 미발생 시 빈 문자열 `""` (P20).

---

## 1. 단계 분할 (세션당 1단계 — 규칙 0-1)

> 각 세션은 독립적으로 완료·검증 가능한 크기. 검증 통과 시 커밋 + HANDOVER 갱신 + 사용자 보고 후 세션 종료.

### 세션 1: 백엔드 모델 + 가산점 트리거 보존

**목표**: `StockScore`에 개별 가산점 트리거 필드 4개 추가, `calculate_boost_score()`에서 트리거 시 필드 설정.

**수정 파일**:
- `backend/app/domain/models.py` — `StockScore`에 `boost_high_triggered`, `boost_news_triggered`, `boost_order_ratio_triggered`, `boost_program_triggered` (bool, 기본값 `False`) 추가
- `backend/app/domain/buy_filter.py` — `calculate_boost_score()` 내 각 조건 만족 시 해당 트리거 필드 `True` 설정 (합산 로직은 유지, 필드 설정만 추가)

**검증 방법**:
- `py_compile` + `ruff` (구문/린트)
- `.venv/bin/python -m pytest backend/tests -q` (기존 buy_filter 테스트 통과 + 트리거 필드 설정 확인)
- `.venv/bin/python main.py` 런타임 기동 (StockScore 직렬화·WS 전송 정상)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증)

**적용 스킬**: `backend-fix` (모델 변경). safe-trade 해당 없음(매수 로직 아님, 스코어링 보존만).

**P원칙 점검**: P10(트리거 상태 보존), P22(매수 결정 시점 정합성), P25(기본값 False로 기존 동작 영향 없음)

**테스트 추가**:
- `test_buy_filter.py` — 각 가산점 트리거 시 `stock.boost_*_triggered == True` 확인 (기존 17개 테스트에 단정문 추가 또는 신규 케이스)

---

### 세션 2: DB 마이그레이션 (db-backup 필수)

**목표**: `trades` 테이블에 구조화 컬럼 2개(sector, buy_rank) 추가 마이그레이션 함수 작성 + 기동 시 호출.

**수정 파일**:
- `backend/app/db/stock_tables.py` — `migrate_add_buy_reason_columns_to_trades()` 신규 추가: `PRAGMA table_info(trades)`로 2개 컬럼 존재 확인 후 `ALTER TABLE ADD COLUMN` 2개 (`sector TEXT`, `buy_rank INTEGER`). 기존 `migrate_add_buy_date_to_trades()` 패턴 준수.
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
- `.venv/bin/python main.py` 런타임 기동 → 마이그레이션 로그 확인 + `PRAGMA table_info(trades)`로 2개 컬럼 존재 확인
- 기존 체결 이력 조회 정상 확인 (과거 레코드 NULL)

**적용 스킬**: `db-backup`(필수), `backend-fix`. safe-trade 해당 없음(스키마만, 주문 경로 미관여).

**P원칙 점검**: P22(컬럼 타입 보장), P25(마이그레이션 실패 시 NULL, 기존 데이터 영향 없음), 안전 규칙 2(백업 필수)

---

### 세션 3: record_buy + INSERT SQL 확장 (safe-trade 필수)

**목표**: `_TRADE_INSERT_SQL`에 컬럼 2개(sector, buy_rank) 추가, `record_buy()` 시그니처에 sector/buy_rank 인자 추가, rec 딕셔너리 2개 필드 추가.

**수정 파일**:
- `backend/app/services/trade_history.py`:
  - `_TRADE_INSERT_SQL`(78-84): 컬럼 2개 추가(sector, buy_rank) + VALUES placeholder 2개 추가
  - `_trade_params()`(87-96): rec에서 sector, buy_rank 2개 필드 추가 추출
  - `record_buy()`(248-285): 시그니처에 `sector: str = ""`, `buy_rank: int | None = None` 인자 추가, rec 딕셔너리에 sector/buy_rank 필드 추가

**검증 방법**:
- `py_compile` + `ruff`
- `.venv/bin/python -m pytest backend/tests -q` (trade_history 테스트 — 기존 record_buy 호출에 기본값 적용으로 호환성 유지)
- `.venv/bin/python main.py` 런타임 기동 (record_buy 호출 정상)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증)

**적용 스킬**: `safe-trade`(필수 — record_buy 호출 경로 수정), `backend-fix`.

**safe-trade 점검**:
- P15: `record_buy()` 단일 경로 유지. 신규 기록 경로 분기 없음.
- P16: sector/buy_rank가 INSERT SQL까지 배선. dead field 금지.
- P18: 테스트/실전 모두 동일하게 sector/buy_rank 저장.
- 기본값(`sector=""`, `buy_rank=None`)으로 기존 호출 호환성 유지 — 세션 4에서 buy_order_executor가 실제 값 전달.

**P원칙 점검**: P10(구조화 컬럼 영속화), P15(단일 경로), P16(살아있는 경로), P22(컬럼 타입 보장)

**테스트 추가**:
- `test_trade_history.py` — record_buy에 sector/buy_rank 전달 시 rec에 포함·DB INSERT되는지 확인 (신규 케이스)

---

### 세션 4: execute_buy + buy_order_executor 가산점 통합 문자열 생성 (safe-trade 필수)

**목표**: `execute_buy()` 시그니처에 sector/buy_rank 인자 추가, `buy_order_executor`에서 트리거 필드로 가산점 통합 문자열(reason) 생성 후 전달.

**수정 파일**:
- `backend/app/services/trading.py`:
  - `execute_buy()` 시그니처(256-257): `sector: str = ""`, `buy_rank: int | None = None` 인자 추가
  - `_buy_reason = reason or "자동매수"`(518) 폴백 제거 — reason 그대로 전달 (P20)
  - `record_buy()` 호출(520-524): sector, buy_rank 전달 추가
- `backend/app/services/buy_order_executor.py`:
  - 229-232: `bt.stock`에서 sector 추출, `bt.rank`에서 buy_rank 추출, 트리거 필드로 가산점 통합 문자열 생성
  - reason 문자열 `f"업종자동매수 업종={s.sector} 순위={bt.rank}"` 제거 → 가산점 통합 문자열로 교체
  - 가산점 통합 문자열 생성 헬퍼 함수(또는 인라인) — 트리거 필드 순회하며 발생한 것만 ` · ` 구분자로 연결

**가산점 통합 문자열 생성 로직** (설계서 §2.2 준수):
```python
# 의사코드 — 실제 구현 시 P23 네이밍·P24 단순성 준수
_parts = []
if s.boost_high_triggered: _parts.append("📈고가돌파")
if s.boost_order_ratio_triggered: _parts.append("📊잔량비율")
if s.boost_news_triggered: _parts.append("📰뉴스")
if s.boost_program_triggered: _parts.append("💹프로그램순매수")
_reason = " · ".join(_parts)  # 미발생 시 빈 문자열 (P20)
```

**검증 방법**:
- `py_compile` + `ruff`
- `.venv/bin/python -m pytest backend/tests -q` (trading, buy_order_executor 테스트)
- `.venv/bin/python main.py` 런타임 기동 (매수 시도 시 reason 생성 정상)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증)

**적용 스킬**: `safe-trade`(필수 — execute_buy 시그니처 + buy_order_executor 매수 경로 수정), `backend-fix`.

**safe-trade 점검**:
- P15: `execute_buy()` → `record_buy()` 단일 경로 유지. 신규 매수 분기 없음.
- P16: sector/buy_rank/reason이 buy_order_executor → execute_buy → record_buy → DB까지 단일 배선.
- P18: 테스트/실전 모두 동일 가산점 통합 문자열 생성.
- 주문 발생·리스크 검사·가드 조건 변경 없음 — 근거 **생성·전달**만 추가.

**P원칙 점검**: P10(트리거 필드 → reason 문자열 SSOT), P15(단일 경로), P16(살아있는 경로), P20(폴백 제거), P21(가산점 근거 사용자 열람 가능), P23(용어 통일 — "고가돌파"/"뉴스"/"잔량비율"/"프로그램순매수")

**테스트 추가**:
- `test_trading.py` — execute_buy에 sector/buy_rank/reason 전달 시 record_buy에 전달되는지 확인 (기존 mock 패치 재사용)
- `test_buy_order_executor.py` (있을 경우) 또는 `test_trading.py` — 트리거 필드 조합별 reason 문자열 생성 확인 (4개 모두 발생, 일부 발생, 미발생 케이스)

---

### 세션 5: 프론트엔드 구조화 컬럼 표시 + 가산점 컬럼 추가

**목표**: `profit-columns.ts` reason 파싱 제거, r.sector/r.buy_rank 직접 표시, 신규 "매수 근거" 컬럼 추가.

**수정 파일**:
- `frontend/src/pages/profit-columns.ts`:
  - `parseBuyReasonSector`/`parseBuyReasonRank` 정규식 파싱 함수 + `_BUY_REASON_SECTOR`/`_BUY_REASON_RANK` 상수 제거 (9-19)
  - "업종" 컬럼(37-38): `parseBuyReasonSector(r.reason)` → `String(r.sector ?? '')` 직접 표시
  - "매수순위" 컬럼(39): `parseBuyReasonRank(r.reason)` → `r.buy_rank != null ? String(r.buy_rank) : ''` 직접 표시
  - 신규 "매수 근거" 컬럼 추가: `r.reason` 표시 (가산점 통합 문자열), align 'left', type 'reason' 또는 신규 type
  - 컬럼 순서: 기존 "매수순위" 뒤에 "매수 근거" 추가 (또는 "수수료" 앞)

**검증 방법**:
- `cd frontend && npm run typecheck` (타입 에러 없음)
- `cd frontend && npm run build` (빌드 성공)
- `cd frontend && npm run test` (vitest — profit-columns 기존 테스트 통과 + 신규 컬럼 테스트)
- 브라우저 확인 — 수익 상세 페이지 매수 테이블 렌더링 정상, "업종"·"매수순위"·"매수 근거" 컬럼 표시

**적용 스킬**: `frontend-fix`.

**P원칙 점검**: P10(reason 파싱 제거 → 구조화 컬럼 SSOT), P21(매수 근거 사용자 열람), P23(용어 통일 — "매수 근거" 컬럼명), P24(파싱 로직 제거로 단순화)

**테스트 추가**:
- `profit-columns` 관련 테스트 — r.sector/r.buy_rank 직접 표시 확인, r.reason 가산점 통합 문자열 표시 확인 (기존 파싱 테스트가 있을 경우 수정)

---

### 세션 6: 문서 갱신 + 통합 검증

**목표**: 설계서·태스크 파일 삭제(규칙 10), 통합 검증, HANDOVER 최종 갱신.

**수정 파일**:
- `docs/buy-reason-column-design.md` — 삭제 (규칙 10 — 구현 완료 후 설계서 삭제)
- `docs/buy-reason-column-tasks.md` — 삭제 (규칙 10)
- `HANDOVER.md` — 최종 갱신 (BUY-REASON 구현 세션 1~6 완료 기록)

**검증 방법**:
- `.venv/bin/python -m pytest backend/tests -q` (전체 백엔드 테스트)
- `cd frontend && npm run typecheck && npm run build && npm run test` (전체 프론트엔드 검증)
- `.venv/bin/python main.py` 런타임 기동 (전체 통합)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증)
- DB 마이그레이션 적용 확인 + 매수 체결 시 reason/sector/buy_rank 저장 확인 (테스트모드 매수 1건 발생시켜 DB 조회)

**적용 스킬**: `backend-fix`, `frontend-fix`.

**P원칙 점검**: 전체 통합 — P10/P15/P16/P18/P20/P21/P22/P23/P24/P25 전수 점검.

---

## 2. 다단계 진행 상황 추적

| 세션 | 목표 | 상태 | 적용 스킬 |
|------|------|------|----------|
| 1 | 백엔드 모델 + 가산점 트리거 보존 | 대기 | backend-fix |
| 2 | DB 마이그레이션 (sector, buy_rank 2개 컬럼) | 대기 | db-backup, backend-fix |
| 3 | record_buy + INSERT SQL 확장 | 대기 | safe-trade, backend-fix |
| 4 | execute_buy + buy_order_executor 가산점 통합 문자열 | 대기 | safe-trade, backend-fix |
| 5 | 프론트엔드 구조화 컬럼 + 가산점 컬럼 | 대기 | frontend-fix |
| 6 | 문서 갱신 + 통합 검증 | 대기 | backend-fix, frontend-fix |

---

## 3. 테스트 계획 (세션별)

### 세션 1
- 기존 `test_buy_filter.py` 17개 케이스 통과 (기본값 False로 호환)
- 신규: 각 가산점 트리거 시 `stock.boost_*_triggered == True` 확인 (고가돌파/잔량비율/뉴스/프로그램 각 1케이스 + 미발생 케이스)

### 세션 2
- 기존 마이그레이션 테스트 통과
- 신규: `migrate_add_buy_reason_columns_to_trades()` 호출 후 `PRAGMA table_info(trades)`에 sector, buy_rank 컬럼 존재 확인

### 세션 3
- 기존 `test_trade_history.py` 통과 (기본값으로 호환)
- 신규: record_buy에 sector/buy_rank 전달 시 rec 포함 + DB INSERT되는지 확인

### 세션 4
- 기존 `test_trading.py` 통과 (mock patch 재사용)
- 신규: 트리거 필드 조합별 reason 문자열 생성 확인 (4개 모두/일부/미발생)
- 신규: execute_buy에 sector/buy_rank 전달 시 record_buy에 전달되는지 확인

### 세션 5
- 기존 profit-columns 테스트 통과 (파싱 테스트 수정)
- 신규: r.sector/r.buy_rank 직접 표시 확인, r.reason 가산점 통합 문자열 표시 확인

### 세션 6
- 전체 백엔드 테스트 통과
- 전체 프론트엔드 테스트 통과
- 런타임 기동 + DB 마이그레이션 + 매수 체결 시 reason/sector/buy_rank 저장 통합 확인
