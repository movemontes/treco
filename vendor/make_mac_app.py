"""Cria o Treco.app na pasta do projeto, para usar no dia a dia enquanto o app final não existe.

O Treco.app roda o código desta pasta com o Python do .venv, mas com nome, ícone e Dock próprios
(sem isso o Mac mostra "Python"). Rode de novo se mudar a pasta do projeto de lugar:

    .venv/bin/python vendor/make_mac_app.py
"""
import os
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
APP = os.path.join(ROOT, "Treco.app")
from treco_app.version import VERSION  # noqa: E402


def python_binary():
    """O executável de verdade do Python da Apple/python.org (o que fica dentro do Python.app)."""
    base = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    path = os.path.join(base, "Python.framework", "Versions", version, "Resources", "Python.app", "Contents", "MacOS", "Python")
    if not os.path.isfile(path):
        raise SystemExit("Este Python não é o do python.org: não sei montar o Treco.app com ele.")
    return path


def make_icns(target):
    from treco_app.ui.icons import app_icon
    work = tempfile.mkdtemp()
    iconset = os.path.join(work, "Treco.iconset")
    os.makedirs(iconset)
    big = app_icon(1024)
    for size in (16, 32, 128, 256, 512):
        big.resize((size, size), 1).save(os.path.join(iconset, f"icon_{size}x{size}.png"))
        big.resize((size * 2, size * 2), 1).save(os.path.join(iconset, f"icon_{size}x{size}@2x.png"))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", target], check=True)
    shutil.rmtree(work)


def main():
    site = sysconfig.get_paths()["purelib"]  # site-packages do .venv
    if os.path.isdir(APP):
        shutil.rmtree(APP)
    macos = os.path.join(APP, "Contents", "MacOS")
    resources = os.path.join(APP, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(resources)
    shutil.copy2(python_binary(), os.path.join(macos, "python"))
    launcher = os.path.join(macos, "Treco")
    boot = ("import runpy, site, sys; site.addsitedir(sys.argv[1]); sys.argv = sys.argv[2:]; "
            "runpy.run_path(sys.argv[0], run_name='__main__')")
    with open(launcher, "w") as f:
        f.write(f"""#!/bin/sh
# Abre o Treco da pasta do projeto. Feito por vendor/make_mac_app.py
ROOT={sh(ROOT)}
if [ ! -f "$ROOT/treco.py" ]; then
  osascript -e 'display alert "Treco" message "A pasta do projeto mudou de lugar. Rode vendor/make_mac_app.py de novo."'
  exit 1
fi
cd "$ROOT"
exec "$(dirname "$0")/python" -c {sh(boot)} {sh(site)} "$ROOT/treco.py" "$@"
""")
    os.chmod(launcher, 0o755)
    make_icns(os.path.join(resources, "Treco.icns"))
    with open(os.path.join(APP, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({
            "CFBundleName": "Treco", "CFBundleDisplayName": "Treco", "CFBundleIdentifier": "app.treco",
            "CFBundleExecutable": "Treco", "CFBundleIconFile": "Treco", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "O Treco usa o microfone para gravar a sua voz.",
            "NSAppleEventsUsageDescription": "O Treco pede ao Finder para mandar ao Lixo apps que precisam da sua senha.",
            "LSApplicationCategoryType": "public.app-category.utilities",
        }, f)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", APP], check=True, capture_output=True)
    subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
                    "-f", APP], capture_output=True)
    print("Pronto:", APP)


def sh(text):
    return "'" + text.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    main()
