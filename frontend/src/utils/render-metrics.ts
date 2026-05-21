// frontend/src/utils/render-metrics.ts
// 프론트엔드 렌더링 성능 측정 모듈

/* ── 타입 정의 ── */

export interface RenderMetric {
  timestamp: number
  renderDuration: number
  frameDrop: boolean
}

export interface RenderMetricsSummary {
  count: number
  min: number
  max: number
  avg: number
  frameDropCount: number
  frameDropRate: number
}

/* ── RenderMetrics 클래스 ── */

export class RenderMetrics {
  private metrics: RenderMetric[] = []
  private maxSamples: number = 1000
  private frameThreshold: number = 16.67 // 60fps 기준 (ms)
  private lastFrameTime: number = 0

  constructor(maxSamples: number = 1000, frameThreshold: number = 16.67) {
    this.maxSamples = maxSamples
    this.frameThreshold = frameThreshold
  }

  /**
   * 렌더링 지연시간 측정
   */
  measureRender(): number {
    const now = performance.now()
    let duration = 0
    
    if (this.lastFrameTime > 0) {
      duration = now - this.lastFrameTime
      const frameDrop = duration > this.frameThreshold
      
      this.metrics.push({
        timestamp: Date.now(),
        renderDuration: duration,
        frameDrop
      })
      
      // 최대 샘플 수 유지
      if (this.metrics.length > this.maxSamples) {
        this.metrics.shift()
      }
    }
    
    this.lastFrameTime = now
    return duration
  }

  /**
   * 렌더링 메트릭 요약 계산
   */
  getSummary(): RenderMetricsSummary {
    if (this.metrics.length === 0) {
      return {
        count: 0,
        min: 0,
        max: 0,
        avg: 0,
        frameDropCount: 0,
        frameDropRate: 0
      }
    }

    const durations = this.metrics.map(m => m.renderDuration)
    const frameDrops = this.metrics.filter(m => m.frameDrop).length

    return {
      count: this.metrics.length,
      min: Math.min(...durations),
      max: Math.max(...durations),
      avg: durations.reduce((sum, d) => sum + d, 0) / durations.length,
      frameDropCount: frameDrops,
      frameDropRate: frameDrops / this.metrics.length
    }
  }

  /**
   * 최근 N개의 메트릭 반환
   */
  getRecentMetrics(count: number): RenderMetric[] {
    return this.metrics.slice(-count)
  }

  /**
   * 메트릭 초기화
   */
  reset(): void {
    this.metrics = []
    this.lastFrameTime = 0
  }
}

/* ── 싱글톤 인스턴스 ── */

let renderMetricsInstance: RenderMetrics | null = null

export function getRenderMetrics(): RenderMetrics {
  if (!renderMetricsInstance) {
    renderMetricsInstance = new RenderMetrics()
  }
  return renderMetricsInstance
}
