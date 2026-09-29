import { Page } from "@/components/app/page"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { t } from "@/lib/i18n"

/** Заглушка страницы, которую ещё не перенесли из прежнего интерфейса. */
export function StubPage({ id, titleKey }: { id: string; titleKey: string }) {
  const title = t(titleKey)
  return (
    <Page id={id} title={title}>
      <Card data-testid={`stub-${id}`}>
        <CardHeader>
          <CardTitle>{t("stub.title")}</CardTitle>
          <CardDescription>{t("stub.desc", { page: title })}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">{t("stub.hint")}</p>
        </CardContent>
      </Card>
    </Page>
  )
}
