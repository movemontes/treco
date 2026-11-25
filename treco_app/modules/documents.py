"""Conversões de PDF, documentos, planilhas e apresentações do Treco.

As bibliotecas pesadas só são importadas na hora de usar, para o app abrir rápido.
"""
import html as html_lib
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def find_program(name, *paths):
    found = shutil.which(name)
    if found:
        return found
    for p in paths:
        p = os.path.expandvars(p)
        if os.path.exists(p):
            return p
    return None


if sys.platform == "darwin":
    SOFFICE = find_program("soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice")
    EDGE = find_program("msedge", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                        "/Applications/Chromium.app/Contents/MacOS/Chromium",
                        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
else:
    SOFFICE = find_program("soffice", r"%ProgramFiles%\LibreOffice\program\soffice.exe",
                           r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe")
    EDGE = find_program("msedge", r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")

PDF_IN = {".pdf"}
DOC_IN = {".docx", ".odt", ".rtf", ".md", ".markdown", ".txt", ".html", ".htm", ".epub"}
SHEET_IN = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".tsv"}
SLIDE_IN = {".pptx", ".ppt", ".odp"} if SOFFICE else set()
if SOFFICE:
    DOC_IN = DOC_IN | {".doc"}

PDF_OUT = ["DOCX", "TXT", "MD", "HTML", "EPUB", "PNG", "JPG", "PPTX", "XLSX"]
DOC_OUT = ["DOCX", "PDF", "ODT", "RTF", "MD", "HTML", "TXT", "EPUB"]
SHEET_OUT = ["XLSX", "ODS", "CSV", "TSV", "HTML", "PDF"]
SLIDE_OUT = ["PDF", "PNG", "JPG"]

PANDOC_FROM = {".docx": "docx", ".odt": "odt", ".rtf": "rtf", ".md": "markdown",
               ".markdown": "markdown", ".html": "html", ".htm": "html", ".epub": "epub"}
PANDOC_TO = {"DOCX": "docx", "ODT": "odt", "RTF": "rtf", "MD": "gfm", "HTML": "html5",
             "TXT": "plain", "EPUB": "epub3"}

PAGE_CSS = """
@page { size: A4%s; margin: 18mm; }
body { font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #111; }
img { max-width: 100%%; height: auto; }
table { border-collapse: collapse; width: 100%%; font-size: 9pt; }
td, th { border: 1px solid #bbb; padding: 3px 6px; vertical-align: top; }
tr { break-inside: avoid; }
h2.sheet { font-size: 13pt; margin: 0 0 8px; }
section + section { break-before: page; }
pre { white-space: pre-wrap; }
"""


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def run(cmd, cwd=None, timeout=600):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=NO_WINDOW, timeout=timeout)
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip().splitlines()
        raise RuntimeError(msg[-1] if msg else f"{os.path.basename(cmd[0])} falhou")


def pandoc(src, src_format, dst, fmt, title, sandbox):
    import pypandoc
    args = [pypandoc.get_pandoc_path(), src, "-f", src_format, "-t", PANDOC_TO[fmt], "-o", dst]
    if sandbox:  # não busca imagens nem nada fora do arquivo
        args.append("--sandbox")
    if fmt == "RTF":
        args.append("--standalone")
    if fmt == "EPUB":
        args += ["--standalone", "--metadata", f"title={title}"]
    if fmt == "HTML":  # pagetitle: nome na aba, sem inserir um título no texto
        args += ["--standalone", "--embed-resources", "--metadata", f"pagetitle={title}"]
    if fmt in ("MD", "TXT"):
        args.append("--wrap=none")
    if fmt == "MD" and not sandbox:
        args.append(f"--extract-media={title} imagens")
    run(args, cwd=os.path.dirname(dst))


def print_with_edge(page, out, profile, timeout=45):
    """Gera o PDF com o Edge sem janela. Se ele travar, encerra só este processo e seus filhos."""
    group = {"start_new_session": True} if sys.platform != "win32" else {}
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
         "--disable-extensions", "--blink-settings=scriptEnabled=false", f"--user-data-dir={profile}",
         f"--print-to-pdf={out}", "file:///" + page.replace("\\", "/").lstrip("/")],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=NO_WINDOW, **group)
    deadline = time.monotonic() + timeout
    last_size, stable = -1, 0
    while time.monotonic() < deadline and proc.poll() is None:
        size = os.path.getsize(out) if os.path.exists(out) else -1
        stable = stable + 1 if size > 0 and size == last_size else 0
        last_size = size
        if stable >= 3:  # PDF pronto, mesmo que o Edge demore para fechar
            break
        time.sleep(0.1)
    if proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # só o grupo deste processo
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def html_to_pdf(html, dst, landscape=False):
    css = PAGE_CSS % (" landscape" if landscape else "")
    if "</head>" in html:
        html = html.replace("</head>", f"<style>{css}</style></head>", 1)
    else:
        html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{html}</body></html>"
    with tempfile.TemporaryDirectory(prefix="treco_", ignore_cleanup_errors=True) as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(html)
        if EDGE:
            out = os.path.join(tmp, "out.pdf")
            print_with_edge(page, out, os.path.join(tmp, "edge"))
            if os.path.exists(out) and os.path.getsize(out) > 0:
                shutil.move(out, dst)
                return
        import pymupdf as fitz
        story = fitz.Story(html=html)
        writer = fitz.DocumentWriter(dst)
        box = fitz.paper_rect("a4-l" if landscape else "a4")
        more = 1
        while more:
            dev = writer.begin_page(box)
            more, _ = story.place(box + (50, 50, -50, -50))
            story.draw(dev)
            writer.end_page()
        writer.close()


def soffice_to_pdf(src, dst):
    with tempfile.TemporaryDirectory(prefix="treco_") as tmp:
        run([SOFFICE, f"-env:UserInstallation=file:///{tmp.replace(os.sep, '/').lstrip('/')}/lo", "--headless",
             "--convert-to", "pdf", "--outdir", tmp, src])
        out = os.path.join(tmp, os.path.splitext(os.path.basename(src))[0] + ".pdf")
        if not os.path.exists(out):
            raise RuntimeError("LibreOffice não gerou o PDF")
        shutil.move(out, dst)


# ---------------------------------------------------------------- PDF
def open_pdf(src):
    import pymupdf as fitz
    doc = fitz.open(src)
    if doc.needs_pass:
        doc.close()
        raise RuntimeError("PDF protegido por senha")
    return doc


def pdf_markdown(src):
    with open_pdf(src) as doc:
        if not any(p.get_text().strip() for p in doc):
            raise RuntimeError("PDF sem texto (escaneado)")
    try:
        import pymupdf4llm
        if hasattr(pymupdf4llm, "use_layout"):
            pymupdf4llm.use_layout(False)  # modo leve: bem mais rápido e sem modelos de IA
        md = pymupdf4llm.to_markdown(src, show_progress=False)
        if md.strip():
            return md
    except Exception:
        pass
    with open_pdf(src) as doc:
        return "\n\n".join(html_lib.escape(p.get_text(), quote=False) for p in doc)


def render_pages(doc, dst, fmt, dpi=200):
    """Uma página vira um arquivo; várias páginas viram uma pasta."""
    ext = "png" if fmt == "PNG" else "jpg"
    if doc.page_count == 1:
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        pix.save(dst, jpg_quality=92) if ext == "jpg" else pix.save(dst)
        return dst
    os.remove(dst)
    stem = os.path.splitext(dst)[0]
    folder, n = stem, 1
    while os.path.exists(folder):
        folder, n = f"{stem} ({n})", n + 1
    os.makedirs(folder)
    width = max(2, len(str(doc.page_count)))
    for i, page in enumerate(doc, 1):
        out = os.path.join(folder, f"página {i:0{width}d}.{ext}")
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        pix.save(out, jpg_quality=92) if ext == "jpg" else pix.save(out)
    return folder


def pdf_to_pptx(doc, dst):
    from pptx import Presentation
    deck = Presentation()
    first = doc[0].rect
    deck.slide_width, deck.slide_height = int(first.width * 12700), int(first.height * 12700)
    blank = deck.slide_layouts[6]
    for page in doc:
        data = page.get_pixmap(dpi=170, alpha=False).tobytes("jpeg", jpg_quality=88)
        deck.slides.add_slide(blank).shapes.add_picture(io.BytesIO(data), 0, 0, deck.slide_width,
                                                        deck.slide_height)
    deck.save(dst)


def pdf_to_xlsx(doc, dst):
    from openpyxl import Workbook
    book = Workbook()
    book.remove(book.active)
    for pno, page in enumerate(doc, 1):
        for tno, table in enumerate(page.find_tables().tables, 1):
            sheet = book.create_sheet(f"Pág {pno} tabela {tno}"[:31])
            for row in table.extract():
                sheet.append([clean_cell(c) for c in row])
    if not book.worksheets:
        raise RuntimeError("nenhuma tabela encontrada no PDF")
    book.save(dst)


def clean_cell(value):
    if value is None:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))


def convert_pdf(src, dst, fmt):
    title = os.path.splitext(os.path.basename(src))[0]
    if fmt in ("PNG", "JPG", "PPTX", "XLSX"):
        with open_pdf(src) as doc:
            if fmt == "PPTX":
                pdf_to_pptx(doc, dst)
            elif fmt == "XLSX":
                pdf_to_xlsx(doc, dst)
            else:
                return render_pages(doc, dst, fmt)
        return dst
    if fmt == "TXT":
        with open_pdf(src) as doc:
            text = "\n\n".join(p.get_text().strip() for p in doc).strip()
        if not text:
            raise RuntimeError("PDF sem texto (escaneado)")
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        return dst
    md = pdf_markdown(src)
    if fmt == "MD":
        with open(dst, "w", encoding="utf-8") as f:
            f.write(md)
        return dst
    with tempfile.TemporaryDirectory(prefix="treco_") as tmp:
        temp = os.path.join(tmp, "doc.md")
        with open(temp, "w", encoding="utf-8") as f:
            f.write(md)
        pandoc(temp, "markdown", dst, fmt, title, True)
    return dst


# ---------------------------------------------------------------- documentos
def text_as_html(text):
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    return "\n".join("<p>" + html_lib.escape(b).replace("\n", "<br>") + "</p>" for b in blocks)


def convert_doc(src, dst, fmt):
    ext = os.path.splitext(src)[1].lower()
    title = os.path.splitext(os.path.basename(src))[0]
    if fmt == "PDF" and SOFFICE:
        soffice_to_pdf(src, dst)
        return dst
    if ext == ".doc":
        if not SOFFICE:
            raise RuntimeError(".doc precisa do LibreOffice")
        with tempfile.TemporaryDirectory(prefix="treco_") as tmp:
            pdf = os.path.join(tmp, "doc.pdf")
            soffice_to_pdf(src, pdf)
            return convert_pdf(pdf, dst, fmt)

    with tempfile.TemporaryDirectory(prefix="treco_") as tmp:
        source, source_format = src, PANDOC_FROM.get(ext)
        if ext == ".txt":  # texto puro: preserva linhas e símbolos como estão
            source, source_format = os.path.join(tmp, "doc.html"), "html"
            with open(source, "w", encoding="utf-8") as f:
                f.write(text_as_html(read_text(src)))
        elif ext in (".md", ".markdown", ".html", ".htm", ".rtf"):
            source = os.path.join(tmp, "doc" + ext)  # aceita arquivos que não estão em UTF-8
            with open(source, "w", encoding="utf-8") as f:
                f.write(read_text(src))
        sandbox = ext in (".txt", ".md", ".markdown", ".html", ".htm", ".rtf")
        if fmt == "PDF":
            temp_html = os.path.join(tmp, "out.html")
            pandoc(source, source_format, temp_html, "HTML", title, sandbox)
            html_to_pdf(read_text(temp_html), dst)
        else:
            pandoc(source, source_format, dst, fmt, title, sandbox)
    return dst


# ---------------------------------------------------------------- planilhas
def read_sheets(src):
    import pandas as pd
    ext = os.path.splitext(src)[1].lower()
    if ext in (".csv", ".tsv"):
        text = read_text(src)
        options = {"sep": "\t"} if ext == ".tsv" else {"sep": None, "engine": "python"}
        frame = pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False,
                            skip_blank_lines=False, **options)
        return {"Planilha": frame}
    engine = {".xls": "xlrd", ".ods": "odf"}.get(ext, "openpyxl")
    sheets = pd.read_excel(src, sheet_name=None, header=None, dtype=object, engine=engine)
    return {name: frame.astype(object).where(frame.notna(), "") for name, frame in sheets.items()}


def safe_sheet_name(name, used):
    base = re.sub(r"[\[\]:*?/\\]", " ", str(name)).strip()[:31] or "Planilha"
    out, n = base, 1
    while out.lower() in used:
        suffix = f" {n}"
        out, n = base[:31 - len(suffix)] + suffix, n + 1
    used.add(out.lower())
    return out


def sheets_html(sheets):
    parts = []
    for name, frame in sheets.items():
        title = f"<h2 class='sheet'>{html_lib.escape(str(name))}</h2>" if len(sheets) > 1 else ""
        parts.append(f"<section>{title}{frame.to_html(header=False, index=False, border=0, na_rep='')}</section>")
    return "\n".join(parts)


def convert_sheet(src, dst, fmt):
    import pandas as pd
    sheets = read_sheets(src)
    if fmt in ("XLSX", "ODS"):
        used = set()
        with pd.ExcelWriter(dst, engine="openpyxl" if fmt == "XLSX" else "odf") as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=safe_sheet_name(name, used), header=False, index=False)
    elif fmt in ("CSV", "TSV"):
        # ";" é o separador que o Excel em português abre direto
        sep, ext = (";", "csv") if fmt == "CSV" else ("\t", "tsv")
        if len(sheets) == 1:
            next(iter(sheets.values())).to_csv(dst, sep=sep, header=False, index=False, encoding="utf-8-sig")
            return dst
        os.remove(dst)
        stem = os.path.splitext(dst)[0]
        folder, n = stem, 1
        while os.path.exists(folder):
            folder, n = f"{stem} ({n})", n + 1
        os.makedirs(folder)
        used = set()
        for name, frame in sheets.items():
            clean = re.sub(r'[<>:"/\\|?*]', " ", safe_sheet_name(name, used))
            frame.to_csv(os.path.join(folder, f"{clean}.{ext}"), sep=sep, header=False, index=False,
                         encoding="utf-8-sig")
        return folder
    elif fmt == "HTML":
        title = html_lib.escape(os.path.splitext(os.path.basename(src))[0])
        css = PAGE_CSS % ""
        with open(dst, "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
                    f"<style>{css}</style></head><body>{sheets_html(sheets)}</body></html>")
    elif fmt == "PDF":
        wide = max((f.shape[1] for f in sheets.values()), default=0) > 6
        html_to_pdf(sheets_html(sheets), dst, landscape=wide)
    return dst


# ---------------------------------------------------------------- apresentações
def convert_slides(src, dst, fmt):
    if not SOFFICE:
        raise RuntimeError("apresentações precisam do LibreOffice")
    if fmt == "PDF":
        soffice_to_pdf(src, dst)
        return dst
    with tempfile.TemporaryDirectory(prefix="treco_") as tmp:
        pdf = os.path.join(tmp, "slides.pdf")
        soffice_to_pdf(src, pdf)
        with open_pdf(pdf) as doc:
            return render_pages(doc, dst, fmt)


def convert(src, dst, kind, fmt):
    return {"pdf": convert_pdf, "doc": convert_doc, "sheet": convert_sheet,
            "slide": convert_slides}[kind](src, dst, fmt)
