from __future__ import annotations

import shutil
import subprocess

from .model import TabRecord, tree_rows


def parent_candidates(
    records: list[TabRecord], child_tab_id: int
) -> list[TabRecord]:
    """Return tabs that can become the child's parent without making a cycle."""
    tab_for_window = {
        window_id: record.id
        for record in records
        for window_id in record.window_ids
    }
    parent_for = {
        record.id: tab_for_window[record.parent_window_id]
        for record in records
        if record.parent_window_id in tab_for_window
        and tab_for_window[record.parent_window_id] != record.id
    }

    valid_ids: set[int] = set()
    for candidate in records:
        if candidate.id == child_tab_id:
            continue
        current = candidate.id
        visited: set[int] = set()
        while current in parent_for and current not in visited:
            if current == child_tab_id:
                break
            visited.add(current)
            current = parent_for[current]
        else:
            if current != child_tab_id:
                valid_ids.add(candidate.id)

    return [
        row.tab for row in tree_rows(records) if row.tab.id in valid_ids
    ]


def choose_parent_tab(
    records: list[TabRecord], child_tab_id: int
) -> TabRecord | None:
    child = next(
        (record for record in records if record.id == child_tab_id), None
    )
    if child is None:
        raise RuntimeError(f"selected Kitty tab {child_tab_id} no longer exists")

    candidates = parent_candidates(records, child_tab_id)
    if not candidates:
        raise RuntimeError("no other valid tabs are available as a parent")

    rofi = shutil.which("rofi")
    if rofi is None:
        raise RuntimeError("rofi is required for parent selection")

    labels = [
        f"{candidate.title.replace(chr(10), ' ')}  [tab {candidate.id}]"
        for candidate in candidates
    ]
    result = subprocess.run(
        [
            rofi,
            "-dmenu",
            "-i",
            "-p",
            f"New parent for {child.title}",
            "-format",
            "i",
        ],
        input="\n".join(labels) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit status {result.returncode}"
        raise RuntimeError(f"rofi parent selection failed: {message}")
    try:
        index = int(result.stdout.strip())
        if index < 0:
            raise IndexError
        return candidates[index]
    except (ValueError, IndexError) as error:
        raise RuntimeError("rofi returned an invalid parent selection") from error
