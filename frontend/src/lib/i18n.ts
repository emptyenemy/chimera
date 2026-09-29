/* Каталоги интерфейса и бэкенда; множественные формы выбирает Intl.PluralRules. */
import ru from "@/locales/ru.json"
import en from "@/locales/en.json"

export type Params = Record<string, string | number>
export type Language = "ru" | "en"
let locale: Language = "ru"
let catalog: Record<string, string> = ru
let rules = new Intl.PluralRules(locale)
const missing = new Set<string>()

export function currentLocale(): Language { return locale }

export function setCatalog(backend: Record<string, string>, lang: string): void {
  locale = lang === "en" ? "en" : "ru"
  catalog = { ...en, ...backend, ...(locale === "ru" ? ru : en) }
  rules = new Intl.PluralRules(locale)
  document.documentElement.lang = locale
  document.documentElement.dir = "ltr"
  missing.clear()
}

export function hasTranslation(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(catalog, key)
}

export function t(key: string, params?: Params): string {
  let text: string | undefined
  const lookup = (k: string) => hasTranslation(k) ? catalog[k] : undefined
  if (typeof params?.count === "number") {
    const form = rules.select(params.count)
    text = lookup(`${key}.${form}`) ?? lookup(`${key}.other`) ?? lookup(`${key}.many`)
  }
  text ??= lookup(key)
  if (text === undefined) {
    if (!missing.has(key)) {
      missing.add(key)
      console.warn(`[i18n] missing: ${key}`)
    }
    return key
  }
  if (!params) return text
  return text.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? String(params[name]) : m))
}

export function errorMessage(reply: { error?: string; code?: string; params?: Params }): string {
  return reply.code && hasTranslation(reply.code) ? t(reply.code, reply.params) : reply.error || t("common.failed")
}
