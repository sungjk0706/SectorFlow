# 태스크 파일: 수익현황/수익상세 dailySummary 공유 store 의미 충돌 근본 개선

> **상태**: 2세션(태스크 파일 작성) 완료 → 3세션(백엔드 구현) 대기
> **작성일**: 2026-07-24 (2세션)
> **설계서**: `docs/architecture_profit_pages_daily_summary_design.md`
> **다단계 워크플로우**: 1세션(설계) ✅ → 2세션(사전조사+태스크) ✅ → 3세션(백엔드 설정+WS) 대기 → 4세션(프론트 수익현황) 대기 → 5세션(프론트 수익상세+공통) 대기 → 6세션(테스트+런타임 검증) 대기
> **관련 원칙**: P10 · P13 · P16 · P20 · P21 · P22 · P23 · P24 · P25

---

## 0. 사전조사 결과 요약 (2세션)

### 0.1 의존성 (규칙 0-2 항목1)

**백엔드 4파일 + 프론트엔드 8파일 + 테스트 2파일**

| 파일 | 변경점 | 기준 라인 |
|---|---|---|
| `backend/app/core/settings_defaults.py` | `DEFAULT_USER_SETTINGS`에 `daily_summary_days: 20` 추가 | 143 이전 |
| `backend/app/services/trade_history.py` | `_broadcast_sell_append`·`_broadcast_full_sell_history`의 `days=20` → `days=N`(캐시 참조) + 주석 "해당 일자 요약"→"최근 N거래일 요약" | 184-192, 204-213 |
| `backend/app/services/engine_snapshot.py` | `_get_daily_summary_for_snapshot`의 `days=20` → `days=N`(캐시 참조) + 주석 "20거래일"→"N거래일(사용자 설정)" | 131-136 |
| `backend/app/core/settings_store.py` | `_validate_numeric_fields()`에 `daily_summary_days` 범위 검증 추가 (1~365) | 321 |
| `frontend/src/stores/hotStore.ts` | `profitDateFrom`/`profitDateTo` 필드·초기값 제거. `dailySummary` 주석 "WS push 전용 (최근 N거래일)" 명시 | 34-48, 50-62 |
| `frontend/src/pages/profit-overview.ts` | `ProfitOverviewState`에 `localDailySummary`·`localDateFrom`·`localDateTo` 추가 | 34-72 |
| `frontend/src/pages/profit-overview-mount.ts` | `applyDateRange`에서 `hotStore.setState({ dailySummary, profitDateFrom, profitDateTo })` 제거 → `state.localDailySummary/localDateFrom/localDateTo` 저장. `refreshFilteredViews`가 `hotStore.profitDateFrom/To` 대신 `state.localDateFrom/To` 참조. days 기반 버튼 클릭 시 `settingsMgr.saveSection({ daily_summary_days: N })` 호출. WS push 수신 시 `localDailySummary` 동기화 로직 추가 | 55-60, 199-232, 245-251 |
| `frontend/src/pages/profit-overview-date.ts` | `initDateRange`에서 `hotStore.setState({ profitDateFrom, profitDateTo })` 제거 → 페이지 로컬 상태로 이동 | 55, 58 |
| `frontend/src/pages/profit-detail-mount.ts` | `ensureMonthlyDailySummary` 제거. `restoreInitialView`가 `hotStore.dailySummary`(WS)만 참조 (기존과 동일하나 HTTP 덮어쓰기 제거로 단순화) | 237-265, 267-282 |
| `frontend/src/pages/profit-shared.ts` | `updateSummaryCards`의 당월/누적 카드를 `aggregatePnl(sellHistory)` → `dailySummary` 기반 집계로 변경. `buildMonthlyDrilldown`에 N거래일 초과 시 안내 데이터 추가. "일"→"거래일" 주석 정정 | 132-175, 315-333 |
| `frontend/src/pages/profit-detail-display.ts` | `showDrilldown`에 "최근 N거래일만 표시됨" 안내 문구 렌더링 추가 | 83-109 |
| `frontend/src/settings.ts` (또는 수익현황 설정) | `daily_summary_days` 설정 추가 — 기존 `saveSection` 패턴 준용 | 66-82 |
| `backend/tests/test_trade_history.py` | `days=20` 하드코딩 테스트 → `days=N` 설정 기반 수정 | 기존 파일 |
| `backend/tests/test_engine_snapshot.py` | `_get_daily_summary_for_snapshot` 테스트 → N 설정 기반 수정 | 기존 파일 |

### 0.2 영향 범위 (규칙 0-2 항목2)
- 백엔드 4파일 + 프론트엔드 8파일 + 테스트 2파일
- DB 스키마 변경 **없음** (`integrated_system_settings` 테이블에 설정 키 증분 추가만)
- 거래 로직(`execute_buy`/`execute_sell`) 변경 **없음** (P15 부합)
- WS 이벤트 핸들러(`binding.ts`) 변경 **없음** (이미 WS push만 `hotStore.dailySummary`에 반영)

### 0.3 아키텍처 원칙 부합 (규칙 0-2 항목3)
- **P10 (SSOT)** ✅: `hotStore.dailySummary` 의미 "최근 N거래일" 고정. 3주체 경쟁 덮어쓰기 제거. `updateSummaryCards` sellHistory 재집계 제거.
- **P13 (메모리 상주)** ✅: WS push 3곳이 `integrated_system_settings_cache`에서 N값 조회 (틱 단계 DB 조회 없음).
- **P16 (살아있는 경로)** ✅: `ensureMonthlyDailySummary` 제거 (HTTP 덮어쓰기 dead path 제거). 모든 경로가 WS push로 통일.
- **P20 (폴백 금지)** ✅: `days=20` 하드코딩을 `DEFAULT_USER_SETTINGS`에서 관리. 캐시 조회 시 기본값은 `DEFAULT_USER_SETTINGS`에서만.
- **P21 (사용자 투명성)** ✅: 당월 드릴다운 N거래일 초과 시 안내 문구. 누적 카드 "최근 N거래일 누적"/"전체 누적" 의미 표시.
- **P22 (데이터 정합성)** ✅: 공유 store 의미 고정. 드릴다운과 요약 카드 간 정합성 확보 (둘 다 dailySummary 기반).
- **P23 (일관성)** ✅: 수익현황/수익상세 날짜 범위 관리 패턴 통일 (페이지 로컬). "일"→"거래일" 용어 통일. 기존 설정 전파 패턴 준용.
- **P24 (단순성)** ✅: `profitDateFrom`/`profitDateTo` 공유 store 제거. 3주체 경쟁 구조 제거.
- **P25 (격리된 실패)** ✅: 수익현황 HTTP 조회 실패 시 페이지 로컬만 영향, 공유 store 건드리지 않음.

### 0.4 기존 공통 자산 확인 (규칙 0-2 항목4)
**재사용**:
- `PATCH /api/settings/{field_name}` 설정 변경 API (`backend/app/web/routes/settings.py:26-86`)
- `apply_settings_updates()` DB 증분 저장 (`backend/app/core/settings_store.py:354-378`)
- `refresh_engine_integrated_system_settings_cache()` 캐시 갱신 (`backend/app/services/engine_config.py:60-94`)
- `DEFAULT_USER_SETTINGS` 설정 기본값 dict (`backend/app/core/settings_defaults.py:10-143`)
- `_validate_numeric_fields()` 수치 필드 검증 (`backend/app/core/settings_store.py:321`)
- `settingsMgr.saveSection({ key: value })` 프론트 설정 저장 (`frontend/src/settings.ts:66-82`)
- `api.patchSettingField(key, value)` API 호출 (`frontend/src/api/client.ts:59-62`)
- `applyInitialSnapshotHot` 빈 배열 보존 패턴 (`hotStore.ts:565-600`) — 이미 dailySummary 보존 로직 있음
- `buildMonthlyDrilldown` dailySummary 직접 사용 패턴 (`profit-shared.ts:315-333`) — 이미 P10 준수
- `saveProfitDateRange` localStorage 저장 (`profit-overview-date.ts:36-42`) — 기존 패턴 유지

**신규 생성**: 없음 (모든 기능을 기존 공통 자산으로 구현)

### 0.5 보류 항목 해결 (설계 7-3절)

#### 보류 1: N값 전파 경로 구현 방식
**해결**: 기존 `PATCH /api/settings/{field_name}` 패턴 그대로 준용.
- `DEFAULT_USER_SETTINGS`에 `daily_summary_days: 20` 추가.
- 수익현황 days 기반 버튼(당일→1, 5일→5, 전체→0) 클릭 시 `settingsMgr.saveSection({ daily_summary_days: N })` 호출.
- 백엔드 `settings.py:patch_setting_field` → `apply_settings_updates()` → DB 저장 → `refresh_engine_integrated_system_settings_cache()` → 캐시 갱신.
- WS push 3곳이 `engine_state.state.integrated_system_settings_cache.get("daily_summary_days", 20)` 참조.
- 날짜 범위 버튼(직전, 당월)은 N 변경 없음 — 페이지 로컬에서 WS 데이터 필터링.
- **후처리 핸들러 불필요**: `daily_summary_days`는 실시간 호출 시점에 캐시 참조하므로 `_apply_*_change()` 추가 안 함.

#### 보류 2: 누적 손익 카드 "최근 N거래일 누적" 표시 방식
**해결**: `updateSummaryCards`의 당월/누적 카드를 `aggregatePnl(sellHistory)` → `dailySummary` 기반 집계로 변경.
- **당월 카드**: `dailySummary`에서 당월(`YYYY-MM` prefix) 엔트리의 `realized_pnl` 합계. `pnl_rate`는 가중 평균 또는 단순 합계 (기존 `aggregatePnl` 로직 준용하여 dailySummary 기반으로 재구현).
- **누적 카드**: `dailySummary`의 전체 `realized_pnl` 합계. N거래일 모드 시 "최근 N거래일 누적", "전체" 버튼(days=0) 시 "전체 누적".
- **UI 문구**: 누적 카드 라벨을 "최근 N거래일 누적"으로 동적 변경 (N값 표시). "전체" 모드 시 "전체 누적". 당월 카드는 "당월 손익" 유지 (N 초과 시 안내 문구는 드릴다운에만).
- **계산 범위**: `dailySummary`에 있는 날짜만 집계. N거래일 모드에서 당월이 N 초과 시, 당월 카드는 N거래일 내 당월 날짜만 집계 (안내 문구로 보완 — P21).

#### 보류 3: 수익현황 localDailySummary와 WS push dailySummary 관계
**해결**: 
- `state.localDailySummary`: 사용자 기간 선택 시 HTTP 조회 결과 저장 (공유 store 덮어쓰지 않음 — 설계 4-2절 준수).
- `hotStore.dailySummary`: WS push 전용 (최근 N거래일 — 설계 4-1절 준수).
- **WS push 수신 시 동기화**: 수익현황은 `hotStore.subscribe` 리스너에서 `hotStore.dailySummary` 변경 시 `state.localDailySummary`를 `hotStore.dailySummary`로 동기화. 차트/도넛은 `state.localDailySummary` + `state.localDateFrom/localDateTo`로 필터링 렌더링.
- **days 기반 버튼(당일/5일/전체)**: HTTP 조회 → `state.localDailySummary` 저장 + N값 백엔드 전파. WS push가 같은 범위(days=N)로 갱신 → `localDailySummary` 동기화 (동일 범위이므로 무관).
- **날짜 범위 버튼(직전)**: HTTP 조회 유지 (`api.getPrevTradingDay()` + `api.getDailySummary()`) → `state.localDailySummary` 저장. N 변경 없음. WS push 수신 시 `localDailySummary` 동기화, 차트는 `localDateFrom/To`(직전)로 필터링.
- **날짜 범위 버튼(당월)**: HTTP 조회 안 함 (결정 C 준수). `state.localDailySummary` = `hotStore.dailySummary`(WS)에서 당월 필터링. `localDateFrom/To` = 당월 시작~오늘. N 초과 시 안내 문구 (P21).

---

## 1. 단계 분할 (세션당 1단계, 규칙 0-1)

### 3세션: 백엔드 — `daily_summary_days` 설정 추가 + WS push 3곳 days=N 변경

**목표**: 백엔드 하드코딩 `days=20`을 사용자 설정 N으로 변경. 설정 전파 경로 구축.

**수정 파일 (4파일)**:
1. `backend/app/core/settings_defaults.py`
   - `DEFAULT_USER_SETTINGS`에 `"daily_summary_days": 20` 추가 (라인 143 이전)
   - 주석: `# 수익현황/수익상세 WS push 일별 요약 범위 (최근 N거래일, 0=전체)`

2. `backend/app/services/trade_history.py`
   - 라인 189 (`_broadcast_sell_append`): `summary = await get_daily_summary(days=20, trade_mode=trade_mode)` → `days=int(engine_state.state.integrated_system_settings_cache.get("daily_summary_days", 20))`
   - 라인 210 (`_broadcast_full_sell_history`): 동일 수정
   - 라인 184 주석: `"""매도 체결 후 단건 + 해당 일자 요약을 브로드캐스트."""` → `"""매도 체결 후 단건 + 최근 N거래일 요약을 브로드캐스트."""` (P23 주석-코드 일치)
   - 라인 204 주석: `"""초기 스냅샷용: 해당 trade_mode의 전체 매도 내역 + 일별 요약을 브로드캐스트."""` → `일별 요약` → `최근 N거래일 요약`
   - import: `from backend.app.services import engine_state` 추가 (이미 있으면 생략)

3. `backend/app/services/engine_snapshot.py`
   - 라인 136 (`_get_daily_summary_for_snapshot`): `return await trade_history.get_daily_summary(days=20, trade_mode=get_trade_mode())` → `days=int(engine_state.state.integrated_system_settings_cache.get("daily_summary_days", 20))`
   - 라인 132 주석: `"""initial-snapshot용 20거래일 일별 요약 반환."""` → `"""initial-snapshot용 N거래일(사용자 설정) 일별 요약 반환."""`
   - import: `from backend.app.services import engine_state` 추가 (이미 있으면 생략)

4. `backend/app/core/settings_store.py`
   - `_validate_numeric_fields()`에 `daily_summary_days` 범위 검증 추가 (1~365, 0=전체 허용)
   - 기존 수치 필드 검증 패턴 준용

**검증**:
- py_compile ✅ + ruff ✅ + mypy (신규 에러 없음) ✅
- 런타임 기동: `daily_summary_days` 설정 로드 확인 (캐시에 20 저장)
- WS push 3곳에서 캐시 참조 확인 (로그: `days=20` → `days=N`)
- 테스트: `test_trade_history.py` + `test_engine_snapshot.py` 수정 후 통과
- 잔존 프로세스 0건

---

### 4세션: 프론트엔드 — hotStore 정리 + 수익현황 localDailySummary + 설정 전파

**목표**: 공유 store `profitDateFrom`/`profitDateTo` 제거. 수익현황 페이지 로컬 상태 도입. days 기반 버튼 N값 백엔드 전파.

**수정 파일 (5파일)**:
1. `frontend/src/stores/hotStore.ts`
   - `HotState` 인터페이스에서 `profitDateFrom: string` / `profitDateTo: string` 제거 (라인 34-48)
   - `initialState`에서 `profitDateFrom: ''` / `profitDateTo: ''` 제거 (라인 50-62)
   - `dailySummary` 필드 주석 추가: `/** WS push 전용 (최근 N거래일) — HTTP 덮어쓰기 금지 (P10 SSOT) */`
   - `applyInitialSnapshotHot`·`applyDailySummaryUpdate`는 변경 없음 (이미 WS push만 반영)

2. `frontend/src/pages/profit-overview.ts`
   - `ProfitOverviewState`에 추가:
     - `localDailySummary: Record<string, unknown>[]`
     - `localDateFrom: string`
     - `localDateTo: string`
   - 초기값: `localDailySummary: []`, `localDateFrom: ''`, `localDateTo: ''`

3. `frontend/src/pages/profit-overview-mount.ts`
   - `applyDateRange` (라인 199-232):
     - `hotStore.setState({ profitDateFrom, profitDateTo, dailySummary: data })` 제거
     - → `state.localDailySummary = data; state.localDateFrom = actualFrom; state.localDateTo = actualTo`
     - `state.chart?.updateData(buildChartFromDailySummary(data))` 유지 (data는 HTTP 결과)
     - `saveProfitDateRange(actualFrom, actualTo, label)` 유지
     - `refreshFilteredViews(state)` 유지
     - **days 기반 버튼 시 N값 전파 추가**: `if (days !== undefined) { await state.settingsMgr?.saveSection({ daily_summary_days: days }) }`
   - `refreshFilteredViews` (라인 55-60):
     - `const { profitDateFrom, profitDateTo } = hotStore.getState()` 제거
     - → `const { localDateFrom, localDateTo } = state`
     - `filterTradeRows(state.sellHistory, localDateFrom, localDateTo)` 사용
   - 기간 버튼 핸들러 (라인 245-251): 변경 없음 (config 유지, `applyDateRange` 호출 시 days 전달)
   - **WS push 동기화**: `subscribeProfitOverviewStore`(또는 기존 구독 리스너)에서 `hotStore.dailySummary` 변경 시 `state.localDailySummary = hotStore.getState().dailySummary` 동기화 + 차트 갱신. 단, 사용자가 기간 버튼 선택 중이면 `localDateFrom/To`로 필터링은 유지.

4. `frontend/src/pages/profit-overview-date.ts`
   - `initDateRange` (라인 55, 58): `hotStore.setState({ profitDateFrom, profitDateTo })` 제거
   - → 페이지 로컬 상태 `state.localDateFrom/localDateTo`에 저장
   - `saveProfitDateRange` localStorage 저장은 유지

5. `frontend/src/settings.ts` (또는 수익현황 설정 진입점)
   - `daily_summary_days` 설정 추가 — 기존 `saveSection` 패턴 준용
   - `AppSettings` 타입에 `daily_summary_days: number` 추가 (`frontend/src/types/index.ts`)
   - 수익현황 days 기반 버튼 클릭 시 `settingsMgr.saveSection({ daily_summary_days: N })` 호출 (이미 3번에서 처리)

**검증**:
- `npm run type-check` ✅ + `npm run lint` ✅
- `npm run build` ✅
- 브라우저: 수익현황 기간 버튼 클릭 시 차트 갱신. 페이지 전환 후 복귀 시 깜빡임 없음. `hotStore.profitDateFrom/To` 참조 잔존 0건 (grep 확인)

---

### 5세션: 프론트엔드 — 수익상세 ensureMonthlyDailySummary 제거 + updateSummaryCards dailySummary 기반 + 용어 통일

**목표**: 수익상세 HTTP 덮어쓰기 제거. 요약 카드 sellHistory 재집계 → dailySummary 기반. "일"→"거래일" 통일. 당월 드릴다운 N 초과 안내.

**수정 파일 (3파일)**:
1. `frontend/src/pages/profit-detail-mount.ts`
   - `ensureMonthlyDailySummary` (라인 267-282) 제거 전체
   - 주석(라인 267-270)도 함께 제거 (Code Removal Rules 준수)
   - `restoreInitialView` (라인 237-265): 변경 없음 (이미 `hotStore.dailySummary` 참조)
   - mount 시 `ensureMonthlyDailySummary` 호출부 제거 (grep 확인)
   - `subscribeProfitDetailStore` (라인 324-357): 변경 없음 (이미 WS push만 반영)

2. `frontend/src/pages/profit-shared.ts`
   - `updateSummaryCards` (라인 132-175):
     - 당월 카드: `aggregatePnl(sellHistory, yearMonth + '-01', yearMonth + '-31')` → `dailySummary`에서 당월 prefix 필터링 후 `realized_pnl` 합계. `pnl_rate`는 기존 `aggregatePnl` 로직 준용하여 dailySummary 기반 재구현.
     - 누적 카드: `aggregatePnl(sellHistory)` → `dailySummary` 전체 `realized_pnl` 합계.
     - 당일/직전 카드: 기존과 동일 (`dailySummary`에서 find)
     - 누적 카드 라벨: "최근 N거래일 누적" 동적 표시 (N값은 설정에서 조회). "전체" 모드(days=0) 시 "전체 누적".
   - `buildMonthlyDrilldown` (라인 315-333):
     - N거래일 초과 시 안내 데이터 추가 — 반환 타입에 `truncated: boolean` 필드 추가 (당월 날짜 수 > dailySummary 당월 날짜 수인 경우)
     - 주석 "일별 요약" → "거래일별 요약" (P23)
   - 라인 145 주석: "직전 거래일" 유지 (이미 "거래일" 표기)
   - 라인 315 주석: "당월 일별 요약" → "당월 거래일별 요약"

3. `frontend/src/pages/profit-detail-display.ts`
   - `showDrilldown` (라인 83-109):
     - `buildMonthlyDrilldown` 반환 값의 `truncated`가 true면 "최근 N거래일만 표시됨" 안내 문구 렌더링 (드릴다운 상단)
     - N값은 설정에서 조회하여 문구에 표시 ("최근 20거래일만 표시됨")
   - 라인 119 (profit-detail-mount.ts): `label: '당월 일별 요약'` → `label: '당월 거래일별 요약'`

**용어 통일 추가 위치** (grep "일" 결과):
- `profit-overview-mount.ts:74`: `chartTitleText.textContent = '일별 수익률'` → `'거래일별 수익률'`
- `profit-overview-mount.ts:68, 207, 234`: 주석 "일별" → "거래일별"
- `profit-overview.ts:3, 140`: 주석 "일별 수익률" → "거래일별 수익률"
- `profit-shared.ts:335`: 주석 "일별 요약" → "거래일별 요약"

**검증**:
- `npm run type-check` ✅ + `npm run lint` ✅
- `npm run build` ✅
- 브라우저: 수익상세 진입 시 당일/직전/당월/누적 카드 정상. 드릴다운 당월 표시. N 초과 시 안내 문구. "거래일" 표기 확인. `ensureMonthlyDailySummary` 잔존 0건 (grep 확인)

---

### 6세션: 테스트 + 런타임 검증

**목표**: 백엔드 테스트 수정 + 전체 런타임 기동 검증 + UI 최종 확인.

**수정 파일 (2파일)**:
1. `backend/tests/test_trade_history.py`
   - `days=20` 하드코딩 관련 테스트 → `days=N` 설정 기반으로 수정
   - `_broadcast_sell_append`/`_broadcast_full_sell_history` 테스트에서 캐시 mock 설정 후 `days=N` 검증

2. `backend/tests/test_engine_snapshot.py`
   - `_get_daily_summary_for_snapshot` 테스트 → N 설정 기반 수정
   - 캐시 mock 설정 후 `days=N` 검증

**검증**:
- 백엔드: `pytest test_trade_history.py test_engine_snapshot.py -v --timeout=15` 통과
- 런타임 기동: `.venv/bin/python main.py` 정상 기동. `daily_summary_days` 설정 로드. WS push 3곳 `days=N` 확인.
- 프론트엔드: `npm run build` ✅. 브라우저에서 수익현황 기간 버튼 → 차트 갱신 → 수익상세 이동 → 당일/직전/당월/누적 카드 정상 → 드릴다운 → 안내 문구 → "거래일" 표기.
- 페이지 전환 반복: 깜빡임/0원 현상 없음 (FIX-WS-03 증상 해결 확인).
- 잔존 프로세스 0건

**완료 시**:
- 계획서 파일 삭제 (규칙 11): `docs/architecture_profit_pages_daily_summary_design.md` + `docs/plan_profit_pages_daily_summary.md`
- HANDOVER.md 참조 경로 정리 (P10 SSOT)

---

## 2. 사용자 결정 항목 (설계서에서 이관)

| # | 항목 | 결정 | 출처 |
|---|---|---|---|
| A | N 설정 변경 위치 | 기존 수익현황 기간 선택 UI 활용. 새 설정 항목 만들지 않음. days 기반 버튼(당일/5일/전체)이 N 결정. | 설계 2-2 결정 A |
| B | WS push 범위 연동 | WS push 3곳 모두 N 연동. 공유 store 의미 "최근 N거래일" 고정. | 설계 2-2 결정 B |
| C | 당월 드릴다운 예외 | N 초과 시 "최근 N거래일만 표시됨" 안내. HTTP 예외 조회 안 함. "일"→"거래일" 통일. | 설계 2-2 결정 C |

---

## 3. 테스트 계획

### 3.1 백엔드 단위 테스트
- `test_trade_history.py`: `_broadcast_sell_append`/`_broadcast_full_sell_history`가 캐시의 `daily_summary_days` 값으로 `get_daily_summary(days=N)` 호출하는지 검증
- `test_engine_snapshot.py`: `_get_daily_summary_for_snapshot`이 캐시의 `daily_summary_days` 값으로 호출하는지 검증
- `settings_store.py`: `daily_summary_days` 범위 검증 (0~365, 음수/문자열 거부)

### 3.2 런타임 기동 검증
- 앱 기동 → `integrated_system_settings_cache`에 `daily_summary_days: 20` 로드 확인
- WS 연결 → `initial-snapshot`의 `daily_summary`가 20거래일인지 확인
- 설정 변경 (`PATCH /api/settings/daily_summary_days` 값 5) → 캐시 갱신 → 다음 WS push가 5거래일인지 확인

### 3.3 프론트엔드 빌드 + 브라우저 검증
- `npm run build` 성공
- 수익현황: 기간 버튼(당일/직전/5일/당월/전체) 클릭 시 차트 갱신
- 수익현황 → 수익상세 이동 → 당일/직전/당월/누적 카드 정상 표시 (0원 깜빡임 없음)
- 수익상세 드릴다운: 당월 거래일별 표시. N 초과 시 안내 문구.
- 페이지 전환 반복: 깜빡임/0원 현상 없음
- "거래일" 표기 확인 (차트 제목, 드릴다운 라벨, 안내 문구)

---

## 4. 런타임 검증 방법

### 4.1 백엔드
```bash
.venv/bin/python -W error::RuntimeWarning main.py
```
- 기동 로그: `daily_summary_days` 설정 로드 확인
- WS push 로그: `days=N` 값 확인
- RuntimeWarning 없음

### 4.2 프론트엔드
- `npm run build` 성공
- 브라우저에서 수익현황/수익상세 페이지 조작
- 개발자 도구 콘솔: 에러 없음
- `hotStore.profitDateFrom`/`profitDateTo` 참조 잔존 0건 (grep)

---

## 5. 위험 및 대응

| 위험 | 대응 |
|---|---|
| WS push 지연 시 수익현황 차트 빈 데이터 | 초기 마운트 시 `hotStore.dailySummary`가 빈 경우 HTTP 1회 조회로 `localDailySummary` 채움 (기존 `applyDateRange` 초기 호출 유지) |
| N값 전파 지연 (설정 변경 → WS push 갱신) | 기존 `trade_mode` 변경 전파와 동일 패턴. 지연 중 이전 N 기준 표시 후 자동 갱신. |
| `updateSummaryCards` dailySummary 기반 집계 시 pnl_rate 계산 | 기존 `aggregatePnl` 로직 준용하여 dailySummary 기반 재구현. per-day rate 재계산 금지 (P10 — 백엔드 값 직접 사용). |
| 당월 카드 N 초과 시 당월 초반 누락 | 안내 문구로 보완 (P21). HTTP 예외 조회 안 함 (결정 C). |
