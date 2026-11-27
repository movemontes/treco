"""O Disquetinho, mascote do Treco: poses, tour da primeira vez e balões de dica."""
import os
from functools import lru_cache

from PIL import Image

from ..core import prefs
from ..core.i18n import tr
from .pixel import BLUE, DARK, INK, WHITE, text_width

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mascote")
TOUR_VERSION = 1  # aumente quando o tour mudar: ele aparece de novo uma vez


def enabled():
    """A pessoa pode desligar o Disquetinho (menu do T)."""
    return prefs.get("mascote") is not False


def toggle():
    prefs.put("mascote", not enabled())


@lru_cache(maxsize=64)
def sprite(pose, height, scale):
    """A pose já no tamanho real da tela (altura em pixels lógicos)."""
    image = Image.open(os.path.join(FOLDER, pose + ".png")).convert("RGBA")
    h = height * scale
    w = round(image.width * h / image.height)
    return image.resize((w, h), Image.Resampling.LANCZOS)


def width(pose, height, scale):
    return -(-sprite(pose, height, scale).width // scale)


def draw(g, pose, x, y, height):
    """Desenha a pose com o canto de cima à esquerda em (x, y)."""
    image = sprite(pose, height, g.s)
    g.im.paste(image.convert("RGB"), (x * g.s, y * g.s), image.getchannel("A"))


def wrap(text, limit, bold=False, scale=1):
    lines, current = [], ""
    for word in tr(text).split():
        test = f"{current} {word}".strip()
        if current and text_width(test, bold, scale) > limit:
            lines.append(current)
            current = word
        else:
            current = test
    return lines + [current] if current else lines


def balloon(g, x, y, w, title, text):
    """Balão branco de borda preta e sombra dura. Devolve a altura usada pelo texto."""
    lines = wrap(text, w - 20)
    h = 16 + (14 if title else 0) + len(lines) * 12 + 6
    g.rect(x + 3, y + 3, w, h, fill=INK)
    g.rect(x, y, w, h, fill=WHITE, line=INK)
    ty = y + 9
    if title:
        g.text(x + 10, ty, tr(title), INK, True, 1.1)
        ty += 15
    for line in lines:
        g.text(x + 10, ty, line, DARK)
        ty += 12
    return h


def balloon_height(w, title, text):
    return 16 + (14 if title else 0) + len(wrap(text, w - 20)) * 12 + 6


# --- tour: (pose, alvo, título, texto). O alvo é uma chave que a janela sabe onde fica.
TOUR = [
    ("oi", None, "Oi! Eu sou o Disquetinho.",
     "Vou te mostrar o Treco em poucos passos. Dá pra pular quando quiser."),
    ("aponta-esquerda", "rail", "Os assuntos ficam aqui.",
     "Converter, comprimir, editar, vídeo, imagem, documentos, baixar e utilidades."),
    ("normal", "add", "Comece pelos arquivos.",
     "Arraste arquivos para a janela ou clique aqui para escolher."),
    ("trabalhando", "main", "Depois, é só clicar.",
     "Escolha uma ação e o Treco faz o resto. O botão direito mostra mais opções."),
    ("oi", "dest", "Onde o pronto vai parar.",
     "Escolha a pasta. O original nunca é movido nem apagado."),
    ("pensando", "logo", "Mais coisas no T.",
     "Clique no T para ver o menu do Treco, rever este tour e ligar ou desligar o Disquetinho."),
    ("comemorando", None, "Pronto!",
     "Dica: segure Shift ao arrastar um arquivo no Finder para usar a Roda do Shift. Bom proveito!"),
]


def tour_pending():
    seen = prefs.get("tour_seen")
    return not (isinstance(seen, int) and not isinstance(seen, bool) and seen >= TOUR_VERSION)


def tour_done():
    prefs.put("tour_seen", TOUR_VERSION)


# --- dicas ao parar o mouse em cima (com o rosto do Disquetinho, se ligado)
TIPS = {
    "logo": "Menu do Treco: tour, Disquetinho, iniciar com o Mac e mais.",
    "open": "Abre a pasta onde ficam os arquivos prontos.",
    "dest": "Escolhe a pasta onde salvar o pronto.",
    "clear": "Limpa a lista. Nenhum arquivo é apagado.",
    "add": "Escolha arquivos ou arraste para a janela.",
}
TIP_DELAY = .7  # segundos parado em cima antes do balão aparecer
