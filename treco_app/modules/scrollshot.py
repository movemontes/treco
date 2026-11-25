"""Captura com rolagem (só no Mac): a pessoa marca uma área e rola devagar; o Treco tira fotos seguidas
e emenda numa imagem comprida só, sem repetir pedaços.

Topo e rodapé que ficam parados durante a rolagem (barra de menu do site, por exemplo) entram uma vez só.
"""
import os
import subprocess
import tempfile
import time

import numpy
from PIL import Image

from ..core.i18n import tr
from ..core.files import unique_path

MATCH_LIMIT = 2.0  # diferença média aceita entre duas fotos na parte que se repete (0 a 255)


def grab(region, path):
    """Foto de uma área da tela, em pontos (x, y, largura, altura). Sai em resolução Retina."""
    x, y, w, h = (int(round(v)) for v in region)
    subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", "-t", "png", path], check=True, timeout=10,
                   capture_output=True)
    with Image.open(path) as image:
        return image.convert("RGB")


def profile(image):
    """Resumo de cada linha da foto (média por faixas), para comparar rápido."""
    gray = numpy.asarray(image.convert("L"), dtype=numpy.float32)
    columns = gray.shape[1] // 32 * 32 or gray.shape[1]
    return gray[:, :columns].reshape(gray.shape[0], 32, -1).mean(axis=2) if columns >= 32 else gray


def plain(diff):
    return float(diff.mean())


def trimmed(diff):
    """Ignora, em cada linha, as 8 faixas (de 32) que mais mudaram: o que está parado por cima não atrapalha."""
    if diff.ndim < 2 or diff.shape[1] < 32:
        return plain(diff)
    return float(numpy.partition(diff, 23, axis=1)[:, :24].mean())


class Stitcher:
    def __init__(self):
        self.head = None  # primeira foto
        self.last = self.last_profile = None
        self.steps = []  # (parte de baixo da foto, linha onde essa parte começa, quanto rolou)
        self.bottom = None  # rodapé parado (em linhas): o menor visto, porque linha branca parada engana
        self.lost = False  # a última foto não encaixou (rolou rápido demais ou para cima)

    @property
    def height(self):
        if self.head is None:
            return 0
        return self.head.height + sum(shift for _, _, shift in self.steps)

    def add(self, image):
        """Junta mais uma foto. Devolve True se entrou um pedaço novo."""
        current = profile(image)
        if self.head is None:
            self.head, self.last, self.last_profile = image, image, current
            return False
        if image.size != self.last.size:
            return False
        before = self.last_profile
        rows = abs(before - current).mean(axis=1)
        if rows.max() < 1.5:  # nada mudou
            self.lost = False
            return False
        still = rows < 1.5
        top = int(numpy.argmin(still))
        bottom = int(numpy.argmin(still[::-1]))
        height = len(rows)
        a, b = before[top:height - bottom], current[top:height - bottom]
        span = len(a)
        if span < 24:
            return False
        best_shift = self.match(a, b, span, plain)
        if best_shift is None:
            best_shift = self.match(a, b, span, trimmed, strict=True)  # algo parado por cima (balão de chat)
        if best_shift is None:
            self.lost = True  # não encaixa: espera a pessoa voltar um pouco
            return False
        self.lost = False
        start = height - bottom - best_shift
        self.steps.append((image.crop((0, start, image.width, height)), start, best_shift))
        self.bottom = bottom if self.bottom is None else min(self.bottom, bottom)
        self.last, self.last_profile = image, current
        return True

    @staticmethod
    def match(a, b, span, score, strict=False):
        """Quanto a página subiu entre as duas fotos, ou None se não der para ter certeza.

        strict: o encaixe tem que ser quase exato e não pode haver outro parecido longe dele."""
        diffs = numpy.array([score(abs(a[shift:] - b[:span - shift])) for shift in range(1, span - 12)])
        if not len(diffs):
            return None
        best_shift = int(diffs.argmin()) + 1
        best = float(diffs.min())
        # tem que encaixar quase perfeito, e bem melhor que os outros encaixes (texto parecido engana)
        if best > MATCH_LIMIT or best > numpy.median(diffs) * .3 or best_shift > span - 40:
            return None
        if strict:
            far = numpy.concatenate((diffs[:max(0, best_shift - 6)], diffs[best_shift + 4:]))
            if best > .5 or (len(far) and float(far.min()) < best * 2 + .3):
                return None
        return best_shift

    def result(self):
        if self.head is None:
            return None
        height = self.head.height
        bottom = self.bottom or 0
        out = Image.new("RGB", (self.head.width, self.height), "white")
        out.paste(self.head.crop((0, 0, self.head.width, height - bottom)), (0, 0))
        y = height - bottom
        for crop, start, shift in self.steps:
            top = height - bottom - shift - start
            out.paste(crop.crop((0, top, crop.width, top + shift)), (0, y))
            y += shift
        if bottom:
            out.paste(self.last.crop((0, height - bottom, self.last.width, height)), (0, y))
        return out


class Session:
    """Tira fotos da área sem parar (numa linha de trabalho separada) até mandarem parar."""

    def __init__(self, region):
        self.region = region
        self.stitcher = Stitcher()
        self.running = True
        self.error = None
        self.temp = tempfile.mkdtemp(prefix="treco_rolagem_")

    def run(self):
        path = os.path.join(self.temp, "foto.png")
        try:
            while self.running:
                started = time.monotonic()
                self.stitcher.add(grab(self.region, path))
                time.sleep(max(0.0, 0.12 - (time.monotonic() - started)))
        except Exception as error:
            self.error = error
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def stop(self):
        self.running = False


def save(image, folder, fmt="PNG"):
    ext = "jpg" if fmt == "JPG" else "png"
    path = unique_path(folder, tr("Captura com rolagem") + f" {time.strftime('%Y-%m-%d %H.%M.%S')}", ext)
    if ext == "jpg":
        image.save(path, "JPEG", quality=90, optimize=True)
    else:
        image.save(path, "PNG", optimize=True)
    return path
