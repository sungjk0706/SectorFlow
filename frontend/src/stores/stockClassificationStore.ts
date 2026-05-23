// frontend/src/stores/stockClassificationStore.ts — 업종분류 커스텀 상태 관리
import { createStore } from './store'
import type { AppSettings, StockClassificationChangedEvent } from '../types'

export interface StockClassificationState {
  sectors: Record<string, string>
  stockMoves: Record<string, string>
  deletedSectors: string[]
  mergedSectors: string[]
  editWindowOpen: boolean
  loading: boolean
  noSectorCount: number
  filter_summary?: string
  allStocks: Array<{
    code: string;
    name: string;
    sector: string;
    market_type?: string;
    nxt_enable?: boolean;
  }>
}

const initialState: StockClassificationState = {
  sectors: {},
  stockMoves: {},
  deletedSectors: [],
  mergedSectors: [],
  editWindowOpen: true,
  loading: false,
  noSectorCount: 0,
  filter_summary: "",
  allStocks: [],
}

export const stockClassificationStore = createStore<StockClassificationState>(initialState)

/** SSE `stock-classification-changed` 이벤트 수신 시 store 갱신 */
export function applyStockClassificationChanged(data: StockClassificationChangedEvent & { filter_summary?: string }): void {
  const cd = data.custom_data
  const currentState = stockClassificationStore.getState()
  stockClassificationStore.setState({
    sectors: cd?.sectors ?? {},
    stockMoves: cd?.stock_moves ?? {},
    deletedSectors: cd?.deleted_sectors ?? [],
    mergedSectors: data.merged_sectors ?? [],
    noSectorCount: data.no_sector_count ?? 0,
    filter_summary: data.filter_summary ?? currentState.filter_summary,
    allStocks: data.all_stocks ?? currentState.allStocks,
  })
}

/**
 * 편집 항상 허용 — 시간대 제한 제거.
 * 이전: ws_subscribe 범위 밖이면 true, 안이면 false.
 * 수정: 항상 true 반환 (장중 warning은 백엔드 응답으로 처리).
 */
export function computeEditWindowOpenByTime(_settings: AppSettings | null): boolean {
  return true
}
