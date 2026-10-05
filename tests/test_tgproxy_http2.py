"""HTTP/2 integration: persisted settings, portable config and the real upstream lifecycle.

The upstream listener, domain refresh and warmup are replaced at the network boundary.
"""

import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from modules import configbackups, shareconfig
from modules.tgproxy import manager
from ui import api as api_mod
from ui.shareops import ShareOps


@pytest.fixture
def tg(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "STATE_PATH", tmp_path / "tgproxy.json")
    return manager.TgProxy()


def test_http2_setting_roundtrips_and_updates_core(tg):
    core = manager._import_core()
    from proxy.config import ProxyConfig

    for enabled in (False, True):
        result = tg.set_advanced({"cfproxy_h2_media": enabled})
        assert result["cfproxy_h2_media"] is enabled
        reloaded = manager.TgProxy()
        assert reloaded.config["cfproxy_h2_media"] is enabled
        pc = ProxyConfig()
        reloaded._apply_config(SimpleNamespace(proxy_config=pc))
        assert pc.cfproxy_h2_media is enabled
        assert pc.h2_enabled is enabled
        assert pc.pool_size > 0 and pc.dc_redirects == {2: "149.154.167.220", 4: "149.154.167.220"}
    assert core.__version__ == "1.11.0"


@pytest.mark.parametrize("option", ["fallback_cfproxy", "disable_secure", "force_test_dc"])
def test_http2_follows_upstream_compatibility_flags(tg, option):
    manager._import_core()
    from proxy.config import ProxyConfig

    pc = ProxyConfig()
    assert tg.config["cfproxy_h2_media"] is True
    tg.set_advanced({option: option != "fallback_cfproxy"})
    tg._apply_config(SimpleNamespace(proxy_config=pc))
    assert pc.cfproxy_h2_media is True and pc.h2_enabled is False


def test_http2_survives_portable_export_import_and_backup_normalize(tg):
    tg.set_advanced({"cfproxy_h2_media": False})
    api = api_mod.Api.__new__(api_mod.Api)
    api.tg = tg
    api.winws = SimpleNamespace(config={}, strategies=lambda: [])
    api.proxy = SimpleNamespace(config={})
    api.hosts = SimpleNamespace(assignments=lambda: {}, providers=lambda: [])
    from unittest.mock import patch
    with patch("ui.shareops.domains.available_lists", return_value=[]), patch("ui.shareops.dns_providers.load_all", return_value=[]):
        snapshot = ShareOps(api).snapshot()
    exported = shareconfig.build_export(snapshot, ["telegram"], "1.0.4")
    assert exported["sections"]["telegram"]["advanced"]["cfproxy_h2_media"] is False
    parsed = shareconfig.parse(json.dumps(exported))
    assert not parsed["invalid"] and not parsed["unknown_fields"]
    assert parsed["doc"]["sections"]["telegram"]["advanced"]["cfproxy_h2_media"] is False
    assert configbackups.normalize("telegram", tg.config)["cfproxy_h2_media"] is False


@pytest.mark.parametrize("running,failed", [(False, False), (True, False), (True, True)])
def test_api_saves_http2_and_restarts_only_running_proxy(tg, monkeypatch, running, failed):
    monkeypatch.setattr(api_mod.configbackups, "automatic", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(type(tg), "running", property(lambda _self: running))
    restarted = Mock(side_effect=RuntimeError("Restart failed") if failed else None)
    monkeypatch.setattr(tg, "restart", restarted)
    api = api_mod.Api.__new__(api_mod.Api)
    api.tg = tg
    res = api.tg_set_advanced({"cfproxy_h2_media": False})
    assert res["ok"] is True and res["data"]["cfproxy_h2_media"] is False
    assert manager.TgProxy().config["cfproxy_h2_media"] is False
    assert restarted.call_count == int(running)
    assert bool(res["data"].get("apply_error")) is failed


def test_live_stats_include_http2_connections(tg, monkeypatch):
    manager._import_core()
    from proxy.stats import stats

    monkeypatch.setattr(stats, "connections_h2", 7)
    assert tg.live_stats()["h2"] == 7


def test_upstream_http2_pool_closes_between_event_loops(tg, monkeypatch):
    manager._import_core()
    from proxy import tg_ws_proxy as runner
    from proxy.config import ProxyConfig

    pc = ProxyConfig(secret="ab" * 16)
    tg._apply_config(SimpleNamespace(proxy_config=pc))
    monkeypatch.setattr(runner, "proxy_config", pc)
    monkeypatch.setattr(runner, "start_cfproxy_domain_refresh", lambda: None)
    monkeypatch.setattr(runner.ws_pool, "warmup", AsyncMock())
    monkeypatch.setattr(runner.cf_worker_pool, "warmup", AsyncMock())
    pools = []

    async def cycle():
        stop = asyncio.Event()

        async def serving():
            pools.append(runner.cf_h2_pool)
            stop.set()
            await asyncio.Event().wait()

        server = SimpleNamespace(sockets=[], close=Mock(), wait_closed=AsyncMock(), serve_forever=serving)
        monkeypatch.setattr(asyncio, "start_server", AsyncMock(return_value=server))
        await asyncio.wait_for(runner._run(stop_event=stop), 2)
        server.close.assert_called()
        assert runner.cf_h2_pool is None and runner._server_instance is None
        assert runner._server_stop_event is None

    for enabled in (True, False, True):
        pc.cfproxy_h2_media = enabled
        asyncio.run(cycle())
        assert (pools[-1] is not None) is enabled
        if enabled:
            assert pools[-1].closed is True
    assert pools[0] is not pools[2]
