// frontend/src/components/common/market-count-row.ts
// 시장별 종목수 카운트 행 공통 컴포넌트 — sector-stock.ts 인라인 패턴 추출 (P23 일관성)
// 사용처: sector-stock.ts (업종별 종목 시세), 2단계 sector-settings.ts (수신률 분리 배지)

import { FONT_WEIGHT, COLOR } from './ui-styles'

export interface MarketCounts {
  total: number
  krx: number
  nxt: number
  kospi: number
  kosdaq: number
}

export interface MarketCountRowHandle {
  /** 카운트 행 루트 요소 (부모 컨테이너에 appendChild) */
  el: HTMLElement
  /** 각 카운트 값만 갱신 (DOM 재구성 없이 textContent만 교체) */
  updateCounts(counts: MarketCounts): void
}

type NumSpanMap = Partial<Record<keyof MarketCounts, HTMLSpanElement>>

/**
 * 표준 세그먼트 추가 — 라벨(콜론 포함) + 숫자 + '종목' 단위.
 * 합계/KRX/코스피/코스닥 공통 구조. 첫 세그먼트는 marginLeft 없음.
 */
function _appendStandardSegment(
  parent: HTMLElement, label: string, labelColor: string, isFirst: boolean,
): HTMLSpanElement {
  const labelEl = document.createElement('span')
  Object.assign(labelEl.style, { color: labelColor, marginLeft: isFirst ? '' : '14px' })
  labelEl.textContent = label
  parent.appendChild(labelEl)
  const numSpan = document.createElement('span')
  Object.assign(numSpan.style, { color: COLOR.down, fontWeight: FONT_WEIGHT.semibold })
  parent.appendChild(numSpan)
  const suffix = document.createElement('span')
  Object.assign(suffix.style, { color: COLOR.neutral })
  suffix.textContent = '종목'
  parent.appendChild(suffix)
  return numSpan
}

/**
 * NXT 세그먼트 추가 — 빨강 라벨 + ▲ 삼각 + 콜론 + 숫자 + '종목' (sector-stock.ts 기존 패턴 보존).
 */
function _appendNxtSegment(parent: HTMLElement): HTMLSpanElement {
  const label = document.createElement('span')
  Object.assign(label.style, { color: COLOR.up, marginLeft: '14px' })
  label.textContent = 'NXT'
  parent.appendChild(label)
  const tri = document.createElement('span')
  Object.assign(tri.style, {
    display: 'inline-block', width: '0', height: '0',
    borderLeft: '5px solid transparent',
    borderBottom: `5px solid ${COLOR.up}`,
    marginRight: '3px', verticalAlign: 'middle',
  })
  parent.appendChild(tri)
  const colon = document.createElement('span')
  Object.assign(colon.style, { color: COLOR.up })
  colon.textContent = ':'
  parent.appendChild(colon)
  const numSpan = document.createElement('span')
  Object.assign(numSpan.style, { color: COLOR.down, fontWeight: FONT_WEIGHT.semibold })
  parent.appendChild(numSpan)
  const suffix = document.createElement('span')
  Object.assign(suffix.style, { color: COLOR.neutral })
  suffix.textContent = '종목'
  parent.appendChild(suffix)
  return numSpan
}

/**
 * 시장별 종목수 카운트 행 생성.
 * 구조: [합계: N종목] [KRX: N종목] [NXT▲: N종목] [코스피: N종목] [코스닥: N종목]
 * - NXT 라벨: 빨강(COLOR.up) + ▲ 삼각이모지
 * - 코스닥 라벨: 자주색(COLOR.kosdaq)
 * - 숫자: 파랑(COLOR.down) + semibold, 단위 '종목': 회색(COLOR.neutral)
 * - 값 갱신: updateCounts()로 textContent만 교체 (innerHTML 파괴 금지)
 */
export function createMarketCountRow(options: {
  showTotal?: boolean
  showKrx?: boolean
  showNxt?: boolean
  showKospi?: boolean
  showKosdaq?: boolean
} = {}): MarketCountRowHandle {
  const { showTotal = true, showKrx = true, showNxt = true, showKospi = true, showKosdaq = true } = options

  const el = document.createElement('div')
  Object.assign(el.style, { display: 'flex', alignItems: 'center', gap: '2px' })
  const numSpans: NumSpanMap = {}

  let isFirst = true
  if (showTotal) { numSpans.total = _appendStandardSegment(el, '합계:', COLOR.neutral, isFirst); isFirst = false }
  if (showKrx) { numSpans.krx = _appendStandardSegment(el, 'KRX:', COLOR.neutral, isFirst); isFirst = false }
  if (showNxt) { numSpans.nxt = _appendNxtSegment(el); isFirst = false }
  if (showKospi) { numSpans.kospi = _appendStandardSegment(el, '코스피:', COLOR.neutral, isFirst); isFirst = false }
  if (showKosdaq) { numSpans.kosdaq = _appendStandardSegment(el, '코스닥:', COLOR.kosdaq, isFirst) }

  function updateCounts(counts: MarketCounts): void {
    if (numSpans.total) numSpans.total.textContent = String(counts.total)
    if (numSpans.krx) numSpans.krx.textContent = String(counts.krx)
    if (numSpans.nxt) numSpans.nxt.textContent = String(counts.nxt)
    if (numSpans.kospi) numSpans.kospi.textContent = String(counts.kospi)
    if (numSpans.kosdaq) numSpans.kosdaq.textContent = String(counts.kosdaq)
  }

  return { el, updateCounts }
}
