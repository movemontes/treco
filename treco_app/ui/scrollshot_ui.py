"""Captura com rolagem: marcar a área na tela e a janelinha de controle enquanto a pessoa rola."""
import os
import threading
import tkinter as tk

from PIL import Image, ImageDraw

from ..core import prefs
from ..core.log import log_error
from .pixel import AMBER, BLUE, DARK, INK, RED, fit
from .tool_dialogs import ToolDialog


class AreaPicker:
    """A tela fica escura; a pessoa arrasta para marcar a área que vai rolar. Esc cancela."""

    def __init__(self, app, on_done):
        from . import platform_mac as mac
        self.app, self.on_done = app, on_done
        self.win = win = tk.Toplevel(app.root)
        win.withdraw()
        mac.borderless(win)
        width, height = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{width}x{height}+0+0")
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.4)
        self.canvas = tk.Canvas(win, bg="#000000", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(width // 2, height // 2, fill="#FFFFFF", font=("Helvetica", 22, "bold"),
                                text="Arraste para marcar a área que vai rolar\nEsc cancela", justify="center")
        self.start = self.box = None
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        win.bind("<Escape>", lambda e: self.finish(None))
        win.deiconify()
        win.lift()
        mac.activate()
        win.focus_force()

    def press(self, event):
        self.start = (event.x_root, event.y_root)

    def move(self, event):
        if not self.start:
            return
        x0, y0 = self.start
        ox, oy = self.win.winfo_rootx(), self.win.winfo_rooty()
        if self.box:
            self.canvas.delete(self.box)
        self.box = self.canvas.create_rectangle(x0 - ox, y0 - oy, event.x_root - ox, event.y_root - oy,
                                                outline="#FFFFFF", width=3, fill="#3355FF")

    def release(self, event):
        if not self.start:
            return
        x0, y0 = self.start
        x, y = min(x0, event.x_root), min(y0, event.y_root)
        w, h = abs(event.x_root - x0), abs(event.y_root - y0)
        self.finish((x, y, w, h) if w >= 60 and h >= 60 else None)

    def finish(self, region):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.app.root.after(150, lambda: self.on_done(region))  # espera a tela escura sumir antes da 1ª foto


class Frame:
    """Moldura azul em volta da área (por fora dela, para não sair na foto). Não pega cliques."""

    def __init__(self, region):
        from .platform_mac import Overlay
        x, y, w, h = (int(v) for v in region)
        pad = 4
        self.panel = Overlay(w + pad * 2, h + pad * 2, click_through=True)
        from .platform_mac import hide_from_capture
        hide_from_capture(self.panel.panel)  # a moldura não pode sair na foto
        image = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((0, 0, w + pad * 2 - 1, h + pad * 2 - 1), outline=(40, 90, 255, 255), width=3)
        self.panel.push(image, x - pad, y - pad)
        self.panel.deiconify()

    def close(self):
        self.panel.withdraw()


class ScrollShotDialog(ToolDialog):
    """Fica do lado da área enquanto a pessoa rola. "Pronto" junta tudo numa imagem só."""

    def __init__(self, app, region):
        from ..modules import scrollshot
        super().__init__(app, "Captura com rolagem", 236, 118)
        self.region = region
        self.session = scrollshot.Session(region)
        self.thread = threading.Thread(target=self.session.run, daemon=True)
        self.saving = False
        self.frame_box = None
        self.place()
        try:
            from .platform_mac import hide_from_capture
            self.update()
            if not hide_from_capture(self):  # esta janelinha fica fora das fotos, mesmo em cima da área
                log_error("captura com rolagem", RuntimeError("não escondi a janela da captura"))
        except Exception as error:
            log_error("esconder janela da captura", error)
        try:
            self.frame_box = Frame(region)
        except Exception as error:
            log_error("moldura da captura", error)
        self.after(200, self.thread.start)  # começa depois que as janelas do Treco sumiram das fotos
        self.host.frame()
        self.tick()

    def bring_front(self):
        pass  # não rouba o foco: a pessoa está rolando outra janela

    def place(self):
        """Fora da área marcada: à direita, à esquerda ou embaixo."""
        x, y, w, h = self.region
        width, height = self.dw * self.app.scale, self.dh * self.app.scale
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        if x + w + 16 + width <= screen_w:
            spot = (x + w + 16, y)
        elif x - 16 - width >= 0:
            spot = (x - 16 - width, y)
        elif y + h + 16 + height <= screen_h:
            spot = (x, y + h + 16)
        else:
            spot = (max(0, x - width - 16), max(0, y - height - 16))
        self.geometry(f"+{int(spot[0])}+{int(spot[1])}")

    def tick(self):
        if not self.alive:
            return
        self.host.invalidate()
        if self.session.error and not self.saving:
            self.saving = True
            self.app.say("O Mac não deixou capturar a tela")
            from ..modules import recorder
            recorder.open_privacy("ScreenCapture")
            self.close()
            return
        self.after(250, self.tick)

    def body(self, ui):
        g = ui.g
        x, y, w = 12, 24, self.dw - 24
        stitch = self.session.stitcher
        if self.saving:
            g.text(x, y, "Juntando e salvando…", INK, True)
            return
        g.text(x, y, "Role devagar a área marcada.", INK, True)
        g.text(x, y + 14, f"Altura: {stitch.height:,} px".replace(",", "."), BLUE, True)
        if stitch.lost:
            g.text(x, y + 28, fit("Rápido demais: volte um pouco", w, True), RED, True)
        else:
            g.text(x, y + 28, "Pode rolar com o mouse ou o trackpad.", DARK)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("done", self.dw - 100, by, 88, 17, "Pronto", on=self.done, tone=AMBER, bold=True,
                  enabled=stitch.head is not None)

    def done(self):
        from ..modules import scrollshot
        self.saving = True
        self.session.stop()
        self.host.invalidate()

        def work():
            self.thread.join(5)
            try:
                image = self.session.stitcher.result()
                folder = self.app.out_dir or os.path.expanduser("~/Desktop")
                path = scrollshot.save(image, folder, prefs.get("shot_format"))
                self.app.root.after(0, lambda: self.saved(path, None))
            except Exception as error:
                log_error("captura com rolagem", error)
                message = str(error)[:44]
                self.app.root.after(0, lambda: self.saved(None, message))
        threading.Thread(target=work, daemon=True).start()

    def saved(self, path, error):
        if path:
            self.app.add_files([path])
            from .platform_mac import notify, reveal
            reveal(path)
            notify(os.path.basename(path), "Treco: captura salva")
            self.app.say("Captura salva", BLUE)
        else:
            self.app.say(error or "Não consegui salvar")
        self.close()

    def close(self):
        self.session.stop()
        if self.frame_box:
            self.frame_box.close()
            self.frame_box = None
        if getattr(self, "hid_main", False):
            self.hid_main = False
            self.app.win.deiconify()
        super().close()


def start(app):
    """Esconde o Treco, deixa marcar a área e começa a capturar."""
    from ..modules import recorder
    if not recorder.screen_allowed(ask=True):
        recorder.open_privacy("ScreenCapture")
        app.say("Libere o Treco em Gravação de Tela nos Ajustes")
        return
    shown = app.win.state() != "withdrawn"
    app.win.withdraw()

    def picked(region):
        if region is None:
            if shown:
                app.win.deiconify()
            return
        dialog = ScrollShotDialog(app, region)
        dialog.hid_main = shown
    AreaPicker(app, picked)
