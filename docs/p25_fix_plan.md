# SectorFlow P25 (격리된 실패) 위반 40건 수정 계획서

> 작성일: 2026-07-23
> 기준 문서: `docs/p25_isolated_failure_investigation.md` (전수 조사 보고서)
> 성격: **설계 문서 (수정 계획)** — 사용자 승인 전까지 코드 수정 금지 (AGENTS.md 섹션3 규칙 0)
> 진행 방식: Tier 1 → Tier 2 → Tier 3 순차 진행, 세션당 1단계 (규칙 0-1)

---

## 1. 계획 개요

### 1.1 목적

`p25_isolated_failure_investigation.md`에서 식별된 P25 위반 40건을 체계적으로 수정.
- 한 구성요소의 실패가 전체 시스템 기동/운영을 블로킹하지 않도록 격리
- 실패 시 해당 구성요소에서 차단 + 에러 로깅 (silent pass 금지, P20/P23 일관)
- 의존성이 있는 위반은 선행 수정이 후속 수정에 영향주지 않도록 순서 보장

### 1.2 Tier 분류 기준

| Tier | 등급 | 건수 | 기준 |
|------|------|------|------|
| **Tier 1** | CRITICAL + HIGH | 10건 | 한 구성요소 실패가 시스템 전체 중단(자동매매 정지, 화면 전체 멈춤) 또는 주요 기능(매수 후보 산출, 업종 점수) 중단 유발 |
| **Tier 2** | MEDIUM | 14건 | 한 구성요소 실패가 일부 기능 손실(알림 누락, 데이터 불일치 등). 시스템은 동작하나 품질 저하 |
| **Tier 3** | LOW | 16건 | 일관성 위반(혼용 패턴, exc_info 누락 등). 즉시 중단 유발 아님, 정비 권장 |

### 1.3 수정 원칙 (모든 Tier 공통)

1. **P25 본질 준수**: 실패는 해당 구성요소에서 차단 + `logger.warning(..., exc_info=True)` / `console.error` 로깅. 다른 구성요소 정상 작동 유지.
2. **P20 폴백 금지**: 정상 경로의 빈 값/None을 폴백으로 덮지 않음. silent `except: pass` 금지.
3. **P23 일관성**: 동일 패턴은 파일 간 동일 구조 적용. `schedule_engine_task()` vs 직접 `create_task` 혼용 해소.
4. **P24 단순성**: 과도한 격리 추상화 금지. 최소 전파 차단에 국한. 함수 50줄 이하 유지.
5. **P16 살아있는 경로**: 격리 코드는 실제 실행 경로에 연결. dead code 아님.
6. **세션당 1단계 (규칙 0-1)**: 각 세션은 1단계만 진행. 검증 → 커밋 → HANDOVER.md 갱신 → 보고 후 종료.
7. **승인 전 수정 금지 (규칙 0)**: 본 설계 문서 승인 후에만 수정 시작.

---

## 2. 의존성 그래프

```
A1-01-01 (WS 디스패치 격리) ←──── 모든 프론트엔드 위반의 근원
  ├── A1-01-02 (binary frame 루프) → A1-01-01 수정으로 자연 해결
  ├── A1-01-03 (catch 로그 분류) → A1-01-01/A1-01-02 분리 후 적용
  ├── A1-01-04 (binding.ts 33 핸들러) → A1-01-01 선행 후 본문 격리 결정
  ├── A2-04-01 (setState updater) → A1-01-04 → A1-01-01 전파 경로
  └── A2-04-02 (hotStore dispatchEvent) → A1-01-04 → A1-01-01 전파 경로

B1-02-05/06 (engine_ws_dispatch) → B2-03-03 (_handle_real_tick per-item) 호출자 격리
B2-03-04 (_handle_real_0j_tick) → B2-03-03 경로 합류
B5-08-03 (fake_fill_event 정합성) → 기동 시 대조(reconciliation) 메커니즘 (세션 9 교차)
```

**핵심 의존성 결론**:
- **A1-01-01은 모든 프론트엔드 격리의 기반** — Tier 1 최우선 수정.
- **B2-03-03은 B1-02-05/06의 상위 격리** — B2-03-03이 Tier 3이나 B1-02-05/06도 Tier 3이므로 같은 Tier 내에서 순서만 보장.
- **A1-01-02는 A1-01-01 수정으로 자연 해결** — 별도 수정 불필요, A1-01-01 세션에서 함께 처리.

---

## 3. Tier 1 상세 (CRITICAL + HIGH, 10건)

### 3.1 위반 목록

| ID | 등급 | 파일:줄 | 위반 요약 | 수정 방향 |
|----|------|---------|-----------|-----------|
| A1-01-01 | CRITICAL | `frontend/src/api/ws.ts:193` | `_dispatchMessage` forEach 핸들러별 try/catch 없음 | forEach → for 루프 + per-handler try/catch, throw 시 `console.error('[WS] handler error', type, e)` + 다른 핸들러 계속 |
| A1-01-02 | CRITICAL | `frontend/src/api/ws.ts:164-174` | binary frame 루프가 try 내부 → 후속 이벤트 손실 | 디코딩 try와 핸들러 디스패치 try 분리 (A1-01-01 수정으로 자연 해결) |
| A1-01-04 | HIGH | `frontend/src/binding.ts` 33개 핸들러 | 내부 try/catch 없음 | A1-01-01로 디스패치 격리 확보 후, 고위험 핸들러(buy-targets-delta 등) 본문 try/catch 추가 |
| B1-02-01 | HIGH | `backend/app/services/engine_loop.py:304` | `is_ws_subscribe_window` 호출 무보호 → 엔진 루프 종료 | while 루프 본문을 try/except로 감싸고 `except Exception: logger.warning(..., exc_info=True); continue` |
| B1-02-04 | HIGH | `backend/app/services/engine_loop.py:31` | `_load_caches_preboot` 무보호 → 엔진 기동 차단 | try/except 감싸고 실패 시 `logger.warning(..., exc_info=True)` + 캐시 없이 진행(폴백 아닌 명시적 감소 모드) 또는 기동 중단 시 사용자 알림 |
| B2-03-01 | HIGH | `backend/app/pipelines/pipeline_compute.py:646-670` | Phase2 recompute 루프 본문 무보호 → 태스크 사망 | while 루프 본문 try/except + `except Exception: logger.warning(..., exc_info=True); continue` (`_compute_loop_impl` 패턴과 일치) |
| B3-05-01 | HIGH | `backend/app/services/market_close_pipeline.py:645-650` | `_save_confirmed_cache` 실패 시 True 반환 → 후속 단계 잘못된 전제 | inner except에서 rollback 후 `return False`로 변경. 호출자가 False 시 6단계 메모리 교체 스킵 |
| A3-07-01 | HIGH | `frontend/src/components/virtual-scroller.ts:293-316` | renderRange 루프 renderRow 무보호 → 가시 영역 공백 | per-row try/catch, throw 시 `console.error` + 해당 행 스킵 + 다음 행 계속 |
| A3-07-02 | HIGH | `frontend/src/components/common/data-table-fixed.ts:230-236` | updateRows 루프 renderDataRow 무보호 → 테이블 전체 실패 | per-row try/catch (A3-07-01과 동일 패턴, P23 일관성) |
| A3-07-04 | HIGH | `frontend/src/layout/header.ts:365-494` | onStateChange 15개 칩 순차 갱신 무보호 → 일부 칩 방치 | per-chip try/catch, throw 시 `console.error` + 다음 칩 계속. 증권사 칩 루프(461-467)도 per-broker 격리 |

### 3.2 수정 범위

| 세션 | 위반 ID | 수정 파일 | 프론트/백엔드 |
|------|---------|-----------|---------------|
| T1-S1 | A1-01-01, A1-01-02, A1-01-04 | `frontend/src/api/ws.ts`, `frontend/src/binding.ts` | 프론트엔드 |
| T1-S2 | B1-02-01, B1-02-04 | `backend/app/services/engine_loop.py` | 백엔드 |
| T1-S3 | B2-03-01 | `backend/app/pipelines/pipeline_compute.py` | 백엔드 |
| T1-S4 | B3-05-01 | `backend/app/services/market_close_pipeline.py` | 백엔드 |
| T1-S5 | A3-07-01, A3-07-02 | `frontend/src/components/virtual-scroller.ts`, `frontend/src/components/common/data-table-fixed.ts` | 프론트엔드 |
| T1-S6 | A3-07-04 | `frontend/src/layout/header.ts` | 프론트엔드 |

### 3.3 의존성

- **T1-S1 → T1-S5/T1-S6**: A1-01-01(WS 디스패치 격리)이 선행되어야 A3 UI 렌더링 격리의 전파 경로가 완전 차단. 단, A3는 store listener 루프(F-02 fix)로 이미 1차 보호되므로 T1-S5/T1-S6를 T1-S1보다 먼저 진행해도 기능적 안전. 권장 순서: T1-S1 우선.
- **T1-S1 내부**: A1-01-01 먼저 수정 → A1-01-02 자연 해결 → A1-01-04 본문 격리. 한 세션에서 순차 적용.
- **T1-S2 ~ T1-S4**: 서로 독립 (백엔드 파일 상이). 순서 무관.

### 3.4 검증 기준

#### 프론트엔드 세션 (T1-S1, T1-S5, T1-S6)
- `npm run build` 성공 (TypeScript 컴파일 에러 없음)
- 브라우저 수동 확인:
  - T1-S1: WS 연결 후 이벤트 수신 정상, 한 핸들러 고의 throw 시 다른 핸들러 계속 실행 (콘솔에서 확인)
  - T1-S5: 업종 순위 테이블 / 매수 후보 테이블 렌더링 정상, 한 행 데이터 오류 시 해당 행만 공백 + 나머지 정상
  - T1-S6: 헤더 칩(자동매수/매도/텔레그램) 정상 표시, 한 칩 오류 시 해당 칩만 멈춤 + 나머지 정상
- `python -W error::RuntimeWarning` 해당 없음 (프론트엔드)

#### 백엔드 세션 (T1-S2, T1-S3, T1-S4)
- `pytest tests/` 관련 테스트 통과 (각 세션에서 대상 파일 관련 테스트 식별 후 실행)
- `python -W error::RuntimeWarning main.py` 기동 확인 (async await 누락 경고 없음)
- 런타임 기동: 엔진 시작 → WS 구간 감지 → 파이프라인 실행 → 정상 동작 확인
- T1-S2: 엔진 루프 중 `is_ws_subscribe_window` 고의 예외 시 루프 종료 아닌 continue 확인
- T1-S3: Phase2 recompute 루프 중 예외 시 루프 종료 아닌 continue 확인
- T1-S4: `_save_confirmed_cache` DB 실패 시 `return False` → 6단계 메모리 교체 스킵 확인

---

## 4. Tier 2 상세 (MEDIUM, 14건)

### 4.1 위반 목록

| ID | 등급 | 파일:줄 | 위한 요약 | 수정 방향 |
|----|------|---------|-----------|-----------|
| A1-01-03 | MEDIUM | `frontend/src/api/ws.ts:172,181` | catch 로그 "파싱 실패"가 핸들러 예외와 혼동 | 디코딩 catch와 핸들러 catch 분리 후 각각 목적에 맞는 로그 메시지 |
| B1-02-02 | MEDIUM | `backend/app/services/engine_loop.py:374,377` | finally disconnect 무보호 → 후속 정리 스킵 | per-call try/except, 실패 시 `logger.warning(..., exc_info=True)` + 다음 정리 계속 |
| B1-02-03 | MEDIUM | `backend/app/services/engine_loop.py:387,389` | finally REST 정리 루프 무보호 → 일부 클라이언트 미정리 | per-client try/except (revoke_token 패턴과 일치, P23) |
| B2-03-02 | MEDIUM | `backend/app/pipelines/pipeline_compute.py:673-686` | `_sector_recompute_loop_impl` except Exception 없음 | `except Exception: logger.warning(..., exc_info=True); continue` 추가 (`_compute_loop_impl` 패턴과 일치) |
| A2-04-01 | MEDIUM | `frontend/src/stores/store.ts:19` | setState updater `partial(state)` try/catch 밖 | updater 호출을 try/catch 감싸고 throw 시 `console.error` + 기존 state 반환 |
| A2-04-02 | MEDIUM | `frontend/src/stores/hotStore.ts:367-370,390,412,431` | window.dispatchEvent CustomEvent 핸들러 무보호 | per-dispatch try/catch (A2-04-01과 동일 패턴) |
| B3-05-02 | MEDIUM | `backend/app/services/market_close_pipeline.py:897` | `confirmed = {}` 빈 폴백 → 빈 eligible_codes로 후속 진행 | 빈 confirmed 시 `_run_post_confirmed_pipeline` 호출 스킵 + `logger.warning` |
| B4-06-01 | MEDIUM | `backend/app/services/db_writer.py:79` | 실패 시 task_done 스킵 → 큐 미완료 누적 | 실패 시에도 `task_done()` 호출 (또는 예외 로깅 후 task_done) |
| B4-06-03 | MEDIUM | `backend/app/services/engine_cache.py:148-149` | 치명적 오류를 "무시" 처리 → P20 폴백 | RuntimeError(master_stocks_table 없음) 시 기동 중단 또는 명시적 감소 모드 전환 + 사용자 알림 |
| A3-07-03 | MEDIUM | `frontend/src/components/common/data-table.ts:104-112` | extractSamples 이중 루프 render 무보호 → 너비 계산 실패 | per-cell try/catch, throw 시 기본 너비 사용 + `console.error` |
| A3-07-05 | MEDIUM | `frontend/src/pages/profit-overview-sector-pnl.ts:139-168` | 업종×종목 이중 루프 무보호 → 수익 분석 왜곡 | per-row try/catch (A3-07-01/02 패턴과 일치) |
| A3-07-06 | MEDIUM | `frontend/src/pages/stock-classification.ts:278-322` | 3개 루프 무보호 → 분류 UI 불완전 | per-item try/catch |
| A3-07-07 | MEDIUM | `frontend/src/pages/profit-overview-mount.ts:101-133` | 계좌 행 루프 무보호 → 잔고 정보 누락 | per-row try/catch |
| B5-08-03 | MEDIUM | `backend/app/services/trading.py:477-482,666-671` + `dry_run.py:153-198` | fake_fill_event 태스크 실패 시 Settlement Engine 잔고 불일치 | fake_fill_event 내부 try/except + 실패 시 trade_history 롤백 또는 기동 시 대조(reconciliation) 강화 |

### 4.2 수정 범위

| 세션 | 위반 ID | 수정 파일 | 프론트/백엔드 |
|------|---------|-----------|---------------|
| T2-S7 | A1-01-03, A2-04-01, A2-04-02 | `frontend/src/api/ws.ts`, `frontend/src/stores/store.ts`, `frontend/src/stores/hotStore.ts` | 프론트엔드 |
| T2-S8 | B1-02-02, B1-02-03, B2-03-02 | `backend/app/services/engine_loop.py`, `backend/app/pipelines/pipeline_compute.py` | 백엔드 |
| T2-S9 | B3-05-02, B4-06-01, B4-06-03 | `backend/app/services/market_close_pipeline.py`, `backend/app/services/db_writer.py`, `backend/app/services/engine_cache.py` | 백엔드 |
| T2-S10 | A3-07-03, A3-07-05, A3-07-06, A3-07-07 | `frontend/src/components/common/data-table.ts`, `frontend/src/pages/profit-overview-sector-pnl.ts`, `frontend/src/pages/stock-classification.ts`, `frontend/src/pages/profit-overview-mount.ts` | 프론트엔드 |
| T2-S11 | B5-08-03 | `backend/app/services/trading.py`, `backend/app/services/dry_run.py` | 백엔드 (safe-trade 스킬 필수) |

### 4.3 의존성

- **T2-S7 → T1-S1**: A1-01-03은 A1-01-01/A1-01-02 분리 후 적용. A2-04-01/A2-04-02는 A1-01-04(본문 격리) 선행 후 전파 경로 완전 차단. **T1-S1 완료 후 진행 필수**.
- **T2-S8 → T1-S2/T1-S3**: B1-02-02/03은 engine_loop.py finally 블록 (T1-S2와 같은 파일). B2-03-02는 pipeline_compute.py (T1-S3와 같은 파일). **같은 파일이므로 T1-S2/T1-S3 완료 후 진행** (충돌 방지).
- **T2-S9 → T1-S4**: B3-05-02는 market_close_pipeline.py (T1-S4와 같은 파일). **T1-S4 완료 후 진행**.
- **T2-S10 → T1-S5**: A3-07-03은 data-table.ts (A3-07-02 data-table-fixed.ts와 유사 패턴이나 다른 파일). A3-07-05/06/07은 pages. **T1-S5 완료 후 진행 권장** (패턴 일관성 확보).
- **T2-S11**: 독립적이나 **safe-trade 스킬 필수** (거래 로직 수정, AGENTS.md P15). 테스트모드 한정이나 Settlement Engine 정합성(P22) 관련.

### 4.4 검증 기준

#### 프론트엔드 세션 (T2-S7, T2-S10)
- `npm run build` 성공
- 브라우저 수동 확인:
  - T2-S7: WS 에러 로그 메시지 정확성 (디코딩 vs 핸들러 구분), store updater throw 시 화면 멈춤 없음
  - T2-S10: 수익 분석 / 업종 분류 / 계좌 현황 페이지 렌더링 정상, 일부 데이터 오류 시 해당 항목만 누락

#### 백엔드 세션 (T2-S8, T2-S9, T2-S11)
- `pytest tests/` 관련 테스트 통과
- `python -W error::RuntimeWarning main.py` 기동 확인
- T2-S8: 엔진 종료 시 finally 블록 정리 로그 확인, 일부 클라이언트 정리 실패 시 나머지 정상 정리
- T2-S9: DB writer 실패 시 task_done 호출 확인, engine_cache 치명적 오류 시 기동 중단 또는 감소 모드 전환 확인
- T2-S11: **safe-trade 스킬 호출**, 테스트모드에서 fake_fill_event 실패 시 잔고 정합성 유지 확인, `tests/test_settlement_verification.py` S4-1 통과

---

## 5. Tier 3 상세 (LOW, 16건)

### 5.1 위반 목록

| ID | 등급 | 파일:줄 | 위반 요약 | 수정 방향 |
|----|------|---------|-----------|-----------|
| A1-01-05 | LOW | `frontend/src/api/ws.ts:132-136` | `_scheduleReconnect` setTimeout 무보호 | `_connect()` try/catch, 실패 시 `_scheduleReconnect` 재호출(백오프 유지) |
| B1-02-05 | LOW | `backend/app/services/engine_ws_dispatch.py:149-153` | `_handle_real_00` on_fill_update 무보호 | per-call try/except (B2-03-03 선행 후 호출자 격리 확보되면 영향도 최소) |
| B1-02-06 | LOW | `backend/app/services/engine_ws_dispatch.py:162` | `_handle_real_balance` _apply_balance_realtime 무보호 | per-call try/except |
| B1-02-07 | LOW | `backend/app/services/engine_lifecycle.py:38` | start_engine dry_run 무보호 | per-call try/except (주 호출자 app.py는 이미 격리, 추가 보호) |
| B2-03-03 | LOW | `backend/app/pipelines/pipeline_compute.py:521-526` | `_handle_real_tick` per-item 무보호 | per-item try/except, throw 시 `logger.warning` + 다음 item 계속 |
| B2-03-04 | LOW | `backend/app/pipelines/pipeline_compute_tick_handlers.py:92-104` | `_handle_real_0j_tick` try/except 없음 (다른 leaf 핸들러와 불일치) | try/except 추가 (형제 핸들러 패턴과 일치, P23) |
| B2-03-05 | LOW | `backend/app/pipelines/pipeline_gateway.py:32` | `_gateway_task` done_callback 없음 | `add_done_callback` 추가 (compute 서브태스크 패턴과 일치, P23) |
| B3-05-03 | LOW | `backend/app/services/market_close_pipeline.py:492` | `except (ValueError, TypeError): pass` silent | `logger.warning(..., exc_info=True)` 추가 |
| B3-05-04 | LOW | 11곳 (market_close 424,858,934,1103,1254 + daily_time_scheduler 1273,1287,1327,1354,1446,1507) | exc_info 누락 | 각 `logger.warning`에 `exc_info=True` 추가 |
| B4-06-02 | LOW | `backend/app/services/kiwoom_rest.py:353-356` | `_request` 재시도 없이 None 반환 (_call_api와 불일치) | 재시도 로직 추가 또는 의도적 None 반환 시 주석 명시 + P23 일관성 검토 |
| A3-07-08 | LOW | `frontend/src/pages/profit-detail-mount.ts:185-222` | buildStatRow 6개 카드 루프 무보호 | per-card try/catch |
| A3-07-09 | LOW | `frontend/src/router.ts:105-109` | notifyRouteChange cb 루프 무보호 | per-cb try/catch |
| A3-07-10 | LOW | 프론트엔드 전역 87개 addEventListener | 핸들러 대부분 try/catch 없음 | 빈도 낮으나 P25 적용 미흡 — **별도 검토 필요**: 87개 전역 적용은 범위 과대, 고위험 핸들러(주문/설정 변경)만 우선 try/catch 권장 |
| B5-08-01 | LOW | `backend/app/services/trading.py:477-482,666-671` | create_task 직접 호출 (schedule_engine_task 미사용) | `schedule_engine_task()`로 교체 (P23 일관성, ARCHITECTURE.md 금지 패턴 2) |
| B5-08-02 | LOW | `backend/app/services/trading.py:572-598` | 평균매입가 조회 테스트/실전 분기 (P18 엄격 해석상 미세 위반) | 분기 위치 검토 — 돈 I/O가 아닌 조회이므로 현행 유지 가능. **사용자 승인 시 정비 권장** |
| B5-08-04 | LOW | `backend/app/services/trading.py:204-210` | 실시간 지연 체크 실패 시 매수 계속 (fail-open) | fail-closed 전환 검토 — 지연 중단 게이트 의도 존중. **사용자 승인 필수** (핵심 매매 로직, 규칙 0-4) |

### 5.2 수정 범위

| 세션 | 위반 ID | 수정 파일 | 프론트/백엔드 |
|------|---------|-----------|---------------|
| T3-S12 | A1-01-05, B1-02-05, B1-02-06, B1-02-07 | `frontend/src/api/ws.ts`, `backend/app/services/engine_ws_dispatch.py`, `backend/app/services/engine_lifecycle.py` | 프론트+백엔드 혼합 (**분리 권장**: T3-S12a 프론트, T3-S12b 백엔드) |
| T3-S13 | B2-03-03, B2-03-04, B2-03-05 | `backend/app/pipelines/pipeline_compute.py`, `backend/app/pipelines/pipeline_compute_tick_handlers.py`, `backend/app/pipelines/pipeline_gateway.py` | 백엔드 |
| T3-S14 | B3-05-03, B3-05-04, B4-06-02 | `backend/app/services/market_close_pipeline.py`, `backend/app/services/daily_time_scheduler.py`, `backend/app/services/kiwoom_rest.py` | 백엔드 |
| T3-S15 | A3-07-08, A3-07-09, A3-07-10 | `frontend/src/pages/profit-detail-mount.ts`, `frontend/src/router.ts`, + addEventListener 전역 검토 | 프론트엔드 |
| T3-S16 | B5-08-01, B5-08-02, B5-08-04 | `backend/app/services/trading.py` | 백엔드 (safe-trade 스킬 필수, 규칙 0-4 핵심 로직 변경 승인) |

### 5.3 의존성

- **T3-S12b → T3-S13**: B1-02-05/06은 B2-03-03(호출자 격리)에 의존. **T3-S13 완료 후 T3-S12b 진행 권장**. 단, 둘 다 Tier 3이므로 순서만 보장.
- **T3-S16**: B5-08-01은 schedule_engine_task 교체 (P23). B5-08-02/04는 **핵심 매매 로직** — 규칙 0-4(핵심 로직 변경 시 UI 기준 설명 + 승인) 및 규칙 0-5(사용자 설계 로직 더 엄격) 적용. **safe-trade 스킬 필수**.
- **T3-S15 (A3-07-10)**: 87개 addEventListener 전역 적용은 범위 과대. **별도 하위 계획 수립 필요** — 고위험 핸들러(주문 제출, 설정 변경, 매수/매도 버튼)만 우선 식별 후 try/catch. 전역 적용 여부는 사용자 승인 시 별도 논의.

### 5.4 검증 기준

#### 프론트엔드 세션 (T3-S12a, T3-S15)
- `npm run build` 성공
- T3-S12a: WS 재연결 루프 안정성 확인 (고의 `_connect` throw 시 재연결 계속)
- T3-S15: 통계 카드 / 라우트 변경 정상, addEventListener 고위험 핸들러 격리 확인

#### 백엔드 세션 (T3-S12b, T3-S13, T3-S14, T3-S16)
- `pytest tests/` 관련 테스트 통과
- `python -W error::RuntimeWarning main.py` 기동 확인
- T3-S13: REAL 틱 처리 중 일부 item 예외 시 나머지 item 계속 처리 확인
- T3-S14: exc_info=True 추가 후 로그에 스택트레이스 포함 확인
- T3-S16: **safe-trade 스킬 호출**, schedule_engine_task 교체 후 dry_run 태스크 정상 동작, 매수/매도 로직 변경 시 모의투자 모드에서 충분한 검증

---

## 6. 전체 세션 일정 총합

| 순번 | 세션 ID | Tier | 위반 건수 | 수정 파일 | 프론트/백엔드 | 선행 세션 |
|------|---------|------|-----------|-----------|---------------|-----------|
| 1 | T1-S1 | 1 | 3건 (A1-01-01/02/04) | ws.ts, binding.ts | 프론트 | 없음 |
| 2 | T1-S2 | 1 | 2건 (B1-02-01/04) | engine_loop.py | 백엔드 | 없음 |
| 3 | T1-S3 | 1 | 1건 (B2-03-01) | pipeline_compute.py | 백엔드 | 없음 |
| 4 | T1-S4 | 1 | 1건 (B3-05-01) | market_close_pipeline.py | 백엔드 | 없음 |
| 5 | T1-S5 | 1 | 2건 (A3-07-01/02) | virtual-scroller.ts, data-table-fixed.ts | 프론트 | T1-S1 권장 |
| 6 | T1-S6 | 1 | 1건 (A3-07-04) | header.ts | 프론트 | T1-S1 권장 |
| 7 | T2-S7 | 2 | 3건 (A1-01-03, A2-04-01/02) | ws.ts, store.ts, hotStore.ts | 프론트 | **T1-S1 필수** |
| 8 | T2-S8 | 2 | 3건 (B1-02-02/03, B2-03-02) | engine_loop.py, pipeline_compute.py | 백엔드 | **T1-S2, T1-S3 필수** |
| 9 | T2-S9 | 2 | 3건 (B3-05-02, B4-06-01/03) | market_close_pipeline.py, db_writer.py, engine_cache.py | 백엔드 | **T1-S4 필수** |
| 10 | T2-S10 | 2 | 4건 (A3-07-03/05/06/07) | data-table.ts, 3개 pages | 프론트 | T1-S5 권장 |
| 11 | T2-S11 | 2 | 1건 (B5-08-03) | trading.py, dry_run.py | 백엔드 (safe-trade) | 없음 |
| 12 | T3-S12a | 3 | 1건 (A1-01-05) | ws.ts | 프론트 | T2-S7 권장 (같은 파일) |
| 13 | T3-S12b | 3 | 3건 (B1-02-05/06/07) | engine_ws_dispatch.py, engine_lifecycle.py | 백엔드 | **T3-S13 필수** (B2-03-03 선행) |
| 14 | T3-S13 | 3 | 3건 (B2-03-03/04/05) | pipeline_compute.py, tick_handlers.py, gateway.py | 백엔드 | T2-S8 권장 (같은 파일) |
| 15 | T3-S14 | 3 | 3건 (B3-05-03/04, B4-06-02) | market_close_pipeline.py, daily_time_scheduler.py, kiwoom_rest.py | 백엔드 | T2-S9 권장 (같은 파일) |
| 16 | T3-S15 | 3 | 3건 (A3-07-08/09/10) | profit-detail-mount.ts, router.ts, + addEventListener 검토 | 프론트 | T2-S10 권장 |
| 17 | T3-S16 | 3 | 3건 (B5-08-01/02/04) | trading.py | 백엔드 (safe-trade, 규칙 0-4) | T2-S11 권장 (같은 파일) |

**총 17세션** (T3-S12를 프론트/백엔드 분리 시 17세션, 통합 시 16세션).

### 6.1 세션 분할 원칙

- **같은 파일 수정은 같은 세션 또는 순차 세션**: 동시 수정 충돌 방지.
- **프론트엔드/백엔드 혼합 세션은 분리 권장**: 검증 방법 상이 (build vs pytest+기동).
- **safe-trade 스킬 필요 세션은 별도 표시**: T2-S11, T3-S16.
- **핵심 로직 변경 세션은 규칙 0-4 적용**: T3-S16 (B5-08-02, B5-08-04) — UI 기준 설명 + 승인 필수.

### 6.2 병렬 진행 가능 세션

다음 세션 그룹은 서로 독립적이므로 순차 진행 중 병렬 검토 가능 (단, 세션당 1단계 원칙상 한 세션에서는 1개만 진행):

- **Tier 1 독립 그룹**: T1-S1, T1-S2, T1-S3, T1-S4 (서로 다른 파일, 의존성 없음)
- **Tier 2 독립 그룹**: T2-S11 (T2-S7~S10과 독립)
- **Tier 3 독립 그룹**: T3-S14, T3-S15 (서로 다른 파일)

---

## 7. 검증 전략 총합

### 7.1 프론트엔드 검증 (모든 프론트엔드 세션 공통)

1. `npm run build` — TypeScript 컴파일 에러 없음
2. 브라우저 수동 확인 — 해당 기능 정상 동작 + 고의 예외 시 격리 동작 확인
3. 콘솔 에러 로그 — `console.error` 출력 확인 (silent 무시 아님, P20)

### 7.2 백엔드 검증 (모든 백엔드 세션 공통)

1. `pytest tests/` — 관련 테스트 통과 (각 세션에서 대상 파일 관련 테스트 식별)
2. `python -W error::RuntimeWarning main.py` — async await 누락 경고 없음 (ARCHITECTURE.md 금지 패턴 4)
3. 런타임 기동 — 엔진 시작 → 파이프라인 실행 → 정상 동작 확인
4. 로그 확인 — `logger.warning(..., exc_info=True)` 스택트레이스 포함 확인

### 7.3 거래 로직 세션 추가 검증 (T2-S11, T3-S16)

1. **safe-trade 스킬 호출** — 모의투자/안전성 확인 (AGENTS.md P15)
2. `tests/test_settlement_verification.py` — Settlement Engine 정합성 테스트 통과
3. 모의투자 모드에서 충분한 검증 — 실전 전환 전 사용자 명시적 승인

### 7.4 세션 완료 조건 (모든 세션 공통)

- 검증 이상 없음 → `git commit` (롤백 사유 기록 의무, 규칙 0-3)
- `HANDOVER.md` 갱신 — "직전 완료 작업" 섹션에 해당 세션 내용 명시
- 사용자 보고 — UI 기준 일반 용어로 수정 내용 + 화면 변화 설명 (규칙 0-4)
- 다음 세션은 새 세션에서 `HANDOVER.md` 기반으로 이어서 진행 (규칙 0-1)

---

## 8. 리스크 및 주의사항

### 8.1 수정 시 주의 (AGENTS.md 체크리스트)

- **P1-P3 (async 일관성)**: 백엔드 수정 시 동기 함수(`requests`, `sqlite3`, `time.sleep`) 금지
- **P4 (증권사명 침투 금지)**: 공통 로직에 `kiwoom_`/`ls_` 접두사 없는지 확인
- **P5 (EventBus 금지)**: 격리를 위해 Pub-Sub/옵서버 패턴 도입 금지, 직접 호출 체인 유지
- **P15 (단일 주문 경로)**: T2-S11, T3-S16 수정 시 `execute_buy()`/`execute_sell()` 단일 경로 유지
- **P20 (폴백 금지)**: 격리 try/catch에서 빈 값/None으로 폴백 덮지 않음. 실패 시 명시적 처리(스킵 + 로깅, 또는 중단 + 알림)
- **P22 (데이터 정합성)**: B3-05-01, B5-08-03은 정합성 직결 — 파생 데이터 중복 저장 금지, 불일치 시 즉시 차단
- **P24 (단순성)**: 격리 추상화 과도 금지. per-item try/catch는 단순 래퍼 함수로 패턴화 (P23 일관성)

### 8.2 핵심 로직 변경 특별 주의 (규칙 0-4, 0-5)

- **T3-S16 (B5-08-02, B5-08-04)**: 매매 로직 변경. UI 기준 설명 필수:
  - B5-08-02: 평균매입가 조회 경로 단일화 — 화면에서 매도 시 표시되는 평균단가/손익에 영향 없음 (결과 동등성 보장)
  - B5-08-04: 실시간 지연 체크 fail-closed 전환 — 지연 중단 게이트가 실시간 통신 200ms 초과 시 매수를 차단하도록 변경. 화면에서 "매수 차단: 실시간 지연" 표시 강화 필요 (P21)
- **사용자 설계 로직 (규칙 0-5)**: B5-08-04는 사용자가 설계한 지연 중단 게이트. 변경 사유·영향·대안 상세 보고 후 승인 필수.

### 8.3 A3-07-10 (87개 addEventListener) 특별 검토

- 87개 전역 addEventListener에 일괄 try/catch 적용은 범위 과대 (P24 단순성 위반 소지)
- **권장 방향**: 고위험 핸들러(주문 제출, 설정 변경, 매수/매도 버튼)만 우선 식별 → try/catch 적용
- 전역 적용 여부는 T3-S15 세션에서 별도 하위 계획 수립 후 사용자 승인

### 8.4 롤백 주의 (규칙 0-3)

- 본 수정 계획은 "격리 추가"이지 기존 로직 제거/회귀가 아님. 단, B3-05-01(`return True` → `return False`)은 기존 반환값 변경이므로 호출자 6단계 메모리 교체 로직에 영향. **롤백 사유 기록 의무** 적용 대상은 아님 (신규 격리 추가이므로), 단 반환값 변경은 호출자 검증 필수.

---

## 9. 승인 요청

본 설계 문서는 **수정 계획서**입니다. 사용자 승인 전까지 어떤 코드 수정도 수행하지 않습니다 (AGENTS.md 섹션3 규칙 0).

### 9.1 승인 시 필요 항목

1. **Tier 1 전체 승인 여부** — 10건 CRITICAL/HIGH 위반 수정 진행
2. **Tier 2 전체 승인 여부** — 14건 MEDIUM 위반 수정 진행
3. **Tier 3 전체 승인 여부** — 16건 LOW 위반 수정 진행 (핵심 로직 B5-08-02/04는 별도 승인)
4. **세션 분할(17세션) 승인 여부** — 세션당 1단계 원칙 준수
5. **A3-07-10 하위 계획 별도 수립 승인 여부** — 87개 addEventListener 전역 적용 범위

### 9.2 승인 후 진행 순서

1. T1-S1 (WS 디스패치 격리) — 모든 프론트엔드 격리의 기반
2. T1-S2 ~ T1-S4 (백엔드 Tier 1, 병렬 가능)
3. T1-S5, T1-S6 (프론트엔드 UI 렌더링 Tier 1)
4. T2-S7 ~ T2-S11 (Tier 2, 의존성 순서 준수)
5. T3-S12a ~ T3-S16 (Tier 3, 의존성 순서 준수)

각 세션 완료 시마다 검증 → 커밋 → HANDOVER.md 갱신 → UI 기준 보고 후 다음 세션 진행.

---

## 10. 참조 문서

- `docs/p25_isolated_failure_investigation.md` — P25 전수 조사 보고서 (위반 40건 상세)
- `ARCHITECTURE.md` 제1부 — 불변 원칙 25개 (P1~P25)
- `AGENTS.md` 섹션3 — 수행 규칙 (규칙 0, 0-1, 0-2, 0-3, 0-4, 0-5)
- `.devin/skills/safe-trade/SKILL.md` — 거래 로직 수정 시 모의투자/안전성 확인
- `.devin/skills/backend-fix/SKILL.md` — 백엔드 코드 수정 및 런타임 검증 절차
- `.devin/skills/frontend-fix/SKILL.md` — 프론트엔드 코드 수정 및 검증 절차
