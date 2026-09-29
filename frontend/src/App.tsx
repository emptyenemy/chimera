import { useEffect, useState, type CSSProperties } from "react"

import { AppSidebar } from "@/components/app/app-sidebar"
import { DialogHost } from "@/components/app/dialog-host"
import { SidebarResizer } from "@/components/app/sidebar-resizer"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/toast"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useCurrentPage } from "@/lib/router"
import {
  SIDEBAR_WIDTH_DEFAULT,
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
  loadSidebar,
  saveSidebar,
} from "@/lib/sidebar-state"
import { useUpdateNotice } from "@/lib/update-notice"
import { pageById } from "@/pages/registry"

function initialWidth(): number {
  const w = loadSidebar().width
  return typeof w === "number" && w > 0
    ? Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, w))
    : SIDEBAR_WIDTH_DEFAULT
}

export default function App() {
  const page = useCurrentPage()
  const [open, setOpen] = useState(() => !loadSidebar().collapsed)
  const [width, setWidth] = useState(initialWidth)
  useUpdateNotice()

  // свёрнутость и ширина переживают перезапуск (тот же ключ, что у старого фронта)
  useEffect(() => {
    saveSidebar({ collapsed: !open, width: width === SIDEBAR_WIDTH_DEFAULT ? null : width })
  }, [open, width])

  // новая страница открывается сверху
  useEffect(() => {
    document.getElementById("main")?.scrollTo(0, 0)
  }, [page])

  const Current = pageById(page).component

  return (
    <TooltipProvider delay={350}>
      <Toaster>
        <SidebarProvider
          open={open}
          onOpenChange={setOpen}
          style={{ "--sidebar-width": `${width}px` } as CSSProperties}
          className="h-svh min-h-0"
        >
          <AppSidebar />
          <SidebarResizer width={width} onWidth={setWidth} />
          <SidebarInset id="main" data-testid="main" className="h-svh overflow-y-auto overflow-x-hidden">
            <Current />
          </SidebarInset>
        </SidebarProvider>
        <DialogHost />
      </Toaster>
    </TooltipProvider>
  )
}
