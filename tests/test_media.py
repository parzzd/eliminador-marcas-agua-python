from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image

from limpiacolor.core import ColorTarget, ProcessingCancelled, Settings
from limpiacolor.media import NO_WINDOW, export_image, export_video, read_image, read_video_frame, video_info


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        # La expansión incluye el halo cromático del H.264 con submuestreo 4:2:0.
        self.settings = Settings((ColorTarget((255, 0, 255), 70),), expansion=2)

    def tearDown(self):
        self.temp.cleanup()

    def image(self):
        image = np.full((32, 32, 3), (32, 64, 96), np.uint8)
        image[12:20, 12:20] = (255, 0, 255)
        return image

    def make_video(self, odd=False, frames=8, fps=12):
        path = self.folder / "vídeo fuente.mp4"
        size = (33, 31) if odd else (32, 32)
        writer = imageio_ffmpeg.write_frames(str(path), size, fps=fps, codec="libx264",
            pix_fmt_out="yuv444p" if odd else "yuv420p", macro_block_size=1, ffmpeg_log_level="error",
            input_params=["-r", format(fps, ".12g")])
        try:
            writer.send(None)
            for i in range(frames):
                image = np.full((size[1], size[0], 3), (32, 64, 96), np.uint8)
                image[10:17, 5 + i:12 + i] = (255, 0, 255)
                writer.send(image)
        finally:
            writer.close()
        return path

    def test_unicode_image_export_and_alpha(self):
        source, destination = self.folder / "imagen áé.png", self.folder / "salida ñ.png"
        alpha = np.full((32, 32), 128, np.uint8)
        Image.fromarray(np.dstack((self.image(), alpha))).save(source)
        export_image(source, destination, self.settings)
        result, result_alpha = read_image(destination)
        np.testing.assert_array_equal(result_alpha, alpha)
        np.testing.assert_array_equal(result[15, 15], [32, 64, 96])

    def test_original_cannot_be_overwritten(self):
        source = self.folder / "original.png"
        Image.fromarray(self.image()).save(source)
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "original"):
            export_image(source, source, self.settings)
        self.assertEqual(source.read_bytes(), before)

    def test_cancel_preserves_existing_destination(self):
        source, destination = self.folder / "source.png", self.folder / "output.png"
        Image.fromarray(self.image()).save(source)
        destination.write_bytes(b"existing output")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ProcessingCancelled):
            export_image(source, destination, self.settings, cancel)
        self.assertEqual(destination.read_bytes(), b"existing output")
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_image_orientation(self):
        image = Image.new("RGB", (20, 10), (32, 64, 96))
        exif = image.getexif()
        exif[274] = 6
        path = self.folder / "rotated.jpg"
        image.save(path, exif=exif)
        result, _ = read_image(path)
        self.assertEqual(result.shape, (20, 10, 3))

    def test_video_frames_fps_and_moving_mask(self):
        source = self.make_video()
        destination = self.folder / "salida.mp4"
        done = export_video(source, destination, self.settings)
        width, height, fps, count = video_info(destination)
        self.assertEqual((width, height, count, done), (32, 32, 8, 8))
        self.assertAlmostEqual(fps, 12)
        for index in (0, 3, 7):
            frame = read_video_frame(destination, index)
            error = np.abs(frame[12, 8 + index].astype(int) - np.array([32, 64, 96]))
            self.assertLess(int(error.max()), 25)

    def test_odd_dimensions_are_padded_not_cropped(self):
        source = self.make_video(odd=True, frames=2)
        destination = self.folder / "even.mp4"
        export_video(source, destination, Settings(), preserve_audio=False)
        self.assertEqual(video_info(destination)[:2], (34, 32))

    def test_fractional_fps_is_not_rounded_to_two_decimals(self):
        source = self.make_video(frames=3, fps=24000 / 1001)
        destination = self.folder / "fractional.mp4"
        export_video(source, destination, Settings(), preserve_audio=False)
        self.assertAlmostEqual(video_info(destination)[2], 24000 / 1001, places=5)

    def test_audio_is_preserved(self):
        silent = self.make_video()
        source, output = self.folder / "with-audio.mp4", self.folder / "cleaned.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(silent), "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.666667",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(source)], check=True, creationflags=NO_WINDOW)
        export_video(source, output, self.settings)
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(output)],
            capture_output=True, text=True, creationflags=NO_WINDOW)
        self.assertIn("Audio: aac", result.stderr)

    def test_video_cancel_removes_partial_and_preserves_destination(self):
        source = self.make_video()
        destination = self.folder / "existing.mp4"
        destination.write_bytes(b"previous video")
        cancel = threading.Event()

        def progress(done, total, phase):
            if done == 2:
                cancel.set()

        with self.assertRaises(ProcessingCancelled):
            export_video(source, destination, self.settings, cancel, progress)
        self.assertEqual(destination.read_bytes(), b"previous video")
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_invalid_image_export_does_not_replace_destination(self):
        source, destination = self.folder / "source.png", self.folder / "output.png"
        Image.fromarray(np.zeros((10, 10, 3), np.uint8)).save(source)
        destination.write_bytes(b"existing")
        with self.assertRaises(ValueError):
            export_image(source, destination, Settings((ColorTarget((0, 0, 0), 0),)))
        self.assertEqual(destination.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
