---
id: glossary
title: Glossary
sidebar_label: Glossary
---

# Glossary

**Adapter.** The component inside the daemon that maps Agentira's contract onto one runtime's native features — session resume, streaming, stop.

**Agent.** A configured worker: persona, model, toolkit, permissions. Either managed by Agentira or external.

**Artifact.** A deliverable registered on a run: pull request, commit, file, report, address, or log. Distinct from the conversation transcript.

**Conductor.** The built-in orchestrator agent. Plans projects and, in autonomous mode, dispatches work on a schedule.

**Conversation.** An agent's working memory for one scope. Persists across many runs.

**Daemon.** The process on your machine that receives dispatches, owns Git worktrees, and starts runtimes.

**Definition of done.** A checklist on a task. Tells the agent what finished means and supplies evidence to gates.

**Dispatch.** Sending work from the backend to a daemon.

**Epic.** A grouping of related tasks.

**Evidence provider.** A component that answers one factual question from one trusted source, such as whether a pull request merged.

**Gate.** A check that runs when a task changes column. Blocks the move when required evidence is absent.

**MCP.** Model Context Protocol. The interface agents use to call Agentira tools.

**Outcome.** An agent's declared result: `succeeded`, `failed`, `blocked`, or `needs_input`.

**Run.** An emergent span grouping the turns of one work episode. Carries status, outcome, diff, artifacts, and accounting. Created only when a turn produces work.

**Runtime.** The external tool that edits code — Claude CLI, Codex, Grok, Ollama, and others.

**Sandbox mode.** A declaration of how much of the machine an agent may touch. Configured and logged; not yet enforced per runtime.

**Scope.** The grain of a conversation: `task:<id>`, `chat:project:<id>`, or `chat:default`.

**Service account.** An identity with an API key and no runtime, for external tools calling the API.

**Turn.** One dispatch: a message and the agent's response, sharing one trace identifier. The atomic unit — always durable, always stoppable.

**Work signal.** The rule deciding whether a turn produced real work and should become a run.

**Worktree.** The Git working directory an agent has during a run. Stable per agent and task; recreated per run.
