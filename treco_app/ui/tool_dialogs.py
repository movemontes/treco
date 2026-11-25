"""Janelinhas das ferramentas de edição rápida."""
import os
import re
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageOps

from ..modules import media, quick
from ..modules.images import ensure_heif
from .icons import KIND_ICON
from .pixel import AMBER, DARK, GRAY, INK, LCD_LINE, PURPLE, RED, TEAL, WHITE, fit, text_width
from .toolkit import PixelHost, TextField

RATIOS = {"Livre": None, "9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5, "16:9": 16 / 9}


def format_time(value):
    value = max(0, value)
    minutes = int(value // 60)
    return f"{minutes}:{value - minutes * 60:04.1f}"


def parse_time(text):
    text = text.strip().replace(",", ".")
    match = re.fullmatch(r"(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d*)?)", text)
    if not match:
        return None
    parts = [float(p) for p in match.groups() if p is not None]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


class ToolDialog(tk.Toplevel):
    def __init__(self, app, title, width, height, on_close=None):
        super().__init__(app.root)
        self.app, self.on_close_cb, self.title_text = app, on_close, title
        self.dw, self.dh = width, height
        self.alive = True
        scale = app.scale
        self.host = PixelHost(self, width, height, scale, self.draw, title)
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(0, (screen_w - width * scale) // 2)
        y = max(0, (screen_h - 56 - height * scale) // 2)
        self.geometry(f"+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.bring_front)

    def bring_front(self):
        if self.alive:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
            self.after(200, lambda: self.alive and self.attributes("-topmost", False))

    def ui_call(self, fn, *args):
        def run():
            if self.alive:
                fn(*args)
                self.host.invalidate()
        try:
            self.app.root.after(0, run)
        except (RuntimeError, tk.TclError):
            pass

    def draw(self, ui):
        ui.chassis()
        x, y, w, h = 2, 2, self.dw - 4, self.dh - 4
        ui.panel(x, y, w, h, self.title_text, close=self.close, frame=False)
        ui.drag_area(x, y, w - 20, 16)
        self.body(ui)

    def body(self, ui):
        pass

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.host.destroy()
        callback = self.on_close_cb
        self.destroy()
        if callback:
            callback()

    def accept(self):
        """Fecha sem cancelar a fila: a tarefa continua na janela principal."""
        self.close()


class TrimDialog(ToolDialog):
    def __init__(self, app, path, kind, on_close=None):
        super().__init__(app, f"Cortar · {os.path.basename(path)}", 500, 304, on_close)
        self.path, self.kind = path, kind
        self.duration = media.probe(path)["duration"] or 0.0
        self.t0, self.t1 = 0.0, self.duration
        self.exact = True
        self.f0, self.f1 = TextField(format_time(0), 12), TextField(format_time(self.duration), 12)
        self.grab = None
        self.last = "start"
        self.prev_focus = None
        self.strip = None
        self.frame_image = None
        self.frame_key = None
        self.frame_after = None
        self.token = 0
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.box = (14, 22, 300, 170)
        self.line = (16, 206, 466, 46)
        self.pool.submit(self.load_strip)
        self.host.frame()

    def load_strip(self):
        x, y, w, h = self.line
        try:
            image = quick.timeline_strip(self.path, self.kind, w, h)
            if self.kind == "audio":
                base = Image.new("RGBA", image.size, INK + (255,))
                color = Image.new("RGBA", image.size, TEAL + (255,))
                base.paste(color, (0, 0), image.convert("L").point(lambda v: 255 if v > 90 else 0))
                image = base
            self.ui_call(self.set_strip, image.convert("RGB"))
        except Exception:
            pass

    def set_strip(self, image):
        self.strip = image

    def commit(self, key, field, start):
        value = parse_time(field.text)
        if value is not None:
            if start:
                self.t0 = max(0, min(value, self.t1 - 0.05))
            else:
                self.t1 = min(self.duration, max(value, self.t0 + 0.05))
            self.last = "start" if start else "end"

    def body(self, ui):
        g = ui.g
        for key, field, start in (("t0", self.f0, True), ("t1", self.f1, False)):
            if ui.focus == key and any(k[0] == "Return" for k in ui.keys):
                self.commit(key, field, start)
                ui.focus = None
            elif self.prev_focus == key and ui.focus != key:
                self.commit(key, field, start)
            if ui.focus != key:
                field.set(format_time(self.t0 if start else self.t1))
        self.prev_focus = ui.focus

        x, y, w, h = self.box
        g.rect(x - 1, y - 1, w + 2, h + 2, fill=INK)
        if self.kind == "video":
            g.pattern(x, y, w, h, DARK, "25")
            if self.frame_image is not None:
                image = self.frame_image
                s = ui.s
                ui.overlays.append((image, x * s + (w * s - image.width) // 2, y * s + (h * s - image.height) // 2))
            else:
                g.center(x, y + h // 2 - 5, w, "Carregando o quadro…", WHITE)
        else:
            g.icon("audio", x + (w - 64) // 2, y + 36, 64, WHITE)
            g.center(x, y + 112, w, fit(os.path.basename(self.path), w - 16), WHITE)

        cx, cy = 326, 26
        g.text(cx, cy + 2, "Início", INK, True)
        ui.entry("t0", cx + 48, cy, 112, 15, self.f0)
        g.text(cx, cy + 24, "Fim", INK, True)
        ui.entry("t1", cx + 48, cy + 22, 112, 15, self.f1)
        g.hline(cx, cy + 45, 160, GRAY)
        g.text(cx, cy + 51, "Trecho", INK, True)
        g.right(cx + 160, cy + 51, format_time(self.t1 - self.t0), PURPLE, True)
        g.text(cx, cy + 64, "Total", DARK)
        g.right(cx + 160, cy + 64, format_time(self.duration), DARK)
        self.exact = not ui.checkbox("fast", cx, cy + 86, "Corte rápido", not self.exact)
        note = ("corta no quadro exato" if self.exact else "sem recodificar; pode") if self.kind == "video" else ("regrava o áudio" if self.exact else "sem regravar o áudio")
        g.text(cx + 15, cy + 100, note, DARK)
        if self.kind == "video" and not self.exact:
            g.text(cx + 15, cy + 111, "variar alguns quadros", DARK)
        self.draw_timeline(ui)
        by = self.dh - 31
        ui.button("cancel", 16, by, 70, 17, "Cancelar", on=self.close)
        valid = self.duration > 0 and self.t1 - self.t0 >= 0.05 and not (self.t0 <= 0.01 and self.t1 >= self.duration - 0.01)
        ui.button("go", self.dw - 136, by, 118, 17, "Cortar trecho", on=self.apply, enabled=valid, tone=AMBER, bold=True)
        if self.kind == "video":
            self.watch_frame()

    def draw_timeline(self, ui):
        g = ui.g
        x, y, w, h = self.line
        g.rect(x - 1, y - 1, w + 2, h + 2, fill=INK)
        if self.strip is not None:
            g.blit(self.strip.crop((0, 0, w, h)), x, y)
        else:
            g.pattern(x, y, w, h, DARK, "50")
            g.center(x, y + h // 2 - 5, w, "Lendo o arquivo…", WHITE)
        duration = max(self.duration, 0.001)
        to_x = lambda t: x + int(t / duration * (w - 1))
        a, b = to_x(self.t0), to_x(self.t1)
        g.pattern(x, y, a - x, h, INK, "75")
        g.pattern(b + 1, y, x + w - b - 1, h, INK, "75")
        for offset in (0, 1):
            g.hline(a, y + offset, b - a + 1, AMBER)
            g.hline(a, y + h - 1 - offset, b - a + 1, AMBER)
        for handle in (a, b):
            g.rect(handle - 3, y - 3, 7, h + 6, fill=AMBER, line=INK)
            for dot in range(y + h // 2 - 4, y + h // 2 + 5, 3):
                g.hline(handle - 1, dot, 3, INK)
        for i in range(0, 11):
            tx = x + (w - 1) * i // 10
            g.vline(tx, y + h + 4, 3 if i % 5 else 5, INK)
        hover, _, _ = ui.clickable("line", x - 4, y - 4, w + 8, h + 9)
        if hover and ui.pressed:
            self.grab = "start" if abs(ui.mx - a) <= abs(ui.mx - b) else "end"
            ui.focus = None
        if self.grab and ui.down:
            value = max(0.0, min(1.0, (ui.mx - x) / max(1, w - 1))) * duration
            if self.grab == "start":
                self.t0 = max(0, min(value, self.t1 - 0.05))
            else:
                self.t1 = min(duration, max(value, self.t0 + 0.05))
            self.last = self.grab
        if not ui.down:
            self.grab = None

    def watch_frame(self):
        at = self.t0 if self.last == "start" else max(0, self.t1 - 0.05)
        at = round(at, 1)
        if at == self.frame_key:
            return
        self.frame_key = at
        if self.frame_after:
            self.after_cancel(self.frame_after)
        self.frame_after = self.after(120, self.request_frame, at)

    def request_frame(self, at):
        self.frame_after = None
        self.token += 1
        self.pool.submit(self.load_frame, self.token, at)

    def load_frame(self, token, at):
        if token != self.token:
            return
        try:
            s = self.app.scale
            image = quick.frame_png(self.path, at, self.box[2] * s, self.box[3] * s)
            self.ui_call(self.set_frame, token, image)
        except Exception:
            pass

    def set_frame(self, token, image):
        if token == self.token:
            self.frame_image = image

    def apply(self):
        self.app.run_quick([self.path], "trim", {"start": self.t0, "end": self.t1, "exact": self.exact})
        self.accept()

    def close(self):
        if self.alive:
            self.token += 1
            if self.frame_after:
                try:
                    self.after_cancel(self.frame_after)
                except tk.TclError:
                    pass
            self.pool.shutdown(wait=False, cancel_futures=True)
        super().close()


class CropDialog(ToolDialog):
    def __init__(self, app, path, kind, on_close=None):
        super().__init__(app, f"Recortar · {os.path.basename(path)}", 500, 372, on_close)
        self.path, self.kind = path, kind
        self.sw, self.sh = quick.media_size(path, kind)
        self.ratio = "Livre"
        margin_w, margin_h = self.sw // 10, self.sh // 10
        self.rect = [margin_w, margin_h, self.sw - margin_w * 2, self.sh - margin_h * 2]
        self.box = (14, 22, 472, 292)
        self.base = None
        self.dimmed = None
        self.overlay = None
        self.overlay_key = None
        self.grab = None
        self.grab_origin = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pool.submit(self.load_image)
        self.host.frame()

    def load_image(self):
        s = self.app.scale
        max_w, max_h = self.box[2] * s, self.box[3] * s
        try:
            if self.kind == "image":
                ensure_heif()
                with Image.open(self.path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                if image.width < max_w and image.height < max_h:
                    factor = min(max_w / image.width, max_h / image.height)
                    image = image.resize((int(image.width * factor), int(image.height * factor)), Image.Resampling.NEAREST)
            else:
                duration = media.probe(self.path)["duration"]
                image = quick.frame_png(self.path, duration / 2, max_w, max_h)
            dim = Image.blend(image, Image.new("RGB", image.size, INK), 0.66)
            self.ui_call(self.set_base, image, dim)
        except Exception:
            pass

    def set_base(self, image, dim):
        self.base, self.dimmed = image, dim

    def apply_ratio(self, name):
        self.ratio = name
        ratio = RATIOS[name]
        if ratio is None:
            return
        cx, cy = self.rect[0] + self.rect[2] / 2, self.rect[1] + self.rect[3] / 2
        w, h = self.sw, self.sw / ratio
        if h > self.sh:
            h, w = self.sh, self.sh * ratio
        w, h = int(w), int(h)
        x = max(0, min(int(cx - w / 2), self.sw - w))
        y = max(0, min(int(cy - h / 2), self.sh - h))
        self.rect = [x, y, w, h]
        self.overlay_key = None

    def image_origin(self, ui):
        x, y, w, h = self.box
        s = ui.s
        return x * s + (w * s - self.base.width) // 2, y * s + (h * s - self.base.height) // 2

    def body(self, ui):
        g = ui.g
        x, y, w, h = self.box
        g.rect(x - 1, y - 1, w + 2, h + 2, fill=INK)
        g.pattern(x, y, w, h, DARK, "25")
        if self.base is None:
            g.center(x, y + h // 2 - 5, w, "Carregando…", WHITE)
        else:
            self.handle_mouse(ui)
            ox, oy = self.image_origin(ui)
            ui.overlays.append((self.compose(), ox, oy))
        by = self.dh - 37
        names = list(RATIOS)
        cx = 16
        for name in names:
            width = text_width(name) + 12
            ui.button(("ratio", name), cx, by, width, 16, name, on=lambda n=name: self.set_ratio(n), selected=self.ratio == name)
            cx += width + 3
        g.text(cx + 7, by + 3, f"{int(self.rect[2])} × {int(self.rect[3])}", PURPLE, True)
        ui.button("cancel", self.dw - 158, by, 62, 16, "Cancelar", on=self.close)
        whole = self.rect == [0, 0, self.sw, self.sh]
        ui.button("go", self.dw - 90, by, 72, 16, "Recortar", on=self.apply, enabled=self.base is not None and not whole, tone=AMBER, bold=True)

    def set_ratio(self, name):
        self.apply_ratio(name)
        self.host.invalidate()

    def handle_mouse(self, ui):
        s = ui.s
        ox, oy = self.image_origin(ui)
        factor = self.base.width / self.sw
        mx, my = (ui.mx * s + s // 2 - ox) / factor, (ui.my * s + s // 2 - oy) / factor
        x, y, w, h = self.rect
        over_box = ui.over(*self.box)
        reach = 7 * s / factor
        corners = {"nw": (x, y), "ne": (x + w, y), "sw": (x, y + h), "se": (x + w, y + h)}
        if over_box and ui.pressed and ui.active is None:
            ui.active = "crop"
            grabbed = min(corners, key=lambda k: (corners[k][0] - mx) ** 2 + (corners[k][1] - my) ** 2)
            cx, cy = corners[grabbed]
            if abs(cx - mx) <= reach and abs(cy - my) <= reach:
                self.grab = grabbed
            elif x <= mx <= x + w and y <= my <= y + h:
                self.grab = "move"
                self.grab_origin = (mx - x, my - y)
            else:
                self.grab = None
        if self.grab and ui.down:
            if self.grab == "move":
                nx = max(0, min(int(mx - self.grab_origin[0]), self.sw - w))
                ny = max(0, min(int(my - self.grab_origin[1]), self.sh - h))
                self.rect = [nx, ny, w, h]
            else:
                self.drag_corner(mx, my)
        if not ui.down:
            self.grab = None

    def drag_corner(self, mx, my):
        x, y, w, h = self.rect
        ax = x + w if "w" in self.grab else x
        ay = y + h if "n" in self.grab else y
        left = "w" in self.grab
        up = "n" in self.grab
        max_w = ax if left else self.sw - ax
        max_h = ay if up else self.sh - ay
        new_w = max(16, min(max_w, ax - mx if left else mx - ax))
        new_h = max(16, min(max_h, ay - my if up else my - ay))
        ratio = RATIOS[self.ratio]
        if ratio:
            new_w = max(new_w, new_h * ratio)
            new_w = min(new_w, max_w, max_h * ratio)
            new_h = new_w / ratio
        new_w, new_h = int(new_w), int(new_h)
        self.rect = [ax - new_w if left else ax, ay - new_h if up else ay, new_w, new_h]

    def compose(self):
        key = tuple(self.rect)
        if key == self.overlay_key and self.overlay is not None:
            return self.overlay
        factor = self.base.width / self.sw
        x0, y0 = int(self.rect[0] * factor), int(self.rect[1] * factor)
        x1, y1 = int((self.rect[0] + self.rect[2]) * factor), int((self.rect[1] + self.rect[3]) * factor)
        x1, y1 = min(x1, self.base.width - 1), min(y1, self.base.height - 1)
        out = self.dimmed.copy()
        out.paste(self.base.crop((x0, y0, x1, y1)), (x0, y0))
        d = ImageDraw.Draw(out)
        s = self.app.scale
        for i in (1, 2):
            tx = x0 + (x1 - x0) * i // 3
            ty = y0 + (y1 - y0) * i // 3
            for p in range(y0, y1, 4 * s):
                d.rectangle((tx, p, tx + s - 1, p + 2 * s - 1), fill=WHITE)
            for p in range(x0, x1, 4 * s):
                d.rectangle((p, ty, p + 2 * s - 1, ty + s - 1), fill=WHITE)
        d.rectangle((x0, y0, x1, y1), outline=INK, width=s * 2)
        d.rectangle((x0 + s, y0 + s, x1 - s, y1 - s), outline=AMBER, width=s)
        size = 5 * s
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            d.rectangle((cx - size, cy - size, cx + size, cy + size), fill=AMBER, outline=INK, width=s)
        self.overlay, self.overlay_key = out, key
        return out

    def apply(self):
        x, y, w, h = self.rect
        self.app.run_quick([self.path], "crop", {"x": x, "y": y, "w": w, "h": h})
        self.accept()

    def close(self):
        if self.alive:
            self.pool.shutdown(wait=False, cancel_futures=True)
        super().close()


class ResizeDialog(ToolDialog):
    PRESETS = (("25%", {"percent": 25}), ("50%", {"percent": 50}), ("75%", {"percent": 75}), ("1080p", {"side": 1080}),
               ("720p", {"side": 720}), ("480p", {"side": 480}))

    def __init__(self, app, paths, on_close=None):
        super().__init__(app, "Tamanho", 330, 134, on_close)
        self.paths = paths
        self.single = len(paths) == 1
        self.choice = "50%"
        self.size = None
        self.lock = True
        self.fw, self.fh = TextField("", 5), TextField("", 5)
        self.prev = ("", "")
        if self.single:
            try:
                self.size = quick.media_size(paths[0], app.rows[paths[0]].kind)
                self.select("50%")
            except Exception:
                self.single = False
        self.host.frame()

    def select(self, name):
        self.choice = name
        if self.size:
            params = dict(self.PRESETS)[name]
            w, h = quick.target_size(self.size[0], self.size[1], params)
            self.fw.set(str(w))
            self.fh.set(str(h))
            self.prev = (self.fw.text, self.fh.text)
        self.host.invalidate()

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        if self.single:
            g.text(x, y, f"Agora: {self.size[0]} × {self.size[1]}", DARK)
        else:
            g.text(x, y, f"{len(self.paths)} arquivos, cada um na sua proporção", DARK)
        y += 16
        each = 47
        for i, (name, _) in enumerate(self.PRESETS):
            ui.button(("preset", name), x + i * (each + 2), y, each, 18, name, on=lambda n=name: self.select(n),
                      selected=self.choice == name)
        y += 28
        if self.single:
            g.text(x, y + 2, "Largura", INK, True)
            ui.entry("w", x + 52, y, 54, 15, self.fw, numeric=True)
            g.text(x + 116, y + 2, "Altura", INK, True)
            ui.entry("h", x + 158, y, 54, 15, self.fh, numeric=True)
            self.lock = ui.checkbox("lock", x + 222, y + 2, "Proporção", self.lock)
            self.sync_fields()
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Aplicar", on=self.apply, tone=AMBER, bold=True, enabled=self.valid())

    def sync_fields(self):
        current = (self.fw.text, self.fh.text)
        if current == self.prev:
            return
        self.choice = None
        if self.lock and self.size:
            try:
                if current[0] != self.prev[0] and current[0]:
                    self.fh.set(str(max(2, round(int(current[0]) * self.size[1] / self.size[0]))))
                elif current[1] != self.prev[1] and current[1]:
                    self.fw.set(str(max(2, round(int(current[1]) * self.size[0] / self.size[1]))))
            except ValueError:
                pass
        self.prev = (self.fw.text, self.fh.text)

    def valid(self):
        if self.choice:
            return True
        return self.fw.text.isdigit() and self.fh.text.isdigit() and int(self.fw.text) >= 2 and int(self.fh.text) >= 2

    def apply(self):
        params = dict(self.PRESETS)[self.choice] if self.choice else {"w": int(self.fw.text), "h": int(self.fh.text)}
        self.app.run_quick(self.paths, "resize", params)
        self.accept()


class SpeedDialog(ToolDialog):
    VALUES = (0.5, 0.75, 1.25, 1.5, 2.0, 3.0, 4.0)

    def __init__(self, app, paths, on_close=None):
        super().__init__(app, "Velocidade", 330, 110, on_close)
        self.paths, self.value = paths, 2.0
        self.host.frame()

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        g.text(x, y, "Menos que 1x deixa em câmera lenta", DARK)
        y += 16
        each = 40
        for i, value in enumerate(self.VALUES):
            label = f"{value:g}x"
            ui.button(("speed", value), x + i * (each + 3), y, each, 20, label, on=lambda v=value: self.set_value(v),
                      selected=self.value == value)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Aplicar", on=self.apply, tone=AMBER, bold=True)

    def set_value(self, value):
        self.value = value
        self.host.invalidate()

    def apply(self):
        self.app.run_quick(self.paths, "speed", {"factor": self.value})
        self.accept()


SLOW_STEPS = (90, 80, 75, 66, 50, 33, 25)


class SlowDialog(ToolDialog):
    """Deixa vídeo e áudio mais lentos. O som continua com a mesma voz (não fica grosso)."""

    def __init__(self, app, paths, on_close=None):
        from ..core import prefs
        super().__init__(app, "Mais lento", 350, 128, on_close)
        self.paths = paths
        self.field = TextField(str(prefs.get("slow_percent") or 50), 3)
        self.host.frame()

    def percent(self):
        try:
            value = int(self.field.text.strip().rstrip("%"))
        except ValueError:
            return None
        return value if 25 <= value <= 99 else None

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        g.text(x, y, "Velocidade nova, em % da original. 50% = metade.", DARK)
        y += 16
        each = (self.dw - 32 - 6 * 3) // 7
        for i, value in enumerate(SLOW_STEPS):
            ui.button(("slow", value), x + i * (each + 3), y, each, 20, f"{value}%",
                      on=lambda v=value: self.field.set(str(v)), selected=self.percent() == value)
        y += 28
        g.text(x, y + 5, "Ou digite", INK, True)
        ui.entry("pct", x + 70, y, 44, 20, self.field, numeric=True)
        g.text(x + 120, y + 5, "%  (de 25 a 99)", DARK)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Aplicar", on=self.apply, tone=AMBER, bold=True,
                  enabled=self.percent() is not None)

    def apply(self):
        from ..core import prefs
        value = self.percent()
        if value is None:
            return
        prefs.put("slow_percent", value)
        self.app.run_quick(self.paths, "speed", {"factor": value / 100})
        self.accept()


class SplitDialog(ToolDialog):
    def __init__(self, app, path, on_close=None):
        super().__init__(app, f"Separar · {os.path.basename(path)}", 350, 124, on_close)
        self.path = path
        self.pages = quick.pdf_pages(path)
        self.field = TextField("", 80)
        self.host.focus = "pages"
        self.host.frame()

    def error(self):
        try:
            quick.parse_ranges(self.field.text, self.pages)
            return None
        except RuntimeError as e:
            return str(e)

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        g.icon("pdf", x, y, 16, INK)
        g.text(x + 22, y + 3, f"Este PDF tem {self.pages} {'página' if self.pages == 1 else 'páginas'}", INK, True)
        y += 24
        g.text(x, y + 2, "Páginas", INK, True)
        ui.entry("pages", x + 56, y, self.dw - 92, 15, self.field)
        y += 19
        problem = self.error() if self.field.text.strip() else None
        if problem:
            g.text(x + 56, y, problem, RED)
        else:
            g.text(x + 56, y, "Ex.: 1-3, 5  ·  vazio = todas", DARK)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Separar", on=self.apply, tone=AMBER, bold=True,
                  enabled=not problem and self.pages > 1)

    def apply(self):
        self.app.run_quick([self.path], "split", {"ranges": self.field.text})
        self.accept()


class JoinDialog(ToolDialog):
    def __init__(self, app, paths, kind, on_close=None):
        result = "um PDF" if kind in ("image", "pdf") else "um arquivo"
        super().__init__(app, f"Juntar em {result}", 390, 306, on_close)
        self.paths, self.kind = list(paths), kind
        self.scroll = 0
        self.host.frame()

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 22, self.dw - 32
        g.text(x, y, "Arrume a ordem com as setas", DARK)
        y += 14
        rows = (self.dh - 88) // 22
        list_h = rows * 22 + 2
        g.rect(x, y, w - 11, list_h, fill=WHITE, line=INK)
        if ui.wheel:
            self.scroll += ui.wheel
        self.scroll = ui.scrollbar("join-scroll", x + w - 12, y, list_h, max(len(self.paths), 1), rows, self.scroll)
        self.scroll = max(0, min(max(0, len(self.paths) - rows), self.scroll))
        for i in range(self.scroll, min(len(self.paths), self.scroll + rows)):
            ry = y + 1 + (i - self.scroll) * 22
            g.hline(x + 1, ry + 21, w - 13, LCD_LINE)
            g.text(x + 5, ry + 6, f"{i + 1}.", DARK, True)
            g.icon(KIND_ICON[self.kind], x + 24, ry + 3, 15, INK)
            g.text(x + 44, ry + 6, fit(os.path.basename(self.paths[i]), w - 118), INK)
            for k, (label, delta, enabled) in enumerate((("↑", -1, i > 0), ("↓", 1, i < len(self.paths) - 1))):
                bx = x + w - 62 + k * 16
                hover, held, clicked = ui.clickable(("move", i, delta), bx, ry + 4, 14, 14, enabled)
                offset = ui.face(bx, ry + 4, 14, 14, hover, held, enabled=enabled)
                color = ui.ink(hover, held, enabled=enabled)
                for row in range(3):
                    py = ry + 9 + row + offset if delta < 0 else ry + 13 - row + offset
                    g.hline(bx + 7 - row, py, row * 2 + 1, color)
                if clicked:
                    ui.later(self.move, i, delta)
            mark = lambda mx, my, color: ui.mark_x(mx + 3, my + 3, 5, color)
            if ui.mini(("drop", i), x + w - 28, ry + 5, 12, mark, len(self.paths) > 2):
                ui.later(self.remove, i)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        label = "Criar PDF" if self.kind == "image" else "Juntar"
        ui.button("go", self.dw - 106, by, 88, 17, label, on=self.apply, tone=AMBER, bold=True, enabled=len(self.paths) > 1)

    def move(self, index, delta):
        other = index + delta
        if 0 <= other < len(self.paths):
            self.paths[index], self.paths[other] = self.paths[other], self.paths[index]
            self.host.invalidate()

    def remove(self, index):
        if len(self.paths) > 2:
            self.paths.pop(index)
            self.host.invalidate()

    def apply(self):
        self.app.run_join(self.paths, self.kind)
        self.accept()


# ---------------------------------------------------------------- aba Mais
class TranscribeDialog(ToolDialog):
    LANGUAGES = {"Português": "pt", "Inglês": "en", "Espanhol": "es", "Detectar": "auto"}
    FORMATS = {"Texto": "txt", "Legenda SRT": "srt"}

    def __init__(self, app, paths, on_close=None):
        super().__init__(app, "Transcrever", 390, 128, on_close)
        self.paths, self.language, self.format = paths, "Português", "Texto"
        self.host.frame()

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        many = len(self.paths)
        g.text(x, y, "O Treco ouve sem internet e salva o texto." if many == 1
               else f"{many} arquivos, um texto para cada", DARK)
        y += 18
        g.text(x, y + 4, "Idioma", INK, True)
        self.language = ui.segmented("lang", x + 66, y, self.dw - 98, list(self.LANGUAGES), self.language)
        y += 24
        g.text(x, y + 4, "Salvar", INK, True)
        self.format = ui.segmented("fmt", x + 66, y, self.dw - 98, list(self.FORMATS), self.format)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Transcrever", on=self.apply, tone=AMBER, bold=True)

    def apply(self):
        self.app.run_quick(self.paths, "transcribe", {"language": self.LANGUAGES[self.language],
                                                      "format": self.FORMATS[self.format]})
        self.accept()


class PasswordDialog(ToolDialog):
    """Põe senha num PDF aberto, ou tira a senha de um PDF protegido."""

    def __init__(self, app, path, on_close=None):
        from ..modules import extras
        self.locked = extras.pdf_has_password(path)
        title = "Tirar senha" if self.locked else "Pôr senha"
        super().__init__(app, f"{title} · {os.path.basename(path)}", 340, 128, on_close)
        self.path = path
        self.first, self.second = TextField("", 64), TextField("", 64)
        self.host.focus = "pw1"
        self.host.frame()

    def problem(self):
        if self.locked:
            return None if self.first.text else ""
        if len(self.first.text) < 4:
            return "Use pelo menos 4 caracteres" if self.first.text else ""
        if self.second.text != self.first.text:
            return "As senhas não são iguais" if self.second.text else ""
        return None

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        g.icon("lock", x, y, 16, INK)
        g.text(x + 22, y + 3, "Digite a senha do PDF" if self.locked else "Quem abrir o PDF vai precisar dela",
               INK, True)
        y += 24
        g.text(x, y + 2, "Senha", INK, True)
        typed = ui.entry("pw1", x + 70, y, self.dw - 102, 15, self.first, secret=True)
        if not self.locked:
            y += 19
            g.text(x, y + 2, "De novo", INK, True)
            typed = ui.entry("pw2", x + 70, y, self.dw - 102, 15, self.second, secret=True) or typed
        problem = self.problem()
        if problem:
            g.text(x + 70, y + 19, problem, RED)
        if typed and any(k[0] == "Return" for k in ui.keys) and problem is None:
            ui.later(self.apply)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Tirar senha" if self.locked else "Proteger", on=self.apply,
                  tone=AMBER, bold=True, enabled=problem is None)

    def apply(self):
        self.app.run_quick([self.path], "unlock" if self.locked else "lock", {"password": self.first.text})
        self.accept()


class WatermarkDialog(ToolDialog):
    def __init__(self, app, paths, on_close=None):
        from ..modules.extras import POSITIONS
        super().__init__(app, "Marca d'água", 340, 128, on_close)
        self.paths, self.positions, self.position = paths, POSITIONS, POSITIONS[0]
        self.text = TextField(app.last_mark if getattr(app, "last_mark", "") else "", 80)
        self.host.focus = "text"
        self.host.frame()

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        g.text(x, y, "Texto branco e meio transparente, num arquivo novo", DARK)
        y += 18
        g.text(x, y + 2, "Texto", INK, True)
        ui.entry("text", x + 66, y, self.dw - 98, 15, self.text)
        if not self.text.text:
            g.text(x + 72, y + 2, "Ex.: @seunome", DARK)
        y += 24
        g.text(x, y + 4, "Onde", INK, True)
        self.position = ui.segmented("pos", x + 66, y, self.dw - 98, list(self.positions), self.position)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Aplicar", on=self.apply, tone=AMBER, bold=True,
                  enabled=bool(self.text.text.strip()))

    def apply(self):
        self.app.last_mark = self.text.text
        self.app.run_quick(self.paths, "mark", {"text": self.text.text, "position": self.position})
        self.accept()


class RenameDialog(ToolDialog):
    """Renomeia os próprios arquivos (não cria cópias), na ordem da lista."""

    def __init__(self, app, paths, on_close=None):
        super().__init__(app, "Renomear", 360, 160, on_close)
        self.paths = paths
        self.name = TextField("", 80)
        self.start = TextField("1", 5)
        self.host.focus = "name"
        self.host.frame()

    def plan(self):
        from ..modules import extras
        if not self.name.text.strip():
            return None, ""
        try:
            start = int(self.start.text or "1")
            return extras.rename_plan(self.paths, self.name.text, start), None
        except ValueError:
            return None, "Número inválido"
        except RuntimeError as e:
            return None, str(e)

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        many = len(self.paths)
        g.text(x, y, "Muda o nome dos próprios arquivos, na ordem da lista" if many > 1
               else "Muda o nome do próprio arquivo", DARK)
        y += 18
        g.text(x, y + 2, "Nome", INK, True)
        typed = ui.entry("name", x + 52, y, self.dw - 84 - (112 if many > 1 else 0), 15, self.name)
        if many > 1:
            g.text(self.dw - 120, y + 2, "Do nº", INK, True)
            ui.entry("start", self.dw - 72, y, 40, 15, self.start, numeric=True)
        y += 24
        plan, problem = self.plan()
        if problem:
            g.text(x, y, problem, RED)
        elif plan:
            for i, (old, new) in enumerate(plan[:3]):
                line = f"{os.path.basename(old)}  →  {os.path.basename(new)}"
                g.text(x, y + i * 14, fit(line, self.dw - 32), INK)
            if many > 3:
                g.text(x, y + 42, f"e mais {many - 3}", DARK)
        else:
            g.text(x, y, "Ex.: Viagem  →  Viagem 01.jpg, Viagem 02.jpg…", DARK)
        if typed and plan and any(k[0] == "Return" for k in ui.keys):
            ui.later(self.apply)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Renomear", on=self.apply, tone=AMBER, bold=True,
                  enabled=bool(plan))

    def apply(self):
        plan, _ = self.plan()
        if plan and self.app.rename_rows(plan):
            self.accept()


class TranslateDialog(ToolDialog):
    """Traduz textos, legendas e documentos com o tradutor do Mac."""

    def __init__(self, app, paths, on_close=None):
        from ..modules.translate import LANGUAGES
        super().__init__(app, "Traduzir", 390, 104, on_close)
        self.codes = {name: code for name, code, _ in LANGUAGES}
        self.paths = paths
        self.target = getattr(app, "last_language", "Inglês")
        self.host.frame()

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        many = len(self.paths)
        g.text(x, y, "Sem internet. Legenda continua legenda; documento vira texto." if many == 1
               else f"{many} arquivos, uma tradução para cada", DARK)
        y += 18
        g.text(x, y + 4, "Para", INK, True)
        self.target = ui.segmented("lang", x + 66, y, self.dw - 98, list(self.codes), self.target)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Traduzir", on=self.apply, tone=AMBER, bold=True)

    def apply(self):
        self.app.last_language = self.target
        self.app.run_quick(self.paths, "translate", {"target": self.codes[self.target]})
        self.accept()


class SlideshowDialog(ToolDialog):
    """Escolhas do vídeo de slides. Ficam guardadas para a próxima vez."""
    ROWS = (("slide_seconds", "Cada foto", None), ("slide_transition", "Transição", None),
            ("slide_zoom", "Movimento", None), ("slide_order", "Ordem", None), ("slide_shape", "Formato", None))

    def __init__(self, app, paths, on_close=None):
        from ..core import prefs
        super().__init__(app, "Slides em vídeo", 400, 196, on_close)
        self.paths = paths
        self.values = {key: prefs.get(key) for key, _, _ in self.ROWS}
        self.host.frame()

    def choices(self, key):
        from ..modules import slideshow as sl
        return {"slide_seconds": [(f"{v} s", v) for v in sl.SECONDS],
                "slide_transition": [(v, v) for v in sl.TRANSITIONS],
                "slide_zoom": [("Zoom suave", True), ("Parado", False)],
                "slide_order": [(v, v) for v in sl.ORDERS],
                "slide_shape": [(v, v) for v in sl.FORMATS]}[key]

    def body(self, ui):
        g = ui.g
        x, y = 16, 22
        g.text(x, y, f"{len(self.paths)} fotos viram um vídeo MP4 (sem som)", DARK)
        y += 16
        for key, label, _ in self.ROWS:
            options = self.choices(key)
            names = [n for n, _ in options]
            current = next((n for n, v in options if v == self.values[key]), names[0])
            g.text(x, y + 4, label, INK, True)
            picked = ui.segmented(key, x + 80, y, self.dw - 112, names, current)
            self.values[key] = dict(options)[picked]
            y += 21
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 116, by, 98, 17, "Criar vídeo", on=self.apply, tone=AMBER, bold=True)

    def apply(self):
        from ..core import prefs
        for key, value in self.values.items():
            prefs.put(key, value)
        self.app.run_many("slideshow", self.paths, self.app.slide_params())
        self.accept()
