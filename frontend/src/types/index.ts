// frontend/src/types/index.ts

export interface AccountSnapshot {
  total_buy_amount: number;
  total_sell_amount: number;
  total_eval_amount: number;
  total_pnl: number;
  total_pnl_rate: number;
  deposit: number;
  orderable?: number;
  initial_deposit?: number;
  price_source?: string;
  trade_mode: string;
}

export interface Position {
  stk_cd: string;
  stk_nm: string;
  qty: number;
  /** 실전모드: buy_price, 테스트모드: avg_price */
  buy_price?: number;
  avg_price?: number;
  cur_price: number;
  eval_amount?: number;
  eval_amt?: number;
  buy_amt?: number;
  buy_amount?: number;
  pnl_amount?: number;
  pnl_rate: number;
  market_type?: string;
  nxt_enable?: boolean;
}

export interface SectorStock {
  code: string;
  name: string;
  cur_price: number;
  change_rate: number;
  trade_amount?: number;
  sector?: string;
  is_kosdaq?: boolean;
  vi_triggered?: boolean;
  change?: number;
  strength?: number;
  avg_amt_5d?: number;
  market_type?: string;
  nxt_enable?: boolean;
}

export interface RadarStock {
  code: string;
  name: string;
  cur_price: number;
  change_rate: number;
  status: string;
  sector?: string;
  strength?: number;
  market_type?: string;
  nxt_enable?: boolean;
}


export interface BuyTarget {
  rank: number;
  name: string;
  code: string;
  sector: string;
  change: number;
  change_rate: number;
  cur_price: number;
  strength: number;
  trade_amount: number;
  boost_score: number;
  order_ratio: [number, number] | null;
  guard_pass: boolean;
  reason: string;
  market_type?: string;
  nxt_enable?: boolean;
  high_5d?: number;
}

export interface IndexData {
  price: number;
  change: number;
  rate: number;
}

export interface EngineStatus {
  running: boolean;
  kiwoom_connected: boolean;
  login_ok: boolean;
  kiwoom_token_valid: boolean;
  trade_mode: string;
  is_test_mode: boolean;
  engine_task_alive: boolean;
  stock_subscribed_count: number;
  ws_reg_total_estimate: number;
  kospi?: IndexData;
  kosdaq?: IndexData;
  index_polling?: boolean;
}

export interface AppSettings {
  // 거래 모드
  trade_mode: string;
  test_mode: boolean;
  kiwoom_mock_mode: boolean;
  mode_real: boolean;

  // 매수 설정
  buy_amt: number;
  max_daily_total_buy_amt: number;
  max_stock_cnt: number;

  // 매도 설정
  tp_val: number;
  tp_unit: string;
  tp_apply: boolean;
  loss_val: number;
  loss_unit: string;
  loss_apply: boolean;
  ts_apply: boolean;
  ts_start_val: number;
  ts_start_unit: string;
  ts_drop_val: number;
  ts_drop_unit: string;
  sell_price_type: string;
  sell_offset: number;

  // 시간 설정
  buy_time_start: string;
  buy_time_end: string;
  sell_time_start: string;
  sell_time_end: string;
  ws_subscribe_start: string;
  ws_subscribe_end: string;
  ws_subscribe_on: boolean;
  industry_auto_subscribe: boolean;
  index_auto_subscribe: boolean;
  quote_auto_subscribe: boolean;

  // 업종 필터
  sector_min_rise_ratio_pct: number;
  sector_min_trade_amt: number;
  sector_weights: Record<string, number>;
  sector_max_targets: number;

  // 매수 차단
  buy_block_rise_pct: number;
  buy_block_fall_pct: number;
  buy_index_guard_kospi_on: boolean;
  buy_index_guard_kosdaq_on: boolean;
  buy_index_kospi_drop: number;
  buy_index_kosdaq_drop: number;

  // 텔레그램
  tele_on: boolean;
  telegram_chat_id: string;
  telegram_bot_token: string;

  // 키움 API
  kiwoom_app_key: string;
  kiwoom_app_secret: string;
  kiwoom_account_no: string;
  kiwoom_app_key_real: string;
  kiwoom_app_secret_real: string;
  kiwoom_account_no_real: string;

  // 테스트 가상잔고
  test_virtual_deposit: number;
  test_virtual_balance: number;

  // 토글
  auto_buy_on: boolean;
  auto_sell_on: boolean;
  time_scheduler_on: boolean;
  holiday_guard_on: boolean;

  // 스케줄러 제어
  scheduler_market_close_on: boolean;
  scheduler_5d_download_on: boolean;

  // 기타
  auto_trading_effective: boolean;
  auto_buy_effective: boolean;
  auto_sell_effective: boolean;
  [key: string]: unknown;
}

export interface SaveResult {
  ok: boolean;
  error?: string;
}

export interface SectionProps {
  settings: AppSettings;
  onSave: (data: Record<string, unknown>) => Promise<SaveResult>;
  onEditingChange: (editing: boolean) => void;
}

export interface SnapshotHistory {
  timestamp?: string;
  snapshot_at?: string;
  total_buy_amount: number;
  total_eval_amount: number;
  total_pnl: number;
  total_pnl_rate: number;
}

export interface SectorScoreRow {
  rank: number;
  sector: string;
  final_score: number;
  total_trade_amount: number;
  rise_ratio: number;
  total: number;
  rise_count: number;
}

export interface SectorStatus {
  total_stocks: number;
  max_targets?: number;
  ranked_sectors_count?: number;
}

// SSE 이벤트 페이로드
export interface TradePriceEvent {
  code: string;
  price: number;
  change?: number;
  change_rate?: number;
  strength?: number | string;
  trade_amount?: number;
}

export interface SectorScoresEvent {
  scores: SectorScoreRow[];
  status: SectorStatus;
}

/** [근본해결] 키움 실시간 Raw 데이터 이벤트 */
export interface RealDataEvent {
  type: string;
  item: string;
  values: Record<string, string>;
}

export interface AccountUpdateEvent {
  snapshot: AccountSnapshot;
  changed_positions?: Position[];
  removed_codes?: string[];
  // Legacy full snapshot (backward compat)
  positions?: Position[];
}

export interface WsSubscribeStatusEvent {
  _v: number;
  index_subscribed: boolean;
  quote_subscribed: boolean;
}

// ── Sector Custom 관련 타입 ──

export interface SectorCustomChangedEvent {
  _v: number;
  custom_data: {
    sectors: Record<string, string>;
    stock_moves: Record<string, string>;
    deleted_sectors: string[];
  };
  merged_sectors: string[];
  no_sector_count?: number;
}

export interface SectorCustomResponse {
  custom_data: {
    sectors: Record<string, string>;
    stock_moves: Record<string, string>;
    deleted_sectors: string[];
  };
  merged_sectors: string[];
  edit_window_open: boolean;
  no_sector_count?: number;
}

export interface SectorCustomMutationResponse {
  ok: boolean;
  error?: string;
  warning?: string;
}
