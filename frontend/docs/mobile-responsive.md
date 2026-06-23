# Mobile responsiveness (AP-310)

First pass at making the app usable on phones. Scope is "mobile friendly for
now" — a native app comes later. Breakpoint is Tailwind's `md` (768px): at or
below that width the chrome switches to its mobile layout.

## What changed

### Off-canvas sidebar (`AppSidebar` + `Layout` + `AppTopbar`)
On desktop the 248px left rail is unchanged. On `≤768px` it becomes a drawer:

- A **hamburger** button appears at the left of the topbar (`.shell-hamburger`,
  hidden on desktop via CSS).
- Tapping it toggles `navOpen` state in `Layout`, which slides the sidebar in
  over the content (`.shell-sidebar--open`) and shows a dimming **backdrop**.
- The drawer closes on backdrop tap **and** automatically on any route change
  (project switch, nav click) — `Layout` watches `location.pathname`.

All of the drawer behaviour lives in `src/components/shell/shell.css` under the
`@media (max-width: 768px)` block; the JSX only toggles a class. The sidebar's
inline styles (width, colours) are untouched, so desktop is byte-for-byte the
same.

### Chat page single-pane (`pages/Chat.jsx`)
The two-pane (agent rail + thread) layout doesn't fit a phone. On mobile it's
now single-pane, driven by `mobilePane` state:

- Default shows the **agent list** full-width.
- Picking an agent/conversation shows the **thread** full-width.
- A **back arrow** (`md:hidden`) in the thread header returns to the list.

Desktop (`md+`) still shows both panes side by side — the responsive classes
(`w-full md:w-72`, `hidden md:flex`) collapse to the original layout above the
breakpoint.

### Floating chat dock (`components/FloatingChat.jsx`)
The 380×520 panel is larger than a small phone screen, which let it anchor
partly off-screen. It now shrinks to `min(size, viewport − 8px)` so it always
fits and stays draggable within bounds.

## Manual test checklist

Use browser devtools device toolbar (e.g. iPhone SE, 375px) or a real phone:

- [ ] Topbar shows a hamburger; tapping it slides the sidebar in with a backdrop.
- [ ] Tapping the backdrop, or a nav item, closes the drawer.
- [ ] Desktop (≥769px) shows the static sidebar and **no** hamburger.
- [ ] Chat page: agent list is full-width; tapping an agent opens the thread;
      the back arrow returns to the list.
- [ ] Floating chat button and panel stay fully on-screen on a 375px viewport.

## Not covered (follow-ups)

- The Kanban **Board** still scrolls horizontally on mobile (expected for a
  column board, but a stacked/swipe view would be nicer).
- Dense data tables/dashboards in Forge were not reworked — they scroll.
