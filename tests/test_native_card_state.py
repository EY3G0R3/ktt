import unittest

from ktt import model
from ktt.native_card_state import NativeCardState
from ktt.repository import RepositoryLocation
from ktt.render import READY_RIGHT_CAP, render_screen, strip_ansi


class FakeWindow:
    def __init__(self, window_id, cwd, **user_vars):
        self.id = window_id
        self._cwd = cwd
        self.user_vars = user_vars

    def get_cwd_of_child(self):
        return self._cwd

    def get_cwd_of_root_child(self):
        return self._cwd


class FakeTab:
    def __init__(
        self, tab_id, title, window, *, active=False, effective_title=None
    ):
        self.id = tab_id
        self.title = title
        if effective_title is not None:
            self.effective_title = effective_title
        self.windows = [window]
        self.active_window = window
        self.active = active

    def __iter__(self):
        return iter(self.windows)


class FakeManager(list):
    def __init__(self, tabs, *, os_window_id=7):
        super().__init__(tabs)
        self.os_window_id = os_window_id
        self.active_tab = next(tab for tab in tabs if tab.active)


class FakeIdentities:
    pending = {}

    def __init__(self):
        self.update_calls = 0
        self.locations = {
            "/work/repo__worktrees/feature": RepositoryLocation(
                worktree="feature"
            ),
            "/work/first": RepositoryLocation(),
            "/work/second": RepositoryLocation(),
        }

    def update(self, paths, _now):
        self.update_calls += 1
        return {path: "repo" for path in paths if path}

    def worktrees(self):
        return {"/work/repo__worktrees/feature": "feature"}

    def close(self):
        pass


class FakeSummary:
    def __init__(self, label="topic"):
        self.label = label
        self.paths = []
        self.closed = False

    def update(self, path, _width, _height, _now):
        self.paths.append(path)
        return ["/repo/  ✓ clean", self.label]

    def needs_refresh(self, _now):
        return False

    def close(self):
        self.closed = True


class NativeCardStateTests(unittest.TestCase):
    def test_redraw_token_skips_repeated_metadata_work(self):
        identities = FakeIdentities()
        state = NativeCardState(
            identities=identities, summary_factory=FakeSummary
        )
        manager = FakeManager([
            FakeTab(
                1,
                "working tab",
                FakeWindow(100, "/work/first", workmux_status="working"),
                active=True,
            )
        ])
        frame_token = object()

        first = state.render(
            manager,
            width=40,
            card_height=3,
            now=20.0,
            frame_token=frame_token,
        )
        repeated = state.render(
            manager,
            width=40,
            card_height=3,
            now=40.0,
            frame_token=frame_token,
        )

        self.assertIs(repeated, first)
        self.assertEqual(identities.update_calls, 1)

        state.render(
            manager,
            width=40,
            card_height=3,
            now=40.0,
            frame_token=object(),
        )
        self.assertEqual(identities.update_calls, 2)

    def test_native_cards_reuse_repository_status_and_verdict_rendering(self):
        root_window = FakeWindow(
            100,
            "/work/repo__worktrees/feature",
            workmux_status="working",
            workmux_verdict="ready_to_merge",
        )
        child_window = FakeWindow(
            200,
            "/work/repo__worktrees/feature",
            ktt_parent_window_id="100",
            workmux_status="waiting",
        )
        manager = FakeManager([
            FakeTab(1, "implement auth", root_window, active=True),
            FakeTab(2, "review", child_window),
        ])
        state = NativeCardState(
            identities=FakeIdentities(), summary_factory=FakeSummary
        )

        cards = state.render(manager, width=40, card_height=3, now=20.0)
        root = [strip_ansi(line) for line in cards[1]]
        child = [strip_ansi(line) for line in cards[2]]

        self.assertIn("/repo/", root[1])
        self.assertIn("🌳feature", root[1])
        self.assertIn("✓ clean", root[1])
        self.assertIn("topic · implement auth", root[2])
        self.assertTrue(any(READY_RIGHT_CAP in line for line in root))
        self.assertIn("💬", child[1])
        self.assertTrue(child[1].startswith("    "))

    def test_native_cards_match_legacy_visual_output(self):
        path = "/work/repo__worktrees/feature"
        root_window = FakeWindow(
            100,
            path,
            workmux_status="working",
            workmux_verdict="ready_to_merge",
        )
        child_window = FakeWindow(
            200,
            path,
            ktt_parent_window_id="100",
            workmux_status="waiting",
        )
        manager = FakeManager([
            FakeTab(
                1,
                "⠼ repo",
                root_window,
                active=True,
                effective_title="Hirayama supervisor",
            ),
            FakeTab(2, "review", child_window),
        ])
        state = NativeCardState(
            identities=FakeIdentities(), summary_factory=FakeSummary
        )

        native = state.render(manager, width=40, card_height=3, now=20.0)
        rows = model.tree_rows([
            model.TabRecord(
                1,
                7,
                "Hirayama supervisor",
                (100,),
                is_active=True,
                status="ready_to_merge",
                cwd=path,
                repository="repo",
                repository_worktree="feature",
            ),
            model.TabRecord(
                2,
                7,
                "review",
                (200,),
                parent_window_id=100,
                status="💬",
                source_index=1,
                cwd=path,
                repository="repo",
                repository_worktree="feature",
            ),
        ])
        legacy_lines = render_screen(
            rows,
            selected_index=0,
            os_window_id=7,
            width=40,
            height=7,
            now=20.0,
            repository_lines=["/repo/  ✓ clean", "topic"],
            repository_location=RepositoryLocation(worktree="feature"),
        ).splitlines()

        self.assertEqual(native[1], tuple(legacy_lines[:3]))
        self.assertEqual(native[2], tuple(legacy_lines[4:7]))

    def test_repository_summaries_are_isolated_per_os_window(self):
        summaries = iter((FakeSummary("first"), FakeSummary("second")))
        state = NativeCardState(
            identities=FakeIdentities(), summary_factory=lambda: next(summaries)
        )
        first = FakeManager([
            FakeTab(
                1,
                "first tab",
                FakeWindow(100, "/work/first"),
                active=True,
            )
        ], os_window_id=7)
        second = FakeManager([
            FakeTab(
                2,
                "second tab",
                FakeWindow(200, "/work/second"),
                active=True,
            )
        ], os_window_id=8)

        state.render(first, width=40, card_height=3, now=20.0)
        state.render(second, width=40, card_height=3, now=20.0)

        self.assertEqual(set(state.summaries), {7, 8})
        self.assertIsNot(state.summaries[7], state.summaries[8])
        self.assertEqual(state.summaries[7].paths, ["/work/first"])
        self.assertEqual(state.summaries[8].paths, ["/work/second"])


if __name__ == "__main__":
    unittest.main()
