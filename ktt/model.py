from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Iterable


PARENT_VAR = "ktt_parent_window_id"
STATUS_VAR = "workmux_status"
WAITING_STATUS = "💬"
WORKING_STATUS = "🤖"

CLAUDE_SPINNER_CHARS = frozenset(
    "✳✻✽✢✶✷◐◓◑◒◴◵◶◷◜◝◞◟"
) | {chr(code) for code in range(0x2800, 0x2900)}


@dataclass(frozen=True)
class TabRecord:
    id: int
    os_window_id: int
    title: str
    window_ids: tuple[int, ...]
    is_active: bool = False
    parent_window_id: int | None = None
    status: str | None = None
    source_index: int = 0


@dataclass(frozen=True)
class TreeRow:
    tab: TabRecord
    depth: int
    parent_tab_id: int | None
    orphaned: bool = False
    has_children: bool = False
    is_collapsed: bool = False
    has_active_descendant: bool = False


def _ordered_windows(tab: dict[str, Any]) -> list[dict[str, Any]]:
    windows = list(tab.get("windows") or [])
    return sorted(windows, key=lambda window: not bool(window.get("is_active")))


def _first_user_var(windows: Iterable[dict[str, Any]], key: str) -> str | None:
    for window in windows:
        value = str((window.get("user_vars") or {}).get(key) or "")
        if value:
            return value
    return None


def _positive_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def clean_title(title: str) -> str:
    title = title.strip()
    while title and title[0] in CLAUDE_SPINNER_CHARS:
        title = title[1:].lstrip()
    if title.startswith(" "):
        title = title[2:].lstrip()
    title = re.sub(r"^[^@\s]+@[^:]+:", "", title, count=1)
    return title or "untitled"


def title_is_working(title: str) -> bool:
    title = title.lstrip()
    return bool(title) and title[0] in CLAUDE_SPINNER_CHARS


def records_for_os_window(os_window: dict[str, Any]) -> list[TabRecord]:
    records: list[TabRecord] = []
    os_window_id = int(os_window["id"])
    for index, tab in enumerate(os_window.get("tabs") or []):
        windows = _ordered_windows(tab)
        window_ids = tuple(int(window["id"]) for window in windows)
        title = str(tab.get("title") or "")
        if title == "surf" or not title:
            title = next(
                (
                    str(window.get("title") or "")
                    for window in windows
                    if window.get("title") and window.get("title") != "surf"
                ),
                title,
            )
        status = _first_user_var(windows, STATUS_VAR)
        if status == WAITING_STATUS and title_is_working(title):
            status = WORKING_STATUS
        records.append(
            TabRecord(
                id=int(tab["id"]),
                os_window_id=os_window_id,
                title=clean_title(title),
                window_ids=window_ids,
                is_active=bool(tab.get("is_active")),
                parent_window_id=_positive_int(
                    _first_user_var(windows, PARENT_VAR)
                ),
                status=status,
                source_index=index,
            )
        )
    return records


def tree_rows(
    records: Iterable[TabRecord],
    collapsed_tab_ids: set[int] | frozenset[int] = frozenset(),
) -> list[TreeRow]:
    tabs = list(records)
    tab_by_id = {tab.id: tab for tab in tabs}
    tab_for_window = {
        window_id: tab.id for tab in tabs for window_id in tab.window_ids
    }
    parent_for: dict[int, int] = {}
    orphaned: set[int] = set()

    for tab in tabs:
        parent_window_id = tab.parent_window_id
        if parent_window_id is None:
            continue
        parent_tab_id = tab_for_window.get(parent_window_id)
        if parent_tab_id is None:
            orphaned.add(tab.id)
        elif parent_tab_id != tab.id:
            parent_for[tab.id] = parent_tab_id

    # Remove every edge involved in a cycle. All affected tabs remain visible as
    # roots instead of becoming unreachable.
    for start in list(parent_for):
        path: list[int] = []
        position: dict[int, int] = {}
        current = start
        while current in parent_for:
            if current in position:
                for tab_id in path[position[current]:]:
                    orphaned.add(tab_id)
                    parent_for.pop(tab_id, None)
                break
            position[current] = len(path)
            path.append(current)
            current = parent_for[current]

    children: dict[int, list[int]] = {tab.id: [] for tab in tabs}
    for child_id, parent_id in parent_for.items():
        children[parent_id].append(child_id)
    for child_ids in children.values():
        child_ids.sort(key=lambda tab_id: tab_by_id[tab_id].source_index)

    active_cache: dict[int, bool] = {}

    def subtree_is_active(tab_id: int) -> bool:
        cached = active_cache.get(tab_id)
        if cached is not None:
            return cached
        active = tab_by_id[tab_id].is_active or any(
            subtree_is_active(child_id) for child_id in children[tab_id]
        )
        active_cache[tab_id] = active
        return active

    rows: list[TreeRow] = []
    emitted: set[int] = set()

    def visit(tab_id: int, depth: int) -> None:
        if tab_id in emitted:
            return
        emitted.add(tab_id)
        has_children = bool(children[tab_id])
        is_collapsed = has_children and tab_id in collapsed_tab_ids
        rows.append(
            TreeRow(
                tab=tab_by_id[tab_id],
                depth=depth,
                parent_tab_id=parent_for.get(tab_id),
                orphaned=tab_id in orphaned,
                has_children=has_children,
                is_collapsed=is_collapsed,
                has_active_descendant=any(
                    subtree_is_active(child_id) for child_id in children[tab_id]
                ),
            )
        )
        if not is_collapsed:
            for child_id in children[tab_id]:
                visit(child_id, depth + 1)

    for tab in tabs:
        if tab.id not in parent_for:
            visit(tab.id, 0)
    return rows


def active_tree_row_index(rows: list[TreeRow]) -> int:
    active = next(
        (index for index, row in enumerate(rows) if row.tab.is_active),
        None,
    )
    if active is not None:
        return active
    return next(
        (index for index, row in enumerate(rows) if row.has_active_descendant),
        0,
    )


def adjacent_tree_tab_id(rows: list[TreeRow], direction: int) -> int | None:
    """Return the adjacent visible tab without wrapping at either boundary."""
    if not rows or direction == 0:
        return None
    target_index = active_tree_row_index(rows) + (1 if direction > 0 else -1)
    if not 0 <= target_index < len(rows):
        return None
    return rows[target_index].tab.id


def with_active_tab(records: Iterable[TabRecord], tab_id: int) -> list[TabRecord]:
    return [
        replace(record, is_active=record.id == tab_id)
        for record in records
    ]


def choose_os_window(
    snapshot: list[dict[str, Any]],
    target_os_window_id: int | None = None,
    self_window_id: int | None = None,
) -> dict[str, Any]:
    if target_os_window_id is not None:
        for os_window in snapshot:
            if int(os_window["id"]) == target_os_window_id:
                return os_window
        raise ValueError(f"Kitty OS window {target_os_window_id} does not exist")

    self_os_window_id = None
    if self_window_id is not None:
        for os_window in snapshot:
            if any(
                int(window["id"]) == self_window_id
                for tab in os_window.get("tabs") or []
                for window in tab.get("windows") or []
            ):
                self_os_window_id = int(os_window["id"])
                break

    candidates = [
        os_window
        for os_window in snapshot
        if len(snapshot) == 1 or int(os_window["id"]) != self_os_window_id
    ]
    if not candidates:
        raise ValueError("Kitty reported no controllable OS windows")
    return max(
        candidates,
        key=lambda os_window: (
            len(os_window.get("tabs") or []),
            bool(os_window.get("is_active")),
            int(os_window["id"]),
        ),
    )
