"""Keep an automatically refreshed Kitty session manifest for crash recovery."""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from .kitty import RemoteControl
from .session import (
    SessionManifestError,
    SessionResolver,
    autosave_session_path,
    autosave_sessions_dir,
    capture_session,
    default_recovery_path,
    previous_recovery_path,
    read_manifest,
    write_manifest,
)


RECOVERY_REFRESH_SECONDS = 30.0
RECOVERY_SETTLE_SECONDS = 1.0
AUTOSAVE_RETENTION_DAYS = 8
AUTOSAVE_MAX_FILES = 200


class RecoverySnapshotter:
    """Write full snapshots periodically and soon after tab topology changes."""

    def __init__(
        self,
        remote: RemoteControl,
        *,
        path: Path | None = None,
        refresh_seconds: float = RECOVERY_REFRESH_SECONDS,
        settle_seconds: float = RECOVERY_SETTLE_SECONDS,
        log_error: Callable[[str], None] | None = None,
        session_resolver: SessionResolver | None = None,
    ) -> None:
        self.remote = remote
        self.path = path or default_recovery_path()
        self.refresh_seconds = refresh_seconds
        self.settle_seconds = settle_seconds
        self.log_error = log_error or (lambda _message: None)
        self.session_resolver = session_resolver
        self._requested = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._archive_path: Path | None = None
        self._owns_archive_bucket = False

    def start(self) -> None:
        if self._thread is not None:
            return
        preserve_previous_snapshot(self.path)
        self._thread = threading.Thread(
            target=self._run,
            name="ktt-recovery-snapshot",
            daemon=True,
        )
        self._thread.start()
        self.request()

    def request(self) -> None:
        """Request a coalesced snapshot after Kitty's state has settled."""
        self._requested.set()

    def stop(self) -> None:
        self._stopped.set()
        self._requested.set()

    def snapshot_once(self) -> None:
        manifest = capture_session(
            self.remote.snapshot(),
            hostname=socket.gethostname(),
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            session_resolver=self.session_resolver,
        )
        write_manifest(self.path, manifest)
        archive_path = autosave_session_path(manifest.created_at, self.path)
        if archive_path != self._archive_path:
            self._archive_path = archive_path
            self._owns_archive_bucket = not archive_path.exists()
            prune_autosave_history(self.path)
        if self._owns_archive_bucket:
            write_manifest(archive_path, manifest)

    def _run(self) -> None:
        while not self._stopped.is_set():
            topology_changed = self._requested.wait(self.refresh_seconds)
            if self._stopped.is_set():
                return
            if topology_changed:
                # Opening a tab and starting its agent are separate operations.  A
                # short delay lets the snapshot capture the resumable session ID.
                if self._stopped.wait(self.settle_seconds):
                    return
                self._requested.clear()
            try:
                self.snapshot_once()
            except Exception as error:
                detail = str(error) or type(error).__name__
                if detail != self._last_error:
                    self.log_error(f"ktt recovery snapshot failed: {detail}")
                self._last_error = detail
            else:
                self._last_error = None

def preserve_previous_snapshot(path: Path) -> None:
    """Retain the prior Kitty process's final snapshot before overwriting it."""
    if not path.exists():
        return
    try:
        manifest = read_manifest(path)
        archive_path = autosave_session_path(manifest.created_at, path)
        if not archive_path.exists():
            write_manifest(archive_path, manifest)
        prune_autosave_history(path)
    except (OSError, SessionManifestError, ValueError):
        # The legacy previous-generation file remains a fallback if archival
        # cannot be completed.
        pass
    previous = previous_recovery_path(path)
    os.replace(path, previous)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def prune_autosave_history(
    path: Path | None = None,
    *,
    now: datetime | None = None,
) -> None:
    directory = autosave_sessions_dir(path)
    if not directory.exists():
        return
    reference = now or datetime.now().astimezone()
    cutoff = reference - timedelta(days=AUTOSAVE_RETENTION_DAYS)
    retained: list[tuple[datetime, Path]] = []
    for archive in directory.glob("autosave-*.json"):
        try:
            saved_at = datetime.fromisoformat(read_manifest(archive).created_at)
        except (OSError, SessionManifestError, ValueError):
            continue
        if saved_at < cutoff:
            archive.unlink()
        else:
            retained.append((saved_at, archive))
    retained.sort(reverse=True)
    for _saved_at, archive in retained[AUTOSAVE_MAX_FILES:]:
        archive.unlink()
