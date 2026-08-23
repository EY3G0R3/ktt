# Kitty Tab Tree: original vision

## The idea

`ktt` is a vertical, tree-shaped tab bar for Kitty, inspired by Firefox's
Tree Style Tab extension and by `workmux sidebar`.

The tree represents who launched whom. When an agent launches another agent,
the new Kitty tab becomes a child of the launching agent's tab. Children are
indented below parents, and nesting can continue to any depth.

Each row initially occupies one terminal line and mirrors the useful state in
the existing Kitty tab bar:

- the tab title;
- a stable, colored tree marker;
- an animated spinner while an agent is working;
- green `ready_to_merge` state;
- red `blocked` state; and
- the other existing workmux states, such as waiting and done.

Rows are deliberately modeled as records rather than strings so a later
version can make them taller and show branch, repository, review, cost, or
other agent details.

## Why v1 is a separate Kitty OS window

Kitty's hierarchy is OS window -> tab -> terminal window. Its built-in tab bar
belongs to each OS window and is horizontal; it does not expose a persistent
vertical sidebar shared by all tabs. Putting a terminal pane inside every tab
would duplicate the tree, consume layout space repeatedly, and recreate it on
every tab switch.

Version 1 therefore runs `ktt` in a second top-level Kitty OS window. A tiling
window manager such as dwm can keep it to the left of the main Kitty OS window.
Both windows remain in the same Kitty instance, so `ktt` can use Kitty remote
control to:

1. read the main OS window's tabs with `kitten @ ls`; and
2. activate a row with `kitten @ focus-tab --match id:<tab-id>`.

The main OS window ID is captured when the sidebar is launched. This avoids
accidentally displaying or controlling the sidebar's own tab.

Relevant Kitty interfaces:

- <https://sw.kovidgoyal.net/kitty/remote-control/>
- <https://sw.kovidgoyal.net/kitty/launch/>
- <https://sw.kovidgoyal.net/kitty/overview/#tabs-and-windows>

## Tree identity

Kitty user variables belong to terminal windows, not directly to tabs. `ktt`
uses this variable on a child agent's terminal window:

```text
ktt_parent_window_id=<launching-agent-kitty-window-id>
```

The parent value is an exact Kitty terminal-window ID. `ktt` maps that ID back
to its containing tab. Unlike a family label, this supports multiple levels and
answers the important question: which agent launched this agent?

`ktt_parent_window_id` is the only hierarchy metadata. ktt does not read
`workmux_family`; external integrations must replace that legacy assignment in
one cutover rather than dual-writing both relationship schemes.

If a parent window disappears, its children remain visible as roots. Cycles or
invalid values are also rendered safely as roots rather than hiding tabs.

## First implementation slice

The initial usable slice includes:

- live polling of Kitty's JSON state;
- automatic selection of the main OS window, or an explicit OS window ID;
- arbitrary-depth tree ordering from `ktt_parent_window_id`;
- current workmux status rendering and animation;
- keyboard navigation with arrows or `j`/`k`;
- tab activation with Enter;
- `link` and `unlink` commands to manage parent metadata; and
- a `launch-child` command that atomically tags a newly launched child tab; and
- a `launch` command that opens the sidebar as a separate Kitty OS window.

## Original deferred decisions and their resolution

These were deferred during the first slice. They were decided on August 22,
2026 (PDT); [DECISIONS.md](DECISIONS.md) is now authoritative:

1. **Workmux hook ownership.** The installed configuration replaced
   `assign-family` with `assign-parent` after the metadata contract passed live
   tab tests. The wrapper resolves the exact coordinator window before the
   child sandbox starts. **Decision implemented:** configuration assigns the
   edge; ktt owns the metadata contract; Workmux source remains untouched.
2. **Tiling policy.** Let dwm or another window manager place the `ktt` class at
   first. **Decision:** window-manager placement remains the permanent boundary.
3. **Richer rows.** Keep one row per tab first; add adaptive multi-line rows
   without changing the Kitty state/model layer. **Decision:** use taller cards
   when space permits and fall back automatically to one line.
4. **Interaction.** Mouse selection and collapse/expand are now implemented.
   **Decision:** explicit command-based reparenting and no destructive close
   affordance on the main row.
5. **Event delivery.** Polling is sufficient for v1. A Kitty watcher or a small
   event bridge can reduce latency and idle work later. **Decision:** retain
   500 ms polling until measurements justify an event bridge.

## Future direction: horizontal tree bar

A horizontal ktt mode could act as a visual replacement for Kitty's built-in
tab bar. Root tabs would run left to right across the top, while each root's
descendants grow downward beneath it. Siblings would occupy adjacent columns
or lanes, making launch ancestry visible without a permanently narrow sidebar.

The primary motivation is gaze travel rather than space efficiency. Wide
displays favor a left sidebar geometrically, but reading it requires turning
the head away from the prompt. A shallow strip docked at the bottom remains in
peripheral vision near the place where prompts are typed and responses finish.
The cost is scarce vertical terminal space, so height must be capped and the
tree must collapse aggressively under pressure.

The existing Kitty snapshot, parent-edge model, folding state, status policy,
and focus commands should remain shared. Only layout, hit testing, navigation,
and density would differ. The first experiment should run in a separate,
shallow ktt OS window tiled below the main Kitty window; Kitty's single-row
custom tab renderer is not assumed to provide a multi-row drawing surface.

Questions to resolve in the experiment:

- how subtree width is allocated when titles and child counts differ;
- whether descendants form columns, compact diagonal branches, or both as
  switchable themes;
- how horizontal scrolling preserves the active path and parent context;
- how folding and mouse targets behave when several trees overlap vertically;
- when the layout collapses to a one-row conventional tab bar.

The horizontal and vertical modes should be two views over one tree model, not
separate applications or metadata contracts.

## Success criteria

The first milestone is successful when a separate `ktt` OS window can stay
open, show every tab in the selected main Kitty OS window, animate working
agents, clearly color ready/blocked agents, render three nesting levels from
parent metadata, and focus the chosen main-window tab.
