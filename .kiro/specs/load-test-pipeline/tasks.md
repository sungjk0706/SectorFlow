# Implementation Plan: Load Test Pipeline

## Overview

SectorFlow 실시간 파이프라인 부하 테스트 도구 구현. 합성 틱을 기존 처리 경로에 주입하여 단계별 성능 한계를 측정하고, 테스트 완료 후 자기 삭제하는 임시 모듈 세트를 구현한다. 백엔드는 Python(FastAPI + asyncio), 프론트엔드는 TypeScript로 작성한다.

## Tasks

- [x] 1. Implement MockTickGenerator
  - [x] 1.1 Create `backend/app/services/mock_tick_generator.py` with MockTickGenerator class
    - Per-stock state management (last price, cumulative trade amount)
    - `generate_tick()` → (item, vals, stock_code) tuple in Kiwoom REAL 0B format
    - Bounded random walk price simulation with configurable `volatility_pct`
    - Round-robin distribution across stock codes (T000001~T000050)
    - `_lt_ts` nanosecond timestamp injection via `time.perf_counter_ns()`
    - `reset()` method to clear all per-stock state
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 8.5_

  - [ ]* 1.2 Write property tests for MockTickGenerator
    - **Property 1: Tick Format Validity** — random stock codes/price ranges, validate schema
    - **Property 2: Sequential Tick Coherence** — random sequence lengths, verify bounded volatility and monotonic trade amount
    - **Property 3: Tick Distribution Coverage** — random stock count (20~100), verify all codes appear in N×10 ticks
    - **Property 11: Test Stock Code Distinguishability** — verify T-prefix + 6 digits never matches real code format
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 8.5**

- [x] 2. Implement MetricsCollector
  - [x] 2.1 Create `backend/app/services/load_test_metrics.py` with MetricsCollector class
    - `__init__` accepting baseline_cpu and baseline_rss
    - `record_tick_injected()` — increment injected count
    - `record_frontend_report(fps, rendered_count, avg_delay_ms)` — store frontend metrics
    - `evaluate_stop_conditions()` → (bool, str) with 1-second `call_later` scheduling
    - Stop conditions: CPU > 90%, FPS < 30, WS disconnect, memory > 500MB/60s, delay > 100ms/5s
    - `finalize_step(step_tps)` → StepResult dict with aggregated metrics
    - Sliding window implementations (60s for memory, 5s for delay)
    - Status classification logic (ok/warning/stopped)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.4, 4.5, 4.6, 6.3, 6.4, 6.5_

  - [ ]* 2.2 Write property tests for MetricsCollector
    - **Property 5: Sliding Window Stop Condition Detection** — random metric sequences, verify detection accuracy
    - **Property 6: Tick Loss Rate Calculation** — random (injected, rendered) pairs, verify formula
    - **Property 7: Step Metrics Aggregation** — random metric collections, verify mean/max computations
    - **Property 8: Status Classification** — random metric combinations, verify ok/warning/stopped assignment
    - **Validates: Requirements 3.5, 3.6, 4.5, 4.6, 6.3, 6.4, 6.5**

- [ ] 3. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement LoadTestRunner
  - [x] 4.1 Create `backend/app/services/load_test_runner.py` with LoadTestRunner class
    - STEPS list: [100, 200, 500, 1000, 2000, 5000, 10000]
    - STEP_DURATION_SEC = 30, STEP_PAUSE_SEC = 5
    - `start()` — isolation setup → baseline measurement (psutil) → step execution loop
    - `stop()` — immediate halt → result generation → cleanup trigger
    - `get_status()` — current step, elapsed time, latest metrics snapshot
    - Uniform tick injection via `asyncio.get_running_loop().call_later()` chain
    - Direct synchronous call to `engine_ws_dispatch._handle_real_01(item, vals, "0B", True, es_module)`
    - Isolation: disable auto-trading, verify no real broker WS active
    - SIGINT handler for graceful shutdown with partial result generation
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 7.1, 7.2, 7.5, 8.1, 8.2, 8.3, 8.4_

  - [ ]* 4.2 Write property test for uniform injection timing
    - **Property 4: Uniform Injection Timing** — random tick rates (100~10000), verify coefficient of variation < 0.1
    - **Validates: Requirements 2.4**

  - [ ]* 4.3 Write property test for concurrent start rejection
    - **Property 10: Concurrent Start Rejection** — verify multiple start requests while running all get 409
    - **Validates: Requirements 7.3**

- [x] 5. Implement Result Report generation
  - [x] 5.1 Add result report logic to LoadTestRunner
    - `ResultReport` dataclass: timestamp, steps, comfortable_throughput, limit_throughput, first_bottleneck, recommended_safe_limit, stop_reason, total_duration_sec
    - Conclusions derivation: comfortable = last "ok" step_tps, limit = last step before "stopped", recommended = floor(comfortable × 0.7)
    - JSON file output to `backend/data/load_test_result_{timestamp}.json`
    - Console table output (human-readable)
    - _Requirements: 6.1, 6.2, 6.6, 6.7_

  - [ ]* 5.2 Write property test for conclusions derivation
    - **Property 9: Conclusions Derivation** — random StepResult sequences, verify comfortable/limit/recommended calculations
    - **Validates: Requirements 6.6**

- [x] 6. Implement Load Test API routes
  - [x] 6.1 Create `backend/app/web/routes/load_test.py` with FastAPI router
    - `POST /api/load-test/start` — begin test, 409 if already running
    - `POST /api/load-test/stop` — immediate stop + result generation
    - `GET /api/load-test/status` — current step, elapsed time, latest metrics
    - Register router in `backend/app/web/app.py`
    - WS message handler for `load-test-metrics` type from frontend
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 7. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement Frontend MetricsReporter
  - [x] 8.1 Create `frontend/src/utils/loadTestReporter.ts` with LoadTestMetricsReporter class
    - `start()` — begin rAF loop, register WS listener for ticks with `_lt_ts`
    - `stop()` — halt rAF loop, unregister listeners
    - FPS measurement via `requestAnimationFrame` frame counting per 1-second interval
    - `onTickReceived(vals)` — extract `_lt_ts`, compute end-to-end delay (ns → ms)
    - `reportMetrics()` — send `{type: "load-test-metrics", fps, rendered_count, avg_delay_ms}` via WS every 1 second
    - WS disconnect detection → stop collecting + display warning
    - Wire into `binding.ts` (conditional import when load test active)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 9. Implement Post-Test Cleanup
  - [x] 9.1 Add cleanup logic to LoadTestRunner (or separate LoadTestCleanup class)
    - `FILES_TO_DELETE` list: all 5 load-test source files
    - `MODIFIED_FILES` dict: store original content of app.py and binding.ts before modification
    - `execute(result_path)` — verify result JSON exists → restore modified files → delete test files
    - Error handling: skip deletion if result write failed, log individual file deletion errors, save `.bak` on restore failure
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 9.2 Write property test for post-test state restoration
    - **Property 12: Post-Test State Restoration** — random settings dicts, verify round-trip equality after cleanup
    - **Validates: Requirements 8.4, 9.4**

- [ ] 10. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Integration wiring and end-to-end test
  - [x] 11.1 Wire all components together
    - LoadTestRunner instantiates MockTickGenerator and MetricsCollector
    - API routes reference singleton LoadTestRunner instance
    - Frontend MetricsReporter conditionally activates on load-test-start WS event
    - Cleanup triggers after result generation in both normal and stop flows
    - Verify import paths and module registration
    - _Requirements: 2.1, 7.1, 8.1, 9.1_

  - [ ]* 11.2 Write integration test (mini 2-step run)
    - Execute 2-step test (100, 200 tps × 2 seconds each) end-to-end
    - Verify StepResult generation for both steps
    - Verify result JSON file creation
    - Verify cleanup deletes test files after completion
    - Mock frontend WS metrics reporting
    - _Requirements: 2.1, 4.6, 6.1, 9.1_

- [ ] 12. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All load test modules are TEMPORARY — they self-delete after test completion, leaving only the result JSON
- Property tests use `hypothesis` library (already in project) with `@settings(max_examples=100)`
- Each property test file tagged with `# Feature: load-test-pipeline, Property N: {title}`
- Test files location: `backend/tests/test_load_test_properties.py`, `backend/tests/test_load_test_unit.py`, `backend/tests/test_load_test_integration.py`
- Stock codes use T-prefix (T000001~T000050) to avoid collision with real 6-digit codes
- Tick injection uses `asyncio.call_later` chain (no polling loops per workspace rules)
- Direct synchronous call to `_handle_real_01` (no `create_task` per workspace rules)
- `psutil` for CPU/memory metrics, collected outside tick processing path
- `pathlib.Path` for all file operations (cross-platform per workspace rules)
