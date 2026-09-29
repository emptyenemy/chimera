/* Черновики полей с отложенным сохранением. Страница рисует поля из стора, поэтому без
   черновика любой тик хаба стёр бы то, что пользователь напечатал, но что ещё не долетело
   до бэкенда. Черновик живёт, пока сохранение не подтвердилось. */

import { useCallback, useEffect, useRef, useState } from "react"

export interface Draft<T extends object> {
  /** Текущий черновик для отрисовки (null — правок нет). */
  value: T | null
  /** Актуальный черновик для обработчиков и таймеров (в отрисовке не читать). */
  read: () => T | null
  update: (part: Partial<T>) => void
  /** Сбросить, только если за время сохранения не появилось новых правок. */
  clearIf: (snapshot: T | null) => void
}

export function useDraft<T extends object>(): Draft<T> {
  const ref = useRef<T | null>(null)
  const [value, setValue] = useState<T | null>(null)
  const update = useCallback((part: Partial<T>) => {
    ref.current = { ...(ref.current ?? {}), ...part } as T
    setValue(ref.current)
  }, [])
  const clearIf = useCallback((snapshot: T | null) => {
    if (ref.current !== snapshot) return
    ref.current = null
    setValue(null)
  }, [])
  const read = useCallback(() => ref.current, [])
  return { value, read, update, clearIf }
}

/** Отложенный вызов: schedule() переставляет таймер, flush() выполняет сразу, если он ждал. */
export function useDebounced(fn: () => void, delay = 500) {
  const timer = useRef(0)
  const latest = useRef(fn)
  useEffect(() => {
    latest.current = fn
  })
  useEffect(() => () => clearTimeout(timer.current), [])
  const schedule = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      timer.current = 0
      latest.current()
    }, delay)
  }, [delay])
  const flush = useCallback(() => {
    if (!timer.current) return
    clearTimeout(timer.current)
    timer.current = 0
    latest.current()
  }, [])
  return { schedule, flush }
}
