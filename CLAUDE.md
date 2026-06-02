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
- New features go in their own `backend/<domain>.py` (or `backend/forge/<domain>.py`), not appended to `services.py`. Functions, not class hierarchies, unless there's a real polymorphism need. See `backend/attachments.py`, `backend/forge/turns.py`, `backend/forge/live_inflight.py`.
- **Prompts are configuration, not code.** Agent system prompts live on `Profile.system_prompt` (edited in Agent Settings UI). Task content lives on `Task.description` (edited in Task UI). Don't hardcode prompt text in dispatch code, and never re-apply a code constant on top of a user-edited row (set-if-empty seeds are the only acceptable shape).

## Products (Flowty umbrella)
- **Flowty Studio** = existing Agentira workspace/tasks (routes: `/`)
- **Flowty Forge** = agent orchestration (routes: `/forge/*`)
- Google-style app switcher between products.
