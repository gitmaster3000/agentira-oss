QUEUE PLANNING.

## Agents available for auto-dispatch
{{AGENTS}}

## Unassigned todo tasks (need an owner)
{{TASKS}}

Assign each unassigned task to the best-fit agent IN THE SAME PROJECT. Balance load — don't pile everything on one agent; weigh in_flight vs capacity. For each task you assign, call mcp__agentira__update_task with task_id and assignee set to the agent's exact name (optionally also set priority). Only touch the tasks listed above — do not reassign anything else. If a task has no suitable agent in its project, leave it. Be terse; just make the update_task calls.
