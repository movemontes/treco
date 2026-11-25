"""Janelinhas das utilidades do Mac: bateria, teste de internet, senha do Wi-Fi e liberar app."""
import os
import threading
import time

from ..core.log import log_error
from ..modules import mac_utils
from .pixel import AMBER, BLUE, DARK, INK, RED, fit
from .tool_dialogs import ToolDialog
from .toolkit import TextField


class BackgroundDialog(ToolDialog):
    """Janela que faz um trabalho demorado sem travar, e redesenha enquanto espera."""

    def __init__(self, app, title, width, height):
        super().__init__(app, title, width, height)
        # começa "trabalhando": quem não começa sozinho (Wi-Fi) desliga isso
        self.result, self.error, self.working = None, None, True

    def work(self, fn, *args):
        self.result, self.error, self.working = None, None, True

        def run():
            try:
                value, error = fn(*args), None
            except Exception as e:
                value, error = None, e
                log_error(self.title_text, e)
            self.ui_call(self.finish, value, error)

        threading.Thread(target=run, daemon=True).start()
        self.spin()

    def finish(self, value, error):
        self.result, self.error, self.working = value, error, False

    def spin(self):
        if self.alive and self.working:
            self.host.invalidate()
            self.after(80, self.spin)

    def waiting(self, ui, x, y, w, text):
        ui.g.text(x, y, text, INK, True)
        ui.g.barber(x, y + 18, w, 10, int(time.monotonic() * 10), BLUE)

    def failed(self, ui, x, y, w):
        ui.g.text(x, y, fit(str(self.error) or "Não deu certo", w, True), RED, True, 1.2)


class BatteryDialog(BackgroundDialog):
    def __init__(self, app):
        super().__init__(app, "Bateria", 300, 168)
        self.host.frame()
        self.work(mac_utils.battery)

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        if self.working:
            self.waiting(ui, x, y, w, "Lendo a bateria…")
            return
        if self.error:
            self.failed(ui, x, y, w)
            return
        b = self.result
        capacity = b["capacity"]
        g.text(x, y, f"{capacity}%" if capacity is not None else "?", BLUE, True, 3.6)
        g.text(x + 112, y + 6, "da capacidade", INK, True)
        g.text(x + 112, y + 20, "de uma bateria nova", DARK)
        y += 56
        rows = [("Estado", b["condition"]), ("Ciclos de carga", str(b["cycles"] or "?")),
                ("Carga agora", f"{b['charge']}%" + (" · carregando" if b["charging"] else
                                                      " · na tomada" if b["plugged"] else ""))]
        if b["temperature"]:
            rows.append(("Temperatura", f"{b['temperature']} °C"))
        for label, value in rows:
            g.text(x, y, label, DARK)
            g.right(x + w, y, value, INK, True)
            g.hline(x, y + 13, w, INK)
            y += 17


class SpeedDialog(BackgroundDialog):
    def __init__(self, app):
        super().__init__(app, "Internet", 320, 176)
        self.processes = []
        self.host.frame()
        self.start()

    def start(self):
        self.processes = []
        self.work(mac_utils.speed_test, self.processes)

    def close(self):
        for process in self.processes:  # fechar a janela para o teste
            if process.poll() is None:
                process.terminate()
        super().close()

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        if self.working:
            self.waiting(ui, x, y, w, "Testando a internet…")
            g.text(x, y + 38, "Demora uns 20 segundos. O teste é da Apple.", DARK)
            return
        if self.error:
            self.failed(ui, x, y, w)
        else:
            r = self.result
            half = (w - 10) // 2
            for i, (label, value) in enumerate((("Baixar", r["down"]), ("Enviar", r["up"]))):
                bx = x + i * (half + 10)
                g.text(bx, y, label, DARK)
                g.text(bx, y + 12, f"{value:.0f}" if value >= 10 else f"{value:.1f}", BLUE, True, 3.2)
                g.text(bx + g.text_w(f"{value:.0f}" if value >= 10 else f"{value:.1f}", True, 3.2) + 4, y + 30, "Mbps", INK, True)
            y += 54
            g.text(x, y, fit(mac_utils.speed_words(r["down"]), w, True), INK, True)
            g.text(x, y + 14, f"Resposta: {r['feel']} ({r['rpm']:.0f} RPM)", DARK)
        ui.button("again", x, self.dh - 31, 110, 17, "Testar de novo", on=self.start, tone=AMBER, bold=True)


class WifiDialog(BackgroundDialog):
    """Escolhe uma rede guardada e mostra a senha com um QR Code para o celular."""

    def __init__(self, app):
        super().__init__(app, "Senha do Wi-Fi", 320, 222)
        self.networks = mac_utils.saved_networks()
        self.search = TextField("", 64)
        self.working = False
        self.host.focus = "search"
        self.name = None
        self.copied = False
        self.host.frame()

    def pick(self, name):
        self.name, self.copied = name, False
        self.work(mac_utils.wifi_password, name)

    def finish(self, value, error):
        super().finish(value, error)
        if not error:
            self.qr = mac_utils.wifi_qr(self.name, value, 132)

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.result)
        self.copied = True

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        if not self.networks:
            g.text(x, y, "Este Mac não tem redes Wi-Fi guardadas.", INK, True)
            return
        if self.name is None:
            g.text(x, y, "Qual rede? O Mac vai pedir a senha do computador.", DARK)
            focused = ui.entry("search", x, y + 14, w, 20, self.search)
            if not self.search.text and not focused:
                g.text(x + 6, y + 20, "Digite parte do nome da rede", DARK)
            words = self.search.text.strip().lower()
            shown = [n for n in self.networks if words in n.lower()][:6]
            for i, name in enumerate(shown):
                ui.button(("net", name), x, y + 40 + i * 24, w, 20, name, on=lambda n=name: self.pick(n))
            if not shown:
                g.text(x, y + 46, "Nenhuma rede guardada com esse nome.", DARK)
            elif focused and any(k[0] == "Return" for k in ui.keys):
                ui.later(self.pick, shown[0])
            return
        if self.working:
            self.waiting(ui, x, y, w, fit(f"Pegando a senha de {self.name}…", w, True))
            g.text(x, y + 38, "Digite a senha do Mac na janela que abrir.", DARK)
            return
        if self.error:
            self.failed(ui, x, y, w)
            ui.button("back", x, self.dh - 31, 70, 17, "Voltar", on=lambda: setattr(self, "name", None))
            return
        g.blit(self.qr, x - 4, y - 2)
        tx = x + self.qr.width + 6
        tw = self.dw - tx - 14
        g.text(tx, y + 4, "Rede", DARK)
        g.text(tx, y + 16, fit(self.name, tw, True), INK, True)
        g.text(tx, y + 38, "Senha", DARK)
        g.text(tx, y + 50, fit(self.result or "(sem senha)", tw, True), BLUE, True, 1.2)
        g.text(tx, y + 76, "Aponte a câmera", DARK)
        g.text(tx, y + 88, "do celular para o QR.", DARK)
        ui.button("copy", tx, self.dh - 31, tw, 17, "Copiado" if self.copied else "Copiar senha", on=self.copy,
                  enabled=bool(self.result))
        ui.button("back", tx, self.dh - 53, tw, 17, "Outra rede", on=lambda: setattr(self, "name", None))


def choose_app(start="/Applications", title="Escolha o app que o Mac diz estar danificado", prompt="Liberar"):
    """Janela do Mac para escolher um app. Devolve o caminho, ou None se cancelar."""
    from AppKit import NSModalResponseOK, NSOpenPanel
    from Foundation import NSURL
    from ..core.i18n import tr
    title, prompt = tr(title), tr(prompt)
    panel = NSOpenPanel.openPanel()
    panel.setTitle_(title)
    panel.setMessage_(title)
    panel.setPrompt_(prompt)
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setTreatsFilePackagesAsDirectories_(False)
    panel.setAllowedFileTypes_(["app"])
    panel.setDirectoryURL_(NSURL.fileURLWithPath_(start))
    if panel.runModal() != NSModalResponseOK:
        return None
    return str(panel.URL().path())


class UnblockDialog(BackgroundDialog):
    def __init__(self, app, path):
        super().__init__(app, "Liberar app", 320, 120)
        self.path = path
        self.host.frame()
        self.work(mac_utils.unblock, path)

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        name = os.path.basename(self.path)
        if self.working:
            self.waiting(ui, x, y, w, fit(f"Liberando {name}…", w, True))
            return
        if self.error:
            self.failed(ui, x, y, w)
            return
        g.text(x, y, fit(f"{name} liberado.", w, True), BLUE, True, 1.4)
        g.text(x, y + 22, "Pode abrir de novo." if self.result else "Ele já não estava bloqueado.", INK)
        g.text(x, y + 36, "Se o aviso voltar, abra com o botão direito > Abrir.", DARK)
        ui.button("open", x, self.dh - 31, 90, 17, "Abrir o app", on=self.open_app, tone=AMBER, bold=True)

    def open_app(self):
        import subprocess
        subprocess.Popen(["open", self.path])
        self.close()


def unblock_app(app):
    try:
        path = choose_app()
    except Exception as error:
        log_error("escolher app", error)
        app.say("Não consegui abrir a escolha de app")
        return
    if path:
        UnblockDialog(app, path)
