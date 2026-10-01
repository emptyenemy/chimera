from pathlib import Path

import pytest

from tools import finish_build


def test_missing_binary_preserves_previous_build_and_compiler_output(tmp_path, monkeypatch):
    monkeypatch.setattr(finish_build, "ROOT", tmp_path)
    source = tmp_path / "build/lite/main.dist"
    source.mkdir(parents=True)
    (source / "Chimera.exe").write_bytes(b"new executable")
    previous = tmp_path / "build/Chimera-lite"
    previous.mkdir()
    (previous / "Chimera.exe").write_bytes(b"previous executable")
    with pytest.raises(FileNotFoundError, match="Missing build inputs"):
        finish_build.finish("lite")
    assert (source / "Chimera.exe").read_bytes() == b"new executable"
    assert (previous / "Chimera.exe").read_bytes() == b"previous executable"


@pytest.mark.parametrize("flavor", ["../outside", "invalid"])
def test_invalid_flavor_never_moves_files(tmp_path, monkeypatch, flavor):
    monkeypatch.setattr(finish_build, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        finish_build.finish(flavor)
    assert list(Path(tmp_path).iterdir()) == []
