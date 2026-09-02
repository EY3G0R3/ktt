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
- Every card shows repository identity before other labels. Tall cards place
  repository/worktree/state on the middle row and useful branch/title on the
  bottom row, omitting redundant labels.
- Active, active-descendant, working, waiting, ready, and blocked treatments
  retain the established colors, brightness, caps, and attention debounce.
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
