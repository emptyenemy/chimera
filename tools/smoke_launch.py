"""Launch the extracted exe through the Windows shell without arguments or a console."""

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.smoke_build import _cli_checks_while_running, _free_port, _wait_cdp  # noqa: E402


class ShellInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("priority", ctypes.c_long), ("flags", wintypes.DWORD),
                ("exe", wintypes.WCHAR * 260)]


class ShellProcess:
    def __init__(self, exe):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetProcessId.argtypes = [wintypes.HANDLE]
        self.kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        self.kernel.GetStdHandle.restype = wintypes.HANDLE
        self.kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        info = ShellInfo()
        info.cbSize, info.fMask, info.nShow = ctypes.sizeof(info), 0x40 | 0x100, 1
        info.lpVerb, info.lpFile, info.lpDirectory = "open", str(exe), str(exe.parent)
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellInfo)]
        streams = [(kind, self.kernel.GetStdHandle(kind)) for kind in (-10, -11, -12)]
        try:
            # Explorer supplies no console streams. Never leak the test runner's pipes.
            for kind, _handle in streams:
                self.kernel.SetStdHandle(kind, None)
            opened = shell.ShellExecuteExW(ctypes.byref(info))
            error = ctypes.get_last_error()
        finally:
            for kind, handle in streams:
                self.kernel.SetStdHandle(kind, handle)
        if not opened:
            raise ctypes.WinError(error)
        self.handle = info.hProcess
        self.pid = self.kernel.GetProcessId(self.handle)
        self.returncode = None

    def poll(self):
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = None if code.value == 259 else code.value
        return self.returncode

    def close(self):
        if self.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.pid), "/T", "/F"], capture_output=True, timeout=15)
        self.kernel.CloseHandle(self.handle)


def creation_time(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return 0
    times = [wintypes.FILETIME() for _ in range(4)]
    try:
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            return 0
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def processes(root_pid, owned=()):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessInfo)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessInfo)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    entry = ProcessInfo()
    entry.dwSize = ctypes.sizeof(entry)
    rows = []
    try:
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            rows.append((entry.pid, entry.parent, entry.exe))
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    started = creation_time(root_pid)
    if not started:
        raise RuntimeError("The launched exe has exited")
    # A dead parent's PID can be reused by Chimera while its old children survive.
    rows = [(pid, parent, name) for pid, parent, name in rows if creation_time(pid) >= started]
    family = {root_pid, *owned}
    for _ in range(10):
        previous = len(family)
        family.update(pid for pid, parent, name in rows if parent in family)
        if len(family) == previous:
            break
    return [(pid, name) for pid, parent, name in rows if pid in family]


def visible_windows(pids):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = []

    def visit(handle, parameter):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value in pids and user.IsWindowVisible(handle):
            title = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(handle, title, len(title))
            rect = wintypes.RECT()
            user.GetWindowRect(handle, ctypes.byref(rect))
            if "chimera" in title.value.lower() and rect.right > rect.left and rect.bottom > rect.top:
                found.append({"handle": int(handle), "pid": pid.value, "title": title.value,
                              "size": [rect.right - rect.left, rect.bottom - rect.top]})
        return True

    user.EnumWindows(callback_type(visit), 0)
    return found


def image_path(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.OpenProcess(0x1000, False, pid)
    try:
        path, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(path.value).resolve()
    finally:
        kernel.CloseHandle(process)


def run(build, flavor, screenshot=None, no_browser=False, timeout=90):
    if sys.platform != "win32":
        raise RuntimeError("Windows shell launch check requires Windows")
    with tempfile.TemporaryDirectory(prefix="chimera-doubleclick Кириллица ", ignore_cleanup_errors=True) as temporary:
        work = Path(temporary)
        app = work / "Chimera"
        shutil.copytree(build, app, ignore=shutil.ignore_patterns("config.json", "data"))
        assert not (app / "config.json").exists() and not (app / "data").exists()
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)
        env.pop("CHIMERA_NO_BROWSER", None)
        env.pop("CHIMERA_DATA", None)
        port = _free_port()
        env.update(CHIMERA_SMOKE="1", CHIMERA_INSTANCE_EVENT=rf"Local\Chimera_Launch_{os.getpid()}",
                   QTWEBENGINE_REMOTE_DEBUGGING=str(port), CHIMERA_SMOKE_NO_BROWSER="1" if no_browser else "0",
                   LOCALAPPDATA=str(work / "user"))
        previous = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        # Explorer has no console. Detach this launcher too so Nuitka cannot attach to it.
        ctypes.windll.kernel32.FreeConsole()
        from modules.gui_stdio import prepare
        prepare()
        process = None
        try:
            process = ShellProcess(app / "Chimera.exe")
            _wait_cdp(port, process, timeout=timeout)
            state = subprocess.run([str(app / "Chimera.exe"), "status", "--json"],
                                   capture_output=True, env=env, timeout=30, check=True)
            owned = json.loads(state.stdout)["data"]["app"]["window_pids"]
            deadline = time.monotonic() + 30
            windows = []
            while not windows and time.monotonic() < deadline:
                family = processes(process.pid, owned)
                windows = visible_windows({pid for pid, name in family})
                if not windows:
                    time.sleep(0.1)
            if not windows:
                raise RuntimeError("The exe has no visible Chimera window")
            native = any(name.lower() == "msedgewebview2.exe" for pid, name in family)
            if (flavor == "webview" or no_browser) and not native:
                raise RuntimeError("The packaged native window did not open")
            if native:
                engines = [image_path(pid) for pid, name in family if name.lower() == "msedgewebview2.exe"]
                if not engines or not all(path.is_relative_to(app / "bin/webview2") for path in engines):
                    raise RuntimeError("The window used a system engine instead of the packaged runtime")
            print(json.dumps({"shell": "open", "arguments": [], "clean_config": True,
                              "flavor": flavor, "no_browser": no_browser, "visible": windows,
                              "packaged_runtime": native, "processes": [name for pid, name in family]}, ensure_ascii=False), flush=True)
            second = ShellProcess(app / "Chimera.exe")
            try:
                deadline = time.monotonic() + 10
                while second.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)
                if second.poll() != 0:
                    raise RuntimeError("Double-clicking again did not reuse the open window")
                after = visible_windows({pid for pid, name in processes(process.pid, owned)})
                if not after or {window["handle"] for window in after} != {window["handle"] for window in windows}:
                    raise RuntimeError("Second launch created a duplicate or lost the window")
            finally:
                second.close()
            command = ["node", str(ROOT / "tools/smoke_build.mjs"), str(port),
                       str(ROOT / "tools/smoke_checks.js"), "check"]
            if screenshot:
                screenshot = Path(screenshot).resolve()
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                command.append(str(screenshot))
            checked = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                     timeout=420, env={**env, "CHIMERA_SMOKE_TG_PORT": str(_free_port())})
            if checked.returncode:
                raise RuntimeError(f"UI checks failed: {checked.stderr[:1000]}")
            result = json.loads(checked.stdout.strip().splitlines()[-1])
            result["steps"] += _cli_checks_while_running(app, env, flavor)
            failed = [f"{step['name']}: {step.get('detail')}" for step in result["steps"] if not step["ok"] and not step.get("network")]
            if result["pageErrors"] or failed:
                diagnostic = subprocess.run([str(app / "Chimera.exe"), "autostart", "state", "--json"],
                                            capture_output=True, env=env, timeout=30)
                print(diagnostic.stdout.decode("utf-8", "replace"), flush=True)
                raise RuntimeError(f"Window checks failed: {failed}; page errors: {result['pageErrors']}")
            skipped = sum(str(step.get("detail", "")).startswith("пропуск:") for step in result["steps"])
            print(json.dumps({"ok": True, "steps": len(result["steps"]), "skipped": skipped,
                              "double_click_reused_window": True}, ensure_ascii=False), flush=True)
        finally:
            if process:
                process.close()
            os.environ.clear()
            os.environ.update(previous)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("--flavor", required=True, choices=("qt", "webview", "lite"))
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    run(args.build.resolve(), args.flavor, args.screenshot, args.no_browser, args.timeout)
