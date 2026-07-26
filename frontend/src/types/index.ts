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
  trade_mode: string;
  position_count?: number;
}

export interface Position {
  stk_cd: string;
  stk_nm: string;
  qty: number;
  avg_price: number;
  cur_price: number;
  buy_amt: number;
  pnl_rate: number;
  nxt_enable?: boolean;
  buy_date: string;
  sectorStock?: SectorStock;
}

export interface SectorStock {
  code: string;
  name: string;
  // ── 실시간 파생 필드 (sectorStocks가 SSOT, buyTargets는 파생 캐시) ──
  // P10: sectorStocks Record가 실시간 시세의 단일 진실 소스.
  // buyTargets 배열 요소의 이 필드들은 DataTable O(1) updateItemByKey 갱신을 위한
  // 파생 캐시 — applyRealData가 in-place mutation으로 동기화,
  // applySectorStocksRefresh/applyRealtimeReset이 rebindBuyTargetsRealtime으로 재결합.
  // null 표시 규칙 (세션 8 — P22 데이터 정합성, 백엔드 _build_target_entry 계약 반영):
  //   cur_price: null = 틱 미수신 (테스트모드 기동 직후, 장 전, 구독 지연).
  //              첫 틱 도달 후 applyRealData가 number로 갱신.
  //   change_rate/trade_amount/change/strength: 백엔드 None 시 null/undefined 가능.
  //              현재 타입은 기존 호환성 유지 (change_rate는 number, 나머지 optional).
  //              백엔드가 null을 보내면 런타임 값은 null이나 타입은 좁게 선언 —
  //              소비 측는 null 가드(== null)로 처리 권장.
  cur_price: number | null;
  change_rate: number;
  trade_amount?: number;
  change?: number;
  strength?: number;
  // ── 정적·식별 필드 (업종 종목·매수 후보 공통) ──
  sector?: string;
  avg_amt_5d?: number;
  market_type?: string;
  nxt_enable?: boolean;
  // ── 매수 후보 전용 정적 필드 (buyTargets에만 의미 있음) ──
  rank?: number;
  guard_pass?: boolean;
  reason?: string;
  boost_score?: number;
  order_ratio?: [number, number] | null;
  high_5d?: number;  // 0 = 원천 부재/미다운로드 (5거래일 일봉 전), >0 = 유효 고가
  program_net_buy?: number | null;  // null/undefined = 프로그램 순매수 미수신
  news_boost?: number;  // 뉴스 호재 가산점 (0 = 미부여, >0 = 부여됨)
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
}

/** engine-status 이벤트 payload — get_engine_status() 결과 + _v */
export interface EngineStatusPayload {
  _v?: number;
  running?: boolean;
  connected?: boolean;
  broker_connected?: boolean;
  logged_in?: boolean;
  login_ok?: boolean;
  broker_token_valid?: boolean;
  trade_mode?: string;
  is_test_mode?: boolean;
  engine_task_alive?: boolean;
  stock_subscribed_count?: number;
  ws_reg_total_estimate?: number;
  broker_statuses?: Record<string, { token_valid: boolean; ws_connected: boolean }>;
  market_phase?: {
    krx: string;
    nxt: string;
    krx_alert?: string | null;
    is_nxt_only?: boolean;
    krx_countdown?: { label: string; remaining_sec: number } | null;
    nxt_countdown?: { label: string; remaining_sec: number } | null;
  };
  position_build_failed?: boolean;
  degraded_mode?: boolean;
}

export interface AppSettings {
  // 주 사용 증권사 (Primary Broker)
  broker: string;

  // 거래 모드
  trade_mode: string;

  // 매수 설정
  buy_amt: number;
  buy_amt_on: boolean;
  max_daily_total_buy_on: boolean;
  max_daily_total_buy_amt: number;
  max_stock_cnt: number;
  max_stock_cnt_on: boolean;
  rebuy_block_on: boolean;
  rebuy_block_period: string;

  // 매수 주문 간격 (1순위 종목만 매수 후 사용자 설정 간격 대기, 초 단위 5~300 5초 단위)
  buy_interval_on: boolean;
  buy_interval_sec: number;

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

  // 매도 주문 간격 (손절 포함 모든 매도에 적용, 초 단위 5~300 5초 단위)
  sell_interval_on: boolean;
  sell_interval_sec: number;

  // 시간 설정
  buy_time_start: string;
  buy_time_end: string;
  sell_time_start: string;
  sell_time_end: string;
  'timetable.confirmed_download': string;
  industry_auto_subscribe: boolean;
  index_auto_subscribe: boolean;
  quote_auto_subscribe: boolean;

  // 구독 한도 (종목 실시간 시세 0B 동시 구독 최대 개수, 기본 200, 범위 1~1000)
  'subscribe.max_0b_count'?: number;

  // 전역매매설정 (리스크 매니저) — 목표 손실 도달 시 자동 매매 중단
  risk_manager_on?: boolean;
  daily_loss_limit_on?: boolean;                // 일일 손실 한도 활성화 (기본 ON — 기존 항상 실행 동작 유지)
  daily_loss_limit?: number;                    // 일일 손실 한도 (원, 음수, 기본 -50만원)
  daily_loss_rate_limit_on?: boolean;           // 일일 손실률 한도 활성화
  daily_loss_rate_limit?: number;               // 일일 손실률 한도 (%, 음수, 기본 -5.0)
  risk_block_buy_on?: boolean;                  // 리스크 조건 충족 시 매수 차단
  risk_block_sell_on?: boolean;                 // 리스크 조건 충족 시 매도 차단 (손실 확대 위험)
  consecutive_loss_limit_on?: boolean;          // 연속 손실 횟수 한도 활성화
  consecutive_loss_limit?: number;              // 연속 손실 횟수 한도 (회, 기본 3)

  // 업종 필터
  sector_min_rise_ratio_pct: number;
  sector_min_trade_amt: number;
  sector_max_targets: number;
  sector_start_threshold_pct: number;

  // 업종 점수 3단계 가산점 가중치 슬라이더 (-100%~+100%, 기본값 0)
  sector_bonus_rise_ratio_slider: number;
  sector_bonus_relative_strength_slider: number;
  sector_bonus_trade_amount_slider: number;

  // 매수 차단
  buy_block_rise_on: boolean;
  buy_block_rise_pct: number;
  buy_block_fall_on: boolean;
  buy_block_fall_pct: number;

  // 매수 가산점
  boost_high_breakout_on: boolean;
  boost_high_breakout_score: number;
  boost_order_ratio_on: boolean;
  boost_order_ratio_pct: number;
  boost_order_ratio_score: number;
  boost_program_net_buy_on: boolean;
  boost_program_net_buy_score: number;

  // 매수 가산점 — 뉴스 호재 (NWS)
  boost_news_on: boolean;
  boost_news_score: number;
  news_boost_ttl_sec: number;
  news_keywords: string;  // 쉼표 구분 문자열

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

  // 수익현황/수익상세 WS push 일별 요약 범위 (최근 N거래일, 0=누적, 기본 20)
  daily_summary_days: number;

  // 기타
  auto_trading_effective: boolean;
  auto_buy_effective: boolean;
  auto_sell_effective: boolean;

  // B21-01 세션7: 암호화 상태 — 백엔드 GET /api/settings 응답에 포함 (설계 7.1/7.2).
  // 옵션 필드 — 구형 백엔드 응답에 없을 수 있음 (하위 호환).
  encryption_key_state?: EncryptionKeyState;
  secret_field_states?: Record<string, SecretFieldStatus>;

  [key: string]: unknown;
}

// sector_max_targets 프론트엔드 fallback 기본값
// 백엔드 settings_defaults.py의 기본값(3)과 동일 — SSOT
export const DEFAULT_SECTOR_MAX_TARGETS = 3;

// B21-01 세션7: 암호화 상태 타입 — 백엔드 encryption.py KeyState/SecretValueState와 1:1 대응 (P10 SSOT).
// 백엔드가 enum.name 문자열로 내려주므로 프론트엔드는 문자열 리터럴 유니온으로 수신.
export type EncryptionKeyState = 'AVAILABLE' | 'MISSING' | 'INVALID';
export type SecretFieldStatus =
  | 'EMPTY'
  | 'ENCRYPTED'
  | 'PLAINTEXT_LEGACY'
  | 'KEY_UNAVAILABLE'
  | 'DECRYPT_FAILED';

export interface SaveResult {
  ok: boolean;
  error?: string;
  // B21-01 세션6: 백엔드 구조화 오류 응답(설계 5) 전달 — 세션7 UI에서 코드 기반 메시지 매핑.
  errorCode?: string;
  errorField?: string;
}

export interface SectorScoreRow {
  rank: number;
  sector: string;
  final_score: number;              // 0~만점 합 (종합 가산점 = 1차+2차+3차)
  bonus_rise_ratio: number;         // 1차 가산점 (0~조정 만점) — 업종 내 상승 종목 비율 순위
  bonus_relative_strength: number;  // 2차 가산점 (0~조정 만점) — 통과 업종 종목들 가중 순위 합
  bonus_trade_amount: number;       // 3차 가산점 (0~조정 만점) — 업종 평균 거래대금 순위
  avg_trade_amount: number;         // 평균 거래대금
  rise_ratio: number;
  total: number;
  is_cutoff_passed: boolean;        // 컷오프(min_rise_ratio) 통과 여부 — rank와 분리된 진실 소스 (P10)
}

export interface SectorStatus {
  total_stocks: number;
  max_targets?: number;
  ranked_sectors_count?: number;
}

export interface SectorScoresEvent {
  scores?: SectorScoreRow[];
  changed_scores?: SectorScoreRow[];
  status: SectorStatus;
  delta?: boolean;
  changed_sectors?: string[];
  removed_sectors?: string[];
}

/** [근본해결] 키움 실시간 Raw 데이터 이벤트
 *
 * 갱신 계약 (세션 7 — `applyRealData` 참조):
 * - `type`: 키움 TR 코드. `applyRealData`가 처리하는 handled types:
 *   - '01' / '0B' / '0H' — 주식체결 (현재가/대비/등락률/체결강도/거래대금).
 *   - 미지원 type(예: '0A' 등)은 `applyRealData`에서 스킵 — 상태 미변경, 디스패치 안 함.
 * - `item`: 종목코드 (정규화 전 raw — `applyRealData`가 `normalizeStockCode`로 정규화).
 * - `values`: 키움 FID 키 → 값 문자열 매핑. handled keys (01/0B/0H):
 *   - '10' = 현재가, '11' = 대비, '12' = 등락률, '14' = 거래대금, '228' = 체결강도.
 *   - 부재 키는 `applyRealData`가 기존 상태값 유지 (폴백 아님 — P20).
 */
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

export interface StockClassificationMutationResponse {
  ok: boolean;
  error?: string;
  warning?: string;
  all_stocks?: Array<{ code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }>;
}
