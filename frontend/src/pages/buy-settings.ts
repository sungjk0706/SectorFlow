// frontend/src/pages/buy-settings.ts
// 매수설정 카드 — Vanilla TS PageModule
// BuySettingsCard.tsx + BuySettingsSection.tsx + BuyBlockSection.tsx + QuickToggle + TimePairInput 통합

import { createSettingRow, createNumInput, createMoneyInput, createToggleBtn, createFixedValue, createSelect } from '../components/common/setting-row'
import { sectionTitle } from '../components/common/settings-common'
import { initSettingsPage, startSettingsSubscription, destroySettingsPage } from '../utils/settings-page'
import type { AutoSaveHelper } from '../utils/settings-save'
import type { SettingsManager } from '../settings'
import { setDisabled } from '../components/common/ui-styles'
import type { AppSettings } from '../types'

/* ── 모듈 상태 ── */
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let saveHelper: AutoSaveHelper | null = null
// 현재 값 추적
let vals: Record<string, unknown> = {}

// 입력 컴포넌트 참조
let riseInput: ReturnType<typeof createNumInput> | null = null
let fallInput: ReturnType<typeof createNumInput> | null = null
let strengthInput: ReturnType<typeof createNumInput> | null = null
let maxDailyToggle: ReturnType<typeof createToggleBtn> | null = null
let maxDailyInput: ReturnType<typeof createMoneyInput> | null = null
let maxStockCntInput: ReturnType<typeof createNumInput> | null = null
let buyAmtInput: ReturnType<typeof createMoneyInput> | null = null

// 가산점 UI 참조
let boostHighToggle: ReturnType<typeof createToggleBtn> | null = null
let boostHighScoreInput: ReturnType<typeof createNumInput> | null = null
let boostHighControls: HTMLElement | null = null

let boostOrderToggle: ReturnType<typeof createToggleBtn> | null = null
let boostOrderScoreInput: ReturnType<typeof createNumInput> | null = null
let boostOrderControls: HTMLElement | null = null

let boostProgramToggle: ReturnType<typeof createToggleBtn> | null = null
let boostProgramScoreInput: ReturnType<typeof createNumInput> | null = null
let boostProgramControls: HTMLElement | null = null

let boostTradeAmountToggle: ReturnType<typeof createToggleBtn> | null = null
let boostTradeAmountScoreInput: ReturnType<typeof createNumInput> | null = null
let boostTradeAmountControls: HTMLElement | null = null

// 재매수 차단 UI 참조
let rebuyBlockToggle: ReturnType<typeof createToggleBtn> | null = null
let rebuyBlockSelect: ReturnType<typeof createSelect> | null = null
let rebuyBlockControls: HTMLElement | null = null

// 매수 주문 간격 UI 참조
let buyIntervalToggle: ReturnType<typeof createToggleBtn> | null = null
let buyIntervalInput: ReturnType<typeof createNumInput> | null = null
let buyIntervalControls: HTMLElement | null = null


/* ── 부스트 가산점 섹션 헬퍼 (토글 + 라벨 + 스코어 입력) ── */
function createBoostScoreSection(
  root: HTMLElement,
  labelText: string,
  toggleKey: string,
  scoreKey: string,
  vals: Record<string, unknown>,
  helper: AutoSaveHelper,
): { toggle: ReturnType<typeof createToggleBtn>; scoreInput: ReturnType<typeof createNumInput>; controls: HTMLElement } {
  const labelWrap = document.createElement('span')
  labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
  const toggle = createToggleBtn({ on: false, onClick: () => {
    const next = !vals[toggleKey]
    vals[toggleKey] = next
    toggle.setOn(next)
    setDisabled(controls, !next)
    helper.autoSave(toggleKey, next)
  }})
  labelWrap.appendChild(toggle.el)
  const label = document.createElement('span')
  label.textContent = labelText
  labelWrap.appendChild(label)

  const controls = document.createElement('span')
  controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
  setDisabled(controls, true)

  const scoreInput = createNumInput({ value: 1.0, onChange: v => { vals[scoreKey] = v; helper.autoSave(scoreKey, v) }, step: 1, name: scoreKey })
  controls.appendChild(scoreInput.el)

  root.appendChild(createSettingRow(labelWrap, controls))
  return { toggle, scoreInput, controls }
}


/* ── 설정 동기화 ── */
function syncFromSettings(s: AppSettings): void {
  const r = s as Record<string, unknown>
  vals = { ...r }

  const act = document.activeElement

  // 매수 조건
  if (riseInput && (!act || !riseInput.el.contains(act))) riseInput.setValue(Number(r.buy_block_rise_pct) || 0)
  if (fallInput && (!act || !fallInput.el.contains(act))) fallInput.setValue(Number(r.buy_block_fall_pct) || 0)
  if (strengthInput && (!act || !strengthInput.el.contains(act))) strengthInput.setValue(Number(r.buy_min_strength) || 0)

  // 매수 금액
  const dailyOn = !!r.max_daily_total_buy_on
  maxDailyToggle?.setOn(dailyOn)
  if (maxDailyInput && (!act || !maxDailyInput.el.contains(act))) maxDailyInput.setValue(Number(r.max_daily_total_buy_amt) || 0)
  if (maxDailyInput) setDisabled(maxDailyInput.el, !dailyOn)
  if (maxStockCntInput && (!act || !maxStockCntInput.el.contains(act))) maxStockCntInput.setValue(Number(r.max_stock_cnt) || 0)
  if (buyAmtInput && (!act || !buyAmtInput.el.contains(act))) buyAmtInput.setValue(Number(r.buy_amt) || 0)

  // 매수 가산점
  const highOn = !!r.boost_high_breakout_on
  boostHighToggle?.setOn(highOn)
  if (boostHighScoreInput && (!act || !boostHighScoreInput.el.contains(act))) boostHighScoreInput.setValue(Number(r.boost_high_breakout_score) || 1.0)
  if (boostHighControls) {
    setDisabled(boostHighControls, !highOn)
  }

  const orderOn = !!r.boost_order_ratio_on
  boostOrderToggle?.setOn(orderOn)
  boostOrderScoreInput?.setValue(Number(r.boost_order_ratio_score) || 1.0)
  if (boostOrderControls) {
    setDisabled(boostOrderControls, !orderOn)
  }

  const programOn = !!r.boost_program_net_buy_on
  boostProgramToggle?.setOn(programOn)
  if (boostProgramScoreInput && (!act || !boostProgramScoreInput.el.contains(act))) boostProgramScoreInput.setValue(Number(r.boost_program_net_buy_score) || 1.0)
  if (boostProgramControls) {
    setDisabled(boostProgramControls, !programOn)
  }

  const tradeAmountOn = !!r.boost_trade_amount_rank_on
  boostTradeAmountToggle?.setOn(tradeAmountOn)
  if (boostTradeAmountScoreInput && (!act || !boostTradeAmountScoreInput.el.contains(act))) boostTradeAmountScoreInput.setValue(Number(r.boost_trade_amount_rank_score) || 1.0)
  if (boostTradeAmountControls) {
    setDisabled(boostTradeAmountControls, !tradeAmountOn)
  }

  // 재매수 차단
  const rebuyOn = !!r.rebuy_block_on
  rebuyBlockToggle?.setOn(rebuyOn)
  if (rebuyBlockSelect && (!act || !rebuyBlockSelect.el.contains(act))) {
    rebuyBlockSelect.setValue(String(r.rebuy_block_period ?? 'today'))
  }
  if (rebuyBlockControls) {
    setDisabled(rebuyBlockControls, !rebuyOn)
  }

  // 매수 주문 간격
  const intervalOn = !!r.buy_interval_on
  buyIntervalToggle?.setOn(intervalOn)
  if (buyIntervalInput && (!act || !buyIntervalInput.el.contains(act))) buyIntervalInput.setValue(Number(r.buy_interval_min) || 0)
  if (buyIntervalControls) {
    setDisabled(buyIntervalControls, !intervalOn)
  }

}

/* ── mount ── */
function mount(container: HTMLElement): void {
  const ctx = initSettingsPage(syncFromSettings)
  settingsMgr = ctx.settingsMgr
  saveHelper = ctx.saveHelper
  vals = {}

  const root = document.createElement('div')


  // ── 매수 조건 섹션 ──
  root.appendChild(sectionTitle('매수 차단'))

  // 상승률 제한
  riseInput = createNumInput({ value: 0, onChange: v => { vals.buy_block_rise_pct = v; saveHelper!.autoSave('buy_block_rise_pct', v) }, step: 1, name: 'buy_block_rise_pct' })
  root.appendChild(createSettingRow('종목 상승률 매수차단', riseInput.el))

  // 하락률 제한
  fallInput = createNumInput({ value: 0, onChange: v => { vals.buy_block_fall_pct = v; saveHelper!.autoSave('buy_block_fall_pct', v) }, step: 1, name: 'buy_block_fall_pct' })
  root.appendChild(createSettingRow('종목 하락률 매수차단', fallInput.el))

  // 체결강도 하한
  strengthInput = createNumInput({ value: 0, onChange: v => { vals.buy_min_strength = v; saveHelper!.autoSave('buy_min_strength', v) }, step: 1, name: 'buy_min_strength' })
  root.appendChild(createSettingRow('종목 체결강도 매수차단', strengthInput.el))

  // ── 매수 가산점 섹션 ──
  root.appendChild(sectionTitle('매수 가산점 (+N)'))

  // --- 5일 고가 돌파 ---
  {
    const r = createBoostScoreSection(root, '5일 고가 돌파', 'boost_high_breakout_on', 'boost_high_breakout_score', vals, saveHelper!)
    boostHighToggle = r.toggle; boostHighScoreInput = r.scoreInput; boostHighControls = r.controls
  }

  // --- 프로그램 순매수 ---
  {
    const r = createBoostScoreSection(root, '프로그램 순매수', 'boost_program_net_buy_on', 'boost_program_net_buy_score', vals, saveHelper!)
    boostProgramToggle = r.toggle; boostProgramScoreInput = r.scoreInput; boostProgramControls = r.controls
  }

  // --- 거래대금 순위 ---
  {
    const r = createBoostScoreSection(root, '거래대금 순위 (보유제외)', 'boost_trade_amount_rank_on', 'boost_trade_amount_rank_score', vals, saveHelper!)
    boostTradeAmountToggle = r.toggle; boostTradeAmountScoreInput = r.scoreInput; boostTradeAmountControls = r.controls
  }

  // --- 매수/매도호가 잔량비율 ---
  {
    const block = document.createElement('div')
    block.style.borderBottom = '1px solid #eee'

    // Row 1: toggle + label | 가산점 + input
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    boostOrderToggle = createToggleBtn({ on: false, onClick: () => {
      const next = !vals.boost_order_ratio_on
      vals.boost_order_ratio_on = next
      boostOrderToggle!.setOn(next)
      if (boostOrderControls) {
        setDisabled(boostOrderControls, !next)
      }
      saveHelper!.autoSave('boost_order_ratio_on', next)
    }})
    labelWrap.appendChild(boostOrderToggle.el)
    const label = document.createElement('span')
    label.textContent = '매수/매도호가 잔량비율'
    labelWrap.appendChild(label)

    const row1Controls = document.createElement('span')
    row1Controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    setDisabled(row1Controls, true)
    boostOrderControls = row1Controls

    boostOrderScoreInput = createNumInput({ value: 1.0, onChange: v => { vals.boost_order_ratio_score = v; saveHelper!.autoSave('boost_order_ratio_score', v) }, step: 1, name: 'boost_order_ratio_score' })
    row1Controls.appendChild(boostOrderScoreInput.el)

    const row1 = document.createElement('div')
    Object.assign(row1.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0' })
    row1.appendChild(labelWrap)
    row1.appendChild(row1Controls)
    block.appendChild(row1)

    root.appendChild(block)
  }

  // ── 매수 금액 섹션 ──
  root.appendChild(sectionTitle('매수 금액 한도'))

  // 매수 주문 유형 (시장가 고정)
  root.appendChild(createSettingRow('매수 주문 유형', createFixedValue('시장가')))

  // 일일 최대 매수 금액 (토글 + 금액 입력)
  maxDailyInput = createMoneyInput({ value: 0, onChange: v => { vals.max_daily_total_buy_amt = v; saveHelper!.autoSave('max_daily_total_buy_amt', v) }, name: 'max_daily_total_buy_amt' })
  {
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    maxDailyToggle = createToggleBtn({ on: false, onClick: () => {
      const next = !maxDailyToggle!.isOn()
      vals.max_daily_total_buy_on = next
      maxDailyToggle!.setOn(next)
      if (maxDailyInput) setDisabled(maxDailyInput.el, !next)
      saveHelper!.autoSave('max_daily_total_buy_on', next)
    }})
    labelWrap.appendChild(maxDailyToggle.el)
    const label = document.createElement('span')
    label.textContent = '전체 일일 최대 매수 금액'
    labelWrap.appendChild(label)
    root.appendChild(createSettingRow(labelWrap, maxDailyInput.el))
  }

  // 최대 동시 보유 종목 수
  maxStockCntInput = createNumInput({ value: 0, onChange: v => { vals.max_stock_cnt = v; saveHelper!.autoSave('max_stock_cnt', v) }, name: 'max_stock_cnt' })
  root.appendChild(createSettingRow('최대 동시 보유 종목 수', maxStockCntInput.el))

  // ── 매수 주문 간격 섹션 ──
  root.appendChild(sectionTitle('매수 주문 간격'))
  {
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    buyIntervalToggle = createToggleBtn({ on: false, onClick: () => {
      const next = !buyIntervalToggle!.isOn()
      vals.buy_interval_on = next
      buyIntervalToggle!.setOn(next)
      if (buyIntervalControls) {
        setDisabled(buyIntervalControls, !next)
      }
      saveHelper!.autoSave('buy_interval_on', next)
    }})
    labelWrap.appendChild(buyIntervalToggle.el)
    const label = document.createElement('span')
    label.textContent = '매수 주문 간격 활성화 (분)'
    labelWrap.appendChild(label)

    const controls = document.createElement('span')
    controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    setDisabled(controls, true)
    buyIntervalControls = controls

    buyIntervalInput = createNumInput({ value: 0, onChange: v => { vals.buy_interval_min = v; saveHelper!.autoSave('buy_interval_min', v) }, step: 1, name: 'buy_interval_min' })
    controls.appendChild(buyIntervalInput.el)

    root.appendChild(createSettingRow(labelWrap, controls))
  }

  // ── 동일 종목 재매수 제어 섹션 ──
  root.appendChild(sectionTitle('동일 종목 재매수 제어'))

  // 종목당 일일 최대 매수 금액
  buyAmtInput = createMoneyInput({ value: 0, onChange: v => { vals.buy_amt = v; saveHelper!.autoSave('buy_amt', v) }, name: 'buy_amt' })
  root.appendChild(createSettingRow('종목당 일일 최대 매수 금액', buyAmtInput.el))

  // 재매수 차단 ON/OFF + 차단 기간 select
  {
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    rebuyBlockToggle = createToggleBtn({ on: true, onClick: () => {
      const next = !vals.rebuy_block_on
      vals.rebuy_block_on = next
      rebuyBlockToggle!.setOn(next)
      if (rebuyBlockControls) {
        setDisabled(rebuyBlockControls, !next)
      }
      saveHelper!.autoSave('rebuy_block_on', next)
    }})
    labelWrap.appendChild(rebuyBlockToggle.el)
    const label = document.createElement('span')
    label.textContent = '재매수 차단 활성화'
    labelWrap.appendChild(label)

    const controls = document.createElement('span')
    controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    rebuyBlockControls = controls

    rebuyBlockSelect = createSelect({
      items: [
        { value: 'today', label: '당일' },
        { value: '1h', label: '1시간' },
        { value: '3h', label: '3시간' },
        { value: '6h', label: '6시간' },
        { value: '12h', label: '12시간' },
        { value: '24h', label: '24시간' },
      ],
      value: String(vals.rebuy_block_period ?? 'today'),
      onChange: v => { vals.rebuy_block_period = v; saveHelper!.autoSave('rebuy_block_period', v) },
      name: 'rebuy_block_period',
    })
    controls.appendChild(rebuyBlockSelect.el)

    root.appendChild(createSettingRow(labelWrap, controls))
  }

  container.appendChild(root)

  // 초기 설정 동기화 + 구독
  unsubSettings = startSettingsSubscription(settingsMgr, syncFromSettings)
}

/* ── unmount ── */
function unmount(): void {
  destroySettingsPage(unsubSettings, saveHelper, settingsMgr)
  unsubSettings = null; saveHelper = null; settingsMgr = null
  riseInput = null; fallInput = null; strengthInput = null
  maxDailyToggle = null; maxDailyInput = null; maxStockCntInput = null; buyAmtInput = null
  boostHighToggle = null; boostHighScoreInput = null; boostHighControls = null
  boostOrderToggle = null
  boostOrderScoreInput = null; boostOrderControls = null
  boostProgramToggle = null; boostProgramScoreInput = null; boostProgramControls = null
  boostTradeAmountToggle = null; boostTradeAmountScoreInput = null; boostTradeAmountControls = null
  rebuyBlockToggle = null; rebuyBlockSelect = null; rebuyBlockControls = null
  buyIntervalToggle = null; buyIntervalInput = null; buyIntervalControls = null
  vals = {}
}

export default { mount, unmount }