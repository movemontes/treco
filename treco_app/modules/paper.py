"""Papel: QR Code, fotos num PDF e foto de documento virando PDF "escaneado".

Tudo cria arquivos novos. O original nunca é alterado.
"""
import io
import os
import re

from PIL import Image, ImageFilter, ImageOps

from ..core.files import unique_path
from ..core.jobs import Job
from .images import ensure_heif
from .quick import Result, guarded, new_output

A4 = (595.28, 841.89)  # pontos (1/72 de polegada)
MARGIN = 28  # 1 cm
PAGE_DPI = 200  # resolução das fotos dentro do PDF: nítido para imprimir, sem ficar enorme
MAX_SIDE = 3000


# ---------------------------------------------------------------- QR Code
def qr_image(text, size=None, border=2):
    """QR Code em preto e branco, com quadradinhos exatos (sem borrar).
    size: lado aproximado em pixels; None = 1 pixel por quadradinho."""
    import segno
    matrix = segno.make(text, error="m").matrix
    modules = len(matrix) + border * 2
    image = Image.new("L", (modules, modules), 255)
    pixels = image.load()
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            if value:
                pixels[x + border, y + border] = 0
    scale = max(1, (size or modules) // modules)
    return image.resize((modules * scale, modules * scale), Image.Resampling.NEAREST)


def qr_name(text):
    """Nome do arquivo a partir do texto: o site, ou o começo do texto."""
    site = re.match(r"(?:https?://)?(?:www\.)?([^/\s?#]+)", text.strip())
    base = site[1] if site and "." in site[1] and " " not in text.strip() else text.strip()[:30]
    base = " ".join(re.sub(r'[\\/:*?"<>|]+', " ", base).split()).strip(" .") or "texto"
    return f"QR Code {base}"


QR_SIZES = {"Pequeno": 400, "Médio": 1000, "Grande": 2000}


def save_qr(text, folder, size="Médio"):
    if not text.strip():
        raise RuntimeError("Escreva um texto ou link")
    image = qr_image(text, QR_SIZES.get(size, 1000))
    dst = unique_path(folder, qr_name(text), "png")
    guarded(dst, lambda: image.save(dst, "PNG", optimize=True))
    return dst


# ---------------------------------------------------------------- fotos num PDF
def _open(path):
    ensure_heif()
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return image.convert("RGB" if image.mode not in ("L", "1") else image.mode)


def _shrink(image, limit=MAX_SIDE):
    if max(image.size) > limit:
        image = image.copy()
        image.thumbnail((limit, limit), Image.Resampling.LANCZOS)
    return image


def _stream(image, black_white=False):
    buffer = io.BytesIO()
    if black_white:
        sharp = image.convert("L").point(lambda v: 255 if v > 127 else 0)
        sharp.convert("1", dither=Image.Dither.NONE).save(buffer, "PNG", optimize=True)
    else:
        image.save(buffer, "JPEG", quality=85, optimize=True)
    return buffer.getvalue()


def _place(doc, image, page_mode, margin, black_white=False):
    """Põe uma imagem numa página nova: A4 em pé ou deitado, ou do tamanho da própria foto."""
    import pymupdf
    width, height = image.size
    if page_mode == "A4":
        pw, ph = A4 if height >= width else A4[::-1]
        pad = MARGIN if margin else 0
        room_w, room_h = pw - 2 * pad, ph - 2 * pad
        fit = min(room_w / width, room_h / height)
        w, h = width * fit, height * fit
        x, y = (pw - w) / 2, (ph - h) / 2
        dpi = width / (w / 72)
        if dpi > PAGE_DPI * 1.5:  # foto grande demais para a página: diminui sem perder nitidez
            image = image.resize((max(1, round(w / 72 * PAGE_DPI)), max(1, round(h / 72 * PAGE_DPI))), Image.Resampling.LANCZOS)
    else:
        image = _shrink(image)
        width, height = image.size
        w, h = width / PAGE_DPI * 72, height / PAGE_DPI * 72
        pad = MARGIN if margin else 0
        pw, ph = w + 2 * pad, h + 2 * pad
        x, y = pad, pad
    page = doc.new_page(width=pw, height=ph)
    page.insert_image(pymupdf.Rect(x, y, x + w, y + h), stream=_stream(image, black_white))


def _output(paths, suffix, folder):
    """Nome do PDF: "foto em PDF", "foto e mais 2 fotos" ou "foto escaneado, 3 páginas"."""
    many = len(paths) - 1
    if not many:
        name = suffix
    elif suffix == "escaneado":
        name = f"escaneado, {len(paths)} páginas"
    else:
        name = f"e mais {many} {'foto' if many == 1 else 'fotos'}"
    return new_output(paths[0], name, "pdf", folder)


def photos_to_pdf(paths, page="A4", margin=True, folder=None, job=None):
    """Junta as fotos num PDF, uma por página, na ordem da lista."""
    import pymupdf
    job = job or Job()
    if not paths:
        raise RuntimeError("Adicione fotos primeiro")
    dst = _output(paths, "em PDF", folder)

    def work():
        doc = pymupdf.open()
        for i, path in enumerate(paths):
            job.check()
            _place(doc, _open(path), page, margin)
            job.progress((i + 1) / (len(paths) + 1))
        doc.save(dst, garbage=3, deflate=True)
        doc.close()
    guarded(dst, work)
    job.progress(1)
    return Result(dst, sum(os.path.getsize(p) for p in paths), os.path.getsize(dst))


# ---------------------------------------------------------------- documento "escaneado"
def _coefficients(source, target):
    """Números que o Pillow usa para entortar a foto: levam cada canto de target para source."""
    import numpy
    rows, values = [], []
    for (x, y), (u, v) in zip(target, source):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values += [u, v]
    return numpy.linalg.solve(numpy.array(rows, float), numpy.array(values, float)).tolist()


def flatten(image, corners):
    """Endireita a folha: os 4 cantos (topo esq., topo dir., base dir., base esq.) viram um retângulo."""
    (tl, tr, br, bl) = corners
    dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5
    width = round(max(dist(tl, tr), dist(bl, br)))
    height = round(max(dist(tl, bl), dist(tr, br)))
    if width < 50 or height < 50:
        return image
    target = [(0, 0), (width, 0), (width, height), (0, height)]
    flat = image.transform((width, height), Image.Transform.PERSPECTIVE, _coefficients(corners, target),
                           Image.Resampling.BICUBIC)
    edge = max(2, round(min(width, height) * .008))  # tira o fiozinho da mesa que sobra na borda
    return flat.crop((edge, edge, width - edge, height - edge))


def _light(gray):
    """Só a luz que bate no papel (sombras grandes), sem o conteúdo: foto 3x4, letras e desenhos somem."""
    small = gray.copy()
    small.thumbnail((300, 300))
    for _ in range(3):  # o máximo apaga o que é mais escuro que o papel em volta
        small = small.filter(ImageFilter.MaxFilter(9))
    small = small.filter(ImageFilter.GaussianBlur(max(small.size) / 7))
    return small.resize(gray.size, Image.Resampling.BILINEAR)


def even_light(image, paper=238, strongest=1.4):
    """Iguala a luz: o lado da sombra fica tão claro quanto o lado iluminado.
    Mexe só no brilho (as cores continuam as mesmas) e nunca clareia mais que `strongest` vezes,
    para fotos e fundos coloridos não estourarem."""
    import numpy
    gray = image.convert("L")
    light = numpy.asarray(_light(gray), dtype=numpy.float32)
    top = numpy.percentile(light, 97)  # o papel mais bem iluminado
    gain = numpy.clip(top / numpy.maximum(light, 1), 1, strongest)
    # depois o papel inteiro sobe até quase branco, sem passar disso
    gain *= min(strongest, paper / max(top, 1))
    pixels = numpy.asarray(image, dtype=numpy.float32)
    if pixels.ndim == 3:
        gain = gain[..., None]
    out = numpy.clip(pixels * gain, 0, 255).astype(numpy.uint8)
    return Image.fromarray(out, image.mode)


def black_and_white(gray):
    """Preto e branco de verdade, que aguenta sombra: cada ponto é comparado com a vizinhança."""
    import numpy
    pixels = numpy.asarray(gray, dtype=numpy.float32)
    area = numpy.asarray(gray.filter(ImageFilter.BoxBlur(max(8, gray.width // 60))), dtype=numpy.float32)
    ink = pixels < area * .82
    return Image.fromarray(numpy.where(ink, 0, 255).astype(numpy.uint8), "L")


SCAN_COLORS = ("Original", "Colorido", "Cinza", "Preto e branco")


def scan_page(image, color="Colorido", crop=True, corners=None):
    """Uma foto de documento vira página limpa.
    Original: só endireita. Colorido e Cinza: tiram sombra sem estourar fotos. Preto e branco: só texto."""
    if crop:
        if corners is None:
            corners = find_sheet(image)
        if corners:
            image = flatten(image, corners)
    image = _shrink(image)
    if color == "Original":
        return image
    if color != "Colorido":
        image = image.convert("L")
    if color == "Preto e branco":
        return black_and_white(even_light(image, paper=255, strongest=2.2))
    image = even_light(image)
    return image.filter(ImageFilter.UnsharpMask(1.0, 40, 3))


def find_sheet(image):
    """Cantos da folha na foto. Só no Mac (Vision); sem ele, usa a foto inteira."""
    try:
        from . import vision_mac
        if vision_mac.available():
            return vision_mac.document_corners(image)
    except Exception:
        pass
    return None


def scan_to_pdf(paths, color="Colorido", crop=True, folder=None, job=None):
    """Fotos de documento viram um PDF com cara de escaneado, uma página por foto."""
    import pymupdf
    job = job or Job()
    if not paths:
        raise RuntimeError("Adicione fotos do documento")
    dst = _output(paths, "escaneado", folder)

    def work():
        doc = pymupdf.open()
        for i, path in enumerate(paths):
            job.check()
            page = scan_page(_open(path).convert("RGB"), color, crop)
            _place(doc, page, "A4", False, black_white=color == "Preto e branco")
            job.progress((i + 1) / (len(paths) + 1))
        doc.save(dst, garbage=3, deflate=True)
        doc.close()
    guarded(dst, work)
    job.progress(1)
    return Result(dst, sum(os.path.getsize(p) for p in paths), os.path.getsize(dst))
