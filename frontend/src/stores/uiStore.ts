// frontend/src/stores/uiStore.ts
// UI Store - UI 상태 전용 (저빈도 업데이트, 사용자 인터랙션)
import { createStore } from './store'
import type {
  SectorStatus,
  AppSettings,
  EngineStatus,
  SnapshotHistory,
} from '../types'

export interface UIState {
  /* ── UI 상태 필드 ── */
  settings: AppSettings | null
  status: EngineStatus | null
  snapshotHistory: SnapshotHistory[]
  sectorStatus: SectorStatus | null
  selectedSector: string | null
  positionCount: number

  /* ── 연결 상태 ── */
  connected: boolean
  initialized: boolean
  engineReady: boolean
  backfilling: boolean

  /* ── 백그라운드 진행률 ── */
  avgAmtProgress: { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number } | null

  /* ── 부트스트랩 단계 ── */
  bootstrapStage: { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } } | null

  /* ── 장 상태 ── */
  marketPhase: { krx: string; nxt: string }

  /* ── 매수 한도 상태 ── */
  buyLimitStatus: { daily_buy_spent: number }

  /* ── WS 구독 상태 ── */
  wsSubscribeStatus: { index_subscribed: boolean; quote_subscribed: boolean }

  /* ── 업종 점수 델타 ── */
  sectorScoresDelta: { delta: boolean; changed_sectors: string[]; removed_sectors: string[] } | null

  /* ── 업종 요약 ── */
  sectorSummary: Record<string, unknown> | null

  /* ── 실시간 상태 ── */
  realtimeStatus: "waiting" | "live" | null

  /* ── 엔진 재시작 완료 상태 ── */
  engineReloadComplete: boolean
}

const initialState: UIState = {
  settings: null,
  status: null,
  snapshotHistory: [],
  sectorStatus: null,
  selectedSector: null,
  positionCount: 0,
  connected: false,
  initialized: false,
  engineReady: false,
  backfilling: false,
  avgAmtProgress: null,
  bootstrapStage: null,
  marketPhase: { krx: 'CLOSED', nxt: 'CLOSED' },
  buyLimitStatus: { daily_buy_spent: 0 },
  realtimeStatus: "waiting",
  wsSubscribeStatus: { index_subscribed: false, quote_subscribed: false },
  sectorScoresDelta: null,
  sectorSummary: null,
  engineReloadComplete: false,
}

export const uiStore = createStore<UIState>(initialState)

/* ── UI 상태 액션 함수 ── */

export function setConnected(v: boolean): void {
  uiStore.setState({ connected: v })
}

export function setBackfilling(v: boolean): void {
  uiStore.setState({ backfilling: v })
}

export function setEngineReady(v: boolean): void {
  uiStore.setState({ engineReady: v })
}

export function applyAvgAmtProgress(data: { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number }): void {
  if (data.done && (data.status === 'completed' || data.status === 'confirmed')) {
    // 완료: 3초 후 자동 숨김
    uiStore.setState({ avgAmtProgress: data })
    setTimeout(() => {
      const cur = uiStore.getState().avgAmtProgress
      if (cur && (cur.status === 'completed' || cur.status === 'confirmed')) {
        uiStore.setState({ avgAmtProgress: null })
      }
    }, 3000)
  } else if (data.done && (data.status === 'failed' || data.status === 'partial')) {
    // 실패/부분성공: 숨기지 않음
    uiStore.setState({ avgAmtProgress: data })
  } else if (data.done && !data.status) {
    // 하위 호환: status 없이 done=true → 즉시 숨김
    uiStore.setState({ avgAmtProgress: null })
  } else {
    uiStore.setState({ avgAmtProgress: data })
  }
}

export function applyBootstrapStage(data: { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } } | null): void {
  uiStore.setState({ bootstrapStage: data })
}

/* ── settings-changed: 설정만 갱신 (증분 갱신 대응) ── */
export function applySettingsChanged(data: AppSettings | { delta: boolean; changed: Partial<AppSettings> }): void {
  if (data && 'delta' in data && data.delta) {
    uiStore.setState((state) => ({
      settings: state.settings ? { ...state.settings, ...(data.changed && typeof data.changed === 'object' ? data.changed : {}) } : (data.changed as AppSettings),
    }))
  } else {
    uiStore.setState({ settings: data as AppSettings })
  }
}

/* ── index-refresh: 엔진 상태 + 장 상태 갱신 ── */
export function applyIndexRefresh(data: EngineStatus): void {
  const patch: Partial<UIState> = { status: data }
  const mp = (data as unknown as Record<string, unknown>).market_phase as { krx: string; nxt: string } | undefined
  if (mp) patch.marketPhase = mp
  uiStore.setState(patch)
}

/* ── engine-reload-complete: 엔진 재시작 완료 ── */
export function applyEngineReloadComplete(): void {
  uiStore.setState({ engineReloadComplete: true })
}

/* ── snapshot-update: 수익 이력만 갱신 ── */
export function applySnapshotUpdate(data: { snapshot_history: SnapshotHistory[] }): void {
  const incoming = data.snapshot_history ?? []
  const prev = uiStore.getState().snapshotHistory

  // 길이 같고 마지막 항목의 timestamp·total_pnl·total_pnl_rate 동일하면 스킵
  if (
    incoming.length === prev.length
    && incoming.length > 0
  ) {
    const a = incoming[incoming.length - 1]
    const b = prev[prev.length - 1]
    if (
      a.timestamp === b.timestamp
      && a.total_pnl === b.total_pnl
      && a.total_pnl_rate === b.total_pnl_rate
    ) return
  }

  uiStore.setState({ snapshotHistory: incoming })
}

/* ── buy-limit-status: 매수 한도 상태 갱신 ── */
export function applyBuyLimitStatus(data: { daily_buy_spent: number }): void {
  uiStore.setState({ buyLimitStatus: { daily_buy_spent: data.daily_buy_spent ?? 0 } })
}

/* ── test-data-reset-completed: 통합 초기화 완료 ── */
export function applyTestDataResetCompleted(): void {
  console.log("[초기화] applyTestDataResetCompleted 실행")
  console.log("Store 업데이트 전")
  uiStore.setState({
    snapshotHistory: [],
    buyLimitStatus: { daily_buy_spent: 0 },
  })
  console.log("Store 업데이트 후")
}

/* ── ws-subscribe-status: 구독 상태 갱신 ── */
export function applyWsSubscribeStatus(data: { index_subscribed: boolean; quote_subscribed: boolean }): void {
  uiStore.setState({ wsSubscribeStatus: data })
}

/* ── ws-connection-status: Broker WebSocket 연결 상태 갱신 ── */
export function applyWsConnectionStatus(data: { connected: boolean }): void {
  uiStore.setState((state) => ({
    status: state.status ? { ...state.status, broker_connected: data.connected } : null,
  }))
}

/* ── market-phase: 장 상태 갱신 ── */
export function applyMarketPhase(data: { krx: string; nxt: string }): void {
  uiStore.setState({ marketPhase: data })
}

/* ── realtime-state: 실시간 상태 갱신 ── */
export function applyRealtimeState(data: { status: "waiting" | "live" }): void {
  uiStore.setState({ realtimeStatus: data.status })
}

/* ── selectedSector: 토글 ── */
export function setSelectedSector(sector: string | null): void {
  uiStore.setState((state) => ({
    selectedSector: state.selectedSector === sector ? null : sector,
  }))
}

/* ── initial-snapshot (uiStore): UI 상태 초기화 ── */
export function applyInitialSnapshotUI(data: Record<string, unknown>): void {
  uiStore.setState({
    settings: (data.settings as AppSettings) ?? null,
    status: (data.status as EngineStatus) ?? null,
    snapshotHistory: (data.snapshot_history as SnapshotHistory[]) ?? [],
    sectorStatus: (data.sector_status as SectorStatus) ?? null,
    sectorSummary: (data.sector_summary as Record<string, unknown>) ?? null,
    buyLimitStatus: (data.buy_limit_status as { daily_buy_spent: number }) ?? { daily_buy_spent: 0 },
    wsSubscribeStatus: (data.ws_subscribe_status as { index_subscribed: boolean; quote_subscribed: boolean }) ?? { index_subscribed: false, quote_subscribed: false },
    initialized: true,
    backfilling: false,
    engineReady: !!(data.bootstrap_done),
    marketPhase: (data.market_phase as { krx: string; nxt: string }) ?? { krx: 'CLOSED', nxt: 'CLOSED' },
    avgAmtProgress: data.avg_amt_refresh ? { current: (data.avg_amt_refresh as Record<string, unknown>).current as number ?? 0, total: (data.avg_amt_refresh as Record<string, unknown>).total as number ?? 0, done: false, status: ((data.avg_amt_refresh as Record<string, unknown>).status as string) || undefined } : data.confirmed_refresh ? { current: 0, total: 0, done: false, message: ((data.confirmed_refresh as Record<string, unknown>).message as string) || '', status: 'confirmed' } : null,
  })
}
