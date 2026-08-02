import { describe, it, expect, beforeEach, vi } from 'vitest'

/**
 * 3세션 — notifyPageActive가 페이지 이름만 전송하는지 검증.
 * 종목 코드 목록(codes)이 page-active 메시지에서 제거되었는지 확인 (P10 SSOT, P24 단순성).
 * - notifyPageActive(page) → { type: 'page-active', page } (codes 필드 없음)
 * - notifyPageInactive(page) → { type: 'page-inactive', page }
 * - getCurrentPageCodes는 더 이상 export되지 않음
 */

const { sendMock, settingsSendMock } = vi.hoisted(() => ({
  sendMock: vi.fn(),
  settingsSendMock: vi.fn(),
}))

vi.mock('../../src/api/ws', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/api/ws')>()
  // wsClient/wsSettingsClient의 send를 가로채기 위해 실제 모듈의 싱글톤 send를 덮어쓰기.
  actual.wsClient.send = sendMock
  actual.wsSettingsClient.send = settingsSendMock
  return actual
})

import { notifyPageActive, notifyPageInactive, getCurrentPage } from '../../src/api/ws'

describe('notifyPageActive — 페이지 이름 전용 전송', () => {
  beforeEach(() => {
    sendMock.mockClear()
    settingsSendMock.mockClear()
    notifyPageInactive('buy-target')
    notifyPageInactive('sell-position')
    notifyPageInactive('profit-overview')
    notifyPageInactive('profit-detail')
    notifyPageInactive('stock-classification')
    notifyPageInactive('stock-detail')
    notifyPageInactive('settings')
    notifyPageInactive('sector-ranking')
    sendMock.mockClear()
    settingsSendMock.mockClear()
  })

  it('page-active 메시지에 codes 필드가 없다', () => {
    notifyPageActive('buy-target')
    expect(sendMock).toHaveBeenCalledTimes(1)
    const payload = JSON.parse(sendMock.mock.calls[0][0] as string)
    expect(payload.type).toBe('page-active')
    expect(payload.page).toBe('buy-target')
    expect(payload).not.toHaveProperty('codes')
  })

  it('prices 채널과 settings 채널 모두에 동일 메시지 전송', () => {
    notifyPageActive('settings')
    expect(sendMock).toHaveBeenCalledTimes(1)
    expect(settingsSendMock).toHaveBeenCalledTimes(1)
    const pricesPayload = JSON.parse(sendMock.mock.calls[0][0] as string)
    const settingsPayload = JSON.parse(settingsSendMock.mock.calls[0][0] as string)
    expect(pricesPayload).toEqual(settingsPayload)
    expect(pricesPayload.page).toBe('settings')
  })

  it('여덟 화면 키 모두 페이지 이름만 전송', () => {
    const pages = [
      'sector-ranking', 'buy-target', 'sell-position', 'profit-overview',
      'profit-detail', 'stock-classification', 'stock-detail', 'settings',
    ]
    for (const page of pages) {
      sendMock.mockClear()
      settingsSendMock.mockClear()
      notifyPageActive(page)
      const payload = JSON.parse(sendMock.mock.calls[0][0] as string)
      expect(payload.page).toBe(page)
      expect(payload).not.toHaveProperty('codes')
    }
  })

  it('notifyPageInactive는 page-inactive 메시지 전송', () => {
    notifyPageActive('buy-target')
    sendMock.mockClear()
    settingsSendMock.mockClear()
    notifyPageInactive('buy-target')
    const payload = JSON.parse(sendMock.mock.calls[0][0] as string)
    expect(payload.type).toBe('page-inactive')
    expect(payload.page).toBe('buy-target')
  })

  it('getCurrentPage는 활성 페이지 반환', () => {
    notifyPageActive('profit-detail')
    expect(getCurrentPage()).toBe('profit-detail')
    notifyPageInactive('profit-detail')
    expect(getCurrentPage()).toBeNull()
  })
})
