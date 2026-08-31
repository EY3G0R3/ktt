from types import SimpleNamespace
from collections import namedtuple
import importlib
import sys
import unittest
from unittest.mock import patch

from ktt.tab_bar_renderer import (
    LEFT_CAP,
    RIGHT_CAP,
    draw_vertical_tab,
    install_vertical_tab_layout,
    update_vertical_tab_bar,
)


CellRange = namedtuple("CellRange", "start end")
TabExtent = namedtuple("TabExtent", "tab_id x y")


class FakeScreen:
    def __init__(self) -> None:
        self.cursor = SimpleNamespace(x=0, fg=None, bg=None)
        self.drawn = []

    def draw(self, value: str) -> None:
        self.drawn.append(value)
        self.cursor.x += len(value)


class GridScreen(FakeScreen):
    def __init__(self, *, lines: int, columns: int) -> None:
        super().__init__()
        self.lines = lines
        self.columns = columns
        self.cursor.y = 0
        self.cursor.bold = False
        self.cursor.italic = False
        self.drawn_at = []

    def draw(self, value: str) -> None:
        self.drawn_at.append((self.cursor.y, self.cursor.x, value))
        super().draw(value)

    def erase_in_display(self, _mode: int, _private: bool) -> None:
        pass


class FakeDrawData:
    default_bg = 0

    @staticmethod
    def tab_bg(tab) -> int:
        return 7 if tab.is_active else 3

    @staticmethod
    def tab_fg(_tab) -> int:
        return 9


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

        self.assertEqual(result, 5)
        self.assertEqual(screen.drawn, [LEFT_CAP, "abc", RIGHT_CAP])

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
        self.assertEqual(screen.drawn, [LEFT_CAP, "abc", "   ", RIGHT_CAP])
        self.assertEqual(screen.cursor.bg, 7)

    def test_non_content_rows_form_a_tapered_three_row_card(self) -> None:
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
            panel_background=3,
            line_index=0,
            card_height=3,
            for_layout=False,
        )

        self.assertEqual(result, 8)
        self.assertEqual(screen.drawn, [" ", "      ", " "])
        self.assertEqual(screen.cursor.bg, 3)

    def test_tree_indent_shifts_the_complete_card(self) -> None:
        screen = FakeScreen()

        result = draw_vertical_tab(
            screen=screen,
            draw_title=draw_short_title,
            draw_data=object(),
            tab=object(),
            before=0,
            max_tab_length=12,
            index=1,
            tab_background=7,
            panel_background=3,
            leading_cells=4,
            line_index=1,
            card_height=3,
            for_layout=False,
        )

        self.assertEqual(result, 12)
        self.assertEqual(
            screen.drawn,
            ["    ", LEFT_CAP, "abc", "   ", RIGHT_CAP],
        )

    def test_native_update_centers_three_row_cards_and_click_extents(self) -> None:
        screen = GridScreen(lines=15, columns=10)
        owner = SimpleNamespace(
            screen=screen,
            tab_bar_align="center",
            draw_data=FakeDrawData(),
            active_font_style=(True, False),
            inactive_font_style=(False, False),
        )
        owner._update_edge_defaults = lambda _vertical: False

        def draw_func(data, target, tab, before, limit, index, _last, extra):
            return draw_vertical_tab(
                screen=target,
                draw_title=draw_short_title,
                draw_data=data,
                tab=tab,
                before=before,
                max_tab_length=limit,
                index=index,
                tab_background=target.cursor.bg,
                panel_background=extra.ktt_panel_background,
                line_index=extra.ktt_line_index,
                card_height=extra.ktt_card_height,
                for_layout=False,
            )

        owner.draw_func = draw_func
        tabs = tuple(
            SimpleNamespace(tab_id=index + 1, is_active=index == 1)
            for index in range(3)
        )

        update_vertical_tab_bar(
            owner,
            tabs,
            as_rgb=lambda value: value,
            color_as_int=int,
            cell_range_type=CellRange,
            tab_extent_type=TabExtent,
            extra_data_type=lambda: SimpleNamespace(for_layout=False),
        )

        self.assertEqual(
            [(item.y.start, item.y.end) for item in owner.tab_extents],
            [(2, 4), (6, 8), (10, 12)],
        )
        title_rows = [
            row for row, _column, value in screen.drawn_at if value == "abc"
        ]
        self.assertEqual(title_rows, [3, 7, 11])

    def test_layout_wrapper_delegates_when_unmanaged_or_drawer_is_plain(
        self,
    ) -> None:
        class TabBar:
            def update_vertical(self, data):
                return ("kitty", data)

        original = TabBar.update_vertical
        install_vertical_tab_layout(TabBar, is_enabled=lambda: False)
        owner = TabBar()
        owner.draw_func = SimpleNamespace(_ktt_vertical_cards=True)
        self.assertEqual(owner.update_vertical((1,)), ("kitty", (1,)))

        install_vertical_tab_layout(TabBar, is_enabled=lambda: True)
        owner.draw_func = lambda: None
        self.assertEqual(owner.update_vertical((2,)), ("kitty", (2,)))
        self.assertIs(
            TabBar.update_vertical._ktt_original_update_vertical,
            original,
        )


if __name__ == "__main__":
    unittest.main()
