// frontend/src/pages/sector-stock.ts
// 업종별 종목 실시간 시세 — Web Component (Shadow DOM + DataTable 적용)

import { createDataTable, type DataTableApi, type ColumnDef, type GroupRow as DataTableGroupRow, type TableRow } from '../components/common/data-table'
import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createStockNameColumn, makeSeqColumn, makeCodeColumn, makePriceColumn, makeChangeColumn, makeRateColumn, makeStrengthColumn, makeAmountColumn, makeAvgAmountColumn, FONT_SIZE, FONT_WEIGHT, COLOR } from '../components/common/ui-styles'
import { createCardTitleWithContent } from '../components/common/card-title'
import { createSearchInput } from '../components/common/search-input'
import type { SectorStock, SectorScoreRow } from '../types'

/* ── ColumnDef 배열 (10개 컬럼) ── */

const COLUMNS: ColumnDef<DataRowItem>[] = [
  makeSeqColumn<DataRowItem>((item) => item.seq),
  makeCodeColumn<DataRowItem>((item) => item.stock.code),
  createStockNameColumn<DataRowItem>(
    (item: DataRowItem) => ({
      name: item.stock.name,
      market_type: item.stock.market_type,
      nxt_enable: item.stock.nxt_enable
    })
  ),
  makePriceColumn<DataRowItem>(
    (item) => Number(item.stock.cur_price) || 0,
    (item) => Number(item.stock.change_rate) || 0,
  ),
  makeChangeColumn<DataRowItem>((item) => Number(item.stock.change) || 0),
  makeRateColumn<DataRowItem>((item) => Number(item.stock.change_rate) || 0),
  makeStrengthColumn<DataRowItem>((item) => parseFloat(String(item.stock.strength ?? '')) || 0),
  makeAmountColumn<DataRowItem>((item) => Number(item.stock.trade_amount) || 0),
  makeAvgAmountColumn<DataRowItem>((item) => Number(item.stock.avg_amt_5d) || 0),
]

/* ── 행 타입 ── */

interface GroupRowItem {
  type: 'group'
  sector: string
  label: string
  score?: number
  dim: boolean
}

interface DataRowItem {
  type: 'data'
  stock: SectorStock
  dim: boolean
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

/* ── RowItem → TableRow<DataRowItem> 매핑 ── */

function mapRowsToTableRows(rows: RowItem[]): TableRow<DataRowItem>[] {
  return rows.map(item => {
    if (item.type === 'group') {
      return {
        type: 'group' as const,
        label: item.label,
        key: 'g-' + item.sector,
        score: item.score,
        style: { opacity: item.dim ? '0.65' : '1' },
      } satisfies DataTableGroupRow
    }
    return item
  })
}

/* ── KRX 비활성 구간 판정 (NXT-only 거래 시간대) ── */

const KRX_INACTIVE_PHASES = new Set([
  '장개시전',
  '장전 동시호가',
  '장마감',
  '장후 시간외',
  '시간외 단일가',
  '휴장일',
])

const NXT_ACTIVE_PHASES = new Set([
  '프리마켓',
  '메인마켓',
  '애프터마켓',
])

function isKrxInactiveWindow(marketPhase: { krx: string; nxt: string }): boolean {
  return KRX_INACTIVE_PHASES.has(marketPhase.krx)
    && NXT_ACTIVE_PHASES.has(marketPhase.nxt)
}

/* ── rows 계산 ── */

function computeRows(
  stockMap: Record<string, SectorStock>,
  sectorScores: SectorScoreRow[],
  maxTargets: number,
  selectedSector: string | null,
  matchedCodes: Set<string> | null,
  rowCache: Map<string, { stock: SectorStock; row: DataRowItem }>,
  marketPhase: { krx: string; nxt: string },
): RowItem[] {
  // 업종별 종목 그룹핑
  const grouped = new Map<string, string[]>()
  for (const s of Object.values(stockMap)) {
    const sector = s.sector || '미분류'
    if (selectedSector && sector !== selectedSector) continue
    if (matchedCodes && !matchedCodes.has(s.code)) continue

    // 5일평균거래대금 필터링은 백엔드에서 수행 (단일 소스 진리)

    let arr = grouped.get(sector)
    if (!arr) { arr = []; grouped.set(sector, arr) }
    arr.push(s.code)
  }

  // rank > 0 먼저 표시 (프론트엔드에서 표시 순서 결정)
  const sortedSectorScores = [...sectorScores].sort((a, b) => {
    if (a.rank === 0 && b.rank === 0) return b.final_score - a.final_score
    if (a.rank === 0) return 1
    if (b.rank === 0) return -1
    return b.final_score - a.final_score
  })
  const sectorOrder = sortedSectorScores.map(s => s.sector)
  // selectedSector 또는 검색 모드: 빈 배열로 시작
  const orderedSectors = (selectedSector || matchedCodes) ? [] : [...sectorOrder]

  if (selectedSector) {
    if (grouped.has(selectedSector)) {
      orderedSectors.push(selectedSector)
    }
  } else if (matchedCodes) {
    // 검색 모드: 검색된 종목이 속한 업종만 표시
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

  const krxInactive = isKrxInactiveWindow(marketPhase)
  const rows: RowItem[] = []
  let stockSeq = 0

  for (const sector of orderedSectors) {
    const codes = grouped.get(sector)
    const sectorRank = sortedSectorScores.find(s => s.sector === sector)?.rank ?? 0
    const dim = sectorRank === 0 || sectorRank > maxTargets
    const score = scoreMap.get(sector)

    rows.push({
      type: 'group',
      sector,
      label: `${sectorRank === 0 ? '❌' : sectorRank}. ${sector}`,
      score,
      dim,
    })

    // 종목이 없으면 종목 행 추가 안 함
    if (!codes) continue

    // selectedSector 모드: 종목코드 기준 안정 정렬 (Map 삽입순서 변동 방지)
    const sortedCodes = selectedSector ? [...codes].sort() : codes

    for (const code of sortedCodes) {
      stockSeq++
      const stock = stockMap[code]
      if (!stock) continue

      // KRX 비활성 구간: KRX 단독 종목 (nxt_enable !== true) 불투명 처리
      const stockDim = dim || (krxInactive && !stock.nxt_enable)

      // 행 객체 캐시: stock 참조가 같으면 이전 행 재사용
      const cached = rowCache.get(code)
      if (cached && cached.stock === stock && cached.row.dim === stockDim && cached.row.seq === stockSeq) {
        rows.push(cached.row)
      } else {
        const row: DataRowItem = { type: 'data', stock, dim: stockDim, seq: stockSeq }
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
  private searchTerm = ''
  private currentMatchedCodes: Set<string> | null = null
  private rowCache = new Map<string, { stock: SectorStock; row: DataRowItem }>()
  private onRealDataTick: ((e: Event) => void) | null = null

  // DOM 참조
  private titleH3: HTMLElement | null = null
  private titleBaseSpan: HTMLElement | null = null
  private titleFilterSpan: HTMLElement | null = null
  private titleCountSpan: HTMLElement | null = null
  private titleWarningSpan: HTMLElement | null = null
  private filterBadge: HTMLElement | null = null
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
    const maxTargets = Number(uiState.settings?.sector_max_targets) || 10
    // 5일평균거래대금 필터링은 백엔드에서 수행 (단일 소스 진리)

    return computeRows(
      state.sectorStocks,
      state.sectorScores,
      maxTargets,
      uiState.selectedSector,
      this.currentMatchedCodes,
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
    const stockCount = Object.keys(state.sectorStocks).length
    const minTradeAmt = uiState.settings?.sector_min_trade_amt ?? 0

    // 타이틀 갱신 — CSS display 토글 + textContent 갱신 (innerHTML 파괴 금지)
    if (this.titleFilterSpan && this.titleCountSpan) {
      this.titleFilterSpan.textContent = `5일평균최소거래대금(${minTradeAmt})억`
      this.titleFilterSpan.style.display = ''
      this.titleCountSpan.textContent = `(${stockCount}종목)`
      this.titleCountSpan.style.display = ''
    }

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

    // 종목 수 경고
    if (this.titleWarningSpan) {
      if (stockCount > 170) {
        this.titleWarningSpan.style.display = ''
        this.titleWarningSpan.textContent = '⚠️ 170개 초과'
      } else {
        this.titleWarningSpan.style.display = 'none'
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
    this.currentMatchedCodes = null
    this.rowCache = new Map()
    notifyPageActive('sector-ranking')

    this.rootEl = document.createElement('div')
    Object.assign(this.rootEl.style, { display: 'flex', flexDirection: 'column', height: '100%', contain: 'content' })

    // 1. 카드 타이틀 — DOM 요소 1회 생성 (이후 textContent/display만 갱신)
    const titleContent = document.createElement('span')
    this.titleBaseSpan = document.createElement('span')
    this.titleBaseSpan.textContent = '업종별 종목 실시간 시세'

    this.titleFilterSpan = document.createElement('span')
    Object.assign(this.titleFilterSpan.style, { color: COLOR.down, fontWeight: '500', display: 'none' })

    this.titleCountSpan = document.createElement('span')
    this.titleCountSpan.style.display = 'none'

    this.titleWarningSpan = document.createElement('span')
    Object.assign(this.titleWarningSpan.style, { color: COLOR.warning, fontWeight: '500', display: 'none', marginLeft: '8px' })

    titleContent.appendChild(this.titleBaseSpan)
    titleContent.appendChild(document.createTextNode(' '))
    titleContent.appendChild(this.titleFilterSpan)
    titleContent.appendChild(document.createTextNode(' '))
    titleContent.appendChild(this.titleCountSpan)
    titleContent.appendChild(this.titleWarningSpan)

    this.titleH3 = createCardTitleWithContent(titleContent)
    this.rootEl.appendChild(this.titleH3)

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

    const clearBtn = document.createElement('button')
    Object.assign(clearBtn.style, {
      marginLeft: 'auto',
      background: 'none',
      border: '1px solid ' + COLOR.down,
      borderRadius: '4px',
      color: COLOR.down,
      cursor: 'pointer',
      fontSize: FONT_SIZE.badge,
      padding: '2px 8px',
    })
    clearBtn.textContent = '전체 보기'
    clearBtn.addEventListener('click', () => setSelectedSector(null))
    this.filterBadge.appendChild(clearBtn)
    this.rootEl.appendChild(this.filterBadge)

    // 3. 검색 + WS 상태 배지
    const searchRow = document.createElement('div')
    Object.assign(searchRow.style, {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '12px',
      marginBottom: '4px',
    })

    this.searchInput = createSearchInput({
      placeholder: '종목명 / 코드 검색',
      width: '220px',
      onSearch: (query) => {
        this.searchTerm = query
        this.refreshRows()
      },
    })
    searchRow.appendChild(this.searchInput.el)


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
        opacity: row.dim ? '0.65' : '1',
        background: this.currentMatchedCodes?.has(row.stock.code) ? '#fff9c4' : '',
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

        prevSectorStocks = state.sectorStocks
        prevSectorScores = state.sectorScores
        prevSelectedSector = uiState.selectedSector
        prevWsSubscribeStatus = uiState.wsSubscribeStatus
        prevSettings = uiState.settings
        prevMarketPhase = uiState.marketPhase

        if (!changed) return

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
    this.titleBaseSpan = null
    this.titleFilterSpan = null
    this.titleCountSpan = null
    this.titleWarningSpan = null
    this.filterBadge = null
    this.emptyDiv = null
    this.scrollContainer = null
    this.searchInput = null
    this.rowCache.clear()
    this.rowCache = new Map()
    this.currentMatchedCodes = null
    this.searchTerm = ''
  }
}

/* ── Custom Element 등록 ── */

customElements.define('sector-stock-table', SectorStockTable)

/* ── Export for backward compatibility (optional) ── */
// This export is kept for potential backward compatibility,
// but the primary usage should be via <sector-stock-table> custom element.
export default SectorStockTable