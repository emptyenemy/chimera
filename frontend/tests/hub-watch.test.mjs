import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

async function setup(api = async () => {}) {
  let effect
  const calls = []
  const { useHubWatch } = await loadModule("../src/lib/hub-watch.ts", {
    useEffect: fn => { effect = fn },
    api: (...args) => { calls.push(args); return api(...args) },
  })
  return { calls, mount: keys => { useHubWatch(keys); return effect() } }
}

test("StrictMode and overlapping watchers produce one balanced subscription", async () => {
  const { calls, mount } = await setup()
  mount(["tg"])()
  const unmount = mount(["tg", "tg"])
  const unmountSecond = mount(["tg"])
  await settle()
  assert.deepEqual(calls, [["hub_watch", ["tg"], true]])
  unmount()
  await settle()
  assert.equal(calls.length, 1)
  unmountSecond()
  await settle()
  assert.deepEqual(calls.at(-1), ["hub_watch", ["tg"], false])
})

test("unmount waits for a pending enable before disabling it", async () => {
  const enabling = deferred()
  const { calls, mount } = await setup((_, __, on) => on ? enabling.promise : Promise.resolve())
  const unmount = mount(["tg"])
  await settle()
  unmount()
  await settle()
  assert.equal(calls.length, 1)
  enabling.resolve()
  await settle()
  assert.deepEqual(calls.at(-1), ["hub_watch", ["tg"], false])
})

test("a rejected subscription does not leave reconciliation stuck", async () => {
  const { calls, mount } = await setup(async () => { throw new Error("bridge") })
  const unmount = mount(["tg"])
  await settle()
  unmount()
  await settle()
  assert.equal(calls.length, 2)
  const unmountNext = mount(["dns"])
  await settle()
  assert.deepEqual(calls.at(-1), ["hub_watch", ["dns"], true])
  unmountNext()
  await settle()
})
