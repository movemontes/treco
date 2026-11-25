"""Ferramentas do grupo "Mais": transcrever, tirar fundo, ler texto, borrar rostos,
senha em PDF, marca d'água e renomear em lote.

Todas, menos renomear, criam um arquivo novo. O original nunca é alterado.
"""
import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..core.jobs import Job
from . import captions, media
from .quick import Result, edit_image, finish, guarded, new_output
from .transform import image_ext, video_ext


# ---------------------------------------------------------------- transcrever
def srt_time(value):
    ms = int(round(max(0, value) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def as_srt(segments):
    blocks = [f"{i}\n{srt_time(s.start)} --> {srt_time(s.end)}\n{s.text.strip()}"
              for i, s in enumerate(segments, 1)]
    return "\n\n".join(blocks) + "\n"


def as_text(segments):
    """Texto corrido, quebrando parágrafo quando a fala dá uma pausa longa."""
    paragraphs, current, last_end = [], [], None
    for s in segments:
        if current and last_end is not None and s.start - last_end > 1.5:
            paragraphs.append(" ".join(current))
            current = []
        current.append(s.text.strip())
        last_end = s.end
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(p for p in paragraphs if p) + "\n"


def transcribe(src, fmt="txt", language="auto", folder=None, job=None):
    job = job or Job()
    segments = captions.transcribe(src, language, job)
    if not segments:
        raise RuntimeError("Não ouvi fala nesse arquivo")
    dst = new_output(src, "transcrição", fmt, folder)
    text = as_srt(segments) if fmt == "srt" else as_text(segments)
    guarded(dst, lambda: open(dst, "w", encoding="utf-8").write(text))
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- tirar o fundo
def remove_background(src, folder=None, job=None):
    from . import vision_mac
    job = job or Job()
    img = vision_mac.open_image(src)
    job.progress(.2)
    mask = vision_mac.subject_mask(img)
    if mask is None:
        raise RuntimeError("Não achei um objeto em destaque")
    job.check()
    out = img.convert("RGBA")
    if "A" in img.getbands():
        from PIL import ImageChops
        mask = ImageChops.multiply(mask, img.getchannel("A"))
    out.putalpha(mask)
    box = mask.point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:  # corta as sobras transparentes, deixando uma margem pequena
        pad = max(4, int(max(out.size) * .01))
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(out.width, box[2] + pad), min(out.height, box[3] + pad))
        out = out.crop(box)
    dst = new_output(src, "sem fundo", "png", folder)
    guarded(dst, lambda: out.save(dst, "PNG", optimize=True))
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- ler texto
def extract_text(src, kind, folder=None, job=None):
    from . import vision_mac
    job = job or Job()
    if kind == "image":
        text = vision_mac.read_text(vision_mac.open_image(src))
    else:
        from .documents import open_pdf
        parts = []
        with open_pdf(src) as doc:
            total = len(doc)
            for number, page in enumerate(doc, 1):
                job.check()
                found = page.get_text().strip()
                if len(found) < 20:  # página escaneada: lê a imagem
                    pix = page.get_pixmap(dpi=220)
                    found = vision_mac.read_text(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
                if found:
                    parts.append(f"— Página {number} —\n{found}" if total > 1 else found)
                job.progress(number / total * .95)
        text = "\n\n".join(parts)
    if not text.strip():
        raise RuntimeError("Não achei texto")
    dst = new_output(src, "texto", "txt", folder)
    guarded(dst, lambda: open(dst, "w", encoding="utf-8").write(text.strip() + "\n"))
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- borrar rostos
def hide_faces(src, folder=None, job=None):
    from . import vision_mac
    job = job or Job()
    found = vision_mac.faces(vision_mac.open_image(src))
    if not found:
        raise RuntimeError("Não achei rostos")
    job.progress(.4)

    def change(image):
        image = image.copy()
        for left, top, right, bottom in found:
            pad_x, pad_y = (right - left) * .18, (bottom - top) * .25
            box = (int(max(0, left - pad_x)), int(max(0, top - pad_y)),
                   int(min(image.width, right + pad_x)), int(min(image.height, bottom + pad_y * .6)))
            w, h = box[2] - box[0], box[3] - box[1]
            if w < 2 or h < 2:
                continue
            region = image.crop(box)
            blocks = max(1, int(max(w, h) / 12))  # pixelado, com uns 12 quadrados no rosto
            small = region.resize((max(1, w // blocks), max(1, h // blocks)), Image.BILINEAR)
            region = small.resize((w, h), Image.NEAREST).filter(ImageFilter.GaussianBlur(blocks * .35))
            oval = Image.new("L", (w, h), 0)
            ImageDraw.Draw(oval).ellipse((0, 0, w - 1, h - 1), fill=255)
            image.paste(region, box[:2], oval.filter(ImageFilter.GaussianBlur(max(1, w // 30))))
        return image

    ext = image_ext(src)
    dst = new_output(src, "sem rostos", ext, folder)
    guarded(dst, lambda: edit_image(src, dst, ext, change, job))
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- senha em PDF
def pdf_has_password(src):
    import pymupdf
    with pymupdf.open(src) as doc:
        return bool(doc.needs_pass)


def pdf_lock(src, password, folder=None, job=None):
    import pymupdf
    job = job or Job()
    if len(password) < 4:
        raise RuntimeError("Senha curta demais")
    with pymupdf.open(src) as doc:
        if doc.needs_pass:
            raise RuntimeError("Esse PDF já tem senha")
        dst = new_output(src, "com senha", "pdf", folder)
        permissions = (pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY | pymupdf.PDF_PERM_ANNOTATE
                       | pymupdf.PDF_PERM_PRINT_HQ | pymupdf.PDF_PERM_ACCESSIBILITY)
        guarded(dst, lambda: doc.save(dst, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password,
                                      owner_pw=password, permissions=permissions, garbage=3, deflate=True))
    job.progress(1)
    return finish(src, dst)


def pdf_unlock(src, password, folder=None, job=None):
    import pymupdf
    job = job or Job()
    with pymupdf.open(src) as doc:
        if not doc.needs_pass and not doc.is_encrypted:
            raise RuntimeError("Esse PDF não tem senha")
        if doc.needs_pass and not doc.authenticate(password):
            raise RuntimeError("Senha errada")
        dst = new_output(src, "sem senha", "pdf", folder)
        guarded(dst, lambda: doc.save(dst, encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=3, deflate=True))
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- marca d'água
POSITIONS = ("Canto", "Centro", "Repetir")


def _font(pixels):
    from ..ui.pixel import FONT_FILE
    try:
        font = ImageFont.truetype(FONT_FILE, max(8, pixels))
        font.set_variation_by_axes([800, 125])
        return font
    except OSError:
        return ImageFont.load_default(max(8, pixels))


def watermark_layer(size, text, position, opacity=.55):
    """Camada transparente com o texto, do tamanho da imagem ou do vídeo."""
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    short = min(width, height)
    alpha = int(255 * opacity)
    if position == "Repetir":
        font = _font(int(short * .055))
        tile_w = int(ImageDraw.Draw(layer).textlength(text, font=font)) + short // 6
        tile = Image.new("RGBA", (tile_w, int(short * .055 * 3.2)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)
        draw.text((2, 2), text, font=font, fill=(0, 0, 0, alpha // 2))
        draw.text((0, 0), text, font=font, fill=(255, 255, 255, alpha))
        diagonal = int((width ** 2 + height ** 2) ** .5)
        sheet = Image.new("RGBA", (diagonal, diagonal), (0, 0, 0, 0))
        for row, y in enumerate(range(0, diagonal, tile.height)):
            for x in range(-(row % 2) * tile_w // 2, diagonal, tile_w):
                sheet.paste(tile, (x, y), tile)
        sheet = sheet.rotate(30, resample=Image.BICUBIC)
        layer.alpha_composite(sheet.crop(((diagonal - width) // 2, (diagonal - height) // 2,
                                          (diagonal - width) // 2 + width, (diagonal - height) // 2 + height)))
        return layer
    font = _font(int(short * (.045 if position == "Canto" else .09)))
    draw = ImageDraw.Draw(layer)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    tw, th = right - left, bottom - top
    if position == "Canto":
        margin = int(short * .035)
        x, y = width - tw - margin - left, height - th - margin - top
    else:
        x, y = (width - tw) // 2 - left, (height - th) // 2 - top
    shadow = max(1, int(short * .004))
    draw.text((x + shadow, y + shadow), text, font=font, fill=(0, 0, 0, int(alpha * .6)))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha))
    return layer


def watermark(src, kind, text, position="Canto", folder=None, job=None):
    job = job or Job()
    text = " ".join((text or "").split())
    if not text:
        raise RuntimeError("Escreva o texto da marca")
    if kind == "image":
        def change(image):
            base = image.convert("RGBA")
            base.alpha_composite(watermark_layer(base.size, text, position))
            return base if "A" in image.getbands() else base.convert("RGB")
        ext = image_ext(src)
        dst = new_output(src, "com marca", ext, folder)
        guarded(dst, lambda: edit_image(src, dst, ext, change, job))
    elif kind == "video":
        import tempfile
        info = media.probe(src)
        if not info["width"]:
            raise RuntimeError("Não achei a imagem do vídeo")
        ext = video_ext(src)
        dst = new_output(src, "com marca", ext, folder)
        with tempfile.TemporaryDirectory(prefix="treco_marca_") as tmp:
            mark = os.path.join(tmp, "marca.png")
            watermark_layer((info["width"], info["height"]), text, position).save(mark)
            sound = ["-c:a", "copy"] if info["audio"] else []
            args = ["-i", src, "-i", mark, "-filter_complex", "[0:v:0][1:v]overlay=0:0:format=auto,format=yuv420p[v]",
                    "-map", "[v]", "-map", "0:a?"] + media.H264[:8] + sound
            args += ["-movflags", "+faststart"] if ext != "mkv" else []
            guarded(dst, lambda: media.run_with_progress(args + [dst], info["duration"], job))
    else:
        raise RuntimeError("Marca d'água é para imagem e vídeo")
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- renomear em lote
BAD_NAME = re.compile(r'[\x00-\x1f/\\:*?"<>|]')


def rename_plan(paths, base, start=1):
    """Lista de (caminho atual, caminho novo). Não toca em nada."""
    base = " ".join(BAD_NAME.sub(" ", base or "").split()).strip(" .")
    if not base:
        raise RuntimeError("Escreva um nome")
    digits = max(2, len(str(start + len(paths) - 1)))
    plan, taken = [], set()
    for i, path in enumerate(paths):
        ext = os.path.splitext(path)[1]
        folder = os.path.dirname(path)
        name = f"{base} {start + i:0{digits}d}{ext}" if len(paths) > 1 else f"{base}{ext}"
        target = os.path.join(folder, name)
        plan.append((path, target))
        taken.add(os.path.normcase(target))
    sources = {os.path.normcase(p) for p in paths}
    for _, target in plan:
        if os.path.exists(target) and os.path.normcase(target) not in sources:
            raise RuntimeError(f"Já existe {os.path.basename(target)}")
    return plan


def rename_apply(plan):
    """Renomeia em duas etapas (nome temporário e depois o final), para trocas entre os
    próprios arquivos não se atropelarem. Devolve a lista do que foi feito."""
    moves = [(src, dst) for src, dst in plan if src != dst]
    temps = []
    for i, (src, dst) in enumerate(moves):
        temp = os.path.join(os.path.dirname(src), f".treco_renomeando_{os.getpid()}_{i}{os.path.splitext(src)[1]}")
        os.rename(src, temp)
        temps.append((src, temp, dst))
    done = []
    try:
        for src, temp, dst in temps:
            if os.path.exists(dst):
                raise RuntimeError(f"Já existe {os.path.basename(dst)}")
            os.rename(temp, dst)
            done.append((src, dst))
    except BaseException:
        for src, dst in done:  # desfaz tudo, para não ficar metade renomeada
            os.rename(dst, src)
        for src, temp, _ in temps:
            if os.path.exists(temp):
                os.rename(temp, src)
        raise
    return done
