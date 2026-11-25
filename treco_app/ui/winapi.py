"""Chamadas do Windows usadas pela roda."""
import sys
import threading

from PIL import Image

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    VP = ctypes.c_void_p
    user32.GetDC.restype = VP
    user32.GetDC.argtypes = [VP]
    user32.ReleaseDC.argtypes = [VP, VP]
    user32.GetParent.restype = VP
    user32.GetParent.argtypes = [VP]
    user32.GetWindowLongW.argtypes = [VP, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [VP, ctypes.c_int, ctypes.c_long]
    user32.GetForegroundWindow.restype = VP
    user32.GetClassNameW.argtypes = [VP, ctypes.c_wchar_p, ctypes.c_int]
    gdi32.CreateCompatibleDC.restype = VP
    gdi32.CreateCompatibleDC.argtypes = [VP]
    gdi32.CreateDIBSection.restype = VP
    gdi32.CreateDIBSection.argtypes = [VP, VP, ctypes.c_uint, ctypes.POINTER(VP), VP, ctypes.c_uint]
    gdi32.SelectObject.restype = VP
    gdi32.SelectObject.argtypes = [VP, VP]
    gdi32.DeleteObject.argtypes = [VP]
    gdi32.DeleteDC.argtypes = [VP]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    user32.UpdateLayeredWindow.argtypes = [VP, VP, ctypes.POINTER(wintypes.POINT),
                                           ctypes.POINTER(wintypes.SIZE), VP,
                                           ctypes.POINTER(wintypes.POINT), ctypes.c_uint32,
                                           ctypes.POINTER(BLENDFUNCTION), ctypes.c_uint32]

    def cursor_pos():
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def key_down(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def foreground_is_explorer():
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(user32.GetForegroundWindow(), buf, 256)
        return buf.value in ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW")

    def active_tab(windows):
        """No Explorer com abas, encontra a aba que está visível."""
        import pythoncom
        from win32com.shell import shell as shell_ext
        for window in windows:
            try:
                provider = window._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
                browser = provider.QueryService(shell_ext.IID_IShellBrowser, shell_ext.IID_IShellBrowser)
                if user32.IsWindowVisible(browser.QueryActiveShellView().GetWindow()):
                    return window
            except Exception:
                continue
        return windows[0]

    def explorer_selection():
        """Arquivos selecionados na aba do Explorer ou na Área de Trabalho."""
        try:
            import pythoncom
            import win32com.client
            fg = user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(fg, buf, 256)
            shell = win32com.client.Dispatch("Shell.Application")
            if buf.value in ("Progman", "WorkerW"):
                empty = win32com.client.VARIANT(pythoncom.VT_EMPTY, None)
                handle = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                window = shell.Windows().FindWindowSW(0, empty, 8, handle, 1)
            else:
                matches = []
                for candidate in shell.Windows():
                    try:
                        if int(candidate.HWND) == int(fg or 0):
                            matches.append(candidate)
                    except Exception:
                        continue
                if not matches:
                    return []
                window = matches[0] if len(matches) == 1 else active_tab(matches)
            return [item.Path for item in window.Document.SelectedItems()]
        except Exception:
            return []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    user32.MonitorFromPoint.restype = VP
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [VP, ctypes.POINTER(MONITORINFO)]

    def monitor_work_area(x, y):
        """Área útil da tela onde o cursor está (sem a barra de tarefas)."""
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return (x - 10000, y - 10000, x + 10000, y + 10000)
        r = info.rcWork
        return (r.left, r.top, r.right, r.bottom)

    gdi32.BitBlt.argtypes = [VP, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, VP, ctypes.c_int, ctypes.c_int,
                             ctypes.c_uint32]
    user32.SetWindowPos.argtypes = [VP, VP, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.IsIconic.argtypes = [VP]
    user32.IsWindowVisible.argtypes = [VP]
    user32.GetWindowRect.argtypes = [VP, ctypes.POINTER(wintypes.RECT)]

    def grab_region(x, y, width, height):
        """Copia uma parte da tela."""
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = VP()
        bitmap = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(mem, bitmap)
        try:
            gdi32.BitBlt(mem, 0, 0, width, height, screen, x, y, 0x00CC0020)
            raw = ctypes.string_at(bits, width * height * 4)
        finally:
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)
        return Image.frombytes("RGB", (width, height), raw, "raw", "BGRX")

    user32.SetWindowDisplayAffinity.argtypes = [VP, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL

    def hide_from_capture(hwnds, hidden):
        """Por um instante, tira a janela da cópia de tela para enxergar o que há atrás dela."""
        ok = True
        for hwnd in hwnds:
            ok = bool(user32.SetWindowDisplayAffinity(hwnd, 0x11 if hidden else 0)) and ok
        return ok

    def move_below(hwnd, owner, x, y):
        user32.SetWindowPos(hwnd, owner, x, y, 0, 0, 0x0001 | 0x0010)

    def set_layered_style(hwnd, click_through):
        flags = 0x80000 | 0x80 | 0x08000000  # layered, toolwindow, noactivate
        if click_through:
            flags |= 0x20
        user32.SetWindowLongW(hwnd, -20, user32.GetWindowLongW(hwnd, -20) | flags)

    def is_showing(hwnd):
        return bool(user32.IsWindowVisible(hwnd)) and not user32.IsIconic(hwnd)

    def window_bounds(hwnd):
        rect = wintypes.RECT()
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(VP(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if result != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    def place_below(hwnd, owner):
        user32.SetWindowPos(hwnd, owner, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # não move, não redimensiona, sem foco

    def set_caption_color(hwnd, background, text):
        def colorref(value):
            value = value.lstrip("#")
            return int(value[4:6] + value[2:4] + value[0:2], 16)
        for attribute, value in ((35, background), (36, text)):
            color = ctypes.c_int(colorref(value))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(VP(hwnd), attribute, ctypes.byref(color), ctypes.sizeof(color))

    class MouseWatch:
        """Enquanto a roda está aberta, avisa o momento exato em que o botão é solto."""
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        def __init__(self):
            self.left = False
            self.running = False
            self.thread_id = None
            self.proc = None
            self.release_at = None

        def start(self):
            if self.running:
                return
            self.left = True
            self.release_at = None
            self.running = True
            self.ready = threading.Event()
            threading.Thread(target=self.loop, daemon=True).start()
            self.ready.wait(0.3)

        def stop(self):
            if self.running and self.thread_id:
                user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
            self.running = False

        def handle(self, code, message, data):
            if code >= 0 and message == 0x0202:  # botão esquerdo solto, com o ponto exato
                point = ctypes.cast(data, ctypes.POINTER(wintypes.POINT)).contents
                self.release_at = (point.x, point.y)
                self.left = False

        def loop(self):
            kernel = ctypes.windll.kernel32
            kernel.GetModuleHandleW.restype = VP
            kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            user32.SetWindowsHookExW.restype = VP
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, self.HOOKPROC, VP, wintypes.DWORD]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.CallNextHookEx.argtypes = [VP, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.UnhookWindowsHookEx.argtypes = [VP]

            def callback(code, message, data):
                self.handle(code, message, data)
                return user32.CallNextHookEx(None, code, message, data)

            self.proc = self.HOOKPROC(callback)
            self.thread_id = kernel.GetCurrentThreadId()
            hook = user32.SetWindowsHookExW(14, self.proc, kernel.GetModuleHandleW(None), 0)
            self.ready.set()
            if not hook:
                self.running = False
                return
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                pass
            user32.UnhookWindowsHookEx(hook)

    def push_layered(hwnd, img, x, y, alpha=255):
        """Mostra uma imagem RGBA com transparência real (bordas suaves)."""
        w, h = img.size
        r, g, b, a = img.split()
        from PIL import ImageChops
        r, g, b = (ImageChops.multiply(ch, a) for ch in (r, g, b))  # pré-multiplica
        data = Image.merge("RGBA", (b, g, r, a)).tobytes()
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = VP()
        hbmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(mem, hbmp)
        blend = BLENDFUNCTION(0, 0, alpha, 1)
        user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(wintypes.POINT(x, y)),
                                   ctypes.byref(wintypes.SIZE(w, h)), mem,
                                   ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
