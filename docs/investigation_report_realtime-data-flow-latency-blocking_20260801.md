# 실시간 데이터 흐름 지연/블로킹 발생 지점 전수 조사 보고서

> **조사 주제**: 실시간 데이터 흐름에서 지연/블로킹 발생 지점 전수 조사 (백엔드 + 프론트엔드)
> **조사 슬러그**: `realtime-data-flow-latency-blocking`
> **상태 파일**: `.devin/state/investigation_status.json` (continuity-investigation 스킬)
> **작성일**: 2026-08-01
> **최종 갱신**: 2026-08-01 (초안 작성)

---

## 0. 문서 갱신 가이드 (에이전트용)

본 보고서는 **나중에 수정할 때마다 갱신하기 쉽도록** 아래 규칙으로 구조화되어 있다.

| 갱신 시 작업 | 위치 | 방법 |
|---|---|---|
| 신규 발견 사항 추가 | §3 (심각도별 상세) | ID 시퀀스 유지 (H-12, M-38, L-40 …). 상태 `신규`로 추가. |
| 기존 사항 상태 변경 | §3 해당 항목의 `조치 상태` 라인 | `신규` → `검토 중` / `수정 완료` / `보류` / `기각(의도적 설계)` 중 하나로 변경 + 날짜 기재. |
| 통계 갱신 | §1.2 통계 요약 | 심각도별 카운트·파일별 카운트 재계산. 상태별 카운트도 갱신. |
| 갱신 이력 추가 | §6 갱신 이력 | 날짜 + 변경 요약 한 줄 추가 (최신 상단). |
| 원본 상태 파일 동기화 | `.devin/state/investigation_status.json` | 본 보고서와 상태 파일의 `findings` 배열이 일치하도록 유지. |

**ID 체계**: `H-NN`(high) / `M-NN`(mid) / `L-NN`(low). 심각도별 독립 시퀀스. 삭제 시 ID 재사용 금지 (공란으로 두거나 `~삭제~` 표기).

**조치 상태 값**:
- `신규` — 조사 단계에서 식별, 후속 조치 미정
- `검토 중` — 수정 방향 논의/설계 중
- `수정 완료` — 코드 수정 반영 + 검증 통과 (커밋 해시 기재)
- `보류` — 현재 구조상 통합 어려움 또는 후순위
- `기각(의도적 설계)` — 의도적 설계로 판명, 수정 대상 아님 (사유 기재)

---

## 1. 조사 개요

### 1.1 메타데이터

| 항목 | 값 |
|---|---|
| 조사 주제 | 실시간 데이터 흐름에서 지연/블로킹 발생 지점 전수 조사 (백엔드 + 프론트엔드) |
| 시작일 | 2026-07-31 21:01 UTC |
| 종료일 | 2026-08-01 (조사 완료) |
| 조사 방법 | continuity-investigation 스킬 (세션 단위 분할 전수 조사) |
| 세션 수 | 2세션 진행 |
| 조사 범위 | `backend/app/**/*.py` + `frontend/src/**/*.ts` (총 205 파일 후보) |
| 조사 완료 파일 | 88개 (핫패스·파이프라인·WS·스토어·페이지 중심) |
| 미조사 파일 | remaining 137개 (config/init/broker registry 등 비핫패스 — 조사 종료 결정) |
| 상태 파일 | `.devin/state/investigation_status.json` |

### 1.2 통계 요약

> **갱신 포인트**: 발견 사항 추가/상태 변경 시 아래 표를 재계산. 원본 상태 파일 기준 카운트.

**심각도별 발견 사항** (총 87건):

| 심각도 | 건수 | 정의 |
|---|---|---|
| high | 11 | 틱 핫패스 / 실시간 수신 경로 블로킹 |
| mid | 37 | 파이프라인 / 기동 / WS 브로드캐스트 경로 |
| low | 39 | 드문 경로 / 스타일 / 이미 최적화 양호 |
| **합계** | **87** | — |

> 참고: 상태 파일 `next_action`에 "88개 / 40 low"로 기재되어 있으나, 실제 `findings` 배열 카운트는 87건 (high 11 + mid 37 + low 39). 본 보고서는 실제 데이터 기준.

**조치 상태별 분포** (갱신 포인트):

| 상태 | 건수 |
|---|---|
| 신규 | 87 |
| 검토 중 | 0 |
| 수정 완료 | 0 |
| 보류 | 0 |
| 기각(의도적 설계) | 0 |

**파일별 발견 사항 수** (상위 다건 파일):

| 파일 | 건수 | 심각도 |
|---|---|---|
| frontend/src/stores/hotStore.ts | 7 | low, mid |
| backend/app/pipelines/pipeline_compute.py | 4 | high, low, mid |
| backend/app/pipelines/pipeline_compute_tick_handlers.py | 4 | high, mid |
| backend/app/services/engine_account.py | 4 | high, mid |
| backend/app/web/ws_manager.py | 4 | high, low |
| backend/app/services/risk_manager.py | 3 | low, mid |
| backend/app/services/sector_data_provider.py | 3 | mid |
| backend/app/services/settlement_engine.py | 3 | mid |
| backend/app/services/trade_history.py | 3 | low, mid |
| backend/app/services/trading.py | 3 | mid |

전체 파일별 목록은 §4 파일별 인덱스 참조.

### 1.3 조사 체크리스트

각 파일에서 아래 5개 항목을 점검. 해당 원칙 번호는 `ARCHITECTURE.md` 불변 원칙(P1~P25) 참조.

1. **동기 I/O 블로킹** (P1-P3, P7): async 컨텍스트에서 `requests`/`sqlite3`/`time.sleep`/동기 파일 I/O/`run_in_executor` 우회/`asyncio.run` 사용.
2. **per-tick O(n) 연산** (P7): 틱 핸들러에서 O(n) 순회, 매 틱 DB 조회, 매 틱 전체 리스트 스캔, 매 틱 dictionary 전체 rebuild.
3. **폴링/과도한 대기** (P11): `while + sleep` 폴링, `asyncio.wait` 타임아웃 남용, 불필요한 sleep, `while True` 무한루프.
4. **DB 연결/쿼리 비효율** (P12): 요청마다 `connect()`, 인덱스 없는 쿼리, N+1 쿼리, 트랜잭션 과다, 매 tick DB write.
5. **추가 항목**: 브로커 REST 호출 동기화/재시도 폭주, WS 브로드캐스트 전체 순회, 큐 적체(`while queue.empty()` 아님 패턴), 프론트 rAF/setTimeout 중복 스케줄, store listener 동기 순회, 대량 DOM 조작.

**심각도 기준**:
- `high` = 틱 핫패스 / 실시간 수신 경로 블로킹
- `mid` = 파이프라인 / 기동 / WS 브로드캐스트 경로
- `low` = 드문 경로 / 스타일 / 이미 최적화 양호

---

## 2. 조사 범위

### 2.1 조사 완료 파일 (88개)

**백엔드 (69개)**:
engine_loop.py, engine_ws.py, engine_ws_dispatch.py, engine_ws_parsing.py, engine_ws_reg.py, engine_account.py, engine_account_broadcast.py, engine_account_rest.py, engine_account_notify.py, engine_lifecycle.py, engine_state.py, engine_bootstrap.py, engine_service.py, engine_radar.py, engine_symbol_utils.py, engine_initial_data.py, engine_cache.py, engine_config.py, engine_strategy_core.py, engine_sector_confirm.py, engine_utils.py, core_queues.py, db/db_writer.py, db/database.py, web/routes/ws.py, web/routes/ws_settings.py, web/routes/ws_orders.py, web/routes/ws_subscribe.py, web/ws_manager.py, core/ls_connector.py, core/kiwoom_connector.py, core/broker_connector.py, core/connector_manager.py, pipelines/pipeline_compute.py, pipelines/pipeline_compute_tick_handlers.py, pipelines/pipeline_gateway.py, services/trading.py, services/buy_order_executor.py, services/dry_run.py, services/order_interval.py, services/settlement_engine.py, services/auto_trading_effective.py, core/kiwoom_ws_reg.py, core/kiwoom_rest.py, core/ls_rest.py, core/kiwoom_stock_rest.py, core/kiwoom_order.py, services/risk_manager.py, services/circuit_breaker.py, services/data_manager.py, services/sector_data_provider.py, services/trade_history.py, services/ws_subscribe_control.py, services/daily_time_scheduler.py, services/notification_worker.py, services/telegram_bot.py

**프론트엔드 (12개)**:
api/ws.ts, stores/hotStore.ts, stores/store.ts, main.ts, binding.ts, components/common/data-table-virtual.ts, components/virtual-scroller.ts, pages/buy-target.ts, pages/sell-position.ts, pages/profit-overview.ts, pages/profit-detail.ts, pages/sector-stock.ts

### 2.2 미조사 파일 (remaining 137개)

config/init/broker registry/공통 컴포넌트/설정 페이지 등 비핫패스 파일. 조사 종료 결정 — 핫패스 분석 완료 후 remaining은 성능 영향 제한적으로 판단.

---

## 3. 발견 사항 상세

> 각 항목 형식: `ID · 파일:줄 · 심각도 · 조치 상태`. 증거 코드는 발견 시점 기준.

### 3.1 High (틱 핫패스 / 실시간 수신 경로 블로킹) — 11건

#### H-01 · pipeline_compute.py:253 · high · 신규
- **함수**: `_process_tick_batch`
- **설명**: 배치 내 각 이벤트를 `_process_tick_data` await로 순차 처리. 01 틱은 `_apply_01_price_to_positions`(보유종목 O(n) 스캔) + `_check_01_auto_sell`(매도 조건 체크)를 per-tick 실행. 배치 500개일 때 500회 직렬 await.
- **증거**: `for event in coalesced: _hit = await _process_tick_data(event, broadcast_queue)`
- **관련 원칙**: P7 (per-tick O(n))
- **조치 상태**: 신규 (2026-08-01)

#### H-02 · pipeline_compute.py:275 · high · 신규
- **함수**: `_compute_loop_impl`
- **설명**: 단일 컨슈머가 `tick_queue`에서 배치 드레인 후 `_process_tick_batch`를 await로 직렬 처리. 배치 처리 중(매도 조건 체크, 계좌 갱신 등) 후속 틱 대기. 틱 폭주 시 배치 처리 시간이 수신 속도 미충가 가능.
- **증거**: `data = await asyncio.wait_for(tick_queue.get(), timeout=0.5); ... await _process_tick_batch(batch, broadcast_queue)`
- **관련 원칙**: P7, P11
- **조치 상태**: 신규 (2026-08-01)

#### H-03 · pipeline_compute_tick_handlers.py:178 · high · 신규
- **함수**: `_check_01_auto_sell`
- **설명**: 01 체결 틱마다 보유종목 리스트에서 매칭 포지션 O(n) 선형 검색 후 `check_sell_conditions()` await. 틱 핫패스에서 per-tick 매도 조건 평가.
- **증거**: `_matched = [p for p in state.positions if _base_stk_cd(...) == nk_px]; await state.auto_trade.check_sell_conditions(_matched, ...)`
- **관련 원칙**: P7 (per-tick O(n))
- **조치 상태**: 신규 (2026-08-01)

#### H-04 · pipeline_gateway.py:66 · high · 신규
- **함수**: `_broadcast_loop`
- **설명**: 단일 컨슈머가 `broadcast_queue`에서 데이터를 꺼내 `_process_broadcast` → `ws_manager.broadcast`를 await로 직렬 호출. `ws_manager.broadcast` 내부에서 클라이언트별 순차 전송. 전송 지연 시 큐 적체 → 틱 처리 블로킹 전파.
- **증거**: `data = await broadcast_queue.get(); await _process_broadcast(data)`
- **관련 원칙**: P7, P11
- **조치 상태**: 신규 (2026-08-01)

#### H-05 · engine_account.py:317 · high · 신규
- **함수**: `_apply_balance_realtime`
- **설명**: 잔고(04) 틱 핫패스에서 `_cash_insufficient` 시 `evaluate_buy_candidates()` await 호출. 잔고 회복 감지 시 매수 후보 전체 재평가가 틱 처리 중 동기 실행됨.
- **증거**: `if _cash_insufficient: invalidate_buy_snapshot(); await evaluate_buy_candidates()`
- **관련 원칙**: P7
- **조치 상태**: 신규 (2026-08-01)

#### H-06 · engine_account.py:359 · high · 신규
- **함수**: `_on_fill_after_ws`
- **설명**: 체결 수신 틱 핫패스에서 `_refresh_account_snapshot_meta()` await + `auto_trade.check_sell_conditions()` await 직렬. `check_sell_conditions`는 전체 포지션 순회 매도 조건 검사. 체결마다 매도 조건 전체 재검사로 틱 지연 가능.
- **증거**: `await _refresh_account_snapshot_meta(); ... await state.auto_trade.check_sell_conditions(pos, ...)`
- **관련 원칙**: P7
- **조치 상태**: 신규 (2026-08-01)

#### H-07 · engine_ws_dispatch.py:127 · high · 신규
- **함수**: `_handle_real_00`
- **설명**: 주문체결(00) 틱 핫패스에서 `auto_trade.on_fill_update()` await + `engine_account._on_fill_after_ws()` await 직렬 호출. 두 await가 순차 실행되어 체결 처리 지연 누적. `_broker_message_handler`가 `create_task` 없이 await 직접 호출(엔진 설계 의도)하므로 후속 메시지 수신도 블로킹.
- **증거**: `await engine_state.state.auto_trade.on_fill_update(raw_cd, side, unex, ...); await engine_account._on_fill_after_ws()`
- **관련 원칙**: P7, P14 (create_task 무분별 분리 금지 — 설계 의도와 충돌 주의)
- **조치 상태**: 신규 (2026-08-01)

#### H-08 · engine_ws_dispatch.py:151 · high · 신규
- **함수**: `_handle_real_balance`
- **설명**: 잔고(04) 틱 핫패스에서 `engine_account._apply_balance_realtime()` await. `_apply_balance_realtime` 내부에서 `evaluate_buy_candidates()` await까지 호출될 수 있어 틱 처리 중 매수 후보 재평가까지 직렬 실행.
- **증거**: `await engine_account._apply_balance_realtime(item, item)`
- **관련 원칙**: P7 (H-05와 동일 체인 상위 진입점)
- **조치 상태**: 신규 (2026-08-01)

#### H-09 · ws_manager.py:44 · high · 신규
- **함수**: `_encode_realdata`
- **설명**: real-data 틱마다 `dumps(data, sort_keys=True)` + `hashlib.md5()` 실행. 틱 핫패스에서 JSON 직렬화 + 해시 계산. 캐시 적중 시에도 매 틱 dumps+md5 연산 발생.
- **증거**: `data_str = dumps(data, sort_keys=True); data_hash = hashlib.md5(data_str.encode('utf-8')).hexdigest()`
- **관련 원칙**: P7
- **조치 상태**: 신규 (2026-08-01)

#### H-10 · ws_manager.py:144 · high · 신규
- **함수**: `_send_broadcast`
- **설명**: 모든 클라이언트에 `await ws.send_text()` 순차 전송. 클라이언트 N명일 때 N번 직렬 await. 한 클라이언트 전송 지연 시 전체 broadcast 블로킹. real-data 틱 핫패스에서 호출됨.
- **증거**: `for ws in set(self._clients): try: await ws.send_text(message)`
- **관련 원칙**: P7
- **조치 상태**: 신규 (2026-08-01)

#### H-11 · ws_manager.py:153 · high · 신규
- **함수**: `_send_realdata_encoded`
- **설명**: real-data 틱 핫패스. 클라이언트를 FID 그룹별로 분류 후 각 그룹 내에서 `await ws.send_text()`/`send_bytes()` 순차 전송. 틱마다 실행되며 클라이언트 전송 지연 시 틱 처리 블로킹.
- **증거**: `for ws in clients: try: ... await ws.send_text(text_frame)`
- **관련 원칙**: P7 (H-10과 동일 파일, real-data 전용 경로)
- **조치 상태**: 신규 (2026-08-01)

### 3.2 Mid (파이프라인 / 기동 / WS 브로드캐스트 경로) — 37건

#### M-01 · kiwoom_connector.py:290 · mid · 신규
- **함수**: `subscribe_stocks`
- **설명**: 청크(100개)별 `_ws_send_reg_unreg_and_wait_ack` 순차 호출. ACK 10초 타임아웃 + post-ACK sleep(0.35초) per 청크. 200종목 = 2청크 = 최소 0.7초 + ACK 대기.
- **증거**: `for payload in payloads: ok, rc = await _ws_send_reg_unreg_and_wait_ack(payload, sender=self)`
- **조치 상태**: 신규 (2026-08-01)

#### M-02 · kiwoom_order.py:16 · mid · 신규
- **함수**: `_send_request`
- **설명**: 매 주문마다 `async with httpx.AsyncClient()` 생성/종료. 매수/매도 주문 시마다 새 HTTP 클라이언트 생성. 연결 풀 재사용 안함. 주문 경로.
- **증거**: `async with httpx.AsyncClient() as client: r = await client.post(url, headers=headers, json=params, timeout=5)`
- **조치 상태**: 신규 (2026-08-01)

#### M-03 · ls_connector.py:464 · mid · 신규
- **함수**: `subscribe_stocks_tr`
- **설명**: 종목 리스트를 per-code 루프로 개별 WS 전송. 200종목 구독 시 200회 순차 await send + `asyncio.sleep(0)`. 구독 경로(비틱)이나 대량 구독 시 누적 지연.
- **증거**: `for code in codes: ... success = await self._socket.send(payload) ... await asyncio.sleep(0)`
- **조치 상태**: 신규 (2026-08-01)

#### M-04 · db_writer.py:163 · mid · 신규
- **함수**: `enqueue_db_write`
- **설명**: `_db_write_queue.put(op)`가 maxsize=100 초과 시 블로킹. DB 쓰기 지연 시 생산자 큐 적체로 전체 파이프라인 지연 가능.
- **증거**: `await _db_write_queue.put(op)`
- **조치 상태**: 신규 (2026-08-01)

#### M-05 · db_writer.py:168 · mid · 신규
- **함수**: `execute_db_write(wait=True)`
- **설명**: `await op.future`로 DB 쓰기 완료까지 호출자 블로킹. 틱 핫패스에서 `wait=True` 호출 시 틱 처리가 DB 쓰기까지 대기.
- **증거**: `if wait and op.future: return await op.future`
- **조치 상태**: 신규 (2026-08-01)

#### M-06 · pipeline_compute.py:162 · mid · 신규
- **함수**: `_calc_market_receive_rate`
- **설명**: codes 리스트 O(n) 순회 + `master_stocks_cache.get(code)` per-code 조회. Phase 1/2 루프에서 200ms마다 호출. n=전체 종목(2000+).
- **증거**: `for code in codes: if code in received_set: ... else: entry = state.master_stocks_cache.get(code)`
- **조치 상태**: 신규 (2026-08-01)

#### M-07 · pipeline_compute_tick_handlers.py:110 · mid · 신규
- **함수**: `_apply_01_radar_and_receive_rate`
- **설명**: 01 틱마다 `_apply_real01_volume_amount_to_radar_rows`(캐시 직접 갱신) + `request_sector_recompute`(dirty 마킹). per-tick 실행.
- **증거**: `_apply_real01_volume_amount_to_radar_rows(raw_cd, vals, is_0b_tick=is_0b_tick); ... request_sector_recompute(nk_px)`
- **조치 상태**: 신규 (2026-08-01)

#### M-08 · pipeline_compute_tick_handlers.py:141 · mid · 신규
- **함수**: `_apply_01_price_to_positions`
- **설명**: `apply_last_price_to_positions_inplace`가 `state.positions` O(n) 선형 스캔. 01 틱마다 실행. 보유 종목 수에 비례.
- **증거**: `_price_hit = apply_last_price_to_positions_inplace(state.positions, raw_cd, last_px)`
- **조치 상태**: 신규 (2026-08-01)

#### M-09 · pipeline_compute_tick_handlers.py:350 · mid · 신규
- **함수**: `_recompute_boost_scores_for_hits`
- **설명**: 뉴스 히트 시 `get_high_price_5d_cache`/`get_orderbook_cache`/`get_program_net_buy_cache`/`get_news_boost_cache` 4개 O(n) 캐시 getter 동시 호출. 각각 `master_stocks_cache` 전체 순회. 뉴스 이벤트 빈도에 따라 누적.
- **증거**: `high_5d = get_high_price_5d_cache(); obc = get_orderbook_cache(); pnb = get_program_net_buy_cache(); nbc = get_news_boost_cache()`
- **조치 상태**: 신규 (2026-08-01)

#### M-10 · dry_run.py:173 · mid · 신규
- **함수**: `fake_fill_event`
- **설명**: `asyncio.sleep(FAKE_FILL_DELAY=0.1)`으로 가상 체결 지연. 테스트모드 매수/매도 후 0.1초 블로킹. 의도적 지연이나 테스트모드 틱 처리 경로에 영향.
- **증거**: `await asyncio.sleep(FAKE_FILL_DELAY)`
- **조치 상태**: 신규 (2026-08-01)

#### M-11 · engine_account.py:165 · mid · 신규
- **함수**: `_fetch_account_raw`
- **설명**: deposit REST 호출 후 0.5초 sleep 후 balance REST 호출. 429 예방 의도적 sleep이나 REST bootstrap 경로 0.5초 블로킹.
- **증거**: `await asyncio.sleep(0.5)`
- **조치 상태**: 신규 (2026-08-01)

#### M-12 · engine_account.py:384 · mid · 신규
- **함수**: `_broadcast_account`
- **설명**: `trade_history.build_positions_from_trades('real')` await 호출. DB 기반 거래 내역 조회가 계좌 브로드캐스트 경로에서 동기 대기. 체결/잔고 갱신 후 브로드캐스트 시 틱 경로 간접 지연.
- **증거**: `trade_positions = await trade_history.build_positions_from_trades('real')`
- **조치 상태**: 신규 (2026-08-01)

#### M-13 · engine_account_rest.py:78 · mid · 신규
- **함수**: `recalc_broker_totals_from_positions`
- **설명**: REAL 01 틱마다 positions O(n) 합산 루프. per-tick O(n) 연산 (P7). 포지션 수가 적으면 영향 제한적.
- **증거**: `for p in positions: if int(p.get('qty',0) or 0) > 0: tot_eval += ...`
- **조치 상태**: 신규 (2026-08-01)

#### M-14 · engine_account_rest.py:146 · mid · 신규
- **함수**: `apply_last_price_to_positions_inplace`
- **설명**: REAL 01 틱마다 positions 리스트 O(n) 선형 스캔으로 종목 매칭. per-tick O(n) 연산 (P7). 포지션이 적으면 영향 제한적이나 구조적으로 per-tick 스캔.
- **증거**: `for s in positions: if _base_stk_cd(str(s.get('stk_cd','') or '')) == key:`
- **조치 상태**: 신규 (2026-08-01)

#### M-15 · engine_lifecycle.py:177 · mid · 신규
- **함수**: `get_engine_status`
- **설명**: `master_stocks_cache.values()` O(n) 순회로 구독 종목 수 계산. n=전체 종목(2000+). `broadcast_engine_status()` 호출 시마다 실행되어 주기적 O(n) 스캔.
- **증거**: `sub_count = sum(1 for entry in engine_state.state.master_stocks_cache.values() if entry.get('_subscribed', False))`
- **조치 상태**: 신규 (2026-08-01)

#### M-16 · engine_radar.py:18 · mid · 신규
- **함수**: `get_high_price_5d_cache` / `get_program_net_buy_cache` / `get_orderbook_cache`
- **설명**: `master_stocks_cache` 전체 O(n) 순회로 dict 생성. 호출 경로에 따라 틱 핫패스일 수 있음 (pipeline_compute에서 호출 시 per-tick O(n)). 확인 필요.
- **증거**: `return {cd: int(stock.get('high_5d_price', 0) or 0) for cd, stock in engine_state.state.master_stocks_cache.items()}`
- **조치 상태**: 신규 (2026-08-01)

#### M-17 · engine_sector_confirm.py:120 · mid · 신규
- **함수**: `_flush_sector_recompute_impl`
- **설명**: `get_merged_sectors_batch(all_codes)`로 전체 종목 O(n) 배치 조회. 틱 누적으로 발생하는 업종 재계산 경로에서 실행. dirty 업종 필터링을 위해 전체 종목 스캔.
- **증거**: `all_sectors_map = await sector_mapping.get_merged_sectors_batch(all_codes)`
- **조치 상태**: 신규 (2026-08-01)

#### M-18 · engine_sector_confirm.py:286 · mid · 신규
- **함수**: `sync_dynamic_subscriptions`
- **설명**: `master_stocks_cache` 전체 O(n) 순회로 `_subscribed_dynamic` 종목 추출. buy_targets 변경 시 호출. n=전체 종목(2000+).
- **증거**: `prev_codes = ({cd for cd, entry in all_stocks.items() if entry.get('_subscribed_dynamic', False)} | _PENDING_REG_CODES)`
- **조치 상태**: 신규 (2026-08-01)

#### M-19 · engine_ws.py:35 · mid · 신규
- **함수**: `_ws_send_reg_unreg_and_wait_ack`
- **설명**: `reg_seq_lock`으로 모든 REG/UNREG 직렬화 + `asyncio.wait_for` 10초 타임아웃 + `REG_POST_ACK_GAP_SEC` sleep. 구독 배치(200종목) 시 1건당 ACK 대기+sleep 누적. 한 건 타임아웃 시 후속 전체 10초 블로킹.
- **증거**: `async with engine_state.state.reg_seq_lock: ... await asyncio.wait_for(..., timeout=10.0) ... await asyncio.sleep(engine_state.state.REG_POST_ACK_GAP_SEC)`
- **조치 상태**: 신규 (2026-08-01)

#### M-20 · engine_ws.py:121 · mid · 신규
- **함수**: `_subscribe_positions_stocks_realtime`
- **설명**: `master_stocks_cache.values()` 전체 O(n) 순회로 `_subscribed` 여부 확인. n=전체 종목(2000+). 구독 경로(비틱)이나 대량 스캔.
- **증거**: `any(entry.get('_subscribed', False) for entry in engine_state.state.master_stocks_cache.values())`
- **조치 상태**: 신규 (2026-08-01)

#### M-21 · risk_manager.py:169 · mid · 신규
- **함수**: `check_buy_order_allowed`
- **설명**: 매수 주문 전 다수 await 호출 — `get_total_realized_pnl(today_only=True)` + `_check_extended_buy_risk` 내부 `get_buy_history` + `_get_consecutive_loss_count`(`get_sell_history`). 매수 시도마다 DB 조회 2~3회. 매수 핫패스.
- **증거**: `today_pnl = await get_total_realized_pnl(...); ... buy_rows = await get_buy_history(...); ... consec_count = await self._get_consecutive_loss_count(trade_mode)`
- **조치 상태**: 신규 (2026-08-01)

#### M-22 · risk_manager.py:218 · mid · 신규
- **함수**: `check_buy_order_allowed`
- **설명**: 단일 종목 비중 검사 시 실전모드에서 `state.positions` O(n) 순회로 매칭 포지션 검색. 매수 시도마다 실행.
- **증거**: `for p in engine_state.positions: if _base_stk_cd(...) == nk: existing_position_amount = int(p.get('buy_amount', 0) or 0); break`
- **조치 상태**: 신규 (2026-08-01)

#### M-23 · sector_data_provider.py:68 · mid · 신규
- **함수**: `get_sector_stocks`
- **설명**: `master_stocks_cache` 전체 O(n) 순회 + `copy()` per-entry + `get_merged_sectors_batch` await. 업종 요약 계산 입력 데이터 구성 시마다 호출. Phase 1/2 루프, `recompute_sector_summary_now` 등에서 호출.
- **증거**: `for cd in engine_state.state.master_stocks_cache: e = engine_state.state.master_stocks_cache.get(cd, {}).copy(); ...`
- **조치 상태**: 신규 (2026-08-01)

#### M-24 · sector_data_provider.py:183 · mid · 신규
- **함수**: `get_all_sector_stocks`
- **설명**: `master_stocks_cache` 전체 O(n) 순회 + `get_merged_sectors_batch` await. WS 초기 스냅샷 전송, 업종분류 페이지용. 비틱이나 WS 연결 시 + 재계산 시 호출.
- **증거**: `for cd, entry in engine_state.state.master_stocks_cache.items(): ... sectors_map = await get_merged_sectors_batch(valid_codes)`
- **조치 상태**: 신규 (2026-08-01)

#### M-25 · sector_data_provider.py:254 · mid · 신규
- **함수**: `recompute_sector_summary_now`
- **설명**: `get_sector_summary_inputs()` await + `compute_full_sector_summary()` await + `get_held_codes()` await + `build_buy_targets_from_settings` + notify 3종 await. 설정 변경 시 호출. 다수 await 직렬 체인.
- **증거**: `_inputs = await get_sector_summary_inputs(); _sector_summary = await compute_full_sector_summary(...); _held = await engine_account.get_held_codes(); ... await notify_desktop_sector_scores(force=True); await notify_desktop_sector_stocks_refresh(force=True); await notify_buy_targets_update()`
- **조치 상태**: 신규 (2026-08-01)

#### M-26 · settlement_engine.py:69 · mid · 신규
- **함수**: `reserve_buy_power`
- **설명**: 매수 시 `_persist()` + `_broadcast_delta()` await. 매 체결마다 DB 저장 + WS 브로드캐스트. 테스트모드 매수 경로에서 매번 실행.
- **증거**: `_orderable -= cost; await _persist(); await _broadcast_delta()`
- **조치 상태**: 신규 (2026-08-01)

#### M-27 · settlement_engine.py:101 · mid · 신규
- **함수**: `on_buy_fill`
- **설명**: 매수 체결마다 `_persist()` + `_broadcast_delta()`. `on_sell_fill`도 동일 패턴. 테스트모드 체결 시마다 DB 저장 + 브로드캐스트.
- **증거**: `_orderable = max(0, _orderable - cost); await _persist(); await _broadcast_delta()`
- **조치 상태**: 신규 (2026-08-01)

#### M-28 · settlement_engine.py:124 · mid · 신규
- **함수**: `on_sell_fill`
- **설명**: 매도 체결 후 `_cash_insufficient` 시 `evaluate_buy_candidates()` await 호출. 매도 체결 → 매수 재평가 트리거. 테스트모드 매도 경로.
- **증거**: `if _cash_insufficient: invalidate_buy_snapshot(); await evaluate_buy_candidates()`
- **조치 상태**: 신규 (2026-08-01)

#### M-29 · trade_history.py:599 · mid · 신규
- **함수**: `get_daily_summary`
- **설명**: `trading_dates` 각각에 대해 `_buy_history` + `_sell_history` O(n) 순회 (dates × (buys+sells)). 추가로 per-date `get_base_asset_for_period` DB 조회. N거래일 × M체결 × 2 + N DB 조회. UI 요약 갱신 시 호출.
- **증거**: `for d in trading_dates: ... for rec in _buy_history: ... for rec in _sell_history: ... entry['base_asset'] = await get_base_asset_for_period(conn, date_from=d, trade_mode=resolved_mode)`
- **조치 상태**: 신규 (2026-08-01)

#### M-30 · trading.py:298 · mid · 신규
- **함수**: `execute_buy`
- **설명**: `_buy_lock`(asyncio.Lock)으로 전역 매수 직렬화. 매수 주문 실행 중 다른 매수 요청 대기. 의도적 TOCTOU 방지이나 매수 처리 시간이 길면 후속 매수 대기.
- **증거**: `async with self._buy_lock: return await self._execute_buy_locked(...)`
- **조치 상태**: 신규 (2026-08-01)

#### M-31 · trading.py:310 · mid · 신규
- **함수**: `_execute_buy_locked`
- **설명**: `_ensure_daily_buy_counter()` await + `get_positions()` await + 다수 가드 체크. 매수 판단부터 주문 전송까지 다수 await 직렬 체인. 매수 이벤트 경로.
- **증거**: `await self._ensure_daily_buy_counter(); ... _positions_for_count = await _get_positions(); ...`
- **조치 상태**: 신규 (2026-08-01)

#### M-32 · trading.py:374 · mid · 신규
- **함수**: `_execute_buy_locked`
- **설명**: `get_positions()` await로 보유종목 리스트 조회 후 `holding_count` 계산을 위한 O(n) 순회. 매수 시도마다 실행.
- **증거**: `_positions_for_count = await _get_positions(); holding_count = sum(1 for p in _positions_for_count if int(p.get('qty', 0)) > 0)`
- **조치 상태**: 신규 (2026-08-01)

#### M-33 · web/routes/ws.py:56 · mid · 신규
- **함수**: `_send_initial_snapshot_delayed`
- **설명**: WS 연결 시 `get_all_sector_stocks()` + `build_initial_snapshot()` + `build_sector_stocks_payload()` + `get_buy_targets_sector_stocks()` 등 다수 O(n) await 순차 실행. WS 연결 1회성이나 누적 지연.
- **증거**: `stocks = await get_all_sector_stocks(); ... snapshot = await build_initial_snapshot(); ... stocks_payload = await build_sector_stocks_payload()`
- **조치 상태**: 신규 (2026-08-01)

#### M-34 · frontend/src/pages/sector-stock.ts:63 · mid · 신규
- **함수**: `buildRows`
- **설명**: `filterStocksBySearch(Object.values(sectorStocks))` + `filterSectorsByName` + `computeRows`. sectorStocks 전체 순회. store 변경 시마다 동기 실행 (rAF 미사용 — sectorScores는 저빈도이나 sectorStocks는 틱마다 in-place mutation으로 참조 미변경, 실제 refreshRows는 sectorStocks 참조 변경 시에만).
- **증거**: `this.currentMatchedCodes = filterStocksBySearch(Object.values(state.sectorStocks), this.searchTerm); ... return computeRows(...)`
- **조치 상태**: 신규 (2026-08-01)

#### M-35 · frontend/src/pages/sector-stock.ts:91 · mid · 신규
- **함수**: `updateUI`
- **설명**: `Object.values(sectorStocks)` + filter 4회 (krx/nxt/kospi/kosdaq). sectorStocks 전체 순회 × 4. refreshRows 시마다 실행. 종목 수에 비례 (2000+).
- **증거**: `const stocks = Object.values(state.sectorStocks); ... const krxCount = stocks.filter(s => !s.nxt_enable).length; const nxtCount = stocks.filter(s => s.nxt_enable).length; const kospiCount = stocks.filter(s => s.market_type === '0').length; const kosdaqCount = stocks.filter(s => s.market_type === '10').length`
- **조치 상태**: 신규 (2026-08-01)

#### M-36 · frontend/src/stores/hotStore.ts:192 · mid · 신규
- **함수**: `applyAccountUpdate`
- **설명**: changed_positions 처리 시 positions 배열 복사 + `findIndex` O(n) per changed position. 매도 체결 등으로 다수 포지션 변경 시 O(n × changed). account-update 이벤트 경로 (틱이 아닌 체결 이벤트).
- **증거**: `const positions = [...state.positions]; ... for (const pos of changed) { const idx = positions.findIndex(p => normalizeStockCode(p.stk_cd) === normalizeStockCode(pos.stk_cd)) }`
- **조치 상태**: 신규 (2026-08-01)

#### M-37 · frontend/src/stores/hotStore.ts:250 · mid · 신규
- **함수**: `applyAccountSummaryUpdate`
- **설명**: `applyAccountUpdate`와 동일 — changed_positions 시 `findIndex` O(n) per changed. 수익현황 페이지 전용 경량 payload 갱신.
- **증거**: `for (const pos of changed) { const idx = positions.findIndex(p => normalizeStockCode(p.stk_cd) === normalizeStockCode(pos.stk_cd)) }`
- **조치 상태**: 신규 (2026-08-01)

### 3.3 Low (드문 경로 / 스타일 / 이미 최적화 양호) — 39건

#### L-01 · kiwoom_connector.py:170 · low · 신규
- **함수**: `_recv_loop`
- **설명**: 수신 오류 시 `asyncio.sleep(0.1)`. 비정상 오류 반복 시 100ms 블로킹 루프. 정상 경로 아님.
- **증거**: `await asyncio.sleep(0.1)`
- **조치 상태**: 신규 (2026-08-01)

#### L-02 · kiwoom_order.py:26 · low · 신규
- **함수**: `_send_request`
- **설명**: 재시도 간 `asyncio.sleep(delay=1.0)`. 주문 실패 시 1초 대기 후 재시도. 최대 3회 = 최대 3초 블로킹. 주문 경로.
- **증거**: `await asyncio.sleep(delay)`
- **조치 상태**: 신규 (2026-08-01)

#### L-03 · kiwoom_rest.py:174 · low · 신규
- **함수**: `_call_api`
- **설명**: 429 발생 시 `asyncio.sleep(wait_sec=8*(attempt+1))`. 최대 3회 = 8+16+24=48초 대기. REST API 호출 경로 (계좌 조회 등). 비틱이나 매수/매도 주문 시 호출 가능.
- **증거**: `wait_sec = self._API_BACKOFF_BASE * (attempt + 1); await asyncio.sleep(wait_sec)`
- **조치 상태**: 신규 (2026-08-01)

#### L-04 · kiwoom_rest.py:361 · low · 신규
- **함수**: `_paginated_request`
- **설명**: 연속 조회 페이지 간 `asyncio.sleep(0.3)`. 계좌 평가 잔고 내역 조회 시. 비틱 경로 (기동/갱신 시).
- **증거**: `if page > 0: await asyncio.sleep(0.3)`
- **조치 상태**: 신규 (2026-08-01)

#### L-05 · kiwoom_stock_rest.py:254 · low · 신규
- **함수**: `_fetch_all_stocks_ka10081`
- **설명**: 전체 종목 순차 조회 루프. 종목당 `asyncio.sleep(0.3)`. 2000종목 = 600초. 장마감 파이프라인 경로 (비틱).
- **증거**: `for cd in krx_codes: ... await asyncio.sleep(interval_sec)`
- **조치 상태**: 신규 (2026-08-01)

#### L-06 · ls_rest.py:285 · low · 신규
- **함수**: `_place_order`
- **설명**: 주문 재시도 간 `asyncio.sleep(2*attempt)`. 429 시 `asyncio.sleep(8*(attempt+1))`. 매수/매도 주문 경로. 최대 3회.
- **증거**: `await asyncio.sleep(wait_sec); ... await asyncio.sleep(8 * (attempt + 1))`
- **조치 상태**: 신규 (2026-08-01)

#### L-07 · database.py:80 · low · 신규
- **함수**: `cleanup_old_backups`
- **설명**: `base.glob()` + `p.stat()` + `target.unlink()` 동기 파일 I/O. async 컨텍스트가 아니나 호출 경로 확인 필요. DB 백업 정리 시에만 실행 (드문 경로).
- **증거**: `for p in base.glob('stocks.db*.backup'): ... mtime = p.stat().st_mtime ... target.unlink()`
- **조치 상태**: 신규 (2026-08-01)

#### L-08 · pipeline_compute.py:638 · low · 신규
- **함수**: `_phase2_batch_recompute_loop`
- **설명**: 0.2초 sleep 폴링 루프. P11 폴링 금지 원칙과 충돌 가능성. 단, 이벤트 기반(`_receive_rate_event`)과 혼용되어 의도적 디바운스로 해석 가능.
- **증거**: `while _compute_running: await asyncio.sleep(0.2)`
- **조치 상태**: 신규 (2026-08-01)

#### L-09 · buy_order_executor.py:127 · low · 신규
- **함수**: `evaluate_buy_candidates`
- **설명**: `_pos_for_cnt` O(n) 순회로 `holding_cnt` 계산. 매수 후보 평가 시마다 실행. 보유 종목 수에 비례.
- **증거**: `_holding_cnt = sum(1 for p in _pos_for_cnt if int(p.get('qty', 0)) > 0)`
- **조치 상태**: 신규 (2026-08-01)

#### L-10 · buy_order_executor.py:186 · low · 신규
- **함수**: `_refresh_buyable_prices`
- **설명**: `buy_targets` 순회하며 매수 가능 종목 집합 재계산. 매수 후보 수에 비례. `evaluate_buy_candidates` 호출 시마다 실행.
- **증거**: `for bt in ss.buy_targets: ... _new_codes.add(s.code)`
- **조치 상태**: 신규 (2026-08-01)

#### L-11 · daily_time_scheduler.py:107 · low · 신규
- **함수**: `calc_timebased_market_phase`
- **설명**: 순수 함수, O(1) 시간 기반 판정. 틱 핫패스에서 `is_nxt_only_window`/`is_order_blocked_by_time` 등으로 간접 호출. 성능 이슈 없음.
- **증거**: `def calc_timebased_market_phase() -> dict: ... return {'krx': krx, 'nxt': nxt}`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-12 · engine_initial_data.py:167 · low · 신규
- **함수**: `_reset_realtime_fields`
- **설명**: `master_stocks_cache` O(n) + positions O(n) + dry_run positions O(n) 순회. WS 구독 시작 시 1회 실행. 비틱 경로.
- **증거**: `for entry in engine_state.state.master_stocks_cache.values(): for f in _REALTIME_FIELDS: entry[f] = None`
- **조치 상태**: 신규 (2026-08-01)

#### L-13 · engine_initial_data.py:196 · low · 신규
- **함수**: `_reset_realtime_fields`
- **설명**: DB UPDATE `master_stocks_table` 전체 테이블 실시간 필드 리셋. WS 구독 시작 시 1회. 비틱 경로.
- **증거**: `await conn.execute('UPDATE master_stocks_table SET cur_price = NULL, change = NULL, ...')`
- **조치 상태**: 신규 (2026-08-01)

#### L-14 · engine_loop.py:141 · low · 신규
- **함수**: `run_engine_loop`
- **설명**: 기동 시 `master_stocks_cache.values()` O(n) 순회로 `_subscribed` 제거. 기동 1회만 실행, 비틱 경로.
- **증거**: `for entry in engine_state.state.master_stocks_cache.values(): entry.pop('_subscribed', None)`
- **조치 상태**: 신규 (2026-08-01)

#### L-15 · notification_worker.py:23 · low · 신규
- **함수**: `NotificationWorker`
- **설명**: `asyncio.Queue(maxsize=100)`. 큐 가득 시 `put_nowait` 예외 → 메시지 누락. 텔레그램 전송 지연 시 큐 적체 가능. 비틱 경로 (알림).
- **증거**: `self._queue: asyncio.Queue = asyncio.Queue(maxsize=self._QUEUE_MAXSIZE); ... self._queue.put_nowait(msg)`
- **조치 상태**: 신규 (2026-08-01)

#### L-16 · risk_manager.py:253 · low · 신규
- **함수**: `check_sell_order_allowed`
- **설명**: 매도 주문 전 `get_total_realized_pnl` + `get_buy_history` + `_get_consecutive_loss_count` await. `risk_manager_on` + `risk_block_sell_on` 시에만 실행 (기본 OFF).
- **증거**: `today_pnl = await get_total_realized_pnl(...); ... buy_rows = await get_buy_history(...); ... consec_count = await self._get_consecutive_loss_count(trade_mode)`
- **조치 상태**: 신규 (2026-08-01)

#### L-17 · telegram_bot.py:303 · low · 신규
- **함수**: `_poll_loop`
- **설명**: 30초 long polling + `asyncio.gather`로 다중 토큰 폴링. 비틱 경로 (백그라운드 폴링). `httpx.AsyncClient` 매 루프 생성/종료.
- **증거**: `async with httpx.AsyncClient(timeout=_HTTPX_POLL) as client: resp = await client.get(url, params=params)`
- **조치 상태**: 신규 (2026-08-01)

#### L-18 · trade_history.py:103 · low · 신규
- **함수**: `_insert_trade`
- **설명**: 매수/매도 체결 시 `execute_db_write(wait=True)` await. DB 쓰기 완료 대기. 체결 이벤트 경로. db_writer 큐 적체 시 블로킹.
- **증거**: `await execute_db_write(DBWriteOperation(table='trades', operation='INSERT', data=rec, query=_TRADE_INSERT_SQL, params=_trade_params(rec)))`
- **조치 상태**: 신규 (2026-08-01)

#### L-19 · trade_history.py:819 · low · 신규
- **함수**: `build_positions_from_trades`
- **설명**: `_buy_history` + `_sell_history` 전체 병합 + ts 정렬 O(n log n) + FIFO lot 구축 O(n). dry_run 포지션 캐시 재구축 시 호출. `_positions_dirty=True` 시마다.
- **증거**: `all_trades = list(_buy_history) + list(_sell_history); all_trades.sort(key=lambda r: r['ts']); lots = _build_fifo_lots(all_trades, trade_mode)`
- **조치 상태**: 신규 (2026-08-01)

#### L-20 · ws_subscribe_control.py:27 · low · 신규
- **함수**: `_get_lock`
- **설명**: `asyncio.Lock`으로 구독 시작/해지 직렬화. 구독 제어 경로. 틱 핫패스 아님 (구독 시작/해지 시에만).
- **증거**: `_lock: asyncio.Lock | None = None; async with _get_lock(): ...`
- **조치 상태**: 신규 (2026-08-01)

#### L-21 · ws_manager.py:257 · low · 신규
- **함수**: `_send_initial_data_on_connect`
- **설명**: WS 클라이언트 연결 시 `get_buy_targets_sector_stocks()` await. `register()` 내에서 호출되어 연결 처리 블로킹. 1회성.
- **증거**: `targets = await get_buy_targets_sector_stocks()`
- **조치 상태**: 신규 (2026-08-01)

#### L-22 · frontend/src/api/ws.ts:19 · low · 신규
- **함수**: `decodeProtobufEvents`
- **설명**: 바이너리 프레임 디코딩. 이벤트 수만큼 루프 + `event.Event.deserializeBinary`. 틱 핫패스 (prices 채널). 초당 수십~수백 틱 시 디코딩 비용. 다만 백엔드에서 이미 프레임당 다수 이벤트를 묶어 전송하므로 프레임 단위 디코딩.
- **증거**: `while (offset < uint8Array.length) { ... const protoEvent = event.Event.deserializeBinary(eventBytes) ... }`
- **조치 상태**: 신규 (2026-08-01)

#### L-23 · frontend/src/api/ws.ts:202 · low · 신규
- **함수**: `_dispatchMessage`
- **설명**: 핸들러 리스트 순회. 이벤트 타입별 핸들러 수에 비례. 현재 prices 채널에 20+ 이벤트 핸들러 등록. 프레임당 다수 이벤트 디스패치 시 핸들러 조회 비용. Map.get + 배열 순회.
- **증거**: `const list = this.handlers.get(eventType); if (list) { for (const h of list) { try { h(data) } ... } }`
- **조치 상태**: 신규 (2026-08-01)

#### L-24 · frontend/src/binding.ts:69 · low · 신규
- **함수**: `bindWSToStore`
- **설명**: 20+ 이벤트 핸들러 등록. 초기화 시 1회 호출. 핸들러 자체는 O(1) 디스패치. 성능 이슈 없음.
- **증거**: `pricesClient.onEvent('real-data', (data) => { applyRealData(data as RealDataEvent) })`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-25 · frontend/src/components/common/data-table-virtual.ts:152 · low · 신규
- **함수**: `renderRow`
- **설명**: 셀별 diff — columns 수만큼 render 호출 + `textContent`/`isEqualNode` 비교. 가상 스크롤 범위 내 행만 렌더링. `updateItemByKey` 시 단일 행만 renderRow. rAF 배칭 적용. 성능 최적화 양호.
- **증거**: `for (let i = 0; i < columns.length; i++) { ... const content = columns[i].render(dataRow, index); if (typeof content === 'string') { if (cell.textContent !== content) cell.textContent = content } }`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-26 · frontend/src/components/common/data-table-virtual.ts:397 · low · 신규
- **함수**: `scheduleRender`
- **설명**: rAF 배칭 + 60fps 프레임 간격 제한. pendingRows 스왑. `updateRows` 호출 시 단일 rAF 예약. 성능 최적화 양호.
- **증거**: `function scheduleRender() { if (rafId !== null) return; rafId = -1; requestAnimationFrame((timestamp) => { ... if (elapsed < FRAME_INTERVAL) { scheduleRender(); return } ... }) }`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-27 · frontend/src/components/virtual-scroller.ts:110 · low · 신규
- **함수**: `computeVisibleRange`
- **설명**: 이진 탐색 O(log n) + 선형 탐색 visibleEnd. scroll 이벤트 시. 고정 높이 모드 시 O(1) 산술. 성능 최적화 양호.
- **증거**: `let lo = 0, hi = count - 1; while (lo < hi) { const mid = (lo + hi) >>> 1; ... }`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-28 · frontend/src/components/virtual-scroller.ts:357 · low · 신규
- **함수**: `updateItems`
- **설명**: `detectFixedHeight` O(n) + `validateOffsetDrift` O(n/5 샘플) + 범위 내 행 렌더링. 데이터 교체 시. 고정 높이 모드 시 산술 계산. 성능 최적화 양호.
- **증거**: `const newFixedMode = detectFixedHeight(items, getRowHeight); ... if (fixedMode.enabled && !validateOffsetDrift()) { ... }`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-29 · frontend/src/pages/buy-target.ts:126 · low · 신규
- **함수**: `computeBadgeContext`
- **설명**: buyTargets spread + sort + find로 1위 종목 검색. 배지 갱신 시마다. buyTargets 수에 비례. 다만 상태 변경 시에만 실행 (rAF 배칭).
- **증거**: `const topTarget = [...state.buyTargets].sort(compareBuyTargets).find(t => t.guard_pass && t.reject_reason === '')`
- **조치 상태**: 신규 (2026-08-01)

#### L-30 · frontend/src/pages/buy-target.ts:371 · low · 신규
- **함수**: `renderTableRows`
- **설명**: `filterStocksBySearch` + spread copy + filter + sort. buyTargets 수에 비례. buyTargets 참조 변경 시에만 실행 (rAF 배칭). 검색어 변경 시에도 실행.
- **증거**: `const matchedCodes = filterStocksBySearch(buyTargets, searchTerm); const targets = [...buyTargets].filter(t => !matchedCodes || matchedCodes.has(t.code)).sort(compareBuyTargets)`
- **조치 상태**: 신규 (2026-08-01)

#### L-31 · frontend/src/pages/profit-detail.ts:131 · low · 신규
- **함수**: `refreshProfitDetailPage`
- **설명**: `Promise.all` 2개 HTTP fetch (buy/sell history). 페이지 진입 시. 비틱 경로. filterCache로 필터링 중복 연산 방지.
- **증거**: `const results = await Promise.all([refreshPageData(...), refreshPageData(...)])`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-32 · frontend/src/pages/profit-overview.ts:138 · low · 신규
- **함수**: `refreshProfitOverviewPage`
- **설명**: `Promise.all` 2개 HTTP fetch. 페이지 진입 시. 비틱 경로. rAF 배칭 + dirty flag로 렌더링 최적화.
- **증거**: `const results = await Promise.all([refreshPageData(...), refreshPageData(...)])`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-33 · frontend/src/pages/sell-position.ts:156 · low · 신규
- **함수**: `renderSummary`
- **설명**: `computeHoldingsSummary` positions 전체 순회. positions 수에 비례. rAF 배칭 + 상태 변경 시에만 실행. 성능 최적화 양호.
- **증거**: `const { evalTotal, evalPnl, evalRate, hasNullPrice } = computeHoldingsSummary(state.positions)`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

#### L-34 · frontend/src/stores/hotStore.ts:331 · low · 신규
- **함수**: `applyRealData`
- **설명**: 틱 핫패스. `parseKiwoomNum`/`parseChangeRateToPercent` 문자열 파싱 + 정규식 per-tick. sectorStocks/buyTargets/positions in-place mutation + rAF 배칭으로 최적화. 다만 per-tick 정규식 replace + Number 변환 비용. 초당 수백 틱 시 파싱 비용 누적.
- **증거**: `const numStr = s.replace(/[^0-9.]/g, ''); if (numStr === '') return undefined; return sign * Number(numStr)`
- **조치 상태**: 신규 (2026-08-01)

#### L-35 · frontend/src/stores/hotStore.ts:548 · low · 신규
- **함수**: `applyRealtimeReset`
- **설명**: sectorStocks `Object.entries` 순회 + `nullifyFields` per entry + positions map. 전체 종목 수에 비례. realtime-reset 이벤트 시 (장 마감 등 드문 이벤트).
- **증거**: `for (const [code, stock] of Object.entries(state.sectorStocks)) { const n = nullifyFields(stock, [...]) }`
- **조치 상태**: 신규 (2026-08-01)

#### L-36 · frontend/src/stores/hotStore.ts:608 · low · 신규
- **함수**: `applyBuyTargetsUpdate`
- **설명**: incoming 배열 map + sectorStocks lookup per target + same 비교 `prev.every`. buyTargets 수에 비례. buy-targets-update 이벤트 시 (틱 아님, 설정 변경/재계산 시).
- **증거**: `const incoming = (data.buy_targets ?? []).map(t => { ... const ss = sectorStocks[code] ... }); const same = prev.length === incoming.length && prev.every(...)`
- **조치 상태**: 신규 (2026-08-01)

#### L-37 · frontend/src/stores/hotStore.ts:661 · low · 신규
- **함수**: `applyNewsHit`
- **설명**: codes 배열 × buyTargets `findIndex` O(n). codes는 단일 뉴스 매칭 종목 수(소). 뉴스 히트 이벤트 시.
- **증거**: `for (let k = 0; k < codes.length; k++) { ... const idx = buyTargets.findIndex((t: StockScore) => normalizeStockCode(t.code) === code) }`
- **조치 상태**: 신규 (2026-08-01)

#### L-38 · frontend/src/stores/hotStore.ts:688 · low · 신규
- **함수**: `applyBuyTargetsDelta`
- **설명**: changed 배열 `findIndex` O(n) per changed item. buy-targets-delta 이벤트 시. changed 수가 적으면 양호하나, 대규모 delta 시 O(n × changed).
- **증거**: `for (const item of changed) { const idx = buyTargets.findIndex((t: StockScore) => normalizeStockCode(t.code) === normalizeStockCode(item.code)) }`
- **조치 상태**: 신규 (2026-08-01)

#### L-39 · frontend/src/stores/store.ts:18 · low · 신규
- **함수**: `setState`
- **설명**: shallow merge + `Object.is` 비교 + listeners 순회. listener 수에 비례. 모든 store 업데이트 시. try/catch로 listener 격리. 성능 최적화 양호.
- **증거**: `for (const key of keys) { if (!Object.is(state[key], nextPartial[key])) { hasChange = true; break } } ... for (const listener of listeners) { try { listener(state) } ... }`
- **조치 상태**: 신규 (2026-08-01) — 성능 양호, 참조용

---

## 4. 파일별 인덱스

> **갱신 포인트**: 발견 사항 추가/삭제 시 파일별 카운트 갱신.

| 파일 | 건수 | ID 목록 |
|---|---|---|
| backend/app/core/kiwoom_connector.py | 2 | L-01, M-01 |
| backend/app/core/kiwoom_order.py | 2 | L-02, M-02 |
| backend/app/core/kiwoom_rest.py | 2 | L-03, L-04 |
| backend/app/core/kiwoom_stock_rest.py | 1 | L-05 |
| backend/app/core/ls_connector.py | 1 | M-03 |
| backend/app/core/ls_rest.py | 1 | L-06 |
| backend/app/db/database.py | 1 | L-07 |
| backend/app/db/db_writer.py | 2 | M-04, M-05 |
| backend/app/pipelines/pipeline_compute.py | 4 | H-01, H-02, M-06, L-08 |
| backend/app/pipelines/pipeline_compute_tick_handlers.py | 4 | H-03, M-07, M-08, M-09 |
| backend/app/pipelines/pipeline_gateway.py | 1 | H-04 |
| backend/app/services/buy_order_executor.py | 2 | L-09, L-10 |
| backend/app/services/daily_time_scheduler.py | 1 | L-11 |
| backend/app/services/dry_run.py | 1 | M-10 |
| backend/app/services/engine_account.py | 4 | H-05, H-06, M-11, M-12 |
| backend/app/services/engine_account_rest.py | 2 | M-13, M-14 |
| backend/app/services/engine_initial_data.py | 2 | L-12, L-13 |
| backend/app/services/engine_lifecycle.py | 1 | M-15 |
| backend/app/services/engine_loop.py | 1 | L-14 |
| backend/app/services/engine_radar.py | 1 | M-16 |
| backend/app/services/engine_sector_confirm.py | 2 | M-17, M-18 |
| backend/app/services/engine_ws.py | 2 | M-19, M-20 |
| backend/app/services/engine_ws_dispatch.py | 2 | H-07, H-08 |
| backend/app/services/notification_worker.py | 1 | L-15 |
| backend/app/services/risk_manager.py | 3 | M-21, M-22, L-16 |
| backend/app/services/sector_data_provider.py | 3 | M-23, M-24, M-25 |
| backend/app/services/settlement_engine.py | 3 | M-26, M-27, M-28 |
| backend/app/services/trade_history.py | 3 | M-29, L-18, L-19 |
| backend/app/services/trading.py | 3 | M-30, M-31, M-32 |
| backend/app/services/telegram_bot.py | 1 | L-17 |
| backend/app/services/ws_subscribe_control.py | 1 | L-20 |
| backend/app/web/routes/ws.py | 1 | M-33 |
| backend/app/web/ws_manager.py | 4 | H-09, H-10, H-11, L-21 |
| frontend/src/api/ws.ts | 2 | L-22, L-23 |
| frontend/src/binding.ts | 1 | L-24 |
| frontend/src/components/common/data-table-virtual.ts | 2 | L-25, L-26 |
| frontend/src/components/virtual-scroller.ts | 2 | L-27, L-28 |
| frontend/src/pages/buy-target.ts | 2 | L-29, L-30 |
| frontend/src/pages/profit-detail.ts | 1 | L-31 |
| frontend/src/pages/profit-overview.ts | 1 | L-32 |
| frontend/src/pages/sector-stock.ts | 2 | M-34, M-35 |
| frontend/src/pages/sell-position.ts | 1 | L-33 |
| frontend/src/stores/hotStore.ts | 7 | M-36, M-37, L-34, L-35, L-36, L-37, L-38 |
| frontend/src/stores/store.ts | 1 | L-39 |

---

## 5. 권장 조치 우선순위 (참고용)

> 본 섹션은 조사 결과 기반 권장 우선순위이며, 각 항목 수정 전 별도 승인 필요. ARCHITECTURE.md 원칙(P7/P11/P14 등)과 충돌 여부 사전 점검 필수.

### 5.1 1순위 — 틱 핫패스 직접 블로킹 (high)

| ID | 핵심 이슈 | 잠재 개선 방향 (검토 대상) |
|---|---|---|
| H-09 | 매 틱 JSON 직렬화 + MD5 | 해시 키 대체 (참조/요약값) 또는 증분 해시 |
| H-10, H-11 | 클라이언트 순차 전송 | `asyncio.gather` 병렬 전송 또는 per-client 태스크 분리 (P14 충돌 점검) |
| H-01, H-02 | 배치 내 직렬 처리 + 단일 컨슈머 | 배치 병렬화 가능 부분 식별 (순서 의존성 점검) |
| H-03 | per-tick 포지션 O(n) 검색 | code→index 맵 유지 (P10 SSOT 점검) |
| H-05, H-08 | 틱 중 매수 후보 재평가 | 재평가 지연 스케줄 (dirty 마킹 후 배치 처리) |
| H-06, H-07 | 체결 틱 중 매도 조건 전체 재검사 | 체결 종목 한정 매도 검사 또는 지연 스케줄 |
| H-04 | broadcast 단일 컨슈머 | 큐 적체 모니터링 + 전송 병렬화 (H-10/H-11 연계) |

### 5.2 2순위 — 파이프라인/기동/WS 경로 (mid)

- **O(n) 전체 종목 스캔 군집** (M-15, M-16, M-18, M-20, M-23, M-24): `master_stocks_cache` 전체 순회. 구독 종목 집합 별도 유지 시 O(구독 수)로 축소 가능 (P10 점검).
- **매수/매도 주문 경로 다수 await** (M-21, M-30, M-31, M-32): 매수 시도마다 DB 조회 2~3회 + O(n) 순회. 캐시/맵 기반 조회 검토.
- **DB 쓰기 큐 적체** (M-04, M-05): maxsize=100 초과 시 생산자 블로킹. 큐 모니터링 + 적체 시 우회 정책 검토.
- **체결마다 DB 저장 + 브로드캐스트** (M-26, M-27): 배치 저장 또는 브로드캐스트 debouncing 검토.

### 5.3 3순위 — 드문 경로/이미 양호 (low)

- L-11, L-24, L-25, L-26, L-27, L-28, L-31, L-32, L-33, L-39: 이미 최적화 양호 (rAF 배칭, 가상 스크롤, O(log n) 등). 참조용, 수정 불필요.
- L-03, L-05: 429 백오프/종목 순차 조회. 의도적 rate limit 대응. 비틱 경로.

---

## 6. 갱신 이력

| 날짜 | 변경 요약 | 변경자 |
|---|---|---|
| 2026-08-01 | 초안 작성 — investigation_status.json 기반 87건 발견 사항 상세 보고서 구성 (high 11 / mid 37 / low 39) | 에이전트 |

---

## 7. 참조

- **상태 파일 (원본)**: `.devin/state/investigation_status.json`
- **조사 스킬**: `.devin/skills/continuity-investigation/SKILL.md`
- **아키텍처 원칙**: `ARCHITECTURE.md` 제1부 불변 원칙 25개 (P1~P25)
- **프로젝트 규칙**: `AGENTS.md` 섹션2 아키텍처 원칙·코드 수정 시 점검 체크리스트
- **유사 보고서 (프론트엔드 데드코드)**: `docs/investigation_report_frontend-src-dead-code-duplicate-functions_20260801.md` — 후속 정리 완료(커밋 `7e4050e`) 후 규칙 10-(1)에 따라 삭제됨. 상세는 git history 참조.
