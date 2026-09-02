"""Testable orchestration for Kitty's process-local native tab configuration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
import sys
from typing import Any, Literal

from .native_tabs import (
    HIDDEN_MIN_TABS,
    NATIVE_CARD_STATE_ATTRIBUTE,
    NATIVE_MANAGED_ATTRIBUTE,
    NATIVE_MARKER_ATTRIBUTE,
    NATIVE_STYLE_RECOVERY_ATTRIBUTE,
    NATIVE_VERTICAL_TABS_VERSION,
    NativeTabsActionPlan,
    TabBarEdge,
    merge_config_overrides,
    plan_native_tabs_action,
)


Action = Literal["enable", "toggle"]


class NativeTabsRuntimeError(RuntimeError):
    pass


@contextmanager
def temporary_sys_path(path: str):
    """Expose ktt to renderer reloads without permanently changing Kitty."""
    added = path not in sys.path
    if added:
        sys.path.insert(0, path)
    try:
        yield
    finally:
        if added:
            try:
                sys.path.remove(path)
            except ValueError:
                pass


def parse_action_args(arguments: Sequence[str]) -> Action:
    """Return the native-tab action from arguments after the kitten path."""
    if not arguments:
        return "toggle"
    if tuple(arguments) != ("vertical",):
        raise ValueError(f"unknown native-tabs action: {arguments[0]}")
    return "enable"


def options_hidden(options: Any) -> bool:
    return (
        options.tab_bar_style == "hidden"
        or options.tab_bar_min_tabs >= HIDDEN_MIN_TABS
    )


def _close_native_card_state(
    boss: Any, log_error: Callable[[str], None]
) -> None:
    state = getattr(boss, NATIVE_CARD_STATE_ATTRIBUTE, None)
    if state is None:
        return
    try:
        state.close()
    except Exception as error:
        log_error(f"ktt native tabs: renderer cleanup failed: {error}")
    finally:
        if getattr(boss, NATIVE_CARD_STATE_ATTRIBUTE, None) is state:
            delattr(boss, NATIVE_CARD_STATE_ATTRIBUTE)


def current_edge_name(
    options: Any,
    running_version: tuple[int, int, int],
    left_edge: object,
    right_edge: object,
) -> TabBarEdge:
    if running_version < NATIVE_VERTICAL_TABS_VERSION:
        return "horizontal"
    if options.tab_bar_edge == left_edge:
        return "left"
    if options.tab_bar_edge == right_edge:
        return "right"
    return "horizontal"


def _verify_postcondition(
    options: Any,
    plan: NativeTabsActionPlan,
    running_version: tuple[int, int, int],
    left_edge: object,
    right_edge: object,
) -> None:
    hidden = options_hidden(options)
    edge = current_edge_name(options, running_version, left_edge, right_edge)
    if hidden != plan.expected_hidden:
        state = "hidden" if hidden else "visible"
        raise NativeTabsRuntimeError(
            f"Kitty tab bar remained {state} after config reload"
        )
    if plan.native_managed and edge != plan.expected_edge:
        raise NativeTabsRuntimeError(
            f"Kitty tab bar edge is {edge}, expected {plan.expected_edge}"
        )
    if (
        plan.expected_style is not None
        and options.tab_bar_style != plan.expected_style
    ):
        raise NativeTabsRuntimeError(
            "Kitty tab bar style is "
            f"{options.tab_bar_style}, expected {plan.expected_style}"
        )
    if (
        plan.expected_alignment is not None
        and options.tab_bar_align != plan.expected_alignment
    ):
        raise NativeTabsRuntimeError(
            "Kitty tab bar alignment is "
            f"{options.tab_bar_align}, expected {plan.expected_alignment}"
        )
    if (
        plan.expected_drag_threshold is not None
        and options.drag_threshold != plan.expected_drag_threshold
    ):
        raise NativeTabsRuntimeError(
            "Kitty drag threshold is "
            f"{options.drag_threshold}, expected {plan.expected_drag_threshold}"
        )


def _attribute_snapshot(value: Any, name: str) -> tuple[bool, Any]:
    return hasattr(value, name), getattr(value, name, None)


def _restore_attribute(value: Any, name: str, snapshot: tuple[bool, Any]) -> None:
    present, previous = snapshot
    if present:
        setattr(value, name, previous)
    elif hasattr(value, name):
        delattr(value, name)


def run_native_tabs_action(
    *,
    boss: Any,
    action: Action,
    running_version: tuple[int, int, int],
    options: Any,
    read_options: Callable[[], Any],
    left_edge: object,
    right_edge: object,
    kitty_tabs: Any,
    log_error: Callable[[str], None],
) -> NativeTabsActionPlan:
    """Apply one action, logging maintenance failures and verifying visibility."""
    current_edge = current_edge_name(
        options, running_version, left_edge, right_edge
    )
    plan = plan_native_tabs_action(
        action,
        running_version=running_version,
        currently_hidden=options_hidden(options),
        current_edge=current_edge,
        current_style=options.tab_bar_style,
        native_managed=bool(
            getattr(boss, NATIVE_MANAGED_ATTRIBUTE, False)
        ),
        style_recovery_managed=bool(
            getattr(boss, NATIVE_STYLE_RECOVERY_ATTRIBUTE, False)
        ),
    )
    previous_overrides = tuple(
        getattr(options, "config_overrides", ()) or ()
    )
    previous_hidden = options_hidden(options)
    previous_edge = current_edge
    previous_style = options.tab_bar_style
    previous_alignment = options.tab_bar_align
    previous_min_tabs = options.tab_bar_min_tabs
    previous_drag_threshold = options.drag_threshold
    previous_marker = _attribute_snapshot(boss, NATIVE_MARKER_ATTRIBUTE)
    previous_managed = _attribute_snapshot(boss, NATIVE_MANAGED_ATTRIBUTE)
    previous_style_recovery = _attribute_snapshot(
        boss, NATIVE_STYLE_RECOVERY_ATTRIBUTE
    )
    pending_orders = (
        tuple(
            (tab_manager, kitty_tabs.live_tree_tab_ids(tab_manager))
            for tab_manager in boss.all_tab_managers
        )
        if plan.normalize_tree_order
        else ()
    )
    previous_orders = tuple(
        (tab_manager, tuple(tab.id for tab in tab_manager))
        for tab_manager in boss.all_tab_managers
    )

    def rollback(original_error: Exception) -> None:
        rollback_errors: list[Exception] = []

        def attempt(stage: str, operation: Callable[[], None]) -> None:
            try:
                operation()
            except Exception as error:
                log_error(f"ktt native tabs: rollback {stage} failed: {error}")
                rollback_errors.append(error)

        attempt(
            "managed marker",
            lambda: _restore_attribute(
                boss, NATIVE_MANAGED_ATTRIBUTE, previous_managed
            ),
        )
        attempt(
            "visibility marker",
            lambda: _restore_attribute(
                boss, NATIVE_MARKER_ATTRIBUTE, previous_marker
            ),
        )
        attempt(
            "style recovery marker",
            lambda: _restore_attribute(
                boss,
                NATIVE_STYLE_RECOVERY_ATTRIBUTE,
                previous_style_recovery,
            ),
        )
        attempt(
            "config",
            lambda: boss.load_config_file(
                apply_overrides=False, overrides=previous_overrides
            ),
        )
        for tab_manager, tab_ids in previous_orders:
            attempt(
                f"order for OS window {tab_manager.os_window_id}",
                lambda manager=tab_manager, ids=tab_ids: (
                    kitty_tabs.apply_tab_order(manager, ids)
                ),
            )
        for tab_manager in boss.all_tab_managers:
            attempt(
                f"resize for OS window {tab_manager.os_window_id}",
                tab_manager.resize,
            )

        try:
            restored = read_options()
            if tuple(getattr(restored, "config_overrides", ()) or ()) != (
                previous_overrides
            ):
                raise NativeTabsRuntimeError(
                    "Kitty did not restore the previous config overrides"
                )
            if (
                options_hidden(restored) != previous_hidden
                or current_edge_name(
                    restored, running_version, left_edge, right_edge
                ) != previous_edge
                or restored.tab_bar_style != previous_style
                or restored.tab_bar_align != previous_alignment
                or restored.tab_bar_min_tabs != previous_min_tabs
                or restored.drag_threshold != previous_drag_threshold
                or _attribute_snapshot(boss, NATIVE_MARKER_ATTRIBUTE)
                != previous_marker
                or _attribute_snapshot(boss, NATIVE_MANAGED_ATTRIBUTE)
                != previous_managed
                or _attribute_snapshot(boss, NATIVE_STYLE_RECOVERY_ATTRIBUTE)
                != previous_style_recovery
            ):
                raise NativeTabsRuntimeError(
                    "Kitty did not restore the previous native-tab state"
                )
            for tab_manager, tab_ids in previous_orders:
                if tuple(tab.id for tab in tab_manager) != tab_ids:
                    raise NativeTabsRuntimeError(
                        "Kitty did not restore the previous tab order for "
                        f"OS window {tab_manager.os_window_id}"
                    )
        except Exception as error:
            log_error(f"ktt native tabs: rollback verification failed: {error}")
            rollback_errors.append(error)
        if rollback_errors:
            raise NativeTabsRuntimeError(
                "native tab action failed and rollback was incomplete: "
                + "; ".join(map(str, rollback_errors))
            ) from original_error
        raise original_error

    _close_native_card_state(boss, log_error)
    try:
        boss.load_config_file(
            apply_overrides=False,
            overrides=merge_config_overrides(previous_overrides, plan),
        )
    except Exception as error:
        log_error(f"ktt native tabs: config load failed: {error}")
        rollback(error)
    setattr(boss, NATIVE_MANAGED_ATTRIBUTE, plan.native_managed)
    setattr(boss, NATIVE_MARKER_ATTRIBUTE, plan.native_visible)
    setattr(boss, NATIVE_STYLE_RECOVERY_ATTRIBUTE, plan.style_recovery)

    failures: list[Exception] = []

    def maintain(stage: str, operation: Callable[[], None]) -> None:
        try:
            operation()
        except Exception as error:
            log_error(f"ktt native tabs: {stage} failed: {error}")
            failures.append(error)

    for tab_manager, desired_tab_ids in pending_orders:
        maintain(
            f"tree ordering for OS window {tab_manager.os_window_id}",
            lambda manager=tab_manager, ids=desired_tab_ids: (
                kitty_tabs.apply_tab_order(manager, ids)
            ),
        )
    for tab_manager in boss.all_tab_managers:
        maintain(
            f"resize for OS window {tab_manager.os_window_id}",
            tab_manager.resize,
        )
    try:
        _verify_postcondition(
            read_options(), plan, running_version, left_edge, right_edge
        )
    except Exception as error:
        log_error(f"ktt native tabs: postcondition failed: {error}")
        rollback(error)
    if failures:
        rollback(NativeTabsRuntimeError(
            f"native tab maintenance failed: {failures[0]}"
        ))
    return plan
