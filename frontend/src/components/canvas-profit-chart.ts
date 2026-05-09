/**
 * Canvas 2D API 기반 프리미엄 수익 현황 차트
 * - 막대: 일별 실현손익 (Daily PnL)
 * - 라인: 누적 실현손익 (Cumulative PnL / Equity Curve)
 * - 인터랙티브: 크로스헤어, 툴팁, 막대 클릭 필터링
 */

import { pnlColor, FONT_FAMILY } from './common/ui-styles'

// ── 타입 ────────────────────────────────────────────────────

export interface ProfitChartRow {
  date: string
  pnl: number | null
  rate: number
}

// 내부에서 누적 합계가 포함된 확장 타입
interface DisplayRow extends ProfitChartRow {
  cumulative: number
}

export interface ProfitChartOptions {
  container: HTMLElement
  data: ProfitChartRow[]
  maxBars?: number
  onBarClick?: (date: string) => void
  onDateRangeChange?: (from: string, to: string) => void
  dateFrom?: string
  dateTo?: string
}

export interface ProfitChartApi {
  el: HTMLElement
  updateData(data: ProfitChartRow[]): void
  resize(): void
  destroy(): void
  setDateRange(from: string, to: string): void
}

// ── 상수 ───────────────────────────────────────────────

const CHART_HEIGHT = 220
const PADDING = { top: 20, right: 48, bottom: 30, left: 48 }
const BAR_RADIUS = 3
const BAR_GAP_RATIO = 0.3
const COLORS = {
  profit: ['#ef4444', '#f87171'], // Red -> Light Red (수익: 빨강)
  loss: ['#3b82f6', '#60a5fa'],   // Blue -> Light Blue (손실: 파랑)
  equity: '#1976d2',               // Blue for Equity Curve
  equityArea: 'rgba(25, 118, 210, 0.08)',
  grid: '#f0f0f0',
  axis: '#888',
  zeroLine: '#ddd',
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
  const { container, maxBars = 30 } = options
  
  let isSample = false
  let displayData: DisplayRow[] = []

  // ── 데이터 처리 (누적 합계 계산) ──────────────────────────
  function processData(rows: ProfitChartRow[]): DisplayRow[] {
    let cumulative = 0
    return rows.map(r => {
      cumulative += (r.pnl || 0)
      return { ...r, cumulative }
    })
  }

  // 데이터 갱신 로직 (초기화 및 updateData 공용)
  function refreshInternal(newData: ProfitChartRow[]) {
    const dataSlice = newData.slice(-maxBars)
    const hasVisibleBar = dataSlice.some(d => d.pnl !== null && d.pnl !== 0)
    isSample = dataSlice.length === 0 || !hasVisibleBar
    
    if (isSample) {
      displayData = processData(generateDummyData())
    } else {
      displayData = processData(dataSlice)
    }
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

  const dateFromInput = document.createElement('input')
  dateFromInput.type = 'date'
  dateFromInput.value = options.dateFrom || monthFirstStr
  dateFromInput.style.cssText = 'padding:2px 4px;font-size:11px;border:1px solid #eee;border-radius:4px;color:#555;'

  const dateToInput = document.createElement('input')
  dateToInput.type = 'date'
  dateToInput.value = options.dateTo || todayStr
  dateToInput.style.cssText = 'padding:2px 4px;font-size:11px;border:1px solid #eee;border-radius:4px;color:#555;'

  const dateSep = document.createElement('span')
  dateSep.textContent = '~'
  dateSep.style.color = '#ccc'

  dateHeader.appendChild(dateFromInput)
  dateHeader.appendChild(dateSep)
  dateHeader.appendChild(dateToInput)
  wrapper.appendChild(dateHeader)

  dateFromInput.addEventListener('change', () => options.onDateRangeChange?.(dateFromInput.value, dateToInput.value))
  dateToInput.addEventListener('change', () => options.onDateRangeChange?.(dateToInput.value, dateToInput.value))

  const canvasWrap = document.createElement('div')
  canvasWrap.style.cssText = `position:relative;width:100%;height:${CHART_HEIGHT}px;background:#fff;overflow:hidden;`
  wrapper.appendChild(canvasWrap)

  const canvas = document.createElement('canvas')
  canvas.style.cssText = 'display:block;width:100%;height:100%;'
  canvasWrap.appendChild(canvas)

  const tooltip = document.createElement('div')
  tooltip.style.cssText = [
    'position:absolute;display:none;pointer-events:none;z-index:10;',
    'background:rgba(255,255,255,0.98);border:1px solid #eee;border-radius:8px;',
    'padding:10px 14px;font-size:11px;box-shadow:0 4px 15px rgba(0,0,0,0.08);',
    'min-width:120px;line-height:1.5;'
  ].join('')
  canvasWrap.appendChild(tooltip)

  const overlay = document.createElement('div')
  overlay.style.cssText = 'position:absolute;top:55%;left:50%;transform:translate(-50%,-50%);color:rgba(0,0,0,0.2);font-size:12px;pointer-events:none;'
  overlay.textContent = '거래 내역이 없습니다 (샘플 데이터)'
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

    if (plotW <= 0 || plotH <= 0 || displayData.length === 0) return

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
      const colors = isPos ? COLORS.profit : COLORS.loss
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

      // 라인 하단 채우기
      ctx.lineTo(plotR - barW_total / 2, plotB)
      ctx.lineTo(plotL + barW_total / 2, plotB)
      ctx.fillStyle = COLORS.equityArea
      ctx.fill()
    }

    // ── 축 텍스트 ───────────────────────────────────────────
    ctx.font = `10px ${FONT_FAMILY}`
    ctx.fillStyle = COLORS.axis
    
    // Y축 Left (Daily)
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    pTicks.forEach(v => {
      ctx.fillText(formatAmountWon(v), plotL - 8, pToY(v))
    })

    // Y축 Right (Equity)
    ctx.textAlign = 'left'
    cTicks.forEach(v => {
      ctx.fillText(formatAmountWon(v), plotR + 8, cToY(v))
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
      ctx.strokeStyle = '#fff'
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
        tooltip.innerHTML = `
          <div style="font-weight:600;margin-bottom:6px;border-bottom:1px solid #eee;padding-bottom:4px;">${formatDate(d.date)}</div>
          <div style="display:flex;justify-content:space-between;gap:12px;">
            <span style="color:#666">일별 손익:</span>
            <span style="color:${pColor};font-weight:600">${(d.pnl || 0).toLocaleString()}원</span>
          </div>
          <div style="display:flex;justify-content:space-between;gap:12px;">
            <span style="color:#666">일별 수익률:</span>
            <span style="color:${rColor};font-weight:600">${d.rate.toFixed(2)}%</span>
          </div>
        `
        const tw = tooltip.offsetWidth
        let tx = mx + 15
        if (tx + tw > cw) tx = mx - tw - 15
        tooltip.style.left = `${tx}px`
        tooltip.style.top = `${Math.max(10, my - 40)}px`
      } else {
        tooltip.style.display = 'none'
      }
    }
  }

  canvas.addEventListener('mousemove', onMove)
  canvas.addEventListener('mouseleave', () => { hitIdx = null; render(); tooltip.style.display = 'none' })
  canvas.addEventListener('click', () => {
    if (hitIdx !== null && displayData[hitIdx].pnl !== null) {
      options.onBarClick?.(displayData[hitIdx].date)
    }
  })

  function generateDummyData(): ProfitChartRow[] {
    const rows: ProfitChartRow[] = []
    const now = new Date()
    let trend = 0
    for (let i = 0; i < 20; i++) {
      const d = new Date(now)
      d.setDate(d.getDate() - (19 - i))
      const pnl = Math.round((Math.random() - 0.35) * 1200000 + trend)
      trend += 20000
      rows.push({
        date: d.toISOString().slice(0, 10),
        pnl,
        rate: +(Math.random() * 4).toFixed(2)
      })
    }
    return rows
  }

  const RO = (window as any).ResizeObserver ? new (window as any).ResizeObserver(() => render()) : null
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
    setDateRange(from: string, to: string) {
      dateFromInput.value = from
      dateToInput.value = to
    }
  }
}
