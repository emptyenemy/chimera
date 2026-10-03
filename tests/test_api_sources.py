"""Source streams identify their bulk request without changing legacy replies."""

from types import SimpleNamespace

import pytest

from ui import api as api_mod


@pytest.mark.parametrize("request_id", [None, "request-7"])
def test_bulk_source_stream_keeps_request_identity(monkeypatch, request_id):
    source = {"name": "Source", "current": "1", "latest": "2"}
    events = []

    def check_updates(on_result):
        on_result(source)
        return [source]

    monkeypatch.setattr(api_mod.upstream, "check_updates", check_updates)
    api = SimpleNamespace(_push=lambda event, payload: events.append((event, payload)))
    assert api_mod.Api.upstream_check_updates(api, request_id) == api_mod._ok([source])
    expected = {**source, "_request_id": request_id} if request_id is not None else source
    assert events == [("srcChecked", expected)]
    assert "_request_id" not in source
