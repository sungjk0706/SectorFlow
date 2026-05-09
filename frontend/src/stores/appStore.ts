// frontend/src/stores/appStore.ts
// zustand 기반 useAppStore를 createStore<AppState>로 마이그레이션
import { createStore } from './store'
import type {
  AccountSnapshot,
  Position,
  SectorStock,
  SectorScoreRow,
  SectorStatus,
  BuyTarget,
  AppSettings,
  EngineStatus,
  SnapshotHistory,
  AccountUpdateEvent,
  SectorRefreshEvent,
  SectorScoresEvent,
  RealDataEvent,
} from '../types'

/** 현재 지원하는 데이터 스키마 버전 */
const SUPPORTED_VERSION = 1

/** 버전 검증 — 미지원 버전이면 false 반환 + 콘솔 경고 */
export function isVersionSupported(data: unknown, eventName: string): boolean {
  if (typeof data !== 'object' || data === null) return false
  const v = (data as Record<string, unknown>)._v
  if (v === SUPPORTED_VERSION) return true
  console.warn(`[WS] 미지원 버전 이벤트 무시: ${eventName} _v=${v}`)
  return false
}

/** 배열 → Record 변환 헬퍼 */
export function stocksToMap(stocks: SectorStock[]): Record<string, SectorStock> {
  const m: Record<string, SectorStock> = {}
  for (const s of stocks) m[s.code] = s
  return m
}

export interface AppState {
  /* ── 데이터 필드 ── */
  account: AccountSnapshot | null
  positions: Position[]
  sectorStocks: Record<string, SectorStock>
  sectorOrder: string[]
  sectorScores: SectorScoreRow[]
  sectorStatus: SectorStatus | null
  sectorSummary: Record<string, unknown> | null
  buyTargets: BuyTarget[]
  settings: AppSettings | null
  status: EngineStatus | null
  snapshotHistory: SnapshotHistory[]
  sellHistory: Record<string, unknown>[]
  buyHistory: Record<string, unknown>[]
  dailySummary: Record<string, unknown>[]

  /* ── 매수 한도 상태 ── */
  buyLimitStatus: { daily_buy_spent: number }

  /* ── WS 구독 상태 ── */
  wsSubscribeStatus: { index_subscribed: boolean; quote_subscribed: boolean }

  /* ── 업종 선택 필터 ── */
  selectedSector: string | null

  /* ── 연결 상태 ── */
  connected: boolean
  initialized: boolean
  engineReady: boolean

  /* ── 백그라운드 진행률 ── */
  avgAmtProgress: { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number } | null

  /* ── 부트스트랩 단계 ── */
  bootstrapStage: { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } } | null

  /* ── 장 상태 ── */
  marketPhase: { krx: string; nxt: string }
}

const initialState: AppState = {
  account: null,
  positions: [],
  sectorStocks: {},
  sectorOrder: [],
  sectorScores: [],
  sectorStatus: null,
  sectorSummary: null,
  buyTargets: [],
  settings: null,
  status: null,
  snapshotHistory: [],
  sellHistory: [],
  buyHistory: [],
  dailySummary: [],
  buyLimitStatus: { daily_buy_spent: 0 },
  wsSubscribeStatus: { index_subscribed: false, quote_subscribed: false },
  connected: false,
  initialized: false,
  engineReady: false,
  avgAmtProgress: null,
  bootstrapStage: null,
  selectedSector: null,
  marketPhase: { krx: 'closed', nxt: 'closed' },
}

export const appStore = createStore<AppState>(initialState)

/* ── 액션 메서드 (store 외부 함수) ── */

export function setConnected(v: boolean): void {
  appStore.setState({ connected: v })
}

export function setEngineReady(v: boolean): void {
  appStore.setState({ engineReady: v })
}

export function applyAvgAmtProgress(data: { current: number; total: number; done: boolean; message?: string; eta_sec?: number; status?: string; step?: number }): void {
  if (data.done && (data.status === 'completed' || data.status === 'confirmed')) {
    // 완료: 3초 후 자동 숨김
    appStore.setState({ avgAmtProgress: data })
    setTimeout(() => {
      const cur = appStore.getState().avgAmtProgress
      if (cur && (cur.status === 'completed' || cur.status === 'confirmed')) {
        appStore.setState({ avgAmtProgress: null })
      }
    }, 3000)
  } else if (data.done && (data.status === 'failed' || data.status === 'partial')) {
    // 실패/부분성공: 숨기지 않음
    appStore.setState({ avgAmtProgress: data })
  } else if (data.done && !data.status) {
    // 하위 호환: status 없이 done=true → 즉시 숨김
    appStore.setState({ avgAmtProgress: null })
  } else {
    appStore.setState({ avgAmtProgress: data })
  }
}

export function applyBootstrapStage(data: { stage_id: number; stage_name: string; total: number; progress?: { current: number; total: number } } | null): void {
  appStore.setState({ bootstrapStage: data })
}

/* ── initial-snapshot: 전체 상태 반영 ── */
export function applyInitialSnapshot(data: Record<string, unknown>): void {
  if (!isVersionSupported(data, 'initial-snapshot')) return
  const stocks = (data.sector_stocks as SectorStock[]) ?? []
  const scores = (data.sector_scores as SectorScoreRow[]) ?? []
  appStore.setState({
    account: (data.account as AccountSnapshot) ?? null,
    positions: (data.positions as Position[]) ?? [],
    sectorStocks: stocksToMap(stocks),
    sectorOrder: scores.map(s => s.sector),
    sectorScores: scores,
    sectorStatus: (data.sector_status as SectorStatus) ?? null,
    sectorSummary: (data.sector_summary as Record<string, unknown>) ?? null,
    buyTargets: (data.buy_targets as BuyTarget[]) ?? [],
    settings: (data.settings as AppSettings) ?? null,
    status: (data.status as EngineStatus) ?? null,
    snapshotHistory: (data.snapshot_history as SnapshotHistory[]) ?? [],
    sellHistory: (data.sell_history as Record<string, unknown>[]) ?? [],
    buyHistory: (data.buy_history as Record<string, unknown>[]) ?? [],
    dailySummary: (data.daily_summary as Record<string, unknown>[]) ?? [],
    buyLimitStatus: (data.buy_limit_status as { daily_buy_spent: number }) ?? { daily_buy_spent: 0 },
    wsSubscribeStatus: (data.ws_subscribe_status as { index_subscribed: boolean; quote_subscribed: boolean }) ?? { index_subscribed: false, quote_subscribed: false },
    initialized: true,
    engineReady: !!(data.bootstrap_done),
    marketPhase: (data.market_phase as { krx: string; nxt: string }) ?? { krx: 'closed', nxt: 'closed' },
    avgAmtProgress: data.avg_amt_refresh ? { current: (data.avg_amt_refresh as Record<string, unknown>).current as number ?? 0, total: (data.avg_amt_refresh as Record<string, unknown>).total as number ?? 0, done: false, status: ((data.avg_amt_refresh as Record<string, unknown>).status as string) || undefined } : data.confirmed_refresh ? { current: 0, total: 0, done: false, message: ((data.confirmed_refresh as Record<string, unknown>).message as string) || '', status: 'confirmed' } : null,
  })
}

/* ── account-update: 계좌·보유종목 갱신 (delta 지원) ── */
export function applyAccountUpdate(data: AccountUpdateEvent): void {
  if (!isVersionSupported(data, 'account-update')) return
  if (data.changed_positions) {
    const changed = data.changed_positions ?? []
    const removed = data.removed_codes ?? []
    // 변경/제거 모두 없으면 snapshot만 갱신 (positions 참조 유지)
    if (changed.length === 0 && removed.length === 0) {
      if (data.snapshot) appStore.setState({ account: data.snapshot })
      return
    }
    appStore.setState((state) => {
      const positions = [...state.positions]
      // removed_codes: 역순 splice 제거
      if (removed.length > 0) {
        const removedSet = new Set(removed)
        const indices: number[] = []
        for (let i = 0; i < positions.length; i++) {
          if (removedSet.has(positions[i].stk_cd)) indices.push(i)
        }
        for (let i = indices.length - 1; i >= 0; i--) {
          positions.splice(indices[i], 1)
        }
      }
      // changed_positions: 인덱스 찾아 교체 또는 push
      for (const pos of changed) {
        const idx = positions.findIndex(p => p.stk_cd === pos.stk_cd)
        if (idx >= 0) {
          positions[idx] = pos
        } else {
          positions.push(pos)
        }
      }
      return {
        account: data.snapshot ?? state.account,
        positions,
      }
    })
    return
  }
  const incomingPos = data.positions ?? []
  const prevPos = appStore.getState().positions
  const positionsSame = prevPos.length === incomingPos.length && prevPos.every((p, i) => {
    const n = incomingPos[i]
    return p.stk_cd === n.stk_cd && p.qty === n.qty
      && p.buy_price === n.buy_price && p.avg_price === n.avg_price
      && p.cur_price === n.cur_price && p.pnl_rate === n.pnl_rate
  })
  const incomingSnap = data.snapshot ?? null
  const prevSnap = appStore.getState().account
  const snapSame = incomingSnap && prevSnap
    && incomingSnap.total_buy_amount === prevSnap.total_buy_amount
    && incomingSnap.total_eval_amount === prevSnap.total_eval_amount
    && incomingSnap.total_pnl === prevSnap.total_pnl
    && incomingSnap.total_pnl_rate === prevSnap.total_pnl_rate
    && incomingSnap.deposit === prevSnap.deposit
    && incomingSnap.withdrawable === prevSnap.withdrawable
    && incomingSnap.pending_withdrawal === prevSnap.pending_withdrawal
  const updates: Partial<AppState> = {}
  if (!snapSame) updates.account = incomingSnap
  if (!positionsSame) updates.positions = incomingPos
  if (Object.keys(updates).length > 0) appStore.setState(updates)
}

/* ── sector-refresh: sector-scores + sector-tick으로 대체됨 (전환 기간 무시) ── */
export function applySectorRefresh(data: SectorRefreshEvent): void {
  if (!isVersionSupported(data, 'sector-refresh')) return
}

/* ── settings-changed: 설정만 갱신 ── */
export function applySettingsChanged(data: AppSettings): void {
  if (!isVersionSupported(data, 'settings-changed')) return
  appStore.setState({ settings: data })
}

/* ── index-refresh: 엔진 상태 + 장 상태 갱신 ── */
export function applyIndexRefresh(data: EngineStatus): void {
  if (!isVersionSupported(data, 'index-refresh')) return
  const patch: Partial<AppState> = { status: data }
  const mp = (data as unknown as Record<string, unknown>).market_phase as { krx: string; nxt: string } | undefined
  if (mp) patch.marketPhase = mp
  appStore.setState(patch)
}

/* ── real-data: 키움 Raw FID를 직접 파싱하여 상태 갱신 (무결성 보장) ── */
export function applyRealData(item: RealDataEvent): void {
  const type = item.type;
  const rawCode = item.item;
  const vals = item.values;
  if (!rawCode || !vals) return;

  // 종목코드 정규화: "028260_AL", "005930_NX" → "028260", "005930"
  const code = rawCode.includes('_') ? rawCode.split('_')[0] : rawCode;

  // 1. 01/0B/0H (주식체결) 처리
  if (type === '01' || type === '0B' || type === '0H') {
    const rawPrice = vals['10'];
    const rawChange = vals['11'];
    const rawRate = vals['12'];
    const rawStrength = vals['228'];
    const rawAmount = vals['14'];

    if (!rawPrice) return;

    const price = Math.abs(parseInt(String(rawPrice).replace(/,/g, '')) || 0);
    const change = parseInt(String(rawChange).replace(/,/g, '')) || 0;
    const rate = parseFloat(String(rawRate).replace(/,/g, '')) || 0;
    const strength = parseFloat(String(rawStrength).replace(/,/g, '').trim()) || 0;
    const amount = (parseInt(String(rawAmount).replace(/,/g, '')) || 0) * 1000000;

    appStore.setState((state) => {
      let sectorStocks = state.sectorStocks;
      const old = sectorStocks[code];
      if (old) {
        if (!(old.cur_price === price && old.change === change &&
            old.change_rate === rate && old.strength === strength &&
            old.trade_amount === amount)) {
          // 변경된 종목만 교체 — shallow-copy + single-key replacement
          sectorStocks = { ...sectorStocks, [code]: { ...old,
            cur_price: price, change: change, change_rate: rate,
            strength: strength, trade_amount: amount,
          }};
        }
      }

      const bt = state.buyTargets;
      const btIdx = bt.findIndex(t => t.code === code);
      let buyTargets = bt;
      if (btIdx >= 0) {
        const t = bt[btIdx];
        if (!(t.cur_price === price && t.change === change && t.change_rate === rate &&
              t.strength === strength && t.trade_amount === amount)) {
          buyTargets = [...bt];
          buyTargets[btIdx] = { ...t, cur_price: price, change: change, change_rate: rate, strength: strength, trade_amount: amount };
        }
      }

      // 보유종목 현재가 실시간 반영 + 평가손익/수익률 재계산
      let positions = state.positions;
      const posIdx = positions.findIndex(p => p.stk_cd === code);
      if (posIdx >= 0) {
        const pos = positions[posIdx];
        if (pos.cur_price !== price) {
          const buyAmt = pos.buy_amt ?? pos.buy_amount ?? 0;
          const qty = pos.qty ?? 0;
          const evalAmount = price * qty;
          const pnlAmount = buyAmt > 0 ? evalAmount - buyAmt : 0;
          const pnlRate = buyAmt > 0 ? Math.round((pnlAmount / buyAmt) * 10000) / 100 : 0;
          positions = [...positions];
          positions[posIdx] = { ...pos, cur_price: price, eval_amount: evalAmount, pnl_amount: pnlAmount, pnl_rate: pnlRate };
        }
      }

      if (sectorStocks === state.sectorStocks && buyTargets === bt && positions === state.positions) return state;
      const patch: Partial<AppState> = {};
      if (sectorStocks !== state.sectorStocks) patch.sectorStocks = sectorStocks;
      if (buyTargets !== bt) patch.buyTargets = buyTargets;
      if (positions !== state.positions) patch.positions = positions;
      return patch;
    });
  }

  // 2. 0J (업종지수) — 백엔드 index-refresh 이벤트로 처리됨 (여기서는 무시)

  // 3. 00 (주문체결) 처리 -- 필요 시 로깅 또는 토스트 알림 가능
  if (type === '00') {
    const side = vals['907']; // 1:매도, 2:매수
    const fillPrice = Math.abs(parseInt(vals['910']) || 0);
    const fillQty = Math.abs(parseInt(vals['911']) || 0);
    const unexQty = Math.abs(parseInt(vals['902']) || 0);
    console.log(`[체결알림] ${code} | ${side === '1' ? '매도' : '매수'} | ${fillPrice}원 | ${fillQty}주 체결 | 잔량 ${unexQty}주`);
  }
}

/* ── orderbook-update: 매수후보 호가잔량비 실시간 갱신 ── */
export function applyOrderbookUpdate(data: { code: string; bid: number; ask: number }): void {
  const { code, bid, ask } = data;
  if (!code) return;
  appStore.setState((state) => {
    const bt = state.buyTargets;
    const idx = bt.findIndex(t => t.code === code);
    if (idx < 0) return state;
    const t = bt[idx];
    const prev = t.order_ratio;
    if (prev && prev[0] === bid && prev[1] === ask) return state;
    const buyTargets = [...bt];
    buyTargets[idx] = { ...t, order_ratio: [bid, ask] };
    return { buyTargets };
  });
}


/* ── snapshot-update: 수익 이력만 갱신 ── */
export function applySnapshotUpdate(data: { snapshot_history: SnapshotHistory[] }): void {
  if (!isVersionSupported(data, 'snapshot-update')) return
  const incoming = data.snapshot_history ?? []
  const prev = appStore.getState().snapshotHistory

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

  appStore.setState({ snapshotHistory: incoming })
}

/* ── sell-history-update: 매도 내역 갱신 ── */
export function applySellHistoryUpdate(data: { sell_history: Record<string, unknown>[] }): void {
  appStore.setState({ sellHistory: data.sell_history ?? [] })
}

/* ── daily-summary-update: 일별 요약 갱신 ── */
export function applyDailySummaryUpdate(data: { daily_summary: Record<string, unknown>[] }): void {
  appStore.setState({ dailySummary: data.daily_summary ?? [] })
}

/* ── buy-history-update: 매수 내역 갱신 ── */
export function applyBuyHistoryUpdate(data: { buy_history: Record<string, unknown>[] }): void {
  appStore.setState({ buyHistory: data.buy_history ?? [] })
}

/* ── order-filled: 체결 이벤트 -- 거래내역 테이블 즉시 갱신 ── */
export function applyOrderFilled(data: Record<string, unknown>): void {
  const side = data.side as string
  const state = appStore.getState()
  if (side === 'BUY') {
    appStore.setState({ buyHistory: [data, ...state.buyHistory] })
  } else if (side === 'SELL') {
    appStore.setState({ sellHistory: [data, ...state.sellHistory] })
  }
}

/* ── buy-limit-status: 매수 한도 상태 갱신 ── */
export function applyBuyLimitStatus(data: { daily_buy_spent: number }): void {
  appStore.setState({ buyLimitStatus: { daily_buy_spent: data.daily_buy_spent ?? 0 } })
}

/* ── buy-targets-update: 매수후보만 갱신 (내용 비교) ── */
export function applyBuyTargetsUpdate(data: { buy_targets: BuyTarget[] }): void {
  if (!isVersionSupported(data, 'buy-targets-update')) return
  const incoming = data.buy_targets ?? []
  const prev = appStore.getState().buyTargets
  const same = prev.length === incoming.length && prev.every((p, i) => {
    const n = incoming[i]
    return p.rank === n.rank && p.code === n.code && p.name === n.name
      && p.cur_price === n.cur_price && p.change_rate === n.change_rate
      && p.strength === n.strength && p.trade_amount === n.trade_amount
      && p.guard_pass === n.guard_pass && p.reason === n.reason
      && p.boost_score === n.boost_score
  })
  if (!same) appStore.setState({ buyTargets: incoming })
}

/* ── sector-scores: 업종 점수·상태 갱신 + sectorOrder 갱신 (내용 비교) ── */
export function applySectorScores(data: SectorScoresEvent): void {
  if (!isVersionSupported(data, 'sector-scores')) return
  const scores = data.scores ?? []
  const prev = appStore.getState().sectorScores
  const same = prev.length === scores.length && prev.every((p, i) => {
    const n = scores[i]
    return p.rank === n.rank && p.sector === n.sector
      && p.final_score === n.final_score && p.rise_ratio === n.rise_ratio
      && p.total_trade_amount === n.total_trade_amount
      && p.total === n.total && p.rise_count === n.rise_count
  })
  const updates: Partial<AppState> = { sectorStatus: data.status ?? null }
  if (!same) {
    updates.sectorScores = scores
    updates.sectorOrder = scores.map(s => s.sector)
  }
  appStore.setState(updates)
}



/* ── sector-stocks-refresh: 필터 변경 시 종목 목록 교체 + sectorOrder 조건부 갱신 ── */
export function applySectorStocksRefresh(data: { stocks: SectorStock[] }): void {
  const stocks = data.stocks ?? []
  const newRecord = stocksToMap(stocks)
  appStore.setState((state) => {
    const newSectors = new Set<string>()
    for (const s of Object.values(newRecord)) {
      if (s.sector) newSectors.add(s.sector)
    }
    const kept = state.sectorOrder.filter(s => newSectors.has(s))
    const existing = new Set(kept)
    const added: string[] = []
    for (const s of newSectors) {
      if (!existing.has(s)) added.push(s)
    }
    const orderChanged = kept.length !== state.sectorOrder.length || added.length > 0
    return {
      sectorStocks: newRecord,
      ...(orderChanged ? { sectorOrder: [...kept, ...added] } : {}),
    }
  })
}

/* ── ws-subscribe-status: 구독 상태 갱신 ── */
export function applyWsSubscribeStatus(data: { index_subscribed: boolean; quote_subscribed: boolean }): void {
  if (!isVersionSupported(data, 'ws-subscribe-status')) return
  appStore.setState({ wsSubscribeStatus: data })
}

/* ── ws-connection-status: Kiwoom WebSocket 연결 상태 갱신 ── */
export function applyWsConnectionStatus(data: { connected: boolean }): void {
  if (!isVersionSupported(data, 'ws-connection-status')) return
  appStore.setState((state) => ({
    status: state.status ? { ...state.status, kiwoom_connected: data.connected } : null,
  }))
}

/* ── market-phase: 장 상태 갱신 ── */
export function applyMarketPhase(data: { krx: string; nxt: string }): void {
  appStore.setState({ marketPhase: data })
}

/* ── selectedSector: 토글 ── */
export function setSelectedSector(sector: string | null): void {
  appStore.setState((state) => ({
    selectedSector: state.selectedSector === sector ? null : sector,
  }))
}
