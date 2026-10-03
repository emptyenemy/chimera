import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup() {
  const values = new Map(), calls = [], errors = []
  const store = { get: key => values.get(key), set: (key, value) => values.set(key, value) }
  const api = (method, ...args) => { const request = deferred(); calls.push({ method, args, ...request }); return request.promise }
  const mod = await loadModule("../src/pages/dns-probe.ts", { api, store, t: key => key, notify: { error: (...args) => errors.push(args) } })
  store.set(mod.PROBE_KEY, { value: { bypass: "old.example", ad: "ad.example" }, draft: null, busy: false, error: null })
  return { ...mod, store, calls, errors, state: () => store.get(mod.PROBE_KEY) }
}

test("probe saves execute in order and older acknowledgements retain newer text", async () => {
  const s = await setup()
  s.editProbeConfig({ bypass: "FIRST.EXAMPLE" })
  const first = s.saveProbeConfig()
  s.editProbeConfig({ ad: "NEXT.EXAMPLE" })
  const second = s.saveProbeConfig()
  await settle()
  assert.equal(s.calls.length, 1)
  s.calls[0].resolve({ bypass: ["first.example"], ad: "ad.example" })
  await first
  await settle()
  assert.equal(s.state().draft.ad, "NEXT.EXAMPLE")
  assert.equal(s.state().busy, true)
  assert.deepEqual(s.calls[1].args, ["FIRST.EXAMPLE", "NEXT.EXAMPLE"])
  s.calls[1].resolve({ bypass: ["first.example"], ad: "next.example" })
  await second
  assert.deepEqual(s.state().value, { bypass: "first.example", ad: "next.example" })
  assert.equal(s.state().draft, null)
  assert.equal(s.state().busy, false)
})

test("a failed save survives page reload and can be retried", async () => {
  const s = await setup()
  s.editProbeConfig({ bypass: "recover.example" })
  const saving = s.saveProbeConfig()
  await settle()
  s.calls[0].reject(new Error("disk failure"))
  assert.equal(await saving, false)
  await s.loadProbeConfig()
  assert.equal(s.calls.length, 1)
  assert.equal(s.state().draft.bypass, "recover.example")
  assert.equal(s.state().draft.error, "disk failure")
  const retry = s.saveProbeConfig()
  await settle()
  s.calls[1].resolve({ bypass: ["recover.example"], ad: "ad.example" })
  assert.equal(await retry, true)
  assert.equal(s.state().draft, null)
})

test("an older failed save does not clear a newer queued draft", async () => {
  const s = await setup()
  s.editProbeConfig({ bypass: "first.example" })
  const first = s.saveProbeConfig()
  s.editProbeConfig({ bypass: "second.example" })
  const second = s.saveProbeConfig()
  await settle()
  s.calls[0].reject(new Error("failed"))
  await first
  await settle()
  assert.equal(s.state().draft.bypass, "second.example")
  assert.equal(s.state().draft.error, null)
  s.calls[1].resolve({ bypass: ["second.example"], ad: "ad.example" })
  await second
  assert.equal(s.state().value.bypass, "second.example")
})

test("late reads cannot revert a completed probe save", async () => {
  const s = await setup()
  const loading = s.loadProbeConfig()
  s.editProbeConfig({ ad: "new.example" })
  const saving = s.saveProbeConfig()
  await settle()
  s.calls[1].resolve({ bypass: ["old.example"], ad: "new.example" })
  await saving
  s.calls[0].resolve({ bypass: ["old.example"], ad: "ad.example" })
  await loading
  assert.equal(s.state().value.ad, "new.example")
})

test("blur and unmount deduplicate a submitted probe draft", async () => {
  const s = await setup()
  s.editProbeConfig({ ad: "new.example" })
  const first = s.saveProbeConfig(), second = s.saveProbeConfig()
  assert.equal(first, second)
  await settle()
  assert.equal(s.calls.length, 1)
  s.calls[0].resolve({ bypass: ["old.example"], ad: "new.example" })
  await first
  await s.saveProbeConfig()
  assert.equal(s.calls.length, 1)
})

test("a failed initial read can be retried instead of leaving loading forever", async () => {
  const s = await setup()
  s.store.set(s.PROBE_KEY, { value: null, draft: null, busy: false, error: null })
  const first = s.loadProbeConfig()
  s.calls[0].reject(new Error("offline"))
  await first
  assert.equal(s.state().error, "offline")
  const retry = s.loadProbeConfig()
  s.calls[1].resolve({ bypass: ["test.example"], ad: "ad.example" })
  await retry
  assert.equal(s.state().error, null)
  assert.equal(s.state().value.bypass, "test.example")
})
