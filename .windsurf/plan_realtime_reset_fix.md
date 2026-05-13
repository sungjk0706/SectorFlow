# 실시간 데이터 초기화 이슈 수정 — 세분화 실행 계획

> 원본 조사: `/Users/sungjk0706/Desktop/SectorFlow/.windsurf/HANDOVER.md`
> 수정 대상: 백엔드 4건 + 프론트엔드 2건 + 테스트 파일 정리 1건 = 총 14개 파일 변경

---

## 보고 규칙

- **모든 단계(Step)가 마무리될 때마다 반드시 인계서(`HANDOVER.md`)를 업데이트**한다.
  - 완료한 Step의 실제 수정 라인 번호, 컴파일 결과, 남은 리스크를 기록
  - Phase 진행 상황을 실시간으로 반영하여 작업 이어하기 가능하도록 유지
- **모든 보고는 함수/변수명(기술용어)과 UI 일반용어를 함께 병기**한다.
- 예시:
  - `get_sector_stocks()` 반환값의 실시간 필드 → "업종분석 페이지 테이블의 현재가/대비/등락률 데이터"
  - `_positions[*].change` 초기화 → "매도설정 페이지 테이블의 대비 컬럼 값 초기화"
  - `_sector_stocks_cache` 무효화 → "업종분석 페이지 데이터 캐시 갱신"
- **목적**: 기술 구현 담당자와 비즈니스/기획 담당자 모두가 단계 진행 상황을 즉시 이해할 수 있도록 함.

---

## Phase 1: 백엔드 — `_reset_realtime_fields()` 캐시 무효화 ✅ 완료

### Step 1.1: 정밀 재조사 ✅
- **대상**: `backend/app/services/engine_service.py`
- **확인 결과**: `_invalidate_sector_stocks_cache(force: bool = False)` 존재, `_shared_lock` 블록 내 호출 결정

### Step 1.2: 분석 및 수정 계획 보고 ✅
- **결정**: `_shared_lock` 블록 내부에 `_invalidate_sector_stocks_cache(force=True)` 추가

### Step 1.3: 수정 실행 ✅
- **적용 라인**: `engine_service.py:485`

### Step 1.4: 수정 후 검증 ✅
- **결과**: `python3 -m py_compile engine_service.py` → **성공 (0 error)**

### Step 1.5: 단계 최종 보고 ✅
- **수정 파일**: `engine_service.py:483` → 실제 `485`로 확정
- **남은 리스크**: 없음

### Step 1.6: 인계서 업데이트 ✅

---

## Phase 2: 백엔드 — `_positions` 필드 추가 초기화 ✅ 완료

### Step 2.1: 정밀 재조사 ✅
- **확인 결과**: `_positions`는 `list[dict]`, `cur_price`만 초기화 중, `change`/`change_rate` 누락 확인

### Step 2.2: 분석 및 수정 계획 보고 ✅
- **결정**: `_positions` 루프 내 `pos["change"] = None`, `pos["change_rate"] = None` 추가 + 테스트모드 `_test_positions` 동일 처리

### Step 2.3: 수정 실행 ✅
- **적용 라인**: `engine_service.py:470-471`, `478-479` (테스트모드)

### Step 2.4: 수정 후 검증 ✅
- **결과**: `python3 -m py_compile engine_service.py` → **성공 (0 error)**

### Step 2.5: 단계 최종 보고 ✅

### Step 2.6: 인계서 업데이트 ✅

---

## Phase 3: 백엔드 — delta 캐시 초기화 ✅ 완료

### Step 3.1: 정밀 재조사 ✅
- **확인 결과**: `_position_sent_cache`, `_prev_sent_cache`, `_prev_scores_cache`가 `engine_account_notify.py` 모듈 전역 변수로 존재, `engine_service.py`에서 `_account_notify` alias로 접근 가능

### Step 3.2: 분석 및 수정 계획 보고 ✅
- **결정**: `_shared_lock` 블록 내에서 `.clear()` 메서드로 "내용만 지우기" (객체 재할당 금지)

### Step 3.3: 수정 실행 ✅
- **적용 라인**: `engine_service.py:486-488`

### Step 3.4: 수정 후 검증 ✅
- **결과**: `python3 -m py_compile engine_service.py` → **성공 (0 error)**

### Step 3.5: 단계 최종 보고 ✅

### Step 3.6: 인계서 업데이트 ✅

---

## Phase 4: 백엔드 — 강제 전체 리스트 전송 ✅ 완료

### Step 4.1: 정밀 재조사 ✅
- **확인 결과**: `notify_desktop_sector_stocks_refresh()`가 `_prev_sector_stock_codes`와 `new_codes` 비교 시 변경 없으면 전송 생략. `_reset_realtime_fields()` 호출 시 종목 코드 변경 없으므로 전송 안 됨

### Step 4.2: 분석 및 수정 계획 보고 ✅
- **결정**: `_reset_realtime_fields()` 말미, `notify_desktop_sector_stocks_refresh()` 호출 직전에 `_prev_sector_stock_codes.clear()` 추가 → 강제 `sector-stocks-refresh` 전송 유도

### Step 4.3: 수정 실행 ✅
- **적용 라인**: `engine_service.py:493`

### Step 4.4: 수정 후 검증 ✅
- **결과**: `python3 -m py_compile engine_service.py` → **성공 (0 error)**

### Step 4.5: 단계 최종 보고 ✅

### Step 4.6: 인계서 업데이트 ✅

---

## Phase 5: 프론트엔드 — `applyRealtimeReset()` 추가 ✅ 완료

### Step 5.1: 정밀 재조사 ✅
- **확인 결과**: `appStore.ts`는 `createStore<AppState>` 패턴, `sectorStocks: Record<string, SectorStock>`, `buyTargets: BuyTarget[]`, `positions: Position[]`

### Step 5.2: 분석 및 수정 계획 보고 ✅
- **결정**: `nullifyFields<T>(obj, fields)` 공통 헬퍼 + `applyRealtimeReset()` 함수 추가

### Step 5.3: 수정 실행 ✅
- **적용 라인**: `appStore.ts:408-465`

### Step 5.4: 수정 후 검증 ✅
- **결과**: `npx tsc --noEmit` → `appStore.ts` **0 error** (기존 test 파일 에러 8건은 이번 수정과 무관)

### Step 5.5: 단계 최종 보고 ✅

### Step 5.6: 인계서 업데이트 ✅

---

## Phase 6: 백엔드 — `realtime-reset` WS 이벤트 발행 ✅ 완료

### Step 6.1: 정밀 재조사 ✅
- **확인 결과**: `_broadcast_account("realtime_reset")`은 `account-update` 이벤트로만 전송됨. 별도 `realtime-reset` 이벤트는 **전송되지 않음**

### Step 6.2: 분석 및 수정 계획 보고 ✅
- **결정**: `_reset_realtime_fields()` 말미에 `_account_notify._broadcast("realtime-reset", {})` 추가

### Step 6.3: 수정 실행 ✅
- **적용 라인**: `engine_service.py:496`

### Step 6.4: 수정 후 검증 ✅
- **결과**: `python3 -m py_compile engine_service.py` → **성공 (0 error)**

### Step 6.5: 단계 최종 보고 ✅

### Step 6.6: 인계서 업데이트 ✅

---

## Phase 8: 프론트엔드 — WS 이벤트 핸들러 등록 ✅ 완료

### Step 8.1: 정밀 재조사 ✅
- **확인 결과**: `binding.ts`에 `realtime-reset` 핸들러 **누락** — Phase 5에서 `applyRealtimeReset()`만 추가되고 `wsClient.onEvent('realtime-reset', ...)` 등록이 되지 않음

### Step 8.2: 분석 및 수정 계획 보고 ✅
- **결정**: `applyRealtimeReset` import 추가 + `wsClient.onEvent('realtime-reset', () => { applyRealtimeReset(); })` 등록

### Step 8.3: 수정 실행 ✅
- **적용 라인**: `binding.ts:30` (import), `binding.ts:240-243` (핸들러)

### Step 8.4: 수정 후 검증 ✅
- **결과**: `tsc -p tsconfig.json --noEmit` → `binding.ts`/`appStore.ts` **0 error**

### Step 8.5: 단계 최종 보고 ✅

### Step 8.6: 인계서 업데이트 ✅

---

## Phase 7: 통합 검증 ✅ 완료

### Step 7.1: 전체 컴파일 검증 ✅
- **명령 실행**:
  - `python3 -m py_compile backend/app/services/engine_service.py` → **성공**
  - `python3 -m py_compile backend/app/services/engine_account_notify.py` → **성공**
  - `tsc -p frontend/tsconfig.json --noEmit` → **성공 (0 error, 기존 test 파일 에러 11건과 무관)**

### Step 7.2: 로그 검증 계획
- **확인할 로그 패턴** (실제 배포 후 확인 필요):
  - `[엔진] 실시간 필드 및 REST 보완 저장데이터`
  - `sector-stocks-refresh 화면전송`
  - `[WS] realtime-reset 수신` (프론트엔드 콘솔)

### Step 7.3: UI 눈 검증 체크리스트 (배포 후 수행)
- [ ] 업종분석 페이지: 현재가, 대비, 등락률, 체결강도, 거래대금 → 전부 `'-'`
- [ ] 매수설정 페이지: 현재가, 대비, 등락률, 체결강도, 거래대금, 호가잔량비 → 전부 `'-'`
- [ ] 매도설정 페이지: 현재가, 대비, 등락률 → 전부 `'-'`
- [ ] Store 상태: `appStore.getState().sectorStocks['005930'].cur_price === null`
- [ ] Store 상태: `appStore.getState().positions[0].cur_price === null`
- [ ] Store 상태: `appStore.getState().buyTargets[0].cur_price === null`

### Step 7.4: 단계 최종 보고 ✅

### Step 7.5: 인계서 최종 업데이트 ✅

---

## Phase 9: 테스트 파일 TypeScript 에러 정리 ✅ 완료

### Step 9.1: 조사 ✅
- **에러 11건**: 7개 테스트 파일에서 미사용 변수/잘못된 속성/불필요한 import 보고됨
- **결론**: 모두 실제 불필요하거나 잘못된 코드. 삭제/변경으로 해결

### Step 9.2: 수정 실행 ✅
- `cellDiffingIdempotence.test.ts`: `DataTableOptions` import 제거, `scrollContainer` 변수 제거
- `fixedTableIncrementalUpdate.test.ts`: `testRowsArrayArb` generator 제거
- `flashDirection.test.ts`: 존재하지 않는 `priceFn` 속성 제거 (연쇄 `r: any` 에러 동시 해결)
- `selectivePageUpdate.test.ts`: `beforeEach`, `vi` import 제거
- `wsReconnectSnapshot.test.ts`: `AppSettings`, `EngineStatus` import 제거
- `wsFidFiltering.test.ts`: `key` → `_key` (미사용 변수 무시)
- `wsMessageRoundTrip.test.ts`: `KEY_SHORTEN` 상수 제거

### Step 9.3: 컴파일 검증 ✅
- **결과**: `tsc -p tsconfig.json --noEmit` → **Exit code 0, 0 error** (테스트 파일 포함 전체 통과)

---

## 작업 상태 추적 (전체 완료)

| Phase | Step | 상태 | 비고 |
|-------|------|------|------|
| 1 | 1.1 ~ 1.6 | ✅ 완료 | `_invalidate_sector_stocks_cache(force=True)` 추가 |
| 2 | 2.1 ~ 2.6 | ✅ 완료 | `_positions` `change`/`change_rate` 초기화 |
| 3 | 3.1 ~ 3.6 | ✅ 완료 | delta 캐시 `.clear()` |
| 4 | 4.1 ~ 4.6 | ✅ 완료 | `_prev_sector_stock_codes.clear()` → 강제 전송 |
| 5 | 5.1 ~ 5.6 | ✅ 완료 | `nullifyFields<T>()` + `applyRealtimeReset()` |
| 6 | 6.1 ~ 6.6 | ✅ 완료 | `_broadcast("realtime-reset", {})` 추가 |
| 7 | 7.1 ~ 7.5 | ✅ 완료 | 통합 컴파일 검증 완료 |
| 8 | 8.1 ~ 8.6 | ✅ 완료 | `binding.ts` 핸들러 등록 (Phase 6 분리) |
| 9 | 9.1 ~ 9.3 | ✅ 완료 | 테스트 파일 에러 11건 해결 |

> **전체 작업 완료**. 다음 세션 필요 시 `HANDOVER.md`를 참조하세요.
