// frontend/src/pages/general-settings.ts
// 일반설정 — Vanilla TS PageModule
// SettingsTabContainer.tsx + TelegramSection + AccountManageSection + TestVirtualSection 통합

import { uiStore, applyTestDataResetCompleted } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingsManager, extractDirty, MASKED_FIELDS, type SettingsManager } from '../settings'
import { startSettingsSubscription, destroySettingsPage } from '../utils/settings-page'
import { createToggleBtn, createMoneyInput, createTextInput, createRadioGroup, createNumInput, createToggleLabelControlsRow, focusNext } from '../components/common/setting-row'
import { toastResult, showSaveToast } from '../components/common/toast'
import { createDataTable, type ColumnDef } from '../components/common/data-table'
import { api } from '../api/client'
import { parseHM, sectionTitle, createDescText, createTimeSlot, updateTimeSlotDisplay } from '../components/common/settings-common'
import { createTimePairInput, type TimePairInputHandle } from '../components/common/time-pair-input'
import { FONT_SIZE, FONT_WEIGHT, createDarkInput, COLOR, setDisabled } from '../components/common/ui-styles'
import { showConfirmDialog, showAlertDialog, showCustomDialog } from '../components/common/dialog'
import { createCardTitle } from '../components/common/card-title'
import { createActionButton, createTabBar } from '../components/common/button'
import type { AppSettings } from '../types'

type TabId = 'auto-trade' | 'time-settings' | 'telegram' | 'account-manage' | 'api-settings'

// 일반설정 페이지 전용 스타일 상수 (공유 FONT_SIZE와 분리)
const GS = {
  label: FONT_SIZE.settingsLabel,   // 토글/행 라벨 (FONT_SIZE.settingsLabel = 14px)
  input: '13px',   // 입력박스 폰트
  rowPad: '10px 0', // 행 상하 패딩
  inputPad: '6px 10px', // 입력박스 패딩
  btnPad: '6px 20px',   // 저장/액션 버튼 패딩
  rowBorder: '1px solid ' + COLOR.borderLight,    // 설정 행 구분선
  saveMargin: '12px 0 0',         // 저장 버튼 상단 마진
} as const

/* ── 모듈 상태 ── */
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let vals: Record<string, unknown> = {}
let isTradingDay = true
let tradingDayLoading = true

// 탭 상태
let activeTab: TabId = 'auto-trade'
let tabBar: HTMLElement | null = null
let tabBarHandle: ReturnType<typeof createTabBar> | null = null
let tabContent: HTMLElement | null = null
let rootEl: HTMLElement | null = null
let tabPanels: Record<TabId, HTMLElement> | null = null

// 자동매매 탭 참조
let masterToggle: ReturnType<typeof createToggleBtn> | null = null
let autoBuyToggle: ReturnType<typeof createToggleBtn> | null = null
let buyTimeHandle: TimePairInputHandle | null = null
let autoSellToggle: ReturnType<typeof createToggleBtn> | null = null
let sellTimeHandle: TimePairInputHandle | null = null
let holidayBadgeEls: HTMLElement[] = []
let uiFlashToggle: ReturnType<typeof createToggleBtn> | null = null

// 매매 안전장치 참조 (전역매매설정 섹션)
let riskManagerToggle: ReturnType<typeof createToggleBtn> | null = null
let riskManagerChildren: HTMLElement | null = null
let dailyLossToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyLossInput: ReturnType<typeof createMoneyInput> | null = null
let dailyLossControls: HTMLElement | null = null
let dailyLossRateToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyLossRateInput: ReturnType<typeof createNumInput> | null = null
let dailyLossRateControls: HTMLElement | null = null
let dailyProfitToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyProfitInput: ReturnType<typeof createMoneyInput> | null = null
let dailyProfitControls: HTMLElement | null = null
let dailyProfitRateToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyProfitRateInput: ReturnType<typeof createNumInput> | null = null
let dailyProfitRateControls: HTMLElement | null = null
let consecLossToggle: ReturnType<typeof createToggleBtn> | null = null
let consecLossInput: ReturnType<typeof createNumInput> | null = null
let consecLossControls: HTMLElement | null = null
let riskBlockBuyToggle: ReturnType<typeof createToggleBtn> | null = null
let riskBlockSellToggle: ReturnType<typeof createToggleBtn> | null = null

// 확정 시세 다운로드 시간 (단일 슬롯) + 자동다운로드 토글
let confirmedDlSlot: HTMLElement | null = null
let confirmedDlToggle: ReturnType<typeof createToggleBtn> | null = null
let confirmedDlH = '20', confirmedDlM = '40'

// 장 시작 전 사전 준비 시간 (타임테이블 사용자 조정 3개 슬롯)
// 백엔드 키: timetable.realtime_reset / timetable.ws_prestart / timetable.krx_pre_subscribe
// 거래소 고정 7개 시간(08:00~20:00)은 코드 상수로 백엔드에 유지 → UI에는 참고 표시만.
let timetableResetSlot: HTMLElement | null = null
let timetableWsSlot: HTMLElement | null = null
let timetableKrxSlot: HTMLElement | null = null
let savingTimetable = false

// 구독 한도 (종목 동시 구독 최대 개수, 기본 200, 범위 1~1000)
let subscribeMaxInput: ReturnType<typeof createNumInput> | null = null

// 텔레그램 탭 참조
let teleToggle: ReturnType<typeof createToggleBtn> | null = null
let teleInputs: Record<string, HTMLInputElement> = {}

// 계정관리 탭 참조
let tradeModeRadioGroup: ReturnType<typeof createRadioGroup> | null = null
let testVirtualSection: HTMLElement | null = null
let depositInput: ReturnType<typeof createMoneyInput> | null = null
let depositDisplay: HTMLElement | null = null

// API 설정 탭 참조
let apiKeyInputs: Record<string, HTMLInputElement> = {}
let brokerRadioGroup: ReturnType<typeof createRadioGroup> | null = null
let activeApiTab: 'kiwoom' | 'ls' = 'kiwoom'
let apiTabButtons: Record<string, HTMLElement> = {}
let brokerSaving = false

// 증권사 코드 → 표시명 (라디오 items 라벨과 SSOT 일치)
const BROKER_NAMES: Record<string, string> = { kiwoom: '키움증권', ls: 'LS증권' }

/* ── 헬퍼 ── */
function shouldForceOff(): boolean {
  return !tradingDayLoading && !isTradingDay
}

function createHolidayBadge(): HTMLElement {
  const span = document.createElement('span')
  Object.assign(span.style, { fontSize: FONT_SIZE.chip, color: COLOR.up, background: COLOR.upBg, borderRadius: '4px', padding: '1px 6px', marginLeft: '6px', fontWeight: FONT_WEIGHT.normal, display: 'none' })
  span.textContent = '비거래일'
  holidayBadgeEls.push(span)
  return span
}

function updateHolidayBadges(): void {
  const show = shouldForceOff()
  for (const el of holidayBadgeEls) el.style.display = show ? 'inline' : 'none'
}

// 타임테이블 4개 키 저장 — 변경된 키만 전송 (P10 SSOT, P24 단순성)
// 백엔드 _validate_timetable_order()가 나머지 키를 DB에서 보충해 순서 검증
// 422 응답 시 api/client.ts가 detail 필드 추출 → toastResult가 검증 에러 메시지 토스트 (P21)
function scheduleTimetableSave(key: 'timetable.realtime_reset' | 'timetable.ws_prestart' | 'timetable.krx_pre_subscribe' | 'timetable.confirmed_download', newVal: string): void {
  if (!settingsMgr) return
  if (savingTimetable) return
  savingTimetable = true
  const run = async (): Promise<void> => {
    const serverVal = String(vals[key] ?? '')
    if (newVal !== serverVal) {
      const dirty: Record<string, unknown> = { [key]: newVal }
      const res = await settingsMgr!.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(vals, dirty)
    }
    savingTimetable = false
  }
  run()
}

/* ── 탭 렌더링 ── */
function renderTabBar(): HTMLElement {
  const bar = document.createElement('div')
  Object.assign(bar.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid ' + COLOR.borderDark, marginBottom: '12px' })

  const tabs: { id: TabId; label: string }[] = [
    { id: 'auto-trade', label: '자동매매' },
    { id: 'time-settings', label: '시간 설정' },
    { id: 'account-manage', label: '투자모드' },
    { id: 'api-settings', label: 'API 설정' },
    { id: 'telegram', label: '텔레그램' },
  ]

  tabBarHandle = createTabBar({
    tabs,
    activeId: activeTab,
    onChange: (id) => { activeTab = id as TabId; refreshUI() },
    fontSize: FONT_SIZE.tab,
    padding: '8px 16px',
  })
  bar.appendChild(tabBarHandle.el)

  return bar
}

function refreshUI(): void {
  if (!rootEl || !tabContent || !tabPanels) return
  // 탭 바 활성 상태 업데이트 (DOM 재생성 없음)
  if (tabBarHandle) tabBarHandle.setActive(activeTab)

  // 탭 패널 display 토글 (DOM 재생성 없음)
  for (const [id, panel] of Object.entries(tabPanels) as [TabId, HTMLElement][]) {
    panel.style.display = id === activeTab ? '' : 'none'
  }

  const s = settingsMgr?.getSettings()
  if (s) syncFromSettings(s)
}

/* ── 시간 설정 탭 ── */
// Step 1 골조 + Step 2 자동매수/매도 시간쌍 이동 + Step 3 사전 준비 시간·거래소 고정 시간 이동 + Step 4 1일봉 다운로드 이동.
// 토글 OFF 시에도 시간 입력 활성화 유지 (설계서 2-1, P24 탭 간 의존성 최소화, P21 안내 문구로 보완).
function buildBuyTimeRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매수 시간'
  row.appendChild(label)
  const buyStart = String(vals.buy_time_start ?? '09:00')
  const buyEnd = String(vals.buy_time_end ?? '15:00')
  const { el: tpWrap, handle } = createTimePairInput(buyStart, buyEnd, (s, e) => {
    if (settingsMgr) {
      const dirty: Record<string, unknown> = {}
      if (s !== vals.buy_time_start) dirty.buy_time_start = s
      if (e !== vals.buy_time_end) dirty.buy_time_end = e
      if (Object.keys(dirty).length > 0) {
        settingsMgr.saveSection(dirty).then(toastResult)
        Object.assign(vals, dirty)
      }
    }
  })
  buyTimeHandle = handle
  row.appendChild(tpWrap)
  return row
}

function buildSellTimeRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매도 시간'
  row.appendChild(label)
  const sellStart = String(vals.sell_time_start ?? '09:00')
  const sellEnd = String(vals.sell_time_end ?? '15:00')
  const { el: tpWrap, handle } = createTimePairInput(sellStart, sellEnd, (s, e) => {
    if (settingsMgr) {
      const dirty: Record<string, unknown> = {}
      if (s !== vals.sell_time_start) dirty.sell_time_start = s
      if (e !== vals.sell_time_end) dirty.sell_time_end = e
      if (Object.keys(dirty).length > 0) {
        settingsMgr.saveSection(dirty).then(toastResult)
        Object.assign(vals, dirty)
      }
    }
  })
  sellTimeHandle = handle
  row.appendChild(tpWrap)
  return row
}

function buildTimetableRow(labelText: string, key: 'timetable.realtime_reset' | 'timetable.ws_prestart' | 'timetable.krx_pre_subscribe', defaultTime: string): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = labelText
  row.appendChild(label)
  const [h, m] = parseHM(String(vals[key] ?? defaultTime))
  const slot = createTimeSlot(h, m, (nh, nm) => {
    updateTimeSlotDisplay(slot, nh, nm)
    scheduleTimetableSave(key, `${nh}:${nm}`)
  })
  row.appendChild(slot)
  // 모듈 상태 업데이트 (키별)
  if (key === 'timetable.realtime_reset') { timetableResetSlot = slot }
  else if (key === 'timetable.ws_prestart') { timetableWsSlot = slot }
  else if (key === 'timetable.krx_pre_subscribe') { timetableKrxSlot = slot }
  return row
}

function buildConfirmedDownloadRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal, whiteSpace: 'nowrap' })
  label.textContent = '1일봉차트 자동다운로드'
  row.appendChild(label)

  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;gap:10px;'

  const [cdh, cdm] = parseHM(String(vals['timetable.confirmed_download'] ?? '20:40'))
  confirmedDlH = cdh; confirmedDlM = cdm
  confirmedDlSlot = createTimeSlot(confirmedDlH, confirmedDlM, (h, m) => {
    confirmedDlH = h; confirmedDlM = m; updateTimeSlotDisplay(confirmedDlSlot!, h, m)
    scheduleTimetableSave('timetable.confirmed_download', `${h}:${m}`)
  })
  right.appendChild(confirmedDlSlot)

  const dlOn = vals.scheduler_market_close_on !== false
  confirmedDlToggle = createToggleBtn({ on: dlOn, onClick: async () => {
    const next = !confirmedDlToggle!.isOn()
    confirmedDlToggle!.setOn(next)
    setDisabled(confirmedDlSlot!, !next)
    vals.scheduler_market_close_on = next
    const res = await settingsMgr!.saveSection({ scheduler_market_close_on: next })
    toastResult(res)
    if (!res.ok) {
      vals.scheduler_market_close_on = !next
      confirmedDlToggle!.setOn(!next)
      setDisabled(confirmedDlSlot!, next)
    }
  }})
  right.appendChild(confirmedDlToggle.el)
  row.appendChild(right)
  setDisabled(confirmedDlSlot, !dlOn)
  return row
}

function buildFixedTimesBox(): HTMLElement {
  const fixedTimes: Array<[string, string]> = [
    ['08:00', 'NXT 프리마켓 시작'],
    ['09:00', '정규장 시작'],
    ['15:20', '정규장 종료'],
    ['15:30', '종가 동시호가 종료'],
    ['15:40', 'NXT 애프터마켓 시작'],
    ['18:00', '애프터마켓 지속 전환'],
    ['20:00', '장마감'],
  ]
  const box = document.createElement('div')
  Object.assign(box.style, {
    margin: '8px 0 0', padding: '8px 10px',
    background: COLOR.surface, border: '1px solid ' + COLOR.borderLight,
    borderRadius: '6px', fontSize: FONT_SIZE.desc, color: COLOR.tertiary,
  })
  const title = document.createElement('div')
  Object.assign(title.style, { fontWeight: FONT_WEIGHT.normal, color: COLOR.neutral, marginBottom: '4px' })
  title.textContent = '참고: 거래소 고정 시간 (변경 불가)'
  box.appendChild(title)
  for (const [t, label] of fixedTimes) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', gap: '8px', fontVariantNumeric: 'tabular-nums' })
    const time = document.createElement('span')
    Object.assign(time.style, { color: COLOR.neutral, minWidth: '48px' })
    time.textContent = t
    const desc = document.createElement('span')
    desc.textContent = label
    row.appendChild(time)
    row.appendChild(desc)
    box.appendChild(row)
  }
  return box
}

function buildSubscribeMaxRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '종목 동시 구독 최대 개수'
  row.appendChild(label)

  // 백엔드 settings_store.py가 1~1000 외 값 저장 차단 (422) — UI clamp와 이중 방어
  const initMax = Number(vals['subscribe.max_0b_count'] ?? 200) || 200
  subscribeMaxInput = createNumInput({
    value: initMax,
    min: 1, max: 1000, step: 10,
    name: 'subscribe.max_0b_count',
    onChange: async (v) => {
      if (!settingsMgr) return
      const dirty: Record<string, unknown> = { 'subscribe.max_0b_count': v }
      const res = await settingsMgr.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(vals, dirty)
    },
  })
  row.appendChild(subscribeMaxInput.el)
  return row
}

function renderTimeSettingsTab(container: HTMLElement): void {
  container.appendChild(buildBuyTimeRow())
  container.appendChild(buildSellTimeRow())
  container.appendChild(createDescText('자동매수/매도가 꺼져 있어도 시간을 미리 설정할 수 있습니다. "자동매매" 탭에서 자동매수/매도를 켜면 이 시간에 맞춰 실행됩니다.'))

  // 사전 준비 시간 설정 (타임테이블 사용자 조정 3개) — P21 투명성
  container.appendChild(sectionTitle('사전 준비 시간 설정'))
  container.appendChild(createDescText('너무 늦으면 실시간 데이터가 누락될 수 있습니다.'))
  container.appendChild(buildTimetableRow('실시간 데이터 필드 초기화', 'timetable.realtime_reset', '07:58'))
  container.appendChild(createDescText('장 시작 전 필드를 비워 새 데이터를 받을 준비를 합니다'))
  container.appendChild(buildTimetableRow('NXT 종목 구독 신청', 'timetable.ws_prestart', '07:59'))
  container.appendChild(createDescText('NXT 프리마켓 시작 전 구독을 미리 신청합니다'))
  container.appendChild(buildTimetableRow('KRX 종목 추가 구독', 'timetable.krx_pre_subscribe', '08:59'))
  container.appendChild(createDescText('KRX 정규장 시작 전 KRX 단독 종목 구독을 추가합니다'))

  // 1일봉차트 자동다운로드 (토글 + 시간 슬롯) — 단일 항목이라 섹션 제목 생략 (P24)
  container.appendChild(buildConfirmedDownloadRow())
  container.appendChild(createDescText('장마감 후 자동 다운로드 시간 (기본값 20:40) — OFF 시 수동 다운로드만 가능'))

  // 거래소 고정 시간 참고 표시 (읽기 전용, 변경 불가) — P21 투명성
  container.appendChild(buildFixedTimesBox())

  // 구독 한도 — P10 SSOT 단일 설정 키, P21 사용자 조정 가능
  container.appendChild(sectionTitle('구독 한도'))
  container.appendChild(createDescText('종목 실시간 시세를 동시에 구독할 최대 개수입니다. 보유 종목을 우선 등록한 뒤, 남은 자리만큼 필터 통과 종목이 추가로 등록됩니다. (기본값 200, 범위 1~1000)'))
  container.appendChild(buildSubscribeMaxRow())
}

/* ── 자동매매 탭 ── */
function buildMasterToggleRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매매'
  row.appendChild(label)

  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;'
  right.appendChild(createHolidayBadge())
  masterToggle = createToggleBtn({ on: false, onClick: () => handleMasterToggle() })
  right.appendChild(masterToggle.el)
  row.appendChild(right)
  return row
}

function buildAutoBuyRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매수'
  row.appendChild(label)
  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;'
  autoBuyToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.auto_buy_on
    vals.auto_buy_on = next; autoBuyToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ auto_buy_on: next })
    toastResult(res)
    if (!res.ok) { vals.auto_buy_on = !next; autoBuyToggle!.setOn(!next) }
  }})
  right.appendChild(createHolidayBadge())
  right.appendChild(autoBuyToggle.el)
  row.appendChild(right)
  return row
}

function buildAutoSellRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매도'
  row.appendChild(label)
  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;'
  autoSellToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.auto_sell_on
    vals.auto_sell_on = next; autoSellToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ auto_sell_on: next })
    toastResult(res)
    if (!res.ok) { vals.auto_sell_on = !next; autoSellToggle!.setOn(!next) }
  }})
  right.appendChild(createHolidayBadge())
  right.appendChild(autoSellToggle.el)
  row.appendChild(right)
  return row
}

function buildRiskManagerMasterRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '매매 안전장치'
  row.appendChild(label)
  riskManagerChildren = document.createElement('div')
  riskManagerToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.risk_manager_on
    vals.risk_manager_on = next; riskManagerToggle!.setOn(next)
    setDisabled(riskManagerChildren!, !next)
    const res = await settingsMgr!.saveSection({ risk_manager_on: next })
    toastResult(res)
    if (!res.ok) {
      vals.risk_manager_on = !next; riskManagerToggle!.setOn(!next)
      setDisabled(riskManagerChildren!, next)
    }
  }})
  row.appendChild(riskManagerToggle.el)
  return row
}

function buildDailyLossRow(): void {
  dailyLossInput = createMoneyInput({
    value: -500000,
    onChange: async v => {
      vals.daily_loss_limit = v
      const res = await settingsMgr!.saveSection({ daily_loss_limit: v })
      toastResult(res)
      if (res.ok) vals.daily_loss_limit = v
    },
    step: 10000, min: -1000000000, max: 0, name: 'daily_loss_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 손실 한도 (원)',
    toggleOn: true,
    onToggle: async next => {
      vals.daily_loss_limit_on = next
      const res = await settingsMgr!.saveSection({ daily_loss_limit_on: next })
      toastResult(res)
      if (!res.ok) vals.daily_loss_limit_on = !next
    },
    controlsChild: dailyLossInput.el,
  })
  dailyLossToggle = r.toggle; dailyLossControls = r.controls
  riskManagerChildren!.appendChild(r.el)
}

function buildDailyLossRateRow(): void {
  dailyLossRateInput = createNumInput({
    value: -5,
    onChange: async v => {
      vals.daily_loss_rate_limit = v
      const res = await settingsMgr!.saveSection({ daily_loss_rate_limit: v })
      toastResult(res)
      if (res.ok) vals.daily_loss_rate_limit = v
    },
    step: 0.1, min: -100, max: 0, name: 'daily_loss_rate_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 손실률 한도 (%)',
    toggleOn: false,
    onToggle: async next => {
      vals.daily_loss_rate_limit_on = next
      const res = await settingsMgr!.saveSection({ daily_loss_rate_limit_on: next })
      toastResult(res)
      if (!res.ok) vals.daily_loss_rate_limit_on = !next
    },
    controlsChild: dailyLossRateInput.el,
  })
  dailyLossRateToggle = r.toggle; dailyLossRateControls = r.controls
  riskManagerChildren!.appendChild(r.el)
}

function buildDailyProfitRow(): void {
  dailyProfitInput = createMoneyInput({
    value: 500000,
    onChange: async v => {
      vals.daily_profit_limit = v
      const res = await settingsMgr!.saveSection({ daily_profit_limit: v })
      toastResult(res)
      if (res.ok) vals.daily_profit_limit = v
    },
    name: 'daily_profit_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 수익 한도 (원)',
    toggleOn: false,
    onToggle: async next => {
      vals.daily_profit_limit_on = next
      const res = await settingsMgr!.saveSection({ daily_profit_limit_on: next })
      toastResult(res)
      if (!res.ok) vals.daily_profit_limit_on = !next
    },
    controlsChild: dailyProfitInput.el,
  })
  dailyProfitToggle = r.toggle; dailyProfitControls = r.controls
  riskManagerChildren!.appendChild(r.el)
}

function buildDailyProfitRateRow(): void {
  dailyProfitRateInput = createNumInput({
    value: 5,
    onChange: async v => {
      vals.daily_profit_rate_limit = v
      const res = await settingsMgr!.saveSection({ daily_profit_rate_limit: v })
      toastResult(res)
      if (res.ok) vals.daily_profit_rate_limit = v
    },
    step: 0.1, min: 0, max: 100, name: 'daily_profit_rate_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 수익률 한도 (%)',
    toggleOn: false,
    onToggle: async next => {
      vals.daily_profit_rate_limit_on = next
      const res = await settingsMgr!.saveSection({ daily_profit_rate_limit_on: next })
      toastResult(res)
      if (!res.ok) vals.daily_profit_rate_limit_on = !next
    },
    controlsChild: dailyProfitRateInput.el,
  })
  dailyProfitRateToggle = r.toggle; dailyProfitRateControls = r.controls
  riskManagerChildren!.appendChild(r.el)
}

function buildConsecLossRow(): void {
  consecLossInput = createNumInput({
    value: 3,
    onChange: async v => {
      vals.consecutive_loss_limit = v
      const res = await settingsMgr!.saveSection({ consecutive_loss_limit: v })
      toastResult(res)
      if (res.ok) vals.consecutive_loss_limit = v
    },
    step: 1, min: 1, max: 100, name: 'consecutive_loss_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '연속 손실 횟수 한도 (회)',
    toggleOn: false,
    onToggle: async next => {
      vals.consecutive_loss_limit_on = next
      const res = await settingsMgr!.saveSection({ consecutive_loss_limit_on: next })
      toastResult(res)
      if (!res.ok) vals.consecutive_loss_limit_on = !next
    },
    controlsChild: consecLossInput.el,
  })
  consecLossToggle = r.toggle; consecLossControls = r.controls
  riskManagerChildren!.appendChild(r.el)
}

function buildRiskBlockBuyRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '안전장치 조건 충족 시 매수 차단'
  row.appendChild(label)
  riskBlockBuyToggle = createToggleBtn({ on: true, onClick: async () => {
    const next = !vals.risk_block_buy_on
    vals.risk_block_buy_on = next; riskBlockBuyToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ risk_block_buy_on: next })
    toastResult(res)
    if (!res.ok) { vals.risk_block_buy_on = !next; riskBlockBuyToggle!.setOn(!next) }
  }})
  row.appendChild(riskBlockBuyToggle.el)
  return row
}

function buildRiskBlockSellRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '안전장치 조건 충족 시 매도 차단'
  row.appendChild(label)
  riskBlockSellToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.risk_block_sell_on
    vals.risk_block_sell_on = next; riskBlockSellToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ risk_block_sell_on: next })
    toastResult(res)
    if (!res.ok) { vals.risk_block_sell_on = !next; riskBlockSellToggle!.setOn(!next) }
  }})
  row.appendChild(riskBlockSellToggle.el)
  return row
}

function buildRiskManagerChildren(): HTMLElement {
  // 매매 안전장치 OFF 시 일괄 비활성화
  buildDailyLossRow()
  buildDailyLossRateRow()
  buildDailyProfitRow()
  buildDailyProfitRateRow()
  buildConsecLossRow()
  riskManagerChildren!.appendChild(buildRiskBlockBuyRow())
  riskManagerChildren!.appendChild(buildRiskBlockSellRow())
  riskManagerChildren!.appendChild(createDescText('손실 상태에서 매도 차단 시 손실 확대 위험 — 신중하게 활성화하세요'))
  return riskManagerChildren!
}

function buildUiFlashRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '실시간 현재가 플래시 효과'
  row.appendChild(label)
  uiFlashToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.ui_price_flash_on
    vals.ui_price_flash_on = next
    uiFlashToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ ui_price_flash_on: next })
    toastResult(res)
    if (!res.ok) { vals.ui_price_flash_on = !next; uiFlashToggle!.setOn(!next) }
  }})
  row.appendChild(uiFlashToggle.el)
  return row
}

function renderAutoTradeTab(container: HTMLElement): void {
  container.appendChild(buildMasterToggleRow())
  container.appendChild(createDescText('자동매매(매수/매도) 마스터 스위치 — OFF면 모든 매매 중단'))
  container.appendChild(buildAutoBuyRow())
  container.appendChild(buildAutoSellRow())
  container.appendChild(createDescText('거래일 설정시간 내에서만 자동 매수/매도 실행. 공휴일·주말에는 자동매매가 항상 차단됩니다. 시간 설정은 "시간 설정" 탭에서'))

  // 전역매매설정 (매매 안전장치) 섹션 — 목표 수익/손실 도달 시 자동 매매 중단
  container.appendChild(sectionTitle('전역매매설정 (매매 안전장치)'))
  container.appendChild(createDescText('목표 수익/손실 도달 시 자동 매매 중단. 매매 안전장치 OFF 시 모든 조건이 적용되지 않습니다.'))
  container.appendChild(buildRiskManagerMasterRow())
  container.appendChild(buildRiskManagerChildren())

  // 화면 표시 섹션 — 플래시 효과 (API 설정 탭에서 이동, Step 5, 설계서 5-3)
  container.appendChild(sectionTitle('화면 표시'))
  container.appendChild(buildUiFlashRow())
  container.appendChild(createDescText('실시간 시세 변경 시 노란색 플래시 깜빡임 효과 적용 여부'))
}

async function handleMasterToggle(): Promise<void> {
  const next = !vals.time_scheduler_on
  vals.time_scheduler_on = next; masterToggle?.setOn(next)
  const r = await settingsMgr!.saveSection({ time_scheduler_on: next })
  toastResult(r)
  if (!r.ok) { vals.time_scheduler_on = !next; masterToggle?.setOn(!next) }
}

/* ── 텔레그램 탭 ── */
const TELE_STR_KEYS = ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real'] as const
const TELE_LABELS: Record<string, string> = { telegram_chat_id: '채팅 ID', telegram_bot_token_test: '테스트 봇 토큰', telegram_bot_token_real: '실전 봇 토큰' }

function buildTeleToggleRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '텔레그램 알림'
  row.appendChild(label)
  teleToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.tele_on; vals.tele_on = next; teleToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ tele_on: next })
    toastResult(res)
    if (!res.ok) { vals.tele_on = !next; teleToggle!.setOn(!next) }
  }})
  row.appendChild(teleToggle.el)
  return row
}

function buildTeleInputRows(container: HTMLElement): void {
  for (const k of TELE_STR_KEYS) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
    const lbl = document.createElement('span')
    Object.assign(lbl.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
    lbl.textContent = TELE_LABELS[k]
    row.appendChild(lbl)
    const input = createTextInput({
      value: String(vals[k] || ''),
      type: MASKED_FIELDS.has(k) ? 'password' : 'text',
      name: k,
      style: { padding: GS.inputPad } as Partial<CSSStyleDeclaration>,
    })
    teleInputs[k] = input
    row.appendChild(input)
    container.appendChild(row)
  }
}

function buildTeleSaveRow(): HTMLElement {
  const saveRow = document.createElement('div')
  Object.assign(saveRow.style, { margin: GS.saveMargin, textAlign: 'right' })
  const saveBtn = createActionButton({
    label: '저장', variant: 'secondary', padding: GS.btnPad, fontSize: GS.label,
    onClick: async () => {
      const orig: Record<string, unknown> = {}
      const current: Record<string, unknown> = {}
      for (const k of TELE_STR_KEYS) {
        orig[k] = vals[k]
        current[k] = teleInputs[k]?.value ?? vals[k]
      }
      const dirty = extractDirty(orig, current, TELE_STR_KEYS as unknown as string[])
      saveBtn.textContent = '저장 중...'
      saveBtn.disabled = true
      const res = await settingsMgr!.saveSection(dirty)
      showSaveToast(res.ok ? 'saved' : 'error')
      saveBtn.textContent = '저장'
      saveBtn.disabled = false
    },
  })
  saveRow.appendChild(saveBtn)
  return saveRow
}

function buildTeleCommandTable(): HTMLElement {
  interface CommandRow { cmd: string; desc: string }
  const COMMAND_COLUMNS: ColumnDef<CommandRow>[] = [
    { key: 'cmd', label: '명령어', align: 'center', type: 'cmd', render: r => r.cmd },
    { key: 'desc', label: '설명', align: 'left', type: 'desc', render: r => r.desc },
  ]
  const commands: CommandRow[] = [
    { cmd: '자동', desc: '자동매매 ON/OFF' }, { cmd: '매수', desc: '자동매수 ON/OFF' },
    { cmd: '매도', desc: '자동매도 ON/OFF' }, { cmd: '상태', desc: '현재 설정 + 계좌 요약' },
    { cmd: '잔고', desc: '계좌 현황' }, { cmd: '업종', desc: '업종 분석 요약' },
    { cmd: '후보', desc: '매수후보 1~10순위' }, { cmd: '휴일', desc: '공휴일 자동 차단 ON/OFF' },
    { cmd: '도움말', desc: '명령어 목록' },
  ]
  const tableWrap = document.createElement('div')
  tableWrap.style.marginTop = '16px'
  const table = createDataTable<CommandRow>({ columns: COMMAND_COLUMNS, stickyHeader: false })
  table.updateRows(commands)
  tableWrap.appendChild(table.el)
  return tableWrap
}

function renderTelegramTab(container: HTMLElement): void {
  container.appendChild(buildTeleToggleRow())
  buildTeleInputRows(container)
  container.appendChild(buildTeleSaveRow())
  container.appendChild(buildTeleCommandTable())
}

/* ── 계정관리 탭 ── */
function renderAccountTab(container: HTMLElement): void {
  // 투자모드 선택 (중앙정렬)
  tradeModeRadioGroup = createRadioGroup({
    items: [
      { value: 'test', label: '테스트' },
      { value: 'real', label: '실전투자' },
    ],
    name: 'trade-mode-acct',
    value: String(vals.trade_mode ?? 'test'),
    onChange: (v) => handleTradeMode(v),
  })
  Object.assign(tradeModeRadioGroup.el.style, { justifyContent: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  container.appendChild(tradeModeRadioGroup.el)

  // 가상 예수금 (항상 렌더링, display로 토글)
  const virtualTitle = sectionTitle('가상 투자금 (테스트모드 전용)')
  testVirtualSection = document.createElement('div')
  const innerSection = renderTestVirtualSection()
  testVirtualSection.appendChild(virtualTitle)
  testVirtualSection.appendChild(innerSection)
  testVirtualSection.style.display = vals.trade_mode === 'test' ? '' : 'none'
  container.appendChild(testVirtualSection)
}

function handleTradeMode(val: string): void {
  if (val === vals.trade_mode) return

  if (val === 'real') {
    const msg = document.createElement('div')
    Object.assign(msg.style, { fontSize: FONT_SIZE.label, color: COLOR.code, lineHeight: '1.6' })
    msg.innerHTML = `실전투자 모드로 전환하시겠습니까?<br><span style="color:${COLOR.up};font-weight:500">실제 돈으로 매매가 실행됩니다.</span>`
    showCustomDialog({
      title: '⚠️ 실전투자 모드 전환',
      content: msg,
      actions: [
        { label: '취소', onClick: () => {} },
        { label: '전환', onClick: async () => {
          vals.trade_mode = 'real'
          const res = await settingsMgr!.saveSection({ trade_mode: 'real' })
          if (!res.ok) vals.trade_mode = 'test'
          syncTradeMode()
        }, variant: 'danger' },
      ]
    })
    return
  }

  vals.trade_mode = val
  settingsMgr?.saveSection({ trade_mode: val }).then(res => {
    if (!res.ok) vals.trade_mode = 'test'
    syncTradeMode()
  })
}

function syncTradeMode(): void {
  // 라디오 버튼 상태 업데이트
  tradeModeRadioGroup?.setValue(String(vals.trade_mode ?? 'test'))
  // 가상 예수금 섹션 표시/숨김
  if (testVirtualSection) {
    testVirtualSection.style.display = vals.trade_mode === 'test' ? '' : 'none'
  }
}

function buildTestVirtualInputRow(state: { inputAmount: number }): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', alignItems: 'center', gap: '8px', padding: GS.rowPad })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, whiteSpace: 'nowrap' })
  label.textContent = '금액입력(원):'
  row.appendChild(label)

  depositInput = createMoneyInput({ value: state.inputAmount, onChange: v => { state.inputAmount = Math.max(0, v) }, style: { width: '160px' } as unknown as Partial<CSSStyleDeclaration>, name: 'deposit_amount' })
  row.appendChild(depositInput.el)

  const chargeBtn = createActionButton({
    label: '투자금충전', variant: 'secondary', padding: '7px 12px', borderRadius: '4px', fontSize: GS.label,
    onClick: async () => {
      if (state.inputAmount <= 0) return
      try {
        const res = await api.settlementCharge(state.inputAmount)
        showSaveToast(res.ok ? 'saved' : 'error')
      } catch {
        showSaveToast('error')
      }
    },
  })
  row.appendChild(chargeBtn)
  return row
}

function buildTestVirtualSaveRow(state: { inputAmount: number }): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'flex-end', margin: GS.saveMargin })
  const btn = createActionButton({
    label: '투자금 변경', variant: 'secondary', padding: '7px 16px', borderRadius: '4px', fontSize: GS.label,
    onClick: async () => {
      const res = await settingsMgr!.saveSection({ test_virtual_deposit: state.inputAmount, test_virtual_balance: state.inputAmount })
      showSaveToast(res.ok ? 'saved' : 'error')
    },
  })
  row.appendChild(btn)
  return row
}

function buildTestVirtualInfoWrap(): HTMLElement {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { borderTop: '1px solid ' + COLOR.borderLight, padding: GS.rowPad })
  const depRow = document.createElement('div')
  Object.assign(depRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, fontSize: GS.label })
  depRow.innerHTML = '<span>기본투자금</span>'
  depositDisplay = document.createElement('span')
  depositDisplay.textContent = `${(Number(vals.test_virtual_deposit) || 0).toLocaleString()}원`
  depRow.appendChild(depositDisplay)
  wrap.appendChild(depRow)
  return wrap
}

function buildTestVirtualResetWrap(): HTMLElement {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { borderTop: '1px solid ' + COLOR.borderLight, padding: GS.rowPad })
  const resetBtn = createActionButton({
    label: '🔴 테스트 데이터 전체 초기화', variant: 'danger', padding: '8px 18px', borderRadius: '4px', fontSize: GS.label,
    onClick: async () => {
      const confirmed = await showConfirmDialog({
        title: '테스트 데이터 초기화',
        message: '테스트 데이터를 전체 초기화하시겠습니까?\n가상 보유종목, 매매 이력, 투자금이 모두 초기화됩니다.',
        isDanger: true
      })
      if (!confirmed) return
      try {
        await api.resetTestData()
        applyTestDataResetCompleted()
        showSaveToast('saved')
      } catch {
        await showAlertDialog({ title: '오류', message: '초기화 실패' })
      }
    },
  })
  wrap.appendChild(resetBtn)
  return wrap
}

function renderTestVirtualSection(): HTMLElement {
  const wrap = document.createElement('div')
  const disabled = vals.trade_mode !== 'test'
  if (disabled) { wrap.style.opacity = '0.4'; wrap.style.pointerEvents = 'none' }

  const state = { inputAmount: Number(vals.test_virtual_deposit) || 0 }
  wrap.appendChild(buildTestVirtualInputRow(state))
  wrap.appendChild(buildTestVirtualSaveRow(state))
  wrap.appendChild(createDescText('누적투자금과 주문가능금액을 입력한 금액으로 변경합니다. 데이터 초기화 시에도 이 금액이 기본값으로 사용됩니다.'))
  wrap.appendChild(buildTestVirtualInfoWrap())
  wrap.appendChild(buildTestVirtualResetWrap())
  return wrap
}

/* ── API 설정 탭 ── */
function renderApiSettingsTab(container: HTMLElement): void {
  // Step 2A: 주 사용 증권사 선택 (통신망 전환)
  container.appendChild(sectionTitle('주 사용 증권사'))
  brokerRadioGroup = createRadioGroup({
    items: [
      { value: 'kiwoom', label: '키움증권' },
      { value: 'ls', label: 'LS증권' },
    ],
    name: 'primary-broker',
    value: String(vals.broker ?? 'kiwoom'),
    onChange: (v) => handleBrokerChange(v as 'kiwoom' | 'ls'),
  })
  Object.assign(brokerRadioGroup.el.style, { justifyContent: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  container.appendChild(brokerRadioGroup.el)

  container.appendChild(createDescText('선택한 증권사로 시스템 전체 통신망(시세, 계좌, 주문)이 전환됩니다. 엔진이 재기동되어 실시간 연결이 잠시 끊깁니다.', { textAlign: 'center' }))

  // Step 2B: API 키 보관용 탭 (키움 API / LS API)
  const apiTabBar = document.createElement('div')
  Object.assign(apiTabBar.style, { display: 'flex', gap: '8px', marginBottom: '12px' })

  const tabConfigs = [
    { id: 'kiwoom', label: '키움 API' },
    { id: 'ls', label: 'LS API' },
  ] as const

  for (const tab of tabConfigs) {
    const btn = document.createElement('button')
    btn.type = 'button'
    const isActive = activeApiTab === tab.id
    Object.assign(btn.style, {
      padding: '6px 12px', cursor: 'pointer', border: '1px solid ' + COLOR.borderDark, background: isActive ? COLOR.hoverBg : COLOR.white,
      borderRadius: '4px', fontSize: GS.label, color: isActive ? COLOR.neutral : COLOR.tertiary,
    })
    btn.textContent = tab.label
    btn.addEventListener('click', () => { activeApiTab = tab.id; refreshApiTabContent() })
    apiTabButtons[tab.id] = btn
    apiTabBar.appendChild(btn)
  }
  container.appendChild(apiTabBar)

  // API 필드 컨테이너
  const apiFieldsContainer = document.createElement('div')
  apiFieldsContainer.id = 'api-fields-container'
  container.appendChild(apiFieldsContainer)

  // 초기 렌더링
  renderApiFields(apiFieldsContainer)
}

const API_FIELDS_CONFIG: Record<string, { key: string; label: string; type: 'password' | 'text' }[]> = {
  kiwoom: [
    { key: 'kiwoom_app_key', label: '앱키', type: 'password' },
    { key: 'kiwoom_app_secret', label: '앱시크릿', type: 'password' },
    { key: 'kiwoom_account_no', label: '계좌번호', type: 'text' },
  ],
  ls: [
    { key: 'ls_app_key', label: '앱키', type: 'password' },
    { key: 'ls_app_secret', label: '앱시크릿', type: 'password' },
    { key: 'ls_account_no', label: '계좌번호', type: 'text' },
  ],
}

function buildApiInputRows(container: HTMLElement, fields: { key: string; label: string; type: 'password' | 'text' }[]): void {
  for (const field of fields) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
    const lbl = document.createElement('span')
    Object.assign(lbl.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal, flex: '1' })
    lbl.textContent = field.label
    row.appendChild(lbl)

    const input = createDarkInput(field.type)
    input.value = String(vals[field.key] || '')
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
    })
    apiKeyInputs[field.key] = input
    row.appendChild(input)
    container.appendChild(row)
  }
}

function buildApiSaveRow(fields: { key: string }[]): HTMLElement {
  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, { textAlign: 'right', margin: GS.saveMargin })
  const saveBtn = createActionButton({
    label: '저장', variant: 'warning', padding: GS.btnPad, borderRadius: '4px', fontSize: GS.label,
    onClick: async () => {
      const keys = fields.map(f => f.key)
      const orig: Record<string, unknown> = {}
      const current: Record<string, unknown> = {}
      for (const k of keys) {
        orig[k] = vals[k]
        current[k] = apiKeyInputs[k]?.value ?? vals[k]
      }
      const dirty = extractDirty(orig, current, keys)
      if (Object.keys(dirty).length === 0) return
      saveBtn.textContent = '저장 중...'
      saveBtn.disabled = true
      const res = await settingsMgr!.saveSection(dirty)
      showSaveToast(res.ok ? 'saved' : 'error')
      saveBtn.textContent = '저장'
      saveBtn.disabled = false
    },
  })
  btnRow.appendChild(saveBtn)
  return btnRow
}

function renderApiFields(container: HTMLElement): void {
  container.innerHTML = ''
  const fields = API_FIELDS_CONFIG[activeApiTab] || []
  buildApiInputRows(container, fields)
  container.appendChild(buildApiSaveRow(fields))
}

function refreshApiTabContent(): void {
  const container = document.getElementById('api-fields-container')
  if (container) {
    // 탭 버튼 스타일 업데이트
    for (const [id, btn] of Object.entries(apiTabButtons)) {
      const isActive = id === activeApiTab
      Object.assign(btn.style, {
        background: isActive ? COLOR.hoverBg : COLOR.white,
        color: isActive ? COLOR.neutral : COLOR.tertiary,
      })
    }
    renderApiFields(container)
  }
}

async function handleBrokerChange(val: 'kiwoom' | 'ls'): Promise<void> {
  if (val === vals.broker || brokerSaving) return

  const prev = String(vals.broker ?? 'kiwoom')
  const prevName = BROKER_NAMES[prev] ?? prev
  const nextName = BROKER_NAMES[val] ?? val

  const message =
    '주 사용 증권사를 변경합니다.\n\n' +
    `변경 전: ${prevName}\n` +
    `변경 후: ${nextName}\n\n` +
    '수행될 작업:\n' +
    '  • 기존 증권사 연결 해제\n' +
    '  • 기존 인증 토큰 폐기\n' +
    '  • 거래 엔진 재기동\n' +
    '  • 새 증권사 연결 및 인증\n\n' +
    '확인을 누르면 즉시 실행되며, 실시간 연결이 잠시 끊깁니다.'

  const confirmed = await showConfirmDialog({
    title: '주 사용 증권사 변경',
    message,
    confirmText: '확인',
    cancelText: '취소',
  })

  if (!confirmed) {
    // 취소/Escape/외부클릭 — 라디오를 원래 값으로 복원
    syncBrokerRadios()
    return
  }

  // 확인 — 기존 변경 로직 그대로 진행
  brokerSaving = true
  const prevBroker = vals.broker
  settingsMgr?.saveSection({ broker: val }).then(res => {
    if (res.ok) {
      vals.broker = val
    } else {
      vals.broker = prevBroker
    }
    brokerSaving = false
    syncBrokerRadios()
  })
}

function syncBrokerRadios(): void {
  brokerRadioGroup?.setValue(String(vals.broker ?? 'kiwoom'))
  brokerRadioGroup?.setDisabled(brokerSaving)
}

/* ── 설정 동기화 ── */
/** 토글+입력+컨트롤 행 동기화 공통 패턴 (5회 반복 추출 — P23 DRY) */
function syncToggleInputRow(
  toggle: ReturnType<typeof createToggleBtn> | null,
  input: { el: HTMLElement; setValue: (v: number) => void } | null,
  controls: HTMLElement | null,
  on: boolean,
  value: number,
  act: Element | null,
): void {
  toggle?.setOn(on)
  if (input && (!act || !input.el.contains(act))) {
    input.setValue(value)
  }
  if (controls) setDisabled(controls, !on)
}

function syncRiskManager(r: Record<string, unknown>, act: Element | null): void {
  riskManagerToggle?.setOn(!!r.risk_manager_on)
  if (riskManagerChildren) setDisabled(riskManagerChildren, !r.risk_manager_on)
  syncToggleInputRow(dailyLossToggle, dailyLossInput, dailyLossControls, r.daily_loss_limit_on !== false, Number(r.daily_loss_limit ?? -500000), act)
  syncToggleInputRow(dailyLossRateToggle, dailyLossRateInput, dailyLossRateControls, !!r.daily_loss_rate_limit_on, Number(r.daily_loss_rate_limit ?? -5), act)
  syncToggleInputRow(dailyProfitToggle, dailyProfitInput, dailyProfitControls, !!r.daily_profit_limit_on, Number(r.daily_profit_limit ?? 500000), act)
  syncToggleInputRow(dailyProfitRateToggle, dailyProfitRateInput, dailyProfitRateControls, !!r.daily_profit_rate_limit_on, Number(r.daily_profit_rate_limit ?? 5), act)
  syncToggleInputRow(consecLossToggle, consecLossInput, consecLossControls, !!r.consecutive_loss_limit_on, Number(r.consecutive_loss_limit ?? 3), act)
  riskBlockBuyToggle?.setOn(r.risk_block_buy_on !== false)
  riskBlockSellToggle?.setOn(!!r.risk_block_sell_on)
}

function syncTimetables(r: Record<string, unknown>): void {
  const [trh, trm] = parseHM(String(r['timetable.realtime_reset'] ?? '07:58'))
  if (timetableResetSlot) updateTimeSlotDisplay(timetableResetSlot, trh, trm)
  const [twh, twm] = parseHM(String(r['timetable.ws_prestart'] ?? '07:59'))
  if (timetableWsSlot) updateTimeSlotDisplay(timetableWsSlot, twh, twm)
  const [tkh, tkm] = parseHM(String(r['timetable.krx_pre_subscribe'] ?? '08:59'))
  if (timetableKrxSlot) updateTimeSlotDisplay(timetableKrxSlot, tkh, tkm)
}

function syncAutoTradeTab(r: Record<string, unknown>): void {
  masterToggle?.setOn(!!r.time_scheduler_on)
  updateHolidayBadges()

  // 확정 시세 다운로드 시간 + 자동다운로드 토글
  const [cdh, cdm] = parseHM(String(r['timetable.confirmed_download'] ?? '20:40'))
  confirmedDlH = cdh; confirmedDlM = cdm
  if (confirmedDlSlot) updateTimeSlotDisplay(confirmedDlSlot, cdh, cdm)
  const dlOn = r.scheduler_market_close_on !== false
  confirmedDlToggle?.setOn(dlOn)
  if (confirmedDlSlot) setDisabled(confirmedDlSlot, !dlOn)

  uiFlashToggle?.setOn(r.ui_price_flash_on !== false)

  syncRiskManager(r, document.activeElement)
  syncTimetables(r)

  // 구독 한도
  subscribeMaxInput?.setValue(Number(r['subscribe.max_0b_count'] ?? 200) || 200)

  // 자동매수/매도 (시간쌍은 시간 설정 탭에서 표시, 토글 OFF 시에도 활성화 유지 — 설계서 2-1)
  autoBuyToggle?.setOn(!!r.auto_buy_on)
  if (buyTimeHandle) buyTimeHandle.setValue(String(r.buy_time_start ?? '09:00'), String(r.buy_time_end ?? '15:00'))
  autoSellToggle?.setOn(!!r.auto_sell_on)
  if (sellTimeHandle) sellTimeHandle.setValue(String(r.sell_time_start ?? '09:00'), String(r.sell_time_end ?? '15:00'))
}

function syncTelegramTab(r: Record<string, unknown>): void {
  const act = document.activeElement
  teleToggle?.setOn(!!r.tele_on)
  for (const k of ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real']) {
    if (teleInputs[k] && (!act || !teleInputs[k].contains(act))) {
      teleInputs[k].value = String(r[k] || '')
    }
  }
}

function syncAccountTab(r: Record<string, unknown>): void {
  if (depositDisplay) depositDisplay.textContent = `${(Number(r.test_virtual_deposit) || 0).toLocaleString()}원`
}

function syncApiSettingsTab(r: Record<string, unknown>): void {
  const act = document.activeElement
  const allApiKeys = ['kiwoom_app_key', 'kiwoom_app_secret', 'kiwoom_account_no', 'ls_app_key', 'ls_app_secret', 'ls_account_no']
  for (const k of allApiKeys) {
    if (apiKeyInputs[k] && (!act || !apiKeyInputs[k].contains(act))) {
      apiKeyInputs[k].value = String(r[k] || '')
    }
  }
  if (r.broker !== undefined && vals.broker !== r.broker) {
    vals.broker = r.broker
  }
  syncBrokerRadios()
}

function syncFromSettings(s: AppSettings): void {
  const r = s as Record<string, unknown>
  // 전체 복사 대신 변경된 키만 업데이트
  for (const k of Object.keys(r)) {
    if (vals[k] !== r[k]) {
      vals[k] = r[k]
    }
  }

  syncAutoTradeTab(r)
  syncTelegramTab(r)
  syncAccountTab(r)
  syncApiSettingsTab(r)
}

/* ── mount ── */
function buildTabPanels(): void {
  // 모든 탭 패널 사전 렌더링 (display: none으로 숨김)
  const autoTradePanel = document.createElement('div')
  renderAutoTradeTab(autoTradePanel)

  const timeSettingsPanel = document.createElement('div')
  renderTimeSettingsTab(timeSettingsPanel)

  const accountPanel = document.createElement('div')
  renderAccountTab(accountPanel)

  const apiPanel = document.createElement('div')
  renderApiSettingsTab(apiPanel)

  const telegramPanel = document.createElement('div')
  renderTelegramTab(telegramPanel)

  tabPanels = {
    'auto-trade': autoTradePanel,
    'time-settings': timeSettingsPanel,
    'account-manage': accountPanel,
    'api-settings': apiPanel,
    'telegram': telegramPanel,
  }

  // DOM에 추가하고 비활성 탭은 숨김
  for (const [id, panel] of Object.entries(tabPanels) as [TabId, HTMLElement][]) {
    panel.style.display = id === activeTab ? '' : 'none'
    tabContent!.appendChild(panel)
  }
}

function mount(container: HTMLElement): void {
  notifyPageActive('settings')
  settingsMgr = createSettingsManager(uiStore)
  vals = {}
  activeTab = 'auto-trade'
  holidayBadgeEls = []
  isTradingDay = true
  tradingDayLoading = true

  rootEl = document.createElement('div')
  rootEl.appendChild(createCardTitle('일반설정'))

  // 탭 바
  tabBar = renderTabBar()
  rootEl.appendChild(tabBar)

  // 탭 콘텐츠 컨테이너
  tabContent = document.createElement('div')
  tabContent.style.padding = '0 4px'
  rootEl.appendChild(tabContent)

  container.appendChild(rootEl)

  // 초기 설정 로드
  const initial = settingsMgr.getSettings()
  if (initial) {
    vals = { ...(initial as Record<string, unknown>) }
  }

  buildTabPanels()

  // 설정 동기화 + 구독 (표준 유틸 — settings-page.ts, P23 일관성)
  unsubSettings = startSettingsSubscription(settingsMgr, syncFromSettings)

  // 거래일 확인
  api.getTradingDay()
    .then(data => { isTradingDay = data.is_trading_day; tradingDayLoading = false; updateHolidayBadges() })
    .catch(() => { isTradingDay = true; tradingDayLoading = false; showSaveToast('error', '거래일 조회 실패 — 거래일로 간주하여 자동매매를 허용합니다') })
}
function unmount(): void {
  notifyPageInactive('settings')
  destroySettingsPage(unsubSettings, null, settingsMgr)
  unsubSettings = null
  settingsMgr = null
  rootEl = null
  tabBar = null
  tabBarHandle = null
  tabContent = null
  tabPanels = null
  masterToggle = null
  autoBuyToggle = null
  buyTimeHandle = null
  autoSellToggle = null
  sellTimeHandle = null
  holidayBadgeEls = []
  // 매매 안전장치
  riskManagerToggle = null
  riskManagerChildren = null
  dailyLossToggle = null
  dailyLossInput = null
  dailyLossControls = null
  dailyLossRateToggle = null
  dailyLossRateInput = null
  dailyLossRateControls = null
  dailyProfitToggle = null
  dailyProfitInput = null
  dailyProfitControls = null
  dailyProfitRateToggle = null
  dailyProfitRateInput = null
  dailyProfitRateControls = null
  consecLossToggle = null
  consecLossInput = null
  consecLossControls = null
  riskBlockBuyToggle = null
  riskBlockSellToggle = null
  teleToggle = null
  teleInputs = {}
  tradeModeRadioGroup = null
  testVirtualSection = null
  depositInput = null
  depositDisplay = null
  apiKeyInputs = {}
  brokerRadioGroup = null
  apiTabButtons = {}
  activeApiTab = 'kiwoom'
  brokerSaving = false
  vals = {}
}

export default { mount, unmount }
