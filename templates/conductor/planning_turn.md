QUEUE PLANNING — project {{PROJECT}}.

## Agents available for auto-dispatch (this project only)
{{AGENTS}}

## Backlog — top candidates to promote (team free capacity: {{CAPACITY}})
{{BACKLOG}}

## Unassigned todo tasks (need an owner)
{{TASKS}}

Do two things, in order. Be terse; just make the MCP tool calls.

### 1. Promote backlog → todo

Promote up to **{{CAPACITY}}** tasks from the backlog list above into `todo`,
best candidates first (priority, then whatever else makes a task ready to
work). For each one you promote:

  a. Call `mcp__agentira__update_task` to set `dod_items` to 3-6 concrete,
     checkable Definition-of-Done items. Include **at least one
     product-level check** — something a human can do against the *running
     product* to confirm it actually works (e.g. "open the X page and
     confirm Y appears"), not just "unit tests pass." Also set `assignee`
     to the best-fit agent from the list above.
  b. Call `mcp__agentira__move_task` to move it from `backlog` to `todo`.
  c. Call `mcp__agentira__add_comment` with a one-line rationale for the
     promotion and assignment (traceability — a human should be able to
     see *why* later).

If a promotion is gate-blocked (missing evidence), try to fix it once with
the tools above; if it still can't move, add a comment explaining why and
skip it — do not force it through.

### 2. Assign remaining unassigned todo

For any task still listed under "Unassigned todo tasks", assign it to the
best-fit agent: match **specialty** first (read each agent's specialty
line), then **priority** (critical/high before medium/low), then **balance
load** (in_flight vs capacity — don't pile everything on one agent). Call
`mcp__agentira__update_task` with `assignee` set to the agent's exact name.

### Rules

- Never touch a task that is `in_progress` or `review` — those belong to
  the active worker, not the planner.
- Don't create new tasks in this turn.
- Use each agent's *exact* name when assigning.
- Only act on the tasks listed above.
