"""Редактор списков прямо в терминале: явное сохранение и черновики до выхода."""

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea

from modules.i18n import t as _tr


def canonical(text):
    return text.replace('\r\n', '\n').rstrip('\n') + '\n'


@dataclass
class ListDraft:
    text: str
    baseline: str


class ListTextArea(TextArea):
    BINDINGS = [Binding('ctrl+home', 'document_edge(False)', '', show=False),
                Binding('ctrl+end', 'document_edge(True)', '', show=False),
                Binding('ctrl+shift+home', 'document_edge(False, True)', '', show=False),
                Binding('ctrl+shift+end', 'document_edge(True, True)', '', show=False)]

    def action_document_edge(self, end, select=False):
        row = self.document.line_count - 1 if end else 0
        column = len(self.document.get_line(row)) if end else 0
        self.move_cursor((row, column), select=select)


class ListEditorScreen(ModalScreen[None]):
    BINDINGS = [Binding('ctrl+s', 'save', '', show=False, priority=True),
                Binding('escape', 'close', '', show=False, priority=True),
                Binding('f5', 'reload', '', show=False, priority=True)]

    def __init__(self, name):
        super().__init__()
        self.list_name = name
        self.baseline = None
        self.reading = False
        self.saving = False
        self.pending = None
        self.close_when_saved = False
        self.closed = False

    def compose(self) -> ComposeResult:
        yield Static(_tr('tui.editor.title', name=self.list_name), id='editor-title', markup=False)
        yield ListTextArea('', id='list-text', read_only=True, show_line_numbers=False,
                       highlight_cursor_line=False, tab_behavior='indent')
        yield Static('', id='editor-status', markup=False)
        yield Static(_tr('tui.editor.keys'), id='editor-keys', markup=False)

    @property
    def area(self):
        return self.query_one(TextArea)

    @property
    def dirty(self):
        return self.baseline is not None and canonical(self.area.text) != canonical(self.baseline)

    def on_mount(self):
        draft = self.app.list_drafts.get(self.list_name)
        if draft:
            self.baseline = draft.baseline
            self.area.load_text(draft.text)
            self.area.read_only = False
            self.note(_tr('tui.editor.draft_restored'))
        else:
            self.load()
        self.area.focus()

    def note(self, message, error=False):
        widget = self.query_one('#editor-status', Static)
        widget.update(message)
        widget.set_class(error, 'state-error')

    def remember(self):
        if self.baseline is not None:
            draft = ListDraft(self.area.text, self.baseline) if self.dirty else None
            self.app.remember_list_draft(self.list_name, draft)
        title = _tr('tui.editor.title', name=self.list_name) + (' *' if self.dirty else '')
        self.query_one('#editor-title', Static).update(title)

    def on_text_area_changed(self, event):
        event.stop()
        if not self.closed:
            self.remember()

    def load(self):
        if self.reading or self.saving:
            return
        self.reading = True
        self.area.read_only = True
        self.note(_tr('tui.editor.loading'))
        self.app.act(_tr('tui.editor.read', name=self.list_name), 'lists_read', self.list_name,
                     after=self.loaded, failed=self.load_failed, record=False)

    def loaded(self, content):
        if self.closed or not self.is_mounted:
            return
        self.reading = False
        if not isinstance(content, str):
            self.note(_tr('tui.editor.invalid_response'), error=True)
            return
        self.area.load_text(content)
        self.baseline = self.area.text
        self.area.read_only = False
        self.remember()
        self.note(_tr('tui.editor.ready'))
        self.area.focus()

    def load_failed(self):
        if not self.closed and self.is_mounted:
            self.reading = False
            self.area.read_only = self.baseline is None
            self.note(self.app.status_text + '\n' + _tr('tui.editor.retry_load'), error=True)

    def action_reload(self):
        if self.reading or self.saving:
            return
        if self.dirty:
            self.app.confirm(_tr('tui.editor.reload_confirm'), self.load)
        else:
            self.load()

    def action_save(self):
        if self.baseline is None or self.reading:
            return
        snapshot = self.area.text
        if self.saving:
            self.pending = snapshot
            self.note(_tr('tui.editor.saving'))
        elif self.dirty:
            self.save(snapshot)
        else:
            self.note(_tr('tui.editor.unchanged'))

    def save(self, snapshot):
        self.saving = True
        self.note(_tr('tui.editor.saving'))
        self.app.act(_tr('tui.editor.save', name=self.list_name), 'lists_save', self.list_name, snapshot,
                     after=lambda result: self.saved(snapshot, result), failed=self.save_failed)

    def saved(self, snapshot, result):
        if self.closed or not self.is_mounted:
            return
        self.saving = False
        self.baseline = canonical(snapshot)
        self.remember()
        errors = (result or {}).get('apply_errors') or []
        if errors:
            details = '; '.join(f"{item.get('module', '?')}: {item.get('error', '?')}" for item in errors)
            self.note(_tr('tui.editor.apply_error', error=details), error=True)
            self.close_when_saved = False
        else:
            self.note(_tr('tui.editor.saved'))
        pending, self.pending = self.pending, None
        if pending is not None and canonical(pending) != canonical(self.baseline):
            self.save(pending)
        elif self.close_when_saved:
            self.action_close()

    def save_failed(self):
        if not self.closed and self.is_mounted:
            self.saving = self.close_when_saved = False
            self.pending = None
            self.remember()
            self.note(self.app.status_text + '\n' + _tr('tui.editor.retry_save'), error=True)

    def action_close(self):
        if self.saving:
            self.close_when_saved = True
            self.note(_tr('tui.editor.wait_save'))
            return
        self.remember()
        if self.dirty:
            self.app.status(_tr('tui.editor.draft_kept', name=self.list_name))
        self.closed = True
        self.dismiss(None)
