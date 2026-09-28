"""Один экземпляр окна: повторный запуск показывает уже открытую программу.

Окно, свёрнутое в трей, держит именованное событие Windows и ждёт его в
отдельном потоке. Новый запуск, найдя событие, взводит его и выходит — первая
копия показывает окно. Проверка стоит в main.py до запроса UAC, так что лишнего
окна «разрешить изменения» тоже не будет.

Тонкость с правами: работающая копия повышена до администратора (высокий
уровень целостности), а новая ещё нет (средний). Объект, созданный повышенным
процессом, по умолчанию помечен «не писать снизу», и SetEvent из обычного
процесса получил бы отказ в доступе. Поэтому событие создаётся с явным
дескриптором: доступ всем и метка низкого уровня целостности. Худшее, что
может сделать посторонний процесс с таким событием, — показать окно.
"""

import ctypes
import sys
import threading
from ctypes import wintypes

EVENT_NAME = r"Local\Chimera_UI_Show"

# Всем — полный доступ к событию; SACL: метка Low без записи снизу — чтобы
# процесс любого уровня целостности мог взвести событие повышенной копии.
_SDDL = "D:(A;;GA;;;WD)S:(ML;;NW;;;LW)"

_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF

if sys.platform == "win32":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _adv = ctypes.WinDLL("advapi32", use_last_error=True)

    _k32.CreateEventW.restype = wintypes.HANDLE
    _k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.OpenEventW.restype = wintypes.HANDLE
    _k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.SetEvent.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.WaitForMultipleObjects.restype = wintypes.DWORD
    _k32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                            wintypes.BOOL, wintypes.DWORD]
    _k32.LocalFree.argtypes = [ctypes.c_void_p]
    _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
else:  # pragma: no cover — программа только под Windows
    _k32 = _adv = None


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


def _open(access: int, name: str):
    if _k32 is None:
        return None
    return _k32.OpenEventW(access, False, name) or None


def is_running(name: str = EVENT_NAME) -> bool:
    """Есть ли уже открытое окно программы."""
    h = _open(_SYNCHRONIZE, name)
    if not h:
        return False
    _k32.CloseHandle(h)
    return True


def signal_existing(name: str = EVENT_NAME) -> bool:
    """Просит уже открытую копию показать окно. False — такой копии нет."""
    h = _open(_EVENT_MODIFY_STATE, name)
    if not h:
        return False
    try:
        return bool(_k32.SetEvent(h))
    finally:
        _k32.CloseHandle(h)


class Listener:
    """Держит событие и зовёт on_signal (из своего потока) на каждый повторный запуск."""

    def __init__(self, event, on_signal):
        self._event = event
        self._stop = _k32.CreateEventW(None, True, False, None)
        self._on_signal = on_signal
        self._thread = threading.Thread(target=self._loop, daemon=True, name="instance-listener")
        self._thread.start()

    def _loop(self):
        handles = (wintypes.HANDLE * 2)(self._event, self._stop)
        while True:
            r = _k32.WaitForMultipleObjects(2, handles, False, _INFINITE)
            if r != _WAIT_OBJECT_0:
                return  # стоп или ошибка ожидания
            try:
                self._on_signal()
            except Exception:
                pass

    def close(self):
        if self._stop:
            _k32.SetEvent(self._stop)
            self._thread.join(timeout=2)
            _k32.CloseHandle(self._stop)
            self._stop = None
        if self._event:
            _k32.CloseHandle(self._event)
            self._event = None


def listen(on_signal, name: str = EVENT_NAME) -> Listener | None:
    """Занимает имя и начинает ждать повторных запусков. None — имя уже занято
    другой копией (гонка двух одновременных запусков) или не Windows."""
    if _k32 is None:
        return None
    psd = ctypes.c_void_p()
    if not _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(_SDDL, 1, ctypes.byref(psd), None):
        psd = ctypes.c_void_p()  # без дескриптора — хотя бы для копий того же уровня
    sa = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), psd.value, False)
    try:
        event = _k32.CreateEventW(ctypes.byref(sa), False, False, name)
        already = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    finally:
        if psd.value:
            _k32.LocalFree(psd)
    if not event:
        return None
    if already:
        _k32.CloseHandle(event)
        return None
    return Listener(event, on_signal)
