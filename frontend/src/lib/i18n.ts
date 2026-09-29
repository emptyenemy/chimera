/* Тонкая обёртка над каталогом строк. Все пользовательские тексты идут через
   t("ключ", { параметры }); сейчас каталог один — русский (locales/ru.json), другие
   языки подключатся заменой каталога, без переписывания компонентов.

   Плюрализация — по правилам языка: если передан count, берутся ключи
   "ключ.one" / "ключ.few" / "ключ.many" / "ключ.other". */

import ru from "@/locales/ru.json"

export type Params = Record<string, string | number>

let catalog: Record<string, string> = ru
let rules = new Intl.PluralRules("ru")

/** Подмена каталога (для будущего выбора языка). */
export function setCatalog(next: Record<string, string>, locale: string): void {
  catalog = next
  rules = new Intl.PluralRules(locale)
}

const missing = new Set<string>()

function lookup(key: string): string | undefined {
  return Object.prototype.hasOwnProperty.call(catalog, key) ? catalog[key] : undefined
}

export function t(key: string, params?: Params): string {
  let text: string | undefined
  if (typeof params?.count === "number") {
    const form = rules.select(params.count)
    text = lookup(`${key}.${form}`) ?? lookup(`${key}.other`) ?? lookup(`${key}.many`)
  }
  text ??= lookup(key)
  if (text === undefined) {
    // отсутствующий ключ виден в интерфейсе как есть и один раз ругается в консоль
    if (!missing.has(key)) {
      missing.add(key)
      console.warn(`[i18n] нет строки: ${key}`)
    }
    return key
  }
  if (!params) return text
  return text.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? String(params[name]) : m))
}
