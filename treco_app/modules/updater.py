"""Atualização: confere no GitHub se saiu uma versão nova e, no Mac, troca o app sozinho.

Só acessa a página pública de "releases" do repositório. Nada do computador é enviado.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from ..core import prefs
from ..core.paths import MAC
from ..version import GITHUB_REPO, VERSION

DAY = 24 * 3600


def configured():
    return bool(GITHUB_REPO) and "SEU_" not in GITHUB_REPO and "/" in GITHUB_REPO


def parse(version):
    """'v1.2.3' -> (1, 2, 3)."""
    return tuple(int(n) for n in re.findall(r"\d+", version or "")[:4]) or (0,)


def _open(url, timeout=15):
    from .captions import tls_context
    request = urllib.request.Request(url, headers={"User-Agent": "Treco-updater", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=timeout, context=tls_context())


def latest():
    """A versão mais nova publicada, ou None se não houver nada mais novo que esta."""
    if not configured():
        return None
    with _open(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest") as response:
        data = json.load(response)
    version = (data.get("tag_name") or "").lstrip("vV")
    if parse(version) <= parse(VERSION):
        return None
    ending = "-mac.dmg" if MAC else ".exe"
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith(ending)), None)
    return {"version": version, "notes": (data.get("body") or "").strip(), "page": data.get("html_url"),
            "download": asset and asset.get("browser_download_url"), "size": asset and asset.get("size")}


def due():
    """Confere no máximo uma vez por dia, sozinho, ao abrir o Treco."""
    return configured() and time.time() - (prefs.get("update_checked") or 0) > DAY


def mark_checked():
    prefs.put("update_checked", time.time())


def app_bundle():
    """Pasta Treco.app que está rodando (só no app empacotado)."""
    if not getattr(sys, "frozen", False):
        return None
    path = os.path.abspath(sys.executable)
    while path != "/" and not path.endswith(".app"):
        path = os.path.dirname(path)
    return path if path.endswith(".app") else None


def can_install():
    bundle = app_bundle()
    return bool(MAC and bundle and os.access(os.path.dirname(bundle), os.W_OK))


def download(url, progress=None):
    folder = tempfile.mkdtemp(prefix="treco_update_")
    target = os.path.join(folder, "Treco.dmg")
    with _open(url, timeout=60) as response, open(target, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            out.write(block)
            done += len(block)
            if progress and total:
                progress(done / total)
    return target


def install(dmg):
    """Abre o .dmg, copia o Treco novo ao lado do atual e deixa pronto um passo final
    que, quando este Treco fechar, manda o antigo para o Lixo, põe o novo no lugar e abre."""
    bundle = app_bundle()
    mount = tempfile.mkdtemp(prefix="treco_mount_")
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, dmg],
                   check=True, capture_output=True, timeout=120)
    try:
        source = os.path.join(mount, "Treco.app")
        if not os.path.isdir(source):
            raise RuntimeError("O arquivo baixado não tem o Treco")
        staged = os.path.join(os.path.dirname(bundle), ".Treco-novo.app")
        if os.path.exists(staged):
            shutil.rmtree(staged, ignore_errors=True)
        subprocess.run(["ditto", source, staged], check=True, capture_output=True, timeout=300)
    finally:
        subprocess.run(["hdiutil", "detach", "-force", mount], capture_output=True, timeout=60)
    trash = os.path.expanduser("~/.Trash")
    old = os.path.join(trash, f"Treco {VERSION} ({time.strftime('%H.%M.%S')}).app")
    script = (f'while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.3; done; '
              f'mv "$OLD_APP" "$TRASHED" && mv "$NEW_APP" "$OLD_APP" && xattr -dr com.apple.quarantine "$OLD_APP"; '
              f'open "$OLD_APP"')
    env = dict(os.environ, OLD_APP=bundle, NEW_APP=staged, TRASHED=old)
    subprocess.Popen(["/bin/sh", "-c", script], env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
