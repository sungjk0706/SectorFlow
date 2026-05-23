// frontend/src/pages/stock-classification.ui.test.ts
// stock-classification.ui.ts 테스트

import { renderStockClassificationUi, updateStockClassificationUi, type StockClassificationUiProps } from './stock-classification.ui'

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

export function testStockClassificationUi(): void {
  console.log('[stock-classification.ui.test] 테스트 시작')

  const tripleHeader = createMockContainer()
  const tripleLeft = createMockContainer()

  const mockProps: StockClassificationUiProps = {
    editWindowOpen: true,
    sectors: { '반도체': '반도체' },
    stockMoves: {},
    deletedSectors: [],
    mergedSectors: ['반도체', 'IT', '건설', '화학'],
    allStocks: createMockAllStocks(),
    onRenameSector: (oldName, newName) => console.log(`[TEST] onRenameSector: ${oldName} -> ${newName}`),
    onDeleteSector: (name) => console.log(`[TEST] onDeleteSector: ${name}`),
    onAddSector: (name) => console.log(`[TEST] onAddSector: ${name}`),
    onSearchResultClick: (code, sector) => console.log(`[TEST] onSearchResultClick: ${code} -> ${sector}`),
    onSectorSelect: (sectorName) => console.log(`[TEST] onSectorSelect: ${sectorName}`),
  }

  // 렌더링 테스트
  renderStockClassificationUi(tripleHeader, tripleLeft, mockProps)
  console.log('[stock-classification.ui.test] 렌더링 완료')

  // tripleHeader 검증
  if (tripleHeader.querySelector('h4')?.textContent === '업종분류') {
    console.log('[stock-classification.ui.test] ✓ tripleHeader 타이틀 검증 성공')
  } else {
    console.error('[stock-classification.ui.test] ✗ tripleHeader 타이틀 검증 실패')
  }

  // tripleLeft 검증
  if (tripleLeft.querySelector('.sf-card-title')?.textContent?.includes('업종 관리')) {
    console.log('[stock-classification.ui.test] ✓ 업종 관리 카드 타이틀 검증 성공')
  } else {
    console.error('[stock-classification.ui.test] ✗ 업종 관리 카드 타이틀 검증 실패')
  }

  // 업종 테이블 검증
  const table = tripleLeft.querySelector('table')
  if (table) {
    console.log('[stock-classification.ui.test] ✓ 업종 테이블 렌더링 성공')
    const rows = table.querySelectorAll('tbody tr')
    if (rows.length === 4) {
      console.log('[stock-classification.ui.test] ✓ 업종 행 수 검증 성공 (4개)')
    } else {
      console.error(`[stock-classification.ui.test] ✗ 업종 행 수 검증 실패 (기대: 4, 실제: ${rows.length})`)
    }
  } else {
    console.error('[stock-classification.ui.test] ✗ 업종 테이블 렌더링 실패')
  }

  // Props 갱신 테스트
  mockProps.editWindowOpen = false
  updateStockClassificationUi(mockProps)
  console.log('[stock-classification.ui.test] Props 갱신 완료')

  // 정리
  document.body.removeChild(tripleHeader)
  document.body.removeChild(tripleLeft)
  console.log('[stock-classification.ui.test] 테스트 완료')
}

// 자동 실행 (브라우저 환경)
if (typeof window !== 'undefined') {
  (window as any).testStockClassificationUi = testStockClassificationUi
}
