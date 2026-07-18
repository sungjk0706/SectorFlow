// frontend/src/pages/sector-ranking-list.ts
// 업종 순위 리스트 패널 — Vanilla TS PageModule (순위 표시만 담당)
// createDataTable 기반 — 헤더/데이터 단일 gridTemplateColumns 공유 (P10/P21/P23).

import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { FONT_WEIGHT, FONT_SIZE, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { getMaxTargetsStatusEl, getMaxTargetsSumEl } from './sector-settings'
import { type SectorScoreRow, DEFAULT_SECTOR_MAX_TARGETS } from '../types'
import type { PageModule } from '../router'

/* ── 모듈 상태 ── */
let _mounted = false
let rafHandle: number | null = null
let unsubStore: (() => void) | null = null
let unsubUiStore: (() => void) | null = null

let dataTable: DataTableApi<SectorScoreRow> | null = null
// 행 클릭 핸들러 해제용 참조
let rowClickHandler: ((e: MouseEvent) => void) | null = null

// 현재 렌더에 사용된 maxScore (진행 바 비율 계산용) — updateRows 시마다 갱신
let currentMaxScore = 1
// 현재 렌더에 사용된 maxTargets (rowStyle 클로저가 참조) — 설정 변경 시마다 갱신
let currentMaxTargets = DEFAULT_SECTOR_MAX_TARGETS
// 현재 선택 업종 (rowStyle 클로저가 참조)
let currentSelected: string | null = null

function updateMaxTargetsStatus(scores: SectorScoreRow[], maxTargets: number): void {
  const el = getMaxTargetsStatusEl()
  if (el) {
    const passed = scores.filter(s => s.is_cutoff_passed).length

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
    // 통과 업종(is_cutoff_passed)을 rank 오름차순 정렬 후 상위 maxTargets개의 total 합산
    const ranked = scores
      .filter(s => s.is_cutoff_passed)
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

/* ── 진행 바 렌더: 행 전체 너비 하단 별도 줄 (rowFooter) ── */
function renderScoreBar(row: SectorScoreRow): HTMLElement {
  const barOuter = document.createElement('div')
  Object.assign(barOuter.style, {
    width: '100%',
    height: '5px',
    background: COLOR.borderLight,
    borderRadius: '3px',
    overflow: 'hidden',
  })

  const barInner = document.createElement('div')
  const barPct = Math.min((row.final_score / currentMaxScore) * 100, 100)
  // 상위 N 이내 파랑 바 — 공통 progress-bar.ts _colorGradient 패턴과 동일 (P23 시각 일관성)
  // 회색 계열(미통과/N밖)은 그라데이션 효과 미미해 단색 유지 (P24 단순성)
  const barBackground = row.is_cutoff_passed && row.rank <= currentMaxTargets
    ? `linear-gradient(to right, ${COLOR.downLight}, ${COLOR.down})`
    : !row.is_cutoff_passed ? COLOR.inactiveBg : COLOR.muted
  Object.assign(barInner.style, {
    height: '100%',
    width: `${barPct}%`,
    background: barBackground,
    borderRadius: '3px',
  })
  barOuter.appendChild(barInner)

  return barOuter
}

/* ── 컬럼 정의 (단일 SSOT — 헤더/데이터 동일 gridTemplateColumns 공유, P10) ── */
// 셀 구분선 숨김 공통 스타일 (모든 컬럼에 적용)
const NO_BORDER: Partial<CSSStyleDeclaration> = { borderLeft: 'none' }

const COLUMNS: ColumnDef<SectorScoreRow>[] = [
  {
    key: 'rank',
    label: '순위',
    align: 'right',
    type: 'rank',
    render: (row) => String(row.rank),
    headerStyle: NO_BORDER,
    cellStyle: NO_BORDER,
  },
  {
    key: 'sector',
    label: '업종명',
    align: 'left',
    type: 'name',
    render: (row) => row.sector,
    headerStyle: NO_BORDER,
    cellStyle: NO_BORDER,
  },
  {
    key: 'total',
    label: '종목수',
    align: 'right',
    type: 'count',
    render: (row) => String(row.total || ''),
    headerStyle: NO_BORDER,
    cellStyle: { ...NO_BORDER, color: COLOR.down },
  },
  {
    key: 'final_score',
    label: '가산점',
    align: 'right',
    type: 'score',
    render: (row) => {
      const span = document.createElement('span')
      span.textContent = String(row.final_score)
      span.style.fontWeight = FONT_WEIGHT.bold
      return span
    },
    headerStyle: NO_BORDER,
    cellStyle: NO_BORDER,
  },
  {
    key: 'rise_ratio',
    label: '상승비율',
    align: 'right',
    type: 'rise_ratio',
    render: (row) => {
      const txt = row.rise_ratio.toFixed(1) + '%'
      const color = row.rise_ratio > 50 ? COLOR.up : row.rise_ratio < 50 ? COLOR.down : COLOR.neutral
      const span = document.createElement('span')
      span.textContent = txt
      span.style.color = color
      return span
    },
    headerStyle: NO_BORDER,
    cellStyle: NO_BORDER,
  },
  {
    key: 'avg_trade_amount',
    label: '평균거래(억)',
    align: 'right',
    type: 'avg_amount',
    render: (row) => (row.avg_trade_amount / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    headerStyle: NO_BORDER,
    cellStyle: { ...NO_BORDER, color: COLOR.tertiary },
  },
]

/* ── rowStyle: 선택/컷오프 시각화 + 셀 구분선 숨김 (sector-stock.ts 동일 패턴, P23) ── */
function rowStyle(row: SectorScoreRow, _index: number): Partial<CSSStyleDeclaration> {
  const isSel = currentSelected === row.sector
  const isEliminated = !row.is_cutoff_passed || row.rank > currentMaxTargets
  return {
    opacity: isEliminated ? '0.85' : '1',
    background: isSel ? COLOR.downBg : (isEliminated ? COLOR.hoverBg : 'transparent'),
    outline: isSel ? `2px solid ${COLOR.down}` : 'none',
    cursor: 'pointer',
    borderBottom: 'none',
  }
}

/* ── 데이터 갱신: rank 오름차순 정렬 후 DataTable.updateRows ── */
function refreshRows(scores: SectorScoreRow[]): void {
  if (!dataTable) return
  const sorted = [...scores].sort((a, b) => a.rank - b.rank)
  currentMaxScore = sorted.length > 0 ? Math.max(...sorted.map(s => s.final_score), 1) : 1
  dataTable.updateRows(sorted)
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  dataTable = null
  rowClickHandler = null

  const root = document.createElement('div')
  Object.assign(root.style, { padding: '0', margin: '0', width: '100%', height: '100%', display: 'flex', flexDirection: 'column' })
  root.appendChild(createCardTitle('업종순위'))

  // DataTable 생성 — 가상 스크롤 활성화 (전체 업종 표시, P21)
  const initUi = uiStore.getState()
  currentMaxTargets = typeof initUi.settings?.sector_max_targets === 'number'
    ? initUi.settings!.sector_max_targets!
    : DEFAULT_SECTOR_MAX_TARGETS
  currentSelected = initUi.selectedSector

  dataTable = createDataTable<SectorScoreRow>({
    columns: COLUMNS,
    virtualScroll: true,
    keyFn: (row) => row.sector,
    stickyHeader: true,
    rowHeight: 42,
    rowStyle,
    rowFooter: (row) => renderScoreBar(row),
    emptyText: '업종 데이터가 없습니다. 엔진이 기동 중인지 확인해주세요.',
  })

  // 행 클릭 — DataTable 내부 행 요소의 _rowKey 역추적 (내부 직접 부착, 결정사항 B)
  rowClickHandler = (e: MouseEvent) => {
    let target = e.target as HTMLElement | null
    // 클릭 대상에서 상위로 순회하며 data-row-type='data' 행 찾기
    while (target && target !== dataTable!.el) {
      if (target.classList.contains('data-table-row')) {
        const rowKey = (target as unknown as { _rowKey?: string })._rowKey
        if (rowKey) {
          setSelectedSector(rowKey)
          return
        }
      }
      target = target.parentElement
    }
  }
  dataTable.el.addEventListener('click', rowClickHandler)

  // DataTable 래퍼 스타일 — 부모 컨테이너 flex 채우기 + 외곽 border 제거 (여백 축소)
  Object.assign(dataTable.el.style, { flex: '1', minHeight: '0', border: 'none' })

  // 헤더 하단 구분선 숨김 (headerDiv borderBottom 제거) — 셀 구분선 숨김 일관성
  const scrollContainer = dataTable.el.firstElementChild as HTMLElement | null
  const headerDiv = scrollContainer?.firstElementChild as HTMLElement | null
  if (headerDiv) headerDiv.style.borderBottom = 'none'

  // DataTable 래퍼를 감싸는 flex 컬럼 컨테이너 — 여백 최소화 (컬럼 폭 확보)
  const tableWrap = document.createElement('div')
  Object.assign(tableWrap.style, { display: 'flex', flexDirection: 'column', flex: '1', minHeight: '300px', padding: '0', margin: '0' })
  tableWrap.appendChild(dataTable.el)
  root.appendChild(tableWrap)

  container.appendChild(root)

  // hotStore/uiStore 구독 — sectorScores/selectedSector/settings 변동 시 갱신
  {
    const initHot = hotStore.getState()
    let prevSectorScores = initHot.sectorScores
    let prevSelectedSector = initUi.selectedSector
    let prevSettings = initUi.settings
    let prevDelta: { delta: boolean; changed_sectors: string[]; removed_sectors: string[] } | null = initUi.sectorScoresDelta

    const checkAndRender = () => {
      const state = hotStore.getState()
      const uiState = uiStore.getState()
      const scoresChanged = state.sectorScores !== prevSectorScores
      const sectorChanged = uiState.selectedSector !== prevSelectedSector
      const settingsChanged = uiState.settings !== prevSettings
      const deltaChanged = uiState.sectorScoresDelta !== prevDelta
      prevSectorScores = state.sectorScores
      prevSelectedSector = uiState.selectedSector
      prevSettings = uiState.settings
      prevDelta = uiState.sectorScoresDelta

      if (!scoresChanged && !sectorChanged && !settingsChanged && !deltaChanged) return

      if (rafHandle !== null) return

      rafHandle = requestAnimationFrame(() => {
        rafHandle = null
        if (!_mounted) return
        const latest = hotStore.getState()
        const latestUi = uiStore.getState()
        const rawT = latestUi.settings?.sector_max_targets
        const maxTargets = typeof rawT === 'number' ? rawT : DEFAULT_SECTOR_MAX_TARGETS
        currentMaxTargets = maxTargets
        currentSelected = latestUi.selectedSector

        // delta 모드: changed_sectors만 개별 갱신 (성능 최적화)
        // 단, settings/selected/maxScore 변경 시는 전체 갱신 필요 (바 비율·rowStyle 영향)
        const delta = latestUi.sectorScoresDelta
        const sorted = [...latest.sectorScores].sort((a, b) => a.rank - b.rank)
        const newMaxScore = sorted.length > 0 ? Math.max(...sorted.map(s => s.final_score), 1) : 1
        const maxScoreChanged = newMaxScore !== currentMaxScore
        const needFullRefresh = settingsChanged || sectorChanged || maxScoreChanged
        if (delta && delta.delta && !needFullRefresh && dataTable && dataTable.updateItemByKey) {
          currentMaxScore = newMaxScore
          for (const sector of delta.changed_sectors) {
            dataTable.updateItemByKey(sector)
          }
        } else if (dataTable) {
          currentMaxScore = newMaxScore
          dataTable.updateRows(sorted)
        }
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
  currentMaxTargets = maxTargets
  currentSelected = uiState.selectedSector
  refreshRows(state.sectorScores)
  updateMaxTargetsStatus(state.sectorScores, maxTargets)
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (rowClickHandler && dataTable) {
    dataTable.el.removeEventListener('click', rowClickHandler)
    rowClickHandler = null
  }
  if (dataTable) {
    dataTable.destroy()
    dataTable = null
  }
}

export default { mount, unmount } satisfies PageModule
