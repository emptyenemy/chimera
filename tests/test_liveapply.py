"""modules/liveapply.py — применение изменённых списков без Api: им пользуются и окно, и служба."""

from modules import liveapply


class Mod:
    def __init__(self, lists=(), assignments=None, fail=None):
        self.config = {"lists": list(lists)}
        self._assignments = assignments or {}
        self.fail = fail
        self.calls = []

    def _do(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            raise RuntimeError(self.fail)

    def refresh_user_lists(self): self._do("refresh")
    def reload_lists(self): self._do("reload")
    def resync(self): self._do("resync")
    def assignments(self): return self._assignments
    def set_assignments(self, mapping): self._do("set_assignments", mapping)

    def set_lists(self, names):
        self.config["lists"] = list(names)
        self._do("set_lists", list(names))


def mods(**kw):
    return (Mod(lists=["discord"]), Mod(lists=["discord"]), Mod(assignments={"xbox": ["discord"]}))


def test_changed_applies_to_every_consumer_once_for_several_lists():
    winws, proxy, hosts = mods()

    errors = liveapply.lists_changed(["discord", "youtube"], winws, proxy, hosts)

    assert errors == []
    assert winws.calls == [("refresh",)] and proxy.calls == [("reload",)] and hosts.calls == [("resync",)]


def test_changed_skips_lists_nobody_uses():
    winws, proxy, hosts = mods()

    assert liveapply.lists_changed(["other"], winws, proxy, hosts) == []
    assert winws.calls == proxy.calls == hosts.calls == []


def test_changed_ignores_static_hosts_assignment():
    winws, proxy, hosts = mods()
    hosts._assignments = {"comss": True}

    liveapply.lists_changed(["discord"], winws, proxy, hosts)

    assert hosts.calls == []


def test_changed_collects_errors_and_keeps_going():
    winws, proxy, hosts = mods()
    hosts.fail = "нет прав"

    errors = liveapply.lists_changed(["discord"], winws, proxy, hosts)

    assert errors == [{"module": "hosts", "error": "нет прав"}]
    assert winws.calls and proxy.calls


def test_consumers_names_modules_that_use_the_lists():
    winws, proxy, hosts = mods()
    proxy.config["lists"] = []

    assert liveapply.consumers(["discord"], winws, proxy, hosts) == ["winws", "hosts"]
    assert liveapply.consumers(["other"], winws, proxy, hosts) == []


def test_removed_reinstalls_lists_without_the_file():
    winws, proxy, hosts = mods()
    hosts._assignments = {"xbox": ["discord", "youtube"], "comss": ["discord"], "static": True}

    errors = liveapply.lists_removed("discord", winws, proxy, hosts)

    assert errors == []
    assert proxy.calls == [("set_lists", ["discord"])]  # set_lists сам сверит имена с файлами
    assert winws.calls == [("set_lists", ["discord"])]
    assert hosts.calls == [("set_assignments", {"xbox": ["youtube"], "static": True})]


def test_removed_of_unused_list_does_nothing():
    winws, proxy, hosts = mods()

    assert liveapply.lists_removed("other", winws, proxy, hosts) == []
    assert winws.calls == proxy.calls == hosts.calls == []


def test_consumers_and_removal_ignore_case():
    winws, proxy, hosts = Mod(lists=["YouTube"]), Mod(), Mod(assignments={"xbox": ["YOUTUBE"]})

    assert liveapply.consumers(["youtube"], winws, proxy, hosts) == ["winws", "hosts"]
    liveapply.lists_removed("youtube", winws, proxy, hosts)
    assert hosts.calls == [("set_assignments", {})]


def test_apply_event_routes_by_kind():
    winws, proxy, hosts = mods()

    liveapply.apply_event("changed", "discord", winws, proxy, hosts)
    liveapply.apply_event("created", "discord", winws, proxy, hosts)
    assert len(winws.calls) == 2

    liveapply.apply_event("removed", "discord", winws, proxy, hosts)
    assert winws.calls[-1][0] == "set_lists"
