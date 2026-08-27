# ktt

`ktt` is a tree-shaped tab bar for Kitty with vertical and experimental
horizontal views. It runs in a separate Kitty OS window, watches the tabs in a
main Kitty OS window, and uses Kitty remote control to focus the active tab.
Vertical cards use three terminal rows
when the whole tree fits, squeeze to two rows when necessary, and fall back to
one row under pressure. The normal TUI has no diagnostic
header; target-window details remain available through commands and errors
without permanently consuming a row. The help block is a centered two-column
legend with a visible separator between shortcuts and their actions. It stays
hidden by default; `?` shows or hides it. The legend is vertically centered
inside otherwise-unused space above the centered tab stack, so toggling it does
not move cards or mouse targets.

Horizontal mode gives each root tree a fixed-width column and stacks its
descendants downward with four-cell indentation. Cards are capped at forty
terminal cells and the complete group is centered, avoiding an edge-to-edge
ribbon on wide displays. It uses a compact one-line help legend and falls back
to an active-centered one-row tab strip when the window is too narrow or short
to show useful tree lanes.

See [VISION.md](VISION.md) for the original product vision and architecture.
The resolved product choices are in [DECISIONS.md](DECISIONS.md).
Prioritized follow-up work and the current status-data contract are documented
in [IMPROVEMENTS.md](IMPROVEMENTS.md).

## Try it from this checkout

Requirements: Python 3.11+, Kitty with `allow_remote_control yes`, and a
reachable `KITTY_LISTEN_ON` socket. Changing a tab's parent interactively also
requires `rofi`.

```bash
python3 -m ktt list
python3 -m ktt
```

Bare `ktt` targets the current Kitty OS window and opens the tree in a separate
sidebar OS window. The launched internal TUI receives that target explicitly,
so the sidebar never treats its own OS window as the tab source.

For immediate external tab-switch updates, load ktt's global Kitty watcher.
Run `ktt watcher-path`, then paste the printed absolute path into `kitty.conf`:

```conf
watcher /absolute/path/printed/by/ktt-watcher-path
```

The watcher sends the active tab ID and ordered membership in a nonblocking
local Unix datagram only when either value changes. When membership still
matches its cache, ktt repaints the active highlight immediately and performs a
full reconciliation snapshot 100 ms later for repository and window metadata.
Membership changes and legacy wakeups request an immediate full snapshot; the
one-second polling interval remains the recovery fallback. Title, spinner, and
status-only tab-bar redraws are filtered inside Kitty and do not wake ktt. When
both orientations watch the same Kitty OS window, passive tab-change wake-ups
are broadcast to both views while one listener remains the owner of external
tree-navigation commands. Refused socket paths left behind by abruptly closed
views are removed after an inode check, avoiding repeated failed sends without
touching live or concurrently replaced listeners.

Snapshot reads use Kitty's documented framed-JSON
[remote-control protocol](https://sw.kovidgoyal.net/kitty/rc_protocol/)
directly over a filesystem or Linux abstract `KITTY_LISTEN_ON` Unix socket.
This avoids starting `kitten @ ls` for every recovery poll. Commands that
change Kitty state still use the official `kitten` client because they are
interactive and infrequent. If the direct request fails—for example, because
the listener requires protocol features ktt does not implement—ktt disables
that path and falls back to `kitten @ ls` for the rest of the process.

ktt also caches the complete visible render signature. An unchanged recovery
poll does not rebuild or repaint the screen. With no working spinner, the TUI
sleeps until the next poll, source check, or input/event wake-up instead of
waking 20 times per second. Working rows schedule only their 120 ms animation
boundaries, preserving smooth dots without imposing that cadence while idle.

To make Kitty-wide `Alt-j`/`Alt-k` navigation follow ktt's visible tree order,
run `ktt navigation-kitten-path`, then map the printed absolute path:

```conf
map alt+j kitten /absolute/path/to/ktt/tree_navigation_kitten.py next
map alt+k kitten /absolute/path/to/ktt/tree_navigation_kitten.py previous
map alt+shift+j kitten /absolute/path/to/ktt/tree_navigation_kitten.py move-next
map alt+shift+k kitten /absolute/path/to/ktt/tree_navigation_kitten.py move-previous
```

When the main window is focused, the kitten sends navigation to ktt so folded
subtrees are honored. ktt also publishes its visible order and folded active
anchor to a tiny owner-only runtime file only when that value changes. When the
sidebar itself is focused, the kitten reads that snapshot and changes the main
tab directly inside Kitty without moving OS-window focus. If the sidebar is
absent, it falls back to the complete tree order inside Kitty. Navigation stays
bounded at the first and last visible rows, and no path rewrites native tabs.
Rapid key repeats are drained one transition per repaint at 50 ms intervals, so
every adjacent row remains visible instead of several queued switches appearing
as one jump. This cadence exists only while navigation is queued and does not
change idle polling. `Alt+Shift+j` and `Alt+Shift+k` move the active node among
its siblings without wrapping. Parent nodes move together with their complete
subtrees, and Kitty's native tab order is normalized to the same preorder shown
by ktt. Reordering never changes a tab's parent.

Inside the tree:

- left-click any physical row of a card to focus its tab;
- click a disclosure arrow, right-click a parent, or press Space to fold it;
- use the mouse wheel, `j`, `k`, or arrow keys to change the active main-window
  tab while keeping keyboard focus in ktt;
- Enter transfers keyboard focus into that already-active tab;
- `p` opens a rofi prompt to choose a new parent for the highlighted tab;
- `e` cycles the live card-edge style;
- `t` toggles Kitty's native tab bar while preserving its configured style;
- `r` refreshes immediately; `q` exits.

Fold choices persist in an atomic owner-only runtime file keyed by Kitty PID
and target OS-window ID. They survive ktt source reloads and in-place refreshes
without becoming cross-session configuration; closed tab IDs are pruned on the
next snapshot.

The current main-window tab is the single highlighted/selected state and uses
a higher-contrast background without a separate marker gutter. Folding does
not create another selection. When the active tab is hidden inside a folded
subtree, the visible ancestor uses a dimmer active background. Every tab has a
background card; child cards start
four columns farther right per level against the black panel, so card position
alone shows the tree. Leaf rows have no decorative dash. Every vertical card
uses the same left-aligned status, `/repository/`, and title sequence, so
selecting a card or adding active repository context does not move its middle
row. Tall cards center that line vertically. Filled themes keep one background
color
throughout, while the rounded theme uses a colored outline around the content
line. A black separator row distinguishes tall cards; every row inside the
card boundary remains part of the mouse target. Compact one-line mode omits
separators.

When ktt opens or refreshes its sidebar, it sets only that Kitty window's
background to the panel's black. This also colors any fractional-cell filler
left around Kitty's grid by a tiling window manager, avoiding a thin border
without changing the main terminal or Kitty's configured colors globally.

Four edge styles render against the real tree rather than a separate preview:
`tapered` (the default), `straight`, `rounded`, and `wedge`. Press
`e` to cycle them in that order; the help block names the active style. Select a
startup style with:

```bash
python3 -m ktt --edge-style rounded
python3 -m ktt --edge-style wedge launch
```

The content line uses `` as the left half-moon and `` as the normal right half-moon.
Ready-to-merge agents replace the right cap with the waveform/jet-exhaust
Powerline separator `` (U+E0C8). Its mirrored, left-facing partner is ``
(U+E0CA). Blocked agents use the flamey separator `` (U+E0C0) on the red
“dumpster fire” card. Working agents keep the rounded half-circle while their
braille spinner animates inside the card. Idle and other states also use the
rounded cap. On tall verdict cards in the filled themes, exhaust or flame
repeats on every physical row to form one continuous serrated status edge. The
rounded-outline theme keeps its corner glyphs and shows the verdict cap on the
content row.

Waiting agents—the Workmux `waiting` state currently projected as `💬`—use an
off-white attention card with dark text. An active waiting tab becomes slightly
brighter, while the speech bubble and rounded cap remain unchanged.
When that user variable transiently says `💬` while the live Kitty title still
starts with an animated working spinner, ktt treats the tab as working. This is
a direct precedence rule rather than a timer: the white card appears as soon as
the working signal is absent.

The status area is a fixed two terminal cells wide. Wide emoji, narrow
Powerline/braille glyphs, and an empty status therefore leave every root title
in the same column; only parent-child depth moves a title to the right. ktt no
longer renders family dots, reserves a family-marker column, or parses
`workmux_family`. Hierarchy comes exclusively from `ktt_parent_window_id`.
Each vertical card places a restrained but readable `/repository/` label before
its other identity fields. Compact horizontal
cards include it as `title · /repository/`. A deterministic hash of the full
repository name assigns its base hue without a finite palette. Before rendering,
ktt shifts any near-collisions around the color wheel so the repositories in the
current tree remain visibly distinct. The same repository set keeps the same
colors across launches; adding or removing a repository can move a colliding
label. The renderer also adjusts brightness when a card background needs more
contrast. In the normal three-row vertical view, `/repository/` and any linked
worktree form a left-aligned middle-row sequence on every tab, while the selected tab's
cached clean/dirty state is right-aligned on that row. Useful branch and nonredundant title form one
centered group on the bottom. Ordinary `main` and
`master` branches, branches represented by the title, and branches equivalent
to the worktree label are omitted. Titles equivalent to the displayed worktree
are omitted too.

Repository names come from Fancylog rather than a second set of Git or yadm
rules. Ktt submits each unique tab `cwd` to a two-worker background cache and
resolves linked-worktree identity in the same one-time task. Tabs sharing a
directory are deduplicated. Only the selected tab polls status and branch,
using its existing three-second detailed refresh.

## Active repository context

Every three-row tab card places `/repository/` on the middle-left and appends
`🌳worktree` only for a linked worktree.
The selected tab adds cached clean/dirty state on the middle-right. Useful
branch and nonredundant title share the bottom row. Redundant and default branch labels
are omitted, as are titles that repeat the worktree. Dirty counts remain on the
middle row and also become a heading above changed-file rows whenever at least
one file can remain visible. In the default `bottom` placement, changed-file
rows remain detached from the spatially stable tab stack and center inside its
lower free space. In `inline` placement, they attach immediately below the card
and follow its tree indent. Both modes right-align actions against a shared
path column. Paths start immediately to the right of the action;
only staged entries add the literal `staged`, while unstaged is the default.
Fancylog's ANSI colors distinguish modified, untracked, staged, and conflict
states. Changed files and their dirty heading use up to six free rows after
rendering every tab and collapse when the tree needs those rows. Summary polling continues even without
spare rows because it renders inside the selected card. Inactive cards retain
their one-time repository and linked-worktree identity without polling state. The selected
tab's three-second Fancylog snapshot supplies branch, summary, and file state.

ktt reads the active terminal's `cwd` from the existing Kitty snapshot and
asks `fancylog --status-only` to render the file column, a width-bounded
identity/count row, and a branch row. Ktt preserves Fancylog's aligned,
color-coded file rows and maps the last two rows into the selected tab card.
The result is cached for three seconds with a 750 ms subprocess timeout.
A tab, directory, width, or available-height change refreshes immediately. If
fancylog is unavailable or the directory has no supported repository, the
panel stays hidden.

Changed-file details default to `bottom`, keeping the tab stack spatially stable
and centering the details horizontally and vertically inside the free space
below it. Use `--changed-files-placement inline` to attach them immediately below
the selected card. `KTT_CHANGED_FILES_PLACEMENT=inline` sets the same override
through the environment. Status and branch placement inside the selected card
is unchanged.

Fancylog exclusively owns ordinary Git, linked-worktree, yadm, branch,
worktree-status, file-row palette, and truncation policy. Ktt parses only the
two summary rows for presentation; it carries no second Git/yadm
implementation.

ktt defaults changed-file details to Fancylog's warm `amber` palette. The
`terminal` palette instead follows Kitty scheme changes and inactive-window
fading, while `dracula` is available as a fixed truecolor reference. Choose
another palette without changing standalone Fancylog configuration:

```bash
ktt --repository-palette terminal launch
KTT_REPOSITORY_PALETTE=quiet ktt refresh
```

During development, changes to `ktt/*.py` restart the TUI automatically after
restoring terminal input mode. To replace a sidebar started by an older version
without replacing its top-level Kitty window, run:

```bash
python3 -m ktt refresh
```

Launch it in a separate Kitty OS window:

```bash
python3 -m ktt launch
```

Launch the experimental bottom-bar view without replacing the vertical view:

```bash
python3 -m ktt --orientation horizontal launch
```

The separate OS-window launcher remains available for comparison. The current
direction is a fixed-height bottom pane inside an agent's Kitty tab, documented
in [COCKPIT.md](COCKPIT.md).

Launch that bottom pane beneath the current Kitty window with an initial ten
percent height:

```bash
python3 -m ktt --orientation horizontal launch-pane
```

Set a different initial split percentage when testing density:

```bash
python3 -m ktt --orientation horizontal launch-pane --pane-percent 12
```

Prototype a persistent bottom bar in every tab of the current Kitty OS window:

```bash
python3 -m ktt --orientation horizontal embed --pane-percent 10
```

Prototype the same shared tree as a side pane in every tab:

```bash
python3 -m ktt --orientation vertical embed --pane-percent 20
```

`embed` starts one daemon for the target OS window and reconciles one small
renderer pane into every current and newly created tab. Horizontal renderers
use a bottom split and default to ten percent height; vertical renderers use a
root-level left-edge split and default to twenty percent width. If the content
side of any vertical tab is resized, that tab's sidebar width becomes the
shared width for every current tab and the starting width for new tabs. If the
content windows in a tab all close, the daemon closes that tab's renderer too,
allowing Kitty to remove the empty tab instead of expanding ktt to fill it. The
daemon owns Kitty
snapshots, tree construction, repository identities, folds, visible-order
publishing, and watcher navigation. Each pane consumes the shared snapshot and
only performs geometry-dependent rendering. The daemon also owns the single
selected-repository Fancylog refresh and broadcasts its summary, branch, and
changed-file rows; inactive renderer panes never launch duplicate Fancylog
polls. Keyboard navigation follows focus into the renderer in the destination
tab; Enter or a left click transfers focus back to that tab's content window.
Embedded renderer windows are excluded from tab identity and
repository-context selection.

Stop the daemon and close only its horizontal renderer panes with:

```bash
python3 -m ktt unembed
```

This is an experimental comparison path. `launch-pane` remains the simpler
single-tab prototype, and the separate OS-window modes are unchanged.

For a future three-column cockpit, create the bottom pane while the tab still
has a single top window, then split that top window into the equal-width
fancylog and scratch-shell rails. This allows ktt's split to span the full tab.

The horizontal window uses the distinct `ktt-horizontal` window class so dwm
or another window manager can assign it a shallow bottom region independently
of the vertical `ktt` sidebar. Both views share folds, active-tab state,
statuses, repository context, mouse switching, and visible tree order. Refresh
only the horizontal instance with:

```bash
python3 -m ktt --orientation horizontal refresh
```

Install an editable `ktt` command with `uv`:

```bash
uv tool install --editable .
ktt launch
```

This creates `~/.local/bin/ktt` through uv's managed tool environment while
keeping imports pointed at the current checkout, so source changes take effect
without reinstalling the command.

## Create a parent-child relationship

The child and parent values are Kitty terminal-window IDs, available inside a
Kitty terminal as `$KITTY_WINDOW_ID` and in `kitten @ ls` output.

```bash
ktt link --child-window 456 --parent-window 123
ktt unlink --child-window 456
```

`link` writes `ktt_parent_window_id=123` to window 456. The renderer then puts
the child tab below the tab containing window 123. The installed Workmux agent
wrappers set this automatically for dispatched children.

For an existing tab, highlight it in ktt and press `p`. The rofi prompt lists
the other tabs in tree order. Descendants are omitted because choosing one
would create a cycle; cancelling rofi leaves the hierarchy unchanged.

### Workmux integration contract

The yadm-managed Workmux configuration uses
`~/.config/workmux/hooks/assign-parent`, called by both configured Claude and
Codex wrappers before the agent sandbox starts. It reads the dispatched
prompt's exact `Coordinator: HANDLE`, resolves that handle within the same Git
repository, selects its sole status-bearing Kitty agent window, and writes that
window ID to the child as `ktt_parent_window_id`.

The adapter fails closed when the coordinator, repository, Kitty session, or
agent window is missing or ambiguous. It never writes `workmux_family`, and it
does not modify or depend on Workmux source or binary internals. A plain
`workmux add` without the coordinator contract remains an independent root.

The equivalent direct Kitty launch contract is:

```bash
kitten @ launch --type=tab \
  --source-window "id:$KITTY_WINDOW_ID" \
  --location=after --cwd=current \
  --var "ktt_parent_window_id=$KITTY_WINDOW_ID" \
  child-agent-command
```

Each child repeats the same operation with its immediate coordinator, which
produces arbitrary nesting depth. If another launcher cannot attach the
variable during launch, call `ktt link --child-window CHILD --parent-window
PARENT` immediately after Kitty returns the new child window ID. No renderer
change is needed.

For launchers that can call `ktt` directly, create and tag the child in one
operation:

```bash
ktt launch-child --title child-agent -- codex -- "child prompt"
```

This uses the current `$KITTY_WINDOW_ID` as the parent and passes the parent
variable to Kitty as the new tab is created.

Use `--target-os-window ID` to pin any command to one Kitty OS window and
`--to unix:/path/to/socket` when `KITTY_LISTEN_ON` is unavailable.
Pass `--no-auto-reload` before the command to disable source watching. Pass
`--edge-style STYLE` before the command to choose the initial edge theme.

## Test

```bash
python3 -m unittest discover -s tests -v
```
