// frontend/src/pages/sector-stock-list.ui.test.ts
// sector-stock-list.ui.ts 테스트

import { renderSectorStockListUi, updateSectorStockListUi, type SectorStockListUiProps } from './sector-stock-list.ui'

/* ── 테스트 유틸리티 ── */

function createMockContainer(): HTMLElement {
  const div = document.createElement('div')
  document.body.appendChild(div)
  return div
}

function createMockAllStocks(): Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }> {
  const map = new Map()
  map.set('005930', { code: '005930', name: '삼성전자', sector: '반도체', market_type: 'KOSPI', nxt_enable: true })
  map.set('000660', { code: '000660', name: 'SK하이닉스', sector: '반도체', market_type: 'KOSPI', nxt_enable: true })
  map.set('035420', { code: '035420', name: 'NAVER', sector: 'IT', market_type: 'KOSPI', nxt_enable: false })
  map.set('028260', { code: '028260', name: '삼성물산', sector: '건설', market_type: 'KOSPI', nxt_enable: true })
  map.set('051910', { code: '051910', name: 'LG화학', sector: '화학', market_type: 'KOSPI', nxt_enable: true })
  return map
}

/* ── 테스트 케이스 ── */

export function testSectorStockListUi(): void {
  console.log('[sector-stock-list.ui.test] 테스트 시작')

  const tripleCenter = createMockContainer()
  const tripleRight = createMockContainer()

  const stagingSet = new Set(['005930'])
  const selectedStocks = new Set(['000660'])

  const mockProps: SectorStockListUiProps = {
    selectedSector: '반도체',
    allStocks: createMockAllStocks(),
    stockMoves: {},
    sectors: {},
    deletedSectors: [],
    mergedSectors: ['반도체', 'IT', '건설', '화학'],
    stagingSet,
    selectedStocks,
    onStagingRemove: (code) => console.log(`[TEST] onStagingRemove: ${code}`),
    onStagingClear: () => console.log('[TEST] onStagingClear'),
    onStockSelect: (codes) => console.log(`[TEST] onStockSelect: ${codes.size}개 선택`),
    onMoveStock: (codes, targetSector) => console.log(`[TEST] onMoveStock: ${codes.length}개 -> ${targetSector}`),
  }

  // 렌더링 테스트
  renderSectorStockListUi(tripleCenter, tripleRight, mockProps)
  console.log('[sector-stock-list.ui.test] 렌더링 완료')

  // Staging Panel 검증
  const stagingPanel = tripleCenter.querySelector('.staging-chip-list')
  if (stagingPanel) {
    console.log('[sector-stock-list.ui.test] ✓ Staging Panel 렌더링 성공')
    const chips = stagingPanel.querySelectorAll('.staging-chip')
    if (chips.length === 1) {
      console.log('[sector-stock-list.ui.test] ✓ Chip 수 검증 성공 (1개)')
    } else {
      console.error(`[sector-stock-list.ui.test] ✗ Chip 수 검증 실패 (기대: 1, 실제: ${chips.length})`)
    }
  } else {
    console.error('[sector-stock-list.ui.test] ✗ Staging Panel 렌더링 실패')
  }

  // 종목 목록 테이블 검증
  const detailTitle = tripleCenter.querySelector('div')
  if (detailTitle?.textContent?.includes('반도체 종목 목록')) {
    console.log('[sector-stock-list.ui.test] ✓ 종목 목록 타이틀 검증 성공')
  } else {
    console.error('[sector-stock-list.ui.test] ✗ 종목 목록 타이틀 검증 실패')
  }

  const detailTable = tripleCenter.querySelector('table')
  if (detailTable) {
    console.log('[sector-stock-list.ui.test] ✓ 종목 테이블 렌더링 성공')
    const rows = detailTable.querySelectorAll('tbody tr')
    if (rows.length === 2) {
      console.log('[sector-stock-list.ui.test] ✓ 종목 행 수 검증 성공 (2개)')
    } else {
      console.error(`[sector-stock-list.ui.test] ✗ 종목 행 수 검증 실패 (기대: 2, 실제: ${rows.length})`)
    }
  } else {
    console.error('[sector-stock-list.ui.test] ✗ 종목 테이블 렌더링 실패')
  }

  // 대상 업종 리스트 검증
  const rightTitle = tripleRight.querySelector('div')
  if (rightTitle?.textContent === '대상 업종') {
    console.log('[sector-stock-list.ui.test] ✓ 대상 업종 타이틀 검증 성공')
  } else {
    console.error('[sector-stock-list.ui.test] ✗ 대상 업종 타이틀 검증 실패')
  }

  const targetList = tripleRight.querySelector('.sf-sector-row')
  if (targetList) {
    console.log('[sector-stock-list.ui.test] ✓ 대상 업종 리스트 렌더링 성공')
  } else {
    console.error('[sector-stock-list.ui.test] ✗ 대상 업종 리스트 렌더링 실패')
  }

  // Props 갱신 테스트
  stagingSet.add('000660')
  updateSectorStockListUi(mockProps)
  console.log('[sector-stock-list.ui.test] Props 갱신 완료')

  // 정리
  document.body.removeChild(tripleCenter)
  document.body.removeChild(tripleRight)
  console.log('[sector-stock-list.ui.test] 테스트 완료')
}

// 자동 실행 (브라우저 환경)
if (typeof window !== 'undefined') {
  (window as any).testSectorStockListUi = testSectorStockListUi
}
