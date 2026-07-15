/**
 * Canvas 2D API 기반 프리미엄 수익 현황 차트
 * - 막대: 일별 실현손익 (Daily PnL)
 * - 라인: 누적 실현손익 (Cumulative PnL / Equity Curve)
 * - 인터랙티브: 크로스헤어, 툴팁
 */

import { pnlColor, FONT_FAMILY, COLOR, fmtWon, positionTooltip } from './common/ui-styles'
import { createToggleSelectBtn } from './common/button'
import { createDateRangeInput } from './common/date-range-input'

// ── 타입 ────────────────────────────────────────────────────

export interface ProfitChartRow {
  date: string
  pnl: number | null
  rate: number
  buyFee?: number
  sellFee?: number
  tax?: number
}

// 내부에서 누적 합계가 포함된 확장 타입
interface DisplayRow extends ProfitChartRow {
  cumulative: number
}

export interface QuickDateRange {
  label: string
  from?: string
  to?: string
  days?: number
}

export interface ProfitChartOptions {
  container: HTMLElement
  data: ProfitChartRow[]
  mode?: 'pnl' | 'volume'
  maxBars?: number
  height?: number
  onDateRangeChange?: (from: string, to: string, days?: number, label?: string) => void
  dateFrom?: string
  dateTo?: string
  quickDateRanges?: QuickDateRange[]
  /** 초기 활성 빠른 버튼 라벨 (영속화 복원용) */
  initialActiveQuickLabel?: string
}

export interface ProfitChartApi {
  el: HTMLElement
  updateData(data: ProfitChartRow[]): void
  resize(): void
  destroy(): void
  setDateRange(from: string, to: string, label?: string): void
}

// ── 상수 ───────────────────────────────────────────────

const CHART_HEIGHT = 220
const PADDING = { top: 20, right: 48, bottom: 30, left: 48 }
const BAR_RADIUS = 3
const BAR_GAP_RATIO = 0.3
const COLORS = {
  profit: [COLOR.up, COLOR.upLight],
  loss: [COLOR.down, COLOR.downLight],
  volume: [COLOR.down, COLOR.downLight],
  equity: COLOR.down,
  equityArea: 'rgba(25, 118, 210, 0.08)',
  grid: COLOR.hoverBg,
  axis: COLOR.tertiary,
  zeroLine: COLOR.borderDark,
  crosshair: 'rgba(0,0,0,0.1)'
}

// ── 유틸 ────────────────────────────────────────────────────

function formatDate(dateStr: string): string {
  if (dateStr.length >= 10 && dateStr[4] === '-') return dateStr.slice(5, 10).replace('-', '/')
  return dateStr
}

function formatAmountWon(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 100000000) return `${(value / 100000000).toFixed(1)}억`
  if (abs >= 10000) return `${Math.round(value / 10000)}만`
  return String(value)
}

function formatCount(value: number): string {
  return String(Math.round(value))
}

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`
}

/** 그리드 눈금을 위한 적절한 간격 계산 */
function computeYTicks(minVal: number, maxVal: number): number[] {
  const range = maxVal - minVal
  if (range === 0) return [minVal - 10000, minVal, minVal + 10000]
  
  const rawStep = range / 4
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)))
  const res = rawStep / mag
  let step = mag
  if (res > 5) step = 10 * mag
  else if (res > 2) step = 5 * mag
  else if (res > 1) step = 2 * mag
  
  const ticks: number[] = []
  const start = Math.floor(minVal / step) * step
  for (let v = start; v <= maxVal + step * 0.01; v += step) {
    ticks.push(v)
  }
  return ticks
}

// ── 메인 팩토리 ──────────────────────────────────────────────

export function createProfitChart(options: ProfitChartOptions): ProfitChartApi {
  const { container, mode = 'pnl', maxBars = 30, height = CHART_HEIGHT } = options
  
  let isSample = false
  let displayData: DisplayRow[] = []

  // ── 데이터 처리 (누적 합계 계산) ──────────────────────────
  function processData(rows: ProfitChartRow[]): DisplayRow[] {
    if (mode === 'volume') {
      return rows.map(r => ({ ...r, cumulative: r.rate }))
    }
    let cumulative = 0
    return rows.map(r => {
      cumulative += (r.pnl || 0)
      return { ...r, cumulative }
    })
  }

  // 데이터 갱신 로직 (초기화 및 updateData 공용)
  function refreshInternal(newData: ProfitChartRow[]) {
    const dataSlice = newData.slice(-maxBars)
    isSample = dataSlice.length === 0 || dataSlice.every(d => d.pnl === null)
    displayData = isSample ? [] : processData(dataSlice)
    render()
  }

  // ── DOM 구조 ──────────────────────────────────────────────
  const wrapper = document.createElement('div')
  wrapper.style.cssText = 'position:relative;width:100%;height:100%;'

  const dateHeader = document.createElement('div')
  dateHeader.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 0;margin-bottom:4px;'

  const now = new Date()
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const monthFirstStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`

  const dateRangeInput = createDateRangeInput({
    from: options.dateFrom || monthFirstStr,
    to: options.dateTo || todayStr,
    onChange: (from, to) => {
      // 수동 날짜 변경 시 모든 빠른 버튼 비활성화
      _activeQuickIdx = -1
      updateQuickBtnActive()
      options.onDateRangeChange?.(from, to, undefined, undefined)
    },
  })

  dateHeader.appendChild(dateRangeInput.el)

  // 빠른 날짜 범위 버튼들
  const quickRanges = options.quickDateRanges ?? []
  let _activeQuickIdx = -1
  const quickBtnHandles: ReturnType<typeof createToggleSelectBtn>[] = []

  function updateQuickBtnActive(): void {
    quickBtnHandles.forEach((h, i) => h.setActive(i === _activeQuickIdx))
  }

  for (let i = 0; i < quickRanges.length; i++) {
    const qr = quickRanges[i]
    const handle = createToggleSelectBtn({
      label: qr.label,
      active: false,
      onClick: () => {
        _activeQuickIdx = i
        updateQuickBtnActive()
        const from = qr.from ?? ''
        const to = qr.to ?? ''
        dateRangeInput.setValue(from, to)
        options.onDateRangeChange?.(from, to, qr.days, qr.label)
      },
    })
    if (i === 0) handle.el.style.marginLeft = 'auto'
    quickBtnHandles.push(handle)
    dateHeader.appendChild(handle.el)
  }
  // 초기 활성 버튼 복원 (영속화된 quickLabel 기반)
  if (options.initialActiveQuickLabel) {
    _activeQuickIdx = quickRanges.findIndex(qr => qr.label === options.initialActiveQuickLabel)
  }
  updateQuickBtnActive()

  wrapper.appendChild(dateHeader)

  const canvasWrap = document.createElement('div')
  canvasWrap.style.cssText = `position:relative;width:100%;height:${height}px;background:${COLOR.white};overflow:hidden;`
  wrapper.appendChild(canvasWrap)

  const canvas = document.createElement('canvas')
  canvas.style.cssText = 'display:block;width:100%;height:100%;'
  canvasWrap.appendChild(canvas)

  const tooltip = document.createElement('div')
  tooltip.style.cssText = [
    'position:absolute;display:none;pointer-events:none;z-index:10;',
    `background:rgba(255,255,255,0.98);border:1px solid ${COLOR.borderLight};border-radius:8px;`,
    'padding:10px 14px;font-size:11px;box-shadow:0 4px 15px rgba(0,0,0,0.08);',
    'min-width:120px;line-height:1.5;'
  ].join('')
  canvasWrap.appendChild(tooltip)

  const overlay = document.createElement('div')
  overlay.style.cssText = 'position:absolute;top:55%;left:50%;transform:translate(-50%,-50%);color:rgba(0,0,0,0.2);font-size:12px;pointer-events:none;'
  overlay.textContent = '거래 내역이 없습니다'
  canvasWrap.appendChild(overlay)

  container.appendChild(wrapper)

  const ctx = canvas.getContext('2d')
  let hitIdx: number | null = null
  let barRects: { x: number; w: number; row: DisplayRow }[] = []
  let cw = 0, ch = 0

  refreshInternal(options.data)

  function render() {
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    cw = canvasWrap.clientWidth
    ch = canvasWrap.clientHeight
    canvas.width = cw * dpr
    canvas.height = ch * dpr
    canvas.style.width = cw + 'px'
    canvas.style.height = ch + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    overlay.style.display = isSample ? '' : 'none'

    const plotL = PADDING.left
    const plotR = cw - PADDING.right
    const plotT = PADDING.top
    const plotB = ch - PADDING.bottom
    const plotW = plotR - plotL
    const plotH = plotB - plotT

    if (plotW <= 0 || plotH <= 0 || displayData.length === 0) {
      barRects = []
      if (hitIdx !== null) {
        hitIdx = null
        tooltip.style.display = 'none'
      }
      return
    }

    // ── 축 범위 계산 ────────────────────────────────────────
    let minPnl = 0, maxPnl = 0
    let minCum = 0, maxCum = 0
    for (const d of displayData) {
      if (d.pnl !== null) {
        minPnl = Math.min(minPnl, d.pnl)
        maxPnl = Math.max(maxPnl, d.pnl)
      }
      minCum = Math.min(minCum, d.cumulative)
      maxCum = Math.max(maxCum, d.cumulative)
    }
    
    const pnlPad = (maxPnl - minPnl) * 0.15 || 10000
    const cumPad = (maxCum - minCum) * 0.15 || 10000
    
    // Y축 눈금 계산 (PnL 기준)
    const pTicks = computeYTicks(minPnl - pnlPad, maxPnl + pnlPad)
    const yPnlMin = pTicks[0], yPnlMax = pTicks[pTicks.length - 1]
    
    // Y축 눈금 계산 (Cumulative 기준)
    const cTicks = computeYTicks(minCum - cumPad, maxCum + cumPad)
    const yCumMin = cTicks[0], yCumMax = cTicks[cTicks.length - 1]

    const pToY = (v: number) => plotT + (1 - (v - yPnlMin) / (yPnlMax - yPnlMin || 1)) * plotH
    const cToY = (v: number) => plotT + (1 - (v - yCumMin) / (yCumMax - yCumMin || 1)) * plotH

    ctx.clearRect(0, 0, cw, ch)

    // ── 그리드 & 축 ─────────────────────────────────────────
    ctx.strokeStyle = COLORS.grid
    ctx.lineWidth = 1
    ctx.beginPath()
    pTicks.forEach(v => {
      const y = pToY(v)
      ctx.moveTo(plotL, y)
      ctx.lineTo(plotR, y)
    })
    ctx.stroke()

    const zeroY = pToY(0)
    ctx.strokeStyle = COLORS.zeroLine
    ctx.beginPath()
    ctx.moveTo(plotL, zeroY)
    ctx.lineTo(plotR, zeroY)
    ctx.stroke()

    // ── 막대 그리기 (Daily) ──────────────────────────────────
    const n = displayData.length
    const barW_total = plotW / n
    const barW = barW_total * (1 - BAR_GAP_RATIO)
    const barOff = (barW_total - barW) / 2
    
    barRects = []
    displayData.forEach((d, i) => {
      const x = plotL + i * barW_total + barOff
      barRects.push({ x, w: barW, row: d })

      if (d.pnl === null) return
      
      const isPos = d.pnl >= 0
      const bTop = isPos ? pToY(d.pnl) : pToY(0)
      const bBottom = isPos ? pToY(0) : pToY(d.pnl)
      const bH = Math.max(Math.abs(bBottom - bTop), 2)
      
      const grad = ctx.createLinearGradient(x, bTop, x, bBottom)
      const colors = mode === 'volume' ? COLORS.volume : (isPos ? COLORS.profit : COLORS.loss)
      grad.addColorStop(0, colors[0])
      grad.addColorStop(1, colors[1])
      
      ctx.fillStyle = grad
      drawRoundedRect(ctx, x, bTop, barW, bH, BAR_RADIUS, isPos)
    })

    // ── 누적 라인 (Equity) ───────────────────────────────────
    if (n > 1) {
      ctx.beginPath()
      ctx.strokeStyle = COLORS.equity
      ctx.lineWidth = 3
      ctx.lineJoin = 'round'
      ctx.shadowBlur = 4
      ctx.shadowColor = 'rgba(0,0,0,0.1)'
      
      const getPoint = (i: number) => ({
        x: plotL + i * barW_total + barW_total / 2,
        y: cToY(displayData[i].cumulative)
      })

      const p0 = getPoint(0)
      ctx.moveTo(p0.x, p0.y)
      
      for (let i = 0; i < n - 1; i++) {
        const curr = getPoint(i)
        const next = getPoint(i + 1)
        const mx = (curr.x + next.x) / 2
        ctx.bezierCurveTo(mx, curr.y, mx, next.y, next.x, next.y)
      }
      ctx.stroke()
      ctx.shadowBlur = 0

      // 라인 하단 채우기 (pnl 모드만 — volume 모드는 일별 수익률이므로 영역 채우기 생략)
      if (mode === 'pnl') {
        ctx.lineTo(plotR - barW_total / 2, plotB)
        ctx.lineTo(plotL + barW_total / 2, plotB)
        ctx.fillStyle = COLORS.equityArea
        ctx.fill()
      }
    }

    // ── 축 텍스트 ───────────────────────────────────────────
    ctx.font = `10px ${FONT_FAMILY}`
    ctx.fillStyle = COLORS.axis
    
    // Y축 Left (Daily / Volume)
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    const leftFmt = mode === 'volume' ? formatCount : formatAmountWon
    pTicks.forEach(v => {
      ctx.fillText(leftFmt(v), plotL - 8, pToY(v))
    })

    // Y축 Right (Equity / Rate)
    ctx.textAlign = 'left'
    const rightFmt = mode === 'volume' ? formatPercent : formatAmountWon
    cTicks.forEach(v => {
      ctx.fillText(rightFmt(v), plotR + 8, cToY(v))
    })

    // X축 (MM/DD)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    const labelStep = Math.max(1, Math.ceil(n / 6))
    for (let i = 0; i < n; i += labelStep) {
      const d = displayData[i]
      const cx = plotL + i * barW_total + barW_total / 2
      ctx.fillText(formatDate(d.date), cx, plotB + 8)
    }

    // ── 하이라이트 & 크로스헤어 ───────────────────────────────
    if (hitIdx !== null) {
      const br = barRects[hitIdx]
      ctx.fillStyle = COLORS.crosshair
      ctx.fillRect(br.x - barOff, plotT, barW_total, plotH)
      
      const point = {
        x: br.x + br.w / 2,
        y: cToY(displayData[hitIdx].cumulative)
      }
      ctx.beginPath()
      ctx.arc(point.x, point.y, 4, 0, Math.PI * 2)
      ctx.fillStyle = COLORS.equity
      ctx.fill()
      ctx.strokeStyle = COLOR.white
      ctx.lineWidth = 2
      ctx.stroke()
    }
  }

  function drawRoundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number, isPos: boolean) {
    if (h < 1) return
    ctx.beginPath()
    if (isPos) {
      ctx.moveTo(x, y + h); ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r); ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r); ctx.lineTo(x + w, y + h); ctx.closePath()
    } else {
      ctx.moveTo(x, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + h - r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r); ctx.lineTo(x + r, y + h); ctx.arcTo(x, y + h, x, y + h - r, r); ctx.lineTo(x, y); ctx.closePath()
    }
    ctx.fill()
  }

  function onMove(e: MouseEvent) {
    const r = canvas.getBoundingClientRect()
    const mx = e.clientX - r.left
    const my = e.clientY - r.top
    
    let newHit: number | null = null
    for (let i = 0; i < barRects.length; i++) {
      const br = barRects[i]
      if (mx >= br.x - 2 && mx <= br.x + br.w + 2) {
        newHit = i
        break
      }
    }

    if (newHit !== hitIdx) {
      hitIdx = newHit
      render()
      if (hitIdx !== null) {
        const d = displayData[hitIdx]
        const pColor = pnlColor(d.pnl || 0)
        const rColor = pnlColor(d.rate)
        tooltip.style.display = 'block'
        const barLabel = mode === 'volume' ? '거래 건수:' : '일별 손익:'
        const barValue = mode === 'volume'
          ? `${d.pnl || 0}건`
          : `${(d.pnl || 0) >= 0 ? '+' : ''}${fmtWon(d.pnl || 0)}`
        const lineLabel = mode === 'volume' ? '수익률:' : '일별 수익률:'
        const lineValue = `${d.rate.toFixed(2)}%`
        const feeTotal = (d.buyFee ?? 0) + (d.sellFee ?? 0) + (d.tax ?? 0)
        tooltip.innerHTML = `
          <div style="font-weight:600;margin-bottom:6px;border-bottom:1px solid ${COLOR.borderLight};padding-bottom:4px;">${formatDate(d.date)}</div>
          <div style="display:flex;justify-content:space-between;gap:12px;">
            <span style="color:${COLOR.tertiary}">${barLabel}</span>
            <span style="color:${pColor};font-weight:600">${barValue}</span>
          </div>
          <div style="display:flex;justify-content:space-between;gap:12px;">
            <span style="color:${COLOR.tertiary}">${lineLabel}</span>
            <span style="color:${rColor};font-weight:600">${lineValue}</span>
          </div>
          ${feeTotal > 0 ? `<div style="display:flex;justify-content:space-between;gap:12px;border-top:1px solid ${COLOR.borderLight};margin-top:4px;padding-top:4px;"><span style="color:${COLOR.tertiary}">수수료/세금</span><span style="color:${COLOR.neutral};font-weight:600">${fmtWon(feeTotal)}</span></div>` : ''}
        `
        positionTooltip(tooltip, mx, my, cw, ch)
      } else {
        tooltip.style.display = 'none'
      }
    }
  }

  canvas.addEventListener('mousemove', onMove)
  canvas.addEventListener('mouseleave', () => { hitIdx = null; render(); tooltip.style.display = 'none' })

  const RO = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => render()) : null
  if (RO) RO.observe(canvasWrap)

  render()

  return {
    el: wrapper,
    updateData: (newData: ProfitChartRow[]) => {
      refreshInternal(newData)
      render()
    },
    resize() { render() },
    destroy: () => {
      if (RO) RO.disconnect()
      canvas.removeEventListener('mousemove', onMove)
      wrapper.remove()
    },
    setDateRange(from: string, to: string, label?: string) {
      dateRangeInput.setValue(from, to)
      // label 지정 시 label 기반 매칭 ('직전' 등 from/to가 동적 조회되는 버튼용)
      if (label) {
        _activeQuickIdx = quickRanges.findIndex(qr => qr.label === label)
      } else {
        _activeQuickIdx = quickRanges.findIndex(qr => qr.from === from && qr.to === to)
      }
      updateQuickBtnActive()
    }
  }
}
