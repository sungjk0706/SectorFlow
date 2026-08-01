// frontend/src/pages/sector-stock-rows.ts
// 업종별 종목 실시간 시세 — 순수 로직 모듈 (컬럼 정의 + 행 계산)
// sector-stock.ts(Web Component)가 import. 상태 없음, 부작용 없음.

import { type ColumnDef, type GroupRow as DataTableGroupRow, type TableRow } from '../components/common/data-table'
import { createStockNameColumn, makeSeqColumn, makeCodeColumn, makePriceColumn, makeChangeColumn, makeRateColumn, makeStrengthColumn, makeAmountColumn, makeAvgAmountColumn, COLOR } from '../components/common/ui-styles'
import { type MasterStock, type SectorScoreRow } from '../types'
// filterStocksBySearch는 범용 유틸 → utils/stock-search.ts로 이동 (F03-10, P23)

/* ── ColumnDef 배열 (10개 컬럼) ── */

export const COLUMNS: ColumnDef<DataRowItem>[] = [
  makeSeqColumn<DataRowItem>((item) => item.seq),
  makeCodeColumn<DataRowItem>((item) => item.stock.code),
  {
    ...createStockNameColumn<DataRowItem>(
      (item: DataRowItem) => ({
        name: item.stock.name,
        market_type: item.stock.market_type,
        nxt_enable: item.stock.nxt_enable
      })
    ),
    minWidth: 130,
    maxWidth: 200,
  },
  makePriceColumn<DataRowItem>(
    (item) => item.stock.cur_price != null ? Number(item.stock.cur_price) : null,
    (item) => item.stock.change_rate != null ? Number(item.stock.change_rate) : null,
  ),
  makeChangeColumn<DataRowItem>((item) => item.stock.change != null ? Number(item.stock.change) : null),
  makeRateColumn<DataRowItem>((item) => item.stock.change_rate != null ? Number(item.stock.change_rate) : null),
  makeStrengthColumn<DataRowItem>((item) => item.stock.strength != null ? parseFloat(String(item.stock.strength)) : null),
  {
    ...makeAmountColumn<DataRowItem>((item) => item.stock.trade_amount != null ? Number(item.stock.trade_amount) : null),
    maxWidth: 90,
  },
  {
    ...makeAvgAmountColumn<DataRowItem>((item) => Number(item.stock.avg_amt_5d) || 0),
    maxWidth: 90,
  },
]

/* ── 행 타입 ── */

interface GroupRowItem {
  type: 'group'
  sector: string
  label: string
  score?: number
  opacity: string
  bgColor: string
}

export interface DataRowItem {
  type: 'data'
  stock: MasterStock
  opacity: string
  eliminated: boolean
  seq: number
}

export type RowItem = GroupRowItem | DataRowItem

/* ── 업종명 검색 필터링 ── */

export function filterSectorsByName(
  stocks: Record<string, MasterStock>,
  query: string,
): Set<string> | null {
  const q = query.trim().toLowerCase()
  if (!q) return null
  const sectors = new Set<string>()
  for (const s of Object.values(stocks)) {
    const sector = (s.sector || '미분류').toLowerCase()
    if (sector.includes(q)) {
      sectors.add(s.sector || '미분류')
    }
  }
  return sectors
}

/* ── RowItem → TableRow<DataRowItem> 매핑 ── */

export function mapRowsToTableRows(rows: RowItem[]): TableRow<DataRowItem>[] {
  return rows.map(item => {
    if (item.type === 'group') {
      return {
        type: 'group' as const,
        label: item.label,
        key: 'g-' + item.sector,
        score: item.score,
        style: { opacity: item.opacity, background: item.bgColor },
      } satisfies DataTableGroupRow
    }
    return item
  })
}

/* ── rows 계산 ── */

export function computeRows(
  stockMap: Record<string, MasterStock>,
  sectorScores: SectorScoreRow[],
  maxTargets: number,
  selectedSector: string | null,
  matchedCodes: Set<string> | null,
  matchedSectors: Set<string> | null,
  rowCache: Map<string, { stock: MasterStock; row: DataRowItem }>,
  marketPhase: { krx: string; nxt: string; is_nxt_only?: boolean },
): RowItem[] {
  // 업종별 종목 그룹핑
  const grouped = new Map<string, string[]>()
  for (const s of Object.values(stockMap)) {
    const sector = s.sector || '미분류'
    if (selectedSector && sector !== selectedSector) continue
    if (matchedSectors && !matchedSectors.has(sector)) continue
    if (matchedCodes && !matchedCodes.has(s.code)) continue

    // 5거래일 평균 거래대금 필터링은 백엔드에서 수행 (단일 소스 진리)

    let arr = grouped.get(sector)
    if (!arr) { arr = []; grouped.set(sector, arr) }
    arr.push(s.code)
  }

  // rank 오름차순 정렬 (모든 업종에 1..N 순위 부여됨, is_cutoff_passed로 통과 여부 구분)
  const sortedSectorScores = [...sectorScores].sort((a, b) => a.rank - b.rank)
  const sectorOrder = sortedSectorScores.map(s => s.sector)
  // selectedSector 또는 검색 모드: 빈 배열로 시작
  const orderedSectors = (selectedSector || matchedCodes || matchedSectors) ? [] : [...sectorOrder]

  if (selectedSector) {
    if (grouped.has(selectedSector)) {
      orderedSectors.push(selectedSector)
    }
  } else if (matchedCodes || matchedSectors) {
    // 검색 모드: 검색된 종목 또는 업종에 해당하는 업종만 표시
    for (const sector of grouped.keys()) {
      if (!orderedSectors.includes(sector)) {
        orderedSectors.push(sector)
      }
    }
  } else {
    // 전체 모드: 모든 업종 표시
    for (const sector of grouped.keys()) {
      if (!orderedSectors.includes(sector)) {
        orderedSectors.push(sector)
      }
    }
  }

  const scoreMap = new Map<string, number>()
  for (const sc of sectorScores) scoreMap.set(sc.sector, sc.final_score)

  const sectorRankMap = new Map<string, number>()
  for (let i = 0; i < sectorOrder.length; i++) sectorRankMap.set(sectorOrder[i], i + 1)

  const krxInactive = marketPhase.is_nxt_only === true
  const rows: RowItem[] = []
  let stockSeq = 0

  for (const sector of orderedSectors) {
    const codes = grouped.get(sector)
    const sectorScore = sortedSectorScores.find(s => s.sector === sector)
    const sectorRank = sectorScore?.rank ?? 0
    const isEliminated = !sectorScore?.is_cutoff_passed || sectorRank > maxTargets
    const opacity = '1'
    const bgColor = isEliminated ? COLOR.eliminatedBg : 'transparent'
    const score = scoreMap.get(sector)

    // NXT 전용 시간대: 이 업종의 활성 종목(NXT 지원)이 0개면 그룹 행도 숨김
    if (krxInactive && codes) {
      const hasActiveStock = codes.some(code => {
        const s = stockMap[code]
        return s && s.nxt_enable
      })
      if (!hasActiveStock) continue
    }

    rows.push({
      type: 'group',
      sector,
      label: `${sectorRankMap.get(sector) ?? 0}. ${sector}`,
      score,
      opacity,
      bgColor,
    })

    // 종목이 없으면 종목 행 추가 안 함
    if (!codes) continue

    // selectedSector 모드: 종목코드 기준 안정 정렬 (Map 삽입순서 변동 방지)
    const sortedCodes = selectedSector ? [...codes].sort() : codes

    for (const code of sortedCodes) {
      const stock = stockMap[code]
      if (!stock) continue
      // KRX 비활성 구간: KRX 단독 종목 (nxt_enable !== true)은 행 자체를 추가하지 않음 (숨김)
      if (krxInactive && !stock.nxt_enable) continue
      stockSeq++
      const rowOpacity = opacity

      // 행 객체 캐시: stock 참조가 같으면 이전 행 재사용
      const cached = rowCache.get(code)
      if (cached && cached.stock === stock && cached.row.opacity === rowOpacity && cached.row.eliminated === isEliminated && cached.row.seq === stockSeq) {
        rows.push(cached.row)
      } else {
        const row: DataRowItem = { type: 'data', stock, opacity: rowOpacity, eliminated: isEliminated, seq: stockSeq }
        rowCache.set(code, { stock, row })
        rows.push(row)
      }
    }
  }

  return rows
}
