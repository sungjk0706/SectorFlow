# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. 이전 세션의 완료 작업, 현재 상태, 다음 세션에서 이어서 진행할 항목을 기록.

---

## 직전 완료 작업

### F-06-a (F06-07/08): 공통 컴포넌트 dead code 제거 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. dead code 2건 제거.

**수정 파일 2개**:
- `frontend/src/components/common/ui-styles.ts` (599→564줄, -35줄): `createStockNameColumnWithSectorLookup` 함수 제거 + unused import 제거 (`hotStore`, `normalizeStockCode`)
- `frontend/src/components/common/setting-row.ts` (635→569줄, -66줄): `createWsStatusBadge` + `createWsToggleGroup` 함수 제거

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-07 | P16 | `createStockNameColumnWithSectorLookup` dead code — `createStockNameColumn`(사용처 7개)과 기능 중복, 정의 외 호출 0건. 제거 |
| F06-08 | P16 | `createWsStatusBadge` + `createWsToggleGroup` dead code — 정의 외 호출 0건. 제거. F06-09(증권사 색상/이름 중복 정의 P10) 동시 해결 (brokerColors/brokerNames 하드코딩 함께 제거) |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.40s exit 0. 잔여 참조 grep 0건 확인 (createStockNameColumnWithSectorLookup / createWsStatusBadge / createWsToggleGroup).

**화면 영향**: 없음. 제거된 함수는 어떤 페이지에서도 호출되지 않았으므로 UI 변화 없음.

## 다음 세션 작업

**잔여 F-06 (별도 세션 each)**:
- F06-06: `data-table.ts` `callbackRan` dead code 제거 (MEDIUM, 6곳)
- F06-01: `data-table.ts` 파일 분할 (1054줄 → ~500줄, fixed/virtual 모드 분리)
- F06-02: `setting-row.ts` 파일 분할 (569줄, 입력란 그룹 분리 검토)
- F06-03: `ui-styles.ts` 파일 분할 (564줄, 셀/컬럼 팩토리 분리 검토)
- F06-10: "보유주식" → "보유 종목" 용어 통일 (account-labels.ts + sell-position.ts 동시 수정 → F-03/F-05 범위와 연계 검토)
- F06-11, F06-12: LOW — 색상 상수화

---

## 직전 완료 작업 (이전 세션)

### F-05-c (F05-08): 수익 페이지 컬럼 정의 분할 (2026-07-22)

**세션**: F-05-c (P3 — 수익 페이지) 1단계. F05-08 (파일 길이) 해결.

**수정 파일 3개**:
- `frontend/src/pages/profit-columns.ts` (신규, 111줄): 컬럼 정의 3개 이동 (BUY_COLS/SELL_COLS/createDrilldownCols)
- `frontend/src/pages/profit-shared.ts` (598→493줄, -105줄): 컬럼 정의 3개 제거 + unused import 6개 제거 (ColumnDef/fmtComma/createStockNameColumn/createCodeCell/createNumberCell/hotStore)
- `frontend/src/pages/profit-detail.ts` (672→674줄, +2줄): import 분할 (BUY_COLS/SELL_COLS/createDrilldownCols → profit-columns, 나머지 → profit-shared 유지)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F05-08 | P24 | `profit-shared.ts` 598줄 (500줄 초과) → 493줄 달성. 컬럼 정의 3개를 신규 `profit-columns.ts` (111줄)로 분할 |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.07s exit 0 (profit-shared 13.84 kB, profit-detail 12.65 kB, profit-overview 21.94 kB). 잔여 참조 grep: profit-shared.ts에서 BUY_COLS/SELL_COLS/createDrilldownCols 0건 확인.

**화면 영향**: 없음. 수익 상세 페이지 매수/매도/드릴다운 테이블 표시 동일. 구조 개선만 수행.

## 다음 세션 작업

**잔여 (별도 세션 필요)**:
- `profit-overview.ts` 742줄 (500줄 초과) — `renderSectorStockPnl` 146줄 (135-280줄, P24 50줄의 2.9배) 분할 포함. 업종 그룹 헤더 + 종목 행 렌더 로직을 헬퍼로 분할.
- `profit-detail.ts` 674줄 (500줄 초과) — 별도 세션에서 추가 분할 검토.
- F05-07 "보유주식" → "보유 종목" 용어 통일 (account-labels.ts, sell-position.ts 전역 동시 수정 필요).

## 미해결 문제 (발견 즉시 기록)

### 백엔드 버그 (F-05-a 조사 중 발견)
- `backend/app/services/engine_account_rest.py:125-144` `build_account_snapshot_meta`가 응답 dict에서 `accumulated_investment`를 **누락**. 테스트모드에서 `state.account_snapshot["accumulated_investment"]`를 set한 후 `build_account_snapshot_meta`가 새 dict을 반환하므로 누락됨. 프론트엔드 F05-01은 `initial_deposit`만 사용하여 우회(테스트모드에서는 동일 값이므로 UI 변화 없음). 백엔드 수정은 별도 세션 필요.

## 작업 여력

F-05-c(F05-08) 완료 후 작업 여력: **충분**. 잔여 profit-overview.ts/profit-detail.ts 파일 길이 분할 및 renderSectorStockPnl 분할은 규칙 0-1 세션당 1단계 준수를 위해 별도 세션에서 진행 권장.

---

## 직전 완료 작업 (이전 세션)

### F-05-a: 수익 페이지 폴백/중복/비동기 안전 (7건 해결, 2026-07-22)

**세션**: F-05 (P3 — 수익 페이지) 전반부. F-05-b(후반)는 다음 세션에서 진행.

**수정 파일 3개**:
- `frontend/src/pages/profit-shared.ts` (569→598줄): 공통 함수 추가(`buildSectorDonutRows`, `filterTradeRows`), 폴백 제거(F05-01/02)
- `frontend/src/pages/profit-overview.ts` (718→698줄): 중복 함수 제거(`buildSectorDonutData`, `filterSellHistoryByDate`), catch 로깅(F05-03/04), 레이스 가드(F05-11)
- `frontend/src/pages/profit-detail.ts` (667→654줄): 중복 함수 제거(`filterRows`), catch 로깅(F05-03/04)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F05-01 | P20 | `accumulated_investment ?? initial_deposit ?? 0` 3단 폴백 → `initial_deposit ?? 0` (테스트모드 동일 값) |
| F05-02 | P20 | `orderable ?? Math.max(0, deposit - todayBuyAmt)` 폴백 → `orderable ?? 0` (백엔드 항상 전송) |
| F05-03 | P20 | save 함수 `catch { }` 빈 블록 → `console.warn` 로깅 |
| F05-04 | P20 | load 함수 `catch { return null }` → `console.warn` 로깅 |
| F05-05 | P10/P23 | `buildSectorDonutData` 중복 → `buildSectorDonutRows` shared SSOT, `buildSectorStockPnl`이 재사용 |
| F05-06 | P23 | `filterSellHistoryByDate`/`filterRows` 중복 → `filterTradeRows` shared SSOT |
| F05-11 | P19 | `applyDateRange` 레이스 가드 추가 (`_applyDateRangeSeq` 시퀀스) |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.06s exit 0, 잔여 참조 grep 0건. 브라우저 확인 권장.

---

## 직전 완료 작업 (이전 세션)

### F-04-e: P2 — stock-classification.ts + general-settings.ts 함수 분할 11건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/stock-classification.ts` (1617→1618줄, +1줄): F04-01 함수 4개 50줄 초과 분할 — **P24**
  - `buildTripleHeader` (71줄) → `buildHeaderLeft`/`buildHeaderCenter`/`buildHeaderRight` + 본문
  - `buildSectorManageCard` (280줄) → 여러 빌더로 분할 + **중복 퍼지 검색 로직 추출** (F04-16 해결)
  - `buildTripleCenter` (231줄) → 여러 빌더로 분할
  - `mount` (103줄) → `handleStockClassificationChange`/`handleStockDataChange`/`handleUiStoreChange` + 본문
- `frontend/src/pages/general-settings.ts` (1438→1390줄, 48줄 감소): F04-02/F04-04 함수 7개 50줄 초과 분할 — **P24**
  - `renderTimeSettingsTab` (217줄) → `buildBuyTimeRow`/`buildSellTimeRow`/`buildTimetableRow`(3행 중복 제거)/`buildConfirmedDownloadRow`/`buildFixedTimesBox`/`buildSubscribeMaxRow` + 본문
  - `renderAutoTradeTab` (328줄) → 14개 빌더로 분할 (`buildMasterToggleRow`, `buildAutoBuyRow`, `buildAutoSellRow`, `buildOrderTimeGuardRow`, `buildRiskManagerMasterRow`, `buildDailyLossRow` 등)
  - `renderTelegramTab` (87줄) → `buildTeleToggleRow`/`buildTeleInputRows`/`buildTeleSaveRow`/`buildTeleCommandTable` + 본문
  - `renderTestVirtualSection` (101줄) → `buildTestVirtualInputRow`/`buildTestVirtualSaveRow`/`buildTestVirtualInfoWrap`/`buildTestVirtualResetWrap` + 본문
  - `renderApiFields` (65줄) → `buildApiInputRows`/`buildApiSaveRow` + 본문
  - `syncFromSettings` (129줄) → `syncToggleInputRow`(공통 패턴 5회 반복 추출)/`syncRiskManager`/`syncTimetables`/`syncAutoTradeTab`/`syncTelegramTab`/`syncAccountTab`/`syncApiSettingsTab` + 본문 — **P23 DRY**
  - `mount` (67줄) → `buildTabPanels` + 본문

**해결 원칙**: P23 (일관성 — syncToggleInputRow 공통 패턴 추출, buildTimetableRow 3행 중복 제거), P24 (단순성 — 함수 50줄 이하)

**검증**:
- `npm run build` (tsc -b + vite build) — 성공 (2.20s, exit code 0)
- 분할된 11개 함수 모두 50줄 이하 확인 (Python 스크립트로 전수 검증)
- 빌드 에러 4건 발생 후 즉시 해결 (unused 모듈 변수 6개 제거: `timetableResetH/M`/`timetableWsH/M`/`timetableKrxH/M` — 읽히는 곳 없는 dead code, `buildTimetableRow` 타입 좁히기)

**화면 영향**: 없음. 업종분류 페이지 + 일반설정 페이지 모든 탭 표시/입력/저장 동작 동일. 구조 개선만 수행.

**부수적 정리**:
- F04-16 (P23) 해결: fuzzy 검색 로직 중복 → 공통 함수 추출 (F-04-a 보류 항목 해결)
- F04-02/F04-04 (P24) 해결: general-settings.ts 함수 7개 50줄 초과 → 모두 분할 (F-04-b 보류 항목 해결)
- F04-01/F04-03 (P24) 해결: stock-classification.ts 함수 4개 50줄 초과 → 모두 분할 (F-04-a 보류 항목 해결)
- unused 모듈 변수 6개 제거 (timetableResetH/M, timetableWsH/M, timetableKrxH/M — 쓰이지 않는 dead code)

**참고**: 파일 자체는 여전히 500줄 기준 초과 (stock-classification.ts 1618줄, general-settings.ts 1390줄). 본 세션은 "함수 분할"에 한정했으며, "파일 분할(멀티 파일)"은 별도 세션에서 다단계 워크플로우 적용 필요. 현재까지의 F-04 서브세션(a~e)은 모두 함수 단위 분할에 집중.

---

### F-04-d: P2 — sector-settings.ts 구조 분할 2건 (2026-07-22)

**수정 파일 1개**:
- `frontend/src/pages/sector-settings.ts` (503→466줄, 37줄 감소): F04-05 `mount()` 261줄 → 24줄, 7개 빌더 함수 + 2개 구독 함수 분할 (buildFilterSection/buildThresholdSection/buildReceiveProgressSection/buildCutoffSection/buildMaxScoreDisplay/buildBonusSection/buildMaxTargetsSection + startUiStoreSubscription/startHotStoreSubscription) — **P24**. F04-17 파일 503줄 → 466줄 (500줄 기준 해결) — **P24**. 가산점 슬라이더 3블록 중복 (각 13줄 × 3 = 39줄, 슬라이더 설정 완전 동일) → `createBonusSliderBlock` 헬퍼 1개 + 호출 3줄로 통합, 기존 `createBonusSliderRow` 제거 — **P23/P24**

**해결 원칙**: P23 (일관성 — buy-settings.ts 분할 패턴과 동일), P24 (단순성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (3.94s, exit code 0)
- 모든 함수 50줄 이하 (최장 buildReceiveProgressSection 39줄, createBonusSliderBlock 38줄)
- 파일 466줄 (500줄 기준 충족)
- 잔여 `createBonusSliderRow` grep 0건, `createDualLabelSlider` 직접 호출 1건(헬퍼 내)만

**화면 영향**: 없음. 업종순위 설정 패널 표시/입력/저장 동작 동일. 구조 개선만 수행.

**보류 항목 (F-04-d 범위외, 추후 세션)**:
- F-04-e (별도): stock-classification.ts + general-settings.ts 파일 분할 (구조 변경, 다단계 워크플로우 적용)

---

### F-04-c: P2 — 매수/매도 설정 페이지 buy-settings.ts + sell-settings.ts 4건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/buy-settings.ts` (425→452줄, +27줄): F04-12 `Number() || 기본값` 폴백 11건 → `??` (nullish coalescing). **가산점 점수 0 설정 후 새로고침 시 1.0으로 잘못 표시되는 버그 수정** (boost_high/order/program/trade_amount_score 4건). 나머지 7건(rise_pct/fall_pct/min_strength/max_daily_amt/max_stock_cnt/buy_amt/buy_interval_sec)도 동일 패턴으로 통일 — **P20/P21**. F04-06 `mount()` 233줄 → 5개 섹션 빌더 분할 (buildBuyBlockSection/buildBoostSection+buildBoostOrderBlock/buildBuyAmountSection/buildRebuySection/buildBuyIntervalSection), mount 본문 20줄 — **P24**. F04-07 `syncFromSettings` 92줄 → 5개 동기화 함수 분할 (syncBuyBlock/syncBoost/syncBuyAmount/syncRebuy/syncBuyInterval), 본문 13줄 — **P24**
- `frontend/src/pages/sell-settings.ts` (174→181줄, +7줄): F04-13 `Number() || 기본값` 폴백 5건 → `??` (일관성, 동작 버그 없음) — **P20**. F04-07 `mount()` 80줄 → 2개 섹션 빌더 분할 (buildSellTypeSection/buildSellIntervalSection), mount 본문 17줄 — **P24**

**해결 원칙**: P20 (폴백 금지), P21 (사용자 투명성 — 가산점 0 표시 버그), P24 (단순성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (2.05s, exit code 0)
- 잔여 `Number() ||` 폴백 grep 0건
- 모든 함수 50줄 이하 (최장 buildSellTypeSection 49줄)

**화면 영향**:
- 매수 가산점 점수 0 설정 시: 이전 화면 1.0 잘못 표시 → 이제 0 올바르게 표시 (버그 수정)
- 매수/매도 설정 페이지 표시/저장 동작: 동일 (구조 개선만, 사용자 동작 변화 없음)

**보류 항목 (F-04-c 범위외, 추후 세션)**:
- F04-14 (P23, INFO): 저장 호출 패턴 3종 혼재 (buy/sell: saveHelper.saveImmediate 미await / general: async/await saveSection / sector: autoSave 디바운스) — saveSection이 내부 try/catch로 reject하지 않으므로 안전. F-07 범위(settings-save.ts)와 연계 검토 권장
- F-04-e (별도): stock-classification.ts + general-settings.ts 파일 분할 (구조 변경, 다단계 워크플로우 적용)

---

### F-04-b: P2 — 설정 페이지 general-settings.ts + sector-settings.ts 4건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/general-settings.ts` (1453→1448줄, 5줄 감소): F04-20 `.then()` 패턴 12개 → async/await 통일 (handleMasterToggle, dailyLoss/Rate/Profit/ProfitRate/ConsecLoss Input onChange 5개 + onToggle 5개, subscribeMaxInput onChange) — **P23**. F04-21 구독/정리를 `startSettingsSubscription`/`destroySettingsPage` 표준 유틸로 전환 (buy-settings/sell-settings와 동일 패턴) — **P23**. F04-23 거래일 조회 실패 시 조용한 폴백 → 사용자 알림 토스트 추가 ("거래일 조회 실패 — 거래일로 간주하여 자동매매를 허용합니다") — **P20/P21**
- `frontend/src/pages/sector-settings.ts` (509→501줄, 8줄 감소): F04-22 `initSettingsPage`/`startSettingsSubscription`/`destroySettingsPage` 표준 유틸로 전환 + **onSync 콜백 누락 해결** (기존 `createAutoSaveHelper(settingsMgr)`는 onSync 없이 생성 → 저장 후 동기화 누락 버그) — **P23**

**해결 원칙**: P20 (폴백 금지), P21 (사용자 투명성), P23 (일관성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (1.94s, exit code 0)

**화면 영향**:
- 설정 저장 동작: 동일 (토글/입력 저장 방식 변함 없음)
- 거래일 조회 실패 시: 이전 화면 알림 없음 → 이제 "거래일 조회 실패" 토스트 표시 (자동매매는 여전히 거래일로 간주하여 허용)
- 업종순위 설정 저장 후: 이전 화면 갱신 누락 가능 → 이제 저장 후 즉시 갱신 (onSync 콜백 연결)

**보류 항목 (F-04-b 범위외, 추후 세션)**:
- F04-02/F04-04 (P24): general-settings.ts 파일 1448줄 / 함수 7개 50줄 초과 — 파일 분할은 별도 세션 필요 (구조 변경)
- F04-05 (P24): sector-settings.ts mount 함수 길이 — 분할 검토
- F04-06/F04-07 (P24): buy-settings/sell-settings 함수 길이 — 분할 검토
- F04-12/F04-13 (P20): buy-settings/sell-settings `Number() || 0` 폴백 — 사용자 설계 로직 판단 필요

---

### F-04-a: P2 — 설정 페이지 stock-classification.ts 5건 (2026-07-22)

**수정 파일 1개** (1617→1597줄, 20줄 감소):
- `frontend/src/pages/stock-classification.ts`: F04-08 `_testSetState` dead code 제거 (10줄, 사용처 없는 테스트 헬퍼) — **P16**. F04-09 전역 이벤트 리스너(`window mouseup`, `detailTableRef keydown`)를 명명된 핸들러로 변경 후 unmount 시 `removeEventListener` 제거 (메모리 누수 방지) — **P19**. F04-10 `_mounted` 플래그 추가, `onMoveStock` async 응답 후 store 업데이트 전 가드 (race condition 방지) — **P19**. F04-11 외부 미사용 export 9개 제거 (`parseBatchInput`, `resolveToken`, `getMoveSource`, `getMovableCount`, `createChip`, `addToStaging`, `removeFromStaging`, `clearStaging`, `buildMoveMessage` — 모두 파일 내부에서만 사용) — **P16/P24**. F04-19 제거된 코드 참조 주석 2건 정리 (`// import ... (removed)`, `// buildSchedulerCard removed.`) — **P23**

**해결 원칙**: P16 (살아있는 경로), P19 (비동기 누락/메모리 누수), P23 (주석 정리), P24 (단순성)

**검증**:
- `npm run build` (tsc -b + vite build) — 성공 (exit code 0)
- 타입 오류 없음, 빌드 산출물 정상 생성

**화면 영향**: 없음. 업종분류 페이지 표시/동작 동일. 구조 개선만 수행.

**보류 항목 (F-04-a 범위외, 추후 세션)**:
- F04-01/F04-03 (P24): stock-classification.ts 파일 1597줄 / 함수 4개 50줄 초과 (buildSectorManageCard 278줄, buildTripleCenter 231줄, mount 103줄, buildTripleHeader 71줄) — 파일 분할은 별도 세션 필요 (구조 변경)
- F04-15 (P10): 로컬 캐시/파생 상태 (cachedSectorStocksRef, cachedAllStocksMap, stockNameIndex, stagingSet, selectedStocks) — 성능 최적화 목적이므로 판단 필요
- F04-16 (P23): fuzzy 검색 로직 중복 (612-628줄, 684-694줄) — 공통 함수 추출 검토
- F04-18 (P21): 업종 삭제 시 사용자 명시적 알림 부재 — 경미

---

## 현재 진행 상황

### 아키텍처 전수 조사 진행률: 30/30 세션 완료 (100%, F-04-e 완료)

| 상태 | 세션 |
|------|------|
| 완료 | B-01~B-12, B-14~B-23, F-01, F-02, F-03, F-04 |
| 부분 완료 | B-13 (3건 해결, 5건 보류 LOW/INFO), F-04 (F-04-a 5건 + F-04-b 4건 + F-04-c 4건 + F-04-d 2건 + F-04-e 11건 해결, 잔여 파일 분할 별도) |
| 미시작 | F-05, F-06, F-07 |

**다음 세션**: F-05 (P3 — 수익 페이지 profit-overview.ts + profit-detail.ts + profit-shared.ts)

---

## 미해결 문제

### F-04-e 보류 항목 (F-04-e 범위외, 추후 세션)
- F04-01/F04-03 파일 분할 (P24): stock-classification.ts 1618줄 — 함수 분할은 완료, 파일 자체는 500줄 기준 초과. 멀티 파일 분할은 별도 세션 필요 (다단계 워크플로우)
- F04-02/F04-04 파일 분할 (P24): general-settings.ts 1390줄 — 함수 분할은 완료, 파일 자체는 500줄 기준 초과. 멀티 파일 분할은 별도 세션 필요 (다단계 워크플로우)

### F-04-d 보류 항목 (F-04-d 범위외, 추후 세션)
- ~~F-04-e (별도): stock-classification.ts + general-settings.ts 함수 분할~~ — **F-04-e 해결** (11건 함수 분할 완료, 파일 분할은 잔여)

### F-04-c 보류 항목 (F-04-c 범위외, 추후 세션)
- F04-14 (P23, INFO): 저장 호출 패턴 3종 혼재 (buy/sell: saveHelper.saveImmediate 미await / general: async/await saveSection / sector: autoSave 디바운스) — saveSection이 내부 try/catch로 reject하지 않으므로 안전. F-07 범위(settings-save.ts)와 연계 검토 권장
- ~~F-04-e (별도): stock-classification.ts + general-settings.ts 함수 분할~~ — **F-04-e 해결** (11건 함수 분할 완료)

### F-04-b 보류 항목 (F-04-b 범위외, 추후 세션)
- ~~F04-02/F04-04 (P24): general-settings.ts 함수 7개 50줄 초과~~ — **F-04-e 해결** (7개 함수 모두 분할, 파일 1448→1390줄)
- F04-06/F04-07 (P24): buy-settings/sell-settings 함수 길이 — 분할 검토
- F04-12/F04-13 (P20): buy-settings/sell-settings `Number() || 0` 폴백 — 사용자 설계 로직 판단 필요
- ~~F04-05 (P24): sector-settings.ts mount 함수 길이~~ — **F-04-d 해결** (mount 261→24줄)
- ~~F04-17 (P24): sector-settings.ts 파일 길이~~ — **F-04-d 해결** (503→466줄)

### F-04-a 보류 항목 (F-04-a 범위외, 추후 세션)
- ~~F04-01/F04-03 (P24): stock-classification.ts 함수 4개 50줄 초과~~ — **F-04-e 해결** (4개 함수 모두 분할)
- F04-15 (P10): 로컬 캐시/파생 상태 — 성능 최적화 목적이므로 판단 필요
- ~~F04-16 (P23): fuzzy 검색 로직 중복~~ — **F-04-e 해결** (공통 함수 추출)
- F04-18 (P21): 업종 삭제 시 사용자 명시적 알림 부재 — 경미

### F-03 보류 항목 (B그룹 4건, 추후 검토)
- F03-07 (P20/P22): sell-position.ts:59,73 — `sectorStock?.cur_price ?? p.cur_price` 폴백 (사용자 설계 로직, 규칙 0-5 적용 대상)
- F03-08 (P24): sector-stock.ts 653줄 — 500줄 기준 초과, 분할 시 별도 세션 필요
- F03-09 (P24): computeRows(115줄)/connectedCallback(263줄)/updateBadges(79줄)/mount(192줄) — 50줄 기준 초과
- F03-10 (P23): filterStocksBySearch가 페이지 파일에 정의, buy-target.ts 크로스 사용 — utils/ 이동 검토

### F-03 범위외 발견 (F-06 공통 컴포넌트 세션에서 처리)
- F03-11 (P16): card-header.ts:8-24 `createCardHeader` (margin 없는 버전) 사용처 없음, `createCardHeaderWithMargin`만 사용

### F-02 발견 경미 사항 (정보만 기록, 수정 여부 사용자 판단)
- **main.ts**: 주석 번호 중복 (이미 F-02에서 "6."→"7."로 정리 완료)
- **header.ts line 99**: `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` — 알 수 없는 장 페이즈를 '장마감' 스타일로 처리하는 폴백 (P20 경미 — 백엔드가 알려진 페이즈만 보내므로 실제 발생 가능성 낮음)

### B-13 보류 항목 (5건, LOW/INFO)
- B-13 부분 완료. 잔여 5건은 LOW/INFO 등급으로 보류 중.

---

## 다음 세션 인계 사항

1. **F-05 (P3 — 수익 페이지)** 부터 시작. F-04-e 완료 (stock-classification.ts + general-settings.ts 함수 11건 분할).
   - F-05 대상: `profit-overview.ts` (718줄) + `profit-detail.ts` (667줄) + `profit-shared.ts` (569줄) — 총 1954줄
   - F-04 잔여: stock-classification.ts (1618줄) / general-settings.ts (1390줄) 파일 자체 분할 — 별도 세션 (멀티 파일 분할, 다단계 워크플로우)
2. 대상 원칙: P5, P10, P16, P19, P22, P23, P24
3. `architecture_audit_tasks.md` 섹션 F-05 체크리스트 참조
4. 세션당 1단계 원칙 준수 (AGENTS.md 규칙 0-1)
5. F-03 보류 항목 4건 (F03-07~F03-10) 참조
