"""Supply valid NUL handles when Explorer starts the exe without console streams."""

import ctypes
import os
import sys

_streams = []


def prepare():
    if sys.platform != "win32":
        return
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    for kind, name, mode in ((-10, "stdin", "r"), (-11, "stdout", "w"), (-12, "stderr", "w")):
        handle = kernel.GetStdHandle(kind)
        if handle and handle != ctypes.c_void_p(-1).value and kernel.GetFileType(handle):
            continue
        stream = open(os.devnull, mode, encoding="utf-8")
        if not kernel.SetStdHandle(kind, msvcrt.get_osfhandle(stream.fileno())):
            stream.close()
            raise ctypes.WinError(ctypes.get_last_error())
        _streams.append(stream)
        setattr(sys, name, stream)
        setattr(sys, f"__{name}__", stream)
