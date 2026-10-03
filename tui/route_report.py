"""Читаемый с клавиатуры разбор маршрута; Esc закрывает, F5 повторяет чтение."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from modules import routeexplain
from modules.i18n import t as _tr


class RouteReportScreen(ModalScreen[None]):
    BINDINGS = [Binding('escape', 'close', '', show=False), Binding('f5', 'reload', '', show=False)]

    def __init__(self, address):
        super().__init__()
        self.address = address
        self.busy = False
        self.closed = False

    def compose(self) -> ComposeResult:
        yield Static(_tr('tui.route.title'), id='route-title', markup=False)
        with VerticalScroll(id='route-report'):
            yield Static(_tr('tui.route.loading'), id='route-text', markup=False)
        yield Static(_tr('tui.route.keys'), classes='prompt-keys', markup=False)

    def on_mount(self):
        self.query_one('#route-report', VerticalScroll).focus()
        self.action_reload()

    def action_reload(self):
        if self.busy:
            return
        self.busy = True
        self.app.act(_tr('tui.route.title'), 'route_explain', self.address,
                     after=self.loaded, failed=self.failed, record=False)

    def loaded(self, report):
        if self.closed:
            return
        self.busy = False
        self.query_one('#route-text', Static).update('\n'.join(routeexplain.render(report)))

    def failed(self):
        if not self.closed:
            self.busy = False
            self.query_one('#route-text', Static).update(self.app.status_text + '\n' + _tr('tui.route.retry'))

    def action_close(self):
        self.closed = True
        self.dismiss(None)
