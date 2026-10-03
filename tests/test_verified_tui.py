from tests.test_tui_textual import FakeRemote, drive, online, text, until

from tui.screens import ConfirmScreen


class VerifiedRemote(FakeRemote):
    def __init__(self):
        super().__init__()
        self.backup = None
        self.fail = False

    def m_config_verified(self):
        return {"backup": self.backup, "error": None}

    def m_config_verify(self, selected):
        if self.fail:
            return {"saved": False, "error": "Site failed", "checks": [], "backup": None}
        self.backup = {"id": "20261001-120000-001-manual", "checked_at": "2026-10-01T12:00:00Z",
                       "checks": [{"domain": n, "status": "ok"} for n in selected]}
        return {"saved": True, "backup": self.backup, "checks": self.backup["checks"], "error": None}

    def m_config_backup_preview(self, backup_id):
        return {"ok": True, "sections": [{"title": "Proxy", "changes": ["Mode: split → PAC"]}],
                "requires_admin": False, "warnings": []}

    def m_config_backup_restore(self, backup_id, confirmed):
        assert confirmed
        return {"errors": [], "rollback_errors": []}


def test_keyboard_verification_and_restore_need_explicit_confirmation():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('9')
        pane = app.query_one('#settings')
        await until(pilot, lambda: 'verify' in pane.actions)
        assert 'restore' not in pane.actions
        await pilot.press('2', *'YouTube.com,discord.com', 'enter')
        await until(pilot, lambda: ('config_verify', (['youtube.com', 'discord.com'],)) in remote.calls)
        await until(pilot, lambda: 'restore' in pane.actions)
        assert 'youtube.com' in text(app, '#settings-summary')
        await pilot.press('3')
        await until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        assert 'split' in app.screen._text
        assert 'config_backup_restore' not in remote.methods()
        await pilot.press('escape', '3')
        await until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press('y')
        await until(pilot, lambda: ('config_backup_restore', (remote.backup['id'], True)) in remote.calls)
    drive(scenario, VerifiedRemote())


def test_failed_check_is_visible_and_does_not_enable_restore():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('9')
        await until(pilot, lambda: 'verify' in app.query_one('#settings').actions)
        await pilot.press('2', *'youtube.com', 'enter')
        await until(pilot, lambda: 'Site failed' in text(app, '#status'))
        assert 'restore' not in app.query_one('#settings').actions
    remote = VerifiedRemote()
    remote.fail = True
    drive(scenario, remote)
