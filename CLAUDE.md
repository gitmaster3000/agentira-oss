# Agentira / Flowty

## Communication Style
- Maximize token efficiency. Be brief, direct, no filler.
- Lead with action, not explanation.
- Skip preambles, recaps, and "let me" phrases.

## Code Style
- Minimal changes. No unnecessary refactors, comments, or abstractions.
- Test after changes: `cd frontend && npx vite build` for UI, `pytest tests/` for backend.
- Follow existing patterns in the codebase.

## Architecture
- Single DB, modular code boundaries (`backend/forge/` is self-contained).
- Real FKs between modules, no string workarounds.
- Profile stays Profile. Agent = runtime executor. Persona = future role template concept.
- Push+poll hybrid for notifications (ADR-007).

## Products (Flowty umbrella)
- **Flowty Studio** = existing Agentira workspace/tasks (routes: `/`)
- **Flowty Forge** = agent orchestration (routes: `/forge/*`)
- Google-style app switcher between products.
