import type { ReactNode } from "react"
import { PanelLeftIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSidebar } from "@/components/ui/sidebar"
import { t } from "@/lib/i18n"

/** Обёртка страницы: колонка по центру и заголовок. data-page/data-testid нужны
    агентским проверкам (tools/ui_shot.mjs, tools/smoke_checks.js). */
export function Page({
  id,
  title,
  description,
  actions,
  children,
}: {
  id: string
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}) {
  const { toggleSidebar } = useSidebar()
  return (
    <section
      data-page={id}
      data-testid={`page-${id}`}
      className="mx-auto flex w-full min-w-0 max-w-[1080px] flex-col gap-6 px-4 pt-5 pb-12 md:px-8 md:pt-7"
    >
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-label={t("sidebar.expand")}
              data-testid="page-menu"
              onClick={toggleSidebar}
            >
              <PanelLeftIcon />
            </Button>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          </div>
          {description && <p className="text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  )
}
