"""Legenda rápida: transcreve sem internet e grava a legenda no vídeo.

A internet só é usada uma vez, para baixar o modelo de voz.
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections import namedtuple
from dataclasses import dataclass

from ..core.i18n import tr
from ..core.files import unique_path
from ..core.formats import FFMPEG
from ..core.jobs import Job
from ..core.paths import bundled_dirs, data_dir
from . import media

MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
MODEL_SHA1 = "465707469ff3a37a2b9b8d8f89f2f99de7299dac"
MODEL_BYTES = 147_951_465
LANGUAGES = {"Português": "pt", "Inglês": "en", "Espanhol": "es", "Automático": "auto"}
COLORS = {"Branco": "FFFFFF", "Amarelo": "FFE600", "Verde": "8BD26E", "Preto": "000000"}
POSITIONS = {"Baixo": 2, "Meio": 5, "Cima": 8}
MAX_CHARS = 72
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

Segment = namedtuple("Segment", "start end text")
Result = namedtuple("Result", "path before after")


@dataclass(frozen=True)
class Style:
    font: str = "Arial"
    size: int = 64
    color: str = "Branco"
    position: str = "Baixo"
    bold: bool = True


def tls_context():
    """Conexão segura; o Python para Mac não usa os certificados do sistema."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def model_path():
    for folder in bundled_dirs():  # modelo que já vem dentro do app
        path = os.path.join(os.path.dirname(folder), "models", "ggml-base.bin")
        if os.path.isfile(path) and os.path.getsize(path) == MODEL_BYTES:
            return path
    return os.path.join(data_dir(), "models", "ggml-base.bin")


def model_ready():
    path = model_path()
    return os.path.isfile(path) and os.path.getsize(path) == MODEL_BYTES


def ensure_model(job=None, report=None):
    job = job or Job()
    path = model_path()
    if model_ready():
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + ".part"
    digest = hashlib.sha1()
    received = 0
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "file-converter"})
    try:
        with urllib.request.urlopen(request, timeout=30, context=tls_context()) as response, open(part, "wb") as out:
            while True:
                job.check()
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if report:
                    report(received / MODEL_BYTES)
        if received != MODEL_BYTES or digest.hexdigest() != MODEL_SHA1:
            raise RuntimeError("download do modelo veio incompleto")
        os.replace(part, path)
    except OSError as error:
        raise RuntimeError("não consegui baixar o modelo; confira a internet") from error
    finally:
        if os.path.exists(part):
            os.remove(part)
    return path


def filter_path(path):
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def seconds(stamp):
    h, m, s = stamp.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_srt(text):
    items = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        match = re.search(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)", block)
        if not match:
            continue
        body = " ".join(block[match.end():].split())
        if body and not re.fullmatch(r"[\[(♪].*[\])♪]", body):
            items.append(Segment(seconds(match[1]), seconds(match[2]), body))
    return items


def split_readable(segment):
    """Divide falas longas para a legenda caber em até duas linhas."""
    if len(segment.text) <= MAX_CHARS:
        return [segment]
    parts, current = [], ""
    for word in segment.text.split():
        joined = f"{current} {word}".strip()
        if current and (len(joined) > MAX_CHARS or (current[-1] in ".!?" and len(current) > 24)):
            parts.append(current)
            current = word
        else:
            current = joined
    if current:
        parts.append(current)
    total = sum(len(p) for p in parts)
    duration = segment.end - segment.start
    out, cursor = [], segment.start
    for part in parts:
        end = cursor + duration * len(part) / total
        out.append(Segment(cursor, end, part))
        cursor = end
    return out


def whisper_threads():
    """No Mac, usar os núcleos econômicos deixa o whisper dezenas de vezes mais lento."""
    if sys.platform != "darwin":
        return []
    try:
        count = int(subprocess.check_output(["/usr/sbin/sysctl", "-n", "hw.perflevel0.physicalcpu"], text=True))
    except (OSError, ValueError, subprocess.SubprocessError):
        count = 4
    return ["-filter_threads", str(max(2, min(count, 8)))]


def transcribe(src, language="pt", job=None, report=None):
    job = job or Job()
    info = media.probe(src)
    if not info["audio"]:
        return []
    model = ensure_model(job, (lambda f: report("download", f)) if report else None)
    with tempfile.TemporaryDirectory(prefix="treco_", ignore_cleanup_errors=True) as tmp:
        out = os.path.join(tmp, "fala.srt")
        audio_filter = ("aformat=sample_rates=16000:channel_layouts=mono,"
                        f"whisper=model='{filter_path(model)}':language={language}:queue=12:"
                        f"use_gpu=false:format=srt:destination='{filter_path(out)}'")
        proxy = Job((lambda f: report("transcribe", f)) if report else None)
        proxy.cancelled = job.cancelled
        job_attach = job.attach
        proxy.attach = job_attach
        proxy.detach = job.detach
        media.run_with_progress(whisper_threads() + ["-i", src, "-map", "0:a:0", "-vn", "-af", audio_filter, "-f", "null", "-"],
                                info["duration"], proxy)
        if not os.path.exists(out):
            return []
        with open(out, encoding="utf-8", errors="replace") as f:
            parsed = parse_srt(f.read())
    limit = info["duration"] or float("inf")
    result = []
    for item in parsed:
        fixed = Segment(max(0, item.start), min(limit, max(item.end, item.start + 0.4)), item.text)
        result.extend(split_readable(fixed))
    return result


# ---------------------------------------------------------------- gravar no vídeo
def ass_time(value):
    centis = int(round(max(0, value) * 100))
    h, centis = divmod(centis, 360000)
    m, centis = divmod(centis, 6000)
    s, centis = divmod(centis, 100)
    return f"{h}:{m:02d}:{s:02d}.{centis:02d}"


def ass_color(hex_rgb):
    return f"&H00{hex_rgb[4:6]}{hex_rgb[2:4]}{hex_rgb[0:2]}".upper()


def ass_text(text):
    clean = " ".join(text.replace("\\", "/").split())
    return clean.replace("{", "(").replace("}", ")")


def build_ass(segments, style, width, height):
    short = max(1, min(width, height))
    play_x, play_y = round(width * 1080 / short), round(height * 1080 / short)
    color = COLORS[style.color]
    outline = "&H00FFFFFF" if style.color == "Preto" else "&H00000000"
    font = style.font.replace(",", " ")
    margin_v = round(play_y * 0.07)
    margin_h = round(play_x * 0.06)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_x}
PlayResY: {play_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{style.size},{ass_color(color)},&H000000FF,{outline},&H80000000,{-1 if style.bold else 0},0,0,0,100,100,0,0,1,{max(2, round(style.size * 0.075))},{max(1, round(style.size * 0.03))},{POSITIONS[style.position]},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 0,{ass_time(s.start)},{ass_time(s.end)},Default,,0,0,0,,{ass_text(s.text)}"
             for s in segments if s.text.strip()]
    return header + "\n".join(lines) + "\n"


def burn(src, segments, style, folder=None, job=None):
    job = job or Job()
    if not any(s.text.strip() for s in segments):
        raise RuntimeError("a legenda está vazia")
    info = media.probe(src)
    if not info["width"]:
        raise RuntimeError("vídeo não reconhecido")
    width, height = info["width"] // 2 * 2, info["height"] // 2 * 2
    stem = os.path.splitext(os.path.basename(src))[0] + " " + tr("legendado")
    dst = unique_path(folder or os.path.dirname(src), stem, "mp4")
    try:
        with tempfile.TemporaryDirectory(prefix="treco_", ignore_cleanup_errors=True) as tmp:
            with open(os.path.join(tmp, "legenda.ass"), "w", encoding="utf-8-sig", newline="\n") as f:
                f.write(build_ass(segments, style, width, height))
            audio = ["-c:a", "copy"] if info.get("audio_codec") in ("aac", "mp3") else ["-c:a", "aac", "-b:a", "192k"]
            media.run_with_progress(["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "0",
                                     "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,ass=legenda.ass",
                                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p"] +
                                    audio + ["-movflags", "+faststart", dst], info["duration"], job, cwd=tmp)
        job.progress(1)
        return Result(dst, os.path.getsize(src), os.path.getsize(dst))
    except BaseException:
        if os.path.isfile(dst):
            os.remove(dst)
        raise


def preview_frame(src, at, text, style, max_height=420):
    """Devolve um PNG real do vídeo com a legenda aplicada."""
    info = media.probe(src)
    width, height = info["width"] // 2 * 2, info["height"] // 2 * 2
    with tempfile.TemporaryDirectory(prefix="treco_", ignore_cleanup_errors=True) as tmp:
        sample = [Segment(0, 36000, text or "Sua legenda aparece aqui")]
        with open(os.path.join(tmp, "p.ass"), "w", encoding="utf-8-sig", newline="\n") as f:
            f.write(build_ass(sample, style, width, height))
        out = os.path.join(tmp, "p.png")
        at = max(0, min(at, max(0, info["duration"] - 0.1)))
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", src, "-frames:v", "1",
               "-vf", f"scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,ass=p.ass,scale=-2:{max_height}", out]
        result = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=30, creationflags=NO_WINDOW)
        if result.returncode != 0 or not os.path.exists(out):
            raise RuntimeError("não consegui gerar a prévia")
        with open(out, "rb") as f:
            return f.read()
