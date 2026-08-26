import unittest
import re

from ktt.model import TabRecord, TreeRow
from ktt.repository import RepositoryLocation
from ktt.render import (
    CONTROL_ACTION_FOREGROUND,
    CONTROL_LINES,
    CONTROL_SHORTCUT_FOREGROUND,
    EDGE_STYLES,
    FLAME_RIGHT_CAP,
    LEFT_CAP,
    READY_RIGHT_CAP,
    REPOSITORY_BACKGROUND,
    RIGHT_CAP,
    WAITING_BACKGROUNDS,
    WEDGE_BOTTOM_LEFT,
    WEDGE_BOTTOM_RIGHT,
    WEDGE_TOP_LEFT,
    WEDGE_TOP_RIGHT,
    adaptive_card_height,
    card_background,
    card_content_line,
    display_width,
    horizontal_index_at_mouse,
    horizontal_layout,
    horizontal_disclosure_column,
    panel_style,
    next_edge_style,
    render_control_line,
    render_card,
    render_horizontal_card,
    render_horizontal_screen,
    render_repository_card,
    render_repository_detail_lines,
    repository_dirty_heading,
    render_row,
    render_screen,
    repository_hue_assignments,
    repository_label_foreground,
    worktree_matches_branch,
    status_icon,
    strip_ansi,
    truncate_ansi_cells,
    vertical_padding,
    vertical_bottom_padding,
)


class RenderTests(unittest.TestCase):
    def test_horizontal_tree_grows_down_in_fixed_width_root_columns(self) -> None:
        rows = [
            TreeRow(
                TabRecord(1, 1, "root", (10,)), 0, None,
                has_children=True,
            ),
            TreeRow(TabRecord(2, 1, "left", (20,)), 1, 1),
            TreeRow(TabRecord(3, 1, "right", (30,)), 1, 1),
            TreeRow(TabRecord(4, 1, "other", (40,)), 0, None),
        ]
        placements = horizontal_layout(rows, 91, 8, 0)
        by_index = {placement.index: placement for placement in placements}
        self.assertEqual(by_index[0].screen_row, 0)
        self.assertEqual(by_index[1].screen_row, 1)
        self.assertEqual(by_index[2].screen_row, 2)
        self.assertEqual(by_index[3].screen_row, 0)
        self.assertEqual(by_index[0].width, by_index[1].width)
        self.assertEqual(by_index[1].width, by_index[2].width)
        self.assertEqual(by_index[2].width, by_index[3].width)
        self.assertEqual(by_index[0].width, 40)
        self.assertEqual(by_index[1].left - by_index[0].left, 4)
        self.assertEqual(by_index[1].left, by_index[2].left)
        self.assertLess(by_index[0].left, by_index[3].left)

    def test_horizontal_tree_places_indented_children_on_the_next_row(self) -> None:
        rows = [
            TreeRow(
                TabRecord(1, 1, "root", (10,)), 0, None,
                has_children=True,
            ),
            TreeRow(TabRecord(2, 1, "left", (20,)), 1, 1),
            TreeRow(TabRecord(3, 1, "right", (30,)), 1, 1),
        ]
        screen = render_horizontal_screen(
            rows, 0, 1, 80, 5, ansi=False, show_controls=False
        )
        lines = screen.split("\n")
        self.assertIn("root", lines[0])
        self.assertIn("left", lines[1])
        self.assertIn("right", lines[2])
        self.assertTrue(lines[1].startswith(" " * 4))
        self.assertTrue(lines[2].startswith(" " * 4))
        self.assertFalse(
            any(character in lines[1] + lines[2] for character in "┬┴┼")
        )

    def test_horizontal_nested_descendants_keep_width_and_add_indent(self) -> None:
        rows = [
            TreeRow(TabRecord(1, 1, "root", (10,)), 0, None, has_children=True),
            TreeRow(TabRecord(2, 1, "child", (20,)), 1, 1, has_children=True),
            TreeRow(TabRecord(3, 1, "grandchild", (30,)), 2, 2),
        ]
        placements = horizontal_layout(rows, 80, 5, 0)
        self.assertEqual([item.screen_row for item in placements], [0, 1, 2])
        self.assertEqual(len({item.width for item in placements}), 1)
        self.assertEqual([item.left for item in placements], [15, 19, 23])

    def test_horizontal_root_group_is_narrow_and_centered(self) -> None:
        rows = [
            TreeRow(TabRecord(index, 1, f"tab-{index}", (index,)), 0, None)
            for index in range(1, 4)
        ]
        placements = horizontal_layout(rows, 200, 4, 0)
        self.assertEqual([item.width for item in placements], [40, 40, 40])
        self.assertEqual([item.left for item in placements], [38, 79, 120])

    def test_horizontal_layout_compacts_to_active_centered_strip(self) -> None:
        rows = [
            TreeRow(TabRecord(index, 1, f"tab-{index}", (index,)), 0, None)
            for index in range(1, 9)
        ]
        placements = horizontal_layout(rows, 60, 4, 5)
        self.assertTrue(all(item.screen_row == 0 for item in placements))
        self.assertIn(5, [item.index for item in placements])
        self.assertLess(len(placements), len(rows))

    def test_horizontal_mouse_hit_testing_uses_card_rectangles(self) -> None:
        rows = [
            TreeRow(TabRecord(1, 1, "one", (10,)), 0, None),
            TreeRow(TabRecord(2, 1, "two", (20,)), 0, None),
        ]
        placements = horizontal_layout(rows, 80, 4, 0)
        second = next(item for item in placements if item.index == 1)
        self.assertEqual(
            horizontal_index_at_mouse(second.left + 1, 1, placements), 1
        )
        self.assertIsNone(
            horizontal_index_at_mouse(second.left, 2, placements)
        )

    def test_horizontal_disclosure_column_tracks_centered_content(self) -> None:
        row = TreeRow(
            TabRecord(1, 1, "parent", (10,)), 0, None, has_children=True
        )
        placement = horizontal_layout([row], 40, 3, 0)[0]
        column = horizontal_disclosure_column(row, placement)
        rendered = render_horizontal_card(row, width=placement.width, ansi=False)
        self.assertEqual(rendered[column - placement.left - 1], "▾")

    def test_horizontal_card_centers_title_and_keeps_fixed_status_space(self) -> None:
        plain = render_horizontal_card(
            TreeRow(TabRecord(1, 1, "centered", (10,)), 0, None),
            width=30,
            ansi=False,
        )
        working = render_horizontal_card(
            TreeRow(TabRecord(1, 1, "centered", (10,), status="🤖"), 0, None),
            width=30,
            ansi=False,
            now=0.0,
        )
        self.assertEqual(display_width(plain), 30)
        self.assertEqual(plain.index("centered"), working.index("centered"))
        self.assertGreater(plain.index("centered"), 5)

    def test_horizontal_card_includes_repository_badge(self) -> None:
        rendered = render_horizontal_card(
            TreeRow(
                TabRecord(1, 1, "runner", (10,), repository="quiver"),
                0,
                None,
            ),
            width=36,
            ansi=False,
        )
        self.assertIn("runner · /quiver/", rendered)

    def test_horizontal_screen_does_not_render_repository_status(self) -> None:
        rows = [TreeRow(TabRecord(1, 1, "root", (10,)), 0, None)]
        screen = render_horizontal_screen(
            rows, 0, 1, 80, 5, ansi=False, show_controls=False,
            repository_lines=["fancylog status", " main"],
        )
        self.assertNotIn("fancylog status", screen)
        self.assertNotIn(" main", screen)

    def test_branch_uses_the_top_and_status_uses_the_bottom_row(self) -> None:
        rows = [TreeRow(
            TabRecord(1, 1, "one", (10,), repository="ktt"), 0, None
        )]
        screen = render_screen(
            rows,
            0,
            1,
            48,
            18,
            ansi=False,
            repository_lines=[" (ktt) ~/src/ktt  ✓ clean ", "  main "],
        )
        lines = screen.split("\n")
        tab_index = next(index for index, line in enumerate(lines) if "one" in line)
        status_index = next(
            index for index, line in enumerate(lines)
            if "✓ clean" in line
        )
        self.assertEqual(status_index, tab_index + 1)
        self.assertIn(" main", lines[tab_index - 1])
        self.assertIn("/ktt/", lines[tab_index])

    def test_repository_status_is_clipped_to_available_padding(self) -> None:
        rows = [TreeRow(
            TabRecord(1, 1, "one", (10,), repository="ktt"), 0, None
        )]
        screen = render_screen(
            rows,
            0,
            1,
            40,
            8,
            ansi=False,
            repository_lines=[" (ktt) ~/src/ktt  ✓ clean ", "  main "],
        )
        lines = screen.split("\n")
        tab_index = next(index for index, line in enumerate(lines) if "one" in line)
        status_index = next(
            index for index, line in enumerate(lines)
            if "✓ clean" in line
        )
        self.assertEqual(status_index, tab_index + 1)

    def test_embedded_repository_context_keeps_lower_tabs_in_the_group(self) -> None:
        rows = [
            TreeRow(TabRecord(1, 1, "one", (10,), repository="ktt"), 0, None),
            TreeRow(TabRecord(2, 1, "two", (20,), repository="ktt"), 0, None),
        ]
        screen = render_screen(
            rows,
            0,
            1,
            60,
            14,
            ansi=False,
            show_controls=False,
            repository_lines=[" (ktt) ~/src/ktt  ✓ clean ", "  main "],
        )
        lines = screen.split("\n")
        first = next(index for index, line in enumerate(lines) if "one" in line)
        identity = next(index for index, line in enumerate(lines) if " main" in line)
        state = next(index for index, line in enumerate(lines) if "✓ clean" in line)
        second = next(index for index, line in enumerate(lines) if "two" in line)

        self.assertEqual(identity, first - 1)
        self.assertEqual(state, first + 1)
        self.assertEqual(second, state + 3)
        self.assertIn("/ktt/", lines[second])

    def test_repository_card_compacts_fancylog_into_one_colored_pill(self) -> None:
        rendered = render_repository_card(
            [
                " (ktt) ~/src/ktt                      ✓ working tree clean ",
                "                          main                         ",
            ],
            68,
            ansi=False,
        )
        self.assertEqual(rendered.strip(), " /ktt/  ~/src/ktt  ·   main  ·  ✓ clean ")

    def test_repository_card_matches_the_tab_repository_label_color(self) -> None:
        rows = [TreeRow(
            TabRecord(1, 1, "one", (10,), repository="ktt"), 0, None
        )]
        screen = render_screen(
            rows,
            0,
            1,
            60,
            12,
            ansi=True,
            show_controls=False,
            repository_lines=[
                " (ktt) ~/src/ktt  ✓ working tree clean ",
                "  main ",
            ],
        )
        hue = repository_hue_assignments(("ktt",))["ktt"]
        color = repository_label_foreground(
            "ktt", REPOSITORY_BACKGROUND, hue
        )
        red, green, blue = (
            int(color[offset:offset + 2], 16) for offset in (0, 2, 4)
        )

        repository_lines = [
            line for line in screen.split("\n") if "/ktt/" in strip_ansi(line)
        ]
        self.assertEqual(len(repository_lines), 1)
        self.assertIn(
            f"\x1b[38;2;{red};{green};{blue}m\x1b[22m/ktt/",
            repository_lines[0],
        )

    def test_repository_card_compacts_main_checkout_paths(self) -> None:
        rendered = render_repository_card(
            [
                " (ktt) ~/src/ktt/build  ✓ working tree clean ",
                "  main ",
            ],
            68,
            ansi=False,
            repository_location=RepositoryLocation(relative_path="build/"),
        )

        self.assertEqual(
            rendered.strip(),
            " /ktt/  build/  ·   main  ·  ✓ clean ",
        )

    def test_repository_card_places_worktree_before_path_and_branch(self) -> None:
        rendered = render_repository_card(
            [
                " (quiver) ~/work/quiver__worktrees/feature/build  ✓ clean ",
                "  topic/branch ",
            ],
            88,
            ansi=False,
            repository_location=RepositoryLocation(
                worktree="feature", relative_path="build/"
            ),
        )

        self.assertEqual(
            rendered.strip(),
            " /quiver/  🌲feature  build/  ·   topic/branch  ·  ✓ clean ",
        )

    def test_dirty_counts_move_above_files_when_the_card_fits(self) -> None:
        repository_lines = [
            " modified one.py ",
            " untracked two.py ",
            " untracked three.py ",
            " (slock) ~/src/slock  ◈ 1 unstaged  ·  2 untracked ",
            "  master ",
        ]
        screen = render_screen(
            [TreeRow(TabRecord(1, 1, "one", (10,), repository="slock"), 0, None)],
            0,
            1,
            72,
            18,
            ansi=False,
            show_controls=False,
            repository_lines=repository_lines,
            repository_location=RepositoryLocation(),
        )

        lines = screen.split("\n")
        state_index = next(
            index for index, line in enumerate(lines)
            if "1 unstaged  ·  2 untracked" in line
        )
        first_file_index = next(
            index for index, line in enumerate(lines) if "modified one.py" in line
        )

        self.assertEqual(first_file_index, state_index + 1)
        self.assertIn(" master", lines[state_index - 2])
        self.assertEqual(sum("/slock/" in line for line in lines), 1)

    def test_dirty_counts_lift_above_files_when_the_card_is_too_narrow(self) -> None:
        repository_lines = [
            " modified one.py ",
            " untracked two.py ",
            " untracked three.py ",
            (
                " (quiver) /long/worktree/path  "
                "◈ 1 unstaged  ·  2 untracked "
            ),
            "  long/topic/branch ",
        ]
        screen = render_screen(
            [TreeRow(TabRecord(1, 1, "one", (10,), repository="quiver"), 0, None)],
            0,
            1,
            46,
            20,
            ansi=False,
            show_controls=False,
            repository_lines=repository_lines,
            repository_location=RepositoryLocation(
                worktree="feature", relative_path="deep/build/"
            ),
        )
        lines = screen.split("\n")
        state_index = next(
            index for index, line in enumerate(lines)
            if "1 unstaged  ·  2 untracked" in line
        )
        first_file_index = next(
            index for index, line in enumerate(lines) if "modified one.py" in line
        )

        self.assertEqual(first_file_index, state_index + 1)
        self.assertIn(" long/", lines[state_index - 2])

    def test_worktree_moves_into_selected_tab_and_out_of_summary(self) -> None:
        screen = render_screen(
            [TreeRow(
                TabRecord(1, 1, "runner", (10,), repository="quiver"),
                0,
                None,
            )],
            0,
            1,
            72,
            12,
            ansi=False,
            show_controls=False,
            repository_lines=[
                " (quiver) /worktree/build  ✓ clean ",
                "  topic/branch ",
            ],
            repository_location=RepositoryLocation(
                worktree="feature", relative_path="build/"
            ),
        )
        lines = screen.split("\n")
        tab_line = next(line for line in lines if "runner" in line)
        identity = next(line for line in lines if "🌲feature" in line)
        summary = next(line for line in lines if "✓ clean" in line)

        self.assertIn("🌲feature  ·   topic/branch", identity)
        self.assertIn("/quiver/", tab_line)
        self.assertNotIn("/quiver/", summary)
        self.assertNotIn("🌲feature", summary)
        self.assertNotIn(" topic/branch", summary)

    def test_top_row_omits_branch_when_it_matches_worktree(self) -> None:
        screen = render_screen(
            [TreeRow(
                TabRecord(1, 1, "runner", (10,), repository="quiver"),
                0,
                None,
            )],
            0,
            1,
            72,
            12,
            ansi=False,
            show_controls=False,
            repository_lines=[
                " (quiver) /worktree  ✓ clean ",
                "  topic/branch ",
            ],
            repository_location=RepositoryLocation(worktree="topic-branch"),
        )
        top = next(line for line in screen.split("\n") if "🌲" in line)

        self.assertIn("🌲topic-branch", top)
        self.assertNotIn(" topic/branch", top)

    def test_compact_tab_centers_top_identity_and_bottom_status(self) -> None:
        screen = render_screen(
            [TreeRow(
                TabRecord(1, 1, "runner", (10,), repository="quiver"),
                0,
                None,
            )],
            0,
            1,
            32,
            8,
            ansi=False,
            show_controls=False,
            repository_lines=[
                " (quiver) /worktree  ✓ clean ",
                "  topic/branch ",
            ],
            repository_location=RepositoryLocation(worktree="feature"),
        )
        lines = screen.split("\n")
        tab_line = next(line for line in lines if "runner" in line)
        identity = next(line for line in lines if "" in line)
        summary = next(line for line in lines if "✓ clean" in line)

        self.assertIn("/quiver/", tab_line)
        self.assertNotIn("/quiver/", summary)
        self.assertIn("", identity)
        self.assertNotIn("", summary)
        self.assertLessEqual(
            abs(summary.index("✓ clean") * 2 + len("✓ clean") - 31), 1
        )

    def test_equivalent_worktree_and_branch_are_not_repeated(self) -> None:
        rendered = render_repository_card(
            [
                " (convex-backend) /worktree  ✓ clean ",
                "  perf/optimize-concurrency ",
            ],
            80,
            ansi=False,
            repository_location=RepositoryLocation(
                worktree="perf-optimize-concurrency"
            ),
        )

        self.assertIn(
            "/convex-backend/  🌲perf-optimize-concurrency",
            rendered,
        )
        self.assertNotIn("", rendered)
        self.assertTrue(worktree_matches_branch(
            "perf-optimize-concurrency", " perf/optimize-concurrency"
        ))

    def test_dirty_heading_removes_icon_and_adds_colon(self) -> None:
        self.assertEqual(
            repository_dirty_heading([
                " (slock) ~/src/slock  ◈ 1 unstaged  ·  2 untracked ",
                "  master ",
            ]),
            "1 unstaged  ·  2 untracked:",
        )
        self.assertIsNone(repository_dirty_heading([
            " (slock) ~/src/slock  ✓ working tree clean ",
            "  master ",
        ]))

    def test_repository_card_uses_tapered_caps_for_single_row_edge_styles(self) -> None:
        source = [" (ktt) ~/src/ktt  ✓ clean ", "  main "]
        for edge_style in ("tapered", "rounded", "wedge"):
            with self.subTest(edge_style=edge_style):
                rendered = render_repository_card(
                    source, 48, ansi=False, edge_style=edge_style
                )
                self.assertIn(LEFT_CAP, rendered)
                self.assertTrue(rendered.endswith(RIGHT_CAP))

    def test_repository_file_block_is_centered_with_aligned_paths_and_colors(self) -> None:
        modified = (
            "\x1b[49m                    \x1b[38;5;3mmodified "
            "\x1b[38;5;8mktt/render.py             \x1b[0m"
        )
        untracked = (
            "\x1b[49m                   \x1b[38;5;6muntracked "
            "\x1b[38;5;8mnew.py                    \x1b[0m"
        )
        screen = render_screen(
            [TreeRow(TabRecord(1, 1, "one", (10,)), 0, None)],
            0,
            1,
            60,
            20,
            ansi=True,
            repository_lines=[
                modified,
                untracked,
                " (ktt) ~/src/ktt  ◈ 2 unstaged ",
                "  main ",
            ],
        )
        rendered_modified = next(
            line for line in screen.split("\n") if "ktt/render.py" in line
        )
        rendered_untracked = next(
            line for line in screen.split("\n") if "new.py" in line
        )
        modified_plain = strip_ansi(rendered_modified)
        untracked_plain = strip_ansi(rendered_untracked)
        self.assertEqual(
            modified_plain.index("ktt/render.py"),
            untracked_plain.index("new.py"),
        )
        block_left = min(
            len(modified_plain) - len(modified_plain.lstrip()),
            len(untracked_plain) - len(untracked_plain.lstrip()),
        )
        block_right = max(len(modified_plain), len(untracked_plain))
        self.assertLessEqual(abs((block_left + block_right) - 59), 1)
        self.assertIn("\x1b[38;5;3mmodified", rendered_modified)
        self.assertIn("\x1b[38;5;6muntracked", rendered_untracked)

    def test_repository_file_rows_keep_alignment_without_ansi(self) -> None:
        detail = "\x1b[49m                    \x1b[38;5;6muntracked new.py\x1b[0m"
        screen = render_screen(
            [TreeRow(TabRecord(1, 1, "one", (10,)), 0, None)],
            0,
            1,
            60,
            20,
            ansi=False,
            repository_lines=[detail, " (ktt) ~/src/ktt  ◈ 1 untracked ", "  main "],
        )
        self.assertIn(
            "                     untracked new.py", screen.split("\n")
        )

    def test_repository_file_rows_preserve_long_paths_that_fit(self) -> None:
        path = "application/src/application_function_runner/mod.rs"
        detail = f"modified {path}"

        rendered = render_repository_detail_lines(
            [detail, " (repo) /repo  ◈ 1 unstaged ", "  main "],
            80,
            ansi=False,
        )

        self.assertIn(path, rendered[0])

    def test_repository_file_rows_only_truncate_at_the_physical_width(self) -> None:
        path = (
            "crates/application/src/application_function_runner/"
            "mutation_admission.rs"
        )
        rendered = render_repository_detail_lines(
            [
                f"modified {path}",
                " (convex-backend) /repo  ◈ 1 unstaged ",
                "  main ",
            ],
            48,
            ansi=False,
        )[0]

        self.assertIn("modified crates/application/", rendered)
        self.assertNotIn("mutation_admission.rs", rendered)
        self.assertTrue(rendered.endswith("…"))
        self.assertLessEqual(display_width(strip_ansi(rendered)), 47)

    def test_ansi_cell_truncation_keeps_full_text_when_it_fits(self) -> None:
        colored = "\x1b[38;5;3mmodified \x1b[38;5;8mfull/path.rs\x1b[0m"

        self.assertEqual(truncate_ansi_cells(colored, 40), colored)

    def test_panel_uses_explicit_black_background(self) -> None:
        self.assertEqual(panel_style(), "\x1b[48;2;0;0;0m\x1b[38;2;248;248;242m")

    def test_statuses_match_existing_workmux_conventions(self) -> None:
        self.assertEqual(status_icon("ready_to_merge"), ("✓", "50fa7b"))
        self.assertEqual(status_icon("blocked"), ("✗", "ff5555"))
        self.assertEqual(status_icon("🤖", now=0.0)[0], "⠋")

    def test_child_row_is_indented(self) -> None:
        tab = TabRecord(2, 1, "child", (20,), status="blocked")
        rendered = render_row(
            TreeRow(tab, depth=2, parent_tab_id=1),
            selected=False,
            width=80,
            ansi=False,
            now=0.0,
        )
        self.assertIn(f"        {LEFT_CAP}", rendered)
        self.assertIn("✗", rendered)
        self.assertIn("child", rendered)

    def test_repository_badge_is_enclosed_and_inset_from_card_edge(self) -> None:
        rendered = render_row(
            TreeRow(
                TabRecord(1, 1, "cloud runner", (10,), repository="quiver"),
                0,
                None,
            ),
            selected=False,
            width=60,
            ansi=False,
        )
        self.assertIn("cloud runner", rendered)
        self.assertGreater(rendered.index("/quiver/"), rendered.index("cloud runner"))
        self.assertTrue(rendered.endswith(f"/quiver/ {RIGHT_CAP}"))

        colored = render_row(
            TreeRow(
                TabRecord(1, 1, "cloud runner", (10,), repository="quiver"),
                0,
                None,
            ),
            selected=False,
            width=60,
        )
        repository_color = repository_label_foreground("quiver", "20232a")
        repository_rgb = tuple(
            int(repository_color[offset:offset + 2], 16)
            for offset in (0, 2, 4)
        )
        self.assertIn(
            f"\x1b[38;2;{';'.join(map(str, repository_rgb))}m"
            "\x1b[22m/quiver/",
            colored,
        )

    def test_repository_colors_are_stable_distinct_and_contrast_aware(self) -> None:
        quiver = repository_label_foreground("quiver", "20232a")
        self.assertEqual(quiver, repository_label_foreground("quiver", "20232a"))
        self.assertNotEqual(quiver, repository_label_foreground("ktt", "20232a"))
        self.assertNotEqual(
            repository_label_foreground("quiver", "20232a"),
            repository_label_foreground("quiver", "f8f8f2"),
        )

    def test_quiver_and_squawk_repository_colors_are_visibly_separated(self) -> None:
        colors = [
            repository_label_foreground(repository, "20232a")
            for repository in ("quiver", "squawk")
        ]
        rgb = [
            tuple(int(color[offset:offset + 2], 16) for offset in (0, 2, 4))
            for color in colors
        ]
        self.assertGreater(
            sum(abs(first - second) for first, second in zip(*rgb)),
            100,
        )

    def test_visible_repository_colors_resolve_near_collisions(self) -> None:
        names = ("quiver", "squawk", "tower")
        hues = repository_hue_assignments(names)
        self.assertEqual(hues, repository_hue_assignments(tuple(reversed(names))))
        distances = [
            min(abs(first - second), 1 - abs(first - second))
            for index, first in enumerate(hues.values())
            for second in list(hues.values())[index + 1:]
        ]
        self.assertGreaterEqual(min(distances), 45 / 360)

        rows = [
            TreeRow(TabRecord(index, 1, name, (index,), repository=name), 0, None)
            for index, name in enumerate(names, start=1)
        ]
        rendered = render_screen(
            rows, 0, 1, 60, 3, ansi=True, show_controls=False
        )
        for name in names:
            color = repository_label_foreground(name, "20232a", hues[name])
            rgb = tuple(
                int(color[offset:offset + 2], 16) for offset in (0, 2, 4)
            )
            self.assertIn(
                f"\x1b[38;2;{';'.join(map(str, rgb))}m\x1b[22m/{name}/",
                rendered,
            )

    def test_ready_and_blocked_rows_have_verdict_backgrounds(self) -> None:
        ready = TabRecord(2, 1, "ready", (20,), status="ready_to_merge")
        blocked = TabRecord(3, 1, "blocked", (30,), status="blocked")
        self.assertIn("\x1b[48;2;27;94;54m", render_row(
            TreeRow(ready, 0, None), selected=False, width=80
        ))
        self.assertIn("\x1b[48;2;122;32;41m", render_row(
            TreeRow(blocked, 0, None), selected=False, width=80
        ))

    def test_waiting_row_uses_a_white_attention_card_with_dark_text(self) -> None:
        waiting = TreeRow(
            TabRecord(2, 1, "question", (20,), status="💬"), 0, None
        )
        rendered = render_row(waiting, selected=False, width=40)
        background = tuple(
            int(WAITING_BACKGROUNDS[0][offset:offset + 2], 16)
            for offset in (0, 2, 4)
        )
        self.assertIn(
            f"\x1b[48;2;{';'.join(map(str, background))}m", rendered
        )
        self.assertIn("\x1b[38;2;32;35;42m", rendered)
        self.assertIn(RIGHT_CAP, rendered)

    def test_active_waiting_row_is_brighter_than_inactive_waiting(self) -> None:
        inactive = card_background(TreeRow(
            TabRecord(1, 1, "question", (10,), status="💬"), 0, None
        ))
        active = card_background(TreeRow(
            TabRecord(1, 1, "question", (10,), status="💬", is_active=True),
            0,
            None,
        ))
        self.assertEqual((inactive, active), WAITING_BACKGROUNDS)

    def test_help_is_centered_in_the_free_space_above_tabs(self) -> None:
        rows = [
            TreeRow(TabRecord(1, 1, "one", (10,)), 0, None),
            TreeRow(TabRecord(2, 1, "two", (20,)), 0, None),
        ]
        screen = render_screen(rows, 0, 1, 80, 32, ansi=False)
        lines = screen.splitlines()
        top_padding = vertical_padding(2, 32)
        control_start = (top_padding - len(CONTROL_LINES)) // 2
        self.assertEqual(adaptive_card_height(2, 32), 3)
        self.assertIn("one", lines[top_padding + 1])
        self.assertEqual(lines[top_padding + 3], "")
        self.assertIn("two", lines[top_padding + 5])
        controls = lines[control_start:control_start + len(CONTROL_LINES)]
        self.assertEqual(
            [line.strip() for line in controls],
            [line.strip() for line in CONTROL_LINES],
        )
        expected_padding = (80 - display_width(CONTROL_LINES[0])) // 2
        self.assertTrue(all(
            line.startswith(" " * expected_padding) for line in controls
        ))

    def test_cards_squeeze_from_three_lines_to_two_then_one(self) -> None:
        self.assertEqual(adaptive_card_height(4, 23), 3)
        self.assertEqual(adaptive_card_height(4, 14), 2)
        self.assertEqual(adaptive_card_height(4, 10), 1)

    def test_edge_style_cycle_wraps_in_display_order(self) -> None:
        observed = []
        current = EDGE_STYLES[0]
        for _ in EDGE_STYLES:
            observed.append(current)
            current = next_edge_style(current)
        self.assertEqual(tuple(observed), EDGE_STYLES)
        self.assertEqual(current, EDGE_STYLES[0])

    def test_all_edge_styles_render_real_three_line_cards(self) -> None:
        row = TreeRow(TabRecord(1, 1, "tab", (10,)), 0, None)
        cards = {
            style: render_card(
                row,
                selected=False,
                width=30,
                card_height=3,
                ansi=False,
                edge_style=style,
            )
            for style in EDGE_STYLES
        }
        self.assertTrue(cards["tapered"][0].startswith(" "))
        self.assertFalse(any(LEFT_CAP in line for line in cards["straight"]))
        self.assertIn("╭", cards["rounded"][0])
        self.assertIn("│", cards["rounded"][1])
        self.assertIn("╰", cards["rounded"][2])
        self.assertIn(WEDGE_TOP_LEFT, cards["wedge"][0])
        self.assertIn(WEDGE_TOP_RIGHT, cards["wedge"][0])
        self.assertIn(WEDGE_BOTTOM_LEFT, cards["wedge"][2])
        self.assertIn(WEDGE_BOTTOM_RIGHT, cards["wedge"][2])
        self.assertTrue(all(
            all(display_width(line) == 29 for line in card)
            for card in cards.values()
        ))

    def test_all_edge_styles_fill_spare_rows_with_selected_repository_context(self) -> None:
        row = TreeRow(
            TabRecord(1, 1, "runner", (10,), repository="quiver"), 0, None
        )
        source = [" (quiver) /worktree  ✓ clean ", "  main "]
        for edge_style in EDGE_STYLES:
            with self.subTest(edge_style=edge_style):
                card = render_card(
                    row,
                    selected=True,
                    width=48,
                    card_height=3,
                    ansi=False,
                    edge_style=edge_style,
                    repository_lines=source,
                    repository_location=RepositoryLocation(worktree="feature"),
                )

                self.assertIn("🌲feature  ·   main", card[0])
                self.assertIn("runner", card[1])
                self.assertIn("/quiver/", card[1])
                self.assertIn("✓ clean", card[2])
                self.assertNotIn(" main", card[2])
                self.assertLessEqual(
                    abs(card[2].index("✓ clean") * 2 + len("✓ clean") - 47),
                    1,
                )
                self.assertTrue(all(display_width(line) == 47 for line in card))

    def test_three_line_card_centers_content_inside_background(self) -> None:
        row = TreeRow(
            TabRecord(1, 1, "blocked-child", (10,), status="blocked"),
            1,
            2,
        )
        card = render_card(
            row,
            selected=False,
            width=40,
            card_height=3,
            ansi=False,
        )
        self.assertEqual(len(card), 3)
        self.assertEqual(card_content_line(3), 1)
        self.assertNotIn("blocked-child", card[0])
        self.assertIn("blocked-child", card[1])
        self.assertNotIn("blocked-child", card[2])
        self.assertTrue(card[0].startswith("     "))
        self.assertTrue(card[1].startswith(f"    {LEFT_CAP}"))

    def test_tall_card_uses_one_background_color(self) -> None:
        card = render_card(
            TreeRow(TabRecord(1, 1, "tab", (10,)), 0, None),
            selected=False,
            width=40,
            card_height=3,
        )
        self.assertIn("\x1b[48;2;32;35;42m", card[0])
        self.assertIn("\x1b[48;2;32;35;42m", card[1])

    def test_tall_verdict_card_repeats_status_cap_on_every_line(self) -> None:
        ready = render_card(
            TreeRow(
                TabRecord(1, 1, "ready", (10,), status="ready_to_merge"),
                0,
                None,
            ),
            selected=False,
            width=40,
            card_height=3,
            ansi=False,
        )
        blocked = render_card(
            TreeRow(
                TabRecord(2, 1, "blocked", (20,), status="blocked"),
                0,
                None,
            ),
            selected=False,
            width=40,
            card_height=3,
            ansi=False,
        )
        self.assertTrue(all(READY_RIGHT_CAP in line for line in ready))
        self.assertTrue(all(FLAME_RIGHT_CAP in line for line in blocked))

    def test_screen_has_no_normal_header(self) -> None:
        screen = render_screen([], 0, 17, 40, 8, total_tabs=9, ansi=False)
        self.assertNotIn("Kitty OS window", screen)
        self.assertNotIn("9 tabs", screen)

    def test_control_lines_fit_a_narrow_sidebar(self) -> None:
        width = 32
        screen = render_screen([], 0, 1, width, 9, ansi=False)
        lines = screen.splitlines()
        self.assertTrue(all(display_width(line) <= width for line in lines))
        self.assertEqual(len(lines), 9)
        self.assertIn("↑/↓", lines[0])
        self.assertIn("p │ parent", screen)
        self.assertIn("r │ refresh", screen)
        self.assertIn("q", lines[len(CONTROL_LINES) - 1])

    def test_controls_can_hide_without_changing_screen_geometry(self) -> None:
        visible = render_screen([], 0, 1, 40, 10, ansi=False)
        hidden = render_screen(
            [], 0, 1, 40, 10, ansi=False, show_controls=False
        )
        self.assertEqual(len(visible.split("\n")), len(hidden.split("\n")))
        self.assertIn("switch tab", visible)
        self.assertNotIn("switch tab", hidden)

    def test_pinned_help_labels_its_toggle(self) -> None:
        screen = render_screen(
            [], 0, 1, 40, 10, ansi=False, help_pinned=True
        )
        self.assertIn("? │ unpin help", screen)

    def test_control_legend_visually_separates_shortcuts_and_actions(self) -> None:
        line = render_control_line("Enter · click", "enter tab", 40, ansi=False)
        self.assertEqual(line.strip(), "Enter · click │ enter tab")

    def test_control_legend_names_the_current_edge_style(self) -> None:
        screen = render_screen(
            [], 0, 1, 48, 9, ansi=False, edge_style="rounded"
        )
        self.assertIn("e │ edge: rounded", screen)

    def test_control_legend_is_dimmer_than_tab_text(self) -> None:
        line = render_control_line("e", "edge: tapered", 48)
        shortcut_rgb = tuple(
            int(CONTROL_SHORTCUT_FOREGROUND[offset:offset + 2], 16)
            for offset in (0, 2, 4)
        )
        action_rgb = tuple(
            int(CONTROL_ACTION_FOREGROUND[offset:offset + 2], 16)
            for offset in (0, 2, 4)
        )
        self.assertIn(f"\x1b[38;2;{';'.join(map(str, shortcut_rgb))}m", line)
        self.assertIn(f"\x1b[38;2;{';'.join(map(str, action_rgb))}m", line)
        self.assertLess(sum(shortcut_rgb), sum((216, 222, 233)))
        self.assertLess(sum(action_rgb), sum((216, 222, 233)))

    def test_long_tab_list_uses_all_available_rows(self) -> None:
        self.assertEqual(vertical_padding(20, 10), 0)

    def test_bottom_padding_receives_the_odd_centering_row(self) -> None:
        self.assertEqual(vertical_padding(1, 12, 3), 4)
        self.assertEqual(vertical_bottom_padding(1, 12, 3), 5)

    def test_active_tab_has_persistent_background(self) -> None:
        active = TabRecord(1, 1, "active", (10,), is_active=True)
        rendered = render_row(
            TreeRow(active, 0, None), selected=False, width=80
        )
        self.assertIn("\x1b[48;2;76;86;106m", rendered)

    def test_folded_active_descendant_uses_dimmer_active_background(self) -> None:
        parent = TabRecord(1, 1, "parent", (10,))
        rendered = render_row(
            TreeRow(parent, 0, None, has_children=True,
                    is_collapsed=True, has_active_descendant=True),
            selected=False,
            width=80,
        )
        self.assertIn("\x1b[48;2;52;59;73m", rendered)

    def test_expanded_parent_does_not_look_like_the_active_child(self) -> None:
        parent = TabRecord(1, 1, "parent", (10,))
        rendered = render_row(
            TreeRow(
                parent,
                0,
                None,
                has_children=True,
                has_active_descendant=True,
            ),
            selected=False,
            width=80,
        )
        self.assertIn("\x1b[48;2;32;35;42m", rendered)
        self.assertNotIn("\x1b[48;2;52;59;73m", rendered)

    def test_rows_have_no_active_marker_gutter(self) -> None:
        active = render_row(
            TreeRow(TabRecord(1, 1, "active", (10,), is_active=True), 0, None),
            selected=False, width=30, ansi=False,
        )
        self.assertTrue(active.startswith(LEFT_CAP))
        self.assertNotIn("●", active)
        self.assertNotIn("◉", active)

    def test_inactive_row_has_full_width_inset_background_card(self) -> None:
        parent = render_row(
            TreeRow(TabRecord(1, 1, "parent", (10,)), 0, None),
            selected=False, width=30,
        )
        child = render_row(
            TreeRow(TabRecord(2, 1, "child", (20,)), 2, 1),
            selected=False, width=30,
        )
        background = "\x1b[48;2;32;35;42m"
        self.assertIn(background, parent)
        self.assertIn(background, child)
        self.assertLess(parent.index(background), child.index(background))
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        self.assertEqual(len(ansi.sub("", parent)), 29)
        self.assertEqual(len(ansi.sub("", child)), 29)

    def test_inactive_row_restores_readable_foreground_after_left_cap(self) -> None:
        rendered = render_row(
            TreeRow(TabRecord(1, 1, "visible", (10,)), 0, None),
            selected=False, width=30,
        )
        self.assertIn("\x1b[38;2;216;222;233m", rendered)
        self.assertTrue(rendered.startswith(panel_style()))

    def test_selection_does_not_create_a_second_highlight(self) -> None:
        row = TreeRow(TabRecord(1, 1, "one", (10,)), 0, None)
        self.assertEqual(
            render_row(row, selected=False, width=30),
            render_row(row, selected=True, width=30),
        )

    def test_status_glyph_width_does_not_move_title(self) -> None:
        statuses = [None, "🤖", "💬", "ready_to_merge", "blocked"]
        positions = []
        for status in statuses:
            rendered = render_row(
                TreeRow(TabRecord(1, 1, "fixed-title", (10,), status=status), 0, None),
                selected=False, width=40, ansi=False, now=0.0,
            )
            positions.append(display_width(rendered.split("fixed-title", 1)[0]))
        self.assertEqual(positions, [positions[0]] * len(positions))

    def test_only_tree_depth_moves_title_column(self) -> None:
        root = render_row(
            TreeRow(TabRecord(1, 1, "fixed-title", (10,), status="💬"), 0, None),
            selected=False, width=40, ansi=False,
        )
        child = render_row(
            TreeRow(TabRecord(2, 1, "fixed-title", (20,), status=None), 2, 1),
            selected=False, width=40, ansi=False,
        )
        root_column = display_width(root.split("fixed-title", 1)[0])
        child_column = display_width(child.split("fixed-title", 1)[0])
        self.assertEqual(child_column - root_column, 8)

    def test_leaf_row_has_no_tree_dash(self) -> None:
        leaf = render_row(
            TreeRow(TabRecord(1, 1, "leaf", (10,)), 0, None),
            selected=False, width=30, ansi=False,
        )
        self.assertNotIn("─", leaf)
        self.assertIn(LEFT_CAP, leaf)
        self.assertIn(RIGHT_CAP, leaf)

    def test_working_row_uses_rounded_right_cap(self) -> None:
        working = render_row(
            TreeRow(TabRecord(1, 1, "working", (10,), status="🤖"), 0, None),
            selected=False, width=30, ansi=False, now=0.0,
        )
        self.assertIn(LEFT_CAP, working)
        self.assertIn(RIGHT_CAP, working)
        self.assertNotIn(FLAME_RIGHT_CAP, working)

    def test_verdicts_replace_only_the_right_cap(self) -> None:
        ready = render_row(
            TreeRow(TabRecord(1, 1, "ready", (10,), status="ready_to_merge"), 0, None),
            selected=False, width=30, ansi=False,
        )
        blocked = render_row(
            TreeRow(TabRecord(2, 1, "blocked", (20,), status="blocked"), 0, None),
            selected=False, width=30, ansi=False,
        )
        self.assertIn(READY_RIGHT_CAP, ready)
        self.assertEqual(READY_RIGHT_CAP, "\ue0c8")
        self.assertIn(FLAME_RIGHT_CAP, blocked)
        self.assertNotIn(RIGHT_CAP, ready)
        self.assertNotIn(RIGHT_CAP, blocked)


if __name__ == "__main__":
    unittest.main()
