# ktt product decisions

Decided on August 22, 2026 (PDT). These choices replace the open-ended items
in the original first-slice plan. They can be revisited with evidence, but no
longer block implementation.

## 1. Workmux owns launch-time assignment; ktt owns the contract

`ktt_parent_window_id` is the canonical tree edge. `ktt` owns its meaning,
validation, rendering, and manual commands. A launcher that knows both exact
Kitty window IDs writes it while creating the child. The installed Workmux
configuration now calls an `assign-parent` adapter from both agent wrappers; it
sets this variable and never assigns `workmux_family`. There is no dual-write
period and no family fallback in ktt.

Kitty's horizontal tab bar should derive its color key only from the cached tree
root. Tabs that predate the cutover and lack a parent edge remain independent
roots until relaunched; compatibility metadata is not retained to preserve
their old family color.

The adapter must use the launching agent's exact Kitty window for every child,
rather than a tree root ID. The configured wrappers resolve it from the exact
`Coordinator: HANDLE`, same-repository Workmux path, and sole status-bearing
window before the sandbox starts. Kitty's direct launch form is `--var
ktt_parent_window_id=PARENT`; the manual alternative is `ktt link` after Kitty
returns the child window ID. Repeating this at each launch creates multiple
indentation levels without additional renderer logic.

This keeps process ancestry at the only layer that reliably knows it and keeps
the renderer independent of repository paths or prompt parsing.

## 2. The window manager owns placement

`ktt launch` creates a separate Kitty OS window with class and name `ktt`.
dwm, another tiling manager, or the user decides its monitor, left/right
placement, and width. `ktt` will not move or resize top-level windows.

This avoids coupling the application to X11, Wayland, or one window manager.

## 3. Rows expand when vertical space permits

Use two- or three-line cards to provide a larger mouse target and richer
information when the sidebar has room. Fall back automatically to shorter
cards, down to one line per tab, when the full tree would not fit. The model
remains structured so adaptive rows do not require extra Kitty queries.

The first expanded fields should be repository/branch, agent phase, and the
latest blocker or readiness reason.

## 4. Navigation is safe and direct

- Moving with the wheel, `j`/`k`, or arrows changes the active main-window tab
  and restores focus to ktt. This active tab is the only selection highlight.
  Enter or left-click transfers keyboard focus into the main window.
- The disclosure arrow, right-click, or Space folds a subtree.
- Reparenting stays an explicit `ktt link` command; there is no drag-to-reparent.
- Closing tabs is not part of the main row click surface. A later close action
  must be explicit and confirm tabs containing running processes.

This favors fast switching without making a small pointer error destructive.

## 5. Events drive tab selection; polling is recovery

Kitty's global `on_tab_bar_dirty` watcher sends ktt a nonblocking Unix-datagram
wake-up when the active tab or ordered tab membership changes. ktt immediately
reads one fresh Kitty snapshot. Title, spinner, and status-only redraws are
filtered inside Kitty. The 500 ms JSON poll remains as a recovery path when the
watcher is absent or an event is lost.

Development reload is separate from Kitty-state delivery: a source change
automatically restarts the running TUI in place after restoring terminal mode.
`ktt refresh` replaces an older sidebar process inside the same Kitty OS
window, so the window manager keeps its tile.

## 6. Edge treatments are switchable themes

Keep the explored card shapes as real renderer styles rather than choosing one
from static mockups. `tapered` remains the initial default; `stacked`,
`straight`, `rounded`, and `wedge` are equally available through
`--edge-style`. Pressing `e` cycles them against the live tree and the footer
names the current style.

All styles share the same tree, status, density, scrolling, and mouse-hit
model. In one-line compact mode, shapes that require vertical geometry fall
back to the default Powerline caps.

## 7. Repository context occupies only spare padding

Added August 23, 2026 (PDT).

Show repository, directory, branch, and worktree state at
the top of the sidebar for the active main-window tab. The panel may replace up
to three existing blank padding rows, but must not reduce tab-card height or
capacity. It compacts before it disappears as the tree grows.

Kitty's active-window `cwd` is the path authority. ktt passes it, the available
row count, and the sidebar width to `fancylog --status-only`, then caches the
rendered rows for three seconds. fancylog owns repository discovery—including
yadm—status semantics, palette, and truncation. ktt treats command failure as
an absent panel and carries no fallback Git parser.
