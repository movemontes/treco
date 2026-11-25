"""Menus do Treco no Mac: o T da barra de cima e os menus do app (Treco, Arquivo, Ferramentas...).

Os dois usam a mesma lista de ações, para nunca ficarem diferentes.
"""
import tkinter as tk

from ..core.i18n import tr
from ..core.log import log_error

TABS = (("convert", "Converter"), ("compress", "Comprimir"), ("edit", "Editar"), ("av", "Vídeo e áudio"),
        ("image", "Imagem"), ("docs", "Documentos"), ("download", "Baixar"), ("utils", "Utilidades"))
FILE_TABS = {"convert", "compress", "edit"}  # só com arquivo na lista


class Entry:
    def __init__(self, text, action, checked=None, visible=None, raw=False):
        self.text, self.action, self.checked, self.visible, self.raw = text, action, checked, visible, raw

    def label(self):
        text = self.text() if callable(self.text) else self.text
        return text if self.raw else tr(text)

    def shown(self):
        return self.visible is None or bool(self.visible())


def quick_entries(app):
    """Gravar e traduzir a cópia."""
    from ..modules import translate
    rec, items = app.recording, []
    if rec:
        idle = lambda: not rec.busy
        items += [Entry(lambda: "Salvando gravação…" if rec.saving else f"Parar gravação ({rec.label()})",
                        rec.stop, visible=lambda: rec.busy),
                  Entry("Gravar voz", lambda: app.tool("rec_voice"), visible=idle),
                  Entry("Gravar tela", lambda: app.tool("rec_screen"), visible=idle),
                  Entry("Gravar tela e voz", lambda: app.tool("rec_both"), visible=idle)]
    if translate.available():
        items.append(Entry("Traduzir o que copiei", lambda: app.tool("clip")))
    return items


def utility_entries(app):
    """Grupo 2: utilidades do Mac."""
    from ..modules import mac_utils
    from . import utility_dialogs as ud
    from .platform_mac import activate

    def dialog(factory):
        def run():
            activate()
            try:
                factory(app)
            except Exception as error:
                log_error("utilidade", error)
                app.say(str(error)[:44] or "Não deu certo")
        return run

    tool = lambda op: (lambda: (activate(), app.tool(op)))
    items = [Entry("Histórico de cópias…", tool("cliphist")),
             Entry("Captura com rolagem…", lambda: app.tool("scrollshot")),
             Entry("Resumir página…", tool("summary"), visible=lambda: "summary" in app.utility_ok()),
             Entry("Limpar Downloads…", tool("cleanup")),
             Entry("Desinstalar app…", tool("uninstall")),
             Entry("Gerar QR Code…", tool("qr")),
             Entry("Manter o Mac acordado", app.awake.toggle, checked=lambda: app.awake.on)]
    if mac_utils.has_battery():
        items.append(Entry("Saúde da bateria", dialog(ud.BatteryDialog)))
    items.append(Entry("Teste de internet", dialog(ud.SpeedDialog)))
    if mac_utils.wifi_device():
        items.append(Entry("Senha do Wi-Fi e QR Code", dialog(ud.WifiDialog)))
    items.append(Entry("Liberar app bloqueado…", dialog(ud.unblock_app)))
    return items


def update_entry(app):
    from .update_ui import check
    return Entry("Procurar atualização…", lambda: check(app, manual=True))


def dock_entry():
    """Escolha: ao fechar a janela, o Treco some do Dock e fica só na barra de menus."""
    from ..core import prefs
    return Entry("Sumir do Dock ao fechar", lambda: prefs.toggle("hide_dock"), checked=lambda: prefs.get("hide_dock"))


def recent_clips(app, count=5):
    """As últimas cópias direto no T: clicar copia de novo."""
    if not app.clips:
        return []
    from .platform_mac import set_clipboard_text

    def item(n):
        def text():
            entries = app.clips.history.items
            if n >= len(entries):
                return ""
            preview = " ".join(entries[n]["text"].split())
            return "   " + (preview[:40] + "…" if len(preview) > 40 else preview)

        def pick():
            entries = app.clips.history.items
            if n < len(entries):
                set_clipboard_text(entries[n]["text"])
        return Entry(text, pick, visible=lambda: n < len(app.clips.history.items))
    title = Entry("Copiados por último:", lambda: None, visible=lambda: bool(app.clips.history.items))
    return [title] + [item(n) for n in range(count)]


def start_menubar(root, app, show):
    """Ícone na barra de cima: o Treco continua lá mesmo com a janela fechada."""
    from .icons import menubar_icon
    from .platform_mac import MenuBar
    from .tray import autostart_on, autostart_toggle
    # O clique no menu chega pelo Objective-C. Chamar o Tk dali derruba o Python (erro de GIL),
    # então o clique só entra numa fila, e o próprio Tk confere a fila a cada 50 ms.
    from collections import deque
    pending = deque()
    later = lambda action: (lambda: pending.append(action))

    def run_pending():
        while pending:
            action = pending.popleft()
            try:
                action()
            except Exception as error:
                log_error("menu da barra", error)
        root.after(50, run_pending)
    run_pending()
    groups = [[Entry("Abrir o Treco", show)], quick_entries(app), recent_clips(app), utility_entries(app),
              [Entry("Iniciar com o Mac", autostart_toggle, checked=autostart_on), dock_entry(), update_entry(app)],
              [Entry("Sair do Treco", app.quit)]]
    items = []
    for group in groups:
        if group:
            if items:
                items.append(None)
            items += [(e.label, later(e.action), e.checked, e.visible) for e in group]
    try:
        return MenuBar(menubar_icon(), tr("Treco: segure Shift ao arrastar um arquivo no Finder"), items)
    except Exception as error:
        log_error("barra de menus", error)
        return None


def _fill(menu, entries):
    """Põe as ações num menu do Tk e as atualiza (texto, ✓, escondido) toda vez que o menu abre."""
    variables = {}
    for entry in entries:
        if entry.checked:
            variables[entry] = tk.BooleanVar(value=False)

    def refresh():
        menu.delete(0, "end")
        for entry in entries:
            if not entry.shown():
                continue
            if entry in variables:
                variables[entry].set(bool(entry.checked()))
                menu.add_checkbutton(label=entry.label(), variable=variables[entry], command=entry.action)
            else:
                menu.add_command(label=entry.label(), command=entry.action)

    menu.configure(postcommand=refresh)
    refresh()
    return refresh


def app_menus(root, app, show):
    """Menus da barra de cima quando o Treco está na frente."""
    from .tray import autostart_on, autostart_toggle
    bar = tk.Menu(root)
    from ..core import i18n
    treco = tk.Menu(bar, name="apple", tearoff=0)  # o menu "Treco", ao lado da maçã

    def pick_language(lang):
        """Troca o idioma na hora: a janela redesenha e os menus são refeitos."""
        i18n.set_language(lang)
        app.host.invalidate()
        root.after(50, lambda: app_menus(root, app, show))
    _fill(treco, [update_entry(app), Entry("Iniciar com o Mac", autostart_toggle, checked=autostart_on), dock_entry(),
                  Entry("Português", lambda: pick_language("pt"), checked=lambda: i18n.language() == "pt", raw=True),
                  Entry("English", lambda: pick_language("en"), checked=lambda: i18n.language() == "en", raw=True)])
    bar.add_cascade(menu=treco)
    root.createcommand("tkAboutDialog", lambda: (show(), app.show_about()))
    root.createcommand("tk::mac::ShowPreferences", show)  # "Ajustes…" abre a janela do Treco

    files = tk.Menu(bar, tearoff=0)
    files.add_command(label=tr("Abrir a janela do Treco"), command=show)
    files.add_command(label=tr("Adicionar arquivos…"), accelerator="Command-O", command=lambda: (show(), app.pick_files()))
    files.add_command(label=tr("Adicionar pasta…"), command=lambda: (show(), app.pick_folder()))
    files.add_separator()
    files.add_command(label=tr("Salvar em…"), command=lambda: (show(), app.choose_dest()))
    files.add_command(label=tr("Abrir a pasta dos prontos"), command=app.open_folder)
    files.add_separator()
    files.add_command(label=tr("Limpar a lista"), command=app.clear)
    bar.add_cascade(label=tr("Arquivo"), menu=files)

    def open_tab(key):
        show()
        app.tab = key
        app.host.invalidate()

    tools = tk.Menu(bar, tearoff=0)
    tool_entries = [Entry(label, lambda k=key: open_tab(k)) for key, label in TABS]
    quick = quick_entries(app)

    def refresh_tools():
        tools.delete(0, "end")
        kinds = {r.kind for r in app.rows.values()}
        shown_tabs = {c[0] for c in app.categories(kinds)}
        for (key, _), entry in zip(TABS, tool_entries):
            if key in shown_tabs or key not in FILE_TABS:
                tools.add_command(label=entry.label(), command=entry.action)
        shown = [e for e in quick if e.shown()]
        if shown:
            tools.add_separator()
        for entry in shown:
            tools.add_command(label=entry.label(), command=entry.action)

    tools.configure(postcommand=refresh_tools)
    refresh_tools()
    bar.add_cascade(label=tr("Ferramentas"), menu=tools)

    utilities = tk.Menu(bar, tearoff=0)
    _fill(utilities, utility_entries(app))
    bar.add_cascade(label=tr("Utilidades"), menu=utilities)

    bar.add_cascade(label=tr("Janela"), menu=tk.Menu(bar, name="window", tearoff=0))
    root.configure(menu=bar)
    app.win.configure(menu=bar)
    app.win.bind("<Command-o>", lambda _: app.pick_files())
    app.win.bind("<Command-w>", lambda _: app.hide_window())
    return bar
