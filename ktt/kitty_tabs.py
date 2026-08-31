"""Kitty-process helpers for preserving ktt's tree tab order."""

from __future__ import annotations

from collections.abc import Sequence
import inspect
from typing import Any

from . import model
from .tab_bar_geometry import select_content_windows


ORDER_TRANSACTION_ATTRIBUTE = "_ktt_tab_order_transaction"


def _user_var(window: Any, key: str) -> str:
    return str(getattr(window, "user_vars", {}).get(key) or "")


def _content_windows(tab: Any) -> list[Any]:
    return list(select_content_windows(
        tuple(tab),
        user_var=_user_var,
        sidebar_var=model.SIDEBAR_VAR,
        role_var=model.COCKPIT_ROLE_VAR,
        agent_role=model.AGENT_ROLE,
        is_active=lambda window: window is getattr(tab, "active_window", None),
    ))


def _parent_window_id(windows: Sequence[Any]) -> int | None:
    value = ""
    for window in windows:
        value = _user_var(window, model.PARENT_VAR)
        if value:
            break
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _first_user_var(windows: Sequence[Any], key: str) -> str | None:
    return next(
        (value for window in windows if (value := _user_var(window, key))),
        None,
    )


def live_tree_records(tab_manager: Any) -> tuple[model.TabRecord, ...]:
    """Build tree records from Kitty's live tabs without a process snapshot."""
    records = []
    for source_index, tab in enumerate(tab_manager):
        windows = _content_windows(tab)
        if not windows:
            continue
        title = str(getattr(tab, "title", "")) or "untitled"
        status = _first_user_var(windows, model.STATUS_VAR)
        records.append(model.TabRecord(
            id=tab.id,
            os_window_id=tab_manager.os_window_id,
            title=title,
            window_ids=tuple(window.id for window in windows),
            is_active=tab is tab_manager.active_tab,
            parent_window_id=_parent_window_id(windows),
            status=status,
            source_index=source_index,
            attention_suppressed=(
                status in model.WAITING_STATUSES
                and model.title_is_working(title)
            ),
        ))
    return tuple(records)


def live_tree_tab_ids(tab_manager: Any) -> tuple[int, ...]:
    """Return model-validated tree preorder for a live Kitty tab manager."""
    return tuple(
        row.tab.id for row in model.tree_rows(live_tree_records(tab_manager))
    )


def tree_topology_signature(tab_manager: Any) -> tuple[Any, ...]:
    """Track order inputs while excluding title and status repaint churn."""
    return tuple(
        (
            tab.id,
            tuple(
                (
                    window.id,
                    window is getattr(tab, "active_window", None),
                    _user_var(window, model.SIDEBAR_VAR),
                    _user_var(window, model.COCKPIT_ROLE_VAR),
                    _user_var(window, model.PARENT_VAR),
                )
                for window in tab
            ),
        )
        for tab in tab_manager
    )


def _swap_tabs(os_window_id: int, left: int, right: int) -> None:
    from kitty.fast_data_types import swap_tabs

    swap_tabs(os_window_id, left, right)


def _active_tab_restorer(tab_manager: Any, active_tab: Any):
    if active_tab is None:
        return lambda: None
    public = getattr(tab_manager, "set_active_tab", None)
    if callable(public):
        inspect.signature(public).bind(active_tab)
        return lambda: public(active_tab)
    private = getattr(tab_manager, "_set_active_tab", None)
    if not callable(private):
        raise TypeError("Kitty TabManager has no supported active-tab setter")
    active_index = tab_manager.tabs.index(active_tab)
    inspect.signature(private).bind(active_index, store_in_history=False)
    return lambda: private(
        tab_manager.tabs.index(active_tab), store_in_history=False
    )


def _restore_history(history: Any, saved: tuple[Any, ...]) -> None:
    history.clear()
    history.extend(saved)


def apply_tab_order(tab_manager: Any, desired_tab_ids: Sequence[int]) -> bool:
    """Transactionally order known tabs without disturbing focus or history."""
    tabs = tab_manager.tabs
    active_tab = tab_manager.active_tab
    by_id = {tab.id: tab for tab in tabs}

    desired = []
    seen: set[int] = set()
    for tab_id in desired_tab_ids:
        if tab_id in by_id and tab_id not in seen:
            desired.append(by_id[tab_id])
            seen.add(tab_id)
    known_slots = [
        index for index, tab in enumerate(tabs) if tab.id in seen
    ]
    final_order = list(tabs)
    for index, tab in zip(known_slots, desired):
        final_order[index] = tab
    if final_order == tabs:
        return False

    history = tab_manager.active_tab_history
    saved_history = tuple(history)
    restore_active = _active_tab_restorer(tab_manager, active_tab)
    inspect.signature(_swap_tabs).bind(tab_manager.os_window_id, 0, 1)
    inspect.signature(tab_manager.mark_tab_bar_dirty).bind()
    if not callable(getattr(history, "clear", None)) or not callable(
        getattr(history, "extend", None)
    ):
        raise TypeError("Kitty active-tab history is not restorable")

    simulated = list(tabs)
    swaps: list[tuple[int, int]] = []
    for target_index, target in enumerate(final_order):
        current_index = simulated.index(target)
        while current_index > target_index:
            previous_index = current_index - 1
            simulated[previous_index], simulated[current_index] = (
                simulated[current_index],
                simulated[previous_index],
            )
            swaps.append((previous_index, current_index))
            current_index = previous_index

    original_tabs = list(tabs)
    completed: list[tuple[int, int]] = []
    previous_transaction = getattr(
        tab_manager, ORDER_TRANSACTION_ATTRIBUTE, None
    )
    setattr(tab_manager, ORDER_TRANSACTION_ATTRIBUTE, True)
    try:
        for left, right in swaps:
            _swap_tabs(tab_manager.os_window_id, left, right)
            completed.append((left, right))
            tabs[left], tabs[right] = tabs[right], tabs[left]
        restore_active()
        _restore_history(history, saved_history)
        tab_manager.mark_tab_bar_dirty()
    except Exception as error:
        rollback_errors = []
        for left, right in reversed(completed):
            try:
                _swap_tabs(tab_manager.os_window_id, left, right)
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)
        tabs[:] = original_tabs
        try:
            restore_active()
        except Exception as rollback_error:
            rollback_errors.append(rollback_error)
        try:
            _restore_history(history, saved_history)
        except Exception as rollback_error:
            rollback_errors.append(rollback_error)
        try:
            tab_manager.mark_tab_bar_dirty()
        except Exception as rollback_error:
            rollback_errors.append(rollback_error)
        if rollback_errors:
            setattr(
                tab_manager,
                ORDER_TRANSACTION_ATTRIBUTE,
                previous_transaction,
            )
            raise RuntimeError(
                "tab-order update failed and rollback was incomplete: "
                + "; ".join(map(str, rollback_errors))
            ) from error
        setattr(
            tab_manager, ORDER_TRANSACTION_ATTRIBUTE, previous_transaction
        )
        raise
    setattr(tab_manager, ORDER_TRANSACTION_ATTRIBUTE, previous_transaction)
    return True
