import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup() {
  const values = new Map(), pushes = new Map(), calls = [], dialogs = [], notifications = []
  const runtime = {
    store: { get: key => values.get(key), set: (key, value) => values.set(key, value) },
    api: (method, ...args) => {
      const reply = deferred()
      calls.push({ method, args, ...reply })
      return reply.promise
    },
    onPush: (name, fn) => pushes.set(name, fn),
    confirmDialog: options => { const reply = deferred(); dialogs.push({ options, ...reply }); return reply.promise },
    t: key => key,
    notify: Object.fromEntries(["error", "info", "success", "warning"].map(name => [name, (...args) => notifications.push([name, ...args])])),
  }
  const mod = await loadModule("../src/pages/settings/sources.ts", runtime)
  const initial = [
    { name: "A", kind: "tag", current: "1", update: true, updatable: true },
    { name: "B", kind: "tag", current: "1", update: true, updatable: true },
  ]
  runtime.store.set(mod.SOURCES_KEY, initial)
  return { ...mod, values, calls, dialogs, notifications, initial, push: value => pushes.get("srcChecked")({ _request_id: calls.findLast(c => c.method === "upstream_check_updates")?.args[0], ...value }), store: runtime.store }
}

test("late local versions cannot erase a completed remote check", async () => {
  const s = await setup()
  const read = s.refreshSources()
  const check = s.checkOne("A")
  s.calls.find(c => c.method === "upstream_check_one").resolve({ ...s.initial[0], latest: "2", update: true })
  await check
  s.calls.find(c => c.method === "upstream_versions").resolve(s.initial)
  await read
  assert.equal(s.store.get(s.SOURCES_KEY).find(x => x.name === "A").latest, "2")
})

test("the last local versions request wins even if older reads finish later", async () => {
  const s = await setup()
  const old = s.refreshSources(), fresh = s.refreshSources()
  s.calls[1].resolve([{ ...s.initial[0], current: "3" }])
  await fresh
  s.calls[0].resolve([{ ...s.initial[0], current: "1" }])
  await old
  assert.equal(s.store.get(s.SOURCES_KEY)[0].current, "3")
})

test("a bulk check cannot release or overwrite an update started after its streamed result", async () => {
  const s = await setup()
  const all = s.checkAll()
  await settle()
  s.push({ ...s.initial[0], latest: "2" })
  const updating = s.updateOneConfirm("A")
  s.dialogs[0].resolve(true)
  await settle()
  assert.equal(s.store.get(s.BUSY_KEY).A, "update")
  s.calls.find(c => c.method === "upstream_check_updates").resolve(s.initial)
  await all
  assert.equal(s.store.get(s.BUSY_KEY).A, "update")
  assert.equal(s.store.get(s.SOURCES_KEY).find(x => x.name === "A").latest, "2")
  s.calls.find(c => c.method === "upstream_update").resolve({ ...s.initial[0], current: "2", update: false })
  await updating
  assert.equal(s.store.get(s.SOURCES_KEY).find(x => x.name === "A").current, "2")
})

test("a bulk check preserves another row's pre-existing operation", async () => {
  const s = await setup()
  const one = s.checkOne("A")
  const all = s.checkAll()
  await settle()
  s.push({ ...s.initial[0], latest: "obsolete" })
  s.calls.find(c => c.method === "upstream_check_updates").resolve(s.initial)
  await all
  assert.equal(s.store.get(s.BUSY_KEY).A, "check")
  s.calls.find(c => c.method === "upstream_check_one").resolve({ ...s.initial[0], latest: "3" })
  await one
  assert.equal(s.store.get(s.SOURCES_KEY).find(x => x.name === "A").latest, "3")
})

test("duplicate bulk checks share one request across page remounts", async () => {
  const s = await setup()
  const first = s.checkAll(), second = s.checkAll()
  await settle()
  assert.equal(s.calls.length, 1)
  s.calls[0].resolve(s.initial)
  await Promise.all([first, second])
})

test("duplicate confirmation clicks reserve one source until cancellation", async () => {
  const s = await setup()
  const first = s.updateOneConfirm("A"), second = s.updateOneConfirm("A")
  assert.equal(s.dialogs.length, 1)
  s.dialogs[0].resolve(false)
  await Promise.all([first, second])
  const retry = s.updateOneConfirm("A")
  assert.equal(s.dialogs.length, 2)
  s.dialogs[1].resolve(false)
  await retry
})

test("strategy confirmation includes its warning in either language", async () => {
  const s = await setup()
  const name = "Strategies (Flowseal)"
  s.store.set(s.SOURCES_KEY, [{ name, kind: "tag", repo: "https://github.com/Flowseal/zapret-discord-youtube", update: true, updatable: true }])
  const pending = s.updateOneConfirm(name)
  assert.match(s.dialogs[0].options.description, /settings.src.confirmStrategies/)
  s.dialogs[0].resolve(false)
  await pending
})

test("a late stream from the previous bulk request cannot enter the next check", async () => {
  const s = await setup()
  const first = s.checkAll()
  await settle()
  const oldId = s.calls[0].args[0]
  s.calls[0].resolve(s.initial)
  await first
  const second = s.checkAll()
  await settle()
  assert.notEqual(s.calls[1].args[0], oldId)
  s.push({ ...s.initial[0], latest: "obsolete", _request_id: oldId })
  assert.equal(s.store.get(s.SOURCES_KEY)[0].latest, undefined)
  assert.equal(s.store.get(s.BUSY_KEY).A, "check")
  s.push({ ...s.initial[0], latest: "2" })
  assert.equal(s.store.get(s.SOURCES_KEY)[0].latest, "2")
  s.calls[1].resolve([{ ...s.initial[0], latest: "2" }, s.initial[1]])
  await second
})

test("opening settings again retains checked status if the installed version did not change", async () => {
  const s = await setup()
  const check = s.checkOne("A")
  s.calls[0].resolve({ ...s.initial[0], latest: "2" })
  await check
  const read = s.refreshSources()
  s.calls[1].resolve([{ name: "A", kind: "tag", version: "1", updatable: true }])
  await read
  assert.equal(s.store.get(s.SOURCES_KEY)[0].latest, "2")
  assert.equal(s.store.get(s.SOURCES_KEY)[0].update, true)
})
