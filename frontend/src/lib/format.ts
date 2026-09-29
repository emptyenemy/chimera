/* Форматирование чисел и версий — те же правила, что у старого фронта. */

/** Число по-русски: есть дробная часть — ровно 2 знака, нет — без запятой.
    Сначала toFixed(6) гасит мусор плавающей точки, потом копейку добираем по третьему
    знаку строки (прямой toFixed(2) врёт на числах вроде 1.005). */
export function fmtNum(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—"
  const neg = n < 0
  const [int, frac] = Math.abs(n).toFixed(6).split(".")
  let cents = parseInt(frac.slice(0, 2), 10)
  if (parseInt(frac[2], 10) >= 5) cents += 1
  let whole = BigInt(int)
  if (cents >= 100) {
    cents -= 100
    whole += 1n
  }
  const intStr = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ")
  const out = cents ? `${intStr},${String(cents).padStart(2, "0")}` : intStr
  return (neg ? "−" : "") + out
}

/** 0.2.0 -> v0.2.0, а «dev» (запуск из исходников) — как есть. */
export function fmtVersion(v: string | null | undefined): string {
  if (!v) return ""
  return /^\d/.test(v) ? `v${v}` : v
}
