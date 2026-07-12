// frontend/src/stores/uiStore.ts
// UI Store - UI 상태 전용 (저빈도 업데이트, 사용자 인터랙션)
import { createStore } from './store'
import type {
  SectorStatus,
  AppSettings,
  EngineStatus,
  SnapshotHistory,
  IndexData,
} from '../types'

export interface UIState {
  /* ── UI 상태 필드 ── */
  settings: AppSettings | null
  status: EngineStatus | null
  snapshotHistory: SnapshotHistory[]
  sectorStatus: SectorStatus | null
  selectedSector: string | null

  /* ── 연결 상태 ── */
  initialized: boolean
  engineReady: boolean

  /* ── 백그라운드 진행률 ── */
  avgAmtProgress: { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number; failed_count?: number } | null

  /* ── 부트스트랩 단계 ── */
  bootstrapStage: { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } } | null

  /* ── 장 상태 ── */
  marketPhase: {
    krx: string
    nxt: string
    krx_alert?: string | null
    krx_event?: string | null
    nxt_event?: string | null
  }

  /* ── 매수 한도 상태 ── */
  buyLimitStatus: { daily_buy_spent: number }

  /* ── WS 구독 상태 ── */
  wsSubscribeStatus: { index_subscribed: boolean; quote_subscribed: boolean }

  /* ── 업종 점수 델타 ── */
  sectorScoresDelta: { delta: boolean; changed_sectors: string[]; removed_sectors: string[] } | null

  /* ── 업종 요약 ── */
  sectorSummary: Record<string, unknown> | null

  /* ── 설정 재로드 완료 상태 ── */
  engineReloadComplete: boolean

  /* ── 수신율 상태 ── */
  receiveRate: { received: number; total: number; pct: number } | null

  /* ── 업종지수 실시간 (참고용, 저장 없음) ── */
  indexData: Record<string, IndexData> | null

  /* ── OMS 서킷브레이커 발동 상태 ── */
  circuitBreakerOpen: { message: string } | null
}

const initialState: UIState = {
  settings: null,
  status: null,
  snapshotHistory: [],
  sectorStatus: null,
  selectedSector: null,
  initialized: false,
  engineReady: false,
  avgAmtProgress: null,
  bootstrapStage: null,
  marketPhase: { krx: 'CLOSED', nxt: 'CLOSED', krx_alert: null, krx_event: null, nxt_event: null },
  buyLimitStatus: { daily_buy_spent: 0 },
  wsSubscribeStatus: { index_subscribed: false, quote_subscribed: false },
  sectorScoresDelta: null,
  sectorSummary: null,
  engineReloadComplete: false,
  receiveRate: null,
  indexData: null,
  circuitBreakerOpen: null,
}

export const uiStore = createStore<UIState>(initialState)

/* ── UI 상태 액션 함수 ── */

export function applyAvgAmtProgress(data: { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number; failed_count?: number }): void {
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
  const mp = (data as unknown as Record<string, unknown>).market_phase as UIState['marketPhase'] | undefined
  if (mp) patch.marketPhase = mp
  uiStore.setState(patch)
}

/* ── engine-reload-complete: 설정 재로드 완료 + 서킷브레이커 알림 해제 ── */
export function applyEngineReloadComplete(): void {
  uiStore.setState({ engineReloadComplete: true, circuitBreakerOpen: null })
}

/* ── circuit_breaker_open: OMS 서킷브레이커 발동 알림 ── */
export function applyCircuitBreakerOpen(data: { message?: string }): void {
  uiStore.setState({ circuitBreakerOpen: { message: data.message ?? '서킷브레이커 발동 — 자동매매 중지' } })
}

/* ── 서킷브레이커 알림 수동 해제 (사용자 클릭) ── */
export function clearCircuitBreakerOpen(): void {
  uiStore.setState({ circuitBreakerOpen: null })
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
  uiStore.setState({
    snapshotHistory: [],
    buyLimitStatus: { daily_buy_spent: 0 },
  })
}

/* ── ws-subscribe-status: 구독 상태 갱신 ── */
export function applyWsSubscribeStatus(data: { index_subscribed: boolean; quote_subscribed: boolean }): void {
  uiStore.setState({ wsSubscribeStatus: data })
}

/* ── market-phase: 장 상태 갱신 ── */
export function applyMarketPhase(data: Partial<UIState['marketPhase']>): void {
  const prev = uiStore.getState().marketPhase
  uiStore.setState({ marketPhase: { ...prev, ...data } })
}

/* ── index-data: 업종지수 실시간 갱신 + broker_statuses 갱신 ── */
export function applyIndexData(data: IndexData): void {
  uiStore.setState((state) => {
    const patch: Partial<UIState> = {}
    if (data.upcode) {
      const prev = state.indexData ?? {}
      patch.indexData = { ...prev, [data.upcode]: data }
    }
    if (data.broker_statuses) {
      patch.status = state.status
        ? { ...state.status, broker_statuses: data.broker_statuses }
        : { broker_statuses: data.broker_statuses } as EngineStatus
    }
    return patch
  })
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
    circuitBreakerOpen: null,
    engineReady: !!(data.bootstrap_done),
    marketPhase: (data.market_phase as UIState['marketPhase']) ?? { krx: 'CLOSED', nxt: 'CLOSED', krx_alert: null, krx_event: null, nxt_event: null },
    receiveRate: (data.receive_rate as { received: number; total: number; pct: number }) ?? null,
    avgAmtProgress: data.avg_amt_refresh ? { current: (data.avg_amt_refresh as Record<string, unknown>).current as number ?? 0, total: (data.avg_amt_refresh as Record<string, unknown>).total as number ?? 0, done: false, status: ((data.avg_amt_refresh as Record<string, unknown>).status as string) || undefined } : data.confirmed_refresh ? { current: 0, total: 0, done: false, message: ((data.confirmed_refresh as Record<string, unknown>).message as string) || '', status: 'confirmed' } : null,
  })
}
