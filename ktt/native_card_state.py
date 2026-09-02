"""Live Kitty adapter for KTT's canonical native card renderer."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
import time
from typing import Any, Callable, Mapping

from . import kitty_tabs, model, render
from .repository import (
    AsyncFancylogMonitor,
    FancylogIdentityCache,
    with_repository_worktrees,
)


STATUS_ALIASES = {
    "working": model.WORKING_STATUS,
    "waiting": model.WAITING_STATUS,
    "done": "✅",
    "complete": "✅",
}
FRAME_CACHE_LIMIT = len(render.SPINNER_FRAMES) + 2


class NativeCardState:
    """Cache live metadata and render native rows with established semantics."""

    def __init__(
        self,
        *,
        identities: FancylogIdentityCache | None = None,
        summary_factory: Callable[[], AsyncFancylogMonitor] = AsyncFancylogMonitor,
    ) -> None:
        self.identities = identities or FancylogIdentityCache()
        self.summary_factory = summary_factory
        self.summaries: dict[int, AsyncFancylogMonitor] = {}
        self.waiting = model.WaitingStatusDebouncer()
        self._frame_key: tuple[Any, ...] | None = None
        self._frame: dict[int, tuple[str, ...]] = {}
        self._frame_cache: dict[
            int,
            OrderedDict[
                tuple[Any, ...], dict[int, tuple[str, ...]]
            ],
        ] = {}
        self._redraw_frames: dict[
            int,
            tuple[
                object,
                int,
                int,
                tuple[tuple[int, str], ...],
                dict[int, tuple[str, ...]],
            ],
        ] = {}

    def render(
        self,
        tab_manager: Any,
        *,
        width: int,
        card_height: int,
        now: float | None = None,
        frame_token: object | None = None,
        background_overrides: Mapping[int, str] | None = None,
    ) -> dict[int, tuple[str, ...]]:
        os_window_id = int(tab_manager.os_window_id)
        background_overrides = background_overrides or {}
        background_override_key = tuple(sorted(background_overrides.items()))
        cached_redraw = self._redraw_frames.get(os_window_id)
        if (
            frame_token is not None
            and cached_redraw is not None
            and cached_redraw[0] is frame_token
            and cached_redraw[1] == width
            and cached_redraw[2] == card_height
            and cached_redraw[3] == background_override_key
        ):
            return cached_redraw[4]
        current = time.monotonic() if now is None else now
        records = [
            replace(record, status=STATUS_ALIASES.get(record.status, record.status))
            for record in kitty_tabs.live_tree_records(tab_manager)
        ]
        records = self.waiting.update(records, current)
        names = self.identities.update(
            (record.cwd for record in records), current
        )
        records = model.with_repository_names(records, names)
        records = with_repository_worktrees(
            records, self.identities.worktrees()
        )
        rows = model.tree_rows(records)
        active = next((row.tab for row in rows if row.tab.is_active), None)
        active_path = active.cwd if active is not None else None
        summary = self.summaries.setdefault(
            os_window_id, self.summary_factory()
        )
        repository_lines = summary.update(
            active_path, width, 2, current
        )
        active_location = self.identities.locations.get(active_path or "")
        hues = render.repository_hue_assignments(tuple(
            row.tab.repository for row in rows if row.tab.repository
        ))
        animated = any(
            row.tab.status == model.WORKING_STATUS for row in rows
        )
        frame_key = (
            tuple(rows),
            width,
            card_height,
            background_override_key,
            tuple(repository_lines),
            active_location,
            (
                int(current / render.SPINNER_INTERVAL)
                % len(render.SPINNER_FRAMES)
                if animated
                else None
            ),
        )
        if frame_key == self._frame_key:
            if frame_token is not None:
                self._redraw_frames[os_window_id] = (
                    frame_token,
                    width,
                    card_height,
                    background_override_key,
                    self._frame,
                )
            return self._frame
        frame_cache = self._frame_cache.setdefault(
            os_window_id, OrderedDict()
        )
        cached_frame = frame_cache.pop(frame_key, None)
        self._frame_key = frame_key
        if cached_frame is None:
            cached_frame = {
                row.tab.id: tuple(render.render_card(
                    row,
                    selected=row.tab.is_active,
                    width=width,
                    card_height=card_height,
                    now=current,
                    repository_hue=hues.get(row.tab.repository or ""),
                    repository_location=(
                        active_location if row.tab.is_active else None
                    ),
                    repository_lines=(
                        repository_lines if row.tab.is_active else None
                    ),
                    background_override=background_overrides.get(row.tab.id),
                ))
                for row in rows
            }
        self._frame = cached_frame
        frame_cache[frame_key] = cached_frame
        while len(frame_cache) > FRAME_CACHE_LIMIT:
            frame_cache.popitem(last=False)
        if frame_token is not None:
            self._redraw_frames[os_window_id] = (
                frame_token,
                width,
                card_height,
                background_override_key,
                self._frame,
            )
        return self._frame

    def needs_refresh(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return (
            bool(self.identities.pending)
            or any(
                summary.needs_refresh(current)
                for summary in self.summaries.values()
            )
            or (
                self.waiting.next_deadline is not None
                and current >= self.waiting.next_deadline
            )
        )

    def close(self) -> None:
        self.identities.close()
        for summary in self.summaries.values():
            summary.close()
        self.summaries.clear()
        self._frame_cache.clear()
        self._redraw_frames.clear()
