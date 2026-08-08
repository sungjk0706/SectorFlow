import { describe, it, expect, beforeEach } from 'vitest'
import { uiStore, applySettingsChanged } from '../../src/stores/uiStore'
import type { AppSettings, SettingsChangedDeltaEvent } from '../../src/types'

/**
 * COUPLING-S3 항목9 후속 — settings-changed 이벤트 payload 계약 (P23 일관성).
 * 백엔드 notify_desktop_settings_toggled가 동일 이벤트로 전체/delta 두 payload를 전송.
 * applySettingsChanged가 두 분기를 모두 올바르게 처리하는지 검증 (P16 살아있는 경로).
 *
 * 전체 payload: AppSettings 전체 스냅샷 → settings 전체 교체
 * delta payload: { _v, delta: true, changed: Partial<AppSettings> } → 기존 settings에 병합
 */
function makeFullSettings(): AppSettings {
  return {
    broker: 'kiwoom',
    trade_mode: 'test',
    buy_amt: 100000,
    buy_amt_on: true,
    max_daily_total_buy_on: false,
    max_daily_total_buy_amt: 1000000,
    max_stock_cnt: 5,
    max_stock_cnt_on: true,
    rebuy_block_on: true,
    rebuy_block_period: '30',
    buy_interval_on: false,
    buy_interval_sec: 30,
    tp_val: 10,
    tp_unit: '%',
    tp_apply: true,
    loss_val: 5,
    loss_unit: '%',
    loss_apply: true,
    ts_apply: false,
    ts_start_val: 15,
    ts_start_unit: '%',
    ts_drop_val: 3,
    ts_drop_unit: '%',
    sell_price_type: 'market',
    sell_offset: 0,
    sell_interval_on: false,
    sell_interval_sec: 30,
    buy_time_start: '09:00',
    buy_time_end: '15:20',
    sell_time_start: '09:00',
    sell_time_end: '15:20',
    'timetable.confirmed_download': '15:30',
    industry_auto_subscribe: true,
    index_auto_subscribe: true,
    quote_auto_subscribe: true,
    sector_min_rise_ratio_pct: 1.5,
    sector_min_trade_amt: 100,
    sector_max_targets: 3,
    sector_start_threshold_pct: 0.5,
    sector_bonus_rise_ratio_slider: 0,
    sector_bonus_relative_strength_slider: 0,
    sector_bonus_trade_amount_slider: 0,
    buy_block_rise_on: false,
    buy_block_rise_pct: 5,
    buy_block_fall_on: false,
    buy_block_fall_pct: -5,
    boost_high_breakout_on: false,
    boost_high_breakout_score: 1,
    boost_order_ratio_on: false,
    boost_order_ratio_pct: 10,
    boost_order_ratio_score: 1,
    boost_program_net_buy_on: false,
    boost_program_net_buy_score: 1,
    boost_news_on: false,
    boost_news_score: 1,
    news_boost_ttl_sec: 300,
    news_keywords: '',
    tele_on: false,
    telegram_chat_id: '',
    telegram_bot_token_test: '',
    telegram_bot_token_real: '',
    kiwoom_app_key: '',
    kiwoom_app_secret: '',
    kiwoom_account_no: '',
    ls_app_key: '',
    ls_app_secret: '',
    ls_account_no: '',
    virtual_deposit: 10000000,
    virtual_balance: 10000000,
    auto_buy_on: true,
    auto_sell_on: true,
    time_scheduler_on: true,
    scheduler_market_close_on: true,
    ui_price_flash_on: true,
    daily_summary_days: 20,
    auto_trading_effective: true,
    auto_buy_effective: true,
    auto_sell_effective: true,
  } as AppSettings
}

describe('uiStore — applySettingsChanged (settings-changed 이벤트 payload 계약, COUPLING-S3 항목9 후속)', () => {
  beforeEach(() => {
    uiStore.setState({ settings: null })
  })

  describe('전체 payload — settings 전체 교체', () => {
    it('null 상태에서 전체 payload 수신 시 settings 전체 저장', () => {
      const full = makeFullSettings()
      applySettingsChanged(full)
      expect(uiStore.getState().settings).toEqual(full)
    })

    it('기존 settings가 있어도 전체 payload 수신 시 전체 교체 (병합 아님)', () => {
      const existing = makeFullSettings()
      uiStore.setState({ settings: existing })

      const next = makeFullSettings()
      next.auto_buy_on = false
      next.broker = 'ls'
      applySettingsChanged(next)

      const s = uiStore.getState().settings
      expect(s?.auto_buy_on).toBe(false)
      expect(s?.broker).toBe('ls')
    })
  })

  describe('delta payload — 기존 settings에 변경 키만 병합', () => {
    it('기존 settings에 단건 키 병합 (time_scheduler_on 토글)', () => {
      const existing = makeFullSettings()
      existing.time_scheduler_on = true
      uiStore.setState({ settings: existing })

      const delta: SettingsChangedDeltaEvent = {
        _v: 1,
        delta: true,
        changed: { time_scheduler_on: false },
      }
      applySettingsChanged(delta)

      const s = uiStore.getState().settings
      expect(s?.time_scheduler_on).toBe(false)
      // 병합이므로 다른 키는 유지
      expect(s?.broker).toBe('kiwoom')
      expect(s?.auto_buy_on).toBe(true)
    })

    it('여러 키 동시 병합', () => {
      const existing = makeFullSettings()
      uiStore.setState({ settings: existing })

      const delta: SettingsChangedDeltaEvent = {
        _v: 1,
        delta: true,
        changed: { auto_buy_on: false, auto_sell_on: false, buy_amt: 200000 },
      }
      applySettingsChanged(delta)

      const s = uiStore.getState().settings
      expect(s?.auto_buy_on).toBe(false)
      expect(s?.auto_sell_on).toBe(false)
      expect(s?.buy_amt).toBe(200000)
      // 미변경 키 유지
      expect(s?.broker).toBe('kiwoom')
    })

    it('settings가 null일 때 delta 수신 시 changed가 새 settings가 됨', () => {
      const delta: SettingsChangedDeltaEvent = {
        _v: 1,
        delta: true,
        changed: { auto_buy_on: false, broker: 'ls' },
      }
      applySettingsChanged(delta)

      const s = uiStore.getState().settings
      expect(s?.auto_buy_on).toBe(false)
      expect(s?.broker).toBe('ls')
    })
  })

  describe('payload 계약 식별 (P23 일관성)', () => {
    it('delta: true 명시적 신호만 delta 분기로 처리', () => {
      const existing = makeFullSettings()
      existing.auto_buy_on = true
      uiStore.setState({ settings: existing })

      // delta: true 가 없는 payload는 전체로 간주 (AppSettings에 delta 키가 우연히 있어도)
      const fullLike: AppSettings = { ...makeFullSettings(), auto_buy_on: false } as AppSettings
      // AppSettings 인덱스 시그니처로 인해 delta 키가 들어갈 수 있으나 값이 true가 아니면 전체 분기
      ;(fullLike as unknown as { delta?: unknown }).delta = 'not-true'
      applySettingsChanged(fullLike)

      // 전체 교체 — auto_buy_on=false 반영
      expect(uiStore.getState().settings?.auto_buy_on).toBe(false)
    })
  })
})
