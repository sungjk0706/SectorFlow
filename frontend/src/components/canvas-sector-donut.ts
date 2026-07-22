/**
 * Canvas 2D API 기반 업종별 수익 도넛 차트
 * - 매도 체결 기록의 업종별 실현손익을 도넛 형태로 시각화
 * - 수익(빨강) / 손실(파랑) 색상 구분
 * - 인터랙티브: 호버 시 업종명 + 손익 금액 툴팁
 */

import { FONT_FAMILY, COLOR, fmtWon, positionTooltip, computeWeightedRate } from './common/ui-styles'

// ── 타입 ────────────────────────────────────────────────────

export interface SectorDonutRow {
  sector: string
  pnl: number
  rate?: number
  buyTotal?: number
}

export interface SectorDonutOptions {
  container: HTMLElement
  data: SectorDonutRow[]
  height?: number
  onSectorClick?: (sector: string) => void
}

export interface SectorDonutApi {
  el: HTMLElement
  updateData(data: SectorDonutRow[]): void
  resize(): void
  destroy(): void
}

// ── 상수 ────────────────────────────────────────────────────

const PADDING = 20

// 도넛 색상 팔레트 — 수익/손실 계열 (외부 재사용을 위해 export)
export const PROFIT_COLORS = [
  '#f44336', '#e91e63', '#9c27b0', '#673ab7', '#3f51b5',
  '#2196f3', '#00bcd4', '#009688', '#4caf50', '#8bc34a',
]
export const LOSS_COLORS = [
  '#1e88e5', '#03a9f4', '#00acc1', '#5c6bc0', '#7986cb',
  '#42a5f5', '#26c6da', '#66bb6a', '#9ccc65', '#80cbc4',
]

// ── 색상 할당 공유 함수 ────────────────────────────────────
// 도넛 차트와 종목 리스트가 동일한 색상 매핑을 사용하도록 분리
// 입력: 절대값 내림차순 정렬된 SectorDonutRow[]
// 출력: sector → color 맵
export function assignSectorColors(rows: SectorDonutRow[]): Map<string, string> {
  const colorMap = new Map<string, string>()
  let profitIdx = 0
  let lossIdx = 0
  for (const r of rows) {
    const isProfit = r.pnl >= 0
    const palette = isProfit ? PROFIT_COLORS : LOSS_COLORS
    const color = palette[isProfit ? profitIdx++ : lossIdx++ % palette.length]
    colorMap.set(r.sector, color)
  }
  return colorMap
}

// ── 메인 팩토리 ──────────────────────────────────────────────

export function createSectorDonut(options: SectorDonutOptions): SectorDonutApi {
  const { container } = options

  let data: SectorDonutRow[] = []
  let hoveredIdx: number | null = null
  const onSectorClick = options.onSectorClick

  // ── DOM 구조 ──────────────────────────────────────────────
  const wrapper = document.createElement('div')
  wrapper.style.cssText = 'position:relative;width:100%;height:100%;display:flex;gap:8px;'

  const canvasWrap = document.createElement('div')
  canvasWrap.style.cssText = `position:relative;flex:1;min-width:0;height:100%;background:${COLOR.white};overflow:hidden;`
  wrapper.appendChild(canvasWrap)

  const legendWrap = document.createElement('div')
  legendWrap.style.cssText = 'flex:none;width:auto;max-width:45%;height:100%;overflow-y:auto;padding:4px 0;'
  wrapper.appendChild(legendWrap)

  const canvas = document.createElement('canvas')
  canvas.style.cssText = 'display:block;width:100%;height:100%;'
  canvasWrap.appendChild(canvas)

  const tooltip = document.createElement('div')
  tooltip.style.cssText = [
    'position:absolute;display:none;pointer-events:none;z-index:10;',
    `background:rgba(255,255,255,0.98);border:1px solid ${COLOR.borderLight};border-radius:8px;`,
    'padding:10px 14px;font-size:11px;box-shadow:0 4px 15px rgba(0,0,0,0.08);',
    'min-width:120px;line-height:1.5;',
  ].join('')
  canvasWrap.appendChild(tooltip)

  const overlay = document.createElement('div')
  overlay.style.cssText = 'position:absolute;top:55%;left:50%;transform:translate(-50%,-50%);color:rgba(0,0,0,0.2);font-size:12px;pointer-events:none;'
  overlay.textContent = '매도 체결 내역이 없습니다'
  canvasWrap.appendChild(overlay)

  container.appendChild(wrapper)

  const ctx = canvas.getContext('2d')
  let cw = 0, ch = 0
  let segmentRects: { startAngle: number; endAngle: number; row: SectorDonutRow; color: string }[] = []
  let currentSegments: { row: SectorDonutRow; color: string }[] = []

  // ── 데이터 처리 ──────────────────────────────────────────
  function processData(rows: SectorDonutRow[]): SectorDonutRow[] {
    // 업종별 집계 (이미 집계된 데이터라고 가정, 중복 병합)
    const pnlMap = new Map<string, number>()
    const buyTotalMap = new Map<string, number>()
    for (const r of rows) {
      pnlMap.set(r.sector, (pnlMap.get(r.sector) ?? 0) + r.pnl)
      buyTotalMap.set(r.sector, (buyTotalMap.get(r.sector) ?? 0) + (r.buyTotal ?? 0))
    }
    // 절대값 기준 내림차순 정렬
    return Array.from(pnlMap.entries())
      .map(([sector, pnl]) => ({ sector, pnl, buyTotal: buyTotalMap.get(sector) ?? 0 }))
      .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
  }

  // ── 렌더 ──────────────────────────────────────────────────
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

    ctx.clearRect(0, 0, cw, ch)

    const processed = processData(data)
    const hasData = processed.length > 0 && processed.some(r => r.pnl !== 0)

    overlay.style.display = hasData ? 'none' : ''

    if (!hasData) {
      currentSegments = []
      segmentRects = []
      return
    }

    const cx = cw / 2
    const cy = ch / 2
    const outerR = Math.min(cw, ch) / 2 - PADDING
    const innerR = outerR * 0.55

    // 전체 절대값 합
    const totalAbs = processed.reduce((s, r) => s + Math.abs(r.pnl), 0)
    if (totalAbs === 0) {
      currentSegments = []
      segmentRects = []
      return
    }

    // 세그먼트 색상 할당 (공유 함수 사용)
    const colorMap = assignSectorColors(processed)
    const segments = processed.map((r) => ({ row: r, color: colorMap.get(r.sector) ?? COLOR.disabled }))
    currentSegments = segments

    // 도넛 세그먼트 그리기
    let startAngle = -Math.PI / 2
    segmentRects = []

    for (const seg of segments) {
      const angle = (Math.abs(seg.row.pnl) / totalAbs) * Math.PI * 2
      const endAngle = startAngle + angle

      ctx.beginPath()
      ctx.arc(cx, cy, outerR, startAngle, endAngle)
      ctx.arc(cx, cy, innerR, endAngle, startAngle, true)
      ctx.closePath()
      ctx.fillStyle = seg.color
      ctx.fill()

      segmentRects.push({ startAngle, endAngle, row: seg.row, color: seg.color })

      startAngle = endAngle
    }

    // 호버 하이라이트
    if (hoveredIdx !== null && segmentRects[hoveredIdx]) {
      const seg = segmentRects[hoveredIdx]
      ctx.beginPath()
      ctx.arc(cx, cy, outerR + 4, seg.startAngle, seg.endAngle)
      ctx.arc(cx, cy, innerR - 4, seg.endAngle, seg.startAngle, true)
      ctx.closePath()
      ctx.strokeStyle = seg.color
      ctx.lineWidth = 2
      ctx.stroke()
    }

    // 중액 텍스트 — 누적 손익 + 누적 수익률
    const totalPnl = processed.reduce((s, r) => s + r.pnl, 0)
    const totalBuy = processed.reduce((s, r) => s + (r.buyTotal ?? 0), 0)
    const totalRate = computeWeightedRate(totalPnl, totalBuy)
    ctx.fillStyle = totalPnl >= 0 ? COLOR.up : COLOR.down
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.font = `bold 14px ${FONT_FAMILY}`
    ctx.fillText('누적 손익', cx, cy - 18)
    ctx.font = `bold 16px ${FONT_FAMILY}`
    ctx.fillText(fmtWon(totalPnl), cx, cy + 2)
    ctx.font = `bold 12px ${FONT_FAMILY}`
    const rateSign = totalRate >= 0 ? '+' : ''
    ctx.fillText(`${rateSign}${totalRate.toFixed(2)}%`, cx, cy + 22)

  }

  // ── DOM 범례 렌더 ────────────────────────────────────────
  function renderLegend() {
    legendWrap.innerHTML = ''
    if (currentSegments.length === 0) return
    for (let i = 0; i < currentSegments.length; i++) {
      const seg = currentSegments[i]
      const isProfit = seg.row.pnl >= 0
      const item = document.createElement('div')
      item.style.cssText = `display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-radius:4px;${hoveredIdx === i ? `background:${COLOR.hoverBg};` : ''}`
      const dot = document.createElement('span')
      dot.style.cssText = `flex:none;width:8px;height:8px;border-radius:50%;background:${seg.color};`
      const label = document.createElement('span')
      label.style.cssText = 'flex:1;min-width:0;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
      label.textContent = seg.row.sector
      const val = document.createElement('span')
      val.style.cssText = `flex:none;font-size:11px;font-weight:600;color:${isProfit ? COLOR.up : COLOR.down};`
      val.textContent = `${seg.row.pnl >= 0 ? '+' : ''}${fmtWon(seg.row.pnl)}`
      item.appendChild(dot)
      item.appendChild(label)
      item.appendChild(val)
      if (seg.row.rate !== undefined) {
        const rateEl = document.createElement('span')
        rateEl.style.cssText = `flex:none;font-size:10px;color:${isProfit ? COLOR.up : COLOR.down};opacity:0.8;`
        const rateSign = seg.row.rate >= 0 ? '+' : ''
        rateEl.textContent = `${rateSign}${seg.row.rate.toFixed(2)}%`
        item.appendChild(rateEl)
      }
      item.addEventListener('mouseenter', () => {
        hoveredIdx = i
        render()
        renderLegendHighlight()
      })
      item.addEventListener('mouseleave', () => {
        hoveredIdx = null
        render()
        renderLegendHighlight()
      })
      if (onSectorClick) {
        item.addEventListener('click', () => {
          onSectorClick(seg.row.sector)
        })
      }
      legendWrap.appendChild(item)
    }
  }

  function renderLegendHighlight() {
    const items = legendWrap.children
    for (let i = 0; i < items.length; i++) {
      ;(items[i] as HTMLElement).style.background = hoveredIdx === i ? COLOR.hoverBg : ''
    }
  }

  // ── 호버 처리 ──────────────────────────────────────────────
  function onMove(e: MouseEvent) {
    const r = canvas.getBoundingClientRect()
    const mx = e.clientX - r.left
    const my = e.clientY - r.top

    const cx = cw / 2
    const cy = ch / 2
    const dx = mx - cx
    const dy = my - cy
    const dist = Math.sqrt(dx * dx + dy * dy)
    const outerR = Math.min(cw, ch) / 2 - PADDING
    const innerR = outerR * 0.55

    let newHit: number | null = null

    if (dist >= innerR && dist <= outerR + 6) {
      let angle = Math.atan2(dy, dx)
      if (angle < -Math.PI / 2) angle += Math.PI * 2

      for (let i = 0; i < segmentRects.length; i++) {
        const seg = segmentRects[i]
        if (angle >= seg.startAngle && angle < seg.endAngle) {
          newHit = i
          break
        }
      }
    }

    if (newHit !== hoveredIdx) {
      hoveredIdx = newHit
      render()
      renderLegendHighlight()
      if (hoveredIdx !== null) {
        const seg = segmentRects[hoveredIdx]
        const isProfit = seg.row.pnl >= 0
        tooltip.style.display = 'block'
        tooltip.innerHTML = `
          <div style="font-weight:600;margin-bottom:6px;border-bottom:1px solid ${COLOR.borderLight};padding-bottom:4px;">${seg.row.sector}</div>
          <div style="display:flex;justify-content:space-between;gap:12px;">
            <span style="color:${COLOR.tertiary}">실현손익</span>
            <span style="color:${isProfit ? COLOR.up : COLOR.down};font-weight:600">${seg.row.pnl >= 0 ? '+' : ''}${fmtWon(seg.row.pnl)}</span>
          </div>
          ${seg.row.rate !== undefined ? `<div style="display:flex;justify-content:space-between;gap:12px;"><span style="color:${COLOR.tertiary}">수익률</span><span style="color:${isProfit ? COLOR.up : COLOR.down};font-weight:600">${seg.row.rate >= 0 ? '+' : ''}${seg.row.rate.toFixed(2)}%</span></div>` : ''}
        `
        positionTooltip(tooltip, mx, my, cw, ch)
      } else {
        tooltip.style.display = 'none'
      }
    }
  }

  canvas.addEventListener('mousemove', onMove)
  canvas.addEventListener('mouseleave', () => { hoveredIdx = null; render(); renderLegendHighlight(); tooltip.style.display = 'none' })

  const RO = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => render()) : null
  if (RO) RO.observe(canvasWrap)

  // 초기 렌더
  data = options.data
  render()
  renderLegend()

  return {
    el: wrapper,
    updateData(newData: SectorDonutRow[]) {
      data = newData
      render()
      renderLegend()
    },
    resize() { render() },
    destroy() {
      if (RO) RO.disconnect()
      canvas.removeEventListener('mousemove', onMove)
      wrapper.remove()
    },
  }
}
