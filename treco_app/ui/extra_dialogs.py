"""Janelinhas do QR Code e da limpeza da pasta Downloads."""
import io
import os
import subprocess

from ..core import prefs
from ..core.files import human_size
from ..core.log import log_error
from ..core.paths import MAC
from ..modules import cleanup, paper
from .pixel import AMBER, BLUE, DARK, GRAY, INK, WHITE, fit, text_width
from .tool_dialogs import ToolDialog
from .toolkit import TextField
from .utility_dialogs import BackgroundDialog

QR_BOX = 132


def show_file(path):
    if MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def save_folder(app):
    """Onde salvar: a pasta escolhida em "Salvar em", ou a Mesa."""
    folder = app.out_dir or os.path.expanduser("~/Desktop")
    return folder if os.path.isdir(folder) else os.path.expanduser("~")


class QRDialog(ToolDialog):
    """Escreve ou cola um link e vê o QR Code na hora."""

    def __init__(self, app, text=None):
        super().__init__(app, "QR Code", 360, 214)
        if text is None:  # começa com o que estiver copiado, se for curto
            try:
                copied = self.clipboard_get().strip()
            except Exception:
                copied = ""
            text = copied if 0 < len(copied) <= 300 and "\n" not in copied else ""
        self.field = TextField(" ".join(text.split()), 1200)
        self.host.focus = "qr-text"
        self.preview, self.preview_text = None, None
        self.message = None
        self.host.frame()

    def image(self):
        text = self.field.text.strip()
        if text != self.preview_text:
            self.preview_text, self.message = text, None
            try:
                self.preview = paper.qr_image(text, QR_BOX).convert("RGB") if text else None
            except Exception:
                self.preview = None  # texto grande demais para um QR
        return self.preview

    def body(self, ui):
        g = ui.g
        x, y = 14, 24
        g.text(x, y, "Link ou texto", INK, True)
        focused = ui.entry("qr-text", x, y + 13, self.dw - 28, 20, self.field)
        if not self.field.text and not focused:
            g.text(x + 6, y + 19, "Cole ou escreva aqui", DARK)
        if focused and any(k[0] == "Return" for k in ui.keys):
            ui.later(self.save)
        top = y + 40
        image = self.image()
        g.rect(x, top, QR_BOX, QR_BOX, fill=WHITE, line=GRAY)
        if image:
            g.blit(image, x + (QR_BOX - image.width) // 2, top + (QR_BOX - image.height) // 2)
        else:
            g.center(x, top + QR_BOX // 2 - 5, QR_BOX, "texto grande demais" if self.field.text.strip() else "o QR aparece aqui", DARK)
        rx, rw = x + QR_BOX + 12, self.dw - x - QR_BOX - 26
        size = prefs.get("qr_size")
        g.text(rx, top + 2, "A câmera do celular lê", DARK)
        g.text(rx, top + 14, "e abre o link.", DARK)
        g.text(rx, top + 34, f"Imagem PNG {size.lower()}", DARK)
        g.text(rx, top + 46, f"({paper.QR_SIZES[size]} px)", DARK)
        if self.message:
            g.text(rx, top + 66, fit(self.message[0], rw, True), self.message[1], True)
        ui.button("qr-save", rx, top + QR_BOX - 17, rw, 17, "Salvar imagem", on=self.save, enabled=bool(image),
                  tone=AMBER, bold=True)
        if MAC:
            ui.button("qr-copy", rx, top + QR_BOX - 39, rw, 17, "Copiar imagem", on=self.copy, enabled=bool(image))

    def save(self):
        if not self.image():
            return
        try:
            path = paper.save_qr(self.field.text, save_folder(self.app), prefs.get("qr_size"))
        except Exception as error:
            log_error("QR Code", error)
            self.message = (str(error)[:40] or "Não deu certo", AMBER)
            return
        self.app.add_files([path])
        show_file(path)
        where = "na Mesa" if os.path.dirname(path) == os.path.expanduser("~/Desktop") else "na pasta"
        self.message = (f"Salvo {where}", BLUE)

    def copy(self):
        from .platform_mac import set_clipboard_image
        buffer = io.BytesIO()
        paper.qr_image(self.field.text.strip(), paper.QR_SIZES[prefs.get("qr_size")]).save(buffer, "PNG")
        set_clipboard_image(buffer.getvalue())
        self.message = ("Copiado: ⌘V para colar", BLUE)


ROW = 19
SORTS = ("Maiores", "Mais antigos")


class CleanupDialog(BackgroundDialog):
    """Lista o que ocupa espaço em Downloads. Só vai para o Lixo o que a pessoa marcar."""

    def __init__(self, app):
        super().__init__(app, "Limpar Downloads", 390, 340)
        self.how = SORTS[0]
        self.marked = set()
        self.scroll = 0
        self.message = None
        self.host.frame()
        self.work(self.load)

    @staticmethod
    def load(message=None):
        return {"items": cleanup.scan(), "message": message}

    def trash(self, paths):
        moved, failed = cleanup.to_trash(paths)
        text = f"{moved} {'item foi' if moved == 1 else 'itens foram'} para o Lixo"
        if failed:
            text += f" · {len(failed)} não deu"
        return self.load(text)

    def finish(self, value, error):
        super().finish(value, error)
        if value:
            self.message = value["message"]
            alive = {i["path"] for i in value["items"]}
            self.marked &= alive

    def body(self, ui):
        g = ui.g
        x, y, w = 14, 24, self.dw - 28
        if self.working:
            self.waiting(ui, x, y, w, "Olhando a pasta Downloads…")
            return
        if self.error:
            self.failed(ui, x, y, w)
            return
        items = cleanup.sort(self.result["items"], self.how)
        total = sum(i["size"] for i in items)
        g.text(x, y + 3, f"{len(items)} itens · {human_size(total)}", INK, True)
        self.how = ui.segmented("sort", x + w - 170, y, 170, list(SORTS), self.how)
        top = y + 20
        height = (self.dh - top - 70) // ROW * ROW + 2
        g.rect(x, top, w, height, fill=WHITE, line=INK)
        visible = height // ROW
        if ui.wheel and ui.over(x, top, w, height):
            self.scroll += ui.wheel * 2
        self.scroll = ui.scrollbar("list", x + w - 12, top, height, max(1, len(items)), visible, self.scroll)
        if not items:
            g.center(x, top + height // 2 - 5, w, "A pasta Downloads está vazia.", DARK, True)
        for n, item in enumerate(items[self.scroll:self.scroll + visible]):
            ry = top + 1 + n * ROW
            lw = w - 14
            on = item["path"] in self.marked
            over, held, clicked = ui.clickable(("item", item["path"]), x + 1, ry, lw, ROW)
            tone = BLUE if over else INK
            g.rect(x + 6, ry + 4, 10, 10, fill=tone if on else WHITE, line=tone)
            if on:
                g.icon("x", x + 7, ry + 5, 8, WHITE)
            g.icon("folder" if item["folder"] else "doc", x + 21, ry + 3, 12, tone)
            right = f"{human_size(item['size'])} · {cleanup.age_words(item['days'])}"
            g.right(x + lw - 4, ry + 5, right, DARK if not over else BLUE)
            g.text(x + 37, ry + 5, fit(item["name"], lw - 49 - text_width(right), on or over), tone, on or over)
            g.hline(x + 1, ry + ROW - 1, lw, GRAY)
            if clicked:
                (self.marked.discard if on else self.marked.add)(item["path"])
        size = sum(i["size"] for i in items if i["path"] in self.marked)
        by = top + height + 6
        if self.message:
            g.text(x, by + 2, fit(self.message, w, True), BLUE, True)
        else:
            g.text(x, by + 2, "Clique para marcar. Tudo vai para o Lixo e dá para recuperar.", DARK)
        by += 18
        ui.button("open", x, by, 112, 20, "Abrir Downloads", on=lambda: subprocess.Popen(["open", cleanup.downloads_folder()]))
        label = f"Mandar {len(self.marked)} para o Lixo ({human_size(size)})" if self.marked else "Marque o que não quer"
        ui.button("trash", x + 118, by, w - 118, 20, label, on=self.go, enabled=bool(self.marked), tone=AMBER, bold=True)
        by += 24
        if items and ui.button("old", x, by, w, 16, "Marcar tudo com mais de 6 meses"):
            self.marked |= {i["path"] for i in items if i["days"] >= 180}

    def go(self):
        paths = sorted(self.marked)
        self.marked = set()
        self.work(self.trash, paths)


# ---------------------------------------------------------------- histórico de cópias
class ClipHistoryDialog(ToolDialog):
    """Tudo o que foi copiado (texto). Clique num item para copiar de novo e colar com ⌘V."""

    def __init__(self, app):
        super().__init__(app, "Histórico de cópias", 390, 360)
        self.search = TextField("", 80)
        self.host.focus = "search"
        self.scroll = 0
        self.message = None
        self.host.frame()
        self.refresh()

    def refresh(self):
        if self.alive:  # o histórico muda sozinho enquanto a janela está aberta
            self.host.invalidate()
            self.after(1500, self.refresh)

    def body(self, ui):
        import time
        from ..modules.cliphistory import when
        g = ui.g
        x, y, w = 14, 24, self.dw - 28
        history = self.app.clips.history if self.app.clips else None
        on = prefs.get("clip_history")
        focused = ui.entry("search", x, y, w, 20, self.search)
        if not self.search.text and not focused:
            g.text(x + 6, y + 6, "Procurar no que você copiou", DARK)
        items = history.search(self.search.text) if history else []
        top, row = y + 26, 26
        height = (self.dh - top - 52) // row * row + 2
        g.rect(x, top, w, height, fill=WHITE, line=INK)
        visible = height // row
        if ui.wheel and ui.over(x, top, w, height):
            self.scroll += ui.wheel * 2
        self.scroll = ui.scrollbar("list", x + w - 12, top, height, max(1, len(items)), visible, self.scroll)
        if not items:
            empty = "Nada encontrado." if self.search.text else ("Copie algo (⌘C) e aparece aqui." if on else "O histórico está desligado.")
            g.center(x, top + height // 2 - 5, w, empty, DARK, True)
        now = time.time()
        for n, item in enumerate(items[self.scroll:self.scroll + visible]):
            ry = top + 1 + n * row
            lw = w - 14
            over, held, clicked = ui.clickable(("clip", n + self.scroll), x + 1, ry, lw - 18, row)
            if over:
                g.rect(x + 1, ry, lw, row - 1, fill=INK)
            tone = WHITE if over else INK
            text = " ".join(item["text"].split())
            age = when(now - item.get("at", now))
            g.text(x + 7, ry + 3, fit(text, lw - 70, over), tone, over)
            g.right(x + lw - 22, ry + 3, age, WHITE if over else DARK)
            lines = item["text"].count("\n") + 1
            extra = f"{len(item['text'])} letras" + (f" · {lines} linhas" if lines > 1 else "")
            g.text(x + 7, ry + 14, extra, WHITE if over else GRAY, False, .85)
            mark = lambda mx, my, color: ui.mark_x(mx + 1, my + 1, 8, color)
            if ui.mini(("del", n + self.scroll), x + lw - 16, ry + 7, 11, mark):
                history.remove(item["text"])
            elif clicked:
                ui.later(self.pick, item["text"])
            g.hline(x + 1, ry + row - 1, lw, GRAY)
        if focused and items and any(k[0] == "Return" for k in ui.keys):
            ui.later(self.pick, items[0]["text"])
        by = top + height + 6
        if self.message:
            g.text(x, by + 2, self.message, BLUE, True)
        else:
            g.text(x, by + 2, "Clique para copiar de novo. Senhas de gerenciadores ficam de fora.", DARK)
        by += 16
        new = ui.checkbox("on", x, by + 4, "Guardar o que eu copiar", on)
        if new != on:
            prefs.put("clip_history", new)
        ui.button("clear", x + w - 100, by, 100, 18, "Apagar tudo", on=self.clear, enabled=bool(history and history.items))

    def pick(self, text):
        from .platform_mac import set_clipboard_text
        set_clipboard_text(text)
        self.app.say("Copiado: ⌘V para colar", BLUE)
        self.close()

    def clear(self):
        if self.app.clips:
            self.app.clips.history.clear()
        self.message = "Histórico apagado"


# ---------------------------------------------------------------- desinstalar
class UninstallDialog(BackgroundDialog):
    """Mostra o app e tudo o que ele deixou na Biblioteca. Vai tudo para o Lixo."""

    def __init__(self, app, path):
        from ..modules import uninstall
        super().__init__(app, "Desinstalar", 400, 330)
        self.path = path
        self.info = uninstall.app_info(path)
        self.marked = set()
        self.scroll = 0
        self.done = None
        self.host.frame()
        self.work(self.find)

    def find(self):
        from ..modules import uninstall
        found = [(self.path, cleanup.folder_size(self.path))] + uninstall.leftovers(self.path)
        return found

    def finish(self, value, error):
        super().finish(value, error)
        if value and self.done is None:
            self.marked = {p for p, _ in value}

    def body(self, ui):
        from ..modules import uninstall
        g = ui.g
        x, y, w = 14, 24, self.dw - 28
        name = self.info["name"]
        if self.working:
            self.waiting(ui, x, y, w, fit(("Desinstalando " if self.done is not None else "Procurando o que é de ") + name + "…", w, True))
            return
        if self.error:
            self.failed(ui, x, y, w)
            return
        if self.done is not None:
            ok, failed = self.result
            g.text(x, y, fit(f"{name} foi para o Lixo." if ok else f"Não consegui tirar {name}.", w, True), BLUE if ok else AMBER, True, 1.3)
            g.text(x, y + 22, f"{len(self.marked) - len(failed)} itens no Lixo. Dá para recuperar até esvaziar o Lixo.", INK)
            if failed:
                g.text(x, y + 36, fit("Ficaram: " + ", ".join(failed), w), DARK)
            ui.button("ok", self.dw - 84, self.dh - 31, 70, 17, "OK", on=self.close, tone=AMBER, bold=True)
            return
        items = self.result
        g.text(x, y + 1, fit(f"{name} e o que ele guardou no Mac:", w, True), INK, True)
        top = y + 16
        height = (self.dh - top - 64) // 19 * 19 + 2
        g.rect(x, top, w, height, fill=WHITE, line=INK)
        visible = height // 19
        if ui.wheel and ui.over(x, top, w, height):
            self.scroll += ui.wheel * 2
        self.scroll = ui.scrollbar("list", x + w - 12, top, height, max(1, len(items)), visible, self.scroll)
        home = os.path.expanduser("~/Library/")
        for n, (path, size) in enumerate(items[self.scroll:self.scroll + visible]):
            ry = top + 1 + n * 19
            lw = w - 14
            on = path in self.marked
            over, held, clicked = ui.clickable(("item", path), x + 1, ry, lw, 19)
            tone = BLUE if over else INK
            g.rect(x + 6, ry + 4, 10, 10, fill=tone if on else WHITE, line=tone)
            if on:
                g.icon("x", x + 7, ry + 5, 8, WHITE)
            label = os.path.basename(path) if path == self.path else path.replace(home, "")
            size_text = human_size(size)
            g.right(x + lw - 4, ry + 5, size_text, DARK)
            g.text(x + 22, ry + 5, fit(label, lw - 34 - text_width(size_text), on), tone, on or path == self.path)
            g.hline(x + 1, ry + 18, lw, GRAY)
            if clicked:
                (self.marked.discard if on else self.marked.add)(path)
        total = sum(s for p, s in items if p in self.marked)
        by = top + height + 6
        busy = uninstall.running(self.info["id"]) if self.info["id"] else []
        if busy:
            g.text(x, by + 2, fit(f"{name} está aberto: feche antes.", w - 100, True), AMBER, True)
            ui.button("quit", x + w - 96, by - 2, 96, 16, f"Fechar {name}"[:18], on=lambda: uninstall.quit_app(self.info["id"]))
        else:
            g.text(x, by + 2, "Desmarque o que quiser manter.", DARK)
        by += 20
        ui.button("cancel", x, by, 70, 20, "Cancelar", on=self.close)
        label = f"Desinstalar ({human_size(total)})" if self.path in self.marked else f"Apagar só os dados ({human_size(total)})"
        ui.button("go", x + 76, by, w - 76, 20, label, on=self.go, enabled=bool(self.marked) and not busy, tone=AMBER, bold=True)

    def go(self):
        paths = list(self.marked)
        self.done = paths
        self.work(self.remove, paths)

    def remove(self, paths):
        from ..modules import uninstall
        others = [p for p in paths if p != self.path]
        moved, failed = cleanup.to_trash(others) if others else (0, [])
        ok = True
        if self.path in paths:
            ok = uninstall.trash_app(self.path)
            if not ok:
                failed.append(os.path.basename(self.path))
        return ok, failed


def uninstall_app(app):
    from ..modules import uninstall
    from .utility_dialogs import choose_app
    try:
        path = choose_app(title="Escolha o app para desinstalar", prompt="Desinstalar")
    except Exception as error:
        log_error("escolher app", error)
        app.say("Não consegui abrir a escolha de app")
        return
    if not path:
        return
    why = uninstall.problem(path)
    if why:
        app.say(why)
        return
    UninstallDialog(app, path)


# ---------------------------------------------------------------- resumo de página
class SummaryDialog(BackgroundDialog):
    """Cola um link, a IA do Mac resume e salva um arquivo de texto."""

    def __init__(self, app, url=""):
        from ..modules import summary
        super().__init__(app, "Resumir página", 400, 250)
        if not url:
            try:
                copied = self.clipboard_get().strip()
            except Exception:
                copied = ""
            url = copied if summary.clean_url(copied) and " " not in copied and len(copied) < 500 else ""
        self.field = TextField(url, 2000)
        self.blocked = summary.status()  # IA desligada, baixando ou Mac sem suporte
        self.size = prefs.get("summary_size")
        self.working = False
        self.stage = ""
        self.jobs = []
        self.host.focus = "url"
        self.host.frame()

    def body(self, ui):
        from ..modules import summary
        g = ui.g
        x, y, w = 14, 24, self.dw - 28
        if self.working:
            self.waiting(ui, x, y, w, fit(self.stage or "Lendo a página…", w, True))
            g.text(x, y + 38, "A IA do Mac resume sem mandar o texto para ninguém.", DARK)
            g.text(x, y + 52, "Página grande pode levar 1 ou 2 minutos.", DARK)
            ui.button("cancel", x, self.dh - 31, 70, 17, "Cancelar", on=self.cancel)
            return
        g.text(x, y, "Link da página (blog, notícia, artigo)", INK, True)
        focused = ui.entry("url", x, y + 13, w - 64, 20, self.field)
        if not self.field.text and not focused:
            g.text(x + 6, y + 19, "https://…", DARK)
        ui.button("paste", x + w - 60, y + 13, 60, 20, "Colar", on=self.paste)
        g.text(x, y + 44, "Tamanho", INK, True)
        self.size = ui.segmented("size", x + 64, y + 40, w - 64, list(summary.SIZES), self.size)
        ready = bool(summary.clean_url(self.field.text)) and not self.blocked
        if self.blocked:
            g.text(x, y + 64, fit(self.blocked, w, True), AMBER, True)
            g.text(x, y + 78, "Ajustes > Apple Intelligence e Siri.", DARK)
        if focused and ready and any(k[0] == "Return" for k in ui.keys):
            ui.later(self.go)
        if self.blocked:
            pass
        elif self.error:
            g.text(x, y + 64, fit(str(self.error), w, True), AMBER, True)
        elif self.result:
            path, title, text = self.result
            g.text(x, y + 64, fit("Pronto: " + os.path.basename(path), w, True), BLUE, True)
            lines = []
            for paragraph in text.splitlines():
                while paragraph and len(lines) < 7:
                    cut = len(paragraph)
                    while text_width(paragraph[:cut]) > w - 4 and cut > 10:
                        cut = paragraph.rfind(" ", 0, cut - 1) if " " in paragraph[:cut - 1] else cut - 1
                    lines.append(paragraph[:cut])
                    paragraph = paragraph[cut:].strip()
            for n, line in enumerate(lines):
                g.text(x, y + 80 + n * 11, line, INK)
            ui.button("copy", x, self.dh - 31, 110, 17, "Copiar resumo", on=self.copy)
            ui.button("show", x + 116, self.dh - 31, 100, 17, "Mostrar arquivo", on=lambda: show_file(path))
        else:
            g.text(x, y + 66, "O resumo vira um arquivo de texto e aparece aqui.", DARK)
        ui.button("go", self.dw - 100, self.dh - 31, 86, 17, "Resumir", on=self.go, enabled=ready, tone=AMBER, bold=True)

    def paste(self):
        try:
            self.field.set(" ".join(self.clipboard_get().split())[:2000])
        except Exception:
            pass

    def go(self):
        from ..core.jobs import Job
        from ..modules import summary
        url = summary.clean_url(self.field.text)
        if not url:
            return
        prefs.put("summary_size", self.size)
        job = Job()
        self.jobs = [job]
        self.stage = ""

        def stage(text):
            self.stage = text
        self.work(summary.summarize_url, url, self.size, prefs.get("summary_format"), save_folder(self.app), job, stage)

    def finish(self, value, error):
        from ..core.jobs import Cancelled
        if isinstance(error, Cancelled):
            error = None
        super().finish(value, error)
        if value:
            self.app.add_files([value[0]])

    def cancel(self):
        for job in self.jobs:
            job.cancel()

    def close(self):
        self.cancel()
        super().close()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.result[2])
        self.app.say("Resumo copiado", BLUE)
