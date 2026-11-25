"""Edição rápida: girar e espelhar imagens e vídeos. O original nunca é alterado."""
import io
import os
from collections import namedtuple

from PIL import Image, ImageOps

from ..core.i18n import tr
from ..core.files import unique_path
from ..core.jobs import Job
from . import media
from .images import ensure_heif

Result = namedtuple("Result", "path before after")

OPERATIONS = {
    "direita": ("girado", Image.Transpose.ROTATE_270, "transpose=1"),
    "esquerda": ("girado", Image.Transpose.ROTATE_90, "transpose=2"),
    "180": ("girado", Image.Transpose.ROTATE_180, "hflip,vflip"),
    "espelhar": ("espelhado", Image.Transpose.FLIP_LEFT_RIGHT, "hflip"),
    "inverter": ("invertido", Image.Transpose.FLIP_TOP_BOTTOM, "vflip"),
}
IMAGE_SAVE = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "heic": "HEIF", "avif": "AVIF", "bmp": "BMP",
              "tiff": "TIFF", "gif": "GIF", "tga": "TGA"}


def transform(src, kind, operation, folder=None, job=None):
    job = job or Job()
    suffix, image_op, video_filter = OPERATIONS[operation]
    stem = f"{os.path.splitext(os.path.basename(src))[0]} {tr(suffix)}"
    target_folder = folder or os.path.dirname(src)
    ext = image_ext(src) if kind == "image" else video_ext(src)
    dst = unique_path(target_folder, stem, ext)
    try:
        if kind == "image":
            transform_image(src, dst, ext, image_op, job)
        elif kind == "video":
            transform_video(src, dst, video_filter, job)
        else:
            raise RuntimeError("só imagem e vídeo")
        return Result(dst, os.path.getsize(src), os.path.getsize(dst))
    except BaseException:
        if os.path.isfile(dst):
            os.remove(dst)
        raise


def image_ext(src):
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    ext = {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff", "heif": "heic"}.get(ext, ext)
    return ext if ext in IMAGE_SAVE else "png"  # ICO e PSD não são bons formatos de saída


def video_ext(src):
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    return ext if ext in ("mp4", "mov", "mkv") else "mp4"


def transform_image(src, dst, ext, operation, job):
    ensure_heif()
    with Image.open(src) as source:
        if getattr(source, "n_frames", 1) > 1 and ext in ("gif", "webp"):
            save_animation(source, dst, ext, operation, job)
            return
        icc = source.info.get("icc_profile")
        exif = source.getexif()
        img = ImageOps.exif_transpose(source)
        img.load()
    result = img.transpose(operation)
    alpha = result.mode in ("RGBA", "LA", "PA") or (result.mode == "P" and "transparency" in result.info)
    options = {"icc_profile": icc} if icc and ext not in ("gif", "bmp", "tga", "heic", "avif") else {}
    if ext in ("jpg", "webp", "heic", "avif"):
        options["quality"] = 95
    if ext == "jpg":
        result = result.convert("RGB")
        options["subsampling"] = 0
    elif ext in ("bmp", "tga") and result.mode not in ("RGB", "RGBA", "L", "P"):
        result = result.convert("RGBA" if alpha else "RGB")
    elif ext in ("webp", "heic", "avif", "png", "tiff") and result.mode not in ("RGB", "RGBA", "L", "I;16"):
        result = result.convert("RGBA" if alpha else "RGB")
    if exif and ext in ("jpg", "webp", "png", "tiff"):
        exif[0x0112] = 1  # a rotação agora está nos pixels
        options["exif"] = exif.tobytes()
    data = io.BytesIO()
    result.save(data, IMAGE_SAVE[ext], **options)
    job.check()
    with open(dst, "wb") as f:
        f.write(data.getvalue())


def save_animation(source, dst, ext, operation, job):
    frames, durations = [], []
    for i in range(source.n_frames):
        job.check()
        source.seek(i)
        frames.append(source.convert("RGBA").transpose(operation))
        durations.append(source.info.get("duration", 100))
    options = {"format": "GIF", "disposal": 2} if ext == "gif" else {"format": "WEBP", "quality": 92}
    frames[0].save(dst, save_all=True, append_images=frames[1:], duration=durations, loop=0, **options)


def transform_video(src, dst, video_filter, job):
    info = media.probe(src)
    if not info["width"]:
        raise RuntimeError("vídeo não reconhecido")
    faststart = [] if dst.lower().endswith(".mkv") else ["-movflags", "+faststart"]
    base = ["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "0",
            "-vf", f"{video_filter},scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    audio = ["-c:a", "copy"] if info.get("audio_codec") in ("aac", "mp3") else ["-c:a", "aac", "-b:a", "192k"]
    media.run_with_progress(base + audio + faststart + [dst], info["duration"], job)
    job.progress(1)
