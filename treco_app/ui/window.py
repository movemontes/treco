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
from . import mascot
from .icons import KIND_ICON
from .pill import ProgressPill
from .pixel import BLUE, CREAM, DARK, GRAY, INK, RED, SKY, WHITE, fit, mix, text_width
from .toolkit import PixelHost, TextField, pick_scale

try:
    from tkinterdnd2 import DND_FILES
    DND_OK = True
except Exception:
    DND_OK = False

W, H = (440, 540) if MAC else (420, 420)  # no Windows, quase quadrada
MIN_W, MIN_H = 340, 420  # menor que isso os botões não cabem
RAIL_W, TOP_H, BAR_H = 66, 24, 34  # trilho preto à esquerda, faixa de cima e barra de baixo
PAD, CHIP_H = 12, 17  # margem da área principal e altura das etiquetas de arquivo
HEADER_H, FOOTER_H = TOP_H, BAR_H  # nomes antigos (usados por outras janelas)
# categorias da tela; as três primeiras só aparecem com arquivo na lista
CATEGORIES = (("convert", "Converter", "convert"), ("compress", "Comprimir", "compress"), ("edit", "Editar", "edit"),
              ("av", "Vídeo e áudio", "video"), ("image", "Imagem", "image"), ("docs", "Documentos", "doc"),
              ("download", "Baixar", "download"), ("utils", "Utilidades", "tools"))
TABS = CATEGORIES
NEEDS_FILES = {"convert", "compress", "edit"}
RAIL_LABEL = {"av": "Vídeo", "docs": "Docs"}  # nomes curtos no trilho
LEADS = {"convert": "Escolha o formato novo. O original fica como está.",
         "compress": "Deixa o arquivo menor para mandar ou guardar.",
         "edit": "Gire, corte e ajuste todos os arquivos da lista.",
         "av": "Legenda, silêncios, voz limpa, BPM e gravação.",
         "image": "Fotos em PDF, fundo, texto e rostos.",
         "docs": "Assinatura, páginas, tarja, senha e tradução.",
         "download": "Cole o link de um vídeo da internet.",
         "utils": "Atalhos rápidos para o dia a dia no Mac."}
# frase curta embaixo do nome de cada ação nos cartões
DESC = {"direita": "Gira 90° para a direita", "esquerda": "Gira 90° para a esquerda", "180": "Vira de ponta-cabeça",
        "espelhar": "Inverte de lado, como espelho", "inverter": "Vira de cima para baixo",
        "trim": "Fica só o trecho que você marcar", "crop": "Tira as bordas", "resize": "Menor, maior ou 1080p",
        "mute": "Tira o áudio do vídeo", "speed": "Deixa mais rápido", "slow": "Câmera lenta",
        "volume": "Som mais alto ou mais baixo", "clean": "Tira dados escondidos do arquivo",
        "join": "Junta tudo num arquivo só", "split": "Separa as páginas do PDF"}
# botões de cada categoria (os que não existem neste computador somem sozinhos)
TAB_TOOLS = {"av": ("caption", "transcribe", "silence", "voice", "tempo", "mark", "rec_voice", "rec_screen", "rec_both"),
             "image": ("photos_pdf", "scan", "slideshow", "nobg", "ocr", "faces", "mark"),
             "docs": ("sign", "pages", "redact", "summary", "scan", "ocr", "lock", "translate", "clip", "rename"),
             "utils": ("lens", "dupes", "cleanup", "uninstall", "magic", "cliphist", "scrollshot", "picker", "qr", "awake",
                       "speed_test", "wifi", "battery", "unblock")}
CAPTION_TOOL = ("caption", "Legendar", "caption", {"video"})
QUICK_VERBS = {"trim": "Cortando", "crop": "Recortando", "resize": "Redimensionando", "mute": "Silenciando",
               "speed": "Ajustando", "volume": "Nivelando", "clean": "Limpando", "split": "Separando",
               "transcribe": "Transcrevendo", "nobg": "Recortando", "ocr": "Lendo", "faces": "Borrando",
               "lock": "Protegendo", "unlock": "Destravando", "mark": "Marcando", "translate": "Traduzindo",
               "photos_pdf": "Juntando", "scan": "Escaneando", "slideshow": "Montando",
               "silence": "Cortando", "voice": "Limpando", "pages": "Organizando", "redact": "Escondendo",
               "sign": "Assinando"}
RECORD_OPS = ("rec_voice", "rec_screen", "rec_both")
# utilidades do Mac (ação, nome, ícone); "qr" funciona em qualquer sistema
UTILITIES = (("cleanup", "Limpar Downloads", "trash"), ("uninstall", "Desinstalar app", "uninstall"),
             ("cliphist", "Histórico de cópias", "history"), ("scrollshot", "Captura com rolagem", "scrollshot"),
             ("summary", "Resumir página", "summary"), ("qr", "QR Code", "qr"), ("awake", "Mac acordado", "awake"),
             ("speed_test", "Teste de internet", "gauge"), ("wifi", "Senha do Wi-Fi", "wifi"),
             ("battery", "Bateria", "battery"), ("unblock", "Liberar app", "unlock"),
             ("lens", "Lupa de espaço", "lens"), ("dupes", "Arquivos repetidos", "dupes"),
             ("magic", "Pasta mágica", "magic"), ("picker", "Conta-gotas", "picker"))
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
        "summary": "A IA do Mac resume um link da internet", "unblock": "Abre app que o Mac diz estar danificado",
        "tempo": "Descobre o andamento e o tom da música", "silence": "Tira as pausas da fala",
        "voice": "Tira chiado, ruído e eco da gravação", "sign": "Põe sua assinatura no PDF",
        "pages": "Gira, troca de lugar ou tira páginas", "redact": "Esconde CPF e outros dados de verdade",
        "lens": "Mostra o que ocupa espaço no disco", "dupes": "Acha arquivos iguais para apagar",
        "magic": "O que cair na pasta é convertido sozinho", "picker": "Pega a cor de qualquer ponto da tela"}


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
        try:  # PC/Mac acordado e histórico de cópias (nos dois sistemas)
            from ..core import prefs
            from ..modules.cliphistory import Watcher
            if MAC:
                from ..modules.mac_utils import KeepAwake
            else:
                from ..modules.win_utils import KeepAwake
            self.awake = KeepAwake()
            self.clips = Watcher(root, enabled=lambda: prefs.get("clip_history"))
            self.clips.start()
        except Exception as error:
            log_error("utilidades", error)
        if MAC:
            from ..modules import recorder
            if recorder.available():
                from .actions_mac import RecorderControl
                self.recording = RecorderControl(self)
        self.pill = ProgressPill(root, self.scale)
        from ..modules.magic import Watcher
        self.magic = Watcher(self.magic_done)
        root.after(3000, self.magic.start)
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
        self.tour = None  # passo do tour do Disquetinho (None = fora do tour)
        self.tip = None  # dica que o mouse está esperando: (chave, área, texto)
        self.tip_key, self.tip_since = None, 0.0
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
        ui.enabled = self.menu is None and not self.about and self.context_menu is None and self.tour is None
        self.tip = None
        kinds = {r.kind for r in self.rows.values()}
        if self.tab is None and self.rows:
            self.tab = "convert"  # chegou arquivo: já mostra Converter
        self.draw_main(ui, kinds)
        self.draw_footer(ui)
        self.draw_rail(ui, kinds)
        ui.enabled = not self.about and self.tour is None
        self.draw_header(ui)
        if self.tour is not None:
            ui.enabled = True
            self.draw_tour(ui)
        elif self.about:
            ui.enabled = True
            self.draw_about(ui)
        elif self.context_menu:
            ui.enabled = True
            self.draw_context(ui)
        if not self.about and self.tour is None:
            ui.draw_grip(INK)
        self.draw_tip(ui)

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
        """Faixa de cima da área principal: situação, minimizar e fechar. O menu do Treco abre no logo."""
        g = ui.g
        x0 = RAIL_W
        text, color = self.status_line()
        g.text(x0 + PAD, 9, fit(text, self.w - x0 - PAD - 60), DARK if color == INK else color, False, .9)
        for key, kx, name, action in (("min", self.w - 44, "min", self.host.minimize), ("hide", self.w - 24, "x", self.hide_window)):
            over, held, clicked = ui.clickable(("win", key), kx, 5, 15, 15)
            ui.face(kx, 5, 15, 15, over, held, key=("win", key))
            ui.g.icon(name, kx + 2 + ui.shift, 7 + ui.shift, 11, ui.ink(over, held))
            if clicked:
                ui.later(action)
        if self.menu is None:
            ui.drag_area(x0, 0, self.w - x0 - 50, TOP_H)
            return
        items = self.menus()["Treco"]
        mw = max(text_width(i[0], True) for i in items if i) + 24
        mh = sum(17 if i else 5 for i in items) + 6
        mx, my = 8, 52
        g.rect(mx + 3, my + 3, mw, mh, fill=BLUE)
        g.rect(mx, my, mw, mh, fill=WHITE, line=INK)
        g.rect(mx + 1, my + 1, mw - 2, mh - 2, line=INK)
        iy = my + 3
        inside = ui.over(mx, my, mw, mh)
        for item in items:
            if item is None:
                g.hline(mx, iy + 2, mw, INK)
                iy += 5
                continue
            over = ui.over(mx + 2, iy, mw - 4, 17)
            if over:
                g.rect(mx + 2, iy, mw - 4, 17, fill=BLUE)
            g.text(mx + 10, iy + 4, item[0], WHITE if over else INK, over)
            if over and ui.released:
                self.menu = None
                ui.later(item[1])
                ui.later(ui.invalidate)
            iy += 17
        if ui.pressed and not inside and not ui.over(0, 0, RAIL_W, 52):
            self.menu = None
            ui.later(ui.invalidate)

    def menus(self):
        from .tray import autostart_on, autostart_toggle
        start = "Iniciar com o Mac" if MAC else "Iniciar com o Windows"
        return {"Treco": [("Adicionar arquivos…", self.pick_files), ("Adicionar pasta…", self.pick_folder), None,
                          (("✓ " if autostart_on() else "") + tr(start), autostart_toggle),
                          (("✓ " if mascot.enabled() else "") + tr("Disquetinho"), self.toggle_mascot),
                          ("Ver o tour", self.start_tour), ("Sobre o Treco", self.show_about), None,
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

    # --- trilho preto à esquerda: o logo (abre o menu) e os assuntos, um embaixo do outro
    def draw_rail(self, ui, kinds):
        g = ui.g
        g.rect(0, 0, RAIL_W, self.h, fill=INK)
        lx = (RAIL_W - 40) // 2
        hover, held, clicked = ui.clickable(("menu", "Treco"), lx, 9, 40, 40)
        open_ = self.menu == "Treco"
        self.spots[("logo",)] = (lx, 9, 40, 40)
        if hover and not open_:
            self.want_tip("logo", (lx, 9, 40, 40), mascot.TIPS["logo"])
        t = ui.ease(("logo",), 1.0 if hover or open_ else 0.0)
        lift = 1 if t > .5 and not held else 0
        if t > 0 or open_:  # quadrado azul atrás do Disquetinho ao passar o mouse
            g.rect(lx - 2, 7, 44, 44, fill=mix(INK, BLUE, 1.0 if open_ else t))
        face = mascot.sprite("rosto", 40, g.s)
        g.put(face, lx + (40 - face.width // g.s) // 2, 9 - lift)
        if clicked:
            self.menu = None if open_ else "Treco"
            ui.later(ui.invalidate)
        cats = list(CATEGORIES)
        top, bottom = 60, self.h - 6
        each = min(44, (bottom - top) / len(cats))
        pinned = each >= 40 and (bottom - top) - each * len(cats) > 20  # sobra: Utilidades vai para o pé
        for i, (key, label, image) in enumerate(cats):
            y = round(top + i * each)
            if pinned and key == "utils":
                y = round(bottom - each)
            self.rail_item(ui, key, RAIL_LABEL.get(key, label), image, y, round(each) - 3,
                           key not in NEEDS_FILES or bool(kinds))

    def rail_item(self, ui, key, label, image, y, h, ready):
        g = ui.g
        x, w = 5, RAIL_W - 10
        selected = self.tab == key
        self.spots[("cat", key)] = (x, y, w, h)
        hover, held, clicked = ui.clickable(("cat", key), x, y, w, h)
        if hover:
            self.want_tip(("cat", key), (x, y, w, h), LEADS.get(key, ""))
        t = ui.ease(("rail", key), 1.0 if hover and not selected else 0.0)
        if selected:
            g.rect(x + 2, y + 2, w, h, fill=BLUE)
            g.rect(x, y, w, h, fill=WHITE)
            color = INK
        else:
            if t > 0:
                g.rect(x, y, w, h, fill=mix(INK, BLUE, t))
            color = WHITE  # sem arquivo também fica branco: cinza parecia botão desligado
        if held:
            g.rect(x, y, w, h, fill=BLUE)
            color = WHITE
        icon = 16 if h >= 34 else 13
        top = y + (h - icon - (11 if h >= 30 else 0)) // 2
        g.icon(image, x + (w - icon) // 2, top, icon, color)
        if h >= 30:
            g.center(x, top + icon + 4, w, fit(label.upper() if not english() else tr(label).upper(), int((w - 2) / .66), True),
                     color, True, .66)
        if clicked:
            if self.tab != key:
                self.tab_at = time.monotonic()  # o conteúdo novo entra deslizando
            self.tab = key
            ui.later(ui.invalidate)

    # --- área principal: título grande, frase, etiquetas dos arquivos e o conteúdo do assunto
    def draw_main(self, ui, kinds):
        g = ui.g
        x0 = RAIL_W + PAD
        w = self.w - RAIL_W - 2 * PAD
        key = self.tab
        label = dict((k, l) for k, l, _ in CATEGORIES).get(key, "Solte aqui.")
        size = 2.6 if w >= 220 else 2.1
        tw = min(w, text_width(label, True, size))
        g.rect(x0 - 2, TOP_H + 14, tw + 4, 10, fill=SKY)
        g.text(x0, TOP_H + 2, fit(label, int(w / size), True), INK, True, size)
        lead = LEADS.get(key, "Arraste arquivos para a janela ou clique em Adicionar.")
        hovered = getattr(self, "chip_hover", None)
        row = self.rows.get(hovered) if hovered else None
        if row:  # passou o mouse numa etiqueta: mostra o que aconteceu com ela
            detail = row.status if row.status and row.tone is False else row.sub
            lead, lead_color = f"{row.name} · {detail}" if detail else row.name, BLUE if row.tone is not False else RED
        else:
            lead_color = DARK
        g.text(x0, TOP_H + 32, fit(lead, int(w / .95)), lead_color, False, .95)
        y = TOP_H + 48
        if self.rows:
            y = self.draw_files(ui, x0, y, w) + 8
        age = time.monotonic() - getattr(self, "tab_at", 0)
        if age < .18:  # entrada suave: sobe 10 px em 180 ms
            slide = round(10 * (1 - age / .18) ** 2)
            self.root.after(16, self.host.invalidate)
        else:
            slide = 0
        area = (x0, y + slide, w, self.h - BAR_H - 10 - y - slide)
        if self.drop_hot:
            self.drop_zone(ui, area, True)
            return
        if key is None or (key in NEEDS_FILES and not kinds):
            self.drop_zone(ui, area, False)
            return
        if area[3] < 30:
            return
        {"convert": self.tab_convert, "compress": self.tab_compress, "edit": self.tab_edit,
         "download": self.tab_download}.get(key, lambda *a: self.tab_group(key, *a))(ui, area, kinds)

    def drop_zone(self, ui, area, hot):
        """Área grande para soltar arquivos (ou clicar e escolher)."""
        g = ui.g
        x, y, w, h = area
        hover, held, clicked = ui.clickable("drop", x, y, w, h)
        t = ui.ease(("drop",), 1.0 if hover or hot else 0.0)
        if hot:
            g.rect(x, y, w, h, fill=BLUE)
        elif t > 0:
            g.rect(x, y, w, h, fill=mix(CREAM, (232, 232, 255), t))
        self.dashed(g, x, y, w, h, WHITE if hot else mix(INK, BLUE, t))
        color = WHITE if hot else mix(INK, BLUE, t)
        if mascot.enabled() and h >= 190 and self.tour is None:
            size = min(96, h // 3)
            pose = "comemorando" if hot else "oi" if t > .5 else "normal"
            mascot.draw(g, pose, x + (w - mascot.width(pose, size, g.s)) // 2, y + h // 2 - size - 4, size)
            ty = y + h // 2 + 6
        else:
            g.icon("plus", x + (w - 34) // 2, y + h // 2 - 34, 34, color)
            ty = y + h // 2 + 6
        g.center(x, ty, w, "Pode soltar." if hot else "Solte os arquivos aqui", color, True, 1.4)
        g.center(x, ty + 18, w, "" if hot else "ou clique para escolher", WHITE if hot else DARK)
        if clicked:
            ui.later(self.pick_files)
        if hot:
            self.root.after(120, self.host.invalidate)

    @staticmethod
    def dashed(g, x, y, w, h, color, dash=4):
        for dx in range(0, w, dash * 2):
            g.rect(x + dx, y, min(dash, w - dx), 2, fill=color)
            g.rect(x + dx, y + h - 2, min(dash, w - dx), 2, fill=color)
        for dy in range(0, h, dash * 2):
            g.rect(x, y + dy, 2, min(dash, h - dy), fill=color)
            g.rect(x + w - 2, y + dy, 2, min(dash, h - dy), fill=color)

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
        ry = y
        for kind in shown:
            g.icon(KIND_ICON[kind], x, ry + 1, 14, INK)
            names = OUTS[kind]
            avail = w - 22 - (len(names) - 1) * 4
            room = avail - sum(text_width(f, True) for f in names)
            padding = max(8, min(12, room // len(names)))
            cx = x + 22
            for fmt in names:
                width = text_width(fmt, True) + padding
                if cx + width > x + w:  # não cabe: continua na linha de baixo
                    cx, ry = x + 22, ry + 22
                ui.button(("fmt", kind, fmt), cx, ry, width, 16, fmt, on=lambda k=kind, f=fmt: self.convert_all(k, f), bold=True)
                cx += width + 4
            ry += 26
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
        each = (w - 16) // 3
        for i, (label, mode) in enumerate(COMPRESS_ITEMS[:3]):
            bx = x + i * (each + 8)
            over, held, clicked = ui.clickable(("comp", mode), bx, y, each, 48)
            ui.face(bx, y, each, 48, over, held, key=("comp", mode))
            color = ui.ink(over, held)
            shift = ui.shift
            g.center(bx + shift, y + 9 + shift, each, label, color, True, 1.5)
            g.center(bx + shift, y + 31 + shift, each, notes[mode], color if over or held else DARK)
            if clicked:
                ui.later(self.compress_all, mode)
        ry = y + 60
        g.text(x, ry + 5, "Até", INK, True)
        focused = ui.entry("target", x + 28, ry, 46, 20, self.target, numeric=True)
        if focused and any(k[0] == "Return" for k in ui.keys):
            ui.later(self.compress_target)
        g.text(x + 79, ry + 5, "MB", INK, True)
        ui.button("target-go", x + 104, ry, 92, 20, "Comprimir", on=self.compress_target, tone=BLUE, bold=True)
        presets = COMPRESS_ITEMS[3:]
        py = ry + 32
        g.text(x, py + 5, "Para mandar em app:", DARK)
        left = x + text_width("Para mandar em app:") + 10
        width = (w - (left - x) - (len(presets) - 1) * 6) // len(presets)
        for label, value in presets:
            ui.button(("preset", value), left, py, width, 20, label, on=lambda v=value: self.compress_all(v), bold=True)
            left += width + 6

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
            found = {"qr", "magic"}
            if MAC:
                from ..modules import mac_utils
                from ..modules import summary
                found |= {"cleanup", "awake", "speed_test", "unblock", "uninstall", "cliphist", "scrollshot",
                          "lens", "dupes", "picker"}
                if summary.available():
                    found.add("summary")
                if mac_utils.wifi_device():
                    found.add("wifi")
                if mac_utils.has_battery():
                    found.add("battery")
            else:
                found |= {"cleanup", "awake", "speed_test", "unblock", "uninstall", "cliphist", "lens", "dupes", "picker"}
                try:
                    from ..modules import win_utils
                    if win_utils.wifi_device():
                        found.add("wifi")
                    if win_utils.has_battery():
                        found.add("battery")
                except Exception as error:
                    log_error("utilidades do Windows", error)
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
        """Ações em cartões: ícone, nome e uma frase do que faz. Rola com a rodinha se não couber."""
        g = ui.g
        x, y, w, h = area
        gap = 7
        columns = columns or (3 if w >= 430 else 2)
        rows = -(-len(tools) // columns)
        card_h = max(36, min(52, (h - gap * (rows - 1)) // rows))
        visible = max(1, (h + gap) // (card_h + gap))
        scroll_key = ("cards", self.tab)
        offset = getattr(self, "card_scroll", {}).get(scroll_key, 0)
        if rows > visible:
            if ui.wheel and ui.over(x, y, w, h):
                offset += ui.wheel
            offset = ui.scrollbar(("cards", self.tab), x + w - 11, y, visible * (card_h + gap) - gap, rows, visible, offset)
            w -= 16
        offset = max(0, min(max(0, rows - visible), offset))
        self.card_scroll = {**getattr(self, "card_scroll", {}), scroll_key: offset}
        each = (w - gap * (columns - 1)) // columns
        for i, (op, label, image, accepted) in enumerate(tools):
            r = i // columns - offset
            if not 0 <= r < visible:
                continue
            bx, by = x + (i % columns) * (each + gap), y + r * (card_h + gap)
            active = accepted is None or bool(kinds & accepted)
            selected = self.selected_tool(op)
            self.spots[("tool", op)] = (bx, by, each, card_h)
            over, held, clicked = ui.clickable(("tool", op), bx, by, each, card_h, active)
            ui.face(bx, by, each, card_h, over, held, selected, enabled=active, key=("tool", op))
            color = ui.ink(over, held, selected, enabled=active)
            shift = ui.shift
            cx, cy = bx + shift, by + shift
            icon = 20 if card_h >= 44 else 16
            g.icon(image, cx + 9, cy + (card_h - icon) // 2, icon, color)
            tx = cx + icon + 17
            room = each - icon - 24
            desc = TIPS.get(op) or DESC.get(op, "")
            dim = GRAY if not active else WHITE if (held or selected) else mix(DARK, (225, 225, 255), ui.mix)
            if desc and card_h >= 34:
                g.text(tx, cy + card_h // 2 - 11, fit(label, int(room / 1.05), True), color, True, 1.05)
                g.text(tx, cy + card_h // 2 + 2, fit(desc, int(room / .82)), dim, False, .82)
            else:
                g.text(tx, cy + (card_h - 10) // 2, fit(label, int(room / 1.05), True), color, True, 1.05)
            if clicked:
                ui.later(self.tool, op)
            if ui.context and ui.over(bx, by, each, card_h):
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

    # --- arquivos: etiquetas com o tipo, o nome e um x para tirar da lista
    def chip_size(self, row):
        ext = (os.path.splitext(row.name)[1][1:] or row.kind).upper()[:4]
        name = os.path.splitext(row.name)[0]
        return ext, name, text_width(ext, True, .8) + 6

    def draw_files(self, ui, x0, y, w):
        """Desenha as etiquetas em linhas (até 2 ou 3; a rodinha rola). Devolve onde terminam."""
        g = ui.g
        rows = list(self.rows.values())
        lines, line, used = [], [], 0
        for row in rows:
            ext, name, tag_w = self.chip_size(row)
            label = name + (" ✓" if row.tone is True else "")
            chip_w = min(w, tag_w + 10 + min(text_width(label, True, .9), 150) + 22)
            if line and used + chip_w > w:
                lines.append(line)
                line, used = [], 0
            line.append((row, chip_w))
            used += chip_w + 6
        if line:
            lines.append(line)
        most = 3 if self.h >= 520 else 2
        area_h = min(len(lines), most) * (CHIP_H + 5)
        if ui.wheel and ui.over(x0, y, w, area_h):
            self.scroll += ui.wheel
        self.scroll = max(0, min(max(0, len(lines) - most), self.scroll))
        self.chip_hover = None
        phase = int(time.monotonic() * 10)
        for n, line in enumerate(lines[self.scroll:self.scroll + most]):
            cy = y + n * (CHIP_H + 5)
            cx = x0
            last = n == most - 1 and self.scroll + most < len(lines)
            for row, chip_w in line:
                self.chip(ui, row, cx, cy, chip_w, phase)
                cx += chip_w + 6
            if last:  # tem mais linhas embaixo: um aviso no fim
                more = sum(len(l) for l in lines[self.scroll + most:])
                g.right(x0 + w, cy + 4, f"+{more} ↓", BLUE, True)
        return y + area_h

    def chip(self, ui, row, x, y, w, phase):
        g = ui.g
        ext, name, tag_w = self.chip_size(row)
        over = ui.over(x, y, w, CHIP_H)
        t = ui.ease(("chip", row.path), 1.0 if over else 0.0)
        if over:
            self.chip_hover = row.path
        g.rect(x + 1, y + 1, w, CHIP_H, fill=INK)
        g.rect(x, y, w, CHIP_H, fill=mix(WHITE, (232, 232, 255), t), line=INK)
        if row.busy:  # progresso: um filete azul no pé da etiqueta
            inner = w - 2
            if row.progress is None:  # sem porcentagem: um pedaço indo e voltando
                part = max(12, inner // 4)
                span = max(1, inner - part)
                pos = abs((phase * 3) % (span * 2) - span)
                g.rect(x + 1 + pos, y + CHIP_H - 3, part, 2, fill=BLUE)
                self.root.after(60, self.host.invalidate)
            else:
                g.rect(x + 1, y + CHIP_H - 3, max(1, int(inner * row.progress)), 2, fill=BLUE)
        tag = BLUE if row.tone is True else RED if row.tone is False else INK
        g.rect(x + 3, y + 3, tag_w, CHIP_H - 7, fill=tag)
        g.text(x + 6, y + 4, ext, WHITE, True, .8)
        nx = x + tag_w + 8
        label = name + (" ✓" if row.tone is True else "")
        g.text(nx, y + 4, fit(label, int((w - tag_w - 30) / .9), True), mix(INK, BLUE, t), True, .9)
        mark = lambda mx, my, color: ui.mark_x(mx + 1, my + 1, 8, color)
        if ui.mini(("row-close", row.path), x + w - 15, y + 3, 11, mark):
            ui.later(self.close_row, row.path)
        self.spots[("row", row.path)] = (x, y, w - 16, CHIP_H)
        if over and ui.mx < x + w - 16:
            if ui.double:  # duplo clique: mostra o pronto (ou o original) no Finder
                ui.later(self.show_row, row.path)
            elif ui.context:
                ui.later(self.open_row_menu, row.path, ui.mx, ui.my)

    def draw_footer(self, ui):
        """Barra de baixo: área tracejada para adicionar e os botões Abrir, Salvar em e Limpar."""
        g = ui.g
        y = self.h - BAR_H
        x0 = RAIL_W
        g.rect(x0, y, self.w - x0, BAR_H, fill=WHITE)
        g.hline(x0, y, self.w - x0, INK)
        g.hline(x0, y + 1, self.w - x0, INK)
        g.hline(x0, self.h - 1, self.w - x0, INK)  # borda de baixo, igual à de cima (o fundo branco cobria)
        g.vline(self.w - 1, y, BAR_H, INK)  # e a da direita, no trecho da barra
        dest ="Salvar em" if not self.out_dir else os.path.basename(self.out_dir)
        buttons = [("open", "folder", "Abrir", self.open_folder), ("dest", "disk", dest, self.choose_dest),
                   ("clear", "trash", "Clear" if english() else "Limpar", self.clear)]
        bx = self.w - PAD
        by, bh = y + 9, 18
        for key, image, label, action in reversed(buttons):
            text = fit(label, 70, True)
            bw = text_width(text, True, .9) + 30 if key == "dest" else 22 if key == "clear" else text_width(text, True, .9) + 30
            if self.w - RAIL_W < 330 and key == "open":
                bw = 22
            bx -= bw
            over, held, clicked = ui.clickable(("desk", key), bx, by, bw, bh)
            self.spots[("desk", key)] = (bx, by, bw, bh)
            if over:
                self.want_tip(key, (bx, by, bw, bh), mascot.TIPS[key])
            ui.face(bx, by, bw, bh, over, held, tone=key == "dest", key=("desk", key))
            color = ui.ink(over, held, tone=key == "dest")
            shift = ui.shift
            if bw == 22:
                g.icon(image, bx + 5 + shift, by + 4 + shift, 11, color)
            else:
                g.icon(image, bx + 8 + shift, by + 4 + shift, 11, color)
                g.text(bx + 23 + shift, by + 5 + shift, text, color, True, .9)
            if clicked:
                ui.later(action)
            bx -= 8
        ax, aw = x0 + PAD, bx - x0 - PAD - 2
        over, held, clicked = ui.clickable(("desk", "add"), ax, by - 1, aw, bh + 2)
        self.spots[("desk", "add")] = (ax, by - 1, aw, bh + 2)
        if over:
            self.want_tip("add", (ax, by - 1, aw, bh + 2), mascot.TIPS["add"])
        t = ui.ease(("add",), 1.0 if over or self.drop_hot else 0.0)
        if t > 0:
            g.rect(ax, by - 1, aw, bh + 2, fill=mix(WHITE, BLUE, t))
        color = mix(INK, WHITE, t)
        self.dashed(g, ax, by - 1, aw, bh + 2, INK if t < .5 else BLUE)
        text = fit("Adicionar arquivos" if aw > 150 else "Adicionar", int((aw - 30) / .9), True)
        g.icon("plus", ax + 8, by + 4, 11, color)
        g.text(ax + 23, by + 5, text.upper(), color, True, .9)
        if clicked:
            ui.later(self.pick_files)

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
        if mascot.enabled():
            mascot.draw(g, "oi", x + w - 96, y + 26, 70)

    # --- Disquetinho: tour da primeira vez e balões de dica
    def toggle_mascot(self):
        mascot.toggle()
        self.host.invalidate()

    def maybe_tour(self):
        if mascot.tour_pending() and self.tour is None:
            self.start_tour()

    def start_tour(self):
        self.menu = self.context_menu = None
        self.about = False
        self.tour = 0
        self.host.invalidate()

    def tour_step(self, delta):
        step = self.tour + delta
        if step >= len(mascot.TOUR) or step < 0:
            self.end_tour()
        else:
            self.tour = step
            self.host.invalidate()

    def end_tour(self):
        self.tour = None
        mascot.tour_done()
        self.host.invalidate()

    def tour_target(self, name):
        if name == "rail":
            return (0, 56, RAIL_W, self.h - 56)
        if name == "main":
            return (RAIL_W + 6, TOP_H + 4, self.w - RAIL_W - 12, self.h - TOP_H - BAR_H - 8)
        if name == "logo":
            x, y, w, h = self.spots.get(("logo",), (13, 9, 40, 40))
            return (x - 4, y - 4, w + 8, h + 8)
        spot = self.spots.get(("desk", name))
        if spot:
            x, y, w, h = spot
            return (x - 4, y - 4, w + 8, h + 8)
        return None

    def draw_tour(self, ui):
        from PIL import Image, ImageDraw
        g = ui.g
        pose, target, title, text = mascot.TOUR[self.tour]
        box = self.tour_target(target) if target else None
        # escurece tudo, menos o que o passo mostra
        s = g.s
        shade = Image.new("L", (self.w * s, self.h * s), 120)
        if box:
            bx, by, bw, bh = box
            ImageDraw.Draw(shade).rectangle((bx * s, by * s, (bx + bw) * s - 1, (by + bh) * s - 1), fill=0)
        g.im.paste(INK, (0, 0), shade)
        if box:
            bx, by, bw, bh = box
            for i in range(2):
                g.rect(bx - i, by - i, bw + 2 * i, bh + 2 * i, line=BLUE)
        show = mascot.enabled()
        size = 84 if self.h >= 470 else 66
        mw = mascot.width(pose, size, s) if show else 0
        w = max(170, min(240, self.w - RAIL_W - mw - 40))
        bh_ = mascot.balloon_height(w, title, text) + 30
        # onde fica o balão: perto do alvo, sem cobrir
        if target == "rail":
            x, y = RAIL_W + 14, max(60, self.h // 2 - bh_ // 2)
        elif target == "logo":
            x, y = RAIL_W + 14, 40
        elif target in ("add", "dest", "open", "clear"):
            x, y = RAIL_W + 14, self.h - BAR_H - bh_ - 16
            if target == "dest":  # o balão fica à esquerda e o Disquetinho logo acima do botão
                x = max(RAIL_W + 8, self.w - PAD - mw - w - 12)
        else:
            x, y = (self.w - w - mw - 8 + RAIL_W) // 2, (self.h - bh_) // 2
        x = max(4, min(x, self.w - w - mw - 10))
        mx = x + w + 8
        used = mascot.balloon(g, x, y, w, title, text)
        g.rect(x, y + used, w, 30, fill=WHITE)
        g.vline(x, y + used, 30, INK)
        g.vline(x + w - 1, y + used, 30, INK)
        g.hline(x, y + used + 29, w, INK)
        g.rect(x + 3, y + used + 30, w, 3, fill=INK)
        g.rect(x + w, y + used, 3, 30, fill=INK)
        last = self.tour == len(mascot.TOUR) - 1
        by = y + used + 5
        g.text(x + 10, by + 5, f"{self.tour + 1}/{len(mascot.TOUR)}", DARK)
        nxt = "Começar" if last else "Próximo"
        nw = text_width(nxt, True, .9) + 20
        ui.button("tour-next", x + w - nw - 8, by, nw, 18, nxt, on=lambda: self.tour_step(1), tone=BLUE, bold=True)
        if not last:
            sw = text_width("Pular o tour", True, .9) + 16
            ui.button("tour-skip", x + w - nw - sw - 14, by, sw, 18, "Pular o tour", on=self.end_tour)
        if show:
            mascot.draw(g, pose, mx, y + used + 30 - size + 6, size)

    def want_tip(self, key, area, text):
        if text and self.tour is None and self.menu is None and self.context_menu is None and not self.about:
            self.tip = (key, area, text)

    def draw_tip(self, ui):
        tip = self.tip
        if tip is None:
            self.tip_key = None
            return
        key, (x, y, w, h), text = tip
        now = time.monotonic()
        if key != self.tip_key:
            self.tip_key, self.tip_since = key, now
            self.root.after(int(mascot.TIP_DELAY * 1000) + 30, self.host.invalidate)
            return
        if now - self.tip_since < mascot.TIP_DELAY:
            return
        g = ui.g
        face = 30 if mascot.enabled() else 0
        tw = min(200, max(120, text_width(tr(text)) + 20))
        bw = tw + face
        bh = max(mascot.balloon_height(tw, None, text), face + 8)
        tx = x + w + 8 if x < RAIL_W else min(x, self.w - bw - 8)
        ty = y + (h - bh) // 2 if x < RAIL_W else y - bh - 8
        ty = max(4, min(ty, self.h - bh - 6))
        g.rect(tx + 3, ty + 3, bw, bh, fill=INK)
        g.rect(tx, ty, bw, bh, fill=WHITE, line=INK)
        if face:
            mascot.draw(g, "rosto", tx + 5, ty + (bh - 26) // 2, 26)
        ly = ty + (bh - len(mascot.wrap(text, tw - 20)) * 12) // 2 + 1
        for line in mascot.wrap(text, tw - 20):
            g.text(tx + face + 8, ly, line, DARK)
            ly += 12

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
            if MAC:
                from .platform_mac import activate
                activate()
            self.safe_dialog(uninstall_app)
        elif op == "scrollshot":
            from . import scrollshot_ui
            self.safe_dialog(scrollshot_ui.start)
        elif op in ("lens", "dupes", "magic", "picker"):
            from . import new_tools as nt
            if op == "picker":
                try:
                    nt.pick_color(self)
                except Exception as e:
                    log_error("conta-gotas", e)
                    self.say("Conta-gotas não funcionou aqui")
                return
            if MAC:
                from .platform_mac import activate
                activate()
            self.safe_dialog({"lens": nt.SpaceDialog, "dupes": nt.DupesDialog, "magic": nt.MagicDialog}[op])
        elif op == "awake":
            on = self.awake.toggle()
            self.say("O Mac não vai dormir até você desligar" if on else "O Mac pode dormir de novo", BLUE)
        else:
            from . import utility_dialogs as ud
            if MAC:
                from .platform_mac import activate
                activate()
            self.safe_dialog({"speed_test": ud.SpeedDialog, "wifi": ud.WifiDialog, "battery": ud.BatteryDialog,
                              "unblock": ud.unblock_app}[op])

    def list_height(self):
        return 0  # a lista virou etiquetas dentro da área principal

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
        elif op in ("tempo", "silence", "voice"):
            from . import new_tools as nt
            self.safe_dialog({"tempo": nt.TempoDialog, "silence": nt.SilenceDialog, "voice": nt.VoiceDialog}[op], targets)
        elif op in ("sign", "pages", "redact"):
            from . import new_tools as nt
            if len(targets) > 1:
                self.say("Um PDF por vez: abri o primeiro", BLUE)
            self.safe_dialog({"sign": nt.SignDialog, "pages": nt.PagesDialog, "redact": nt.RedactDialog}[op], targets[0])
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
            elif op in ("silence", "voice"):
                from ..modules import audio_tools
                if op == "silence":
                    result = audio_tools.cut_silences(src, kind, params["gap"], params["pause"], folder, job)
                else:
                    result = audio_tools.clean_voice(src, kind, params["hiss"], params["noise"], params["echo"],
                                                     params["level"], folder, job)
            elif op in ("pages", "redact", "sign"):
                from ..modules import pdftools
                if op == "pages":
                    result = pdftools.organize(src, params["pages"], folder, job)
                elif op == "redact":
                    result = pdftools.redact(src, params["boxes"], folder, job)
                else:
                    result = pdftools.sign(src, params["places"], params["image"], folder, job,
                                           params.get("certificate"), params.get("password"))
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

    def restart_magic(self):
        """Liga, desliga ou troca a pasta da Pasta mágica."""
        self.magic.stop()
        self.magic.start()

    def magic_done(self, name, ok, detail):
        def show():
            if ok:
                self.pill.flash("Pasta mágica", f"{name} → {detail}")
            else:
                self.pill.flash("Pasta mágica: não deu", f"{name}: {detail}")
        self.root.after(0, show)

    def shutdown(self):
        self.magic.stop()
        for row in self.rows.values():
            if row.job:
                row.job.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)
