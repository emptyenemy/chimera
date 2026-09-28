"""app_info: фронт узнаёт из него, собранная ли программа (что в сборке есть, а чего нет)."""

from ui import api as api_mod


def test_app_info_reports_frozen(monkeypatch):
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    monkeypatch.setattr(api_mod.paths, "IS_FROZEN", True)
    assert api_mod.Api.app_info(None)["data"]["frozen"] is True
    monkeypatch.setattr(api_mod.paths, "IS_FROZEN", False)
    assert api_mod.Api.app_info(None)["data"]["frozen"] is False
