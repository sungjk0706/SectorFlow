// frontend/src/stores/hotStore.ts
// Hot Store - 실시간 데이터 전용 (mutable, 고빈도 업데이트)
import { createStore } from './store'
import type {
  Position,
  SectorStock,
  SectorScoreRow,
  BuyTarget,
  AccountSnapshot,
  AccountUpdateEvent,
  SectorScoresEvent,
  RealDataEvent,
} from '../types'

/** 종목코드 정규화 헬퍼 */
export function normalizeStockCode(code: string | undefined | null): string {
  if (!code) return ''
  let cd = code.includes('_') ? code.split('_')[0] : code
  if (cd.startsWith('A')) cd = cd.substring(1)
  if (/^\d+$/.test(cd) && cd.length < 6) {
    cd = cd.padStart(6, '0')
  }
  return cd
}

/** 배열 → Record 변환 헬퍼 */
export function stocksToMap(stocks: SectorStock[]): Record<string, SectorStock> {
  const m: Record<string, SectorStock> = {}
  for (const s of stocks) {
    m[normalizeStockCode(s.code)] = s
  }
  return m
}

export interface HotState {
  /* ── 실시간 데이터 필드 ── */
  account: AccountSnapshot | null
  positions: Position[]
  positionCount: number
  sectorStocks: Record<string, SectorStock>
  sectorScores: SectorScoreRow[]
  buyTargets: BuyTarget[]
  sellHistory: Record<string, unknown>[]
  buyHistory: Record<string, unknown>[]
  dailySummary: Record<string, unknown>[]
}

const initialState: HotState = {
  account: null,
  positions: [],
  positionCount: 0,
  sectorStocks: {},
  sectorScores: [],
  buyTargets: [],
  sellHistory: [],
  buyHistory: [],
  dailySummary: [],
}

export const hotStore = createStore<HotState>(initialState)

/* ── 인덱스 캐시 (모듈 스코프 — Zustand state 외부) ── */
let _buyTargetIndexCache: Map<string, number> = new Map()
let _positionIndexCache: Map<string, number> = new Map()

/** buyTargets 배열로부터 code→index 캐시 재구축 */
export function rebuildBuyTargetIndex(targets: BuyTarget[]): void {
  const map = new Map<string, number>()
  for (let i = 0; i < targets.length; i++) {
    map.set(normalizeStockCode(targets[i].code), i)
  }
  _buyTargetIndexCache = map
}

/** positions 배열로부터 stk_cd→index 캐시 재구축 */
export function rebuildPositionIndex(positions: Position[]): void {
  const map = new Map<string, number>()
  for (let i = 0; i < positions.length; i++) {
    map.set(normalizeStockCode(positions[i].stk_cd), i)
  }
  _positionIndexCache = map
}

/** 캐시 조회 헬퍼 (외부 모듈에서 사용 가능) */
export function getBuyTargetIndex(code: string): number | undefined {
  return _buyTargetIndexCache.get(normalizeStockCode(code))
}

export function getPositionIndex(stkCd: string): number | undefined {
  return _positionIndexCache.get(normalizeStockCode(stkCd))
}

/* ── 실시간 데이터 액션 함수 ── */

/* ── account-update: 계좌·보유종목 갱신 (delta 지원) ── */
export function applyAccountUpdate(data: AccountUpdateEvent): void {
  // 경량화 페이로드 (수익현황 전용): position_count만 처리
  if ('position_count' in data) {
    const positionCount = (data as { position_count?: number }).position_count ?? 0
    const incomingSnap = data.snapshot
    const prevAccount = hotStore.getState().account
    const snapSame = incomingSnap && prevAccount
      && incomingSnap.deposit === prevAccount.deposit
      && incomingSnap.orderable === prevAccount.orderable
      && incomingSnap.total_eval_amount === prevAccount.total_eval_amount
      && incomingSnap.total_pnl === prevAccount.total_pnl
      && incomingSnap.total_pnl_rate === prevAccount.total_pnl_rate
      && incomingSnap.accumulated_investment === prevAccount.accumulated_investment
      && incomingSnap.initial_deposit === prevAccount.initial_deposit
    hotStore.setState({
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
      if (data.snapshot) hotStore.setState({ account: data.snapshot })
      return
    }
    hotStore.setState((state) => {
      const positions = [...state.positions]
      // removed_codes: 역순 splice 제거
      if (removed.length > 0) {
        const removedSet = new Set(removed.map(c => normalizeStockCode(c)))
        const indices: number[] = []
        for (let i = 0; i < positions.length; i++) {
          if (removedSet.has(normalizeStockCode(positions[i].stk_cd))) indices.push(i)
        }
        for (let i = indices.length - 1; i >= 0; i--) {
          positions.splice(indices[i], 1)
        }
      }
      // changed_positions: 인덱스 찾아 교체 또는 push
      for (const pos of changed) {
        const idx = positions.findIndex(p => normalizeStockCode(p.stk_cd) === normalizeStockCode(pos.stk_cd))
        if (idx >= 0) {
          positions[idx] = pos
        } else {
          positions.push(pos)
        }
      }
      rebuildPositionIndex(positions)
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
      }
    })
    return
  }
  const incomingPos = data.positions ?? []
  const prevPos = hotStore.getState().positions
  const positionsSame = prevPos.length === incomingPos.length && prevPos.every((p, i) => {
    const n = incomingPos[i]
    return p.stk_cd === n.stk_cd && p.qty === n.qty
      && p.buy_price === n.buy_price && p.avg_price === n.avg_price
      && p.cur_price === n.cur_price && p.pnl_rate === n.pnl_rate
  })
  const incomingSnap = data.snapshot ?? null
  const prevSnap = hotStore.getState().account
  const snapSame = incomingSnap && prevSnap
    && incomingSnap.total_buy_amount === prevSnap.total_buy_amount
    && incomingSnap.total_eval_amount === prevSnap.total_eval_amount
    && incomingSnap.total_pnl === prevSnap.total_pnl
    && incomingSnap.total_pnl_rate === prevSnap.total_pnl_rate
    && incomingSnap.deposit === prevSnap.deposit
    && incomingSnap.orderable === prevSnap.orderable
  const updates: Partial<HotState> = {}
  if (!snapSame) updates.account = incomingSnap
  if (!positionsSame) {
    updates.positions = incomingPos
    rebuildPositionIndex(incomingPos)
  }
  if (Object.keys(updates).length > 0) hotStore.setState(updates)
}

/* ── real-data: 키움 Raw FID를 직접 파싱하여 상태 갱신 (무결성 보장) ── */
export function applyRealData(item: RealDataEvent): void {
  const type = item.type;
  const rawCode = item.item;
  const vals = item.values;
  if (!rawCode || !vals) return;

  // 종목코드 정규화
  const code = normalizeStockCode(rawCode);

  // 1. 01/0B/0H (주식체결) 처리
  if (type === '01' || type === '0B' || type === '0H') {
    const rawPrice = vals['10'];
    const rawChange = vals['11'];
    const rawRate = vals['12'];
    const rawStrength = vals['228'];
    const rawAmount = vals['14'];

    if (!rawPrice) return;

  const parseKiwoomNum = (val: unknown): number | undefined => {
    if (val === undefined || val === null) return undefined;
    const s = String(val).trim();
    if (s === '') return undefined;
    let sign = 1;
    if (s.includes('-') || s.includes('▼')) sign = -1;
    const numStr = s.replace(/[^0-9.]/g, '');
    if (numStr === '') return undefined;
    return sign * Number(numStr);
  };

  const price = Math.abs(parseKiwoomNum(rawPrice) || 0);
  const parsedChange = parseKiwoomNum(rawChange);
  const parsedRate = parseKiwoomNum(rawRate);
  const parsedStrength = parseKiwoomNum(rawStrength);
  const rawAmt = parseKiwoomNum(rawAmount);
  const parsedAmount = rawAmt !== undefined ? rawAmt * 1000000 : undefined;

  hotStore.setState((state) => {
    let sectorStocks = state.sectorStocks;
    const old = sectorStocks[code];
    if (old) {
      const change = parsedChange !== undefined ? parsedChange : old.change;
      const rate = parsedRate !== undefined ? parsedRate : old.change_rate;
      const strength = parsedStrength !== undefined ? parsedStrength : old.strength;
      const amount = parsedAmount !== undefined ? parsedAmount : old.trade_amount;

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
      const change = parsedChange !== undefined ? parsedChange : t.change;
      const rate = parsedRate !== undefined ? parsedRate : t.change_rate;
      const strength = parsedStrength !== undefined ? parsedStrength : t.strength;

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
    }

    // no-op guard: 변경 없으면 setState 생략 (reference equality 유지)
    if (sectorStocks === state.sectorStocks && !buyTargetsChanged && !positionsChanged) return state;
    const patch: Partial<HotState> = {};
    if (sectorStocks !== state.sectorStocks) patch.sectorStocks = sectorStocks;
    if (buyTargetsChanged) patch.buyTargets = bt;
    if (positionsChanged) {
      patch.positions = newPositions;
    }
    return patch;
  });
  }
}

/* ── orderbook-update: 매수후보 호가잔량비 실시간 갱신 ── */
export function applyOrderbookUpdate(data: { code: string; bid: number; ask: number }): void {
  const code = normalizeStockCode(data.code);
  const { bid, ask } = data;
  if (!code) return;
  hotStore.setState((state) => {
    const bt = state.buyTargets;
    const idx = getBuyTargetIndex(code);
    if (idx === undefined) return state;
    const t = bt[idx];
    const prev = t.order_ratio;
    if (prev && prev[0] === bid && prev[1] === ask) return state;
    const newBt = [...bt];
    newBt[idx] = { ...t, order_ratio: [bid, ask] };
    return { buyTargets: newBt };
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
  hotStore.setState((state) => {
    const updates: Partial<HotState> = {}

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

/* ── buy-targets-update: 매수후보만 갱신 (내용 비교) ── */
export function applyBuyTargetsUpdate(data: { buy_targets: BuyTarget[] }): void {
  const incoming = data.buy_targets ?? []
  const prev = hotStore.getState().buyTargets
  const same = prev.length === incoming.length && prev.every((p, i) => {
    const n = incoming[i]
    return p.rank === n.rank && normalizeStockCode(p.code) === normalizeStockCode(n.code) && p.name === n.name
      && p.cur_price === n.cur_price && p.change === n.change && p.change_rate === n.change_rate
      && p.strength === n.strength
      && p.guard_pass === n.guard_pass && p.reason === n.reason
      && p.boost_score === n.boost_score
      && p.order_ratio?.[0] === n.order_ratio?.[0] && p.order_ratio?.[1] === n.order_ratio?.[1]
      && p.high_5d === n.high_5d
  })
  if (!same) {
    rebuildBuyTargetIndex(incoming)
    hotStore.setState({ buyTargets: incoming })
  }
}

/* ── sector-scores: 업종 점수·상태 갱신 (내용 비교) ── */
export function applySectorScores(data: SectorScoresEvent): void {
  const scores = data.scores ?? []
  const prev = hotStore.getState().sectorScores
  const same = prev.length === scores.length && prev.every((p, i) => {
    const n = scores[i]
    return p.rank === n.rank && p.sector === n.sector
      && p.final_score === n.final_score && p.rise_ratio === n.rise_ratio
      && p.total_trade_amount === n.total_trade_amount
      && p.total === n.total
  })
  if (!same) {
    hotStore.setState({ sectorScores: scores })
  }
}

/* ── sector-stocks-refresh: 필터 변경 시 종목 목록 교체 ── */
export function applySectorStocksRefresh(data: { stocks: SectorStock[] }): void {
  const stocks = data.stocks ?? []
  const newRecord = stocksToMap(stocks)
  hotStore.setState({ sectorStocks: newRecord })
}

/* ── order-filled: 체결 이벤트 -- 거래내역 테이블 즉시 갱신 ── */
export function applyOrderFilled(data: Record<string, unknown>): void {
  const side = data.side as string
  const state = hotStore.getState()
  if (side === 'BUY') {
    hotStore.setState({ buyHistory: [data, ...state.buyHistory] })
  } else if (side === 'SELL') {
    hotStore.setState({ sellHistory: [data, ...state.sellHistory] })
  }
}

/* ── sell-history-update: 매도 내역 갱신 ── */
export function applySellHistoryUpdate(data: { sell_history: Record<string, unknown>[] }): void {
  hotStore.setState({ sellHistory: data.sell_history ?? [] })
}

/* ── daily-summary-update: 일별 요약 갱신 ── */
export function applyDailySummaryUpdate(data: { daily_summary: Record<string, unknown>[] }): void {
  hotStore.setState({ dailySummary: data.daily_summary ?? [] })
}

/* ── buy-history-update: 매수 내역 갱신 ── */
export function applyBuyHistoryUpdate(data: { buy_history: Record<string, unknown>[] }): void {
  hotStore.setState({ buyHistory: data.buy_history ?? [] })
}

/* ── initial-snapshot (hotStore): 실시간 데이터 초기화 ── */
export function applyInitialSnapshotHot(data: Record<string, unknown>): void {
  const stocks = (data.sector_stocks as SectorStock[]) ?? []
  const scores = (data.sector_scores as SectorScoreRow[]) ?? []
  const newBuyTargets = (data.buy_targets as BuyTarget[]) ?? []
  const newPositions = (data.positions as Position[]) ?? []
  rebuildBuyTargetIndex(newBuyTargets)
  rebuildPositionIndex(newPositions)
  hotStore.setState({
    account: (data.account as AccountSnapshot) ?? null,
    positions: newPositions,
    sectorStocks: stocksToMap(stocks),
    sectorScores: scores,
    buyTargets: newBuyTargets,
    sellHistory: (data.sell_history as Record<string, unknown>[]) ?? [],
    buyHistory: (data.buy_history as Record<string, unknown>[]) ?? [],
    dailySummary: (data.daily_summary as Record<string, unknown>[]) ?? [],
  })
}
