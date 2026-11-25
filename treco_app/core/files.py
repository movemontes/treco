"""Nomes e tamanhos de arquivos."""
import os

from .i18n import tr


HIDDEN_PLACES = (".photoslibrary", "/Library/Containers/", "/Library/Group Containers/", "/private/var/folders/",
                 "/var/folders/", "/Library/Caches/")


def safe_folder(folder):
    """Arquivo arrastado do Fotos (ou de outro app) vem de uma pasta escondida do sistema.
    Salvar lá dentro some com o resultado e pode estragar a biblioteca do Fotos: nesses casos, vai para a Mesa."""
    full = os.path.realpath(folder or ".") + "/"
    if any(place in full for place in HIDDEN_PLACES) or not os.access(folder or ".", os.W_OK):
        desktop = os.path.expanduser("~/Desktop")
        return desktop if os.path.isdir(desktop) else os.path.expanduser("~")
    return folder


def unique_path(folder, stem, ext):
    """Reserva o nome na hora, para conversões simultâneas nunca usarem o mesmo arquivo."""
    folder = safe_folder(folder)
    out = os.path.join(folder, f"{stem}.{ext}")
    n = 1
    while True:
        try:
            os.close(os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return out
        except FileExistsError:
            out = os.path.join(folder, f"{stem} ({n}).{ext}")
            n += 1


def human_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def out_path(src, fmt, folder=None):
    stem = os.path.splitext(os.path.basename(src))[0]
    ext = {"JPG": "jpg", "TIFF": "tiff"}.get(fmt, fmt.lower())
    folder = folder or os.path.dirname(src)
    if os.path.splitext(src)[1].lower().lstrip(".") == ext and folder == os.path.dirname(src):
        stem += " " + tr("convertido")
    return unique_path(folder, stem, ext)


def compressed_path(src, ext, folder=None):
    stem = os.path.splitext(os.path.basename(src))[0] + " " + tr("comprimido")
    return unique_path(folder or os.path.dirname(src), stem, ext)
