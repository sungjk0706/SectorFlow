// frontend/src/stores/uiStore.ts
// UI Store - UI 상태 전용 (저빈도 업데이트, 사용자 인터랙션)
import { createStore } from './store'
import type {
  SectorStatus,
  AppSettings,
  EngineStatus,
  IndexData,
} from '../types'

/** 수신율 단일 항목 — KRX/NXT 각각 1개씩 (2단계 분리 구조) */
export interface ReceiveRateEntry {
  received: number
  total: number
  pct: number
}

export interface UIState {
  /* ── UI 상태 필드 ── */
  settings: AppSettings | null
  status: EngineStatus | null
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
    is_nxt_only?: boolean
    krx_countdown?: { label: string; remaining_sec: number } | null
    nxt_countdown?: { label: string; remaining_sec: number } | null
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

  /* ── 수신율 상태 — KRX/NXT 분리 (2단계: 단일 데이터 양쪽 동일 매핑, 3단계: 백엔드 분리 데이터 연동) ── */
  receiveRate: { krx: ReceiveRateEntry | null; nxt: ReceiveRateEntry | null } | null

  /* ── 업종지수 실시간 (참고용, 저장 없음) ── */
  indexData: Record<string, IndexData> | null

  /* ── OMS 서킷브레이커 발동 상태 ── */
  circuitBreakerOpen: { message: string } | null

  /* ── 체결 불가 시간대 주문 차단 상태 (동시호가/장외) ── */
  orderTimeBlocked: { reason: string } | null

  /* ── 리스크 매니저 차단 상태 (손실/수익 한도 도달 등) ── */
  riskBlockStatus: { side: string; reason: string } | null
}

const initialState: UIState = {
  settings: null,
  status: null,
  sectorStatus: null,
  selectedSector: null,
  initialized: false,
  engineReady: false,
  avgAmtProgress: null,
  bootstrapStage: null,
  marketPhase: { krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false },
  buyLimitStatus: { daily_buy_spent: 0 },
  wsSubscribeStatus: { index_subscribed: false, quote_subscribed: false },
  sectorScoresDelta: null,
  sectorSummary: null,
  engineReloadComplete: false,
  receiveRate: null,
  indexData: null,
  circuitBreakerOpen: null,
  orderTimeBlocked: null,
  riskBlockStatus: null,
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

/* ── order_time_blocked: 체결 불가 시간대 주문 차단 상태 갱신 ── */
export function applyOrderTimeBlocked(data: { blocked?: boolean; reason?: string }): void {
  if (data.blocked) {
    uiStore.setState({ orderTimeBlocked: { reason: data.reason ?? '동시호가/장외 시간대 — 주문 일시중단' } })
  } else {
    uiStore.setState({ orderTimeBlocked: null })
  }
}

/* ── 주문 일시중단 상태 수동 해제 (사용자 클릭) ── */
export function clearOrderTimeBlocked(): void {
  uiStore.setState({ orderTimeBlocked: null })
}

/* ── risk_block_status: 리스크 매니저 차단 상태 갱신 ── */
export function applyRiskBlockStatus(data: { blocked?: boolean; side?: string; reason?: string }): void {
  if (data.blocked) {
    uiStore.setState({ riskBlockStatus: { side: data.side ?? 'unknown', reason: data.reason ?? '리스크 차단' } })
  } else {
    uiStore.setState({ riskBlockStatus: null })
  }
}

/* ── 리스크 차단 상태 수동 해제 (사용자 클릭) ── */
export function clearRiskBlockStatus(): void {
  uiStore.setState({ riskBlockStatus: null })
}

/* ── buy-limit-status: 매수 한도 상태 갱신 ── */
export function applyBuyLimitStatus(data: { daily_buy_spent: number }): void {
  uiStore.setState({ buyLimitStatus: { daily_buy_spent: data.daily_buy_spent ?? 0 } })
}

/* ── test-data-reset-completed: 통합 초기화 완료 ── */
export function applyTestDataResetCompleted(): void {
  uiStore.setState({
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

/* ── index-data: 업종지수 실시간 갱신 + broker_statuses + market_phase 갱신 ── */
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
    if (data.market_phase) {
      patch.marketPhase = { ...state.marketPhase, ...data.market_phase }
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
    sectorStatus: (data.sector_status as SectorStatus) ?? null,
    sectorSummary: (data.sector_summary as Record<string, unknown>) ?? null,
    buyLimitStatus: (data.buy_limit_status as { daily_buy_spent: number }) ?? { daily_buy_spent: 0 },
    wsSubscribeStatus: (data.ws_subscribe_status as { index_subscribed: boolean; quote_subscribed: boolean }) ?? { index_subscribed: false, quote_subscribed: false },
    initialized: true,
    circuitBreakerOpen: null,
    orderTimeBlocked: null,
    riskBlockStatus: null,
    engineReady: !!(data.bootstrap_done),
    marketPhase: (data.market_phase as UIState['marketPhase']) ?? { krx: '장마감', nxt: '장마감', krx_alert: null },
    receiveRate: (() => {
      const r = data.receive_rate as { received: number; total: number; pct: number } | { krx: ReceiveRateEntry | null; nxt: ReceiveRateEntry | null } | undefined
      if (!r) return null
      // 3단계: 백엔드 KRX/NXT 분리 수신률 → 분리 매핑 (단일 구조는 레거시 호환)
      if ('krx' in r || 'nxt' in r) return r as { krx: ReceiveRateEntry | null; nxt: ReceiveRateEntry | null }
      const single = r as { received: number; total: number; pct: number }
      return { krx: single, nxt: single }
    })(),
    avgAmtProgress: data.avg_amt_refresh ? { current: (data.avg_amt_refresh as Record<string, unknown>).current as number ?? 0, total: (data.avg_amt_refresh as Record<string, unknown>).total as number ?? 0, done: false, status: ((data.avg_amt_refresh as Record<string, unknown>).status as string) || undefined } : data.confirmed_refresh ? { current: 0, total: 0, done: false, message: ((data.confirmed_refresh as Record<string, unknown>).message as string) || '', status: 'confirmed' } : null,
  })
}
