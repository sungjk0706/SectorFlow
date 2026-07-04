// frontend/src/pages/sector-ranking.ts
// 업종분석 페이지 — Vanilla TS PageModule (SectorAnalysisCard.tsx 1:1 전환)

import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { createSettingsManager } from '../settings'
import { createAutoSaveHelper, type AutoSaveHelper } from '../utils/settings-save'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingRow, createNumInput, createMoneyInput, createWsStatusBadge } from '../components/common/setting-row'
import { createDualLabelSlider } from '../components/common/create-slider'
import type { DualLabelSliderHandle } from '../components/common/create-slider'
import { toDisplayValue, toServerValue } from '../utils/sliderConvert'
import { FONT_SIZE, FONT_WEIGHT, COLOR } from '../components/common/ui-styles'
import type { SectorScoreRow, AppSettings } from '../types'

const NUM_KEYS = ['sector_start_threshold_pct', 'sector_min_trade_amt', 'sector_min_rise_ratio_pct', 'sector_max_targets', 'sector_trim_trade_amt_pct', 'sector_trim_change_rate_pct'] as const
const MAX_ROWS = 60

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

function updateMaxTargetsStatus(scores: SectorScoreRow[]): void {
  if (!maxTargetsStatusEl) return
  // 백엔드에서 이미 계산된 데이터를 그대로 사용 (Dumb Terminal)
  const passed = scores.filter(s => s.rank > 0).length

  while (maxTargetsStatusEl.firstChild) {
    maxTargetsStatusEl.removeChild(maxTargetsStatusEl.firstChild)
  }
  maxTargetsStatusEl.style.gap = '4px'

  const passedLabel = document.createElement('span')
  passedLabel.textContent = '통과'
  passedLabel.style.color = COLOR.up
  maxTargetsStatusEl.appendChild(passedLabel)

  const passedVal = document.createElement('span')
  passedVal.textContent = String(passed)
  passedVal.style.color = COLOR.up
  passedVal.style.fontWeight = FONT_WEIGHT.bold
  maxTargetsStatusEl.appendChild(passedVal)
}

/* ── mount / unmount ── */
let settingsMgr: ReturnType<typeof createSettingsManager> | null = null
let autoSaveHelper: AutoSaveHelper | null = null
let unsubStore: (() => void) | null = null
let unsubUiStore: (() => void) | null = null
let unsubSettings: (() => void) | null = null
let saving = false
let wsBadge: ReturnType<typeof createWsStatusBadge> | null = null
let rafHandle: number | null = null
let _mounted = false

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

// 업종 순위 행 DOM 참조
let rankRows: HTMLDivElement[] = []
// 행별 이전 렌더 값 캐시 (델타 갱신용)
interface RowCache {
  rank: number; sector: string; total: number; finalScore: string
  riseRatio: string; riseColor: string; tradeAmt: string
  barWidth: string; barColor: string; opacity: string; selected: boolean; visible: boolean
}
let rowCaches: (RowCache | null)[] = []

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
  // focus 뺏김 방지 — 현재 포커스된 input은 업데이트 제외
  const act = document.activeElement
  if (thresholdInput && (!act || !thresholdInput.el.contains(act))) thresholdInput.setValue(currentVals.sector_start_threshold_pct ?? 70)
  if (minTradeAmtInput && (!act || !minTradeAmtInput.el.contains(act))) minTradeAmtInput.setValue(currentVals.sector_min_trade_amt ?? 0)
  if (trimChangeRateInput && (!act || !trimChangeRateInput.el.contains(act))) trimChangeRateInput.setValue(currentVals.sector_trim_change_rate_pct ?? 0)
  if (trimTradeAmtInput && (!act || !trimTradeAmtInput.el.contains(act))) trimTradeAmtInput.setValue(currentVals.sector_trim_trade_amt_pct ?? 0)
  if (minRiseRatioInput && (!act || !minRiseRatioInput.el.contains(act))) minRiseRatioInput.setValue(currentVals.sector_min_rise_ratio_pct ?? 0)
  if (maxTargetsInput && (!act || !maxTargetsInput.el.contains(act))) maxTargetsInput.setValue(currentVals.sector_max_targets ?? 0)
  updateSliderUI()
}


/* ── 업종 순위 리스트 빌드 ── */
function buildRankingRows(container: HTMLElement): void {
  for (let i = 0; i < MAX_ROWS; i++) {
    const row = document.createElement('div')
    row.style.cssText = 'height:30px;overflow:hidden;margin-bottom:8px;cursor:pointer;border-radius:6px;padding:4px 2px;display:none;'

    const info = document.createElement('div')
    info.style.cssText = 'display:flex;align-items:center;margin-bottom:2px;padding:0 2px;'
    const defs = [
      'width:24px;text-align:right;color:' + COLOR.secondary + ';',
      'flex:1;font-weight:500;padding-left:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
      'width:40px;text-align:right;color:' + COLOR.down + ';margin-right:12px;',
      'width:48px;text-align:right;',
      'width:64px;text-align:right;',
      'width:72px;text-align:right;color:' + COLOR.tertiary + ';',
    ]
    for (const css of defs) {
      const sp = document.createElement('span')
      sp.style.cssText = css
      info.appendChild(sp)
    }
    row.appendChild(info)

    const barOuter = document.createElement('div')
    barOuter.style.cssText = 'height:5px;background:#eee;border-radius:3px;overflow:hidden;'
    const barInner = document.createElement('div')
    barInner.style.cssText = 'height:100%;border-radius:3px;width:0%;'
    barOuter.appendChild(barInner)
    row.appendChild(barOuter)

    row.addEventListener('click', () => {
      const sector = row.dataset.sector
      if (sector) {
        setSelectedSector(sector)
      }
    })

    container.appendChild(row)
    rankRows.push(row)
  }
}

function updateRankingRows(scores: SectorScoreRow[], selected: string | null, maxTargets: number, _delta: { delta: boolean; changed_sectors: string[]; removed_sectors: string[] } | null = null): void {
  // rank > 0 먼저 표시 (프론트엔드에서 표시 순서 결정)
  const sortedScores = [...scores].sort((a, b) => {
    if (a.rank === 0 && b.rank === 0) return b.final_score - a.final_score
    if (a.rank === 0) return 1
    if (b.rank === 0) return -1
    return b.final_score - a.final_score
  })
  
  const maxScore = sortedScores.length > 0 ? Math.max(...sortedScores.map(s => s.final_score), 1) : 1

  for (let i = 0; i < MAX_ROWS; i++) {
    const row = rankRows[i]
    if (!row) continue

    // 숨김 처리
    if (i >= sortedScores.length) {
      if (!rowCaches[i] || rowCaches[i]!.visible) {
        row.style.display = 'none'
        rowCaches[i] = { rank: -1, sector: '', total: 0, finalScore: '', riseRatio: '', riseColor: '', tradeAmt: '', barWidth: '', barColor: '', opacity: '', selected: false, visible: false }
      }
      continue
    }

    const s = sortedScores[i]
    const prev = rowCaches[i]
    const isSel = selected === s.sector
    const isUnranked = s.rank === 0
    const opacity = isUnranked ? '0.4' : (s.rank > maxTargets ? '0.65' : '1')
    const finalScore = s.final_score.toFixed(1)
    const riseRatio = s.rise_ratio.toFixed(1) + '%'
    const riseColor = s.rise_ratio > 50 ? COLOR.up : s.rise_ratio < 50 ? COLOR.down : COLOR.neutral
    const tradeAmt = (s.total_trade_amount / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })  // 백만원 → 억단위 (소수점 1자리, 콤마)
    const barWidth = `${Math.min((s.final_score / maxScore) * 100, 100)}%`
    const barColor = isUnranked ? '#dee2e6' : (s.rank <= maxTargets ? COLOR.down : COLOR.muted)

    if (!prev || !prev.visible) row.style.display = ''

    // 바뀐 속성만 DOM 반영
    if (!prev || prev.opacity !== opacity) row.style.opacity = opacity
    if (!prev || prev.sector !== s.sector) row.dataset.sector = s.sector
    if (!prev || prev.selected !== isSel) {
      row.style.background = isSel ? COLOR.downBg : 'transparent'
      row.style.outline = isSel ? '2px solid ' + COLOR.down : 'none'
    }

    const spans = Array.from(row.firstElementChild!.children) as HTMLSpanElement[]
    if (!prev || prev.rank !== s.rank) spans[0].textContent = s.rank === 0 ? '❌' : String(s.rank)
    if (!prev || prev.sector !== s.sector) spans[1].textContent = s.sector
    if (!prev || prev.total !== s.total) spans[2].textContent = String(s.total || '')
    if (!prev || prev.finalScore !== finalScore) spans[3].textContent = finalScore
    if (!prev || prev.riseRatio !== riseRatio) spans[4].textContent = riseRatio
    if (!prev || prev.riseColor !== riseColor) spans[4].style.color = riseColor
    if (!prev || prev.tradeAmt !== tradeAmt) spans[5].textContent = tradeAmt

    const bar = row.lastElementChild!.firstElementChild as HTMLDivElement
    if (!prev || prev.barWidth !== barWidth) bar.style.width = barWidth
    if (!prev || prev.barColor !== barColor) bar.style.background = barColor

    // 캐시 갱신
    rowCaches[i] = { rank: s.rank, sector: s.sector, total: s.total, finalScore, riseRatio, riseColor, tradeAmt, barWidth, barColor, opacity, selected: isSel, visible: true }
  }
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  notifyPageActive('sector-ranking')
  settingsMgr = createSettingsManager(uiStore)
  autoSaveHelper = createAutoSaveHelper(settingsMgr)
  currentVals = {}
  currentRiseRatio = 50
  rankRows = []
  rowCaches = []
  saving = false

  const root = document.createElement('div')

  // ① 종목 필터
  root.appendChild(createStepLabel('①', '5일 평균 거래대금(N억) 이하 차단 필터링'))
  minTradeAmtInput = createMoneyInput({ value: 0, onChange: v => onNumChange('sector_min_trade_amt', v), step: 1, name: 'sector_min_trade_amt' })
  root.appendChild(createSettingRow('5일평균 최소 거래대금', minTradeAmtInput.el))

  // ② 업종순위
  root.appendChild(createStepLabel('②', '업종순위 : 필터링종목 실시간데이터 수신율(%N)후 계산'))
  thresholdInput = createNumInput({ value: 70, onChange: v => { onNumChange('sector_start_threshold_pct', v) }, step: 1, name: 'sector_start_threshold_pct' })

  // 수신율 표시 요소
  const receiveRateSpan = document.createElement('span')
  Object.assign(receiveRateSpan.style, { fontSize: '12px', color: COLOR.down, marginLeft: '8px' })
  receiveRateSpan.textContent = '(현재: 0%)'

  // 레이블 컨테이너
  const labelContainer = document.createElement('div')
  Object.assign(labelContainer.style, { display: 'flex', alignItems: 'center' })
  const labelText = document.createElement('span')
  labelText.textContent = '업종순위 계산 수신율'
  labelContainer.appendChild(labelText)
  labelContainer.appendChild(receiveRateSpan)

  const thresholdRow = createSettingRow(labelContainer, thresholdInput.el)
  thresholdRow.style.margin = '0 0 12px 0'
  root.appendChild(thresholdRow)

  // 수신율 업데이트 함수 — 마지막 수신율을 항상 표시
  function updateReceiveRate(receiveRate: { received: number; total: number; pct: number } | null): void {
    if (receiveRate) {
      receiveRateSpan.textContent = `(현재: ${receiveRate.pct.toFixed(1)}%)`
    }
  }

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

  // ⑤ 매수 대상
  root.appendChild(createStepLabel('⑤', '최대 매수 대상 업종수 설정'))
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

  // 업종 순위 리스트
  const rankSection = document.createElement('div')
  Object.assign(rankSection.style, { marginTop: '16px', borderTop: '1px solid #eee', paddingTop: '12px' })

  // 헤더 행
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', fontSize: '11px', color: COLOR.secondary, marginBottom: '6px', padding: '0 2px' })
  const headerDefs: [string, string][] = [
    ['width:24px;text-align:right;', '순위'],
    ['flex:1;padding-left:6px;', '업종명'],
    ['width:40px;text-align:right;margin-right:12px;', '종목수'],
    ['width:48px;text-align:right;', '종합점수'],
    ['width:64px;text-align:right;', '상승비율'],
    ['width:72px;text-align:right;', '평균거래(억)'],
  ]
  for (const [css, text] of headerDefs) {
    const sp = document.createElement('span')
    sp.style.cssText = css
    sp.textContent = text
    headerRow.appendChild(sp)
  }
  rankSection.appendChild(headerRow)

  const rankContainer = document.createElement('div')
  buildRankingRows(rankContainer)
  rankSection.appendChild(rankContainer)
  root.appendChild(rankSection)

  container.appendChild(root)

  // 설정 초기 동기화
  const initialSettings = settingsMgr.getSettings()
  if (initialSettings) syncFromSettings(initialSettings)
  updateSliderUI()

  // 설정 변경 구독 — 사용자 입력에 의한 설정 동기화 + 순위 리스트 갱신
  unsubSettings = settingsMgr.subscribe(() => {
    const s = settingsMgr?.getSettings()
    if (s) {
      syncFromSettings(s)
      const state = hotStore.getState()
      const uiState = uiStore.getState()
      const maxTargets = Number(currentVals.sector_max_targets) || 1
      updateRankingRows(state.sectorScores, uiState.selectedSector, maxTargets, uiState.sectorScoresDelta)
    }
  })

  // hotStore/uiStore 구독 — sectorScores/selectedSector 변동 시 델타 갱신 (변경된 셀만 DOM 반영)
  {
    const initHot = hotStore.getState()
    const initUi = uiStore.getState()
    let prevSectorScores = initHot.sectorScores
    let prevSelectedSector = initUi.selectedSector
    let prevWsSubscribeStatus = initUi.wsSubscribeStatus
    let prevReceiveRate = initUi.receiveRate

    const checkAndRender = () => {
      const state = hotStore.getState()
      const uiState = uiStore.getState()
      const scoresChanged = state.sectorScores !== prevSectorScores
      const sectorChanged = uiState.selectedSector !== prevSelectedSector
      const wsStatusChanged = uiState.wsSubscribeStatus !== prevWsSubscribeStatus
      const receiveRateChanged = uiState.receiveRate !== prevReceiveRate
      prevSectorScores = state.sectorScores
      prevSelectedSector = uiState.selectedSector
      prevWsSubscribeStatus = uiState.wsSubscribeStatus
      prevReceiveRate = uiState.receiveRate

      if (wsStatusChanged) {
        const sub = uiState.wsSubscribeStatus?.quote_subscribed ?? false
        wsBadge?.update(sub, 'kiwoom')
      }

      if (receiveRateChanged) {
        updateReceiveRate(uiState.receiveRate)
      }

      if (!scoresChanged && !sectorChanged) return

      // rAF 배칭: 이미 예약된 rAF가 있으면 추가 예약하지 않음
      if (rafHandle !== null) return

      rafHandle = requestAnimationFrame(() => {
        rafHandle = null
        if (!_mounted) return
        const latest = hotStore.getState()
        const latestUi = uiStore.getState()
        const maxTargets = Number(currentVals.sector_max_targets) || 1
        updateRankingRows(latest.sectorScores, latestUi.selectedSector, maxTargets, latestUi.sectorScoresDelta)
        updateMaxTargetsStatus(latest.sectorScores)
      })
    }

    unsubStore = hotStore.subscribe(checkAndRender)
    unsubUiStore = uiStore.subscribe(checkAndRender)
  }

  // 초기 렌더링
  const state = hotStore.getState()
  const uiState = uiStore.getState()
  const maxTargets = Number(currentVals.sector_max_targets) || 1
  updateRankingRows(state.sectorScores, uiState.selectedSector, maxTargets, uiState.sectorScoresDelta)
  updateMaxTargetsStatus(state.sectorScores)
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  notifyPageInactive('sector-ranking')
  if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
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
  wsBadge = null
  rankRows = []
  rowCaches = []
  saving = false
}

export default { mount, unmount }
