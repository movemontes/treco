"""Desinstalar um app por completo (só no Mac): o app e o que ele espalhou pela Biblioteca.

Tudo vai para o Lixo (dá para recuperar). Apps da Apple e o próprio Treco ficam de fora.
"""
import glob
import os
import plistlib
import subprocess

from .cleanup import folder_size

# pasta da Biblioteca: modelos de nome (com {id} = identificador do app e {name} = nome do app)
PLACES = (
    ("Application Support", ("{name}", "{id}")),
    ("Caches", ("{id}", "{name}")),
    ("Preferences", ("{id}.plist", "{id}.*.plist")),
    ("Containers", ("{id}",)),
    ("Group Containers", ("group.{id}*",)),
    ("Saved Application State", ("{id}.savedState",)),
    ("Logs", ("{name}", "{id}")),
    ("HTTPStorages", ("{id}", "{id}.binarycookies")),
    ("WebKit", ("{id}",)),
    ("Cookies", ("{id}.binarycookies",)),
    ("LaunchAgents", ("{id}*.plist",)),
    ("Application Scripts", ("{id}",)),
    ("Caches/com.apple.helpd/Generated", ("{id}*",)),
)


def app_info(app_path):
    with open(os.path.join(app_path, "Contents", "Info.plist"), "rb") as f:
        info = plistlib.load(f)
    name = info.get("CFBundleName") or os.path.splitext(os.path.basename(app_path))[0]
    return {"id": info.get("CFBundleIdentifier") or "", "name": name,
            "file_name": os.path.splitext(os.path.basename(app_path))[0]}


def problem(app_path):
    """Motivo para não desinstalar, ou None."""
    if not app_path.endswith(".app") or not os.path.isdir(app_path):
        return "Escolha um app (.app)"
    real = os.path.realpath(app_path)
    if real.startswith("/System/"):
        return "Esse app faz parte do macOS"
    try:
        info = app_info(app_path)
    except (OSError, ValueError):
        return "Não consegui ler esse app"
    if info["id"].startswith("com.apple."):
        return "Apps da Apple ficam: o Mac precisa deles"
    if info["id"] == "app.treco":
        return "O Treco não desinstala ele mesmo"
    return None


def leftovers(app_path, library=None):
    """O que o app deixou na Biblioteca do usuário: [(caminho, tamanho)]."""
    library = library or os.path.expanduser("~/Library")
    info = app_info(app_path)
    found = {}
    names = {n for n in (info["name"], info["file_name"]) if len(n) >= 3}
    for folder, patterns in PLACES:
        base = os.path.join(library, folder)
        for pattern in patterns:
            if "{id}" in pattern and len(info["id"]) < 5:
                continue
            for name in (names if "{name}" in pattern else [None]):
                wanted = pattern.replace("{id}", glob.escape(info["id"])).replace("{name}", glob.escape(name or ""))
                for path in glob.glob(os.path.join(glob.escape(base), wanted)):
                    if path not in found:
                        found[path] = folder_size(path) if os.path.isdir(path) and not os.path.islink(path) else _size(path)
    found = list(found.items())
    return found


def _size(path):
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


def running(bundle_id):
    from AppKit import NSRunningApplication
    return list(NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id) or [])


def quit_app(bundle_id):
    for app in running(bundle_id):
        app.terminate()


def trash_app(app_path):
    """O app vai para o Lixo. Se ele for do sistema (instalado pela App Store), o Finder pede a senha."""
    from .cleanup import to_trash
    moved, failed = to_trash([app_path])
    if moved:
        return True
    quoted = app_path.replace("\\", "\\\\").replace('"', '\\"')
    result = subprocess.run(["osascript", "-e", f'tell application "Finder" to delete (POSIX file "{quoted}" as alias)'],
                            capture_output=True, text=True, timeout=300)
    return result.returncode == 0 and not os.path.exists(app_path)
