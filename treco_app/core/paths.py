"""Onde o Treco guarda dados e procura programas, em cada sistema."""
import os
import shutil
import sys

MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"


def data_dir():
    """Pasta dos dados do app, como o modelo de voz."""
    if MAC:
        return os.path.expanduser("~/Library/Application Support/Treco")
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Treco")


def log_dir():
    if MAC:
        return os.path.expanduser("~/Library/Logs/Treco")
    return data_dir()


def bundled_dirs():
    """Pastas de programas que vão dentro do app."""
    dirs = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dirs.append(os.path.join(base, "bin"))
    dirs.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "vendor", "bin"))
    return dirs


def find_tool(name):
    """Acha um programa. Apps abertos pelo Finder não enxergam o PATH do Terminal."""
    places = bundled_dirs()
    if MAC:
        for folder in places:
            path = os.path.join(folder, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    found = shutil.which(name)
    if found:
        return found
    if MAC:
        for folder in ("/opt/homebrew/bin", "/usr/local/bin"):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None
