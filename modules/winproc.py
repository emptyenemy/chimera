"""Быстрые системные запросы через WinAPI (ctypes), без subprocess.

Хаб опрашивает статусы модулей каждые 2-3 c, и раньше каждый опрос winws/proxy
поднимал `tasklist` (или несколько) — это отдельный cmd.exe + чтение вывода,
десятки миллисекунд впустую. ToolHelp32Snapshot даёт тот же список PID
напрямую из ядра за доли миллисекунды и без побочных процессов.
"""

import ctypes
from ctypes import wintypes

_kernel32 = ctypes.windll.kernel32

TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
_MAX_PATH = 260


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * _MAX_PATH),
    ]


_kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


def pids_by_name(image_name: str) -> list[int]:
    """PID всех живых процессов с именем образа `image_name` (без учёта регистра).

    Снапшот системный (как у tasklist) — попадают и чужие процессы: winws2/
    sing-box, оставшиеся от прошлой сессии программы или запущенные не нами.
    Пустой список — снапшот не удалось снять (крайне маловероятно) или
    совпадений нет.
    """
    target = image_name.lower()
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, _INVALID_HANDLE_VALUE):
        return []
    pids: list[int] = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        found = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() == target:
                pids.append(entry.th32ProcessID)
            found = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return pids


# --- статус службы SCM (Get-Service без PowerShell) --------------------------

_advapi32 = ctypes.windll.advapi32

_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SERVICE_RUNNING = 0x00000004


class _SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwServiceFlags", wintypes.DWORD),
    ]


_advapi32.OpenSCManagerW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
_advapi32.OpenSCManagerW.restype = wintypes.HANDLE
_advapi32.OpenServiceW.argtypes = (wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD)
_advapi32.OpenServiceW.restype = wintypes.HANDLE
_advapi32.QueryServiceStatusEx.argtypes = (
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)
_advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
_advapi32.CloseServiceHandle.argtypes = (wintypes.HANDLE,)


def service_status(name: str) -> str | None:
    """Статус службы SCM: 'RUNNING' / 'STOPPED' / None (не установлена).

    То же самое, что `(Get-Service -Name name).Status`, но без PowerShell —
    прямой запрос в Service Control Manager (доли миллисекунды вместо ~150-200 мс
    на поднятие powershell.exe). Не требует прав админа — SERVICE_QUERY_STATUS
    доступен на чтение большинству служб для обычного пользователя.
    """
    scm = _advapi32.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not scm:
        return None
    try:
        svc = _advapi32.OpenServiceW(scm, name, _SERVICE_QUERY_STATUS)
        if not svc:
            return None  # не установлена (или нет доступа — трактуем так же)
        try:
            status = _SERVICE_STATUS_PROCESS()
            needed = wintypes.DWORD(0)
            ok = _advapi32.QueryServiceStatusEx(
                svc, 0, ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(needed)
            )
            if not ok:
                return None
            return "RUNNING" if status.dwCurrentState == _SERVICE_RUNNING else "STOPPED"
        finally:
            _advapi32.CloseServiceHandle(svc)
    finally:
        _advapi32.CloseServiceHandle(scm)
