import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup() {
  const calls = [], errors = []
  const api = (method, ...args) => {
    if (method === "hub_refresh") return Promise.resolve()
    const request = deferred()
    calls.push({ method, args, ...request })
    return request.promise
  }
  const t = key => key, notify = { error: (...args) => errors.push(args) }
  const { store, optimistic } = await loadModule("../src/lib/store.ts", { api, onPush: () => {}, t, notify })
  const mod = await loadModule("../src/pages/strategy-filters.ts", { api, store, optimistic, t, notify })
  const initial = { game: "all", game_ranges: { tcp: "80", udp: "90" }, ipset: "none" }
  store.set("filters", initial)
  const reply = (index, patch = {}) => calls[index].resolve({ ...initial, ...patch })
  return { ...mod, store, optimistic, api, calls, errors, reply, drafts: () => store.get(mod.RANGE_DRAFTS_KEY) ?? {} }
}

test("a late range acknowledgement preserves newer unsubmitted text", async () => {
  const s = await setup()
  s.editRange("tcp", "8000")
  const saving = s.commitRange("tcp")
  await settle()
  s.editRange("tcp", "9000")
  s.reply(0, { game_ranges: { tcp: "8000", udp: "90" } })
  await saving
  assert.equal(s.drafts().tcp.value, "9000")
  assert.equal(s.drafts().tcp.status, "dirty")
})

test("range edits share the filter queue and use the last confirmed mode", async () => {
  const s = await setup()
  const mode = s.optimistic("filters", { game: "udp" }, () => s.api("game_filter_set", "udp"))
  s.editRange("udp", "9000")
  const saving = s.commitRange("udp")
  await settle()
  s.reply(0, { game: "udp" })
  await mode
  await settle()
  assert.deepEqual(s.calls[1].args, ["udp", null, "9000"])
  s.reply(1, { game: "udp", game_ranges: { tcp: "80", udp: "9000" } })
  await saving
  assert.equal(s.store.get("filters").game, "udp")
})

test("blur, unmount and repeated commits do not duplicate a submitted range", async () => {
  const s = await setup()
  s.editRange("tcp", "8000")
  const saving = s.commitRange("tcp")
  await s.commitRange("tcp")
  await s.flushRanges()
  await settle()
  assert.equal(s.calls.length, 1)
  s.reply(0, { game_ranges: { tcp: "8000", udp: "90" } })
  await saving
  await s.commitRange("tcp")
  assert.equal(s.calls.length, 1)
})

test("a failed TCP edit does not poison a queued UDP edit", async () => {
  const s = await setup()
  s.editRange("tcp", "8000")
  const tcp = s.commitRange("tcp")
  s.editRange("udp", "9000")
  const udp = s.commitRange("udp")
  await settle()
  assert.equal(s.calls.length, 1)
  s.calls[0].reject(new Error("disk failure"))
  await tcp
  await settle()
  assert.deepEqual(s.calls[1].args, ["all", null, "9000"])
  assert.equal(s.drafts().tcp.error, "disk failure")
  s.reply(1, { game_ranges: { tcp: "80", udp: "9000" } })
  await udp
  assert.equal(s.store.get("filters").game_ranges.tcp, "80")
  assert.equal(s.drafts().tcp.value, "8000")
})

test("reverting to the original range while another value saves still writes the final intent", async () => {
  const s = await setup()
  s.editRange("tcp", "8000")
  const first = s.commitRange("tcp")
  s.editRange("tcp", "80")
  const last = s.commitRange("tcp")
  await settle()
  s.reply(0, { game_ranges: { tcp: "8000", udp: "90" } })
  await first
  await settle()
  assert.deepEqual(s.calls[1].args, ["all", "80", null])
  s.reply(1)
  await last
  assert.equal(s.store.get("filters").game_ranges.tcp, "80")
  assert.equal(s.drafts().tcp, undefined)
})

test("reset deduplicates clicks and preserves text entered during its reply", async () => {
  const s = await setup()
  const reset = s.resetRanges()
  await s.resetRanges()
  await settle()
  assert.equal(s.calls.length, 1)
  s.editRange("tcp", "9000")
  s.reply(0, { game_ranges: { tcp: s.GAME_RANGE_DEFAULT, udp: s.GAME_RANGE_DEFAULT } })
  await reset
  assert.equal(s.drafts().tcp.value, "9000")
  assert.equal(s.drafts().udp, undefined)
})

test("invalid drafts stay local and failed drafts can be retried after navigation", async () => {
  const s = await setup()
  s.editRange("tcp", "80-")
  await s.flushRanges()
  assert.equal(s.calls.length, 0)
  assert.equal(s.drafts().tcp.status, "error")
  s.editRange("tcp", "8 000")
  const saving = s.flushRanges()
  await settle()
  assert.deepEqual(s.calls[0].args, ["all", "8000", null])
  s.calls[0].reject(new Error("offline"))
  await saving
  assert.equal(s.drafts().tcp.value, "8 000")
  assert.equal(s.drafts().tcp.error, "offline")
  await s.flushRanges()
  assert.equal(s.calls.length, 1)
  const retry = s.commitRange("tcp")
  await settle()
  s.reply(1, { game_ranges: { tcp: "8000", udp: "90" } })
  await retry
  assert.equal(s.drafts().tcp, undefined)
})


test("a failed mode switch cannot leak its optimistic mode into a queued range", async () => {
  const s = await setup()
  const mode = s.optimistic("filters", { game: "udp" }, () => s.api("game_filter_set", "udp"))
  const rejected = assert.rejects(mode, /failed/)
  s.editRange("udp", "8000")
  const saving = s.commitRange("udp")
  await settle()
  s.calls[0].reject(new Error("failed"))
  await rejected
  await settle()
  assert.deepEqual(s.calls[1].args, ["all", null, "8000"])
  s.reply(1, { game_ranges: { tcp: "80", udp: "8000" } })
  await saving
  assert.equal(s.store.get("filters").game, "all")
})

test("an older failed range cannot mark newer unsaved text as failed", async () => {
  const s = await setup()
  s.editRange("tcp", "8000")
  const saving = s.commitRange("tcp")
  await settle()
  s.editRange("tcp", "9000")
  s.calls[0].reject(new Error("offline"))
  await saving
  assert.equal(s.drafts().tcp.value, "9000")
  assert.equal(s.drafts().tcp.status, "dirty")
  assert.equal(s.drafts().tcp.error, undefined)
})

test("a failed reset remains editable and does not retry itself on unmount", async () => {
  const s = await setup()
  const saving = s.resetRanges()
  await settle()
  s.calls[0].reject(new Error("offline"))
  await saving
  assert.equal(s.store.get(s.RANGE_RESET_KEY), false)
  assert.equal(s.drafts().udp.value, s.GAME_RANGE_DEFAULT)
  assert.equal(s.drafts().udp.status, "error")
  await s.flushRanges()
  assert.equal(s.calls.length, 1)
  const retry = s.commitRange("udp")
  await settle()
  s.reply(1, { game_ranges: { tcp: "80", udp: s.GAME_RANGE_DEFAULT } })
  await retry
  assert.equal(s.drafts().udp, undefined)
  assert.equal(s.drafts().tcp.status, "error")
})

test("unchanged and discarded ranges do not write or discard the other protocol", async () => {
  const s = await setup()
  s.editRange("tcp", " 80 ")
  await s.commitRange("tcp")
  assert.equal(s.calls.length, 0)
  s.editRange("tcp", "invalid")
  s.editRange("udp", "9000")
  s.discardRange("tcp")
  assert.equal(s.drafts().tcp, undefined)
  assert.equal(s.drafts().udp.value, "9000")
})

test("navigation saves still report a failure to apply confirmed settings", async () => {
  const s = await setup()
  s.editRange("udp", "9000")
  const saving = s.flushRanges()
  await settle()
  s.reply(0, { game_ranges: { tcp: "80", udp: "9000" }, apply_error: "restart blocked" })
  await saving
  assert.equal(s.drafts().udp, undefined)
  assert.equal(s.store.get("filters").game_ranges.udp, "9000")
  assert.deepEqual(s.errors, [["strat.applyFailed", "restart blocked"]])
})
