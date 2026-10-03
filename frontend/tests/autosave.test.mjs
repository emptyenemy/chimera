import assert from "node:assert/strict"
import test from "node:test"
import { loadModule } from "./helpers.mjs"

async function setup() {
  const timers = new Map(), cleanups = []
  let next = 0
  globalThis.window = { setTimeout: fn => { timers.set(++next, fn); return next } }
  globalThis.clearTimeout = id => timers.delete(id)
  const mod = await loadModule("../src/lib/use-autosave.ts", {
    useRef: current => ({ current }), useCallback: fn => fn,
    useEffect: fn => { const cleanup = fn(); if (cleanup) cleanups.push(cleanup) },
    useState: value => [value, () => {}],
  })
  return { ...mod, timers, unmount: () => cleanups.forEach(fn => fn()) }
}

test("leaving a page flushes its unsaved debounce exactly once", async () => {
  const { useDebounced, timers, unmount } = await setup()
  let saves = 0
  const { schedule } = useDebounced(() => saves++)
  schedule()
  schedule()
  assert.equal(timers.size, 1)
  assert.equal(saves, 0)
  unmount()
  assert.equal(saves, 1)
  assert.equal(timers.size, 0)
  unmount()
  assert.equal(saves, 1)
})

test("an explicit flush leaves nothing to save on unmount", async () => {
  const { useDebounced, timers, unmount } = await setup()
  let saves = 0
  const { schedule, flush } = useDebounced(() => saves++)
  schedule()
  flush()
  flush()
  unmount()
  assert.equal(saves, 1)
  assert.equal(timers.size, 0)
})
