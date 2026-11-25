"""Vídeo de apresentação a partir de fotos: zoom suave (efeito Ken Burns), transição seca ou suave.

Cada quadro é desenhado aqui (movimento liso, sem tremer) e o ffmpeg só grava o vídeo.
"""
import os
import random
import subprocess

from PIL import Image, ImageEnhance, ImageFilter

from ..core.i18n import tr
from ..core.files import unique_path
from ..core.formats import FFMPEG
from ..core.jobs import Job
from ..core.paths import MAC
from .quick import Result, guarded

FORMATS = {"Deitado 16:9": (1920, 1080), "Em pé 9:16": (1080, 1920), "Quadrado": (1080, 1080)}
ORDERS = ("Da lista", "Alfabética", "Aleatória")
TRANSITIONS = ("Suave", "Seca")
SECONDS = (2, 3, 5, 8)
FPS = 30
FADE = 0.8  # segundos da transição suave
ZOOM = 1.12  # quanto o zoom aproxima do começo ao fim de cada foto


def order(paths, how, seed=None):
    if how == "Alfabética":
        return sorted(paths, key=lambda p: os.path.basename(p).lower())
    if how == "Aleatória":
        paths = list(paths)
        random.Random(seed).shuffle(paths)
        return paths
    return list(paths)


def canvas(path, size, margin):
    """A foto inteira no meio, e a mesma foto desfocada preenchendo o resto (sem faixas pretas)."""
    from .paper import _open
    image = _open(path).convert("RGB")
    width, height = round(size[0] * margin), round(size[1] * margin)
    cover = max(width / image.width, height / image.height)
    back = image.resize((max(1, round(image.width * cover / 8)), max(1, round(image.height * cover / 8))), Image.Resampling.BILINEAR)
    back = back.filter(ImageFilter.GaussianBlur(6)).resize((round(image.width * cover), round(image.height * cover)), Image.Resampling.BILINEAR)
    back = ImageEnhance.Brightness(back).enhance(.55)
    board = back.crop(((back.width - width) // 2, (back.height - height) // 2,
                       (back.width - width) // 2 + width, (back.height - height) // 2 + height))
    fit = min(width / image.width, height / image.height)
    front = image.resize((max(1, round(image.width * fit)), max(1, round(image.height * fit))), Image.Resampling.LANCZOS)
    board.paste(front, ((width - front.width) // 2, (height - front.height) // 2))
    return board


class Slide:
    """Uma foto e o seu movimento: aproxima ou afasta, puxando um pouco para um lado."""

    def __init__(self, path, size, zoom, index):
        self.size, self.zoom = size, zoom
        self.board = canvas(path, size, ZOOM if zoom else 1)
        self.zoom_in = index % 2 == 0
        rng = random.Random(index * 7919 + 13)
        self.drift = (rng.uniform(-1, 1), rng.uniform(-1, 1))
        self.still = None

    def frame(self, u):
        """u vai de 0 (começo da foto) a 1 (fim)."""
        if not self.zoom:
            if self.still is None:
                self.still = self.board.resize(self.size, Image.Resampling.BILINEAR) if self.board.size != self.size else self.board
            return self.still
        u = max(0.0, min(1.0, u))
        progress = u if self.zoom_in else 1 - u
        scale = 1 - (1 - 1 / ZOOM) * progress  # que parte do quadro grande aparece
        bw, bh = self.board.size
        w, h = bw * scale, bh * scale
        room_x, room_y = (bw - w) / 2, (bh - h) / 2
        cx = bw / 2 + self.drift[0] * room_x * progress
        cy = bh / 2 + self.drift[1] * room_y * progress
        box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        return self.board.transform(self.size, Image.Transform.EXTENT, box, Image.Resampling.BILINEAR)


def encoder():
    if MAC:
        return ["-c:v", "h264_videotoolbox", "-b:v", "12M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def make(paths, seconds=3, transition="Suave", zoom=True, how="Da lista", shape="Deitado 16:9", folder=None, job=None):
    """Cria o vídeo .mp4 e devolve o Result. As fotos originais não mudam."""
    job = job or Job()
    if len(paths) < 2:
        raise RuntimeError("Use 2 ou mais fotos")
    paths = order(paths, how)
    size = FORMATS.get(shape, FORMATS["Deitado 16:9"])
    fade = FADE if transition == "Suave" else 0
    count = len(paths)
    total = count * seconds
    frames = round(total * FPS)
    folder = folder or os.path.dirname(paths[0])
    stem = os.path.splitext(os.path.basename(paths[0]))[0]
    dst = unique_path(folder, f"{stem} " + tr(f"apresentação de {count} fotos"), "mp4")
    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-"] + encoder() \
        + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", dst]

    def work():
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        job.attach(process)
        slides = {}
        black = Image.new("RGB", size)

        def slide(i):  # prepara só as fotos em uso, para não encher a memória
            if i not in slides:
                for old in [k for k in slides if k < i - 1]:
                    del slides[old]
                slides[i] = Slide(paths[i], size, zoom, i)
            return slides[i]

        try:
            for n in range(frames):
                job.check()
                t = n / FPS
                i = min(count - 1, int(t // seconds))
                start = i * seconds
                span = seconds + (fade if i < count - 1 else 0)
                image = slide(i).frame((t - start) / span)
                if i > 0 and fade and t - start < fade:  # a foto anterior ainda está sumindo
                    before = slide(i - 1).frame((t - (start - seconds)) / (seconds + fade))
                    image = Image.blend(before, image, (t - start) / fade)
                if fade:  # começa e termina escurecendo, como um filme
                    edge = min(t / .5, (total - t) / .6)
                    if edge < 1:
                        image = Image.blend(black, image, max(0.0, edge))
                process.stdin.write(image.tobytes())
                if n % 15 == 0:
                    job.progress(n / frames)
            process.stdin.close()
            error = process.stderr.read().decode("utf-8", "replace")
            if process.wait() != 0:
                raise RuntimeError(error.strip().splitlines()[-1] if error.strip() else "o ffmpeg falhou")
        except BrokenPipeError:
            job.check()
            raise RuntimeError("o ffmpeg parou no meio")
        finally:
            if process.poll() is None:
                process.kill()
            job.detach()
    guarded(dst, work)
    job.progress(1)
    return Result(dst, sum(os.path.getsize(p) for p in paths), os.path.getsize(dst))
