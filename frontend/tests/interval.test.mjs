import assert from "node:assert/strict"
import test from "node:test"
import { loadModule } from "./helpers.mjs"

const { parseInterval } = await loadModule("../src/lib/interval.ts", {})

test("hours and minutes keep their units and blank input restores defaults", () => {
  assert.equal(parseInterval(" 12 ", 3600, 6), 43200)
  assert.equal(parseInterval("01", 60, 15), 60)
  assert.equal(parseInterval("", 3600, 6), 21600)
  assert.equal(parseInterval("  ", 60, 15), 900)
})

test("invalid intervals cannot be truncated, defaulted or sent as imprecise seconds", () => {
  for (const value of ["12abc", "1.5", "1,5", "1e3", "0", "-1", "Infinity", "9007199254740991", "9".repeat(100)]) {
    assert.equal(parseInterval(value, 3600, 6), null, value)
  }
})
