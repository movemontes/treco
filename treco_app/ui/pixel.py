"""Base gráfica do Treco: paleta, fonte do painel e desenho em resolução real."""
import math
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from ..core.i18n import tr
from .glyphs import glyph

# Preto, branco e um azul elétrico. Vermelho só para erro.
INK = (0, 0, 0)
COAL = (0, 0, 0)
PAPER = (255, 255, 255)
WHITE = (255, 255, 255)
GRAY = (176, 176, 176)
DARK = (92, 92, 92)
BLUE = (0, 0, 255)
PURPLE = BLUE
DEEP = INK
TEAL = WHITE
TEALD = BLUE
AMBER = BLUE
ORANGE = BLUE
PINK = BLUE
RED = (225, 0, 0)
GREEN = BLUE
BONE = WHITE
BONE_DIM = GRAY
CREAM = (253, 249, 238)  # fundo das janelas
SKY = (190, 190, 255)  # marca-texto azul clarinho embaixo dos títulos
LCD = WHITE
LCD_HI = (226, 226, 255)
LCD_LINE = INK

def mix(a, b, t):
    """Cor no meio do caminho entre a e b (t de 0 a 1)."""
    if t <= 0:
        return a
    if t >= 1:
        return b
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


_GLYPHS = (
    "0000000000 00005F0000 0007000700 147F147F14 242A7F2A12 2313086462 3649562050 0008070300 "
    "001C224100 0041221C00 2A1C7F1C2A 08083E0808 0080703000 0808080808 0000606000 2010080402 "
    "3E5149453E 00427F4000 7249494946 2141494D33 1814127F10 2745454539 3C4A494931 4121110907 "
    "3649494936 464949291E 0000140000 0040340000 0008142241 1414141414 0041221408 0201590906 "
    "3E415D594E 7C1211127C 7F49494936 3E41414122 7F4141413E 7F49494941 7F09090901 3E41415173 "
    "7F0808087F 00417F4100 2040413F01 7F08142241 7F40404040 7F021C027F 7F0408107F 3E4141413E "
    "7F09090906 3E4151215E 7F09192946 2649494932 03017F0103 3F4040403F 1F2040201F 3F4038403F "
    "6314081463 0304780403 6159494D43 007F414141 0204081020 004141417F 0402010204 4040404040 "
    "0003070800 2054547840 7F28444438 3844444428 384444287F 3854545418 00087E0902 18A4A49C78 "
    "7F08040478 00447D4000 2040403D00 7F10284400 00417F4000 7C04780478 7C08040478 3844444438 "
    "FC18242418 18242418FC 7C08040408 4854545424 04043F4424 3C4040207C 1C2040201C 3C4030403C "
    "4428102844 4C9090907C 4464544C44 0008364100 0000770000 0041360800 0201020402"
).split()
_FONT = {chr(0x20 + i): bytes.fromhex(code) for i, code in enumerate(_GLYPHS)}
_FONT.update({
    "ı": bytes.fromhex("00447C4000"), "→": bytes.fromhex("08082A1C08"), "←": bytes.fromhex("081C2A0808"),
    "°": bytes.fromhex("06090906"), "…": bytes.fromhex("4000400040"), "✓": bytes.fromhex("204020100804"),
    "×": bytes.fromhex("2214081422"), "·": bytes.fromhex("0018180000"), "−": bytes.fromhex("0808080808"),
})
_MARKS = {
    "acute": [(1, 0), (0, 1)], "grave": [(-1, 0), (0, 1)], "circ": [(0, 0), (-1, 1), (1, 1)],
    "tilde": [(-1, 1), (0, 0), (1, 1), (2, 0)], "uml": [(-1, 1), (1, 1)],
}
_ACCENTS = {}
for base, row in (("aeiou", 2), ("AEIOU", 0)):
    for letter, group in zip(base, ("áàâãä", "éèêẽë", "íìîĩï", "óòôõö", "úùûũü")):
        if base == "AEIOU":
            group = group.upper()
        for char, mark in zip(group, ("acute", "grave", "circ", "tilde", "uml")):
            _ACCENTS[char] = ("ı" if letter == "i" else letter, mark, row)

LINE = 11
_cache = {}
_tiles = {}
_scaled = {}


class _ScaledDraw:
    """Linhas finas em coordenadas lógicas, com pixels do tamanho da escala."""

    def __init__(self, gfx):
        self.g = gfx

    def line(self, xy, fill=None):
        x0, y0, x1, y1 = xy
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            self.g.dot(round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps), fill)


def _glyph(char, bold):
    if char in "mwMW@#&%":  # letras largas entupiriam com o negrito
        bold = False
    key = (char, bold)
    if key in _cache:
        return _cache[key]
    mark = None
    cedilla = char in "çÇ"
    base = "c" if char == "ç" else "C" if char == "Ç" else char
    if char in _ACCENTS:
        base, mark_name, row = _ACCENTS[char]
        mark = (_MARKS[mark_name], row)
    columns = _FONT.get(base, _FONT["?"])
    if base == " ":
        cols = [0, 0]
    else:
        cols = list(columns)
        while len(cols) > 1 and cols[0] == 0:
            cols.pop(0)
        while len(cols) > 1 and cols[-1] == 0:
            cols.pop()
    width = len(cols) + (1 if bold else 0)
    mask = Image.new("1", (max(1, width), LINE - 1), 0)
    px = mask.load()
    for x, col in enumerate(cols):
        for bit in range(8):
            if col >> bit & 1:
                px[x, 2 + bit] = 1
                if bold:
                    px[x + 1, 2 + bit] = 1
    center = (len(cols) - 1) // 2
    if mark:
        for dx, dy in mark[0]:
            x = center + dx
            if 0 <= x < width:
                px[x, mark[1] + dy] = 1
    if cedilla:
        for x, y in ((center, 9), (center + 1, 9)):
            if x < width:
                px[x, y] = 1
    result = (mask, width + 1)
    _cache[key] = result
    return result


def bitmap_width(text, bold=False, scale=1):
    return max(0, sum(_glyph(c, bold)[1] for c in text) - 1) * scale


def bitmap_fit(text, width, bold=False):
    if bitmap_width(text, bold) <= width:
        return text
    while text and bitmap_width(text + "…", bold) > width:
        text = text[:-1]
    return text + "…"


# --- fonte: Archivo, que vai dentro do app (licença livre, ver fonts/OFL.txt).
# Títulos grandes usam a versão larga; o resto usa a estreita, que ocupa menos espaço.
FONT_SIZE = 9
BASELINE = 9
SYMBOLS = "→←✓"  # desenhados à mão, porque nem toda fonte tem
FONT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Archivo-Variable.ttf")
WEIGHT, WEIGHT_BOLD, WIDTH_WIDE, WIDTH_NARROW = 500, 800, 125, 100
WIDE_SCALE = 1.8  # a partir deste tamanho o texto é título


def _wide(scale):
    return scale >= WIDE_SCALE


@lru_cache(maxsize=64)
def _font(bold, pixels, wide=False):
    try:
        if not wide and SMALL_FONT:
            return _small_font(bold, pixels)
        font = ImageFont.truetype(FONT_FILE, pixels)
        font.set_variation_by_axes([WEIGHT_BOLD if bold else WEIGHT, WIDTH_WIDE if wide else WIDTH_NARROW])
        return font
    except OSError:
        return None


# Texto pequeno: Clash Grotesk. A licença dela (ITF FFL) deixa ir dentro do app, mas não
# em repositório público, então o arquivo fica fora do Git. Sem ela, usa a Archivo normal.
SMALL_FILES = [os.path.join(os.path.dirname(FONT_FILE), name)
               for name in ("ClashGrotesk-Medium.otf", "ClashGrotesk-Semibold.otf")]
SMALL_FONT = all(os.path.exists(path) for path in SMALL_FILES)
FALLBACK = "°"  # a Clash desenha o grau pequeno demais; esse vem da Archivo


def _small_font(bold, pixels):
    return ImageFont.truetype(SMALL_FILES[1 if bold else 0], pixels)


@lru_cache(maxsize=64)
def _plain_font(bold, pixels):
    """Archivo de largura normal: usada nos símbolos que a fonte pequena não tem bons."""
    font = ImageFont.truetype(FONT_FILE, pixels)
    font.set_variation_by_axes([WEIGHT_BOLD if bold else WEIGHT, 100])
    return font


def _runs(text):
    """Separa o texto comum dos símbolos desenhados à mão ("symbol") e dos que vêm
    de outra fonte ("fallback")."""
    current = ""
    for char in text:
        kind = "symbol" if char in SYMBOLS else "fallback" if char in FALLBACK else None
        if kind:
            if current:
                yield current, "text"
                current = ""
            yield char, kind
        else:
            current += char
    if current:
        yield current, "text"


def _run_font(font, kind, bold, pixels, wide):
    """A fonte de cada trecho: a pequena empresta alguns símbolos da Archivo."""
    if kind == "fallback" and SMALL_FONT and not wide:
        return _plain_font(bold, pixels)
    return font


@lru_cache(maxsize=4096)
def _measure(text, bold, wide=False):
    font = _font(bold, FONT_SIZE * 4, wide)
    if font is None:
        return float(bitmap_width(text, bold))
    total = 0.0
    for run, kind in _runs(text):
        if kind == "symbol":
            total += bitmap_width(run, True) + 1
        else:
            total += _run_font(font, kind, bold, FONT_SIZE * 4, wide).getlength(run) / 4
    return total


def text_width(text, bold=False, scale=1):
    text = tr(text)
    return math.ceil(_measure(text, bold, _wide(scale)) * scale)


def fit(text, width, bold=False):
    text = tr(text)
    size = lambda value: math.ceil(_measure(value, bold))  # já traduzido: mede direto
    if size(text) <= width:
        return text
    while text and size(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


@lru_cache(maxsize=2048)
def _label(text, bold, pixels, wide=False):
    """Máscara suave do texto. Devolve a máscara, a folga à esquerda e a linha de base."""
    if pixels < FONT_SIZE * 4:
        # Em tamanho pequeno a fonte se alarga sozinha e passa da medida; por isso
        # desenha grande e reduz, mantendo a mesma largura que o layout calculou.
        k = math.ceil(FONT_SIZE * 4 / pixels)
        big, pad, base = _label(text, bold, pixels * k, wide)
        size = (math.ceil(big.width / k), math.ceil(big.height / k))
        return big.resize(size, Image.Resampling.LANCZOS), round(pad / k), round(base / k)
    font = _font(bold, pixels, wide)
    pad = max(2, pixels // 6)
    base = round(pixels * 1.15)
    width = math.ceil(max(_measure(text, bold, wide) * pixels / FONT_SIZE, font.getlength(text) + pixels)) + pad * 2 + 2
    mask = Image.new("L", (width, base + round(pixels * .45)), 0)
    draw = ImageDraw.Draw(mask)
    x = pad
    factor = max(1, round(pixels / FONT_SIZE))
    for run, kind in _runs(text):
        if kind == "symbol":
            shape, advance = _glyph(run, True)
            big = shape.resize((shape.width * factor, shape.height * factor), Image.Resampling.NEAREST)
            mask.paste(255, (int(x), base - 9 * factor), big)
            x += advance * factor
        else:
            face = _run_font(font, kind, bold, pixels, wide)
            draw.text((x, base), run, fill=255, font=face, anchor="ls")
            x += face.getlength(run)
    return mask, pad, base


def tile(name):
    """Padrões de meio-tom com 1 bit, repetidos sem emenda."""
    if name not in _tiles:
        rows = {"50": (0xAA, 0x55), "25": (0x88, 0x00, 0x22, 0x00), "12": (0x80, 0, 0, 0, 0x08, 0, 0, 0),
                "75": (0x77, 0xFF, 0xDD, 0xFF), "stripe": (0xFF, 0x00), "diag": (0x11, 0x22, 0x44, 0x88)}[name]
        size = 2048
        data = bytearray()
        for y in range(size):
            data.extend(bytes([rows[y % len(rows)]]) * (size // 8))
        _tiles[name] = Image.frombytes("1", (size, size), bytes(data))
    return _tiles[name]


class Gfx:
    """Tela em resolução real. As coordenadas continuam nos pixels lógicos do Treco."""

    def __init__(self, width, height, scale=1):
        self.w, self.h, self.s = width, height, scale
        self.im = Image.new("RGB", (width * scale, height * scale), COAL)
        self.raw = ImageDraw.Draw(self.im)
        self.d = self.raw if scale == 1 else _ScaledDraw(self)
        self.masks = {}

    def rect(self, x, y, w, h, fill=None, line=None):
        if w > 0 and h > 0:
            s = self.s
            self.raw.rectangle((x * s, y * s, (x + w) * s - 1, (y + h) * s - 1), fill=fill, outline=line, width=s)

    def hline(self, x, y, w, color):
        self.rect(x, y, w, 1, fill=color)

    def vline(self, x, y, h, color):
        self.rect(x, y, 1, h, fill=color)

    def dot(self, x, y, color):
        self.rect(x, y, 1, 1, fill=color)

    def pattern(self, x, y, w, h, color, name="50", offset=0):
        if w <= 0 or h <= 0:
            return
        mask = tile(name).crop(((x + offset) % 512, y % 512, (x + offset) % 512 + w, y % 512 + h))
        if self.s > 1:
            mask = mask.resize((w * self.s, h * self.s), Image.Resampling.NEAREST)
        self.im.paste(color, (x * self.s, y * self.s), mask)

    def box(self, x, y, w, h, fill, line=INK):
        """Caixa com cantos recortados, como nas telas antigas."""
        self.rect(x + 1, y, w - 2, h, fill=fill)
        self.rect(x, y + 1, w, h - 2, fill=fill)
        self.hline(x + 1, y, w - 2, line)
        self.hline(x + 1, y + h - 1, w - 2, line)
        self.vline(x, y + 1, h - 2, line)
        self.vline(x + w - 1, y + 1, h - 2, line)

    def text_w(self, text, bold=False, scale=1):
        text = tr(text)
        return bitmap_width(text, bold, scale) if self.s == 1 else text_width(text, bold, scale)

    def text(self, x, y, text, color=INK, bold=False, scale=1):
        text = tr(text)
        pixels = max(6, round(FONT_SIZE * scale * self.s))
        if self.s > 1 and _font(bold, pixels) is not None:
            if text:
                mask, pad, base = _label(text, bold, pixels, _wide(scale))
                self.im.paste(color, (x * self.s - pad, y * self.s + round(BASELINE * scale * self.s) - base), mask)
            return x + text_width(text, bold, scale) + 1
        factor = max(1, int(scale)) * self.s
        for char in text:
            mask, advance = _glyph(char, bold)
            key = (char, bold, factor)
            big = _scaled.get(key)
            if big is None:
                big = mask if factor == 1 else mask.resize((mask.width * factor, mask.height * factor), Image.Resampling.NEAREST)
                _scaled[key] = big
            self.im.paste(color, (x * self.s, y * self.s), big)
            x += advance * scale
        return x

    def center(self, x, y, w, text, color=INK, bold=False, scale=1):
        self.text(x + (w - self.text_w(text, bold, scale)) // 2, y, text, color, bold, scale)

    def right(self, x, y, text, color=INK, bold=False):
        self.text(x - self.text_w(text, bold), y, text, color, bold)

    def blit(self, image, x, y):
        """Arte em pixels lógicos: amplia sem borrar."""
        if self.s > 1:
            image = image.resize((image.width * self.s, image.height * self.s), Image.Resampling.NEAREST)
        if image.mode == "RGBA":
            self.im.paste(image.convert("RGB"), (x * self.s, y * self.s), image.getchannel("A"))
        else:
            self.im.paste(image, (x * self.s, y * self.s))

    def icon(self, name, x, y, size, color):
        """Ícone de traço em qualquer cor."""
        self.im.paste(color, (x * self.s, y * self.s), glyph(name, size * self.s))

    def put(self, image, x, y):
        """Peça já em resolução real."""
        position = (x * self.s, y * self.s)
        if image.mode == "RGBA":
            self.im.paste(image.convert("RGB"), position, image.getchannel("A"))
        else:
            self.im.paste(image, position)

    def stripes(self, x, y, w, h, color=INK):
        for row in range(y + 1, y + h - 1, 2):
            self.hline(x, row, w, color)

    def blocks(self, x, y, w, h, value, color=BLUE, back=WHITE):
        """Barra cheia, sem enfeite."""
        self.rect(x, y, w, h, fill=back, line=INK)
        self.rect(x + 1, y + 1, int((w - 2) * max(0, min(1, value))), h - 2, fill=color)

    def barber(self, x, y, w, h, phase, color=BLUE, back=WHITE):
        self.rect(x, y, w, h, fill=back, line=INK)
        for row in range(y + 1, y + h - 1):
            for col in range(x + 1, x + w - 1):
                if (col - row + phase) % 8 < 4:
                    self.dot(col, row, color)


def desktop_art(width, height):
    """Paisagem de fundo: céu em meio-tom, horizonte e grade em perspectiva."""
    g = Gfx(width, height)
    horizon = int(height * 0.40)
    g.rect(0, 0, width, horizon, fill=TEAL)
    bands = (("12", 0.46), ("25", 0.62), ("50", 0.76), ("75", 0.90))
    for index, (name, start) in enumerate(bands):
        top = int(horizon * start)
        bottom = int(horizon * (bands[index + 1][1] if index + 1 < len(bands) else 1))
        g.pattern(0, top, width, bottom - top, WHITE, name)
    g.rect(0, int(horizon * 0.97), width, horizon - int(horizon * 0.97), fill=WHITE)
    sun = width // 2 + 110
    for row in range(44):
        y = horizon - row
        half = int((44 ** 2 - row ** 2) ** 0.5)
        if row % 6 != 2:
            g.hline(sun - half, y, half * 2, AMBER if row < 26 else ORANGE)
    g.rect(0, horizon, width, 3, fill=AMBER)
    g.rect(0, horizon + 3, width, 2, fill=ORANGE)
    ground = height - horizon - 5
    g.rect(0, horizon + 5, width, ground, fill=PURPLE)
    g.pattern(0, horizon + 5 + ground // 4, width, ground // 4, DEEP, "25")
    g.pattern(0, horizon + 5 + ground // 2, width, ground // 4, DEEP, "50")
    g.rect(0, horizon + 5 + ground * 3 // 4, width, ground - ground * 3 // 4, fill=DEEP)
    vanish = width // 2
    for offset in range(-11, 12):
        color = TEAL if offset % 3 == 0 else PINK
        g.d.line((vanish + offset * 12, horizon + 5, vanish + offset * 92, height), fill=color)
    step = 3
    y = horizon + 8
    while y < height:
        g.hline(0, int(y), width, PINK)
        y += step
        step *= 1.45
    return g.im
