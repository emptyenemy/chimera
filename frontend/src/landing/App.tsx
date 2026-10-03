import { useEffect, useState } from 'react'
import { ArrowDown, ArrowRight, Bot, Check, ChevronDown, Clipboard, FileUp, Code2, Globe, ListChecks, Monitor, Network, Radio, RotateCcw, Share2, Shield, SlidersHorizontal, Terminal, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Separator } from '@/components/ui/separator'
import { ReleaseNotes } from '@/components/app/release-notes'
import { releaseNotes } from '@/lib/release-notes'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

const repo = 'https://github.com/emptyenemy/chimera'
const en = document.documentElement.lang === 'en'
const rootUrl = new URL(en ? '../' : './', window.location.href)
const assetUrl = (name: string) => new URL(name, rootUrl).href
const t = (ru: string, english: string) => en ? english : ru

type Release = {
  tag_name: string
  html_url: string
  name: string
  body: string
  assets: { name: string; browser_download_url: string; size: number }[]
}

const features = [
  { icon: Shield, title: 'zapret2', text: t('Стратегии обхода DPI. Подберите рабочую для своей сети и проверьте доступность сайтов.', 'DPI bypass strategies. Choose one that works on your network and check website access.') },
  { icon: Network, title: t('Прокси', 'Proxy'), text: t('VLESS, Trojan, Shadowsocks и VMess через sing-box. PAC или TUN, маршрутизация по спискам сайтов.', 'VLESS, Trojan, Shadowsocks and VMess through sing-box. PAC or TUN, with website list routing.') },
  { icon: Radio, title: 'Telegram', text: t('Локальный MTProto-прокси на базе tg-ws-proxy. Подключение к Telegram по ссылке.', 'A local MTProto proxy powered by tg-ws-proxy. Connect Telegram with a link.') },
  { icon: Globe, title: 'Hosts + DNS', text: t('Провайдеры hosts, выбор DNS и проверка серверов. Настройки собраны в одном месте.', 'Hosts providers, DNS selection and server checks. All settings in one place.') },
  { icon: ListChecks, title: t('Диагностика', 'Diagnostics'), text: t('Проверка сайтов, DNS и состояния модулей. Команда explain показывает, почему сайт идёт этим маршрутом.', 'Check websites, DNS and module status. The explain command shows why a site takes its route.') },
  { icon: SlidersHorizontal, title: t('Под себя', 'Make it yours'), text: t('Готовые палитры и свой вариант, акцент Windows, скругления и плотность. Снимки настроек для сравнения и возврата.', 'Curated palettes and your own variant, Windows accent, corner radius and density. Settings snapshots for comparison and restore.') },
]

const faqs = [
  [t('Как агент настраивает Chimera?', 'How does an agent configure Chimera?'), t('Вы даёте своему агенту доступ к установленной Chimera и просите настроить её. Рядом с программой лежат AGENTS.md и skills/chimera/SKILL.md. Агент сверяет версии, читает справку, проводит диагностику и управляет программой через CLI. Изменения hosts, DNS, TUN и запуск обхода требуют вашей прямой просьбы.', 'Give your agent access to your Chimera installation and ask it to configure the app. AGENTS.md and skills/chimera/SKILL.md are included beside the executable. The agent checks versions, reads the docs, runs diagnostics and uses the CLI. Hosts, DNS, TUN changes and starting bypass require your explicit request.')],
  [t('Можно отправить другу свои настройки?', 'Can I send my settings to a friend?'), t('Да. В Настройках выберите разделы и экспортируйте файл .chimera. Друг увидит содержимое до применения и сможет выбрать нужные разделы. Ссылка прокси и секрет Telegram-прокси не экспортируются: они остаются у вас.', 'Yes. Select sections in Settings and export a .chimera file. Your friend can preview it before applying and choose which sections to import. Your proxy link and Telegram proxy secret are excluded from the export and stay with you.')],
  [t('Можно ли пробовать настройки без риска потерять доступ?', 'Can I try settings without risking my access?'), t('Да. Стратегию, включение hosts или режим TUN можно применить на пробу: Chimera проверит выбранные сайты и только после этого предложит оставить изменение, а при неудаче или истечении времени сама вернёт прежнее состояние. Отдельно хранится последняя проверенная конфигурация — кнопка «Вернуть как работало» применяет её в любой момент. Понять, почему конкретный сайт идёт тем или иным маршрутом, поможет chimera explain или Ctrl+E в терминале.', 'Yes. Apply a strategy, hosts toggle or TUN mode as a trial: Chimera checks the websites you choose before offering to keep the change, and reverts it on its own if a check fails or time runs out. A separate last verified configuration is kept too, restorable at any time. To see why a specific site takes a given route, use chimera explain or Ctrl+E in the terminal.')],
  [t('Зачем сразу несколько способов обхода?', 'Why include several bypass methods?'), t('Сети и блокировки отличаются. Для одних сайтов достаточно стратегии zapret2, для других нужен прокси или DNS. Chimera позволяет сочетать инструменты и применять их к выбранным спискам.', 'Networks and blocks differ. A zapret2 strategy may work for some sites; others need a proxy or DNS. Chimera lets you combine tools and use them with selected lists.')],
  [t('Какой вариант программы выбрать?', 'Which edition should I choose?'), t('Qt содержит собственный Chromium. WebView2 использует системный Runtime и имеет нативный трей. Lite работает через службу, CLI и TUI; веб-интерфейс открывается командой chimera --browser. Все варианты используют одни инструменты и команды.', 'Qt includes Chromium. WebView2 uses the system Runtime and includes a native tray. Lite runs as a service, CLI or TUI; use chimera --browser for the web interface. All editions use the same tools and commands.')],
  [t('Нужны Python, Node или git?', 'Do I need Python, Node or git?'), t('Для готовой программы — нет. Распакуйте архив и запустите Chimera.exe. Права администратора нужны для инструментов, меняющих системные настройки.', 'Not for a packaged release. Extract the archive and run Chimera.exe. Tools that change system settings require administrator privileges.')],
]

function LinkButton({ href, children, outline = false }: { href: string; children: React.ReactNode; outline?: boolean }) {
  return <Button size="lg" variant={outline ? 'outline' : 'default'} nativeButton={false} render={<a href={href} rel={href.startsWith('https:') ? 'noopener noreferrer' : undefined} />}>{children}</Button>
}

function CopyPrompt() {
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)
  const prompt = t('Настрой Chimera для моей сети. Сначала прочитай AGENTS.md и skills/chimera/SKILL.md рядом с программой, сверь версии через chimera agent-info --json и проведи диагностику. Покажи план настройки. После моего подтверждения примени изменения и проверь результат.', 'Configure Chimera for my network. First read AGENTS.md and skills/chimera/SKILL.md beside the app, check versions with chimera agent-info --json and run diagnostics. Show me your configuration plan. After my confirmation, apply the changes and verify the result.')
  async function copy() {
    try { await navigator.clipboard.writeText(prompt); setCopied(true); setFailed(false) }
    catch { setFailed(true) }
  }
  return <Card>
    <CardHeader><CardTitle>{t('Дайте агенту задачу', 'Give your agent a task')}</CardTitle><CardDescription>{t('Chimera уже умеет говорить с ним на языке команд.', 'Chimera already speaks the language of commands.')}</CardDescription></CardHeader>
    <CardContent><p className="leading-relaxed">{prompt}</p></CardContent>
    <CardFooter className="flex-wrap gap-3"><Button variant="outline" onClick={copy}>{copied ? <Check data-icon="inline-start" /> : <Clipboard data-icon="inline-start" />}{copied ? t('Скопировано', 'Copied') : t('Скопировать запрос', 'Copy prompt')}</Button>{failed && <span role="status" className="text-sm text-muted-foreground">{t('Выделите текст запроса и скопируйте вручную.', 'Select the prompt text and copy it manually.')}</span>}</CardFooter>
  </Card>
}

export default function Landing() {
  const [release, setRelease] = useState<Release | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    fetch('https://api.github.com/repos/emptyenemy/chimera/releases/latest', { signal: controller.signal, headers: { Accept: 'application/vnd.github+json' } })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json() })
      .then((data: Release) => { if (Array.isArray(data.assets) && typeof data.tag_name === 'string') setRelease(data) })
      .catch(() => {})
    return () => controller.abort()
  }, [])
  const released = release?.assets.find(a => /^Chimera-.+-win64\.zip$/.test(a.name))
  const downloadUrl = released?.browser_download_url ?? `${repo}/releases/latest`
  return <>
    <header className="border-b bg-background/95">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-4">
        <a className="flex items-center gap-2 text-lg font-semibold" href="#top"><img src={assetUrl('logo.svg')} alt="" className="size-7" />Chimera</a>
        <nav aria-label={t('Разделы', 'Navigation')} className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
          <a href="#features">{t('Возможности', 'Features')}</a><a href="#agents">{t('Для агентов', 'For agents')}</a><a href="#download">{t('Скачать', 'Download')}</a><a href="#news">{t('Что нового', 'What’s new')}</a><a href="#faq">FAQ</a>
        </nav>
        <div className="flex items-center gap-2"><Button variant="ghost" nativeButton={false} render={<a href={new URL(en ? './' : 'en/', rootUrl).href} lang={en ? 'ru' : 'en'} />}>{en ? 'Русский' : 'English'}</Button><Button variant="outline" nativeButton={false} render={<a href={repo} rel="noopener noreferrer" />}><Code2 data-icon="inline-start" />GitHub</Button></div>
      </div>
    </header>
    <main id="top" className="mx-auto flex max-w-6xl flex-col gap-24 px-5 pb-24 md:gap-32">
      <section className="flex flex-col items-center gap-7 pt-20 text-center md:pt-28">
        <Badge variant="outline"><Zap data-icon="inline-start" />{release ? `Chimera ${release.tag_name}` : t('Обход блокировок для Windows', 'Access blocked services on Windows')}</Badge>
        <h1 className="max-w-4xl text-4xl leading-tight font-semibold tracking-tight sm:text-6xl">{t('Обход блокировок.', 'Get past the blocks.')}<br /><span className="text-muted-foreground">{t('Всё под вашим контролем.', 'Keep control of your connection.')}</span></h1>
        <p className="max-w-2xl text-lg leading-relaxed text-muted-foreground">{t('Стратегии, прокси, Telegram, hosts и DNS в одном приложении. Настройте сами, поручите своему агенту или возьмите готовый конфиг у друга.', 'Strategies, proxy, Telegram, hosts and DNS in one app. Set it up yourself, ask your agent, or get a configuration from a friend.')}</p>
        <div className="flex flex-wrap justify-center gap-3"><LinkButton href={downloadUrl}><ArrowDown data-icon="inline-start" />{t('Скачать для Windows', 'Download for Windows')}</LinkButton><LinkButton outline href="#agents"><Bot data-icon="inline-start" />{t('Настроить с агентом', 'Set up with an agent')}</LinkButton></div>
        <p className="text-sm text-muted-foreground">Windows 10 / 11 · MIT · {release ? `${t('Последний релиз', 'Latest release')}: ${release.tag_name}` : t('Скачать текущий релиз с GitHub', 'Get the current release on GitHub')}</p>
        <Tabs defaultValue="strategies" className="mt-5 w-full text-left">
          <TabsList className="mx-auto"><TabsTrigger value="strategies">{t('Стратегии', 'Strategies')}</TabsTrigger><TabsTrigger value="lists">{t('Общие списки', 'Shared lists')}</TabsTrigger></TabsList>
          <TabsContent value="strategies"><img className="mt-3 w-full rounded-xl border" src={assetUrl(en ? 'img/app-strategies-en.png' : 'img/app-strategies.png')} alt={t('Страница стратегий в Chimera', 'Chimera strategies page')} fetchPriority="high" /></TabsContent>
          <TabsContent value="lists"><img className="mt-3 w-full rounded-xl border" src={assetUrl(en ? 'img/app-lists-en.png' : 'img/app-lists.png')} alt={t('Общие списки сайтов в Chimera', 'Chimera website lists')} loading="lazy" /></TabsContent>
        </Tabs>
      </section>

      <section id="features" className="flex flex-col gap-8">
        <div className="flex flex-col gap-3"><p className="text-sm text-muted-foreground">{t('Меньше рутины', 'Less manual work')}</p><h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('Настройте один раз. Используйте как удобно.', 'Set it up once. Use it your way.')}</h2></div>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <Card><CardHeader><Bot className="mb-3 size-7" /><CardTitle>{t('Агент может настроить за вас', 'Let your agent do the setup')}</CardTitle><CardDescription>{t('Скилл, инструкция и инструменты уже на месте.', 'The skill, instructions and tools are included.')}</CardDescription></CardHeader><CardContent><p className="text-sm leading-relaxed text-muted-foreground">{t('Проверка версии, диагностика, команды с JSON и документация вашей версии. Ваш агент может подобрать настройки и проверить результат.', 'Version checks, diagnostics, JSON commands and docs for your version. Your agent can choose settings and check the result.')}</p></CardContent><CardFooter><Button variant="link" nativeButton={false} render={<a href="#agents" />}>{t('Как это работает', 'How it works')}<ArrowRight data-icon="inline-end" /></Button></CardFooter></Card>
          <Card><CardHeader><Share2 className="mb-3 size-7" /><CardTitle>{t('Поделитесь рабочим конфигом', 'Share a working configuration')}</CardTitle><CardDescription>{t('Свою настройку — друзьям в одном файле.', 'Send your setup to friends in a single file.')}</CardDescription></CardHeader><CardContent><p className="text-sm leading-relaxed text-muted-foreground">{t('Выберите разделы и сохраните .chimera. Перед импортом видно, что будет применено; друг может взять только нужные настройки.', 'Choose sections and save a .chimera file. Preview it before importing; your friend can apply only the settings they need.')}</p></CardContent><CardFooter><Badge variant="secondary"><FileUp data-icon="inline-start" />{t('Экспорт → проверка → импорт', 'Export → preview → import')}</Badge></CardFooter></Card>
          <Card><CardHeader><RotateCcw className="mb-3 size-7" /><CardTitle>{t('Пробуйте без риска', 'Try it without risk')}</CardTitle><CardDescription>{t('Автооткат, если что-то пошло не так.', 'Rolls back on its own if something breaks.')}</CardDescription></CardHeader><CardContent><p className="text-sm leading-relaxed text-muted-foreground">{t('Стратегию, hosts или TUN можно включить на время: Chimera проверит выбранные сайты и только потом предложит оставить изменение, иначе вернёт прежнее состояние сама. Последняя проверенная конфигурация хранится отдельно — к ней можно вернуться в любой момент.', 'Turn on a strategy, hosts toggle or TUN mode temporarily: Chimera checks the sites you pick before offering to keep the change, or reverts it on its own otherwise. A separate last verified configuration lets you go back to what worked at any time.')}</p></CardContent><CardFooter><Badge variant="secondary"><RotateCcw data-icon="inline-start" />{t('Попробовать → проверить → оставить', 'Try → verify → keep')}</Badge></CardFooter></Card>
          <Card><CardHeader><ListChecks className="mb-3 size-7" /><CardTitle>{t('Списки применяются на лету', 'Lists update live')}</CardTitle><CardDescription>{t('Один список сайтов для нескольких инструментов.', 'One website list for multiple tools.')}</CardDescription></CardHeader><CardContent><p className="text-sm leading-relaxed text-muted-foreground">{t('Правьте списки в интерфейсе, командой, в lists/*.txt или прямо в терминале — Ctrl+S сохраняет, доступны отмена и повтор. Работающая Chimera подхватывает изменения за пару секунд.', 'Edit lists in the app, with a command, in lists/*.txt, or right in the terminal — Ctrl+S saves, with undo and redo. Running Chimera picks up changes within seconds.')}</p></CardContent><CardFooter><Badge variant="secondary">{t('Без перезапуска приложения', 'No app restart needed')}</Badge></CardFooter></Card>
        </div>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">{features.map(({ icon: Icon, title, text }) => <Card key={title} size="sm"><CardHeader><CardTitle className="flex items-center gap-2"><Icon className="size-5" />{title}</CardTitle></CardHeader><CardContent><p className="text-sm leading-relaxed text-muted-foreground">{text}</p></CardContent></Card>)}</div>
      </section>

      <section id="agents" className="flex flex-col gap-8">
        <div className="flex flex-col gap-3"><Badge variant="outline" className="w-fit">CLI · JSON · Skill</Badge><h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('Ваш агент знает, что делать.', 'Your agent knows what to do.')}</h2><p className="max-w-2xl text-lg text-muted-foreground">{t('Для управления есть команды, для принятия решений — диагностика и документация. Вы задаёте цель, агент работает с Chimera.', 'Commands for control, diagnostics and documentation for decisions. You set the goal; your agent works with Chimera.')}</p></div>
        <div className="grid items-start gap-5 md:grid-cols-2"><CopyPrompt /><Card><CardHeader><CardTitle>{t('Понятный первый шаг', 'A clear first step')}</CardTitle><CardDescription>{t('Версии, справка и диагностика из терминала.', 'Versions, help and diagnostics from the terminal.')}</CardDescription></CardHeader><CardContent><pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs leading-8 sm:text-sm"><code>{'chimera agent-info --json\nchimera docs\nchimera doctor --json\nchimera lists validate'}</code></pre></CardContent><CardFooter><Button variant="link" nativeButton={false} render={<a href={`${repo}/blob/main/skills/chimera/SKILL.md`} rel="noopener noreferrer" />}>{t('Скилл Chimera', 'Chimera skill')}<ArrowRight data-icon="inline-end" /></Button></CardFooter></Card></div>
        <div className="grid gap-6 md:grid-cols-3">{[
          [t('1. Прочитать инструкции', '1. Read the instructions'), t('AGENTS.md указывает на скилл, CLI сообщает версию и доступные команды.', 'AGENTS.md points to the skill. The CLI reports its version and available commands.')],
          [t('2. Проверить вашу сеть', '2. Check your network'), t('Статус модулей, проверка сайтов и DNS помогают подобрать способ обхода.', 'Module status, website checks and DNS diagnostics help choose a bypass method.')],
          [t('3. Настроить и проверить', '3. Configure and verify'), t('По вашей просьбе агент применяет настройки и проверяет, что всё работает.', 'At your request, the agent applies settings and verifies that they work.')],
        ].map(([title, text]) => <div key={title} className="flex flex-col gap-3"><h3 className="font-medium">{title}</h3><p className="text-sm leading-relaxed text-muted-foreground">{text}</p></div>)}</div>
      </section>

      <section id="download" className="flex flex-col gap-8">
        <div className="flex flex-col gap-3"><h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('Окно, терминал или служба.', 'Window, terminal or service.')}</h2><p className="max-w-2xl text-lg text-muted-foreground">{t('Три варианта для Windows. Один набор инструментов, CLI во всех.', 'Three editions for Windows. The same tools, with CLI in every edition.')}</p></div>
        <Tabs defaultValue="qt"><TabsList><TabsTrigger value="qt"><Monitor />Qt</TabsTrigger><TabsTrigger value="webview">WebView2</TabsTrigger><TabsTrigger value="lite"><Terminal />Lite</TabsTrigger></TabsList>{[
          { id: 'qt', title: t('Самостоятельное окно', 'A self-contained window'), text: t('Собственный Chromium в комплекте. Оконный интерфейс, трей, CLI и TUI.', 'Includes Chromium. Window interface, tray, CLI and TUI.'), suffix: '' },
          { id: 'webview', title: t('Системный WebView2', 'System WebView2'), text: t('Использует Microsoft Edge WebView2 Runtime. Нативный трей; при отсутствии Runtime доступен браузерный интерфейс.', 'Uses Microsoft Edge WebView2 Runtime. Native tray; the browser interface is available if Runtime is missing.'), suffix: '-webview' },
          { id: 'lite', title: t('Компактный вариант', 'The compact edition'), text: t('Служба, команды и полноэкранный TUI. Тот же интерфейс в браузере: chimera --browser.', 'Service, commands and a full-screen TUI. The same UI in your browser: chimera --browser.'), suffix: '-lite' },
        ].map(({ id, title, text, suffix }) => {
          const archive = release?.assets.find(a => a.name.endsWith(`-win64${suffix}.zip`))
          return <TabsContent key={id} value={id}><Card className="mt-3"><CardHeader><CardTitle>{title}</CardTitle><CardDescription>{text}</CardDescription></CardHeader><CardContent><p className="text-sm text-muted-foreground">{archive ? `${release?.tag_name} · ${Math.round(archive.size / 1048576)} ${t('МБ', 'MB')}` : t('Вариант появится с ближайшим релизом. Доступные архивы — на GitHub.', 'This edition will be available with the next release. Find current archives on GitHub.')}</p></CardContent><CardFooter><LinkButton href={archive?.browser_download_url ?? `${repo}/releases/latest`}><ArrowDown data-icon="inline-start" />{archive ? t('Скачать', 'Download') : t('Текущий релиз', 'Current release')}</LinkButton></CardFooter></Card></TabsContent>
        })}</Tabs>
        <Card><CardHeader><Terminal className="mb-3 size-7" /><CardTitle>{t('Терминал без мыши', 'A mouse-free terminal')}</CardTitle><CardDescription>{t('Меню, списки и разбор маршрута — с клавиатуры.', 'Menus, lists and route checks — all from the keyboard.')}</CardDescription></CardHeader><CardContent><p className="text-sm leading-relaxed text-muted-foreground">{t('Стрелки или WASD выбирают пункт, Enter подтверждает, Esc возвращает назад. Списки сайтов редактируются прямо в терминале: Ctrl+S сохраняет, работают отмена и повтор. Двоеточие открывает командную строку с историей — команды CLI выполняются без выхода из интерфейса, секреты скрыты. Ctrl+E в любом разделе объясняет, почему сайт идёт выбранным маршрутом.', 'Arrows or WASD move the selection, Enter confirms, Esc goes back. Edit website lists right in the terminal: Ctrl+S saves, with undo and redo. A colon opens a command line with history — CLI commands run without leaving the interface, and secrets stay hidden. Ctrl+E in any section explains why a site takes the route it does.')}</p></CardContent><CardFooter><Button variant="link" nativeButton={false} render={<a href={`${repo}/blob/main/docs/CLI.md#tui`} rel="noopener noreferrer" />}><code>chimera tui</code><ArrowRight data-icon="inline-end" /></Button></CardFooter></Card>
        <Alert><Terminal /><AlertTitle>{t('Команды есть во всех вариантах', 'Commands in every edition')}</AlertTitle><AlertDescription><code>chimera --help</code>{t(' показывает команды, доступные в установленном варианте.', ' lists the commands available in your edition.')}</AlertDescription></Alert>
      </section>

      <section id="news" className="flex flex-col gap-7">
        <h2 className="text-3xl font-semibold tracking-tight">{t('Что нового', 'What’s new')}</h2>
        <Card><CardHeader><CardTitle>{release?.name || t('История релизов', 'Release history')}</CardTitle><CardDescription>{release?.tag_name || t('Изменения опубликованных версий Chimera', 'Changes in published Chimera versions')}</CardDescription></CardHeader>
          <CardContent>{release?.body ? <ReleaseNotes>{releaseNotes(release.tag_name, release.body, en ? 'en' : 'ru')}</ReleaseNotes> : <p className="text-muted-foreground">{t('Не удалось загрузить список изменений. Он доступен на странице релизов GitHub.', 'The release notes could not be loaded. Read them on the GitHub releases page.')}</p>}</CardContent>
          <CardFooter><LinkButton outline href={release?.html_url || `${repo}/releases`}>{t('Страница релиза', 'Release page')}<ArrowRight data-icon="inline-end" /></LinkButton></CardFooter>
        </Card>
      </section>

      <section id="faq" className="flex flex-col gap-7"><h2 className="text-3xl font-semibold tracking-tight">{t('Частые вопросы', 'Frequently asked questions')}</h2><div className="flex flex-col gap-2">{faqs.map(([question, answer]) => <Collapsible key={question} className="border-b py-3"><CollapsibleTrigger render={<Button variant="ghost" className="h-auto w-full justify-between gap-4 py-3 whitespace-normal text-left" />}><span>{question}</span><ChevronDown data-icon="inline-end" /></CollapsibleTrigger><CollapsibleContent><p className="px-3 pt-2 pb-5 text-sm leading-relaxed text-muted-foreground">{answer}</p></CollapsibleContent></Collapsible>)}</div></section>
      <section className="flex flex-col items-center gap-5 text-center"><h2 className="text-3xl font-semibold tracking-tight">{t('Открытый код. Общий опыт.', 'Open source. Shared experience.')}</h2><p className="max-w-xl text-muted-foreground">{t('Нашли рабочую настройку — поделитесь. Нашли проблему — расскажите. Chimera развивается вместе с пользователями.', 'Found a working setup? Share it. Found a problem? Tell us. Chimera grows with its users.')}</p><div className="flex flex-wrap justify-center gap-3"><LinkButton outline href={`${repo}/discussions`}>{t('Обсуждения', 'Discussions')}<ArrowRight data-icon="inline-end" /></LinkButton><LinkButton outline href={`${repo}/issues`}>{t('Сообщить о проблеме', 'Report an issue')}</LinkButton><LinkButton outline href={repo}><Code2 data-icon="inline-start" />{t('Исходный код', 'Source code')}</LinkButton></div></section>
    </main>
    <Separator /><footer className="mx-auto flex max-w-6xl flex-wrap justify-between gap-4 px-5 py-7 text-sm text-muted-foreground"><span>Chimera · MIT</span><a href={`${repo}/releases`}>{t('История релизов', 'Release history')}</a></footer>
  </>
}
