// frontend/src/pages/sector-stock.ts
// 업종별 종목 실시간 시세 — Web Component (Shadow DOM + DataTable 적용)
// 순수 로직(컬럼 정의, 행 계산, 검색 필터)은 sector-stock-rows.ts에 분리 (P24 단순성)

import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { virtualScrollOptions } from '../components/common/table-options'
import { hotStore } from '../stores/hotStore'
import { uiStore, setSelectedSector } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createPageRefreshStatus } from '../utils/page-refresh'
import { createCardTitle } from '../components/common/card-title'
import { createActionButton } from '../components/common/button'
import { createSearchInput } from '../components/common/search-input'
import { createMarketCountRow, type MarketCountRowHandle } from '../components/common/market-count-row'
import { FONT_SIZE, FONT_WEIGHT, COLOR, RADIUS } from '../components/common/ui-styles'
import { createFrameScheduler, type FrameScheduler } from '../components/common/frame-scheduler'
import { createRankChangeDetector, type RankChangeDetector } from '../components/common/rank-change-detector'
import { type MasterStock, DEFAULT_SECTOR_MAX_TARGETS } from '../types'
import { filterStocksBySearch } from '../utils/stock-search'
import {
  COLUMNS,
  type DataRowItem,
  type RowItem,
  filterSectorsByName,
  mapRowsToTableRows,
  computeRows,
} from './sector-stock-rows'

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
  private rowCache = new Map<string, { stock: MasterStock; row: DataRowItem }>()
  private onRealDataTick: ((e: Event) => void) | null = null
  // 공통 화면주기 갱신 도구 — 전체 갱신 경로(updateRows) 예약용 (delta 모드는 동기 유지)
  private renderScheduler: FrameScheduler | null = null
  // 순위 변동 감지 도구 — 가운데 패널(sector-ranking-list.ts)과 같은 도구 공유 (W11 표현 통일 · W12 중복 제거)
  private rankDetector: RankChangeDetector | null = null
  // H-04: 요약 카운트 캐싱 — masterStocks 참조 변경 시에만 재계산
  private countCache: {
    stocksRef: MasterStock[] | null
    stockCount: number
    krxCount: number
    nxtCount: number
    kospiCount: number
    kosdaqCount: number
  } = { stocksRef: null, stockCount: 0, krxCount: 0, nxtCount: 0, kospiCount: 0, kosdaqCount: 0 }

  // DOM 참조
  private titleH3: HTMLElement | null = null
  private titleFilterNumSpan: HTMLElement | null = null
  private marketCountRow: MarketCountRowHandle | null = null
  private filterBadge: HTMLElement | null = null
  private nxtOnlyNoticeBadge: HTMLElement | null = null
  private refreshStatus: ReturnType<typeof createPageRefreshStatus> | null = null
  private emptyDiv: HTMLElement | null = null
  private scrollContainer: HTMLElement | null = null
  private _mounted = false

  constructor() {
    super()
    this.shadow = this.attachShadow({ mode: 'open' })
  }

  /* ── 행 빌드 + UI 갱신 (기능 로직 보호) ── */

  private buildRows(): RowItem[] {
    const state = hotStore.getState()
    const uiState = uiStore.getState()
    this.currentMatchedCodes = filterStocksBySearch(Object.values(state.masterStocks), this.searchTerm)
    this.currentMatchedSectors = filterSectorsByName(state.masterStocks, this.sectorSearchTerm)
    const rawTargets = uiState.settings?.sector_max_targets
    const maxTargets = typeof rawTargets === 'number' ? rawTargets : DEFAULT_SECTOR_MAX_TARGETS
    // 5거래일 평균 거래대금 필터링은 백엔드에서 수행 (단일 소스 진리)

    return computeRows(
      state.masterStocks,
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
    this.rankDetector?.reset(hotStore.getState().sectorScores)
  }

  /** 증분 갱신 — 바뀐 업종의 그룹행만 갱신 (rank 변동 없이 점수·파생만 바뀐 경우).
   *  가운데 패널(sector-ranking-list.ts)의 delta 모드와 같은 타이밍에 동기 갱신 (W4 정합성).
   *  updateItems로 표 엔진 내부 items 배열을 최신 데이터로 동기 교체 후,
   *  바뀐 업종의 그룹행만 updateItemByKey로 다시 렌더링 — 전체 재구성 비용 회피. */
  private refreshRowsIncremental(changedSectors: string[]): void {
    if (!this.dataTable) return
    const rows = this.buildRows()
    const mappedRows = mapRowsToTableRows(rows)
    if (this.dataTable.updateItems) this.dataTable.updateItems(mappedRows)
    if (this.dataTable.updateItemByKey) {
      for (const sector of changedSectors) {
        this.dataTable.updateItemByKey('g-' + sector)
      }
    }
    this.updateUI(rows)
    this.rankDetector?.reset(hotStore.getState().sectorScores)
  }

  private updateUI(rows: RowItem[]): void {
    const state = hotStore.getState()
    const uiState = uiStore.getState()
    // H-04: 4개 filter() 순회를 단일 for 루프로 통합 + masterStocks 참조 변경 시에만 재계산
    const stocks = Object.values(state.masterStocks)
    if (this.countCache.stocksRef !== stocks) {
      let krxCount = 0, nxtCount = 0, kospiCount = 0, kosdaqCount = 0
      for (let i = 0; i < stocks.length; i++) {
        const s = stocks[i]
        if (s.nxt_enable) nxtCount++
        else krxCount++
        if (s.market_type === '0') kospiCount++
        else if (s.market_type === '10') kosdaqCount++
      }
      this.countCache = {
        stocksRef: stocks,
        stockCount: stocks.length,
        krxCount,
        nxtCount,
        kospiCount,
        kosdaqCount,
      }
    }
    const { stockCount, krxCount, nxtCount, kospiCount, kosdaqCount } = this.countCache
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
        // hiddenCount === krxCount (!nxt_enable) — 캐시 재사용 (H-04)
        this.nxtOnlyNoticeBadge.textContent = `NXT 전용 시간대 — KRX 단독 종목 숨김 (${krxCount}종목)`
        this.nxtOnlyNoticeBadge.style.display = 'flex'
      } else {
        this.nxtOnlyNoticeBadge.style.display = 'none'
      }
    }

    // 빈 상태 / 스크롤 영역 표시 토글
    const hasRows = rows.length > 0
    if (this.emptyDiv) this.emptyDiv.style.display = hasRows ? 'none' : ''
    if (this.scrollContainer) this.scrollContainer.style.display = hasRows ? 'flex' : 'none'
  }

  /* ── DOM 빌더 (connectedCallback에서 추출 — P24 단순성) ── */

  /** 합계 정보 바: 좌측 5거래일 평균 거래대금 + 우측 종목수 요약 */
  private buildSummaryBar(): HTMLElement {
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

    // 좌측: 5거래일 평균 거래대금 (N)억
    const filterGroup = document.createElement('div')
    Object.assign(filterGroup.style, { display: 'flex', alignItems: 'center', gap: '2px', fontSize: FONT_SIZE.section })
    const filterLabel = document.createElement('span')
    Object.assign(filterLabel.style, { color: COLOR.neutral, marginRight: '8px' })
    filterLabel.textContent = '5거래일 평균 거래대금'
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
    return summaryBar
  }

  /** 선택된 업종 필터 배지 (전체 보기 버튼 포함) */
  private buildFilterBadge(): HTMLElement {
    this.filterBadge = document.createElement('div')
    Object.assign(this.filterBadge.style, {
      display: 'none',
      alignItems: 'center',
      gap: '8px',
      marginBottom: '8px',
      padding: '6px 12px',
      background: COLOR.downBg,
      borderRadius: RADIUS.sm,
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
      borderRadius: RADIUS.xs,
      onClick: () => setSelectedSector(null),
    })
    Object.assign(clearBtn.style, {
      marginLeft: 'auto',
      background: 'none',
      border: '1px solid ' + COLOR.down,
      color: COLOR.down,
    })
    this.filterBadge.appendChild(clearBtn)
    return this.filterBadge
  }

  /** NXT 전용 시간대 안내 배지 (P21 투명성 — KRX 단독 종목 숨김 사유 명시) */
  private buildNxtNoticeBadge(): HTMLElement {
    this.nxtOnlyNoticeBadge = document.createElement('div')
    Object.assign(this.nxtOnlyNoticeBadge.style, {
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
    this.nxtOnlyNoticeBadge.textContent = ''
    return this.nxtOnlyNoticeBadge
  }

  /** 종목명/코드 검색 핸들러 */
  private onStockSearch = (query: string): void => {
    this.searchTerm = query
    if (query) {
      setSelectedSector(null)
      if (this.sectorSearchInput) this.sectorSearchInput.clear()
      this.sectorSearchTerm = ''
    }
    // 검색어 변경 시 rowCache 클리어 — rowStyle(outline/background) 갱신 보장
    this.rowCache.clear()
    this.refreshRows()
  }

  /** 업종명 검색 핸들러 */
  private onSectorSearch = (query: string): void => {
    this.sectorSearchTerm = query
    if (query) {
      setSelectedSector(null)
      if (this.searchInput) this.searchInput.clear()
      this.searchTerm = ''
    }
    // 검색어 변경 시 rowCache 클리어 — rowStyle(outline/background) 갱신 보장
    this.rowCache.clear()
    this.refreshRows()
  }

  /** 검색 입력란 (좌: 종목명/코드, 우: 업종명) */
  private buildSearchRow(): HTMLElement {
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
      onSearch: this.onStockSearch,
    })
    searchRow.appendChild(this.searchInput.el)

    // 우측: 업종명 검색 (주황색 라벨 — 인라인 배치)
    this.sectorSearchInput = createSearchInput({
      label: '업종명',
      labelColor: COLOR.warning,
      placeholder: '업종명 검색',
      borderColor: COLOR.warning,
      onSearch: this.onSectorSearch,
    })
    searchRow.appendChild(this.sectorSearchInput.el)
    return searchRow
  }

  /** 빈 상태 메시지 + 스크롤 컨테이너 + DataTable 생성 */
  private buildEmptyAndScroll(): { empty: HTMLElement; scroll: HTMLElement } {
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

    // 6. 테이블 컨테이너 (단일 상자 — 높이 계약 통일, 결정 2·3)
    this.scrollContainer = document.createElement('div')
    Object.assign(this.scrollContainer.style, { flex: '1', minHeight: '0', display: 'flex', flexDirection: 'column', overflow: 'hidden' })

    // 7. DataTable 생성 (공통 옵션 헬퍼 — 결정 4)
    this.dataTable = createDataTable<DataRowItem>(
      virtualScrollOptions<DataRowItem>({
        columns: COLUMNS,
        keyFn: (item) => item.stock.code,
        emptyText: '종목 데이터가 없습니다. 엔진이 기동 중인지 확인해주세요.',
        groupRowHeight: 48,
        rowStyle: (row, _idx) => ({
          opacity: row.opacity,
          background: this.currentMatchedCodes?.has(row.stock.code)
            ? COLOR.downBg
            : row.eliminated ? COLOR.hoverBg : '',
        }),
        // 컬럼 폭 계산 준비 게이트 — 백엔드 수신율 임계값 통과 후 실제 rows로 1회 계산 (P10 SSOT).
        // 준비 전에는 헤더/type 캡 기반 안전 폭으로 대기, 준비 완료 후 영구 고정.
        widthReady: () => uiStore.getState().sectorDataReady,
      }),
    )

    this.scrollContainer.appendChild(this.dataTable.el)
    return { empty: this.emptyDiv, scroll: this.scrollContainer }
  }

  /** Store 구독 — 선택적 구독 가드 (Bug 0 fix: sector-stock interest keys only) */
  private setupSubscriptions(): void {
    const initHot = hotStore.getState()
    const initUi = uiStore.getState()
    let prevMasterStocks = initHot.masterStocks
    let prevSectorScores = initHot.sectorScores
    let prevSelectedSector = initUi.selectedSector
    let prevWsSubscribeStatus = initUi.wsSubscribeStatus
    let prevSettings = initUi.settings
    let prevMarketPhase = initUi.marketPhase
    let prevWaiting = initUi.sectorScoresWaiting
    let prevDelta = initUi.sectorScoresDelta

    const checkAndRefresh = () => {
      const state = hotStore.getState()
      const uiState = uiStore.getState()
      const masterStocksChanged = state.masterStocks !== prevMasterStocks
      const sectorScoresChanged = state.sectorScores !== prevSectorScores
      const selectedSectorChanged = uiState.selectedSector !== prevSelectedSector
      const wsSubscribeChanged = uiState.wsSubscribeStatus !== prevWsSubscribeStatus
      const settingsChanged = uiState.settings !== prevSettings
      const marketPhaseChanged = uiState.marketPhase !== prevMarketPhase
      const waitingChanged = uiState.sectorScoresWaiting !== prevWaiting
      const deltaChanged = uiState.sectorScoresDelta !== prevDelta

      const changed = masterStocksChanged || sectorScoresChanged || selectedSectorChanged || wsSubscribeChanged || settingsChanged || marketPhaseChanged || waitingChanged || deltaChanged

      if (!changed) return

      if (this.refreshStatus && Object.keys(state.masterStocks).length > 0) {
        this.refreshStatus.set('', true)
      }

      // selectedSector가 좌측 패널에서 변경된 경우: 양쪽 검색 입력란 초기화
      if (selectedSectorChanged) {
        if (this.searchInput) { this.searchInput.clear(); this.searchTerm = '' }
        if (this.sectorSearchInput) { this.sectorSearchInput.clear(); this.sectorSearchTerm = '' }
      }

      prevMasterStocks = state.masterStocks
      prevSectorScores = state.sectorScores
      prevSelectedSector = uiState.selectedSector
      prevWsSubscribeStatus = uiState.wsSubscribeStatus
      prevSettings = uiState.settings
      prevMarketPhase = uiState.marketPhase
      prevWaiting = uiState.sectorScoresWaiting
      prevDelta = uiState.sectorScoresDelta

      if (!this._mounted) return

      // delta 판정 — 설계서 결정 3-1 판정 흐름:
      // 1. delta 정보 없음 또는 전체 모드(delta=false) → 전체 갱신
      // 2. 사용자 인터랙션(업종 선택·해제, 설정·구독·장상태·대기·종목 데이터 변경) → 전체 갱신
      // 3. removed_sectors 1건 이상 → 전체 갱신 (업종 사라지면 그룹 순서 달라짐)
      // 4. changed_sectors 중 rank 변동 1건 이상 → 전체 갱신 (그룹행 순서 재배치 필요)
      // 5. 위 모두 해당 없음 → 증분 갱신 (바뀐 업종 그룹행만 동기 갱신)
      // real-data-tick 리스너(종목 시세 O(1) 갱신)는 별도 경로로 유지됨.
      const delta = uiState.sectorScoresDelta
      const userInteractionChanged = selectedSectorChanged || settingsChanged || wsSubscribeChanged || marketPhaseChanged || waitingChanged || masterStocksChanged

      if (!delta || !delta.delta || userInteractionChanged || delta.removed_sectors.length > 0) {
        // 전체 갱신 — 공통 화면주기 갱신 도구로 예약 (가운데 패널과 같은 화면 주기에 실행, W4 정합성)
        this.renderScheduler?.schedule()
        return
      }

      if (this.rankDetector?.detect(delta.changed_sectors, state.sectorScores)) {
        // rank 변동 → 전체 갱신 (공통 도구 사용 — W11 표현 통일 · W12 중복 제거)
        this.renderScheduler?.schedule()
        return
      }

      // 증분 갱신 — 동기 호출 (가운데 패널 delta 모드와 같은 타이밍, W4 정합성)
      this.refreshRowsIncremental(delta.changed_sectors)
    }

    this.unsubStore = hotStore.subscribe(checkAndRefresh)
    this.unsubUi = uiStore.subscribe(checkAndRefresh)
  }

  /* ── connectedCallback (mount) ── */

  connectedCallback(): void {
    this._mounted = true
    this.searchTerm = ''
    this.sectorSearchTerm = ''
    this.currentMatchedCodes = null
    this.currentMatchedSectors = null
    this.rowCache = new Map()

    // 호스트 엘리먼트를 block + height:100%로 설정 (Custom Element 기본 display:inline 방지).
    // display:inline이면 Shadow DOM 내부 rootEl의 height:100%가 부모 높이를 참조하지 못해
    // 가상스크롤 컨테이너가 패널 전체 높이 대신 min-height 기반 작은 영역만 확보 →
    // 기동 직후 컨테이너 높이 불안정 상태로 가시 범위 계산이 부정확해 행 겹침 발생.
    // block + height:100%로 높이 체인(tripleRight → host → rootEl → scrollContainer) 완성.
    this.style.display = 'block'
    this.style.height = '100%'

    this.rootEl = document.createElement('div')
    Object.assign(this.rootEl.style, { display: 'flex', flexDirection: 'column', height: '100%', contain: 'content' })

    // Shadow DOM은 외부 전역 CSS(::-webkit-scrollbar in index.html)가 내부로 전달되지 않으므로,
    // 동일 스크롤바 스타일을 Shadow DOM 내부에 주입 (P23 일관성 — 다른 페이지와 동일 스크롤바).
    const scrollbarStyle = document.createElement('style')
    scrollbarStyle.textContent = `
      ::-webkit-scrollbar { width: 8px; height: 8px; }
      ::-webkit-scrollbar-thumb { background: #e5e5ea; border-radius: 4px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb:hover { background: #d1d1d6; }
    `
    this.shadow.appendChild(scrollbarStyle)

    // 1. 카드 타이틀 — 좌측 정렬 (다른 패널과 동일)
    this.titleH3 = createCardTitle('업종별 종목 실시간 시세')
    this.rootEl.appendChild(this.titleH3)
    this.refreshStatus = createPageRefreshStatus()
    this.rootEl.appendChild(this.refreshStatus.el)
    this.refreshStatus.set('업종 데이터 수신 중')

    // 1-1. 합계 정보 바 — 1행: 좌측 5거래일 평균 거래대금, 우측 종목수 요약
    this.rootEl.appendChild(this.buildSummaryBar())

    // 2. 선택된 업종 필터 배지
    this.rootEl.appendChild(this.buildFilterBadge())

    // 2-1. NXT 전용 시간대 안내 배지 (P21 투명성)
    this.rootEl.appendChild(this.buildNxtNoticeBadge())

    // 3. 검색 입력란 (좌: 종목명/코드, 우: 업종명)
    this.rootEl.appendChild(this.buildSearchRow())

    // 5-7. 빈 상태 메시지 + 스크롤 컨테이너 + DataTable
    const { empty, scroll } = this.buildEmptyAndScroll()
    this.rootEl.appendChild(empty)
    this.rootEl.appendChild(scroll)
    this.shadow.appendChild(this.rootEl)

    // 초기 데이터 — updateItems(동기)로 즉시 렌더.
    // updateRows(rAF 지연)를 쓰면 가상스크롤러 initialRender rAF가 먼저 발화해
    // items=[] 상태로 no-op이 된 뒤 데이터가 늦게 반영되어 기동 직후 행 겹침 유발.
    // updateItems는 internalUpdate를 동기 호출해 가상스크롤러 items를 즉시 설정 →
    // initialRender rAF 발화 시 정확한 가시 범위 계산. 이후 store listener 갱신은
    // updateRows(rAF 배칭) 사용 — 초기 렌더만 동기 처리.
    const initialRows = this.buildRows()
    const mappedRows = mapRowsToTableRows(initialRows)
    if (this.dataTable && this.dataTable.updateItems) this.dataTable.updateItems(mappedRows)
    this.updateUI(initialRows)
    // rank 변동 감지 도구 생성 + 초기 업종별 순위 저장
    this.rankDetector = createRankChangeDetector()
    this.rankDetector.reset(hotStore.getState().sectorScores)

    // 공통 화면주기 갱신 도구 — 전체 갱신 경로를 화면 주기에 맞춰 실행 (delta 모드는 동기 유지).
    // 가운데 패널(sector-ranking-list.ts)과 같은 공통 도구 사용 — 두 패널이 같은 화면 주기에 갱신 (W4 정합성).
    // refreshRows 내부에서 rankDetector.reset 호출 — 콜백에서 별도 reset 불필요 (W12 중복 제거).
    this.renderScheduler = createFrameScheduler(() => {
      this.refreshRows()
    })

    // Store 구독
    this.setupSubscriptions()

    // 구독 전에 store 갱신 리스너를 연결해 초기 스냅샷 수신과 화면 렌더 사이의 경주를 방지한다.
    notifyPageActive('sector-ranking')

    // O(1) 초저지연 DOM 갱신 이벤트 리스너
    this.setupTickListener()
  }

  /** O(1) 초저지연 DOM 갱신 이벤트 리스너 등록 */
  private setupTickListener(): void {
    this.onRealDataTick = (e: Event) => {
      try {
        const code = (e as CustomEvent<string>).detail
        if (this.dataTable && this.dataTable.updateItemByKey) {
          this.dataTable.updateItemByKey(code)
        }
      } catch (err) {
        console.error('[sector-stock] real-data-tick error', err)
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
    if (this.renderScheduler) { this.renderScheduler.destroy(); this.renderScheduler = null }
    if (this.unsubStore) { this.unsubStore(); this.unsubStore = null }
    if (this.unsubUi) { this.unsubUi(); this.unsubUi = null }
    if (this.dataTable) { this.dataTable.destroy(); this.dataTable = null }
    if (this.rootEl && this.rootEl.parentNode) this.rootEl.parentNode.removeChild(this.rootEl)
    this.rootEl = null
    this.titleH3 = null
    this.marketCountRow = null
    this.filterBadge = null
    this.nxtOnlyNoticeBadge = null
    this.refreshStatus = null
    this.emptyDiv = null
    this.scrollContainer = null
    this.searchInput = null
    this.sectorSearchInput = null
    this.rowCache = new Map()
    this.currentMatchedCodes = null
    this.currentMatchedSectors = null
    this.rankDetector = null
    this.searchTerm = ''
    this.sectorSearchTerm = ''
  }
}

/* ── Custom Element 등록 ── */

customElements.define('sector-stock-table', SectorStockTable)
