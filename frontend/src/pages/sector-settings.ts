// frontend/src/pages/sector-settings.ts
// 업종순위 설정 패널 — Vanilla TS PageModule (설정 입력만 담당)

import { uiStore } from '../stores/uiStore'
import { createSettingsManager } from '../settings'
import { createAutoSaveHelper, type AutoSaveHelper } from '../utils/settings-save'
import { createSettingRow, createNumInput, createMoneyInput } from '../components/common/setting-row'
import { createDescText, createStepLabel } from '../components/common/settings-common'
import { FONT_SIZE, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import type { AppSettings } from '../types'
import type { PageModule } from '../router'

const NUM_KEYS = [
  'sector_start_threshold_pct', 'sector_min_trade_amt', 'sector_min_rise_ratio_pct', 'sector_max_targets',
  'sector_bonus_rise_ratio_max', 'sector_bonus_relative_strength_max', 'sector_bonus_trade_amount_max',
] as const

/* ── 모듈 상태 ── */
let settingsMgr: ReturnType<typeof createSettingsManager> | null = null
let autoSaveHelper: AutoSaveHelper | null = null
let unsubSettings: (() => void) | null = null
let unsubUiStore: (() => void) | null = null
let saving = false

// 입력 컴포넌트 참조
let thresholdInput: ReturnType<typeof createNumInput> | null = null
let minTradeAmtInput: ReturnType<typeof createMoneyInput> | null = null
let minRiseRatioInput: ReturnType<typeof createNumInput> | null = null
let maxTargetsInput: ReturnType<typeof createNumInput> | null = null
let bonusRiseRatioMaxInput: ReturnType<typeof createNumInput> | null = null
let bonusRelativeStrengthMaxInput: ReturnType<typeof createNumInput> | null = null
let bonusTradeAmountMaxInput: ReturnType<typeof createNumInput> | null = null
let maxTargetsStatusEl: HTMLSpanElement | null = null
let maxTargetsSumEl: HTMLDivElement | null = null

// 현재 값 추적
let currentVals: Record<string, number> = {}

async function onNumChange(key: string, value: number): Promise<void> {
  // sector_max_targets: 0은 "매수 대상 0개" (백엔드 buy_filter와 일치) — P20 폴백 금지
  const v = value
  currentVals[key] = v
  if (autoSaveHelper) {
    autoSaveHelper.autoSave(key, v)
  }
}

function syncFromSettings(s: AppSettings): void {
  if (saving) return
  for (const k of NUM_KEYS) {
    const newValue = s[k];
    currentVals[k] = newValue !== undefined ? Number(newValue) : currentVals[k];
  }
  const act = document.activeElement
  if (thresholdInput && (!act || !thresholdInput.el.contains(act))) thresholdInput.setValue(currentVals.sector_start_threshold_pct ?? 70)
  if (minTradeAmtInput && (!act || !minTradeAmtInput.el.contains(act))) minTradeAmtInput.setValue(currentVals.sector_min_trade_amt ?? 0)
  if (minRiseRatioInput && (!act || !minRiseRatioInput.el.contains(act))) minRiseRatioInput.setValue(currentVals.sector_min_rise_ratio_pct ?? 0)
  if (maxTargetsInput && (!act || !maxTargetsInput.el.contains(act))) maxTargetsInput.setValue(currentVals.sector_max_targets ?? 0)
  if (bonusRiseRatioMaxInput && (!act || !bonusRiseRatioMaxInput.el.contains(act))) bonusRiseRatioMaxInput.setValue(currentVals.sector_bonus_rise_ratio_max ?? 10)
  if (bonusRelativeStrengthMaxInput && (!act || !bonusRelativeStrengthMaxInput.el.contains(act))) bonusRelativeStrengthMaxInput.setValue(currentVals.sector_bonus_relative_strength_max ?? 7)
  if (bonusTradeAmountMaxInput && (!act || !bonusTradeAmountMaxInput.el.contains(act))) bonusTradeAmountMaxInput.setValue(currentVals.sector_bonus_trade_amount_max ?? 5)
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  settingsMgr = createSettingsManager(uiStore)
  autoSaveHelper = createAutoSaveHelper(settingsMgr)
  currentVals = {}
  saving = false

  const root = document.createElement('div')

  root.appendChild(createCardTitle('업종순위 설정'))

  // ① 종목 필터
  root.appendChild(createStepLabel('①', '5일 평균 거래대금 이하 차단'))
  minTradeAmtInput = createMoneyInput({ value: 0, onChange: v => onNumChange('sector_min_trade_amt', v), step: 1, name: 'sector_min_trade_amt' })
  root.appendChild(createSettingRow('5일평균 최소 거래대금', minTradeAmtInput.el))

  // ② 업종순위
  root.appendChild(createStepLabel('②', '업종순위: 수신율 기반 계산'))
  thresholdInput = createNumInput({ value: 70, onChange: v => { onNumChange('sector_start_threshold_pct', v) }, step: 1, name: 'sector_start_threshold_pct' })

  const receiveRateSpan = document.createElement('span')
  Object.assign(receiveRateSpan.style, { fontSize: '12px', color: COLOR.down, marginLeft: '8px' })
  const _initialRate = uiStore.getState().receiveRate
  receiveRateSpan.textContent = _initialRate
    ? `(현재: ${_initialRate.pct.toFixed(1)}%)`
    : '(현재: 0%)'

  const labelContainer = document.createElement('div')
  Object.assign(labelContainer.style, { display: 'flex', alignItems: 'center' })
  const labelText = document.createElement('span')
  labelText.textContent = '업종순위 계산 수신율'
  Object.assign(labelText.style, { color: COLOR.neutral })
  labelContainer.appendChild(labelText)
  labelContainer.appendChild(receiveRateSpan)

  const thresholdRow = createSettingRow(labelContainer, thresholdInput.el)
  thresholdRow.style.margin = '0'
  thresholdRow.style.borderBottom = 'none'
  root.appendChild(thresholdRow)

  // 수신/미수신 종목수 표시 행 — 정적 라벨(검정) + 동적 숫자(파랑) 분리
  const receiveCountRow = document.createElement('div')
  Object.assign(receiveCountRow.style, {
    fontSize: FONT_SIZE.small,
    color: COLOR.neutral,
    textAlign: 'right',
    padding: '2px 0 6px 0',
    borderBottom: '1px solid ' + COLOR.borderLight,
    marginBottom: '12px',
  })
  // 동적 숫자 span — 수신 종목수
  const receivedCountSpan = document.createElement('span')
  Object.assign(receivedCountSpan.style, { color: COLOR.down })
  // 동적 숫자 span — 미수신 종목수
  const missedCountSpan = document.createElement('span')
  Object.assign(missedCountSpan.style, { color: COLOR.down })

  function _fillReceiveCount(rate: { received: number; total: number }) {
    receivedCountSpan.textContent = `${rate.received}종목`
    missedCountSpan.textContent = `${rate.total - rate.received}종목`
  }

  if (_initialRate) {
    _fillReceiveCount(_initialRate)
    receiveCountRow.append('수신: ', receivedCountSpan, ' / 미수신: ', missedCountSpan)
  }
  root.appendChild(receiveCountRow)

  // ③ 업종 컷오프
  root.appendChild(createStepLabel('③', '업종 내 상승비율 이하 차단'))
  minRiseRatioInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_min_rise_ratio_pct', v), step: 1, name: 'sector_min_rise_ratio_pct' })
  root.appendChild(createSettingRow('업종내 종목 상승비율', minRiseRatioInput.el))

  // ④ 가산점 만점 설정 (상승비율·상대평가·거래대금 3단계 누적)
  root.appendChild(createStepLabel('④', '가산점 만점 설정 (3단계 누적)'))

  bonusRiseRatioMaxInput = createNumInput({ value: 10, onChange: v => onNumChange('sector_bonus_rise_ratio_max', v), step: 1, name: 'sector_bonus_rise_ratio_max' })
  root.appendChild(createSettingRow('1차 만점 (상승비율)', bonusRiseRatioMaxInput.el))

  bonusRelativeStrengthMaxInput = createNumInput({ value: 7, onChange: v => onNumChange('sector_bonus_relative_strength_max', v), step: 1, name: 'sector_bonus_relative_strength_max' })
  root.appendChild(createSettingRow('2차 만점 (상대평가)', bonusRelativeStrengthMaxInput.el))

  bonusTradeAmountMaxInput = createNumInput({ value: 5, onChange: v => onNumChange('sector_bonus_trade_amount_max', v), step: 1, name: 'sector_bonus_trade_amount_max' })
  root.appendChild(createSettingRow('3차 만점 (거래대금)', bonusTradeAmountMaxInput.el))

  const bonusDescWrap = document.createElement('div')
  Object.assign(bonusDescWrap.style, {
    borderBottom: '1px solid ' + COLOR.borderLight,
    marginBottom: '12px',
  })
  bonusDescWrap.appendChild(createDescText('1위 = 만점, 2위 = 만점-1, ... 0점까지 1점씩 차감', { marginTop: '8px' }))
  bonusDescWrap.appendChild(createDescText('종합 점수 = 1차 + 2차 + 3차 (0~만점 합)'))
  root.appendChild(bonusDescWrap)

  // ⑤ 매수 대상
  root.appendChild(createStepLabel('⑤', '최대 매수 대상 업종수 설정'))
  maxTargetsInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_max_targets', v), step: 1, name: 'sector_max_targets' })

  const maxTargetsRow = document.createElement('div')
  Object.assign(maxTargetsRow.style, {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 0',
    borderBottom: '1px solid ' + COLOR.borderLight,
  })

  const maxTargetsLabel = document.createElement('span')
  maxTargetsLabel.textContent = '매수대상 업종수'
  Object.assign(maxTargetsLabel.style, { flex: '1.5', color: COLOR.neutral, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap' })

  maxTargetsStatusEl = document.createElement('span')
  Object.assign(maxTargetsStatusEl.style, {
    flex: '1',
    fontSize: FONT_SIZE.label,
    color: COLOR.tertiary,
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

  // ⑤ 행 아래 보조 줄 — 상위 N 업종 종목 합계 (P21 투명성)
  maxTargetsSumEl = document.createElement('div')
  Object.assign(maxTargetsSumEl.style, {
    fontSize: FONT_SIZE.small,
    color: COLOR.tertiary,
    textAlign: 'right',
    marginTop: '4px',
    marginBottom: '6px',
    minHeight: '16px',
    padding: '4px 8px',
    background: COLOR.downBg,
    borderRadius: '6px',
    display: 'flex',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: '4px',
  })
  root.appendChild(maxTargetsSumEl)

  container.appendChild(root)

  // 설정 초기 동기화
  const initialSettings = settingsMgr.getSettings()
  if (initialSettings) syncFromSettings(initialSettings)

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
        // 최초 수신율이 없었을 경우 분리된 span 구성
        if (receiveCountRow.childElementCount === 0) {
          _fillReceiveCount(uiState.receiveRate)
          receiveCountRow.append('수신: ', receivedCountSpan, ' / 미수신: ', missedCountSpan)
        } else {
          _fillReceiveCount(uiState.receiveRate)
        }
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
  minRiseRatioInput = null
  maxTargetsInput = null
  bonusRiseRatioMaxInput = null
  bonusRelativeStrengthMaxInput = null
  bonusTradeAmountMaxInput = null
  maxTargetsStatusEl = null
  maxTargetsSumEl = null
  saving = false
}

/* ── 외부에서 maxTargetsStatusEl 갱신용 ── */
export function getMaxTargetsStatusEl(): HTMLSpanElement | null {
  return maxTargetsStatusEl
}

/* ── 외부에서 maxTargetsSumEl 갱신용 (상위 N 업종 종목 합계) ── */
export function getMaxTargetsSumEl(): HTMLDivElement | null {
  return maxTargetsSumEl
}

export default { mount, unmount } satisfies PageModule
