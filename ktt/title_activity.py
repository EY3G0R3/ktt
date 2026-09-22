"""Read agent activity from Kitty's title-change events instead of polling.

Agents that publish no `workmux_status` still animate their tab titles while
they work, and leave the last spinner glyph frozen in the title when they stop.
A snapshot therefore cannot tell work from a stale decoration, and sampling
titles to compare glyphs costs a poll per frame.  Kitty already reports every
title change to its watchers, so activity is whatever the agent last told us.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from . import model


ACTIVITY_GRACE_SECONDS = 1.5
# Animated cards need their next frame; this paces redraws, not title reads.
FRAME_INTERVAL_SECONDS = 0.12


class TitleActivity:
    """Hold the deadline until which each window counts as actively working."""

    def __init__(
        self,
        *,
        grace: float = ACTIVITY_GRACE_SECONDS,
        frame_interval: float = FRAME_INTERVAL_SECONDS,
    ) -> None:
        if grace < 0 or frame_interval < 0:
            raise ValueError("title activity intervals must not be negative")
        self.grace = grace
        self.frame_interval = frame_interval
        self._active_until: dict[int, float] = {}
        self._frame_deadline: float | None = None

    def record(self, window_id: int, title: str, now: float) -> None:
        """Note a title Kitty just reported for one window."""
        if not model.title_spinner(title):
            # Shells and log panes retitle themselves too; only a spinner glyph
            # marks the title as an agent reporting its own progress.
            self._active_until.pop(window_id, None)
            return
        self._active_until[window_id] = now + self.grace

    def forget(self, window_id: int) -> None:
        self._active_until.pop(window_id, None)

    def working(self, window_ids: Iterable[int], now: float) -> bool:
        return any(
            now < self._active_until.get(window_id, 0.0)
            for window_id in window_ids
        )

    @property
    def next_deadline(self) -> float | None:
        return self._frame_deadline

    def apply(self, records: Iterable[model.TabRecord], now: float) -> list[model.TabRecord]:
        """Fold observed title activity into records about to be rendered."""
        updated: list[model.TabRecord] = []
        animated = False
        for record in records:
            working = self.working(record.window_ids, now)
            animated = animated or working
            updated.append(_with_title_activity(record, working))
        for window_id, until in tuple(self._active_until.items()):
            if now >= until:
                self._active_until.pop(window_id, None)
        self._frame_deadline = now + self.frame_interval if animated else None
        return updated


def _with_title_activity(record: model.TabRecord, working: bool) -> model.TabRecord:
    status = record.status or (model.WORKING_STATUS if working else None)
    attention_suppressed = status in model.WAITING_STATUSES and working
    if (
        status == record.status
        and attention_suppressed == record.attention_suppressed
    ):
        return record
    return replace(
        record, status=status, attention_suppressed=attention_suppressed
    )


_activity: TitleActivity | None = None


def activity() -> TitleActivity:
    """Return the per-Kitty-process registry shared by watcher and renderer."""
    global _activity
    if _activity is None:
        _activity = TitleActivity()
    return _activity
