// frontend/src/pages/sector-ranking-list.ts
// 업종 순위 리스트 패널 — Vanilla TS PageModule (순위 표시만 담당)
// createDataTable 기반 — 헤더/데이터 단일 gridTemplateColumns 공유 (P10/P21/P23).

import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { FONT_WEIGHT, FONT_SIZE, COLOR, RADIUS, fmtMillionsToBillion } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { virtualScrollOptions } from '../components/common/table-options'
import { createFrameScheduler, type FrameScheduler } from '../components/common/frame-scheduler'
import { getMaxTargetsStatusEl, getMaxTargetsSumEl } from './sector-settings'
import { type SectorScoreRow, DEFAULT_SECTOR_MAX_TARGETS } from '../types'
import type { PageModule } from '../router'

/* ── 모듈 상태 ── */
let _mounted = false
let unsubStore: (() => void) | null = null
let unsubUiStore: (() => void) | null = null

let dataTable: DataTableApi<SectorScoreRow> | null = null
// 행 클릭 핸들러 해제용 참조
let rowClickHandler: ((e: MouseEvent) => void) | null = null
// 공통 화면주기 갱신 도구 — 전체 갱신 경로(updateRows) 예약용 (delta 모드는 동기 유지)
let renderScheduler: FrameScheduler | null = null

// 현재 렌더에 사용된 maxScore (진행 바 비율 계산용) — updateRows 시마다 갱신
let currentMaxScore = 1
// 현재 렌더에 사용된 maxTargets (rowStyle 클로저가 참조) — 설정 변경 시마다 갱신
let currentMaxTargets = DEFAULT_SECTOR_MAX_TARGETS
// 현재 선택 업종 (rowStyle 클로저가 참조)
let currentSelected: string | null = null
// rank 변동 감지용 — 이전 업종별 순위 저장 (전체 갱신 시마다 재구축)
// 우측 패널(sector-stock.ts)의 prevSectorRanks와 같은 패턴 (W4 정합성 · W11 표현 통일)
let prevSectorRanks = new Map<string, number>()

// 수신 대기 중 메시지 요소 (P21 투명성 — 임계값 미통과 시 표시)
let waitingNoticeEl: HTMLElement | null = null

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
    borderRadius: RADIUS.xs,
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
    borderRadius: RADIUS.xs,
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
    key: 'bonus_relative_strength',
    label: '집중도',
    align: 'right',
    type: 'score',
    render: (row) => String(row.bonus_relative_strength),
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
    label: '평균거래',
    align: 'right',
    type: 'avg_amount',
    render: (row) => fmtMillionsToBillion(row.avg_trade_amount),
    headerStyle: NO_BORDER,
    cellStyle: { ...NO_BORDER, color: COLOR.tertiary },
  },
]

/* ── rowStyle: 선택/컷오프 시각화 + 셀 구분선 숨김 (sector-stock.ts 동일 패턴, P23) ── */
function rowStyle(row: SectorScoreRow, _index: number): Partial<CSSStyleDeclaration> {
  const isSel = currentSelected === row.sector
  const isEliminated = !row.is_cutoff_passed || row.rank > currentMaxTargets
  return {
    background: isSel ? COLOR.downBg : (isEliminated ? COLOR.eliminatedBg : 'transparent'),
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
  updatePrevRanks(scores)
}

/** 이전 업종별 순위 맵 재구축 — 전체 갱신 후 호출하여 다음 rank 변동 감지 기준 갱신.
 *  우측 패널(sector-stock.ts)의 updatePrevRanks와 같은 패턴 (W4 정합성 · W11 표현 통일). */
function updatePrevRanks(scores: SectorScoreRow[]): void {
  prevSectorRanks = new Map()
  for (const s of scores) prevSectorRanks.set(s.sector, s.rank)
}

/** rank 변동 감지 — changed_sectors 중 하나라도 이전 순위와 다르거나 새 업종이면 true (전체 갱신 필요).
 *  우측 패널(sector-stock.ts)의 detectRankChange와 같은 패턴 (W4 정합성 · W11 표현 통일). */
function detectRankChange(changedSectors: string[], currentScores: SectorScoreRow[]): boolean {
  const currentMap = new Map<string, number>()
  for (const s of currentScores) currentMap.set(s.sector, s.rank)
  for (const sector of changedSectors) {
    const prevRank = prevSectorRanks.get(sector)
    const currentRank = currentMap.get(sector)
    if (prevRank === undefined || currentRank === undefined || prevRank !== currentRank) {
      return true
    }
  }
  return false
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  dataTable = null
  rowClickHandler = null

  const root = document.createElement('div')
  Object.assign(root.style, { padding: '0', margin: '0', width: '100%', height: '100%', display: 'flex', flexDirection: 'column' })
  root.appendChild(createCardTitle('업종순위'))

  // 수신 대기 중 안내 배지 (P21 투명성 — 임계값 미통과 시 "데이터 수신 대기 중" 표시)
  // sector-stock.ts의 nxtOnlyNoticeBadge와 동일 패턴 (P23 일관성)
  waitingNoticeEl = document.createElement('div')
  Object.assign(waitingNoticeEl.style, {
    display: 'none',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '8px',
    padding: '6px 12px',
    background: COLOR.warningBg,
    borderRadius: RADIUS.sm,
    border: '1px solid ' + COLOR.warning,
    fontSize: FONT_SIZE.badge,
    color: COLOR.warning,
  })
  waitingNoticeEl.textContent = '업종순위 데이터 수신 대기 중...'
  root.appendChild(waitingNoticeEl)

  // DataTable 생성 — 가상 스크롤 활성화 (전체 업종 표시, P21)
  const initUi = uiStore.getState()
  currentMaxTargets = typeof initUi.settings?.sector_max_targets === 'number'
    ? initUi.settings!.sector_max_targets!
    : DEFAULT_SECTOR_MAX_TARGETS
  currentSelected = initUi.selectedSector

  dataTable = createDataTable<SectorScoreRow>(
    virtualScrollOptions<SectorScoreRow>({
      columns: COLUMNS,
      keyFn: (row) => row.sector,
      rowHeight: 42,
      rowStyle,
      rowFooter: (row) => renderScoreBar(row),
      emptyText: '업종 데이터가 없습니다. 엔진이 기동 중인지 확인해주세요.',
      // 컬럼 폭 계산 준비 게이트 — 백엔드 수신율 임계값 통과 후 실제 rows로 1회 계산 (P10 SSOT).
      // 준비 전에는 헤더/type 캡 기반 안전 폭으로 대기, 준비 완료 후 영구 고정.
      widthReady: () => uiStore.getState().sectorDataReady,
    }),
  )

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
  Object.assign(tableWrap.style, { display: 'flex', flexDirection: 'column', flex: '1', minHeight: '0', padding: '0', margin: '0', overflow: 'hidden' })
  tableWrap.appendChild(dataTable.el)
  root.appendChild(tableWrap)

  container.appendChild(root)

  // hotStore/uiStore 구독 — sectorScores/selectedSector/settings/waiting 변동 시 갱신.
  // 전체 갱신 경로(updateRows)는 공통 화면주기 갱신 도구로 예약 — 한 화면 주기에 한 번만 실행 (W11 표현 통일).
  // delta 모드(updateItemByKey)는 동기 유지 — 바뀐 업종만 즉시 갱신하는 것이 타이밍 동기화 목표에 부합 (W4).
  // 우측 패널(sector-stock.ts)도 같은 store 변경 시 같은 공통 도구로 예약하여 두 패널이 같은 화면 주기에 갱신 (P22 정합성).
  {
    const initHot = hotStore.getState()
    let prevSectorScores = initHot.sectorScores
    let prevSelectedSector = initUi.selectedSector
    let prevSettings = initUi.settings
    let prevDelta: { delta: boolean; changed_sectors: string[]; removed_sectors: string[] } | null = initUi.sectorScoresDelta
    let prevWaiting = initUi.sectorScoresWaiting

    // 화면주기 갱신 콜백 — 전체 갱신 (공통 도구에서 호출). 실행 시점에 최신 상태를 다시 읽는다.
    const renderNow = (deltaMode: boolean) => {
      if (!_mounted) return
      const latest = hotStore.getState()
      const latestUi = uiStore.getState()
      const rawT = latestUi.settings?.sector_max_targets
      const maxTargets = typeof rawT === 'number' ? rawT : DEFAULT_SECTOR_MAX_TARGETS
      currentMaxTargets = maxTargets
      currentSelected = latestUi.selectedSector

      // 수신 대기 중 상태 표시 (P21 투명성)
      if (waitingNoticeEl) {
        waitingNoticeEl.style.display = latestUi.sectorScoresWaiting ? 'flex' : 'none'
      }

      // delta 모드: changed_sectors만 개별 갱신 (동기 호출 시에만 — 바뀐 업종만 즉시 갱신)
      // 전체 모드: updateRows로 전체 재구성 (공통 도구 콜백에서 호출)
      const delta = latestUi.sectorScoresDelta
      const sorted = [...latest.sectorScores].sort((a, b) => a.rank - b.rank)
      const newMaxScore = sorted.length > 0 ? Math.max(...sorted.map(s => s.final_score), 1) : 1
      currentMaxScore = newMaxScore
      if (deltaMode && delta && delta.delta && dataTable && dataTable.updateItemByKey) {
        for (const sector of delta.changed_sectors) {
          dataTable.updateItemByKey(sector)
        }
      } else if (dataTable) {
        dataTable.updateRows(sorted)
      }
      updateMaxTargetsStatus(latest.sectorScores, maxTargets)
    }

    // 공통 화면주기 갱신 도구 — 전체 갱신 경로를 화면 주기에 맞춰 실행 (delta 모드는 동기 유지)
    renderScheduler = createFrameScheduler(() => renderNow(false))

    const checkAndRender = () => {
      const state = hotStore.getState()
      const uiState = uiStore.getState()
      const scoresChanged = state.sectorScores !== prevSectorScores
      const sectorChanged = uiState.selectedSector !== prevSelectedSector
      const settingsChanged = uiState.settings !== prevSettings
      const deltaChanged = uiState.sectorScoresDelta !== prevDelta
      const waitingChanged = uiState.sectorScoresWaiting !== prevWaiting
      prevSectorScores = state.sectorScores
      prevSelectedSector = uiState.selectedSector
      prevSettings = uiState.settings
      prevDelta = uiState.sectorScoresDelta
      prevWaiting = uiState.sectorScoresWaiting

      if (!scoresChanged && !sectorChanged && !settingsChanged && !deltaChanged && !waitingChanged) return

      // delta 모드 판정 — settings/selected/waiting 변경이 없고 maxScore도 동일하고
      // rank 변동도 없으면 바뀐 업종만 동기 갱신 (타이밍 동기화 목표에 부합).
      // rank 변동이 있으면 전체 재정렬이 필요하므로 전체 갱신으로 전환 (W4 정합성 —
      // 우측 패널과 같은 판정 기준·같은 갱신 경로 사용).
      // 그 외(전체 갱신 필요)는 공통 도구로 화면주기 갱신 예약.
      const delta = uiState.sectorScoresDelta
      const needFullByFlags = settingsChanged || sectorChanged || waitingChanged
      let useDelta = false
      if (delta && delta.delta && !needFullByFlags && dataTable && dataTable.updateItemByKey) {
        const sorted = [...state.sectorScores].sort((a, b) => a.rank - b.rank)
        const newMaxScore = sorted.length > 0 ? Math.max(...sorted.map(s => s.final_score), 1) : 1
        // rank 변동 감지 — changed_sectors 중 하나라도 이전 순위와 다르면 전체 갱신.
        // 우측 패널(sector-stock.ts)의 detectRankChange와 같은 패턴 (W4 정합성).
        const hasRankChange = detectRankChange(delta.changed_sectors, state.sectorScores)
        if (newMaxScore === currentMaxScore && !hasRankChange) useDelta = true
      }

      if (useDelta) {
        // delta 모드 — 동기 갱신 유지 (바뀐 업종만 즉시)
        renderNow(true)
      } else {
        // 전체 갱신 — 공통 도구로 화면주기 갱신 예약 (이미 예약 중이면 no-op)
        renderScheduler?.schedule()
      }
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
  // 수신 대기 중 상태 초기 표시 (P21 투명성)
  if (waitingNoticeEl) {
    waitingNoticeEl.style.display = uiState.sectorScoresWaiting ? 'flex' : 'none'
  }
  refreshRows(state.sectorScores)
  updateMaxTargetsStatus(state.sectorScores, maxTargets)
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (renderScheduler) { renderScheduler.destroy(); renderScheduler = null }
  if (rowClickHandler && dataTable) {
    dataTable.el.removeEventListener('click', rowClickHandler)
    rowClickHandler = null
  }
  if (dataTable) {
    dataTable.destroy()
    dataTable = null
  }
  waitingNoticeEl = null
  prevSectorRanks = new Map()
}

export default { mount, unmount } satisfies PageModule
