// frontend/src/pages/sector-settings.ts
// 업종순위 설정 패널 — Vanilla TS PageModule (설정 입력만 담당)

import { uiStore } from '../stores/uiStore'
import { hotStore } from '../stores/hotStore'
import { createSettingsManager } from '../settings'
import { createAutoSaveHelper, type AutoSaveHelper } from '../utils/settings-save'
import { createSettingRow, createNumInput, createMoneyInput } from '../components/common/setting-row'
import { createDualLabelSlider, type DualLabelSliderHandle } from '../components/common/create-slider'
import { createProgressBar, type ProgressBarHandle } from '../components/common/progress-bar'
import { createMarketCountRow, type MarketCountRowHandle } from '../components/common/market-count-row'
import { createDescText, createStepLabel } from '../components/common/settings-common'
import { FONT_SIZE, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import type { ReceiveRateEntry } from '../stores/uiStore'
import type { AppSettings } from '../types'
import type { PageModule } from '../router'

const NUM_KEYS = [
  'sector_start_threshold_pct', 'sector_min_trade_amt', 'sector_min_rise_ratio_pct', 'sector_max_targets',
  'sector_bonus_rise_ratio_slider', 'sector_bonus_relative_strength_slider', 'sector_bonus_trade_amount_slider',
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
let bonusRiseRatioSlider: DualLabelSliderHandle | null = null
let bonusRelativeStrengthSlider: DualLabelSliderHandle | null = null
let bonusTradeAmountSlider: DualLabelSliderHandle | null = null
let bonusRiseRatioInput: ReturnType<typeof createNumInput> | null = null
let bonusRelativeStrengthInput: ReturnType<typeof createNumInput> | null = null
let bonusTradeAmountInput: ReturnType<typeof createNumInput> | null = null
let maxScoreDisplayEl: HTMLSpanElement | null = null
let maxTargetsStatusEl: HTMLSpanElement | null = null
let maxTargetsSumEl: HTMLDivElement | null = null
let unsubHotStore: (() => void) | null = null
let krxProgressBar: ProgressBarHandle | null = null
let nxtProgressBar: ProgressBarHandle | null = null
let krxCountRow: MarketCountRowHandle | null = null
let nxtCountRow: MarketCountRowHandle | null = null
let krxRowEl: HTMLDivElement | null = null
let nxtRowEl: HTMLDivElement | null = null
let receiveStatusLabelEl: HTMLSpanElement | null = null

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

// 수신율 상태 라벨 갱신 — 임계치 대기/진행 중 (P21 투명성)
// 옵션 C (승인됨): NXT-only 구간은 NXT 수신률만 기준, 정규장은 KRX/NXT 양쪽 모두 임계값 도달(AND)
function _updateStatusLabel(
  rate: { krx: ReceiveRateEntry | null; nxt: ReceiveRateEntry | null } | null,
  threshold: number,
  marketPhase: { is_nxt_only?: boolean },
): void {
  if (!receiveStatusLabelEl) return
  const isNxtOnly = marketPhase.is_nxt_only === true
  const krxPct = rate?.krx?.pct ?? 0
  const nxtPct = rate?.nxt?.pct ?? 0
  const reached = isNxtOnly ? nxtPct >= threshold : (krxPct >= threshold && nxtPct >= threshold)
  receiveStatusLabelEl.textContent = reached ? '업종순위 계산 진행 중' : '업종순위 계산 대기 중'
  receiveStatusLabelEl.style.color = reached ? COLOR.success : COLOR.down
}

// 시간대별 KRX/NXT 활성/비활성 전환 (P21 투명성 — NXT-only 구간에서 KRX 비활성 명시)
function _applyMarketPhaseActive(marketPhase: { is_nxt_only?: boolean }): void {
  const isNxtOnly = marketPhase.is_nxt_only === true
  if (krxRowEl) krxRowEl.style.opacity = isNxtOnly ? '0.3' : '1'
  if (nxtRowEl) nxtRowEl.style.opacity = '1'
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
  if (bonusRiseRatioSlider && (!act || !bonusRiseRatioSlider.el.contains(act))) bonusRiseRatioSlider.setValue(currentVals.sector_bonus_rise_ratio_slider ?? 0)
  if (bonusRelativeStrengthSlider && (!act || !bonusRelativeStrengthSlider.el.contains(act))) bonusRelativeStrengthSlider.setValue(currentVals.sector_bonus_relative_strength_slider ?? 0)
  if (bonusTradeAmountSlider && (!act || !bonusTradeAmountSlider.el.contains(act))) bonusTradeAmountSlider.setValue(currentVals.sector_bonus_trade_amount_slider ?? 0)
  if (bonusRiseRatioInput && (!act || !bonusRiseRatioInput.el.contains(act))) bonusRiseRatioInput.setValue(currentVals.sector_bonus_rise_ratio_slider ?? 0)
  if (bonusRelativeStrengthInput && (!act || !bonusRelativeStrengthInput.el.contains(act))) bonusRelativeStrengthInput.setValue(currentVals.sector_bonus_relative_strength_slider ?? 0)
  if (bonusTradeAmountInput && (!act || !bonusTradeAmountInput.el.contains(act))) bonusTradeAmountInput.setValue(currentVals.sector_bonus_trade_amount_slider ?? 0)

  // 임계치 변경 시 진행률 바 마커 + 상태 라벨 갱신
  const threshold = currentVals.sector_start_threshold_pct ?? 70
  if (krxProgressBar) krxProgressBar.setThreshold(threshold)
  if (nxtProgressBar) nxtProgressBar.setThreshold(threshold)
  if (receiveStatusLabelEl) {
    const curRate = uiStore.getState().receiveRate
    const curPhase = uiStore.getState().marketPhase
    _updateStatusLabel(curRate, threshold, curPhase)
  }
}

/* ── 가산점 슬라이더 2행 레이아웃 (매수설정 슬라이더와 동일 패턴 — P23 일관성) ── */
function createBonusSliderRow(labelText: string, sliderEl: HTMLElement, numInputEl: HTMLElement): HTMLElement {
  const block = document.createElement('div')
  block.style.borderBottom = '1px solid ' + COLOR.borderLight

  // Row 1: 라벨 행 — 설명 라벨(좌) + 숫자 입력란(우) (매수설정 라벨 행과 동일 패턴)
  const labelRow = document.createElement('div')
  Object.assign(labelRow.style, {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 0',
  })
  const labelSpan = document.createElement('span')
  labelSpan.textContent = labelText
  labelSpan.style.color = COLOR.neutral
  labelRow.appendChild(labelSpan)
  labelRow.appendChild(numInputEl)
  block.appendChild(labelRow)

  // Row 2: 슬라이더 행 (전체 너비 — 매수설정 row2와 동일)
  const sliderRow = document.createElement('div')
  Object.assign(sliderRow.style, { padding: '0 0 6px' })
  sliderRow.appendChild(sliderEl)
  block.appendChild(sliderRow)

  return block
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

  const _initialRate = uiStore.getState().receiveRate
  const _initialThreshold = uiStore.getState().settings?.sector_start_threshold_pct ?? 70
  const _initialPhase = uiStore.getState().marketPhase

  // 1행: 임계치 설정 입력란 (라벨 명확화 — "수신율" → "임계치")
  const thresholdRow = createSettingRow('업종순위 계산 임계치', thresholdInput.el)
  thresholdRow.style.margin = '0'
  thresholdRow.style.borderBottom = 'none'
  root.appendChild(thresholdRow)

  // 2행: 상태 라벨 — P21 투명성 (KRX/NXT 분리 배지가 각 행에 표시되므로 상태 라벨만 단독)
  const statusRow = document.createElement('div')
  Object.assign(statusRow.style, {
    display: 'flex',
    alignItems: 'center',
    padding: '4px 0 2px 0',
  })

  receiveStatusLabelEl = document.createElement('span')
  Object.assign(receiveStatusLabelEl.style, {
    fontSize: FONT_SIZE.small,
    color: COLOR.down,
  })
  statusRow.appendChild(receiveStatusLabelEl)
  _updateStatusLabel(_initialRate, _initialThreshold, _initialPhase)
  root.appendChild(statusRow)

  // 3행/4행: KRX/NXT 분리 배지 + 진행 바 2인스턴스 (P21 투명성, P23 일관성 — createMarketCountRow 재사용)
  // createMarketCountRow: showKrx/showNxt 옵션으로 각 시장 세그먼트만 표시, updateCounts로 수신 종목수 갱신
  const progressWrap = document.createElement('div')
  Object.assign(progressWrap.style, {
    padding: '6px 0 6px 0',
    borderBottom: '1px solid ' + COLOR.borderLight,
    marginBottom: '12px',
  })

  // KRX 행: 배지(KRX: N종목) + 진행 바(% 표시)
  krxRowEl = document.createElement('div')
  Object.assign(krxRowEl.style, { display: 'flex', alignItems: 'center', gap: '10px', padding: '2px 0' })
  krxCountRow = createMarketCountRow({ showTotal: false, showKrx: true, showNxt: false, showKospi: false, showKosdaq: false })
  Object.assign(krxCountRow.el.style, { flexShrink: '0' })
  krxCountRow.updateCounts({ total: 0, krx: _initialRate?.krx?.received ?? 0, nxt: 0, kospi: 0, kosdaq: 0 })
  krxRowEl.appendChild(krxCountRow.el)
  krxProgressBar = createProgressBar(COLOR.down, { showPct: true, height: '10px' })
  krxProgressBar.el.style.flex = '1'
  krxProgressBar.setThreshold(_initialThreshold)
  krxProgressBar.setValue(_initialRate?.krx?.pct ?? 0)
  krxRowEl.appendChild(krxProgressBar.el)
  progressWrap.appendChild(krxRowEl)

  // NXT 행: 배지(NXT▲: N종목) + 진행 바(% 표시)
  nxtRowEl = document.createElement('div')
  Object.assign(nxtRowEl.style, { display: 'flex', alignItems: 'center', gap: '10px', padding: '2px 0' })
  nxtCountRow = createMarketCountRow({ showTotal: false, showKrx: false, showNxt: true, showKospi: false, showKosdaq: false })
  Object.assign(nxtCountRow.el.style, { flexShrink: '0' })
  nxtCountRow.updateCounts({ total: 0, krx: 0, nxt: _initialRate?.nxt?.received ?? 0, kospi: 0, kosdaq: 0 })
  nxtRowEl.appendChild(nxtCountRow.el)
  nxtProgressBar = createProgressBar(COLOR.down, { showPct: true, height: '10px' })
  nxtProgressBar.el.style.flex = '1'
  nxtProgressBar.setThreshold(_initialThreshold)
  nxtProgressBar.setValue(_initialRate?.nxt?.pct ?? 0)
  nxtRowEl.appendChild(nxtProgressBar.el)
  progressWrap.appendChild(nxtRowEl)

  _applyMarketPhaseActive(_initialPhase)
  root.appendChild(progressWrap)

  // ③ 업종 컷오프
  root.appendChild(createStepLabel('③', '업종 내 상승비율 이하 차단'))
  minRiseRatioInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_min_rise_ratio_pct', v), step: 1, name: 'sector_min_rise_ratio_pct' })
  root.appendChild(createSettingRow('업종내 종목 상승비율', minRiseRatioInput.el))

  // ④ 가산점 가중치 슬라이더 (상승비율·가중 순위 합·거래대금 3단계)
  root.appendChild(createStepLabel('④', '가산점 가중치 조절 (3단계)'))

  // 만점 자동 표시 — 업종 수 = 만점 (P21 투명성)
  maxScoreDisplayEl = document.createElement('span')
  Object.assign(maxScoreDisplayEl.style, { fontSize: FONT_SIZE.small, color: COLOR.down, marginLeft: '8px' })
  const _initialSectorCount = hotStore.getState().sectorScores.length
  maxScoreDisplayEl.textContent = _initialSectorCount > 0
    ? `(현재 만점 = ${_initialSectorCount}점, 업종 ${_initialSectorCount}개)`
    : '(업종 수에 따라 자동 설정)'
  const maxScoreLabel = document.createElement('div')
  Object.assign(maxScoreLabel.style, { display: 'flex', alignItems: 'center', marginBottom: '8px' })
  const maxScoreLabelText = document.createElement('span')
  maxScoreLabelText.textContent = '만점 = 업종 수 (자동)'
  Object.assign(maxScoreLabelText.style, { color: COLOR.neutral, fontSize: FONT_SIZE.small })
  maxScoreLabel.appendChild(maxScoreLabelText)
  maxScoreLabel.appendChild(maxScoreDisplayEl)
  root.appendChild(maxScoreLabel)

  // 1차 가산점 — 업종 내 상승 종목 비율 (슬라이더-입력란 양방향 연동)
  bonusRiseRatioInput = createNumInput({ value: 0, min: -100, max: 100, onChange: v => { bonusRiseRatioSlider?.setValue(v); onNumChange('sector_bonus_rise_ratio_slider', v) }, step: 1, name: 'sector_bonus_rise_ratio_slider' })
  bonusRiseRatioSlider = createDualLabelSlider({
    min: -100, max: 100, value: 0, step: 1,
    leftLabel: v => v < 0 ? `${v}%` : '0%',
    rightLabel: v => v > 0 ? `+${v}%` : '0%',
    leftColor: COLOR.down,
    leftColorLight: COLOR.downLight,
    rightColor: COLOR.up,
    rightColorLight: COLOR.upLight,
    onChange: v => { bonusRiseRatioInput?.setValue(v); onNumChange('sector_bonus_rise_ratio_slider', v) },
  })
  root.appendChild(createBonusSliderRow('1차 가산점 — 업종 내 상승 종목 비율', bonusRiseRatioSlider.el, bonusRiseRatioInput.el))

  // 2차 가산점 — 종목 상승률 상위 집중도 (슬라이더-입력란 양방향 연동)
  bonusRelativeStrengthInput = createNumInput({ value: 0, min: -100, max: 100, onChange: v => { bonusRelativeStrengthSlider?.setValue(v); onNumChange('sector_bonus_relative_strength_slider', v) }, step: 1, name: 'sector_bonus_relative_strength_slider' })
  bonusRelativeStrengthSlider = createDualLabelSlider({
    min: -100, max: 100, value: 0, step: 1,
    leftLabel: v => v < 0 ? `${v}%` : '0%',
    rightLabel: v => v > 0 ? `+${v}%` : '0%',
    leftColor: COLOR.down,
    leftColorLight: COLOR.downLight,
    rightColor: COLOR.up,
    rightColorLight: COLOR.upLight,
    onChange: v => { bonusRelativeStrengthInput?.setValue(v); onNumChange('sector_bonus_relative_strength_slider', v) },
  })
  root.appendChild(createBonusSliderRow('2차 가산점 — 종목 상승률 상위 집중도', bonusRelativeStrengthSlider.el, bonusRelativeStrengthInput.el))

  // 3차 가산점 — 업종 평균 거래대금 (슬라이더-입력란 양방향 연동)
  bonusTradeAmountInput = createNumInput({ value: 0, min: -100, max: 100, onChange: v => { bonusTradeAmountSlider?.setValue(v); onNumChange('sector_bonus_trade_amount_slider', v) }, step: 1, name: 'sector_bonus_trade_amount_slider' })
  bonusTradeAmountSlider = createDualLabelSlider({
    min: -100, max: 100, value: 0, step: 1,
    leftLabel: v => v < 0 ? `${v}%` : '0%',
    rightLabel: v => v > 0 ? `+${v}%` : '0%',
    leftColor: COLOR.down,
    leftColorLight: COLOR.downLight,
    rightColor: COLOR.up,
    rightColorLight: COLOR.upLight,
    onChange: v => { bonusTradeAmountInput?.setValue(v); onNumChange('sector_bonus_trade_amount_slider', v) },
  })
  root.appendChild(createBonusSliderRow('3차 가산점 — 업종 평균 거래대금', bonusTradeAmountSlider.el, bonusTradeAmountInput.el))

  const bonusDescWrap = document.createElement('div')
  Object.assign(bonusDescWrap.style, {
    borderBottom: '1px solid ' + COLOR.borderLight,
    marginBottom: '12px',
  })
  bonusDescWrap.appendChild(createDescText('슬라이더 -100%~+100%: 조정 만점 = 업종 수 × (1 + 슬라이더/100)', { marginTop: '8px' }))
  bonusDescWrap.appendChild(createDescText('1위 = 조정 만점, 2위 = 조정 만점 - 1, ... 0점까지 1점씩 차감'))
  bonusDescWrap.appendChild(createDescText('종합 점수 = 1차 + 2차 + 3차'))
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

  // uiStore 구독 — 수신율 표시 갱신 (KRX/NXT 분리 진행 바 + 카운트 + 라벨 + 시간대별 활성/비활성)
  let prevReceiveRate = uiStore.getState().receiveRate
  let prevMarketPhase = uiStore.getState().marketPhase
  unsubUiStore = uiStore.subscribe(() => {
    const uiState = uiStore.getState()
    const rateChanged = uiState.receiveRate !== prevReceiveRate
    const phaseChanged = uiState.marketPhase !== prevMarketPhase
    if (!rateChanged && !phaseChanged) return
    prevReceiveRate = uiState.receiveRate
    prevMarketPhase = uiState.marketPhase
    const rate = uiState.receiveRate
    const threshold = currentVals.sector_start_threshold_pct ?? 70
    const phase = uiState.marketPhase
    // KRX/NXT 진행 바 + 카운트 갱신
    krxProgressBar?.setValue(rate?.krx?.pct ?? 0)
    nxtProgressBar?.setValue(rate?.nxt?.pct ?? 0)
    krxCountRow?.updateCounts({ total: 0, krx: rate?.krx?.received ?? 0, nxt: 0, kospi: 0, kosdaq: 0 })
    nxtCountRow?.updateCounts({ total: 0, krx: 0, nxt: rate?.nxt?.received ?? 0, kospi: 0, kosdaq: 0 })
    // 시간대별 활성/비활성 + 상태 라벨
    _applyMarketPhaseActive(phase)
    _updateStatusLabel(rate, threshold, phase)
  })

  // hotStore 구독 — 만점 자동 표시 갱신 (업종 수 = 만점)
  let prevSectorCount = hotStore.getState().sectorScores.length
  unsubHotStore = hotStore.subscribe(() => {
    const sectorCount = hotStore.getState().sectorScores.length
    if (sectorCount !== prevSectorCount) {
      prevSectorCount = sectorCount
      if (maxScoreDisplayEl) {
        maxScoreDisplayEl.textContent = sectorCount > 0
          ? `(현재 만점 = ${sectorCount}점, 업종 ${sectorCount}개)`
          : '(업종 수에 따라 자동 설정)'
      }
    }
  })
}

/* ── unmount ── */
function unmount(): void {
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (unsubHotStore) { unsubHotStore(); unsubHotStore = null }
  if (autoSaveHelper) { autoSaveHelper.destroy(); autoSaveHelper = null }
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
  thresholdInput = null
  minTradeAmtInput = null
  minRiseRatioInput = null
  maxTargetsInput = null
  bonusRiseRatioSlider = null
  bonusRelativeStrengthSlider = null
  bonusTradeAmountSlider = null
  bonusRiseRatioInput = null
  bonusRelativeStrengthInput = null
  bonusTradeAmountInput = null
  maxScoreDisplayEl = null
  maxTargetsStatusEl = null
  maxTargetsSumEl = null
  krxProgressBar = null
  nxtProgressBar = null
  krxCountRow = null
  nxtCountRow = null
  krxRowEl = null
  nxtRowEl = null
  receiveStatusLabelEl = null
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
