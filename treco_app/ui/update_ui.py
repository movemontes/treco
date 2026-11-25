"""Aviso de versão nova e a troca do app."""
import threading
import webbrowser

from ..core.log import log_error
from ..modules import updater
from ..version import VERSION
from .pixel import AMBER, BLUE, DARK, INK, RED
from .tool_dialogs import ToolDialog
from .welcome import wrap


class UpdateDialog(ToolDialog):
    def __init__(self, app, info):
        super().__init__(app, "Atualização", 300, 150)
        self.info = info
        self.state, self.progress, self.error = "offer", 0.0, None
        self.host.frame()

    def body(self, ui):
        g = ui.g
        x, y = 16, 26
        g.text(x, y, f"Treco {self.info['version']} saiu!", BLUE, True, 1.25)
        y += 20
        g.text(x, y, f"Você tem a versão {VERSION}.", DARK)
        y += 16
        notes = " ".join(self.info.get("notes", "").split())[:160]
        for part in wrap(notes, self.dw - 2 * x)[:3]:
            g.text(x, y, part, DARK)
            y += 12
        by = self.dh - 30
        right = self.dw - 126, by, 108, 17
        if self.state == "downloading":
            g.rect(x, by + 4, self.dw - 2 * x, 9, line=INK)
            g.rect(x + 1, by + 5, int((self.dw - 2 * x - 2) * self.progress), 7, fill=BLUE)
            g.text(x, by - 14, "Baixando… o Treco vai fechar e abrir de novo sozinho.", DARK)
            return
        if self.state == "error":
            g.text(x, by - 14, self.error or "Não deu certo", RED)
        ui.button("later", x, by, 90, 17, "Agora não", on=self.close)
        if updater.can_install() and self.info.get("download"):
            ui.button("go", *right, "Atualizar", on=self.start, tone=AMBER, bold=True)
        else:
            ui.button("go", *right, "Baixar", on=self.open_page, tone=AMBER, bold=True)

    def open_page(self):
        webbrowser.open(self.info.get("download") or self.info.get("page"))
        self.close()

    def start(self):
        self.state = "downloading"
        self.host.invalidate()

        def work():
            try:
                dmg = updater.download(self.info["download"], lambda v: self.ui_call(setattr, self, "progress", v))
                updater.install(dmg)
                self.ui_call(self.app.quit)
            except Exception as error:
                log_error("atualizar", error)
                self.ui_call(self.failed, str(error))
        threading.Thread(target=work, daemon=True).start()

    def failed(self, message):
        self.state, self.error = "error", ("Não consegui atualizar: " + message)[:60]


def check(app, manual=False):
    """Confere em segundo plano. manual=True avisa também quando não há nada novo."""
    if not updater.configured():
        if manual:
            app.say("Atualização ainda não configurada")
        return

    def work():
        try:
            info = updater.latest()
            updater.mark_checked()
        except Exception as error:
            log_error("procurar atualização", error)
            if manual:
                app.root.after(0, lambda: app.say("Não consegui ver se tem versão nova"))
            return
        if info:
            app.root.after(0, lambda: UpdateDialog(app, info))
        elif manual:
            app.root.after(0, lambda: app.say("Você já tem a versão mais nova"))
    threading.Thread(target=work, daemon=True).start()


def check_later(app):
    """Ao abrir: confere uma vez por dia, sem atrapalhar."""
    if updater.due():
        app.root.after(6000, lambda: check(app))
