"""modules/doctor.py — диагностика: оценка собранных данных (чистая функция) и маскирование
секретов в отчёте. Живой сбор данных (gather) — только чтение, здесь его данные подставляются
словарём. Api.doctor_run / doctor_report — на заглушках."""

import pytest

from modules import doctor
from ui import api as api_mod


def healthy():
    """Данные здоровой системы: всё установлено, ничего не запущено."""
    return {
        "admin": True,
        "app_version": "1.0.0",
        "os": "Windows-11",
        "winws_exe": True,
        "winws": {"running": False, "external": False, "windivert": "STOPPED"},
        "proxy": {"running": False, "external": False, "socks_port": 2080, "mode": "pac",
                  "core": {"present": True, "version": "1.14.2"}},
        "tg": {"running": False, "host": "127.0.0.1", "port": 1443},
        "ports": {"proxy": False, "tg": False},
        "versions": [{"name": "zapret2", "current": "v0.9"}, {"name": "sing-box", "current": "1.14.2"}],
        "system_proxy": {"autoconfig": None, "our_pac": "file:///C:/x/proxy.pac", "enabled": False, "server": None},
        "service": {"installed": False, "running": False},
    }


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


def test_healthy_system_has_no_warnings():
    res = doctor.evaluate(healthy())
    assert res["summary"] == {"ok": len(res["checks"]), "warn": 0, "fail": 0}
    assert all(c["status"] == "ok" for c in res["checks"])
    assert all({"id", "title", "status", "message", "hint"} <= set(c) for c in res["checks"])


def test_no_admin_is_a_warning_with_a_hint():
    d = healthy()
    d["admin"] = False
    c = by_id(doctor.evaluate(d))["admin"]
    assert c["status"] == "warn" and "администратор" in c["hint"]


def test_windivert_stopped_while_winws_runs_is_a_failure():
    d = healthy()
    d["winws"] = {"running": True, "external": False, "windivert": "STOPPED"}
    assert by_id(doctor.evaluate(d))["windivert"]["status"] == "fail"


def test_windivert_missing_is_fine_until_first_start():
    d = healthy()
    d["winws"]["windivert"] = None
    assert by_id(doctor.evaluate(d))["windivert"]["status"] == "ok"


def test_foreign_winws_and_singbox_processes_are_warnings():
    d = healthy()
    d["winws"] = {"running": True, "external": True, "windivert": "RUNNING"}
    d["proxy"]["running"] = True
    d["proxy"]["external"] = True
    got = by_id(doctor.evaluate(d))
    assert got["foreign_winws"]["status"] == "warn"
    assert got["foreign_singbox"]["status"] == "warn"


def test_busy_port_of_stopped_proxy_is_a_failure_but_our_own_is_fine():
    d = healthy()
    d["ports"] = {"proxy": True, "tg": True}
    got = by_id(doctor.evaluate(d))
    assert got["port_proxy"]["status"] == "fail" and "2080" in got["port_proxy"]["message"]
    assert got["port_tg"]["status"] == "fail" and "1443" in got["port_tg"]["message"]

    d["proxy"]["running"] = True
    d["tg"]["running"] = True
    got = by_id(doctor.evaluate(d))
    assert got["port_proxy"]["status"] == "ok" and got["port_tg"]["status"] == "ok"


def test_missing_bundle_and_core_are_reported():
    d = healthy()
    d["winws_exe"] = False
    d["proxy"]["core"] = {"present": False, "version": None}
    got = by_id(doctor.evaluate(d))
    assert got["zapret_bundle"]["status"] == "fail"
    assert got["singbox_core"]["status"] == "warn"


def test_stale_pac_of_ours_while_proxy_is_stopped_is_a_warning():
    d = healthy()
    d["system_proxy"]["autoconfig"] = d["system_proxy"]["our_pac"]
    c = by_id(doctor.evaluate(d))["system_proxy"]
    assert c["status"] == "warn" and "Выключить всё" in c["hint"]


def test_foreign_system_proxy_is_pointed_out_without_alarm():
    d = healthy()
    d["system_proxy"].update(autoconfig=None, enabled=True, server="127.0.0.1:8888")
    c = by_id(doctor.evaluate(d))["system_proxy"]
    assert c["status"] == "warn" and "127.0.0.1:8888" in c["message"]


def test_versions_are_listed_in_one_line():
    c = by_id(doctor.evaluate(healthy()))["versions"]
    assert "zapret2 v0.9" in c["message"] and "sing-box 1.14.2" in c["message"]


def test_missing_data_is_reported_not_raised():
    d = healthy()
    d["winws"] = None
    d["versions"] = None
    res = doctor.evaluate(d)
    got = by_id(res)
    assert got["windivert"]["status"] == "warn" and "получить" in got["windivert"]["message"]
    assert got["versions"]["status"] == "warn"


def test_service_running_is_informational():
    d = healthy()
    d["service"] = {"installed": True, "running": True}
    assert "работает" in by_id(doctor.evaluate(d))["service"]["message"]


# --- отчёт для issue -------------------------------------------------------------------

def test_markdown_report_lists_every_check_with_status():
    text = doctor.to_markdown(doctor.evaluate(healthy()))
    assert text.startswith("### Диагностика Chimera")
    assert "Права администратора" in text
    assert "✅" in text


def test_markdown_marks_problems_and_hints():
    d = healthy()
    d["admin"] = False
    d["winws_exe"] = False
    text = doctor.to_markdown(doctor.evaluate(d))
    assert "⚠️" in text and "❌" in text
    assert "Подсказка" in text


@pytest.mark.parametrize("secret", [
    "vless://11111111-2222-3333-4444-555555555555@example.com:443?security=tls#name",
    "trojan://pa55w0rd@example.com:443",
    "tg://proxy?server=192.168.1.2&port=1443&secret=dd00112233445566778899aabbccddeeff",
])
def test_secrets_are_masked_in_report(secret):
    d = healthy()
    d["versions"] = [{"name": "прокси", "current": secret}]
    res = doctor.evaluate(d)
    text = doctor.to_markdown(res)
    assert secret not in text
    assert "***" in text
    # маскируется и структурный вид, который получает интерфейс
    assert secret not in repr(res)


def test_mask_leaves_ordinary_text_alone():
    assert doctor.mask("порт 2080 занят другим приложением") == "порт 2080 занят другим приложением"


# --- Api -------------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    a = api_mod.Api.__new__(api_mod.Api)
    monkeypatch.setattr(doctor, "gather", lambda api: healthy())
    return a


def test_api_doctor_run_returns_structured_result(api):
    res = api.doctor_run()
    assert res["ok"] is True
    assert res["data"]["summary"]["fail"] == 0
    assert res["data"]["checks"]


def test_api_doctor_report_returns_markdown(api):
    res = api.doctor_report()
    assert res["ok"] and res["data"].startswith("### Диагностика Chimera")


def test_api_doctor_report_can_return_data_instead(api):
    res = api.doctor_report(markdown=False)
    assert res["ok"] and "checks" in res["data"]


def test_api_doctor_only_reads(api):
    # диагностика ничего не меняет: после неё хаб дёргать незачем
    assert api_mod.Api.is_read("doctor_run") is True
    assert api_mod.Api.is_read("doctor_report") is True
