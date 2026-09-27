@echo off
REM Builds CHIMERA (PySide6/QWebEngineView) into a standalone folder via Nuitka.
REM
REM Standalone, not onefile: all paths in the code resolve as
REM Path(__file__).parent... (see modules/appconfig.py, modules/winws/manager.py,
REM etc.) which needs a stable on-disk tree next to the exe. Onefile extracts to
REM a fresh temp dir on every run, which breaks that.
REM
REM bin/ (winws, sing-box) is not in the repo (.gitignore) - fetched/placed
REM separately. If missing at build time we warn: exe will build fine but
REM winws/proxy features won't work without it.
REM
REM ui/app.py picks the UI engine by name from config.json, which Nuitka cannot
REM see statically - hence --include-module for both shipped engines: backend_qt
REM (window) and backend_browser (a tab in the user's browser, stdlib only; note
REM the console is disabled here, so its startup URL is only opened, not printed).
REM pywebview is deliberately left out of the build (it pulls WebView2 through
REM .NET/clr_loader at runtime, invisible to the packager); picking "pywebview"
REM in a built exe falls back to the browser engine.

setlocal
REM Nuitka names the standalone folder after the entry script (main.py -> main.dist)
set DIST_DIR=build\main.dist

python -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --windows-uac-admin ^
    --assume-yes-for-downloads ^
    --company-name=CHIMERA ^
    --product-name=CHIMERA ^
    --file-version=1.0.0 ^
    --product-version=1.0.0 ^
    --output-dir=build ^
    --include-data-dir=ui/web=ui/web ^
    --include-data-dir=strategies=strategies ^
    --include-data-files=modules/dns_providers.json=modules/dns_providers.json ^
    --include-data-files=upstream/tg-ws-proxy/proxy=upstream/tg-ws-proxy/proxy/=*.py ^
    --include-package=cryptography ^
    --include-package=certifi ^
    --include-module=ui.backend_qt ^
    --include-module=ui.backend_browser ^
    main.py

if errorlevel 1 (
    echo.
    echo [!] Nuitka build failed, see output above.
    exit /b 1
)

if exist bin (
    echo Copying bin\ into %DIST_DIR%\bin ...
    xcopy /E /I /Y bin "%DIST_DIR%\bin" >nul
) else (
    echo.
    echo [!] bin\ folder not found - winws.exe/sing-box.exe not included in the build.
    echo     Place bin\ next to the exe in %DIST_DIR% before running.
)

echo.
echo Done: %DIST_DIR%\main.exe
endlocal
