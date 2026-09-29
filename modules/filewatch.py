"""Наблюдатель за lists/*.txt: правка списка на диске подхватывается работающей программой.

Агент или пользователь правит файл напрямую, минуя Api, и программа применяет его так же,
как `lists_save`: через modules/liveapply.py. Наблюдатель запускает тот процесс, что владеет
модулями (окно, если службы нет, иначе сама служба), поэтому применение не двоится.

Опрос os.stat раз в секунду, без внешних библиотек. Файл считается готовым, когда его
(mtime, size) совпали в двух опросах подряд: редактор может писать не сразу и не атомарно,
и читать половину списка нельзя. Свои записи (domains.save_raw и остальные) не применяются
повторно: по хэшу содержимого (CRLF и LF не различаются), который domains запоминает до
записи. Следим только за lists/*.txt; всё, что программа генерирует сама (hostlists
winws, файлы правил sing-box, PAC, логи), лежит в других папках и сюда не попадает.
"""

import threading
from pathlib import Path
from typing import Callable

from modules import applog, changelog, domains

POLL_INTERVAL = 1.0

_UNSET = object()
# событие -> глагол в журнале изменений (`lists edit youtube`)
_VERBS = {"changed": "edit", "created": "create", "removed": "delete"}


class ListsWatcher:
    def __init__(self, on_change: Callable[[str, str], list], directory: Path | None = None,
                 interval: float = POLL_INTERVAL, active: Callable[[], bool] = lambda: True,
                 changes_log: Path | None = None, log: Callable[[str], None] = applog.write):
        """on_change(kind, name) применяет событие (created | changed | removed) и возвращает
        ошибки применения [{"module", "error"}]. active() == False — сейчас следить не наш
        черёд (работает служба): опросы пропускаются, а база следует за диском."""
        self._on_change = on_change
        self._dir = directory
        self._interval = interval
        self._active = active
        self._changes_log = changes_log
        self._log = log
        self._sig: dict[str, tuple | None] = {}      # (mtime_ns, size) последнего обработанного состояния
        self._known: dict[str, str] = {}             # хэш содержимого этого состояния
        self._pending: dict[str, tuple | None] = {}  # состояние, увиденное в прошлом опросе
        self._thread: threading.Thread | None = None

    # --- снимок диска --------------------------------------------------------------

    @property
    def directory(self) -> Path:
        return self._dir or domains.LISTS_DIR

    def _scan(self) -> dict[str, tuple]:
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
            found[path.stem] = (st.st_mtime_ns, st.st_size)
        return found

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.txt"

    def prime(self) -> None:
        """Запоминает то, что лежит на диске сейчас, как уже известное: событий не будет."""
        self._sig, self._known, self._pending = {}, {}, {}
        for name, sig in self._scan().items():
            try:
                self._known[name] = domains.content_hash(self._path(name).read_bytes())
            except OSError:
                continue  # займёмся, когда файл освободится: он покажется как новый
            self._sig[name] = sig

    # --- опрос ---------------------------------------------------------------------

    def poll(self) -> None:
        current = self._scan()
        for name in sorted(set(current) | set(self._sig) | set(self._pending)):
            sig = current.get(name)
            if sig == self._sig.get(name):
                self._pending.pop(name, None)
                continue
            if self._pending.get(name, _UNSET) != sig:
                self._pending[name] = sig  # такое состояние вижу впервые: подождём следующего опроса
                continue
            self._settle(name, sig)

    def _settle(self, name: str, sig: tuple | None) -> None:
        """Состояние держится уже два опроса: разбираем, что это за событие."""
        if sig is None:
            self._pending.pop(name, None)
            self._sig.pop(name, None)
            was_known = self._known.pop(name, None) is not None
            known_own, own_hash = domains.own_written(name)
            own_removal = known_own and own_hash is None
            domains.own_forget(name)
            if was_known and not own_removal:  # свои удаления применены при удалении
                self._emit("removed", name)
            return
        try:
            digest = domains.content_hash(self._path(name).read_bytes())
            after = self._path(name).stat()
        except OSError:
            return  # занят (редактор, антивирус): pending остаётся, прочтём в следующий опрос
        if (after.st_mtime_ns, after.st_size) != sig:
            self._pending[name] = (after.st_mtime_ns, after.st_size)  # дописывают прямо сейчас
            return
        self._pending.pop(name, None)
        self._sig[name] = sig
        known_own, own_hash = domains.own_written(name)
        if known_own and own_hash == digest:
            domains.own_forget(name)  # наша запись, применена тем, кто её сделал
            self._known[name] = digest
            return
        if self._known.get(name) == digest:
            return  # тронули, но содержимое прежнее
        kind = "changed" if name in self._known else "created"
        self._known[name] = digest
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
            self.prime()  # чужой черёд: чужие применения не повторяем, когда он вернётся
            return
        self.poll()

    def start_background(self, stop: threading.Event) -> None:
        self.prime()

        def loop():
            while not stop.wait(self._interval):
                try:
                    self._step()
                except Exception as e:
                    self._log(f"Наблюдатель за списками: {e}")  # опрос не должен падать насовсем

        self._thread = threading.Thread(target=loop, daemon=True, name="lists-watch")
        self._thread.start()
