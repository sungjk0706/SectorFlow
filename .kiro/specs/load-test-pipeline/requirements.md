# Requirements Document

## Introduction

SectorFlow 실시간 데이터 파이프라인의 최대 부하 한계를 측정하기 위한 로드 테스트 도구. 실제 증권사 WebSocket을 사용하지 않고, 백엔드 내부에 Mock Tick Generator를 구현하여 동일한 처리 경로(engine_ws_dispatch → engine_sector_confirm → ws_manager broadcast)에 합성 틱을 주입한다. 단계별로 부하를 증가시키며 처리 지연, CPU, FPS, 메모리, 틱 유실률을 측정하고, 정지 조건 도달 시 자동 중단하여 시스템의 안전 한계를 도출한다.

## Glossary

- **Load_Test_Runner**: 부하 테스트 전체 실행을 오케스트레이션하는 백엔드 모듈
- **Mock_Tick_Generator**: 합성 틱 데이터를 생성하여 기존 WS 처리 경로에 주입하는 컴포넌트
- **Step**: 특정 ticks/sec 속도로 일정 시간 동안 틱을 주입하는 단일 부하 단계
- **Metrics_Collector**: 각 Step 동안 처리 지연, CPU, 메모리, 틱 유실 등을 수집하는 컴포넌트
- **Frontend_Metrics_Reporter**: 프론트엔드에서 FPS 및 렌더링 지연을 측정하여 백엔드에 보고하는 모듈
- **Stop_Condition**: 시스템 과부하를 감지하여 테스트를 즉시 중단시키는 조건
- **Result_Report**: 모든 Step의 측정 결과를 표 형태로 정리한 최종 보고서
- **Processing_Delay**: 틱 주입 시점부터 프론트엔드 화면 갱신까지의 경과 시간(ms)
- **Tick_Loss_Rate**: 주입된 틱 대비 프론트엔드에 실제 반영되지 않은 틱의 비율(%)
- **Comfortable_Throughput**: 모든 지표가 정상 범위 내에서 유지되는 최대 처리량
- **Limit_Throughput**: Stop Condition에 도달하기 직전의 최대 처리량

## Requirements

### Requirement 1: Mock Tick Generator

**User Story:** As a developer, I want a mock tick generator that injects synthetic ticks into the same processing path as real broker WebSocket messages, so that I can stress-test the pipeline without connecting to Kiwoom Securities.

#### Acceptance Criteria

1. THE Mock_Tick_Generator SHALL produce tick data containing stock code, current price, price change, change rate, trade amount, and strength for each tick
2. WHEN generating ticks, THE Mock_Tick_Generator SHALL simulate realistic price movements by applying random walk with bounded volatility to previous prices
3. THE Mock_Tick_Generator SHALL distribute ticks across a configurable set of stock codes (minimum 20 codes)
4. WHEN a tick is generated, THE Mock_Tick_Generator SHALL inject it into the `engine_ws_dispatch._handle_real_01` processing path using the same data format as Kiwoom WebSocket REAL messages
5. THE Mock_Tick_Generator SHALL maintain per-stock state (last price, cumulative trade amount) to produce coherent sequential tick data
6. WHILE the load test is running, THE Mock_Tick_Generator SHALL NOT connect to any external WebSocket or REST API

### Requirement 2: Step-Based Load Escalation

**User Story:** As a developer, I want the load test to increase tick injection rate in predefined steps, so that I can identify the exact throughput level where degradation begins.

#### Acceptance Criteria

1. THE Load_Test_Runner SHALL execute steps in ascending order: 100, 200, 500, 1000, 2000, 5000, 10000 ticks per second
2. WHEN a step begins, THE Load_Test_Runner SHALL maintain the configured tick rate for exactly 30 seconds before advancing to the next step
3. WHEN advancing between steps, THE Load_Test_Runner SHALL pause for 5 seconds to allow system stabilization
4. THE Load_Test_Runner SHALL distribute tick injections uniformly across each 1-second interval to avoid burst patterns
5. IF a Stop Condition is triggered during a step, THEN THE Load_Test_Runner SHALL immediately terminate the current step and skip all remaining steps

### Requirement 3: Stop Conditions

**User Story:** As a developer, I want the test to automatically stop when the system reaches dangerous thresholds, so that I can prevent crashes and data corruption.

#### Acceptance Criteria

1. WHILE the load test is running, THE Metrics_Collector SHALL evaluate all Stop Conditions at 1-second intervals
2. IF backend CPU usage exceeds 90%, THEN THE Load_Test_Runner SHALL immediately stop tick injection and record the stop reason
3. IF the Frontend_Metrics_Reporter reports frame rate below 30 FPS, THEN THE Load_Test_Runner SHALL immediately stop tick injection and record the stop reason
4. IF the WebSocket connection between backend and frontend drops, THEN THE Load_Test_Runner SHALL immediately stop tick injection and record the stop reason
5. IF memory usage grows by more than 500 MB within any 60-second window, THEN THE Load_Test_Runner SHALL immediately stop tick injection and record the stop reason
6. IF average tick processing time exceeds 100 ms over a 5-second window, THEN THE Load_Test_Runner SHALL immediately stop tick injection and record the stop reason

### Requirement 4: Per-Step Metrics Collection

**User Story:** As a developer, I want detailed performance metrics collected at each step, so that I can analyze exactly where bottlenecks occur.

#### Acceptance Criteria

1. THE Metrics_Collector SHALL measure processing delay (ms) from tick injection timestamp to frontend screen update acknowledgment for each tick
2. THE Metrics_Collector SHALL record backend CPU usage (%) by comparing current usage against idle baseline measured before the test starts
3. THE Frontend_Metrics_Reporter SHALL measure frame rate (FPS) using `requestAnimationFrame` timing and report it to the backend every second via WebSocket
4. THE Metrics_Collector SHALL record memory usage (MB) as the delta between current process RSS and the baseline measured before the test starts
5. THE Metrics_Collector SHALL calculate tick loss rate (%) by comparing ticks injected by Mock_Tick_Generator against ticks acknowledged as rendered by the frontend
6. WHEN a step completes, THE Metrics_Collector SHALL compute average delay, maximum delay, average CPU, average FPS, peak memory delta, and tick loss rate for that step

### Requirement 5: Frontend Metrics Reporter

**User Story:** As a developer, I want the frontend to report rendering performance back to the backend during load tests, so that end-to-end latency and frame drops are accurately measured.

#### Acceptance Criteria

1. WHEN the load test mode is active, THE Frontend_Metrics_Reporter SHALL measure FPS using `requestAnimationFrame` frame counting over 1-second intervals
2. WHEN the load test mode is active, THE Frontend_Metrics_Reporter SHALL track the timestamp of each received tick and the timestamp of its corresponding DOM update to compute rendering delay
3. THE Frontend_Metrics_Reporter SHALL send metrics (FPS, rendered tick count, average render delay) to the backend via WebSocket every 1 second
4. WHEN a tick arrives with a load-test injection timestamp, THE Frontend_Metrics_Reporter SHALL extract that timestamp and compute the end-to-end processing delay
5. IF the WebSocket connection to the backend is lost, THEN THE Frontend_Metrics_Reporter SHALL stop collecting metrics and display a disconnection warning

### Requirement 6: Result Report Generation

**User Story:** As a developer, I want a structured result report after the test completes, so that I can quickly identify the system's performance limits.

#### Acceptance Criteria

1. WHEN the load test completes (all steps finished or Stop Condition triggered), THE Result_Report SHALL be generated within 5 seconds
2. THE Result_Report SHALL contain a table with columns: Step (ticks/sec), Average Delay (ms), Max Delay (ms), CPU (%), FPS, Memory (MB), Tick Loss Rate (%), Status (✅/⚠️/❌)
3. THE Result_Report SHALL assign status ✅ when all metrics are within normal range (delay < 50ms, CPU < 70%, FPS > 55, memory < 200MB, loss < 1%)
4. THE Result_Report SHALL assign status ⚠️ when any metric enters warning range (delay 50-100ms, CPU 70-90%, FPS 30-55, memory 200-500MB, loss 1-5%)
5. THE Result_Report SHALL assign status ❌ when a Stop Condition was triggered during that step
6. THE Result_Report SHALL include a conclusions section containing: maximum comfortable throughput, maximum limit throughput, first bottleneck point description, and recommended safe operating limit (70% of comfortable throughput)
7. THE Result_Report SHALL be saved as a JSON file and also printed to the console in a human-readable table format

### Requirement 7: Load Test Lifecycle Control

**User Story:** As a developer, I want to start and stop the load test via a REST API endpoint, so that I can trigger it programmatically or from a simple UI button.

#### Acceptance Criteria

1. WHEN a POST request is received at `/api/load-test/start`, THE Load_Test_Runner SHALL begin the test sequence from Step 1
2. WHEN a POST request is received at `/api/load-test/stop`, THE Load_Test_Runner SHALL immediately stop tick injection and generate the Result_Report with data collected so far
3. WHILE the load test is running, THE Load_Test_Runner SHALL reject additional start requests with HTTP 409 (Conflict)
4. THE Load_Test_Runner SHALL expose a GET endpoint at `/api/load-test/status` returning current step, elapsed time, and latest metrics snapshot
5. IF the application receives SIGINT (Ctrl+C) during a load test, THEN THE Load_Test_Runner SHALL gracefully stop tick injection, generate the partial Result_Report, and allow the application to shut down cleanly

### Requirement 8: Isolation from Production Path

**User Story:** As a developer, I want the load test to be completely isolated from production trading logic, so that no accidental orders are placed during testing.

#### Acceptance Criteria

1. WHILE the load test is active, THE Load_Test_Runner SHALL disable all auto-buy and auto-sell logic regardless of settings
2. WHILE the load test is active, THE Mock_Tick_Generator SHALL NOT trigger any order placement functions
3. WHEN the load test starts, THE Load_Test_Runner SHALL verify that no real broker WebSocket connection is active and refuse to start if one exists
4. WHEN the load test ends, THE Load_Test_Runner SHALL restore all engine settings to their pre-test state
5. THE Mock_Tick_Generator SHALL use stock codes that are clearly distinguishable as test data (prefixed with "T" or using a dedicated test code range)

### Requirement 9: Post-Test Cleanup

**User Story:** As a developer, I want all load test source files to be automatically deleted after the test completes, keeping only the test result report, so that the codebase stays clean and test artifacts don't accumulate.

#### Acceptance Criteria

1. WHEN the load test completes (either all steps finished or Stop Condition triggered), THE Load_Test_Runner SHALL delete all load-test-specific source files (mock tick generator, metrics collector, frontend metrics reporter, load test runner, load test API routes) from the project
2. THE Load_Test_Runner SHALL NOT delete the generated Result_Report JSON file or any console output logs
3. BEFORE deleting files, THE Load_Test_Runner SHALL verify that the Result_Report has been successfully written to disk
4. THE Load_Test_Runner SHALL restore any modified existing files (e.g., route registrations, frontend entry points) to their pre-test state
5. IF the cleanup process encounters an error, THEN THE Load_Test_Runner SHALL log the error and list the files that could not be deleted, without crashing the application
