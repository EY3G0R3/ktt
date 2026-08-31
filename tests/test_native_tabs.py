import unittest

from ktt.native_tabs import (
    NativeVerticalTabsUnsupported,
    merge_config_overrides,
    plan_native_tabs_action,
    version_tuple,
)


class NativeTabsTests(unittest.TestCase):
    def test_explicit_native_enable_preserves_preset_style_and_alignment(self) -> None:
        plan = plan_native_tabs_action(
            "enable",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="horizontal",
            current_style="custom",
        )

        self.assertEqual(plan.overrides, (
            "tab_bar_edge left",
            "tab_bar_min_tabs 1",
            "tab_title_max_length 40",
        ))
        self.assertTrue(plan.normalize_tree_order)

    def test_explicit_enable_preserves_existing_right_edge(self) -> None:
        plan = plan_native_tabs_action(
            "enable",
            running_version=(0, 48, 2),
            currently_hidden=False,
            current_edge="right",
            current_style="custom",
        )

        self.assertIn("tab_bar_edge right", plan.overrides)
        self.assertNotIn("tab_bar_edge left", plan.overrides)

    def test_hidden_native_toggle_restores_native_without_preset_overrides(
        self,
    ) -> None:
        shown = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="right",
            current_style="custom",
            native_managed=True,
        )
        disabled = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=False,
            current_edge="right",
            current_style="custom",
            native_managed=True,
        )

        self.assertEqual(shown.overrides, (
            "tab_bar_edge right",
            "tab_bar_min_tabs 1",
            "tab_title_max_length 40",
        ))
        self.assertEqual(disabled.overrides, (
            "tab_bar_edge right",
            "tab_bar_min_tabs 1000000",
        ))

    def test_native_toggle_round_trip_retains_native_identity(self) -> None:
        enabled = plan_native_tabs_action(
            "enable",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="horizontal",
            current_style="custom",
        )
        disabled = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=False,
            current_edge="left",
            current_style="custom",
            native_managed=True,
        )
        reenabled = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="left",
            current_style="custom",
            native_managed=True,
        )

        self.assertIn("tab_bar_edge left", enabled.overrides)
        self.assertIn("tab_bar_edge left", disabled.overrides)
        self.assertNotIn("tab_title_max_length 40", disabled.overrides)
        self.assertTrue(enabled.native_visible)
        self.assertFalse(disabled.native_visible)
        self.assertTrue(reenabled.native_visible)
        self.assertEqual(reenabled, enabled)

    def test_managed_hide_removes_temporary_fade_recovery(self) -> None:
        hidden_recovery = merge_config_overrides(
            ("font_size 14",),
            plan_native_tabs_action(
                "enable",
                running_version=(0, 48, 2),
                currently_hidden=True,
                current_edge="horizontal",
                current_style="hidden",
            ),
        )
        hidden = merge_config_overrides(
            hidden_recovery,
            plan_native_tabs_action(
                "toggle",
                running_version=(0, 48, 2),
                currently_hidden=False,
                current_edge="left",
                current_style="fade",
                native_managed=True,
                style_recovery_managed=True,
            ),
        )

        self.assertNotIn("tab_bar_style fade", hidden)

    def test_explicit_enable_recovers_persistent_hidden_style(self) -> None:
        plan = plan_native_tabs_action(
            "enable",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="horizontal",
            current_style="hidden",
        )

        self.assertEqual(plan.overrides, (
            "tab_bar_edge left",
            "tab_bar_min_tabs 1",
            "tab_title_max_length 40",
            "tab_bar_style fade",
        ))
        self.assertNotIn("tab_bar_align", "\n".join(plan.overrides))

    def test_persistent_hidden_style_toggle_becomes_visible(self) -> None:
        plan = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="horizontal",
            current_style="hidden",
        )

        self.assertEqual(plan.overrides, (
            "tab_bar_min_tabs 1",
            "tab_bar_style fade",
        ))

    def test_override_merge_preserves_unrelated_user_options(self) -> None:
        merged = merge_config_overrides(
            (
                "font_size=14",
                "tab_bar_style custom",
                "tab_bar_align center",
                "tab_bar_edge bottom",
            ),
            plan_native_tabs_action(
                "enable",
                running_version=(0, 48, 2),
                currently_hidden=False,
                current_edge="horizontal",
                current_style="custom",
            ),
        )

        self.assertEqual(merged, (
            "font_size=14",
            "tab_bar_style custom",
            "tab_bar_align center",
            "tab_bar_edge left",
            "tab_bar_min_tabs 1",
            "tab_title_max_length 40",
        ))

    def test_hidden_style_recovery_is_idempotent_across_enable(self) -> None:
        existing = (
            "font_size 14",
            "tab_bar_style hidden",
            "tab_bar_align center",
        )
        first_plan = plan_native_tabs_action(
            "enable",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="horizontal",
            current_style="hidden",
        )
        first = merge_config_overrides(existing, first_plan)
        second_plan = plan_native_tabs_action(
            "enable",
            running_version=(0, 48, 2),
            currently_hidden=False,
            current_edge="left",
            current_style="fade",
        )

        self.assertEqual(merge_config_overrides(first, second_plan), first)
        self.assertEqual(first.count("tab_bar_style fade"), 1)
        self.assertIn("tab_bar_align center", first)

    def test_merged_native_toggle_cycle_is_stable(self) -> None:
        existing = (
            "background_opacity 0.9",
            "tab_bar_style custom",
            "tab_bar_align center",
        )
        enabled = merge_config_overrides(
            existing,
            plan_native_tabs_action(
                "enable",
                running_version=(0, 48, 2),
                currently_hidden=False,
                current_edge="horizontal",
                current_style="custom",
            ),
        )
        hidden = merge_config_overrides(
            enabled,
            plan_native_tabs_action(
                "toggle",
                running_version=(0, 48, 2),
                currently_hidden=False,
                current_edge="left",
                current_style="custom",
                native_managed=True,
            ),
        )
        shown = merge_config_overrides(
            hidden,
            plan_native_tabs_action(
                "toggle",
                running_version=(0, 48, 2),
                currently_hidden=True,
                current_edge="left",
                current_style="custom",
                native_managed=True,
            ),
        )

        self.assertEqual(shown, enabled)
        self.assertIn("background_opacity 0.9", shown)
        self.assertIn("tab_bar_style custom", shown)
        self.assertIn("tab_bar_align center", shown)

    def test_unmarked_user_vertical_toggle_never_arms_native_ordering(self) -> None:
        plan = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=True,
            current_edge="right",
            current_style="custom",
            native_managed=False,
        )

        self.assertEqual(plan.overrides, ("tab_bar_min_tabs 1",))
        self.assertFalse(plan.native_visible)
        self.assertFalse(plan.native_managed)

    def test_toggle_on_horizontal_bar_keeps_legacy_behavior(self) -> None:
        plan = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=False,
            current_edge="horizontal",
            current_style="custom",
        )

        self.assertEqual(plan.overrides, ("tab_bar_min_tabs 1000000",))

    def test_legacy_toggle_does_not_claim_native_edge_or_width(self) -> None:
        plan = plan_native_tabs_action(
            "toggle",
            running_version=(0, 48, 2),
            currently_hidden=False,
            current_edge="horizontal",
            current_style="custom",
        )

        self.assertEqual(
            merge_config_overrides(
                (
                    "tab_bar_edge right",
                    "tab_title_max_length 77",
                    "font_size 14",
                ),
                plan,
            ),
            (
                "tab_bar_edge right",
                "tab_title_max_length 77",
                "font_size 14",
                "tab_bar_min_tabs 1000000",
            ),
        )

    def test_old_kitty_toggle_keeps_legacy_behavior(self) -> None:
        plan = plan_native_tabs_action(
            "toggle",
            running_version=(0, 45, 0),
            currently_hidden=True,
            current_edge="horizontal",
            current_style="custom",
        )

        self.assertEqual(plan.overrides, ("tab_bar_min_tabs 1",))

    def test_explicit_native_enable_rejects_old_running_kitty(self) -> None:
        with self.assertRaises(NativeVerticalTabsUnsupported):
            plan_native_tabs_action(
                "enable",
                running_version=(0, 47, 4),
                currently_hidden=False,
                current_edge="horizontal",
                current_style="custom",
            )

    def test_unsupported_error_round_trips_through_remote_control_text(self) -> None:
        original = NativeVerticalTabsUnsupported((0, 47, 4))

        parsed = NativeVerticalTabsUnsupported.from_message(
            f"RuntimeError: {original}"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.version, (0, 47, 4))

    def test_version_tuple_has_exact_three_part_shape(self) -> None:
        self.assertEqual(version_tuple((0, 48, 2)), (0, 48, 2))


if __name__ == "__main__":
    unittest.main()
