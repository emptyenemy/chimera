import type { ReactNode } from "react"
import { ChevronDownIcon, type LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"

/** Сворачиваемый раздел «Дополнительно» / «Логи»: карточка, свёрнутая по умолчанию. */
export function Fold({
  icon: Icon,
  title,
  testId,
  children,
}: {
  icon: LucideIcon
  title: string
  testId: string
  children: ReactNode
}) {
  return (
    <Card size="sm" data-testid={testId}>
      <CardContent>
        <Collapsible>
          <CollapsibleTrigger
            data-testid={`${testId}-toggle`}
            render={<Button variant="ghost" className="w-full justify-start [&[data-panel-open]>svg:last-child]:rotate-180" />}
          >
            <Icon data-icon="inline-start" />
            {title}
            <ChevronDownIcon data-icon="inline-end" className="ml-auto transition-transform" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="pt-4">{children}</div>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}
