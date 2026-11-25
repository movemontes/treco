"""Acompanhamento de tarefas longas: progresso e cancelamento."""
import threading


class Cancelled(Exception):
    pass


class NothingToGain(Exception):
    """O arquivo já está pequeno: não vale criar uma cópia maior ou igual."""


class Job:
    def __init__(self, on_progress=None):
        self.on_progress = on_progress
        self.cancelled = threading.Event()
        self.process = None
        self._lock = threading.Lock()

    def attach(self, process):
        with self._lock:
            self.process = process
            if self.cancelled.is_set():
                process.terminate()

    def detach(self):
        with self._lock:
            self.process = None

    def cancel(self):
        with self._lock:
            self.cancelled.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def progress(self, fraction):
        if self.on_progress:
            self.on_progress(max(0.0, min(1.0, fraction)))
