// frontend/src/pages/sector-ranking-list.ts
// 업종 순위 리스트 패널 — Vanilla TS PageModule (순위 표시만 담당)

import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { FONT_WEIGHT, FONT_SIZE, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { getMaxTargetsStatusEl, getMaxTargetsSumEl } from './sector-settings'
import { type SectorScoreRow, DEFAULT_SECTOR_MAX_TARGETS } from '../types'
import type { PageModule } from '../router'

const MAX_ROWS = 60

/* ── 모듈 상태 ── */
let _mounted = false
let rafHandle: number | null = null
let unsubStore: (() => void) | null = null
let unsubUiStore: (() => void) | null = null

// 업종 순위 행 DOM 참조
let rankRows: HTMLDivElement[] = []
// 행별 이전 렌더 값 캐시 (델타 갱신용)
interface RowCache {
  rank: number; sector: string; total: number; finalScore: string
  riseRatio: string; riseColor: string; tradeAmt: string
  barWidth: string; barColor: string; opacity: string; selected: boolean; visible: boolean
  bgColor: string
}
let rowCaches: (RowCache | null)[] = []

function updateMaxTargetsStatus(scores: SectorScoreRow[], maxTargets: number): void {
  const el = getMaxTargetsStatusEl()
  if (el) {
    const passed = scores.filter(s => s.rank > 0).length

    while (el.firstChild) {
      el.removeChild(el.firstChild)
    }
    el.style.gap = '4px'

    const passedLabel = document.createElement('span')
    passedLabel.textContent = '통과'
    passedLabel.style.color = COLOR.up
    el.appendChild(passedLabel)

    const passedVal = document.createElement('span')
    passedVal.textContent = String(passed)
    passedVal.style.color = COLOR.up
    passedVal.style.fontWeight = FONT_WEIGHT.bold
    el.appendChild(passedVal)
  }

  // 상위 N 업종 종목 합계 보조 줄 갱신 (P21 투명성)
  const sumEl = getMaxTargetsSumEl()
  if (sumEl) {
    // rank>0 업종을 rank 오름차순 정렬 후 상위 maxTargets개의 total 합산
    const ranked = scores
      .filter(s => s.rank > 0)
      .sort((a, b) => a.rank - b.rank)
    const limit = maxTargets > 0 ? maxTargets : 0
    const topSectors = limit > 0 ? ranked.slice(0, limit) : []
    const stockSum = topSectors.reduce((acc, s) => acc + (s.total || 0), 0)

    while (sumEl.firstChild) {
      sumEl.removeChild(sumEl.firstChild)
    }

    const labelSpan = document.createElement('span')
    labelSpan.textContent = `상위 ${limit}개 업종 종목 합계:`
    labelSpan.style.color = COLOR.tertiary
    sumEl.appendChild(labelSpan)

    const valSpan = document.createElement('span')
    valSpan.textContent = `${stockSum}종목`
    valSpan.style.color = COLOR.down
    valSpan.style.fontWeight = FONT_WEIGHT.bold
    valSpan.style.fontSize = FONT_SIZE.label
    sumEl.appendChild(valSpan)
  }
}

/* ── 업종 순위 리스트 빌드 ── */
function buildRankingRows(container: HTMLElement): void {
  for (let i = 0; i < MAX_ROWS; i++) {
    const row = document.createElement('div')
    row.style.cssText = 'height:30px;overflow:hidden;margin-bottom:8px;cursor:pointer;border-radius:6px;padding:4px 2px;display:none;'

    const info = document.createElement('div')
    info.style.cssText = 'display:flex;align-items:center;margin-bottom:2px;padding:0 2px;'
    const defs = [
      'width:24px;text-align:right;color:' + COLOR.tertiary + ';',
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
    barOuter.style.cssText = `height:5px;background:${COLOR.borderLight};border-radius:3px;overflow:hidden;`
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
  const sortedScores = [...scores].sort((a, b) => {
    if (a.rank === 0 && b.rank === 0) return b.final_score - a.final_score
    if (a.rank === 0) return 1
    if (b.rank === 0) return -1
    return a.rank - b.rank
  })

  const maxScore = sortedScores.length > 0 ? Math.max(...sortedScores.map(s => s.final_score), 1) : 1

  for (let i = 0; i < MAX_ROWS; i++) {
    const row = rankRows[i]
    if (!row) continue

    if (i >= sortedScores.length) {
      if (!rowCaches[i] || rowCaches[i]!.visible) {
        row.style.display = 'none'
        rowCaches[i] = { rank: -1, sector: '', total: 0, finalScore: '', riseRatio: '', riseColor: '', tradeAmt: '', barWidth: '', barColor: '', opacity: '', selected: false, visible: false, bgColor: '' }
      }
      continue
    }

    const s = sortedScores[i]
    const prev = rowCaches[i]
    const isSel = selected === s.sector
    const isEliminated = s.rank === 0 || s.rank > maxTargets
    const opacity = isEliminated ? '0.85' : '1'
    const bgColor = isSel ? COLOR.downBg : (isEliminated ? COLOR.hoverBg : 'transparent')
    const finalScore = String(s.final_score)
    const riseRatio = s.rise_ratio.toFixed(1) + '%'
    const riseColor = s.rise_ratio > 50 ? COLOR.up : s.rise_ratio < 50 ? COLOR.down : COLOR.neutral
    const tradeAmt = (s.avg_trade_amount / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    const barWidth = `${Math.min((s.final_score / maxScore) * 100, 100)}%`
    const barColor = s.rank === 0 ? COLOR.inactiveBg : (s.rank <= maxTargets ? COLOR.down : COLOR.muted)

    if (!prev || !prev.visible) row.style.display = ''

    if (!prev || prev.opacity !== opacity) row.style.opacity = opacity
    if (!prev || prev.sector !== s.sector) row.dataset.sector = s.sector
    if (!prev || prev.bgColor !== bgColor || prev.selected !== isSel) {
      row.style.background = bgColor
      row.style.outline = isSel ? '2px solid ' + COLOR.down : 'none'
    }

    const spans = Array.from(row.firstElementChild!.children) as HTMLSpanElement[]
    if (!prev || prev.rank !== i + 1) spans[0].textContent = String(i + 1)
    if (!prev || prev.sector !== s.sector) spans[1].textContent = s.sector
    if (!prev || prev.total !== s.total) spans[2].textContent = String(s.total || '')
    if (!prev || prev.finalScore !== finalScore) spans[3].textContent = finalScore
    if (!prev || prev.riseRatio !== riseRatio) spans[4].textContent = riseRatio
    if (!prev || prev.riseColor !== riseColor) spans[4].style.color = riseColor
    if (!prev || prev.tradeAmt !== tradeAmt) spans[5].textContent = tradeAmt

    const bar = row.lastElementChild!.firstElementChild as HTMLDivElement
    if (!prev || prev.barWidth !== barWidth) bar.style.width = barWidth
    if (!prev || prev.barColor !== barColor) bar.style.background = barColor

    rowCaches[i] = { rank: i + 1, sector: s.sector, total: s.total, finalScore, riseRatio, riseColor, tradeAmt, barWidth, barColor, opacity, selected: isSel, visible: true, bgColor }
  }
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  rankRows = []
  rowCaches = []

  const root = document.createElement('div')

  root.appendChild(createCardTitle('업종순위'))

  // 헤더 행
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', fontSize: '11px', color: COLOR.tertiary, marginBottom: '6px', padding: '0 2px' })
  const headerDefs: [string, string][] = [
    ['width:24px;text-align:right;', '순위'],
    ['flex:1;padding-left:6px;', '업종명'],
    ['width:40px;text-align:right;margin-right:12px;', '종목수'],
    ['width:48px;text-align:right;', '가산점'],
    ['width:64px;text-align:right;', '상승비율'],
    ['width:72px;text-align:right;', '평균거래(억)'],
  ]
  for (const [css, text] of headerDefs) {
    const sp = document.createElement('span')
    sp.style.cssText = css
    sp.textContent = text
    headerRow.appendChild(sp)
  }
  root.appendChild(headerRow)

  const rankContainer = document.createElement('div')
  buildRankingRows(rankContainer)
  root.appendChild(rankContainer)

  container.appendChild(root)

  // hotStore/uiStore 구독 — sectorScores/selectedSector/settings 변동 시 델타 갱신
  {
    const initHot = hotStore.getState()
    const initUi = uiStore.getState()
    let prevSectorScores = initHot.sectorScores
    let prevSelectedSector = initUi.selectedSector
    let prevSettings = initUi.settings

    const checkAndRender = () => {
      const state = hotStore.getState()
      const uiState = uiStore.getState()
      const scoresChanged = state.sectorScores !== prevSectorScores
      const sectorChanged = uiState.selectedSector !== prevSelectedSector
      const settingsChanged = uiState.settings !== prevSettings
      prevSectorScores = state.sectorScores
      prevSelectedSector = uiState.selectedSector
      prevSettings = uiState.settings

      if (!scoresChanged && !sectorChanged && !settingsChanged) return

      if (rafHandle !== null) return

      rafHandle = requestAnimationFrame(() => {
        rafHandle = null
        if (!_mounted) return
        const latest = hotStore.getState()
        const latestUi = uiStore.getState()
        const rawTargets = latestUi.settings?.sector_max_targets
        const maxTargets = typeof rawTargets === 'number' ? rawTargets : DEFAULT_SECTOR_MAX_TARGETS
        updateRankingRows(latest.sectorScores, latestUi.selectedSector, maxTargets, latestUi.sectorScoresDelta)
        updateMaxTargetsStatus(latest.sectorScores, maxTargets)
      })
    }

    unsubStore = hotStore.subscribe(checkAndRender)
    unsubUiStore = uiStore.subscribe(checkAndRender)
  }

  // 초기 렌더링
  const state = hotStore.getState()
  const uiState = uiStore.getState()
  const rawTargets = uiState.settings?.sector_max_targets
  const maxTargets = typeof rawTargets === 'number' ? rawTargets : DEFAULT_SECTOR_MAX_TARGETS
  updateRankingRows(state.sectorScores, uiState.selectedSector, maxTargets, uiState.sectorScoresDelta)
  updateMaxTargetsStatus(state.sectorScores, maxTargets)
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  rankRows = []
  rowCaches = []
}

export default { mount, unmount } satisfies PageModule
