"""Espaço no disco: arquivos repetidos e a Lupa de espaço (o que ocupa mais, pasta por pasta).

Nada é apagado aqui. O que a pessoa escolher vai para o Lixo (cleanup.to_trash).
"""
import hashlib
import os
import stat
import threading
import time

SKIP_NAMES = {".Trash", ".Spotlight-V100", ".fseventsd", ".DocumentRevisions-V100", ".TemporaryItems",
              "node_modules", ".git",
              "$Recycle.Bin", "System Volume Information", "$WinREAgent", "Config.Msi"}  # Windows
# pastas que o macOS protege ou que não fazem sentido mexer
SKIP_PATHS = ("/System", "/private/var/vm", "/Volumes/com.apple.TimeMachine", "/dev", "/cores")
# dados guardados de cada app: o macOS pede permissão para cada um e a leitura ficaria parada esperando
PROTECTED = ("/Library/Containers", "/Library/Group Containers", "/Library/Mail", "/Library/Messages",
             "/Library/Safari", "/Library/Metadata/CoreSpotlight", "/Library/Biome", "/Library/Accounts")


def real_size(info):
    """Espaço que o arquivo ocupa de verdade no disco."""
    blocks = getattr(info, "st_blocks", None)
    return blocks * 512 if blocks is not None else info.st_size


# ---------------------------------------------------------------- arquivos repetidos
def _hash(path, limit=None):
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        if limit:
            h.update(f.read(limit))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.digest()


def find_duplicates(folders, minimum=1024, progress=None, cancel=None):
    """Arquivos com conteúdo idêntico (byte a byte), agrupados. Cada grupo começa pelo mais antigo."""
    by_size = {}
    seen = set()
    count = 0
    for folder in folders:
        for root, dirs, files in os.walk(folder):
            if cancel and cancel.is_set():
                return []
            dirs[:] = [d for d in dirs if d not in SKIP_NAMES and not d.startswith(".")
                       and not d.endswith((".app", ".photoslibrary", ".bundle", ".framework"))]
            for name in files:
                if name.startswith("."):
                    continue
                path = os.path.join(root, name)
                try:
                    info = os.lstat(path)
                except OSError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_size < minimum:
                    continue
                key = (info.st_dev, info.st_ino)
                if key in seen:  # o mesmo arquivo por dois caminhos (atalho de verdade)
                    continue
                seen.add(key)
                by_size.setdefault(info.st_size, []).append((path, info.st_mtime))
                count += 1
                if progress and count % 500 == 0:
                    progress("Olhando", count, root)
    candidates = [group for group in by_size.values() if len(group) > 1]
    groups = []
    total = sum(len(g) for g in candidates)
    checked = 0
    for group in candidates:
        if cancel and cancel.is_set():
            return []
        by_head = {}
        for path, mtime in group:
            try:
                by_head.setdefault(_hash(path, 64 * 1024), []).append((path, mtime))
            except OSError:
                pass
            checked += 1
            if progress and checked % 50 == 0:
                progress("Comparando", checked, total)
        for same_head in by_head.values():
            if len(same_head) < 2:
                continue
            by_full = {}
            for path, mtime in same_head:
                try:
                    by_full.setdefault(_hash(path), []).append((path, mtime))
                except OSError:
                    pass
            for same in by_full.values():
                if len(same) > 1:
                    same.sort(key=lambda item: (item[1], len(item[0])))  # o mais antigo primeiro: é o "original"
                    size = os.path.getsize(same[0][0])
                    groups.append({"size": size, "files": [p for p, _ in same], "times": [t for _, t in same]})
    groups.sort(key=lambda g: g["size"] * (len(g["files"]) - 1), reverse=True)
    return groups


# ---------------------------------------------------------------- lupa de espaço
class Tree:
    """Tamanho de cada pasta, calculado uma vez e navegável depois."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.sizes = {}      # pasta -> bytes (tudo dentro dela)
        self.children = {}   # pasta -> [(nome, bytes, é pasta)]
        self.files = 0
        self.denied = 0
        self.skipped = 0
        self.current = ""
        self.done = False
        self.cancel = threading.Event()
        self.started = time.monotonic()

    def scan(self, workers=12):
        """Lê várias pastas ao mesmo tempo (o disco responde melhor assim) e soma tudo no fim."""
        from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
        self.own = {}    # pasta -> (bytes dos arquivos dela, [subpastas], [(nome, bytes) dos arquivos])
        pending = set()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending.add(pool.submit(self._list, self.root))
            while pending and not self.cancel.is_set():
                done, pending = wait(pending, timeout=.5, return_when=FIRST_COMPLETED)
                for future in done:
                    for sub in future.result():
                        pending.add(pool.submit(self._list, sub))
            for future in pending:
                future.cancel()
        if not self.cancel.is_set():
            self._total(self.root)
        self.done = True
        return self

    def _list(self, folder):
        """Uma pasta só: soma os arquivos e devolve as subpastas para ler depois."""
        if self.cancel.is_set():
            return []
        self.current = folder
        files, subs, total = [], [], 0
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.name in SKIP_NAMES:
                        continue
                    try:
                        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            path = entry.path
                            if path.endswith(PROTECTED):
                                self.skipped += 1
                            elif not path.startswith(SKIP_PATHS) and not (self.root == "/" and path == "/Volumes"):
                                subs.append(path)
                            continue
                        size = real_size(entry.stat(follow_symlinks=False))
                    except OSError:
                        continue
                    files.append((entry.name, size))
                    total += size
        except OSError:
            self.denied += 1
        self.files += len(files)
        self.own[folder] = (total, subs, files)
        return subs

    def _total(self, folder):
        """Soma de baixo para cima, sem recursão (pastas muito fundas não quebram)."""
        order, stack = [], [folder]
        while stack:
            path = stack.pop()
            order.append(path)
            stack.extend(self.own.get(path, (0, [], []))[1])
        for path in reversed(order):
            total, subs, files = self.own.get(path, (0, [], []))
            items = [(name, size, False) for name, size in files]
            for sub in subs:
                size = self.sizes.get(sub, 0)
                items.append((os.path.basename(sub), size, True))
                total += size
            items.sort(key=lambda item: item[1], reverse=True)
            self.sizes[path] = total
            self.children[path] = items
        self.own = {}

    def remove(self, path):
        """Depois de mandar para o Lixo: tira da conta, sem medir tudo de novo."""
        size = 0
        parent = os.path.dirname(path)
        name = os.path.basename(path)
        items = self.children.get(parent, [])
        for item in items:
            if item[0] == name:
                size = item[1]
        self.children[parent] = [item for item in items if item[0] != name]
        walk = parent
        while walk.startswith(self.root):
            self.sizes[walk] = max(0, self.sizes.get(walk, 0) - size)
            if walk == self.root:
                break
            up = os.path.dirname(walk)
            name = os.path.basename(walk)
            self.children[up] = sorted(((n, self.sizes[walk] if n == name and d else s, d)
                                        for n, s, d in self.children.get(up, [])),
                                       key=lambda item: item[1], reverse=True)
            walk = up
        for key in [k for k in self.children if k == path or k.startswith(path + os.sep)]:
            self.children.pop(key, None)
            self.sizes.pop(key, None)


def disk_usage(path="/"):
    import shutil
    usage = shutil.disk_usage(path)
    return usage.total, usage.used, usage.free
