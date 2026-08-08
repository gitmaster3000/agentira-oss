# Theming — Day / Night

Agentira ships two looks: **Night** (the original dark chrome, the default) and
**Day** (light). Users pick one in **their name → Settings → Appearance**. The
choice is stored per device in `localStorage` under `theme` and applied before
the app renders, so there is no flash of the wrong theme on reload.

## How it works

One palette, two value sets. Every colour is a CSS custom property defined in
`src/tokens/colors.css`:

- `:root` holds the Night values.
- `:root[data-theme="light"]` re-declares the same token names with Day values.

Switching themes only sets `<html data-theme="light|dark">` — nothing re-renders
for colour. `src/lib/theme.js` owns that: `getTheme()`, `setTheme()`,
`toggleTheme()`, `applyStoredTheme()` (called once in `main.jsx`) and
`subscribeTheme()` so any widget showing the current theme stays in sync.

`src/tokens/compat.css` maps the older chrome variable names (`--bg-app`,
`--border-subtle`, `--accent-primary`, …) onto those tokens, so Tailwind classes
like `bg-bg-card` follow the theme too.

## Rules for new UI

- **Never hardcode a hex.** Use a token: `var(--surface-card)`,
  `var(--border-default)`, `var(--text-muted)`, `var(--brand-lavender)`, …
- For hairlines and tints drawn *on top of* a surface, use the overlay tokens
  (`--overlay-line`, `--overlay-line-strong`, `--overlay-tint`,
  `--overlay-tint-soft`) instead of `rgba(255,255,255,…)` — white overlays
  disappear on a white background.
- Adding a colour means adding it to **both** blocks in `colors.css`.

## Known gap

The Deploy tab (`src/components/deploy/theme.js`) is a dark-only design port
with its own palette constants and does not follow the Day theme yet.
