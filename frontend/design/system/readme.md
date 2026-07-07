# Agentira Design System

The product language for Agentira — a workspace for orchestrating coding agents.
Dark-first, dense, and built so that **one accent (Pulse blue `#38bdf8`) means exactly
one thing: work that is live and running right now.**

Open **`Design System.html`** for the browsable overview, or the **Design System tab**
for the specimen cards.

---

## Context

Agentira is an agent workspace: a board of tasks, agents that pick them up, and runs that
execute. The UI is information-dense product chrome — closer to a code host or an IDE than
a marketing site. The system optimizes for: scanning many rows fast, telling idle from live
at a glance, and giving each agent a stable identity color.

**Three rules that hold the whole thing together**

1. **Surfaces carry depth, color carries meaning.** The six-step dark surface ramp
   (`sunken → hover`) does the structural work. Saturated color is reserved for status and brand.
2. **One accent for "live."** Pulse blue and the rotating `.agentira-glow` border are *only*
   ever used for actively-running work. Never decorative.
3. **Agent identity is separate from status.** Each agent role has a fixed hash color
   (Planner amber, Backend cyan, Frontend lavender…) that is independent of task status.

---

## Visual foundations

| Token group | File | Notes |
|---|---|---|
| Color | `tokens/colors.css` | 6 surfaces, lavender+teal brand, Pulse blue, semantic, status, priority, agent identity |
| Type | `tokens/typography.css` | `--font-sans` (system UI) for chrome, `--font-mono` for keys/code. Scale 9→36px |
| Spacing & radius | `tokens/spacing.css` | 4px base rhythm; radii 2→12px + pill; layout dims |
| Elevation & glow | `tokens/elevation.css` | Border-led depth, shadows, focus ring, the live `.agentira-glow` |
| Base | `tokens/base.css` | Reset, scrollbars, selection, mono utility |

Density: product chrome lives at **11–14px**. Page titles 20px, dashboard greeting 28px.
Hit targets: `--control-sm/md/lg` = 28/34/40px.

## Color in one paragraph

The app sits on `--surface-base` (#0e1117). Cards and rows step up through `--surface-card`
and `--surface-hover`. Brand lavender is the primary action / agent-frontend identity; teal is
the secondary brand. Status uses dot-pills (backlog grey → todo blue → in-progress amber →
review purple → done green). Priority is a separate dot scale (critical red → low grey).
Pulse blue is never used for anything that isn't running.

## Iconography

Stroke icons, 1.5–2px, `currentColor`, ~15px in chrome. No filled/duotone icon sets.
Status and priority read as **dots**, not icons.

---

## How to consume

Link the single entry point — it `@import`s every token file:

```html
<link rel="stylesheet" href="styles.css">
```

Then build with the CSS variables (never hard-code hex):

```html
<button style="background:var(--brand-lavender);color:var(--surface-base)">New task</button>
<div class="card agentira-glow">…live run…</div>
```

---

## Index

- **`Design System.html`** — browsable overview (start here)
- **`styles.css`** — the only file consumers link
- **`tokens/`** — source of truth (colors, typography, spacing, elevation, base)
- **`guidelines/`** — specimen cards (one `@dsCard` each, shown in the Design System tab)
- **`assets/`** — `logo-mark.svg`, `logo-wordmark.svg`
- **`Agentira.dc.html`** — the product prototype, the kit in real use
- **`handoff/`** — `COMPONENT_MAP.md` (prototype → React seam) + `agentira.types.ts`
