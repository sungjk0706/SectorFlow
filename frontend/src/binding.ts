// frontend/src/binding.ts — WS → Store 바인딩 (순수 TS, React 의존성 없음)
// WS 채널 분리: prices(시세), settings(설정/진행률), orders(체결)

import type { WSClient } from './api/ws'
import { getCurrentPage } from './api/ws'
import {
  applyAccountUpdate,
  applyRealData,
  applyOrderbookUpdate,
  applyProgramUpdate,
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
  recalcTradeAmountRank,
  hotStore,
  applyInitialSnapshotHot,
  normalizeStockCode,
} from './stores/hotStore'
import {
  applySettingsChanged,
  applySnapshotUpdate,
  applyBootstrapStage,
  applyAvgAmtProgress,
  applyTestDataResetCompleted,
  applyInitialSnapshotUI,
  applyWsSubscribeStatus,
  applyBuyLimitStatus,
  applyEngineReloadComplete,
  applyCircuitBreakerOpen,
  applyMarketPhase,
  applyIndexData,
  uiStore,
} from './stores/uiStore'
import type {
  AccountUpdateEvent,
  AppSettings,
  SnapshotHistory,
  SectorStock,
  StockClassificationChangedEvent,
  RealDataEvent,
  SectorScoreRow,
  SectorScoresEvent,
  IndexData,
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


  pricesClient.onEvent('buy-targets-update', (data) => {
    applyBuyTargetsUpdate(data as { buy_targets: SectorStock[] })
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
        sectorStocks = { ...sectorStocks, ...addedMap }
      }
      if (sectorStocks === state.sectorStocks) return state
      return { sectorStocks }
    })
  })

  pricesClient.onEvent('buy-targets-delta', (data) => {
    const { added, removed, changed } = data as { added: SectorStock[]; removed: string[]; changed: SectorStock[] }
    hotStore.setState((state) => {
      let buyTargets = state.buyTargets
      if (removed && removed.length > 0) {
        const removedSet = new Set(removed.map(c => normalizeStockCode(c)))
        buyTargets = buyTargets.filter((t: SectorStock) => !removedSet.has(normalizeStockCode(t.code)))
      }
      if (changed && changed.length > 0) {
        buyTargets = buyTargets === state.buyTargets ? [...buyTargets] : buyTargets
        for (const item of changed) {
          const idx = buyTargets.findIndex((t: SectorStock) => normalizeStockCode(t.code) === normalizeStockCode(item.code))
          if (idx >= 0) {
            // 아키텍처 원칙 — sectorStocks가 실시간 데이터 단일 소스
            const sectorStock = state.sectorStocks[normalizeStockCode(item.code)]
            buyTargets[idx] = {
              ...item,
              cur_price: sectorStock?.cur_price,
              change: sectorStock?.change,
              change_rate: sectorStock?.change_rate,
              strength: sectorStock?.strength,
              trade_amount: sectorStock?.trade_amount,
            }
          }
        }
      }
      if (added && added.length > 0) {
        // 아키텍처 원칙 — sectorStocks가 실시간 데이터 단일 소스
        const addedWithRealtime = added.map(item => {
          const sectorStock = state.sectorStocks[normalizeStockCode(item.code)]
          const result = {
            ...item,
            cur_price: sectorStock?.cur_price,
            change: sectorStock?.change,
            change_rate: sectorStock?.change_rate,
            strength: sectorStock?.strength,
            trade_amount: sectorStock?.trade_amount,
          }
          return result
        })
        buyTargets = buyTargets === state.buyTargets ? [...buyTargets, ...addedWithRealtime] : [...buyTargets, ...addedWithRealtime]
      }
      if (buyTargets === state.buyTargets) return state
      recalcTradeAmountRank(buyTargets)
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
    applySettingsChanged(data as AppSettings)
  })

  settingsClient.onEvent('engine-reload-complete', () => {
    applyEngineReloadComplete()
  })

  settingsClient.onEvent('index-data', (data) => {
    applyIndexData(data as IndexData)
  })

  settingsClient.onEvent('snapshot-update', (data) => {
    applySnapshotUpdate(data as { snapshot_history: SnapshotHistory[] })
  })


  settingsClient.onEvent('bootstrap-stage', (data) => {
    applyBootstrapStage(data as { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } })
  })

  settingsClient.onEvent('avg-amt-progress', (data) => {
    applyAvgAmtProgress(data as { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number; failed_count?: number })
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
    applyMarketPhase(data as Partial<{ krx: string; nxt: string; krx_alert: string | null; is_nxt_only: boolean }>)
  })

  /* ── receive-rate: 수신율 실시간 갱신 ── */
  pricesClient.onEvent('receive-rate', (data) => {
    const d = data as { pct: number; received: number; total: number }
    uiStore.setState({ receiveRate: { pct: d.pct, received: d.received, total: d.total } })
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
    // receiveRate (uiStore) 갱신
    const receiveRate = (d.status as Record<string, unknown>)?.receive_rate as { received: number; total: number; pct: number } | undefined
    uiStore.setState({ receiveRate: receiveRate ?? null })
  })

  /* ── ws-subscribe-status: 구독 상태 실시간 갱신 ── */
  pricesClient.onEvent('ws-subscribe-status', (data) => {
    applyWsSubscribeStatus(data as { index_subscribed: boolean; quote_subscribed: boolean })
  })

  /* ── circuit_breaker_open: OMS 서킷브레이커 발동 알림 ── */
  pricesClient.onEvent('circuit_breaker_open', (data) => {
    const d = data as { message?: string }
    applyCircuitBreakerOpen(d)
    showToast('error', d.message ?? '서킷브레이커 발동 — 자동매매 중지', 8000)
  })

  /* ── buy-limit-status: 매수 한도 상태 실시간 갱신 ── */
  pricesClient.onEvent('buy-limit-status', (data) => {
    applyBuyLimitStatus(data as { daily_buy_spent: number })
  })
}
