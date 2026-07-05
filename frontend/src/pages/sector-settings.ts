// frontend/src/pages/sector-settings.ts
// 업종순위 설정 패널 — Vanilla TS PageModule (설정 입력만 담당)

import { uiStore } from '../stores/uiStore'
import { createSettingsManager } from '../settings'
import { createAutoSaveHelper, type AutoSaveHelper } from '../utils/settings-save'
import { createSettingRow, createNumInput, createMoneyInput } from '../components/common/setting-row'
import { createDualLabelSlider } from '../components/common/create-slider'
import type { DualLabelSliderHandle } from '../components/common/create-slider'
import { toDisplayValue, toServerValue } from '../utils/sliderConvert'
import { FONT_SIZE, FONT_WEIGHT, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import type { AppSettings } from '../types'
import type { PageModule } from '../router'

const NUM_KEYS = ['sector_start_threshold_pct', 'sector_min_trade_amt', 'sector_min_rise_ratio_pct', 'sector_max_targets', 'sector_trim_trade_amt_pct', 'sector_trim_change_rate_pct'] as const

/* ── 헬퍼: 단계 라벨 ── */
function createStepLabel(num: string, text: string): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, { fontSize: FONT_SIZE.small, color: COLOR.disabled, marginBottom: '2px', display: 'flex', alignItems: 'center', gap: '4px' })
  const badge = document.createElement('span')
  Object.assign(badge.style, { color: COLOR.down, fontWeight: FONT_WEIGHT.normal })
  badge.textContent = num
  div.appendChild(badge)
  div.appendChild(document.createTextNode(text))
  return div
}

/* ── 모듈 상태 ── */
let settingsMgr: ReturnType<typeof createSettingsManager> | null = null
let autoSaveHelper: AutoSaveHelper | null = null
let unsubSettings: (() => void) | null = null
let unsubUiStore: (() => void) | null = null
let saving = false

// 입력 컴포넌트 참조
let thresholdInput: ReturnType<typeof createNumInput> | null = null
let minTradeAmtInput: ReturnType<typeof createMoneyInput> | null = null
let trimChangeRateInput: ReturnType<typeof createNumInput> | null = null
let trimTradeAmtInput: ReturnType<typeof createNumInput> | null = null
let minRiseRatioInput: ReturnType<typeof createNumInput> | null = null
let maxTargetsInput: ReturnType<typeof createNumInput> | null = null
let maxTargetsStatusEl: HTMLSpanElement | null = null
let dualSlider: DualLabelSliderHandle | null = null

// 현재 값 추적
let currentVals: Record<string, number> = {}
let currentRiseRatio = 50

async function onNumChange(key: string, value: number): Promise<void> {
  let v = value
  if (key === 'sector_max_targets') {
    if (v < 1) {
      v = 1
    }
  }
  currentVals[key] = v
  if (autoSaveHelper) {
    autoSaveHelper.autoSave(key, v)
  }
}

async function saveWeightsNow(ratio: number): Promise<void> {
  const serverWeights = { rise_ratio: toServerValue(100 - ratio), total_trade_amount: toServerValue(ratio) }
  if (autoSaveHelper) {
    await autoSaveHelper.saveImmediate({ sector_weights: serverWeights })
  }
}

function updateSliderUI(): void {
  if (dualSlider && !dualSlider.isInteracting && dualSlider.getValue() !== currentRiseRatio) {
    dualSlider.setValue(currentRiseRatio)
  }
}

function syncFromSettings(s: AppSettings): void {
  if (saving) return
  for (const k of NUM_KEYS) {
    const newValue = s[k];
    currentVals[k] = newValue !== undefined ? Number(newValue) : currentVals[k];
  }
  const w = s.sector_weights || {}
  const tradeAmtVal = w.total_trade_amount !== undefined ? Number(w.total_trade_amount) : 0.5
  currentRiseRatio = toDisplayValue(tradeAmtVal)
  const act = document.activeElement
  if (thresholdInput && (!act || !thresholdInput.el.contains(act))) thresholdInput.setValue(currentVals.sector_start_threshold_pct ?? 70)
  if (minTradeAmtInput && (!act || !minTradeAmtInput.el.contains(act))) minTradeAmtInput.setValue(currentVals.sector_min_trade_amt ?? 0)
  if (trimChangeRateInput && (!act || !trimChangeRateInput.el.contains(act))) trimChangeRateInput.setValue(currentVals.sector_trim_change_rate_pct ?? 0)
  if (trimTradeAmtInput && (!act || !trimTradeAmtInput.el.contains(act))) trimTradeAmtInput.setValue(currentVals.sector_trim_trade_amt_pct ?? 0)
  if (minRiseRatioInput && (!act || !minRiseRatioInput.el.contains(act))) minRiseRatioInput.setValue(currentVals.sector_min_rise_ratio_pct ?? 0)
  if (maxTargetsInput && (!act || !maxTargetsInput.el.contains(act))) maxTargetsInput.setValue(currentVals.sector_max_targets ?? 0)
  updateSliderUI()
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  settingsMgr = createSettingsManager(uiStore)
  autoSaveHelper = createAutoSaveHelper(settingsMgr)
  currentVals = {}
  currentRiseRatio = 50
  saving = false

  const root = document.createElement('div')

  root.appendChild(createCardTitle('업종순위 설정'))

  // ① 종목 필터
  root.appendChild(createStepLabel('①', '5일 평균 거래대금(N억) 이하 차단 필터링'))
  minTradeAmtInput = createMoneyInput({ value: 0, onChange: v => onNumChange('sector_min_trade_amt', v), step: 1, name: 'sector_min_trade_amt' })
  root.appendChild(createSettingRow('5일평균 최소 거래대금', minTradeAmtInput.el))

  // ② 업종순위
  root.appendChild(createStepLabel('②', '업종순위 : 필터링종목 실시간데이터 수신율(%N)후 계산'))
  thresholdInput = createNumInput({ value: 70, onChange: v => { onNumChange('sector_start_threshold_pct', v) }, step: 1, name: 'sector_start_threshold_pct' })

  const receiveRateSpan = document.createElement('span')
  Object.assign(receiveRateSpan.style, { fontSize: '12px', color: COLOR.down, marginLeft: '8px' })
  receiveRateSpan.textContent = '(현재: 0%)'

  const labelContainer = document.createElement('div')
  Object.assign(labelContainer.style, { display: 'flex', alignItems: 'center' })
  const labelText = document.createElement('span')
  labelText.textContent = '업종순위 계산 수신율'
  labelContainer.appendChild(labelText)
  labelContainer.appendChild(receiveRateSpan)

  const thresholdRow = createSettingRow(labelContainer, thresholdInput.el)
  thresholdRow.style.margin = '0 0 12px 0'
  root.appendChild(thresholdRow)

  // ③ 업종 컷오프
  root.appendChild(createStepLabel('③', '업종내 종목 상승비율(N%)이하 차단 필터링'))
  minRiseRatioInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_min_rise_ratio_pct', v), step: 1, name: 'sector_min_rise_ratio_pct' })
  root.appendChild(createSettingRow('업종내 종목 상승비율', minRiseRatioInput.el))

  // ④ 극단값 제외
  root.appendChild(createStepLabel('④', '상하위(N%) 종목 제외후 가중치 계산'))
  const trimRow = document.createElement('div')
  Object.assign(trimRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '6px 0', borderBottom: '1px solid #eee' })

  const leftCol = document.createElement('div')
  const leftLabel = document.createElement('div')
  Object.assign(leftLabel.style, { color: COLOR.code, marginBottom: '4px' })
  leftLabel.textContent = '상승률 상/하위'
  leftCol.appendChild(leftLabel)
  trimChangeRateInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_trim_change_rate_pct', v), step: 1, name: 'sector_trim_change_rate_pct' })
  leftCol.appendChild(trimChangeRateInput.el)

  const rightCol = document.createElement('div')
  rightCol.style.textAlign = 'right'
  const rightLabel = document.createElement('div')
  Object.assign(rightLabel.style, { color: COLOR.code, marginBottom: '4px' })
  rightLabel.textContent = '거래대금 상/하위'
  rightCol.appendChild(rightLabel)
  const rightInputWrap = document.createElement('div')
  Object.assign(rightInputWrap.style, { display: 'flex', justifyContent: 'flex-end' })
  trimTradeAmtInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_trim_trade_amt_pct', v), step: 1, name: 'sector_trim_trade_amt_pct' })
  rightInputWrap.appendChild(trimTradeAmtInput.el)
  rightCol.appendChild(rightInputWrap)

  trimRow.appendChild(leftCol)
  trimRow.appendChild(rightCol)
  root.appendChild(trimRow)

  // ⑤ 점수 가중치
  const weightLabel = createStepLabel('⑤', '')
  const weightDesc = document.createElement('span')
  Object.assign(weightDesc.style, { fontSize: FONT_SIZE.small, color: COLOR.secondary })
  weightDesc.textContent = '상승 종목 비율과 평균 거래대금의 점수 반영 비중을 조절합니다.'
  weightLabel.appendChild(weightDesc)
  root.appendChild(weightLabel)
  const weightWrap = document.createElement('div')
  Object.assign(weightWrap.style, { marginBottom: '8px', marginTop: '4px' })

  dualSlider = createDualLabelSlider({
    min: 0,
    max: 100,
    value: currentRiseRatio,
    step: 1,
    leftLabel: (v) => `상승 종목 비율 ${100 - v}%`,
    rightLabel: (v) => `평균 거래대금 ${v}%`,
    leftColor: COLOR.down,
    leftColorLight: COLOR.downLight,
    rightColor: COLOR.warning,
    rightColorLight: COLOR.warningLight,
    onChange(v) {
      currentRiseRatio = v
    },
    onCommit(v) {
      saveWeightsNow(v)
    },
  })
  weightWrap.appendChild(dualSlider.el)
  root.appendChild(weightWrap)

  // ⑥ 매수 대상
  root.appendChild(createStepLabel('⑥', '최대 매수 대상 업종수 설정'))
  maxTargetsInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_max_targets', v), step: 1, name: 'sector_max_targets' })

  const maxTargetsRow = document.createElement('div')
  Object.assign(maxTargetsRow.style, {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 0',
    borderBottom: '1px solid #eee',
  })

  const maxTargetsLabel = document.createElement('span')
  maxTargetsLabel.textContent = '매수대상 업종수'
  Object.assign(maxTargetsLabel.style, { flex: '1.5', color: COLOR.neutral, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap' })

  maxTargetsStatusEl = document.createElement('span')
  Object.assign(maxTargetsStatusEl.style, {
    flex: '1',
    fontSize: FONT_SIZE.label,
    color: COLOR.secondary,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    whiteSpace: 'nowrap',
  })

  const rightWrap = document.createElement('div')
  Object.assign(rightWrap.style, { flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' })
  rightWrap.appendChild(maxTargetsInput.el)

  maxTargetsRow.appendChild(maxTargetsLabel)
  maxTargetsRow.appendChild(maxTargetsStatusEl)
  maxTargetsRow.appendChild(rightWrap)
  root.appendChild(maxTargetsRow)

  container.appendChild(root)

  // 설정 초기 동기화
  const initialSettings = settingsMgr.getSettings()
  if (initialSettings) syncFromSettings(initialSettings)
  updateSliderUI()

  // 설정 변경 구독 — 사용자 입력에 의한 설정 동기화
  unsubSettings = settingsMgr.subscribe(() => {
    const s = settingsMgr?.getSettings()
    if (s) {
      syncFromSettings(s)
    }
  })

  // uiStore 구독 — 수신율 표시 갱신
  let prevReceiveRate = uiStore.getState().receiveRate
  unsubUiStore = uiStore.subscribe(() => {
    const uiState = uiStore.getState()
    if (uiState.receiveRate !== prevReceiveRate) {
      prevReceiveRate = uiState.receiveRate
      if (uiState.receiveRate) {
        receiveRateSpan.textContent = `(현재: ${uiState.receiveRate.pct.toFixed(1)}%)`
      }
    }
  })
}

/* ── unmount ── */
function unmount(): void {
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (autoSaveHelper) { autoSaveHelper.destroy(); autoSaveHelper = null }
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
  thresholdInput = null
  minTradeAmtInput = null
  trimChangeRateInput = null
  trimTradeAmtInput = null
  minRiseRatioInput = null
  maxTargetsInput = null
  maxTargetsStatusEl = null
  if (dualSlider && typeof dualSlider.destroy === 'function') {
    dualSlider.destroy()
  }
  dualSlider = null
  saving = false
}

/* ── 외부에서 maxTargetsStatusEl 갱신용 ── */
export function getMaxTargetsStatusEl(): HTMLSpanElement | null {
  return maxTargetsStatusEl
}

export default { mount, unmount } satisfies PageModule
