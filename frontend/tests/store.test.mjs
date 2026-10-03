import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup() {
  const pushes = new Map(), calls = [], errors = [], snapshot = deferred()
  const runtime = {
    useSyncExternalStore: (_subscribe, read) => read(),
    api: (method, ...args) => {
      calls.push({ method, args })
      return method === "hub_snapshot" ? snapshot.promise : Promise.resolve()
    },
    onPush: (name, fn) => pushes.set(name, fn),
    t: key => key, notify: { error: (...args) => errors.push(args) },
  }
  const mod = await loadModule("../src/lib/store.ts", runtime)
  return { ...mod, calls, errors, snapshot, push: data => pushes.get("hub")(data), runtime }
}

test("nested queued edits retain confirmed normalization and exclude failed earlier edits", async () => {
  const { store, optimistic } = await setup()
  store.set("hosts", { background: { refresh_enabled: false, check_enabled: false, interval: 60 } })
  const first = deferred(), second = deferred()
  const nested = patch => value => ({ background: { ...value.background, ...patch } })
  const a = optimistic("hosts", nested({ refresh_enabled: true }), () => first.promise)
  const failed = assert.rejects(a, /failed/)
  const b = optimistic("hosts", nested({ check_enabled: true }), () => {
    assert.deepEqual(store.confirmed("hosts").background, { refresh_enabled: false, check_enabled: false, interval: 60 })
    return second.promise
  })
  assert.equal(store.get("hosts").background.refresh_enabled, true)
  first.reject(new Error("failed"))
  await failed
  await settle()
  assert.deepEqual(store.get("hosts").background, { refresh_enabled: false, check_enabled: true, interval: 60 })
  second.resolve({ background: { refresh_enabled: false, check_enabled: true, interval: 300 } })
  await b
  assert.equal(store.get("hosts").background.interval, 300)
})

test("queued edits stay visible while backend mutations execute in order", async () => {
  const { store, optimistic, calls } = await setup()
  store.set("proxy", { mode: "pac", autostart: false, running: false })
  const first = deferred(), second = deferred(), started = []
  const a = optimistic("proxy", { autostart: true }, () => { started.push("a"); return first.promise })
  const b = optimistic("proxy", { mode: "split" }, () => { started.push("b"); return second.promise })
  assert.deepEqual(store.get("proxy"), { mode: "split", autostart: true, running: false })
  await settle()
  assert.deepEqual(started, ["a"])
  first.resolve({ mode: "pac", autostart: true, running: false })
  await a
  assert.equal(store.get("proxy").mode, "split")
  await settle()
  assert.deepEqual(started, ["a", "b"])
  assert.equal(calls.filter(c => c.method === "hub_refresh").length, 0)
  second.resolve({ mode: "split", autostart: true, running: false })
  await b
  assert.equal(store.pending("proxy"), false)
  assert.deepEqual(store.get("proxy"), { mode: "split", autostart: true, running: false })
  assert.equal(calls.filter(c => c.method === "hub_refresh").length, 1)
})

test("failure rolls back its own edit while preserving a later edit", async () => {
  const { store, optimistic, errors } = await setup()
  store.set("tg", { autostart: false, fallback_cfproxy: false })
  const first = deferred(), second = deferred()
  const a = optimistic("tg", { autostart: true }, () => first.promise)
  const rejected = assert.rejects(a, /failed/)
  const b = optimistic("tg", { fallback_cfproxy: true }, () => second.promise)
  first.reject(new Error("failed"))
  await rejected
  assert.deepEqual(store.get("tg"), { autostart: false, fallback_cfproxy: true })
  second.resolve({ autostart: false, fallback_cfproxy: true })
  await b
  assert.equal(errors.length, 1)
  assert.deepEqual(store.get("tg"), { autostart: false, fallback_cfproxy: true })
})

test("a later failure retains the earlier successful change", async () => {
  const { store, optimistic } = await setup()
  store.set("proxy", { mode: "pac", autostart: false })
  const second = deferred()
  const a = optimistic("proxy", { autostart: true }, async () => ({ autostart: true }))
  const b = optimistic("proxy", { mode: "split" }, () => second.promise)
  const rejected = assert.rejects(b, /failed/)
  await a
  second.reject(new Error("failed"))
  await rejected
  assert.deepEqual(store.get("proxy"), { mode: "pac", autostart: true })
})

test("different module queues progress independently", async () => {
  const { store, optimistic } = await setup()
  const pending = deferred()
  const slow = optimistic("hosts", { enabled: true }, () => pending.promise)
  await optimistic("proxy", { autostart: true }, async () => ({ autostart: true }))
  assert.equal(store.pending("hosts"), true)
  assert.equal(store.pending("proxy"), false)
  pending.resolve({ enabled: true })
  await slow
})

test("startup snapshot cannot overwrite a newer push or queued edit", async () => {
  const { store, optimistic, loadSnapshot, snapshot, push } = await setup()
  const loading = loadSnapshot()
  push({ key: "proxy", data: { mode: "split" } })
  const pending = deferred()
  const saving = optimistic("tg", { autostart: true }, () => pending.promise)
  snapshot.resolve({ proxy: { mode: "pac" }, tg: { autostart: false }, hosts: { enabled: false } })
  await loading
  assert.deepEqual(store.get("proxy"), { mode: "split" })
  assert.deepEqual(store.get("tg"), { autostart: true })
  assert.deepEqual(store.get("hosts"), { enabled: false })
  push({ key: "tg", data: { autostart: false }, error: "old" })
  assert.deepEqual(store.get("tg"), { autostart: true })
  assert.equal(store.error("tg"), null)
  pending.resolve({ autostart: true })
  await saving
})

test("writes without state replies remain confirmed and quiet failures do not toast", async () => {
  const { store, optimistic, errors } = await setup()
  store.set("hosts", { background: { check_enabled: false } })
  await optimistic("hosts", { background: { check_enabled: true } }, async () => ({ check_enabled: true }), { applyResult: false })
  assert.deepEqual(store.get("hosts"), { background: { check_enabled: true } })
  await assert.rejects(optimistic("proxy", null, async () => { throw new Error("bad link") }, { notifyError: false }), /bad link/)
  assert.equal(errors.length, 0)
})

test("late hub replies cannot undo a completed write or publish its obsolete error", async () => {
  const { store, optimistic, push } = await setup()
  const before = Date.now() / 1000 - 1
  store.set("proxy", { mode: "pac" })
  await optimistic("proxy", { mode: "split" }, async () => ({ mode: "split" }))
  push({ key: "proxy", data: { mode: "pac" }, error: "obsolete", ts: before })
  assert.deepEqual(store.get("proxy"), { mode: "split" })
  assert.equal(store.error("proxy"), null)
  push({ key: "proxy", data: { mode: "tun" }, ts: Date.now() / 1000 + 1 })
  assert.deepEqual(store.get("proxy"), { mode: "tun" })
})

test("out-of-order hub replies retain the newest received state", async () => {
  const { store, push } = await setup()
  push({ key: "proxy", data: { mode: "split" }, ts: 200 })
  push({ key: "proxy", data: { mode: "pac" }, error: "old", ts: 100 })
  assert.deepEqual(store.get("proxy"), { mode: "split" })
  assert.equal(store.error("proxy"), null)
  push({ key: "hosts", data: { enabled: true }, ts: 100 })
  assert.equal(store.get("hosts").enabled, true)
})

test("failed writes also exclude hub replies sampled before rollback", async () => {
  const { store, optimistic, push } = await setup()
  const before = Date.now() / 1000 - 1
  store.set("proxy", { mode: "pac" })
  await assert.rejects(optimistic("proxy", { mode: "split" }, async () => {
    throw new Error("save failed")
  }), /save failed/)
  push({ key: "proxy", data: { mode: "split" }, ts: before })
  assert.deepEqual(store.get("proxy"), { mode: "pac" })
})
