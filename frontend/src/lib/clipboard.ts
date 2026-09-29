import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"

/** Копирует текст в буфер (запасной путь — для встроенных браузеров без Clipboard API)
    и показывает тост «Скопировано». */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement("textarea")
    ta.value = text
    ta.style.position = "fixed"
    ta.style.opacity = "0"
    document.body.appendChild(ta)
    ta.select()
    document.execCommand("copy")
    ta.remove()
  }
  notify.success(t("clipboard.copied"))
}
