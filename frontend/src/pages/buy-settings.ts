// frontend/src/pages/buy-settings.ts
// 매수설정 카드 — Vanilla TS PageModule
// BuySettingsCard.tsx + BuySettingsSection.tsx + BuyBlockSection.tsx + QuickToggle + TimePairInput 통합

import { createSettingRow, createNumInput, createMoneyInput, createToggleBtn, createFixedValue, createSelect, createSettingToggleRow } from '../components/common/setting-row'
import { sectionTitle } from '../components/common/settings-common'
import { initSettingsPage, startSettingsSubscription, destroySettingsPage } from '../utils/settings-page'
import type { AutoSaveHelper } from '../utils/settings-save'
import type { SettingsManager } from '../settings'
import { setDisabled, COLOR } from '../components/common/ui-styles'
import { createDualLabelSlider, type DualLabelSliderHandle } from '../components/common/create-slider'
import { createCardTitle } from '../components/common/card-title'
import type { AppSettings } from '../types'

/* ── 모듈 상태 ── */
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let saveHelper: AutoSaveHelper | null = null
// 현재 값 추적
let vals: Record<string, unknown> = {}

// 입력 컴포넌트 참조
let riseToggle: ReturnType<typeof createToggleBtn> | null = null
let riseInput: ReturnType<typeof createNumInput> | null = null
let riseControls: HTMLElement | null = null
let fallToggle: ReturnType<typeof createToggleBtn> | null = null
let fallInput: ReturnType<typeof createNumInput> | null = null
let fallControls: HTMLElement | null = null
let maxDailyToggle: ReturnType<typeof createToggleBtn> | null = null
let maxDailyInput: ReturnType<typeof createMoneyInput> | null = null
let maxDailyControls: HTMLElement | null = null
let maxStockCntToggle: ReturnType<typeof createToggleBtn> | null = null
let maxStockCntInput: ReturnType<typeof createNumInput> | null = null
let maxStockCntControls: HTMLElement | null = null
let buyAmtToggle: ReturnType<typeof createToggleBtn> | null = null
let buyAmtInput: ReturnType<typeof createMoneyInput> | null = null
let buyAmtControls: HTMLElement | null = null

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

let boostNewsToggle: ReturnType<typeof createToggleBtn> | null = null
let boostNewsScoreInput: ReturnType<typeof createNumInput> | null = null
let boostNewsControls: HTMLElement | null = null

// 재매수 차단 UI 참조
let rebuyBlockToggle: ReturnType<typeof createToggleBtn> | null = null
let rebuyBlockSelect: ReturnType<typeof createSelect> | null = null
let rebuyBlockControls: HTMLElement | null = null

// 매수 주문 간격 UI 참조
let buyIntervalToggle: ReturnType<typeof createToggleBtn> | null = null
let buyIntervalInput: ReturnType<typeof createNumInput> | null = null
let buyIntervalControls: HTMLElement | null = null


/* ── 설정 동기화 섹션 ── */
// syncFromSettings() 92줄 → 섹션별 동기화 함수로 분할 (P24)

function syncBuyBlock(r: Record<string, unknown>, act: Element | null): void {
  const riseOn = !!r.buy_block_rise_on
  riseToggle?.setOn(riseOn)
  if (riseInput && (!act || !riseInput.el.contains(act))) riseInput.setValue(Number(r.buy_block_rise_pct ?? 0))
  if (riseControls) setDisabled(riseControls, !riseOn)

  const fallOn = !!r.buy_block_fall_on
  fallToggle?.setOn(fallOn)
  if (fallInput && (!act || !fallInput.el.contains(act))) fallInput.setValue(Number(r.buy_block_fall_pct ?? 0))
  if (fallControls) setDisabled(fallControls, !fallOn)
}

function syncBoost(r: Record<string, unknown>, act: Element | null): void {
  const highOn = !!r.boost_high_breakout_on
  boostHighToggle?.setOn(highOn)
  if (boostHighScoreInput && (!act || !boostHighScoreInput.el.contains(act))) boostHighScoreInput.setValue(Number(r.boost_high_breakout_score ?? 1.0))
  if (boostHighControls) {
    setDisabled(boostHighControls, !highOn)
  }

  const orderOn = !!r.boost_order_ratio_on
  boostOrderToggle?.setOn(orderOn)
  const signedPct = Number(r.boost_order_ratio_pct ?? 20)
  boostOrderDualSlider?.setValue(signedPct + 100)
  boostOrderScoreInput?.setValue(Number(r.boost_order_ratio_score ?? 1.0))
  if (boostOrderControls) {
    setDisabled(boostOrderControls, !orderOn)
  }
  if (boostOrderRow2) {
    setDisabled(boostOrderRow2, !orderOn)
  }

  const programOn = !!r.boost_program_net_buy_on
  boostProgramToggle?.setOn(programOn)
  if (boostProgramScoreInput && (!act || !boostProgramScoreInput.el.contains(act))) boostProgramScoreInput.setValue(Number(r.boost_program_net_buy_score ?? 1.0))
  if (boostProgramControls) {
    setDisabled(boostProgramControls, !programOn)
  }

  const newsOn = !!r.boost_news_on
  boostNewsToggle?.setOn(newsOn)
  if (boostNewsScoreInput && (!act || !boostNewsScoreInput.el.contains(act))) boostNewsScoreInput.setValue(Number(r.boost_news_score ?? 1.0))
  if (boostNewsControls) {
    setDisabled(boostNewsControls, !newsOn)
  }
}

function syncBuyAmount(r: Record<string, unknown>, act: Element | null): void {
  const dailyOn = !!r.max_daily_total_buy_on
  maxDailyToggle?.setOn(dailyOn)
  if (maxDailyInput && (!act || !maxDailyInput.el.contains(act))) maxDailyInput.setValue(Number(r.max_daily_total_buy_amt ?? 0))
  if (maxDailyControls) setDisabled(maxDailyControls, !dailyOn)

  const stockCntOn = !!r.max_stock_cnt_on
  maxStockCntToggle?.setOn(stockCntOn)
  if (maxStockCntInput && (!act || !maxStockCntInput.el.contains(act))) maxStockCntInput.setValue(Number(r.max_stock_cnt ?? 0))
  if (maxStockCntControls) setDisabled(maxStockCntControls, !stockCntOn)

  const buyAmtOn = !!r.buy_amt_on
  buyAmtToggle?.setOn(buyAmtOn)
  if (buyAmtInput && (!act || !buyAmtInput.el.contains(act))) buyAmtInput.setValue(Number(r.buy_amt ?? 0))
  if (buyAmtControls) setDisabled(buyAmtControls, !buyAmtOn)
}

function syncRebuy(r: Record<string, unknown>, act: Element | null): void {
  const rebuyOn = !!r.rebuy_block_on
  rebuyBlockToggle?.setOn(rebuyOn)
  if (rebuyBlockSelect && (!act || !rebuyBlockSelect.el.contains(act))) {
    rebuyBlockSelect.setValue(String(r.rebuy_block_period ?? 'today'))
  }
  if (rebuyBlockControls) {
    setDisabled(rebuyBlockControls, !rebuyOn)
  }
}

function syncBuyInterval(r: Record<string, unknown>, act: Element | null): void {
  const intervalOn = !!r.buy_interval_on
  buyIntervalToggle?.setOn(intervalOn)
  if (buyIntervalInput && (!act || !buyIntervalInput.el.contains(act))) buyIntervalInput.setValue(Number(r.buy_interval_sec ?? 30))
  if (buyIntervalControls) {
    setDisabled(buyIntervalControls, !intervalOn)
  }
}

/* ── 설정 동기화 ── */
function syncFromSettings(s: AppSettings): void {
  if (boostOrderDualSlider && boostOrderDualSlider.isInteracting) return
  const r = s as Record<string, unknown>
  vals = { ...r }

  const act = document.activeElement

  syncBuyBlock(r, act)
  syncBoost(r, act)
  syncBuyAmount(r, act)
  syncRebuy(r, act)
  syncBuyInterval(r, act)
}

/* ── mount 섹션 빌더 ── */
// 각 섹션은 독립된 빌더 함수로 분할 (P24 — mount() 233줄 → 섹션별 30~50줄)

function buildBuyBlockSection(root: HTMLElement): void {
  root.appendChild(sectionTitle('매수 차단'))

  // 상승률 제한 (토글 + 입력)
  riseInput = createNumInput({ value: 0, onChange: v => { const orig = Number(vals.buy_block_rise_pct); vals.buy_block_rise_pct = v; saveHelper!.autoSave('buy_block_rise_pct', v, () => { vals.buy_block_rise_pct = orig; riseInput!.setValue(orig) }) }, step: 1, min: 0, max: 100, suffix: '%', name: 'buy_block_rise_pct' })
  {
    const r = createSettingToggleRow({
      label: '종목 상승률 매수차단',
      infoText: '종목 상승률이 이 값 이상이면 매수를 차단합니다. 0~100%',
      toggleOn: true,
      onToggle: next => { vals.buy_block_rise_on = next; saveHelper!.saveImmediate({ buy_block_rise_on: next }) },
      disableControlsOnToggle: true,
      controls: [riseInput.el],
    })
    riseToggle = r.toggle; riseControls = r.controls
    root.appendChild(r.el)
  }

  // 하락률 제한 (토글 + 입력) — 음수 규약 (후안 B: 하락/손실은 음수)
  fallInput = createNumInput({ value: 0, onChange: v => { const orig = Number(vals.buy_block_fall_pct); vals.buy_block_fall_pct = v; saveHelper!.autoSave('buy_block_fall_pct', v, () => { vals.buy_block_fall_pct = orig; fallInput!.setValue(orig) }) }, step: 1, min: -100, max: 0, suffix: '%', name: 'buy_block_fall_pct' })
  {
    const r = createSettingToggleRow({
      label: '종목 하락률 매수차단',
      infoText: '종목 하락률이 이 값 이하이면 매수를 차단합니다. -100%~0%, 기본 -7%',
      toggleOn: true,
      onToggle: next => { vals.buy_block_fall_on = next; saveHelper!.saveImmediate({ buy_block_fall_on: next }) },
      disableControlsOnToggle: true,
      controls: [fallInput.el],
    })
    fallToggle = r.toggle; fallControls = r.controls
    root.appendChild(r.el)
  }
}

function buildBoostSection(root: HTMLElement): void {
  root.appendChild(sectionTitle('매수 가산점 (+N)'))

  // --- 5거래일 고가 돌파 ---
  {
    boostHighScoreInput = createNumInput({ value: 1.0, onChange: v => { const orig = Number(vals.boost_high_breakout_score); vals.boost_high_breakout_score = v; saveHelper!.autoSave('boost_high_breakout_score', v, () => { vals.boost_high_breakout_score = orig; boostHighScoreInput!.setValue(orig) }) }, step: 1, min: 0, max: 100, suffix: '점', name: 'boost_high_breakout_score' })
    const r = createSettingToggleRow({
      label: '5거래일 고가 돌파',
      infoText: '5거래일 고가 돌파 시 매수 점수 가산. 0~100점',
      toggleOn: false,
      onToggle: next => { vals.boost_high_breakout_on = next; saveHelper!.saveImmediate({ boost_high_breakout_on: next }) },
      disableControlsOnToggle: true,
      controls: [boostHighScoreInput.el],
    })
    boostHighToggle = r.toggle; boostHighControls = r.controls
    root.appendChild(r.el)
  }

  // --- 뉴스 호재 ---
  {
    boostNewsScoreInput = createNumInput({ value: 1.0, onChange: v => { const orig = Number(vals.boost_news_score); vals.boost_news_score = v; saveHelper!.autoSave('boost_news_score', v, () => { vals.boost_news_score = orig; boostNewsScoreInput!.setValue(orig) }) }, step: 1, min: 0, max: 100, suffix: '점', name: 'boost_news_score' })
    const r = createSettingToggleRow({
      label: '뉴스 호재',
      icon: 'newspaper',
      infoText: '뉴스 호재 감지 시 매수 점수 가산. 0~100점',
      toggleOn: false,
      onToggle: next => { vals.boost_news_on = next; saveHelper!.saveImmediate({ boost_news_on: next }) },
      disableControlsOnToggle: true,
      controls: [boostNewsScoreInput.el],
    })
    boostNewsToggle = r.toggle; boostNewsControls = r.controls
    root.appendChild(r.el)
  }

  // --- 프로그램 순매수 ---
  {
    boostProgramScoreInput = createNumInput({ value: 1.0, onChange: v => { const orig = Number(vals.boost_program_net_buy_score); vals.boost_program_net_buy_score = v; saveHelper!.autoSave('boost_program_net_buy_score', v, () => { vals.boost_program_net_buy_score = orig; boostProgramScoreInput!.setValue(orig) }) }, step: 1, min: 0, max: 100, suffix: '점', name: 'boost_program_net_buy_score' })
    const r = createSettingToggleRow({
      label: '프로그램 순매수',
      infoText: '프로그램 순매수 발생 시 매수 점수 가산. 0~100점',
      toggleOn: false,
      onToggle: next => { vals.boost_program_net_buy_on = next; saveHelper!.saveImmediate({ boost_program_net_buy_on: next }) },
      disableControlsOnToggle: true,
      controls: [boostProgramScoreInput.el],
    })
    boostProgramToggle = r.toggle; boostProgramControls = r.controls
    root.appendChild(r.el)
  }

  // --- 매수/매도호가 잔량비율 ---
  buildBoostOrderBlock(root)
}

function buildBoostOrderBlock(root: HTMLElement): void {
  const block = document.createElement('div')
  block.style.borderBottom = '1px solid ' + COLOR.borderLight

  // Row 2: dual label slider (먼저 생성 — extraDisableTargets로 전달)
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
      const orig = Number(vals.boost_order_ratio_pct)
      vals.boost_order_ratio_pct = v - 100
      saveHelper!.autoSave('boost_order_ratio_pct', v - 100, () => { vals.boost_order_ratio_pct = orig; boostOrderDualSlider?.setValue(orig + 100) })
    },
  })

  const row2 = document.createElement('div')
  Object.assign(row2.style, { padding: '0 0 6px' })
  row2.appendChild(boostOrderDualSlider.el)
  boostOrderRow2 = row2

  // Row 1: toggle + label | 가산점 + input
  boostOrderScoreInput = createNumInput({ value: 1.0, onChange: v => { const orig = Number(vals.boost_order_ratio_score); vals.boost_order_ratio_score = v; saveHelper!.autoSave('boost_order_ratio_score', v, () => { vals.boost_order_ratio_score = orig; boostOrderScoreInput!.setValue(orig) }) }, step: 1, min: 0, max: 100, suffix: '점', name: 'boost_order_ratio_score' })
  const r = createSettingToggleRow({
    label: '매수/매도호가 잔량비율',
    infoText: '호가 잔량비율 조건 충족 시 매수 점수 가산. 0~100점',
    toggleOn: false,
    onToggle: next => { vals.boost_order_ratio_on = next; saveHelper!.saveImmediate({ boost_order_ratio_on: next }) },
    disableControlsOnToggle: true,
    controls: [boostOrderScoreInput.el],
    extraDisableTargets: [row2],
    rowStyle: { borderBottom: 'none' },
  })
  boostOrderToggle = r.toggle; boostOrderControls = r.controls

  block.appendChild(r.el)
  block.appendChild(row2)
  root.appendChild(block)
}

function buildBuyAmountSection(root: HTMLElement): void {
  root.appendChild(sectionTitle('매수 금액 한도'))

  // 매수 주문 유형 (시장가 고정)
  root.appendChild(createSettingRow('매수 주문 유형', createFixedValue('시장가')))

  // 일일 최대 매수 금액 (토글 + 금액 입력)
  maxDailyInput = createMoneyInput({ value: 0, onChange: v => { const orig = Number(vals.max_daily_total_buy_amt); vals.max_daily_total_buy_amt = v; saveHelper!.autoSave('max_daily_total_buy_amt', v, () => { vals.max_daily_total_buy_amt = orig; maxDailyInput!.setValue(orig) }) }, min: 0, max: 1_000_000_000, unit: 'manwon', name: 'max_daily_total_buy_amt' })
  {
    const r = createSettingToggleRow({
      label: '전체 일일 한도',
      infoText: '전체 일일 누적 한도. 수수료 포함. OFF 시 제한 없음.',
      toggleOn: false,
      onToggle: next => { vals.max_daily_total_buy_on = next; saveHelper!.saveImmediate({ max_daily_total_buy_on: next }) },
      disableControlsOnToggle: true,
      controls: [maxDailyInput.el],
    })
    maxDailyToggle = r.toggle; maxDailyControls = r.controls
    root.appendChild(r.el)
  }

  // 최대 동시 보유 종목 수 (토글 + 입력)
  maxStockCntInput = createNumInput({ value: 0, onChange: v => { const orig = Number(vals.max_stock_cnt); vals.max_stock_cnt = v; saveHelper!.autoSave('max_stock_cnt', v, () => { vals.max_stock_cnt = orig; maxStockCntInput!.setValue(orig) }) }, min: 0, max: 100, suffix: '개', name: 'max_stock_cnt' })
  {
    const r = createSettingToggleRow({
      label: '최대 동시 보유종목수',
      infoText: '동시 보유 최대 종목 수. 0~100개',
      toggleOn: true,
      onToggle: next => { vals.max_stock_cnt_on = next; saveHelper!.saveImmediate({ max_stock_cnt_on: next }) },
      disableControlsOnToggle: true,
      controls: [maxStockCntInput.el],
    })
    maxStockCntToggle = r.toggle; maxStockCntControls = r.controls
    root.appendChild(r.el)
  }
}

function buildRebuySection(root: HTMLElement): void {
  root.appendChild(sectionTitle('동일 종목 재매수 제어'))

  // 종목당 1회 매수 금액 (토글 + 입력)
  buyAmtInput = createMoneyInput({ value: 0, onChange: v => { const orig = Number(vals.buy_amt); vals.buy_amt = v; saveHelper!.autoSave('buy_amt', v, () => { vals.buy_amt = orig; buyAmtInput!.setValue(orig) }) }, min: 0, max: 1_000_000_000, unit: 'manwon', name: 'buy_amt' })
  {
    const r = createSettingToggleRow({
      label: '종목당 1회 매수금액',
      infoText: '1회 매수 시 금액. 수수료 포함. OFF 시 한도 없음, 주문가능금액 전체로 매수 시도. 같은 종목 재매수는 "재매수 차단" 설정이 담당.',
      toggleOn: true,
      onToggle: next => { vals.buy_amt_on = next; saveHelper!.saveImmediate({ buy_amt_on: next }) },
      disableControlsOnToggle: true,
      controls: [buyAmtInput.el],
    })
    buyAmtToggle = r.toggle; buyAmtControls = r.controls
    root.appendChild(r.el)
  }

  // 재매수 차단 ON/OFF + 차단 기간 select
  {
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
    const r = createSettingToggleRow({
      label: '재매수 차단',
      infoText: '매도 후 같은 종목 재매수를 지정 기간 동안 차단.',
      toggleOn: true,
      onToggle: next => { vals.rebuy_block_on = next; saveHelper!.saveImmediate({ rebuy_block_on: next }) },
      disableControlsOnToggle: true,
      controls: [rebuyBlockSelect.el],
    })
    rebuyBlockToggle = r.toggle; rebuyBlockControls = r.controls
    root.appendChild(r.el)
  }
}

function buildBuyIntervalSection(root: HTMLElement): void {
  root.appendChild(sectionTitle('매수 주문 간격'))
  {
    buyIntervalInput = createNumInput({ value: 30, onChange: v => { const orig = Number(vals.buy_interval_sec); vals.buy_interval_sec = v; saveHelper!.autoSave('buy_interval_sec', v, () => { vals.buy_interval_sec = orig; buyIntervalInput!.setValue(orig) }) }, step: 1, min: 1, max: 300, suffix: '초', name: 'buy_interval_sec' })
    const r = createSettingToggleRow({
      label: '주문 간격',
      infoText: '매수 주문 사이 대기 시간. 1초 단위, 1~300초, 기본 30초',
      toggleOn: false,
      onToggle: next => { vals.buy_interval_on = next; saveHelper!.saveImmediate({ buy_interval_on: next }) },
      disableControlsOnToggle: true,
      controls: [buyIntervalInput.el],
    })
    buyIntervalToggle = r.toggle; buyIntervalControls = r.controls
    root.appendChild(r.el)
  }
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  const ctx = initSettingsPage(syncFromSettings)
  settingsMgr = ctx.settingsMgr
  saveHelper = ctx.saveHelper
  vals = {}

  const root = document.createElement('div')

  root.appendChild(createCardTitle('매수설정'))
  buildBuyBlockSection(root)
  buildBoostSection(root)
  buildBuyAmountSection(root)
  buildRebuySection(root)
  buildBuyIntervalSection(root)

  container.appendChild(root)

  // 초기 설정 동기화 + 구독
  unsubSettings = startSettingsSubscription(settingsMgr, syncFromSettings)
}

/* ── unmount ── */
function unmount(): void {
  destroySettingsPage(unsubSettings, saveHelper, settingsMgr)
  unsubSettings = null; saveHelper = null; settingsMgr = null
  riseToggle = null; riseInput = null; riseControls = null
  fallToggle = null; fallInput = null; fallControls = null
  maxDailyToggle = null; maxDailyInput = null; maxDailyControls = null
  maxStockCntToggle = null; maxStockCntInput = null; maxStockCntControls = null
  buyAmtToggle = null; buyAmtInput = null; buyAmtControls = null
  boostHighToggle = null; boostHighScoreInput = null; boostHighControls = null
  boostOrderToggle = null
  if (boostOrderDualSlider && typeof boostOrderDualSlider.destroy === 'function') {
    boostOrderDualSlider.destroy()
  }
  boostOrderDualSlider = null
  boostOrderScoreInput = null; boostOrderControls = null; boostOrderRow2 = null
  boostProgramToggle = null; boostProgramScoreInput = null; boostProgramControls = null
  boostNewsToggle = null; boostNewsScoreInput = null; boostNewsControls = null
  rebuyBlockToggle = null; rebuyBlockSelect = null; rebuyBlockControls = null
  buyIntervalToggle = null; buyIntervalInput = null; buyIntervalControls = null
  vals = {}
}

export default { mount, unmount }