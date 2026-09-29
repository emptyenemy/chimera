"""Проверка упаковки Textual без терминала и запуска окна."""
import asyncio
import json

from tui.remote import Remote
from tui.textual_app import ChimeraTui, TABS


class ExistingRemote(Remote):
    def ensure_running(self, progress=None):
        self.call("app_info")
        return False


def run() -> int:
    async def check():
        app = ChimeraTui(ExistingRemote(), poll_interval=0.1)
        async with app.run_test(size=(130, 42)) as pilot:
            for _ in range(100):
                if app.link is True:
                    break
                await pilot.pause(0.1)
            if app.link is not True:
                raise RuntimeError("TUI did not connect to the smoke instance")
            for i, (tab, _, _) in enumerate(TABS, 1):
                await pilot.press(str(i))
                await pilot.pause(0.1)
                if app.active_tab != tab:
                    raise RuntimeError(f"TUI tab did not open: {tab}")
            if not app.export_screenshot().lstrip().startswith("<svg"):
                raise RuntimeError("TUI did not render")
        print(json.dumps({"ok": True, "tabs": len(TABS)}))

    asyncio.run(check())
    return 0
