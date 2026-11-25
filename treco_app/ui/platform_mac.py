"""Partes nativas do macOS: janela sem moldura, mouse, telas e janelas flutuantes.

O AppKit só é importado depois que o Tk cria o aplicativo; antes disso o Tk quebra.
"""
import fcntl
import os
import subprocess

from PIL import ImageChops, Image

from ..core.paths import data_dir

_lock_file = None
CORNER_RADIUS = 0


def single_instance():
    """Devolve False se já houver outro Treco aberto."""
    global _lock_file
    os.makedirs(data_dir(), exist_ok=True)
    _lock_file = open(os.path.join(data_dir(), "treco.lock"), "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def borderless(win):
    """Janela sem moldura que ainda recebe o teclado. Chamar antes de ela aparecer."""
    win.tk.call("::tk::unsupported::MacWindowStyle", "style", win._w, "plain", "none")


def ns_window(win):
    from AppKit import NSApp
    title = win.title()
    for candidate in NSApp().windows():
        if str(candidate.title()) == title:
            return candidate
    return None


def hide_from_capture(window):
    """A janela (Tk ou NSWindow) não sai em capturas e gravações de tela."""
    from AppKit import NSWindowSharingNone
    if not hasattr(window, "setSharingType_"):
        window.update_idletasks()
        window = ns_window(window)
    if window is not None:
        window.setSharingType_(NSWindowSharingNone)
        return True
    return False


def finish_window(win):
    """Deixa a janela minimizar para o Dock."""
    from AppKit import NSColor, NSWindowStyleMaskMiniaturizable
    window = ns_window(win)
    if window is not None:
        window.setStyleMask_(window.styleMask() | NSWindowStyleMaskMiniaturizable)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        view = window.contentView()
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(CORNER_RADIUS)
        view.layer().setMasksToBounds_(True)
        window.setHasShadow_(True)
        window.invalidateShadow()


def dock_visible(show):
    """Mostra ou esconde o Treco no Dock (escondido, ele fica só na barra de menus)."""
    from AppKit import NSApp, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular
    NSApp().setActivationPolicy_(NSApplicationActivationPolicyRegular if show else NSApplicationActivationPolicyAccessory)


def minimize(win):
    window = ns_window(win)
    if window is not None:
        window.miniaturize_(None)
    else:
        win.iconify()


def activate():
    """Traz o Treco para a frente, para o teclado funcionar."""
    from AppKit import NSApp
    NSApp().activateIgnoringOtherApps_(True)


def primary_height():
    from AppKit import NSScreen
    return NSScreen.screens()[0].frame().size.height


def cursor_pos():
    """Posição do mouse com a origem no topo da tela principal, como o Tk usa."""
    from AppKit import NSEvent
    point = NSEvent.mouseLocation()
    return int(point.x), int(primary_height() - point.y)


def monitor_work_area(x, y):
    """Área útil da tela do cursor, sem a barra de menus e o Dock."""
    from AppKit import NSScreen
    top = primary_height()
    flipped = top - y
    screens = NSScreen.screens()
    chosen = screens[0]
    for screen in screens:
        f = screen.frame()
        if f.origin.x <= x < f.origin.x + f.size.width and f.origin.y <= flipped <= f.origin.y + f.size.height:
            chosen = screen
            break
    v = chosen.visibleFrame()
    return (int(v.origin.x), int(top - v.origin.y - v.size.height),
            int(v.origin.x + v.size.width), int(top - v.origin.y))


def cg_image(img):
    """Converte RGBA do Pillow para uma imagem do macOS, com transparência real."""
    import Quartz
    from Foundation import NSData
    width, height = img.size
    r, g, b, a = img.split()
    r, g, b = (ImageChops.multiply(channel, a) for channel in (r, g, b))
    raw = Image.merge("RGBA", (r, g, b, a)).tobytes()
    provider = Quartz.CGDataProviderCreateWithCFData(NSData.dataWithBytes_length_(raw, len(raw)))
    return Quartz.CGImageCreate(width, height, 8, 32, width * 4, Quartz.CGColorSpaceCreateDeviceRGB(),
                                Quartz.kCGImageAlphaPremultipliedLast, provider, None, False,
                                Quartz.kCGRenderingIntentDefault)


class Overlay:
    """Janela flutuante, transparente, que não rouba o foco. Pixels sempre nítidos."""

    def __init__(self, width, height, click_through=True):
        from AppKit import (NSBackingStoreBuffered, NSColor, NSPanel, NSStatusWindowLevel,
                            NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                            NSWindowCollectionBehaviorStationary, NSWindowStyleMaskBorderless,
                            NSWindowStyleMaskNonactivatingPanel)
        from Foundation import NSMakeRect
        self.w, self.h = width, height
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setLevel_(NSStatusWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setIgnoresMouseEvents_(click_through)
        self.panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                          | NSWindowCollectionBehaviorStationary
                                          | NSWindowCollectionBehaviorFullScreenAuxiliary)
        view = self.panel.contentView()
        view.setWantsLayer_(True)
        self.layer = view.layer()
        self.layer.setMagnificationFilter_("nearest")
        self.layer.setMinificationFilter_("nearest")
        self.layer.setContentsGravity_("resize")

    def move(self, x, y):
        from Foundation import NSMakePoint
        self.panel.setFrameTopLeftPoint_(NSMakePoint(x, primary_height() - y))

    def geometry(self, spec):
        """Aceita o mesmo formato do Tk: LxA+X+Y."""
        size, x, y = spec.replace("-", "+-").split("+")[0], *spec.replace("-", "+-").split("+")[1:3]
        width, height = (int(v) for v in size.split("x"))
        if (width, height) != (self.w, self.h):
            self.w, self.h = width, height
            self.panel.setContentSize_((width, height))
        self.move(int(x), int(y))

    def deiconify(self):
        self.panel.orderFrontRegardless()

    def withdraw(self):
        self.panel.orderOut_(None)

    def push(self, img, x, y):
        import Quartz
        Quartz.CATransaction.begin()
        Quartz.CATransaction.setDisableActions_(True)
        self.layer.setContents_(cg_image(img))
        Quartz.CATransaction.commit()
        self.move(x, y)


def push_layered(overlay, img, x, y, alpha=255):
    overlay.push(img, x, y)


# --- roda do Shift: lê o estado do mouse sem precisar de permissão de acessibilidade
_drag_count = None
_catch_view = None


def key_down(code):
    """Aceita os mesmos códigos do Windows: botão esquerdo, Shift e Esc."""
    from AppKit import NSEvent, NSEventModifierFlagShift
    if code == 0x01:
        return bool(NSEvent.pressedMouseButtons() & 1)
    if code == 0x10:
        return bool(NSEvent.modifierFlags() & NSEventModifierFlagShift)
    if code == 0x1B:
        import Quartz
        return bool(Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateCombinedSessionState, 53))
    return False


def _drag_pasteboard():
    from AppKit import NSPasteboard, NSPasteboardNameDrag
    return NSPasteboard.pasteboardWithName_(NSPasteboardNameDrag)


def foreground_is_explorer():
    """Chamado ao apertar o botão: diz se o clique foi numa janela do Finder ou na Mesa."""
    global _drag_count
    import Quartz
    from AppKit import NSRunningApplication
    _drag_count = _drag_pasteboard().changeCount()  # o que já estava lá é de um arrasto antigo
    x, y = cursor_pos()
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    for window in windows:
        if window.get("kCGWindowLayer", 0) > 0 or window.get("kCGWindowAlpha", 1) <= 0:
            continue
        box = window.get("kCGWindowBounds") or {}
        if not (box.get("X", 0) <= x < box.get("X", 0) + box.get("Width", 0)
                and box.get("Y", 0) <= y < box.get("Y", 0) + box.get("Height", 0)):
            continue
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(window.get("kCGWindowOwnerPID", 0))
        return app is not None and str(app.bundleIdentifier()) == "com.apple.finder"
    return False


def explorer_selection():
    """Todos os arquivos do arrasto atual; vazio enquanto o Finder ainda não os publicou."""
    from AppKit import NSPasteboardURLReadingFileURLsOnlyKey
    from Foundation import NSURL
    board = _drag_pasteboard()
    if board.changeCount() == _drag_count:
        return []
    urls = board.readObjectsForClasses_options_([NSURL], {NSPasteboardURLReadingFileURLsOnlyKey: True}) or []
    paths = []
    for url in urls:
        real = url.filePathURL() or url
        if real.path():
            paths.append(str(real.path()))
    return paths


class MouseWatch:
    """No Mac a soltura vem da leitura do botão físico; não há escuta separada."""
    running = False
    left = False
    release_at = None

    def start(self):
        pass

    def stop(self):
        pass


def catch_view_class():
    """Área que aceita o arrasto como cópia e não faz nada com ele."""
    global _catch_view
    if _catch_view is None:
        import objc
        from AppKit import NSDragOperationCopy, NSView

        class TrecoDropCatcher(NSView):
            @objc.signature(b"Q@:@")
            def draggingEntered_(self, sender):
                return NSDragOperationCopy

            @objc.signature(b"Q@:@")
            def draggingUpdated_(self, sender):
                return NSDragOperationCopy

            @objc.signature(b"Z@:@")
            def prepareForDragOperation_(self, sender):
                return True

            @objc.signature(b"Z@:@")
            def performDragOperation_(self, sender):
                return True
        _catch_view = TrecoDropCatcher
    return _catch_view


class DropCatcher:
    """Cobre as telas durante a roda: assim o Finder nunca recebe o arquivo e nunca o move."""

    def __init__(self):
        self.panels = []
        self.visible = False

    def show(self):
        from AppKit import (NSBackingStoreBuffered, NSColor, NSPanel, NSPasteboardTypeFileURL, NSScreen, NSStatusWindowLevel,
                            NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                            NSWindowCollectionBehaviorStationary, NSWindowStyleMaskBorderless,
                            NSWindowStyleMaskNonactivatingPanel)
        self.hide()
        view_class = catch_view_class()
        for screen in NSScreen.screens():
            frame = screen.frame()
            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                frame, NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel, NSBackingStoreBuffered, False)
            panel.setReleasedWhenClosed_(False)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0, 0.004))  # invisível, mas recebe o arrasto
            panel.setHasShadow_(False)
            panel.setLevel_(NSStatusWindowLevel - 1)
            panel.setHidesOnDeactivate_(False)
            panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
                                         | NSWindowCollectionBehaviorFullScreenAuxiliary)
            view = view_class.alloc().initWithFrame_(((0, 0), (frame.size.width, frame.size.height)))
            view.registerForDraggedTypes_([NSPasteboardTypeFileURL, "NSFilenamesPboardType"])
            panel.setContentView_(view)
            panel.setFrame_display_(frame, False)
            panel.orderFrontRegardless()
            self.panels.append(panel)
        self.visible = True

    def hide(self):
        for panel in self.panels:
            panel.orderOut_(None)
        self.panels = []
        self.visible = False


def ns_image(img, points=None):
    """Imagem do Pillow para NSImage; `points` define o tamanho lógico (para telas Retina)."""
    import io
    from AppKit import NSImage
    from Foundation import NSData
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    data = buffer.getvalue()
    image = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))
    if points:
        image.setSize_((points, points))
    return image


def set_dock_icon(img):
    from AppKit import NSApp
    NSApp().setApplicationIconImage_(ns_image(img))


_menu_target_class = None


def _target_class():
    """Objeto do Objective-C que recebe os cliques do menu e repassa para o Python."""
    global _menu_target_class
    if _menu_target_class is None:
        import objc
        from Foundation import NSObject

        class TrecoMenuTarget(NSObject):
            def initWithActions_(self, actions):
                self = objc.super(TrecoMenuTarget, self).init()
                if self is not None:
                    self.actions = actions
                return self

            @objc.signature(b"v@:@")
            def run_(self, item):
                action = self.actions.get(int(item.tag()))
                if action:
                    action()

            @objc.signature(b"v@:@")
            def menuNeedsUpdate_(self, menu):
                refresh = self.actions.get(-1)
                if refresh:
                    refresh(menu)

        _menu_target_class = TrecoMenuTarget
    return _menu_target_class


class MenuBar:
    """Ícone do Treco na barra de cima do Mac, com um menu pequeno.

    items: lista de (texto, função, marcado) ou (texto, função, marcado, visível). O texto pode ser
    uma função (muda a cada vez que o menu abre); marcado diz se aparece o ✓; visível esconde o item.
    Um item None vira uma linha separadora.
    """

    def __init__(self, image, tooltip, items):
        from AppKit import NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength
        self.items = items
        actions = {-1: self.refresh}
        self.menu = NSMenu.alloc().init()
        self.menu.setAutoenablesItems_(False)
        for index, entry in enumerate(items):
            if entry is None:
                self.menu.addItem_(NSMenuItem.separatorItem())
                continue
            text, action = entry[0], entry[1]
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(text() if callable(text) else text, "run:", "")
            item.setTag_(index)
            actions[index] = action
            self.menu.addItem_(item)
        self.target = _target_class().alloc().initWithActions_(actions)
        for item in self.menu.itemArray():
            if not item.isSeparatorItem():
                item.setTarget_(self.target)
        self.menu.setDelegate_(self.target)
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        icon = ns_image(image, 18)
        icon.setTemplate_(True)
        button = self.item.button()
        button.setImage_(icon)
        button.setToolTip_(tooltip)
        self.item.setMenu_(self.menu)
        self.refresh(self.menu)

    def refresh(self, menu=None):
        from AppKit import NSControlStateValueOff, NSControlStateValueOn
        menu = menu or self.menu
        for index, entry in enumerate(self.items):
            if not entry:
                continue
            item = menu.itemWithTag_(index)
            if callable(entry[0]):
                item.setTitle_(entry[0]())
            if entry[2]:
                item.setState_(NSControlStateValueOn if entry[2]() else NSControlStateValueOff)
            if len(entry) > 3 and entry[3]:
                item.setHidden_(not entry[3]())

    def set_title(self, text):
        """Texto ao lado do ícone, como o tempo de uma gravação. Vazio tira o texto."""
        from AppKit import NSFont, NSImageLeft, NSImageOnly
        button = self.item.button()
        button.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13, 0.3))
        from ..core.i18n import tr
        button.setTitle_(f" {tr(text)}" if text else "")
        button.setImagePosition_(NSImageLeft if text else NSImageOnly)

    def remove(self):
        from AppKit import NSStatusBar
        NSStatusBar.systemStatusBar().removeStatusItem_(self.item)


def clipboard_text():
    from AppKit import NSPasteboard, NSPasteboardTypeString
    return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or ""


def set_clipboard_text(text):
    from AppKit import NSPasteboard, NSPasteboardTypeString
    board = NSPasteboard.generalPasteboard()
    board.clearContents()
    board.setString_forType_(text, NSPasteboardTypeString)


def notify(text, title="Treco"):
    """Aviso no canto da tela do Mac."""
    quote = lambda value: '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
    from ..core.i18n import tr
    text, title = tr(text), tr(title)
    subprocess.Popen(["osascript", "-e", f"display notification {quote(text)} with title {quote(title)}"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal(path):
    """Mostra o arquivo selecionado no Finder."""
    subprocess.Popen(["open", "-R", path])


def set_clipboard_image(png_bytes):
    """Copia uma imagem PNG: dá para colar no WhatsApp, Mensagens, Pages..."""
    from AppKit import NSPasteboard, NSPasteboardTypePNG
    from Foundation import NSData
    board = NSPasteboard.generalPasteboard()
    board.clearContents()
    board.setData_forType_(NSData.dataWithBytes_length_(png_bytes, len(png_bytes)), NSPasteboardTypePNG)
