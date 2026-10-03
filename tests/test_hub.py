"""Delivery retries and refreshes during background state polling."""

import threading

from ui.hub import StateHub


def test_failed_delivery_retries_identical_data():
    delivered = []

    def push(key, payload):
        delivered.append(payload)
        if len(delivered) == 1:
            raise RuntimeError("bridge not ready")

    hub = StateHub(push, [("sample", lambda: {"ok": True, "data": {"enabled": True}}, 30, False)])
    src = hub._sources["sample"]
    hub._poll(src)
    hub._poll(src)
    hub._poll(src)
    assert len(delivered) == 2
    assert delivered[1]["data"] == {"enabled": True}


def test_poke_during_poll_is_kept_for_the_next_poll():
    delivered = []
    hub = None

    def read():
        hub.poke("sample")
        return {"ok": True, "data": {"enabled": True}}

    hub = StateHub(lambda key, payload: delivered.append(payload), [("sample", read, 30, False)])
    src = hub._sources["sample"]
    hub._poll(src)
    assert src.force
    assert delivered == []
    src.fn = lambda: {"ok": True, "data": {"enabled": True}}
    hub._poll(src)
    assert len(delivered) == 1
    assert not src.force


def test_poke_during_poll_wakes_without_waiting_for_the_interval():
    entered = threading.Event()
    release = threading.Event()
    refreshed = threading.Event()
    calls = []

    def read():
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(2)
        else:
            refreshed.set()
        return {"ok": True, "data": len(calls)}

    hub = StateHub(lambda *args: None, [("sample", read, 60, False)])
    hub.start()
    try:
        assert entered.wait(2)
        hub.poke("sample")
        release.set()
        assert refreshed.wait(2)
    finally:
        release.set()
        hub.stop()
        for thread in hub._threads:
            thread.join(2)


def test_stop_discards_a_late_poll_result():
    delivered = []
    hub = None

    def read():
        hub.stop()
        return {"ok": True, "data": {"enabled": True}}

    hub = StateHub(lambda key, payload: delivered.append(payload), [("sample", read, 30, False)])
    hub._poll(hub._sources["sample"])
    assert delivered == []
    assert hub.snapshot() == {}


def test_source_exception_is_reported_and_later_recovery_is_delivered():
    delivered = []

    def broken():
        raise RuntimeError("offline")

    hub = StateHub(lambda key, payload: delivered.append(payload), [("sample", broken, 30, False)])
    src = hub._sources["sample"]
    hub._poll(src)
    assert delivered[-1]["error"] == "offline"
    src.fn = lambda: {"ok": True, "data": {"enabled": True}}
    hub._poll(src)
    assert delivered[-1]["error"] is None
    assert hub.snapshot() == {"sample": {"enabled": True}}
