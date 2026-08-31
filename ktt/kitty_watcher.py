"""Push active-tab and tab-list changes to a running ktt sidebar.

Load this as a global Kitty watcher. The callback deliberately ignores title,
status, and tab-bar animation churn when neither tab selection nor membership
changed.
"""

from __future__ import annotations

import errno
import importlib
import os
from pathlib import Path
import socket
import sys


# Kitty loads watcher files with runpy without adding their checkout to
# sys.path. Add it only around the optional ordering import so notifications do
# not depend on package loading or permanently alter Kitty's import search path.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

STATE_ATTRIBUTE = "_ktt_external_tree_state"
NORMALIZING_ATTRIBUTE = "_ktt_normalizing_native_tab_order"
ORDER_SIGNATURE_ATTRIBUTE = "_ktt_native_tree_order_signatures"
ORDER_FAILURE_ATTRIBUTE = "_ktt_native_tree_order_failures"
NATIVE_MARKER_ATTRIBUTE = "_ktt_native_vertical_tabs_enabled"
ORDER_TRANSACTION_ATTRIBUTE = "_ktt_tab_order_transaction"
TAB_STATE_EVENT_PREFIX = b"tabs:"


def event_socket_path(os_window_id: int) -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(runtime) / "ktt" / f"kitty-{os.getpid()}-os-{os_window_id}.sock"


def _remove_refused_socket(path: Path, error: OSError, inode: int | None) -> None:
    if error.errno != errno.ECONNREFUSED or inode is None:
        return
    try:
        if path.stat().st_ino == inode:
            path.unlink()
    except FileNotFoundError:
        pass


def _tab_state_event(
    active_tab_id: int | None, tab_ids: tuple[int, ...]
) -> bytes:
    active = b"" if active_tab_id is None else str(active_tab_id).encode()
    members = b",".join(str(tab_id).encode() for tab_id in tab_ids)
    return TAB_STATE_EVENT_PREFIX + active + b"|" + members


def _notify(
    os_window_id: int,
    active_tab_id: int | None,
    tab_ids: tuple[int, ...],
) -> None:
    base_path = event_socket_path(os_window_id)
    paths = [
        base_path,
        *sorted(base_path.parent.glob(f"{base_path.name}.*")),
    ]
    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sender.setblocking(False)
    event = _tab_state_event(active_tab_id, tab_ids)
    try:
        for path in paths:
            try:
                inode = path.stat().st_ino
            except OSError:
                inode = None
            try:
                sender.sendto(event, str(path))
            except OSError as error:
                _remove_refused_socket(path, error, inode)
                continue
    finally:
        sender.close()


def _is_vertical_tab_bar() -> bool:
    try:
        from kitty.fast_data_types import LEFT_EDGE, RIGHT_EDGE, get_options
    except ImportError:
        return False
    return get_options().tab_bar_edge in (LEFT_EDGE, RIGHT_EDGE)


def _load_kitty_tabs():
    """Import optional ordering code only after notification setup succeeds."""
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


def _normalize_native_tab_order(boss, window, tab_manager) -> None:
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
        _normalize_native_tab_order(boss, _window, tab_manager)
    except Exception as error:
        # Watchers run synchronously in Kitty's redraw path. Tree ordering is
        # best-effort and must never suppress the normal state notification.
        _log_error(f"ktt watcher: native tab ordering failed: {error}")
    active_tab = tab_manager.active_tab
    state = (
        active_tab.id if active_tab is not None else None,
        tuple(tab.id for tab in tab_manager),
    )
    states = getattr(boss, STATE_ATTRIBUTE, None)
    if states is None:
        states = {}
        setattr(boss, STATE_ATTRIBUTE, states)
    os_window_id = tab_manager.os_window_id
    if states.get(os_window_id) == state:
        return
    states[os_window_id] = state
    _notify(os_window_id, state[0], state[1])
