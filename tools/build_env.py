"""Reject build environments that produce unsupported Windows executables."""

import sys
from importlib.metadata import PackageNotFoundError, version


def verify():
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Build requires Python 3.13. Create and activate a venv with py -3.13 -m venv .venv.")
    try:
        compiler = version("nuitka")
    except PackageNotFoundError:
        compiler = None
    if compiler != "4.2.2":
        raise RuntimeError(f"Build requires Nuitka 4.2.2 (found {compiler or 'none'}). Run python -m pip install -r requirements-dev.txt.")


if __name__ == "__main__":
    try:
        verify()
    except RuntimeError as error:
        sys.exit(f"[!] {error}")
