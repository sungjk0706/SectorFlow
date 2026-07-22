// frontend/src/pages/sector-settings.ts
// 업종순위 설정 패널 — Vanilla TS PageModule (설정 입력만 담당)

import { uiStore } from '../stores/uiStore'
import { hotStore } from '../stores/hotStore'
import { type SettingsManager } from '../settings'
import { initSettingsPage, startSettingsSubscription, destroySettingsPage } from '../utils/settings-page'
import type { AutoSaveHelper } from '../utils/settings-save'
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
let settingsMgr: SettingsManager | null = null
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
let maxScoreDetailEl: HTMLSpanElement | null = null
let maxScoreTotalEl: HTMLSpanElement | null = null
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

// 가산점 만점 표시 갱신 — 1차/2차/3차 각각 + 합계 (P21 투명성, P10 SSOT — 백엔드 sector_score.py 계산식과 동일)
// 조정 만점 = 업종 수 × (1 + 슬라이더/100). 슬라이더/업종 수 변경 시 호출.
// 표시 형식: (1차: N점 | 2차: N점 | 3차: N점) — 작게, 합계: N점 (업종 N개) — 크고 진하게.
function _formatScore(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}
function _updateMaxScoreDisplay(): void {
  if (!maxScoreDisplayEl) return
  const n = hotStore.getState().sectorScores.length
  if (n <= 0) {
    maxScoreDetailEl!.textContent = '(업종 수에 따라 자동 설정)'
    maxScoreDetailEl!.style.display = 'inline'
    maxScoreTotalEl!.style.display = 'none'
    return
  }
  const riseSlider = currentVals.sector_bonus_rise_ratio_slider ?? 0
  const relSlider = currentVals.sector_bonus_relative_strength_slider ?? 0
  const tradeSlider = currentVals.sector_bonus_trade_amount_slider ?? 0
  const max1 = n * (1 + riseSlider / 100)
  const max2 = n * (1 + relSlider / 100)
  const max3 = n * (1 + tradeSlider / 100)
  const total = max1 + max2 + max3
  maxScoreDetailEl!.textContent = `(1차: ${_formatScore(max1)}점 | 2차: ${_formatScore(max2)}점 | 3차: ${_formatScore(max3)}점)`
  maxScoreDetailEl!.style.display = 'inline'
  maxScoreTotalEl!.textContent = `합계: ${_formatScore(total)}점 (업종 ${n}개)`
  maxScoreTotalEl!.style.display = 'inline'
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

// 정규장 phase 문자열 집합 (구독 시점 기준 08:59~15:20 — 시가 동시호가 포함)
// header.ts PHASE_STYLE의 "거래 가능(초록)" 그룹 중 "정규장 모드"에 해당하는 phase만 포함.
// 시간외/NXT 전용 phase('장전 시간외', '장후 시간외', '프리마켓', '애프터마켓',
// '시간외 종가매매 종료 + 시간외 단일가매매 개시')는 is_nxt_only 플래그로 우선 분리되므로 제외.
// ⚠️ 동기화 주의: header.ts PHASE_STYLE에 신규 "정규장 모드" phase 추가 시 본 집합도 갱신 필요 (P10/P23).
const REGULAR_PHASES = new Set(['정규장', '시가 동시호가', '종가 동시호가', '메인마켓'])

// 시간대별 KRX/NXT 수신률 바 표시/숨김 (P21 투명성 — 3상태: NXT 전용/정규장/그 외)
// 구독 신청/해지 시점 기준:
//   1) NXT 전용 (07:59~08:59, 15:20~20:00): KRX 숨김, NXT 표시
//   2) 정규장 (08:59~15:20): KRX/NXT 둘 다 표시
//   3) 그 외 (20:00~07:59): KRX/NXT 둘 다 숨김
// 판정 순서: is_nxt_only 우선 → false일 때만 REGULAR_PHASES로 정규장 여부 판단.
function _applyMarketPhaseActive(marketPhase: {
  is_nxt_only?: boolean
  krx: string
  nxt: string
}): void {
  const isNxtOnly = marketPhase.is_nxt_only === true
  const isRegular = REGULAR_PHASES.has(marketPhase.krx) || REGULAR_PHASES.has(marketPhase.nxt)
  if (krxRowEl) krxRowEl.style.display = isNxtOnly ? 'none' : (isRegular ? 'flex' : 'none')
  if (nxtRowEl) nxtRowEl.style.display = (isNxtOnly || isRegular) ? 'flex' : 'none'
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
  // 가산점 만점 표시 갱신 — 슬라이더 값 동기화 후 (P21 투명성)
  _updateMaxScoreDisplay()
}

/* ── 가산점 슬라이더 블록 (슬라이더+입력란 양방향 연동 + 2행 레이아웃, 매수설정과 동일 패턴 — P23 일관성/P24 중복 제거) ── */
// 3개 가산점(1차/2차/3차) 슬라이더 설정이 완전 동일하므로 단일 헬퍼로 통합.
function createBonusSliderBlock(key: string, label: string): {
  input: ReturnType<typeof createNumInput>
  slider: DualLabelSliderHandle
  row: HTMLElement
} {
  let slider: DualLabelSliderHandle | null = null
  const input = createNumInput({
    value: 0, min: -100, max: 100, step: 1, name: key,
    onChange: v => { slider?.setValue(v); onNumChange(key, v); _updateMaxScoreDisplay() },
  })
  slider = createDualLabelSlider({
    min: -100, max: 100, value: 0, step: 1,
    leftLabel: v => v < 0 ? `${v}%` : '0%',
    rightLabel: v => v > 0 ? `+${v}%` : '0%',
    leftColor: COLOR.down,
    leftColorLight: COLOR.downLight,
    rightColor: COLOR.up,
    rightColorLight: COLOR.upLight,
    onChange: v => { input.setValue(v); onNumChange(key, v); _updateMaxScoreDisplay() },
  })
  // Row 1: 라벨(좌) + 숫자 입력란(우)
  const labelRow = document.createElement('div')
  Object.assign(labelRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0' })
  const labelSpan = document.createElement('span')
  labelSpan.textContent = label
  labelSpan.style.color = COLOR.neutral
  labelRow.appendChild(labelSpan)
  labelRow.appendChild(input.el)
  // Row 2: 슬라이더 (전체 너비)
  const sliderRow = document.createElement('div')
  Object.assign(sliderRow.style, { padding: '0 0 6px' })
  sliderRow.appendChild(slider.el)
  const block = document.createElement('div')
  block.style.borderBottom = '1px solid ' + COLOR.borderLight
  block.appendChild(labelRow)
  block.appendChild(sliderRow)
  return { input, slider, row: block }
}

/* ── mount 빌더 함수들 (F-04-c buy-settings.ts 패턴과 동일 — P23/P24) ── */

// ① 종목 필터 — 5일 평균 거래대금 이하 차단
function buildFilterSection(root: HTMLElement): void {
  root.appendChild(createStepLabel('①', '5일 평균 거래대금 이하 차단'))
  minTradeAmtInput = createMoneyInput({ value: 0, onChange: v => onNumChange('sector_min_trade_amt', v), step: 1, name: 'sector_min_trade_amt' })
  root.appendChild(createSettingRow('5일평균 최소 거래대금', minTradeAmtInput.el))
}

// ② 업종순위 — 임계치 입력 + 상태 라벨 (KRX/NXT 진행 바는 별도 섹션)
function buildThresholdSection(root: HTMLElement): void {
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
  Object.assign(statusRow.style, { display: 'flex', alignItems: 'center', padding: '4px 0 2px 0' })
  receiveStatusLabelEl = document.createElement('span')
  Object.assign(receiveStatusLabelEl.style, { fontSize: FONT_SIZE.small, color: COLOR.down })
  statusRow.appendChild(receiveStatusLabelEl)
  _updateStatusLabel(_initialRate, _initialThreshold, _initialPhase)
  root.appendChild(statusRow)
}

// ② KRX/NXT 분리 배지 + 진행 바 2인스턴스 (P21 투명성, P23 일관성 — createMarketCountRow 재사용)
function buildReceiveProgressSection(root: HTMLElement): void {
  const _initialRate = uiStore.getState().receiveRate
  const _initialThreshold = uiStore.getState().settings?.sector_start_threshold_pct ?? 70
  const _initialPhase = uiStore.getState().marketPhase

  const progressWrap = document.createElement('div')
  Object.assign(progressWrap.style, { padding: '6px 0 6px 0', borderBottom: '1px solid ' + COLOR.borderLight, marginBottom: '12px' })

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
}

// ③ 업종 컷오프 — 업종 내 상승비율 이하 차단
function buildCutoffSection(root: HTMLElement): void {
  root.appendChild(createStepLabel('③', '업종 내 상승비율 이하 차단'))
  minRiseRatioInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_min_rise_ratio_pct', v), step: 1, name: 'sector_min_rise_ratio_pct' })
  root.appendChild(createSettingRow('업종내 종목 상승비율', minRiseRatioInput.el))
}

// ④ 만점 자동 표시 — 1차/2차/3차 각각(작게) + 합계(크고 진하게) (P21 투명성, P10 SSOT — 백엔드 sector_score.py 계산식과 동일)
function buildMaxScoreDisplay(root: HTMLElement): void {
  root.appendChild(createStepLabel('④', '가산점 가중치 조절 (3단계)'))
  maxScoreDisplayEl = document.createElement('span')
  Object.assign(maxScoreDisplayEl.style, { marginLeft: '8px', display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' })
  maxScoreDetailEl = document.createElement('span')
  Object.assign(maxScoreDetailEl.style, { fontSize: FONT_SIZE.small, color: COLOR.tertiary })
  maxScoreTotalEl = document.createElement('span')
  Object.assign(maxScoreTotalEl.style, { fontSize: FONT_SIZE.label, color: COLOR.down, fontWeight: 'bold' })
  maxScoreDisplayEl.appendChild(maxScoreDetailEl)
  maxScoreDisplayEl.appendChild(maxScoreTotalEl)
  const maxScoreLabel = document.createElement('div')
  Object.assign(maxScoreLabel.style, { display: 'flex', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' })
  const maxScoreLabelText = document.createElement('span')
  maxScoreLabelText.textContent = '만점 = 업종 수 × (1 + 슬라이더/100)'
  Object.assign(maxScoreLabelText.style, { color: COLOR.neutral, fontSize: FONT_SIZE.small })
  maxScoreLabel.appendChild(maxScoreLabelText)
  maxScoreLabel.appendChild(maxScoreDisplayEl)
  root.appendChild(maxScoreLabel)
  // 초기 만점 표시 — currentVals 동기화 전이므로 슬라이더 기본값 0 기준
  _updateMaxScoreDisplay()
}

// ④ 가산점 슬라이더 3개 (createBonusSliderBlock 헬퍼 사용) + 설명
function buildBonusSection(root: HTMLElement): void {
  // 1차 가산점 — 업종 내 상승 종목 비율 (슬라이더-입력란 양방향 연동)
  const b1 = createBonusSliderBlock('sector_bonus_rise_ratio_slider', '1차 가산점 — 업종 내 상승 종목 비율')
  bonusRiseRatioInput = b1.input; bonusRiseRatioSlider = b1.slider; root.appendChild(b1.row)
  // 2차 가산점 — 종목 상승률 상위 집중도 (슬라이더-입력란 양방향 연동)
  const b2 = createBonusSliderBlock('sector_bonus_relative_strength_slider', '2차 가산점 — 종목 상승률 상위 집중도')
  bonusRelativeStrengthInput = b2.input; bonusRelativeStrengthSlider = b2.slider; root.appendChild(b2.row)
  // 3차 가산점 — 업종 평균 거래대금 (슬라이더-입력란 양방향 연동)
  const b3 = createBonusSliderBlock('sector_bonus_trade_amount_slider', '3차 가산점 — 업종 평균 거래대금')
  bonusTradeAmountInput = b3.input; bonusTradeAmountSlider = b3.slider; root.appendChild(b3.row)

  const bonusDescWrap = document.createElement('div')
  Object.assign(bonusDescWrap.style, { borderBottom: '1px solid ' + COLOR.borderLight, marginBottom: '12px' })
  bonusDescWrap.appendChild(createDescText('슬라이더 -100%~+100%: 조정 만점 = 업종 수 × (1 + 슬라이더/100)', { marginTop: '8px' }))
  bonusDescWrap.appendChild(createDescText('1위 = 조정 만점, 2위 = 조정 만점 - 1, ... 0점까지 1점씩 차감'))
  bonusDescWrap.appendChild(createDescText('종합 점수 = 1차 + 2차 + 3차'))
  root.appendChild(bonusDescWrap)
}

// ⑤ 매수 대상 — 최대 매수 대상 업종수 설정 + 상위 N 업종 종목 합계 보조 줄 (P21 투명성)
function buildMaxTargetsSection(root: HTMLElement): void {
  root.appendChild(createStepLabel('⑤', '최대 매수 대상 업종수 설정'))
  maxTargetsInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_max_targets', v), step: 1, name: 'sector_max_targets' })

  const maxTargetsRow = document.createElement('div')
  Object.assign(maxTargetsRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid ' + COLOR.borderLight })
  const maxTargetsLabel = document.createElement('span')
  maxTargetsLabel.textContent = '매수대상 업종수'
  Object.assign(maxTargetsLabel.style, { flex: '1.5', color: COLOR.neutral, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap' })
  maxTargetsStatusEl = document.createElement('span')
  Object.assign(maxTargetsStatusEl.style, { flex: '1', fontSize: FONT_SIZE.label, color: COLOR.tertiary, display: 'flex', alignItems: 'center', justifyContent: 'center', whiteSpace: 'nowrap' })
  const rightWrap = document.createElement('div')
  Object.assign(rightWrap.style, { flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' })
  rightWrap.appendChild(maxTargetsInput.el)
  maxTargetsRow.appendChild(maxTargetsLabel)
  maxTargetsRow.appendChild(maxTargetsStatusEl)
  maxTargetsRow.appendChild(rightWrap)
  root.appendChild(maxTargetsRow)

  // ⑤ 행 아래 보조 줄 — 상위 N 업종 종목 합계 (P21 투명성)
  maxTargetsSumEl = document.createElement('div')
  Object.assign(maxTargetsSumEl.style, { fontSize: FONT_SIZE.small, color: COLOR.tertiary, textAlign: 'right', marginTop: '4px', marginBottom: '6px', minHeight: '16px', padding: '4px 8px', background: COLOR.downBg, borderRadius: '6px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '4px' })
  root.appendChild(maxTargetsSumEl)
}

// uiStore 구독 — 수신율 표시 갱신 (KRX/NXT 분리 진행 바 + 카운트 + 라벨 + 시간대별 활성/비활성)
function startUiStoreSubscription(): () => void {
  let prevReceiveRate = uiStore.getState().receiveRate
  let prevMarketPhase = uiStore.getState().marketPhase
  return uiStore.subscribe(() => {
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
}

// hotStore 구독 — 만점 표시 갱신 (업종 수 변경 시 1차/2차/3차/합계 모두 자동 갱신, P21 투명성)
function startHotStoreSubscription(): () => void {
  let prevSectorCount = hotStore.getState().sectorScores.length
  return hotStore.subscribe(() => {
    const sectorCount = hotStore.getState().sectorScores.length
    if (sectorCount !== prevSectorCount) {
      prevSectorCount = sectorCount
      _updateMaxScoreDisplay()
    }
  })
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  const ctx = initSettingsPage(syncFromSettings)
  settingsMgr = ctx.settingsMgr
  autoSaveHelper = ctx.saveHelper
  currentVals = {}
  saving = false

  const root = document.createElement('div')
  root.appendChild(createCardTitle('업종순위 설정'))
  buildFilterSection(root)
  buildThresholdSection(root)
  buildReceiveProgressSection(root)
  buildCutoffSection(root)
  buildMaxScoreDisplay(root)
  buildBonusSection(root)
  buildMaxTargetsSection(root)
  container.appendChild(root)

  // 설정 동기화 + 구독 (표준 유틸 — settings-page.ts, P23 일관성)
  unsubSettings = startSettingsSubscription(settingsMgr, syncFromSettings)
  // 수신율/업종수 구독
  unsubUiStore = startUiStoreSubscription()
  unsubHotStore = startHotStoreSubscription()
}

/* ── unmount ── */
function unmount(): void {
  destroySettingsPage(unsubSettings, autoSaveHelper, settingsMgr)
  unsubSettings = null
  autoSaveHelper = null
  settingsMgr = null
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (unsubHotStore) { unsubHotStore(); unsubHotStore = null }
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
  maxScoreDetailEl = null
  maxScoreTotalEl = null
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
