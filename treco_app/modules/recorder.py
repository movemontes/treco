"""Gravador de voz e de tela do Mac, usando o ffmpeg que vai junto com o Treco.

Na primeira vez, o Mac pede permissão de Microfone e de Gravação de Tela.
"""
import os
import re
import subprocess
import threading
import time

from ..core.files import unique_path
from ..core.formats import FFMPEG
from ..core.paths import MAC

# modo: (começo do nome do arquivo, extensão, grava tela?, grava som?)
MODES = {
    "voice": ("Gravação de voz", "m4a", False, True),
    "screen": ("Gravação de tela", "mov", True, False),
    "screen_mic": ("Gravação de tela", "mov", True, True),
}
SCREEN_VIDEO = ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p"]
AUDIO = ["-c:a", "aac", "-b:a", "160k"]
RESOLUTIONS = {"Original": None, "1080p": 1080, "720p": 720}
PRIVACY = "x-apple.systempreferences:com.apple.preference.security?Privacy_"


def available():
    return MAC and bool(FFMPEG)


def screen_allowed(ask=False):
    """Diz se o Mac deixa gravar a tela. Com ask=True, mostra o pedido de permissão do Mac."""
    try:
        import Quartz
        if Quartz.CGPreflightScreenCaptureAccess():
            return True
        if ask:
            Quartz.CGRequestScreenCaptureAccess()
        return False
    except Exception:
        return True  # sem como perguntar: tenta gravar mesmo assim


def open_privacy(what):
    """Abre o lugar dos Ajustes onde se libera o microfone ("Microphone") ou a tela ("ScreenCapture")."""
    subprocess.Popen(["open", PRIVACY + what])


def default_folder():
    return os.path.expanduser("~/Desktop")


_devices = {"at": 0, "value": ([], [])}


def devices(fresh=False):
    """Telas e microfones que o Mac oferece: ([nomes das telas], [nomes dos microfones])."""
    if not fresh and time.monotonic() - _devices["at"] < 20:
        return _devices["value"]
    screens, mics, section = [], [], None
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                             capture_output=True, text=True, timeout=15).stderr
    except Exception:
        out = ""
    for line in out.splitlines():
        if "video devices" in line:
            section = screens
        elif "audio devices" in line:
            section = mics
        else:
            match = re.search(r"\] \[(\d+)\] (.+?)(?:\s+\[uid:.*)?$", line)
            if match and section is not None:
                name = match[2].strip()
                if section is mics or name.startswith("Capture screen"):  # câmeras ficam de fora
                    section.append(name)
    _devices.update(at=time.monotonic(), value=(screens, mics))
    return screens, mics


def screen_label(name):
    """ "Capture screen 0" vira "Tela 1"."""
    match = re.match(r"Capture screen (\d+)", name)
    return f"Tela {int(match[1]) + 1}" if match else name


def options():
    """As escolhas do botão direito, com o que vale se nada foi escolhido."""
    from ..core import prefs
    return {key: prefs.get("rec_" + key) for key in ("resolution", "fps", "cursor", "clicks", "mic", "screen")}


def input_name(mode, chosen):
    """O que o ffmpeg recebe no -i: "tela:microfone", pelo nome (o número muda quando liga um iPhone)."""
    _, _, video, audio = MODES[mode]
    screens, mics = devices() if (video and chosen.get("screen")) or (audio and chosen.get("mic")) else ([], [])
    screen = chosen.get("screen") if chosen.get("screen") in screens else "Capture screen 0"
    mic = chosen.get("mic") if chosen.get("mic") in mics else "default"
    return f"{screen if video else 'none'}:{mic if audio else 'none'}"


class Recording:
    def __init__(self, mode, folder=None, chosen=None):
        self.mode = mode
        chosen = dict(options() if chosen is None else chosen)
        self.folder = folder or chosen.get("folder") or default_folder()
        name, self.ext, video, audio = MODES[mode]
        from ..core.i18n import tr
        name = tr(name)
        self.name = f"{name} {time.strftime('%Y-%m-%d %H.%M.%S')}"
        self.temp = os.path.join(self.folder, f".treco_gravando_{os.getpid()}_{int(time.time())}.{self.ext}")
        fps = str(int(chosen.get("fps") or 30))
        screen_input, video_out = [], []
        if video:
            screen_input = ["-capture_cursor", "1" if chosen.get("cursor", True) else "0",
                            "-capture_mouse_clicks", "1" if chosen.get("clicks") else "0", "-framerate", fps]
            video_out = SCREEN_VIDEO + ["-r", fps]
            height = RESOLUTIONS.get(chosen.get("resolution"))
            if height:  # só diminui: uma tela menor que isso fica como está
                video_out = ["-vf", f"scale=-2:'min(ih,{height})'"] + video_out
        self.args = [FFMPEG, "-hide_banner", "-nostats", "-y", "-f", "avfoundation"] + screen_input \
            + ["-i", input_name(mode, chosen)] + video_out + (AUDIO if audio else []) + [self.temp]
        self.process = None
        self.started = None
        self.log = []

    def start(self):
        os.makedirs(self.folder, exist_ok=True)
        self.process = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
        self.started = time.monotonic()
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        for raw in self.process.stderr:
            self.log = (self.log + [raw.decode("utf-8", "replace").strip()])[-12:]

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    def elapsed(self):
        return 0 if self.started is None else time.monotonic() - self.started

    def problem(self):
        """Motivo em palavras simples, se o ffmpeg parou sozinho."""
        text = " ".join(self.log).lower()
        if "not authorized" in text or "permission" in text or "denied" in text:
            return "O Mac não deixou gravar"
        if "input/output error" in text or "no such" in text or "could not" in text:
            return "Não achei microfone ou tela"
        return "A gravação parou sozinha"

    def stop(self):
        """Termina a gravação com calma (o arquivo fica inteiro) e devolve o caminho final."""
        if self.alive:
            try:
                self.process.stdin.write(b"q")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(5)
        if not os.path.isfile(self.temp) or os.path.getsize(self.temp) < 1000:
            if os.path.isfile(self.temp):
                os.remove(self.temp)
            raise RuntimeError(self.problem())
        final = unique_path(self.folder, self.name, self.ext)
        os.replace(self.temp, final)
        return final

    def discard(self):
        if self.alive:
            self.process.kill()
            self.process.wait(5)
        if os.path.isfile(self.temp):
            os.remove(self.temp)
