from types import SimpleNamespace
import sys
import tempfile
import unittest

from ktt.native_tabs import (
    HIDDEN_MIN_TABS,
    NATIVE_CARD_STATE_ATTRIBUTE,
    NATIVE_MANAGED_ATTRIBUTE,
    NATIVE_MARKER_ATTRIBUTE,
    NativeVerticalTabsUnsupported,
)
from ktt.native_tabs_runtime import (
    NativeTabsRuntimeError,
    current_edge_name,
    options_hidden,
    parse_action_args,
    run_native_tabs_action,
    temporary_sys_path,
)


LEFT_EDGE = 1
RIGHT_EDGE = 2
BOTTOM_EDGE = 3


class FakeManager:
    def __init__(self, events) -> None:
        self.os_window_id = 7
        self.events = events

    def resize(self) -> None:
        self.events.append("resize")

    def __iter__(self):
        return iter(())


class FakeBoss:
    def __init__(self, options, events, *, apply_config=True) -> None:
        self.options = options
        self.events = events
        self.apply_config = apply_config
        self.persistent = (
            options.tab_bar_edge,
            options.tab_bar_style,
            options.tab_bar_align,
            options.tab_bar_min_tabs,
        )
        self.all_tab_managers = [FakeManager(events)]

    def load_config_file(self, *, apply_overrides, overrides) -> None:
        self.events.append("load")
        if not self.apply_config:
            return
        (
            self.options.tab_bar_edge,
            self.options.tab_bar_style,
            self.options.tab_bar_align,
            self.options.tab_bar_min_tabs,
        ) = self.persistent
        self.options.config_overrides = tuple(overrides)
        for override in overrides:
            key, value = override.replace("=", " ", 1).split(None, 1)
            if key == "tab_bar_edge":
                self.options.tab_bar_edge = {
                    "left": LEFT_EDGE,
                    "right": RIGHT_EDGE,
                    "bottom": BOTTOM_EDGE,
                }[value]
            elif key == "tab_bar_min_tabs":
                self.options.tab_bar_min_tabs = int(value)
            elif key == "tab_bar_style":
                self.options.tab_bar_style = value
            elif key == "tab_bar_align":
                self.options.tab_bar_align = value


class BadFirstPostconditionBoss(FakeBoss):
    def __init__(self, options, events) -> None:
        super().__init__(options, events)
        self.loads = 0

    def load_config_file(self, *, apply_overrides, overrides) -> None:
        self.loads += 1
        super().load_config_file(
            apply_overrides=apply_overrides, overrides=overrides
        )
        if self.loads == 1:
            self.options.tab_bar_edge = BOTTOM_EDGE


class FailSecondResizeManager(FakeManager):
    def __init__(self, events) -> None:
        super().__init__(events)
        self.resize_calls = 0

    def resize(self) -> None:
        self.resize_calls += 1
        self.events.append("resize")
        if self.resize_calls == 2:
            raise RuntimeError("rollback resize failed")


class FakeTabs:
    def __init__(self, boss, events, *, order_error=None) -> None:
        self.boss = boss
        self.events = events
        self.order_error = order_error

    def live_tree_tab_ids(self, manager):
        self.events.append("plan-order")
        return (10, 20)

    def apply_tab_order(self, manager, desired):
        self.events.append("order")
        if not desired:
            return
        if not getattr(self.boss, NATIVE_MARKER_ATTRIBUTE, False):
            raise AssertionError("marker was not set before ordering")
        if self.order_error is not None:
            raise self.order_error


def options(**overrides):
    values = {
        "tab_bar_edge": BOTTOM_EDGE,
        "tab_bar_style": "custom",
        "tab_bar_align": "start",
        "tab_bar_min_tabs": 2,
        "config_overrides": ("font_size 14",),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class NativeTabsRuntimeTests(unittest.TestCase):
    def test_temporary_renderer_import_path_is_removed_after_reload(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            self.assertNotIn(path, sys.path)
            with temporary_sys_path(path):
                self.assertEqual(sys.path[0], path)
            self.assertNotIn(path, sys.path)

    def run_action(
        self,
        *,
        current_options=None,
        apply_config=True,
        order_error=None,
    ):
        events = []
        current_options = current_options or options()
        boss = FakeBoss(current_options, events, apply_config=apply_config)
        logs = []
        plan = run_native_tabs_action(
            boss=boss,
            action="enable",
            running_version=(0, 48, 2),
            options=current_options,
            read_options=lambda: current_options,
            left_edge=LEFT_EDGE,
            right_edge=RIGHT_EDGE,
            kitty_tabs=FakeTabs(boss, events, order_error=order_error),
            log_error=logs.append,
        )
        return plan, boss, events, logs

    def test_argv_action_parsing_accepts_toggle_or_vertical_enable(self) -> None:
        self.assertEqual(parse_action_args(()), "toggle")
        self.assertEqual(parse_action_args(("vertical",)), "enable")
        with self.assertRaises(ValueError):
            parse_action_args(("vertical", "strict"))

    def test_hidden_and_edge_mapping_share_runtime_contract(self) -> None:
        self.assertTrue(options_hidden(options(tab_bar_style="hidden")))
        self.assertTrue(options_hidden(options(tab_bar_min_tabs=HIDDEN_MIN_TABS)))
        self.assertEqual(
            current_edge_name(
                options(tab_bar_edge=RIGHT_EDGE),
                (0, 48, 2),
                LEFT_EDGE,
                RIGHT_EDGE,
            ),
            "right",
        )
        self.assertEqual(
            current_edge_name(options(), (0, 47, 4), None, None),
            "horizontal",
        )

    def test_old_kitty_toggle_is_unsupported(self) -> None:
        events = []
        current_options = options(tab_bar_edge=object())
        boss = FakeBoss(current_options, events)
        action = parse_action_args(())

        with self.assertRaises(NativeVerticalTabsUnsupported):
            run_native_tabs_action(
                boss=boss,
                action=action,
                running_version=(0, 47, 4),
                options=current_options,
                read_options=lambda: current_options,
                left_edge=None,
                right_edge=None,
                kitty_tabs=FakeTabs(boss, events),
                log_error=lambda _message: None,
            )
        self.assertEqual(events, [])

    def test_old_kitty_explicit_enable_fails_before_capture(self) -> None:
        events = []
        current_options = options()
        boss = FakeBoss(current_options, events)

        with self.assertRaises(NativeVerticalTabsUnsupported):
            run_native_tabs_action(
                boss=boss,
                action="enable",
                running_version=(0, 47, 4),
                options=current_options,
                read_options=lambda: current_options,
                left_edge=None,
                right_edge=None,
                kitty_tabs=FakeTabs(boss, events),
                log_error=lambda _message: None,
            )

        self.assertEqual(events, [])

    def test_success_sequence_sets_marker_before_order_and_verifies(self) -> None:
        plan, boss, events, logs = self.run_action()

        self.assertEqual(
            events,
            ["plan-order", "load", "order", "resize"],
        )
        self.assertTrue(getattr(boss, NATIVE_MANAGED_ATTRIBUTE))
        self.assertTrue(getattr(boss, NATIVE_MARKER_ATTRIBUTE))
        self.assertTrue(plan.native_visible)
        self.assertEqual(logs, [])

    def test_reload_closes_background_renderer_state_before_config_load(self) -> None:
        events = []
        current_options = options()
        boss = FakeBoss(current_options, events)
        state = SimpleNamespace(close=lambda: events.append("card-close"))
        setattr(boss, NATIVE_CARD_STATE_ATTRIBUTE, state)

        run_native_tabs_action(
            boss=boss,
            action="enable",
            running_version=(0, 48, 2),
            options=current_options,
            read_options=lambda: current_options,
            left_edge=LEFT_EDGE,
            right_edge=RIGHT_EDGE,
            kitty_tabs=FakeTabs(boss, events),
            log_error=lambda _message: None,
        )

        self.assertLess(events.index("card-close"), events.index("load"))
        self.assertFalse(hasattr(boss, NATIVE_CARD_STATE_ATTRIBUTE))

    def test_maintenance_failure_logs_cleans_up_then_raises(self) -> None:
        events = []
        current_options = options()
        boss = FakeBoss(current_options, events)
        logs = []

        with self.assertRaisesRegex(NativeTabsRuntimeError, "maintenance"):
            run_native_tabs_action(
                boss=boss,
                action="enable",
                running_version=(0, 48, 2),
                options=current_options,
                read_options=lambda: current_options,
                left_edge=LEFT_EDGE,
                right_edge=RIGHT_EDGE,
                kitty_tabs=FakeTabs(
                    boss, events, order_error=RuntimeError("order failed")
                ),
                log_error=logs.append,
            )

        self.assertIn("resize", events)
        self.assertIn("order failed", logs[0])
        self.assertEqual(current_options.config_overrides, ("font_size 14",))
        self.assertFalse(getattr(boss, NATIVE_MARKER_ATTRIBUTE, False))

    def test_failed_postcondition_clears_marker_and_never_succeeds(self) -> None:
        events = []
        previous_overrides = (
            "font_size 14",
            "tab_bar_align center",
        )
        current_options = options(
            tab_bar_align="center", config_overrides=previous_overrides
        )
        boss = BadFirstPostconditionBoss(current_options, events)
        logs = []

        with self.assertRaisesRegex(NativeTabsRuntimeError, "edge"):
            run_native_tabs_action(
                boss=boss,
                action="enable",
                running_version=(0, 48, 2),
                options=current_options,
                read_options=lambda: current_options,
                left_edge=LEFT_EDGE,
                right_edge=RIGHT_EDGE,
                kitty_tabs=FakeTabs(boss, events),
                log_error=logs.append,
            )

        self.assertFalse(getattr(boss, NATIVE_MARKER_ATTRIBUTE, False))
        self.assertEqual(current_options.config_overrides, previous_overrides)
        self.assertEqual(current_options.tab_bar_edge, BOTTOM_EDGE)
        self.assertEqual(current_options.tab_bar_style, "custom")
        self.assertEqual(current_options.tab_bar_min_tabs, 2)
        self.assertIn("postcondition failed", logs[-1])

    def test_rollback_failure_is_explicit_after_user_overrides_restore(self) -> None:
        events = []
        previous_overrides = (
            "font_size 14",
            "tab_bar_align center",
        )
        current_options = options(
            tab_bar_align="center", config_overrides=previous_overrides
        )
        boss = BadFirstPostconditionBoss(current_options, events)
        boss.all_tab_managers = [FailSecondResizeManager(events)]
        logs = []

        with self.assertRaisesRegex(NativeTabsRuntimeError, "rollback was incomplete"):
            run_native_tabs_action(
                boss=boss,
                action="enable",
                running_version=(0, 48, 2),
                options=current_options,
                read_options=lambda: current_options,
                left_edge=LEFT_EDGE,
                right_edge=RIGHT_EDGE,
                kitty_tabs=FakeTabs(boss, events),
                log_error=logs.append,
            )

        self.assertEqual(current_options.config_overrides, previous_overrides)
        self.assertFalse(getattr(boss, NATIVE_MARKER_ATTRIBUTE, False))
        self.assertTrue(any("rollback resize" in message for message in logs))

    def test_unmarked_user_vertical_toggle_does_not_arm_marker(self) -> None:
        events = []
        current_options = options(
            tab_bar_edge=RIGHT_EDGE,
            tab_bar_min_tabs=HIDDEN_MIN_TABS,
            config_overrides=("tab_bar_edge right",),
        )
        boss = FakeBoss(current_options, events)
        plan = run_native_tabs_action(
            boss=boss,
            action="toggle",
            running_version=(0, 48, 2),
            options=current_options,
            read_options=lambda: current_options,
            left_edge=LEFT_EDGE,
            right_edge=RIGHT_EDGE,
            kitty_tabs=FakeTabs(boss, events),
            log_error=lambda _message: None,
        )

        self.assertFalse(plan.native_managed)
        self.assertFalse(getattr(boss, NATIVE_MARKER_ATTRIBUTE))
        self.assertNotIn("order", events)

    def test_managed_toggle_clears_and_rearms_normalization_marker(self) -> None:
        events = []
        current_options = options()
        boss = FakeBoss(current_options, events)
        tabs = FakeTabs(boss, events)
        common = {
            "boss": boss,
            "running_version": (0, 48, 2),
            "options": current_options,
            "read_options": lambda: current_options,
            "left_edge": LEFT_EDGE,
            "right_edge": RIGHT_EDGE,
            "kitty_tabs": tabs,
            "log_error": lambda _message: None,
        }
        run_native_tabs_action(action="enable", **common)
        run_native_tabs_action(action="toggle", **common)

        self.assertTrue(getattr(boss, NATIVE_MANAGED_ATTRIBUTE))
        self.assertFalse(getattr(boss, NATIVE_MARKER_ATTRIBUTE))

        run_native_tabs_action(action="toggle", **common)

        self.assertTrue(getattr(boss, NATIVE_MARKER_ATTRIBUTE))

    def test_managed_bar_keeps_custom_card_style_across_toggle(
        self,
    ) -> None:
        events = []
        current_options = options(tab_bar_style="hidden")
        boss = FakeBoss(current_options, events)
        common = {
            "boss": boss,
            "running_version": (0, 48, 2),
            "options": current_options,
            "read_options": lambda: current_options,
            "left_edge": LEFT_EDGE,
            "right_edge": RIGHT_EDGE,
            "kitty_tabs": FakeTabs(boss, events),
            "log_error": lambda _message: None,
        }

        run_native_tabs_action(action="enable", **common)
        self.assertIn("tab_bar_style custom", current_options.config_overrides)
        run_native_tabs_action(action="toggle", **common)
        self.assertIn("tab_bar_style custom", current_options.config_overrides)
        self.assertEqual(current_options.tab_bar_style, "custom")
        run_native_tabs_action(action="toggle", **common)
        self.assertIn("tab_bar_style custom", current_options.config_overrides)


if __name__ == "__main__":
    unittest.main()
