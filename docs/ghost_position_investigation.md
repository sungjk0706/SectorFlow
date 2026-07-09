# Ghost Position 근본 원인 조사 기록

## 조사 대상
- 삼성전자(005930) ghost position: avg_buy_price=70,100 KRW, 10주
- 발생 시점: 2026-07-09 15:52 (startup 시 DB에서 로드됨)
- DB 경로: `backend/data/stocks.db`
- 핵심 의문: 포지션은 존재하나 매수내역(trade_history)에 대응하는 매수 기록이 없고, 매도내역만 존재함

---

## 타임라인 (2026-07-09)

| 시간 | 이벤트 | 근거 |
|------|--------|------|
| 07:50 | 앱 시작, SQLite 복원 -- 1종목 (033780) | 로그 line 673 |
| 08:04~09:47 | 활발 매매: 005930 포함 다수 종목 매수/매도 | 로그 보유현재가 라인 981~4873 |
| 10:53 | 005930 SELL 6주 @281,000 | 로그 line 6489 |
| 11:05~11:53 | 추가 매매 진행, 최종 SELL 357780 | 로그 line 6999~7999 |
| 13:59:54 | 앱 시작, SQLite 복원 -- 0종목 | 로그 line 11859 |
| 14:00:35 | 앱 shutdown (SIGTERM) | 로그 line 11993~12025 |
| 14:02:38 | 앱 재시작, SQLite 복원 -- 0종목 | 로그 line 12073 |
| 14:24:32~14:24:47 | "database is locked" 에러 4회 (설정 저장 실패) | 로그 line 12493~13024 |
| 14:32:41 | 앱 shutdown (WS 끊김 → graceful shutdown) | 로그 line 13347~13395 |
| 14:32:42~15:52:18 | **앱 완전 중지 (로그 공백, 약 1시간 20분)** | 로그 line 13395→13413 |
| 15:52:18 | 앱 시작, **SQLite 복원 -- 1종목 (005930, avg_price=70,100)** | 로그 line 13413~13445 |
| 15:52:18.853 | realtime_reset 보유현재가=[('005930', 70100)] | 로그 line 13445 |
| 15:52:19.236 | SELL 005930 10주 @279,500, avg_buy_price=70,100 | trades 테이블 row 144 |

---

## 핵심 발견

### 1. 14:02 DB = 0종목, 15:52 DB = 1종목 (005930, avg_price=70,100)
- 14:02:38 로그: `[매매] SQLite 복원 -- 0종목` (line 12073)
- 15:52:18 로그: `[매매] SQLite 복원 -- 1종목` (line 13413 부근)
- **DB에 005930 포지션이 14:02~15:52 사이에 기록됨**
- 14:32~15:52는 앱 완전 중지 상태 (로그 공백)
- 14:02~14:32는 앱 실행 중이었으나 **005930 관련 매매/체결/저장 로그 없음**

### 2. 14:02~14:32 사이 005930 관련 활동 없음
- `가상 체결 완료.*005930` — 해당 시간대에 없음
- `보유현재가.*005930` — 해당 시간대에 없음
- `test-data/reset` / `reset_test_data` — 해당 시간대에 없음
- `clear` / `초기화` — 포지션 관련 없음
- **유일한 이상 활동: 14:24 "database is locked" 에러 4회 (설정 저장)**

### 3. 07-08 로그에서 005930 활동 확인
- 07-08 09:59~10:02: 005930 매수 시도 다수 (모두 리스크 차단 또는 조건 미충족)
- 07-08 10:04: 005930 호가/프로그램매매 구독
- 07-08 종가 기준 보유종목: 033780 (KT&G) 1종목 — 005930 아님
- 07-08 16:09 이후 모든 SQLite 복원: 1종목 (033780)

### 4. 07-09 07:50 시작 시 DB = 1종목 (033780)
- 07-08 종가 포지션이 033780이고, 07-09 시작 시에도 033780 1종목 로드됨
- 07-09 08:04부터 005930 포함 다수 종목 매수 시작
- 07-09 10:53: 005930 SELL 6주 @281,000 — 전량 매도
- 07-09 11:05~11:53: 추가 매매 후 모든 포지션 정리된 것으로 추정
- 13:59 재시작 시: 0종목 — **정상적으로 모든 포지션이 정리됨**

### 5. 보유현재가 필드는 cur_price (avg_price 아님)
- `engine_account_notify.py:519-522`에서 확인: `보유현재가` = `p.get("cur_price")`
- 15:52:18 로그의 `보유현재가=[('005930', 70100)]`는 cur_price=70,100
- **DB의 avg_price=70,100과 cur_price=70,100이 같은 값** — `save_test_positions`는 avg_price와 cur_price를 **별도 컬럼으로 저장** (`stock_tables.py:173-174`)
- 즉, DB에 005930 포지션이 저장될 때 avg_price=70,100, cur_price=70,100으로 저장되었음
- `_recalc_pnl` (`dry_run.py:284`): `cur = int(pos.get("cur_price") or avg)` — cur_price가 0/None이면 avg_price로 fallback하지만, 이 경우 cur_price도 70,100으로 저장되어 있었음

### 6. save_test_positions 트랜잭션 구조 취약
- `backend/app/db/stock_tables.py:161-191`
- `DELETE FROM test_positions` 후 개별 `INSERT OR REPLACE` 수행
- **명시적 `BEGIN TRANSACTION` / `COMMIT` 블록 없음**
- `conn.commit()`는 마지막에 1회 호출
- 반면 `save_integrated_system_settings`는 `BEGIN TRANSACTION`/`COMMIT` 사용 (settings_file.py:205-218)
- **인터럽트 발생 시 DELETE만 실행되고 INSERT는 누락될 가능성 있음**
- **또는 부분 INSERT만 실행될 가능성 있음**

### 7. 단일 DB 연결 확인
- `backend/app/db/database.py`: `get_db_connection` — 단일 shared aiosqlite 연결
- `close_db_connection` — 로그 없음
- 원칙 12 준수: 앱 시작 시 1회 생성, 종료 시 유지

### 8. shutdown 시퀀스
- `backend/app/web/app.py`: shutdown 시 `stop_db_writer()` + `close_db_connection()` 호출
- 14:00 shutdown: 백그라운드 태스크 종료 → LS증권 연결 종료 → 루프 종료
  - **DB writer 정지 로그 없음, DB close 로그 없음**
- 14:32 shutdown: 동일한 순서
  - **DB writer 정지 로그 없음, DB close 로그 없음**
- `SectorFlow.command`: `kill -15` (SIGTERM) → 2초 대기 → `kill -9` (SIGKILL)
  - SIGTERM으로 graceful shutdown이 2초 내 완료되지 않으면 SIGKILL 강제 종료

### 9. 70,100 KRW 값 추적
- `integrated_system_settings` 테이블: "70100" 없음
- `trades` 테이블: `144|2026-07-09|15:52:19|SELL|005930|삼성전자|10|279500|70100` — 유일한 레코드
- 07-08 및 07-09 로그에서 "70100" 검색: 15:52:18 보유현재가 로그에만 존재
- **70,100이 어떤 매수 체결가로부터 계산된 것인지 추적 불가** — 해당 가격의 매수 체결 로그 없음

### 10. _positions_loaded 플래그
- `dry_run.py:23`: `_positions_loaded: bool = False`
- `_load_positions()`: 플래그가 True면 DB 로드 스킵
- `clear()`: 플래그를 True로 설정하고 _test_positions.clear()
- 앱 재시작 시 프로세스가 새로 시작되므로 플래그는 항상 False에서 시작

### 11. 07-09 005930 실제 매매 이력 (이번 세션 확인)
- **08:03:42** — BUY 6주 @287,500 (가상 체결 완료, 로그 line 861)
  - 매수 신호 감지 → 시장가 6주 주문 → 체결가 287,500 (슬리피지 적용)
  - `record_buy` + `_apply_buy` 각각 호출됨
- **10:53:27** — SELL 6주 @281,000 (손절 발동, 실현손익=-42,884, 로그 line 6485~6491)
  - 전량 매도 → 005930 포지션 0주 됨
  - `record_sell` + `_apply_sell` 각각 호출됨
- **10:53 이후 005930 포지션 = 0주** — 정상적으로 전량 매도됨
- **15:52:19** — SELL 10주 @279,500 (익절 발동, avg_buy_price=70,100, 실현손익=+2,087,886)
  - **이 매도의 avg_buy_price=70,100은 어떤 실제 매수에서도 유래하지 않음**
  - 08:03 매수는 287,500이었고, 10:53에 전량 매도됨

### 12. 07-08 005930 활동 (이번 세션 확인)
- 07-08 09:51~09:52: 005930 매수 시도 다수 (로그에 "매수 시도"만 있음)
- **07-08에 005930 실제 체결(BUY fill) 없음** — `가상 체결 완료 BUY 005930` 로그 없음
- 07-08 종가 기준 보유종목: 033780 (KT&G) 1종목
- **07-08 로그 파일만 존재** — 07-07 이전 로그 파일 없음 (`ls` 확인)

### 13. trade_history와 _test_positions의 독립성 (이번 세션 확인)
- **매수 플로우** (`trading.py:259-341`):
  1. `dry_run.fake_send_order` → `fake_fill_event` → `_apply_buy` → `_test_positions` 갱신 + `_schedule_save_positions`
  2. `trade_history.record_buy` → `_buy_history` 메모리 + SQLite `trades` 테이블 저장
  - 두 호출은 **별도의 독립적인 함수 호출** — 하나의 트랜잭션으로 묶이지 않음
- **매도 플로우** (`trading.py:393-510`):
  1. `execute_sell`에서 `_test_positions`의 `avg_price`를 미리 조회 (`trading.py:418-424`)
  2. `dry_run.fake_send_order` → `fake_fill_event` → `_apply_sell` → `_test_positions` 갱신
  3. `trade_history.record_sell(avg_buy_price=_avg_buy)` → `_sell_history` 메모리 + SQLite 저장
  - 매도 기록의 `avg_buy_price`는 `_test_positions`에서 읽어온 값
- **핵심**: `_apply_buy`은 `_test_positions`만 갱신하고 `record_buy`을 호출하지 않음
- **반대로** `record_buy`은 trade_history만 갱신하고 `_test_positions`를 건드리지 않음
- 따라서 DB에서 포지션을 로드하면 `_test_positions`에만 들어가고, 매수 기록은 생성되지 않음

### 14. Ghost position 매도 트리거 메커니즘 (이번 세션 확인)
- **15:52 엔진 기동 시퀀스**:
  1. `_load_positions()` → DB에서 005930 (10주, avg_price=70,100, cur_price=70,100) 로드
  2. `_reconciliation_on_startup()` → **테스트모드이므로 대조 스킵** (`engine_lifecycle.py:231-233`)
  3. 실시간 시세 수신 → `update_price('005930', ~280,000)` 호출 (`dry_run.py:295-312`)
  4. cur_price 70,100 → ~280,000으로 갱신, `_recalc_pnl` 실행
  5. pnl_rate = (280,000 - 70,100) / 70,100 * 100 ≈ **+300%** (엄청난 수익률)
  6. `pipeline_compute.py:544-548`: 가격 틱 hit → `check_sell_conditions` 호출
  7. 익절 조건(tp_val) 즉시 충족 → `execute_sell` 호출
  8. `execute_sell`이 `_test_positions`에서 avg_buy_price=70,100 읽음
  9. `record_sell(avg_buy_price=70,100)` → 실현손익 = (279,500-70,100)*10 - fees = +2,087,886
- **15:52:18.853** 보유현재가=[('005930', 70100)] — cur_price가 아직 70,100 (실시간 시세 수신 전)
- **15:52:19.236** SELL 10주 @279,500 — 실시간 시세 수신 후 0.4초 만에 매도 실행
- **결론**: ghost position이 DB에서 로드된 후, 실시간 가격 갱신 시 자동매도 조건이 즉시 충족되어 매도됨

---

## 미조사 항목 (다음 세션에서 조사 필요)

### [A] 14:00 shutdown 시 DB close 누락 확인
- 14:00 shutdown 로그에 `stop_db_writer` / `close_db_connection` 로그가 없음
- `app.py` shutdown 시퀀스에 로그 추가되어 있는지 확인 필요
- `close_db_connection`에 로그가 없다면 실행되었더라도 로그에 안 찍힐 수 있음
- **확인 방법**: `app.py` shutdown 함수 전체 읽기, `database.py` close_db_connection 함수 읽기

### [B] SIGKILL 강제 종료 가능성
- `SectorFlow.command` line 30: `kill -9` after 2초 대기
- 14:00 shutdown이 2초 내 완료되지 않았으면 SIGKILL로 강제 종료
- SIGKILL 시 `close_db_connection` 실행되지 않음
- WAL 파일이 checkpoint 되지 않은 상태로 남을 수 있음
- **확인 방법**: 14:00 shutdown 로그 시간 범위 확인 (14:00:35.741 ~ 14:00:36.006 = 0.265초 — 2초 내 완료됨, SIGKILL 아님)

### [C] WAL 파일 상태
- 14:00 및 14:32 shutdown 시 WAL checkpoint 여부 확인 필요
- WAL 파일이 남아있으면 체크포인트되지 않은 데이터가 DB에 반영되지 않았을 수 있음
- 반대로, WAL 파일이 비어있으면 모든 데이터가 메인 DB에 체크포인트됨
- **현재 WAL 파일 존재 여부 확인 필요**: `ls -la backend/data/stocks.db-wal`

### [D] 14:24 "database is locked" 에러 영향
- 14:24:32~14:24:47에 설정 저장 4회 실패
- `save_integrated_system_settings`는 `BEGIN TRANSACTION`/`COMMIT` 사용
- 실패 시 `rollback` 수행됨
- **하지만 `save_test_positions`는 명시적 트랜잭션 없음**
- `busy_timeout` 미설정 확인됨 — 동시 접근 시 즉시 에러
- **의문**: 14:24에 어떤 작업이 동시에 DB에 접근했는가? 단일 연결인데 왜 lock?
- **확인 방법**: 14:24 시간대 전체 로그 분석, db_write_queue 작업 확인

### [E] 14:32 shutdown 시 _save_positions_worker 실행 여부
- 14:32 shutdown 시 포지션 저장 워커가 대기 중이었을 가능성
- _test_positions가 비어있으므로 `save_test_positions({})` 호출 시:
  - `DELETE FROM test_positions` 실행 (이미 비어있음)
  - INSERT 없음
  - `commit()` 실행
- **정상적으로 0종목 상태 유지되어야 함**
- **하지만 shutdown 인터럽트 시 DELETE 후 INSERT 사이에 끊기면?**
  - 이 경우 0종목 → DELETE → 0종목 (변화 없음)
  - 부분 쓰기가 발생하려면 기존 데이터가 있어야 함 — 14:32 시점에 0종목이므로 해당 안 됨

### [F] 15:52 startup 시 DB에 005930이 있었는지 직접 확인
- 15:52 로그: `SQLite 복원 -- 1종목` — DB에서 1종목을 로드함
- **DB에 005930 avg_price=70,100이 실제로 저장되어 있었음**
- 이 값이 언제 DB에 기록되었는지가 핵심 질문
- 14:02~14:32 사이에 기록되어야 하지만, 해당 시간대에 포지션 저장 로그 없음
- **가능성**: 14:00 이전의 _save_positions_worker가 비동기로 실행 중이었고, shutdown 시점에 아직 완료되지 않았을 가능성
  - 하지만 13:59 시작 시 0종목이었고, 14:00 shutdown까지 매매 활동 없음
  - _save_positions_worker가 실행될 이유가 없음

### [G] 외부 프로세스에 의한 DB 접근 가능성
- `sqlite3` CLI나 다른 프로세스가 DB에 직접 쓰기를 했을 가능성
- 14:32~15:52 공백 시간에 외부에서 DB 조작 가능성
- **확인 방법**: OS 로그, 터미널 히스토리, 또는 다른 스크립트 존재 여부

### [H] 70,100 값의 출처 추적 (이번 세션 업데이트)
- **07-09 005930 실제 매수**: 08:03:42 단 한 번, 6주 @287,500 (슬리피지 적용)
  - 10:53:27에 6주 전량 매도 @281,000 (손절) — 포지션 0됨
- **07-08 005930 매수 시도**: 있었으나 **실제 체결 없음** (가상 체결 완료 BUY 005930 로그 없음)
- **70,100은 07-08, 07-09의 어떤 매수 체결가로부터도 계산될 수 없음**
  - 287,500과 70,100은 관계없는 값
  - 07-08에는 체결 자체가 없음
- **로그 파일은 07-08, 07-09만 존재** — 07-07 이전 로그 없음
- 70,100의 출처는 여전히 미확인 — 외부 DB 조작 또는 WAL 이슈 가능성**

### [I] _test_positions 메모리 상태와 DB 상태의 불일치
- 13:59 시작: DB 0종목 → 메모리 0종목 (정상)
- 14:00 shutdown: 메모리 0종목 → DB 저장 (0종목, 정상)
- 14:02 시작: DB 0종목 → 메모리 0종목 (정상)
- 14:32 shutdown: 메모리 0종목 → DB 저장 (0종목, 정상)
- 15:52 시작: **DB 1종목 (005930, avg_price=70,100, cur_price=70,100)** → 메모리 1종목 (비정상!)
- **14:32~15:52 사이에 DB가 변경됨** — 앱이 꺼져있는 상태에서
- **가능한 원인 후보**:
  1. 외부 프로세스의 DB 조작
  2. WAL 체크포인트 지연으로 인한 이전 데이터 복원
  3. SIGKILL로 인한 미완성 트랜잭션의 부분 커밋
  4. SQLite WAL 모드의 checkpoint 타이밍 이슈

### [J] 매수내역(trade_history) 누락 원인 (이번 세션 확인)
- **확인된 사실**: ghost position의 매도 기록은 존재하지만 매수 기록은 존재하지 않음
- **원인**: `_test_positions`와 `trade_history`는 **독립적인 시스템**
  - `_apply_buy`은 `_test_positions`만 갱신 (`dry_run.py:223-255`)
  - `record_buy`은 `trade_history`만 갱신 (`trade_history.py:227-351`)
  - 두 함수는 `trading.py`의 매수 플로우에서 **별도로 호출됨**
- **DB 로드 시**: `_load_positions()`는 `_test_positions`에만 데이터를 채움
  - `trade_history`는 별도의 `_restore_from_db()`를 호출하지만, DB `trades` 테이블에 매수 기록이 없으면 복원되지 않음
  - ghost position은 정상 매수 플로우를 거치지 않고 DB에 들어갔으므로, `trades` 테이블에 매수 기록이 없음
- **결론**: 포지션이 DB에 직접 삽입되면 매수내역 없이 매도내역만 생성되는 것이 정상적인 동작임
  - 매도 시 `execute_sell`이 `_test_positions`에서 avg_buy_price를 읽어 `record_sell`에 전달
  - 매수 기록은 매수 주문 플로우에서만 생성되므로, DB 직접 삽입 포지션에는 매수 기록이 없음

---

## 조사에 사용한 파일 목록

| 파일 | 조사 내용 |
|------|-----------|
| `backend/app/services/dry_run.py` | _test_positions, _apply_buy (cur_price=price로 초기화), _apply_sell, clear, _save_positions_worker, _schedule_save_positions, _load_positions, update_price, _recalc_pnl (cur_price or avg fallback) |
| `backend/app/db/stock_tables.py:160-225` | save_test_positions (avg_price, cur_price 별도 컬럼 저장, 트랜잭션 없음), load_test_positions (avg_price, cur_price 별도 로드) |
| `backend/app/core/settings_file.py:205-218` | save_integrated_system_settings (트랜잭션 있음) |
| `backend/app/db/database.py` | get_db_connection (단일 연결), close_db_connection (로그 없음) |
| `backend/app/web/app.py` | shutdown 시퀀스: stop_db_writer + close_db_connection |
| `backend/app/web/routes/settings.py:89-164` | reset_test_data → clear() 호출 경로 |
| `backend/app/services/engine_account_notify.py:519-522` | 보유현재가 = cur_price 확인 (p.get("cur_price")) |
| `backend/app/services/trading.py:259-341` | 매수 플로우: record_buy + _apply_buy 별도 호출 |
| `backend/app/services/trading.py:393-510` | 매도 플로우: _test_positions에서 avg_buy_price 조회 후 record_sell 호출 |
| `backend/app/services/trading.py:512-639` | check_sell_conditions: tp/loss/ts 조건 검사 후 execute_sell 호출 |
| `backend/app/services/trade_history.py:227-351` | record_buy (avg_buy_price=0), record_sell (avg_buy_price 파라미터, 0 이하 경고) |
| `backend/app/services/engine_lifecycle.py:213-233` | _reconciliation_on_startup: 테스트모드 스킵 |
| `backend/app/services/engine_account.py:424-438` | _on_fill_after_ws: 매도 조건 검사 트리거 |
| `backend/app/pipelines/pipeline_compute.py:544-548` | 실시간 가격 틱 시 check_sell_conditions 호출 |
| `SectorFlow.command` | shutdown: kill -15 → 2초 대기 → kill -9 |
| `backend/logs/trading_2026-07-08.log` | 07-08 005930 매수 시도만 있고 체결 없음, SQLite 복원 이력 |
| `backend/logs/trading_2026-07-09.log` | 07-09 전체 타임라인, 005930 매수/매도 이력, 14:24 lock 에러, 15:52 ghost position |
| `backend/data/stocks.db` | trades 테이블, integrated_system_settings 테이블, test_positions 테이블 |

---

## 다음 세션 핸드오버

### 현재까지 결론
1. **Ghost position의 매도 기록만 있고 매수 기록이 없는 것은 정상 동작**
   - `_test_positions`와 `trade_history`는 독립 시스템
   - DB에서 포지션 로드 시 `_test_positions`에만 들어가고, `trade_history`의 매수 기록은 생성되지 않음
   - 매도 시 `execute_sell`이 `_test_positions`의 avg_price를 읽어 `record_sell`에 전달하므로 매도 기록은 생성됨
2. **70,100 KRW 값은 07-08, 07-09의 어떤 실제 매수 체결가와도 무관**
   - 07-09 유일한 005930 매수: 287,500 (10:53에 전량 매도됨)
   - 07-08: 005930 체결 기록 없음
   - 로그 파일은 07-08, 07-09만 존재
3. **DB에 005930 포지션이 14:32~15:52 사이 (앱 완전 중지)에 기록됨**
   - 14:32 shutdown 시 메모리 0종목, 15:52 startup 시 DB 1종목
   - 앱이 꺼져있는 동안 DB가 변경됨
4. **15:52 매도 트리거**: ghost position 로드 → 실시간 가격 갱신 → pnl_rate +300% → 익절 조건 즉시 충족 → 자동 매도

### 다음 세션에서 조사할 항목

#### [P0] 14:32~15:52 DB 변경 원인 (최우선)
- 앱이 완전 중지된 상태에서 DB test_positions 테이블이 변경됨
- **확인 필요**:
  1. WAL 파일 존재 여부 및 내용: `ls -la backend/data/stocks.db-wal backend/data/stocks.db-shm`
  2. 14:32 shutdown이 SIGKILL로 끝났는지 확인 (로그 시간 범위로 판단)
  3. `_save_positions_worker`가 shutdown 시점에 실행 중이었을 가능성
  4. 외부 프로세스(DB 브라우저, sqlite3 CLI 등) 접근 이력

#### [P1] save_test_positions 트랜잭션 부재 영향
- `stock_tables.py:161-189`: DELETE 후 INSERT 사이에 명시적 트랜잭션 없음
- SIGKILL 시 DELETE만 실행되거나 부분 INSERT만 실행될 가능성
- **하지만** 14:32 시점에 메모리 0종목이었으므로, 정상 실행 시 DELETE만 (빈 테이블 DELETE) → 0종목 유지
- **의문**: 0종목 상태에서 save_test_positions가 실행 중이었고, SIGKILL로 중단되면?
  - DELETE FROM test_positions (이미 비어있음) → commit 안 됨 → 이전 데이터가 남아있을 수 있음?
  - 하지만 14:02 시작 시 0종목이었으므로 이전 데이터도 0종목이어야 함

#### [P1] WAL 체크포인트 지연 가능성
- SQLite WAL 모드에서 checkpoint가 실행되지 않으면, WAL 파일의 변경사항이 메인 DB에 반영되지 않음
- 14:32 SIGKILL 시 WAL checkpoint가 미실행 → 이전 체크포인트 시점의 데이터가 메인 DB에 남아있을 수 있음
- **확인 필요**: 14:32 이전의 마지막 save_test_positions 실행 시점과 그 시점의 포지션 상태
  - 10:53 005930 전량 매도 후 → _apply_sell → _schedule_save_positions → 0종목 저장
  - 이후 포지션 변화가 있었는지 11:05~13:59 로그 확인 필요

#### [P2] 프론트엔드 더미 데이터 가능성
- 사용자 초기 의견: 70,100이 프론트엔드 더미 데이터(70,000 + 슬리피지 100)에서 유래했을 가능형
- 프론트엔드에서 백엔드 DB로 더미 포지션을 직접 삽입하는 API/코드 경로 확인 필요
- `reset_test_data` 이외에 포지션을 직접 조작하는 API 엔드포인트 확인

#### [P2] 11:05~13:59 포지션 상태 추적
- 10:53 005930 전량 매도 후 13:59 재시작까지의 포지션 변화 추적
- 11:05~11:53 추가 매매 로그 분석
- 13:59 startup 시 0종목이었으므로, 11:53 이전에 모든 포지션이 정리되었을 것
- 하지만 중간에 _save_positions_worker가 어떤 상태를 저장했는지 확인 필요

---

## 예방 조치 구현 기록 (2025-07-12)

> **목적**: 과거 유령 포지션의 정확한 발생 시점 추적은 별도 과제로 남기되,  
> 동일한 근본 원인(포지션과 체결이력의 독립적 영속화)으로 인한 재발을 원천 차단하는 예방 조치를 구현했다.

### 근본 원인 요약

`_test_positions`(인메모리 → SQLite `test_positions` 테이블)와 `trade_history`(인메모리 → SQLite `trades` 테이블)가 **독립적으로 영속화**되어, 두 시스템 간 데이터 불일치 시 유령 포지션이 발생할 수 있었다.

- `dry_run._apply_buy()` → `_test_positions` 업데이트 + `test_positions` 테이블 저장
- `trade_history.record_buy()` → `_buy_history` 업데이트 + `trades` 테이블 저장
- 두 호출은 `trading.py:execute_buy()`에서 순차 호출되지만, 중단/예외 시 한쪽만 영속화될 수 있음
- 기동 시 `test_positions` 테이블에서 로드 → `trades`와 불일치 가능

### 아키텍처 원칙 위반 사항

- **원칙 10 (SSOT)**: 포지션 데이터가 `test_positions`와 `trades` 두 곳에 중복 관리
- **원칙 12 (DB 쓰기 직렬화)**: `save_test_positions`가 DB Writer 큐를 우회하고 직접 `conn.execute` + `commit` 수행
- **원칙 16 (살아있는 경로)**: 테스트모드에서 `_reconciliation_on_startup`이 대조를 스킵하여 유령 포지션 미정정

### 구현 내역

#### 1. `stock_tables.py` — test_positions 테이블/함수 제거
- `CREATE TABLE test_positions` 제거
- `save_test_positions()`, `load_test_positions()` 함수 제거
- `trades` 테이블이 보유 포지션의 유일한 진실 원천(SSOT)

#### 2. `trade_history.py` — `build_positions_from_trades()` 추가
- `_buy_history` + `_sell_history`에서 보유 포지션을 파생하는 함수
- 매수 기록으로 포지션 생성/가중평균단가 계산, 매도 기록으로 수량 차감/제거
- `_history_lock`으로 스레드 안전 보장

#### 3. `dry_run.py` — _load_positions를 trades 기반으로 변경, 저장 로직 제거
- `_load_positions()`: `load_test_positions()` → `trade_history.build_positions_from_trades("test")` 로 변경
- `_save_positions()`, `_schedule_save_positions()`, `_save_positions_worker()`, `_pos_save_event`, `_pos_lock` 등 영속화 로직 전체 제거
- `LazyEvent`, `LazyLock` import 제거 (미사용)
- `clear()`: `_schedule_save_positions()` 호출 제거

#### 4. `trading.py` — execute_sell() 런타임 가드 추가
- 매도 전 `trade_history.build_positions_from_trades("test")`로 포지션 존재/수량 검증
- 포지션 없거나 수량 부족 시 `logger.critical` + Telegram 알림 + 매도 중단
- 유령 포지션 매도 시도를 런타임에서 차단 (원칙 16: 살아있는 경로)

#### 5. `engine_lifecycle.py` — 테스트모드 대조 활성화
- 테스트모드에서 대조 스킵 → `dry_run._load_positions()` 호출로 변경
- 기동 시 `trades` 기반으로 포지션 복원 (SSOT 준수)

#### 6. `settings.py` — reset 순서 정정
- `clear_test_history()`를 `clear()`보다 먼저 실행
- `trades`가 SSOT이므로, trades 삭제 후 positions 초기화 순서가 보장되어야 함

### 검증 결과

- **전체 테스트**: 105 passed, 3 warnings (기존 warnings, 신규 아님) in 17.31s
- **잔존 프로세스**: 0건
- **수정 파일**: `stock_tables.py`, `trade_history.py`, `dry_run.py`, `trading.py`, `engine_lifecycle.py`, `settings.py`, `test_dry_run_fill_event.py`

### 향후 심층 조사 과제

- 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적은 별도 세션에서 진행
- WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석 필요
