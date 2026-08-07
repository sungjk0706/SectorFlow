// frontend/src/pages/buy-target-columns.ts
// 매수후보 페이지 — 컬럼 정의 모듈 (순수 데이터, 상태 없음)
// buy-target.ts(페이지 진입점)가 import. P24 단순성 — 책임 분리.

import { type ColumnDef } from '../components/common/data-table'
import {
  createStockNameColumn,
  createSeqCell,
  makeCodeColumn,
  makeChangeColumn,
  makeRateColumn,
  createPriceCell,
  createNumberCell,
  FONT_SIZE,
  FONT_WEIGHT,
  COLOR,
} from '../components/common/ui-styles'
import { createIcon } from '../components/common/icon'
import type { StockScore } from '../types'
import { hotStore, normalizeStockCode } from '../stores/hotStore'

/** 매수후보 종목의 실시간 시세를 masterStocks(단일 진실 소스)에서 조회.
 *  buyTargets는 정적 스코어만 보관 — 실시간 필드는 masterStocks 참조 (P10 SSOT). */
function getMasterStock(code: string) {
  return hotStore.getState().masterStocks[normalizeStockCode(code)]
}

/* ── M-08: 호가잔량비 칸 요소 재사용 ──
 *  매번 새 요소를 만들지 않고 종목코드별로 한 번 만든 요소를 재사용.
 *  텍스트·색상만 갱신 (양호 패턴 OK-16 셀 diff와 동일 방식).
 *  페이지 이탈 시 destroyOrderRatioCells()로 정리. */
interface OrderRatioCell {
  el: HTMLDivElement
  label: HTMLSpanElement
  num: HTMLSpanElement
}
const orderRatioCellMap = new Map<string, OrderRatioCell>()

function getOrderRatioCell(code: string): OrderRatioCell {
  let cell = orderRatioCellMap.get(code)
  if (!cell) {
    const el = document.createElement('div')
    Object.assign(el.style, { display: 'flex', justifyContent: 'space-between', width: '100%' })
    const label = document.createElement('span')
    const num = document.createElement('span')
    el.appendChild(label)
    el.appendChild(num)
    cell = { el, label, num }
    orderRatioCellMap.set(code, cell)
  }
  return cell
}

/* ── M-08: 5일고가 칸 요소 재사용 ──
 *  createNumberCell 매번 새 요소 생성을 종목코드별 재사용으로 전환.
 *  고가 돌파 배경색만 조건부 갱신. */
interface High5dCell {
  el: HTMLElement
  lastValue: number
  lastBreakthrough: boolean
}
const high5dCellMap = new Map<string, High5dCell>()

function getHigh5dCell(code: string, value: number): HTMLElement {
  let cell = high5dCellMap.get(code)
  if (!cell) {
    cell = { el: createNumberCell(value), lastValue: value, lastBreakthrough: false }
    high5dCellMap.set(code, cell)
  } else if (cell.lastValue !== value) {
    cell.el.textContent = (function fmtCommaLocal(v: number): string {
      return v.toLocaleString('ko-KR')
    })(value)
    cell.lastValue = value
  }
  return cell.el
}

export function destroyOrderRatioCells(): void {
  orderRatioCellMap.clear()
  high5dCellMap.clear()
}

/* ── ColumnDef 배열 (13개 컬럼) ── */
export const COLUMNS: ColumnDef<StockScore>[] = [
  { key: 'seq', label: '순번', align: 'center', type: 'seq', render: (_t, idx) => createSeqCell(idx + 1) },
  makeCodeColumn<StockScore>((t) => t.code),
  {
    ...createStockNameColumn<StockScore>(
      (t: StockScore) => ({
        name: t.name,
        market_type: t.market_type,
        nxt_enable: t.nxt_enable
      })
    ),
    minWidth: 140,
    maxWidth: 168,
  },
  {
    key: 'cur_price', label: '현재가', align: 'right', type: 'price', flash: true,
    render: (t) => {
      const ms = getMasterStock(t.code)
      const curPrice = ms?.cur_price
      const changeRate = ms?.change_rate
      return createPriceCell(curPrice != null ? Number(curPrice) : null, changeRate != null ? Number(changeRate) : null)
    },
  },
  makeChangeColumn<StockScore>(
    (t) => {
      const ms = getMasterStock(t.code)
      return ms?.change != null ? Number(ms.change) : null
    },
    (t) => getMasterStock(t.code)?.sign,
  ),
  makeRateColumn<StockScore>(
    (t) => {
      const ms = getMasterStock(t.code)
      return ms?.change_rate != null ? Number(ms.change_rate) : null
    },
    (t) => getMasterStock(t.code)?.sign,
  ),
  {
    key: 'order_ratio', label: '호가잔량비(%)', align: 'right', type: 'order_ratio', maxWidth: 80,
    render: (t) => {
      const ms = getMasterStock(t.code)
      const orderRatio = ms?.order_ratio
      if (!orderRatio) return ''
      const [bid, ask] = orderRatio
      if (bid <= 0 && ask <= 0) return ''
      // M-08: 종목코드별 요소 재사용 — 텍스트·색상만 갱신
      const { el: wrap, label: labelSpan, num: numSpan } = getOrderRatioCell(t.code)
      if (bid === ask) {
        if (labelSpan.textContent !== '보합') labelSpan.textContent = '보합'
        if (labelSpan.style.color !== COLOR.tertiary) labelSpan.style.color = COLOR.tertiary
        if (numSpan.textContent !== '100.0') numSpan.textContent = '100.0'
        if (numSpan.style.color !== COLOR.tertiary) numSpan.style.color = COLOR.tertiary
      } else if (bid > ask) {
        if (labelSpan.textContent !== '[매수]') labelSpan.textContent = '[매수]'
        if (labelSpan.style.color !== COLOR.up) labelSpan.style.color = COLOR.up
        const numText = ((bid / ask) * 100).toFixed(1)
        if (numSpan.textContent !== numText) numSpan.textContent = numText
        if (numSpan.style.color !== COLOR.up) numSpan.style.color = COLOR.up
      } else {
        if (labelSpan.textContent !== '[매도]') labelSpan.textContent = '[매도]'
        if (labelSpan.style.color !== COLOR.down) labelSpan.style.color = COLOR.down
        const numText = ((ask / bid) * 100).toFixed(1)
        if (numSpan.textContent !== numText) numSpan.textContent = numText
        if (numSpan.style.color !== COLOR.down) numSpan.style.color = COLOR.down
      }
      return wrap
    },
  },
  {
    key: 'program_net_buy', label: '프.순.매(백)', align: 'right', type: 'program_net', minWidth: 72, maxWidth: 72,
    render: (t) => {
      const ms = getMasterStock(t.code)
      const programNetBuy = ms?.program_net_buy
      if (programNetBuy === undefined || programNetBuy === null) return ''
      // tval이 금액(원)이라면 백만 원 단위로 환산, LS증권 대금 포맷을 고려하여 백만 단위로 나눈 후 1자리 소수점 표시
      const valMillions = programNetBuy / 1000000;
      const span = document.createElement('span')
      // 1자리 소수점 및 콤마 포맷 (Intl.NumberFormat 사용)
      const formatter = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
      span.textContent = formatter.format(valMillions);
      if (programNetBuy > 0) {
        span.style.color = COLOR.up
      } else if (programNetBuy < 0) {
        span.style.color = COLOR.down
      } else {
        span.style.color = COLOR.tertiary
      }
      return span
    },
  },
  {
    key: 'news_boost', label: '뉴스', align: 'center', type: 'news', minWidth: 60, maxWidth: 100,
    render: (t) => {
      const newsScore = Number(t.news_boost) || 0
      if (newsScore <= 0) return ''
      const wrap = document.createElement('span')
      wrap.style.display = 'inline-flex'
      wrap.style.alignItems = 'center'
      wrap.style.gap = '2px'
      const icon = createIcon('newspaper', { size: 13, color: COLOR.up })
      icon.style.flexShrink = '0'
      wrap.appendChild(icon)
      // 매칭된 호재 키워드 표시 — 백엔드가 매칭 단계에서 전달한 키워드 (P10 SSOT, P21 투명성).
      // 키워드 부재 시(과거 데이터 등) 뉴스 호재 아이콘만 표시 — 툴팁으로 상세 확인.
      const keyword = t.news_boost_keyword || ''
      if (keyword) {
        const kw = document.createElement('span')
        kw.textContent = keyword
        kw.style.color = COLOR.up
        kw.style.fontSize = FONT_SIZE.body
        kw.style.fontWeight = FONT_WEIGHT.bold
        wrap.appendChild(kw)
      }
      // P21: 뉴스 제목이 있으면 툴팁에 호재 정보 노출 (news_boost_title — applyNewsHit이 보관).
      //      title 부재 시 가산점 점수만 표시 (P20 명시적 값).
      const title = t.news_boost_title || ''
      wrap.title = title
        ? `${title}\n뉴스 가산점 ${newsScore.toFixed(1)}점 반영됨`
        : `뉴스 가산점 ${newsScore.toFixed(1)}점 반영됨`
      return wrap
    },
  },
  {
    key: 'high_5d', label: '5일고가', align: 'right', type: 'high', minWidth: 80, maxWidth: 130,
    render: (t) => {
      const value = Number(t.high_5d) || 0
      // M-08: 종목코드별 요소 재사용 — 값 변경 시에만 textContent 갱신
      const cell = getHigh5dCell(t.code, value)
      const ms = getMasterStock(t.code)
      const curPrice = ms?.cur_price
      const breakthrough = !!(t.high_5d && t.high_5d > 0 && curPrice != null && Number(curPrice) > t.high_5d)
      const cached = high5dCellMap.get(t.code)
      if (cached && cached.lastBreakthrough !== breakthrough) {
        cell.style.backgroundColor = breakthrough ? COLOR.successBg : ''
        cached.lastBreakthrough = breakthrough
      }
      return cell
    },
  },
  {
    key: 'boost_score', label: '가산점', align: 'right', type: 'boost',
    render: (t) => {
      const bs = Number(t.boost_score) || 0
      return bs > 0 ? bs.toFixed(1) : ''
    },
  },
  {
    key: 'guard', label: '제한', align: 'center', type: 'guard',
    render: (t) => {
      const span = document.createElement('span')
      // 3단계 표시 (P21 사용자 투명성):
      //   통과(초록) — guard_pass && reject_reason 빈칸: 개별 검사 통과 + 지금 바로 매수 가능
      //   보류(주황) — guard_pass && reject_reason 있음: 개별 검사 통과했지만 전역 상태/잔액으로 매수 불가
      //   차단(빨강) — !guard_pass: 개별 종목이 매수 조건 검사에서 걸림
      if (!t.guard_pass) {
        span.textContent = '차단'
        span.style.color = COLOR.up
      } else if (t.reject_reason) {
        span.textContent = '보류'
        span.style.color = COLOR.warning
        span.style.fontWeight = '600'
      } else {
        span.textContent = '통과'
        span.style.color = COLOR.success
      }
      return span
    },
  },
  {
    key: 'reject_reason', label: '원인', align: 'left', type: 'reject_reason', minWidth: 95, maxWidth: 115, cellStyle: { color: COLOR.tertiary },
    render: (t) => {
      const r = t.reject_reason || ''
      if (r === '보유중' || r === '금일매수') {
        const span = document.createElement('span')
        span.textContent = r
        span.style.color = COLOR.warning
        span.style.fontWeight = '600'
        return span
      }
      // 보류 상태(guard_pass=true && reject_reason 있음) — 전역 차단 사유 주황색 표시 (P21, "보류" 라벨과 시각적 일치)
      if (t.guard_pass && r) {
        const span = document.createElement('span')
        span.textContent = r
        span.style.color = COLOR.warning
        return span
      }
      return r
    },
  },
]
