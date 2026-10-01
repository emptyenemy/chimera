import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

import pytest

from ui.windows_job import WindowsJob


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process ownership")
def test_job_keeps_child_after_launcher_exits_and_kills_only_owned_processes():
    job = WindowsJob()
    # В Windows venv python.exe — обёртка, которая создаёт дополнительный процесс.
    executable = sys._base_executable
    outside = subprocess.Popen([executable, "-c", "import time; time.sleep(60)"])
    command = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])"
    launcher = subprocess.Popen([executable, "-c", command], creationflags=0x4)
    try:
        job.attach_and_resume(launcher)
        assert launcher.wait(timeout=10) == 0
        # Сигнал завершения процесса может опередить удаление его PID из Job Object.
        deadline = time.monotonic() + 5
        children = job.pids()
        while launcher.pid in children and time.monotonic() < deadline:
            time.sleep(0.01)
            children = job.pids()
        assert len(children) == 1 and launcher.pid not in children and outside.pid not in children
        job.close()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        child = kernel.OpenProcess(0x100000, False, children[0])
        if child:
            try:
                assert kernel.WaitForSingleObject(child, 5000) == 0
            finally:
                kernel.CloseHandle(child)
        assert outside.poll() is None
    finally:
        job.close()
        if launcher.poll() is None:
            launcher.kill()
        launcher.wait(timeout=10)
        outside.kill()
        outside.wait(timeout=10)
