// frontend/src/pages/buy-target.ts
// 매수후보 페이지 — DataTable 적용

import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { virtualScrollOptions } from '../components/common/table-options'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import { applyAccountSnapshot, applyBuyTargetsSnapshot, applyPositionsSnapshot } from '../stores/hotStore'
import { refreshPageData, createPageRefreshStatus } from '../utils/page-refresh'
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
let pageDataReady = false
let refreshStatus: ReturnType<typeof createPageRefreshStatus> | null = null

async function refreshBuyTargetPage(): Promise<void> {
  const isActive = () => _mounted
  refreshStatus?.set('최신 데이터 확인 중')
  pageDataReady = false
  renderTableRows([])
  const results = await Promise.all([
    refreshPageData({
      key: 'buy-target:account', policy: 'always-fresh', isActive,
      fetcher: async () => api.getAccountSnapshot('buy-target'),
      apply: (response) => applyAccountSnapshot(response.data, response.freshness!),
    }),
    refreshPageData({
      key: 'buy-target:positions', policy: 'always-fresh', isActive,
      fetcher: async () => api.getAccountPositions('buy-target'),
      apply: (response) => applyPositionsSnapshot(response.data, response.freshness!),
    }),
    refreshPageData({
      key: 'buy-target:targets', policy: 'always-fresh', isActive,
      fetcher: async () => api.getBuyTargets('buy-target'),
      apply: (response) => applyBuyTargetsSnapshot(response.data, response.freshness!),
    }),
  ])
  if (!_mounted) return
  if (results.some(result => result.status === 'error')) {
    refreshStatus?.set('최신 데이터를 확인하지 못했습니다')
    return
  }
  pageDataReady = true
  refreshStatus?.set('', false)
  // sell-position.ts와 동일 패턴 — 성공 후 현재 store 값을 직접 렌더.
  // scheduleRender()만 호출하면 applyBuyTargetsUpdate의 same skip으로 참조가
  // 변경되지 않아 renderFrame의 targetsChanged=false가 되어 테이블이 빈 상태로 고정됨 (P16).
  const buyTargets = hotStore.getState().buyTargets
  renderTableRows(buyTargets)
}

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
  // 1위 종목 현재가는 masterStocks(실시간 시세 SSOT)에서 조회 — buyTargets에 실시간 필드 없음 (P10).
  const topCode = topTarget ? normalizeStockCode(topTarget.code) : ''
  const topPrice = topCode ? state.masterStocks[topCode]?.cur_price : undefined

  // 백엔드 trading.py와 동일 — buy_amt_on=False 시 종목당 1회 매수금액 없음 (주문가능 금액이 상한)
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
  if (topTarget && effectiveBuyAmt > 0 && topPrice != null && topPrice > 0) {
    qty = Math.floor(effectiveBuyAmt / topPrice)
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
): { value: string; unit: string; statusText: string; status: BadgeStatus; statusColor: string; valueColor?: string } {
  const { uiState, settings, orderable, topName, qty } = ctx
  const insufficient = orderable <= 0
  const cannotBuy = !insufficient && topName !== '' && qty <= 0
  const base: { value: string; unit: string; statusText: string; status: BadgeStatus; statusColor: string; valueColor?: string } = {
    value: orderable.toLocaleString(),
    unit: '원',
    statusText: '',
    status: 'normal',
    // 정상(매수 가능) — 헤더 칩 거래 가능 색과 동일 초록 (P23 일관성).
    statusColor: COLOR.success,
  }
  try {
    const { text: hardStatusText, blocked: hardBlocked, partial: hardPartial, holiday } =
      computeOrderBlockStatus('buy', uiState, settings)
    if (holiday) {
      // 휴장일 — 장 자체가 열리지 않으므로 주문가능금액 대신 휴장일 문구 표시.
      // 위험이 아니라 정보 상태이므로 헤더 휴장일 칩과 동일한 회색 표시 (P21/P23).
      return { value: hardStatusText, unit: '', statusText: '', status: 'normal', statusColor: COLOR.disabled, valueColor: COLOR.disabled }
    }
    if (hardBlocked) {
      // 위험/강제 차단 (서킷브레이커/리스크/자동매매 OFF 등) — 차단 범위와 사유를 화면에 표시 (빨간색)
      return { value: hardPartial ? '부분 차단' : '차단', unit: '', statusText: ` · ${hardStatusText.replace(/^차단: /, '')}`, status: 'warn', statusColor: COLOR.up }
    }
    if (hardStatusText !== '매수 가능') {
      // 정보 상태 (NXT만 가능 / 거래 시간 외) — 주문가능금액 유지 + 정보 텍스트 (파란색, P21 투명성).
      // 정상(초록)과 구분 — 부분 가능/시스템적 사실은 정보색 파랑 (P23 일관성).
      return { ...base, statusColor: COLOR.down, statusText: ` · ${hardStatusText}` }
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
  const { value, unit, statusText, status, statusColor, valueColor } = computeCombinedStatus(ctx)
  updateBadge(badge, value, { status, statusText, statusColor, valueColor })
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

/** 테이블 영역 + DataTable + 빈 상태 메시지 빌드 (단일 상자 — 이중 스크롤 제거, 결정 2) */
function buildTableArea(root: HTMLElement): void {
  // 단일 레이아웃 상자 — overflowY:auto 제거 (컴포넌트 내부 단일 스크롤)
  const tableWrap = document.createElement('div')
  Object.assign(tableWrap.style, { flex: '1', minHeight: '0', display: 'flex', flexDirection: 'column', overflow: 'hidden' })

  // DataTable 생성 (공통 옵션 헬퍼 — 결정 4)
  dataTable = createDataTable<StockScore>(
    virtualScrollOptions<StockScore>({
      columns: COLUMNS,
      keyFn: (t) => t.code,
      emptyText: '매수후보가 없습니다.',
      rowStyle: (_row, _idx) => searchTerm
        ? { background: COLOR.downBg }
        : { background: '' },
    }),
  )

  // 빈 상태 메시지 (DataTable 외부 — 기존 동작 유지)
  emptyEl = document.createElement('div')
  Object.assign(emptyEl.style, { color: COLOR.disabled, padding: '20px 0', textAlign: 'center', fontSize: FONT_SIZE.badge, display: 'none' })
  emptyEl.textContent = '매수후보가 없습니다.'

  tableWrap.appendChild(dataTable.el)
  tableWrap.appendChild(emptyEl)
  root.appendChild(tableWrap)
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
  if (!_mounted || !pageDataReady) return
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
  refreshStatus = createPageRefreshStatus()
  root.appendChild(refreshStatus.el)
  buildSearchRow(root)
  buildTableArea(root)
  container.appendChild(root)

  // 초기 데이터 + 렌더링 상태 초기화
  initRenderState(initState, uiStore.getState())
  // 최신 HTTP 스냅샷 확인 전에는 기존 hotStore 값을 화면에 노출하지 않는다.
  renderTableRows([])

  // Store 구독 — rAF 배칭 + reference equality guard
  unsubTargets = hotStore.subscribe(() => scheduleRender())
  unsubUiStore = uiStore.subscribe(() => scheduleRender())

  // O(1) 초저지연 DOM 갱신 이벤트 리스너
  setupTickListeners()
  void refreshBuyTargetPage()
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
  pageDataReady = false
  refreshStatus = null
}

export default { mount, unmount }
