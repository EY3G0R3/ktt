"""Shared compatibility contract for Kitty's native vertical tab bar."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


Version = tuple[int, int, int]
NATIVE_VERTICAL_TABS_VERSION: Version = (0, 48, 0)
UNSUPPORTED_MARKER = "KTT_NATIVE_VERTICAL_TABS_UNSUPPORTED="
TabBarEdge = Literal["horizontal", "left", "right"]
VISIBLE_FALLBACK_STYLE = "fade"
HIDDEN_MIN_TABS = 1_000_000
NATIVE_MARKER_ATTRIBUTE = "_ktt_native_vertical_tabs_enabled"
NATIVE_MANAGED_ATTRIBUTE = "_ktt_native_vertical_tabs_managed"
NATIVE_STYLE_RECOVERY_ATTRIBUTE = "_ktt_native_tabs_style_recovery"
KTT_OVERRIDE_KEYS = frozenset({
    "tab_bar_edge",
    "tab_bar_min_tabs",
    "tab_title_max_length",
})


def version_tuple(value: Sequence[int]) -> Version:
    """Normalize Kitty's version value without widening it to an arbitrary tuple."""
    major, minor, patch = value[:3]
    return int(major), int(minor), int(patch)


def format_version(version: Version) -> str:
    return ".".join(map(str, version))


class NativeVerticalTabsUnsupported(RuntimeError):
    """The running Kitty process predates native vertical tab bars."""

    def __init__(self, version: Version) -> None:
        self.version = version
        super().__init__(f"{UNSUPPORTED_MARKER}{format_version(version)}")

    @classmethod
    def from_message(
        cls, message: str
    ) -> NativeVerticalTabsUnsupported | None:
        match = re.search(
            rf"{re.escape(UNSUPPORTED_MARKER)}(\d+)\.(\d+)\.(\d+)",
            message,
        )
        if match is None:
            return None
        major, minor, patch = (int(part) for part in match.groups())
        return cls((major, minor, patch))


@dataclass(frozen=True)
class NativeTabsActionPlan:
    overrides: tuple[str, ...]
    owned_keys: frozenset[str] = frozenset()
    normalize_tree_order: bool = False
    native_visible: bool = False
    native_managed: bool = False
    expected_hidden: bool = False
    expected_edge: TabBarEdge = "horizontal"
    style_recovery: bool = False


def _override_key(override: str) -> str:
    parts = str(override).strip().split(None, 1)
    if not parts:
        return ""
    head = parts[0]
    return head.split("=", 1)[0]


def merge_config_overrides(
    existing: Sequence[str], plan: NativeTabsActionPlan
) -> tuple[str, ...]:
    """Replace only ktt-owned settings while retaining every unrelated `-o`."""
    planned = plan.overrides
    planned_by_key = {_override_key(value): value for value in planned}
    replaced_keys = plan.owned_keys | planned_by_key.keys()
    merged: list[str] = []
    emitted: set[str] = set()
    for override in existing:
        key = _override_key(override)
        if key not in replaced_keys:
            merged.append(str(override))
        elif key in planned_by_key and key not in emitted:
            merged.append(planned_by_key[key])
            emitted.add(key)
    for override in planned:
        key = _override_key(override)
        if key not in emitted:
            merged.append(str(override))
            emitted.add(key)
    return tuple(merged)


def plan_native_tabs_action(
    action: Literal["enable", "toggle"],
    *,
    running_version: Version,
    currently_hidden: bool,
    current_edge: TabBarEdge,
    current_style: str,
    native_managed: bool = False,
    style_recovery_managed: bool = False,
) -> NativeTabsActionPlan:
    """Plan one config reload without masking the selected tab-bar preset."""
    supported = running_version >= NATIVE_VERTICAL_TABS_VERSION
    if action == "enable":
        if not supported:
            raise NativeVerticalTabsUnsupported(running_version)
        native_edge = "right" if current_edge == "right" else "left"
        overrides = [
            f"tab_bar_edge {native_edge}",
            "tab_bar_min_tabs 1",
            "tab_title_max_length 40",
        ]
        if current_style == "hidden":
            overrides.append(f"tab_bar_style {VISIBLE_FALLBACK_STYLE}")
        return NativeTabsActionPlan(
            tuple(overrides),
            owned_keys=KTT_OVERRIDE_KEYS,
            normalize_tree_order=True,
            native_visible=True,
            native_managed=True,
            expected_edge=native_edge,
            style_recovery=current_style == "hidden",
        )
    if action != "toggle":
        raise ValueError(f"unknown native tab action: {action}")

    result_hidden = not currently_hidden
    tab_bar_min_tabs = HIDDEN_MIN_TABS if result_hidden else 1
    if (
        supported
        and native_managed
        and current_edge in ("left", "right")
    ):
        overrides = [
            f"tab_bar_edge {current_edge}",
            f"tab_bar_min_tabs {tab_bar_min_tabs}",
        ]
        if currently_hidden:
            overrides.append("tab_title_max_length 40")
        if currently_hidden and current_style == "hidden":
            overrides.append(f"tab_bar_style {VISIBLE_FALLBACK_STYLE}")
        return NativeTabsActionPlan(
            tuple(overrides),
            # A fade override is injected only to recover a persistently hidden
            # bar. Strip that temporary recovery style when hiding again.
            owned_keys=(
                KTT_OVERRIDE_KEYS
                | (
                    {"tab_bar_style"}
                    if result_hidden and style_recovery_managed
                    else set()
                )
            ),
            normalize_tree_order=currently_hidden,
            native_visible=currently_hidden,
            native_managed=True,
            expected_hidden=result_hidden,
            expected_edge=current_edge,
            style_recovery=(
                currently_hidden and current_style == "hidden"
            ),
        )
    overrides = [f"tab_bar_min_tabs {tab_bar_min_tabs}"]
    if currently_hidden and current_style == "hidden":
        overrides.append(f"tab_bar_style {VISIBLE_FALLBACK_STYLE}")
    return NativeTabsActionPlan(
        tuple(overrides),
        owned_keys=frozenset({"tab_bar_min_tabs"}),
        expected_hidden=result_hidden,
        expected_edge=current_edge,
    )
