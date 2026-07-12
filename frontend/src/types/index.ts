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
  accumulated_investment?: number;  // 테스트모드: 누적투자금 (초기투자금 + 충전금액)
  price_source?: string;
  trade_mode: string;
  position_count?: number;
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
  buy_date?: string;
  sectorStock?: SectorStock;
}

export interface SectorStock {
  code: string;
  name: string;
  cur_price: number;
  change_rate: number;
  trade_amount?: number;
  sector?: string;
  change?: number;
  strength?: number;
  avg_amt_5d?: number;
  market_type?: string;
  nxt_enable?: boolean;
  // 매수후보 테이블용 추가 필드 (단일 소스 진리 유지)
  rank?: number;
  guard_pass?: boolean;
  reason?: string;
  boost_score?: number;
  order_ratio?: [number, number] | null;
  high_5d?: number;
  trade_amount_rank?: number;
  program_net_buy?: number;
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

// BuyTarget 제거: 매수후보 테이블은 SectorStock 타입 사용 (단일 소스 진리)

export interface EngineStatus {
  running: boolean;
  broker_connected: boolean;
  login_ok: boolean;
  broker_token_valid: boolean;
  trade_mode: string;
  is_test_mode: boolean;
  engine_task_alive: boolean;
  stock_subscribed_count: number;
  ws_reg_total_estimate: number;
  broker_statuses?: Record<string, { token_valid: boolean; ws_connected: boolean }>;
}

export interface IndexData {
  upcode?: string;
  jisu?: string;
  change?: string;
  drate?: string;
  sign?: string;
  broker_statuses?: Record<string, { token_valid: boolean; ws_connected: boolean }>;
}

export interface AppSettings {
  // 주 사용 증권사 (Primary Broker)
  broker: string;

  // 거래 모드
  trade_mode: string;

  // 매수 설정
  buy_amt: number;
  max_daily_total_buy_on: boolean;
  max_daily_total_buy_amt: number;
  max_stock_cnt: number;
  rebuy_block_on: boolean;
  rebuy_block_period: string;

  // 매수 주문 간격 (1순위 종목만 매수 후 사용자 설정 간격 대기)
  buy_interval_on: boolean;
  buy_interval_min: number;

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
  confirmed_download_time: string;
  ws_subscribe_on: boolean;
  industry_auto_subscribe: boolean;
  index_auto_subscribe: boolean;
  quote_auto_subscribe: boolean;

  // 업종 필터
  sector_min_rise_ratio_pct: number;
  sector_min_trade_amt: number;
  sector_weights: Record<string, number>;
  sector_max_targets: number;
  sector_start_threshold_pct: number;
  sector_trim_trade_amt_pct: number;
  sector_trim_change_rate_pct: number;

  // 매수 차단
  buy_block_rise_pct: number;
  buy_block_fall_pct: number;
  buy_min_strength: number;

  // 매수 가산점
  boost_high_breakout_on: boolean;
  boost_high_breakout_score: number;
  boost_order_ratio_on: boolean;
  boost_order_ratio_pct: number;
  boost_order_ratio_score: number;
  boost_program_net_buy_on: boolean;
  boost_program_net_buy_score: number;

  // 텔레그램
  tele_on: boolean;
  telegram_chat_id: string;
  telegram_bot_token_test: string;
  telegram_bot_token_real: string;

  // 키움 API
  kiwoom_app_key: string;
  kiwoom_app_secret: string;
  kiwoom_account_no: string;
  ls_app_key: string;
  ls_app_secret: string;
  ls_account_no: string;

  // 테스트 가상잔고
  test_virtual_deposit: number;
  test_virtual_balance: number;

  // 토글
  auto_buy_on: boolean;
  auto_sell_on: boolean;
  time_scheduler_on: boolean;

  // 스케줄러 제어
  scheduler_market_close_on: boolean;
  scheduler_5d_download_on: boolean;

  // UI 설정
  ui_price_flash_on: boolean;

  // 기타
  auto_trading_effective: boolean;
  auto_buy_effective: boolean;
  auto_sell_effective: boolean;
  [key: string]: unknown;
}

// sector_max_targets 프론트엔드 fallback 기본값
// 백엔드 settings_defaults.py의 기본값(3)과 동일 — SSOT
export const DEFAULT_SECTOR_MAX_TARGETS = 3;

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
  total_trade_amount: number;  // 평균 거래대금 (가중치 계산 기반과 일관성 유지)
  rise_ratio: number;
  total: number;
}

export interface SectorStatus {
  total_stocks: number;
  max_targets?: number;
  ranked_sectors_count?: number;
  normalized_weights?: Record<string, number>;
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
  scores?: SectorScoreRow[];
  changed_scores?: SectorScoreRow[];
  status: SectorStatus;
  delta?: boolean;
  changed_sectors?: string[];
  removed_sectors?: string[];
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

export interface StockClassificationChangedEvent {
  _v: number;
  custom_data: {
    sectors: Record<string, string>;
    stock_moves: Record<string, string>;
  };
  merged_sectors: string[];
  no_sector_count?: number;
  filter_summary?: string;
  all_stocks?: Array<{
    code: string;
    name: string;
    sector: string;
    market_type?: string;
    nxt_enable?: boolean;
  }>;
}

export interface StockClassificationResponse {
  custom_data: {
    sectors: Record<string, string>;
    stock_moves: Record<string, string>;
  };
  merged_sectors: string[];
  edit_window_open: boolean;
  no_sector_count?: number;
  filter_summary?: string;
}

export interface StockClassificationMutationResponse {
  ok: boolean;
  error?: string;
  warning?: string;
  all_stocks?: Array<{ code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }>;
}
