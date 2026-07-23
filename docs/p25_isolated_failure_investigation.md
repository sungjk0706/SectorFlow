# SectorFlow P25 (격리된 실패) 전수 조사 보고서

> 작성일: 2026-07-23
> 기준 문서: `ARCHITECTURE.md` 제1부 P25 (불변 원칙 25개 중 25번째)
> 성격: 조사 보고서 (AGENTS.md 문서 저장 경로 규칙 — `docs/*_investigation.md`, 역사적 기록 유지, 규칙 11 삭제 제외)
> 진행 방식: 조사만 수행 (수정은 별도 승인 세션에서 진행)

---

## 1. 조사 개요

### 1.1 목적

P25 (격리된 실패) 원칙 관점에서 전체 코드베이스 전수 조사.
- 한 구성요소의 실패가 전체 시스템 기동/운영을 블로킹할 수 있는 취약점 식별
- 실패가 해당 구성요소에서 차단+로깅되는지, 다른 구성요소가 정상 작동 유지되는지 점검
- 관련 원칙(P7/P9/P16/P20/P23)과의 교차 점검

### 1.2 P25 핵심 내용 (ARCHITECTURE.md 발췌)

- 한 구성요소 실패가 전체 시스템 기동/운영 블로킹 금지
- 실패는 해당 구성요소에서 차단+로깅, 다른 구성요소 정상 작동 유지
- 격리 ≠ silent 무시 — 반드시 에러 로깅 (P20/P23 일관)
- P24 균형: 최소 전파 차단에 국한, 과도한 격리 추상화 금지

### 1.3 조사 범위

#### A. 프론트엔드 (3개 영역)
- **A1. WS 이벤트 디스패치**: `frontend/src/api/ws.ts`, `frontend/src/binding.ts`
- **A2. Store listener 전파**: `frontend/src/stores/store.ts`, `hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts`
- **A3. UI 컴포넌트 렌더링·DOM 리스너**: 36개 파일 (pages, components/common, layout)

#### B. 백엔드 (5개 영역)
- **B1. 엔진 코어 루프·태스크 스케줄러**: `engine_lifecycle.py`, `engine_loop.py`, `engine_ws*.py` 6개
- **B2. 파이프라인 연산 루프**: `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `pipeline_gateway.py`
- **B3. 대형 스케줄러·파이프라인**: `daily_time_scheduler.py`, `market_close_pipeline.py`
- **B4. 워커·IO·재시도 루프**: `notification_worker.py`, `db_writer.py`, `telegram_bot.py`, `kiwoom_rest.py`, `kiwoom_stock_rest.py`, `engine_cache.py`, `app.py`, `ws.py`/`ws_settings.py`/`ws_orders.py`
- **B5. 매매·테스트모드 태스크**: `trading.py`, `buy_order_executor.py`, `dry_run.py`

#### C. 교차 원칙 점검 (모든 세션에 통합)
- **P7** (블로킹 금지): 틱 핸들러 경로의 예외 전파가 루프 중단 유발 여부
- **P9** (파이프라인 독립): 예외 전파 경로 점검
- **P16** (살아있는 경로): add_done_callback 로깅 실제 발화 여부, dead code 격리 아닌지
- **P20** (폴백 금지): 모든 `except Exception`이 silent pass 아닌지, `exc_info=True` 로깅 여부
- **P23** (일관성): 격리 패턴이 파일 간 동일한지 (`schedule_engine_task` vs 직접 `create_task` 혼용 여부)

### 1.4 조사 방식 (모든 세션 공통)

- 각 파일의 `try/except`, `create_task`, `asyncio.gather`, `while` 루프, `add_done_callback` 패턴 분석
- 위반 후보 식별 시: 파일:줄번호 + 증상 + 영향 범위 기록 → 본 보고서 섹션 2 매트릭스에 누적
- 발견 즉시 `HANDOVER.md` "미해결 문제" 섹션에 병행 기록 (AGENTS.md 섹션4 규칙9)
- 수정은 별도 승인 세션에서 진행 (본 조사는 보고까지만)

### 1.5 9세션 분할

AGENTS.md 섹션3 규칙 0-1 (세션당 1단계 원칙) 준수.

| 세션 | 영역 | 우선순위 | 조사 파일 | 산출물 |
|------|------|----------|-----------|--------|
| 1 | A1 WS 디스패치 | 1 | `api/ws.ts`, `binding.ts` | 핸들러별 격리 여부 매트릭스 |
| 2 | B1 엔진 코어 루프 | 2 | `engine_lifecycle.py`, `engine_loop.py`, `engine_ws*.py` 6개 | 루프·태스크 격리 매트릭스 |
| 3 | B2 파이프라인 연산 | 3 | `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `pipeline_gateway.py` | compute 루프·sector 재계산 루프 격리 점검 |
| 4 | A2 Store listener | 4 | `store.ts`, `hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts` | listener 전파 차단 검증 + 추가 setState 경로 |
| 5 | B3 대형 스케줄러·파이프라인 | 5 | `daily_time_scheduler.py`, `market_close_pipeline.py` | schedule_engine_task 호출별 격리 + except 블록 P20 점검 |
| 6 | B4 워커·IO·재시도 | 6 | `notification_worker.py`, `db_writer.py`, `telegram_bot.py`, `kiwoom_rest.py`, `kiwoom_stock_rest.py`, `engine_cache.py`, `app.py`, `ws.py`/`ws_settings.py`/`ws_orders.py` | 워커·재시도 루프 격리 점검 |
| 7 | A3 UI 컴포넌트 렌더링 | 7 | 36개 파일 (pages, components/common, layout) | 컴포넌트·DOM 리스너 격리 매트릭스 |
| 8 | B5 매매·테스트모드 | 8 | `trading.py`, `buy_order_executor.py`, `dry_run.py` | dry_run 태스크·매매 경로 격리 점검 |
| 9 | C 교차 점검·총합 보고 | 9 | 전 세션 결과 취합 | P25 위반 전체 목록 + P7/P9/P16/P20/P23 교차 매트릭스 + 우선수정 추천 |

### 1.6 우선순위 기준 (영향도 큰 것부터)

| 순위 | 영역 | 사유 |
|------|------|------|
| 1 | A1 WS 디스패치 | 매 이벤트 통과. 한 핸들러 throw 시 전 채널 이벤트 수신 중단 → 화면 전체 멈춤 |
| 2 | B1 엔진 코어 루프 | 매 틱·매 이벤트 통과. 한 번 중단 시 자동매매 전체 정지 |
| 3 | B2 파이프라인 연산 루프 | 업종 점수·매수 후보 산출 경로. 중단 시 매수 후보 미갱신 |
| 4 | A2 Store listener | 화면 갱신 최종 경로 |
| 5 | B3 대형 스케줄러·파이프라인 | 장 마감 후 파이프라인·타임테이블 |
| 6 | B4 워커·IO·재시도 루프 | 알림·DB·재시도. 실패 시 일부 기능 손실 |
| 7 | A3 UI 컴포넌트 렌더링 | 개별 화면 단위 격리. 영향도 국소적 |
| 8 | B5 매매·테스트모드 태스크 | dry_run 태스크. 테스트모드 한정 |
| 9 | C 교차 점검·총합 보고 | 모든 세션 결과 취합 |

### 1.7 사전 확인된 주요 위반 후보 (조사 전 단계, 확정은 각 세션에서)

- `frontend/src/api/ws.ts:193` — `_dispatchMessage`의 `list.forEach(h => h(data))` 핸들러별 try/catch 누락 (P25 위반 후보)
- `backend/app/pipelines/pipeline_compute.py:209,214` — `create_task` 직접 호출 (schedule_engine_task 미사용, P23 일관성 위반 후보)
- `backend/app/services/trading.py:477,666` — dry_run 태스크 `create_task` 직접 호출 (P23 위반 후보)

---

## 2. P25 위반 매트릭스 (빈 템플릿 — 세션별 누적 갱신)

> 각 세션 조사 완료 후 위반 식별 시 본 매트릭스에 행 추가.
> ID 형식: `{영역}-{세션번호}-{순번}` (예: `A1-01-01`).

| ID | 영역 | 파일:줄 | 위반 내용 | 영향 범위 | 등급 | 관련 원칙 | 조사 세션 | 수정 승인 |
|----|------|---------|-----------|-----------|------|-----------|-----------|-----------|
| A1-01-01 | A1 WS 디스패치 | `frontend/src/api/ws.ts:193` | `_dispatchMessage`의 `list.forEach(h => h(data))`가 핸들러별 try/catch 없음. 한 핸들러 throw 시 forEach 즉시 중단 → 같은 event type의 후속 핸들러 미실행 + 예외가 `_handleBinaryFrame`/`_handleTextFrame` catch로 전파 | 같은 이벤트의 다른 핸들러 미실행 + (binary) 같은 프레임 후속 이벤트 손실. 화면 갱신 경로 전체가 WS 디스패치 단계에서 차단될 수 있음 | CRITICAL | P25, P21 | 세션 1 | 미승인 |
| A1-01-02 | A1 WS 디스패치 | `frontend/src/api/ws.ts:164-174` | `_handleBinaryFrame`의 `for (const event of events)` 루프가 try 블록 내부. 한 이벤트 핸들러 throw 시 catch(171)가 잡지만 루프 중단 → 같은 바이너리 프레임의 나머지 이벤트 모두 손실 | real-data는 고빈도 바이너리 프레임. 한 종목 핸들러 오류가 같은 프레임의 다른 종목 시세 갱신을 막음 → 화면 일부 종목 시세 정지 | CRITICAL | P25, P7 | 세션 1 | 미승인 |
| A1-01-03 | A1 WS 디스패치 | `frontend/src/api/ws.ts:172,181` | `_handleBinaryFrame`/`_handleTextFrame` catch 블록이 "디코딩 실패"/"파싱 실패"로 로깅. 실제로는 핸들러 예외일 수도 있어 로그 메시지가 원인을 잘못 표시 | 잘못된 로그로 디버깅 방해. P21(사용자 투명성) — 개발자가 원인 파악 불가. P23(일관성) — 에러 분류 불일치 | MEDIUM | P21, P23 | 세션 1 | 미승인 |
| A1-01-04 | A1 WS 디스패치 | `frontend/src/binding.ts` (33개 핸들러 전체) | 33개 onEvent 핸들러 중 어느 것도 내부 try/catch 없음. store.ts setState listener 루프는 F-02 fix로 보호되나, (a) 핸들러 본문 로직(destructuring, recalcTradeAmountRank, rebuildBuyTargetIndex, 중첩 property access), (b) setState의 updater 함수(`partial(state)` — store.ts:19), (c) applyXxx 함수 본문은 보호되지 않음. throw 시 A1-01-01/02로 전파 | 고위험 핸들러: `buy-targets-delta`(114-161, 복잡 로직), `sector-scores`(287-310, 중첩 접근), `sector-stocks-delta`(95-112), `circuit_breaker_open`(318-322, showToast). 이들 throw 시 WS 디스패치 단계에서 다른 이벤트까지 손실 | HIGH | P25, P16 | 세션 1 | 미승인 |
| A1-01-05 | A1 WS 디스패치 | `frontend/src/api/ws.ts:132-136` | `_scheduleReconnect`의 setTimeout 콜백이 `_connect()` 호출 시 try/catch 없음. `_connect` 동기 throw 시 재연결 루프 영구 중단 | `_connect`는 단순 WebSocket 생성으로 동기 throw 확률 낮음. 단, `disconnect()` 내부 오류 시 throw 가능. 발생 시 WS 영구 단절 | LOW | P25 | 세션 1 | 미승인 |

### 등급 정의
- **CRITICAL**: 한 구성요소 실패가 시스템 전체 중단 유발 (자동매매 정지, 화면 전체 멈춤)
- **HIGH**: 한 구성요소 실패가 주요 기능(매수 후보 산출, 업종 점수 등) 중단 유발
- **MEDIUM**: 한 구성요소 실패가 일부 기능 손실 (알림 누락 등), 시스템은 동작
- **LOW**: 일관성 위반 (혼용 패턴 등), 즉시 중단 유발 아님

### 관련 원칙 표기
- P25 (격리된 실패) — 본 조사 주 원칙
- P7 (블로킹 금지), P9 (파이프라인 독립), P16 (살아있는 경로), P20 (폴백 금지), P23 (일관성) — 교차 점검 대상

---

## 3. 세션 1: A1 WS 디스패치 조사

> 상태: 완료 (2026-07-23)
> 조사 파일: `frontend/src/api/ws.ts` (261줄), `frontend/src/binding.ts` (338줄), `frontend/src/stores/store.ts` (57줄 — 보호 범위 확인용)
> 조사 범위:
> - `_dispatchMessage` (ws.ts:185-194) 핸들러별 try/catch 여부
> - `_handleBinaryFrame` / `_handleTextFrame` (ws.ts:164-183) 디코딩 실패 시 핸들러 호출 차단 여부
> - `binding.ts` 33개 onEvent 핸들러 각각의 내부 예외 처리 여부
> - WS 재연결 루프 (`_scheduleReconnect`) 실패 시 전파 경로
> - store.ts setState try/catch (F-02 fix)의 보호 범위 한계 확인

### 3.1 조사 결과

#### 3.1.1 WS 디스패치 호출 경로 (정상 시)

```
ws.onmessage (ws.ts:104)
  → _handleBinaryFrame(buffer)  /  _handleTextFrame(text)
    → try { decodeProtobufEvents(buffer) / JSON.parse(text) }
      → for (const event of events)  /  단일 msg
        → _dispatchMessage(msg)
          → list.forEach(h => h(data))   ← 핸들러 호출
            → binding.ts 33개 핸들러 중 해당 type
              → applyXxx(...) / hotStore.setState((state) => {...})
                → store.ts setState → listener 루프 (F-02 try/catch 보호)
```

#### 3.1.2 보호 계층 분석 (어디까지 막아주는가)

| 계층 | 위치 | try/catch | 보호 대상 | 비고 |
|------|------|-----------|-----------|------|
| Protobuf 디코딩 | `decodeProtobufEvents` ws.ts:36-53 | O (per-event) | 단일 이벤트 디코딩 실패 | 다른 이벤트는 계속 디코딩. 양호 |
| 바이너리 프레임 루프 | `_handleBinaryFrame` ws.ts:164-174 | O (루프 전체) | 디코딩 + 핸들러 예외 전부 | **문제**: 루프가 try 내부 → 한 핸들러 throw 시 나머지 이벤트 손실 (A1-01-02) |
| 텍스트 프레임 | `_handleTextFrame` ws.ts:176-183 | O (단일) | 파싱 + 핸들러 예외 전부 | catch 로그가 "파싱 실패"로 핸들러 예외와 혼동 (A1-01-03) |
| 핸들러 디스패치 | `_dispatchMessage` ws.ts:193 | X | 핸들러별 격리 | **핵심 위반**: `forEach` 내 핸들러별 try/catch 없음 (A1-01-01) |
| binding.ts 핸들러 본문 | binding.ts 33개 | X | 핸들러 로직 | 33개 전부 try/catch 없음 (A1-01-04) |
| setState updater 함수 | store.ts:19 `partial(state)` | X | updater 함수 본문 | F-02 fix는 listener 루프(40-46)만 보호. updater throw는 보호 안됨 |
| setState listener 루프 | store.ts:40-46 | O (per-listener) | UI 렌더링 listener | F-02 fix. 양호. 단, binding.ts 핸들러 오류는 여기 도달 전 전파 |

**핵심 한계**: F-02 fix(store.ts listener 루프 try/catch)는 UI 렌더링 listener만 보호. binding.ts 핸들러 본문 로직 + setState updater 함수는 보호되지 않아, 이들 throw 시 예외가 store.ts를 넘어 ws.ts 디스패치 단계로 역전파 → A1-01-01/02 위반 경로로 합류.

#### 3.1.3 binding.ts 33개 핸들러 분류

| 채널 | 핸들러 수 | 위험도 | 고위험 핸들러 (복잡 로직) |
|------|-----------|--------|---------------------------|
| prices | 25 | HIGH | `buy-targets-delta`(114-161), `sector-scores`(287-310), `sector-stocks-delta`(95-112), `sell-history-append`(234-242), `circuit_breaker_open`(318-322, showToast) |
| settings | 6 | MEDIUM | `avg-amt-progress`(209-211, 다중 optional 필드), `bootstrap-stage`(205-207) |
| orders | 2 | LOW | `order-filled`(220-222), `test-data-reset-completed`(225-227) — 단순 applyXxx 호출 |

전 33개 핸들러가 내부 try/catch 없음. 단순 핸들러(orders 채널 등)는 applyXxx 내부 오류 가능성만 남고, 복잡 핸들러(prices 채널)는 핸들러 본문 자체 오류 가능성이 높음.

#### 3.1.4 재연결 루프 분석

- `_scheduleReconnect` (ws.ts:132-136): setTimeout 콜백 → `_connect()`. try/catch 없음.
- `_connect` (ws.ts:89-130): `disconnect()` → `new WebSocket(url)` → 핸들러 설정. 동기 throw 가능성 낮으나 `disconnect()` 내부 오류 시 throw 가능.
- ping 타이머 (ws.ts:141-154): `ws.send` try/catch 있음. 2회 실패 시 close + reconnect. 양호.
- `onclose` (ws.ts:118-129): 1008(인증거부) 시 재연결 안함(의도적). 나머지 `_scheduleReconnect`. 양호.

#### 3.1.5 사전 위반 후보(1.7절) 확정 결과

- `ws.ts:193` `_dispatchMessage` forEach — **확정 CRITICAL** (A1-01-01)
- (백엔드 후보 2건은 세션 3/8에서 조사 예정)

### 3.2 위반 목록

| ID | 등급 | 파일:줄 | 위반 요약 | 수정 방향 (참고용, 승인 시 별도 세션) |
|----|------|---------|-----------|---------------------------------------|
| A1-01-01 | CRITICAL | ws.ts:193 | `_dispatchMessage` 핸들러별 try/catch 없음 | `forEach`를 try/catch 감싼 루프로 변경, 핸들러 throw 시 `console.error('[WS] handler error', type, e)` + 다른 핸들러 계속 실행 |
| A1-01-02 | CRITICAL | ws.ts:164-174 | `_handleBinaryFrame` 루프가 try 내부 → 후속 이벤트 손실 | 디코딩 try와 핸들러 디스패치 try 분리. 디코딩은 프레임 단위, 핸들러는 per-event try (A1-01-01 수정으로 자연 해결) |
| A1-01-03 | MEDIUM | ws.ts:172,181 | catch 로그가 "파싱 실패"로 핸들러 예외와 혼동 | 디코딩/파싱 catch와 핸들러 catch 분리 후 각각 목적에 맞는 로그 메시지 |
| A1-01-04 | HIGH | binding.ts 33개 핸들러 | 내부 try/catch 없음 | (a) A1-01-01 수정으로 디스패치 단계 격리 확보 시 핸들러 개별 try/catch는 선택적. (b) 단, 고위험 핸들러(buy-targets-delta 등)는 본문 try/catch 권장 — 디스패치 격리와 본문 격리는 상호 보완. 최종 방침은 수정 세션에서 결정 |
| A1-01-05 | LOW | ws.ts:132-136 | `_scheduleReconnect` setTimeout 콜백 try/catch 없음 | `_connect()` 호출을 try/catch 감싸고 실패 시 `_scheduleReconnect` 재호출(백오프 유지) |

### 3.3 교차 원칙 점검 (세션 1 범위)

| 원칙 | 해당 여부 | 비고 |
|------|-----------|------|
| P7 (블로킹 금지) | 해당 | A1-01-02: 바이너리 프레임 루프 중단 = 시세 갱신 블로킹. 틱 핸들러 경로는 아니지만 고빈도 real-data 경로 |
| P9 (파이프라인 독립) | 해당 아님 | WS 디스패치는 파이프라인 아님 |
| P16 (살아있는 경로) | 해당 | A1-01-04: 핸들러 본문 보호 없음 = 예외 시 경로 사망. F-02 fix는 listener 경로만 살림 |
| P20 (폴백 금지) | 해당 아님 | 본 세션에서 silent `except: pass` 없음. 모든 catch는 console.error 로깅 |
| P23 (일관성) | 해당 | A1-01-03: 에러 로그 메시지 불일치(파싱 vs 핸들러). P25 격리 패턴이 ws.ts 내에서도 불일치(디코딩은 per-event, 핸들러는 per-batch) |

---

## 4. 세션 2: B1 엔진 코어 루프 조사

> 상태: 미시작
> 조사 파일: `engine_lifecycle.py`, `engine_loop.py`, `engine_ws_dispatch.py`, `engine_ws.py`, `engine_ws_fill_followup.py`, `engine_ws_parsing.py`, `engine_ws_reg.py`
> 조사 범위:
> - `schedule_engine_task` (engine_lifecycle.py:279-309) 중앙 격리 메커니즘 검증
> - `engine_loop.py:302` 메인 루프 while 내부 try/except 전파 차단
> - `engine_loop.py:343-344` create_task 직접 호출 (stop_wait/change_wait) 격리
> - engine_ws_* 6개 파일의 이벤트 핸들러 예외 전파 경로

### 4.1 조사 결과
_작성 예정_

### 4.2 위반 목록
_작성 예정_

---

## 5. 세션 3: B2 파이프라인 연산 루프 조사

> 상태: 미시작
> 조사 파일: `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `pipeline_gateway.py`
> 조사 범위:
> - `pipeline_compute.py:209,214` create_task 직접 호출 (schedule_engine_task 미사용 — P23 위반 후보)
> - `pipeline_compute.py:247` `while True` 루프 내부 예외 격리
> - `_compute_loop_impl` / `_sector_recompute_loop_impl` 루프 실패 시 전파 경로
> - tick_handlers의 틱 핸들러 예외 처리 (P7 교차)

### 5.1 조사 결과
_작성 예정_

### 5.2 위반 목록
_작성 예정_

---

## 6. 세션 4: A2 Store listener 조사

> 상태: 미시작
> 조사 파일: `frontend/src/stores/store.ts`, `hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts`
> 조사 범위:
> - `store.ts:40-46` listener 루프 try/catch 검증 (F-02 해결 시 추가됨)
> - `hotStore.ts` apply* 함수들의 setState 경로 — listener throw 유발 가능성
> - `uiStore.ts` apply* 함수들의 setState 경로
> - `stockClassificationStore.ts` setState 경로

### 6.1 조사 결과
_작성 예정_

### 6.2 위반 목록
_작성 예정_

---

## 7. 세션 5: B3 대형 스케줄러·파이프라인 조사

> 상태: 미시작
> 조사 파일: `daily_time_scheduler.py` (1524줄), `market_close_pipeline.py` (1407줄)
> 조사 범위:
> - `daily_time_scheduler.py` schedule_engine_task 15회 호출별 context 명시·격리 여부
> - `market_close_pipeline.py` except 블록 19개 — silent pass 여부 (P20 교차), exc_info 로깅 여부
> - 파이프라인 단계 간 실패 전파 경로 (P9 교차)
> - `call_later` / `call_soon_threadsafe` 콜백 실패 시 루프 영향

### 7.1 조사 결과
_작성 예정_

### 7.2 위반 목록
_작성 예정_

---

## 8. 세션 6: B4 워커·IO·재시도 루프 조사

> 상태: 미시작
> 조사 파일: `notification_worker.py`, `db_writer.py`, `telegram_bot.py`, `kiwoom_rest.py`, `kiwoom_stock_rest.py`, `engine_cache.py`, `app.py`, `ws.py`, `ws_settings.py`, `ws_orders.py`
> 조사 범위:
> - `notification_worker.py:55` `_consume_loop` while 루프 예외 격리
> - `kiwoom_rest.py:377,383` / `kiwoom_stock_rest.py:156,321` while 재시도 루프 실패 시 전파
> - `ws.py:171` WS 서버 while 루프 — 클라이언트별 격리
> - `ws_settings.py:29`, `ws_orders.py:29` WS 루프
> - `app.py:62,141,146` 시작 태스크 실패 시 기동 블로킹 여부 (P25 핵심 — 기동 블로킹 금지)

### 8.1 조사 결과
_작성 예정_

### 8.2 위반 목록
_작성 예정_

---

## 9. 세션 7: A3 UI 컴포넌트 렌더링 조사

> 상태: 미시작
> 조사 파일: 36개 파일 (pages/*, components/common/*, layout/*)
> 조사 범위:
> - `subscribe()` 리스너 내부 렌더링 실패 시 전파
> - `addEventListener` 콜백 실패 시 전파
> - 컴포넌트 팩토리 내부 DOM 조작 예외 처리
> - 개별 칩/컴포넌트 렌더링 실패가 전체 화면 중단 유발 여부 (F-02 사례와 동일 패턴)

### 9.1 조사 결과
_작성 예정_

### 9.2 위반 목록
_작성 예정_

---

## 10. 세션 8: B5 매매·테스트모드 태스크 조사

> 상태: 미시작
> 조사 파일: `trading.py`, `buy_order_executor.py`, `dry_run.py`
> 조사 범위:
> - `trading.py:477,666` dry_run fake_fill create_task 직접 호출 (P23 위반 후보)
> - `add_done_callback` 로깅 실제 발화 여부 (P16 교차)
> - 매매 경로 예외 전파 — 매수/매도 실패 시 엔진 루프 영향
> - safe-trade 스킬 연계 (거래 로직 수정 시 별도 스킬 필수)

### 10.1 조사 결과
_작성 예정_

### 10.2 위반 목록
_작성 예정_

---

## 11. 세션 9: 교차 점검·총합 보고

> 상태: 미시작
> 조사 범위: 세션 1~8 결과 취합 + 교차 원칙 매트릭스 작성 + 우선수정 추천

### 11.1 P25 위반 전체 목록 (취합)
_세션 1~8 완료 후 본 섹션 2 매트릭스와 연동_

### 11.2 교차 원칙 매트릭스 (빈 템플릿)

| 위반 ID | P25 | P7 | P9 | P16 | P20 | P23 | 비고 |
|---------|-----|----|----|-----|-----|-----|------|
| _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ |

### 11.3 우선수정 추천 (영향도 순)
_세션 1~8 완료 후 작성_

### 11.4 조사 완료 정의
- 본 보고서 섹션 2 매트릭스에 모든 위반 누적 완료
- 교차 원칙 매트릭스 (11.2) 작성 완료
- 우선수정 추천 (11.3) 작성 완료
- 각 위반에 대해 별도 수정 세션 승인 대기 상태로 이관

---

## 12. 변경 이력

| 날짜 | 세션 | 변경 내용 |
|------|------|-----------|
| 2026-07-23 | (준비) | 본 보고서 생성 (조사 개요, 매트릭스 빈 템플릿, 세션 1~9 기본 구조) |
| 2026-07-23 | 세션 1 | A1 WS 디스패치 조사 완료. 위반 5건 식별 (A1-01-01~05). 섹션 2 매트릭스 + 섹션 3 결과 작성. CRITICAL 2건, HIGH 1건, MEDIUM 1건, LOW 1건 |
