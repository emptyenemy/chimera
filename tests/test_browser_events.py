"""A stalled browser receives current module state after the event tail overflows."""

from ui.backend_browser import _Hub


def flood(hub):
    for index in range(1001):
        hub.push("reachResult", {"domain": f"site-{index}.example"})


def test_overflow_replays_module_state_before_remaining_stream_events():
    hub = _Hub()
    payload = {"key": "proxy", "data": {"running": True}, "ts": 1}
    hub.push("hub", payload)
    flood(hub)
    events, cursor = hub.poll(0, 0)
    assert events[0] == {"fn": "hub", "payload": payload}
    assert len(events) == 1001
    assert cursor == 1002
    assert hub.poll(cursor, 0) == ([], cursor)


def test_recovery_uses_the_last_module_state_without_duplicate_tail_events():
    hub = _Hub()
    hub.push("hub", {"key": "proxy", "data": {"running": False}})
    hub.push("hub", {"key": "proxy", "data": {"running": True}})
    hub.push("hub", {"key": "hosts", "data": {"enabled": True}})
    flood(hub)
    fresh = {"key": "proxy", "data": {"running": False}}
    hub.push("hub", fresh)
    events, _ = hub.poll(0, 0)
    states = [event["payload"] for event in events if event["fn"] == "hub"]
    assert states == [{"key": "hosts", "data": {"enabled": True}}, fresh]


def test_recovery_does_not_replay_an_already_acknowledged_module_state():
    hub = _Hub()
    hub.push("hub", {"key": "proxy", "data": {"running": True}})
    _, cursor = hub.poll(0, 0)
    flood(hub)
    events, _ = hub.poll(cursor, 0)
    assert all(event["fn"] == "reachResult" for event in events)


def test_normal_poll_preserves_every_event_in_order():
    hub = _Hub()
    for running in (False, True, False):
        hub.push("hub", {"key": "proxy", "data": {"running": running}})
    events, cursor = hub.poll(0, 0)
    assert [event["payload"]["data"]["running"] for event in events] == [False, True, False]
    assert cursor == 3


def test_recovered_poll_does_not_mutate_the_shared_event_tail():
    hub = _Hub()
    hub.push("hub", {"key": "proxy", "data": {"running": True}})
    flood(hub)
    first, cursor = hub.poll(0, 0)
    second, second_cursor = hub.poll(0, 0)
    assert first == second and cursor == second_cursor
    assert len(hub._events) == 1000


def test_completed_check_snapshot_survives_overflow_after_its_done_event():
    hub = _Hub()
    snapshot = {"_request_id": "run-1", "results": [{"target": "site.example", "status": "ok"}]}
    hub.push("blockDone", snapshot)
    flood(hub)
    events, cursor = hub.poll(0, 0)
    assert events[0] == {"fn": "blockDone", "payload": snapshot}
    assert hub.poll(cursor, 0) == ([], cursor)


def test_completed_check_history_is_bounded_and_preserves_both_kinds():
    hub = _Hub()
    for index in range(6):
        for kind in ("blockDone", "cheburDone"):
            hub.push(kind, {"_request_id": f"run-{index}", "results": []})
    flood(hub)
    events, _ = hub.poll(0, 0)
    done = [event for event in events if event["fn"].endswith("Done")]
    assert len(done) == 8
    assert {event["payload"]["_request_id"] for event in done} == {"run-2", "run-3", "run-4", "run-5"}
    assert len(hub._completed) == 8
