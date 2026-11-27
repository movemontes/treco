"""Recado de boas-vindas: aparece só na primeira vez que o Treco abre."""
import webbrowser

from ..core import prefs
from ..core.i18n import english
from . import mascot
from .pixel import AMBER, BLUE, DARK, INK, RED, text_width
from .tool_dialogs import ToolDialog

AUTHOR = "Mateus"
PIX_KEY = "e2a1f4a9-ebfe-4c3c-a531-92a0e7433f14"  # chave aleatória (PicPay): não mostra CPF nem telefone
BLESSING = "Tudo para honra e glória do Senhor!"
SPONSOR_URL = ""  # doação em dólar para quem é de fora; vazio = sem esse botão
VERSION = 4  # aumente quando mudar o recado: ele aparece de novo uma vez para quem já viu


def lines():
    """(chamada em vermelho, frase em negrito, parágrafos)."""
    if english():
        return ("HELP ME: I'VE GOT 5 MOUTHS TO FEED",
                "and I made this app for free, for you.",
                [f"Hi, I'm {AUTHOR}. Treco has no ads, needs no account and never uploads your files.",
                 "",
                 "If it makes your day a little easier, any amount helps my family a lot. "
                 "Thank you so much!"])
    return ("ME AJUDA: TENHO 5 BOCAS PRA ALIMENTAR",
            "e fiz esse app de graça pra você.",
            [f"Oi, eu sou o {AUTHOR}. O Treco não tem anúncio, não pede conta e não manda nada seu pra internet.",
             "",
             "Se ele facilitar o seu dia, qualquer valor ajuda muito aqui em casa. "
             "Obrigado de coração!"])


def wrap(text, width, bold=False, scale=1):
    """Quebra o texto em linhas que cabem na largura."""
    if not text:
        return [""]
    lines, current = [], ""
    for word in text.split():
        test = f"{current} {word}".strip()
        if current and text_width(test, bold, scale) > width:
            lines.append(current)
            current = word
        else:
            current = test
    return lines + [current]


class WelcomeDialog(ToolDialog):
    def __init__(self, app, on_close=None):
        super().__init__(app, "Treco", 320, 258, on_close)
        self.copied = False
        self.host.frame()  # desenha já, sem esperar o mouse passar por cima

    def body(self, ui):
        g = ui.g
        title, subtitle, text = lines()
        x, y = 16, 26
        width = self.dw - 2 * x
        for part in wrap(title, width, True, 1.5):
            g.text(x, y, part + "  ", RED, True, 1.5)
            y += 17
        y += 2
        for part in wrap(subtitle, width, True):
            g.text(x, y, part, INK, True)
            y += 12
        y += 8
        for line in text:
            for part in wrap(line, width):
                g.text(x, y, part, DARK)
                y += 12
        y += 8  # assinatura: foto, nome e a frase
        mascot.draw(g, "mateus", x, y, 28)
        g.text(x + 36, y + 3, AUTHOR + "  ", INK, True)
        g.text(x + 36, y + 16, BLESSING + "  ", BLUE)
        y += 30
        by = self.dh - 30
        right = self.dw - 140, by, 122, 17
        if english():
            if SPONSOR_URL:
                ui.button("later", x, by, 90, 17, "Not now", on=self.close)
                ui.button("donate", *right, "Donate", on=self.sponsor, tone=AMBER, bold=True)
            else:
                ui.button("ok", *right, "Let's go", on=self.close, tone=AMBER, bold=True)
            return
        y += 6
        g.text(x, y, "Pix (chave aleatória, PicPay):  ", INK, True)  # espaços: o último caractere não corta
        g.text(x, y + 13, PIX_KEY + "  ", BLUE)
        ui.button("later", x, by, 90, 17, "Bora usar", on=self.close)
        ui.button("pix", *right, "Copiado!" if self.copied else "Copiar chave Pix", on=self.copy_pix,
                  tone=AMBER, bold=True)

    def copy_pix(self):
        self.clipboard_clear()
        self.clipboard_append(PIX_KEY)
        self.copied = True
        self.host.invalidate()

    def sponsor(self):
        webbrowser.open(SPONSOR_URL)
        self.close()

    def close(self):
        prefs.put("welcome_seen", VERSION)
        super().close()


def show_once(app, then=None):
    """Abre o recado se a pessoa ainda não viu. Depois (ou se já viu), chama then()."""
    seen = prefs.get("welcome_seen")
    if seen is not False and isinstance(seen, int) and seen >= VERSION:
        if then:
            then()
        return None
    return WelcomeDialog(app, on_close=then)
