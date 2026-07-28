// frontend/src/binding.ts — WS → Store 바인딩 (순수 TS, React 의존성 없음)
// WS 채널 분리: prices(시세), settings(설정/진행률), orders(체결)

import type { WSClient } from './api/ws'
import { getCurrentPage } from './api/ws'
import {
  applyAccountUpdate,
  applyAccountSummaryUpdate,
  applyRealData,
  applyOrderbookUpdate,
  applyProgramUpdate,
  applyBuyTargetsUpdate,
  applyBuyTargetsDelta,
  applyNewsHit,
  applySectorStocksRefresh,
  applySectorStocksDelta,
  applyRealtimeReset,
  applySellHistoryUpdate,
  applyBuyHistoryUpdate,
  applyDailySummaryUpdate,
  applySectorScores,
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
  SectorStock,
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
      if (page) pricesClient.send(JSON.stringify({ type: 'page-active', page }))
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
    applyBuyTargetsUpdate(data as { buy_targets: StockScore[] })
  })

  pricesClient.onEvent('sector-stocks-refresh', (data) => {
    applySectorStocksRefresh(data as { stocks: SectorStock[] })
  })

  /* ── prices 채널 델타 이벤트 핸들러 (Phase 2 — 증분 갱신) ── */
  pricesClient.onEvent('sector-stocks-delta', (data) => {
    applySectorStocksDelta(data as { added: SectorStock[]; removed: string[] })
  })

  pricesClient.onEvent('buy-targets-delta', (data) => {
    applyBuyTargetsDelta(data as { added: StockScore[]; removed: string[]; changed: StockScore[] })
  })

  pricesClient.onEvent('buy-history-append', (data) => {
    const { trade } = data as { trade: Record<string, unknown> }
    if (trade) {
      hotStore.setState((state) => ({ buyHistory: [trade, ...state.buyHistory] }))
    }
  })

  pricesClient.onEvent('real-data', (data) => {
    applyRealData(data as RealDataEvent)
  })

  pricesClient.onEvent('orderbook-update', (data) => {
    applyOrderbookUpdate(data as { code: string; bid: number; ask: number })
  })

  pricesClient.onEvent('program-update', (data) => {
    applyProgramUpdate(data as { code: string; net_buy: number })
  })

  /* ── settings 채널 연결 상태 콜백 ── */
  settingsClient.setConnectionCallbacks(
    () => {
      const page = getCurrentPage()
      if (page) settingsClient.send(JSON.stringify({ type: 'page-active', page }))
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
    applyDailySummaryUpdate(data as { daily_summary: Record<string, unknown>[] })
  })


  /* ── orders 채널 이벤트 핸들러 ── */
  ordersClient.onEvent('test-data-reset-completed', () => {
    applyTestDataResetCompleted()
  })

  /* ── stock-classification-changed는 모든 채널에서 수신 가능하도록 prices 채널에 유지 ── */
  pricesClient.onEvent('stock-classification-changed', (data) => {
    applyStockClassificationChanged(data as StockClassificationChangedEvent)
  })

  pricesClient.onEvent('sell-history-append', (data) => {
    const { trade, daily_summary } = data as { trade: Record<string, unknown>; daily_summary: Record<string, unknown>[] }
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
    applySellHistoryUpdate(data as { sell_history: Record<string, unknown>[] })
  })

  pricesClient.onEvent('buy-history-update', (data) => {
    applyBuyHistoryUpdate(data as { buy_history: Record<string, unknown>[] })
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
      status?: Record<string, unknown>
    }
    applySectorScores(d as unknown as SectorScoresEvent)
    // sectorScoresDelta (uiStore) 갱신
    uiStore.setState({
      sectorScoresDelta: d.delta
        ? { delta: true, changed_sectors: d.changed_sectors ?? [], removed_sectors: d.removed_sectors ?? [] }
        : null,
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

  /* ── order-time-blocked: 체결 불가 시간대 주문 차단 상태 (10초 주기) ── */
  pricesClient.onEvent('order-time-blocked', (data) => {
    applyOrderTimeBlocked(data as { blocked?: boolean; reason?: string })
  })

  /* ── risk-block-status: 리스크 매니저 차단 상태 (손실 한도 도달 등) ── */
  pricesClient.onEvent('risk-block-status', (data) => {
    applyRiskBlockStatus(data as { blocked?: boolean; side?: string; reason?: string })
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
