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
import type { StockScore } from '../types'
import { hotStore, normalizeStockCode } from '../stores/hotStore'

/** 매수후보 종목의 실시간 시세를 masterStocks(단일 진실 소스)에서 조회.
 *  buyTargets는 정적 스코어만 보관 — 실시간 필드는 masterStocks 참조 (P10 SSOT). */
function getMasterStock(code: string) {
  return hotStore.getState().masterStocks[normalizeStockCode(code)]
}

/* ── ColumnDef 배열 (12개 컬럼) ── */
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
  makeChangeColumn<StockScore>((t) => {
    const ms = getMasterStock(t.code)
    return ms?.change != null ? Number(ms.change) : null
  }),
  makeRateColumn<StockScore>((t) => {
    const ms = getMasterStock(t.code)
    return ms?.change_rate != null ? Number(ms.change_rate) : null
  }),
  {
    key: 'order_ratio', label: '호가잔량비(%)', align: 'right', type: 'order_ratio', maxWidth: 88,
    render: (t) => {
      const ms = getMasterStock(t.code)
      const orderRatio = ms?.order_ratio
      if (!orderRatio) return ''
      const [bid, ask] = orderRatio
      if (bid <= 0 && ask <= 0) return ''
      const wrap = document.createElement('div')
      Object.assign(wrap.style, { display: 'flex', justifyContent: 'space-between', width: '100%' })
      const labelSpan = document.createElement('span')
      const numSpan = document.createElement('span')
      if (bid === ask) {
        labelSpan.textContent = '보합'
        labelSpan.style.color = COLOR.tertiary
        numSpan.textContent = '100.0'
        numSpan.style.color = COLOR.tertiary
      } else if (bid > ask) {
        labelSpan.textContent = '[매수]'
        labelSpan.style.color = COLOR.up
        numSpan.textContent = ((bid / ask) * 100).toFixed(1)
        numSpan.style.color = COLOR.up
      } else {
        labelSpan.textContent = '[매도]'
        labelSpan.style.color = COLOR.down
        numSpan.textContent = ((ask / bid) * 100).toFixed(1)
        numSpan.style.color = COLOR.down
      }
      wrap.appendChild(labelSpan)
      wrap.appendChild(numSpan)
      return wrap
    },
  },
  {
    key: 'program_net_buy', label: '프.순.매(백)', align: 'right', type: 'program_net', minWidth: 76, maxWidth: 76,
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
    key: 'news_boost', label: '📰뉴스', align: 'center', type: 'news', maxWidth: 70,
    render: (t) => {
      const newsScore = Number(t.news_boost) || 0
      if (newsScore <= 0) return ''
      const span = document.createElement('span')
      span.textContent = '📰'
      span.style.color = COLOR.up
      span.style.fontSize = FONT_SIZE.body
      span.style.fontWeight = FONT_WEIGHT.bold
      // P21: 뉴스 제목이 있으면 툴팁에 호재 정보 노출 (news_boost_title — applyNewsHit이 보관, 세션 4).
      //      title 부재 시 가산점 점수만 표시 (P20 명시적 값).
      // A안: 📰 표시 = boost_news_on=True 상태에서 감지된 호재 → 가산점 반영됨 (3동작 완전 일치).
      //      boost_news_on=False 시 백엔드에서 감지 자체를 수행 안 하므로 📰 미표시.
      const title = t.news_boost_title || ''
      span.title = title
        ? `${title}\n뉴스 가산점 ${newsScore.toFixed(1)}점 반영됨`
        : `뉴스 가산점 ${newsScore.toFixed(1)}점 반영됨`
      return span
    },
  },
  {
    key: 'high_5d', label: '5일고가', align: 'right', type: 'high', maxWidth: 98,
    render: (t) => {
      const cell = createNumberCell(Number(t.high_5d) || 0)
      const ms = getMasterStock(t.code)
      const curPrice = ms?.cur_price
      if (t.high_5d && t.high_5d > 0 && curPrice != null && Number(curPrice) > t.high_5d) {
        cell.style.backgroundColor = COLOR.successBg
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
      span.textContent = t.guard_pass ? '통과' : '차단'
      span.style.color = t.guard_pass ? COLOR.success : COLOR.up
      return span
    },
  },
  {
    key: 'reject_reason', label: '원인', align: 'left', type: 'reject_reason', cellStyle: { color: COLOR.tertiary },
    render: (t) => {
      const r = t.reject_reason || ''
      if (r === '보유중' || r === '금일매수') {
        const span = document.createElement('span')
        span.textContent = r
        span.style.color = COLOR.warning
        span.style.fontWeight = '600'
        return span
      }
      return r
    },
  },
]
