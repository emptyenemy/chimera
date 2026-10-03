"""modules/hosts/background.py — единый фоновый поток (автообновление, чекер,
автопереключение), прогоняемый строго синхронно через run_once(now=...):
никакого sleep/потока в тестах, время и резолвер/чекер/проба провайдера — свои,
без сети. Использует настоящий HostsManager с временными hosts/state.json, как
tests/test_hosts_manager.py."""

import pytest

from modules.hosts import background as hosts_background
from modules.hosts import manager as hosts_manager
from modules.hosts.background import DEFAULT_OPTIONS, HostsBackground
from modules.hosts.manager import HostsManager


@pytest.fixture
def hm(tmp_path, monkeypatch):
    hosts_path = tmp_path / "hosts"
    hosts_path.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(hosts_manager.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(hosts_manager, "is_admin", lambda: True)
    return HostsManager(state_path=state_path, hosts_path=hosts_path)


def _seed_dns_assignment(hm, monkeypatch, provider_id="xbox", ip="9.9.9.9"):
    """Применяет одну dns-привязку без сети — как в test_hosts_manager.py."""
    monkeypatch.setattr(
        hosts_manager, "resolve_domains",
        lambda domains_, doh, servers: [{"ip": ip, "host": d} for d in domains_],
    )
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid.upper(),
                                                         "type": "dns", "doh": None, "servers": []})
    # manager.py и background.py импортируют split_lists каждый в свою область
    # видимости — патчим обе, иначе background._refresh() резолвит настоящий
    # список lists/discord.txt вместо тестового "example.com".
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["example.com"], []))
    monkeypatch.setattr(hosts_background, "split_lists", lambda names: (["example.com"], []))
    hm.set_assignments({provider_id: ["discord"]})


# --- расписание: refresh/check тикают по своим интервалам --------------------


def test_run_once_does_nothing_before_any_interval_elapsed():
    calls = []
    stub_manager = type("M", (), {"background_options": staticmethod(lambda: DEFAULT_OPTIONS)})()
    bg = HostsBackground(stub_manager)
    bg._refresh = lambda: calls.append("refresh")
    bg._do_check = lambda opts: calls.append("check")
    bg.run_once(now=0.0)
    # _last_refresh/_last_check стартуют с 0.0, а now=0.0 -> прошло 0 секунд, меньше
    # любого интервала по умолчанию — на первом тике при таком now ничего не срабатывает.
    assert calls == []


def test_refresh_writes_new_ip_when_it_changed(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch, ip="9.9.9.9")
    assert "9.9.9.9 example.com" in hm._read_hosts()

    # провайдер отдаёт новый IP — на следующем тике refresh должен переписать блок
    monkeypatch.setattr(hosts_manager, "resolve_domains",
                        lambda domains_, doh, servers: [{"ip": "8.8.8.8", "host": d} for d in domains_])
    bg = HostsBackground(hm, resolve_fn=lambda d, doh, s: [{"ip": "8.8.8.8", "host": x} for x in d])
    bg._refresh()
    assert "8.8.8.8 example.com" in hm._read_hosts()
    assert "9.9.9.9 example.com" not in hm._read_hosts()


def test_refresh_is_noop_when_ip_unchanged(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch, ip="9.9.9.9")
    text_before = hm._read_hosts()

    calls = []
    real_sync = hm._sync

    def spy_sync(**kwargs):
        calls.append(1)
        return real_sync(**kwargs)

    monkeypatch.setattr(hm, "_sync", spy_sync)
    bg = HostsBackground(hm, resolve_fn=lambda d, doh, s: [{"ip": "9.9.9.9", "host": x} for x in d])
    bg._refresh()
    assert calls == []  # IP не поменялся — _sync не звался, лишней записи в hosts не было
    assert hm._read_hosts() == text_before


def test_refresh_skips_static_providers(hm, monkeypatch):
    """static-провайдер обновляется вместе с сабмодулем сам — refresh не должен его трогать."""
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid, "type": "static"})
    hm._save_state({"assignments": {"flowseal-hosts": True}, "entries": [], "enabled": True})

    def boom(*a, **kw):
        raise AssertionError("resolve не должен звать static-провайдер")

    bg = HostsBackground(hm, resolve_fn=boom)
    bg._refresh()  # не должно упасть


def test_refresh_disabled_by_option_via_run_once(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch, ip="9.9.9.9")
    hm.set_background({"refresh_enabled": False})
    called = []
    bg = HostsBackground(hm)
    bg._refresh = lambda: called.append(1)
    bg._do_check = lambda opts: None
    bg.run_once(now=10 ** 9)  # интервал заведомо истёк
    assert called == []


# --- чекер: health по провайдерам ---------------------------------------------


def test_do_check_computes_ratio_per_provider(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch, provider_id="xbox", ip="9.9.9.9")

    def fake_check(host):
        return host == "example.com"  # единственная запись — считаем живой

    bg = HostsBackground(hm, check_fn=fake_check)
    bg._do_check(hm.background_options())

    st = hm._load_state()
    health = st["health"]
    assert health["total"] == 1
    assert health["alive"] == 1
    assert health["ratio"] == 1.0
    assert health["providers"]["xbox"] == {"alive": 1, "total": 1, "ratio": 1.0}


def test_do_check_no_entries_is_noop(hm):
    bg = HostsBackground(hm, check_fn=lambda host: True)
    bg._do_check(hm.background_options())
    assert hm._load_state().get("health") is None


def test_hosts_state_exposes_health(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch)
    bg = HostsBackground(hm, check_fn=lambda host: True)
    bg._do_check(hm.background_options())
    assert hm.state()["health"]["ratio"] == 1.0


# --- автопереключение ---------------------------------------------------------


def test_autoswitch_after_two_consecutive_degraded_checks(hm, monkeypatch):
    monkeypatch.setattr(
        hosts_manager, "resolve_domains",
        lambda domains_, doh, servers: [{"ip": "9.9.9.9", "host": d} for d in domains_],
    )
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["a", "b"], []))
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid.upper(),
                                                         "type": "dns", "doh": None, "servers": []})
    hm.set_assignments({"xbox": ["discord"]})

    hm.set_background({"autoswitch_enabled": True, "provider_order": ["xbox", "comss", "malw"]})

    bg = HostsBackground(hm, check_fn=lambda host: False,  # всё мертво -> ratio 0.0 < 0.5
                         probe_fn=lambda pid: pid == "comss")
    opts = hm.background_options()

    bg._do_check(opts)  # деградация №1 — переключения ещё нет
    assert hm.assignments() == {"xbox": ["discord"]}

    bg._do_check(opts)  # деградация №2 подряд — переключаемся
    assert hm.assignments() == {"comss": ["discord"]}

    st = hm._load_state()
    assert st["last_switch"]["from"] == "xbox"
    assert st["last_switch"]["to"] == "comss"
    assert st["switch_log"][-1] == st["last_switch"]


def test_autoswitch_disabled_by_default(hm, monkeypatch):
    monkeypatch.setattr(
        hosts_manager, "resolve_domains",
        lambda domains_, doh, servers: [{"ip": "9.9.9.9", "host": d} for d in domains_],
    )
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["a"], []))
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid.upper(),
                                                         "type": "dns", "doh": None, "servers": []})
    hm.set_assignments({"xbox": ["discord"]})
    hm.set_background({"provider_order": ["xbox", "comss"]})  # autoswitch_enabled остаётся False

    bg = HostsBackground(hm, check_fn=lambda host: False, probe_fn=lambda pid: True)
    opts = hm.background_options()
    bg._do_check(opts)
    bg._do_check(opts)
    assert hm.assignments() == {"xbox": ["discord"]}  # без переключения


def test_autoswitch_recovers_streak_when_healthy_again(hm, monkeypatch):
    monkeypatch.setattr(
        hosts_manager, "resolve_domains",
        lambda domains_, doh, servers: [{"ip": "9.9.9.9", "host": d} for d in domains_],
    )
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["a"], []))
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid.upper(),
                                                         "type": "dns", "doh": None, "servers": []})
    hm.set_assignments({"xbox": ["discord"]})
    hm.set_background({"autoswitch_enabled": True, "provider_order": ["xbox", "comss"]})

    alive = {"value": False}
    bg = HostsBackground(hm, check_fn=lambda host: alive["value"], probe_fn=lambda pid: True)
    opts = hm.background_options()

    bg._do_check(opts)  # деградация №1
    alive["value"] = True
    bg._do_check(opts)  # ожил — счётчик сбрасывается
    alive["value"] = False
    bg._do_check(opts)  # деградация №1 (заново, не №3) — переключения ещё нет
    assert hm.assignments() == {"xbox": ["discord"]}


def test_autoswitch_skips_static_providers(hm, monkeypatch):
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid, "type": "static"})
    hm._save_state({"assignments": {"flowseal-hosts": True},
                    "entries": [{"ip": "1.1.1.1", "host": "x", "provider": "flowseal-hosts"}],
                    "enabled": True})
    hm.set_background({"autoswitch_enabled": True, "provider_order": ["flowseal-hosts"]})

    bg = HostsBackground(hm, check_fn=lambda host: False, probe_fn=lambda pid: True)
    opts = hm.background_options()
    bg._do_check(opts)
    bg._do_check(opts)
    assert hm.assignments() == {"flowseal-hosts": True}  # не переключаем static


def test_next_alive_provider_skips_dead_and_wraps_order():
    bg = HostsBackground(manager=object())
    bg.probe_fn = lambda pid: pid == "malw"
    assert bg._next_alive_provider("xbox", ["xbox", "comss", "malw"]) == "malw"


def test_next_alive_provider_returns_none_when_all_dead():
    bg = HostsBackground(manager=object())
    bg.probe_fn = lambda pid: False
    assert bg._next_alive_provider("xbox", ["xbox", "comss"]) is None


# --- запуск/остановка потока ---------------------------------------------------


def test_start_stop_background_thread(hm):
    hm.background.tick_interval = 0.01
    hm.start_background()
    assert hm.background._thread is not None
    hm.stop_background()
    assert not hm.background._thread.is_alive() if hm.background._thread else True


def test_checker_network_runs_outside_mutation_gate_and_discards_stale_result(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch)
    lock_held = []

    class Gate:
        def __enter__(self):
            lock_held.append(True)
        def __exit__(self, *args):
            lock_held.pop()

    def check(host):
        assert not lock_held
        hm.set_background({"check_enabled": False})
        return False

    bg = HostsBackground(hm, check_fn=check)
    bg.mutation_lock = Gate()
    bg._do_check(hm.background_options())
    assert hm._load_state().get("health") is None


def test_background_refresh_discards_result_after_foreground_changes_settings(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch)
    lock_held = []

    class Gate:
        def __enter__(self):
            lock_held.append(True)
        def __exit__(self, *args):
            lock_held.pop()

    def resolve(domains, doh, servers):
        assert not lock_held
        hm.set_enabled(False)
        return [{"host": host, "ip": "8.8.8.8"} for host in domains]

    bg = HostsBackground(hm, resolve_fn=resolve)
    bg.mutation_lock = Gate()
    bg._refresh()
    assert not hm.state()["enabled"]
    assert "example.com" not in hm._read_hosts()


@pytest.mark.parametrize("key", ["refresh_interval", "check_interval"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "15", None, [], {}])
def test_background_rejects_invalid_interval_without_saving(hm, key, value):
    hm.set_background({"refresh_interval": 7200, "check_interval": 120})
    before = hm.state_path.read_bytes()
    with pytest.raises(ValueError):
        hm.set_background({"refresh_enabled": False, key: value})
    assert hm.state_path.read_bytes() == before


@pytest.mark.parametrize("key", ["refresh_enabled", "check_enabled", "autoswitch_enabled"])
@pytest.mark.parametrize("value", [0, 1, "false", None, []])
def test_background_rejects_non_boolean_flags(hm, key, value):
    with pytest.raises(ValueError):
        hm.set_background({key: value})
    assert not hm.state_path.exists()


@pytest.mark.parametrize("options", [[], "bad", 15])
def test_background_rejects_non_object_options(hm, options):
    with pytest.raises(ValueError):
        hm.set_background(options)


def test_background_recovers_malformed_saved_options_without_rewriting(hm):
    hm._save_state({"background": {"refresh_interval": -1, "check_interval": "invalid",
                                    "autoswitch_enabled": "false", "provider_order": 123,
                                    "refresh_enabled": False}})
    before = hm.state_path.read_bytes()
    assert hm.background_options() == {**DEFAULT_OPTIONS, "refresh_enabled": False}
    hm.background.run_once(now=0)
    assert hm.state_path.read_bytes() == before


def test_cancelled_checker_does_not_publish_health(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch)
    bg = hm.background

    def check(host):
        bg.stop()
        return True

    bg.check_fn = check
    bg._do_check(hm.background_options())
    assert hm._load_state().get("health") is None


def test_cancelled_refresh_does_not_apply_hosts(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch)
    before = hm.hosts_path.read_bytes()
    bg = hm.background

    def resolve(domains, doh, servers):
        bg.stop()
        return [{"host": host, "ip": "8.8.8.8"} for host in domains]

    bg.resolve_fn = resolve
    monkeypatch.setattr(hosts_manager, "resolve_domains",
                        lambda domains_, doh, servers: [{"host": host, "ip": "8.8.8.8"} for host in domains_])
    bg._refresh()
    assert hm.hosts_path.read_bytes() == before


def test_restart_waits_for_cancelled_worker_without_overlapping_ticks(hm, monkeypatch):
    import threading
    bg = hm.background
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    calls = []
    active = []
    max_active = []

    def tick():
        index = len(calls)
        calls.append(threading.current_thread())
        active.append(True)
        max_active.append(len(active))
        entered[index].set()
        assert release[index].wait(3)
        active.pop()

    bg.run_once = tick
    bg.start()
    first = bg._thread
    original_join = first.join
    try:
        assert entered[0].wait(1)
        monkeypatch.setattr(first, "join", lambda timeout=None: None)
        bg.stop()
        assert bg._thread is first
        bg.start()
        bg.start()
        assert bg._stop.is_set()
        assert calls == [first]
        release[0].set()
        assert entered[1].wait(1)
        assert calls[1] is not first
        assert max(max_active) == 1
        assert bg._thread is calls[1]
    finally:
        release[0].set()
        release[1].set()
        bg.stop()
        original_join(timeout=1)


def test_stop_cancels_requested_restart(hm, monkeypatch):
    import threading
    bg = hm.background
    entered, release = threading.Event(), threading.Event()
    calls = []

    def tick():
        calls.append(True)
        entered.set()
        assert release.wait(3)

    bg.run_once = tick
    bg.start()
    first = bg._thread
    original_join = first.join
    try:
        assert entered.wait(1)
        monkeypatch.setattr(first, "join", lambda timeout=None: None)
        bg.stop()
        bg.start()
        bg.stop()
        release.set()
        original_join(timeout=1)
        assert not first.is_alive()
        assert bg._thread is None
        assert calls == [True]
    finally:
        release.set()
        bg.stop()
        original_join(timeout=1)


@pytest.mark.parametrize("value", [123, [None], [15], [""], ["bad id"], ["x" * 65], "xbox"])
def test_background_rejects_invalid_provider_order(hm, value):
    with pytest.raises(ValueError):
        hm.set_background({"provider_order": value})


def test_background_defaults_do_not_share_mutable_provider_order(hm):
    options = hm.background_options()
    options["provider_order"].append("xbox")
    assert hm.background_options()["provider_order"] == []
    assert DEFAULT_OPTIONS["provider_order"] == []


@pytest.mark.parametrize("saved", [None, [], "bad", 15, True])
def test_non_object_hosts_state_uses_defaults_without_rewriting(hm, saved):
    import json
    hm.state_path.write_text(json.dumps(saved), encoding="utf-8")
    before = hm.state_path.read_bytes()
    assert hm.background_options() == DEFAULT_OPTIONS
    assert hm.state()["assignments"] == {}
    assert hm.state_path.read_bytes() == before


def test_cancelled_provider_probe_does_not_switch_assignment(hm, monkeypatch):
    _seed_dns_assignment(hm, monkeypatch)
    hm.set_background({"autoswitch_enabled": True, "provider_order": ["xbox", "comss"]})
    before = hm.state_path.read_bytes()
    bg = hm.background
    bg._degraded_streak["xbox"] = 1

    def probe(provider):
        bg.stop()
        return True

    bg.probe_fn = probe
    bg._maybe_autoswitch(hm.background_options(), {"xbox": {"total": 1, "alive": 0, "ratio": 0.0}})
    assert hm.state_path.read_bytes() == before
    assert hm.assignments() == {"xbox": ["discord"]}
