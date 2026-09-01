import unittest

from ktt import model
from ktt.kitty_tabs import live_tree_records


class LiveWindow:
    def __init__(self, window_id, title, cwd, **user_vars):
        self.id = window_id
        self.title = title
        self.cwd = cwd
        self.user_vars = user_vars

    def get_cwd_of_child(self):
        return self.cwd

    def get_cwd_of_root_child(self):
        return self.cwd


class LiveTab:
    def __init__(
        self,
        tab_id,
        title,
        effective_title,
        windows,
        *,
        active_window=0,
    ):
        self.id = tab_id
        self.title = title
        self.effective_title = effective_title
        self.windows = windows
        self.active_window = windows[active_window]

    def __iter__(self):
        return iter(self.windows)


class LiveManager(list):
    def __init__(self, tabs, *, active_tab=0):
        super().__init__(tabs)
        self.os_window_id = 7
        self.active_tab = tabs[active_tab]


def legacy_snapshot(manager):
    return {
        "id": manager.os_window_id,
        "tabs": [
            {
                "id": tab.id,
                "title": tab.effective_title,
                "is_active": tab is manager.active_tab,
                "windows": [
                    {
                        "id": window.id,
                        "title": window.title,
                        "cwd": window.cwd,
                        "is_active": window is tab.active_window,
                        "user_vars": dict(window.user_vars),
                    }
                    for window in tab
                ],
            }
            for tab in manager
        ],
    }


class AdapterParityTests(unittest.TestCase):
    def test_native_records_match_legacy_identity_and_tree_semantics(self):
        root_content = LiveWindow(100, "⠼ qri-apps", "/work/qri-apps")
        root_sidebar = LiveWindow(
            101, "ktt", "/work/qri-apps", ktt_sidebar="1"
        )
        root = LiveTab(
            10,
            "ktt",
            "Hirayama supervisor",
            [root_content, root_sidebar],
            active_window=1,
        )
        agent = LiveWindow(
            200,
            "review agent",
            "/work/qri-apps__worktrees/review",
            ktt_cockpit_role="agent",
            ktt_parent_window_id="100",
            workmux_status="working",
            workmux_verdict="ready_to_merge",
        )
        stale_shell = LiveWindow(
            201,
            "editor",
            "/work/wrong",
            ktt_parent_window_id="999",
            workmux_status="blocked",
        )
        child = LiveTab(
            20,
            "editor",
            "explicit title ignored for agent-owned tabs",
            [agent, stale_shell],
            active_window=1,
        )
        plain_content = LiveWindow(
            300, "✳ implement auth", "/work/other", workmux_status="waiting"
        )
        plain_sidebar = LiveWindow(
            301, "surf", "/work/other", ktt_sidebar="1"
        )
        sidebar_focused = LiveTab(
            30,
            "surf",
            "surf",
            [plain_content, plain_sidebar],
            active_window=1,
        )
        manager = LiveManager([root, child, sidebar_focused])

        legacy = tuple(model.records_for_os_window(legacy_snapshot(manager)))
        native = live_tree_records(manager)

        for legacy_record, native_record in zip(legacy, native, strict=True):
            self.assertEqual(
                (
                    native_record.id,
                    native_record.os_window_id,
                    native_record.title,
                    native_record.window_ids,
                    native_record.is_active,
                    native_record.parent_window_id,
                    native_record.source_index,
                    native_record.cwd,
                ),
                (
                    legacy_record.id,
                    legacy_record.os_window_id,
                    legacy_record.title,
                    legacy_record.window_ids,
                    legacy_record.is_active,
                    legacy_record.parent_window_id,
                    legacy_record.source_index,
                    legacy_record.cwd,
                ),
            )
        self.assertEqual(native[0].title, "Hirayama supervisor")
        self.assertEqual(native[1].title, "review agent")
        self.assertEqual(native[2].title, "implement auth")

    def test_native_pending_verdict_is_an_intentional_improvement(self):
        window = LiveWindow(
            100,
            "review agent",
            "/work/review",
            workmux_status="working",
            workmux_verdict="ready_to_merge",
        )
        manager = LiveManager([
            LiveTab(10, "review agent", "review agent", [window])
        ])

        legacy = model.records_for_os_window(legacy_snapshot(manager))[0]
        native = live_tree_records(manager)[0]

        self.assertEqual(legacy.status, "working")
        self.assertEqual(native.status, "ready_to_merge")


if __name__ == "__main__":
    unittest.main()
