import type { ReactNode } from "react"

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
  return (
    <section
      data-page={id}
      data-testid={`page-${id}`}
      className="mx-auto flex w-full max-w-[1080px] flex-col gap-6 px-8 pt-7 pb-12"
    >
      <header className="flex items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  )
}
