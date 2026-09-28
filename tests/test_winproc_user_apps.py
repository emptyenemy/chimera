"""modules/winproc.py — user_apps(): список программ сессии пользователя для выбора
приложений в выборочный TUN. Снапшот настоящий (только чтение), поэтому проверяем
форму и инварианты, а не конкретный набор процессов."""

import os
import sys

from modules import winproc
from ui.api import Api


def test_user_apps_shape_and_order():
    apps = winproc.user_apps()
    assert apps, "в сессии пользователя всегда есть хотя бы сам python"
    names = [a["name"] for a in apps]
    assert names == sorted(names, key=str.lower)
    assert len({n.lower() for n in names}) == len(names)  # без повторов по регистру
    assert all(n.lower().endswith(".exe") and a["count"] >= 1 for n, a in zip(names, apps, strict=True))


def test_user_apps_includes_current_process_and_skips_session_zero():
    names = {a["name"].lower() for a in winproc.user_apps()}
    assert os.path.basename(sys.executable).lower() in names
    # System/Idle/службы — в сессии 0, пользователю их выбирать незачем
    assert "system" not in names
    assert "services.exe" not in names


def test_apps_snapshot_is_read_and_set_apps_is_write():
    assert Api.is_read("proxy_apps_snapshot")
    assert not Api.is_read("proxy_set_apps")
