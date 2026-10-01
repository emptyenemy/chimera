import json
import zipfile

import pytest

from tools.verify_archive import extract


def archive(tmp_path, *, omit=None, flavor="lite", extra=None, manifest_omit=False):
    files = {
        name: b"file" for name in (
            "Chimera.exe", "AGENTS.md", "skills/chimera/SKILL.md", "ui/web-next/index.html",
            "modules/locales/ru.json", "modules/locales/en.json", "versions.json",
            "bin/sing-box/sing-box.exe", "bin/zapret-win-bundle/zapret-winws/winws2.exe",
            "bin/zapret-win-bundle/zapret-winws/WinDivert.dll", "bin/zapret-win-bundle/zapret-winws/WinDivert64.sys",
            "ui/web-next/assets/index.js", "lists/example.txt", "strategies/assets/example.bin",
            "bin/webview2/msedgewebview2.exe", "bin/webview2/msedge.dll", "bin/webview2/icudtl.dat",
            "bin/webview2/resources.pak", "bin/webview2/chimera-runtime.json", "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
            "webview/lib/Microsoft.Web.WebView2.Core.dll", "clr_loader/ffi/dlls/amd64/ClrLoader.dll",
            "pythonnet/runtime/Python.Runtime.dll",
        )
    }
    files["flavor.json"] = json.dumps({"flavor": flavor}).encode()
    files["manifest.txt"] = "\n".join(files).encode()
    if omit:
        files.pop(omit)
        if manifest_omit:
            files["manifest.txt"] = "\n".join(name for name in files if name != "manifest.txt").encode()
    path = tmp_path / "app.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        for name, data in files.items():
            zipped.writestr(f"Chimera-lite/{name}", data)
        if extra:
            zipped.writestr(extra, b"extra")
    return path


def test_extract_complete_archive_into_unicode_path(tmp_path):
    app = extract(archive(tmp_path), tmp_path / "Тест с пробелом", "lite")
    assert (app / "Chimera.exe").is_file()


@pytest.mark.parametrize("missing", ["Chimera.exe", "modules/locales/ru.json", "ui/web-next/assets/index.js"])
def test_missing_file_in_archive_fails_manifest_check(tmp_path, missing):
    with pytest.raises(ValueError, match="Manifest mismatch"):
        extract(archive(tmp_path, omit=missing), tmp_path / "out", "lite")


def test_wrong_flavor_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="flavor mismatch"):
        extract(archive(tmp_path, flavor="webview"), tmp_path / "out", "lite")


def test_unlisted_files_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="unlisted"):
        extract(archive(tmp_path, extra="Chimera-lite/extra.txt"), tmp_path / "out", "lite")


def test_paths_outside_expected_program_folder_are_rejected_before_extraction(tmp_path):
    with pytest.raises(ValueError, match="outside Chimera-lite"):
        extract(archive(tmp_path, extra="Chimera-lite/../../outside.txt"), tmp_path / "out", "lite")
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize("missing", ["bin/webview2/msedge.dll", "pythonnet/runtime/Python.Runtime.dll",
                                    "webview/lib/runtimes/win-x64/native/WebView2Loader.dll"])
def test_manifest_cannot_hide_missing_portable_window_dependencies(tmp_path, missing):
    with pytest.raises(ValueError, match="Archive is incomplete"):
        extract(archive(tmp_path, omit=missing, manifest_omit=True), tmp_path / "out", "lite")
