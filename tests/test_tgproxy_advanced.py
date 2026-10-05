"""modules/tgproxy/manager.py — «продвинутые» настройки ядра tg-ws-proxy
(disable_secure, fallback_cfproxy, cfproxy_*_domains, fake_tls_domain, dc_redirects,
proxy_protocol, force_test_dc): валидация, применение к proxy_config, ссылка tg://.

STATE_PATH подменяем monkeypatch'ем на файл во tmp_path — реальный data/tgproxy.json
не трогаем. Прокси нигде не запускаем: TgProxy.start()/_runner() тут не участвуют.
_import_core() дёргает настоящий сабмодуль upstream/tg-ws-proxy (он уже подтянут в
репозитории) только чтобы прочитать version/get_link_host — сети и сокетов это не
открывает."""

import json

import pytest

from modules.tgproxy import manager as tgproxy_manager
from modules.tgproxy.manager import DEFAULTS, TgProxy


@pytest.fixture
def tg(tmp_path, monkeypatch):
    monkeypatch.setattr(tgproxy_manager, "STATE_PATH", tmp_path / "tgproxy.json")
    return TgProxy()


# --- дефолты и обратная совместимость со старым state.json ---------------------


def test_defaults_match_upstream_proxyconfig(tg):
    assert tg.config["disable_secure"] is False
    assert tg.config["fallback_cfproxy"] is True
    assert tg.config["cfproxy_h2_media"] is True
    assert tg.config["cfproxy_user_domains"] == []
    assert tg.config["cfproxy_worker_domains"] == []
    assert tg.config["fake_tls_domain"] == ""
    assert tg.config["dc_redirects"] == {"2": "149.154.167.220", "4": "149.154.167.220"}
    assert tg.config["proxy_protocol"] is False
    assert tg.config["force_test_dc"] is False


def test_old_state_file_without_new_keys_gets_defaults(tmp_path, monkeypatch):
    old_state = {"host": "1.2.3.4", "port": 999, "secret": "a" * 32, "autostart": True}
    state_path = tmp_path / "tgproxy.json"
    state_path.write_text(json.dumps(old_state), encoding="utf-8")
    monkeypatch.setattr(tgproxy_manager, "STATE_PATH", state_path)

    tg = TgProxy()
    assert tg.config["host"] == "1.2.3.4"          # старое значение сохранилось
    assert tg.config["fallback_cfproxy"] is True    # новый ключ - дефолт
    assert tg.config["dc_redirects"] == DEFAULTS["dc_redirects"]
    assert tg.config["cfproxy_h2_media"] is True


# --- _validate_domain / _normalize_domains --------------------------------------


@pytest.mark.parametrize("value", ["example.com", "sub.example.com", "a-b.co"])
def test_validate_domain_accepts_valid(value):
    assert tgproxy_manager._validate_domain(value) == value.lower()


@pytest.mark.parametrize("value", [
    "", "localhost", "-bad.com", "bad-.com", "bad..com", ".com", "example.",
    "exa mple.com", "example.c", "under_score.com",
])
def test_validate_domain_rejects_invalid(value):
    with pytest.raises(ValueError):
        tgproxy_manager._validate_domain(value)


def test_normalize_domains_dedupes_and_splits_separators():
    result = tgproxy_manager._normalize_domains("Example.com, foo.com; example.com foo.com")
    assert result == ["example.com", "foo.com"]


def test_normalize_domains_accepts_list():
    assert tgproxy_manager._normalize_domains(["a.com", "b.com"]) == ["a.com", "b.com"]


def test_normalize_domains_empty_is_empty_list():
    assert tgproxy_manager._normalize_domains(None) == []
    assert tgproxy_manager._normalize_domains("") == []


def test_normalize_domains_rejects_bad_domain_inside_list():
    with pytest.raises(ValueError):
        tgproxy_manager._normalize_domains(["good.com", "-bad.com"])


# --- _validate_dc_redirects ------------------------------------------------------


def test_validate_dc_redirects_normalizes_keys_to_str():
    out = tgproxy_manager._validate_dc_redirects({2: "1.2.3.4", "4": "5.6.7.8"})
    assert out == {"2": "1.2.3.4", "4": "5.6.7.8"}


def test_validate_dc_redirects_rejects_bad_dc():
    with pytest.raises(ValueError):
        tgproxy_manager._validate_dc_redirects({"x": "1.2.3.4"})


def test_validate_dc_redirects_rejects_bad_ip():
    with pytest.raises(ValueError):
        tgproxy_manager._validate_dc_redirects({"2": "not-an-ip"})


def test_validate_dc_redirects_rejects_non_dict():
    with pytest.raises(ValueError):
        tgproxy_manager._validate_dc_redirects(["2:1.2.3.4"])


# --- TgProxy.set_advanced --------------------------------------------------------


def test_set_advanced_updates_only_given_keys(tg):
    tg.set_advanced({"disable_secure": True})
    assert tg.config["disable_secure"] is True
    assert tg.config["fallback_cfproxy"] is True  # не тронуто


def test_set_advanced_validates_and_persists(tmp_path, monkeypatch):
    state_path = tmp_path / "tgproxy.json"
    monkeypatch.setattr(tgproxy_manager, "STATE_PATH", state_path)
    tg = TgProxy()

    tg.set_advanced({
        "cfproxy_user_domains": "one.com, two.com",
        "fake_tls_domain": "Mask.Example.com",
        "dc_redirects": {2: "1.1.1.1"},
    })
    assert tg.config["cfproxy_user_domains"] == ["one.com", "two.com"]
    assert tg.config["fake_tls_domain"] == "mask.example.com"
    assert tg.config["dc_redirects"] == {"2": "1.1.1.1"}

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["fake_tls_domain"] == "mask.example.com"


def test_set_advanced_empty_fake_tls_domain_clears_it(tg):
    tg.set_advanced({"fake_tls_domain": "example.com"})
    tg.set_advanced({"fake_tls_domain": ""})
    assert tg.config["fake_tls_domain"] == ""


def test_set_advanced_rejects_invalid_domain(tg):
    with pytest.raises(ValueError):
        tg.set_advanced({"cfproxy_worker_domains": ["-bad.com"]})


def test_set_advanced_rejects_non_dict_options(tg):
    with pytest.raises(ValueError):
        tg.set_advanced("not-a-dict")


def test_set_advanced_reports_restart_required_when_running(tg, monkeypatch):
    monkeypatch.setattr(type(tg), "running", property(lambda self: True))
    result = tg.set_advanced({"disable_secure": True})
    assert result["restart_required"] is True


def test_set_advanced_no_restart_hint_when_stopped(tg):
    result = tg.set_advanced({"disable_secure": True})
    assert result["restart_required"] is False


# --- _apply_config ----------------------------------------------------------------


class _FakeProxyConfig:
    pass


class _FakeCore:
    def __init__(self):
        self.proxy_config = _FakeProxyConfig()


def test_apply_config_sets_all_advanced_fields(tg):
    tg.set_advanced({
        "disable_secure": True,
        "fallback_cfproxy": False,
        "cfproxy_user_domains": ["a.com"],
        "cfproxy_worker_domains": ["b.com"],
        "fake_tls_domain": "c.com",
        "dc_redirects": {5: "9.9.9.9"},
        "proxy_protocol": True,
        "force_test_dc": True,
    })
    core = _FakeCore()
    tg._apply_config(core)
    pc = core.proxy_config
    assert pc.host == tg.config["host"]
    assert pc.port == tg.config["port"]
    assert pc.secret == tg.config["secret"]
    assert pc.disable_secure is True
    assert pc.fallback_cfproxy is False
    assert pc.cfproxy_user_domains == ["a.com"]
    assert pc.cfproxy_worker_domains == ["b.com"]
    assert pc.fake_tls_domain == "c.com"
    assert pc.proxy_protocol is True
    assert pc.force_test_dc is True
    assert pc.dc_redirects == {5: "9.9.9.9"}  # ключи -> int, как parse_dc_ip_list апстрима


def test_apply_config_defaults_produce_upstream_default_dc_redirects(tg):
    core = _FakeCore()
    tg._apply_config(core)
    assert core.proxy_config.dc_redirects == {2: "149.154.167.220", 4: "149.154.167.220"}


# --- state(): ссылка tg:// с учётом fake_tls_domain ------------------------------

# ссылку строит ядро из сабмодуля (get_link_host) — в клоне без сабмодулей state()
# отдаёт link=None, и проверять тут нечего
_needs_core = pytest.mark.skipif(
    not (tgproxy_manager.UPSTREAM / "proxy").is_dir(),
    reason="нет сабмодуля upstream/tg-ws-proxy",
)


@_needs_core
def test_state_link_is_dd_secret_without_fake_tls(tg):
    tg.config["secret"] = "a" * 32
    st = tg.state()
    assert st["link"] == f"tg://proxy?server=127.0.0.1&port=1443&secret=dd{'a' * 32}"


@_needs_core
def test_state_link_is_ee_secret_with_fake_tls_domain(tg):
    tg.config["secret"] = "b" * 32
    tg.set_advanced({"fake_tls_domain": "example.com"})
    st = tg.state()
    domain_hex = "example.com".encode("ascii").hex()
    assert st["link"] == f"tg://proxy?server=127.0.0.1&port=1443&secret=ee{'b' * 32}{domain_hex}"
