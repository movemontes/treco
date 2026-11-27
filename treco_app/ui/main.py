"""Inicia o Treco."""
import ctypes
import os
import sys
import tempfile
import tkinter as tk

from ..core.engine import compress_file, convert_file, transform_file
from ..core.formats import COMPRESSIBLE, MB, OUTS, kind_of
from ..core.jobs import NothingToGain
from ..core.paths import MAC


def command_line():
    """Uso sem janela. Devolve True se tratou o comando."""
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "--converter":
        src, fmt = os.path.abspath(args[1]), args[2].upper()
        kind = kind_of(src)
        if not kind or fmt not in OUTS[kind]:
            sys.exit(2)
        try:
            convert_file(src, kind, fmt)
        except Exception:
            sys.exit(1)
        return True
    if len(args) == 3 and args[0] == "--comprimir":
        src, value = os.path.abspath(args[1]), args[2].lower()
        kind = kind_of(src)
        if kind not in COMPRESSIBLE:
            sys.exit(2)
        mode = int(float(value[:-2].replace(",", ".")) * MB) if value.endswith("mb") else value
        try:
            compress_file(src, kind, mode)
        except NothingToGain:
            sys.exit(3)
        except Exception:
            sys.exit(1)
        return True
    if len(args) == 3 and args[0] == "--editar":
        try:
            src = os.path.abspath(args[1])
            transform_file(src, kind_of(src), args[2])
        except Exception:
            sys.exit(1)
        return True
    if len(args) == 3 and args[0] == "--rapido":  # mute, volume, clean ou split
        from ..modules import quick
        op, src = args[1], os.path.abspath(args[2])
        kind = kind_of(src)
        try:
            if op == "mute":
                quick.mute(src)
            elif op == "volume":
                quick.volume(src, kind)
            elif op == "clean":
                quick.clean(src, kind)
            elif op == "split":
                quick.split_pdf(src)
            else:
                sys.exit(2)
        except Exception:
            sys.exit(1)
        return True
    if len(args) == 2 and args[0] == "--legendar":
        from ..modules import captions
        try:
            src = os.path.abspath(args[1])
            captions.burn(src, captions.transcribe(src), captions.Style())
        except Exception:
            sys.exit(1)
        return True
    return False


def single_instance():
    if MAC:
        from .platform_mac import single_instance as mac_single
        return mac_single()
    ctypes.windll.kernel32.CreateMutexW(None, False, "Treco-Mutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def set_window_icon(root):
    from .icons import mascot
    if MAC:
        from .icons import app_icon
        from .platform_mac import set_dock_icon
        try:
            set_dock_icon(app_icon(512))
        except Exception:
            pass
        return
    try:
        path = os.path.join(tempfile.gettempdir(), "treco_icon.ico")
        if not os.path.exists(path):
            mascot(256).save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
        root.iconbitmap(path)
    except Exception:
        pass


def main():
    if command_line():
        return
    if not single_instance():
        return
    if not MAC:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    from .window import App, DND_OK
    if DND_OK:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    if MAC:
        root.withdraw()
    set_window_icon(root)
    app = App(root)
    x = (root.winfo_screenwidth() - app.w * app.scale) // 2
    y = max(0, (root.winfo_screenheight() - 56 - app.h * app.scale) // 2)
    app.win.geometry(f"+{x}+{y}")
    args = [a for a in sys.argv[1:] if a != "--bandeja"]
    if args:  # arquivos passados via "Abrir com" / arrastar no ícone
        app.add_files(args)
    if MAC:
        from .platform_mac import activate

        from .platform_mac import dock_visible

        def show():
            try:
                dock_visible(True)
            except Exception:
                pass
            app.win.deiconify()
            app.win.lift()
            activate()
            app.win.focus_force()
        root.createcommand("tk::mac::ReopenApplication", show)  # clicar no ícone do Dock
        root.createcommand("tk::mac::Quit", app.quit)
        root.createcommand("tk::mac::OpenDocument", lambda *paths: (show(), app.add_files(list(paths))))
        from .wheel import Radial
        app.wheel = Radial(root, app)
        from .mac_menus import app_menus, start_menubar
        app.menubar = start_menubar(root, app, show)
        try:
            app_menus(root, app, show)
        except Exception as error:
            from ..core.log import log_error
            log_error("menus do app", error)
    elif DND_OK:
        from .tray import start_tray
        from .wheel import Radial
        app.wheel = Radial(root, app)
        app.tray = start_tray(root, app)
        if app.tray:
            root.protocol("WM_DELETE_WINDOW", root.withdraw)
    if "--bandeja" in sys.argv:
        app.hide_window() if MAC else app.win.withdraw()
    elif MAC:
        root.after(120, show)
    if "--bandeja" not in sys.argv:
        from .welcome import show_once
        # recado de boas-vindas e depois o tour do Disquetinho, só na primeira vez
        root.after(900, lambda: show_once(app, then=app.maybe_tour))
    from .update_ui import check_later
    check_later(app)  # versão nova no GitHub? confere uma vez por dia
    root.mainloop()
