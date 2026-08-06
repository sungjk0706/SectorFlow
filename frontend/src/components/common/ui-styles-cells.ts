/**
 * 공통 UI 스타일 — 테이블 셀 컴포넌트.
 * ui-styles.ts에서 분할 (F06-03, P24 단순성).
 * 순수 이동 — 동작 변경 없음. 외부 import 경로는 메인에서 re-export 유지.
 */

import { COLOR, FONT_SIZE, FONT_WEIGHT, rateColor, pnlColor, strengthColor, changeArrow, fmtComma, fmtRate, fmtMillionsToBillion } from './ui-styles'

/* ── 종목명 셀 ── */

/** 거래소 라벨 생성 — 둥근 사각 맥 아이콘 스타일 (em 단위로 셀 폰트 대비 자동 스케일).
 *  종목명 셀(createStockNameCell)과 카운트 행(market-count-row) 공통 사용 (P23 일관성). */
export function createMarketLabel(text: 'K' | '통', bg: string, fg: string, title: string): HTMLElement {
  const label = document.createElement('span')
  Object.assign(label.style, {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '1.6em',
    aspectRatio: '1',
    borderRadius: '0.25em',
    fontSize: '0.8em',
    fontWeight: '600',
    lineHeight: '1',
    backgroundColor: bg,
    color: fg,
    flexShrink: '0',
    userSelect: 'none',
  } as Partial<CSSStyleDeclaration>)
  label.textContent = text
  label.title = title
  label.setAttribute('aria-label', title)
  return label
}

export function createStockNameCell(
  name: string,
  marketType?: string,
  nxtEnable?: boolean,
): HTMLElement {
  const wrap = document.createElement('span')
  Object.assign(wrap.style, {
    display: 'inline-flex',
    alignItems: 'center',
    width: '100%',
  } as Partial<CSSStyleDeclaration>)

  const nameSpan = document.createElement('span')
  if (marketType === '10') nameSpan.style.color = COLOR.kosdaq
  nameSpan.textContent = name
  nameSpan.style.flex = '1'
  nameSpan.style.overflow = 'hidden'
  nameSpan.style.textOverflow = 'ellipsis'
  nameSpan.style.whiteSpace = 'nowrap'
  wrap.appendChild(nameSpan)

  // 거래소 라벨 — KRX 전용 "K" / 통합 "통" (P21 투명성: 모든 종목 명시적 표시)
  const label = nxtEnable
    ? createMarketLabel('통', COLOR.nxtLabelBg, COLOR.nxtLabel, 'KRX+NXT 통합 거래 종목')
    : createMarketLabel('K', COLOR.krxLabelBg, COLOR.krxLabel, 'KRX 전용 종목')
  label.style.marginLeft = '6px'
  wrap.appendChild(label)

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
    fontVariantNumeric: 'tabular-nums',  // 숫자 셀 자릿수 정렬 (P23 일관성)
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

/** 대비 셀 (매수설정 페이지 스타일과 동일하게 통일).
 *  sign 제공 시 5단계 부호 원본 기준 색상·기호 적용 — 상한(1)·하한(4)은 진한 색상으로 구별 (P21). */
export function createChangeCell(change: number | null | undefined, sign?: string): HTMLElement {
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
  wrap.style.fontVariantNumeric = 'tabular-nums'

  const arrow = document.createElement('span')
  arrow.textContent = changeArrow(change, sign)
  arrow.style.color = rateColor(change, sign)

  const abs = document.createElement('span')
  abs.textContent = fmtComma(Math.abs(change))
  abs.style.color = rateColor(change, sign)

  wrap.appendChild(arrow)
  wrap.appendChild(abs)
  return wrap
}

/** 등락률 셀 (우측정렬, +/- 포맷, rateColor, null이면 "-", 0이면 "0.00%").
 *  sign 제공 시 5단계 부호 원본 기준 색상 적용 — 상한(1)·하한(4)은 진한 색상으로 구별 (P21). */
export function createRateCell(rate: number | null | undefined, sign?: string): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  if (rate === null || rate === undefined) {
    cell.textContent = '-'
  } else {
    const span = document.createElement('span')
    span.style.color = rateColor(rate, sign)
    span.textContent = fmtRate(rate)
    cell.appendChild(span)
  }
  return cell
}

/** 거래대금 셀 (우측정렬, 기본색, 억 단위).
 *  숫자를 고정 폭 span에 담아 자릿수 변화(9→10, 99→100 등)에도 텍스트 시작 위치가
 *  밀리지 않도록 한다 (업계 표준: tabular-nums + 고정 폭 숫자 영역). */
export function createAmountCell(amount: number | null | undefined): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  const span = document.createElement('span')
  Object.assign(span.style, {
    display: 'inline-block',
    minWidth: '5.5em',
    textAlign: 'right',
  })
  span.textContent = amount && amount > 0 ? fmtMillionsToBillion(amount) : '-'  // 백만원 → 억단위 (소수점 2자리 고정, 콤마)
  cell.appendChild(span)
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

/** 5거래일 평균 셀 (우측정렬, 기본색).
 *  거래대금 셀과 동일 패턴 — 고정 폭 span에 담아 자릿수 변화 시 밀림 방지 (P23 일관성). */
export function createAvgAmountCell(amount: number): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  // 백만원 단위 → 억단위 변환 (소수점 2자리 고정, 콤마)
  const span = document.createElement('span')
  Object.assign(span.style, {
    display: 'inline-block',
    minWidth: '5.5em',
    textAlign: 'right',
  })
  span.textContent = amount > 0 ? fmtMillionsToBillion(amount) : '-'
  cell.appendChild(span)
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
