import os
"""Ícones do Treco, desenhados pixel a pixel."""
from PIL import Image, ImageDraw

from .pixel import AMBER, DARK, DEEP, GRAY, GREEN, INK, ORANGE, PAPER, PINK, PURPLE, RED, TEAL, TEALD, WHITE

COLORS = {"#": INK, "w": WHITE, "c": PAPER, "g": GRAY, "d": DARK, "p": PURPLE, "P": DEEP, "t": TEAL, "T": TEALD,
          "y": AMBER, "o": ORANGE, "r": PINK, "R": RED, "G": GREEN}

ART = {
    "floppy": """
################
#pp#wwwwwww#ppp#
#pp#wwww##w#ppp#
#pp#wwww##w#ppp#
#pp#wwwwwww#ppp#
#pp#########ppp#
#pppppppppppppp#
#pppppppppppppp#
#p############p#
#p#wwwwwwwwww#p#
#p#w########w#p#
#p#wwwwwwwwww#p#
#p#w######www#p#
#p#wwwwwwwwww#p#
#P############P#
################""",
    "folder": """
................
..#####.........
.#rrrrr#........
#rrrrrrr#######.
#rrrrrrrrrrrrr#.
#r#############.
#r#yyyyyyyyyyyy#
#r#yyyyyyyyyyyy#
#.#yyyyyyyyyyy#.
##yyyyyyyyyyyy#.
##yyyyyyyyyyyy#.
#yyyyyyyyyyyy#..
#yyyyyyyyyyyy#..
##############..
................
................""",
    "image": """
################
#wwwwwwwwwwwwww#
#w############w#
#w#tttttttttt#w#
#w#ttyyttttt t#w#""".replace(" t#w#", "t#w#") + """
#w#ttyyttttttt#w#
#w#ttttttPtttt#w#
#w#ttttttPPttt#w#
#w#tttPtPPPPtt#w#
#w#ttPPPPPPPPt#w#
#w#tPPppPPPPPP#w#
#w#PPppppPPPPP#w#
#w############w#
#wwwwwwwwwwwwww#
################
................""",
    "audio": """
.......#####....
.....##yyyy#....
...##yyyyyy#....
...#yyyy###.....
...#yy##..#.....
...#y#....#.....
...#y#....#.....
...#y#....#.....
...#y#..####....
...#y#.#yyyy#...
.###y#.#yyyy#...
#yyyy#.#yyy#....
#yyyy#..###.....
#yyy#...........
.###............
................""",
    "video": """
################
#w#w#w#w#w#w#w##
################
#d############d#
#d#pppppppppp#d#
#d#ppp#ppppp.#d#""".replace("ppppp.#d#", "pppppp#d#") + """
#d#ppp##ppppp#d#
#d#ppp###pppp#d#
#d#ppp##ppppp#d#
#d#ppp#pppppp#d#
#d#pppppppppp#d#
#d############d#
################
#w#w#w#w#w#w#w##
################
................""",
    "pdf": """
.#########......
.#wwwwwww##.....
.#wwwwwww#w#....
.#wwwwwww####...
.#wwwwwwwwww#...
#############...
#RRRRRRRRRRRR#..
#R#wR##RR###R#..
#R##RR#R#R#RR#..
#R#RR##RR##RR#..
#RRRRRRRRRRRR#..
#############...
.#wwwwwwwwww#...
.#wwwwwwwwww#...
.############...
................""",
    "doc": """
..#########.....
..#wwwwwww##....
..#w#####w#w#...
..#wwwwwww####..
..#w########w#..
..#wwwwwwwwww#..
..#w########w#..
..#wwwwwwwwww#..
..#w########w#..
..#wwwwwwwwww#..
..#w######www#..
..#wwwwwwwwww#..
..#w####wwwww#..
..#wwwwwwwwww#..
..############..
................""",
    "sheet": """
################
#TTTTTTTTTTTTTT#
#T#T##T##T##T#T#
#TTTTTTTTTTTTTT#
################
#wwww#wwww#wwww#
#wwww#wGGw#wwww#
################
#wwww#wwww#wGGw#
#wGGw#wwww#wwww#
################
#wwww#wGGw#wwww#
#wwww#wwww#wwww#
################
................
................""",
    "slide": """
.......##.......
################
#oooooooooooooo#
#ooo#######ooo.#
#ooooooooooooo.#
#oo#####oooooo.#
#ooooooooooooo.#
#oo######ooooo.#
#oooooooooooooo#
################
......#..#......
.....#....#.....
....#......#....
...#........#...
................
................""".replace("o.#", "oo#"),
    "convert": """
................
......##........
......#t#.......
#######tt#......
#tttttttttt#....
#tttttttttt#....
#######tt#......
......#t#.......
......##..##....
.........#y#....
.......##yy#####
.....#yyyyyyyyy#
.....#yyyyyyyyy#
.......##yy#####
.........#y#....
..........##....""",
    "compress": """
################
#pppppppppppppp#
################
......####......
......#gg#......
.....##gg##.....
.....#yyyy#.....
.....#yyyy#.....
..############..
..#yyyyyyyyyy#..
..#yyyyyyyyyy#..
..#yyyyyyyyyy#..
..############..
################
#pppppppppppppp#
################""",
    "edit": """
............###.
...........#rrr#
..........#wrrr#
.........#yw#r#.
........#yyy##..
.......#yyy#....
......#yyy#.....
.....#yyy#......
....#yyy#.......
...#yyy#........
..#yyy#.........
.#cyy#..........
.#cc#...........
.###............
................
################""",
    "caption": """
################
#ppppppppppppp.#
#pppppppppppppp#
#ppp#pppppppppp#
#ppp##ppppppppp#
#ppp###pppppppp#
#ppp##ppppppppp#
#ppp#pppppppppp#
#pppppppppppppp#
#p############p#
#p#w#ww#www#w#p#
#p#ww#www#www#p#
#p############p#
#pppppppppppppp#
################
................""".replace("ppp.#", "pppp#"),
    "right": """
................
.....#####......
...##ttttt##....
..#ttt###ttt#...
.#tt##...##t#.#.
.#t#.......###..
#tt#.....#####..
#t#......#ttt#..
#t#.......#t#...
#tt#.......#....
.#t#............
.#tt##...##.....
..#ttt###tt#....
...##ttttt#.....
.....#####......
................""",
    "left": """
................
......#####.....
....##ttttt##...
...#ttt###ttt#..
.#.#t##...##tt#.
..###.......#t#.
..#####.....#tt#
..#ttt#......#t#
...#t#.......#t#
....#.......#tt#
............#t#.
.....##...##tt#.
....#tt###ttt#..
.....#ttttt##...
......#####.....
................""",
    "r180": """
................
.....######.....
...##yyyyyy##...
..#yyy####yyy#..
.#yy#....#yyy#..
.#y#......####..
#yy#............
#y#.............
#y#......#####..
#yy#......#y#...
.#y#.......#....
.#yy##..........
..#yyy####......
...##yyyyy#.....
.....#####......
................""",
    "mirror": """
.......##.......
.......##.......
...#...##...#...
..##...##...##..
.#t#...##...#y#.
#tt#####.####yy#""".replace("#####.####", "####..####") + """
#tttttt#.yyyyyy#
#tttttt#.yyyyyy#
#tt#####.####yy#
.#t#...##...#y#.
..##...##...##..
...#...##...#...
.......##.......
.......##.......
................
................""".replace("t#.y", "t..y").replace("#tt#####.####yy#", "#tt####..####yy#"),
    "flip": """
.......#........
......#t#.......
.....#ttt#......
....#ttttt#.....
...####t####....
......#t#.......
................
################
................
......#y#.......
...####y####....
....#yyyyy#.....
.....#yyy#......
......#y#.......
.......#........
................""",
    "trash": """
.....######.....
....#g####g#....
.##############.
.#wwwwwwwwwwww#.
.##############.
..#gwgwgwgwgg#..
..#gwgwgwgwgg#..
..#gwgwgwgwgg#..
..#gwgwgwgwgg#..
..#gwgwgwgwgg#..
..#gwgwgwgwgg#..
..#gwgwgwgwgg#..
..#gwgwgwgwgg#..
..#dddddddddd#..
...##########...
................""",
    "disk": """
.##############.
#gggggggggggggg#
#gwwwwwwwwwwwwg#
#gwdddddddddwwg#
#gwwwwwwwwwwwwg#
#gggggggggggggg#
################
#dddddddddddddd#
#d##dd##ddddGGd#
#dddddddddddGGd#
################
.#.#.#.#.#.#.#..
................
................
................
................""",
}


ART.update({
    "trim": """
...##.......##..
...#g#.....#g#..
....#g#...#g#...
....#g#...#g#...
.....#g#.#g#....
.....#g#.#g#....
......#g#g#.....
.......#g#......
......#r#r#.....
....###...###...
...#rrr#.#rrr#..
..#r..r#.#r..r#.
..#r..r#.#r..r#.
..#rrr#...#rrr#.
...###.....###..
................""",
    "crop": """
...##...........
...##...........
##############..
##############..
...##.......##..
...##.ttttt.##..
...##.ttttt.##..
...##.ttttt.##..
...##.ttttt.##..
...##.ttttt.##..
...##.......##..
...#############
...#############
...........##...
...........##...
................""",
    "resize": """
################
#wwwwwwwwwwwwww#
#wwwwwwwww####w#
#wwwwwwwwwww##w#
#wwwwwwwwww#w#w#
#wwwwwwwww#www w#
#wwwwwwww#wwwww#
#######w#wwwwww#
#ttttt##wwwwwww#
#ttttt#wwwwwwww#
#ttttt#wwwwwwww#
#ttttt#wwwwwwww#
#ttttt#wwwwwwww#
#ttttt#wwwwwwww#
#######wwwwwwww#
################""".replace("#www w#", "#wwww#"),
    "mute": """
................
......##........
.....#y#........
....#yy#..R...R.
####yyy#...R.R..
#yyyyyy#....R...
#yyyyyy#....R...
#yyyyyy#...R.R..
####yyy#..R...R.
....#yy#........
.....#y#........
......##........
................
................
................
................""",
    "volume": """
................
......##....#...
.....#y#..#..#..
....#yy#...#..#.
####yyy#.#..#.#.
#yyyyyy#..#.#..#
#yyyyyy#..#.#..#
#yyyyyy#..#.#..#
####yyy#.#..#.#.
....#yy#...#..#.
.....#y#..#..#..
......##....#...
................
................
................
................""",
    "speed": """
................
.##.....##......
.#t#....#t#.....
.#tt#...#tt#....
.#ttt#..#ttt#...
.#tttt#.#tttt#..
.#ttttt##ttttt#.
.#tttttt#tttttt#
.#tttttt#tttttt#
.#ttttt##ttttt#.
.#tttt#.#tttt#..
.#ttt#..#ttt#...
.#tt#...#tt#....
.#t#....#t#.....
.##.....##......
................""",
    "clean": """
...........###..
..........#ddd#.
.........#ddd#..
........#ddd#...
.......#ddd#....
......#ddd#.....
.....##dd#......
....#yy###......
...#yyyyy#......
..#yyyyyyy#.....
.#y#y#y#yy#.....
#y#y#y#y#y#..t..
#########.#.ttt.
...........  t..
.t..............
ttt.............""".replace("...........  t..", ".............t.."),
    "join": """
.#####....#####.
.#ttt#....#yyy#.
.#ttt#....#yyy#.
.#ttt#....#yyy#.
.#####....#####.
...#........#...
...##......##...
...###....###...
....###..###....
.....######.....
......####......
................
...##########...
...#ppppppppp#..
...#ppppppppp#..
...###########..""",
    "split": """
################
#rrrrrr##rrrrrr#
#rwwwwr##rwwwwr#
#rrrrrr##rrrrrr#
#rwwwwr##rwwwwr#
################
.......##.......
......#..#......
.....#....#.....
....#......#....
...###....###...
.#######.#######
.#wwwww#.#wwwww#
.#w###w#.#w###w#
.#wwwww#.#wwwww#
.#######.#######""",
})


def _load(art):
    rows = [row for row in art.strip("\n").split("\n")]
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    px = image.load()
    for y, row in enumerate(rows[:16]):
        for x, char in enumerate(row[:16]):
            if char in COLORS:
                px[x, y] = COLORS[char] + (255,)
    return image


ICONS = {name: _load(art) for name, art in ART.items()}
KIND_ICON = {"image": "image", "audio": "audio", "video": "video", "pdf": "pdf", "doc": "doc", "sheet": "sheet",
             "slide": "slide", "sub": "caption"}
_disabled = {}


def icon(name):
    return ICONS[name]


def dimmed(name):
    """Versão apagada: um pixel sim, outro não, como nos sistemas antigos."""
    if name not in _disabled:
        image = ICONS[name].copy()
        px = image.load()
        for y in range(16):
            for x in range(16):
                if px[x, y][3] and (x + y) % 2:
                    px[x, y] = (0, 0, 0, 0)
        _disabled[name] = image
    return _disabled[name]


def mascot(size=32):
    """O Treco: um disquete com cara de gente."""
    im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((1, 1, 30, 30), fill=PURPLE + (255,), outline=INK + (255,))
    d.rectangle((2, 28, 29, 29), fill=DEEP + (255,))
    d.point([(30, 1), (29, 1), (30, 2)], fill=(0, 0, 0, 0))
    d.line((28, 1, 30, 3), fill=INK + (255,))
    d.rectangle((8, 1, 23, 10), fill=GRAY + (255,), outline=INK + (255,))
    d.rectangle((17, 3, 20, 8), fill=INK + (255,))
    d.rectangle((5, 14, 26, 30), fill=WHITE + (255,), outline=INK + (255,))
    d.rectangle((6, 15, 25, 16), fill=TEAL + (255,))
    d.rectangle((10, 19, 12, 22), fill=INK + (255,))
    d.rectangle((19, 19, 21, 22), fill=INK + (255,))
    d.point([(11, 19), (20, 19)], fill=WHITE + (255,))
    d.point([(8, 24), (23, 24)], fill=PINK + (255,))
    d.line((13, 25, 18, 25), fill=INK + (255,))
    d.point([(12, 24), (19, 24)], fill=INK + (255,))
    if size == 32:
        return im
    return im.resize((size, size), Image.Resampling.NEAREST)


# --- ícone brutalista do Mac: T branco com sombra preta sobre o azul
def _letter_font(pixels):
    from PIL import ImageFont
    from .pixel import FONT_FILE
    font = ImageFont.truetype(FONT_FILE, pixels)
    font.set_variation_by_axes([900, 125])
    return font


def _rounded_mask(size, radius=.225):
    from PIL import ImageDraw
    big = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=int(size * 4 * radius), fill=255)
    return big.resize((size, size), Image.LANCZOS)


MASCOTE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mascote")


def mascote(pose):
    """Uma pose do Disquetinho, o mascote (RGBA, fundo transparente)."""
    return Image.open(os.path.join(MASCOTE_DIR, pose + ".png")).convert("RGBA")


def _label_box(face):
    """Acha a etiqueta branca no pé do rosto do Disquetinho, para escrever o T nela."""
    w, h = face.size
    px = face.load()
    col = w // 2
    rows = [y for y in range(int(h * .7), h) if px[col, y][3] > 200 and min(px[col, y][:3]) > 200]
    if not rows:
        return None
    top, bottom = rows[0], rows[-1]
    mid = (top + bottom) // 2
    cols = [x for x in range(w) if px[x, mid][3] > 200 and min(px[x, mid][:3]) > 200]
    return min(cols), top, max(cols), bottom


def app_icon(size=1024):
    """Ícone do Dock e do Finder, na grade padrão do macOS (corpo de 824 em 1024): quadrado
    creme de contorno grosso e sombra dura, com o rosto do Disquetinho, como o do Pauta."""
    canvas, body, margin = 1024, 824, 100
    line, shadow = 24, 34
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    outer = body - shadow
    mask = _rounded_mask(outer)
    img.paste((10, 10, 10, 255), (margin + shadow, margin + shadow), mask)
    img.paste((10, 10, 10, 255), (margin, margin), mask)
    inner = outer - line * 2
    img.paste((253, 249, 238, 255), (margin + line, margin + line), _rounded_mask(inner, .2))
    face = mascote("rosto")
    box = _label_box(face)
    if box:
        draw = ImageDraw.Draw(face)
        x0, y0, x1, y1 = box
        pixels = (y1 - y0) * 2
        while True:  # o maior T que cabe com folga na etiqueta
            font = _letter_font(pixels)
            left, top, right, bottom = draw.textbbox((0, 0), "T", font=font)
            if bottom - top <= (y1 - y0) * .78 or pixels < 8:
                break
            pixels -= 2
        draw.text(((x0 + x1) // 2 - (left + right) // 2, (y0 + y1) // 2 - (top + bottom) // 2), "T", font=font, fill=(10, 10, 10))
    k = inner * .84 / max(face.size)
    face = face.resize((round(face.width * k), round(face.height * k)), Image.LANCZOS)
    img.alpha_composite(face, (margin + (outer - face.width) // 2, margin + (outer - face.height) // 2))
    return img if size == canvas else img.resize((size, size), Image.LANCZOS)


def menubar_icon(points=18, scale=2):
    """Ícone da barra de cima: o Disquetinho só com a janelinha e os olhos, vazados.
    É uma "template image", então o macOS pinta de preto ou branco conforme o tema."""
    n, m, cut = 512, 24, 120
    alpha = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(alpha)
    d.rounded_rectangle((m, m, n - m, n - m), 60, fill=255)
    # canto de cima à direita cortado, como num disquete
    d.polygon([(n - m - cut, m - 40), (n + 40, m - 40), (n + 40, m + cut + 40),
               (n - m + 2, m + cut + 2), (n - m - cut, m - 2)], fill=0)
    d.rounded_rectangle((150, 66, 340, 146), 14, fill=0)   # janelinha
    d.rectangle((280, 80, 314, 132), fill=255)             # trava
    for cx in (180, 332):                                  # olhos com pupila
        d.ellipse((cx - 72, 210, cx + 72, 400), fill=0)
        d.ellipse((cx - 30, 262, cx + 30, 362), fill=255)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    img.putalpha(alpha)
    size = points * scale
    pad = int(size * .07)
    small = img.resize((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(small, (pad, pad), small)
    return out
