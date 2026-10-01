"""Startup diagnostics independent of third-party window engines."""

import ctypes
import os
import sys
import time
import traceback
from pathlib import Path


def log_failure(stage, error):
    # Frame locations are useful for startup failures; exception values can contain secrets.
    code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    text = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {stage}: {type(error).__name__} (code={code})\n"
    text += "".join(f"  {frame.filename}:{frame.lineno} in {frame.name}\n"
                    for frame in traceback.extract_tb(error.__traceback__))
    for root in (os.environ.get("LOCALAPPDATA"), os.environ.get("TEMP")):
        if not root:
            continue
        path = Path(root) / "Chimera" / "startup.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > 1024 * 1024:
                path.replace(path.with_suffix(".previous.log"))
            with path.open("a", encoding="utf-8") as output:
                output.write(text)
            return path
        except OSError:
            pass
    return None


def show_failure(error):
    path = log_failure("startup", error)
    from modules.i18n import t
    message = t("msg.startup.failed", path=str(path or "startup.log"))
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "Chimera", 0x10 | 0x10000)
    else:
        print(message, file=sys.stderr)
