"""User configuration for KTT, read from `~/.config/ktt/config.toml`.

KTT had no configuration file until the phase track grew several styles worth
keeping. The file is optional: a missing file, an unreadable one, an unknown
key, or an unknown value all fall back to the defaults below, because a typo
in a cosmetic setting must never take the tab bar down with it. Every value is
validated against the vocabulary the renderer actually supports, so a stale
name from an older version degrades to the default rather than raising deep
inside a Kitty draw call.

Kitty reloads the renderer on `kitty @ load-config`, and the renderer reads
this module at import, so editing the file and reloading twice applies it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from typing import Any

PHASE_TRACK_FORMS = (
    "dots",
    "blocks",
    "squares",
    "bar",
    "thick",
    "stairs",
    "braille",
    "full",
)
PHASE_TRACK_COLORS = (
    "phase",
    "two_tone",
    "gradient",
    "rainbow",
    "accent",
    "fixed",
)
DEFAULT_PHASE_TRACK_FORM = "squares"
DEFAULT_PHASE_TRACK_COLOR = "phase"


@dataclass(frozen=True)
class Config:
    phase_track_form: str = DEFAULT_PHASE_TRACK_FORM
    phase_track_color: str = DEFAULT_PHASE_TRACK_COLOR


def config_path() -> Path:
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    )
    return config_home / "ktt" / "config.toml"


def _choice(table: Any, key: str, allowed: tuple[str, ...], default: str) -> str:
    value = table.get(key) if isinstance(table, dict) else None
    return value if isinstance(value, str) and value in allowed else default


def parse_config(text: str) -> Config:
    """Parse config text, falling back to defaults for anything unusable."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return Config()
    phase_track = data.get("phase_track")
    return Config(
        phase_track_form=_choice(
            phase_track, "form", PHASE_TRACK_FORMS, DEFAULT_PHASE_TRACK_FORM
        ),
        phase_track_color=_choice(
            phase_track, "color", PHASE_TRACK_COLORS, DEFAULT_PHASE_TRACK_COLOR
        ),
    )


def load_config(path: Path | None = None) -> Config:
    """Read the config file, or the defaults when it is absent or unreadable."""
    try:
        text = (path or config_path()).read_text(encoding="utf-8")
    except OSError:
        return Config()
    return parse_config(text)
