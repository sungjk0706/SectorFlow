// frontend/src/stores/store.ts
// zustand를 대체하는 순수 TypeScript 상태 관리 모듈

export interface StoreApi<T> {
  getState(): T
  setState(partial: Partial<T> | ((state: T) => Partial<T>)): void
  subscribe(listener: (state: T) => void): () => void
}

export function createStore<T extends object>(initialState: T): StoreApi<T> {
  let state: T = initialState
  const listeners = new Set<(state: T) => void>()

  function getState(): T {
    return state
  }

  function setState(partial: Partial<T> | ((state: T) => Partial<T>)): void {
    // updater 함수 호출을 try/catch로 격리 — updater 본문 throw 시
    // setState 호출자로 전파되어 binding.ts 핸들러 → WS 디스패치로 전파되는 것을 차단 (P25/P16).
    // 실패 시 기존 state 유지 — 잘못된 부분 상태로 교체 방지 (P22).
    // silent pass가 아님 — 에러는 콘솔에 명시 로깅 (P20).
    let nextPartial: Partial<T>
    try {
      nextPartial = typeof partial === 'function' ? partial(state) : partial
    } catch (e) {
      console.error('[Store] updater error', e)
      return
    }

    // shallow merge + Object.is 비교: 실제 변경된 키가 있을 때만 상태 교체 + 구독자 통지
    let hasChange = false
    const keys = Object.keys(nextPartial) as (keyof T)[]
    for (const key of keys) {
      if (!Object.is(state[key], nextPartial[key])) {
        hasChange = true
        break
      }
    }

    if (!hasChange) {
      return
    }

    state = { ...state, ...nextPartial }

    // listener throw가 다른 listener / setState 호출자에게 전파되어
    // 앱 전체 렌더링이 중단되는 것을 차단 (P16/P21).
    // silent pass가 아님 — 에러는 콘솔에 명시 로깅되고 다른 listener는 계속 실행.
    for (const listener of listeners) {
      try {
        listener(state)
      } catch (e) {
        console.error('[Store] listener error', e)
      }
    }
  }

  function subscribe(listener: (state: T) => void): () => void {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }

  return { getState, setState, subscribe }
}
