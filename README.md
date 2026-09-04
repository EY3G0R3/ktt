# ktt

`ktt` renders a parent/child tab tree in Kitty's native vertical tab bar.
It requires Kitty 0.48 or newer. The separate-window sidebar, embedded panes,
horizontal TUI, daemon, and old-Kitty fallback were removed after the native
renderer passed the migration gates in [VISUAL_CONTRACT.md](VISUAL_CONTRACT.md).
The final revision containing those paths is tagged `last-with-legacy`.

## Enable native tabs

Run this inside the Kitty process you want to configure:

```bash
python3 -m ktt
```

Bare `ktt` and `ktt native` both enable a native left-side tab bar for the
current Kitty process. KTT applies process-local overrides for the custom
style, center alignment, edge, visibility, and title width. It preserves
unrelated Kitty overrides and keeps an existing right-side native bar on the
right. Restarting Kitty restores the persistent configuration until KTT is
enabled again.

To enable KTT automatically for every new Kitty process, load its versioned
watcher in `kitty.conf`:

```conf
watcher /absolute/path/to/ktt/ktt/kitty_watcher.py
```

`python3 -m ktt watcher-path` prints the exact path. The watcher enables KTT
once Kitty has constructed its first window and waits until tab 2 to show the
bar. If KTT cannot activate on Kitty 0.48 or newer, it selects Kitty's regular
vertical tabs instead. Older Kitty versions retain the persistent horizontal
configuration.

KTT disables Kitty drag-and-drop for the current process while it owns the
native tab bar. Kitty exposes one global `drag_threshold` setting rather than
a tab-only switch, so this also disables dragging window title bars. Clicks
and KTT's tree-aware keyboard reordering continue to work.

KTT uses Kitty remote control. Configure `allow_remote_control yes` and a
reachable `KITTY_LISTEN_ON` socket. Native cards also require the KTT-aware
custom `tab_bar.py` already used by this installation.

Kitty older than 0.48 now returns a clear requirement error; there is no
fallback renderer.

## Tree relationships

`ktt_parent_window_id` is the only hierarchy edge. Launchers should set it on
the child window while creating a tab. KTT uses exact window IDs, so every
launch can create another nesting level without family-name inference.

```bash
python3 -m ktt launch-child --title review -- codex
python3 -m ktt link --child-window 42 --parent-window 17
python3 -m ktt unlink --child-window 42
```

A direct non-Workmux coordinator may publish `ktt_coordinator=HANDLE` so the
Workmux launch hook can resolve it. This is launch-time routing metadata; KTT
still renders and persists only `ktt_parent_window_id`.

`python3 -m ktt list` prints the current tree as a diagnostic snapshot.

## Tree ordering and navigation

The startup watcher also normalizes Kitty's physical tab order to tree preorder
only while KTT's native bar is enabled. It has no sidebar notification socket
or polling daemon.

Map the navigation kitten if you want tree-aware keys:

```conf
map alt+j kitten /absolute/path/to/ktt/ktt/tree_navigation_kitten.py next
map alt+k kitten /absolute/path/to/ktt/ktt/tree_navigation_kitten.py previous
map alt+n kitten /absolute/path/to/ktt/ktt/tree_navigation_kitten.py attention
map alt+shift+j kitten /absolute/path/to/ktt/ktt/tree_navigation_kitten.py move-next
map alt+shift+k kitten /absolute/path/to/ktt/ktt/tree_navigation_kitten.py move-previous
map alt+p kitten /absolute/path/to/ktt/ktt/parent_chooser_kitten.py
```

`next` and `previous` follow complete tree order. `attention` wraps through
ready, blocked, waiting, and complete tabs. The move actions reorder a node
among its siblings, moving its descendants as one subtree without changing any
parent relationship.

`Alt+p` treats the active tab as the child and opens a rofi prompt containing
only parents that cannot create a cycle. Choosing a parent updates the tree
immediately. `python3 -m ktt parent-chooser-kitten-path` prints the exact kitten
path for the mapping.

## Card behavior

Native cards retain the established visual contract:

- custom Kitty tab titles and tagged agent ownership;
- four-cell indentation per tree level;
- fixed status width, repository identity, and worktree context;
- active, waiting, working, ready, and blocked treatments;
- adaptive three-, two-, and one-row density with active-tab overflow handling.

The native renderer reads pending `workmux_verdict` values immediately. A
seven-second debounce prevents a freshly waiting agent from flashing amber
while its title still shows a working spinner.

## Preserved dormant designs

Changed-file details and keyboard help do not currently have a native tab-bar
surface. Their rendering code, tests, and product decisions remain deliberately
preserved so a future native overlay or companion surface can reuse them
without redesigning the behavior.

The preserved changed-file contract includes selected-repository ownership,
dirty counts, centered `bottom` placement, attached `inline` placement,
Fancylog alignment/colors, staged markers, and a ten-file cap. The preserved
help contract includes hidden-by-default state, independent centering above the
tab stack, aligned shortcut/action columns, dimmed colors, and edge-style
labels.

See [VISUAL_CONTRACT.md](VISUAL_CONTRACT.md) for executable gates and exact
behavior, and [DECISIONS.md](DECISIONS.md) for the historical rationale.

## Sessions

```bash
python3 -m ktt save-session
python3 -m ktt restore-session --dry-run
python3 -m ktt restore-session
```

Restore recreates tabs and hierarchy, then enables native vertical tabs. It no
longer starts a presentation daemon or embeds renderer panes.

## Verification

```bash
make autoupdate
```

Kitty loads the watcher and kittens directly from this checkout, so the
validated checkout is the installation. `make autoupdate-install` therefore
performs no copy step.
