"""Push active-tab and tab-list changes to a running ktt sidebar.

Load this as a global Kitty watcher. The callback deliberately ignores title,
status, and tab-bar animation churn when neither tab selection nor membership
changed.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket


STATE_ATTRIBUTE = "_ktt_external_tree_state"


def event_socket_path(os_window_id: int) -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(runtime) / "ktt" / f"kitty-{os.getpid()}-os-{os_window_id}.sock"


def _notify(os_window_id: int) -> None:
    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sender.setblocking(False)
    try:
        sender.sendto(b"tabs", str(event_socket_path(os_window_id)))
    except OSError:
        pass
    finally:
        sender.close()


def on_tab_bar_dirty(boss, _window, data: dict) -> None:
    tab_manager = data.get("tab_manager")
    if tab_manager is None:
        return
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
    _notify(os_window_id)
