"""Переносимый WebView2 и запасная проверка установленного Evergreen Runtime."""
import os
import subprocess
import sys
from modules import paths

CLIENT = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def bundled():
    folder = paths.APP_DIR / "bin/webview2"
    required = ("msedgewebview2.exe", "msedge.dll", "icudtl.dat", "resources.pak")
    return folder if all((folder / name).is_file() for name in required) else None


def prepare():
    folder = bundled()
    if folder is not None and sys.platform == "win32" and sys.getwindowsversion().build < 22000:
        # Fixed runtimes >=120 require AppContainer read access on Windows 10.
        icacls = os.path.join(os.environ["WINDIR"], "System32", "icacls.exe")
        for sid in ("S-1-15-2-1", "S-1-15-2-2"):
            subprocess.run([icacls, str(folder), "/grant", f"*{sid}:(OI)(CI)(RX)"], check=True,
                           capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    return folder


def installed() -> bool:
    if sys.platform != "win32":
        return True
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, CLIENT, 0, winreg.KEY_READ | view) as key:
                    version = winreg.QueryValueEx(key, "pv")[0]
                if isinstance(version, str) and version not in ("", "0.0.0.0"):
                    return True
            except OSError:
                pass
    return False
