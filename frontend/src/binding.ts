// frontend/src/binding.ts — WS → Store 바인딩 (순수 TS, React 의존성 없음)
// WS 채널 분리: prices(시세), settings(설정/진행률), orders(체결)

import type { WSClient } from './api/ws'
import {
  applyAccountUpdate,
  applyRealData,
  applyOrderbookUpdate,
  applyBuyTargetsUpdate,
  applySectorStocksRefresh,
  applyOrderFilled,
  applyRealtimeReset,
  applySellHistoryUpdate,
  applyBuyHistoryUpdate,
  applyDailySummaryUpdate,
  applySectorScores,
  stocksToMap,
  rebuildBuyTargetIndex,
  hotStore,
  applyInitialSnapshotHot,
  normalizeStockCode,
} from './stores/hotStore'
import {
  applySettingsChanged,
  applyIndexRefresh,
  applySnapshotUpdate,
  applyBootstrapStage,
  applyAvgAmtProgress,
  applyTestDataResetCompleted,
  applyInitialSnapshotUI,
  applyRealtimeState,
  applyWsSubscribeStatus,
  applyBuyLimitStatus,
  applyEngineReloadComplete,
  uiStore,
} from './stores/uiStore'
import type {
  AccountUpdateEvent,
  AppSettings,
  EngineStatus,
  SnapshotHistory,
  BuyTarget,
  SectorStock,
  StockClassificationChangedEvent,
  RealDataEvent,
  SectorScoreRow,
  SectorScoresEvent,
} from './types'
import { applyStockClassificationChanged } from './stores/stockClassificationStore'

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
      console.log('[WS] prices 채널 연결됨')
    },
    () => {
      console.log('[WS] prices 채널 연결 끊김 — 재연결 시도 중…')
    },
  )

  /* ── prices 채널 기존 SSE 이벤트 핸들러 (WS로 통합) ── */
  pricesClient.onEvent('initial-snapshot', (data) => {
    applyInitialSnapshotHot(data as Record<string, unknown>)
    applyInitialSnapshotUI(data as Record<string, unknown>)
  })

  pricesClient.onEvent('account-update', (data) => {
    applyAccountUpdate(data as AccountUpdateEvent)
  })


  pricesClient.onEvent('buy-targets-update', (data) => {
    applyBuyTargetsUpdate(data as { buy_targets: BuyTarget[] })
  })

  pricesClient.onEvent('sector-stocks-refresh', (data) => {
    applySectorStocksRefresh(data as { stocks: SectorStock[] })
  })

  /* ── prices 채널 델타 이벤트 핸들러 (Phase 2 — 증분 갱신) ── */
  pricesClient.onEvent('sector-stocks-delta', (data) => {
    const { added, removed } = data as { added: SectorStock[]; removed: string[] }
    hotStore.setState((state) => {
      let sectorStocks = state.sectorStocks
      if (removed && removed.length > 0) {
        sectorStocks = { ...sectorStocks }
        for (const code of removed) {
          delete sectorStocks[normalizeStockCode(code)]
        }
      }
      if (added && added.length > 0) {
        const addedMap = stocksToMap(added)
        sectorStocks = sectorStocks === state.sectorStocks
          ? { ...sectorStocks, ...addedMap }
          : { ...sectorStocks, ...addedMap }
      }
      if (sectorStocks === state.sectorStocks) return state
      return { sectorStocks }
    })
  })

  pricesClient.onEvent('buy-targets-delta', (data) => {
    const { added, removed, changed } = data as { added: BuyTarget[]; removed: string[]; changed: BuyTarget[] }
    hotStore.setState((state) => {
      let buyTargets = state.buyTargets
      if (removed && removed.length > 0) {
        const removedSet = new Set(removed.map(c => normalizeStockCode(c)))
        buyTargets = buyTargets.filter((t: BuyTarget) => !removedSet.has(normalizeStockCode(t.code)))
      }
      if (changed && changed.length > 0) {
        buyTargets = buyTargets === state.buyTargets ? [...buyTargets] : buyTargets
        for (const item of changed) {
          const idx = buyTargets.findIndex((t: BuyTarget) => normalizeStockCode(t.code) === normalizeStockCode(item.code))
          if (idx >= 0) buyTargets[idx] = item
        }
      }
      if (added && added.length > 0) {
        buyTargets = buyTargets === state.buyTargets ? [...buyTargets, ...added] : [...buyTargets, ...added]
      }
      if (buyTargets === state.buyTargets) return state
      rebuildBuyTargetIndex(buyTargets)
      return { buyTargets }
    })
  })

  pricesClient.onEvent('buy-history-append', (data) => {
    const { trade } = data as { trade: Record<string, unknown> }
    if (trade) {
      hotStore.setState((state) => ({ buyHistory: [trade, ...state.buyHistory] }))
    }
  })

  pricesClient.onEvent('sell-history-append', (data) => {
    const { trade } = data as { trade: Record<string, unknown> }
    if (trade) {
      hotStore.setState((state) => ({ sellHistory: [trade, ...state.sellHistory] }))
    }
  })

  pricesClient.onEvent('real-data', (data) => {
    applyRealData(data as RealDataEvent)
  })

  pricesClient.onEvent('orderbook-update', (data) => {
    applyOrderbookUpdate(data as { code: string; bid: number; ask: number })
  })

  /* ── settings 채널 이벤트 핸들러 ── */
  settingsClient.onEvent('settings-changed', (data) => {
    applySettingsChanged(data as AppSettings)
  })

  settingsClient.onEvent('engine-reload-complete', () => {
    console.log('[WS] engine-reload-complete 수신 — 엔진 재시작 완료')
    applyEngineReloadComplete()
  })

  settingsClient.onEvent('index-refresh', (data) => {
    applyIndexRefresh(data as EngineStatus)
  })

  settingsClient.onEvent('snapshot-update', (data) => {
    applySnapshotUpdate(data as { snapshot_history: SnapshotHistory[] })
  })


  settingsClient.onEvent('ws-connection-status', (data) => {
    console.log('[WS] ws-connection-status 수신:', data)
  })

  settingsClient.onEvent('bootstrap-stage', (data) => {
    applyBootstrapStage(data as { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } })
  })

  settingsClient.onEvent('avg-amt-progress', (data) => {
    applyAvgAmtProgress(data as { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number })
  })


  settingsClient.onEvent('daily-summary-update', (data) => {
    applyDailySummaryUpdate(data as { daily_summary: Record<string, unknown>[] })
  })


  /* ── orders 채널 이벤트 핸들러 ── */
  ordersClient.onEvent('order-filled', (data) => {
    applyOrderFilled(data as Record<string, unknown>)
  })


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
    console.log('[WS] engine-ready 수신 — 부트스트랩 완료')
    applyEngineReloadComplete()
  })

  pricesClient.onEvent('confirmed-progress', (data) => {
    applyAvgAmtProgress(data as { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string })
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

  pricesClient.onEvent('realtime-state', (data) => {
    applyRealtimeState(data as { status: "waiting" | "live" })
  })

  /* ── sector-scores: 업종순위 실시간 갱신 ── */
  pricesClient.onEvent('sector-scores', (data) => {
    const d = data as {
      scores: SectorScoreRow[]
      delta?: boolean
      changed_sectors?: string[]
      removed_sectors?: string[]
      status?: Record<string, unknown>
    }
    applySectorScores(d as unknown as SectorScoresEvent)
    // sectorOrder (uiStore) 갱신 — 초기 스냅샷 이후에도 순서 유지
    if (d.scores) {
      const prev = uiStore.getState().sectorOrder
      const newOrder = d.scores.map(s => s.sector)
      if (prev.length !== newOrder.length || prev.some((s, i) => s !== newOrder[i])) {
        uiStore.setState({ sectorOrder: newOrder })
      }
    }
    // sectorScoresDelta (uiStore) 갱신
    uiStore.setState({
      sectorScoresDelta: d.delta
        ? { delta: true, changed_sectors: d.changed_sectors ?? [], removed_sectors: d.removed_sectors ?? [] }
        : null,
    })
  })

  /* ── ws-subscribe-status: 구독 상태 실시간 갱신 ── */
  pricesClient.onEvent('ws-subscribe-status', (data) => {
    applyWsSubscribeStatus(data as { index_subscribed: boolean; quote_subscribed: boolean })
  })

  /* ── buy-limit-status: 매수 한도 상태 실시간 갱신 ── */
  pricesClient.onEvent('buy-limit-status', (data) => {
    applyBuyLimitStatus(data as { daily_buy_spent: number })
  })

  pricesClient.onEvent('test-data-reset-completed', () => {
    applyTestDataResetCompleted()
  })
}
