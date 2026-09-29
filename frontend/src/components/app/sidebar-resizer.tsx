import { useRef } from "react"

import { useSidebar } from "@/components/ui/sidebar"
import { t } from "@/lib/i18n"
import {
  SIDEBAR_SNAP,
  SIDEBAR_WIDTH_DEFAULT,
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
} from "@/lib/sidebar-state"

const clamp = (w: number) => Math.round(Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, w)))
const RAIL_WIDTH = 48

/** Ручка у правой границы сайдбара: тянуть — менять ширину, дальше SNAP влево — свернуть
    в полосу иконок, двойной клик — ширина по умолчанию. Состояние ведёт хозяин
    (width/onWidth) и сам сохраняет его в localStorage. */
export function SidebarResizer({ width, onWidth }: { width: number; onWidth: (w: number) => void }) {
  const { open, setOpen } = useSidebar()
  const drag = useRef<{ x0: number; w0: number; wOpen: number; raf: number; x: number } | null>(null)

  const finish = () => {
    const d = drag.current
    if (!d) return
    cancelAnimationFrame(d.raf)
    drag.current = null
    document.documentElement.classList.remove("sb-resizing")
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t("sidebar.resize")}
      data-slot="sidebar-resizer"
      data-testid="sidebar-resize"
      className="group/resize fixed inset-y-0 z-20 hidden w-1.5 -translate-x-1/2 cursor-col-resize transition-[left] duration-200 ease-linear md:block"
      style={{ left: open ? "var(--sidebar-width)" : "var(--sidebar-width-icon)" }}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        e.preventDefault()
        e.currentTarget.setPointerCapture(e.pointerId)
        // wOpen — ширина развёрнутой панели до начала: к ней вернёмся, если утащат в полосу
        drag.current = { x0: e.clientX, w0: open ? width : RAIL_WIDTH, wOpen: width, raf: 0, x: e.clientX }
        document.documentElement.classList.add("sb-resizing")
      }}
      onPointerMove={(e) => {
        const d = drag.current
        if (!d) return
        d.x = e.clientX
        // не чаще раза в кадр: pointermove сыплет быстрее, чем браузер успевает перекладку
        d.raf ||= requestAnimationFrame(() => {
          d.raf = 0
          const raw = d.w0 + d.x - d.x0
          if (raw < SIDEBAR_SNAP) {
            onWidth(d.wOpen)
            setOpen(false)
            return
          }
          setOpen(true)
          onWidth(clamp(raw))
        })
      }}
      onPointerUp={finish}
      onPointerCancel={finish}
      onDoubleClick={() => {
        onWidth(SIDEBAR_WIDTH_DEFAULT)
        setOpen(true)
      }}
    >
      <div className="mx-auto h-full w-0.5 bg-transparent transition-colors group-hover/resize:bg-ring" />
    </div>
  )
}
