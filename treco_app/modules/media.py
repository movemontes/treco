"""Conversão de áudio e vídeo com o ffmpeg."""
import re
import subprocess
import sys
import tempfile

from ..core.formats import FFMPEG
from ..core.jobs import Cancelled

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def run_ffmpeg(args):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + args
    p = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "ffmpeg falhou")


APPLE_VIDEO = {"h264", "hevc"}  # o que o QuickTime e o iPhone abrem
APPLE_AUDIO = {"aac", "mp3", "alac"}


def codecs(src):
    """Codecs de vídeo e de áudio do arquivo, em minúsculas (None quando não existe)."""
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", src], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    video = re.search(r"Stream #.*Video: (\w+)", p.stderr)
    audio = re.search(r"Stream #.*Audio: (\w+)", p.stderr)
    return (video[1].lower() if video else None), (audio[1].lower() if audio else None)


H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k"]


def convert(src, dst, fmt, is_video, job=None):
    if not FFMPEG:
        raise RuntimeError("ffmpeg não encontrado (instale: winget install ffmpeg)")
    i = ["-i", src]
    run = run_ffmpeg
    if job:
        duration = probe(src)["duration"]
        run = lambda arguments: run_with_progress(arguments, duration, job)
    if is_video and fmt in ("MP4", "MOV", "MKV"):
        # tenta só trocar o "envelope" (instantâneo); se não der, recodifica
        # (MP4 e MOV só copiam se o QuickTime conseguir abrir o resultado)
        fast = ["-movflags", "+faststart"] if fmt != "MKV" else []
        video, audio = codecs(src)
        apple = video in APPLE_VIDEO and (audio is None or audio in APPLE_AUDIO)
        if fmt == "MKV" or apple:
            tag = ["-tag:v", "hvc1"] if video == "hevc" and fmt != "MKV" else []
            try:
                run(i + ["-map", "0:v:0", "-map", "0:a?", "-c", "copy"] + tag + fast + [dst])
                return
            except RuntimeError:
                pass
        run(i + H264 + fast + [dst])
    elif is_video and fmt == "WEBM":
        run(i + ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0",
                        "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1",
                        "-c:a", "libopus", "-b:a", "128k", dst])
    elif is_video and fmt == "AVI":
        run(i + ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3", dst])
    elif is_video and fmt == "GIF":
        run(i + ["-vf", "fps=12,scale='min(640,iw)':-1:flags=lanczos,"
                        "split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0", dst])
    else:  # áudio (ou extrair áudio de vídeo)
        codec = {
            "MP3": ["-c:a", "libmp3lame", "-q:a", "2"],
            "WAV": ["-c:a", "pcm_s16le"],
            "M4A": ["-c:a", "aac", "-b:a", "192k"],
            "FLAC": ["-c:a", "flac"],
            "OGG": ["-c:a", "libvorbis", "-q:a", "5"],
            "OPUS": ["-c:a", "libopus", "-b:a", "128k"],
            "AIFF": ["-c:a", "pcm_s16be"],
        }[fmt]
        run(i + ["-vn"] + codec + [dst])


def probe(src):
    """Duração, tamanho do vídeo e se existe áudio."""
    if not FFMPEG:
        raise RuntimeError("ffmpeg não encontrado")
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", src], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    text = p.stderr
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]) if d else 0.0
    v = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", text)
    width, height = int(v[1]) if v else 0, int(v[2]) if v else 0
    turn = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", text)
    if turn and round(abs(float(turn[1]))) % 180 == 90:  # vídeo gravado em pé
        width, height = height, width
    codec = re.search(r"Stream #.*Audio: (\w+)", text)
    return {"duration": duration, "width": width, "height": height, "audio": bool(codec),
            "audio_codec": codec[1] if codec else None}


def run_with_progress(args, duration, job=None, start=0.0, span=1.0, cwd=None):
    """Roda o ffmpeg informando o progresso e permitindo cancelar."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-nostats", "-progress", "pipe:1"] + args
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        if job:
            job.attach(proc)
        try:
            for line in proc.stdout:
                if job and duration > 0 and line.startswith("out_time_us="):
                    value = line.split("=", 1)[1].strip()
                    if value.lstrip("-").isdigit():
                        job.progress(start + span * (int(value) / 1_000_000 / duration))
            proc.wait()
        finally:
            proc.stdout.close()
            if job:
                job.detach()
        if job and job.cancelled.is_set():
            raise Cancelled()
        if proc.returncode != 0:
            err.seek(0)
            lines = err.read().strip().splitlines()
            raise RuntimeError(lines[-1] if lines else "ffmpeg falhou")
