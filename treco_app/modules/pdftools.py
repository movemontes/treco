"""PDF: organizar páginas, tarja preta de verdade e assinatura.

Sempre cria um PDF novo. O original fica como está.
"""
import io
import os
import re

from ..core.jobs import Job
from .quick import finish, guarded, new_output

# o que a tarja automática procura (no texto do PDF)
PATTERNS = {
    "CPF": r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
    "CNPJ": r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b",
    "RG": r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dxX]\b",
    "E-mail": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "Telefone": r"(?:\(?\b\d{2}\)?\s?)?\b9?\d{4}[-\s]?\d{4}\b",
    "Conta": r"\b(?:ag(?:ência)?|c/?c|conta)\.?:?\s*[\d.-]{4,}\b",
}


def open_pdf(src):
    import pymupdf
    doc = pymupdf.open(src)
    if doc.needs_pass:
        doc.close()
        raise RuntimeError("Esse PDF tem senha. Tire a senha antes.")
    return doc


def page_count(src):
    with open_pdf(src) as doc:
        return doc.page_count


def render(src, index, width):
    """Imagem da página com a largura pedida (em pixels reais). Devolve (imagem, escala)."""
    import pymupdf
    from PIL import Image
    with open_pdf(src) as doc:
        page = doc[index]
        scale = width / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), scale


# ---------------------------------------------------------------- organizar páginas
def organize(src, pages, folder=None, job=None):
    """pages: lista de (índice da página original, giro extra em graus), na ordem nova."""
    job = job or Job()
    if not pages:
        raise RuntimeError("Sobrou nenhuma página")
    with open_pdf(src) as doc:
        dst = new_output(src, "organizado", "pdf", folder)

        def work():
            import pymupdf
            out = pymupdf.open()
            for n, (index, turn) in enumerate(pages):
                out.insert_pdf(doc, from_page=index, to_page=index)
                if turn:
                    page = out[-1]
                    page.set_rotation((page.rotation + turn) % 360)
                job.progress(.9 * (n + 1) / len(pages))
            out.save(dst, garbage=3, deflate=True)
            out.close()
        guarded(dst, work)
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- tarja preta
def find_text(src, kinds=(), words=""):
    """Onde aparecem os dados escolhidos: {página: [retângulos]} em pontos do PDF."""
    found = {}
    expressions = [re.compile(PATTERNS[k], re.IGNORECASE) for k in kinds]
    words = [w.strip() for w in words.split(",") if w.strip()]
    with open_pdf(src) as doc:
        for index, page in enumerate(doc):
            rects = []
            text = page.get_text()
            hits = set()
            for expression in expressions:
                hits |= {m.group(0).strip() for m in expression.finditer(text)}
            hits |= set(words)
            for hit in hits:
                rects += [tuple(r) for r in page.search_for(hit)]
            if rects:
                found[index] = rects
    return found


def redact(src, boxes, folder=None, job=None):
    """boxes: {página: [(x0, y0, x1, y1)]}. O texto, as imagens e os desenhos embaixo somem de verdade:
    não dá para copiar nem tirar a tarja depois."""
    import pymupdf
    job = job or Job()
    if not any(boxes.values()):
        raise RuntimeError("Marque o que esconder")
    with open_pdf(src) as doc:
        dst = new_output(src, "com tarja", "pdf", folder)

        def work():
            total = len(boxes)
            for n, (index, rects) in enumerate(sorted(boxes.items())):
                page = doc[index]
                for rect in rects:
                    page.add_redact_annot(pymupdf.Rect(rect), fill=(0, 0, 0))
                page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                                      graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
                job.progress(.9 * (n + 1) / total)
            doc.set_metadata({})  # nome do autor e programas também saem
            doc.save(dst, garbage=4, deflate=True, clean=True)
        guarded(dst, work)
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- assinatura
def signature_folder():
    from ..core.paths import data_dir
    folder = os.path.join(data_dir(), "assinaturas")
    os.makedirs(folder, exist_ok=True)
    return folder


def clean_signature(image):
    """Foto ou desenho da assinatura: fundo vira transparente e a tinta fica escura e nítida."""
    from PIL import Image, ImageOps
    image = ImageOps.exif_transpose(image).convert("RGBA")
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=2)
    alpha = gray.point(lambda v: 0 if v > 200 else 255 if v < 110 else int((200 - v) * 255 / 90))
    if image.getchannel("A").getextrema()[0] < 255:  # já tinha transparência (PNG)
        alpha = Image.composite(alpha, Image.new("L", image.size, 0), image.getchannel("A"))
    ink = Image.new("RGBA", image.size, (20, 24, 60, 255))
    ink.putalpha(alpha)
    box = alpha.getbbox()
    return ink.crop(box) if box else ink


def sign(src, placements, image, folder=None, job=None, certificate=None, password=None, reason=""):
    """placements: lista de (página, (x0, y0, x1, y1)) em pontos. Com certificado (.pfx/.p12), o PDF sai
    também assinado digitalmente: qualquer leitor de PDF mostra quem assinou e se o arquivo mudou depois."""
    import pymupdf
    job = job or Job()
    if not placements:
        raise RuntimeError("Clique na página onde vai a assinatura")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    data = buffer.getvalue()
    with open_pdf(src) as doc:
        dst = new_output(src, "assinado", "pdf", folder)

        def work():
            for index, rect in placements:
                doc[index].insert_image(pymupdf.Rect(rect), stream=data, keep_proportion=True, overlay=True)
            job.progress(.5)
            if certificate:
                plain = doc.tobytes(garbage=3, deflate=True)
                with open(dst, "wb") as out:
                    out.write(certify(plain, certificate, password, reason))
            else:
                doc.save(dst, garbage=3, deflate=True)
        guarded(dst, work)
    job.progress(1)
    return finish(src, dst)


def can_certify():
    try:
        import pyhanko  # noqa: F401
        return True
    except ImportError:
        return False


def certificate_name(path, password):
    """Nome de quem é o certificado. Erro claro se a senha estiver errada."""
    from cryptography.hazmat.primitives.serialization import pkcs12
    with open(path, "rb") as f:
        data = f.read()
    try:
        _, cert, _ = pkcs12.load_key_and_certificates(data, (password or "").encode())
    except ValueError:
        raise RuntimeError("Senha do certificado errada")
    if cert is None:
        raise RuntimeError("Esse arquivo não tem certificado")
    from cryptography.x509.oid import NameOID
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return names[0].value.split(":")[0] if names else "certificado"  # ICP-Brasil: "NOME:CPF"


def certify(pdf_bytes, certificate, password, reason=""):
    """Assinatura digital (PAdES) com o certificado A1 da pessoa, como o do ICP-Brasil."""
    if not can_certify():
        raise RuntimeError("Assinatura digital não disponível nesta versão")
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    signer = signers.SimpleSigner.load_pkcs12(certificate, passphrase=(password or "").encode() or None)
    if signer is None:
        raise RuntimeError("Senha do certificado errada")
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
    meta = signers.PdfSignatureMetadata(field_name="Assinatura", reason=reason or None,
                                        md_algorithm="sha256")
    out = signers.sign_pdf(writer, meta, signer=signer)
    return out.getvalue()
