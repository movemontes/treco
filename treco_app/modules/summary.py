"""Resumo rápido de página: baixa o texto de um link e a IA do próprio Mac resume.

A página é lida pela internet (como um navegador), mas o resumo é feito no Mac, sem mandar o texto a ninguém.
"""
import html
import os
import re
import ssl
import subprocess
import threading
import time
import urllib.request
from html.parser import HTMLParser

from ..core.i18n import english, tr
from ..core.files import unique_path
from ..core.jobs import Job
from ..core.paths import MAC, find_tool

SIZES = {"Curto": "curto", "Médio": "medio", "Detalhado": "detalhado"}
FORMATS = ("txt", "md")
AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


class Unavailable(RuntimeError):
    """A IA do Mac não está pronta (desligada, baixando ou Mac sem suporte)."""


def helper():
    return find_tool("treco-summarize") if MAC else None


_status = {}


def status():
    """None se a IA está pronta; senão, o motivo em palavras simples."""
    path = helper()
    if not path:
        return "Resumo precisa do macOS 26 com Apple Intelligence"
    if "value" not in _status or time.monotonic() - _status["at"] > 60:
        try:
            result = subprocess.run([path, "status"], capture_output=True, text=True, timeout=20)
            _status["value"] = None if result.returncode == 0 else (result.stderr.strip() or "IA indisponível")
        except Exception:
            _status["value"] = "A IA do Mac não respondeu"
        _status["at"] = time.monotonic()
    return _status["value"]


def available():
    return helper() is not None


# ---------------------------------------------------------------- ler a página
def clean_url(text):
    text = text.strip()
    if not text:
        return None
    if not re.match(r"https?://", text, re.I):
        text = "https://" + text
    return text if re.match(r"https?://[^\s/]+\.[^\s/]+", text, re.I) else None


def fetch(url, limit=6_000_000):
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=25, context=context) as response:
            kind = response.headers.get("Content-Type", "")
            if "html" not in kind and "text" not in kind:
                raise RuntimeError("Esse link não é uma página de texto")
            data = response.read(limit)
            charset = response.headers.get_content_charset()
    except urllib.error.HTTPError as error:
        raise RuntimeError("A página não abriu (pode pedir login)" if error.code in (401, 403) else f"A página respondeu erro {error.code}")
    except urllib.error.URLError:
        raise RuntimeError("Sem internet, ou o link está errado")
    if not charset:
        match = re.search(rb'charset=["\']?([\w-]+)', data[:4000])
        charset = match[1].decode() if match else "utf-8"
    return data.decode(charset, "replace")


SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "button", "iframe", "select",
        "figure", "template"}
BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "td", "dd"}


class _Reader(HTMLParser):
    """Separa o texto do artigo do resto (menus, rodapé, propaganda)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta_title = "", ""
        self.skip = 0
        self.stack = []
        self.blocks = []  # (texto, dentro de <article>/<main>, é título)
        self.current, self.block_tag = [], None
        self.in_title = False
        self.article = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property") == "og:title":
            self.meta_title = attrs.get("content") or ""
        hidden = "hidden" in attrs or attrs.get("aria-hidden") == "true"
        role = attrs.get("role", "")
        if tag in SKIP or hidden or role in ("navigation", "banner", "contentinfo", "complementary"):
            if tag not in ("meta", "link", "br", "img", "input"):
                self.skip += 1
                self.stack.append(("skip", tag))
            return
        if tag in ("article", "main") or role == "main":
            self.article += 1
            self.stack.append(("article", tag))
        elif tag == "title":
            self.in_title = True
        elif tag in BLOCKS and self.block_tag is None and not self.skip:
            self.block_tag, self.current = tag, []

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][1] == tag:
            what, _ = self.stack.pop()
            if what == "skip":
                self.skip -= 1
            else:
                self.article -= 1
        if tag == "title":
            self.in_title = False
        if tag == self.block_tag:
            text = " ".join("".join(self.current).split())
            if text:
                self.blocks.append((text, self.article > 0, tag in ("h1", "h2", "h3", "h4")))
            self.block_tag = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif self.block_tag and not self.skip:
            self.current.append(data)


def extract(page):
    """(título, texto do artigo)."""
    reader = _Reader()
    try:
        reader.feed(page)
    except Exception:
        pass
    inside = [b for b in reader.blocks if b[1]]
    blocks = inside if sum(len(b[0]) for b in inside) > 600 else reader.blocks
    lines = []
    for text, _, heading in blocks:
        if heading or len(text) >= 40:  # frases soltas curtas costumam ser menu ou botão
            if not lines or lines[-1] != text:
                lines.append(text)
    title = short_title(" ".join(html.unescape(reader.meta_title or reader.title).split()))
    return title, "\n".join(lines)


# ---------------------------------------------------------------- resumir
def summarize_text(text, size="Médio", job=None, stage=None):
    path = helper()
    if not path:
        raise Unavailable("Resumo precisa do macOS 26 com Apple Intelligence")
    job = job or Job()
    process = subprocess.Popen([path, "run", SIZES.get(size, "medio"), "en" if english() else "pt"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    job.attach(process)
    errors = []

    def read_errors():
        for raw in process.stderr:
            line = raw.decode("utf-8", "replace").strip()
            match = re.match(r"parte (\d+) (\d+)", line)
            if match:
                done, total = int(match[1]), int(match[2])
                job.progress(.1 + .8 * (done - 1) / total)
                if stage:
                    stage(f"Resumindo a parte {done} de {total}…")
            elif line == "final":
                job.progress(.9)
                if stage:
                    stage("Escrevendo o resumo…")
            else:
                errors.append(line)

    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    output = b""
    try:
        # não usa communicate(): ele também leria os avisos e a linha de leitura acima ficaria sem eles
        try:
            process.stdin.write(text.encode("utf-8"))
            process.stdin.close()
        except BrokenPipeError:
            pass
        output = process.stdout.read()
        process.wait(timeout=600)
    finally:
        job.detach()
    reader.join(5)
    job.check()
    if process.returncode and process.returncode < 0 and not errors:
        raise RuntimeError("A IA do Mac parou no meio. Tente de novo")
    if process.returncode == 3:
        raise Unavailable(errors[-1] if errors else "A IA do Mac não está disponível")
    if process.returncode:
        raise RuntimeError(errors[-1] if errors else "A IA do Mac falhou")
    return tidy(output.decode("utf-8", "replace"))


def tidy(text):
    """Deixa o resumo em texto simples: tópicos com "- " e sem asteriscos de negrito."""
    lines = []
    for line in text.strip().splitlines():
        line = re.sub(r"^\s*[*•]\s+", "- ", line.rstrip())
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def short_title(title):
    """ "Capivara – Wikipédia, a enciclopédia livre" vira "Capivara"."""
    for mark in (" | ", " – ", " — ", " - "):
        if mark in title:
            head, tail = title.rsplit(mark, 1)
            if len(tail) <= 45 and len(head) >= 8:
                return head.strip()
    return title


def file_name(title, url):
    base = title or re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    base = " ".join(re.sub(r'[\\/:*?"<>|]+', " ", base).split())[:70].strip(" .") or "página"
    return f"{tr('Resumo')} - {base}"


def summarize_url(url, size="Médio", fmt="txt", folder=None, job=None, stage=None):
    """Lê a página, resume e salva o arquivo. Devolve (caminho, título, resumo)."""
    job = job or Job()
    say = stage or (lambda text: None)
    say("Lendo a página…")
    title, text = extract(fetch(url))
    job.check()
    if len(text) < 200:
        raise RuntimeError("Não achei o texto dessa página (pode ser vídeo, app ou pedir login)")
    say("Resumindo…")
    job.progress(.1)
    summary = summarize_text(text, size, job, say)
    folder = folder or os.path.expanduser("~/Desktop")
    path = unique_path(folder, file_name(title, url), fmt)
    day = time.strftime("%d/%m/%Y")
    if fmt == "md":
        body = (f"# {title or 'Summary'}\n\n[{url}]({url}) · summarized on {day}\n\n{summary}\n" if english() else
                f"# {title or 'Resumo'}\n\n[{url}]({url}) · resumido em {day}\n\n{summary}\n")
    else:
        body = (f"{title or 'Summary'}\n{url}\nSummarized on {day} by the Mac's AI.\n\n{summary}\n" if english() else
                f"{title or 'Resumo'}\n{url}\nResumido em {day} pela IA do Mac.\n\n{summary}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    job.progress(1)
    return path, title, summary
