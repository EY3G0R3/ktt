"""Portable smoke test for an installed or staged Kitty tab_bar.py."""

from __future__ import annotations

from collections import namedtuple
from contextlib import contextmanager
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import runpy
from types import ModuleType, SimpleNamespace
import sys
import tempfile


class Screen:
    def __init__(self) -> None:
        self.cursor = SimpleNamespace(x=0, fg=1, bg=2)

    def draw(self, value: str) -> None:
        self.cursor.x += len(value)


@contextmanager
def mocked_kitty(*, vertical_api: bool = True):
    boss = SimpleNamespace(os_window_map={})
    boss.tab_for_id = lambda _tab_id: None
    modules = {}
    kitty = ModuleType("kitty")
    fast = ModuleType("kitty.fast_data_types")
    fast.LEFT_EDGE, fast.RIGHT_EDGE = 1, 2
    fast.add_timer = lambda *_args: object()
    fast.get_boss = lambda: boss
    fast.get_options = lambda: SimpleNamespace(
        tab_bar_edge=fast.LEFT_EDGE,
        tab_bar_style="custom",
    )
    fast.truncate_point_for_length = lambda text, limit: min(len(text), limit)
    fast.wcswidth = len
    tab_bar = ModuleType("kitty.tab_bar")
    if vertical_api:
        tab_bar.CellRange = namedtuple("CellRange", "start end")
        tab_bar.ExtraData = type("ExtraData", (), {})
        tab_bar.TabBar = type(
            "TabBar", (), {"update_vertical": lambda _self, _data: False}
        )
        tab_bar.TabExtent = namedtuple("TabExtent", "tab_id x y")
    tab_bar.as_rgb = lambda value: value
    tab_bar.draw_attributed_string = (
        lambda value, screen: screen.draw(value)
    )
    tab_bar.draw_title = (
        lambda _data, screen, _tab, _index, _limit: screen.draw("title")
    )
    utils = ModuleType("kitty.utils")
    if vertical_api:
        utils.color_as_int = int
    utils.log_error = lambda _message: None
    utils.sanitize_title = lambda value: " ".join(str(value).split())
    utils.sgr_sanitizer_pat = lambda: re.compile(r"\x1b\[[0-9;]*m")
    window = ModuleType("kitty.window")
    window.path_from_osc7_url = lambda value: value
    for module in (kitty, fast, tab_bar, utils, window):
        modules[module.__name__] = module
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def load_without_ktt(tab_bar_path: Path, home: Path) -> dict:
    old_home = os.environ.get("HOME")
    old_path = list(sys.path)
    removed = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name == "ktt" or name.startswith("ktt.")
    }
    for name in removed:
        sys.modules.pop(name, None)
    os.environ["HOME"] = str(home)
    sys.path[:] = [
        entry for entry in sys.path
        if Path(entry or ".").resolve() != Path(__file__).resolve().parents[1]
    ]
    try:
        with mocked_kitty():
            return runpy.run_path(str(tab_bar_path), run_name="kitty_tab_bar")
    finally:
        sys.path[:] = old_path
        sys.modules.update(removed)
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def verify_with_ktt(tab_bar_path: Path) -> None:
    with mocked_kitty():
        module = runpy.run_path(str(tab_bar_path), run_name="kitty_tab_bar")
    assert module["KTT_RENDERER_HELPERS_AVAILABLE"]
    assert getattr(
        module["TabBar"].update_vertical, "_ktt_vertical_layout", False
    )


def verify_pre_vertical_kitty(tab_bar_path: Path) -> None:
    with mocked_kitty(vertical_api=False):
        module = runpy.run_path(str(tab_bar_path), run_name="kitty_tab_bar")
    assert module["KTT_RENDERER_HELPERS_AVAILABLE"]
    assert module["TabBar"] is None


def verify(module: dict) -> None:
    assert not module["KTT_RENDERER_HELPERS_AVAILABLE"]
    assert "tab_bar_edge bottom" in module["render_config"](
        module["PRESETS"][0]
    )
    assert module["resolve_preset"]("1") == module["PRESETS"][0]
    output = io.StringIO()
    with redirect_stdout(output):
        assert module["main"](["tab_bar.py", "list"]) == 0
    assert "centered-spotlight-slants" in output.getvalue()
    title = module["draw_title"]({
        "title": "safe title",
        "tab": SimpleNamespace(tab_id=1),
        "max_title_length": 20,
    })
    assert title == "safe title"
    screen = Screen()
    result = module["draw_tab"](
        SimpleNamespace(os_window_id=1),
        screen,
        SimpleNamespace(is_active=False),
        0,
        20,
        1,
        True,
        SimpleNamespace(for_layout=False),
    )
    assert result == len("title")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: renderer_fallback_smoke.py /path/to/tab_bar.py")
    source = Path(sys.argv[1]).resolve()
    verify_with_ktt(source)
    verify_pre_vertical_kitty(source)
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        verify(load_without_ktt(source, home))
        package = home / "src" / "ktt" / "ktt"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "tab_bar_geometry.py").write_text(
            'raise RuntimeError("synthetic broken helper")\n'
        )
        verify(load_without_ktt(source, home))


if __name__ == "__main__":
    main()
