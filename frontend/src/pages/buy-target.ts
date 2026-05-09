// frontend/src/pages/buy-target.ts
// 매수후보 페이지 — DataTable 적용

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { appStore } from '../stores/appStore'
import { createCardTitle } from '../components/common/card-title'
import { createWsStatusBadge } from '../components/common/setting-row'
import { createStockNameColumn, createSeqCell, makeCodeColumn, makePriceColumn, makeChangeColumn, makeRateColumn, makeStrengthColumn, createNumberCell, FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import type { BuyTarget } from '../types'

/* ── ColumnDef 배열 (12개 컬럼) ── */
const COLUMNS: ColumnDef<BuyTarget>[] = [
  { key: 'seq', label: '순번', align: 'center', render: (_t, idx) => createSeqCell(idx + 1) },
  makeCodeColumn<BuyTarget>((t) => t.code),
  createStockNameColumn<BuyTarget>(
    (t: BuyTarget) => ({
      name: t.name,
      market_type: t.market_type,
      nxt_enable: t.nxt_enable
    })
  ),
  makePriceColumn<BuyTarget>(
    (t) => Number(t.cur_price) || 0,
    (t) => Number(t.change_rate) || 0,
  ),
  makeChangeColumn<BuyTarget>((t) => Number(t.change) || 0),
  makeRateColumn<BuyTarget>((t) => Number(t.change_rate) || 0),
  makeStrengthColumn<BuyTarget>((t) => Number(t.strength)),
  {
    key: 'order_ratio', label: '호가잔량비', align: 'right',
    cellStyle: { fontSize: FONT_SIZE.badge },
    render: (t) => {
      if (!t.order_ratio) return ''
      const [bid, ask] = t.order_ratio
      if (bid <= 0 && ask <= 0) return ''
      const span = document.createElement('span')
      if (bid === ask) {
        span.textContent = '1.00'
        span.style.color = '#888'
      } else if (bid > ask) {
        span.textContent = `매수×${(bid / ask).toFixed(2)}`
        span.style.color = '#0d6efd'
      } else {
        span.textContent = `매도×${(ask / bid).toFixed(2)}`
        span.style.color = '#dc3545'
      }
      return span
    },
  },
  {
    key: 'high_5d', label: '5일고가', align: 'right',
    render: (t) => createNumberCell(Number(t.high_5d) || 0),
  },
  {
    key: 'boost_score', label: '가산점', align: 'right',
    cellStyle: { fontSize: FONT_SIZE.badge },
    render: (t) => {
      const bs = Number(t.boost_score) || 0
      return bs > 0 ? bs.toFixed(1) : ''
    },
  },
  {
    key: 'guard', label: '제한', align: 'center',
    render: (t) => {
      const span = document.createElement('span')
      span.textContent = t.guard_pass ? '통과' : '차단'
      span.style.color = t.guard_pass ? '#198754' : '#dc3545'
      return span
    },
  },
  {
    key: 'reason', label: '원인', align: 'left', minWidth: 60,
    cellStyle: { color: '#666' },
    render: (t) => {
      const r = t.reason || ''
      if (r === '보유중' || r === '금일매수') {
        const span = document.createElement('span')
        span.textContent = r
        span.style.color = '#e65100'
        span.style.fontWeight = '600'
        return span
      }
      return r
    },
  },
]

/* ── 모듈 변수 ── */
let dataTable: DataTableApi<BuyTarget> | null = null
let badgeEls: { daily: HTMLSpanElement; holding: HTMLSpanElement; perStock: HTMLSpanElement } | null = null
let wsBadge: ReturnType<typeof createWsStatusBadge> | null = null
let emptyEl: HTMLElement | null = null
let unsubTargets: (() => void) | null = null

/* ── 한도 배지 렌더링 ── */
function renderLimitBadge(el: HTMLSpanElement, label: string, cur: number, max: number, unit = '원'): void {
  const hit = max > 0 && cur >= max
  el.style.background = hit ? '#fdecea' : '#f5f5f5'
  el.style.color = hit ? '#dc3545' : '#555'
  el.style.fontWeight = hit ? FONT_WEIGHT.semibold : FONT_WEIGHT.normal
  el.textContent = `${label} ${cur.toLocaleString()}${unit} / ${max > 0 ? max.toLocaleString() + unit : '무제한'}${hit ? ' (한도)' : ''}`
}

function createBadgeSpan(): HTMLSpanElement {
  const span = document.createElement('span')
  Object.assign(span.style, { fontSize: FONT_SIZE.badge, padding: '3px 10px', borderRadius: '4px', marginRight: '6px' })
  return span
}

/* ── 배지 행 업데이트 ── */
function updateBadges(): void {
  if (!badgeEls) return
  const state = appStore.getState()
  const settings = state.settings
  const maxDaily = settings?.max_daily_total_buy_amt ?? 0
  const maxStock = settings?.max_stock_cnt ?? 5
  const buyAmtPerStock = settings?.buy_amt ?? 0
  const holdingCnt = state.positions.filter(p => (p.qty ?? 0) > 0).length
  const dailySpent = state.buyLimitStatus.daily_buy_spent

  renderLimitBadge(badgeEls.daily, '💰 일일 최대 매수 금액', dailySpent, maxDaily)
  renderLimitBadge(badgeEls.holding, '📦 동시 보유 종목 최대', holdingCnt, maxStock, '종목')

  // 종목당 일일 최대 매수 금액: 1순위 통과 종목 기준 매수 가능 수량 표시
  const dailyRemain = maxDaily > 0 ? Math.max(0, maxDaily - dailySpent) : Infinity
  const effectiveBuyAmt = buyAmtPerStock > 0 ? Math.min(buyAmtPerStock, dailyRemain) : 0
  const topTarget = state.buyTargets.find(t => t.guard_pass && t.reason === '')
  let perStockText = `🏷️ 종목당 매수 최대 금액 ${buyAmtPerStock > 0 ? buyAmtPerStock.toLocaleString() + '원' : '미설정'}`
  let perStockLimited = false
  if (topTarget && effectiveBuyAmt > 0 && topTarget.cur_price > 0) {
    const qty = Math.floor(effectiveBuyAmt / topTarget.cur_price)
    if (dailyRemain < buyAmtPerStock) {
      perStockText += ` (1위 ${topTarget.name} ${qty}주 ⚠️)`
      perStockLimited = true
    } else {
      perStockText += ` (1위 ${topTarget.name} ${qty}주)`
    }
  }
  badgeEls.perStock.style.background = perStockLimited ? '#fff3e0' : '#f5f5f5'
  badgeEls.perStock.style.color = perStockLimited ? '#e65100' : '#555'
  badgeEls.perStock.style.fontWeight = perStockLimited ? FONT_WEIGHT.semibold : FONT_WEIGHT.normal
  badgeEls.perStock.textContent = perStockText
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  // 헤더: 제목 + WS 상태 배지
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' })
  headerRow.appendChild(createCardTitle('매수후보'))

  const initState = appStore.getState()
  const subscribed = initState.wsSubscribeStatus.quote_subscribed
  wsBadge = createWsStatusBadge({
    subscribed,
    broker: 'kiwoom',
  })
  headerRow.appendChild(wsBadge.el)
  root.appendChild(headerRow)

  // 한도 배지 행
  const badgeRow = document.createElement('div')
  Object.assign(badgeRow.style, { marginBottom: '6px', lineHeight: '2' })
  const dailySpan = createBadgeSpan()
  const holdingSpan = createBadgeSpan()
  const perStockSpan = createBadgeSpan()
  badgeRow.appendChild(dailySpan)
  badgeRow.appendChild(holdingSpan)
  badgeRow.appendChild(perStockSpan)
  badgeEls = { daily: dailySpan, holding: holdingSpan, perStock: perStockSpan }
  root.appendChild(badgeRow)

  // 스크롤 컨테이너
  const scrollContainer = document.createElement('div')
  Object.assign(scrollContainer.style, { flex: '1', minHeight: '200px', display: 'flex', flexDirection: 'column' })

  // DataTable 생성
  dataTable = createDataTable<BuyTarget>({
    columns: COLUMNS,
    virtualScroll: true,
    keyFn: (t) => t.code,
    emptyText: '매수후보가 없습니다.',
    stickyHeader: true,
  })

  // 빈 상태 메시지 (DataTable 외부 — 기존 동작 유지)
  emptyEl = document.createElement('div')
  Object.assign(emptyEl.style, { color: '#aaa', padding: '20px 0', textAlign: 'center', fontSize: FONT_SIZE.badge, display: 'none' })
  emptyEl.textContent = '매수후보가 없습니다.'

  scrollContainer.appendChild(dataTable.el)
  scrollContainer.appendChild(emptyEl)
  root.appendChild(scrollContainer)
  container.appendChild(root)

  // 초기 데이터
  const initialTargets = [...initState.buyTargets].sort((a, b) => {
    if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
    return a.rank - b.rank
  })
  updateBadges()

  dataTable.updateRows(initialTargets)
  if (emptyEl) emptyEl.style.display = initialTargets.length === 0 ? '' : 'none'

  // Store 구독 — 선택적 구독 가드 (Bug 0 fix: buy-target interest keys only)
  {
    let prevBuyTargets = initState.buyTargets
    let prevPositions = initState.positions
    let prevSettings = initState.settings
    let prevWsSubscribeStatus = initState.wsSubscribeStatus
    let prevBuyLimitStatus = initState.buyLimitStatus

    unsubTargets = appStore.subscribe((state) => {
      const changed =
        state.buyTargets !== prevBuyTargets ||
        state.positions !== prevPositions ||
        state.settings !== prevSettings ||
        state.wsSubscribeStatus !== prevWsSubscribeStatus ||
        state.buyLimitStatus !== prevBuyLimitStatus

      prevBuyTargets = state.buyTargets
      prevPositions = state.positions
      prevSettings = state.settings
      prevWsSubscribeStatus = state.wsSubscribeStatus
      prevBuyLimitStatus = state.buyLimitStatus

      if (!changed) return

      const targets = [...state.buyTargets].sort((a, b) => {
        if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
        return a.rank - b.rank
      })
      dataTable?.updateRows(targets)
      if (emptyEl) emptyEl.style.display = targets.length === 0 ? '' : 'none'
      updateBadges()
      const q = state.wsSubscribeStatus.quote_subscribed
      wsBadge?.update(q, 'kiwoom')
    })
  }
}

/* ── unmount ── */
function unmount(): void {
  if (unsubTargets) { unsubTargets(); unsubTargets = null }
  if (dataTable) { dataTable.destroy(); dataTable = null }
  badgeEls = null
  wsBadge = null
  emptyEl = null
}

export default { mount, unmount }
