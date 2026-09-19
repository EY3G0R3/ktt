# KTT visual contract

Established September 1, 2026 (PDT).

This document was the compatibility gate for replacing the attached KTT window
with Kitty's native vertical tabs. The gate passed, and the old runtime was
removed on September 1, 2026 (PDT). Its final revision is tagged
`last-with-legacy`. The established behavior remains authoritative until an
explicit later decision changes it.

## Completed native migration gate

The retired transport and interactive TUI were removed after:

1. Equivalent live-Kitty and serialized-Kitty inputs produce equivalent tab
   identity, effective custom titles, agent ownership, hierarchy, working
   directory, selection, and attention behavior, except where noted below.
2. Native cards match the legacy `render_card` output for the same records,
   repository context, dimensions, time, and theme.
3. Adaptive one-, two-, and three-row density preserves the legacy card-height
   and separator rules. Native-only scrolling or an overflow marker may differ.
4. The card and dormant-surface tests named below remain in the suite.

The retained executable regression gates are `tests/test_adapter_parity.py`,
`tests/test_native_card_state.py`, `tests/test_render.py`, and
`tests/test_tab_bar_geometry.py`.

## Accepted historical differences

Parity protected product behavior, not implementation mechanics or every
terminal cell. These differences justified the native result and remain
recorded:

- Kitty owns the native surface's physical width, mouse targets, and scrolling.
  KTT keeps the same responsive truncation and card-density rules at a given
  size, but does not reproduce the legacy window's placement machinery.
- Native overflow keeps the active tab visible and reserves an `…` row. The
  legacy sidebar silently showed a selected slice. The native marker is clearer
  and does not justify recreating legacy scrolling.
- Native tabs read a pending `workmux_verdict` immediately, while the legacy
  adapter reads `workmux_status` until a hook promotes the verdict. The native
  result is newer information and remains the chosen behavior.
- Changed-file details, the help block, interactive edge-style cycling, and
  folding have no native-tab surface today. Their decisions, pure renderers,
  and tests remain preserved below rather than being forced into Kitty's tab
  plate.

## Tab-card behavior

The canonical painter is `ktt.render.render_card`. Native code supplies data and
physical rows to that painter; it must not independently reinterpret the visual
design.

- Custom Kitty tab names use Kitty's effective title. A tagged agent window is
  the deliberate exception: it exclusively owns that tab's title and metadata.
- Tree depth shifts a child card four cells per level. Status always occupies
  two cells, so titles remain aligned across spinner, emoji, and empty states.
- Three-row cards collect their dynamic values once in an immutable snapshot.
  Their widgets only format that snapshot; they never query Kitty, Git,
  Workmux, the clock, or configuration independently.
- `THREE_ROW_CARD_WIDGETS` is the complete placement declaration:

  | left | center | right |
  | --- | --- | --- |
  | status space | worktree | repository state |
  | status | title | phase track |
  | status space | repository context | phase label |

  The fixed-width left column is reserved for status; its top and bottom cells
  are empty. Center widgets therefore share one starting column, while the
  right widget is pinned to the right. When a worktree is shown, title and
  repository text receive a spacer matching the worktree glyph so their text
  aligns after that glyph. There is no per-widget alignment metadata. If a row
  is tight, left-flow content truncates before the pinned right widget
  according to the shared row compositor.
- Native cards do not show a disclosure triangle or reserve space for one.
  Native trees are always expanded; indentation already communicates the tree.
- The active native card uses the full available width. Every inactive card is
  three cells shorter at the right edge; its widgets receive that reduced width
  so truncation and right alignment remain inside the visible card.
- Worktree, title, and repository context have fixed top, middle, and bottom
  positions. Missing values leave their declared slot empty; widgets never
  move between rows. A title that repeats the worktree is omitted. Two-row
  cards retain their compact shared-row behavior.
- The title color only ever brightens to reach contrast. The shared accent
  helper moves to the nearer readable lightness, which on the active card's
  light slate is the dark end; a title must stay light on every card.
- A worktree agent's reported phase (`workmux_phase`) stacks the right edge
  of a three-row card: working-tree state on the top row, the eight-cell track
  (`■■■□□□□□` for fixing review by default) on the middle row, and the phase
  label with compact elapsed time on the bottom row, such as `in review (12m)`,
  each at the same right column. A two-row card has
  no top row, so its state stays on the middle row and label and track share
  the bottom row as `fixing review (12m) ■■■□□□□□`. One-row cards omit the phase
  and its elapsed time. Elapsed time uses Workmux's durable phase-transition
  timestamp, updates on minute boundaries, and compacts to hours and days.
  Done cells take the phase color, the rest meta gray, both passed through
  the shared accent helper so they stay visible on the active card's light
  slate. A clean tree is the one-cell filled check ``; on a three-row card
  it sits at the top right with one interior blank cell between it and the
  visible card edge, before the structural cap cell. Dirty and conflict states
  retain their detail there. The right edge is the one column every card shares
  regardless of tree depth, so state, phase tracks, and labels line up down the
  bar. A lifted title claims its full width before state uses what remains, and
  starts at the middle row's text column even with the state beside it. A phase
  off the pipeline,
  such as `needs human design`, shows its label with no track. Its whole card
  uses the yellow attention background, even when its status is blocked;
  ordinary blocked cards remain red. Coding is yellow and fixing review is
  orange. The track's form and coloring are user-configurable (see README,
  "Configuration"); the contract fixes the placement, not the glyphs.
- Active, active-descendant, working, waiting, ready, merged, and blocked treatments
  retain the established colors, brightness, caps, and attention debounce.
  Active and inactive card text use the same normal font weight; the active
  background carries selection without requesting a different font face.
- Cards adapt from three rows to two and then one without changing their field
  precedence. Tall cards have a one-row black separator; compact cards do not.

## Preserved dormant surfaces

Changed-file context and keyboard help do not need to be exposed by native tabs
immediately. Their pure rendering code, decisions, and tests must remain after
the legacy runtime is removed so a future native overlay or companion surface
can reuse them without redesigning them.

### Changed files

- Only the selected repository supplies branch, dirty counts, and changed-file
  details; inactive cards retain cached repository/worktree identity only.
- Dirty counts stay on the selected card. When at least one file row fits, the
  counts repeat as a colon-terminated heading immediately above the files.
- `bottom` placement centers details in free space below the stable tab stack;
  `inline` placement attaches them below the selected card with matching tree
  indentation. Details never shrink or hide tab cards.
- Fancylog owns status text, color, alignment, and truncation. KTT preserves its
  shared action/path columns and marks only staged entries with `staged`.
- Details compact before disappearing and show at most ten files.

These decisions are guarded by the repository-context cases in
`tests/test_render.py`, including dirty-heading, narrow-card, one-row-capacity,
inline-placement, and bottom-placement coverage.

### Help text

- Help is hidden by default and may be shown transiently or pinned.
- It is centered independently in free space above the tab group and never
  shifts or shrinks the cards.
- Shortcut and action form two aligned columns separated by `│`; both are
  dimmer than card text.
- The edge-style row names the active style, and pinned help labels `?` as
  `unpin help`.

These decisions are guarded by the help and control-legend cases in
`tests/test_render.py`.

Historical rationale and the fuller design remain in `DECISIONS.md` sections 6
and 7. The runtime removal did not delete those decisions, pure renderers, or
their tests.
