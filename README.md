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

## Configuration

KTT reads an optional `~/.config/ktt/config.toml` (or under
`$XDG_CONFIG_HOME`). Every key has a default, and an unknown or mistyped value
falls back to it rather than breaking the tab bar. Apply a change with
`kitty @ load-config` twice.

```toml
[phase_track]
# form:  dots ●○  blocks ▰▱  squares ■□  bar ━─  thick ▮▯  stairs ▁▂▃
#        braille ⣿⣀  full █░
form = "squares"
# color: phase     done cells in the current phase's color (default)
#        two_tone  yellow until ready to merge turns the track green
#        gradient  yellow shading to green across the six steps
#        rainbow   each done cell in the color of its own phase
#        accent    earlier steps dim, the current step bright
#        fixed     one progress green regardless of phase
color = "phase"
```

## Sessions

When KTT's watcher is configured, it automatically maintains a rolling crash
recovery snapshot at `$XDG_STATE_HOME/ktt/recovery.json` (normally
`~/.local/state/ktt/recovery.json`). A tab topology change requests a snapshot
after a one-second settle delay, and a 30-second refresh captures agents that
start or change without opening a new tab. Snapshots use atomic replacement, so
an interrupted write leaves the previous good snapshot intact.

At the next Kitty startup, KTT moves that final snapshot to
`recovery.previous.json` before recording the new process. `ktt session restore`
prefers the preserved pre-startup file, preventing a new shell tab from
overwriting the session needed after a reboot. If no previous-process snapshot
exists, it uses the current rolling file.

```bash
ktt session save [name]
ktt session restore [name]
ktt session list
ktt session show [name]
```

The `session` group is the stable interface for higher-level launchers. Saving
without a name creates a timestamped snapshot such as `2026-09-10-192353`; a
name creates or replaces a stable named snapshot. KTT also retains one
hourly `autosave-YYYY-MM-DD-HH00-ZONE` snapshot for eight days, capped at 200
files. The live crash snapshot still refreshes every 30 seconds. Restoring
without a name selects the newest manual or automatic snapshot; restoring
`autosave` explicitly selects the newest automatic snapshot. Add `--dry-run`
to restore to preview its launch plan, or `--new-window` to avoid replacing
the current tab. `show` displays each saved tab's title, hierarchy, state,
working directory, agent session, and launch command without restoring it.

Use automatic recovery after an abrupt reboot. It restores the latest automatically
observed set, so tabs closed before that snapshot stay closed. Named snapshots
remain separate from the rolling automatic snapshot.

KTT uses rolling full snapshots instead of an open/close event journal. The
manifest already captures tab hierarchy, focus, working directories, and
resumable agent IDs in one atomic file. A journal would also need a baseline,
replay, and compaction while still needing periodic full scans to notice an
agent starting inside an existing tab.

Restore recreates tabs and hierarchy, then enables native vertical tabs. It no
longer starts a presentation daemon or embeds renderer panes. The recovery file
can lag a topology change by about one second, or an in-tab agent change by up
to 30 seconds.

## Verification

```bash
make autoupdate
```

Kitty loads the watcher and kittens directly from this checkout, so the
validated checkout is the installation. `make autoupdate-install` therefore
performs no copy step.
