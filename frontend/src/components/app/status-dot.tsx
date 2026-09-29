import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const dotVariants = cva("inline-block size-2 shrink-0 rounded-full", {
  variants: {
    tone: {
      off: "bg-muted-foreground/60",
      on: "bg-success ring-3 ring-success/20",
      warn: "bg-warning ring-3 ring-warning/20",
      err: "bg-destructive ring-3 ring-destructive/20",
    },
  },
  defaultVariants: { tone: "off" },
})

/** Точка состояния: серая — выключено, зелёная — работает, жёлтая — внимание, красная — ошибка. */
export function StatusDot({ tone, className }: VariantProps<typeof dotVariants> & { className?: string }) {
  return <span aria-hidden="true" className={cn(dotVariants({ tone }), className)} />
}
