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
| _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ | _빈_ |

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

> 상태: 미시작
> 조사 파일: `frontend/src/api/ws.ts`, `frontend/src/binding.ts`
> 조사 범위:
> - `_dispatchMessage` (ws.ts:185-194) 핸들러별 try/catch 여부
> - `_handleBinaryFrame` / `_handleTextFrame` (ws.ts:164-183) 디코딩 실패 시 핸들러 호출 차단 여부
> - `binding.ts` 33개 onEvent 핸들러 각각의 내부 예외 처리 여부
> - WS 재연결 루프 (`_scheduleReconnect`) 실패 시 전파 경로

### 3.1 조사 결과
_작성 예정_

### 3.2 위반 목록
_작성 예정_

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
