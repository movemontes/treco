"""Monta o Treco para passar a outras pessoas: um Treco.app que funciona sozinho, dentro de um .dmg.

A pessoa abre o .dmg e arrasta o Treco para Aplicativos. Não precisa de Python nem de nada instalado.

    .venv/bin/python vendor/build_mac.py

Sai em dist/Treco.app e dist/Treco-<versão>-mac.dmg. Precisa de vendor/bin/ffmpeg e ffprobe
(vendor/build_ffmpeg.sh) e dos ajudantes treco-translate e treco-summarize (vendor/src).

O app é só para Mac com chip Apple (M1 ou mais novo). Sem conta de desenvolvedor da Apple ele não é
"notarizado": na primeira vez a pessoa precisa liberar em Ajustes > Privacidade e Segurança > "Abrir Mesmo Assim".
O modelo de legendas (148 MB) não vai junto: o Treco baixa na primeira vez que alguém legenda um vídeo.
"""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_mac_app import VERSION, make_icns  # noqa: E402

DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")
APP = os.path.join(DIST, "Treco.app")
TOOLS = ("ffmpeg", "ffprobe", "treco-translate", "treco-summarize")
EXTRA_PLIST = {
    "CFBundleDisplayName": "Treco",
    "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
    "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
    "LSApplicationCategoryType": "public.app-category.utilities",
    "CFBundleLocalizations": ["pt", "en"], "CFBundleDevelopmentRegion": "pt",
    "NSMicrophoneUsageDescription": "O Treco usa o microfone para gravar a sua voz.",
    "NSAppleEventsUsageDescription": "O Treco pede ao Finder para mandar ao Lixo apps que precisam da sua senha.",
    "NSHumanReadableCopyright": "Treco — grátis",
}


def run(command, **kw):
    print("»", " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(command))[:160])
    subprocess.run(command, check=True, **kw)


def build_app():
    for name in TOOLS:
        if not os.path.isfile(os.path.join(ROOT, "vendor", "bin", name)):
            raise SystemExit(f"Falta vendor/bin/{name}")
    icon = os.path.join(tempfile.mkdtemp(), "Treco.icns")
    make_icns(icon)
    sep = os.pathsep
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
               "--name", "Treco", "--icon", icon, "--osx-bundle-identifier", "app.treco",
               "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
               "--add-data", f"{ROOT}/treco_app/ui/fonts{sep}treco_app/ui/fonts",
               "--add-data", f"{ROOT}/treco_app/ui/mascote{sep}treco_app/ui/mascote",  # o Disquetinho
               "--add-data", f"{ROOT}/treco_app/core/en.json{sep}treco_app/core",  # tradução para inglês
               "--collect-submodules", "treco_app",  # muitos módulos são importados só na hora do uso
               "--collect-all", "tkinterdnd2", "--collect-all", "pypandoc", "--collect-data", "certifi",
               "--collect-submodules", "yt_dlp", "--collect-data", "segno",
               # assinatura digital de PDF (certificado A1)
               "--collect-submodules", "pyhanko", "--collect-data", "pyhanko",
               "--collect-submodules", "pyhanko_certvalidator", "--copy-metadata", "pyhanko",
               "--exclude-module", "PyObjCTest", "--exclude-module", "pytest", "--exclude-module", "IPython",
               "--exclude-module", "matplotlib", "--exclude-module", "win32api", "--exclude-module", "pystray"]
    for name in TOOLS:
        command += ["--add-binary", f"{ROOT}/vendor/bin/{name}{sep}bin"]
    command.append(os.path.join(ROOT, "treco.py"))
    run(command, cwd=ROOT)
    plist_path = os.path.join(APP, "Contents", "Info.plist")
    with open(plist_path, "rb") as f:
        info = plistlib.load(f)
    info.update(EXTRA_PLIST)
    with open(plist_path, "wb") as f:
        plistlib.dump(info, f)
    # assinatura "caseira" (sem conta da Apple): o Mac exige alguma assinatura em chip Apple
    run(["codesign", "--force", "--deep", "--sign", "-", APP], capture_output=True)


def build_dmg():
    dmg = os.path.join(DIST, f"Treco-{VERSION}-mac.dmg")
    stage = tempfile.mkdtemp(prefix="treco_dmg_")
    shutil.copytree(APP, os.path.join(stage, "Treco.app"), symlinks=True)
    os.symlink("/Applications", os.path.join(stage, "Aplicativos"))
    with open(os.path.join(stage, "Como instalar.txt"), "w", encoding="utf-8") as f:
        f.write("1. Arraste o Treco para a pasta Aplicativos.\n"
                "2. Abra o Treco pelos Aplicativos.\n"
                "3. Se o Mac disser que não pode verificar o app: abra Ajustes do Sistema >\n"
                "   Privacidade e Segurança, role até o fim e clique em \"Abrir Mesmo Assim\".\n"
                "   Isso só é preciso na primeira vez.\n\n"
                "Precisa de um Mac com chip Apple (M1 ou mais novo) e macOS 13 ou mais novo.\n"
                "Traduzir e Resumir página precisam do macOS 26 (o Resumir também da Apple Intelligence).\n")
    if os.path.exists(dmg):
        os.remove(dmg)
    run(["hdiutil", "create", "-volname", "Treco", "-srcfolder", stage, "-fs", "HFS+", "-format", "UDZO",
         "-imagekey", "zlib-level=9", "-ov", dmg], capture_output=True)
    shutil.rmtree(stage)
    return dmg


if __name__ == "__main__":
    build_app()
    dmg = build_dmg()
    print("Pronto:", APP)
    print("Para passar adiante:", dmg, f"({os.path.getsize(dmg) / 1e6:.0f} MB)")
