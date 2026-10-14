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

## Work and Build

The app has two areas, switched from the top bar. **Work** (everything outside
`/forge/*`) renders full width with **no sidebar**. **Build** (`/forge/*`) keeps
the sidebar. `Layout` decides with `pathname.startsWith('/forge')`.

## Top bar

Per `home-dashboard.html`, left to right: **logo** (to Home), **Work | Build**
switch, spacer, **search** (⌘K), **New** menu, **bell**, **avatar**. Nothing
else — no project switcher, no breadcrumb, no "N running" chip. The bar is one
40px row flush with the page edges. Below 768px the hamburger (Build only) opens
the sidebar drawer, and the wordmark, search and bell are hidden
(`.shell-hide-sm`) so logo, switch, New and avatar fit at 375px.

- **New menu** — Task, Project, Epic, Milestone, divider, Agent. Each opens the
  existing create flow: Task/Epic fire `open-create-task` / `open-create-epic`
  inside a project, otherwise navigate to the active project's board with route
  state `{ create }` that `ProjectLayout` reads; Milestone goes to the roadmap
  with `{ create: 'milestone' }`; Agent goes to `/forge/agents` with
  `{ create: 'agent' }`; Project opens the wizard.
- **Avatar menu** — Inbox, My Work, Chat, Settings, Sign out.
- **Project identity** lives only in the project page header: a
  `Home / Project name` breadcrumb, the title, members, then the tabs. Switch
  projects from Home or with search / ⌘K.

The project board toolbar has a **New task** button (opens the same task modal).

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

## Nav order

**BUILD** only: Agents, Runs, Conductor, Agent Runtimes, MCP Servers. No
footer — the user menu is the top-bar avatar.

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
