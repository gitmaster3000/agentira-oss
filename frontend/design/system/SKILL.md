# Agentira Design System — skill

Use this when designing any Agentira surface (the agent workspace product).

## Always
- Link **`styles.css`** for tokens. Never hard-code hex — use the `--surface-*`,
  `--brand-*`, `--text-*`, `--status-*`, `--agent-*` variables.
- **Dark-first.** Background is `--surface-base` (#0e1117). Step UP for cards
  (`--surface-card`), hover (`--surface-hover`), nav (`--surface-nav`).
- **Dense chrome.** Default UI text is 13px; meta is 11px. Page titles 20px.
- **System-UI font** (`--font-sans`) for everything; **mono** (`--font-mono`) only for
  keys, run IDs, branches, code, config.

## The one hard rule
**Pulse blue `#38bdf8` and `.agentira-glow` mean "running" — nothing else.** Don't use them
for hover, selection, primary buttons, or decoration. Primary actions use `--brand-lavender`.

## Color cheatsheet
- Primary action / agent-frontend → `--brand-lavender` `#c9b8ff`
- Secondary brand → `--brand-teal`
- Live / running → `--pulse-blue` + `.agentira-glow`
- Status dots → backlog grey · todo blue · in-progress amber · review purple · done green
- Priority dots → critical red · high orange · medium slate · low grey
- Agent identity → color is **auto-assigned by hashing the agent id** onto `--agent-ring-1…5` (agents are user-created; never tie color to a role). `--agent-conductor` is reserved for the system Conductor only.
- Semantic → `--success / --warning / --danger / --info`

## Components (match these patterns — see guidelines/)
- **Button**: radius `--radius-lg`, 8×16px pad, 13px semibold. Primary=lavender on base;
  secondary=card bg + `--border-strong`; ghost=lavender text.
- **Input**: `--surface-base` bg, `--border-default`, radius `--radius-xl`; focus →
  `--pulse-blue` border + `--ring-focus`.
- **Status pill**: dot + label, `--radius-pill`, tint background.
- **Mono key** (ACM-142, run IDs): `--accent-mono-blue` on `--surface-sunken`, radius `--radius-sm`.
- **Task card**: `--surface-card`, `--radius-xl`; add `.agentira-glow` when an agent is running it.
- **Agent avatar**: round, role color bg, base-color initial.

## Don'ts
- No gradient backgrounds (the brand gradient is for the logo/mark only).
- No emoji in chrome. No filled/duotone icons — stroke icons, ~15px, currentColor.
- Don't invent colors; if you need a new shade, derive it in oklch from an existing token.
- Don't use status colors for agent identity or vice versa.

Reference the product prototype `Agentira.dc.html` for the kit in real use, and
`handoff/COMPONENT_MAP.md` for the React wiring seam.
