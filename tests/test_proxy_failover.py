"""Переключение сервера подписки при отказе: только свой прокси, только после двух неудач."""

import pytest

from modules.proxy import failover as failover_mod
from modules.proxy import subscription
from modules.proxy.failover import ProxyFailover

A = "vless://11111111-1111-1111-1111-111111111111@a.example:443?security=tls#A"
B = "vless://22222222-2222-2222-2222-222222222222@b.example:443?security=tls#B"
C = "trojan://p@c.example:443#C"
Q = "hysteria2://p@q.example:8443#Q"


class Proxy:
    def __init__(self, servers, link, ours=True):
        self.config = {"servers": list(servers), "link": link}
        self._ours_alive = ours
        self.last_switch = None
        self.selected = []

    def select_server(self, index):
        self.selected.append(index)
        self.config["link"] = self.config["servers"][index]


@pytest.fixture
def net(monkeypatch):
    alive = {A: 50, B: 30, C: 80, Q: None}
    monkeypatch.setattr(subscription, "ping", lambda link, **kw: alive.get(link))
    monkeypatch.setattr(subscription, "ping_all", lambda servers, ping_fn=None: [alive.get(s) for s in servers])
    monkeypatch.setattr(failover_mod.applog, "write", lambda text: None)
    return alive


def test_a_dead_server_is_replaced_after_two_failed_checks(net):
    proxy = Proxy([A, B, C], A)
    fo = ProxyFailover(proxy, now=lambda: 1000)
    net[A] = None
    assert fo.run_once() == {"ok": False, "fails": 1} and proxy.selected == []   # одна неудача — не повод
    result = fo.run_once()
    assert result["switched"] and proxy.config["link"] == B and proxy.selected == [1]
    assert proxy.last_switch == {"from": "A", "to": "B", "at": 1000}


def test_a_server_that_answers_again_resets_the_count(net):
    proxy = Proxy([A, B], A)
    fo = ProxyFailover(proxy)
    net[A] = None
    fo.run_once()
    net[A] = 50
    assert fo.run_once() == {"ok": True}
    net[A] = None
    assert fo.run_once()["fails"] == 1 and proxy.selected == []


def test_nothing_happens_when_no_other_server_answers(net):
    proxy = Proxy([A, B], A)
    fo = ProxyFailover(proxy)
    net[A] = net[B] = None
    fo.run_once()
    assert fo.run_once() == {"ok": False, "fails": 2, "switched": False} and proxy.config["link"] == A


@pytest.mark.parametrize("proxy", [Proxy([A], A), Proxy([A, B], A, ours=False), Proxy([A, B], C)])
def test_only_our_running_proxy_with_a_real_choice_is_watched(net, proxy):
    net[A] = None
    fo = ProxyFailover(proxy)
    assert fo.run_once() is None and fo.run_once() is None and proxy.selected == []


def test_quic_servers_are_not_judged_by_tcp(net):
    proxy = Proxy([Q, A], Q)
    fo = ProxyFailover(proxy)
    assert fo.run_once() is None and fo.run_once() is None and proxy.selected == []


def test_choosing_another_server_by_hand_starts_the_count_over(net):
    proxy = Proxy([A, B, C], A)
    fo = ProxyFailover(proxy)
    net[A] = None
    fo.run_once()
    proxy.config["link"] = C          # пользователь сам выбрал другой
    net[C] = None
    assert fo.run_once()["fails"] == 1 and proxy.selected == []


def test_a_server_that_answers_in_the_full_sweep_is_kept(net, monkeypatch):
    proxy = Proxy([A, B], A)
    fo = ProxyFailover(proxy)
    monkeypatch.setattr(subscription, "ping", lambda link, **kw: None)   # одиночные проверки не прошли
    fo.run_once()
    assert fo.run_once() == {"ok": True} and proxy.selected == [] and fo.fails == 0
