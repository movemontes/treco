"""Janelinhas das utilidades: bateria, teste de internet, senha do Wi-Fi e liberar app (Mac e Windows)."""
import os
import threading
import time

from ..core.log import log_error
from ..core.paths import MAC

if MAC:
    from ..modules import mac_utils
else:  # mesmas funções, feitas com o que vem no Windows
    from ..modules import win_utils as mac_utils
from . import mascot
from .pill import pose_for
from .pixel import AMBER, BLUE, DARK, GRAY, INK, RED, fit
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
    """Teste de internet: os números sobem ao vivo e a janela fica por cima do Treco até acabar."""

    def __init__(self, app):
        super().__init__(app, "Internet", 340, 160)
        self.processes = []
        self.live, self.shown = [0.0, 0.0], [0.0, 0.0]
        self.host.frame()
        self.start()

    def start(self):
        self.processes = []
        self.live = [0.0, 0.0]   # o que o teste mediu até agora
        self.shown = [0.0, 0.0]  # o que aparece na tela, chegando aos poucos no medido
        self.started = time.monotonic()
        self.hold_app()
        self.work(mac_utils.speed_test, self.processes, self.on_progress)

    def on_progress(self, down, up):
        self.ui_call(self._progress, down, up)

    def _progress(self, down, up):
        self.live = [down, up]

    def finish(self, value, error):
        super().finish(value, error)
        if value:
            self.live = self.shown = [value["down"], value["up"]]
        self.release_app()

    def spin(self):
        if self.alive and self.working:
            for i in (0, 1):  # o número corre até o valor medido, sem pular
                self.shown[i] += (self.live[i] - self.shown[i]) * .3
            self.host.invalidate()
            self.after(50, self.spin)

    def cancel(self):
        self.close()

    def close(self):
        for process in self.processes:  # fechar a janela para o teste
            if process.poll() is None:
                process.terminate()
        super().close()

    def buddy(self, g, pose, y, bob):
        size = 76
        mascot.draw(g, pose, self.dw - 12 - mascot.width(pose, size, g.s), y + bob, size)

    @staticmethod
    def number(value):
        return f"{value:.0f}" if value >= 10 else f"{value:.1f}"

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        buddy = mascot.enabled()
        cols_w = w - (84 if buddy else 0)
        if self.error and not self.working:
            if buddy:
                self.buddy(g, "triste", y, 0)
            self.failed(ui, x, y, cols_w)
            g.text(x, y + 22, "Confira se o Mac está conectado.", DARK)
        else:
            uploading = self.working and self.live[1] > 0
            half = (cols_w - 10) // 2
            values = self.shown if self.working else [self.result["down"], self.result["up"]]
            for i, label in enumerate(("Baixar", "Enviar")):
                bx = x + i * (half + 10)
                active = self.working and (i == 1) == uploading
                waiting = self.working and i == 1 and not uploading
                g.text(bx, y, label, BLUE if active else DARK, active)
                if waiting:
                    g.text(bx, y + 12, "—", GRAY, True, 3.2)
                else:
                    text = self.number(values[i])
                    size = 3.2 if g.text_w(text, True, 3.2) + 34 <= half else 2.4  # 1000 Mbps ou mais
                    g.text(bx, y + 12 + round((3.2 - size) * 6), text, BLUE if not self.working or active else INK, True, size)
                    g.text(bx + g.text_w(text, True, size) + 4, y + 30, "Mbps", INK, True)
                if active:
                    g.barber(bx, y + 46, half - 6, 5, int(time.monotonic() * 12), BLUE)
            y += 58
            if self.working:
                step = "Medindo o envio…" if uploading else "Medindo o download…"
                g.text(x, y, step, INK, True)
                g.text(x, y + 14, "Demora uns 25 segundos. O teste é da Apple." if MAC else
                       "Demora uns 25 segundos. O teste é da Cloudflare.", DARK)
            else:
                r = self.result
                g.text(x, y, fit(mac_utils.speed_words(r["down"]), cols_w, True), INK, True)
                if r.get("rpm"):
                    g.text(x, y + 14, f"Resposta: {r['feel']} ({r['rpm']:.0f} RPM)", DARK)
                elif r.get("ping"):
                    g.text(x, y + 14, f"Resposta: {r['feel']} ({r['ping']:.0f} ms)", DARK)
            if buddy:
                pose = "pensando" if self.working else pose_for("done")
                bob = int(time.monotonic() * 2.5) % 2 if self.working else 0
                self.buddy(g, pose, 22, bob)
        by = self.dh - 31
        if self.working:
            ui.button("cancel", x, by, 90, 17, "Cancelar", on=self.cancel, bold=True)
        else:
            ui.button("again", x, by, 110, 17, "Testar de novo", on=self.start, tone=AMBER, bold=True)
            ui.button("done", x + 118, by, 70, 17, "Fechar", on=self.close)


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
            g.text(x, y, "Qual rede? O Mac vai pedir a senha do computador." if MAC else "Qual rede?", DARK)
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
            if MAC:
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
    if not MAC:
        return choose_file()
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


def choose_file():
    """Windows: escolhe o arquivo baixado que o Windows bloqueia (programa, instalador, planilha...)."""
    from tkinter import filedialog
    from ..core.i18n import tr
    from ..modules.cleanup import downloads_folder
    path = filedialog.askopenfilename(title=tr("Escolha o arquivo que o Windows bloqueou"),
                                      initialdir=downloads_folder())
    return os.path.normpath(path) if path else None


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
        label = "Abrir o app" if MAC else "Abrir"
        g.text(x, y + 22, "Pode abrir de novo." if self.result else "Ele já não estava bloqueado.", INK)
        g.text(x, y + 36, "Se o aviso voltar, abra com o botão direito > Abrir." if MAC else
               "Só libere o que você baixou de um lugar confiável.", DARK)
        ui.button("open", x, self.dh - 31, 90, 17, label, on=self.open_app, tone=AMBER, bold=True)

    def open_app(self):
        import subprocess
        if MAC:
            subprocess.Popen(["open", self.path])
        else:
            os.startfile(self.path)
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
