"""Janela da legenda rápida, em pixels."""
import io
import os
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import font as tkfont

from PIL import Image

from ..core.jobs import Cancelled, Job
from ..modules import captions
from .pixel import AMBER, DARK, GREEN, INK, LCD_HI, RED, TEALD, WHITE, fit, text_width
from .toolkit import PixelHost, TextField

W, H = 520, 372
ROW = 16
SWATCH = {"Branco": WHITE, "Amarelo": (255, 230, 0), "Verde": (139, 210, 110), "Preto": (0, 0, 0)}
LANGS = {"PT": "Português", "EN": "Inglês", "ES": "Espanhol", "Auto": "Automático"}


def clock(value):
    value = int(value)
    return f"{value // 60:02d}:{value % 60:02d}"


class CaptionEditor(tk.Toplevel):
    def __init__(self, app, path, on_close=None):
        super().__init__(app.root)
        self.app, self.path, self.on_close_cb = app, path, on_close
        self.alive = True
        self.job = None
        self.burning = False
        self.segments = []
        self.fields = []
        self.current = 0
        self.scroll = 0
        self.status = ("", DARK)
        self.progress = 0.0
        self.generated = False
        self.pill_task = None
        families = sorted({f for f in tkfont.families(self) if f and not f.startswith("@")}, key=str.casefold)
        self.families = families or ["Arial"]
        self.font = next((f for f in ("Arial", "Segoe UI", "Verdana") if f in self.families), self.families[0])
        self.size = 64
        self.color = "Branco"
        self.position = "Baixo"
        self.bold = True
        self.lang = "PT"
        self.font_open = False
        self.font_scroll = 0
        self.font_filter = TextField("", 40)
        self.preview_image = None
        self.preview_key = None
        self.preview_after = None
        self.preview_token = 0
        self.preview_pool = ThreadPoolExecutor(max_workers=1)
        scale = app.scale
        height = min(H, (self.winfo_screenheight() - 56) // scale)
        self.h = height
        self.host = PixelHost(self, W, height, scale, self.draw, f"Legenda · {os.path.basename(path)}")
        self.box = (14, 22, 248, 140)
        x = app.root.winfo_rootx() + 30 if app.root.state() == "normal" else (self.winfo_screenwidth() - W * scale) // 2
        y = max(0, app.root.winfo_rooty() + 30 if app.root.state() == "normal" else 40)
        x = max(0, min(x, self.winfo_screenwidth() - W * scale))
        self.geometry(f"+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self.close)
        if app.root.state() == "normal":  # Windows: fica na frente do Treco ao voltar de outro app
            self.after(60, lambda: self.alive and self.host.set_owner(app.host))
        self.after(100, self.bring_front)
        self.host.frame()
        self.start_transcription()

    def bring_front(self):
        if self.alive:
            self.lift()
            self.focus_force()

    def ui_call(self, fn, *args):
        def run():
            if self.alive:
                fn(*args)
                self.host.invalidate()
        try:
            self.app.root.after(0, run)
        except (RuntimeError, tk.TclError):
            pass

    # ------------------------------------------------ desenho
    def draw(self, ui):
        g = ui.g
        ui.chassis()
        ui.enabled = not self.font_open
        px, py, pw, ph = 2, 2, W - 4, self.h - 4
        ui.panel(px, py, pw, ph, f"Legenda rápida · {os.path.basename(self.path)}", close=self.close, frame=False)
        ui.drag_area(px, py, pw - 20, 16)
        if ui.keys and self.fields and not self.font_open:
            self.keyboard(ui)
        self.draw_preview(ui)
        self.draw_controls(ui)
        self.draw_text_list(ui)
        if self.font_open:
            ui.enabled = True
            self.draw_font_list(ui)
        self.watch_preview()

    def keyboard(self, ui):
        focus = ui.focus
        if not (isinstance(focus, tuple) and focus[0] == "seg"):
            return
        index = focus[1]
        for keysym, _, _ in list(ui.keys):
            target = None
            if keysym in ("Down", "Return"):
                target = index + 1
            elif keysym == "Up":
                target = index - 1
            if target is not None and 0 <= target < len(self.fields):
                ui.focus = ("seg", target)
                self.current = target
                self.ensure_visible(target)
                ui.keys = []
                return

    def ensure_visible(self, index):
        rows = self.visible_rows()
        if index < self.scroll:
            self.scroll = index
        elif index >= self.scroll + rows:
            self.scroll = index - rows + 1

    def visible_rows(self):
        return max(1, (self.h - 92) // ROW)

    def draw_preview(self, ui):
        g = ui.g
        x, y, w, h = self.box
        g.rect(x - 1, y - 1, w + 2, h + 2, fill=INK)
        g.pattern(x, y, w, h, DARK, "25")
        if self.preview_image is not None and not self.font_open:
            image = self.preview_image
            s = ui.s
            ox = x * s + (w * s - image.width) // 2
            oy = y * s + (h * s - image.height) // 2
            ui.overlays.append((image, ox, oy))
        elif self.preview_image is None:
            g.center(x, y + h // 2 - 5, w, "Preparando a prévia…", WHITE)

    def draw_controls(self, ui):
        g = ui.g
        x, y = 14, 170
        label_w, field_x, field_w = 58, 72, 190
        g.text(x, y + 2, "Fonte", INK, True)
        hover, held, clicked = ui.clickable("font-open", field_x, y, field_w, 15)
        ui.face(field_x, y, field_w, 15, hover, held)
        tone = ui.ink(hover, held)
        g.text(field_x + 5, y + 3, fit(self.font, field_w - 24, hover), tone, hover)
        for row in range(4):
            g.hline(field_x + field_w - 13 + row, y + 6 + row, 8 - row * 2, tone)
        if clicked:
            self.font_open = True
            self.font_filter.set("")
            ui.focus = "font-filter"
            try:
                self.font_scroll = max(0, self.families.index(self.font) - 3)
            except ValueError:
                self.font_scroll = 0
            ui.later(ui.invalidate)
        y += 22
        g.text(x, y + 1, "Tamanho", INK, True)
        self.size = ui.slider("size", field_x, y, field_w - 28, self.size, 28, 140)
        g.right(field_x + field_w, y + 1, str(self.size), INK, True)
        y += 20
        g.text(x, y + 2, "Cor", INK, True)
        sx = field_x
        for name in captions.COLORS:
            each = text_width(name, True, .8) + 15
            hover, held, clicked = ui.clickable(("color", name), sx, y, each, 15)
            selected = self.color == name
            ui.face(sx, y, each, 15, hover, held, selected)
            g.rect(sx + 3, y + 4, 8, 8, fill=SWATCH[name], line=WHITE if selected and name == "Preto" else INK)
            g.text(sx + 13, y + 4, name, ui.ink(hover, held, selected), hover or selected, .8)
            if clicked:
                self.color = name
            sx += each + 1
        y += 22
        g.text(x, y + 2, "Posição", INK, True)
        self.position = ui.segmented("pos", field_x, y + 1, field_w - 1, list(captions.POSITIONS), self.position)
        y += 21
        self.bold = ui.checkbox("bold", field_x, y, "Negrito", self.bold)

    def draw_text_list(self, ui):
        g = ui.g
        x, y, w = 272, 22, 232
        g.text(x, y - 1, "Texto da legenda", INK, True)
        for i, code in enumerate(LANGS):
            bw = 28
            bx = x + w - (len(LANGS) - i) * (bw + 1)
            enabled = not self.job and not self.burning
            ui.button(("lang", code), bx, y - 2, bw, 13, code, on=lambda c=code: self.set_lang(c), selected=self.lang == code,
                      enabled=enabled or self.lang == code)
        y += 14
        text, color = self.status
        g.text(x, y, fit(text, w), color)
        y += 12
        if self.job or self.burning:
            g.blocks(x, y, w, 7, self.progress)
        else:
            g.rect(x, y, w, 7, fill=WHITE, line=INK)
            if self.generated:
                g.rect(x + 1, y + 1, w - 2, 5, fill=GREEN)
        y += 11
        list_h = self.visible_rows() * ROW + 2
        g.rect(x, y, w - 11, list_h, fill=WHITE, line=INK)
        rows = self.visible_rows()
        if ui.wheel and ui.over(x, y, w, list_h):
            self.scroll += ui.wheel
        self.scroll = ui.scrollbar("seg-scroll", x + w - 12, y, list_h, max(len(self.fields), 1), rows, self.scroll)
        self.scroll = max(0, min(max(0, len(self.fields) - rows), self.scroll))
        for i in range(self.scroll, min(len(self.fields), self.scroll + rows)):
            ry = y + 1 + (i - self.scroll) * ROW
            selected = i == self.current
            if selected:
                g.rect(x + 1, ry, w - 13, ROW, fill=LCD_HI)
            g.text(x + 4, ry + 3, clock(self.segments[i].start), INK if selected else DARK)
            key = ("seg", i)
            if ui.over(x + 34, ry, w - 48, ROW) and ui.pressed:
                self.current = i
            if ui.focus == key:
                self.current = i
            ui.entry(key, x + 34, ry + 1, w - 48, ROW - 2, self.fields[i], flat=True)
        by = self.h - 30
        editable = bool(self.fields) and not self.job and not self.burning
        ui.button("redo", x, by, 58, 17, "Refazer", on=self.start_transcription, enabled=not self.job and not self.burning)
        ui.button("cancel", x + 64, by, 58, 17, "Cancelar" if self.job else "Fechar", on=self.cancel_work)
        ui.button("generate", x + 128, by, w - 129, 17, "Gerar de novo" if self.generated else "Gerar vídeo", on=self.start_burn,
                  enabled=editable, tone=AMBER, bold=True)

    def draw_font_list(self, ui):
        g = ui.g
        g.pattern(0, 0, W, self.h, INK, "50")
        w, h = 260, min(286, self.h - 28)
        x, y = (W - w) // 2, (self.h - h) // 2
        ui.panel(x, y, w, h, "Escolha a fonte", close=self.close_fonts)
        g.text(x + 8, y + 18, "Buscar", INK, True)
        ui.entry("font-filter", x + 52, y + 16, w - 60, 15, self.font_filter)
        needle = self.font_filter.text.casefold().strip()
        names = [f for f in self.families if needle in f.casefold()]
        lx, ly, lw, lh = x + 8, y + 36, w - 16, h - 44
        g.rect(lx, ly, lw - 11, lh, fill=WHITE, line=INK)
        rows = (lh - 2) // 13
        if ui.wheel:
            self.font_scroll += ui.wheel * 2
        self.font_scroll = ui.scrollbar("font-scroll", lx + lw - 12, ly, lh, max(len(names), 1), rows, self.font_scroll)
        self.font_scroll = max(0, min(max(0, len(names) - rows), self.font_scroll))
        for i, name in enumerate(names[self.font_scroll:self.font_scroll + rows]):
            ry = ly + 1 + i * 13
            hover, held, clicked = ui.clickable(("font", name), lx + 1, ry, lw - 13, 13)
            selected = name == self.font
            if selected or hover:
                g.rect(lx + 1, ry, lw - 13, 13, fill=INK if selected else LCD_HI)
            g.text(lx + 5, ry + 1, fit(name, lw - 22), WHITE if selected else INK)
            if clicked:
                self.font = name
                ui.later(self.close_fonts)

    def close_fonts(self):
        self.font_open = False
        self.host.focus = None
        self.host.invalidate()

    def set_lang(self, code):
        self.lang = code
        self.host.invalidate()

    # ------------------------------------------------ transcrição
    def set_status(self, text, color=DARK):
        self.status = (text, color)

    def start_transcription(self):
        if self.job or self.burning:
            return
        self.pill_task = self.app.pill.begin("Ouvindo o vídeo")
        self.job = Job()
        self.progress = 0
        self.generated = False
        first = not captions.model_ready()
        self.set_status("Baixando o modelo de voz (só uma vez)…" if first else "Ouvindo o vídeo…")
        job, language = self.job, captions.LANGUAGES[LANGS[self.lang]]
        self.app.pool.submit(self.transcribe_worker, job, language)
        self.host.invalidate()

    def transcribe_worker(self, job, language):
        def report(stage, fraction):
            self.ui_call(self.show_stage, stage, fraction)
        try:
            segments = captions.transcribe(self.path, language, job, report)
            self.ui_call(self.transcribed, segments)
        except Cancelled:
            self.ui_call(self.work_cancelled)
        except Exception as error:
            self.ui_call(self.work_failed, str(error))

    def finish_pill(self, ok):
        if self.pill_task is not None:
            self.app.pill.end(self.pill_task, ok)
            self.pill_task = None

    def show_stage(self, stage, fraction):
        self.progress = fraction
        percent = int(fraction * 100)
        if stage == "download":
            self.set_status(f"Baixando o modelo (só uma vez)… {percent}%")
        else:
            if self.pill_task is not None:
                self.app.pill.update(self.pill_task, fraction)
            self.set_status(f"Ouvindo o vídeo… {percent}%")

    def transcribed(self, segments):
        self.finish_pill(True)
        self.job = None
        self.progress = 1
        if segments:
            self.set_status(f"{len(segments)} frases. Clique pra corrigir.", TEALD)
        else:
            duration = captions.media.probe(self.path)["duration"] or 5
            segments = [captions.Segment(0, duration, "")]
            self.set_status("Não achei fala. Digite a legenda.", RED)
        self.segments = list(segments)
        self.fields = [TextField(s.text) for s in self.segments]
        self.current = self.scroll = 0
        self.host.focus = None

    def work_cancelled(self):
        self.finish_pill(None)
        self.job = None
        self.set_status("Cancelado.")

    def work_failed(self, message):
        self.finish_pill(False)
        self.job = None
        self.set_status(message[:60], RED)

    def cancel_work(self):
        if self.job:
            self.job.cancel()
            self.set_status("Cancelando…")
            self.host.invalidate()
        else:
            self.close()

    # ------------------------------------------------ prévia real do vídeo
    def style(self):
        return captions.Style(font=self.font, size=int(self.size), color=self.color, position=self.position, bold=self.bold)

    def watch_preview(self):
        if self.segments:
            index = min(self.current, len(self.segments) - 1)
            segment = self.segments[index]
            text = self.fields[index].text.strip()
            at = segment.start + (segment.end - segment.start) / 2
        else:
            text, at = "Sua legenda aparece aqui", 0.5
        key = (at, text, self.style())
        if key == self.preview_key:
            return
        self.preview_key = key
        if self.preview_after:
            self.after_cancel(self.preview_after)
        self.preview_after = self.after(170, self.render_preview, at, text, self.style())

    def render_preview(self, at, text, style):
        self.preview_after = None
        self.preview_token += 1
        self.preview_pool.submit(self.preview_worker, self.preview_token, at, text, style)

    def preview_worker(self, token, at, text, style):
        if token != self.preview_token:
            return
        try:
            _, _, w, h = self.box
            s = self.app.scale
            png = captions.preview_frame(self.path, at, text, style, max_height=h * s)
            image = Image.open(io.BytesIO(png)).convert("RGB")
            image.thumbnail((w * s, h * s), Image.Resampling.LANCZOS)
            self.ui_call(self.show_preview, token, image)
        except Exception:
            pass

    def show_preview(self, token, image):
        if token == self.preview_token:
            self.preview_image = image

    # ------------------------------------------------ gerar
    def edited_segments(self):
        return [captions.Segment(s.start, s.end, f.text.strip()) for s, f in zip(self.segments, self.fields)]

    def start_burn(self):
        segments = self.edited_segments()
        if not any(s.text for s in segments):
            self.set_status("Escreva pelo menos uma frase.", RED)
            self.host.invalidate()
            return
        self.burning = True
        self.progress = 0
        self.set_status("Gerando o vídeo… 0%")
        self.job = self.app.start_caption(self.path, segments, self.style(), self.burn_progress, self.burn_done)
        self.host.invalidate()

    def burn_progress(self, fraction):
        self.ui_call(self.show_burn, fraction)

    def show_burn(self, fraction):
        self.progress = fraction
        self.set_status(f"Gerando o vídeo… {int(fraction * 100)}%")

    def burn_done(self, ok, message):
        self.ui_call(self.after_burn, ok, message)

    def after_burn(self, ok, message):
        self.burning = False
        self.job = None
        self.generated = bool(ok)
        self.set_status(message, TEALD if ok else RED if ok is False else DARK)

    def close(self):
        if self.job and not self.burning:
            self.job.cancel()
            self.finish_pill(None)
        self.alive = False
        self.host.destroy()
        self.preview_token += 1
        if self.preview_after:
            try:
                self.after_cancel(self.preview_after)
            except tk.TclError:
                pass
        self.preview_pool.shutdown(wait=False, cancel_futures=True)
        callback = self.on_close_cb
        self.destroy()
        if callback:
            callback()
