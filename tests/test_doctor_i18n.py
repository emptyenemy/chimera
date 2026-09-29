"""Диагностика на двух языках: текст по языку, код и параметры — постоянные."""

import re

import pytest

from modules import doctor, i18n
from tests.test_doctor import by_id, healthy


def broken():
    d = healthy()
    d.update(admin=False, winws_exe=False)
    d["winws"] = {"running": True, "external": True, "windivert": "STOPPED"}
    d["proxy"].update(external=True, core={"present": False})
    d["ports"] = {"proxy": True, "tg": False}
    d["system_proxy"] = {"autoconfig": "http://x/proxy.pac", "our_pac": "file:///C:/x/proxy.pac",
                         "enabled": False, "server": None}
    d["service"] = {"installed": True, "running": True}
    return d


def test_checks_carry_code_and_params():
    got = by_id(doctor.evaluate(broken()))
    assert got["admin"]["code"] == "doctor.admin.warn" and got["admin"]["params"] == {}
    assert got["port_proxy"]["code"] == "doctor.port.busy" and got["port_proxy"]["params"] == {"port": 2080}
    assert got["system_proxy"]["code"] == "doctor.system_proxy.foreign_pac"
    assert got["system_proxy"]["params"] == {"pac": "http://x/proxy.pac"}


def test_every_check_text_comes_from_its_code():
    for lang in ("ru", "en"):
        with i18n.using(lang):
            for data in (healthy(), broken()):
                for c in doctor.evaluate(data)["checks"]:
                    assert c["title"] == i18n.t(f"doctor.{c['id']}.title")
                    assert c["message"] == doctor.mask(i18n.t(c["code"] + ".message", **c["params"]))
                    expected_hint = i18n.t(c["code"] + ".hint", **c["params"]) if i18n.has(c["code"] + ".hint") else ""
                    assert c["hint"] == doctor.mask(expected_hint)
                    if c["status"] != "ok":
                        assert c["hint"], (c["id"], c["code"])


def test_language_changes_text_but_not_ids_statuses_or_codes():
    with i18n.using("ru"):
        ru = doctor.evaluate(broken())
    with i18n.using("en"):
        en = doctor.evaluate(broken())
    strip = lambda res: [(c["id"], c["status"], c["code"], c["params"]) for c in res["checks"]]  # noqa: E731
    assert strip(ru) == strip(en)
    assert ru["summary"] == en["summary"]
    assert by_id(ru)["admin"]["message"] == "Chimera работает без прав администратора."
    assert by_id(en)["admin"]["message"] == "Chimera is running without administrator rights."


def test_english_checks_have_no_cyrillic():
    with i18n.using("en"):
        for data in (healthy(), broken()):
            text = str(doctor.evaluate(data)["checks"])
            assert not re.search("[А-Яа-яЁё]", text)


def test_english_markdown_report():
    with i18n.using("en"):
        text = doctor.to_markdown(doctor.evaluate(broken()))
    assert text.startswith("### Chimera diagnostics")
    assert "Summary:" in text and "Hint:" in text and "**Administrator rights**" in text
    assert not re.search("[А-Яа-яЁё]", text)


def test_missing_data_texts_exist_in_both_languages():
    d = healthy()
    d.update(admin=None, winws=None, versions=None, system_proxy=None, os=None)
    for lang in ("ru", "en"):
        with i18n.using(lang):
            res = doctor.evaluate(d)
            for c in res["checks"]:
                assert not c["message"].startswith("doctor."), c
            assert by_id(res)["app"]["message"].endswith(i18n.t("doctor.app.unknown_os") + ".")


@pytest.mark.parametrize("secret", ["vless://11111111-2222-3333-4444-555555555555@example.com:443",
                                    "tg://proxy?server=1.2.3.4&port=1443&secret=dd00112233445566778899aabbccddeeff"])
def test_secrets_do_not_reach_params_either(secret):
    d = healthy()
    d["system_proxy"] = {"autoconfig": secret, "our_pac": "x", "enabled": False, "server": None}
    res = doctor.evaluate(d)
    assert secret not in repr(res) and "***" in repr(res)
