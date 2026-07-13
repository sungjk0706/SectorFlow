// frontend/src/pages/buy-target.ts
// 매수후보 페이지 — DataTable 적용

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { hotStore } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createCardTitle } from '../components/common/card-title'
import { createSearchInput } from '../components/common/search-input'
import { globalSettingsManager } from '../settings'
import { createStockNameColumn, createSeqCell, makeCodeColumn, makeChangeColumn, makeRateColumn, makeStrengthColumn, createAmountCell, createPriceCell, createNumberCell, FONT_SIZE, FONT_WEIGHT, COLOR } from '../components/common/ui-styles'
import { createBadgeRow, createBadge, updateBadge, type BadgeHandle, type BadgeStatus } from '../components/common/badge'
import { filterStocksBySearch } from './sector-stock'
import type { SectorStock } from '../types'

/* ── ColumnDef 배열 (13개 컬럼) ── */
const COLUMNS: ColumnDef<SectorStock>[] = [
  { key: 'seq', label: '순번', align: 'center', minWidth: 36, maxWidth: 36, render: (_t, idx) => createSeqCell(idx + 1) },
  makeCodeColumn<SectorStock>((t) => t.code),
  createStockNameColumn<SectorStock>(
    (t: SectorStock) => ({
      name: t.name,
      market_type: t.market_type,
      nxt_enable: t.nxt_enable
    })
  ),
  {
    key: 'cur_price', label: '현재가', align: 'right', flash: true, minWidth: 78, maxWidth: 90,
    render: (t) => {
      const cell = createPriceCell(t.cur_price != null ? Number(t.cur_price) : null, t.change_rate != null ? Number(t.change_rate) : null)
      if (t.high_5d && t.high_5d > 0 && t.cur_price != null && Number(t.cur_price) > t.high_5d) {
        cell.style.justifyContent = 'space-between'
        const icon = document.createElement('span')
        icon.textContent = '▲'
        icon.style.color = COLOR.up
        icon.style.fontSize = FONT_SIZE.body
        icon.style.fontWeight = FONT_WEIGHT.bold
        cell.insertBefore(icon, cell.firstChild)
      }
      return cell
    },
  },
  makeChangeColumn<SectorStock>((t) => t.change != null ? Number(t.change) : null),
  makeRateColumn<SectorStock>((t) => t.change_rate != null ? Number(t.change_rate) : null),
  makeStrengthColumn<SectorStock>((t) => t.strength != null ? parseFloat(String(t.strength)) : null),
  {
    key: 'trade_amount', label: '거래대금(억)', align: 'right', minWidth: 72, maxWidth: 85,
    render: (t) => {
      const cell = createAmountCell(t.trade_amount != null ? Number(t.trade_amount) : null)
      if (t.trade_amount_rank === 0) {
        cell.style.backgroundColor = COLOR.successBg
      }
      return cell
    },
  },
  {
    key: 'order_ratio', label: '호가잔량비', align: 'right', minWidth: 85, maxWidth: 100,
    render: (t) => {
      if (!t.order_ratio) return ''
      const [bid, ask] = t.order_ratio
      if (bid <= 0 && ask <= 0) return ''
      const span = document.createElement('span')
      if (bid === ask) {
        span.textContent = '100.0%'
        span.style.color = COLOR.tertiary
      } else if (bid > ask) {
        span.textContent = `[매수] ${((bid / ask) * 100).toFixed(1)}%`
        span.style.color = COLOR.up
      } else {
        span.textContent = `[매도] ${((ask / bid) * 100).toFixed(1)}%`
        span.style.color = COLOR.down
      }
      return span
    },
  },
  {
    key: 'program_net_buy', label: '프순매', align: 'right', minWidth: 68, maxWidth: 80,
    render: (t) => {
      if (t.program_net_buy === undefined || t.program_net_buy === null) return ''
      // tval이 금액(원)이라면 백만 원 단위로 환산, LS증권 대금 포맷을 고려하여 백만 단위로 나눈 후 1자리 소수점 표시
      const valMillions = t.program_net_buy / 1000000;
      const span = document.createElement('span')
      // 1자리 소수점 및 콤마 포맷 (Intl.NumberFormat 사용)
      const formatter = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
      span.textContent = formatter.format(valMillions);
      if (t.program_net_buy > 0) {
        span.style.color = COLOR.up
      } else if (t.program_net_buy < 0) {
        span.style.color = COLOR.down
      } else {
        span.style.color = COLOR.tertiary
      }
      return span
    },
  },
  {
    key: 'high_5d', label: '5일고가', align: 'right', minWidth: 68, maxWidth: 80,
    render: (t) => {
      const cell = createNumberCell(Number(t.high_5d) || 0)
      if (t.high_5d && t.high_5d > 0 && t.cur_price != null && Number(t.cur_price) > t.high_5d) {
        cell.style.backgroundColor = COLOR.successBg
      }
      return cell
    },
  },
  {
    key: 'boost_score', label: '가산점', align: 'right', minWidth: 52, maxWidth: 60,
    render: (t) => {
      const bs = Number(t.boost_score) || 0
      return bs > 0 ? bs.toFixed(1) : ''
    },
  },
  {
    key: 'guard', label: '제한', align: 'center', minWidth: 48, maxWidth: 52,
    render: (t) => {
      const span = document.createElement('span')
      span.textContent = t.guard_pass ? '통과' : '차단'
      span.style.color = t.guard_pass ? COLOR.success : COLOR.up
      return span
    },
  },
  {
    key: 'reason', label: '원인', align: 'left', minWidth: 60, maxWidth: 90,
    cellStyle: { color: COLOR.tertiary },
    render: (t) => {
      const r = t.reason || ''
      if (r === '보유중' || r === '금일매수') {
        const span = document.createElement('span')
        span.textContent = r
        span.style.color = COLOR.warning
        span.style.fontWeight = '600'
        return span
      }
      return r
    },
  },
]

/* ── 모듈 변수 ── */
let dataTable: DataTableApi<SectorStock> | null = null
let badgeEls: { orderable: BadgeHandle; daily: BadgeHandle; holding: BadgeHandle } | null = null
let emptyEl: HTMLElement | null = null
let searchInput: ReturnType<typeof createSearchInput> | null = null
let searchTerm = ''
let unsubTargets: (() => void) | null = null
let unsubUiStore: (() => void) | null = null
let rafHandle: number | null = null
let onRealDataTick: ((e: Event) => void) | null = null
let onOrderbookTick: ((e: Event) => void) | null = null
let onProgramTick: ((e: Event) => void) | null = null
let _mounted = false

/* ── 배지 행 업데이트 — DOM 재구성 없이 textContent만 갱신 ── */
function updateBadges(): void {
  if (!badgeEls) return
  const state = hotStore.getState()
  const uiState = uiStore.getState()
  const settings = globalSettingsManager.getSettings()
  const maxDailyOn = !!settings?.max_daily_total_buy_on
  const maxDaily = (maxDailyOn ? (settings?.max_daily_total_buy_amt ?? 0) : 0)
  const maxStockOn = !!settings?.max_stock_cnt_on
  const maxStock = settings?.max_stock_cnt ?? 5
  const buyAmtOn = !!settings?.buy_amt_on
  const buyAmtPerStock = settings?.buy_amt ?? 0
  const holdingCnt = state.positions.filter(p => (p.qty ?? 0) > 0).length
  const dailySpent = uiState.buyLimitStatus.daily_buy_spent
  const orderable = state.account?.orderable ?? 0

  // 1순위 통과 종목 — 주문가능금액 배지의 1위 종목 매수 가능 수량 계산용
  const topTarget = [...state.buyTargets].sort((a, b) => {
    if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
    return (a.rank ?? 999999) - (b.rank ?? 999999)
  }).find(t => t.guard_pass && t.reason === '')

  // 백엔드 trading.py와 동일 — buy_amt_on=False 시 종목당 한도 없음 (주문가능 금액이 상한)
  const dailyRemain = maxDaily > 0 ? Math.max(0, maxDaily - dailySpent) : Infinity
  let effectiveBuyAmt: number
  if (buyAmtOn && buyAmtPerStock > 0) {
    effectiveBuyAmt = Math.min(buyAmtPerStock, dailyRemain, orderable)
  } else if (buyAmtOn) {
    effectiveBuyAmt = 0  // buy_amt_on=True but buy_amt=0 → 매수 불가
  } else {
    effectiveBuyAmt = Math.min(dailyRemain, orderable)  // 한도 없음
  }
  let qty = 0
  if (topTarget && effectiveBuyAmt > 0 && topTarget.cur_price > 0) {
    qty = Math.floor(effectiveBuyAmt / topTarget.cur_price)
  }
  const topName = topTarget?.name ?? ''

  // 주문가능금액 배지 — 값 + 1위 종목 정보
  const insufficient = orderable <= 0
  const cannotBuy = !insufficient && topName !== '' && qty <= 0
  const orderableStatus: BadgeStatus = (insufficient || cannotBuy) ? 'warn' : 'normal'
  let orderableStatusText = ''
  if (topName !== '') {
    orderableStatusText = cannotBuy
      ? ` (1위 ${topName} ${qty}주 ⚠️ 매수 불가)`
      : ` (1위 ${topName} ${qty}주)`
  } else if (insufficient) {
    orderableStatusText = ' (매수 불가)'
  }
  updateBadge(badgeEls.orderable, orderable.toLocaleString(), {
    status: orderableStatus,
    statusText: orderableStatusText,
    statusColor: (insufficient || cannotBuy) ? COLOR.up : COLOR.code,
  })

  // 일일 매수 금액 배지 — cur / max
  const dailyHit = maxDaily > 0 && dailySpent >= maxDaily
  const dailyNear = maxDaily > 0 && dailySpent >= maxDaily * 0.8 && dailySpent < maxDaily
  const dailyStatus: BadgeStatus = dailyHit ? 'hit' : dailyNear ? 'near' : 'normal'
  const dailyValue = `${dailySpent.toLocaleString()} / ${maxDaily > 0 ? maxDaily.toLocaleString() : '무제한'}`
  const dailyStatusText = dailyHit ? ' (한도)' : dailyNear ? ' (근접)' : ''
  updateBadge(badgeEls.daily, dailyValue, {
    status: dailyStatus,
    statusText: dailyStatusText,
    statusColor: dailyHit ? COLOR.up : dailyNear ? COLOR.warning : COLOR.code,
  })

  // 동시 보유 종목 배지 — cur / max (maxStockOn=False 시 무제한)
  const effectiveMaxStock = maxStockOn ? maxStock : 0  // 0 = 무제한 표시
  const holdingHit = effectiveMaxStock > 0 && holdingCnt >= effectiveMaxStock
  const holdingNear = effectiveMaxStock > 0 && holdingCnt >= effectiveMaxStock * 0.8 && holdingCnt < effectiveMaxStock
  const holdingStatus: BadgeStatus = holdingHit ? 'hit' : holdingNear ? 'near' : 'normal'
  const holdingValue = `${holdingCnt.toLocaleString()} / ${effectiveMaxStock > 0 ? effectiveMaxStock.toLocaleString() : '무제한'}`
  const holdingStatusText = holdingHit ? ' (한도)' : holdingNear ? ' (근접)' : ''
  updateBadge(badgeEls.holding, holdingValue, {
    status: holdingStatus,
    statusText: holdingStatusText,
    statusColor: holdingHit ? COLOR.up : holdingNear ? COLOR.warning : COLOR.code,
  })
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  notifyPageActive('buy-target')
  const initState = hotStore.getState()
  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  // 헤더: 제목
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '4px',
  })
  headerRow.appendChild(createCardTitle('매수후보'))
  root.appendChild(headerRow)

  // 한도 배지 행 — 공통 컴포넌트 (flex 3등분 고정)
  const badgeRow = createBadgeRow()
  const orderableBadge = createBadge('💳 주문가능금액', '원')
  const dailyBadge = createBadge('💰 일일 매수 금액 (수수료 제외)', '원')
  const holdingBadge = createBadge('📦 동시 보유 종목 최대', '종목')
  badgeRow.appendChild(orderableBadge.el)
  badgeRow.appendChild(dailyBadge.el)
  badgeRow.appendChild(holdingBadge.el)
  badgeEls = { orderable: orderableBadge, daily: dailyBadge, holding: holdingBadge }
  root.appendChild(badgeRow)

  // 검색 입력란 — 테이블 좌측 상단, 주문가능금액 배지 하단 (업종별 종목 시세와 동일한 패턴)
  const searchRow = document.createElement('div')
  Object.assign(searchRow.style, {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    marginBottom: '4px',
  })

  searchInput = createSearchInput({
    label: '종목명/코드',
    labelColor: COLOR.down,
    placeholder: '종목명/코드 검색',
    borderColor: COLOR.down,
    onSearch: (query) => {
      searchTerm = query
      scheduleRender()
    },
  })
  searchRow.appendChild(searchInput.el)
  root.appendChild(searchRow)

  // 스크롤 컨테이너
  const scrollContainer = document.createElement('div')
  Object.assign(scrollContainer.style, { flex: '1', minHeight: '200px', display: 'flex', flexDirection: 'column', overflowY: 'auto' })

  // DataTable 생성
  dataTable = createDataTable<SectorStock>({
    columns: COLUMNS,
    virtualScroll: true,
    keyFn: (t) => t.code,
    emptyText: '매수후보가 없습니다.',
    stickyHeader: true,
    rowHeight: 32,
    rowStyle: (_row, _idx) => searchTerm
      ? { background: COLOR.downBg }
      : { background: '' },
  })

  // 빈 상태 메시지 (DataTable 외부 — 기존 동작 유지)
  emptyEl = document.createElement('div')
  Object.assign(emptyEl.style, { color: COLOR.disabled, padding: '20px 0', textAlign: 'center', fontSize: FONT_SIZE.badge, display: 'none' })
  emptyEl.textContent = '매수후보가 없습니다.'

  scrollContainer.appendChild(dataTable.el)
  scrollContainer.appendChild(emptyEl)
  root.appendChild(scrollContainer)
  container.appendChild(root)

  // 초기 데이터 — 검색 필터링 적용 (SSOT: filterStocksBySearch 재사용)
  const initialMatched = filterStocksBySearch(initState.buyTargets, searchTerm)
  const initialTargets = [...initState.buyTargets]
    .filter(t => !initialMatched || initialMatched.has(t.code))
    .sort((a, b) => {
      if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
      return (a.rank ?? 999999) - (b.rank ?? 999999)
    })
  updateBadges()

  dataTable.updateRows(initialTargets)
  if (emptyEl) {
    emptyEl.style.display = initialTargets.length === 0 ? '' : 'none'
    emptyEl.textContent = searchTerm ? `'${searchTerm}' 검색 결과가 없습니다.` : '매수후보가 없습니다.'
  }

  // Store 구독 — rAF 배칭 + reference equality guard
  // 마지막 렌더링 시점의 참조 (rAF 콜백에서 갱신)
  let lastRenderedBuyTargets = initState.buyTargets
  let lastRenderedSearchTerm = searchTerm
  let lastRenderedPositions = initState.positions
  let lastRenderedAccount = initState.account
  let lastRenderedSettings = globalSettingsManager.getSettings()
  const initUiState = uiStore.getState()
  let lastRenderedBuyLimitStatus = initUiState.buyLimitStatus

  function scheduleRender(): void {
    const hotState = hotStore.getState()
    const uiState = uiStore.getState()
    const anyChanged =
      hotState.buyTargets !== lastRenderedBuyTargets ||
      hotState.positions !== lastRenderedPositions ||
      hotState.account !== lastRenderedAccount ||
      globalSettingsManager.getSettings() !== lastRenderedSettings ||
      uiState.buyLimitStatus !== lastRenderedBuyLimitStatus ||
      searchTerm !== lastRenderedSearchTerm

    if (!anyChanged) return

    // rAF 배칭: 이미 예약된 rAF가 있으면 추가 예약하지 않음
    // 콜백 실행 시 getState()로 최신 상태를 가져오므로 항상 최신 반영
    if (rafHandle !== null) return

    rafHandle = requestAnimationFrame(() => {
      rafHandle = null
      if (!_mounted) return
      const latest = hotStore.getState()
      const latestUi = uiStore.getState()

      // buyTargets 참조 또는 검색어 변경 시 필터링 + sort + updateRows
      const targetsChanged = latest.buyTargets !== lastRenderedBuyTargets
      const searchChanged = searchTerm !== lastRenderedSearchTerm
      if (targetsChanged || searchChanged) {
        lastRenderedBuyTargets = latest.buyTargets
        lastRenderedSearchTerm = searchTerm
        // 필터링 (SSOT: filterStocksBySearch 재사용) → 정렬
        const matchedCodes = filterStocksBySearch(latest.buyTargets, searchTerm)
        const targets = [...latest.buyTargets]
          .filter(t => !matchedCodes || matchedCodes.has(t.code))
          .sort((a, b) => {
            if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
            return (a.rank ?? 999999) - (b.rank ?? 999999)
          })
        dataTable?.updateRows(targets)
        if (emptyEl) {
          emptyEl.style.display = targets.length === 0 ? '' : 'none'
          emptyEl.textContent = searchTerm ? `'${searchTerm}' 검색 결과가 없습니다.` : '매수후보가 없습니다.'
        }
      }

      // buyTargets / positions / account / settings / buyLimitStatus 변경 시 배지 업데이트
      if (
        targetsChanged ||
        latest.positions !== lastRenderedPositions ||
        latest.account !== lastRenderedAccount ||
        globalSettingsManager.getSettings() !== lastRenderedSettings ||
        latestUi.buyLimitStatus !== lastRenderedBuyLimitStatus
      ) {
        lastRenderedPositions = latest.positions
        lastRenderedAccount = latest.account
        lastRenderedSettings = globalSettingsManager.getSettings()
        lastRenderedBuyLimitStatus = latestUi.buyLimitStatus
        updateBadges()
      }
    })
  }

  unsubTargets = hotStore.subscribe(() => scheduleRender())
  unsubUiStore = uiStore.subscribe(() => scheduleRender())

  // O(1) 초저지연 DOM 갱신 이벤트 리스너
  onRealDataTick = (e: Event) => {
    const code = (e as CustomEvent<string>).detail
    if (dataTable && dataTable.updateItemByKey) {
      dataTable.updateItemByKey(code)
    }
  }
  window.addEventListener('real-data-tick', onRealDataTick)

  onOrderbookTick = (e: Event) => {
    const code = (e as CustomEvent<string>).detail
    if (dataTable && dataTable.updateItemByKey) {
      dataTable.updateItemByKey(code)
    }
  }
  window.addEventListener('orderbook-tick', onOrderbookTick)

  onProgramTick = (e: Event) => {
    const code = (e as CustomEvent<string>).detail
    if (dataTable && dataTable.updateItemByKey) {
      dataTable.updateItemByKey(code)
    }
  }
  window.addEventListener('program-tick', onProgramTick)
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  notifyPageInactive('buy-target')
  if (onRealDataTick) {
    window.removeEventListener('real-data-tick', onRealDataTick)
    onRealDataTick = null
  }
  if (onOrderbookTick) {
    window.removeEventListener('orderbook-tick', onOrderbookTick)
    onOrderbookTick = null
  }
  if (onProgramTick) {
    window.removeEventListener('program-tick', onProgramTick)
    onProgramTick = null
  }
  if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
  if (unsubTargets) { unsubTargets(); unsubTargets = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (dataTable) { dataTable.destroy(); dataTable = null }
  badgeEls = null
  emptyEl = null
  searchInput = null
  searchTerm = ''
}

export default { mount, unmount }
