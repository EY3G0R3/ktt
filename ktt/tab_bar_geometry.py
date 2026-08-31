"""Pure geometry and tree helpers for Kitty's native vertical tab renderer."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, Sequence
from typing import TypeAlias


DEFAULT_MAX_CELLS = 40
TopologyEntry: TypeAlias = tuple[int, tuple[int, ...], int | None]
TopologySignature: TypeAlias = tuple[TopologyEntry, ...]


def select_content_windows(
    windows: Sequence[object],
    *,
    user_var: Callable[[object, str], str],
    sidebar_var: str,
    role_var: str,
    agent_role: str,
    is_active: Callable[[object], bool] | None = None,
) -> tuple[object, ...]:
    """Select content windows with agent role ahead of active-window state."""
    active = is_active or (lambda _window: False)
    return tuple(sorted(
        (
            window
            for window in windows
            if user_var(window, sidebar_var) != "1"
        ),
        key=lambda window: (
            user_var(window, role_var) != agent_role,
            not active(window),
        ),
    ))


def bounded_cell_count(max_cells: int) -> int:
    """Use a finite native width even when Kitty reports no explicit bound."""
    return max_cells if max_cells > 0 else DEFAULT_MAX_CELLS


def is_vertical_edge(edge: object, left_edge: object, right_edge: object) -> bool:
    return left_edge is not None and edge in (left_edge, right_edge)


def tree_indent(depth: int, max_cells: int) -> str:
    """Build a bounded four-cell indent while reserving one title cell."""
    max_cells = bounded_cell_count(max_cells)
    depth = max(0, int(depth))
    max_depth = max(0, (max_cells - 5) // 4)
    depth = min(depth, max_depth)
    return f"{' ' * (4 * depth)}└─ " if depth else ""


def _shorter_indent(indent: str) -> str:
    if not indent.endswith("└─ "):
        return ""
    spaces = len(indent) - len("└─ ")
    return f"{' ' * (spaces - 4)}└─ " if spaces > 4 else ""


def fit_vertical_title(
    indent: str,
    prefixes: Sequence[str],
    title: str,
    max_cells: int,
    *,
    sanitize: Callable[[str], str],
    measure: Callable[[str], int],
    truncate: Callable[[str, int], str],
) -> str:
    """Fit trusted indent/decorations and sanitized title into one cell row."""
    max_cells = bounded_cell_count(max_cells)
    title = sanitize(str(title))
    prefixes = list(prefixes)

    def decoration() -> str:
        return indent + " ".join(prefixes)

    # Preserve semantic labels before tree depth when the bar is narrow.
    while indent and measure(decoration()) + 1 >= max_cells:
        indent = _shorter_indent(indent)
    while prefixes and measure(decoration()) + 1 >= max_cells:
        prefixes.pop(0)
    decorated = decoration()
    gap = " " if decorated else ""
    title_budget = max(0, max_cells - measure(decorated) - len(gap))
    rendered = decorated + gap + truncate(title, title_budget)
    if measure(rendered) > max_cells:
        return truncate(title, max_cells)
    return rendered


def vertical_cursor_plan(
    before: int, after_title: int, max_tab_length: int
) -> tuple[int, int]:
    """Return cursor rewind and trailing fill without exceeding the row bound."""
    limit = max(0, int(max_tab_length))
    if limit <= 1:
        return 0, 0
    overflow = after_title - before - limit
    rewind = overflow + 1 if overflow > 0 else 0
    cursor = after_title - rewind + (1 if rewind else 0)
    remaining = max(0, limit - (cursor - before))
    return rewind, remaining


def valid_parent_tab_ids(signature: TopologySignature) -> dict[int, int]:
    """Resolve window parents to tabs and remove every edge in a cycle."""
    tab_for_window = {
        window_id: tab_id
        for tab_id, window_ids, _parent_window_id in signature
        for window_id in window_ids
    }
    parent_for = {
        tab_id: parent_tab_id
        for tab_id, _window_ids, parent_window_id in signature
        if parent_window_id is not None
        and (parent_tab_id := tab_for_window.get(parent_window_id)) is not None
        and parent_tab_id != tab_id
    }
    for start in tuple(parent_for):
        path: list[int] = []
        position: dict[int, int] = {}
        current = start
        while current in parent_for:
            if current in position:
                for tab_id in path[position[current]:]:
                    parent_for.pop(tab_id, None)
                break
            position[current] = len(path)
            path.append(current)
            current = parent_for[current]
    return parent_for


def tree_depths(signature: TopologySignature) -> dict[int, int]:
    parent_for = valid_parent_tab_ids(signature)
    depths: dict[int, int] = {}

    def depth_for(tab_id: int) -> int:
        if tab_id not in depths:
            parent_id = parent_for.get(tab_id)
            depths[tab_id] = 0 if parent_id is None else depth_for(parent_id) + 1
        return depths[tab_id]

    for tab_id, _window_ids, _parent_window_id in signature:
        depth_for(tab_id)
    return depths


def cached_tree_depth(
    cache: MutableMapping[int, tuple[TopologySignature, dict[int, int]]],
    os_window_id: int,
    signature: TopologySignature,
    tab_id: int,
) -> int:
    cached = cache.get(os_window_id)
    if (
        not isinstance(cached, tuple)
        or len(cached) != 2
        or cached[0] != signature
        or not isinstance(cached[1], dict)
    ):
        cached = (signature, tree_depths(signature))
        cache[os_window_id] = cached
    return cached[1].get(tab_id, 0)
