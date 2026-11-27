"""Quais arquivos o Treco entende. Não carrega nenhuma biblioteca pesada."""
import importlib.util
import os

from ..modules import documents as docs
from .paths import find_tool

IMAGE_IN = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif",
            ".ico", ".heic", ".heif", ".avif", ".jfif", ".tga", ".psd"}
AUDIO_IN = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
            ".aiff", ".aif", ".amr"}
VIDEO_IN = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv", ".m4v",
            ".3gp", ".mts", ".ts", ".mpg", ".mpeg"}
SUB_IN = {".srt", ".vtt"}

HEIF_OK = importlib.util.find_spec("pillow_heif") is not None
IMAGE_OUT = ["PNG", "JPG", "WEBP", "HEIC", "AVIF", "BMP", "TIFF", "GIF", "ICO", "PDF"]
AUDIO_OUT = ["MP3", "WAV", "M4A", "FLAC", "OGG", "OPUS", "AIFF"]
VIDEO_OUT = ["MP4", "MOV", "MKV", "WEBM", "AVI", "GIF", "MP3"]
if not HEIF_OK:
    IMAGE_OUT.remove("HEIC")

OUTS = {"image": IMAGE_OUT, "audio": AUDIO_OUT, "video": VIDEO_OUT, "pdf": docs.PDF_OUT,
        "doc": docs.DOC_OUT, "sheet": docs.SHEET_OUT, "sub": ["SRT", "VTT"]}
KIND_NAME = {"image": "Imagem", "audio": "Áudio", "video": "Vídeo", "pdf": "PDF", "doc": "Docs",
             "sheet": "Planilha", "sub": "Legenda"}
KIND_TAG = {"image": "IMG", "audio": "ÁUD", "video": "VÍD", "pdf": "PDF", "doc": "DOC", "sheet": "XLS",
            "sub": "LEG"}
KINDS = ["image", "audio", "video", "pdf", "doc", "sheet", "sub"]
if docs.SLIDE_IN:  # apresentações dependem do LibreOffice
    OUTS["slide"] = docs.SLIDE_OUT
    KIND_NAME["slide"] = "Slides"
    KIND_TAG["slide"] = "PPT"
    KINDS.append("slide")

COMPRESSIBLE = {"image", "audio", "video", "pdf"}
MB = 1_000_000  # "16 MB" como os apps de mensagem e e-mail contam
COMPRESS_ITEMS = [("Leve", "leve"), ("Médio", "medio"), ("Forte", "forte"), ("2 MB", 2 * MB),
                  ("10 MB", 10 * MB), ("16 MB", 16 * MB), ("25 MB", 25 * MB)]

EDITABLE = {"image", "video"}
EDIT_ITEMS = [("Girar →", "direita"), ("Girar ←", "esquerda"), ("180°", "180"), ("Espelhar", "espelhar"),
              ("Inverter", "inverter")]

ROTATIONS = {"direita", "esquerda", "180", "espelhar", "inverter"}
# ação, nome no botão, ícone e tipos de arquivo aceitos
TOOLS = [
    ("direita", "Direita", "right", {"image", "video"}), ("esquerda", "Esquerda", "left", {"image", "video"}),
    ("180", "180°", "r180", {"image", "video"}), ("espelhar", "Espelhar", "mirror", {"image", "video"}),
    ("inverter", "Inverter", "flip", {"image", "video"}),
    ("trim", "Cortar", "trim", {"video", "audio"}), ("crop", "Recortar", "crop", {"image", "video"}),
    ("resize", "Tamanho", "resize", {"image", "video"}), ("mute", "Sem som", "mute", {"video"}),
    ("speed", "Acelerar", "speed", {"video", "audio"}),
    ("slow", "Mais lento", "slow", {"video", "audio"}),
    ("volume", "Volume", "volume", {"video", "audio"}), ("clean", "Limpar", "clean", {"image", "video", "audio", "pdf"}),
    ("join", "Juntar", "join", {"image", "video", "audio", "pdf"}), ("split", "Separar", "split", {"pdf"}),
]
# ferramentas da aba "Mais"; as que usam recursos do próprio Mac só aparecem no Mac
MAC_ONLY = {"nobg", "ocr", "faces", "translate"}
MORE_TOOLS = [
    ("transcribe", "Transcrever", "transcribe", {"video", "audio"}),
    ("nobg", "Sem fundo", "nobg", {"image"}), ("ocr", "Ler texto", "ocr", {"image", "pdf"}),
    ("faces", "Rostos", "faces", {"image"}), ("lock", "Senha", "lock", {"pdf"}),
    ("mark", "Marca", "mark", {"image", "video"}), ("translate", "Traduzir", "translate", {"doc", "pdf", "sub"}),
    ("rename", "Renomear", "rename", set(KINDS)),
    ("photos_pdf", "Fotos em PDF", "photos", {"image"}), ("scan", "Escanear", "scan", {"image"}),
    ("slideshow", "Slides em vídeo", "slides", {"image"}),
    ("tempo", "BPM e tom", "tempo", {"audio", "video"}), ("silence", "Cortar silêncios", "silence", {"audio", "video"}),
    ("voice", "Limpar a voz", "voice", {"audio", "video"}),
    ("sign", "Assinar", "sign", {"pdf"}), ("pages", "Páginas", "pages", {"pdf"}), ("redact", "Tarja preta", "redact", {"pdf"}),
]
# ações da aba "Mais" que não dependem de arquivo (só no Mac)
ACTIONS = [("rec_voice", "Gravar voz", "mic"), ("rec_screen", "Gravar tela", "screen"),
           ("rec_both", "Tela e voz", "screenmic"), ("clip", "Traduzir cópia", "clipboard")]
WHEEL_LABEL = {"direita": "Girar →", "esquerda": "Girar ←"}


def edit_items(kind, many=False):
    """Opções de edição da roda para este tipo de arquivo."""
    items = []
    for op, label, _, kinds in TOOLS:
        if kind in kinds and (op != "join" or many):
            items.append((WHEEL_LABEL.get(op, label), op))
    return items


FFMPEG = find_tool("ffmpeg")


def selection_problem(paths, allow_mixed=False):
    """Devolve o aviso (título, detalhe) se a seleção não puder ir para a roda.

    allow_mixed: tipos misturados passam (a roda mostra só Renomear)."""
    unsupported = [p for p in paths if os.path.isdir(p) or not kind_of(p)]
    if unsupported:
        only = len(unsupported) == len(paths)
        if len(unsupported) > 1:
            title = f"{len(unsupported)} sem suporte"
        elif os.path.isdir(unsupported[0]):
            title = "Pasta" if only else "Pasta na seleção"
        else:
            extension = os.path.splitext(unsupported[0])[1].lstrip(".").upper()
            if only:
                title = f"Arquivo {extension}" if extension else "Este arquivo"
            else:
                title = f"{extension} sem suporte" if extension else "Item sem suporte"
        return title, "Sem opções no Treco" if only else "Tire da seleção"
    kinds = []
    for path in paths:
        kind = kind_of(path)
        if kind not in kinds:
            kinds.append(kind)
    if len(kinds) > 1 and not allow_mixed:
        title = " + ".join(KIND_NAME[k] for k in kinds) if len(kinds) == 2 else f"{len(kinds)} tipos diferentes"
        return title, "Selecione um tipo só"
    return None


def selection_kind(paths):
    """O tipo da seleção, ou "mixed" quando há mais de um."""
    kinds = {kind_of(p) for p in paths}
    return kinds.pop() if len(kinds) == 1 else ("mixed" if kinds else None)


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    for kind, group in (("image", IMAGE_IN), ("audio", AUDIO_IN), ("video", VIDEO_IN),
                        ("pdf", docs.PDF_IN), ("doc", docs.DOC_IN), ("sheet", docs.SHEET_IN),
                        ("slide", docs.SLIDE_IN), ("sub", SUB_IN)):
        if ext in group:
            return kind
    return None
