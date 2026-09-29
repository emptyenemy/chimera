import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"

const ru = JSON.parse(readFileSync(new URL("../src/locales/ru.json", import.meta.url)))
const en = JSON.parse(readFileSync(new URL("../src/locales/en.json", import.meta.url)))
const source = readFileSync(new URL("../src/lib/i18n.ts", import.meta.url), "utf8")
  .replace(/^import ru .*$/m, `const ru = ${JSON.stringify(ru)}`)
  .replace(/^import en .*$/m, `const en = ${JSON.stringify(en)}`)
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
globalThis.document = { documentElement: {} }
const { setCatalog, t, errorMessage } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`)
const base = key => key.replace(/\.(one|few|many|other)$/, "")
const placeholders = text => [...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort()

test("catalogs cover the same messages and placeholders", () => {
  assert.deepEqual([...new Set(Object.keys(ru).map(base))].sort(), [...new Set(Object.keys(en).map(base))].sort())
  for (const [key, text] of Object.entries(en)) {
    assert.deepEqual(placeholders(text), placeholders(ru[key]), key)
    // Names of supported languages keep their native spelling.
    if (key !== "settings.lang.ru") assert.doesNotMatch(text, /[а-яё]/i, key)
  }
})

test("language, plural forms, interpolation and coded errors", () => {
  setCatalog({ "err.example": "Failure: {name}" }, "en")
  assert.equal(document.documentElement.lang, "en")
  assert.equal(t("nav.settings"), "Settings")
  assert.equal(t("scope.apps", { count: 1, n: 1 }), "1 application")
  assert.equal(t("scope.apps", { count: 21, n: 21 }), "21 applications")
  assert.equal(errorMessage({ code: "err.example", params: { name: "DNS" }, error: "old text" }), "Failure: DNS")
  assert.equal(errorMessage({ code: "err.unknown", error: "fallback" }), "fallback")
  setCatalog({}, "ru")
  assert.equal(t("scope.apps", { count: 21, n: 21 }), "21 приложение")
  assert.equal(t("scope.apps", { count: 22, n: 22 }), "22 приложения")
  assert.equal(t("scope.apps", { count: 5, n: 5 }), "5 приложений")
})
