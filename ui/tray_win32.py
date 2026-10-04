"""Трей WebView2 на WinAPI, без Qt и отдельного графического пакета."""
import ctypes
import json
import threading
from ctypes import wintypes as w
from pathlib import Path

from modules import appconfig, applog, errors
from modules.i18n import t
from ui import tray_model

ICON = Path(__file__).resolve().parent.parent / "assets" / "logo" / "chimera.ico"
CALLBACK = 0x8001
TICK_MS = 1500   # как часто трей смотрит, не закончилось ли самолечение в фоне


class Tray:
    def __init__(self, api, show, quit_app):
        self.api, self.show, self.quit_app = api, show, quit_app
        self.command_lock = threading.Lock()
        self.ready = threading.Event()
        self.available = False
        self.hwnd = None
        self.autotune_news = tray_model.AutotuneNews()
        self.thread = threading.Thread(target=self._run, daemon=True, name="chimera-tray")
        self.thread.start()
        self.ready.wait(3)

    def menu_entries(self):
        states = self.api.hub.snapshot()
        entries = [(1, t("tray.open"), False)]
        for i, (key, _) in enumerate(tray_model.MODULES, 10):
            entries.append((i, tray_model.module_label(key), tray_model.is_on(key, states.get(key))))
        entries.extend([(20, tray_model.panic_label(), False), (2, t("tray.quit"), False)])
        return entries

    def command(self, command):
        if command == 1:
            self.show()
        elif command == 2:
            self.quit_app()
        elif command == 20:
            method, args = tray_model.PANIC_COMMAND
            reply = json.loads(self.api.dispatch(method, json.dumps(args)))
            if not reply.get("ok"):
                raise RuntimeError(errors.localized(reply))
            partial = tray_model.panic_summary(reply.get("data"))
            if partial:
                raise RuntimeError(partial)
        elif 10 <= command < 10 + len(tray_model.MODULES):
            key = tray_model.MODULES[command - 10][0]
            data = self.api.hub.snapshot().get(key)
            method, args = tray_model.toggle_command(key, data, not tray_model.is_on(key, data))
            reply = json.loads(self.api.dispatch(method, json.dumps(args)))
            if not reply.get("ok"):
                raise RuntimeError(errors.localized(reply))

    def news(self):
        """(заголовок, текст) нового итога самолечения или None."""
        return self.autotune_news.update(self.api.hub.snapshot().get("autotune"))

    def close(self):
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, 0x0010, 0, 0)
            if threading.current_thread() is not self.thread:
                self.thread.join(timeout=3)

    def _run(self):
        try:
            self._loop()
        except Exception as e:
            applog.write(f"Трей WebView2 не запустился: {e}")
        finally:
            self.available = False
            self.ready.set()

    def _loop(self):
        user = self.user = ctypes.WinDLL("user32", use_last_error=True)
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WindowClass(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("proc", proc_type), ("class_extra", ctypes.c_int),
                        ("window_extra", ctypes.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
                        ("cursor", w.HANDLE), ("background", w.HBRUSH), ("menu", w.LPCWSTR), ("name", w.LPCWSTR)]

        class IconData(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("window", w.HWND), ("id", w.UINT), ("flags", w.UINT),
                        ("message", w.UINT), ("icon", w.HICON), ("tip", w.WCHAR * 128),
                        ("state", w.DWORD), ("state_mask", w.DWORD), ("info", w.WCHAR * 256),
                        ("timeout", w.UINT), ("title", w.WCHAR * 64), ("info_flags", w.DWORD),
                        ("guid", ctypes.c_byte * 16), ("balloon_icon", w.HICON)]

        user.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        user.RegisterClassW.restype = w.WORD
        user.UnregisterClassW.argtypes = [w.LPCWSTR, w.HINSTANCE]
        user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
        user.CreateWindowExW.restype = w.HWND
        user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user.DefWindowProcW.restype = ctypes.c_ssize_t
        user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user.DestroyWindow.argtypes = [w.HWND]
        user.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
        user.LoadImageW.restype = w.HANDLE
        user.DestroyIcon.argtypes = [w.HICON]
        user.CreatePopupMenu.restype = w.HMENU
        user.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
        user.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, ctypes.c_void_p]
        user.TrackPopupMenu.restype = w.UINT
        user.DestroyMenu.argtypes = [w.HMENU]
        user.SetForegroundWindow.argtypes = [w.HWND]
        user.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
        user.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        user.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
        user.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
        user.DispatchMessageW.restype = ctypes.c_ssize_t
        shell.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(IconData)]
        kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
        kernel.GetModuleHandleW.restype = w.HMODULE
        user.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p]
        user.SetTimer.restype = ctypes.c_size_t
        user.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
        taskbar_created = user.RegisterWindowMessageW("TaskbarCreated")
        instance = kernel.GetModuleHandleW(None)
        name = f"ChimeraTray_{id(self)}"
        nid = IconData()

        def balloon(title, text, error=False):
            nid.flags |= 0x10
            nid.title, nid.info, nid.info_flags = title[:63], text[:255], 3 if error else 1
            shell.Shell_NotifyIconW(1, ctypes.byref(nid))

        def execute(command):
            if not self.command_lock.acquire(blocking=False):
                return
            try:
                self.command(command)
            except Exception as e:
                applog.write(f"Команда трея: {e}")
                balloon("Chimera", str(e), error=True)
            finally:
                self.command_lock.release()

        def tick():
            try:
                news = self.news()
            except Exception as e:   # исключение не должно вылететь из оконной процедуры
                applog.write(f"Трей: итог самолечения не прочитан: {e}")
                return
            if news:
                balloon(*news)

        def popup(hwnd):
            menu = user.CreatePopupMenu()
            try:
                for command, title, checked in self.menu_entries():
                    user.AppendMenuW(menu, 0x8 if checked else 0, command, title)
                point = w.POINT()
                user.GetCursorPos(ctypes.byref(point))
                user.SetForegroundWindow(hwnd)
                command = user.TrackPopupMenu(menu, 0x100 | 0x2, point.x, point.y, 0, hwnd, None)
                user.PostMessageW(hwnd, 0, 0, 0)
                if command:
                    threading.Thread(target=execute, args=(command,), daemon=True).start()
            finally:
                user.DestroyMenu(menu)

        def procedure(hwnd, msg, wp, lp):
            if msg == CALLBACK:
                if lp == 0x203:
                    self.show()
                elif lp == 0x205:
                    popup(hwnd)
                return 0
            if msg == 0x0113:   # WM_TIMER
                tick()
                return 0
            if msg == taskbar_created:
                shell.Shell_NotifyIconW(0, ctypes.byref(nid))
                return 0
            if msg == 0x0010:
                user.DestroyWindow(hwnd)
                return 0
            if msg == 0x0002:
                user.PostQuitMessage(0)
                return 0
            return user.DefWindowProcW(hwnd, msg, wp, lp)

        callback = proc_type(procedure)
        klass = WindowClass(proc=callback, instance=instance, name=name)
        if not user.RegisterClassW(ctypes.byref(klass)):
            raise ctypes.WinError(ctypes.get_last_error())
        icon = user.LoadImageW(None, str(ICON), 1, 0, 0, 0x10)
        try:
            self.hwnd = user.CreateWindowExW(0, name, "Chimera", 0, 0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            nid.size, nid.window, nid.id = ctypes.sizeof(nid), self.hwnd, 1
            nid.flags, nid.message, nid.icon, nid.tip = 1 | 2 | 4, CALLBACK, icon, "Chimera"
            self.available = bool(shell.Shell_NotifyIconW(0, ctypes.byref(nid)))
            user.SetTimer(self.hwnd, 1, TICK_MS, None)
            self.ready.set()
            message = w.MSG()
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        finally:
            shell.Shell_NotifyIconW(2, ctypes.byref(nid))
            if icon:
                user.DestroyIcon(icon)
            user.UnregisterClassW(name, instance)
            self.hwnd = None


def close_to_tray(tray):
    return bool(tray and tray.available and appconfig.load().get("close_to_tray", True))
