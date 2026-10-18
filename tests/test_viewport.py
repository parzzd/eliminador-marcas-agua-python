import unittest

from limpiacolor.viewport import Viewport


class ViewportTests(unittest.TestCase):
    def view(self):
        view = Viewport()
        view.set_image(1000, 800)
        view.resize(500, 400)
        return view

    def test_fit_and_image_pixel_mapping(self):
        view = self.view()
        self.assertEqual(view.scale, 0.5)
        self.assertEqual(view.image_point(125, 100), (250, 200))

    def test_zoom_keeps_pixel_under_cursor(self):
        view = self.view()
        before = view.image_coordinates(200, 180)
        view.zoom_at(2.5, 200, 180)
        self.assertAlmostEqual(view.image_coordinates(200, 180)[0], before[0])
        self.assertAlmostEqual(view.image_coordinates(200, 180)[1], before[1])

    def test_coordinate_roundtrip_after_zoom_and_pan(self):
        view = self.view()
        view.zoom_at(4.0, 250, 200)
        view.pan(-30, 25)
        for point in ((401, 310), (560, 482), (580, 370)):
            screen = view.canvas_point(point[0] + 0.5, point[1] + 0.5)
            self.assertEqual(view.image_point(*screen), point)

    def test_letterbox_is_not_a_pixel_but_can_start_clamped_selection(self):
        view = self.view()
        view.resize(500, 600)
        self.assertIsNone(view.image_point(100, 20))
        self.assertEqual(view.image_point(100, 20, clamp=True), (200, 0))

    def test_negative_fraction_does_not_select_first_pixel(self):
        view = self.view()
        self.assertIsNone(view.image_point(-0.01, 100))

    def test_pan_stays_within_image(self):
        view = self.view()
        view.zoom_at(4, 250, 200)
        view.pan(100000, -100000)
        self.assertEqual(view.image_point(0, 0), (0, 600))
        self.assertEqual(view.image_point(499, 399), (249, 799))

    def test_zoom_limits_and_reset(self):
        view = self.view()
        view.zoom_at(100, 250, 200)
        self.assertEqual(view.zoom, 32)
        view.fit()
        self.assertEqual(view.zoom, 1)
        self.assertEqual(view.offset, (0, 0))
        view.zoom_at(0.1, 250, 200)
        self.assertEqual(view.zoom, 1)

    def test_frame_refresh_preserves_zoom_but_new_dimensions_reset_it(self):
        view = self.view()
        view.zoom_at(3, 250, 200)
        view.set_image(1000, 800)
        self.assertEqual(view.zoom, 3)
        view.set_image(1920, 1080)
        self.assertEqual(view.zoom, 1)
        self.assertEqual((view.center_x, view.center_y), (960, 540))

    def test_resize_keeps_center_and_valid_mapping(self):
        view = self.view()
        view.zoom_at(3, 250, 200)
        view.resize(1000, 600)
        self.assertEqual(view.image_point(500, 300), (500, 400))


if __name__ == "__main__":
    unittest.main()
