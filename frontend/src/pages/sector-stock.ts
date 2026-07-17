// frontend/src/pages/sector-stock.ts
// 업종별 종목 실시간 시세 — Web Component (Shadow DOM + DataTable 적용)

import { createDataTable, type DataTableApi, type ColumnDef, type GroupRow as DataTableGroupRow, type TableRow } from '../components/common/data-table'
import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createStockNameColumn, makeSeqColumn, makeCodeColumn, makePriceColumn, makeChangeColumn, makeRateColumn, makeStrengthColumn, makeAmountColumn, makeAvgAmountColumn, FONT_SIZE, FONT_WEIGHT, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { createActionButton } from '../components/common/button'
import { createSearchInput } from '../components/common/search-input'
import { createMarketCountRow, type MarketCountRowHandle } from '../components/common/market-count-row'
import { type SectorStock, type SectorScoreRow, DEFAULT_SECTOR_MAX_TARGETS } from '../types'

/* ── ColumnDef 배열 (10개 컬럼) ── */

const COLUMNS: ColumnDef<DataRowItem>[] = [
  makeSeqColumn<DataRowItem>((item) => item.seq),
  makeCodeColumn<DataRowItem>((item) => item.stock.code),
  {
    ...createStockNameColumn<DataRowItem>(
      (item: DataRowItem) => ({
        name: item.stock.name,
        market_type: item.stock.market_type,
        nxt_enable: item.stock.nxt_enable
      })
    ),
    maxWidth: 166,
  },
  makePriceColumn<DataRowItem>(
    (item) => item.stock.cur_price != null ? Number(item.stock.cur_price) : null,
    (item) => item.stock.change_rate != null ? Number(item.stock.change_rate) : null,
  ),
  makeChangeColumn<DataRowItem>((item) => item.stock.change != null ? Number(item.stock.change) : null),
  makeRateColumn<DataRowItem>((item) => item.stock.change_rate != null ? Number(item.stock.change_rate) : null),
  makeStrengthColumn<DataRowItem>((item) => item.stock.strength != null ? parseFloat(String(item.stock.strength)) : null),
  {
    ...makeAmountColumn<DataRowItem>((item) => item.stock.trade_amount != null ? Number(item.stock.trade_amount) : null),
    maxWidth: 126,
  },
  {
    ...makeAvgAmountColumn<DataRowItem>((item) => Number(item.stock.avg_amt_5d) || 0),
    maxWidth: 108,
  },
]

/* ── 행 타입 ── */

interface GroupRowItem {
  type: 'group'
  sector: string
  label: string
  score?: number
  opacity: string
  bgColor: string
}

interface DataRowItem {
  type: 'data'
  stock: SectorStock
  opacity: string
  eliminated: boolean
  seq: number
}

type RowItem = GroupRowItem | DataRowItem

/* ── 검색 필터링 (export for PBT) ── */

export function filterStocksBySearch(
  stocks: Iterable<SectorStock>,
  query: string,
): Set<string> | null {
  const q = query.trim().toLowerCase()
  if (!q) return null
  const codes = new Set<string>()
  for (const s of stocks) {
    if (s.code.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q)) {
      codes.add(s.code)
    }
  }
  return codes
}

/* ── 업종 필터링 (export for PBT) ── */

export function filterStocksBySector(
  stocks: Iterable<SectorStock>,
  selectedSector: string | null,
): SectorStock[] {
  if (!selectedSector) return [...stocks]
  const result: SectorStock[] = []
  for (const s of stocks) {
    if ((s.sector || '미분류') === selectedSector) result.push(s)
  }
  return result
}

/* ── 업종명 검색 필터링 ── */

export function filterSectorsByName(
  stocks: Record<string, SectorStock>,
  query: string,
): Set<string> | null {
  const q = query.trim().toLowerCase()
  if (!q) return null
  const sectors = new Set<string>()
  for (const s of Object.values(stocks)) {
    const sector = (s.sector || '미분류').toLowerCase()
    if (sector.includes(q)) {
      sectors.add(s.sector || '미분류')
    }
  }
  return sectors
}

/* ── RowItem → TableRow<DataRowItem> 매핑 ── */

function mapRowsToTableRows(rows: RowItem[]): TableRow<DataRowItem>[] {
  return rows.map(item => {
    if (item.type === 'group') {
      return {
        type: 'group' as const,
        label: item.label,
        key: 'g-' + item.sector,
        score: item.score,
        style: { opacity: item.opacity, background: item.bgColor },
      } satisfies DataTableGroupRow
    }
    return item
  })
}

/* ── rows 계산 ── */

function computeRows(
  stockMap: Record<string, SectorStock>,
  sectorScores: SectorScoreRow[],
  maxTargets: number,
  selectedSector: string | null,
  matchedCodes: Set<string> | null,
  matchedSectors: Set<string> | null,
  rowCache: Map<string, { stock: SectorStock; row: DataRowItem }>,
  marketPhase: { krx: string; nxt: string; is_nxt_only?: boolean },
): RowItem[] {
  // 업종별 종목 그룹핑
  const grouped = new Map<string, string[]>()
  for (const s of Object.values(stockMap)) {
    const sector = s.sector || '미분류'
    if (selectedSector && sector !== selectedSector) continue
    if (matchedSectors && !matchedSectors.has(sector)) continue
    if (matchedCodes && !matchedCodes.has(s.code)) continue

    // 5일평균거래대금 필터링은 백엔드에서 수행 (단일 소스 진리)

    let arr = grouped.get(sector)
    if (!arr) { arr = []; grouped.set(sector, arr) }
    arr.push(s.code)
  }

  // rank 오름차순 정렬 (모든 업종에 1..N 순위 부여됨, is_cutoff_passed로 통과 여부 구분)
  const sortedSectorScores = [...sectorScores].sort((a, b) => a.rank - b.rank)
  const sectorOrder = sortedSectorScores.map(s => s.sector)
  // selectedSector 또는 검색 모드: 빈 배열로 시작
  const orderedSectors = (selectedSector || matchedCodes || matchedSectors) ? [] : [...sectorOrder]

  if (selectedSector) {
    if (grouped.has(selectedSector)) {
      orderedSectors.push(selectedSector)
    }
  } else if (matchedCodes || matchedSectors) {
    // 검색 모드: 검색된 종목 또는 업종에 해당하는 업종만 표시
    for (const sector of grouped.keys()) {
      if (!orderedSectors.includes(sector)) {
        orderedSectors.push(sector)
      }
    }
  } else {
    // 전체 모드: 모든 업종 표시
    for (const sector of grouped.keys()) {
      if (!orderedSectors.includes(sector)) {
        orderedSectors.push(sector)
      }
    }
  }

  const scoreMap = new Map<string, number>()
  for (const sc of sectorScores) scoreMap.set(sc.sector, sc.final_score)

  const sectorRankMap = new Map<string, number>()
  for (let i = 0; i < sectorOrder.length; i++) sectorRankMap.set(sectorOrder[i], i + 1)

  const krxInactive = marketPhase.is_nxt_only === true
  const rows: RowItem[] = []
  let stockSeq = 0

  for (const sector of orderedSectors) {
    const codes = grouped.get(sector)
    const sectorScore = sortedSectorScores.find(s => s.sector === sector)
    const sectorRank = sectorScore?.rank ?? 0
    const isEliminated = !sectorScore?.is_cutoff_passed || sectorRank > maxTargets
    const opacity = isEliminated ? '0.85' : '1'
    const bgColor = isEliminated ? COLOR.hoverBg : 'transparent'
    const score = scoreMap.get(sector)

    // NXT 전용 시간대: 이 업종의 활성 종목(NXT 지원)이 0개면 그룹 행도 숨김
    if (krxInactive && codes) {
      const hasActiveStock = codes.some(code => {
        const s = stockMap[code]
        return s && s.nxt_enable
      })
      if (!hasActiveStock) continue
    }

    rows.push({
      type: 'group',
      sector,
      label: `${sectorRankMap.get(sector) ?? 0}. ${sector}`,
      score,
      opacity,
      bgColor,
    })

    // 종목이 없으면 종목 행 추가 안 함
    if (!codes) continue

    // selectedSector 모드: 종목코드 기준 안정 정렬 (Map 삽입순서 변동 방지)
    const sortedCodes = selectedSector ? [...codes].sort() : codes

    for (const code of sortedCodes) {
      const stock = stockMap[code]
      if (!stock) continue
      // KRX 비활성 구간: KRX 단독 종목 (nxt_enable !== true)은 행 자체를 추가하지 않음 (숨김)
      if (krxInactive && !stock.nxt_enable) continue
      stockSeq++
      const rowOpacity = isEliminated ? '0.85' : opacity

      // 행 객체 캐시: stock 참조가 같으면 이전 행 재사용
      const cached = rowCache.get(code)
      if (cached && cached.stock === stock && cached.row.opacity === rowOpacity && cached.row.eliminated === isEliminated && cached.row.seq === stockSeq) {
        rows.push(cached.row)
      } else {
        const row: DataRowItem = { type: 'data', stock, opacity: rowOpacity, eliminated: isEliminated, seq: stockSeq }
        rowCache.set(code, { stock, row })
        rows.push(row)
      }
    }
  }

  return rows
}


/* ── Web Component 클래스 ── */

class SectorStockTable extends HTMLElement {
  private shadow: ShadowRoot
  private rootEl: HTMLElement | null = null
  private dataTable: DataTableApi<DataRowItem> | null = null
  private unsubStore: (() => void) | null = null
  private unsubUi: (() => void) | null = null
  private searchInput: ReturnType<typeof createSearchInput> | null = null
  private sectorSearchInput: ReturnType<typeof createSearchInput> | null = null
  private searchTerm = ''
  private sectorSearchTerm = ''
  private currentMatchedCodes: Set<string> | null = null
  private currentMatchedSectors: Set<string> | null = null
  private rowCache = new Map<string, { stock: SectorStock; row: DataRowItem }>()
  private onRealDataTick: ((e: Event) => void) | null = null

  // DOM 참조
  private titleH3: HTMLElement | null = null
  private titleFilterNumSpan: HTMLElement | null = null
  private marketCountRow: MarketCountRowHandle | null = null
  private filterBadge: HTMLElement | null = null
  private nxtOnlyNoticeBadge: HTMLElement | null = null
  private emptyDiv: HTMLElement | null = null
  private scrollContainer: HTMLElement | null = null
  private _rafId: number | null = null
  private _mounted = false

  constructor() {
    super()
    this.shadow = this.attachShadow({ mode: 'open' })
  }

  /* ── 행 빌드 + UI 갱신 (기능 로직 보호) ── */

  private buildRows(): RowItem[] {
    const state = hotStore.getState()
    const uiState = uiStore.getState()
    this.currentMatchedCodes = filterStocksBySearch(Object.values(state.sectorStocks), this.searchTerm)
    this.currentMatchedSectors = filterSectorsByName(state.sectorStocks, this.sectorSearchTerm)
    const rawTargets = uiState.settings?.sector_max_targets
    const maxTargets = typeof rawTargets === 'number' ? rawTargets : DEFAULT_SECTOR_MAX_TARGETS
    // 5일평균거래대금 필터링은 백엔드에서 수행 (단일 소스 진리)

    return computeRows(
      state.sectorStocks,
      state.sectorScores,
      maxTargets,
      uiState.selectedSector,
      this.currentMatchedCodes,
      this.currentMatchedSectors,
      this.rowCache,
      uiState.marketPhase,
    )
  }

  private refreshRows(): void {
    const rows = this.buildRows()
    const mappedRows = mapRowsToTableRows(rows)
    if (this.dataTable) this.dataTable.updateRows(mappedRows)
    this.updateUI(rows)
  }

  private updateUI(rows: RowItem[]): void {
    const state = hotStore.getState()
    const uiState = uiStore.getState()
    const stocks = Object.values(state.sectorStocks)
    const stockCount = stocks.length
    const krxCount = stocks.filter(s => !s.nxt_enable).length
    const nxtCount = stocks.filter(s => s.nxt_enable).length
    const kospiCount = stocks.filter(s => s.market_type === '0').length
    const kosdaqCount = stocks.filter(s => s.market_type === '10').length
    const minTradeAmt = uiState.settings?.sector_min_trade_amt ?? 0

    // summaryBar 갱신 — 숫자 span textContent만 갱신 (innerHTML 파괴 금지)
    if (this.titleFilterNumSpan) this.titleFilterNumSpan.textContent = String(minTradeAmt)
    if (this.marketCountRow) this.marketCountRow.updateCounts({ total: stockCount, krx: krxCount, nxt: nxtCount, kospi: kospiCount, kosdaq: kosdaqCount })

    // 업종 필터 배지
    if (this.filterBadge) {
      const selected = uiState.selectedSector
      if (selected) {
        this.filterBadge.style.display = 'flex'
        const label = this.filterBadge.querySelector('.badge-label') as HTMLElement
        if (label) label.textContent = `📌 ${selected}`
      } else {
        this.filterBadge.style.display = 'none'
      }
    }

    // NXT 전용 시간대 안내 배지 갱신 (P21 투명성)
    if (this.nxtOnlyNoticeBadge) {
      const isNxtOnly = uiState.marketPhase.is_nxt_only === true
      if (isNxtOnly) {
        const hiddenCount = stocks.filter(s => !s.nxt_enable).length
        this.nxtOnlyNoticeBadge.textContent = `NXT 전용 시간대 — KRX 단독 종목 숨김 (${hiddenCount}종목)`
        this.nxtOnlyNoticeBadge.style.opacity = '0'
        this.nxtOnlyNoticeBadge.style.display = 'flex'
        requestAnimationFrame(() => {
          if (this.nxtOnlyNoticeBadge) this.nxtOnlyNoticeBadge.style.opacity = '1'
        })
      } else {
        this.nxtOnlyNoticeBadge.style.display = 'none'
      }
    }

    // 빈 상태 / 스크롤 영역 표시 토글
    const hasRows = rows.length > 0
    if (this.emptyDiv) this.emptyDiv.style.display = hasRows ? 'none' : ''
    if (this.scrollContainer) this.scrollContainer.style.display = hasRows ? 'flex' : 'none'
  }

  /* ── connectedCallback (mount) ── */

  connectedCallback(): void {
    this._mounted = true
    this.searchTerm = ''
    this.sectorSearchTerm = ''
    this.currentMatchedCodes = null
    this.currentMatchedSectors = null
    this.rowCache = new Map()
    notifyPageActive('sector-ranking')

    this.rootEl = document.createElement('div')
    Object.assign(this.rootEl.style, { display: 'flex', flexDirection: 'column', height: '100%', contain: 'content' })

    // 1. 카드 타이틀 — 좌측 정렬 (다른 패널과 동일)
    this.titleH3 = createCardTitle('업종별 종목 실시간 시세')
    this.rootEl.appendChild(this.titleH3)

    // 1-1. 합계 정보 바 — 1행: 좌측 5일평균거래대금, 우측 종목수 요약
    const summaryBar = document.createElement('div')
    Object.assign(summaryBar.style, {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: '8px',
      flexShrink: '0',
      fontSize: FONT_SIZE.label,
      fontWeight: FONT_WEIGHT.normal,
    })

    // 좌측: 5일평균거래대금 (N)억
    const filterGroup = document.createElement('div')
    Object.assign(filterGroup.style, { display: 'flex', alignItems: 'center', gap: '2px', fontSize: FONT_SIZE.section })
    const filterLabel = document.createElement('span')
    Object.assign(filterLabel.style, { color: COLOR.neutral, marginRight: '8px' })
    filterLabel.textContent = '5일평균거래대금'
    filterGroup.appendChild(filterLabel)
    const filterOpenParen = document.createElement('span')
    Object.assign(filterOpenParen.style, { color: COLOR.neutral })
    filterOpenParen.textContent = '('
    filterGroup.appendChild(filterOpenParen)
    this.titleFilterNumSpan = document.createElement('span')
    Object.assign(this.titleFilterNumSpan.style, { color: COLOR.down, fontWeight: FONT_WEIGHT.semibold })
    filterGroup.appendChild(this.titleFilterNumSpan)
    const filterSuffix = document.createElement('span')
    Object.assign(filterSuffix.style, { color: COLOR.neutral })
    filterSuffix.textContent = ')억'
    filterGroup.appendChild(filterSuffix)
    summaryBar.appendChild(filterGroup)

    // 우측: 합계 KRX NXT▲ 코스피 코스닥 — 공통 컴포넌트 (market-count-row.ts)
    this.marketCountRow = createMarketCountRow()
    summaryBar.appendChild(this.marketCountRow.el)
    this.rootEl.appendChild(summaryBar)

    // 2. 선택된 업종 필터 배지
    this.filterBadge = document.createElement('div')
    Object.assign(this.filterBadge.style, {
      display: 'none',
      alignItems: 'center',
      gap: '8px',
      marginBottom: '8px',
      padding: '6px 12px',
      background: COLOR.downBg,
      borderRadius: '6px',
      border: '1px solid ' + COLOR.down,
    })
    const badgeLabel = document.createElement('span')
    Object.assign(badgeLabel.style, { fontSize: FONT_SIZE.badge, color: COLOR.down, fontWeight: FONT_WEIGHT.normal })
    badgeLabel.className = 'badge-label'
    this.filterBadge.appendChild(badgeLabel)

    const clearBtn = createActionButton({
      label: '전체 보기',
      variant: 'secondary',
      fontSize: FONT_SIZE.badge,
      padding: '2px 8px',
      borderRadius: '4px',
      onClick: () => setSelectedSector(null),
    })
    Object.assign(clearBtn.style, {
      marginLeft: 'auto',
      background: 'none',
      border: '1px solid ' + COLOR.down,
      color: COLOR.down,
    })
    this.filterBadge.appendChild(clearBtn)
    this.rootEl.appendChild(this.filterBadge)

    // 2-1. NXT 전용 시간대 안내 배지 (P21 투명성 — KRX 단독 종목 숨김 사유 명시)
    // filterBadge 패턴 재사용 (같은 페이지 내 동일 배지 구조 — P23 일관성)
    this.nxtOnlyNoticeBadge = document.createElement('div')
    Object.assign(this.nxtOnlyNoticeBadge.style, {
      display: 'none',
      alignItems: 'center',
      gap: '8px',
      marginBottom: '8px',
      padding: '6px 12px',
      background: COLOR.warningBg,
      borderRadius: '6px',
      border: '1px solid ' + COLOR.warning,
      fontSize: FONT_SIZE.badge,
      color: COLOR.warning,
      transition: 'opacity 0.15s ease',
      opacity: '0',
    })
    this.nxtOnlyNoticeBadge.textContent = ''
    this.rootEl.appendChild(this.nxtOnlyNoticeBadge)

    // 3. 검색 입력란 (좌: 종목명/코드, 우: 업종명)
    const searchRow = document.createElement('div')
    Object.assign(searchRow.style, {
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: '12px',
      marginBottom: '4px',
    })

    // 좌측: 종목명/코드 검색 (파란색 라벨 — 인라인 배치)
    this.searchInput = createSearchInput({
      label: '종목명/코드',
      labelColor: COLOR.down,
      placeholder: '종목명/코드 검색',
      borderColor: COLOR.down,
      onSearch: (query) => {
        this.searchTerm = query
        if (query) {
          setSelectedSector(null)
          if (this.sectorSearchInput) this.sectorSearchInput.clear()
          this.sectorSearchTerm = ''
        }
        // 검색어 변경 시 rowCache 클리어 — rowStyle(outline/background) 갱신 보장
        this.rowCache.clear()
        this.refreshRows()
      },
    })
    searchRow.appendChild(this.searchInput.el)

    // 우측: 업종명 검색 (주황색 라벨 — 인라인 배치)
    this.sectorSearchInput = createSearchInput({
      label: '업종명',
      labelColor: COLOR.warning,
      placeholder: '업종명 검색',
      borderColor: COLOR.warning,
      onSearch: (query) => {
        this.sectorSearchTerm = query
        if (query) {
          setSelectedSector(null)
          if (this.searchInput) this.searchInput.clear()
          this.searchTerm = ''
        }
        // 검색어 변경 시 rowCache 클리어 — rowStyle(outline/background) 갱신 보장
        this.rowCache.clear()
        this.refreshRows()
      },
    })
    searchRow.appendChild(this.sectorSearchInput.el)

    this.rootEl.appendChild(searchRow)

    // 5. 빈 상태 메시지
    this.emptyDiv = document.createElement('div')
    Object.assign(this.emptyDiv.style, {
      display: 'none',
      color: COLOR.muted,
      padding: '20px 0',
      textAlign: 'center',
      fontSize: FONT_SIZE.badge,
    })
    this.emptyDiv.textContent = '종목 데이터가 없습니다. 엔진이 기동 중인지 확인해주세요.'
    this.rootEl.appendChild(this.emptyDiv)

    // 6. 스크롤 컨테이너 (DataTable.el을 삽입)
    this.scrollContainer = document.createElement('div')
    Object.assign(this.scrollContainer.style, { flex: '1', minHeight: '200px', display: 'flex', flexDirection: 'column' })

    // 7. DataTable 생성
    this.dataTable = createDataTable<DataRowItem>({
      columns: COLUMNS,
      virtualScroll: true,
      keyFn: (item) => item.stock.code,
      emptyText: '종목 데이터가 없습니다. 엔진이 기동 중인지 확인해주세요.',
      stickyHeader: true,
      groupRowHeight: 48,
      rowHeight: 32,
      rowStyle: (row, _idx) => ({
        opacity: row.opacity,
        background: this.currentMatchedCodes?.has(row.stock.code)
          ? COLOR.downBg
          : row.eliminated ? COLOR.hoverBg : '',
      }),
    })

    this.scrollContainer.appendChild(this.dataTable.el)
    this.rootEl.appendChild(this.scrollContainer)
    this.shadow.appendChild(this.rootEl)

    // 초기 데이터
    const initialRows = this.buildRows()
    const mappedRows = mapRowsToTableRows(initialRows)
    this.dataTable.updateRows(mappedRows)
    this.updateUI(initialRows)

    // Store 구독 — 선택적 구독 가드 (Bug 0 fix: sector-stock interest keys only)
    {
      const initHot = hotStore.getState()
      const initUi = uiStore.getState()
      let prevSectorStocks = initHot.sectorStocks
      let prevSectorScores = initHot.sectorScores
      let prevSelectedSector = initUi.selectedSector
      let prevWsSubscribeStatus = initUi.wsSubscribeStatus
      let prevSettings = initUi.settings
      let prevMarketPhase = initUi.marketPhase

      const checkAndRefresh = () => {
        const state = hotStore.getState()
        const uiState = uiStore.getState()
        const changed =
          state.sectorStocks !== prevSectorStocks ||
          state.sectorScores !== prevSectorScores ||
          uiState.selectedSector !== prevSelectedSector ||
          uiState.wsSubscribeStatus !== prevWsSubscribeStatus ||
          uiState.settings !== prevSettings ||
          uiState.marketPhase !== prevMarketPhase

        if (!changed) return

        // selectedSector가 좌측 패널에서 변경된 경우: 양쪽 검색 입력란 초기화
        if (uiState.selectedSector !== prevSelectedSector) {
          if (this.searchInput) { this.searchInput.clear(); this.searchTerm = '' }
          if (this.sectorSearchInput) { this.sectorSearchInput.clear(); this.sectorSearchTerm = '' }
        }

        prevSectorStocks = state.sectorStocks
        prevSectorScores = state.sectorScores
        prevSelectedSector = uiState.selectedSector
        prevWsSubscribeStatus = uiState.wsSubscribeStatus
        prevSettings = uiState.settings
        prevMarketPhase = uiState.marketPhase

        if (this._rafId === null) {
          this._rafId = requestAnimationFrame(() => {
            this._rafId = null
            if (!this._mounted) return
            this.refreshRows()
          })
        }
      }

      this.unsubStore = hotStore.subscribe(checkAndRefresh)
      this.unsubUi = uiStore.subscribe(checkAndRefresh)
    }

    // 초기 렌더링
    this.refreshRows()

    // O(1) 초저지연 DOM 갱신 이벤트 리스너
    this.onRealDataTick = (e: Event) => {
      const code = (e as CustomEvent<string>).detail
      if (this.dataTable && this.dataTable.updateItemByKey) {
        this.dataTable.updateItemByKey(code)
      }
    }
    window.addEventListener('real-data-tick', this.onRealDataTick)
  }

  /* ── disconnectedCallback (unmount) ── */

  disconnectedCallback(): void {
    this._mounted = false
    notifyPageInactive('sector-ranking')
    if (this.onRealDataTick) {
      window.removeEventListener('real-data-tick', this.onRealDataTick)
      this.onRealDataTick = null
    }
    if (this.unsubStore) { this.unsubStore(); this.unsubStore = null }
    if (this.unsubUi) { this.unsubUi(); this.unsubUi = null }
    if (this._rafId !== null) { cancelAnimationFrame(this._rafId); this._rafId = null }
    if (this.dataTable) { this.dataTable.destroy(); this.dataTable = null }
    if (this.rootEl && this.rootEl.parentNode) this.rootEl.parentNode.removeChild(this.rootEl)
    this.rootEl = null
    this.titleH3 = null
    this.marketCountRow = null
    this.filterBadge = null
    this.nxtOnlyNoticeBadge = null
    this.emptyDiv = null
    this.scrollContainer = null
    this.searchInput = null
    this.sectorSearchInput = null
    this.rowCache.clear()
    this.rowCache = new Map()
    this.currentMatchedCodes = null
    this.currentMatchedSectors = null
    this.searchTerm = ''
    this.sectorSearchTerm = ''
  }
}

/* ── Custom Element 등록 ── */

customElements.define('sector-stock-table', SectorStockTable)

/* ── Export for backward compatibility (optional) ── */
// This export is kept for potential backward compatibility,
// but the primary usage should be via <sector-stock-table> custom element.
export default SectorStockTable