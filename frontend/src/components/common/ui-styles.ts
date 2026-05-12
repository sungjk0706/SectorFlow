/**
 * 공통 UI 스타일 — 한국 증권 HTS 표준 기반.
 * 색상 · 폰트 · 굵기 · 기호를 한 곳에서 관리.
 */

import type { ColumnDef } from './data-table'

/* ── 폰트 ── */

/** 기본 폰트 — 숫자/영어: Tahoma, 한글: 굴림 */
export const FONT_FAMILY = "Tahoma, '굴림', Gulim, sans-serif"

/* ── 폰트 크기 ── */

export const FONT_SIZE = {
  header: '13px',    // 테이블 헤더 (전역과 동일)
  body: '13px',      // 테이블 본문
  code: '12px',      // 종목코드
  small: '11px',     // 순번·배지·보조 텍스트
  group: '18px',     // 업종 그룹 헤더
  title: '15px',     // 카드 제목 (h3)
  section: '14px',   // 섹션/팝업 제목
  tab: '13px',       // 탭 버튼
  label: '12px',     // 토글 라벨·서브패널 제목·검색·탭(소)
  badge: '11px',     // 한도배지·경고·빈상태 메시지
  chip: '10px',      // 헤더 칩
  spin: '8px',       // 스핀 버튼 화살표
} as const

/* ── 폰트 굵기 ── */

export const FONT_WEIGHT = {
  normal: '400',      // 일반 수치
  medium: '500',      // 종목명 · 가격
  semibold: '600',    // 헤더 · 강조
  bold: '700',        // 그룹 헤더
} as const

/* ── 공통 색상 ── */

/** 등락률 / 대비 / 현재가 색상: 양수 빨강, 음수 파랑, 0 기본 */
export function rateColor(v: number): string {
  return v > 0 ? 'red' : v < 0 ? 'blue' : '#333'
}

/** 손익 색상: 양수=#dc3545, 음수=#2563eb, 0=#333 */
export function pnlColor(v: number): string {
  return v > 0 ? '#dc3545' : v < 0 ? '#2563eb' : '#333'
}

/** 체결강도 색상: 100 미만 파랑, 100 이상 빨강 */
export function strengthColor(v: number): string {
  return v >= 100 ? 'red' : 'blue'
}

/* ── 기호 ── */

/** 대비 화살표: 상승 ▲, 하락 ▼, 보합 빈 문자열 */
export function changeArrow(v: number): string {
  return v > 0 ? '▲' : v < 0 ? '▼' : ''
}

/** 등락률 포맷: +3.70 / -2.15 / 0.00 (부호 포함, 색상으로도 구분) */
export function fmtRate(v: number): string {
  if (v > 0) return '+' + v.toFixed(2)
  if (v < 0) return v.toFixed(2)
  return '0.00'
}

/** 금액 천 단위 콤마 */
export function fmtComma(v: number): string {
  return v.toLocaleString()
}

/** 금액 포맷: 천 단위 콤마 + '원' */
export function fmtWon(v: number): string {
  return `${v.toLocaleString()}원`
}

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
  if (marketType === '10') nameSpan.style.color = '#d63384'
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
      borderBottom: '6px solid #dc3545',
    })
    wrap.appendChild(tri)
  }

  return wrap
}

/* ── 공통 셀 border ── */

export const CELL_BORDER = '1px solid #ccc'
const CELL_PADDING = '4px 6px'

/* ── 행 높이 ── */

export const ROW_HEIGHT = {
  data: '32px',       // 데이터 행
  header: '32px',     // 헤더 행
  group: '48px',      // 업종 그룹 행
} as const

/** 행 높이 숫자값 (가상 스크롤러용) */
export const ROW_HEIGHT_PX = {
  data: 32,
  header: 32,
  group: 48,
} as const

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
  cell.style.color = '#666'
  cell.textContent = String(seq)
  return cell
}

/** 종목코드 셀 (가운데정렬) */
export function createCodeCell(code: string): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'center')
  cell.style.color = '#555'
  cell.textContent = code
  return cell
}

/** 현재가 셀 (우측정렬, 등락률 기반 색상, 가격 미수신 시 "-") */
export function createPriceCell(price: number | null | undefined, rate: number): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  if (!price) {
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
export function createChangeCell(change: number): HTMLElement {
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

/** 등락률 셀 (우측정렬, +/- 포맷, rateColor, null/0이면 "-") */
export function createRateCell(rate: number | null | undefined): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  if (!rate && rate !== 0) {
    cell.textContent = '-'
  } else if (rate === 0) {
    cell.textContent = '0'
  } else {
    const span = document.createElement('span')
    span.style.color = rateColor(rate)
    span.textContent = fmtRate(rate)
    cell.appendChild(span)
  }
  return cell
}

/** 거래대금 셀 (우측정렬, 기본색) */
export function createAmountCell(amount: number | null | undefined): HTMLElement {
  const cell = document.createElement('div')
  applyCell(cell, 'right')
  cell.textContent = amount && amount > 0 ? fmtComma(Math.round(amount / 100_000_000)) : '-'
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
  cell.textContent = amount > 0 ? fmtComma(Math.round(amount / 100_000_000)) : '-'
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

/* ── 공통 컬럼 팩토리 ── */
/**
 * 데이터 접근 getter를 받아 ColumnDef를 반환하는 팩토리 함수.
 * buy-target(flat) / sector-stock(중첩) 등 구조가 다른 페이지에서 동일하게 사용.
 */

/** 순번 컬럼 */
export function makeSeqColumn<T>(get: (t: T) => number): ColumnDef<T> {
  return {
    key: 'seq',
    label: '순번',
    align: 'center',
    render: (t) => createSeqCell(get(t)),
  }
}

/** 종목코드 컬럼 */
export function makeCodeColumn<T>(get: (t: T) => string): ColumnDef<T> {
  return {
    key: 'code',
    label: '종목코드',
    align: 'center',
    render: (t) => createCodeCell(get(t)),
  }
}

/** 현재가 컬럼 */
export function makePriceColumn<T>(
  getPrice: (t: T) => number | null | undefined,
  getRate: (t: T) => number,
): ColumnDef<T> {
  return {
    key: 'cur_price',
    label: '현재가',
    align: 'right',
    flash: true,
    render: (t) => createPriceCell(getPrice(t), getRate(t)),
  }
}

/** 대비 컬럼 */
export function makeChangeColumn<T>(get: (t: T) => number): ColumnDef<T> {
  return {
    key: 'change',
    label: '대비',
    align: 'center',
    render: (t) => createChangeCell(get(t)),
  }
}

/** 등락률 컬럼 */
export function makeRateColumn<T>(get: (t: T) => number | null | undefined): ColumnDef<T> {
  return {
    key: 'change_rate',
    label: '등락률',
    align: 'right',
    render: (t) => createRateCell(get(t)),
  }
}

/** 체결강도 컬럼 */
export function makeStrengthColumn<T>(get: (t: T) => number | null | undefined): ColumnDef<T> {
  return {
    key: 'strength',
    label: '체결강도',
    align: 'right',
    render: (t) => createStrengthCell(get(t)),
  }
}

/** 거래대금 컬럼 (억 단위 표시) */
export function makeAmountColumn<T>(get: (t: T) => number | null | undefined): ColumnDef<T> {
  return {
    key: 'trade_amount',
    label: '거래대금',
    align: 'right',
    render: (t) => createAmountCell(get(t)),
  }
}

/** 5일평균거래대금 컬럼 (억 단위 표시) */
export function makeAvgAmountColumn<T>(get: (t: T) => number): ColumnDef<T> {
  return {
    key: 'avg_amt_5d',
    label: '5일평균',
    align: 'right',
    render: (t) => createAvgAmountCell(get(t)),
  }
}

/* ── 표준화된 종목명 컬럼 생성 함수 ── */

/** 표준 종목명 컬럼 정의 - 모든 페이지에서 동일한 스타일과 구조 사용 */
export function createStockNameColumn<T extends object>(
  fallbackLookup: (item: T) => { name: string; market_type?: string; nxt_enable?: boolean }
): ColumnDef<T> {
  return {
    key: 'name',
    label: '종목명',
    align: 'left',
    minWidth: 80,
    cellStyle: { fontWeight: 'normal', color: '#111' },
    render: (item: T) => {
      const lookup = fallbackLookup(item)
      return createStockNameCell(lookup.name, lookup.market_type, lookup.nxt_enable)
    }
  }
}

/** sell-position 페이지용 종목명 컬럼 - sectorStocks에서 조회 */
export function createStockNameColumnWithSectorLookup<T extends object>(
  nameKey: keyof T,
  codeKey: keyof T
): ColumnDef<T> {
  return {
    key: String(nameKey),
    label: '종목명',
    align: 'left',
    minWidth: 80,
    cellStyle: { fontWeight: 'normal', color: '#111' },
    render: (item: T) => {
      const name = String(item[nameKey] || '')
      const code = String(item[codeKey] || '')
      
      // appStore에서 sectorStock 조회
      const state = (window as any).appStore?.getState?.()
      const sectorStocks = state?.sectorStocks
      const sectorStock = sectorStocks?.get?.(code)
      
      if (!sectorStock && sectorStocks?.size === 0) {
        console.warn('[createStockNameColumnWithSectorLookup] sectorStocks is empty. Market type and NXT enable indicators will not be displayed.')
      }
      
      return createStockNameCell(
        name,
        sectorStock?.market_type,
        sectorStock?.nxt_enable
      )
    }
  }
}

/* ── 다크테마 폼 컨트롤 ── */

const DARK_FIELD_STYLE = {
  width: '200px',
  flexShrink: '0',
  padding: '6px 10px',
  borderRadius: '6px',
  border: '1px solid #555',
  background: '#1e1e1e',
  color: '#ddd',
  fontSize: '14px',
  boxSizing: 'border-box' as const,
}

/** 다크테마 텍스트/패스워드 input */
export function createDarkInput(type: 'text' | 'password' = 'text'): HTMLInputElement {
  const el = document.createElement('input')
  el.type = type
  el.autocomplete = 'off'
  Object.assign(el.style, DARK_FIELD_STYLE)
  return el
}

/** 다크테마 select (options: { value, label }[]) */
export function createDarkSelect(options: { value: string; label: string; disabled?: boolean }[], value: string): HTMLSelectElement {
  const el = document.createElement('select')
  Object.assign(el.style, { ...DARK_FIELD_STYLE, cursor: 'pointer', appearance: 'none', backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23aaa'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' })
  for (const opt of options) {
    const o = document.createElement('option')
    o.value = opt.value
    o.textContent = opt.label
    if (opt.disabled) { o.disabled = true; o.style.color = '#666' }
    el.appendChild(o)
  }
  el.value = value
  return el
}