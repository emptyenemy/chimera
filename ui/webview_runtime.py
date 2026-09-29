"""Проверка установленного Evergreen WebView2 Runtime до создания окна."""
import sys

CLIENT = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


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
