import unittest

from PIL import Image

from main import CLIPBOARD_SETTLE_TIME, SnipWatcher


class BrokenImage(Image.Image):
    def load(self):
        raise OSError("clipboard is still rendering")


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.sequence = 10
        self.calls = 0
        self.image = Image.new("RGB", (4, 3), "white")

    def watcher(self, grabber=None):
        def default_grabber():
            self.calls += 1
            return self.image

        return SnipWatcher(
            sequence=lambda: self.sequence,
            grabber=grabber or default_grabber,
            clock=lambda: self.now,
        )

    def test_waits_for_new_stable_clipboard_image(self):
        watcher = self.watcher()
        watcher._on_hotkey()
        self.assertEqual(watcher.poll()[0], "selecting")
        self.assertEqual(self.calls, 0)

        self.sequence += 1
        self.now += 0.1
        self.assertEqual(watcher.poll()[0], "selecting")
        self.assertEqual(self.calls, 0)

        self.now += CLIPBOARD_SETTLE_TIME + 0.01
        state, image = watcher.poll()
        self.assertEqual(state, "captured")
        self.assertEqual(image.size, (4, 3))
        self.assertEqual(watcher.poll()[0], "ready")

    def test_retries_when_image_is_not_ready(self):
        images = iter([None, BrokenImage(), self.image])
        watcher = self.watcher(grabber=lambda: next(images))
        watcher._on_hotkey()
        self.sequence += 1
        watcher.poll()
        self.now += 0.5
        self.assertEqual(watcher.poll()[0], "selecting")
        self.assertEqual(watcher.poll()[0], "selecting")
        self.assertEqual(watcher.poll()[0], "captured")

    def test_retries_if_clipboard_changes_during_read(self):
        def grabber():
            self.calls += 1
            if self.calls == 1:
                self.sequence += 1
            return self.image

        watcher = self.watcher(grabber=grabber)
        watcher._on_hotkey()
        self.sequence += 1
        watcher.poll()
        self.now += 0.5
        self.assertEqual(watcher.poll()[0], "selecting")
        self.assertEqual(watcher.poll()[0], "selecting")
        self.now += 0.5
        self.assertEqual(watcher.poll()[0], "captured")

    def test_reports_timeout(self):
        watcher = self.watcher()
        watcher._on_hotkey()
        self.now += 121
        self.assertEqual(watcher.poll()[0], "timeout")
        self.assertEqual(watcher.poll()[0], "ready")

    def test_second_capture_can_follow_quickly(self):
        watcher = self.watcher()
        watcher._on_hotkey()
        self.sequence += 1
        watcher.poll()
        self.now += 0.5
        self.assertEqual(watcher.poll()[0], "captured")

        watcher._on_hotkey()
        self.sequence += 1
        watcher.poll()
        self.now += 0.5
        self.assertEqual(watcher.poll()[0], "captured")


if __name__ == "__main__":
    unittest.main()
