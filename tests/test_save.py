import unittest
from pathlib import Path

from PIL import Image

from main import save_image


class SaveTests(unittest.TestCase):
    def test_png_and_jpg_are_written_without_overwriting(self):
        image = Image.new("RGBA", (20, 10), (40, 80, 120, 160))
        folder = Path(__file__).parent
        files = []
        try:
            first = save_image(image, folder, "PNG")
            files.append(first)
            second = save_image(image, folder, "PNG")
            files.append(second)
            jpeg = save_image(image, folder, "JPG")
            files.append(jpeg)

            self.assertNotEqual(first, second)
            with Image.open(first) as saved:
                self.assertEqual(saved.format, "PNG")
                self.assertEqual(saved.size, (20, 10))
            with Image.open(jpeg) as saved:
                self.assertEqual(saved.format, "JPEG")
                self.assertEqual(saved.size, (20, 10))
        finally:
            for path in files:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
