// frontend/src/api/client.ts

import type { AccountSnapshot, FreshnessMetadata, Position, SectorScoreRow, SectorStock, StockScore } from '../types'

const BASE_URL = '';

function getToken(): string | null {
  return localStorage.getItem('token');
}

// B21-01 세션6: 백엔드 구조화 오류 응답(설계 5 — detail={code,message,field}) 전달.
// Error 상속 → 기존 e instanceof Error 호환. code/field는 선택적(문자열 detail 응답에는 없음).
export class ApiError extends Error {
  code?: string;
  field?: string;
  constructor(message: string, code?: string, field?: string) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.field = field;
  }
}

interface RequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  pageContext?: string;
}

export interface FreshnessResponse<T> {
  data: T;
  freshness: FreshnessMetadata;
}

export interface SectorScoresResponse {
  scores: SectorScoreRow[];
  ranked_count: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (options.pageContext) {
    headers['X-Page-Context'] = options.pageContext;
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    // 백엔드 에러 응답 본문의 detail 필드 추출 (FastAPI HTTPException 형식)
    // — P21: 사용자가 검증 실패 사유를 토스트에서 확인 가능 (예: 타임테이블 시간 순서 오류)
    // — B21-01 세션6: detail 이 객체인 경우(code/message/field) ApiError 로 전달 (P20 폴백 제거).
    //   문자열 detail 은 기존대로 Error(message) throw (하위 호환 — 비암호화 검증 오류).
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      // 본문이 JSON이 아닌 경우 status 코드만 사용 (에러 경로 처리 — P20 폴백 금지 대상 아님)
    }
    const detail = (body as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      throw new Error(detail)
    }
    if (detail && typeof detail === 'object') {
      const d = detail as { code?: string; message?: string; field?: string }
      const msg = typeof d.message === 'string' && d.message.length > 0 ? d.message : `API error: ${res.status}`
      throw new ApiError(msg, d.code, d.field)
    }
    throw new Error(`API error: ${res.status}`)
  }

  return res.json();
}

// API 함수들
export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),


  getSettings: () =>
    request<Record<string, unknown>>('/api/settings'),

  patchSettingField: (fieldName: string, value: unknown) =>
    request<{ ok: boolean }>(`/api/settings/${fieldName}`, {
      method: 'PATCH',
      body: JSON.stringify({ value }),
    }),

  resetTestData: () =>
    request<{ ok: boolean; message?: string }>('/api/test-data/reset', {
      method: 'POST',
    }),

  getBuyHistory: (tradeMode?: string, dateFrom?: string, dateTo?: string) => {
    const params = new URLSearchParams();
    if (tradeMode) params.set('trade_mode', tradeMode);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const qs = params.toString();
    return request<Record<string, unknown>[]>(`/api/trade-history/buy${qs ? `?${qs}` : ''}`);
  },

  getSellHistory: (tradeMode?: string, dateFrom?: string, dateTo?: string) => {
    const params = new URLSearchParams();
    if (tradeMode) params.set('trade_mode', tradeMode);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const qs = params.toString();
    return request<Record<string, unknown>[]>(`/api/trade-history/sell${qs ? `?${qs}` : ''}`);
  },

  wsSubscribeStart: (group: 'industry' | 'index' | 'quote') =>
    request<{ ok: boolean; status: { index_subscribed: boolean; quote_subscribed: boolean }; message?: string }>('/api/ws-subscribe/start', {
      method: 'POST',
      body: JSON.stringify({ group }),
    }),

  wsSubscribeStop: (group: 'industry' | 'index' | 'quote') =>
    request<{ ok: boolean; status: { index_subscribed: boolean; quote_subscribed: boolean }; message?: string }>('/api/ws-subscribe/stop', {
      method: 'POST',
      body: JSON.stringify({ group }),
    }),

  getTradingDay: () =>
    request<{ is_trading_day: boolean; today: string }>('/api/trading-day'),

  getAccountSnapshot: (pageContext?: string) =>
    request<FreshnessResponse<AccountSnapshot>>('/api/account/snapshot', { pageContext }),

  getAccountPositions: (pageContext?: string) =>
    request<FreshnessResponse<Position[]>>('/api/account/positions', { pageContext }),

  getBuyTargets: (pageContext?: string) =>
    request<FreshnessResponse<StockScore[]>>('/api/market/buy-targets', { pageContext }),

  getSectorScores: (pageContext?: string) =>
    request<FreshnessResponse<SectorScoresResponse>>('/api/market/sector-scores', { pageContext }),

  getSectorStocks: (pageContext?: string) =>
    request<FreshnessResponse<SectorStock[]>>('/api/market/sector-stocks', { pageContext }),

  // Health Check for modern stability pattern
  healthCheck: () =>
    request<{
      status: 'ready' | 'initializing' | 'downloading' | 'error';
      message: string;
      progress: {
        server_ready: boolean;
        engine_ready: boolean;
        bootstrap_done: boolean;
        data_loaded: boolean;
        broker_connected: boolean;
      };
      timestamp: string | null;
    }>('/api/health'),

  settlementCharge: (amount: number) =>
    request<{ ok: boolean; available_cash: number }>('/api/settlement/charge', {
      method: 'POST',
      body: JSON.stringify({ amount }),
    }),

  post: <T = { ok: boolean; message?: string }>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),

  get: <T = unknown>(path: string) =>
    request<T>(path),

  getDailySummary: (from: string, to: string, tradeMode: string, days?: number) =>
    request<Record<string, unknown>[]>(`/api/trade-history/daily-summary?date_from=${from}&date_to=${to}&trade_mode=${tradeMode}${days !== undefined ? `&days=${days}` : ''}`),

  getPrevTradingDay: () =>
    request<{ date: string }>(`/api/trade-history/prev-trading-day`),

  getStockDetail5d: () =>
    request<{
      date: string;
      items: Array<{
        code: string;
        name: string;
        market_type: string;
        nxt_enable: boolean;
        bars: Array<{
          dt: string;
          trade_amount: number | null;
          high_price: number | null;
        }>;
      }>;
    }>('/api/stock-detail/5d-array'),
};
