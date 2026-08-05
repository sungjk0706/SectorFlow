// frontend/src/binding.ts — WS → Store 바인딩 (순수 TS, React 의존성 없음)
// WS 채널 분리: prices(시세), settings(설정/진행률), orders(체결)

import type { WSClient } from './api/ws'
import { getCurrentPage } from './api/ws'
import {
  applyAccountUpdate,
  applyAccountSummaryUpdate,
  applyRealData,
  applyBuyTargetsUpdate,
  applyBuyTargetsDelta,
  applyNewsHit,
  applyMasterStocksSnapshot,
  applyMasterStocksDelta,
  applyRealtimeReset,
  applySellHistoryUpdate,
  applyBuyHistoryUpdate,
  applyDailySummaryUpdate,
  applySectorScores,
  isFreshnessNewer,
  recordFreshness,
  hotStore,
  applyInitialSnapshotHot,
} from './stores/hotStore'
import {
  applySettingsChanged,
  applyAvgAmtProgress,
  applyTestDataResetCompleted,
  applyInitialSnapshotUI,
  applyWsSubscribeStatus,
  applyBuyLimitStatus,
  applyEngineReloadComplete,
  applyCircuitBreakerOpen,
  applyOrderTimeBlocked,
  applyRiskBlockStatus,
  applyRealtimeLatencyStatus,
  applyDailyBuyStateStatus,
  applyTestCashFailed,
  applyMarketPhase,
  applyIndexData,
  applyEngineStatus,
  uiStore,
  type ReceiveRateEntry,
} from './stores/uiStore'
import type {
  AccountUpdateEvent,
  AccountSummaryUpdateEvent,
  SettingsChangedEvent,
  MasterStock,
  StockScore,
  StockClassificationChangedEvent,
  RealDataEvent,
  SectorScoreRow,
  SectorScoresEvent,
  IndexData,
  EngineStatusPayload,
  NewsHitEvent,
} from './types'
import { applyStockClassificationChanged } from './stores/stockClassificationStore'
import { showToast } from './components/common/toast'

/**
 * WS 18개+ 이벤트 타입을 Store 액션에 바인딩한다.
 * 채널 분리: prices(시세), settings(설정/진행률), orders(체결)
 * main.ts에서 앱 초기화 시 1회 호출.
 */
export function bindWSToStore(
  pricesClient: WSClient,
  settingsClient: WSClient,
  ordersClient: WSClient
): void {
  /* ── prices 채널 연결 상태 콜백 ── */
  pricesClient.setConnectionCallbacks(
    () => {
      const page = getCurrentPage()
      if (page && page !== 'settings') pricesClient.send(JSON.stringify({ type: 'page-active', page }))
    },
    () => {},
  )

  /* ── prices 채널 기존 SSE 이벤트 핸들러 (WS로 통합) ── */
  pricesClient.onEvent('initial-snapshot', (data) => {
    applyInitialSnapshotHot(data as Record<string, unknown>)
    applyInitialSnapshotUI(data as Record<string, unknown>)
  })

  pricesClient.onEvent('account-update', (data) => {
    applyAccountUpdate(data as AccountUpdateEvent)
  })

  pricesClient.onEvent('account-summary-update', (data) => {
    applyAccountSummaryUpdate(data as AccountSummaryUpdateEvent)
  })


  pricesClient.onEvent('buy-targets-update', (data) => {
    applyBuyTargetsUpdate(data as { buy_targets: StockScore[]; freshness?: import('./types').FreshnessMetadata })
  })

  pricesClient.onEvent('master-cache-snapshot', (data) => {
    applyMasterStocksSnapshot(data as { stocks: MasterStock[]; freshness?: import('./types').FreshnessMetadata })
  })

  /* ── prices 채널 델타 이벤트 핸들러 (Phase 2 — 증분 갱신) ── */
  pricesClient.onEvent('master-cache-delta', (data) => {
    applyMasterStocksDelta(data as { code: string; fields: Partial<MasterStock> })
  })

  pricesClient.onEvent('buy-targets-delta', (data) => {
    applyBuyTargetsDelta(data as { added: StockScore[]; removed: string[]; changed: StockScore[]; freshness?: import('./types').FreshnessMetadata })
  })

  pricesClient.onEvent('buy-history-append', (data) => {
    const event = data as { trade: Record<string, unknown>; freshness?: import('./types').FreshnessMetadata }
    if (event.freshness && !isFreshnessNewer(event.freshness)) return
    if (event.freshness) recordFreshness(event.freshness)
    if (event.trade) {
      hotStore.setState((state) => ({ buyHistory: [event.trade, ...state.buyHistory] }))
    }
  })

  pricesClient.onEvent('real-data', (data) => {
    applyRealData(data as RealDataEvent)
  })

  /* ── settings 채널 연결 상태 콜백 ── */
  settingsClient.setConnectionCallbacks(
    () => {
      const page = getCurrentPage()
      if (page === 'settings') settingsClient.send(JSON.stringify({ type: 'page-active', page }))
    },
    () => {
    },
  )

  /* ── settings 채널 이벤트 핸들러 ── */
  settingsClient.onEvent('settings-changed', (data) => {
    applySettingsChanged(data as SettingsChangedEvent)
  })

  settingsClient.onEvent('engine-status', (data) => {
    applyEngineStatus(data as EngineStatusPayload)
  })

  settingsClient.onEvent('index-data', (data) => {
    applyIndexData(data as IndexData)
  })

  settingsClient.onEvent('daily-summary-update', (data) => {
    applyDailySummaryUpdate(data as { daily_summary: Record<string, unknown>[]; freshness?: import('./types').FreshnessMetadata })
  })


  /* ── orders 채널 이벤트 핸들러 ── */
  ordersClient.onEvent('test-data-reset-completed', () => {
    applyTestDataResetCompleted()
  })

  /* ── stock-classification-changed는 모든 채널에서 수신 가능하도록 prices 채널에 유지 ── */
  pricesClient.onEvent('stock-classification-changed', (data) => {
    applyStockClassificationChanged(data as StockClassificationChangedEvent)
  })

  /* ── 자료 중심 화면 초기 스냅샷 — 페이지 활성화 시 백엔드가 전송 (3세션).
   *    payload: { page, data: {...} } — data를 풀어 기존 변경 이벤트 apply 함수에 전달.
   *    stock-detail-snapshot은 종목 상세 페이지가 직접 수신 (페이지 로컬 자료). ── */
  pricesClient.onEvent('profit-detail-snapshot', (data) => {
    const payload = data as { page: string; data: { buy_history: Record<string, unknown>[]; sell_history: Record<string, unknown>[]; daily_summary: Record<string, unknown>[] } }
    applyBuyHistoryUpdate({ buy_history: payload.data.buy_history })
    applySellHistoryUpdate({ sell_history: payload.data.sell_history })
    applyDailySummaryUpdate({ daily_summary: payload.data.daily_summary })
  })

  pricesClient.onEvent('stock-classification-snapshot', (data) => {
    const payload = data as { page: string; data: StockClassificationChangedEvent }
    applyStockClassificationChanged(payload.data)
  })

  settingsClient.onEvent('settings-snapshot', (data) => {
    const payload = data as { page: string; data: SettingsChangedEvent }
    applySettingsChanged(payload.data)
  })

  pricesClient.onEvent('sell-history-append', (data) => {
    const event = data as { trade: Record<string, unknown>; daily_summary: Record<string, unknown>[]; freshness?: import('./types').FreshnessMetadata }
    if (event.freshness && !isFreshnessNewer(event.freshness)) return
    if (event.freshness) recordFreshness(event.freshness)
    const { trade, daily_summary } = event
    hotStore.setState((state) => {
      const patch: Partial<typeof state> = {}
      if (trade) patch.sellHistory = [trade, ...state.sellHistory]
      if (daily_summary) patch.dailySummary = daily_summary
      return patch
    })
  })

  pricesClient.onEvent('engine-ready', () => {
    applyEngineReloadComplete()
  })

  pricesClient.onEvent('confirmed-progress', (data) => {
    applyAvgAmtProgress(data as { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; failed_count?: number })
  })

  pricesClient.onEvent('sell-history-update', (data) => {
    applySellHistoryUpdate(data as { sell_history: Record<string, unknown>[]; freshness?: import('./types').FreshnessMetadata })
  })

  pricesClient.onEvent('buy-history-update', (data) => {
    applyBuyHistoryUpdate(data as { buy_history: Record<string, unknown>[]; freshness?: import('./types').FreshnessMetadata })
  })

  pricesClient.onEvent('realtime-reset', () => {
    applyRealtimeReset()
  })

  /* ── market-phase: 장 상태 실시간 갱신 ── */
  pricesClient.onEvent('market-phase', (data) => {
    applyMarketPhase(data as Partial<{
      krx: string;
      nxt: string;
      krx_alert: string | null;
      is_nxt_only: boolean;
      krx_countdown: { label: string; remaining_sec: number } | null;
      nxt_countdown: { label: string; remaining_sec: number } | null;
    }>)
  })

  /* ── receive-rate: 수신율 실시간 갱신 ── */
  // 3단계: 백엔드 KRX/NXT 분리 수신률 → 분리 매핑
  pricesClient.onEvent('receive-rate', (data) => {
    const d = data as {
      krx: ReceiveRateEntry
      nxt: ReceiveRateEntry
    }
    uiStore.setState({ receiveRate: { krx: d.krx, nxt: d.nxt } })
  })

  /* ── sector-scores: 업종순위 실시간 갱신 ── */
  pricesClient.onEvent('sector-scores', (data) => {
    const d = data as {
      scores?: SectorScoreRow[]
      changed_scores?: SectorScoreRow[]
      delta?: boolean
      changed_sectors?: string[]
      removed_sectors?: string[]
      status?: { waiting?: boolean } & Record<string, unknown>
    }
    applySectorScores(d as unknown as SectorScoresEvent)
    // sectorScoresDelta (uiStore) 갱신 + 수신 대기 상태 (P21 투명성)
    // sectorDataReady — 컬럼 폭 계산 게이트: waiting!==true 시 준비 완료, waiting===true 시 대기.
    // 초기 sectorScoresWaiting=false 기본값만으로 준비 완료로 판단하지 않고 실제 이벤트로만 전환.
    const waiting = d.status?.waiting === true
    uiStore.setState({
      sectorScoresDelta: d.delta
        ? { delta: true, changed_sectors: d.changed_sectors ?? [], removed_sectors: d.removed_sectors ?? [] }
        : null,
      sectorScoresWaiting: waiting,
      sectorDataReady: !waiting,
    })
    // receiveRate는 receive-rate 이벤트가 단일 소스(P10 SSOT) — sector-scores에서 중복 갱신 제거
  })

  /* ── ws-subscribe-status: 구독 상태 실시간 갱신 ── */
  pricesClient.onEvent('ws-subscribe-status', (data) => {
    applyWsSubscribeStatus(data as { index_subscribed: boolean; quote_subscribed: boolean })
  })

  /* ── circuit-breaker-open: OMS 서킷브레이커 발동 알림 ── */
  pricesClient.onEvent('circuit-breaker-open', (data) => {
    const d = data as { message?: string }
    applyCircuitBreakerOpen(d)
    showToast('error', d.message ?? '서킷브레이커 발동 — 자동매매 중지', 8000)
  })

  /* ── news-hit: 뉴스 호재 가산점 갱신 + 토스트 알림 (P10 단일 전달 경로, P21 투명성) ── */
  // 백엔드 _handle_nws_news()가 호재 매칭 시 news_boost를 본 이벤트로만 전달.
  // applyNewsHit이 해당 종목 news_boost만 patch (buy-targets-delta는 news_boost 제외, 세션 1).
  // 토스트로 사용자에게 즉시 알림 (P21). title 빈 문자열 시 기본 문구 (P20 명시적 값,
  // circuit-breaker-open의 `?? 기본문구` 패턴과 일관).
  pricesClient.onEvent('news-hit', (data) => {
    const d = data as NewsHitEvent
    applyNewsHit(d)
    showToast('info', d.title || '뉴스 호재 발생', 4000)
  })

  /* ── order-time-blocked: 체결 불가 시간대 주문 상태 (10초 주기) ── */
  pricesClient.onEvent('order-time-blocked', (data) => {
    applyOrderTimeBlocked(data as { level?: string; reason?: string })
  })

  /* ── risk-block-status: 리스크 매니저 차단 상태 (손실 한도 도달 등) ── */
  pricesClient.onEvent('risk-block-status', (data) => {
    applyRiskBlockStatus(data as { blocked?: boolean; side?: string; reason?: string; partial?: boolean })
  })

  /* ── buy-limit-status: 매수 한도 상태 실시간 갱신 ── */
  pricesClient.onEvent('buy-limit-status', (data) => {
    applyBuyLimitStatus(data as { daily_buy_spent: number })
  })

  /* ── realtime-latency-status: 실시간 통신 지연 200ms 초과 상태 (매수/매도 공통 차단) ── */
  pricesClient.onEvent('realtime-latency-status', (data) => {
    applyRealtimeLatencyStatus(data as { blocked?: boolean })
  })

  /* ── daily-buy-state-status: 일일 매수 상태 로드 실패 (매수 전용 차단) ── */
  pricesClient.onEvent('daily-buy-state-status', (data) => {
    applyDailyBuyStateStatus(data as { failed?: boolean })
  })

  /* ── test-cash-failed: 테스트 예수금 검증 실패 (사후 1회성 — 헤더 칩 알림) ── */
  pricesClient.onEvent('test-cash-failed', (data) => {
    applyTestCashFailed(data as { failed?: boolean; stk_cd?: string; reason?: string })
  })
}
