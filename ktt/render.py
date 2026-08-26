from __future__ import annotations

import colorsys
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re
import time
import unicodedata

from .model import TabRecord, TreeRow
from .repository import RepositoryLocation


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL = 0.12
VERDICT_BACKGROUNDS = {
    "ready_to_merge": ("1b5e36", "2f9c5c"),
    "blocked": ("7a2029", "c0394a"),
}
WAITING_BACKGROUNDS = ("d8dee9", "f8f8f2")
PANEL_BACKGROUND = "000000"
ACTIVE_BACKGROUND = "4c566a"
ACTIVE_DESCENDANT_BACKGROUND = "343b49"
INACTIVE_BACKGROUND = "20232a"
LEFT_CAP = ""
RIGHT_CAP = ""
FLAME_RIGHT_CAP = ""
READY_RIGHT_CAP = ""
WEDGE_TOP_LEFT = ""
WEDGE_TOP_RIGHT = ""
WEDGE_BOTTOM_LEFT = ""
WEDGE_BOTTOM_RIGHT = ""
EDGE_STYLES = ("tapered", "straight", "rounded", "wedge")
DEFAULT_EDGE_STYLE = EDGE_STYLES[0]
ORIENTATIONS = ("vertical", "horizontal")
DEFAULT_ORIENTATION = ORIENTATIONS[0]
TREE_INDENT_WIDTH = 4
STATUS_CELL_WIDTH = 2
HORIZONTAL_MIN_CARD_WIDTH = 14
HORIZONTAL_MAX_CARD_WIDTH = 40
HORIZONTAL_TREE_INDENT = 4
HORIZONTAL_CONTROL_TEXT = (
    "j/k switch · Enter/click enter · Space fold · p parent · e edges · "
    "t tabs · ? help · q quit"
)
CONTROL_ROWS = (
    ("↑/↓ · j/k · wheel", "switch tab"),
    ("Enter · click", "enter tab"),
    ("Space · right-click", "fold tree"),
    ("e", "edge style"),
    ("p", "parent"),
    ("r", "refresh"),
    ("t", "native tab bar"),
    ("?", "pin help"),
    ("q", "quit"),
)
CONTROL_LEFT_WIDTH = max(len(shortcut) for shortcut, _ in CONTROL_ROWS)
CONTROL_RIGHT_WIDTH = max(
    max(len(action) for _, action in CONTROL_ROWS),
    max(len(f"edge: {style}") for style in EDGE_STYLES),
)
CONTROL_SEPARATOR = " │ "
CONTROL_SHORTCUT_FOREGROUND = "5f7a82"
CONTROL_SEPARATOR_FOREGROUND = "3f4552"
CONTROL_ACTION_FOREGROUND = "777d89"
REPOSITORY_TOP_GAP = 1
REPOSITORY_BOTTOM_MARGIN = 1
REPOSITORY_BACKGROUND = "20232a"
REPOSITORY_NAME_FOREGROUND = "f8f8f2"
REPOSITORY_META_FOREGROUND = "777d89"
REPOSITORY_WORKTREE_FOREGROUND = "ffb86c"
REPOSITORY_HEADING_FOREGROUND = "f1fa8c"
REPOSITORY_BRANCH_FOREGROUND = "8be9fd"
REPOSITORY_CLEAN_FOREGROUND = "50fa7b"
REPOSITORY_DIRTY_FOREGROUND = "f1fa8c"
REPOSITORY_CONFLICT_FOREGROUND = "ff5555"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_LINES = tuple(
    f"{shortcut:>{CONTROL_LEFT_WIDTH}}{CONTROL_SEPARATOR}"
    f"{(f'edge: {DEFAULT_EDGE_STYLE}' if shortcut == 'e' else action):<{CONTROL_RIGHT_WIDTH}}"
    for shortcut, action in CONTROL_ROWS
)


def next_edge_style(edge_style: str) -> str:
    try:
        index = EDGE_STYLES.index(edge_style)
    except ValueError:
        return DEFAULT_EDGE_STYLE
    return EDGE_STYLES[(index + 1) % len(EDGE_STYLES)]


def _fg(hex_color: str, enabled: bool) -> str:
    if not enabled:
        return ""
    red, green, blue = (int(hex_color[offset:offset + 2], 16) for offset in (0, 2, 4))
    return f"\x1b[38;2;{red};{green};{blue}m"


def _bg(hex_color: str, enabled: bool) -> str:
    if not enabled:
        return ""
    red, green, blue = (int(hex_color[offset:offset + 2], 16) for offset in (0, 2, 4))
    return f"\x1b[48;2;{red};{green};{blue}m"


def panel_style(ansi: bool = True) -> str:
    return _bg(PANEL_BACKGROUND, ansi) + _fg("f8f8f2", ansi)


def _relative_luminance(hex_color: str) -> float:
    channels = [
        int(hex_color[offset:offset + 2], 16) / 255
        for offset in (0, 2, 4)
    ]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (light + 0.05) / (dark + 0.05)


@lru_cache(maxsize=256)
def repository_label_foreground(
    repository: str,
    background: str,
    hue: float | None = None,
) -> str:
    """Return a stable repository hue adjusted for the card's contrast."""
    digest = hashlib.blake2s(
        repository.casefold().encode("utf-8"), digest_size=3
    ).digest()
    hue_seed = int.from_bytes(digest[:2], "big")
    # Permute neighboring hash values around the hue wheel instead of letting
    # an accidental near-match produce nearly identical repository colors.
    hue = hue if hue is not None else ((hue_seed * 40503) & 0xffff) / 65536
    saturation = 0.62 + digest[2] / 255 * 0.18
    target_lightness = 0.72 if _relative_luminance(background) < 0.4 else 0.3
    candidates: list[tuple[float, str, float]] = []
    for step in range(15, 86):
        lightness = step / 100
        channels = colorsys.hls_to_rgb(hue, lightness, saturation)
        foreground = "".join(f"{round(channel * 255):02x}" for channel in channels)
        candidates.append(
            (lightness, foreground, _contrast_ratio(foreground, background))
        )
    readable = [candidate for candidate in candidates if candidate[2] >= 4.5]
    if readable:
        return min(readable, key=lambda candidate: abs(candidate[0] - target_lightness))[1]
    return max(candidates, key=lambda candidate: candidate[2])[1]


def _hue_distance(first: float, second: float) -> float:
    distance = abs(first - second)
    return min(distance, 1 - distance)


@lru_cache(maxsize=64)
def repository_hue_assignments(repositories: tuple[str, ...]) -> dict[str, float]:
    """Keep repositories in one tree perceptually distinct from each other."""
    names = tuple(sorted(set(repositories)))
    if not names:
        return {}
    minimum_distance = min(45 / 360, (300 / len(names)) / 360)
    golden_angle = 137.50776405003785 / 360
    ordered = sorted(
        names,
        key=lambda name: hashlib.blake2s(name.casefold().encode("utf-8")).digest(),
    )
    assigned: dict[str, float] = {}
    used: list[float] = []
    for name in ordered:
        digest = hashlib.blake2s(
            name.casefold().encode("utf-8"), digest_size=3
        ).digest()
        seed = int.from_bytes(digest[:2], "big")
        base = ((seed * 40503) & 0xffff) / 65536
        candidates = tuple((base + index * golden_angle) % 1 for index in range(24))
        separated = [
            candidate
            for candidate in candidates
            if all(
                _hue_distance(candidate, existing) >= minimum_distance
                for existing in used
            )
        ]
        chosen = (
            separated[0]
            if separated
            else max(
                candidates,
                key=lambda candidate: min(
                    (_hue_distance(candidate, existing) for existing in used),
                    default=1,
                ),
            )
        )
        assigned[name] = chosen
        used.append(chosen)
    return assigned


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def repository_summary_parts(lines: list[str]) -> tuple[str, str, str]:
    if not lines:
        return "", "", ""
    header = strip_ansi(lines[-2] if len(lines) > 1 else lines[-1]).strip()
    branch = strip_ansi(lines[-1]).strip() if len(lines) > 1 else ""
    header_parts = re.split(r"\s{2,}", header, maxsplit=1)
    identity = header_parts[0]
    state = header_parts[1].strip() if len(header_parts) > 1 else ""
    if state == "✓ working tree clean":
        state = "✓ clean"
    return identity, branch, state


def repository_identity_name(lines: list[str]) -> str | None:
    identity, _, _ = repository_summary_parts(lines)
    match = re.match(r"^\(([^)]+)\)", identity)
    return match.group(1) if match else None


def repository_dirty_heading(lines: list[str]) -> str | None:
    _, _, state = repository_summary_parts(lines)
    if not state or state.startswith("✓"):
        return None
    counts = [int(value) for value in re.findall(r"\b(\d+)\b", state)]
    if counts:
        count = sum(counts)
        noun = "file" if count == 1 else "files"
        return f"{count} modified {noun}:"
    return f"{state.rstrip(':')}:"


def worktree_matches_branch(worktree: str | None, branch: str) -> bool:
    if not worktree or not branch:
        return False
    branch_name = re.sub(r"^[^\w/.-]+\s*", "", branch)
    normalize = lambda value: re.sub(r"[^a-z0-9]+", "", value.casefold())
    return normalize(worktree) == normalize(branch_name)


def _trim_ansi_padding(text: str) -> str:
    first_visible: int | None = None
    last_visible: int | None = None
    cursor = 0
    escapes = list(ANSI_ESCAPE.finditer(text))
    for escape in [*escapes, None]:
        end = escape.start() if escape is not None else len(text)
        for offset, character in enumerate(text[cursor:end], start=cursor):
            if not character.isspace():
                first_visible = offset if first_visible is None else first_visible
                last_visible = offset
        cursor = escape.end() if escape is not None else len(text)
    if first_visible is None or last_visible is None:
        return ""
    prefix = "".join(
        escape.group() for escape in escapes if escape.end() <= first_visible
    )
    suffix = "".join(
        escape.group() for escape in escapes if escape.start() > last_visible
    )
    return f"{prefix}{text[first_visible:last_visible + 1]}{suffix}"


def render_repository_detail_lines(
    lines: list[str],
    width: int,
    *,
    ansi: bool = True,
) -> list[str]:
    details = [line for line in lines[:-2] if strip_ansi(line).strip()]
    if not details or width <= 0:
        return []
    plain = [strip_ansi(line) for line in details]
    first_columns = [
        display_width(line) - display_width(line.lstrip()) for line in plain
    ]
    last_columns = [display_width(line.rstrip()) for line in plain]
    block_left = min(first_columns)
    block_width = max(last_columns) - block_left
    available = max(1, width - 1)
    left_margin = max(0, (available - block_width) // 2)
    rendered: list[str] = []
    for line, first_column in zip(details, first_columns):
        content = _trim_ansi_padding(line if ansi else strip_ansi(line))
        rendered.append(
            f"{panel_style(ansi)}"
            f"{' ' * (left_margin + first_column - block_left)}{content}"
        )
    return rendered


def _repository_segments(
    lines: list[str],
    repository_hue: float | None = None,
    repository_location: RepositoryLocation | None = None,
    show_state: bool = True,
) -> list[tuple[str, str, bool]]:
    identity, branch, state = repository_summary_parts(lines)
    segments: list[tuple[str, str, bool]] = []
    identity_match = re.match(r"^\(([^)]+)\)\s*(.*)$", identity)
    if identity_match:
        repository = identity_match.group(1)
        segments.append((
            f"/{repository}/",
            repository_label_foreground(
                repository, REPOSITORY_BACKGROUND, repository_hue
            ),
            False,
        ))
        if repository_location is not None:
            if repository_location.worktree:
                segments.append((
                    f"   {repository_location.worktree}",
                    REPOSITORY_WORKTREE_FOREGROUND,
                    False,
                ))
            if repository_location.relative_path:
                segments.append((
                    f"  {repository_location.relative_path}",
                    REPOSITORY_META_FOREGROUND,
                    False,
                ))
        elif identity_match.group(2):
            segments.append((f"  {identity_match.group(2)}", REPOSITORY_META_FOREGROUND, False))
    elif identity:
        segments.append((identity, REPOSITORY_NAME_FOREGROUND, True))
    if branch and not worktree_matches_branch(
        repository_location.worktree if repository_location else None,
        branch,
    ):
        if segments:
            segments.append(("  ·  ", REPOSITORY_META_FOREGROUND, False))
        segments.append((branch, REPOSITORY_BRANCH_FOREGROUND, False))
    if state and show_state:
        if segments:
            segments.append(("  ·  ", REPOSITORY_META_FOREGROUND, False))
        state_color = (
            REPOSITORY_CONFLICT_FOREGROUND
            if state.startswith("✗")
            else REPOSITORY_CLEAN_FOREGROUND
            if state.startswith("✓")
            else REPOSITORY_DIRTY_FOREGROUND
        )
        segments.append((state, state_color, False))
    return segments


def _render_repository_text(
    segments: list[tuple[str, str, bool]],
    width: int,
    *,
    ansi: bool,
) -> str:
    plain = "".join(text for text, _, _ in segments)
    truncated = display_width(plain) > width
    budget = max(0, width - int(truncated))
    output: list[str] = []
    used = 0
    for segment_text, foreground, bold in segments:
        remaining = max(0, budget - used)
        fitted_characters: list[str] = []
        fitted_width = 0
        for character in segment_text:
            character_width = display_width(character)
            if fitted_width + character_width > remaining:
                break
            fitted_characters.append(character)
            fitted_width += character_width
        fitted = "".join(fitted_characters)
        if not fitted:
            continue
        output.append(_fg(foreground, ansi))
        if ansi and bold:
            output.append("\x1b[1m")
        output.append(fitted)
        if ansi and bold:
            output.append("\x1b[22m")
        used += fitted_width
        if used >= budget:
            break
    if truncated and width > 0:
        output.extend((_fg(REPOSITORY_META_FOREGROUND, ansi), "…"))
    return "".join(output)


def render_repository_card(
    lines: list[str],
    width: int,
    *,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_hue: float | None = None,
    repository_location: RepositoryLocation | None = None,
    show_state: bool = True,
) -> str:
    if width <= 0 or not lines:
        return ""
    segments = _repository_segments(
        lines, repository_hue, repository_location, show_state
    )
    if not segments:
        return ""
    available = max(1, width - 1)
    content_width = display_width("".join(text for text, _, _ in segments))
    card_width = min(available, content_width + 4)
    show_caps = card_width >= 3
    body_width = card_width - 2 if show_caps else card_width
    text_width = max(0, body_width - 2)
    drawn_width = min(content_width, text_width)
    left_text_padding = max(0, (body_width - drawn_width) // 2)
    right_text_padding = max(0, body_width - drawn_width - left_text_padding)
    left_margin = max(0, (available - card_width) // 2)
    background = _bg(REPOSITORY_BACKGROUND, ansi)
    cap_style = _bg(PANEL_BACKGROUND, ansi) + _fg(REPOSITORY_BACKGROUND, ansi)
    reset = "\x1b[0m" if ansi else ""
    effective_style = (
        DEFAULT_EDGE_STYLE if edge_style in {"rounded", "wedge"} else edge_style
    )
    if show_caps and effective_style == "tapered":
        left_edge = f"{cap_style}{LEFT_CAP}{background}"
        right_edge = f"{cap_style}{RIGHT_CAP}"
    elif show_caps and effective_style == "straight":
        left_edge = f"{background} "
        right_edge = f"{background} "
    else:
        left_edge = background
        right_edge = ""
    rendered_text = _render_repository_text(segments, text_width, ansi=ansi)
    return (
        f"{panel_style(ansi)}{' ' * left_margin}{left_edge}"
        f"{' ' * left_text_padding}{rendered_text}{background}"
        f"{' ' * right_text_padding}{right_edge}{reset}"
    )


def repository_card_fits(
    lines: list[str],
    width: int,
    *,
    repository_hue: float | None = None,
    repository_location: RepositoryLocation | None = None,
) -> bool:
    segments = _repository_segments(
        lines, repository_hue, repository_location
    )
    content_width = display_width("".join(text for text, _, _ in segments))
    return content_width + 4 <= max(1, width - 1)


def render_repository_heading(
    lines: list[str],
    details: list[str],
    width: int,
    *,
    ansi: bool = True,
) -> str:
    heading = repository_dirty_heading(lines)
    if not heading or not details or width <= 0:
        return ""
    plain_details = [strip_ansi(detail) for detail in details]
    left_margin = min(
        display_width(detail) - display_width(detail.lstrip())
        for detail in plain_details
    )
    text = truncate_cells(heading, max(0, width - left_margin))
    return (
        f"{panel_style(ansi)}{' ' * left_margin}"
        f"{_fg(REPOSITORY_HEADING_FOREGROUND, ansi)}{text}"
    )


def display_width(text: str) -> int:
    return sum(
        0 if unicodedata.combining(character)
        else 2 if unicodedata.east_asian_width(character) in {"W", "F"}
        else 1
        for character in text
    )


def fit_cells(text: str, width: int) -> str:
    fitted: list[str] = []
    used = 0
    for character in text:
        character_width = display_width(character)
        if used + character_width > width:
            break
        fitted.append(character)
        used += character_width
    return "".join(fitted) + (" " * (width - used))


def truncate_cells(text: str, width: int) -> str:
    if display_width(text) <= width:
        return text
    if width <= 1:
        return fit_cells("…", width).rstrip()
    return fit_cells(text, width - 1).rstrip() + "…"


def render_control_line(
    shortcut: str,
    action: str,
    width: int,
    *,
    ansi: bool = True,
) -> str:
    shortcut = f"{shortcut:>{CONTROL_LEFT_WIDTH}}"
    action = f"{action:<{CONTROL_RIGHT_WIDTH}}"
    plain = f"{shortcut}{CONTROL_SEPARATOR}{action}"
    if display_width(plain) > width:
        return f"{panel_style(ansi)}{truncate_cells(plain, width)}"
    padding = " " * ((width - display_width(plain)) // 2)
    return (
        f"{panel_style(ansi)}{padding}"
        f"{_fg(CONTROL_SHORTCUT_FOREGROUND, ansi)}{shortcut}"
        f"{_fg(CONTROL_SEPARATOR_FOREGROUND, ansi)}{CONTROL_SEPARATOR}"
        f"{_fg(CONTROL_ACTION_FOREGROUND, ansi)}{action}"
    )


def status_icon(status: str | None, now: float | None = None) -> tuple[str, str | None]:
    if status == "🤖":
        current = time.monotonic() if now is None else now
        frame = int(current / SPINNER_INTERVAL) % len(SPINNER_FRAMES)
        return SPINNER_FRAMES[frame], "8be9fd"
    if status == "ready_to_merge":
        return "✓", "50fa7b"
    if status == "blocked":
        return "✗", "ff5555"
    if status == "💬":
        return "💬", "20232a"
    if status == "✅":
        return "✓", None
    return (status or " "), None


def card_background(row: TreeRow) -> str:
    tab = row.tab
    if tab.status == "💬":
        return WAITING_BACKGROUNDS[1 if tab.is_active else 0]
    verdict = VERDICT_BACKGROUNDS.get(tab.status or "")
    if verdict:
        return verdict[1 if tab.is_active else 0]
    return (
        ACTIVE_BACKGROUND
        if tab.is_active
        else ACTIVE_DESCENDANT_BACKGROUND
        if row.has_active_descendant and row.is_collapsed
        else INACTIVE_BACKGROUND
    )


@dataclass(frozen=True)
class HorizontalPlacement:
    index: int
    left: int
    width: int
    screen_row: int


def _horizontal_children(rows: list[TreeRow]) -> tuple[list[int], dict[int, list[int]]]:
    index_for_tab = {row.tab.id: index for index, row in enumerate(rows)}
    children = {index: [] for index in range(len(rows))}
    roots: list[int] = []
    for index, row in enumerate(rows):
        parent = index_for_tab.get(row.parent_tab_id)
        if parent is None:
            roots.append(index)
        else:
            children[parent].append(index)
    return roots, children


def _compact_horizontal_layout(
    rows: list[TreeRow], width: int, selected_index: int
) -> list[HorizontalPlacement]:
    usable = max(0, width - 1)
    if not rows or usable < 3:
        return []
    capacity = max(1, usable // HORIZONTAL_MIN_CARD_WIDTH)
    capacity = min(capacity, len(rows))
    start = min(
        max(0, selected_index - capacity // 2),
        max(0, len(rows) - capacity),
    )
    slot_width = min(HORIZONTAL_MAX_CARD_WIDTH + 1, usable // capacity)
    group_left = max(0, (usable - capacity * slot_width) // 2)
    return [
        HorizontalPlacement(
            index=index,
            left=group_left + offset * slot_width,
            width=slot_width - 1,
            screen_row=0,
        )
        for offset, index in enumerate(range(start, start + capacity))
    ]


def horizontal_layout(
    rows: list[TreeRow],
    width: int,
    height: int,
    selected_index: int,
) -> list[HorizontalPlacement]:
    """Lay out each visible subtree in a fixed-width column growing downward."""
    usable = max(0, width - 1)
    if not rows or usable < 3 or height <= 0:
        return []
    roots, children = _horizontal_children(rows)

    def subtree(index: int) -> list[int]:
        descendants = [
            descendant
            for child in children[index]
            for descendant in subtree(child)
        ]
        return [index, *descendants]

    subtrees = [subtree(root) for root in roots]
    tree_depths = [
        max(rows[index].depth - rows[root].depth for index in indexes)
        for root, indexes in zip(roots, subtrees)
    ]
    lane_overhead = sum(
        tree_depth * HORIZONTAL_TREE_INDENT + 1
        for tree_depth in tree_depths
    )
    available_card_width = (
        (usable - lane_overhead) // len(roots) if roots else 0
    )
    if (
        not roots
        or available_card_width < HORIZONTAL_MIN_CARD_WIDTH
        or max((len(indexes) for indexes in subtrees), default=0) > height
    ):
        return _compact_horizontal_layout(rows, width, selected_index)

    card_width = min(HORIZONTAL_MAX_CARD_WIDTH, available_card_width)
    group_width = lane_overhead + len(roots) * card_width
    lane_left = max(0, (usable - group_width) // 2)
    placements: list[HorizontalPlacement] = []
    for root, indexes, tree_depth in zip(roots, subtrees, tree_depths):
        for screen_row, index in enumerate(indexes):
            relative_depth = rows[index].depth - rows[root].depth
            placements.append(
                HorizontalPlacement(
                    index,
                    lane_left + relative_depth * HORIZONTAL_TREE_INDENT,
                    card_width,
                    screen_row,
                )
            )
        lane_left += card_width + tree_depth * HORIZONTAL_TREE_INDENT + 1
    return placements


def horizontal_index_at_mouse(
    mouse_column: int,
    mouse_row: int,
    placements: list[HorizontalPlacement],
) -> int | None:
    column = mouse_column - 1
    row = mouse_row - 1
    return next(
        (
            placement.index
            for placement in placements
            if placement.screen_row == row
            and placement.left <= column < placement.left + placement.width
        ),
        None,
    )


def adaptive_card_height(row_count: int, height: int) -> int:
    available = content_height(height)
    if row_count > 0 and cards_height(row_count, 3) <= available:
        return 3
    if row_count > 0 and cards_height(row_count, 2) <= available:
        return 2
    return 1


def card_content_line(card_height: int) -> int:
    return max(0, (card_height - 1) // 2)


def card_gap(card_height: int) -> int:
    return 1 if card_height > 1 else 0


def cards_height(row_count: int, card_height: int) -> int:
    if row_count <= 0:
        return 0
    return row_count * card_height + (row_count - 1) * card_gap(card_height)


def card_capacity(available: int, card_height: int) -> int:
    gap = card_gap(card_height)
    return max(0, (available + gap) // (card_height + gap))


def tab_labels(tab: TabRecord, width: int) -> tuple[str, str]:
    repository = tab.repository or ""
    if not repository or width < 14:
        return truncate_cells(tab.title, max(0, width)), ""
    repository_width = min(20, max(6, width // 3))
    repository = f"/{truncate_cells(repository, repository_width - 2)}/"
    title_width = width - display_width(repository) - 4
    if title_width < 5:
        return truncate_cells(tab.title, max(0, width)), ""
    return truncate_cells(tab.title, title_width), repository


def render_row(
    row: TreeRow,
    *,
    selected: bool,
    width: int,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    line_index: int = 0,
    card_height: int = 1,
    repository_hue: float | None = None,
) -> str:
    tab = row.tab
    disclosure = "▸" if row.is_collapsed else "▾" if row.has_children else " "
    indent = " " * (TREE_INDENT_WIDTH * row.depth)
    orphan = "?" if row.orphaned else " "
    icon, status_color = status_icon(tab.status, now)
    status_text = fit_cells(icon, STATUS_CELL_WIDTH)
    left = indent
    card_prefix_width = (
        display_width(disclosure)
        + display_width(orphan)
        + STATUS_CELL_WIDTH
        + 1
    )
    # Keep the final terminal column untouched. Drawing a cap there sets the
    # terminal's pending-wrap flag, so the following newline can create a blank
    # row and visually split the tree.
    card_width = max(1, width - len(left) - 1)
    show_caps = card_width >= 3
    body_width = card_width - 2 if show_caps else card_width
    remaining = max(1, body_width - card_prefix_width)
    title, repository = tab_labels(tab, remaining)
    label_padding = max(
        0,
        remaining
        - display_width(title)
        - display_width(repository)
        - int(bool(repository)),
    )

    base = ""
    verdict = VERDICT_BACKGROUNDS.get(tab.status or "")
    background = card_background(row)
    if ansi:
        foreground = (
            "20232a"
            if tab.status == "💬"
            else "f8f8f2"
            if verdict or tab.is_active
            else "d8dee9"
        )
        base = _bg(background, True) + _fg(
            foreground, True
        )
        if tab.is_active:
            base += "\x1b[1m"
    reset = "\x1b[0m" if ansi else ""
    restore = reset + base if ansi else ""
    unbold = "\x1b[22m" if ansi else ""
    status = (
        f"{_fg(status_color, ansi) if status_color else ''}{status_text}"
        f"{restore if status_color else ''}"
    )
    repository_label = (
        f"{_fg(repository_label_foreground(tab.repository or '', background, repository_hue), ansi)}"
        f"{unbold}{repository}{restore}"
        if repository
        else ""
    )
    cap_style = f"{_bg('000000', ansi)}{_fg(background, ansi)}"
    verdict_cap = (
        READY_RIGHT_CAP
        if tab.status == "ready_to_merge"
        else FLAME_RIGHT_CAP
        if tab.status == "blocked"
        else None
    )
    effective_style = (
        DEFAULT_EDGE_STYLE
        if card_height == 1 and edge_style in {"rounded", "wedge"}
        else edge_style
    )
    if show_caps and effective_style == "tapered":
        left_cap = f"{cap_style}{LEFT_CAP}{base}"
        right_cap = f"{cap_style}{verdict_cap or RIGHT_CAP}"
    elif show_caps and effective_style == "straight":
        left_cap = f"{base} "
        right_cap = f"{cap_style}{verdict_cap}" if verdict_cap else f"{base} "
    elif show_caps and effective_style == "rounded":
        left_edge = "╭" if card_height == 2 and line_index == 0 else "│"
        right_edge = "╮" if card_height == 2 and line_index == 0 else "│"
        left_cap = f"{cap_style}{left_edge}{base}"
        right_cap = f"{cap_style}{verdict_cap or right_edge}"
    elif show_caps and effective_style == "wedge":
        left_edge = WEDGE_TOP_LEFT if line_index == 0 else " "
        right_edge = WEDGE_TOP_RIGHT if line_index == 0 else " "
        left_cap = (
            f"{cap_style}{left_edge}{base}"
            if line_index == 0
            else f"{base} "
        )
        right_cap = (
            f"{cap_style}{verdict_cap or right_edge}"
            if line_index == 0 or verdict_cap
            else f"{base} "
        )
    else:
        left_cap = base
        right_cap = ""
    return (
        f"{panel_style(ansi)}{left}{left_cap}{disclosure}{orphan}{status}"
        f" {title}{' ' * label_padding}{repository_label}"
        f"{' ' if repository else ''}"
        f"{right_cap}{reset}"
    )


def render_card_blank(
    row: TreeRow,
    *,
    width: int,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    line_index: int = 0,
    card_height: int = 3,
) -> str:
    left = " " * (TREE_INDENT_WIDTH * row.depth)
    card_width = max(1, width - len(left) - 1)
    show_caps = card_width >= 3
    body_width = card_width - 2 if show_caps else card_width
    background = card_background(row)
    base = _bg(background, ansi)
    reset = "\x1b[0m" if ansi else ""
    if not show_caps:
        return f"{panel_style(ansi)}{left}{base}{' ' * body_width}{reset}"
    verdict_cap = (
        READY_RIGHT_CAP
        if row.tab.status == "ready_to_merge"
        else FLAME_RIGHT_CAP
        if row.tab.status == "blocked"
        else None
    )
    cap_style = f"{_bg(PANEL_BACKGROUND, ansi)}{_fg(background, ansi)}"
    if edge_style == "tapered":
        right_edge = (
            f"{cap_style}{verdict_cap}" if verdict_cap else f"{panel_style(ansi)} "
        )
        return (
            f"{panel_style(ansi)}{left} {base}{' ' * body_width}{reset}"
            f"{right_edge}{reset}"
        )
    if edge_style == "straight":
        right_edge = f"{cap_style}{verdict_cap}" if verdict_cap else f"{base} "
        return (
            f"{panel_style(ansi)}{left}{base}{' ' * (body_width + 1)}"
            f"{right_edge}{reset}"
        )
    if edge_style == "rounded":
        bottom = line_index == card_height - 1
        left_edge, right_edge = ("╰", "╯") if bottom else ("╭", "╮")
        return (
            f"{panel_style(ansi)}{left}{cap_style}{left_edge}"
            f"{'─' * body_width}{right_edge}{reset}"
        )
    if edge_style == "wedge":
        bottom = line_index == card_height - 1
        left_edge = WEDGE_BOTTOM_LEFT if bottom else WEDGE_TOP_LEFT
        right_edge = WEDGE_BOTTOM_RIGHT if bottom else WEDGE_TOP_RIGHT
        return (
            f"{panel_style(ansi)}{left}{cap_style}{left_edge}{base}"
            f"{' ' * body_width}{cap_style}{verdict_cap or right_edge}{reset}"
        )
    raise ValueError(f"unknown edge style: {edge_style}")


def render_card(
    row: TreeRow,
    *,
    selected: bool,
    width: int,
    card_height: int,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_hue: float | None = None,
) -> list[str]:
    content_line = card_content_line(card_height)
    return [
        render_row(
            row,
            selected=selected,
            width=width,
            now=now,
            ansi=ansi,
            edge_style=edge_style,
            line_index=line,
            card_height=card_height,
            repository_hue=repository_hue,
        )
        if line == content_line
        else render_card_blank(
            row,
            width=width,
            ansi=ansi,
            edge_style=edge_style,
            line_index=line,
            card_height=card_height,
        )
        for line in range(card_height)
    ]


def render_horizontal_card(
    row: TreeRow,
    *,
    width: int,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_hue: float | None = None,
) -> str:
    if width <= 0:
        return ""
    tab = row.tab
    disclosure = "▸" if row.is_collapsed else "▾" if row.has_children else " "
    orphan = "?" if row.orphaned else " "
    icon, status_color = status_icon(tab.status, now)
    status_text = fit_cells(icon, STATUS_CELL_WIDTH)
    show_caps = width >= 3
    body_width = width - 2 if show_caps else width
    prefix_width = 2 + STATUS_CELL_WIDTH + 1
    title, repository = tab_labels(tab, max(0, body_width - prefix_width))
    repository_suffix = f" · {repository}" if repository else ""
    content_width = min(
        body_width,
        prefix_width + display_width(title) + display_width(repository_suffix),
    )
    left_padding = max(0, (body_width - content_width) // 2)
    right_padding = max(0, body_width - content_width - left_padding)

    background = card_background(row)
    verdict = VERDICT_BACKGROUNDS.get(tab.status or "")
    foreground = (
        "20232a"
        if tab.status == "💬"
        else "f8f8f2"
        if verdict or tab.is_active
        else "d8dee9"
    )
    base = _bg(background, ansi) + _fg(foreground, ansi)
    if ansi and tab.is_active:
        base += "\x1b[1m"
    reset = "\x1b[0m" if ansi else ""
    restore = reset + base if ansi else ""
    unbold = "\x1b[22m" if ansi else ""
    status = (
        f"{_fg(status_color, ansi) if status_color else ''}{status_text}"
        f"{restore if status_color else ''}"
    )
    repository_label = (
        f"{_fg(repository_label_foreground(tab.repository or '', background, repository_hue), ansi)}"
        f"{unbold}{repository_suffix}{restore}"
        if repository_suffix
        else ""
    )
    content = (
        f"{' ' * left_padding}{disclosure}{orphan}{status} {title}"
        f"{repository_label}"
        f"{' ' * right_padding}"
    )
    if not show_caps:
        return f"{base}{fit_cells(content, body_width)}{reset}"

    cap_style = f"{_bg(PANEL_BACKGROUND, ansi)}{_fg(background, ansi)}"
    verdict_cap = (
        READY_RIGHT_CAP
        if tab.status == "ready_to_merge"
        else FLAME_RIGHT_CAP
        if tab.status == "blocked"
        else None
    )
    effective_style = (
        DEFAULT_EDGE_STYLE if edge_style in {"rounded", "wedge"} else edge_style
    )
    if effective_style == "straight":
        left_cap = f"{base} "
        right_cap = f"{cap_style}{verdict_cap}" if verdict_cap else f"{base} "
    else:
        left_cap = f"{cap_style}{LEFT_CAP}{base}"
        right_cap = f"{cap_style}{verdict_cap or RIGHT_CAP}"
    return f"{left_cap}{content}{right_cap}{reset}"


def horizontal_disclosure_column(
    row: TreeRow, placement: HorizontalPlacement
) -> int:
    body_width = placement.width - 2 if placement.width >= 3 else placement.width
    prefix_width = 2 + STATUS_CELL_WIDTH + 1
    title, repository = tab_labels(
        row.tab,
        max(0, body_width - prefix_width),
    )
    repository_suffix = f" · {repository}" if repository else ""
    content_width = min(
        body_width,
        prefix_width + display_width(title) + display_width(repository_suffix),
    )
    left_padding = max(0, (body_width - content_width) // 2)
    cap_width = 1 if placement.width >= 3 else 0
    return placement.left + cap_width + left_padding + 1


def render_horizontal_screen(
    rows: list[TreeRow],
    selected_index: int,
    os_window_id: int,
    width: int,
    height: int,
    *,
    total_tabs: int | None = None,
    error: str | None = None,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_lines: list[str] | None = None,
    repository_location: RepositoryLocation | None = None,
    show_controls: bool = True,
    help_pinned: bool = False,
) -> str:
    del (
        os_window_id,
        total_tabs,
        help_pinned,
        repository_lines,
        repository_location,
    )
    repository_hues = repository_hue_assignments(tuple(
        row.tab.repository for row in rows if row.tab.repository
    ))
    placements = horizontal_layout(rows, width, height, selected_index)
    output = ["" for _ in range(height)]
    by_screen_row: dict[int, list[HorizontalPlacement]] = {}
    for placement in placements:
        by_screen_row.setdefault(placement.screen_row, []).append(placement)
    for screen_row, items in by_screen_row.items():
        if screen_row >= height:
            continue
        cursor = 0
        line = panel_style(ansi)
        for placement in sorted(items, key=lambda item: item.left):
            line += " " * max(0, placement.left - cursor)
            line += render_horizontal_card(
                rows[placement.index],
                width=placement.width,
                now=now,
                ansi=ansi,
                edge_style=edge_style,
                repository_hue=repository_hues.get(
                    rows[placement.index].tab.repository or ""
                ),
            )
            cursor = placement.left + placement.width
        output[screen_row] = line

    tree_height = max(
        (placement.screen_row + 1 for placement in placements), default=0
    )
    free_start = tree_height
    free_end = height
    if show_controls and free_end > free_start:
        text = truncate_cells(HORIZONTAL_CONTROL_TEXT, width)
        padding = " " * max(0, (width - display_width(text)) // 2)
        control_row = free_start + (free_end - free_start - 1) // 2
        output[control_row] = (
            f"{panel_style(ansi)}{_fg(CONTROL_ACTION_FOREGROUND, ansi)}"
            f"{padding}{text}"
        )
    if error:
        blank = next(
            (index for index in range(height - 1, -1, -1) if not output[index]),
            None,
        )
        if blank is not None:
            output[blank] = f" error: {error}"[:width]
    return "\n".join(output)


def render_screen(
    rows: list[TreeRow],
    selected_index: int,
    os_window_id: int,
    width: int,
    height: int,
    *,
    total_tabs: int | None = None,
    error: str | None = None,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_lines: list[str] | None = None,
    repository_location: RepositoryLocation | None = None,
    show_controls: bool = True,
    help_pinned: bool = False,
) -> str:
    repository_hues = repository_hue_assignments(tuple(
        row.tab.repository for row in rows if row.tab.repository
    ))
    available = content_height(height)
    card_height = adaptive_card_height(len(rows), height)
    capacity = card_capacity(available, card_height)
    start = visible_start(len(rows), selected_index, height, card_height)
    visible = rows[start:start + capacity]
    top_padding = vertical_padding(len(rows), height, card_height)
    bottom_padding = vertical_bottom_padding(len(rows), height, card_height)
    context_spacing = REPOSITORY_TOP_GAP + REPOSITORY_BOTTOM_MARGIN
    context_capacity = max(0, bottom_padding - context_spacing)
    context: list[str] = []
    if repository_lines and context_capacity:
        repository_hue = repository_hues.get(
            repository_identity_name(repository_lines) or ""
        )
        details = render_repository_detail_lines(
            repository_lines,
            width,
            ansi=ansi,
        )
        lift_state = (
            bool(details)
            and context_capacity >= 3
            and not repository_card_fits(
                repository_lines,
                width,
                repository_hue=repository_hue,
                repository_location=repository_location,
            )
        )
        visible_details = details[
            :max(0, context_capacity - 1 - int(lift_state))
        ]
        if lift_state:
            context.append(render_repository_heading(
                repository_lines,
                visible_details,
                width,
                ansi=ansi,
            ))
        context.extend(visible_details)
        context.append(
            render_repository_card(
                repository_lines,
                width,
                ansi=ansi,
                edge_style=edge_style,
                repository_hue=repository_hue,
                repository_location=repository_location,
                show_state=not lift_state,
            )
        )
    cards: list[str] = []
    for offset, row in enumerate(visible):
        if offset:
            cards.extend("" for _ in range(card_gap(card_height)))
        cards.extend(
            render_card(
                row,
                selected=(start + offset == selected_index),
                width=width,
                card_height=card_height,
                now=now,
                ansi=ansi,
                edge_style=edge_style,
                repository_hue=repository_hues.get(row.tab.repository or ""),
            )
        )
    output = ["" for _ in range(height)]
    for index, line in enumerate(cards, start=top_padding):
        if index >= height:
            break
        output[index] = line
    if show_controls and top_padding >= len(CONTROL_ROWS):
        controls = list(
            render_control_line(
                shortcut,
                f"edge: {edge_style}"
                if shortcut == "e"
                else "unpin help"
                if shortcut == "?" and help_pinned
                else action,
                width,
                ansi=ansi,
            )
            for shortcut, action in CONTROL_ROWS
        )
        control_start = (top_padding - len(controls)) // 2
        output[control_start:control_start + len(controls)] = controls
    if context:
        context_start = height - REPOSITORY_BOTTOM_MARGIN - len(context)
        output[context_start:context_start + len(context)] = context
    if error:
        blank = next(
            (index for index in range(height - 1, -1, -1) if not output[index]),
            None,
        )
        if blank is not None:
            output[blank] = f" error: {error}"[:width]
    return "\n".join(output)


def content_height(height: int) -> int:
    # Help and repository context live in the free space around the vertically
    # centered cards. They never reserve rows or shift the tab stack.
    return max(0, height)


def visible_start(
    row_count: int,
    selected_index: int,
    height: int,
    card_height: int | None = None,
) -> int:
    available = content_height(height)
    card_height = card_height or adaptive_card_height(row_count, height)
    capacity = card_capacity(available, card_height)
    if capacity and selected_index >= capacity:
        return min(selected_index - capacity + 1, max(0, row_count - capacity))
    return 0


def vertical_padding(
    row_count: int,
    height: int,
    card_height: int | None = None,
) -> int:
    available = content_height(height)
    if row_count == 0:
        return available
    card_height = card_height or adaptive_card_height(row_count, height)
    used = cards_height(row_count, card_height)
    if used >= available:
        return 0
    return (available - used) // 2


def vertical_bottom_padding(
    row_count: int,
    height: int,
    card_height: int | None = None,
) -> int:
    available = content_height(height)
    if row_count == 0:
        return 0
    card_height = card_height or adaptive_card_height(row_count, height)
    used = cards_height(row_count, card_height)
    return max(0, available - used - vertical_padding(
        row_count, height, card_height
    ))
