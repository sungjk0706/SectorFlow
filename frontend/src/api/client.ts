// frontend/src/api/client.ts

const BASE_URL = '';

function getToken(): string | null {
  return localStorage.getItem('token');
}

export function setToken(token: string): void {
  localStorage.setItem('token', token);
}

export function clearToken(): void {
  localStorage.removeItem('token');
}

/** JWT payload에서 exp 추출 (디코딩 실패 시 null) */
// TODO: 개발 완료 후 재활성화
// function getTokenExp(token: string): number | null {
//   try {
//     const payload = JSON.parse(atob(token.split('.')[1]));
//     return typeof payload.exp === 'number' ? payload.exp : null;
//   } catch {
//     return null;
//   }
// }

export function isAuthenticated(): boolean {
  // TODO: 개발 완료 후 토큰 검증 재활성화
  return true;
  // const token = getToken();
  // if (!token) return false;
  // const exp = getTokenExp(token);
  // if (!exp) return false;
  // return exp > Date.now() / 1000 + 10;
}

/** 토큰 무효화 + 로그인 화면 전환 (SSE/WS 401/403 공용) */
export function forceLogout(): void {
  // TODO: 개발 완료 후 재활성화
  console.warn('[Auth] forceLogout 호출됨 — 개발 모드에서 무시');
  // clearToken();
  // window.location.href = '/';
}

interface RequestOptions extends RequestInit {
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

  if (res.status === 401) {
    // TODO: 개발 완료 후 재활성화
    console.warn('[Auth] 401 응답 — 개발 모드에서 무시');
    // clearToken();
    // window.location.href = '/login';
  }

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

  updateSettings: (data: Record<string, unknown>) =>
    request<{ ok: boolean }>('/api/settings', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  resetTestData: () =>
    request<{ ok: boolean; message?: string }>('/api/test-data/reset', {
      method: 'POST',
    }),

  getBuyHistory: (tradeMode?: string) =>
    request<Record<string, unknown>[]>(`/api/trade-history/buy${tradeMode ? `?trade_mode=${tradeMode}` : ''}`),

  getSellHistory: (tradeMode?: string) =>
    request<Record<string, unknown>[]>(`/api/trade-history/sell${tradeMode ? `?trade_mode=${tradeMode}` : ''}`),

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
      status: 'ready' | 'initializing' | 'error';
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
};
