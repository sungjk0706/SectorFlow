// frontend/src/pages/metrics-dashboard.ts
// Metrics Dashboard 페이지 — Latency metrics 시각화 및 Alert 표시

import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import { api } from '../api/client'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { getRenderMetrics } from '../utils/render-metrics'

/* ── 타입 정의 ── */

interface MetricSummary {
  count: number
  min: number
  max: number
  avg: number
  p50: number | null
  p95: number | null
  p99: number | null
}

interface Alert {
  timestamp: number
  metric_name: string
  value: number
  threshold: number
}

/* ── 프론트엔드 메트릭 컬럼 ── */

const FRONTEND_METRIC_COLS: ColumnDef<{ name: string; value: string }>[] = [
  { key: 'name', label: '메트릭', align: 'left', render: r => r.name },
  { key: 'value', label: '값', align: 'right', render: r => r.value },
]

/* ── 메트릭 요약 테이블 컬럼 ── */

const METRIC_COLS: ColumnDef<{ name: string; summary: MetricSummary }>[] = [
  { key: 'name', label: '메트릭', align: 'left', render: r => r.name },
  { key: 'count', label: 'Count', align: 'right', render: r => String(r.summary.count) },
  { key: 'min', label: 'Min (ms)', align: 'right', render: r => r.summary.min.toFixed(2) },
  { key: 'max', label: 'Max (ms)', align: 'right', render: r => r.summary.max.toFixed(2) },
  { key: 'avg', label: 'Avg (ms)', align: 'right', render: r => r.summary.avg.toFixed(2) },
  { key: 'p50', label: 'P50 (ms)', align: 'right', render: r => r.summary.p50?.toFixed(2) ?? 'N/A' },
  { key: 'p95', label: 'P95 (ms)', align: 'right', render: r => r.summary.p95?.toFixed(2) ?? 'N/A' },
  { key: 'p99', label: 'P99 (ms)', align: 'right', render: r => r.summary.p99?.toFixed(2) ?? 'N/A' },
]

/* ── Alert 테이블 컬럼 ── */

const ALERT_COLS: ColumnDef<Alert>[] = [
  { 
    key: 'timestamp', 
    label: '시간', 
    align: 'center', 
    render: r => {
      const date = new Date(r.timestamp * 1000)
      return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
    }
  },
  { key: 'metric_name', label: '메트릭', align: 'left', render: r => r.metric_name },
  { key: 'value', label: '값 (ms)', align: 'right', render: r => r.value.toFixed(2) },
  { key: 'threshold', label: '임계값 (ms)', align: 'right', render: r => r.threshold.toFixed(2) },
]

/* ── 페이지 모듈 ── */

export function createMetricsDashboard() {
  const container = document.createElement('div')
  container.style.cssText = `
    padding: 20px;
    max-width: 1400px;
    margin: 0 auto;
  `

  // 헤더
  const header = document.createElement('div')
  header.style.cssText = `
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  `
  
  const title = document.createElement('h1')
  title.textContent = 'Metrics Dashboard'
  title.style.cssText = `
    font-size: ${FONT_SIZE.title};
    font-weight: ${FONT_WEIGHT.bold};
    margin: 0;
  `
  
  header.appendChild(title)
  container.appendChild(header)

  // Phase 2.3: 프론트엔드 메트릭 섹션
  const frontendSection = document.createElement('div')
  frontendSection.style.cssText = `
    margin-bottom: 30px;
  `

  const frontendTitle = document.createElement('h2')
  frontendTitle.textContent = '프론트엔드 렌더링 성능'
  frontendTitle.style.cssText = `
    font-size: ${FONT_SIZE.section};
    font-weight: ${FONT_WEIGHT.semibold};
    margin-bottom: 15px;
  `
  frontendSection.appendChild(frontendTitle)

  const frontendTableContainer = document.createElement('div')
  frontendSection.appendChild(frontendTableContainer)
  container.appendChild(frontendSection)

  // 메트릭 요약 섹션
  const metricsSection = document.createElement('div')
  metricsSection.style.cssText = `
    margin-bottom: 30px;
  `

  const metricsTitle = document.createElement('h2')
  metricsTitle.textContent = '메트릭 요약'
  metricsTitle.style.cssText = `
    font-size: ${FONT_SIZE.section};
    font-weight: ${FONT_WEIGHT.semibold};
    margin-bottom: 15px;
  `
  metricsSection.appendChild(metricsTitle)

  const metricsTableContainer = document.createElement('div')
  metricsSection.appendChild(metricsTableContainer)
  container.appendChild(metricsSection)

  // Alert 섹션
  const alertsSection = document.createElement('div')
  alertsSection.style.cssText = `
    margin-bottom: 30px;
  `

  const alertsTitle = document.createElement('h2')
  alertsTitle.textContent = '최근 Alert'
  alertsTitle.style.cssText = `
    font-size: ${FONT_SIZE.section};
    font-weight: ${FONT_WEIGHT.semibold};
    margin-bottom: 15px;
  `
  alertsSection.appendChild(alertsTitle)

  const alertsTableContainer = document.createElement('div')
  alertsSection.appendChild(alertsTableContainer)
  container.appendChild(alertsSection)

  // 컨트롤 섹션
  const controlsSection = document.createElement('div')
  controlsSection.style.cssText = `
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
  `

  const refreshButton = document.createElement('button')
  refreshButton.textContent = '새로고침'
  refreshButton.style.cssText = `
    padding: 8px 16px;
    background: #007bff;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: ${FONT_SIZE.label};
  `
  
  const clearButton = document.createElement('button')
  clearButton.textContent = '메트릭 초기화'
  clearButton.style.cssText = `
    padding: 8px 16px;
    background: #dc3545;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: ${FONT_SIZE.label};
  `

  controlsSection.appendChild(refreshButton)
  controlsSection.appendChild(clearButton)
  container.insertBefore(controlsSection, metricsSection)

  // 테이블 생성
  let metricsTable: DataTableApi<{ name: string; summary: MetricSummary }> | null = null
  let alertsTable: DataTableApi<Alert> | null = null
  let frontendTable: DataTableApi<{ name: string; value: string }> | null = null

  // 데이터 로드 함수
  async function loadData() {
    try {
      const [summary, alerts, dropped] = await Promise.all([
        api.fetchMetricsSummary(),
        api.fetchMetricsAlerts(20),
        api.fetchMetricsDropped(),
      ])

      // Phase 2.3: 프론트엔드 메트릭 로드
      const renderMetrics = getRenderMetrics()
      const renderSummary = renderMetrics.getSummary()
      const frontendData = [
        { name: '렌더링 수', value: String(renderSummary.count) },
        { name: '최소 지연시간 (ms)', value: renderSummary.min.toFixed(2) },
        { name: '최대 지연시간 (ms)', value: renderSummary.max.toFixed(2) },
        { name: '평균 지연시간 (ms)', value: renderSummary.avg.toFixed(2) },
        { name: 'Frame Drop 수', value: String(renderSummary.frameDropCount) },
        { name: 'Frame Drop 비율 (%)', value: (renderSummary.frameDropRate * 100).toFixed(2) },
        { name: 'Drop 패킷 수', value: String(dropped.dropped_count) },
      ]

      if (!frontendTable) {
        frontendTable = createDataTable<{ name: string; value: string }>({
          columns: FRONTEND_METRIC_COLS,
          virtualScroll: false,
          stickyHeader: true,
          emptyText: '프론트엔드 메트릭 데이터 없음',
        })
        frontendTableContainer.appendChild(frontendTable.el)
      }
      frontendTable.updateRows(frontendData)

      // 메트릭 요약 데이터 변환
      const metricsData = Object.entries(summary).map(([name, sum]) => ({ name, summary: sum }))

      if (!metricsTable) {
        metricsTable = createDataTable<{ name: string; summary: MetricSummary }>({
          columns: METRIC_COLS,
          virtualScroll: false,
          stickyHeader: true,
          emptyText: '메트릭 데이터 없음',
        })
        metricsTableContainer.appendChild(metricsTable.el)
      }
      metricsTable.updateRows(metricsData)

      // Alert 데이터
      if (!alertsTable) {
        alertsTable = createDataTable<Alert>({
          columns: ALERT_COLS,
          virtualScroll: false,
          stickyHeader: true,
          emptyText: 'Alert 없음',
        })
        alertsTableContainer.appendChild(alertsTable.el)
      }
      alertsTable.updateRows(alerts)
    } catch (error) {
      console.error('[MetricsDashboard] 데이터 로드 실패:', error)
    }
  }

  // 이벤트 리스너
  refreshButton.addEventListener('click', loadData)

  clearButton.addEventListener('click', async () => {
    try {
      await api.clearMetrics()
      getRenderMetrics().reset() // Phase 2.3: 프론트엔드 메트릭 초기화
      await loadData()
    } catch (error) {
      console.error('[MetricsDashboard] 메트릭 초기화 실패:', error)
    }
  })

  // 자동 갱신 (5초 주기)
  let refreshInterval: number | null = null

  function startAutoRefresh() {
    if (refreshInterval !== null) return
    refreshInterval = window.setInterval(loadData, 5000)
  }

  function stopAutoRefresh() {
    if (refreshInterval !== null) {
      clearInterval(refreshInterval)
      refreshInterval = null
    }
  }

  // 초기 로드
  loadData()
  startAutoRefresh()

  // 페이지 활성/비활성 처리
  notifyPageActive('metrics-dashboard')

  return {
    element: container,
    destroy: () => {
      stopAutoRefresh()
      notifyPageInactive('metrics-dashboard')
      metricsTable?.destroy()
      alertsTable?.destroy()
      container.remove()
    },
    mount: (target: HTMLElement) => {
      target.appendChild(container)
      startAutoRefresh()
    },
    unmount: () => {
      stopAutoRefresh()
      notifyPageInactive('metrics-dashboard')
      metricsTable?.destroy()
      alertsTable?.destroy()
      container.remove()
    },
  }
}

// PageModule 인터페이스 구현
export default {
  mount: (container: HTMLElement) => {
    const dashboard = createMetricsDashboard()
    container.appendChild(dashboard.element)
    return dashboard
  },
  unmount: () => {
    // unmount는 dashboard.destroy()가 처리
  },
}
