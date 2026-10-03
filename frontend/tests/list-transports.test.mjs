import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup() {
  const calls = [], errors = []
  const runtime = {
    useSyncExternalStore: (_subscribe, read) => read(), onPush() {}, t: key => key,
    notify: { info() {}, error: (...args) => errors.push(args) },
    api: (method, ...args) => {
      if (method === "hub_refresh") return Promise.resolve()
      const d = deferred()
      calls.push({ method, args, ...d })
      return d.promise
    },
  }
  const state = await loadModule("../src/lib/store.ts", runtime)
  const lists = await loadModule("../src/pages/lists-data.ts", { ...runtime, ...state })
  state.store.set("proxy", { lists: [] })
  state.store.set(lists.LISTS_KEY, [{ name: "a", count: 1, proxy: false }, { name: "b", count: 1, proxy: false }])
  return { ...state, ...lists, calls, errors }
}

test("a failed list connection is excluded from a later queued connection", async () => {
  const { store, LISTS_KEY, setTransport, calls, errors } = await setup()
  const first = setTransport("a", "proxy", true)
  const second = setTransport("b", "proxy", true)
  assert.deepEqual(store.get("proxy").lists, ["a", "b"])
  assert.ok(store.get(LISTS_KEY).every(item => item.proxy))
  await settle()
  assert.deepEqual(calls[0].args, [["a"]])
  calls[0].reject(new Error("cannot apply"))
  await first
  await settle()
  assert.deepEqual(calls[1].args, [["b"]])
  assert.deepEqual(store.get(LISTS_KEY).map(item => item.proxy), [false, true])
  calls[1].resolve({ lists: ["b"] })
  await second
  assert.deepEqual(store.get("proxy").lists, ["b"])
  assert.equal(errors.length, 1)
})

test("switching the same list twice keeps the last selection throughout replies", async () => {
  const { store, LISTS_KEY, setTransport, applySelections, calls } = await setup()
  const first = setTransport("a", "proxy", true)
  const second = setTransport("a", "proxy", false)
  assert.equal(store.get(LISTS_KEY)[0].proxy, false)
  assert.equal(applySelections([{ name: "a", count: 1, proxy: true }])[0].proxy, false)
  await settle()
  calls[0].resolve({ lists: ["a"] })
  await first
  await settle()
  assert.equal(store.get(LISTS_KEY)[0].proxy, false)
  assert.deepEqual(calls[1].args, [[]])
  calls[1].resolve({ lists: [] })
  await second
  assert.equal(store.get(LISTS_KEY)[0].proxy, false)
})

test("list connection rollback works even before the module snapshot arrives", async () => {
  const { store, LISTS_KEY, setTransport, calls } = await setup()
  store.set("proxy", undefined)
  const saving = setTransport("a", "proxy", true)
  await settle()
  calls[0].reject(new Error("offline"))
  await saving
  assert.deepEqual(store.get("proxy").lists, [])
  assert.equal(store.get(LISTS_KEY)[0].proxy, false)
})

test("a list read issued before a completed connection uses its newer selection", async () => {
  const { store, applySelections, setTransport, calls } = await setup()
  const before = { proxy: store.get("proxy"), winws: store.get("winws") }
  const saving = setTransport("a", "proxy", true)
  await settle()
  calls[0].resolve({ lists: ["a"] })
  await saving
  assert.equal(applySelections([{ name: "a", count: 1, proxy: false }], before)[0].proxy, true)
})
