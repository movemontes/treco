"""Desinstalar um app por completo (só no Mac): o app e o que ele espalhou pelo Mac.

Procura pelo identificador do app, pelos identificadores das peças que ele traz dentro dele (ajudantes,
extensões, itens de início), pelos grupos que ele declara, e pelo nome. Olha na Biblioteca do usuário,
nas pastas temporárias, na Biblioteca do sistema e nos recibos de instalação.

Tudo vai para o Lixo (dá para recuperar). Apps da Apple e o próprio Treco ficam de fora.
O que pode ser de outro app do mesmo fabricante aparece desmarcado: a pessoa decide.
"""
import glob
import os
import plistlib
import subprocess

from .cleanup import folder_size

# Biblioteca do usuário: pasta e modelos de nome.
# {id} = cada identificador (do app e das peças dele), {name} = nome do app, {group} = grupo de apps.
USER_PLACES = (
    ("Application Support", ("{name}", "{id}", "{company}/{name}")),
    ("Application Support/CrashReporter", ("{name}_*.plist",)),
    ("Application Support/com.apple.sharedfilelist/com.apple.LSSharedFileList.ApplicationRecentDocuments", ("{id}.sfl*",)),
    ("Caches", ("{id}", "{id}.*", "{name}", "{name}-updater")),
    ("Caches/com.apple.helpd/Generated", ("{id}*",)),
    ("Preferences", ("{id}.plist", "{id}.*.plist")),
    ("Preferences/ByHost", ("{id}.*.plist",)),
    ("Containers", ("{id}",)),
    ("Group Containers", ("{group}", "group.{id}*")),
    ("Application Scripts", ("{id}", "{group}")),
    ("Saved Application State", ("{id}.savedState",)),
    ("Logs", ("{name}", "{id}")),
    ("Logs/DiagnosticReports", ("{name}-*", "{name}_*")),
    ("HTTPStorages", ("{id}", "{id}.binarycookies")),
    ("WebKit", ("{id}",)),
    ("Cookies", ("{id}.binarycookies",)),
    ("LaunchAgents", ("{id}*.plist", "{vendor}.*.plist")),
    ("Autosave Information", ("{id}*",)),
)

# Biblioteca do sistema (apagar aqui pede a senha do Mac).
SYSTEM_PLACES = (
    ("Application Support", ("{name}", "{id}")),
    ("Caches", ("{id}",)),
    ("Preferences", ("{id}.plist",)),
    ("LaunchAgents", ("{id}*.plist", "{vendor}.*.plist")),
    ("LaunchDaemons", ("{id}*.plist", "{vendor}.*.plist")),
    ("PrivilegedHelperTools", ("{id}*", "{vendor}.*")),
    ("Logs", ("{name}", "{id}")),
)

# Tipos de peça que um app pode trazer dentro dele, cada uma com seu próprio identificador.
BUNDLE_KINDS = (".app", ".appex", ".xpc", ".systemextension", ".qlgenerator", ".mdimporter", ".plugin", ".bundle")


def _plist(path):
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {}


def app_info(app_path):
    info = _plist(os.path.join(app_path, "Contents", "Info.plist"))
    if not info:
        raise ValueError("sem Info.plist")
    name = info.get("CFBundleName") or os.path.splitext(os.path.basename(app_path))[0]
    return {"id": info.get("CFBundleIdentifier") or "", "name": name,
            "file_name": os.path.splitext(os.path.basename(app_path))[0],
            "executable": info.get("CFBundleExecutable") or ""}


def problem(app_path):
    """Motivo para não desinstalar, ou None."""
    if not app_path.endswith(".app") or not os.path.isdir(app_path):
        return "Escolha um app (.app)"
    real = os.path.realpath(app_path)
    if real.startswith("/System/"):
        return "Esse app faz parte do macOS"
    try:
        info = app_info(app_path)
    except (OSError, ValueError):
        return "Não consegui ler esse app"
    if info["id"].startswith("com.apple."):
        return "Apps da Apple ficam: o Mac precisa deles"
    if info["id"] == "app.treco":
        return "O Treco não desinstala ele mesmo"
    return None


# Fabricantes "genéricos": muitos apps diferentes usam esse começo de identificador.
GENERIC_VENDORS = {"com.github", "io.github", "com.electron", "org.electron", "com.example", "com.company",
                   "com.yourcompany", "org.python", "org.sparkle-project", "com.squirrel", "com.microsoft"}


def vendor(bundle_id):
    """As duas primeiras partes do identificador ("com.google" em "com.google.Chrome").

    Ignora o código de equipe no começo ("4FG648TM2A.group.com.aone.keka" vira "com.aone")."""
    parts = bundle_id.split(".")
    if len(parts) > 1 and len(parts[0]) == 10 and parts[0].isalnum() and parts[0].isupper():
        parts = parts[1:]
    if parts and parts[0] == "group":
        parts = parts[1:]
    parts = [p.lower() for p in parts]
    return ".".join(parts[:2]) if len(parts) >= 3 else ".".join(parts)


def inner_ids(app_path, main_id):
    """Identificadores das peças que o app traz dentro dele e que são do mesmo fabricante.

    Peças de bibliotecas de terceiros (como o Sparkle, que muitos apps usam) ficam de fora,
    porque os dados delas podem ser de outro app."""
    found = set()
    contents = os.path.join(app_path, "Contents")
    own = vendor(main_id)
    for base, dirs, names in os.walk(contents):
        depth = base[len(contents):].count(os.sep)
        if depth > 6:
            dirs[:] = []
            continue
        for d in list(dirs):
            if d.endswith(BUNDLE_KINDS):
                info = _plist(os.path.join(base, d, "Contents", "Info.plist")) or _plist(os.path.join(base, d, "Info.plist"))
                bid = info.get("CFBundleIdentifier") or ""
                if bid and not bid.lower().startswith("com.apple.") and vendor(bid) == own:
                    found.add(bid)
            if d in ("Resources", "Headers", "_CodeSignature", "Modules") or d.endswith(".lproj"):
                dirs.remove(d)
    found.discard(main_id)
    return sorted(found)


def app_groups(app_path):
    """Grupos de apps que o app declara (pastas que ele divide com as peças dele)."""
    try:
        out = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", app_path],
                             capture_output=True, timeout=20).stdout
        ents = plistlib.loads(out) if out.strip() else {}
    except (OSError, subprocess.SubprocessError, ValueError, plistlib.InvalidFileException):
        return []
    groups = ents.get("com.apple.security.application-groups") or []
    return [g for g in groups if isinstance(g, str) and len(g) >= 5]


def other_apps(app_path):
    """Identificadores dos outros apps instalados (para não apagar o que é de outro app)."""
    ids = []
    real = os.path.realpath(app_path)
    for folder in ("/Applications", os.path.expanduser("~/Applications"), "/Applications/Utilities"):
        for path in glob.glob(os.path.join(glob.escape(folder), "*.app")):
            if os.path.realpath(path) == real:
                continue
            bid = _plist(os.path.join(path, "Contents", "Info.plist")).get("CFBundleIdentifier")
            if bid:
                ids.append(bid)
    return ids


def temp_dirs():
    """Pastas temporárias e de cache do usuário que o macOS guarda em /var/folders."""
    dirs = []
    for key in ("DARWIN_USER_CACHE_DIR", "DARWIN_USER_TEMP_DIR"):
        try:
            value = subprocess.run(["getconf", key], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            value = ""
        if value and os.path.isdir(value):
            dirs.append(value)
    return dirs


def receipts(main_id, ids, names):
    """Recibos de instalação (.pkg) do app em /var/db/receipts: [(caminho, certeza)]."""
    found = []
    base = "/var/db/receipts"
    own = vendor(main_id)
    words = {n.lower().replace(" ", "") for n in names}
    for path in glob.glob(os.path.join(base, "*.plist")) + glob.glob(os.path.join(base, "*.bom")):
        pkg = os.path.basename(path).rsplit(".", 1)[0]
        low = pkg.lower()
        if low.startswith("com.apple."):
            continue
        if any(low == i.lower() or low.startswith(i.lower() + ".") for i in ids):
            found.append((path, True))
        elif low.startswith(own + ".") and any(w and w in low.replace("-", "").replace("_", "") for w in words):
            found.append((path, False))
    return found


def needs_admin(path):
    """Caminho fora da pasta do usuário (o Finder pede a senha para apagar)."""
    return not os.path.realpath(path).startswith(os.path.realpath(os.path.expanduser("~")) + os.sep) and \
        not os.path.realpath(path).startswith("/private/var/folders/")


def scan(app_path, library=None, system_library="/Library", home=None, extra_temp=None):
    """Tudo o que o app deixou no Mac: [(caminho, tamanho, certeza)].

    certeza=False quando o item pode ser de outro app do mesmo fabricante: aparece desmarcado."""
    home = home or os.path.expanduser("~")
    library = library or os.path.join(home, "Library")
    info = app_info(app_path)
    main_id = info["id"]
    ids = [main_id] + inner_ids(app_path, main_id) if len(main_id) >= 5 else []
    groups = app_groups(app_path)
    names = {n for n in (info["name"], info["file_name"], info["executable"]) if len(n) >= 3}
    others = other_apps(app_path)
    sibling = {vendor(o) for o in others}
    other_low = [o.lower() for o in others]

    def shared(path, by_name):
        """Pode ser de outro app? (pasta só pelo nome, ou de um grupo de um fabricante com outros apps)."""
        low = os.path.basename(path).lower()
        if any(low == o or low.startswith(o + ".") for o in other_low):
            return True
        if by_name:
            return vendor(main_id) in sibling
        return False

    found = {}

    def add(path, sure):
        if path in found:
            found[path] = (found[path][0], found[path][1] and sure)
            return
        if os.path.realpath(path) == os.path.realpath(app_path):
            return
        size = folder_size(path) if os.path.isdir(path) and not os.path.islink(path) else _size(path)
        found[path] = (size, sure)

    def look(base, patterns):
        for pattern in patterns:
            if "{company}" in pattern:
                # Pasta do fabricante com a do app dentro ("Google/Chrome").
                # É específica o bastante (fabricante + nome do app) para vir marcada.
                company = vendor(main_id).split(".")[-1].lower()
                if len(company) >= 3 and vendor(main_id) not in GENERIC_VENDORS:
                    wanted = {n.lower() for n in names}
                    for folder in _list(base):
                        if folder.lower() == company:
                            for sub in _list(os.path.join(base, folder)):
                                if sub.lower() in wanted:
                                    add(os.path.join(base, folder, sub), True)
                continue
            if "{vendor}" in pattern:
                # Ajudantes do mesmo fabricante (atualizador, serviço de fundo): só quando o fabricante é claro.
                own = vendor(main_id)
                values = [("vendor", own)] if own.count(".") == 1 and len(own) >= 6 and own not in GENERIC_VENDORS else []
            elif "{group}" in pattern:
                values = [("group", g) for g in groups]
            elif "{name}" in pattern:
                values = [("name", n) for n in names]
            elif "{id}" in pattern:
                values = [("id", i) for i in ids]
            else:
                values = [(None, None)]
            for kind, value in values:
                wanted = pattern.replace("{" + kind + "}", glob.escape(value)) if kind else pattern
                for path in glob.glob(os.path.join(glob.escape(base), wanted)):
                    by_name = kind in ("name", "vendor")
                    sure = not shared(path, by_name)
                    if kind == "group" and vendor(value) in sibling:
                        sure = False
                    add(path, sure)

    for folder, patterns in USER_PLACES:
        look(os.path.join(library, folder), patterns)
    for folder, patterns in SYSTEM_PLACES:
        look(os.path.join(system_library, folder), patterns)
    for temp in (extra_temp if extra_temp is not None else temp_dirs()):
        look(temp, ("{id}",))
    if system_library == "/Library":
        for path, sure in receipts(main_id, ids, names):
            add(path, sure)

    # Pastas escondidas na pasta pessoal (~/.nome, ~/.config/nome): só pelo nome, então ficam desmarcadas.
    for n in names:
        low = n.lower().replace(" ", "")
        if len(low) < 4:
            continue
        for path in (os.path.join(home, "." + low), os.path.join(home, ".config", low)):
            if os.path.exists(path):
                add(path, False)

    return [(p, s, sure) for p, (s, sure) in found.items()]


def leftovers(app_path, library=None):
    """O que o app deixou no Mac: [(caminho, tamanho)]."""
    return [(p, s) for p, s, _ in scan(app_path, library)]


def _list(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []


def _size(path):
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


def running(bundle_id):
    from AppKit import NSRunningApplication
    return list(NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id) or [])


def quit_app(bundle_id):
    for app in running(bundle_id):
        app.terminate()


def finder_trash(paths):
    """Manda para o Lixo pelo Finder, que pede a senha do Mac quando precisa. Devolve o que ficou."""
    if not paths:
        return []
    items = ", ".join('(POSIX file "{}" as alias)'.format(p.replace("\\", "\\\\").replace('"', '\\"')) for p in paths)
    try:
        subprocess.run(["osascript", "-e", f'tell application "Finder" to delete {{{items}}}'],
                       capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        pass
    return [p for p in paths if os.path.lexists(p)]


def trash_app(app_path):
    """O app vai para o Lixo. Se ele for do sistema (instalado pela App Store), o Finder pede a senha."""
    from .cleanup import to_trash
    moved, failed = to_trash([app_path])
    if moved:
        return True
    return not finder_trash([app_path])


def trash_all(paths):
    """Manda tudo para o Lixo. O que precisa de senha vai junto, num pedido só. Devolve o que ficou."""
    from .cleanup import to_trash
    left = []
    for path in paths:
        if not os.path.lexists(path):
            continue
        moved, _ = to_trash([path])
        if not moved:
            left.append(path)
    # Fora da pasta do usuário, o Finder pede a senha do Mac. Dentro dela, o que ficou é protegido pelo macOS
    # (pasta de dados de outro app): precisa liberar o Treco em Acesso Total ao Disco.
    system = finder_trash([p for p in left if needs_admin(p)])
    return [p for p in left if not needs_admin(p)] + system
