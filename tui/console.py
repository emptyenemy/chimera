"""Строка команд с очередью, историей и результатами в том же терминале."""

from collections import deque

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, RichLog, Static

from modules.cli.client import CliError
from modules.i18n import t as _tr
from tui import commandline


class ConsoleScreen(ModalScreen[bool]):
    BINDINGS = [Binding('escape', 'close', '', show=False, priority=True),
                Binding('up,ctrl+p', 'history(-1)', '', show=False, priority=True),
                Binding('down,ctrl+n', 'history(1)', '', show=False, priority=True),
                Binding('pageup', 'scroll(-1)', '', show=False, priority=True),
                Binding('pagedown', 'scroll(1)', '', show=False, priority=True),
                Binding('ctrl+l', 'clear', '', show=False),
                Binding('f6', 'focus_output', '', show=False)]

    def __init__(self):
        super().__init__()
        self.queue = deque()
        self.busy = False
        self.closed = False
        self.closing = False
        self.exit_when_closed = False

    def compose(self) -> ComposeResult:
        yield Static(_tr('tui.console.title'), id='console-title', markup=False)
        yield RichLog(id='console-output', wrap=True, markup=False, min_width=1, max_lines=1000)
        yield Static(_tr('tui.console.ready'), id='console-status', markup=False)
        with Horizontal(id='console-line'):
            yield Static(':', id='console-prefix', markup=False)
            yield Input(id='console-input', select_on_focus=False, max_length=65536)
        yield Static(_tr('tui.console.keys'), id='console-keys', markup=False)

    @property
    def pending(self):
        return self.busy or bool(self.queue)

    @property
    def field(self):
        return self.query_one(Input)

    @property
    def output(self):
        return self.query_one(RichLog)

    def on_mount(self):
        for line, kind in self.app.command_transcript:
            self._write_line(line, kind)
        self.field.value = self.app.command_draft
        self.field.cursor_position = len(self.field.value)
        self.field.focus()
        self.set_interval(0.05, self.pump)

    def _write_line(self, line, kind):
        style = 'bold #a78bfa' if kind == 'command' else '#e5949e' if kind == 'error' else ''
        self.output.write(Text(line, style=style))

    def emit(self, lines, kind='text'):
        for line in lines:
            self.app.command_transcript.append((line, kind))
            self._write_line(line, kind)
        self.app.command_transcript = self.app.command_transcript[-1000:]

    def note(self, text, error=False):
        widget = self.query_one('#console-status', Static)
        widget.update(text)
        widget.set_class(error, 'state-error')

    def on_input_changed(self, event):
        event.stop()
        if not event.value:
            self.field.password = False
        elif commandline.sensitive(event.value):
            self.field.password = True

    def on_input_submitted(self, event):
        event.stop()
        value = event.value.strip()
        if not value or self.closing:
            return
        if value.lstrip(':').strip() in ('clear', 'history'):
            if value.lstrip(':').strip() == 'clear':
                self.action_clear()
            else:
                self.emit([f'{i}. {line}' for i, line in enumerate(self.app.command_history.items, 1)])
            self.field.value = ''
            return
        try:
            invocation = commandline.prepare(value)
        except CliError as error:
            if commandline.sensitive(value):
                self.emit([_tr('tui.console.sensitive_error')], 'error')
            else:
                self.emit([': ' + value], 'command')
                self.emit([error.message], 'error')
            self.note(_tr('tui.console.correct_command'), error=True)
            return
        if len(self.queue) >= 100:
            self.note(_tr('tui.console.queue_full'), error=True)
            return
        self.queue.append(invocation)
        self.app.command_history.add(value)
        self.emit([': ' + invocation.label], 'command')
        self.field.value = ''
        self.pump()

    def pump(self):
        if self.closed or self.busy:
            return
        if self.app._writes.pending:
            if self.queue or self.closing:
                self.note(_tr('tui.console.wait_writes'))
            return
        if not self.queue:
            if self.closing:
                self._close_now()
            return
        invocation = self.queue.popleft()
        self.busy = True
        if invocation.changes:
            self.app.invalidate_command_state()
        self.note(_tr('tui.console.executing', command=invocation.action.command if invocation.action else 'help'))

        def work():
            try:
                result = commandline.execute(invocation, self.app.remote)
                lines, code, offline = commandline.output(invocation, result), result.exit_code, False
            except CliError as error:
                lines, code, offline = [error.message], error.exit_code, error.exit_code == 3
            except Exception as error:  # noqa: BLE001 - keep the prompt usable after a transport or file error
                lines, code, offline = [str(error)], 1, False
            if code and commandline.sensitive(invocation.text):
                lines = [_tr('tui.console.sensitive_error')]
            if invocation.changes:
                self.app.remote.record(invocation.label, code == 0)
            self.app._post(self.finished, invocation, lines, code, offline)

        self.app.run_worker(work, thread=True, group='console-command')

    def finished(self, invocation, lines, code, offline):
        if self.closed:
            return
        self.busy = False
        if invocation.changes:
            self.app.invalidate_command_state()
        if offline:
            self.app._set_link(False)
        self.emit(lines, 'error' if code else 'text')
        if code:
            self.cancel_close()
        self.note(_tr('tui.console.failed' if code else 'tui.console.done', code=code), error=bool(code))
        self.app._full_render = True
        self.app.refresh_now(force=True)
        self.pump()

    def cancel_close(self):
        self.closing = self.exit_when_closed = False
        self.field.disabled = False
        self.field.focus()

    def action_history(self, direction):
        if self.field.has_focus:
            self.field.value = self.app.command_history.move(direction, self.field.value)
            self.field.cursor_position = len(self.field.value)
        else:
            getattr(self.output, 'action_scroll_up' if direction < 0 else 'action_scroll_down')()

    def action_scroll(self, direction):
        getattr(self.output, 'action_page_up' if direction < 0 else 'action_page_down')()

    def action_focus_output(self):
        (self.output if self.field.has_focus else self.field).focus()

    def action_clear(self):
        self.output.clear()
        self.app.command_transcript.clear()

    def action_close(self):
        if self.pending or self.app._writes.pending:
            self.closing = True
            self.field.disabled = True
            self.note(_tr('tui.console.wait_writes'))
        else:
            self._close_now()

    def _close_now(self):
        self.app.command_draft = self.field.value if not self.field.password else ''
        self.closed = True
        self.dismiss(self.exit_when_closed)
