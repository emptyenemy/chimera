"""Папка программы в PATH пользователя: `chimera path add|remove|show`.

Правится только пользовательская переменная Path (HKCU\\Environment), системная не
трогается. После изменения окружению сообщается WM_SETTINGCHANGE — новые терминалы
подхватят Path без перезагрузки. Реестр спрятан за небольшим классом, чтобы тесты
подсовывали фальшивый.
"""

import ctypes
import os
import sys
from pathlib import Path

from modules import paths


class Registry:
    """Значение Path в HKCU\\Environment."""

    def get(self) -> str:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                value, _kind = winreg.QueryValueEx(k, "Path")
                return value
        except FileNotFoundError:
            return ""

    def set(self, value: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, value)

    def notify(self) -> None:
        try:
            # HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 3000, None)
        except (OSError, AttributeError):
            pass


def app_dir() -> Path:
    """Папка, где лежит chimera.exe (у собранной программы), либо корень репозитория."""
    return Path(sys.executable).parent if paths.IS_FROZEN else Path(__file__).resolve().parent.parent.parent


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip().strip('"')))).rstrip("\\/")


def _entries(value: str) -> list[str]:
    return [e for e in value.split(";") if e.strip()]


def contains(directory: Path, reg: Registry | None = None) -> bool:
    reg = reg or Registry()
    target = _norm(str(directory))
    return any(_norm(e) == target for e in _entries(reg.get()))


def add(directory: Path, reg: Registry | None = None) -> bool:
    """True — добавили, False — уже была."""
    reg = reg or Registry()
    if contains(directory, reg):
        return False
    entries = _entries(reg.get())
    entries.append(str(directory))
    reg.set(";".join(entries))
    reg.notify()
    return True


def remove(directory: Path, reg: Registry | None = None) -> bool:
    """True — убрали, False — её и не было."""
    reg = reg or Registry()
    target = _norm(str(directory))
    entries = _entries(reg.get())
    kept = [e for e in entries if _norm(e) != target]
    if len(kept) == len(entries):
        return False
    reg.set(";".join(kept))
    reg.notify()
    return True
