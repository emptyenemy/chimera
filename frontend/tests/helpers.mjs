import { readFileSync } from "node:fs"
import ts from "typescript"

let sequence = 0
export async function loadModule(path, runtime, extra = "") {
  const source = readFileSync(new URL(path, import.meta.url), "utf8").replace(/^import .*$/gm, "")
  globalThis.__moduleTestRuntime = runtime
  const prefix = `const { ${Object.keys(runtime).join(", ")} } = globalThis.__moduleTestRuntime;`
  const js = ts.transpileModule(`${prefix}\n${source}\n${extra}`, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}#${++sequence}`)
}

export function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

export const settle = () => new Promise(resolve => setImmediate(resolve))
