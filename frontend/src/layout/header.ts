// frontend/src/layout/header.ts
// Store 구독으로 장 상태, 앱 준비 상태, 엔진 상태, 설정 상태, 지수 실시간 표시
// 기존 Header.tsx의 모든 로직을 DOM 직접 업데이트로 전환

import { uiStore } from '../stores/uiStore'
import type { UIState } from '../stores/uiStore'
import { clearCircuitBreakerOpen, clearRiskBlockStatus, clearVirtualCashFailed, clearPositionBuildFailed, clearDegradedMode, clearTradeModeSwitchFailed } from '../stores/uiStore'
import type { IndexData } from '../types'
import { BROKER_LABELS } from '../components/common/broker-badge'
import { COLOR, RADIUS, BLUR, SURFACE_ALPHA, FONT_WEIGHT } from '../components/common/ui-styles'
import { isInTradeTimeWindow, isInNxtTradeWindow } from '../utils/order-block-status'
import { createIcon } from '../components/common/icon'

// ── 스타일 상수 ──

const CHIP_STYLE =
  `padding:3px 8px;border-radius:${RADIUS.lg};font-size:10px;font-weight:600;cursor:default;white-space:nowrap;`

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

// 경고 칩에 SVG 아이콘 + 텍스트 설정 (경고 이모지 → SVG 교체)
function setAlertChip(chip: HTMLSpanElement, text: string): void {
  chip.style.display = 'inline-flex'
  chip.style.alignItems = 'center'
  chip.style.gap = '4px'
  chip.textContent = ''
  chip.appendChild(createIcon('alert-triangle', { size: 11, color: chip.style.color }))
  chip.appendChild(document.createTextNode(text))
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
  // 분 단위까지만 표시 (60초 미만은 표시 안 함 — 개인 투자자에게 불필요한 노이즈).
  if (remaining_sec < 60) return null
  const min = Math.floor(remaining_sec / 60)
  const sec = remaining_sec % 60
  return sec > 0 ? `${label} ${min}분 ${sec}초 전` : `${label} ${min}분 전`
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
  const s = PHASE_STYLE[phase]
  if (!s) {
    // 정상 경로의 폴백 금지 (P20). 알 수 없는 phase는 백엔드-프론트 불일치이므로
    // 경고 로깅 후 칩만 neutral 기본 표시 — 나머지 헤더/화면은 정상 작동 (P21).
    console.warn('[header] 알 수 없는 장 phase:', phase)
    el.style.background = `${COLOR.neutralBg}`
    el.style.color = `${COLOR.neutral}`
    el.style.border = `1px solid ${COLOR.neutral}20`
    el.style.fontWeight = '600'
    el.textContent = `${market} ${phase}`
    return
  }
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
      return { msg: `전종목 5거래일 거래대금/고가 데이터 다운로드 중 (${p.current.toLocaleString()}/${p.total.toLocaleString()}, ${Math.round(pct())}%)`, bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: pct() }
    case 'completed':
      return { msg: '전종목 5거래일 거래대금,고가 데이터 다운로드 완료', bg: `${COLOR.successBg}`, color: `${COLOR.success}`, progressPct: 100 }
    case 'failed':
      return { msg: '전종목 5거래일 고가 실패', bg: `${COLOR.upBg}`, color: `${COLOR.up}`, progressPct: 0 }
    case 'partial': {
      const failedCount = (p as Record<string, unknown>).failed_count as number || 0
      return { msg: p.message || `다운로드 부분 완료 (${p.current.toLocaleString()}/${p.total.toLocaleString()}) — ${failedCount}종목 실패`, bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: pct() }
    }
    case 'cache_deleted':
      return { msg: '전종목 5거래일 고가 재계산 중', bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: 100 }
    case 'token_pending':
      return { msg: '인증 대기중', bg: `${COLOR.neutralBg}`, color: COLOR.tertiary, progressPct: 0 }
    case 'requested':
      return { msg: '전종목 5거래일 데이터 준비 시작', bg: `${COLOR.downBg}`, color: `${COLOR.down}`, progressPct: 0 }
    case 'confirmed':
      return { msg: (p.total > 0 ? `전종목 확정시세 데이터 다운로드 중 (${p.current.toLocaleString()}/${p.total.toLocaleString()}, ${Math.round(pct())}%)` : '확정 데이터 갱신 중'), bg: `${COLOR.downBg}`, color: `${COLOR.down}`, progressPct: pct() }
    default:
      return { msg: (p.total > 0 ? `전종목 5거래일 거래대금/고가 데이터 다운로드 중 (${p.current.toLocaleString()}/${p.total.toLocaleString()}, ${Math.round(pct())}%)` : '전종목 5거래일 데이터 준비 중'), bg: `${COLOR.warningBg}`, color: `${COLOR.warning}`, progressPct: pct() }
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

  // 로딩 중이거나 다운로드 중, 상태 미확정(status 빈 문자열)일 때 프로그레스 바 적용
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
    `box-sizing:border-box;padding:6px 16px;background:${SURFACE_ALPHA.toolbar};backdrop-filter:${BLUR.toolbar};-webkit-backdrop-filter:${BLUR.toolbar};border-bottom:1px solid ${COLOR.borderDark};display:flex;gap:8px;align-items:center;flex-wrap:nowrap;flex-shrink:0;height:52px;min-height:52px;max-height:52px;overflow-x:auto;overflow-y:hidden;`

  // 로고
  const logo = document.createElement('div')
  logo.style.cssText =
    `display:inline-flex;align-items:center;gap:8px;margin-right:4px;font-weight:${FONT_WEIGHT.bold};`

  const logoIcon = document.createElement('img')
  logoIcon.src = '/logo.png?v=2'
  logoIcon.alt = 'SectorFlow'
  logoIcon.width = 40
  logoIcon.height = 40
  logoIcon.style.cssText = `width:40px;height:40px;border-radius:${RADIUS.md};display:block;flex-shrink:0;object-fit:cover;`

  const logoText = document.createElement('span')
  logoText.textContent = 'SectorFlow'
  logo.appendChild(logoIcon)
  logo.appendChild(logoText)
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

  // 백그라운드 데이터 갱신 칩 (NXT/KRX 장 상태 칩 좌측 — 다운로드 표시/소멸 시 장 상태 칩 위치 고정)
  const avgAmtChip = createChipEl()
  avgAmtChip.style.display = 'none'
  header.appendChild(avgAmtChip)

  // NXT / KRX 장 상태 칩
  const nxtChip = createChipEl()
  const krxChip = createChipEl()
  header.appendChild(nxtChip)
  header.appendChild(krxChip)

  // KRX 알림 칩 (서킷브레이커/사이드카)
  const krxAlertChip = createChipEl()
  krxAlertChip.style.display = 'none'
  header.appendChild(krxAlertChip)

  // 엔진 상태 칩: 증권사(항상 표시, 상태만 갱신), 가상/실전매매
  const brokerChipsContainer = document.createElement('span')
  brokerChipsContainer.style.cssText = 'display:inline-flex;gap:4px;align-items:center;'
  header.appendChild(brokerChipsContainer)

  // 증권사 칩 미리 생성 (BROKER_LABELS 기반, 상태만 업데이트 — 재생성 금지)
  // 초기 display='none' — 첫 상태 갱신 시 활성 broker만 표시 (P21 비활성 증권사 칩 숨김)
  const brokerChipRefs: Record<string, { token: HTMLSpanElement; ws: HTMLSpanElement }> = {}
  for (const brokerId of Object.keys(BROKER_LABELS)) {
    const label = BROKER_LABELS[brokerId]
    const tokenChip = createChipEl()
    tokenChip.style.display = 'none'
    applyStatusChip(tokenChip, `${label}증권`, false)
    brokerChipsContainer.appendChild(tokenChip)

    const wsChip = createChipEl()
    wsChip.style.display = 'none'
    applyStatusChip(wsChip, `${label}실시간`, false)
    brokerChipsContainer.appendChild(wsChip)

    brokerChipRefs[brokerId] = { token: tokenChip, ws: wsChip }
  }

  // OMS 서킷브레이커 발동 칩 (클릭 시 해제)
  const circuitBreakerChip = createChipEl()
  circuitBreakerChip.style.display = 'none'
  circuitBreakerChip.style.cursor = 'pointer'
  circuitBreakerChip.addEventListener('click', () => {
    try { clearCircuitBreakerOpen() } catch (e) { console.error('[Header] circuitBreaker clear error', e) }
  })
  header.appendChild(circuitBreakerChip)

  // 리스크 매니저 차단 칩 (빨간색 — 손실 한도 도달, 클릭 시 해제)
  const riskBlockChip = createChipEl()
  riskBlockChip.style.display = 'none'
  riskBlockChip.style.cursor = 'pointer'
  riskBlockChip.addEventListener('click', () => {
    try { clearRiskBlockStatus() } catch (e) { console.error('[Header] riskBlock clear error', e) }
  })
  header.appendChild(riskBlockChip)

  // 가상매매 잔고 부족 칩 (노란색 — 사후 1회성, 클릭 시 해제)
  const virtualCashFailedChip = createChipEl()
  virtualCashFailedChip.style.display = 'none'
  virtualCashFailedChip.style.cursor = 'pointer'
  virtualCashFailedChip.addEventListener('click', () => {
    try { clearVirtualCashFailed() } catch (e) { console.error('[Header] virtualCashFailed clear error', e) }
  })
  header.appendChild(virtualCashFailedChip)

  // 포지션 구축 실패 칩 (노란색 — 지속 상태, 클릭 시 다음 index-data까지 해제)
  const positionBuildFailedChip = createChipEl()
  positionBuildFailedChip.style.display = 'none'
  positionBuildFailedChip.style.cursor = 'pointer'
  positionBuildFailedChip.addEventListener('click', () => {
    try { clearPositionBuildFailed() } catch (e) { console.error('[Header] positionBuildFailed clear error', e) }
  })
  header.appendChild(positionBuildFailedChip)

  // 감소 모드 기동 칩 (빨간색 — 치명 상태, 클릭 시 다음 index-data까지 해제)
  const degradedModeChip = createChipEl()
  degradedModeChip.style.display = 'none'
  degradedModeChip.style.cursor = 'pointer'
  degradedModeChip.addEventListener('click', () => {
    try { clearDegradedMode() } catch (e) { console.error('[Header] degradedMode clear error', e) }
  })
  header.appendChild(degradedModeChip)

  // 모드 전환 실패 칩 (빨간색 — 구독 전환 실패, 클릭 시 해제)
  const tradeModeSwitchFailedChip = createChipEl()
  tradeModeSwitchFailedChip.style.display = 'none'
  tradeModeSwitchFailedChip.style.cursor = 'pointer'
  tradeModeSwitchFailedChip.addEventListener('click', () => {
    try { clearTradeModeSwitchFailed() } catch (e) { console.error('[Header] tradeModeSwitchFailed clear error', e) }
  })
  header.appendChild(tradeModeSwitchFailedChip)

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

  // ── Store 구독 ──

  function onStateChange(state: UIState): void {
    const { marketPhase, avgAmtProgress, status, settings, indexData, circuitBreakerOpen, riskBlockStatus, virtualCashFailed, positionBuildFailed, degradedMode, tradeModeSwitchFailed } = state

    // P25: 칩 단위 격리 — 각 칩 렌더링 throw 시 해당 칩만 미갱신 + 로깅, 다음 칩 계속
    // (F-02 잔존 위험 해결 — onStateChange 콜백 내부 칩 간 격리)

    // OMS 서킷브레이커 발동 칩
    try {
      if (circuitBreakerOpen) {
        circuitBreakerChip.style.display = ''
        circuitBreakerChip.style.background = `${COLOR.upBg}`
        circuitBreakerChip.style.color = `${COLOR.up}`
        circuitBreakerChip.style.border = `1px solid ${COLOR.up}40`
        setAlertChip(circuitBreakerChip, circuitBreakerOpen.message)
      } else {
        circuitBreakerChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] circuitBreaker chip error', e) }

    // 리스크 매니저 차단 칩 (빨간색 — 손실 한도 도달, 클릭 시 해제)
    try {
      if (riskBlockStatus) {
        riskBlockChip.style.display = ''
        riskBlockChip.style.background = `${COLOR.upBg}`
        riskBlockChip.style.color = `${COLOR.up}`
        riskBlockChip.style.border = `1px solid ${COLOR.up}40`
        const sideLabel = riskBlockStatus.side === 'buy' ? '매수' : riskBlockStatus.side === 'sell' ? '매도' : '매매'
        setAlertChip(riskBlockChip, `리스크 차단(${sideLabel}): ${riskBlockStatus.reason}`)
      } else {
        riskBlockChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] riskBlock chip error', e) }

    // 가상매매 잔고 부족 칩 (노란색 — 사후 1회성, 클릭 시 해제)
    try {
      if (virtualCashFailed) {
        virtualCashFailedChip.style.display = ''
        virtualCashFailedChip.style.background = `${COLOR.warningBg}`
        virtualCashFailedChip.style.color = `${COLOR.warning}`
        virtualCashFailedChip.style.border = `1px solid ${COLOR.warning}40`
        const reasonText = virtualCashFailed.reason || '가상매매 잔고 부족 — 매수 거부'
        setAlertChip(virtualCashFailedChip, reasonText)
      } else {
        virtualCashFailedChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] virtualCashFailed chip error', e) }

    // 포지션 구축 실패 칩 (노란색 — 보유 종목 불러오기 실패, 엔진은 계속 가동)
    try {
      if (positionBuildFailed) {
        positionBuildFailedChip.style.display = ''
        positionBuildFailedChip.style.background = `${COLOR.warningBg}`
        positionBuildFailedChip.style.color = `${COLOR.warning}`
        positionBuildFailedChip.style.border = `1px solid ${COLOR.warning}40`
        setAlertChip(positionBuildFailedChip, '보유 종목 불러오기 실패 — 엔진은 계속 가동 중')
      } else {
        positionBuildFailedChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] positionBuildFailed chip error', e) }

    // 감소 모드 기동 칩 (빨간색 — 종목 데이터 불완전, 치명 상태)
    try {
      if (degradedMode) {
        degradedModeChip.style.display = ''
        degradedModeChip.style.background = `${COLOR.upBg}`
        degradedModeChip.style.color = `${COLOR.up}`
        degradedModeChip.style.border = `1px solid ${COLOR.up}40`
        setAlertChip(degradedModeChip, '감소 모드 기동 — 종목 데이터 불완전')
      } else {
        degradedModeChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] degradedMode chip error', e) }

    // 모드 전환 실패 칩 (빨간색 — 구독 전환 실패, 체결 수신 확인 필요)
    try {
      if (tradeModeSwitchFailed) {
        tradeModeSwitchFailedChip.style.display = ''
        tradeModeSwitchFailedChip.style.background = `${COLOR.upBg}`
        tradeModeSwitchFailedChip.style.color = `${COLOR.up}`
        tradeModeSwitchFailedChip.style.border = `1px solid ${COLOR.up}40`
        setAlertChip(tradeModeSwitchFailedChip, '모드 전환 실패 — 체결 수신 확인 필요')
      } else {
        tradeModeSwitchFailedChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] tradeModeSwitchFailed chip error', e) }

    // 장 상태 — 카운트다운(백엔드 SSOT 수신값)이 있으면 우선 표시, 없으면 시계 페이즈명
    // 서킷브레이커/사이드카 발동(krx_alert 있음) 시 NXT/KRX 칩 숨김, CB 알림 칩만 표시 (P21 투명성).
    try {
      if (marketPhase.krx_alert) {
        nxtChip.style.display = 'none'
      } else {
        applyMarketPhaseChip(nxtChip, 'NXT', marketPhase.nxt, formatCountdown(marketPhase.nxt_countdown))
      }
    } catch (e) { console.error('[header] nxt phase chip error', e) }
    try {
      if (marketPhase.krx_alert) {
        krxChip.style.display = 'none'
      } else {
        applyMarketPhaseChip(krxChip, 'KRX', marketPhase.krx, formatCountdown(marketPhase.krx_countdown))
      }
    } catch (e) { console.error('[header] krx phase chip error', e) }

    // 업종지수 실시간 — 칩은 항상 표시, 데이터 없으면 placeholder
    try {
      const kospi = indexData?.['001']
      const kosdaq = indexData?.['301']
      kospiChip.style.display = ''
      kosdaqChip.style.display = ''
      applyIndexChip(kospiChip, kospi ?? { upcode: '001' })
      applyIndexChip(kosdaqChip, kosdaq ?? { upcode: '301' })
    } catch (e) { console.error('[header] index chip error', e) }

    // KRX 알림 (서킷브레이커/사이드카)
    try {
      const alert = marketPhase.krx_alert
      if (alert) {
        krxAlertChip.style.display = ''
        krxAlertChip.style.background = `${COLOR.upBg}`
        krxAlertChip.style.color = `${COLOR.up}`
        krxAlertChip.style.border = `1px solid ${COLOR.up}40`
        setAlertChip(krxAlertChip, alert)
      } else {
        krxAlertChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] krxAlert chip error', e) }

    // 백그라운드 데이터 갱신
    try {
      if (avgAmtProgress) {
        renderAvgAmtChip(avgAmtChip, avgAmtProgress)
      } else {
        avgAmtChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] avgAmt chip error', e) }

    // 엔진 상태
    try {
      if (status) {
        modeChip.style.display = ''
        applyStatusChip(modeChip, status.is_virtual_mode ? '가상매매' : '실전매매', undefined, status.is_virtual_mode ? 'blue' : 'red')
      } else {
        modeChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] mode chip error', e) }

    // 증권사 칩 상태 업데이트 (미리 생성된 칩 재사용 — 재생성 금지)
    // P21: 비활성 증권사(broker_statuses에 없음) 칩은 숨김 — 회색 칩이 "연결 실패"로 오해되는 것 방지.
    // P10: 백엔드 broker_statuses(활성 broker만 포함)를 그대로 반영.
    // P25: 증권사 단위 격리 — 한 증권사 칩 렌더링 throw 시 해당 증권사만 스킵 + 로깅, 다른 증권사 계속
    const brokerStatuses = status?.broker_statuses ?? {}
    for (const brokerId of Object.keys(brokerChipRefs)) {
      try {
        const refs = brokerChipRefs[brokerId]
        const bs = brokerStatuses[brokerId]
        // 활성 broker만 표시, 비활성 증권사 칩 숨김
        const show = bs !== undefined
        refs.token.style.display = show ? '' : 'none'
        refs.ws.style.display = show ? '' : 'none'
        if (!show) continue
        const label = BROKER_LABELS[brokerId]
        applyStatusChip(refs.token, `${label}증권`, bs?.token_valid ?? false)
        applyStatusChip(refs.ws, `${label}실시간`, bs?.ws_connected ?? false)
      } catch (e) { console.error('[header] broker chip error', brokerId, e) }
    }

    // 설정 상태
    try {
      if (settings) {
        autoTradeChip.style.display = ''
        autoBuyChip.style.display = ''
        autoSellChip.style.display = ''
        teleChip.style.display = ''
        // 자동매매 칩: 마스터 ON + 거래일 + NXT 시간 창 내 → "자동매매" 녹색.
        // 마스터 ON + 휴장일 또는 NXT 시간 창 외 → "매매대기" 회색 (거래일 오면 자동 재개).
        // 마스터 OFF → "자동매매" 회색 (사용자가 직접 끈 상태 — 수동으로 다시 켜야 함).
        // 휴장일 판단은 marketPhase SSOT 사용, NXT 시간 창은 사용자 설정값 사용 (P10 SSOT, P21 투명성).
        const isHoliday = marketPhase.krx === '휴장일' || marketPhase.nxt === '휴장일'
        const isMasterOn = !!settings.time_scheduler_on
        const inNxtWindow = !isHoliday && isInNxtTradeWindow(settings)
        if (isMasterOn) {
          applyStatusChip(autoTradeChip, inNxtWindow ? '자동매매' : '매매대기', inNxtWindow)
        } else {
          applyStatusChip(autoTradeChip, '자동매매', false)
        }
        // 자동매수/매도 칩: 토글 ON + 현재 시간이 작동 시간 창 내일 때만 활성(녹색).
        // 시간 창 외면 회색(비활성) — 백엔드 _on_auto_trade_transition이 시간 전환 시점에
        // settings-changed WS를 push하므로 별도 타이머 없이 자동 갱신 (P10 SSOT, P21 투명성).
        applyStatusChip(
          autoBuyChip,
          `자동매수 ${(settings.buy_time_start || '09:00').slice(0, 5)}~${(settings.buy_time_end || '15:20').slice(0, 5)}`,
          !!settings.auto_buy_on && isInTradeTimeWindow(settings, 'buy'),
        )
        applyStatusChip(
          autoSellChip,
          `자동매도 ${(settings.sell_time_start || '09:00').slice(0, 5)}~${(settings.sell_time_end || '15:20').slice(0, 5)}`,
          !!settings.auto_sell_on && isInTradeTimeWindow(settings, 'sell'),
        )
        applyStatusChip(teleChip, '텔레그램', settings.tele_on)
      } else {
        autoTradeChip.style.display = 'none'
        autoBuyChip.style.display = 'none'
        autoSellChip.style.display = 'none'
        teleChip.style.display = 'none'
      }
    } catch (e) { console.error('[header] settings chip error', e) }

  }

  // M-09: 헤더 칩 갱신을 rAF로 모아 1프레임에 1회 실행 (중복 예약 방지)
  let headerRafId: number | null = null
  const unsubscribe = uiStore.subscribe(() => {
    if (headerRafId !== null) return
    headerRafId = requestAnimationFrame(() => {
      headerRafId = null
      onStateChange(uiStore.getState())
    })
  })

  // 초기 렌더링
  onStateChange(uiStore.getState())

  // 카운트다운 주기 갱신 — 30초 간격으로 수신값 재적용 (백엔드 push 보완, P16/P21)
  const countdownTimer = setInterval(() => {
    const { marketPhase } = uiStore.getState()
    applyMarketPhaseChip(nxtChip, 'NXT', marketPhase.nxt, formatCountdown(marketPhase.nxt_countdown))
    applyMarketPhaseChip(krxChip, 'KRX', marketPhase.krx, formatCountdown(marketPhase.krx_countdown))
  }, 30_000)

  function destroy(): void {
    unsubscribe()
    clearInterval(countdownTimer)
    if (headerRafId !== null) {
      cancelAnimationFrame(headerRafId)
      headerRafId = null
    }
  }

  return { el: header, destroy }
}
