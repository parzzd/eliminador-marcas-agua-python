import threading
import unittest

import numpy as np

from limpiacolor.core import ColorTarget, ProcessingCancelled, Settings, make_mask, process_frame


class MaskTests(unittest.TestCase):
    def test_multiple_colors_and_rgb_distance(self):
        image = np.array([[[255, 0, 0], [0, 255, 0], [250, 0, 0], [0, 0, 255]]], dtype=np.uint8)
        settings = Settings((ColorTarget((255, 0, 0), 5), ColorTarget((0, 255, 0), 0)), expansion=0)
        np.testing.assert_array_equal(make_mask(image, settings), [[255, 255, 255, 0]])

    def test_distance_does_not_overflow(self):
        image = np.array([[[0, 0, 0], [255, 255, 255], [100, 100, 100]]], dtype=np.uint8)
        settings = Settings((ColorTarget((255, 255, 255), 200),), expansion=0)
        np.testing.assert_array_equal(make_mask(image, settings), [[0, 255, 0]])

    def test_roi_constrains_expanded_mask(self):
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image[4, 4] = 255
        settings = Settings((ColorTarget((255, 255, 255), 0),), expansion=4, roi=(4, 4, 6, 6))
        mask = make_mask(image, settings)
        self.assertTrue(np.any(mask[4:6, 4:6]))
        mask[4:6, 4:6] = 0
        self.assertFalse(np.any(mask))

    def test_empty_palette_is_noop(self):
        image = np.full((8, 8, 3), 77, np.uint8)
        result, mask = process_frame(image, Settings())
        np.testing.assert_array_equal(image, result)
        self.assertFalse(np.any(mask))

    def test_invalid_settings(self):
        for action in [lambda: ColorTarget((300, 0, 0)), lambda: ColorTarget((1, 2, 3), -1),
                       lambda: Settings(radius=0), lambda: Settings(method="unknown")]:
            with self.assertRaises(ValueError):
                action()

    def test_roi_outside_image_is_empty(self):
        image = np.zeros((8, 8, 3), np.uint8)
        settings = Settings((ColorTarget((0, 0, 0)),), roi=(20, 20, 30, 30))
        self.assertFalse(np.any(make_mask(image, settings)))


class FillTests(unittest.TestCase):
    def test_dominant_prefers_frequency_over_brightness(self):
        image = np.full((7, 7, 3), (32, 64, 96), dtype=np.uint8)
        image[3, 3] = (255, 0, 255)
        image[2, 3] = (240, 240, 240)
        settings = Settings((ColorTarget((255, 0, 255), 0),), radius=1, expansion=0)
        result, mask = process_frame(image, settings)
        np.testing.assert_array_equal(result[3, 3], [32, 64, 96])
        np.testing.assert_array_equal(result[mask == 0], image[mask == 0])

    def test_maximum_is_per_channel(self):
        image = np.zeros((5, 5, 3), np.uint8)
        image[2, 2] = (255, 0, 255)
        image[1, 2] = (100, 50, 0)
        image[2, 1] = (0, 90, 150)
        settings = Settings((ColorTarget((255, 0, 255), 0),), method="maximum", radius=1, expansion=0)
        result, _ = process_frame(image, settings)
        np.testing.assert_array_equal(result[2, 2], [100, 90, 150])

    def test_each_region_uses_its_own_neighbors(self):
        image = np.full((20, 30, 3), (32, 64, 96), dtype=np.uint8)
        image[:, 15:] = (80, 144, 176)
        image[7:12, 5:9] = (255, 0, 255)
        image[7:12, 22:26] = (255, 0, 255)
        result, _ = process_frame(image, Settings((ColorTarget((255, 0, 255), 0),), radius=2, expansion=0))
        np.testing.assert_array_equal(result[9, 7], [32, 64, 96])
        np.testing.assert_array_equal(result[9, 24], [80, 144, 176])

    def test_large_mask_and_image_edge(self):
        for method in ("dominant", "maximum"):
            image = np.full((22, 23, 3), (16, 32, 48), dtype=np.uint8)
            image[:14, :14] = (255, 0, 255)
            result, _ = process_frame(image, Settings((ColorTarget((255, 0, 255), 0),), method=method, radius=2, expansion=0))
            np.testing.assert_array_equal(result, np.full_like(image, (16, 32, 48)))

    def test_black_neighbors_are_valid(self):
        image = np.zeros((12, 12, 3), np.uint8)
        image[2:10, 2:10] = 255
        result, _ = process_frame(image, Settings((ColorTarget((255, 255, 255), 0),), expansion=0))
        self.assertFalse(np.any(result))

    def test_telea_preserves_unmasked_pixels(self):
        image = np.full((20, 20, 3), 50, np.uint8)
        image[8:12, 8:12] = 255
        result, mask = process_frame(image, Settings((ColorTarget((255, 255, 255), 0),), method="telea", expansion=0))
        np.testing.assert_array_equal(result[mask == 0], image[mask == 0])
        self.assertLess(int(result[10, 10].max()), 70)

    def test_full_mask_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "toda la imagen"):
            process_frame(np.zeros((10, 10, 3), np.uint8), Settings((ColorTarget((0, 0, 0), 0),)))

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ProcessingCancelled):
            process_frame(np.zeros((10, 10, 3), np.uint8), Settings(), cancel)

    def test_mask_is_recomputed_for_moving_colors(self):
        settings = Settings((ColorTarget((255, 0, 255), 0),), expansion=0)
        for x in (2, 7, 12):
            image = np.full((10, 16, 3), (40, 80, 120), np.uint8)
            image[4:6, x:x+2] = (255, 0, 255)
            result, mask = process_frame(image, settings)
            self.assertEqual(np.count_nonzero(mask), 4)
            np.testing.assert_array_equal(result[4, x], [40, 80, 120])


if __name__ == "__main__":
    unittest.main()
