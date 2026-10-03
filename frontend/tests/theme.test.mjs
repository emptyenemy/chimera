import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/theme.ts", import.meta.url), "utf8")
  .replace(/^import .*$/gm, "")
const js = ts.transpileModule(
  `const { api, onPush, useSyncExternalStore, t, notify } = globalThis.__themeHarness;\n${source}`,
  { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }
).outputText
let instance = 0
const palette = (hue = 0) => ({
  mode: "dark", palette: "classic", hue,
  styles: { "--primary": `color-${hue}`, "--background": "#000000" },
  settings: { theme: "dark", appearance: { density: "comfortable", accent_source: "custom" } },
})

async function setup() {
  const calls = [], frames = new Map(), styles = new Map()
  let frame = 0
  globalThis.document = { documentElement: {
    dataset: {}, classList: { toggle() {} },
    style: { setProperty: (key, value) => styles.set(key, value), getPropertyValue: key => styles.get(key) },
  } }
  globalThis.window = { __CHIMERA_APPEARANCE__: palette(), matchMedia: () => ({ addEventListener() {} }) }
  globalThis.requestAnimationFrame = fn => { frames.set(++frame, fn); return frame }
  globalThis.cancelAnimationFrame = id => frames.delete(id)
  globalThis.__themeHarness = {
    api: (method, ...args) => new Promise((resolve, reject) => calls.push({ method, args, resolve, reject })),
    onPush() {}, useSyncExternalStore: (_subscribe, read) => read(), t: key => key, notify: { error() {} },
  }
  const theme = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}#${++instance}`)
  const paint = () => {
    const batch = [...frames.values()]
    frames.clear()
    for (const fn of batch) fn()
  }
  const settle = () => new Promise(resolve => setImmediate(resolve))
  return { theme, calls, styles, paint, settle }
}

test("a burst previews only the latest hue and keeps one request in flight", async () => {
  const { theme, calls, paint, settle } = await setup()
  const first = Array.from({ length: 100 }, (_, hue) => theme.previewAppearance({ hue }))
  paint()
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, [{ hue: 99 }])
  const second = Array.from({ length: 100 }, (_, n) => theme.previewAppearance({ hue: n + 100 }))
  paint()
  assert.equal(calls.length, 1)
  calls[0].resolve(palette(99))
  await settle()
  assert.equal(theme.useAppearance().hue, 0)
  paint()
  assert.equal(calls.length, 2)
  assert.deepEqual(calls[1].args, [{ hue: 199 }])
  calls[1].resolve(palette(199))
  const results = await Promise.all([...first, ...second])
  assert.ok(results.slice(0, -1).every(value => value === null))
  assert.equal(results.at(-1).hue, 199)
  assert.equal(theme.useAppearance().hue, 199)
})

test("commit cancels queued previews and ignores late responses", async () => {
  const { theme, calls, paint } = await setup()
  const active = theme.previewAppearance({ hue: 25 })
  paint()
  const queued = theme.previewAppearance({ hue: 30 })
  const saving = theme.applyAppearance({ hue: 45 })
  assert.equal(await queued, null)
  assert.equal(theme.useAppearancePending(), true)
  assert.equal(await theme.previewAppearance({ hue: 60 }), null)
  assert.equal(calls[1].method, "appearance_apply")
  calls[1].resolve(palette(45))
  await saving
  calls[0].resolve(palette(25))
  assert.equal(await active, null)
  paint()
  assert.equal(calls.length, 2)
  assert.equal(theme.useAppearance().hue, 45)
  assert.equal(theme.useAppearancePending(), false)
})

test("discard restores saved appearance and invalidates in-flight previews", async () => {
  const { theme, calls, paint } = await setup()
  const preview = theme.previewAppearance({ hue: 120 })
  paint()
  const restoring = theme.discardAppearancePreview()
  assert.equal(calls[1].method, "appearance_state")
  calls[1].resolve(palette())
  await restoring
  calls[0].resolve(palette(120))
  assert.equal(await preview, null)
  assert.equal(theme.useAppearance().hue, 0)
})

test("failed obsolete preview cannot reject the current edit", async () => {
  const { theme, calls, paint, settle } = await setup()
  const obsolete = theme.previewAppearance({ hue: 10 })
  paint()
  const current = theme.previewAppearance({ hue: 20 })
  calls[0].reject(new Error("offline"))
  assert.equal(await obsolete, null)
  await settle()
  paint()
  const rejected = assert.rejects(current, /offline/)
  calls[1].reject(new Error("offline"))
  await rejected
})
