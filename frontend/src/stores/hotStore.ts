// frontend/src/stores/hotStore.ts
// Hot Store - 실시간 데이터 전용 (mutable, 고빈도 업데이트)
import { createStore } from './store'
import type {
  Position,
  SectorStock,
  SectorScoreRow,
  AccountSnapshot,
  AccountUpdateEvent,
  AccountSummaryUpdateEvent,
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
  buyTargets: SectorStock[]
  sellHistory: Record<string, unknown>[]
  buyHistory: Record<string, unknown>[]
  /** WS push 전용 (최근 N거래일) — HTTP 덮어쓰기 금지 (P10 SSOT) */
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
export function rebuildBuyTargetIndex(targets: SectorStock[]): void {
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

/* ── 틱 디스패치 rAF 배칭 스케줄러 (세션 7) ──
 * 업계 표준 coalescing mutable store 패턴 (engineered.at "React at 1,000 updates/sec",
 * svelte #18093, sitepoint "Streaming Backends & React", LMAX Coalescing Ring Buffer):
 * 고빈도 틱은 in-place mutation으로 상태만 갱신하고, 디스패치는 rAF로 프레임당 1회 coalescing.
 * last-write-wins: 동일 code 여러 틱 → Set dedup → 1회 디스패치.
 * 초당 수십~수백 틱을 60fps(프레임당 1회)로 묶어 메인 스레드 점유 최소화 + 60fps 안정성.
 */
let _tickDirty = new Set<string>()
let _orderbookDirty = new Set<string>()
let _programDirty = new Set<string>()
let _tickRafId: number | null = null

/** 테스트/동기 호출용 — rAF 대기 없이 즉시 flush (프로덕션은 rAF 콜백이 호출). */
export function flushTickBatch(): void {
  _tickRafId = null
  // flush 중 새 틱이 들어오면 다음 프레임으로 연기하기 위해 Set을 스왑
  const ticks = _tickDirty; _tickDirty = new Set()
  const orderbooks = _orderbookDirty; _orderbookDirty = new Set()
  const programs = _programDirty; _programDirty = new Set()
  for (const code of ticks) {
    try { window.dispatchEvent(new CustomEvent('real-data-tick', { detail: code })) }
    catch (e) { console.error('[hotStore] dispatch real-data-tick error', e) }
  }
  for (const code of orderbooks) {
    try { window.dispatchEvent(new CustomEvent('orderbook-tick', { detail: code })) }
    catch (e) { console.error('[hotStore] dispatch orderbook-tick error', e) }
  }
  for (const code of programs) {
    try { window.dispatchEvent(new CustomEvent('program-tick', { detail: code })) }
    catch (e) { console.error('[hotStore] dispatch program-tick error', e) }
  }
}

/** 틱 디스패치를 다음 rAF 프레임으로 예약 (이미 예약 중이면 no-op). */
function scheduleTickFlush(): void {
  if (_tickRafId !== null) return
  _tickRafId = requestAnimationFrame(flushTickBatch)
}

/* ── 실시간 데이터 액션 함수 ── */

/* ── account-update: 계좌·보유종목 갱신 — 전체 payload (매도포지션/폴백) ── */
export function applyAccountUpdate(data: AccountUpdateEvent): void {
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
        positionCount: incomingSnap?.position_count ?? 0,
      }
    })
    return
  }
  // changed_positions 없음: snapshot만 갱신 (P20 — 빈 데이터 폴백 금지, snapshot 정상 경로)
  if (data.snapshot) hotStore.setState({ account: data.snapshot })
}

/* ── account-summary-update: 계좌·보유종목 갱신 — 경량화 payload (수익현황 전용) ── */
export function applyAccountSummaryUpdate(data: AccountSummaryUpdateEvent): void {
  const positionCount = data.position_count ?? 0
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

  // 경량화 snapshot은 Partial<AccountSnapshot> (7필드) — 기존 account와 merge하여 full 유지 (P10 SSOT, P22 정합성)
  const mergedAccount = snapSame
    ? prevAccount
    : (prevAccount ? { ...prevAccount, ...incomingSnap } : { ...incomingSnap } as AccountSnapshot)

  const changed = data.changed_positions
  const removed = data.removed_codes

  if ((changed && changed.length > 0) || (removed && removed.length > 0)) {
    hotStore.setState((state) => {
      const positions = [...state.positions]
      // removed_codes: 역순 splice 제거
      if (removed && removed.length > 0) {
        const removedSet = new Set(removed.map(c => normalizeStockCode(c)))
        const indices: number[] = []
        for (let i = 0; i < positions.length; i++) {
          if (removedSet.has(normalizeStockCode(positions[i].stk_cd))) indices.push(i)
        }
        for (let i = indices.length - 1; i >= 0; i--) {
          positions.splice(indices[i], 1)
        }
      }
      // changed_positions: 인덱스 찾아 merge (최소 필드만 덮어쓰고 나머지는 기존 값 유지)
      if (changed) {
        for (const pos of changed) {
          const idx = positions.findIndex(p => normalizeStockCode(p.stk_cd) === normalizeStockCode(pos.stk_cd))
          if (idx >= 0) {
            // 최소 필드 병합: 기존 position에 새 값만 덮어쓰기
            const existing = positions[idx]
            positions[idx] = { ...existing, ...pos }
          } else {
            positions.push(pos as Position)
          }
        }
      }
      rebuildPositionIndex(positions)
      return {
        account: mergedAccount,
        positions,
        positionCount,
      }
    })
  } else {
    hotStore.setState({
      account: mergedAccount,
      positionCount,
    })
  }
}

/* ── real-data: 키움 Raw FID를 직접 파싱하여 상태 갱신 (무결성 보장) ── */
/**
 * 키움 실시간 Raw 체결 이벤트 → in-place mutation + rAF 배칭 디스패치.
 *
 * 갱신 계약 (세션 7 — 업계 표준 coalescing mutable store 패턴):
 * - handled types: '01'/'0B'/'0H' (주식체결). 미지원 type은 스킵 (디스패치 안 함, 상태 미변경).
 * - in-place mutation: sectorStocks(SSOT) + buyTargets(파생 캐시) + positions(cur_price만).
 *   `hotStore.setState()`를 호출하지 않음 → 일반 `hotStore.subscribe()` 리스너 미발화.
 *   사유: setState 시 scheduleRender가 배열 참조 비교로 전체 재렌더 트리거 → 초저지연 저해.
 *   화면 갱신은 `real-data-tick` window 이벤트를 addEventListener로 수신한 페이지만 수행 (row-level).
 * - rAF 배칭: 변경 시 즉시 디스패치 ❌, dirty Set에 code 추가 후 다음 rAF 프레임에서 1회 디스패치.
 *   동일 code 여러 틱 → Set dedup → 1회 디스패치 (last-write-wins coalescing).
 *   초당 수십~수백 틱을 60fps로 묶어 메인 스레드 점유 최소화.
 * - 디스패치 조건: changed=true(실제 값 변경) 시에만. no-change 틱은 디스패치 안 함.
 * - payload: code 문자열 (정규화된 종목코드). 수신 측은 `dataTable.updateItemByKey(code)`로 O(1) 갱신.
 */
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

  const parseChangeRateToPercent = (val: unknown): number | undefined => {
    if (val === undefined || val === null) return undefined;
    const s = String(val).trim();
    if (s === '') return undefined;
    let sign = 1;
    if (s.includes('-') || s.includes('▼')) sign = -1;
    const numStr = s.replace(/[^0-9.]/g, '');
    if (numStr === '') return undefined;
    const raw = Number(numStr);
    const absRaw = Math.abs(raw);
    const isIntLike = Math.abs(raw - Math.round(raw)) < 1e-6;
    let result: number;
    if (isIntLike && absRaw >= 100) {
      result = absRaw / 1000.0;
    } else {
      result = absRaw;
    }
    if (result > 1000.0) return undefined;
    return sign * result;
  };

  const price = Math.abs(parseKiwoomNum(rawPrice) || 0);
  const parsedChange = parseKiwoomNum(rawChange);
  const parsedRate = parseChangeRateToPercent(rawRate);
  const parsedStrength = parseKiwoomNum(rawStrength);
  const rawAmt = parseKiwoomNum(rawAmount);
  const parsedAmount = rawAmt !== undefined ? rawAmt : undefined;

  // 2. In-place Mutation (객체 직접 수정) 및 커스텀 이벤트 발생
  // setState()를 호출하여 배열을 재생성하면 리액티브 구독 패턴에 의해 
  // 전체 리스트 재정렬 및 VirtualScroller 전체 diff가 발생하여 초저지연을 저해함.
  // 객체 속성만 직접 변경하고, UI 컴포넌트는 커스텀 이벤트를 구독하여 해당 DOM 셀만 갱신.

  let changed = false;

  const state = hotStore.getState();
  const sectorStocks = state.sectorStocks;
  const old = sectorStocks[code];
  if (old) {
    const change = parsedChange !== undefined ? parsedChange : old.change;
    const rate = parsedRate !== undefined ? parsedRate : old.change_rate;
    const strength = parsedStrength !== undefined ? parsedStrength : old.strength;
    const amount = parsedAmount !== undefined ? parsedAmount : old.trade_amount;

    if (!(old.cur_price === price && old.change === change &&
        old.change_rate === rate && old.strength === strength &&
        old.trade_amount === amount)) {
      // In-place mutation
      old.cur_price = price;
      old.change = change;
      old.change_rate = rate;
      old.strength = strength;
      old.trade_amount = amount;
      changed = true;
    }
  }

  // buyTargets 실시간 필드 — sectorStocks(SSOT)에서 파생된 캐시.
  // P10: sectorStocks가 실시간 시세의 단일 진실 소스. buyTargets의 실시간 필드는
  // DataTable의 O(1) updateItemByKey 갱신을 위해 in-place mutation으로 동기화하는
  // 파생 캐시(객체 참조를 DataTable currentRows가 보관 중).
  // P22: sectorStocks 교체/초기화 시 applySectorStocksRefresh/applyRealtimeReset에서
  // rebindBuyTargetsRealtime으로 재동기화됨.
  const bt = state.buyTargets;
  const btIdx = getBuyTargetIndex(code);
  if (btIdx !== undefined) {
    const t = bt[btIdx];
    const sectorStock = sectorStocks[code];
    if (sectorStock) {
      const change = sectorStock.change;
      const rate = sectorStock.change_rate;
      const strength = sectorStock.strength;
      const amount = sectorStock.trade_amount;

      if (!(t.cur_price === price && t.change === change && t.change_rate === rate &&
            t.strength === strength && t.trade_amount === amount)) {
        // In-place mutation — DataTable currentRows 객체 참조 유지
        t.cur_price = price;
        t.change = change;
        t.change_rate = rate;
        t.strength = strength;
        t.trade_amount = amount;
        changed = true;
      }
    }
  }

  // positions — cur_price만 갱신 (PnL/eval은 백엔드 account-update가 SSOT)
  const positions = state.positions;
  const posIdx = getPositionIndex(code);
  if (posIdx !== undefined) {
    const pos = positions[posIdx];
    if (pos.cur_price !== price) {
      pos.cur_price = price;
      changed = true;
    }
  }

  // 변경사항이 있을 경우 dirty Set에 추가하고 다음 rAF 프레임에서 디스패치 (coalescing).
  // 매 틱마다 즉시 디스패치하면 초당 수십~수백 회 디스패치 → 60fps 초과 → 끊김.
  // rAF 배칭: 프레임당 1회 flush, 동일 code 여러 틱 → Set dedup → 1회 디스패치.
  if (changed) {
    _tickDirty.add(code)
    scheduleTickFlush()
  }
  }
}

/* ── orderbook-update: 매수후보 호가잔량비 실시간 갱신 ── */
/**
 * 호가잔량비 갱신 계약 (applyRealData와 동일 — in-place mutation + rAF 배칭):
 * - in-place mutation: buyTargets[idx].order_ratio만 갱신. setState ❌ → subscribe 미발화.
 * - buyTargets에 없는 종목은 스킵 (idx === undefined).
 * - no-change(동일 bid/ask) 시 디스패치 안 함.
 * - rAF 배칭: dirty Set에 code 추가 후 다음 프레임에서 1회 디스패치 (last-write-wins).
 * - payload: code 문자열. 수신 측은 `dataTable.updateItemByKey(code)`로 O(1) 갱신.
 */
export function applyOrderbookUpdate(data: { code: string; bid: number; ask: number }): void {
  const code = normalizeStockCode(data.code);
  const { bid, ask } = data;
  if (!code) return;
  const state = hotStore.getState();
  const bt = state.buyTargets;
  const idx = getBuyTargetIndex(code);
  if (idx === undefined) return;
  const t = bt[idx];
  const prev = t.order_ratio;
  if (prev && prev[0] === bid && prev[1] === ask) return;

  // In-place mutation: 배열 복사 없이 직접 요소 수정
  t.order_ratio = [bid, ask];

  // rAF 배칭 — 프레임당 1회 coalescing 디스패치
  _orderbookDirty.add(code)
  scheduleTickFlush()
}

/* ── program-update: 매수후보 프로그램순매수 실시간 갱신 ── */
/**
 * 프로그램순매수 갱신 계약 (applyRealData/applyOrderbookUpdate와 동일 — in-place mutation + rAF 배칭):
 * - in-place mutation: buyTargets[idx].program_net_buy만 갱신. setState ❌ → subscribe 미발화.
 * - buyTargets에 없는 종목은 스킵 (idx === undefined).
 * - no-change(동일 net_buy) 시 디스패치 안 함.
 * - rAF 배칭: dirty Set에 code 추가 후 다음 프레임에서 1회 디스패치 (last-write-wins).
 * - payload: code 문자열. 수신 측은 `dataTable.updateItemByKey(code)`로 O(1) 갱신.
 */
export function applyProgramUpdate(data: { code: string; net_buy: number }): void {
  const code = normalizeStockCode(data.code);
  const { net_buy } = data;
  if (!code) return;
  const state = hotStore.getState();
  const bt = state.buyTargets;
  const idx = getBuyTargetIndex(code);
  if (idx === undefined) return;
  const t = bt[idx];
  if (t.program_net_buy === net_buy) return;

  // In-place mutation: 배열 복사 없이 직접 요소 수정
  t.program_net_buy = net_buy;

  // rAF 배칭 — 프레임당 1회 coalescing 디스패치
  _programDirty.add(code)
  scheduleTickFlush()
}

/* ── 공통 헬퍼: 지정된 필드를 null로 설정 ── */
function nullifyFields<T extends object>(
  obj: T,
  fields: string[]
): T {
  let changed = false
  const result = { ...obj } as Record<string, unknown>
  for (const f of fields) {
    const current = (obj as Record<string, unknown>)[f]
    if (current !== null && current !== undefined) {
      changed = true
      result[f] = null
    }
  }
  return changed ? (result as T) : obj
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

    // buyTargets: sectorStocks 실시간 필드가 null화되었으므로 파생 캐시도 동기화.
    // (applyRealData가 buyTargets 실시간 필드도 in-place mutation하므로
    //  reset 시 sectorStocks만 null화하면 buyTargets에 stale 값이 잔류 — P22 위반.
    //  rebindBuyTargetsRealtime 재사용 — in-place mutation으로 DataTable 객체 참조 유지)
    if (sectorChanged) {
      rebindBuyTargetsRealtime(state.buyTargets, sectorStocks)
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
// P10(SSOT) + P22(데이터 정합성): 백엔드 초기 buy-targets-update에 포함된 실시간 필드는
// sectorStocks와 불일치 가능 (조회 시점 차이). incoming 실시간 필드를 sectorStocks 기준으로
// 재결합하여 단일 소스 일관성 유지. buy-targets-delta의 added/changed 결합 패턴과 동일 (P23).
//
// same 비교 키 (세션 8 — 백엔드 _BUY_TARGET_CMP_KEYS와 일치, P23 일관성):
//   식별자: code, name (백엔드는 code 기준 delta이므로 불필요, 프론트는 배열 순서 비교용)
//   정적 필드: rank, boost_score, guard_pass, reason, order_ratio, program_net_buy,
//             high_5d, avg_amt_5d, news_boost
//   실시간 필드(cur_price/change/change_rate/strength/trade_amount)는 제외 —
//   틱 디스패치(real-data-tick)가 별도 갱신 담당, update same에서 비교하면 매 틱마다
//   setState 트리거하여 비용 낭비. 백엔드 _BUY_TARGET_CMP_KEYS도 동일 제외.
export function applyBuyTargetsUpdate(data: { buy_targets: SectorStock[] }): void {
  const sectorStocks = hotStore.getState().sectorStocks
  const incoming = (data.buy_targets ?? []).map(t => {
    const code = normalizeStockCode(t.code)
    const ss = sectorStocks[code]
    if (ss) {
      return {
        ...t,
        code,
        cur_price: ss.cur_price,
        change: ss.change,
        change_rate: ss.change_rate,
        strength: ss.strength,
        trade_amount: ss.trade_amount,
      }
    }
    return { ...t, code }
  })
  const prev = hotStore.getState().buyTargets
  const same = prev.length === incoming.length && prev.every((p, i) => {
    const n = incoming[i]
    return p.rank === n.rank && normalizeStockCode(p.code) === normalizeStockCode(n.code) && p.name === n.name
      && p.guard_pass === n.guard_pass && p.reason === n.reason
      && p.boost_score === n.boost_score
      && p.order_ratio?.[0] === n.order_ratio?.[0] && p.order_ratio?.[1] === n.order_ratio?.[1]
      && p.program_net_buy === n.program_net_buy
      && p.high_5d === n.high_5d
      && p.avg_amt_5d === n.avg_amt_5d
      && p.news_boost === n.news_boost
  })
  if (!same) {
    rebuildBuyTargetIndex(incoming)
    hotStore.setState({ buyTargets: incoming })
  }
}

/* ── buy-targets-delta: 매수후보 증분 갱신 (added/removed/changed) ── */
// P10(SSOT) + P22(데이터 정합성): added/changed 종목의 실시간 필드는 sectorStocks 기준으로
// 재결합하여 단일 소스 일관성 유지. applyBuyTargetsUpdate의 결합 패턴과 동일 (P23 일관성).
// binding.ts 인라인 45줄 → action 추출 (P23/P24, COUPLING-S8 후속).
export function applyBuyTargetsDelta(data: {
  added?: SectorStock[]
  removed?: string[]
  changed?: SectorStock[]
}): void {
  const { added, removed, changed } = data
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
          // P10(SSOT) + P22(데이터 정합성): sectorStocks가 실시간 데이터 단일 소스.
          // sectorStocks 누락 시 incoming 실시간 필드 유지 — applyBuyTargetsUpdate 결합 패턴과 동일 (P23 일관성).
          const sectorStock = state.sectorStocks[normalizeStockCode(item.code)]
          if (sectorStock) {
            buyTargets[idx] = {
              ...item,
              cur_price: sectorStock.cur_price,
              change: sectorStock.change,
              change_rate: sectorStock.change_rate,
              strength: sectorStock.strength,
              trade_amount: sectorStock.trade_amount,
            }
          } else {
            buyTargets[idx] = { ...item }
          }
        }
      }
    }
    if (added && added.length > 0) {
      // P10(SSOT) + P22(데이터 정합성): sectorStocks가 실시간 데이터 단일 소스.
      // sectorStocks 누락 시 incoming 실시간 필드 유지 — applyBuyTargetsUpdate 결합 패턴과 동일 (P23 일관성).
      const addedWithRealtime = added.map(item => {
        const sectorStock = state.sectorStocks[normalizeStockCode(item.code)]
        if (sectorStock) {
          return {
            ...item,
            cur_price: sectorStock.cur_price,
            change: sectorStock.change,
            change_rate: sectorStock.change_rate,
            strength: sectorStock.strength,
            trade_amount: sectorStock.trade_amount,
          }
        }
        return { ...item }
      })
      buyTargets = buyTargets === state.buyTargets ? [...buyTargets, ...addedWithRealtime] : [...buyTargets, ...addedWithRealtime]
    }
    if (buyTargets === state.buyTargets) return state
    rebuildBuyTargetIndex(buyTargets)
    return { buyTargets }
  })
}

/* ── sector-scores: 업종 점수·상태 갱신 (delta 머지) ── */
export function applySectorScores(data: SectorScoresEvent): void {
  if (data.delta && data.changed_scores) {
    // delta 모드: changed_scores를 기존 배열에 머지, removed_sectors 제거
    const current = hotStore.getState().sectorScores
    const removedSet = new Set(data.removed_sectors ?? [])
    const changedMap = new Map<string, SectorScoreRow>()
    for (const s of data.changed_scores) {
      changedMap.set(s.sector, s)
    }
    // 기존 배열에서 removed 제거 + changed 교체
    const merged: SectorScoreRow[] = []
    const seen = new Set<string>()
    for (const s of current) {
      if (removedSet.has(s.sector)) continue
      const changed = changedMap.get(s.sector)
      if (changed) {
        merged.push(changed)
        seen.add(s.sector)
      } else {
        merged.push(s)
      }
    }
    // 기존에 없던 새 섹터 추가
    for (const s of data.changed_scores) {
      if (!seen.has(s.sector)) {
        merged.push(s)
      }
    }
    hotStore.setState({ sectorScores: merged })
  } else if (data.scores) {
    // 전체 데이터: 전체 교체
    hotStore.setState({ sectorScores: data.scores })
  }
}

/* ── sector-stocks-refresh: 필터 변경 시 종목 목록 교체 ── */
// P10(SSOT) + P22(데이터 정합성): sectorStocks가 실시간 시세의 단일 진실 소스.
// buyTargets의 실시간 필드(cur_price/change/change_rate/strength/trade_amount)는
// DataTable의 O(1) updateItemByKey 갱신을 위한 파생 캐시이므로, sectorStocks 교체 시
// 새 기준점으로 재결합해야 다음 틱 전까지 stale 값이 남지 않는다.
// (buy-targets-delta 이벤트가 이미 동일한 결합 패턴을 사용 — P23 일관성)

/** buyTargets 요소의 실시간 필드를 sectorStocks 기준으로 in-place 재결합 */
function rebindBuyTargetsRealtime(
  buyTargets: SectorStock[],
  sectorStocks: Record<string, SectorStock>,
): boolean {
  let changed = false
  for (let i = 0; i < buyTargets.length; i++) {
    const t = buyTargets[i]
    const ss = sectorStocks[normalizeStockCode(t.code)]
    if (!ss) continue
    if (t.cur_price !== ss.cur_price) { t.cur_price = ss.cur_price; changed = true }
    if (t.change !== ss.change) { t.change = ss.change; changed = true }
    if (t.change_rate !== ss.change_rate) { t.change_rate = ss.change_rate; changed = true }
    if (t.strength !== ss.strength) { t.strength = ss.strength; changed = true }
    if (t.trade_amount !== ss.trade_amount) { t.trade_amount = ss.trade_amount; changed = true }
  }
  return changed
}

export function applySectorStocksRefresh(data: { stocks: SectorStock[] }): void {
  const stocks = data.stocks ?? []
  const newRecord = stocksToMap(stocks)
  hotStore.setState((state) => {
    // buyTargets 실시간 필드를 새 sectorStocks 기준으로 재결합
    // (in-place mutation — DataTable currentRows 객체 참조 유지, O(1) 갱신 경로 보존)
    rebindBuyTargetsRealtime(state.buyTargets, newRecord)
    return { sectorStocks: newRecord }
  })
}

/* ── sector-stocks-delta: 종목 목록 증분 갱신 (added/removed) ── */
// P10(SSOT) + P22(데이터 정합성): sectorStocks 증분 교체 후 buyTargets 실시간 필드도
// 새 기준으로 재결합. removed 종목이 buyTargets에 있으면 sectorStocks에서 사라져
// 다음 틱에서도 갱신 불가 → stale 잔류 방지. applySectorStocksRefresh와 동일 계약.
export function applySectorStocksDelta(data: { added: SectorStock[]; removed: string[] }): void {
  const added = data.added ?? []
  const removed = data.removed ?? []
  if (added.length === 0 && removed.length === 0) return
  hotStore.setState((state) => {
    let sectorStocks = state.sectorStocks
    if (removed.length > 0) {
      sectorStocks = { ...sectorStocks }
      for (const code of removed) {
        delete sectorStocks[normalizeStockCode(code)]
      }
    }
    if (added.length > 0) {
      sectorStocks = { ...sectorStocks, ...stocksToMap(added) }
    }
    if (sectorStocks === state.sectorStocks) return state
    // buyTargets 실시간 필드를 갱신된 sectorStocks 기준으로 재결합
    // (removed 종목은 sectorStocks에 없으므로 rebindBuyTargetsRealtime이 스킵 —
    //  buyTargets에서의 제거는 buy-targets-delta 이벤트가 담당하므로 여기서 보존)
    rebindBuyTargetsRealtime(state.buyTargets, sectorStocks)
    return { sectorStocks }
  })
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
  const newBuyTargets = ((data.buy_targets as SectorStock[]) ?? []).map(t => ({
    ...t,
    code: normalizeStockCode(t.code)
  }))
  const newPositions = (data.positions as Position[]) ?? []
  const accountSnap = (data.account as AccountSnapshot) ?? null
  rebuildBuyTargetIndex(newBuyTargets)
  rebuildPositionIndex(newPositions)
  // sector_stocks는 설계상 initial-snapshot에서 빈 배열로 전송됨 (engine_initial_data.py 참조).
  // 실제 데이터는 sector-stocks-refresh 이벤트로 별도 수신.
  // 재연결 시 빈 배열로 기존 데이터를 리셋하지 않도록 기존 값을 보존한다.
  const prev = hotStore.getState()
  const prevSectorStocks = prev.sectorStocks
  const newSectorStocks = stocks.length > 0 ? stocksToMap(stocks) : prevSectorStocks
  // P22(데이터 정합성) + P23(일관성): sellHistory/buyHistory/dailySummary도
  // sectorStocks와 동일하게, 재연결 시 빈 데이터로 기존 정상 값을 리셋하지 않도록 보존.
  // 빈 배열은 "데이터 없음"이 아니라 "초기 데이터 미준비/일시적 조회 실패"일 수 있으므로
  // 기존 값을 권위 있는 값으로 유지하고 다음 거래 이벤트로 갱신.
  const newSellHistory = (data.sell_history as Record<string, unknown>[]) ?? []
  const newBuyHistory = (data.buy_history as Record<string, unknown>[]) ?? []
  const newDailySummary = (data.daily_summary as Record<string, unknown>[]) ?? []
  hotStore.setState({
    account: accountSnap,
    positionCount: accountSnap?.position_count || newPositions.length,
    positions: newPositions,
    sectorStocks: newSectorStocks,
    sectorScores: scores,
    buyTargets: newBuyTargets,
    sellHistory: newSellHistory.length > 0 ? newSellHistory : prev.sellHistory,
    buyHistory: newBuyHistory.length > 0 ? newBuyHistory : prev.buyHistory,
    dailySummary: newDailySummary.length > 0 ? newDailySummary : prev.dailySummary,
  })
}
