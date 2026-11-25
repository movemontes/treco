"""Mini janela de progresso que segue o mouse."""
import itertools
import time
import tkinter as tk

from .pixel import BLUE, DARK, INK, RED, WHITE, Gfx, fit
from ..core.paths import MAC

if MAC:
    from .platform_mac import Overlay, cursor_pos, monitor_work_area, push_layered
else:
    from .winapi import cursor_pos, monitor_work_area, push_layered, set_layered_style, user32

WIDTH, HEIGHT = 172, 36
OFFSET_X, OFFSET_Y = 18, 20
FRAME_MS = 33


class ProgressPill:
    def __init__(self, root, scale=2):
        self.root = root
        self.s = scale
        self.w, self.h = WIDTH * scale, HEIGHT * scale
        if MAC:
            self.win = self.hwnd = Overlay(self.w, self.h, click_through=True)
        else:
            self.win = tk.Toplevel(root)
            self.win.withdraw()
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.win.geometry(f"{self.w}x{self.h}+0+0")
            self.win.update_idletasks()
            self.hwnd = user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            set_layered_style(self.hwnd, click_through=True)
        self.ids = itertools.count(1)
        self.tasks = {}
        self.done = self.failed = self.total = 0
        self.running = self.visible = False
        self.x = self.y = 0.0
        self.finish_until = 0
        self.last_key = None
        self.image = None
        self.info = None
        self.info_until = 0

    # --- chamadas seguras de qualquer thread
    def begin(self, label):
        task = next(self.ids)
        self.root.after(0, self._begin, task, label)
        return task

    def update(self, task, fraction):
        self.root.after(0, self._update, task, fraction)

    def end(self, task, ok=True):
        self.root.after(0, self._end, task, ok)

    def flash(self, title, detail):
        """Aviso curto perto do mouse, que não atrapalha o arrasto."""
        self.root.after(0, self._flash, title, detail)

    def _flash(self, title, detail):
        self.info = (title, detail)
        self.info_until = time.monotonic() + 2.6
        self.last_key = None
        if not self.tasks:
            self.done = self.failed = self.total = 0
            self.finish_until = self.info_until
        self.start()

    def _begin(self, task, label):
        if not self.tasks:
            self.done = self.failed = self.total = 0
        self.finish_until = 0
        self.tasks[task] = {"label": label, "fraction": None}
        self.total += 1
        self.start()

    def _update(self, task, fraction):
        if task in self.tasks:
            self.tasks[task]["fraction"] = max(self.tasks[task]["fraction"] or 0, min(1.0, fraction))

    def _end(self, task, ok):
        if self.tasks.pop(task, None) is None:
            return
        self.done += 1
        self.failed += ok is False
        if not self.tasks:
            self.finish_until = time.monotonic() + (1.6 if self.failed else 1.0)

    # --- movimento
    def target(self):
        x, y = cursor_pos()
        left, top, right, bottom = monitor_work_area(x, y)
        off_x, off_y = OFFSET_X * self.s, OFFSET_Y * self.s
        tx = x + off_x if x + off_x + self.w <= right else x - off_x - self.w
        ty = y + off_y if y + off_y + self.h <= bottom else y - off_y - self.h
        return max(left, min(tx, right - self.w)), max(top, min(ty, bottom - self.h))

    def start(self):
        if self.running:
            return
        self.running = self.visible = True
        self.x, self.y = self.target()
        self.last_key = None
        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")
        self.win.deiconify()
        self.tick()

    def tick(self):
        if not self.running:
            return
        tx, ty = self.target()
        self.x += (tx - self.x) * 0.45
        self.y += (ty - self.y) * 0.45
        if abs(tx - self.x) < self.s:
            self.x = tx
        if abs(ty - self.y) < self.s:
            self.y = ty
        if not self.tasks and time.monotonic() >= self.finish_until:
            self.running = self.visible = False
            self.win.withdraw()
            return
        try:
            self.draw()
        except Exception:
            pass
        self.root.after(FRAME_MS, self.tick)

    # --- desenho
    def state(self):
        if self.info and time.monotonic() < self.info_until:
            return self.info[0], None, "info"
        self.info = None
        if self.tasks:
            active = list(self.tasks.values())
            known = [t["fraction"] for t in active if t["fraction"] is not None]
            if self.total == 1:
                label = active[0]["label"]
            else:
                from ..core.i18n import english, tr
                label = f"{tr(active[0]['label']).split()[0]} {self.done + 1} {'of' if english() else 'de'} {self.total}"
            if len(known) == len(active) or self.total > 1:
                return label, (self.done + sum(known)) / self.total, "work"
            return label, None, "pulse"
        if self.failed:
            return ("Não deu certo" if self.failed == self.total else f"{self.failed} com erro"), 1.0, "error"
        return ("Pronto!" if self.total <= 1 else f"{self.total} prontos!"), 1.0, "done"

    def draw(self):
        label, value, mode = self.state()
        phase = int(time.monotonic() * 14) if mode == "pulse" else 0
        key = (label, None if value is None else int(value * 60), mode, phase)
        if key != self.last_key:
            self.last_key = key
            g = Gfx(WIDTH, HEIGHT, self.s)
            g.rect(0, 0, WIDTH, HEIGHT, fill=WHITE, line=INK)
            g.rect(1, 1, WIDTH - 2, HEIGHT - 2, line=INK)
            left, top, inner = 7, 5, WIDTH - 14
            percent = "" if value is None or mode != "work" else f"{int(value * 100)}%"
            right = left + inner
            if percent:
                g.right(right, top, percent, BLUE, True)
                right -= 34
            if mode == "info":
                g.text(left, top, fit(label, inner, True), INK, True)
                g.text(left, top + 13, fit(self.info[1], inner), DARK)
            elif mode == "done":
                g.text(left, top, "✓", BLUE, True)
                g.text(left + 11, top, fit(label, right - left - 11, True), BLUE, True)
            else:
                g.text(left, top, fit(label, right - left, True), RED if mode == "error" else INK, True)
            if mode == "info":
                pass
            elif value is None:
                g.barber(left, top + 15, inner, 9, phase, BLUE)
            else:
                g.blocks(left, top + 15, inner, 9, value, RED if mode == "error" else BLUE)
            self.image = g.im.convert("RGBA")
        push_layered(self.hwnd, self.image, int(self.x), int(self.y))
