"""Small Windows tray icon for a background Kadr window."""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

import win32api
import win32con
import win32gui
import winerror


TRAY_MESSAGE = win32con.WM_USER + 20
SHOW_COMMAND = 101
EXIT_COMMAND = 102


class TrayIcon:
    def __init__(self, events: queue.SimpleQueue[str]) -> None:
        self.events = events
        self.hwnd: int | None = None
        self.error: Exception | None = None
        self.ready = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="Kadr tray", daemon=True)
        self.thread.start()
        self.ready.wait(timeout=3)

    @property
    def available(self) -> bool:
        return self.hwnd is not None and self.error is None

    def stop(self) -> None:
        if self.hwnd is not None:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def _run(self) -> None:
        try:
            taskbar_restart = win32gui.RegisterWindowMessage("TaskbarCreated")
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = "KadrTrayWindow"
            window_class.lpfnWndProc = {
                taskbar_restart: self._add_icon,
                TRAY_MESSAGE: self._on_tray,
                win32con.WM_COMMAND: self._on_command,
                win32con.WM_CLOSE: self._on_close,
                win32con.WM_DESTROY: self._on_destroy,
            }
            try:
                win32gui.RegisterClass(window_class)
            except win32gui.error as exc:
                if exc.winerror != winerror.ERROR_CLASS_ALREADY_EXISTS:
                    raise
            self.hwnd = win32gui.CreateWindow(
                window_class.lpszClassName, "Kadr tray", win32con.WS_OVERLAPPED,
                0, 0, 0, 0, 0, 0, window_class.hInstance, None,
            )
            self._add_icon(self.hwnd, 0, 0, 0)
        except Exception as exc:
            self.error = exc
        finally:
            self.ready.set()
        if self.available:
            win32gui.PumpMessages()

    def _add_icon(self, hwnd: int, _msg: int, _wparam: int, _lparam: int) -> int:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        icon_file = root / "assets" / "kadr.ico"
        if icon_file.exists():
            icon = win32gui.LoadImage(0, str(icon_file), win32con.IMAGE_ICON, 0, 0,
                                      win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
        else:
            icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        info = (hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                TRAY_MESSAGE, icon, "Kadr - screenshot saver")
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, info)
        except win32gui.error:
            # Explorer may start later.
            pass
        return 0

    def _on_tray(self, hwnd: int, _msg: int, _wparam: int, lparam: int) -> int:
        if lparam == win32con.WM_LBUTTONDBLCLK:
            self.events.put("show")
        elif lparam == win32con.WM_RBUTTONUP:
            menu = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(menu, win32con.MF_STRING, SHOW_COMMAND, "Open Kadr")
            win32gui.AppendMenu(menu, win32con.MF_STRING, EXIT_COMMAND, "Quit")
            x, y = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(hwnd)
            win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, x, y, 0, hwnd, None)
            win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
            win32gui.DestroyMenu(menu)
        return 1

    def _on_command(self, _hwnd: int, _msg: int, wparam: int, _lparam: int) -> int:
        command = win32api.LOWORD(wparam)
        if command == SHOW_COMMAND:
            self.events.put("show")
        elif command == EXIT_COMMAND:
            self.events.put("exit")
        return 0

    def _on_close(self, hwnd: int, _msg: int, _wparam: int, _lparam: int) -> int:
        win32gui.DestroyWindow(hwnd)
        return 0

    def _on_destroy(self, hwnd: int, _msg: int, _wparam: int, _lparam: int) -> int:
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
        except win32gui.error:
            pass
        self.hwnd = None
        win32gui.PostQuitMessage(0)
        return 0
