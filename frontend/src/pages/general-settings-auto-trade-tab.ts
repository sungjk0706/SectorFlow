// frontend/src/pages/general-settings-auto-trade-tab.ts
// 일반설정 — 자동매매 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.

import { createToggleBtn, createMoneyInput, createNumInput, createToggleLabelControlsRow } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { createTagChip } from '../components/common/tag-chip'
import { FONT_WEIGHT, setDisabled } from '../components/common/ui-styles'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, GS, createHolidayBadge } from './general-settings-shared'

/* ── 자동매매 탭 ── */
function buildMasterToggleRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매매'
  row.appendChild(label)

  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;'
  right.appendChild(createHolidayBadge())
  state.masterToggle = createToggleBtn({ on: false, onClick: () => handleMasterToggle(state) })
  right.appendChild(state.masterToggle.el)
  row.appendChild(right)
  return row
}

function buildAutoBuyRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매수'
  row.appendChild(label)
  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;'
  state.autoBuyToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !state.vals.auto_buy_on
    state.vals.auto_buy_on = next; state.autoBuyToggle!.setOn(next)
    const res = await state.settingsMgr!.saveSection({ auto_buy_on: next })
    toastResult(res)
    if (!res.ok) { state.vals.auto_buy_on = !next; state.autoBuyToggle!.setOn(!next) }
  }})
  right.appendChild(createHolidayBadge())
  right.appendChild(state.autoBuyToggle.el)
  row.appendChild(right)
  return row
}

function buildAutoSellRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매도'
  row.appendChild(label)
  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;'
  state.autoSellToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !state.vals.auto_sell_on
    state.vals.auto_sell_on = next; state.autoSellToggle!.setOn(next)
    const res = await state.settingsMgr!.saveSection({ auto_sell_on: next })
    toastResult(res)
    if (!res.ok) { state.vals.auto_sell_on = !next; state.autoSellToggle!.setOn(!next) }
  }})
  right.appendChild(createHolidayBadge())
  right.appendChild(state.autoSellToggle.el)
  row.appendChild(right)
  return row
}

function buildRiskManagerMasterRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '매매 안전장치'
  row.appendChild(label)
  state.riskManagerChildren = document.createElement('div')
  state.riskManagerToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !state.vals.risk_manager_on
    state.vals.risk_manager_on = next; state.riskManagerToggle!.setOn(next)
    setDisabled(state.riskManagerChildren!, !next)
    const res = await state.settingsMgr!.saveSection({ risk_manager_on: next })
    toastResult(res)
    if (!res.ok) {
      state.vals.risk_manager_on = !next; state.riskManagerToggle!.setOn(!next)
      setDisabled(state.riskManagerChildren!, next)
    }
  }})
  row.appendChild(state.riskManagerToggle.el)
  return row
}

function buildDailyLossRow(state: GeneralSettingsState): void {
  state.dailyLossInput = createMoneyInput({
    value: -500000,
    onChange: async v => {
      state.vals.daily_loss_limit = v
      const res = await state.settingsMgr!.saveSection({ daily_loss_limit: v })
      toastResult(res)
      if (res.ok) state.vals.daily_loss_limit = v
    },
    step: 10000, min: -1000000000, max: 0, name: 'daily_loss_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 손실 한도 (원)',
    toggleOn: true,
    onToggle: async next => {
      state.vals.daily_loss_limit_on = next
      const res = await state.settingsMgr!.saveSection({ daily_loss_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.daily_loss_limit_on = !next
    },
    controlsChild: state.dailyLossInput.el,
  })
  state.dailyLossToggle = r.toggle; state.dailyLossControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildDailyLossRateRow(state: GeneralSettingsState): void {
  state.dailyLossRateInput = createNumInput({
    value: -5,
    onChange: async v => {
      state.vals.daily_loss_rate_limit = v
      const res = await state.settingsMgr!.saveSection({ daily_loss_rate_limit: v })
      toastResult(res)
      if (res.ok) state.vals.daily_loss_rate_limit = v
    },
    step: 0.1, min: -100, max: 0, name: 'daily_loss_rate_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 손실률 한도 (%)',
    toggleOn: false,
    onToggle: async next => {
      state.vals.daily_loss_rate_limit_on = next
      const res = await state.settingsMgr!.saveSection({ daily_loss_rate_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.daily_loss_rate_limit_on = !next
    },
    controlsChild: state.dailyLossRateInput.el,
  })
  state.dailyLossRateToggle = r.toggle; state.dailyLossRateControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildDailyProfitRow(state: GeneralSettingsState): void {
  state.dailyProfitInput = createMoneyInput({
    value: 500000,
    onChange: async v => {
      state.vals.daily_profit_limit = v
      const res = await state.settingsMgr!.saveSection({ daily_profit_limit: v })
      toastResult(res)
      if (res.ok) state.vals.daily_profit_limit = v
    },
    name: 'daily_profit_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 수익 한도 (원)',
    toggleOn: false,
    onToggle: async next => {
      state.vals.daily_profit_limit_on = next
      const res = await state.settingsMgr!.saveSection({ daily_profit_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.daily_profit_limit_on = !next
    },
    controlsChild: state.dailyProfitInput.el,
  })
  state.dailyProfitToggle = r.toggle; state.dailyProfitControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildDailyProfitRateRow(state: GeneralSettingsState): void {
  state.dailyProfitRateInput = createNumInput({
    value: 5,
    onChange: async v => {
      state.vals.daily_profit_rate_limit = v
      const res = await state.settingsMgr!.saveSection({ daily_profit_rate_limit: v })
      toastResult(res)
      if (res.ok) state.vals.daily_profit_rate_limit = v
    },
    step: 0.1, min: 0, max: 100, name: 'daily_profit_rate_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '일일 수익률 한도 (%)',
    toggleOn: false,
    onToggle: async next => {
      state.vals.daily_profit_rate_limit_on = next
      const res = await state.settingsMgr!.saveSection({ daily_profit_rate_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.daily_profit_rate_limit_on = !next
    },
    controlsChild: state.dailyProfitRateInput.el,
  })
  state.dailyProfitRateToggle = r.toggle; state.dailyProfitRateControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildConsecLossRow(state: GeneralSettingsState): void {
  state.consecLossInput = createNumInput({
    value: 3,
    onChange: async v => {
      state.vals.consecutive_loss_limit = v
      const res = await state.settingsMgr!.saveSection({ consecutive_loss_limit: v })
      toastResult(res)
      if (res.ok) state.vals.consecutive_loss_limit = v
    },
    step: 1, min: 1, max: 100, name: 'consecutive_loss_limit',
  })
  const r = createToggleLabelControlsRow({
    labelText: '연속 손실 횟수 한도 (회)',
    toggleOn: false,
    onToggle: async next => {
      state.vals.consecutive_loss_limit_on = next
      const res = await state.settingsMgr!.saveSection({ consecutive_loss_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.consecutive_loss_limit_on = !next
    },
    controlsChild: state.consecLossInput.el,
  })
  state.consecLossToggle = r.toggle; state.consecLossControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildRiskBlockBuyRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '안전장치 조건 충족 시 매수 차단'
  row.appendChild(label)
  state.riskBlockBuyToggle = createToggleBtn({ on: true, onClick: async () => {
    const next = !state.vals.risk_block_buy_on
    state.vals.risk_block_buy_on = next; state.riskBlockBuyToggle!.setOn(next)
    const res = await state.settingsMgr!.saveSection({ risk_block_buy_on: next })
    toastResult(res)
    if (!res.ok) { state.vals.risk_block_buy_on = !next; state.riskBlockBuyToggle!.setOn(!next) }
  }})
  row.appendChild(state.riskBlockBuyToggle.el)
  return row
}

function buildRiskBlockSellRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '안전장치 조건 충족 시 매도 차단'
  row.appendChild(label)
  state.riskBlockSellToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !state.vals.risk_block_sell_on
    state.vals.risk_block_sell_on = next; state.riskBlockSellToggle!.setOn(next)
    const res = await state.settingsMgr!.saveSection({ risk_block_sell_on: next })
    toastResult(res)
    if (!res.ok) { state.vals.risk_block_sell_on = !next; state.riskBlockSellToggle!.setOn(!next) }
  }})
  row.appendChild(state.riskBlockSellToggle.el)
  return row
}

function buildRiskManagerChildren(state: GeneralSettingsState): HTMLElement {
  // 매매 안전장치 OFF 시 일괄 비활성화
  buildDailyLossRow(state)
  buildDailyLossRateRow(state)
  buildDailyProfitRow(state)
  buildDailyProfitRateRow(state)
  buildConsecLossRow(state)
  state.riskManagerChildren!.appendChild(buildRiskBlockBuyRow(state))
  state.riskManagerChildren!.appendChild(buildRiskBlockSellRow(state))
  state.riskManagerChildren!.appendChild(createDescText('손실 상태에서 매도 차단 시 손실 확대 위험 — 신중하게 활성화하세요'))
  return state.riskManagerChildren!
}

function buildUiFlashRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '실시간 현재가 플래시 효과'
  row.appendChild(label)
  state.uiFlashToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !state.vals.ui_price_flash_on
    state.vals.ui_price_flash_on = next
    state.uiFlashToggle!.setOn(next)
    const res = await state.settingsMgr!.saveSection({ ui_price_flash_on: next })
    toastResult(res)
    if (!res.ok) { state.vals.ui_price_flash_on = !next; state.uiFlashToggle!.setOn(!next) }
  }})
  row.appendChild(state.uiFlashToggle.el)
  return row
}

export function renderAutoTradeTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(buildMasterToggleRow(state))
  container.appendChild(createDescText('자동매매(매수/매도) 마스터 스위치 — OFF면 모든 매매 중단'))
  container.appendChild(buildAutoBuyRow(state))
  container.appendChild(buildAutoSellRow(state))
  container.appendChild(createDescText('거래일 설정시간 내에서만 자동 매수/매도 실행. 공휴일·주말에는 자동매매가 항상 차단됩니다. 시간 설정은 "시간 설정" 탭에서'))

  // 전역매매설정 (매매 안전장치) 섹션 — 목표 수익/손실 도달 시 자동 매매 중단
  container.appendChild(sectionTitle('전역매매설정 (매매 안전장치)'))
  container.appendChild(createDescText('목표 수익/손실 도달 시 자동 매매 중단. 매매 안전장치 OFF 시 모든 조건이 적용되지 않습니다.'))
  container.appendChild(buildRiskManagerMasterRow(state))
  container.appendChild(buildRiskManagerChildren(state))

  // 화면 표시 섹션 — 플래시 효과 (API 설정 탭에서 이동, Step 5, 설계서 5-3)
  container.appendChild(sectionTitle('화면 표시'))
  container.appendChild(buildUiFlashRow(state))
  container.appendChild(createDescText('실시간 시세 변경 시 노란색 플래시 깜빡임 효과 적용 여부'))

  // 실시간 뉴스 설정 섹션 — 호재 키워드 편집 + 가산점 유지 시간 (NWS-S6)
  container.appendChild(sectionTitle('실시간 뉴스 설정'))
  container.appendChild(createDescText('뉴스 제목에 포함된 호재 키워드 감지 시 매수 가산점 부여. 키워드는 쉼표로 구분하여 입력.'))
  container.appendChild(buildNewsKeywordsRow(state))
  container.appendChild(buildNewsTtlRow(state))
}

// 호재 키워드 칩 행 — news_keywords 쉼표 문자열 ↔ 칩 배열 변환
function buildNewsKeywordsRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { padding: GS.rowPad, borderBottom: GS.rowBorder })

  const label = document.createElement('div')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal, marginBottom: '4px' })
  label.textContent = '호재 키워드'
  row.appendChild(label)

  const initialKeywords = String(state.vals.news_keywords ?? '')
    .split(',')
    .map(s => s.trim())
    .filter(s => s.length > 0)
  state.newsKeywordsTagChip = createTagChip({
    initialTags: initialKeywords,
    onChange: async (tags) => {
      if (!state.settingsMgr) return
      const joined = tags.join(',')
      const dirty: Record<string, unknown> = { news_keywords: joined }
      const res = await state.settingsMgr.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(state.vals, dirty)
    },
  })
  row.appendChild(state.newsKeywordsTagChip.el)
  return row
}

// 뉴스 가산점 유지 시간(초) 행 — createNumInput 패턴 (subscribeMaxInput과 동일)
function buildNewsTtlRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '뉴스 가산점 유지 시간(초)'
  row.appendChild(label)

  const initTtl = Number(state.vals.news_boost_ttl_sec ?? 300) || 300
  state.newsTtlInput = createNumInput({
    value: initTtl,
    min: 0, max: 3600, step: 60,
    name: 'news_boost_ttl_sec',
    onChange: async (v) => {
      if (!state.settingsMgr) return
      const dirty: Record<string, unknown> = { news_boost_ttl_sec: v }
      const res = await state.settingsMgr.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(state.vals, dirty)
    },
  })
  row.appendChild(state.newsTtlInput.el)
  return row
}

async function handleMasterToggle(state: GeneralSettingsState): Promise<void> {
  const next = !state.vals.time_scheduler_on
  state.vals.time_scheduler_on = next; state.masterToggle?.setOn(next)
  const r = await state.settingsMgr!.saveSection({ time_scheduler_on: next })
  toastResult(r)
  if (!r.ok) { state.vals.time_scheduler_on = !next; state.masterToggle?.setOn(!next) }
}
