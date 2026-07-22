// frontend/src/layout/header.ts
// Store 구독으로 장 상태, 앱 준비 상태, 엔진 상태, 설정 상태, 지수 실시간 표시
// 기존 Header.tsx의 모든 로직을 DOM 직접 업데이트로 전환

import { uiStore } from '../stores/uiStore'
import type { UIState } from '../stores/uiStore'
import { clearCircuitBreakerOpen, clearOrderTimeBlocked, clearRiskBlockStatus } from '../stores/uiStore'
import type { IndexData } from '../types'
import { BROKER_LABELS } from '../components/common/broker-badge'
import { COLOR } from '../components/common/ui-styles'

// ── 스타일 상수 ──

const CHIP_STYLE =
  'padding:3px 8px;border-radius:10px;font-size:10px;font-weight:600;cursor:default;white-space:nowrap;'

const PHASE_STYLE: Record<string, { bg: string; color: string }> = {
  /* 장중(거래 가능) — 초록 */
  '장전 시간외': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '시가 동시호가': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '정규장': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '종가 동시호가': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '장후 시간외': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '시간외 종가매매 종료 + 시간외 단일가매매 개시': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '프리마켓': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '메인마켓': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '애프터마켓': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  '애프터마켓 지속': { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  /* 비장중(휴장/대기/거래없음/종료) — 회색 */
  '휴장일': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '장개시전': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '장전 대기': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '동시호가 접수': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '체결 정산': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '장 종료': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '정규장 준비': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '조기 마감': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '단일가 매매': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  '장마감': { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
}

const STATUS_THEME = {
  on: { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  off: { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  blue: { bg: `${COLOR.downBg}`, color: `${COLOR.down}` },
  red: { bg: `${COLOR.upBg}`, color: `${COLOR.up}` },
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

// ── 장 페이즈 카운트다운 표시 (백엔드 SSOT 수신값 — P10) ──
// 카운트다운 계산은 백엔드 calc_countdown()이 담당 (10초 간격 WS push).
// 프론트엔드는 수신값을 포맷하여 칩에 표시만 수행. 30초 setInterval은 백엔드 push 보완 (P16).
function formatCountdown(
  countdown: { label: string; remaining_sec: number } | null | undefined,
): string | null {
  if (!countdown) return null
  const { label, remaining_sec } = countdown
  if (remaining_sec <= 0) return null
  if (remaining_sec >= 60) return `${label} ${Math.floor(remaining_sec / 60)}분 전`
  return `${label} ${remaining_sec}초 전`
}

function applyMarketPhaseChip(
  el: HTMLSpanElement,
  market: string,
  phase: string,
  countdown?: string | null,
): void {
  // 카운트다운 표시가 있으면 우선 표시(강조색), 없으면 시계 페이즈명 표시
  if (countdown) {
    el.style.background = `${COLOR.warningBg}`
    el.style.color = `${COLOR.warning}`
    el.style.border = `1px solid ${COLOR.warning}40`
    el.style.fontWeight = '700'
    el.textContent = `${market} ${countdown}`
    return
  }
  const s = PHASE_STYLE[phase] || PHASE_STYLE['장마감']
  el.style.background = s.bg
  el.style.color = s.color
  el.style.border = `1px solid ${s.color}20`
  el.style.fontWeight = '600'
  el.textContent = `${market} ${phase}`
}

const INDEX_LABELS: Record<string, string> = {
  '001': '코스피',
  '301': '코스닥',
}

// ── 백그라운드 데이터 갱신 칩 렌더링 ──
// avgAmtProgress 상태를 avgAmtChip에 반영. onStateChange에서 분리 (P24 단순성).
type AvgAmtProgress = NonNullable<UIState['avgAmtProgress']>

interface AvgAmtRender {
  msg: string
  bg: string
  color: string
  progressPct: number
}

// 백엔드 메시지가 비어있을 때 상태별 하드코딩 템플릿
function resolveAvgAmtMsg(p: AvgAmtProgress, status: string): { msg: string; bg: string; color: string; progressPct: number } {
  const pct = () => p.total > 0 ? (p.current / p.total) * 100 : 0
  switch (status) {
    case 'downloading':
      return { msg: `전종목 5일거래대금/고가 데이터 다운로드 중 (${p.current.toLocaleString()}/${p.total.toLocaleString()}, ${Math.round(pct())}%)`, bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: pct() }
    case 'completed':
      return { msg: '전종목 5일 거래대금,고가 데이터 다운로드 완료', bg: `${COLOR.successBg}`, color: `${COLOR.success}`, progressPct: 100 }
    case 'failed':
      return { msg: '전종목 5일 고가 실패', bg: `${COLOR.upBg}`, color: `${COLOR.up}`, progressPct: 0 }
    case 'partial': {
      const failedCount = (p as Record<string, unknown>).failed_count as number || 0
      return { msg: p.message || `⚠️ 다운로드 부분 완료 (${p.current.toLocaleString()}/${p.total.toLocaleString()}) — ${failedCount}종목 실패`, bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: pct() }
    }
    case 'cache_deleted':
      return { msg: '전종목 5일 고가 재계산 중', bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: 100 }
    case 'token_pending':
      return { msg: '인증 대기중', bg: `${COLOR.neutralBg}`, color: COLOR.tertiary, progressPct: 0 }
    case 'requested':
      return { msg: '전종목 5일 데이터 준비 시작', bg: `${COLOR.downBg}`, color: `${COLOR.down}`, progressPct: 0 }
    case 'confirmed':
      return { msg: (p.total > 0 ? `전종목 확정시세 데이터 다운로드 중 (${p.current.toLocaleString()}/${p.total.toLocaleString()}, ${Math.round(pct())}%)` : '확정 데이터 갱신 중'), bg: `${COLOR.downBg}`, color: `${COLOR.down}`, progressPct: pct() }
    default:
      return { msg: (p.total > 0 ? `전종목 5일거래대금/고가 데이터 다운로드 중 (${p.current.toLocaleString()}/${p.total.toLocaleString()}, ${Math.round(pct())}%)` : '전종목 5일 데이터 준비 중'), bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: pct() }
  }
}

// 백엔드 메시지가 있을 때 상태별 스타일만 결정
function resolveAvgAmtStyle(status: string, p: AvgAmtProgress): { bg: string; color: string; progressPct: number } {
  const progressPct = p.total > 0 ? (p.current / p.total) * 100 : 0
  if (status === 'completed') return { bg: `${COLOR.successBg}`, color: `${COLOR.success}`, progressPct }
  if (status === 'confirmed') return { bg: `${COLOR.downBg}`, color: `${COLOR.down}`, progressPct }
  if (status === 'failed') return { bg: `${COLOR.upBg}`, color: `${COLOR.up}`, progressPct }
  return { bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct }
}

function renderAvgAmtChip(chip: HTMLSpanElement, p: AvgAmtProgress): void {
  chip.style.display = 'flex'
  chip.style.position = 'relative'
  chip.style.overflow = 'hidden'
  chip.style.alignItems = 'center'
  chip.style.padding = '3px 8px'

  const status = (p as Record<string, unknown>).status as string || ''
  const backendMsg = p.message || ''
  let r: AvgAmtRender
  if (backendMsg) {
    const s = resolveAvgAmtStyle(status, p)
    r = { msg: backendMsg, bg: s.bg, color: s.color, progressPct: s.progressPct }
  } else {
    r = resolveAvgAmtMsg(p, status)
  }

  let msg = r.msg
  if (msg.length > 45) msg = msg.slice(0, 44) + '…'

  chip.style.background = r.bg
  chip.style.border = `1px solid ${r.color}20`

  // ETA 표시
  const etaSec = p.eta_sec ?? 0
  const sec = Math.ceil(etaSec)
  const eta = etaSec > 0 ? ` · 약 ${sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`} 남음` : ''
  const finalMsg = msg + eta

  // 로딩 중이거나 다운로드 중일 때는 프로그레스 바 적용
  if (['downloading', 'confirmed', 'partial'].includes(status) || status === '') {
    const fillColor = r.color + '30'
    chip.innerHTML = `
      <div style="position:absolute;left:0;top:0;height:100%;width:${r.progressPct}%;background:${fillColor};transition:width 0.3s ease;"></div>
      <span style="position:relative;color:${r.color};display:flex;align-items:center;gap:4px;z-index:1;">
        <span style="display:inline-block;width:12px;height:12px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:header-spin 0.8s linear infinite"></span>
        ${finalMsg}
      </span>
    `
  } else {
    chip.innerHTML = `<span style="position:relative;color:${r.color};z-index:1;">${finalMsg}</span>`
  }
}

function applyIndexChip(el: HTMLSpanElement, data: IndexData): void {
  const upcode = data.upcode ?? ''
  const label = INDEX_LABELS[upcode] || upcode
  const sign = data.sign ?? ''
  let bg = `${COLOR.neutralBg}`
  let color = `${COLOR.neutral}`
  let prefix = ''
  if (sign === '1' || sign === '2') {
    bg = `${COLOR.upBg}`; color = `${COLOR.up}`; prefix = '+'
  } else if (sign === '4' || sign === '5') {
    bg = `${COLOR.downBg}`; color = `${COLOR.down}`
  }
  el.style.background = bg
  el.style.border = `1px solid ${color}20`
  // drate에 이미 부호가 있으면 prefix 추가하지 않음 (이중 마이너스 방지)
  const rawDrate = data.drate ?? ''
  const hasSign = rawDrate.startsWith('-') || rawDrate.startsWith('+')
  const drateStr = rawDrate ? `${hasSign ? '' : prefix}${rawDrate}%` : '--'
  const jisuStr = data.jisu ?? '--'
  // 라벨은 검정색, 등락률/지수만 색상 적용
  const arrow = sign === '1' || sign === '2' ? '▲' : sign === '4' || sign === '5' ? '▼' : '－'
  el.innerHTML = `<span style="color:${color};font-weight:700;">${arrow}</span> <span style="color:${COLOR.neutral};font-weight:700;">${label}</span><span style="color:${color};margin-left:6px;">${jisuStr}</span><span style="color:${color};margin-left:4px;">${drateStr}</span>`
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
    `box-sizing:border-box;padding:4px 16px;border-bottom:1px solid ${COLOR.borderDark};display:flex;gap:8px;align-items:center;flex-wrap:nowrap;flex-shrink:0;height:40px;min-height:40px;max-height:40px;overflow-x:auto;overflow-y:hidden;`

  // 로고
  const logo = document.createElement('strong')
  logo.style.marginRight = '4px'
  logo.textContent = '🌊 SectorFlow'
  header.appendChild(logo)

  // 투자모드 칩 (로고 바로 우측, 독립적 위치 — 시각적 우선순위)
  const modeChip = createChipEl()
  modeChip.style.display = 'none'
  modeChip.style.marginRight = 'auto'
  modeChip.style.marginLeft = '12px'
  modeChip.style.fontSize = '12px'
  modeChip.style.padding = '4px 12px'
  modeChip.style.fontWeight = '700'
  header.appendChild(modeChip)

  // 백그라운드 데이터 갱신 칩
  const avgAmtChip = createChipEl()
  avgAmtChip.style.display = 'none'
  header.appendChild(avgAmtChip)

  // 엔진 상태 칩: 증권사(항상 표시, 상태만 갱신), 테스트/실전모드
  const brokerChipsContainer = document.createElement('span')
  brokerChipsContainer.style.cssText = 'display:inline-flex;gap:4px;align-items:center;'
  header.appendChild(brokerChipsContainer)

  // 증권사 칩 미리 생성 (BROKER_LABELS 기반, 상태만 업데이트 — 재생성 금지)
  const brokerChipRefs: Record<string, { token: HTMLSpanElement; ws: HTMLSpanElement }> = {}
  for (const brokerId of Object.keys(BROKER_LABELS)) {
    const label = BROKER_LABELS[brokerId]
    const tokenChip = createChipEl()
    applyStatusChip(tokenChip, `${label}증권`, false)
    brokerChipsContainer.appendChild(tokenChip)

    const wsChip = createChipEl()
    applyStatusChip(wsChip, `${label}실시간`, false)
    brokerChipsContainer.appendChild(wsChip)

    brokerChipRefs[brokerId] = { token: tokenChip, ws: wsChip }
  }

  // KRX / NXT 장 상태 칩
  const krxChip = createChipEl()
  const nxtChip = createChipEl()
  header.appendChild(krxChip)
  header.appendChild(nxtChip)

  // KRX 알림 칩 (서킷브레이커/사이드카)
  const krxAlertChip = createChipEl()
  krxAlertChip.style.display = 'none'
  header.appendChild(krxAlertChip)

  // OMS 서킷브레이커 발동 칩 (클릭 시 해제)
  const circuitBreakerChip = createChipEl()
  circuitBreakerChip.style.display = 'none'
  circuitBreakerChip.style.cursor = 'pointer'
  circuitBreakerChip.addEventListener('click', () => clearCircuitBreakerOpen())
  header.appendChild(circuitBreakerChip)

  // 체결 불가 시간대 주문 일시중단 칩 (클릭 시 해제)
  const orderTimeBlockedChip = createChipEl()
  orderTimeBlockedChip.style.display = 'none'
  orderTimeBlockedChip.style.cursor = 'pointer'
  orderTimeBlockedChip.addEventListener('click', () => clearOrderTimeBlocked())
  header.appendChild(orderTimeBlockedChip)

  // 리스크 매니저 차단 칩 (빨간색 — 손실/수익 한도 도달, 클릭 시 해제)
  const riskBlockChip = createChipEl()
  riskBlockChip.style.display = 'none'
  riskBlockChip.style.cursor = 'pointer'
  riskBlockChip.addEventListener('click', () => clearRiskBlockStatus())
  header.appendChild(riskBlockChip)

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

  // 업종지수 칩 (헤더 최우측)
  const kospiChip = createChipEl()
  const kosdaqChip = createChipEl()
  kospiChip.style.display = 'none'
  kosdaqChip.style.display = 'none'
  header.appendChild(kospiChip)
  header.appendChild(kosdaqChip)

  const spinnerHtml = '<span style="display:inline-block;width:12px;height:12px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:header-spin 0.8s linear infinite"></span>'

  // ── Store 구독 ──

  function onStateChange(state: UIState): void {
    const { marketPhase, bootstrapStage, engineReady, avgAmtProgress, status, settings, indexData, circuitBreakerOpen, orderTimeBlocked, riskBlockStatus } = state

    // OMS 서킷브레이커 발동 칩
    if (circuitBreakerOpen) {
      circuitBreakerChip.style.display = ''
      circuitBreakerChip.style.background = `${COLOR.upBg}`
      circuitBreakerChip.style.color = `${COLOR.up}`
      circuitBreakerChip.style.border = `1px solid ${COLOR.up}40`
      circuitBreakerChip.textContent = `⚠ ${circuitBreakerOpen.message}`
    } else {
      circuitBreakerChip.style.display = 'none'
    }

    // 체결 불가 시간대 주문 일시중단 칩 (노란색 — 동시호가/장외)
    if (orderTimeBlocked) {
      orderTimeBlockedChip.style.display = ''
      orderTimeBlockedChip.style.background = `${COLOR.warningBg}`
      orderTimeBlockedChip.style.color = `${COLOR.warning}`
      orderTimeBlockedChip.style.border = `1px solid ${COLOR.warning}40`
      orderTimeBlockedChip.textContent = `⏸ 주문 일시중단(${orderTimeBlocked.reason})`
    } else {
      orderTimeBlockedChip.style.display = 'none'
    }

    // 리스크 매니저 차단 칩 (빨간색 — 손실/수익 한도 도달, 클릭 시 해제)
    if (riskBlockStatus) {
      riskBlockChip.style.display = ''
      riskBlockChip.style.background = `${COLOR.upBg}`
      riskBlockChip.style.color = `${COLOR.up}`
      riskBlockChip.style.border = `1px solid ${COLOR.up}40`
      const sideLabel = riskBlockStatus.side === 'buy' ? '매수' : riskBlockStatus.side === 'sell' ? '매도' : '매매'
      riskBlockChip.textContent = `⚠ 리스크 차단(${sideLabel}): ${riskBlockStatus.reason}`
    } else {
      riskBlockChip.style.display = 'none'
    }

    // 장 상태 — 카운트다운(백엔드 SSOT 수신값)이 있으면 우선 표시, 없으면 시계 페이즈명
    applyMarketPhaseChip(krxChip, 'KRX', marketPhase.krx, formatCountdown(marketPhase.krx_countdown))
    applyMarketPhaseChip(nxtChip, 'NXT', marketPhase.nxt, formatCountdown(marketPhase.nxt_countdown))

    // 업종지수 실시간 — 칩은 항상 표시, 데이터 없으면 placeholder
    const kospi = indexData?.['001']
    const kosdaq = indexData?.['301']
    kospiChip.style.display = ''
    kosdaqChip.style.display = ''
    applyIndexChip(kospiChip, kospi ?? { upcode: '001' })
    applyIndexChip(kosdaqChip, kosdaq ?? { upcode: '301' })

    // KRX 알림 (서킷브레이커/사이드카)
    const alert = marketPhase.krx_alert
    if (alert) {
      krxAlertChip.style.display = ''
      krxAlertChip.style.background = `${COLOR.upBg}`
      krxAlertChip.style.color = `${COLOR.up}`
      krxAlertChip.style.border = `1px solid ${COLOR.up}40`
      krxAlertChip.textContent = `⚠ ${alert}`
    } else {
      krxAlertChip.style.display = 'none'
    }

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
      renderAvgAmtChip(avgAmtChip, avgAmtProgress)
    } else {
      avgAmtChip.style.display = 'none'
    }

    // 엔진 상태
    if (status) {
      modeChip.style.display = ''
      applyStatusChip(modeChip, status.is_test_mode ? '테스트모드' : '실전모드', undefined, status.is_test_mode ? 'blue' : 'red')
    } else {
      modeChip.style.display = 'none'
    }

    // 증권사 칩 상태 업데이트 (미리 생성된 칩 재사용 — 재생성 금지)
    const brokerStatuses = status?.broker_statuses ?? {}
    for (const brokerId of Object.keys(brokerChipRefs)) {
      const refs = brokerChipRefs[brokerId]
      const bs = brokerStatuses[brokerId]
      const label = BROKER_LABELS[brokerId]
      applyStatusChip(refs.token, `${label}증권`, bs?.token_valid ?? false)
      applyStatusChip(refs.ws, `${label}실시간`, bs?.ws_connected ?? false)
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

  }

  const unsubscribe = uiStore.subscribe(onStateChange)

  // 초기 렌더링
  onStateChange(uiStore.getState())

  // 카운트다운 주기 갱신 — 30초 간격으로 수신값 재적용 (백엔드 push 보완, P16/P21)
  const countdownTimer = setInterval(() => {
    const { marketPhase } = uiStore.getState()
    applyMarketPhaseChip(krxChip, 'KRX', marketPhase.krx, formatCountdown(marketPhase.krx_countdown))
    applyMarketPhaseChip(nxtChip, 'NXT', marketPhase.nxt, formatCountdown(marketPhase.nxt_countdown))
  }, 30_000)

  function destroy(): void {
    unsubscribe()
    clearInterval(countdownTimer)
  }

  return { el: header, destroy }
}
