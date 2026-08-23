# Agent cockpit design

## Requirements

The primary agent terminal should remain near the physical center of a wide
display so sustained work does not require turning toward either edge.

The visible workspace for an agent should include:

- the agent terminal as the dominant, centered surface;
- a live commit graph, currently provided by `fancylog --watch --`;
- a scratch terminal in the agent's worktree for quick edits, tests, and
  commands;
- the global tab tree and agent statuses in peripheral vision, with attention
  states visually prominent;
- an unmistakable clean/dirty working-tree indication; and
- changed files when space permits.

Dunst notifications may move to a less disruptive edge if that improves the
composition. They should not cover the central agent surface.

Switching agents must switch the entire associated set: agent terminal,
commit graph, scratch terminal, repository state, and the active indication in
the tab tree. Navigation follows ktt's visible tree order rather than Kitty's
underlying tab insertion order.

The design must avoid application-specific geometry in dwm. Workmux and Codex
remain black boxes; integration should use their supported configuration,
hooks, environment, Kitty metadata, and process boundaries rather than source
changes.

## Recommended design: balanced Kitty cockpit

One Kitty tab is the atomic cockpit for one agent. A nested `splits` layout
places equal-width context rails around the centered agent and gives horizontal
ktt a shallow full-width pane at the bottom:

```text
┌────────────────────┬──────────────────────────────┬────────────────────┐
│                    │                              │                    │
│     FANCYLOG       │            AGENT             │   SCRATCH SHELL    │
│                    │                              │                    │
│ commit graph       │ primary prompts and coding   │ tests and edits    │
│ changed files      │                              │ builds and commands│
│ repository state   │                              │                    │
│                    │                              │                    │
├────────────────────┴──────────────────────────────┴────────────────────┤
│ root agent          sibling agent             another agent           │
│    └ child agent       └ blocked agent           └ ready agent         │
│                                             optional ktt controls/help │
└────────────────────────────────────────────────────────────────────────┘
```

On a 3440-pixel-wide display, an initial split of approximately 21% / 58% /
21% keeps the agent's center at the display's physical center. Horizontal ktt
starts at four to eight terminal rows and compresses before taking more height
from the agent. Dunst belongs at the upper-right over the scratch terminal.

Kitty performs the whole-cockpit switch natively because all companion windows
are siblings in the same tab. Dwm sees one ordinary Kitty OS window and needs
no ktt-specific rules or layout behavior.

## Alternative A: vertical status rail

```text
┌────────────────────┬──────────────────────────────┬────────────────────┐
│                    │                              │   SCRATCH SHELL    │
│     FANCYLOG       │            AGENT             ├────────────────────┤
│ commit graph       │                              │   VERTICAL KTT     │
│ changed files      │                              │   tab tree         │
│ repository state   │                              │   attention states │
└────────────────────┴──────────────────────────────┴────────────────────┘
```

This preserves full agent height and suits deep trees, but places attention
farther from the prompt and requires more deliberate gaze movement.

## Alternative B: minimal native ribbon

```text
┌────────────────────┬──────────────────────────────┬────────────────────┐
│     FANCYLOG       │            AGENT             │   SCRATCH SHELL    │
│                    │                              │                    │
├────────────────────┴──────────────────────────────┴────────────────────┤
│ working · question · blocked · ready · working tree clean             │
└────────────────────────────────────────────────────────────────────────┘
```

Kitty's native tab bar is always one cell high, including custom renderers, so
it can provide a compact fallback or focus mode but cannot contain ktt's
multi-row tree. A shortcut could open the full tree as an overlay or restore
the embedded pane.

## Runtime architecture

The first prototype runs horizontal ktt as an ordinary Kitty window in the
bottom split of the current tab. This solves sizing inside Kitty and avoids a
second top-level OS window.

### Reversibility is a product requirement

The horizontal cockpit is an experiment, not a migration away from vertical
ktt. Both orientations remain first-class views over the same tree, status,
fold, and navigation state. Neither renderer may become the other's source of
truth, and horizontal-only metadata must not enter the tab hierarchy contract.

Returning to the vertical sidebar must be a single command or keyboard action.
The switch should remove or hide only ktt's current presentation surface,
restore the alternate surface, preserve folds and active-tab identity, and
leave the agent, fancylog, and scratch-shell processes untouched. It must not
require manually rebuilding Kitty splits or changing dwm source/configuration.

The intended interaction is an orientation toggle with two named profiles:

- `horizontal cockpit`: a shallow embedded pane with the native tab bar hidden;
- `vertical sidebar`: the established separate sidebar with the embedded pane
  absent and the main cockpit using the recovered vertical space.

Exact command and key names remain an implementation decision. Prefer one
idempotent `set-view horizontal|vertical` operation plus a shortcut that toggles
between them; this is easier to automate and recover than a sequence of window
creation and closing commands.

The mature version should query Kitty once per OS window. A shared ktt state
service consumes watcher events and recovery polling, while small render
clients in cockpit tabs display the latest frame. Hidden clients remain
dormant. This prevents one complete Kitty polling loop per agent cockpit.

Fancylog remains the repository authority for Git, linked worktrees, yadm,
branch, graph, and file status. Ktt owns tab hierarchy, agent attention state,
folds, and navigation. Repository information shown by ktt should be supplied
by fancylog rather than independently derived.

The horizontal ktt pane does not repeat Fancylog's repository footer. Its
limited height belongs to the tab tree; repository state and changed files stay
in the dedicated Fancylog rail. Vertical ktt may continue using otherwise-empty
padding for the compact Fancylog status block.

Each Kitty window in a cockpit should eventually have an explicit role such as
`agent`, `fancylog`, `shell`, or `ktt`. Tab-level status and ancestry are read
from the designated agent window, so focusing the scratch shell cannot hide
the agent's status or change the cockpit identity.

## Prototype sequence

1. Build one cockpit tab manually with a fixed-height horizontal ktt split.
2. Validate physical centering, useful ktt height, clicks, folds, and tree-order
   navigation.
3. Add a cockpit launcher outside Workmux source using supported configuration
   and hooks.
4. Measure background cost with several cockpits before introducing the shared
   ktt state service.
5. Add and live-test the idempotent horizontal/vertical view switch before
   treating either layout as a default.
