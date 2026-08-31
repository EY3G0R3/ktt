# ktt product decisions

Decided on August 22, 2026 (PDT). These choices replace the open-ended items
in the original first-slice plan. They can be revisited with evidence, but no
longer block implementation.

## 0. Native vertical tabs are primary; the sidebar is compatibility-only

Kitty 0.48 added left/right native tab bars. Bare `ktt` selects that backend
when the running Kitty process is new enough and falls back to the original
separate-window sidebar otherwise. `ktt native` requires the new backend, while
`ktt launch` always exposes the legacy one.
Native selection is a runtime override for the current Kitty process, not a
persistent config rewrite. Hiding the bar retains that native identity so the
same toggle can show it again; restarting Kitty restores the configured edge.
While that native identity is managed, KTT also owns a process-local custom
style and center alignment. Its renderer raises Kitty's two-row native cap to
the same adaptive three-, two-, and one-row tapered cards used by the sidebar,
including card gaps, tree indentation, active-tab visibility, and vertical
centering. Hiding retains these overrides so a show/hide cycle is stable;
restarting Kitty restores the persistent preset.

The legacy backend remains tested but frozen: compatibility fixes are in scope;
new vertical presentation features are not. Remove it after the supported
machines have moved to Kitty 0.48+, rather than carrying permanent dual-backend
feature work.

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

An embedded horizontal pane is not a top-level placement exception. Kitty's
`splits` layout owns geometry inside the existing OS window; dwm continues to
see and tile one ordinary Kitty client. Ktt must not add application-specific
weights, docks, or reserved regions to dwm's generic layouts.

## 3. Rows expand when vertical space permits

Use two- or three-line cards to provide a larger mouse target and richer
information when the sidebar has room. Fall back automatically to shorter
cards, down to one line per tab, when the full tree would not fit. The model
remains structured so adaptive rows do not require extra Kitty queries.

Use the same left-aligned status, repository, and title sequence on every
vertical card at every density, with the repository before the title.
Selection and active repository context must not change that alignment.
Disclosure hit testing remains in its fixed tree column.

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
Kitty-wide `Alt-j` and `Alt-k` traverse the visible tree rather than Kitty's
flat tab order. From the main window, the Kitty-side kitten delegates through
ktt's event socket. From the focused sidebar, it reads ktt's owner-only visible
order snapshot and changes the target manager's active tab directly, preserving
OS-window focus. Snapshots name their publisher PID and are ignored once that
process is gone. Folded subtrees are skipped exactly as rendered. The kitten
computes the complete tree itself when no ktt listener or snapshot is
available; no path reorders native tabs.

`Alt+Shift+j` and `Alt+Shift+k` reorder sibling nodes in the same direction as
tree navigation. A parent and its descendants move as one block, and the
resulting native Kitty order is normalized to the tree preorder. Reordering is
bounded within one sibling list and never implicitly changes parent metadata.

Fold state is local to one Kitty process and target OS window, but durable
across ktt process replacement. Store the collapsed tab-ID set atomically in
the owner-only runtime directory, reload it before building the first tree, and
prune IDs when their tabs disappear. Do not promote this interaction state into
repository configuration or a global cross-Kitty preference.

## 5. Events drive tab selection; polling is recovery

Kitty's global `on_tab_bar_dirty` watcher sends ktt a nonblocking Unix-datagram
wake-up when the active tab or ordered tab membership changes. ktt immediately
reads one fresh Kitty snapshot. Title, spinner, and status-only redraws are
filtered inside Kitty. The one-second JSON poll remains as a recovery path when
the watcher is absent or an event is lost.

Rendering is independently demand-driven. A signature covers the visible tree,
selection, geometry, pinned-help state, repository rows, errors, theme, and the
current spinner frame. ktt repaints only when that signature changes. Without a
working row, input waits until the next poll or source deadline rather than a
fixed 50 ms timer; working rows add their next 120 ms frame boundary.

Development reload is separate from Kitty-state delivery: a source change
automatically restarts the running TUI in place after restoring terminal mode.
`ktt refresh` replaces an older sidebar process inside the same Kitty OS
window, so the window manager keeps its tile.

## 6. Edge treatments are switchable themes

Keep the explored card shapes as real renderer styles rather than choosing one
from static mockups. `tapered` remains the initial default; `straight`,
`rounded`, and `wedge` are equally available through
`--edge-style`. Pressing `e` cycles them against the live tree and the help block
names the current style.

All styles share the same tree, status, density, scrolling, and mouse-hit
model. In one-line compact mode, shapes that require vertical geometry fall
back to the default Powerline caps.

## 7. Repository context uses the selected card's spare rows

Added August 23, 2026 (PDT).
Revised August 26, 2026 (PDT).

Left-align repository or yadm identity on every card's middle row, followed by
worktree identity only for linked worktrees.
Show cached clean/dirty state on the selected card's right. Group useful
branch and nonredundant title on the bottom row. Omit default branches and any
branch represented by the title or worktree; omit the title when it repeats the
worktree. Attach
changed-file rows below the card. When space permits a dirty heading plus at
least one file, repeat dirty counts as the attachment heading while retaining
them in the card.
Those rows may
consume only space left after rendering every
tab and must not reduce tab-card height or capacity. They compact before they
disappear as the tree grows. Lower cards shift as part of the centered group,
and mouse hit testing follows their rendered positions. Keyboard help remains
centered separately in the spare space above the group.

Each tab's content-window `cwd` is the path authority. A two-worker cache
resolves repository and linked-worktree identity once per unique directory.
Only the selected tab polls branch and state, caching detailed Fancylog rows for
three seconds. fancylog owns repository discovery—including yadm—status
semantics, palette, and truncation. Failed selected-tab refreshes retain the
last good snapshot.

## 8. Orientations share one branch behind a view boundary

Added August 23, 2026 (PDT).

Keep vertical and horizontal ktt on the same main branch. They are two
presentations of one Kitty snapshot, hierarchy, status contract, fold store,
visible order, and navigation system. A permanent horizontal experiment branch
would duplicate fixes in all of those layers, drift over time, and make the
required one-action orientation switch depend on changing installed code.

Vertical remains the default and horizontal remains explicitly experimental.
The TUI talks to a selected view object for rendering, density, repository
capacity, and mouse hit-testing; it does not branch through horizontal and
vertical geometry itself. Orientation-specific behavior belongs behind that
boundary. The initial adapter is `ktt/views.py` and preserves the existing
renderers without changing their output.

Short-lived development branches remain appropriate for risky refactors, but
orientation is not a product branch. If either renderer grows materially,
split its implementation into a dedicated module while retaining the same view
interface and shared model. Do not solve growth by copying shared runtime code
into a long-lived branch.
