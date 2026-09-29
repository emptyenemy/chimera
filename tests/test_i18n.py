"""Язык программы: выбор, подстановка, множественные формы, запасной язык."""

import json
from types import SimpleNamespace

import pytest

from modules import appconfig, i18n
from modules.errors import ChimeraError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    i18n.set_lang(None)
    i18n.refresh()
    yield
    i18n.set_lang(None)
    i18n.refresh()


@pytest.fixture
def catalogs(monkeypatch):
    """Подменяет каталоги маленькими: тест не зависит от настоящих текстов."""
    data = {
        "ru": {"hello": "Привет, {name}!", "only_ru": "только русский", "files.one": "{count} файл",
               "files.few": "{count} файла", "files.many": "{count} файлов", "braces": 'в JSON {"a": 1} и {x}'},
        "en": {"hello": "Hello, {name}!", "only_en": "only english", "files.one": "{count} file",
               "files.other": "{count} files", "only_ru": "russian only (en)"},
    }
    monkeypatch.setattr(i18n, "catalog", lambda lang: data.get(lang, {}))
    return data


# --- определение языка системы ---------------------------------------------------------------

def _fake_ctypes(langid):
    return SimpleNamespace(windll=SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=lambda: langid)))


@pytest.mark.parametrize("langid, expected", [
    (0x0419, "ru"),   # русский
    (0x0422, "ru"),   # украинский
    (0x0423, "ru"),   # белорусский
    (0x0409, "en"),   # английский (США)
    (0x0407, "en"),   # немецкий: не русский → английский
    (0x0804, "en"),   # китайский
])
def test_system_language_from_windows_ui_language(monkeypatch, langid, expected):
    monkeypatch.setattr(i18n, "ctypes", _fake_ctypes(langid))
    assert i18n.detect_system_lang() == expected


def test_system_language_falls_back_to_russian_on_failure(monkeypatch):
    def boom():
        raise OSError("нет API")
    monkeypatch.setattr(i18n, "ctypes", SimpleNamespace(
        windll=SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=boom))))
    assert i18n.detect_system_lang() == "ru"
    monkeypatch.setattr(i18n, "ctypes", SimpleNamespace())  # не Windows: windll нет
    assert i18n.detect_system_lang() == "ru"


# --- приоритеты: флаг, переменная, config.json, система ----------------------------------------------

def test_auto_uses_system_language(monkeypatch):
    monkeypatch.setattr(appconfig, "load", lambda: {"lang": "auto"})
    monkeypatch.setattr(i18n, "detect_system_lang", lambda: "en")
    i18n.refresh()
    assert i18n.current_lang() == "en"


def test_config_language_beats_system(monkeypatch):
    monkeypatch.setattr(appconfig, "load", lambda: {"lang": "ru"})
    monkeypatch.setattr(i18n, "detect_system_lang", lambda: "en")
    i18n.refresh()
    assert i18n.current_lang() == "ru"


def test_env_beats_config_and_flag_beats_env(monkeypatch):
    monkeypatch.setattr(appconfig, "load", lambda: {"lang": "ru"})
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    i18n.refresh()
    assert i18n.current_lang() == "en"
    i18n.set_lang("ru")
    assert i18n.current_lang() == "ru"
    i18n.set_lang(None)
    assert i18n.current_lang() == "en"


def test_garbage_env_and_config_are_ignored(monkeypatch):
    monkeypatch.setenv(i18n.ENV_VAR, "klingon")
    monkeypatch.setattr(appconfig, "load", lambda: {"lang": 42})
    monkeypatch.setattr(i18n, "detect_system_lang", lambda: "en")
    i18n.refresh()
    assert i18n.current_lang() == "en"


def test_broken_config_does_not_break_language(monkeypatch):
    def boom():
        raise OSError("диск")
    monkeypatch.setattr(appconfig, "load", boom)
    monkeypatch.setattr(i18n, "detect_system_lang", lambda: "en")
    i18n.refresh()
    assert i18n.current_lang() == "en"


def test_set_lang_rejects_unknown_language():
    with pytest.raises(ValueError):
        i18n.set_lang("klingon")


def test_using_switches_language_temporarily():
    i18n.set_lang("ru")
    with i18n.using("en"):
        assert i18n.current_lang() == "en"
    assert i18n.current_lang() == "ru"


# --- подстановка и запасной язык -------------------------------------------------------------------------

def test_placeholders_are_substituted(catalogs):
    assert i18n.translate("ru", "hello", {"name": "Мир"}) == "Привет, Мир!"
    assert i18n.translate("en", "hello", {"name": "World"}) == "Hello, World!"


def test_unknown_placeholder_is_left_in_place_and_json_braces_survive(catalogs):
    assert i18n.translate("ru", "hello", {}) == "Привет, {name}!"
    assert i18n.translate("ru", "braces", {"x": 5}) == 'в JSON {"a": 1} и 5'


def test_missing_key_in_language_falls_back_to_english(catalogs):
    assert i18n.translate("ru", "only_en", {}) == "only english"


def test_missing_everywhere_returns_the_key_and_does_not_raise(catalogs):
    assert i18n.translate("ru", "no.such.key", {}) == "no.such.key"
    assert i18n.translate("en", "no.such.key", {"a": 1}) == "no.such.key"


def test_t_uses_current_language(catalogs):
    i18n.set_lang("en")
    assert i18n.t("hello", name="X") == "Hello, X!"
    i18n.set_lang("ru")
    assert i18n.t("hello", name="X") == "Привет, X!"


def test_parameter_named_like_translate_arguments_is_allowed(catalogs):
    assert i18n.translate("en", "hello", {"key": "k", "lang": "l", "name": "n"}) == "Hello, n!"


# --- множественные формы ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n, expected", [
    (0, "many"), (1, "one"), (2, "few"), (3, "few"), (4, "few"), (5, "many"), (10, "many"),
    (11, "many"), (12, "many"), (14, "many"), (21, "one"), (22, "few"), (25, "many"),
    (101, "one"), (111, "many"), (112, "many"), (121, "one"), (1000, "many"), (1.5, "other"),
])
def test_russian_plural_categories(n, expected):
    assert i18n.plural_category("ru", n) == expected


@pytest.mark.parametrize("n, expected", [(0, "other"), (1, "one"), (2, "other"), (21, "other"), (1.5, "other")])
def test_english_plural_categories(n, expected):
    assert i18n.plural_category("en", n) == expected


def test_plural_forms_are_chosen_by_count(catalogs):
    ru = [i18n.translate("ru", "files", {"count": n}) for n in (1, 2, 5, 11, 21, 101)]
    assert ru == ["1 файл", "2 файла", "5 файлов", "11 файлов", "21 файл", "101 файл"]
    en = [i18n.translate("en", "files", {"count": n}) for n in (1, 2, 0)]
    assert en == ["1 file", "2 files", "0 files"]


def test_plural_falls_back_to_other_then_plain_key(catalogs):
    # у ru нет .other: дробное число берёт .many
    assert i18n.translate("ru", "files", {"count": 1.5}) == "1.5 файлов"
    # ключ без форм при count работает как обычный
    assert i18n.translate("ru", "hello", {"count": 3, "name": "a"}) == "Привет, a!"


def test_plural_rules_are_published_for_the_frontend():
    rules = i18n.plural_rules()
    assert rules["ru"]["categories"] == ["one", "few", "many", "other"]
    assert rules["en"]["categories"] == ["one", "other"]
    for lang, rule in rules.items():
        for category, numbers in rule["samples"].items():
            assert all(i18n.plural_category(lang, n) == category for n in numbers), (lang, category)


# --- отдача каталога фронту -------------------------------------------------------------------------------------------------

def test_frontend_payload_merges_fallback_under_the_language(catalogs):
    payload = i18n.frontend_payload("ru")
    assert payload["lang"] == "ru" and payload["fallback"] == "en" and payload["langs"] == ["ru", "en"]
    assert payload["catalog"]["hello"] == "Привет, {name}!"
    assert payload["catalog"]["only_en"] == "only english"      # добрано из запасного языка
    assert payload["catalog"]["only_ru"] == "только русский"    # язык важнее запасного
    json.dumps(payload)                                         # уходит по мосту как JSON


def test_frontend_payload_rejects_unknown_language(catalogs):
    with pytest.raises(ChimeraError) as e:
        i18n.frontend_payload("klingon")
    assert e.value.code == "err.lang.unknown"


# --- ошибки с кодом -----------------------------------------------------------------------------------------------------------------

def test_chimera_error_str_is_russian_whatever_the_current_language():
    i18n.set_lang("en")
    e = ChimeraError("err.url.http_only")
    assert str(e) == "Только http(s)-ссылки"
    assert e.message() == "Only http(s) links are allowed."
    assert e.message("ru") == "Только http(s)-ссылки"
    assert e.code == "err.url.http_only" and e.params == {}


def test_chimera_error_params_are_kept_and_substituted():
    e = ChimeraError("err.method.unknown", method="foo")
    assert e.params == {"method": "foo"} and "foo" in str(e)


def test_describe_plain_exception_wraps_the_text():
    from modules.errors import describe
    d = describe(ValueError("сломалось"))
    assert d == {"error": "сломалось", "code": "err.raw", "params": {"message": "сломалось"}}
    d = describe(ChimeraError("err.method.unknown", method="m"))
    assert d["code"] == "err.method.unknown" and d["params"] == {"method": "m"} and "m" in d["error"]


def test_describe_stringifies_odd_params():
    from modules.errors import describe
    assert describe(ChimeraError("err.method.unknown", method=object()))["params"]["method"].startswith("<object")


def test_localized_prefers_code_when_known_and_falls_back_to_text():
    from modules.errors import localized
    i18n.set_lang("en")
    assert localized({"error": "рус", "code": "err.url.http_only", "params": {}}) == "Only http(s) links are allowed."
    assert localized({"error": "рус", "code": "err.raw", "params": {"message": "рус"}}) == "рус"
    assert localized({"error": "рус", "code": "нет.такого", "params": {}}) == "рус"
    assert localized({"error": "", "code": None}) != ""


# --- config.json ------------------------------------------------------------------------------------------------------------------------------

def test_lang_setting_defaults_to_auto_and_is_validated(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")
    assert appconfig.load()["lang"] == "auto"
    assert appconfig.set_value("lang", "en")["lang"] == "en"
    for bad in ("de", "", 5, None, "RU"):
        with pytest.raises(ChimeraError) as e:
            appconfig.set_value("lang", bad)
        assert e.value.code == "err.config.lang_unknown"
    assert appconfig.load()["lang"] == "en"


def test_theme_error_keeps_its_russian_text(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")
    with pytest.raises(ChimeraError) as e:
        appconfig.set_value("theme", "розовая")
    assert str(e.value) == "Тема 'розовая' неизвестна. Доступные: system, light, dark."


def test_changing_lang_in_config_switches_current_language(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")
    i18n.refresh()
    appconfig.set_value("lang", "en")
    assert i18n.current_lang() == "en"
    appconfig.set_value("lang", "ru")
    assert i18n.current_lang() == "ru"
