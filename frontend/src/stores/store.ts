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
    const nextPartial = typeof partial === 'function' ? partial(state) : partial

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

    for (const listener of listeners) {
      listener(state)
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
