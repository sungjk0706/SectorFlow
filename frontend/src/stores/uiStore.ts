// frontend/src/stores/uiStore.ts
// UI Store - UI 상태 전용 (저빈도 업데이트, 사용자 인터랙션)
import { createStore } from './store'
import type {
  SectorStatus,
  AppSettings,
  EngineStatus,
  EngineStatusPayload,
  IndexData,
  SettingsChangedEvent,
  SettingsChangedDeltaEvent,
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

  /* ── 업종 점수 수신 대기 상태 (P21 투명성) ──
   * 수신율 임계값 미통과 시 true — "데이터 수신 대기 중" 표시.
   * 임계값 통과 후 정상 sector-scores 전송 시 false로 해제. */
  sectorScoresWaiting: boolean

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

  /* ── 체결 불가 시간대 주문 상태 (동시호가/장외 — 정보성, 위험 아님) ──
   *  level: "nxt_only" (NXT 종목만 거래 가능) | "blocked" (거래 시간 외) */
  orderTimeBlocked: { level: 'nxt_only' | 'blocked'; reason: string } | null

  /* ── 리스크 매니저 차단 상태 (손실 한도 도달 등) ── */
  riskBlockStatus: { side: string; reason: string } | null

  /* ── 실시간 통신 지연 200ms 초과 상태 (매수/매도 공통 차단) ── */
  realtimeLatencyExceeded: boolean

  /* ── 일일 매수 상태 로드 실패 (매수 전용 차단) ── */
  dailyBuyStateFailed: boolean

  /* ── 테스트 예수금 검증 실패 (사후 1회성 — 헤더 칩 알림) ── */
  testCashFailed: { stk_cd: string; reason: string } | null

  /* ── 엔진 기동 상태 경고 (P21 — 지속 상태, 엔진 재기동 시 해제) ── */
  positionBuildFailed: boolean  // 테스트모드 포지션 구축 실패 (보유 종목 비어있음)
  degradedMode: boolean         // 감소 모드 기동 (종목 데이터 불완전)
}

const initialState: UIState = {
  settings: null,
  status: null,
  sectorStatus: null,
  selectedSector: null,
  initialized: false,
  engineReady: false,
  avgAmtProgress: null,
  marketPhase: { krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false },
  buyLimitStatus: { daily_buy_spent: 0 },
  wsSubscribeStatus: { index_subscribed: false, quote_subscribed: false },
  sectorScoresDelta: null,
  sectorScoresWaiting: false,
  sectorSummary: null,
  engineReloadComplete: false,
  receiveRate: null,
  indexData: null,
  circuitBreakerOpen: null,
  orderTimeBlocked: null,
  riskBlockStatus: null,
  realtimeLatencyExceeded: false,
  dailyBuyStateFailed: false,
  testCashFailed: null,
  positionBuildFailed: false,
  degradedMode: false,
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

/* ── settings-changed: 설정만 갱신 (증분 갱신 대응) ── */

// AppSettings가 `[key: string]: unknown` 인덱스 시그니처를 가져 'delta' in data만으로는
// 타입 좁히기가 불가능하므로 명시적 type predicate로 delta payload 식별 (P23 타입 계약).
function isSettingsDeltaEvent(data: SettingsChangedEvent): data is SettingsChangedDeltaEvent {
  return typeof data === 'object' && data !== null && 'delta' in data && (data as { delta?: unknown }).delta === true
}

export function applySettingsChanged(data: SettingsChangedEvent): void {
  if (isSettingsDeltaEvent(data)) {
    const changed = data.changed
    uiStore.setState((state) => ({
      settings: state.settings ? { ...state.settings, ...changed } : (changed as AppSettings),
    }))
  } else {
    uiStore.setState({ settings: data as AppSettings })
  }
}

/* ── engine-ready: 엔진 준비 완료 + 서킷브레이커 알림 해제 ── */
export function applyEngineReloadComplete(): void {
  uiStore.setState({ engineReloadComplete: true, circuitBreakerOpen: null })
}

/* ── circuit-breaker-open: OMS 서킷브레이커 발동 알림 ──
 *  message가 빈 문자열이면 복구 신호 — 칩 해제 (P21 사용자 투명성). */
export function applyCircuitBreakerOpen(data: { message?: string }): void {
  if (data.message) {
    uiStore.setState({ circuitBreakerOpen: { message: data.message } })
  } else {
    uiStore.setState({ circuitBreakerOpen: null })
  }
}

/* ── 서킷브레이커 알림 수동 해제 (사용자 클릭) ── */
export function clearCircuitBreakerOpen(): void {
  uiStore.setState({ circuitBreakerOpen: null })
}

/* ── order-time-blocked: 체결 불가 시간대 주문 상태 갱신 ──
 *  백엔드 get_order_time_block_status()의 (level, reason) 튜플을 payload로 수신.
 *  level="ok" 또는 누락 시 null (칩 숨김). "nxt_only"/"blocked" 시 정보 표시. */
export function applyOrderTimeBlocked(data: { level?: string; reason?: string }): void {
  if (data.level && data.level !== 'ok') {
    const level = data.level === 'blocked' ? 'blocked' : 'nxt_only'
    uiStore.setState({ orderTimeBlocked: { level, reason: data.reason ?? '시간대 정보 없음' } })
  } else {
    uiStore.setState({ orderTimeBlocked: null })
  }
}

/* ── 주문 일시중단 상태 수동 해제 (사용자 클릭) ── */
export function clearOrderTimeBlocked(): void {
  uiStore.setState({ orderTimeBlocked: null })
}

/* ── risk-block-status: 리스크 매니저 차단 상태 갱신 ── */
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

/* ── realtime-latency-status: 실시간 통신 지연 200ms 초과 상태 갱신 (매수/매도 공통) ── */
export function applyRealtimeLatencyStatus(data: { blocked?: boolean }): void {
  uiStore.setState({ realtimeLatencyExceeded: !!data.blocked })
}

/* ── daily-buy-state-status: 일일 매수 상태 로드 실패 갱신 (매수 전용) ── */
export function applyDailyBuyStateStatus(data: { failed?: boolean }): void {
  uiStore.setState({ dailyBuyStateFailed: !!data.failed })
}

/* ── test-cash-failed: 테스트 예수금 검증 실패 갱신 (사후 1회성 — 헤더 칩) ── */
export function applyTestCashFailed(data: { failed?: boolean; stk_cd?: string; reason?: string }): void {
  if (data.failed) {
    uiStore.setState({ testCashFailed: { stk_cd: data.stk_cd ?? '', reason: data.reason ?? '테스트 잔고 부족 — 매수 거부' } })
  } else {
    uiStore.setState({ testCashFailed: null })
  }
}

/* ── 테스트 잔고 부족 알림 수동 해제 (사용자 클릭) ── */
export function clearTestCashFailed(): void {
  uiStore.setState({ testCashFailed: null })
}

/* ── 엔진 기동 상태 경고 수동 해제 (사용자 클릭 — 다음 index-data까지 유지) ── */
export function clearPositionBuildFailed(): void {
  uiStore.setState({ positionBuildFailed: false })
}

export function clearDegradedMode(): void {
  uiStore.setState({ degradedMode: false })
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

/* ── index-data: 업종지수 실시간 갱신 (업종지수 전용 — 엔진 상태는 engine-status 이벤트) ── */
export function applyIndexData(data: IndexData): void {
  const upcode = data.upcode
  if (!upcode) return
  uiStore.setState((state) => {
    const prev = state.indexData ?? {}
    return { indexData: { ...prev, [upcode]: data } }
  })
}

/* ── engine-status: 엔진 상태 갱신 (broker_statuses + market_phase + 엔진 상태 필드) ── */
export function applyEngineStatus(data: EngineStatusPayload): void {
  uiStore.setState((state) => {
    const patch: Partial<UIState> = {}
    if (data.broker_statuses) {
      patch.status = state.status
        ? { ...state.status, broker_statuses: data.broker_statuses }
        : { broker_statuses: data.broker_statuses } as EngineStatus
    }
    if (data.market_phase) {
      patch.marketPhase = { ...state.marketPhase, ...data.market_phase }
    }
    if (data.position_build_failed !== undefined) {
      patch.positionBuildFailed = !!data.position_build_failed
    }
    if (data.degraded_mode !== undefined) {
      patch.degradedMode = !!data.degraded_mode
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
    realtimeLatencyExceeded: false,
    dailyBuyStateFailed: false,
    testCashFailed: null,
    positionBuildFailed: !!(data.position_build_failed),
    degradedMode: !!(data.degraded_mode),
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
