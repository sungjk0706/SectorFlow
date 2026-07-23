# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. 이전 세션의 완료 작업, 현재 상태, 다음 세션에서 이어서 진행할 항목을 기록.

---

## 직전 완료 작업

### T3-S12a/S12b REAL 틱 per-item 격리 + 0J 핸들러 + 게이트웨이 done_callback + REST 재시도 일관성 — 완료 (2026-07-23) — B2-03-03/04/05 + B4-06-02 완료 (Tier 3 첫 세션, LOW 4건)

**세션**: 단일 세션. 백엔드 코드 수정 (backend-fix + problem-solve 스킬). 세션 라벨 T3-S12a/S12b (사용자 지정 — 문서상 T3-S13 + T3-S14 일부).

**배경**: P25 수정 계획 Tier 3 첫 세션. 사용자가 문서상 T3-S13(B2-03-03/04/05)과 T3-S14의 B4-06-02를 한 세션에 묶어 "T3-S12a/S12b" 라벨로 진행 지시. 모두 LOW 등급·동일 성격(격리 패턴 정비)이므로 한 세션 처리. T2-S8(pipeline_compute.py 같은 파일)·T2-S9(market_close_pipeline.py 같은 파일) 권장 의존성 해결 상태에서 진행.

**작업 내용** (4건 + 테스트 2건):
1. **B2-03-03 (LOW) 완료** — `pipeline_compute.py:521-531` `_handle_real_tick` for 루프 per-item try/except 추가. 한 item 예외 시 같은 REAL 틱의 나머지 item 계속 처리. 외곽 try/except(_extract_real_items 보호)는 유지. `_process_tick_batch`(262-267) 패턴 재사용 — `logger.error("[연산] 아이템 처리 오류 (계속): %s", e, exc_info=True)`.
2. **B2-03-04 (LOW) 완료** — `pipeline_compute_tick_handlers.py:92-107` `_handle_real_0j_tick` 본문 try/except 추가. 형제 leaf 핸들러(01/0d/PGM)는 이미 try/except 있는데 0J만 누락되어 P23 위반 → 해소. `logger.error("[연산] 업종지수 틱(0J) 처리 오류: %s", e, exc_info=True)`.
3. **B2-03-05 (LOW) 완료** — `pipeline_gateway.py:32-36` `start_gateway_loop`에 `_gateway_task.add_done_callback` 추가. compute 서브태스크(pipeline_compute.py:210-213) 패턴과 일치. app.py:63 외부 콜백은 다층 방어로 유지 (제거 시 별도 파일 수정 + 규칙 0-3 검토 대상).
4. **B4-06-02 (LOW) 완료 (Option A)** — `kiwoom_rest.py:353-360` `_request` 예외 시 즉시 `return None` → `_call_api`(188-194) 패턴대로 재시도. 3회 루프가 있어도 예외 경로는 1회만 실행되던 P23 위반 해소. `if attempt < 2: await asyncio.sleep(3*(attempt+1)); continue; return None`. 로그에 시도 횟수 추가.
5. **테스트**:
   - `test_pipeline_compute.py`: 신규 2건 — `test_per_item_exception_continues_remaining_items`(B2-03-03), `TestHandleReal0jTickException.test_exception_does_not_raise`(B2-03-04).
   - `test_kiwoom_rest.py`: 기존 `test_exception`에 `asyncio.sleep` 패치 추가 + 신규 `test_exception_retry_then_success`(B4-06-02).

**수정 파일**: 6개 (백엔드 4 + 테스트 2).
- `backend/app/pipelines/pipeline_compute.py` (+9줄)
- `backend/app/pipelines/pipeline_compute_tick_handlers.py` (+16줄)
- `backend/app/pipelines/pipeline_gateway.py` (+4줄)
- `backend/app/core/kiwoom_rest.py` (+5줄)
- `backend/tests/test_pipeline_compute.py` (+25줄)
- `backend/tests/test_kiwoom_rest.py` (+16줄)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 4건 직접 해결 — 한 item/leaf/태스크/REST 호출 실패가 형제/전체로 전파 차단.
- P23 (일관성): B2-03-04(형제 핸들러 패턴), B2-03-05(compute 서브태스크 done_callback 패턴), B4-06-02(`_call_api` 재시도 패턴) — 기존 패턴에 맞춤.
- P20 (폴백 금지): silent `except: pass` 없음 — 전부 `logger.error/warning(..., exc_info=True)`.
- P16 (살아있는 경로): per-item try/except는 실시간 틱 처리 경로에 직접 배선, done_callback은 태스크 생성 시 부착.
- P24 (단순성): 함수 50줄 이하 유지, 신규 추상화/상수 없음, 기존 패턴 3줄 복제.
- P23 (공통 자산 재사용): per-item 패턴(_process_tick_batch), leaf 패턴(_handle_real_0d_tick), done_callback 패턴(pipeline_compute.py:210-213), 재시도 패턴(_call_api:188-194) 재사용. 신규 함수/상수 없음.

**영향 범위**: 백엔드 4개 파일 + 테스트 2개 파일. 프론트엔드 영향 없음. 핵심 매매 로직(매수/매도 조건, 수신률, 업종 점수) 변경 없음 — 규칙 0-4 해당 없음. 롤백 아님 (신규 격리 코드 추가만, 기존 로직 제거 없음) — 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 정상 동작 변화 없음.
- 비정상 상황에서만 개선: 실시간 틱의 여러 종목 중 1개 처리 오류여도 나머지 종목 화면 갱신 계속(기존은 같은 틱 나머지 종목 누락). 업종지수 표시 중 오류 시에도 틱 흐름 유지. 계좌 잔고 조회 일시적 통신 오류 시 자동 재시도 후 화면 표시(기존은 즉시 실패).

**검증**:
- `py_compile` 6개 파일 통과.
- `ruff check` — 본 수정 범위 밖 unused import 2건(`time`, `_check_realtime_latency`) 잔존. T2-S11에서 이미 HANDOVER 미해결 문제에 기록된 항목 — 중복 기록 생략.
- `pytest test_pipeline_compute.py test_kiwoom_rest.py` — 182 passed (신규 3건 포함).
- `python -W error::RuntimeWarning main.py` 기동 — RuntimeWarning/Traceback/Error 0건, 게이트웨이·compute 루프 정상 기동, 실시간 틱 수신 정상 (NXT 80%+ 진행).
- 종료 시 finally 블록 전 단계 정상 실행, 잠금 파일 자동 삭제.
- 잔존 프로세스 0건 확인 (이전 세션 잔존 PID 19201 + 본 세션 자식 19970 모두 정리).

**작업 중 발견 문제**: 없음. (unused import 2건은 T2-S11에서 이미 기록된 항목)

**핵심 결정**:
- B4-06-02 Option A(재시도 추가) 선택: 3회 재시도 루프가 이미 존재하므로 "의도적 단일 시도" 주석(Option B)은 코드와 모순. `_call_api`와 동일 패턴 적용으로 P23 일관성 확보.
- app.py:63 외부 done_callback 유지: 제거 시 별도 파일 수정 + 규칙 0-3 검토 대상. 다층 방어로 의도적이므로 본 세션 범위에서 유지.
- 사용자 라벨 "T3-S12a/S12b"와 문서상 라벨 "T3-S13 + T3-S14 일부" 불일치 — 본 세션은 사용자 라벨 따르되, 태스크 파일에는 문서상 라벨(T3-S13/T3-S14) 기준으로 체크 표시.

**다음 세션 대기 사항**:
- **Tier 3 잔여**: T3-S12a(A1-01-05 프론트, 문서상 T3-S12a), T3-S12b(B1-02-05/06/07 백엔드, 문서상 T3-S12b — T3-S13 선행 완료로 의존성 해결), T3-S14 잔여(B3-05-03/04 백엔드), T3-S15(A3-07-08/09/10 프론트), T3-S16(B5-08-01/02/04 백엔드, safe-trade 필수 + 규칙 0-4 핵심 로직). 총 5세션.
- **중요 안내**: 본 세션에서 이미 문서상 T3-S13(B2-03-03/04/05) 완료. 사용자가 "다음 세션: T3-S13 진행"이라고 하셨으나, 문서상 T3-S13은 본 세션에서 완료됨. 다음 세션 후보는 위 잔여 5세션 중 선택 필요.

---

### T2-S11 fake_fill_event 정합성 격리 (기동 시 대조 메커니즘 신설) — 완료 (2026-07-23) — B5-08-03 완료 (Tier 2 마지막 세션, safe-trade 적용)

**세션**: 단일 세션. 백엔드 코드 수정 (safe-trade 스킬). 세션 라벨 T2-S11 (Tier 2 마지막 세션, MEDIUM 1건).

**배경**: P25 수정 계획 Tier 2 마지막 세션. fake_fill_event 태스크 실패/취소 시 on_buy_fill/on_sell_fill이 누락되어 Settlement Engine 잔고(_orderable)가 거래 이력과 불일치하는 상태가 영속화되는 것을 방지 (P22 데이터 정합성). 세션9 조사에서 기동 시 대조 메커니즘 부재 확정 — 본 세션에서 메커니즘 신설.

**작업 내용** (신규 메커니즘 3개 파일 + 테스트 1개 파일):
1. **trade_history.py** — `compute_expected_orderable(initial_deposit, trade_mode)` 신설. _buy_history/_sell_history에서 주문가능금액 재계산. on_buy_fill/on_sell_fill 공식과 동일 (BUY_COMMISSION/SELL_COMMISSION/SECURITIES_TAX 상수 재사용). ts 오름차순 병합 처리. trade_mode="test"만 대조 (실전은 증권사 서버 SSOT).
2. **settlement_engine.py** — `reconcile_with_trades()` 신설. compute_expected_orderable 호출 후 현재 _orderable과 대조. 일치 시 debug 로그. 불일치 시 error 로그 + 재계산값으로 _orderable 복구 + _persist + _broadcast_delta + UI 알림(settlement_reconciled 이벤트 — 불일치 금액/복구 여부). 대조 자체 실패 시 기동 중단 아님 (P25 격리된 실패).
3. **engine_cache.py** — `_load_caches_preboot` 내 load_state 직후 reconcile_with_trades 호출 추가 (테스트모드만, 1줄).
4. **test_settlement_verification.py** — S4-1 확장: 태스크 취소 후 정합성 위반 상태에서 reconcile_with_trades 호출 시 거래내역 기준으로 orderable 복구 검증 추가.
5. **test_engine_cache.py** — autouse fixture 추가: reconcile_with_trades를 AsyncMock으로 패치 (engine_cache 테스트는 캐시 로드 로직 검증이 목적, settlement 정합성 검증이 아님 — _persist DB writer 큐 대기로 무한 hang 방지).

**수정 파일**: 5개 (백엔드 3 + 테스트 2).
- `backend/app/services/trade_history.py` (+33줄, compute_expected_orderable 신설)
- `backend/app/services/settlement_engine.py` (+50줄, reconcile_with_trades 신설)
- `backend/app/services/engine_cache.py` (+2줄, 기동 시 대조 호출)
- `backend/tests/test_settlement_verification.py` (+6줄, S4-1 복구 검증)
- `backend/tests/test_engine_cache.py` (+13줄, autouse fixture)

**아키텍처 원칙 부합**:
- P22 (데이터 정합성): 본 위반의 직접 해결 — 기동 시 거래내역 기준 잔고 재계산·대조·복구.
- P10 (SSOT): trade_history가 잔고의 진실 원천. orderable이 별도 영속화되어 SSOT 분산 상태 → 대조로 단일화.
- P16 (살아있는 경로): 기동 시 매번 실행되는 _load_caches_preboot 경로에 배선.
- P20 (폴백 금지): 불일치 시 silent pass 아님 — error 로그 + UI 알림 + 자동 복구.
- P21 (사용자 투명성): 불일치 발견 시 settlement_reconciled 이벤트로 화면에 알림 (잔고 자동 보정 표시).
- P25 (격리된 실패): 대조 실패 시 엔진 기동 중단 아님 — error 로깅 후 계속 진행.
- P15 (단일 주문 경로): 유지 — execute_buy()/execute_sell() 경로 변경 없음.
- P18 (테스트모드 동등성): 유지 — 실전모드는 증권사 서버가 SSOT이므로 대조 대상 아님 (테스트모드만 대조).
- P23 (공통 자산 재사용): on_buy_fill/on_sell_fill 공식·상수·_persist/_broadcast_delta/_safe_broadcast 재사용. 신규 상수/패턴 없음.

**영향 범위**: 백엔드 3개 파일 + 테스트 2개 파일. 프론트엔드 영향 없음 (기존 account-update WS 채널 + 신규 settlement_reconciled 이벤트 수신만). 핵심 매매 로직(매수/매도 조건, 주문 경로, 수수료 계산식) 변경 없음 — 규칙 0-4 해당 없음. 롤백 아님 (신규 메커니즘 추가만, 규칙 0-3 해당 없음).

**검증**:
- `pytest tests/test_settlement_verification.py tests/test_settlement_engine.py tests/test_dry_run.py tests/test_dry_run_fill_event.py tests/test_engine_cache.py` — 131 passed (settlement 관련 전체).
- `python -W error::RuntimeWarning main.py` 기동 확인 — RuntimeWarning 없음, 기동 성공. 기동 시 대조 로그 확인: "[정산] 기동 대조 완료 — 주문가능 870,541원 (일치)" — 메커니즘 정상 작동 확인.
- P15 단일 주문 경로 유지 확인 — execute_buy()/execute_sell() 변경 없음.

**작업 중 발견 문제**: 없음.

**핵심 결정**:
- 기동 시 대조 메커니즘 방식 선택 (세션9 조사 결과 11.4.4 반영): fake_fill_event 내부 try/except + 실패 시 trade_history 롤백 방식 대신 기동 시 대조 방식 선택. 이유: fake_fill_event 실패 시 롤백은 태스크 취소/프로세스 비정상 종료 시 처리 불가 — 기동 시 대조가 유일한 복구 시점. 불일치 시 자동 복구(재계산값 적용) 선택 — 사용자 확인 대기 차단 방식은 엔진 기동 블로킹으로 P25 위반.
- test_engine_cache.py autouse fixture: reconcile_with_trades가 _persist(save_settlement_state wait=True)를 호출하는데, 테스트 환경에서 DB writer 미기동 시 무한 hang. engine_cache 테스트는 캐시 로드 로직 검증이 목적이므로 reconcile_with_trades를 AsyncMock으로 패치.

**다음 세션 대기 사항**:
- **Tier 2 완료**: T2-S7~S11 전체 완료. MEDIUM 14건 전부 완료.
- **Tier 3 진행 대기**: T3-S12a (A1-01-05, 프론트), T3-S12b (B1-02-05/06/07, 백엔드), T3-S13 (B2-03-03, 백엔드), T3-S14 (B3-05-03/04, B4-06-02, 백엔드), T3-S15 (A3-07-08/09/10, 프론트), T3-S16 (B5-08-01/02/04, 백엔드, safe-trade 필수 + 규칙 0-4 핵심 로직). 총 6세션.
- **T3-S16 주의**: B5-08-01은 schedule_engine_task 교체 (trading.py 같은 파일 — 본 세션과 충돌 방지 위해 T2-S11 권장 의존성 해결). B5-08-02/04는 핵심 매매 로직 — 규칙 0-4(핵심 로직 변경 UI 기준 설명+승인) 및 규칙 0-5(사용자 설계 로직 더 엄격) 적용. safe-trade 스킬 필수.

---

### T2-S10 페이지 렌더링 루프 격리 (수익/분류/계좌/통계) — 완료 (2026-07-23) — A3-07-05/06/07/08 완료 (Tier 2 넷째 세션, 안 B 적용)

**세션**: 단일 세션. 프론트엔드 코드 수정 (frontend-fix + problem-solve 스킬). 세션 라벨 T2-S10 (Tier 2 넷째 세션, MEDIUM 4건).

**배경**: P25 수정 계획 Tier 2 넷째 세션. 페이지 렌더링 루프 내 per-item 보호 부재로 한 항목 throw 시 전체 루프 중단 → 화면 일부 항목 누락(P25/P21 위반) 해결. T1-S5 (data-table-fixed.ts / virtual-scroller.ts per-row 격리, A3-07-01/02) 선행 완료 상태에서 진행 — 동일 패턴 일관성 확보.

**작업 내용** (안 B — 공식 3건 + A3-07-08 편입, 총 4개 파일 6개 지점):
1. **A3-07-05 (MEDIUM) 완료** — `frontend/src/pages/profit-overview-sector-pnl.ts` 139-168줄 `renderSectorStockPnl`: 업종×종목 이중 루프 per-item try/catch. 외부 루프(업종 그룹) + 내부 루프(종목 행) 각각 독립 try/catch. 한 종목 행 실패 시 해당 업종 나머지 종목 계속 렌더링, 한 업종 그룹 실패 시 다음 업종 계속 렌더링.
2. **A3-07-06 (MEDIUM) 완료** — `frontend/src/pages/stock-classification.ts` 3개 함수 per-item try/catch:
   - `updateStagingChipSectors` (278-288줄): 칩 단위 격리 — 한 칩 업종명 갱신 throw 시 다음 칩 계속 갱신.
   - `countStocksBySector` (294-308줄): 종목 단위 격리 — 한 종목 카운트 처리 throw 시 다음 종목 계속 카운트.
   - `getStocksForSector` (310-322줄): 종목 단위 격리 — 한 종목 수집 throw 시 다음 종목 계속 수집.
3. **A3-07-07 (MEDIUM) 완료** — `frontend/src/pages/profit-overview-mount.ts` 101-133줄 `buildAccountRows`: 행 루프 per-row try/catch. `valRefs.push(val)`이 인덱스 기반(`accountValRefs`/`testAccountValRefs`)이므로 실패 시 더미 span push로 인덱스 정합성 유지 (P22). 한 행 생성 실패 시 다음 행 계속 렌더링.
4. **A3-07-08 (LOW, T3-S15 소속이나 T2-S10으로 편입) 완료** — `frontend/src/pages/profit-detail-mount.ts` 185-222줄 `buildStatRow`: 6개 통계 카드 루프 per-card try/catch. `statEls.push(valEl)` + `state.statCardEls.push(stat)` 이후 `state.statCountEl = statEls[0]` 등 인덱스 참조이므로 실패 시 더미 push로 인덱스 정합성 유지 (P22).

**A3-07-03 제외 사유**: 사전조사 결과 `frontend/src/components/common/data-table.ts` 108-115줄 `extractSamples`에 이미 per-cell try/catch 적용되어 있었음. 본 세션에서 수정 불필요.

**수정 파일**: 4개 (프론트엔드).
- `frontend/src/pages/profit-overview-sector-pnl.ts` (+31/-19, 이중 루프 per-item 격리)
- `frontend/src/pages/stock-classification.ts` (+43/-26, 3개 함수 per-item 격리)
- `frontend/src/pages/profit-overview-mount.ts` (+37/-27, buildAccountRows per-row 격리 + 더미 push)
- `frontend/src/pages/profit-detail-mount.ts` (+31/-19, buildStatRow per-card 격리 + 더미 push)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 4건 모두 핵심 — 한 항목 throw 시 전체 루프 중단 방지, 다음 항목 계속 처리.
- P20 (폴백 금지): 모든 catch 블록 `console.error('[모듈명] ... error', e)` 명시 로깅 (silent pass 아님). 더미 push는 에러 경로에서만 동작 — 정상 경로의 빈 값/None을 폴백으로 덮는 분기 아님.
- P22 (데이터 정합성): 인덱스 기반 참조(`valRefs`/`statEls`/`statCardEls`)가 있는 루프는 실패 시 더미 push로 인덱스 정합성 유지 — `state.statCountEl = statEls[0]` 등 참조가 밀리지 않음.
- P23 (일관성): 기존 `data-table.ts:108-115`, `store.ts:24-29` 표준 패턴과 동일 형태(`console.error('[모듈명] ... error', e)` + continue/더미) 유지.
- P21 (사용자 투명성): 루프 일부 항목 누락 시 콘솔 로깅으로 추적 가능. UI 별도 표시는 기존 패턴과 일치하게 추가하지 않음.
- P24 (단순성): per-item try/catch는 단순 래퍼, 함수 길이 미증가.

**영향 범위**: 프론트엔드 4개 파일. 백엔드/DB/테스트 영향 없음. 정상 경로(모든 항목 렌더링 성공) 동작 변화 없음 — 예외 발생 시에만 해당 항목 스킵 + 로깅 + 다음 항목 계속. 롤백 아님 (신규 try/catch 추가만, 규칙 0-3/0-4/0-5 해당 없음). 핵심 로직(수신률/업종점수/매매/매수후보선정/매도조건) 변경 아님 — 규칙 0-4 해당 없음.

**검증**:
- `npm run typecheck` — 통과 (exit 0).
- `npm run build` — 통과 (exit 0, 76 modules transformed, 1.95s).
- `npm run lint` — 스크립트 없음 (프로젝트에 lint 미설정).
- 브라우저 검증 — 사용자 확인 대기 (수익현황/수익상세/업종분류 3개 페이지).

**작업 중 발견 문제**: 없음.

**핵심 결정**:
- 안 B 선택 (공식 3건 + A3-07-08 편입): 사용자 언급 4개 파일 중 `sector-stock.ts`는 해당 함수(`countStocksBySector`/`getStocksForSector`)가 없고 `stock-classification.ts`에 있었음. T2-S10 공식 대상 `profit-overview-sector-pnl.ts`(A3-07-05)를 누락 방지하기 위해 안 B 적용 — 공식 3건 + 사용자 언급 buildStatRow(A3-07-08, 원래 T3-S15 소속)를 T2-S10으로 편입.
- 인덱스 기반 참조 루프의 더미 push: `valRefs`/`statEls`/`statCardEls`는 이후 `state.statCountEl = statEls[0]` 등 인덱스로 참조되므로 실패 시 더미 push로 인덱스를 맞추지 않으면 참조 밀림 발생 (P22 위반). 더미는 에러 경로에서만 생성 — 정상 경로 폴백 아님 (P20 준수).

**다음 세션 대기 사항**:
- **사용자 확정**: 다음 세션은 **T2-S11** (B5-08-03 — fake_fill_event 정합성 격리, Tier 2 마지막 세션, safe-trade 필수). 백엔드 거래 로직 수정 (`backend/app/services/trading.py`, `backend/app/services/dry_run.py`). safe-trade 스킬 필수 호출 (AGENTS.md P15 단일 주문 경로). P22 데이터 정합성 직결 — Settlement Engine 잔고 불일치 방지.
- **Tier 2 진행 상태**: T2-S7, T2-S8, T2-S9, T2-S10 완료. 잔존 T2-S11 (1세션). MEDIUM 14건 중 13건 완료, 1건 잔존 (B5-08-03).

---

### T2-S9 confirmed 빈 폴백 제거 / DB writer task_done 보장 / engine_cache 치명 오류 처리 — 완료 (2026-07-23) — B3-05-02, B4-06-01, B4-06-03 완료 (Tier 2 셋째 세션)

**세션**: 단일 세션. 백엔드 코드 수정 (backend-fix + problem-solve 스킬). 세션 라벨 T2-S9 (Tier 2 셋째 세션, MEDIUM 3건).

**배경**: P25 수정 계획 Tier 2 셋째 세션. 장마감 파이프라인 빈 폴백, DB writer 큐 미완료 누적, 엔진 캐시 치명 오류 삼킴 3건 해결. T1-S4 (B3-05-01, market_close_pipeline.py 같은 파일) 선행 완료 상태에서 진행.

**작업 내용**:
1. **B3-05-02 (MEDIUM) 완료** — `backend/app/services/market_close_pipeline.py` 896-908줄: `_step5_download_daily_confirmed`에서 전종목 1일봉 시세 다운로드 실패 시 빈 폴백 `confirmed = {}` 제거. `logger.error(..., exc_info=True)` + 화면에 "❌ 다운로드 실패 — 파이프라인 중단" 진행률 전송 (P21) + `return 0, total, False` early return. 빈 데이터로 후속 파이프라인(`_run_post_confirmed_pipeline`, `execute_unified_rolling_and_save`) 진행 차단 (P20).
2. **B4-06-01 (MEDIUM) 완료** — `backend/app/db/db_writer.py` 76-84줄: `_db_writer_loop`에서 `_process_operation(op)`을 try/finally로 감싸 `task_done()` 항상 호출 보장 (P25). 실패 시 큐 미완료 카운트 누적 → graceful shutdown `queue.join()` 무한 대기 위험 제거. 예외는 기존대로 외부 except(81줄)에서 `logger.error(..., exc_info=True)` 로깅.
3. **B4-06-03 (MEDIUM) 완료** — `backend/app/services/engine_cache.py` 148-153줄: `_load_caches_preboot` 치명 오류(`master_stocks_table` 없음 RuntimeError 포함)를 "무시, 기존 흐름으로 진행"에서 log-and-rethrow(`logger.error + raise`)로 변경 (P20). 예외가 호출자 `engine_loop.py:34`로 전파 → "감소 모드로 기동" 에러 로그 + `engine-ready` 화면 전송 (P21, 기존 설계된 경로 활성화).

**수정 파일**: 6개.
- `backend/app/services/market_close_pipeline.py` (+12/-4, 빈 폴백 제거 + early return)
- `backend/app/db/db_writer.py` (+7/-2, task_done try/finally 보장)
- `backend/app/services/engine_cache.py` (+5/-2, 치명 오류 log-and-rethrow)
- `backend/tests/test_engine_cache.py` (+33/-27, 2 테스트 정정: warning → error + pytest.raises)
- `backend/tests/test_market_close_pipeline.py` (+82/-15, 신규 2 테스트: step5 실패 early return + 성공 회귀)
- `backend/tests/test_db_writer.py` (신규, 3 테스트: task_done 보장 실패/성공 + _process_operation 롤백)

**아키텍처 원칙 부합**:
- P20 (폴백 금지): B3-05-02 빈 `confirmed={}` 제거, B4-06-03 치명 오류 삼킴 제거. 모든 catch `exc_info=True`.
- P25 (격리된 실패): B4-06-01 큐 미완료 누적 방지.
- P21 (사용자 투명성): B3-05-02 실패 진행률 화면 전송, B4-06-03 감소 모드 전환 로그 + engine-ready 전송.
- P16 (살아있는 경로): 모든 격리 코드가 실제 예외 경로에 연결.
- P23 (일관성): log-and-rethrow / try-finally 패턴은 기존 코드베이스 패턴과 일관.

**영향 범위**: 백엔드 3개 파일 + 테스트 3개 파일. 프론트엔드/DB 스키마 영향 없음. 정상 경로(다운로드 성공, 쓰기 성공, 캐시 로드 성공) 동작 변화 없음 — 예외 발생 시에만 early return / task_done 보장 / 예외 전파. 롤백 아님 (신규 격리/전파 로직 추가 및 빈 폴백 제거만, 규칙 0-3/0-4/0-5 해당 없음).

**검증**:
- `py_compile` — 3개 소스 + 3개 테스트 파일 전부 통과.
- `ruff check` — 6개 파일 전부 통과 (초기 1건 F401 수정 후 0건).
- `pytest backend/tests/` — **2819 passed, 0 failed** (10.75s). 신규/정정 테스트 7개 포함.
- `python -W error::RuntimeWarning main.py` 기동 — RuntimeWarning/Traceback/Error 0건. `[데이터] 선행 캐시 로드 완료` (engine_cache 정상 경로), `[데이터] 시작됨` (db_writer 정상 시작) 확인. 15:29~15:30 로그 파일 에러/경고 0건.
- 잔존 프로세스 0건 확인.

**작업 중 발견 문제 (HANDOVER 미해결 문제에 기록)**:
- B4-06-03 "감소 모드" 화면 명시 표시 추가 필요 — engine_loop.py:35 "감소 모드로 기동" 에러 로그는 활성화되었으나, 프론트엔드에 "감소 모드" 상태를 명시적으로 표시하려면 프론트엔드 변경이 별도로 필요. 본 세션 백엔드 3건 범위 밖. (P21 부분 충족 — 백엔드 로그 + engine-ready 전송은 유지.)

**핵심 결정**:
- B3-05-02에서 early return 선택 (빈 폴백 제거): 빈 confirmed로 후속 파이프라인 진행 시 빈 캐시 저장 시도 위험이 있으므로 파이프라인 중단이 안전. 호출자(1051줄)는 반환값 `(0, total, False)` 그대로 처리 — `cached=False` 분기와 7단계 재계산 동작은 기존과 동일.
- B4-06-01에서 try/finally 선택 (task_done 보장): `_process_operation` 실패 시에도 큐 카운트 정합성 유지가 핵심. 예외 로깅은 기존 외부 except 경로 유지.
- B4-06-03에서 log-and-rethrow 선택 (치명 오류 전파): 치명 오류를 삼키면 호출자의 "감소 모드" 처리가 발화하지 않으므로 전파가 필요. engine_loop.py:34의 기존 except가 이미 "감소 모드로 기동" 에러 로그 + engine-ready 전송을 처리하도록 설계되어 있어 호출자 변경 불필요.

**다음 세션 대기 사항**:
- **사용자 확정**: 다음 세션은 **T2-S10** (A3-07-03, A3-07-05, A3-07-06, A3-07-07 — 페이지 렌더링 루프 격리: 수익/분류/계좌). 프론트엔드 수정 (data-table.ts, profit-overview-sector-pnl.ts, stock-classification.ts, profit-overview-mount.ts). 선행 의존성: T1-S5 완료 권장 (패턴 일관성 확보) — 완료됨.
- **Tier 2 진행 상태**: T2-S7, T2-S8, T2-S9 완료. 잔존 T2-S10, T2-S11 (2세션). MEDIUM 14건 중 9건 완료, 5건 잔존.

---

### T2-S8 엔진 종료 finally / 파이프라인 서브루프 격리 — 완료 (2026-07-23) — B1-02-02/03, B2-03-02 완료 (Tier 2 둘째 세션)

**세션**: 단일 세션. 백엔드 코드 수정 (backend-fix + problem-solve 스킬). 세션 라벨 T2-S8 (Tier 2 둘째 세션, MEDIUM 3건).

**배경**: P25 수정 계획 Tier 2 둘째 세션. 엔진 종료 finally 블록의 무보호 disconnect / REST 정리 루프와 파이프라인 서브루프 치명 오류 처리의 잔존 격리 부재 3건 해결. T1-S2 (engine_loop.py 기동 캐시 격리), T1-S3 (pipeline_compute.py Phase 1/2 루프 격리) 선행 완료 상태에서 진행.

**작업 내용**:
1. **B1-02-02 (MEDIUM) 완료** — `backend/app/services/engine_loop.py` 383-389줄: finally 블록 `disconnect_all()` / `disconnect()` 호출을 per-call try/except로 격리. 연결 해제 실패해도 이후 REST 토큰 폐기 루프가 실행되도록 보장 (P25). 실패 시 `logger.warning(..., exc_info=True)` (P20).
2. **B1-02-03 (MEDIUM) 완료** — `backend/app/services/engine_loop.py` 391-404줄: REST 정리 루프 per-broker 격리. `revoke_token()`과 `_reset_client()`/`_client.aclose()`를 각각 별도 try/except로 분리 — 한 증권사 토큰 폐기/클라이언트 정리 실패가 다른 증권사 정리를 차단하지 않음 (P25). 기존 `logger.warning`에 누락된 `exc_info=True` 추가 (P20).
3. **B2-03-02 (MEDIUM) 완료** — `backend/app/pipelines/pipeline_compute.py` 689-695줄: `_sector_recompute_loop_impl` `except Exception` 블록에 `_compute_running=False` 정리 추가. 치명 오류로 루프 완전 종료 시 stop_compute_loop의 cancel 대기에서 의미 없는 대기 방지 (P25). 단, T1-S3에서 이미 `except Exception: logger.error(..., exc_info=True)` 골격 처리됨 — 본 세션에서 상태 정리 보완.

**수정 파일**: 2개.
- `backend/app/services/engine_loop.py` (+19/-9, finally disconnect + REST 루프 격리)
- `backend/app/pipelines/pipeline_compute.py` (+4/-1, _sector_recompute_loop_impl 상태 정리)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 3건 모두 핵심 — 단일 예외가 엔진 종료 전체 정리 / 파이프라인 서브루프 종료 처리를 블로킹하지 않도록 per-step, per-broker 격리.
- P20 (폴백 금지): 모든 catch에 `logger.warning/error(..., exc_info=True)` 명시 로깅 (silent pass 아님). 기존 395줄 `exc_info=True` 누락 분 수정.
- P16 (살아있는 경로): 정리 로직이 끝까지 실행되도록 보장 — finally 블록 내 모든 단계가 독립 try/except로 보호.
- P23 (일관성): 338-346줄 WS 해제 루프 패턴(try/except + `logger.error(..., exc_info=True)`)과 동일 구조 적용.

**영향 범위**: 백엔드 2개 파일만 수정. 프론트엔드/DB/테스트 영향 없음. 정상 종료 경로 동작 변화 없음 — 예외 발생 시에만 로그 출력 + 정리 연속성 보장. 롤백 아님 (신규 try/except 추가 + 상태 정리 보완만, 규칙 0-3/0-4/0-5 해당 없음).

**검증**:
- `py_compile` — engine_loop.py / pipeline_compute.py 통과.
- `ruff check` — 본 세션 수정 범위 밖 unused import 2건(`time`, `_check_realtime_latency`) 잔존. 기존 잔존 — HANDOVER.md 미해결 문제에 기록.
- `python -W error::RuntimeWarning main.py` 기동 — RuntimeWarning/Traceback/Error 0건, 30초 정상 구독·수신율 갱신 (KRX 100% / NXT 100%).
- 런타임 종료 로그 — `백그라운드 업종 점수 재계산 반복 취소됨` → `백그라운드 태스크 종료 완료` → `LS증권 연결 해제 완료` → `LS증권 토큰 폐기 완료` / `키움증권 토큰 폐기 완료` → `엔진 루프 완료` → `앱 종료 완료`. finally 블록 전 단계 정상 실행 확인.
- 잔존 프로세스 0건 확인.

**작업 중 발견 문제 (HANDOVER 미해결 문제에 기록)**:
- `pipeline_compute.py:14` `import time` unused (F401) — 본 세션 수정 범위 밖. 기존 잔존.
- `pipeline_compute.py:18` `_check_realtime_latency` import unused (F401) — 본 세션 수정 범위 밖. 기존 잔존.

**핵심 결정**:
- B2-03-02에서 `_compute_running=False` 추가 선택: 치명 오류로 루프가 완전히 종료된 상태에서 플래그가 True로 잔존하면 stop_compute_loop의 `await _sector_recompute_task`가 이미 종료된 태스크를 대기하게 됨 — 의미 없는 대기 제거.
- REST 루프에서 `revoke_token()`과 `_reset_client()`/`aclose()`를 별도 try/except로 분리 선택: 토큰 폐기 실패해도 클라이언트 리소스 정리는 독립적으로 수행되어야 함 (httpx 클라이언트 미정리 시 리소스 누수).

**다음 세션 대기 사항**:
- **사용자 확정**: 다음 세션은 **T2-S9** (B3-05-02, B4-06-01, B4-06-03 — confirmed 빈 폴백 제거 / DB writer / engine_cache 치명 오류 처리). 백엔드 수정 (market_close_pipeline.py, db_writer.py, engine_cache.py). 선행 의존성: T1-S4 필수 (B3-05-02는 market_close_pipeline.py 같은 파일) — 완료됨.
- **Tier 2 진행 상태**: T2-S7, T2-S8 완료. 잔존 T2-S9~T2-S11 (3세션). MEDIUM 14건 중 6건 완료, 8건 잔존.

---

### T2-S7 WS 로그 분류 / store updater / hotStore dispatch 격리 — 완료 (2026-07-23) — A1-01-03, A2-04-01/02 완료 (Tier 2 첫 세션)

**세션**: 단일 세션. 프론트엔드 코드 수정 (frontend-fix 스킬). 세션 라벨 T2-S7 (Tier 2 첫 세션, MEDIUM 3건).

**배경**: P25 수정 계획 Tier 2 첫 세션. WS 디스패치 / store / hotStore 전파 경로의 잔존 격리 부재 3건 해결. T1-S1 (A1-01-01/02 WS 디스패치 per-handler 격리) 선행 완료 상태에서 진행.

**작업 내용**:
1. **A1-01-03 (MEDIUM) 완료** — `frontend/src/api/ws.ts` `_handleTextFrame` (180-193줄): JSON.parse try와 `_dispatchMessage` try를 분리. 기존에는 동일 try 블록 안에 있어 핸들러 예외를 "파싱 실패"로 잘못 분류하던 문제 수정. "JSON 파싱 실패" / "text frame event 디스패치 실패"로 분류 — binary frame 패턴(`_handleBinaryFrame` 171-173줄)과 일관 (P23). 단, `_handleBinaryFrame`은 T1-S1에서 이미 디코딩/디스패치 try 분리 완료 — 본 세션 추가 수정 불필요.
2. **A2-04-01 (MEDIUM) 완료** — `frontend/src/stores/store.ts` `setState` (18-29줄): updater 함수 호출 `partial(state)`를 try/catch로 격리. updater 본문 throw 시 `console.error('[Store] updater error', e)` + early return (기존 state 유지, P22 데이터 정합성). `createStore` 한 곳 수정으로 모든 store(hotStore, uiStore 등) 자동 보호 (P24 단순성). listener 루프(40-46)는 이미 per-listener try/catch로 보호됨 — updater만 미보호 상태였던 것 해결.
3. **A2-04-02 (MEDIUM) 완료** — `frontend/src/stores/hotStore.ts` 5곳 `window.dispatchEvent(new CustomEvent(...))` try/catch 격리:
   - `applyRealData` rank-0 변경 2곳 (367, 370줄)
   - `applyRealData` 변경 알림 1곳 (390줄)
   - `applyOrderbookUpdate` 1곳 (412줄)
   - `applyProgramUpdate` 1곳 (431줄)
   - 각 이벤트명(real-data-tick/orderbook-tick/program-tick)을 로그 메시지에 명시 (P21, P23). 한 UI 컴포넌트 핸들러 오류가 같은 틱의 다른 종목 시세 갱신 중단되는 것 차단 (P7, P25).

**수정 파일**: 3개.
- `frontend/src/api/ws.ts` (+8/-2, _handleTextFrame try 분리)
- `frontend/src/stores/store.ts` (+11/-1, setState updater 격리)
- `frontend/src/stores/hotStore.ts` (+25/-5, 5곳 dispatchEvent 격리)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 3건 모두 핵심 — 단일 예외가 전파 경로(WS 디스패치 → 화면 갱신 전체) 차단 방지.
- P21 (사용자 투명성): A1-01-03 로그 분류로 디버깅 시 원인 파악 가능.
- P23 (일관성): text frame = binary frame 패턴; hotStore 5곳 동일 패턴; store.ts 단일 수정으로 모든 store 보호.
- P22 (데이터 정합성): A2-04-01 early return 시 기존 state 유지 — 잘못된 부분 상태로 교체 방지.
- P24 (단순성): 신규 추상화 없음, try/catch 1뎁스 추가.
- P20 (폴백 금지): 모든 catch에 `console.error` 명시 로깅 (silent pass 아님).

**영향 범위**: 프론트엔드 3개 파일만 수정. 백엔드/DB/테스트 영향 없음. 정상 경로 동작 변화 없음 — 예외 발생 시에만 로그 출력 + 전파 차단. 롤백 아님 (신규 try/catch 추가만, 규칙 0-3/0-4/0-5 해당 없음).

**검증**:
- `npm run typecheck` (`tsc --noEmit`) — 통과, 오류 0건.
- `npm run build` (`tsc -b && vite build`) — 성공, 76 모듈 변환, 910ms, TypeScript 오류 0건.
- 브라우저 실시간 데이터 흐름 검증: 백엔드 미기동으로 정적 검증만 수행 (코드 경로 유효성 확인).

**커밋**: `bc920df fix(frontend): T2-S7 WS 로그 분류 / store updater / hotStore dispatch 격리 (A1-01-03, A2-04-01/02)`

**핵심 결정**:
- A2-04-01에서 early return 선택 (기존 state 유지): updater 실패 시 부분 갱신으로 인한 데이터 불일치 방지 (P22). listener 루프처럼 continue가 아닌 return인 이유 — updater가 실패하면 nextPartial 자체가 신뢰할 수 없어 변경 감지/상태 교체/리스너 통지 전체를 스킵해야 함.
- A2-04-02에서 dispatchEvent 호출부 보호 선택 (CustomEvent 핸들러 등록부 아님): 호출부 보호가 더 근본적. 핸들러 등록부(A3 영역)는 후속 세션에서 별도 검토.

**다음 세션 대기 사항**:
- **사용자 확정**: 다음 세션은 **T2-S8** (B1-02-02, B1-02-03, B2-03-02 — 엔진 종료 finally / 파이프라인 서브루프 격리). 백엔드 수정 (engine_loop.py, pipeline_compute.py). 선행 의존성: T1-S2, T1-S3 필수 (같은 파일 — 충돌 방지 위해 선행 세션 완료 후 진행) — 둘 다 완료됨.
- **Tier 2 진행 상태**: T2-S7 완료. 잔존 T2-S8~T2-S11 (4세션). MEDIUM 14건 중 3건 완료, 11건 잔존.

---

### T1-S5 `_save_confirmed_cache` DB 실패 시 False 반환 — 완료 (2026-07-23) — B3-05-01 완료 (Tier 1 마지막)

**세션**: 단일 세션. 백엔드 코드 수정 (backend-fix + problem-solve 스킬). 세션 라벨 T1-S5 (사용자 지정 라벨 — `p25_fix_tasks.md` 문서상 T1-S4 항목의 내용, 위반 ID B3-05-01 HIGH).

**배경**: P25 수정 계획 Tier 1 마지막 세션. `market_close_pipeline.py`의 `_save_confirmed_cache` inner except(645~648)가 rollback+warning 후 fall-through → 650 `return True` 도달. DB 저장 실패를 성공으로 보고하는 silent failure (P20 폴백 금지 / P21 사용자 투명성 / P22 데이터 정합성 위반).

**작업 내용**:
1. **B3-05-01 (HIGH) 완료** — `backend/app/services/market_close_pipeline.py` 648줄: inner except에 `return False` 추가 (1줄). DB 저장 실패 시 False 반환, 정상 시에만 650 `return True` 도달. outer except(651~653)의 `return False` 패턴과 일관 (P23).
2. **테스트 정정** — `backend/tests/test_market_close_pipeline.py` 725~737줄: `test_db_exception_returns_true_with_warning` → `test_db_exception_returns_false_with_warning`로 테스트명/주석/`assert result is False` 정정. 기존 테스트가 잘못된 동작(True 반환)을 명시적으로 검증하던 것을 올바른 동작(False 반환) 검증으로 수정.

**수정 파일**: 2개.
- `backend/app/services/market_close_pipeline.py` (+1줄)
- `backend/tests/test_market_close_pipeline.py` (8줄 변경 — 테스트명/주석/assert)

**아키텍처 원칙 부합**:
- P20 (폴백 금지): DB 실패를 성공으로 보고하는 silent failure 제거 — 해결.
- P21 (사용자 투명성): False 반환으로 실패 인지 가능 — 강화.
- P22 (데이터 정합성): DB 저장 실패 시 잘못된 성공 전제 차단 — 해결.
- P23 (일관성): outer except의 `return False` 패턴과 동일하게 정렬.
- P24 (단순성): `return False` 1줄 추가, 복잡도 증가 없음.

**영향 범위**: 현재 호출자 `_run_post_confirmed_pipeline`(510~520)이 반환값 무시(`await`만 하고 결과 사용 안 함) → 직접 동작 변화 없음. 향후 반환값 사용 시 올바른 계약 보장. 프론트엔드/DB 스키마 영향 없음.

**검증**:
- `py_compile` 통과.
- `pytest backend/tests/test_market_close_pipeline.py -v --timeout=15` — 57 passed (0.77s), 0 failed.
- `python -W error::RuntimeWarning main.py` 기동 — RuntimeWarning/Traceback/Error 0건. 30초 정상 구독·수신율 갱신 동작 확인.
- 잔존 프로세스 0건 확인.

**커밋**: `06cd751 fix(backend): T1-S5 _save_confirmed_cache DB 실패 시 False 반환 (B3-05-01)`

**도중 발견 문제**:
- HANDOVER.md 갱신 중 실수로 기존 HANDOVER.md(1961줄)를 82줄로 덮어쓰는 사고 발생 (규칙 0-3 승인 없는 롤백 위반). 즉시 `git show HEAD~1:HANDOVER.md`로 복구 후 본 섹션 추가 형태로 갱신. 사용자에게 보고 예정.

**핵심 결정**:
- 반환값 변경이나 현재 호출자가 반환값 무시하므로 직접 동작 변화 없음 — 계약 정정 자체가 의미 (P16 살아있는 경로: dead code 아님, 향후 사용 시 올바른 계약).
- 롤백 아님 (버그 수정 — 잘못된 반환값 정정). 규칙 0-3/0-4/0-5 해당 없음.

**Tier 1 전체 완료**: T1-S1~T1-S6 (문서상 라벨) = 사용자 라벨 T1-S1~T1-S5. CRITICAL 2건 + HIGH 8건 = 10건 전부 완료. 다음은 Tier 2 (MEDIUM 14건 / 5세션).

---

### T1-S4 엔진 루프 / 기동 캐시 격리 — 완료 (2026-07-23) — B1-02-01/04 완료

**세션**: 단일 세션. 백엔드 코드 수정 (backend-fix 스킬). 세션 라벨 T1-S4 (사용자 지정 라벨 — `p25_fix_tasks.md` 문서상 T1-S2 항목의 내용, 위반 ID B1-02-01 HIGH + B1-02-04 HIGH).

**배경**: P25 수정 계획 Tier 1 세션. `engine_loop.py`의 (1) WS 구간 감지 while 루프 본문이 무보호 상태로 `is_ws_subscribe_window` 호출이 throw 시 엔진 루프 전체 종료되는 P25 위반, (2) `_cache_and_bootstrap`에서 `_load_caches_preboot`가 무보호로 throw 시 `engine-ready` 브로드캐스트 스킵 → 프론트엔드 hang → P21 위반 해결.

**작업 내용**:
1. **B1-02-01 (HIGH) 완료** — `backend/app/services/engine_loop.py` `run_engine_loop` while 루프 (306-351줄): while 본문(303~341줄)을 `try/except`로 감싸고 `except asyncio.CancelledError: break` + `except Exception as e: logger.error("[연산] WS 구간 감지 루프 오류 (계속): %s", e, exc_info=True)` + `await asyncio.sleep(1)` (hot-spin 방지) 추가. 이벤트 대기(353줄 `asyncio.wait`)는 try 밖 유지. `is_ws_subscribe_window` throw 시 루프 종료 아닌 error 로그 + 1초 대기 후 continue.
2. **B1-02-04 (HIGH) 완료** — `backend/app/services/engine_loop.py` `_cache_and_bootstrap` (22-43줄): `_load_caches_preboot`를 `try/except`로 감싸고 실패 시 `logger.error("[연산] 캐시 선행 로드 치명 오류 — 감소 모드로 기동", exc_info=True)` + 계속 진행. `engine-ready` 브로드캐스트는 캐시 로드 성공/실패 무관 항상 실행되도록 분리 (P21 사용자 투명성 — 프론트엔드 hang 방지).

**수정 파일**: 2개.
- `backend/app/services/engine_loop.py` (+22/-18, while 루프 격리 + _cache_and_bootstrap 격리)
- `backend/tests/test_engine_loop.py` (+54/-14, 테스트 2건 추가)

**테스트 추가**:
- `test_load_caches_preboot_exception_still_broadcasts`: `_load_caches_preboot` throw 시 `engine-ready` 브로드캐스트 여전히 실행 확인 (B1-02-04, P21).
- `test_ws_loop_isolates_subscribe_window_exception`: `is_ws_subscribe_window` throw 시 루프 종료 아닌 `logger.error` + continue 확인 (B1-02-01, P25).

**아키텍처 원칙 부합**:
- P25 (격리된 실패): `is_ws_subscribe_window` 단일 호출 실패가 엔진 루프 전체 중단하지 않고 continue → 엔진 유지 — 해결. `_load_caches_preboot` 실패 시에도 `engine-ready` 브로드캐스트 보장 → 프론트엔드 hang 방지 — 해결.
- P21 (사용자 투명성): 캐시 로드 실패 시에도 프론트엔드에 엔진 준비 상태 전송 → 사용자가 상태 인지 — 강화.
- P23 (일관성): while 루프 격리 패턴은 T1-S3에서 적용한 `_phase2_batch_recompute_loop` (`pipeline_compute.py:646-675`)와 동일 — `except asyncio.CancelledError: break` + `except Exception: logger.error(..., exc_info=True)`.
- P20 (폴백 금지): `logger.error(..., exc_info=True)` 명시 로깅 (silent pass 금지) — 준수.
- P16 (살아있는 경로): call-site try/except는 내부 except와 중복 우려 있으나, `engine-ready` 브로드캐스트 보장(P21)이라는 실제 효과로 비-dead-code.
- P24 (단순성): `_cache_and_bootstrap` 18줄 → 25줄 내외, while 루프는 기존 구조 유지 + try/except 1뎁스 추가. 신규 추상화 없음.

**검증**:
- `py_compile` 통과.
- `pytest backend/tests/test_engine_loop.py -v --timeout=15` — 40 passed (기존 38 + 신규 2), 0 failed.
- `python -W error::RuntimeWarning main.py` 기동 — RuntimeWarning/Traceback/Error 0건. WS 연결 완료, 수신율 100% 도달, 모든 구독 정상 (기동 후 30초).
- 잔존 프로세스 0건 확인.

**도중 발견 및 수정**:
- `core_queues` 모듈명을 `core_queue`로 오타 입력(제가 도입). 런타임 기동 시 `ModuleNotFoundError: No module named 'backend.app.services.core_queue'` 발견, 즉시 `core_queues`로 수정. 최종 기동에서 정상 동작 확인.

**핵심 결정**:
- B1-02-01에서 `logger.warning`이 아닌 `logger.error` 사용: 태스크 파일 수정 방향은 `logger.warning`이었으나, 엔진 루프 전체 종료 위험이므로 치명 오류 등급(`error`) 적용. T1-S3의 `_phase2_batch_recompute_loop` 패턴(`logger.error`)과 일관성 유지 (P23).
- B1-02-04에서 감소 모드 기동 선택 (기동 중단 아님): 캐시 로드 실패 시에도 엔진은 계속 기동하되 `engine-ready` 브로드캐스트로 프론트엔드에 상태 전송. 기동 중단은 T2-S9(B4-06-03)에서 별도 검토.

**다음 세션 대기 사항**:
- **사용자 확정**: 다음 세션은 **T1-S5 (B3-05-01 DB 저장 실패 처리, market_close_pipeline.py)**. 사용자가 "T1-S5" 라벨을 사용하되 내용은 B3-05-01로 진행하라고 지시.
- **태스크 라벨 메모**: `p25_fix_tasks.md`에서 B3-05-01은 문서상 **T1-S4** 항목(95-110줄)이고, 문서상 **T1-S5**는 A3-07-01/02(이미 완료) 항목임. 사용자가 "T1-S5" 라벨을 B3-05-01 작업에 부여했으므로, 다음 세션은 문서상 T1-S4 항목의 내용(B3-05-01)을 "T1-S5" 세션 라벨로 진행.
- **Tier 1 잔존**: B3-05-01 (market_close_pipeline.py, 다음 세션)만 남음. 사용자가 "Tier 1 마지막"으로 확인. 세션당 1단계 원칙(규칙 0-1) 준수.

---

### T1-S3 업종 점수 재계산 루프 격리 — 완료 (2026-07-23) — B2-03-01/02 완료

**세션**: 단일 세션. 백엔드 코드 수정 (backend-fix 스킬). 세션 라벨 T1-S3 (`p25_fix_tasks.md`의 T1-S3 항목, 위반 ID B2-03-01 HIGH + B2-03-02 MEDIUM).

**배경**: P25 수정 계획 Tier 1 세션. `pipeline_compute.py`의 업종 점수 재계산 백그라운드 루프가 예외 발생 시 루프 전체 즉시 종료되어 업종 점수 화면 갱신이 영구 중단되는 P25 위반 해결. B2-03-02는 T2-S8에 포함되어 있었으나 동일 파일 인접 함수라 본 세션에서 선제 처리.

**작업 내용**:
1. **B2-03-01 (HIGH) 완료** — `backend/app/pipelines/pipeline_compute.py` `_phase2_batch_recompute_loop` (638-675줄): while 루프 본문을 try로 감싸고 `except asyncio.CancelledError: break` + `except Exception as e: logger.error("[연산] Phase2 재계산 루프 오류 (계속): %s", e, exc_info=True)` 추가. `await asyncio.sleep(0.2)`는 try 밖 유지 (sleep 취소 시 정상 종료). 0.2초 주기 재계산 중 한 단계 예외 발생해도 루프가 멈추지 않고 다음 주기 계속 실행.
2. **B2-03-02 (MEDIUM) 완료** — `backend/app/pipelines/pipeline_compute.py` `_sector_recompute_loop_impl` (678-692줄): 기존 `except asyncio.CancelledError` 외에 `except Exception as e: logger.error("[연산] 업종 점수 재계산 루프 치명 오류: %s", e, exc_info=True)` 추가. Phase 1/Phase 2 어느 단계 치명 오류 발생 시 로깅 후 종료 (무한 재시도 위험 방지, P24 단순성).

**수정 파일**: 1개 (+9/-3줄).
- `backend/app/pipelines/pipeline_compute.py` (+9/-3)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 0.2초 재계산 루프에서 단일 예외 시 해당 주기만 건너뛰고 루프 유지 → 업종 점수 화면 갱신 지속 — 해결.
- P23 (일관성): `_compute_loop_impl` (285-319줄)의 `try/while/try/except CancelledError:break/except Exception:logger.error` 패턴과 동일 구조 — 준수.
- P20 (폴백 금지): `logger.error(..., exc_info=True)` 명시 로깅 (silent pass 금지) — 준수.
- P21 (사용자 투명성): 예외 발생 시 로그로 사용자/로그에서 원인 파악 가능 — 준수.
- P16 (살아있는 경로): 예외 후 루프 계속 실행 → 경로 유지 — 준수.
- P24 (단순성): 기존 패턴 복제, 신규 추상화 없음 — 준수.

**검증**:
- `py_compile` 통과.
- `pytest backend/tests/test_pipeline_compute.py -v --timeout=15` — 93개 테스트 전부 통과 (0.21s).
- `python -W error::RuntimeWarning main.py` 기동 — RuntimeWarning/Traceback/Error 0건. Phase 1 임계값 대기 → 95.8%/100% 통과 → Phase 2 진입 정상 동작 확인 (기동 후 23초).
- 잔존 프로세스 0건 확인.

**핵심 결정**:
- `_sector_recompute_loop_impl`의 `except Exception`에서 재시도 없이 종료: 무한 재시도 위험 방지 (P24 단순성). done_callback의 `t.exception()` 로깅과 중복되지 않음 (except에서 잡으면 exception 전파 안 됨).
- B2-03-02 선제 처리: T2-S8 태스크에 포함되어 있었으나 동일 파일 인접 함수라 본 세션에서 함께 처리. T2-S8 진행 시 engine_loop.py만 남음 (B1-02-02/03).

**다음 세션 대기 사항**:
- **사용자 확정**: 다음 세션은 **T1-S4 (B1-02-01/04 엔진 루프 격리, engine_loop.py)**. 사용자가 명시적으로 "T1-S4" 라벨을 사용하되 내용은 B1-02-01/04 engine_loop.py로 진행하라고 지시.
- **태스크 라벨 메모**: `p25_fix_tasks.md`에서 B1-02-01/04는 문서상 **T1-S2** 항목(57-72줄)이고, 문서상 **T1-S4**는 B3-05-01(market_close_pipeline.py) 항목(89-104줄)임. 사용자가 "T1-S4" 라벨을 B1-02-01/04 작업에 부여했으므로, 다음 세션은 문서상 T1-S2 항목의 내용(B1-02-01/04)을 "T1-S4" 세션 라벨로 진행. 문서상 T1-S4(B3-05-01)는 후속 세션으로 이월.
- Tier 1 잔존: B1-02-01/04 (engine_loop.py, 다음 세션), B3-05-01 (market_close_pipeline.py, 후속). 세션당 1단계 원칙(규칙 0-1) 준수.

---

### T1-S6 헤더 칩 순차 갱신 격리 — 완료 (2026-07-23) — A3-07-04 완료

**세션**: 단일 세션. 프론트엔드 코드 수정 (frontend-fix 스킬). 세션 라벨 T1-S6 (`p25_fix_tasks.md`의 T1-S6 항목, 위반 ID A3-07-04).

**배경**: P25 수정 계획 Tier 1 세션. `header.ts`의 `onStateChange` 콜백이 15개 헤더 칩을 순차 갱신하는데 칩 간 격리가 없어, 한 칩 렌더링 throw 시 이후 모든 칩이 미갱신되는 P25 위반 (F-02 잔존 위험). `store.ts` listener 루프(40-46줄)가 "리스너 간" 격리는 보장하나 "콜백 내부 칩 간" 격리는 없었음. 사용자가 자동매수/자동매도/텔레그램 활성화 여부를 헤더에서 오인할 수 있는 P21 위반 잔존.

**작업 내용**:
1. **A3-07-04 (HIGH) 완료** — `frontend/src/layout/header.ts` `onStateChange` (368-494줄): 13개 칩 갱신 블록을 per-chip try/catch로 감쌈. 각 catch 블록은 `console.error('[header] <칩명> chip error', e)` 로깅 (silent pass 금지, P20 준수). catch 블록에서 칩 내용/style 폴백 덮지 않음 (기존 상태 유지).
   - 적용 칩: circuitBreaker, orderTimeBlocked, riskBlock, krx phase, nxt phase, index(코스피/코스닥), krxAlert, bootstrap, avgAmt, mode, settings(autoTrade/autoBuy/autoSell/tele).
2. **증권사 칩 루프 per-broker 격리** — `onStateChange` 내 증권사 칩 루프(485-493줄): 루프 내 각 brokerId 반복을 개별 try/catch로 감싸 한 증권사 칩 실패 시 다른 증권사 칩 계속 갱신. catch 로깅에 brokerId 포함.

**수정 파일**: 1개 (+125/-97줄).
- `frontend/src/layout/header.ts` (+125/-97)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 한 칩 렌더링 throw 시 해당 칩만 미갱신 + 로깅, 나머지 칩 계속 갱신 — 해결. F-02 잔존 위험 완결.
- P20 (폴백 금지): `console.error` 명시 로깅 (silent pass 금지) — 준수. catch 블록에서 빈 문자열/None 폴백 덮지 않음 — 준수.
- P21 (사용자 투명성): 한 칩 실패 시 다른 칩(자동매수/매도/텔레그램 등) 정상 갱신 → 사용자가 활성화 여부 정확히 인지 — 강화.
- P23 (일관성): 기존 `data-table.ts:108-115`, `virtual-scroller.ts:304-307, 315-322`의 P25 격리 패턴과 동일 구조 (`// P25: ... 격리 — ... throw 시 ... + 로깅, 다음 ... 계속` 주석 + `console.error('[header] ... error', e)`) — 준수.
- P24 (단순성): per-chip try/catch 1뎁스만 추가, 헬퍼 함수/추상화 도입 없음 — 준수.

**검증**:
- `npm run typecheck` (`tsc --noEmit`) 통과.
- `npm run build` (`tsc -b && vite build`) 통과 — 76 모듈 변환, 1.95s, 번들 정상 생성.
- lint 스크립트는 package.json에 없음 → typecheck + build로 대체.
- 브라우저 확인: 사용자 직접 확인 필요 (헤더 칩 정상 표시). 수정은 실패 전파 차단만 추가한 것이므로 정상 경로 동작은 변경되지 않음. dev 서버 5173 포트 실행 중.
- 잔존 프로세스 0건 확인.

**핵심 결정**:
- 칩 그룹화: 설정 상태 4칩(autoTrade/autoBuy/autoSell/tele)은 단일 settings 블록 내에서 함께 갱신되므로 1개 try/catch로 통합 감쌈 (P24 단순성 — 4칩을 4개 try/catch로 분리하면 과도한 중첩).
- 업종지수 2칩(코스피/코스닥)도 단일 블록에서 `display` 설정 후 `applyIndexChip` 2회 호출하므로 1개 try/catch로 통합 감쌈.
- catch 블록에서 칩 내용/style 초기화하지 않음: throw 시점에 칩이 어느 상태였는지 알 수 없으므로 폴백 덮지 않고 기존 표시 유지 (P20 준수). 사용자는 콘솔 에러 로그로 원인 파악.

**다음 세션 대기 사항**: `p25_fix_tasks.md` 순서상 T1-S3 (B2-03-01 pipeline_compute.py Phase2 recompute 루프 격리, 백엔드) 또는 T1-S4 (B3-05-01 market_close_pipeline.py, 백엔드). Tier 1 잔존: T1-S3, T1-S4. 세션당 1단계 원칙(규칙 0-1) 준수.

---

### T1-S2 DataTable 행 렌더링 격리 — 완료 (2026-07-23) — A3-07-01/02/03 완료

**세션**: 단일 세션. 프론트엔드 코드 수정 (frontend-fix 스킬). 세션 라벨 T1-S2 (문서상 T1-S5와 동일 — `p25_fix_tasks.md`의 T1-S5 항목).

**배경**: P25 수정 계획 Tier 1 세션. 가상 스크롤 / 고정 테이블 / 컬럼 너비 샘플링 루프에서 한 행/셀 렌더링 throw 시 전체 테이블 렌더링 루프 중단되는 P25 위반 해결. 사용자 추가 지시로 A3-07-03(extractSamples)도 본 세션에 포함.

**작업 내용**:
1. **A3-07-01 (HIGH) 완료** — `frontend/src/components/virtual-scroller.ts` `renderRange` 루프 (293-325줄): per-row try/catch. existing 경로는 throw 시 기존 내용 유지 + 로깅, new 경로는 throw 시 `releaseRow(el)` 풀 반환 + activeRows 미등록 → 해당 행 공백.
2. **A3-07-02 (HIGH) 완료** — `frontend/src/components/common/data-table-fixed.ts` 3곳: (a) keyFn 경로 신규 키 추가 루프(229-240), (b) 인덱스 경로 신규 행 생성(308-323) — throw 시 placeholder tr 추가로 인덱스 정렬 유지, (c) 타입변경 교체(328-336) — throw 시 기존 rowEl 유지.
3. **A3-07-03 (MEDIUM) 완료** — `frontend/src/components/common/data-table.ts` `extractSamples` (99-119줄): per-cell try/catch. throw 시 빈 문자열 push(기본 너비 사용) + 로깅.

**수정 파일**: 3개 (+47/-16줄).
- `frontend/src/components/virtual-scroller.ts` (+17/-7)
- `frontend/src/components/common/data-table-fixed.ts` (+36/-12)
- `frontend/src/components/common/data-table.ts` (+10/-4)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 한 행/셀 렌더링 throw 시 해당 행만 스킵/공백, 나머지 계속 — 해결.
- P20 (폴백 금지): `console.error` 로깅 (silent pass 금지) — 준수. extractSamples 빈 문자열은 오류 경로의 안전 기본값(명시된 예외 경로)으로 P20 위반 아님.
- P23 (일관성): 3개 파일 동일 `console.error('[DataTable/VirtualScroller] ... render error', e)` 패턴, 기존 cell 단위 격리 5곳과 동일 구조 — 준수.
- P21 (사용자 투명성): 행 단위 실패 시 콘솔 로깅으로 원인 추적 가능 — 준수.
- P24 (단순성): per-row try/catch 1뎁스만 추가, 구조 변경 없음 — 준수.

**검증**:
- `npm run typecheck` (`tsc --noEmit`) 통과.
- `npm run build` (`tsc -b && vite build`) 통과 — 76 모듈 변환, 2.06s, 번들 정상 생성.
- lint 스크립트는 package.json에 없음 → typecheck + build로 대체.
- 브라우저 확인: 사용자 직접 확인 필요 (업종 순위 테이블, 매수 후보 테이블 정상 렌더링). 수정은 실패 전파 차단만 추가한 것이므로 정상 경로 동작은 변경되지 않음.
- 잔존 프로세스 0건 확인.

**핵심 결정**:
- 인덱스 경로(305-323) placeholder 방식: 인덱스 기반 갱신 루프에서 `rowCaches[i]` 인덱스 정렬이 필수이므로, throw 시 빈 tr placeholder를 push하여 인덱스 정렬 유지. placeholder는 `display: none`으로 화면에 보이지 않음.
- 타입변경 교체 경로(328-336): throw 시 `tbody.replaceChild` 미수행 → 기존 rowEl 유지. 타입 불일치 상태로 표시될 수 있으나 테이블 전체 중단보다 안전.
- virtual-scroller.ts의 다른 renderRow 호출부(updateItems 444/451, updateItemByKey 468, updateItem 499)는 계획에 명시된 범위(renderRange 293-316)가 아니므로 본 세션에서 미수정 — 미해결 문제로 기록.

**다음 세션 대기 사항**: T1-S3 (사용자 지시 시 결정) 또는 `p25_fix_tasks.md` 순서상 T1-S6 (A3-07-04 헤더 칩 순차 갱신 격리). 세션당 1단계 원칙(규칙 0-1) 준수.

---

### T1-S1 WS 디스패치 핸들러 격리 — 부분 완료 (2026-07-23) — A1-01-01/02 완료, A1-01-04 이관

**세션**: 단일 세션. 프론트엔드 코드 수정 (frontend-fix + problem-solve 스킬 연계).

**배경**: P25 수정 계획 Tier 1 최우선 세션. WS 디스패치 격리는 모든 프론트엔드 격리의 근원 — 한 핸들러/한 이벤트 실패가 같은 프레임의 다른 핸들러·다른 이벤트까지 블로킹하는 P25 위반 해결.

**작업 내용**:
1. **A1-01-01 (CRITICAL) 완료** — `frontend/src/api/ws.ts` `_dispatchMessage` (196-205줄): `forEach` → `for` 루프 + per-handler try/catch. 한 핸들러 throw 시 `console.error('[WS] 핸들러 실행 실패 (event=...)', err)` 로깅 후 같은 이벤트의 다른 핸들러 계속 실행.
2. **A1-01-02 (CRITICAL) 완료** — `frontend/src/api/ws.ts` `_handleBinaryFrame` (167-174줄): 바이너리 프레임 다중 이벤트 per-item try/catch. 디코딩 try(바깥)와 디스패치 try(안쪽) 분리 — 한 이벤트 디스패치 실패 시 같은 프레임의 다음 이벤트 계속 처리.
3. **A1-01-04 (HIGH) 미진행** — 사용자 지시로 `binding.ts` 변경 없음. 핸들러 본문 try/catch는 후속 세션에서 별도 승인 시 진행. 단, A1-01-01 per-handler 격리가 디스패처 단에서 1차 보호하므로 기능적 안전성은 이미 확보. A1-01-04는 2차 방어(핸들러 본문 내부 예외 세분화) 성격.

**수정 파일**: `frontend/src/api/ws.ts` (1개, +15/-3줄). `binding.ts` 변경 없음.

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 한 핸들러/한 이벤트 실패가 전파되지 않음 — 해결.
- P20 (폴백 금지): `console.error` 로깅 (silent pass 금지) — 준수.
- P23 (일관성): 기존 `console.error('[WS] ...')` 패턴 5곳과 동일 구조 유지 — 준수.
- P24 (단순성): 각 격리는 try/catch 1뎁스, 과도한 추상화 없음 — 준수.
- P16 (살아있는 경로): `_dispatchMessage`/`_handleBinaryFrame`은 실제 WS onmessage 경로에 연결 — 준수.

**검증**:
- `npm run typecheck` (`tsc --noEmit`) 통과.
- `npm run build` (`tsc -b && vite build`) 통과 — 76 모듈 변환, 1.91s, 번들 정상 생성.
- lint 스크립트는 package.json에 없음 → typecheck + build로 대체.
- 브라우저 실시간 데이터 흐름: 백엔드 미실행 상태라 미검증. 단, 수정은 실패 전파 차단만 추가한 것이므로 정상 경로 동작은 변경되지 않음. 백엔드 기동 후 WS 데이터 정상 수신 여부는 후속 확인 권장.
- 잔존 프로세스 0건 확인.

**핵심 결정**:
- 격리 책임을 디스패처(ws.ts)에 중앙 집중 — 각 핸들러마다 try/catch 중복 작성 방지 (P24 단순성, P23 일관성).
- A1-01-04는 T2-S7(A1-01-03, A2-04-01/02 — ws.ts/store.ts/hotStore.ts)와 동일 파일군이므로 T2-S7 진행 시 통합 처리 가능. 단, A1-01-04는 binding.ts 핸들러 본문이므로 T2-S7 범위에 명시적 포함 필요.

**다음 세션 대기 사항**: T1-S2 (A3-07-01/02 DataTable 행 렌더링 격리) 진행 예정 (사용자 지시). `frontend/src/components/virtual-scroller.ts`, `frontend/src/components/common/data-table-fixed.ts` 수정. T1-S1 완료 권장 의존성 충족(부분 완료이나 디스패처 단 1차 보호 확보로 T1-S5 진행에 기능적 안전). 세션당 1단계 원칙(규칙 0-1) 준수.

---

### P25 수정 계획·태스크 체크리스트 작성 (2026-07-23) — 설계 문서 2건 완성, 코드 수정 없음

**세션**: 단일 세션. 설계 문서 작성만 수행 (코드 수정 없음, 규칙 0 준수).

**배경**: P25 전수 조사 9/9 세션 완료 후, 식별된 위반 40건의 수정 계획서(`p25_fix_plan.md`)와 세션별 실행 태스크 체크리스트(`p25_fix_tasks.md`) 작성.

**작업 내용**:
1. **`docs/p25_fix_plan.md`** (수정 계획서): 40건 위반을 Tier 1(CRITICAL+HIGH 10건) / Tier 2(MEDIUM 14건) / Tier 3(LOW 16건) 분류. 의존성 그래프, 세션당 1단계 원칙 기반 17세션 일정, 검증 기준, 리스크, 승인 요청 항목 명시.
2. **`docs/p25_fix_tasks.md`** (실행용 태스크 체크리스트): 17세션별 체크리스트 (T1-S1 ~ T3-S16). 각 세션별 대상 위반 ID, 수정 파일, 검증 방법, 의존성(필수/권장 구분), safe-trade 스킬 필요 여부 명시. 공통 사전/완료 점검 항목 포함.

**핵심 설계 결정**:
- 세션 분할: T3-S12를 프론트(T3-S12a)/백엔드(T3-S12b) 분리 시 17세션 (통합 시 16세션)
- safe-trade 스킬 필수 세션: T2-S11 (fake_fill_event 정합성), T3-S16 (trading.py 매매 로직, 규칙 0-4 핵심 로직 변경 승인 포함)
- A3-07-10 (87개 addEventListener) 별도 하위 계획 필요: T3-S15 세션 내에서 `docs/p25_fix_a3_07_10_subplan.md` 작성 후 사용자 승인 (P24 단순성 vs P25 격리 범위 균형)
- 의존성: T1-S1(WS 디스패치 격리)이 모든 프론트엔드 격리의 기반 — Tier 1 최우선

**검증**: 설계 문서 작성만 수행 — typecheck/build/런타임 기동 불필요. 잔존 프로세스 0건.

**다음 세션 대기 사항**: T1-S1 (A1-01-01 WS 디스패치 핸들러 격리, CRITICAL) 시작 예정. 모든 프론트엔드 격리의 근원이므로 최우선. 사용자 명시적 승인(실행 지시어) 수신 후 `frontend/src/api/ws.ts`, `frontend/src/binding.ts` 수정 착수. 세션당 1단계 원칙(규칙 0-1) 준수 — T1-S1 완료 시 검증 → 커밋 → HANDOVER 갱신 → 보고 후 종료.

---

### P25 전수 조사 세션 9: 교차 점검·총합 보고 완료 (2026-07-23) — P25 전수 조사 9/9 세션 완료

**세션**: 단일 세션. 조사만 수행 (코드 수정 없음). 마지막 세션.

**배경**: P25 전수 조사 9세션 중 세션 9 (교차 점검·총합 보고). 세션 1~8 위반 40건 취합 + P25 × P7/P9/P16/P20/P23 교차 원칙 매트릭스 + 우선수정 추천 + 세션 8 이월 B5-08-03 기동 시 대조 메커니즘 확인.

**조사 항목 결과**:

1. **위반 40건 취합**: 세션 1~8 식별 위반 전수 취합. 등급별 분포: CRITICAL 2건, HIGH 8건, MEDIUM 14건, LOW 16건. 영역별: A1(5), B1(7), B2(5), A2(2), B3(4), B4(3), A3(10), B5(4).

2. **교차 원칙 매트릭스 작성**: P25 × P7/P9/P16/P20/P23 매트릭스 + 원칙별 집계.
   - P25: 32건 (주 원칙)
   - P7: 6건 (고빈도 real-data/틱 경로 블로킹)
   - P9: **0건** (파이프라인 간 독립성은 구조적 분리로 유지, P25와 교차 위반 없음)
   - P16: 3건 (핸들러 본문/updater/캐시 로드 보호 부재)
   - P20: 5건 (silent pass/빈 폴백)
   - P23: 11건 (최다 — 격리 패턴 혼용, exc_info 누락)
   - 기타: P21 11건, P22 3건, P18 1건

3. **우선수정 추천**: Tier 1(10건, 즉시 수정 권장), Tier 2(14건, 단계적 수정), Tier 3(16건, 일관성 정비). 영향도 순 정렬. 거래 로직 수정 시 safe-trade 스킬 필수 표기.

4. **B5-08-03 기동 시 대조 메커니즘 조사 (세션 8 이월)**: **메커니즘 부재 확정**.
   - `settlement_engine.load_state()` (settlement_engine.py:191-258): SQLite KV 스토어에서 orderable 그대로 로드만, trade_history 대조 없음
   - `dry_run._refresh_positions_if_dirty()` (dry_run.py:36-65): trade_history에서 포지션만 재구축, 잔고 대조 없음
   - `trade_history.py`: orderable/cash 재계산 함수 부재
   - `engine_lifecycle.start_engine()` (engine_lifecycle.py:22-45): 기동 시 잔고 대조 로직 없음
   - `tests/test_settlement_verification.py` S4-1 (207-254): 정합성 위반 재현만, 복구 메커니즘 부재
   - **결론**: fake_fill_event 태스크 실패 시 trade_history와 settlement_engine orderable 불일치가 영속화 (재시작으로 복구 불가). 수정 방향: 기동 시 대조 메커니즘 신설 권장 (trade_history에서 expected orderable 재계산 → 대조 → 불일치 시 차단+로깅).

**핵심 발견**:
- P9 위반 0건 — 파이프라인 독립성은 P25와 직접 교차하지 않는 독립 축
- P23 × P25 교차 11건으로 최다 — 일관성 위반은 즉시 중단 아닌 점진적 부채 축적 패턴
- B5-08-03 기동 시 대조 메커니즘 부재 — 가장 심각한 정합성 위험 (MEDIUM 등급이나 영속화 특성)
- A1-01-01/02 (CRITICAL) WS 디스패치 격리는 다수 하위 위반의 상위 보호 계층 — 선수정 시 하위 영향도 감소

**수정 방향 (참고용, 승인 시 별도 세션)**:
- Tier 1: A1-01-01/02 (WS 디스패치), A3-07-01/02/04 (행/칩 격리), B2-03-01 (Phase 2 루프), B1-02-01/04 (엔진 루프), B3-05-01 (DB 저장 False 반환), A1-01-04 (핸들러 본문)
- Tier 2: B5-08-03 (기동 시 대조 메커니즘 신설 — safe-trade 필수), A2-04-01/02 (Store 격리), B1-02-02/03 (finally 정리), B2-03-02, B3-05-02, B4-06-01/03, A3-07-03/05/06/07, A1-01-03
- Tier 3: 일관성 정비 16건 (create_task 통일, exc_info 보완, silent pass 로깅 등)

**검증**: 조사만 수행 — typecheck/build/런타임 기동 불필요. 잔존 프로세스 0건.

**다음 세션 대기 사항**: P25 전수 조사 9/9 세션 완료. 수정은 별도 승인 세션에서 진행. 우선수정 추천 Tier 1부터 사용자 승인 시 순차 진행. 각 수정 세션은 AGENTS.md 섹션3 규칙 0-1(세션당 1단계) 준수. 거래 로직 수정(B5-08-03, B5-08-02, B5-08-04) 시 safe-trade 스킬 필수 + 사용자 승인 필수. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 11 + 변경 이력에 결과 누적 완료.

---

### P25 전수 조사 세션 8: B5 매매·테스트모드 태스크 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사만 수행 (코드 수정 없음). safe-trade 스킬 연계. HANDOVER 미해결 문제 4건 기록.

**배경**: P25 전수 조사 9세션 중 세션 8. B5 매매·테스트모드 영역 조사. 우선순위 8위 — 백엔드 매매 실행 경로(`trading.py`, `buy_order_executor.py`, `dry_run.py`). dry_run 태스크 격리, 매매 경로 실패 전파, P15(단일 주문 경로)/P18(테스트모드 동등성) 교차 점검.

**조사 파일**: 3개 (`trading.py` 859줄, `buy_order_executor.py` 234줄, `dry_run.py` 333줄)

**조사 항목 결과**:

1. **P15 단일 주문 경로**: ✅ 준수. `execute_buy`/`execute_sell` 단일 경로. 분기/우회 없음. `buy_order_executor.evaluate_buy_candidates`도 동일 경로 호출.

2. **P18 테스트모드 동등성**: 대체 준수, 1건 미세 위반 (B5-08-02). RiskManager 게이트, 등락률/체결강도 가드, 재매수 차단, 시간대 차단, 한도 체크 모두 테스트/실전 공통. 모드 분기는 돈 I/O 최소 지점에 한정. 단 `execute_sell` 평균매입가 조회(trading.py:572-598)가 모드 분기됨 — 돈 I/O 아닌 "조회" 분기로 P18 엄격 해석상 미세 위반.

3. **P25 격리된 실패 / dry_run 태스크 격리**: 2건 이슈.
   - B5-08-01 (LOW/P23): trading.py:477-482, 666-671 `asyncio.create_task` 직접 사용 + add_done_callback 수동 연결. `schedule_engine_task()` 미사용 → ARCHITECTURE.md 금지 패턴 2 위반. 기능적 동등.
   - B5-08-03 (MEDIUM/P22): `fake_fill_event` 태스크 실패 시 trade_history와 Settlement Engine 잔고 불일치 가능. 단 `tests/test_settlement_verification.py` S4-1에 재현 테스트 존재 → 인지된 영역. 기동 시 대조 메커니즘 보유 여부는 세션 9 교차 점검 대상.

4. **매매 경로 실패 전파**: ✅ 양호. 매수 실패 시 사전 차감 롤백 + RiskManager 실패 보고 + 서킷브레이커 OPEN 시 마스터 스위치 강제 OFF + WS 브로드캐스트. 매도 실패 시 `_recent_sells` 해제 + 동일 RiskManager 처리. buy_order_executor 예외 시 `break` 안전 종료 + `logger.warning(exc_info=True)` (silent pass 아님).

5. **기타 발견 (B5-08-04, LOW)**: trading.py:204-210 실시간 지연 체크 실패 시 매수 차단 아닌 통과 (게이트 우회 형태). P20/P25 관점에서 fail-closed가 더 보수적.

**식별 위반 4건** (미해결 문제에 기록):
- **B5-08-01 (LOW)**: `trading.py:477-482, 666-671` create_task 직접 사용 → schedule_engine_task 통일 권장 (P23)
- **B5-08-02 (LOW)**: `trading.py:572-598` execute_sell 평균매입가 조회 모드 분기 (P18 미세 위반)
- **B5-08-03 (MEDIUM)**: `trading.py:477-482, 666-671` fake_fill_event 태스크 실패 시 P22 정합성 잠재 위험 (테스트 존재)
- **B5-08-04 (LOW)**: `trading.py:204-210` 실시간 지연 체크 실패 시 매수 통과 (P20/P25 게이트 우회 형태)

**핵심 발견**:
- P15 단일 주문 경로는 완벽 준수. 매수/매도 모두 `execute_buy`/`execute_sell` 단일 경로.
- 매수/매도 실패 전파 처리는 양호 — 사전 차감 롤백, 서킷브레이커 강제 OFF, WS 브로드캐스트로 P20/P21/P22 준수.
- 가장 심각한 항목은 B5-08-03 (MEDIUM) — fake_fill_event 태스크 실패 시 잔고 정합성 잠재 위험. 단 테스트가 존재하므로 인지된 영역.
- B5-08-01은 ARCHITECTURE.md 금지 패턴 2 위반이나 기능적 동등, 심각도 낮음.
- safe-trade 스킬 연계: 조사 시작 시 스킬 호출, 거래 로직 수정 안전 절차 준수. 본 세션은 조사만 수행하여 수정 없음.

**수정 방향 (참고용, 승인 시 별도 세션 — 거래 로직이므로 safe-trade 스킬 필수)**:
- B5-08-01: trading.py:477, 666 create_task → schedule_engine_task로 교체 (add_done_callback 포함). 거래 로직 수정 아님 — 안전장치 배선만 통일.
- B5-08-02: execute_sell 평균매입가 조회를 공통 헬퍼로 추출 (모드 분기 제거). 거래 로직 수정 — safe-trade 스킬 필수, 사용자 승인 필요.
- B5-08-03: fake_fill_event 태스크 실패 시 정합성 복구 메커니즘 점검 (기동 시 대조). 세션 9 교차 점검에서 우선순위 논의.
- B5-08-04: 실시간 지연 체크 실패 시 fail-closed (매수 차단) 전환. 거래 로직 수정 — safe-trade 스킬 필수.

**검증**: 조사만 수행 — typecheck/build/런타임 기동 불필요. 잔존 프로세스 0건.

**다음 세션 대기 사항**: 세션 9 (교차 점검·총합 보고) 진행 — 마지막 세션. 세션 1~8 결과 취합 + 교차 원칙 매트릭스 작성 + 우선수정 추천. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 11에 결과 누적 예정. 세션 9 완료 시 P25 전수 조사 9/9 세션 완료.

---

### P25 전수 조사 세션 7: A3 UI 컴포넌트 렌더링 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사만 수행 (코드 수정 없음). HANDOVER 미해결 문제 10건 기록.

**배경**: P25 전수 조사 9세션 중 세션 7. A3 UI 컴포넌트 렌더링 영역 조사. 우선순위 7위 — 프론트엔드 pages/, components/common/, layout/ 전역. 개별 칩/컴포넌트 렌더링 실패가 전체 화면 중단 유발 여부 (F-02 사례와 동일 패턴).

**조사 파일**: 51개 (pages/ 23, components/common/ 28, layout/ 3) + 참조 2개 (binding.ts, virtual-scroller.ts)

**조사 항목 결과**:

1. **Store 리스너 간 격리**: ✅ 준수. `store.ts:40-46` setState가 각 listener를 try/catch + console.error로 격리 (F-02 fix). 한 페이지 subscribe 콜백이 throw해도 다른 페이지/헤더 리스너는 계속 실행. 단, **리스너 "내부" 부분 실패 시 콜백 내 나머지 작업은 중단** (A3-07-04).

2. **DataTable 셀 렌더링 격리**: ✅ 준수. `data-table-fixed.ts:154-162, 274-290` 및 `data-table-virtual.ts:243-250`에서 각 셀 `c.render()`를 try/catch + console.error로 격리. 개별 셀 실패 시 해당 셀만 빈 상태로 남고 나머지 셀/행은 정상 렌더링.

3. **DataTable 행 렌더링 격리**: ❌ 미준수. `virtual-scroller.ts:293-316` renderRange 루프 내 `renderRow()` 호출(304, 312행)과 `data-table-fixed.ts:230-236` 신규 키 추가 루프 내 `renderDataRow()` 호출(232행)에 try/catch 없음. rowStyle() 또는 행 생성 자체 throw 시 루프 중단 → 가시 영역 전체 공백.

4. **헤더 칩 렌더링 (콜백 내)**: ❌ 미준수. `header.ts:365-494` onStateChange 단일 대형 함수(~130줄, 15개 칩 순차 갱신)에 내부 try/catch 없음. store.ts가 콜백 전체를 보호하므로 다른 리스너는 안전하나, 콜백 내 한 칩 throw 시 이후 칩들 미갱신 → 헤더 일부 칩 멈춤 상태 방치 (P21 위반). F-02 잔존 위험.

5. **페이지 리스트 루프**: ❌ 미준수. profit-overview-sector-pnl(이중 루프), stock-classification(칩/종목 3개 루프), profit-overview-mount(계좌 행), profit-detail-mount(통계 카드) 등 대부분 per-item 격리 없음.

6. **DOM addEventListener 핸들러**: ❌ 미준수. 87개 중 try/catch 보호 사실상 전무. 사용자 구동이라 빈도 낮아 위험 중간~낮음.

7. **Router**: 부분. `notifyRouteChange`(105-109) cb 루프 무보호(LOW). `handleRouteChange`(154-193)는 try/catch + 에러 UI + 재시도 버튼으로 P25 준수.

**식별 위반 10건** (미해결 문제에 기록):
- **A3-07-01 (HIGH)**: `virtual-scroller.ts:293-316` renderRange 루프 내 renderRow 호출 try/catch 없음 → 가시 영역 전체 렌더링 중단
- **A3-07-02 (HIGH)**: `data-table-fixed.ts:230-236` 신규 키 추가 루프 내 renderDataRow 호출 try/catch 없음 → 전체 테이블 렌더링 실패
- **A3-07-03 (MEDIUM)**: `data-table.ts:104-112` extractSamples 루프 무보호 → 테이블 초기화 차단
- **A3-07-04 (HIGH)**: `header.ts:365-494` onStateChange 단일 함수, 15개 칩 간 격리 없음 → 한 칩 실패 시 이후 칩 미갱신 (P21 위반, F-02 잔존)
- **A3-07-05 (MEDIUM)**: `profit-overview-sector-pnl.ts:139-168` 업종×종목 이중 루프 무보호 → 한 종목 실패 시 이후 업종 전부 누락
- **A3-07-06 (MEDIUM)**: `stock-classification.ts:278-322` 3개 루프 무보호 → 칩 업종명/카운트 미갱신
- **A3-07-07 (MEDIUM)**: `profit-overview-mount.ts:101-133` buildAccountRows 루프 무보호 → 계좌 행 일부 누락
- **A3-07-08 (LOW)**: `profit-detail-mount.ts:185-222` buildStatRow 루프 무보호
- **A3-07-09 (LOW)**: `router.ts:105-109` notifyRouteChange cb 루프 무보호
- **A3-07-10 (LOW)**: 프론트엔드 전역 87개 addEventListener 핸들러 대부분 무보호

**핵심 발견**:
- Store 리스너 "간" 격리는 F-02 fix로 양호하나 "내부" 칩 간 격리는 미해결 (A3-07-04)
- DataTable 셀 단위 격리는 잘 되어 있으나 행 단위 격리 부재 (A3-07-01/02)
- F-02 사례와 동일 패턴이 헤더 onStateChange에 잔존 — F-02 근본 수정 완성을 위해 A3-07-04 수정 필요
- 페이지 리스트 루프 대부분 per-item 격리 없음
- 양호 항목: store.ts listener 루프, DataTable 셀 단위 격리(fixed/virtual), Router handleRouteChange(에러 UI+재시도)

**수정 방향 (참고용, 승인 시 별도 세션)**:
- A3-07-01/02: 행 렌더링 루프 내 renderRow/renderDataRow 호출을 try/catch로 감싸고 실패 시 로깅 + 해당 행 건너뛰기
- A3-07-04: onStateChange 내 각 칩 갱신 블록을 개별 try/catch로 감싸거나 칩 갱신 헬퍼에 try/catch 내장. 증권사 칩 루프도 per-broker try/catch
- A3-07-05~07: 페이지 리스트 루프 per-item try/catch + 로깅
- A3-07-03: extractSamples 샘플링 루프 내 셀 render try/catch (샘플링이므로 빈 문자열 폴백은 P20 위반 아님)
- A3-07-09: notifyRouteChange cb 루프 try/catch
- A3-07-10: 고위력 핸들러(저장/주문 관련)부터 우선 try/catch, 전역 일괄은 P24 검토

**추가 작업**: 세션 6 B4-06 위반 3건이 섹션 2 매트릭스에 누락되어 있어 이번 세션에서 보완 추가 (B4-06-01~03).

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**다음 세션 대기 사항**: 세션 8 (B5 매매·테스트모드 태스크 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 10에 결과 누적 예정. 조사 파일: `trading.py`, `buy_order_executor.py`, `dry_run.py`. 조사 범위: `trading.py:477,666` dry_run fake_fill create_task 직접 호출 (P23 위반 후보), add_done_callback 로깅 실제 발화 여부 (P16 교차), 매매 경로 예외 전파 — 매수/매도 실패 시 엔진 루프 영향, safe-trade 스킬 연계 (거래 로직 수정 시 별도 스킬 필수).

---

### P25 전수 조사 세션 5: B3 대형 스케줄러·파이프라인 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사만 수행 (코드 수정 없음). HANDOVER 미해결 문제 1건 기록.

**배경**: P25 전수 조사 9세션 중 세션 5. B3 대형 스케줄러·파이프라인 영역(`daily_time_scheduler.py` 1524줄, `market_close_pipeline.py` 1407줄) 조사. 우선순위 5위 — 장마감 후 확정 데이터 파이프라인 + 타임테이블 스케줄러. 한 번 중단 시 당일 확정 데이터 미갱신 위험.

**조사 파일**: 2개 메인 파일 + 1개 보조 파일 (engine_lifecycle.py — schedule_engine_task 정의 확인용)

**조사 항목 4가지 결과**:

1. **schedule_engine_task 15회 호출 격리 (daily_time_scheduler.py)**:
   - 14회 실제 호출 + 1회 import. 모두 `schedule_engine_task(coro, context="...")` 형태로 일관 (P23 OK)
   - `engine_lifecycle.py:279-309` 정의: `loop.call_soon_threadsafe(_create_with_callback)` + `task.add_done_callback(lambda t: logger.warning(...) if t.exception() else None)` → 태스크 실패 시 경고 로깅, 루프 중단 없음 → **P25 격리 OK**
   - call_soon_threadsafe 자체 실패 시 `coro.close()` 정리 → OK
   - 15회 모두 동일 패턴, 격리 일관적

2. **except 블록 silent pass 여부 (P20)**:
   - **market_close_pipeline.py 19개**: silent pass 1건(492 float 변환 `pass`), 빈 폴백 1건(897 `confirmed={}`), exc_info 누락 5건(424, 858, 934, 1103, 1254), raise 전파 1건(385 의도적), 나머지 11건 logger.warning+exc_info OK
   - **daily_time_scheduler.py 26개**: silent pass 0건, exc_info 누락 6건(1273, 1287, 1327, 1354, 1446, 1507), RuntimeError→return 3건(1085, 1372, 1458 의도적 루프 없음 시 스킵), 나머지 17건 OK

3. **파이프라인 단계 간 실패 전파 (P9)**:
   - `_run_confirmed_pipeline` (976-1064): 1~4단계 None 반환 시 즉시 `return {"fetched":0,"failed":0,"cached":False}` → 전파 명시적. 단 실패 상태 알림 필드 없어 fetched=0이 정상 0건인지 실패인지 구분 안 됨 → **P21 부분 위반**
   - 5단계 `confirmed={}` 폴백(897) → `if confirmed` 가드로 메모리/DB 보호되나, `_run_post_confirmed_pipeline(eligible_codes=confirmed_codes)`는 여전히 실행 → 빈 eligible로 캐시 저장 시도
   - 7단계 `_step7_recompute_and_broadcast` except(972) → logger.warning+exc_info → 격리 OK
   - finally 플래그 복원 → OK

4. **call_later/call_soon_threadsafe 콜백 실패 시 루프 영향**:
   - daily_time_scheduler.py call_later 3곳(1116, 1401, 1465): 모두 `lambda: schedule_engine_task(coro, context=...)` → schedule_engine_task 내부 try/except로 보호되어 lambda 예외 거의 불가능. lambda 자체 예외 시 asyncio "Exception in callback" 경고, 루프 중단 없음 → **P25 OK**
   - market_close_pipeline.py call_soon_threadsafe 1곳(68): `lambda: q.put_nowait(data) if not q.full() else None` + 외부 try/except(44-73) → 실패 시 logger.warning → OK. 단일 루프 스레드이므로 full()/put_nowait 레이스 없음

**식별 위반 4건** (미해결 문제에 기록):
- **B3-05-01 (HIGH)**: `market_close_pipeline.py:645-650` `_save_confirmed_cache` inner except에서 rollback+warning 후 fall-through → 650 `return True` → 전종목 마스터 테이블 DB 저장 실패해도 함수 True 반환 → **P22 데이터 정합성 위반 + P21 사용자 투명성 위반** (실패를 성공으로 보고)
- **B3-05-02 (MEDIUM)**: `market_close_pipeline.py:897` `_step5_download_daily_confirmed`에서 `confirmed = {}` 빈 폴백 → **P20 폴백 금지 위반**. if confirmed 가드로 메모리/DB는 보호되나, 빈 eligible_codes로 `_run_post_confirmed_pipeline` 실행 → 빈 캐시 저장 시도
- **B3-05-03 (LOW)**: `market_close_pipeline.py:492` `except (ValueError, TypeError): pass` silent pass → **P20 위반** (로깅 없음). float 변환 실패 시 strength_str 갱신 스킵만 하고 종목 루프 계속
- **B3-05-04 (LOW)**: exc_info 누락 11건 (pipeline 424, 858, 934, 1103, 1254 + scheduler 1273, 1287, 1327, 1354, 1446, 1507) → **P23 일관성 위반**. logger.warning은 하나 exc_info=True 누락. 단 934는 "(무시)" 표시로 의도적 일부 드러남

**핵심 발견**:
- schedule_engine_task 15회 호출은 모두 P25 격리 준수 — add_done_callback으로 태스크 실패 격리 일관
- call_later 3곳 모두 schedule_engine_task 경유로 보호 — 직접 코루틴 호출 아님 → P25 OK
- 파이프라인 1~4단계 None 반환 패턴은 명시적이나 실패 상태 전달 부재 → P21 부분 위반
- 5단계 confirmed={} 폴백은 if confirmed 가드로 완화되나 여전히 P20 위반
- _save_confirmed_cache 645-650은 가장 심각 — DB 저장 실패를 True로 보고 → 후속 6단계 메모리 교체 로직이 잘못된 성공 전제로 진행
- 양호 항목 다수: 26+19=45개 except 중 28개는 logger.warning+exc_info=True로 P25 준수. RuntimeError→return 3건은 의도적 스킵. call_later/call_soon_threadsafe 콜백 모두 보호

**수정 방향 (참고용, 승인 시 별도 세션)**:
- B3-05-01: 645 except 블록 끝에 `return False` 추가 (또는 650 return True를 inner try 안으로 이동). inner DB 저장 실패 시 False 반환하도록
- B3-05-02: 897 `confirmed = {}` 대신 `return 0, total, False` (전체 실패로 종료). 또는 raise 후 상위에서 처리
- B3-05-03: 492 `pass` 대신 `logger.warning("[데이터] strength 변환 실패: %r", str_val, exc_info=True)` 추가
- B3-05-04: 11곳 logger.warning에 `exc_info=True` 추가. 단 934는 "(무시)" 의도적이나 exc_info 추가 권장

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (조사 보고서 작성).

**다음 세션 대기 사항**: 세션 6 (B4 파이프라인 헬퍼·유틸리티 조사) 진행 대기. 조사 파일: 미정 (P25 전수 조사 계획 문서 참조). 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 8에 결과 누적 예정.

---

### P25 전수 조사 세션 4: A2 Store listener 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사 보고서 1파일 갱신. 조사만 수행 (코드 수정 없음).

**배경**: P25 전수 조사 9세션 중 세션 4. A2 Store listener 영역(`store.ts`, `hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts` 4개) 조사. 우선순위 4위 — 화면 갱신 최종 경로. 세션 1(A1 WS 디스패치)에서 식별한 A1-01-04(binding.ts 핸들러 try/catch 없음)의 후속 경로 검증.

**조사 파일**: 4개 메인 파일 (store 57줄, hotStore 607줄, uiStore 256줄, stockClassification 54줄) + 2개 보조 파일 (stores/index 5줄, binding 338줄 — setState 호출부·updater 함수 본문 확인용)

**식별 위반 2건**:
- **A2-04-01 (MEDIUM)**: `store.ts:19` `setState`의 updater 함수 `partial(state)`가 try/catch 밖. updater 본문 throw 시 listener 루프(40-46) 보호 우회, setState 호출자에게 즉시 전파 → binding.ts 핸들러(A1-01-04) → WS 디스패치(A1-01-01)로 전파. 고빈도 이벤트(real-data, buy-targets-delta, account-update)의 updater throw 시 화면 갱신 전체 중단 위험. throw 확률은 낮으나 구조적 보호 부재.
- **A2-04-02 (MEDIUM)**: `hotStore.ts:367-370,390,412,431` `window.dispatchEvent(new CustomEvent(...))`가 try/catch 밖. CustomEvent 핸들러(real-data-tick/orderbook-tick/program-tick) throw 시 apply* 함수 호출자로 전파 → binding.ts 핸들러 → WS 디스패치로 전파. real-data-tick은 매 틱 발생. 핸들러 등록부는 A3(세션 7)에서 조사 예정.

**핵심 발견**:
- `store.ts:40-46` listener 루프는 try/catch + `console.error('[Store] listener error', e)`로 보호 — **F-02 fix로 P25 준수**. silent pass 아님 (P20 준수).
- 하지만 updater 함수(19)와 dispatchEvent(367-431)가 listener 루프 보호를 우회하는 2개 경로. 한 예외가 WS 디스패치 체인 전체로 전파될 수 있음.
- 3개 store(hot/ui/stockClassification) 모두 동일 `createStore` 패턴 — P23 일관성 준수. 단 updater 보호 부재가 3개 store에 공통 적용.
- 양호 항목 다수: apply* 함수 30개(hotStore 13 + uiStore 16 + stockClassification 1) 모두 setState 경유로 listener 루프 보호됨. shallow merge + Object.is 변경 감지로 불필요한 리렌더 방지(P24). subscribe/unsubscribe Set 기반 정리(P25).

**수정 방향 (참고용, 승인 시 별도 세션)**:
- A2-04-01: `setState` 본문을 try/catch로 감싸거나 updater 함수 호출(19)을 try/catch로 감싸고 실패 시 로깅 후 early return. `store.ts` 단일 파일 수정으로 3개 store 모두 보호.
- A2-04-02: `applyRealData`/`applyOrderbookUpdate`/`applyProgramUpdate` 내 `window.dispatchEvent`를 try/catch로 감싸거나, CustomEvent 핸들러 등록부(A3 영역)에서 try/catch 추가. A3(세션 7) 조사 후 결정 권장.

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (조사 보고서 작성).

**다음 세션 대기 사항**: 세션 5 (B3 대형 스케줄러·파이프라인 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 7에 결과 누적 예정. 조사 파일: `daily_time_scheduler.py`, `market_close_pipeline.py`.

---

### P25 전수 조사 세션 3: B2 파이프라인 연산 루프 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사 보고서 1파일 갱신. 조사만 수행 (코드 수정 없음).

**배경**: P25 전수 조사 9세션 중 세션 3. B2 파이프라인 연산 루프 영역(`pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `pipeline_gateway.py` 3개) 조사. 우선순위 3위 — 업종 점수·매수 후보 산출 경로, 중단 시 매수 후보 미갱신 위험. 세션 2에서 이월된 B1-02-05/06(호출자 의존) 확인도 함께 수행.

**조사 파일**: 3개 메인 파일 (pipeline_compute 686줄, pipeline_compute_tick_handlers 333줄, pipeline_gateway 120줄) + 6개 보조 파일 (engine_lifecycle, app.py, engine_ws_dispatch, engine_sector_confirm, engine_account_notify, sector_data_provider — schedule_engine_task 비교·B1-02-05/06 원본·Phase 2 호출 함수 확인용)

**식별 위반 5건**:
- **B2-03-01 (HIGH)**: `pipeline_compute.py:646-670` `_phase2_batch_recompute_loop` while 루프 본문에 try/except 없음. `notify_desktop_sector_scores`/`_flush_sector_recompute_impl` 무보호 호출이 throw 시 태스크 영구 종료 → 업종 점수 갱신 영구 중단 → 매수 후보 선정 영향.
- **B2-03-02 (MEDIUM)**: `pipeline_compute.py:673-686` `_sector_recompute_loop_impl`이 `except CancelledError`만 있고 `except Exception` 없음. B2-03-01 상위 원인. `_compute_loop_impl`은 `except Exception` 있는데 비대칭 (P23 위반).
- **B2-03-03 (LOW)**: `pipeline_compute.py:521-526` `_handle_real_tick` for item 루프에 per-item try/except 없음. 한 item 실패 시 같은 REAL 틱의 나머지 item 스킵. 루프 전체 try/except(519-528)는 compute 루프 전파는 차단하나 형제 item 손실은 막지 못함.
- **B2-03-04 (LOW)**: `pipeline_compute_tick_handlers.py:92-104` `_handle_real_0j_tick`에 try/except 없음. 다른 leaf 핸들러(01/0d/PGM)는 try/except 있는데 0J만 없음 → P23 일관성 위반.
- **B2-03-05 (LOW)**: `pipeline_gateway.py:32` `start_gateway_loop`가 `_gateway_task`에 done_callback 없음. compute 서브태스크는 done_callback 있는데 게이트웨이는 없음 → P23 일관성 위반. 단 app.py:63에서 외부 done_callback 추가됨.

**핵심 발견**:
- 사전 위반 후보 `pipeline_compute.py:209,214` create_task 직접 호출은 **위반 아님**으로 확정 — `start_compute_loop`는 엔진 루프 안에서 `await`로 호출되므로 `schedule_engine_task`(UI 스레드 크로스 스레드용) 불필요. done_callback 로깅 있어 P25/P23 준수.
- **B1-02-05/06 호출부 격리 확인 완료**: `_handle_real_tick`(519-528) try/except가 루프 전파 차단 → compute 루프로 전파 안 됨. 단 per-item try/except 없어 형제 item 손실(B2-03-03). B1-02-05/06 등급 LOW 유지, 본문 try/catch는 선택적.
- `_compute_loop_impl`(278-319)과 `_phase1_wait_threshold`(569-635)는 while 루프 try/except + `except Exception: log+continue`로 P25 준수. 반면 `_phase2_batch_recompute_loop`(646-670)와 `_sector_recompute_loop_impl`(673-686)는 미보호 — 동일한 while 루프 패턴 4곳 중 2곳만 보호되어 P23 비대칭.
- 양호 항목 다수: `_process_tick_batch` per-event try/except, `_process_control_signal`/`_handle_sector_recompute`/`_calculate_receive_rate` try/except, leaf 핸들러 01/0d/PGM try/except, `_flush_sector_recompute_impl` try/except, `_broadcast_loop` while 루프 try/except.

**수정 방향 (참고용, 승인 시 별도 세션)**:
- B2-03-01: while 루프 본문을 try/except로 감싸고, `except CancelledError: break` + `except Exception: log+continue`. `_compute_loop_impl`(314-317) 패턴과 일치
- B2-03-02: `except Exception: log` 추가. 단 B2-03-01 수정 시 자연 해결 가능
- B2-03-03: for 루프 본문 per-item try/except. `_process_tick_batch`(262-267) 패턴과 일치
- B2-03-04: `_handle_real_0j_tick` 본문 try/except. 다른 leaf 핸들러 패턴과 일치
- B2-03-05: `_gateway_task.add_done_callback(...)` 추가. compute 서브태스크 패턴과 일치

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (조사 보고서 작성).

**다음 세션 대기 사항**: 세션 4 (A2 Store listener 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 6에 결과 누적 예정. 조사 파일: `frontend/src/stores/store.ts`, `hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts`.

---

### P25 전수 조사 세션 2: B1 엔진 코어 루프 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사 보고서 1파일 갱신. 조사만 수행 (코드 수정 없음).

**배경**: P25 전수 조사 9세션 중 세션 2. B1 엔진 코어 루프 영역(`engine_lifecycle.py`, `engine_loop.py`, `engine_ws_dispatch.py`, `engine_ws.py`, `engine_ws_fill_followup.py`, `engine_ws_parsing.py`, `engine_ws_reg.py` 7개) 조사. 우선순위 2위 — 매 틱·매 이벤트 통과 경로, 한 번 중단 시 자동매매 전체 정지 위험.

**조사 파일**: 7개 메인 파일 (engine_lifecycle 328줄, engine_loop 395줄, engine_ws_dispatch 401줄, engine_ws 271줄, engine_ws_fill_followup 29줄, engine_ws_parsing 218줄, engine_ws_reg 490줄) + 4개 보조 파일 (kiwoom_connector, ls_connector, app.py, engine_service — 호출자 격리 확인용)

**식별 위반 7건**:
- **B1-02-01 (HIGH)**: `engine_loop.py:304` while 루프 본문 내 `is_ws_subscribe_window` 호출이 try/except 없음. throw 시 외부 try(159)에서 catch → 엔진 루프 전체 종료. 한 번의 오류가 엔진을 영구 정지.
- **B1-02-02 (MEDIUM)**: `engine_loop.py:374,377` finally 블록 `disconnect_all()`/`disconnect()` 무보호. throw 시 후속 정리 스킵 → 엔진 상태 불일치.
- **B1-02-03 (MEDIUM)**: `engine_loop.py:387,389` finally 블록 REST 정리 루프에서 `_reset_client()`/`aclose()` 무보호. 한 증권사 실패 시 나머지 스킵.
- **B1-02-04 (HIGH)**: `engine_loop.py:31` `_cache_and_bootstrap`에서 `_load_caches_preboot` 무보호. throw 시 엔진 루프 종료. 캐시 로드 실패가 엔진 기동 전체 차단.
- **B1-02-05 (LOW)**: `engine_ws_dispatch.py:149-153` `_handle_real_00` 내 `on_fill_update`/`_on_fill_after_ws` 무보호. 호출자(pipeline_compute) 의존 — 세션 3에서 확인.
- **B1-02-06 (LOW)**: `engine_ws_dispatch.py:162` `_handle_real_balance` 내 `_apply_balance_realtime` 무보호. 호출자 의존 — 세션 3에서 확인.
- **B1-02-07 (LOW)**: `engine_lifecycle.py:38` `start_engine` 내 `_refresh_positions_if_dirty` 무보호. 주 호출자(app.py)는 격리 있으나 engine_service.py:93 경유 시 미확인 — 세션 6에서 확인.

**핵심 발견**:
- `schedule_engine_task` (engine_lifecycle.py:279-309) 중앙 격리 메커니즘은 P25 준수 (done_callback 로깅 + coro.close() 정리). 이 패턴을 사용하는 모든 경로는 격리 확보.
- 커넥터 recv 루프 (Kiwoom/LS)는 전체 루프 try/except, 비-연결오류 시 로깅+계속. P25 준수, P23 일관.
- 사전 위반 후보 `engine_loop.py:343-344` create_task 직접 호출은 **위반 아님**으로 확정 — 로컬 이벤트 대기 태스크, asyncio.wait + cancel로 정상 정리.
- `handle_ws_data` (engine_ws_dispatch.py:165-177)의 try/except가 LOGIN/REG/UNREG/REMOVE/JIF 핸들러를 격리. 양호.
- 엔진 루프의 취약점은 while 루프 본문 내 개별 무보호 호출(B1-02-01)과 finally 정리 루프의 무보호 호출(B1-02-02, B1-02-03). 이들은 한 예외가 엔진 전체를 종료시키거나 정리를 불완전하게 만듦.

**수정 방향 (참고용, 승인 시 별도 세션)**:
- B1-02-01: while 루프 본문을 try/except로 감싸고, 예외 시 로깅 + sleep(1) 후 계속. 루프 종료는 engine_stop_event에서만 유도
- B1-02-02: disconnect_all/disconnect를 try/except로 감싸고, 후속 정리는 항상 실행
- B1-02-03: _reset_client/aclose를 기존 revoke_token try/except 블록 내로 통합
- B1-02-04: _load_caches_preboot를 try/except로 감싸고, 실패 시 빈 캐시로 기동 또는 안전한 종료 + 프론트엔드 상태 전송(P21)
- B1-02-05~07: 세션 3/6에서 호출자 격리 확인 후 결정

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (조사 보고서 작성).

**다음 세션 대기 사항**: 세션 3 (B2 파이프라인 연산 루프 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 5에 결과 누적 예정. 세션 2에서 식별한 B1-02-05/06(호출자 의존)의 확인이 세션 3에서 pipeline_compute.py 호출부 격리 점검과 함께 수행될 예정.

---

### P25 전수 조사 세션 1: A1 WS 디스패치 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사 보고서 1파일 갱신. 조사만 수행 (코드 수정 없음).

**배경**: P25 전수 조사 9세션 중 세션 1. A1 WS 디스패치 영역(`frontend/src/api/ws.ts`, `frontend/src/binding.ts`) 조사. 우선순위 1위 — 매 이벤트 통과 경로, 한 핸들러 throw 시 전 채널 이벤트 수신 중단 위험.

**조사 파일**: `ws.ts`(261줄), `binding.ts`(338줄), `store.ts`(57줄 — F-02 fix 보호 범위 확인용)

**식별 위반 5건**:
- **A1-01-01 (CRITICAL)**: `ws.ts:193` `_dispatchMessage`의 `list.forEach(h => h(data))` 핸들러별 try/catch 없음. 한 핸들러 throw 시 forEach 중단 → 같은 event type 후속 핸들러 미실행 + 예외 상위 전파.
- **A1-01-02 (CRITICAL)**: `ws.ts:164-174` `_handleBinaryFrame`의 `for (const event of events)` 루프가 try 블록 내부. 한 이벤트 핸들러 throw 시 catch가 잡지만 루프 중단 → 같은 바이너리 프레임의 나머지 이벤트 모두 손실. real-data 고빈도 프레임이므로 한 종목 오류가 다른 종목 시세 갱신 차단.
- **A1-01-03 (MEDIUM)**: `ws.ts:172,181` catch 로그가 "디코딩 실패"/"파싱 실패"로 핸들러 예외와 혼동. P21/P23 위반.
- **A1-01-04 (HIGH)**: `binding.ts` 33개 onEvent 핸들러 전부 내부 try/catch 없음. F-02 fix(store.ts listener 루프)는 UI 렌더링 listener만 보호, binding.ts 핸들러 본문 로직 + setState updater 함수는 보호되지 않음. 고위험: `buy-targets-delta`, `sector-scores`, `sector-stocks-delta`, `circuit_breaker_open`.
- **A1-01-05 (LOW)**: `ws.ts:132-136` `_scheduleReconnect` setTimeout 콜백 try/catch 없음. `_connect` 동기 throw 시 재연결 루프 영구 중단.

**핵심 발견**: F-02 fix(store.ts:40-46 listener 루프 try/catch)는 UI 렌더링 listener만 보호. binding.ts 핸들러 본문 로직(destructuring, recalcTradeAmountRank, rebuildBuyTargetIndex) + setState updater 함수(`partial(state)` — store.ts:19)는 보호되지 않아, throw 시 store.ts를 넘어 ws.ts 디스패치 단계로 역전파 → A1-01-01/02 경로 합류.

**수정 방향 (참고용, 승인 시 별도 세션)**:
- A1-01-01: `forEach`를 try/catch 감싼 루프로 변경, 핸들러 throw 시 `console.error('[WS] handler error', type, e)` + 다른 핸들러 계속 실행
- A1-01-02: A1-01-01 수정으로 자연 해결 (핸들러 throw가 상위로 전파되지 않음)
- A1-01-03: 디코딩 catch와 핸들러 catch 분리 후 목적에 맞는 로그
- A1-01-04: 디스패치 격리 확보 시 핸들러 개별 try/catch는 선택적. 고위험 핸들러는 본문 try/catch 권장. 최종 방침은 수정 세션에서 결정
- A1-01-05: `_connect()` 호출 try/catch, 실패 시 `_scheduleReconnect` 재호출

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (조사 보고서 작성).

**다음 세션 대기 사항**: 세션 2 (B1 엔진 코어 루프 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 4에 결과 누적 예정.

---

### P25 전수 조사 보고서 파일 생성 (2026-07-23)

**세션**: 단일 세션. 문서 1파일 신규 작성. 사전 검토(별도 파일 필요성) → 승인 → 파일 생성 → 커밋.

**배경**: P25 원칙 신규 추가 후, P25 관점 전수 조사 계획 수립. 9세션 예정. HANDOVER.md 단독 사용 시 규칙 7 롤링 윈도우(최근 3건 유지)로 초기 세션 조사 결과 소실 위험 → 별도 조사 보고서 파일 필요성 검토.

**검토 결과**:
- 규칙 11 (계획서 파일 삭제): `docs/plan_*.md`, `docs/architecture_*_design.md`는 완료 시 삭제. 단, `docs/*_investigation.md` (조사 보고서)는 삭제 제외 — 역사적 기록 유지
- 30세션 감사 파일(`architecture_audit_plan.md` 1221줄, `architecture_audit_tasks.md` 1105줄)은 24개 원칙 전체 대상. P25 단일 원칙 감사와 범위 혼재 방지를 위해 별도 파일 분리
- P24 단순성: 9세션은 단일 파일에 세션별 섹션으로 충분. plan+tasks 2분할 불필요

**생성 파일 1개**:
- `docs/p25_isolated_failure_investigation.md` (287줄)
  - 섹션 1: 조사 개요 (목적, P25 핵심 내용, 조사 범위 A/B/C, 조사 방식, 9세션 분할, 우선순위 기준, 사전 확인 위반 후보)
  - 섹션 2: P25 위반 매트릭스 빈 템플릿 (ID/영역/파일:줄/위반 내용/영향 범위/등급/관련 원칙/조사 세션/수정 승인) + 등급 정의(CRITICAL/HIGH/MEDIUM/LOW)
  - 섹션 3~10: 세션 1~8 기본 구조 (상태 미시작, 조사 파일, 조사 범위, 조사 결과/위반 목록 placeholder)
  - 섹션 11: 세션 9 교차 점검·총합 보고 (교차 원칙 매트릭스 빈 템플릿, 우선수정 추천 placeholder, 조사 완료 정의)
  - 섹션 12: 변경 이력

**문서 종류**: 조사 보고서 (`docs/*_investigation.md`) — 규칙 11 삭제 제외, 완료 후에도 유지

**HANDOVER.md 연동 규칙**:
- 각 세션 종료 시 `세션 개요`에 본 보고서 경로 참조 명시
- `다음 세션 진행 대기`에 현재 세션 번호 + 다음 세션 조사 영역 명시
- 조사 완료(9세션) 후에도 본 보고서는 유지, HANDOVER.md에서 해당 참조 제거

**검증**: 문서 신규 작성만 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (문서 작성).

**다음 세션 대기 사항**: 세션 1 (A1 WS 디스패치 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 3에 결과 누적 예정.

---

### P25 (격리된 실패) 아키텍처 원칙 신규 추가 (2026-07-23)

**세션**: 단일 세션. 문서 2파일. 사전조사(기존 원칙 충돌/중복 분석) → 승인 → 문서 수정 → 커밋.

**배경**: 직전 세션에서 F-02(header.ts 장 상태 칩 렌더링 실패 → 앱 전체 중단) 근본 해결 완료. 해당 사례에서 "예외 전파 차단(fault isolation)"을 명시하는 기존 원칙이 없음을 확인 → P25 신규 추가.

**기존 원칙과의 관계 분석 (사전조사 결과)**:
- P7(블로킹): "느린 연산" 방지. P25는 "throw 전파 차단". 원인 다름.
- P9(파이프라인 독립): 파이프라인 간 독립. P25는 구성요소 간 격리. 범위 다름.
- P20(폴백 금지): "빈값 덮기 금지". P25는 "실패 전파 차단". 격리 시 에러 로그 출력하므로 폴백 아님.
- P24(단순성): 잠재 충돌 — P25는 "최소 전파 차단"에 국한, microservice식 과도 격리 추상화 금지 명시로 충돌 방지.
- 결론: P25가 다루는 "실패 전파 차단"을 직접 명시하는 기존 원칙 없음. 추가 타당.

**수정 내용 (2파일)**:
- `ARCHITECTURE.md`:
  - line 18: "불변 원칙 24개" → "불변 원칙 25개"
  - P24 이후에 P25 블록 추가 (내용/배경/구현 가이드/P24 균형/P20 구분 명시)
- `AGENTS.md`:
  - 섹션2: "24개" → "25개" (3곳), P 목록에 P25 추가, 사전조사 원칙 목록에 P25 추가
  - 백엔드 체크리스트: P25 항목 추가 (태스크/코루틴 실패 격리, schedule_engine_task 사용, 에러 로깅)
  - 프론트엔드 체크리스트: P25 항목 추가 (칩/컴포넌트 렌더링 실패 격리, store listener 루프 전파 차단, 에러 로깅)

**P25 핵심 내용**:
- 한 구성요소 실패가 전체 시스템 기동/운영 블로킹 금지
- 실패는 해당 구성요소에서 차단+로깅, 다른 구성요소 정상 작동 유지
- 격리 ≠ silent 무시 — 반드시 에러 로깅 (P20/P23과 일관)
- P24 균형: 최소 전파 차단에 국한, 과도한 격리 추상화 금지

**검증**: 문서 수정만 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (문서 수정).

**다음 세션 대기 사항**: 없음.

---

### header.ts 장 상태 칩 렌더링 실패 → 앱 전체 중단 구조 근본 수정 (F-02 해결) (2026-07-23)

**세션**: 단일 세션. 프론트엔드 3파일. 사전조사 → 승인 → 수정 → 검증 → 커밋.

**문제 현상**: `PHASE_STYLE[phase]`가 undefined일 때 TypeError가 header의 `onStateChange`에서 throw → `store.setState` listener 루프에서 다른 listener/호출자로 전파 → 앱 전체 렌더링 중단(하얀 화면). 이전 세션에서 긴급 폴백 복구로 증상만 덮어둔 상태.

**근본 원인 (구조적)**:
1. `frontend/src/stores/store.ts:37-39` — listener 루프에 try/catch 없음. 하나의 listener throw가 다른 listener와 setState 호출자(WS 핸들러)까지 전파 → 앱 전체 중단. "undefined 하나가 전체 앱을 죽이는" 구조의 핵심.
2. `frontend/src/stores/uiStore.ts:85, 245` — 초기값/폴백값 `'CLOSED'`가 `PHASE_STYLE`에 없는 키. 부트스트랩 단계에서 항상 undefined 도달.
3. `frontend/src/layout/header.ts:102` — `|| PHASE_STYLE['장마감']` 폴백은 P20 위반 (정상 경로의 undefined를 폴밭으로 덮음). 긴급 조치일 뿐 근본 해결 아님.

**수정 내용 (3파일)**:
- `frontend/src/stores/store.ts:37-46` — listener 루프 try/catch 전파 차단. throw 시 `console.error('[Store] listener error', e)` 로깅(silent pass 아님), 다른 listener는 계속 실행. P16/P21.
- `frontend/src/stores/uiStore.ts:85, 245` — 초기값/폴백 `'CLOSED'` → `'장마감'` 통일 (안 B). P10/P23.
- `frontend/src/layout/header.ts:102-117` — 폴백 제거. undefined 시 `console.warn` 경고 + neutral 기본 스타일로 phase 문자열 그대로 표시. 정상 경로 폴밭 금지(P20), 칩만 기본 표시하고 나머지 화면 정상 작동(P21).

**아키텍처 원칙 부합**:
- P20 (폴백 금지): 정상 경로 폴백 제거. 단, "알 수 없는 phase(백엔드-프론트 불일치)"에 대한 기본 표시는 폴백이 아닌 에러 복구 표시로定位 — 경고 로그 + neutral 스타일.
- P21 (사용자 투명성): 칩 렌더링 실패 시 칩만 기본 표시, 나머지 헤더/화면 정상 작동.
- P22 (데이터 정합성): 초기값 'CLOSED' → '장마감'으로 백엔드 phase 문자열과 일치.
- P16 (살아있는 경로): store.ts try/catch는 silent except:pass 아님 — console.error 로깅.

**수정 파일 3개**:
- `frontend/src/stores/store.ts` — listener 루프 전파 차단
- `frontend/src/stores/uiStore.ts` — 초기값/폴백 '장마감' 통일 (2곳)
- `frontend/src/layout/header.ts` — 폴백 제거 + 명시적 안전 처리

**검증**:
- `npm run typecheck` exit 0
- `npm run build` 1.94s exit 0 (76 modules transformed)
- lint 스크립트 존재하지 않음 (package.json에 없음)
- 잔존 프로세스 0건

**화면 영향**:
- 앱 기동 시 헤더 장 상태 칩이 '장마감' 스타일로 정상 표시 (이전과 동일 외관)
- WS 수신 후 실제 phase로 갱신 (이전과 동일)
- 향후 백엔드가 알 수 없는 phase를 보내도 칩만 neutral 표시, 앱 전체 중단 없음 (구조적 개선)

**다음 세션 대기 사항**: 없음 (F-02 근본 해결 완료).

---

### header.ts 장 페이즈 폴백 제거 → 긴급 복구 (F-02 경미) (2026-07-23)

**세션**: 단일 세션. 프론트엔드 1파일. 사전조사 생략 (간단 수정, 사용자 지시) → 잘못된 분석으로 인한 긴급 롤백 포함.

**문제 현상**: `header.ts:102`의 `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` 폴백 — 백엔드가 알려진 페이즈만 보내므로 "도달 불가능한 dead code"로 판단. P20(폴백 금지) + P16(살아있는 경로) 위반 (경미 등급).

**사전 조사 결과** (승인 전 조사 — **누락 있음**):
- 백엔드 `calc_timebased_market_phase()` + `_JIF_PHASE_MAP_KRX/NXT`가 보내는 phase = KRX 13개 + NXT 9개 (중복 제외 19개)
- `PHASE_STYLE` 키 19개와 1:1 완전 일치 — 누락/과잉 없음
- ~~실제 도달 가능성 0, 화면 영향 없음~~ → **잘못된 결론**. 프론트엔드 초기값/폴백값 `'CLOSED'`를 누락함.

**1차 수정 (폴백 제거)**:
- `frontend/src/layout/header.ts:102` — `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` → `PHASE_STYLE[phase]`
- 커밋 `ce9e137` "fix: header.ts 장 페이즈 폴백 제거 — 도달 불가능 dead code (P20/P16)"

**긴급 롤백 사유** (사용자 보고: 하얀 화면):
- `uiStore.ts:85` 초기값 `marketPhase: { krx: 'CLOSED', nxt: 'CLOSED', ... }`
- `uiStore.ts:245` engine_status 폴백 `?? { krx: 'CLOSED', nxt: 'CLOSED', ... }`
- 앱 기동 직후 `header.ts:488`이 `onStateChange(uiStore.getState())` 즉시 호출 → `applyMarketPhaseChip(el, 'KRX', 'CLOSED', ...)` → `PHASE_STYLE['CLOSED']` = undefined → `s.bg` 접근 시 TypeError → 렌더링 전체 중단 → 하얀 화면
- **근본 원인**: 백엔드는 한국어 페이즈명(`장마감` 등)만 보내지만, 프론트엔드 초기값/폴백은 영문 `'CLOSED'` 사용 (P23 용어 통일 위반). 폴백은 "도달 불가능 dead code"가 아니라 **부트스트랩 단계에서 항상 도달 가능한 정상 분기**.

**2차 수정 (폴백 복구)**:
- `frontend/src/layout/header.ts:102` — `PHASE_STYLE[phase]` → `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` (원복)
- 커밋 `a5b357b` "revert: header.ts 장 페이즈 폴백 복구 — 부트스트랩 'CLOSED' phase 하얀 화면 원인"
- 롤백 사유 기록 (규칙 0-3): 커밋 메시지에 잘못된 분석 인정 + 사유 + 되돌린 대상 + 영향 범위 명시

**수정 파일 1개**:
- `frontend/src/layout/header.ts:102` — 최종 상태: 폴백 복원 (원래 코드로 회귀)

**검증**:
- 1차: `npm run typecheck` exit 0, `npm run build` 1.88s exit 0 (하지만 런타임 TypeError 발생 — 빌드 통과가 런타임 안전성 보장 아님)
- 2차: `npm run build` 631ms exit 0
- 잔존 프로세스 0건

**화면 영향**:
- 1차 수정 후: 앱 기동 시 하얀 화면 (TypeError로 렌더링 중단)
- 2차 복구 후: 정상 렌더링 복구. 부트스트랩 단계 'CLOSED' phase가 '장마감' 스타일로 표시 (기존 동작 회귀)

**교훈**:
- 빌드/typecheck 통과가 런타임 안전성을 보장하지 않음 — 부트스트랩 초기값/폴백값 경로는 별도 검증 필요
- "도달 불가능" 판단 시 백엔드 값뿐 아니라 프론트엔드 초기값/폴백값/기본값도 포함해야 함
- 사전조사 생략은 "간단 수정"이라도 위험 — 규칙 0-2(수정 전 사전조사 의무) 준수 필요

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 안 B 사전조사 — `uiStore.ts` 초기값/폴백 `'CLOSED'` → `'장마감'` 통일 (P10/P23). 사전조사 항목: `'CLOSED'`를 비교/참조하는 다른 코드 전체 검색. 근본 해결 완료 시 header.ts 폴백 제거 재검토.

---

### header.ts 장 페이즈 폴백 제거 (F-02 경미) (2026-07-23, 롤백됨)

**세션**: 단일 세션. 프론트엔드 1파일. 사전조사 생략 (간단 수정, 사용자 지시).

**문제 현상**: `header.ts:102`의 `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` 폴백 — 백엔드가 알려진 페이즈만 보내므로 도달 불가능한 dead code. P20(폴백 금지) + P16(살아있는 경로) 위반 (경미 등급).

**사전 조사 결과** (승인 전 조사):
- 백엔드 `calc_timebased_market_phase()` + `_JIF_PHASE_MAP_KRX/NXT`가 보내는 phase = KRX 13개 + NXT 9개 (중복 제외 19개)
- `PHASE_STYLE` 키 19개와 1:1 완전 일치 — 누락/과잉 없음
- 실제 도달 가능성 0, 화면 영향 없음

**수정 안**: 폴백 제거 → `PHASE_STYLE[phase]` 직접 참조.

**수정 파일 1개**:
- `frontend/src/layout/header.ts:102` — `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` → `PHASE_STYLE[phase]`

**원칙 부합**:
- P16 살아있는 경로: 도달 불가능한 dead code 제거
- P20 폴백 금지: 정상 경로의 누락을 폴백으로 덮는 패턴 제거
- P24 단순성: 1줄 변경

**검증**:
- `npm run typecheck` (tsc --noEmit) — exit 0
- `npm run build` (vite build) — 1.88s exit 0
- 잔존 프로세스 0건

**화면 영향**: 없음. 백엔드가 보내는 모든 phase가 PHASE_STYLE에 정의되어 있으므로 칩 스타일 표시 변화 없음.

**커밋**: `ce9e137` (이후 `a5b357b`로 롤백됨 — 상단 세션 참조).

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 롤백됨. 상단 "header.ts 장 페이즈 폴백 제거 → 긴급 복구" 세션 참조.

---

### 수신율 갱신 로그 1줄 \r 갱신 통일 (2026-07-23)

**세션**: 단일 세션. 백엔드 2파일 + 테스트 1파일.

**문제 현상**: 수신율 갱신 시마다 `logger.info`로 매번 새 줄 출력 → 장초반 틱 집중 수신 시 40~50줄 폭주, 파일 로그 용량 증가. 다운로드 진행률은 이미 `log_progress`로 1줄 `\r` 갱신 중이나 수신율만 예외 상태.

**근본 원인**: `pipeline_compute.py` Phase 1/Phase 2 루프의 수신율 갱신 로그가 `logger.info`로 매번 새 줄 출력. 파일에도 INFO로 누적되어 용량 증가.

**수정 안**: 다운로드 진행률 `log_progress` 패턴 재사용 (P23 일관성).
- 콘솔: `\r` 1줄 갱신 (TTY 아닐 때 `\n`)
- 파일: DEBUG 강하 (INFO 운영 시 파일 누적 안 됨 → 용량 절감)
- 임계값 통과 시점: 별도 `logger.info` 1줄 영구 기록 유지 (P21 투명성)
- Phase 2 구간도 동일 적용

**수정 파일 3개**:
- `backend/app/core/logger.py` — `log_receive_rate_progress` 헬퍼 신규 추가. KRX/NXT 이중 카운터 + 임계값 표시. `_progress_active` 플래그 공유, `log_progress_end` 재사용.
- `backend/app/pipelines/pipeline_compute.py` — Phase 1 대기 중 로그 → `log_receive_rate_progress(waiting=True)`, 임계값 통과 직전 `log_progress_end()` 추가 (커서 꼬임 방지), Phase 2 로그 → `log_receive_rate_progress(waiting=False)`.
- `backend/tests/test_logger.py` — `TestLogReceiveRateProgress` 4건 추가 (TTY 대기 중, TTY Phase 2, non-TTY, zero total).

**원칙 부합**:
- P10 SSOT: `_progress_active` 단일 플래그 유지, 수신율 데이터는 기존 `_current_receive_rate` 참조
- P16 살아있는 경로: 헬퍼가 실제 Phase 1/2 루프 호출 경로에 연결
- P21 사용자 투명성: 임계값 통과 시점 `logger.info` 영구 기록 유지
- P23 일관성: `log_progress`와 동일 패턴, 용어 "수신율/임계값" 유지
- P24 단순성: 신규 헬퍼 단일 역할, 20줄 이내

**검증**:
- `py_compile` 통과, `ruff` 신규 코드 통과 (기존 unused import 2건은 본 수정과 무관)
- `pytest backend/tests/test_logger.py` 42 passed (신규 4건 포함)
- 런타임 기동 (`-W error::RuntimeWarning`) 정상 — RuntimeWarning/Traceback 없음
- 콘솔 1줄 `\r` 갱신 확인, 파일 수신율 갱신 0건 / 임계값 통과 1건 확인
- 잔존 프로세스 0건

**화면 영향**: 없음 (로그 출력 방식 변경만, WS 수신율 broadcast 불변)

**커밋**: `fe150c9` refactor: 수신율 갱신 로그를 1줄 \r 갱신으로 통일 — 다운로드 진행률과 동일 패턴 (P23/P24)

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 완료. 다음 우선순위 작업 진행.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 override datetime JSON 직렬화 오류 근본 해결 (2026-07-23)

**세션**: 긴급 런타임 오류 수정 — 단일 세션. 백엔드 2파일.

**문제 현상**: JIF 카운트다운 수신 시 `TypeError: Object of type datetime is not JSON serializable` 발생. 이후 10초 주기 장상태 브로드캐스트마다 override 만료 전까지 동일 오류 반복 (조용히 실패 — P21 위반).

**근본 원인** (데이터 흐름):
1. `engine_ws_dispatch.py:335` — `expires_at = now + timedelta(...)` 로 datetime 객체 생성 후 override dict에 그대로 저장
2. `daily_time_scheduler.py:_get_active_override()` — 저장된 override dict를 expires_at 포함 그대로 반환
3. `daily_time_scheduler.py:get_market_phase()` — `phase["krx_countdown"]`에 datetime 포함 dict 삽입
4. `engine_ws_dispatch.py:343` — `_broadcast("market-phase", get_market_phase())` 가 datetime 포함 payload 전달
5. `ws_manager.py:160` — `dumps(...)` 직렬화 실패 → TypeError

**수정 안**: 안 A (P24 단순성, P10 SSOT) — `_get_active_override()` 반환 시 `expires_at` 제외, `{label, remaining_sec}`만 반환.
- 저장은 datetime 그대로 유지 (만료 판정 `_kst_now() >= expires_at`에 필요)
- 반환은 프론트엔드 타입과 정확 일치
- 안 B(ISO 문자열 변환)는 매 호출 시 파싱 오버헤드로 P24 위반 → 비추천

**수정 파일 2개**:
- `backend/app/services/daily_time_scheduler.py` — `_get_active_override()` 반환 + docstring
- `backend/app/services/engine_state.py` — 주석 보완 (expires_at 내부 전용 명시)

**원칙 부합**:
- P10 SSOT: 브로드캐스트 스키마 = 프론트엔드 타입 = {label, remaining_sec} 정합
- P16 살아있는 경로: JIF 즉시 브로드캐스트 + 10초 주기 브로드캐스트 모두 정상 복구
- P20 폴백 금지: 만료 판정 로직 유지, 폴백 도입 아님
- P21 사용자 투명성: 10초 주기 브로드캐스트 조용히 실패 문제 함께 해결 — 화면 장상태 갱신 정상화
- P24 단순성: 1줄 변경, 파싱 오버헤드 없음

**검증**:
- `pytest test_daily_time_scheduler.py test_engine_ws_dispatch.py` 286 passed
- 런타임 기동 정상 (RuntimeWarning 없음, TypeError 없음, 수신율 100% 도달)
- 잔존 프로세스 0건

**화면 영향**:
- 상단 헤더 카운트다운 칩: JIF 카운트다운 수신 시점(장개시 10분전/5분전/1분전/10초전 등)에 화면 갱신 정상 복구. 기존에는 카운트다운 수신 순간부터 만료 시까지 화면 장상태 갱신이 조용히 실패했음.
- 매수/매도 동작: 영향 없음 (카운트다운은 표시 전용)

**커밋**: `322b888` fix: JIF 카운트다운 override 반환 시 expires_at 제외 — datetime JSON 직렬화 오류 근본 해결

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 긴급 오류 해결 완료. 이후 다음 우선순위 작업 진행.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 S-2 프론트엔드 + 테스트 보완 (2026-07-23)

**세션**: 다단계 작업 워크플로우 4세션 — `plan_jif_countdown.md` 기반 S-2 구현. 프론트엔드 3파일 + 테스트 1파일. JIF 카운트다운 복구 최종 세션.

**구현 내용 (Step 2-1 ~ 2-2)**:
1. `header.ts` — `formatCountdown()` 포맷 확장: 60초 이상일 때 "X분 Y초 전" 표시 (예: 90초 → "1분 30초 전"). sec=0이면 "X분 전" 유지.
2. `header.ts` — `PHASE_STYLE` "애프터마켓 지속" 항목 제거 (dead code — P16. 백엔드에서 더 이상 해당 페이즈명 사용 안 함).
3. `general-settings.ts` — `fixedTimes` "18:00 애프터마켓 지속 전환" 항목 제거 (백엔드 타임테이블에서 18:00 phase 엔트리 제거됨 — P10 SSOT 일치).
4. `sector-settings.ts` — 주석에서 "애프터마켓 지속" 제거 (P23 용어 통일).
5. `test_engine_ws_dispatch.py` — `_JIF_COUNTDOWN_KRX`/`_JIF_COUNTDOWN_NXT` 임포트 추가 + `TestJifConstants` 클래스에 매핑 완전성 검증 6건 추가:
   - 카운트다운 맵/페이즈 맵 중복 없음
   - 카운트다운 맵/무시 코드 중복 없음 (P20)
   - KRX 7개 / NXT 14개 엔트리 수 검증
   - remaining_sec 값 {600, 300, 60, 10} 일치 (API 문서 기준 — P10)
   - KRX 장마감 10분전 코드 없음 검증 (API 문서 — 44=5분전이 최대)

**수정 파일 4개**:
- 프론트엔드 3개: `header.ts`, `general-settings.ts`, `sector-settings.ts`
- 테스트 1개: `test_engine_ws_dispatch.py`

**검증**:
- `npm run build` 성공 (vite build, 76 modules, 945ms, 타입 오류 없음)
- `pytest backend/tests/test_engine_ws_dispatch.py backend/tests/test_daily_time_scheduler.py` 286 passed
- `pytest backend/tests/` 전체 2808 passed (이전 2802에서 6개 증가 — 신규 매핑 완전성 테스트 6건)
- 잔존 프로세스 0건

**화면 영향 (S-2 완료 후)**:
- 상단 헤더 카운트다운 칩: 90초 전일 때 "1분 30초 전"으로 더 정확하게 표시 (기존 "1분 전" → 개선)
- 설정 화면 "거래소 고정 시간" 안내: "18:00 애프터마켓 지속 전환" 항목 제거 (NXT 애프터마켓은 15:40~20:00 단일 구간)
- NXT 애프터마켓 칩: 15:40~20:00 동일 "애프터마켓" 표시 (UI 변화 없음, dead code 제거만)
- 매수/매도 동작: 영향 없음 (카운트다운은 표시 전용)

**JIF 카운트다운 복구 전체 완료 (S-1 + S-2)**:
- S-1: 백엔드 핵심 11 Step (engine_state.py, engine_ws_dispatch.py, daily_time_scheduler.py + 설계 문서 수정)
- S-2: 프론트엔드 3파일 + 테스트 1파일 (header.ts, general-settings.ts, sector-settings.ts, test_engine_ws_dispatch.py)
- 전체 수정 파일 8개 (백엔드 3 + 프론트엔드 3 + 테스트 2 + 문서 1)
- 태스크 파일(`docs/plan_jif_countdown.md`) + 설계 문서(`docs/jif_countdown_design.md`) 삭제 완료 (규칙 11 — 모든 단계 완료 후)

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: JIF 카운트다운 복구 전체 완료 + 태스크 파일/설계 문서 삭제 완료 (규칙 11). 이후 다음 우선순위 작업 진행.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 S-1 백엔드 핵심 구현 (2026-07-23)

**세션**: 다단계 작업 워크플로우 3세션 — `plan_jif_countdown.md` 기반 S-1 구현. 백엔드 핵심 11 Step + 테스트 보완.

**구현 내용 (Step 1-1 ~ 1-11)**:
1. `engine_state.py` — `krx_countdown_override`, `nxt_countdown_override` 필드 추가 (P10 SSOT — override 단일 소스)
2. `engine_ws_dispatch.py` — `_JIF_COUNTDOWN_KRX`/`_JIF_COUNTDOWN_NXT` 매핑 테이블 신설 (API 문서 기준) + `_JIF_IGNORE_CODES`에서 카운트다운 코드 전부 제거 ("53"만 남김)
3. `engine_ws_dispatch.py` — `_handle_jif()` 카운트다운 처리 추가 (override 저장 + 브로드캐스트) + 페이즈 전환 시 override 초기화
4. `daily_time_scheduler.py` — 카운트다운 임계 시각 상수 22개 정의 (KRX/NXT 장개시·장마감, 거래소 규정 코드 상수)
5. `daily_time_scheduler.py` — `build_timetable_from_cache()`에 `kind="countdown"` 엔트리 22개 추가 (타임테이블 12→33항목)
6. `daily_time_scheduler.py` — `_timetable_event_fired()`에 `kind="countdown"` 분기 추가 (JIF override 활성 시 스킵, 없으면 calc_countdown 보조)
7. `daily_time_scheduler.py` — `_get_active_override()` 헬퍼 신설 (만료 시 None 반환 — P20 폴백 금지)
8. `daily_time_scheduler.py` — `get_market_phase()` override 우선 적용 (JIF 1순위, calc_countdown 보조)
9. `daily_time_scheduler.py` — `_KRX_COUNTDOWN_MAP` 누락 페이즈 3개 보완 (종가 동시호가, 장후 시간외, 시간외 단일가 — `KRX_AFTER_HOURS_END` 사용)
10. `daily_time_scheduler.py` — NXT 페이즈명 "애프터마켓" 통일 ("애프터마켓 지속" 제거) + 18:00 엔트리/상수/분기 제거
11. `jif_countdown_design.md` 3.2절 KRX 장마감 매핑 오류 수정 (44=300초/43=60초/42=10초 — API 문서 기준)

**재심층 사전조사에서 발견·보고한 태스크 파일 오차 3건**:
- 발견 A: Step 1-9 상수명 `KRX_AFTER_CLOSE_START` → 실제 `KRX_AFTER_HOURS_END` 사용 (태스크 파일이 예견한 사항)
- 발견 B: 기존 테스트 2건 S-1에서 깨짐 → 규칙 0-1 준수를 위해 S-2 범위 일부를 S-1로 이동하여 수정
- 발견 C: `_KRX_COUNTDOWN_MAP` 라벨을 "장마감" 대신 "종가 동시호가 종료" 등 명확한 이름 사용 (P21/P23 — "장마감" 페이즈명과 혼동 방지)

**수정 파일 5개**:
- 백엔드 3개: `engine_state.py`, `engine_ws_dispatch.py`, `daily_time_scheduler.py`
- 테스트 2개: `test_engine_ws_dispatch.py` (1건 변경 + MagicMock import 추가), `test_daily_time_scheduler.py` (기존 6건 수정 + 신규 4 클래스 20건 추가)
- 문서 1개: `jif_countdown_design.md` (3.2절 매핑 오류 수정)

**검증**:
- `pytest backend/tests/` 2802 passed (이전 2782에서 20개 증가 — 신규 테스트 20건 반영, 기존 테스트 6건 수정)
- `python -W error::RuntimeWarning main.py` 런타임 기동 18초 — RuntimeWarning 없음, 타임테이블 33항목 빌드 확인, 스케줄러 정상 시작
- 잔존 프로세스 0건 확인

**화면 영향 (S-1 완료 후)**:
- 상단 헤더 칩: 카운트다운 코드 수신 시 즉시 "정규장 장마감 5분 전" 등 상세 카운트다운 표시 (JIF 기반 — 기존에는 무시됨)
- NXT 애프터마켓: 15:40~20:00 단일 "애프터마켓" 표시 (기존 18:00에 "애프터마켓 지속"으로 전환되던 것 제거 — UI 변화 없음, 동일 초록 칩 유지)
- 매수/매도 동작: 영향 없음 (카운트다운은 표시 전용, 주문 차단은 `get_order_time_block_status()` 담당)

**S-2 대기 사항 (프론트엔드 + 테스트 보완)**:
- `header.ts` — `formatCountdown()` "X분 Y초 전" 포맷 확장 (90초 → "1분 30초 전")
- `header.ts` — PHASE_STYLE "애프터마켓 지속" 항목 제거 (dead code — P16)
- `general-settings.ts` — timetable 표시 "18:00 애프터마켓 지속 전환" 항목 제거
- `sector-settings.ts` — 주석 "애프터마켓 지속" 제거
- `test_engine_ws_dispatch.py` — `_JIF_COUNTDOWN_KRX`/`_JIF_COUNTDOWN_NXT` 매핑 완전성 검증 추가
- `test_daily_time_scheduler.py` — override 만료 전환, 카운트다운 엔트리 수 검증 등 보완

**잔존 프로세스**: 없음 (런타임 기동 후 완전 종료 확인).

**다음 세션 대기 사항**: JIF 카운트다운 복구 S-2(프론트엔드 + 테스트 보완) 구현 — 다단계 작업 워크플로우 4세션. 태스크 파일(`docs/plan_jif_countdown.md`) 섹션 4 기반 진행. S-2 착수 전 재심층 사전조사(규칙 0-2) 수행 후 사용자 승인(규칙 0) 받아 Step 2-1~2-3 구현. 참조 문서: `docs/plan_jif_countdown.md`, `docs/jif_countdown_design.md`.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 태스크 파일 작성 (2026-07-23)

**세션**: 다단계 작업 워크플로우 2세션 — `jif_countdown_design.md` 기반 심층 사전조사 + 태스크 파일 작성. 코드 수정 없음 (조사·태스크 작성 전용 세션).

**심층 사전조사 결과 (규칙 0-2 4항목)**:
1. **의존성**: 6개 파일 수정 지점별 의존 호출자/참조자 식별 완료 (태스크 파일 섹션 1.1 표).
2. **영향범위**: 백엔드 3 + 프론트엔드 1 + 테스트 2 = 6파일. 거래 로직 영향 없음 (카운트다운은 표시 전용).
3. **아키텍처 원칙 부합**: P10/P11/P14/P16/P20/P23/P24 부합 확인 (태스크 파일 섹션 1.3 표).
4. **기존 공통 자산 확인**: `calc_countdown()`, `_TIMETABLE` 스케줄러, `_apply_market_phase()`, 시간 상수들 재사용 가능 확인 (태스크 파일 섹션 1.4 표).

**⚠️ 설계 문서 오류 발견 + 바로잡기**:
- 설계 문서 3.2의 KRX 장마감 JIF 매핑이 API 문서(`장운영정보JIF.txt` 114-122줄)와 불일치:
  - 설계: 44=600초(10분), 43=300초(5분), 42=60초(1분) — **오류**
  - API 실제: 44=300초(5분전, 최대), 43=60초(1분), 42=10초(10초) — KRX 장마감 10분전 코드 없음
- 태스크 파일에는 API 문서 기준 올바른 매핑 반영 (섹션 1.5 + Step 1-2).
- S-1 착수 시 설계 문서 3.2 매핑 테이블도 함께 수정 예정 (P10 SSOT — 문서-코드 불일치 해소, Step 1-11).

**산출물**: `docs/plan_jif_countdown.md` (태스크 파일, 427줄). 심층 사전조사 결과 + 2세션 분할 + 11개 구현 Step(S-1) + 3개 구현 Step(S-2) + 테스트 계획 + 런타임 검증 방법 + 사용자 결정 항목 + 착수 전 최종 확인 항목 포함.

**2세션 분할 (태스크 파일 섹션 2)**:
- S-1 (백엔드 핵심): 방안 1 + 3 + 2 + 4-2/4-3. Step 1-1~1-11 (engine_state.py, engine_ws_dispatch.py, daily_time_scheduler.py + 설계 문서 수정). 검증: pytest + 런타임 기동.
- S-2 (프론트엔드 + 테스트 보완): 방안 4-1 + 테스트 정비. Step 2-1~2-3 (header.ts, test_engine_ws_dispatch.py, test_daily_time_scheduler.py). 검증: npm run build + 브라우저 + pytest.

**영향 범위 (6개 파일 + 설계 문서 1)**:
| 구분 | 파일 | 변경 내용 | 세션 |
|------|------|-----------|------|
| 백엔드 | `engine_state.py` | override 필드 추가 | S-1 |
| 백엔드 | `engine_ws_dispatch.py` | JIF 카운트다운 매핑 테이블, `_handle_jif()` 처리, `_JIF_IGNORE_CODES` 정리 | S-1 |
| 백엔드 | `daily_time_scheduler.py` | 카운트다운 임계 상수, 타임테이블 엔트리, countdown 분기, override 헬퍼, get_market_phase override 우선, 맵 보완, 페이즈명 통일, 18:00 엔트리 제거 | S-1 |
| 프론트엔드 | `header.ts` | formatCountdown "X분 Y초 전" 포맷 | S-2 |
| 테스트 | `test_engine_ws_dispatch.py` | 카운트다운 코드 무시→처리 검증 변경 | S-2 |
| 테스트 | `test_daily_time_scheduler.py` | 카운트다운 엔트리·override·맵·페이즈명 테스트 | S-1+S-2 |
| 문서 | `jif_countdown_design.md` | 3.2절 KRX 장마감 매핑 오류 수정 | S-1 |

**거래 로직 영향**: 없음 — 카운트다운은 표시 전용. 매수/매도/주문 차단은 `get_order_time_block_status()` 담당.

**잔존 프로세스**: 없음 (조사·태스크 작성 전용 세션, 런타임 기동 없음).

**다음 세션 대기 사항**: JIF 카운트다운 복구 S-1(백엔드 핵심) 구현 — 다단계 작업 워크플로우 3세션. 태스크 파일(`docs/plan_jif_countdown.md`) 기반 진행. S-1 착수 전 재심층 사전조사(규칙 0-2) 수행 후 사용자 승인(규칙 0) 받아 Step 1-1~1-11 구현. 참조 문서: `docs/plan_jif_countdown.md`, `docs/jif_countdown_design.md`.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 설계 문서 작성 (2026-07-23)

**세션**: 상단 헤더 KRX/NXT 시간대별 장운영정보(JIF) 카운트다운 상세 표시 누락 문제 조사 + 설계 문서 작성. 코드 수정 없음 (조사·설계 전용 세션).

**산출물**: `docs/jif_countdown_design.md` (설계 문서, 326줄). 4개 방안 + 2세션 분할 계획 + 영향 범위 6개 파일 + 착수 전 최종 확인 항목 2건 포함. 상세 내용은 설계 문서 본문 참조.

---

## 직전 완료 작업 (이전 세션)

### order_time_guard_on 토글 제거 — 대안 A + 옵션 2 (2026-07-23)

**세션**: 6세션에 걸쳐 사용자가 설계한 "체결 불가 시간대 주문 차단" 토글 제거. P10(SSOT)/P16(살아있는 경로)/P23(일관성)/P24(단순성). 시장가 단일 운용에서 OFF의 의미 부재로 인한 제거 결정 (규칙 0-5 엄격 절차 적용).

**문제 배경**: SectorFlow는 시장가 주문만 사용. 체결 불가 시간대(동시호가·장외)에 시장가 주문을 전송해도 체결되지 않음. 토글 OFF의 유일한 효과 = 미체결 주문 적체(P22 위험) + 불필요한 API 호출/에러 로그. 사용자 이득 없음. 토글 ON이 항상 올바른 상태이므로 토글 자체가 무의미.

**사용자 결정**: 대안 A (토글 제거) + 옵션 2 (buy_order_executor.py의 is_krx_after_hours() → is_order_blocked_by_time() 교체). 옵션 2 선택으로 인해 is_krx_after_hours() 함수 정의도 dead code 제거.

**수정 파일 10개**:

백엔드 6개:
- `backend/app/core/settings_defaults.py:131-132` — `order_time_guard_on` 키 + 주석 제거 (2줄).
- `backend/app/services/daily_time_scheduler.py` — `get_order_time_block_status()` 토글 분기 4줄 제거 + docstring 갱신. `is_krx_after_hours()` 함수 정의 제거 (dead code — buy_order_executor.py에서 옵션 2 교체로 인해 실사용 0건).
- `backend/app/services/trading.py:820-831` — `_is_order_time_blocked()` 토글 분기 제거, 서명 `(self, stk_cd: str)` 단순화 (raw_settings 인자 제거). 호출부 2곳(L218 매수, L558 매도) 인자 수정.
- `backend/app/services/engine_service.py` — `_apply_order_time_guard_change()` 전체 제거 (16줄) + L69 호출부 제거.
- `backend/app/db/stock_tables.py:98-105` — `init_cache_tables()`에 idempotent DELETE 쿼리 추가 (`DELETE FROM integrated_system_settings WHERE key = 'order_time_guard_on'`). 스키마 변경 아님 (key-value row 삭제).
- `backend/app/services/buy_order_executor.py` — `_refresh_buyable_prices()`와 `evaluate_buy_candidates()`에서 `is_krx_after_hours()` + `is_nxt_enabled()` 이원화 판별 → `is_order_blocked_by_time(s.code)` 단일 호출로 통일. `_after_hours` 변수 제거.

프론트엔드 2개:
- `frontend/src/pages/general-settings.ts` — `buildOrderTimeGuardRow()` 함수 제거 (18줄) + L702 호출부 + L703 설명 텍스트 + L57 `orderTimeGuardToggle` 변수 선언 + L1210 sync 라인 제거.
- `frontend/src/types/index.ts:231-232` — `order_time_guard_on: boolean;` 필드 + 주석 제거.

테스트 2개:
- `backend/tests/test_daily_time_scheduler.py` — 토글 OFF 케이스 2건 제거 + `is_krx_after_hours` import 제거 + `TestIsKrxAfterHours` 클래스 전체 제거 (8 테스트).
- `backend/tests/test_buy_order_executor.py` — 36곳 `is_krx_after_hours` + `is_nxt_enabled` mock → `is_order_blocked_by_time` mock 교체. (False,False)→False 34곳, (True,False)→True 1곳, (True,True)→False 1곳.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 토글제거 | P10/P24 | 시장가 단일 운용에서 무의미한 토글 제거. 불필요한 분기 3곳 제거 (get_order_time_block_status, _is_order_time_blocked, _apply_order_time_guard_change 전체 제거). 코드 약 50줄 감소. |
| 일관성 | P23 | buy_order_executor.py의 is_krx_after_hours() + is_nxt_enabled() 이원화 판별 → is_order_blocked_by_time() 단일 함수로 통일. is_krx_after_hours() dead code 제거. |
| DB정리 | P10/P21 | integrated_system_settings 테이블에서 order_time_guard_on row 삭제 (idempotent DELETE). DB 잔존 시 코드=무시 vs DB=존재 진실 소스 분리 위험 제거. |

**검증**: `pytest backend/tests/` 2782 passed (이전 2792에서 10개 감소 — 제거한 테스트 10개 반영: TestIsKrxAfterHours 8건 + 토글 OFF 케이스 2건). `python -W error::RuntimeWarning main.py` 런타임 기동 15초+ RuntimeWarning 없음. `npm run typecheck`/`npm run build` 정상. DB에서 order_time_guard_on row 삭제 확인. 잔존 프로세스 0건.

**화면 영향**:
- 설정 페이지: "체결 불가 시간대 주문 차단" 토글 행 사라짐 (설정 항목 1개 감소).
- 상단 헤더 배지: 체결 불가 시간대에 항상 배지 표시 (이전에는 설정 OFF 시 숨김). "지금은 주문 불가 시간"이 항상 보여 더 명확.
- 매수 후보 목록: 양쪽 비활성 시간대(15:20~15:30, 20:00 이후)에 NXT 종목도 후보에서 제외 (옵션 2 적용 — 실제 거래 영향 없음, 어차피 주문 차단).
- 매수/매도 동작: 체결 불가 시간대 주문 안 함 — 기존 토글 ON일 때와 동일 (사용자 체감 차이 없음).

**잔존 프로세스**: 없음 (백엔드 기동 후 종료, 런타임 검증만 수행).

**다음 세션 대기 사항**: 특별한 대기 사항 없음. 필요 시 다음 개선 작업 지시.

## 사용자 결정 변경 (이전 세션 기록 — 2026-07-23)

### 옵션 C → 대안 A (토글 제거) 결정 전환

**검토 배경**: 옵션 C(통합 게이트 방식) 상세 구현 계획 보고 전, 사용자 제기 — "SectorFlow는 시장가 주문만 사용하는데, 체결 불가 시간대에 주문을 넣어도 체결이 안 되면 `order_time_guard_on` 토글 자체가 무의미하지 않은가? ON/OFF와 관계없이 무조건 차단하는 게 더 단순하고 명확하지 않은가?"

**검토 결과 (코드 수정 없음)**:
- 시장가 단일 운용 확인 (trading.py:360-363 매수, 561-568 매도 — `trde_tp="3"`, `order_type="시장가"`, 지정가 경로 없음).
- 체결 불가 시간대 시장가 체결 불가 — 코드 주석에 명시.
- 토글 OFF의 유일한 효과 = 미체결 주문 적체 + 불필요한 API 호출/에러 로그. 사용자 이득 없음.
- 결론: 토글 제거가 P24(단순성)/P10(SSOT)에 부합.

**사용자 결정: 대안 A (토글 제거) + 옵션 2 (buy_order_executor.py 교체)**:
- 6세션에 걸쳐 사용자가 직접 설계한 토글이나, 시장가 단일 운용에서 무의미하다는 검토에 동의.
- 설정 페이지 토글 제거 승인.
- DB row 제거 승인 — 기동 시 자동 정리(idempotent DELETE) 방식.
- 옵션 2 선택: buy_order_executor.py의 is_krx_after_hours() → is_order_blocked_by_time() 교체 (P23 일관성 + is_krx_after_hours() dead code 제거).

**구현 완료**: 위 "직전 완료 작업" 섹션 참조.

## 직전 완료 작업 (이전 세션)

### 주문 일시중단 배지 문구/표시 로직 정비 (2026-07-22)

**세션**: 헤더 "주문 일시중단" 배지 UI/UX 개선. P21/P16/P23. "NXT 전용 구간 (KRX 단독 종목 차단)" 문구의 모호성 해소 및 설정 OFF 시 배지 숨김.

**문제 현상**: 배지 문구 "주문 일시중단(NXT 전용 구간 (KRX 단독 종목 차단))"이 KRX 단독 종목만 차단하는지, NXT/KRX 모든 종목이 일시중단인지 명확하지 않았음. 또한 "체결 불가 시간대 주문 차단" 설정이 OFF인데도 배지가 계속 표시되어 실제 차단 상태와 불일치 (P16 살아있는 경로).

**수정 파일 4개**:
- `backend/app/services/daily_time_scheduler.py` — `get_order_time_block_status()`에서 `order_time_guard_on` OFF 시 `(False, "")` 반환. reason을 `"KRX 단독 종목 차단 · NXT 가능"` / `"KRX·NXT 모두 주문 불가"`로 변경.
- `backend/app/services/engine_service.py` — `apply_settings_change()`에 `_apply_order_time_guard_change()` 추가. `order_time_guard_on` 토글 변경 시 `order_time_blocked` 웹소켓 이벤트 즉시 브로드캐스트.
- `frontend/src/layout/header.ts` — 배지 텍스트를 `⏸ ${reason}`으로 변경. 중복/모호한 `주문 일시중단(` 접두사 제거.
- `backend/tests/test_daily_time_scheduler.py` — 새 reason 및 `order_time_guard_on=OFF` 케이스 테스트 추가/갱신.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 배지문구 | P21/P23 | KRX/NXT 각각 주문 가능 여부를 배지 문구만 보고도 파악 가능. KRX 단독 종목 차단 / NXT 가능, 또는 KRX·NXT 모두 주문 불가로 명시. |
| 배지숨김 | P16 | `order_time_guard_on` OFF 시 `get_order_time_block_status()`가 `(False, "")`를 반환하여 배지를 표시하지 않음. 실제 주문 게이트(`trading.py::_is_order_time_blocked`)와 동일한 설정 기준 적용. |

**검증**: `pytest backend/tests/` 2792 passed. `python -W error::RuntimeWarning main.py` 런타임 기동 15초+ RuntimeWarning 없음. `npm run typecheck`/`npm run build` 정상. 잔존 프로세스 0건.

**화면 영향**:
- NXT-only 시간대(예: 08:00~09:00, 15:40~20:00): `⏸ KRX 단독 종목 차단 · NXT 가능` 표시.
- KRX·NXT 모두 비활성 시간대(예: 15:20~15:30, 20:00 이후): `⏸ KRX·NXT 모두 주문 불가` 표시.
- "체결 불가 시간대 주문 차단" 설정 OFF: 배지 완전히 숨김. **[참고: 다음 세션 대안 A로 토글 제거 예정 — 이 동작은 사라짐]**

**잔존 프로세스**: 없음 (백엔드 기동 후 종료, 런타임 검증만 수행).

**다음 세션 대기 사항**: 특별한 대기 사항 없음 (대안 A 토글 제거는 다음 섹션에서 완료됨).

## 직전 완료 작업 (이전 세션)

### 상단 헤더 인디케이터 순서 재배치 — KRX/NXT 장 상태 칩 좌측 이동 (2026-07-22)

**세션**: 프론트엔드 헤더 UI 개선. P21/P23/P24. 단순 순서 변경 (로직 변경 없음).

**문제 현상**: 상단 헤더의 KRX/NXT 장 상태 칩이 증권사 칩(키움증권/키움실시간) 우측에 배치되어 있었음. KRX/NXT 칩은 장 페이즈명(`KRX 정규장`, `NXT 시간외 종가매매 종료 + 시간외 단일가매매 개시` 등)과 카운트다운(`KRX 정규장 30분 전`) 표시로 인해 가로 너비 변동이 가장 큰 칩. 이 칩이 중간에 있으면 우측의 모든 칩(증권사·설정·업종지수)이 좌우로 밀려 화면이 흔들리는 느낌 발생.

**수정 파일 1개**:
- `frontend/src/layout/header.ts:266-300` — 칩 생성 블록 순서 재배치. KRX/NXT 장 상태 칩과 KRX 알림 칩(서킷브레이커/사이드카)을 증권사 칩 블록 앞으로 이동. avgAmtChip(백그라운드 데이터 갱신)은 KRX/NXT 우측, 증권사 칩 좌측에 배치. modeChip의 `marginRight:auto` 유지 (좌·우 분할점 역할).

**변경 전 (좌→우)**: 로고 · 투자모드 ┃ 데이터갱신 · 키움증권 · 키움실시간 · KRX · NXT · KRX알림 · (이하 동일)
**변경 후 (좌→우)**: 로고 · 투자모드 ┃ KRX · NXT · KRX알림 · 데이터갱신 · 키움증권 · 키움실시간 · (이하 동일)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 헤더재배치 | P21/P23/P24 | KRX/NXT 장 상태 칩을 인디케이터 가장 좌측으로 이동. 가로 너비 변동이 큰 칩이 좌측에서 흡수되어 우측 칩들 위치 안정. 장 운영 상태(거래 가능 여부)가 가장 먼저 보이도록 정보 우선순위 정렬. KRX 알림 칩을 KRX/NXT와 함께 묶어 장 상태 그룹 응집성 향상. |

**검증**: `npm run typecheck` exit 0. `npm run build` exit 0 (763ms). 브라우저 확인 — 개발 서버(5173) 실행 중, KRX/NXT 칩이 키움증권 칩 왼쪽에 배치됨 확인 필요.

**화면 영향**: 상단 헤더 인디케이터 순서 변경. KRX/NXT 칩이 가장 좌측(투자모드 칩 우측 영역의 시작점)에 표시. 장 페이즈/카운트다운 변동 시 우측 칩들이 더 이상 좌우로 밀리지 않음.

**잔존 프로세스**: 없음 (프론트엔드 빌드만 수행, 런타임 기동 없음).

**다음 세션 대기 사항**: 없음. 신규 작업 대기.

## 직전 완료 작업 (이전 세션)

### 단계 B-연계: 프론트엔드 수익률 분모 buy_total_amt 동기화 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 B-연계 (프론트엔드). P22/P23/P21 해결. **수익률 SSOT/P22 일괄 정비 전체 완료 (단계 A·C·B-사전·B-본·B-연계 5세션).**

**문제 현상**: 단계 B-본에서 백엔드 per-trade realized_pnl을 현금 기준(`total_amt - buy_total_amt`)으로 전환. 분자(realized_pnl)는 sellHistory에서 그대로 읽어 자동 동기화되었으나, 프론트엔드 수익률 분모가 `avg_buy_price * qty`(수수료 미포함)로 백엔드 `buy_total_amt`(수수료 포함)와 불일치 (P22 위반).

**수정 파일 2개 (4곳)**:
- `frontend/src/pages/profit-detail-display.ts:149-150` — updateStatistics 가중평균 수익률 분모 `avg_buy_price * qty` → `buy_total_amt`. 주석 "백엔드 현금 기준 buy_total_amt 분모" 갱신.
- `frontend/src/pages/profit-shared.ts:175` — buildSectorDonutRows 업종별 분모 `avg_buy_price * qty` → `buy_total_amt`.
- `frontend/src/pages/profit-shared.ts:205` — buildSectorStockPnl 종목별 분모 `avg_buy_price * qty` → `buy_total_amt`.
- `frontend/src/pages/profit-shared.ts:295` — aggregatePnl 범위 손익 분모 `avg_buy_price * qty` → `buy_total_amt`.

**자동 동기화 (수정 불필요)**: `canvas-sector-donut.ts:202` — buildSectorDonutRows 출력의 `buyTotal` 필드 사용으로 #2 수정 시 자동 동기화.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| B-연계 | P22/P23/P21 | 프론트엔드 수익률 분모 4곳을 백엔드 현금 기준 buy_total_amt로 동기화. 분자(realized_pnl)는 B-본에서 이미 동기화. 백엔드/프론트엔드 공식 완전 일치. |

**검증**: `npm run typecheck` exit 0. `npm run build` exit 0 (2.02s, 76 modules). `npx vitest run` 8 files / 116 tests passed (7.58s). 프론트엔드 테스트는 buildSectorDonutRows/buildSectorStockPnl/aggregatePnl/updateStatistics 직접 커버 테스트 없음 (기존 테스트 영향 없음).

**화면 영향 (테스트모드)**: 수익현황/수익상세 페이지의 업종별 수익률·종목별 수익률·범위 손익 수익률·가중평균 수익률이 **테스트모드에서 약간 낮게** 표시됨 (분모에 매수 수수료 포함으로 분모 증가, 수익률 절대값 미세 감소). **실전모드는 수수료/세금이 0이므로 화면 수치 변화 없음.**

**잔존 프로세스**: 없음 (프론트엔드 빌드/테스트만 수행, 런타임 기동 없음).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 B-연계 섹션(5.2~5.5) 체크리스트 [x] 표시 + 섹션 6 전체 완료 조건 [x] 표시. (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**수익률 SSOT/P22 일괄 정비 전체 완료**:
| 단계 | 세션 | 위반 | 내용 |
|------|------|------|------|
| A | 1 | P10/P22/P21 | buildMonthlyDrilldown이 백엔드 dailySummary 직접 사용 (sellHistory 재집계 제거) |
| C | 2 | P22/P23/P10/P24 | computeWeightedRate 공통 함수 신설 + 7곳 호출부 통일 |
| B-사전 | 3 | P22/P18 | DB 백업 + 마이그레이션 방식 확정 |
| B-본 | 4 | P22/P21/P18/P10 | per-trade realized_pnl/pnl_rate 현금 기준 전환 + 마이그레이션 |
| B-연계 | 5 | P22/P23/P21 | 프론트엔드 분모 buy_total_amt 동기화 |

**다음 세션 대기 사항**: 없음 (일괄 정비 완료). 신규 작업 대기.

## 직전 완료 작업 (이전 세션)

### 단계 B-본: per-trade realized_pnl/pnl_rate 현금 기준 전환 + 마이그레이션 실행 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 B-본 (백엔드/DB). P22/P21/P18/P10 해결. 핵심 로직 변경(규칙 0-4/0-5) — UI 기준 변경 전/후 설명 + 사용자 승인 완료.

**문제 현상**: per-trade realized_pnl/pnl_rate가 순수 차익 기준(`(price - avg_buy_price) * qty`)으로 계산되나, get_total_realized_pnl(합계)은 현금 기준(`total_amt - buy_total_amt`) 사용. 같은 "실현손익"이 두 기준으로 혼재 (P22 위반). 순수 차익은 수수료/세금 미반영으로 실제 체감 수익률과 불일치 (P21 위반).

**수정 파일 3개 + 신규 1개**:
- `backend/app/services/trade_history.py:352-368` — record_sell의 realized_pnl/pnl_rate 공식 현금 기준 전환. `realized_pnl = sell_net - buy_total` (매도 실수령 - 매수 실지출, 수수료/세금 포함). `pnl_rate = round(realized_pnl / buy_total * 100, 2)`. `buy_principal` 변수 제거 (P24 단순성). 주석 "순수 차익" → "현금 기준 실현손익" 갱신.
- `backend/app/services/trade_history.py:517-518` — get_daily_summary의 buy_total 집계를 `avg_buy_price * qty` → `buy_total_amt` 로 변경 (수수료 포함, per-trade와 동일 기준).
- `backend/app/services/trade_history.py:647-650` — build_positions_from_trades docstring "순수 차익" → "현금 기준" 갱신.
- `backend/scripts/migrate_realized_pnl_cash.py` (신규) — trades 테이블 SELL 레코드 현금 기준 마이그레이션 스크립트. 조건: `side='SELL' AND avg_buy_price > 0 AND buy_total_amt > 0`. `realized_pnl = total_amt - buy_total_amt`, `pnl_rate = round(realized_pnl / buy_total_amt * 100, 2)`. idempotent, 스키마 변경 없음, 모드 무관 (P18). 실행 결과: 대상 0건 (현재 SELL 레코드 없음) → 갱신 없음. 향후 매도 시 현금 기준 적용.

**테스트 갱신**: `backend/tests/test_trade_history.py` — `_make_sell_rec` 헬퍼(270-282) + `test_daily_summary_no_duplicate_buy_total`(55-100) + `test_daily_summary_fee_tax_aggregation`(151-202) 주입 데이터 현금 기준으로 갱신.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| B-본 | P22/P21/P18/P10 | per-trade realized_pnl/pnl_rate를 현금 기준으로 전환. get_total_realized_pnl과 동일 기준 단일화. 실전/테스트 모드 동등 (실전은 fee/tax=0이므로 영향 없음). 마이그레이션 스크립트로 과거 데이터 일치 확보 (현재 0건). |

**검증**: `python -m py_compile` 성공. `pytest backend/tests/test_trade_history.py` 64 passed. `pytest backend/tests/` 2790 passed. `python -W error::RuntimeWarning main.py` 런타임 기동 — 앱 시작 완료, RuntimeWarning 에러 없음, 매수 0건/매도 0건 정상 로드.

**화면 영향 (테스트모드)**: 수익현황/수익상세 페이지의 실현손익(원)과 수익률(%)이 **테스트모드에서 더 낮게** 표시됨 (수수료/세금 반영). 예: 7만원 매수→6.9만원 매도 시 기존 −10,000원/−1.43% → 변경 후 −11,589원/−1.66%. **실전모드는 수수료/세금이 0이므로 화면 수치 변화 없음.** 일별 요약 수익률도 현금 기준으로 일관. 프론트엔드 분모 동기화는 단계 B-연계(세션 5)에서 처리.

**잔존 프로세스**: 없음 (백엔드 기동 후 종료, 런타임 검증만 수행).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 B-본 섹션(4.2~4.5) 체크리스트 [x] 표시 — 사전조사 항목·수정 체크리스트·검증·완료조건 모두 완료. (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**다음 세션 대기 사항**:
1. **단계 B-연계 실행 시작 승인** — 프론트엔드 공식 동기화 + 테스트 갱신 (프론트엔드/테스트). tasks.md 섹션 5 기반. 사전조사 항목: 프론트엔드가 sellHistory의 `realized_pnl`/`avg_buy_price`/`qty`를 사용하는 집계 지점, 분모를 `buy_total_amt`(수수료 포함)로 변경 필요 여부 확인. UI 수치 변화(테스트모드 수익률 낮아짐) 사전 안내 포함 (P21).

## 직전 완료 작업 (이전 세션)

### 단계 B-사전: DB 백업 + 마이그레이션 스크립트 설계 확정 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 B-사전 (백엔드/DB 사전 준비). 코드 수정 없음 (DB 백업 + 설계 보고만). P22/P18 준비.

**문제 현상**: 단계 B-본에서 per-trade realized_pnl/pnl_rate 공식을 현금 기준(수수료/세금 포함)으로 전환 예정. 이때 기존 trades 테이블 레코드가 순수 차익 기준으로 남아 과거/현재 데이터 불일치(P22 위반) 발생. 본 세션은 사전 준비(백업 + 마이그레이션 방식 확정).

**수행 작업** (코드 수정 없음):
- DB 백업 (db-backup 스킬): `stocks.db.20260722_230709.backup` (1.2M), `stocks.db-shm.20260722_230709.backup` (32K), `stocks.db-wal.20260722_230709.backup` (0B). 백엔드 미실행 상태에서 안전 백업.
- 사전조사 (규칙 0-2): trades 테이블 SELL 레코드 **0건** 확인. test_positions 3건은 평가손익 필드(pnl_amount/pnl_rate)이며 realized_pnl/buy_total_amt 없음 → 마이그레이션 대상 아님. trades 스키마(stock_tables.py:22-43)에 realized_pnl/pnl_rate/buy_total_amt 필드 모두 존재 → 스키마 변경 불필요.
- 마이그레이션 스크립트 설계 (옵션 2, 사용자 설계 승인 2026-07-22):
  - 대상: `trades` SELL 레코드 전체 (현재 0건, 향후 매도 발생 시 대상)
  - 조건: `side='SELL' AND avg_buy_price > 0 AND buy_total_amt > 0` (유령 데이터/0매입 제외, trade_history.py:340 안전장치와 동일 기준)
  - `realized_pnl = total_amt - buy_total_amt` (현금 기준)
  - `pnl_rate = round(realized_pnl / buy_total_amt * 100, 2)`
  - UPDATE 1건 (트랜잭션 단위), idempotent(멱등), 스키마 변경 없음, 모드 무관(P18)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| B-사전 | P22/P18 (준비) | DB 백업 + 마이그레이션 방식 확정으로 단계 B-본 실행 준비 완료. 과거/현재 데이터 기준 일치 기반 마련. |

**검증**: 코드 수정 없음. DB 백업 파일 3개 존재 확인. 마이그레이션 설계 사용자 승인 확보.

**화면 영향**: 없음. DB 백업 + 설계 보고만 수행.

**잔존 프로세스**: 없음 (DB 백업 + 문서 갱신만, 백엔드 기동 없음).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 B-사전 섹션(3.2~3.5) 체크리스트 [x] 표시 — 사전조사 항목·수정 체크리스트·검증·완료조건 모두 완료. (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**다음 세션 대기 사항**:
1. **단계 B-본 실행 시작 승인** — per-trade realized_pnl/pnl_rate 공식 현금 기준 전환 + 마이그레이션 실행 (백엔드/DB). 사용자 지시 순서: (1) per-trade 생성 공식 현금 기준 변경 → (2) 마이그레이션 스크립트 실행 → (3) 검증. 핵심 로직 변경이므로 규칙 0-4/0-5 적용 — UI 기준 변경 전/후 설명 + 승인 필수.

## 직전 완료 작업 (이전 세션)

### 단계 C: 공통 함수 computeWeightedRate 신설 + 7곳 호출부 통일 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 C (프론트엔드 단독). P22/P23/P10/P24 해결.

**문제 현상**: 동일한 수익률 공식(`Math.round(pnl / buyTotal * 10000) / 100`, 소수 2자리 반올림)이 프론트엔드 7곳에서 독립 구현. 한쪽 공식 변경 시 타측 불일치 위험 (P22/P23 위반). 작업 파일 예상 5곳에서 사전조사 결과 7곳으로 확정 (단계 A로 1곳 감소 + 조사로 3곳 추가 발견).

**수정 파일 4개**:
- `frontend/src/components/common/ui-styles.ts:90-96` — `computeWeightedRate(pnl, buyTotal): number` 공통 함수 신설. 구현: `buyTotal > 0 ? Math.round(pnl / buyTotal * 10000) / 100 : 0`. `fmtRate`/`pnlColor`/`rateColor` 등 동일 성격 공통 함수군 옆에 배치. profit-shared.ts ↔ canvas-sector-donut.ts 순환 참조 방지 (두 파일 모두 ui-styles.ts를 이미 import 중).
- `frontend/src/pages/profit-shared.ts:4,179-187,222-226,242-245,297-299,365-368` — import 라인에 `computeWeightedRate` 추가. 5곳 치환: buildSectorDonutRows(업종별 도넛 행 수익률), buildSectorStockPnl(종목별 수익률 + 업종 합계 수익률), aggregatePnl(범위 손익 집계 수익률), computeHoldingsSummary(보유종목 평가손익 수익률).
- `frontend/src/pages/profit-detail-display.ts:6,149-151` — import 라인에 `computeWeightedRate` 추가. updateStatistics의 가중평균 수익률 1곳 치환.
- `frontend/src/components/canvas-sector-donut.ts:8,203` — import 라인에 `computeWeightedRate` 추가. 도넛 차트 중앙 "누적 수익률" 1곳 치환.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| C | P22/P23/P10/P24 | 수익률 가중 평균 공식을 ui-styles.ts 1곳에서 정의. 7곳 호출부가 모두 공통 함수 사용. 백엔드 공식 변경 시(단계 B) 프론트엔드 동기화 지점 1곳 집중. |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.99s exit 0, `npx vitest run` 8 files / 116 tests passed (8.07s). 공식 동일하므로 화면 수치 변화 없음.

**화면 영향**: 없음. 모든 화면의 수익률(%) 수치가 그대로 표시. 공식을 하나로 모았을 뿐 계산 결과 동일.

**잔존 프로세스**: 없음 (프론트엔드 typecheck/build/vitest만 수행, 백엔드 기동 없음).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 C 섹션을 5곳 → 7곳 실제 내역으로 갱신 (사전조사 항목·체크리스트·검증·완료조건 모두 [x] 표시). (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**다음 세션 대기 사항**:
1. **단계 B-사전 실행 시작 승인** — DB 백업 + 마이그레이션 방식 확정 (백엔드/DB). tasks.md 섹션 3 기반.
2. **마이그레이션 방식 결정 완료**: **옵션 2(1회 스크립트 실행)** 로 확정 (사용자 결정 2026-07-22). 기동 시 재계산(옵션 1)은 기각. 단계 B-사전 세션에서 DB 백업 후 1회 마이그레이션 스크립트 설계·실행.

## 직전 완료 작업 (이전 세션)

### 단계 A: buildMonthlyDrilldown SSOT 위반 해결 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 A (프론트엔드 단독). P10/P22/P21 해결.

**문제 현상**: 수익상세 페이지 "당월 일별 요약" 드릴다운이 백엔드 `dailySummary`의 per-day 수익률을 무시하고 sellHistory 원시 레코드에서 수익률을 재계산. 백엔드 공식 변경 시 드릴다운만 다른 수치 표시 위험 (P10/P22/P21 위반).

**수정 파일 4개**:
- `frontend/src/pages/profit-shared.ts:34-41,302-320` — `DailyDrilldownRow`에서 `buyTotal` 필드 제거 (표시되지 않는 dead data, P16). `buildMonthlyDrilldown` 시그니처 변경: `(sells, buys, yearMonth)` → `(dailySummary, yearMonth)`. dailySummary에서 `yearMonth` 접두사 필터 후 백엔드 per-day rate(`pnl_rate`) 직접 사용, 재계산 제거. `buildChartFromDailySummary`와 동일한 dailySummary 직접 사용 패턴 (P23 일관성).
- `frontend/src/pages/profit-detail-display.ts:19-21,106` — `hotStore` import 추가. `showDrilldown` 호출부를 `buildMonthlyDrilldown(state.sellHistory, state.buyHistory, yearMonth)` → `buildMonthlyDrilldown(hotStore.getState().dailySummary, yearMonth)`로 갱신.
- `frontend/src/pages/profit-detail-mount.ts:9-16,250-269,290-300` — `globalSettingsManager` import 추가. `ensureMonthlyDailySummary` 비동기 헬퍼 신설: mount 시 당월 범위(monthStart~today) dailySummary 조회 후 `hotStore.setState({ dailySummary: data })`. 수익현황 페이지의 `applyDateRange`와 동일한 `api.getDailySummary` + `hotStore.setState` 패턴 (P23). `flushDirtyRender`의 `dirtySummary` 분기에 드릴다운 갱신 추가 (dailySummary 기반이므로 summary 변경 시 드릴다운도 갱신).
- `frontend/src/pages/profit-detail.ts:19-28,147` — `ensureMonthlyDailySummary` import 추가. mount에서 `restoreInitialView` 후 `ensureMonthlyDailySummary(state, todayStr)` 호출.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| A | P10/P22/P21 | 드릴다운 per-day 수익률을 백엔드 dailySummary에서 직접 사용. 프론트엔드 재계산 제거. 수익현황에서 "당일"/"5일" 선택 후 진입해도 드릴다운은 항상 당월 전체 표시 (mount 시 당월 dailySummary 재조회). |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.86s exit 0, `npx vitest run` 8 files / 116 tests passed (9.25s).

**화면 영향**: 수익상세 페이지 "당월 일별 요약" 드릴다운의 수익률(%) 수치가 백엔드 기준값으로 표시. 기존 프론트엔드 재계산값에서 백엔드 dailySummary 값으로 변경. 표시 날짜 범위는 당월 전체로 유지 (수익현황에서 다른 범위 선택 후 진입해도 당월 전체 표시). 매도건수/매수건수/당일손익 수치는 동일 데이터 소스이므로 변화 없음.

**잔존 프로세스**: 없음 (프론트엔드 typecheck/build/vitest만 수행, 백엔드 기동 없음).

**다음 세션 대기 사항** (단계 C 완료로 갱신):
1. **단계 B-사전 전 마이그레이션 방식 사전 결정** — 옵션 1(기동 시 재계산) vs 옵션 2(1회 스크립트 실행). 단계 B-사전 세션 전까지 확정 필요.
2. **단계 B-사전 실행 시작 승인** — DB 백업 + 마이그레이션 방식 확정 (백엔드/DB). tasks.md 섹션 3 기반.

## 직전 완료 작업 (이전 세션)

### 수익률 계산 SSOT/P22 일괄 정비 — 설계 문서 + 작업 파일 작성 (2026-07-22)

**세션**: 다단계 작업 워크플로우 1단계(설계). 코드 수정 없음 (문서 2개 신규 작성).

**배경**: 이전 세션에서 수익상세 페이지 "수익률" 공식 불일치 해결(가중 평균 통일) 후, 심층 조사로 pnl_rate 계산 분산 3개 문제 식별. 본 세션은 설계 단계만 수행 (규칙 0-1 세션당 1단계).

**신규 파일 2개** (삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제):
- `docs/pnl_rate_ssot_design.md` — 문제 정의(A/B/C), 해결 방향, 영향 범위, 원칙 준수 매핑, 위험/주의사항. 사용자 결정: 문제 B는 B-2(수수료/세금 포함 현금 기준 진짜 수익률)로 확정.
- `docs/pnl_rate_ssot_tasks.md` — 5세션 단계별 체크리스트(A → C → B-사전 → B-본 → B-연계). 사전조사/수정/검증/완료조건 포함.

**식별된 3개 문제**:
| ID | 위반 | 설명 |
|----|------|------|
| A | P10/P22/P21 | `buildMonthlyDrilldown`(profit-shared.ts:332)가 백엔드 dailySummary 무시하고 per-day rate 재계산. 백엔드가 이미 제공하므로 SSOT 위반. |
| B | P22/P21/P18 | pnl_rate가 수수료/세금 미포함(순수 차익). 테스트모드에서만 실제 수익률 과대 표시 → 모드 동등성 위반. 사용자 결정: B-2(현금 기준 통일)로 해결. |
| C | P22/P23 | 동일 pnl_rate 공식이 7곳에서 독립 구현. 공통 함수 computeWeightedRate 신설로 변경 지점 1곳 집중. |

**사용자 결정 사항**:
- 문제 B 해결 방향: **B-2**(수수료/세금 포함 현금 기준 진짜 수익률) 확정. B-1(용어 명확화)은 기각.
- 실행 순서: A → C → B 그대로 유지.

**다음 세션 대기 사항**:
1. **단계 A 실행 시작 승인** — buildMonthlyDrilldown SSOT 위반 해결 (프론트엔드 단독).
2. **단계 B-사전 전 마이그레이션 방식 사전 결정** — 옵션 1(기동 시 재계산) vs 옵션 2(1회 스크립트 실행). 단계 B-사전 세션 전까지 확정 필요.

**검증**: 코드 수정 없음 (문서만 작성). 설계 문서와 작업 파일 간 단계 분할·체크리스트·원칙 매핑 일치 확인.

**화면 영향**: 없음. 문서 작성만 수행.

**잔존 프로세스**: 없음. 다음 세션에서 단계 A 실행 시작 (tasks.md 섹션 1 기반).

## 직전 완료 작업 (이전 세션)

### 수익상세 페이지 통계 "평균 수익률" 가중 평균 통일 (2026-07-22)

**세션**: P22/P21 데이터 정합성 해결 1단계. 수익상세 페이지 내 "수익률" 용어 공식 불일치 해소.

**문제 현상**: 수익상세 페이지에서 같은 기간(당일)을 보고 있는데 두 카드의 수익률이 다르게 표시됨.
- 좌측상단 "당일 손익" 카드: 백엔드 일별 요약 `pnl_rate` = `realized_pnl / buy_total × 100` (금액 기준 가중 평균)
- 우측하단 "평균 수익률" 통계: `sum(건별 pnl_rate) / sellCount` (건수 기준 단순 산술 평균)
- 매도 건들의 매입금액이 서로 다르기 때문에 두 공식 결과가 항상 상이 → 사용자 혼란 (P21 위반), 같은 "수익률" 용어를 두 공식으로 혼용 (P22 위반).

**수정 파일 2개**:
- `frontend/src/pages/profit-detail-display.ts:148` — `avgRate` 계산식을 단순 산술 평균에서 가중 평균으로 변경. `buyTotal = sum(avg_buy_price × qty)`, `avgRate = pnl / buyTotal × 100` (소수 2자리 반올림). 좌측상단 카드가 사용하는 백엔드 공식(`backend/app/services/trade_history.py:527`)과 동일.
- `frontend/src/pages/profit-detail-mount.ts:183,189` — 통계 라벨 "평균 수익률" → "수익률"로 변경 (단순 평균 연상 방지). 주석도 동일 갱신.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 수익률 공식 통일 | P22/P21 | 수익상세 페이지 내 "수익률" 표시를 단일 공식(금액 기준 가중 평균)으로 통일. 좌측상단 카드와 우측하단 통계가 동일 기간에서 동일 수치 표시. |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.18s exit 0.

**화면 영향**: 수익상세 페이지 우측하단 통계의 "수익률" 수치가 변경됨. 기존 단순 평균 → 가중 평균. 좌측상단 "당일 손익" 카드의 %와 동일한 값으로 표시됨. 사용자가 "왜 두 수치가 다르지?" 혼란 해소.

**잔존 프로세스**: 없음 (프론트엔드 typecheck/build만 수행, 백엔드 기동 없음).

## 직전 완료 작업 (이전 세션)

### 문서 정리: audit 문서 최신화 + HANDOVER 미해결 문제 취소선 처리 (2026-07-22)

**세션**: 문서 정리 1단계. 코드 수정 없음 (문서만 업데이트).

**수정 파일 3개**:
- `HANDOVER.md` (197-200줄): "프론트엔드 — 용어 통일 잔존 (F06-10 범위 밖)" 미해결 문제 섹션에 취소선 + 해결 표시 추가. F-06-d 세션에서 이미 해결된 항목들을 문서에 반영 (잔여 "보유주식" 0건).
- `docs/architecture_audit_plan.md` (6곳): F-05/F-06 세션 섹션 파일 표 + 체크리스트 ☐→☑ 완료 표시. F05-01 백엔드 #3 해결 내역 추가. F05-07 보류→해결 (F-06-c/d). F05-08 잔여→완료 (파일 분할 완료). 세션 상태 표 + 진행률 (완료 24→26, 진행중 1→0, 미시작 5→4, 보류 2→1).
- `docs/architecture_audit_tasks.md` (5곳): 세션 현황 표 F-05/F-06 ☐→☑. 진행률 F-05/F-06/백엔드 #3 완료 반영. "잔여 6세션" → "잔여 4세션". F-05/F-06 세션 섹션 파일 [ ]→[x] + 체크리스트 [ ]→[x] + 검증 [ ]→[x].

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 문서 정리 | P21/P23 | audit 문서 2개가 구 버전 상태로 F-05/F-06을 미시작/진행중으로 표시 + HANDOVER 미해결 문제 섹션에 해결된 항목 취소선 누락. 실제 코드 상태(HANDOVER 최신)와 문서 불일치 해결. 잔여 보류 항목(B-13 5건, B21-01, F-03 4건, F-04 파일 분할, F-07)은 명확히 분리하여 추적 정보 보존. |

**검증**: 코드 수정 없음 (문서만 업데이트). 두 audit 파일 간 F-05/F-06 상태 일관성 확인 (모두 ☑ 완료, 진행률 수치 일치).

**화면 영향**: 없음. 문서 정리만 수행.

## 직전 완료 작업 (이전 세션)

### F-05-b: profit-detail.ts 파일 분할 (2026-07-22)

**세션**: F-05 (페이지 파일 분할) 1단계. P24 단순성 해결. F-05-a와 동일한 메인+re-export 패턴.

**수정 파일 4개**:
- `frontend/src/pages/profit-detail.ts` (메인): 674줄 → 166줄. `ProfitDetailState` 인터페이스 (모든 가변 상태를 단일 상태 객체로 관리 — P10 SSOT) + `createState()` 팩토리 + `mount`/`unmount` + `export default`. 분할 파일에서 사용하는 타입(`LowerTab`, `SelectedView`, `ProfitDetailState`) export. F-05-a 메인+re-export 패턴 준수.
- `frontend/src/pages/profit-detail-view.ts` (신규, 52줄): `PROFIT_DETAIL_VIEW_KEY`, `ProfitDetailViewState`, `loadProfitDetailView`, `saveProfitDetailView` 이관. 순수 이동.
- `frontend/src/pages/profit-detail-display.ts` (신규, 215줄): `applyCardStyle` + `updateStatCardSelection` + `updateCardSelection` + `updateDrilldownBtnStyle` + `setTabLabel` + `updateTabLabels` + `showDrilldown` + `filterByDate` + `filterByDateRange` + `updateStatistics` + `showTable` + `persistViewState` 이관. 모든 함수가 `state: ProfitDetailState` 인자를 받도록 시그니처만 변경, 로직 동일.
- `frontend/src/pages/profit-detail-mount.ts` (신규, 326줄): `buildSummaryRow` + `onDrilldownToggle` + `buildFilterRow` + `buildTabRow` + `buildTableContainer` + `buildStatRow` + `restoreInitialView` + `flushDirtyRender` + `subscribeProfitDetailStore` 이관. 모든 함수가 `state` 인자 사용.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F-05-b | P24 | profit-detail.ts 674줄 → 4개 파일 분할 (166/52/215/326줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (라우터 `./pages/profit-detail` 경로 + `export default { mount, unmount }` 시그니처). F-05-a 메인+re-export 패턴 준수 (상태 객체를 인자로 전달 — profit-overview 분할과 동일). |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.18s exit 0, `npx vitest run` 8 files / 116 tests passed (8.94s). 모든 파일 500줄 이하.

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 수익 상세 페이지의 모든 기능(요약 카드 당일/직전/당월/누적 손익, 드릴다운 당월 일별 요약, 매도/매수 탭, 날짜 범위 필터, 종목 검색, 통계 정보, 가상 스크롤 거래내역)이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-05-a: profit-overview.ts 파일 분할 + renderSectorStockPnl 함수 분할 (2026-07-22)

**세션**: F-05 (페이지 파일 분할) 1단계. P24 단순성 해결.

**수정 파일 4개**:
- `frontend/src/pages/profit-overview.ts` (메인): 742줄 → 175줄. `ProfitOverviewState` 인터페이스 (28개 가변 필드를 단일 상태 객체로 관리 — P10 SSOT) + `createState()` 팩토리 + `mount`/`unmount` + `export default`. 분할 파일에서 사용하는 타입을 export. F-06 메인+re-export 패턴 준수.
- `frontend/src/pages/profit-overview-date.ts` (신규, 62줄): `PROFIT_DATE_KEY`, `ProfitDateRange`, `loadProfitDateRange`, `saveProfitDateRange`, `defaultDateRange`, `initDateRange` 이관. 순수 이동.
- `frontend/src/pages/profit-overview-sector-pnl.ts` (신규, 219줄): `createAmountCell` (셀 헬퍼 — 헤더/행 공통, P23 일관성) + `createSectorHeader` (업종 헤더 5컬럼) + `createStockRow` (종목 행 5컬럼) + `renderSectorStockPnl` (orchestrator, 45줄 — 50줄 이하 달성) + `updateExpandToggleBtn` + `buildStockListSection` 이관. `renderSectorStockPnl` 146줄 → 5개 함수로 분할 (createAmountCell 25줄 + createSectorHeader 40줄 + createStockRow 35줄 + renderSectorStockPnl 45줄 + updateExpandToggleBtn 4줄).
- `frontend/src/pages/profit-overview-mount.ts` (신규, 377줄): `renderAccountVals`, `refreshFilteredViews`, `buildLeftColumn`, `buildAccountRows`, `buildAccountPanel`, `buildLowerSection`, `applyDateRange`, `buildProfitChart`, `buildDonutChart`, `flushRender`, `subscribeProfitOverviewStore` 이관. 순수 이동.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F-05-a | P24 | profit-overview.ts 742줄 → 4개 파일 분할 (175/62/219/377줄, 모두 500줄 이하). renderSectorStockPnl 146줄 → 5개 함수 분할 (최대 45줄, 모두 50줄 이하). 순수 이동(move) + 함수 분할만 수행, 동작 변경 없음. 외부 import 경로 유지 (라우터 `./pages/profit-overview` 경로 + `export default { mount, unmount }` 시그니처). F-06 메인+re-export 패턴 준수 (상태 객체를 인자로 전달 — data-table-fixed.ts의 options 인자 패턴과 동일). |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.73s exit 0, `npx vitest run` 8 files / 116 tests passed (8.09s). 모든 파일 500줄 이하, renderSectorStockPnl 45줄 (50줄 이하).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 수익현황 페이지의 모든 기능(일별 수익률 차트, 업종별 도넛 차트, 계좌 현황, 업종별 종목 수익, 전체보기 토글, 상세 분석 버튼)이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### 백엔드 #3: build_account_snapshot_meta accumulated_investment 누락 수정 (2026-07-22)

**세션**: 백엔드 정합성 버그 수정 1단계. P22 데이터 정합성 회복.

**수정 파일 2개**:
- `backend/app/services/engine_account_rest.py:131`: `build_account_snapshot_meta` 반환 dict에 `"accumulated_investment": account_snapshot.get("accumulated_investment")` 1줄 추가. 기존에 누락되어 호출부(engine_account.py:330)에서 `state.account_snapshot["accumulated_investment"]`를 set한 직후 반환 dict로 덮어쓰기(line 350)하면서 값이 사라지던 P22 위반 해결. 실전모드에서는 account_snapshot에 키가 없으므로 None 전달 (P20 폴백 금지 준수 — 0으로 덮지 않음).
- `backend/tests/test_engine_account_rest.py:288-302`: 새 테스트 2개 추가 — `test_accumulated_investment_passed_through` (테스트모드 값 전달 검증), `test_accumulated_investment_none_when_absent` (실전모드 None 전달 검증).

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 백엔드 #3 | P22 | `build_account_snapshot_meta`가 매번 새 dict 반환 시 `accumulated_investment` 키 누락. 호출부에서 set 후 덮어쓰기로 값 소실 → broadcast가 None 전송. 반환 dict에 키 추가로 단일 흐름 유지 (settlement_engine → state.account_snapshot → broadcast → 프론트엔드). |

**검증**: `py_compile` OK. `pytest test_engine_account_rest.py` 63/63 passed (새 테스트 2개 포함). `pytest test_engine_account.py + test_engine_account_notify.py + test_settlement_verification.py` 62/62 passed. 런타임 기동(`-W error::RuntimeWarning`) 정상 — 에러/Traceback/RuntimeWarning 없음, "누적투자금: 10,000,000원" 정상 로드. 잔존 프로세스 0건.

**화면 영향**: 현재 화면 변화 없음 (프론트엔드 F05-01이 `initial_deposit` 사용 중이며 테스트모드에서는 initial_deposit == accumulated_investment). 향후 프론트엔드가 `accumulated_investment` 직접 사용 시 정확한 누적 투자금 표시 가능.

## 직전 완료 작업 (이전 세션)

### F-06-g (F06-03): ui-styles.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-03 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/ui-styles.ts` (메인): 581줄 → 252줄. 상수(FONT_FAMILY/FONT_SIZE/FONT_WEIGHT/COLOR) + 색상함수(rateColor/pnlColor/strengthColor/hexToRgba) + 기호/포맷함수(changeArrow/fmtRate/fmtComma/fmtWon) + positionTooltip + CELL_BORDER/ROW_HEIGHT/ROW_HEIGHT_PX + 다크폼(createDarkInput/createDarkSelect) + 헬퍼(setDisabled/setDisplay) + `export * from` cells/columns re-export. ColumnDef/COLUMN_WIDTH import 제거 (columns 파일로 이동).
- `frontend/src/components/common/ui-styles-cells.ts` (신규, 211줄): createStockNameCell + applyCell(private 이동) + CELL_PADDING(private 이동) + createHeaderCell + 11개 createCell 함수 (Seq/Code/Price/Change/Rate/Amount/Strength/AvgAmount/Number/Pnl). 메인의 COLOR/FONT_*/rateColor/pnlColor/strengthColor/changeArrow/fmtComma/fmtRate import.
- `frontend/src/components/common/ui-styles-columns.ts` (신규, 148줄): 8개 makeColumn (Seq/Code/Price/Change/Rate/Strength/Amount/AvgAmount) + createStockNameColumn. data-table(ColumnDef) + table-config(COLUMN_WIDTH) + 메인(COLOR) + cells(create* 함수) import.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-03 | P24 | ui-styles.ts 581줄 → 3개 파일 분할 (252/211/148줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (41곳: 컴포넌트 18 + 페이지 14 + 레이아웃 3 + 기타 6). F-06-e(data-table)/F-06-f(setting-row)와 동일한 메인+re-export 패턴. |

**검증**: `npm run typecheck` exit 0, `npm run build` 735ms exit 0, `npx vitest run` 8 files / 116 tests passed (4.18s). 잔여 ui-styles-cells/columns 참조: 메인 re-export(2곳) + columns 내부 import(1곳)만 (외부 누출 없음).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 페이지의 테이블 셀·컬럼·다크폼이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-06-f (F06-02): setting-row.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-02 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/setting-row.ts` (메인): 569줄 → 168줄. 상수(INPUT_WIDTH, TEXT_INPUT_WIDTH) + 공통 유틸(focusNext, applyInputBase, createSpinButtons — inputs에서 import하도록 export 추가) + createSettingRow + createSettingField + createFixedValue + `export * from` inputs/controls re-export. 사용처가 controls로 이동한 setDisabled/FONT_SIZE import 제거.
- `frontend/src/components/common/setting-row-inputs.ts` (신규, 243줄): createNumInput, createMoneyInput, createTextInput, createSelect 이관. 메인의 유틸(focusNext, applyInputBase, createSpinButtons, TEXT_INPUT_WIDTH) import.
- `frontend/src/components/common/setting-row-controls.ts` (신규, 191줄): createToggleBtn, createRadioGroup, createToggleLabelControlsRow 이관. 메인의 createSettingRow + ui-styles(COLOR, FONT_SIZE, setDisabled) import.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-02 | P24 | setting-row.ts 569줄 → 3개 파일 분할 (168/243/191줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (4개 설정 페이지: general/sector/sell/buy-settings). F-06-e(data-table.ts)와 동일한 메인+re-export 패턴. |

**검증**: `npm run typecheck` exit 0, `npm run build` 982ms exit 0, `npx vitest run` 8 files / 116 tests passed (6.07s). 잔여 setting-row 참조: 메인 + inputs + controls(상호 import) + 4 설정 페이지(동일 경로 유지) + docs 역사적 로그.

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 설정 화면(일반/업종/매수/매도)의 입력란·토글·라디오·드롭다운이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-06-e (F06-01): data-table.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-01 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/data-table.ts` (메인): 1045줄 → 176줄. 타입/인터페이스 + 공통 유틸리티(triggerFlash, isGroupRow, scoreColor, createColumnWidthManager) + createDataTable 팩토리만 잔류. 유틸리티 함수에 export 추가 (모드 파일에서 import).
- `frontend/src/components/common/data-table-fixed.ts` (신규, 454줄): createFixedMode + CellWithPrevContent 이관.
- `frontend/src/components/common/data-table-virtual.ts` (신규, 454줄): createVirtualScrollMode + RowWithKey 이관.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-01 | P24 | data-table.ts 1045줄 → 3개 파일 분할 (176/454/454줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (9개 페이지 + ui-styles.ts + 테스트) |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.93s exit 0, `npx vitest run tests/components/data-table.ui.test.ts` 17/17 passed. 잔여 createFixedMode/createVirtualScrollMode 참조: 메인 + 각 모드 파일에서만 (외부 누출 없음).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 페이지가 동일하게 동작.

## 미해결 문제 (발견 즉시 기록)

### T2-S9 진행 중 발견 — B4-06-03 "감소 모드" 화면 명시 표시 미구현 (2026-07-23)
- **파일**: `backend/app/services/engine_loop.py:35`, `backend/app/services/engine_lifecycle.py:162` (get_engine_status), 프론트엔드 `frontend/src/binding.ts:244` (engine-ready 핸들러)
- **위반/부합 원칙**: P21 (사용자 투명성) 부분 충족 — 백엔드 log-and-rethrow로 engine_loop.py:35 "감소 모드로 기동" 에러 로그는 활성화되었으나, 화면에 "감소 모드" 상태를 명시적으로 표시하는 프론트엔드 경로 미구현.
- **증상**: 종목 마스터 DB가 비어있는 치명 상황에서 백엔드는 감소 모드로 기동하나, 사용자 화면에는 정상 기동과 동일하게 `engine-ready`만 표시됨. 사용자가 "왜 종목이 안 보이지?" 의문 가능.
- **수정 방향**: engine_loop.py:35 except 블록에서 `engine_state.state`에 감소 모드 플래그 설정 → get_engine_status() 반환값에 포함 → 프론트엔드 index-data 핸들러에서 UI 표시. 본 세션 백엔드 3건 범위 밖 — 프론트엔드 변경이 별도로 필요하므로 후속 세션에서 별도 승인 시 진행 권장.

### T1-S2 진행 중 발견 — virtual-scroller.ts renderRow 호출부 3곳 무보호 (2026-07-23)
- **파일**: `frontend/src/components/virtual-scroller.ts`
- **위반/부합 원칙**: P25 (격리된 실패) 위반 소지, P23 (일관성) — 같은 파일 내 renderRange 루프는 격리했으나 다음 3곳은 무보호 상태로 잔존:
  - `updateItems` 루프 내 renderRow 2곳 (444줄 existing 경로, 451줄 new 경로)
  - `updateItemByKey` 내 renderRow (468줄)
  - `updateItem` 내 renderRow (499줄)
- **증상**: 가상 스크롤 아이템 증분 갱신 시 한 행 renderRow throw → updateItems/updateItemByKey/updateItem 루프 중단. renderRange와 동일 패턴 적용 시 해결.
- **수정 범위**: 본 세션 계획은 A3-07-01이 `renderRange` 루프(293-316)만 명시하므로 미수정. 후속 세션에서 사용자 승인 시 동일 패턴 적용 권장 (P23 일관성).
- **참고**: `p25_fix_plan.md` A3-07-01 위치 명시가 `virtual-scroller.ts:293-316`으로 renderRange만 지칭. 전체 renderRow 호출부 확장 여부는 별도 승인 필요.

### T1-S2 진행 중 발견 — data-table-fixed.ts:290 셀 렌더 에러 로그 메시지 불일치 (2026-07-23)
- **파일**: `frontend/src/components/common/data-table-fixed.ts:290`
- **위반/부합 원칙**: P23 (일관성) — 사전 존재 불일치 (본 세션 수정 범위 아님).
- **증상**: `console.error('[data-table] cell render error:', err)` — 다른 4곳은 `console.error('[DataTable] cell render error', e)` (대소문자/콜론/변수명 불일치).
- **수정 방향**: 후속 세션에서 일관성 정비 시 통일 권장. 본 세션에서는 범위 외.

### P25 전수 조사 — 세션 8 (B5 매매·테스트모드 태스크) 위반 4건 식별 (2026-07-23)
- 조사 파일: `backend/app/services/trading.py`, `backend/app/services/buy_order_executor.py`, `backend/app/services/dry_run.py`
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` 섹션 2(매트릭스) + 섹션 10(세션 8 결과) 참조
- **B5-08-01 (LOW)**: `trading.py:477-482, 666-671` `asyncio.create_task` 직접 사용 + add_done_callback 수동 연결. `schedule_engine_task()`(engine_lifecycle.py:279-309)가 동일 기능 제공하는데 미사용 → **ARCHITECTURE.md 금지 패턴 2 위반 + P23 일관성 위반**. 기능적으로는 동등(엔진 루프 내 호출이므로 schedule_engine_task 두 번째 분기와 동일). 심각도 낮음
- **B5-08-02 (LOW)**: `trading.py:572-598` `execute_sell` 평균매입가 조회가 테스트/실전 분기됨 (`build_positions_from_trades` vs `get_positions`). 돈 I/O가 아닌 "조회" 분기로 **P18 "모드 분기는 돈 I/O 최소 지점에만" 엄격 해석상 미세 위반**. 결과 동일성은 보장되나 분기 위치 검토 대상
- **B5-08-03 (MEDIUM)**: `trading.py:477-482, 666-671` (연관 `dry_run.py:153-198`) `fake_fill_event` 태스크 실패/취소 시: 주문 접수는 `record_buy`/`record_sell`로 영속화되어 있으나, `fake_fill_event` 내부 `_apply_buy`/`_apply_sell`(Settlement Engine 예수금 차감/매도 정산) 누락 가능 → **P22 데이터 정합성 잠재 위험** (trade_history와 Settlement Engine 잔고 불일치). 단 `tests/test_settlement_verification.py` S4-1(207-260)에 재현 테스트 존재 → 인지된 영역. 기동 시 대조(reconciliation) 메커니즘 보유 여부는 세션 9 교차 점검 대상
- **B5-08-04 (LOW)**: `trading.py:204-210` 실시간 지연 체크 `except Exception:`이 로깅은 하되 체크 실패 시 매수를 차단하지 않고 계속 진행 → **P20/P25 관점에서 fail-closed(안전 차단)가 더 보수적** (현재는 게이트 우회 형태)
- 양호: P15 단일 주문 경로 완벽 준수, 매수/매도 실패 전파 양호 (사전 차감 롤백+서킷브레이커 강제 OFF+WS 브로드캐스트), buy_order_executor 예외 break+로깅, RiskManager 보고 실패 격리, safe-trade 스킬 연계 준수
- 수정은 별도 승인 세션에서 진행 (거래 로직 수정 시 safe-trade 스킬 필수, B5-08-02/03/04는 핵심 로직 변경이므로 AGENTS.md 섹션3 규칙 0-4/0-5 엄격 적용)

### P25 전수 조사 — 세션 5 (B3 대형 스케줄러·파이프라인) 위반 4건 식별 (2026-07-23)
- 조사 파일: `backend/app/services/daily_time_scheduler.py`, `backend/app/services/market_close_pipeline.py`, `backend/app/services/engine_lifecycle.py`(정의 확인용)
- **B3-05-01 (HIGH)**: `market_close_pipeline.py:645-650` `_save_confirmed_cache` inner except에서 rollback+warning 후 fall-through → 650 `return True` → 전종목 마스터 테이블 DB 저장 실패해도 함수 True 반환 → **P22 데이터 정합성 위반 + P21 사용자 투명성 위반**. 후속 6단계 메모리 교체 로직이 잘못된 성공 전제로 진행됨
- **B3-05-02 (MEDIUM)**: `market_close_pipeline.py:897` `_step5_download_daily_confirmed`에서 `confirmed = {}` 빈 폴백 → **P20 폴백 금지 위반**. if confirmed 가드로 메모리/DB는 보호되나, 빈 eligible_codes로 `_run_post_confirmed_pipeline` 실행 → 빈 캐시 저장 시도
- **B3-05-03 (LOW)**: `market_close_pipeline.py:492` `except (ValueError, TypeError): pass` silent pass → **P20 위반** (로깅 없음). float 변환 실패 시 strength_str 갱신 스킵만 하고 종목 루프 계속
- **B3-05-04 (LOW)**: exc_info 누락 11건 → **P23 일관성 위반**. `market_close_pipeline.py` 424, 858, 934, 1103, 1254 + `daily_time_scheduler.py` 1273, 1287, 1327, 1354, 1446, 1507. logger.warning은 하나 exc_info=True 누락. 단 934는 "(무시)" 표시로 의도적 일부 드러남
- 양호: schedule_engine_task 15회 호출 모두 P25 격리 준수(add_done_callback), call_later 3곳+call_soon_threadsafe 1곳 모두 보호, 45개 except 중 28개 logger.warning+exc_info=True 준수, RuntimeError→return 3건 의도적 스킵
- 수정은 별도 승인 세션에서 진행 (조사는 보고까지만)

### P25 전수 조사 — 세션 2 (B1 엔진 코어 루프) 위반 7건 식별 (2026-07-23)
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` 섹션 2(매트릭스) + 섹션 4(세션 2 결과) 참조
- **B1-02-01 (HIGH)**: `engine_loop.py:304` while 루프 본문 내 `is_ws_subscribe_window` 무보호. throw 시 엔진 루프 전체 종료
- **B1-02-02 (MEDIUM)**: `engine_loop.py:374,377` finally 블록 `disconnect_all()`/`disconnect()` 무보호. throw 시 후속 정리 스킵
- **B1-02-03 (MEDIUM)**: `engine_loop.py:387,389` finally 블록 REST 정리 루프 `_reset_client()`/`aclose()` 무보호. 한 증권사 실패 시 나머지 스킵
- **B1-02-04 (HIGH)**: `engine_loop.py:31` `_load_caches_preboot` 무보호. throw 시 엔진 기동 전체 차단
- **B1-02-05 (LOW)**: `engine_ws_dispatch.py:149-153` `_handle_real_00` 내 `on_fill_update`/`_on_fill_after_ws` 무보호. 호출자 의존 — 세션 3에서 확인
- **B1-02-06 (LOW)**: `engine_ws_dispatch.py:162` `_handle_real_balance` 내 `_apply_balance_realtime` 무보호. 호출자 의존 — 세션 3에서 확인
- **B1-02-07 (LOW)**: `engine_lifecycle.py:38` `_refresh_positions_if_dirty` 무보호. 주 호출자는 격리 있으나 engine_service.py:93 경유 시 미확인 — 세션 6에서 확인
- 수정은 별도 승인 세션에서 진행 (조사는 보고까지만)

### P25 전수 조사 — 세션 1 (A1 WS 디스패치) 위반 5건 식별 (2026-07-23)
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` 섹션 2(매트릭스) + 섹션 3(세션 1 결과) 참조
- **A1-01-01 (CRITICAL)**: `ws.ts:193` `_dispatchMessage` 핸들러별 try/catch 없음. 한 핸들러 throw 시 같은 이벤트 후속 핸들러 미실행 + 예외 상위 전파
- **A1-01-02 (CRITICAL)**: `ws.ts:164-174` `_handleBinaryFrame` 루프가 try 내부 → 한 핸들러 throw 시 같은 바이너리 프레임 나머지 이벤트 손실
- **A1-01-03 (MEDIUM)**: `ws.ts:172,181` catch 로그가 핸들러 예외를 "파싱 실패"로 잘못 분류
- **A1-01-04 (HIGH)**: `binding.ts` 33개 핸들러 내부 try/catch 없음. F-02 fix는 listener 루프만 보호, 핸들러 본문은 미보호
- **A1-01-05 (LOW)**: `ws.ts:132-136` 재연결 setTimeout 콜백 try/catch 없음
- 수정은 별도 승인 세션에서 진행 (조사는 보고까지만)

### 프론트엔드 — profit-overview 통계 카드 avgRate 공식 일치 여부 — 해결됨 (2026-07-23 조사)
- ~~`frontend/src/pages/profit-overview-mount.ts:57`가 `filteredSellHistory`를 사용하며, profit-overview 페이지에도 동일한 통계 카드(평균 수익률)가 있는지 확인 필요~~ → 해결 (조사 완료). profit-overview에는 평균 수익률 통계 카드 자체가 없음(avgRate/statAvgRate/updateSummaryCards 0건). profit-overview의 수익률 계산 3곳(도넛 차트/종목 행/업종 헤더) 모두 `computeWeightedRate(pnl, buy_total_amt)` 단일 공식 사용 — profit-detail의 avgRate와 동일. P22/P21 위반 잔존 없음.

### 백엔드 버그 (F-05-a 조사 중 발견) — 해결됨 (2026-07-22)
- ~~`backend/app/services/engine_account_rest.py:125-144` `build_account_snapshot_meta`가 응답 dict에서 `accumulated_investment`를 **누락**~~ → 해결 (백엔드 #3 세션에서 반환 dict에 키 추가).

## 다음 세션 작업

**Tier 2 (MEDIUM, 14건 / 5세션) — 진행 예정**:

| 세션 | 위반 ID | 파일 | 의존성 | safe-trade |
|------|---------|------|--------|------------|
| T2-S7 | A1-01-03, A2-04-01/02 | ws.ts, store.ts, hotStore.ts | T1-S1 완료 ✓ | 불필요 |
| T2-S8 | B1-02-02/03, B2-03-02 | engine_loop.py, pipeline_compute.py | T1-S2/S3 완료 ✓ | 불필요 |
| T2-S9 | B3-05-02, B4-06-01/03 | market_close_pipeline.py, db_writer.py, engine_cache.py | T1-S4 완료 ✓ | 불필요 |
| T2-S10 | A3-07-03/05/06/07 | data-table.ts, profit-overview-sector-pnl.ts, stock-classification.ts, profit-overview-mount.ts | T1-S5 완료 권장 ✓ | 불필요 |
| T2-S11 | B5-08-03 | trading.py, dry_run.py | 없음 | **필수** |

**다음 시작 세션**: T2-S7 (프론트엔드 — WS 로그 분류 / store updater / hotStore dispatch 격리)
- A1-01-03: 디코딩 catch와 핸들러 catch 분리 후 각각 목적에 맞는 로그 메시지
- A2-04-01: setState updater `partial(state)` try/catch, throw 시 `console.error` + 기존 state 반환
- A2-04-02: window.dispatchEvent CustomEvent per-dispatch try/catch (A2-04-01과 동일 패턴, P23)

**세션 시작 시 확인 사항**:
- 본 HANDOVER.md "직전 완료 작업" 파악
- `docs/p25_fix_tasks.md` 해당 세션 항목 확인
- 사전조사 4항목 수행 (규칙 0-2)
- 사용자 명시적 승인(실행 지시어) 수신 후 수정 착수

**audit 문서에 기록된 잔여 항목 (사용자 지시 시 진행)**:
- B-13 보류 5건 (B13-03/04/06/07/08, LOW/INFO 등급) — `docs/architecture_audit_plan.md` 섹션 7 참조
- B21-01 보류 (암호화 폴백, 사용자 승인 대기 — 보안 동작 변화, UI 기준 설명 필요)
- F-03 보류 4건 (F03-07/08/09/10) — `docs/architecture_audit_tasks.md` F-03 섹션 참조
- F-04 잔여 파일 분할 (stock-classification.ts 1618줄, general-settings.ts 1390줄)
- F-07 미시작 (타입 및 유틸 5개 파일, 총 651줄)

---

## 직전 완료 작업 (이전 세션)

### F-06-d (F06-10 잔존): 용어 통일 마무리 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-10 잔존 2곳 해결 (프로젝트 전역 용어 통일 종료).

**수정 파일 2개**:
- `frontend/src/pages/profit-overview.ts:347`: UI 텍스트 "보유주식 평가금액 (" → "보유 종목 평가금액 (" (F06-10 잔존)
- `frontend/src/pages/profit-shared.ts:426`: 주석 "보유주식 평가금액/평가손익/수익률" → "보유 종목 평가금액/평가손익/수익률" (F06-10 잔존)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-10 잔존 | P23 | F06-10에서 account-labels.ts + sell-position.ts 완료 후 남은 2곳. UI 텍스트 1곳 + 주석 1곳. "보유주식" → "보유 종목" (용어 사전 준수). 프로젝트 전역 "보유주식" 잔존 0건 달성 |

**검증**: `npm run build` 612ms exit 0. 잔여 "보유주식" grep (frontend 전역): 0건 확인.

**화면 영향**:
- 수익 요약 페이지 계좌 현황 표: "보유주식 평가금액 (N종목)" → "보유 종목 평가금액 (N종목)"으로 표시 변경

## 직전 완료 작업 (이전 세션)

### F-06-c (F06-10/11/12): 용어 통일 + 색상 상수화 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-10 (P23 용어), F06-11/12 (P23 색상 상수화) 해결.

**수정 파일 5개**:
- `frontend/src/components/common/ui-styles.ts`: `hexToRgba(hex, alpha)` 공통 헬퍼 추가 (P23 공통 자산 — toast.ts + 향후 재사용)
- `frontend/src/components/common/toast.ts`: TYPE_CONFIG bg/border 8곳 하드코딩 rgba → `hexToRgba(COLOR.*, alpha)` (F06-12)
- `frontend/src/components/common/create-slider.ts`: 우측 트랙 기본색 `'#e9ecef'` → `COLOR.inactiveBg` (F06-11)
- `frontend/src/components/common/account-labels.ts`: "보유주식" → "보유 종목" 6곳 (F06-10)
- `frontend/src/pages/sell-position.ts`: "보유주식" → "보유 종목" 6곳 (주석 2 + 배지 라벨 4, F06-10)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-10 | P23 | UI 라벨 "보유주식" → "보유 종목" (용어 사전 준수). account-labels.ts 6곳 + sell-position.ts 6곳 |
| F06-11 | P23 | create-slider.ts 우측 트랙 하드코딩 `#e9ecef` → `COLOR.inactiveBg` (비활성 영역 의미 부합) |
| F06-12 | P23 | toast.ts TYPE_CONFIG 8곳 하드코딩 rgba → `hexToRgba(COLOR.*, alpha)` 공통 헬퍼 활용. 에러/정보 토스트 테두리 색상 톤이 표준 COLOR 팔레트로 통일 |

**검증**: `npm run build` 618ms exit 0. 잔여 "보유주식" grep: profit-overview.ts 1곳 + profit-shared.ts 1곳 (사용자 지시 범위 밖, 미해결 문제에 기록).

**화면 영향**:
- 계좌 현황 표 라벨: "보유주식 평가 금액" → "보유 종목 평가 금액" 등으로 표시 변경
- 보유 종목 페이지 요약 배지: "📊 보유주식 평가금액 합계" → "📊 보유 종목 평가금액 합계" 등
- 슬라이더 우측 트랙: 미세하게 더 진한 회색 (비활성 영역 의미 강화)
- 에러/정보 토스트 테두리: 기존 어두운 톤 → 표준 COLOR 톤 (약간 더 밝고 선명)

## 해결된 문제 (F-06-c 세션 발견)

### 프론트엔드 — 용어 통일 잔존 (F06-10 범위 밖) — 해결됨 (2026-07-22, F-06-d 세션)
- ~~`frontend/src/pages/profit-overview.ts:347` — `보유주식 평가금액 (` UI 텍스트 (P23 위반)~~ → 해결 ("보유 종목 평가금액 ("로 변경)
- ~~`frontend/src/pages/profit-shared.ts:426` — `// 보유주식 평가금액/...` 주석 (P23 위반)~~ → 해결 ("보유 종목 평가금액/..."로 변경)
- ~~사용자 지시(F06-10)가 account-labels.ts + sell-position.ts로 한정되었으므로 본 세션에서 제외. 다음 세션에서 profit-overview/profit-shared 동시 수정 권장.~~ → F-06-d 세션에서 해결 완료. 잔여 "보유주식" grep 0건 확인.

---

## 직전 완료 작업 (이전 세션)

### F-06-b (F06-06): data-table.ts callbackRan dead code 제거 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-06 (P16 dead code) 해결.

**수정 파일 1개**:
- `frontend/src/components/common/data-table.ts` (1053→1045줄, -8줄): `callbackRan` 플래그 6곳(고정 모드 3곳 + 가상 스크롤 모드 3곳) 제거 → `rafId = -1` 센티넬 방식으로 대체

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-06 | P16 | `callbackRan` dead code — 프로덕션(비동기 rAF)에서는 항상 `false`로 남아 조건문이 항상 true인 dead code. 단, 테스트 환경(`vitest.setup.ts` 동기 rAF mock)에서는 살아있는 경로. 근본 원인: 프로덕션-테스트 rAF 동작 불일치. 해결: `rafId = -1` 센티넬을 rAF 호출 전에 설정하여 양 환경에서 동일하게 작동. `callbackRan` 6곳 전부 제거. 테스트 코드는 변경 없음. |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.77s exit 0, `npx vitest run tests/components/data-table.ui.test.ts` 17 tests passed (380ms). 잔여 `callbackRan` 참조 grep 0건 확인.

**화면 영향**: 없음. 렌더링 스케줄링 내부 로직만 변경하며, 테이블 표시/업데이트/플래시 등 사용자에게 보이는 동작은 동일.

## 다음 세션 작업

**잔여 F-06 (별도 세션 each)**:
- F06-01: `data-table.ts` 파일 분할 (1045줄 → ~500줄, fixed/virtual 모드 분리)
- F06-02: `setting-row.ts` 파일 분할 (569줄, 입력란 그룹 분리 검토)
- F06-03: `ui-styles.ts` 파일 분할 (564줄, 셀/컬럼 팩토리 분리 검토)
- F06-10 잔존: profit-overview.ts:347 + profit-shared.ts:426 "보유주식" → "보유 종목" (미해결 문제 참조)

---

## 직전 완료 작업 (이전 세션)

### F-06-a (F06-07/08): 공통 컴포넌트 dead code 제거 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. dead code 2건 제거.

**수정 파일 2개**:
- `frontend/src/components/common/ui-styles.ts` (599→564줄, -35줄): `createStockNameColumnWithSectorLookup` 함수 제거 + unused import 제거 (`hotStore`, `normalizeStockCode`)
- `frontend/src/components/common/setting-row.ts` (635→569줄, -66줄): `createWsStatusBadge` + `createWsToggleGroup` 함수 제거

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-07 | P16 | `createStockNameColumnWithSectorLookup` dead code — `createStockNameColumn`(사용처 7개)과 기능 중복, 정의 외 호출 0건. 제거 |
| F06-08 | P16 | `createWsStatusBadge` + `createWsToggleGroup` dead code — 정의 외 호출 0건. 제거. F06-09(증권사 색상/이름 중복 정의 P10) 동시 해결 (brokerColors/brokerNames 하드코딩 함께 제거) |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.40s exit 0. 잔여 참조 grep 0건 확인 (createStockNameColumnWithSectorLookup / createWsStatusBadge / createWsToggleGroup).

**화면 영향**: 없음. 제거된 함수는 어떤 페이지에서도 호출되지 않았으므로 UI 변화 없음.

## 다음 세션 작업

**잔여 F-06 (별도 세션 each)**:
- F06-01: `data-table.ts` 파일 분할 (1054줄 → ~500줄, fixed/virtual 모드 분리)
- F06-02: `setting-row.ts` 파일 분할 (569줄, 입력란 그룹 분리 검토)
- F06-03: `ui-styles.ts` 파일 분할 (564줄, 셀/컬럼 팩토리 분리 검토)
- F06-10 잔존: profit-overview.ts:347 + profit-shared.ts:426 "보유주식" → "보유 종목" (미해결 문제 참조)

---

## 직전 완료 작업 (이전 세션)

### F-05-c (F05-08): 수익 페이지 컬럼 정의 분할 (2026-07-22)

**세션**: F-05-c (P3 — 수익 페이지) 1단계. F05-08 (파일 길이) 해결.

**수정 파일 3개**:
- `frontend/src/pages/profit-columns.ts` (신규, 111줄): 컬럼 정의 3개 이동 (BUY_COLS/SELL_COLS/createDrilldownCols)
- `frontend/src/pages/profit-shared.ts` (598→493줄, -105줄): 컬럼 정의 3개 제거 + unused import 6개 제거 (ColumnDef/fmtComma/createStockNameColumn/createCodeCell/createNumberCell/hotStore)
- `frontend/src/pages/profit-detail.ts` (672→674줄, +2줄): import 분할 (BUY_COLS/SELL_COLS/createDrilldownCols → profit-columns, 나머지 → profit-shared 유지)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F05-08 | P24 | `profit-shared.ts` 598줄 (500줄 초과) → 493줄 달성. 컬럼 정의 3개를 신규 `profit-columns.ts` (111줄)로 분할 |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.07s exit 0 (profit-shared 13.84 kB, profit-detail 12.65 kB, profit-overview 21.94 kB). 잔여 참조 grep: profit-shared.ts에서 BUY_COLS/SELL_COLS/createDrilldownCols 0건 확인.

**화면 영향**: 없음. 수익 상세 페이지 매수/매도/드릴다운 테이블 표시 동일. 구조 개선만 수행.

## 다음 세션 작업

**잔여 (별도 세션 필요)**:
- `profit-overview.ts` 742줄 (500줄 초과) — `renderSectorStockPnl` 146줄 (135-280줄, P24 50줄의 2.9배) 분할 포함. 업종 그룹 헤더 + 종목 행 렌더 로직을 헬퍼로 분할.
- `profit-detail.ts` 674줄 (500줄 초과) — 별도 세션에서 추가 분할 검토.
- F05-07 "보유주식" → "보유 종목" 용어 통일 잔존: profit-overview.ts:347 + profit-shared.ts:426 (account-labels.ts, sell-position.ts는 F06-10에서 완료).

## 작업 여력

F-05-c(F05-08) 완료 후 작업 여력: **충분**. 잔여 profit-overview.ts/profit-detail.ts 파일 길이 분할 및 renderSectorStockPnl 분할은 규칙 0-1 세션당 1단계 준수를 위해 별도 세션에서 진행 권장.

---

## 직전 완료 작업 (이전 세션)

### F-05-a: 수익 페이지 폴백/중복/비동기 안전 (7건 해결, 2026-07-22)

**세션**: F-05 (P3 — 수익 페이지) 전반부. F-05-b(후반)는 다음 세션에서 진행.

**수정 파일 3개**:
- `frontend/src/pages/profit-shared.ts` (569→598줄): 공통 함수 추가(`buildSectorDonutRows`, `filterTradeRows`), 폴백 제거(F05-01/02)
- `frontend/src/pages/profit-overview.ts` (718→698줄): 중복 함수 제거(`buildSectorDonutData`, `filterSellHistoryByDate`), catch 로깅(F05-03/04), 레이스 가드(F05-11)
- `frontend/src/pages/profit-detail.ts` (667→654줄): 중복 함수 제거(`filterRows`), catch 로깅(F05-03/04)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F05-01 | P20 | `accumulated_investment ?? initial_deposit ?? 0` 3단 폴백 → `initial_deposit ?? 0` (테스트모드 동일 값) |
| F05-02 | P20 | `orderable ?? Math.max(0, deposit - todayBuyAmt)` 폴백 → `orderable ?? 0` (백엔드 항상 전송) |
| F05-03 | P20 | save 함수 `catch { }` 빈 블록 → `console.warn` 로깅 |
| F05-04 | P20 | load 함수 `catch { return null }` → `console.warn` 로깅 |
| F05-05 | P10/P23 | `buildSectorDonutData` 중복 → `buildSectorDonutRows` shared SSOT, `buildSectorStockPnl`이 재사용 |
| F05-06 | P23 | `filterSellHistoryByDate`/`filterRows` 중복 → `filterTradeRows` shared SSOT |
| F05-11 | P19 | `applyDateRange` 레이스 가드 추가 (`_applyDateRangeSeq` 시퀀스) |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.06s exit 0, 잔여 참조 grep 0건. 브라우저 확인 권장.

---

## 직전 완료 작업 (이전 세션)

### F-04-e: P2 — stock-classification.ts + general-settings.ts 함수 분할 11건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/stock-classification.ts` (1617→1618줄, +1줄): F04-01 함수 4개 50줄 초과 분할 — **P24**
  - `buildTripleHeader` (71줄) → `buildHeaderLeft`/`buildHeaderCenter`/`buildHeaderRight` + 본문
  - `buildSectorManageCard` (280줄) → 여러 빌더로 분할 + **중복 퍼지 검색 로직 추출** (F04-16 해결)
  - `buildTripleCenter` (231줄) → 여러 빌더로 분할
  - `mount` (103줄) → `handleStockClassificationChange`/`handleStockDataChange`/`handleUiStoreChange` + 본문
- `frontend/src/pages/general-settings.ts` (1438→1390줄, 48줄 감소): F04-02/F04-04 함수 7개 50줄 초과 분할 — **P24**
  - `renderTimeSettingsTab` (217줄) → `buildBuyTimeRow`/`buildSellTimeRow`/`buildTimetableRow`(3행 중복 제거)/`buildConfirmedDownloadRow`/`buildFixedTimesBox`/`buildSubscribeMaxRow` + 본문
  - `renderAutoTradeTab` (328줄) → 14개 빌더로 분할 (`buildMasterToggleRow`, `buildAutoBuyRow`, `buildAutoSellRow`, `buildOrderTimeGuardRow`, `buildRiskManagerMasterRow`, `buildDailyLossRow` 등)
  - `renderTelegramTab` (87줄) → `buildTeleToggleRow`/`buildTeleInputRows`/`buildTeleSaveRow`/`buildTeleCommandTable` + 본문
  - `renderTestVirtualSection` (101줄) → `buildTestVirtualInputRow`/`buildTestVirtualSaveRow`/`buildTestVirtualInfoWrap`/`buildTestVirtualResetWrap` + 본문
  - `renderApiFields` (65줄) → `buildApiInputRows`/`buildApiSaveRow` + 본문
  - `syncFromSettings` (129줄) → `syncToggleInputRow`(공통 패턴 5회 반복 추출)/`syncRiskManager`/`syncTimetables`/`syncAutoTradeTab`/`syncTelegramTab`/`syncAccountTab`/`syncApiSettingsTab` + 본문 — **P23 DRY**
  - `mount` (67줄) → `buildTabPanels` + 본문

**해결 원칙**: P23 (일관성 — syncToggleInputRow 공통 패턴 추출, buildTimetableRow 3행 중복 제거), P24 (단순성 — 함수 50줄 이하)

**검증**:
- `npm run build` (tsc -b + vite build) — 성공 (2.20s, exit code 0)
- 분할된 11개 함수 모두 50줄 이하 확인 (Python 스크립트로 전수 검증)
- 빌드 에러 4건 발생 후 즉시 해결 (unused 모듈 변수 6개 제거: `timetableResetH/M`/`timetableWsH/M`/`timetableKrxH/M` — 읽히는 곳 없는 dead code, `buildTimetableRow` 타입 좁히기)

**화면 영향**: 없음. 업종분류 페이지 + 일반설정 페이지 모든 탭 표시/입력/저장 동작 동일. 구조 개선만 수행.

**부수적 정리**:
- F04-16 (P23) 해결: fuzzy 검색 로직 중복 → 공통 함수 추출 (F-04-a 보류 항목 해결)
- F04-02/F04-04 (P24) 해결: general-settings.ts 함수 7개 50줄 초과 → 모두 분할 (F-04-b 보류 항목 해결)
- F04-01/F04-03 (P24) 해결: stock-classification.ts 함수 4개 50줄 초과 → 모두 분할 (F-04-a 보류 항목 해결)
- unused 모듈 변수 6개 제거 (timetableResetH/M, timetableWsH/M, timetableKrxH/M — 쓰이지 않는 dead code)

**참고**: 파일 자체는 여전히 500줄 기준 초과 (stock-classification.ts 1618줄, general-settings.ts 1390줄). 본 세션은 "함수 분할"에 한정했으며, "파일 분할(멀티 파일)"은 별도 세션에서 다단계 워크플로우 적용 필요. 현재까지의 F-04 서브세션(a~e)은 모두 함수 단위 분할에 집중.

---

### F-04-d: P2 — sector-settings.ts 구조 분할 2건 (2026-07-22)

**수정 파일 1개**:
- `frontend/src/pages/sector-settings.ts` (503→466줄, 37줄 감소): F04-05 `mount()` 261줄 → 24줄, 7개 빌더 함수 + 2개 구독 함수 분할 (buildFilterSection/buildThresholdSection/buildReceiveProgressSection/buildCutoffSection/buildMaxScoreDisplay/buildBonusSection/buildMaxTargetsSection + startUiStoreSubscription/startHotStoreSubscription) — **P24**. F04-17 파일 503줄 → 466줄 (500줄 기준 해결) — **P24**. 가산점 슬라이더 3블록 중복 (각 13줄 × 3 = 39줄, 슬라이더 설정 완전 동일) → `createBonusSliderBlock` 헬퍼 1개 + 호출 3줄로 통합, 기존 `createBonusSliderRow` 제거 — **P23/P24**

**해결 원칙**: P23 (일관성 — buy-settings.ts 분할 패턴과 동일), P24 (단순성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (3.94s, exit code 0)
- 모든 함수 50줄 이하 (최장 buildReceiveProgressSection 39줄, createBonusSliderBlock 38줄)
- 파일 466줄 (500줄 기준 충족)
- 잔여 `createBonusSliderRow` grep 0건, `createDualLabelSlider` 직접 호출 1건(헬퍼 내)만

**화면 영향**: 없음. 업종순위 설정 패널 표시/입력/저장 동작 동일. 구조 개선만 수행.

**보류 항목 (F-04-d 범위외, 추후 세션)**:
- F-04-e (별도): stock-classification.ts + general-settings.ts 파일 분할 (구조 변경, 다단계 워크플로우 적용)

---

### F-04-c: P2 — 매수/매도 설정 페이지 buy-settings.ts + sell-settings.ts 4건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/buy-settings.ts` (425→452줄, +27줄): F04-12 `Number() || 기본값` 폴백 11건 → `??` (nullish coalescing). **가산점 점수 0 설정 후 새로고침 시 1.0으로 잘못 표시되는 버그 수정** (boost_high/order/program/trade_amount_score 4건). 나머지 7건(rise_pct/fall_pct/min_strength/max_daily_amt/max_stock_cnt/buy_amt/buy_interval_sec)도 동일 패턴으로 통일 — **P20/P21**. F04-06 `mount()` 233줄 → 5개 섹션 빌더 분할 (buildBuyBlockSection/buildBoostSection+buildBoostOrderBlock/buildBuyAmountSection/buildRebuySection/buildBuyIntervalSection), mount 본문 20줄 — **P24**. F04-07 `syncFromSettings` 92줄 → 5개 동기화 함수 분할 (syncBuyBlock/syncBoost/syncBuyAmount/syncRebuy/syncBuyInterval), 본문 13줄 — **P24**
- `frontend/src/pages/sell-settings.ts` (174→181줄, +7줄): F04-13 `Number() || 기본값` 폴백 5건 → `??` (일관성, 동작 버그 없음) — **P20**. F04-07 `mount()` 80줄 → 2개 섹션 빌더 분할 (buildSellTypeSection/buildSellIntervalSection), mount 본문 17줄 — **P24**

**해결 원칙**: P20 (폴백 금지), P21 (사용자 투명성 — 가산점 0 표시 버그), P24 (단순성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (2.05s, exit code 0)
- 잔여 `Number() ||` 폴백 grep 0건
- 모든 함수 50줄 이하 (최장 buildSellTypeSection 49줄)

**화면 영향**:
- 매수 가산점 점수 0 설정 시: 이전 화면 1.0 잘못 표시 → 이제 0 올바르게 표시 (버그 수정)
- 매수/매도 설정 페이지 표시/저장 동작: 동일 (구조 개선만, 사용자 동작 변화 없음)

**보류 항목 (F-04-c 범위외, 추후 세션)**:
- F04-14 (P23, INFO): 저장 호출 패턴 3종 혼재 (buy/sell: saveHelper.saveImmediate 미await / general: async/await saveSection / sector: autoSave 디바운스) — saveSection이 내부 try/catch로 reject하지 않으므로 안전. F-07 범위(settings-save.ts)와 연계 검토 권장
- F-04-e (별도): stock-classification.ts + general-settings.ts 파일 분할 (구조 변경, 다단계 워크플로우 적용)

---

### F-04-b: P2 — 설정 페이지 general-settings.ts + sector-settings.ts 4건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/general-settings.ts` (1453→1448줄, 5줄 감소): F04-20 `.then()` 패턴 12개 → async/await 통일 (handleMasterToggle, dailyLoss/Rate/Profit/ProfitRate/ConsecLoss Input onChange 5개 + onToggle 5개, subscribeMaxInput onChange) — **P23**. F04-21 구독/정리를 `startSettingsSubscription`/`destroySettingsPage` 표준 유틸로 전환 (buy-settings/sell-settings와 동일 패턴) — **P23**. F04-23 거래일 조회 실패 시 조용한 폴백 → 사용자 알림 토스트 추가 ("거래일 조회 실패 — 거래일로 간주하여 자동매매를 허용합니다") — **P20/P21**
- `frontend/src/pages/sector-settings.ts` (509→501줄, 8줄 감소): F04-22 `initSettingsPage`/`startSettingsSubscription`/`destroySettingsPage` 표준 유틸로 전환 + **onSync 콜백 누락 해결** (기존 `createAutoSaveHelper(settingsMgr)`는 onSync 없이 생성 → 저장 후 동기화 누락 버그) — **P23**

**해결 원칙**: P20 (폴백 금지), P21 (사용자 투명성), P23 (일관성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (1.94s, exit code 0)

**화면 영향**:
- 설정 저장 동작: 동일 (토글/입력 저장 방식 변함 없음)
- 거래일 조회 실패 시: 이전 화면 알림 없음 → 이제 "거래일 조회 실패" 토스트 표시 (자동매매는 여전히 거래일로 간주하여 허용)
- 업종순위 설정 저장 후: 이전 화면 갱신 누락 가능 → 이제 저장 후 즉시 갱신 (onSync 콜백 연결)

**보류 항목 (F-04-b 범위외, 추후 세션)**:
- F04-02/F04-04 (P24): general-settings.ts 파일 1448줄 / 함수 7개 50줄 초과 — 파일 분할은 별도 세션 필요 (구조 변경)
- F04-05 (P24): sector-settings.ts mount 함수 길이 — 분할 검토
- F04-06/F04-07 (P24): buy-settings/sell-settings 함수 길이 — 분할 검토
- F04-12/F04-13 (P20): buy-settings/sell-settings `Number() || 0` 폴백 — 사용자 설계 로직 판단 필요

---

### F-04-a: P2 — 설정 페이지 stock-classification.ts 5건 (2026-07-22)

**수정 파일 1개** (1617→1597줄, 20줄 감소):
- `frontend/src/pages/stock-classification.ts`: F04-08 `_testSetState` dead code 제거 (10줄, 사용처 없는 테스트 헬퍼) — **P16**. F04-09 전역 이벤트 리스너(`window mouseup`, `detailTableRef keydown`)를 명명된 핸들러로 변경 후 unmount 시 `removeEventListener` 제거 (메모리 누수 방지) — **P19**. F04-10 `_mounted` 플래그 추가, `onMoveStock` async 응답 후 store 업데이트 전 가드 (race condition 방지) — **P19**. F04-11 외부 미사용 export 9개 제거 (`parseBatchInput`, `resolveToken`, `getMoveSource`, `getMovableCount`, `createChip`, `addToStaging`, `removeFromStaging`, `clearStaging`, `buildMoveMessage` — 모두 파일 내부에서만 사용) — **P16/P24**. F04-19 제거된 코드 참조 주석 2건 정리 (`// import ... (removed)`, `// buildSchedulerCard removed.`) — **P23**

**해결 원칙**: P16 (살아있는 경로), P19 (비동기 누락/메모리 누수), P23 (주석 정리), P24 (단순성)

**검증**:
- `npm run build` (tsc -b + vite build) — 성공 (exit code 0)
- 타입 오류 없음, 빌드 산출물 정상 생성

**화면 영향**: 없음. 업종분류 페이지 표시/동작 동일. 구조 개선만 수행.

**보류 항목 (F-04-a 범위외, 추후 세션)**:
- F04-01/F04-03 (P24): stock-classification.ts 파일 1597줄 / 함수 4개 50줄 초과 (buildSectorManageCard 278줄, buildTripleCenter 231줄, mount 103줄, buildTripleHeader 71줄) — 파일 분할은 별도 세션 필요 (구조 변경)
- F04-15 (P10): 로컬 캐시/파생 상태 (cachedSectorStocksRef, cachedAllStocksMap, stockNameIndex, stagingSet, selectedStocks) — 성능 최적화 목적이므로 판단 필요
- F04-16 (P23): fuzzy 검색 로직 중복 (612-628줄, 684-694줄) — 공통 함수 추출 검토
- ~~F04-18 (P21): 업종 삭제 시 사용자 명시적 알림 부재 — 경미~~ → 해결 (2026-07-23 조사). `onDeleteSector`에 사전 확인 팝업(업종명+영향 명시) + 사후 성공/실패 토스트 + warning alert 3중 알림 구현됨. P21 위반 잔존 없음.

---

## 현재 진행 상황

### 아키텍처 전수 조사 진행률: 30/30 세션 완료 (100%, F-04-e 완료)

| 상태 | 세션 |
|------|------|
| 완료 | B-01~B-12, B-14~B-23, F-01, F-02, F-03, F-04 |
| 부분 완료 | B-13 (3건 해결, 5건 보류 LOW/INFO), F-04 (F-04-a 5건 + F-04-b 4건 + F-04-c 4건 + F-04-d 2건 + F-04-e 11건 해결, 잔여 파일 분할 별도) |
| 미시작 | F-05, F-06, F-07 |

**다음 세션**: F-05 (P3 — 수익 페이지 profit-overview.ts + profit-detail.ts + profit-shared.ts)

---

## 미해결 문제

### F-04-e 보류 항목 (F-04-e 범위외, 추후 세션)
- F04-01/F04-03 파일 분할 (P24): stock-classification.ts 1618줄 — 함수 분할은 완료, 파일 자체는 500줄 기준 초과. 멀티 파일 분할은 별도 세션 필요 (다단계 워크플로우)
- F04-02/F04-04 파일 분할 (P24): general-settings.ts 1390줄 — 함수 분할은 완료, 파일 자체는 500줄 기준 초과. 멀티 파일 분할은 별도 세션 필요 (다단계 워크플로우)

### F-04-d 보류 항목 (F-04-d 범위외, 추후 세션)
- ~~F-04-e (별도): stock-classification.ts + general-settings.ts 함수 분할~~ — **F-04-e 해결** (11건 함수 분할 완료, 파일 분할은 잔여)

### F-04-c 보류 항목 (F-04-c 범위외, 추후 세션)
- F04-14 (P23, INFO): 저장 호출 패턴 3종 혼재 (buy/sell: saveHelper.saveImmediate 미await / general: async/await saveSection / sector: autoSave 디바운스) — saveSection이 내부 try/catch로 reject하지 않으므로 안전. F-07 범위(settings-save.ts)와 연계 검토 권장
- ~~F-04-e (별도): stock-classification.ts + general-settings.ts 함수 분할~~ — **F-04-e 해결** (11건 함수 분할 완료)

### F-04-b 보류 항목 (F-04-b 범위외, 추후 세션)
- ~~F04-02/F04-04 (P24): general-settings.ts 함수 7개 50줄 초과~~ — **F-04-e 해결** (7개 함수 모두 분할, 파일 1448→1390줄)
- F04-06/F04-07 (P24): buy-settings/sell-settings 함수 길이 — 분할 검토
- F04-12/F04-13 (P20): buy-settings/sell-settings `Number() || 0` 폴백 — 사용자 설계 로직 판단 필요
- ~~F04-05 (P24): sector-settings.ts mount 함수 길이~~ — **F-04-d 해결** (mount 261→24줄)
- ~~F04-17 (P24): sector-settings.ts 파일 길이~~ — **F-04-d 해결** (503→466줄)

### F-04-a 보류 항목 (F-04-a 범위외, 추후 세션)
- ~~F04-01/F04-03 (P24): stock-classification.ts 함수 4개 50줄 초과~~ — **F-04-e 해결** (4개 함수 모두 분할)
- F04-15 (P10): 로컬 캐시/파생 상태 — 성능 최적화 목적이므로 판단 필요
- ~~F04-16 (P23): fuzzy 검색 로직 중복~~ — **F-04-e 해결** (공통 함수 추출)
- ~~F04-18 (P21): 업종 삭제 시 사용자 명시적 알림 부재 — 경미~~ → 해결 (2026-07-23 조사). `onDeleteSector`에 사전 확인 팝업 + 사후 토스트 + warning alert 3중 알림 구현됨. P21 위반 잔존 없음.

### F-03 보류 항목 (B그룹 4건, 추후 검토)
- F03-07 (P20/P22): sell-position.ts:59,73 — `sectorStock?.cur_price ?? p.cur_price` 폴백 (사용자 설계 로직, 규칙 0-5 적용 대상)
- F03-08 (P24): sector-stock.ts 653줄 — 500줄 기준 초과, 분할 시 별도 세션 필요
- F03-09 (P24): computeRows(115줄)/connectedCallback(263줄)/updateBadges(79줄)/mount(192줄) — 50줄 기준 초과
- F03-10 (P23): filterStocksBySearch가 페이지 파일에 정의, buy-target.ts 크로스 사용 — utils/ 이동 검토

### F-03 범위외 발견 (F-06 공통 컴포넌트 세션에서 처리)
- F03-11 (P16): card-header.ts:8-24 `createCardHeader` (margin 없는 버전) 사용처 없음, `createCardHeaderWithMargin`만 사용

### F-02 발견 경미 사항 (정보만 기록, 수정 여부 사용자 판단)
- **main.ts**: 주석 번호 중복 (이미 F-02에서 "6."→"7."로 정리 완료)
- **header.ts line 99**: `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` — 알 수 없는 장 페이즈를 '장마감' 스타일로 처리하는 폴백 (P20 경미). 2026-07-23 폴백 제거 시도 → 하얀 화면 발생으로 롤백 (커밋 `ce9e137` → `a5b357b`). 근본 원인: 프론트엔드 초기값/폴백값 `'CLOSED'`가 PHASE_STYLE 키에 없음. **안 B(초기값 'CLOSED' → '장마감' 통일) 사전조사 후 근본 해결 예정 — 상단 직전 완료 작업 참조**.

### B-13 보류 항목 (5건, LOW/INFO)
- B-13 부분 완료. 잔여 5건은 LOW/INFO 등급으로 보류 중.

---

## 다음 세션 인계 사항

1. **F-05 (P3 — 수익 페이지)** 부터 시작. F-04-e 완료 (stock-classification.ts + general-settings.ts 함수 11건 분할).
   - F-05 대상: `profit-overview.ts` (718줄) + `profit-detail.ts` (667줄) + `profit-shared.ts` (569줄) — 총 1954줄
   - F-04 잔여: stock-classification.ts (1618줄) / general-settings.ts (1390줄) 파일 자체 분할 — 별도 세션 (멀티 파일 분할, 다단계 워크플로우)
2. 대상 원칙: P5, P10, P16, P19, P22, P23, P24
3. `architecture_audit_tasks.md` 섹션 F-05 체크리스트 참조
4. 세션당 1단계 원칙 준수 (AGENTS.md 규칙 0-1)
5. F-03 보류 항목 4건 (F03-07~F03-10) 참조

### T2-S8 작업 중 발견 (2026-07-23)
- pipeline_compute.py:14 `import time` unused (F401) — 본 세션 수정 범위 밖. 기존 잔존.
- pipeline_compute.py:18 `_check_realtime_latency` import unused (F401) — 본 세션 수정 범위 밖. 기존 잔존.
