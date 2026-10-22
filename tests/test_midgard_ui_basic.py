import importlib.util
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

HAVE_PYGAME = importlib.util.find_spec("pygame") is not None
if HAVE_PYGAME:
    import pygame

    from wyrd.midgard.ui.assets import Assets
    from wyrd.midgard.ui.draw import (
        Button,
        draw_number,
        draw_text,
        draw_time,
        world_to_screen,
        y_down,
    )
    from wyrd.midgard.ui.view import View, initial_window_size, present


def setUpModule() -> None:
    if HAVE_PYGAME:
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((100, 100))


def tearDownModule() -> None:
    if HAVE_PYGAME:
        pygame.quit()


@unittest.skipUnless(HAVE_PYGAME, "pygame-ce is not installed")
class ViewTest(unittest.TestCase):
    def test_view_layout(self) -> None:
        v = View((1280, 1380))
        self.assertEqual(v.layout((640, 690)), (0.5, (0, 0)))
        self.assertEqual(v.layout((1280, 690)), (0.5, (320, 0)))
        w = (1280, 690)
        self.assertEqual(v.to_logical((320, 0), w), (0, 0))
        self.assertIsNone(v.to_logical((319, 0), w))
        self.assertEqual(v.to_logical((959, 345), w), (1278, 690))
        self.assertEqual(v.to_window((0, 0), w), (320, 0))
        self.assertEqual(v.to_logical(v.to_window((200, 300), w), w), (200, 300))
        self.assertGreater(v.layout((1, 1))[0], 0)
        self.assertIsNone(v.to_logical((5, 5), (1, 1)))

    def test_initial_window_size(self) -> None:
        self.assertEqual(initial_window_size((1280, 1380), (1920, 1080)), (890, 960))
        self.assertEqual(initial_window_size((1280, 1380), (3840, 2160)), (1280, 1380))
        self.assertEqual(initial_window_size((1280, 1280), (1920, 1080)), (960, 960))

    def test_present(self) -> None:
        logical = pygame.Surface((1280, 1380))
        logical.fill((255, 0, 0))
        window = pygame.Surface((640, 800))
        present(logical, window, View((1280, 1380)))
        self.assertEqual(window.get_at((10, 100))[:3], (255, 0, 0))
        self.assertEqual(window.get_at((10, 790))[:3], (0, 0, 0))
        present(logical, pygame.Surface((1, 1)), View((1280, 1380)))


@unittest.skipUnless(HAVE_PYGAME, "pygame-ce is not installed")
class DrawTest(unittest.TestCase):
    def test_world_to_screen(self) -> None:
        self.assertEqual(world_to_screen(0, 0), (0, 1316))
        self.assertEqual(world_to_screen(256, 128), (256, 1188))
        self.assertEqual(y_down(950, 200, 1280), 130)

    def test_assets(self) -> None:
        a = Assets()
        self.assertEqual(a.image("data/stop_tran.png").get_size(), (64, 64))
        self.assertIs(a.image("data/stop_tran.png"), a.image("data/stop_tran.png"))
        self.assertEqual(a.level_map(1).get_size(), (1280, 1280))
        frames = a.car_frames()
        self.assertEqual(len(frames), 6)
        self.assertTrue(all(f.get_size() == (64, 64) for f in frames))
        self.assertEqual(a.digit(7, "red").get_size(), (64, 64))
        self.assertEqual(a.digit(7, "chiller").get_size(), (64, 64))
        with self.assertRaises(FileNotFoundError):
            a.image("nope.png")
        self.assertGreater(a.font(28).get_linesize(), 0)
        self.assertGreater(a.credits_font(58).get_linesize(), 0)

    def test_button(self) -> None:
        b = Button((10, 10, 250, 60), "a", "b", "c")
        self.assertTrue(b.contains((10, 10)))
        self.assertTrue(b.contains((260, 70)))
        self.assertFalse(b.contains((261, 70)))
        self.assertFalse(b.contains((9, 10)))

    def test_button_draw(self) -> None:
        a = Assets()
        s = pygame.Surface((400, 100))
        b = Button((0, 0, 250, 60), *(f"ASSET_RESOURCES/level1_{k}.png" for k in
                                       ("normal", "mouse_on", "pressed")))
        for state in ("normal", "hover", "pressed"):
            b.draw(s, a, state)

    def changed(self, s: "pygame.Surface", fill: tuple[int, int, int]) -> bool:
        w, h = s.get_size()
        return any(s.get_at((x, y))[:3] != fill for x in range(0, w, 4) for y in range(0, h, 4))

    def test_draw_number_and_time(self) -> None:
        a = Assets()
        fill = (10, 200, 30)
        s = pygame.Surface((400, 100))
        s.fill(fill)
        draw_number(s, a, 0, 0, 123, 3, 64, 66)
        self.assertTrue(self.changed(s, fill))
        s.fill(fill)
        draw_time(s, a, 0, 0, 7500, 64, 70)
        self.assertTrue(self.changed(s, fill))
        s.fill(fill)
        draw_text(s, a, "hello", (0, 0), 28)
        self.assertTrue(any(s.get_at((x, y))[:3] != fill for x in range(60) for y in range(30)))


if __name__ == "__main__":
    unittest.main()
