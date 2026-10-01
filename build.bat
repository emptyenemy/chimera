@echo off
REM Portable builds: build.bat [qt|webview|lite] [--post-only]. Node 22+ required.
setlocal
cd /d "%~dp0"
set FLAVOR=%~1
if "%FLAVOR%"=="" set FLAVOR=qt
if /I "%FLAVOR%"=="--post-only" (
    set FLAVOR=qt
    goto post
)
if /I "%~2"=="--post-only" goto post
if /I "%FLAVOR%"=="qt" goto variant_qt
if /I "%FLAVOR%"=="webview" goto variant_webview
if /I "%FLAVOR%"=="lite" goto variant_lite
echo [!] Unknown flavor: %FLAVOR%. Use qt, webview or lite.
exit /b 2

:variant_qt
set VARIANT=--enable-plugin=pyside6 --include-module=ui.backend_qt --nofollow-import-to=webview,clr_loader,pythonnet
goto frontend
:variant_webview
set VARIANT=--include-module=ui.backend_webview --include-module=ui.tray_win32 --include-package=clr_loader --include-package=pythonnet --include-package=proxy_tools --include-package=bottle --include-package-data=clr_loader --include-package-data=pythonnet --nofollow-import-to=PySide6,shiboken6,ui.backend_qt
goto frontend
:variant_lite
set VARIANT=--include-module=ui.backend_webview --include-module=ui.tray_win32 --include-package=clr_loader --include-package=pythonnet --include-package=proxy_tools --include-package=bottle --include-package-data=clr_loader --include-package-data=pythonnet --nofollow-import-to=PySide6,shiboken6,ui.backend_qt

:frontend
python tools\build_env.py
if errorlevel 1 exit /b 1
if /I not "%FLAVOR%"=="qt" (
    python tools\fetch_webview.py
    if errorlevel 1 exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
    echo [!] Node 22+ is required to build the interface.
    exit /b 1
)
node -e "if (Number(process.versions.node.split('.')[0]) < 22) process.exit(1)"
if errorlevel 1 exit /b 1
pushd frontend
call npm ci
if errorlevel 1 goto frontend_failed
call npm run build
if errorlevel 1 goto frontend_failed
popd
for /f "delims=" %%v in ('python -c "from modules.version import VERSION, file_version; print(file_version(VERSION))"') do set FILEVER=%%v
if not defined FILEVER exit /b 1
python tools\set_flavor.py %FLAVOR%
if errorlevel 1 exit /b 1

python -m nuitka ^
    --standalone ^
    %VARIANT% ^
    --windows-console-mode=attach ^
    --windows-icon-from-ico=assets/logo/chimera.ico ^
    --assume-yes-for-downloads ^
    --output-filename=Chimera.exe ^
    --company-name=Chimera ^
    --product-name=Chimera ^
    --file-version=%FILEVER% ^
    --product-version=%FILEVER% ^
    --output-dir=build/%FLAVOR% ^
    --remove-output ^
    --include-data-dir=ui/web-next=ui/web-next ^
    --include-data-dir=modules/locales=modules/locales ^
    --include-data-dir=release-notes=release-notes ^
    --include-data-dir=themes=themes ^
    --include-data-dir=strategies=strategies ^
    --include-data-dir=lists=lists ^
    --include-data-files=upstream/zapret-discord-youtube/.service/hosts=upstream/zapret-discord-youtube/.service/hosts ^
    --include-data-files=strategies/assets=strategies/assets/=*.bin ^
    --include-data-files=modules/dns_providers.json=modules/dns_providers.json ^
    --include-data-files=assets/logo/chimera.ico=assets/logo/chimera.ico ^
    --include-data-files=upstream/tg-ws-proxy/proxy=upstream/tg-ws-proxy/proxy/=*.py ^
    --include-package=cryptography ^
    --include-package=certifi ^
    --include-module=ui.backend_browser ^
    --include-module=modules.service ^
    --include-module=modules._build_flavor ^
    --include-package=tui ^
    --include-package=textual ^
    --include-package-data=textual ^
    --include-package=rich ^
    --include-package=markdown_it ^
    --include-package=mdit_py_plugins ^
    --include-package=pygments ^
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
set BUILD_RESULT=%ERRORLEVEL%
python tools\set_flavor.py --clear
if not "%BUILD_RESULT%"=="0" exit /b %BUILD_RESULT%

:post
python tools\finish_build.py %FLAVOR%
exit /b %ERRORLEVEL%

:frontend_failed
popd
echo [!] Could not build the interface.
exit /b 1
