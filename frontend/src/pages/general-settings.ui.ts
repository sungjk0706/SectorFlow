// frontend/src/pages/general-settings.ui.ts
// 일반설정 — 순수 UI 껍데기 (Dumb Component)
// 비즈니스 로직 제거, Props로 데이터 수신

import { createToggleBtn, createMoneyInput, TEXT_INPUT_WIDTH } from '../components/common/setting-row'
import { createDataTable, type ColumnDef } from '../components/common/data-table'
import { parseHM, sectionTitle, createTimeSlot, updateTimeSlotDisplay } from '../components/common/settings-common'
import { FONT_SIZE, FONT_WEIGHT, createDarkInput } from '../components/common/ui-styles'
import { createGlobalWsBadge } from '../settings'

type TabId = 'auto-trade' | 'telegram' | 'account-manage' | 'api-settings'
type BrokerTabId = 'kiwoom' | 'ls'

// 일반설정 페이지 전용 스타일 상수 (공유 FONT_SIZE와 분리)
const GS = {
  label: '14px',   // 토글/행 라벨 (기존 FONT_SIZE.label=12px → 14px)
  desc:  '12px',   // 설명 텍스트 (기존 FONT_SIZE.badge=11px → 12px)
  input: '13px',   // 입력박스 폰트
  rowPad: '10px 0', // 행 상하 패딩
  inputPad: '6px 10px', // 입력박스 패딩
  btnPad: '6px 20px',   // 저장/액션 버튼 패딩
} as const

// ── Props 타입 정의 ──

export interface GeneralSettingsProps {
  // 현재 설정 값
  settings: Record<string, unknown>
  
  // 거래일 상태
  isTradingDay: boolean
  tradingDayLoading: boolean
  
  // WS 구독 상태
  wsSubscribed: boolean
  
  // 이벤트 핸들러 (비즈니스 로직 대신 Props로 받음)
  onMasterToggle: () => void
  onHolidayToggle: (value: boolean) => void
  onWsToggle: () => void
  onWsTimeChange: (start: string, end: string) => void
  onTeleToggle: (value: boolean) => void
  onTeleSave: (chatId: string, botToken: string) => void
  onTradeModeChange: (mode: 'test' | 'real') => void
  onDepositCharge: (amount: number) => void
  onDepositChange: (amount: number) => void
  onTestDataReset: () => void
  onApiSave: (appKey: string, appSecret: string, accountNo: string) => void
}

let props: GeneralSettingsProps

// 모듈 상태 (UI 전용)
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
let wsBadge: HTMLElement | null = null

// TimePairInput
let wsSH = '09', wsSM = '00', wsEH = '15', wsEM = '00'
let wsStartSlot: HTMLElement | null = null
let wsEndSlot: HTMLElement | null = null

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
let activeBrokerTab: BrokerTabId = 'kiwoom'
let brokerTabBar: HTMLElement | null = null
let brokerTabPanels: Record<BrokerTabId, HTMLElement> | null = null

/* ── 헬퍼 ── */
function shouldForceOff(): boolean {
  return !props.tradingDayLoading && !props.isTradingDay && !!props.settings.holiday_guard_on
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
function createTimePairInput(): HTMLElement {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 0' })
  wsStartSlot = createTimeSlot(wsSH, wsSM, (h, m) => {
    wsSH = h; wsSM = m; updateTimeSlotDisplay(wsStartSlot!, h, m); props.onWsTimeChange(`${wsSH}:${wsSM}`, `${wsEH}:${wsEM}`)
  })
  wsEndSlot = createTimeSlot(wsEH, wsEM, (h, m) => {
    wsEH = h; wsEM = m; updateTimeSlotDisplay(wsEndSlot!, h, m); props.onWsTimeChange(`${wsSH}:${wsSM}`, `${wsEH}:${wsEM}`)
  })
  const tilde = document.createElement('span')
  Object.assign(tilde.style, { color: '#999', fontSize: FONT_SIZE.badge, margin: '0 2px' })
  tilde.textContent = '~'
  wrap.appendChild(wsStartSlot); wrap.appendChild(tilde); wrap.appendChild(wsEndSlot)
  wsTimePairWrap = wrap
  return wrap
}

/* ── 탭 렌더링 ── */
function renderTabBar(): HTMLElement {
  const bar = document.createElement('div')
  Object.assign(bar.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #ddd', marginBottom: '12px' })

  const tabs: { id: TabId; label: string }[] = [
    { id: 'auto-trade', label: '자동매매' },
    { id: 'account-manage', label: '거래모드' },
    { id: 'telegram', label: '텔레그램' },
    { id: 'api-settings', label: 'API 설정' },
  ]

  const btnGroup = document.createElement('div')
  btnGroup.style.display = 'flex'

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
    btnGroup.appendChild(btn)
  }
  bar.appendChild(btnGroup)

  // WS 상태 배지
  wsBadge = createGlobalWsBadge()
  bar.appendChild(wsBadge)

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

  syncFromSettings()
}

/* ── 자동매매 탭 ── */
function renderAutoTradeTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('자동매매'))

  const vals = props.settings
  const forceOff = shouldForceOff()

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
  masterToggle = createToggleBtn({ on: forceOff ? false : !!vals.time_scheduler_on, onClick: () => props.onMasterToggle() })
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
  holidayToggle = createToggleBtn({ on: !!vals.holiday_guard_on, onClick: async () => {
    const next = !vals.holiday_guard_on
    holidayToggle!.setOn(next)
    props.onHolidayToggle(next)
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
  wsToggle = createToggleBtn({ on: forceOff ? false : !!vals.ws_subscribe_on, onClick: () => props.onWsToggle() })
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
  wsTimeRow.appendChild(createTimePairInput())
  wsTimeRow.appendChild(createHolidayBadge())
  container.appendChild(wsTimeRow)

  const descLabel4 = document.createElement('div')
  Object.assign(descLabel4.style, { fontSize: GS.desc, color: '#888', padding: '0 0 4px', marginTop: '-4px' })
  descLabel4.textContent = '실시간 시세 수신 시작/종료 시간'
  container.appendChild(descLabel4)

  updateAutoTradeDisabledStates()
  updateWsTimeDisabled()
}

function updateAutoTradeDisabledStates(): void {
  const vals = props.settings
  if (holidayToggleRow) {
    holidayToggleRow.style.opacity = vals.time_scheduler_on ? '1' : '0.45'
    holidayToggleRow.style.pointerEvents = vals.time_scheduler_on ? 'auto' : 'none'
  }
}

function updateWsTimeDisabled(): void {
  const vals = props.settings
  if (wsTimePairWrap) {
    const disabled = shouldForceOff() || !vals.ws_subscribe_on
    wsTimePairWrap.style.opacity = disabled ? '0.5' : '1'
    wsTimePairWrap.style.pointerEvents = disabled ? 'none' : 'auto'
  }
}

/* ── 텔레그램 탭 ── */
function renderTelegramTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('텔레그램'))

  const vals = props.settings

  // tele_on 토글
  const teleRow = document.createElement('div')
  Object.assign(teleRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad })
  const teleLabel = document.createElement('span')
  Object.assign(teleLabel.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  teleLabel.textContent = '텔레그램 알림'
  teleRow.appendChild(teleLabel)
  teleToggle = createToggleBtn({ on: !!vals.tele_on, onClick: async () => {
    const next = !vals.tele_on; teleToggle!.setOn(next)
    props.onTeleToggle(next)
  }})
  teleRow.appendChild(teleToggle.el)
  container.appendChild(teleRow)

  // 채팅 ID / 봇 토큰
  const STR_KEYS = ['telegram_chat_id', 'telegram_bot_token'] as const
  const LABELS: Record<string, string> = { telegram_chat_id: '채팅 ID', telegram_bot_token: '봇 토큰' }
  const MASKED_FIELDS = new Set(['telegram_bot_token'])

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
    const chatId = teleInputs['telegram_chat_id']?.value ?? String(vals.telegram_chat_id ?? '')
    const botToken = teleInputs['telegram_bot_token']?.value ?? String(vals.telegram_bot_token ?? '')
    props.onTeleSave(chatId, botToken)
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

  const vals = props.settings

  // 거래모드 선택 (중앙정렬)
  tradeModeSection = document.createElement('div')
  Object.assign(tradeModeSection.style, { display: 'flex', alignItems: 'center', justifyContent: 'center', padding: GS.rowPad, borderBottom: '1px solid #f0f0f0', gap: '24px' })

  for (const v of ['test', 'real'] as const) {
    const label = document.createElement('label')
    label.style.cssText = 'cursor:pointer;display:flex;align-items:center;gap:6px;font-size:' + GS.label
    const radio = document.createElement('input')
    radio.type = 'radio'; radio.name = 'trade-mode-acct'
    radio.checked = vals.trade_mode === v
    radio.addEventListener('change', () => props.onTradeModeChange(v))
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

function renderTestVirtualSection(): HTMLElement {
  const wrap = document.createElement('div')
  const vals = props.settings
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
    props.onDepositCharge(inputAmount)
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
    props.onDepositChange(inputAmount)
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
    props.onTestDataReset()
  })
  resetWrap.appendChild(resetBtn)
  wrap.appendChild(resetWrap)

  return wrap
}

/* ── API 설정 탭 ── */
function renderApiSettingsTab(container: HTMLElement): void {
  container.appendChild(sectionTitle('증권사 API 인증 정보'))

  // 증권사 탭 바
  brokerTabBar = document.createElement('div')
  Object.assign(brokerTabBar.style, { display: 'flex', gap: '8px', marginBottom: '12px', borderBottom: '1px solid #ddd' })

  const brokerTabs: { id: BrokerTabId; label: string }[] = [
    { id: 'kiwoom', label: '키움증권' },
    { id: 'ls', label: 'LS증권' },
  ]

  for (const tab of brokerTabs) {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.dataset.brokerTabId = tab.id
    const isActive = activeBrokerTab === tab.id
    Object.assign(btn.style, {
      padding: '6px 12px', cursor: 'pointer', border: 'none', background: 'transparent', fontSize: FONT_SIZE.tab,
      borderBottom: isActive ? '2px solid #1976d2' : '2px solid transparent',
      fontWeight: isActive ? FONT_WEIGHT.normal : FONT_WEIGHT.normal,
      color: isActive ? '#1976d2' : '#666',
    })
    btn.textContent = tab.label
    btn.addEventListener('click', () => { activeBrokerTab = tab.id; refreshBrokerTabs() })
    brokerTabBar.appendChild(btn)
  }
  container.appendChild(brokerTabBar)

  // 증권사 탭 패널 컨테이너
  const brokerTabContent = document.createElement('div')
  container.appendChild(brokerTabContent)

  // 키움증권 패널
  const kiwoomPanel = document.createElement('div')
  renderKiwoomApiPanel(kiwoomPanel)

  // LS증권 패널
  const lsPanel = document.createElement('div')
  renderLsApiPanel(lsPanel)

  brokerTabPanels = {
    'kiwoom': kiwoomPanel,
    'ls': lsPanel,
  }

  // DOM에 추가하고 비활성 탭은 숨김
  for (const [id, panel] of Object.entries(brokerTabPanels) as [BrokerTabId, HTMLElement][]) {
    panel.style.display = id === activeBrokerTab ? '' : 'none'
    brokerTabContent.appendChild(panel)
  }
}

function refreshBrokerTabs(): void {
  if (!brokerTabBar || !brokerTabPanels) return

  // 탭 바 재렌더링
  const oldBar = brokerTabBar
  const container = oldBar.parentNode
  if (container) {
    brokerTabBar = document.createElement('div')
    Object.assign(brokerTabBar.style, { display: 'flex', gap: '8px', marginBottom: '12px', borderBottom: '1px solid #ddd' })

    const brokerTabs: { id: BrokerTabId; label: string }[] = [
      { id: 'kiwoom', label: '키움증권' },
      { id: 'ls', label: 'LS증권' },
    ]

    for (const tab of brokerTabs) {
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.dataset.brokerTabId = tab.id
      const isActive = activeBrokerTab === tab.id
      Object.assign(btn.style, {
        padding: '6px 12px', cursor: 'pointer', border: 'none', background: 'transparent', fontSize: FONT_SIZE.tab,
        borderBottom: isActive ? '2px solid #1976d2' : '2px solid transparent',
        fontWeight: isActive ? FONT_WEIGHT.normal : FONT_WEIGHT.normal,
        color: isActive ? '#1976d2' : '#666',
      })
      btn.textContent = tab.label
      btn.addEventListener('click', () => { activeBrokerTab = tab.id; refreshBrokerTabs() })
      brokerTabBar.appendChild(btn)
    }
    container.replaceChild(brokerTabBar, oldBar)
  }

  // 탭 패널 display 토글
  for (const [id, panel] of Object.entries(brokerTabPanels) as [BrokerTabId, HTMLElement][]) {
    panel.style.display = id === activeBrokerTab ? '' : 'none'
  }
}

function renderKiwoomApiPanel(container: HTMLElement): void {
  const vals = props.settings
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
    const appKey = apiKeyInputs['kiwoom_app_key_real']?.value ?? String(vals.kiwoom_app_key_real ?? '')
    const appSecret = apiKeyInputs['kiwoom_app_secret_real']?.value ?? String(vals.kiwoom_app_secret_real ?? '')
    const accountNo = apiKeyInputs['kiwoom_account_no_real']?.value ?? String(vals.kiwoom_account_no_real ?? '')
    props.onApiSave(appKey, appSecret, accountNo)
  })
  btnRow.appendChild(saveBtn)
  container.appendChild(btnRow)
}

function renderLsApiPanel(container: HTMLElement): void {
  const vals = props.settings
  const API_FIELDS: { key: string; label: string; type: 'password' | 'text' }[] = [
    { key: 'ls_app_key', label: '앱키', type: 'password' },
    { key: 'ls_app_secret', label: '앱시크릿', type: 'password' },
    { key: 'ls_account_no', label: '계좌번호', type: 'text' },
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
    border: '1px solid #DC143C', background: 'transparent',
    color: '#DC143C', cursor: 'pointer', fontSize: GS.label,
  })
  saveBtn.textContent = '저장'
  saveBtn.addEventListener('click', async () => {
    const appKey = apiKeyInputs['ls_app_key']?.value ?? String(vals.ls_app_key ?? '')
    const appSecret = apiKeyInputs['ls_app_secret']?.value ?? String(vals.ls_app_secret ?? '')
    const accountNo = apiKeyInputs['ls_account_no']?.value ?? String(vals.ls_account_no ?? '')
    // LS증권 저장 핸들러 필요시 props에 추가
    // props.onLsApiSave(appKey, appSecret, accountNo)
  })
  btnRow.appendChild(saveBtn)
  container.appendChild(btnRow)
}

/* ── 설정 동기화 ── */
function syncFromSettings(): void {
  const vals = props.settings

  // 자동매매 탭 (항상 DOM에 존재)
  {
    const forceOff = shouldForceOff()
    masterToggle?.setOn(forceOff ? false : !!vals.time_scheduler_on)
    holidayToggle?.setOn(!!vals.holiday_guard_on)
    wsToggle?.setOn(forceOff ? false : !!vals.ws_subscribe_on)
    updateHolidayBadges()
    updateAutoTradeDisabledStates()

    // TimePairInput
    const [sh, sm] = parseHM(String(vals.ws_subscribe_start ?? ''))
    const [eh, em] = parseHM(String(vals.ws_subscribe_end ?? ''))
    wsSH = sh; wsSM = sm; wsEH = eh; wsEM = em
    if (wsStartSlot) updateTimeSlotDisplay(wsStartSlot, sh, sm)
    if (wsEndSlot) updateTimeSlotDisplay(wsEndSlot, eh, em)
    updateWsTimeDisabled()
  }

  // 텔레그램 탭 (항상 DOM에 존재)
  {
    teleToggle?.setOn(!!vals.tele_on)
    for (const k of ['telegram_chat_id', 'telegram_bot_token']) {
      if (teleInputs[k]) teleInputs[k].value = String(vals[k] || '')
    }
  }

  // 계정관리 탭 (항상 DOM에 존재)
  {
    if (depositDisplay) depositDisplay.textContent = `${(Number(vals.test_virtual_deposit) || 0).toLocaleString()}원`
    if (testVirtualSection) testVirtualSection.style.display = vals.trade_mode === 'test' ? '' : 'none'
    if (tradeModeSection) {
      const radios = tradeModeSection.querySelectorAll<HTMLInputElement>('input[type="radio"]')
      radios.forEach(r => { r.checked = (r.parentElement?.textContent?.includes('테스트') ? 'test' : 'real') === vals.trade_mode })
    }
  }

  // API 설정 탭 (항상 DOM에 존재)
  {
    for (const k of ['kiwoom_app_key_real', 'kiwoom_app_secret_real', 'kiwoom_account_no_real', 'ls_app_key', 'ls_app_secret', 'ls_account_no']) {
      if (apiKeyInputs[k]) apiKeyInputs[k].value = String(vals[k] || '')
    }
  }
}

/* ── 컴포넌트 생성 함수 ── */

export function createGeneralSettingsCard(initialProps: GeneralSettingsProps): { el: HTMLElement; update: (newProps: GeneralSettingsProps) => void; destroy: () => void } {
  props = initialProps

  rootEl = document.createElement('div')

  // 탭 바
  tabBar = renderTabBar()
  rootEl.appendChild(tabBar)

  // 탭 콘텐츠 컨테이너
  tabContent = document.createElement('div')
  tabContent.style.padding = '0 4px'
  rootEl.appendChild(tabContent)

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

  syncFromSettings()

  // Props 업데이트 함수
  function update(newProps: GeneralSettingsProps): void {
    Object.assign(props, newProps)
    syncFromSettings()
    updateHolidayBadges()
  }

  // 파괴 함수
  function destroy(): void {
    if (rootEl && rootEl.parentNode) rootEl.parentNode.removeChild(rootEl)
    rootEl = null
    tabBar = null
    tabContent = null
    tabPanels = null
    masterToggle = null
    holidayToggle = null
    wsToggle = null
    wsTimePairWrap = null
    holidayBadgeEls = []
    holidayToggleRow = null
    wsBadge = null
    teleToggle = null
    teleInputs = {}
    tradeModeSection = null
    testVirtualSection = null
    depositInput = null
    depositDisplay = null
    wsStartSlot = null
    wsEndSlot = null
    apiKeyInputs = {}
    brokerTabBar = null
    brokerTabPanels = null
  }

  return { el: rootEl, update, destroy }
}
