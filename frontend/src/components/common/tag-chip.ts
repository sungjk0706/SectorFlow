/**
 * 공통 태그 칩 입력 컴포넌트 — 키워드 편집 (추가/삭제).
 *
 * 일반설정 자동매매 탭 "실시간 뉴스 설정" 섹션에서 호재 키워드 편집에 사용.
 * - 입력 필드 + 추가 버튼 + 칩 나열(× 삭제)
 * - Enter 또는 추가 버튼 시 신규 칩 추가, × 클릭 시 삭제
 * - 중복 키워드 방지
 * - 칩 색상: COLOR.up/upBg (호재 직관적 표현, P23 일관성)
 *
 * P23(일관된 통일성) + P24(단순성) + P25(격리된 실패) 준수.
 */

import { FONT_SIZE, FONT_WEIGHT, COLOR } from './ui-styles'

export interface TagChipHandle {
  /** 루트 요소 (설정 행에 appendChild) */
  el: HTMLElement
  /** 외부에서 태그 목록 강제 갱신 (설정 동기화 시 사용) */
  setTags: (tags: string[]) => void
}

/**
 * 태그 칩 입력 컴포넌트 생성.
 * @param initialTags 초기 태그 목록
 * @param onChange 태그 목록 변경 콜백 (추가/삭제 시 즉시 호출)
 */
export function createTagChip(options: {
  initialTags: string[]
  onChange: (tags: string[]) => void
}): TagChipHandle {
  let tags: string[] = [...options.initialTags]

  const el = document.createElement('div')
  Object.assign(el.style, {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: '6px',
    padding: '6px 0',
  })

  // 칩 컨테이너 (칩들 + 입력 필드가 같은 flex 행에 나열)
  const chipContainer = document.createElement('div')
  chipContainer.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:6px;flex:1;min-width:0;'
  el.appendChild(chipContainer)

  // 입력 필드
  const input = document.createElement('input')
  input.type = 'text'
  input.placeholder = '키워드 입력 후 Enter'
  Object.assign(input.style, {
    fontSize: FONT_SIZE.body,
    padding: '4px 8px',
    border: '1px solid ' + COLOR.border,
    borderRadius: '4px',
    background: COLOR.white,
    color: COLOR.neutral,
    width: '160px',
    minWidth: '120px',
  })

  // 추가 버튼
  const addBtn = document.createElement('button')
  addBtn.type = 'button'
  addBtn.textContent = '추가'
  Object.assign(addBtn.style, {
    fontSize: FONT_SIZE.label,
    padding: '4px 12px',
    border: '1px solid ' + COLOR.up,
    borderRadius: '4px',
    background: COLOR.upBg,
    color: COLOR.up,
    cursor: 'pointer',
  })

  function emitChange(): void {
    try { options.onChange([...tags]) } catch (e) { console.error('[TagChip] onChange error', e) }
  }

  function addTag(raw: string): void {
    const t = raw.trim()
    if (!t) return
    if (tags.includes(t)) { input.value = ''; return }
    tags.push(t)
    renderChips()
    input.value = ''
    emitChange()
  }

  function removeTag(idx: number): void {
    tags.splice(idx, 1)
    renderChips()
    emitChange()
  }

  function renderChips(): void {
    // 기존 칩 요소만 제거 (입력 필드/추가 버튼은 보존)
    const preserved: HTMLElement[] = []
    for (const child of Array.from(chipContainer.children)) {
      if (child === input || child === addBtn) preserved.push(child as HTMLElement)
    }
    while (chipContainer.firstChild) chipContainer.removeChild(chipContainer.firstChild)

    for (let i = 0; i < tags.length; i++) {
      const chip = document.createElement('span')
      Object.assign(chip.style, {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        fontSize: FONT_SIZE.body,
        fontWeight: FONT_WEIGHT.normal,
        color: COLOR.up,
        background: COLOR.upBg,
        border: '1px solid ' + COLOR.up,
        borderRadius: '12px',
        padding: '2px 8px 2px 10px',
        whiteSpace: 'nowrap',
      })
      const text = document.createElement('span')
      text.textContent = tags[i]
      chip.appendChild(text)

      const xBtn = document.createElement('button')
      xBtn.type = 'button'
      xBtn.textContent = '×'
      Object.assign(xBtn.style, {
        border: 'none',
        background: 'transparent',
        color: COLOR.up,
        cursor: 'pointer',
        fontSize: FONT_SIZE.body,
        fontWeight: FONT_WEIGHT.semibold,
        padding: '0 2px',
        lineHeight: '1',
      })
      const idx = i
      xBtn.addEventListener('click', () => {
        try { removeTag(idx) } catch (e) { console.error('[TagChip] remove error', e) }
      })
      chip.appendChild(xBtn)
      chipContainer.appendChild(chip)
    }

    // 입력 필드 + 추가 버튼을 칩 행 끝에 배치
    chipContainer.appendChild(input)
    chipContainer.appendChild(addBtn)
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      addTag(input.value)
    }
  })
  addBtn.addEventListener('click', () => {
    try { addTag(input.value) } catch (e) { console.error('[TagChip] add error', e) }
  })

  function setTags(newTags: string[]): void {
    tags = [...newTags]
    renderChips()
  }

  renderChips()

  return { el, setTags }
}
