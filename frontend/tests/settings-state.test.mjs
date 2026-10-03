import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup() {
  const calls = [], errors = []
  const runtime = {
    useSyncExternalStore: (_subscribe, read) => read(), onPush() {}, t: key => key,
    notify: { error: (...args) => errors.push(args), success() {} },
    api: (method, ...args) => {
      if (method === "hub_refresh") return Promise.resolve()
      const d = deferred()
      calls.push({ method, args, ...d })
      return d.promise
    },
  }
  const state = await loadModule("../src/lib/store.ts", runtime)
  const settings = await loadModule("../src/pages/settings/state.ts", { ...runtime, ...state, fmtNum: String })
  state.store.set(settings.CONFIG_KEY, { auto_elevate: false, close_to_tray: false })
  return { ...state, ...settings, calls, errors }
}

test("a stale autostart read cannot undo a completed toggle", async () => {
  const { store, AUTOSTART_KEY, refreshAutostart, toggleAutostart, calls } = await setup()
  store.set(AUTOSTART_KEY, { supported: true, enabled: false })
  const reading = refreshAutostart()
  const saving = toggleAutostart(true)
  calls.find(c => c.method === "autostart_set").resolve({ enabled: true })
  await saving
  calls.find(c => c.method === "autostart_get").resolve({ supported: true, enabled: false })
  await reading
  assert.equal(store.get(AUTOSTART_KEY).enabled, true)
})

test("a stale config read cannot undo a completed setting change", async () => {
  const { store, CONFIG_KEY, refreshConfig, setConfig, calls } = await setup()
  const reading = refreshConfig()
  const saving = setConfig("auto_elevate", true)
  await settle()
  calls.find(c => c.method === "config_set").resolve({ auto_elevate: true, close_to_tray: false })
  await saving
  calls.find(c => c.method === "config_read").resolve({ auto_elevate: false, close_to_tray: false })
  await reading
  assert.equal(store.get(CONFIG_KEY).auto_elevate, true)
})

test("two distinct setting changes keep both optimistic values and serialize saves", async () => {
  const { store, CONFIG_KEY, setConfig, calls } = await setup()
  const first = setConfig("auto_elevate", true)
  const second = setConfig("close_to_tray", true)
  assert.deepEqual(store.get(CONFIG_KEY), { auto_elevate: true, close_to_tray: true })
  await settle()
  assert.equal(calls.length, 1)
  calls[0].resolve({ auto_elevate: true, close_to_tray: false })
  await first
  assert.deepEqual(store.get(CONFIG_KEY), { auto_elevate: true, close_to_tray: true })
  await settle()
  calls[1].resolve({ auto_elevate: true, close_to_tray: true })
  await second
})
