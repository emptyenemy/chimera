"""Доп. проверка: сгенерированный ProxyManager.build_config() конфиг реально
валиден с точки зрения sing-box (`sing-box check -c`).

`check` — статическая проверка конфига, без запуска ядра (не поднимает TUN,
не слушает порты, не лезет в сеть) — единственная подкоманда sing-box, которую
можно дёргать в тестах без нарушения «не запускать winws2/sing-box». Пишем
конфиг во временный файл, не в реальный modules/proxy/singbox-config.json.
Скип, если бинаря нет (bin/sing-box/sing-box.exe — не в репозитории)."""

import json
import subprocess

import pytest

from modules.proxy.manager import SINGBOX_EXE, ProxyManager

pytestmark = pytest.mark.skipif(not SINGBOX_EXE.exists(), reason="sing-box.exe не установлен")

VLESS_LINK = "vless://uuid-1@1.2.3.4:443?security=none&type=tcp#test"


@pytest.mark.parametrize("mode", ["pac", "split", "tun"])
def test_generated_config_passes_singbox_check(tmp_path, monkeypatch, mode):
    from modules.proxy import manager as proxy_manager

    monkeypatch.setattr(
        proxy_manager.domains, "split_lists",
        lambda names: (["example.com"], ["10.0.0.0/24"]),
    )
    pm = ProxyManager()
    pm.config["link"] = VLESS_LINK
    pm.config["lists"] = ["somelist"]
    pm.config["apps"] = ["Discord.exe", "chrome.exe"]
    pm.config["mode"] = mode

    cfg = pm.build_config()
    # конфиг ссылается на файлы правил — check открывает их и сверяет схему
    pm._write_rulesets()
    cfg_path = tmp_path / "singbox-config.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    res = subprocess.run(
        [str(SINGBOX_EXE), "check", "-c", str(cfg_path)],
        capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert res.returncode == 0, f"sing-box check провалился:\n{res.stdout}\n{res.stderr}"
