"""Utilidades do Mac no menu do Treco: manter acordado, bateria, internet, Wi-Fi e app bloqueado.

Tudo usa programas que já vêm no macOS. Nada disso existe no Windows.
"""
import json
import os
import plistlib
import re
import subprocess

from PIL import Image


def _run(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- manter acordado
class KeepAwake:
    """Enquanto ligado, o Mac e a tela não dormem (o mesmo que o comando caffeinate)."""

    def __init__(self):
        self.process = None

    @property
    def on(self):
        return self.process is not None and self.process.poll() is None

    def toggle(self):
        if self.on:
            self.stop()
        else:
            # -w: se o Treco fechar de qualquer jeito, o caffeinate para junto
            self.process = subprocess.Popen(["caffeinate", "-d", "-i", "-w", str(os.getpid())])
        return self.on

    def stop(self):
        if self.on:
            self.process.terminate()
        self.process = None


# ---------------------------------------------------------------- bateria
def has_battery():
    try:
        data = plistlib.loads(_run(["ioreg", "-rn", "AppleSmartBattery", "-a"]).stdout.encode())
        return bool(data and data[0].get("BatteryInstalled"))
    except Exception:
        return False


def battery_from(raw, power):
    """Monta o resumo a partir do ioreg (raw) e do Informações do Sistema (power)."""
    health_info = power.get("sppower_battery_health_info", {}) if power else {}
    charge_info = power.get("sppower_battery_charge_info", {}) if power else {}
    design = raw.get("DesignCapacity") or 0
    real = raw.get("AppleRawMaxCapacity") or raw.get("NominalChargeCapacity") or 0
    capacity = health_info.get("sppower_battery_health_maximum_capacity")
    if capacity:
        capacity = int(str(capacity).rstrip("%"))
    elif design and real:
        capacity = min(100, round(real / design * 100))
    condition = {"Good": "Normal", "Normal": "Normal", "Fair": "Razoável", "Poor": "Fraca",
                 "Check Battery": "Verificar", "Service Recommended": "Trocar em breve"}
    status = health_info.get("sppower_battery_health")
    temperature = raw.get("Temperature")
    return {
        "capacity": capacity,  # quanto a bateria ainda guarda, comparada a uma nova (%)
        "condition": condition.get(status, status or ("Normal" if capacity and capacity >= 80 else "Verificar")),
        "cycles": health_info.get("sppower_battery_cycle_count") or raw.get("CycleCount"),
        "charge": charge_info.get("sppower_battery_state_of_charge") or raw.get("CurrentCapacity"),
        "charging": bool(raw.get("IsCharging")),
        "plugged": bool(raw.get("ExternalConnected")),
        "temperature": round(temperature / 100) if temperature else None,
    }


def battery():
    data = plistlib.loads(_run(["ioreg", "-rn", "AppleSmartBattery", "-a"]).stdout.encode())
    raw = data[0] if data else {}
    if not raw.get("BatteryInstalled"):
        raise RuntimeError("Este Mac não tem bateria")
    power = {}
    try:
        items = json.loads(_run(["system_profiler", "SPPowerDataType", "-json"]).stdout)["SPPowerDataType"]
        power = next((i for i in items if "sppower_battery_health_info" in i), {})
    except Exception:
        pass
    return battery_from(raw, power)


# ---------------------------------------------------------------- internet
_LIVE = re.compile(r"Downlink:\s*([\d.]+)\s*([KMG])bps.*?Uplink:\s*([\d.]+)\s*([KMG])bps")
_UNIT = {"K": .001, "M": 1, "G": 1000}


def _mbps(value, unit):
    return float(value) * _UNIT.get(unit, 1)


def _summary(text, pattern):
    return re.search(pattern, text)


def speed_test(process_holder=None, progress=None):
    """Teste da própria Apple (networkQuality), primeiro baixando e depois enviando.
    Roda num terminal falso para ler os números ao vivo: progress(baixar, enviar) em Mbps."""
    import pty
    import select
    import time
    master, slave = pty.openpty()
    process = subprocess.Popen(["networkQuality", "-s"], stdin=subprocess.DEVNULL, stdout=slave, stderr=slave,
                               close_fds=True)
    os.close(slave)
    if process_holder is not None:
        process_holder.append(process)
    text, live = "", (0.0, 0.0)
    deadline = time.monotonic() + 120
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                raise RuntimeError("O teste demorou demais")
            ready, _, _ = select.select([master], [], [], .25)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                text += chunk.decode("utf-8", "replace")
                found = _LIVE.findall(text[-600:])
                if found:
                    down, du, up, uu = found[-1]
                    live = (_mbps(down, du), _mbps(up, uu))
                    if progress:
                        progress(*live)
            elif process.poll() is not None:
                break
    finally:
        os.close(master)
    process.wait(timeout=10)
    if process.returncode:
        raise RuntimeError("Sem internet, ou o teste falhou")
    down = _summary(text, r"Downlink capacity:\s*([\d.]+)\s*([KMG])bps")
    up = _summary(text, r"Uplink capacity:\s*([\d.]+)\s*([KMG])bps")
    if not (down or up or any(live)):
        raise RuntimeError("Sem internet, ou o teste falhou")
    rpm = _summary(text, r"Downlink Responsiveness:[^|\n]*\|\s*(\d+)\s*RPM")
    ping = _summary(text, r"Idle Latency:\s*([\d.]+)\s*milliseconds")
    rpm = float(rpm[1]) if rpm else 0
    return {
        "down": _mbps(*down.groups()) if down else live[0],  # megabits por segundo
        "up": _mbps(*up.groups()) if up else live[1],
        "rpm": rpm,
        "feel": "Ótima" if rpm >= 800 else "Boa" if rpm >= 300 else "Lenta",
        "ping": float(ping[1]) if ping else None,
    }


def speed_words(mbps):
    """O que dá para fazer com essa velocidade, em palavras simples."""
    if mbps >= 100:
        return "Sobra para tudo, até 4K em várias telas"
    if mbps >= 25:
        return "Dá para vídeo 4K e chamadas de vídeo"
    if mbps >= 5:
        return "Dá para vídeo em HD e chamadas"
    return "Lenta: vídeo pode travar"


# ---------------------------------------------------------------- Wi-Fi
def wifi_device():
    text = _run(["networksetup", "-listallhardwareports"]).stdout
    match = re.search(r"Hardware Port: (?:Wi-Fi|AirPort)\nDevice: (\S+)", text)
    return match[1] if match else None


def saved_networks():
    """Redes Wi-Fi guardadas no Mac, na ordem de preferência."""
    device = wifi_device()
    if not device:
        return []
    lines = _run(["networksetup", "-listpreferredwirelessnetworks", device]).stdout.splitlines()[1:]
    return [line.strip() for line in lines if line.strip()]


def wifi_password(name):
    """Pede ao Mac a senha guardada. O próprio Mac mostra a janela pedindo a senha do computador."""
    result = _run(["security", "find-generic-password", "-D", "AirPort network password", "-a", name, "-w"], timeout=120)
    if result.returncode:
        if "could not be found" in result.stderr:
            raise RuntimeError("Essa rede não tem senha guardada")
        raise RuntimeError("O Mac não liberou a senha")
    return result.stdout.strip()


def wifi_qr_text(name, password):
    escape = lambda value: re.sub(r'([\\;,:"])', r"\\\1", value)
    kind = "WPA" if password else "nopass"
    return f"WIFI:T:{kind};S:{escape(name)};P:{escape(password)};;"


def wifi_qr(name, password, size):
    """QR Code que a câmera do celular lê para entrar na rede. Pixels pretos e brancos, sem borrar."""
    import segno
    matrix = segno.make(wifi_qr_text(name, password), error="m").matrix
    modules = len(matrix) + 4  # 2 quadradinhos de margem branca de cada lado
    scale = max(1, size // modules)
    image = Image.new("L", (modules, modules), 255)
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            if value:
                image.putpixel((x + 2, y + 2), 0)
    return image.resize((modules * scale, modules * scale), Image.Resampling.NEAREST).convert("RGB")


# ---------------------------------------------------------------- app bloqueado
def blocked(app_path):
    return "com.apple.quarantine" in _run(["xattr", app_path]).stdout


def unblock(app_path):
    """Tira a marca de "baixado da internet" do app, que causa o aviso de app danificado.
    Se o app for de outro usuário, o Mac pede a senha do computador."""
    if not app_path.endswith(".app") or not os.path.isdir(app_path):
        raise RuntimeError("Escolha um app (.app)")
    was_blocked = blocked(app_path)
    result = _run(["xattr", "-dr", "com.apple.quarantine", app_path])
    if result.returncode or blocked(app_path):
        quoted = app_path.replace("\\", "\\\\").replace('"', '\\"')
        script = f'do shell script "xattr -dr com.apple.quarantine " & quoted form of "{quoted}" with administrator privileges'
        admin = _run(["osascript", "-e", script], timeout=300)
        if admin.returncode or blocked(app_path):
            raise RuntimeError("Não consegui liberar esse app")
    return was_blocked
