# 태스크 파일: 일반설정 탭 재분류 + 토글 이동 + 파일 분할

> **설계서**: `docs/architecture_general_settings_redesign_design.md`
> **단계 수**: 2단계 (각 단계별 별도 세션, 규칙 0-1)
> **관련 원칙**: P10(SSOT) · P21(사용자 투명성) · P23(일관성) · P24(단순성) · P25(격리된 실패)

---

## 심층 사전조사 결과 (규칙 0-2)

### 의존성
- **대상 파일**: `frontend/src/pages/general-settings.ts` (1443줄)
- **외부 참조**: 라우터에서 `import generalSettings from './pages/general-settings'` (export default { mount, unmount } 시그니처 유지 필수)
- **공통 자산 (변경 없음, 재사용)**:
  - `components/common/setting-row.ts`: createToggleBtn, createMoneyInput, createNumInput, createRadioGroup, createTextInput, createToggleLabelControlsRow, createSettingRow, createFixedValue, createSelect
  - `components/common/settings-common.ts`: sectionTitle, createDescText, parseHM, createTimeSlot, updateTimeSlotDisplay
  - `components/common/time-pair-input.ts`: createTimePairInput, TimePairInputHandle
  - `components/common/ui-styles.ts`: FONT_SIZE, FONT_WEIGHT, COLOR, createDarkInput, setDisabled
  - `components/common/card-title.ts`: createCardTitle
  - `components/common/button.ts`: createActionButton, createTabBar
  - `components/common/tag-chip.ts`: createTagChip, TagChipHandle
  - `components/common/dialog.ts`: showConfirmDialog, showAlertDialog, showCustomDialog
  - `components/common/toast.ts`: toastResult, showSaveToast
  - `utils/settings-page.ts`: startSettingsSubscription, destroySettingsPage
  - `settings.ts`: createSettingsManager, extractDirty, MASKED_FIELDS, SettingsManager
  - `stores/uiStore.ts`: uiStore, applyTestDataResetCompleted
  - `api/ws.ts`: notifyPageActive, notifyPageInactive
  - `api/client.ts`: api

### 영향 범위
- **프론트엔드**: `general-settings.ts` → 메인 축소 + 8개 파일 신설 (shared + 5개 탭 + Step 2에서 2개 탭 추가)
- **백엔드**: 변경 없음 (설정 키·API·WS 그대로)
- **테스트**: 프론트엔드 단위 테스트 없음 (typecheck + build로 검증)

### 아키텍처 원칙 부합
- **P10 (SSOT)**: `vals`는 shared 단일 소스. 각 탭은 참조만. 상태 배지는 uiStore 기반.
- **P16 (살아있는 경로)**: 모든 탭 파일은 메인에서 호출됨. dead code 없음.
- **P21 (사용자 투명성)**: 자동매매 탭 상태 배지로 토글 켜짐/꺼짐 표시.
- **P23 (일관성)**: 기존 `profit-*` 파일 분할 패턴 준수 (pages/ 폴더 평행 파일). 공통 자산 재사용. 용어 사전 준수.
- **P24 (단순성)**: 각 파일 500줄 이하. 토글·시간 통합 행으로 조작 단순화.
- **P25 (격리된 실패)**: 각 탭 렌더링 try/catch 격리, 실패 시 로깅 + 폴백 메시지.

### 기존 공통 자산 확인 (P23 사전 절차)
- 파일 분할 패턴: `profit-detail.ts` → `profit-detail-mount.ts`/`profit-detail-view.ts`/`profit-detail-display.ts` + `profit-shared.ts` (F-05-a/b 완료). 동일 패턴 준수.
- 상태 배지: 기존 `COLOR.up`/`COLOR.upBg` 표준 색상 재사용 (신규 색상 생성 금지).
- 토글: 기존 `createToggleBtn` 재사용.
- 탭 바: 기존 `createTabBar` 재사용.

---

## 사용자 결정 항목 (1세션에서 승인)

| 항목 | 결정 |
|---|---|
| 탭 재분류 구조 | 옵션 A — 자동매매(마스터+안전장치) / 시간 설정(시간+토글 함께) / 뉴스 설정 탭(신설) / 화면 설정 탭(신설) |
| 자동매매 탭 상태 표시 | 작은 배지 — '켜짐'/'꺼짐' 색상 배지 (클릭 불가) |
| 파일 분할 포함 | 함께 진행 — 탭 재분류 + 파일 분할 통합 워크플로우 |

---

## Step 1: 파일 분할 (순수 이동, 동작 변경 없음)

> **세션**: 3세션
> **목표**: 1443줄 단일 파일 → 7개 파일로 분할. UI 동작은 기존 그대로 (5개 탭 구조 유지).
> **패턴**: 기존 `profit-*` 분할과 동일 — 순수 이동, 동작 변경 없음.

### 1-1. 파일 생성 계획

| 파일 | 줄 수 (예상) | 이관 내용 |
|---|---|---|
| `general-settings-shared.ts` | ~160 | 모듈 상태(vals, settingsMgr, isTradingDay 등), GS 상수, BROKER_NAMES, 헬퍼(shouldForceOff, createHolidayBadge, updateHolidayBadges, scheduleTimetableSave) |
| `general-settings-time-settings-tab.ts` | ~200 | buildBuyTimeRow, buildSellTimeRow, buildTimetableRow, buildConfirmedDownloadRow, buildFixedTimesBox, buildSubscribeMaxRow, renderTimeSettingsTab |
| `general-settings-auto-trade-tab.ts` | ~360 | buildMasterToggleRow, buildAutoBuyRow, buildAutoSellRow, buildRiskManager*, buildUiFlashRow, renderAutoTradeTab, buildNewsKeywordsRow, buildNewsTtlRow, handleMasterToggle (기존 그대로 — 토글+뉴스+화면 포함) |
| `general-settings-telegram-tab.ts` | ~95 | TELE_STR_KEYS, TELE_LABELS, buildTele*, renderTelegramTab |
| `general-settings-account-tab.ts` | ~160 | renderAccountTab, handleTradeMode, syncTradeMode, buildTestVirtual*, renderTestVirtualSection |
| `general-settings-api-settings-tab.ts` | ~185 | renderApiSettingsTab, API_FIELDS_CONFIG, buildApi*, renderApiFields, refreshApiTabContent, handleBrokerChange, syncBrokerRadios |
| `general-settings.ts` (메인) | ~200 | imports, renderTabBar, refreshUI, syncToggleInputRow, syncRiskManager, syncTimetables, syncAutoTradeTab, syncTelegramTab, syncAccountTab, syncApiSettingsTab, syncFromSettings, buildTabPanels, mount, unmount, export default |

### 1-2. 상태 공유 방식

`general-settings-shared.ts`에서 모듈 상태를 export:
```typescript
export let settingsMgr: SettingsManager | null = null
export let vals: Record<string, unknown> = {}
export let isTradingDay = true
// ... 기타 모듈 상태
export const GS = { ... } as const
export function shouldForceOff(): boolean { ... }
export function createHolidayBadge(): HTMLElement { ... }
// ...
```

각 탭 파일은 `shared.ts`에서 import하여 사용. 메인 파일에서 mount 시 `settingsMgr`/`vals` 등을 초기화.

> **주의**: `let` 변수를 export하면 재할당 시 import 측에서 갱신되지 않는 TS 한계. 대안:
> - **옵션 A (채택)**: 상태를 객체로 래핑 (`export const state = { settingsMgr: null, vals: {} }`). 각 탭은 `state.settingsMgr`로 접근. 재할당 시 `state.settingsMgr = ...` (객체 속성 변경은 갱신됨).
> - 옵션 B: 각 탭 파일에서 setter 함수 export. 복잡도 증가.
> - 옵션 C: 모듈 상태를 각 탭 파일에 분산. P10 위반 (vals 중복).

### 1-3. 구현 순서

1. `general-settings-shared.ts` 생성 — 모듈 상태를 `state` 객체로 래핑, GS/BROKER_NAMES/헬퍼 export
2. `general-settings-time-settings-tab.ts` 생성 — 시간 설정 탭 함수 이관
3. `general-settings-auto-trade-tab.ts` 생성 — 자동매매 탭 함수 이관 (기존 그대로)
4. `general-settings-telegram-tab.ts` 생성 — 텔레그램 탭 함수 이관
5. `general-settings-account-tab.ts` 생성 — 투자모드 탭 함수 이관
6. `general-settings-api-settings-tab.ts` 생성 — API 설정 탭 함수 이관
7. `general-settings.ts` 재작성 — 탭 바, refreshUI, syncFromSettings, mount/unmount만. 각 탭 모듈 import하여 호출.
8. 각 탭 파일의 모듈 상태 참조를 `state.xxx`로 변경 (shared에서 import)
9. syncFromSettings의 각 탭별 sync 함수를 해당 탭 파일로 이관 (또는 메인에 유지 — P24 검토)

### 1-4. 검증

- `npm run typecheck` — exit 0
- `npm run build` — exit 0
- 브라우저: 5개 탭 전환, 모든 설정 토글/입력 동작 기존과 동일 확인
- **P16 확인**: 모든 탭 파일이 메인에서 호출됨 (dead code 없음)
- **P10 확인**: vals 단일 소스 (shared state 객체)
- **커밋**: "refactor(frontend): general-settings.ts 파일 분할 (F-04, P24) — 순수 이동, 동작 변경 없음"

---

## Step 2: UI 변경 — 토글 이동 + 배지 + 탭 신설 (5→7개 탭)

> **세션**: 4세션
> **목표**: 자동매수/매도 토글을 시간 설정 탭으로 이동, 자동매매 탭에 상태 배지 추가, 뉴스/화면 설정 탭 신설.
> **핵심 로직 변경 (규칙 0-4)**: 자동매수/매도 토글 위치 변경. 매매 로직 자체는 변경 없음 (설정 키·저장 로직 동일).

### 2-1. 변경 내용

#### 2-1-1. 시간 설정 탭 — 토글 통합 행
- `buildBuyTimeRow`에 자동매수 토글 추가 (기존 `buildAutoBuyRow` 로직 이관)
- `buildSellTimeRow`에 자동매도 토글 추가 (기존 `buildAutoSellRow` 로직 이관)
- 행 구조: `[라벨] [시간쌍 입력] [토글]`
- 토글 OFF 시에도 시간 입력 활성화 유지 (현행 설계서 2-1 유지)

#### 2-1-2. 자동매매 탭 — 상태 배지 + 섹션 제거
- `buildAutoBuyRow`/`buildAutoSellRow` 제거 → 상태 배지 행으로 교체
- 배지: `auto_buy_on`/`auto_sell_on` 값 기반 '켜짐'/'꺼짐' 표시 (클릭 불가)
- 배지 색상: 켜짐=`COLOR.up`/`COLOR.upBg`, 꺼짐=중립 회색 (기존 표준 색상 재사용)
- `buildUiFlashRow` + 화면 표시 섹션 제거 → 화면 설정 탭으로 이동
- `buildNewsKeywordsRow`/`buildNewsTtlRow` + 뉴스 설정 섹션 제거 → 뉴스 설정 탭으로 이동

#### 2-1-3. 뉴스 설정 탭 신설
- `general-settings-news-settings-tab.ts` 생성 (~60줄)
- `buildNewsKeywordsRow`, `buildNewsTtlRow` 이관
- sectionTitle('실시간 뉴스 설정') + 설명 문구

#### 2-1-4. 화면 설정 탭 신설
- `general-settings-display-settings-tab.ts` 생성 (~30줄)
- `buildUiFlashRow` 이관
- sectionTitle('화면 표시') + 설명 문구

#### 2-1-5. 메인 파일 — 탭 구조 5→7개
- TabId 타입에 `'news-settings'`/`'display-settings'` 추가
- renderTabBar tabs 배열에 뉴스 설정/화면 설정 탭 추가 (순서: 자동매매 → 시간 설정 → 뉴스 설정 → 화면 설정 → 투자모드 → API 설정 → 텔레그램)
- buildTabPanels에 뉴스/화면 탭 패널 추가
- syncFromSettings에 syncNewsSettingsTab/syncDisplaySettingsTab 추가 (또는 기존 syncAutoTradeTab에서 분리)

### 2-2. syncFromSettings 분할

기존 `syncAutoTradeTab`이 자동매매+시간+뉴스+화면+구독한도를 모두 처리. Step 2에서 탭별로 분산:
- `syncAutoTradeTab`: 마스터 + 배지 + 안전장치만
- `syncTimeSettingsTab`: 시간 + 토글 + 타임테이블 + 구독한도
- `syncNewsSettingsTab`: 키워드 칩 + TTL
- `syncDisplaySettingsTab`: 플래시 토글

### 2-3. 구현 순서

1. `general-settings-news-settings-tab.ts` 생성 — 뉴스 함수 이관 + render/sync 함수
2. `general-settings-display-settings-tab.ts` 생성 — 화면 함수 이관 + render/sync 함수
3. `general-settings-time-settings-tab.ts` 수정 — 토글 통합 행 추가 + sync 함수 추가
4. `general-settings-auto-trade-tab.ts` 수정 — 토글 제거 → 배지 추가, 뉴스/화면 섹션 제거, sync 함수 수정
5. `general-settings.ts` 수정 — TabId 7개, 탭 바 7개, buildTabPanels 7개, syncFromSettings 분할
6. `general-settings-shared.ts` 수정 — 배지 관련 상태 추가 (필요 시)

### 2-4. 검증

- `npm run typecheck` — exit 0
- `npm run build` — exit 0
- **브라우저 확인 (P21 필수)**:
  1. 7개 탭 전환 정상
  2. 시간 설정 탭: 자동매수/매도 토글+시간이 한 행에서 조작 가능
  3. 시간 설정 탭에서 자동매수 토글 OFF → 자동매매 탭 배지가 '꺼짐'으로 변경 (P21)
  4. 시간 설정 탭에서 자동매수 토글 ON → 자동매매 탭 배지가 '켜짐'으로 변경 (P21)
  5. 뉴스 설정 탭: 키워드 칩 + TTL 독립 동작
  6. 화면 설정 탭: 플래시 효과 토글 독립 동작
  7. 자동매매 탭: 마스터 스위치 + 안전장치만 표시 (뉴스/화면 없음)
- **커밋**: "feat(frontend): 일반설정 탭 재분류 + 토글 이동 + 상태 배지 (P21/P24) — 5→7개 탭"

---

## 완료 후: 계획서 파일 삭제 (규칙 11)

Step 2 완료 후 최종 커밋 시:
- `docs/architecture_general_settings_redesign_design.md` 삭제
- `docs/plan_general_settings_redesign.md` 삭제 (본 파일)
- HANDOVER.md 세션 개요/다음 세션 진행 대기에서 참조 경로 제거 (P10 SSOT)

---

## P25 격리된 실패 적용

- 각 탭 렌더링 시 try/catch로 격리:
  ```typescript
  try { renderAutoTradeTab(panel) }
  catch (e) { logger?.error('자동매매 탭 렌더링 실패', e); panel.textContent = '탭 로드 실패' }
  ```
- 단, 기존 코드에 try/catch가 없으므로 Step 1에서는 기존 패턴 유지 (순수 이동). Step 2에서 P25 격리 추가 검토 (별도 태스크가 아닌 본 워크플로우 범위).
- **주의**: P25 격리 추가는 선택 사항 (기존 profit-* 분할에도 try/catch 없음). 강제 아님. 단, 실패 시 silent pass 금지 (P20).
