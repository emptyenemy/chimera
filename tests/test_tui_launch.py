"""Запуск TUI (tui/launch.py), команда `chimera tui` и связь tui/remote.py с каналом управления."""

import pytest

from modules.cli import client as cl
from modules.cli import commands, registry
from modules.cli.app import main as cli_main
from tui import launch
from tui.remote import Offline, Remote, RemoteError


@pytest.fixture
def menu(monkeypatch):
    """Подменяет старое меню: запоминаем, что его запустили."""
    calls = []
    import tui.app
    monkeypatch.setattr(tui.app, "run", lambda *a, **kw: calls.append("simple") or 0)
    return calls


# --- откат на простое меню --------------------------------------------------------------------------

def test_simple_flag_runs_the_old_menu_without_textual(menu):
    assert launch.run(simple=True) == 0
    assert menu == ["simple"]


def test_outside_a_terminal_it_explains_and_falls_back(menu, capsys):
    assert launch.run(interactive=lambda: False) == 0
    assert menu == ["simple"]
    assert "интерактивный терминал" in capsys.readouterr().err


def test_import_error_falls_back(menu, capsys, monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name == "tui.textual_app":
            raise ImportError("No module named 'textual'")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert launch.run(interactive=lambda: True) == 0
    assert menu == ["simple"]
    assert "Textual" in capsys.readouterr().err


def test_fullscreen_failure_falls_back(menu, capsys, monkeypatch):
    from tui import textual_app

    def boom(self, *a, **kw):
        raise RuntimeError("терминал не тянет")

    monkeypatch.setattr(textual_app.ChimeraTui, "run", boom)
    assert launch.run(interactive=lambda: True, remote=object()) == 0
    assert menu == ["simple"]
    assert "терминал не тянет" in capsys.readouterr().err


def test_fullscreen_runs_textual_app_and_not_the_menu(menu, monkeypatch):
    from tui import textual_app
    ran = []
    monkeypatch.setattr(textual_app.ChimeraTui, "run", lambda self, *a, **kw: ran.append(self.remote))
    remote = object()
    assert launch.run(interactive=lambda: True, remote=remote) == 0
    assert ran == [remote] and menu == []


# --- команда chimera tui --------------------------------------------------------------------------------

def test_tui_command_is_in_the_table_at_app_level():
    act = registry.BY_GROUP["tui"][""]
    assert act.level == registry.APP and act.handler == "tui" and act.offline


def test_cli_tui_passes_simple_flag(monkeypatch):
    got = []
    monkeypatch.setattr(launch, "run", lambda simple=False, **kw: got.append(simple) or 0)
    assert cli_main(["tui"]) == 0
    assert cli_main(["tui", "--simple"]) == 0
    assert got == [False, True]


def test_cli_tui_returns_the_exit_code(monkeypatch):
    monkeypatch.setattr(launch, "run", lambda simple=False, **kw: 5)
    assert cli_main(["tui"]) == 5


def test_cli_tui_has_no_json_output(capsys):
    assert cli_main(["tui", "--json"]) == 2
    assert "нет вывода в JSON" in capsys.readouterr().out


def test_tui_start_is_not_written_to_the_change_journal(monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "CHANGES_LOG", tmp_path / "changes.log")
    commands.record_change(registry.BY_GROUP["tui"][""], ["tui"], True)
    assert not (tmp_path / "changes.log").exists()


# --- Remote ---------------------------------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []
        self.timeout = 0

    def api(self, method, *args, reveal=False):
        self.calls.append((method, args, reveal))
        if self.error:
            raise self.error
        return self.result


def test_remote_never_asks_for_secrets_and_masks_them_anyway():
    client = FakeClient({"link": "vless://secret-uuid@host", "port": 1})
    data = Remote(connect=lambda: client).call("proxy_state", 1)
    assert client.calls == [("proxy_state", (1,), False)]
    assert "secret-uuid" not in str(data)
    assert data["port"] == 1


def test_remote_keeps_telegram_link_for_connecting():
    link = "tg://proxy?server=127.0.0.1&port=1443&secret=dd00"
    data = Remote(connect=lambda: FakeClient({"link": link, "secret": "00"})).call("tg_state")
    assert data == {"link": link, "secret": "00"}


def test_remote_maps_errors():
    with pytest.raises(Offline):
        Remote(connect=lambda: (_ for _ in ()).throw(cl.NotRunning())).call("app_info")
    with pytest.raises(Offline):
        Remote(connect=lambda: FakeClient(error=cl.CliError("файл связи устарел", "forbidden", 3))).call("app_info")
    with pytest.raises(Offline):
        Remote(connect=lambda: FakeClient(error=ConnectionResetError())).call("app_info")
    with pytest.raises(RemoteError, match="нужны права"):
        Remote(connect=lambda: FakeClient(error=cl.CliError("нужны права", "remote_error", 1))).call("dns_set")


def test_remote_reconnects_after_a_lost_connection():
    clients = [FakeClient(error=ConnectionResetError()), FakeClient({"ok": 1})]
    r = Remote(connect=lambda: clients.pop(0))
    with pytest.raises(Offline):
        r.call("app_info")
    assert r.call("app_info") == {"ok": 1}


def test_ensure_running_does_nothing_if_chimera_is_up():
    launched = []
    r = Remote(discover=lambda: object(), launch=lambda: launched.append(1))
    assert r.ensure_running() is False and launched == []


def test_ensure_running_starts_chimera_without_window_and_waits():
    state = {"up": False}
    launched, said = [], []

    def launch_():
        launched.append(1)
        state["up"] = True

    r = Remote(discover=lambda: object() if state["up"] else None, launch=launch_, wait=lambda cond, t, step=0.3: cond())
    assert r.ensure_running(said.append) is True
    assert launched == [1] and said


def test_ensure_running_gives_up_when_chimera_does_not_come_up():
    r = Remote(discover=lambda: None, launch=lambda: None, wait=lambda cond, t, step=0.3: False)
    with pytest.raises(Offline, match="запуска"):
        r.ensure_running()


def test_record_writes_a_tui_line_to_the_journal(monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "CHANGES_LOG", tmp_path / "changes.log")
    Remote().record("tg start", True)
    line = (tmp_path / "changes.log").read_text(encoding="utf-8").strip().split("\t")
    assert line[1:] == ["tui", "tg start", "ok"]


def test_build_bat_ships_textual_and_rich():
    from pathlib import Path
    bat = (Path(__file__).resolve().parent.parent / "build.bat").read_text(encoding="ascii")
    for pkg in ("textual", "rich", "markdown_it"):
        assert f"--include-package={pkg}" in bat
    assert "textual" in (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8")
