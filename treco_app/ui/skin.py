"""Peças físicas do Treco: carrega, estica sem deformar os cantos e guarda prontas."""
import os
from functools import lru_cache

from PIL import Image, ImageChops

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skin")

# Parte de cada peça que forma o canto, em relação ao menor lado da imagem.
CORNERS = {
    "f01_carcaca": .10, "f02_baia": .17, "f03_visor_lcd": .25, "f04_entrada_disquete": .30, "f05_campo_texto": .30,
    "k01_tecla_grande": .30, "k02_tecla_modo": .34, "k03_tecla_pequena": .38, "k04_tecla_laranja": .38,
    "k05_botao_mini": .42, "c01_trilho_fader": .46, "c03_barra_rolagem": .49,
}


@lru_cache(maxsize=None)
def source(name):
    with Image.open(os.path.join(FOLDER, name + ".png")) as image:
        return image.convert("RGBA")


def _base(name):
    for key in CORNERS:
        if name.startswith(key):
            return key
    return name


@lru_cache(maxsize=768)
def piece(name, width, height):
    """Peça inteira no tamanho pedido."""
    return source(name).resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)


@lru_cache(maxsize=768)
def nine(name, width, height, corner):
    """Estica só o miolo e as bordas; os quatro cantos ficam intactos."""
    image = source(name)
    sw, sh = image.size
    cut = max(1, int(min(sw, sh) * CORNERS[_base(name)]))
    corner = max(1, min(corner, width // 2, height // 2))
    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    xs = ((0, cut, 0, corner), (cut, sw - cut, corner, width - corner), (sw - cut, sw, width - corner, width))
    ys = ((0, cut, 0, corner), (cut, sh - cut, corner, height - corner), (sh - cut, sh, height - corner, height))
    for sy0, sy1, dy0, dy1 in ys:
        for sx0, sx1, dx0, dx1 in xs:
            if dx1 > dx0 and dy1 > dy0 and sx1 > sx0 and sy1 > sy0:
                part = image.crop((sx0, sy0, sx1, sy1)).resize((dx1 - dx0, dy1 - dy0), Image.Resampling.LANCZOS)
                out.paste(part, (dx0, dy0))
    return out


@lru_cache(maxsize=64)
def texture(name, width, height):
    """Textura repetida até cobrir a área."""
    base = source(name).convert("RGB")
    out = Image.new("RGB", (width, height))
    for y in range(0, height, base.height):
        for x in range(0, width, base.width):
            out.paste(base, (x, y))
    return out


_shaded = {}


def shaded(image, color, amount):
    """Tinge a peça mantendo o relevo, para hover, seleção e desativado."""
    key = (id(image), color, amount)
    found = _shaded.get(key)
    if found is not None and found[0] is image:  # guardar a original impede o id de ser reaproveitado
        return found[1]
    if len(_shaded) > 512:
        _shaded.clear()
    rgb = image.convert("RGB")
    tint = ImageChops.multiply(rgb, Image.new("RGB", image.size, color))
    out = Image.blend(rgb, tint, amount).convert("RGBA")
    out.putalpha(image.getchannel("A"))
    _shaded[key] = (image, out)
    return out
