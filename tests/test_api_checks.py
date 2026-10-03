"""List check streams keep run identity and a complete final result snapshot."""

from types import SimpleNamespace

import pytest

from ui import api as api_mod


@pytest.mark.parametrize("kind", ["block", "chebur"])
@pytest.mark.parametrize("request_id", [None, "run-1"])
def test_check_worker_stream_and_final_snapshot(kind, request_id):
    events = []
    def check(target):
        return {"target": target, "status": "ok"}

    api = SimpleNamespace(_push=lambda name, data: events.append((name, data)), _block_one=check, _chebur_one=check)
    worker = api_mod.Api._run_blockcheck if kind == "block" else api_mod.Api._run_chebur
    worker(api, ["first.example", "second.example"], request_id)
    assert len(events) == 3 and events[-1][0] == f"{kind}Done"
    results = [data for name, data in events if name == f"{kind}Result"]
    assert {result["target"] for result in results} == {"first.example", "second.example"}
    if request_id is None:
        assert events[-1][1] == {} and all("_request_id" not in result for result in results)
    else:
        assert all(result["_request_id"] == request_id for result in results)
        done = events[-1][1]
        assert done["_request_id"] == request_id
        assert {result["target"] for result in done["results"]} == {"first.example", "second.example"}


@pytest.fixture
def captured_threads(monkeypatch):
    threads = []

    class Thread:
        def __init__(self, **options):
            threads.append(options)

        def start(self):
            pass

    monkeypatch.setattr(api_mod.threading, "Thread", Thread)
    return threads


def test_reachability_reply_provides_the_original_target_snapshot(monkeypatch, captured_threads):
    monkeypatch.setattr(api_mod.domains, "load_lists", lambda names: ["first.example", "second.example"])
    api = SimpleNamespace(_run_blockcheck=lambda: None)
    reply = api_mod.Api.block_check_start(api, "sample", "run-1")
    assert reply == api_mod._ok({"total": 2, "targets": ["first.example", "second.example"]})
    assert captured_threads[0]["args"] == (["first.example", "second.example"], "run-1")


def test_registry_worker_uses_supplied_snapshot_after_the_list_changes(monkeypatch, captured_threads):
    monkeypatch.setattr(api_mod.domains, "load_lists", lambda names: ["changed.example"])
    api = SimpleNamespace(_run_chebur=lambda: None)
    reply = api_mod.Api.chebur_check_start(api, "sample", "run-1", ["original.example"])
    assert reply == api_mod._ok({"total": 1})
    assert captured_threads[0]["args"] == (["original.example"], "run-1")


@pytest.mark.parametrize("targets", ["example.com", [None], [""], {}])
def test_invalid_registry_snapshot_does_not_start_a_worker(targets, captured_threads):
    reply = api_mod.Api.chebur_check_start(None, "sample", "run-1", targets)
    assert not reply["ok"] and captured_threads == []
