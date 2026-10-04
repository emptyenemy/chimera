"""modules/cli — командная строка chimera.

Команды гоняем против настоящего сервера управления (modules/control.py) с фиктивным Api,
чтобы проверить всю цепочку: разбор аргументов, связь, вывод, коды возврата. Ничего
настоящего (winws2, hosts, DNS) не запускается.
"""

import io
import json

import pytest

from modules import control
from modules.cli import app, client, commands, registry


class FakeApi:
    """Фиктивный Api: отвечает готовыми состояниями и помнит, что у него просили."""

    def __init__(self):
        self.calls = []
        self.fail = {}
        self.extra = {}
        self.shutdowns = 0
        self.quit_asked = False
        self.on_quit = None

    def dispatch(self, method, args_json):
        args = json.loads(args_json)
        self.calls.append((method, args))
        if method in self.fail:
            return json.dumps({"ok": False, "error": self.fail[method]})
        table = {
            "app_info": {"admin": True, "version": "1.0.0", "service_running": False, "frozen": False},
            "winws_state": {"strategies": [{"id": "general", "name": "General"}, {"id": "alt2", "name": "ALT2"}],
                            "running": True, "current": "general", "last_strategy": "general",
                            "lists": ["discord"], "error": None},
            "proxy_state": {"running": False, "mode": "pac", "link": "vless://uuid@1.2.3.4:443?x=1",
                            "domains": 10, "ips": 2, "error": None},
            "tg_state": {"running": True, "host": "127.0.0.1", "port": 1443, "secret": "abcdef",
                         "autostart": False, "link": "tg://proxy?server=1.2.3.4&port=1443&secret=ddabcdef",
                         "error": None},
            "hosts_state": {"applied": True, "enabled": True, "count": 3,
                            "assignments": {"comss": ["youtube"]}, "background": {"refresh_enabled": True}},
            "dns_state": {"adapters": [{"index": 12, "name": "Ethernet", "servers": ["1.1.1.1"]}]},
            "dns_probe_config": {"bypass": ["rutracker.org"], "ad": "doubleclick.net"},
            "lists_read": "# youtube\nyoutube.com\nggpht.com\n",
            "lists_all": [{"name": "youtube", "count": 2}],
            "lists_save": {"name": "youtube", "count": 3},
            "config_read": {"update_channel": "stable", "auto_elevate": True, "ui_backend": "pyside6"},
            "config_set": {"update_channel": "beta"},
            "selfupdate_check": {"current": "1.0.0", "latest": "1.1.0", "update": True, "installable": True},
            "selfupdate_install": {"stage": "installing"},
            "block_check_one": {"domain": "discord.com", "verdict": "ok"},
            "chebur_check_one": {"domain": "discord.com", "blocked": False},
        }
        table.update(self.extra)
        return json.dumps({"ok": True, "data": table.get(method, {})})

    def shutdown(self):
        self.shutdowns += 1

    def request_quit(self):
        self.quit_asked = True
        if self.on_quit:
            self.on_quit()

    def called(self, method):
        return [a for m, a in self.calls if m == method]


@pytest.fixture
def running(tmp_path, monkeypatch):
    """Работающая «Chimera»: сервер управления + файл со связью во временной папке."""
    monkeypatch.setattr(control, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(commands, "CHANGES_LOG", tmp_path / "changes.log")
    api = FakeApi()
    srv = control.ControlServer(api).start()
    api.on_quit = srv.stop  # закрытая «программа» исчезает вместе с файлом связи
    yield api, srv
    srv.stop()


@pytest.fixture
def stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(commands, "CHANGES_LOG", tmp_path / "changes.log")
    return tmp_path


def run(capsys, *argv):
    code = app.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    return code, json.loads(out), err


# --- справка, версия, ошибки разбора -------------------------------------------------

def test_no_arguments_prints_help(capsys):
    code, out, _ = run(capsys)
    assert code == 0
    assert "chimera <команда>" in out and "Коды возврата" in out


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["help"]])
def test_help_forms(capsys, argv):
    code, out, _ = run(capsys, *argv)
    assert code == 0 and "winws" in out and "--json" in out


def test_main_help_lists_every_command(capsys):
    _, out, _ = run(capsys, "--help")
    for group in registry.GROUPS:
        assert group in out, group


def test_each_command_has_its_own_help_with_examples(capsys):
    for name in registry.GROUPS:
        code, out, _ = run(capsys, name, "--help")
        assert code == 0, name
        assert f"chimera {name}" in out and "Примеры" in out, name


def test_each_action_has_its_own_help_with_level(capsys):
    for act in registry.ACTIONS:
        argv = [act.group] + ([act.name] if act.name else []) + ["--help"]
        code, out, _ = run(capsys, *argv)
        assert code == 0, act.command
        assert "Уровень:" in out and act.summary.split(".")[0] in out, act.command
        assert act.examples, f"у {act.command} нет примеров"


def test_help_for_a_command_via_help_word(capsys):
    code, out, _ = run(capsys, "help", "winws")
    assert code == 0 and "chimera winws start" in out


def test_version_works_without_running_app(capsys, stopped):
    code, out, _ = run(capsys, "--version")
    assert code == 0 and "Chimera" in out


def test_version_json(capsys, stopped):
    code, data, _ = run_json(capsys, "--version")
    assert code == 0 and data["ok"] is True and data["schema"] == 1
    assert data["data"]["protocol"] == control.PROTOCOL and "version" in data["data"]
    assert data["level"] == "read"


def test_unknown_command_is_usage_error(capsys):
    code, out, err = run(capsys, "нечто")
    assert code == 2 and "Неизвестная команда" in err and out == ""


def test_bad_action_is_usage_error(capsys):
    code, _, err = run(capsys, "winws", "прыгнуть")
    assert code == 2 and "winws" in err


def test_group_without_action_is_usage_error(capsys):
    code, _, err = run(capsys, "winws")
    assert code == 2 and "start" in err


def test_missing_required_argument_is_usage_error(capsys):
    code, _, err = run(capsys, "check", "site")
    assert code == 2 and "домен" in err.lower()


def test_usage_error_in_json_mode(capsys):
    code, data, _ = run_json(capsys, "нечто")
    assert code == 2 and data["ok"] is False and data["error"]["code"] == "usage"


# --- нет связи -----------------------------------------------------------------------

def test_not_running_is_exit_3_with_hint(capsys, stopped):
    code, _, err = run(capsys, "status")
    assert code == 3
    assert "Chimera не запущена" in err and "chimera start" in err


def test_not_running_json(capsys, stopped):
    code, data, _ = run_json(capsys, "winws", "state")
    assert code == 3 and data["ok"] is False and data["error"]["code"] == "not_running"


def test_stale_discovery_file_means_not_running(capsys, stopped):
    # файл остался от упавшей копии: порт никто не слушает
    control.CONTROL_PATH.write_text(json.dumps({"port": 1, "token": "x", "pid": 1, "protocol": 1}), encoding="utf-8")
    code, _, err = run(capsys, "status")
    assert code == 3 and "не запущена" in err


def test_old_app_protocol_asks_to_update(capsys, running, monkeypatch):
    monkeypatch.setattr(control, "PROTOCOL", 1)
    monkeypatch.setattr(client, "CLI_PROTOCOL", 2)
    code, _, err = run(capsys, "status")
    assert code == 3 and "chimera update" in err and "старая" in err


# --- status и управление модулями ---------------------------------------------------------

def test_status_human(capsys, running):
    code, out, _ = run(capsys, "status")
    assert code == 0
    assert "1.0.0" in out and "general" in out
    assert "uuid@" not in out  # ссылка прокси скрыта


def test_status_json_has_stable_keys(capsys, running):
    code, data, _ = run_json(capsys, "status")
    assert code == 0 and data["schema"] == 1 and data["ok"] is True
    d = data["data"]
    assert d["app"]["version"] == "1.0.0"
    assert d["winws"]["running"] is True and d["winws"]["current"] == "general"
    assert d["proxy"]["running"] is False and d["tg"]["running"] is True
    assert d["hosts"]["applied"] is True
    assert "uuid@" not in json.dumps(data)


def test_show_secrets_reveals_link(capsys, running):
    code, data, _ = run_json(capsys, "status", "--show-secrets")
    assert code == 0 and "uuid@1.2.3.4" in json.dumps(data)


def test_json_returns_what_the_api_returned(capsys, running):
    code, data, _ = run_json(capsys, "hosts", "state")
    assert code == 0
    assert data["data"] == {"applied": True, "enabled": True, "count": 3,
                            "assignments": {"comss": ["youtube"]}, "background": {"refresh_enabled": True}}


def test_winws_start_with_explicit_strategy(capsys, running):
    api, _ = running
    code, out, _ = run(capsys, "winws", "start", "alt2")
    assert code == 0 and api.called("winws_start") == [["alt2"]]


def test_winws_start_without_id_uses_last_strategy(capsys, running):
    api, _ = running
    api.extra["winws_start"] = {"running": True}
    # без имени команда сама подставляет последнюю стратегию из состояния
    code, _, _ = run(capsys, "winws", "start")
    assert code == 0
    assert api.called("winws_start") == [["general"]]


def test_winws_strategies_lists_ids(capsys, running):
    code, out, _ = run(capsys, "winws", "strategies")
    assert code == 0 and "alt2" in out and "general" in out


def test_winws_stop_and_state(capsys, running):
    api, _ = running
    assert run(capsys, "winws", "stop")[0] == 0
    assert api.called("winws_stop") == [[]]
    code, data, _ = run_json(capsys, "winws", "state")
    assert code == 0 and data["data"]["running"] is True


def test_winws_autostart_lists_game_ipset_fake(capsys, running):
    api, _ = running
    assert run(capsys, "winws", "autostart", "on")[0] == 0
    assert run(capsys, "winws", "lists", "youtube", "discord")[0] == 0
    assert run(capsys, "winws", "lists")[0] == 0
    assert run(capsys, "winws", "game", "udp", "--tcp", "1024-2000")[0] == 0
    assert run(capsys, "winws", "ipset", "loaded")[0] == 0
    assert run(capsys, "winws", "ipset-update")[0] == 0
    assert run(capsys, "winws", "fake", "discord", "blob1")[0] == 0
    assert run(capsys, "winws", "filters")[0] == 0
    assert api.called("winws_set_autostart") == [[True]]
    assert api.called("winws_set_lists") == [[["youtube", "discord"]], [[]]]
    assert api.called("game_filter_set") == [["udp", "1024-2000", None]]
    assert api.called("ipset_set") == [["loaded"]]
    assert api.called("fake_set") == [["discord", "blob1"]]


def test_remote_error_is_exit_1_without_traceback(capsys, running):
    api, _ = running
    api.fail["winws_start"] = "Нужны права администратора"
    code, _, err = run(capsys, "winws", "start", "x")
    assert code == 1 and "Нужны права администратора" in err and "Traceback" not in err


def test_remote_error_json(capsys, running):
    api, _ = running
    api.fail["winws_start"] = "нет такой стратегии"
    code, data, _ = run_json(capsys, "winws", "start", "x")
    assert code == 1 and data["ok"] is False
    assert data["error"]["code"] == "remote_error" and "нет такой" in data["error"]["message"]


def test_proxy_commands(capsys, running):
    api, _ = running
    assert run(capsys, "proxy", "start")[0] == 0
    assert run(capsys, "proxy", "stop")[0] == 0
    assert run(capsys, "proxy", "mode", "tun")[0] == 0
    assert run(capsys, "proxy", "lists", "youtube")[0] == 0
    assert run(capsys, "proxy", "apps", "Discord.exe", "chrome.exe")[0] == 0
    assert run(capsys, "proxy", "apps-running")[0] == 0
    assert run(capsys, "proxy", "autostart", "off")[0] == 0
    assert run(capsys, "proxy", "core-download")[0] == 0
    assert api.called("proxy_set_mode") == [["tun"]]
    assert api.called("proxy_set_apps") == [[["Discord.exe", "chrome.exe"]]]
    assert api.called("proxy_set_autostart") == [[False]]


def test_proxy_mode_rejects_unknown_value(capsys, running):
    code, _, err = run(capsys, "proxy", "mode", "vpn")
    assert code == 2 and "pac" in err


def test_proxy_link_set_clear_and_stdin(capsys, running, monkeypatch):
    api, _ = running
    assert run(capsys, "proxy", "link", "vless://x@y:1")[0] == 0
    assert run(capsys, "proxy", "link", "--clear")[0] == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("trojan://p@h:2\n"))
    assert run(capsys, "proxy", "link", "-")[0] == 0
    assert api.called("proxy_set_link") == [["vless://x@y:1"], [""], ["trojan://p@h:2"]]


def test_proxy_link_without_value_is_usage_error(capsys, running):
    code, _, err = run(capsys, "proxy", "link")
    assert code == 2 and "ссылку" in err


def test_tg_commands(capsys, running):
    api, _ = running
    assert run(capsys, "tg", "start")[0] == 0
    assert run(capsys, "tg", "stop")[0] == 0
    assert run(capsys, "tg", "stats")[0] == 0
    assert run(capsys, "tg", "regen-secret")[0] == 0
    assert run(capsys, "tg", "check-update")[0] == 0
    assert ("tg_start", []) in api.calls and api.called("tg_regen_secret") == [[]]


def test_tg_state_shows_link_and_secret(capsys, running):
    code, out, _ = run(capsys, "tg", "state")
    assert code == 0 and "ddabcdef" in out


def test_tg_link_is_shown_in_full(capsys, running):
    code, out, _ = run(capsys, "tg", "link")
    assert code == 0 and out.strip() == "tg://proxy?server=1.2.3.4&port=1443&secret=ddabcdef"
    code, data, _ = run_json(capsys, "tg", "link")
    assert data["data"]["link"].endswith("secret=ddabcdef")


def test_tg_config_merges_with_current_settings(capsys, running):
    api, _ = running
    assert run(capsys, "tg", "config", "--host", "0.0.0.0")[0] == 0
    # порт, секрет и автозапуск берутся из текущих настроек (с реальным секретом, а не маской)
    assert api.called("tg_set_config") == [["0.0.0.0", 1443, None, False]]


def test_tg_advanced_parses_key_values(capsys, running):
    api, _ = running
    code, _, _ = run(capsys, "tg", "advanced", "fallback_cfproxy=false", "fake_tls_domain=example.com",
                     "cfproxy_user_domains=a.example,b.example")
    assert code == 0
    assert api.called("tg_set_advanced") == [[{"fallback_cfproxy": False, "fake_tls_domain": "example.com",
                                               "cfproxy_user_domains": ["a.example", "b.example"]}]]


def test_tg_advanced_bad_pair_is_usage_error(capsys, running):
    code, _, err = run(capsys, "tg", "advanced", "oops")
    assert code == 2 and "ключ=значение" in err


def test_hosts_commands(capsys, running):
    api, _ = running
    assert run(capsys, "hosts", "on")[0] == 0
    assert run(capsys, "hosts", "off")[0] == 0
    assert run(capsys, "hosts", "overview")[0] == 0
    assert run(capsys, "hosts", "ping", "comss")[0] == 0
    assert run(capsys, "hosts", "provider-add", "my", "https://d/dns-query", "1.2.3.4", "5.6.7.8")[0] == 0
    assert run(capsys, "hosts", "provider-delete", "my")[0] == 0
    assert api.called("hosts_set_enabled") == [[True], [False]]
    assert api.called("hosts_add_provider") == [["my", "https://d/dns-query", ["1.2.3.4", "5.6.7.8"]]]
    assert api.called("hosts_delete_provider") == [["my"]]


def test_hosts_assign_merges_and_replaces(capsys, running):
    api, _ = running
    assert run(capsys, "hosts", "assign", "xbox=discord,steam", "comss=")[0] == 0
    # comss опустошён (снят), остальные привязки не тронуты, xbox добавлен
    assert api.called("hosts_set_assignments")[0] == [{"xbox": ["discord", "steam"]}]
    assert run(capsys, "hosts", "assign", "malw=notion", "--replace")[0] == 0
    assert api.called("hosts_set_assignments")[1] == [{"malw": ["notion"]}]


def test_hosts_assign_keeps_unmentioned(capsys, running):
    api, _ = running
    assert run(capsys, "hosts", "assign", "xbox=discord")[0] == 0
    assert api.called("hosts_set_assignments") == [[{"comss": ["youtube"], "xbox": ["discord"]}]]


def test_hosts_background_show_and_set(capsys, running):
    api, _ = running
    code, data, _ = run_json(capsys, "hosts", "background")
    assert data["data"] == {"refresh_enabled": True}
    assert run(capsys, "hosts", "background", "refresh_enabled=false")[0] == 0
    assert api.called("hosts_set_background") == [[{"refresh_enabled": False}]]


def test_dns_commands(capsys, running):
    api, _ = running
    assert run(capsys, "dns", "set", "12", "cloudflare")[0] == 0
    assert run(capsys, "dns", "reset", "12")[0] == 0
    assert run(capsys, "dns", "state")[0] == 0
    assert run(capsys, "dns", "ping")[0] == 0
    assert run(capsys, "dns", "ping", "google")[0] == 0
    assert run(capsys, "dns", "probe", "google")[0] == 0
    assert api.called("dns_set") == [[12, "cloudflare"]] and api.called("dns_reset") == [[12]]
    assert api.called("dns_ping_one") == [["google"]] and api.called("dns_ping") == [[]]


def test_dns_adapter_must_be_a_number(capsys, running):
    code, _, err = run(capsys, "dns", "set", "eth", "cloudflare")
    assert code == 2 and "номер" in err.lower()


def test_dns_provider_add_and_delete(capsys, running):
    api, _ = running
    code, _, _ = run(capsys, "dns", "provider-add", "my", "9.9.9.9", "1.1.1.1", "--doh", "https://d/q", "--unblock")
    assert code == 0
    assert api.called("dns_add_provider") == [["my", ["9.9.9.9", "1.1.1.1"], "", "https://d/q", "", True, False]]
    assert run(capsys, "dns", "provider-delete", "my")[0] == 0


def test_dns_probe_config_show_and_partial_set(capsys, running):
    api, _ = running
    assert run(capsys, "dns", "probe-config")[0] == 0
    assert run(capsys, "dns", "probe-config", "--ad", "ads.example")[0] == 0
    # bypass не указан — берётся текущий
    assert api.called("dns_set_probe_config") == [[["rutracker.org"], "ads.example"]]


# --- start / stop / restart / update ---------------------------------------------------------

def test_stop_asks_the_app_to_quit(capsys, running):
    api, _ = running
    code, out, _ = run(capsys, "stop")
    assert code == 0 and "закрыта" in out.lower()
    assert api.quit_asked and api.shutdowns == 1


def test_stop_when_not_running_is_success(capsys, stopped):
    code, out, _ = run(capsys, "stop")
    assert code == 0 and "не запущена" in out.lower()


def test_stop_times_out_when_app_does_not_go_away(capsys, running, monkeypatch):
    api, _ = running
    api.on_quit = None  # «программа» не закрывается
    monkeypatch.setattr(commands, "WAIT_STOP", 0.4)
    code, _, err = run(capsys, "stop")
    assert code == 1 and "не закрылась" in err


def test_restart_asks_the_app_to_restart(capsys, running, monkeypatch):
    spawned = []
    monkeypatch.setattr(control, "spawn_relaunch", lambda: spawned.append(1))
    monkeypatch.setattr(commands, "WAIT_RESTART", 0)
    code, out, _ = run(capsys, "restart")
    assert code == 0 and "перезапущена" in out
    assert spawned == [1]


def test_start_when_already_running(capsys, running, monkeypatch):
    launched = []
    monkeypatch.setattr(commands, "launch_app", lambda: launched.append(1))
    code, out, _ = run(capsys, "start")
    assert code == 0 and "уже запущена" in out and launched == []


def test_start_launches_app_and_waits_for_channel(capsys, stopped, monkeypatch):
    started = []

    def fake_launch():
        started.append(control.ControlServer(FakeApi()).start())

    monkeypatch.setattr(commands, "launch_app", fake_launch)
    monkeypatch.setattr(commands, "WAIT_START", 5)
    try:
        code, out, _ = run(capsys, "start")
        assert code == 0 and "запущена" in out
    finally:
        for srv in started:
            srv.stop()


def test_start_times_out_with_exit_3(capsys, stopped, monkeypatch):
    monkeypatch.setattr(commands, "launch_app", lambda: None)
    monkeypatch.setattr(commands, "WAIT_START", 0.3)
    code, _, err = run(capsys, "start")
    assert code == 3 and "не удалось" in err.lower()


def test_launch_app_starts_window_in_tray(monkeypatch):
    got = []
    monkeypatch.setattr(commands.subprocess, "Popen", lambda cmd, **kw: got.append(cmd))
    commands.launch_app()
    assert got[0][-2:] == ["--window", "--tray"]


def test_update_commands(capsys, running):
    api, _ = running
    code, out, _ = run(capsys, "update", "check")
    assert code == 0 and "1.1.0" in out
    assert run(capsys, "update", "state")[0] == 0
    assert run(capsys, "update", "install")[0] == 0
    assert ("selfupdate_check", []) in api.calls and ("selfupdate_install", []) in api.calls


def test_autostart_discord_sources(capsys, running):
    api, _ = running
    assert run(capsys, "autostart", "state")[0] == 0
    assert run(capsys, "autostart", "set", "on")[0] == 0
    assert run(capsys, "discord", "clear-cache")[0] == 0
    assert run(capsys, "sources", "versions")[0] == 0
    assert run(capsys, "sources", "check")[0] == 0
    assert run(capsys, "sources", "check", "zapret2")[0] == 0
    assert run(capsys, "sources", "update", "zapret2")[0] == 0
    assert api.called("autostart_set") == [[True]]
    assert api.called("upstream_check_one") == [["zapret2"]] and api.called("upstream_update") == [["zapret2"]]
    assert api.called("upstream_check_updates") == [[]]


# --- списки, проверки, настройки, логи -----------------------------------------------------

@pytest.fixture
def local_lists(tmp_path, monkeypatch):
    from modules import domains
    d = tmp_path / "lists"
    d.mkdir()
    (d / "youtube.txt").write_text("# youtube\nyoutube.com\nggpht.com\n", encoding="utf-8")
    (d / "discord.txt").write_text("discord.com\n", encoding="utf-8")
    monkeypatch.setattr(domains, "LISTS_DIR", d)
    return d


def test_lists_show_works_without_running_app(capsys, stopped, local_lists):
    code, out, _ = run(capsys, "lists", "show")
    assert code == 0 and "youtube" in out and "discord" in out


def test_lists_show_one_list(capsys, stopped, local_lists):
    code, out, _ = run(capsys, "lists", "show", "youtube")
    assert code == 0 and "youtube.com" in out and "ggpht.com" in out


def test_lists_show_json(capsys, stopped, local_lists):
    code, data, _ = run_json(capsys, "lists", "show")
    assert code == 0
    assert {"name": "youtube", "count": 2} in data["data"]


def test_lists_add_offline_writes_file_without_duplicates(capsys, stopped, local_lists):
    code, out, _ = run(capsys, "lists", "add", "youtube", "ytimg.com", "youtube.com")
    assert code == 0
    text = (local_lists / "youtube.txt").read_text(encoding="utf-8")
    assert text.count("youtube.com") == 1 and "ytimg.com" in text
    assert "добавлено: 1" in out.lower()


def test_lists_remove_offline(capsys, stopped, local_lists):
    code, _, _ = run(capsys, "lists", "remove", "youtube", "ggpht.com")
    assert code == 0
    assert "ggpht.com" not in (local_lists / "youtube.txt").read_text(encoding="utf-8")


def test_lists_add_creates_missing_list(capsys, stopped, local_lists):
    code, _, _ = run(capsys, "lists", "add", "newlist", "a.example")
    assert code == 0 and "a.example" in (local_lists / "newlist.txt").read_text(encoding="utf-8")


def test_lists_add_online_goes_through_the_app(capsys, running):
    api, _ = running
    code, _, _ = run(capsys, "lists", "add", "youtube", "ytimg.com")
    assert code == 0
    saved = api.called("lists_save")
    assert saved and saved[0][0] == "youtube" and "ytimg.com" in saved[0][1]


def test_lists_save_from_file_and_create(capsys, stopped, local_lists, tmp_path):
    src = tmp_path / "new.txt"
    src.write_text("one.example\ntwo.example\n", encoding="utf-8")
    code, _, _ = run(capsys, "lists", "save", "discord", "--file", str(src))
    assert code == 0
    assert (local_lists / "discord.txt").read_text(encoding="utf-8").splitlines() == ["one.example", "two.example"]
    assert run(capsys, "lists", "create", "games")[0] == 0
    assert (local_lists / "games.txt").exists()


def test_lists_delete_and_rename_need_the_app(capsys, stopped, local_lists):
    code, _, err = run(capsys, "lists", "delete", "discord")
    assert code == 3 and "не запущена" in err
    assert run(capsys, "lists", "rename", "discord", "d2")[0] == 3


def test_lists_delete_and_rename_online(capsys, running):
    api, _ = running
    assert run(capsys, "lists", "delete", "games")[0] == 0
    assert run(capsys, "lists", "rename", "a", "b")[0] == 0
    assert api.called("lists_delete") == [["games"]] and api.called("lists_rename") == [["a", "b"]]


def test_lists_validate_ok_without_running_app(capsys, stopped, local_lists):
    code, data, _ = run_json(capsys, "lists", "validate", "youtube")
    assert code == 0 and data["ok"] is True
    res = data["data"]["lists"][0]
    assert res["name"] == "youtube" and res["entries"] == 2 and res["errors"] == []


def test_lists_validate_all_lists_and_reports_errors_with_exit_code_1(capsys, stopped, local_lists):
    (local_lists / "bad.txt").write_text("ok.example\nbad..dots.example\n", encoding="utf-8")
    code, out, _ = run(capsys, "lists", "validate")
    assert code == 1
    assert "bad" in out and "строка 2" in out and "youtube" in out


def test_lists_validate_json_lists_problems(capsys, stopped, local_lists):
    (local_lists / "bad.txt").write_text("a.example\na.example\nhas space.example\n*.b.example\n", encoding="utf-8")
    code, data, _ = run_json(capsys, "lists", "validate", "bad")
    res = data["data"]["lists"][0]
    assert code == 1 and data["ok"] is False
    assert [e["line"] for e in res["errors"]] == [3]
    # дубль и *. — предупреждения: звёздочку программа отбрасывает сама
    assert [w["line"] for w in res["warnings"]] == [2, 4]


def test_lists_validate_all_survives_a_file_with_invalid_name(capsys, stopped, local_lists):
    (local_lists / "a b.txt").write_text("x.example\n", encoding="utf-8")
    code, data, _ = run_json(capsys, "lists", "validate")
    rows = {r["name"]: r for r in data["data"]["lists"]}
    assert code == 1 and rows["a b"]["ok"] is False and "Имя списка" in rows["a b"]["errors"][0]["problem"]
    assert rows["youtube"]["ok"] is True  # остальные проверены


def test_lists_validate_unknown_list_is_not_found(capsys, stopped, local_lists):
    code, _, err = run(capsys, "lists", "validate", "nope")
    assert code == 1 and "nope" in err


def test_lists_apply_goes_through_the_app(capsys, running):
    api, _ = running
    api.extra["lists_apply"] = {"applied": ["youtube"], "modules": ["winws"], "apply_errors": []}
    code, out, _ = run(capsys, "lists", "apply", "youtube")
    assert code == 0 and api.called("lists_apply") == [["youtube"]]
    assert "youtube" in out


def test_lists_apply_without_name_applies_everything(capsys, running):
    api, _ = running
    api.extra["lists_apply"] = {"applied": ["a", "b"], "modules": [], "apply_errors": []}
    assert run(capsys, "lists", "apply")[0] == 0
    assert api.called("lists_apply") == [[None]]


def test_lists_apply_reports_module_errors_with_exit_code_1(capsys, running):
    api, _ = running
    api.extra["lists_apply"] = {"applied": ["youtube"], "modules": ["hosts"],
                                "apply_errors": [{"module": "hosts", "error": "нет прав"}]}
    code, out, _ = run(capsys, "lists", "apply", "youtube")
    assert code == 1 and "hosts" in out and "нет прав" in out


def test_lists_apply_when_only_the_service_runs_explains_why(capsys, stopped, monkeypatch):
    from modules import service
    monkeypatch.setattr(service, "is_running", lambda: True)
    code, data, _ = run_json(capsys, "lists", "apply")
    assert code == 3
    assert data["error"]["code"] == "service_only"
    assert "сама" in data["error"]["message"]  # служба следит за списками сама


def test_lists_apply_without_any_process_says_nothing_to_apply(capsys, stopped, monkeypatch):
    from modules import service
    monkeypatch.setattr(service, "is_running", lambda: False)
    code, _, err = run(capsys, "lists", "apply")
    assert code == 3 and "не запущена" in err


def test_check_offline_uses_local_checkers(capsys, stopped, monkeypatch):
    from modules import blockcheck, cheburcheck
    monkeypatch.setattr(blockcheck, "check", lambda d, socks_addr=None: {"domain": d, "verdict": "ok"})
    monkeypatch.setattr(cheburcheck, "check", lambda d: {"domain": d, "blocked": False})
    code, data, _ = run_json(capsys, "check", "discord.com")
    assert code == 0
    assert data["data"]["local"]["verdict"] == "ok" and data["data"]["registry"]["blocked"] is False


def test_check_online_goes_through_the_app(capsys, running):
    api, _ = running
    code, _, _ = run(capsys, "check", "site", "discord.com")
    assert code == 0
    assert api.called("block_check_one") == [["discord.com"]]
    assert api.called("chebur_check_one") == [["discord.com"]]


def test_check_only_local(capsys, running):
    api, _ = running
    code, _, _ = run(capsys, "check", "discord.com", "--only", "local")
    assert code == 0
    assert api.called("chebur_check_one") == []


def test_check_list_and_status(capsys, running):
    api, _ = running
    code, data, _ = run_json(capsys, "check", "list", "youtube", "--only", "local")
    assert code == 0
    assert [r["domain"] for r in data["data"]["results"]] == ["youtube.com", "ggpht.com"]
    assert run(capsys, "check", "status")[0] == 0


def test_config_get_offline(capsys, stopped, monkeypatch):
    from modules import appconfig
    monkeypatch.setattr(appconfig, "load", lambda: {"update_channel": "stable", "ui_backend": "pyside6"})
    code, out, _ = run(capsys, "config", "get", "update_channel")
    assert code == 0 and "stable" in out
    code, data, _ = run_json(capsys, "config", "get")
    assert data["data"]["ui_backend"] == "pyside6"


def test_config_get_unknown_key(capsys, stopped, monkeypatch):
    from modules import appconfig
    monkeypatch.setattr(appconfig, "load", lambda: {"a": 1})
    code, _, err = run(capsys, "config", "get", "zzz")
    assert code == 1 and "zzz" in err


def test_config_set_online_and_forbidden_key(capsys, running):
    api, _ = running
    assert run(capsys, "config", "set", "update_channel", "beta")[0] == 0
    assert api.called("config_set") == [["update_channel", "beta"]]
    code, _, err = run(capsys, "config", "set", "interface", "service")
    assert code == 1 and "нельзя" in err


def test_config_set_parses_json_literals(capsys, running):
    api, _ = running
    run(capsys, "config", "set", "update_check", "false")
    assert api.called("config_set") == [["update_check", False]]


def test_config_set_offline_writes_config_and_refuses_unsafe_keys(capsys, stopped, monkeypatch):
    from modules import appconfig
    saved = {}
    monkeypatch.setattr(appconfig, "set_value", lambda k, v: saved.update({k: v}) or saved)
    assert run(capsys, "config", "set", "update_channel", "beta")[0] == 0
    assert saved == {"update_channel": "beta"}
    code, _, err = run(capsys, "config", "set", "interface", "service")
    assert code == 1 and "нельзя" in err and "interface" not in saved


def test_logs_tail(capsys, stopped, tmp_path, monkeypatch):
    log = tmp_path / "winws.log"
    log.write_text("\n".join(f"строка {i}" for i in range(10)) + "\n", encoding="utf-8")
    monkeypatch.setattr(commands, "LOG_FILES", {"winws": log, "proxy": tmp_path / "p.log", "tg": tmp_path / "t.log"})
    code, out, _ = run(capsys, "logs", "winws", "--tail", "3")
    assert code == 0 and out.strip().splitlines() == ["строка 7", "строка 8", "строка 9"]


def test_logs_missing_file(capsys, stopped, tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "LOG_FILES", {"winws": tmp_path / "nope.log", "proxy": tmp_path / "p.log",
                                                 "tg": tmp_path / "t.log"})
    code, out, _ = run(capsys, "logs", "winws")
    assert code == 0 and "пуст" in out.lower()


def test_logs_unknown_module(capsys):
    code, _, err = run(capsys, "logs", "камень")
    assert code == 2 and "winws" in err


def test_service_is_passed_to_service_cli(capsys, monkeypatch):
    from modules import service
    got = []
    monkeypatch.setattr(service, "cli", lambda argv: got.append(argv) or 0)
    assert run(capsys, "service", "status")[0] == 0
    assert run(capsys, "service", "install", "--dry-run")[0] == 0
    assert got == [["status"], ["install", "--dry-run"]]


# --- PATH -------------------------------------------------------------------------------------

def test_path_commands(capsys, stopped, monkeypatch):
    from modules.cli import pathenv

    class Reg:
        value = r"C:\Windows;C:\Tools"

        def get(self):
            return self.value

        def set(self, v):
            self.value = v

        def notify(self):
            pass

    reg = Reg()
    monkeypatch.setattr(pathenv, "Registry", lambda: reg)
    code, out, _ = run(capsys, "path", "add")
    assert code == 0 and pathenv.app_dir().as_posix() and str(pathenv.app_dir()) in reg.value
    assert "добавлено" in out.lower()
    code, data, _ = run_json(capsys, "path", "show")
    assert data["data"]["in_path"] is True
    assert run(capsys, "path", "add")[1].lower().startswith("папка уже")
    code, out, _ = run(capsys, "path", "remove")
    assert code == 0 and str(pathenv.app_dir()) not in reg.value and r"C:\Tools" in reg.value


# --- журнал изменений ------------------------------------------------------------------------

def test_mutating_commands_are_logged(capsys, running):
    run(capsys, "winws", "start", "alt2")
    text = commands.CHANGES_LOG.read_text(encoding="utf-8")
    assert "cli" in text and "winws start alt2" in text and "ok" in text


def test_failed_command_is_logged_as_error(capsys, running):
    api, _ = running
    api.fail["winws_start"] = "нет прав"
    run(capsys, "winws", "start", "alt2")
    assert "error" in commands.CHANGES_LOG.read_text(encoding="utf-8")


def test_read_only_commands_are_not_logged(capsys, running):
    run(capsys, "status")
    run(capsys, "winws", "state")
    assert not commands.CHANGES_LOG.exists()


def test_secrets_are_not_written_to_the_log(capsys, running):
    run(capsys, "proxy", "link", "vless://secret-uuid@host:1")
    run(capsys, "tg", "config", "--secret", "0123456789abcdef0123456789abcdef")
    run(capsys, "tg", "advanced", "fake_tls_domain=example.com")
    text = commands.CHANGES_LOG.read_text(encoding="utf-8")
    assert "secret-uuid" not in text and "0123456789abcdef" not in text and "example.com" not in text
    assert "proxy link" in text and "tg config" in text


# --- автонастройка -----------------------------------------------------------------------------

def _fix_session(phase="done"):
    report = {"fixes": {"youtube": {"kind": "strategy", "id": "alt"}}, "offline": False, "services": [
        {"name": "youtube", "after": {"ok": True}, "fix": {"kind": "strategy", "id": "alt"}},
        {"name": "openai", "after": {"ok": False, "reasons": ["geo"]}, "fix": None, "hint": "need_proxy"},
    ]}
    return {"phase": phase, "report": report}


def test_fix_without_arguments_runs_fast_mode_for_everything_and_waits(capsys, running, monkeypatch):
    api, _ = running
    monkeypatch.setattr(commands, "FIX_POLL", 0)
    api.extra["autotune_start"] = {"active": {"phase": "running", "current": {"step": "strategy", "candidate": "alt",
                                                                             "index": 1, "total": 23}}}
    api.extra["autotune_state"] = {"active": _fix_session()}
    code, out, _ = run(capsys, "fix")
    assert api.called("autotune_start") == [[None, "fast"]]
    assert "Пробую стратегию alt — 2 из 23" in out
    assert "youtube: открывается — стратегия alt" in out and "нужен прокси" in out
    assert code == 1   # openai так и не открылся


def test_fix_for_chosen_services_in_smart_mode(capsys, running, monkeypatch):
    api, _ = running
    api.extra["autotune_start"] = {"active": {"phase": "done", "report": {"fixes": {}, "services": [
        {"name": "youtube", "after": {"ok": True}, "fix": None}]}}}
    code, data, _ = run_json(capsys, "fix", "youtube", "--smart")
    assert api.called("autotune_start") == [[["youtube"], "smart"]] and code == 0
    assert data["data"]["active"]["phase"] == "done"


def test_fix_check_names_the_reason_and_changes_nothing(capsys, running):
    api, _ = running
    api.extra["autotune_diagnose"] = {"offline": False, "services": [
        {"name": "youtube", "ok": False, "reasons": ["dpi"], "covered": 1, "total": 3},
        {"name": "discord", "ok": True}]}
    code, out, _ = run(capsys, "fix", "check")
    assert api.called("autotune_diagnose") == [[None]] and api.called("autotune_start") == []
    assert "youtube: не открывается (блокировка DPI), открылось адресов: 1 из 3" in out
    assert "discord: открывается" in out and code == 1


def test_fix_cancel_revert_and_keep_reach_the_app(capsys, running):
    api, _ = running
    for action, method in (("cancel", "autotune_cancel"), ("revert", "autotune_revert"), ("keep", "autotune_keep")):
        assert run(capsys, "fix", action)[0] == 0
        assert api.called(method) == [[]]
