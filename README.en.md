<p align="center"><img src="assets/logo/chimera.svg" alt="Chimera" width="104"></p>

<h1 align="center">Chimera</h1>

<p align="center"><a href="README.md">Русский</a> · <b>English</b></p>

<p align="center">
  <a href="https://github.com/emptyenemy/chimera/releases/latest"><b>Download</b></a> ·
  <a href="https://emptyenemy.github.io/chimera/en/">Website</a> ·
  <a href="docs/ROADMAP.md">Roadmap</a> ·
  <a href="https://github.com/emptyenemy/chimera/issues/new">Report a problem</a>
</p>

**Chimera** brings tools for accessing blocked services in Russia into one Windows application. Strategies, proxies, Telegram proxy, hosts overrides and DNS share domain lists. The source code is available under the MIT license.

## Quick start

The following editions are being prepared for the next update; available archives are listed on Releases.

1. Download an archive from [Releases](https://github.com/emptyenemy/chimera/releases/latest):
   - `Chimera-<version>-win64.zip`: Qt, including its own Chromium engine;
   - `Chimera-<version>-win64-webview.zip`: system WebView2, with a native Windows tray;
   - `Chimera-<version>-win64-lite.zip`: service, CLI and TUI; use `--browser` for the web interface.
2. Extract the archive and run `Chimera.exe`. For Lite, use commands from a terminal.
3. Enable a tool appropriate for your connection. Python, git and Node are not required for the packaged application.

Updates install only when requested in Settings. The updater keeps your build variant.

## Features

The tools work independently and share domain lists:

- **Strategies (zapret2 / winws2)**: DPI bypass through [bol-van/zapret2](https://github.com/bol-van/zapret2), with strategies ported from [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube).
- **Proxy (sing-box)**: VLESS, Trojan, Shadowsocks and VMess for selected domains. PAC mode works without administrator rights; TUN supports routing by application or all traffic.
- **Telegram proxy**: local MTProto proxy powered by [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy).
- **Hosts**: override system hosts entries using alternative DNS providers such as xbox, comss and malw.
- **DNS**: select system DNS, measure server response times and try changes with automatic rollback.
- **Checks**: RKN registry checks through [cheburcheck](https://github.com/LowderPlay/cheburcheck), plus domain reachability from your computer.
- **Agent setup**: bundled skill, instructions, versioned docs and JSON commands let your agent diagnose and configure Chimera at your request.
- **Share configurations**: export selected sections to a `.chimera` file; preview the contents before importing.
- **Import backups**: preview and restore through the window or CLI; save the current state before restoring and roll back on failure ([details, in Russian](docs/BACKUPS.md)).
- **CLI and TUI**: commands and a full-screen terminal interface for controlling the running application or service.
- **Live lists**: edits to `lists/*.txt` are validated and applied automatically.
- **Languages and themes**: Russian/English and system/light/dark themes, selectable in Settings.

## Stack and layout

Python implements the managers in `modules/`. The interface uses shadcn/ui on Base UI, React, TypeScript and Tailwind v4. The same frontend works with Qt, WebView2 and the local HTTP bridge. The bridge runs on loopback and requires a session token.

```
main.py               entry point, elevation and mode selection
modules/              managers, configuration, CLI, control channel and translations
ui/                   API, state hub and window/browser backends
frontend/             Vite + React + TypeScript + shadcn/ui sources
ui/web-next/          generated frontend; ignored by git
tui/                  Textual interface and simple terminal menu
lists/                shared domain and subnet lists
strategies/           winws2 strategies, fake blobs and hostlists
assets/logo/          SVG logo and transparent application icon
tools/                build, dependency fetching and validation tools
skills/chimera/       instructions for local agents
upstream/             external projects, included as git submodules
data/                 local runtime data; ignored by git
```

Node 22+ is required to develop or build the frontend. Packaged users do not need Node. See [frontend documentation](docs/FRONTEND.md) and [build/release documentation](docs/RELEASES.md).

## Run from source

```powershell
git clone --recurse-submodules <repo-url>
git submodule update --init
pip install -r requirements.txt
python tools/fetch_bins.py
cd frontend
npm ci
npm run build
cd ..
python main.py
```

The application requests administrator rights for hosts, DNS, winws2 and TUN. PAC proxy mode and Telegram proxy also work without them.

## CLI and agents

The packaged executable is also the `chimera` command:

```powershell
Chimera.exe --help
Chimera.exe status --json
Chimera.exe agent-info --json
Chimera.exe docs
Chimera.exe tui
Chimera.exe tui --simple
Chimera.exe --browser
Chimera.exe path add
```

`path add` makes `chimera` available from any folder. Commands that manage active modules use the running application's or service's control channel. Lists, configuration, domain checks and logs also support offline operations. `chimera start` launches the window in the tray. CLI text can be selected with `--lang ru|en`.

See the [English CLI reference](docs/en/CLI.md) for commands, access levels, exit codes and JSON output. `chimera docs` reports documentation matching the installed version. [AGENTS.md](AGENTS.md) points to [skills/chimera](skills/chimera/SKILL.md), also included alongside the executable.

## Binary dependencies

`python tools/fetch_bins.py` installs pinned dependencies. sing-box archives are checked against SHA256:

- `bin/zapret-win-bundle/zapret-winws/`: winws2, Lua and WinDivert from [bol-van/zapret-win-bundle](https://github.com/bol-van/zapret-win-bundle). The pinned bundle commit must stay compatible with `upstream/zapret2`.
- `bin/sing-box/sing-box.exe`: also downloadable from the Proxy page; the version is pinned in `modules/proxy/manager.py`.

External projects are used as submodules. They are not modified by Chimera.

## Update external sources

Settings → Sources and updates checks sources individually or together. Updating Flowseal strategies regenerates `strategies/*.txt`. Versions pinned in code, including sing-box and fonts, require a source change.

For manual submodule updates:

```powershell
git submodule update --remote upstream/zapret2
git add upstream/zapret2
git commit -m "bump zapret2"
```

After updating `upstream/zapret-discord-youtube`, run `python tools/port_flowseal.py`.

## Development and builds

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
cd ..
build.bat qt
build.bat webview
build.bat lite
```

Each build includes CLI, Textual and the generated frontend. Output folders are `build/Chimera`, `build/Chimera-webview` and `build/Chimera-lite`.

Preview without opening the application: `python tools/ui_preview.py shot <folder>`. Validate a packaged build with `python tools/smoke_build.py <build-folder> --flavor qt|webview|lite`. Qt runs offscreen; the other variants use the HTTP bridge and headless Edge. `--full` changes system settings and is intended for disposable CI machines.

After changing CLI commands, regenerate both references with `python tools/gen_cli_docs.py`. Agent behavior changes belong in `skills/chimera/SKILL.md`, its version and `CHANGELOG.md`.

## Launch modes

`config.json` selects `interface`:

- **`ui`**: a Qt/WebView2 window or the browser bridge. Default for window builds.
- **`tui`**: the Textual client of the running application/service. The simple menu is available with `chimera tui --simple`.
- **`service`**: background process without a window or tray; default for Lite. It starts modules marked for autostart, exposes the command channel and watches domain lists.

```powershell
python main.py service install --dry-run
python main.py service install
python main.py service uninstall
python main.py service start
python main.py service stop
python main.py service status
python main.py service run
```

The background service uses a Windows Task Scheduler boot task running as SYSTEM, rather than the Service Control Manager. PAC autostart is skipped under SYSTEM because PAC writes to the current user's HKCU registry hive. TUN can be used by the service. When the service is running, the window skips its own autostarts and leaves service-owned processes running when closed.

Service logs are in `data/logs/service.log`. `data/service.pid` is informational; a named Windows mutex determines whether the service is running.

## Status and license

Early development. Current features and future plans are tracked in [docs/ROADMAP.md](docs/ROADMAP.md).

[MIT](LICENSE). The zapret2, tg-ws-proxy and zapret-discord-youtube upstream projects also use MIT.
