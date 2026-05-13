// frontend/src/binding.ts — WS → Store 바인딩 (순수 TS, React 의존성 없음)
// WS 단일 채널로 모든 이벤트(18개+) 통합

import type { WSClient } from './api/ws'
import type { StoreApi } from './stores/store'
import type { AppState } from './stores/appStore'
import {
  setConnected,
  setEngineReady,
  applyInitialSnapshot,
  applyAccountUpdate,
  applySectorScores,
  applySettingsChanged,
  applyIndexRefresh,
  applySnapshotUpdate,
  applyBuyTargetsUpdate,
  applySectorStocksRefresh,
  applyWsSubscribeStatus,
  applyWsConnectionStatus,
  applyBootstrapStage,
  applyAvgAmtProgress,
  applyMarketPhase,
  applySellHistoryUpdate,
  applyBuyHistoryUpdate,
  applyOrderFilled,
  applyBuyLimitStatus,
  applyDailySummaryUpdate,
  applyRealData,
  applyOrderbookUpdate,
  applyRealtimeReset,
  applyTestDataResetCompleted,
  appStore,
  stocksToMap,
  rebuildBuyTargetIndex,
} from './stores/appStore'
import type {
  AccountUpdateEvent,
  SectorScoresEvent,
  AppSettings,
  EngineStatus,
  SnapshotHistory,
  BuyTarget,
  SectorStock,
  SectorCustomChangedEvent,
  RealDataEvent,
} from './types'
import { applySectorCustomChanged } from './stores/sectorCustomStore'

/**
 * WS 18개+ 이벤트 타입을 Store 액션에 바인딩한다.
 * main.ts에서 앱 초기화 시 1회 호출.
 */
export function bindWSToStore(wsClient: WSClient, _store: StoreApi<AppState>): void {
  /* ── 연결 상태 콜백 ── */
  wsClient.setConnectionCallbacks(
    () => {
      console.log('[WS] 연결됨')
      setConnected(true)
    },
    () => {
      console.log('[WS] 연결 끊김 — 재연결 시도 중…')
      setConnected(false)
    },
  )

  /* ── 기존 SSE 이벤트 핸들러 (WS로 통합) ── */
  wsClient.onEvent('initial-snapshot', (data) => {
    console.log('[WS] initial-snapshot 수신')
    applyInitialSnapshot(data as Record<string, unknown>)
  })

  wsClient.onEvent('account-update', (data) => {
    applyAccountUpdate(data as AccountUpdateEvent)
  })

  wsClient.onEvent('sector-scores', (data) => {
    applySectorScores(data as SectorScoresEvent)
  })

  wsClient.onEvent('settings-changed', (data) => {
    applySettingsChanged(data as AppSettings)
  })

  wsClient.onEvent('index-refresh', (data) => {
    applyIndexRefresh(data as EngineStatus)
  })

  wsClient.onEvent('snapshot-update', (data) => {
    applySnapshotUpdate(data as { snapshot_history: SnapshotHistory[] })
  })

  wsClient.onEvent('buy-targets-update', (data) => {
    applyBuyTargetsUpdate(data as { buy_targets: BuyTarget[] })
  })

  wsClient.onEvent('sector-stocks-refresh', (data) => {
    applySectorStocksRefresh(data as { stocks: SectorStock[] })
  })

  /* ── 델타 이벤트 핸들러 (Phase 2 — 증분 갱신) ── */

  wsClient.onEvent('sector-stocks-delta', (data) => {
    const { added, removed } = data as { added: SectorStock[]; removed: string[] }
    appStore.setState((state) => {
      let sectorStocks = state.sectorStocks
      if (removed && removed.length > 0) {
        sectorStocks = { ...sectorStocks }
        for (const code of removed) {
          delete sectorStocks[code]
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

  wsClient.onEvent('buy-targets-delta', (data) => {
    const { added, removed, changed } = data as { added: BuyTarget[]; removed: string[]; changed: BuyTarget[] }
    appStore.setState((state) => {
      let buyTargets = state.buyTargets
      if (removed && removed.length > 0) {
        const removedSet = new Set(removed)
        buyTargets = buyTargets.filter(t => !removedSet.has(t.code))
      }
      if (changed && changed.length > 0) {
        buyTargets = buyTargets === state.buyTargets ? [...buyTargets] : buyTargets
        for (const item of changed) {
          const idx = buyTargets.findIndex(t => t.code === item.code)
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

  wsClient.onEvent('buy-history-append', (data) => {
    const { trade } = data as { trade: Record<string, unknown> }
    if (trade) {
      appStore.setState((state) => ({ buyHistory: [trade, ...state.buyHistory] }))
    }
  })

  wsClient.onEvent('sell-history-append', (data) => {
    const { trade, daily_summary } = data as { trade: Record<string, unknown>; daily_summary: Record<string, unknown>[] }
    appStore.setState((state) => {
      const patch: Partial<typeof state> = {}
      if (trade) patch.sellHistory = [trade, ...state.sellHistory]
      if (daily_summary) patch.dailySummary = daily_summary
      return patch
    })
  })

  wsClient.onEvent('ws-subscribe-status', (data) => {
    applyWsSubscribeStatus(data as { index_subscribed: boolean; quote_subscribed: boolean })
  })

  wsClient.onEvent('ws-connection-status', (data) => {
    console.log('[WS] ws-connection-status 수신:', data)
    applyWsConnectionStatus(data as { connected: boolean })
  })

  wsClient.onEvent('engine-ready', () => {
    console.log('[WS] engine-ready 수신 — 부트스트랩 완료')
    setEngineReady(true)
    applyBootstrapStage(null)
  })

  wsClient.onEvent('bootstrap-stage', (data) => {
    applyBootstrapStage(data as { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } })
  })

  wsClient.onEvent('avg-amt-progress', (data) => {
    applyAvgAmtProgress(data as { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string })
  })

  wsClient.onEvent('confirmed-progress', (data) => {
    applyAvgAmtProgress(data as { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string })
  })

  wsClient.onEvent('market-phase', (data) => {
    applyMarketPhase(data as { krx: string; nxt: string })
  })

  wsClient.onEvent('sell-history-update', (data) => {
    applySellHistoryUpdate(data as { sell_history: Record<string, unknown>[] })
  })

  wsClient.onEvent('daily-summary-update', (data) => {
    applyDailySummaryUpdate(data as { daily_summary: Record<string, unknown>[] })
  })

  wsClient.onEvent('buy-history-update', (data) => {
    applyBuyHistoryUpdate(data as { buy_history: Record<string, unknown>[] })
  })

  wsClient.onEvent('order-filled', (data) => {
    applyOrderFilled(data as Record<string, unknown>)
  })

  wsClient.onEvent('buy-limit-status', (data) => {
    applyBuyLimitStatus(data as { daily_buy_spent: number })
  })

  wsClient.onEvent('sector-custom-changed', (data) => {
    applySectorCustomChanged(data as SectorCustomChangedEvent)
  })

  /* ── [근본해결] 무가공 Raw 데이터 수신 (모든 FID 포함) ── */
  wsClient.onEvent<RealDataEvent>('real-data', (data) => {
    const t0 = performance.now()
    applyRealData(data)
    const procMs = performance.now() - t0
    // 서버→클라이언트 전파 지연 (백엔드 _ts 주입 기준)
    const srvTs = (data as any)._ts as number | undefined
    const netMs = srvTs ? Math.max(0, Date.now() - srvTs) : -1
    // 5ms 이상 처리 지연 또는 50ms 이상 네트워크 지연 시 warn
    if (procMs > 5.0) {
      console.warn(`[WS] real-data 처리 지연: ${procMs.toFixed(2)}ms`, data.item)
    }
    if (netMs > 50) {
      console.warn(`[WS] real-data 네트워크 지연: ${netMs.toFixed(0)}ms`, data.item)
    }
  })

  /* ── 호가잔량 실시간 갱신 (매수후보 테이블) ── */
  wsClient.onEvent('orderbook-update', (data) => {
    applyOrderbookUpdate(data as { code: string; bid: number; ask: number })
  })

  wsClient.onEvent('realtime-reset', () => {
    console.log('[WS] realtime-reset 수신 — 실시간 필드 초기화')
    applyRealtimeReset()
  })

  wsClient.onEvent('test-data-reset-completed', () => {
    console.log('[WS] test-data-reset-completed 수신 — 테스트 데이터 초기화 완료')
    console.log('[WS] 핸들러 실행')
    applyTestDataResetCompleted()
  })
}
