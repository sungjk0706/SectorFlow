// frontend/src/api/client.ts

const BASE_URL = '';

function getToken(): string | null {
  return localStorage.getItem('token');
}

interface RequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  pageContext?: string;
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
    throw new Error(`API error: ${res.status}`);
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
