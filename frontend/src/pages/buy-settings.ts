// frontend/src/pages/buy-settings.ts
// 매수설정 카드 — Vanilla TS PageModule
// BuySettingsCard.tsx + BuySettingsSection.tsx + BuyBlockSection.tsx + QuickToggle + TimePairInput 통합

import { uiStore } from '../stores/uiStore'
import { createSettingsManager, type SettingsManager } from '../settings'
import { createSettingRow, createNumInput, createMoneyInput, createToggleBtn, createFixedValue } from '../components/common/setting-row'
import { sectionTitle } from '../components/common/settings-common'
import { createDualLabelSlider, type DualLabelSliderHandle } from '../components/common/create-slider'
import { createAutoSaveHelper } from '../utils/settings-save'
import { setDisabled, COLOR } from '../components/common/ui-styles'
import type { AppSettings } from '../types'

/* ── 모듈 상태 ── */
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let saveHelper: ReturnType<typeof createAutoSaveHelper> | null = null
// 현재 값 추적
let vals: Record<string, unknown> = {}

// 입력 컴포넌트 참조
let riseInput: ReturnType<typeof createNumInput> | null = null
let fallInput: ReturnType<typeof createNumInput> | null = null
let strengthInput: ReturnType<typeof createNumInput> | null = null
let maxDailyInput: ReturnType<typeof createMoneyInput> | null = null
let maxStockCntInput: ReturnType<typeof createNumInput> | null = null
let buyAmtInput: ReturnType<typeof createMoneyInput> | null = null

// 가산점 UI 참조
let boostHighToggle: ReturnType<typeof createToggleBtn> | null = null
let boostHighScoreInput: ReturnType<typeof createNumInput> | null = null
let boostHighControls: HTMLElement | null = null

let boostOrderToggle: ReturnType<typeof createToggleBtn> | null = null
let boostOrderDualSlider: DualLabelSliderHandle | null = null
let boostOrderScoreInput: ReturnType<typeof createNumInput> | null = null
let boostOrderControls: HTMLElement | null = null
let boostOrderRow2: HTMLElement | null = null

let boostProgramToggle: ReturnType<typeof createToggleBtn> | null = null
let boostProgramScoreInput: ReturnType<typeof createNumInput> | null = null
let boostProgramControls: HTMLElement | null = null


/* ── 헬퍼 ── */
function syncAfterSave(): void {
  const latest = settingsMgr?.getSettings()
  if (latest) {
    syncFromSettings(latest)
  }
}

/* ── 설정 동기화 ── */
function syncFromSettings(s: AppSettings): void {
  if (boostOrderDualSlider && boostOrderDualSlider.isInteracting) return
  const r = s as Record<string, unknown>
  vals = { ...r }

  const act = document.activeElement

  // 매수 조건
  if (riseInput && (!act || !riseInput.el.contains(act))) riseInput.setValue(Number(r.buy_block_rise_pct) || 0)
  if (fallInput && (!act || !fallInput.el.contains(act))) fallInput.setValue(Number(r.buy_block_fall_pct) || 0)
  if (strengthInput && (!act || !strengthInput.el.contains(act))) strengthInput.setValue(Number(r.buy_min_strength) || 0)

  // 매수 금액
  if (maxDailyInput && (!act || !maxDailyInput.el.contains(act))) maxDailyInput.setValue(Number(r.max_daily_total_buy_amt) || 0)
  if (maxStockCntInput && (!act || !maxStockCntInput.el.contains(act))) maxStockCntInput.setValue(Number(r.max_stock_cnt) || 0)
  if (buyAmtInput && (!act || !buyAmtInput.el.contains(act))) buyAmtInput.setValue(Number(r.buy_amt) || 0)

  // 매수 가산점
  const highOn = !!r.boost_high_breakout_on
  boostHighToggle?.setOn(highOn)
  if (boostHighScoreInput && (!act || !boostHighScoreInput.el.contains(act))) boostHighScoreInput.setValue(Number(r.boost_high_breakout_score) ?? 1.0)
  if (boostHighControls) {
    setDisabled(boostHighControls, !highOn)
  }

  const orderOn = !!r.boost_order_ratio_on
  boostOrderToggle?.setOn(orderOn)
  const signedPct = Number(r.boost_order_ratio_pct ?? 20)
  boostOrderDualSlider?.setValue(signedPct + 100)
  boostOrderScoreInput?.setValue(Number(r.boost_order_ratio_score) ?? 1.0)
  if (boostOrderControls) {
    setDisabled(boostOrderControls, !orderOn)
  }
  if (boostOrderRow2) {
    setDisabled(boostOrderRow2, !orderOn)
  }

  const programOn = !!r.boost_program_net_buy_on
  boostProgramToggle?.setOn(programOn)
  if (boostProgramScoreInput && (!act || !boostProgramScoreInput.el.contains(act))) boostProgramScoreInput.setValue(Number(r.boost_program_net_buy_score) ?? 1.0)
  if (boostProgramControls) {
    setDisabled(boostProgramControls, !programOn)
  }

}

/* ── mount ── */
function mount(container: HTMLElement): void {
  settingsMgr = createSettingsManager(uiStore)
  saveHelper = createAutoSaveHelper(settingsMgr, syncAfterSave)
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
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    boostHighToggle = createToggleBtn({ on: false, onClick: () => {
      const next = !vals.boost_high_breakout_on
      vals.boost_high_breakout_on = next
      boostHighToggle!.setOn(next)
      if (boostHighControls) {
        setDisabled(boostHighControls, !next)
      }
      saveHelper!.autoSave('boost_high_breakout_on', next)
    }})
    labelWrap.appendChild(boostHighToggle.el)
    const label = document.createElement('span')
    label.textContent = '5일 고가 돌파'
    labelWrap.appendChild(label)

    const controls = document.createElement('span')
    controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    setDisabled(controls, true)
    boostHighControls = controls

    boostHighScoreInput = createNumInput({ value: 1.0, onChange: v => { vals.boost_high_breakout_score = v; saveHelper!.autoSave('boost_high_breakout_score', v) }, step: 1, name: 'boost_high_breakout_score' })
    controls.appendChild(boostHighScoreInput.el)

    root.appendChild(createSettingRow(labelWrap, controls))
  }

  // --- 프로그램 순매수 ---
  {
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    boostProgramToggle = createToggleBtn({ on: false, onClick: () => {
      const next = !vals.boost_program_net_buy_on
      vals.boost_program_net_buy_on = next
      boostProgramToggle!.setOn(next)
      if (boostProgramControls) {
        setDisabled(boostProgramControls, !next)
      }
      saveHelper!.autoSave('boost_program_net_buy_on', next)
    }})
    labelWrap.appendChild(boostProgramToggle.el)
    const label = document.createElement('span')
    label.textContent = '프로그램 순매수'
    labelWrap.appendChild(label)

    const controls = document.createElement('span')
    controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    setDisabled(controls, true)
    boostProgramControls = controls

    boostProgramScoreInput = createNumInput({ value: 1.0, onChange: v => { vals.boost_program_net_buy_score = v; saveHelper!.autoSave('boost_program_net_buy_score', v) }, step: 1, name: 'boost_program_net_buy_score' })
    controls.appendChild(boostProgramScoreInput.el)

    root.appendChild(createSettingRow(labelWrap, controls))
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
      if (boostOrderRow2) {
        setDisabled(boostOrderRow2, !next)
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

    // Row 2: dual label slider
    boostOrderDualSlider = createDualLabelSlider({
      min: 0, max: 200, value: 120, step: 1,
      leftLabel: (v) => v < 100 ? `매도잔량 +${100 - v}%` : '매도잔량',
      rightLabel: (v) => v > 100 ? `매수잔량 +${v - 100}%` : '매수잔량',
      leftColor: COLOR.down,
      leftColorLight: COLOR.downLight,
      rightColor: COLOR.up,
      rightColorLight: COLOR.upLight,
      onChange(_v) {
        // live preview only
      },
      onCommit(v) {
        vals.boost_order_ratio_pct = v - 100
        saveHelper!.autoSave('boost_order_ratio_pct', v - 100)
      },
    })

    const row2 = document.createElement('div')
    Object.assign(row2.style, { padding: '0 0 6px' })
    row2.appendChild(boostOrderDualSlider.el)
    setDisabled(row2, true)
    boostOrderRow2 = row2

    block.appendChild(row2)
    root.appendChild(block)
  }

  // ── 매수 금액 섹션 ──
  root.appendChild(sectionTitle('매수 한도'))

  // 매수 주문 유형 (시장가 고정)
  root.appendChild(createSettingRow('매수 주문 유형', createFixedValue('시장가')))

  // 일일 최대 매수 금액
  maxDailyInput = createMoneyInput({ value: 0, onChange: v => { vals.max_daily_total_buy_amt = v; saveHelper!.autoSave('max_daily_total_buy_amt', v) }, name: 'max_daily_total_buy_amt' })
  root.appendChild(createSettingRow('일일 최대 매수 금액', maxDailyInput.el))

  // 최대 동시 보유 종목 수
  maxStockCntInput = createNumInput({ value: 0, onChange: v => { vals.max_stock_cnt = v; saveHelper!.autoSave('max_stock_cnt', v) }, name: 'max_stock_cnt' })
  root.appendChild(createSettingRow('최대 동시 보유 종목 수', maxStockCntInput.el))

  // 종목당 일일 최대 매수 금액
  buyAmtInput = createMoneyInput({ value: 0, onChange: v => { vals.buy_amt = v; saveHelper!.autoSave('buy_amt', v) }, name: 'buy_amt' })
  root.appendChild(createSettingRow('종목당 일일 최대 매수 금액', buyAmtInput.el))

  container.appendChild(root)

  // 초기 설정 동기화
  const initial = settingsMgr.getSettings()
  if (initial) syncFromSettings(initial)

  // 설정 변경 구독
  unsubSettings = settingsMgr.subscribe(() => {
    const s = settingsMgr?.getSettings()
    if (s) syncFromSettings(s)
  })
}

/* ── unmount ── */
function unmount(): void {
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (saveHelper) { saveHelper.destroy(); saveHelper = null }
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
  riseInput = null; fallInput = null; strengthInput = null
  maxDailyInput = null; maxStockCntInput = null; buyAmtInput = null
  boostHighToggle = null; boostHighScoreInput = null; boostHighControls = null
  boostOrderToggle = null
  if (boostOrderDualSlider && typeof boostOrderDualSlider.destroy === 'function') {
    boostOrderDualSlider.destroy()
  }
  boostOrderDualSlider = null
  boostOrderScoreInput = null; boostOrderControls = null; boostOrderRow2 = null
  boostProgramToggle = null; boostProgramScoreInput = null; boostProgramControls = null
  vals = {}
}

export default { mount, unmount }