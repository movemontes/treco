"""Reconhecimento de imagem do próprio macOS (framework Vision), sem internet.

Só funciona no Mac. No Windows, as ferramentas que dependem daqui ficam escondidas.
"""
import io

from PIL import Image

from .images import ensure_heif


def available():
    try:
        import Vision  # noqa: F401
        return True
    except Exception:
        return False


def _handler(img):
    """Entrega a imagem ao Vision como PNG em memória, já com a rotação aplicada."""
    from Foundation import NSData
    import Vision
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    data = buffer.getvalue()
    return Vision.VNImageRequestHandler.alloc().initWithData_options_(NSData.dataWithBytes_length_(data, len(data)), {})


def _perform(handler, request):
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(str(error.localizedDescription()) if error else "O Mac não conseguiu analisar a imagem")


def open_image(path):
    """Abre a imagem em RGB/RGBA, girada do jeito que a câmera registrou."""
    from PIL import ImageOps
    ensure_heif()
    img = ImageOps.exif_transpose(Image.open(path))
    return img.convert("RGBA" if "A" in img.getbands() else "RGB")


# ---------------------------------------------------------------- texto
def read_text(img, languages=("pt-BR", "en-US", "es-ES")):
    """Texto encontrado na imagem, linha por linha, na ordem de leitura."""
    import Vision
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    request.setRecognitionLanguages_(list(languages))
    _perform(_handler(img.convert("RGB")), request)
    lines = []
    for item in request.results() or []:
        best = item.topCandidates_(1)
        if best:
            box = item.boundingBox()
            # origem do Vision é embaixo à esquerda: ordena de cima para baixo, depois da esquerda para a direita
            lines.append((round(1 - box.origin.y - box.size.height, 2), box.origin.x, str(best[0].string())))
    lines.sort()
    return "\n".join(text for _, _, text in lines)


# ---------------------------------------------------------------- rostos
def faces(img):
    """Caixas dos rostos em pixels: (esquerda, topo, direita, base)."""
    import Vision
    request = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    _perform(_handler(img.convert("RGB")), request)
    width, height = img.size
    boxes = []
    for face in request.results() or []:
        b = face.boundingBox()
        left, right = b.origin.x * width, (b.origin.x + b.size.width) * width
        top, bottom = (1 - b.origin.y - b.size.height) * height, (1 - b.origin.y) * height
        boxes.append((left, top, right, bottom))
    return boxes


# ---------------------------------------------------------------- fundo
def subject_mask(img):
    """Máscara em tons de cinza (branco = objeto principal), do tamanho da imagem.
    Devolve None se o Mac não achar nenhum objeto em destaque."""
    import Quartz
    import Vision
    from AppKit import NSBitmapImageRep, NSPNGFileType
    request = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    handler = _handler(img.convert("RGB"))
    _perform(handler, request)
    results = request.results() or []
    if not results:
        return None
    observation = results[0]
    instances = observation.allInstances()
    if instances is None or instances.count() == 0:
        return None
    buffer, error = observation.generateScaledMaskForImageForInstances_fromRequestHandler_error_(instances, handler, None)
    if buffer is None:
        raise RuntimeError(str(error.localizedDescription()) if error else "O Mac não conseguiu recortar")
    ci = Quartz.CIImage.imageWithCVPixelBuffer_(buffer)
    context = Quartz.CIContext.contextWithOptions_(None)
    cg = context.createCGImage_fromRect_(ci, ci.extent())
    rep = NSBitmapImageRep.alloc().initWithCGImage_(cg)
    png = rep.representationUsingType_properties_(NSPNGFileType, {})
    mask = Image.open(io.BytesIO(bytes(png))).convert("L")
    if mask.size != img.size:
        mask = mask.resize(img.size, Image.LANCZOS)
    return mask


# ---------------------------------------------------------------- folha de papel
def document_corners(img):
    """Cantos da folha na foto, em pixels: (topo esq., topo dir., base dir., base esq.).
    Devolve None se o Mac não achar uma folha."""
    import Vision
    width, height = img.size
    small = img.convert("RGB")
    small.thumbnail((1600, 1600))
    found = None
    for request in (Vision.VNDetectDocumentSegmentationRequest.alloc().init(), None):
        if request is None:  # plano B: o maior retângulo da foto
            request = Vision.VNDetectRectanglesRequest.alloc().init()
            request.setMinimumSize_(0.3)
            request.setMinimumConfidence_(0.6)
            request.setMaximumObservations_(1)
            request.setQuadratureTolerance_(30)
        try:
            _perform(_handler(small), request)
        except RuntimeError:
            continue
        results = [r for r in request.results() or [] if r.confidence() >= 0.5]
        if results:
            found = results[0]
            break
    if found is None:
        return None
    # Vision mede de 0 a 1, com a origem embaixo à esquerda
    point = lambda p: (p.x * width, (1 - p.y) * height)
    corners = [point(found.topLeft()), point(found.topRight()), point(found.bottomRight()), point(found.bottomLeft())]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    if (max(xs) - min(xs)) * (max(ys) - min(ys)) < width * height * 0.15:
        return None  # pedaço pequeno demais: provavelmente não é a folha
    return corners
