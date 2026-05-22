// frontend/src/pages/sector-analysis.ts
// 업종분석 페이지 — Vanilla TS PageModule (SectorAnalysisCard.tsx 1:1 전환)

import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { createSettingsManager } from '../settings'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingRow, createNumInput, createMoneyInput, createWsStatusBadge } from '../components/common/setting-row'
import { toastResult } from '../components/common/save-toast'
import { createDualLabelSlider } from '../components/common/create-slider'
import type { DualLabelSliderHandle } from '../components/common/create-slider'
import { toDisplayValue, toServerValue } from '../utils/sliderConvert'
import { FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import type { SectorScoreRow, AppSettings } from '../types'

const NUM_KEYS = ['sector_min_trade_amt', 'sector_min_rise_ratio_pct', 'sector_max_targets', 'sector_trim_trade_amt_pct', 'sector_trim_change_rate_pct'] as const
const MAX_ROWS = 60

/* ── 헬퍼: 단계 라벨 ── */
function createStepLabel(num: string, text: string): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, { fontSize: FONT_SIZE.small, color: '#999', marginBottom: '2px', display: 'flex', alignItems: 'center', gap: '4px' })
  const badge = document.createElement('span')
  Object.assign(badge.style, { color: '#0d6efd', fontWeight: FONT_WEIGHT.normal })
  badge.textContent = num
  div.appendChild(badge)
  div.appendChild(document.createTextNode(text))
  return div
}

function updateMaxTargetsStatus(scores: SectorScoreRow[]): void {
  if (!maxTargetsStatusEl) return
  const passed = scores.filter(s => s.rank > 0).length
  const cutoff = scores.filter(s => s.rank === 0).length

  while (maxTargetsStatusEl.firstChild) {
    maxTargetsStatusEl.removeChild(maxTargetsStatusEl.firstChild)
  }
  maxTargetsStatusEl.style.gap = '4px'

  const passedLabel = document.createElement('span')
  passedLabel.textContent = '통과'
  passedLabel.style.color = '#dc3545'
  maxTargetsStatusEl.appendChild(passedLabel)

  const passedVal = document.createElement('span')
  passedVal.textContent = String(passed)
  passedVal.style.color = '#dc3545'
  passedVal.style.fontWeight = FONT_WEIGHT.bold
  maxTargetsStatusEl.appendChild(passedVal)

  const cutoffLabel = document.createElement('span')
  cutoffLabel.textContent = '컷오프'
  cutoffLabel.style.color = '#0d6efd'
  cutoffLabel.style.marginLeft = '10px'
  maxTargetsStatusEl.appendChild(cutoffLabel)

  const cutoffVal = document.createElement('span')
  cutoffVal.textContent = String(cutoff)
  cutoffVal.style.color = '#0d6efd'
  cutoffVal.style.fontWeight = FONT_WEIGHT.bold
  maxTargetsStatusEl.appendChild(cutoffVal)
}

/* ── 헬퍼: ▼ 화살표 구분선 ── */
function createArrowDivider(): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, { textAlign: 'center', color: '#bbb', fontSize: FONT_SIZE.chip, lineHeight: '1', padding: '2px 0' })
  div.textContent = '▼'
  return div
}

/* ── mount / unmount ── */
let settingsMgr: ReturnType<typeof createSettingsManager> | null = null
let unsubStore: (() => void) | null = null
let unsubSettings: (() => void) | null = null
let saving = false
let wsBadge: ReturnType<typeof createWsStatusBadge> | null = null
let rafHandle: number | null = null
let _mounted = false

// 입력 컴포넌트 참조
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

// Debounced settings save
let pendingSettings: Record<string, any> = {}
let saveTimer: ReturnType<typeof setTimeout> | null = null

async function flushSettingsSave(): Promise<void> {
  if (Object.keys(pendingSettings).length === 0 || !settingsMgr) return
  const dataToSave = { ...pendingSettings }
  pendingSettings = {}
  
  saving = true
  try {
    const res = await settingsMgr.saveSection(dataToSave)
    toastResult(res)
  } finally {
    saving = false
    // If new changes accumulated during the save, flush again
    if (Object.keys(pendingSettings).length > 0) {
      saveTimer = setTimeout(flushSettingsSave, 500)
    } else {
      const latest = settingsMgr.getSettings()
      if (latest) {
        syncFromSettings(latest)
      }
    }
  }
}

function queueSettingSave(key: string, value: any): void {
  pendingSettings[key] = value
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(flushSettingsSave, 500)
}

function onNumChange(key: string, value: number): void {
  let v = value
  if (key === 'sector_max_targets') {
    if (v < 1) {
      v = 1
    }
  }
  currentVals[key] = v
  queueSettingSave(key, v)
}

function saveWeightsNow(ratio: number): void {
  const serverWeights = { rise_ratio: toServerValue(100 - ratio), total_trade_amount: toServerValue(ratio) }
  queueSettingSave('sector_weights', serverWeights)
}

function updateSliderUI(): void {
  if (dualSlider && !dualSlider.isInteracting && dualSlider.getValue() !== currentRiseRatio) {
    dualSlider.setValue(currentRiseRatio)
  }
}

function syncFromSettings(s: AppSettings): void {
  if (saving || Object.keys(pendingSettings).length > 0) return
  for (const k of NUM_KEYS) currentVals[k] = Number((s as Record<string, unknown>)[k]) || 0
  const w = s.sector_weights || {}
  const tradeAmtVal = w.total_trade_amount !== undefined ? Number(w.total_trade_amount) : 0.5
  currentRiseRatio = toDisplayValue(tradeAmtVal)
  // focus 뺏김 방지 — 현재 포커스된 input은 업데이트 제외
  const act = document.activeElement
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
    row.style.cssText = 'height:30px;overflow:hidden;margin-bottom:8px;cursor:pointer;border-radius:6px;padding:4px 2px;visibility:hidden;'

    const info = document.createElement('div')
    info.style.cssText = 'display:flex;align-items:center;margin-bottom:2px;padding:0 2px;'
    const defs = [
      'width:24px;text-align:right;color:#888;',
      'flex:1;font-weight:500;padding-left:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
      'width:40px;text-align:right;color:#1a73e8;margin-right:12px;',
      'width:48px;text-align:right;',
      'width:64px;text-align:right;',
      'width:72px;text-align:right;color:#666;',
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
      if (sector) setSelectedSector(sector)
    })

    container.appendChild(row)
    rankRows.push(row)
  }
}

function updateRankingRows(scores: SectorScoreRow[], selected: string | null, maxTargets: number, delta: { delta: boolean; changed_sectors: string[]; removed_sectors: string[] } | null = null): void {
  const maxScore = scores.length > 0 ? Math.max(...scores.map(s => s.final_score), 1) : 1

  // 초기화 예외 처리: delta 없거나 최초 데이터 수신 시 전체 화면 생성
  if (!delta || !delta.delta) {
    for (let i = 0; i < MAX_ROWS; i++) {
      const row = rankRows[i]
      if (!row) continue

      // 숨김 처리
      if (i >= scores.length) {
        if (!rowCaches[i] || rowCaches[i]!.visible) {
          row.style.visibility = 'hidden'
          rowCaches[i] = { rank: -1, sector: '', total: 0, finalScore: '', riseRatio: '', riseColor: '', tradeAmt: '', barWidth: '', barColor: '', opacity: '', selected: false, visible: false }
        }
        continue
      }

      const s = scores[i]
      const prev = rowCaches[i]
      const isSel = selected === s.sector
      const isUnranked = s.rank === 0
      const opacity = isUnranked ? '0.4' : (s.rank > maxTargets ? '0.65' : '1')
      const finalScore = s.final_score.toFixed(1)
      const riseRatio = s.rise_ratio.toFixed(1) + '%'
      const riseColor = s.rise_ratio > 50 ? 'red' : s.rise_ratio < 50 ? 'blue' : '#333'
      const tradeAmt = Math.round(s.total_trade_amount / 100_000_000).toLocaleString()
      const barWidth = `${Math.min((s.final_score / maxScore) * 100, 100)}%`
      const barColor = isUnranked ? '#dee2e6' : (s.rank <= maxTargets ? '#0d6efd' : '#adb5bd')

      // 첫 렌더 또는 visibility 변경
      if (!prev || !prev.visible) row.style.visibility = 'visible'

      // 델타 비교 — 바뀐 속성만 DOM 반영
      if (!prev || prev.opacity !== opacity) row.style.opacity = opacity
      if (!prev || prev.sector !== s.sector) row.dataset.sector = s.sector
      if (!prev || prev.selected !== isSel) {
        row.style.background = isSel ? '#e8f0fe' : 'transparent'
        row.style.outline = isSel ? '2px solid #1a73e8' : 'none'
      }

      const spans = row.firstElementChild!.children as HTMLCollectionOf<HTMLSpanElement>
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
    return
  }

  // delta 기반 증분 갱신
  const { changed_sectors, removed_sectors } = delta

  // removed_sectors에 해당하는 행 제거
  for (const sector of removed_sectors) {
    const index = rowCaches.findIndex(c => c && c.sector === sector)
    if (index !== -1 && rankRows[index]) {
      rankRows[index].style.visibility = 'hidden'
      rowCaches[index] = { rank: -1, sector: '', total: 0, finalScore: '', riseRatio: '', riseColor: '', tradeAmt: '', barWidth: '', barColor: '', opacity: '', selected: false, visible: false }
    }
  }

  // changed_sectors에 해당하는 행 갱신 + 정렬 순서 동기화
  const sectorToIndex = new Map<string, number>()
  scores.forEach((s, i) => sectorToIndex.set(s.sector, i))

  for (const sector of changed_sectors) {
    const newIndex = sectorToIndex.get(sector)
    if (newIndex === undefined) continue

    const s = scores[newIndex]
    const prevCacheIndex = rowCaches.findIndex(c => c && c.sector === sector)
    const row = rankRows[newIndex]

    if (!row) continue

    const isSel = selected === s.sector
    const isUnranked = s.rank === 0
    const opacity = isUnranked ? '0.4' : (s.rank > maxTargets ? '0.65' : '1')
    const finalScore = s.final_score.toFixed(1)
    const riseRatio = s.rise_ratio.toFixed(1) + '%'
    const riseColor = s.rise_ratio > 50 ? 'red' : s.rise_ratio < 50 ? 'blue' : '#333'
    const tradeAmt = Math.round(s.total_trade_amount / 100_000_000).toLocaleString()
    const barWidth = `${Math.min((s.final_score / maxScore) * 100, 100)}%`
    const barColor = isUnranked ? '#dee2e6' : (s.rank <= maxTargets ? '#0d6efd' : '#adb5bd')

    row.style.visibility = 'visible'
    row.style.opacity = opacity
    row.dataset.sector = s.sector
    row.style.background = isSel ? '#e8f0fe' : 'transparent'
    row.style.outline = isSel ? '2px solid #1a73e8' : 'none'

    const spans = row.firstElementChild!.children as HTMLCollectionOf<HTMLSpanElement>
    spans[0].textContent = s.rank === 0 ? '❌' : String(s.rank)
    spans[1].textContent = s.sector
    spans[2].textContent = String(s.total || '')
    spans[3].textContent = finalScore
    spans[4].textContent = riseRatio
    spans[4].style.color = riseColor
    spans[5].textContent = tradeAmt

    const bar = row.lastElementChild!.firstElementChild as HTMLDivElement
    bar.style.width = barWidth
    bar.style.background = barColor

    // 캐시 갱신
    rowCaches[newIndex] = { rank: s.rank, sector: s.sector, total: s.total, finalScore, riseRatio, riseColor, tradeAmt, barWidth, barColor, opacity, selected: isSel, visible: true }

    // 정렬 순서 동기화: 점수 변동으로 순위가 바뀌면 DOM 노드 위치 재정렬
    if (prevCacheIndex !== -1 && prevCacheIndex !== newIndex) {
      const container = row.parentNode
      if (container) {
        // 새 위치에 삽입
        const targetRow = rankRows[newIndex]
        const referenceRow = rankRows[newIndex + 1]
        if (referenceRow) {
          container.insertBefore(targetRow, referenceRow)
        } else {
          container.appendChild(targetRow)
        }
      }
    }
  }
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  notifyPageActive('sector-analysis')
  settingsMgr = createSettingsManager(uiStore)
  currentVals = {}
  currentRiseRatio = 50
  rankRows = []
  rowCaches = []
  saving = false
  pendingSettings = {}

  const root = document.createElement('div')

  // 제목 + 실시간 상태 뱃지
  const titleRow = document.createElement('div')
  Object.assign(titleRow.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '0 0 12px' })
  const h4 = document.createElement('h4')
  h4.style.margin = '0'
  h4.textContent = '업종 분석'
  titleRow.appendChild(h4)

  const initSt = uiStore.getState()
  const isSubscribed = initSt.wsSubscribeStatus?.quote_subscribed ?? false
  wsBadge = createWsStatusBadge({ subscribed: isSubscribed, broker: 'kiwoom' })
  titleRow.appendChild(wsBadge.el)
  root.appendChild(titleRow)

  // ① 종목 필터
  root.appendChild(createStepLabel('①', '종목 필터'))
  minTradeAmtInput = createMoneyInput({ value: 0, onChange: v => onNumChange('sector_min_trade_amt', v), step: 1, name: 'sector_min_trade_amt' })
  root.appendChild(createSettingRow('5일평균거래대금 컷오프 (억원)', minTradeAmtInput.el))

  root.appendChild(createArrowDivider())

  // ② 업종 컷오프
  root.appendChild(createStepLabel('②', '업종 컷오프'))
  minRiseRatioInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_min_rise_ratio_pct', v), step: 1, name: 'sector_min_rise_ratio_pct' })
  root.appendChild(createSettingRow('업종내종목상승비율 컷오프 (%)', minRiseRatioInput.el))

  root.appendChild(createArrowDivider())

  // ③ 극단값 제외
  root.appendChild(createStepLabel('③', '극단값 제외'))
  const trimRow = document.createElement('div')
  Object.assign(trimRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '6px 0', borderBottom: '1px solid #eee' })

  const leftCol = document.createElement('div')
  const leftLabel = document.createElement('div')
  Object.assign(leftLabel.style, { color: '#555', marginBottom: '4px' })
  leftLabel.textContent = '상승률 상/하위 컷오프 (%)'
  leftCol.appendChild(leftLabel)
  trimChangeRateInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_trim_change_rate_pct', v), step: 1, name: 'sector_trim_change_rate_pct' })
  leftCol.appendChild(trimChangeRateInput.el)

  const rightCol = document.createElement('div')
  rightCol.style.textAlign = 'right'
  const rightLabel = document.createElement('div')
  Object.assign(rightLabel.style, { color: '#555', marginBottom: '4px' })
  rightLabel.textContent = '거래대금 상/하위 컷오프 (%)'
  rightCol.appendChild(rightLabel)
  const rightInputWrap = document.createElement('div')
  Object.assign(rightInputWrap.style, { display: 'flex', justifyContent: 'flex-end' })
  trimTradeAmtInput = createNumInput({ value: 0, onChange: v => onNumChange('sector_trim_trade_amt_pct', v), step: 1, name: 'sector_trim_trade_amt_pct' })
  rightInputWrap.appendChild(trimTradeAmtInput.el)
  rightCol.appendChild(rightInputWrap)

  trimRow.appendChild(leftCol)
  trimRow.appendChild(rightCol)
  root.appendChild(trimRow)

  root.appendChild(createArrowDivider())

  // ④ 점수 가중치
  root.appendChild(createStepLabel('④', '점수 가중치'))
  const weightWrap = document.createElement('div')
  Object.assign(weightWrap.style, { marginBottom: '8px', marginTop: '4px' })

  dualSlider = createDualLabelSlider({
    min: 0,
    max: 100,
    value: currentRiseRatio,
    step: 1,
    leftLabel: (v) => `업종내 상승비율 ${100 - v}%`,
    rightLabel: (v) => `업종내 거래대금 ${v}%`,
    leftColor: '#0d6efd',
    leftColorLight: '#8bb8f8',
    rightColor: '#fd7e14',
    rightColorLight: '#fdc89e',
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
  root.appendChild(createStepLabel('⑤', '매수 대상'))
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
  maxTargetsLabel.textContent = '상위 업종 수'
  Object.assign(maxTargetsLabel.style, { flex: '1', fontSize: FONT_SIZE.label, color: '#333', display: 'flex', alignItems: 'center' })

  maxTargetsStatusEl = document.createElement('span')
  Object.assign(maxTargetsStatusEl.style, {
    flex: '1.6',
    fontSize: FONT_SIZE.label,
    color: '#888',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    whiteSpace: 'nowrap',
  })

  const rightWrap = document.createElement('div')
  Object.assign(rightWrap.style, { flex: '1', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' })
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
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', fontSize: '11px', color: '#888', marginBottom: '6px', padding: '0 2px' })
  const headerDefs: [string, string][] = [
    ['width:24px;text-align:right;', '순위'],
    ['flex:1;padding-left:6px;', '업종명'],
    ['width:40px;text-align:right;margin-right:12px;', '종목수'],
    ['width:48px;text-align:right;', '종합점수'],
    ['width:64px;text-align:right;', '상승비율'],
    ['width:72px;text-align:right;', '거래대금(억)'],
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

    unsubStore = hotStore.subscribe((state) => {
      const scoresChanged = state.sectorScores !== prevSectorScores
      const uiState = uiStore.getState()
      const sectorChanged = uiState.selectedSector !== prevSelectedSector
      const wsStatusChanged = uiState.wsSubscribeStatus !== prevWsSubscribeStatus
      prevSectorScores = state.sectorScores
      prevSelectedSector = uiState.selectedSector
      prevWsSubscribeStatus = uiState.wsSubscribeStatus

      if (wsStatusChanged) {
        const sub = uiState.wsSubscribeStatus?.quote_subscribed ?? false
        wsBadge?.update(sub, 'kiwoom')
      }

      if (!scoresChanged && !sectorChanged) return

      // rAF coalescing: 이미 예약된 rAF가 있으면 추가 예약하지 않음
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
    })
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
  notifyPageInactive('sector-analysis')
  if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
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
  pendingSettings = {}
}

export default { mount, unmount }
