"""Baixa vídeos e áudios da internet com o yt-dlp, sem login e sem usar dados do navegador."""
import os
import re
import shutil
import tempfile
from collections import namedtuple
from urllib.parse import urlparse

from ..core.files import unique_path
from ..core.formats import FFMPEG
from ..core.jobs import Cancelled, Job
from ..core.paths import find_tool

AUDIO = "Áudio"
DOWNLOAD_SPAN = .85  # o resto da barra fica para a conversão, quando ela for necessária
QUALITIES = {"Melhor": 1080, "720p": 720, "480p": 480, AUDIO: None}
Result = namedtuple("Result", "path title total")


class _Quiet:
    """O yt-dlp fala muito; os erros chegam pelas exceções."""

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def clean_url(text):
    """Devolve o link pronto para usar, ou None se não for um endereço da web."""
    text = (text or "").strip()
    if not text or any(c.isspace() for c in text):
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlparse(text)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or "." not in (parts.hostname or ""):
        return None
    return text


def site_name(url):
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def video_format(height):
    """Prefere H.264 com AAC em MP4, que abre em qualquer player e editor."""
    limit = f"[height<={height}]"
    return (f"bv*{limit}[vcodec^=avc1]+ba[ext=m4a]/b{limit}[ext=mp4][vcodec^=avc1]/"
            f"bv*{limit}+ba/b{limit}/bv*+ba/b")


def safe_name(title):
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', " ", title or "")
    name = " ".join(name.split()).strip(" .")
    return name[:100].strip(" .") or "video"


def friendly(error):
    text = str(error).lower()
    if "unsupported url" in text or "no video could be found" in text or "no video formats" in text:
        return "Não achei vídeo nesse link"
    if any(k in text for k in ("login", "logged-in", "sign in", "cookies", "private", "rate-limit", "age-restricted", "your age")):
        return "Esse vídeo exige login"
    if any(k in text for k in ("not available", "unavailable", "removed", "deleted", "404")):
        return "Vídeo indisponível"
    if any(k in text for k in ("country", "geo", "region")):
        return "Bloqueado neste país"
    if any(k in text for k in ("drm", "protected")):
        return "Vídeo protegido contra cópia"
    if any(k in text for k in ("timed out", "network", "connection", "resolve", "unreachable")):
        return "Sem conexão com o site"
    if "no space" in text:
        return "Sem espaço no disco"
    return "Não consegui baixar"


def options(quality, folder, hook):
    settings = {
        "outtmpl": os.path.join(folder, "download.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _Quiet(),
        "progress_hooks": [hook],
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 20,
        "cachedir": False,
        "overwrites": True,
    }
    if FFMPEG:
        settings["ffmpeg_location"] = os.path.dirname(FFMPEG)
    deno = find_tool("deno")
    if deno:  # o YouTube exige um interpretador de JavaScript
        settings["js_runtimes"] = {"deno": {"path": deno}}
    height = QUALITIES[quality]
    if height is None:
        settings["format"] = "ba/b"
        settings["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        settings["format"] = video_format(height)
        settings["merge_output_format"] = "mp4"
    return settings


def make_playable(source, job):
    """Sites como Instagram e Facebook às vezes entregam VP9, AV1 ou Opus, que o QuickTime
    não abre. Nesses casos recodifica para H.264 + AAC; senão devolve o arquivo como veio."""
    from .media import APPLE_AUDIO, APPLE_VIDEO, codecs, probe, run_with_progress
    if not FFMPEG:
        return source
    video, audio = codecs(source)
    if video is None:
        return source
    good_video, good_audio = video in APPLE_VIDEO, audio is None or audio in APPLE_AUDIO
    if good_video and good_audio and source.lower().endswith(".mp4"):
        return source
    target = os.path.splitext(source)[0] + ".playable.mp4"
    args = ["-i", source, "-map", "0:v:0", "-map", "0:a:0?"]
    args += ["-c:v", "copy"] if good_video else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                                  "-pix_fmt", "yuv420p"]
    args += ["-c:a", "copy"] if good_audio else ["-c:a", "aac", "-b:a", "192k"]
    if good_video and video == "hevc":
        args += ["-tag:v", "hvc1"]
    args += ["-movflags", "+faststart", target]
    run_with_progress(args, probe(source)["duration"], job, start=DOWNLOAD_SPAN, span=1 - DOWNLOAD_SPAN)
    os.remove(source)
    return target


def fetch(url, quality, folder, job=None):
    """Baixa numa pasta oculta e só coloca o arquivo no destino quando estiver completo."""
    import yt_dlp
    job = job or Job()
    finished = []

    def hook(data):
        job.check()
        info = data.get("info_dict") or {}
        parts = max(1, len(info.get("requested_formats") or ()))
        name = data.get("filename")
        if data.get("status") == "finished":
            if name not in finished:
                finished.append(name)
            job.progress(DOWNLOAD_SPAN * min(1, len(finished) / parts))
        elif data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total:
                job.progress(DOWNLOAD_SPAN * min(1, (len(finished) + data.get("downloaded_bytes", 0) / total) / parts))

    os.makedirs(folder, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".treco_download_", dir=folder)
    try:
        job.check()
        with yt_dlp.YoutubeDL(options(quality, work, hook)) as client:
            info = client.extract_info(url, download=True)
        job.check()
        total = 1
        if info and info.get("entries") is not None:
            entries = [e for e in info["entries"] if e]
            total = info.get("playlist_count") or len(entries) or 1
            info = entries[0] if entries else info
        files = [os.path.join(work, n) for n in os.listdir(work) if not n.endswith((".part", ".ytdl", ".temp"))]
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            raise RuntimeError("no video could be found")
        source = max(files, key=os.path.getsize)
        if QUALITIES[quality] is not None:
            source = make_playable(source, job)
        title = (info or {}).get("title") or site_name(url)
        ext = os.path.splitext(source)[1].lstrip(".") or "mp4"
        target = unique_path(folder, safe_name(title), ext)
        os.replace(source, target)
        job.progress(1)
        return Result(target, title, total)
    except Cancelled:
        raise
    except yt_dlp.utils.DownloadCancelled as error:
        raise Cancelled() from error
    finally:
        shutil.rmtree(work, ignore_errors=True)
