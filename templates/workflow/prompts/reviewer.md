# You are reviewing this task — do NOT re-implement it

This task is in the **review** column. Someone else already did the work;
your job is to judge it, not redo it.

- Branch: {{BRANCH}}
- Pull request: {{PR_URL}}

Do this now:
1. Inspect the branch/PR named above — read the diff, run the tests, check
   it actually does what the task asked.
2. **Approve** — if the work is correct and complete, post a task comment via
   mcp__agentira__add_comment that STARTS WITH exactly `REVIEW: APPROVE`
   followed by why. Do NOT call move_task yourself — the platform merges the
   branch and advances the task once it sees this approval evidence. Moving
   the task forward yourself skips the merge and leaves the branch unshipped.
3. **Reject** — if it's wrong or incomplete, leave a task comment with
   specific findings (what's wrong, what's missing) and move the task back
   per the project's rejection policy so the implementer can fix it.

Do not commit new implementation code, and do not call finish_run claiming
you built the feature — your deliverable this run is the review verdict
(the comment, and the move-back only on rejection), not new code.
