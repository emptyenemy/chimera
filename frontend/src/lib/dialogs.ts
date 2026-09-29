/* Подтверждение и ввод строки — вместо window.confirm()/prompt(). Вызываются откуда
   угодно (как в старом core.js), рисует их DialogHost (components/app/dialog-host.tsx). */

import { useSyncExternalStore } from "react"

export interface ConfirmOptions {
  title: string
  description?: string
  confirmText?: string
  cancelText?: string
  destructive?: boolean
}

export interface PromptOptions {
  title: string
  description?: string
  label?: string
  value?: string
  placeholder?: string
  confirmText?: string
  mono?: boolean
}

export type DialogRequest =
  | { kind: "confirm"; opts: ConfirmOptions; resolve: (ok: boolean) => void }
  | { kind: "prompt"; opts: PromptOptions; resolve: (value: string | null) => void }

const queue: DialogRequest[] = []
const listeners = new Set<() => void>()

function emit(): void {
  for (const fn of listeners) fn()
}

function push(req: DialogRequest): void {
  queue.push(req)
  emit()
}

/** Убрать показанный запрос из очереди (после ответа пользователя). */
export function dismissDialog(req: DialogRequest): void {
  const i = queue.indexOf(req)
  if (i >= 0) queue.splice(i, 1)
  emit()
}

export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => push({ kind: "confirm", opts, resolve }))
}

/** null — отмена. */
export function promptDialog(opts: PromptOptions): Promise<string | null> {
  return new Promise((resolve) => push({ kind: "prompt", opts, resolve }))
}

export function useDialogRequest(): DialogRequest | undefined {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => queue[0]
  )
}
