"""Tradução com o tradutor do próprio Mac, sem internet.

Quem traduz é o programa treco-translate (vendor/src/treco-translate.swift), porque a
tradução da Apple só existe em Swift. Os idiomas precisam estar baixados nos Ajustes do Mac.
"""
import json
import os
import re
import subprocess
import threading
import time

from ..core.jobs import Job
from ..core.paths import MAC, find_tool
from .quick import finish, guarded, new_output

# nome no botão, código para o Mac, palavra usada no nome do arquivo novo
LANGUAGES = [("Português", "pt-BR", "português"), ("Inglês", "en", "inglês"),
             ("Espanhol", "es", "espanhol"), ("Francês", "fr", "francês")]
TEXT_EXT = {".txt", ".md", ".markdown"}
SUB_EXT = {".srt", ".vtt"}
SETTINGS_URL = "x-apple.systempreferences:com.apple.Localization-Settings.extension"
_settings_opened = [0.0]


class NotDownloaded(RuntimeError):
    def __init__(self):
        super().__init__("Baixe o idioma nos Ajustes")


def helper():
    return find_tool("treco-translate") if MAC else None


def available():
    return bool(helper())


def open_language_settings():
    """Abre Ajustes > Geral > Idioma e Região, onde ficam os Idiomas de Tradução."""
    if time.monotonic() - _settings_opened[0] < 30:  # um arquivo por vez não abre a janela várias vezes
        return
    _settings_opened[0] = time.monotonic()
    subprocess.Popen(["open", SETTINGS_URL])


def _call(args, data, job=None):
    process = subprocess.Popen([helper()] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    if job:
        job.attach(process)
    messages = []

    def read_errors():
        for raw in process.stderr:
            line = raw.decode("utf-8", "replace").strip()
            parts = line.split()
            if job and len(parts) == 3 and parts[0] == "progresso" and int(parts[2]):
                job.progress(.05 + .9 * int(parts[1]) / int(parts[2]))
            elif line:
                messages.append(line)

    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    try:
        process.stdin.write(data.encode("utf-8"))
        process.stdin.close()
    except BrokenPipeError:
        pass
    output = process.stdout.read()
    process.wait()
    reader.join(2)
    if job:
        job.detach()
        job.check()
    return process.returncode, output.decode("utf-8", "replace"), " ".join(messages)


def detect(text):
    """Código do idioma do texto, como 'pt' ou 'en'."""
    code, output, _ = _call(["detect"], text)
    return output.strip() if code == 0 else ""


def translate_texts(texts, target, source="auto", job=None):
    """Traduz uma lista de textos, na mesma ordem. Textos vazios voltam vazios."""
    if not helper():
        raise RuntimeError("Tradutor só no Mac")
    if not any(t.strip() for t in texts):
        raise RuntimeError("Não achei texto")
    code, output, message = _call(["run", source, target], json.dumps(texts, ensure_ascii=False), job)
    if code == 0:
        return json.loads(output)
    if code == 3:
        open_language_settings()
        raise NotDownloaded()
    if code == 4:
        raise RuntimeError("Já está nesse idioma")
    if code == 5:
        raise RuntimeError("O Mac não traduz esse idioma")
    raise RuntimeError(message[:80] or "O tradutor do Mac falhou")


def quick_target(text):
    """Para o que foi copiado: traduz para português, ou para inglês se já estiver em português."""
    return "en" if detect(text).startswith("pt") else "pt-BR"


def translate_text(text, target=None):
    target = target or quick_target(text)
    return translate_plain(text, target), target


# ---------------------------------------------------------------- arquivos
def _subtitle_blocks(text):
    """Separa a legenda em blocos e, em cada bloco, a parte fixa (número, tempo) do texto falado."""
    blocks = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:  # cabeçalho WEBVTT, NOTE, STYLE: fica como está
            blocks.append((block, ""))
        else:
            blocks.append(("\n".join(lines[:timing + 1]), "\n".join(lines[timing + 1:])))
    return blocks


def translate_subtitle(text, target, job=None):
    blocks = _subtitle_blocks(text)
    spoken = translate_texts([body for _, body in blocks], target, job=job)
    return "\n\n".join(head + ("\n" + body if body else "") for (head, _), body in zip(blocks, spoken)) + "\n"


MARKDOWN_PREFIX = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|>\s*|\d+[.)]\s+)?)(.*)$")


def translate_plain(text, target, markdown=False, job=None):
    """Texto corrido: traduz parágrafo por parágrafo. No Markdown, cada linha guarda o seu # ou -."""
    lines = text.replace("\r\n", "\n").split("\n")
    if markdown:
        parts = [MARKDOWN_PREFIX.match(line).groups() for line in lines]
        fence, keep = False, []
        for prefix, body in parts:
            if body.strip().startswith("```") or prefix.strip().startswith("```"):
                fence = not fence
                keep.append(True)
            else:
                keep.append(fence)
        done = translate_texts(["" if k else body for (_, body), k in zip(parts, keep)], target, job=job)
        return "\n".join(line if k else prefix + new for line, (prefix, _), new, k in zip(lines, parts, done, keep))
    paragraphs = re.split(r"(\n\s*\n)", text.replace("\r\n", "\n"))  # guarda as linhas em branco
    done = translate_texts([p if i % 2 == 0 else "" for i, p in enumerate(paragraphs)], target, job=job)
    return "".join(paragraphs[i] if i % 2 else piece for i, piece in enumerate(done))


def _document_text(src, kind):
    if kind == "pdf":
        from .documents import open_pdf
        with open_pdf(src) as doc:
            return "\n\n".join(page.get_text().strip() for page in doc)
    import pypandoc
    result = subprocess.run([pypandoc.get_pandoc_path(), src, "-t", "plain", "--wrap=none"],
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Não consegui ler esse documento")
    return result.stdout


def _read(path):
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def translate_file(src, kind, target, folder=None, job=None):
    """Cria "X em inglês.ext". Legendas e textos mantêm o formato; outros documentos viram .txt."""
    job = job or Job()
    ext = os.path.splitext(src)[1].lower()
    word = next(w for _, code, w in LANGUAGES if code == target)
    job.progress(.02)
    if ext in SUB_EXT:
        text, out_ext = translate_subtitle(_read(src), target, job), ext.lstrip(".")
    elif ext in TEXT_EXT:
        text, out_ext = translate_plain(_read(src), target, ext != ".txt", job), ext.lstrip(".")
    else:
        source = _document_text(src, kind)
        if not source.strip():
            raise RuntimeError("Não achei texto (use Ler texto)" if kind == "pdf" else "Não achei texto")
        # o pandoc entrega um parágrafo por linha: traduz linha por linha, guardando os marcadores de lista
        text, out_ext = translate_plain(source, target, markdown=kind != "pdf", job=job), "txt"
    from ..core.i18n import english, tr
    dst = new_output(src, f"in {tr(word)}" if english() else f"em {word}", out_ext, folder)
    guarded(dst, lambda: open(dst, "w", encoding="utf-8").write(text.rstrip("\n") + "\n"))
    job.progress(1)
    return finish(src, dst)
