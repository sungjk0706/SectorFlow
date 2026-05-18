// frontend/src/pages/sector-analysis.ui.ts
// 업종분석 페이지 — 순수 UI 껍데기 (Dumb Component)
// 비즈니스 로직 제거, Props로 데이터 수신

import { createSettingRow, createNumInput, createMoneyInput, createWsStatusBadge } from '../components/common/setting-row'
import { createDualLabelSlider } from '../components/common/create-slider'
import type { DualLabelSliderHandle } from '../components/common/create-slider'
import { FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'

// ── Props 타입 정의 ──

export interface SectorAnalysisProps {
  // 설정 값
  minTradeAmt: number
  minRiseRatio: number
  trimChangeRate: number
  trimTradeAmt: number
  maxTargets: number
  riseRatioWeight: number
  
  // 업종 순위 데이터
  sectorScores: SectorScoreRow[]
  selectedSector: string | null
  
  // 실시간 상태
  wsSubscribed: boolean
  
  // 이벤트 핸들러 (UI 전용 상태 변경)
  onMinTradeAmtChange: (value: number) => void
  onMinRiseRatioChange: (value: number) => void
  onTrimChangeRateChange: (value: number) => void
  onTrimTradeAmtChange: (value: number) => void
  onMaxTargetsChange: (value: number) => void
  onRiseRatioWeightChange: (value: number) => void
  onSectorClick: (sector: string) => void
}

export interface SectorScoreRow {
  rank: number
  sector: string
  total: number
  final_score: number
  rise_ratio: number
  total_trade_amount: number
}

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

function updateMaxTargetsStatus(scores: SectorScoreRow[], maxTargetsStatusEl: HTMLElement | null): void {
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

/* ── 업종 순위 리스트 빌드 ── */
function buildRankingRows(container: HTMLElement): HTMLDivElement[] {
  const rows: HTMLDivElement[] = []
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

    container.appendChild(row)
    rows.push(row)
  }
  return rows
}

interface RowCache {
  rank: number; sector: string; total: number; finalScore: string
  riseRatio: string; riseColor: string; tradeAmt: string
  barWidth: string; barColor: string; opacity: string; selected: boolean; visible: boolean
}

function updateRankingRows(
  rows: HTMLDivElement[],
  rowCaches: (RowCache | null)[],
  scores: SectorScoreRow[],
  selected: string | null,
  maxTargets: number,
): void {
  const maxScore = scores.length > 0 ? Math.max(...scores.map(s => s.final_score), 1) : 1

  for (let i = 0; i < MAX_ROWS; i++) {
    const row = rows[i]
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
}

/* ── 컴포넌트 생성 함수 ── */

export function createSectorAnalysisCard(props: SectorAnalysisProps): { el: HTMLElement; update: (newProps: SectorAnalysisProps) => void; destroy: () => void } {
  const root = document.createElement('div')
  
  // 입력 컴포넌트 참조
  let minTradeAmtInput: ReturnType<typeof createMoneyInput> | null = null
  let trimChangeRateInput: ReturnType<typeof createNumInput> | null = null
  let trimTradeAmtInput: ReturnType<typeof createNumInput> | null = null
  let minRiseRatioInput: ReturnType<typeof createNumInput> | null = null
  let maxTargetsInput: ReturnType<typeof createNumInput> | null = null
  let maxTargetsStatusEl: HTMLSpanElement | null = null
  let dualSlider: DualLabelSliderHandle | null = null
  let wsBadge: ReturnType<typeof createWsStatusBadge> | null = null
  
  // 업종 순위 행 DOM 참조
  let rankRows: HTMLDivElement[] = []
  let rowCaches: (RowCache | null)[] = []

  // 제목 + 실시간 상태 뱃지
  const titleRow = document.createElement('div')
  Object.assign(titleRow.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '0 0 12px' })
  const h4 = document.createElement('h4')
  h4.style.margin = '0'
  h4.textContent = '업종 분석'
  titleRow.appendChild(h4)

  wsBadge = createWsStatusBadge({ subscribed: props.wsSubscribed, broker: 'kiwoom' })
  titleRow.appendChild(wsBadge.el)
  root.appendChild(titleRow)

  // ① 종목 필터
  root.appendChild(createStepLabel('①', '종목 필터'))
  minTradeAmtInput = createMoneyInput({ 
    value: props.minTradeAmt, 
    onChange: props.onMinTradeAmtChange, 
    step: 1, 
    name: 'sector_min_trade_amt' 
  })
  root.appendChild(createSettingRow('5일평균거래대금 컷오프 (억원)', minTradeAmtInput.el))

  root.appendChild(createArrowDivider())

  // ② 업종 컷오프
  root.appendChild(createStepLabel('②', '업종 컷오프'))
  minRiseRatioInput = createNumInput({ 
    value: props.minRiseRatio, 
    onChange: props.onMinRiseRatioChange, 
    step: 1, 
    name: 'sector_min_rise_ratio_pct' 
  })
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
  trimChangeRateInput = createNumInput({ 
    value: props.trimChangeRate, 
    onChange: props.onTrimChangeRateChange, 
    step: 1, 
    name: 'sector_trim_change_rate_pct' 
  })
  leftCol.appendChild(trimChangeRateInput.el)

  const rightCol = document.createElement('div')
  rightCol.style.textAlign = 'right'
  const rightLabel = document.createElement('div')
  Object.assign(rightLabel.style, { color: '#555', marginBottom: '4px' })
  rightLabel.textContent = '거래대금 상/하위 컷오프 (%)'
  rightCol.appendChild(rightLabel)
  const rightInputWrap = document.createElement('div')
  Object.assign(rightInputWrap.style, { display: 'flex', justifyContent: 'flex-end' })
  trimTradeAmtInput = createNumInput({ 
    value: props.trimTradeAmt, 
    onChange: props.onTrimTradeAmtChange, 
    step: 1, 
    name: 'sector_trim_trade_amt_pct' 
  })
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
    value: props.riseRatioWeight,
    step: 1,
    leftLabel: (v) => `업종내 상승비율 ${100 - v}%`,
    rightLabel: (v) => `업종내 거래대금 ${v}%`,
    leftColor: '#0d6efd',
    leftColorLight: '#8bb8f8',
    rightColor: '#fd7e14',
    rightColorLight: '#fdc89e',
    onChange() {
      // UI 상태만 업데이트 (비즈니스 로직 제거)
    },
    onCommit(v) {
      props.onRiseRatioWeightChange(v)
    },
  })
  weightWrap.appendChild(dualSlider.el)
  root.appendChild(weightWrap)

  // ⑤ 매수 대상
  root.appendChild(createStepLabel('⑤', '매수 대상'))
  maxTargetsInput = createNumInput({ 
    value: props.maxTargets, 
    onChange: props.onMaxTargetsChange, 
    step: 1, 
    name: 'sector_max_targets' 
  })

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
  rankRows = buildRankingRows(rankContainer)
  rankSection.appendChild(rankContainer)
  root.appendChild(rankSection)

  // 초기 렌더링
  updateRankingRows(rankRows, rowCaches, props.sectorScores, props.selectedSector, props.maxTargets)
  updateMaxTargetsStatus(props.sectorScores, maxTargetsStatusEl)

  // 행 클릭 이벤트
  rankRows.forEach((row) => {
    row.addEventListener('click', () => {
      const sector = row.dataset.sector
      if (sector) props.onSectorClick(sector)
    })
  })

  // Props 업데이트 함수
  function update(newProps: SectorAnalysisProps): void {
    // 입력 값 동기화
    minTradeAmtInput?.setValue(newProps.minTradeAmt)
    trimChangeRateInput?.setValue(newProps.trimChangeRate)
    trimTradeAmtInput?.setValue(newProps.trimTradeAmt)
    minRiseRatioInput?.setValue(newProps.minRiseRatio)
    maxTargetsInput?.setValue(newProps.maxTargets)
    
    // 슬라이더 값 동기화
    if (dualSlider && !dualSlider.isInteracting && dualSlider.getValue() !== newProps.riseRatioWeight) {
      dualSlider.setValue(newProps.riseRatioWeight)
    }
    
    // WS 상태 배지 업데이트
    wsBadge?.update(newProps.wsSubscribed, 'kiwoom')
    
    // 업종 순위 리스트 업데이트
    updateRankingRows(rankRows, rowCaches, newProps.sectorScores, newProps.selectedSector, newProps.maxTargets)
    updateMaxTargetsStatus(newProps.sectorScores, maxTargetsStatusEl)
  }

  // 파괴 함수
  function destroy(): void {
    minTradeAmtInput = null
    trimChangeRateInput = null
    trimTradeAmtInput = null
    minRiseRatioInput = null
    maxTargetsInput = null
    maxTargetsStatusEl = null
    dualSlider = null
    wsBadge = null
    rankRows = []
    rowCaches = []
  }

  return { el: root, update, destroy }
}
