"""Правка списков клавиатурой, ошибки и запоздалые ответы без настоящих файлов."""

import threading

from textual.widgets import Button

from tests.test_tui_textual import FakeRemote, drive, online, until
from tui.editor import ListEditorScreen
from tui.remote import RemoteError
from tui.screens import ConfirmScreen


async def editor(app, pilot, name='discord'):
    await online(pilot, app)
    app.open_section('lists')
    await until(pilot, lambda: app.data('lists') is not None)
    app.edit_list(name)
    await until(pilot, lambda: isinstance(app.screen, ListEditorScreen) and not app.screen.area.read_only)
    return app.screen


class DelayedSave(FakeRemote):
    def __init__(self, fail=False):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = fail
        self.writes = 0

    def m_lists_save(self, name, content):
        self.writes += 1
        if self.writes == 1:
            self.entered.set()
            if not self.release.wait(8):
                raise RemoteError('test response timed out')
            if self.fail:
                raise RemoteError('disk full')
        return super().m_lists_save(name, content)


def test_terminal_editing_saves_text_comments_and_networks_without_window_controls():
    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        assert not list(screen.query(Button))
        assert screen.area.styles.scrollbar_size_horizontal == 0
        assert screen.area.styles.scrollbar_size_vertical == 0
        await pilot.press('f7', *'# note', 'enter', *'example.com', 'enter', *'192.0.2.0/24', 'ctrl+s')
        await until(pilot, lambda: not screen.saving and not screen.dirty)
        assert remote.list_text['discord'] == '# note\nexample.com\n192.0.2.0/24\n'
        assert remote.journal == [('lists_save', True)]
        assert 'discord' not in app.list_drafts
        await pilot.press('ctrl+s')
        assert remote.methods().count('lists_save') == 1
        await pilot.press('escape')
        assert app.active_section == 'lists'
    drive(scenario)


def test_wasd_numbers_question_mark_and_q_type_normally_and_copy_does_not_quit():
    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'wasd123q?', 'f7', 'ctrl+c')
        assert app.is_running and not app._exit
        assert screen.area.text == 'wasd123q?'
        assert app.clipboard == 'wasd123q?'
        assert app.active_section == 'lists'
        await pilot.press('end', 'backspace', 'ctrl+z')
        assert screen.area.text == 'wasd123q?'
    drive(scenario)


def test_escape_keeps_draft_and_e_restores_it_without_a_second_read():
    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'new.example', 'escape')
        assert app.list_drafts['discord'].text == 'new.example'
        assert remote.list_text['discord'] == '# Discord\ndiscord.com\n'
        assert 'Черновик' in app.status_text
        await pilot.press('e')
        await until(pilot, lambda: isinstance(app.screen, ListEditorScreen))
        assert app.screen.area.text == 'new.example'
        assert app.screen.dirty
        assert remote.methods().count('lists_read') == 1
        assert screen is not app.screen
    drive(scenario)


def test_quit_requires_keyboard_confirmation_before_discarding_drafts():
    async def scenario(app, pilot, remote):
        await editor(app, pilot)
        await pilot.press('f7', *'new.example', 'escape', 'q')
        assert isinstance(app.screen, ConfirmScreen)
        assert not app._exit
        await pilot.press('enter')
        assert not app._exit and 'discord' in app.list_drafts
        await pilot.press('q', 'y')
        assert app._exit
        assert not any(method.endswith('_stop') for method in remote.methods())
        assert 'lists_save' not in remote.methods()
    drive(scenario)


def test_save_failure_preserves_the_text_and_allows_explicit_retry():
    remote = FakeRemote()
    remote.errors['lists_save'] = 'disk full'

    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'new.example', 'ctrl+s')
        await until(pilot, lambda: not screen.saving)
        assert screen.area.text == 'new.example' and screen.dirty
        assert app.list_drafts['discord'].text == 'new.example'
        assert 'disk full' in str(screen.query_one('#editor-status').render())
        remote.errors.clear()
        await pilot.press('ctrl+s')
        await until(pilot, lambda: not screen.saving and not screen.dirty)
        assert remote.list_text['discord'] == 'new.example\n'
    drive(scenario, remote)


def test_edits_during_a_save_survive_the_acknowledgement_as_an_unsaved_draft():
    remote = DelayedSave()

    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'first.example', 'ctrl+s')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('end', 'enter', *'second.example')
            assert remote.writes == 1
        finally:
            remote.release.set()
        await until(pilot, lambda: not screen.saving)
        assert remote.list_text['discord'] == 'first.example\n'
        assert screen.area.text == 'first.example\nsecond.example'
        assert screen.dirty
        assert app.list_drafts['discord'].text == screen.area.text
    drive(scenario, remote)


def test_fast_saves_coalesce_to_the_latest_requested_text_and_stay_serial():
    remote = DelayedSave()

    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'first.example', 'ctrl+s')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('f7', *'second.example', 'ctrl+s', 'f7', *'last.example', 'ctrl+s', 'ctrl+s')
            assert remote.writes == 1
        finally:
            remote.release.set()
        await until(pilot, lambda: not screen.saving)
        assert remote.list_text['discord'] == 'last.example\n'
        assert remote.writes == 2
        assert not screen.dirty and not app.list_drafts
    drive(scenario, remote)


def test_escape_waits_for_save_and_write_failure_leaves_editor_open():
    remote = DelayedSave(fail=True)

    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'new.example', 'ctrl+s')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('escape')
            assert app.screen is screen and screen.close_when_saved
        finally:
            remote.release.set()
        await until(pilot, lambda: not screen.saving)
        assert app.screen is screen and screen.dirty
        assert not screen.close_when_saved
    drive(scenario, remote)


def test_partial_apply_failure_is_distinguished_from_file_save_failure():
    remote = FakeRemote()
    save = remote.m_lists_save

    def partial(name, content):
        result = save(name, content)
        result['apply_errors'] = [{'module': 'hosts', 'error': 'access denied'}]
        return result

    remote.m_lists_save = partial

    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'new.example', 'ctrl+s')
        await until(pilot, lambda: not screen.saving)
        assert not screen.dirty and not app.list_drafts
        message = str(screen.query_one('#editor-status').render())
        assert 'Файл сохранён' in message and 'hosts: access denied' in message
        await pilot.press('ctrl+s')
        assert remote.methods().count('lists_save') == 1
    drive(scenario, remote)


def test_failed_read_can_be_retried_and_cannot_save_an_empty_placeholder():
    remote = FakeRemote()
    remote.errors['lists_read'] = 'read failed'

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        app.edit_list('discord')
        screen = app.screen
        await until(pilot, lambda: not screen.reading)
        assert screen.area.read_only
        await pilot.press('ctrl+s')
        assert 'lists_save' not in remote.methods()
        remote.errors.clear()
        await pilot.press('f5')
        await until(pilot, lambda: not screen.area.read_only)
        assert screen.area.text == remote.list_text['discord']
    drive(scenario, remote)


def test_reload_discards_changes_only_after_confirmation_and_only_after_success():
    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'draft.example', 'f5', 'enter')
        assert screen.area.text == 'draft.example'
        remote.errors['lists_read'] = 'read failed'
        await pilot.press('f5', 'y')
        await until(pilot, lambda: not screen.reading)
        assert screen.area.text == 'draft.example' and screen.dirty
        assert not screen.area.read_only
        remote.errors.clear()
        remote.list_text['discord'] = 'external.example\n'
        await pilot.press('f5', 'y')
        await until(pilot, lambda: not screen.reading)
        assert screen.area.text == 'external.example\n'
        assert not app.list_drafts
    drive(scenario)


def test_late_read_cannot_replace_text_in_a_new_editor():
    remote = FakeRemote()
    entered, release = threading.Event(), threading.Event()
    read = remote.m_lists_read

    def delayed(name):
        if name == 'discord':
            entered.set()
            if not release.wait(8):
                raise RemoteError('test response timed out')
        return read(name)

    remote.m_lists_read = delayed

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        app.edit_list('discord')
        await until(pilot, entered.is_set)
        try:
            await pilot.press('escape')
            app.edit_list('youtube')
            screen = app.screen
            await until(pilot, lambda: not screen.area.read_only)
        finally:
            release.set()
        await pilot.pause(0.1)
        assert app.screen is screen and screen.area.text == 'youtube.com\n'
    drive(scenario, remote)


def test_invalid_names_and_invalid_read_responses_are_not_editable():
    remote = FakeRemote()
    remote.m_lists_read = lambda name: {'text': 'wrong format'}

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        for name in ('../bad', 'bad\n', '', None):
            app.edit_list(name)
            assert not isinstance(app.screen, ListEditorScreen)
        assert 'lists_read' not in remote.methods()
        app.edit_list('discord')
        screen = app.screen
        await until(pilot, lambda: not screen.reading)
        assert screen.area.read_only and screen.baseline is None
        await pilot.press('ctrl+s')
        assert 'lists_save' not in remote.methods()
    drive(scenario, remote)


def test_escape_after_a_successful_save_keeps_newer_edits_available_in_the_menu():
    remote = DelayedSave()

    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('f7', *'first.example', 'ctrl+s')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('end', 'enter', *'newer.example', 'escape')
            assert app.screen is screen
        finally:
            remote.release.set()
        await until(pilot, lambda: app.screen is not screen)
        assert remote.list_text['discord'] == 'first.example\n'
        assert app.list_drafts['discord'].text == 'first.example\nnewer.example'
        await pilot.press('e')
        await until(pilot, lambda: isinstance(app.screen, ListEditorScreen))
        assert app.screen.dirty and 'newer.example' in app.screen.area.text
    drive(scenario, remote)


def test_long_list_can_be_navigated_and_edited_with_hidden_scrollbars():
    remote = FakeRemote()
    remote.list_text['discord'] = ''.join(f'site-{i}.example\n' for i in range(1000))

    async def scenario(app, pilot, remote):
        screen = await editor(app, pilot)
        await pilot.press('ctrl+end', *'last.example', 'ctrl+s')
        await until(pilot, lambda: not screen.saving)
        assert remote.list_text['discord'].endswith('site-999.example\nlast.example\n')
        assert screen.area.styles.scrollbar_size_vertical == 0
        await pilot.press('ctrl+home')
        assert screen.area.selection.end == (0, 0)
        await pilot.press('ctrl+shift+end', 'ctrl+c')
        assert app.clipboard == screen.area.text and not app._exit
    drive(scenario, remote)
