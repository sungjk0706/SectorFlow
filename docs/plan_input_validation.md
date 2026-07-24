# 태스크 파일: 프론트엔드 설정 입력란 검증·복원

> **상태**: 태스크 파일 작성 완료 (사용자 승인 대기)
> **작성일**: 2026-07-24
> **설계서**: `docs/architecture_input_validation_design.md`
> **원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패)
> **규칙**: 세션당 1단계 (규칙 0-1). 각 세션 완료 후 검증 + 커밋 + HANDOVER 갱신.

---

## 사전조사 결과 (규칙 0-2 4항목) — 2세션 심층 조사 완료

### 설계서와 실제 코드의 차이점 (설계서 수정 반영)

| # | 항목 | 설계서 | 실제 코드 | 반영 |
|---|---|---|---|---|
| 1 | 일일 수익률 한도 max 확장 | "백엔드 수정 없음" | 백엔드 `_RISK_FLOAT_KEYS["daily_profit_rate_limit"]: (0.0, 100.0)` 검증 존재 (`settings_store.py:227`) | **백엔드도 `(0.0, 1000.0)`로 수정** |
| 2 | 일일 수익 한도(원) 상한 | "상한 없이 음수만 막기" | 백엔드 `daily_profit_limit: (0, 1_000_000_000)` 10억 상한 (`settings_store.py:222`) | **사용자 결정: 백엔드 10억 유지 → 프론트도 max:10억** |
| 3 | createMoneyInput clamp | 미언급 | input 이벤트에서 clamp 없음 (spin 버튼에서만 min/max). createNumInput은 input 이벤트에서 실시간 clamp | **createMoneyInput에도 input 이벤트 clamp 추가** (P23 일관성) |
| 4 | 허용 범위 안내 라벨 위치 | labelSubText(라벨 하단) 재사용 | 기존 labelSubText 4곳(수수료 포함 2곳, 초 5초 단위 2곳) 라벨 하단 사용 중 | **사용자 결정: 입력란 좌측 통일** — 기존 labelSubText도 입력란 좌측으로 이동 |

### 백엔드 검증 현황 (settings_store.py:294-350)

이미 백엔드에서 검증하는 필드:
- `daily_loss_limit`: -10억~0
- `daily_profit_limit`: 0~10억
- `consecutive_loss_limit`: 1~100
- `daily_loss_rate_limit`: -100~0
- `daily_profit_rate_limit`: 0~100 → **0~1000로 수정 필요 (1세션)**
- `boost_news_score`: 0~100
- `news_boost_ttl_sec`: 0~3600
- `subscribe.max_0b_count`: 1~1000
- 타임테이블 순서 (realtime_reset <= ws_prestart <= krx_pre_subscribe < 09:00)

백엔드에서 검증 **없는** 필드 (프론트 검증만 추가):
- buy_block_rise_pct, buy_block_fall_pct, max_daily_total_buy_amt, max_stock_cnt, buy_amt
- boost_high_breakout_score, boost_program_net_buy_score, boost_order_ratio_score
- tp_val, loss_val, ts_start_val, ts_drop_val
- buy_interval_sec, sell_interval_sec
- sector_min_trade_amt, sector_start_threshold_pct, sector_min_rise_ratio_pct, sector_max_targets
- buy_time_start/end, sell_time_start/end (순서 검증 없음)

### 공통 컴포넌트 시그니처 (수정 영향)

- `createNumInput` (`setting-row-inputs.ts:12-20`): `min?`(기본 0), `max?`(기본 Infinity) 이미 지원. input 이벤트 실시간 clamp 있음 (line 46).
- `createMoneyInput` (`setting-row-inputs.ts:82-90`): `min?`/`max?` 있지만 **input 이벤트 clamp 없음** (line 122). → 1세션에서 clamp 추가.
- `createToggleLabelControlsRow` (`setting-row-controls.ts:142-195`): `labelSubText?` 라벨 하단 (line 178-183). controls 영역 `display:flex;gap:6px;` (line 157). → 2세션에서 rangeText 파라미터 추가 (입력란 좌측).
- `createSettingRow` (`setting-row.ts:112-136`): labelSubText 없음. → 2세션에서 rangeText 옵션 추가.
- `createTimePairInput` (`time-pair-input.ts:11-65`): onTimeChange 콜백만. 순서 검증 없음. → 3세션에서 검증 추가.
- `AutoSaveHelper` (`settings-save.ts:27-35`): autoSave 디바운스 400ms. 복원 로직 없음. → 4세션에서 복원 추가.

### 저장 방식 두 가지 혼재 (4세션 복원 로직에 영향)

- **buy/sell/sector-settings**: `AutoSaveHelper.autoSave()` — 복원 로직 아예 없음.
- **general-settings 탭들**: 직접 `saveSection()` — `if (res.ok) state.vals.X = v` (vals는 성공 시만 갱신)하지만 `input.setValue(원래값)` 복원 없음 → 화면에 잘못된 값 남음.

---

## 단계 분할 (세션당 1단계)

### 1세션: 수정안 1 — min/max 추가 + 수익률 한도 1000 확장 + createMoneyInput clamp

**목표**: 18개 입력란에 min/max 추가. 일일 수익률 한도 max:1000 확장(프론트+백엔드). createMoneyInput input 이벤트 clamp 추가.

**사전조사 4항목**:
1. 의존성: createNumInput/createMoneyInput 시그니처 변경 없음(min/max 파라미터 이미 존재). createMoneyInput input 이벤트 핸들러 수정. 백엔드 `_RISK_FLOAT_KEYS` 1줄 수정.
2. 영향범위: 프론트엔드 4개 파일 + 백엔드 1개 파일 + 공통 컴포넌트 1개 파일.
3. 원칙: P23(일관성 — 같은 단위 같은 검증), P20(폴백 금지 — 음수 자동 교정 아닌 입력 차단), P22(데이터 정합성 — 프론트/백엔드 검증 일치).
4. 공통 자산: createNumInput/createMoneyInput의 기존 min/max 파라미터 재사용. 신규 검증 프레임워크 도입 없음.

**수정 파일**:
- `frontend/src/components/common/setting-row-inputs.ts` — createMoneyInput input 이벤트에 clamp 추가 (createNumInput line 46 패턴 동일 적용)
- `frontend/src/pages/buy-settings.ts` — 9개 입력란 min/max 추가
- `frontend/src/pages/sell-settings.ts` — 4개 입력란 min/max 추가
- `frontend/src/pages/sector-settings.ts` — 4개 입력란 min/max 추가
- `frontend/src/pages/general-settings-auto-trade-tab.ts` — 1개 입력란 min 추가(일일 수익 한도 min:0 max:10억), 1개 입력란 max 확장(일일 수익률 한도 max:1000)
- `backend/app/core/settings_store.py` — `_RISK_FLOAT_KEYS["daily_profit_rate_limit"]: (0.0, 1000.0)` 수정

**min/max 값 (단위별 분류 — 설계서 결정 1)**:

| 단위 | min | max | 적용 입력란 |
|---|---|---|---|
| 비율 (%) | 0 | 100 | 종목 상승률/하락률 매수차단, 익절, 손절, 고점 추적 시작, 추적 하락률, 업종순위 임계치, 업종내 상승비율 |
| 금액 (원) | 0 | 10억 | 전체 일일 최대 매수 금액, 종목당 일일 최대 매수 금액, 5일평균 최소 거래대금, 일일 수익 한도 |
| 개수 (개) | 0 | 100 | 최대 동시 보유 종목 수, 최대 매수 대상 업종수 |
| 가산점 점수 | 0 | 100 | 5일 고가 돌파, 뉴스 호재, 프로그램 순매수, 매수/매도호가 잔량비율 가산점 |

**예외**:
- 일일 수익률 한도 (%): min:0, max:1000 (사용자 결정 — 200% 이상 수익 허용)

**검증**:
- 프론트: typecheck + build
- 백엔드: `python -W error::RuntimeWarning main.py` 기동 + 설정 저장 테스트 (수익률 한도 150 저장 → 성공, 1001 저장 → 실패)
- 브라우저: 음수 입력 시 자동 보정 확인, 100 초과 비율 입력 시 보정 확인

**원칙 부합**: P10(검증 값 단일 지정)/P20(음수 자동 교정 아닌 clamp)/P22(프론트/백엔드 일치)/P23(같은 단위 같은 검증)/P24(기존 파라미터 재사용)

---

### 2세션: 수정안 2 — 허용 범위 안내 라벨 (입력란 좌측 통일)

**목표**: 모든 숫자 입력란에 허용 범위 안내를 **입력란 좌측**에 작은 텍스트로 표시. 기존 labelSubText(라벨 하단) 4곳도 입력란 좌측으로 이동. P23 일관성 — 단일 위치 통일.

**사전조사 4항목**:
1. 의존성: createToggleLabelControlsRow 시그니처 변경(labelSubText → rangeText). createSettingRow 시그니처 변경(rangeText 옵션 추가). 기존 labelSubText 사용처 4곳 이동.
2. 영향범위: 공통 컴포넌트 2개 파일 + 모든 설정 페이지(기존 labelSubText 사용처 + 신규 범위 안내 추가).
3. 원칙: P23(일관성 — 단일 안내 위치), P21(투명성 — 입력 전 범위 인지), P24(단순성 — 신규 컴포넌트 없음, 기존 패턴 변형).
4. 공통 자산: createToggleLabelControlsRow의 controls 영역(flex) 재사용. createSettingRow 재사용. 신규 컴포넌트 생성 금지.

**수정 파일**:
- `frontend/src/components/common/setting-row-controls.ts` — createToggleLabelControlsRow에 `rangeText?` 파라미터 추가. controls 영역에 `[rangeText span][controlsChild]` 순서 배치. labelSubText 파라미터 제거(사용 중단) — 기존 사용처 rangeText로 이동.
- `frontend/src/components/common/setting-row.ts` — createSettingRow에 `rangeText?` 옵션 추가. child 앞에 rangeText span 배치.
- `frontend/src/pages/buy-settings.ts` — 9개 입력란 rangeText 추가 + 기존 labelSubText 3곳(수수료 포함 2곳, 초 5초 단위 1곳) rangeText로 이동/병합
- `frontend/src/pages/sell-settings.ts` — 4개 입력란 rangeText 추가 + 기존 labelSubText 1곳(초 5초 단위 손절 포함) rangeText로 이동/병합
- `frontend/src/pages/sector-settings.ts` — 4개 입력란 rangeText 추가 (createSettingRow 사용)
- `frontend/src/pages/general-settings-auto-trade-tab.ts` — 검증 있는 입력란 5개 + 신규 2개 rangeText 추가
- `frontend/src/pages/general-settings-news-settings-tab.ts` — 뉴스 가산점 유지 시간 rangeText 추가

**rangeText 표시 포맷 (단위별)**:

| 단위 | 포맷 | 예시 |
|---|---|---|
| 비율 (%) | `0~100%` | 종목 상승률 매수차단: `0~100%` |
| 금액 (원) | `0~10억원` | 전체 일일 최대 매수 금액: `0~10억원` |
| 개수 (개) | `0~100개` | 최대 동시 보유 종목 수: `0~100개` |
| 가산점 점수 | `0~100점` | 5일 고가 돌파 가산점: `0~100점` |

**예외 rangeText**:
- 일일 수익률 한도: `0~1000%`
- 업종 가산점 슬라이더 3개: `-100%~+100%` (이미 검증 있음, 안내만 추가)
- 매수/매도 주문 간격: `5~300초` (기존 `(초, 5초 단위)` 병합 → `5~300초, 5초 단위`)

**기존 labelSubText 병합 (입력란 좌측으로 이동)**:
- 전체 일일 최대 매수 금액: `(수수료 포함)` → rangeText: `0~10억원, 수수료 포함`
- 종목당 일일 최대 매수 금액: `(수수료 포함)` → rangeText: `0~10억원, 수수료 포함`
- 매수 주문 간격: `(초, 5초 단위)` → rangeText: `5~300초, 5초 단위`
- 매도 주문 간격: `(초, 5초 단위, 손절 포함)` → rangeText: `5~300초, 5초 단위, 손절 포함`

**레이아웃**: `[라벨 + 토글] ... [rangeText span] [입력란]` (rangeText는 controls 영역 내 입력란 좌측, 작은 회색 폰트)

**공간 부족 시 처리 (사용자 결정)**:
- 입력란 좌측에 rangeText를 추가했을 때 행 너비가 초과하여 레이아웃이 깨지는 경우, **해당 입력란은 rangeText를 생략**.
- 다른 입력란은 정상적으로 rangeText 적용. 일관성이 부분 저하되지만 기능(min/max 검증)에는 영향 없음.
- 판단 기준: 2세션 구현 시 브라우저에서 각 입력란별로 rangeText 추가 후 레이아웃 확인. 깨지는 입력란만 rangeText 제거.
- 생략된 입력란은 2세션 보고서에 명시하여 사용자가 어떤 입력란에 안내가 없는지 인지 (P21 투명성).

**검증**:
- 프론트: typecheck + build
- 브라우저: 모든 숫자 입력란 좌측에 허용 범위 표시 확인. 기존 (수수료 포함) 등이 라벨 하단에서 입력란 좌측으로 이동 확인. 공간 부족으로 생략된 입력란이 있는지 확인.

**원칙 부합**: P21(입력 전 범위 인지, 생략 시 보고)/P23(단일 안내 위치 통일)/P24(신규 컴포넌트 없음, 기존 패턴 변형)

---

### 3세션: 수정안 3 — 시간쌍 순서 검증

**목표**: 자동매수/매도 시간쌍에서 시작 ≥ 종료 시 저장 막고 안내 메시지 표시. 입력란 값은 사용자 입력대로 두고 저장만 차단 (P20 폴백 금지 — 자동 교정 안 함).

**사전조사 4항목**:
1. 의존성: createTimePairInput 시그니처 변경(onTimeChange 호출 전 검증) 또는 호출처(general-settings-time-settings-tab.ts)에서 검증. 백엔드 buy_time/sell_time 순서 검증 없음 — 프론트만.
2. 영향범위: time-pair-input.ts 1개 파일(또는 time-settings-tab.ts 2곳) + 안내 메시지 표시 방식.
3. 원칙: P20(자동 교정/스왑 금지), P21(안내 메시지로 사유 표시), P16(검증이 실제 입력 이벤트 경로에 연결).
4. 공통 자산: toast 컴포넌트(`toastResult`) 재사용 가능. 또는 별도 안내 엘리먼트.

**수정 파일**:
- `frontend/src/components/common/time-pair-input.ts` — onTimeChange 호출 전 순서 검증 추가. 시작 ≥ 종료 시 콜백 호출하지 않고 안내 표시.
- `frontend/src/pages/general-settings-time-settings-tab.ts` — 자동매수/매도 시간쌍 2곳에 안내 메시지 표시 영역 추가 (또는 toast 사용)

**검증 로직**:
```
시작 시간(분) >= 종료 시간(분) → 저장 막음, 안내 메시지
안내: "시작 시간이 종료 시간보다 빨라야 합니다"
```

**검증**:
- 프론트: typecheck + build
- 브라우저: 자동매수 시간 시작 15:00, 종료 09:00 설정 시 저장 안 됨 + 안내 메시지 확인. 정상 순서(09:00~15:00) 시 저장 확인.

**원칙 부합**: P16(검증이 입력 경로에 연결)/P20(자동 교정 금지)/P21(안내로 사유 표시)

---

### 4세션: 수정안 4 — 저장 실패 시 입력값 복원

**목표**: 숫자 입력란·시간쌍에 저장 실패 시 원래 값으로 복원 로직 추가. 토글·라디오에 있는 복원 패턴 재사용. 두 가지 저장 방식(AutoSaveHelper / 직접 saveSection) 모두에 적용.

**사전조사 4항목**:
1. 의존성: AutoSaveHelper에 복원 콜백 지원 추가(또는 각 입력란 onChange를 직접 saveSection으로 변경). general-settings 탭들의 `if (res.ok)` 패턴에 `input.setValue(원래값)` 복원 추가.
2. 영향범위: settings-save.ts + buy-settings.ts + sell-settings.ts + sector-settings.ts + general-settings 탭들.
3. 원칙: P22(데이터 정합성 — 프론트 값과 백엔드 값 불일치 방지), P23(토글 복원 패턴 재사용), P21(저장 실패 시 사용자가 화면에서 잘못된 값 안 봄).
4. 공통 자산: 토글 복원 패턴(`if (!res.ok) { state.vals.X = 원래값; toggle.setOn(원래값) }`) 재사용.

**수정 파일**:
- `frontend/src/utils/settings-save.ts` — AutoSaveHelper.autoSave에 복원 콜백 지원 추가 (onSaveFail 콜백) 또는 autoSave 반환값을 Promise로 변경하여 실패 감지.
- `frontend/src/pages/buy-settings.ts` — 9개 숫자 입력란 onChange에 복원 로직 추가
- `frontend/src/pages/sell-settings.ts` — 4개 숫자 입력란 onChange에 복원 로직 추가
- `frontend/src/pages/sector-settings.ts` — 4개 숫자 입력란 onChange에 복원 로직 추가
- `frontend/src/pages/general-settings-auto-trade-tab.ts` — 기존 `if (res.ok)` 패턴에 `input.setValue(원래값)` 복원 추가
- `frontend/src/pages/general-settings-news-settings-tab.ts` — 뉴스 가산점 유지 시간 복원 추가
- `frontend/src/pages/general-settings-time-settings-tab.ts` — 시간쌍 저장 실패 시 복원 추가

**복원 패턴 (토글 패턴 재사용)**:
```
// AutoSaveHelper 사용처 (buy/sell/sector)
const 원래값 = vals[key]
vals[key] = 새값
const res = await saveSection({ [key]: 새값 })
toastResult(res)
if (!res.ok) { vals[key] = 원래값; input.setValue(원래값) }

// 직접 saveSection 사용처 (general-settings)
const 원래값 = state.vals[key]
state.vals[key] = 새값
const res = await state.settingsMgr.saveSection({ [key]: 새값 })
toastResult(res)
if (!res.ok) { state.vals[key] = 원래값; input.setValue(원래값) }
```

**검증**:
- 프론트: typecheck + build
- 브라우저: 백엔드 저장 실패 유도(예: 일일 수익 한도 10억 초과) 시 입력란이 원래 값으로 복원되는지 확인.

**원칙 부합**: P22(프론트/백엔드 값 일치)/P23(토글 복원 패턴 재사용)/P21(잘못된 값 화면 잔류 방지)

---

## 진행 순서

1세션(min/max) → 2세션(안내 라벨) → 3세션(시간쌍 순서) → 4세션(복원)

**순서 근거**:
- 1세션이 먼저 — 범위가 정해져야 2세션 안내 라벨에 표시할 범위 결정.
- 2세션은 1세션 이후 — min/max 값 기반으로 rangeText 생성.
- 3세션은 독립적 — 시간쌍만 다룸.
- 4세션이 마지막 — 모든 입력란에 복원 로직 적용, 앞선 수정 완료 후 일괄 적용.

---

## 리스크/롤백 기준

- **리스크 낮음**: 입력란 검증 추가는 기존 정상 값의 범위를 제한. 기존에 음수·범위 초과 값을 사용 중이었다면 해당 값이 입력란에 표시될 때 clamp 보정됨.
- **롤백 기준**: 검증 추가 후 기존 정상 값(0~100, 0~10억)이 입력되지 않는 경우. 즉시 롤백.
- **거래 로직 영향 없음**: 본 작업은 프론트엔드 입력란 검증 + 백엔드 검증 상한 1개 확장만. 매매 로직 변경 없음. safe-trade 스킬 미적용.
- **백엔드 수정**: 1세션에서 `_RISK_FLOAT_KEYS["daily_profit_rate_limit"]` 상한 100→1000만. 거래 로직 아님. backend-fix 스킬 적용.

---

## 완료 후 처리

- 태스크 파일(`docs/plan_input_validation.md`) 삭제 (규칙 10 — 계획서/설계 문서는 완료 후 삭제)
- 설계서(`docs/architecture_input_validation_design.md`) 삭제 (규칙 10)
- HANDOVER.md에 완료 세션 기록
