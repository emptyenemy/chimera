"""Один экземпляр окна: событие занимается первой копией, вторая его взводит."""

import sys
import threading
import uuid

import pytest

from modules import instance

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="именованные события Windows")


@pytest.fixture
def name():
    # своё имя на каждый тест — не задеть открытую программу пользователя
    return rf"Local\Chimera_Test_{uuid.uuid4().hex}"


def test_nothing_running_by_default(name):
    assert instance.is_running(name) is False
    assert instance.signal_existing(name) is False


def test_second_launch_signals_first(name):
    shown = threading.Event()
    listener = instance.listen(shown.set, name)
    assert listener is not None
    try:
        assert instance.is_running(name) is True
        assert instance.signal_existing(name) is True
        assert shown.wait(2), "первая копия не получила сигнал показать окно"
        # повторные запуски тоже доходят, а не только первый
        shown.clear()
        assert instance.signal_existing(name) is True
        assert shown.wait(2)
    finally:
        listener.close()
    assert instance.is_running(name) is False


def test_name_taken_by_other_copy(name):
    first = instance.listen(lambda: None, name)
    try:
        assert instance.listen(lambda: None, name) is None
    finally:
        first.close()
