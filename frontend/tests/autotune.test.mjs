import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

function memoryStore() {
  const data = new Map()
  return { get: key => data.get(key), set: (key, value) => data.set(key, value), data }
}

const setup = (api = async () => null) => {
  const store = memoryStore()
  return loadModule("../src/pages/autotune-data.ts", {
    api, store, t: (key, params) => (params ? `${key} ${JSON.stringify(params)}` : key),
  }).then(mod => ({ ...mod, store }))
}

const running = (stage, current = null) => ({ id: "a", phase: "running", stage, current, log: [], report: null })

test("progress follows the steps and the variant within a step", async () => {
  const { progressPercent } = await setup()
  assert.equal(progressPercent(null), 0)
  assert.equal(progressPercent(running("diagnose")), 0)
  assert.equal(progressPercent(running("strategy", { step: "strategy", candidate: "x", index: 0, total: 1 })), 70)
  assert.equal(progressPercent(running("strategy", { step: "strategy", candidate: "x", index: 9, total: 20 })), 38)
  assert.equal(progressPercent(running("verify")), 97)
  assert.equal(progressPercent({ ...running("verify"), phase: "done" }), 0)
})

test("a finished session becomes the diagnosis once, without losing other services", async () => {
  const { absorbReport, statusOf, store, DIAGNOSIS_KEY } = await setup()
  store.set(DIAGNOSIS_KEY, { busy: false, error: null, result: { offline: false, services: [
    { name: "youtube", ok: false, reasons: ["dpi"] }, { name: "discord", ok: true }] } })
  const done = { id: "s1", phase: "done", report: { offline: false, services: [
    { name: "youtube", after: { ok: true, ms: 40 }, fix: { kind: "strategy", id: "alt" } }] } }
  absorbReport(done)
  const result = store.get(DIAGNOSIS_KEY).result
  assert.deepEqual(result.services.map(r => [r.name, r.ok]), [["youtube", true], ["discord", true]])
  // повторный пуш того же состояния не затирает свежий диагноз
  store.set(DIAGNOSIS_KEY, { busy: false, error: null, result: { offline: false, services: [{ name: "youtube", ok: false }] } })
  absorbReport(done)
  assert.equal(store.get(DIAGNOSIS_KEY).result.services[0].ok, false)
  assert.equal(statusOf("youtube", null, done).ok, true)
  assert.equal(statusOf("discord", { services: [{ name: "discord", ok: false }] }, done).ok, false)
})

test("checking one service updates only its row", async () => {
  const reply = deferred()
  const { diagnose, store, DIAGNOSIS_KEY } = await setup(() => reply.promise)
  store.set(DIAGNOSIS_KEY, { busy: false, error: null, result: { offline: false, services: [
    { name: "youtube", ok: false }, { name: "discord", ok: false }] } })
  const done = diagnose(["discord"])
  assert.equal(store.get(DIAGNOSIS_KEY).busy, true)
  reply.resolve({ offline: false, services: [{ name: "discord", ok: true }] })
  await done
  assert.deepEqual(store.get(DIAGNOSIS_KEY).result.services.map(r => r.ok), [false, true])
})

test("a failed check keeps the previous result and shows the error", async () => {
  const { diagnose, store, DIAGNOSIS_KEY } = await setup(async () => { throw new Error("no owner") })
  store.set(DIAGNOSIS_KEY, { busy: false, error: null, result: { offline: false, services: [{ name: "x", ok: true }] } })
  await diagnose()
  await settle()
  const view = store.get(DIAGNOSIS_KEY)
  assert.equal(view.error, "no owner") ; assert.equal(view.result.services[0].ok, true) ; assert.equal(view.busy, false)
})

test("methods are named with strategy and provider names", async () => {
  const { fixText, candidateText } = await setup()
  const strategies = [{ id: "alt", name: "ALT" }]
  const names = { comss: "Comss DNS" }
  assert.equal(fixText({ kind: "strategy", id: "alt" }, strategies, names), 'autotune.via.strategy {"name":"ALT"}')
  assert.equal(fixText({ kind: "hosts", id: "comss" }, strategies, names), 'autotune.via.hosts {"name":"Comss DNS"}')
  assert.equal(fixText({ kind: "dns", id: "google" }, strategies, names), 'autotune.via.dns {"name":"google"}')
  assert.equal(fixText({ kind: "proxy", id: "proxy" }, strategies, names), "autotune.via.proxy")
  assert.equal(candidateText("strategy", "zzz", strategies, names), "zzz")
})

test("the progress line names the variant; the proxy has a line of its own", async () => {
  const { currentText } = await setup()
  const strategies = [{ id: "alt", name: "ALT" }]
  assert.equal(currentText({ step: "strategy", candidate: "alt", index: 2, total: 9 }, strategies, {}),
    'autotune.running.current {"step":"autotune.step.strategy","who":"ALT","n":3,"total":9}')
  // у прокси нет шага и имени варианта: иначе в строке «Пробую  Через прокси» — двойной пробел и регистр
  assert.equal(currentText({ step: "proxy", candidate: "proxy", index: 0, total: 1 }, strategies, {}),
    'autotune.running.proxy {"n":1,"total":1}')
})
