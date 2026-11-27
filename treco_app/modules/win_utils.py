"""Utilidades do Windows no menu do Treco: Lixeira, PC acordado, bateria, internet, Wi-Fi, liberar arquivo,
área de transferência e programas instalados.

Mesmos nomes de funções do mac_utils, para as janelas servirem aos dois sistemas.
Tudo usa o que já vem no Windows (netsh, powercfg, registro) e nada pede senha de administrador.
"""
import ctypes
import os
import re
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from ctypes import wintypes

from .mac_utils import speed_words, wifi_qr, wifi_qr_text  # noqa: F401 (iguais nos dois sistemas)

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: o app é de janela, sem isso pisca um terminal preto


def _run(args, timeout=30):
    result = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    decode = lambda raw: raw.decode("oem", "replace") if raw else ""
    return subprocess.CompletedProcess(args, result.returncode, decode(result.stdout), decode(result.stderr))


# ---------------------------------------------------------------- Lixeira
def to_trash(paths):
    """Manda para a Lixeira do Windows (dá para recuperar). Devolve quantos foram e o que não deu."""
    from win32com.shell import shell, shellcon
    flags = shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI
    moved, failed = 0, []
    for path in paths:
        path = os.path.normpath(path)
        try:
            code, aborted = shell.SHFileOperation((0, shellcon.FO_DELETE, path, None, flags, None, None))
        except Exception:
            code, aborted = 1, True
        if code == 0 and not aborted and not os.path.lexists(path):
            moved += 1
        else:
            failed.append(os.path.basename(path))
    return moved, failed


def downloads_folder():
    """A pasta Downloads de verdade (ela pode ter sido mudada de lugar nas propriedades)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            value = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
        folder = os.path.expandvars(value)
        if os.path.isdir(folder):
            return folder
    except OSError:
        pass
    return os.path.expanduser("~/Downloads")


def drives():
    """Outros discos (D:, pendrive...), sem o do sistema e sem os de rede ou de CD vazio."""
    system = os.path.splitdrive(os.path.expanduser("~"))[0].upper() + "\\"
    found = []
    for root in getattr(os, "listdrives", lambda: [])():
        kind = ctypes.windll.kernel32.GetDriveTypeW(root)
        if root.upper() != system and kind in (2, 3) and os.path.isdir(root):  # removível ou fixo
            found.append(root)
    return found


# ---------------------------------------------------------------- PC acordado
class KeepAwake:
    """Enquanto ligado, o PC e a tela não dormem. Se o Treco fechar, o Windows desfaz sozinho."""
    ES_CONTINUOUS, ES_SYSTEM, ES_DISPLAY = 0x80000000, 0x00000001, 0x00000002

    def __init__(self):
        self.on = False

    def toggle(self):
        state = self.ES_CONTINUOUS | (0 if self.on else self.ES_SYSTEM | self.ES_DISPLAY)
        if ctypes.windll.kernel32.SetThreadExecutionState(state):
            self.on = not self.on
        return self.on

    def stop(self):
        if self.on:
            self.toggle()


# ---------------------------------------------------------------- bateria
class _Power(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def _power():
    status = _Power()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
    return status


def has_battery():
    try:
        flag = _power().BatteryFlag
        return flag != 255 and not flag & 128  # 128: sem bateria; 255: não sabe
    except Exception:
        return False


def _report():
    """O relatório de bateria do próprio Windows (powercfg), em XML."""
    path = os.path.join(tempfile.mkdtemp(prefix="treco_bat_"), "bateria.xml")
    try:
        _run(["powercfg", "/batteryreport", "/xml", "/output", path], timeout=60)
        root = ET.parse(path).getroot()
    finally:
        try:
            os.remove(path)
            os.rmdir(os.path.dirname(path))
        except OSError:
            pass
    for battery in root.iter():
        if battery.tag.endswith("Battery") and any(c.tag.endswith("DesignCapacity") for c in battery):
            values = {child.tag.split("}")[-1]: (child.text or "").strip() for child in battery}
            return values
    return {}


def battery():
    if not has_battery():
        raise RuntimeError("Este PC não tem bateria")
    status = _power()
    info = {}
    try:
        info = _report()
    except Exception:
        pass
    number = lambda key: int(info[key]) if info.get(key, "").isdigit() else 0
    design, full = number("DesignCapacity"), number("FullChargeCapacity")
    capacity = min(100, round(full / design * 100)) if design and full else None
    charge = status.BatteryLifePercent if status.BatteryLifePercent <= 100 else None
    return {
        "capacity": capacity,
        "condition": "Normal" if capacity is None or capacity >= 80 else "Razoável" if capacity >= 60 else "Fraca",
        "cycles": number("CycleCount") or None,
        "charge": charge if charge is not None else "?",
        "charging": bool(status.BatteryFlag & 8),
        "plugged": status.ACLineStatus == 1,
        "temperature": None,  # o Windows não informa
    }


# ---------------------------------------------------------------- internet
SPEED_HOST = "https://speed.cloudflare.com"


class Stopper:
    """Faz o papel do processo do Mac: a janela chama poll() e terminate() para cancelar."""

    def __init__(self):
        self.event = threading.Event()

    def poll(self):
        return 0 if self.event.is_set() else None

    def terminate(self):
        self.event.set()


def _opener():
    import ssl
    import urllib.request
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


def _measure(job, seconds, stop, report, streams=4):
    """Roda job(contador) em várias conexões ao mesmo tempo por alguns segundos. Devolve Mbps."""
    moved = [0]
    lock = threading.Lock()
    end = time.monotonic() + seconds
    start = time.monotonic()

    def add(n):
        with lock:
            moved[0] += n

    def worker():
        while time.monotonic() < end and not stop.is_set():
            try:
                job(add, end, stop)
            except Exception:
                time.sleep(.2)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(streams)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(.25)
        elapsed = max(.25, time.monotonic() - start)
        report(moved[0] * 8 / elapsed / 1e6)
    elapsed = max(.25, time.monotonic() - start)
    return moved[0] * 8 / elapsed / 1e6


def speed_test(process_holder=None, progress=None):
    """Baixa e envia dados de teste da Cloudflare por uns 10 segundos cada. progress(baixar, enviar) em Mbps.
    Não manda nada do computador: o que sobe são bytes zerados."""
    import urllib.request
    stopper = Stopper()
    if process_holder is not None:
        process_holder.append(stopper)
    stop = stopper.event
    opener = _opener()
    headers = {"User-Agent": "Treco"}

    pings = []
    for _ in range(4):
        started = time.monotonic()
        try:
            opener.open(urllib.request.Request(f"{SPEED_HOST}/__down?bytes=0", headers=headers), timeout=5).read()
            pings.append((time.monotonic() - started) * 1000)
        except Exception:
            pass
    if not pings:
        raise RuntimeError("Sem internet, ou o teste falhou")

    def download(add, end, stop):
        request = urllib.request.Request(f"{SPEED_HOST}/__down?bytes=50000000", headers=headers)
        with opener.open(request, timeout=10) as response:
            while time.monotonic() < end and not stop.is_set():
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                add(len(chunk))

    blob = bytes(2_000_000)

    def upload(add, end, stop):
        request = urllib.request.Request(f"{SPEED_HOST}/__up", data=blob, headers=headers, method="POST")
        opener.open(request, timeout=15).read()
        add(len(blob))

    live = [0.0, 0.0]

    def report(i):
        def inner(value):
            live[i] = value
            if progress:
                progress(*live)
        return inner

    down = _measure(download, 10, stop, report(0))
    if stop.is_set():
        raise RuntimeError("Teste cancelado")
    live[1] = .01  # a janela troca para "Medindo o envio"
    up = _measure(upload, 10, stop, report(1))
    if stop.is_set():
        raise RuntimeError("Teste cancelado")
    if not down:
        raise RuntimeError("Sem internet, ou o teste falhou")
    ping = sorted(pings)[len(pings) // 2]
    return {"down": down, "up": up, "rpm": 0, "ping": ping,
            "feel": "Ótima" if ping < 40 else "Boa" if ping < 100 else "Lenta"}


# ---------------------------------------------------------------- Wi-Fi
def wifi_device():
    """Tem placa de Wi-Fi? (o serviço de Wi-Fi do Windows responde)"""
    try:
        return "wifi" if _run(["netsh", "wlan", "show", "interfaces"]).returncode == 0 else None
    except Exception:
        return None


def saved_networks():
    """Redes Wi-Fi guardadas no Windows. As linhas têm "nome do campo: rede", em qualquer idioma."""
    text = _run(["netsh", "wlan", "show", "profiles"]).stdout
    names, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith("---"):
            inside = True
            continue
        if inside and ":" in line:
            name = line.split(":", 1)[1].strip()
            if name and not name.startswith("<"):
                names.append(name)
    return names


_KEY = re.compile(r"^\s*(?:Key Content|Conte\S*do da Chave|Contenido de la clave|Contenu de la cl\S*)\s*:\s*(.*)$",
                  re.I | re.M)


def wifi_password(name):
    """A senha guardada da rede. Rede aberta devolve texto vazio."""
    result = _run(["netsh", "wlan", "show", "profile", f"name={name}", "key=clear"])
    if result.returncode:
        raise RuntimeError("Essa rede não está guardada")
    found = _KEY.search(result.stdout)
    if found:
        return found[1].strip()
    if re.search(r"(Authentication|Autentica\S*o)\s*:\s*(Open|Aberta|Abrir)", result.stdout, re.I):
        return ""
    raise RuntimeError("O Windows não mostrou a senha")


# ---------------------------------------------------------------- liberar arquivo baixado
def _zone(path):
    return path + ":Zone.Identifier"


def blocked(path):
    return os.path.exists(_zone(path))


def unblock(path):
    """Tira a marca de "baixado da internet" (o que faz o Windows dizer que protegeu o computador)."""
    if not os.path.isfile(path):
        raise RuntimeError("Escolha um arquivo")
    was = blocked(path)
    if was:
        try:
            os.remove(_zone(path))
        except OSError:
            raise RuntimeError("Não consegui liberar esse arquivo")
    return was


# ---------------------------------------------------------------- área de transferência
_user32 = ctypes.windll.user32
_user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
# formatos que gerenciadores de senha usam para dizer "não guarde isto"
SECRET_FORMATS = ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore")
_last_count = None


def pasteboard_change():
    """(número da mudança, texto ou None), igual ao do Mac."""
    import win32clipboard
    global _last_count
    count = _user32.GetClipboardSequenceNumber()
    if count == _last_count:  # nada mudou: nem abre a área de transferência (não atrapalha outros programas)
        return count, None
    _last_count = count
    for name in SECRET_FORMATS:
        if _user32.IsClipboardFormatAvailable(_user32.RegisterClipboardFormatW(name)):
            return count, None
    history = _user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
    for _ in range(5):  # outro programa pode estar com a área de transferência aberta agora
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception:
            time.sleep(.05)
    else:
        return count, None
    try:
        if win32clipboard.IsClipboardFormatAvailable(history):
            data = win32clipboard.GetClipboardData(history)
            if data and data[:1] == b"\x00":  # o programa pediu para não entrar no histórico
                return count, None
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return count, win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return count, None
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_text(text):
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


# ---------------------------------------------------------------- programas instalados
_UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def installed_programs():
    """Programas que aparecem em "Adicionar ou remover programas", com o desinstalador de cada um."""
    import winreg
    places = [(winreg.HKEY_CURRENT_USER, 0), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
              (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)]
    found = {}
    for hive, view in places:
        try:
            base = winreg.OpenKey(hive, _UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with base:
            for i in range(winreg.QueryInfoKey(base)[0]):
                try:
                    with winreg.OpenKey(base, winreg.EnumKey(base, i)) as key:
                        get = lambda name: _value(key, name)
                        name, command = get("DisplayName"), get("UninstallString")
                        if not name or not command or get("SystemComponent") == 1 or get("ParentKeyName"):
                            continue
                        if str(get("ReleaseType") or "").lower() in ("update", "hotfix", "security update"):
                            continue
                        size = get("EstimatedSize")
                        found.setdefault(name.lower(), {
                            "name": name.strip(), "command": command, "publisher": (get("Publisher") or "").strip(),
                            "size": int(size) * 1024 if isinstance(size, int) else 0,
                            "version": str(get("DisplayVersion") or "")})
                except OSError:
                    continue
    return sorted(found.values(), key=lambda p: p["name"].lower())


def _value(key, name):
    import winreg
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def run_uninstaller(program):
    """Abre o desinstalador do próprio programa. É ele quem pergunta e remove; o Treco não apaga nada."""
    command = program["command"]
    if re.match(r"(?i)^msiexec(\.exe)?\s", command):
        command = re.sub(r"(?i)/I\s*\{", "/X{", command)  # alguns pedem "instalar" em vez de "remover"
    subprocess.Popen(command, shell=True)


def running_from_treco(program):
    """O Treco não desinstala a si mesmo por aqui (fecharia no meio)."""
    return program["name"].lower().startswith("treco")
