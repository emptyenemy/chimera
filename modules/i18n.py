"""Тексты программы на нескольких языках: каталоги modules/locales/<язык>.json.

Каталог — плоский словарь «ключ -> текст». В тексте {имя} подставляется из параметров,
порядок слов в предложении остаётся за переводчиком. Множественное число — набором ключей
`ключ.one|few|many|other`: форму выбирает параметр `count` по правилам языка (те же, что
у Intl.PluralRules во фронте). Запасной язык — английский; ключа нигде нет — вернётся
сам ключ, программа от этого не падает (пропуски ловят тесты каталогов).

Язык: флаг `--lang` (set_lang) > переменная CHIMERA_LANG > `lang` в config.json
("auto" — язык интерфейса Windows: русский, украинский и белорусский дают ru, остальные en).
"""

import ctypes
import json
import os
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

LANGS = ("ru", "en")
FALLBACK = "en"
SETTINGS = ("auto",) + LANGS      # что можно записать в config.json
ENV_VAR = "CHIMERA_LANG"
LOCALES_DIR = Path(__file__).parent / "locales"

# LANGID (младшие 10 бит) русского, украинского и белорусского
_RU_FAMILY = (0x19, 0x22, 0x23)

# Формы множественного числа по языкам. required — что обязан дать каталог у ключа с формами.
# Для ru «other» нужен только дробным числам, целые не используют его: берётся many.
PLURAL_CATEGORIES = {"ru": ("one", "few", "many", "other"), "en": ("one", "other")}
PLURAL_REQUIRED = {"ru": ("one", "few", "many"), "en": ("one", "other")}
PLURAL_SAMPLES = {
    "ru": {"one": (1, 21, 101), "few": (2, 3, 4, 22, 104), "many": (0, 5, 11, 12, 14, 25, 111), "other": (1.5,)},
    "en": {"one": (1,), "other": (0, 2, 5, 21, 1.5)},
}
_ALL_FORMS = ("one", "few", "many", "other")

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

_catalogs: dict[str, dict] = {}
_override: str | None = None
_config_lang: str | None = None     # уже разобранное значение lang из config.json
_system_lang: str | None = None


# --- каталоги ------------------------------------------------------------------------------

def catalog(lang: str) -> dict:
    """Каталог языка (кэшируется). Нет файла или он битый — пустой: работает запасной язык."""
    if lang not in _catalogs:
        try:
            data = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _catalogs[lang] = data if isinstance(data, dict) else {}
    return _catalogs[lang]


def reload_catalogs() -> None:
    _catalogs.clear()


# --- какой язык сейчас ---------------------------------------------------------------------------

def detect_system_lang() -> str:
    """Язык интерфейса Windows; при любом сбое — русский."""
    try:
        langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except Exception:  # noqa: BLE001 — не Windows, нет API, странный ответ: всё это «не знаем»
        return "ru"
    return "ru" if (langid & 0x3FF) in _RU_FAMILY else "en"


def resolve(setting) -> str:
    """'auto' | 'ru' | 'en' -> конкретный язык."""
    global _system_lang
    if setting in LANGS:
        return setting
    if _system_lang is None:
        _system_lang = detect_system_lang()
    return _system_lang


def _from_config() -> str:
    global _config_lang
    if _config_lang is None:
        try:
            from modules import appconfig
            setting = appconfig.load().get("lang")
        except Exception:  # noqa: BLE001 — язык не должен ронять то, что его спросило
            setting = None
        _config_lang = resolve(setting)
    return _config_lang


def current_lang() -> str:
    if _override:
        return _override
    env = (os.environ.get(ENV_VAR) or "").strip().lower()
    if env in LANGS:
        return env
    return _from_config()


def set_lang(lang: str | None) -> None:
    """Принудительный язык на этот процесс (флаг `--lang`); None — снять."""
    global _override
    if lang is not None and lang not in LANGS:
        raise ValueError(f"неизвестный язык {lang!r}")
    _override = lang


def refresh() -> None:
    """Перечитать настройку языка из config.json (после его изменения) и язык системы."""
    global _config_lang, _system_lang
    _config_lang = None
    _system_lang = None


@contextmanager
def using(lang: str):
    """На время блока — другой язык (генерация docs/en/CLI.md, проверки)."""
    global _override
    prev = _override
    set_lang(lang)
    try:
        yield
    finally:
        _override = prev


# --- множественные формы --------------------------------------------------------------------------

def plural_category(lang: str, n) -> str:
    """Категория числа по правилам языка: как Intl.PluralRules(lang).select(n)."""
    if isinstance(n, float) and not n.is_integer():
        return "other"
    n = abs(int(n))
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    return "one" if n == 1 else "other"


def plural_rules() -> dict:
    return {lang: {"categories": list(PLURAL_CATEGORIES[lang]),
                   "samples": {c: list(v) for c, v in PLURAL_SAMPLES[lang].items()}}
            for lang in LANGS}


# --- перевод ---------------------------------------------------------------------------------------------

def _candidates(key: str, lang: str, params: dict) -> list[str]:
    if "count" not in params:
        return [key]
    try:
        category = plural_category(lang, params["count"])
    except (TypeError, ValueError):
        return [key]
    names = [f"{key}.{category}"]
    if category == "other":
        names.append(f"{key}.many")     # ru: у дробных нет своей формы, берём «много»
    else:
        names.append(f"{key}.other")
    return names + [key]


def _find(lang: str, key: str, params: dict):
    cat = catalog(lang)
    for name in _candidates(key, lang, params):
        text = cat.get(name)
        if isinstance(text, str):
            return text
    return None


def translate(lang: str, key: str, params: dict | None = None) -> str:
    params = params or {}
    text = _find(lang, key, params)
    if text is None and lang != FALLBACK:
        text = _find(FALLBACK, key, params)
    if text is None:
        return key
    return _PLACEHOLDER.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), text)


def t(key: str, /, **params) -> str:
    return translate(current_lang(), key, params)


def has(key: str, lang: str = FALLBACK) -> bool:
    """Есть ли ключ (сам или его формы) в каталоге языка."""
    cat = catalog(lang)
    return key in cat or any(f"{key}.{f}" in cat for f in _ALL_FORMS)


# --- для фронта --------------------------------------------------------------------------------------------

def frontend_payload(lang: str | None = None) -> dict:
    """Весь каталог языка поверх запасного плюс правила множественных форм: фронт собирает текст сам."""
    from modules.errors import ChimeraError
    lang = lang or current_lang()
    if lang not in LANGS:
        raise ChimeraError("err.lang.unknown", lang=str(lang), options=", ".join(LANGS))
    merged = dict(catalog(FALLBACK))
    merged.update(catalog(lang))
    return {"lang": lang, "fallback": FALLBACK, "langs": list(LANGS), "catalog": merged, "plural": plural_rules()}


# --- ленивые таблицы --------------------------------------------------------------------------------------
# Модульные константы вроде GROUPS или LEVEL_TITLES читались как обычные словари. Чтобы код и
# тесты не менялись, а текст брался на нужном языке в момент чтения, они стали такими объектами.

class LazyMap(Mapping):
    """{ключ: t(prefix.ключ)} в порядке keys; текст берётся при обращении."""

    def __init__(self, keys, prefix: str):
        self._keys = tuple(keys)
        self._prefix = prefix

    def __getitem__(self, key):
        if key not in self._keys:
            raise KeyError(key)
        return t(f"{self._prefix}.{key}")

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)

    def __repr__(self):
        return f"LazyMap({self._prefix!r})"


class LazySeq(Sequence):
    """Последовательность, элементы которой строит функция при обращении."""

    def __init__(self, build):
        self._build = build

    def __getitem__(self, i):
        return self._build()[i]

    def __len__(self):
        return len(self._build())
