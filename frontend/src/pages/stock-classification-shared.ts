// frontend/src/pages/stock-classification-shared.ts
// 종목분류 페이지 공통 모듈 — stock-classification.ts에서 이관 (F-04 분할, P24 단순성)
// 순수 이동, 동작 변경 없음. state 의존 없는 타입/유틸만 포함.

import { toastResult } from '../components/common/toast'
import { showAlertDialog } from '../components/common/dialog'
import { COLOR, RADIUS, SHADOW } from '../components/common/ui-styles'
import type { StockClassificationMutationResponse } from '../types'

/* ── 행 데이터 타입 ── */

export interface MasterRow {
  sectorName: string
  stockCount: number
  seq: number | null  // 미분류는 null (실제 업종이 아니므로 순번 미부여)
}

export interface DetailRow {
  code: string
  name: string
  market_type?: string
  nxt_enable?: boolean
}

export interface SearchResultRow {
  code: string
  name: string
  sector: string
  market_type?: string
  nxt_enable?: boolean
}

/* ── 순수 함수 ── */

/** 뮤테이션 응답 처리 — 성공/실패 토스트 + 장중 warning 토스트 */
export function handleMutationResult(res: StockClassificationMutationResponse): void {
  toastResult(res)
  if (res.ok && res.warning) {
    showAlertDialog({ title: '경고', message: res.warning })
  }
}

/** 배치 입력 파싱 — 따옴표 제거 후 쉼표, 탭, 줄바꿈, 공백, 괄호 기준으로 분리 */
export function parseBatchInput(input: string): string[] {
  const cleaned = input.replace(/["']/g, '')
  return cleaned.split(/[\s,()（）]+/).map(t => t.trim()).filter(t => t.length > 0)
}

/** 카드 래퍼 — 공통 컨테이너 스타일 */
export function cardWrap(): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, {
    background: COLOR.white, border: '1px solid ' + COLOR.borderDark, borderRadius: RADIUS.md,
    boxShadow: SHADOW.card,
    padding: '16px', marginBottom: '12px',
  })
  return div
}

/** 이동 확인 팝업 메시지 생성 (순수 함수) */
export function buildMoveMessage(
  codes: string[],
  allStocks: Map<string, { code: string; name: string }>,
  targetSector: string,
): string {
  const firstCode = codes[0]
  const firstName = allStocks.get(firstCode)?.name ?? firstCode
  if (codes.length === 1) {
    return `${firstName} 을(를) ${targetSector} 업종으로 이동하시겠습니까?`
  }
  return `${firstName} 외 ${codes.length - 1}개 종목을 ${targetSector} 업종으로 이동하시겠습니까?`
}
