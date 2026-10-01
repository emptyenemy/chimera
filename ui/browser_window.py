"""A dedicated Chromium app window, with its own profile and process."""

import ctypes
import os
import subprocess
from ctypes import wintypes
from pathlib import Path

from modules import paths


def executable():
    for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if not root:
            continue
        for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            candidate = Path(root) / relative
            if candidate.is_file():
                return candidate
    return None


class BrowserWindow:
    def __init__(self, url):
        program = executable()
        if program is None:
            raise RuntimeError("No Chromium browser is available")
        profile = paths.DATA_DIR / "browser-profile"
        command = [str(program), f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                   "--no-default-browser-check", "--disable-background-mode"]
        if os.environ.get("CHIMERA_SMOKE") == "1":
            port = os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING")
            if port:
                command.append(f"--remote-debugging-port={int(port)}")
        from ui.windows_job import WindowsJob
        self.job = WindowsJob()
        self.process = None
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            creationflags=0x4)
            self.job.attach_and_resume(self.process)
        except Exception:
            if self.process is not None:
                self.process.kill()
                self.process.wait(timeout=10)
            self.job.close()
            raise

    def pids(self):
        return self.job.pids()

    def running(self):
        return bool(self._windows())

    def _windows(self):
        owned = set(self.pids())
        found = []
        user = ctypes.windll.user32
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(window, parameter):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            if pid.value in owned and user.IsWindowVisible(window):
                found.append(window)
            return True

        user.EnumWindows(callback_type(visit), 0)
        return found

    def show(self):
        user = ctypes.windll.user32
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        for window in self._windows():
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)

    def close(self):
        self.job.close()
        if self.process is not None:
            self.process.wait(timeout=15)
