import { useEffect, useRef } from "react"
import { cn } from "cn"

import { api } from "@/lib/bridge"

interface LogChunk {
  offset: number
  data?: string
  reset?: boolean
}

function lineClass(line: string): string {
  if (/\b(error|fatal|panic|fail(ed)?|ошибк)/i.test(line)) return "text-destructive"
  if (/\b(warn(ing)?|предупр)/i.test(line)) return "text-warning"
  if (/\b(started|listening|ready|запущен|ok)\b/i.test(line)) return "text-success"
  return ""
}

/** Живой лог с инкрементальной догрузкой. method — метод Api вида *_log(offset) ->
    {offset, data, reset}. Строки дописываются в конец без перерисовки старых, хвост
    ограничен maxLines. Автопрокрутка — только если пользователь и так внизу. */
export function LogView({
  method,
  maxLines = 1500,
  interval = 700,
  className,
}: {
  method: string
  maxLines?: number
  interval?: number
  className?: string
}) {
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = box.current
    if (!el) return
    let stopped = false
    let timer = 0
    let offset = 0
    let lines = 0

    const poll = async () => {
      const r = await api<LogChunk>(method, offset)
      if (r.reset) {
        el.textContent = ""
        lines = 0
      }
      offset = r.offset
      if (!r.data) return
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
      // первый запрос отдаёт весь файл — берём только хвост
      const all = r.data.split("\n")
      const frag = document.createDocumentFragment()
      for (const line of all.length > maxLines ? all.slice(-maxLines) : all) {
        if (!line) continue
        const div = document.createElement("div")
        const cls = lineClass(line)
        if (cls) div.className = cls
        div.textContent = line
        frag.appendChild(div)
        lines++
      }
      el.appendChild(frag)
      while (lines > maxLines && el.firstChild) {
        el.firstChild.remove()
        lines--
      }
      if (atBottom) el.scrollTop = el.scrollHeight
    }

    const tick = async () => {
      if (stopped) return
      if (!document.hidden) {
        try {
          await poll()
        } catch (e) {
          console.error(e)
        }
      }
      if (!stopped) timer = window.setTimeout(tick, interval)
    }
    void tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [method, maxLines, interval])

  return (
    <div
      ref={box}
      data-testid="log-view"
      className={cn(
        "selectable h-72 overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-5 whitespace-pre-wrap select-text",
        className
      )}
    />
  )
}
