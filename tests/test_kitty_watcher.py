from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from ktt import kitty_watcher
from ktt.native_tabs import (
    NATIVE_MANAGED_ATTRIBUTE,
    NATIVE_MARKER_ATTRIBUTE,
    NATIVE_STYLE_RECOVERY_ATTRIBUTE,
)


LEFT_EDGE = 1
RIGHT_EDGE = 2
BOTTOM_EDGE = 3


class FakeManager:
    def __init__(self) -> None:
        self.os_window_id = 7
        self.tabs = []
        self.active_tab = None
        self.active_tab_history = []
        self.resize_calls = 0

    def resize(self) -> None:
        self.resize_calls += 1

    def __iter__(self):
        return iter(self.tabs)


class FakeBoss:
    def __init__(self) -> None:
        self.options = SimpleNamespace(
            tab_bar_edge=BOTTOM_EDGE,
            tab_bar_style="fade",
            tab_bar_align="left",
            tab_bar_min_tabs=2,
            tab_title_max_length=30,
            drag_threshold=5,
            config_overrides=("font_size 14",),
        )
        self.persistent = {
            key: getattr(self.options, key)
            for key in (
                "tab_bar_edge",
                "tab_bar_style",
                "tab_bar_align",
                "tab_bar_min_tabs",
                "tab_title_max_length",
                "drag_threshold",
            )
        }
        self.all_tab_managers = [FakeManager()]
        self.loads: list[tuple[str, ...]] = []

    def load_config_file(self, *, apply_overrides, overrides) -> None:
        if apply_overrides:
            raise AssertionError("startup must preserve process-local overrides")
        self.loads.append(tuple(overrides))
        for key, value in self.persistent.items():
            setattr(self.options, key, value)
        self.options.config_overrides = tuple(overrides)
        for override in overrides:
            key, value = override.replace("=", " ", 1).split(None, 1)
            if key == "tab_bar_edge":
                self.options.tab_bar_edge = {
                    "left": LEFT_EDGE,
                    "right": RIGHT_EDGE,
                    "bottom": BOTTOM_EDGE,
                }[value]
            elif key == "tab_bar_style":
                self.options.tab_bar_style = value
            elif key == "tab_bar_align":
                self.options.tab_bar_align = value
            elif key == "tab_bar_min_tabs":
                self.options.tab_bar_min_tabs = int(value)
            elif key == "tab_title_max_length":
                self.options.tab_title_max_length = int(value)
            elif key == "drag_threshold":
                self.options.drag_threshold = int(value)


class KittyWatcherStartupTests(unittest.TestCase):
    def test_startup_enables_ktt_and_waits_for_a_second_tab(self) -> None:
        boss = FakeBoss()
        logs: list[str] = []

        kitty_watcher._configure_startup(
            boss,
            (0, 48, 2),
            lambda: boss.options,
            LEFT_EDGE,
            RIGHT_EDGE,
            logs.append,
        )

        self.assertEqual(len(boss.loads), 2)
        self.assertEqual(boss.options.tab_bar_edge, LEFT_EDGE)
        self.assertEqual(boss.options.tab_bar_style, "custom")
        self.assertEqual(boss.options.tab_bar_align, "center")
        self.assertEqual(boss.options.tab_bar_min_tabs, 2)
        self.assertEqual(boss.options.drag_threshold, 0)
        self.assertTrue(getattr(boss, NATIVE_MARKER_ATTRIBUTE))
        self.assertTrue(getattr(boss, NATIVE_MANAGED_ATTRIBUTE))
        self.assertEqual(boss.all_tab_managers[0].resize_calls, 2)
        self.assertEqual(logs, [])

    def test_startup_failure_falls_back_without_ktt_side_effects(self) -> None:
        boss = FakeBoss()
        logs: list[str] = []
        closed: list[bool] = []
        boss._ktt_native_card_state = SimpleNamespace(
            close=lambda: closed.append(True)
        )

        def fail_after_partial_enable(*_args, **_kwargs) -> None:
            boss.options.config_overrides = (
                "font_size 14",
                "tab_bar_style custom",
                "drag_threshold 0",
            )
            setattr(boss, NATIVE_MARKER_ATTRIBUTE, True)
            setattr(boss, NATIVE_MANAGED_ATTRIBUTE, True)
            setattr(boss, NATIVE_STYLE_RECOVERY_ATTRIBUTE, True)
            raise ImportError("broken renderer")

        with patch.object(
            kitty_watcher, "_apply_ktt", side_effect=fail_after_partial_enable
        ):
            kitty_watcher._configure_startup(
                boss,
                (0, 48, 2),
                lambda: boss.options,
                LEFT_EDGE,
                RIGHT_EDGE,
                logs.append,
            )

        self.assertEqual(boss.options.tab_bar_edge, LEFT_EDGE)
        self.assertEqual(boss.options.tab_bar_style, "fade")
        self.assertEqual(boss.options.tab_bar_min_tabs, 2)
        self.assertEqual(boss.options.drag_threshold, 5)
        self.assertFalse(getattr(boss, NATIVE_MARKER_ATTRIBUTE))
        self.assertFalse(getattr(boss, NATIVE_MANAGED_ATTRIBUTE))
        self.assertFalse(getattr(boss, NATIVE_STYLE_RECOVERY_ATTRIBUTE))
        self.assertFalse(hasattr(boss, "_ktt_native_card_state"))
        self.assertEqual(closed, [True])
        self.assertIn("KTT startup failed", logs[0])

    def test_old_kitty_keeps_the_persistent_tab_bar(self) -> None:
        boss = FakeBoss()

        kitty_watcher._configure_startup(
            boss,
            (0, 47, 4),
            lambda: boss.options,
            None,
            None,
            self.fail,
        )

        self.assertEqual(boss.loads, [])

    def test_old_kitty_does_not_import_native_edge_constants(self) -> None:
        kitty = ModuleType("kitty")
        kitty.__path__ = []
        constants = ModuleType("kitty.constants")
        constants.version = (0, 47, 4)
        fast_data_types = ModuleType("kitty.fast_data_types")

        modules = {
            "kitty": kitty,
            "kitty.constants": constants,
            "kitty.fast_data_types": fast_data_types,
        }
        with patch.dict(sys.modules, modules):
            kitty_watcher._configure_from_kitty(FakeBoss())

    def test_fallback_replaces_only_ktt_owned_overrides(self) -> None:
        merged = kitty_watcher._merge_overrides(
            (
                "font_size 14",
                "tab_bar_style custom",
                "tab_bar_min_tabs=1",
                "drag_threshold 0",
            ),
            kitty_watcher.VERTICAL_FALLBACK_OVERRIDES,
        )

        self.assertEqual(merged[0], "font_size 14")
        self.assertEqual(merged[1:], kitty_watcher.VERTICAL_FALLBACK_OVERRIDES)


if __name__ == "__main__":
    unittest.main()
