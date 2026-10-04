import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"

const source = readFileSync(new URL("../src/pages/checks-data.ts", import.meta.url), "utf8").replace(/^import .*$/gm, "")
const js = ts.transpileModule(
  `const { api, onPush, notify, t, useSyncExternalStore } = globalThis.__checksHarness;\n${source}`,
  { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }
).outputText
let instance = 0
async function setup() {
  const calls = [], pushes = new Map(), errors = []
  globalThis.window = { setTimeout }
  globalThis.__checksHarness = {
    api: (method, ...args) => new Promise((resolve, reject) => calls.push({ method, args, resolve, reject })),
    onPush: (name, fn) => pushes.set(name, fn),
    notify: { error: (...args) => errors.push(args) }, t: key => key, useSyncExternalStore: () => null,
  }
  const page = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}#${++instance}`)
  return { page, calls, errors, push: (name, data = {}) => pushes.get(name)({ _request_id: calls.findLast(c => c.method === "block_check_start")?.args[1], ...data }), settle: () => new Promise(resolve => setImmediate(resolve)) }
}

test("early streamed results and Done events survive both start responses", async () => {
  const { page, calls, push, settle } = await setup()
  const running = page.checkList("test")
  push("blockResult", { target: "first.test", status: "ok" })
  push("blockResult", { target: "second.test", status: "ok" })
  push("blockDone")
  assert.ok(page.s.run)
  calls[0].resolve({ total: 2 })
  await settle()
  assert.equal(calls[1].method, "chebur_check_start")
  assert.ok(page.s.run)
  push("cheburResult", { target: "first.test", blocked: false })
  push("cheburResult", { target: "second.test", blocked: true, rkn_domain: true })
  push("cheburDone")
  assert.ok(page.s.run)
  calls[1].resolve({ total: 2 })
  await running
  assert.equal(page.s.run, null)
  assert.equal(page.s.results.size, 2)
  assert.equal(page.s.results.get("second.test").rkn.blocked, true)
})

test("an empty list finishes and allows another check", async () => {
  const { page, calls, settle } = await setup()
  const running = page.checkList("empty")
  calls[0].resolve({ total: 0 })
  await settle()
  calls[1].resolve({ total: 0 })
  await running
  assert.equal(page.s.run, null)
  const again = page.checkList("empty")
  assert.equal(calls.length, 3)
  calls[2].resolve({ total: 0 })
  await settle()
  calls[3].resolve({ total: 0 })
  await again
})

test("registry start failure still completes available reachability results", async () => {
  const { page, calls, push, settle } = await setup()
  const running = page.checkList("test")
  calls[0].resolve({ total: 1 })
  await settle()
  push("blockResult", { target: "first.test", status: "ok" })
  push("blockDone")
  calls[1].reject(new Error("registry unavailable"))
  await running
  assert.equal(page.s.run, null)
  assert.equal(page.s.results.get("first.test").reach.status, "ok")
  assert.equal(page.s.results.get("first.test").rkn.status, "error")
})

test("duplicate streamed results do not inflate progress or finish a run early", async () => {
  const { page, calls, push, settle } = await setup()
  const starting = page.checkList("test")
  calls[0].resolve({ total: 2, targets: ["first.test", "second.test"] })
  await settle()
  calls[1].resolve({ total: 2 })
  await starting
  push("blockResult", { target: "first.test", status: "ok" })
  push("blockResult", { target: "first.test", status: "ok" })
  push("cheburResult", { target: "first.test", blocked: false })
  assert.equal(page.s.run.reachDone, 1)
  assert.equal(page.s.run.rknDone, 1)
  push("cheburResult", { target: "second.test", blocked: false })
  assert.ok(page.s.run, "The second site is still awaiting reachability")
  push("blockResult", { target: "second.test", status: "ok" })
  assert.equal(page.s.run, null)
})

test("foreign results and Done cannot enter a running list check", async () => {
  const { page, calls, push, settle } = await setup()
  const starting = page.checkList("test")
  calls[0].resolve({ total: 1, targets: ["first.test"] })
  await settle()
  calls[1].resolve({ total: 1 })
  await starting
  push("blockResult", { target: "foreign.test", status: "ok", _request_id: "other" })
  push("blockDone", { _request_id: "other" })
  assert.equal(page.s.run.reachDone, 0)
  assert.equal(page.s.results.has("foreign.test"), false)
})

test("streamed list events do not alter a manually entered check", async () => {
  const { page, calls, push } = await setup()
  page.s.input = "first.test"
  const running = page.checkTyped()
  push("blockResult", { target: "foreign.test", status: "ok", _request_id: "other" })
  push("blockDone", { _request_id: "other" })
  assert.equal(page.s.run.reachDone, 0)
  assert.equal(page.s.results.has("foreign.test"), false)
  calls.find(c => c.method === "block_check_one").resolve({ target: "first.test", status: "ok" })
  calls.find(c => c.method === "chebur_check_one").resolve({ target: "first.test", blocked: false })
  await running
})

test("Done restores every missed result without overwriting the other kind", async () => {
  const { page, calls, push, settle } = await setup()
  const starting = page.checkList("test")
  calls[0].resolve({ total: 2, targets: ["first.test", "second.test"] })
  await settle()
  calls[1].resolve({ total: 2 })
  await starting
  push("blockResult", { target: "first.test", status: "ok" })
  push("cheburDone", { results: [{ target: "first.test", blocked: false }, { target: "second.test", blocked: true }] })
  push("blockDone", { results: [{ target: "first.test", status: "ok" }, { target: "second.test", status: "dns" }] })
  assert.equal(page.s.run, null)
  assert.equal(page.s.results.get("second.test").reach.status, "dns")
  assert.equal(page.s.results.get("second.test").rkn.blocked, true)
})

test("both list workers use the same original target snapshot", async () => {
  const { page, calls, settle } = await setup()
  const starting = page.checkList("test")
  calls[0].resolve({ total: 1, targets: ["original.test"] })
  await settle()
  assert.deepEqual(calls[1].args.slice(1), [calls[0].args[1], ["original.test"]])
  calls[1].reject(new Error("unavailable"))
  await starting
})

test("manual targets accept international domains, IP addresses and HTTPS links", async () => {
  const { page } = await setup()
  assert.deepEqual(page.parseTargets("https://ПРИМЕР.рф/path, 1.1.1.1; https://[2606:4700:4700::1111]/ www.example.com:443/a example.com"),
    ["xn--e1afmkfd.xn--p1ai", "1.1.1.1", "2606:4700:4700::1111", "example.com"])
  assert.deepEqual(page.parseTargets("::1 [::1] 2606:4700:4700::1111"), ["::1", "2606:4700:4700::1111"])
})

test("manual targets reject broken domain labels, credentials and unsupported protocols", async () => {
  const { page } = await setup()
  assert.deepEqual(page.parseTargets(".bad.example broken..example -bad.example bad-.example ftp://example.com user:password@example.com https://example.com:99999"), [])
})

test("returning to Checks cannot replace newer lists with a late read", async () => {
  const { page, calls } = await setup()
  const old = page.loadLists(), fresh = page.loadLists()
  assert.equal(calls[0].method, "lists_index")
  calls[1].resolve([{ name: "new", count: 2, entries: ["a.test", "b.test"] }])
  await fresh
  calls[0].resolve([{ name: "old", count: 1, entries: ["c.test"] }])
  await old
  assert.deepEqual(page.s.lists.map(l => l.name), ["new"])
})

const LISTS = [
  { name: "google", count: 3, entries: ["google.com", "youtube-nocookie.com", "1.2.3.4"] },
  { name: "youtube", count: 3, entries: ["youtube.com", "youtu.be", "ytimg.com"] },
  { name: "other", count: 2, entries: [".m.youtube.com", "example.com"] },
]

test("search suggests lists by name first, then by matching entries, and their domains", async () => {
  const { page } = await setup()
  const [lists, sites] = page.suggest(LISTS, "YouTube")
  assert.deepEqual(lists.items.map(l => l.name), ["youtube", "google", "other"])
  assert.deepEqual(lists.items[2].hits, ["m.youtube.com"])
  assert.deepEqual(sites.items.map(s => s.domain), ["youtube.com", "youtube-nocookie.com", "m.youtube.com"])
})

test("search looks only at the address being typed and ignores links and short queries", async () => {
  const { page } = await setup()
  assert.deepEqual(page.suggest(LISTS, "y"), [])
  assert.deepEqual(page.suggest(LISTS, "youtube.com "), [])
  assert.deepEqual(page.suggest(LISTS, "discord.com https://www.ytimg.com/path")[0].items.map(l => l.name), ["youtube"])
  assert.deepEqual(page.suggest(LISTS, "1.2.3"), [{ value: "lists", items: [{ kind: "list", name: "google", count: 3, hits: ["1.2.3.4"], byName: false }] }])
})

test("a picked domain replaces the unfinished address and starts the check", async () => {
  const { page, calls } = await setup()
  page.s.input = "discord.com youtu"
  page.pickSuggestion({ kind: "site", domain: "youtube.com" })
  assert.equal(page.s.input, "discord.com youtube.com")
  assert.deepEqual(calls.filter(c => c.method === "block_check_one").map(c => c.args[0]), ["discord.com", "youtube.com"])
})

test("an old registry status cannot hide a newer unavailable status", async () => {
  const { page, calls } = await setup()
  const old = page.loadRegistryStatus(), fresh = page.loadRegistryStatus()
  calls[1].reject(new Error("unavailable"))
  await fresh
  calls[0].resolve({})
  await old
  assert.equal(page.s.registryDown, "unavailable")
})

test("sites behind Cloudflare that fail are found by our networks or by the registry's CDN field", async () => {
  const { page } = await setup()
  const results = new Map([
    ["medium.com", { rkn: null, reach: { status: "blocked", cdn: "cloudflare" } }],
    ["patreon.com", { rkn: { blocked: false, cdn: ["Cloudflare"] }, reach: { status: "denied" } }],
    ["npmjs.com", { rkn: null, reach: { status: "ok", cdn: "cloudflare" } }],
    ["itch.io", { rkn: null, reach: { status: "blocked" } }],
    ["pending.example", { rkn: { cdn: ["cloudflare"] }, reach: null }],
  ])
  assert.deepEqual(page.cloudflareProblems(results), ["medium.com", "patreon.com"])
  // режет РКН — к стратегиям; сам не пускает из России (403/451) — только прокси
  assert.equal(page.refusedByRegion(results.get("medium.com")), false)
  assert.equal(page.refusedByRegion(results.get("patreon.com")), true)
})

