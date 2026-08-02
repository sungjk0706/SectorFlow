// frontend/src/stores/hotStore.ts
// Hot Store - 실시간 데이터 전용 (mutable, 고빈도 업데이트)
import { createStore } from './store'
import type {
  Position,
  MasterStock,
  StockScore,
  SectorScoreRow,
  AccountSnapshot,
  AccountUpdateEvent,
  AccountSummaryUpdateEvent,
  SectorScoresEvent,
  RealDataEvent,
  FreshnessMetadata,
  FreshnessSnapshot,
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
export function stocksToMap(stocks: MasterStock[]): Record<string, MasterStock> {
  const m: Record<string, MasterStock> = {}
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
  masterStocks: Record<string, MasterStock>
  sectorScores: SectorScoreRow[]
  buyTargets: StockScore[]
  sellHistory: Record<string, unknown>[]
  buyHistory: Record<string, unknown>[]
  /** WS push 전용 (최근 N거래일) — HTTP 덮어쓰기 금지 (P10 SSOT) */
  dailySummary: Record<string, unknown>[]
  freshness: FreshnessSnapshot
}

const initialState: HotState = {
  account: null,
  positions: [],
  positionCount: 0,
  masterStocks: {},
  sectorScores: [],
  buyTargets: [],
  sellHistory: [],
  buyHistory: [],
  dailySummary: [],
  freshness: {
    account: { group: 'account', revision: 0 },
    buy_targets: { group: 'buy_targets', revision: 0 },
    sector_scores: { group: 'sector_scores', revision: 0 },
    sector_stocks: { group: 'sector_stocks', revision: 0 },
    trade_history: { group: 'trade_history', revision: 0 },
  },
}

export const hotStore = createStore<HotState>(initialState)

export function isFreshnessNewer(metadata: FreshnessMetadata | undefined): boolean {
  if (!metadata) return true
  return metadata.revision >= hotStore.getState().freshness[metadata.group].revision
}

export function recordFreshness(metadata: FreshnessMetadata): void {
  hotStore.setState((state) => ({
    freshness: { ...state.freshness, [metadata.group]: metadata },
  }))
}

/* ── 인덱스 캐시 (모듈 스코프 — Zustand state 외부) ── */
let _buyTargetIndexCache: Map<string, number> = new Map()
let _positionIndexCache: Map<string, number> = new Map()

/** buyTargets 배열로부터 code→index 캐시 재구축 */
export function rebuildBuyTargetIndex(targets: StockScore[]): void {
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

/* ── HTTP 페이지 진입 스냅샷 적용 ── */
export function applyAccountSnapshot(snapshot: AccountSnapshot, freshness: FreshnessMetadata): boolean {
  if (!isFreshnessNewer(freshness)) return false
  recordFreshness(freshness)
  hotStore.setState({ account: snapshot, positionCount: snapshot.position_count ?? hotStore.getState().positionCount })
  return true
}

export function applyPositionsSnapshot(positions: Position[], freshness: FreshnessMetadata): boolean {
  if (!isFreshnessNewer(freshness)) return false
  recordFreshness(freshness)
  rebuildPositionIndex(positions)
  hotStore.setState({ positions, positionCount: positions.length })
  return true
}

export function applyBuyTargetsSnapshot(targets: StockScore[], freshness: FreshnessMetadata): boolean {
  if (!isFreshnessNewer(freshness)) return false
  applyBuyTargetsUpdate({ buy_targets: targets, freshness })
  return true
}

export function applySectorScoresSnapshot(scores: SectorScoreRow[], freshness: FreshnessMetadata): boolean {
  if (!isFreshnessNewer(freshness)) return false
  applySectorScores({ scores, freshness, status: { total_stocks: scores.length } })
  return true
}

export function applyMasterStocksSnapshot(data: { stocks: MasterStock[]; freshness?: FreshnessMetadata }): boolean {
  if (data.freshness && !isFreshnessNewer(data.freshness)) return false
  if (data.freshness) recordFreshness(data.freshness)
  const stocks = data.stocks ?? []
  if (stocks.length === 0) return false
  const newRecord = stocksToMap(stocks)
  hotStore.setState((state) => ({
    masterStocks: { ...state.masterStocks, ...newRecord },
  }))
  return true
}

/* ── account-update: 계좌·보유종목 갱신 — 전체 payload (매도포지션/폴백) ── */
export function applyAccountUpdate(data: AccountUpdateEvent): void {
  if (!isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
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
  if (!isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
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
 * - handled types: '01'/'0B'/'0H' (종목체결). 미지원 type은 스킵 (디스패치 안 함, 상태 미변경).
 * - in-place mutation: masterStocks(표시 SSOT) + positions.cur_price(계산용) 2곳만.
 *   buyTargets는 정적 스코어만 보관하므로 실시간 필드 갱신 불필요 (P10 SSOT 강화).
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

  // 1. 01/0B/0H (종목체결) 처리
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
  const masterStocks = state.masterStocks;
  const old = masterStocks[code];
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

/* ── master-cache-delta: 마스터 캐시 부분 갱신 (호가·PGM) ── */
/**
 * 마스터 캐시 delta 갱신 계약 (applyRealData와 동일 — in-place mutation + rAF 배칭):
 * - in-place mutation: masterStocks[code]의 일부 필드만 갱신. setState ❌ → subscribe 미발화.
 *   사유: applyRealData와 동일 — setState 시 scheduleRender가 배열 참조 비교로 전체 재렌더 트리거.
 * - masterStocks에 없는 종목은 스킵 (old === undefined).
 * - no-change 시 디스패치 안 함.
 * - rAF 배칭: dirty Set에 code 추가 후 다음 프레임에서 1회 디스패치 (last-write-wins).
 *   호가 delta → orderbook-tick 이벤트, PGM delta → program-tick 이벤트 (기존 이벤트명 유지).
 * - payload: code 문자열. 수신 측은 `dataTable.updateItemByKey(code)`로 O(1) 갱신.
 */
export function applyMasterStocksDelta(data: { code: string; fields: Partial<MasterStock> }): void {
  const code = normalizeStockCode(data.code);
  if (!code) return;
  const fields = data.fields ?? {};
  const state = hotStore.getState();
  const old = state.masterStocks[code];
  if (!old) return;

  let changed = false;
  let isOrderbook = false;
  let isProgram = false;
  const oldRecord = old as unknown as Record<string, unknown>;
  for (const [key, value] of Object.entries(fields)) {
    if (oldRecord[key] === value) continue
    oldRecord[key] = value
    changed = true
    if (key === 'order_ratio') isOrderbook = true
    else if (key === 'program_net_buy') isProgram = true
  }

  if (!changed) return;
  if (isOrderbook) _orderbookDirty.add(code)
  if (isProgram) _programDirty.add(code)
  if (!isOrderbook && !isProgram) _tickDirty.add(code)
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
// P10/P21/P22: 백엔드 _reset_realtime_fields()가 sector_summary_cache를 None으로
// 리셋하고 임계값 게이트로 인해 sector-scores 전송이 차단되는 구간에
// 프론트 sectorScores도 함께 비워 좌/우 패널 시점을 동기화.
// 임계값 통과 후 notify_desktop_sector_score가 full payload로 전송 → applySectorScores가 자동 복구.
export function applyRealtimeReset(): void {
  hotStore.setState((state) => {
    const updates: Partial<HotState> = {}

    // sectorScores: 백엔드 sector_summary_cache=None 동기화 (reset 전 낡은 점수 잔류 방지)
    if (state.sectorScores.length > 0) {
      updates.sectorScores = []
    }

    // masterStocks: 현재가/대비/등락률/거래대금/체결강도
    const masterStocks: Record<string, MasterStock> = {}
    let masterChanged = false
    for (const [code, stock] of Object.entries(state.masterStocks)) {
      const n = nullifyFields(stock, ['cur_price', 'change', 'change_rate', 'trade_amount', 'strength'])
      if (n !== stock) masterChanged = true
      masterStocks[code] = n
    }
    if (masterChanged) updates.masterStocks = masterStocks

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
// P10(SSOT): buyTargets는 정적 스코어만 보관 (rank, guard_pass, reject_reason, boost_score,
// high_5d, news_boost, news_boost_title). 실시간 시세는 masterStocks가 단일 진실 소스이므로
// buyTargets에 실시간 필드를 재결합하지 않음 — 화면 표시는 masterStocks 참조.
//
// same 비교 키 (백엔드 _BUY_TARGET_CMP_KEYS와 일치, P23 일관성):
//   식별자: code, name (백엔드는 code 기준 delta이므로 불필요, 프론트는 배열 순서 비교용)
//   정적 필드: rank, boost_score, guard_pass, reject_reason, high_5d
//   실시간 필드(cur_price/change/change_rate/strength/trade_amount)는 제외 —
//   buyTargets에 더 이상 실시간 필드가 없으므로 비교 불필요.
//   order_ratio/program_net_buy 제외 — masterStocks로 이관, buyTargets에서 제거.
//   avg_amt_5d 제외 (T1 설계 수정 — avg_amt_5d 주인은 MasterStock).
//   news_boost 제외 (세션 3 — news-hit 이벤트가 단일 갱신 경로, P10 SSOT).
//   news_boost_title 제외 (세션 4 — 동일 단일 경로, P10 SSOT).
//   applyBuyTargetsUpdate는 초기 buy-targets-update 수신 시에만 news_boost 포함,
//   이후 갱신은 applyNewsHit이 담당하므로 same 비교에서 제외해 이중 갱신 경로 차단.
export function applyBuyTargetsUpdate(data: { buy_targets: StockScore[]; freshness?: FreshnessMetadata }): void {
  if (data.freshness && !isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
  const prev = hotStore.getState().buyTargets
  // P22: news_boost_title은 백엔드 스냅샷에 없음 (news-hit 이벤트가 단일 소스, 세션 4).
  //      전체 새로고침(buy-targets-update) 시 prev에서 보존 — news_boost > 0일 때만
  //      (뉴스 활성 상태). news_boost가 0/undefined면 title도 소멸(만료 일관성).
  const prevTitleByCode = new Map<string, string>()
  for (const t of prev) {
    if (t.news_boost_title) prevTitleByCode.set(normalizeStockCode(t.code), t.news_boost_title)
  }
  const incoming = (data.buy_targets ?? []).map(t => {
    const code = normalizeStockCode(t.code)
    const base: StockScore = { ...t, code }
    const newsBoost = Number(t.news_boost) || 0
    if (newsBoost > 0) {
      const preservedTitle = prevTitleByCode.get(code)
      if (preservedTitle) base.news_boost_title = preservedTitle
    }
    return base
  })
  const same = prev.length === incoming.length && prev.every((p, i) => {
    const n = incoming[i]
    return p.rank === n.rank && normalizeStockCode(p.code) === normalizeStockCode(n.code) && p.name === n.name
      && p.guard_pass === n.guard_pass && p.reject_reason === n.reject_reason
      && p.boost_score === n.boost_score
      && p.high_5d === n.high_5d
  })
  if (!same) {
    rebuildBuyTargetIndex(incoming)
    hotStore.setState({ buyTargets: incoming })
  }
}

/* ── news-hit: 뉴스 호재 가산점 갱신 (news_boost + boost_score 단일 전달 경로, P10 SSOT) ── */
// 백엔드 _handle_nws_news()가 뉴스 호재 매칭 시 news-hit 이벤트로 news_boost + boost_score + title 전달.
// buy-targets-delta에서는 news_boost 제외(세션 1)하고 본 action으로만 갱신 — 이중 갱신
// 경로 제거 (P10). applyBuyTargetsUpdate same 비교에서도 news_boost 제외(세션 3)와 짝.
// 수정안 3: boost_score도 백엔드에서 재계산 후 전달 → 프론트는 표시만 (P10 SSOT — 가산점 계산은 백엔드).
// P23: normalizeStockCode + hotStore.setState updater 패턴 (applyBuyTargetsDelta와 동일).
// P7: O(len(codes) * len(buyTargets)) — codes는 단일 뉴스 매칭 종목 수(소), buyTargets는
//     매수후보 N(소). applyBuyTargetsDelta의 findIndex 패턴과 동일 (P23 일관성).
// P20: codes/scores/boost_scores 누락 시 빈 배열로 명시적 처리 (폴백 아님). title 누락 시 빈 문자열.
// P21: title을 buyTargets[i].news_boost_title에 보관 → 📰 툴팁으로 호재 정보 노출 (세션 4).
// P25: 미매칭 시 setState 미발화 (불필요한 리렌더 방지). 해당 종목만 in-place patch.
export function applyNewsHit(data: { codes: string[]; scores: number[]; boost_scores?: number[]; title?: string }): void {
  const codes = data.codes ?? []
  const scores = data.scores ?? []
  const boostScores = data.boost_scores ?? []
  const title = data.title ?? ''
  if (codes.length === 0) return
  hotStore.setState((state) => {
    let buyTargets = state.buyTargets
    let changed = false
    // masterStocks news_boost 동기화 — 백엔드 master_stocks_cache["news_boost"]와 일치 (P10 SSOT).
    // news_boost_title은 MasterStock에 없으므로 masterStocks에는 news_boost만 갱신.
    const masterStocks = state.masterStocks
    for (let k = 0; k < codes.length; k++) {
      const code = normalizeStockCode(codes[k])
      const ms = masterStocks[code]
      if (ms && ms.news_boost !== (scores[k] ?? 0)) {
        ms.news_boost = scores[k] ?? 0
      }
      const idx = buyTargets.findIndex((t: StockScore) => normalizeStockCode(t.code) === code)
      if (idx >= 0) {
        if (!changed) { buyTargets = [...buyTargets]; changed = true }
        const patch: Partial<StockScore> = { news_boost: scores[k] ?? 0, news_boost_title: title }
        if (boostScores[k] != null) patch.boost_score = boostScores[k]
        buyTargets[idx] = { ...buyTargets[idx], ...patch }
      }
    }
    return changed ? { buyTargets } : state
  })
}

/* ── buy-targets-delta: 매수후보 증분 갱신 (added/removed/changed) ── */
// P10(SSOT): buyTargets는 정적 스코어만 보관. 실시간 시세는 masterStocks가 단일 진실 소스이므로
// added/changed 종목의 실시간 필드를 재결합하지 않음 — 화면 표시는 masterStocks 참조.
// applyBuyTargetsUpdate와 동일 패턴 (P23 일관성).
// binding.ts 인라인 45줄 → action 추출 (P23/P24, COUPLING-S8 후속).
export function applyBuyTargetsDelta(data: {
  freshness?: FreshnessMetadata
  added?: StockScore[]
  removed?: string[]
  changed?: StockScore[]
}): void {
  if (data.freshness && !isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
  const { added, removed, changed } = data
  hotStore.setState((state) => {
    let buyTargets = state.buyTargets
    if (removed && removed.length > 0) {
      const removedSet = new Set(removed.map(c => normalizeStockCode(c)))
      buyTargets = buyTargets.filter((t: StockScore) => !removedSet.has(normalizeStockCode(t.code)))
    }
    if (changed && changed.length > 0) {
      buyTargets = buyTargets === state.buyTargets ? [...buyTargets] : buyTargets
      for (const item of changed) {
        const idx = buyTargets.findIndex((t: StockScore) => normalizeStockCode(t.code) === normalizeStockCode(item.code))
        if (idx >= 0) {
          // P10: news_boost/news_boost_title은 news-hit 이벤트가 단일 전달 경로.
          //   백엔드 changed delta는 _BUY_TARGET_REALTIME_KEYS에 의해 news_boost를 pop 제거하므로
          //   item에 해당 키가 없음. 객체 통째 교체 시 undefined로 소거되면 📰 표시가 사라짐 (P21 위반).
          //   applyBuyTargetsUpdate prevTitleByCode 보존 패턴과 대칭 — 기존 값 보존 (P23 일관성).
          const prev = buyTargets[idx]
          buyTargets[idx] = {
            ...item,
            news_boost: prev.news_boost,
            news_boost_title: prev.news_boost_title,
          }
        }
      }
    }
    if (added && added.length > 0) {
      // P10(SSOT): buyTargets는 정적 스코어만 보관 — incoming을 그대로 사용.
      const addedItems = added.map(item => ({ ...item }))
      buyTargets = buyTargets === state.buyTargets ? [...buyTargets, ...addedItems] : [...buyTargets, ...addedItems]
    }
    if (buyTargets === state.buyTargets) return state
    rebuildBuyTargetIndex(buyTargets)
    return { buyTargets }
  })
}

/* ── sector-scores: 업종 점수·상태 갱신 (delta 머지) ── */
export function applySectorScores(data: SectorScoresEvent): void {
  if (data.freshness && !isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
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
    // 기존에 없던 새 업종 추가
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

/* ── master-cache-snapshot/delta: 마스터 종목 캐시 갱신 ── */
// P10(SSOT): masterStocks가 실시간 시세의 단일 진실 소스 (백엔드 master_stocks_cache 프론트 사본).
// buyTargets는 정적 스코어만 보관하므로 masterStocks 교체 시 재결합 불필요 — 동기화 로직 제거 (P22 강화).
// applyMasterStocksSnapshot은 위(applyMasterStocksSnapshot 함수)에서 정의 — 페이지 구독 신청 시 호출.
// applyMasterStocksDelta는 위(applyMasterStocksDelta 함수)에서 정의 — 호가·PGM 필드 부분 갱신.

/* ── sell-history-update: 매도 내역 갱신 ── */
export function applySellHistoryUpdate(data: { sell_history: Record<string, unknown>[]; freshness?: FreshnessMetadata }): void {
  if (data.freshness && !isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
  hotStore.setState({ sellHistory: data.sell_history ?? [] })
}

/* ── daily-summary-update: 일별 요약 갱신 ── */
export function applyDailySummaryUpdate(data: { daily_summary: Record<string, unknown>[]; freshness?: FreshnessMetadata }): void {
  if (data.freshness && !isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
  hotStore.setState({ dailySummary: data.daily_summary ?? [] })
}

/* ── buy-history-update: 매수 내역 갱신 ── */
export function applyBuyHistoryUpdate(data: { buy_history: Record<string, unknown>[]; freshness?: FreshnessMetadata }): void {
  if (data.freshness && !isFreshnessNewer(data.freshness)) return
  if (data.freshness) recordFreshness(data.freshness)
  hotStore.setState({ buyHistory: data.buy_history ?? [] })
}

/* ── initial-snapshot (hotStore): 실시간 데이터 초기화 ── */
export function applyInitialSnapshotHot(data: Record<string, unknown>): void {
  // 백엔드 initial-snapshot의 sector_stocks 키는 빈 배열로 전송됨 (engine_initial_data.py:65).
  // 키명은 백엔드가 아직 sector_stocks로 유지하므로 그대로 읽되 타입만 MasterStock[] 캐스팅.
  // 실제 데이터는 master-cache-snapshot 이벤트(페이지 구독 신청 시)로 별도 수신.
  const stocks = (data.sector_stocks as MasterStock[]) ?? []
  const scores = (data.sector_scores as SectorScoreRow[]) ?? []
  const newBuyTargets = ((data.buy_targets as StockScore[]) ?? []).map(t => ({
    ...t,
    code: normalizeStockCode(t.code)
  }))
  const newPositions = (data.positions as Position[]) ?? []
  const accountSnap = (data.account as AccountSnapshot) ?? null
  rebuildBuyTargetIndex(newBuyTargets)
  rebuildPositionIndex(newPositions)
  // 재연결 시 빈 배열로 기존 데이터를 리셋하지 않도록 기존 값을 보존한다.
  const prev = hotStore.getState()
  const prevMasterStocks = prev.masterStocks
  const newMasterStocks = stocks.length > 0 ? stocksToMap(stocks) : prevMasterStocks
  // P22(데이터 정합성) + P23(일관성): sellHistory/buyHistory/dailySummary도
  // masterStocks와 동일하게, 재연결 시 빈 데이터로 기존 정상 값을 리셋하지 않도록 보존.
  // 빈 배열은 "데이터 없음"이 아니라 "초기 데이터 미준비/일시적 조회 실패"일 수 있으므로
  // 기존 값을 권위 있는 값으로 유지하고 다음 거래 이벤트로 갱신.
  const newSellHistory = (data.sell_history as Record<string, unknown>[]) ?? []
  const newBuyHistory = (data.buy_history as Record<string, unknown>[]) ?? []
  const newDailySummary = (data.daily_summary as Record<string, unknown>[]) ?? []
  const freshness = data.freshness as FreshnessSnapshot | undefined
  hotStore.setState({
    account: accountSnap,
    positionCount: accountSnap?.position_count || newPositions.length,
    positions: newPositions,
    masterStocks: newMasterStocks,
    sectorScores: scores,
    buyTargets: newBuyTargets,
    sellHistory: newSellHistory.length > 0 ? newSellHistory : prev.sellHistory,
    buyHistory: newBuyHistory.length > 0 ? newBuyHistory : prev.buyHistory,
    dailySummary: newDailySummary.length > 0 ? newDailySummary : prev.dailySummary,
    freshness: freshness ? { ...prev.freshness, ...freshness } : prev.freshness,
  })
}
