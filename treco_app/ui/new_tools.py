"""Janelas das ferramentas novas: BPM e tom, cortar silêncios, limpar a voz, páginas do PDF, tarja,
assinatura, arquivos repetidos, Lupa de espaço, Pasta mágica e conta-gotas."""
import datetime
import os
import subprocess
import threading
import time
from tkinter import filedialog

from PIL import Image

from ..core import prefs
from ..core.files import human_size
from ..core.i18n import english, tr
from ..core.log import log_error
from ..core.paths import MAC
from ..modules import audio_tools, pdftools
from . import mascot
from .pixel import AMBER, BLUE, CREAM, DARK, GRAY, INK, RED, SKY, WHITE, fit, text_width
from .tool_dialogs import ToolDialog
from .toolkit import TextField
from .utility_dialogs import BackgroundDialog


def copy_text(win, text):
    win.clipboard_clear()
    win.clipboard_append(text)


def reveal(path):
    if MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def ask_folder(app, title):
    return filedialog.askdirectory(title=tr(title), **app.dialog_owner()) or None


# ================================================================ BPM e tom
class TempoDialog(BackgroundDialog):
    """Ouve cada música e diz o andamento (BPM) e o tom."""

    ROW = 48

    def __init__(self, app, paths):
        self.paths = paths[:8]
        super().__init__(app, "BPM e tom", 380, 62 + self.ROW * len(self.paths) + 34)
        self.results = {}
        self.copied = False
        self.host.frame()
        self.work(self.analyze)

    def analyze(self):
        out = {}
        for path in self.paths:
            try:
                out[path] = audio_tools.tempo_and_key(path)
            except Exception as e:
                out[path] = {"error": str(e)}
            self.ui_call(self.partial, dict(out))
        return out

    def partial(self, out):
        self.results = out

    def finish(self, value, error):
        super().finish(value, error)
        if value:
            self.results = value

    def summary(self):
        lines = []
        for path in self.paths:
            r = self.results.get(path) or {}
            if r.get("bpm"):
                lines.append(f"{os.path.basename(path)}: {round(r['bpm'])} BPM, {r.get('key') or '?'}")
        return "\n".join(lines)

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        g.text(x, y, "Andamento e tom de cada música." if len(self.paths) > 1 else "Andamento e tom da música.", DARK)
        y += 18
        for path in self.paths:
            r = self.results.get(path)
            g.text(x, y, fit(os.path.basename(path), w, True), INK, True)
            if r is None:
                g.barber(x, y + 17, 150, 9, int(time.monotonic() * 10), BLUE)
                g.text(x + 158, y + 17, "Ouvindo…", DARK)
            elif r.get("error"):
                g.text(x, y + 16, fit(r["error"], w), RED)
            else:
                bpm = round(r["bpm"]) if r.get("bpm") else None
                text = f"{bpm}" if bpm else "?"
                g.text(x, y + 13, text, BLUE, True, 2)
                tx = x + g.text_w(text, True, 2) + 4
                g.text(tx, y + 20, "BPM", INK, True)
                key = r.get("key") or "?"
                kx = x + 120
                g.text(kx, y + 13, fit(key, w - 120, True), INK, True, 1.6)
                extra = []
                if bpm:
                    extra.append(f"{tr('metade')} {round(r['bpm'] / 2)} · {tr('dobro')} {round(r['bpm'] * 2)}")
                if r.get("alt"):
                    extra.append(f"{tr('ou')} {r['alt']}")
                g.text(x, y + 31, fit("   ".join(extra), w), DARK)
            g.hline(x, y + self.ROW - 4, w, GRAY)
            y += self.ROW
        by = self.dh - 31
        ui.button("copy", x, by, 120, 17, "Copiado!" if self.copied else "Copiar resultado", on=self.copy,
                  enabled=bool(self.summary()), tone=AMBER, bold=True)
        ui.button("close", x + 128, by, 70, 17, "Fechar", on=self.close)
        if mascot.enabled():
            pose = "pensando" if self.working else "comemorando"
            mascot.draw(g, pose, self.dw - 12 - mascot.width(pose, 40, g.s), self.dh - 46, 40)
        if self.working:
            self.after(120, self.host.invalidate)

    def copy(self):
        copy_text(self, self.summary())
        self.copied = True


# ================================================================ cortar silêncios
class SilenceDialog(ToolDialog):
    """Tira as pausas da fala. A folga deixa um respiro antes e depois de cada frase, para não comer letras."""

    def __init__(self, app, paths):
        super().__init__(app, "Cortar silêncios", 380, 214)
        self.paths = paths
        self.gap = prefs.get("silence_gap") if prefs.get("silence_gap") in audio_tools.GAPS else "Média"
        self.pause = prefs.get("silence_pause") if prefs.get("silence_pause") in audio_tools.PAUSES else "0,6 s"
        self.silences = None
        self.duration = 0
        self.host.frame()
        threading.Thread(target=self.measure, daemon=True).start()

    def measure(self):
        try:
            from ..modules import media
            duration = media.probe(self.paths[0])["duration"] or 0
            silences = audio_tools.find_silences(self.paths[0])
        except Exception as e:
            log_error("silêncios", e)
            duration, silences = 0, []
        self.ui_call(self.measured, duration, silences)

    def measured(self, duration, silences):
        self.duration, self.silences = duration, silences

    @staticmethod
    def clock(seconds):
        seconds = int(round(seconds))
        return f"{seconds // 60}min{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        g.text(x, y, "Folga antes e depois da fala", INK, True)
        g.text(x, y + 13, "Mais folga = mais natural, sem comer o fim das palavras.", DARK)
        self.gap = ui.segmented("gap", x, y + 28, w, list(audio_tools.GAPS), self.gap)
        y += 52
        g.text(x, y, "Cortar pausas maiores que", INK, True)
        self.pause = ui.segmented("pause", x, y + 15, w, list(audio_tools.PAUSES), self.pause)
        y += 42
        # prévia: o que fica (azul) e o que sai (cinza), no primeiro arquivo
        g.rect(x, y, w, 14, fill=WHITE, line=INK)
        if self.silences is None:
            g.barber(x + 1, y + 1, w - 2, 12, int(time.monotonic() * 10), SKY)
            g.text(x, y + 18, "Ouvindo onde estão as pausas…", DARK)
            self.after(120, self.host.invalidate)
        elif self.duration:
            parts = audio_tools.keep_parts(self.silences, self.duration, audio_tools.GAPS[self.gap],
                                           audio_tools.PAUSES[self.pause])
            g.rect(x + 1, y + 1, w - 2, 12, fill=GRAY)
            for a, b in parts:
                left = x + 1 + int(a / self.duration * (w - 2))
                right = x + 1 + int(b / self.duration * (w - 2))
                g.rect(left, y + 1, max(1, right - left), 12, fill=BLUE)
            kept = sum(b - a for a, b in parts)
            name = fit(os.path.basename(self.paths[0]), 140)
            g.text(x, y + 18, f"{name}: {tr('fica')} {self.clock(kept)} {tr('de')} {self.clock(self.duration)} "
                              f"({tr('tira')} {self.clock(self.duration - kept)})", DARK)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        label = "Cortar" if len(self.paths) == 1 else f"{tr('Cortar')} {len(self.paths)}"
        ui.button("go", self.dw - 106, by, 88, 17, label, on=self.apply, tone=AMBER, bold=True)

    def apply(self):
        prefs.put("silence_gap", self.gap)
        prefs.put("silence_pause", self.pause)
        self.app.run_quick(self.paths, "silence", {"gap": audio_tools.GAPS[self.gap],
                                                   "pause": audio_tools.PAUSES[self.pause]})
        self.accept()


# ================================================================ limpar a voz
class VoiceDialog(ToolDialog):
    def __init__(self, app, paths):
        super().__init__(app, "Limpar a voz", 360, 196)
        self.paths = paths
        saved = prefs.get("voice_clean") or {}
        self.hiss = saved.get("hiss", True)
        self.noise = saved.get("noise", True)
        self.echo = saved.get("echo", False)
        self.level = saved.get("level") if saved.get("level") in audio_tools.STRENGTH else "Média"
        self.host.frame()

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        g.text(x, y, "O que tirar da gravação", INK, True)
        y += 17
        self.hiss = ui.checkbox("hiss", x, y, "Chiado", self.hiss)
        g.text(x + 120, y + 1, "som fino e constante", DARK)
        self.noise = ui.checkbox("noise", x, y + 17, "Ruído de fundo", self.noise)
        g.text(x + 120, y + 18, "ventilador, ar, rua", DARK)
        self.echo = ui.checkbox("echo", x, y + 34, "Eco da sala", self.echo)
        g.text(x + 120, y + 35, "diminui, mas não some todo", DARK)
        y += 58
        g.text(x, y, "Força", INK, True)
        self.level = ui.segmented("level", x + 50, y - 2, w - 50, list(audio_tools.STRENGTH), self.level)
        g.text(x, y + 18, "Forte demais pode deixar a voz abafada.", DARK)
        by = self.dh - 31
        ui.button("cancel", x, by, 70, 17, "Cancelar", on=self.close)
        ui.button("go", self.dw - 106, by, 88, 17, "Limpar", on=self.apply, tone=AMBER, bold=True,
                  enabled=self.hiss or self.noise or self.echo)

    def apply(self):
        prefs.put("voice_clean", {"hiss": self.hiss, "noise": self.noise, "echo": self.echo, "level": self.level})
        self.app.run_quick(self.paths, "voice", {"hiss": self.hiss, "noise": self.noise, "echo": self.echo,
                                                 "level": audio_tools.STRENGTH[self.level]})
        self.accept()


# ================================================================ peças comuns dos PDFs
class PageImages:
    """Imagens das páginas, feitas aos poucos num fio separado para a janela não travar."""

    def __init__(self, dialog, path, width):
        self.dialog, self.path, self.width = dialog, path, width
        self.images = {}
        self.scales = {}
        self.wanted = []
        self.lock = threading.Lock()
        self.thread = None

    def get(self, index):
        if index in self.images:
            return self.images[index]
        with self.lock:
            if index not in self.wanted:
                self.wanted.append(index)
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
        return None

    def run(self):
        while self.dialog.alive:
            with self.lock:
                if not self.wanted:
                    return
                index = self.wanted.pop(0)
            try:
                image, scale = pdftools.render(self.path, index, self.width)
                self.images[index], self.scales[index] = image, scale
            except Exception as e:
                log_error("página do PDF", e)
                self.images[index] = Image.new("RGB", (self.width, int(self.width * 1.4)), (240, 240, 240))
                self.scales[index] = 1
            self.dialog.ui_call(lambda: None)


def fit_image(image, w, h):
    image = image.copy()
    image.thumbnail((w, h), Image.Resampling.LANCZOS)
    return image


# ================================================================ organizar páginas
class PagesDialog(ToolDialog):
    THUMB_W, THUMB_H, GAP = 78, 104, 10

    def __init__(self, app, path):
        super().__init__(app, f"{tr('Páginas')} · {os.path.basename(path)}", 540, 420)
        self.path = path
        self.count = pdftools.page_count(path)
        self.order = [[i, 0] for i in range(self.count)]
        self.selected = set()  # posições na ordem atual
        self.scroll = 0
        self.pages = PageImages(self, path, self.THUMB_W * app.scale * 2)
        self.cache = {}
        self.host.frame()

    def thumb(self, index, turn):
        key = (index, turn)
        if key not in self.cache:
            image = self.pages.get(index)
            if image is None:
                return None
            if turn:
                image = image.rotate(-turn, expand=True)
            self.cache[key] = fit_image(image, (self.THUMB_W - 6) * self.host.s, (self.THUMB_H - 6) * self.host.s)
        return self.cache[key]

    def body(self, ui):
        g = ui.g
        x, y, w = 14, 22, self.dw - 28
        g.text(x, y + 2, "Clique para escolher páginas. Depois gire, mude de lugar ou tire.", DARK)
        top = y + 18
        height = self.dh - top - 62
        g.rect(x, top, w, height, fill=WHITE, line=INK)
        cols = max(1, (w - 14) // (self.THUMB_W + self.GAP))
        row_h = self.THUMB_H + 18
        rows = -(-len(self.order) // cols)
        visible = max(1, (height - 8) // row_h)
        if ui.wheel and ui.over(x, top, w, height):
            self.scroll += ui.wheel
        self.scroll = ui.scrollbar("pg", x + w - 12, top, height, max(1, rows), visible, self.scroll)
        waiting = False
        left0 = x + 8 + ((w - 14) - cols * (self.THUMB_W + self.GAP) + self.GAP) // 2
        for pos in range(self.scroll * cols, min(len(self.order), (self.scroll + visible) * cols)):
            index, turn = self.order[pos]
            r, c = divmod(pos - self.scroll * cols, cols)
            tx = left0 + c * (self.THUMB_W + self.GAP)
            ty = top + 8 + r * row_h
            chosen = pos in self.selected
            over, held, clicked = ui.clickable(("page", pos), tx, ty, self.THUMB_W, self.THUMB_H + 14)
            g.rect(tx + 3, ty + 3, self.THUMB_W, self.THUMB_H, fill=BLUE if chosen else INK)
            g.rect(tx, ty, self.THUMB_W, self.THUMB_H, fill=CREAM, line=BLUE if chosen or over else INK)
            image = self.thumb(index, turn)
            if image is None:
                waiting = True
            else:
                ix = tx + (self.THUMB_W - image.width // g.s) // 2
                iy = ty + (self.THUMB_H - image.height // g.s) // 2
                g.put(image, ix, iy)
            if chosen:
                g.rect(tx, ty, self.THUMB_W, self.THUMB_H, line=BLUE)
                g.rect(tx + 1, ty + 1, self.THUMB_W - 2, self.THUMB_H - 2, line=BLUE)
            label = f"{pos + 1}" + (f"  ({tr('era')} {index + 1})" if index != pos else "")
            g.center(tx, ty + self.THUMB_H + 4, self.THUMB_W, label, BLUE if chosen else INK, chosen)
            if clicked:
                (self.selected.discard if chosen else self.selected.add)(pos)
        if waiting:
            self.after(150, self.host.invalidate)
        by = top + height + 8
        some = bool(self.selected)
        bw = 74
        ui.button("left", x, by, bw, 18, "← Girar", on=lambda: self.turn(-90), enabled=some)
        ui.button("right", x + bw + 4, by, bw, 18, "Girar →", on=lambda: self.turn(90), enabled=some)
        ui.button("back", x + 2 * (bw + 4), by, bw, 18, "← Antes", on=lambda: self.move(-1), enabled=some)
        ui.button("fwd", x + 3 * (bw + 4), by, bw, 18, "Depois →", on=lambda: self.move(1), enabled=some)
        ui.button("drop", x + 4 * (bw + 4), by, bw, 18, "Tirar", on=self.remove, enabled=some)
        ui.button("all", x + 5 * (bw + 4), by, w - 5 * (bw + 4), 18,
                  "Nenhuma" if len(self.selected) == len(self.order) else "Todas", on=self.toggle_all)
        by += 26
        g.text(x, by + 4, f"{len(self.order)} {tr('de')} {self.count} {tr('páginas')}", DARK)
        ui.button("reset", x + 120, by, 90, 17, "Desfazer tudo", on=self.reset)
        ui.button("save", self.dw - 126, by, 110, 17, "Salvar PDF novo", on=self.save, tone=AMBER, bold=True,
                  enabled=bool(self.order) and self.changed())

    def changed(self):
        return self.order != [[i, 0] for i in range(self.count)]

    def toggle_all(self):
        self.selected = set() if len(self.selected) == len(self.order) else set(range(len(self.order)))

    def turn(self, degrees):
        for pos in self.selected:
            self.order[pos][1] = (self.order[pos][1] + degrees) % 360

    def move(self, step):
        chosen = sorted(self.selected, reverse=step > 0)
        new = set()
        for pos in chosen:
            to = pos + step
            if 0 <= to < len(self.order) and to not in new:
                self.order[pos], self.order[to] = self.order[to], self.order[pos]
                new.add(to)
            else:
                new.add(pos)
        self.selected = new

    def remove(self):
        self.order = [item for pos, item in enumerate(self.order) if pos not in self.selected]
        self.selected = set()

    def reset(self):
        self.order = [[i, 0] for i in range(self.count)]
        self.selected = set()

    def save(self):
        self.app.run_quick([self.path], "pages", {"pages": [tuple(item) for item in self.order]})
        self.accept()


# ================================================================ prévia de página com marcações
class PageView:
    """Uma página grande na janela, com navegação. Converte pontos da tela em pontos do PDF."""

    def __init__(self, dialog, path, box):
        self.dialog, self.path = dialog, path
        self.box = box  # (x, y, w, h) na janela
        self.count = pdftools.page_count(path)
        self.index = 0
        self.pages = PageImages(dialog, path, box[2] * dialog.host.s)
        self.place = None  # (x, y, largura, escala) onde a página foi desenhada

    def draw(self, ui):
        g = ui.g
        x, y, w, h = self.box
        g.rect(x + 3, y + 3, w, h, fill=INK)
        g.rect(x, y, w, h, fill=(232, 232, 232), line=INK)
        image = self.pages.get(self.index)
        if image is None:
            g.center(x, y + h // 2, w, "Abrindo a página…", DARK)
            self.dialog.after(150, self.dialog.host.invalidate)
            self.place = None
            return
        shown = fit_image(image, (w - 4) * g.s, (h - 4) * g.s)
        px = x + (w - shown.width // g.s) // 2
        py = y + (h - shown.height // g.s) // 2
        g.put(shown, px, py)
        # pixels lógicos por ponto do PDF
        self.place = (px, py, shown.width / g.s, self.pages.scales[self.index] * shown.width / image.width / g.s)

    def nav(self, ui, x, y, w):
        g = ui.g
        ui.button("prev", x, y, 26, 17, "←", on=lambda: self.go(-1), enabled=self.index > 0)
        g.center(x + 28, y + 4, w - 56, f"{tr('Página')} {self.index + 1} {tr('de')} {self.count}", INK, True)
        ui.button("next", x + w - 26, y, 26, 17, "→", on=lambda: self.go(1), enabled=self.index < self.count - 1)

    def go(self, step):
        self.index = max(0, min(self.count - 1, self.index + step))

    def to_pdf(self, mx, my):
        px, py, pw, scale = self.place
        return (mx - px) / scale, (my - py) / scale

    def to_screen(self, rect):
        px, py, pw, scale = self.place
        x0, y0, x1, y1 = rect
        return px + x0 * scale, py + y0 * scale, px + x1 * scale, py + y1 * scale

    def inside(self, mx, my):
        if not self.place:
            return False
        px, py, pw, scale = self.place
        image = self.pages.images.get(self.index)
        ph = image.height / image.width * pw if image else 0
        return px <= mx < px + pw and py <= my < py + ph


# ================================================================ tarja preta
class RedactDialog(ToolDialog):
    def __init__(self, app, path):
        super().__init__(app, f"{tr('Tarja preta')} · {os.path.basename(path)}", 560, 470)
        self.path = path
        self.view = PageView(self, path, (14, 24, 300, 400))
        self.boxes = {}  # página -> [retângulos em pontos]
        self.kinds = {"CPF", "CNPJ", "E-mail", "Telefone"}
        self.words = TextField("", 200)
        self.start = None
        self.busy = False
        self.message = None
        self.host.frame()

    def body(self, ui):
        g = ui.g
        view = self.view
        view.draw(ui)
        if view.place:
            for rect in self.boxes.get(view.index, []):
                x0, y0, x1, y1 = view.to_screen(rect)
                g.rect(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)), fill=INK)
            # arrastar para desenhar uma tarja; clicar numa tarja tira
            inside = view.inside(ui.mx, ui.my)
            if ui.pressed and inside:
                self.start = (ui.mx, ui.my)
            if self.start and ui.down:
                x0, y0 = self.start
                g.rect(min(x0, ui.mx), min(y0, ui.my), abs(ui.mx - x0) + 1, abs(ui.my - y0) + 1, line=RED)
            if self.start and ui.released:
                x0, y0 = self.start
                self.start = None
                if abs(ui.mx - x0) < 3 and abs(ui.my - y0) < 3:
                    self.remove_at(*view.to_pdf(ui.mx, ui.my))
                else:
                    a, b = view.to_pdf(min(x0, ui.mx), min(y0, ui.my))
                    c, d = view.to_pdf(max(x0, ui.mx), max(y0, ui.my))
                    self.boxes.setdefault(view.index, []).append((a, b, c, d))
        view.nav(ui, 14, 432, 300)
        # coluna da direita
        x, y, w = 330, 24, self.dw - 344
        g.text(x, y, "Achar sozinho", INK, True)
        y += 16
        for n, kind in enumerate(pdftools.PATTERNS):
            cx, cy = x + (n % 2) * (w // 2), y + (n // 2) * 16
            on = ui.checkbox(("k", kind), cx, cy, kind, kind in self.kinds)
            (self.kinds.add if on else self.kinds.discard)(kind)
        y += 52
        g.text(x, y, "E também estas palavras:", DARK)
        focused = ui.entry("words", x, y + 13, w, 19, self.words)
        if not self.words.text and not focused:
            g.text(x + 6, y + 18, "nome, endereço…", GRAY)
        y += 38
        ui.button("find", x, y, w, 19, "Procurando…" if self.busy else "Achar e marcar", on=self.find,
                  enabled=not self.busy and bool(self.kinds or self.words.text.strip()), bold=True)
        y += 30
        g.text(x, y, "Ou arraste na página", INK, True)
        g.text(x, y + 13, "para cobrir à mão.", DARK)
        g.text(x, y + 26, "Clique numa tarja para tirar.", DARK)
        y += 50
        total = sum(len(v) for v in self.boxes.values())
        pages = len([v for v in self.boxes.values() if v])
        g.text(x, y, f"{total} {tr('tarjas')} · {pages} {tr('páginas')}" if total else "Nenhuma tarja ainda", BLUE if total else DARK, bool(total))
        if self.message:
            g.text(x, y + 14, fit(self.message, w), DARK)
        ui.button("clear", x, y + 30, w, 17, "Tirar todas", on=self.clear, enabled=bool(total))
        by = self.dh - 50
        g.text(x, by - 14, "A tarja apaga de verdade:", DARK)
        g.text(x, by - 2, "o texto embaixo some.", DARK)
        ui.button("save", x, by + 16, w, 19, "Salvar com tarja", on=self.save, tone=AMBER, bold=True, enabled=bool(total))

    def remove_at(self, px, py):
        rects = self.boxes.get(self.view.index, [])
        self.boxes[self.view.index] = [r for r in rects if not (r[0] <= px <= r[2] and r[1] <= py <= r[3])]

    def clear(self):
        self.boxes = {}
        self.message = None

    def find(self):
        self.busy = True
        kinds, words = sorted(self.kinds), self.words.text

        def run():
            try:
                found = pdftools.find_text(self.path, kinds, words)
                error = None
            except Exception as e:
                found, error = {}, str(e)
            self.ui_call(self.found, found, error)
        threading.Thread(target=run, daemon=True).start()

    def found(self, found, error):
        self.busy = False
        added = 0
        for index, rects in found.items():
            have = self.boxes.setdefault(index, [])
            for rect in rects:
                if rect not in have:
                    have.append(rect)
                    added += 1
        self.message = error or (f"{added} {tr('achados')}" if added else tr("Não achei nada novo"))
        if found and self.view.index not in found:
            self.view.index = min(found)

    def save(self):
        self.app.run_quick([self.path], "redact", {"boxes": {k: list(v) for k, v in self.boxes.items() if v}})
        self.accept()


# ================================================================ assinatura
class SignDialog(ToolDialog):
    def __init__(self, app, path):
        super().__init__(app, f"{tr('Assinar')} · {os.path.basename(path)}", 560, 470)
        self.path = path
        self.view = PageView(self, path, (14, 24, 300, 400))
        self.view.index = max(0, self.view.count - 1)  # assinatura costuma ir na última página
        self.places = []  # (página, (x0, y0, x1, y1)) em pontos
        self.width = prefs.get("sign_width") or 150
        self.signature = self.load_signature()
        self.drawing = None  # traços enquanto desenha
        self.cert = prefs.get("sign_cert")
        if self.cert and not os.path.isfile(self.cert):
            self.cert = None
        self.cert_on = bool(self.cert) and pdftools.can_certify()
        self.password = TextField("", 120)
        self.cert_name = None
        self.cert_error = None
        self.host.frame()

    # --- assinatura guardada
    @staticmethod
    def signature_file():
        return os.path.join(pdftools.signature_folder(), "assinatura.png")

    def load_signature(self):
        try:
            return Image.open(self.signature_file()).convert("RGBA")
        except OSError:
            return None

    def keep(self, image):
        self.signature = pdftools.clean_signature(image)
        self.signature.save(self.signature_file())

    def pick_image(self):
        path = filedialog.askopenfilename(title=tr("Foto ou imagem da assinatura"), **self.app.dialog_owner(),
                                          filetypes=[(tr("Imagens"), "*.png *.jpg *.jpeg *.heic *.webp")])
        if path:
            try:
                from ..modules.images import ensure_heif
                ensure_heif()
                self.keep(Image.open(path))
            except Exception as e:
                log_error("assinatura", e)
                self.cert_error = tr("Não consegui abrir a imagem")

    def pick_cert(self):
        path = filedialog.askopenfilename(title=tr("Certificado digital (.pfx ou .p12)"), **self.app.dialog_owner(),
                                          filetypes=[(tr("Certificado"), "*.pfx *.p12")])
        if path:
            self.cert, self.cert_name, self.cert_error = path, None, None
            self.cert_on = True
            self.host.focus = "pw"
            prefs.put("sign_cert", path)

    # --- desenho
    def sig_size(self):
        """Tamanho da assinatura na página, em pontos do PDF."""
        if not self.signature:
            return 0, 0
        return self.width, self.width * self.signature.height / self.signature.width

    def body(self, ui):
        g = ui.g
        view = self.view
        view.draw(ui)
        if view.place:
            sw, sh = self.sig_size()
            for index, rect in self.places:
                if index == view.index and self.signature:
                    x0, y0, x1, y1 = view.to_screen(rect)
                    shown = self.signature.resize((max(1, int((x1 - x0) * g.s)), max(1, int((y1 - y0) * g.s))),
                                                  Image.Resampling.LANCZOS)
                    g.put(shown, int(x0), int(y0))
                    g.rect(int(x0) - 1, int(y0) - 1, int(x1 - x0) + 2, int(y1 - y0) + 2, line=BLUE)
            if self.signature and view.inside(ui.mx, ui.my) and self.drawing is None:
                if ui.released:
                    px, py = view.to_pdf(ui.mx, ui.my)
                    hit = [p for p in self.places if p[0] == view.index and p[1][0] <= px <= p[1][2]
                           and p[1][1] <= py <= p[1][3]]
                    if hit:
                        self.places.remove(hit[0])
                    else:
                        self.places.append((view.index, (px - sw / 2, py - sh / 2, px + sw / 2, py + sh / 2)))
                elif not ui.down:  # mostra onde vai cair
                    x0, y0, x1, y1 = view.to_screen((0, 0, sw, sh))
                    pw, ph = int(x1 - x0), int(y1 - y0)
                    g.rect(ui.mx - pw // 2, ui.my - ph // 2, pw, ph, line=BLUE)
        view.nav(ui, 14, 432, 300)
        x, y, w = 330, 24, self.dw - 344
        g.text(x, y, "Sua assinatura", INK, True)
        y += 15
        pad_h = 80
        g.rect(x + 2, y + 2, w, pad_h, fill=INK)
        g.rect(x, y, w, pad_h, fill=WHITE, line=BLUE if self.drawing is not None else INK)
        if self.drawing is not None:
            self.draw_pad(ui, x, y, w, pad_h)
        elif self.signature:
            shown = fit_image(self.signature, (w - 12) * g.s, (pad_h - 12) * g.s)
            g.put(shown, x + (w - shown.width // g.s) // 2, y + (pad_h - shown.height // g.s) // 2)
        else:
            g.center(x, y + pad_h // 2 - 5, w, "Desenhe ou use uma foto", DARK)
        y += pad_h + 8
        half = (w - 6) // 2
        if self.drawing is not None:
            ui.button("clr", x, y, half, 18, "Apagar", on=lambda: setattr(self, "drawing", []))
            ui.button("ok", x + half + 6, y, half, 18, "Pronto", on=self.finish_drawing, tone=AMBER, bold=True,
                      enabled=bool(self.drawing))
        else:
            ui.button("draw", x, y, half, 18, "Desenhar", on=lambda: setattr(self, "drawing", []))
            ui.button("img", x + half + 6, y, half, 18, "Usar foto…", on=self.pick_image)
        y += 28
        g.text(x, y, "Tamanho", INK, True)
        self.width = ui.slider("w", x + 56, y, w - 56, self.width, 70, 260)
        y += 20
        g.text(x, y, "Clique na página para pôr.", DARK)
        g.text(x, y + 12, "Clique de novo para tirar.", DARK)
        y += 32
        g.hline(x, y, w, GRAY)
        y += 8
        g.text(x, y, "Certificado digital (opcional)", INK, True)
        y += 14
        if not self.cert:
            for line in ("Tem certificado A1 (.pfx ou .p12)?", "Escolha o arquivo e o PDF sai",
                         "certificado: qualquer leitor de PDF", "mostra quem assinou."):
                g.text(x, y, line, DARK)
                y += 12
            ui.button("pfx", x, y + 4, w, 18, "Escolher arquivo…", on=self.pick_cert,
                      enabled=pdftools.can_certify())
        else:
            self.cert_on = ui.checkbox("cert", x, y, "Usar o certificado", self.cert_on)
            ui.button("nocert", x + w - 44, y - 1, 44, 14, "Trocar", on=self.pick_cert)
            y += 16
            g.text(x, y, fit(os.path.basename(self.cert), w, True), BLUE if self.cert_on else DARK, True)
            y += 15
            if self.cert_on:
                g.text(x, y + 4, "Senha", DARK)
                ui.entry("pw", x + 44, y, w - 44, 18, self.password, secret=True)
                y += 22
                if self.cert_error:
                    g.text(x, y, fit(self.cert_error, w), RED)
                elif self.cert_name:
                    g.text(x, y, fit(f"{tr('De')}: {self.cert_name}", w), BLUE, True)
                else:
                    g.text(x, y, "A senha não fica guardada.", DARK)
        by = self.dh - 31
        label = f"{tr('Assinar')} ({len(self.places)})" if len(self.places) > 1 else "Assinar"
        ui.button("save", x, by, w, 19, label, on=self.save, tone=AMBER, bold=True,
                  enabled=bool(self.places and self.signature) and (not self.cert_on or bool(self.password.text)))

    def draw_pad(self, ui, x, y, w, h):
        g = ui.g
        self.pad_size = (w, h)
        inside = x <= ui.mx < x + w and y <= ui.my < y + h
        if ui.pressed and inside:
            self.drawing.append([(ui.mx - x, ui.my - y)])
        elif ui.down and self.drawing and inside:
            stroke = self.drawing[-1]
            if stroke[-1] != (ui.mx - x, ui.my - y):
                stroke.append((ui.mx - x, ui.my - y))
        for stroke in self.drawing:
            if len(stroke) == 1:
                g.rect(x + stroke[0][0], y + stroke[0][1], 2, 2, fill=INK)
            for (a, b), (c, d) in zip(stroke, stroke[1:]):
                g.raw.line(((x + a) * g.s, (y + b) * g.s, (x + c) * g.s, (y + d) * g.s), fill=INK, width=2 * g.s)
        if not self.drawing:
            g.center(x, y + h // 2 - 5, w, "Desenhe aqui com o mouse", GRAY)

    def finish_drawing(self):
        from PIL import ImageDraw
        k = 6  # desenha bem maior: a assinatura fica lisa no PDF
        w, h = getattr(self, "pad_size", (220, 80))
        image = Image.new("RGB", (w * k, h * k), "white")
        d = ImageDraw.Draw(image)
        for stroke in self.drawing:
            points = [(px * k, py * k) for px, py in stroke]
            if len(points) == 1:
                d.ellipse((points[0][0] - k, points[0][1] - k, points[0][0] + k, points[0][1] + k), fill="black")
            else:
                d.line(points, fill="black", width=k * 2, joint="curve")
        self.keep(image)
        self.drawing = None

    def save(self):
        password = self.password.text
        if self.cert_on:
            try:
                self.cert_name = pdftools.certificate_name(self.cert, password)
            except Exception as e:
                self.cert_error = str(e)
                return
        prefs.put("sign_width", self.width)
        self.app.run_quick([self.path], "sign", {"places": list(self.places), "image": self.signature,
                                                 "certificate": self.cert if self.cert_on else None,
                                                 "password": password})
        self.accept()


# ================================================================ prévia de arquivo (repetidos e lupa)
_previews = {}


def preview_image(path, w, h):
    """Miniatura de foto ou PDF, ou None. Feita uma vez e guardada."""
    key = (path, w, h)
    if key in _previews:
        return _previews[key]
    image = None
    try:
        from ..core.formats import kind_of
        kind = kind_of(path)
        if kind == "image":
            from ..modules.images import ensure_heif
            ensure_heif()
            image = fit_image(Image.open(path).convert("RGB"), w, h)
        elif kind == "pdf":
            image = fit_image(pdftools.render(path, 0, w)[0], w, h)
    except Exception:
        image = None
    if len(_previews) > 80:
        _previews.clear()
    _previews[key] = image
    return image


def when(timestamp):
    return datetime.datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y" if not english() else "%Y-%m-%d")


def other_disks():
    """Discos externos e partições que aparecem no Finder (no Mac, dentro de /Volumes)."""
    if not MAC:
        try:
            from ..modules.win_utils import drives
            return drives()
        except Exception:
            return []
    try:
        found = [e.path for e in os.scandir("/Volumes") if e.is_dir(follow_symlinks=False)
                 and not e.name.startswith(".") and os.path.ismount(e.path)
                 and not os.statvfs(e.path).f_flag & os.ST_RDONLY]  # instaladores .dmg abertos não contam
        return sorted(found, key=lambda p: os.statvfs(p).f_blocks * os.statvfs(p).f_frsize, reverse=True)
    except OSError:
        return []


def trash(paths):
    from ..modules import cleanup
    return cleanup.to_trash(paths)


def home_places():
    home = os.path.expanduser("~")
    names = [("Downloads", "Downloads"), ("Mesa", "Desktop"), ("Documentos", "Documents"), ("Imagens", "Pictures"),
             ("Filmes", "Movies"), ("Músicas", "Music")]
    return [(label, os.path.join(home, folder)) for label, folder in names if os.path.isdir(os.path.join(home, folder))]


# ================================================================ arquivos repetidos
class DupesDialog(BackgroundDialog):
    ROW = 18

    def __init__(self, app):
        super().__init__(app, "Arquivos repetidos", 600, 460)
        self.working = False
        self.places = home_places()
        self.chosen = {p for _, p in self.places if os.path.basename(p) in ("Downloads", "Desktop", "Documents")}
        self.extra = []
        self.groups = None
        self.marked = set()
        self.focus_path = None
        self.scroll = 0
        self.status = ("", 0, 0)
        self.cancel = threading.Event()
        self.message = None
        self.host.frame()

    def search(self):
        folders = sorted(self.chosen) + self.extra
        self.cancel = threading.Event()
        self.groups, self.marked, self.scroll, self.message = None, set(), 0, None
        self.work(self.find, folders)

    def find(self, folders):
        from ..modules import space
        return space.find_duplicates(folders, progress=lambda *a: self.ui_call(self.progress, a), cancel=self.cancel)

    def progress(self, status):
        self.status = status

    def finish(self, value, error):
        super().finish(value, error)
        if value is not None:
            self.groups = value
            for group in value:  # já marca as cópias; o mais antigo de cada grupo fica
                self.marked |= set(group["files"][1:])
            if value:
                self.focus_path = value[0]["files"][0]

    def add_folder(self):
        folder = ask_folder(self.app, "Procurar repetidos em…")
        if folder and folder not in self.extra:
            self.extra.append(folder)

    def lines(self):
        rows = []
        for n, group in enumerate(self.groups or []):
            rows.append(("head", n, group))
            for path, mtime in zip(group["files"], group["times"]):
                rows.append(("file", path, mtime, group))
        return rows

    def body(self, ui):
        g = ui.g
        x, y, w = 14, 24, self.dw - 28
        if self.working:
            stage, done, total = self.status
            self.waiting(ui, x, y, w - 60, "Procurando arquivos iguais…")
            if stage == "Olhando":
                g.text(x, y + 36, fit(f"{done} {tr('arquivos olhados')} · {total}", w - 60), DARK)
            elif stage:
                g.text(x, y + 36, f"{tr('Comparando')} {done} {tr('de')} {total}", DARK)
            ui.button("stop", x, y + 56, 90, 17, "Cancelar", on=self.cancel.set)
            if mascot.enabled():
                mascot.draw(g, "pensando", self.dw - 14 - mascot.width("pensando", 70, g.s), y, 70)
            return
        if self.groups is None:
            self.choose(ui, x, y, w)
            return
        self.results(ui, x, y, w)

    def choose(self, ui, x, y, w):
        g = ui.g
        g.text(x, y, "Onde procurar", INK, True)
        g.text(x, y + 13, "Compara o conteúdo de verdade, byte a byte. Nome diferente não engana.", DARK)
        y += 32
        for n, (label, path) in enumerate(self.places):
            cx, cy = x + (n % 3) * 150, y + (n // 3) * 18
            on = ui.checkbox(("pl", path), cx, cy, label, path in self.chosen)
            (self.chosen.add if on else self.chosen.discard)(path)
        y += 18 * (-(-len(self.places) // 3)) + 6
        for folder in self.extra:
            g.text(x, y, fit(f"+ {folder}", w), BLUE, True)
            y += 14
        ui.button("more", x, y + 2, 120, 17, "Outra pasta…", on=self.add_folder)
        ui.button("go", x, y + 30, 160, 20, "Procurar repetidos", on=self.search, tone=AMBER, bold=True,
                  enabled=bool(self.chosen or self.extra))
        if self.error:
            g.text(x, y + 60, fit(str(self.error), w), RED)
        if mascot.enabled():
            mascot.draw(ui.g, "oi", self.dw - 14 - mascot.width("oi", 90, ui.g.s), self.dh - 110, 90)

    def results(self, ui, x, y, w):
        g = ui.g
        groups = self.groups
        if not groups:
            g.text(x, y, "Nenhum arquivo repetido. Tudo organizado!", BLUE, True, 1.2)
            if self.message:
                g.text(x, y + 20, fit(self.message, w), DARK)
            ui.button("again", x, y + 44, 130, 18, "Procurar de novo", on=lambda: setattr(self, "groups", None))
            if mascot.enabled():
                mascot.draw(g, "comemorando", self.dw - 14 - mascot.width("comemorando", 100, g.s), self.dh - 120, 100)
            return
        waste = sum(gr["size"] * (len(gr["files"]) - 1) for gr in groups)
        g.text(x, y, f"{len(groups)} {tr('grupos de cópias')} · {human_size(waste)} {tr('repetidos')}", INK, True)
        list_w = 360
        top = y + 16
        height = (self.dh - top - 66) // self.ROW * self.ROW + 2
        g.rect(x, top, list_w, height, fill=WHITE, line=INK)
        rows = self.lines()
        visible = height // self.ROW
        if ui.wheel and ui.over(x, top, list_w, height):
            self.scroll += ui.wheel * 2
        self.scroll = ui.scrollbar("dl", x + list_w - 12, top, height, max(1, len(rows)), visible, self.scroll)
        lw = list_w - 14
        for n, row in enumerate(rows[self.scroll:self.scroll + visible]):
            ry = top + 1 + n * self.ROW
            if row[0] == "head":
                group = row[2]
                g.rect(x + 1, ry, lw, self.ROW, fill=CREAM)
                g.text(x + 6, ry + 4, f"{len(group['files'])} {tr('iguais')} · {human_size(group['size'])} {tr('cada')}",
                       INK, True)
                continue
            _, path, mtime, group = row
            on = path in self.marked
            over, held, clicked = ui.clickable(("f", path), x + 1, ry, lw, self.ROW)
            if over:
                self.focus_path = path
            tone = BLUE if over or path == self.focus_path else INK
            g.rect(x + 8, ry + 4, 10, 10, fill=RED if on else WHITE, line=tone)
            if on:
                g.icon("x", x + 9, ry + 5, 8, WHITE)
            date = when(mtime)
            g.right(x + lw - 4, ry + 5, date, DARK)
            folder = os.path.basename(os.path.dirname(path))
            g.text(x + 24, ry + 5, fit(f"{os.path.basename(path)}  ·  {folder}", lw - 36 - text_width(date)),
                   GRAY if on else tone, not on)
            g.hline(x + 1, ry + self.ROW - 1, lw, (230, 230, 230))
            if clicked:
                if on:
                    self.marked.discard(path)
                elif all(f in self.marked or f == path for f in group["files"]):
                    self.message = tr("Pelo menos um de cada grupo fica")
                else:
                    self.marked.add(path)
        # prévia
        px, pw = x + list_w + 12, w - list_w - 12
        g.rect(px + 3, top + 3, pw, 170, fill=INK)
        g.rect(px, top, pw, 170, fill=CREAM, line=INK)
        path = self.focus_path
        if path:
            image = preview_image(path, (pw - 10) * g.s, 160 * g.s)
            if image:
                g.put(image, px + (pw - image.width // g.s) // 2, top + (170 - image.height // g.s) // 2)
            else:
                g.icon("doc", px + pw // 2 - 16, top + 60, 32, DARK)
            ty = top + 180
            g.text(px, ty, fit(os.path.basename(path), pw, True), INK, True)
            g.text(px, ty + 13, fit(os.path.dirname(path).replace(os.path.expanduser("~"), "~"), pw), DARK)
            g.text(px, ty + 26, "Vai para o Lixo" if path in self.marked else "Fica", RED if path in self.marked else BLUE, True)
            ui.button("show", px, ty + 44, pw, 17, "Mostrar no Finder" if MAC else "Mostrar na pasta",
                      on=lambda p=path: reveal(p))
        size = sum(os.path.getsize(p) for p in self.marked if os.path.exists(p))
        by = top + height + 6
        g.text(x, by + 2, fit(self.message or tr("Marcados em vermelho vão para o Lixo. Dá para recuperar."), w), DARK)
        by += 18
        ui.button("again", x, by, 110, 20, "Procurar de novo", on=lambda: setattr(self, "groups", None))
        label = f"{tr('Mandar')} {len(self.marked)} {tr('para o Lixo')} ({human_size(size)})" if self.marked else "Nada marcado"
        ui.button("trash", x + 116, by, w - 116, 20, label, on=self.go, enabled=bool(self.marked), tone=AMBER, bold=True)

    def go(self):
        paths = sorted(self.marked)
        moved, failed = trash(paths)
        gone = set(paths) - {p for p in paths if os.path.exists(p)}
        groups = []
        for group in self.groups:
            keep = [(f, t) for f, t in zip(group["files"], group["times"]) if f not in gone]
            if len(keep) > 1:
                groups.append({**group, "files": [f for f, _ in keep], "times": [t for _, t in keep]})
        self.groups = groups
        self.marked -= gone
        self.message = f"{moved} {tr('foram para o Lixo')}" + (f" · {len(failed)} {tr('não deu')}" if failed else "")


# ================================================================ lupa de espaço
class SpaceDialog(BackgroundDialog):
    ROW = 20

    def __init__(self, app):
        super().__init__(app, "Lupa de espaço", 600, 470)
        self.working = False
        self.tree = None
        self.folder = None
        self.marked = set()
        self.scroll = 0
        self.message = None
        self.host.frame()

    def scan(self, root):
        from ..modules import space
        self.tree = space.Tree(root)
        self.folder = self.tree.root
        self.marked, self.scroll, self.message = set(), 0, None
        self.work(self.tree.scan)

    def choose_other(self):
        folder = ask_folder(self.app, "Medir qual pasta?")
        if folder:
            self.scan(folder)

    def spin(self):
        if self.alive and self.working:
            self.host.invalidate()
            self.after(150, self.spin)

    def body(self, ui):
        g = ui.g
        x, y, w = 14, 24, self.dw - 28
        if self.tree is None:
            self.start_screen(ui, x, y, w)
            return
        if self.working:
            tree = self.tree
            self.waiting(ui, x, y, w - 80, "Medindo tudo…")
            g.text(x, y + 36, f"{tree.files:,} {tr('arquivos')}".replace(",", "."), INK, True)
            g.text(x, y + 50, fit(tree.current.replace(os.path.expanduser("~"), "~"), w - 80), DARK)
            ui.button("stop", x, y + 70, 90, 17, "Parar", on=tree.cancel.set)
            if mascot.enabled():
                mascot.draw(g, "trabalhando", self.dw - 14 - mascot.width("trabalhando", 80, g.s), y, 80)
            return
        if self.error:
            self.failed(ui, x, y, w)
            return
        self.browse(ui, x, y, w)

    def start_screen(self, ui, x, y, w):
        from ..modules import space
        g = ui.g
        total, used, free = space.disk_usage(os.path.expanduser("~"))
        g.text(x, y, "Veja o que ocupa espaço, pasta por pasta.", INK, True)
        y += 18
        g.rect(x + 3, y + 3, w, 16, fill=INK)
        g.rect(x, y, w, 16, fill=WHITE, line=INK)
        g.rect(x + 1, y + 1, int((w - 2) * used / total), 14, fill=BLUE)
        g.text(x, y + 22, f"{tr('Disco')}: {human_size(used)} {tr('usados')} · {human_size(free)} {tr('livres')} "
                          f"{tr('de')} {human_size(total)}", DARK)
        y += 46
        home = os.path.expanduser("~")
        ui.button("home", x, y, 200, 22, "Minha pasta pessoal", on=lambda: self.scan(home), tone=AMBER, bold=True)
        g.text(x + 210, y + 6, "o mais comum: fotos, downloads, apps", DARK)
        whole = "/" if MAC else os.path.splitdrive(home)[0] + "\\"  # no Windows, o disco C:
        ui.button("disk", x, y + 28, 200, 20, "Disco inteiro", on=lambda: self.scan(whole))
        g.text(x + 210, y + 33, "demora mais", DARK)
        ui.button("other", x, y + 54, 200, 20, "Outra pasta…", on=self.choose_other)
        disks = other_disks()
        if disks:
            g.text(x + 210, y + 59, "Outros discos:", DARK)
            dx = x + 210 + text_width(tr("Outros discos:")) + 6
            for path in disks[:4]:
                name = fit(os.path.basename(path), 70, True)
                bw = text_width(name, True) + 16
                ui.button(("vol", path), dx, y + 54, bw, 20, name, on=lambda p=path: self.scan(p))
                dx += bw + 6
        y += 90
        g.text(x, y, "Nada é apagado sem você marcar. O que for marcado vai para o Lixo.", DARK)
        if MAC:
            g.text(x, y + 13, "Algumas pastas do sistema podem pedir Acesso Total ao Disco.", DARK)
        if mascot.enabled():
            mascot.draw(g, "aponta-esquerda", self.dw - 14 - mascot.width("aponta-esquerda", 110, g.s), self.dh - 130, 110)

    def browse(self, ui, x, y, w):
        g = ui.g
        tree, folder = self.tree, self.folder
        size = tree.sizes.get(folder, 0)
        # caminho e voltar
        up = folder != tree.root
        ui.button("up", x, y, 60, 17, "← Voltar", on=self.go_up, enabled=up)
        shown = folder.replace(os.path.expanduser("~"), "~") or "/"
        g.text(x + 68, y + 4, fit(shown, w - 160, True), INK, True)
        g.right(x + w, y + 4, human_size(size), BLUE, True)
        y += 24
        items = tree.children.get(folder, [])
        # faixa colorida: as maiores partes da pasta, lado a lado
        colors = [(0, 0, 255), (60, 60, 255), (110, 110, 255), (150, 150, 255), (185, 185, 255), (215, 215, 255)]
        g.rect(x + 3, y + 3, w, 22, fill=INK)
        g.rect(x, y, w, 22, fill=WHITE, line=INK)
        left = x + 1
        for n, (name, item_size, is_dir) in enumerate(items[:6]):
            part = int((w - 2) * item_size / size) if size else 0
            if part < 2:
                break
            g.rect(left, y + 1, part, 20, fill=colors[n])
            if part > 50:
                g.text(left + 4, y + 6, fit(name, part - 8, True), WHITE if n < 3 else INK, True)
            left += part
        y += 32
        top = y
        height = (self.dh - top - 52) // self.ROW * self.ROW + 2
        g.rect(x, top, w, height, fill=WHITE, line=INK)
        visible = height // self.ROW
        if ui.wheel and ui.over(x, top, w, height):
            self.scroll += ui.wheel * 2
        self.scroll = ui.scrollbar("sp", x + w - 12, top, height, max(1, len(items)), visible, self.scroll)
        biggest = items[0][1] if items else 1
        lw = w - 14
        if not items:
            g.center(x, top + height // 2 - 5, w, "Pasta vazia (ou sem permissão para olhar).", DARK)
        for n, (name, item_size, is_dir) in enumerate(items[self.scroll:self.scroll + visible]):
            ry = top + 1 + n * self.ROW
            path = os.path.join(folder, name)
            on = path in self.marked
            box_hover, _, box_click = ui.clickable(("m", path), x + 4, ry, 18, self.ROW)
            over, held, clicked = ui.clickable(("r", path), x + 22, ry, lw - 22, self.ROW)
            tone = BLUE if over else INK
            g.rect(x + 7, ry + 5, 10, 10, fill=RED if on else WHITE, line=BLUE if box_hover else INK)
            if on:
                g.icon("x", x + 8, ry + 6, 8, WHITE)
            bar_w = 120
            bx = x + lw - bar_w - 70
            g.rect(bx, ry + 6, bar_w, 8, fill=(235, 235, 235))
            g.rect(bx, ry + 6, max(1, int(bar_w * item_size / biggest)), 8, fill=BLUE if is_dir else DARK)
            g.right(x + lw - 4, ry + 5, human_size(item_size), tone, True)
            g.icon("folder" if is_dir else "doc", x + 24, ry + 3, 13, tone)
            g.text(x + 42, ry + 5, fit(name, bx - x - 50, is_dir), GRAY if on else tone, is_dir)
            g.hline(x + 1, ry + self.ROW - 1, lw, (235, 235, 235))
            if box_click:
                (self.marked.discard if on else self.marked.add)(path)
            elif clicked and is_dir:
                self.folder, self.scroll = path, 0
            elif clicked:
                reveal(path)
        by = top + height + 6
        marked_size = sum(self.size_of(p) for p in self.marked)
        g.text(x, by + 2, fit(self.message or tr("Clique numa pasta para entrar. Quadradinho marca para o Lixo."), w), DARK)
        by += 17
        ui.button("again", x, by, 100, 20, "Medir outra", on=lambda: setattr(self, "tree", None))
        ui.button("finder", x + 106, by, 130, 20, "Mostrar no Finder" if MAC else "Mostrar na pasta",
                  on=lambda: reveal(folder))
        label = f"{tr('Mandar')} {len(self.marked)} {tr('para o Lixo')} ({human_size(marked_size)})" if self.marked \
            else "Nada marcado"
        ui.button("trash", x + 242, by, w - 242, 20, label, on=self.go, enabled=bool(self.marked), tone=AMBER, bold=True)

    def size_of(self, path):
        parent, name = os.path.dirname(path), os.path.basename(path)
        for n, s, d in self.tree.children.get(parent, []):
            if n == name:
                return s
        return 0

    def go_up(self):
        if self.folder != self.tree.root:
            self.folder, self.scroll = os.path.dirname(self.folder), 0

    def go(self):
        paths = sorted(self.marked)
        moved, failed = trash(paths)
        for path in paths:
            if not os.path.exists(path):
                self.tree.remove(path)
        self.marked = {p for p in self.marked if os.path.exists(p)}
        self.message = f"{moved} {tr('foram para o Lixo')}" + (f" · {len(failed)} {tr('não deu')}" if failed else "")


# ================================================================ pasta mágica
class MagicDialog(ToolDialog):
    def __init__(self, app):
        from ..modules import magic
        super().__init__(app, "Pasta mágica", 440, 420)
        self.magic = magic
        self.host.frame()
        self.tick()

    def tick(self):
        if self.alive:
            self.host.invalidate()
            self.after(2000, self.tick)

    def body(self, ui):
        g = ui.g
        magic = self.magic
        cfg = magic.config()
        x, y, w = 16, 24, self.dw - 32
        lines = ["Escolha uma pasta e o que fazer com o que chegar nela.",
                 "Todo arquivo novo que cair lá é tratado sozinho.",
                 "O original fica onde está. O resultado vai para",
                 f"{tr('a pasta')} “{tr(magic.OUT_NAME)}”, {tr('dentro dela.')}"]
        for n, line in enumerate(lines):
            g.text(x, y + n * 13, line, DARK if n != 2 and n != 3 else INK, n in (2, 3))
        if mascot.enabled():
            mascot.draw(g, "aponta-esquerda", self.dw - 14 - mascot.width("aponta-esquerda", 56, g.s), y - 4, 56)
        y += 60
        g.text(x, y, "1. A pasta", INK, True)
        folder = cfg["folder"]
        shown = folder.replace(os.path.expanduser("~"), "~") if folder else tr("Nenhuma escolhida")
        ui.button("folder", x, y + 14, w, 19, fit(shown, w - 12), on=self.pick, bold=bool(folder))
        y += 42
        g.text(x, y, "2. O que fazer", INK, True)
        y += 15
        half = (w - 6) // 2
        for n, (key, label, kinds, explain) in enumerate(magic.RULES):
            bx, by = x + (n % 2) * (half + 6), y + (n // 2) * 22
            if ui.button(("rule", key), bx, by, half, 18, label, selected=cfg["rule"] == key):
                magic.save(rule=key)
        y += 22 * (-(-len(magic.RULES) // 2)) + 2
        rule = magic.RULE_BY_KEY.get(cfg["rule"], magic.RULES[0])
        g.text(x, y, fit(rule[3], w), BLUE, True)
        y += 22
        g.text(x, y, "3. Ligar", INK, True)
        on = cfg["on"] and bool(folder)
        ui.button("on", x, y + 14, 120, 22, "Desligar" if on else "Ligar", on=self.toggle, tone=None if on else AMBER,
                  bold=True, enabled=bool(folder))
        status = tr("Ligada: olhando a pasta") if on else tr("Desligada")
        g.text(x + 130, y + 20, status, BLUE if on else DARK, on)
        y += 44
        watcher = getattr(self.app, "magic", None)
        if watcher and watcher.last:
            stamp, text = watcher.last
            minutes = int((time.time() - stamp) // 60)
            ago = tr("agora") if minutes < 1 else tr("há {} min").format(minutes)
            g.text(x, y, fit(f"{tr('Último')}: {text} ({ago})", w), DARK)
        y += 14
        g.text(x, y, "Funciona enquanto o Treco estiver aberto, mesmo só na barra lá de cima.", DARK)
        g.text(x, y + 13, "Só arquivos que chegarem depois de ligar. Os que já estavam ficam como estão.", DARK)
        by = self.dh - 31
        if folder:
            ui.button("open", x, by, 130, 17, f"{tr('Abrir')} “{tr('Prontos')}”", on=self.open_out)
        ui.button("close", self.dw - 86, by, 70, 17, "Fechar", on=self.close)

    def pick(self):
        folder = ask_folder(self.app, "Qual pasta vai ser a Pasta mágica?")
        if folder:
            self.magic.save(folder=folder)
            self.app.restart_magic()

    def toggle(self):
        cfg = self.magic.config()
        self.magic.save(on=not cfg["on"])
        self.app.restart_magic()

    def open_out(self):
        folder = self.magic.config()["folder"]
        out = os.path.join(folder, tr(self.magic.OUT_NAME))
        target = out if os.path.isdir(out) else folder
        subprocess.Popen(["open", target] if MAC else ["explorer", os.path.normpath(target)])


# ================================================================ conta-gotas
def color_formats(rgb):
    import colorsys
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return [("HEX", f"#{r:02X}{g:02X}{b:02X}"), ("RGB", f"rgb({r}, {g}, {b})"),
            ("HSL", f"hsl({round(h * 360)}, {round(s * 100)}%, {round(l * 100)}%)")]


class ColorDialog(ToolDialog):
    """Mostra a cor pega na tela, já copiada, com os formatos e as últimas cores."""

    def __init__(self, app, rgb):
        super().__init__(app, "Conta-gotas", 340, 196)
        self.rgb = rgb
        self.copied = "HEX"
        self.remember(rgb)
        copy_text(self, color_formats(rgb)[0][1])
        self.host.frame()

    @staticmethod
    def remember(rgb):
        recent = [tuple(c) for c in prefs.get("colors") or [] if tuple(c) != tuple(rgb)]
        prefs.put("colors", [list(rgb)] + recent[:9])

    def show(self, rgb):
        self.rgb = rgb
        self.remember(rgb)
        copy_text(self, color_formats(rgb)[0][1])
        self.copied = "HEX"
        self.bring_front()

    def body(self, ui):
        g = ui.g
        x, y, w = 16, 24, self.dw - 32
        g.rect(x + 3, y + 3, 70, 70, fill=INK)
        g.rect(x, y, 70, 70, fill=tuple(self.rgb), line=INK)
        fx = x + 84
        for n, (name, text) in enumerate(color_formats(self.rgb)):
            ry = y + n * 24
            g.text(fx, ry + 4, name, DARK, True)
            if ui.button(("c", name), fx + 34, ry, w - 118, 18, text, bold=self.copied == name, selected=self.copied == name):
                copy_text(self, text)
                self.copied = name
        g.text(x, y + 78, f"{tr('Copiado')}: {dict(color_formats(self.rgb))[self.copied]}", BLUE, True)
        y += 96
        recent = [tuple(c) for c in prefs.get("colors") or []][:10]
        g.text(x, y, "Últimas cores", DARK)
        for n, color in enumerate(recent):
            bx = x + 82 + n * 22
            over, _, clicked = ui.clickable(("r", n), bx, y - 3, 18, 18)
            g.rect(bx, y - 3, 18, 18, fill=color, line=BLUE if over else INK)
            if clicked:
                self.rgb = color
                copy_text(self, color_formats(color)[0][1])
                self.copied = "HEX"
        by = self.dh - 31
        ui.button("again", x, by, 120, 17, "Pegar outra cor", on=self.again, tone=AMBER, bold=True)
        ui.button("close", self.dw - 86, by, 70, 17, "Fechar", on=self.close)

    def again(self):
        pick_color(self.app, self)


def pick_color(app, dialog=None):
    """Abre a lupa do próprio Mac: a pessoa clica em qualquer ponto da tela e a cor vem para cá."""
    if not MAC:
        from .win_picker import pick

        def picked(rgb):
            if dialog is not None and dialog.alive:
                dialog.show(rgb)
            else:
                app.safe_dialog(ColorDialog, rgb)
        pick(app.root, picked)
        return
    from AppKit import NSColorSampler, NSColorSpace

    def chosen(color):
        if color is None:
            return
        try:
            c = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
            rgb = tuple(max(0, min(255, round(v * 255))) for v in (c.redComponent(), c.greenComponent(), c.blueComponent()))
        except Exception as e:
            log_error("conta-gotas", e)
            return

        def show():
            if dialog is not None and dialog.alive:
                dialog.show(rgb)
            else:
                app.safe_dialog(ColorDialog, rgb)
        app.root.after(0, show)
    sampler = NSColorSampler.alloc().init()
    app._sampler = sampler  # precisa continuar vivo enquanto a lupa está na tela
    sampler.showSamplerWithSelectionHandler_(chosen)
