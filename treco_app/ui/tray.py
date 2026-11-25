"""Ícone perto do relógio e início junto com o sistema."""
import os
import sys

from ..core.paths import MAC
from .icons import mascot

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --bandeja'
    return f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{os.path.abspath(sys.argv[0])}" --bandeja'


AGENT_LABEL = "app.treco.autostart"


def agent_path():
    return os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist")


def agent_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--bandeja"]
    if ".app/Contents/MacOS/" in sys.executable:  # aberto pelo Treco.app da pasta do projeto
        return [os.path.join(os.path.dirname(sys.executable), "Treco"), "--bandeja"]
    return [sys.executable, os.path.abspath(sys.argv[0]), "--bandeja"]


def autostart_on():
    if MAC:
        return os.path.exists(agent_path())
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Treco")
            return True
    except OSError:
        return False


def autostart_toggle():
    if MAC:
        import plistlib
        path = agent_path()
        if os.path.exists(path):
            os.remove(path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": agent_command(), "RunAtLoad": True}, f)
        return
    import winreg
    enabled = autostart_on()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.DeleteValue(k, "Treco")
        else:
            winreg.SetValueEx(k, "Treco", 0, winreg.REG_SZ, autostart_cmd())


def start_tray(root, app):
    try:
        import pystray
    except Exception:
        return None

    def show(_=None, __=None):
        root.after(0, lambda: (root.deiconify(), root.lift(), root.focus_force()))

    def quit_app(icon, _):
        root.after(0, app.quit)

    menu = pystray.Menu(
        pystray.MenuItem("Abrir o Treco", show, default=True),
        pystray.MenuItem("Iniciar com o Windows", lambda i, _: autostart_toggle(), checked=lambda _: autostart_on()),
        pystray.MenuItem("Sair", quit_app),
    )
    icon = pystray.Icon("Treco", mascot(64), "Treco: segure Shift ao arrastar um arquivo", menu)
    icon.run_detached()
    return icon
