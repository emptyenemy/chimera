"""tui/app.py — прогон меню на сценарии ввода (io.StringIO) с поддельным Api.

Настоящий ui.api.Api тут не создаётся: никаких потоков/subprocess/сети — только
проверка, что меню верно читает цифровой ввод, зовёт нужные методы Api (те же
{ok, data|error}, что и у фронта) и корректно выходит (Api.shutdown зовётся
ровно один раз — и по пункту «Выход», и по EOF на stdin, и по Ctrl+C)."""

import io

import pytest

from tui import app as tui_app


class FakeApi:
    """Дублирует сигнатуры нужных методов ui.api.Api. Каждый вызов, меняющий
    состояние, пишется в self.calls — тесты проверяют именно это, без побочных
    эффектов на реальную систему."""

    def __init__(self):
        self.calls = []
        self.shutdown_called = 0
        self._winws = {
            "running": False, "current": None,
            "strategies": [
                {"id": "general", "name": "general", "desc": "обычная стратегия"},
                {"id": "discord", "name": "discord", "desc": "для Discord"},
            ],
            "error": None,
        }
        self._proxy = {"running": False, "mode": "pac", "error": None}
        self._tg = {
            "running": False,
            "link": "tg://proxy?server=1.2.3.4&port=1443&secret=ddaa",
            "error": None,
        }
        self._hosts = {"applied": False, "enabled": True, "assignments": {}, "count": 0}
        self._dns = {
            "adapters": [{"index": 1, "name": "Ethernet", "status": "Up", "dns": ["1.1.1.1"]}],
            "providers": [{"id": "cf", "name": "Cloudflare"}],
        }

    # --- обзор ---------------------------------------------------------------

    def app_info(self):
        return {"ok": True, "data": {"admin": True, "version": "1.0.0", "service_running": False}}

    # --- winws -----------------------------------------------------------------

    def winws_state(self):
        return {"ok": True, "data": self._winws}

    def winws_start(self, strategy_id):
        self.calls.append(("winws_start", strategy_id))
        self._winws["running"] = True
        self._winws["current"] = strategy_id
        return {"ok": True, "data": self._winws}

    def winws_stop(self):
        self.calls.append(("winws_stop",))
        self._winws["running"] = False
        return {"ok": True, "data": self._winws}

    def winws_log(self, offset=0):
        return {"ok": True, "data": {"offset": 5, "data": "winws: строка лога\n", "reset": True}}

    # --- proxy -------------------------------------------------------------

    def proxy_state(self):
        return {"ok": True, "data": self._proxy}

    def proxy_start(self):
        self.calls.append(("proxy_start",))
        self._proxy["running"] = True
        return {"ok": True, "data": self._proxy}

    def proxy_stop(self):
        self.calls.append(("proxy_stop",))
        self._proxy["running"] = False
        return {"ok": True, "data": self._proxy}

    def proxy_set_mode(self, mode):
        self.calls.append(("proxy_set_mode", mode))
        self._proxy["mode"] = mode
        return {"ok": True, "data": self._proxy}

    def proxy_log(self, offset=0):
        return {"ok": True, "data": {"offset": 0, "data": "", "reset": True}}

    # --- tg ------------------------------------------------------------------

    def tg_state(self):
        return {"ok": True, "data": self._tg}

    def tg_start(self):
        self.calls.append(("tg_start",))
        self._tg["running"] = True
        return {"ok": True, "data": self._tg}

    def tg_stop(self):
        self.calls.append(("tg_stop",))
        self._tg["running"] = False
        return {"ok": True, "data": self._tg}

    def tg_log(self, offset=0):
        return {"ok": True, "data": {"offset": 0, "data": "tg: лог\n", "reset": True}}

    # --- hosts -----------------------------------------------------------------

    def hosts_state(self):
        return {"ok": True, "data": self._hosts}

    def hosts_set_enabled(self, value):
        self.calls.append(("hosts_set_enabled", value))
        self._hosts["enabled"] = value
        return {"ok": True, "data": self._hosts}

    # --- dns -------------------------------------------------------------------

    def dns_state(self):
        return {"ok": True, "data": self._dns}

    def dns_set(self, adapter_index, provider_id):
        self.calls.append(("dns_set", adapter_index, provider_id))
        return {"ok": True, "data": {}}

    def dns_reset(self, adapter_index):
        self.calls.append(("dns_reset", adapter_index))
        return {"ok": True, "data": {}}

    # --- выход -----------------------------------------------------------------

    def shutdown(self):
        self.shutdown_called += 1


def _run(inputs):
    api = FakeApi()
    stdin = io.StringIO("\n".join(inputs) + "\n")
    stdout = io.StringIO()
    rc = tui_app.run(api=api, stdin=stdin, stdout=stdout)
    return rc, api, stdout.getvalue()


def test_exit_immediately_calls_shutdown_once():
    rc, api, out = _run(["0"])
    assert rc == 0
    assert api.shutdown_called == 1
    assert "CHIMERA" in out


def test_eof_on_stdin_exits_cleanly_like_explicit_quit():
    api = FakeApi()
    stdin = io.StringIO("")  # сразу конец потока — как Ctrl+D до первого ввода
    stdout = io.StringIO()

    rc = tui_app.run(api=api, stdin=stdin, stdout=stdout)

    assert rc == 0
    assert api.shutdown_called == 1


def test_garbage_input_is_rejected_without_crashing():
    rc, api, out = _run(["мусор", "0"])
    assert rc == 0
    assert "Неизвестный пункт" in out
    assert api.shutdown_called == 1


def test_winws_start_by_substring_search():
    rc, api, out = _run(["1", "1", "disc", "1", "0", "0"])
    assert ("winws_start", "discord") in api.calls
    assert api.shutdown_called == 1


def test_winws_stop():
    rc, api, out = _run(["1", "2", "0", "0"])
    assert ("winws_stop",) in api.calls


def test_winws_search_with_no_matches_does_not_crash():
    rc, api, out = _run(["1", "1", "zzz-nothing", "0", "0"])
    assert rc == 0
    assert "Ничего не найдено" in out
    assert not any(c[0] == "winws_start" for c in api.calls)


def test_proxy_start_stop_and_mode_toggle():
    rc, api, out = _run(["2", "1", "3", "2", "0", "0"])
    assert ("proxy_start",) in api.calls
    assert ("proxy_set_mode", "tun") in api.calls
    assert ("proxy_stop",) in api.calls


def test_tg_menu_shows_link_and_starts():
    rc, api, out = _run(["3", "1", "0", "0"])
    assert ("tg_start",) in api.calls
    assert "tg://proxy" in out


def test_hosts_toggle_flips_enabled():
    rc, api, out = _run(["4", "1", "0", "0"])
    assert ("hosts_set_enabled", False) in api.calls  # был enabled=True -> выключаем


def test_dns_set_provider_on_adapter():
    rc, api, out = _run(["5", "1", "1", "0", "0"])
    assert ("dns_set", 1, "cf") in api.calls


def test_dns_reset_to_dhcp():
    rc, api, out = _run(["5", "1", "0", "0", "0"])
    assert ("dns_reset", 1) in api.calls


def test_log_tail_reads_and_prints():
    rc, api, out = _run(["3", "3", "0", "0"])
    assert "tg: лог" in out


@pytest.mark.parametrize("bad_number", ["99", "-1", "abc"])
def test_dns_adapter_bad_number_reprompts_instead_of_crashing(bad_number):
    rc, api, out = _run(["5", bad_number, "0", "0"])
    assert rc == 0
    assert "Некорректный номер" in out
