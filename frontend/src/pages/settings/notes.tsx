import { HistoryIcon } from "lucide-react"

import { ReleaseNotes } from "@/components/app/release-notes"
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { t, currentLocale } from "@/lib/i18n"
import { releaseNotes } from "@/lib/release-notes"
import { useStore } from "@/lib/store"
import { CardTitleIcon } from "@/pages/settings/general"

interface NotesState {
  current?: string
  current_release?: { version: string; notes: string; url: string | null }
  latest?: string | null
  notes?: string
  update?: boolean
}

export function WhatsNewCard() {
  const state = useStore<NotesState>("selfupdate")
  const current = state?.current_release
  const newer = state?.update && state.current !== "dev" && state.latest
  const text = newer
    ? releaseNotes(state.latest!, state.notes ?? "", currentLocale())
    : current ? releaseNotes(current.version, current.notes, currentLocale()) : ""
  return (
    <Card data-testid="settings-release-notes">
      <CardHeader>
        <CardTitleIcon icon={HistoryIcon}>{t("settings.tab.notes")}</CardTitleIcon>
        <CardDescription>{t("settings.notes.version", { version: newer || current?.version || "—" })}</CardDescription>
      </CardHeader>
      <CardContent>
        {text ? <ReleaseNotes>{text}</ReleaseNotes> : (
          <Empty><EmptyHeader><EmptyTitle>{t("settings.notes.empty")}</EmptyTitle><EmptyDescription>{t("settings.notes.emptyHint")}</EmptyDescription></EmptyHeader></Empty>
        )}
      </CardContent>
    </Card>
  )
}
