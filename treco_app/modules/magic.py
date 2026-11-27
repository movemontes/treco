"""Pasta mágica: tudo o que chegar numa pasta escolhida é tratado sozinho, enquanto o Treco estiver aberto.

O original nunca sai do lugar. O resultado vai para a subpasta "Prontos pelo Treco", dentro da mesma pasta.
Só arquivos novos (que chegarem depois de ligar) são tratados.
"""
import os
import threading
import time

from ..core import prefs
from ..core.formats import kind_of
from ..core.log import log_error

OUT_NAME = "Prontos pelo Treco"
# (chave, nome no botão, tipos aceitos, frase que explica)
RULES = [
    ("jpg", "Fotos → JPG", {"image"}, "Fotos de qualquer formato (HEIC, PNG, WEBP…) viram JPG."),
    ("png", "Imagens → PNG", {"image"}, "Imagens viram PNG, sem perder qualidade."),
    ("img_small", "Comprimir fotos", {"image"}, "Fotos ficam bem mais leves, com a mesma cara."),
    ("mp4", "Vídeos → MP4", {"video"}, "Vídeos de qualquer formato viram MP4, que abre em todo lugar."),
    ("video_small", "Comprimir vídeos", {"video"}, "Vídeos ficam mais leves para mandar e guardar."),
    ("mp3", "Áudios → MP3", {"audio", "video"}, "Áudios (e o som dos vídeos) viram MP3."),
    ("pdf_small", "Comprimir PDFs", {"pdf"}, "PDFs ficam mais leves para mandar por e-mail."),
    ("clean", "Tirar dados escondidos", {"image", "video", "pdf"},
     "Tira localização, autor e outros dados escondidos de fotos, vídeos e PDFs."),
]
RULE_BY_KEY = {r[0]: r for r in RULES}
CHECK_EVERY = 3  # segundos


def config():
    data = prefs.get("magic") or {}
    return {"folder": data.get("folder"), "rule": data.get("rule") or "jpg", "on": bool(data.get("on"))}


def save(**changes):
    data = config()
    data.update(changes)
    prefs.put("magic", data)


def apply(rule, src, kind, out, job=None):
    from ..core.engine import compress_file, convert_file
    from . import quick
    if rule == "jpg":
        return convert_file(src, kind, "JPG", 90, out, job)
    if rule == "png":
        return convert_file(src, kind, "PNG", 90, out, job)
    if rule == "mp4":
        return convert_file(src, kind, "MP4", 90, out, job)
    if rule == "mp3":
        return convert_file(src, kind, "MP3", 90, out, job)
    if rule in ("img_small", "video_small", "pdf_small"):
        return compress_file(src, kind, "medio", out, job).path
    if rule == "clean":
        return quick.clean(src, kind, out, job).path
    raise RuntimeError("regra desconhecida")


class Watcher:
    """Olha a pasta a cada 3 segundos. Espera o arquivo terminar de chegar (tamanho parado) antes de mexer."""

    def __init__(self, on_done=None):
        self.on_done = on_done  # avisa a janela: (nome, deu certo, detalhe)
        self.known = set()
        self.sizes = {}
        self.busy = set()
        self.thread = None
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.last = None  # (hora, texto) do último arquivo tratado

    def start(self):
        cfg = config()
        if not cfg["on"] or not cfg["folder"] or not os.path.isdir(cfg["folder"]):
            return False
        self.stop()
        self.stop_flag = threading.Event()
        self.known = set(self.listing(cfg["folder"]))  # o que já estava lá fica como está
        self.sizes = {}
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stop_flag.set()

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and not self.stop_flag.is_set())

    @staticmethod
    def listing(folder):
        try:
            return [e.path for e in os.scandir(folder)
                    if e.is_file(follow_symlinks=False) and not e.name.startswith((".", "~$"))
                    and not e.name.endswith((".crdownload", ".download", ".part", ".tmp"))]
        except OSError:
            return []

    def loop(self):
        while not self.stop_flag.wait(CHECK_EVERY):
            try:
                self.check()
            except Exception as error:
                log_error("pasta mágica", error)

    def check(self):
        cfg = config()
        folder, rule = cfg["folder"], cfg["rule"]
        if not cfg["on"] or not folder or not os.path.isdir(folder):
            return
        accepted = RULE_BY_KEY.get(rule, RULES[0])[2]
        for path in self.listing(folder):
            if path in self.known or path in self.busy:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if self.sizes.get(path) != size or size == 0:  # ainda chegando: confere de novo daqui a pouco
                self.sizes[path] = size
                continue
            self.known.add(path)
            self.sizes.pop(path, None)
            if kind_of(path) not in accepted or self.already(rule, path):
                continue
            self.busy.add(path)
            threading.Thread(target=self.handle, args=(rule, path, folder), daemon=True).start()

    @staticmethod
    def already(rule, path):
        """Foto que já é JPG não precisa virar JPG de novo."""
        ext = os.path.splitext(path)[1].lower()
        return {"jpg": (".jpg", ".jpeg"), "png": (".png",), "mp4": (".mp4",), "mp3": (".mp3",)}.get(rule, ()) \
            .__contains__(ext)

    def handle(self, rule, path, folder):
        name = os.path.basename(path)
        try:
            from ..core.i18n import tr
            out = os.path.join(folder, tr(OUT_NAME))
            os.makedirs(out, exist_ok=True)
            dst = apply(rule, path, kind_of(path), out)
            text = f"{name} → {os.path.basename(dst)}"
            self.last = (time.time(), text)
            if self.on_done:
                self.on_done(name, True, os.path.basename(dst))
        except Exception as error:
            log_error(f"pasta mágica {name}", error)
            self.last = (time.time(), f"{name}: {str(error)[:40]}")
            if self.on_done:
                self.on_done(name, False, str(error)[:60])
        finally:
            self.busy.discard(path)
