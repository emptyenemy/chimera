"""Api и языки: ответы с кодом ошибки, старое поле error, каталог для фронта."""

import json

import pytest

from modules import appconfig, i18n
from modules.errors import ChimeraError
from ui import api as api_mod


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(api_mod.Api, "_poke_after", lambda self, method: None)
    i18n.refresh()
    yield api_mod.Api.__new__(api_mod.Api)
    i18n.set_lang(None)
    i18n.refresh()


# --- _err: старое поле остаётся, рядом код и параметры ------------------------------------------------

def test_err_keeps_the_russian_error_field_for_plain_exceptions():
    res = api_mod._err(ValueError("что-то сломалось"))
    assert res == {"ok": False, "error": "что-то сломалось", "code": "err.raw",
                   "params": {"message": "что-то сломалось"}}


def test_err_with_code_gives_russian_text_code_and_params():
    res = api_mod._err(ChimeraError("err.method.unknown", method="foo"))
    assert res["ok"] is False
    assert res["error"] == "Неизвестный метод: foo"
    assert (res["code"], res["params"]) == ("err.method.unknown", {"method": "foo"})


def test_error_field_stays_russian_when_the_language_is_english():
    i18n.set_lang("en")
    res = api_mod._err(ChimeraError("err.url.http_only"))
    assert res["error"] == "Только http(s)-ссылки"


def test_open_url_error_is_coded(api):
    res = api.open_url("ftp://example.com")
    assert res["ok"] is False and res["error"] == "Только http(s)-ссылки"
    assert res["code"] == "err.url.http_only" and res["params"] == {}


def test_dispatch_unknown_method_is_coded(api):
    res = json.loads(api.dispatch("нет_такого", "[]"))
    assert res["error"] == "Неизвестный метод: нет_такого"
    assert res["code"] == "err.method.unknown" and res["params"] == {"method": "нет_такого"}


def test_admin_errors_are_coded(api, monkeypatch):
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    res = api.hosts_set_enabled(True)
    assert res["code"] == "err.admin.hosts" and "администратора" in res["error"]
    res = api.dns_set(1, "cloudflare")
    assert res["code"] == "err.admin.dns"
    res = api.winws_start("alt")
    assert res["code"] == "err.admin.winws"
    res = api.autostart_set(True)
    assert res["code"] == "err.admin.autostart"


def test_empty_list_errors_are_coded(api, monkeypatch):
    monkeypatch.setattr(api_mod.domains, "load_lists", lambda names: [])
    assert api.block_check_start("x")["code"] == "err.list.empty"
    assert api.chebur_check_start("x")["code"] == "err.list.empty"


def test_panic_steps_carry_codes(monkeypatch):
    a = api_mod.Api.__new__(api_mod.Api)
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    monkeypatch.setattr(api_mod.applog, "write", lambda *_: None)
    a.winws = type("M", (), {"stop": lambda s: None})()
    a.proxy = type("M", (), {"stop": lambda s: (_ for _ in ()).throw(RuntimeError("ядро занято"))})()
    a.tg = type("M", (), {"stop": lambda s: None})()
    a.hosts = type("M", (), {"set_enabled": lambda s, v: None})()
    a.dns = type("M", (), {"changed_adapters": lambda s: []})()
    steps = {s["step"]: s for s in a.panic_all()["data"]["steps"]}
    assert steps["proxy"]["error"] == "ядро занято" and steps["proxy"]["code"] == "err.raw"
    assert steps["hosts"]["code"] == "err.admin.hosts" and "администратора" in steps["hosts"]["error"]
    assert steps["winws"] == {"step": "winws", "ok": True}


def test_apply_error_gets_code_beside_text():
    data = {}

    def boom():
        raise ChimeraError("err.winws.foreign")
    api_mod.Api._apply_and_report(data, boom)
    assert "вручную" in data["apply_error"]
    assert data["apply_error_code"] == "err.winws.foreign" and data["apply_error_params"] == {}


# --- язык и каталог ----------------------------------------------------------------------------------------------

def test_lang_get_reports_setting_effective_and_system(api, monkeypatch):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    monkeypatch.setattr(i18n, "detect_system_lang", lambda: "en")
    i18n.refresh()
    data = api.lang_get()["data"]
    assert data == {"setting": "auto", "lang": "en", "system": "en", "available": ["ru", "en"]}
    api.config_set("lang", "ru")
    data = api.lang_get()["data"]
    assert (data["setting"], data["lang"], data["system"]) == ("ru", "ru", "en")


def test_config_set_lang_validates(api):
    assert api.config_set("lang", "en")["data"]["lang"] == "en"
    res = api.config_set("lang", "de")
    assert res["ok"] is False and res["code"] == "err.config.lang_unknown"
    assert "auto, ru, en" in res["error"]


def test_i18n_get_returns_whole_catalog_and_plural_rules(api):
    data = api.i18n_get("en")["data"]
    assert data["lang"] == "en" and data["fallback"] == "en" and data["langs"] == ["ru", "en"]
    assert set(data["plural"]) == {"ru", "en"}
    assert data["catalog"] == {**i18n.catalog("en")}
    ru = api.i18n_get("ru")["data"]
    assert ru["catalog"]["err.url.http_only"] == "Только http(s)-ссылки"
    assert set(ru["catalog"]) >= set(i18n.catalog("en"))    # английский добирает недостающее
    json.dumps(ru)


def test_i18n_get_without_language_uses_the_current_one(api):
    i18n.set_lang("en")
    assert api.i18n_get()["data"]["lang"] == "en"


def test_i18n_get_rejects_unknown_language(api):
    res = api.i18n_get("tlh")
    assert res["ok"] is False and res["code"] == "err.lang.unknown" and res["params"]["lang"] == "tlh"


def test_language_methods_only_read():
    assert api_mod.Api.is_read("lang_get") and api_mod.Api.is_read("i18n_get")
