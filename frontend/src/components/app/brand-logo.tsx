import { cn } from "cn"

import { LOGO_PATH } from "@/assets/logo-path"

/** Знак Chimera. Цвет — текущий цвет текста, размер — от родителя. */
export function BrandLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={cn("size-full", className)} data-testid="brand-logo">
      <path fill="currentColor" fillRule="evenodd" d={LOGO_PATH} />
    </svg>
  )
}
