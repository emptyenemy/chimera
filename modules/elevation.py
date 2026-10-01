"""Explicit UAC relaunch; opening the interface itself needs no elevation."""

import ctypes
import subprocess
import sys

from modules import paths


def wait_for_process(pid):
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    process = kernel.OpenProcess(0x00100000, False, pid)
    if process:
        try:
            if kernel.WaitForSingleObject(process, 20000) != 0:
                raise RuntimeError("Previous window did not close")
        finally:
            kernel.CloseHandle(process)


def relaunch(argv=None) -> bool:
    if sys.platform != "win32":
        return False
    args = list(sys.argv[1:] if argv is None else argv)
    if not any(flag in args for flag in ("--window", "--browser", "--tray")):
        args.insert(0, "--window")
    if not paths.IS_FROZEN:
        args.insert(0, str(paths.APP_DIR / "main.py"))
    shell = ctypes.windll.shell32.ShellExecuteW
    shell.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                     ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell.restype = ctypes.c_void_p
    try:
        result = shell(None, "runas", sys.executable, subprocess.list2cmdline(args), str(paths.APP_DIR), 1)
        return bool(result and result > 32)
    except OSError:
        return False
