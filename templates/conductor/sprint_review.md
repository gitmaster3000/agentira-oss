SPRINT REVIEW — project {{PROJECT}}, last 24h.

## Outcomes
- Done: {{DONE_COUNT}}
- Failed: {{FAILED_COUNT}}
- Blocked: {{BLOCKED_COUNT}}
- Needs input: {{NEEDS_INPUT_COUNT}}
- Still in flight: {{IN_FLIGHT_COUNT}}
- Cost: ${{COST_USD}}
- Bounce / escalation comments: {{BOUNCE_ESCALATION_COUNT}}

## Shipped
{{DONE_TASKS}}

## Failed / stalled
{{FAILED_TASKS}}

Write a short, honest, human-readable review of this project's last 24
hours: what shipped, what failed and why, and any systemic issue (repeated
failure pattern, a gate that keeps bouncing, an agent stuck on the same
class of problem). Be terse — a few sentences per section, not an essay.

Then:

1. For each systemic issue you find, call `mcp__agentira__create_task` to
   add a corrective task to the backlog. Give it a description that
   suggests a verification-shaped Definition of Done (what a human — or
   the next agent — checks to confirm the fix actually worked).
2. Publish the review itself as a task so the human reads it on the board:
   call `mcp__agentira__create_task` with `title="Sprint review <today's
   ISO date>"`, `tags=["sprint-review"]`, `status="done"`, and
   `description` set to the review text you just wrote.

Only act on this project's tasks. Don't reassign or restart anything —
this turn is a retro, not a dispatch.
