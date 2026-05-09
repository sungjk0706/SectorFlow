/**
 * Vitest setup — JSDOM CSS normalization patches.
 *
 * JSDOM normalizes CSS values when reading back:
 * - `flex: 1` → `flex: 1 1 0%`
 * - `min-height: 0` → `min-height: 0px`
 *
 * These patches store the original values set via property assignment
 * and return them on read, matching developer intent.
 */

function patchStyleProperty(propName: string): void {
  const store = new WeakMap<CSSStyleDeclaration, string>()
  const el = document.createElement('div')
  const proto = Object.getPrototypeOf(el.style)
  const desc = Object.getOwnPropertyDescriptor(proto, propName)

  if (desc && desc.get && desc.set) {
    const origGet = desc.get
    const origSet = desc.set

    Object.defineProperty(proto, propName, {
      get() {
        return store.get(this) ?? origGet.call(this)
      },
      set(value: string) {
        if (value !== undefined && value !== null && value !== '') {
          store.set(this, value)
        } else {
          store.delete(this)
        }
        origSet.call(this, value)
      },
      configurable: true,
      enumerable: true,
    })
  }
}

patchStyleProperty('flex')
patchStyleProperty('minHeight')
