"""Ações do Treco que não dependem de arquivo: gravar voz, gravar tela e traduzir o que foi copiado.

Ficam na barra de menus e na aba Mais. Só existem no Mac.
"""
import os
import threading

from ..core.log import log_error
from .pixel import BLUE
from .platform_mac import clipboard_text, notify, reveal, set_clipboard_text

MODE_OF = {"rec_voice": "voice", "rec_screen": "screen", "rec_both": "screen_mic"}


def clock(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class RecorderControl:
    """Uma gravação por vez, com o tempo aparecendo ao lado do T na barra de cima."""

    def __init__(self, app):
        self.app = app
        self.current = None
        self.op = None
        self.saving = False

    @property
    def busy(self):
        return self.current is not None or self.saving

    def label(self):
        if self.saving:
            return "Salvando…"
        return clock(self.current.elapsed()) if self.current else ""

    def tell(self, text, title="Treco", good=False):
        """Avisa na janela, se ela estiver aberta, e no canto da tela."""
        notify(text, title)
        if good:
            self.app.say(text[:44], BLUE)
        else:
            self.app.say(text[:44])

    def start(self, op):
        from ..modules import recorder
        if self.busy:
            return
        mode, self.op = MODE_OF[op], op
        if mode != "voice" and not recorder.screen_allowed(ask=True):
            recorder.open_privacy("ScreenCapture")
            self.tell("Libere o Treco em Gravação de Tela nos Ajustes e tente de novo", "Treco: falta permissão")
            return
        try:
            from ..core import prefs
            self.current = recorder.Recording(mode, prefs.get("rec_folder") or self.app.out_dir)
            self.current.start()
        except Exception as error:
            log_error("gravar", error)
            self.current = None
            self.tell(str(error)[:80] or "Não consegui gravar", "Treco: não gravou")
            return
        self.tick()

    def tick(self):
        """A cada meio segundo: atualiza o relógio e percebe se a gravação parou sozinha."""
        rec = self.current
        if rec is None:
            return
        if not rec.alive:
            self.current = None
            reason = rec.problem()
            rec.discard()
            if reason == "O Mac não deixou gravar":
                from ..modules import recorder
                recorder.open_privacy("Microphone")
                reason = "Libere o microfone para o Treco nos Ajustes"
            self.tell(reason, "Treco: a gravação parou")
            self.show()
            return
        self.show()
        self.app.root.after(500, self.tick)

    def show(self):
        menubar = getattr(self.app, "menubar", None)
        if menubar:
            menubar.set_title(("● " + self.label()) if self.busy else "")
        if self.app.tab:
            self.app.host.invalidate()

    def stop(self):
        rec = self.current
        if rec is None:
            return
        self.current, self.saving = None, True
        self.show()

        def work():
            try:
                path, error = rec.stop(), None
            except Exception as e:
                path, error = None, e
            self.app.root.after(0, lambda: self.saved(path, error))

        threading.Thread(target=work, daemon=True).start()

    def saved(self, path, error):
        self.saving = False
        self.show()
        if error:
            log_error("parar gravação", error)
            self.tell(str(error)[:80], "Treco: a gravação falhou")
            return
        self.app.add_files([path])
        reveal(path)
        self.tell(f"Salvo: {os.path.basename(path)}", "Treco: gravação pronta", good=True)

    def shutdown(self):
        """Ao sair do Treco no meio de uma gravação, salva o que já foi gravado."""
        rec, self.current = self.current, None
        if rec:
            try:
                rec.stop()
            except Exception as error:
                log_error("salvar gravação ao sair", error)


def translate_clipboard(app, target=None):
    """Traduz o texto copiado e devolve a tradução para a área de transferência."""
    from ..modules import translate
    text = clipboard_text()
    if not text.strip():
        notify("Copie um texto primeiro (⌘C) e tente de novo", "Treco: nada copiado")
        app.say("Copie um texto primeiro")
        return
    names = {code: word for _, code, word in translate.LANGUAGES}

    def work():
        try:
            result, chosen = translate.translate_text(text, target)
            app.root.after(0, lambda: done(result, chosen))
        except Exception as error:
            if not isinstance(error, translate.NotDownloaded):
                log_error("traduzir cópia", error)
            message = ("Baixe os idiomas em Idioma e Região > Idiomas de Tradução (abri os Ajustes)"
                       if isinstance(error, translate.NotDownloaded) else str(error)[:80])
            short = str(error)[:44]  # o Python apaga "error" ao sair do except: guarda o texto antes
            app.root.after(0, lambda: (notify(message, "Treco: não traduziu"), app.say(short)))

    def done(result, target):
        set_clipboard_text(result)
        preview = " ".join(result.split())
        notify(preview[:140] + ("…" if len(preview) > 140 else ""),
               f"Tradução em {names.get(target, target)} copiada · ⌘V para colar")
        app.say(f"Tradução em {names.get(target, target)} copiada", BLUE)

    threading.Thread(target=work, daemon=True).start()
