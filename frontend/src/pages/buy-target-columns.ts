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
import type { SectorStock } from '../types'

/* ── ColumnDef 배열 (12개 컬럼) ── */
export const COLUMNS: ColumnDef<SectorStock>[] = [
  { key: 'seq', label: '순번', align: 'center', type: 'seq', render: (_t, idx) => createSeqCell(idx + 1) },
  makeCodeColumn<SectorStock>((t) => t.code),
  {
    ...createStockNameColumn<SectorStock>(
      (t: SectorStock) => ({
        name: t.name,
        market_type: t.market_type,
        nxt_enable: t.nxt_enable
      })
    ),
    maxWidth: 168,
  },
  {
    key: 'cur_price', label: '현재가', align: 'right', type: 'price', flash: true,
    render: (t) => {
      const cell = createPriceCell(t.cur_price != null ? Number(t.cur_price) : null, t.change_rate != null ? Number(t.change_rate) : null)
      if (t.high_5d && t.high_5d > 0 && t.cur_price != null && Number(t.cur_price) > t.high_5d) {
        cell.style.justifyContent = 'space-between'
        const icon = document.createElement('span')
        icon.textContent = '▲'
        icon.style.color = COLOR.up
        icon.style.fontSize = FONT_SIZE.body
        icon.style.fontWeight = FONT_WEIGHT.bold
        cell.insertBefore(icon, cell.firstChild)
      }
      return cell
    },
  },
  makeChangeColumn<SectorStock>((t) => t.change != null ? Number(t.change) : null),
  makeRateColumn<SectorStock>((t) => t.change_rate != null ? Number(t.change_rate) : null),
  {
    key: 'order_ratio', label: '호가잔량비(%)', align: 'right', type: 'order_ratio', maxWidth: 110,
    render: (t) => {
      if (!t.order_ratio) return ''
      const [bid, ask] = t.order_ratio
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
    key: 'program_net_buy', label: '프.순.매(백)', align: 'right', type: 'program_net', minWidth: 106, maxWidth: 106,
    render: (t) => {
      if (t.program_net_buy === undefined || t.program_net_buy === null) return ''
      // tval이 금액(원)이라면 백만 원 단위로 환산, LS증권 대금 포맷을 고려하여 백만 단위로 나눈 후 1자리 소수점 표시
      const valMillions = t.program_net_buy / 1000000;
      const span = document.createElement('span')
      // 1자리 소수점 및 콤마 포맷 (Intl.NumberFormat 사용)
      const formatter = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
      span.textContent = formatter.format(valMillions);
      if (t.program_net_buy > 0) {
        span.style.color = COLOR.up
      } else if (t.program_net_buy < 0) {
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
      span.title = `뉴스 가산점 ${newsScore.toFixed(1)}점 부여됨`
      return span
    },
  },
  {
    key: 'high_5d', label: '5거래일 고가', align: 'right', type: 'high', maxWidth: 96,
    render: (t) => {
      const cell = createNumberCell(Number(t.high_5d) || 0)
      if (t.high_5d && t.high_5d > 0 && t.cur_price != null && Number(t.cur_price) > t.high_5d) {
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
    key: 'reason', label: '원인', align: 'left', type: 'reason', cellStyle: { color: COLOR.tertiary },
    render: (t) => {
      const r = t.reason || ''
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
