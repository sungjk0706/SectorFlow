// frontend/src/pages/general-settings-auto-trade-tab.ts
// 일반설정 — 자동매매 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. Step 2: 토글→시간 설정 탭 이관, 상태 배지 추가, 뉴스/화면 섹션→각 탭 이관.

import { createToggleBtn, createMoneyInput, createNumInput, createToggleLabelControlsRow } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { FONT_WEIGHT, setDisabled, COLOR, FONT_SIZE } from '../components/common/ui-styles'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, GS, createHolidayBadge, updateHolidayBadges, state } from './general-settings-shared'

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

// 자동매수 상태 배지 — 읽기 전용 (Step 2: 토글은 시간 설정 탭으로 이관, P21 투명성)
// 켜짐=COLOR.up/COLOR.upBg, 꺼짐=중립 회색 (기존 표준 색상 재사용 — P23)
function buildAutoBuyBadgeRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매수'
  row.appendChild(label)
  state.autoBuyBadge = createStatusBadge()
  row.appendChild(state.autoBuyBadge)
  return row
}

// 자동매도 상태 배지 — 읽기 전용 (Step 2: 토글은 시간 설정 탭으로 이관, P21 투명성)
function buildAutoSellBadgeRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매도'
  row.appendChild(label)
  state.autoSellBadge = createStatusBadge()
  row.appendChild(state.autoSellBadge)
  return row
}

// 상태 배지 생성 — '켜짐'/'꺼짐' 클릭 불가 (설계서 3.3)
function createStatusBadge(): HTMLElement {
  const badge = document.createElement('span')
  Object.assign(badge.style, {
    fontSize: FONT_SIZE.chip, borderRadius: '4px', padding: '1px 8px',
    fontWeight: FONT_WEIGHT.normal, cursor: 'default', userSelect: 'none',
  })
  return badge
}

// 배지 텍스트/색상 업데이트 — syncAutoTradeTab에서 호출
function updateStatusBadge(badge: HTMLElement, on: boolean): void {
  badge.textContent = on ? '켜짐' : '꺼짐'
  if (on) {
    badge.style.color = COLOR.up
    badge.style.background = COLOR.upBg
  } else {
    badge.style.color = COLOR.disabled
    badge.style.background = COLOR.neutralBg
  }
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

export function renderAutoTradeTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(buildMasterToggleRow(state))
  container.appendChild(createDescText('자동매매(매수/매도) 마스터 스위치 — OFF면 모든 매매 중단'))
  container.appendChild(buildAutoBuyBadgeRow(state))
  container.appendChild(buildAutoSellBadgeRow(state))
  container.appendChild(createDescText('자동매수/매도 켜짐/꺼짐 상태 표시 (읽기 전용). 켜고 끄는 조작은 "시간 설정" 탭의 시간 행 우측 토글에서'))

  // 전역매매설정 (매매 안전장치) 섹션 — 목표 수익/손실 도달 시 자동 매매 중단
  container.appendChild(sectionTitle('전역매매설정 (매매 안전장치)'))
  container.appendChild(createDescText('목표 수익/손실 도달 시 자동 매매 중단. 매매 안전장치 OFF 시 모든 조건이 적용되지 않습니다.'))
  container.appendChild(buildRiskManagerMasterRow(state))
  container.appendChild(buildRiskManagerChildren(state))
}

// 자동매매 탭 동기화 — Step 2 분할: 마스터 + 배지 + 안전장치만 (시간·뉴스·화면은 각 탭으로 이관)
export function syncAutoTradeTab(r: Record<string, unknown>): void {
  state.masterToggle?.setOn(!!r.time_scheduler_on)
  updateHolidayBadges()
  updateStatusBadge(state.autoBuyBadge!, !!r.auto_buy_on)
  updateStatusBadge(state.autoSellBadge!, !!r.auto_sell_on)
  syncRiskManager(state, r, document.activeElement)
}

// 토글+입력+컨트롤 행 동기화 공통 패턴 (5회 반복 추출 — P23 DRY)
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

function syncRiskManager(state: GeneralSettingsState, r: Record<string, unknown>, act: Element | null): void {
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

async function handleMasterToggle(state: GeneralSettingsState): Promise<void> {
  const next = !state.vals.time_scheduler_on
  state.vals.time_scheduler_on = next; state.masterToggle?.setOn(next)
  const r = await state.settingsMgr!.saveSection({ time_scheduler_on: next })
  toastResult(r)
  if (!r.ok) { state.vals.time_scheduler_on = !next; state.masterToggle?.setOn(!next) }
}
