/* Тосты: тонкая обёртка над менеджером Toast из shadcn (Base UI). Тосты можно
   показывать откуда угодно, не только из компонентов — менеджер создан вне React. */

import { toast } from "@/components/ui/toast"

type Kind = "success" | "error" | "info" | "warning"

function show(type: Kind, title: string, description?: string): void {
  toast.add({ title, description, type, timeout: type === "error" ? 6000 : 4000 })
}

export const notify = {
  success: (title: string, description?: string) => show("success", title, description),
  error: (title: string, description?: string) => show("error", title, description),
  info: (title: string, description?: string) => show("info", title, description),
  warning: (title: string, description?: string) => show("warning", title, description),
}
