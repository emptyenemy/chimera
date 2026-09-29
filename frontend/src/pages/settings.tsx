/* Настройки: оформление, запуск и закрытие, обновления программы и компонентов, обмен
   конфигом, диагностика. Состояния в хабе нет: страница читает config.json и версии при
   открытии, повторный вход рисует кэш из стора сразу и обновляет данные в фоне. */

import { useEffect, useState } from "react"

import { Page } from "@/components/app/page"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { t } from "@/lib/i18n"
import { BackupsCard } from "@/pages/settings/backups"
import { DoctorCard } from "@/pages/settings/doctor"
import { GeneralCard, MaintenanceCard, ThemeCard, LanguageCard } from "@/pages/settings/general"
import { ShareCard } from "@/pages/settings/share"
import { refreshAutostart, refreshConfig } from "@/pages/settings/state"
import { refreshSources } from "@/pages/settings/sources"
import { AppUpdateCard, SourcesCard } from "@/pages/settings/updates"

const TABS = ["general", "updates", "tools"] as const
type Tab = (typeof TABS)[number]

const TAB_KEY = "chimera.settings.tab"

function loadTab(): Tab {
  try {
    const v = localStorage.getItem(TAB_KEY)
    if (TABS.includes(v as Tab)) return v as Tab
  } catch {
    /* хранилище недоступно — начинаем с первой вкладки */
  }
  return "general"
}

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>(loadTab)

  useEffect(() => {
    void refreshConfig()
    void refreshAutostart()
    void refreshSources()
  }, [])

  const pick = (v: string) => {
    setTab(v as Tab)
    try {
      localStorage.setItem(TAB_KEY, v)
    } catch {
      /* не критично */
    }
  }

  return (
    <Page id="settings" title={t("nav.settings")}>
      <Tabs value={tab} onValueChange={pick} className="gap-4">
        <TabsList data-testid="settings-tabs">
          {TABS.map((id) => (
            <TabsTrigger key={id} value={id} data-testid={`settings-tab-${id}`}>
              {t(`settings.tab.${id}`)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="general" className="flex flex-col gap-4">
          <ThemeCard />
          <LanguageCard />
          <GeneralCard />
          <MaintenanceCard />
        </TabsContent>
        <TabsContent value="updates" className="flex flex-col gap-4">
          <AppUpdateCard />
          <SourcesCard />
        </TabsContent>
        <TabsContent value="tools" className="flex flex-col gap-4">
          <ShareCard />
          <BackupsCard />
          <DoctorCard />
        </TabsContent>
      </Tabs>
    </Page>
  )
}
