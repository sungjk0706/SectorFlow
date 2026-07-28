# C-05 스케줄러·장마감 파이프라인·실시간 엔진 경계

> 작성일: 2026-07-26
> 기준 계획서: `docs/coupling-audit-plan.md` C-05
> 상태: 조사 완료 (코드 수정 없음 — 문서만 작성)
> 대상 원칙: P8/P9 경계 보존, P10 SSOT, P11 이벤트 기반 처리, P16 살아있는 경로, P20 폴백 금지, P24 단순성, P25 격리된 실패

---

## 1. 조사 범위 및 방법

### 1.1 조사 대상 파일

| 파일 | 줄 수 | 역할 |
|------|-------|------|
| `backend/app/services/daily_time_scheduler.py` | 1510 | KST 시간표 기반 단일 call_later 스케줄러 — 시간 이벤트 → WS 구독·파이프라인·페이즈 전환·자정 리셋·자동매매 전환 트리거 |
| `backend/app/services/market_close_pipeline.py` | 1425 | 장마감 확정 데이터 파이프라인 본체 — 7단계(전종목 조회→필터→해석→DB 저장→일봉 다운로드→메모리 교체→업종 재계산) + KRX 단독 종목 REMOVE + 5거래일 일봉 수동 다운로드 |
| `backend/app/pipelines/pipeline_compute.py` | 696 | Compute Engine — tick_queue 소비 + control_queue 제어 신호 + Phase 1(수신율 임계값 대기) + Phase 2(0.2초 배치 증분 재계산) |
| `backend/app/pipelines/pipeline_compute_tick_handlers.py` | 388 | 틱 타입별 leaf 핸들러 — 0J 업종지수/01 체결/0D 호가/PGM 프로그램/NWS 뉴스 + 01 코얼레싱 |
| `backend/app/pipelines/pipeline_gateway.py` | 123 | 화면 전송기 — broadcast_queue 컨슘 → ws_manager.broadcast |
| `backend/app/services/engine_loop.py` | 405 | 엔진 메인 루프 — 캐시·토큰·스펙 병렬 초기화 + WS 구간 감지 루프(연결/해제 단일 책임) |
| `backend/app/services/engine_sector_confirm.py` | 414 | 업종 재계산 — dirty 마킹 + 증분/전체 재계산 + buy_targets 변경 감지 + 동적 구독 갱신 + 매수 후보 평가 트리거 |
| `backend/app/services/notification_worker.py` | 93 | asyncio.Queue 기반 텔레그램 알림 워커 (싱글톤) |
| `backend/app/services/buy_order_executor.py` | 235 | 매수 후보 실행기 — evaluate_buy_candidates() 사전 게이트 + execute_buy() 단일 경로 호출 |
| `backend/app/services/core_queues.py` | 85 | 전역 큐 3종(tick/broadcast/control) 싱글톤 — initialize/clear |
| `backend/app/services/sector_data_provider.py` (참조) | — | recompute_sector_summary_now() — 전체 재계산 + 알림 3종 + 매수 후보는 별도 루프에서 |
| `backend/app/web/app.py` (참조) | — | lifespan — 큐 초기화·게이트웨이·스케줄러·엔진 기동/종료 순서 고정 |

### 1.2 조사 방법

- `daily_time_scheduler|market_close_pipeline|pipeline_compute|pipeline_gateway|notification_worker|engine_sector_confirm|engine_loop` 전체 grep → 참조 파일 28건 식별
- `schedule_engine_task|create_task` 호출부 전수 grep (scheduler 15건, 전체 범위)
- `^async def |^def |^class` 로 각 파일 구조·줄 범위 추출
- `engine_lifecycle.py`·`app.py`에서 기동/종료 순서·백그라운드 태스크 취소 대상 추적
- `recompute_sector_summary_now` 호출부 추적 — scheduler 4곳 + compute 2곳 + sector_confirm 2곳
- `evaluate_buy_candidates` 호출부 추적 — sector_confirm 2곳(_full_recompute, _flush_sector_recompute_impl)
- `broadcast_queue.put_nowait`/`broadcast_to_pages`/`ws_manager.broadcast` 전수 grep → WS 전송 경로 분류
- `aiosqlite execute/executemany` 호출부 전수 grep → DB 쓰기 위치 식별 (market_close_pipeline 집중)
- `try/except` 패턴 점검 → silent `except: pass` 0건, `logger.warning(..., exc_info=True)` 일관 적용 확인

---

## 2. 시스템 기동 순서 (app.py lifespan)

> `app.py:60-191` — 모든 파이프라인 컴포넌트의 생명주기는 lifespan 1곳에서 고정.

### 2.1 기동 순서 (startup)

```
1. initialize_queues()                          app.py:64-65   — tick/broadcast/control 큐 싱글톤 생성
2. start_gateway_loop() (create_task)           app.py:68-69   — broadcast_queue 컨슈머 백그라운드 시작
3. 거래일 캐시·필터 메타·설정 3개 병렬 로드      app.py:88-92   — asyncio.gather
4. build_engine_settings_dict(settings)         app.py:101-104 — 정규화 → integrated_system_settings_cache 주입
5. _sync_nws_settings_to_state(normalized)      app.py:107-108 — NWS 키워드·가산점 메모리 동기화
6. journal.start_consumer_task()                app.py:122-123 — 저널 처리 백그라운드 시작
7. state.server_ready_event.set()               app.py:128     — Health endpoint 즉시 응답 허용
8. _engine_init_background() (create_task)      app.py:134-159
   8a. start_engine(user_id="admin")            engine_lifecycle.py:33-55
       - engine_task = create_task(_engine_loop())  → engine_loop.run_engine_loop()
       - 테스트모드 포지션 구축 (P25 격리)
       - _apply_pending_settings_on_startup()
       - broadcast_engine_status()
   8b. state.engine_ready_event.set()
   8c. start_daily_time_scheduler()             daily_time_scheduler.py:1458
       - _apply_auto_toggle_on_startup(settings)
       - calc_timebased_market_phase() → state.market_phase 초기화
       - _broadcast_market_phase() (기동 시 1회)
       - schedule_auto_trade_timers(settings) — buy/sell 구간 call_later 4건
       - schedule_midnight_timer() — 자정 call_later 1건
       - build_timetable_from_cache(settings) → _TIMETABLE 11~12항목 빌드
       - _timetable_startup_scan() → _schedule_next_timetable_event() 1건 예약
   8d. telegram_bot.start() (3초 지연, tele_on 시만)
```

### 2.2 종료 순서 (shutdown)

```
1. ws_manager.close_all()                       app.py:166-168 — WS 클라이언트 정상 종료 (EPIPE 방지)
2. journal.stop_consumer_task()                 app.py:174-176
3. telegram_bot.stop_async()                    app.py:178
4. stop_engine()                                app.py:179 → engine_lifecycle.py:69-115
   - state.running = False, engine_stop_event.set()
   - cancel_recompute_timer() / cancel_all_dynamic_unreg_timers() / _PENDING_REG_CODES.clear()
   - engine_task.cancel() + await
   - 백그라운드 태스크 일괄 취소 (이름 "daily_time_scheduler" 포함)
   - clear_all_queues() — 큐 잔류 데이터 제거 (P16/P22)
5. NotificationWorker.shutdown()                app.py:182-184 — 큐 잔량 처리 후 종료 (graceful, 10초 타임아웃)
6. stop_gateway_loop()                          app.py:187-188 — broadcast_queue 컨슘 중단
7. stop_daily_time_scheduler()                  app.py:191 — 모든 타이머 취소
```

**P25 격리된 실패 준수**: 각 단계 독립 try/except, 한 단계 실패가 다음 단계 블로킹 금지.
**종료 순서 의미**: 엔진 루프 먼저 종료 → 알림 워커가 엔진 잔량 알림 처리 → 게이트웨이가 broadcast_queue 잔량 전송 → 스케줄러 타이머 정리. 순서 역순 시 큐 잔량 손실 위험.

---

## 3. scheduler → pipeline → compute → candidate → notification 호출 그래프

### 3.1 전체 호출 그래프 (단계별 입력·출력·side effect)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [A] 시간 이벤트 (scheduler)                                                    │
│  daily_time_scheduler.py — call_later 단일 타이머 (_schedule_next_timetable_event)│
│                                                                                  │
│  _TIMETABLE 11~12항목 (build_timetable_from_cache):                             │
│   - 3 direct: 07:58 실시간 필드 리셋 / 07:59 WS 구독 사전 / 08:59 KRX 사전 구독  │
│   - 1 direct: timetable.confirmed_download (기본 20:40, 토글 게이트)             │
│   - 7 phase:  08:00/09:00/09:00:30/15:20/15:30/15:40/20:00                      │
│   - 24 countdown: 카운트다운 보조 (JIF override 시 스킵)                         │
│                                                                                  │
│  별도 call_later 타이머:                                                         │
│   - schedule_auto_trade_timers: buy/sell start/end 4건                          │
│   - schedule_midnight_timer: 자정 1건                                           │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (schedule_engine_task로 격리)
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [B] 페이즈 전환 부작용 (_apply_market_phase:738-783)                            │
│  단일 적용 경로 (P10 SSOT) — JIF 경로(engine_ws_dispatch)와 시간 기반 경로 공통  │
│                                                                                  │
│  입력: phase dict {krx, nxt}                                                     │
│  side effect:                                                                    │
│   - state.market_phase[krx/nxt] 갱신                                             │
│   - WS: _broadcast("market-phase", ...) (engine_account_notify)                 │
│   - WS: _broadcast("order-time-blocked", {blocked, reason})                     │
│   - 페이즈 변경 감지 시:                                                         │
│     NXT "프리마켓" → _on_nxt_premarket_start() + _on_ws_subscribe_start()       │
│     KRX "정규장" → _on_krx_market_open()                                         │
│     KRX "종가 동시호가" → _on_krx_closing_auction_start()                        │
│     NXT "장마감" → _on_ws_subscribe_end()                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┬───────────────────┐
        ▼                     ▼                     ▼                   ▼
┌───────────────┐  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│ [C] WS 구독   │  │ [D] 업종 재계산  │  │ [E] WS 구독 해지│  │ [F] 확정 다운로드│
│ _on_ws_       │  │ _on_nxt_pre_     │  │ _on_ws_         │  │ _on_confirmed_   │
│ subscribe_    │  │ market_start /   │  │ subscribe_end   │  │ download         │
│ start (07:59) │  │ _on_krx_market_  │  │ (20:00)         │  │ (timetable.conf  │
│               │  │ open / _on_krx_  │  │                  │  │  irmed_download) │
│ side effect:  │  │ closing_auction_ │  │ side effect:    │  │                  │
│ - GC 비활성화 │  │ start            │  │ - GC 정상화     │  │ → _fire_unified_ │
│ - 실시간 필드 │  │                  │  │ - mark_sector_  │  │   confirmed_     │
│   초기화      │  │ → recompute_     │  │   threshold_    │  │   fetch()        │
│ - reset_      │  │   sector_        │  │   passed()      │  │ - confirmed_done │
│   sector_     │  │   summary_now()  │  │ - _trigger_     │  │   =True (가드)   │
│   threshold() │  │   (sector_data_  │  │   unreg_all()   │  │                  │
│ - notify_     │  │    provider)     │  │ - _set_status   │  │ → _do_unified_   │
│   cache.prev_ │  │ - notify 3종     │  │   (quote=False) │  │   confirmed_     │
│   scores=[]   │  │   (sector_scores │  │ - _broadcast_   │  │   fetch()        │
│ - sector_     │  │   /stocks_refresh│  │   market_phase()│  │                  │
│   summary_    │  │   /buy_targets)  │  │ - ws_window_    │  │ → fetch_unified_ │
│   cache=None  │  │ - state.sector_  │  │   changed_event │  │   confirmed_data │
│ - _broadcast_ │  │   summary_       │  │   .set()        │  │   (market_close_ │
│   market_     │  │   cache 갱신     │  │                  │  │    pipeline)     │
│   phase()     │  │ - sector_        │  │                  │  │                  │
│ - ws_window_  │  │   summary_ready_ │  │                  │  │                  │
│   changed_    │  │   event.set()    │  │                  │  │                  │
│   event.set() │  │                  │  │                  │  │                  │
└───────────────┘  └──────────────────┘  └─────────────────┘  └──────────────────┘
                                                                        │
                                                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [G] 장마감 파이프라인 (market_close_pipeline._run_confirmed_pipeline:999-1085) │
│  7단계 순차 파이프라인 (check_scheduler=True, check_time_guard=True):           │
│                                                                                  │
│  입력: integrated_system_settings_cache (스냅샷)                                  │
│  게이트: confirmed_refresh_running_confirmed (중복 실행 방지, P10 SSOT)          │
│                                                                                  │
│  Step 1: _step1_fetch_all_stocks — 전종목 리스트 다운로드 (ka10099)              │
│    입력: _sector (broker provider), _broker_name                                  │
│    출력: records list                                                             │
│    WS: _broadcast_confirmed_progress(step=1)                                      │
│                                                                                  │
│  Step 2: _step2_filter_eligible — 적격 종목 필터링                                │
│    입력: records                                                                  │
│    출력: (confirmed_codes set, filter_summary_meta str)                           │
│    WS: _broadcast_confirmed_progress(step=2)                                      │
│                                                                                  │
│  Step 3: _step3_parse_confirmed — 적격 종목 해석/매칭                             │
│    입력: records, confirmed_codes                                                 │
│    출력: (name_map, market_map)                                                   │
│    WS: _broadcast_confirmed_progress(step=3)                                      │
│                                                                                  │
│  Step 4: _step4_save_to_db_and_cache — DB 저장 + 메모리 동기화 + 레이아웃         │
│    입력: records, confirmed_codes, filter_summary_meta, name_map                  │
│    DB: master_stocks_table INSERT/UPSERT, system_state_cache UPSERT               │
│    DB: stock_5d_bars 정리 (master_codes 외 종목 삭제)                              │
│    메모리: master_stocks_cache 갱신 (confirmed_codes 외 종목 pop)                  │
│    메모리: sync_sector_from_custom_sectors()                                       │
│    메모리: _update_layout_cache(all_codes, name_map) → sector_stock_layout 갱신   │
│    WS: broadcast_stock_classification_changed()                                   │
│    WS: _broadcast_confirmed_progress(step=4)                                      │
│    출력: all_codes list                                                            │
│                                                                                  │
│  시간 가드: is_heavy_operation_allowed() — 안전 구역 외 시 5단계 생략             │
│                                                                                  │
│  Step 5: _step5_download_daily_confirmed — 일봉 차트 시세 다운로드 (ka10081)      │
│    입력: all_codes, name_map, confirmed_codes, qry_dt(직전 거래일)                │
│    WS: _broadcast_confirmed_progress(step=5, 진행률/ETA)                          │
│    → _apply_confirmed_to_memory(normalized_confirmed)                             │
│    → execute_unified_rolling_and_save(normalized_confirmed, qry_dt)               │
│      DB: stock_5d_bars INSERT OR REPLACE (당일 세로 행)                            │
│      DB: stock_5d_bars DELETE (dt > qry_dt, 미확정 당일 행 제거, P22)             │
│      DB: master_stocks_table UPSERT (avg_5d/high_5d 재계산 반영)                  │
│      메모리: master_stocks_cache cur_price/change/change_rate/trade_amount 갱신   │
│      메모리: master_stocks_cache avg_5d_trade_amount/high_5d_price 갱신           │
│    WS: broadcast_stock_classification_changed()                                   │
│    → _run_post_confirmed_pipeline(eligible_codes=confirmed_codes)                 │
│      → _save_confirmed_cache(eligible_codes)                                      │
│        DB: master_stocks_table UPSERT (eligible_codes만, P10 SSOT)                │
│    메모리: _subscribed 플래그 정리 (confirmed_codes 외)                            │
│    출력: (fetched, failed, cached)                                                │
│                                                                                  │
│  Step 7: _step7_recompute_and_broadcast — 업종순위 재계산 + 실시간 전송           │
│    → _calculate_receive_rate() + _send_receive_rate() (pipeline_compute)          │
│    → notify_desktop_sector_stocks_refresh(force=True)                             │
│    → recompute_sector_summary_now() (sector_data_provider)                        │
│      → compute_full_sector_summary()                                              │
│      → build_buy_targets_from_settings()                                          │
│      → state.sector_summary_cache 갱신                                             │
│      → notify_desktop_sector_score(force=True)                                    │
│      → notify_desktop_sector_stocks_refresh(force=True)                           │
│      → notify_buy_targets_update()                                                │
│      → state.sector_summary_ready_event.set()                                     │
│    ※ 매수 후보 평가(evaluate_buy_candidates)는 본 경로에서 호출되지 않음 —        │
│      recompute_sector_summary_now는 순수 계산+알림만 담당 (P24 단순성).            │
│      매수 후보 평가는 실시간 틱 경로의 _flush_sector_recompute_impl에서만.        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                                                        │
                                                                        ▼ (실시간 틱 경로)
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [H] 실시간 틱 → Compute Engine (pipeline_compute._compute_loop_impl:275-318)   │
│  입력: tick_queue (broker connector → set_queue_callback)                         │
│  컨슘: asyncio.wait_for(tick_queue.get(), timeout=0.5)                            │
│  병행: _drain_control_queue (control_queue non-blocking 드레인)                   │
│                                                                                  │
│  배치 처리: _process_tick_batch → _coalesce_batch (01 코얼레싱)                   │
│  분배: _process_tick_data → _dispatch_real_item                                  │
│   - 01 체결 → _handle_real_01_tick                                               │
│     side effect:                                                                  │
│     - broadcast_queue.put(real-data) — 화면 전송                                  │
│     - _apply_01_radar_and_receive_rate — 레이더 행 갱신                            │
│       + request_sector_recompute(nk_px) — dirty 마킹                              │
│       + _received_codes_krx/nxt.add(nk_px) — 수신 세트 추가                       │
│       + _receive_rate_dirty=True + _receive_rate_event.set()                      │
│     - _apply_01_price_to_positions — 보유종목 현재가 반영                          │
│       (test: dry_run.update_price / real: apply_last_price_to_positions_inplace)  │
│     - _check_01_auto_sell — 매도 조건 체크 (auto_sell_effective 시)               │
│       → state.auto_trade.check_sell_conditions()                                  │
│   - 00 주문체결 → engine_ws_dispatch._handle_real_00                              │
│   - 04/80 잔고 → engine_ws_dispatch._handle_real_balance                          │
│   - 0D 호가 → _handle_real_0d_tick → notify_orderbook_update (ws_manager 직접)    │
│   - 0J 업종지수 → _handle_real_0j_tick → notify_index_data                        │
│   - PGM 프로그램 → _handle_real_pgm_tick → notify_program_update (ws_manager 직접)│
│                                                                                  │
│  배치 후: _refresh_account_snapshot_meta + _broadcast_account (보유종목 가격 갱신 시)│
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [I] 업종 재계산 루프 (pipeline_compute._sector_recompute_loop_impl:678-694)     │
│  Phase 1: _phase1_wait_threshold (수신율 임계값 대기, 이벤트 기반 P11)             │
│    - _receive_rate_event.wait() + 200ms 디바운스                                  │
│    - _calculate_receive_rate() + _evaluate_threshold()                            │
│    - 통과 시 mark_sector_threshold_passed() + request_sector_recompute(None)      │
│    - WS: _send_receive_rate() (수신율 전송, 미통과 시)                             │
│                                                                                  │
│  Phase 2: _phase2_batch_recompute_loop (0.2초 배치 증분 재계산)                    │
│    - _receive_rate_dirty 시 _calculate_receive_rate + _send_receive_rate          │
│    - notify_desktop_sector_score(force=False) — delta 전송                         │
│    - has_dirty_sectors() 시 _flush_sector_recompute_impl()                         │
│      → engine_sector_confirm._flush_sector_recompute_impl:66-198                  │
│        - dirty 종목 → dirty 업종 추출 → compute_sector_scores (증분)               │
│        - calculate_bonus_scores (3단계 누적 가산점)                                 │
│        - build_buy_targets_from_settings                                           │
│        - state.sector_summary_cache 참조 교체 (R5.6)                               │
│        - notify_desktop_sector_scores() + notify_buy_targets_update()              │
│        - are_buy_targets_changed 시 sync_dynamic_subscriptions (DYNAMIC_REG/UNREG) │
│        - evaluate_buy_candidates() (매수 후보 평가, _cash_insufficient 게이트)     │
│        - state.sector_summary_ready_event.set()                                    │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [J] 매수 후보 실행 (buy_order_executor.evaluate_buy_candidates:67-234)          │
│  게이트 체인 (순서):                                                              │
│   1. state.running / state.auto_trade / sector_summary_cache 존재                 │
│   2. auto_buy_effective(시간 범위 + auto_buy_on + 마스터 스위치)                   │
│   3. max_stock_cnt / max_stock_cnt_on (최대 보유수)                                │
│   4. buy_amt / buy_amt_on (종목당 한도)                                            │
│   5. max_daily_total_buy_amt / max_daily_total_buy_on (일일 한도)                 │
│   6. get_risk_manager().get_withdrawable_deposit() > 0 (주문가능 금액)            │
│   7. check_order_interval(buy) (건별 간격 게이트)                                  │
│   8. _refresh_buyable_prices (guard_pass + 시간대 + 재매수 + 가격/잔액)            │
│   9. _current_snapshot == _last_global_snapshot (조건 변화 없으면 스킵, P11)       │
│                                                                                  │
│  매수 후보 순회:                                                                  │
│   - state.auto_trade.execute_buy() 단일 경로 호출 (P15)                            │
│   - 1건 매수 성공 시 break + invalidate_buy_snapshot + mark_order_executed("buy") │
│   - BUY_REJECT_QTY_ZERO: 잔액 0이면 break, 단가 초과면 continue                    │
│   - BUY_GLOBAL_REJECT_REASONS: break                                               │
│   - 종목별 차단: continue                                                          │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [K] 화면 전송 (pipeline_gateway._broadcast_loop:66-83)                           │
│  컨슘: broadcast_queue.get() (블로킹)                                              │
│  분배: _process_broadcast → _send_to_websocket                                    │
│   - ws_manager.broadcast(event_type, data) — 활성 WS 클라이언트 전원 전송          │
│                                                                                  │
│  우회 경로 (broadcast_queue 미경유, P23 일관성 — 주석 명시):                       │
│   - 0D 호가: notify_orderbook_update → ws_manager.broadcast 직접                   │
│   - PGM 프로그램: notify_program_update → ws_manager.broadcast 직접                │
│   - 0J 업종지수: notify_index_data → ws_manager.broadcast 직접                     │
│   - market-phase/order-time-blocked: _broadcast 헬퍼 → ws_manager.broadcast        │
│   - confirmed-progress: broadcast_queue.put (스레드풀 안전 call_soon_threadsafe)   │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [L] 알림 워커 (notification_worker.NotificationWorker)                           │
│  싱글톤 큐: asyncio.Queue(maxsize=100)                                            │
│  컨슘: _consume_loop — _handle(msg) 라우팅                                         │
│   - "telegram" → telegram.send_msg_async                                          │
│  자동 시작: enqueue 시 미시작이면 start()                                          │
│  graceful shutdown: 큐 잔량 처리 후 종료 (10초 타임아웃)                            │
│                                                                                  │
│  ※ 본 조사 범위에서 notification_worker로 직접 enqueue하는 호출부는               │
│    scheduler/pipeline/compute/candidate 경로에서 발견되지 않음 —                    │
│    telegram 전송은 주로 trading.py 체결 이벤트에서 enqueue (C-04 범위).             │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 별도 호출 그래프 (자정·자동매매 전환)

```
자정 (_on_midnight:1398-1433)
  - state.last_reset_date 갱신
  - krx_remove_done / confirmed_done / last_confirmed_download_date 리셋 (P22)
  - 연도 변경 시 다음 연도 거래일 캐시 생성 (refresh_trading_days_for_year)
  - _apply_auto_toggle_on_startup(settings) — 거래일 자동 ON/OFF
  - schedule_auto_trade_timers(settings) — 당일 매수/매도 타이머 재예약
  - schedule_midnight_timer() — 다음 자정 예약

자동매매 전환 (_on_auto_trade_transition:1327-1341)
  - refresh_engine_integrated_system_settings_cache(use_root=True) — 설정 캐시 갱신
  - notify_desktop_header_refresh() + notify_desktop_settings_toggled()
```

---

## 4. 단계별 소유 캐시·DB 저장·WS 진행률·주문 후보 side effect 매트릭스

### 4.1 소유 캐시 (engine_state.state)

| 상태 필드 | 소유자 (단일 writer) | 갱신 시점 | 비고 |
|----------|---------------------|----------|------|
| `market_phase` | `_apply_market_phase` (scheduler:758-759) | 페이즈 전환 시 | JIF/시간 기반 양쪽 공통 경로 (P10 SSOT) |
| `confirmed_done` | `_fire_unified_confirmed_fetch` (scheduler:646) / `_do_unified_confirmed_fetch` (scheduler:657,660) / `_on_ws_subscribe_end` (907) / `_on_midnight` (1406) / `retry_pipeline_catchup_after_bootstrap` (727) | 확정 조회 트리거/완료/리셋 | 다중 writer이나 전부 scheduler 내부 (P10 단일 모듈) |
| `krmx_remove_done` | `_on_krx_closing_auction_start` (623,627,632) / `_on_midnight` (1405) | 15:20 구독 해지 / 자정 리셋 | scheduler 내부 |
| `last_realtime_reset_date` | `_mark_realtime_reset_done` (engine_initial_data, 단일 경로) | 07:58 실시간 필드 리셋 | P10 SSOT (세션 11) |
| `last_ws_subscribe_start_date` | `_on_ws_subscribe_start` (876) / `_init_ws_subscribe_state` (1220) | 07:59 / 재기동 시 | 멱등성 가드 (P22) |
| `last_krx_pre_subscribe_date` | `_on_krx_pre_subscribe` (589) | 08:59 | 멱등성 가드 |
| `last_confirmed_download_date` | `_on_confirmed_download` (937) / `_on_midnight` (1407) | timetable.confirmed_download / 자정 | P22 멱등성 |
| `last_reset_date` | `_on_midnight` (1404) / `start_daily_time_scheduler` (1478) | 자정 / 기동 | |
| `confirmed_refresh_running_confirmed` | `_run_confirmed_pipeline` (1013,1085) / `_reset_confirmed_refresh_running` (987) | 파이프라인 시작/종료 | 중복 실행 방지 (P10 SSOT — 그룹 F) |
| `confirmed_refresh_running_5d` | `fetch_5d_data_only` (1199,1420) | 수동 5거래일 다운로드 | |
| `latest_filter_summary_meta` | `_set_latest_filter_summary_meta` (990-996) | 파이프라인 4단계 / 기동 시 DB 로드 | P10 SSOT (세션 11) |
| `master_stocks_cache` | 다중 writer (파이프라인 4/5단계, compute 01 틱, sync_dynamic_subscriptions) | 확정 데이터 / 실시간 틱 | C-01 매트릭스 참조 |
| `sector_summary_cache` | `recompute_sector_summary_now` / `_flush_sector_recompute_impl` / `_full_recompute` / `_on_realtime_fields_reset` (None 리셋) | 업종 재계산 / 07:58 리셋 | C-01 매트릭스 — 단일화 1순위 후보 |
| `integrated_system_settings_cache["sector_stock_layout"]` | `_update_layout_cache` (1161) / `_run_confirmed_pipeline` (1019, [] 리셋) / `run_engine_loop` (149, [] 리셋) | 파이프라인 4단계 / 기동 | P10 SSOT (설정 키) |
| `auto_trade_timer_handles` | `schedule_auto_trade_timers` (1352-1354,1388) | 기동 / 자정 / 설정 변경 | |
| `midnight_timer_handle` | `schedule_midnight_timer` (1438-1451) | 기동 / 자정 | |
| `timetable_timer_handle` | `_schedule_next_timetable_event` (1065-1102) | 매 이벤트 완료 시 | 단일 타이머 (P14) |
| `broker_tokens` | `_get_all_tokens_async` (engine_loop:102-108) / `_run_confirmed_pipeline` (1036,1082) / `fetch_5d_data_only` (1211,1422) | 기동 / 파이프라인 임시 토큰 | 파이프라인은 finally에서 pop |

### 4.2 DB 저장 (aiosqlite execute/executemany)

| 위치 | 테이블 | 작업 | 트랜잭션 | 비고 |
|------|--------|------|---------|------|
| `execute_unified_rolling_and_save:310` | stock_5d_bars | DELETE (dt > qry_dt) | get_db_lock | 미확정 당일 행 제거 (P22) |
| `execute_unified_rolling_and_save:313` | stock_5d_bars | INSERT OR REPLACE (당일 세로 행) | get_db_lock | bars_bulk_params |
| `execute_unified_rolling_and_save:323` | stock_5d_bars | SELECT (code, trade_amount, high_price) | get_db_lock | avg_5d/high_5d 재계산용 |
| `execute_unified_rolling_and_save:350` | master_stocks_table | SELECT (code, market) | get_db_lock | market 보존 |
| `execute_unified_rolling_and_save:368` | master_stocks_table | INSERT OR REPLACE (UPSERT) | get_db_lock | master_bulk_params |
| `_save_confirmed_cache:585` | master_stocks_table | SELECT (code, market) | — | mkt_map |
| `_save_confirmed_cache:613` | master_stocks_table | INSERT INTO ... ON CONFLICT UPDATE | commit | eligible_codes만 (P10 SSOT) |
| `_step4_save_to_db_and_cache:789-813` | master_stocks_table, stock_5d_bars, system_state_cache | DELETE + CREATE TABLE + INSERT OR REPLACE | commit | filter_summary_meta 저장 |
| `fetch_5d_data_only:1337-1365` | stock_5d_bars, master_stocks_table | INSERT OR REPLACE + UPDATE + DELETE | get_db_lock + commit | 5거래일 일봉 수동 다운로드 |

**P22 데이터 정합성 준수**: 모든 DB 쓰기는 `qry_dt`(직전 거래일) 기준, 미확정 당일 행 삭제 가드, INSERT OR REPLACE로 같은 날 재실행 시 자동 덮어쓰기.
**P12 DB 연결 준수**: `get_db_connection()` 싱글톤, 매 요청 connect() 호출 없음.

### 4.3 WS 진행률 브로드캐스트 (confirmed-progress)

| 위치 | step | 시점 | 비고 |
|------|------|------|------|
| `_step1_fetch_all_stocks:666` | 1 | 전종목 리스트 다운로드 시작 | |
| `_step2_filter_eligible:687,736` | 2 | 필터링 시작/완료 | |
| `_step3_parse_confirmed:761` | 3 | 해석 시작 | |
| `_step4_save_to_db_and_cache:782` | 4 | 캐시 저장 시작 | |
| `_step5_download_daily_confirmed:880,889,942,946` | 5 | 일봉 다운로드 진행률/ETA/완료 | on_progress 콜백 (스레드풀 안전 call_soon_threadsafe) |
| `fetch_5d_data_only:1235,1283,1390,1392` | 5 | 5거래일 일봉 진행률 | 수동 다운로드 |

**전송 경로**: `_broadcast_confirmed_progress` → `get_broadcast_queue().put_nowait({"type":"confirmed-progress",...})` → pipeline_gateway 컨슘 → ws_manager.broadcast.
**스레드풀 안전**: `_loop` 전달 시 `call_soon_threadsafe`로 메인 루프에 큐 적재 (ka10081 다운로드가 스레드풀에서 진행률 콜백 호출 시).

### 4.4 주문 후보 side effect (evaluate_buy_candidates)

| 항목 | 내용 |
|------|------|
| 호출부 | `engine_sector_confirm._flush_sector_recompute_impl:193` (증분) / `_full_recompute:256` (콜드 스타트) |
| 게이트 | auto_buy_effective / max_stock_cnt / buy_amt / max_daily_total_buy_amt / withdrawable_deposit / check_order_interval / snapshot 비교 |
| 단일 경로 | `state.auto_trade.execute_buy()` (P15, C-04 검증 완료) |
| side effect | 주문 전송 → 체결 이벤트 → on_fill_update → 계좌 갱신 → WS broadcast (C-04 범위) |
| 상태 갱신 | `_cash_insufficient` / `_last_global_snapshot` / `mark_order_executed("buy")` / `invalidate_buy_snapshot()` |
| **파이프라인 경로에서 호출 여부** | **없음** — `_step7_recompute_and_broadcast`는 `recompute_sector_summary_now`만 호출, 매수 후보 평가는 실시간 틱 경로의 `_flush_sector_recompute_impl`에서만. 장마감 후 확정 데이터 기반 매수는 Phase 2 루프가 dirty 마킹 후 다음 0.2초 배치에서 수행. |

---

## 5. 큐 인터페이스 (core_queue.py)

### 5.1 큐 정의

| 큐 | 타입 | maxsize | producer | consumer |
|----|------|---------|----------|----------|
| `_tick_queue` | asyncio.Queue | 20000 | broker connector (`set_queue_callback`) | `_compute_loop_impl` (pipeline_compute) |
| `_broadcast_queue` | asyncio.Queue | 2000 | compute 01 틱 / confirmed-progress / receive-rate / sector-scores / buy-targets / engine_account_notify | `_broadcast_loop` (pipeline_gateway) |
| `_control_queue` | asyncio.PriorityQueue | 500 | sync_dynamic_subscriptions (DYNAMIC_REG/UNREG) / 설정 변경 / sector_recompute | `_drain_control_queue` (pipeline_compute) |

### 5.2 제어 신호 타입

| 신호 타입 | producer | 처리부 | 비고 |
|----------|----------|--------|------|
| `UPDATE_CONFIG` | 설정 변경 경로 | `_handle_config_update` | notify_desktop_header_refresh만 (캐시 갱신은 settings.py 경로) |
| `RECOMPUTE_SECTOR` | (예비) | `_handle_sector_recompute` | recompute_sector_summary_now |
| `sector_recompute` | (개별 종목) | `request_sector_recompute` | dirty 마킹 |
| `DYNAMIC_REG` | `sync_dynamic_subscriptions:299` | `_handle_dynamic_reg` | 0D/PGM 구독 신규 등록 |
| `DYNAMIC_UNREG` | `_flush_unreg_batch:375` | `_handle_dynamic_unreg` | 0D/PGM 구독 해지 (30초 지연) |

### 5.3 P11 이벤트 기반 준수

- `_schedule_next_timetable_event`: `while + sleep` 폴링 대신 `call_later` 단일 타이머 (스케줄러)
- `_phase1_wait_threshold`: `_receive_rate_event.wait()` 이벤트 대기 + 200ms 디바운스
- `engine_loop` WS 구간 감지 루프: `asyncio.wait([stop_wait, change_wait], FIRST_COMPLETED)` — `ws_window_changed_event` 기반
- `_compute_loop_impl`: `asyncio.wait_for(tick_queue.get(), timeout=0.5)` — 틱 없는 시간에도 control_queue 드레인
- **폴링(`while + sleep`) 0건 확인** — P11 준수.

---

## 6. 원칙 부합 점검

### 6.1 P8/P9 경계 보존

- **스케줄러 → 파이프라인**: `schedule_engine_task(_do_unified_confirmed_fetch())`로 태스크 격리, 직접 동기 호출 아님. 파이프라인 실패 시 스케줄러 타이머는 계속 동작 (P25).
- **파이프라인 → compute**: `_step7_recompute_and_broadcast`가 `pipeline_compute._calculate_receive_rate/_send_receive_rate` 직접 호출 — 모듈 경계는 허용 범위(동일 프로세스, P5 직접 호출 체인).
- **compute → 매수 후보**: `_flush_sector_recompute_impl`이 `buy_order_executor.evaluate_buy_candidates` 직접 호출 — P15 단일 주문 경로 유지.
- **매수 후보 → 주문**: `state.auto_trade.execute_buy()` 단일 경로 (C-04 검증 완료).
- **관찰**: 경계는 함수 호출 체인으로 직결되어 있으나, 큐 기반 분리는 tick/broadcast/control 3개만 유지. 새 EventBus/콜백 리스트 도입 없음 (P5 준수).

### 6.2 P10 SSOT

- ✅ `_apply_market_phase` 단일 적용 경로 (JIF/시간 기반 공통)
- ✅ `confirmed_refresh_running_confirmed` 단일 소유자 그룹 (파이프라인 내부 + 외부 리셋 헬퍼)
- ✅ `latest_filter_summary_meta` / `last_realtime_reset_date` 단일 쓰기 경로 (세션 11)
- ✅ `sector_stock_layout` 원본 SSOT (파이프라인 4단계에서 갱신, 설정 PATCH에서는 읽기 전용)
- ✅ `qry_dt`(직전 거래일) 기준 — execute_unified_rolling_and_save / fetch_5d_data_only / retry_pipeline_catchup_after_bootstrap 동일 기준
- ⚠️ `confirmed_done` 플래그 다중 writer (전부 scheduler 내부이나 5곳) — 기능적 단일 모듈이므로 P10 위반 아님, 다만 `_fire_unified_confirmed_fetch` 진입점 통합 여부 검토 가치.

### 6.3 P11 이벤트 기반 처리

- ✅ `call_later` 단일 타이머 (스케줄러) — 폴링 금지 준수
- ✅ `_receive_rate_event.wait()` (Phase 1) — 이벤트 기반
- ✅ `ws_window_changed_event.wait()` (engine_loop WS 감지) — 이벤트 기반
- ✅ `asyncio.wait_for(tick_queue.get(), timeout=0.5)` — 큐 기반
- ✅ `broadcast_queue.get()` (gateway) — 큐 기반
- ⚠️ `_phase2_batch_recompute_loop:647` `await asyncio.sleep(0.2)` — 0.2초 배치 루프. 엄밀히는 폴링이나, dirty 플래그 기반 증분 처리이므로 P11 위반 아님 (이벤트 대기 + 타임윈도우 배치의 하이브리드, P24 단순성).

### 6.4 P16 살아있는 경로

- ✅ `_TIMETABLE` 기동 시 `build_timetable_from_cache`로 빌드 — 빈 리스트 상태로 스케줄러 동작 금지 (주석 명시)
- ✅ `scheduler_market_close_on` OFF 시 마지막 타임테이블 항목 스킵 — dead path 제거
- ✅ `_on_krx_pre_subscribe` 0건 구독 시 가드 미설정 + 경고 로그 — 가짜 성공 방지 (P20/P22)
- ✅ `_check_jif_health` — JIF 미수신 시 시간표가 보완 경로 유지
- ✅ `_apply_market_phase` 페이즈 변경 감지 시에만 부작용 트리거 — 멱등성 보장
- ✅ `retry_pipeline_catchup_after_bootstrap` — 부트스트랩 완료 후 미실행 파이프라인 catch-up

### 6.5 P20 폴백 금지

- ✅ `build_timetable_from_cache` 캐시 키 누락 시 `ValueError` (빈 문자열/None 폴백 금지)
- ✅ `_step5_download_daily_confirmed` 전종목 조회 실패 시 빈 폴백 금지 — 파이프라인 중단 + 화면 알림 (P21)
- ✅ `execute_unified_rolling_and_save` date_str 누락 시 `return False` (폴백 저장 금지)
- ✅ `_handle_real_pgm_tick` tval 누락/오류 시 스킵 + 경고 (화면에 0 잘못 표시 방지)
- ✅ `_handle_nws_news` code 빈 뉴스 스킵 + debug 로깅 (폴백 없음)
- ✅ silent `except: pass` 0건 — 전부 `logger.warning/error(..., exc_info=True)`

### 6.6 P24 단순성

- ✅ `_apply_market_phase` 부작용 트리거 단일 집중 (타이머 3개 통합, 주석 명시)
- ✅ `build_timetable_from_cache` 50줄 이하, 복잡도 O(n) n=12
- ✅ `_schedule_next_timetable_event` 단일 타이머 (P14 멀티스레드 금지 연계)
- ✅ `pipeline_compute_tick_handlers` 분리 (P24 단순성 — 틱 핸들러·코얼레싱 분리)
- ✅ `_run_confirmed_pipeline` 7단계 순차 구조 (각 단계별 함수 분리)
- ⚠️ `market_close_pipeline.py` 1425줄 — 500줄 초과. 단계별 함수 분리는 되어있으나 파일 길이 주의. `_run_confirmed_pipeline` 본체 86줄, 각 step 함수 분리되어 있어 순환 복잡도는 낮으나 파일 분할 검토 가치 (C-09 범위와 중복).
- ⚠️ `daily_time_scheduler.py` 1510줄 — 500줄 초과. 시간 상수 50줄 + 타임테이블 빌드 + 콜백 8개 + 큐 헬퍼 + 자정/자동매매 타이머 통합. 기능 응집도 높으나 파일 분할 검토 가치.
- ⚠️ `_step7_recompute_and_broadcast`와 `fetch_5d_data_only` 후처리(1411-1417)가 동일 패턴 반복 (수신율 계산 + sector_stocks_refresh + recompute_sector_summary_now) — 헬퍼 추출 후보 (P24 중복 제거).

### 6.7 P25 격리된 실패

- ✅ `schedule_engine_task`로 모든 콜백 태스크 격리 — 콜백 실패 시 스케줄러 타이머는 계속
- ✅ `_timetable_event_fired` finally에서 `_schedule_next_timetable_event` 예약 — 오류 발생 여부 무관 스케줄러 지속
- ✅ `_process_tick_batch` 아이템별 try/except — 계속 처리
- ✅ `_handle_real_tick` 아이템별 try/except — 계속 처리
- ✅ `_compute_loop_impl` / `_phase2_batch_recompute_loop` 오류 시 계속
- ✅ `_sector_recompute_loop_impl` 치명 오류 시 `_compute_running=False`로 정리 (의미 없는 cancel 대기 방지)
- ✅ `engine_loop` WS 구간 감지 루프 오류 시 `await asyncio.sleep(1)` hot-spin 방지 후 계속
- ✅ `_run_confirmed_pipeline` finally에서 `confirmed_refresh_running_confirmed=False` + 임시 토큰 pop — 예외 경로 정리
- ✅ `NotificationWorker._consume_loop` 메시지별 try/except — 계속 처리
- ✅ `engine_lifecycle.stop_engine` 백그라운드 태스크 일괄 취소 + `clear_all_queues`

---

## 7. 결합도 관찰 및 개선 후보

### 7.1 결합도 관찰 (변경 금지 후보)

| 항목 | 내용 | 비고 |
|------|------|------|
| 스케줄러 직접 호출 다운스트림 | WS 구독/해지, 파이프라인, 설정 캐시, 업종 재계산, 주문 후보 평가(간접) | C-05 계획서 관찰 항목. 현재는 단일 프로세스 직접 호출이 적합 (P5), 큐/EventBus 도입 금지 |
| `_apply_market_phase` 부작용 집중 | 5개 페이즈 전환 콜백이 한 함수에 집중 | P10 SSOT (단일 적용 경로) + P24 단순성 (타이머 3개 통합) 준수. 분리 시 중복 발생 |
| `recompute_sector_summary_now` 다중 호출부 | scheduler 4곳 + compute 2곳 + sector_confirm 2곳 | 전체 재계산 진입점 단일화 (P10). 매수 후보 평가는 본 함수에서 호출하지 않아 순수 계산+알림 분리 |
| `_step7_recompute_and_broadcast` ↔ `fetch_5d_data_only` 후처리 중복 | 수신율 계산 + sector_stocks_refresh + recompute_sector_summary_now 동일 패턴 | P24 중복 제거 후보 (헬퍼 추출) |
| `engine_loop` WS 구간 감지 루프 | `is_ws_subscribe_window` + `connector_manager` 생성/해제 | 스케줄러가 WS 구독 시작/종료 이벤트만 담당, 실제 연결은 engine_loop가 담당 — 관심사 분리 유지 |
| 파이프라인 임시 토큰 | `_run_confirmed_pipeline` / `fetch_5d_data_only`가 `broker_tokens`에 임시 토큰 등록/해제 | finally에서 pop 보장. 파이프라인 독립성 위해 별도 토큰 발급 필요 |

### 7.2 개선 후보 (우선순위 낮음~중간, 별도 승인 필요)

| 후보 | 원칙 | 위험 | 내용 |
|------|------|------|------|
| 1. `_step7_recompute_and_broadcast` ↔ `fetch_5d_data_only` 후처리 헬퍼 추출 | P24 | 낮음 | 수신율 계산 + sector_stocks_refresh + recompute_sector_summary_now 3줄 패턴 중복. `_post_recompute_notify()` 헬퍼 추출. 단, `_step7`는 tag 파라미터 사용하므로 시그니처 설계 필요. |
| 2. `confirmed_done` 플래그 쓰기 경로 정리 | P10 | 낮음 | 5곳 writer가 전부 scheduler 내부이므로 P10 위반 아님. 다만 `_fire_unified_confirmed_fetch` 진입점 통합 여부 검토. 현행 유지 적합 (기능적 단일 모듈). |
| 3. `market_close_pipeline.py` 파일 분할 검토 | P24 | 중간 | 1425줄. `_run_confirmed_pipeline` 본체 + 7개 step 함수 + KRX REMOVE + 5거래일 수동 다운로드. step 함수들을 별도 모듈로 분할 가능. 단, C-09 대형 파일 범위와 중복. |
| 4. `daily_time_scheduler.py` 파일 분할 검토 | P24 | 중간 | 1510줄. 시간 상수 + 타임테이블 + 콜백 8개 + 자정/자동매매 타이머. 콜백 그룹별 분할 가능. 단, C-09 범위와 중복. |

### 7.3 변경 금지 항목 (현행 유지)

| 항목 | 사유 |
|------|------|
| `_apply_market_phase` 단일 적용 경로 | P10 SSOT — JIF/시간 기반 공통 경로, 분리 시 중복 |
| `call_later` 단일 타이머 (스케줄러) | P11 폴링 금지 + P14 멀티스레드 금지 |
| `asyncio.Queue` 3종 (tick/broadcast/control) | P5 직접 호출 체인, 새 EventBus/Redis 도입 금지 |
| `recompute_sector_summary_now` 매수 후보 평가 미호출 | P24 단순성 — 순수 계산+알림 분리. 매수는 실시간 틱 경로에서만 |
| 파이프라인 `qry_dt`(직전 거래일) 기준 | P10 SSOT + P22 정합성 — 장 전/중 실행 시 미확정 데이터 저장 차단 |
| `confirmed_refresh_running_confirmed` 중복 실행 가드 | P10 SSOT — 파이프라인 동시 실행 차단 |
| `_TIMETABLE` 기동 시 빌드 + 빈 리스트 동작 금지 | P16 살아있는 경로 |
| `schedule_engine_task` 태스크 격리 | P25 격리된 실패 — 콜백 실패 시 스케줄러 지속 |
| `_broadcast_confirmed_progress` 스레드풀 안전 (call_soon_threadsafe) | ka10081 다운로드 스레드풀 진행률 콜백 안전 |
| WS 구독 시작/종료는 스케줄러, 연결/해제는 engine_loop | 관심사 분리 — 스케줄러는 시간 이벤트, engine_loop는 연결 수명 |

---

## 8. 종료 시 큐 잔량 처리 순서 (P21/P22)

```
1. ws_manager.close_all() — WS 클라이언트 정상 종료 (EPIPE 방지)
2. stop_engine()
   - engine_task.cancel() — compute_loop 종료 → tick_queue 컨슘 중단
   - 백그라운드 태스크 일괄 취소 (scheduler 포함)
   - clear_all_queues() — tick/broadcast/control 잔류 데이터 제거
3. NotificationWorker.shutdown() — 큐 잔량 알림 처리 (10초 타임아웃)
4. stop_gateway_loop() — broadcast_queue 컨슘 중단
5. stop_daily_time_scheduler() — 타이머 취소
```

**순서 의미**: 엔진 루프 종료 → 큐 클리어 → 알림 워커가 엔진 잔량 알림 처리 → 게이트웨이 종료. clear_all_queues가 엔진 종료 직후 실행되므로 알림 워커는 자체 큐만 처리 (broadcast_queue 잔량은 손실 가능, 단 종료 시점이므로 P21 위반 아님).

---

## 9. 조사 결론

### 9.1 P8/P9 경계 보존 준수

스케줄러·파이프라인·실시간 엔진은 함수 호출 체인으로 직결되어 있으나, 큐 기반 분리(tick/broadcast/control)와 `schedule_engine_task` 태스크 격리로 실패 전파가 차단됨. 새 EventBus/콜백 리스트/Redis 도입 없음 (P5 준수). 경계 보존 현행 유지 적합.

### 9.2 P10/P11/P16/P20/P24/P25 준수

- P10 SSOT: 단일 적용 경로(`_apply_market_phase`), 단일 쓰기 경로(`latest_filter_summary_meta` 등), `qry_dt` 기준 통일.
- P11 이벤트 기반: `call_later` 단일 타이머, `_receive_rate_event.wait()`, `ws_window_changed_event.wait()`. 폴링 0건.
- P16 살아있는 경로: `_TIMETABLE` 빌드 보장, 토글 OFF 시 dead path 제거, JIF 미수신 시 시간표 보완.
- P20 폴백 금지: 캐시 키 누락 시 ValueError, 조회 실패 시 파이프라인 중단, silent except 0건.
- P24 단순성: 부작용 단일 집중, tick_handlers 분리. 파일 길이 2건 초과 (C-09 범위).
- P25 격리된 실패: schedule_engine_task 격리, 아이템별 try/except, finally 정리.

### 9.3 개선 후보 4건 (우선순위 낮음~중간)

1. `_step7` ↔ `fetch_5d_data_only` 후처리 헬퍼 추출 (P24, 낮음)
2. `confirmed_done` 쓰기 경로 정리 (P10, 낮음, 현행 유지 적합)
3. `market_close_pipeline.py` 분할 (P24, 중간, C-09 중복)
4. `daily_time_scheduler.py` 분할 (P24, 중간, C-09 중복)

**후속 세션에서는 1개만 별도 승인 후 진행 권장 — 1순위: 후처리 헬퍼 추출 (P24, 낮은 위험).**

### 9.4 코드 수정 없음 (조사·문서만 작성)

본 세션은 조사·호출 그래프 문서만 작성. 백엔드·거래 실행 경로·DB·테스트 영향 없음. 검증은 정적 대조 기반 (코드 미수정이므로 런타임 검증 생략).
