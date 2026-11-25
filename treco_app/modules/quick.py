"""Edição rápida: cortar, recortar, redimensionar, velocidade, volume, juntar, separar e limpar dados.

Toda ferramenta cria um arquivo novo. O original nunca é alterado.
"""
import io
import os
import re
import subprocess
import tempfile
from collections import namedtuple

from PIL import Image, ImageOps

from ..core.i18n import tr
from ..core.files import unique_path
from ..core.formats import FFMPEG
from ..core.jobs import Job, NothingToGain
from . import documents, media
from .images import ensure_heif
from .transform import IMAGE_SAVE, image_ext, video_ext

Result = namedtuple("Result", "path before after")

X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
AUDIO_ENCODERS = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"], "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"], "aiff": ["-c:a", "pcm_s16be"],
}
SPEED_MIN, SPEED_MAX = 0.25, 4.0


def audio_ext(src):
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    ext = {"aac": "m4a", "aif": "aiff"}.get(ext, ext)
    return ext if ext in AUDIO_ENCODERS else "mp3"


def faststart(dst):
    return [] if dst.lower().endswith(".mkv") else ["-movflags", "+faststart"]


def new_output(src, suffix, ext, folder):
    stem = os.path.splitext(os.path.basename(src))[0]
    return unique_path(folder or os.path.dirname(src), f"{stem} {tr(suffix)}", ext)


def finish(src, dst):
    return Result(dst, os.path.getsize(src), os.path.getsize(dst))


def guarded(dst, work):
    try:
        work()
    except BaseException:
        if os.path.isfile(dst):
            os.remove(dst)
        raise


def video_sound(info):
    return ["-c:a", "copy"] if info.get("audio_codec") in ("aac", "mp3") else ["-c:a", "aac", "-b:a", "192k"]


def require_video(src):
    info = media.probe(src)
    if not info["width"]:
        raise RuntimeError("vídeo não reconhecido")
    return info


def require_audio(src):
    info = media.probe(src)
    if not info["audio"]:
        raise RuntimeError("áudio não reconhecido")
    return info


# ---------------------------------------------------------------- imagens
def is_animated(image, ext):
    return getattr(image, "n_frames", 1) > 1 and ext in ("gif", "webp")


def save_still(image, dst, ext, icc):
    alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    options = {"icc_profile": icc} if icc and ext not in ("gif", "bmp", "tga", "heic", "avif") else {}
    if ext in ("jpg", "webp", "heic", "avif"):
        options["quality"] = 95
    if ext == "jpg":
        image = image.convert("RGB")
        options["subsampling"] = 0
    elif ext == "gif":
        image = image.convert("RGBA" if alpha else "RGB")
    elif image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGBA" if alpha else "RGB")
    data = io.BytesIO()
    image.save(data, IMAGE_SAVE[ext], **options)
    with open(dst, "wb") as f:
        f.write(data.getvalue())


def edit_image(src, dst, ext, change, job):
    ensure_heif()
    with Image.open(src) as source:
        if is_animated(source, ext):
            frames, durations = [], []
            for i in range(source.n_frames):
                job.check()
                source.seek(i)
                frames.append(change(source.convert("RGBA")))
                durations.append(source.info.get("duration", 100))
            options = {"format": "GIF", "disposal": 2} if ext == "gif" else {"format": "WEBP", "quality": 92}
            frames[0].save(dst, save_all=True, append_images=frames[1:], duration=durations, loop=0, **options)
            return
        icc = source.info.get("icc_profile")
        image = ImageOps.exif_transpose(source)
        image.load()
    save_still(change(image), dst, ext, icc)


def image_size(src):
    ensure_heif()
    with Image.open(src) as source:
        image = ImageOps.exif_transpose(source)
        return image.width, image.height


def media_size(src, kind):
    if kind == "image":
        return image_size(src)
    info = require_video(src)
    return info["width"], info["height"]


# ---------------------------------------------------------------- cortar
def trim(src, kind, start, end, exact=True, folder=None, job=None):
    job = job or Job()
    info = media.probe(src)
    total = info["duration"]
    start, end = max(0.0, start), min(end, total) if total else end
    length = end - start
    if length < 0.05:
        raise RuntimeError("trecho curto demais")
    if start <= 0.01 and total and end >= total - 0.01:
        raise NothingToGain("nada a cortar")
    head = ["-ss", f"{start:.3f}", "-i", src, "-t", f"{length:.3f}", "-map_metadata", "0"]
    if kind == "video":
        require_video(src)
        dst = new_output(src, "cortado", video_ext(src), folder)
        head += ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
        exact_args = X264 + (["-c:a", "aac", "-b:a", "192k"] if info["audio"] else [])
    else:
        require_audio(src)
        ext = audio_ext(src)
        dst = new_output(src, "cortado", ext, folder)
        head += ["-map", "0:a:0", "-vn"]
        exact_args = AUDIO_ENCODERS[ext]

    def work():
        if not exact:
            try:
                media.run_with_progress(head + ["-c", "copy", "-avoid_negative_ts", "make_zero"] + faststart(dst) + [dst],
                                        length, job)
                job.progress(1)
                return
            except RuntimeError:
                pass
        media.run_with_progress(head + exact_args + (faststart(dst) if kind == "video" else []) + [dst], length, job)
        job.progress(1)
    guarded(dst, work)
    return finish(src, dst)


# ---------------------------------------------------------------- recortar e redimensionar
def crop(src, kind, x, y, w, h, folder=None, job=None):
    job = job or Job()
    full_w, full_h = media_size(src, kind)
    x, y = max(0, int(x)), max(0, int(y))
    w, h = min(int(w), full_w - x), min(int(h), full_h - y)
    if w < 2 or h < 2:
        raise RuntimeError("recorte pequeno demais")
    if (x, y, w, h) == (0, 0, full_w, full_h):
        raise NothingToGain("nada a recortar")
    if kind == "image":
        ext = image_ext(src)
        dst = new_output(src, "recortado", ext, folder)
        guarded(dst, lambda: edit_image(src, dst, ext, lambda im: im.crop((x, y, x + w, y + h)), job))
        return finish(src, dst)
    w, h, x, y = w // 2 * 2, h // 2 * 2, x // 2 * 2, y // 2 * 2
    return filter_video(src, "recortado", f"crop={w}:{h}:{x}:{y},setsar=1", folder, job)


def filter_video(src, suffix, video_filter, folder, job):
    info = require_video(src)
    dst = new_output(src, suffix, video_ext(src), folder)
    args = ["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "0", "-vf", video_filter] + X264
    args += video_sound(info) if info["audio"] else []
    guarded(dst, lambda: media.run_with_progress(args + faststart(dst) + [dst], info["duration"], job))
    job.progress(1)
    return finish(src, dst)


def target_size(width, height, params):
    if "percent" in params:
        factor = params["percent"] / 100
        return round(width * factor), round(height * factor)
    if "side" in params:  # lado menor, como em 1080p e 720p
        factor = params["side"] / min(width, height)
        return round(width * factor), round(height * factor)
    return int(params["w"]), int(params["h"])


def resize(src, kind, params, folder=None, job=None):
    job = job or Job()
    width, height = media_size(src, kind)
    new_w, new_h = target_size(width, height, params)
    if new_w < 2 or new_h < 2 or max(new_w, new_h) > 16384:
        raise RuntimeError("tamanho inválido")
    if kind == "video":
        new_w, new_h = new_w // 2 * 2, new_h // 2 * 2
    if (new_w, new_h) == (width, height):
        raise NothingToGain("já tem esse tamanho")
    if kind == "image":
        ext = image_ext(src)
        dst = new_output(src, "redimensionado", ext, folder)

        def change(image):
            if image.mode == "P":
                image = image.convert("RGBA")
            return image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        guarded(dst, lambda: edit_image(src, dst, ext, change, job))
        return finish(src, dst)
    return filter_video(src, "redimensionado", f"scale={new_w}:{new_h}:flags=lanczos,setsar=1", folder, job)


# ---------------------------------------------------------------- som e velocidade
def mute(src, folder=None, job=None):
    job = job or Job()
    info = require_video(src)
    if not info["audio"]:
        raise NothingToGain("já não tem som")
    dst = new_output(src, "sem som", video_ext(src), folder)
    head = ["-i", src, "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "0"]

    def work():
        try:
            media.run_with_progress(head + ["-c:v", "copy"] + faststart(dst) + [dst], info["duration"], job)
        except RuntimeError:
            media.run_with_progress(head + X264 + faststart(dst) + [dst], info["duration"], job)
        job.progress(1)
    guarded(dst, work)
    return finish(src, dst)


def atempo_chain(factor):
    parts = []
    while factor > 2.0:
        parts.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        parts.append("atempo=0.5")
        factor /= 0.5
    parts.append(f"atempo={factor:.4f}")
    return ",".join(parts)


def speed(src, kind, factor, folder=None, job=None):
    job = job or Job()
    factor = float(factor)
    if not SPEED_MIN <= factor <= SPEED_MAX:
        raise RuntimeError("velocidade inválida")
    if abs(factor - 1) < 0.001:
        raise NothingToGain("velocidade igual")
    info = media.probe(src)
    length = info["duration"] / factor
    suffix = "acelerado" if factor > 1 else f"lento {round(factor * 100)}%"
    if kind == "video":
        require_video(src)
        dst = new_output(src, suffix, video_ext(src), folder)
        args = ["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "0",
                "-vf", f"setpts=PTS/{factor:.4f}"] + X264
        if info["audio"]:
            args += ["-af", atempo_chain(factor), "-c:a", "aac", "-b:a", "192k"]
        args += faststart(dst)
    else:
        require_audio(src)
        ext = audio_ext(src)
        dst = new_output(src, suffix, ext, folder)
        args = ["-i", src, "-map", "0:a:0", "-vn", "-map_metadata", "0", "-af", atempo_chain(factor)] + AUDIO_ENCODERS[ext]
    guarded(dst, lambda: media.run_with_progress(args + [dst], length, job))
    job.progress(1)
    return finish(src, dst)


def volume(src, kind, folder=None, job=None):
    """Deixa o volume no nível padrão de vídeos e redes sociais."""
    job = job or Job()
    info = media.probe(src)
    if not info["audio"]:
        raise RuntimeError("não tem áudio")
    audio_filter = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"
    if kind == "video":
        require_video(src)
        dst = new_output(src, "volume ajustado", video_ext(src), folder)
        head = ["-i", src, "-map", "0:v:0", "-map", "0:a:0", "-sn", "-dn", "-map_metadata", "0", "-af", audio_filter]
        sound = ["-c:a", "aac", "-b:a", "192k"]

        def work():
            try:
                media.run_with_progress(head + ["-c:v", "copy"] + sound + faststart(dst) + [dst], info["duration"], job)
            except RuntimeError:
                media.run_with_progress(head + X264 + sound + faststart(dst) + [dst], info["duration"], job)
    else:
        ext = audio_ext(src)
        dst = new_output(src, "volume ajustado", ext, folder)
        args = ["-i", src, "-map", "0:a:0", "-vn", "-map_metadata", "0", "-af", audio_filter] + AUDIO_ENCODERS[ext]

        def work():
            media.run_with_progress(args + [dst], info["duration"], job)
    guarded(dst, work)
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- limpar metadados
def strip_jpeg(data):
    """Remove EXIF, XMP e comentários sem tocar na imagem."""
    if data[:2] != b"\xff\xd8":
        raise ValueError
    out = bytearray(b"\xff\xd8")
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise ValueError
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xDA:
            out += data[i:]
            return bytes(out)
        size = int.from_bytes(data[i + 2:i + 4], "big")
        if marker not in (0xE1, 0xED, 0xFE):
            out += data[i:i + 2 + size]
        i += 2 + size
    raise ValueError


def clean(src, kind, folder=None, job=None):
    job = job or Job()
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    if kind == "image":
        out_ext = image_ext(src)
        dst = new_output(src, "limpo", out_ext, folder)

        def work():
            ensure_heif()
            if out_ext == "jpg":
                with Image.open(src) as source:
                    orientation = source.getexif().get(0x0112, 1)
                if orientation == 1:
                    try:
                        with open(src, "rb") as f:
                            data = strip_jpeg(f.read())
                        with open(dst, "wb") as f:
                            f.write(data)
                        return
                    except ValueError:
                        pass
            edit_image(src, dst, out_ext, lambda image: image, job)
        guarded(dst, work)
    elif kind == "pdf":
        dst = new_output(src, "limpo", "pdf", folder)

        def work():
            import pymupdf
            with documents.open_pdf(src) as doc:
                for page in doc:
                    if any(True for _ in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE])):
                        raise RuntimeError("PDF assinado: não alterei")
                doc.set_metadata({})
                doc.del_xml_metadata()
                doc.save(dst, garbage=4, deflate=True)
        guarded(dst, work)
    else:
        info = media.probe(src)
        dst = new_output(src, "limpo", ext, folder)
        maps = ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-dn"] if kind == "video" else ["-map", "0:a", "-vn"]
        args = ["-i", src] + maps + ["-map_metadata", "-1", "-map_chapters", "-1", "-c", "copy", "-fflags", "+bitexact"]
        guarded(dst, lambda: media.run_with_progress(args + [dst], info["duration"], job))
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- juntar e separar
def join(paths, kind, folder=None, job=None):
    job = job or Job()
    if len(paths) < 2:
        raise RuntimeError("escolha 2 ou mais arquivos")
    first = paths[0]
    before = sum(os.path.getsize(p) for p in paths)
    if kind == "pdf":
        dst = new_output(first, "juntado", "pdf", folder)

        def work():
            import pymupdf
            out = pymupdf.open()
            for i, path in enumerate(paths):
                job.check()
                with documents.open_pdf(path) as doc:
                    out.insert_pdf(doc)
                job.progress((i + 1) / len(paths))
            out.save(dst, garbage=3, deflate=True)
            out.close()
    elif kind == "image":
        dst = new_output(first, "juntado", "pdf", folder)

        def work():
            ensure_heif()
            pages = []
            for i, path in enumerate(paths):
                job.check()
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source)
                    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
                        rgba = image.convert("RGBA")
                        page = Image.new("RGB", rgba.size, (255, 255, 255))
                        page.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        page = image.convert("RGB")
                    page.load()
                    pages.append(page)
                job.progress((i + 1) / (len(paths) + 1))
            pages[0].save(dst, "PDF", save_all=True, append_images=pages[1:], resolution=150, quality=92)
    elif kind == "audio":
        ext = audio_ext(first)
        dst = new_output(first, "juntado", ext, folder)
        infos = [require_audio(p) for p in paths]
        total = sum(i["duration"] for i in infos)
        inputs = [a for p in paths for a in ("-i", p)]
        chains = "".join(f"[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}];" for i in range(len(paths)))
        labels = "".join(f"[a{i}]" for i in range(len(paths)))
        graph = f"{chains}{labels}concat=n={len(paths)}:v=0:a=1[out]"

        def work():
            media.run_with_progress(inputs + ["-filter_complex", graph, "-map", "[out]"] + AUDIO_ENCODERS[ext] + [dst], total, job)
    elif kind == "video":
        dst = new_output(first, "juntado", video_ext(first), folder)
        infos = [require_video(p) for p in paths]
        width, height = infos[0]["width"] // 2 * 2, infos[0]["height"] // 2 * 2
        fps = min(60, round(video_fps(first) or 30))
        total = sum(i["duration"] for i in infos)
        any_audio = any(i["audio"] for i in infos)
        inputs = [a for p in paths for a in ("-i", p)]
        chains = []
        pairs = []
        for i, item in enumerate(infos):
            chains.append(f"[{i}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
            pairs.append(f"[v{i}]")
            if any_audio:
                if item["audio"]:
                    chains.append(f"[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
                else:
                    chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={item['duration']:.3f},asetpts=N/SR/TB[a{i}]")
                pairs.append(f"[a{i}]")
        graph = ";".join(chains) + ";" + "".join(pairs) + f"concat=n={len(paths)}:v=1:a={1 if any_audio else 0}"
        graph += "[vout][aout]" if any_audio else "[vout]"
        maps = ["-map", "[vout]"] + (["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"] if any_audio else [])

        def work():
            media.run_with_progress(inputs + ["-filter_complex", graph] + maps + X264 + faststart(dst) + [dst], total, job)
    else:
        raise RuntimeError("tipo não suportado")
    guarded(dst, work)
    job.progress(1)
    return Result(dst, before, os.path.getsize(dst))


def video_fps(src):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", src], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=media.NO_WINDOW)
    match = re.search(r"Video:.*?(\d+(?:\.\d+)?) fps", p.stderr)
    return float(match[1]) if match else None


def pdf_pages(src):
    with documents.open_pdf(src) as doc:
        return doc.page_count


def parse_ranges(text, total):
    """Transforma "1-3, 5" em listas de páginas. Vazio separa todas."""
    text = text.strip()
    if not text:
        return [[page] for page in range(total)]
    groups = []
    for part in re.split(r"[,;]\s*|\s+", text):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise RuntimeError("páginas inválidas")
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= total:
            raise RuntimeError(f"o PDF tem {total} páginas")
        groups.append(list(range(first - 1, last)))
    if not groups:
        raise RuntimeError("páginas inválidas")
    return groups


def split_pdf(src, ranges="", folder=None, job=None):
    job = job or Job()
    import pymupdf
    total = pdf_pages(src)
    groups = parse_ranges(ranges, total)
    if len(groups) == 1 and len(groups[0]) == total:
        raise NothingToGain("nada a separar")
    base = folder or os.path.dirname(src)
    stem = os.path.splitext(os.path.basename(src))[0]
    target, n = os.path.join(base, f"{stem} páginas"), 1
    while os.path.exists(target):
        target, n = os.path.join(base, f"{stem} páginas ({n})"), n + 1
    os.makedirs(target)
    size = 0
    width = len(str(total))
    with documents.open_pdf(src) as doc:
        for i, pages in enumerate(groups):
            job.check()
            out = pymupdf.open()
            for page in pages:
                out.insert_pdf(doc, from_page=page, to_page=page)
            label = f"{pages[0] + 1:0{width}d}" if len(pages) == 1 else f"{pages[0] + 1:0{width}d}-{pages[-1] + 1:0{width}d}"
            path = os.path.join(target, f"página {label}.pdf")
            out.save(path, garbage=3, deflate=True)
            out.close()
            size += os.path.getsize(path)
            job.progress((i + 1) / len(groups))
    return Result(target, os.path.getsize(src), size)


# ---------------------------------------------------------------- prévias para as janelas
def frame_png(src, at, max_w, max_h):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0, at):.3f}", "-i", src, "-frames:v", "1",
           "-vf", f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease", "-f", "image2pipe", "-c:v", "png", "-"]
    result = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=media.NO_WINDOW)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("sem prévia")
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def timeline_strip(src, kind, width, height):
    """Faixa de quadros do vídeo, ou desenho da onda do áudio."""
    duration = media.probe(src)["duration"] or 1
    if kind == "video":
        count = max(4, width // max(16, height))
        rate = max(0.001, count / duration)
        args = ["-i", src, "-an", "-vf", f"fps={rate:.5f},scale={width // count}:{height}:force_original_aspect_ratio=increase,"
                                         f"crop={width // count}:{height},tile={count}x1", "-frames:v", "1"]
    else:
        args = ["-i", src, "-filter_complex", f"[0:a:0]aformat=channel_layouts=mono,showwavespic=s={width}x{height}:colors=white",
                "-frames:v", "1"]
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + args + ["-f", "image2pipe", "-c:v", "png", "-"]
    result = subprocess.run(cmd, capture_output=True, timeout=120, creationflags=media.NO_WINDOW)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("sem faixa")
    return Image.open(io.BytesIO(result.stdout)).convert("RGBA")
