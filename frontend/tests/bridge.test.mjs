import assert from "node:assert/strict"
import test from "node:test"
import { loadModule } from "./helpers.mjs"

async function setup() {
  const maps = [], calls = []
  let ready, resolved, pushed
  class ObservedMap extends Map {
    constructor(...args) { super(...args); maps.push(this) }
  }
  const bridge = {
    call: (...args) => calls.push(args),
    resolved: { connect: callback => { resolved = callback } },
    pushed: { connect: callback => { pushed = callback } },
  }
  const window = {
    qt: { webChannelTransport: {} },
    QWebChannel: class { constructor(_transport, callback) { ready = callback } },
  }
  const mod = await loadModule("../src/lib/bridge.ts", { window, Map: ObservedMap, t: key => key, errorMessage: reply => reply.error })
  return { ...mod, bridge, maps, calls, ready: value => ready(value ?? { objects: { bridge } }), resolved: (...args) => resolved(...args), pushed: (...args) => pushed(...args) }
}

test("Qt responses resolve the matching calls and ignore duplicate responses", async () => {
  const s = await setup()
  const initialization = s.initBridge()
  s.ready()
  await initialization
  const first = s.Bridge.call("first", "[]"), second = s.Bridge.call("second", "[]")
  s.resolved(s.calls[1][0], "second reply")
  s.resolved(s.calls[0][0], "first reply")
  assert.deepEqual(await Promise.all([first, second]), ["first reply", "second reply"])
  s.resolved(s.calls[0][0], "duplicate")
  assert.equal(s.maps.at(-1).size, 0)
})

test("failed Qt sends release pending callbacks and the bridge can send again", async () => {
  const s = await setup()
  const initialization = s.initBridge()
  s.ready()
  await initialization
  s.bridge.call = () => { throw new Error("Channel closed") }
  for (let index = 0; index < 20; index++)
    await assert.rejects(s.Bridge.call("write", "[]"), /Channel closed/)
  assert.equal(s.maps.at(-1).size, 0)
  s.bridge.call = (...args) => s.calls.push(args)
  const next = s.Bridge.call("read", "[]")
  s.resolved(s.calls.at(-1)[0], "success")
  assert.equal(await next, "success")
})

test("invalid asynchronously delivered Qt channel setup rejects initialization", async () => {
  const s = await setup()
  const initialization = s.initBridge()
  const rejected = assert.rejects(initialization)
  await Promise.resolve()
  assert.doesNotThrow(() => s.ready({ objects: {} }))
  await rejected
  assert.equal(s.Bridge.call, null)
})

test("malformed Qt pushes do not interrupt later events", async () => {
  const s = await setup()
  const initialization = s.initBridge()
  s.ready()
  await initialization
  const events = []
  s.onPush("hub", payload => events.push(payload))
  assert.doesNotThrow(() => s.pushed("hub", "broken"))
  s.pushed("hub", '{"key":"proxy","data":{"running":true}}')
  assert.deepEqual(events, [{ key: "proxy", data: { running: true } }])
})
