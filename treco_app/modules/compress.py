"""Compressão de imagens, áudio, vídeo e PDF.

O original nunca é alterado. Se o resultado não ficar menor, nenhuma cópia é criada.
"""
import io
import os
import tempfile
import threading
from collections import namedtuple

from PIL import Image, ImageOps

from ..core.files import compressed_path, human_size
from ..core.jobs import Job, NothingToGain
from . import documents, media
from .images import ensure_heif

Result = namedtuple("Result", "path before after")

IMAGE_LEVELS = {"leve": (84, None), "medio": (70, 3840), "forte": (52, 1920)}
VIDEO_LEVELS = {"leve": (24, None, 128), "medio": (28, 1920, 112), "forte": (32, 1280, 80)}
AUDIO_LEVELS = {"leve": 160, "medio": 112, "forte": 72}
PDF_LEVELS = {"leve": (220, 80), "medio": (150, 65), "forte": (96, 45)}
PDF_TARGET_STEPS = [(220, 80), (150, 70), (120, 60), (96, 50), (72, 40), (60, 30)]
AUDIO_CODECS = {"mp3": "libmp3lame", "m4a": "aac", "ogg": "libvorbis", "opus": "libopus"}
AUDIO_MIN_KBPS = {"mp3": 32, "m4a": 24, "ogg": 48, "opus": 12}
_video_slot = threading.BoundedSemaphore(1)  # um vídeo por vez para não travar o computador


def compress(src, kind, mode, folder=None, job=None):
    job = job or Job()
    before = os.path.getsize(src)
    target = mode if isinstance(mode, int) else None
    if target is None and mode not in IMAGE_LEVELS:
        raise ValueError("nível inválido")
    if target and before <= target:
        raise NothingToGain("já cabe")
    ext = output_ext(src, kind)
    dst = compressed_path(src, ext, folder)
    try:
        if kind == "image":
            compress_image(src, dst, ext, mode, target, job)
        elif kind == "video":
            with _video_slot:
                job.check()
                compress_video(src, dst, mode, target, job)
        elif kind == "audio":
            compress_audio(src, dst, ext, mode, target, job)
        elif kind == "pdf":
            compress_pdf(src, dst, mode, target, job)
        else:
            raise RuntimeError("tipo não suportado")
        after = os.path.getsize(dst)
        if after >= before:
            raise NothingToGain("já otimizado")
        if target and after > target:
            raise RuntimeError(f"não coube em {human_size(target)}")
        return Result(dst, before, after)
    except BaseException:
        if os.path.isfile(dst):
            os.remove(dst)
        raise


def output_ext(src, kind):
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    if kind == "video":
        return "mp4"
    if kind == "pdf":
        return "pdf"
    if kind == "audio":
        return {"aac": "m4a"}.get(ext, ext if ext in AUDIO_CODECS else "mp3")
    if ext in ("jpg", "jpeg", "jfif"):
        return "jpg"
    if ext in ("heic", "heif"):
        return "heic"
    if ext in ("tif", "tiff"):
        return "tiff"
    if ext in ("png", "webp", "avif", "gif"):
        return ext
    if ext == "ico":
        raise NothingToGain("ícone já é pequeno")
    ensure_heif()
    with Image.open(src) as img:  # BMP, TGA e PSD não têm compressão útil
        return "png" if has_alpha(img) else "jpg"


# ---------------------------------------------------------------- imagens
def has_alpha(img):
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def palette(img, colors):
    if has_alpha(img):
        return img.convert("RGBA").quantize(colors, method=Image.Quantize.FASTOCTREE,
                                             dither=Image.Dither.FLOYDSTEINBERG)
    return img.convert("RGB").quantize(colors, method=Image.Quantize.MEDIANCUT,
                                       dither=Image.Dither.FLOYDSTEINBERG)


def colors_for(quality):
    return max(16, min(256, int(16 + (quality - 35) / (88 - 35) * 240)))


def encode(img, ext, quality, icc):
    """Gera os bytes finais. quality=None em PNG mantém todas as cores."""
    out = io.BytesIO()
    extra = {"icc_profile": icc} if icc else {}
    alpha = has_alpha(img)
    if ext == "jpg":
        rgb = img
        if alpha:
            rgba = img.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, (255, 255, 255))
            rgb.paste(rgba, mask=rgba.getchannel("A"))
        rgb.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True, **extra)
    elif ext == "png":
        final = img.convert("RGBA" if alpha else "RGB") if quality is None else palette(img, colors_for(quality))
        final.save(out, "PNG", optimize=True, compress_level=9, **extra)
    elif ext == "webp":
        img.convert("RGBA" if alpha else "RGB").save(out, "WEBP", quality=quality, method=5, **extra)
    elif ext == "heic":
        img.convert("RGBA" if alpha else "RGB").save(out, "HEIF", quality=max(20, quality - 12))
    elif ext == "avif":
        img.convert("RGBA" if alpha else "RGB").save(out, "AVIF", quality=max(20, quality - 12))
    elif ext == "gif":
        palette(img, colors_for(quality)).save(out, "GIF", optimize=True)
    elif ext == "tiff":
        if alpha or quality >= 84:
            img.convert("RGBA" if alpha else "RGB").save(out, "TIFF", compression="tiff_adobe_deflate", **extra)
        else:
            img.convert("RGB").save(out, "TIFF", compression="jpeg", quality=quality, **extra)
    return out.getvalue()


def limit_side(img, side):
    if side and max(img.size) > side:
        scale = side / max(img.size)
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        return resized(img, size)
    return img


def resized(img, size):
    if img.mode == "P":
        img = img.convert("RGBA" if has_alpha(img) else "RGB")
    return img.resize(size, Image.Resampling.LANCZOS)


def fit_target(img, ext, target, icc, job):
    """Maior qualidade e maior tamanho de imagem que ainda cabem no limite."""
    for scale in (1, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2, 0.12):
        job.check()
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        candidate = img if scale == 1 else resized(img, size)
        low, high, best = 40, 88, None
        while low <= high:
            job.check()
            quality = (low + high) // 2
            data = encode(candidate, ext, quality, icc)
            if len(data) <= target:
                best, low = data, quality + 1
            else:
                high = quality - 1
        if best is not None:
            return best
    raise RuntimeError(f"não coube em {human_size(target)}")


def compress_image(src, dst, ext, mode, target, job):
    ensure_heif()
    with Image.open(src) as source:
        if getattr(source, "n_frames", 1) > 1 and ext in ("gif", "webp"):
            compress_animation(source, dst, ext, mode, target, job)
            return
        icc = source.info.get("icc_profile")
        img = ImageOps.exif_transpose(source)  # aplica a rotação e descarta EXIF/localização
        img.load()
    if target:
        data = fit_target(img, ext, target, icc, job)
    else:
        quality, side = IMAGE_LEVELS[mode]
        img = limit_side(img, side)
        if ext == "png":
            quality = {"leve": None, "medio": 88, "forte": 62}[mode]
        data = encode(img, ext, quality, icc)
    with open(dst, "wb") as f:
        f.write(data)


def compress_animation(source, dst, ext, mode, target, job):
    frames, durations = [], []
    for i in range(source.n_frames):
        job.check()
        source.seek(i)
        frames.append(source.convert("RGBA"))
        durations.append(source.info.get("duration", 100))

    def build(scale, quality):
        size = (max(1, round(frames[0].width * scale)), max(1, round(frames[0].height * scale)))
        out = []
        for frame in frames:
            job.check()
            item = frame if scale == 1 else frame.resize(size, Image.Resampling.LANCZOS)
            out.append(item.quantize(colors_for(quality), method=Image.Quantize.FASTOCTREE) if ext == "gif" else item)
        data = io.BytesIO()
        options = {"format": "GIF", "optimize": True, "disposal": 2} if ext == "gif" else {
            "format": "WEBP", "quality": quality, "method": 4}
        out[0].save(data, save_all=True, append_images=out[1:], duration=durations, loop=0, **options)
        return data.getvalue()

    if target:
        result = None
        for scale in (1, 0.8, 0.65, 0.5, 0.35, 0.25):
            for quality in (75, 55, 40):
                data = build(scale, quality)
                if len(data) <= target:
                    result = data
                    break
            if result:
                break
        if result is None:
            raise RuntimeError(f"não coube em {human_size(target)}")
    else:
        scale = {"leve": 1, "medio": 0.85, "forte": 0.65}[mode]
        result = build(scale, IMAGE_LEVELS[mode][0])
    with open(dst, "wb") as f:
        f.write(result)


# ---------------------------------------------------------------- vídeo
def scale_filter(side):
    if not side:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    return (f"scale=w='if(gte(iw,ih),trunc(min(iw,{side})/2)*2,-2)':"
            f"h='if(gte(iw,ih),-2,trunc(min(ih,{side})/2)*2)'")


def video_common(side, fps_cap=None):
    args = ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "0", "-vf", scale_filter(side),
            "-c:v", "libx264", "-preset", "faster", "-pix_fmt", "yuv420p"]
    if fps_cap:
        args += ["-fpsmax", str(fps_cap)]
    return args


def target_side(video_kbps):
    for minimum, side in ((2500, 1920), (1200, 1280), (600, 854), (300, 640)):
        if video_kbps >= minimum:
            return side
    return 426


def compress_video(src, dst, mode, target, job):
    info = media.probe(src)
    if not info["width"]:
        raise RuntimeError("vídeo não reconhecido")
    duration = info["duration"]
    if not target:
        crf, side, audio = VIDEO_LEVELS[mode]
        args = ["-i", src] + video_common(side, 30 if mode == "forte" else None) + ["-crf", str(crf)]
        args += ["-c:a", "aac", "-b:a", f"{audio}k"] if info["audio"] else []
        media.run_with_progress(args + ["-movflags", "+faststart", dst], duration, job)
        job.progress(1)
        return
    if duration <= 0:
        raise RuntimeError("duração do vídeo desconhecida")
    total = target * 8 / 1000 / duration * 0.95
    audio = 0
    if info["audio"]:
        audio = 112 if total >= 900 else 80 if total >= 350 else 48 if total >= 140 else 32
    margin = 1.0
    with tempfile.TemporaryDirectory(prefix="treco_", ignore_cleanup_errors=True) as tmp:
        log = os.path.join(tmp, "pass")
        for attempt in range(3):
            video = int((total - audio) * margin)
            if video < 45:
                raise RuntimeError(f"não coube em {human_size(target)}")
            base = video_common(target_side(video), 30 if video < 1200 else None) + ["-b:v", f"{video}k"]
            span = 1 / 3
            start = attempt * span
            media.run_with_progress(["-i", src] + base + ["-pass", "1", "-passlogfile", log, "-an", "-f", "null", os.devnull],
                                    duration, job, start, span * 0.4)
            sound = ["-c:a", "aac", "-b:a", f"{audio}k"] if audio else []
            media.run_with_progress(["-i", src] + base + ["-pass", "2", "-passlogfile", log] + sound +
                                    ["-movflags", "+faststart", dst], duration, job, start + span * 0.4, span * 0.6)
            if os.path.getsize(dst) <= target:
                job.progress(1)
                return
            margin *= 0.86
    raise RuntimeError(f"não coube em {human_size(target)}")


# ---------------------------------------------------------------- áudio
def compress_audio(src, dst, ext, mode, target, job):
    info = media.probe(src)
    if not info["audio"]:
        raise RuntimeError("áudio não reconhecido")
    duration = info["duration"]
    if target:
        if duration <= 0:
            raise RuntimeError("duração do áudio desconhecida")
        kbps = target * 8 / 1000 / duration * 0.96
    else:
        kbps = AUDIO_LEVELS[mode]
    for _ in range(3):
        rate = int(min(kbps, 320))
        if rate < AUDIO_MIN_KBPS[ext]:
            raise RuntimeError(f"não coube em {human_size(target)}")
        args = ["-i", src, "-map", "0:a:0", "-vn", "-map_metadata", "0", "-c:a", AUDIO_CODECS[ext], "-b:a", f"{rate}k"]
        if ext == "ogg":
            args += ["-f", "ogg"]
        media.run_with_progress(args + [dst], duration, job)
        if not target or os.path.getsize(dst) <= target:
            job.progress(1)
            return
        kbps *= 0.9
    raise RuntimeError(f"não coube em {human_size(target)}")


# ---------------------------------------------------------------- PDF
def write_pdf(src, dst, dpi, quality):
    doc = documents.open_pdf(src)
    try:
        doc.rewrite_images(dpi_threshold=int(dpi * 1.15), dpi_target=dpi, quality=quality)
        try:
            doc.subset_fonts()
        except Exception:
            pass
        doc.save(dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1)
    finally:
        doc.close()


def compress_pdf(src, dst, mode, target, job):
    import pymupdf
    with documents.open_pdf(src) as doc:
        for page in doc:
            if any(True for _ in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE])):
                raise RuntimeError("PDF assinado: não comprimi")  # alterar invalidaria a assinatura
    temp = dst + ".tmp"
    try:
        steps = PDF_TARGET_STEPS if target else [PDF_LEVELS[mode]]
        for i, (dpi, quality) in enumerate(steps):
            job.check()
            write_pdf(src, temp, dpi, quality)
            job.progress((i + 1) / len(steps))
            if not target or os.path.getsize(temp) <= target:
                os.replace(temp, dst)
                return
        raise RuntimeError(f"não coube em {human_size(target)}")
    finally:
        if os.path.exists(temp):
            os.remove(temp)
