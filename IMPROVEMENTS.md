# ktt improvements

This is the prioritized follow-up backlog. `VISION.md` describes the product
direction and `DECISIONS.md` records settled choices; this file tracks work that
is desirable but not required for the current prototype.

## Current status contract

ktt does not infer agent state from a tab title. Status flows through one Kitty
user variable:

```text
agent lifecycle hook
  -> workmux set-window-status working|waiting|done
  -> Kitty workmux_status=<configured icon>
  -> Kitty tab_bar.py and ktt both render that same value

agent records ready_to_merge|blocked
  -> agent-tab.py leaves a per-window pending verdict
  -> the Stop hook writes that verdict to Kitty workmux_status
  -> Kitty tab_bar.py and ktt both render that same value
```

With the current configuration, workmux's lifecycle icons are `🤖` for working,
`💬` for waiting, and `✅` for done. `ready_to_merge` and `blocked` remain semantic
strings. ktt reads `workmux_status` from the `user_vars` in `kitten @ ls`; title
cleanup only removes agent spinner/title decoration and never determines state.

There is no duplicated status detection inside ktt. There is duplicated policy
and some duplicated runtime writing:

- `ktt/render.py` and Kitty's `tab_bar.py` separately define status icons,
  spinner frames, verdict colors, and title cleanup.
- The installed agent hooks can call `workmux set-window-status` and then
  `agent-tab.py` can mirror the same lifecycle state into Kitty again.
- Workmux stores semantic lifecycle state internally, but its Kitty backend
  writes the configured display icon into `workmux_status`; consumers therefore
  depend on both semantic verdict strings and icon values.

Changing this safely crosses the workmux binary, Codex and Claude hook
configuration, `agent-tab.py`, Kitty's embedded renderer, and ktt. Keep the
current compatible behavior until the contract below can be migrated end to
end.

### External systems are black-box dependencies

#### Workmux

ktt must not read workmux's private state files, depend on its Rust types, vendor
its source, or patch the installed binary. The supported boundary is:

- agent hooks call documented workmux CLI commands;
- workmux projects status into Kitty user variables;
- ktt reads those variables from Kitty's public remote-control snapshot.

Any improvement requiring new workmux behavior is an upstream/API request, not
an implementation task in this repository. Until that API exists, retain the
`/tmp` pending-verdict bridge rather than reaching into workmux internals.

#### Codex

Treat Codex itself as an external product. Do not modify, build, vendor, patch,
or depend on its source or private implementation details from ktt. Previous
attempts in other sessions to solve integration problems by modifying Codex
source are explicitly out of scope.

The permitted boundary is documented Codex configuration and hook behavior,
documented environment/context supplied to those hooks, and observable CLI
behavior. Agent-status adapters may run from configured lifecycle hooks, but
their implementation belongs outside Codex and must tolerate missing context or
unsupported environments without failing an agent turn.

If ktt needs behavior Codex does not expose publicly, record the capability as
an upstream product/API request. Prefer an external adapter or a workmux-owned
bridge; do not inspect or change Codex internals as a workaround. ktt continues
to consume only the resulting Kitty user-variable projection.

## Completed foundation: integrate parent edges at launch time

The yadm-managed Workmux configuration now calls `assign-parent` from both
configured agent wrappers. It resolves the prompt's exact coordinator handle
to the sole status-bearing Kitty window in that same repository and writes its
ID as `ktt_parent_window_id` on the child. Every generation uses its immediate
parent rather than the tree root.

This activates the hierarchy already implemented in ktt without modifying the
Workmux source or binary. ktt, the local Kitty tab renderer, and the configured
agent wrappers have retired family metadata after controlled live smoke tests.
Plain `workmux add` calls without a `Coordinator: HANDLE` contract remain
independent roots.

The smoke test created a root, child, grandchild, and sibling as temporary Kitty
tabs, verified every exact parent variable, and observed multi-level indentation
in the running sidebar. Tree order correctly follows Kitty's current tab order;
because `--location=after` inserts immediately after its source, a later sibling
can precede an earlier sibling without violating the hierarchy. All fixture tabs
were then closed by their exact returned window IDs.

### One hierarchy ground truth

`ktt_parent_window_id` is the single source of truth. ktt does not parse
`workmux_family`, and new integration work must not dual-write or fall back to
that legacy relationship label.

Kitty's local horizontal renderer now derives a color key from each tab's tree
root:

1. Build a map from every Kitty terminal-window ID to its containing tab.
2. Resolve each tab's immediate parent through `ktt_parent_window_id`.
3. Follow parent edges with cycle protection and cache the resulting root key.
4. Hash that root key through the existing family-color palette.
5. Treat an orphan or cycle as a new root rather than hiding or looping.

Rebuild the map only when tabs or `ktt_parent_window_id` values change. That is
`O(tabs + edges)` per topology change, while animated tab-bar repaints remain an
`O(1)` cached lookup per tab. Do not walk the full tree independently from every
`draw_title` call; that would turn spinner repaint into avoidable quadratic work.

The local cutover is complete:

1. ktt ignores `workmux_family` and renders only parent edges.
2. Kitty colors parent-linked components from the cached graph, leaves
   independent roots unmarked, and ignores `workmux_family`.
3. Configured Workmux wrappers set the exact parent edge and contain no family
   assignment or compatibility write.
4. Relaunch existing tabs when their old family coloring matters; untagged tabs
   remain valid independent roots until then.

The first three steps are implemented and live-tested. Workmux and Codex remain
external black boxes; all integration stays in supported configuration and
wrapper processes outside their source and binaries.

With parent-only state, closing an ancestor makes its surviving descendants
orphans; they become independent roots and may change color. Preserving the old
color after the root disappears would require redundant durable family/root
metadata, which conflicts with the single-ground-truth goal. Accept orphan
promotion unless real usage demonstrates a need for explicit reparenting.

## 2. Establish one semantic status API and one writer

Request a documented workmux interface that owns lifecycle transitions, pending
verdicts, and Kitty mirroring. The conceptual capabilities—not prescribed
command names—are:

1. Record a window-scoped pending `ready_to_merge` or `blocked` verdict through
   the same sandbox-to-host routing already used for status updates.
2. Finish a turn atomically: persist `done`, promote a pending verdict when one
   exists, publish exactly one Kitty update, and retire the pending value.
3. Clear stale pending state when the next turn starts or its window disappears.
4. Publish semantic Kitty values—`working`, `waiting`, `done`,
   `ready_to_merge`, and `blocked`—through a versioned contract.
5. Keep repeated Stop events and retries idempotent for an exact window identity.

Once workmux exposes those capabilities, `agent-tab.py` can call them instead
of writing `/tmp` files or Kitty variables directly. ktt still talks only to
Kitty and does not gain a runtime dependency on the workmux CLI or state store.

Store semantic values—`working`, `waiting`, `done`, `ready_to_merge`, and
`blocked`—in `workmux_status`; renderers choose glyphs. During migration,
consumers must continue accepting the current `🤖`, `💬`, and `✅` values.

Remove duplicate hook entries only after tests prove each agent event produces
one state-store update and one Kitty user-variable update.

## 3. Share status presentation policy

Move normalized status names, spinner frames, verdict colors, and title-cleaning
rules into one small compatibility module or generated data file consumed by
both ktt and Kitty's `tab_bar.py`.

The boundary must account for Kitty loading its renderer with an embedded Python
environment while ktt is an independently installed application. Do not make
ktt depend on a particular home-directory layout; a versioned data contract is
preferable to importing personal configuration directly.

## 4. Reduce idle CPU and subprocess churn

Render only when Kitty state, input, terminal size, or the visible spinner frame
changes. Stop redrawing at 20 Hz when no working status is visible. Use adaptive
polling: fast after interaction, slower while idle.

After measuring that change, consider speaking Kitty's remote-control protocol
directly over the existing Unix socket instead of spawning `kitten @ ls` twice
per second. A Kitty watcher/event bridge can later make polling a recovery path.

The active-repository panel adds one bounded Git status subprocess every three
seconds, only for the active tab. Include it in idle measurements. If it is
material, refresh from filesystem/Kitty events or share a structured metadata
provider with fancylog rather than increasing the polling interval blindly.

Target: below 0.3% of one CPU core while idle, measured with short-lived child
processes included.

## 5. Enrich adaptive multi-line tab cards

Adaptive density is implemented: three-line cards are used when the whole tree
fits, two-line cards when space is tighter, and one-line cards as the compact
fallback. Every colored card row maps to the same mouse target. One black row
separates tall cards and disappears in compact mode, while verdict glyphs
repeat vertically to form a continuous flame or exhaust edge.

Repository, directory, branch, upstream divergence, and worktree state now use
otherwise-empty padding above the tree. This gives the active tab ambient
context without consuming card rows. A later card-specific expansion can still
show repository/branch for several tabs at once, plus agent phase and the
latest readiness or blocker reason. Add yadm and unusual bare-repository
discovery only through a bounded metadata provider; conventional and linked Git
worktrees are the current supported paths.

Edge comparison is now live rather than a static
mockup: `tapered`, `stacked`, `straight`, `rounded`, and `wedge` are selectable
at startup and cycle in-place with `e`. Tapered remains the default, while the
other styles stay available as themes instead of being discarded after the
visual experiment.

Choose density deterministically from terminal height and visible-tab count so
resizing does not flicker between modes. Consider persistence for fold state
only after the interaction model is stable; local fold state remains the
current default.
