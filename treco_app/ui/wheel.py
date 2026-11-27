"""Roda do Shift em pixels: a primeira volta mostra as ações; a segunda, as opções."""
import math
import os
import time
import tkinter as tk

from PIL import Image, ImageDraw

from ..core.formats import COMPRESS_ITEMS, COMPRESSIBLE, KIND_NAME, OUTS, edit_items, kind_of, selection_kind, selection_problem
from ..core.log import log_error
from ..core.paths import MAC
from .icons import KIND_ICON
from .pixel import BLUE, GRAY, INK, LINE, RED, WHITE, Gfx, fit, text_width

if MAC:
    from .platform_mac import (DropCatcher, MouseWatch, Overlay, cursor_pos, explorer_selection, foreground_is_explorer, key_down,
                               monitor_work_area, push_layered)
else:
    from tkinterdnd2 import DND_FILES
    from .winapi import (MouseWatch, cursor_pos, explorer_selection, foreground_is_explorer, key_down, monitor_work_area, push_layered,
                         set_layered_style, user32)

VK_LBUTTON, VK_SHIFT, VK_ESCAPE = 0x01, 0x10, 0x1B
R_CENTER, R_INNER, R_OUTER_START, R_OUTER = 26, 70, 72, 112
PAD = 5
CAT_ICON = {"convert": "convert", "compress": "compress", "edit": "edit", "caption": "caption", "rename": "rename"}
DIRECT = {"caption": "Legendar", "rename": "Renomear"}  # ações sem segunda roda: soltar em cima já executa


def center_width(top, bottom):
    """Largura livre dentro do círculo central, na altura do texto."""
    radius = R_CENTER - 3
    distance = max(abs(top), abs(bottom))
    return max(0, int(2 * math.sqrt(max(0, radius * radius - distance * distance))) - 4)


def categories_for(kind, many=False):
    """As ações dependem do tipo de arquivo."""
    if kind is None:
        return []
    if kind == "mixed":  # tipos diferentes juntos: só dá para renomear
        return [("rename", "Renomear", [])]
    items = [("convert", "Converter", [(f, f) for f in OUTS[kind]])]
    if kind in COMPRESSIBLE:
        items.append(("compress", "Comprimir", COMPRESS_ITEMS))
    tools = edit_items(kind, many)
    if tools:
        items.append(("edit", "Editar", tools))
    if kind == "video":
        items.append(("caption", "Legendar", []))
    items.append(("rename", "Renomear", []))  # renomear em lote: vale para qualquer tipo
    return items


class Radial:
    def __init__(self, root, app):
        self.root, self.app = root, app
        self.s = app.scale
        self.n = (R_OUTER + PAD) * 2
        self.size = self.n * self.s
        self.c = self.n // 2
        self.catcher = None
        self.catcher_up = None
        if MAC:
            self.win = self.hwnd = Overlay(self.size, self.size, click_through=True)
            self.catcher = DropCatcher()
        else:
            self.win = tk.Toplevel(root)
            self.win.withdraw()
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.win.geometry(f"{self.size}x{self.size}+0+0")
            self.win.update_idletasks()
            self.hwnd = user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            set_layered_style(self.hwnd, click_through=False)
            self.win.drop_target_register(DND_FILES)
            for ev, fn in (("<<DropEnter>>", self.on_enter), ("<<DropPosition>>", self.on_move),
                           ("<<DropLeave>>", self.on_leave), ("<<Drop>>", self.on_drop)):
                self.win.dnd_bind(ev, fn)
        self.kind = "image"
        self.many = False
        self.categories = categories_for(self.kind)
        self.cat = self.sub = self.center = None
        self.ring = 1.0
        self.ring_token = 0
        self.visible = self.armed = self.busy = False
        self.press_at = None
        self.ox = self.oy = 0
        self.cache = {}
        self.watch = MouseWatch()
        self.files = []
        self.drag_ended = False
        self.up_since = None
        self.shown_at = 0
        self.poll()
        self.root.after(2000, self.warm_up)

    def warm_up(self):
        """Prepara de antemão o que a primeira abertura gastaria: a roda abre na hora."""
        try:
            if MAC:
                import Quartz  # noqa: F401  (a primeira importação leva uns 160 ms)
            for kind in ("image", "video", "audio", "doc"):
                if self.visible:
                    return
                self.kind, self.many = kind, False
                self.categories = categories_for(kind)
                self.cat = self.sub = self.center = None
                self.ring = 1.0
                self.render()
        except Exception as error:
            log_error("roda", error)

    # --- detecção global
    def poll(self):
        try:
            self.release_catcher()
            if self.visible:
                if not self.busy:
                    self.track()
            else:
                lb = key_down(VK_LBUTTON)
                if lb and not self.busy:
                    if self.press_at is None:
                        self.press_at = cursor_pos()
                        self.armed = foreground_is_explorer()
                    elif self.armed and key_down(VK_SHIFT):
                        x, y = cursor_pos()
                        px, py = self.press_at
                        if abs(x - px) + abs(y - py) > 6 * self.s:
                            self.show(x, y)
                elif not lb:
                    self.press_at = None
                    self.armed = False
        except Exception as error:
            log_error("roda", error)
        self.root.after(16 if self.visible else 25, self.poll)

    def release_catcher(self):
        """A proteção só sai depois que o botão foi solto de verdade, mesmo se a roda foi cancelada."""
        if not self.catcher or not self.catcher.visible or (self.visible and not self.busy):
            self.catcher_up = None
            return
        if key_down(VK_LBUTTON):
            self.catcher_up = None
            return
        self.catcher_up = self.catcher_up or time.monotonic()
        if time.monotonic() - self.catcher_up > .25:
            self.catcher.hide()
            self.catcher_up = None

    def track(self):
        """A roda segue o cursor sozinha e só age quando o botão é solto de verdade."""
        if key_down(VK_ESCAPE):
            self.armed = False
            self.close()
            return
        if self.watch.running:
            if not self.watch.left:
                x, y = self.watch.release_at or cursor_pos()
                self.released(x, y)
                return
            if self.drag_ended and not key_down(VK_LBUTTON):  # segurança se o Windows derrubar a escuta
                self.up_since = self.up_since or time.monotonic()
                if time.monotonic() - self.up_since > 2:
                    self.close()
                    return
            else:
                self.up_since = None
        elif not key_down(VK_LBUTTON):
            x, y = cursor_pos()
            self.released(x, y)
            return
        self.update_hover(*cursor_pos())

    def released(self, x, y):
        self.update_hover(x, y)
        self.busy = True  # espera um instante pelos dados do arrasto, se ainda não chegaram
        self.root.after(70, self.apply_release, x, y)

    def apply_release(self, x, y):
        self.busy = False
        where, index = self.hit(x, y)
        self.execute(where, index, [f for f in self.files if self.kind == "mixed" or kind_of(f) == self.kind])

    def close(self):
        self.watch.stop()
        self.win.withdraw()
        self.visible = self.busy = False
        self.cat = self.sub = self.center = None

    def refuse(self, problem):
        """Seleção sem ação possível: não abre a roda e deixa o arrasto normal seguir."""
        self.armed = False
        self.app.pill.flash(*problem)

    def show(self, x, y):
        selected = explorer_selection()
        if MAC and not selected:  # o Finder ainda não publicou o arrasto: tenta de novo
            return
        problem = selection_problem(selected, allow_mixed=True)
        if problem:
            self.refuse(problem)
            return
        files = selected
        self.watch.start()
        self.files = files
        self.drag_ended = False
        self.up_since = None
        self.shown_at = time.monotonic()
        self.many = len(files) > 1
        self.set_kind(selection_kind(files))  # sem adivinhar o tipo
        left, top, right, bottom = monitor_work_area(x, y)
        self.ox = max(left, min(x - self.size // 2, right - self.size))
        self.oy = max(top, min(y - self.size // 2, bottom - self.size))
        self.win.geometry(f"{self.size}x{self.size}+{self.ox}+{self.oy}")
        if self.catcher:
            self.catcher.show()
        self.win.deiconify()
        self.visible = True
        self.cat = self.sub = self.center = None
        self.ring = 1.0
        self.paint()

    def set_kind(self, kind):
        self.kind = kind
        self.categories = categories_for(kind, self.many)
        if self.cat is not None and self.cat >= len(self.categories):
            self.cat = self.sub = None

    # --- geometria
    def center_text(self, g, text, y, color):
        size = .85
        width = int(center_width(y + 2 - self.c, y + 9 - self.c) / size)
        bold = text_width(text, True) <= width
        g.center(self.c - R_CENTER, y, R_CENTER * 2, fit(text, width, bold), color, bold, size)

    def category_angle(self, index):
        return -90 + index * 360 / len(self.categories)

    def item_angle(self, index):
        items = self.categories[self.cat][2]
        return self.category_angle(self.cat) + (index - (len(items) - 1) / 2) * 360 / len(items)

    def outer_open(self):
        return self.cat is not None and bool(self.categories[self.cat][2]) and self.center is None

    def hit(self, xr, yr):
        dx = (xr - (self.ox + self.size / 2)) / self.s
        dy = (yr - (self.oy + self.size / 2)) / self.s
        dist = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))
        if dist < R_CENTER:
            return ("center", None)
        if not self.categories:
            return (None, None)
        if dist <= R_INNER:
            step = 360 / len(self.categories)
            return ("inner", int(round((angle + 90) / step)) % len(self.categories))
        if self.outer_open() and dist <= R_OUTER:
            items = self.categories[self.cat][2]
            step = 360 / len(items)
            offset = (angle - self.category_angle(self.cat)) / step + (len(items) - 1) / 2
            return ("outer", int(round(offset)) % len(items))
        return (None, None)

    # --- desenho
    def wedge(self, d, factor, r0, r1, start, end, fill):
        steps = max(12, int(abs(end - start)))
        c = self.c * factor
        points = []
        for k in range(steps + 1):
            a = math.radians(start + (end - start) * k / steps)
            points.append((c + r1 * factor * math.cos(a), c + r1 * factor * math.sin(a)))
        for k in range(steps + 1):
            a = math.radians(end - (end - start) * k / steps)
            points.append((c + r0 * factor * math.cos(a), c + r0 * factor * math.sin(a)))
        d.polygon(points, fill=fill)

    def spoke(self, d, factor, r0, r1, angle, color=INK):
        a = math.radians(angle)
        c = self.c * factor
        d.line((c + r0 * factor * math.cos(a), c + r0 * factor * math.sin(a),
                c + r1 * factor * math.cos(a), c + r1 * factor * math.sin(a)), fill=color, width=factor)

    def disc(self, d, factor, radius, **style):
        c = self.c * factor
        r = radius * factor
        d.ellipse((c - r, c - r, c + r, c + r), **style)

    def render(self):
        key = (self.kind, self.many, self.cat, self.sub, self.center, round(self.ring, 2))
        if key in self.cache:
            return self.cache[key]
        c, n = self.c, self.n
        factor = self.s * 2  # desenha maior e reduz, para o círculo sair liso
        big = n * factor
        art = Image.new("RGB", (big, big), WHITE)
        shape = Image.new("L", (big, big), 0)
        d = ImageDraw.Draw(art)
        opened = self.outer_open()
        radius = int(R_INNER + (R_OUTER - R_INNER) * self.ring) if opened else R_INNER
        if not self.categories:
            radius = R_CENTER
        dim = opened and self.sub is not None  # o mouse está na segunda volta: a primeira fica em cinza
        self.disc(ImageDraw.Draw(shape), factor, radius, fill=255)
        count = len(self.categories)
        step = 360 / max(1, count)
        items = self.categories[self.cat][2] if opened else []
        if opened:
            self.disc(d, factor, radius, fill=WHITE, outline=INK, width=2 * factor)
            if self.ring >= 0.99:
                item_step = 360 / len(items)
                if self.sub is not None:
                    middle = self.item_angle(self.sub)
                    self.wedge(d, factor, R_OUTER_START, R_OUTER - 1, middle - item_step / 2, middle + item_step / 2, BLUE)
                for j in range(len(items)):
                    self.spoke(d, factor, R_OUTER_START, R_OUTER - 1, self.item_angle(j) - item_step / 2)
            self.disc(d, factor, R_OUTER_START, fill=INK)
        self.disc(d, factor, R_INNER, fill=(232, 232, 232) if dim else WHITE, outline=INK, width=2 * factor)
        if self.cat is not None:
            middle = self.category_angle(self.cat)
            self.wedge(d, factor, R_CENTER, R_INNER - 1, middle - step / 2, middle + step / 2, GRAY if dim else BLUE)
        if count > 1:
            for i in range(count):
                self.spoke(d, factor, R_CENTER, R_INNER, self.category_angle(i) - step / 2, GRAY if dim else INK)
        self.disc(d, factor, R_CENTER, fill=INK)
        if radius >= R_INNER:
            self.disc(d, factor, radius, outline=INK, width=2 * factor)

        g = Gfx(n, n, self.s)
        g.im.paste(art.resize((n * self.s, n * self.s), Image.Resampling.LANCZOS))
        if opened and self.ring >= 0.99:
            label_r = (R_OUTER_START + R_OUTER) / 2
            room = int((2 * math.pi * label_r / len(items) - 4) / .76)
            for j, (text, _) in enumerate(items):
                active = j == self.sub
                a = math.radians(self.item_angle(j))
                across = (R_OUTER - R_OUTER_START - 4) / max(abs(math.cos(a)), .01)  # largura que cabe no anel
                label = fit(text, int(min(room, 58, across / .76)), active)
                x = int(c + label_r * math.cos(a) - text_width(label, active, .76) / 2)
                y = int(c + label_r * math.sin(a) - LINE * .34)
                g.text(x, y, label, WHITE if active else INK, active, .76)
        label_r = (R_CENTER + R_INNER) / 2 + 1
        for i, (cat_id, text, _) in enumerate(self.categories):
            a = math.radians(self.category_angle(i))
            px, py = c + label_r * math.cos(a), c + label_r * math.sin(a)
            active = i == self.cat
            color = WHITE if active else (150, 150, 150) if dim else INK
            g.icon(CAT_ICON[cat_id], int(px - 9), int(py - 17), 18, color)
            g.center(int(px - 30), int(py + 3), 60, text, color, active, .74)
        if self.center is None:
            title = "Vários tipos" if self.kind == "mixed" else KIND_NAME.get(self.kind, "Arquivo")
            if self.cat is not None:
                _, title, entries = self.categories[self.cat]
                if self.sub is not None:
                    title = entries[self.sub][0]
            g.icon(KIND_ICON.get(self.kind, "doc"), c - 9, c - 22, 18, WHITE)
            self.center_text(g, title, c, WHITE)
        else:
            text, tone = self.center
            self.center_text(g, text, c - 5, RED if tone == "err" else WHITE)
        out = g.im.convert("RGBA")
        out.putalpha(shape.resize((n * self.s, n * self.s), Image.Resampling.LANCZOS))
        if len(self.cache) > 120:
            self.cache.clear()
        self.cache[key] = out
        return out

    def paint(self, alpha=255):
        if self.visible:
            push_layered(self.hwnd, self.render(), self.ox, self.oy, alpha)

    def open_ring(self):
        self.ring_token += 1
        token = self.ring_token
        self.ring = 0.6
        self.paint()

        def step(value):
            if token == self.ring_token:
                self.ring = value
                self.paint()
        self.root.after(30, step, 1.0)

    # --- eventos de arrastar
    def names_of(self, event):
        try:
            return list(self.root.tk.splitlist(event.data)) if event.data else []
        except Exception:
            return []

    def files_of(self, event):
        return [f for f in self.names_of(event) if kind_of(f)]

    def on_enter(self, event):
        names = self.names_of(event)
        problem = selection_problem(names, allow_mixed=True)
        if problem:  # o arrasto confirmou que esta seleção não tem ação
            self.close()
            self.refuse(problem)
            return "refuse_drop"
        files = names
        if files:
            self.files = files
            if selection_kind(files) != self.kind or (len(files) > 1) != self.many:
                self.many = len(files) > 1
                self.set_kind(selection_kind(files))
        return self.on_move(event)

    def update_hover(self, x, y):
        if self.busy or not self.visible:
            return
        where, index = self.hit(x, y)
        old_cat, old_sub = self.cat, self.sub
        if where == "inner":
            self.cat, self.sub = index, None
        elif where == "outer":
            self.sub = index
        elif where == "center":
            self.cat = self.sub = None
        else:
            self.sub = None
        if self.cat != old_cat:
            if self.outer_open():
                self.open_ring()
            else:
                self.ring = 1.0
                self.paint()
        elif self.sub != old_sub:
            self.paint()

    def on_move(self, event):
        self.update_hover(event.x_root, event.y_root)
        return "copy"  # nunca "mover": o original fica intacto

    def on_leave(self, event):
        return "copy"

    def on_drop(self, event):
        """O Windows pode encerrar o arrasto antes da hora: isso nunca dispara uma ação."""
        files = self.files_of(event)
        if files:
            self.files = files
        self.drag_ended = True
        if self.visible and self.watch.running and self.watch.left:
            log_error("roda", RuntimeError(f"arrasto encerrado com o botão pressionado após {time.monotonic() - self.shown_at:.1f}s"))
        return "copy"

    def execute(self, where, index, files):
        action = value = text = None
        if files and where == "outer":
            action, _, items = self.categories[self.cat]
            text, value = items[index]
        elif files and where == "inner" and self.categories[index][0] in DIRECT:
            action = self.categories[index][0]
            text = DIRECT[action]
        if action is None:
            self.close()
            return
        self.busy = True
        self.ring_token += 1
        self.cat = self.sub = None
        self.ring = 1.0
        self.center = (text, "busy")
        self.paint()
        if action == "convert":
            self.root.after(0, lambda: self.app.convert_paths(files, value))
        elif action == "compress":
            self.root.after(0, lambda: self.app.compress_paths(files, value, notify=True))
        elif action == "edit":
            self.root.after(0, lambda: self.app.tool(value, files))
        elif action == "rename":
            self.root.after(0, lambda: self.app.tool("rename", files))
        else:
            self.root.after(0, lambda: self.app.open_captions(files))
        self.root.after(150, self.close)
