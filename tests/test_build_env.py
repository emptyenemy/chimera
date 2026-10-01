import pytest

from tools import build_env


def test_python_314_rejected_before_compiler_is_loaded(monkeypatch):
    monkeypatch.setattr(build_env.sys, "version_info", (3, 14, 7))
    monkeypatch.setattr(build_env, "version", lambda name: pytest.fail("Compiler should not be loaded"))
    with pytest.raises(RuntimeError, match="Python 3.13"):
        build_env.verify()


@pytest.mark.parametrize("compiler", [None, "4.0.8", "4.2.3"])
def test_unpinned_or_missing_compiler_is_rejected(monkeypatch, compiler):
    monkeypatch.setattr(build_env.sys, "version_info", (3, 13, 15))

    def version(name):
        if compiler is None:
            raise build_env.PackageNotFoundError(name)
        return compiler

    monkeypatch.setattr(build_env, "version", version)
    with pytest.raises(RuntimeError, match="Nuitka 4.2.2"):
        build_env.verify()


def test_supported_environment(monkeypatch):
    monkeypatch.setattr(build_env.sys, "version_info", (3, 13, 15))
    monkeypatch.setattr(build_env, "version", lambda name: "4.2.2")
    build_env.verify()
