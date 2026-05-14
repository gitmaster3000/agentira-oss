# Agentira Release Roadmap

> Drafted at 4 AM, 2026-05-07. Captures one day of platform work + the
> path to public release. Not a marketing doc — a shipping plan.

## Today's haul (one day, 19 hours)

Started: broken chat. Ended: real platform with CI-gated PRs.

10 PRs shipped:

1. **Trigger rail** — one code path for chat + runs
2. **Workflow template schema** + canonical production-readiness example
3. **Docker dev / qa / prod** running side-by-side, JWT stable per env
4. **AGENTIRA_VISION.md in repo**
5. **CI gating on every PR** — unit + compose-validate + integration smoke
6. **Run-failure notifications** + working bell + inbox
7. **Dialect-aware migrations** (SQLite + Postgres)
8. **Task-runs MVP** — schedule a run on a task, see the conversation stream back
9. **Cancel / Pause / Resume / Stop** controls on active runs
10. **Errors surfaced inline** in chat — no more silent fails

Plus: backlog cleanup (5 deletes, 30 tasks linked to 8 epics), Mac-native
font, EpicPage with rename/delete, project CRUD in nav, Vite hot reload
in docker, parallel-env compose with project scoping.

---

## The four projects under Agentira's wing

| Project | What it becomes | Release shape |
|---|---|---|
| **Agentira** itself | The platform | Flagship — release when Step 7 (Auditor + Planner agents) ships an end-to-end "vibe → prod" demo on a real repo |
| **EasyNote** | AI-native Android note app; legacy preserved | Case study: "EasyNote 1.0 (2015 Java) → EasyNote 2.0 (Kotlin / Compose + LLM features) — done by Agentira" |
| **VoiceCode** | Cross-platform agentic IDE for blind / deaf / motor-disabled developers | **Highest-meaning release.** Real product, real underserved market, real social-good narrative. Public as its own story: "built and modernized via Agentira." |
| **RecordRTC** | Modernized fork (TS / ESM, AI-friendly transcript hooks) | Smallest, fastest. Pairs with VoiceCode. First proof: "8-year-dormant fork → production-grade in N days." |

---

## Release order (only after Auditor agent ships)

1. **Privyr** (or one chosen dogfood) — first. Run it through Agentira. Capture before/after audit scores.
2. **VoiceCode** — public flagship. Press-friendly: indie hacker / accessibility blogs / potential HN front page if framed right. Story: humans + Agentira agents, for accessibility.
3. **EasyNote** — second case study. "Here's the 2015 Java version. Here's the 2026 AI-native version. The work between them: Agentira."
4. **RecordRTC** — quiet release. PR back to upstream OR maintained fork with a clear "why" README. Engineer audience.
5. **Agentira** itself — public only when 3 case studies exist + 1 paying user (or 5 second-time users).

---

## Release surfaces (per project)

- **Open source repos with READMEs that tell the story** — anyone can read and verify the work
- **A landing page** for VoiceCode, EasyNote, Agentira — buyers don't read READMEs
- **A blog post + Loom per case study** — "here's exactly what Agentira did, with timestamps"
- **One curated tweet thread per case study** — for distribution
- **No HN until** 3 case studies AND 1 paying user (or 5 second-time users) exist

---

## What "ahead of competitors" means here

Competitors race on **engineering-agent orchestration polish**:
- inbox UX, sub-issue prefill, agent-card layout, CLI subcommands

Their PRs prove they're not chasing the same wedge. They're refining
their product.

Agentira's wedge: **vibe-to-prod**. Take a half-broken side project,
audit it, plan remediation, fix every issue with verified evidence,
deploy to production. None of the loud competitors are chasing this.

The competition for stars / GitHub follows is **noise**. Measure on:
"does the next person who tries Agentira get to a deployed app from a
vibe-coded repo?" When yes, go public.

---

## Sleep target

8:50 AM. Set the alarm. The platform doesn't move tonight; it can wait.
