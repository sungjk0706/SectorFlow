// frontend/src/pages/general-settings.ts
// 일반설정 — Vanilla TS PageModule
// SettingsTabContainer.tsx + TelegramSection + AccountManageSection + TestVirtualSection 통합

import { appStore } from '../stores/appStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingsManager, extractDirty, MASKED_FIELDS, type SettingsManager } from '../settings'
import { createToggleBtn, createMoneyInput, TEXT_INPUT_WIDTH } from '../components/common/setting-row'
import { toastResult, showSaveToast } from '../components/common/save-toast'
import { createDataTable, type ColumnDef } from '../components/common/data-table'
import { api } from '../api/client'
import { parseHM, sectionTitle, createTimeSlot, updateTimeSlotDisplay } from '../components/common/settings-common'
import { FONT_SIZE, FONT_WEIGHT, createDarkInput } from '../components/common/ui-styles'
import { showPopup } from '../components/common/popup'
import type { AppSettings } from '../types'

type TabId = 'auto-trade' | 'telegram' | 'account-manage' | 'api-settings'

// 일반설정 페이지 전용 스타일 상수 (공유 FONT_SIZE와 분리)
const GS = {
  label: '14px',   // 토글/행 라벨 (기존 FONT_SIZE.label=12px → 14px)
  desc:  '12px',   // 설명 텍스트 (기존 FONT_SIZE.badge=11px → 12px)
  input: '13px',   // 입력박스 폰트
  rowPad: '10px 0', // 행 상하 패딩
  inputPad: '6px 10px', // 입력박스 패딩
  btnPad: '6px 20px',   // 저장/액션 버튼 패딩
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
let tabContent: HTMLElement | null = null
let rootEl: HTMLElement | null = null
let tabPanels: Record<TabId, HTMLElement> | null = null

// 자동매매 탭 참조
let masterToggle: ReturnType<typeof createToggleBtn> | null = null
let holidayToggle: ReturnType<typeof createToggleBtn> | null = null
let wsToggle: ReturnType<typeof createToggleBtn> | null = null
let wsTimePairWrap: HTMLElement | null = null
let holidayBadgeEls: HTMLElement[] = []
let holidayToggleRow: HTMLElement | null = null

// TimePairInput
let wsSH = '09', wsSM = '00', wsEH = '15', wsEM = '00'
let wsStartSlot: HTMLElement | null = null
let wsEndSlot: HTMLElement | null = null
let savingTime = false
let pendingTimeSave: { startKey: string; endKey: string } | null = null

// 텔레그램 탭 참조
let teleToggle: ReturnType<typeof createToggleBtn> | null = null
let teleInputs: Record<string, HTMLInputElement> = {}

// 계정관리 탭 참조
let tradeModeSection: HTMLElement | null = null
let testVirtualSection: HTMLElement | null = null
let depositInput: ReturnType<typeof createMoneyInput> | null = null
let depositDisplay: HTMLElement | null = null

// API 설정 탭 참조
let apiKeyInputs: Record<string, HTMLInputElement> = {}

/* ── 헬퍼 ── */
function shouldForceOff(): boolean {
  return !tradingDayLoading && !isTradingDay && !!vals.holiday_guard_on
}

function createHolidayBadge(): HTMLElement {
  const span = document.createElement('span')
  Object.assign(span.style, { fontSize: FONT_SIZE.chip, color: '#d32f2f', background: '#ffeaea', borderRadius: '4px', padding: '1px 6px', marginLeft: '6px', fontWeight: FONT_WEIGHT.normal, display: 'none' })
  span.textContent = '비거래일'
  holidayBadgeEls.push(span)
  return span
}

function updateHolidayBadges(): void {
  const show = shouldForceOff()
  for (const el of holidayBadgeEls) el.style.display = show ? 'inline' : 'none'
}

/* ── TimePairInput (인라인 — 공통 컴포넌트 사용) ── */
function createTimePairInput(startKey: string, endKey: string): HTMLElement {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 0' })
  wsStartSlot = createTimeSlot(wsSH, wsSM, (h, m) => {
    wsSH = h; wsSM = m; updateTimeSlotDisplay(wsStartSlot!, h, m); scheduleTimeSave(startKey, endKey)
  })
  wsEndSlot = createTimeSlot(wsEH, wsEM, (h, m) => {
    wsEH = h; wsEM = m; updateTimeSlotDisplay(wsEndSlot!, h, m); scheduleTimeSave(startKey, endKey)
  })
  const tilde = document.createElement('span')
  Object.assign(tilde.style, { color: '#999', fontSize: FONT_SIZE.badge, margin: '0 2px' })
  tilde.textContent = '~'
  wrap.appendChild(wsStartSlot); wrap.appendChild(tilde); wrap.appendChild(wsEndSlot)
  wsTimePairWrap = wrap
  return wrap
}

function scheduleTimeSave(startKey: string, endKey: string): void {
  if (!settingsMgr) return
  if (savingTime) {
    pendingTimeSave = { startKey, endKey }
    return
  }
  savingTime = true
  const run = async (sk: string, ek: string): Promise<void> => {
    const serverStart = String(vals[sk] ?? ''), serverEnd = String(vals[ek] ?? '')
    const newStart = `${wsSH}:${wsSM}`, newEnd = `${wsEH}:${wsEM}`
    const dirty: Record<string, unknown> = {}
    if (newStart !== serverStart) dirty[sk] = newStart
    if (newEnd !== serverEnd) dirty[ek] = newEnd
    if (Object.keys(dirty).length > 0) {
      const res = await settingsMgr!.saveSection(dirty)
      toastResult(res)
    }
    if (pendingTimeSave) {
      const next = pendingTimeSave
      pendingTimeSave = null
      await run(next.startKey, next.endKey)
    }
    savingTime = false
  }
  run(startKey, endKey)
}

/* ── 탭 렌더링 ── */
function renderTabBar(): HTMLElement {
  const bar = document.createElement('div')
  Object.assign(bar.style, { display: 'flex', borderBottom: '1px solid #ddd', marginBottom: '12px' })

  const tabs: { id: TabId; label: string }[] = [
    { id: 'auto-trade', label: '자동매매' },
    { id: 'account-manage', label: '거래모드' },
    { id: 'telegram', label: '텔레그램' },
    { id: 'api-settings', label: 'API 설정' },
  ]

  for (const tab of tabs) {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.dataset.tabId = tab.id
    const isActive = activeTab === tab.id
    Object.assign(btn.style, {
      padding: '8px 16px', cursor: 'pointer', border: 'none', background: 'transparent', fontSize: FONT_SIZE.tab,
      borderBottom: isActive ? '2px solid #1976d2' : '2px solid transparent',
      fontWeight: isActive ? FONT_WEIGHT.normal : FONT_WEIGHT.normal,
      color: isActive ? '#1976d2' : '#666',
    })
    btn.textContent = tab.label
    btn.addEventListener('click', () => { activeTab = tab.id; refreshUI() })
    bar.appendChild(btn)
  }
  return bar
}

function refreshUI(): void {
  if (!rootEl || !tabContent || !tabPanels) return
  // 탭 바 재렌더링
  const oldBar = tabBar
  tabBar = renderTabBar()
  if (oldBar && oldBar.parentNode) oldBar.parentNode.replaceChild(tabBar, oldBar)

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
  Object.assign(masterRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad })
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

  const descLabel1 = document.createElement('div')
  Object.assign(descLabel1.style, { fontSize: GS.desc, color: '#888', padding: '0 0 4px', marginTop: '-4px' })
  descLabel1.textContent = '거래일 설정시간 내에서만 자동 매수/매도 실행'
  container.appendChild(descLabel1)

  // 공휴일 자동매매 차단
  const hRow = document.createElement('div')
  Object.assign(hRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px' })
  const hLabel = document.createElement('span')
  Object.assign(hLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  hLabel.textContent = '공휴일 자동매매 차단'
  hRow.appendChild(hLabel)
  holidayToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.holiday_guard_on
    vals.holiday_guard_on = next; holidayToggle!.setOn(next)
    const res = await settingsMgr!.saveSection({ holiday_guard_on: next })
    toastResult(res)
    updateHolidayBadges()
    updateAutoTradeDisabledStates()
  }})
  hRow.appendChild(holidayToggle.el)
  holidayToggleRow = hRow
  container.appendChild(hRow)

  const descLabel2 = document.createElement('div')
  Object.assign(descLabel2.style, { fontSize: GS.desc, color: '#888', padding: '0 0 4px', marginTop: '-4px', paddingLeft: '20px' })
  descLabel2.textContent = 'ON: 공휴일에 자동매매 차단 · OFF: 공휴일에도 허용'
  container.appendChild(descLabel2)

  // 실시간 연결
  const wsRow = document.createElement('div')
  Object.assign(wsRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad })
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

  const descLabel3 = document.createElement('div')
  Object.assign(descLabel3.style, { fontSize: GS.desc, color: '#888', padding: '0 0 4px', marginTop: '-4px' })
  descLabel3.textContent = '시세·체결 실시간 수신 ON/OFF'
  container.appendChild(descLabel3)

  // 실시간 연결 시간
  const wsTimeRow = document.createElement('div')
  wsTimeRow.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 0;'
  const wsTimeLabel = document.createElement('span')
  Object.assign(wsTimeLabel.style, { minWidth: '110px', fontSize: GS.label, whiteSpace: 'nowrap' })
  wsTimeLabel.textContent = '실시간 연결 시간'
  wsTimeRow.appendChild(wsTimeLabel)
  wsTimeRow.appendChild(createTimePairInput('ws_subscribe_start', 'ws_subscribe_end'))
  wsTimeRow.appendChild(createHolidayBadge())
  container.appendChild(wsTimeRow)

  const descLabel4 = document.createElement('div')
  Object.assign(descLabel4.style, { fontSize: GS.desc, color: '#888', padding: '0 0 4px', marginTop: '-4px' })
  descLabel4.textContent = '실시간 시세 수신 시작/종료 시간'
  container.appendChild(descLabel4)
}

function handleMasterToggle(): void {
  if (shouldForceOff()) {
    const p = document.createElement('p')
    Object.assign(p.style, { margin: '0', fontSize: FONT_SIZE.label, color: '#333' })
    p.textContent = '오늘은 KRX 비거래일입니다. 자동매매가 실행되지 않습니다.'
    showPopup('거래일이 아닙니다', p, [
      { label: '확인', onClick: () => {
        settingsMgr?.saveSection({ time_scheduler_on: true, holiday_guard_on: false }).then(r => toastResult(r))
      }, variant: 'primary' },
    ])
    return
  }
  const next = !vals.time_scheduler_on
  vals.time_scheduler_on = next; masterToggle?.setOn(next)
  updateAutoTradeDisabledStates()
  settingsMgr?.saveSection({ time_scheduler_on: next }).then(r => {
    toastResult(r)
    if (!r.ok) { vals.time_scheduler_on = !next; masterToggle?.setOn(!next); updateAutoTradeDisabledStates() }
  })
}

function handleWsToggle(): void {
  if (shouldForceOff()) {
    const p = document.createElement('p')
    Object.assign(p.style, { margin: '0', fontSize: FONT_SIZE.label, color: '#333' })
    p.textContent = '오늘은 KRX 비거래일입니다. 자동매매가 실행되지 않습니다.'
    showPopup('거래일이 아닙니다', p, [
      { label: '확인', onClick: () => {
        settingsMgr?.saveSection({ ws_subscribe_on: true, holiday_guard_on: false }).then(r => toastResult(r))
      }, variant: 'primary' },
    ])
    return
  }
  const next = !vals.ws_subscribe_on
  vals.ws_subscribe_on = next; wsToggle?.setOn(next)
  updateWsTimeDisabled()
  settingsMgr?.saveSection({ ws_subscribe_on: next }).then(r => {
    toastResult(r)
    if (!r.ok) { vals.ws_subscribe_on = !next; wsToggle?.setOn(!next); updateWsTimeDisabled() }
  })
}

function updateAutoTradeDisabledStates(): void {
  if (holidayToggleRow) {
    holidayToggleRow.style.opacity = vals.time_scheduler_on ? '1' : '0.45'
    holidayToggleRow.style.pointerEvents = vals.time_scheduler_on ? 'auto' : 'none'
  }
}

function updateWsTimeDisabled(): void {
  if (wsTimePairWrap) {
    const disabled = shouldForceOff() || !vals.ws_subscribe_on
    wsTimePairWrap.style.opacity = disabled ? '0.5' : '1'
    wsTimePairWrap.style.pointerEvents = disabled ? 'none' : 'auto'
  }
}

/* ── 텔레그램 탭 ── */
function renderTelegramTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('텔레그램'))

  // tele_on 토글
  const teleRow = document.createElement('div')
  Object.assign(teleRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad })
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
  const STR_KEYS = ['telegram_chat_id', 'telegram_bot_token'] as const
  const LABELS: Record<string, string> = { telegram_chat_id: '채팅 ID', telegram_bot_token: '봇 토큰' }

  for (const k of STR_KEYS) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: '1px solid #eee' })
    const lbl = document.createElement('span')
    Object.assign(lbl.style, { fontSize: GS.label })
    lbl.textContent = LABELS[k]
    row.appendChild(lbl)
    const input = document.createElement('input')
    input.type = MASKED_FIELDS.has(k) ? 'password' : 'text'
    input.value = String(vals[k] || '')
    Object.assign(input.style, { width: `${TEXT_INPUT_WIDTH}px`, padding: GS.inputPad, borderRadius: '4px', border: '1px solid #ccc', fontSize: GS.input })
    input.addEventListener('input', () => { teleInputs[k] = input })
    teleInputs[k] = input
    row.appendChild(input)
    container.appendChild(row)
  }

  // 저장 버튼
  const saveRow = document.createElement('div')
  Object.assign(saveRow.style, { marginTop: '12px', textAlign: 'right' })
  const saveBtn = document.createElement('button')
  saveBtn.type = 'button'
  Object.assign(saveBtn.style, { padding: GS.btnPad, borderRadius: '6px', border: '1px solid #ccc', cursor: 'pointer', fontSize: GS.label })
  saveBtn.textContent = '저장'
  saveBtn.addEventListener('click', async () => {
    const orig: Record<string, unknown> = {}
    const current: Record<string, unknown> = {}
    for (const k of STR_KEYS) {
      orig[k] = vals[k]
      current[k] = teleInputs[k]?.value ?? vals[k]
    }
    const dirty = extractDirty(orig, current, STR_KEYS as unknown as string[])
    saveBtn.textContent = '저장 중...'
    saveBtn.setAttribute('disabled', 'true')
    const res = await settingsMgr!.saveSection(dirty)
    showSaveToast(res.ok ? 'saved' : 'error')
    saveBtn.textContent = '저장'
    saveBtn.removeAttribute('disabled')
  })
  saveRow.appendChild(saveBtn)
  container.appendChild(saveRow)

  // 명령어 안내 테이블
  interface CommandRow { cmd: string; desc: string }
  const COMMAND_COLUMNS: ColumnDef<CommandRow>[] = [
    { key: 'cmd', label: '명령어', align: 'center', minWidth: 60, render: r => r.cmd },
    { key: 'desc', label: '설명', align: 'left', render: r => r.desc },
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
  container.appendChild(sectionTitle('거래모드'))

  // 거래모드 선택 (중앙정렬)
  tradeModeSection = document.createElement('div')
  Object.assign(tradeModeSection.style, { display: 'flex', alignItems: 'center', justifyContent: 'center', padding: GS.rowPad, borderBottom: '1px solid #f0f0f0', gap: '24px' })

  for (const v of ['test', 'real'] as const) {
    const label = document.createElement('label')
    label.style.cssText = 'cursor:pointer;display:flex;align-items:center;gap:6px;font-size:' + GS.label
    const radio = document.createElement('input')
    radio.type = 'radio'; radio.name = 'trade-mode-acct'
    radio.checked = vals.trade_mode === v
    radio.addEventListener('change', () => handleTradeMode(v))
    label.appendChild(radio)
    label.appendChild(document.createTextNode(v === 'test' ? '테스트' : '실전투자'))
    tradeModeSection.appendChild(label)
  }
  container.appendChild(tradeModeSection)

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
    Object.assign(msg.style, { fontSize: FONT_SIZE.label, color: '#555', lineHeight: '1.6' })
    msg.innerHTML = '실전투자 모드로 전환하시겠습니까?<br><span style="color:#dc3545;font-weight:500">실제 돈으로 매매가 실행됩니다.</span>'
    showPopup('⚠️ 실전투자 모드 전환', msg, [
      { label: '취소', onClick: () => {} },
      { label: '전환', onClick: async () => {
        vals.trade_mode = 'real'
        const res = await settingsMgr!.saveSection({ trade_mode: 'real', test_mode: false, kiwoom_mock_mode: false, mode_real: true })
        if (!res.ok) vals.trade_mode = 'test'
        syncTradeMode()
      }, variant: 'danger' },
    ])
    return
  }

  vals.trade_mode = val
  const isReal = val === 'real'
  settingsMgr?.saveSection({ trade_mode: val, test_mode: !isReal, kiwoom_mock_mode: !isReal, mode_real: isReal }).then(res => {
    if (!res.ok) vals.trade_mode = 'test'
    syncTradeMode()
  })
}

function syncTradeMode(): void {
  // 라디오 버튼 상태 업데이트
  if (tradeModeSection) {
    const radios = tradeModeSection.querySelectorAll<HTMLInputElement>('input[type="radio"]')
    radios.forEach(r => { r.checked = (r.parentElement?.textContent?.includes('테스트') ? 'test' : 'real') === vals.trade_mode })
  }
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
  inputRow.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 0;'
  const inputLabel = document.createElement('span')
  Object.assign(inputLabel.style, { fontSize: GS.label, whiteSpace: 'nowrap' })
  inputLabel.textContent = '금액입력(원):'
  inputRow.appendChild(inputLabel)

  depositInput = createMoneyInput({ value: inputAmount, onChange: v => { inputAmount = Math.max(0, v) }, style: { width: '160px' } as unknown as Partial<CSSStyleDeclaration>, name: 'deposit_amount' })
  inputRow.appendChild(depositInput.el)

  const chargeBtn = document.createElement('button')
  chargeBtn.type = 'button'
  Object.assign(chargeBtn.style, { padding: '7px 12px', borderRadius: '4px', border: '1px solid #ccc', background: '#f8f9fa', cursor: 'pointer', fontSize: GS.label })
  chargeBtn.textContent = '투자금충전'
  chargeBtn.addEventListener('click', async () => {
    if (inputAmount <= 0) return
    try {
      const res = await api.settlementCharge(inputAmount)
      showSaveToast(res.ok ? 'saved' : 'error')
    } catch {
      showSaveToast('error')
    }
  })
  inputRow.appendChild(chargeBtn)
  wrap.appendChild(inputRow)

  // 기본예수금으로 저장 버튼
  const saveRow = document.createElement('div')
  saveRow.style.cssText = 'display:flex;justify-content:flex-end;padding:4px 0 10px;'
  const saveDepositBtn = document.createElement('button')
  saveDepositBtn.type = 'button'
  Object.assign(saveDepositBtn.style, { padding: '7px 16px', borderRadius: '4px', border: '1px solid #ccc', background: '#f8f9fa', cursor: 'pointer', fontSize: GS.label })
  saveDepositBtn.textContent = '투자금 변경'
  saveDepositBtn.addEventListener('click', async () => {
    const res = await settingsMgr!.saveSection({ test_virtual_deposit: inputAmount, test_virtual_balance: inputAmount })
    showSaveToast(res.ok ? 'saved' : 'error')
  })
  saveRow.appendChild(saveDepositBtn)
  wrap.appendChild(saveRow)

  // 설명 텍스트
  const hintRow = document.createElement('div')
  Object.assign(hintRow.style, { fontSize: '11px', color: '#888', padding: '2px 0 8px', textAlign: 'right' })
  hintRow.textContent = '누적투자금과 주문가능금액을 입력한 금액으로 변경합니다. 데이터 초기화 시에도 이 금액이 기본값으로 사용됩니다.'
  wrap.appendChild(hintRow)

  // 읽기전용 표시
  const infoWrap = document.createElement('div')
  infoWrap.style.cssText = 'border-top:1px solid #eee;padding:8px 0;'

  const depRow = document.createElement('div')
  depRow.style.cssText = `display:flex;justify-content:space-between;align-items:center;padding:8px 0;font-size:${GS.label};`
  depRow.innerHTML = '<span>기본투자금</span>'
  depositDisplay = document.createElement('span')
  depositDisplay.textContent = `${(Number(vals.test_virtual_deposit) || 0).toLocaleString()}원`
  depRow.appendChild(depositDisplay)
  infoWrap.appendChild(depRow)
  wrap.appendChild(infoWrap)

  // 전체 초기화
  const resetWrap = document.createElement('div')
  resetWrap.style.cssText = 'border-top:1px solid #eee;padding:10px 0;'
  const resetBtn = document.createElement('button')
  resetBtn.type = 'button'
  Object.assign(resetBtn.style, { padding: '8px 18px', borderRadius: '4px', border: '1px solid #dc3545', background: '#dc3545', color: '#fff', cursor: 'pointer', fontSize: GS.label })
  resetBtn.textContent = '🔴 테스트 데이터 전체 초기화'
  resetBtn.addEventListener('click', async () => {
    if (!window.confirm('테스트 데이터를 전체 초기화하시겠습니까?\n가상 보유종목, 매매 이력, 투자금이 모두 초기화됩니다.')) return
    try { await api.resetTestData(); showSaveToast('saved') } catch { alert('초기화 실패') }
  })
  resetWrap.appendChild(resetBtn)
  wrap.appendChild(resetWrap)

  return wrap
}

/* ── API 설정 탭 ── */
function renderApiSettingsTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('키움증권 API 인증 정보'))

  const API_FIELDS: { key: string; label: string; type: 'password' | 'text' }[] = [
    { key: 'kiwoom_app_key_real', label: '앱키', type: 'password' },
    { key: 'kiwoom_app_secret_real', label: '앱시크릿', type: 'password' },
    { key: 'kiwoom_account_no_real', label: '계좌번호', type: 'text' },
  ]

  const fieldsWrap = document.createElement('div')

  for (const field of API_FIELDS) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: '1px solid #eee' })
    const lbl = document.createElement('span')
    Object.assign(lbl.style, { fontSize: GS.label, flex: '1' })
    lbl.textContent = field.label
    row.appendChild(lbl)

    const input = createDarkInput(field.type)
    input.value = String(vals[field.key] || '')
    apiKeyInputs[field.key] = input
    row.appendChild(input)
    fieldsWrap.appendChild(row)
  }

  container.appendChild(fieldsWrap)

  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, { textAlign: 'right', marginTop: '10px' })
  const saveBtn = document.createElement('button')
  saveBtn.type = 'button'
  Object.assign(saveBtn.style, {
    padding: GS.btnPad, borderRadius: '4px',
    border: '1px solid #FF8C00', background: 'transparent',
    color: '#FF8C00', cursor: 'pointer', fontSize: GS.label,
  })
  saveBtn.textContent = '저장'
  saveBtn.addEventListener('click', async () => {
    const keys = API_FIELDS.map(f => f.key)
    const orig: Record<string, unknown> = {}
    const current: Record<string, unknown> = {}
    for (const k of keys) {
      orig[k] = vals[k]
      current[k] = apiKeyInputs[k]?.value ?? vals[k]
    }
    const dirty = extractDirty(orig, current, keys)
    if (Object.keys(dirty).length === 0) return
    saveBtn.textContent = '저장 중...'
    saveBtn.setAttribute('disabled', 'true')
    const res = await settingsMgr!.saveSection(dirty)
    showSaveToast(res.ok ? 'saved' : 'error')
    saveBtn.textContent = '저장'
    saveBtn.removeAttribute('disabled')
  })
  btnRow.appendChild(saveBtn)
  container.appendChild(btnRow)
}

/* ── 설정 동기화 ── */
function syncFromSettings(s: AppSettings | null): void {
  if (!s) return
  const r = s as unknown as Record<string, unknown>
  vals = { ...r }

  // 자동매매 탭 (항상 DOM에 존재)
  {
    const forceOff = shouldForceOff()
    masterToggle?.setOn(forceOff ? false : !!r.time_scheduler_on)
    holidayToggle?.setOn(!!r.holiday_guard_on)
    wsToggle?.setOn(forceOff ? false : !!r.ws_subscribe_on)
    updateHolidayBadges()
    updateAutoTradeDisabledStates()

    // TimePairInput
    const [sh, sm] = parseHM(String(r.ws_subscribe_start ?? ''))
    const [eh, em] = parseHM(String(r.ws_subscribe_end ?? ''))
    wsSH = sh; wsSM = sm; wsEH = eh; wsEM = em
    if (wsStartSlot) updateTimeSlotDisplay(wsStartSlot, sh, sm)
    if (wsEndSlot) updateTimeSlotDisplay(wsEndSlot, eh, em)
    updateWsTimeDisabled()
  }

  // 텔레그램 탭 (항상 DOM에 존재)
  {
    teleToggle?.setOn(!!r.tele_on)
    for (const k of ['telegram_chat_id', 'telegram_bot_token']) {
      if (teleInputs[k]) teleInputs[k].value = String(r[k] || '')
    }
  }

  // 계정관리 탭 (항상 DOM에 존재)
  {
    if (depositDisplay) depositDisplay.textContent = `${(Number(r.test_virtual_deposit) || 0).toLocaleString()}원`
  }

  // API 설정 탭 (항상 DOM에 존재)
  {
    for (const k of ['kiwoom_app_key_real', 'kiwoom_app_secret_real', 'kiwoom_account_no_real']) {
      if (apiKeyInputs[k]) apiKeyInputs[k].value = String(r[k] || '')
    }
  }
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('settings')
  settingsMgr = createSettingsManager(appStore)
  vals = {}
  activeTab = 'auto-trade'
  holidayBadgeEls = []
  isTradingDay = true
  tradingDayLoading = true

  rootEl = document.createElement('div')

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
    vals = { ...(initial as unknown as Record<string, unknown>) }
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
    .then(data => { isTradingDay = data.is_trading_day; tradingDayLoading = false; updateHolidayBadges(); updateWsTimeDisabled() })
    .catch(() => { isTradingDay = true; tradingDayLoading = false })
}

/* ── unmount ── */
function unmount(): void {
  notifyPageInactive('settings')
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  savingTime = false
  pendingTimeSave = null
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
  tabBar = null; tabContent = null; rootEl = null; tabPanels = null
  masterToggle = null; holidayToggle = null; wsToggle = null; wsTimePairWrap = null
  holidayBadgeEls = []; holidayToggleRow = null
  teleToggle = null; teleInputs = {}
  tradeModeSection = null; testVirtualSection = null
  depositInput = null; depositDisplay = null
  wsStartSlot = null; wsEndSlot = null
  apiKeyInputs = {}
  vals = {}
}

export default { mount, unmount }
