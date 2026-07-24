# 수익현황/수익상세 페이지 — dailySummary 공유 store 의미 충돌 근본 개선 설계

> **다단계 작업 1세션 산출물 (설계 파일)**
> 규칙 준수: AGENTS.md 섹션4 "다단계 작업 워크플로우" 1세션 — 설계 검토 + 디자인 파일 작성.
> 완료 후 2세션(태스크 파일) → 3세션(구현) 순서로 진행. 모든 단계 완료 시 본 파일 삭제 (규칙 11).

---

## 1. 문제 정의

### 1-1. 현재 구조의 근본 문제

`hotStore.dailySummary`는 단일 슬롯이지만, **3개 주체가 각자 자신의 컨텍스트에 맞는 범위로 덮어쓰고 있어 슬롯의 의미 범위가 시점에 따라 변함**.

| 주체 | 덮어쓰기 시점 | dailySummary가 갖는 의미 |
|---|---|---|
| 수익현황 HTTP (`applyDateRange`) | mount 시 + 사용자가 기간 버튼 클릭할 때마다 | 사용자가 선택한 범위 (당일 1건 / 5일 / 당월 / 전체) |
| 수익상세 HTTP (`ensureMonthlyDailySummary`) | mount 시 1회 | 당월 전체 |
| 백엔드 WS push (`sell-history-append`, `daily-summary-update`, `initial-snapshot`) | 매도 체결 시 / 초기 연결 시 | **최근 20거래일 (하드코딩 `days=20`)** |

**P10(SSOT) 위반 양상**: 슬롯은 1개이므로 형식적 SSOT는 지켜지나, **의미론적으로는 3개의 서로 다른 진실이 같은 자리를 번갈아 차지**. 현재 `hotStore.dailySummary`가 어느 범위를 대표하는지 외부에서 알 수 없음.

**P21(사용자 투명성) 위반 양상**: 사용자가 수익현황에서 "당일" 클릭 → 수익상세로 이동 → `ensureMonthlyDailySummary`가 당월로 덮어쓰기 → 다시 수익현황 복귀 시 잠깐 당월 데이터가 표시되었다가 `applyDateRange` 재호출로 당일로 돌아오는 깜빡임/불일치 발생.

**P22(데이터 정합성) 위반 양상**: 다른 페이지가 `hotStore.dailySummary`를 읽어 쓸 때, 어느 범위의 데이터인지 알 수 없어 잘못된 범위를 신뢰하게 됨.

### 1-2. 추가 발견: `updateSummaryCards`의 프론트 재집계

`profit-shared.ts`의 `updateSummaryCards`가 당월/누적 손익 카드를 `dailySummary`(백엔드 SSOT)가 아닌 `sellHistory` 기반으로 **프론트에서 재집계**. 같은 "당월 손익"이 드릴다운(dailySummary 직접 사용)과 요약 카드(sellHistory 집계)에서 서로 다를 수 있음. 이것도 같은 SSOT 훼손 패턴.

### 1-3. 추가 발견: 수익현황의 `profitDateFrom`/`profitDateTo` 공유 store 저장

수익현황은 날짜 범위 자체도 `hotStore.setState({ profitDateFrom, profitDateTo, dailySummary })`로 공유 store에 저장. `refreshFilteredViews`가 이 공유 범위를 읽어 도넛 차트/업종별 종목 수익을 필터링. 수익상세의 `filterByDate`(페이지 로컬 `dateRangeInput`에만 저장)와 대조적으로, 수익현황 쪽이 공유 store 오염이 한 단계 더 깊음.

---

## 2. 설계 방향 (사용자 결정 4 + 3항목)

### 2-1. 사용자가 정한 기본 방향 4항목

| # | 방향 | 적용 대상 |
|---|---|---|
| 1 | 프론트는 백엔드가 WS로 push하는 데이터를 "읽기만" 한다. HTTP API로 별도 요청해서 공유 store를 덮어쓰는 것 금지. | 수익현황 + 수익상세 |
| 2 | 각 페이지의 날짜 범위 선택(당일/당월/5일 등)은 페이지 로컬 상태로만 관리. 공유 store에 저장하지 않는다. | 수익현황 + 수익상세 |
| 3 | 백엔드 하드코딩 `days=20`(최근 20거래일)을 사용자 설정으로 변경. 사용자가 변경하면 그 값이 새 기본값이 되어 앱 기동 시 로드. | 백엔드 WS push |
| 4 | 초기값만 기본값(20)으로 제공하고, 사용자 변경 시 그 값으로 갱신. | 백엔드 WS push |

### 2-2. 사용자 결정 항목 (질문·답변 기록 — 2세션 태스크 파일에서 그대로 활용)

#### 결정 A: N(최근 N거래일) 설정 변경 위치

**질문**: 최근 N거래일의 N(현재 20 고정)을 사용자가 변경할 수 있게 할 때, 그 설정을 어느 화면에서 바꾸게 할까요?

**사용자 답변**: "새 설정 항목 만들지 말고 기존 UI 활용. 수익현황/수익상세 페이지에 이미 기간 선택 UI가 있고, 사용자가 마지막 선택한 값을 저장했다가 앱 재기동 시 로드하는 게 기본 아키텍처다."

**설계 반영**:
- 새 설정 슬라이더/입력란을 만들지 않음.
- 기존 수익현황의 기간 선택 버튼(당일/직전/5일/당월/전체)을 그대로 활용.
- days 기반 선택("당일"→1, "5일"→5, "전체"→0)이 N값을 결정.
- "직전", "당월"은 날짜 범위 기반이므로 N을 변경하지 않고 페이지 로컬에서 WS 데이터를 필터링해서 표시.
- 마지막으로 선택한 N값이 localStorage에 저장되어 앱 재기동 시 로드. "직전"/"당월"을 마지막으로 선택한 경우, N은 이전 days 기반 선택값을 유지.
- 기본 N값은 20 (현재 하드코딩값과 동일, 호환성 유지).

#### 결정 B: WS push 범위와 N의 연동

**질문**: 사용자가 N을 변경했을 때, 백엔드가 실시간으로 밀어주는(WebSocket) 데이터 범위도 N에 맞춰 바뀌어야 할까요?

**사용자 답변**: "A다. 당연히 A지. B는 우리가 방금 고치기로 한 '프론트 HTTP 따로 요청 + store 의미 충돌' 문제를 다시 만드는 거다. P10 SSOT 원칙을 떠올려봐. WS가 N을 따라가야 공유 store 의미가 하나로 고정된다."

**설계 반영**:
- 백엔드 WS push의 `days` 파라미터가 사용자 설정 N을 따라감.
- `initial-snapshot`, `sell-history-append`, `daily-summary-update` 세 WS 이벤트 모두 `days=N`으로 통일.
- 공유 store의 `dailySummary`는 항상 "최근 N거래일"이라는 고정된 의미를 가짐. P10 SSOT 달성.
- N 변경 시 백엔드에 알려야 함 (설정 전파 경로 필요 — 아래 4-3절 참조).

#### 결정 C: 당월 드릴다운 예외 처리

**질문**: WS 데이터가 '최근 N거래일'이 되면, 당월이 N보다 길 경우(예: N=10인데 당월은 15거래일) 당월 초반 데이터가 빠지게 됩니다. 이 경우 어떻게 처리할까요?

**사용자 답변**: "A. 그리고 한 가지 추가 — '일'이라는 표기를 모두 '거래일'로 정확히 변경해. 사용자가 설정한 N보다 당월이 길면 '최근 N거래일만 표시됨' 같은 안내 문구를 표시해서 P21을 지켜줘."

**설계 반영**:
- 당월이 N거래일보다 길면, 드릴다운에 표시 가능한 날짜(최근 N거래일에 해당하는 당월 날짜)만 표시.
- 드릴다운 상단에 "최근 N거래일만 표시됨" 안내 문구 표시 (P21 사용자 투명성).
- "일" → "거래일" 용어 통일 (P23 일관성, ARCHITECTURE.md 부록 L 준수).
- HTTP로 당월 전체를 별도 조회하지 않음 (결정 1: HTTP로 공유 store 덮어쓰기 금지 준수).

---

## 3. 설계안 비교표

### 3-1. 공유 store dailySummary의 의미 고정 방식

| 안 | 내용 | P10 | P21 | P22 | 선택 |
|---|---|---|---|---|---|
| A | WS push만 공유 store에 저장, 페이지 조회 결과는 로컬 | 의미 고정 (최근 N거래일) | 페이지 전환 시 잔류 효과 제거 | 범위 명확 | **선택** |
| B | 현재 구조 유지 (3주체 경쟁 덮어쓰기) | 의미 변동 | 깜빡임/불일치 | 범위 불명 | 기각 |
| C | 공유 store 폐지, 각 페이지가 독립 조회 | 의미 모호 | 페이지마다 재조회 | 범위 불명 | 기각 |

### 3-2. N값 설정 방식

| 안 | 내용 | P24 단순성 | 사용자 결정 | 선택 |
|---|---|---|---|---|
| A | 기존 기간 선택 UI 활용 (days 기반 버튼이 N 결정) | 새 UI 없음 | 결정 A | **선택** |
| B | 설정 페이지에 새 슬라이더 추가 | 새 UI 추가 | 기각됨 | 기각 |
| C | 양쪽 모두 (설정 페이지 + 페이지 내) | 동기화 부담 | 기각됨 | 기각 |

### 3-3. WS push 범위 연동

| 안 | 내용 | P10 | P22 | 선택 |
|---|---|---|---|---|
| A | WS도 N을 따라감 | 공유 store 의미 고정 | 범위 일관 | **선택** |
| B | WS 고정, 페이지만 N | 의미 혼재 재발 | 범위 불일치 | 기각 |

### 3-4. 당월 드릴다운 예외

| 안 | 내용 | P20 폴백 | P21 | 선택 |
|---|---|---|---|---|
| A | 빠진 날짜 안내 문구 표시 | 폴백 없음 | 투명성 확보 | **선택** |
| B | 당월 클릭 시 HTTP 예외 조회 | 원칙 예외 발생 | 투명 | 기각 (결정 1 위반) |
| C | N 최소값 보장 (당월 항상 커버) | 사용자 의도 제한 | 투명 | 기각 |

### 3-5. 수익현황 `profitDateFrom`/`profitDateTo` 처리

| 안 | 내용 | P10 | P24 | 선택 |
|---|---|---|---|---|
| A | 공유 store에서 제거, 페이지 로컬로 이동 | 공유 store 의미 단순화 | 수익상세와 패턴 일치 | **선택** |
| B | 공유 store 유지 | 의미 혼재 지속 | 수익상세와 불일치 | 기각 |

---

## 4. 선택안 동작 원리

### 4-1. 공유 store dailySummary — WS 전용, 의미 고정

**변경 전**:
- 3주체(수익현황 HTTP, 수익상세 HTTP, 백엔드 WS)가 `hotStore.dailySummary`를 경쟁 덮어쓰기.
- `hotStore.profitDateFrom`/`profitDateTo`도 수익현황이 덮어쓰기.

**변경 후**:
- `hotStore.dailySummary`는 **백엔드 WS push만**으로 갱신. 프론트의 HTTP 응답으로 덮어쓰기 금지.
- `hotStore.dailySummary`의 의미: **"최근 N거래일"** (N은 사용자 설정, 기본 20).
- `hotStore.profitDateFrom`/`profitDateTo` 제거. 수익현황의 날짜 범위는 페이지 로컬 상태로 이동.

**WS push 경로 (3곳 모두 N 적용)**:
- `initial-snapshot` → `_get_daily_summary_for_snapshot()` → `get_daily_summary(days=N, ...)`
- `sell-history-append` → `_broadcast_sell_append()` → `get_daily_summary(days=N, ...)`
- `daily-summary-update` → `_broadcast_full_sell_history()` → `get_daily_summary(days=N, ...)`

### 4-2. 페이지 로컬 상태 — 날짜 범위 관리

**수익현황**:
- `applyDateRange`가 HTTP로 `getDailySummary`를 조회하는 것은 **유지** (HTTP 조회 자체는 금지 아님 — 결정 1은 "공유 store 덮어쓰기" 금지이지 HTTP 조회 금지가 아님).
- 단, 조회 결과를 `hotStore.setState({ dailySummary: data })`로 덮어쓰는 것을 **제거**.
- 조회 결과는 페이지 로컬 상태(예: `state.localDailySummary`)에 저장.
- 차트/도넛/업종별 종목 수익은 `state.localDailySummary`와 `state.localDateFrom`/`state.localDateTo`(페이지 로컬)를 기반으로 렌더링.
- `hotStore.profitDateFrom`/`profitDateTo` 제거에 따라, `refreshFilteredViews`가 페이지 로컬 범위를 참조하도록 변경.

**수익상세**:
- `ensureMonthlyDailySummary` 제거 (mount 시 HTTP로 당월 조회해서 공유 store 덮어쓰는 행위).
- 드릴다운은 `hotStore.dailySummary`(WS push, 최근 N거래일)에서 당월에 해당하는 날짜만 필터링해서 표시.
- 당월이 N거래일보다 길면 "최근 N거래일만 표시됨" 안내 문구 표시 (P21).
- 요약 카드의 당일/직전은 `hotStore.dailySummary`에서 해당 날짜 find (기존과 동일).
- 요약 카드의 당월/누적은 `hotStore.dailySummary`에서 집계 (현재 sellHistory 재집계에서 변경 — P10/P22 정합성 확보). 단, 누적은 N거래일 범위 내에서만 표시 가능하므로 "최근 N거래일 누적"으로 의미 변경. 또는 "전체" 버튼(days=0) 선택 시에만 전체 누적 표시.

### 4-3. N값 전파 경로

**N값 저장 위치**: 사용자 설정(`globalSettingsManager` 또는 백엔드 `integrated_system_settings_cache`).

**전파 흐름**:
1. 사용자가 수익현황에서 "5일" 버튼 클릭 → N=5.
2. 프론트: N값을 사용자 설정에 저장 (localStorage + 백엔드 설정 API).
3. 백엔드: 설정 수신 → `integrated_system_settings_cache` 갱신.
4. 백엔드 WS push 3곳이 갱신된 N을 참조하여 `get_daily_summary(days=N)` 호출.
5. 프론트: WS push 수신 → `hotStore.dailySummary` 갱신 (최근 5거래일).
6. 수익현황/수익상세 모두 갱신된 `hotStore.dailySummary`를 반영.

**앱 재기동 시**:
1. 백엔드 기동 → `integrated_system_settings_cache`에서 N값 로드 (기본 20).
2. WS 연결 → `initial-snapshot`이 `days=N`으로 dailySummary push.
3. 프론트: localStorage에서 마지막 기간 선택 복원 → 해당 버튼 활성화.

### 4-4. 용어 통일

- "일" → "거래일" (P23, ARCHITECTURE.md 부록 L 준수).
- UI 텍스트: "최근 20일" → "최근 20거래일", "5일" → "5거래일" 등.
- 코드 주석/변수명: `days`는 유지 (파라미터명), 사용자 표시 텍스트만 "거래일"로 통일.
- 안내 문구: "최근 N거래일만 표시됨" (N은 현재 설정값).

---

## 5. 표준 검토 근거 (아키텍처 원칙)

### 5-1. P10 (SSOT) — 핵심 달성

**달성**: `hotStore.dailySummary`가 "최근 N거래일"이라는 고정된 의미를 가짐. 3주체 경쟁 덮어쓰기 제거로 의미 혼재 해소. `updateSummaryCards`의 sellHistory 재집계 제거로 "당월 손익" 단일 소스 통일.

**잔존 검토**: N값 자체는 사용자 설정에 저장되므로 SSOT 유지. 페이지 로컬 dailySummary는 "백엔드 응답의 페이지 한정 캐시"이지 독립 계산 결과가 아니므로 P10 위반 아님.

### 5-2. P21 (사용자 투명성) — 개선

**개선**: 페이지 전환 시 잔류 효과/깜빡임 제거. 당월 드릴다운에서 N거래일 초과 시 안내 문구 표시. 사용자가 "왜 당월 전체가 안 보이지?"라는 의문을 갖지 않도록 안내.

### 5-3. P22 (데이터 정합성) — 개선

**개선**: 공유 store 의미 고정으로 다른 페이지가 안전하게 읽을 수 있음. `updateSummaryCards`의 sellHistory 재집계 제거로 드릴다운과 요약 카드 간 정합성 확보.

### 5-4. P23 (일관성) — 개선

**개선**: 수익현황과 수익상세의 날짜 범위 관리 패턴 통일 (둘 다 페이지 로컬). "일" → "거래일" 용어 통일.

### 5-5. P24 (단순성) — 검토

**개선**: `profitDateFrom`/`profitDateTo` 공유 store 제거로 공유 store 슬롯 감소. 3주체 경쟁 구조 제거로 인지 부담 감소.

**잔존 검토**: N값 전파 경로(프론트→백엔드 설정→WS push)가 추가되므로 복잡도 증가 분 있음. 단, 이는 기존 설정 전파 경로(`trade_mode` 등)와 동일한 패턴이므로 신규 추상화 아님.

### 5-6. P25 (격리된 실패) — 검토

**검토**: 수익현황의 HTTP 조회 실패 시 페이지 로컬 상태만 영향, 공유 store는 건드리지 않으므로 다른 페이지 영향 없음. 수익상세의 WS push 지연 시 `hotStore.dailySummary`가 이전 값 유지 (기존 `applyInitialSnapshotHot`의 빈 배열 보존 로직과 일치).

---

## 6. 영향 범위

### 6-1. 백엔드

| 파일 | 변경 내용 |
|---|---|
| `backend/app/services/trade_history.py` | `_broadcast_sell_append`, `_broadcast_full_sell_history`의 `days=20` 하드코딩을 `days=N`(설정값)으로 변경. `_broadcast_sell_append` 주석 "해당 일자 요약"을 "최근 N거래일 요약"으로 수정 (주석-코드 불일치 해소, P23). |
| `backend/app/services/engine_snapshot.py` | `_get_daily_summary_for_snapshot`의 `days=20`을 `days=N`으로 변경. 주석 "20거래일"을 "N거래일(사용자 설정)"로 수정. |
| `backend/app/services/engine_config.py` (또는 설정 관리 모듈) | `integrated_system_settings_cache`에 `daily_summary_days` 설정 키 추가. 기본값 20. |
| `backend/app/web/routes/settings.py` (또는 설정 API) | `daily_summary_days` 변경 API 추가 (기존 설정 변경 패턴 준용). |

### 6-2. 프론트엔드

| 파일 | 변경 내용 |
|---|---|
| `frontend/src/pages/profit-overview-mount.ts` | `applyDateRange`에서 `hotStore.setState({ dailySummary: data })` 제거. 조회 결과를 `state.localDailySummary`에 저장. `hotStore.setState({ profitDateFrom, profitDateTo })` 제거. `refreshFilteredViews`가 `state.localDateFrom`/`localDateTo` 참조하도록 변경. days 기반 버튼 클릭 시 N값을 설정에 저장. |
| `frontend/src/pages/profit-overview.ts` | `state`에 `localDailySummary`, `localDateFrom`, `localDateTo` 추가. `profitDateFrom`/`profitDateTo` 관련 코드 제거. |
| `frontend/src/pages/profit-detail-mount.ts` | `ensureMonthlyDailySummary` 제거. `restoreInitialView`가 `hotStore.dailySummary`(WS)만 참조하도록 변경. `subscribeProfitDetailStore`는 WS push만 반영 (기존과 동일하나 HTTP 덮어쓰기 제거로 단순화). |
| `frontend/src/pages/profit-shared.ts` | `updateSummaryCards`의 당월/누적 카드를 sellHistory 재집계에서 `dailySummary` 기반 집계로 변경. `buildMonthlyDrilldown`에 N거래일 초과 시 안내 문구 데이터 추가. "일" → "거래일" 표기 변경. |
| `frontend/src/pages/profit-detail-display.ts` | `showDrilldown`에 "최근 N거래일만 표시됨" 안내 문구 렌더링 추가. |
| `frontend/src/stores/hotStore.ts` | `profitDateFrom`/`profitDateTo` 필드 제거. `dailySummary`는 WS push만으로 갱신 (주석 명시). |
| `frontend/src/settings/` (설정 관리) | `daily_summary_days` 설정 추가. 기존 설정 패턴 준용. |
| `frontend/src/binding.ts` | WS 이벤트 핸들러는 변경 없음 (이미 WS push만 `hotStore.dailySummary`에 반영). |

### 6-3. 테스트

| 파일 | 변경 내용 |
|---|---|
| `backend/tests/test_trade_history.py` | `days=20` 하드코딩 관련 테스트를 `days=N` 설정 기반으로 수정. |
| `backend/tests/test_engine_snapshot.py` | `_get_daily_summary_for_snapshot` 테스트를 N 설정 기반으로 수정. |
| 프론트엔드 테스트 (있을 경우) | `profitDateFrom`/`profitDateTo` 제거에 따른 테스트 수정. `localDailySummary` 관련 테스트 추가. |

---

## 7. 해결되는 문제 & 남는 제약

### 7-1. 해결되는 문제

1. **공유 store dailySummary 의미 충돌** — 3주체 경쟁 덮어쓰기 제거. WS 전용으로 의미 "최근 N거래일" 고정.
2. **페이지 전환 시 잔류 효과/깜빡임** — 페이지 로컬 상태 분리로 제거.
3. **`updateSummaryCards` sellHistory 재집계** — dailySummary 기반으로 통일, 드릴다운과 정합성 확보.
4. **`profitDateFrom`/`profitDateTo` 공유 store 오염** — 페이지 로컬로 이동.
5. **`days=20` 하드코딩** — 사용자 설정 N으로 변경.
6. **"일" vs "거래일" 용어 불일치** — "거래일"로 통일 (P23).
7. **`_broadcast_sell_append` 주석-코드 불일치** — 주석을 실제 동작(최근 N거래일)에 맞게 수정 (P23).

### 7-2. 남는 제약 (사용자가 결정 C로 수용)

1. **당월 드릴다운은 N거래일 범위 내에서만 표시** — 당월이 N보다 길면 초반 날짜 생략, 안내 문구로 보완 (P21). HTTP 예외 조회는 하지 않음 (결정 1 준수).
2. **누적 손익 카드는 N거래일 범위 내 누적** — "전체" 버튼(days=0) 선택 시에만 전체 누적 표시. N거래일 모드에서는 "최근 N거래일 누적"으로 의미 변경. UI에 이 의미가 명확히 표시되어야 함 (P21).
3. **N값 전파 지연 가능성** — 사용자가 N을 변경하면 백엔드 설정 갱신 → WS push 범위 변경까지 약간의 지연 발생 가능. 이 동안 화면이 잠깐 이전 N 기준으로 표시될 수 있음. 기존 `trade_mode` 변경 전파와 동일한 패턴이므로 신규 이슈 아님.

### 7-3. 다음 세션(2세션)에서 다룰 항목

- N값 전파 경로의 구체적 구현 방식 (기존 설정 전파 패턴 중 어느 것을 따를지)
- 누적 손익 카드의 "최근 N거래일 누적" 표시 방식 (UI 문구, 계산 범위)
- 수익현황의 `localDailySummary`와 WS push `dailySummary`의 관계 (페이지가 HTTP로 조회한 결과를 로컬에 갖되, WS push가 오면 어떻게 동기화할지)
- 2세션 태스크 파일에서 위 항목을 작업 단위로 분할
