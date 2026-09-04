"""Enable KTT at startup and keep Kitty's native tabs in tree order."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Any, Callable


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
NORMALIZING_ATTRIBUTE = "_ktt_normalizing_native_tab_order"
ORDER_SIGNATURE_ATTRIBUTE = "_ktt_native_tree_order_signatures"
ORDER_FAILURE_ATTRIBUTE = "_ktt_native_tree_order_failures"
NATIVE_MARKER_ATTRIBUTE = "_ktt_native_vertical_tabs_enabled"
NATIVE_MANAGED_ATTRIBUTE = "_ktt_native_vertical_tabs_managed"
NATIVE_STYLE_RECOVERY_ATTRIBUTE = "_ktt_native_tabs_style_recovery"
NATIVE_CARD_STATE_ATTRIBUTE = "_ktt_native_card_state"
ORDER_TRANSACTION_ATTRIBUTE = "_ktt_tab_order_transaction"
KTT_OVERRIDE_KEYS = frozenset({
    "tab_bar_edge",
    "tab_bar_align",
    "tab_bar_min_tabs",
    "tab_bar_style",
    "tab_title_max_length",
    "drag_threshold",
})
MIN_VERTICAL_VERSION = (0, 48, 0)
VERTICAL_FALLBACK_OVERRIDES = (
    "tab_bar_edge left",
    "tab_bar_align center",
    "tab_bar_min_tabs 2",
    "tab_bar_style fade",
    "tab_title_max_length 60",
)


def _override_key(override: str) -> str:
    parts = str(override).strip().split(None, 1)
    if not parts:
        return ""
    return parts[0].split("=", 1)[0]


def _merge_overrides(
    existing: tuple[str, ...], desired: tuple[str, ...]
) -> tuple[str, ...]:
    retained = (
        str(override)
        for override in existing
        if _override_key(override) not in KTT_OVERRIDE_KEYS
    )
    return (*retained, *desired)


def _resize_all(boss: Any) -> None:
    for tab_manager in boss.all_tab_managers:
        tab_manager.resize()


def _apply_regular_vertical(
    boss: Any, get_options: Callable[[], Any]
) -> None:
    state = getattr(boss, NATIVE_CARD_STATE_ATTRIBUTE, None)
    if state is not None:
        try:
            state.close()
        except Exception:
            pass
        try:
            delattr(boss, NATIVE_CARD_STATE_ATTRIBUTE)
        except AttributeError:
            pass
    setattr(boss, NATIVE_MARKER_ATTRIBUTE, False)
    setattr(boss, NATIVE_MANAGED_ATTRIBUTE, False)
    setattr(boss, NATIVE_STYLE_RECOVERY_ATTRIBUTE, False)
    options = get_options()
    existing = tuple(getattr(options, "config_overrides", ()) or ())
    boss.load_config_file(
        apply_overrides=False,
        overrides=_merge_overrides(existing, VERTICAL_FALLBACK_OVERRIDES),
    )
    _resize_all(boss)


def _load_native_modules() -> tuple[Any, Any]:
    package_root = str(PACKAGE_ROOT)
    added = package_root not in sys.path
    if added:
        sys.path.insert(0, package_root)
    try:
        kitty_tabs = importlib.import_module("ktt.kitty_tabs")
        native_tabs_runtime = importlib.import_module("ktt.native_tabs_runtime")
        renderer = importlib.import_module("ktt.tab_bar_renderer")
        if not hasattr(renderer, "install_vertical_tab_layout"):
            raise ImportError("KTT native renderer helpers are unavailable")
        return kitty_tabs, native_tabs_runtime
    finally:
        if added:
            try:
                sys.path.remove(package_root)
            except ValueError:
                pass


def _apply_ktt(
    boss: Any,
    version: tuple[int, int, int],
    get_options: Callable[[], Any],
    left_edge: object,
    right_edge: object,
    log_error: Callable[[str], None],
) -> None:
    kitty_tabs, native_tabs_runtime = _load_native_modules()
    with native_tabs_runtime.temporary_sys_path(str(PACKAGE_ROOT)):
        native_tabs_runtime.run_native_tabs_action(
            boss=boss,
            action="enable",
            running_version=version,
            options=get_options(),
            read_options=get_options,
            left_edge=left_edge,
            right_edge=right_edge,
            kitty_tabs=kitty_tabs,
            log_error=log_error,
        )

    # Explicit `ktt` shows the bar for one tab. Startup mode waits for tab 2.
    options = get_options()
    current = tuple(getattr(options, "config_overrides", ()) or ())
    desired = (
        *(value for value in current if _override_key(value) != "tab_bar_min_tabs"),
        "tab_bar_min_tabs 2",
    )
    boss.load_config_file(apply_overrides=False, overrides=desired)
    _resize_all(boss)


def _configure_startup(
    boss: Any,
    version: tuple[int, int, int],
    get_options: Callable[[], Any],
    left_edge: object,
    right_edge: object,
    log_error: Callable[[str], None],
) -> None:
    if version < MIN_VERTICAL_VERSION:
        return
    try:
        _apply_ktt(
            boss, version, get_options, left_edge, right_edge, log_error
        )
    except Exception as error:
        log_error(
            "KTT startup failed; using Kitty's native vertical tabs: "
            f"{error}"
        )
        try:
            _apply_regular_vertical(boss, get_options)
        except Exception as fallback_error:
            log_error(
                "Kitty vertical-tab fallback failed; keeping configured tabs: "
                f"{fallback_error}"
            )


def _configure_from_kitty(boss: Any) -> None:
    from kitty.constants import version as kitty_version

    version = tuple(int(part) for part in kitty_version[:3])
    if version < MIN_VERTICAL_VERSION:
        return
    from kitty.fast_data_types import LEFT_EDGE, RIGHT_EDGE, get_options
    from kitty.utils import log_error

    _configure_startup(
        boss, version, get_options, LEFT_EDGE, RIGHT_EDGE, log_error
    )


def on_load(boss: Any, _data: dict[str, Any]) -> None:
    from kitty.fast_data_types import add_timer

    # Watchers load before Kitty finishes constructing its first window.
    add_timer(lambda _timer_id: _configure_from_kitty(boss), 0, False)


def _is_vertical_tab_bar() -> bool:
    try:
        from kitty.fast_data_types import LEFT_EDGE, RIGHT_EDGE, get_options
    except ImportError:
        return False
    return get_options().tab_bar_edge in (LEFT_EDGE, RIGHT_EDGE)


def _load_kitty_tabs():
    package_root = str(PACKAGE_ROOT)
    added = package_root not in sys.path
    if added:
        sys.path.insert(0, package_root)
    try:
        return importlib.import_module("ktt.kitty_tabs")
    finally:
        if added:
            try:
                sys.path.remove(package_root)
            except ValueError:
                pass


def _log_error(message: str) -> None:
    try:
        from kitty.utils import log_error
    except ImportError:
        print(message, file=sys.stderr)
        return
    try:
        log_error(message)
    except Exception as error:
        print(f"{message} (Kitty logging failed: {error})", file=sys.stderr)


def _normalize_native_tab_order(boss, tab_manager) -> None:
    if not _is_vertical_tab_bar():
        return
    if not getattr(boss, NATIVE_MARKER_ATTRIBUTE, False):
        return
    if getattr(tab_manager, ORDER_TRANSACTION_ATTRIBUTE, False):
        return
    os_window_id = tab_manager.os_window_id
    normalizing = getattr(boss, NORMALIZING_ATTRIBUTE, None)
    if normalizing is None:
        normalizing = set()
        setattr(boss, NORMALIZING_ATTRIBUTE, normalizing)
    if os_window_id in normalizing:
        return
    kitty_tabs = _load_kitty_tabs()
    signatures = getattr(boss, ORDER_SIGNATURE_ATTRIBUTE, None)
    if signatures is None:
        signatures = {}
        setattr(boss, ORDER_SIGNATURE_ATTRIBUTE, signatures)
    signature = kitty_tabs.tree_topology_signature(tab_manager)
    if signatures.get(os_window_id) == signature:
        return
    failures = getattr(boss, ORDER_FAILURE_ATTRIBUTE, None)
    if failures is None:
        failures = {}
        setattr(boss, ORDER_FAILURE_ATTRIBUTE, failures)
    if failures.get(os_window_id) == signature:
        return
    normalizing.add(os_window_id)
    try:
        try:
            kitty_tabs.apply_tab_order(
                tab_manager, kitty_tabs.live_tree_tab_ids(tab_manager)
            )
        except Exception:
            failures[os_window_id] = signature
            raise
    finally:
        normalizing.discard(os_window_id)
    failures.pop(os_window_id, None)
    signatures[os_window_id] = kitty_tabs.tree_topology_signature(tab_manager)


def on_tab_bar_dirty(boss, _window, data: dict) -> None:
    tab_manager = data.get("tab_manager")
    if tab_manager is None:
        return
    try:
        _normalize_native_tab_order(boss, tab_manager)
    except Exception as error:
        _log_error(f"ktt watcher: native tab ordering failed: {error}")
