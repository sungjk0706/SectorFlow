import { describe, it, expect, beforeEach } from 'vitest'
import { renderAccountTab, syncTradeMode } from '../../src/pages/general-settings-account-tab'
import { state, resetState } from '../../src/pages/general-settings-shared'

/**
 * 매매모드 탭 회귀 테스트 — "초기 비활성화 + sync 누락" 패턴 방어.
 *
 * 회귀 버그: renderTestVirtualSection이 초기 렌더 시 innerSection(wrap)에
 * opacity/pointerEvents를 설정하나, syncTradeMode는 외부 testVirtualSection의
 * display만 갱신하여 실전→가상 전환 후 innerSection 비활성화가 잔존했음.
 * 수정: display 토글 단일 메커니즘으로 일원화 (opacity/pointerEvents 초기 설정 제거).
 *
 * DOM 구조:
 *   state.testVirtualSection (외부 div, display 토글 대상)
 *     ├── virtualTitle (children[0])
 *     └── innerSection (children[1], opacity/pointerEvents 잔존 발생지)
 *
 * 이 테스트는 다음 패턴을 방어:
 * - 초기 렌더 시 설정된 비활성화 스타일이 sync 호출 후에도 잔존하지 않는지 확인
 * - display 토글이 모드 전환 시 올바르게 동작하는지 확인
 */
function getInnerSection(): HTMLElement {
  const section = state.testVirtualSection!
  return section.children[1] as HTMLElement
}

describe('매매모드 탭 — display 토글 단일 메커니즘 회귀', () => {
  beforeEach(() => {
    resetState()
    document.body.innerHTML = ''
  })

  describe('초기 렌더', () => {
    it('가상매매 모드: 가상 투자금 영역 표시, 비활성화 스타일 없음', () => {
      state.vals.trade_mode = 'virtual'
      state.vals.virtual_deposit = 10000000

      renderAccountTab(state, document.body)

      const section = state.testVirtualSection!
      expect(section).toBeTruthy()
      expect(section.style.display).toBe('')
      // 핵심: innerSection에 opacity/pointerEvents가 설정되지 않아야 함
      const inner = getInnerSection()
      expect(inner.style.opacity).toBe('')
      expect(inner.style.pointerEvents).toBe('')
    })

    it('실전매매 모드: 가상 투자금 영역 숨김', () => {
      state.vals.trade_mode = 'live'
      state.vals.virtual_deposit = 10000000

      renderAccountTab(state, document.body)

      const section = state.testVirtualSection!
      expect(section.style.display).toBe('none')
    })
  })

  describe('모드 전환 시 syncTradeMode', () => {
    it('실전→가상 전환: 영역 표시 + innerSection 비활성화 스타일 잔존 없음 (회귀 버그 방어)', () => {
      // 초기 실전모드 렌더
      state.vals.trade_mode = 'live'
      state.vals.virtual_deposit = 10000000
      renderAccountTab(state, document.body)

      const section = state.testVirtualSection!
      expect(section.style.display).toBe('none')

      // 가상모드로 전환 + syncTradeMode 호출
      state.vals.trade_mode = 'virtual'
      syncTradeMode(state)

      // 핵심 검증: display는 보이게, innerSection opacity/pointerEvents는 잔존하지 않아야 함
      expect(section.style.display).toBe('')
      const inner = getInnerSection()
      expect(inner.style.opacity).toBe('')
      expect(inner.style.pointerEvents).toBe('')
    })

    it('가상→실전 전환: 영역 숨김', () => {
      state.vals.trade_mode = 'virtual'
      state.vals.virtual_deposit = 10000000
      renderAccountTab(state, document.body)

      const section = state.testVirtualSection!
      expect(section.style.display).toBe('')

      state.vals.trade_mode = 'live'
      syncTradeMode(state)

      expect(section.style.display).toBe('none')
    })

    it('동일 모드 재호출: 상태 유지 (no-op)', () => {
      state.vals.trade_mode = 'virtual'
      state.vals.virtual_deposit = 10000000
      renderAccountTab(state, document.body)

      const section = state.testVirtualSection!
      syncTradeMode(state) // 동일 모드 재호출
      syncTradeMode(state)

      expect(section.style.display).toBe('')
      const inner = getInnerSection()
      expect(inner.style.opacity).toBe('')
      expect(inner.style.pointerEvents).toBe('')
    })
  })

  describe('라디오 그룹 동기화', () => {
    it('syncTradeMode가 라디오 값을 현재 모드로 갱신', () => {
      state.vals.trade_mode = 'live'
      state.vals.virtual_deposit = 10000000
      renderAccountTab(state, document.body)

      state.vals.trade_mode = 'virtual'
      syncTradeMode(state)

      expect(state.tradeModeRadioGroup?.getValue()).toBe('virtual')
    })
  })
})
