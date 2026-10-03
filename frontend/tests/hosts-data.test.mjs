import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup() {
  const calls = []
  const runtime = {
    useSyncExternalStore: (_subscribe, read) => read(), onPush() {}, t: key => key,
    notify: { error() {} },
    api: (method, ...args) => {
      if (method === "hub_refresh") return Promise.resolve()
      const d = deferred()
      calls.push({ method, args, ...d })
      return d.promise
    },
  }
  const state = await loadModule("../src/lib/store.ts", runtime)
  const hosts = await loadModule("../src/pages/hosts-data.ts", { ...runtime, ...state })
  state.store.set("hosts", { assignments: {}, applied: false })
  return { ...state, ...hosts, calls }
}

test("a failed provider assignment is excluded from a subsequent queued assignment", async () => {
  const { store, saveAssignments, calls } = await setup()
  const first = saveAssignments(value => ({ ...value, first: true }), "failed")
  const second = saveAssignments(value => ({ ...value, second: true }), "failed")
  assert.deepEqual(store.get("hosts").assignments, { first: true, second: true })
  await settle()
  calls[0].reject(new Error("failed"))
  await first
  await settle()
  assert.deepEqual(calls[1].args, [{ second: true }])
  calls[1].resolve({ assignments: { second: true } })
  await second
  assert.deepEqual(store.get("hosts").assignments, { second: true })
})

test("a late overview refresh updates the catalog without reverting newer host state", async () => {
  const { store, OVERVIEW_KEY, loadOverview, calls } = await setup()
  const reading = loadOverview()
  store.set("hosts", { assignments: { current: true }, applied: true })
  calls[0].resolve({ providers: [{ id: "current" }], lists: [], state: { assignments: {}, applied: false } })
  await reading
  assert.equal(store.get("hosts").applied, true)
  assert.equal(store.get(OVERVIEW_KEY).providers[0].id, "current")
})

test("an older overview cannot restore a provider removed by a newer refresh", async () => {
  const { store, OVERVIEW_KEY, loadOverview, calls } = await setup()
  const first = loadOverview(), second = loadOverview()
  calls[1].resolve({ providers: [], lists: [], state: {} })
  await second
  calls[0].resolve({ providers: [{ id: "removed" }], lists: [], state: {} })
  await first
  assert.deepEqual(store.get(OVERVIEW_KEY).providers, [])
})
