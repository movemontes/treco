"""Monta o Treco para Windows: uma pasta com o Treco.exe e, se o Inno Setup estiver instalado, um instalador.

Rode no Windows, dentro da pasta do projeto, com o Python do .venv:

    .venv\\Scripts\\python vendor\\build_win.py

Precisa de vendor\\bin\\ffmpeg.exe e ffprobe.exe com os filtros whisper (legenda) e ass.
Confira com:  vendor\\bin\\ffmpeg.exe -hide_banner -filters | findstr "whisper ass"

Sai em:
- dist\\Treco\\Treco.exe            (o app, para testar)
- dist\\Treco-<versão>-win-setup.exe  (instalador; precisa do Inno Setup 6: https://jrsoftware.org/isinfo.php)
- dist\\Treco-<versão>-win.zip       (se não houver Inno Setup)

A atualização automática procura no GitHub um arquivo que termina em ".exe": suba o instalador na release.
Sem certificado de assinatura, o Windows mostra "O Windows protegeu o computador": a pessoa clica em
"Mais informações" > "Executar assim mesmo". Isso só é preciso na primeira vez.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from treco_app.version import VERSION  # noqa: E402

DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")
APP_DIR = os.path.join(DIST, "Treco")
TOOLS = ("ffmpeg.exe", "ffprobe.exe")
ISCC_PLACES = (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe",
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"))


def run(command, **kw):
    print("»", " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(command))[:160])
    subprocess.run(command, check=True, **kw)


def make_ico(target):
    """Ícone do Disquetinho, no mesmo desenho do Mac."""
    from treco_app.ui.icons import save_win_ico
    return save_win_ico(target)


def build_app():
    if sys.platform != "win32":
        raise SystemExit("Este roteiro é para rodar no Windows.")
    for name in TOOLS:
        if not os.path.isfile(os.path.join(ROOT, "vendor", "bin", name)):
            raise SystemExit(f"Falta vendor\\bin\\{name}")
    icon = make_ico(os.path.join(tempfile.mkdtemp(), "Treco.ico"))
    sep = os.pathsep
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
               "--name", "Treco", "--icon", icon,
               "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
               "--add-data", f"{ROOT}/treco_app/ui/fonts{sep}treco_app/ui/fonts",
               "--add-data", f"{ROOT}/treco_app/ui/mascote{sep}treco_app/ui/mascote",
               "--add-data", f"{ROOT}/treco_app/core/en.json{sep}treco_app/core",
               "--collect-submodules", "treco_app",
               "--collect-all", "tkinterdnd2", "--collect-all", "pypandoc", "--collect-data", "certifi",
               "--collect-submodules", "yt_dlp", "--collect-data", "segno",
               "--collect-submodules", "pyhanko", "--collect-data", "pyhanko",
               "--collect-submodules", "pyhanko_certvalidator", "--copy-metadata", "pyhanko",
               "--hidden-import", "pystray._win32", "--hidden-import", "win32com.client",
               "--hidden-import", "win32com.shell.shell", "--hidden-import", "win32clipboard",
               "--exclude-module", "pytest", "--exclude-module", "IPython", "--exclude-module", "matplotlib",
               "--exclude-module", "objc", "--exclude-module", "AppKit", "--exclude-module", "Quartz",
               "--exclude-module", "Foundation", "--exclude-module", "Vision"]
    for name in TOOLS:
        command += ["--add-binary", f"{ROOT}/vendor/bin/{name}{sep}bin"]
    command.append(os.path.join(ROOT, "treco.py"))
    run(command, cwd=ROOT)
    shutil.copy(icon, os.path.join(APP_DIR, "Treco.ico"))


INNO = r"""
[Setup]
AppId={{6C1E2F0A-7A43-4E3B-9D1F-7D3E54A1C0B2}
AppName=Treco
AppVersion=%(version)s
AppPublisher=Treco (grátis)
AppPublisherURL=https://movemontes.github.io/treco
DefaultDirName={localappdata}\Programs\Treco
DefaultGroupName=Treco
PrivilegesRequired=lowest
OutputDir=%(dist)s
OutputBaseFilename=Treco-%(version)s-win-setup
SetupIconFile=%(icon)s
UninstallDisplayIcon={app}\Treco.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "%(app)s\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Treco"; Filename: "{app}\Treco.exe"
Name: "{userdesktop}\Treco"; Filename: "{app}\Treco.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Treco.exe"; Description: "{cm:LaunchProgram,Treco}"; Flags: nowait postinstall skipifsilent
"""


def build_installer():
    iscc = next((p for p in ISCC_PLACES if os.path.isfile(p)), shutil.which("ISCC"))
    if not iscc:
        target = os.path.join(DIST, f"Treco-{VERSION}-win")
        archive = shutil.make_archive(target, "zip", DIST, "Treco")
        print("Sem Inno Setup: fiz só o .zip.")
        return archive
    script = os.path.join(WORK, "Treco.iss")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(INNO % {"version": VERSION, "dist": DIST, "app": APP_DIR,
                        "icon": os.path.join(APP_DIR, "Treco.ico")})
    run([iscc, "/Q", script])
    return os.path.join(DIST, f"Treco-{VERSION}-win-setup.exe")


if __name__ == "__main__":
    build_app()
    out = build_installer()
    print("Pronto:", os.path.join(APP_DIR, "Treco.exe"))
    print("Para passar adiante:", out, f"({os.path.getsize(out) / 1e6:.0f} MB)")
