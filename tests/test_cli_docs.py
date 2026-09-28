"""Документация из программы (chimera docs / agent-info) и docs/CLI.md строятся из кода и не отстают от него."""

import json
from pathlib import Path

import pytest

from modules import control, paths
from modules.cli import app, commands, docs, registry
from modules.cli import help as helptext

ROOT = Path(__file__).resolve().parent.parent


def run_json(capsys, *argv):
    code = app.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


# --- docs/CLI.md ------------------------------------------------------------------------------

def test_committed_cli_md_matches_generated():
    committed = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == docs.cli_md(), "docs/CLI.md устарел: выполните python tools/gen_cli_docs.py"


def test_cli_md_covers_every_action_and_exclusion():
    text = docs.cli_md()
    for a in registry.ACTIONS:
        assert a.ui in text and helptext.usage(a) in text, a.command
    for method in registry.EXCLUDED:
        assert f"`{method}`" in text


def test_generator_check_mode_reports_up_to_date(capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_cli_docs", ROOT / "tools" / "gen_cli_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0


# --- chimera docs ---------------------------------------------------------------------------------

def test_docs_index_and_topics(capsys):
    assert app.main(["docs"]) == 0
    out = capsys.readouterr().out
    for topic in docs.TOPICS:
        assert topic in out
    for topic in docs.TOPICS:
        assert app.main(["docs", topic]) == 0
        assert capsys.readouterr().out.strip(), topic


def test_docs_commands_topic_lists_levels_and_examples(capsys):
    app.main(["docs", "commands"])
    out = capsys.readouterr().out
    assert "chimera winws start" in out and "изменение системы" in out and "пример:" in out


def test_docs_layout_marks_secrets_and_generated(capsys):
    app.main(["docs", "layout"])
    out = capsys.readouterr().out
    assert "data/proxy.json" in out and "секрет" in out and "генерируется" in out
    assert "data/control.json" in out and "data/changes.log" in out


def test_docs_output_topic_has_exit_codes_and_json_format(capsys):
    app.main(["docs", "output"])
    out = capsys.readouterr().out
    assert "3  Chimera не запущена" in out and "schema" in out and "--show-secrets" in out


def test_docs_json_has_everything(capsys):
    code, data = run_json(capsys, "docs")
    assert code == 0 and data["ok"] is True and data["schema"] == 1
    d = data["data"]
    assert set(d) == {"topics", "commands", "layout", "output"}
    assert len(d["commands"]) == len(registry.ACTIONS)
    assert {c["level"] for c in d["commands"]} == {"read", "app", "system"}
    assert d["output"]["exit_codes"]["3"]


def test_docs_unknown_topic_is_usage_error(capsys):
    assert app.main(["docs", "нечто"]) == 2


# --- chimera agent-info ------------------------------------------------------------------------------

def test_agent_info_json(capsys):
    code, data = run_json(capsys, "agent-info")
    assert code == 0
    info = data["data"]
    assert info["program"]["protocol"] == control.PROTOCOL and info["program"]["version"]
    assert info["skill_compat"] == docs.SKILL_COMPAT
    assert {c["command"] for c in info["commands"]} == {a.command for a in registry.ACTIONS}
    assert all(c["level"] in registry.LEVEL_TITLES for c in info["commands"])
    assert set(info["paths"]) >= {"app_dir", "data_dir", "logs_dir", "config", "lists_dir", "changes_log", "control_file"}
    assert info["exit_codes"]["0"]


def test_agent_info_works_without_running_app(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(control, "CONTROL_PATH", tmp_path / "nope.json")
    assert app.main(["agent-info"]) == 0
    assert "протокол" in capsys.readouterr().out


# --- пути в документации совпадают с кодом -------------------------------------------------------------

def _layout_paths() -> set[str]:
    return {p for p, *_ in docs.LAYOUT}


def test_layout_file_names_match_code_constants():
    from modules import dns_providers
    from modules.hosts import manager as hosts_manager
    from modules.proxy import manager as proxy_manager
    from modules.tgproxy import manager as tg_manager
    from modules.winws import manager as winws_manager

    expected = {
        "data/proxy.json": proxy_manager.STATE_PATH, "data/tgproxy.json": tg_manager.STATE_PATH,
        "data/winws.json": winws_manager.STATE_PATH, "data/hosts.json": hosts_manager.STATE_PATH,
        "data/dns_providers.user.json": dns_providers.USER_PATH,
        "data/singbox-config.json": proxy_manager.CONFIG_PATH,
        "data/singbox-domains.json": proxy_manager.DOMAINS_RULESET_PATH,
        "data/singbox-ips.json": proxy_manager.IPS_RULESET_PATH,
        "data/proxy.pac": proxy_manager.PAC_PATH,
        "data/control.json": control.CONTROL_PATH,
        "data/changes.log": commands.CHANGES_LOG,
    }
    layout = _layout_paths()
    for doc_path, real in expected.items():
        assert doc_path in layout, f"{doc_path} нет в раскладке"
        assert doc_path == f"data/{real.name}", f"{doc_path} не совпадает с файлом в коде: {real.name}"
    assert "config.json" in layout and Path("config.json").name == "config.json"
    assert paths.LOG_DIR.name == "logs" and "data/logs/*.log" in layout


def test_log_files_used_by_logs_command_are_documented():
    names = {p.name for p in commands.LOG_FILES.values()}
    assert names == {"winws.log", "proxy.log", "tgproxy.log"}


def test_layout_generated_and_hostlist_files_exist_in_code():
    from modules.winws import manager as winws_manager
    assert f"strategies/hostlists/{winws_manager.USER_HOSTLIST_PATH.name}" in _layout_paths()
    assert f"strategies/hostlists/{winws_manager.USER_IPSET_PATH.name}" in _layout_paths()


@pytest.mark.parametrize("kind", ["edit", "generated", "secret", "log", "internal", "external"])
def test_layout_kinds_are_known(kind):
    assert kind in docs.KIND_TITLES
