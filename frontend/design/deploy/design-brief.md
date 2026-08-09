# Design Brief — Agentira Deploy

## For the designer

Design the **Deploy** experience for Agentira: a per-project tab where a user watches their app go live and tests it, without ever touching a terminal. The bar is the **Lovable / Vercel / AI-Studio out-of-box feeling**: connect a provider once, then it just deploys and you can see and click your running app.

**Use the imported Agentira design system as the source of truth** (`design/agentira-zip/` — colors, type, spacing, component styles). Everything below fills gaps; it never overrides the system. Match the existing app sidebar, cards, pills, and buttons already used across Overview / Board / Backlog / Roadmap / Workflow / Settings — Deploy is a new sibling tab, not a new visual world.

## What Agentira is (one line, for grounding)

Agentira runs autonomous agents that build software. Each managed project is a real git repo with its own `main`. Deploy is where the human sees the *result* of that work running live, and tests it.

## Who it's for & the job

- **User:** a founder/PM/engineer who owns the project. Not necessarily infra-savvy.
- **Job:** "Is the thing the agents built actually running? Let me open it. Let me see this branch before it merges. If it broke, tell me why."

## The core flow (design for this happy path first)

1. **Connect once.** Paste a cloud provider API key (Railway first). It's verified with a quiet probe. Pick which repo/service to connect. Hit **Connect**. Done — never asked again.
2. **Main goes live automatically.** Every push to the project's `main` redeploys. The user just watches the status turn green and clicks the live URL.
3. **Preview a branch on demand.** For any active branch, a **Preview this branch** button spins up a throwaway preview the user can open *inside Agentira* to test before merge.

## Screens & states to design

### 1. Empty / not-connected state
No provider connected yet. This is the first thing most users see — make it inviting, not a dead form. One clear value prop + a single primary CTA (**Connect a deployment provider**). Show which providers are supported (Railway now; GCP/Docker shaped the same, "coming"). Avoid an intimidating wall of fields.

### 2. Connect flow
Minimal. Paste API key → live verify state (checking / valid / invalid, never echo the key back) → pick repo/service → Connect. This is the whole setup. Design the inline verify feedback and the invalid-key error clearly (what went wrong, how to fix).

### 3. Connected — the Deploy home
Two zones:

- **Live (main) card** — the hero of this page. Shows:
  - status pill (see states below)
  - the **live URL**, prominent and clickable, ideally with an **embedded preview/iframe** so the user tests the app *without leaving Agentira*
  - current commit (short SHA + message), who/what triggered it
  - **Redeploy** action
  - a **"why / what's happening" line** when building or failed (e.g. "Building — step 2/4" / "Failed: build error, view logs") — transparency is a first-class requirement, not a tooltip afterthought.

- **Branch deployments** — a list below the Live card. Each row: branch name, last commit, status, a **Preview this branch** button (or open-preview if already live), teardown/stop for previews. Keep it scannable — many branches possible.

### 4. Deployment detail / logs
Opening a deployment shows build/runtime **logs** (streamed/proxied), status timeline, commit, URL. This is where a user goes when something's red. Logs must be readable, scrollable in their own container, copyable.

### 5. Provider / settings affordance
Where the connected provider shows (name, connected repo, key status = valid/last-checked), and where you'd disconnect or reconnect. Small, secondary — not competing with the Live card.

## Deployment status states (design a distinct, legible pill for each)

`queued` · `building` · `live` · `failed` · `crashed` · `stopped` (preview torn down)

Encode state in **form + color**, not color alone (pill shape/icon + label). Semantic colors (good/warning/critical) are separate from the app accent. While anything is `queued`/`building`, the page polls every ~5–10s — design the in-progress state to feel alive (subtle activity, not a frozen spinner).

## Data to surface per deployment

status · live/preview URL · commit SHA + message · branch · is-main · trigger (push / manual / preview) · updated-at (relative) · target provider · logs link.

## Transparency (explicit requirement)

Agentira's whole ethos is "no black boxes." A deployment must never just silently change color. Always show **what's happening and why** — building step, failure reason, "redeployed by push from agent X", "preview torn down after N hours". Make cause a visible line on the card, not hidden.

## Empty / edge / error states to cover

- No provider connected (screen 1).
- Provider connected, but no deploy has ever run (main not deployed yet).
- Invalid / expired API key.
- Provider needs repo access grant (e.g. one-time "grant Railway access to this repo" link — a real GitHub-App step, not skippable).
- Build failed / app crashed (with a direct path to logs).
- Preview limit / many branches (keep the list sane).

## Tone

Confident, calm, "it just works." This is the payoff moment — the user sees their app *alive*. Lovable/Vercel calm, not enterprise-dashboard busy. The Live URL and the running app are the stars; everything else is quiet chrome around them.

## Out of scope (don't design)

- Agentira-hosted zero-key default (BYO key only for this build).
- Automatic per-PR previews (previews are on-demand button only).
- Multi-region / scaling / infra config knobs.

## Deliverable

High-fidelity designs for: the not-connected empty state, the connect flow, the connected Deploy home (Live card + branch list), a deployment detail/logs view, and the full set of status pills — in light and dark, using the Agentira design system.
