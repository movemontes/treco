"""Escolhas que o Treco lembra entre uma vez e outra (as opções do botão direito)."""
import json
import os
import threading

from .paths import data_dir

DEFAULTS = {
    "rec_resolution": "Original",  # Original, 1080p ou 720p
    "rec_fps": 30,
    "rec_cursor": True,
    "rec_clicks": False,
    "rec_mic": None,  # nome do microfone; None = o padrão do Mac
    "rec_screen": None,  # nome da tela; None = a primeira
    "rec_folder": None,  # None = Mesa
    "pdf_page": "A4",  # A4 ou Foto
    "pdf_margin": True,
    "scan_color": "Colorido",  # Colorido, Cinza ou Preto e branco
    "scan_crop": True,
    "scan_separate": False,
    "language": "Inglês",
    "clip_language": None,  # None = automático
    "qr_size": "Médio",
    "slow_percent": 50,
    "slide_seconds": 3,
    "slide_transition": "Suave",
    "slide_zoom": True,
    "slide_order": "Da lista",
    "slide_shape": "Deitado 16:9",
    "clip_history": True,
    "summary_size": "Médio",
    "summary_format": "txt",
    "shot_format": "PNG",
    "hide_dock": True,  # ao fechar a janela, o Treco sai do Dock e fica só na barra de menus
    "welcome_seen": False,
    "window_size": None,  # (largura, altura) em pixels do Treco
}
_lock = threading.Lock()
_cache = None


def _file():
    return os.path.join(data_dir(), "ajustes.json")


def _load():
    global _cache
    if _cache is None:
        try:
            with open(_file(), encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def get(key):
    with _lock:
        return _load().get(key, DEFAULTS.get(key))


def put(key, value):
    with _lock:
        data = _load()
        data[key] = value
        try:
            os.makedirs(data_dir(), exist_ok=True)
            temp = _file() + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(temp, _file())
        except OSError:
            pass  # sem onde gravar: vale só até fechar o Treco


def toggle(key):
    put(key, not get(key))
