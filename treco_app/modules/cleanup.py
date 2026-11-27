"""Limpar a pasta Downloads: lista o que ocupa espaço e manda para o Lixo só o que a pessoa marcar.

Nada é apagado de vez: tudo vai para o Lixo e dá para recuperar.
"""
import os
import time

from ..core.paths import WINDOWS

DAY = 86400


def downloads_folder():
    if WINDOWS:
        from .win_utils import downloads_folder as windows_downloads
        return windows_downloads()
    return os.path.expanduser("~/Downloads")


def folder_size(path, limit=20000):
    """Tamanho de uma pasta (para de contar depois de muitos arquivos, para não travar)."""
    total = count = 0
    for base, dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
            count += 1
            if count > limit:
                return total
    return total


def scan(folder=None):
    """Itens da pasta (arquivos e pastas), com tamanho e há quantos dias chegaram."""
    folder = folder or downloads_folder()
    items, now = [], time.time()
    try:
        names = os.listdir(folder)
    except PermissionError:
        raise RuntimeError("O Mac não deixou ver Downloads. Libere em Privacidade > Arquivos e Pastas")
    for name in names:
        if name.startswith(".") or name in ("Icon\r", "desktop.ini"):
            continue
        path = os.path.join(folder, name)
        try:
            info = os.lstat(path)
        except OSError:
            continue
        is_dir = os.path.isdir(path) and not os.path.islink(path) and not name.endswith(".app")
        size = folder_size(path) if os.path.isdir(path) and not os.path.islink(path) else info.st_size
        when = getattr(info, "st_birthtime", 0) or info.st_mtime  # quando chegou na pasta
        items.append({"path": path, "name": name, "size": size, "folder": is_dir,
                      "days": max(0, int((now - max(when, info.st_mtime if is_dir else 0)) // DAY))})
    return items


def sort(items, how):
    if how == "Mais antigos":
        return sorted(items, key=lambda i: (-i["days"], -i["size"]))
    return sorted(items, key=lambda i: (-i["size"], -i["days"]))


def age_words(days):
    from ..core.i18n import tr
    return tr(_age_words(days))


def _age_words(days):
    if days < 1:
        return "hoje"
    if days < 2:
        return "ontem"
    if days < 31:
        return f"{days} dias"
    if days < 365:
        months = days // 30
        return f"{months} {'mês' if months == 1 else 'meses'}"
    years = days // 365
    return f"{years} {'ano' if years == 1 else 'anos'}"


def to_trash(paths):
    """Manda para o Lixo do Mac (ou a Lixeira do Windows). Devolve quantos foram e o que não deu."""
    if WINDOWS:
        from .win_utils import to_trash as windows_trash
        return windows_trash(paths)
    from Foundation import NSFileManager, NSURL
    manager = NSFileManager.defaultManager()
    moved, failed = 0, []
    for path in paths:
        ok, _, error = manager.trashItemAtURL_resultingItemURL_error_(NSURL.fileURLWithPath_(path), None, None)
        if ok:
            moved += 1
        else:
            failed.append(os.path.basename(path))
    return moved, failed
