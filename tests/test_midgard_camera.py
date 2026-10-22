import unittest

from wyrd.midgard.ui.camera import Camera


class CameraTest(unittest.TestCase):
    def test_start_and_picking(self) -> None:
        c = Camera()
        self.assertEqual(c.zoom, 1.0)
        self.assertEqual((c.x, c.y), (640.0, 690.0))
        self.assertEqual(c.to_world(288, 452), (288.0, 928.0))
        self.assertEqual(c.tile_at(288, 452), (5, 15))
        self.assertIsNone(c.tile_at(10, 50))

    def test_wheel(self) -> None:
        c = Camera()
        c.wheel(-1)
        self.assertEqual(c.zoom, 0.96)
        for _ in range(20):
            c.wheel(-1)
        self.assertEqual(c.zoom, 0.2)
        c.wheel(-1)
        self.assertEqual(c.zoom, 0.2)
        c.wheel(1)
        self.assertEqual(c.zoom, 0.24)
        for _ in range(19):
            c.wheel(1)
        self.assertEqual(c.zoom, 1.0)
        c.wheel(1)
        self.assertEqual(c.zoom, 1.0)

    def test_pan_limits(self) -> None:
        c = Camera()
        c.pan(500, 500)
        self.assertEqual((c.x, c.y), (640.0, 690.0))
        c.zoom = 0.2
        c.pan(-10000, -10000)
        self.assertEqual((c.x, c.y), (128.0, 138.0))
        c.pan(10000, 10000)
        self.assertEqual((c.x, c.y), (1152.0, 1162.0))

    def test_key_zoom(self) -> None:
        c = Camera()
        c.key_zoom_in()
        self.assertEqual(c.zoom, 0.98)
        c.zoom = 0.08
        c.key_zoom_in()
        self.assertEqual(c.zoom, 0.08)
        c = Camera()
        c.key_zoom_out()
        self.assertEqual(c.zoom, 1.0)
        c.zoom = 0.5
        c.key_zoom_out()
        self.assertEqual(c.zoom, 0.52)

    def test_drag_and_visible(self) -> None:
        c = Camera()
        c.zoom = 0.5
        c.drag((100, 100), (110, 90))
        self.assertEqual((c.x, c.y), (630.0, 700.0))
        c.drag((0, 100), (50, 50))
        self.assertEqual((c.x, c.y), (630.0, 700.0))
        c = Camera()
        c.zoom = 0.5
        self.assertEqual(c.visible_rect(), (320.0, 345.0, 640.0, 690.0))


if __name__ == "__main__":
    unittest.main()
