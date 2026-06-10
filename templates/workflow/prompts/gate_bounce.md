# Your run succeeded but the task CANNOT advance — evidence is missing

You declared this task done, but the board's gate blocked the move because:

{{FAILURES}}

Close the gap now:
- For every Definition-of-Done item you genuinely completed, call
  mcp__agentira__update_task with the full dod_items list and checked: true
  on those items. Do NOT check items you did not complete.
- If something on the list is NOT done, either finish it now (commit the
  work) or leave it unchecked and explain precisely what remains in a task
  comment.
- Then call mcp__agentira__finish_run again with an honest outcome.

This is a one-time correction pass — if the task still can't advance after
this run, it will be flagged for human attention.
