// frontend/src/pages/general-settings.ts
// 일반설정 — Vanilla TS PageModule (메인)
// SettingsTabContainer.tsx + TelegramSection + AccountManageSection + TestVirtualSection 통합
//
// 파일 분할 (F-04, P24 단순성):
// - general-settings.ts (본 파일): 탭 바, refreshUI, syncFromSettings, mount/unmount
// - general-settings-shared.ts: 상태 객체 + GS 상수 + 공통 헬퍼
// - general-settings-time-settings-tab.ts: 시간 설정 탭
// - general-settings-auto-trade-tab.ts: 자동매매 탭
// - general-settings-telegram-tab.ts: 텔레그램 탭
// - general-settings-account-tab.ts: 투자모드 탭
// - general-settings-api-settings-tab.ts: API 설정 탭

import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingsManager, type SettingsManager } from '../settings'
import { startSettingsSubscription, destroySettingsPage } from '../utils/settings-page'
import { showSaveToast } from '../components/common/toast'
import { createCardTitle } from '../components/common/card-title'
import { createTabBar } from '../components/common/button'
import { setDisabled, COLOR, FONT_SIZE } from '../components/common/ui-styles'
import { parseHM, updateTimeSlotDisplay } from '../components/common/settings-common'
import { api } from '../api/client'
import type { AppSettings } from '../types'
import {
  type TabId,
  state,
  updateHolidayBadges,
  resetState,
} from './general-settings-shared'
import { renderTimeSettingsTab } from './general-settings-time-settings-tab'
import { renderAutoTradeTab } from './general-settings-auto-trade-tab'
import { renderTelegramTab } from './general-settings-telegram-tab'
import { renderAccountTab, syncTradeMode } from './general-settings-account-tab'
import { renderApiSettingsTab, syncBrokerRadios } from './general-settings-api-settings-tab'

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

  state.tabBarHandle = createTabBar({
    tabs,
    activeId: state.activeTab,
    onChange: (id) => { state.activeTab = id as TabId; refreshUI() },
    fontSize: FONT_SIZE.tab,
    padding: '8px 16px',
  })
  bar.appendChild(state.tabBarHandle.el)

  return bar
}

function refreshUI(): void {
  if (!state.rootEl || !state.tabContent || !state.tabPanels) return
  // 탭 바 활성 상태 업데이트 (DOM 재생성 없음)
  if (state.tabBarHandle) state.tabBarHandle.setActive(state.activeTab)

  // 탭 패널 display 토글 (DOM 재생성 없음)
  for (const [id, panel] of Object.entries(state.tabPanels) as [TabId, HTMLElement][]) {
    panel.style.display = id === state.activeTab ? '' : 'none'
  }

  const s = state.settingsMgr?.getSettings()
  if (s) syncFromSettings(s)
}

/* ── 설정 동기화 ── */
/** 토글+입력+컨트롤 행 동기화 공통 패턴 (5회 반복 추출 — P23 DRY) */
function syncToggleInputRow(
  toggle: { setOn: (v: boolean) => void } | null,
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
  state.riskManagerToggle?.setOn(!!r.risk_manager_on)
  if (state.riskManagerChildren) setDisabled(state.riskManagerChildren, !r.risk_manager_on)
  syncToggleInputRow(state.dailyLossToggle, state.dailyLossInput, state.dailyLossControls, r.daily_loss_limit_on !== false, Number(r.daily_loss_limit ?? -500000), act)
  syncToggleInputRow(state.dailyLossRateToggle, state.dailyLossRateInput, state.dailyLossRateControls, !!r.daily_loss_rate_limit_on, Number(r.daily_loss_rate_limit ?? -5), act)
  syncToggleInputRow(state.dailyProfitToggle, state.dailyProfitInput, state.dailyProfitControls, !!r.daily_profit_limit_on, Number(r.daily_profit_limit ?? 500000), act)
  syncToggleInputRow(state.dailyProfitRateToggle, state.dailyProfitRateInput, state.dailyProfitRateControls, !!r.daily_profit_rate_limit_on, Number(r.daily_profit_rate_limit ?? 5), act)
  syncToggleInputRow(state.consecLossToggle, state.consecLossInput, state.consecLossControls, !!r.consecutive_loss_limit_on, Number(r.consecutive_loss_limit ?? 3), act)
  state.riskBlockBuyToggle?.setOn(r.risk_block_buy_on !== false)
  state.riskBlockSellToggle?.setOn(!!r.risk_block_sell_on)
}

function syncTimetables(r: Record<string, unknown>): void {
  const [trh, trm] = parseHM(String(r['timetable.realtime_reset'] ?? '07:58'))
  if (state.timetableResetSlot) updateTimeSlotDisplay(state.timetableResetSlot, trh, trm)
  const [twh, twm] = parseHM(String(r['timetable.ws_prestart'] ?? '07:59'))
  if (state.timetableWsSlot) updateTimeSlotDisplay(state.timetableWsSlot, twh, twm)
  const [tkh, tkm] = parseHM(String(r['timetable.krx_pre_subscribe'] ?? '08:59'))
  if (state.timetableKrxSlot) updateTimeSlotDisplay(state.timetableKrxSlot, tkh, tkm)
}

function syncAutoTradeTab(r: Record<string, unknown>): void {
  state.masterToggle?.setOn(!!r.time_scheduler_on)
  updateHolidayBadges()

  // 확정 시세 다운로드 시간 + 자동다운로드 토글
  const [cdh, cdm] = parseHM(String(r['timetable.confirmed_download'] ?? '20:40'))
  state.confirmedDlH = cdh; state.confirmedDlM = cdm
  if (state.confirmedDlSlot) updateTimeSlotDisplay(state.confirmedDlSlot, cdh, cdm)
  const dlOn = r.scheduler_market_close_on !== false
  state.confirmedDlToggle?.setOn(dlOn)
  if (state.confirmedDlSlot) setDisabled(state.confirmedDlSlot, !dlOn)

  state.uiFlashToggle?.setOn(r.ui_price_flash_on !== false)

  // 실시간 뉴스 설정 — 키워드 칩 + TTL (NWS-S6)
  const keywords = String(r.news_keywords ?? '')
    .split(',')
    .map(s => s.trim())
    .filter(s => s.length > 0)
  state.newsKeywordsTagChip?.setTags(keywords)
  state.newsTtlInput?.setValue(Number(r.news_boost_ttl_sec ?? 300) || 300)

  syncRiskManager(r, document.activeElement)
  syncTimetables(r)

  // 구독 한도
  state.subscribeMaxInput?.setValue(Number(r['subscribe.max_0b_count'] ?? 200) || 200)

  // 자동매수/매도 (시간쌍은 시간 설정 탭에서 표시, 토글 OFF 시에도 활성화 유지 — 설계서 2-1)
  state.autoBuyToggle?.setOn(!!r.auto_buy_on)
  if (state.buyTimeHandle) state.buyTimeHandle.setValue(String(r.buy_time_start ?? '09:00'), String(r.buy_time_end ?? '15:00'))
  state.autoSellToggle?.setOn(!!r.auto_sell_on)
  if (state.sellTimeHandle) state.sellTimeHandle.setValue(String(r.sell_time_start ?? '09:00'), String(r.sell_time_end ?? '15:00'))
}

function syncTelegramTab(r: Record<string, unknown>): void {
  const act = document.activeElement
  state.teleToggle?.setOn(!!r.tele_on)
  for (const k of ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real']) {
    if (state.teleInputs[k] && (!act || !state.teleInputs[k].contains(act))) {
      state.teleInputs[k].value = String(r[k] || '')
    }
  }
}

function syncAccountTab(r: Record<string, unknown>): void {
  if (state.depositDisplay) state.depositDisplay.textContent = `${(Number(r.test_virtual_deposit) || 0).toLocaleString()}원`
  syncTradeMode(state)
}

function syncApiSettingsTab(r: Record<string, unknown>): void {
  const act = document.activeElement
  const allApiKeys = ['kiwoom_app_key', 'kiwoom_app_secret', 'kiwoom_account_no', 'ls_app_key', 'ls_app_secret', 'ls_account_no']
  for (const k of allApiKeys) {
    if (state.apiKeyInputs[k] && (!act || !state.apiKeyInputs[k].contains(act))) {
      state.apiKeyInputs[k].value = String(r[k] || '')
    }
  }
  if (r.broker !== undefined && state.vals.broker !== r.broker) {
    state.vals.broker = r.broker
  }
  syncBrokerRadios(state)
}

function syncFromSettings(s: AppSettings): void {
  const r = s as Record<string, unknown>
  // 전체 복사 대신 변경된 키만 업데이트
  for (const k of Object.keys(r)) {
    if (state.vals[k] !== r[k]) {
      state.vals[k] = r[k]
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
  renderAutoTradeTab(state, autoTradePanel)

  const timeSettingsPanel = document.createElement('div')
  renderTimeSettingsTab(state, timeSettingsPanel)

  const accountPanel = document.createElement('div')
  renderAccountTab(state, accountPanel)

  const apiPanel = document.createElement('div')
  renderApiSettingsTab(state, apiPanel)

  const telegramPanel = document.createElement('div')
  renderTelegramTab(state, telegramPanel)

  state.tabPanels = {
    'auto-trade': autoTradePanel,
    'time-settings': timeSettingsPanel,
    'account-manage': accountPanel,
    'api-settings': apiPanel,
    'telegram': telegramPanel,
  }

  // DOM에 추가하고 비활성 탭은 숨김
  for (const [id, panel] of Object.entries(state.tabPanels) as [TabId, HTMLElement][]) {
    panel.style.display = id === state.activeTab ? '' : 'none'
    state.tabContent!.appendChild(panel)
  }
}

function mount(container: HTMLElement): void {
  notifyPageActive('settings')
  state.settingsMgr = createSettingsManager(uiStore)
  state.vals = {}
  state.activeTab = 'auto-trade'
  state.holidayBadgeEls = []
  state.isTradingDay = true
  state.tradingDayLoading = true

  state.rootEl = document.createElement('div')
  state.rootEl.appendChild(createCardTitle('일반설정'))

  // 탭 바
  state.tabBar = renderTabBar()
  state.rootEl.appendChild(state.tabBar)

  // 탭 콘텐츠 컨테이너
  state.tabContent = document.createElement('div')
  state.tabContent.style.padding = '0 4px'
  state.rootEl.appendChild(state.tabContent)

  container.appendChild(state.rootEl)

  // 초기 설정 로드
  const initial = state.settingsMgr.getSettings()
  if (initial) {
    state.vals = { ...(initial as Record<string, unknown>) }
  }

  buildTabPanels()

  // 설정 동기화 + 구독 (표준 유틸 — settings-page.ts, P23 일관성)
  state.unsubSettings = startSettingsSubscription(state.settingsMgr as SettingsManager, syncFromSettings)

  // 거래일 확인
  api.getTradingDay()
    .then(data => { state.isTradingDay = data.is_trading_day; state.tradingDayLoading = false; updateHolidayBadges() })
    .catch(() => { state.isTradingDay = true; state.tradingDayLoading = false; showSaveToast('error', '거래일 조회 실패 — 거래일로 간주하여 자동매매를 허용합니다') })
}

function unmount(): void {
  notifyPageInactive('settings')
  destroySettingsPage(state.unsubSettings, null, state.settingsMgr as SettingsManager)
  resetState()
}

export default { mount, unmount }
