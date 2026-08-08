// frontend/src/types/index.ts

export interface FreshnessMetadata {
  group: 'account' | 'buy_targets' | 'sector_scores' | 'sector_stocks' | 'trade_history';
  revision: number;
}

export interface FreshnessSnapshot {
  account: FreshnessMetadata;
  buy_targets: FreshnessMetadata;
  sector_scores: FreshnessMetadata;
  sector_stocks: FreshnessMetadata;
  trade_history: FreshnessMetadata;
}

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
  daily_deposit?: number;           // 당일 입금액 (실시간, 당일 카드 분모 보정용)
  total_asset?: number;             // 실전 증권사 API 총자산 (평가금 + 예수금) — P10 SSOT, 재계산 금지
  trade_mode: string;
  position_count?: number;
}

export interface Position {
  stk_cd: string;
  stk_nm: string;
  qty: number;
  avg_price: number;
  cur_price: number | null;  // 계산용 현재가 (손익·평가금액·매도조건·리스크 계산 입력값). 화면 표시 소스 아님 — 표시는 masterStocks 기반 (역할 분리, P22). null = 틱 미수신 (백엔드 _reset_realtime_fields None 설정과 일치)
  buy_amt: number;
  pnl_rate: number;
  nxt_enable?: boolean;
  buy_date: string;
}

// 매수후보는 StockScore(정적 스코어), 실시간 시세는 masterStocks(백엔드 master_stocks_cache 프론트 사본)로 분리 (P10 SSOT).
// 공통 실시간 파생 필드 null 표시 규칙 (세션 8 — P22 데이터 정합성, 백엔드 _build_target_entry 계약 반영):
//   cur_price: null = 틱 미수신 (테스트모드 기동 직후, 장 전, 구독 지연).
//              첫 틱 도달 후 applyRealData가 number로 갱신.
//   change_rate/trade_amount/change/strength: 백엔드 None 시 null/undefined 가능.
//              현재 타입은 기존 호환성 유지 (change_rate는 number, 나머지 optional).
//              백엔드가 null을 보내면 런타임 값은 null이나 타입은 좁게 선언 —
//              소비 측는 null 가드(== null)로 처리 권장.

export interface StockScore {
  // ── 식별 필드 ──
  code: string;
  name: string;
  sector?: string;
  market_type?: string;
  nxt_enable?: boolean;
  // ── 정적 스코어 필드 (백엔드 StockScore + BuyTarget) ──
  rank?: number;
  guard_pass?: boolean;
  reject_reason?: string;
  boost_score?: number;
  // ── 매수후보 전용 파생 필드 ──
  high_5d?: number;  // 0 = 원천 부재/미다운로드 (5거래일 일봉 전), >0 = 유효 고가
  news_boost?: number;  // 뉴스 호재 가산점 (0 = 미부여, >0 = 부여됨)
  news_boost_title?: string;  // 뉴스 호재 제목 (newspaper 아이콘 툴팁 표시용, applyNewsHit이 보관 — P10 SSOT)
  news_boost_keyword?: string;  // 매칭된 호재 키워드 (newspaper 아이콘 옆 표시용, 백엔드가 매칭 단계에서 전달 — P10 SSOT)
}

// 마스터 종목 캐시 프론트 표시 사본 — 백엔드 master_stocks_cache와 1:1 대응 (P10 SSOT).
// 실시간 시세 단일 진실 소스: applyRealData(틱), applyMasterStocksSnapshot(구독 신청 시),
// applyMasterStocksDelta(호가·PGM delta), applyNewsHit(뉴스 호재)가 갱신.
export interface MasterStock {
  // ── 식별 (5) ──
  code: string;
  name: string;
  sector?: string;
  market_type?: string;
  nxt_enable?: boolean;
  // ── 실시간 시세 (5) ──
  cur_price: number | null;     // null = 틱 미수신
  change?: number;
  change_rate: number;
  strength?: number;
  trade_amount?: number;
  sign?: string;                // 전일대비 부호 원본 (1:상한 2:상승 3:보합 4:하한 5:하락) — 증권사 서버 원본 그대로 (P10 SSOT, P22 정합성)
  // ── 5거래일 통계 (2) ──
  avg_amt_5d?: number;          // 백만원 단위 (백엔드 전송 그대로 — 프론트 fmtMillionsToBillion이 억 변환)
  high_5d?: number;             // 0 = 원천 부재, >0 = 유효 고가
  // ── 호가·PGM·뉴스 (3) ──
  order_ratio?: [number, number] | null;
  program_net_buy?: number | null;
  news_boost?: number;          // 뉴스 호재 가산점 (0 = 미부여)
}

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
    chart_reference_trading_day?: string;
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

  // 매수 주문 간격 (1순위 종목만 매수 후 사용자 설정 간격 대기, 초 단위 1~300 1초 단위)
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

  // 매도 주문 간격 (손절 포함 모든 매도에 적용, 초 단위 1~300 1초 단위)
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

  // 시장 지수 급락 가드 — KOSPI/KOSDAQ 각각 독립 설정 (그룹 마스터 토글 없음)
  // 매수/매도 차단 여부는 기존 risk_block_buy_on/risk_block_sell_on 재사용
  market_guard_kospi_on?: boolean;                    // KOSPI 가드 활성화
  market_guard_kospi_drop_threshold_pct?: number;     // KOSPI 임계 (%, 음수, 기본 -5.0)
  market_guard_kosdaq_on?: boolean;                   // KOSDAQ 가드 활성화
  market_guard_kosdaq_drop_threshold_pct?: number;    // KOSDAQ 임계 (%, 음수, 기본 -5.0)

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
  virtual_deposit: number;
  virtual_balance: number;

  // 토글
  auto_buy_on: boolean;
  auto_sell_on: boolean;
  time_scheduler_on: boolean;

  // 스케줄러 제어
  scheduler_market_close_on: boolean;

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
  /** 수신율 임계값 미통과 — "데이터 수신 대기 중" 상태 (P21 투명성).
   * true 시 scores는 빈 배열이며, 임계값 통과 후 정상 전송됨. */
  waiting?: boolean;
}

export interface SectorScoresEvent {
  freshness?: FreshnessMetadata;
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
 *   - '01' / '0B' / '0H' — 종목체결 (현재가/대비/등락률/체결강도/거래대금).
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

/**
 * news-hit 이벤트 — 뉴스 호재 매칭 시 news_boost + boost_score 단일 전달 경로 (P10 SSOT).
 * 백엔드 `_handle_nws_news()`의 `_safe_broadcast("news-hit", payload)`와 계약 일치:
 *   - codes: 호재 매칭 종목코드 리스트 (정규화 전 원본)
 *   - names: 종목명 리스트 (부재 시 빈 문자열, P20 명시적 값)
 *   - scores: news_boost_score 리스트 (codes와 동일 순서)
 *   - boost_scores: 재계산된 boost_score(총합) 리스트 (수정안 3 — 실시간 반영, codes와 동일 순서)
 *   - title: 뉴스 제목 (토스트 표시용)
 */
export interface NewsHitEvent {
  codes: string[];
  names: string[];
  scores: number[];
  boost_scores: number[];
  title: string;
  matched_keywords?: string[];  // 매칭된 호재 키워드 (백엔드 매칭 단계에서 전달 — P10 SSOT)
}

export interface AccountUpdateEvent {
  freshness?: FreshnessMetadata;
  snapshot: AccountSnapshot;
  changed_positions?: Position[];
  removed_codes?: string[];
}

/**
 * account-summary-update 이벤트 — 수익현황 페이지 전용 경량화 payload (P23 일관성).
 * 백엔드 `_build_lightweight_payload_for_profit_overview`와 계약 일치:
 * - snapshot: 7필드 경량화 (deposit, orderable, accumulated_investment, initial_deposit,
 *   total_eval_amount, total_pnl, total_pnl_rate)
 * - changed_positions: _POSITION_CMP_KEYS 최소 필드만 (stk_cd, stk_nm, qty, avg_price,
 *   buy_amount, buy_amt, total_fee, tax, cur_price, buy_date)
 * - position_count: 보유 종목 수
 */
export interface AccountSummaryUpdateEvent {
  freshness?: FreshnessMetadata;
  snapshot: Partial<AccountSnapshot>;
  position_count: number;
  changed_positions?: Partial<Position>[];
  removed_codes?: string[];
}

/**
 * settings-changed 이벤트 — 전체/delta payload 계약 (P23 일관성).
 * 백엔드 `notify_desktop_settings_toggled`와 계약 일치:
 * - 전체 payload: AppSettings 전체 스냅샷 (외부 전체 갱신 — 텔레그램/스케줄러/엔진 재기동 등)
 * - delta payload: 변경된 키만 부분 갱신 (trading.py 시간스케줄러 토글 등 단건 변경)
 * delta는 동일 consumer(applySettingsChanged)의 부분 갱신 패턴이므로 이벤트 분리 없이
 * union 타입으로 계약 명시 (P24 단순성 — account-update 분리와 다른 구조적 정당성).
 */
export interface SettingsChangedDeltaEvent {
  _v: number;
  delta: true;
  changed: Partial<AppSettings>;
}

export type SettingsChangedEvent = AppSettings | SettingsChangedDeltaEvent;

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
