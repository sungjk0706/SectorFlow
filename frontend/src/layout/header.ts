// frontend/src/layout/header.ts
// Store 구독으로 장 상태, 앱 준비 상태, 엔진 상태, 설정 상태, 지수 실시간 표시
// 기존 Header.tsx의 모든 로직을 DOM 직접 업데이트로 전환

import { uiStore } from '../stores/uiStore'
import type { UIState } from '../stores/uiStore'
import type { IndexData } from '../types'

// ── 스타일 상수 ──

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

// ── 인라인 StatusChip 헬퍼 ──

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
  // active 판단: marketPhase 기반
  // - KRX 정규장(09:00~15:30): connected 기준
  // - 폴링 구간(ws_subscribe_start~09:00, 15:30~ws_subscribe_end): polling 기준
  // - 장마감/휴장일: false (회색)
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


// ── spin 키프레임 (1회 삽입) ──

let spinInjected = false
function ensureSpinKeyframes(): void {
  if (spinInjected) return
  const style = document.createElement('style')
  style.textContent =
    '@keyframes header-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }'
  document.head.appendChild(style)
  spinInjected = true
}

// ── createHeader ──

export function createHeader(): { el: HTMLElement; destroy(): void } {
  ensureSpinKeyframes()

  const header = document.createElement('header')
  header.style.cssText =
    'box-sizing:border-box;padding:4px 16px;border-bottom:1px solid #ddd;display:flex;gap:8px;align-items:center;flex-wrap:nowrap;flex-shrink:0;height:40px;min-height:40px;max-height:40px;overflow-x:auto;overflow-y:hidden;'

  // 로고
  const logo = document.createElement('strong')
  logo.style.marginRight = 'auto'
  logo.textContent = '🌊 SectorFlow'
  header.appendChild(logo)

  // 백그라운드 데이터 갱신 칩
  const avgAmtChip = createChipEl()
  avgAmtChip.style.display = 'none'
  header.appendChild(avgAmtChip)

  // 엔진 상태 칩: 키움증권, 키움실시간, 테스트/실전모드
  const kiwoomBrokerChip = createChipEl()
  kiwoomBrokerChip.style.display = 'none'
  const kiwoomWsChip = createChipEl()
  kiwoomWsChip.style.display = 'none'
  const modeChip = createChipEl()
  modeChip.style.display = 'none'
  header.appendChild(kiwoomBrokerChip)
  header.appendChild(kiwoomWsChip)
  header.appendChild(modeChip)

  // KRX / NXT 장 상태 칩
  const krxChip = createChipEl()
  const nxtChip = createChipEl()
  header.appendChild(krxChip)
  header.appendChild(nxtChip)

  // 앱준비 진행률 칩
  const bootstrapChip = createChipEl()
  bootstrapChip.style.display = 'none'
  header.appendChild(bootstrapChip)

  // 설정 상태 칩: 자동매매, 자동매수, 자동매도, 텔레그램
  const autoTradeChip = createChipEl()
  autoTradeChip.style.display = 'none'
  const autoBuyChip = createChipEl()
  autoBuyChip.style.display = 'none'
  const autoSellChip = createChipEl()
  autoSellChip.style.display = 'none'
  const teleChip = createChipEl()
  teleChip.style.display = 'none'
  header.appendChild(autoTradeChip)
  header.appendChild(autoBuyChip)
  header.appendChild(autoSellChip)
  header.appendChild(teleChip)

  // 지수 칩: 코스피, 코스닥
  const kospiChip = createChipEl()
  kospiChip.style.display = 'none'
  const kosdaqChip = createChipEl()
  kosdaqChip.style.display = 'none'
  header.appendChild(kospiChip)
  header.appendChild(kosdaqChip)

  const spinnerHtml = '<span style="display:inline-block;animation:header-spin 1.2s linear infinite">⏳</span>'

  // ── Store 구독 ──

  function onStateChange(state: UIState): void {
    const { marketPhase, bootstrapStage, engineReady, avgAmtProgress, status, settings } = state

    // 장 상태
    applyMarketPhaseChip(krxChip, 'KRX', marketPhase.krx)
    applyMarketPhaseChip(nxtChip, 'NXT', marketPhase.nxt)

    // 앱준비 진행률
    if (bootstrapStage && !engineReady) {
      bootstrapChip.style.display = ''
      bootstrapChip.style.background = '#f3e5f5'
      bootstrapChip.style.color = '#6a1b9a'
      bootstrapChip.style.border = '1px solid #6a1b9a20'
      let text = ` ${bootstrapStage.stage_name}`
      if (bootstrapStage.progress) {
        text += ` (${bootstrapStage.progress.current}/${bootstrapStage.progress.total})`
      }
      bootstrapChip.innerHTML = spinnerHtml + text
    } else {
      bootstrapChip.style.display = 'none'
    }

    // 백그라운드 데이터 갱신
    if (avgAmtProgress) {
      avgAmtChip.style.display = 'flex'
      avgAmtChip.style.position = 'relative'
      avgAmtChip.style.overflow = 'hidden'
      avgAmtChip.style.alignItems = 'center'
      avgAmtChip.style.padding = '3px 8px'

      const status = (avgAmtProgress as Record<string, unknown>).status as string || ''
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
        const fillColor = color + '30' // 투명도를 준 색상
        avgAmtChip.innerHTML = `
          <div style="position:absolute;left:0;top:0;height:100%;width:${progressPct}%;background:${fillColor};transition:width 0.3s ease;"></div>
          <span style="position:relative;color:${color};display:flex;align-items:center;gap:4px;z-index:1;">
            <span style="display:inline-block;animation:header-spin 1.2s linear infinite">⏳</span>
            ${finalMsg}
          </span>
        `
      } else {
        avgAmtChip.innerHTML = `<span style="position:relative;color:${color};z-index:1;">${finalMsg}</span>`
      }
    } else {
      avgAmtChip.style.display = 'none'
    }

    // 엔진 상태
    if (status) {
      const wsOn = settings ? !!settings.ws_subscribe_on : true

      modeChip.style.display = ''
      applyStatusChip(modeChip, status.is_test_mode ? '테스트모드' : '실전모드', undefined, status.is_test_mode ? 'blue' : 'red')

      kiwoomBrokerChip.style.display = ''
      kiwoomWsChip.style.display = ''
      applyStatusChip(kiwoomBrokerChip, '키움증권', status.kiwoom_token_valid)
      applyStatusChip(kiwoomWsChip, '키움실시간', status.kiwoom_connected && wsOn)
    } else {
      modeChip.style.display = 'none'
      kiwoomBrokerChip.style.display = 'none'
      kiwoomWsChip.style.display = 'none'
    }

    // 설정 상태
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

    // 지수
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

  const unsubscribe = uiStore.subscribe(onStateChange)

  // 초기 렌더링
  onStateChange(uiStore.getState())

  function destroy(): void {
    unsubscribe()
  }

  return { el: header, destroy }
}
