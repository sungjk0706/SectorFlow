# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. 이전 세션의 완료 작업, 현재 상태, 다음 세션에서 이어서 진행할 항목을 기록.

---

## 직전 완료 작업

### 문서 정리: audit 문서 최신화 + HANDOVER 미해결 문제 취소선 처리 (2026-07-22)

**세션**: 문서 정리 1단계. 코드 수정 없음 (문서만 업데이트).

**수정 파일 3개**:
- `HANDOVER.md` (197-200줄): "프론트엔드 — 용어 통일 잔존 (F06-10 범위 밖)" 미해결 문제 섹션에 취소선 + 해결 표시 추가. F-06-d 세션에서 이미 해결된 항목들을 문서에 반영 (잔여 "보유주식" 0건).
- `docs/architecture_audit_plan.md` (6곳): F-05/F-06 세션 섹션 파일 표 + 체크리스트 ☐→☑ 완료 표시. F05-01 백엔드 #3 해결 내역 추가. F05-07 보류→해결 (F-06-c/d). F05-08 잔여→완료 (파일 분할 완료). 세션 상태 표 + 진행률 (완료 24→26, 진행중 1→0, 미시작 5→4, 보류 2→1).
- `docs/architecture_audit_tasks.md` (5곳): 세션 현황 표 F-05/F-06 ☐→☑. 진행률 F-05/F-06/백엔드 #3 완료 반영. "잔여 6세션" → "잔여 4세션". F-05/F-06 세션 섹션 파일 [ ]→[x] + 체크리스트 [ ]→[x] + 검증 [ ]→[x].

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 문서 정리 | P21/P23 | audit 문서 2개가 구 버전 상태로 F-05/F-06을 미시작/진행중으로 표시 + HANDOVER 미해결 문제 섹션에 해결된 항목 취소선 누락. 실제 코드 상태(HANDOVER 최신)와 문서 불일치 해결. 잔여 보류 항목(B-13 5건, B21-01, F-03 4건, F-04 파일 분할, F-07)은 명확히 분리하여 추적 정보 보존. |

**검증**: 코드 수정 없음 (문서만 업데이트). 두 audit 파일 간 F-05/F-06 상태 일관성 확인 (모두 ☑ 완료, 진행률 수치 일치).

**화면 영향**: 없음. 문서 정리만 수행.

## 직전 완료 작업 (이전 세션)

### F-05-b: profit-detail.ts 파일 분할 (2026-07-22)

**세션**: F-05 (페이지 파일 분할) 1단계. P24 단순성 해결. F-05-a와 동일한 메인+re-export 패턴.

**수정 파일 4개**:
- `frontend/src/pages/profit-detail.ts` (메인): 674줄 → 166줄. `ProfitDetailState` 인터페이스 (모든 가변 상태를 단일 상태 객체로 관리 — P10 SSOT) + `createState()` 팩토리 + `mount`/`unmount` + `export default`. 분할 파일에서 사용하는 타입(`LowerTab`, `SelectedView`, `ProfitDetailState`) export. F-05-a 메인+re-export 패턴 준수.
- `frontend/src/pages/profit-detail-view.ts` (신규, 52줄): `PROFIT_DETAIL_VIEW_KEY`, `ProfitDetailViewState`, `loadProfitDetailView`, `saveProfitDetailView` 이관. 순수 이동.
- `frontend/src/pages/profit-detail-display.ts` (신규, 215줄): `applyCardStyle` + `updateStatCardSelection` + `updateCardSelection` + `updateDrilldownBtnStyle` + `setTabLabel` + `updateTabLabels` + `showDrilldown` + `filterByDate` + `filterByDateRange` + `updateStatistics` + `showTable` + `persistViewState` 이관. 모든 함수가 `state: ProfitDetailState` 인자를 받도록 시그니처만 변경, 로직 동일.
- `frontend/src/pages/profit-detail-mount.ts` (신규, 326줄): `buildSummaryRow` + `onDrilldownToggle` + `buildFilterRow` + `buildTabRow` + `buildTableContainer` + `buildStatRow` + `restoreInitialView` + `flushDirtyRender` + `subscribeProfitDetailStore` 이관. 모든 함수가 `state` 인자 사용.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F-05-b | P24 | profit-detail.ts 674줄 → 4개 파일 분할 (166/52/215/326줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (라우터 `./pages/profit-detail` 경로 + `export default { mount, unmount }` 시그니처). F-05-a 메인+re-export 패턴 준수 (상태 객체를 인자로 전달 — profit-overview 분할과 동일). |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.18s exit 0, `npx vitest run` 8 files / 116 tests passed (8.94s). 모든 파일 500줄 이하.

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 수익 상세 페이지의 모든 기능(요약 카드 당일/직전/당월/누적 손익, 드릴다운 당월 일별 요약, 매도/매수 탭, 날짜 범위 필터, 종목 검색, 통계 정보, 가상 스크롤 거래내역)이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-05-a: profit-overview.ts 파일 분할 + renderSectorStockPnl 함수 분할 (2026-07-22)

**세션**: F-05 (페이지 파일 분할) 1단계. P24 단순성 해결.

**수정 파일 4개**:
- `frontend/src/pages/profit-overview.ts` (메인): 742줄 → 175줄. `ProfitOverviewState` 인터페이스 (28개 가변 필드를 단일 상태 객체로 관리 — P10 SSOT) + `createState()` 팩토리 + `mount`/`unmount` + `export default`. 분할 파일에서 사용하는 타입을 export. F-06 메인+re-export 패턴 준수.
- `frontend/src/pages/profit-overview-date.ts` (신규, 62줄): `PROFIT_DATE_KEY`, `ProfitDateRange`, `loadProfitDateRange`, `saveProfitDateRange`, `defaultDateRange`, `initDateRange` 이관. 순수 이동.
- `frontend/src/pages/profit-overview-sector-pnl.ts` (신규, 219줄): `createAmountCell` (셀 헬퍼 — 헤더/행 공통, P23 일관성) + `createSectorHeader` (업종 헤더 5컬럼) + `createStockRow` (종목 행 5컬럼) + `renderSectorStockPnl` (orchestrator, 45줄 — 50줄 이하 달성) + `updateExpandToggleBtn` + `buildStockListSection` 이관. `renderSectorStockPnl` 146줄 → 5개 함수로 분할 (createAmountCell 25줄 + createSectorHeader 40줄 + createStockRow 35줄 + renderSectorStockPnl 45줄 + updateExpandToggleBtn 4줄).
- `frontend/src/pages/profit-overview-mount.ts` (신규, 377줄): `renderAccountVals`, `refreshFilteredViews`, `buildLeftColumn`, `buildAccountRows`, `buildAccountPanel`, `buildLowerSection`, `applyDateRange`, `buildProfitChart`, `buildDonutChart`, `flushRender`, `subscribeProfitOverviewStore` 이관. 순수 이동.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F-05-a | P24 | profit-overview.ts 742줄 → 4개 파일 분할 (175/62/219/377줄, 모두 500줄 이하). renderSectorStockPnl 146줄 → 5개 함수 분할 (최대 45줄, 모두 50줄 이하). 순수 이동(move) + 함수 분할만 수행, 동작 변경 없음. 외부 import 경로 유지 (라우터 `./pages/profit-overview` 경로 + `export default { mount, unmount }` 시그니처). F-06 메인+re-export 패턴 준수 (상태 객체를 인자로 전달 — data-table-fixed.ts의 options 인자 패턴과 동일). |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.73s exit 0, `npx vitest run` 8 files / 116 tests passed (8.09s). 모든 파일 500줄 이하, renderSectorStockPnl 45줄 (50줄 이하).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 수익현황 페이지의 모든 기능(일별 수익률 차트, 업종별 도넛 차트, 계좌 현황, 업종별 종목 수익, 전체보기 토글, 상세 분석 버튼)이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### 백엔드 #3: build_account_snapshot_meta accumulated_investment 누락 수정 (2026-07-22)

**세션**: 백엔드 정합성 버그 수정 1단계. P22 데이터 정합성 회복.

**수정 파일 2개**:
- `backend/app/services/engine_account_rest.py:131`: `build_account_snapshot_meta` 반환 dict에 `"accumulated_investment": account_snapshot.get("accumulated_investment")` 1줄 추가. 기존에 누락되어 호출부(engine_account.py:330)에서 `state.account_snapshot["accumulated_investment"]`를 set한 직후 반환 dict로 덮어쓰기(line 350)하면서 값이 사라지던 P22 위반 해결. 실전모드에서는 account_snapshot에 키가 없으므로 None 전달 (P20 폴백 금지 준수 — 0으로 덮지 않음).
- `backend/tests/test_engine_account_rest.py:288-302`: 새 테스트 2개 추가 — `test_accumulated_investment_passed_through` (테스트모드 값 전달 검증), `test_accumulated_investment_none_when_absent` (실전모드 None 전달 검증).

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 백엔드 #3 | P22 | `build_account_snapshot_meta`가 매번 새 dict 반환 시 `accumulated_investment` 키 누락. 호출부에서 set 후 덮어쓰기로 값 소실 → broadcast가 None 전송. 반환 dict에 키 추가로 단일 흐름 유지 (settlement_engine → state.account_snapshot → broadcast → 프론트엔드). |

**검증**: `py_compile` OK. `pytest test_engine_account_rest.py` 63/63 passed (새 테스트 2개 포함). `pytest test_engine_account.py + test_engine_account_notify.py + test_settlement_verification.py` 62/62 passed. 런타임 기동(`-W error::RuntimeWarning`) 정상 — 에러/Traceback/RuntimeWarning 없음, "누적투자금: 10,000,000원" 정상 로드. 잔존 프로세스 0건.

**화면 영향**: 현재 화면 변화 없음 (프론트엔드 F05-01이 `initial_deposit` 사용 중이며 테스트모드에서는 initial_deposit == accumulated_investment). 향후 프론트엔드가 `accumulated_investment` 직접 사용 시 정확한 누적 투자금 표시 가능.

## 직전 완료 작업 (이전 세션)

### F-06-g (F06-03): ui-styles.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-03 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/ui-styles.ts` (메인): 581줄 → 252줄. 상수(FONT_FAMILY/FONT_SIZE/FONT_WEIGHT/COLOR) + 색상함수(rateColor/pnlColor/strengthColor/hexToRgba) + 기호/포맷함수(changeArrow/fmtRate/fmtComma/fmtWon) + positionTooltip + CELL_BORDER/ROW_HEIGHT/ROW_HEIGHT_PX + 다크폼(createDarkInput/createDarkSelect) + 헬퍼(setDisabled/setDisplay) + `export * from` cells/columns re-export. ColumnDef/COLUMN_WIDTH import 제거 (columns 파일로 이동).
- `frontend/src/components/common/ui-styles-cells.ts` (신규, 211줄): createStockNameCell + applyCell(private 이동) + CELL_PADDING(private 이동) + createHeaderCell + 11개 createCell 함수 (Seq/Code/Price/Change/Rate/Amount/Strength/AvgAmount/Number/Pnl). 메인의 COLOR/FONT_*/rateColor/pnlColor/strengthColor/changeArrow/fmtComma/fmtRate import.
- `frontend/src/components/common/ui-styles-columns.ts` (신규, 148줄): 8개 makeColumn (Seq/Code/Price/Change/Rate/Strength/Amount/AvgAmount) + createStockNameColumn. data-table(ColumnDef) + table-config(COLUMN_WIDTH) + 메인(COLOR) + cells(create* 함수) import.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-03 | P24 | ui-styles.ts 581줄 → 3개 파일 분할 (252/211/148줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (41곳: 컴포넌트 18 + 페이지 14 + 레이아웃 3 + 기타 6). F-06-e(data-table)/F-06-f(setting-row)와 동일한 메인+re-export 패턴. |

**검증**: `npm run typecheck` exit 0, `npm run build` 735ms exit 0, `npx vitest run` 8 files / 116 tests passed (4.18s). 잔여 ui-styles-cells/columns 참조: 메인 re-export(2곳) + columns 내부 import(1곳)만 (외부 누출 없음).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 페이지의 테이블 셀·컬럼·다크폼이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-06-f (F06-02): setting-row.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-02 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/setting-row.ts` (메인): 569줄 → 168줄. 상수(INPUT_WIDTH, TEXT_INPUT_WIDTH) + 공통 유틸(focusNext, applyInputBase, createSpinButtons — inputs에서 import하도록 export 추가) + createSettingRow + createSettingField + createFixedValue + `export * from` inputs/controls re-export. 사용처가 controls로 이동한 setDisabled/FONT_SIZE import 제거.
- `frontend/src/components/common/setting-row-inputs.ts` (신규, 243줄): createNumInput, createMoneyInput, createTextInput, createSelect 이관. 메인의 유틸(focusNext, applyInputBase, createSpinButtons, TEXT_INPUT_WIDTH) import.
- `frontend/src/components/common/setting-row-controls.ts` (신규, 191줄): createToggleBtn, createRadioGroup, createToggleLabelControlsRow 이관. 메인의 createSettingRow + ui-styles(COLOR, FONT_SIZE, setDisabled) import.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-02 | P24 | setting-row.ts 569줄 → 3개 파일 분할 (168/243/191줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (4개 설정 페이지: general/sector/sell/buy-settings). F-06-e(data-table.ts)와 동일한 메인+re-export 패턴. |

**검증**: `npm run typecheck` exit 0, `npm run build` 982ms exit 0, `npx vitest run` 8 files / 116 tests passed (6.07s). 잔여 setting-row 참조: 메인 + inputs + controls(상호 import) + 4 설정 페이지(동일 경로 유지) + docs 역사적 로그.

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 설정 화면(일반/업종/매수/매도)의 입력란·토글·라디오·드롭다운이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-06-e (F06-01): data-table.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-01 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/data-table.ts` (메인): 1045줄 → 176줄. 타입/인터페이스 + 공통 유틸리티(triggerFlash, isGroupRow, scoreColor, createColumnWidthManager) + createDataTable 팩토리만 잔류. 유틸리티 함수에 export 추가 (모드 파일에서 import).
- `frontend/src/components/common/data-table-fixed.ts` (신규, 454줄): createFixedMode + CellWithPrevContent 이관.
- `frontend/src/components/common/data-table-virtual.ts` (신규, 454줄): createVirtualScrollMode + RowWithKey 이관.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-01 | P24 | data-table.ts 1045줄 → 3개 파일 분할 (176/454/454줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (9개 페이지 + ui-styles.ts + 테스트) |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.93s exit 0, `npx vitest run tests/components/data-table.ui.test.ts` 17/17 passed. 잔여 createFixedMode/createVirtualScrollMode 참조: 메인 + 각 모드 파일에서만 (외부 누출 없음).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 페이지가 동일하게 동작.

## 미해결 문제 (발견 즉시 기록)

### 백엔드 버그 (F-05-a 조사 중 발견) — 해결됨 (2026-07-22)
- ~~`backend/app/services/engine_account_rest.py:125-144` `build_account_snapshot_meta`가 응답 dict에서 `accumulated_investment`를 **누락**~~ → 해결 (백엔드 #3 세션에서 반환 dict에 키 추가).

## 다음 세션 작업

**잔여 F-06**: 없음 (F06-01/02/03 완료)

**잔여 F-05 (별도 세션 each)**:
- ~~`profit-overview.ts` 742줄 (500줄 초과) — `renderSectorStockPnl` 146줄 분할 포함~~ → 완료 (F-05-a 세션)
- ~~`profit-detail.ts` 674줄 (500줄 초과)~~ → 완료 (F-05-b 세션, 4개 파일 분할 166/52/215/326줄)

**잔여 F-05**: 없음 (F-05-a + F-05-b 완료)

**백엔드**: 없음 (accumulated_investment 누락 수정 완료)

**audit 문서에 기록된 잔여 항목 (사용자 지시 시 진행)**:
- B-13 보류 5건 (B13-03/04/06/07/08, LOW/INFO 등급) — `docs/architecture_audit_plan.md` 섹션 7 참조
- B21-01 보류 (암호화 폴백, 사용자 승인 대기 — 보안 동작 변화, UI 기준 설명 필요)
- F-03 보류 4건 (F03-07/08/09/10) — `docs/architecture_audit_tasks.md` F-03 섹션 참조
- F-04 잔여 파일 분할 (stock-classification.ts 1618줄, general-settings.ts 1390줄)
- F-07 미시작 (타입 및 유틸 5개 파일, 총 651줄)

---

## 직전 완료 작업 (이전 세션)

### F-06-d (F06-10 잔존): 용어 통일 마무리 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-10 잔존 2곳 해결 (프로젝트 전역 용어 통일 종료).

**수정 파일 2개**:
- `frontend/src/pages/profit-overview.ts:347`: UI 텍스트 "보유주식 평가금액 (" → "보유 종목 평가금액 (" (F06-10 잔존)
- `frontend/src/pages/profit-shared.ts:426`: 주석 "보유주식 평가금액/평가손익/수익률" → "보유 종목 평가금액/평가손익/수익률" (F06-10 잔존)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-10 잔존 | P23 | F06-10에서 account-labels.ts + sell-position.ts 완료 후 남은 2곳. UI 텍스트 1곳 + 주석 1곳. "보유주식" → "보유 종목" (용어 사전 준수). 프로젝트 전역 "보유주식" 잔존 0건 달성 |

**검증**: `npm run build` 612ms exit 0. 잔여 "보유주식" grep (frontend 전역): 0건 확인.

**화면 영향**:
- 수익 요약 페이지 계좌 현황 표: "보유주식 평가금액 (N종목)" → "보유 종목 평가금액 (N종목)"으로 표시 변경

## 직전 완료 작업 (이전 세션)

### F-06-c (F06-10/11/12): 용어 통일 + 색상 상수화 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-10 (P23 용어), F06-11/12 (P23 색상 상수화) 해결.

**수정 파일 5개**:
- `frontend/src/components/common/ui-styles.ts`: `hexToRgba(hex, alpha)` 공통 헬퍼 추가 (P23 공통 자산 — toast.ts + 향후 재사용)
- `frontend/src/components/common/toast.ts`: TYPE_CONFIG bg/border 8곳 하드코딩 rgba → `hexToRgba(COLOR.*, alpha)` (F06-12)
- `frontend/src/components/common/create-slider.ts`: 우측 트랙 기본색 `'#e9ecef'` → `COLOR.inactiveBg` (F06-11)
- `frontend/src/components/common/account-labels.ts`: "보유주식" → "보유 종목" 6곳 (F06-10)
- `frontend/src/pages/sell-position.ts`: "보유주식" → "보유 종목" 6곳 (주석 2 + 배지 라벨 4, F06-10)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-10 | P23 | UI 라벨 "보유주식" → "보유 종목" (용어 사전 준수). account-labels.ts 6곳 + sell-position.ts 6곳 |
| F06-11 | P23 | create-slider.ts 우측 트랙 하드코딩 `#e9ecef` → `COLOR.inactiveBg` (비활성 영역 의미 부합) |
| F06-12 | P23 | toast.ts TYPE_CONFIG 8곳 하드코딩 rgba → `hexToRgba(COLOR.*, alpha)` 공통 헬퍼 활용. 에러/정보 토스트 테두리 색상 톤이 표준 COLOR 팔레트로 통일 |

**검증**: `npm run build` 618ms exit 0. 잔여 "보유주식" grep: profit-overview.ts 1곳 + profit-shared.ts 1곳 (사용자 지시 범위 밖, 미해결 문제에 기록).

**화면 영향**:
- 계좌 현황 표 라벨: "보유주식 평가 금액" → "보유 종목 평가 금액" 등으로 표시 변경
- 보유 종목 페이지 요약 배지: "📊 보유주식 평가금액 합계" → "📊 보유 종목 평가금액 합계" 등
- 슬라이더 우측 트랙: 미세하게 더 진한 회색 (비활성 영역 의미 강화)
- 에러/정보 토스트 테두리: 기존 어두운 톤 → 표준 COLOR 톤 (약간 더 밝고 선명)

## 미해결 문제 (발견 즉시 기록)

### 프론트엔드 — 용어 통일 잔존 (F06-10 범위 밖) — 해결됨 (2026-07-22, F-06-d 세션)
- ~~`frontend/src/pages/profit-overview.ts:347` — `보유주식 평가금액 (` UI 텍스트 (P23 위반)~~ → 해결 ("보유 종목 평가금액 ("로 변경)
- ~~`frontend/src/pages/profit-shared.ts:426` — `// 보유주식 평가금액/...` 주석 (P23 위반)~~ → 해결 ("보유 종목 평가금액/..."로 변경)
- ~~사용자 지시(F06-10)가 account-labels.ts + sell-position.ts로 한정되었으므로 본 세션에서 제외. 다음 세션에서 profit-overview/profit-shared 동시 수정 권장.~~ → F-06-d 세션에서 해결 완료. 잔여 "보유주식" grep 0건 확인.

---

## 직전 완료 작업 (이전 세션)

### F-06-b (F06-06): data-table.ts callbackRan dead code 제거 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-06 (P16 dead code) 해결.

**수정 파일 1개**:
- `frontend/src/components/common/data-table.ts` (1053→1045줄, -8줄): `callbackRan` 플래그 6곳(고정 모드 3곳 + 가상 스크롤 모드 3곳) 제거 → `rafId = -1` 센티넬 방식으로 대체

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-06 | P16 | `callbackRan` dead code — 프로덕션(비동기 rAF)에서는 항상 `false`로 남아 조건문이 항상 true인 dead code. 단, 테스트 환경(`vitest.setup.ts` 동기 rAF mock)에서는 살아있는 경로. 근본 원인: 프로덕션-테스트 rAF 동작 불일치. 해결: `rafId = -1` 센티넬을 rAF 호출 전에 설정하여 양 환경에서 동일하게 작동. `callbackRan` 6곳 전부 제거. 테스트 코드는 변경 없음. |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.77s exit 0, `npx vitest run tests/components/data-table.ui.test.ts` 17 tests passed (380ms). 잔여 `callbackRan` 참조 grep 0건 확인.

**화면 영향**: 없음. 렌더링 스케줄링 내부 로직만 변경하며, 테이블 표시/업데이트/플래시 등 사용자에게 보이는 동작은 동일.

## 다음 세션 작업

**잔여 F-06 (별도 세션 each)**:
- F06-01: `data-table.ts` 파일 분할 (1045줄 → ~500줄, fixed/virtual 모드 분리)
- F06-02: `setting-row.ts` 파일 분할 (569줄, 입력란 그룹 분리 검토)
- F06-03: `ui-styles.ts` 파일 분할 (564줄, 셀/컬럼 팩토리 분리 검토)
- F06-10 잔존: profit-overview.ts:347 + profit-shared.ts:426 "보유주식" → "보유 종목" (미해결 문제 참조)

---

## 직전 완료 작업 (이전 세션)

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
- F06-01: `data-table.ts` 파일 분할 (1054줄 → ~500줄, fixed/virtual 모드 분리)
- F06-02: `setting-row.ts` 파일 분할 (569줄, 입력란 그룹 분리 검토)
- F06-03: `ui-styles.ts` 파일 분할 (564줄, 셀/컬럼 팩토리 분리 검토)
- F06-10 잔존: profit-overview.ts:347 + profit-shared.ts:426 "보유주식" → "보유 종목" (미해결 문제 참조)

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
- F05-07 "보유주식" → "보유 종목" 용어 통일 잔존: profit-overview.ts:347 + profit-shared.ts:426 (account-labels.ts, sell-position.ts는 F06-10에서 완료).

## 미해결 문제 (발견 즉시 기록)

### 백엔드 버그 (F-05-a 조사 중 발견) — 해결됨 (2026-07-22)
- ~~`backend/app/services/engine_account_rest.py:125-144` `build_account_snapshot_meta`가 응답 dict에서 `accumulated_investment`를 **누락**~~ → 해결 (백엔드 #3 세션에서 반환 dict에 키 추가).

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
