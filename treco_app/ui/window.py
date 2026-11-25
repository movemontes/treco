"""Mesa de trabalho do Treco."""
import datetime
import os
import subprocess
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog

from ..core.engine import compress_file, convert_file, transform_file
from ..core.files import human_size
from ..core.formats import ACTIONS, COMPRESS_ITEMS, COMPRESSIBLE, EDITABLE, FFMPEG, KINDS, MAC_ONLY, MB, MORE_TOOLS, OUTS, ROTATIONS, TOOLS, kind_of
from ..core.jobs import Cancelled, Job, NothingToGain
from ..core.i18n import english, tr
from ..core.log import log_error
from ..version import VERSION
from ..core.paths import MAC
from .icons import KIND_ICON
from .pill import ProgressPill
from .pixel import BLUE, DARK, INK, RED, WHITE, fit, text_width
from .toolkit import PixelHost, TextField, pick_scale

try:
    from tkinterdnd2 import DND_FILES
    DND_OK = True
except Exception:
    DND_OK = False

W, H = 400, 480
MIN_W, MIN_H = 320, 400  # menor que isso os botões não cabem
HEADER_H, FILES_H, FOOTER_H = 30, 112, 28
PAD, GAP, TILE_SMALL = 6, 4, 34  # margem, espaço entre quadrados, altura do quadrado com uma categoria aberta
# categorias da tela; as três primeiras só aparecem com arquivo na lista
CATEGORIES = (("convert", "Converter", "convert"), ("compress", "Comprimir", "compress"), ("edit", "Editar", "edit"),
              ("av", "Vídeo e áudio", "video"), ("image", "Imagem", "image"), ("docs", "Documentos", "doc"),
              ("download", "Baixar", "download"), ("utils", "Utilidades", "tools"))
TABS = CATEGORIES
# botões de cada categoria (os que não existem neste computador somem sozinhos)
TAB_TOOLS = {"av": ("caption", "transcribe", "mark", "rec_voice", "rec_screen", "rec_both"),
             "image": ("photos_pdf", "scan", "slideshow", "nobg", "ocr", "faces", "mark"),
             "docs": ("summary", "scan", "ocr", "lock", "translate", "clip", "rename"),
             "utils": ("cleanup", "uninstall", "cliphist", "scrollshot", "qr", "awake", "speed_test", "wifi", "battery",
                       "unblock")}
CAPTION_TOOL = ("caption", "Legendar", "caption", {"video"})
QUICK_VERBS = {"trim": "Cortando", "crop": "Recortando", "resize": "Redimensionando", "mute": "Silenciando",
               "speed": "Ajustando", "volume": "Nivelando", "clean": "Limpando", "split": "Separando",
               "transcribe": "Transcrevendo", "nobg": "Recortando", "ocr": "Lendo", "faces": "Borrando",
               "lock": "Protegendo", "unlock": "Destravando", "mark": "Marcando", "translate": "Traduzindo",
               "photos_pdf": "Juntando", "scan": "Escaneando", "slideshow": "Montando"}
RECORD_OPS = ("rec_voice", "rec_screen", "rec_both")
# utilidades do Mac (ação, nome, ícone); "qr" funciona em qualquer sistema
UTILITIES = (("cleanup", "Limpar Downloads", "trash"), ("uninstall", "Desinstalar app", "uninstall"),
             ("cliphist", "Histórico de cópias", "history"), ("scrollshot", "Captura com rolagem", "scrollshot"),
             ("summary", "Resumir página", "summary"), ("qr", "QR Code", "qr"), ("awake", "Mac acordado", "awake"),
             ("speed_test", "Teste de internet", "gauge"), ("wifi", "Senha do Wi-Fi", "wifi"),
             ("battery", "Bateria", "battery"), ("unblock", "Liberar app", "unlock"))
# frase que aparece no alto do menu do botão direito
TIPS = {"caption": "Escreve a legenda dentro do vídeo", "transcribe": "A fala vira texto (.txt ou .srt)",
        "mark": "Põe seu nome ou marca por cima", "rec_voice": "Grava o microfone até você parar",
        "rec_screen": "Grava a tela até você parar", "rec_both": "Grava a tela com a sua voz",
        "nobg": "Tira o fundo e deixa transparente", "ocr": "Copia o texto de uma foto ou PDF",
        "faces": "Borra os rostos da foto", "photos_pdf": "Junta as fotos num PDF, na ordem da lista",
        "scan": "Foto de documento vira PDF limpo", "slideshow": "Fotos viram um vídeo de apresentação", "lock": "Põe senha no PDF", "slow": "Câmera lenta, sem engrossar a voz",
        "speed": "Deixa mais rápido",
        "translate": "Traduz texto, legenda ou documento", "clip": "Traduz o que você copiou",
        "rename": "Dá nomes em sequência aos arquivos", "cleanup": "Mostra o que ocupa espaço em Downloads",
        "qr": "Link ou texto vira QR Code", "awake": "O Mac não dorme enquanto estiver ligado",
        "speed_test": "Mede a velocidade da internet", "wifi": "Mostra a senha e o QR do Wi-Fi",
        "battery": "Saúde e ciclos da bateria", "uninstall": "Tira o app e o que ele guardou no Mac",
        "cliphist": "Tudo o que você copiou, para colar de novo", "scrollshot": "Foto de uma página inteira, rolando",
        "summary": "A IA do Mac resume um link da internet", "unblock": "Abre app que o Mac diz estar danificado"}


def more_tools():
    """Ferramentas por tipo de arquivo que funcionam neste computador."""
    from ..modules import translate, vision_mac
    vision = MAC and vision_mac.available()
    ok = lambda op: translate.available() if op == "translate" else vision
    return [t for t in MORE_TOOLS if t[0] not in MAC_ONLY or ok(t[0])]


def grid_shape(count, w, h, min_w=64):
    """Colunas e linhas para os botões ficarem perto de quadrados."""
    most = max(1, min(count, (w + 2) // (min_w + 2)))
    rows = -(-count // most)
    return -(-count // rows), rows


def two_lines(text, width, bold, size=1):
    """Quebra o nome em até duas linhas que cabem na largura."""
    text = tr(text)
    if text_width(text, bold, size) <= width or " " not in text:
        return [fit(text, int(width / size), bold)]
    words = text.split()
    for cut in range(len(words) - 1, 0, -1):
        first = " ".join(words[:cut])
        if text_width(first, bold, size) <= width:
            return [first, fit(" ".join(words[cut:]), int(width / size), bold)]
    return [fit(text, int(width / size), bold)]


ROW_H = 23


class Row:
    def __init__(self, path, kind):
        self.path, self.kind = path, kind
        self.name = os.path.basename(path)
        try:
            self.size = human_size(os.path.getsize(path))
        except OSError:
            self.size = ""
        self.sub = self.size
        self.status, self.tone = "", None
        self.busy = False
        self.job = None
        self.action = "Processando"
        self.progress = None
        self.done_path = None

    def working(self, job=None):
        self.busy, self.job = True, job
        self.status, self.tone, self.progress = "", None, None

    def finished(self, ok, text, dst=None, detail=None):
        self.busy, self.job = False, None
        self.progress = None
        self.status, self.tone = text, ok
        if ok is not True:
            self.sub = self.size
        if dst:
            self.done_path = dst
            if detail is None:
                detail = f"{len(os.listdir(dst))} arquivos" if os.path.isdir(dst) else human_size(os.path.getsize(dst))
            self.sub = f"→ {os.path.basename(dst)} · {detail}"


class App:
    def __init__(self, root):
        self.root = root
        from ..core import prefs
        self.scale, height = pick_scale(root, W, H)
        self.max_w = root.winfo_screenwidth() // self.scale
        self.max_h = (root.winfo_screenheight() - 56) // self.scale
        self.w, self.h = W, height
        saved = prefs.get("window_size")
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            self.w = max(MIN_W, min(self.max_w, int(saved[0])))
            self.h = max(MIN_H, min(self.max_h, int(saved[1])))
        self.files_h = self.list_height()
        # No Mac a janela principal do Tk não perde a moldura; usamos uma janela filha.
        self.win = tk.Toplevel(root) if MAC else root
        self.host = PixelHost(self.win, self.w, self.h, self.scale, self.draw, "Treco")
        self.rows = {}
        self.pool = ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 4))
        self.out_dir = None
        self.last_dir = None
        self.tray = None
        self.recording = None
        self.awake = None
        self.clips = None
        if MAC:
            from ..core import prefs
            from ..modules import recorder
            from ..modules.cliphistory import Watcher
            from ..modules.mac_utils import KeepAwake
            self.awake = KeepAwake()
            self.clips = Watcher(root, enabled=lambda: prefs.get("clip_history"))
            self.clips.start()
            if recorder.available():
                from .actions_mac import RecorderControl
                self.recording = RecorderControl(self)
        self.pill = ProgressPill(root, self.scale)
        self.tasks = {}
        self.tab = None
        self.url = TextField("", 2048)
        self.dl_quality = "Melhor"
        self.row_h = None
        self.layout = None
        self.utilities = None
        self.context_menu = None
        self.direct = False
        self.direct_value = None
        self.spots = {}
        self.menu = None
        self.about = False
        self.quality = 90
        self.target = TextField("16", 7)
        self.scroll = 0
        self.drop_hot = False
        self.notice = None
        self.caption_queue = []
        self.dialog_queue = []
        self.animating = False
        if DND_OK:
            for widget in (self.win, self.host.label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self.on_drop)
                widget.dnd_bind("<<DropEnter>>", lambda e: self.hl(True))
                widget.dnd_bind("<<DropPosition>>", lambda e: "copy")
                widget.dnd_bind("<<DropLeave>>", lambda e: self.hl(False))
        self.host.frame()
        self.clock()

    def clock(self):
        self.host.invalidate()
        self.root.after(15000, self.clock)

    def hl(self, on):
        self.drop_hot = on
        self.host.invalidate()
        return "copy"

    # ------------------------------------------------ desenho
    def draw(self, ui):
        self.spots = {}  # onde ficou cada botão neste desenho (usado nos testes)
        if self.menu is None and not self.about and self.context_menu is None:
            ui.resize_grip((MIN_W, MIN_H, self.max_w, self.max_h), self.resized)
        ui.chassis()
        ui.enabled = self.menu is None and not self.about and self.context_menu is None
        self.draw_files(ui)
        self.draw_actions(ui)
        self.draw_footer(ui)
        ui.enabled = not self.about
        self.draw_header(ui)
        if self.about:
            ui.enabled = True
            self.draw_about(ui)
        elif self.context_menu:
            ui.enabled = True
            self.draw_context(ui)
        if not self.about:
            ui.draw_grip(INK)

    def status_line(self):
        done = sum(1 for r in self.rows.values() if r.done_path)
        busy = sum(1 for r in self.rows.values() if r.busy)
        if self.notice:
            return self.notice
        if not FFMPEG:
            return "ffmpeg não encontrado", RED
        if busy:
            return f"Trabalhando em {busy}…", BLUE
        if self.rows:
            return f"{len(self.rows)} {'item' if len(self.rows) == 1 else 'itens'} · {done} {'pronto' if done == 1 else 'prontos'}", INK
        return "Tudo no seu computador", DARK

    def draw_header(self, ui):
        g = ui.g
        g.rect(0, 0, self.w, HEADER_H, fill=WHITE)
        g.hline(0, HEADER_H - 1, self.w, INK)
        g.hline(0, HEADER_H - 2, self.w, INK)
        menus = self.menus()
        label_w = text_width("TRECO", True, 1.9) + 14
        hover, _, _ = ui.clickable(("menu", "Treco"), 0, 0, label_w + 10, HEADER_H - 2)
        selected = self.menu == "Treco"
        if hover and ui.pressed:
            self.menu = None if selected else "Treco"
            selected = self.menu == "Treco"
        if selected:
            g.rect(0, 0, label_w + 10, HEADER_H - 2, fill=INK)
        g.text(9, 4, "TRECO", WHITE if selected else BLUE if hover else INK, True, 1.9)
        text, color = self.status_line()
        g.right(self.w - 42, 10, fit(text, 210), color)
        for key, kx, name, action in (("min", self.w - 37, "min", self.host.minimize), ("hide", self.w - 20, "x", self.hide_window)):
            over, held, clicked = ui.clickable(("win", key), kx, 6, 16, 16)
            g.icon(name, kx + 1, 7, 14, BLUE if over else INK)
            if clicked:
                ui.later(action)
        if self.menu is None:
            ui.drag_area(label_w + 10, 0, self.w - label_w - 56, HEADER_H - 2)
            return
        items = menus["Treco"]
        mw = max(text_width(i[0], True) for i in items if i) + 24
        mh = sum(17 if i else 5 for i in items) + 6
        g.rect(0, HEADER_H - 2, mw, mh, fill=WHITE, line=INK)
        g.rect(1, HEADER_H - 1, mw - 2, mh - 2, line=INK)
        iy = HEADER_H + 1
        inside = ui.over(0, HEADER_H - 2, mw, mh)
        for item in items:
            if item is None:
                g.hline(0, iy + 2, mw, INK)
                iy += 5
                continue
            over = ui.over(2, iy, mw - 4, 17)
            g.text(10, iy + 4, item[0], BLUE if over else INK, over)
            if over and ui.released:
                self.menu = None
                ui.later(item[1])
                ui.later(ui.invalidate)
            iy += 17
        if ui.pressed and not inside and not hover:
            self.menu = None
            ui.later(ui.invalidate)

    def menus(self):
        from .tray import autostart_on, autostart_toggle
        start = "Iniciar com o Mac" if MAC else "Iniciar com o Windows"
        return {"Treco": [("Adicionar arquivos…", self.pick_files), ("Adicionar pasta…", self.pick_folder), None,
                          (("✓ " if autostart_on() else "") + start, autostart_toggle), ("Sobre o Treco", self.show_about), None,
                          ("Esconder", self.hide_window), ("Sair", self.quit)]}

    # --- categorias em quadrados; a escolhida se abre embaixo com as opções
    def categories(self, kinds):
        shown = []
        for key, label, image in CATEGORIES:
            if key == "convert" and not kinds:
                continue
            if key == "compress" and not kinds & COMPRESSIBLE:
                continue
            if key == "edit" and not any(kinds & t[3] for t in TOOLS):
                continue
            shown.append((key, label, image))
        return shown

    def category_rows(self, cats):
        count = len(cats)
        columns = count if count <= 3 else 3 if count <= 6 else 4
        if self.w < 380:  # janela estreita: no máximo 3 por linha
            columns = min(columns, 3)
        return [cats[i:i + columns] for i in range(0, count, columns)]

    def segment_targets(self, rows, total):
        """Altura de cada linha de quadrados e da área aberta embaixo de cada uma."""
        inner = total - 2 * PAD - GAP * (len(rows) - 1)
        opened = next((r for r, row in enumerate(rows) if any(c[0] == self.tab for c in row)), None)
        if opened is None:
            return [v for _ in rows for v in (inner / len(rows), 0)]
        panel = inner - TILE_SMALL * len(rows)
        return [v for r in range(len(rows)) for v in (TILE_SMALL, panel if r == opened else 0)]

    def step_segments(self, targets, signature):
        if self.row_h is None or self.layout != signature:
            self.row_h, self.layout = list(targets), signature  # categorias mudaram: sem animação
        moving = False
        for i, target in enumerate(targets):
            gap = target - self.row_h[i]
            if abs(gap) < .7:
                self.row_h[i] = target
            else:
                self.row_h[i] += gap * .38
                moving = True
        if moving:
            self.root.after(16, self.host.invalidate)
        return moving

    def draw_actions(self, ui):
        g = ui.g
        top = HEADER_H + self.files_h
        total = self.h - FOOTER_H - top
        kinds = {r.kind for r in self.rows.values()}
        cats = self.categories(kinds)
        if self.tab not in [c[0] for c in cats]:
            self.tab = None
        rows = self.category_rows(cats)
        moving = self.step_segments(self.segment_targets(rows, total), tuple(c[0] for c in cats))
        y = top + PAD
        for r, row in enumerate(rows):
            h = self.row_h[2 * r]
            each = (self.w - 2 * PAD - GAP * (len(row) - 1)) / len(row)
            opened = None
            for i, (key, label, image) in enumerate(row):
                x = PAD + round(i * (each + GAP))
                w = PAD + round((i + 1) * (each + GAP) - GAP) - x
                self.category_tile(ui, key, label, image, x, round(y), w, round(h))
                if key == self.tab:
                    opened = (x, w)
            y += h
            panel = self.row_h[2 * r + 1]
            if panel > GAP + 6:
                bx, by, bw, bh = PAD, round(y + GAP), self.w - 2 * PAD, round(panel - GAP)
                g.rect(bx, by, bw, bh, fill=WHITE, line=INK)
                g.rect(bx + 1, by + 1, bw - 2, bh - 2, line=INK)
                if opened:  # liga o quadrado escolhido à área aberta, como uma aba
                    g.rect(opened[0], round(y) - 1, opened[1], GAP + 3, fill=INK)
                if opened and not moving and bh > 40:
                    key = self.tab
                    area = (bx + 9, by + 9, bw - 18, bh - 18)
                    {"convert": self.tab_convert, "compress": self.tab_compress, "edit": self.tab_edit,
                     "download": self.tab_download}.get(key, lambda *a: self.tab_group(key, *a))(ui, area, kinds)
            y += panel + (GAP if r < len(rows) - 1 else 0)

    def category_tile(self, ui, key, label, image, x, y, w, h):
        g = ui.g
        selected = self.tab == key
        self.spots[("cat", key)] = (x, y, w, h)
        hover, held, clicked = ui.clickable(("cat", key), x, y, w, h)
        ui.face(x, y, w, h, hover, held, selected)
        color = ui.ink(hover, held, selected)
        bold = True
        if h >= 64:  # quadrado grande: ícone em cima, nome embaixo
            size = 1.4 if w >= 110 else 1.15
            icon = max(18, min(40, int(h * .3), w - 30))
            lines = two_lines(label, w - 10, bold, size)
            block = icon + 8 + len(lines) * int(11 * size)
            iy = y + (h - block) // 2
            g.icon(image, x + (w - icon) // 2, iy, icon, color)
            for n, line in enumerate(lines):
                g.center(x, iy + icon + 8 + n * int(11 * size), w, line, color, bold, size)
        else:  # categoria aberta: quadrados baixos
            g.icon(image, x + (w - 14) // 2, y + 4, 14, color)
            g.center(x, y + h - 13, w, fit(label, int((w - 4) / .85), hover or selected), color, hover or selected, .85)
        if clicked:
            self.tab = None if selected else key
            ui.later(ui.invalidate)

    def hint(self, ui, area, text):
        x, y, w, h = area
        ui.g.center(x, y + h // 2 - 8, w, fit(text, w, True), DARK, True, 1.1)

    def tab_convert(self, ui, area, kinds):
        g = ui.g
        x, y, w, h = area
        shown = [k for k in KINDS if k in kinds]
        if not shown:
            self.hint(ui, area, "Adicione um arquivo primeiro")
            return
        for row, kind in enumerate(shown):
            ry = y + row * 15
            g.icon(KIND_ICON[kind], x, ry, 13, INK)
            names = OUTS[kind]
            avail = w - 18 - (len(names) - 1) * 2
            room = avail - sum(text_width(f) for f in names)
            padding = max(3, min(10, room // len(names)))
            cx = x + 18
            for fmt in names:
                width = text_width(fmt) + padding
                ui.button(("fmt", kind, fmt), cx, ry, width, 14, fmt, on=lambda k=kind, f=fmt: self.convert_all(k, f))
                cx += width + 2
        if "image" in kinds:
            sy = y + h - 11
            g.text(x, sy, "Qualidade", INK, True)
            self.quality = ui.slider("quality", x + 76, sy, w - 112, self.quality, 40, 100)
            g.right(x + w, sy, f"{self.quality}", BLUE, True)

    def tab_compress(self, ui, area, kinds):
        g = ui.g
        x, y, w, h = area
        active = bool(kinds & COMPRESSIBLE)
        if not active:
            self.hint(ui, area, "Serve para imagem, áudio, vídeo e PDF")
            return
        notes = {"leve": "quase igual", "medio": "equilibrado", "forte": "bem menor"}
        each = (w - 8) // 3
        for i, (label, mode) in enumerate(COMPRESS_ITEMS[:3]):
            bx = x + i * (each + 4)
            over, held, clicked = ui.clickable(("comp", mode), bx, y, each, 48)
            ui.face(bx, y, each, 48, over, held)
            color = ui.ink(over, held)
            g.center(bx, y + 9, each, label, color, True, 1.5)
            g.center(bx, y + 31, each, notes[mode], color if over or held else DARK)
            if clicked:
                ui.later(self.compress_all, mode)
        ry = y + 56
        g.text(x, ry + 5, "Até", INK, True)
        focused = ui.entry("target", x + 28, ry, 46, 20, self.target, numeric=True)
        if focused and any(k[0] == "Return" for k in ui.keys):
            ui.later(self.compress_target)
        g.text(x + 79, ry + 5, "MB", INK, True)
        ui.button("target-go", x + 104, ry, 92, 20, "Comprimir", on=self.compress_target, tone=BLUE, bold=True)
        presets = COMPRESS_ITEMS[3:]
        cx = x + 202
        width = (w - 202 - (len(presets) - 1) * 2) // len(presets)
        for label, value in presets:
            ui.button(("preset", value), cx, ry, width, 20, label.replace(" MB", ""), on=lambda v=value: self.compress_all(v))
            cx += width + 2

    def tab_edit(self, ui, area, kinds):
        self.tool_grid(ui, area, kinds, TOOLS)

    def tab_group(self, key, ui, area, kinds):
        """Vídeo e áudio, Imagem, Documentos e Utilidades: botões quase quadrados, lado a lado."""
        found = {t[0]: t for t in [CAPTION_TOOL] + more_tools() + self.action_tools()}
        tools = [found[op] for op in TAB_TOOLS[key] if op in found]
        self.tool_grid(ui, area, kinds, tools)

    def utility_ok(self):
        """Quais utilidades existem neste computador (só pergunta ao sistema uma vez)."""
        if self.utilities is None:
            found = {"qr"}
            if MAC:
                from ..modules import mac_utils
                from ..modules import summary
                found |= {"cleanup", "awake", "speed_test", "unblock", "uninstall", "cliphist", "scrollshot"}
                if summary.available():
                    found.add("summary")
                if mac_utils.wifi_device():
                    found.add("wifi")
                if mac_utils.has_battery():
                    found.add("battery")
            self.utilities = found
        return self.utilities

    def action_tools(self):
        """Botões que funcionam sem arquivo (aceitos=None): gravar, traduzir a cópia e utilidades."""
        from ..modules import translate
        rec, items = self.recording, []
        for op, label, image in ACTIONS:
            if op == "clip":
                if translate.available():
                    items.append((op, label, image, None))
            elif rec and rec.busy and rec.op == op:
                text = rec.label() if rec.saving else f"Parar {rec.label()}"
                items.append((op, text, "stop", set() if rec.saving else None))
            elif rec:
                items.append((op, label, image, set() if rec.busy else None))
        ok = self.utility_ok()
        items += [(op, label, image, None) for op, label, image in UTILITIES if op in ok]
        return items

    more_actions = action_tools

    def selected_tool(self, op):
        return op == "awake" and bool(self.awake and self.awake.on)

    def tool_grid(self, ui, area, kinds, tools, columns=None):
        g = ui.g
        x, y, w, h = area
        if columns:
            rows = -(-len(tools) // columns)
        else:
            columns, rows = grid_shape(len(tools), w, h)
        each = (w - (columns - 1) * 2) // columns
        cell_h = min(76, (h - 2 * (rows - 1)) // rows)
        y += (h - rows * cell_h - 2 * (rows - 1)) // 2  # sobra de altura: centraliza
        for i, (op, label, image, accepted) in enumerate(tools):
            bx, by = x + (i % columns) * (each + 2), y + (i // columns) * (cell_h + 2)
            active = accepted is None or bool(kinds & accepted)
            selected = self.selected_tool(op)
            self.spots[("tool", op)] = (bx, by, each, cell_h)
            over, held, clicked = ui.clickable(("tool", op), bx, by, each, cell_h, active)
            ui.face(bx, by, each, cell_h, over, held, selected, enabled=active)
            color = ui.ink(over, held, selected, enabled=active)
            if cell_h >= 56:  # botão grande: ícone no meio e nome em até duas linhas
                lines = two_lines(label, each - 6, over, .9)
                icon = 22 if cell_h >= 64 else 18
                block = icon + 6 + len(lines) * 10
                top = by + (cell_h - block) // 2
                g.icon(image, bx + (each - icon) // 2, top, icon, color)
                for n, line in enumerate(lines):
                    g.center(bx, top + icon + 6 + n * 10, each, line, color, over, .9)
            elif cell_h >= 40:
                g.icon(image, bx + (each - 18) // 2, by + 6, 18, color)
                g.center(bx, by + cell_h - 14, each, fit(label, int((each - 4) / .8), over), color, over, .8)
            else:  # botão baixo: ícone ao lado do nome
                g.icon(image, bx + 6, by + (cell_h - 14) // 2, 14, color)
                g.text(bx + 24, by + (cell_h - 8) // 2, fit(label, int((each - 28) / .85), over), color, over, .85)
            if clicked:
                ui.later(self.tool, op)
            if ui.context and ui.over(bx, by, each, cell_h):
                ui.later(self.open_context, op, ui.mx, ui.my)

    def tab_download(self, ui, area, kinds):
        from ..modules.download import AUDIO, QUALITIES
        g = ui.g
        x, y, w, h = area
        g.text(x, y + 6, "Link", INK, True)
        field_x, field_w = x + 34, w - 34 - 64
        focused = ui.entry("url", field_x, y, field_w, 22, self.url)
        if not self.url.text and not focused:
            g.text(field_x + 6, y + 6, "Cole o link do vídeo", DARK)
        if focused and any(k[0] == "Return" for k in ui.keys):
            ui.later(self.start_download)
        ui.button("url-paste", x + w - 60, y, 60, 22, "Colar", on=self.paste_url)
        g.text(x, y + 35, "Qualidade", INK, True)
        self.dl_quality = ui.segmented("dl-quality", x + 76, y + 31, w - 76, list(QUALITIES), self.dl_quality)
        label = "Baixar áudio" if self.dl_quality == AUDIO else "Baixar vídeo"
        top = y + 54
        ui.button("dl-go", x, top, w, min(44, h - 54), label, on=self.start_download, enabled=bool(self.url.text.strip()),
                  tone=BLUE, bold=True, size=1.7)

    # --- lista de arquivos
    def draw_files(self, ui):
        g = ui.g
        y, h = HEADER_H, self.files_h - 2
        rows = list(self.rows.values())
        count = len(rows)
        if not rows or self.drop_hot:
            hover, held, clicked = ui.clickable("drop", 0, y, self.w, h)
            hot = self.drop_hot
            if hot:
                g.rect(0, y, self.w, h, fill=BLUE)
            color = WHITE if hot else BLUE if hover else INK
            g.icon("plus", 12, y + 26, 44, color)
            g.text(68, y + 22, "Solte aqui." if not hot else "Pode soltar.", color, hover or hot, 3.0)
            g.text(70, y + 66, "ou clique para escolher", WHITE if hot else color if hover else DARK)
            if clicked:
                ui.later(self.pick_files)
            if hot:
                self.root.after(120, self.host.invalidate)
        if rows and not self.drop_hot:
            lx, ly, lw, lh = 0, y, self.w - 12, h
            visible = max(1, lh // ROW_H)
            if ui.wheel and ui.over(0, ly, self.w, lh):
                self.scroll += ui.wheel
            self.scroll = ui.scrollbar("list", self.w - 12, ly, lh, max(count, 1), visible, self.scroll)
            self.scroll = max(0, min(max(0, count - visible), self.scroll))
            phase = int(time.monotonic() * 10)
            for i, row in enumerate(rows[self.scroll:self.scroll + visible]):
                ry = ly + i * ROW_H
                over = ui.over(lx, ry, lw, ROW_H)
                tone = BLUE if over else INK
                g.icon(KIND_ICON[row.kind], lx + 10, ry + 4, 15, tone)
                status_w = 80
                g.text(lx + 31, ry + 1, fit(row.name, lw - 31 - status_w - 26, True), tone, True)
                g.text(lx + 31, ry + 12, fit(row.sub, lw - 31 - status_w - 26 if row.busy else lw - 60), tone if over else DARK, False, .9)
                bx = lx + lw - status_w - 20
                if row.busy:
                    if row.progress is None:
                        g.barber(bx, ry + 7, status_w, 9, phase, BLUE)
                    else:
                        g.blocks(bx, ry + 7, status_w, 9, row.progress, BLUE)
                elif row.status:
                    color = BLUE if row.tone is True else RED if row.tone is False else DARK
                    g.right(lx + lw - 23, ry + 6, fit(row.status, status_w, True), color, True)
                mark = lambda mx, my, color: ui.mark_x(mx + 1, my + 1, 9, color)
                if ui.mini(("row-close", row.path), lx + lw - 19, ry + 5, 13, mark):
                    ui.later(self.close_row, row.path)
                g.hline(lx, ry + ROW_H - 1, lw, INK)
                self.spots[("row", row.path)] = (lx, ry, lw - 22, ROW_H)
                if over and ui.mx < lx + lw - 22:
                    if ui.double:  # duplo clique: mostra o pronto (ou o original) no Finder
                        ui.later(self.show_row, row.path)
                    elif ui.context:
                        ui.later(self.open_row_menu, row.path, ui.mx, ui.my)
        g.hline(0, HEADER_H + self.files_h - 2, self.w, INK)
        g.hline(0, HEADER_H + self.files_h - 1, self.w, INK)

    def draw_footer(self, ui):
        g = ui.g
        y = self.h - FOOTER_H
        dest = "Salvar em" if not self.out_dir else os.path.basename(self.out_dir)
        items = (("add", "plus", "Adicionar", self.pick_files), ("open", "folder", "Abrir", self.open_folder),
                 ("dest", "disk", dest, self.choose_dest), ("clear", "trash", "Clear" if english() else "Limpar", self.clear))
        g.hline(0, y, self.w, INK)
        g.hline(0, y + 1, self.w, INK)
        each = self.w // len(items)
        for i, (key, name, label, action) in enumerate(items):
            x = i * each
            over, held, clicked = ui.clickable(("desk", key), x, y + 2, each, FOOTER_H - 2)
            if held:
                g.rect(x, y + 2, each, FOOTER_H - 2, fill=INK)
            color = WHITE if held else BLUE if over else INK
            text = fit(label, each - 26, over)
            width = 15 + text_width(text, over)
            left = x + (each - width) // 2
            g.icon(name, left, y + (FOOTER_H - 11) // 2, 12, color)
            g.text(left + 15, y + (FOOTER_H - 9) // 2, text, color, over)
            if i:
                g.vline(x, y + 2, FOOTER_H - 2, INK)
            if clicked:
                ui.later(action)

    def draw_about(self, ui):
        g = ui.g
        g.pattern(0, 0, self.w, self.h, INK, "50")
        w, h = 300, 150
        x, y = (self.w - w) // 2, (self.h - h) // 2
        ui.panel(x, y, w, h, "Sobre", close=self.hide_about)
        g.text(x + 14, y + 28, "TRECO.", BLUE, True, 3.6)
        g.text(x + 14, y + 76, "O faz-tudo de arquivos.", INK, True)
        g.text(x + 14, y + 91, f"Versão {VERSION}", DARK)
        ui.button("about-ok", x + w - 74, y + h - 32, 60, 20, "OK", on=self.hide_about, tone=BLUE, bold=True)

    def show_about(self):
        self.about = True
        self.host.invalidate()

    def hide_about(self):
        self.about = False
        self.host.invalidate()

    # --- botão direito: mais opções de cada botão
    def open_context(self, op, x, y):
        items = self.context_items(op)
        if items:
            self.context_menu = {"items": items, "x": x, "y": y, "at": time.monotonic()}
            self.host.invalidate()

    def set_pref(self, key, value):
        from ..core import prefs
        prefs.put(key, value)
        self.host.invalidate()

    def context_items(self, op):
        """Itens do menu: texto (título cinza), None (linha) ou (nome, ação, marcado)."""
        from ..core import prefs
        radio = lambda key, value, label=None: (label or str(value), lambda: self.set_pref(key, value), prefs.get(key) == value)
        check = lambda key, label: (label, lambda: self.set_pref(key, not prefs.get(key)), bool(prefs.get(key)))
        opts = []
        if op in RECORD_OPS and self.recording:
            from ..modules import recorder
            screens, mics = recorder.devices()
            if self.recording.busy:
                opts += ["Vale para a próxima gravação"]
            if op != "rec_voice":
                opts += [None, "Resolução"] + [radio("rec_resolution", v) for v in recorder.RESOLUTIONS]
                opts += [None, radio("rec_fps", 30, "30 quadros por segundo"), radio("rec_fps", 60, "60 quadros por segundo")]
                opts += [None, check("rec_cursor", "Mostrar o cursor"), check("rec_clicks", "Mostrar os cliques")]
                if len(screens) > 1:
                    now = prefs.get("rec_screen") if prefs.get("rec_screen") in screens else screens[0]
                    opts += [None, "Qual tela"] + [(recorder.screen_label(n), lambda n=n: self.set_pref("rec_screen", n), n == now)
                                                   for n in screens]
            if op != "rec_screen":
                now = prefs.get("rec_mic") if prefs.get("rec_mic") in mics else None
                opts += [None, "Microfone", ("Padrão do Mac", lambda: self.set_pref("rec_mic", None), now is None)]
                opts += [(m, lambda m=m: self.set_pref("rec_mic", m), m == now) for m in mics]
            folder = prefs.get("rec_folder")
            opts += [None, "Salvar em: " + (os.path.basename(folder) if folder else "Mesa"),
                     ("Escolher pasta…", self.choose_rec_folder, None),
                     ("Abrir a pasta", lambda: self.open_path(folder or recorder.default_folder()), None)]
            if folder:
                opts.append(("Voltar a salvar na Mesa", lambda: self.set_pref("rec_folder", None), None))
        elif op in ("translate", "clip"):
            from ..modules.translate import LANGUAGES
            key = "language" if op == "translate" else "clip_language"
            opts += [None, "Traduzir agora para"]
            if op == "clip":
                opts.append(("Automático (português ⇄ inglês)", lambda: self.translate_to(op, None), prefs.get(key) is None))
            opts += [(name, lambda n=name: self.translate_to(op, n), prefs.get(key) == name) for name, _, _ in LANGUAGES]
        elif op == "slow":
            from .tool_dialogs import SLOW_STEPS
            opts += [None, "Aplicar agora"] + [(f"{v}% da velocidade", lambda v=v: self.run_value(op, v), None)
                                              for v in SLOW_STEPS]
            opts += [None, ("Outra porcentagem…", lambda: self.tool(op), None)]
        elif op == "slideshow":
            from ..modules import slideshow as sl
            opts += [None, "Cada foto"] + [radio("slide_seconds", v, f"{v} segundos") for v in sl.SECONDS]
            opts += [None, "Transição"] + [radio("slide_transition", v) for v in sl.TRANSITIONS]
            opts += [None, check("slide_zoom", "Zoom suave (movimento)")]
            opts += [None, "Ordem"] + [radio("slide_order", v) for v in sl.ORDERS]
            opts += [None, "Formato"] + [radio("slide_shape", v) for v in sl.FORMATS]
            opts += [None, ("Criar agora com essas escolhas", lambda: self.run_direct(op), None)]
        elif op == "photos_pdf":
            opts += [None, "Página", radio("pdf_page", "A4", "A4"), radio("pdf_page", "Foto", "Do tamanho da foto"),
                     None, check("pdf_margin", "Margem branca")]
        elif op == "scan":
            from ..modules import vision_mac
            from ..modules.paper import SCAN_COLORS
            names = {"Original": "Original (só endireitar)", "Preto e branco": "Preto e branco (só texto)"}
            opts += [None, "Cor"] + [radio("scan_color", c, names.get(c)) for c in SCAN_COLORS] + [None]
            if MAC and vision_mac.available():
                opts.append(check("scan_crop", "Endireitar a folha sozinho"))
            opts.append(check("scan_separate", "Um PDF para cada foto"))
        elif op == "qr":
            from ..modules.paper import QR_SIZES
            opts += [None, "Tamanho da imagem"] + [radio("qr_size", name, f"{name} ({px} px)") for name, px in QR_SIZES.items()]
            opts += [None, ("QR do que copiei", self.qr_from_clipboard, None)]
        elif op == "summary":
            from ..modules import summary
            opts += [None, "Tamanho do resumo"] + [radio("summary_size", v) for v in summary.SIZES]
            opts += [None, "Salvar como", radio("summary_format", "txt", "Texto (.txt)"),
                     radio("summary_format", "md", "Markdown (.md)")]
        elif op == "scrollshot":
            opts += [None, "Salvar como", radio("shot_format", "PNG", "PNG (mais nítido)"), radio("shot_format", "JPG", "JPG (menor)")]
        elif op == "cliphist":
            opts += [None, check("clip_history", "Guardar o que eu copiar"),
                     ("Apagar o histórico", lambda: self.clips and self.clips.history.clear(), None)]
        elif op == "cleanup":
            from ..modules.cleanup import downloads_folder
            opts += [None, ("Abrir a pasta Downloads", lambda: self.open_path(downloads_folder()), None)]
        items = ([TIPS[op]] if op in TIPS else []) + opts
        clean = []
        for item in items:  # sem linha no começo, no fim ou repetida
            if item is None and (not clean or clean[-1] is None):
                continue
            clean.append(item)
        while clean and clean[-1] is None:
            clean.pop()
        return clean

    def draw_context(self, ui):
        g = ui.g
        menu = self.context_menu
        items = menu["items"]
        heights = [13 if isinstance(i, str) else 5 if i is None else 15 for i in items]
        widths = [text_width(i, False) + 16 if isinstance(i, str) else text_width(i[0], True) + 30 for i in items if i]
        mw = min(self.w - 8, max(130, max(widths)))
        mh = sum(heights) + 6
        x = max(2, min(menu["x"] + 2, self.w - mw - 4))
        y = max(2, min(menu["y"] + 2, self.h - mh - 4))
        g.rect(x + 3, y + 3, mw, mh, fill=INK)  # sombra dura, como nos menus antigos
        g.rect(x, y, mw, mh, fill=WHITE, line=INK)
        g.rect(x + 1, y + 1, mw - 2, mh - 2, line=INK)
        ready = time.monotonic() - menu["at"] > .3  # o Control + clique solta o botão logo depois de abrir
        iy = y + 3
        for item, h in zip(items, heights):
            if item is None:
                g.hline(x + 2, iy + 2, mw - 4, INK)
            elif isinstance(item, str):
                g.text(x + 8, iy + 3, fit(item, mw - 14), DARK)
            else:
                label, action, checked = item
                self.spots[("ctx", label)] = (x + 2, iy, mw - 4, h)
                over = ui.over(x + 2, iy, mw - 4, h)
                if over:
                    g.rect(x + 2, iy, mw - 4, h, fill=INK)
                color = WHITE if over else INK
                if checked:
                    g.text(x + 7, iy + 3, "✓", color, True)
                g.text(x + 19, iy + 3, fit(label, mw - 26, over), color, over)
                if over and ui.released and ready:
                    self.context_menu = None
                    ui.later(action)
                    ui.later(ui.invalidate)
            iy += h
        inside = ui.over(x, y, mw, mh)
        if ((ui.pressed or ui.context) and not inside) or any(k[0] == "Escape" for k in ui.keys):
            self.context_menu = None
            ui.later(ui.invalidate)

    def show_row(self, path):
        row = self.rows.get(path)
        if row:
            target = row.done_path if row.done_path and os.path.exists(row.done_path) else path
            if os.path.exists(target):
                self.reveal(target)

    def open_row_menu(self, path, x, y):
        row = self.rows.get(path)
        if not row:
            return
        done = row.done_path if row.done_path and os.path.exists(row.done_path) else None
        items = []
        if done:
            items += [fit("Pronto: " + os.path.basename(done), 300), ("Mostrar o pronto na pasta", lambda: self.reveal(done), None),
                      ("Abrir o pronto", lambda: self.open_path(done), None), None]
        if os.path.exists(path):
            items += [("Mostrar o original na pasta", lambda: self.reveal(path), None),
                      ("Abrir o original", lambda: self.open_path(path), None), None]
        if not row.busy:
            items.append(("Tirar da lista", lambda: self.remove(path), None))
        if items:
            self.context_menu = {"items": [i for i in items], "x": x, "y": y, "at": time.monotonic()}
            self.host.invalidate()

    def reveal(self, path):
        if MAC:
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def open_path(self, path):
        if not path or not os.path.exists(path):
            self.say("Essa pasta não existe mais")
        elif MAC:
            subprocess.Popen(["open", path])
        else:
            os.startfile(path)

    def choose_rec_folder(self):
        folder = filedialog.askdirectory(title=tr("Onde salvar as gravações"), **self.dialog_owner())
        if folder:
            self.set_pref("rec_folder", folder)

    @staticmethod
    def slide_params():
        from ..core import prefs
        return {"seconds": prefs.get("slide_seconds"), "transition": prefs.get("slide_transition"),
                "zoom": prefs.get("slide_zoom"), "how": prefs.get("slide_order"), "shape": prefs.get("slide_shape")}

    def run_direct(self, op):
        self.direct = True
        try:
            self.tool(op)
        finally:
            self.direct = False

    def run_value(self, op, value):
        self.direct_value = value
        try:
            self.tool(op)
        finally:
            self.direct_value = None

    def translate_to(self, op, name):
        self.set_pref("language" if op == "translate" else "clip_language", name)
        if op == "translate" and name:
            self.last_language = name
        self.direct = True
        try:
            self.tool(op)
        finally:
            self.direct = False

    def qr_from_clipboard(self):
        from .extra_dialogs import QRDialog
        try:
            text = self.win.clipboard_get()
        except tk.TclError:
            text = ""
        if not text.strip():
            self.say("Copie um texto ou link primeiro")
            return
        self.safe_dialog(QRDialog, text)

    def utility(self, op):
        """Utilidades: não usam os arquivos da lista."""
        if op == "qr":
            from .extra_dialogs import QRDialog
            self.safe_dialog(QRDialog)
        elif op == "cleanup":
            from .extra_dialogs import CleanupDialog
            self.safe_dialog(CleanupDialog)
        elif op == "cliphist":
            from .extra_dialogs import ClipHistoryDialog
            self.safe_dialog(ClipHistoryDialog)
        elif op == "summary":
            from .extra_dialogs import SummaryDialog
            self.safe_dialog(SummaryDialog)
        elif op == "uninstall":
            from .extra_dialogs import uninstall_app
            from .platform_mac import activate
            activate()
            self.safe_dialog(uninstall_app)
        elif op == "scrollshot":
            from . import scrollshot_ui
            self.safe_dialog(scrollshot_ui.start)
        elif op == "awake":
            on = self.awake.toggle()
            self.say("O Mac não vai dormir até você desligar" if on else "O Mac pode dormir de novo", BLUE)
        else:
            from . import utility_dialogs as ud
            from .platform_mac import activate
            activate()
            self.safe_dialog({"speed_test": ud.SpeedDialog, "wifi": ud.WifiDialog, "battery": ud.BatteryDialog,
                              "unblock": ud.unblock_app}[op])

    def list_height(self):
        """A lista de arquivos ganha um terço da altura extra; o resto vai para os botões."""
        return FILES_H + max(0, self.h - H) // 3

    def resized(self, width, height):
        from ..core import prefs
        self.w, self.h = width, height
        self.files_h = self.list_height()
        self.row_h = None  # refaz a divisão dos quadrados sem animação
        self.save_size = (width, height)
        if not getattr(self, "size_timer", None):
            def save():
                self.size_timer = None
                prefs.put("window_size", list(self.save_size))
            self.size_timer = self.root.after(400, save)

    def hide_window(self):
        """Fecha a janela; o Treco continua na barra de menus (e, se escolhido, sai do Dock)."""
        self.win.withdraw()
        if MAC:
            from ..core import prefs
            if prefs.get("hide_dock"):
                try:
                    from . import platform_mac
                    platform_mac.dock_visible(False)
                except Exception as error:
                    log_error("esconder do Dock", error)

    def quit(self):
        if self.recording:
            self.recording.shutdown()
        if self.awake:
            self.awake.stop()
        self.shutdown()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.after(50, self.root.destroy)

    # ------------------------------------------------ arquivos
    def on_drop(self, event):
        self.hl(False)
        self.add_files(self.root.tk.splitlist(event.data))
        return "copy"  # nunca deixa o Explorer apagar o original

    def dialog_owner(self):
        # No Mac, preso a uma janela sem moldura o seletor abriria como folha quebrada.
        return {} if MAC else {"parent": self.root}

    def pick_files(self):
        self.add_files(filedialog.askopenfilenames(title=tr("Escolha os arquivos"), **self.dialog_owner()))

    def pick_folder(self):
        folder = filedialog.askdirectory(title=tr("Adicionar pasta"), **self.dialog_owner())
        if folder:
            self.add_files([folder])

    def add_files(self, paths):
        for p in paths:
            if os.path.isdir(p):
                for base, _, names in os.walk(p):
                    self.add_files([os.path.join(base, n) for n in names])
                continue
            kind = kind_of(p)
            if kind and p not in self.rows:
                self.rows[p] = Row(p, kind)
        self.notice = None
        self.host.invalidate()

    def close_row(self, path):
        row = self.rows.get(path)
        if not row:
            return
        if row.job:  # tarefa longa: o primeiro clique cancela
            row.job.cancel()
            row.status, row.tone = "cancelando…", None
            self.host.invalidate()
        elif not row.busy:
            self.remove(path)

    def remove(self, path):
        self.rows.pop(path, None)
        self.host.invalidate()

    def clear(self):
        for p, row in list(self.rows.items()):
            if not row.busy:
                self.rows.pop(p)
        self.scroll = 0
        self.host.invalidate()

    def choose_dest(self):
        folder = filedialog.askdirectory(title=tr("Salvar em…"), **self.dialog_owner())
        self.out_dir = folder or None
        self.host.invalidate()

    def open_folder(self):
        folder = self.out_dir or self.last_dir
        if folder and os.path.isdir(folder):
            if MAC:
                subprocess.Popen(["open", folder])
            else:
                os.startfile(folder)
        else:
            self.notice = ("Converta algo primeiro", DARK)
            self.host.invalidate()
            self.root.after(2500, self.clear_notice)

    def clear_notice(self):
        self.notice = None
        self.host.invalidate()

    # ------------------------------------------------ tarefas
    def animate(self):
        if any(r.busy for r in self.rows.values()):
            self.host.invalidate()
            self.root.after(100, self.animate)
        else:
            self.animating = False
            self.host.invalidate()

    def start_row(self, row, job, action):
        row.action = action
        row.working(job)
        if not self.animating:
            self.animating = True
            self.animate()

    def new_job(self, path, verb, label=None):
        """Cria a tarefa e liga a linha da lista à mini barra do mouse."""
        task = self.pill.begin(label or f"{verb} {os.path.basename(path)}")
        self.tasks[path] = task

        def progress(fraction):
            self.root.after(0, self.show_progress, path, fraction)
            self.pill.update(task, fraction)
        return Job(progress)

    def show_progress(self, path, fraction):
        row = self.rows.get(path)
        if row and row.busy:
            row.progress = fraction
            row.sub = f"{row.action}… {int(fraction * 100)}%"
            self.host.invalidate()

    def finish_row(self, path, ok, text, dst, detail=None):
        task = self.tasks.pop(path, None)
        if task is not None:
            self.pill.end(task, ok)

        def apply():
            if path in self.rows:
                self.rows[path].finished(ok, text, dst, detail)
                self.host.invalidate()
        self.root.after(0, apply)

    def convert_all(self, kind, fmt):
        self.convert_paths([p for p, r in self.rows.items() if r.kind == kind], fmt)

    def convert_paths(self, paths, fmt):
        self.add_files(paths)
        for p in paths:
            row = self.rows.get(p)
            if row and fmt in OUTS[row.kind] and not row.busy:
                job = self.new_job(p, "Convertendo")
                self.start_row(row, job, "Convertendo")
                self.pool.submit(self.convert_one, p, row.kind, fmt, self.quality, job)

    def convert_one(self, src, kind, fmt, quality, job=None):
        try:
            dst = convert_file(src, kind, fmt, quality, self.out_dir, job)
            self.last_dir = os.path.dirname(dst)
            self.finish_row(src, True, f"✓ {fmt}", dst)
        except Cancelled:
            self.finish_row(src, None, "cancelado", None)
        except Exception as e:
            self.finish_row(src, False, str(e)[:24] or "erro", None)
            log_error(f"converter {os.path.basename(src)} para {fmt}", e)

    def compress_target(self):
        try:
            value = float(self.target.text.strip().replace(",", "."))
            if not 0.01 <= value <= 100000:
                raise ValueError
        except ValueError:
            self.notice = ("Digite um tamanho, como 16 ou 1,5", RED)
            self.host.invalidate()
            self.root.after(3000, self.clear_notice)
            return
        self.compress_all(int(value * MB))

    def compress_all(self, mode):
        self.compress_paths(list(self.rows), mode)

    def compress_paths(self, paths, mode, notify=False):
        self.add_files(paths)
        targets = [p for p in paths if p in self.rows and self.rows[p].kind in COMPRESSIBLE and not self.rows[p].busy]
        batch = {"left": len(targets), "before": 0, "after": 0, "failed": 0, "notify": notify, "lock": threading.Lock()}
        for p in targets:
            row = self.rows[p]
            job = self.new_job(p, "Comprimindo")
            self.start_row(row, job, "Comprimindo")
            self.pool.submit(self.compress_one, p, row.kind, mode, job, batch)

    def compress_one(self, src, kind, mode, job, batch):
        before = after = failed = 0
        try:
            result = compress_file(src, kind, mode, self.out_dir, job)
            before, after = result.before, result.after
            self.last_dir = os.path.dirname(result.path)
            saved = min(99, round((1 - after / before) * 100))
            self.finish_row(src, True, f"✓ −{saved}%", result.path, f"{human_size(before)} → {human_size(after)}")
        except NothingToGain as e:
            self.finish_row(src, None, str(e), None)
        except Cancelled:
            self.finish_row(src, None, "cancelado", None)
        except Exception as e:
            failed = 1
            self.finish_row(src, False, str(e)[:24] or "erro", None)
            log_error(f"comprimir {os.path.basename(src)} ({mode})", e)
        with batch["lock"]:
            batch["left"] -= 1
            batch["before"] += before
            batch["after"] += after
            batch["failed"] += failed
            done = batch["left"] == 0
        if done and batch["notify"] and self.tray:
            text = f"{human_size(batch['before'])} → {human_size(batch['after'])}" if batch["before"] else "Nada precisou ser comprimido."
            if batch["failed"]:
                text += f" · {batch['failed']} com erro"
            self.safe_notify(text, "Treco: compressão concluída")

    def safe_notify(self, text, title):
        try:
            self.tray.notify(text, title)
        except Exception:
            pass

    def transform_all(self, operation):
        self.transform_paths(list(self.rows), operation)

    def transform_paths(self, paths, operation, notify=False):
        self.add_files(paths)
        targets = [p for p in paths if p in self.rows and self.rows[p].kind in EDITABLE and not self.rows[p].busy]
        batch = {"left": len(targets), "failed": 0, "notify": notify, "lock": threading.Lock()}
        for p in targets:
            row = self.rows[p]
            job = self.new_job(p, "Editando")
            self.start_row(row, job, "Editando")
            self.pool.submit(self.transform_one, p, row.kind, operation, job, batch)

    def transform_one(self, src, kind, operation, job, batch):
        failed = 0
        try:
            result = transform_file(src, kind, operation, self.out_dir, job)
            self.last_dir = os.path.dirname(result.path)
            self.finish_row(src, True, "✓ pronto", result.path, human_size(result.after))
        except Cancelled:
            self.finish_row(src, None, "cancelado", None)
        except Exception as e:
            failed = 1
            batch["reason"] = str(e)[:90]
            self.finish_row(src, False, str(e)[:24] or "erro", None)
            log_error(f"editar {os.path.basename(src)} ({operation})", e)
        with batch["lock"]:
            batch["left"] -= 1
            batch["failed"] += failed
            done = batch["left"] == 0
        if done and batch["notify"] and self.tray:
            if batch["failed"]:
                self.safe_notify(batch.get("reason", "erro"), "Treco: não consegui editar")
            else:
                self.safe_notify("Arquivo pronto na mesma pasta.", "Treco: edição concluída")

    # ------------------------------------------------ edição rápida
    def tool(self, op, paths=None):
        """Abre ou executa uma ferramenta nos arquivos compatíveis."""
        if op in RECORD_OPS:
            if self.recording and self.recording.busy:
                self.recording.stop()
            elif self.recording:
                self.recording.start(op)
            return
        if op == "clip":
            from ..core import prefs
            from ..modules.translate import LANGUAGES
            from .actions_mac import translate_clipboard
            translate_clipboard(self, {n: c for n, c, _ in LANGUAGES}.get(prefs.get("clip_language")))
            return
        if op in {u[0] for u in UTILITIES}:
            self.utility(op)
            return
        if op == "caption":
            if not any(r.kind == "video" and not r.busy for r in self.rows.values()):
                self.say("Adicione um vídeo primeiro")
            else:
                self.caption_all()
            return
        accepted = next(t[3] for t in TOOLS + MORE_TOOLS if t[0] == op)
        if paths is not None:
            self.add_files(paths)
        source = list(self.rows) if paths is None else paths
        targets = [p for p in source if p in self.rows and self.rows[p].kind in accepted and not self.rows[p].busy]
        if not targets:
            self.say("Nenhum arquivo compatível livre agora")
            return
        if op in ROTATIONS:
            self.transform_paths(targets, op, notify=paths is not None)
        elif op in ("nobg", "ocr", "faces"):
            self.run_quick(targets, op, {}, notify=paths is not None)
        elif op == "transcribe":
            from .tool_dialogs import TranscribeDialog
            self.safe_dialog(TranscribeDialog, targets)
        elif op == "lock":
            self.dialog_queue = [("lock", p) for p in targets]
            self.next_dialog()
        elif op == "mark":
            from .tool_dialogs import WatermarkDialog
            self.safe_dialog(WatermarkDialog, targets)
        elif op == "translate":
            from ..core import prefs
            from ..modules.translate import LANGUAGES
            codes = {n: c for n, c, _ in LANGUAGES}
            if self.direct and prefs.get("language") in codes:  # escolhido no botão direito: traduz direto
                self.run_quick(targets, "translate", {"target": codes[prefs.get("language")]})
            else:
                from .tool_dialogs import TranslateDialog
                self.safe_dialog(TranslateDialog, targets)
        elif op == "photos_pdf":
            from ..core import prefs
            self.run_many(op, targets, {"page": prefs.get("pdf_page"), "margin": prefs.get("pdf_margin")})
        elif op == "slideshow":
            if len(targets) < 2:
                self.say("Adicione 2 ou mais fotos")
            elif self.direct:
                self.run_many(op, targets, self.slide_params())
            else:
                from .tool_dialogs import SlideshowDialog
                self.safe_dialog(SlideshowDialog, targets)
        elif op == "scan":
            from ..core import prefs
            params = {"color": prefs.get("scan_color"), "crop": prefs.get("scan_crop")}
            if prefs.get("scan_separate") or len(targets) == 1:
                self.run_quick(targets, "scan", params, notify=paths is not None)
            else:
                self.run_many(op, targets, params)
        elif op == "rename":
            from .tool_dialogs import RenameDialog
            self.safe_dialog(RenameDialog, targets)
        elif op in ("mute", "volume", "clean"):
            self.run_quick(targets, op, {}, notify=paths is not None)
        elif op in ("trim", "crop", "split"):
            self.dialog_queue = [(op, p) for p in targets]
            self.next_dialog()
        elif op == "resize":
            from .tool_dialogs import ResizeDialog
            self.safe_dialog(ResizeDialog, targets)
        elif op == "speed":
            from .tool_dialogs import SpeedDialog
            self.safe_dialog(SpeedDialog, targets)
        elif op == "slow":
            if self.direct_value:  # porcentagem escolhida no botão direito
                self.run_quick(targets, "speed", {"factor": self.direct_value / 100}, notify=paths is not None)
            else:
                from .tool_dialogs import SlowDialog
                self.safe_dialog(SlowDialog, targets)
        elif op == "join":
            groups = {}
            for p in targets:
                groups.setdefault(self.rows[p].kind, []).append(p)
            kind, group = max(groups.items(), key=lambda item: len(item[1]))
            if len(group) < 2:
                self.say("Juntar precisa de 2 arquivos do mesmo tipo")
                return
            from .tool_dialogs import JoinDialog
            self.safe_dialog(JoinDialog, group, kind)

    def say(self, text, color=RED):
        self.notice = (text, color)
        self.host.invalidate()
        self.root.after(3200, self.clear_notice)

    def safe_dialog(self, factory, *args, **kwargs):
        try:
            factory(self, *args, **kwargs)
        except Exception as e:
            log_error("abrir ferramenta", e)
            self.say(str(e)[:44] or "não consegui abrir")

    def next_dialog(self):
        if not self.dialog_queue:
            return
        from .tool_dialogs import CropDialog, PasswordDialog, SplitDialog, TrimDialog
        op, path = self.dialog_queue.pop(0)
        row = self.rows.get(path)
        if row is None or row.busy:
            self.next_dialog()
        elif op == "trim":
            self.safe_dialog(TrimDialog, path, row.kind, on_close=self.next_dialog)
        elif op == "crop":
            self.safe_dialog(CropDialog, path, row.kind, on_close=self.next_dialog)
        elif op == "lock":
            self.safe_dialog(PasswordDialog, path, on_close=self.next_dialog)
        else:
            self.safe_dialog(SplitDialog, path, on_close=self.next_dialog)

    def run_quick(self, paths, op, params, notify=False):
        targets = [p for p in paths if p in self.rows and not self.rows[p].busy]
        batch = {"left": len(targets), "failed": 0, "done": 0, "notify": notify, "lock": threading.Lock()}
        for p in targets:
            row = self.rows[p]
            verb = QUICK_VERBS[op]
            job = self.new_job(p, verb)
            self.start_row(row, job, verb)
            self.pool.submit(self.quick_one, p, row.kind, op, params, job, batch)

    def quick_one(self, src, kind, op, params, job, batch):
        from ..modules import quick
        failed = done = 0
        try:
            folder = self.out_dir
            if op == "trim":
                result = quick.trim(src, kind, params["start"], params["end"], params["exact"], folder, job)
            elif op == "crop":
                result = quick.crop(src, kind, params["x"], params["y"], params["w"], params["h"], folder, job)
            elif op == "resize":
                result = quick.resize(src, kind, params, folder, job)
            elif op == "mute":
                result = quick.mute(src, folder, job)
            elif op == "speed":
                result = quick.speed(src, kind, params["factor"], folder, job)
            elif op == "volume":
                result = quick.volume(src, kind, folder, job)
            elif op == "clean":
                result = quick.clean(src, kind, folder, job)
            elif op in ("transcribe", "nobg", "ocr", "faces", "lock", "unlock", "mark", "translate", "scan"):
                result = self.more_one(src, kind, op, params, folder, job)
            else:
                result = quick.split_pdf(src, params["ranges"], folder, job)
            done = 1
            self.last_dir = os.path.dirname(result.path)
            detail = f"{len(os.listdir(result.path))} arquivos" if os.path.isdir(result.path) else human_size(result.after)
            self.finish_row(src, True, "✓ pronto", result.path, detail)
        except NothingToGain as e:
            self.finish_row(src, None, str(e), None)
        except Cancelled:
            self.finish_row(src, None, "cancelado", None)
        except Exception as e:
            failed = 1
            batch["reason"] = str(e)[:90]
            self.finish_row(src, False, str(e)[:24] or "erro", None)
            log_error(f"{op} {os.path.basename(src)}", e)
        with batch["lock"]:
            batch["left"] -= 1
            batch["failed"] += failed
            batch["done"] += done
            finished = batch["left"] == 0
        if finished and batch["notify"] and self.tray:
            if batch["failed"]:
                self.safe_notify(batch.get("reason", "erro"), "Treco: não deu certo")
            elif batch["done"]:
                self.safe_notify("Arquivo pronto na mesma pasta.", "Treco: edição concluída")

    def more_one(self, src, kind, op, params, folder, job):
        from ..modules import extras
        if op == "transcribe":
            return extras.transcribe(src, params["format"], params["language"], folder, job)
        if op == "nobg":
            return extras.remove_background(src, folder, job)
        if op == "ocr":
            return extras.extract_text(src, kind, folder, job)
        if op == "faces":
            return extras.hide_faces(src, folder, job)
        if op == "lock":
            return extras.pdf_lock(src, params["password"], folder, job)
        if op == "unlock":
            return extras.pdf_unlock(src, params["password"], folder, job)
        if op == "translate":
            from ..modules import translate
            return translate.translate_file(src, kind, params["target"], folder, job)
        if op == "scan":
            from ..modules import paper
            return paper.scan_to_pdf([src], params["color"], params["crop"], folder, job)
        return extras.watermark(src, kind, params["text"], params["position"], folder, job)

    def rename_rows(self, plan):
        """Renomeia de verdade e atualiza a lista, mantendo a ordem."""
        from ..modules import extras
        try:
            done = dict(extras.rename_apply(plan))
        except Exception as e:
            log_error("renomear", e)
            self.say(str(e)[:44] or "não consegui renomear")
            return False
        rows = {}
        for path, row in self.rows.items():
            new = done.get(path)
            if new:
                row = Row(new, row.kind)
                row.status, row.tone = "✓ renomeado", True
            rows[new or path] = row
        self.rows = rows
        self.host.invalidate()
        return True

    def run_many(self, op, paths, params):
        """Várias fotos viram um arquivo só; a primeira linha da lista mostra o andamento."""
        row = self.rows.get(paths[0])
        if row is None:
            return
        verb = QUICK_VERBS[op]
        job = self.new_job(paths[0], verb, f"{verb} {len(paths)} fotos")
        self.start_row(row, job, verb)
        self.pool.submit(self.many_worker, op, list(paths), params, job)

    def many_worker(self, op, paths, params, job):
        from ..modules import paper
        src = paths[0]
        try:
            if op == "photos_pdf":
                result = paper.photos_to_pdf(paths, params["page"], params["margin"], self.out_dir, job)
            elif op == "slideshow":
                from ..modules import slideshow
                result = slideshow.make(paths, folder=self.out_dir, job=job, **params)
            else:
                result = paper.scan_to_pdf(paths, params["color"], params["crop"], self.out_dir, job)
            self.last_dir = os.path.dirname(result.path)
            unit = "fotos" if op == "slideshow" else "páginas"
            self.finish_row(src, True, "✓ pronto", result.path, f"{len(paths)} {unit} · {human_size(result.after)}")
        except Cancelled:
            self.finish_row(src, None, "cancelado", None)
        except Exception as e:
            self.finish_row(src, False, str(e)[:24] or "erro", None)
            log_error(f"{op} {os.path.basename(src)}", e)

    def run_join(self, paths, kind):
        row = self.rows.get(paths[0])
        if row is None or any(p in self.rows and self.rows[p].busy for p in paths):
            self.say("Espere os arquivos terminarem")
            return
        job = self.new_job(paths[0], "Juntando")
        self.start_row(row, job, "Juntando")
        self.pool.submit(self.join_worker, list(paths), kind, job)

    def join_worker(self, paths, kind, job):
        from ..modules import quick
        src = paths[0]
        try:
            result = quick.join(paths, kind, self.out_dir, job)
            self.last_dir = os.path.dirname(result.path)
            self.finish_row(src, True, "✓ juntado", result.path, f"{len(paths)} itens · {human_size(result.after)}")
        except Cancelled:
            self.finish_row(src, None, "cancelado", None)
        except Exception as e:
            self.finish_row(src, False, str(e)[:24] or "erro", None)
            log_error(f"juntar {os.path.basename(src)}", e)

    # ------------------------------------------------ baixar da internet
    def paste_url(self):
        try:
            text = self.win.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if text:
            self.url.set(text[:self.url.limit])
            self.host.focus = "url"
        self.host.invalidate()

    def start_download(self):
        from ..modules import download
        url = download.clean_url(self.url.text)
        if not url:
            self.say("Cole um link válido")
            return
        if url in self.rows:
            self.say("Esse link já está baixando")
            return
        site = download.site_name(url)
        quality = self.dl_quality
        folder = self.out_dir or os.path.expanduser("~/Downloads")
        row = Row(url, "audio" if quality == download.AUDIO else "video")
        row.name, row.sub = site, "Procurando o vídeo…"
        self.rows[url] = row
        self.notice = None
        job = self.new_job(url, "Baixando", f"Baixando de {site}")
        self.start_row(row, job, "Baixando")
        self.url.set("")
        self.host.focus = None
        self.pool.submit(self.download_worker, url, quality, folder, job)

    def download_worker(self, url, quality, folder, job):
        from ..modules import download
        try:
            result = download.fetch(url, quality, folder, job)
            self.root.after(0, self.download_done, url, result)
        except Cancelled:
            self.root.after(0, self.download_failed, url, None, "Download cancelado")
        except Exception as error:
            log_error(f"baixar de {download.site_name(url)}", error)
            self.root.after(0, self.download_failed, url, False, download.friendly(error))

    def download_done(self, url, result):
        task = self.tasks.pop(url, None)
        if task is not None:
            self.pill.end(task, True)
        old = self.rows.get(url)
        kind = kind_of(result.path) or (old.kind if old else "video")
        new = Row(result.path, kind)
        new.finished(True, "✓ baixado", result.path)
        new.sub = new.size if result.total <= 1 else f"{new.size} · 1º de {result.total}"
        self.rows = {(result.path if key == url else key): (new if key == url else row) for key, row in self.rows.items()}
        self.rows.setdefault(result.path, new)
        self.last_dir = os.path.dirname(result.path)
        self.host.invalidate()

    def download_failed(self, url, ok, message):
        task = self.tasks.pop(url, None)
        if task is not None:
            self.pill.end(task, ok)
        self.rows.pop(url, None)  # a linha do link não é um arquivo: não pode ficar na lista
        self.say(message, DARK if ok is None else RED)

    # ------------------------------------------------ legenda rápida
    def caption_all(self):
        self.open_captions([p for p, r in self.rows.items() if r.kind == "video" and not r.busy])

    def open_captions(self, paths):
        self.caption_queue = list(paths)
        self.next_caption()

    def next_caption(self):
        if not self.caption_queue:
            return
        from .caption_editor import CaptionEditor
        path = self.caption_queue.pop(0)
        self.add_files([path])
        CaptionEditor(self, path, on_close=self.next_caption)

    def start_caption(self, path, segments, style, on_progress, on_done):
        from ..modules import captions
        task = self.pill.begin(f"Legendando {os.path.basename(path)}")
        self.tasks[path] = task

        def progress(fraction):
            self.root.after(0, self.show_progress, path, fraction)
            self.pill.update(task, fraction)
            on_progress(fraction)

        job = Job(progress)
        row = self.rows.get(path)
        if row:
            self.start_row(row, job, "Legendando")

        def work():
            try:
                result = captions.burn(path, segments, style, self.out_dir, job)
                self.last_dir = os.path.dirname(result.path)
                self.finish_row(path, True, "✓ legendado", result.path, human_size(result.after))
                on_done(True, f"Pronto: {os.path.basename(result.path)}")
                if self.tray:
                    self.safe_notify(os.path.basename(result.path), "Treco: vídeo legendado")
            except Cancelled:
                self.finish_row(path, None, "cancelado", None)
                on_done(None, "Cancelado.")
            except Exception as e:
                self.finish_row(path, False, str(e)[:24] or "erro", None)
                log_error(f"legendar {os.path.basename(path)}", e)
                on_done(False, str(e)[:80])
        self.pool.submit(work)
        return job

    def shutdown(self):
        for row in self.rows.values():
            if row.job:
                row.job.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)
