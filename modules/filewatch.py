"""Наблюдатель за lists/*.txt: правка списка на диске подхватывается работающей программой.

Агент или пользователь правит файл напрямую, минуя Api, и программа применяет его так же,
как `lists_save`: через modules/liveapply.py. Наблюдатель запускает тот процесс, что владеет
модулями (окно, если службы нет, иначе сама служба), поэтому применение не двоится.

Опрос os.stat раз в секунду, без внешних библиотек. Файл считается готовым, когда его
(mtime, size) совпали в двух опросах подряд: редактор может писать не сразу и не атомарно,
и читать половину списка нельзя. Содержимое читается и хэшируется только при смене этой
сигнатуры. Свои записи (domains.save_raw и остальные) не применяются повторно: по хэшу
содержимого (CRLF и LF не различаются), который domains запоминает до записи. Имена
сравниваются без учёта регистра, как на файловой системе Windows. Следим только за
lists/*.txt; всё, что программа генерирует сама (hostlists winws, файлы правил sing-box,
PAC, логи), лежит в других папках и сюда не попадает.
"""

import threading
from pathlib import Path
from typing import Callable

from modules import applog, changelog, domains

POLL_INTERVAL = 1.0
STOP_TIMEOUT = 5.0

_UNSET = object()
# событие -> глагол в журнале изменений (`lists edit youtube`)
_VERBS = {"changed": "edit", "created": "create", "removed": "delete"}


class ListsWatcher:
    def __init__(self, on_change: Callable[[str, str], list], directory: Path | None = None,
                 interval: float = POLL_INTERVAL, active: Callable[[], bool] = lambda: True,
                 changes_log: Path | None = None, log: Callable[[str], None] = applog.write):
        """on_change(kind, name) применяет событие (created | changed | removed) и возвращает
        ошибки применения [{"module", "error"}]. active() == False — сейчас следить не наш
        черёд (работает служба): диск не читаем, а на возврате база снимается заново."""
        self._on_change = on_change
        self._dir = directory
        self._interval = interval
        self._active = active
        self._changes_log = changes_log
        self._log = log
        # все словари — по имени в нижнем регистре
        self._names: dict[str, str] = {}             # как файл называется на диске
        self._sig: dict[str, tuple] = {}             # (mtime_ns, size) последнего обработанного состояния
        self._known: dict[str, str] = {}             # хэш содержимого этого состояния
        self._pending: dict[str, tuple | None] = {}  # состояние, увиденное в прошлом опросе
        self._idle = False                           # были ли пропущены опросы (чужой черёд)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # --- снимок диска --------------------------------------------------------------

    @property
    def directory(self) -> Path:
        return self._dir or domains.LISTS_DIR

    def _scan(self) -> dict[str, tuple[str, tuple]]:
        found = {}
        try:
            files = list(self.directory.glob("*.txt"))
        except OSError:
            return found
        for path in files:
            if not domains.NAME_RE.match(path.stem):
                continue  # такой список программа всё равно не откроет
            try:
                st = path.stat()
            except OSError:
                continue  # исчез между glob и stat: увидим при следующем опросе
            found[path.stem.casefold()] = (path.stem, (st.st_mtime_ns, st.st_size))
        return found

    def _path(self, key: str) -> Path:
        return self.directory / f"{self._names.get(key, key)}.txt"

    def prime(self) -> None:
        """Запоминает то, что лежит на диске сейчас, как уже известное: событий не будет."""
        domains.own_prune()
        self._names, self._sig, self._known, self._pending = {}, {}, {}, {}
        for key, (name, sig) in self._scan().items():
            self._names[key] = name
            try:
                self._known[key] = domains.content_hash(self._path(key).read_bytes())
            except OSError:
                continue  # займёмся, когда файл освободится: он покажется как новый
            self._sig[key] = sig

    # --- опрос ---------------------------------------------------------------------

    def poll(self) -> None:
        current = self._scan()
        for key in sorted(set(current) | set(self._sig) | set(self._pending)):
            name, sig = current.get(key, (None, None))
            if name:
                self._names[key] = name
            if sig == self._sig.get(key):
                self._pending.pop(key, None)
                continue
            if self._pending.get(key, _UNSET) != sig:
                self._pending[key] = sig  # такое состояние вижу впервые: подождём следующего опроса
                continue
            self._settle(key, sig)

    def _settle(self, key: str, sig: tuple | None) -> None:
        """Состояние держится уже два опроса: разбираем, что это за событие."""
        name = self._names.get(key, key)
        if sig is None:
            self._pending.pop(key, None)
            self._sig.pop(key, None)
            was_known = self._known.pop(key, None) is not None
            known_own, own_hash = domains.own_written(name)
            domains.own_forget(name)
            if was_known and not (known_own and own_hash is None):  # свои удаления применены при удалении
                self._emit("removed", name)
            return
        try:
            digest = domains.content_hash(self._path(key).read_bytes())
            after = self._path(key).stat()
        except OSError:
            return  # занят (редактор, антивирус): pending остаётся, прочтём в следующий опрос
        if (after.st_mtime_ns, after.st_size) != sig:
            self._pending[key] = (after.st_mtime_ns, after.st_size)  # дописывают прямо сейчас
            return
        self._pending.pop(key, None)
        self._sig[key] = sig
        known_own, own_hash = domains.own_written(name)
        domains.own_forget(name)  # запись прочитана наблюдателем: чужая правка или наша, память о ней не нужна
        if known_own and own_hash == digest:
            self._known[key] = digest  # наша запись, применена тем, кто её сделал
            return
        if self._known.get(key) == digest:
            return  # тронули, но содержимое прежнее
        kind = "changed" if key in self._known else "created"
        self._known[key] = digest
        self._emit(kind, name)

    def _emit(self, kind: str, name: str) -> None:
        try:
            errors = self._on_change(kind, name) or []
        except Exception as e:
            errors = [{"module": "apply", "error": str(e)}]
        command = f"lists {_VERBS[kind]} {name}"
        changelog.record("file", command, not errors, self._changes_log)
        if errors:
            self._log(f"Список {name}: правка файла применена с ошибками — "
                      + "; ".join(f"{e['module']}: {e['error']}" for e in errors))
        else:
            self._log(f"Список {name}: правка файла применена ({_VERBS[kind]})")

    # --- фон -----------------------------------------------------------------------

    def _step(self) -> None:
        if not self._active():
            self._idle = True  # чужой черёд (служба): диск не трогаем
            return
        if self._idle:
            self._idle = False
            self.prime()  # чужие применения не повторяем: один снимок на возврате
            return
        self.poll()

    def start_background(self, stop: threading.Event) -> None:
        self.prime()

        def loop():
            while not (stop.is_set() or self._stop.wait(self._interval)):
                try:
                    self._step()
                except Exception as e:
                    self._log(f"Наблюдатель за списками: {e}")  # опрос не должен падать насовсем

        self._thread = threading.Thread(target=loop, daemon=True, name="lists-watch")
        self._thread.start()

    def stop(self, timeout: float = STOP_TIMEOUT) -> None:
        """Останавливает опрос и ждёт, пока закончится применение, идущее прямо сейчас: после
        этого можно гасить модули, к которым оно обращалось бы."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)
