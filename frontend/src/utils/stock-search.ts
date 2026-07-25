// frontend/src/utils/stock-search.ts
// 종목명/코드 검색 필터 — 범용 유틸 (P23 공통 자산).
// sector-stock.ts(업종별 종목), buy-target.ts(매수후보) 공유.

import type { SectorStock } from '../types'

/** 종목명/코드 검색 필터 — 대소문자 무시, code 또는 name 부분 일치.
 *  query가 비어 있으면 null 반환 (필터 미적용 의미).
 *  matchedCodes: 검색에 일치한 종목코드 집합. */
export function filterStocksBySearch(
  stocks: Iterable<SectorStock>,
  query: string,
): Set<string> | null {
  const q = query.trim().toLowerCase()
  if (!q) return null
  const codes = new Set<string>()
  for (const s of stocks) {
    if (s.code.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q)) {
      codes.add(s.code)
    }
  }
  return codes
}
