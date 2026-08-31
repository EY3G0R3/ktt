from types import SimpleNamespace
import importlib
import sys
import unittest
from unittest.mock import patch

from ktt.tab_bar_renderer import draw_vertical_tab


class FakeScreen:
    def __init__(self) -> None:
        self.cursor = SimpleNamespace(x=0, bg=None)
        self.drawn = []

    def draw(self, value: str) -> None:
        self.drawn.append(value)
        self.cursor.x += len(value)


def draw_short_title(_data, screen, _tab, _index, _limit) -> None:
    screen.draw("abc")


class VerticalTabRendererTests(unittest.TestCase):
    def test_canonical_renderer_import_has_no_kitty_dependency(self) -> None:
        kitty_modules = {
            name: None
            for name in tuple(sys.modules)
            if name == "kitty" or name.startswith("kitty.")
        }
        with patch.dict(
            sys.modules,
            kitty_modules,
        ):
            module = importlib.reload(sys.modules[draw_vertical_tab.__module__])

        self.assertTrue(callable(module.draw_vertical_tab))

    def test_layout_pass_reports_ideal_width_without_row_fill(self) -> None:
        screen = FakeScreen()

        result = draw_vertical_tab(
            screen=screen,
            draw_title=draw_short_title,
            draw_data=object(),
            tab=object(),
            before=0,
            max_tab_length=8,
            index=1,
            tab_background=7,
            for_layout=True,
        )

        self.assertEqual(result, 4)
        self.assertEqual(screen.drawn, [" ", "abc"])

    def test_render_pass_fills_exact_row_width(self) -> None:
        screen = FakeScreen()

        result = draw_vertical_tab(
            screen=screen,
            draw_title=draw_short_title,
            draw_data=object(),
            tab=object(),
            before=0,
            max_tab_length=8,
            index=1,
            tab_background=7,
            for_layout=False,
        )

        self.assertEqual(result, 8)
        self.assertEqual(screen.drawn, [" ", "abc", "    "])
        self.assertEqual(screen.cursor.bg, 7)


if __name__ == "__main__":
    unittest.main()
