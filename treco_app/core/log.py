"""Registro de erros, para dar para descobrir o motivo quando algo falha."""
import datetime
import os
import threading
import traceback

from .paths import log_dir

_lock = threading.Lock()


def log_path():
    return os.path.join(log_dir(), "treco.log")


def log_error(context, error):
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock:
            if os.path.exists(path) and os.path.getsize(path) > 500_000:
                os.replace(path, path + ".old")
            detail = "".join(traceback.format_exception_only(type(error), error)).strip()
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {context} | {detail}\n")
    except Exception:
        pass
