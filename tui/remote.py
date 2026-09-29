"""Связь TUI с работающей Chimera: тот же канал управления, что у командной строки.

TUI сам ничего не запускает и ничем не владеет: процессами (winws, прокси, Telegram-прокси)
управляет Chimera, а здесь только зовутся её методы Api по таблице modules/cli/registry.py.
Если Chimera не запущена, ensure_running() поднимает её без окна, как `chimera start`.

Remote.call() блокирующий: его зовут из фоновых воркеров Textual, не из потока интерфейса.
Ошибки двух родов: Offline (нет связи, устаревший файл связи, старая программа) и
RemoteError (Chimera ответила, но метод вернул ошибку).
"""

import http.client
from datetime import datetime

from modules import control
from modules.cli import client as cl
from modules.cli import commands
from modules.cli.client import CliError

CALL_TIMEOUT = 30.0   # dns_state и часть других методов бывают медленными; вечно висеть нельзя


class Offline(Exception):
    """Chimera недоступна: не запущена, оборвала соединение или слишком старая."""


class RemoteError(Exception):
    """Chimera ответила ошибкой метода (например, нужны права администратора)."""


class Remote:
    def __init__(self, connect=None, discover=None, launch=None, wait=None):
        # четыре точки подмены для тестов: реальную Chimera и процессы они не трогают
        self._connect = connect or cl.connect
        self._discover = discover or cl.discover
        self._launch = launch or commands.launch_app
        self._wait = wait or commands._wait
        self._client = None

    def call(self, method: str, *args):
        """Метод Api через канал. Секреты остаются скрытыми (reveal не просим), маска
        накладывается ещё раз на всякий случай."""
        try:
            if self._client is None:
                self._client = self._connect()
                self._client.timeout = CALL_TIMEOUT
            data = self._client.api(method, *args, reveal=False)
        except cl.NotRunning as e:
            self._client = None
            raise Offline("нет связи с Chimera") from e
        except CliError as e:
            if e.exit_code == 3:   # файл связи устарел, ответ непонятный или программа старая
                self._client = None
                raise Offline(e.message) from e
            raise RemoteError(e.message) from e
        except (OSError, http.client.HTTPException) as e:
            self._client = None
            raise Offline("нет связи с Chimera") from e
        return control.redact(data)

    def ensure_running(self, progress=None) -> bool:
        """Поднимает Chimera без окна, если она не запущена. True — пришлось запускать."""
        if self._discover() is not None:
            return False
        if progress:
            progress("Chimera не запущена, запускаю её в трее…")
        self._launch()
        if not self._wait(lambda: self._discover() is not None, commands.WAIT_START, 0.5):
            raise Offline("не удалось дождаться запуска Chimera (если был запрос прав администратора, "
                          "подтвердите его и откройте TUI снова)")
        return True

    def record(self, label: str, ok: bool) -> None:
        """Строка в журнал изменений (data/changes.log) рядом с записями командной строки."""
        try:
            with open(commands.CHANGES_LOG, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\ttui\t{label}\t{'ok' if ok else 'error'}\n")
        except OSError:
            pass  # журнал вспомогательный: не мешаем действию
