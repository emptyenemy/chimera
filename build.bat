@echo off
REM Builds Chimera (PySide6/QWebEngineView) into a standalone folder via Nuitka:
REM build\Chimera\Chimera.exe plus the binaries it needs, versions.json and manifest.txt.
REM
REM   build.bat              full build (Nuitka + post steps)
REM   build.bat --post-only  post steps only, on an existing build\main.dist
REM
REM --include-data-dir silently skips "code-like" files (.bin, .dll, .exe, ...).
REM The strategies' fake blobs are .bin - without an explicit --include-data-files
REM rule winws2 fails in the built program (tests/test_build_bat.py guards this).
REM The tg-ws-proxy core ships as plain .py and is imported at runtime, so Nuitka
REM never sees its imports: every stdlib module it uses is listed explicitly
REM below (tests/test_build_bat.py checks the list against the core's imports).
REM lists/ and Flowseal's hosts file are read at runtime from next to the exe.
REM
REM --remove-output drops build\main.build (generated C and objects) afterwards;
REM rebuilds stay fast through Nuitka's own cache in %LOCALAPPDATA%\Nuitka.
REM
REM Standalone, not onefile: paths in the code resolve either as
REM Path(__file__).parent... (see modules/appconfig.py) or through modules/paths.py
REM (APP_DIR = the exe's folder when frozen/Nuitka, data/ next to it) - both need a
REM stable on-disk tree next to the exe. Onefile extracts to a fresh temp dir on
REM every run, which breaks that.
REM
REM bin/ (winws, sing-box) is not in the repo (.gitignore) - run
REM `python tools\fetch_bins.py` first (CI does). Only what the program uses is
REM copied: bin\sing-box\sing-box.exe and bin\zapret-win-bundle\zapret-winws\.
REM If missing we warn: the exe still builds, but winws/proxy won't work.
REM
REM The version comes from modules/version.py ("dev" in the repo, the tag in CI -
REM see tools/set_version.py); Windows wants four numbers: 0.3.0-beta.1 -> 0.3.0.1.
REM
REM ui/app.py picks the UI engine by name from config.json, which Nuitka cannot
REM see statically - hence --include-module for both shipped engines: backend_qt
REM (window) and backend_browser (a tab in the user's browser, stdlib only).
REM
REM The exe is also the `chimera` command line (modules/cli). --windows-console-mode=attach
REM makes it print into the console of the terminal it was started from and open no console
REM window of its own when started by double click. There is deliberately no admin
REM manifest for the exe: commands must not ask for rights on every call. The window
REM still elevates itself through UAC on start (main.py relaunch_as_admin).
REM pywebview is deliberately left out of the build (it pulls WebView2 through
REM .NET/clr_loader at runtime, invisible to the packager); picking "pywebview"
REM in a built exe falls back to the browser engine.
REM
REM Textual (chimera tui) imports its widgets lazily by name (textual.widgets.__getattr__) and
REM rich loads its Unicode width tables with importlib, so both go in with --include-package
REM (+ --include-package-data for their non-code files); markdown-it-py comes with rich.
REM The TUI keeps its CSS inside Python strings on purpose: no .tcss data files to lose.
REM
REM Same story for main.py's own mode dispatch: "interface" (ui/tui/service) is a
REM string from config.json, invisible to static analysis - tui.app and
REM modules.service need --include-module too, or a built exe would fail on
REM `Chimera.exe service run` / "interface": "tui" with a plain ImportError.

setlocal
REM Nuitka names the standalone folder after the entry script (main.py -> main.dist)
set NUITKA_DIST=build\main.dist
set OUT_DIR=build\Chimera

if /I "%~1"=="--post-only" goto post

for /f "delims=" %%v in ('python -c "from modules.version import VERSION, file_version; print(file_version(VERSION))"') do set FILEVER=%%v
if not defined FILEVER (
    echo [!] Could not read the version from modules\version.py.
    exit /b 1
)
echo Version: %FILEVER%

python -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=attach ^
    --windows-icon-from-ico=assets/logo/chimera.ico ^
    --assume-yes-for-downloads ^
    --output-filename=Chimera.exe ^
    --company-name=Chimera ^
    --product-name=Chimera ^
    --file-version=%FILEVER% ^
    --product-version=%FILEVER% ^
    --output-dir=build ^
    --remove-output ^
    --include-data-dir=ui/web=ui/web ^
    --include-data-dir=strategies=strategies ^
    --include-data-dir=lists=lists ^
    --include-data-files=upstream/zapret-discord-youtube/.service/hosts=upstream/zapret-discord-youtube/.service/hosts ^
    --include-data-files=strategies/assets=strategies/assets/=*.bin ^
    --include-data-files=modules/dns_providers.json=modules/dns_providers.json ^
    --include-data-files=assets/logo/chimera.ico=assets/logo/chimera.ico ^
    --include-data-files=upstream/tg-ws-proxy/proxy=upstream/tg-ws-proxy/proxy/=*.py ^
    --include-package=cryptography ^
    --include-package=certifi ^
    --include-module=ui.backend_qt ^
    --include-module=ui.backend_browser ^
    --include-module=modules.service ^
    --include-package=tui ^
    --include-package=textual ^
    --include-package-data=textual ^
    --include-package=rich ^
    --include-package=markdown_it ^
    --include-package=asyncio ^
    --include-package=logging ^
    --include-package=ctypes ^
    --include-package=urllib ^
    --include-package=http ^
    --include-module=argparse ^
    --include-module=base64 ^
    --include-module=collections ^
    --include-module=dataclasses ^
    --include-module=hashlib ^
    --include-module=hmac ^
    --include-module=os ^
    --include-module=random ^
    --include-module=re ^
    --include-module=socket ^
    --include-module=ssl ^
    --include-module=string ^
    --include-module=struct ^
    --include-module=sys ^
    --include-module=threading ^
    --include-module=time ^
    --include-module=typing ^
    main.py

if errorlevel 1 (
    echo.
    echo [!] Nuitka build failed, see output above.
    exit /b 1
)

:post
if not exist "%NUITKA_DIST%\Chimera.exe" (
    echo [!] %NUITKA_DIST%\Chimera.exe not found - nothing to finish.
    exit /b 1
)
if exist "%OUT_DIR%" rmdir /S /Q "%OUT_DIR%"
move "%NUITKA_DIST%" "%OUT_DIR%" >nul
if errorlevel 1 (
    echo [!] Could not move %NUITKA_DIST% to %OUT_DIR%.
    exit /b 1
)

if exist bin\sing-box\sing-box.exe (
    mkdir "%OUT_DIR%\bin\sing-box"
    copy /Y bin\sing-box\sing-box.exe "%OUT_DIR%\bin\sing-box\" >nul
) else (
    echo [!] bin\sing-box\sing-box.exe not found - the proxy will not work in this build.
)
if exist bin\zapret-win-bundle\zapret-winws\winws2.exe (
    xcopy /E /I /Y /Q bin\zapret-win-bundle\zapret-winws "%OUT_DIR%\bin\zapret-win-bundle\zapret-winws" >nul
) else (
    echo [!] bin\zapret-win-bundle\zapret-winws not found - strategies will not work in this build.
)

REM Agent files ship next to the exe (before the manifest, so self-update carries them):
REM an agent started in the program folder finds the pointer file and the skill.
if exist skills xcopy /E /I /Y /Q skills "%OUT_DIR%\skills" >nul
if exist AGENTS.md copy /Y AGENTS.md "%OUT_DIR%\" >nul

python tools\fetch_bins.py --versions "%OUT_DIR%\versions.json" >nul
if errorlevel 1 (
    echo [!] Could not write %OUT_DIR%\versions.json.
    exit /b 1
)

REM Nuitka ships msvcp140 from its own compiler (VS2019 = 14.29); Qt 6.11 needs a
REM newer one - with the old DLL the QtWebEngine renderer crashes (0xC0000005) and
REM the window stays blank. Use the copies PySide6 itself ships with.
python tools\fetch_bins.py --qt-runtime "%OUT_DIR%" >nul
if errorlevel 1 (
    echo [!] Could not put the Qt C++ runtime into %OUT_DIR%.
    exit /b 1
)

REM Last: the list of every file in the build. Self-update touches only files
REM from this list, so anything else next to the exe is never deleted.
python tools\fetch_bins.py --manifest "%OUT_DIR%" >nul
if errorlevel 1 (
    echo [!] Could not write %OUT_DIR%\manifest.txt.
    exit /b 1
)

REM Intermediate C sources and objects - dead weight once the build succeeded
if exist "build\main.build" rmdir /S /Q "build\main.build"

echo.
echo Done: %OUT_DIR%\Chimera.exe
endlocal
