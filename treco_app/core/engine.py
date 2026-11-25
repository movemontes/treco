"""Entrega cada arquivo ao módulo certo, carregando o módulo só quando ele é usado."""
import os

from .files import out_path


def convert_file(src, kind, fmt, quality=90, folder=None, job=None):
    dst = out_path(src, fmt, folder)
    try:
        if kind == "image":
            from ..modules import images
            images.convert(src, dst, fmt, quality)
        elif kind in ("audio", "video"):
            from ..modules import media
            media.convert(src, dst, fmt, kind == "video", job)
        elif kind == "sub":  # legenda SRT <-> VTT
            from ..modules import media
            media.run_ffmpeg(["-i", src, dst])
        else:
            from ..modules import documents
            return documents.convert(src, dst, kind, fmt)
        return dst
    except BaseException:
        if os.path.isfile(dst):  # não deixa arquivo vazio para trás
            os.remove(dst)
        raise


def transform_file(src, kind, operation, folder=None, job=None):
    from ..modules import transform
    return transform.transform(src, kind, operation, folder, job)


def compress_file(src, kind, mode, folder=None, job=None):
    from ..modules import compress
    return compress.compress(src, kind, mode, folder, job)
