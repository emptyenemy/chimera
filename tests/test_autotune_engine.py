"""Движок автонастройки на модели сети: что пробуется, в каком порядке и что выбирается."""

import threading

import pytest

from modules.autotune.engine import Cancelled, Engine
from tests.autotune_net import FakeOps, blocked_unless, opens

YT = {"youtube": ["youtube.com", "i.ytimg.com"]}


def strategy_in(*ids):
    return lambda state: state["strategy"] in ids


def run(ops, services=None, **kwargs):
    return Engine(ops, **kwargs).run(services or list(ops.targets_map))


def row(report, name):
    return next(r for r in report["services"] if r["name"] == name)


def test_nothing_is_changed_when_everything_opens():
    ops = FakeOps(YT, {"youtube.com": opens(), "i.ytimg.com": opens()})
    report = run(ops)
    assert ops.calls == [] and report["steps"] == [] and row(report, "youtube")["fix"] is None


def test_fast_mode_takes_the_first_strategy_that_opens_everything():
    fix = strategy_in("alt", "alt2")
    ops = FakeOps(YT, {"youtube.com": blocked_unless(fix), "i.ytimg.com": blocked_unless(fix)})
    report = run(ops)
    assert ops.applied("apply_strategy") == ["general", "alt", "alt"]   # перебор и итоговое применение
    assert ops.state["strategy"] == "alt" and ops.state["winws_lists"] == ["youtube"]
    assert row(report, "youtube")["fix"] == {"kind": "strategy", "id": "alt"}
    assert row(report, "youtube")["after"]["ok"] is True


def test_smart_mode_compares_every_strategy_and_takes_the_fastest():
    ms = lambda state: {"alt": 120, "alt2": 40}.get(state["strategy"], 0)  # noqa: E731
    fix = strategy_in("alt", "alt2")
    ops = FakeOps(YT, {"youtube.com": blocked_unless(fix, ms), "i.ytimg.com": blocked_unless(fix, ms)})
    report = run(ops, mode="smart")
    assert ops.applied("apply_strategy")[:3] == ["general", "alt", "alt2"]
    assert ops.state["strategy"] == "alt2" and row(report, "youtube")["fix"]["id"] == "alt2"


def test_variant_remembered_for_this_network_is_tried_first():
    fix = strategy_in("alt2")
    ops = FakeOps(YT, {"youtube.com": blocked_unless(fix), "i.ytimg.com": blocked_unless(fix)})
    run(ops, memory={"youtube": {"kind": "strategy", "id": "alt2"}})
    assert ops.applied("apply_strategy") == ["alt2", "alt2"]


def test_strategy_that_breaks_a_working_service_is_rejected():
    targets = {"youtube": ["youtube.com"], "discord": ["discord.com"]}
    ops = FakeOps(targets, {
        "youtube.com": blocked_unless(strategy_in("alt", "alt2")),
        "discord.com": blocked_unless(lambda s: s["strategy"] != "alt"),   # alt ломает discord
    })
    report = run(ops)
    assert ops.state["strategy"] == "alt2"
    assert row(report, "discord")["after"]["ok"] and row(report, "youtube")["after"]["ok"]
    rejected = [e for e in report.get("steps", []) if e.get("step") == "strategy"]
    assert rejected[0]["chosen"] == "alt2"


def test_variant_that_loses_a_control_site_is_rejected():
    targets = {"openai": ["chatgpt.com"]}
    ops = FakeOps(targets, {"chatgpt.com": blocked_unless(lambda s: s["dns"] in ("comss-dns", "bad"), status="denied")},
                  dns_unblock=("bad", "comss-dns"), hosts=(),
                  canary={"ya.ru": blocked_unless(lambda s: s["dns"] != "bad")})
    report = run(ops)
    assert ops.state["dns"] == "comss-dns" and row(report, "openai")["fix"] == {"kind": "dns", "id": "comss-dns"}


def test_geo_block_skips_strategies_and_is_fixed_by_hosts():
    targets = {"openai": ["chatgpt.com", "api.openai.com"]}
    fix = lambda s: s["hosts"].get("openai") == "comss"  # noqa: E731
    ops = FakeOps(targets, {"chatgpt.com": blocked_unless(fix, status="denied"),
                            "api.openai.com": blocked_unless(fix, status="denied")})
    report = run(ops)
    assert ops.applied("apply_strategy") == [] and report["steps"][0] == {"step": "strategy", "skipped": "not_needed"}
    assert ops.state["hosts"] == {"openai": "comss"} and row(report, "openai")["fix"] == {"kind": "hosts", "id": "comss"}


def test_hosts_that_did_not_help_return_the_original_provider():
    targets = {"openai": ["chatgpt.com"]}
    ops = FakeOps(targets, {"chatgpt.com": lambda s: ("denied", None)}, dns_plain=(), dns_unblock=())
    ops.state["hosts"] = {"openai": "malw"}
    run(ops)
    assert ops.state["hosts"] == {"openai": "malw"}
    assert ops.applied("assign_hosts") == ["openai", "openai", "openai"]


def test_resolution_failure_tries_plain_dns_providers_first():
    targets = {"site": ["site.example"]}
    ops = FakeOps(targets, {"site.example": blocked_unless(lambda s: s["dns"] == "google", status="dns")}, hosts=())
    report = run(ops)
    assert ops.applied("apply_dns")[:2] == ["cloudflare", "google"] and ops.state["dns"] == "google"
    assert ("keep_dns",) in ops.calls and row(report, "site")["fix"] == {"kind": "dns", "id": "google"}


def test_dns_that_did_not_help_is_reverted():
    targets = {"site": ["site.example"]}
    ops = FakeOps(targets, {"site.example": lambda s: ("dns", None)}, hosts=())
    report = run(ops)
    assert ops.state["dns"] is None and ("revert_dns",) in ops.calls and row(report, "site")["hint"] == "dns"


def test_geo_block_without_a_proxy_link_says_a_proxy_is_needed():
    targets = {"openai": ["chatgpt.com"]}
    ops = FakeOps(targets, {"chatgpt.com": lambda s: ("denied", None)}, hosts=(), dns_unblock=())
    report = run(ops)
    assert row(report, "openai")["hint"] == "need_proxy" and row(report, "openai")["fix"] is None


def test_proxy_is_the_last_resort_when_a_link_exists():
    targets = {"openai": ["chatgpt.com"]}
    ops = FakeOps(targets, {"chatgpt.com": blocked_unless(lambda s: "openai" in s["proxy"], status="denied")},
                  hosts=(), dns_unblock=(), proxy=True)
    report = run(ops)
    assert ops.state["proxy"] == ["openai"] and row(report, "openai")["fix"] == {"kind": "proxy", "id": "proxy"}


def test_no_network_stops_before_any_change():
    ops = FakeOps(YT, {"youtube.com": lambda s: ("blocked", None), "i.ytimg.com": lambda s: ("blocked", None)},
                  canary={"ya.ru": lambda s: ("blocked", None), "example.com": lambda s: ("dns", None)})
    report = run(ops)
    assert report["offline"] is True and ops.calls == [] and row(report, "youtube")["hint"] == "offline"


def test_strategy_step_restores_winws_when_no_strategy_helps():
    ops = FakeOps(YT, {"youtube.com": lambda s: ("blocked", None), "i.ytimg.com": lambda s: ("blocked", None)},
                  hosts=(), dns_plain=(), dns_unblock=())
    ops.state.update(strategy="general", winws_lists=["discord"])
    report = run(ops)
    assert ("restore_strategy",) in ops.calls
    assert ops.state["strategy"] == "general" and ops.state["winws_lists"] == ["discord"]
    assert row(report, "youtube")["hint"] == "nothing_helped"


def test_strategy_that_fails_to_start_is_skipped():
    fix = strategy_in("alt")
    ops = FakeOps(YT, {"youtube.com": blocked_unless(fix), "i.ytimg.com": blocked_unless(fix)})
    ops.fail_apply.add(("apply_strategy", "general"))
    report = run(ops)
    assert ops.state["strategy"] == "alt" and row(report, "youtube")["after"]["ok"]


def test_external_winws_skips_strategies():
    ops = FakeOps(YT, {"youtube.com": lambda s: ("blocked", None), "i.ytimg.com": lambda s: ("blocked", None)},
                  external=True, hosts=(), dns_plain=(), dns_unblock=())
    report = run(ops)
    assert report["steps"][0] == {"step": "strategy", "skipped": "external"} and ops.applied("apply_strategy") == []


def test_fix_all_prefers_the_strategy_that_fixes_more_services():
    targets = {"youtube": ["youtube.com"], "discord": ["discord.com"]}
    ops = FakeOps(targets, {"youtube.com": blocked_unless(strategy_in("general", "alt")),
                            "discord.com": blocked_unless(strategy_in("alt"))}, hosts=())
    report = run(ops, mode="smart")
    assert ops.state["strategy"] == "alt"
    assert {r["name"]: r["fix"]["id"] for r in report["services"]} == {"youtube": "alt", "discord": "alt"}


def test_partly_fixed_service_keeps_its_list_in_winws_and_continues_to_the_next_step():
    targets = {"youtube": ["youtube.com", "i.ytimg.com"]}
    in_winws = lambda s: s["strategy"] == "alt" and "youtube" in s["winws_lists"]  # noqa: E731
    ops = FakeOps(targets, {"youtube.com": blocked_unless(in_winws),
                            "i.ytimg.com": blocked_unless(lambda s: s["hosts"].get("youtube") == "xbox")})
    report = run(ops)
    assert ops.state["strategy"] == "alt" and ops.state["winws_lists"] == ["youtube"]
    assert ops.state["hosts"] == {"youtube": "xbox"}
    assert row(report, "youtube")["after"]["ok"] is True
    assert row(report, "youtube")["fix"] == {"kind": "hosts", "id": "xbox"}


def test_cancel_stops_between_variants():
    cancel = threading.Event()
    ops = FakeOps(YT, {"youtube.com": lambda s: ("blocked", None), "i.ytimg.com": lambda s: ("blocked", None)})
    ops.hooks["apply_strategy"] = lambda sid: cancel.set()
    with pytest.raises(Cancelled):
        run(ops, cancel=cancel)
    assert ops.applied("apply_strategy") == ["general"]


def test_diagnose_reports_reasons_without_changes():
    targets = {"youtube": ["youtube.com"], "openai": ["chatgpt.com"], "empty": []}
    ops = FakeOps(targets, {"youtube.com": lambda s: ("blocked", None), "chatgpt.com": lambda s: ("denied", None)})
    result = Engine(ops).diagnose(["youtube", "openai", "empty"])
    by = {r["name"]: r for r in result["services"]}
    assert by["youtube"]["reasons"] == ["dpi"] and by["openai"]["reasons"] == ["geo"]
    assert by["empty"]["skipped"] == "no_targets" and ops.calls == [] and result["offline"] is False


def test_progress_reports_each_variant():
    events = []
    fix = strategy_in("alt")
    ops = FakeOps(YT, {"youtube.com": blocked_unless(fix), "i.ytimg.com": blocked_unless(fix)})
    run(ops, progress=events.append)
    tried = [e["candidate"] for e in events if e["type"] == "candidate"]
    results = [e for e in events if e["type"] == "result"]
    assert tried == ["general", "alt"] and results[1]["fixed"] == ["youtube"]
    assert [e["phase"] for e in events if e["type"] == "phase"] == ["diagnose", "strategy", "verify"]
