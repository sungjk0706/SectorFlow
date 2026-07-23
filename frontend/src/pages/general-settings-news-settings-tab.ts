// frontend/src/pages/general-settings-news-settings-tab.ts
// 일반설정 — 뉴스 설정 탭 (Step 2 신설, P21/P24)
// 자동매매 탭에서 이관: 호재 키워드 칩 + 뉴스 가산점 유지 시간 (NWS-S6)

import { createNumInput } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { createTagChip } from '../components/common/tag-chip'
import { FONT_WEIGHT } from '../components/common/ui-styles'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, GS, state } from './general-settings-shared'

// 호재 키워드 칩 행 — news_keywords 쉼표 문자열 ↔ 칩 배열 변환
function buildNewsKeywordsRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { padding: GS.rowPad, borderBottom: GS.rowBorder })

  const label = document.createElement('div')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal, marginBottom: '4px' })
  label.textContent = '호재 키워드'
  row.appendChild(label)

  const initialKeywords = String(state.vals.news_keywords ?? '')
    .split(',')
    .map(s => s.trim())
    .filter(s => s.length > 0)
  state.newsKeywordsTagChip = createTagChip({
    initialTags: initialKeywords,
    onChange: async (tags) => {
      if (!state.settingsMgr) return
      const joined = tags.join(',')
      const dirty: Record<string, unknown> = { news_keywords: joined }
      const res = await state.settingsMgr.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(state.vals, dirty)
    },
  })
  row.appendChild(state.newsKeywordsTagChip.el)
  return row
}

// 뉴스 가산점 유지 시간(초) 행 — createNumInput 패턴 (subscribeMaxInput과 동일)
function buildNewsTtlRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '뉴스 가산점 유지 시간(초)'
  row.appendChild(label)

  const initTtl = Number(state.vals.news_boost_ttl_sec ?? 300) || 300
  state.newsTtlInput = createNumInput({
    value: initTtl,
    min: 0, max: 3600, step: 60,
    name: 'news_boost_ttl_sec',
    onChange: async (v) => {
      if (!state.settingsMgr) return
      const dirty: Record<string, unknown> = { news_boost_ttl_sec: v }
      const res = await state.settingsMgr.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(state.vals, dirty)
    },
  })
  row.appendChild(state.newsTtlInput.el)
  return row
}

export function renderNewsSettingsTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(sectionTitle('실시간 뉴스 설정'))
  container.appendChild(createDescText('뉴스 제목에 포함된 호재 키워드 감지 시 매수 가산점 부여. 키워드는 쉼표로 구분하여 입력.'))
  container.appendChild(buildNewsKeywordsRow(state))
  container.appendChild(buildNewsTtlRow(state))
}

export function syncNewsSettingsTab(r: Record<string, unknown>): void {
  const keywords = String(r.news_keywords ?? '')
    .split(',')
    .map(s => s.trim())
    .filter(s => s.length > 0)
  state.newsKeywordsTagChip?.setTags(keywords)
  state.newsTtlInput?.setValue(Number(r.news_boost_ttl_sec ?? 300) || 300)
}
