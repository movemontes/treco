"""Conta-gotas do Windows: tira uma foto da tela, mostra por cima de tudo com uma lupa e a pessoa clica
na cor. O Windows não tem um seletor pronto como o do Mac. Esc ou botão direito cancela."""
import ctypes
import tkinter as tk

from PIL import Image, ImageDraw, ImageGrab, ImageTk

ZOOM, SPAN = 9, 13  # a lupa mostra 13x13 pixels, cada um 9 vezes maior


def pick(root, done):
    """Chama done((r, g, b)) quando a pessoa clicar. Não chama nada se ela cancelar."""
    metric = ctypes.windll.user32.GetSystemMetrics
    vx, vy, vw, vh = metric(76), metric(77), metric(78), metric(79)  # a área de todos os monitores
    shot = ImageGrab.grab(all_screens=True).convert("RGB")
    top = tk.Toplevel(root)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    top.geometry(f"{vw}x{vh}+{vx}+{vy}")
    canvas = tk.Canvas(top, width=vw, height=vh, highlightthickness=0, cursor="crosshair", bd=0)
    canvas.pack()
    screen = ImageTk.PhotoImage(shot)
    canvas.create_image(0, 0, anchor="nw", image=screen)
    lens = canvas.create_image(0, 0, anchor="nw")
    keep = {"screen": screen, "lens": None}  # o Tk precisa que as imagens continuem vivas

    def color_at(x, y):
        x, y = max(0, min(shot.width - 1, x)), max(0, min(shot.height - 1, y))
        return shot.getpixel((x, y))[:3]

    def move(event):
        half = SPAN // 2
        part = shot.crop((event.x - half, event.y - half, event.x + half + 1, event.y + half + 1))
        size = SPAN * ZOOM
        big = Image.new("RGB", (size + 4, size + 30), (10, 10, 10))
        big.paste(part.resize((size, size), Image.Resampling.NEAREST), (2, 2))
        draw = ImageDraw.Draw(big)
        c = half * ZOOM + 2
        draw.rectangle((c - 1, c - 1, c + ZOOM, c + ZOOM), outline=(255, 255, 255))
        r, g, b = color_at(event.x, event.y)
        draw.rectangle((2, size + 6, 22, size + 26), fill=(r, g, b), outline=(255, 255, 255))
        draw.text((30, size + 10), f"#{r:02X}{g:02X}{b:02X}", fill=(255, 255, 255))
        keep["lens"] = ImageTk.PhotoImage(big)
        lx = event.x + 24 if event.x + 24 + big.width < vw else event.x - 24 - big.width
        ly = event.y + 24 if event.y + 24 + big.height < vh else event.y - 24 - big.height
        canvas.itemconfigure(lens, image=keep["lens"])
        canvas.coords(lens, lx, ly)

    def finish(rgb=None):
        try:
            top.grab_release()
        except tk.TclError:
            pass
        top.destroy()
        if rgb:
            done(rgb)

    canvas.bind("<Motion>", move)
    canvas.bind("<Button-1>", lambda e: finish(color_at(e.x, e.y)))
    canvas.bind("<Button-3>", lambda e: finish())
    top.bind("<Escape>", lambda e: finish())
    top.focus_force()
    try:
        top.grab_set()
    except tk.TclError:
        pass
    return top
