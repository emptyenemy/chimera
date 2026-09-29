"""chimera на нескольких языках: флаг --lang, переменная CHIMERA_LANG, язык в config.json,
ключи и параметры в ошибках --json."""

import json
import re

import pytest

from modules import appconfig, control, i18n
from modules.cli import app, commands, docs, registry

CYRILLIC = re.compile("[А-Яа-яЁё]")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(control, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(commands, "CHANGES_LOG", tmp_path / "changes.log")
    i18n.set_lang(None)
    i18n.refresh()
    yield
    i18n.set_lang(None)
    i18n.refresh()


def run(capsys, *argv):
    code = app.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    return code, json.loads(out), err


# --- флаг и переменная --------------------------------------------------------------------------------

def test_lang_flag_switches_help_to_english(capsys):
    code, out, _ = run(capsys, "--lang", "en", "--help")
    assert code == 0 and "Usage:" in out and "Exit codes:" in out
    assert not CYRILLIC.search(out)


def test_lang_flag_forms_and_position(capsys):
    for argv in (["--lang=en", "winws", "--help"], ["winws", "--help", "--lang", "en"], ["winws", "--lang", "en", "--help"]):
        code, out, _ = run(capsys, *argv)
        assert code == 0 and "Action" in out or "Actions:" in out, argv
        assert not CYRILLIC.search(out), argv


def test_russian_is_still_the_default_in_tests(capsys):
    code, out, _ = run(capsys, "--help")
    assert code == 0 and "Использование:" in out


def test_env_language_and_flag_priority(capsys, monkeypatch):
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    assert "Usage:" in run(capsys, "--help")[1]
    assert "Использование:" in run(capsys, "--lang", "ru", "--help")[1]


def test_config_language_is_used_without_flag_and_env(capsys, monkeypatch):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    appconfig.set_value("lang", "en")
    assert "Usage:" in run(capsys, "--help")[1]
    appconfig.set_value("lang", "ru")
    assert "Использование:" in run(capsys, "--help")[1]


def test_lang_flag_does_not_leak_to_the_next_call(capsys):
    run(capsys, "--lang", "en", "--help")
    assert i18n.override() is None
    assert "Использование:" in run(capsys, "--help")[1]


def test_bad_lang_flag_is_usage_error(capsys):
    code, _, err = run(capsys, "--lang", "de", "--help")
    assert code == 2 and "de" in err and "ru, en" in err
    code, _, err = run(capsys, "--lang")
    assert code == 2 and "--lang" in err
    code, data, _ = run_json(capsys, "--lang=xx", "status")
    assert code == 2 and data["error"]["code"] == "usage" and data["error"]["key"] == "cli.usage.lang_invalid"


def test_json_errors_carry_key_and_params_and_english_text(capsys):
    code, data, _ = run_json(capsys, "--lang", "en", "нечто")
    assert code == 2 and data["schema"] == 1
    err = data["error"]
    assert err["code"] == "usage" and err["key"] == "cli.usage.unknown_command"
    assert err["params"] == {"group": "'нечто'"}
    assert err["message"].startswith("Unknown command")
    code, data, _ = run_json(capsys, "нечто")
    assert data["error"]["key"] == err["key"] and data["error"]["params"] == err["params"]
    assert data["error"]["message"].startswith("Неизвестная команда")


def test_json_error_keeps_language_independent_code_for_not_running(capsys):
    for lang in ("ru", "en"):
        code, data, _ = run_json(capsys, "--lang", lang, "winws", "state")
        assert code == 3 and data["error"]["code"] == "not_running" and data["error"]["key"] == "cli.err.not_running"


def test_config_get_unknown_key_in_english(capsys):
    code, _, err = run(capsys, "--lang", "en", "config", "get", "zzz")
    assert code == 1 and "No setting 'zzz'" in err and not CYRILLIC.search(err)


def test_argparse_errors_are_translated(capsys):
    code, _, err = run(capsys, "--lang", "en", "check", "site")
    assert code == 2 and "missing parameter: domain" in err and "Help: chimera check site --help" in err
    code, _, err = run(capsys, "--lang", "en", "logs", "нечто")
    assert code == 2 and "invalid value" in err
    code, _, err = run(capsys, "--lang", "en", "autostart", "set", "maybe")
    assert code == 2 and "expected on or off" in err
    code, _, err = run(capsys, "--lang", "en", "dns", "set", "abc", "x")
    assert code == 2 and "integer is required" in err and "adapter" in err


def test_default_output_words_follow_language(capsys, monkeypatch):
    from modules.cli.commands import render
    assert render({"a": True, "b": False}) == ["a: да", "b: нет"]
    with i18n.using("en"):
        assert render({"a": True, "b": False}) == ["a: yes", "b: no"]


def test_version_line_in_both_languages(capsys):
    assert "протокол командной строки" in run(capsys, "version")[1]
    assert "command-line protocol" in run(capsys, "--lang", "en", "version")[1]


# --- сообщения приложения приходят по коду ---------------------------------------------------------------------

def test_remote_error_with_code_is_shown_in_cli_language(capsys, tmp_path):
    class Api:
        def dispatch(self, method, args_json):
            return json.dumps({"ok": False, "error": "Нужны права администратора для запуска zapret2",
                               "code": "err.admin.winws", "params": {}})

    srv = control.ControlServer(Api()).start()
    try:
        code, out, err = run(capsys, "--lang", "en", "winws", "start", "x")
        assert code == 1 and "Administrator rights are required to start zapret2." in err
        code, data, _ = run_json(capsys, "--lang", "en", "winws", "start", "x")
        error = data["error"]
        assert error["code"] == "remote_error" and error["key"] == "err.admin.winws" and error["params"] == {}
        assert error["message"].startswith("Administrator rights")
        code, data, _ = run_json(capsys, "winws", "start", "x")
        assert data["error"]["message"] == "Нужны права администратора для запуска zapret2"
    finally:
        srv.stop()


def test_remote_error_without_code_keeps_its_text_and_has_no_key(capsys):
    class Api:
        def dispatch(self, method, args_json):
            return json.dumps({"ok": False, "error": "что-то своё"})

    srv = control.ControlServer(Api()).start()
    try:
        code, data, _ = run_json(capsys, "--lang", "en", "winws", "start", "x")
        assert data["error"]["message"] == "что-то своё" and "key" not in data["error"]
    finally:
        srv.stop()


# --- язык как настройка ------------------------------------------------------------------------------------------------

def test_config_set_lang_offline_validates_and_writes(capsys):
    assert run(capsys, "config", "set", "lang", "en")[0] == 0
    assert appconfig.load()["lang"] == "en"
    code, _, err = run(capsys, "config", "set", "lang", "de")
    assert code == 1 and "de" in err and appconfig.load()["lang"] == "en"


def test_lang_show_and_set_offline(capsys, monkeypatch):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    monkeypatch.setattr(i18n, "detect_system_lang", lambda: "en")
    i18n.refresh()
    code, data, _ = run_json(capsys, "lang", "show")
    assert code == 0 and data["data"] == {"setting": "auto", "lang": "en", "system": "en", "available": ["ru", "en"]}
    code, out, _ = run(capsys, "lang", "set", "ru")
    assert code == 0 and "ru" in out and appconfig.load()["lang"] == "ru"
    code, data, _ = run_json(capsys, "lang", "show")
    assert data["data"]["setting"] == "ru" and data["data"]["lang"] == "ru"
    assert run(capsys, "lang", "set", "de")[0] == 2


def test_lang_catalog_offline_returns_the_catalog(capsys):
    code, data, _ = run_json(capsys, "lang", "catalog", "en")
    assert code == 0
    payload = data["data"]
    assert payload["lang"] == "en" and payload["catalog"]["cli.done"] == "Done."
    assert payload["plural"]["ru"]["categories"] == ["one", "few", "many", "other"]
    code, out, _ = run(capsys, "--lang", "en", "lang", "catalog")
    assert code == 0 and "Catalog for en" in out


def test_lang_is_a_writable_setting_of_the_control_channel():
    assert "lang" in control.CONFIG_KEYS_WRITABLE


# --- документация на английском ---------------------------------------------------------------------------------------------

def test_docs_commands_in_english(capsys):
    code, out, _ = run(capsys, "--lang", "en", "docs", "commands")
    assert code == 0 and "example: chimera winws start" in out and "changes the system" in out
    assert not CYRILLIC.search(out)


def test_docs_json_keeps_ids_and_translates_texts(capsys):
    _, ru, _ = run_json(capsys, "docs")
    _, en, _ = run_json(capsys, "--lang", "en", "docs")
    ru_cmds, en_cmds = ru["data"]["commands"], en["data"]["commands"]
    assert [c["command"] for c in ru_cmds] == [c["command"] for c in en_cmds]
    assert [c["level"] for c in ru_cmds] == [c["level"] for c in en_cmds]
    assert [c["examples"] for c in ru_cmds] == [c["examples"] for c in en_cmds]
    assert ru_cmds[0]["summary"] != en_cmds[0]["summary"]
    ru_args = [a["name"] for c in ru_cmds for a in c["args"]]
    assert ru_args == [a["name"] for c in en_cmds for a in c["args"]]     # идентификаторы не переводятся
    assert {a["label"] for c in en_cmds for a in c["args"]} >= {"strategy", "name", "value"}
    assert set(en["data"]["output"]["exit_codes"]) == {"0", "1", "2", "3"}


def test_agent_info_in_english(capsys):
    code, data, _ = run_json(capsys, "--lang", "en", "agent-info")
    info = data["data"]
    assert code == 0 and info["docs"]["command"] == "chimera docs [topic]"
    assert info["levels"]["system"] == "changes the system"
    assert info["exit_codes"]["0"] == "success"
    assert {c["command"] for c in info["commands"]} == {a.command for a in registry.ACTIONS}


def test_usage_lines_use_localized_argument_names():
    a = registry.BY_GROUP["winws"]["start"]
    from modules.cli import help as helptext
    assert helptext.usage(a) == "chimera winws start [стратегия]"
    with i18n.using("en"):
        assert helptext.usage(a) == "chimera winws start [strategy]"
        assert docs.cli_md().count("`chimera winws start [strategy]`") >= 2
