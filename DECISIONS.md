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

## 5. Polling is the state-delivery baseline

Kitty JSON is polled every 500 ms, while spinner animation remains local. A
watcher/event bridge will be considered only if measured idle cost or latency
becomes noticeable with roughly 50 or more tabs.

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
