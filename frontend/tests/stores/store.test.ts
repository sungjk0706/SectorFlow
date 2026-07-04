import { describe, it, expect } from 'vitest'
import { createStore } from '../../src/stores/store'

interface TestState {
  count: number
  name: string
}

describe('createStore', () => {
  it('returns initial state via getState', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    expect(store.getState()).toEqual({ count: 0, name: 'test' })
  })

  it('updates state via setState with partial object', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    store.setState({ count: 5 })
    expect(store.getState().count).toBe(5)
    expect(store.getState().name).toBe('test')
  })

  it('updates state via setState with function', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    store.setState((state) => ({ count: state.count + 10 }))
    expect(store.getState().count).toBe(10)
  })

  it('notifies subscribers on state change', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    let calls = 0
    store.subscribe(() => { calls++ })
    store.setState({ count: 1 })
    expect(calls).toBe(1)
  })

  it('does not notify subscribers when value is unchanged', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    let calls = 0
    store.subscribe(() => { calls++ })
    store.setState({ count: 0 })
    expect(calls).toBe(0)
  })

  it('does not notify when Object.is returns true for all keys', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    let calls = 0
    store.subscribe(() => { calls++ })
    store.setState({ count: 0, name: 'test' })
    expect(calls).toBe(0)
  })

  it('notifies when at least one key changed', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    let calls = 0
    store.subscribe(() => { calls++ })
    store.setState({ count: 0, name: 'changed' })
    expect(calls).toBe(1)
  })

  it('unsubscribe stops receiving notifications', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    let calls = 0
    const unsub = store.subscribe(() => { calls++ })
    store.setState({ count: 1 })
    expect(calls).toBe(1)
    unsub()
    store.setState({ count: 2 })
    expect(calls).toBe(1)
  })

  it('multiple subscribers all receive notifications', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    let calls1 = 0
    let calls2 = 0
    store.subscribe(() => { calls1++ })
    store.subscribe(() => { calls2++ })
    store.setState({ count: 1 })
    expect(calls1).toBe(1)
    expect(calls2).toBe(1)
  })

  it('merges partial state preserving other keys', () => {
    const store = createStore<TestState>({ count: 0, name: 'test' })
    store.setState({ count: 5 })
    store.setState({ name: 'updated' })
    expect(store.getState()).toEqual({ count: 5, name: 'updated' })
  })
})
