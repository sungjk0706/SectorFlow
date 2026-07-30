// frontend/src/pages/buy-target.ts
// 매수후보 페이지 — DataTable 적용

import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { hotStore } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createCardHeaderWithMargin } from '../components/common/card-header'
import { createSearchInput } from '../components/common/search-input'
import { globalSettingsManager } from '../settings'
import { FONT_SIZE, COLOR } from '../components/common/ui-styles'
import { createBadgeRow, createBadge, updateBadge, type BadgeHandle, type BadgeStatus } from '../components/common/badge'
import { computeOrderBlockStatus } from '../utils/order-block-status'
import { filterStocksBySearch } from '../utils/stock-search'
import { COLUMNS } from './buy-target-columns'
import type { StockScore, AppSettings } from '../types'
import type { UIState } from '../stores/uiStore'
import type { HotState } from '../stores/hotStore'

/* ── 모듈 변수 ── */
let dataTable: DataTableApi<StockScore> | null = null
let badgeEls: { combined: BadgeHandle; daily: BadgeHandle; holding: BadgeHandle } | null = null
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

/* ── 렌더링 참조 상태 — scheduleRender 참조 비교용 (mount 시 초기화, unmount 시 reset)
 *    UIState/HotState 필드 타입을 직접 참조하여 SSOT 유지 (P10) ── */
let _rsBuyTargets: HotState['buyTargets'] = []
let _rsSearchTerm = ''
let _rsPositions: HotState['positions'] = []
let _rsAccount: HotState['account'] = null
let _rsSettings: AppSettings | null = null
let _rsBuyLimitStatus: UIState['buyLimitStatus'] = { daily_buy_spent: 0 }
let _rsCircuitBreaker: UIState['circuitBreakerOpen'] = null
let _rsOrderTimeBlocked: UIState['orderTimeBlocked'] = null
let _rsRiskBlockStatus: UIState['riskBlockStatus'] = null
let _rsRealtimeLatency: UIState['realtimeLatencyExceeded'] = false
let _rsDailyBuyStateFailed: UIState['dailyBuyStateFailed'] = false

/* ── 배지 컨텍스트 — updateBadges 공통 조회 (P24 단순성 — 분할) ── */

/** 매수후보 정렬 comparator — guard_pass 통과 우선, 동일 그룹 내 rank 오름차순.
 *  computeBadgeContext(1위 종목 찾기)와 renderTableRows(전체 정렬) 공통 (P24 중복 제거). */
function compareBuyTargets(a: StockScore, b: StockScore): number {
  if (a.guard_pass !== b.guard_pass) return a.guard_pass ? -1 : 1
  return (a.rank ?? 999999) - (b.rank ?? 999999)
}

interface BadgeContext {
  uiState: UIState
  settings: AppSettings | null
  maxDaily: number
  maxStock: number
  maxStockOn: boolean
  holdingCnt: number
  dailySpent: number
  orderable: number
  topName: string
  qty: number
}

/** 배지 갱신에 필요한 상태 조회 + 1위 종목 매수 가능 수량 계산 */
function computeBadgeContext(): BadgeContext {
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
  const topTarget = [...state.buyTargets].sort(compareBuyTargets).find(t => t.guard_pass && t.reject_reason === '')

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
  if (topTarget && effectiveBuyAmt > 0 && topTarget.cur_price != null && topTarget.cur_price > 0) {
    qty = Math.floor(effectiveBuyAmt / topTarget.cur_price)
  }
  const topName = topTarget?.name ?? ''

  return { uiState, settings, maxDaily, maxStock, maxStockOn, holdingCnt, dailySpent, orderable, topName, qty }
}

/** 통합 매수상태 배지 — 하드 게이트 > 소프트 차단(예산 부족) > 정상 (P21 모순 표시 제거)
 *  하드 게이트 판정은 computeOrderBlockStatus()에 위임 (P10 SSOT — sell-position.ts와 공유)
 *  소프트 차단(예산 부족)은 매수 후보 1위 종목 가격이 필요해 이곳에서 판정
 *    → computeOrderBlockStatus 시그니처 확장 불가 (sell-position은 매수 후보 없음)
 *    → 매수 전용 override를 이곳에 배치 (P23 일관성 예외 — 매수 후보 데이터 의존성) */
/** 통합 매수상태 판정 — 하드 게이트 > 소프트 차단(예산 부족) > 정상 (P21 모순 표시 제거)
 *  하드 게이트 판정은 computeOrderBlockStatus()에 위임 (P10 SSOT — sell-position.ts와 공유)
 *  소프트 차단(예산 부족)은 매수 후보 1위 종목 가격이 필요해 이곳에서 판정
 *    → computeOrderBlockStatus 시그니처 확장 불가 (sell-position은 매수 후보 없음)
 *    → 매수 전용 override를 이곳에 배치 (P23 일관성 예외 — 매수 후보 데이터 의존성) */
function computeCombinedStatus(
  ctx: BadgeContext,
): { value: string; unit: string; statusText: string; status: BadgeStatus; statusColor: string } {
  const { uiState, settings, orderable, topName, qty } = ctx
  const insufficient = orderable <= 0
  const cannotBuy = !insufficient && topName !== '' && qty <= 0
  const base: { value: string; unit: string; statusText: string; status: BadgeStatus; statusColor: string } = {
    value: orderable.toLocaleString(),
    unit: '원',
    statusText: '',
    status: 'normal',
    statusColor: COLOR.down,
  }
  try {
    const { text: hardStatusText, blocked: hardBlocked } = computeOrderBlockStatus('buy', uiState, settings)
    if (hardBlocked) {
      // 위험/강제 차단 (서킷브레이커/리스크/자동매매 OFF 등) — 주문가능금액 숨기고 차단 사유 표시 (빨간색)
      return { value: '차단', unit: '', statusText: ` · ${hardStatusText.replace(/^차단: /, '')}`, status: 'warn', statusColor: COLOR.up }
    }
    if (hardStatusText !== '매수 가능') {
      // 정보 상태 (NXT만 가능 / 거래 시간 외) — 주문가능금액 유지 + 정보 텍스트 (파란색, P21 투명성)
      return { ...base, statusText: ` · ${hardStatusText}` }
    }
    if (insufficient) {
      // 소프트 차단 — 잔액 0
      return { ...base, statusText: ' · 매수 불가 (잔액 없음)', status: 'warn', statusColor: COLOR.up }
    }
    if (cannotBuy) {
      // 소프트 차단 — 잔여 예산으로 1주도 매수 불가 (백엔드 BUY_REJECT_QTY_ZERO와 동일 기준)
      return { ...base, statusText: ` · 매수 불가 (1위 ${topName} ${qty}주)`, status: 'warn', statusColor: COLOR.up }
    }
    if (topName !== '') {
      // 정상 — 1위 종목 매수 가능 수량 표시
      return { ...base, statusText: ` · 매수 가능 (1위 ${topName} ${qty}주)` }
    }
    // 매수 후보 없음 — 하드 게이트 통과 + 예산 있음 + 후보 없음
    return { ...base, statusText: ' · 매수 가능 (후보 없음)' }
  } catch (err) {
    console.error('[buy-target] combined badge status error', err)
    return { ...base, statusText: ' · 상태 판정 오류', status: 'warn', statusColor: COLOR.up }
  }
}

function updateCombinedBadge(ctx: BadgeContext, badge: BadgeHandle): void {
  const { value, unit, statusText, status, statusColor } = computeCombinedStatus(ctx)
  updateBadge(badge, value, { status, statusText, statusColor })
  // unit 슬롯은 하드 차단 시 빈 값으로 설정 (createBadge 시 '원' 고정이므로 갱신 필요)
  badge.unitEl.textContent = unit
}

/** 일일 매수 금액 배지 — cur / max */
function updateDailyBadge(ctx: BadgeContext, badge: BadgeHandle): void {
  const { maxDaily, dailySpent } = ctx
  const dailyHit = maxDaily > 0 && dailySpent >= maxDaily
  const dailyNear = maxDaily > 0 && dailySpent >= maxDaily * 0.8 && dailySpent < maxDaily
  const dailyStatus: BadgeStatus = dailyHit ? 'hit' : dailyNear ? 'near' : 'normal'
  const dailyValue = `${dailySpent.toLocaleString()} / ${maxDaily > 0 ? maxDaily.toLocaleString() : '무제한'}`
  const dailyStatusText = dailyHit ? ' (한도)' : dailyNear ? ' (근접)' : ''
  updateBadge(badge, dailyValue, {
    status: dailyStatus,
    statusText: dailyStatusText,
    statusColor: dailyHit ? COLOR.up : dailyNear ? COLOR.warning : COLOR.code,
  })
}

/** 동시 보유 종목 배지 — cur / max (maxStockOn=False 시 무제한) */
function updateHoldingBadge(ctx: BadgeContext, badge: BadgeHandle): void {
  const { maxStockOn, maxStock, holdingCnt } = ctx
  const effectiveMaxStock = maxStockOn ? maxStock : 0  // 0 = 무제한 표시
  const holdingHit = effectiveMaxStock > 0 && holdingCnt >= effectiveMaxStock
  const holdingNear = effectiveMaxStock > 0 && holdingCnt >= effectiveMaxStock * 0.8 && holdingCnt < effectiveMaxStock
  const holdingStatus: BadgeStatus = holdingHit ? 'hit' : holdingNear ? 'near' : 'normal'
  const holdingValue = `${holdingCnt.toLocaleString()} / ${effectiveMaxStock > 0 ? effectiveMaxStock.toLocaleString() : '무제한'}`
  const holdingStatusText = holdingHit ? ' (한도)' : holdingNear ? ' (근접)' : ''
  updateBadge(badge, holdingValue, {
    status: holdingStatus,
    statusText: holdingStatusText,
    statusColor: holdingHit ? COLOR.up : holdingNear ? COLOR.warning : COLOR.code,
  })
}

/* ── 배지 행 업데이트 — DOM 재구성 없이 textContent만 갱신 ── */
function updateBadges(): void {
  if (!badgeEls) return
  const ctx = computeBadgeContext()
  updateCombinedBadge(ctx, badgeEls.combined)
  updateDailyBadge(ctx, badgeEls.daily)
  updateHoldingBadge(ctx, badgeEls.holding)
}

/* ── DOM 빌더 — mount에서 호출 (P24 책임 분할, sector-stock.ts 동일 패턴 P23) ── */

/** 헤더 + 한도 배지 행 빌드 */
function buildHeader(root: HTMLElement): void {
  // 헤더: 제목 — 공통 컴포넌트 (sell-position.ts 동일 패턴, P23 일관성)
  const headerRow = createCardHeaderWithMargin('매수후보')
  root.appendChild(headerRow)

  // 한도 배지 행 — 공통 컴포넌트 (flex 3등분 고정)
  // 매수상태 배지 통합: 주문가능금액 + 매수상태 → 1개 (P21 모순 표시 제거, P24 중복 제거)
  // 매도 페이지(sell-position.ts)는 본질 다른 관심사(보유 종목 기반)라 통합 제외 — P23 일관성 위반 아님
  const badgeRow = createBadgeRow()
  const combinedBadge = createBadge('🚦 매수상태', '원')
  const dailyBadge = createBadge('💰 일일 매수', '원')
  const holdingBadge = createBadge('📦 보유 종목', '종목')
  badgeRow.appendChild(combinedBadge.el)
  badgeRow.appendChild(dailyBadge.el)
  badgeRow.appendChild(holdingBadge.el)
  badgeEls = { combined: combinedBadge, daily: dailyBadge, holding: holdingBadge }
  root.appendChild(badgeRow)
}

/** 검색 입력란 빌드 */
function buildSearchRow(root: HTMLElement): void {
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
}

/** 스크롤 컨테이너 + DataTable + 빈 상태 메시지 빌드 */
function buildTableArea(root: HTMLElement): void {
  // 스크롤 컨테이너
  const scrollContainer = document.createElement('div')
  Object.assign(scrollContainer.style, { flex: '1', minHeight: '200px', display: 'flex', flexDirection: 'column', overflowY: 'auto' })

  // DataTable 생성
  dataTable = createDataTable<StockScore>({
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
}

/* ── 렌더링 상태 관리 + rAF 배칭 — scheduleRender 참조 비교용 (P24 책임 분할) ── */

/** 렌더링 참조 상태 초기화 — mount 시 호출 */
function initRenderState(initHot: HotState, initUi: UIState): void {
  _rsBuyTargets = initHot.buyTargets
  _rsSearchTerm = searchTerm
  _rsPositions = initHot.positions
  _rsAccount = initHot.account
  _rsSettings = globalSettingsManager.getSettings()
  _rsBuyLimitStatus = initUi.buyLimitStatus
  _rsCircuitBreaker = initUi.circuitBreakerOpen
  _rsOrderTimeBlocked = initUi.orderTimeBlocked
  _rsRiskBlockStatus = initUi.riskBlockStatus
  _rsRealtimeLatency = initUi.realtimeLatencyExceeded
  _rsDailyBuyStateFailed = initUi.dailyBuyStateFailed
}

/** 렌더링 참조 상태 reset — unmount 시 호출 */
function resetRenderState(): void {
  _rsBuyTargets = []
  _rsSearchTerm = ''
  _rsPositions = []
  _rsAccount = null
  _rsSettings = null
  _rsBuyLimitStatus = { daily_buy_spent: 0 }
  _rsCircuitBreaker = null
  _rsOrderTimeBlocked = null
  _rsRiskBlockStatus = null
  _rsRealtimeLatency = false
  _rsDailyBuyStateFailed = false
}

/** 상태 변화 감지 — positions/account/settings/차단 상태 중 하나라도 변경 시 true */
function hasStateChanged(latest: HotState, latestUi: UIState): boolean {
  return (
    latest.positions !== _rsPositions ||
    latest.account !== _rsAccount ||
    globalSettingsManager.getSettings() !== _rsSettings ||
    latestUi.buyLimitStatus !== _rsBuyLimitStatus ||
    latestUi.circuitBreakerOpen !== _rsCircuitBreaker ||
    latestUi.orderTimeBlocked !== _rsOrderTimeBlocked ||
    latestUi.riskBlockStatus !== _rsRiskBlockStatus ||
    latestUi.realtimeLatencyExceeded !== _rsRealtimeLatency ||
    latestUi.dailyBuyStateFailed !== _rsDailyBuyStateFailed
  )
}

/** 테이블 행 렌더 — 필터링 + 정렬 + updateRows + 빈 상태 갱신 (초기 렌더 + rAF 콜백 공용) */
function renderTableRows(buyTargets: StockScore[]): void {
  // 필터링 (SSOT: filterStocksBySearch 재사용) → 정렬
  const matchedCodes = filterStocksBySearch(buyTargets, searchTerm)
  const targets = [...buyTargets]
    .filter(t => !matchedCodes || matchedCodes.has(t.code))
    .sort(compareBuyTargets)
  dataTable?.updateRows(targets)
  if (emptyEl) {
    emptyEl.style.display = targets.length === 0 ? '' : 'none'
    emptyEl.textContent = searchTerm ? `'${searchTerm}' 검색 결과가 없습니다.` : '매수후보가 없습니다.'
  }
}

/** rAF 콜백 — 최신 상태로 테이블 + 배지 갱신 */
function renderFrame(): void {
  rafHandle = null
  if (!_mounted) return
  const latest = hotStore.getState()
  const latestUi = uiStore.getState()

  // buyTargets 참조 또는 검색어 변경 시 필터링 + sort + updateRows
  const targetsChanged = latest.buyTargets !== _rsBuyTargets
  const searchChanged = searchTerm !== _rsSearchTerm
  if (targetsChanged || searchChanged) {
    _rsBuyTargets = latest.buyTargets
    _rsSearchTerm = searchTerm
    renderTableRows(latest.buyTargets)
  }

  // buyTargets / positions / account / settings / buyLimitStatus / 차단 상태 변경 시 배지 업데이트
  if (targetsChanged || hasStateChanged(latest, latestUi)) {
    _rsPositions = latest.positions
    _rsAccount = latest.account
    _rsSettings = globalSettingsManager.getSettings()
    _rsBuyLimitStatus = latestUi.buyLimitStatus
    _rsCircuitBreaker = latestUi.circuitBreakerOpen
    _rsOrderTimeBlocked = latestUi.orderTimeBlocked
    _rsRiskBlockStatus = latestUi.riskBlockStatus
    _rsRealtimeLatency = latestUi.realtimeLatencyExceeded
    _rsDailyBuyStateFailed = latestUi.dailyBuyStateFailed
    updateBadges()
  }
}

/** rAF 배칭 — 상태 변화 감지 후 단일 rAF 예약 */
function scheduleRender(): void {
  const hotState = hotStore.getState()
  const uiState = uiStore.getState()
  const targetsChanged = hotState.buyTargets !== _rsBuyTargets
  const searchChanged = searchTerm !== _rsSearchTerm
  if (!(targetsChanged || searchChanged || hasStateChanged(hotState, uiState))) return

  // rAF 배칭: 이미 예약된 rAF가 있으면 추가 예약하지 않음
  // 콜백 실행 시 getState()로 최신 상태를 가져오므로 항상 최신 반영
  if (rafHandle !== null) return
  rafHandle = requestAnimationFrame(renderFrame)
}

/** O(1) 초저지연 DOM 갱신 이벤트 리스너 등록 */
function setupTickListeners(): void {
  onRealDataTick = (e: Event) => {
    try {
      const code = (e as CustomEvent<string>).detail
      if (dataTable && dataTable.updateItemByKey) {
        dataTable.updateItemByKey(code)
      }
    } catch (err) {
      console.error('[buy-target] real-data-tick error', err)
    }
  }
  window.addEventListener('real-data-tick', onRealDataTick)

  onOrderbookTick = (e: Event) => {
    try {
      const code = (e as CustomEvent<string>).detail
      if (dataTable && dataTable.updateItemByKey) {
        dataTable.updateItemByKey(code)
      }
    } catch (err) {
      console.error('[buy-target] orderbook-tick error', err)
    }
  }
  window.addEventListener('orderbook-tick', onOrderbookTick)

  onProgramTick = (e: Event) => {
    try {
      const code = (e as CustomEvent<string>).detail
      if (dataTable && dataTable.updateItemByKey) {
        dataTable.updateItemByKey(code)
      }
    } catch (err) {
      console.error('[buy-target] program-tick error', err)
    }
  }
  window.addEventListener('program-tick', onProgramTick)
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  notifyPageActive('buy-target')
  const initState = hotStore.getState()
  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  buildHeader(root)
  buildSearchRow(root)
  buildTableArea(root)
  container.appendChild(root)

  // 초기 데이터 + 렌더링 상태 초기화
  initRenderState(initState, uiStore.getState())
  updateBadges()
  renderTableRows(initState.buyTargets)

  // Store 구독 — rAF 배칭 + reference equality guard
  unsubTargets = hotStore.subscribe(() => scheduleRender())
  unsubUiStore = uiStore.subscribe(() => scheduleRender())

  // O(1) 초저지연 DOM 갱신 이벤트 리스너
  setupTickListeners()
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
  resetRenderState()
}

export default { mount, unmount }
