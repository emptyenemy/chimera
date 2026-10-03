import assert from "node:assert/strict"
import test from "node:test"
import { deferred, loadModule, settle } from "./helpers.mjs"

const setup = () => loadModule("../src/pages/lists-data.ts", {
  t: key => key, notify: { error() {} }, store: { get() {}, set() {} },
})

test("list writes run in order, and a failed write does not block the next", async () => {
  const { track, waitSaved } = await setup()
  const first = deferred(), second = deferred(), calls = []
  const a = track("sample", () => { calls.push(1); return first.promise })
  const rejected = assert.rejects(a, /disk/)
  const b = track("sample", () => { calls.push(2); return second.promise })
  let finished = false
  const waiting = waitSaved("sample").then(() => { finished = true })
  await settle()
  assert.deepEqual(calls, [1])
  first.reject(new Error("disk"))
  await rejected
  await settle()
  assert.deepEqual(calls, [1, 2])
  assert.equal(finished, false)
  second.resolve("latest")
  assert.equal(await b, "latest")
  await waiting
})

test("reading waits for writes added while it is already waiting", async () => {
  const { track, waitSaved } = await setup()
  const first = deferred(), second = deferred()
  const a = track("sample", () => first.promise)
  let finished = false
  const waiting = waitSaved("sample").then(() => { finished = true })
  const b = track("sample", () => second.promise)
  first.resolve()
  await a
  await settle()
  assert.equal(finished, false)
  second.resolve()
  await b
  await waiting
})

test("renaming saves the open draft and keeps its editor retired", async () => {
  const { registerEditor, track, withSavedList } = await setup()
  const draft = deferred(), calls = []
  registerEditor("sample", {
    freeze: on => calls.push(["freeze", on]),
    flush: () => track("sample", () => { calls.push(["save"]); return draft.promise }),
    retire: () => calls.push(["retire"]),
  })
  const moving = withSavedList("sample", async () => { calls.push(["rename"]); return "next" }, true)
  await settle()
  assert.deepEqual(calls, [["freeze", true], ["save"]])
  draft.resolve(true)
  assert.equal(await moving, "next")
  assert.deepEqual(calls.slice(2), [["rename"], ["retire"], ["freeze", false]])
})

test("a failed draft blocks destructive operations and unlocks the editor", async () => {
  const { registerEditor, withSavedList } = await setup()
  const calls = []
  registerEditor("sample", {
    freeze: on => calls.push(on), flush: async () => false, retire: () => assert.fail("retired"),
  })
  await assert.rejects(withSavedList("sample", async () => assert.fail("deleted"), true), /lists.status.error/)
  assert.deepEqual(calls, [true, false])
})

test("different lists save independently", async () => {
  const { track } = await setup()
  const slow = deferred()
  const a = track("a", () => slow.promise)
  assert.equal(await track("b", async () => "done"), "done")
  slow.resolve()
  await a
})

test("a failed list draft survives page changes and clears only on matching success", async () => {
  const { readListDraft, writeListDraft, settleListDraft } = await setup()
  writeListDraft("sample", "unsaved.example\n")
  const first = readListDraft("sample")
  settleListDraft("sample", first, "disk unavailable")
  assert.deepEqual(readListDraft("sample"), { text: "unsaved.example\n", error: "disk unavailable" })
  writeListDraft("sample", "latest.example\n")
  assert.equal(settleListDraft("sample", first, null), false)
  assert.equal(readListDraft("sample").text, "latest.example\n")
  const current = readListDraft("sample")
  assert.equal(settleListDraft("sample", current, null), true)
  assert.equal(readListDraft("sample"), undefined)
})

test("a list operation saves a failed draft even after its editor unmounted", async () => {
  const calls = []
  const { writeListDraft, readListDraft, withSavedList } = await loadModule("../src/pages/lists-data.ts", {
    t: key => key, notify: { error() {} }, store: { get() {}, set() {} },
    api: async (...args) => { calls.push(args); return { count: 1 } },
  })
  writeListDraft("sample", "retained.example\n")
  await withSavedList("sample", async () => calls.push(["rename"]), true)
  assert.deepEqual(calls, [["lists_save", "sample", "retained.example\n"], ["rename"]])
  assert.equal(readListDraft("sample"), undefined)
})

test("a newly opened editor stays locked during an already pending file operation", async () => {
  const { registerEditor, withSavedList } = await setup()
  const operation = deferred(), calls = []
  const moving = withSavedList("sample", () => operation.promise, true)
  await settle()
  registerEditor("sample", {
    flush: async () => true, freeze: on => calls.push(on), retire: () => calls.push("retired"),
  })
  assert.deepEqual(calls, [true])
  operation.resolve()
  await moving
  assert.deepEqual(calls, [true, "retired", false])
})
