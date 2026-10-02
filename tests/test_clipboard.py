import io
import unittest
from unittest.mock import patch

from PIL import Image

import main


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        image = Image.new("RGB", (8, 6), "navy")
        png = io.BytesIO()
        bmp = io.BytesIO()
        image.save(png, format="PNG")
        image.save(bmp, format="BMP")
        self.png = png.getvalue()
        self.dib = bmp.getvalue()[14:]

    def test_png_wins_over_file_drop(self):
        with (
            patch.object(main.win32clipboard, "OpenClipboard"),
            patch.object(main.win32clipboard, "CloseClipboard"),
            patch.object(main.win32clipboard, "RegisterClipboardFormat", return_value=900),
            patch.object(main.win32clipboard, "IsClipboardFormatAvailable", return_value=True),
            patch.object(main.win32clipboard, "GetClipboardData", return_value=self.png),
            patch.object(main.ImageGrab, "grabclipboard", return_value=["screenshot.png"]) as fallback,
        ):
            image = main.read_clipboard_image()
        image.load()
        self.assertEqual(image.size, (8, 6))
        fallback.assert_not_called()

    def test_dib_without_png(self):
        def available(fmt):
            return fmt == main.win32clipboard.CF_DIB

        with (
            patch.object(main.win32clipboard, "OpenClipboard"),
            patch.object(main.win32clipboard, "CloseClipboard"),
            patch.object(main.win32clipboard, "RegisterClipboardFormat", return_value=900),
            patch.object(main.win32clipboard, "IsClipboardFormatAvailable", side_effect=available),
            patch.object(main.win32clipboard, "GetClipboardData", return_value=self.dib),
        ):
            image = main.read_clipboard_image()
        image.load()
        self.assertEqual(image.size, (8, 6))


if __name__ == "__main__":
    unittest.main()
