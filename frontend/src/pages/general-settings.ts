// frontend/src/pages/general-settings.ts
// 일반설정 — Vanilla TS PageModule (메인)
// SettingsTabContainer.tsx + TelegramSection + AccountManageSection + TestVirtualSection 통합
//
// 파일 분할 (F-04, P24 단순성):
// - general-settings.ts (본 파일): 탭 바, refreshUI, syncFromSettings, mount/unmount
// - general-settings-shared.ts: 상태 객체 + GS 상수 + 공통 헬퍼
// - general-settings-time-settings-tab.ts: 시간 설정 탭 (+ 자동매수/매도 토글)
// - general-settings-auto-trade-tab.ts: 자동매매 탭 (마스터+배지+안전장치)
// - general-settings-news-settings-tab.ts: 뉴스 설정 탭 (Step 2 신설)
// - general-settings-display-settings-tab.ts: 화면 설정 탭 (Step 2 신설)
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
import { COLOR, FONT_SIZE, RADIUS } from '../components/common/ui-styles'
import { api } from '../api/client'
import type { AppSettings } from '../types'
import {
  type TabId,
  state,
  updateHolidayBadges,
  resetState,
  ENCRYPTION_KEY_STATE_MESSAGES,
  ENCRYPTION_KEY_BACKUP_GUIDE,
  currentEncryptionKeyState,
} from './general-settings-shared'
import { renderTimeSettingsTab, syncTimeSettingsTab } from './general-settings-time-settings-tab'
import { renderAutoTradeTab, syncAutoTradeTab } from './general-settings-auto-trade-tab'
import { renderNewsSettingsTab, syncNewsSettingsTab } from './general-settings-news-settings-tab'
import { renderDisplaySettingsTab, syncDisplaySettingsTab } from './general-settings-display-settings-tab'
import { renderTelegramTab, syncTelegramEncryptionStatus } from './general-settings-telegram-tab'
import { renderAccountTab, syncTradeMode } from './general-settings-account-tab'
import { renderApiSettingsTab, syncBrokerRadios, syncApiEncryptionStatus } from './general-settings-api-settings-tab'

/* ── B21-01 세션7: 암호화 상태 배너 (설계 7.1/9.2) ── */
function renderEncryptionBanner(): HTMLElement {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { marginBottom: '12px' })

  // 상태 라인 (키 상태별 색상·문구 — 설계 7.2)
  const statusLine = document.createElement('div')
  Object.assign(statusLine.style, {
    padding: '8px 12px', borderRadius: RADIUS.sm, fontSize: FONT_SIZE.desc, fontWeight: '500',
  })
  wrap.appendChild(statusLine)

  // 키 백업 안내 (설계 9.2 — 항상 표시, 상태와 무관)
  const guide = document.createElement('div')
  Object.assign(guide.style, {
    padding: '6px 12px', fontSize: FONT_SIZE.desc, color: COLOR.tertiary,
    background: COLOR.neutralBg, borderRadius: RADIUS.sm, marginTop: '6px',
  })
  guide.textContent = ENCRYPTION_KEY_BACKUP_GUIDE
  wrap.appendChild(guide)

  state.encryptionBanner = statusLine
  return wrap
}

function syncEncryptionBanner(): void {
  if (!state.encryptionBanner) return
  const ks = currentEncryptionKeyState()
  if (ks === null) {
    // 백엔드가 상태를 내려주지 않은 경우 (구형 응답) — 배너 숨김 (P25 격리)
    state.encryptionBanner.style.display = 'none'
    return
  }
  const msg = ENCRYPTION_KEY_STATE_MESSAGES[ks]
  state.encryptionBanner.style.display = ''
  state.encryptionBanner.style.color = msg.color
  state.encryptionBanner.style.background = msg.bg
  state.encryptionBanner.textContent = msg.text
}

/* ── 탭 렌더링 ── */
function renderTabBar(): HTMLElement {
  const bar = document.createElement('div')
  Object.assign(bar.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid ' + COLOR.borderDark, marginBottom: '12px' })

  const tabs: { id: TabId; label: string }[] = [
    { id: 'auto-trade', label: '자동매매' },
    { id: 'time-settings', label: '시간 설정' },
    { id: 'news-settings', label: '뉴스 설정' },
    { id: 'display-settings', label: '화면 설정' },
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
// Step 2 분할: syncAutoTradeTab/syncTimeSettingsTab/syncNewsSettingsTab/syncDisplaySettingsTab은 각 탭 파일로 이관.
// 본 파일에는 텔레그램/투자모드/API 설정 탭 동기화만 잔류.

function syncTelegramTab(r: Record<string, unknown>): void {
  const act = document.activeElement
  state.teleToggle?.setOn(!!r.tele_on)
  for (const k of ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real']) {
    if (state.teleInputs[k] && (!act || !state.teleInputs[k].contains(act))) {
      state.teleInputs[k].value = String(r[k] || '')
    }
  }
  syncTelegramEncryptionStatus(state)
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
  syncApiEncryptionStatus(state)
}

function syncFromSettings(s: AppSettings): void {
  const r = s as Record<string, unknown>
  // 전체 복사 대신 변경된 키만 업데이트
  for (const k of Object.keys(r)) {
    if (state.vals[k] !== r[k]) {
      state.vals[k] = r[k]
    }
  }

  syncEncryptionBanner()
  syncAutoTradeTab(r)
  syncTimeSettingsTab(r)
  syncNewsSettingsTab(r)
  syncDisplaySettingsTab(r)
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

  const newsSettingsPanel = document.createElement('div')
  renderNewsSettingsTab(state, newsSettingsPanel)

  const displaySettingsPanel = document.createElement('div')
  renderDisplaySettingsTab(state, displaySettingsPanel)

  const accountPanel = document.createElement('div')
  renderAccountTab(state, accountPanel)

  const apiPanel = document.createElement('div')
  renderApiSettingsTab(state, apiPanel)

  const telegramPanel = document.createElement('div')
  renderTelegramTab(state, telegramPanel)

  state.tabPanels = {
    'auto-trade': autoTradePanel,
    'time-settings': timeSettingsPanel,
    'news-settings': newsSettingsPanel,
    'display-settings': displaySettingsPanel,
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

  // B21-01 세션7: 암호화 상태 배너 (탭 바 상단 — 설계 7.1)
  state.rootEl.appendChild(renderEncryptionBanner())

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
