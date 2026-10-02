"""Save screenshots made with Win + Shift + S."""

from __future__ import annotations

import ctypes
import io
import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
import winreg
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keyboard
import win32api
import win32clipboard
import win32event
import winerror
from PIL import BmpImagePlugin, Image, ImageGrab, ImageTk

from tray import TrayIcon


APP_NAME = "Kadr"
APP_VERSION = "1.1.0"
CONFIG_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kadr" / "settings.json"
DEFAULT_FOLDER = Path.home() / "Pictures" / "Screenshots"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
HOTKEY = "windows+shift+s"
CAPTURE_TIMEOUT = 120
CLIPBOARD_SETTLE_TIME = 0.35


def make_logger() -> logging.Logger:
    logger = logging.getLogger("kadr")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(CONFIG_FILE.parent / "kadr.log", maxBytes=500_000, backupCount=1, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


logger = make_logger()


def clipboard_sequence() -> int:
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def read_clipboard_image() -> Image.Image | None:
    """Prefer image formats when the clipboard also advertises a file drop."""
    try:
        win32clipboard.OpenClipboard()
        try:
            png_format = win32clipboard.RegisterClipboardFormat("PNG")
            if win32clipboard.IsClipboardFormatAvailable(png_format):
                image_format = "PNG"
                data = win32clipboard.GetClipboardData(png_format)
            elif win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                image_format = "DIB"
                data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
            else:
                image_format = None
                data = None
        finally:
            win32clipboard.CloseClipboard()
    except win32clipboard.error as exc:
        raise OSError(f"Clipboard is busy: {exc}") from exc

    if image_format == "PNG":
        return Image.open(io.BytesIO(data))
    if image_format == "DIB":
        return BmpImagePlugin.DibImageFile(io.BytesIO(data))
    image = ImageGrab.grabclipboard()
    return image if isinstance(image, Image.Image) else None


def load_settings() -> tuple[Path, str]:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    folder = Path(data.get("folder", DEFAULT_FOLDER))
    if not folder.is_dir():
        folder = DEFAULT_FOLDER
    image_format = data.get("format", "PNG")
    if image_format not in ("PNG", "JPG"):
        image_format = "PNG"
    return folder, image_format


def save_settings(folder: Path, image_format: str) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"folder": str(folder), "format": image_format}
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --background'
    python = Path(sys.executable)
    runner = python.with_name("pythonw.exe")
    if not runner.exists():
        runner = python
    return f'"{runner}" "{Path(__file__).resolve()}" --background'


def startup_is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _ = winreg.QueryValueEx(key, "Kadr")
        return command == startup_command()
    except OSError:
        return False


def set_startup(enabled: bool) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "Kadr", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "Kadr")
            except FileNotFoundError:
                pass


def next_filename(folder: Path, image_format: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    extension = ".jpg" if image_format == "JPG" else ".png"
    candidate = folder / f"Screenshot {stamp}{extension}"
    number = 2
    while candidate.exists():
        candidate = folder / f"Screenshot {stamp} ({number}){extension}"
        number += 1
    return candidate


def save_image(image: Image.Image, folder: Path, image_format: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = next_filename(folder, image_format)
    if image_format == "JPG":
        image.convert("RGB").save(path, format="JPEG", quality=92)
    else:
        image.save(path, format="PNG")
    return path


def latest_screenshot(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    shots = (p for p in folder.iterdir() if p.name.startswith(("Screenshot ", "Снимок ")) and p.suffix.lower() in (".png", ".jpg"))
    return max(shots, key=lambda p: p.stat().st_mtime, default=None)


class SnipWatcher:
    """Wait for a new clipboard image after the Windows snipping shortcut."""

    def __init__(self, sequence=clipboard_sequence, grabber=read_clipboard_image, clock=time.monotonic) -> None:
        self._sequence = sequence
        self._grabber = grabber
        self._clock = clock
        self._lock = threading.Lock()
        self._deadline = 0.0
        self._initial_sequence = 0
        self._last_sequence = 0
        self._changed_at = 0.0
        self._last_press = -1_000_000.0
        self._generation = 0
        self._hotkey = None

    def start(self) -> None:
        self._hotkey = keyboard.add_hotkey(HOTKEY, self._on_hotkey, suppress=False)

    def stop(self) -> None:
        if self._hotkey is not None:
            keyboard.remove_hotkey(self._hotkey)

    def _on_hotkey(self) -> None:
        now = self._clock()
        with self._lock:
            if now - self._last_press < 0.3:
                return
            self._last_press = now
            self._initial_sequence = self._sequence()
            self._last_sequence = self._initial_sequence
            self._changed_at = 0.0
            self._deadline = now + CAPTURE_TIMEOUT
            self._generation += 1
        logger.info("Capture shortcut pressed; clipboard sequence %s", self._initial_sequence)

    def poll(self) -> tuple[str, Image.Image | None]:
        with self._lock:
            deadline = self._deadline
            initial_sequence = self._initial_sequence
            last_sequence = self._last_sequence
            changed_at = self._changed_at
            generation = self._generation
        if not deadline:
            return "ready", None
        now = self._clock()
        if now > deadline:
            with self._lock:
                if self._generation == generation:
                    self._deadline = 0
            logger.warning("No clipboard image arrived before timeout")
            return "timeout", None

        sequence = self._sequence()
        if sequence != last_sequence:
            with self._lock:
                if self._generation == generation:
                    self._last_sequence = sequence
                    self._changed_at = now
            changed_at = now
        if sequence == initial_sequence or now - changed_at < CLIPBOARD_SETTLE_TIME:
            return "selecting", None
        try:
            image = self._grabber()
            if self._sequence() != sequence:
                return "selecting", None
            if not isinstance(image, Image.Image):
                return "selecting", None
            image.load()
            image = image.copy()
        except (OSError, ValueError) as exc:
            logger.info("Clipboard image not ready: %s", exc)
            return "selecting", None
        with self._lock:
            if self._generation != generation:
                return "selecting", None
            self._deadline = 0
        logger.info("Clipboard image captured: %s x %s", image.width, image.height)
        return "captured", image


class KadrApp:
    def __init__(self, background: bool = False) -> None:
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.configure(bg="#f4f5f6")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.folder, image_format = load_settings()
        self.folder_text = tk.StringVar(value=str(self.folder))
        self.format_text = tk.StringVar(value=image_format)
        self.autostart = tk.BooleanVar(value=startup_is_enabled())
        self.status_text = tk.StringVar(value="Ready to capture")
        self.filename_text = tk.StringVar(value="No screenshots yet")
        self.last_path: Path | None = None
        self.preview_photo = None
        self._stopped = False
        self.watcher = SnipWatcher()
        self.tray_events: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.tray = TrayIcon(self.tray_events)
        self._build_ui()
        self._show_latest_from_folder()
        self._size_window()
        self.tray.start()
        if background and self.tray.available:
            self.root.withdraw()
        try:
            self.watcher.start()
        except Exception as exc:
            self._set_status(f"Could not register the shortcut: {exc}", error=True)
        if not self.tray.available:
            self._set_status("Tray icon unavailable. Keep this window open to capture screenshots.", error=True)
        self.root.after(180, self._poll)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        shell = tk.Frame(self.root, bg="#f4f5f6", padx=28, pady=24)
        shell.pack(fill="both", expand=True)
        tk.Label(shell, text=APP_NAME, bg="#f4f5f6", fg="#17191c", font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(shell, text="Screenshots from Win + Shift + S are saved as soon as you select an area.", bg="#f4f5f6", fg="#626870", font=("Segoe UI", 10), wraplength=700, justify="left").pack(anchor="w", pady=(3, 20))

        body = tk.Frame(shell, bg="white", highlightbackground="#dfe2e5", highlightthickness=1)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)
        left = tk.Frame(body, bg="white", padx=22, pady=21)
        left.grid(row=0, column=0, sticky="nsew")
        right = tk.Frame(body, bg="white", padx=22, pady=21, highlightbackground="#e8eaec", highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew")

        self.status_label = tk.Label(left, textvariable=self.status_text, bg="white", fg="#287348", font=("Segoe UI", 10, "bold"), wraplength=330, justify="left")
        self.status_label.pack(anchor="w", pady=(0, 24))
        self._section_label(left, "Save folder")
        folder_row = tk.Frame(left, bg="white")
        folder_row.pack(fill="x", pady=(8, 22))
        ttk.Entry(folder_row, textvariable=self.folder_text, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="Browse…", command=self.choose_folder).pack(side="left", padx=(8, 0))

        self._section_label(left, "File format")
        format_row = tk.Frame(left, bg="white")
        format_row.pack(fill="x", pady=(8, 4))
        format_box = ttk.Combobox(format_row, textvariable=self.format_text, values=("PNG", "JPG"), state="readonly", width=8)
        format_box.pack(side="left")
        format_box.bind("<<ComboboxSelected>>", self._format_changed)
        tk.Label(format_row, text="PNG for detail · JPG for smaller files", bg="white", fg="#6b7178", font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))

        tk.Frame(left, bg="#e8eaec", height=1).pack(fill="x", pady=(23, 19))
        ttk.Checkbutton(left, text="Start with Windows", variable=self.autostart, command=self._autostart_changed).pack(anchor="w")
        tk.Label(left, text="Kadr will start in the tray when you sign in.", bg="white", fg="#6b7178", font=("Segoe UI", 9), wraplength=330, justify="left").pack(anchor="w", pady=(7, 0))

        self._section_label(right, "Latest screenshot")
        preview_box = tk.Frame(right, bg="#f3f4f5", width=240, height=160)
        preview_box.pack(fill="x", pady=(12, 13))
        preview_box.pack_propagate(False)
        self.preview_label = tk.Label(preview_box, text="Your screenshot will appear here", bg="#f3f4f5", fg="#858b91", font=("Segoe UI", 9))
        self.preview_label.pack(fill="both", expand=True)
        tk.Label(right, textvariable=self.filename_text, bg="white", fg="#363b40", font=("Segoe UI", 9), wraplength=240, justify="left").pack(anchor="w")
        self.open_button = ttk.Button(right, text="Open screenshot", command=self.open_last)
        self.open_button.pack(anchor="w", pady=(15, 0))
        self.open_button.state(["disabled"])

        footer = tk.Frame(shell, bg="#f4f5f6")
        footer.pack(fill="x", pady=(16, 0))
        tk.Label(footer, text="Close this window to keep Kadr in the tray. Use the tray menu to quit.", bg="#f4f5f6", fg="#737980", font=("Segoe UI", 9), wraplength=600, justify="left").pack(side="left")
        ttk.Button(footer, text="Open folder", command=self.open_folder).pack(side="right")

    @staticmethod
    def _section_label(parent: tk.Widget, text: str) -> None:
        tk.Label(parent, text=text, bg="white", fg="#262b30", font=("Segoe UI", 10, "bold")).pack(anchor="w")

    def _size_window(self) -> None:
        self.root.update_idletasks()
        width = max(760, self.root.winfo_reqwidth() + 16)
        height = max(450, self.root.winfo_reqheight() + 16)
        self.root.minsize(width, height)
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_text.set(text)
        self.status_label.configure(fg="#a43d35" if error else "#287348")

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(parent=self.root, initialdir=self.folder)
        if chosen:
            self.folder = Path(chosen)
            self.folder_text.set(chosen)
            save_settings(self.folder, self.format_text.get())
            self._show_latest_from_folder()

    def open_folder(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        os.startfile(self.folder)

    def _format_changed(self, _event: tk.Event) -> None:
        save_settings(self.folder, self.format_text.get())

    def _autostart_changed(self) -> None:
        try:
            set_startup(self.autostart.get())
        except OSError as exc:
            self.autostart.set(not self.autostart.get())
            messagebox.showerror(APP_NAME, f"Could not change startup settings:\n{exc}", parent=self.root)

    def _show_latest_from_folder(self) -> None:
        path = latest_screenshot(self.folder)
        if path is None:
            self.last_path = None
            self.filename_text.set("No screenshots yet")
            self.preview_label.configure(image="", text="Your screenshot will appear here")
            self.preview_photo = None
            self.open_button.state(["disabled"])
            return
        try:
            with Image.open(path) as image:
                self._show_preview(image.copy(), path)
        except OSError:
            self.filename_text.set(path.name)

    def _show_preview(self, image: Image.Image, path: Path) -> None:
        image.thumbnail((245, 150), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_photo, text="")
        self.filename_text.set(path.name)
        self.last_path = path
        self.open_button.state(["!disabled"])

    def open_last(self) -> None:
        if self.last_path and self.last_path.is_file():
            os.startfile(self.last_path)

    def _poll(self) -> None:
        try:
            self._poll_once()
        except Exception as exc:
            logger.exception("Unexpected capture loop error")
            self._set_status(f"Capture error: {exc}", error=True)
        finally:
            if not self._stopped:
                self.root.after(180, self._poll)

    def _poll_once(self) -> None:
        while True:
            try:
                action = self.tray_events.get_nowait()
            except queue.Empty:
                break
            if action == "show":
                self.show()
            elif action == "exit":
                self.exit_app()
                return
        state, image = self.watcher.poll()
        if image is not None:
            try:
                path = save_image(image, self.folder, self.format_text.get())
                self._show_preview(image, path)
                self._set_status("Screenshot saved")
                logger.info("Saved screenshot to %s", path)
            except OSError as exc:
                self._set_status(f"Could not save screenshot: {exc}", error=True)
                logger.exception("Could not save screenshot")
        elif state == "selecting":
            self._set_status("Select an area on screen…")
        elif state == "timeout":
            self._set_status("No screenshot reached the clipboard. Please try again.", error=True)
        elif self.status_text.get() == "Select an area on screen…":
            self._set_status("Ready to capture")

    def close(self) -> None:
        if self.tray.available:
            self.root.withdraw()
        else:
            self.exit_app()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def exit_app(self) -> None:
        self._stopped = True
        self.watcher.stop()
        self.tray.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    instance = win32event.CreateMutex(None, False, "Local\\KadrScreenshotSaver")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        messagebox.showinfo(APP_NAME, "Kadr is already running. Look for its icon in the system tray.")
    else:
        KadrApp(background="--background" in sys.argv[1:]).run()
