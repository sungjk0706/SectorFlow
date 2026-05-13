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
  positionCount: number  /* 수익현황 페이지용 보유종목 수 (경량화 페이로드) */
  sectorStocks: Record<string, SectorStock>
  sectorOrder: string[]
  sectorScores: SectorScoreRow[]
  sectorStatus: SectorStatus | null
  sectorScoresDelta: { delta: boolean; changed_sectors: string[]; removed_sectors: string[] } | null
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
  backfilling: boolean

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
  positionCount: 0,
  sectorStocks: {},
  sectorOrder: [],
  sectorScores: [],
  sectorStatus: null,
  sectorScoresDelta: null,
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
  backfilling: false,
  avgAmtProgress: null,
  bootstrapStage: null,
  selectedSector: null,
  marketPhase: { krx: 'closed', nxt: 'closed' },
}

export const appStore = createStore<AppState>(initialState)

/* ── 인덱스 캐시 (모듈 스코프 — Zustand state 외부) ── */
let _buyTargetIndexCache: Map<string, number> = new Map()
let _positionIndexCache: Map<string, number> = new Map()

/** buyTargets 배열로부터 code→index 캐시 재구축 */
export function rebuildBuyTargetIndex(targets: BuyTarget[]): void {
  const map = new Map<string, number>()
  for (let i = 0; i < targets.length; i++) {
    map.set(targets[i].code, i)
  }
  _buyTargetIndexCache = map
}

/** positions 배열로부터 stk_cd→index 캐시 재구축 */
export function rebuildPositionIndex(positions: Position[]): void {
  const map = new Map<string, number>()
  for (let i = 0; i < positions.length; i++) {
    map.set(positions[i].stk_cd, i)
  }
  _positionIndexCache = map
}

/** 캐시 조회 헬퍼 (외부 모듈에서 사용 가능) */
export function getBuyTargetIndex(code: string): number | undefined {
  return _buyTargetIndexCache.get(code)
}

export function getPositionIndex(stkCd: string): number | undefined {
  return _positionIndexCache.get(stkCd)
}

/* ── 액션 메서드 (store 외부 함수) ── */

export function setConnected(v: boolean): void {
  appStore.setState({ connected: v })
}

export function setBackfilling(v: boolean): void {
  appStore.setState({ backfilling: v })
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
  const newBuyTargets = (data.buy_targets as BuyTarget[]) ?? []
  const newPositions = (data.positions as Position[]) ?? []
  rebuildBuyTargetIndex(newBuyTargets)
  rebuildPositionIndex(newPositions)
  appStore.setState({
    account: (data.account as AccountSnapshot) ?? null,
    positions: newPositions,
    sectorStocks: stocksToMap(stocks),
    sectorOrder: scores.map(s => s.sector),
    sectorScores: scores,
    sectorStatus: (data.sector_status as SectorStatus) ?? null,
    sectorSummary: (data.sector_summary as Record<string, unknown>) ?? null,
    buyTargets: newBuyTargets,
    settings: (data.settings as AppSettings) ?? null,
    status: (data.status as EngineStatus) ?? null,
    snapshotHistory: (data.snapshot_history as SnapshotHistory[]) ?? [],
    sellHistory: (data.sell_history as Record<string, unknown>[]) ?? [],
    buyHistory: (data.buy_history as Record<string, unknown>[]) ?? [],
    dailySummary: (data.daily_summary as Record<string, unknown>[]) ?? [],
    buyLimitStatus: (data.buy_limit_status as { daily_buy_spent: number }) ?? { daily_buy_spent: 0 },
    wsSubscribeStatus: (data.ws_subscribe_status as { index_subscribed: boolean; quote_subscribed: boolean }) ?? { index_subscribed: false, quote_subscribed: false },
    initialized: true,
    backfilling: false,
    engineReady: !!(data.bootstrap_done),
    marketPhase: (data.market_phase as { krx: string; nxt: string }) ?? { krx: 'closed', nxt: 'closed' },
    avgAmtProgress: data.avg_amt_refresh ? { current: (data.avg_amt_refresh as Record<string, unknown>).current as number ?? 0, total: (data.avg_amt_refresh as Record<string, unknown>).total as number ?? 0, done: false, status: ((data.avg_amt_refresh as Record<string, unknown>).status as string) || undefined } : data.confirmed_refresh ? { current: 0, total: 0, done: false, message: ((data.confirmed_refresh as Record<string, unknown>).message as string) || '', status: 'confirmed' } : null,
  })
}

/* ── account-update: 계좌·보유종목 갱신 (delta 지원) ── */
export function applyAccountUpdate(data: AccountUpdateEvent): void {
  if (!isVersionSupported(data, 'account-update')) return

  // 경량화 페이로드 (수익현황 전용): position_count만 처리
  if ('position_count' in data) {
    const positionCount = (data as { position_count?: number }).position_count ?? 0
    const incomingSnap = data.snapshot
    const prevAccount = appStore.getState().account
    const snapSame = incomingSnap && prevAccount
      && incomingSnap.deposit === prevAccount.deposit
      && incomingSnap.orderable === prevAccount.orderable
      && incomingSnap.total_eval_amount === prevAccount.total_eval_amount
      && incomingSnap.total_pnl === prevAccount.total_pnl
      && incomingSnap.total_pnl_rate === prevAccount.total_pnl_rate
      && incomingSnap.accumulated_investment === prevAccount.accumulated_investment
      && incomingSnap.initial_deposit === prevAccount.initial_deposit
    appStore.setState({
      account: snapSame ? prevAccount : (incomingSnap ?? prevAccount),
      positionCount,
    })
    return
  }

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
      rebuildPositionIndex(positions)
      // position_count도 업데이트 (보유종목 수)
      const positionCount = positions.filter(p => (p.qty ?? 0) > 0).length
      // snapshot 동등성 비교: 내용이 동일하면 참조 유지 (불필요한 리렌더 방지)
      const prevAccount = state.account
      const incomingSnap = data.snapshot
      const snapSame = incomingSnap && prevAccount
        && incomingSnap.deposit === prevAccount.deposit
        && incomingSnap.orderable === prevAccount.orderable
        && incomingSnap.total_eval_amount === prevAccount.total_eval_amount
        && incomingSnap.total_pnl === prevAccount.total_pnl
        && incomingSnap.total_pnl_rate === prevAccount.total_pnl_rate
        && incomingSnap.accumulated_investment === prevAccount.accumulated_investment
        && incomingSnap.initial_deposit === prevAccount.initial_deposit
      return {
        account: snapSame ? prevAccount : (incomingSnap ?? prevAccount),
        positions,
        positionCount,
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
    && incomingSnap.orderable === prevSnap.orderable
  const updates: Partial<AppState> = {}
  if (!snapSame) updates.account = incomingSnap
  if (!positionsSame) {
    updates.positions = incomingPos
    rebuildPositionIndex(incomingPos)
    updates.positionCount = incomingPos.filter(p => (p.qty ?? 0) > 0).length
  }
  if (Object.keys(updates).length > 0) appStore.setState(updates)
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
  // 선행 0 방어: "5930" → "005930" (백엔드 REST 정규화와 동일)
  let code = rawCode.includes('_') ? rawCode.split('_')[0] : rawCode;
  if (/^\d+$/.test(code) && code.length < 6) {
    code = code.padStart(6, '0');
  }

  // 1. 01/0B/0H (주식체결) 처리
  if (type === '01' || type === '0B' || type === '0H') {
    const rawPrice = vals['10'];
    const rawChange = vals['11'];
    const rawRate = vals['12'];
    const rawStrength = vals['228'];
    const rawAmount = vals['14'];

    if (!rawPrice) return;

    const price = Math.abs(+(String(rawPrice).replace(/,/g, '')) || 0);
    const change = +(String(rawChange).replace(/,/g, '')) || 0;
    const rate = +(String(rawRate).replace(/,/g, '')) || 0;
    const strength = +(String(rawStrength).replace(/,/g, '').trim()) || 0;
    const amount = (+(String(rawAmount).replace(/,/g, '')) || 0) * 1000000;

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

      // buyTargets: 인덱스 캐시 O(1) 조회 + 증분 갱신 (원본 배열 변이 없음)
      let bt = state.buyTargets;
      let buyTargetsChanged = false;
      const btIdx = getBuyTargetIndex(code);
      if (btIdx !== undefined) {
        const t = bt[btIdx];
        if (!(t.cur_price === price && t.change === change && t.change_rate === rate &&
              t.strength === strength)) {
          bt = [...bt];
          bt[btIdx] = { ...t, cur_price: price, change: change, change_rate: rate, strength: strength };
          buyTargetsChanged = true;
        }
      }

      // positions: 인덱스 캐시 O(1) 조회 + 증분 갱신 (원본 배열 변이 없음)
      const positions = state.positions;
      let newPositions = positions;
      let positionsChanged = false;
      const posIdx = getPositionIndex(code);
      if (posIdx !== undefined) {
        const pos = positions[posIdx];
        const buyAmt = pos.buy_amt ?? pos.buy_amount ?? 0;
        const qty = pos.qty ?? 0;
        const evalAmount = price * qty;
        const pnlAmount = buyAmt > 0 ? evalAmount - buyAmt : 0;
        const pnlRate = buyAmt > 0 ? Math.round((pnlAmount / buyAmt) * 10000) / 100 : 0;
        if (pos.cur_price !== price || pos.eval_amount !== evalAmount ||
            pos.pnl_amount !== pnlAmount || pos.pnl_rate !== pnlRate) {
          newPositions = [...positions];
          newPositions[posIdx] = { ...pos, cur_price: price, eval_amount: evalAmount, pnl_amount: pnlAmount, pnl_rate: pnlRate };
          positionsChanged = true;
        }
      } else if (positions.length > 0) {
      }

      // no-op guard: 변경 없으면 setState 생략 (reference equality 유지)
      if (sectorStocks === state.sectorStocks && !buyTargetsChanged && !positionsChanged) return state;
      const patch: Partial<AppState> = {};
      if (sectorStocks !== state.sectorStocks) patch.sectorStocks = sectorStocks;
      if (buyTargetsChanged) patch.buyTargets = bt;
      if (positionsChanged) {
        patch.positions = newPositions;
      }
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
    const idx = getBuyTargetIndex(code);
    if (idx === undefined) return state;
    const t = bt[idx];
    const prev = t.order_ratio;
    if (prev && prev[0] === bid && prev[1] === ask) return state;
    bt.splice(idx, 1, { ...t, order_ratio: [bid, ask] });
    return { buyTargets: bt };
  });
}


/* ── 공통 헬퍼: 지정된 필드를 null로 설정 ── */
function nullifyFields<T extends object>(
  obj: T,
  fields: string[]
): T {
  let changed = false
  const result: any = { ...obj }
  for (const f of fields) {
    if ((obj as any)[f] !== null && (obj as any)[f] !== undefined) {
      changed = true
      result[f] = null
    }
  }
  return changed ? result : obj
}

/* ── realtime-reset: 실시간 필드 일괄 초기화 ── */
export function applyRealtimeReset(): void {
  appStore.setState((state) => {
    const updates: Partial<AppState> = {}

    // sectorStocks: 현재가/대비/등락률/거래대금/체결강도
    const sectorStocks: Record<string, SectorStock> = {}
    let sectorChanged = false
    for (const [code, stock] of Object.entries(state.sectorStocks)) {
      const n = nullifyFields(stock, ['cur_price', 'change', 'change_rate', 'trade_amount', 'strength'])
      if (n !== stock) sectorChanged = true
      sectorStocks[code] = n
    }
    if (sectorChanged) updates.sectorStocks = sectorStocks

    // buyTargets: 현재가/대비/등락률/거래대금/체결강도/호가잔량비
    let buyTargetsChanged = false
    const buyTargets = state.buyTargets.map((t) => {
      const n = nullifyFields(t, ['cur_price', 'change', 'change_rate', 'trade_amount', 'strength', 'order_ratio'])
      if (n !== t) buyTargetsChanged = true
      return n
    })
    if (buyTargetsChanged) {
      updates.buyTargets = buyTargets
      rebuildBuyTargetIndex(buyTargets)
    }

    // positions: 현재가/대비/등락률
    let positionsChanged = false
    const positions = state.positions.map((p) => {
      const n = nullifyFields(p, ['cur_price', 'change', 'change_rate'])
      if (n !== p) positionsChanged = true
      return n
    })
    if (positionsChanged) {
      updates.positions = positions
      rebuildPositionIndex(positions)
    }

    return Object.keys(updates).length > 0 ? updates : state
  })
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

/* ── test-data-reset-completed: 통합 초기화 완료 ── */
export function applyTestDataResetCompleted(): void {
  console.log("[초기화] applyTestDataResetCompleted 실행")
  rebuildPositionIndex([])
  rebuildBuyTargetIndex([])
  console.log("Store 업데이트 전")
  appStore.setState({
    positions: [],
    snapshotHistory: [],
    sellHistory: [],
    buyHistory: [],
    dailySummary: [],
    buyLimitStatus: { daily_buy_spent: 0 },
    buyTargets: [],
  })
  console.log("Store 업데이트 후")
  const s = appStore.getState()
  console.log("positions 길이:", s.positions.length)
  if (s.account && s.settings) {
    const deposit = Number(s.settings.test_virtual_deposit) || 0
    appStore.setState({ account: { ...s.account, deposit, orderable: deposit } })
  }
}

/* ── buy-targets-update: 매수후보만 갱신 (내용 비교) ── */
export function applyBuyTargetsUpdate(data: { buy_targets: BuyTarget[] }): void {
  if (!isVersionSupported(data, 'buy-targets-update')) return
  const incoming = data.buy_targets ?? []
  const prev = appStore.getState().buyTargets
  const same = prev.length === incoming.length && prev.every((p, i) => {
    const n = incoming[i]
    return p.rank === n.rank && p.code === n.code && p.name === n.name
      && p.cur_price === n.cur_price && p.change === n.change && p.change_rate === n.change_rate
      && p.strength === n.strength
      && p.guard_pass === n.guard_pass && p.reason === n.reason
      && p.boost_score === n.boost_score
      && p.order_ratio?.[0] === n.order_ratio?.[0] && p.order_ratio?.[1] === n.order_ratio?.[1]
      && p.high_5d === n.high_5d
  })
  if (!same) {
    rebuildBuyTargetIndex(incoming)
    appStore.setState({ buyTargets: incoming })
  }
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
      && p.total === n.total
  })
  const updates: Partial<AppState> = { sectorStatus: data.status ?? null }
  if (!same) {
    updates.sectorScores = scores
    const newOrder = scores.map(s => s.sector)
    const prevOrder = appStore.getState().sectorOrder
    const orderSame = prevOrder.length === newOrder.length &&
                      prevOrder.every((s, i) => s === newOrder[i])
    if (!orderSame) {
      updates.sectorOrder = newOrder
    }
  }
  // delta 메타데이터 저장
  if (data.delta === true) {
    updates.sectorScoresDelta = {
      delta: true,
      changed_sectors: data.changed_sectors ?? [],
      removed_sectors: data.removed_sectors ?? []
    }
  } else {
    updates.sectorScoresDelta = null
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
