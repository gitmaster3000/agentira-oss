# App shell: top bar + collapsible rail

The application chrome — the top bar and the sidebar — is a port of the
`Agentira.dc.html` design file (`design/system/Agentira.dc.html`). The design
moved the shell from "two hard-bordered slabs" to **floating panels on a
gradient canvas**, and made the sidebar collapse to an icon rail.

This document covers what the shell is made of, how the collapse works, and the
two places the implementation knowingly departs from the design file.

## Files

| File | Role |
|---|---|
| `src/components/Layout.jsx` | Shell root — the canvas, the header row, the rail/main row. Owns `railOpen`. |
| `src/components/shell/AppTopbar.jsx` | The blended top bar. |
| `src/components/shell/AppSidebar.jsx` | The collapsible rail. |
| `src/components/shell/shell.css` | The collapse rules (`.railwrap` / `.rail.rc` / `.usermenu`) and hover states. |
| `src/components/shell/shellData.jsx` | One shared query feeding the rail badges, the pulse pill and the Pulse drawer. |
| `src/components/shell/shell.test.jsx` | Unit tests for both rail states and the top-bar switcher. |

## Layout

The root is a **column**: `gap: 12px`, `padding: 12px`, on a near-black canvas
(`#090b10`) with two faint radial gradients washed in from the top corners.

```
┌─ canvas #090b10 + 2 radial gradients ─────────────┐
│  header  (40px, blended — no card, no border)     │
│  ┌────────┐  ┌──────────────────────────────────┐ │
│  │  rail  │  │             main                 │ │
│  │ panel  │  │            panel                 │ │
│  └────────┘  └──────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

The rail and main are **separate floating panels** — each is
`border-radius: 16px`, `border: 1px solid rgba(255,255,255,.07)` with a soft
drop shadow. There are no hard rectangular borders anywhere in the shell; the
old `border-right` / `border-bottom` slab dividers are gone.

The header is deliberately **not** a card. It sits directly on the canvas so the
logo lockup reads as part of the page rather than as chrome.

## Top bar

Left to right:

1. **Logo lockup** — gradient "A" tile + "Acme Inc / Agentira". Always visible,
   clicks through to Home.
2. **Divider** — a 1px, 20px-tall hairline.
3. **Project switcher** — a `PROJECT` caption plus a pill showing the active
   project's colour chip, name, and a live-run badge when that project has runs
   in flight. Opens a `SWITCH PROJECT` dropdown. **This moved out of the
   sidebar** — the rail no longer contains a project picker.
4. **Breadcrumb** — derived from the route (`useBreadcrumb`).
5. **Search pill** — `⌘K` affordance. **Also moved out of the sidebar.**
6. **Pulse pill** — "N running" when runs are live, "Live status" when quiet.
   Toggles the Pulse drawer.
7. **New menu** and **bell**.

## The collapsible rail

Collapse is driven by a single boolean, `railOpen`, held in `Layout` and
toggled by the panel button at the top of the rail. It is passed down as a
prop; `AppSidebar` translates it into the `rc` class.

**`rc` must land on both nodes**, because each drives a different half of the
behaviour:

- `.railwrap.rc` → the **width**: 248px collapses to 66px, animated over
  `.22s cubic-bezier(.4,0,.2,1)`.
- `.rail.rc` → **everything inside**: `.rl` elements (labels and badges) are
  hidden, nav rows centre themselves, the `.plangroup` indent is dropped, and
  the user menu becomes a flyout.

### Expanded (248px)
Full labels, badges, and the section headers rendered as text — `BUILD`,
`PROJECT`.

### Collapsed (66px)
Icons only, centred. Every nav row carries a native `title` tooltip, so the row
is still identifiable when only its icon shows. The section headers stop being
text: `.railhdr` collapses to a thin `border-top` divider with a dimmed
`.hdricon` centred on it (`.hdrlabel` hides, `.hdricon` appears).

Note the labels stay in the DOM when collapsed — CSS hides `.rl`, it isn't
conditionally rendered. Tests assert on the class, not on absence of text.

### User menu
Expanded, it opens **above** the user row. Collapsed, `.rail.rc .usermenu`
flies it **out to the right** of the rail (`left: calc(100% + 6px)`, a fixed
194px wide, items left-aligned) — otherwise it would be clipped to 66px.

## Nav order

Home, Inbox, My Work, Chat → **BUILD**: Agents, Runs, Conductor, Agent
Runtimes, MCP Servers → **PROJECT**: Overview, Board, Backlog, Roadmap,
Workflow, Deploy, Settings. Footer: the user row.

## Two deliberate departures from the design file

Both are cases where following the file exactly would have broken the running
app. They are the only places the port is not literal.

**Templates is omitted.** The design's rail has a `Templates` row between Chat
and the BUILD header. The app has no `/templates` route — the row would render
a dead link that falls through the router's catch-all and bounces the user to
`/`. Add the row when the route lands.

**Deploy is kept.** The design's `PROJECT` group is Overview / Board / Backlog
/ Roadmap / Workflow / Settings — no Deploy. But `/studio/project/:id/deploy`
is a live route with a real page behind it, and the rail is its only entry
point. Dropping the row would orphan it. It sits between Workflow and Settings.

## Mobile

Under 768px the rail becomes an off-canvas drawer, toggled by the hamburger in
the top bar and dismissed by a backdrop; route changes close it (`Layout`).
The drawer always shows labels — if the rail happens to be collapsed, the
mobile rules re-show `.rl` and re-hide `.hdricon`, so you never get a 66px
icon-only drawer. See `docs/mobile-responsive.md`.

## Data

Everything in the chrome is real, from `shellData.jsx`: projects, the per-project
and total running-run counts, the agent count, and unread notifications. There
are no mock rows carried over from the prototype.
