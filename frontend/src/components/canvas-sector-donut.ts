/**
 * Canvas 2D API 기반 업종별 수익 도넛 차트
 * - 매도 체결 기록의 업종별 실현손익을 도넛 형태로 시각화
 * - 수익(빨강) / 손실(파랑) 색상 구분
 * - 인터랙티브: 호버 시 업종명 + 손익 금액 툴팁
 */

import { FONT_FAMILY, COLOR, RADIUS, SHADOW, BLUR, SURFACE_ALPHA, fmtWon, positionTooltip } from './common/ui-styles'

// ── 타입 ────────────────────────────────────────────────────

export interface SectorDonutRow {
  sector: string
  pnl: number
}

export interface SectorDonutCenter {
  pnl?: number            // 중앙 손익금 (외부 주입 — SSOT, 미지정 시 data 합산)
  rate?: number | null    // 중앙 수익률 (외부 주입 — SSOT, null/미지정 시 미표시)
  title?: string          // 중앙 레이블 (예: "당월 손익", 미지정 시 "누적 손익")
}

interface SectorDonutOptions {
  container: HTMLElement
  data: SectorDonutRow[]
  height?: number
  onSectorClick?: (sector: string) => void
  center?: SectorDonutCenter
}

export interface SectorDonutApi {
  el: HTMLElement
  updateData(data: SectorDonutRow[], center?: SectorDonutCenter): void
  resize(): void
  destroy(): void
}

// ── 상수 ────────────────────────────────────────────────────

const PADDING = 20

// 도넛 색상 팔레트 — 수익/손실 계열 (외부 재사용을 위해 export)
const PROFIT_COLORS = [
  '#f44336', '#e91e63', '#9c27b0', '#673ab7', '#3f51b5',
  '#2196f3', '#00bcd4', '#009688', '#4caf50', '#8bc34a',
]
const LOSS_COLORS = [
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
  let center: SectorDonutCenter | undefined
  let hoveredIdx: number | null = null
  const onSectorClick = options.onSectorClick

  // ── DOM 구조 ──────────────────────────────────────────────
  const wrapper = document.createElement('div')
  wrapper.style.cssText = 'position:relative;width:100%;height:100%;display:flex;gap:8px;'

  const canvasWrap = document.createElement('div')
  canvasWrap.style.cssText = `position:relative;flex:1;min-width:0;height:100%;background:${COLOR.white};overflow:hidden;`
  wrapper.appendChild(canvasWrap)

  // 범례 폭 고정 — 가변 폭(width:auto) 시 업종명 길이에 따라 도넛 캔버스 폭이 변동하여
  // 도넛 위치·크기가 흔들리는 문제 방지 (P24 단순성 — 근본 원인에 대한 최소 수정).
  const legendWrap = document.createElement('div')
  legendWrap.style.cssText = 'flex:0 0 38%;height:100%;overflow-y:auto;padding:4px 0;'
  wrapper.appendChild(legendWrap)

  const canvas = document.createElement('canvas')
  canvas.style.cssText = 'display:block;width:100%;height:100%;'
  canvasWrap.appendChild(canvas)

  const tooltip = document.createElement('div')
  tooltip.style.cssText = [
    'position:absolute;display:none;pointer-events:none;z-index:10;',
    `background:${SURFACE_ALPHA.panel};backdrop-filter:${BLUR.panel};-webkit-backdrop-filter:${BLUR.panel};`,
    `border:1px solid ${COLOR.borderLight};border-radius:${RADIUS.md};`,
    `padding:10px 14px;font-size:11px;box-shadow:${SHADOW.popup};`,
    'min-width:120px;line-height:1.5;',
  ].join('')
  canvasWrap.appendChild(tooltip)

  // 툴팁 내부 요소 — 미리 생성해두고 마우스 이동 시 글자만 갱신 (M-05: innerHTML 매번 조립 제거)
  const ttSector = document.createElement('div')
  Object.assign(ttSector.style, { fontWeight: '600', marginBottom: '6px', borderBottom: `1px solid ${COLOR.borderLight}`, paddingBottom: '4px' })
  tooltip.appendChild(ttSector)
  const ttPnlRow = document.createElement('div')
  Object.assign(ttPnlRow.style, { display: 'flex', justifyContent: 'space-between', gap: '12px' })
  const ttPnlLabel = document.createElement('span')
  Object.assign(ttPnlLabel.style, { color: COLOR.tertiary })
  ttPnlLabel.textContent = '실현손익'
  const ttPnlValue = document.createElement('span')
  Object.assign(ttPnlValue.style, { fontWeight: '600' })
  ttPnlRow.appendChild(ttPnlLabel)
  ttPnlRow.appendChild(ttPnlValue)
  tooltip.appendChild(ttPnlRow)

  const overlay = document.createElement('div')
  overlay.style.cssText = 'position:absolute;top:55%;left:50%;transform:translate(-50%,-50%);color:rgba(0,0,0,0.2);font-size:12px;pointer-events:none;'
  overlay.textContent = '매도 체결 내역이 없습니다'
  canvasWrap.appendChild(overlay)

  container.appendChild(wrapper)

  const ctx = canvas.getContext('2d')
  let cw = 0, ch = 0
  let segmentRects: { startAngle: number; endAngle: number; row: SectorDonutRow; color: string }[] = []
  let currentSegments: { row: SectorDonutRow; color: string }[] = []
  // H-02: 마우스 이동 시 rAF 배칭 — 1프레임에 1회만 재그리기 (중복 예약 방지)
  let rafId: number | null = null
  // M-03: 범례 key diff — 업종명 키로 기존 범례 항목 요소 맵 유지 (전체 재생성 방지)
  const legendItemMap = new Map<string, HTMLDivElement>()

  // ── 데이터 처리 ──────────────────────────────────────────
  function processData(rows: SectorDonutRow[]): SectorDonutRow[] {
    // 업종별 집계 (이미 집계된 데이터라고 가정, 중복 병합)
    const pnlMap = new Map<string, number>()
    for (const r of rows) {
      pnlMap.set(r.sector, (pnlMap.get(r.sector) ?? 0) + r.pnl)
    }
    // 절대값 기준 내림차순 정렬
    return Array.from(pnlMap.entries())
      .map(([sector, pnl]) => ({ sector, pnl }))
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

    // 중앙 텍스트 — 손익 금액 + 수익률 (기초자산 분모 SSOT — computeCumulativePnl과 동일 소스, P10/P22).
    // rate null/미지정 시 손익 금액만 표시 (P20 폴백 금지).
    const sumPnl = processed.reduce((s, r) => s + r.pnl, 0)
    const totalPnl = center?.pnl ?? sumPnl
    const centerTitle = center?.title ?? '누적 손익'
    const centerRate = center?.rate
    ctx.fillStyle = totalPnl >= 0 ? COLOR.up : COLOR.down
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.font = `bold 14px ${FONT_FAMILY}`
    ctx.fillText(centerTitle, cx, cy - 18)
    ctx.font = `bold 16px ${FONT_FAMILY}`
    ctx.fillText(fmtWon(totalPnl), cx, cy + 2)
    if (centerRate !== undefined && centerRate !== null) {
      ctx.font = `bold 12px ${FONT_FAMILY}`
      ctx.fillText(`${centerRate >= 0 ? '+' : ''}${centerRate.toFixed(2)}%`, cx, cy + 22)
    }

  }

  // ── DOM 범례 렌더 ────────────────────────────────────────
  // M-03: key 기반 diff — 업종명 키로 기존 항목 재사용, 변경된 텍스트만 갱신.
  // 사라진 업종은 제거, 새 업종은 추가, 순서는 currentSegments 순서대로 재배치.
  function renderLegend() {
    if (currentSegments.length === 0) {
      // 전체 비움 — 기존 항목 모두 제거
      for (const [, item] of legendItemMap) item.remove()
      legendItemMap.clear()
      return
    }

    // 새 키 맵 — 현재 세그먼트 기준
    const newKeyMap = new Map<string, { seg: { row: SectorDonutRow; color: string }, index: number }>()
    for (let i = 0; i < currentSegments.length; i++) {
      newKeyMap.set(currentSegments[i].row.sector, { seg: currentSegments[i], index: i })
    }

    // 제거된 업종 항목 삭제
    for (const [sector, item] of legendItemMap) {
      if (!newKeyMap.has(sector)) {
        item.remove()
        legendItemMap.delete(sector)
      }
    }

    // 새 업종 항목 추가 + 기존 항목 갱신 + 순서 재배치
    for (let i = 0; i < currentSegments.length; i++) {
      const seg = currentSegments[i]
      const isProfit = seg.row.pnl >= 0
      let item = legendItemMap.get(seg.row.sector)
      if (!item) {
        // 신규 항목 생성
        item = document.createElement('div')
        const dot = document.createElement('span')
        dot.style.cssText = 'flex:none;width:8px;height:8px;border-radius:50%;'
        const label = document.createElement('span')
        label.style.cssText = 'flex:1;min-width:0;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
        const val = document.createElement('span')
        val.style.cssText = 'flex:none;font-size:11px;font-weight:600;'
        item.appendChild(dot)
        item.appendChild(label)
        item.appendChild(val)
        const idxCapture = i
        item.addEventListener('mouseenter', () => {
          hoveredIdx = idxCapture
          scheduleRender()
        })
        item.addEventListener('mouseleave', () => {
          hoveredIdx = null
          scheduleRender()
        })
        if (onSectorClick) {
          item.addEventListener('click', () => {
            onSectorClick(seg.row.sector)
          })
        }
        legendItemMap.set(seg.row.sector, item)
      }
      // 공통 스타일 + 내용 갱신 (기존·신규 모두)
      item.style.cssText = `display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-radius:${RADIUS.xs};${hoveredIdx === i ? `background:${COLOR.hoverBg};` : ''}`
      const dot = item.children[0] as HTMLElement
      dot.style.background = seg.color
      const label = item.children[1] as HTMLElement
      if (label.textContent !== seg.row.sector) label.textContent = seg.row.sector
      const val = item.children[2] as HTMLElement
      const newVal = `${seg.row.pnl >= 0 ? '+' : ''}${fmtWon(seg.row.pnl)}`
      if (val.textContent !== newVal) {
        val.textContent = newVal
        val.style.color = isProfit ? COLOR.up : COLOR.down
      }
      // 순서 재배치 — 현재 인덱스 순서대로 appendChild (이미 있으면 이동만)
      const refChild = legendWrap.children[i] as HTMLElement | undefined
      if (refChild !== item) {
        if (refChild) legendWrap.insertBefore(item, refChild)
        else legendWrap.appendChild(item)
      }
    }
  }

  function renderLegendHighlight() {
    const items = legendWrap.children
    for (let i = 0; i < items.length; i++) {
      ;(items[i] as HTMLElement).style.background = hoveredIdx === i ? COLOR.hoverBg : ''
    }
  }

  // H-02: rAF 배칭 — 도넛 재그리기 + 범례 하이라이트 갱신을 1프레임에 1회로 통합 (중복 예약 방지)
  function scheduleRender() {
    if (rafId !== null) return
    rafId = requestAnimationFrame(() => {
      rafId = null
      render()
      renderLegendHighlight()
    })
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
      scheduleRender()
      if (hoveredIdx !== null) {
        const seg = segmentRects[hoveredIdx]
        const isProfit = seg.row.pnl >= 0
        tooltip.style.display = 'block'
        // M-05: 미리 만들어둔 툴팁 요소의 글자만 갱신 (innerHTML 조립 제거)
        ttSector.textContent = seg.row.sector
        ttPnlValue.textContent = `${seg.row.pnl >= 0 ? '+' : ''}${fmtWon(seg.row.pnl)}`
        ttPnlValue.style.color = isProfit ? COLOR.up : COLOR.down
        positionTooltip(tooltip, mx, my, cw, ch)
      } else {
        tooltip.style.display = 'none'
      }
    }
  }

  canvas.addEventListener('mousemove', onMove)
  canvas.addEventListener('mouseleave', () => {
    hoveredIdx = null
    scheduleRender()
    tooltip.style.display = 'none'
  })

  const RO = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => render()) : null
  if (RO) RO.observe(canvasWrap)

  // 초기 렌더
  data = options.data
  center = options.center
  render()
  renderLegend()

  return {
    el: wrapper,
    updateData(newData: SectorDonutRow[], newCenter?: SectorDonutCenter) {
      data = newData
      center = newCenter
      render()
      renderLegend()
    },
    resize() { render() },
    destroy() {
      if (rafId !== null) cancelAnimationFrame(rafId)
      rafId = null
      if (RO) RO.disconnect()
      canvas.removeEventListener('mousemove', onMove)
      wrapper.remove()
    },
  }
}
