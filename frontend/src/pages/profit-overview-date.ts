// frontend/src/pages/profit-overview-date.ts
// 수익현황 페이지 — 날짜 범위 localStorage 영속화 (F-05 분할, P24 단순성)
// 날짜 범위는 페이지 로컬 상태로 관리 (P10 SSOT — 공유 store 오염 방지)

/* ── 날짜 범위 localStorage 영속화 ── */
export const PROFIT_DATE_KEY = 'sf_profit_date_range'

export interface ProfitDateRange {
  from: string
  to: string
  quickLabel?: string
}

// 레거시 quickLabel 마이그레이션 매핑 (P23 일관성 — 라벨 통일에 따른 기존 사용자 데이터 호환)
const LEGACY_QUICK_LABEL_MAP: Record<string, string> = {
  '전체': '누적',
  '직전': '전일',
}

export function loadProfitDateRange(): ProfitDateRange | null {
  try {
    const raw = localStorage.getItem(PROFIT_DATE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { from?: string; to?: string; quickLabel?: string }
    // quickLabel이 있는 경우(5거래일/누적 등) from/to가 빈 문자열일 수 있음
    if (parsed.quickLabel) {
      // 레거시 라벨 마이그레이션 (전체→누적, 직전→전일) — 한 번 치환 후 영구 저장
      const migrated = LEGACY_QUICK_LABEL_MAP[parsed.quickLabel] ?? parsed.quickLabel
      if (migrated !== parsed.quickLabel) {
        saveProfitDateRange(parsed.from ?? '', parsed.to ?? '', migrated)
      }
      return { from: parsed.from ?? '', to: parsed.to ?? '', quickLabel: migrated }
    }
    // 수동 날짜 범위 — from/to 유효성 검증
    if (parsed.from && parsed.to && /^\d{4}-\d{2}-\d{2}$/.test(parsed.from) && /^\d{4}-\d{2}-\d{2}$/.test(parsed.to) && parsed.from <= parsed.to) {
      return { from: parsed.from, to: parsed.to }
    }
    return null
  } catch (e) {
    console.warn('[profit-overview] 저장된 날짜 범위 로드 실패 (손상된 데이터):', e)
    return null
  }
}

export function saveProfitDateRange(from: string, to: string, quickLabel?: string): void {
  try {
    localStorage.setItem(PROFIT_DATE_KEY, JSON.stringify({ from, to, quickLabel }))
  } catch (e) {
    console.warn('[profit-overview] 날짜 범위 localStorage 저장 실패:', e)
  }
}

export function defaultDateRange(): { from: string; to: string } {
  const now = new Date()
  const from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
  const to = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return { from, to }
}

/* ── mount 헬퍼: 날짜 범위 초기화 (localStorage 로드 → 페이지 로컬 상태용 from/to 반환) ── */
export function initDateRange(): { saved: ProfitDateRange | null; from: string; to: string } {
  const saved = loadProfitDateRange()
  if (saved) {
    return { saved, from: saved.from, to: saved.to }
  }
  const { from, to } = defaultDateRange()
  saveProfitDateRange(from, to)
  return { saved: null, from, to }
}
