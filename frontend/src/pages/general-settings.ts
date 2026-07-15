// frontend/src/pages/general-settings.ts
// 일반설정 — Vanilla TS PageModule
// SettingsTabContainer.tsx + TelegramSection + AccountManageSection + TestVirtualSection 통합

import { uiStore, applyTestDataResetCompleted } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingsManager, extractDirty, MASKED_FIELDS, type SettingsManager } from '../settings'
import { createToggleBtn, createMoneyInput, createTextInput, createRadioGroup, focusNext } from '../components/common/setting-row'
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

type TabId = 'auto-trade' | 'telegram' | 'account-manage' | 'api-settings'

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
let wsToggle: ReturnType<typeof createToggleBtn> | null = null
let holidayBadgeEls: HTMLElement[] = []
let uiFlashToggle: ReturnType<typeof createToggleBtn> | null = null

// 확정 시세 다운로드 시간 (단일 슬롯) + 자동다운로드 토글
let confirmedDlSlot: HTMLElement | null = null
let confirmedDlToggle: ReturnType<typeof createToggleBtn> | null = null
let confirmedDlH = '20', confirmedDlM = '40'
let savingConfirmedDl = false

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

function scheduleConfirmedDlSave(): void {
  if (!settingsMgr) return
  if (savingConfirmedDl) return
  savingConfirmedDl = true
  const run = async (): Promise<void> => {
    const serverVal = String(vals['confirmed_download_time'] ?? '')
    const newVal = `${confirmedDlH}:${confirmedDlM}`
    if (newVal !== serverVal) {
      const dirty: Record<string, unknown> = { confirmed_download_time: newVal }
      const res = await settingsMgr!.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(vals, dirty)
    }
    savingConfirmedDl = false
  }
  run()
}

/* ── 탭 렌더링 ── */
function renderTabBar(): HTMLElement {
  const bar = document.createElement('div')
  Object.assign(bar.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid ' + COLOR.borderDark, marginBottom: '12px' })

  const tabs: { id: TabId; label: string }[] = [
    { id: 'auto-trade', label: '자동매매' },
    { id: 'account-manage', label: '투자모드' },
    { id: 'telegram', label: '텔레그램' },
    { id: 'api-settings', label: 'API 설정' },
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

  syncFromSettings(settingsMgr?.getSettings() ?? null)
}

/* ── 자동매매 탭 ── */
function renderAutoTradeTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('자동매매'))

  // 마스터 토글
  const masterRow = document.createElement('div')
  Object.assign(masterRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const masterLabel = document.createElement('span')
  Object.assign(masterLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  masterLabel.textContent = '자동매매'
  masterRow.appendChild(masterLabel)

  const masterRight = document.createElement('span')
  masterRight.style.cssText = 'display:flex;align-items:center;'
  masterRight.appendChild(createHolidayBadge())
  masterToggle = createToggleBtn({ on: false, onClick: () => handleMasterToggle() })
  masterRight.appendChild(masterToggle.el)
  masterRow.appendChild(masterRight)
  container.appendChild(masterRow)

  container.appendChild(createDescText('자동매매(매수/매도) 마스터 스위치 — OFF면 모든 매매 중단'))

  // 자동매수 행
  const autoBuyRow = document.createElement('div')
  Object.assign(autoBuyRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const autoBuyLabel = document.createElement('span')
  Object.assign(autoBuyLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  autoBuyLabel.textContent = '자동매수'
  autoBuyRow.appendChild(autoBuyLabel)
  const autoBuyRight = document.createElement('span')
  autoBuyRight.style.cssText = 'display:flex;align-items:center;gap:10px;'
  const buyStart = String(vals.buy_time_start ?? '09:00')
  const buyEnd = String(vals.buy_time_end ?? '15:00')
  const { el: buyTpWrap, handle: buyHandle } = createTimePairInput(buyStart, buyEnd, (s, e) => {
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
  buyTimeHandle = buyHandle
  autoBuyToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.auto_buy_on
    vals.auto_buy_on = next; autoBuyToggle!.setOn(next)
    if (buyTimeHandle) buyTimeHandle.setEnabled(next)
    const res = await settingsMgr!.saveSection({ auto_buy_on: next })
    toastResult(res)
    if (!res.ok) {
      vals.auto_buy_on = !next; autoBuyToggle!.setOn(!next)
      if (buyTimeHandle) buyTimeHandle.setEnabled(!next)
    }
  }})
  autoBuyRight.appendChild(buyTpWrap)
  const buyToggleWrap = document.createElement('span')
  buyToggleWrap.style.cssText = 'display:flex;align-items:center;'
  buyToggleWrap.appendChild(createHolidayBadge())
  buyToggleWrap.appendChild(autoBuyToggle.el)
  autoBuyRight.appendChild(buyToggleWrap)
  autoBuyRow.appendChild(autoBuyRight)
  container.appendChild(autoBuyRow)

  // 자동매도 행
  const autoSellRow = document.createElement('div')
  Object.assign(autoSellRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const autoSellLabel = document.createElement('span')
  Object.assign(autoSellLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  autoSellLabel.textContent = '자동매도'
  autoSellRow.appendChild(autoSellLabel)
  const autoSellRight = document.createElement('span')
  autoSellRight.style.cssText = 'display:flex;align-items:center;gap:10px;'
  const sellStart = String(vals.sell_time_start ?? '09:00')
  const sellEnd = String(vals.sell_time_end ?? '15:00')
  const { el: sellTpWrap, handle: sellHandle } = createTimePairInput(sellStart, sellEnd, (s, e) => {
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
  sellTimeHandle = sellHandle
  autoSellToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.auto_sell_on
    vals.auto_sell_on = next; autoSellToggle!.setOn(next)
    if (sellTimeHandle) sellTimeHandle.setEnabled(next)
    const res = await settingsMgr!.saveSection({ auto_sell_on: next })
    toastResult(res)
    if (!res.ok) {
      vals.auto_sell_on = !next; autoSellToggle!.setOn(!next)
      if (sellTimeHandle) sellTimeHandle.setEnabled(!next)
    }
  }})
  autoSellRight.appendChild(sellTpWrap)
  const sellToggleWrap = document.createElement('span')
  sellToggleWrap.style.cssText = 'display:flex;align-items:center;'
  sellToggleWrap.appendChild(createHolidayBadge())
  sellToggleWrap.appendChild(autoSellToggle.el)
  autoSellRight.appendChild(sellToggleWrap)
  autoSellRow.appendChild(autoSellRight)
  container.appendChild(autoSellRow)

  container.appendChild(createDescText('거래일 설정시간 내에서만 자동 매수/매도 실행. 공휴일·주말에는 자동매매가 항상 차단됩니다'))
}

function handleMasterToggle(): void {
  const next = !vals.time_scheduler_on
  vals.time_scheduler_on = next; masterToggle?.setOn(next)
  settingsMgr?.saveSection({ time_scheduler_on: next }).then(r => {
    toastResult(r)
    if (!r.ok) { vals.time_scheduler_on = !next; masterToggle?.setOn(!next) }
  })
}

function handleWsToggle(): void {
  const next = !vals.ws_subscribe_on
  vals.ws_subscribe_on = next; wsToggle?.setOn(next)
  settingsMgr?.saveSection({ ws_subscribe_on: next }).then(r => {
    toastResult(r)
    if (!r.ok) { vals.ws_subscribe_on = !next; wsToggle?.setOn(!next) }
  })
}

/* ── 텔레그램 탭 ── */
function renderTelegramTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('텔레그램'))

  // tele_on 토글
  const teleRow = document.createElement('div')
  Object.assign(teleRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const teleLabel = document.createElement('span')
  Object.assign(teleLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  teleLabel.textContent = '텔레그램 알림'
  teleRow.appendChild(teleLabel)
  teleToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.tele_on; vals.tele_on = next; teleToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ tele_on: next })
    toastResult(res)
    if (!res.ok) { vals.tele_on = !next; teleToggle!.setOn(!next) }
  }})
  teleRow.appendChild(teleToggle.el)
  container.appendChild(teleRow)

  // 채팅 ID / 봇 토큰
  const STR_KEYS = ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real'] as const
  const LABELS: Record<string, string> = { telegram_chat_id: '채팅 ID', telegram_bot_token_test: '테스트 봇 토큰', telegram_bot_token_real: '실전 봇 토큰' }

  for (const k of STR_KEYS) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
    const lbl = document.createElement('span')
    Object.assign(lbl.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
    lbl.textContent = LABELS[k]
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

  // 저장 버튼
  const saveRow = document.createElement('div')
  Object.assign(saveRow.style, { margin: GS.saveMargin, textAlign: 'right' })
  const saveBtn = createActionButton({
    label: '저장',
    variant: 'secondary',
    padding: GS.btnPad,
    fontSize: GS.label,
    onClick: async () => {
      const orig: Record<string, unknown> = {}
      const current: Record<string, unknown> = {}
      for (const k of STR_KEYS) {
        orig[k] = vals[k]
        current[k] = teleInputs[k]?.value ?? vals[k]
      }
      const dirty = extractDirty(orig, current, STR_KEYS as unknown as string[])
      saveBtn.textContent = '저장 중...'
      saveBtn.disabled = true
      const res = await settingsMgr!.saveSection(dirty)
      showSaveToast(res.ok ? 'saved' : 'error')
      saveBtn.textContent = '저장'
      saveBtn.disabled = false
    },
  })
  saveRow.appendChild(saveBtn)
  container.appendChild(saveRow)

  // 명령어 안내 테이블
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
  container.appendChild(tableWrap)
}

/* ── 계정관리 탭 ── */
function renderAccountTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('투자모드'))

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

function renderTestVirtualSection(): HTMLElement {
  const wrap = document.createElement('div')
  const disabled = vals.trade_mode !== 'test'
  if (disabled) { wrap.style.opacity = '0.4'; wrap.style.pointerEvents = 'none' }

  let inputAmount = Number(vals.test_virtual_deposit) || 0

  // 금액 입력 + 투자금충전
  const inputRow = document.createElement('div')
  Object.assign(inputRow.style, { display: 'flex', alignItems: 'center', gap: '8px', padding: GS.rowPad })
  const inputLabel = document.createElement('span')
  Object.assign(inputLabel.style, { fontSize: GS.label, whiteSpace: 'nowrap' })
  inputLabel.textContent = '금액입력(원):'
  inputRow.appendChild(inputLabel)

  depositInput = createMoneyInput({ value: inputAmount, onChange: v => { inputAmount = Math.max(0, v) }, style: { width: '160px' } as unknown as Partial<CSSStyleDeclaration>, name: 'deposit_amount' })
  inputRow.appendChild(depositInput.el)

  const chargeBtn = createActionButton({
    label: '투자금충전',
    variant: 'secondary',
    padding: '7px 12px',
    borderRadius: '4px',
    fontSize: GS.label,
    onClick: async () => {
      if (inputAmount <= 0) return
      try {
        const res = await api.settlementCharge(inputAmount)
        showSaveToast(res.ok ? 'saved' : 'error')
      } catch {
        showSaveToast('error')
      }
    },
  })
  inputRow.appendChild(chargeBtn)
  wrap.appendChild(inputRow)

  // 기본예수금으로 저장 버튼
  const saveRow = document.createElement('div')
  Object.assign(saveRow.style, { display: 'flex', justifyContent: 'flex-end', margin: GS.saveMargin })
  const saveDepositBtn = createActionButton({
    label: '투자금 변경',
    variant: 'secondary',
    padding: '7px 16px',
    borderRadius: '4px',
    fontSize: GS.label,
    onClick: async () => {
      const res = await settingsMgr!.saveSection({ test_virtual_deposit: inputAmount, test_virtual_balance: inputAmount })
      showSaveToast(res.ok ? 'saved' : 'error')
    },
  })
  saveRow.appendChild(saveDepositBtn)
  wrap.appendChild(saveRow)

  // 설명 텍스트
  wrap.appendChild(createDescText('누적투자금과 주문가능금액을 입력한 금액으로 변경합니다. 데이터 초기화 시에도 이 금액이 기본값으로 사용됩니다.'))

  // 읽기전용 표시
  const infoWrap = document.createElement('div')
  Object.assign(infoWrap.style, { borderTop: '1px solid ' + COLOR.borderLight, padding: GS.rowPad })

  const depRow = document.createElement('div')
  Object.assign(depRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, fontSize: GS.label })
  depRow.innerHTML = '<span>기본투자금</span>'
  depositDisplay = document.createElement('span')
  depositDisplay.textContent = `${(Number(vals.test_virtual_deposit) || 0).toLocaleString()}원`
  depRow.appendChild(depositDisplay)
  infoWrap.appendChild(depRow)
  wrap.appendChild(infoWrap)

  // 전체 초기화
  const resetWrap = document.createElement('div')
  Object.assign(resetWrap.style, { borderTop: '1px solid ' + COLOR.borderLight, padding: GS.rowPad })
  const resetBtn = createActionButton({
    label: '🔴 테스트 데이터 전체 초기화',
    variant: 'danger',
    padding: '8px 18px',
    borderRadius: '4px',
    fontSize: GS.label,
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
  resetWrap.appendChild(resetBtn)
  wrap.appendChild(resetWrap)

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

  container.appendChild(sectionTitle('실시간 데이터 통신'))

  // 실시간 연결
  const wsRow = document.createElement('div')
  Object.assign(wsRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const wsLabel = document.createElement('span')
  Object.assign(wsLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  wsLabel.textContent = '실시간 연결'
  wsRow.appendChild(wsLabel)

  const wsRight = document.createElement('span')
  wsRight.style.cssText = 'display:flex;align-items:center;'
  wsRight.appendChild(createHolidayBadge())
  wsToggle = createToggleBtn({ on: false, onClick: () => handleWsToggle() })
  wsRight.appendChild(wsToggle.el)
  wsRow.appendChild(wsRight)
  container.appendChild(wsRow)

  container.appendChild(createDescText('실시간 데이터 자동 연결 스위치 — OFF면 수동 연결만 가능'))

  // 1일봉차트 자동다운로드 (토글 + 시간 슬롯)
  const confirmedDlRow = document.createElement('div')
  Object.assign(confirmedDlRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const confirmedDlLabel = document.createElement('span')
  Object.assign(confirmedDlLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal, whiteSpace: 'nowrap' })
  confirmedDlLabel.textContent = '1일봉차트 자동다운로드'
  confirmedDlRow.appendChild(confirmedDlLabel)

  const confirmedDlRight = document.createElement('span')
  confirmedDlRight.style.cssText = 'display:flex;align-items:center;gap:10px;'

  const [cdh, cdm] = parseHM(String(vals.confirmed_download_time ?? '20:40'))
  confirmedDlH = cdh; confirmedDlM = cdm
  confirmedDlSlot = createTimeSlot(confirmedDlH, confirmedDlM, (h, m) => {
    confirmedDlH = h; confirmedDlM = m; updateTimeSlotDisplay(confirmedDlSlot!, h, m)
    scheduleConfirmedDlSave()
  })
  confirmedDlRight.appendChild(confirmedDlSlot)

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
  confirmedDlRight.appendChild(confirmedDlToggle.el)

  confirmedDlRow.appendChild(confirmedDlRight)
  container.appendChild(confirmedDlRow)
  setDisabled(confirmedDlSlot, !dlOn)

  container.appendChild(createDescText('장마감 후 자동 다운로드 시간 (기본값 20:40) — OFF 시 수동 다운로드만 가능'))

  // 실시간 현재가 플래시 효과
  const uiFlashRow = document.createElement('div')
  Object.assign(uiFlashRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const uiFlashLabel = document.createElement('span')
  Object.assign(uiFlashLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  uiFlashLabel.textContent = '실시간 현재가 플래시 효과'
  uiFlashRow.appendChild(uiFlashLabel)

  uiFlashToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.ui_price_flash_on
    vals.ui_price_flash_on = next
    uiFlashToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ ui_price_flash_on: next })
    toastResult(res)
    if (!res.ok) {
      vals.ui_price_flash_on = !next
      uiFlashToggle!.setOn(!next)
    }
  }})
  uiFlashRow.appendChild(uiFlashToggle.el)
  container.appendChild(uiFlashRow)

  container.appendChild(createDescText('실시간 시세 변경 시 노란색 플래시 깜빡임 효과 적용 여부'))

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

function renderApiFields(container: HTMLElement): void {
  container.innerHTML = ''

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

  const fields = API_FIELDS_CONFIG[activeApiTab] || []

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

  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, { textAlign: 'right', margin: GS.saveMargin })
  const saveBtn = createActionButton({
    label: '저장',
    variant: 'warning',
    padding: GS.btnPad,
    borderRadius: '4px',
    fontSize: GS.label,
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
  container.appendChild(btnRow)
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
function syncFromSettings(s: AppSettings | null): void {
  if (!s) return
  const r = s as Record<string, unknown>
  // 전체 복사 대신 변경된 키만 업데이트
  for (const k of Object.keys(r)) {
    if (vals[k] !== r[k]) {
      vals[k] = r[k]
    }
  }

  // 자동매매 탭 (항상 DOM에 존재)
  {
    masterToggle?.setOn(!!r.time_scheduler_on)
    wsToggle?.setOn(!!r.ws_subscribe_on)
    updateHolidayBadges()

    // 확정 시세 다운로드 시간 + 자동다운로드 토글
    const [cdh, cdm] = parseHM(String(r.confirmed_download_time ?? '20:40'))
    confirmedDlH = cdh; confirmedDlM = cdm
    if (confirmedDlSlot) updateTimeSlotDisplay(confirmedDlSlot, cdh, cdm)
    const dlOn = r.scheduler_market_close_on !== false
    confirmedDlToggle?.setOn(dlOn)
    if (confirmedDlSlot) setDisabled(confirmedDlSlot, !dlOn)

    // 실시간 현재가 플래시 효과
    uiFlashToggle?.setOn(r.ui_price_flash_on !== false)

    // 자동매수
    autoBuyToggle?.setOn(!!r.auto_buy_on)
    if (buyTimeHandle) {
      buyTimeHandle.setValue(String(r.buy_time_start ?? '09:00'), String(r.buy_time_end ?? '15:00'))
      buyTimeHandle.setEnabled(!!r.auto_buy_on)
    }

    // 자동매도
    autoSellToggle?.setOn(!!r.auto_sell_on)
    if (sellTimeHandle) {
      sellTimeHandle.setValue(String(r.sell_time_start ?? '09:00'), String(r.sell_time_end ?? '15:00'))
      sellTimeHandle.setEnabled(!!r.auto_sell_on)
    }
  }

  // 텔레그램 탭 (항상 DOM에 존재)
  {
    const act = document.activeElement
    teleToggle?.setOn(!!r.tele_on)
    for (const k of ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real']) {
      if (teleInputs[k]) {
        if (!act || !teleInputs[k].contains(act)) {
          teleInputs[k].value = String(r[k] || '')
        }
      }
    }
  }

  // 계정관리 탭 (항상 DOM에 존재)
  {
    if (depositDisplay) depositDisplay.textContent = `${(Number(r.test_virtual_deposit) || 0).toLocaleString()}원`
  }

  // API 설정 탭 (항상 DOM에 존재)
  {
    const act = document.activeElement
    const allApiKeys = ['kiwoom_app_key', 'kiwoom_app_secret', 'kiwoom_account_no', 'ls_app_key', 'ls_app_secret', 'ls_account_no']
    for (const k of allApiKeys) {
      if (apiKeyInputs[k]) {
        if (!act || !apiKeyInputs[k].contains(act)) {
          apiKeyInputs[k].value = String(r[k] || '')
        }
      }
    }
    // broker 값 동기화
    if (r.broker !== undefined && vals.broker !== r.broker) {
      vals.broker = r.broker
    }
    syncBrokerRadios()
  }
}

/* ── mount ── */
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

  // 모든 탭 패널 사전 렌더링 (display: none으로 숨김)
  const autoTradePanel = document.createElement('div')
  renderAutoTradeTab(autoTradePanel)

  const telegramPanel = document.createElement('div')
  renderTelegramTab(telegramPanel)

  const accountPanel = document.createElement('div')
  renderAccountTab(accountPanel)

  const apiPanel = document.createElement('div')
  renderApiSettingsTab(apiPanel)

  tabPanels = {
    'auto-trade': autoTradePanel,
    'telegram': telegramPanel,
    'account-manage': accountPanel,
    'api-settings': apiPanel,
  }

  // DOM에 추가하고 비활성 탭은 숨김
  for (const [id, panel] of Object.entries(tabPanels) as [TabId, HTMLElement][]) {
    panel.style.display = id === activeTab ? '' : 'none'
    tabContent.appendChild(panel)
  }

  syncFromSettings(initial)

  // 설정 변경 구독
  unsubSettings = settingsMgr.subscribe(() => {
    const s = settingsMgr?.getSettings()
    if (s) syncFromSettings(s)
  })

  // 거래일 확인
  api.getTradingDay()
    .then(data => { isTradingDay = data.is_trading_day; tradingDayLoading = false; updateHolidayBadges() })
    .catch(() => { isTradingDay = true; tradingDayLoading = false })
}
function unmount(): void {
  notifyPageInactive('settings')
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
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
  wsToggle = null
  holidayBadgeEls = []
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
