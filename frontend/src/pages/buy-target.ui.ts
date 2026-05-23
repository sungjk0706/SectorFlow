// frontend/src/pages/buy-target.ui.ts
// 매수후보 페이지 — 순수 UI 껍데기 (Dumb Component)
// 비즈니스 로직 제거, Props로 데이터 수신

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { createCardHeaderWithMargin } from '../components/common/card-header'
import { createGlobalWsBadge } from '../settings'
import { createStockNameColumn, createSeqCell, makeCodeColumn, makePriceColumn, makeChangeColumn, makeRateColumn, makeStrengthColumn, createNumberCell, FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import type { BuyTarget } from '../types'

// ── Props 타입 정의 ──

export interface BuyTargetProps {
  // 매수후보 데이터
  buyTargets: BuyTarget[]
  
  // 한도 상태
  dailyBuySpent: number
  maxDailyTotalBuyAmt: number
  holdingCnt: number
  maxStockCnt: number
  buyAmtPerStock: number
  topTarget: BuyTarget | null
  
  // 실시간 상태
  wsSubscribed: boolean
}

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
        span.textContent = `매수우세 ${(bid / ask).toFixed(2)}배`
        span.style.color = '#dc3545'
      } else {
        span.textContent = `매도우세 ${(ask / bid).toFixed(2)}배`
        span.style.color = '#0d6efd'
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

/* ── 컴포넌트 생성 함수 ── */

export function createBuyTargetCard(props: BuyTargetProps): { el: HTMLElement; update: (newProps: BuyTargetProps) => void; destroy: () => void } {
  let root: HTMLElement | null = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  let dataTable: DataTableApi<BuyTarget> | null = null
  let badgeEls: { daily: HTMLSpanElement; holding: HTMLSpanElement; perStock: HTMLSpanElement } | null = null
  let wsBadge: HTMLElement | null = null
  let emptyEl: HTMLElement | null = null

  // 헤더: 제목 + WS 상태 배지
  wsBadge = createGlobalWsBadge()
  const headerRow = createCardHeaderWithMargin('매수후보', wsBadge, '4px')
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

  // 초기 렌더링
  updateBadges(props)
  const initialTargets = [...props.buyTargets].sort((a, b) => {
    if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
    return a.rank - b.rank
  })
  dataTable.updateRows(initialTargets)
  if (emptyEl) emptyEl.style.display = initialTargets.length === 0 ? '' : 'none'

  // 배지 업데이트
  function updateBadges(p: BuyTargetProps): void {
    if (!badgeEls) return
    
    renderLimitBadge(badgeEls.daily, '💰 일일 최대 매수 금액', p.dailyBuySpent, p.maxDailyTotalBuyAmt)
    renderLimitBadge(badgeEls.holding, '📦 동시 보유 종목 최대', p.holdingCnt, p.maxStockCnt, '종목')

    // 종목당 일일 최대 매수 금액: 1순위 통과 종목 기준 매수 가능 수량 표시
    const dailyRemain = p.maxDailyTotalBuyAmt > 0 ? Math.max(0, p.maxDailyTotalBuyAmt - p.dailyBuySpent) : Infinity
    const effectiveBuyAmt = p.buyAmtPerStock > 0 ? Math.min(p.buyAmtPerStock, dailyRemain) : 0
    const topTarget = p.topTarget
    let perStockText = `🏷️ 종목당 매수 최대 금액 ${p.buyAmtPerStock > 0 ? p.buyAmtPerStock.toLocaleString() + '원' : '미설정'}`
    let perStockLimited = false
    if (topTarget && effectiveBuyAmt > 0 && topTarget.cur_price > 0) {
      const qty = Math.floor(effectiveBuyAmt / topTarget.cur_price)
      if (dailyRemain < p.buyAmtPerStock) {
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

  // Props 업데이트 함수
  function update(newProps: BuyTargetProps): void {
    Object.assign(props, newProps)
    
    // 한도 배지 업데이트
    updateBadges(props)
    
    // DataTable 업데이트
    const targets = [...props.buyTargets].sort((a, b) => {
      if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
      return a.rank - b.rank
    })
    dataTable?.updateRows(targets)
    if (emptyEl) emptyEl.style.display = targets.length === 0 ? '' : 'none'
  }

  // 파괴 함수
  function destroy(): void {
    if (dataTable) { dataTable.destroy(); dataTable = null }
    if (root && root.parentNode) root.parentNode.removeChild(root)
    root = null
    badgeEls = null
    wsBadge = null
    emptyEl = null
  }

  return { el: root, update, destroy }
}
