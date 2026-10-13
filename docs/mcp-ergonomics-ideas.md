# MCP ergonomics — ideas log (Conductor, agentic-layer program)

Measured 2026-09-30 while seeding AP-541..AP-591 (154 calls, 94 KB responses, ~9 s).
Source: AP-591 attachment `mcp-ideas.md`. Status column links each idea to its follow-up task.

1. **get_roadmap is 380 KB** for one project (535 tasks). Add filters: `epic_ids`, `tag`, `milestone_id`, `status`, `fields=compact` (id,key,title,status,start,due,blocked_by). Default to open work only. — **AP-597**
2. **list_epics is 54 KB** — returns full markdown descriptions. Add `compact=true` (id,title,status,task_count) and `status` filter; exclude done/superseded by default. — **AP-598**
3. **No batch writes.** Seeding needed 51 create_task + 98 add_dependency calls. Add `create_tasks([...])` with client-side refs (`ref`, `depends_on_refs`) so a whole plan lands in one call, atomically. — **AP-599**
4. **Write responses echo the full object.** create_task/add_dependency return the whole row; return `{id,key}` by default, full object on `verbose=true`. — **AP-600**
5. **Epic dates are not first-class.** Roadmap epics show start/due=None; derive from children or allow setting them, so the Gantt shows epic bars. — not scheduled
6. **create_task returns `key`** — good; list/roadmap should accept keys (AP-561) anywhere an id is accepted. — folded into **AP-597**
7. **Session disconnects are silent to agents:** after stack restart the client stays ECONNREFUSED until manual /mcp reconnect. Consider a health/retry hint in docs. — not scheduled
8. **No tag filter on list_tasks** (only assignee/priority/status/project). Add `tag`, `epic_id`, `milestone_id`. — **AP-601**
