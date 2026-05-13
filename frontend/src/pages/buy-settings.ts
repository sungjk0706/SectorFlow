// frontend/src/pages/buy-settings.ts
// 매수설정 카드 — Vanilla TS PageModule
// BuySettingsCard.tsx + BuySettingsSection.tsx + BuyBlockSection.tsx + QuickToggle + TimePairInput 통합

import { appStore } from '../stores/appStore'
import { createSettingsManager, type SettingsManager, createGlobalWsBadge } from '../settings'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingRow, createNumInput, createMoneyInput, createToggleBtn, createFixedValue } from '../components/common/setting-row'
import { toastResult } from '../components/common/save-toast'
import { sectionTitle } from '../components/common/settings-common'
import { createDualLabelSlider, type DualLabelSliderHandle } from '../components/common/create-slider'
import { FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import { createTimePairInput, type TimePairInputHandle } from '../components/common/time-pair-input'
import type { AppSettings } from '../types'

/* ── 모듈 상태 ── */
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let saving = false
let pendingSave: { key: string; value: unknown } | null = null
let debounceTimer: ReturnType<typeof setTimeout> | null = null
// 현재 값 추적
let vals: Record<string, unknown> = {}
let localOrderRatioPct: number | null = null  // 사용자가 설정한 값 (null=서버값 사용)

// 입력 컴포넌트 참조
let wsBadge: HTMLElement | null = null
let autoBuyToggle: ReturnType<typeof createToggleBtn> | null = null
let timePairHandle: TimePairInputHandle | null = null
let kospiGuardToggle: ReturnType<typeof createToggleBtn> | null = null
let kospiDropInput: ReturnType<typeof createNumInput> | null = null
let kosdaqGuardToggle: ReturnType<typeof createToggleBtn> | null = null
let kosdaqDropInput: ReturnType<typeof createNumInput> | null = null
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

/* ── 헬퍼 ── */
function autoSave(key: string, value: unknown): void {
  if (!settingsMgr) return
  // 디바운스: 마지막 입력 후 400ms 대기 후 저장
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    debounceTimer = null
    flushSave(key, value)
  }, 400)
}

function flushSave(key: string, value: unknown): void {
  if (!settingsMgr) return
  if (saving) {
    pendingSave = { key, value }
    return
  }
  saving = true
  const run = async (k: string, v: unknown): Promise<void> => {
    const res = await settingsMgr!.saveSection({ [k]: v })
    toastResult(res)
    if (pendingSave) {
      const next = pendingSave
      pendingSave = null
      await run(next.key, next.value)
    }
    saving = false
  }
  run(key, value)
}

async function saveImmediate(patch: Record<string, unknown>): Promise<void> {
  if (!settingsMgr) return
  const res = await settingsMgr.saveSection(patch)
  toastResult(res)
}

/* ── 설정 동기화 ── */
function syncFromSettings(s: AppSettings): void {
  const r = s as unknown as Record<string, unknown>
  vals = { ...r }

  // 자동매수 토글
  autoBuyToggle?.setOn(!!r.auto_buy_on)

  // TimePairInput (공통 컴포넌트)
  if (timePairHandle) {
    const start = String(r.buy_time_start ?? '09:00')
    const end = String(r.buy_time_end ?? '15:00')
    timePairHandle.setValue(start, end)
    timePairHandle.setEnabled(!!r.auto_buy_on)
  }

  // 매수 조건
  kospiGuardToggle?.setOn(!!r.buy_index_guard_kospi_on)
  kospiDropInput?.setValue(Number(r.buy_index_kospi_drop) || 0)
  kosdaqGuardToggle?.setOn(!!r.buy_index_guard_kosdaq_on)
  kosdaqDropInput?.setValue(Number(r.buy_index_kosdaq_drop) || 0)
  riseInput?.setValue(Number(r.buy_block_rise_pct) || 0)
  fallInput?.setValue(Number(r.buy_block_fall_pct) || 0)
  strengthInput?.setValue(Number(r.buy_min_strength) || 0)

  // 매수 금액
  maxDailyInput?.setValue(Number(r.max_daily_total_buy_amt) || 0)
  maxStockCntInput?.setValue(Number(r.max_stock_cnt) || 0)
  buyAmtInput?.setValue(Number(r.buy_amt) || 0)

  // 매수 가산점
  const highOn = !!r.boost_high_breakout_on
  boostHighToggle?.setOn(highOn)
  boostHighScoreInput?.setValue(Number(r.boost_high_breakout_score) ?? 1.0)
  if (boostHighControls) {
    boostHighControls.style.opacity = highOn ? '1' : '0.4'
    boostHighControls.style.pointerEvents = highOn ? 'auto' : 'none'
  }

  const orderOn = !!r.boost_order_ratio_on
  boostOrderToggle?.setOn(orderOn)
  const signedPct = Number(r.boost_order_ratio_pct ?? 20)
  if (localOrderRatioPct === null) {
    boostOrderDualSlider?.setValue(signedPct + 100)
  }
  boostOrderScoreInput?.setValue(Number(r.boost_order_ratio_score) ?? 1.0)
  if (boostOrderControls) {
    boostOrderControls.style.opacity = orderOn ? '1' : '0.4'
    boostOrderControls.style.pointerEvents = orderOn ? 'auto' : 'none'
  }
  if (boostOrderRow2) {
    boostOrderRow2.style.opacity = orderOn ? '1' : '0.4'
    boostOrderRow2.style.pointerEvents = orderOn ? 'auto' : 'none'
  }
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('buy-settings')
  settingsMgr = createSettingsManager(appStore)
  saving = false
  pendingSave = null
  vals = {}

  const root = document.createElement('div')

  // 제목 + WS 상태 배지
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' })
  const h4 = document.createElement('h4')
  h4.style.margin = '0'
  h4.textContent = '매수 설정'
  headerRow.appendChild(h4)

  wsBadge = createGlobalWsBadge()
  headerRow.appendChild(wsBadge)
  root.appendChild(headerRow)

  // ── 자동매수 토글 + TimePairInput (1행) ──
  const autoRow = document.createElement('div')
  Object.assign(autoRow.style, { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px', padding: '4px 0' })

  const toggleLabel = document.createElement('span')
  Object.assign(toggleLabel.style, { fontSize: FONT_SIZE.body, fontWeight: FONT_WEIGHT.normal, whiteSpace: 'nowrap' })
  toggleLabel.textContent = '자동매수'

  autoBuyToggle = createToggleBtn({
    on: false,
    onClick: async () => {
      const next = !vals.auto_buy_on
      vals.auto_buy_on = next
      autoBuyToggle!.setOn(next)
      if (timePairHandle) {
        timePairHandle.setEnabled(next)
      }
      const res = await settingsMgr!.saveSection({ auto_buy_on: next })
      toastResult(res)
      if (!res.ok) {
        vals.auto_buy_on = !next
        autoBuyToggle!.setOn(!next)
        if (timePairHandle) {
          timePairHandle.setEnabled(!next)
        }
      }
    },
  })

  // 공통 TimePairInput 컴포넌트 사용
  const startTime = String(vals.buy_time_start ?? '09:00')
  const endTime = String(vals.buy_time_end ?? '15:00')
  
  const { el: tpWrap, handle: handle } = createTimePairInput(
    startTime,
    endTime,
    (start, end) => {
      // 시간 변경 시 자동 저장
      if (settingsMgr) {
        const dirty: Record<string, unknown> = {}
        if (start !== vals.buy_time_start) dirty.buy_time_start = start
        if (end !== vals.buy_time_end) dirty.buy_time_end = end
        if (Object.keys(dirty).length > 0) {
          settingsMgr.saveSection(dirty).then(toastResult)
          Object.assign(vals, dirty)
        }
      }
    }
  )
  timePairHandle = handle
  tpWrap.style.marginLeft = 'auto'

  autoRow.appendChild(toggleLabel)
  autoRow.appendChild(autoBuyToggle.el)
  autoRow.appendChild(tpWrap)
  root.appendChild(autoRow)

  // ── 매수 조건 섹션 ──
  root.appendChild(sectionTitle('전역 조건'))

  // 코스피 하락 제한
  kospiGuardToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.buy_index_guard_kospi_on
    vals.buy_index_guard_kospi_on = next
    kospiGuardToggle!.setOn(next)
    await saveImmediate({ buy_index_guard_kospi_on: next })
  }})
  const kospiLabelWrap = document.createElement('span')
  kospiLabelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
  kospiLabelWrap.appendChild(kospiGuardToggle.el)
  const kospiText = document.createElement('span')
  kospiText.textContent = '코스피 하락 전역매수차단 (%)'
  kospiLabelWrap.appendChild(kospiText)
  kospiDropInput = createNumInput({ value: 0, onChange: v => { vals.buy_index_kospi_drop = v; autoSave('buy_index_kospi_drop', v) }, step: 1, name: 'buy_index_kospi_drop' })
  root.appendChild(createSettingRow(kospiLabelWrap, kospiDropInput.el))

  // 코스닥 하락 제한
  kosdaqGuardToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.buy_index_guard_kosdaq_on
    vals.buy_index_guard_kosdaq_on = next
    kosdaqGuardToggle!.setOn(next)
    await saveImmediate({ buy_index_guard_kosdaq_on: next })
  }})
  const kosdaqLabelWrap = document.createElement('span')
  kosdaqLabelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
  kosdaqLabelWrap.appendChild(kosdaqGuardToggle.el)
  const kosdaqText = document.createElement('span')
  kosdaqText.textContent = '코스닥 하락 전역매수차단 (%)'
  kosdaqLabelWrap.appendChild(kosdaqText)
  kosdaqDropInput = createNumInput({ value: 0, onChange: v => { vals.buy_index_kosdaq_drop = v; autoSave('buy_index_kosdaq_drop', v) }, step: 1, name: 'buy_index_kosdaq_drop' })
  root.appendChild(createSettingRow(kosdaqLabelWrap, kosdaqDropInput.el))

  // 상승률 제한
  riseInput = createNumInput({ value: 0, onChange: v => { vals.buy_block_rise_pct = v; autoSave('buy_block_rise_pct', v) }, step: 1, name: 'buy_block_rise_pct' })
  root.appendChild(createSettingRow('종목 상승률 매수차단 (%)', riseInput.el))

  // 하락률 제한
  fallInput = createNumInput({ value: 0, onChange: v => { vals.buy_block_fall_pct = v; autoSave('buy_block_fall_pct', v) }, step: 1, name: 'buy_block_fall_pct' })
  root.appendChild(createSettingRow('종목 하락률 매수차단 (%)', fallInput.el))

  // 체결강도 하한
  strengthInput = createNumInput({ value: 0, onChange: v => { vals.buy_min_strength = v; autoSave('buy_min_strength', v) }, step: 1, name: 'buy_min_strength' })
  root.appendChild(createSettingRow('종목 체결강도 매수차단 (%)', strengthInput.el))

  // ── 매수 가산점 섹션 ──
  root.appendChild(sectionTitle('매수 가산점'))

  // --- 5일 고가 돌파 ---
  {
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    boostHighToggle = createToggleBtn({ on: false, onClick: () => {
      const next = !vals.boost_high_breakout_on
      vals.boost_high_breakout_on = next
      boostHighToggle!.setOn(next)
      if (boostHighControls) {
        boostHighControls.style.opacity = next ? '1' : '0.4'
        boostHighControls.style.pointerEvents = next ? 'auto' : 'none'
      }
      autoSave('boost_high_breakout_on', next)
    }})
    labelWrap.appendChild(boostHighToggle.el)
    const label = document.createElement('span')
    label.textContent = '5일 고가 돌파'
    labelWrap.appendChild(label)

    const controls = document.createElement('span')
    controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    controls.style.opacity = '0.4'
    controls.style.pointerEvents = 'none'
    boostHighControls = controls

    const scoreLabel = document.createElement('span')
    scoreLabel.textContent = '가산점'
    scoreLabel.style.cssText = 'font-size:12px;color:#888;white-space:nowrap;'
    controls.appendChild(scoreLabel)

    boostHighScoreInput = createNumInput({ value: 1.0, onChange: v => { vals.boost_high_breakout_score = v; autoSave('boost_high_breakout_score', v) }, step: 1, name: 'boost_high_breakout_score' })
    controls.appendChild(boostHighScoreInput.el)

    root.appendChild(createSettingRow(labelWrap, controls))
  }

  // --- 매수/매도 호가 잔량비율 ---
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
        boostOrderControls.style.opacity = next ? '1' : '0.4'
        boostOrderControls.style.pointerEvents = next ? 'auto' : 'none'
      }
      if (boostOrderRow2) {
        boostOrderRow2.style.opacity = next ? '1' : '0.4'
        boostOrderRow2.style.pointerEvents = next ? 'auto' : 'none'
      }
      autoSave('boost_order_ratio_on', next)
    }})
    labelWrap.appendChild(boostOrderToggle.el)
    const label = document.createElement('span')
    label.textContent = '매수/매도 호가 잔량비율'
    labelWrap.appendChild(label)

    const row1Controls = document.createElement('span')
    row1Controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    row1Controls.style.opacity = '0.4'
    row1Controls.style.pointerEvents = 'none'
    boostOrderControls = row1Controls

    const scoreLabel = document.createElement('span')
    scoreLabel.textContent = '가산점'
    scoreLabel.style.cssText = 'font-size:12px;color:#888;white-space:nowrap;'
    row1Controls.appendChild(scoreLabel)

    boostOrderScoreInput = createNumInput({ value: 1.0, onChange: v => { vals.boost_order_ratio_score = v; autoSave('boost_order_ratio_score', v) }, step: 1, name: 'boost_order_ratio_score' })
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
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#dc3545',
      rightColorLight: '#f1aeb5',
      onChange(_v) {
        // live preview only
      },
      onCommit(v) {
        vals.boost_order_ratio_pct = v - 100
        localOrderRatioPct = v - 100
        saveImmediate({ boost_order_ratio_pct: v - 100 })
      },
    })

    const row2 = document.createElement('div')
    Object.assign(row2.style, { padding: '0 0 6px' })
    row2.appendChild(boostOrderDualSlider.el)
    row2.style.opacity = '0.4'
    row2.style.pointerEvents = 'none'
    boostOrderRow2 = row2

    block.appendChild(row2)
    root.appendChild(block)
  }

  // ── 매수 금액 섹션 ──
  root.appendChild(sectionTitle('매수 한도'))

  // 매수 주문 유형 (시장가 고정)
  root.appendChild(createSettingRow('매수 주문 유형', createFixedValue('시장가')))

  // 일일 최대 매수 금액
  maxDailyInput = createMoneyInput({ value: 0, onChange: v => { vals.max_daily_total_buy_amt = v; autoSave('max_daily_total_buy_amt', v) }, name: 'max_daily_total_buy_amt' })
  root.appendChild(createSettingRow('일일 최대 매수 금액', maxDailyInput.el))

  // 최대 동시 보유 종목 수
  maxStockCntInput = createNumInput({ value: 0, onChange: v => { vals.max_stock_cnt = v; autoSave('max_stock_cnt', v) }, name: 'max_stock_cnt' })
  root.appendChild(createSettingRow('최대 동시 보유 종목 수', maxStockCntInput.el))

  // 종목당 일일 최대 매수 금액
  buyAmtInput = createMoneyInput({ value: 0, onChange: v => { vals.buy_amt = v; autoSave('buy_amt', v) }, name: 'buy_amt' })
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
  notifyPageInactive('buy-settings')
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null }
  saving = false
  pendingSave = null
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
  wsBadge = null
  autoBuyToggle = null
  timePairHandle = null
  kospiGuardToggle = null; kospiDropInput = null
  kosdaqGuardToggle = null; kosdaqDropInput = null
  riseInput = null; fallInput = null; strengthInput = null
  maxDailyInput = null; maxStockCntInput = null; buyAmtInput = null
  boostHighToggle = null; boostHighScoreInput = null; boostHighControls = null
  boostOrderToggle = null; boostOrderDualSlider = null; boostOrderScoreInput = null; boostOrderControls = null; boostOrderRow2 = null
  vals = {}
  localOrderRatioPct = null
}

export default { mount, unmount }