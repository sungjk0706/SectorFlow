// frontend/src/pages/general-settings-auto-trade-tab.ts
// 일반설정 — 전역설정 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 마스터 토글·배지·뉴스/화면 섹션은 각 탭으로 이관 완료.
// 본 탭은 전역매매설정(매매 안전장치) 섹션만 담당.

import { createMoneyInput, createNumInput, createSettingToggleRow } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { setDisabled } from '../components/common/ui-styles'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, updateHolidayBadges, state } from './general-settings-shared'

/* ── 전역설정 탭 ── */
function buildRiskManagerMasterRow(state: GeneralSettingsState): HTMLElement {
  state.riskManagerChildren = document.createElement('div')
  const r = createSettingToggleRow({
    label: '매매 안전장치',
    toggleOn: false,
    onToggle: async next => {
      state.vals.risk_manager_on = next
      setDisabled(state.riskManagerChildren!, !next)
      const res = await state.settingsMgr!.saveSection({ risk_manager_on: next })
      toastResult(res)
      if (!res.ok) {
        state.vals.risk_manager_on = !next
        r.toggle.setOn(!next)
        setDisabled(state.riskManagerChildren!, next)
      }
    },
  })
  state.riskManagerToggle = r.toggle
  return r.el
}

function buildDailyLossRow(state: GeneralSettingsState): void {
  state.dailyLossInput = createMoneyInput({
    value: -500000,
    onChange: async v => {
      const orig = Number(state.vals.daily_loss_limit)
      state.vals.daily_loss_limit = v
      const res = await state.settingsMgr!.saveSection({ daily_loss_limit: v })
      toastResult(res)
      if (!res.ok) { state.vals.daily_loss_limit = orig; state.dailyLossInput!.setValue(orig) }
    },
    step: 1, min: -1000000000, max: 0, unit: 'manwon', name: 'daily_loss_limit',
  })
  const r = createSettingToggleRow({
    label: '일일 손실 한도',
    infoText: '당일 누적 손실이 이 값 이하이면 매매 중단.\n범위: -100,000~0만원(=-10억~0원), 기본 -50만원.',
    toggleOn: true,
    disableControlsOnToggle: true,
    controls: [state.dailyLossInput.el],
    onToggle: async next => {
      state.vals.daily_loss_limit_on = next
      const res = await state.settingsMgr!.saveSection({ daily_loss_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.daily_loss_limit_on = !next
    },
  })
  state.dailyLossToggle = r.toggle; state.dailyLossControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildDailyLossRateRow(state: GeneralSettingsState): void {
  state.dailyLossRateInput = createNumInput({
    value: -5,
    onChange: async v => {
      const orig = Number(state.vals.daily_loss_rate_limit)
      state.vals.daily_loss_rate_limit = v
      const res = await state.settingsMgr!.saveSection({ daily_loss_rate_limit: v })
      toastResult(res)
      if (!res.ok) { state.vals.daily_loss_rate_limit = orig; state.dailyLossRateInput!.setValue(orig) }
    },
    step: 0.1, min: -100, max: 0, suffix: '%', name: 'daily_loss_rate_limit',
  })
  const r = createSettingToggleRow({
    label: '일일 손실률 한도',
    infoText: '당일 누적 손실률이 이 값 이하이면 매매 중단.\n범위: -100%~0%, 기본 -5%.',
    toggleOn: false,
    disableControlsOnToggle: true,
    controls: [state.dailyLossRateInput.el],
    onToggle: async next => {
      state.vals.daily_loss_rate_limit_on = next
      const res = await state.settingsMgr!.saveSection({ daily_loss_rate_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.daily_loss_rate_limit_on = !next
    },
  })
  state.dailyLossRateToggle = r.toggle; state.dailyLossRateControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildConsecLossRow(state: GeneralSettingsState): void {
  state.consecLossInput = createNumInput({
    value: 3,
    onChange: async v => {
      const orig = Number(state.vals.consecutive_loss_limit)
      state.vals.consecutive_loss_limit = v
      const res = await state.settingsMgr!.saveSection({ consecutive_loss_limit: v })
      toastResult(res)
      if (!res.ok) { state.vals.consecutive_loss_limit = orig; state.consecLossInput!.setValue(orig) }
    },
    step: 1, min: 1, max: 100, suffix: '회', name: 'consecutive_loss_limit',
  })
  const r = createSettingToggleRow({
    label: '연속 손실 횟수 한도',
    infoText: '연속 손실 횟수가 이 값 이상이면 매매 중단.\n범위: 1~100회, 기본 3회.',
    toggleOn: false,
    disableControlsOnToggle: true,
    controls: [state.consecLossInput.el],
    onToggle: async next => {
      state.vals.consecutive_loss_limit_on = next
      const res = await state.settingsMgr!.saveSection({ consecutive_loss_limit_on: next })
      toastResult(res)
      if (!res.ok) state.vals.consecutive_loss_limit_on = !next
    },
  })
  state.consecLossToggle = r.toggle; state.consecLossControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildRiskBlockBuyRow(state: GeneralSettingsState): HTMLElement {
  const r = createSettingToggleRow({
    label: '안전장치 조건 충족 시 매수 차단',
    toggleOn: true,
    onToggle: async next => {
      state.vals.risk_block_buy_on = next
      const res = await state.settingsMgr!.saveSection({ risk_block_buy_on: next })
      toastResult(res)
      if (!res.ok) { state.vals.risk_block_buy_on = !next; r.toggle.setOn(!next) }
    },
  })
  state.riskBlockBuyToggle = r.toggle
  return r.el
}

function buildRiskBlockSellRow(state: GeneralSettingsState): HTMLElement {
  const r = createSettingToggleRow({
    label: '안전장치 조건 충족 시 매도 차단',
    toggleOn: false,
    onToggle: async next => {
      state.vals.risk_block_sell_on = next
      const res = await state.settingsMgr!.saveSection({ risk_block_sell_on: next })
      toastResult(res)
      if (!res.ok) { state.vals.risk_block_sell_on = !next; r.toggle.setOn(!next) }
    },
  })
  state.riskBlockSellToggle = r.toggle
  return r.el
}

function buildRiskManagerChildren(state: GeneralSettingsState): HTMLElement {
  // 매매 안전장치 OFF 시 일괄 비활성화
  // 순서: 동작 토글(매수/매도 차단) → 시장 조건(코스피/코스닥) → 손실 조건(일일 손실/손실률/연속)
  state.riskManagerChildren!.appendChild(buildRiskBlockBuyRow(state))
  state.riskManagerChildren!.appendChild(buildRiskBlockSellRow(state))
  state.riskManagerChildren!.appendChild(createDescText('손실 상태에서 매도 차단 시 손실 확대 위험 — 신중하게 활성화하세요'))
  // 시장 지수 급락 가드 (매매 안전장치 하위 — 코스피/코스닥 개별 토글이 독립 제어)
  buildMarketGuardChildren(state)
  // 손실 조건
  buildDailyLossRow(state)
  buildDailyLossRateRow(state)
  buildConsecLossRow(state)
  return state.riskManagerChildren!
}

// ── 시장 지수 급락 가드 ──
// 코스피/코스닥 개별 토글이 독립 제어 (그룹 마스터 토글 없음 — 손실 조건 토글들과 동일 계층)
// 매수/매도 차단 여부는 기존 risk_block_buy_on/risk_block_sell_on 재사용 (별도 토글 없음)
function buildMarketGuardKospiRow(state: GeneralSettingsState): void {
  state.marketGuardKospiInput = createNumInput({
    value: -5,
    onChange: async v => {
      const orig = Number(state.vals.market_guard_kospi_drop_threshold_pct)
      state.vals.market_guard_kospi_drop_threshold_pct = v
      const res = await state.settingsMgr!.saveSection({ market_guard_kospi_drop_threshold_pct: v })
      toastResult(res)
      if (!res.ok) { state.vals.market_guard_kospi_drop_threshold_pct = orig; state.marketGuardKospiInput!.setValue(orig) }
    },
    step: 0.1, min: -100, max: 0, suffix: '%', name: 'market_guard_kospi_drop_threshold_pct',
  })
  const r = createSettingToggleRow({
    label: '코스피 급락 가드',
    infoText: '코스피 등락률이 이 값 이하이면 매매 차단.\n범위: -100%~0%, 기본 -5%.',
    toggleOn: false,
    disableControlsOnToggle: true,
    controls: [state.marketGuardKospiInput.el],
    onToggle: async next => {
      state.vals.market_guard_kospi_on = next
      const res = await state.settingsMgr!.saveSection({ market_guard_kospi_on: next })
      toastResult(res)
      if (!res.ok) state.vals.market_guard_kospi_on = !next
    },
  })
  state.marketGuardKospiToggle = r.toggle; state.marketGuardKospiControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildMarketGuardKosdaqRow(state: GeneralSettingsState): void {
  state.marketGuardKosdaqInput = createNumInput({
    value: -5,
    onChange: async v => {
      const orig = Number(state.vals.market_guard_kosdaq_drop_threshold_pct)
      state.vals.market_guard_kosdaq_drop_threshold_pct = v
      const res = await state.settingsMgr!.saveSection({ market_guard_kosdaq_drop_threshold_pct: v })
      toastResult(res)
      if (!res.ok) { state.vals.market_guard_kosdaq_drop_threshold_pct = orig; state.marketGuardKosdaqInput!.setValue(orig) }
    },
    step: 0.1, min: -100, max: 0, suffix: '%', name: 'market_guard_kosdaq_drop_threshold_pct',
  })
  const r = createSettingToggleRow({
    label: '코스닥 급락 가드',
    infoText: '코스닥 등락률이 이 값 이하이면 매매 차단.\n범위: -100%~0%, 기본 -5%.',
    toggleOn: false,
    disableControlsOnToggle: true,
    controls: [state.marketGuardKosdaqInput.el],
    onToggle: async next => {
      state.vals.market_guard_kosdaq_on = next
      const res = await state.settingsMgr!.saveSection({ market_guard_kosdaq_on: next })
      toastResult(res)
      if (!res.ok) state.vals.market_guard_kosdaq_on = !next
    },
  })
  state.marketGuardKosdaqToggle = r.toggle; state.marketGuardKosdaqControls = r.controls
  state.riskManagerChildren!.appendChild(r.el)
}

function buildMarketGuardChildren(state: GeneralSettingsState): void {
  buildMarketGuardKospiRow(state)
  buildMarketGuardKosdaqRow(state)
}

export function renderAutoTradeTab(state: GeneralSettingsState, container: HTMLElement): void {
  // 전역매매설정 (매매 안전장치) 섹션 — 손실 한도/시장 급락 도달 시 자동 매매 중단
  container.appendChild(sectionTitle('전역매매설정 (매매 안전장치)'))
  container.appendChild(createDescText('손실 한도/시장 급락 도달 시 자동 매매 중단. 매매 안전장치 OFF 시 모든 조건이 적용되지 않습니다.'))
  container.appendChild(buildRiskManagerMasterRow(state))
  container.appendChild(buildRiskManagerChildren(state))
}

// 전역설정 탭 동기화 — 매매 안전장치만 (마스터·시간·뉴스·화면은 각 탭으로 이관)
export function syncAutoTradeTab(r: Record<string, unknown>): void {
  updateHolidayBadges()
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
  syncToggleInputRow(state.consecLossToggle, state.consecLossInput, state.consecLossControls, !!r.consecutive_loss_limit_on, Number(r.consecutive_loss_limit ?? 3), act)
  state.riskBlockBuyToggle?.setOn(r.risk_block_buy_on !== false)
  state.riskBlockSellToggle?.setOn(!!r.risk_block_sell_on)
  // 시장 지수 급락 가드 동기화 (매수/매도 차단은 기존 riskBlockBuyToggle/riskBlockSellToggle 재사용)
  syncToggleInputRow(state.marketGuardKospiToggle, state.marketGuardKospiInput, state.marketGuardKospiControls, !!r.market_guard_kospi_on, Number(r.market_guard_kospi_drop_threshold_pct ?? -5), act)
  syncToggleInputRow(state.marketGuardKosdaqToggle, state.marketGuardKosdaqInput, state.marketGuardKosdaqControls, !!r.market_guard_kosdaq_on, Number(r.market_guard_kosdaq_drop_threshold_pct ?? -5), act)
}
