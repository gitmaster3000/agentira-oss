QUEUE PLANNING.

## Agents available for auto-dispatch
{{AGENTS}}

## Unassigned todo tasks (need an owner)
{{TASKS}}

Assign each unassigned task to the best-fit agent IN THE SAME PROJECT. Match by **specialty** first — read each agent's `specialty` line and route the task to the agent whose skills fit (backend/API work → a backend agent, UI work → a frontend agent, infra/CI → devops, etc.). Then respect **priority** (assign critical/high before medium/low) and **balance load** (weigh in_flight vs capacity — don't pile everything on one agent). For each task you assign, call mcp__agentira__update_task with task_id and assignee set to the agent's exact name (optionally also set priority). Only touch the tasks listed above — do not reassign anything else. If no agent's specialty fits, give it to the least-loaded capable agent. Be terse; just make the update_task calls.
