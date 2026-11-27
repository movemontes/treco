"""Idioma do Treco: português ou inglês.

O código continua todo em português. Na hora de mostrar um texto na tela, `tr` troca pelo inglês
usando a lista em `treco_app/core/en.json` (texto em português -> texto em inglês). Textos com partes
que mudam, como "Convertendo 3 arquivos", estão na lista com {} no lugar de cada parte.

O idioma segue o do sistema (português se o Mac/Windows estiver em português, inglês nos outros casos).
Dá para escolher no menu do Treco, e TRECO_LANG=en ou pt força um deles (útil para testar).
"""
import json
import locale
import os
import re
import sys
from functools import lru_cache

from . import prefs

_lang = None
_exact = {}
_patterns = []  # (regex, texto em inglês), dos mais específicos para os mais genéricos
misses = set()  # textos mostrados sem tradução (para conferir em testes)


def _system_language():
    try:
        from Foundation import NSLocale
        first = NSLocale.preferredLanguages()[0]
        return "pt" if str(first).lower().startswith("pt") else "en"
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import ctypes
            return "pt" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x16 else "en"
        name = locale.getlocale()[0] or os.environ.get("LANG", "")
        return "pt" if name.lower().startswith("pt") else "en"
    except Exception:
        return "pt"


def language():
    """'pt' ou 'en'."""
    global _lang
    if _lang is None:
        forced = os.environ.get("TRECO_LANG", "").lower()[:2]
        chosen = prefs.get("ui_language")
        _lang = forced if forced in ("pt", "en") else chosen if chosen in ("pt", "en") else _system_language()
        if _lang == "en":
            _load()
    return _lang


def english():
    return language() == "en"


def set_language(lang):
    """Troca na hora; None volta a seguir o sistema."""
    global _lang
    prefs.put("ui_language", lang)
    _lang = None
    tr.cache_clear()
    language()


def _load():
    if _exact:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "en.json"), encoding="utf-8") as f:
            table = json.load(f)
    except (OSError, ValueError):
        return
    for pt, en in table.items():
        if pt.startswith("//"):
            continue
        if "{}" in pt:
            literal = pt.replace("{}", "")
            if len(re.findall(r"[A-Za-zÀ-ú]", literal)) < 4:
                continue  # quase só partes que mudam: pegaria nomes de arquivo por engano
            body = "".join("(.+?)" if part == "{}" else re.escape(part) for part in re.split(r"(\{\})", pt))
            _patterns.append((len(literal), re.compile("^" + body + "$", re.S), en))
        else:
            _exact[pt] = en
    _patterns.sort(key=lambda item: -item[0])


# --- Windows: os textos foram escritos pensando no Mac. Aqui eles viram "PC", "Lixeira" e "Ctrl".
WINDOWS = sys.platform == "win32"
WIN_TEXT = {  # frases inteiras que mudam de sentido no Windows
    "Mac acordado": "PC acordado",
    "Liberar app": "Liberar arquivo",
    "Desinstalar app": "Desinstalar programa",
    "Abre app que o Mac diz estar danificado": "Tira o bloqueio de arquivo baixado da internet",
    "Tira o app e o que ele guardou no Mac": "Abre o desinstalador de um programa",
    "Mostrar no Finder": "Mostrar na pasta",
}
_WIN_WORDS = {
    "pt": [(r"\bpara o Lixo\b", "para a Lixeira"), (r"\bno Lixo\b", "na Lixeira"), (r"\bdo Lixo\b", "da Lixeira"),
           (r"\bo Lixo\b", "a Lixeira"), (r"\bLixo\b", "Lixeira"), (r"\bFinder\b", "Explorador de Arquivos"),
           (r"\bMac\b", "PC"), (r"⌘", "Ctrl+")],
    "en": [(r"\bTrash\b", "Recycle Bin"), (r"\bFinder\b", "File Explorer"), (r"\bMac\b", "PC"), (r"⌘", "Ctrl+")],
}


def _known(text):
    """É um texto do próprio Treco (está na lista de traduções)? Nome de arquivo não é."""
    _load()
    return text in _exact or any(pattern.match(text) for _, pattern, _ in _patterns)


@lru_cache(maxsize=4096)
def tr(text):
    """O texto no idioma escolhido. Em português (ou sem tradução) devolve o próprio texto."""
    if not WINDOWS or not text or not isinstance(text, str):
        return _tr(text)
    if text in WIN_TEXT:
        return _tr(WIN_TEXT[text])
    out = _tr(text)
    if out != text or _known(text):  # só mexe em texto do Treco, nunca em nome de arquivo
        for pattern, new in _WIN_WORDS["en" if language() == "en" else "pt"]:
            out = re.sub(pattern, new, out)
    return out


def _tr(text):
    if not text or not isinstance(text, str) or language() != "en":
        return text
    found = _exact.get(text)
    if found is not None:
        return found
    # espaços nas pontas e reticências/dois-pontos no fim não mudam a tradução
    stripped = text.strip()
    if stripped != text and stripped:
        inner = tr(stripped)
        if inner != stripped:
            return text[:len(text) - len(text.lstrip())] + inner + text[len(text.rstrip()):]
    for _, pattern, en in _patterns:
        match = pattern.match(text)
        if match:
            parts = [tr(part) for part in match.groups()]
            return _fill(en, parts)
    for ending in ("…", ":", ".", "!"):
        if text.endswith(ending) and len(text) > 1:
            inner = tr(text[:-1])
            if inner != text[:-1]:
                return inner + ending
    if os.environ.get("TRECO_I18N_DEBUG"):
        misses.add(text)
    return text


def _fill(template, parts):
    out, pieces = [], template.split("{}")
    for i, piece in enumerate(pieces):
        out.append(piece)
        if i < len(parts) and i < len(pieces) - 1:
            out.append(parts[i])
    return "".join(out)
