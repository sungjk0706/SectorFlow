/**
 * 공통 UI 스타일 — 테이블 셀 컴포넌트.
 * ui-styles.ts에서 분할 (F06-03, P24 단순성).
 * 순수 이동 — 동작 변경 없음. 외부 import 경로는 메인에서 re-export 유지.
 */

import { COLOR, FONT_SIZE, FONT_WEIGHT, rateColor, pnlColor, strengthColor, changeArrow, fmtComma, fmtRate } from './ui-styles'

/* ── 종목명 셀 ── */

export function createStockNameCell(
  name: string,
  marketType?: string,
  nxtEnable?: boolean,
): HTMLElement {
  const wrap = document.createElement('span')
  wrap.style.position = 'relative'
  wrap.style.display = 'inline-block'
  wrap.style.width = '100%'

  const nameSpan = document.createElement('span')
  if (marketType === '10') nameSpan.style.color = COLOR.kosdaq
  nameSpan.textContent = name
  wrap.appendChild(nameSpan)

  if (nxtEnable) {
    const tri = document.createElement('span')
    Object.assign(tri.style, {
      position: 'absolute',
      right: '1px',
      bottom: '1px',
      width: '0',
      height: '0',
      borderLeft: '6px solid transparent',
      borderBottom: `6px solid ${COLOR.up}`,
    })
    wrap.appendChild(tri)
  }

  return wrap
}

/* ── 공통 셀 padding (private) ── */

const CELL_PADDING = '4px 6px'

/** 데이터 셀 공통 스타일 적용 (stretch 행에서 세로선이 행 전체를 관통하도록 flex 수직 중앙) */
function applyCell(cell: HTMLElement, align: string): void {
  const jc = align === 'right' ? 'flex-end' : align === 'center' ? 'center' : 'flex-start'
  Object.assign(cell.style, {
    display: 'flex',
    alignItems: 'center',
    justifyContent: jc,
    width: '100%',
    boxSizing: 'border-box',
    padding: CELL_PADDING,
    overflow: 'hidden',
  })
}

/* ── 헤더 셀 ── */

/** 테이블 헤더 셀 (공통 border + 스타일) */
export function createHeaderCell(label: string): HTMLElement {
  const cell = document.createElement('div')
  Object.assign(cell.style, {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxSizing: 'border-box',
    padding: CELL_PADDING,
    fontSize: FONT_SIZE.header,
    fontWeight: FONT_WEIGHT.normal,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
  })
  cell.textContent = label
  return cell
}

/* ── 공통 셀 컴포넌트 ── */

/** 순번 셀 (가운데정렬) */
export function createSeqCell(seq: number): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'center')
  cell.style.color = COLOR.tertiary
  cell.textContent = String(seq)
  return cell
}

/** 종목코드 셀 (가운데정렬) */
export function createCodeCell(code: string): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'center')
  cell.style.color = COLOR.code
  cell.textContent = code
  return cell
}

/** 현재가 셀 (우측정렬, 등락률 기반 색상, 가격 미수신 시 "-") */
export function createPriceCell(price: number | null | undefined, rate: number | null | undefined): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  
  if (price === null || price === undefined) {
    cell.textContent = '-'
  } else {
    const span = document.createElement('span')
    span.style.color = rateColor(rate)
    span.textContent = fmtComma(price)
    cell.appendChild(span)
  }
  return cell
}

/** 대비 셀 (매수설정 페이지 스타일과 동일하게 통일) */
export function createChangeCell(change: number | null | undefined): HTMLElement {
  if (change === null || change === undefined) {
    const cell = document.createElement('div')
    applyCell(cell, 'right')
    cell.textContent = '-'
    return cell
  }
  if (change === 0) {
    const cell = document.createElement('div')
    applyCell(cell, 'right')
    cell.textContent = '0'
    return cell
  }
  const wrap = document.createElement('span')
  wrap.style.display = 'inline-flex'
  wrap.style.justifyContent = 'space-between'
  wrap.style.width = '100%'
  
  const arrow = document.createElement('span')
  arrow.textContent = changeArrow(change)
  arrow.style.color = rateColor(change)
  
  const abs = document.createElement('span')
  abs.textContent = fmtComma(Math.abs(change))
  abs.style.color = rateColor(change)
  
  wrap.appendChild(arrow)
  wrap.appendChild(abs)
  return wrap
}

/** 등락률 셀 (우측정렬, +/- 포맷, rateColor, null이면 "-", 0이면 "0.00%") */
export function createRateCell(rate: number | null | undefined): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  if (rate === null || rate === undefined) {
    cell.textContent = '-'
  } else {
    const span = document.createElement('span')
    span.style.color = rateColor(rate)
    span.textContent = fmtRate(rate)
    cell.appendChild(span)
  }
  return cell
}

/** 거래대금 셀 (우측정렬, 기본색, 억 단위) */
export function createAmountCell(amount: number | null | undefined): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  cell.textContent = amount && amount > 0 ? (amount / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : '-'  // 백만원 → 억단위 (소수점 1자리, 콤마)
  return cell
}

/** 체결강도 셀 (우측정렬, strengthColor) */
export function createStrengthCell(strength: number | null | undefined): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  if (strength != null && !isNaN(strength) && strength > 0) {
    cell.textContent = strength.toFixed(1)
    cell.style.color = strengthColor(strength)
  } else {
    cell.textContent = '-'
  }
  return cell
}

/** 5일평균 셀 (우측정렬, 기본색) */
export function createAvgAmountCell(amount: number): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  // 백만원 단위 → 억단위 변환 (소수점 1자리, 콤마)
  cell.textContent = amount > 0 ? (amount / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : '-'
  return cell
}

/** 일반 숫자 셀 (우측정렬, 콤마) */
export function createNumberCell(value: number): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  cell.textContent = fmtComma(value)
  return cell
}

/** 손익 셀 (우측정렬, pnlColor, 콤마) */
export function createPnlCell(value: number): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  const span = document.createElement('span')
  span.style.color = pnlColor(value)
  span.textContent = fmtComma(value)
  cell.appendChild(span)
  return cell
}
