/** Empty input restores the default; other input must contain whole positive units. */
export function parseInterval(value: string, unitSeconds: number, defaultUnits: number): number | null {
  const text = value.trim()
  if (!text) return defaultUnits * unitSeconds
  if (!/^\d+$/.test(text)) return null
  const seconds = Number(text) * unitSeconds
  return Number.isSafeInteger(seconds) && seconds > 0 ? seconds : null
}
