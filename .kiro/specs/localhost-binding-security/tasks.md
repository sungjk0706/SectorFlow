# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - External Network Binding Exposure
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the server binds to all interfaces
  - **Scoped PBT Approach**: Scope the property to the concrete failing cases: `main.py` has `host="0.0.0.0"` and `vite.config.ts` has `host: true`
  - Test that the uvicorn host parameter in `main.py` is set to a loopback address (`127.0.0.1`) — will FAIL on unfixed code because it is `0.0.0.0`
  - Test that the Vite server host in `frontend/vite.config.ts` is set to `localhost` — will FAIL on unfixed code because it is `true`
  - From Bug Condition: `isBugCondition(input) = input.source_ip ≠ "127.0.0.1" AND server_bind_address = "0.0.0.0"`
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists by showing servers bind to `0.0.0.0`)
  - Document counterexamples: `host="0.0.0.0"` in main.py, `host: true` in vite.config.ts
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Local Loopback Access Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: `main.py` uvicorn.run uses port 8000 and the app path `"app.web.app:app"` — these must remain unchanged
  - Observe: `frontend/vite.config.ts` keeps port 5173, proxy config (`/api` → `http://localhost:8000`), and WebSocket support (`ws: true`) — these must remain unchanged
  - Observe: `SectorFlow.command` uses `http://localhost:8000/health` for healthcheck — already uses localhost, no change needed
  - Write property-based test: for all configuration properties OTHER than host binding, values remain identical after fix
  - Verify test passes on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix localhost binding security

  - [x] 3.1 Implement the fix
    - Change `host="0.0.0.0"` to `host="127.0.0.1"` in `main.py` line 62 (uvicorn.run)
    - Change `host: true` to `host: 'localhost'` in `frontend/vite.config.ts` line 7 (server config)
    - _Bug_Condition: isBugCondition(input) where server_bind_address = "0.0.0.0" AND input.source_ip ≠ "127.0.0.1"_
    - _Expected_Behavior: server binds to 127.0.0.1 only, external connections refused at OS network stack level_
    - _Preservation: port numbers, app path, proxy config, WebSocket settings, and all other server options remain unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - External Network Binding Blocked
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (host must be loopback)
    - When this test passes, it confirms the servers now bind to loopback only
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Local Loopback Access Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
