"""Клиент канала управления: находит работающую Chimera и зовёт её методы."""

import http.client
import json

from modules import control

# Версия протокола, которую говорит этот CLI. Приложение с меньшей версией не понимает часть
# запросов — тогда просим обновить программу (см. connect()).
CLI_PROTOCOL = control.PROTOCOL


class CliError(Exception):
    """Ошибка, которую CLI показывает как есть, без стека. exit_code — код возврата процесса."""

    def __init__(self, message: str, code: str = "error", exit_code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code
        self.exit_code = exit_code


class NotRunning(CliError):
    def __init__(self, detail: str = ""):
        super().__init__(
            "Chimera не запущена" + (f" ({detail})" if detail else "")
            + ". Запустите её командой `chimera start` или откройте окно.",
            "not_running", 3)


class Usage(CliError):
    def __init__(self, message: str):
        super().__init__(message, "usage", 2)


class Client:
    def __init__(self, port: int, token: str, timeout: float = 120.0):
        self.port = port
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        conn = http.client.HTTPConnection(control.HOST, self.port, timeout=self.timeout)
        headers = {control.TOKEN_HEADER: self.token}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
        except OSError as e:
            raise NotRunning(str(e)) from e
        finally:
            conn.close()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise CliError("Chimera ответила непонятно", "bad_response", 3) from e
        if resp.status == 403:
            raise CliError("Chimera отказала в доступе: файл связи устарел. Повторите команду.",
                           "forbidden", 3)
        return payload

    def hello(self) -> dict:
        return self._request("GET", "/hello")

    def api(self, method: str, *args, reveal: bool = False):
        """Зовёт метод Api. Ответ {ok, data|error}; ошибка приложения → CliError (код 1)."""
        resp = self._request("POST", "/api", {"method": method, "args": list(args), "reveal": reveal})
        if not resp.get("ok"):
            code = "remote_error" if resp.get("code") != "forbidden" else "forbidden"
            raise CliError(str(resp.get("error") or "ошибка"), code, 1)
        return resp.get("data")

    def action(self, name: str) -> dict:
        resp = self._request("POST", "/control", {"action": name})
        if not resp.get("ok"):
            raise CliError(str(resp.get("error") or "ошибка"), "remote_error", 1)
        return resp.get("data") or {}


def discover() -> Client | None:
    """Клиент по файлу связи, если Chimera отвечает. Файл от упавшей копии — None."""
    info = control.read_discovery()
    if not info:
        return None
    client = Client(int(info["port"]), str(info["token"]))
    try:
        client.hello()
    except CliError:
        return None
    return client


def connect() -> Client:
    """Клиент работающей Chimera или NotRunning. Проверяет версию протокола."""
    info = control.read_discovery()
    if not info:
        raise NotRunning()
    client = Client(int(info["port"]), str(info["token"]))
    hello = client.hello()
    app_protocol = int(hello.get("protocol", 0))
    if app_protocol < CLI_PROTOCOL:
        raise CliError(
            f"Chimera старая (протокол {app_protocol}, а командной строке нужен {CLI_PROTOCOL}). "
            "Выполните `chimera update`.", "app_too_old", 3)
    return client
