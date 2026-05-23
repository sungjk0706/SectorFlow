// frontend/src/layout/header.ui.ts
// 상단 헤더 — 장 상태, 앱 준비 상태, 엔진 상태, 설정 상태, 지수 실시간 표시
// 비즈니스 로직 제거, Props로 데이터 수신

import type { IndexData } from '../types'

/* ── Props 타입 ── */

export interface HeaderUiProps {
  marketPhase?: { krx: string; nxt: string }
  bootstrapStage?: { stage_name: string; progress?: { current: number; total: number } }
  engineReady?: boolean
  avgAmtProgress?: {
    status: string
    current: number
    total: number
    eta_sec?: number
    message?: string
  }
  status?: {
    is_test_mode: boolean
    kiwoom_token_valid: boolean
    kiwoom_connected: boolean
    kospi?: IndexData
    kosdaq?: IndexData
    index_polling?: boolean
  }
  settings?: {
    ws_subscribe_on: boolean
    time_scheduler_on: boolean
    auto_buy_on: boolean
    auto_sell_on: boolean
    tele_on: boolean
    buy_time_start?: string
    buy_time_end?: string
    sell_time_start?: string
    sell_time_end?: string
  }
  realtimeStatus?: 'waiting' | 'live' | null
}

/* ── 스타일 상수 ── */

const CHIP_STYLE =
  'padding:3px 8px;border-radius:10px;font-size:10px;font-weight:600;cursor:default;white-space:nowrap;'

const RISE = '#dc3545'
const FALL = '#1a73e8'

const PHASE_STYLE: Record<string, { bg: string; color: string }> = {
  /* 장중(거래 가능) — 초록 */
  '장전 동시호가': { bg: '#e8f5e9', color: '#2e7d32' },
  '정규장': { bg: '#e8f5e9', color: '#2e7d32' },
  '장후 시간외': { bg: '#e8f5e9', color: '#2e7d32' },
  '시간외 단일가': { bg: '#e8f5e9', color: '#2e7d32' },
  '프리마켓': { bg: '#e8f5e9', color: '#2e7d32' },
  '메인마켓': { bg: '#e8f5e9', color: '#2e7d32' },
  '애프터마켓': { bg: '#e8f5e9', color: '#2e7d32' },
  /* 비장중(휴장/대기/종료) — 회색 */
  '휴장일': { bg: '#f5f5f5', color: '#9e9e9e' },
  '장개시전': { bg: '#f5f5f5', color: '#9e9e9e' },
  '장마감': { bg: '#f5f5f5', color: '#9e9e9e' },
  '휴식': { bg: '#f5f5f5', color: '#9e9e9e' },
}

const STATUS_THEME = {
  on: { bg: '#e8f5e9', color: '#2e7d32' },
  off: { bg: '#f5f5f5', color: '#9e9e9e' },
  blue: { bg: '#e3f2fd', color: '#1565c0' },
  red: { bg: '#ffebee', color: '#c62828' },
} as const

/* ── 인라인 StatusChip 헬퍼 ── */

function createChipEl(): HTMLSpanElement {
  const span = document.createElement('span')
  span.style.cssText = CHIP_STYLE
  return span
}

function applyStatusChip(
  el: HTMLSpanElement,
  label: string,
  active?: boolean,
  variant?: keyof typeof STATUS_THEME,
): void {
  const v = variant ?? (active ? 'on' : 'off')
  const t = STATUS_THEME[v]
  el.style.background = t.bg
  el.style.color = t.color
  el.style.border = `1px solid ${t.color}20`
  el.textContent = label
}

function applyMarketPhaseChip(el: HTMLSpanElement, market: string, phase: string): void {
  const s = PHASE_STYLE[phase] || PHASE_STYLE['장마감']
  el.style.background = s.bg
  el.style.color = s.color
  el.style.border = `1px solid ${s.color}20`
  el.textContent = `${market} ${phase}`
}

function applyIndexChip(
  el: HTMLSpanElement,
  label: string,
  data: IndexData | undefined,
  polling: boolean | undefined,
  connected: boolean | undefined,
  marketPhase: { krx: string; nxt: string } | undefined,
): void {
  const krx = marketPhase?.krx ?? ''
  const isRegular = krx === '정규장'
  const isClosed = krx === '휴장일' || krx === '' || krx === 'closed'
  const active = isClosed ? false : isRegular ? !!connected : !!polling
  if (!data || !data.price) {
    applyStatusChip(el, `${label} --`, false)
    return
  }
  const rate = Number(data.rate) || 0
  const sign = rate > 0 ? '+' : ''
  const priceStr = Number(data.price).toLocaleString('ko-KR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  const text = `${label} ${priceStr} ${sign}${rate.toFixed(2)}%${polling && !isRegular && !isClosed ? ' 🔄' : ''}`
  const bg = active
    ? rate > 0
      ? '#ffebee'
      : rate < 0
        ? '#e3f2fd'
        : '#e8f5e9'
    : '#f5f5f5'
  const color = active ? (rate > 0 ? RISE : rate < 0 ? FALL : '#2e7d32') : '#9e9e9e'
  el.style.background = bg
  el.style.color = color
  el.style.border = `1px solid ${color}20`
  el.textContent = text
}

/* ── spin 키프레임 (1회 삽입) ── */

let spinInjected = false
function ensureSpinKeyframes(): void {
  if (spinInjected) return
  const style = document.createElement('style')
  style.textContent =
    '@keyframes header-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }'
  document.head.appendChild(style)
  spinInjected = true
}

/* ── UI 참조 ── */

let krxChip: HTMLSpanElement | null = null
let nxtChip: HTMLSpanElement | null = null
let bootstrapChip: HTMLSpanElement | null = null
let avgAmtChip: HTMLSpanElement | null = null
let modeChip: HTMLSpanElement | null = null
let brokerChip: HTMLSpanElement | null = null
let brokerWsChip: HTMLSpanElement | null = null
let realtimeStateChip: HTMLSpanElement | null = null
let autoTradeChip: HTMLSpanElement | null = null
let autoBuyChip: HTMLSpanElement | null = null
let autoSellChip: HTMLSpanElement | null = null
let teleChip: HTMLSpanElement | null = null
let kospiChip: HTMLSpanElement | null = null
let kosdaqChip: HTMLSpanElement | null = null

/* ── createHeader ── */

export function createHeader(container: HTMLElement, props: HeaderUiProps): { el: HTMLElement; update(props: HeaderUiProps): void } {
  ensureSpinKeyframes()

  const header = document.createElement('header')
  header.style.cssText =
    'box-sizing:border-box;padding:4px 16px;border-bottom:1px solid #ddd;display:flex;gap:8px;align-items:center;flex-wrap:nowrap;flex-shrink:0;height:40px;min-height:40px;max-height:40px;overflow-x:auto;overflow-y:hidden;'

  // 로고
  const logo = document.createElement('strong')
  logo.style.marginRight = 'auto'
  logo.textContent = '🌊 SectorFlow'
  header.appendChild(logo)

  // KRX / NXT 장 상태 칩
  krxChip = createChipEl()
  nxtChip = createChipEl()
  header.appendChild(krxChip)
  header.appendChild(nxtChip)

  // 앱준비 진행률 칩
  bootstrapChip = createChipEl()
  bootstrapChip.style.display = 'none'
  header.appendChild(bootstrapChip)

  // 백그라운드 데이터 갱신 칩
  avgAmtChip = createChipEl()
  avgAmtChip.style.display = 'none'
  header.appendChild(avgAmtChip)

  // 엔진 상태 칩
  modeChip = createChipEl()
  modeChip.style.display = 'none'
  brokerChip = createChipEl()
  brokerChip.style.display = 'none'
  brokerWsChip = createChipEl()
  brokerWsChip.style.display = 'none'
  realtimeStateChip = createChipEl()
  realtimeStateChip.style.display = 'none'
  header.appendChild(modeChip)
  header.appendChild(brokerChip)
  header.appendChild(brokerWsChip)
  header.appendChild(realtimeStateChip)

  // 설정 상태 칩
  autoTradeChip = createChipEl()
  autoTradeChip.style.display = 'none'
  autoBuyChip = createChipEl()
  autoBuyChip.style.display = 'none'
  autoSellChip = createChipEl()
  autoSellChip.style.display = 'none'
  teleChip = createChipEl()
  teleChip.style.display = 'none'
  header.appendChild(autoTradeChip)
  header.appendChild(autoBuyChip)
  header.appendChild(autoSellChip)
  header.appendChild(teleChip)

  // 지수 칩
  kospiChip = createChipEl()
  kospiChip.style.display = 'none'
  kosdaqChip = createChipEl()
  kosdaqChip.style.display = 'none'
  header.appendChild(kospiChip)
  header.appendChild(kosdaqChip)

  container.appendChild(header)

  // 초기 렌더링
  updateHeader(props)

  return { el: header, update: updateHeader }
}

/* ── updateHeader ── */

export function updateHeader(props: HeaderUiProps): void {
  const { marketPhase, bootstrapStage, engineReady, avgAmtProgress, status, settings, realtimeStatus } = props

  // 장 상태
  if (krxChip && nxtChip) {
    applyMarketPhaseChip(krxChip, 'KRX', marketPhase?.krx ?? '장마감')
    applyMarketPhaseChip(nxtChip, 'NXT', marketPhase?.nxt ?? '장마감')
  }

  // 앱준비 진행률
  if (bootstrapChip) {
    if (bootstrapStage && !engineReady) {
      bootstrapChip.style.display = ''
      bootstrapChip.style.background = '#f3e5f5'
      bootstrapChip.style.color = '#6a1b9a'
      bootstrapChip.style.border = '1px solid #6a1b9a20'
      const spinnerHtml = '<span style="display:inline-block;animation:header-spin 1.2s linear infinite">⏳</span>'
      let text = ` ${bootstrapStage.stage_name}`
      if (bootstrapStage.progress) {
        text += ` (${bootstrapStage.progress.current}/${bootstrapStage.progress.total})`
      }
      bootstrapChip.innerHTML = spinnerHtml + text
    } else {
      bootstrapChip.style.display = 'none'
    }
  }

  // 백그라운드 데이터 갱신
  if (avgAmtChip) {
    if (avgAmtProgress) {
      avgAmtChip.style.display = 'flex'
      avgAmtChip.style.position = 'relative'
      avgAmtChip.style.overflow = 'hidden'
      avgAmtChip.style.alignItems = 'center'
      avgAmtChip.style.padding = '3px 8px'

      const status = avgAmtProgress.status || ''
      let msg = ''
      let bg = '#fff3e0'
      let color = '#e65100'
      let progressPct = 0

      switch (status) {
        case 'downloading': {
          progressPct = avgAmtProgress.total > 0 ? (avgAmtProgress.current / avgAmtProgress.total) * 100 : 0
          msg = `전종목 5일거래대금/고가 데이터 다운로드 중 (${avgAmtProgress.current.toLocaleString()}/${avgAmtProgress.total.toLocaleString()}, ${Math.round(progressPct)}%)`
          bg = '#fff3e0'; color = '#e65100'
          break
        }
        case 'completed': {
          progressPct = 100
          msg = '전종목 5일 거래대금,고가 데이터 다운로드 완료'
          bg = '#e8f5e9'; color = '#2e7d32'
          break
        }
        case 'failed':
          msg = '전종목 5일 고가 실패'
          bg = '#ffebee'; color = '#c62828'
          break
        case 'partial': {
          progressPct = avgAmtProgress.total > 0 ? (avgAmtProgress.current / avgAmtProgress.total) * 100 : 0
          msg = `전종목 5일 데이터 ${Math.round(progressPct)}%만 있음`
          bg = '#fffde7'; color = '#f57f17'
          break
        }
        case 'cache_deleted':
          msg = '전종목 5일 고가 재계산 중'
          bg = '#fff3e0'; color = '#e65100'
          progressPct = 100
          break
        case 'token_pending':
          msg = '인증 대기중'
          bg = '#f5f5f5'; color = '#616161'
          break
        case 'requested':
          msg = '전종목 5일 데이터 준비 시작'
          bg = '#e3f2fd'; color = '#1565c0'
          break
        case 'confirmed': {
          progressPct = avgAmtProgress.total > 0 ? (avgAmtProgress.current / avgAmtProgress.total) * 100 : 0
          msg = (avgAmtProgress.total > 0 ? `전종목 확정시세 데이터 다운로드 중 (${avgAmtProgress.current.toLocaleString()}/${avgAmtProgress.total.toLocaleString()}, ${Math.round(progressPct)}%)` : '확정 데이터 갱신 중')
          bg = '#e3f2fd'; color = '#1565c0'
          break
        }
        default: {
          progressPct = avgAmtProgress.total > 0 ? (avgAmtProgress.current / avgAmtProgress.total) * 100 : 0
          msg = (avgAmtProgress.total > 0
            ? `전종목 5일거래대금/고가 데이터 다운로드 중 (${avgAmtProgress.current.toLocaleString()}/${avgAmtProgress.total.toLocaleString()}, ${Math.round(progressPct)}%)`
            : '전종목 5일 데이터 준비 중')
          break
        }
      }

      if (msg.length > 45) msg = msg.slice(0, 44) + '…'

      // 배경/보더 설정
      avgAmtChip.style.background = bg
      avgAmtChip.style.border = `1px solid ${color}20`

      // ETA 표시
      const isConfirmed = status === 'confirmed'
      const eta = (!isConfirmed && avgAmtProgress.eta_sec && avgAmtProgress.eta_sec > 0)
        ? ` · 약 ${avgAmtProgress.eta_sec >= 60 ? Math.ceil(avgAmtProgress.eta_sec / 60) + '분' : Math.ceil(avgAmtProgress.eta_sec) + '초'} 남음`
        : ''

      const finalMsg = msg + eta

      // 로딩 중이거나 다운로드 중일 때는 프로그레스 바 적용
      if (['downloading', 'confirmed', 'partial'].includes(status) || status === '') {
        // 내부 요소를 프로그레스바 구조로 재구성
        const fillColor = color + '30' // 투명도를 준 색상
        avgAmtChip.innerHTML = `
          <div style="position:absolute;left:0;top:0;height:100%;width:${progressPct}%;background:${fillColor};transition:width 0.3s ease;"></div>
          <span style="position:relative;color:${color};display:flex;align-items:center;gap:4px;z-index:1;">
            <span style="display:inline-block;animation:header-spin 1.2s linear infinite">⏳</span>
            ${finalMsg}
          </span>
        `
      } else {
        // 기타 고정 상태
        avgAmtChip.innerHTML = `<span style="position:relative;color:${color};z-index:1;">${finalMsg}</span>`
      }
    } else {
      avgAmtChip.style.display = 'none'
    }
  }

  // 엔진 상태
  if (modeChip && brokerChip && brokerWsChip) {
    if (status) {
      const wsOn = settings ? !!settings.ws_subscribe_on : true

      modeChip.style.display = ''
      applyStatusChip(modeChip, status.is_test_mode ? '테스트모드' : '실전모드', undefined, status.is_test_mode ? 'blue' : 'red')

      brokerChip.style.display = ''
      brokerWsChip.style.display = ''
      applyStatusChip(brokerChip, '키움증권', status.kiwoom_token_valid)
      applyStatusChip(brokerWsChip, '키움실시간', status.kiwoom_connected && wsOn)
    } else {
      modeChip.style.display = 'none'
      brokerChip.style.display = 'none'
      brokerWsChip.style.display = 'none'
    }
  }

  // 실시간 상태 표시줄
  if (realtimeStateChip) {
    if (realtimeStatus) {
      realtimeStateChip.style.display = ''
      if (realtimeStatus === 'waiting') {
        applyStatusChip(realtimeStateChip, '🟡 실시간 대기 중', false, 'off')
      } else if (realtimeStatus === 'live') {
        applyStatusChip(realtimeStateChip, '🟢 가동 중', true, 'on')
      }
    } else {
      realtimeStateChip.style.display = 'none'
    }
  }

  // 설정 상태
  if (autoTradeChip && autoBuyChip && autoSellChip && teleChip) {
    if (settings) {
      autoTradeChip.style.display = ''
      autoBuyChip.style.display = ''
      autoSellChip.style.display = ''
      teleChip.style.display = ''
      applyStatusChip(autoTradeChip, '자동매매', !!settings.time_scheduler_on)
      applyStatusChip(
        autoBuyChip,
        `자동매수 ${(settings.buy_time_start || '09:00').slice(0, 5)}~${(settings.buy_time_end || '15:20').slice(0, 5)}`,
        !!settings.auto_buy_on,
      )
      applyStatusChip(
        autoSellChip,
        `자동매도 ${(settings.sell_time_start || '09:00').slice(0, 5)}~${(settings.sell_time_end || '15:20').slice(0, 5)}`,
        !!settings.auto_sell_on,
      )
      applyStatusChip(teleChip, '텔레그램', settings.tele_on)
    } else {
      autoTradeChip.style.display = 'none'
      autoBuyChip.style.display = 'none'
      autoSellChip.style.display = 'none'
      teleChip.style.display = 'none'
    }
  }

  // 지수
  if (kospiChip && kosdaqChip) {
    if (status) {
      kospiChip.style.display = ''
      kosdaqChip.style.display = ''
      applyIndexChip(kospiChip, '코스피', status.kospi, status.index_polling, status.kiwoom_connected, marketPhase)
      applyIndexChip(kosdaqChip, '코스닥', status.kosdaq, status.index_polling, status.kiwoom_connected, marketPhase)
    } else {
      kospiChip.style.display = 'none'
      kosdaqChip.style.display = 'none'
    }
  }
}
