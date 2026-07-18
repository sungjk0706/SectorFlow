# 리스크 매니저 확장 태스크 파일 (2026-07-18)

> **설계서**: `docs/architecture_risk_manager_extension_design.md` (1세션 산출물, 862줄)
> **상태**: 심층 사전조사 완료. 구현 승인 대기.
> **참조 규칙**: AGENTS.md 섹션3 규칙 0(승인 전 수정 금지) + 0-1(세션당 1단계) + 0-2(수정 전 사전조사) + 0-3(롤백 금지) + 0-4(핵심 로직 변경 UI 설명) + 0-5(사용자 설계 로직 더 엄격) + P10/P15/P16/P17/P20/P21/P22/P23/P24

---

## 0. 사전조사에서 발견한 설계서 오류 3건 (수정 제안)

> 설계서 작성 단계에서 파악하지 못한 실제 코드와의 불일치. 구현 세션 시작 전 사용자 승인 필요 (규칙 0-4 + 0-5).

### 0.1 오류 1: `test_risk_manager.py` 이미 존재 (신규 파일 아님)

- **설계서 7.1절/5.4절**: "`backend/tests/test_risk_manager.py` | 신규 | RiskManager 확장 전용 테스트"
- **실제 상태**: 파일이 이미 존재 (286줄). 기존 테스트 클래스:
  - `TestSyncThresholds` (L48)
  - `TestGetWithdrawableDeposit` (L80)
  - `TestCheckBuyOrderAllowed` (L109 — 11개 테스트, `await risk_manager.check_buy_order_allowed(...)` 형태)
  - `TestCheckSellOrderAllowed` (L250 — 3개 테스트, **동기 호출** `risk_manager.check_sell_order_allowed(...)` — `await` 없음)
  - `TestRecordOrder` (L271)
- **수정 제안**: "신규 파일" → "기존 파일 확장"으로 변경. `TestCheckSellOrderAllowed` 3개 테스트는 `check_sell_order_allowed()` async 변환에 따라 `await` 추가 + `@pytest.mark.asyncio` 추가 필요. 신규 조건 테스트는 기존 클래스에 추가 또는 신규 클래스 추가.

### 0.2 오류 2: UI 칩 색상 불일치 (설계서 "빨간색" vs 코드 `COLOR.downBg` 파랑)

- **설계서 4.3.3절**: "리스크 매니저 차단 칩 (빨간색 — 손실/수익 한도 도달)" + 코드에 `riskBlockChip.style.background = ${COLOR.downBg}`
- **실제 코드** (`frontend/src/components/common/ui-styles.ts:69-70`):
  ```typescript
  upBg:   '#ffebee',  // 빨강 배경  ← 주식 상승 = 빨강 (한국식)
  downBg: '#e3f2fd',  // 파랑 배경  ← 주식 하락 = 파랑 (한국식)
  ```
- **불일치**: 설계서 문구는 "빨간색"이지만 코드는 `downBg`(파랑). 리스크 차단은 경고/위험 상태이므로 빨강(`upBg`)이 의미에 부합.
- **수정 제안**: 코드를 `COLOR.upBg` + `COLOR.up`로 변경. (설계서 문구 "빨간색"이 의도한 바로 보임. 코드의 `downBg`가 오기입으로 판단.) — 사용자 승인 필요.

### 0.3 오류 3: `check_sell_order_allowed()` async 변환 시 기존 테스트 3개 깨짐

- **설계서 3.4.5절 주의**: "`check_sell_order_allowed()`를 `async def`로 변경해야 함. 호출부(`trading.py:682-683`)도 `await` 추가 필요."
- **실제 상태**: 호출부는 단일(`trading.py:683`)이나, **테스트 3개**(`test_risk_manager.py:253, 259, 265`)가 동기 호출 중.
- **수정 제안**: 4세션(RiskManager 확장)에서 `check_sell_order_allowed()` async 변환 시 동시에 테스트 3개도 `await` + `@pytest.mark.asyncio` 적용. 영향 범위 최소 (단일 파일 내 3줄).

---

## 1. 심층 사전조사 결과 (규칙 0-2 4항목)

### 1.1 의존성 분석

#### 백엔드 — 설정 계층 (3파일)

| 키/함수 | 파일:줄 | 영향 | 변경 내용 |
|---------|---------|------|-----------|
| `DEFAULT_USER_SETTINGS` | `settings_defaults.py:52-55` | **확장** | 기존 `max_daily_loss_limit`/`max_single_stock_exposure`/`max_position_size` 블록 직후 신규 키 12개 추가 |
| `engine_settings.py` 리스크 블록 | `engine_settings.py:137-144` | **확장** | 기존 `max_daily_loss_limit`/`max_single_stock_exposure` 캐스팅 직후 신규 키 12개 캐스팅 추가 |
| `apply_settings_updates()` | `settings_store.py:222` | **확장** | 기존 `subscribe.max_0b_count` 범위 검증(L296-303) 직후 신규 리스크 키 범위/부호 검증 추가 |

#### 백엔드 — RiskManager + 사유코드 (2파일)

| 함수/상수 | 파일:줄 | 영향 | 변경 내용 |
|-----------|---------|------|-----------|
| `_sync_thresholds()` | `risk_manager.py:29-37` | **확장** | 기존 3키 동기화 후 신규 11키 동기화 추가 (P13 메모리 상주) |
| `check_buy_order_allowed()` | `risk_manager.py:39-88` | **확장** | 기존 일일 손실 한도 체크(L50-57) 후 신규 5개 조건(손실률/수익/수익률/연속손실 + 리스크 매니저 OFF 가드 + 매수 차단 비활성화 가드) 추가 |
| `check_sell_order_allowed()` | `risk_manager.py:103-111` | **확장 + async 변환** | 동기 → `async def`. 서킷브레이커만 체크 → 6개 조건 확장. **Code Removal Rules 규칙 3 — 전체 검색 완료** (아래 표) |
| `_get_today_pnl_and_principal()` | (신규) | **신규** | 당일 실현손익 + 당일 매수 원금 반환 헬퍼 |
| `_get_consecutive_loss_count()` | (신규) | **신규** | 최근 매도 `realized_pnl` 음수 연속 건수 헬퍼 |
| `BUY_REJECT_RISK_*` 상수 | `trading.py:35-37, 51` | **확장** | 기존 4개(CIRCUIT/LOSS/CASH/SINGLE) + 신규 4개(PROFIT/LOSS_RATE/PROFIT_RATE/CONSEC_LOSS) |
| `BUY_GLOBAL_REJECT_REASONS` | `trading.py:57-69` | **확장** | frozenset에 신규 4개 추가 |
| `_map_risk_reason_to_code()` | `trading.py:72-86` | **확장** | 기존 4개 매핑 + 신규 4개 매핑 추가 |
| `check_sell_conditions()` 매도 체크 | `trading.py:680-689` | **확장** | `risk_mgr.check_sell_order_allowed(...)` → `await risk_mgr.check_sell_order_allowed(...)` + WS 브로드캐스트 추가 |

**`check_sell_order_allowed` 전체 참조 위치 (Code Removal Rules 규칙 3 — 전체 검색 완료)**:

| 위치 | 파일:줄 | 변경 내용 |
|------|---------|-----------|
| 정의 | `risk_manager.py:103` | `def` → `async def` + 본문 확장 |
| 호출 | `trading.py:683` | `await` 추가 |
| 테스트 호출 | `test_risk_manager.py:253` | `await` + `@pytest.mark.asyncio` |
| 테스트 호출 | `test_risk_manager.py:259` | `await` + `@pytest.mark.asyncio` |
| 테스트 호출 | `test_risk_manager.py:265` | `await` + `@pytest.mark.asyncio` |
| 테스트 docstring | `test_risk_manager.py:3` | "check_sell_order_allowed" 참조 유지 (함수명不变) |

#### 프론트엔드 (5파일)

| 심볼 | 파일:줄 | 영향 | 변경 내용 |
|------|---------|------|-----------|
| `AppSettings` 인터페이스 | `types/index.ts:105-156` | **확장** | 신규 키 12개 타입 추가 (기존 `subscribe.max_0b_count` 패턴 준수) |
| `renderAutoTradeTab()` | `general-settings.ts:397-487` | **확장** | 기존 `orderTimeGuardRow`(L467-485) 직후 "전역매매설정 (리스크 매니저)" 섹션 추가 |
| 모듈 상태 변수 | `general-settings.ts:49-75` | **확장** | 기존 토글/입력 참조 직후 리스크 매니저 참조 12개 추가 |
| `syncFromSettings()` | `general-settings.ts:170` | **확장** | 신규 키 동기화 추가 |
| `UIState` 인터페이스 | `uiStore.ts:69-94` | **확장** | 기존 `orderTimeBlocked`(L72) 직후 `riskBlockStatus` 추가 |
| `initialState` | `uiStore.ts:93-94` | **확장** | `riskBlockStatus: null` 추가 |
| `applySnapshotData()` | `uiStore.ts:139` | **확장** | 초기화에 `riskBlockStatus: null` 추가 (L250-251 패턴) |
| `applyRiskBlockStatus()` | (신규) | **신규** | `applyOrderTimeBlocked`(L153) 패턴 복제 |
| `clearRiskBlockStatus()` | (신규) | **신규** | `clearOrderTimeBlocked`(L163) 패턴 복제 |
| `binding.ts` WS 핸들러 | `binding.ts:330-333` | **확장** | 기존 `order_time_blocked` 핸들러 직후 `risk_block_status` 핸들러 추가 |
| `binding.ts` import | `binding.ts:36-37` | **확장** | `applyRiskBlockStatus` import 추가 |
| `header.ts` 칩 생성 | `header.ts:218-223` | **확장** | 기존 `orderTimeBlockedChip` 직후 `riskBlockChip` 추가 |
| `header.ts` `onStateChange` | `header.ts:258, 271-280` | **확장** | destructuring `riskBlockStatus` 추가 + 표시 로직 추가 |

#### 테스트 (4파일 — 3파일 수정 + 1파일 확장)

| 파일 | 상태 | 변경 내용 |
|------|------|-----------|
| `test_risk_manager.py` | **기존 확장** (오류 1 참조) | `TestCheckSellOrderAllowed` 3개 async 변환 + 신규 조건 테스트 클래스 추가 |
| `test_trading.py` | **수정** | `TestMapRiskReasonToCode`(L453-470) 신규 매핑 4개 추가 + `TestCheckSellConditions` 매도 체크 `await` 반영 |
| `test_buy_order_executor.py` | **수정** | 신규 사유코드 4개가 `BUY_GLOBAL_REJECT_REASONS` 전체 차단 분류되는지 검증 테스트 추가 |
| `test_settings_store.py` | **수정** | `TestSubscribeMax0bCountValidation`(L589) 패턴 복제 — 신규 리스크 키 범위 검증 5개 추가 |

### 1.2 영향 범위

| 영역 | 변경 여부 | 상세 |
|------|-----------|------|
| **백엔드** | 변경 | 5파일 수정 (`settings_defaults.py`, `engine_settings.py`, `settings_store.py`, `risk_manager.py`, `trading.py`) |
| **프론트엔드** | 변경 | 5파일 수정 (`types/index.ts`, `general-settings.ts`, `uiStore.ts`, `binding.ts`, `header.ts`) |
| **테스트** | 변경 | 4파일 (3 수정 + 1 확장) |
| **문서** | 변경 (최종 세션) | `ARCHITECTURE.md` 리스크 매니저 섹션 갱신 + 설계서/태스크 파일 삭제 |
| **DB** | 변경 없음 | 스키마 변경 없음 — 설정 키 추가만 (기존 `user_settings` 테이블 key-value 구조) |
| **설정** | 변경 | `integrated_system_settings_cache` 신규 키 12개 추가 |

### 1.3 아키텍처 원칙 부합 여부

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10 (SSOT) | 준수 | 설정: `integrated_system_settings_cache` 단일 소스. 손익/연속손실: `trade_history` 파생 (중복 저장 금지) |
| P15 (단일 주문 경로) | 준수 | `execute_buy()`/`execute_sell()` 경로 유지. 새 조건을 `check_buy/sell_order_allowed()` 내부에 추가 |
| P16 (살아있는 경로) | 준수 | `check_buy_order_allowed()` → `execute_buy()` 자동 배선. `check_sell_order_allowed()` → `check_sell_conditions()` 자동 배선. dead code 없음 |
| P17 (플래그 단일 소스) | 준수 | `risk_manager_on`/`risk_block_buy_on`/`risk_block_sell_on` 모두 `integrated_system_settings_cache`에서만 관리 |
| P20 (폴백 금지) | 준수 | 0 유효값 → `int(_v if _v is not None else 기본값)` 패턴. 범위 검증 실패 시 422 차단. silent except: pass 금지 (매도 체크 실패 시 매도 전체 중단 — 보수적 차단) |
| P21 (사용자 투명성) | 준수 | 모든 리스크 조건 UI 제어 가능. 차단 사유 WS 브로드캐스트 → 헤더 칩 실시간 표시. 기존 `circuit_breaker_open`/`order_time_blocked` 패턴 재사용 |
| P22 (데이터 정합성) | 준수 | 손익/연속손실 카운트 `trade_history` 파생. 별도 저장 없음. 불일치 가능성 없음 |
| P23 (일관성) | 준수 | 손익 기준 = 기존 `daily_loss_limit`과 동일(현금 기준). 사유코드 `BUY_REJECT_RISK_*` 패턴 준수. UI 공통 컴포넌트 재사용 (`createToggleLabelControlsRow`/`createMoneyInput`/`createNumInput`). 헤더 칩 패턴 기존과 동일. 용어 사전 준수 ("매수"/"매도"/"종목") |
| P24 (단순성) | 준수 | `RiskManager` 내부 조건 추가만. 새 클래스/서비스/경로 생성 없음. 헬퍼 2개로 함수 50줄 이하 유지. 기존 UI 패턴 재사용 |

### 1.4 기존 공통 자산 확인 (P23 사전 절차)

| 자산 | 위치 | 재사용 여부 |
|------|------|-------------|
| `get_total_realized_pnl()` | `trade_history.py:430` | **재사용** — 당일 실현손익 집계 (현금 기준, 기존 `daily_loss_limit`과 동일) |
| `get_buy_history()` | `trade_history.py:418` | **재사용** — 당일 매수 원금 집계 (수익률 분모) |
| `get_sell_history()` | `trade_history.py:423` | **재사용** — 연속 손실 카운트 (DESC 정렬) |
| `is_test_mode()` | `trade_mode.py` | **재사용** — `check_buy_order_allowed()` 기존 패턴 |
| `_safe_broadcast()` | `engine_account_notify.py:77` | **재사용** — 매도 차단 시 WS 브로드캐스트 |
| `BUY_REJECT_RISK_*` 상수 패턴 | `trading.py:35-51` | **재사용** — 신규 4개 동일 패턴 추가 |
| `BUY_GLOBAL_REJECT_REASONS` | `trading.py:57-69` | **재사용** — frozenset 확장 |
| `_map_risk_reason_to_code()` | `trading.py:72-86` | **재사용** — 매핑 패턴 확장 |
| `createToggleBtn` | `setting-row.ts` | **재사용** — 리스크 매니저 토글 |
| `createMoneyInput` | `setting-row.ts:274` | **재사용** — 일일 손실/수익 한도 금액 입력 |
| `createNumInput` | `setting-row.ts:204` | **재사용** — 손실률/수익률/연속손실 횟수 입력 |
| `createToggleLabelControlsRow` | `setting-row.ts:120` | **재사용** — 토글+입력쌍 행 (손실률/수익/수익률/연속손실) |
| `sectionTitle`/`createDescText` | `settings-common.ts` | **재사용** — 섹션 제목/설명 문구 |
| `applyOrderTimeBlocked`/`clearOrderTimeBlocked` | `uiStore.ts:153-163` | **재사용** — `applyRiskBlockStatus`/`clearRiskBlockStatus` 패턴 복제 |
| `orderTimeBlockedChip` | `header.ts:218-223, 271-280` | **재사용** — `riskBlockChip` 패턴 복제 |
| `order_time_blocked` WS 핸들러 | `binding.ts:330-333` | **재사용** — `risk_block_status` 핸들러 패턴 복제 |
| `AppSettings` 인터페이스 | `types/index.ts:105` | **재사용** — 신규 키 12개 추가 (기존 `subscribe.max_0b_count` 패턴) |
| `TestSubscribeMax0bCountValidation` | `test_settings_store.py:589` | **재사용** — 신규 리스크 키 범위 검증 테스트 패턴 복제 |
| `TestMapRiskReasonToCode` | `test_trading.py:453` | **재사용** — 신규 매핑 4개 테스트 패턴 복제 |
| `TestCheckSellOrderAllowed` | `test_risk_manager.py:250` | **재사용** — async 변환 + 신규 조건 테스트 추가 |

**신규 생성 자산**: `_get_today_pnl_and_principal()`, `_get_consecutive_loss_count()` (RiskManager 헬퍼 2개), `applyRiskBlockStatus()`/`clearRiskBlockStatus()` (uiStore 함수 2개), `risk_block_status` WS 이벤트, `riskBlockChip` (header 칩). 모두 기존 패턴 준수.

---

## 2. 구현 Step + 세션 분할

> 규칙 0-1(세션당 1단계) 준수. 4개 구현 세션(3~6세션)은 각각 독립적으로 완료·검증 가능.

### 2.1 3세션 — 구현 Step 1: 백엔드 설정 계층 + 사유코드 (4파일)

> 가장 하위 계층. 다른 단계의 의존基础. 테스트는 `test_settings_store.py` 범위 검증만 포함 (독립 검증 가능).

#### 수정 파일
- `backend/app/core/settings_defaults.py`
- `backend/app/core/engine_settings.py`
- `backend/app/core/settings_store.py`
- `backend/app/services/trading.py` (사유코드 블록만 — L35-86)
- `backend/tests/test_settings_store.py`

#### 수정 상세

**A. `settings_defaults.py` — 신규 키 12개 기본값 추가**
- 위치: L54 (`max_single_stock_exposure` 행) 직후
- 추가 키 (설계서 3.1절 참조):
  - `risk_manager_on`: False
  - `daily_loss_limit`: -500000 (기존 `max_daily_loss_limit`과 동일 기준, UI 노출용)
  - `daily_loss_rate_limit_on`: False / `daily_loss_rate_limit`: -5.0
  - `daily_profit_limit_on`: False / `daily_profit_limit`: 500000
  - `daily_profit_rate_limit_on`: False / `daily_profit_rate_limit`: 5.0
  - `risk_block_buy_on`: True / `risk_block_sell_on`: False
  - `consecutive_loss_limit_on`: False / `consecutive_loss_limit`: 3
- 기존 `max_daily_loss_limit` 키는 유지 (레거시 호환)

**B. `engine_settings.py` — 신규 키 12개 타입 캐스팅 추가**
- 위치: L144 (`max_single_stock_exposure` 캐스팅) 직후
- 패턴: `int(_v if _v is not None else 기본값)` / `float(_v if _v is not None else 기본값)` / `bool(merged.get(...))` (P20 — 0 유효값이므로 `or` 폴백 금지)
- `risk_block_buy_on`/`risk_block_sell_on`은 `bool(merged.get(k, 기본값))` — 기본값 인자로 폴백 (False/True)

**C. `settings_store.py` — 신규 리스크 키 범위 검증 추가**
- 위치: L303 (`subscribe.max_0b_count` 검증 블록) 직후
- 검증 로직 (설계서 3.3절 참조):
  - `_RISK_INT_KEYS`: `daily_loss_limit`(-10억~0), `daily_profit_limit`(0~10억), `consecutive_loss_limit`(1~100)
  - `_RISK_FLOAT_KEYS`: `daily_loss_rate_limit`(-100~0), `daily_profit_rate_limit`(0~100)
  - 범위 위반 시 `raise ValueError` → 422 차단 (P20/P22)

**D. `trading.py` — 사유코드 4개 + frozenset 확장 + 매핑 확장**
- 위치: L35-51 (상수 블록), L57-69 (frozenset), L72-86 (매핑 함수)
- 신규 상수 4개: `BUY_REJECT_RISK_PROFIT`/`_LOSS_RATE`/`_PROFIT_RATE`/`_CONSEC_LOSS`
- `BUY_GLOBAL_REJECT_REASONS` frozenset에 4개 추가
- `_map_risk_reason_to_code()`에 신규 매핑 4개 추가 (기존 매핑 순서 유지, 신규는 "일일 손실 한도" 이후에 삽입)

**E. `test_settings_store.py` — 신규 리스크 키 범위 검증 테스트 5개**
- 위치: `TestSubscribeMax0bCountValidation`(L589) 이후
- 신규 클래스 `TestRiskManagerSettingsValidation` (패턴 복제):
  - `test_rejects_positive_daily_loss_limit` — 양수 입력 시 ValueError
  - `test_rejects_negative_daily_profit_limit` — 음수 입력 시 ValueError
  - `test_rejects_zero_consecutive_loss_limit` — 0 입력 시 ValueError
  - `test_rejects_positive_daily_loss_rate_limit` — 양수 입력 시 ValueError
  - `test_rejects_negative_daily_profit_rate_limit` — 음수 입력 시 ValueError
  - `test_accepts_valid_risk_values` — 경계값 통과 (선택)

#### 검증
- `cd backend && pytest tests/test_settings_store.py -v`
- `cd backend && pytest tests/test_trading.py::TestMapRiskReasonToCode -v` (신규 매핑 4개)
- `python3 -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 0건 + `/api/settings` 응답에 신규 키 12개 포함 확인
- `py_compile` 4파일
- 잔존 프로세스 0건

---

### 2.2 4세션 — 구현 Step 2: RiskManager 확장 + 매도 체크 async 변환 + WS 브로드캐스트 (2파일 + 테스트 2파일)

> 핵심 로직 변경 (규칙 0-4 + 0-5 적용 — 사용자 승인 필수). `check_sell_order_allowed()` async 변환은 기존 테스트 3개에 영향 (오류 3 참조).

#### 수정 파일
- `backend/app/services/risk_manager.py`
- `backend/app/services/trading.py` (매도 체크 부분만 — L680-689)
- `backend/tests/test_risk_manager.py` (기존 확장 — 오류 1 참조)
- `backend/tests/test_trading.py` (매도 체크 테스트 갱신)

#### 수정 상세

**A. `risk_manager.py` — `_sync_thresholds()` 확장**
- 위치: L29-37
- 기존 3키 동기화 후 신규 11키 동기화 추가 (설계서 3.4.1절 참조)
- 패턴: `int(cache.get(k, 기본값) or 기본값)` — 단, 0 유효값이면 `or` 폴백 금지 → `int(cache.get(k) if cache.get(k) is not None else 기본값)` 적용
- `risk_manager_on`/`risk_block_buy_on`/`risk_block_sell_on`/`daily_loss_rate_limit_on`/`daily_profit_limit_on`/`daily_profit_rate_limit_on`/`consecutive_loss_limit_on`은 `bool(cache.get(k, 기본값))`

**B. `risk_manager.py` — `_get_today_pnl_and_principal()` 신규 헬퍼**
- 위치: `_sync_thresholds()` 정의 이후
- async def. `get_total_realized_pnl(today_only=True, trade_mode=...)` + `get_buy_history(today_only=True, trade_mode=...)` 호출
- 반환: `(today_pnl: int, today_buy_principal: int)`
- 당일 매수 원금 = `sum(price * qty for r in buy_rows)`

**C. `risk_manager.py` — `_get_consecutive_loss_count()` 신규 헬퍼**
- 위치: `_get_today_pnl_and_principal()` 이후
- async def. `get_sell_history(trade_mode=...)` 호출 (DESC 정렬)
- 최신 매도부터 역순으로 `realized_pnl < 0` 연속 건수 카운트
- 매도 이력 없거나 최신 거래가 수익이면 0 반환

**D. `risk_manager.py` — `check_buy_order_allowed()` 확장**
- 위치: L39-88
- 기존 서킷브레이커 체크(L47-48) 후 신규 가드 추가:
  1. `risk_manager_on` False → 서킷브레이커만 유지 후 승인 반환
  2. `risk_block_buy_on` False → 리스크 조건 스킵 후 승인 반환
- 기존 일일 손실 한도 체크(L50-57) 후 신규 4개 조건 추가:
  3. 일일 손실률 한도 (`daily_loss_rate_limit_on` and `today_principal > 0`)
  4. 일일 수익 한도 (`daily_profit_limit_on`)
  5. 일일 수익률 한도 (`daily_profit_rate_limit_on` and `today_principal > 0`)
  6. 연속 손실 횟수 (`consecutive_loss_limit_on`)
- 기존 예수금/단일 종목 비중 체크는 그대로 유지 (L59-86)
- `today_pnl`, `today_principal`은 `_get_today_pnl_and_principal(trade_mode)`에서 획득 (기존 `today_pnl = await get_total_realized_pnl(...)` 대체 — 중복 조회 방지 P10)

**E. `risk_manager.py` — `check_sell_order_allowed()` async 변환 + 확장**
- 위치: L103-111
- `def` → `async def`
- 기존 서킷브레이커 체크 후 신규 가드 + 5개 조건 추가 (설계서 3.4.5절 참조)
- 매도 차단 시 사유 문자열에 "(매도 차단)" 접미사 추가 — 매수 차단과 구분 (P23 일관성)

**F. `trading.py` — `check_sell_conditions()` 매도 체크 await + WS 브로드캐스트**
- 위치: L680-689
- `allowed, reason = risk_mgr.check_sell_order_allowed("", 0, 0)` → `allowed, reason = await risk_mgr.check_sell_order_allowed("", 0, 0)`
- 차단 시 `from backend.app.services.engine_account_notify import _safe_broadcast` + `await _safe_broadcast("risk_block_status", {"blocked": True, "side": "sell", "reason": reason})` 추가 (P21)
- `except Exception` 블록 유지 — `logger.warning(..., exc_info=True)` + 매도 전체 중단 `return` (보수적 차단)

**G. `test_risk_manager.py` — 기존 3개 async 변환 + 신규 조건 테스트**
- `TestCheckSellOrderAllowed`(L250-266) 3개 테스트:
  - `def test_closed_allows_sell` → `async def test_closed_allows_sell` + `@pytest.mark.asyncio` + `await risk_manager.check_sell_order_allowed(...)`
  - 동일 패턴 3개 적용
- 신규 테스트 클래스 추가 (설계서 5.4절):
  - `TestRiskManagerToggle`: `risk_manager_on=False` 시 서킷브레이커만 동작 / `risk_block_buy_on=False` 시 매수 리스크 스킵 / `risk_block_sell_on=False` 시 매도 리스크 스킵
  - `TestDailyLossRateLimit`: 손실률 한도 초과 시 매수/매도 차단
  - `TestDailyProfitLimit`: 수익 한도 도달 시 차단
  - `TestDailyProfitRateLimit`: 수익률 한도 도달 시 차단
  - `TestConsecutiveLossLimit`: 연속 손실 N회 시 차단
  - `TestCheckSellOrderAllowedAsync`: async 동작 검증 (기존 클래스 확장 또는 신규)
- 기존 `TestCheckBuyOrderAllowed`(L109-245) 11개 테스트는 `risk_manager_on=False` 기본값이므로 기존 동작 유지 — 단, mock에 `risk_manager_on`/`risk_block_buy_on` 등 신규 필드 추가 필요

**H. `test_trading.py` — 매도 체크 테스트 갱신**
- `TestCheckSellConditions`(L475) 내 매도 체크 관련 테스트 — `check_sell_order_allowed` async 변환 반영
- `TestMapRiskReasonToCode`(L453) — 신규 매핑 4개 테스트 추가 (설계서 5.1절):
  - `test_profit_mapping`: "일일 수익 한도" → `BUY_REJECT_RISK_PROFIT`
  - `test_loss_rate_mapping`: "일일 손실률 한도" → `BUY_REJECT_RISK_LOSS_RATE`
  - `test_profit_rate_mapping`: "일일 수익률 한도" → `BUY_REJECT_RISK_PROFIT_RATE`
  - `test_consec_loss_mapping`: "연속 손실 한도" → `BUY_REJECT_RISK_CONSEC_LOSS`

#### 검증
- `cd backend && pytest tests/test_risk_manager.py -v` (기존 286줄 + 신규 테스트)
- `cd backend && pytest tests/test_trading.py -v`
- `python3 -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 0건 (async await 누락 점검)
- `py_compile` 2파일
- 잔존 프로세스 0건

---

### 2.3 5세션 — 구현 Step 3: 프론트엔드 (5파일)

> UI 기준 동작 (규칙 0-4): "전역매매설정 (리스크 매니저)" 섹션 신규 추가 + 헤더 빨간 칩 표시.

#### 수정 파일
- `frontend/src/types/index.ts`
- `frontend/src/pages/general-settings.ts`
- `frontend/src/stores/uiStore.ts`
- `frontend/src/binding.ts`
- `frontend/src/layout/header.ts`

#### 수정 상세

**A. `types/index.ts` — `AppSettings`에 신규 키 12개 타입 추가**
- 위치: L156 (`subscribe.max_0b_count` 행) 직후
- 추가 (설계서 4.4절 참조):
  ```typescript
  risk_manager_on?: boolean
  daily_loss_limit?: number
  daily_loss_rate_limit_on?: boolean
  daily_loss_rate_limit?: number
  daily_profit_limit_on?: boolean
  daily_profit_limit?: number
  daily_profit_rate_limit_on?: boolean
  daily_profit_rate_limit?: number
  risk_block_buy_on?: boolean
  risk_block_sell_on?: boolean
  consecutive_loss_limit_on?: boolean
  consecutive_loss_limit?: number
  ```

**B. `general-settings.ts` — 리스크 매니저 섹션 추가**
- 모듈 상태 변수 (L49-75 직후): 신규 참조 12개 추가 (설계서 4.2절)
- `renderAutoTradeTab()` 내 `orderTimeGuardRow`(L485) + 설명 문구(L487) 직후:
  - `sectionTitle('전역매매설정 (리스크 매니저)')`
  - `createDescText('목표 수익/손실 도달 시 자동 매매 중단. 리스크 매니저 OFF 시 모든 조건 비활성화.')`
  - 리스크 매니저 토글 행 (`risk_manager_on`)
  - 일일 손실 한도 행 (`createMoneyInput`, 음수, `daily_loss_limit`)
  - 일일 손실률 한도 행 (`createToggleLabelControlsRow` — 토글 + `createNumInput` %, `daily_loss_rate_limit_on`/`_limit`)
  - 일일 수익 한도 행 (`createToggleLabelControlsRow` — 토글 + `createMoneyInput`, `daily_profit_limit_on`/`_limit`)
  - 일일 수익률 한도 행 (`createToggleLabelControlsRow` — 토글 + `createNumInput` %, `daily_profit_rate_limit_on`/`_limit`)
  - 연속 손실 횟수 행 (`createToggleLabelControlsRow` — 토글 + `createNumInput` 회, `consecutive_loss_limit_on`/`_limit`)
  - 매수 차단 체크박스 행 (`risk_block_buy_on`)
  - 매도 차단 체크박스 행 (`risk_block_sell_on`) + 위험성 설명 문구 ("손실 상태에서 매도 차단 시 손실 확대 위험")
- 각 행 자동 저장: `settingsMgr!.saveSection({ key: value }).then(toastResult)` (기존 패턴)
- `syncFromSettings()`(L170): 신규 키 12개 동기화 추가

**C. `uiStore.ts` — `riskBlockStatus` 상태 + 적용/해제 함수**
- `UIState` 인터페이스 (L72 `orderTimeBlocked` 직후): `riskBlockStatus: { side: string; reason: string } | null`
- `initialState` (L94): `riskBlockStatus: null`
- `applySnapshotData()`(L139): 초기화에 `riskBlockStatus: null` 추가 (L250-251 패턴)
- 신규 함수 (L163 `clearOrderTimeBlocked` 이후):
  - `applyRiskBlockStatus(data: { blocked?: boolean; side?: string; reason?: string })` — `applyOrderTimeBlocked`(L153) 패턴 복제
  - `clearRiskBlockStatus()` — `clearOrderTimeBlocked`(L163) 패턴 복제

**D. `binding.ts` — `risk_block_status` WS 이벤트 핸들러**
- import (L36-37): `applyRiskBlockStatus` 추가
- WS 핸들러 (L333 `order_time_blocked` 핸들러 이후):
  ```typescript
  pricesClient.onEvent('risk_block_status', (data) => {
    applyRiskBlockStatus(data as { blocked?: boolean; side?: string; reason?: string })
  })
  ```

**E. `header.ts` — 리스크 차단 칩 추가**
- 칩 생성 (L223 `orderTimeBlockedChip` 이후):
  ```typescript
  const riskBlockChip = createChipEl()
  riskBlockChip.style.display = 'none'
  riskBlockChip.style.cursor = 'pointer'
  riskBlockChip.addEventListener('click', () => clearRiskBlockStatus())
  header.appendChild(riskBlockChip)
  ```
- `onStateChange` destructuring (L258): `riskBlockStatus` 추가
- 표시 로직 (L280 `orderTimeBlocked` 블록 이후):
  - **오류 2 수정 적용**: `COLOR.upBg`/`COLOR.up` 사용 (빨강 — 설계서 문구 의도). `COLOR.downBg` 아님.
  ```typescript
  if (riskBlockStatus) {
    riskBlockChip.style.display = ''
    riskBlockChip.style.background = `${COLOR.upBg}`
    riskBlockChip.style.color = `${COLOR.up}`
    riskBlockChip.style.border = `1px solid ${COLOR.up}40`
    const sideLabel = riskBlockStatus.side === 'buy' ? '매수' : riskBlockStatus.side === 'sell' ? '매도' : '매매'
    riskBlockChip.textContent = `⚠ 리스크 차단(${sideLabel}): ${riskBlockStatus.reason}`
  } else {
    riskBlockChip.style.display = 'none'
  }
  ```
- import: `clearRiskBlockStatus` 추가 (기존 `clearOrderTimeBlocked` import 패턴)

#### 검증
- `cd frontend && npm run build` (tsc 타입체크 + vite 빌드)
- 브라우저 확인: 일반설정 → 자동매매 탭 → "전역매매설정 (리스크 매니저)" 섹션 표시 + 각 토글/입력 동작 + 자동 저장
- 설정 저장 후 재기동 시 값 유지 확인
- 리스크 차단 강제 발생 시 헤더 빨간 칩 표시 확인 (수동 테스트 — 백엔드 조건 충족 필요)

---

### 2.4 6세션 — 구현 Step 4: 통합 검증 + test_buy_order_executor + 문서 갱신 + 계획서 삭제

> 최종 세션. 전체 회귀 + 신규 사유코드 분류 테스트 + 문서 정리.

#### 수정 파일
- `backend/tests/test_buy_order_executor.py`
- `ARCHITECTURE.md`
- `docs/architecture_risk_manager_extension_design.md` (삭제)
- `docs/plan_risk_manager_extension.md` (삭제 — 본 파일)

#### 수정 상세

**A. `test_buy_order_executor.py` — 신규 사유코드 4개 전체 차단 분류 테스트**
- 위치: 기존 `BUY_REJECT_RISE_GUARD`/`BUY_REJECT_AUTO_BUY_OFF` 테스트 패턴(L430, L849) 참조
- 신규 테스트 4개:
  - `test_risk_profit_reason_blocks_all` — `BUY_REJECT_RISK_PROFIT` 반환 시 차순위 시도 안 함 (전체 차단)
  - `test_risk_loss_rate_reason_blocks_all` — `BUY_REJECT_RISK_LOSS_RATE`
  - `test_risk_profit_rate_reason_blocks_all` — `BUY_REJECT_RISK_PROFIT_RATE`
  - `test_risk_consec_loss_reason_blocks_all` — `BUY_REJECT_RISK_CONSEC_LOSS`
- 패턴: `fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_RISK_PROFIT))` → 2순위 호출 안 됨 검증

**B. `ARCHITECTURE.md` — 리스크 매니저 섹션 갱신**
- 기존 리스크 관리 섹션에 신규 키 12개 + UI 노출 + WS 이벤트 `risk_block_status` 명시
- 기존 `max_daily_loss_limit` 레거시 호환 주석 추가
- 헤더 칩 패턴에 `riskBlockStatus` 추가 (기존 `circuitBreakerOpen`/`orderTimeBlocked`와 동일 패턴)

**C. 계획서 삭제 (규칙 11)**
- `git rm docs/architecture_risk_manager_extension_design.md`
- `git rm docs/plan_risk_manager_extension.md`

#### 검증 (통합)
- `cd backend && pytest` 전체 — 기존 2935 passed 카운트 유지 + 신규 테스트 통과
- `cd frontend && npm run build` 성공
- `python3 -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 0건
- `/api/settings` 응답에 신규 키 12개 포함 확인
- 잔존 프로세스 0건
- `grep "check_sell_order_allowed" backend/` — `await` 누락 0건 (Code Removal Rules 규칙 3)
- 계획서 2개 파일 삭제 확인

---

## 3. 테스트 계획

### 3.1 3세션 테스트 (설정 계층 + 사유코드)

| 테스트 클래스 | 테스트 | 검증 항목 |
|---------------|--------|-----------|
| `TestRiskManagerSettingsValidation` (신규) | `test_rejects_positive_daily_loss_limit` | 양수 입력 시 ValueError → 422 |
| `TestRiskManagerSettingsValidation` | `test_rejects_negative_daily_profit_limit` | 음수 입력 시 ValueError → 422 |
| `TestRiskManagerSettingsValidation` | `test_rejects_zero_consecutive_loss_limit` | 0 입력 시 ValueError → 422 |
| `TestRiskManagerSettingsValidation` | `test_rejects_positive_daily_loss_rate_limit` | 양수 입력 시 ValueError → 422 |
| `TestRiskManagerSettingsValidation` | `test_rejects_negative_daily_profit_rate_limit` | 음수 입력 시 ValueError → 422 |
| `TestRiskManagerSettingsValidation` | `test_accepts_valid_risk_values` | 경계값 통과 (선택) |
| `TestMapRiskReasonToCode` (확장) | `test_profit_mapping` (신규) | "일일 수익 한도" → `BUY_REJECT_RISK_PROFIT` |
| `TestMapRiskReasonToCode` | `test_loss_rate_mapping` (신규) | "일일 손실률 한도" → `BUY_REJECT_RISK_LOSS_RATE` |
| `TestMapRiskReasonToCode` | `test_profit_rate_mapping` (신규) | "일일 수익률 한도" → `BUY_REJECT_RISK_PROFIT_RATE` |
| `TestMapRiskReasonToCode` | `test_consec_loss_mapping` (신규) | "연속 손실 한도" → `BUY_REJECT_RISK_CONSEC_LOSS` |

### 3.2 4세션 테스트 (RiskManager 확장 + 매도 async)

| 테스트 클래스 | 테스트 | 검증 항목 |
|---------------|--------|-----------|
| `TestCheckSellOrderAllowed` (갱신) | `test_closed_allows_sell` (async 변환) | `await` 정상 동작 |
| `TestCheckSellOrderAllowed` (갱신) | `test_open_blocks_sell` (async 변환) | 서킷브레이커 차단 |
| `TestCheckSellOrderAllowed` (갱신) | `test_half_open_allows_sell` (async 변환) | HALF_OPEN 승인 |
| `TestRiskManagerToggle` (신규) | `test_risk_manager_off_skips_risk_checks` | `risk_manager_on=False` 시 서킷브레이커만 |
| `TestRiskManagerToggle` | `test_risk_block_buy_off_skips_buy_checks` | `risk_block_buy_on=False` 시 매수 리스크 스킵 |
| `TestRiskManagerToggle` | `test_risk_block_sell_off_skips_sell_checks` | `risk_block_sell_on=False` 시 매도 리스크 스킵 |
| `TestDailyLossRateLimit` (신규) | `test_loss_rate_exceeds_blocks_buy` | 손실률 한도 초과 시 매수 차단 |
| `TestDailyLossRateLimit` | `test_loss_rate_exceeds_blocks_sell` | 손실률 한도 초과 시 매도 차단 (sell_on=True) |
| `TestDailyProfitLimit` (신규) | `test_profit_reached_blocks_buy` | 수익 한도 도달 시 매수 차단 |
| `TestDailyProfitRateLimit` (신규) | `test_profit_rate_reached_blocks` | 수익률 한도 도달 시 차단 |
| `TestConsecutiveLossLimit` (신규) | `test_consec_loss_exceeds_blocks` | 연속 손실 N회 시 차단 |
| `TestConsecutiveLossLimit` | `test_consec_loss_zero_history` | 매도 이력 없으면 0회 (차단 안 함) |
| `TestCheckSellConditions` (갱신) | 기존 테스트 `await` 반영 | async 변환 호환성 |

### 3.3 6세션 테스트 (통합 + buy_order_executor)

| 테스트 클래스 | 테스트 | 검증 항목 |
|---------------|--------|-----------|
| (기존 클래스 확장) | `test_risk_profit_reason_blocks_all` (신규) | `BUY_REJECT_RISK_PROFIT` 전체 차단 분류 |
| (기존 클래스 확장) | `test_risk_loss_rate_reason_blocks_all` (신규) | `BUY_REJECT_RISK_LOSS_RATE` 전체 차단 |
| (기존 클래스 확장) | `test_risk_profit_rate_reason_blocks_all` (신규) | `BUY_REJECT_RISK_PROFIT_RATE` 전체 차단 |
| (기존 클래스 확장) | `test_risk_consec_loss_reason_blocks_all` (신규) | `BUY_REJECT_RISK_CONSEC_LOSS` 전체 차단 |

### 3.4 통합 회귀 (6세션)
- pytest 전체 — 기존 2935 passed 카운트 유지 + 신규 테스트 통과
- 런타임 기동 (`python3 -W error::RuntimeWarning main.py`)
- 빌드 (`npm run build`)
- 잔존 참조 grep (`check_sell_order_allowed` await 누락 0건)

---

## 4. 런타임 검증 방법

### 4.1 각 구현 세션 (3, 4, 5세션)

```bash
# 3세션 (백엔드 설정 계층)
cd backend && pytest tests/test_settings_store.py tests/test_trading.py::TestMapRiskReasonToCode -v
python3 -W error::RuntimeWarning main.py
curl -s http://localhost:8000/api/settings | python3 -m json.tool | grep risk_manager_on
ps aux | grep "[m]ain.py" | wc -l

# 4세션 (RiskManager 확장)
cd backend && pytest tests/test_risk_manager.py tests/test_trading.py -v
python3 -W error::RuntimeWarning main.py
ps aux | grep "[m]ain.py" | wc -l

# 5세션 (프론트엔드)
cd frontend && npm run build
# 브라우저: 일반설정 → 자동매매 탭 → 리스크 매니저 섹션 확인
```

### 4.2 6세션 통합 검증

```bash
cd backend && pytest  # 전체 회귀
cd frontend && npm run build
python3 -W error::RuntimeWarning main.py
curl -s http://localhost:8000/api/settings | python3 -m json.tool | grep -E "risk_manager_on|daily_loss_limit|consecutive_loss"
grep -rn "check_sell_order_allowed" backend/ --include="*.py"  # await 누락 0건
ps aux | grep "[m]ain.py" | wc -l
```

---

## 5. 사용자 결정 항목

### 5.1 이미 결정된 항목 (설계서 1세션 — 9.2절)

| 항목 | 결정 | 근거 |
|------|------|------|
| 수익금/손실금 기준 | 당일 실현손익(현금 기준) | 기존 `daily_loss_limit`과 동일 (P23) |
| 매도 차단 기본값 | `risk_block_sell_on` False | 손실 확대 방지 — 사용자 명시적 ON |
| 연속 손실 기준 | 최근 매도 `realized_pnl` 음수 연속 | 순수 차익 기준 직관적 |
| 리스크 매니저 전체 토글 | `risk_manager_on` 별도 | 모든 조건 한 번에 끄기 |

### 5.2 2세션에서 확인된 항목 (심층 사전조사)

| 항목 | 결정 | 근거 |
|------|------|------|
| `test_risk_manager.py` 신규 여부 | **기존 확장** (오류 1) | 파일이 이미 존재 (286줄) — 설계서 오류 수정 |
| UI 칩 색상 | **`COLOR.upBg`(빨강)** (오류 2) | 설계서 문구 "빨간색"이 의도 — `downBg`(파랑)는 오기입 |
| `check_sell_order_allowed` async 변환 영향 | 테스트 3개 갱신 (오류 3) | 단일 파일 내 3줄 — 영향 최소 |
| 세션 분할: 4개 구현 세션 | 확정 | 설정 계층 / RiskManager / 프론트엔드 / 통합검증 — 수정 영역 독립 |
| 3세션에 사유코드 포함 | 확정 | `trading.py` 사유코드 블록(L35-86)은 RiskManager 확장과 독립 — 설정 계층과 동일 세션 배치 가능 |
| 4세션에 매도 WS 브로드캐스트 포함 | 확정 | `check_sell_order_allowed` async 변환과 동일 파일/함수 — 분리 불가 |

### 5.3 구현 승인 대기 항목 (사용자 명시적 승인 필요)

> 규칙 0-4 + 0-5 적용 — 핵심 로직 변경 시 UI 기준 설명 + 승인 필수.

1. **오류 1~3 수정 승인** (본 태스크 파일 0절 참조)
2. **3세션 구현 Step 1 승인** (백엔드 설정 계층 + 사유코드)
3. **4세션 구현 Step 2 승인** (RiskManager 확장 — 핵심 매매 로직 변경, 규칙 0-5 더 엄격 적용)
4. **5세션 구현 Step 3 승인** (프론트엔드 — UI 기준 동작 변경, 규칙 0-4)
5. **6세션 통합 검증 + 문서 갱신 + 계획서 삭제 승인**

---

## 6. 위험 요소 + 대응

| 위험 | 가능성 | 대응 |
|------|--------|------|
| 매도 차단 시 손실 확대 | 중간 | `risk_block_sell_on` 기본 False + UI 위험성 문구 명시 (설계서 10.1절) |
| `check_sell_order_allowed` async 변환 시 await 누락 | 낮음 | 단일 호출부(`trading.py:683`) + 테스트 3개 — 전체 검색 완료 (1.1절) |
| 매수/매도 시도 시마다 `trade_history` 3회 조회 | 매우 낮음 | 메모리 조회 (`_ensure_loaded()` 후 리스트 순회) — DB I/O 없음. 주문 빈도 낮음 (설계서 10.3절) |
| 기존 `max_daily_loss_limit` 키 호환 | 낮음 | `_sync_thresholds()`에서 `daily_loss_limit` 우선, 없으면 `max_daily_loss_limit` 폴백 (정상 마이그레이션, 설계서 10.4절) |
| `risk_manager_on=False` 기본값으로 인해 기존 동작 유지 안 됨 | 없음 | 기본 False → 기존 사용자 경험 동일 (리스크 매니저 OFF = 서킷브레이커만). 사용자 명시적 ON 필요 |
| 신규 사유코드 4개가 `BUY_GLOBAL_REJECT_REASONS` 누락 | 낮음 | 6세션 `test_buy_order_executor.py` 테스트로 검증 |
| 프론트엔드 `AppSettings` 타입 누락 | 낮음 | 5세션 `npm run build` (tsc 타입체크)로 검증 |

---

## 7. 완료 기준

### 7.1 각 구현 세션 (3, 4, 5세션)
- [ ] 코드 수정 완료 (설계서 + 본 태스크 파일 기준)
- [ ] pytest 해당 파일 통과
- [ ] 런타임 기동 — RuntimeWarning 0건, 에러 없음 (4세션까지)
- [ ] `npm run build` 성공 (5세션)
- [ ] `/api/settings` 응답 정상 (3세션까지)
- [ ] 잔존 프로세스 0건
- [ ] 커밋 (사용자 승인 후)
- [ ] HANDOVER.md 갱신

### 7.2 6세션 (통합 검증 + 정리)
- [ ] pytest 전체 — 기존 2935 passed 유지 + 신규 테스트 통과
- [ ] npm run build 성공
- [ ] 런타임 기동 정상
- [ ] `ARCHITECTURE.md` 리스크 매니저 섹션 갱신
- [ ] 계획서 2개 파일 삭제 (`architecture_risk_manager_extension_design.md`, `plan_risk_manager_extension.md`)
- [ ] 잔존 참조 grep 0건 (`check_sell_order_allowed` await 누락 — 역사적 문서 제외)
- [ ] 커밋 (사용자 승인 후)
- [ ] HANDOVER.md 갱신 — 다단계 작업 완료 기록
