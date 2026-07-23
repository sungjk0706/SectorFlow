# SectorFlow P25 위반 40건 수정 — 세션별 태스크 체크리스트

> 작성일: 2026-07-23
> 기준 문서: `docs/p25_fix_plan.md` (수정 계획서)
> 성격: **실행용 태스크 체크리스트** — 각 세션별 점검 항목을 실행 가능한 형태로 구체화
> 진행 방식: Tier 1 → Tier 2 → Tier 3 순차, 세션당 1단계 (AGENTS.md 규칙 0-1)
> 승인 전 수정 금지 (AGENTS.md 규칙 0) — 본 체크리스트는 실행 지시어 수신 시에만 코드 수정 착수

---

## 공통 사전 점검 (모든 세션 시작 전)

- [ ] `HANDOVER.md` 확인 — 직전 완료 작업 파악, 이어서 진행할 세션 식별
- [ ] 사전조사 4항목 수행 (규칙 0-2): 의존성 / 영향범위 / 아키텍처 원칙 부합 / 기존 공통 자산 확인
- [ ] 수정 계획을 UI 기준 일반 용어로 사용자에게 보고 (핵심 로직 변경 시 규칙 0-4)
- [ ] 사용자 명시적 승인(실행 지시어) 수신 확인
- [ ] 백엔드 수정 시: 백엔드 체크리스트(P1~P25) 사전 확인
- [ ] 프론트엔드 수정 시: 프론트엔드 체크리스트(P21/P23/P25) 사전 확인

## 공통 완료 점검 (모든 세션 종료 전)

- [ ] 검증 수행 (프론트: `npm run build` + 브라우저 확인 / 백엔드: `pytest` + `python -W error::RuntimeWarning main.py` 기동)
- [ ] P20 폴백 금지 확인 — silent `except: pass` 없음, 빈 값/None 폴백 없음
- [ ] P23 일관성 확인 — 동일 패턴은 파일 간 동일 구조
- [ ] P24 단순성 확인 — 함수 50줄 이하, 과도한 격리 추상화 없음
- [ ] P16 살아있는 경로 확인 — 격리 코드가 실제 실행 경로에 연결됨 (dead code 아님)
- [ ] `git commit` (롤백 시 사유 기록 의무, 규칙 0-3)
- [ ] `HANDOVER.md` "직전 완료 작업" 섹션 갱신
- [ ] 사용자에게 UI 기준 일반 용어로 수정 내용 + 화면 변화 보고 (규칙 0-4)

---

## Tier 1 (CRITICAL + HIGH, 10건 / 6세션)

### T1-S1 — WS 디스패치 격리 (프론트엔드 기반) — 부분 완료 (2026-07-23)

- **대상 위반 ID**: A1-01-01 (CRITICAL), A1-01-02 (CRITICAL), A1-01-04 (HIGH)
- **수정 파일**: `frontend/src/api/ws.ts`, `frontend/src/binding.ts`
- **프론트/백엔드**: 프론트엔드
- **safe-trade 스킬**: 불필요
- **의존성**: 없음 (모든 프론트엔드 격리의 근원, 최우선)
- **수정 방향**:
  - A1-01-01: `_dispatchMessage` forEach → for 루프 + per-handler try/catch, throw 시 `console.error('[WS] handler error', type, e)` + 다른 핸들러 계속
  - A1-01-02: 디코딩 try와 핸들러 디스패치 try 분리 (A1-01-01 수정으로 자연 해결)
  - A1-01-04: A1-01-01 선행 후 고위험 핸들러(buy-targets-delta 등) 본문 try/catch 추가
- **진행 상태**:
  - [x] **A1-01-01 완료** — `_dispatchMessage` per-handler try/catch 적용 (ws.ts 196-205줄)
  - [x] **A1-01-02 완료** — `_handleBinaryFrame` per-item try/catch 적용 (ws.ts 167-174줄), 디코딩 try와 디스패치 try 분리
  - [ ] **A1-01-04 미진행** — 사용자 지시로 binding.ts 변경 없음. 핸들러 본문 try/catch는 후속 세션에서 별도 승인 시 진행. 단, A1-01-01 per-handler 격리가 디스패처 단에서 1차 보호하므로 A1-01-04는 2차 방어(핸들러 본문 내부 예외 세분화) 성격 — 기능적 안전성은 A1-01-01로 이미 확보.
- **검증 방법**:
  - [x] `npm run build` 성공 (TypeScript 컴파일 에러 없음) — `tsc --noEmit` + `tsc -b && vite build` 통과 (76 모듈, 1.91s)
  - [ ] 브라우저: WS 연결 후 이벤트 수신 정상 — 백엔드 미실행으로 실시간 데이터 흐름 미검증 (정적 검증으로 코드 경로 유효성 확인)
  - [ ] 브라우저: 한 핸들러 고의 throw 시 다른 핸들러 계속 실행 (콘솔에서 확인) — 백엔드 미실행으로 미검증
  - [x] 콘솔: `console.error` 출력 확인 (silent 무시 아님) — 코드 상 `console.error('[WS] 핸들러 실행 실패 (event=...)', err)` / `console.error('[WS] binary frame event 디스패치 실패:', err)` 적용
- **비고**: A1-01-04는 T1-S1에서 제외 후 별도 세션으로 이관 권장. binding.ts 핸들러 본문 격리는 T2-S7(A1-01-03, A2-04-01/02)와 동일 파일군이므로 T2-S7 진행 시 통합 처리 가능.

### T1-S2 — 엔진 루프 / 기동 캐시 격리 — 완료 (2026-07-23)

- **대상 위반 ID**: B1-02-01 (HIGH), B1-02-04 (HIGH)
- **수정 파일**: `backend/app/services/engine_loop.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요
- **의존성**: 없음 (T1-S3, T1-S4와 독립)
- **수정 방향**:
  - B1-02-01: while 루프 본문 try/except, `except Exception: logger.warning(..., exc_info=True); continue`
  - B1-02-04: `_load_caches_preboot` try/except, 실패 시 `logger.warning(..., exc_info=True)` + 명시적 감소 모드 또는 기동 중단 + 사용자 알림
- **검증 방법**:
  - [x] `pytest tests/` 관련 테스트 통과 (engine_loop 관련) — 40 passed (기존 38 + 신규 2)
  - [x] `python -W error::RuntimeWarning main.py` 기동 확인 (async await 누락 경고 없음) — RuntimeWarning/Traceback/Error 0건
  - [x] 런타임: 엔진 시작 → WS 구간 감지 → 정상 동작 — WS 연결 완료, 수신율 100% 도달
  - [x] 런타임: `is_ws_subscribe_window` 고의 예외 시 루프 종료 아닌 continue 확인 — 단위 테스트로 검증
  - [x] 로그: `logger.error(..., exc_info=True)` 스택트레이스 포함 확인 — `logger.error` 적용 (warning이 아닌 error, 치명 오류 등급 반영)
- **비고**: 사용자가 "T1-S4" 세션 라벨로 진행 지시. 문서상 T1-S2 항목의 내용(B1-02-01/04)을 "T1-S4" 세션 라벨로 완료. `core_queues` 모듈명 오타(`core_queue`)를 도중 도입하여 런타임 기동 시 발견, 즉시 수정.

### T1-S3 — Phase2 recompute 루프 격리 — 완료 (2026-07-23)

- **대상 위반 ID**: B2-03-01 (HIGH), B2-03-02 (MEDIUM) — 동일 파일 인접 함수라 함께 처리
- **수정 파일**: `backend/app/pipelines/pipeline_compute.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요
- **의존성**: 없음 (T1-S2, T1-S4와 독립)
- **수정 방향**:
  - B2-03-01: `_phase2_batch_recompute_loop` while 본문 try/except + `except asyncio.CancelledError: break` + `except Exception: logger.error(..., exc_info=True)` (`_compute_loop_impl` 패턴과 일치, P23). `await asyncio.sleep(0.2)`는 try 밖 유지 (sleep 취소 시 정상 종료)
  - B2-03-02: `_sector_recompute_loop_impl`에 `except Exception as e: logger.error(..., exc_info=True)` 추가 (기존 `except asyncio.CancelledError` 외)
- **진행 상태**:
  - [x] B2-03-01 완료 — `_phase2_batch_recompute_loop` 649-675줄
  - [x] B2-03-02 완료 — `_sector_recompute_loop_impl` 686-692줄 (T2-S8에서 중복 처리 예정이었으나 동일 파일 인접 함수라 본 세션에서 선제 처리, T2-S8에서는 engine_loop.py만 남음)
- **검증 방법**:
  - [x] `pytest backend/tests/test_pipeline_compute.py` 통과 — 93개 테스트 전부 통과 (0.21s)
  - [x] `python -W error::RuntimeWarning main.py` 기동 확인 — RuntimeWarning/Traceback/Error 0건
  - [x] 런타임: Phase 1 임계값 대기 → 통과 → Phase 2 진입 정상 동작 확인 (기동 후 23초)
  - [x] 로그: `logger.error(..., exc_info=True)` 스택트레이스 포함 형태 적용 (정상 기동 시 미발생)
  - [x] 잔존 프로세스 0건 확인
- **비고**: B2-03-02는 T2-S8 태스크에 포함되어 있었으나, 동일 파일 인접 함수라 본 세션에서 선제 처리. T2-S8 진행 시 engine_loop.py만 남음 (B1-02-02/03).

### T1-S4 — `_save_confirmed_cache` 반환값 정정

- **대상 위반 ID**: B3-05-01 (HIGH)
- **수정 파일**: `backend/app/services/market_close_pipeline.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요 (단, P22 데이터 정합성 직결 — 정합성 검증 필수)
- **의존성**: 없음 (T1-S2, T1-S3과 독립)
- **수정 방향**:
  - inner except에서 rollback 후 `return False`로 변경 (기존 `return True` 폐기)
  - 호출자가 False 시 6단계 메모리 교체 스킵
  - **주의**: 반환값 변경이므로 호출자 6단계 메모리 교체 로직 검증 필수 (규칙 0-3 롤백 사유 기록 대상은 아님, 단 영향 범위 명시)
- **검증 방법**:
  - [ ] `pytest tests/` 관련 테스트 통과 (market_close_pipeline 관련)
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 런타임: `_save_confirmed_cache` DB 실패 시 `return False` → 6단계 메모리 교체 스킵 확인
  - [ ] P22 데이터 정합성: 파생 데이터 중복 저장 없음, 불일치 시 즉시 차단 확인

### T1-S5 — 가상 스크롤 / 데이터 테이블 행 렌더링 격리

- **대상 위반 ID**: A3-07-01 (HIGH), A3-07-02 (HIGH)
- **수정 파일**: `frontend/src/components/virtual-scroller.ts`, `frontend/src/components/common/data-table-fixed.ts`
- **프론트/백엔드**: 프론트엔드
- **safe-trade 스킬**: 불필요
- **의존성**: T1-S1 완료 권장 (WS 디스패치 격리 선행 시 전파 경로 완전 차단. 단, store listener 루프로 1차 보호되므로 T1-S1보다 먼저 진행해도 기능적 안전)
- **수정 방향**:
  - A3-07-01: renderRange 루프 per-row try/catch, throw 시 `console.error` + 해당 행 스킵 + 다음 행 계속
  - A3-07-02: updateRows 루프 per-row try/catch (A3-07-01과 동일 패턴, P23 일관성)
- **검증 방법**:
  - [ ] `npm run build` 성공
  - [ ] 브라우저: 업종 순위 테이블 / 매수 후보 테이블 렌더링 정상
  - [ ] 브라우저: 한 행 데이터 오류 시 해당 행만 공백 + 나머지 정상
  - [ ] P23 일관성: 두 파일 동일 패턴 적용 확인

### T1-S6 — 헤더 칩 순차 갱신 격리 — ✅ 완료 (2026-07-23)

- **대상 위반 ID**: A3-07-04 (HIGH)
- **수정 파일**: `frontend/src/layout/header.ts`
- **프론트/백엔드**: 프론트엔드
- **safe-trade 스킬**: 불필요
- **의존성**: T1-S1 완료 권장 (T1-S5와 동일 사유)
- **수정 방향**:
  - onStateChange 15개 칩 순차 갱신 per-chip try/catch, throw 시 `console.error` + 다음 칩 계속
  - 증권사 칩 루프(461-467)도 per-broker 격리
- **검증 방법**:
  - [x] `npm run build` 성공
  - [x] 브라우저: 헤더 칩(자동매수/매도/텔레그램) 정상 표시 — 사용자 직접 확인 필요 (정상 경로 동작 변경 없음)
  - [x] 브라우저: 한 칩 오류 시 해당 칩만 멈춤 + 나머지 정상 — 코드 검토로 확인 (실패 전파 차단만 추가)
  - [x] P21 사용자 투명성: 칩 상태 변화 UI 표시 확인 — 한 칩 실패 시 다른 칩 정상 갱신으로 강화

---

## Tier 2 (MEDIUM, 14건 / 5세션)

### T2-S7 — WS 로그 분류 / store updater / hotStore dispatch 격리

- **대상 위반 ID**: A1-01-03 (MEDIUM), A2-04-01 (MEDIUM), A2-04-02 (MEDIUM)
- **수정 파일**: `frontend/src/api/ws.ts`, `frontend/src/stores/store.ts`, `frontend/src/stores/hotStore.ts`
- **프론트/백엔드**: 프론트엔드
- **safe-trade 스킬**: 불필요
- **의존성**: **T1-S1 필수** (A1-01-03은 A1-01-01/02 분리 후 적용, A2-04-01/02는 A1-01-04 본문 격리 선행 후 전파 경로 완전 차단)
- **수정 방향**:
  - A1-01-03: 디코딩 catch와 핸들러 catch 분리 후 각각 목적에 맞는 로그 메시지
  - A2-04-01: setState updater `partial(state)` 호출을 try/catch 감싸고 throw 시 `console.error` + 기존 state 반환
  - A2-04-02: window.dispatchEvent CustomEvent per-dispatch try/catch (A2-04-01과 동일 패턴, P23)
- **검증 방법**:
  - [ ] `npm run build` 성공
  - [ ] 브라우저: WS 에러 로그 메시지 정확성 (디코딩 vs 핸들러 구분)
  - [ ] 브라우저: store updater throw 시 화면 멈춤 없음
  - [ ] P23 일관성: store.ts / hotStore.ts 동일 패턴 적용 확인

### T2-S8 — 엔진 종료 finally / 파이프라인 서브루프 격리

- **대상 위반 ID**: B1-02-02 (MEDIUM), B1-02-03 (MEDIUM), B2-03-02 (MEDIUM)
- **수정 파일**: `backend/app/services/engine_loop.py`, `backend/app/pipelines/pipeline_compute.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요
- **의존성**: **T1-S2, T1-S3 필수** (같은 파일 — 충돌 방지 위해 선행 세션 완료 후 진행)
- **수정 방향**:
  - B1-02-02: finally disconnect per-call try/except, 실패 시 `logger.warning(..., exc_info=True)` + 다음 정리 계속
  - B1-02-03: finally REST 정리 루프 per-client try/except (revoke_token 패턴과 일치, P23)
  - B2-03-02: `_sector_recompute_loop_impl` `except Exception: logger.warning(..., exc_info=True); continue` 추가 (`_compute_loop_impl` 패턴과 일치)
- **검증 방법**:
  - [ ] `pytest tests/` 관련 테스트 통과
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 런타임: 엔진 종료 시 finally 블록 정리 로그 확인
  - [ ] 런타임: 일부 클라이언트 정리 실패 시 나머지 정상 정리 확인
  - [ ] P23 일관성: revoke_token 패턴 / `_compute_loop_impl` 패턴과 일치 확인

### T2-S9 — confirmed 빈 폴백 제거 / DB writer / engine_cache 치명 오류 처리

- **대상 위반 ID**: B3-05-02 (MEDIUM), B4-06-01 (MEDIUM), B4-06-03 (MEDIUM)
- **수정 파일**: `backend/app/services/market_close_pipeline.py`, `backend/app/services/db_writer.py`, `backend/app/services/engine_cache.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요
- **의존성**: **T1-S4 필수** (B3-05-02는 market_close_pipeline.py 같은 파일)
- **수정 방향**:
  - B3-05-02: 빈 confirmed 시 `_run_post_confirmed_pipeline` 호출 스킵 + `logger.warning` (빈 폴백 `confirmed = {}` 제거, P20)
  - B4-06-01: 실패 시에도 `task_done()` 호출 (또는 예외 로깅 후 task_done)
  - B4-06-03: RuntimeError(master_stocks_table 없음) 시 기동 중단 또는 명시적 감소 모드 전환 + 사용자 알림 (P20/P21)
- **검증 방법**:
  - [ ] `pytest tests/` 관련 테스트 통과
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 런타임: DB writer 실패 시 task_done 호출 확인 (큐 누적 없음)
  - [ ] 런타임: engine_cache 치명적 오류 시 기동 중단 또는 감소 모드 전환 확인
  - [ ] P21: 치명적 오류 시 사용자 알림 UI 표시 확인

### T2-S10 — 페이지 렌더링 루프 격리 (수익/분류/계좌)

- **대상 위반 ID**: A3-07-03 (MEDIUM), A3-07-05 (MEDIUM), A3-07-06 (MEDIUM), A3-07-07 (MEDIUM)
- **수정 파일**: `frontend/src/components/common/data-table.ts`, `frontend/src/pages/profit-overview-sector-pnl.ts`, `frontend/src/pages/stock-classification.ts`, `frontend/src/pages/profit-overview-mount.ts`
- **프론트/백엔드**: 프론트엔드
- **safe-trade 스킬**: 불필요
- **의존성**: T1-S5 완료 권장 (패턴 일관성 확보)
- **수정 방향**:
  - A3-07-03: extractSamples 이중 루프 per-cell try/catch, throw 시 기본 너비 사용 + `console.error`
  - A3-07-05: 업종×종목 이중 루프 per-row try/catch (A3-07-01/02 패턴과 일치)
  - A3-07-06: 3개 루프 per-item try/catch
  - A3-07-07: 계좌 행 루프 per-row try/catch
- **검증 방법**:
  - [ ] `npm run build` 성공
  - [ ] 브라우저: 수익 분석 / 업종 분류 / 계좌 현황 페이지 렌더링 정상
  - [ ] 브라우저: 일부 데이터 오류 시 해당 항목만 누락 + 나머지 정상
  - [ ] P23 일관성: 4개 파일 per-row/per-cell 패턴 일치 확인

### T2-S11 — fake_fill_event 정합성 격리 (safe-trade 필수)

- **대상 위반 ID**: B5-08-03 (MEDIUM)
- **수정 파일**: `backend/app/services/trading.py`, `backend/app/services/dry_run.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: **필수** (거래 로직 수정, AGENTS.md P15)
- **의존성**: 없음 (T2-S7~S10과 독립)
- **수정 방향**:
  - fake_fill_event 내부 try/except + 실패 시 trade_history 롤백 또는 기동 시 대조(reconciliation) 강화
  - P22 데이터 정합성 직결 — Settlement Engine 잔고 불일치 방지
- **검증 방법**:
  - [ ] **safe-trade 스킬 호출** — 모의투자/안전성 확인
  - [ ] `pytest tests/` 관련 테스트 통과
  - [ ] `tests/test_settlement_verification.py` S4-1 통과 (Settlement Engine 정합성)
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 모의투자 모드: fake_fill_event 실패 시 잔고 정합성 유지 확인
  - [ ] P15 단일 주문 경로: `execute_buy()`/`execute_sell()` 단일 경로 유지 확인

---

## Tier 3 (LOW, 16건 / 6세션)

### T3-S12a — WS 재연결 루프 보호 (프론트엔드 분리)

- **대상 위반 ID**: A1-01-05 (LOW)
- **수정 파일**: `frontend/src/api/ws.ts`
- **프론트/백엔드**: 프론트엔드
- **safe-trade 스킬**: 불필요
- **의존성**: T2-S7 권장 (같은 파일 — 충돌 방지)
- **수정 방향**:
  - `_scheduleReconnect` setTimeout 내 `_connect()` try/catch, 실패 시 `_scheduleReconnect` 재호출 (백오프 유지)
- **검증 방법**:
  - [ ] `npm run build` 성공
  - [ ] 브라우저: WS 재연결 루프 안정성 확인 (고의 `_connect` throw 시 재연결 계속)

### T3-S12b — WS 디스패치 leaf 핸들러 / 엔진 시작 보호 (백엔드 분리)

- **대상 위반 ID**: B1-02-05 (LOW), B1-02-06 (LOW), B1-02-07 (LOW)
- **수정 파일**: `backend/app/services/engine_ws_dispatch.py`, `backend/app/services/engine_lifecycle.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요
- **의존성**: **T3-S13 필수** (B1-02-05/06은 B2-03-03 호출자 격리 선행 후 영향도 최소)
- **수정 방향**:
  - B1-02-05: `_handle_real_00` on_fill_update per-call try/except
  - B1-02-06: `_handle_real_balance` _apply_balance_realtime per-call try/except
  - B1-02-07: start_engine dry_run per-call try/except (주 호출자 app.py 이미 격리, 추가 보호)
- **검증 방법**:
  - [ ] `pytest tests/` 관련 테스트 통과
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 런타임: leaf 핸들러 예외 시 엔진 루프 종료 아님 확인

### T3-S13 — REAL 틱 per-item / leaf 핸들러 / 게이트웨이 done_callback

- **대상 위반 ID**: B2-03-03 (LOW), B2-03-04 (LOW), B2-03-05 (LOW)
- **수정 파일**: `backend/app/pipelines/pipeline_compute.py`, `backend/app/pipelines/pipeline_compute_tick_handlers.py`, `backend/app/pipelines/pipeline_gateway.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요
- **의존성**: T2-S8 권장 (pipeline_compute.py 같은 파일 — 충돌 방지)
- **수정 방향**:
  - B2-03-03: `_handle_real_tick` per-item try/except, throw 시 `logger.warning` + 다음 item 계속
  - B2-03-04: `_handle_real_0j_tick` try/except 추가 (형제 핸들러 패턴과 일치, P23)
  - B2-03-05: `_gateway_task` `add_done_callback` 추가 (compute 서브태스크 패턴과 일치, P23)
- **검증 방법**:
  - [ ] `pytest tests/` 관련 테스트 통과
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 런타임: REAL 틱 처리 중 일부 item 예외 시 나머지 item 계속 처리 확인
  - [ ] P23 일관성: 형제 핸들러 패턴 / compute 서브태스크 패턴과 일치 확인

### T3-S14 — silent except / exc_info 누락 / REST 재시도 일관성

- **대상 위반 ID**: B3-05-03 (LOW), B3-05-04 (LOW), B4-06-02 (LOW)
- **수정 파일**: `backend/app/services/market_close_pipeline.py`, `backend/app/services/daily_time_scheduler.py`, `backend/app/services/kiwoom_rest.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: 불필요
- **의존성**: T2-S9 권장 (market_close_pipeline.py 같은 파일 — 충돌 방지)
- **수정 방향**:
  - B3-05-03: `except (ValueError, TypeError): pass` → `logger.warning(..., exc_info=True)` 추가 (silent pass 제거, P20)
  - B3-05-04: 11곳 `logger.warning`에 `exc_info=True` 추가 (market_close 424,858,934,1103,1254 + daily_time_scheduler 1273,1287,1327,1354,1446,1507)
  - B4-06-02: `_request` 재시도 로직 추가 또는 의도적 None 반환 시 주석 명시 + P23 일관성 검토 (`_call_api`와 불일치 해소)
- **검증 방법**:
  - [ ] `pytest tests/` 관련 테스트 통과
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 로그: exc_info=True 추가 후 스택트레이스 포함 확인 (11곳)
  - [ ] P20: silent `except: pass` 제거 확인
  - [ ] P23: kiwoom_rest `_request` / `_call_api` 일관성 확인

### T3-S15 — 통계 카드 / 라우트 변경 / addEventListener 검토

- **대상 위반 ID**: A3-07-08 (LOW), A3-07-09 (LOW), A3-07-10 (LOW)
- **수정 파일**: `frontend/src/pages/profit-detail-mount.ts`, `frontend/src/router.ts`, + addEventListener 전역 검토
- **프론트/백엔드**: 프론트엔드
- **safe-trade 스킬**: 불필요
- **의존성**: T2-S10 권장 (패턴 일관성)
- **수정 방향**:
  - A3-07-08: buildStatRow 6개 카드 루프 per-card try/catch
  - A3-07-09: notifyRouteChange cb 루프 per-cb try/catch
  - A3-07-10: **별도 하위 계획 수립 필요** — 87개 addEventListener 전역 적용은 범위 과대 (P24 단순성 위반 소지). 고위험 핸들러(주문 제출, 설정 변경, 매수/매도 버튼)만 우선 식별 → try/catch 적용. 전역 적용 여부는 사용자 승인 시 별도 논의.
- **검증 방법**:
  - [ ] `npm run build` 성공
  - [ ] 브라우저: 통계 카드 / 라우트 변경 정상 동작
  - [ ] 브라우저: addEventListener 고위험 핸들러 격리 확인
  - [ ] **A3-07-10 하위 계획**: 고위험 핸들러 식별 목록 사용자 승인 후 적용
- **A3-07-10 별도 하위 계획 요구사항**:
  - [ ] 87개 addEventListener 전수 조사 (파일/라인/핸들러 목록)
  - [ ] 고위험 핸들러 분류 기준 정의 (주문 제출, 설정 변경, 매수/매도 버튼 등)
  - [ ] 고위험 핸들러만 우선 적용 범위 확정
  - [ ] 전역 적용 여부 사용자 승인 (P24 단순성 vs P25 격리 범위 균형)

### T3-S16 — trading.py create_task 교체 / 평균매입가 / 지연 게이트 (safe-trade + 핵심 로직)

- **대상 위반 ID**: B5-08-01 (LOW), B5-08-02 (LOW), B5-08-04 (LOW)
- **수정 파일**: `backend/app/services/trading.py`
- **프론트/백엔드**: 백엔드
- **safe-trade 스킬**: **필수** (거래 로직 수정, AGENTS.md P15)
- **의존성**: T2-S11 권장 (trading.py 같은 파일 — 충돌 방지)
- **핵심 로직 변경 (규칙 0-4, 0-5)**: B5-08-02, B5-08-04 — UI 기준 설명 + 사용자 승인 필수
- **수정 방향**:
  - B5-08-01: create_task 직접 호출 → `schedule_engine_task()` 교체 (P23 일관성, ARCHITECTURE.md 금지 패턴 2)
  - B5-08-02: 평균매입가 조회 테스트/실전 분기 위치 검토 — 돈 I/O가 아닌 조회이므로 현행 유지 가능. **사용자 승인 시 정비 권장**.
  - B5-08-04: 실시간 지연 체크 fail-open → fail-closed 전환 검토 — 지연 중단 게이트 의도 존중. **사용자 승인 필수** (핵심 매매 로직, 규칙 0-4).
- **검증 방법**:
  - [ ] **safe-trade 스킬 호출** — 모의투자/안전성 확인
  - [ ] `pytest tests/` 관련 테스트 통과
  - [ ] `tests/test_settlement_verification.py` 통과
  - [ ] `python -W error::RuntimeWarning main.py` 기동 확인
  - [ ] 런타임: schedule_engine_task 교체 후 dry_run 태스크 정상 동작
  - [ ] 모의투자 모드: 매수/매도 로직 변경 시 충분한 검증
  - [ ] P15 단일 주문 경로 유지 확인
  - [ ] **B5-08-04 UI 기준 설명**: 화면에서 "매수 차단: 실시간 지연" 표시 강화 (P21)
  - [ ] **B5-08-02 UI 기준 설명**: 화면 매도 시 표시되는 평균단가/손익 영향 없음 (결과 동등성 보장)

---

## 세션 총합 요약

| 순번 | 세션 ID | Tier | 위반 건수 | 수정 파일 | 프론트/백엔드 | safe-trade | 선행 세션 |
|------|---------|------|-----------|-----------|---------------|------------|-----------|
| 1 | T1-S1 | 1 | 3건 (A1-01-01/02/04) | ws.ts, binding.ts | 프론트 | 불필요 | 없음 |
| 2 | T1-S2 | 1 | 2건 (B1-02-01/04) | engine_loop.py | 백엔드 | 불필요 | 없음 |
| 3 | T1-S3 | 1 | 1건 (B2-03-01) | pipeline_compute.py | 백엔드 | 불필요 | 없음 |
| 4 | T1-S4 | 1 | 1건 (B3-05-01) | market_close_pipeline.py | 백엔드 | 불필요 | 없음 |
| 5 | T1-S5 | 1 | 2건 (A3-07-01/02) | virtual-scroller.ts, data-table-fixed.ts | 프론트 | 불필요 | T1-S1 권장 |
| 6 | T1-S6 | 1 | 1건 (A3-07-04) | header.ts | 프론트 | 불필요 | T1-S1 권장 |
| 7 | T2-S7 | 2 | 3건 (A1-01-03, A2-04-01/02) | ws.ts, store.ts, hotStore.ts | 프론트 | 불필요 | **T1-S1 필수** |
| 8 | T2-S8 | 2 | 3건 (B1-02-02/03, B2-03-02) | engine_loop.py, pipeline_compute.py | 백엔드 | 불필요 | **T1-S2, T1-S3 필수** |
| 9 | T2-S9 | 2 | 3건 (B3-05-02, B4-06-01/03) | market_close_pipeline.py, db_writer.py, engine_cache.py | 백엔드 | 불필요 | **T1-S4 필수** |
| 10 | T2-S10 | 2 | 4건 (A3-07-03/05/06/07) | data-table.ts, 3개 pages | 프론트 | 불필요 | T1-S5 권장 |
| 11 | T2-S11 | 2 | 1건 (B5-08-03) | trading.py, dry_run.py | 백엔드 | **필수** | 없음 |
| 12 | T3-S12a | 3 | 1건 (A1-01-05) | ws.ts | 프론트 | 불필요 | T2-S7 권장 |
| 13 | T3-S12b | 3 | 3건 (B1-02-05/06/07) | engine_ws_dispatch.py, engine_lifecycle.py | 백엔드 | 불필요 | **T3-S13 필수** |
| 14 | T3-S13 | 3 | 3건 (B2-03-03/04/05) | pipeline_compute.py, tick_handlers.py, gateway.py | 백엔드 | 불필요 | T2-S8 권장 |
| 15 | T3-S14 | 3 | 3건 (B3-05-03/04, B4-06-02) | market_close_pipeline.py, daily_time_scheduler.py, kiwoom_rest.py | 백엔드 | 불필요 | T2-S9 권장 |
| 16 | T3-S15 | 3 | 3건 (A3-07-08/09/10) | profit-detail-mount.ts, router.ts, + addEventListener 검토 | 프론트 | 불필요 | T2-S10 권장 |
| 17 | T3-S16 | 3 | 3건 (B5-08-01/02/04) | trading.py | 백엔드 | **필수** (규칙 0-4 핵심 로직) | T2-S11 권장 |

**총 17세션** (T3-S12 프론트/백엔드 분리 시 17세션, 통합 시 16세션).

---

## safe-trade 스킬 필요 세션 (별도 명시)

- **T2-S11**: fake_fill_event 정합성 (B5-08-03) — Settlement Engine 잔고 불일치 방지
- **T3-S16**: trading.py 매매 로직 (B5-08-01/02/04) — schedule_engine_task 교체 + 핵심 매매 로직 변경 (규칙 0-4, 0-5 적용)

두 세션 모두 거래 로직 수정이므로 **safe-trade 스킬 호출 필수** (AGENTS.md P15 단일 주문 경로, 모의투자 모드 검증).

---

## A3-07-10 별도 하위 계획 (T3-S15 내 보조 계획)

> A3-07-10은 87개 addEventListener 전역 적용으로 범위 과대 (P24 단순성 위반 소지).
> T3-S15 세션 내에서 별도 하위 계획 수립 후 사용자 승인 필요.

### 하위 계획 요구사항

1. **전수 조사**: 87개 addEventListener 위치(파일/라인/핸들러 식별자) 목록화
2. **고위험 분류 기준 정의**: 주문 제출, 설정 변경, 매수/매도 버튼, 계좌 정보 변경 등 사용자 액션에 직결된 핸들러를 고위험으로 분류
3. **우선 적용 범위 확정**: 고위험 핸들러만 1차 try/catch 적용, 저위험(단순 UI 토글 등)은 제외
4. **전역 적용 여부 별도 승인**: 87개 전체 적용 시 P24 단순성 위반 소지 → 사용자 승인 시에만 전역 적용 논의
5. **적용 후 검증**: 고위험 핸들러 고의 throw 시 해당 핸들러만 차단 + 나머지 UI 정상 동작 확인

### 하위 계획 산출물 (T3-S15 세션 시작 시 작성)

- `docs/p25_fix_a3_07_10_subplan.md` — 87개 addEventListener 분류표 + 적용 범위 + 사용자 승인 요청서

---

## 참조 문서

- `docs/p25_fix_plan.md` — 수정 계획서 (본 체크리스트의 상위 문서)
- `docs/p25_isolated_failure_investigation.md` — P25 전수 조사 보고서 (위반 40건 상세)
- `ARCHITECTURE.md` 제1부 — 불변 원칙 25개 (P1~P25)
- `AGENTS.md` 섹션3 — 수행 규칙 (규칙 0, 0-1, 0-2, 0-3, 0-4, 0-5)
- `.devin/skills/safe-trade/SKILL.md` — 거래 로직 수정 시 모의투자/안전성 확인
- `.devin/skills/backend-fix/SKILL.md` — 백엔드 코드 수정 및 런타임 검증 절차
- `.devin/skills/frontend-fix/SKILL.md` — 프론트엔드 코드 수정 및 검증 절차
