"""Ошибки с кодом: текст на нужном языке собирает тот, кто показывает (окно, CLI, трей).

ChimeraError(code, **params) — code это ключ каталога (modules/locales), params подставляются
в текст. str(e) даёт русский текст: так ошибку читали раньше и так её видят те, кто ещё не
знает про коды. Тест tests/test_i18n_catalog.py следит, что каждый код есть в каталогах.
"""

from modules import i18n

RAW = "err.raw"    # чужое исключение (менеджеры модулей): «{message}» как есть


class ChimeraError(Exception):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = {k: _plain(v) for k, v in params.items()}

    def message(self, lang: str | None = None) -> str:
        return i18n.translate(lang or i18n.current_lang(), self.code, self.params)

    def __str__(self) -> str:
        return i18n.translate("ru", self.code, self.params)


def _plain(value):
    """Параметры уходят во фронт и в JSON: только простые значения."""
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def describe(e: Exception) -> dict:
    """{error, code, params}: русский текст как раньше плюс код и параметры для сборки текста клиентом."""
    if isinstance(e, ChimeraError):
        return {"error": str(e), "code": e.code, "params": dict(e.params)}
    return {"error": str(e), "code": RAW, "params": {"message": str(e)}}


def localized(result: dict) -> str:
    """Текст ошибки из ответа Api на текущем языке: по коду, если он в каталоге, иначе готовый error."""
    code = result.get("code")
    if code and code != RAW and i18n.has(code):
        return i18n.translate(i18n.current_lang(), code, result.get("params") or {})
    return str(result.get("error") or i18n.t("err.unknown"))


class ChimeraValueError(ChimeraError, ValueError):
    """Неверное значение параметра. Остаётся ValueError: так его ловили до кодов ошибок."""


class ChimeraRuntimeError(ChimeraError, RuntimeError):
    """Ошибка операции с сохранением типа RuntimeError."""


class ChimeraOSError(ChimeraError, OSError):
    """Ошибка соединения или файловой операции."""


class ChimeraPermissionError(ChimeraError, PermissionError):
    """Недостаточно прав для операции."""


class ChimeraFileNotFoundError(ChimeraError, FileNotFoundError):
    """Нужный файл отсутствует."""


class ChimeraKeyError(ChimeraError, KeyError):
    """Неизвестный идентификатор."""
