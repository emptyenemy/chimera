import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"

const source = readFileSync(new URL("../src/pages/lists-record-data.ts", import.meta.url), "utf8").replace(/^import .*$/gm, "")
const js = ts.transpileModule(`const { api } = globalThis.__recordHarness;\n${source}`,
  { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
let instance = 0

async function load(replies) {
  const calls = []
  globalThis.__recordHarness = {
    api: async (method, name) => {
      calls.push([method, name])
      const reply = replies[name]
      if (reply instanceof Error) throw reply
      return reply
    },
  }
  const page = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}#${++instance}`)
  return { page, calls }
}

const VIDEO = { domain: "googlevideo.com", hosts: ["rr1.googlevideo.com"] }
const STATIC = { domain: "ytimg.com", hosts: [] }
const TRACKER = { domain: "doubleclick.net", hosts: ["ad.doubleclick.net"], tracker: true }

test("found domains are checked by the names the site asked for and blocked ones get picked", async () => {
  const { page, calls } = await load({
    "rr1.googlevideo.com": { status: "blocked" }, "ytimg.com": { status: "ok" }, "ad.doubleclick.net": { status: "blocked" },
  })
  const got = {}
  await page.checkDomains([VIDEO, STATIC, TRACKER], (domain, reach) => { got[domain] = reach }, 2)
  assert.deepEqual(calls.map(c => c[1]).sort(), ["ad.doubleclick.net", "rr1.googlevideo.com", "ytimg.com"])
  assert.ok(calls.every(c => c[0] === "block_check_one"))
  assert.deepEqual([...page.preselect([VIDEO, STATIC, TRACKER], got)], ["googlevideo.com"])
})

test("without blocks everything but trackers is picked, and a failed check is not a block", async () => {
  const { page } = await load({ "rr1.googlevideo.com": new Error("offline"), "ytimg.com": { status: "challenge" } })
  const got = {}
  await page.checkDomains([VIDEO, STATIC], (domain, reach) => { got[domain] = reach })
  assert.equal(got["googlevideo.com"].status, "error")
  assert.deepEqual([...page.preselect([VIDEO, STATIC, TRACKER], got)], ["googlevideo.com", "ytimg.com"])
})

test("DNS failures and region refusals count as blocks: the proxy or hosts fix them", async () => {
  const { page } = await load({})
  for (const status of ["dns", "denied", "blocked"]) assert.ok(page.isBlocked({ status }))
  for (const status of ["ok", "challenge", "error"]) assert.ok(!page.isBlocked({ status }))
  assert.deepEqual(page.reachLabel(undefined), { key: "checks.v.pending", tone: "off" })
  assert.deepEqual(page.reachLabel({ status: "blocked" }), { key: "checks.v.unreachable", tone: "err" })
  assert.deepEqual(page.reachLabel({ status: "denied" }), { key: "checks.v.denied", tone: "warn" })
  assert.deepEqual(page.reachLabel({ status: "ok" }), { key: "checks.v.open", tone: "ok" })
})
