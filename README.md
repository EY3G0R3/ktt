# ktt

`ktt` is an early vertical, tree-shaped tab bar for Kitty. It runs in a
separate Kitty OS window, watches the tabs in a main Kitty OS window, and uses
Kitty remote control to focus the active tab. Short tab lists are centered
vertically above a six-line controls footer. Cards use three terminal rows
when the whole tree fits, squeeze to two rows when necessary, and fall back to
one row under pressure. The normal TUI has no diagnostic
header; target-window details remain available through commands and errors
without permanently consuming a row. The footer is a centered two-column
legend with a visible separator between shortcuts and their actions.

See [VISION.md](VISION.md) for the original product vision and architecture.
The resolved product choices are in [DECISIONS.md](DECISIONS.md).
Prioritized follow-up work and the current status-data contract are documented
in [IMPROVEMENTS.md](IMPROVEMENTS.md).

## Try it from this checkout

Requirements: Python 3.11+, Kitty with `allow_remote_control yes`, and a
reachable `KITTY_LISTEN_ON` socket.

```bash
python3 -m ktt list
python3 -m ktt
```

Inside the tree:

- left-click any physical row of a card to focus its tab;
- click a disclosure arrow, right-click a parent, or press Space to fold it;
- use the mouse wheel, `j`, `k`, or arrow keys to change the active main-window
  tab while keeping keyboard focus in ktt;
- Enter transfers keyboard focus into that already-active tab;
- `e` cycles the live card-edge style;
- `r` refreshes immediately; `q` exits.

The current main-window tab is the single highlighted/selected state and uses
a higher-contrast background without a separate marker gutter. Folding does
not create another selection. When the active tab is hidden inside a folded
subtree, the visible ancestor uses a dimmer active background. Every tab has a
background card; child cards start
four columns farther right per level against the black panel, so card position
alone shows the tree. Leaf rows have no decorative dash. Tall cards center the
title/status line vertically. Filled themes keep one background color
throughout, while the rounded theme uses a colored outline around the content
line. A black separator row distinguishes tall cards; every row inside the
card boundary remains part of the mouse target. Compact one-line mode omits
separators.

When ktt opens or refreshes its sidebar, it sets only that Kitty window's
background to the panel's black. This also colors any fractional-cell filler
left around Kitty's grid by a tiling window manager, avoiding a thin border
without changing the main terminal or Kitty's configured colors globally.

Five edge styles render against the real tree rather than a separate preview:
`tapered` (the default), `stacked`, `straight`, `rounded`, and `wedge`. Press
`e` to cycle them in that order; the footer names the active style. Select a
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

The status area is a fixed two terminal cells wide. Wide emoji, narrow
Powerline/braille glyphs, and an empty status therefore leave every root title
in the same column; only parent-child depth moves a title to the right. ktt no
longer renders family dots, reserves a family-marker column, or parses
`workmux_family`. Hierarchy comes exclusively from `ktt_parent_window_id`.

## Active repository context

The otherwise-unused top padding shows the active main tab's repository,
working directory, branch, and clean/dirty summary. It uses two lines when
available, compacts to one, and disappears when
the tab tree needs every content row. Card height, capacity, centering, and
mouse coordinates therefore do not change to make room for the panel.

ktt reads the active terminal's `cwd` from the existing Kitty snapshot and
asks `fancylog --status-only` to render a width-bounded identity/count row plus
a branch row. The result is cached for three seconds with a 750 ms subprocess
timeout. A tab, directory, width, or available-height change refreshes
immediately. If fancylog is unavailable or the directory has no supported
repository, the panel stays hidden.

fancylog exclusively owns ordinary Git, linked-worktree, yadm, branch,
worktree-status, palette, and truncation policy. ktt neither parses its output
nor carries a second Git/yadm implementation; it only places the returned ANSI
rows into spare padding.

ktt defaults that embedded panel to fancylog's neutral `graphite` palette so
it recedes behind the tab cards. Choose another palette without changing
standalone fancylog configuration:

```bash
ktt --repository-palette quiet launch
KTT_REPOSITORY_PALETTE=amber ktt refresh
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

Install an editable `ktt` command:

```bash
python3 -m pip install --user -e .
ktt launch
```

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
