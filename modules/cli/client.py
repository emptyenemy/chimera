"""Клиент канала управления: находит работающую Chimera и зовёт её методы."""

import http.client
import json

from modules import control, errors, i18n
from modules.i18n import t

# Версия протокола, которую говорит этот CLI. Приложение с меньшей версией не понимает часть
# запросов — тогда просим обновить программу (см. connect()).
CLI_PROTOCOL = control.PROTOCOL


class CliError(Exception):
    """Ошибка, которую CLI показывает как есть, без стека. exit_code — код возврата процесса.

    code — устойчивая категория (usage, not_running, …), key и params — ключ сообщения в
    каталоге и его параметры: текст message зависит от языка, они нет."""

    def __init__(self, message: str, code: str = "error", exit_code: int = 1, key: str | None = None,
                 params: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.exit_code = exit_code
        self.key = key
        self.params = params or {}

    @classmethod
    def of(cls, key: str, code: str = "error", exit_code: int = 1, /, **params):
        return cls(t(key, **params), code, exit_code, key, params)


class NotRunning(CliError):
    def __init__(self, detail: str = ""):
        key = "cli.err.not_running_detail" if detail else "cli.err.not_running"
        params = {"detail": detail} if detail else {}
        super().__init__(t(key, **params), "not_running", 3, key, params)


class Usage(CliError):
    def __init__(self, message: str, key: str | None = None, params: dict | None = None):
        super().__init__(message, "usage", 2, key, params)

    @classmethod
    def of(cls, key: str, /, **params):
        return cls(t(key, **params), key, params)


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
            raise CliError.of("cli.err.bad_response", "bad_response", 3) from e
        if resp.status == 403:
            raise CliError.of("cli.err.forbidden", "forbidden", 3)
        return payload

    def hello(self) -> dict:
        return self._request("GET", "/hello")

    def api(self, method: str, *args, reveal: bool = False):
        """Зовёт метод Api. Ответ {ok, data|error}; ошибка приложения → CliError (код 1)."""
        resp = self._request("POST", "/api", {"method": method, "args": list(args), "reveal": reveal})
        if not resp.get("ok"):
            raise _remote_error(resp)
        return resp.get("data")

    def action(self, name: str) -> dict:
        resp = self._request("POST", "/control", {"action": name})
        if not resp.get("ok"):
            raise _remote_error(resp, forbidden=False)
        return resp.get("data") or {}


def _remote_error(resp: dict, forbidden: bool = True) -> CliError:
    """Ошибка приложения -> CliError. Текст собирается на языке CLI по коду ответа; коды
    нашего канала (forbidden, bad_request) каталогу не принадлежат и идут русским текстом как есть."""
    code = "forbidden" if forbidden and resp.get("code") == "forbidden" else "remote_error"
    known = bool(resp.get("code")) and resp.get("code") != errors.RAW and i18n.has(resp["code"])
    return CliError(errors.localized(resp), code, 1, resp["code"] if known else None,
                    resp.get("params") if known else None)


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
        raise CliError.of("cli.err.app_too_old", "app_too_old", 3, app=app_protocol, need=CLI_PROTOCOL)
    return client
