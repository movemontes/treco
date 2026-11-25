"""Interface própria em pixels: janela sem moldura do sistema, botões, listas e campos de texto."""
import ctypes
import tkinter as tk

from PIL import ImageTk

from .pixel import BLUE, DARK, GRAY, INK, LINE, WHITE, Gfx, fit, text_width
from ..core.paths import MAC

if MAC:
    from . import platform_mac as mac
else:
    from .winapi import VP, user32


def pick_scale(root, width, height):
    """Escala inteira: cada pixel do Treco vira um quadrado exato na tela."""
    dpi = root.winfo_fpixels("1i") / 96
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight() - 56
    scale = max(2, round(dpi * 2))
    while scale > 2 and (width * scale > screen_w or height * scale > screen_h):
        scale -= 1
    return scale, min(height, screen_h // scale)


class TextField:
    def __init__(self, text="", limit=500):
        self.text, self.caret, self.limit = text, len(text), limit

    def set(self, text):
        self.text, self.caret = text, len(text)

    def key(self, keysym, char, ctrl, host):
        if ctrl and keysym.lower() == "v":
            try:
                pasted = " ".join(host.win.clipboard_get().split())
            except tk.TclError:
                pasted = ""
            self.insert(pasted)
        elif ctrl and keysym.lower() == "a":
            self.caret = len(self.text)
        elif keysym == "BackSpace" and self.caret:
            self.text = self.text[:self.caret - 1] + self.text[self.caret:]
            self.caret -= 1
        elif keysym == "Delete":
            self.text = self.text[:self.caret] + self.text[self.caret + 1:]
        elif keysym == "Left":
            self.caret = max(0, self.caret - 1)
        elif keysym == "Right":
            self.caret = min(len(self.text), self.caret + 1)
        elif keysym == "Home":
            self.caret = 0
        elif keysym == "End":
            self.caret = len(self.text)
        elif char and char.isprintable() and not ctrl:
            self.insert(char)

    def insert(self, value):
        value = value[:max(0, self.limit - len(self.text))]
        self.text = self.text[:self.caret] + value + self.text[self.caret:]
        self.caret += len(value)


class PixelHost:
    def __init__(self, win, width, height, scale, draw, title):
        self.win, self.w, self.h, self.s, self.draw_fn = win, width, height, scale, draw
        self.g = Gfx(width, height, scale)
        from ..core.i18n import tr
        win.title(tr(title))
        if MAC:
            mac.borderless(win)
        else:
            win.overrideredirect(True)
        win.geometry(f"{width * scale}x{height * scale}")
        win.configure(bg="#FFFFFF")
        self.photo = ImageTk.PhotoImage("RGB", (width * scale, height * scale))
        self.label = tk.Label(win, image=self.photo, bd=0, highlightthickness=0, cursor="arrow")
        self.label.pack()
        self.mx = self.my = -1
        self.pressed = self.released = self.right = False
        self.context = False  # clique com o botão direito neste quadro
        self.double = False  # clique duplo neste quadro
        self.down = False
        self.active = self.focus = None
        self.enabled = True
        self.keys = []
        self.wheel = 0
        self.overlays = []
        self.queued = False
        self.drag = None
        self.sizing = None  # puxando uma borda para mudar o tamanho
        self.resizable = None  # (limites, função) quando a janela pode mudar de tamanho
        self.cursor_now = "arrow"
        self.tick_count = 0
        self.alive = True
        self.after_frame = []
        for name, fn in (("<Motion>", self.on_motion), ("<ButtonPress-1>", self.on_press), ("<ButtonRelease-1>", self.on_release),
                         ("<MouseWheel>", self.on_wheel), ("<Leave>", self.on_leave)):
            self.label.bind(name, fn)
        # botão direito: no Mac é o botão 2 (ou Control + clique); no Windows, o 3
        for name in (("<ButtonPress-2>", "<Control-ButtonPress-1>") if MAC else ("<ButtonPress-3>",)):
            self.label.bind(name, self.on_context)
        self.label.bind("<Double-ButtonPress-1>", self.on_double)
        win.bind("<KeyPress>", self.on_key)
        win.after(10, self.setup_native)
        win.after(500, self.blink)

    # --- janela de verdade no Windows, sem a moldura do sistema
    def hwnd(self):
        return user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()

    def setup_native(self):
        if MAC:
            try:
                mac.finish_window(self.win)
            except Exception:
                pass
            return
        try:
            handle = self.hwnd()
            style = user32.GetWindowLongW(handle, -16)
            user32.SetWindowLongW(handle, -16, style | 0x00020000)  # pode minimizar
            ex = user32.GetWindowLongW(handle, -20)
            user32.SetWindowLongW(handle, -20, (ex & ~0x80) | 0x40000)  # aparece na barra de tarefas
            corner = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(VP(handle), 33, ctypes.byref(corner), ctypes.sizeof(corner))
            if self.win.state() == "normal":
                self.win.withdraw()
                self.win.after(10, self.win.deiconify)
        except Exception:
            pass

    def minimize(self):
        if MAC:
            mac.minimize(self.win)
            return
        user32.ShowWindow(VP(self.hwnd()), 6)

    def destroy(self):
        self.alive = False

    # --- entrada
    def to_local(self, event):
        return event.x // self.s, event.y // self.s

    def on_motion(self, event):
        self.mx, self.my = self.to_local(event)
        if self.sizing:
            self.drag_size(event)
            return
        if self.resizable:
            self.edge_cursor(self.edges(self.mx, self.my))
        if self.drag:
            x = event.x_root - self.drag[0]
            y = event.y_root - self.drag[1]
            self.win.geometry(f"+{x}+{y}")
            return
        self.invalidate()

    def on_press(self, event):
        self.mx, self.my = self.to_local(event)
        self.pressed = self.down = True
        try:
            self.win.focus_force()
        except tk.TclError:
            pass
        self.frame()

    def on_double(self, event):
        self.mx, self.my = self.to_local(event)
        self.pressed = self.down = self.double = True
        self.frame()

    def on_context(self, event):
        self.mx, self.my = self.to_local(event)
        self.context = True
        self.frame()
        return "break"

    def on_release(self, event):
        self.mx, self.my = self.to_local(event)
        self.down = False
        self.released = True
        self.drag = None
        if self.sizing:
            self.sizing = None
            self.pressed = False
        self.frame()

    def on_wheel(self, event):
        self.wheel += 1 if event.delta < 0 else -1
        self.invalidate()

    def on_leave(self, event):
        if not self.down:
            self.mx = self.my = -1
            self.invalidate()

    def on_key(self, event):
        ctrl = bool(event.state & (0x8 if MAC else 0x4))  # Cmd no Mac, Ctrl no Windows
        self.keys.append((event.keysym, event.char, ctrl))
        self.invalidate()

    def blink(self):
        if not self.alive:
            return
        self.tick_count += 1
        if self.focus is not None:
            self.invalidate()
        self.win.after(500, self.blink)

    def invalidate(self):
        if not self.queued and self.alive:
            self.queued = True
            self.win.after_idle(self.frame)

    def later(self, fn, *args):
        self.after_frame.append((fn, args))

    # --- desenho
    def frame(self):
        self.queued = False
        if not self.alive:
            return
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        self.overlays = []
        self.enabled = True
        self.draw_fn(self)
        if self.released:
            self.active = None
        self.pressed = self.released = self.context = self.double = False
        self.keys = []
        self.wheel = 0
        image = self.g.im
        for overlay, x, y in self.overlays:
            image.paste(overlay, (x, y))
        self.photo.paste(image)
        pending, self.after_frame = self.after_frame, []
        for fn, args in pending:
            self.win.after_idle(fn, *args)

    def over(self, x, y, w, h):
        return self.enabled and x <= self.mx < x + w and y <= self.my < y + h

    def clickable(self, key, x, y, w, h, enabled=True):
        hover = enabled and self.over(x, y, w, h)
        if hover and self.pressed:
            self.active = key
        held = hover and self.active == key and self.down
        clicked = hover and self.released and self.active == key
        return hover, held, clicked

    # --- peças da interface: preto, branco, linha grossa
    def chassis(self):
        self.g.rect(0, 0, self.w, self.h, fill=WHITE)
        self.g.rect(0, 0, self.w, self.h, line=INK)

    def ink(self, hover=False, held=False, selected=False, enabled=True, tone=None):
        """Cor do conteúdo de uma tecla, em cada estado."""
        if not enabled:
            return GRAY
        if held or selected or tone:
            return WHITE
        return BLUE if hover else INK

    def face(self, x, y, w, h, hover=False, held=False, selected=False, enabled=True, tone=None):
        g = self.g
        if not enabled:
            g.rect(x, y, w, h, fill=WHITE, line=GRAY)
        elif held or selected:
            g.rect(x, y, w, h, fill=INK)
        elif tone:
            g.rect(x, y, w, h, fill=INK if hover else BLUE)
        else:
            g.rect(x, y, w, h, fill=WHITE, line=BLUE if hover else INK)
            if hover:
                g.rect(x + 1, y + 1, w - 2, h - 2, line=BLUE)
        return 0

    def mark_x(self, x, y, size, color):
        self.g.icon("x", x, y, size + 1, color)

    def mini(self, key, x, y, size, draw_mark, enabled=True):
        """Botãozinho sem moldura. draw_mark recebe x, y e a cor."""
        hover, held, clicked = self.clickable(key, x, y, size, size, enabled)
        if held:
            self.g.rect(x, y, size, size, fill=INK)
        draw_mark(x, y, GRAY if not enabled else WHITE if held else BLUE if hover else INK)
        return clicked

    def panel(self, x, y, w, h, title, close=None, frame=True):
        g = self.g
        if frame:
            g.rect(x, y, w, h, fill=WHITE, line=INK)
            g.rect(x + 1, y + 1, w - 2, h - 2, line=INK)
        g.hline(x, y + 17, w, INK)
        g.hline(x, y + 16, w, INK)
        g.text(x + 7, y + 4, fit(title, w - 34, True), INK, True)
        if close:
            mark = lambda bx, by, color: self.mark_x(bx + 1, by + 1, 10, color)
            if self.mini(("close", title), x + w - 17, y + 2, 13, mark):
                self.later(close)

    def resize(self, width, height, x=None, y=None):
        """Muda o tamanho da janela (em pixels do Treco) e redesenha. x, y: nova posição na tela."""
        self.w, self.h = width, height
        self.g = Gfx(width, height, self.s)
        self.photo = ImageTk.PhotoImage("RGB", (width * self.s, height * self.s))
        self.label.configure(image=self.photo)
        place = f"+{x}+{y}" if x is not None else ""
        self.win.geometry(f"{width * self.s}x{height * self.s}{place}")
        self.frame()

    EDGE = 4  # largura da borda que dá para puxar, em pixels do Treco
    CORNER = 12

    def edges(self, x, y):
        """Quais lados ficam embaixo do mouse: "l", "r", "t", "b" (ou vazio)."""
        if not (0 <= x < self.w and 0 <= y < self.h):
            return ""
        sides = ""
        if x < self.EDGE or (x < self.CORNER and (y < self.EDGE or y >= self.h - self.EDGE)):
            sides += "l"
        if x >= self.w - self.EDGE or (x >= self.w - self.CORNER and (y < self.EDGE or y >= self.h - self.CORNER)):
            sides += "r"
        if y < self.EDGE // 2 + 1:
            sides += "t"
        if y >= self.h - self.EDGE or (y >= self.h - self.CORNER and x >= self.w - self.CORNER):
            sides += "b"
        return sides

    def edge_cursor(self, sides):
        mac_names = {"l": "resizeleftright", "r": "resizeleftright", "t": "resizeupdown", "b": "resizeupdown"}
        win_names = {"l": "sb_h_double_arrow", "r": "sb_h_double_arrow", "t": "sb_v_double_arrow",
                     "b": "sb_v_double_arrow", "diag": "size_nw_se"}
        if not sides:
            name = "arrow"
        elif len(sides) == 2:
            name = "cross" if MAC else win_names["diag"]
        else:
            name = (mac_names if MAC else win_names)[sides]
        if name != self.cursor_now:
            try:
                self.label.configure(cursor=name)
                self.cursor_now = name
            except tk.TclError:
                self.cursor_now = name

    def resize_grip(self, limits, on_size):
        """Deixa puxar qualquer borda ou canto para mudar o tamanho. Chamar antes dos outros botões."""
        self.resizable = (limits, on_size)
        sides = self.edges(self.mx, self.my)
        if self.pressed and sides and self.active is None:
            self.sizing = (self.win.winfo_pointerx(), self.win.winfo_pointery(), self.w, self.h,
                           self.win.winfo_rootx(), self.win.winfo_rooty(), sides)
            self.pressed = False  # o clique é da borda, não do botão embaixo dela

    def drag_size(self, event):
        start_x, start_y, start_w, start_h, win_x, win_y, sides = self.sizing
        (min_w, min_h, max_w, max_h), on_size = self.resizable
        dx, dy = (event.x_root - start_x) // self.s, (event.y_root - start_y) // self.s
        clamp = lambda value, low, high: max(low, min(high, value))
        w, h, x, y = start_w, start_h, win_x, win_y
        if "r" in sides:
            w = clamp(start_w + dx, min_w, max_w)
        if "l" in sides:
            w = clamp(start_w - dx, min_w, max_w)
            x = win_x + (start_w - w) * self.s
        if "b" in sides:
            h = clamp(start_h + dy, min_h, max_h)
        if "t" in sides:
            h = clamp(start_h - dy, min_h, max_h)
            y = win_y + (start_h - h) * self.s
        if (w, h) != (self.w, self.h):
            moved = "l" in sides or "t" in sides
            self.resize(w, h, x if moved else None, y if moved else None)
            on_size(w, h)

    def draw_grip(self, color):
        """Três riscos diagonais no canto, como nas janelas antigas."""
        for n in (3, 6, 9):
            for i in range(n):
                self.g.dot(self.w - 2 - i, self.h - 2 - n + 1 + i, color)

    def drag_area(self, x, y, w, h):
        if self.pressed and self.over(x, y, w, h) and self.active is None:
            self.drag = (self.win.winfo_pointerx() - self.win.winfo_rootx(),
                         self.win.winfo_pointery() - self.win.winfo_rooty())

    def button(self, key, x, y, w, h, text="", on=None, enabled=True, image=None, tone=None, selected=False, bold=False, size=1):
        g = self.g
        hover, held, clicked = self.clickable(key, x, y, w, h, enabled)
        self.face(x, y, w, h, hover, held, selected, enabled, tone)
        color = self.ink(hover, held, selected, enabled, tone)
        heavy = bold or hover or selected
        if image:
            g.icon(image, x + 4 if text else x + (w - 14) // 2, y + (h - 14) // 2, 14, color)
        if text:
            left = x + (20 if image else 0)
            area = w - (20 if image else 0)
            label = fit(text, max(4, int((area - 2) / size)), heavy)
            g.center(left, y + int((h - 9 * size) / 2) - 1, area, label, color, heavy, size)
        if clicked and on:
            self.later(on)
        return clicked

    def entry(self, key, x, y, w, h, field, numeric=False, flat=False, secret=False):
        g, s = self.g, self.s
        hover, held, clicked = self.clickable(key, x, y, w, h)
        if self.pressed and hover:
            self.focus = key
            field.caret = self.caret_at(field, self.mx - x - 6, secret)
        focused = self.focus == key
        if focused:
            for keysym, char, ctrl in self.keys:
                if numeric and char and char.isprintable() and not ctrl and char not in "0123456789.,":
                    continue
                field.key(keysym, char, ctrl, self)
        if not flat:
            g.rect(x, y, w, h, fill=WHITE, line=BLUE if focused or hover else INK)
            if focused:
                g.rect(x + 1, y + 1, w - 2, h - 2, line=BLUE)
        shown = "•" * len(field.text) if secret else field.text
        before = shown[:field.caret]
        shift = max(0, text_width(before) - (w - 14)) if focused else 0
        temp = Gfx(w - 10, h - 2, s)
        temp.im.paste(g.im.crop(((x + 5) * s, (y + 1) * s, (x + w - 5) * s, (y + h - 1) * s)))
        temp.text(1 - shift, (h - 2 - LINE) // 2, shown, INK)
        if focused and self.tick_count % 2 == 0:
            temp.vline(1 - shift + text_width(before) + (1 if before else 0), 1, h - 4, INK)
        g.im.paste(temp.im, ((x + 5) * s, (y + 1) * s))
        return focused

    def caret_at(self, field, px, secret=False):
        text = "•" * len(field.text) if secret else field.text
        for i in range(len(text) + 1):
            if text_width(text[:i]) >= px:
                return i
        return len(text)

    def slider(self, key, x, y, w, value, low, high):
        g = self.g
        hover, held, _ = self.clickable(key, x, y, w, 11)
        if self.active == key and self.down:
            value = low + (high - low) * max(0, min(1, (self.mx - x - 3) / max(1, w - 7)))
            value = int(round(value))
        g.rect(x, y + 4, w, 3, fill=WHITE, line=INK)
        knob = x + int((value - low) / max(1, high - low) * (w - 7))
        g.rect(x, y + 4, knob - x, 3, fill=INK)
        g.rect(knob, y, 7, 11, fill=BLUE if hover or self.active == key else INK)
        return value

    def scrollbar(self, key, x, y, h, total, view, position):
        """Barra de rolagem. Devolve a nova posição."""
        g = self.g
        limit = max(0, total - view)
        if limit <= 0:
            return 0
        g.rect(x, y, 12, h, fill=WHITE)
        g.vline(x, y, h, INK)
        step = max(1, view // 2)
        for k, delta, top in ((f"{key}-up", -step, y), (f"{key}-dn", step, y + h - 12)):
            def arrow(bx, by, color, down=delta > 0):
                for row in range(4):
                    yy = by + 4 + row if not down else by + 7 - row
                    g.hline(bx + 6 - row, yy, row * 2 + 1, color)
            if self.mini(k, x + 1, top, 11, arrow):
                position += delta
        track_y, track_h = y + 12, h - 24
        thumb_h = max(10, track_h * view // total)
        room = track_h - thumb_h
        hover, held, _ = self.clickable(f"{key}-track", x, track_y, 12, track_h)
        if self.active == f"{key}-track" and self.down and room > 0:
            position = int((self.my - track_y - thumb_h / 2) / room * limit)
        position = max(0, min(limit, position))
        thumb_y = track_y + int(position / limit * room)
        g.rect(x + 2, thumb_y, 9, thumb_h, fill=BLUE if hover else INK)
        return position

    def checkbox(self, key, x, y, text, value):
        g = self.g
        width = 15 + text_width(text, True)
        hover, held, clicked = self.clickable(key, x, y, width, 12)
        tone = BLUE if hover else INK
        g.rect(x, y + 1, 10, 10, fill=tone if value else WHITE, line=tone)
        if value:
            g.icon("x", x + 1, y + 2, 8, WHITE)
        g.text(x + 15, y + 1, text, tone, hover)
        return (not value) if clicked else value

    def segmented(self, key, x, y, w, values, current):
        each = w // len(values)
        for i, value in enumerate(values):
            cx = x + i * each
            hover, held, clicked = self.clickable((key, value), cx, y, each, 15)
            selected = value == current
            self.face(cx, y, each + 1, 15, hover, held, selected)
            self.g.center(cx, y + 3, each, fit(value, each - 4, hover or selected), self.ink(hover, held, selected), hover or selected)
            if clicked:
                current = value
        return current
